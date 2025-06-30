import os
import json
import time
import hashlib
import threading
from datetime import datetime, timedelta, timezone

import telebot
from telebot import types
from flask import Flask, request

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import schedule

# === НАСТРОЙКИ ===
BOT_TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301
SPREADSHEET_NAME = 'Фактуры'
FOLDER_IDS = {
    'KOSA': '1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv',
    'ALFATTAH': '1RhO9MimAvO89T9hkSyWgd0wT0zg7n1RV',
    'SUNBUD': '1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS'
}
WEBHOOK_URL = 'https://telegram-bot-p1o6.onrender.com'

# === ВРЕМЯ ===
POLAND_TIME = timezone(timedelta(hours=2))

# === ФАЙЛ ПОЛЬЗОВАТЕЛЕЙ ===
USERS_FILE = 'users.json'

# === ЗАГРУЗКА И СОХРАНЕНИЕ ===
def load_users():
    try:
        sheet_users = gc.open(SPREADSHEET_NAME).worksheet("Пользователи")
        records = sheet_users.get_all_records()
        return {str(row['user_id']): {'name': row['name'], 'spolka': row['spolka']} for row in records}
    except Exception:
        return {}

def save_user_to_sheet(user_id, name, spolka):
    try:
        sheet_users = gc.open(SPREADSHEET_NAME).worksheet("Пользователи")
        sheet_users.append_row([user_id, name, spolka])
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка при записи пользователя в лист Пользователи: {e}")

users_data = load_users()
temp_user_data = {}
photo_queue = {}
photo_hashes = {}

# === TELEGRAM + GOOGLE ===
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

credentials = Credentials.from_service_account_info(
    json.loads(os.environ['GOOGLE_CREDENTIALS_JSON']),
    scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(credentials)
sheet = gc.open(SPREADSHEET_NAME).sheet1
drive_service = build('drive', 'v3', credentials=credentials)

# === START ===
@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = str(message.chat.id)
    if user_id in users_data:
        bot.send_message(message.chat.id, "✅ Ты уже зарегистрирован. Можешь отправлять фото 📸")
        return

    temp_user_data[message.chat.id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for company in FOLDER_IDS.keys():
        markup.add(types.KeyboardButton(company))
    bot.send_message(message.chat.id, "👋 Привет! Выбери свою Spółkę:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in FOLDER_IDS)
def handle_company(msg):
    temp_user_data[msg.chat.id] = {'company': msg.text}
    bot.send_message(msg.chat.id, "✍️ Напиши своё *Имя и Фамилию*", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.chat.id in temp_user_data and 'name' not in temp_user_data[msg.chat.id])
def handle_name(msg):
    user_id = str(msg.chat.id)
    name = msg.text.strip()
    spolka = temp_user_data[msg.chat.id]['company']
    users_data[user_id] = {'name': name, 'spolka': spolka}
    save_user_to_sheet(user_id, name, spolka)
    bot.send_message(msg.chat.id, "✅ Данные сохранены. Можешь отправлять фото 📸")

# === ОБРАБОТКА ФОТО ===
@bot.message_handler(content_types=['photo'])
def handle_photo(msg):
    user_id = str(msg.chat.id)
    if user_id not in users_data:
        bot.send_message(msg.chat.id, "⚠️ Напиши /start и зарегистрируйся.")
        return

    file_id = msg.photo[-1].file_id
    file_info = bot.get_file(file_id)
    file_data = bot.download_file(file_info.file_path)

    file_hash = hashlib.md5(file_data).hexdigest()
    hashes = photo_hashes.setdefault(user_id, set())
    if file_hash in hashes:
        bot.send_message(msg.chat.id, "⚠️ Это фото уже было отправлено ранее.")
        return
    hashes.add(file_hash)

    queue = photo_queue.setdefault(user_id, {'photos': [], 'last_time': None})
    queue['photos'].append((file_id, msg, file_data))
    queue['last_time'] = datetime.now(POLAND_TIME)

# === ФОНОВАЯ ОТПРАВКА АЛЬБОМА ===
def photo_watcher():
    while True:
        now = datetime.now(POLAND_TIME)
        for user_id, queue in list(photo_queue.items()):
            if queue['last_time'] and (now - queue['last_time']).total_seconds() >= 5:
                try:
                    send_album(user_id, queue['photos'])
                except Exception as e:
                    bot.send_message(ADMIN_ID, f"❌ Ошибка при отправке альбома:\n{e}")
                del photo_queue[user_id]
        time.sleep(1)

def send_album(user_id, photos):
    data = users_data[user_id]
    name = data['name']
    spolka = data['spolka']
    first_name, last_name = name.split(maxsplit=1) if " " in name else (name, "")
    username = photos[0][1].from_user.username
    username_display = f"@{username}" if username else "—"
    tg_id = int(user_id)
    now = datetime.now(POLAND_TIME)
    now_str = now.strftime("%Y-%m-%d %H:%M")

    folder_id = FOLDER_IDS[spolka]
    personal_folder_id = get_or_create_folder(name, folder_id)

    media = []
    drive_links = []

    for file_id, msg, file_data in photos:
        path = f"{file_id}.jpg"
        with open(path, 'wb') as f:
            f.write(file_data)

        metadata = {'name': f"{now_str}_{file_id}.jpg", 'parents': [personal_folder_id]}
        media_upload = MediaFileUpload(path, mimetype='image/jpeg')
        file = drive_service.files().create(body=metadata, media_body=media_upload, fields='id').execute()
        drive_links.append(f"https://drive.google.com/file/d/{file['id']}/view")
        os.remove(path)
        media.append(types.InputMediaPhoto(file_id))

    # Отправка альбома админу
    caption = f"📄 Имя: {name}\n🆔 ID: {tg_id}\n👤 {username_display}\n📅 {now_str}\n🏢 {spolka}"
    media[0].caption = caption
    bot.send_media_group(ADMIN_ID, media)

    # Запись в основной лист (Фактуры)
    sheet.append_row([first_name, last_name, username or "—", tg_id, now_str, spolka, ", ".join(drive_links)])

    # Запись в лист "Пользователи"
    try:
        users_sheet = gc.open(SPREADSHEET_NAME).worksheet("Пользователи")
        users_sheet.append_row([tg_id, name, spolka])
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка при записи пользователя в лист Пользователи:\n{e}")

    # Ответ водителю
    bot.send_message(tg_id, "✅ Фото доставлены! Спасибо 📬")

def get_or_create_folder(name, parent_id):
    query = f"'{parent_id}' in parents and name='{name}' and mimeType='application/vnd.google-apps.folder'"
    result = drive_service.files().list(q=query, fields="files(id)").execute()
    if result['files']:
        return result['files'][0]['id']
    metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = drive_service.files().create(body=metadata, fields='id').execute()
    return folder['id']

# === НАПОМИНАНИЯ ===
def check_reminders():
    try:
        rows = sheet.get_all_values()[1:]
        today = datetime.now(POLAND_TIME)
        warned = set()
        for row in rows:
            if len(row) < 6: continue
            first, last, username, user_id, date_str, spolka = row[:6]
            last_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            if (today - last_date).days >= 14 and user_id not in warned:
                warned.add(user_id)
                bot.send_message(int(user_id), "⏰ Напоминание: вы не отправляли фактуру более 14 дней.")
                bot.send_message(ADMIN_ID, f"🔔 {first} {last} ({user_id}) — {spolka} не отправлял фактуру.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка напоминания:\n{e}")

def scheduler_loop():
    schedule.every().day.at("09:00").do(check_reminders)
    while True:
        schedule.run_pending()
        time.sleep(60)

# === WEBHOOK ===
@app.route('/', methods=['POST'])
def webhook():
    try:
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка webhook:\n{e}")
    return 'OK', 200

# === СТАРТ ===
if __name__ == '__main__':
    threading.Thread(target=photo_watcher, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host='0.0.0.0', port=10000)




