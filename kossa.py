# Файл: kossa.py

import telebot
from telebot import types
from flask import Flask
from datetime import datetime, timedelta
import threading
import os
import io
import requests
import hashlib
import schedule
import time

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

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
user_photos = {}
user_data = {}
photo_hashes = set()

# === Google API ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_name("certain-axis-463420-b5-1f4f58ac6291.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Фактуры").sheet1
drive_service = build("drive", "v3", credentials=creds)

# === Утилиты ===
def notify_admin_error(user_id, username, error_text):
    try:
        user_link = f"@{username}" if username else f"[\u043f\u0440\u043e\u0444\u0438\u043b\u044c](tg://user?id={user_id})"
        bot.send_message(ADMIN_ID, f"❗ Ошибка у {user_link} (ID: {user_id}):\n```\n{error_text}\n```", parse_mode="Markdown")
    except: pass

def escape_markdown(text):
    return ''.join(['\\' + c if c in r"_*[]()~`>#+-=|{}.!\\>" else c for c in text])

def build_caption(user_id):
    info = user_data[user_id]
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_link = f"@{info['username']}" if info['username'] else f"[\u043f\u0440\u043e\u0444\u0438\u043b\u044c](tg://user?id={user_id})"
    return f"📸 Фото\n👤 {escape_markdown(info['first_name'])} {escape_markdown(info['last_name'])}\n🔗 {user_link}\n🆔 ID: {user_id}\n🏢 Spółka: {info['company']}\n🕒 {timestamp}"

def get_or_create_driver_folder(company_id, full_name):
    query = f"'{company_id}' in parents and name = '{full_name}' and mimeType = 'application/vnd.google-apps.folder'"
    response = drive_service.files().list(q=query, fields='files(id)').execute()
    files = response.get('files', [])
    if files:
        return files[0]['id']
    file_metadata = {
        'name': full_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [company_id]
    }
    folder = drive_service.files().create(body=file_metadata, fields='id').execute()
    return folder['id']

# === Обработка команд ===
@bot.message_handler(commands=['start'])
def start_message(message):
    user_id = message.from_user.id
    user_data[user_id] = {
        "username": message.from_user.username or "",
        "telegram_id": user_id
    }
    bot.send_message(user_id, "👋 Привет! Напиши своё имя и фамилию.")
    user_data[user_id]["state"] = "waiting_name"

@bot.message_handler(func=lambda m: user_data.get(m.from_user.id, {}).get("state") == "waiting_name")
def handle_name(message):
    user_id = message.from_user.id
    parts = message.text.strip().split(" ", 1)
    user_data[user_id]["first_name"] = parts[0]
    user_data[user_id]["last_name"] = parts[1] if len(parts) > 1 else ""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("KOSA", "ALFATTAH", "SUNBUD")
    bot.send_message(user_id, "Теперь выбери свою Spółkę:", reply_markup=markup)
    user_data[user_id]["state"] = "waiting_company"

@bot.message_handler(func=lambda m: user_data.get(m.from_user.id, {}).get("state") == "waiting_company")
def handle_company(message):
    user_id = message.from_user.id
    company = message.text.strip().upper()
    if company not in FOLDER_IDS:
        bot.send_message(user_id, "Выбери Spółkę из списка.")
        return
    user_data[user_id]["company"] = company
    user_data[user_id]["state"] = "ready"
    bot.send_message(user_id, "✅ Данные сохранены. Можешь отправлять фото.", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.from_user.id
    info = user_data.get(user_id)
    if not info or "company" not in info:
        bot.send_message(user_id, "Сначала нажми /start и выбери Spółkę.")
        return
    file_id = message.photo[-1].file_id
    try:
        file_info = bot.get_file(file_id)
        file_url = f'https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}'
        content = requests.get(file_url).content
        content_hash = hashlib.md5(content).hexdigest()
        if content_hash in photo_hashes:
            bot.send_message(user_id, "⛔ Такое фото уже отправляли.")
            return
        photo_hashes.add(content_hash)
        if not file_info.file_path.lower().endswith((".jpg", ".jpeg", ".png")):
    bot.send_message(user_id, "⛔ Только фото чеков/фактуры.")
    return

        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        full_name = f"{info['first_name']} {info['last_name']}"
        folder_id = get_or_create_driver_folder(FOLDER_IDS[info['company']], full_name)

        file_stream = io.BytesIO(content)
        media = MediaIoBaseUpload(file_stream, mimetype='image/jpeg')
        file_metadata = {
            'name': f'{full_name}_{timestamp.replace(" ", "_")}.jpg',
            'parents': [folder_id]
        }
        uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        drive_link = f"https://drive.google.com/file/d/{uploaded['id']}/view?usp=sharing"

        caption = build_caption(user_id)
        bot.send_photo(ADMIN_ID, photo=file_id, caption=caption, parse_mode="Markdown")
        bot.send_message(user_id, "✅ Фото получено.")

        sheet.append_row([info['first_name'], info['last_name'], info['username'], user_id, timestamp, info['company'], drive_link])

    except Exception as e:
        notify_admin_error(user_id, info.get("username", ""), str(e))
        bot.send_message(user_id, "⚠️ Ошибка при обработке фото.")

# === Напоминания ===
def check_inactive_users():
    try:
        records = sheet.get_all_records()
        now = datetime.now()
        user_latest = {}
        for row in records:
            uid = str(row['Telegram ID'])
            date = datetime.strptime(row['Дата'], '%Y-%m-%d %H:%M:%S')
            if uid not in user_latest or user_latest[uid] < date:
                user_latest[uid] = date
        for uid, last in user_latest.items():
            diff = now - last
            if diff > timedelta(days=14):
                bot.send_message(int(uid), "⏰ Напоминание: вы не отправляли фактуру более 2 недель.")
                bot.send_message(ADMIN_ID, f"🔔 Водитель ID {uid} не отправлял фактуру {diff.days} дней.")
    except Exception as e:
        notify_admin_error("system", "schedule", str(e))

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(60)

schedule.every().day.at("03:00").do(check_inactive_users)
threading.Thread(target=run_schedule, daemon=True).start()

# === Flask (Render) ===
@app.route('/')
def index():
    return 'Bot is running!'

def run_bot():
    bot.infinity_polling()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
else:
    threading.Thread(target=run_bot).start()


