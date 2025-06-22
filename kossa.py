import telebot
from googleapiclient.discovery import build
from telebot import types
from flask import Flask
from datetime import datetime
import threading
import os

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.http import MediaIoBaseUpload
import io
import requests

# === НАСТРОЙКИ ===
TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301
GOOGLE_FOLDER_ID = '1owM3Tx_MtX3aTqKSX1N0DfFQSkTXECI0'  # ID папки на Google Drive

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
user_photos = {}
user_timers = {}
user_states = {}
user_data = {}

# === Google API настройка ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_name("certain-axis-463420-b5-1f4f58ac6291.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Фактуры").sheet1
drive_service = build("drive", "v3", credentials=creds)

# === Уведомление администратора об ошибке ===
def notify_admin_error(user_id, username, error_text):
    try:
        user_link = f"@{username}" if username else f"[профиль](tg://user?id={user_id})"
        bot.send_message(ADMIN_ID, f"❗ Ошибка у пользователя {user_link} (ID: {user_id}):\n\n```\n{error_text}\n```", parse_mode="Markdown")
    except Exception as err:
        print(f"Ошибка при уведомлении администратора: {err}")

# === Утилиты ===
def escape_markdown(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!\\"
    return ''.join(['\\' + char if char in escape_chars else char for char in text])

def build_caption(user_id):
    info = user_data.get(user_id, {})
    first_name = escape_markdown(info.get("first_name", ""))
    last_name = escape_markdown(info.get("last_name", ""))
    username = escape_markdown(info.get("username", ""))
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_link = f"@{username}" if username else f"[профиль](tg://user?id={user_id})"
    return f"📸 Новые фото\n👤 Имя: {first_name} {last_name}\n🔗 {user_link}\n🆔 ID: {user_id}\n🕒 Время: {timestamp}"

# === Отправка альбома и запись в Google Таблицу ===
def send_album(user_id, message):
    try:
        info = user_data.get(user_id, {})
        first_name = info.get("first_name", "")
        last_name = info.get("last_name", "")
        username = info.get("username", "")
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        media_files = user_photos.get(user_id, [])
        media_group = []
        drive_links = []

        for i, file_id in enumerate(media_files):
            try:
                file_info = bot.get_file(file_id)
                file_url = f'https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}'
                file_content = requests.get(file_url).content

                file_stream = io.BytesIO(file_content)
                media = MediaIoBaseUpload(file_stream, mimetype='image/jpeg')
                file_metadata = {
                    'name': f'{first_name}_{last_name}_{timestamp.replace(" ", "_")}_{i+1}.jpg',
                    'parents': [GOOGLE_FOLDER_ID]
                }

                uploaded_file = drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()

                file_id_on_drive = uploaded_file.get('id')
                drive_link = f'https://drive.google.com/file/d/{file_id_on_drive}/view?usp=sharing'
                drive_links.append(drive_link)

                if i == 0:
                    media_group.append(types.InputMediaPhoto(media=file_id, caption=build_caption(user_id), parse_mode="Markdown"))
                else:
                    media_group.append(types.InputMediaPhoto(media=file_id))

            except Exception as e:
                notify_admin_error(user_id, username, f"Ошибка обработки фото {i+1}: {str(e)}")

        try:
            if media_group:
                bot.send_media_group(ADMIN_ID, media_group)
                bot.send_message(user_id, "✅ Спасибо! Фото отправлены.")
            else:
                bot.send_message(user_id, "⚠️ Не удалось отправить фото администратору.")

            for link in drive_links:
                sheet.append_row([first_name, last_name, username, user_id, timestamp, link])

        except Exception as e:
            notify_admin_error(user_id, username, f"Ошибка при отправке альбома или записи в таблицу: {str(e)}")
            bot.send_message(user_id, "⚠️ Произошла ошибка при отправке фото или записи в таблицу.")

        user_photos.pop(user_id, None)
        user_timers.pop(user_id, None)
        user_states.pop(user_id, None)
        user_data.pop(user_id, None)

    except Exception as e:
        notify_admin_error(user_id, user_data.get(user_id, {}).get("username", ""), f"Ошибка в send_album: {str(e)}")

# === Хендлеры ===
@bot.message_handler(commands=['start'])
def start_message(message):
    try:
        user_id = message.from_user.id
        bot.send_message(user_id, "👋 Привет! Напиши, пожалуйста, своё имя и фамилию перед отправкой фото.")
        user_states[user_id] = 'waiting_for_name'
        user_data[user_id] = {
            "username": message.from_user.username or "",
            "telegram_id": user_id
        }
    except Exception as e:
        notify_admin_error(message.from_user.id, message.from_user.username, f"Ошибка в /start: {str(e)}")

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'waiting_for_name')
def save_name(message):
    try:
        user_id = message.from_user.id
        name_parts = message.text.strip().split(" ", 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""
        user_data[user_id]["first_name"] = first_name
        user_data[user_id]["last_name"] = last_name
        user_states[user_id] = 'ready_for_photos'
        bot.send_message(user_id, "✅ Имя сохранено. Теперь отправь одно или несколько фото подряд.")
    except Exception as e:
        notify_admin_error(message.from_user.id, message.from_user.username, f"Ошибка при сохранении имени: {str(e)}")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    try:
        user_id = message.from_user.id

        if user_states.get(user_id) != 'ready_for_photos':
            bot.send_message(user_id, "Сначала напиши своё имя и фамилию. Отправь /start.")
            return

        file_id = message.photo[-1].file_id
        user_photos.setdefault(user_id, []).append(file_id)

        if user_id in user_timers:
            user_timers[user_id].cancel()

        user_timers[user_id] = threading.Timer(5.0, send_album, args=(user_id, message))
        user_timers[user_id].start()
    except Exception as e:
        notify_admin_error(message.from_user.id, message.from_user.username, f"Ошибка при приёме фото: {str(e)}")

# === Flask для Render ===
@app.route('/')
def index():
    return 'Бот работает!'

def run_bot():
    bot.infinity_polling()

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)

