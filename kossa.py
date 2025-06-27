# === БИБЛИОТЕКИ ===
import telebot
from telebot import types
from flask import Flask
from datetime import datetime, timedelta
import threading
import os
import io
import requests
import hashlib

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# === НАСТРОЙКИ ===
TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301
FOLDER_IDS = {
    'KOSA': '1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv',
    'ALFATTAH': '1RhO9MimAvO89T9hkSyWgd0wT0zg7N1RV',
    'SUNBUD': '1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS'
}

# === INIT ===
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
user_photos = {}
user_timers = {}
user_states = {}
user_data = {}
photo_hashes = set()

# === GOOGLE API ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("certain-axis-463420-b5-1f4f58ac6291.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Фактуры").sheet1
drive_service = build("drive", "v3", credentials=creds)

# === УТИЛИТЫ ===
def escape_markdown(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!\\"
    return ''.join(['\\' + c if c in escape_chars else c for c in text])

def build_caption(user_id):
    info = user_data.get(user_id, {})
    name = escape_markdown(info.get("first_name", "") + " " + info.get("last_name", ""))
    username = escape_markdown(info.get("username", ""))
    spolka = info.get("spolka", "")
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_link = f"@{username}" if username else f"[профиль](tg://user?id={user_id})"
    return f"\ud83d\udcf8 Новые фото\n\ud83d\udc64 Имя: {name}\n\ud83d\udd17 {user_link}\n\ud83c\udfe2 Sp\u00f3\u0142ka: {spolka}\n\ud83c\udd94 ID: {user_id}\n\ud83d\udd52 Время: {timestamp}"

def notify_admin_error(user_id, username, error_text):
    try:
        link = f"@{username}" if username else f"[профиль](tg://user?id={user_id})"
        bot.send_message(ADMIN_ID, f"❗ Ошибка у {link} (ID: {user_id}):\n```\n{error_text}\n```", parse_mode="Markdown")
    except: pass

def file_is_duplicate(content):
    hash_val = hashlib.sha256(content).hexdigest()
    if hash_val in photo_hashes:
        return True
    photo_hashes.add(hash_val)
    return False

# === ОБРАБОТКА И ОТПРАВКА ===
def send_album(user_id, message):
    try:
        info = user_data.get(user_id, {})
        first_name = info.get("first_name", "")
        last_name = info.get("last_name", "")
        username = info.get("username", "")
        spolka = info.get("spolka", "")
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        folder_id = FOLDER_IDS.get(spolka)
        
        media_files = user_photos.get(user_id, [])
        media_group = []
        drive_links = []

        for i, file_id in enumerate(media_files):
            try:
                file_info = bot.get_file(file_id)
                file_url = f'https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}'
                file_content = requests.get(file_url).content

                if file_is_duplicate(file_content):
                    continue

                # === Google Drive ===
                file_stream = io.BytesIO(file_content)
                media = MediaIoBaseUpload(file_stream, mimetype='image/jpeg')
                file_metadata = {
                    'name': f'{first_name}_{last_name}_{timestamp.replace(" ", "_")}_{i+1}.jpg',
                    'parents': [folder_id]
                }
                uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                link = f'https://drive.google.com/file/d/{uploaded.get("id")}/view?usp=sharing'
                drive_links.append(link)

                if i == 0:
                    media_group.append(types.InputMediaPhoto(media=file_id, caption=build_caption(user_id), parse_mode="Markdown"))
                else:
                    media_group.append(types.InputMediaPhoto(media=file_id))

            except Exception as e:
                notify_admin_error(user_id, username, f"Фото {i+1}: {str(e)}")

        if media_group:
            bot.send_media_group(ADMIN_ID, media_group)
            bot.send_message(user_id, "✅ Спасибо! Фото отправлены.")
        else:
            bot.send_message(user_id, "⚠️ Не удалось отправить фото. Возможно, это были дубликаты.")

        for link in drive_links:
            sheet.append_row([first_name, last_name, username, user_id, timestamp, spolka, link])

    except Exception as e:
        notify_admin_error(user_id, username, f"send_album: {str(e)}")

    user_photos.pop(user_id, None)
    user_timers.pop(user_id, None)
    user_states.pop(user_id, None)

# === ОБРАБОТКА СООБЩЕНИЙ ===
@bot.message_handler(commands=['start'])
def start_message(message):
    try:
        user_id = message.from_user.id
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("KOSA", "ALFATTAH", "SUNBUD")
        bot.send_message(user_id, "👋 Привет! Выбери свою Spółkę:", reply_markup=markup)
        user_states[user_id] = 'waiting_for_spolka'
        user_data[user_id] = {
            "username": message.from_user.username or "",
            "telegram_id": user_id
        }
    except Exception as e:
        notify_admin_error(user_id, message.from_user.username, f"start: {str(e)}")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == 'waiting_for_spolka')
def save_spolka(message):
    user_id = message.from_user.id
    if message.text not in FOLDER_IDS:
        bot.send_message(user_id, "Пожалуйста, выбери Spółkę из кнопок.")
        return
    user_data[user_id]["spolka"] = message.text
    user_states[user_id] = 'waiting_for_name'
    bot.send_message(user_id, "Теперь напиши своё имя и фамилию (например: Мумин Мумин)")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == 'waiting_for_name')
def save_name(message):
    try:
        user_id = message.from_user.id
        parts = message.text.strip().split(" ", 1)
        user_data[user_id]["first_name"] = parts[0]
        user_data[user_id]["last_name"] = parts[1] if len(parts) > 1 else ""
        user_states[user_id] = 'ready_for_photos'
        bot.send_message(user_id, "✅ Данные сохранены. Отправь фото фактур.")
    except Exception as e:
        notify_admin_error(user_id, message.from_user.username, f"save_name: {str(e)}")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    try:
        user_id = message.from_user.id
        info = user_data.get(user_id)
        if not info or "first_name" not in info or "last_name" not in info or "spolka" not in info:
            bot.send_message(user_id, "Пожалуйста, начни с /start и введи свои данные.")
            return

        file_id = message.photo[-1].file_id
        user_photos.setdefault(user_id, []).append(file_id)

        if user_id in user_timers:
            user_timers[user_id].cancel()

        user_timers[user_id] = threading.Timer(3.0, send_album, args=(user_id, message))
        user_timers[user_id].start()

    except Exception as e:
        notify_admin_error(user_id, message.from_user.username, f"handle_photos: {str(e)}")

# === FLASK ===
@app.route('/')
def index():
    return 'Бот работает!'

def run_bot():
    bot.infinity_polling()

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
