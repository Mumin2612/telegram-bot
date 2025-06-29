import os
import json
import time
import hashlib
import logging
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

# ==== НАСТРОЙКИ ====
BOT_TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301
SPREADSHEET_NAME = 'Фактуры'
FOLDER_IDS = {
    'KOSA': '1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv',
    'ALFATTAH': '1RhO9MimAvO89T9hkSyWgd0wT0zg7n1RV',
    'SUNBUD': '1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS'
}
WEBHOOK_URL = 'https://telegram-bot-p1o6.onrender.com'  # замените

POLAND_TIME = timezone(timedelta(hours=2))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ==== Google Auth ====
credentials = Credentials.from_service_account_info(
    json.loads(os.environ['GOOGLE_CREDENTIALS_JSON']),
    scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(credentials)
sheet = gc.open(SPREADSHEET_NAME).sheet1
drive_service = build('drive', 'v3', credentials=credentials)

# ==== JSON-файл с водителями ====
USERS_FILE = 'users.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(data):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users_data = load_users()
photo_queue = {}
photo_hashes = {}

# ==== /start ====
@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = str(message.chat.id)
    if user_id in users_data:
        bot.send_message(message.chat.id, "✅ Ты уже зарегистрирован. Можешь отправлять фото прямо сейчас 📸")
        return

    user_data[message.chat.id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for company in ['KOSA', 'ALFATTAH', 'SUNBUD']:
        markup.add(types.KeyboardButton(company))
    bot.send_message(message.chat.id, "👋 Привет! Выбери свою Spółkę:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in FOLDER_IDS)
def handle_company(msg):
    user_data[msg.chat.id] = {'company': msg.text}
    bot.send_message(msg.chat.id, "✍️ Напиши своё *Имя и Фамилию*", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.chat.id in user_data and 'name' not in user_data[msg.chat.id])
def handle_name(msg):
    user_id = str(msg.chat.id)
    name = msg.text.strip()
    company = user_data[msg.chat.id]['company']
    users_data[user_id] = {
        'name': name,
        'spolka': company
    }
    save_users(users_data)
    bot.send_message(msg.chat.id, "✅ Данные сохранены! Теперь можешь отправлять фото 📸")

# ==== Обработка фото ====
@bot.message_handler(content_types=['photo'])
def handle_photo(msg):
    user_id = str(msg.chat.id)
    if user_id not in users_data:
        bot.send_message(msg.chat.id, "⚠️ Напиши /start и введи свои данные.")
        return

    file_id = msg.photo[-1].file_id
    file_info = bot.get_file(file_id)
    downloaded = bot.download_file(file_info.file_path)

    file_hash = hashlib.md5(downloaded).hexdigest()
    user_hashes = photo_hashes.setdefault(user_id, set())
    if file_hash in user_hashes:
        bot.send_message(msg.chat.id, "⚠️ Это фото уже было отправлено ранее и не будет загружено повторно.")
        return
    user_hashes.add(file_hash)

    queue = photo_queue.setdefault(user_id, {'photos': [], 'last_time': None})
    queue['photos'].append((file_id, msg, file_hash, downloaded))
    queue['last_time'] = datetime.now(POLAND_TIME)

# ==== Отправка альбома ====
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
    company = data['spolka']
    first_name, last_name = name.strip().split(maxsplit=1) if " " in name else (name.strip(), "")
    username = photos[0][1].from_user.username or "—"
    tg_id = int(user_id)
    now = datetime.now(POLAND_TIME)
    now_str = now.strftime("%Y-%m-%d %H:%M")

    folder_id_spolka = FOLDER_IDS[company]
    personal_folder_id = get_or_create_folder(name, folder_id_spolka)

    media = []
    drive_links = []

    for file_id, msg, file_hash, file_bytes in photos:
        local_path = f"{file_id}.jpg"
        with open(local_path, 'wb') as f:
            f.write(file_bytes)

        file_metadata = {'name': f"{now_str}_{file_id}.jpg", 'parents': [personal_folder_id]}
        media_upload = MediaFileUpload(local_path, mimetype='image/jpeg')
        uploaded = drive_service.files().create(body=file_metadata, media_body=media_upload, fields='id').execute()
        drive_id = uploaded.get('id')
        drive_links.append(f"https://drive.google.com/file/d/{drive_id}/view")
        os.remove(local_path)
        media.append(types.InputMediaPhoto(file_id))

    caption = f"📄 Имя: {name}\n🆔 ID: {tg_id}\n👤 Username: @{username}\n📅 Дата: {now_str}\n🏢 Spółka: {company}"
    media[0].caption = caption
    bot.send_media_group(ADMIN_ID, media)

    sheet.append_row([
        first_name, last_name, username, tg_id, now_str, company, ", ".join(drive_links)
    ])
    bot.send_message(tg_id, "✅ Фото доставлены! Спасибо 📬")

def get_or_create_folder(name, parent_id):
    query = f"'{parent_id}' in parents and name = '{name}' and mimeType = 'application/vnd.google-apps.folder'"
    result = drive_service.files().list(q=query, fields="files(id)").execute()
    if result['files']:
        return result['files'][0]['id']
    file_metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = drive_service.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')

# ==== Напоминания ====
def check_reminders():
    try:
        rows = sheet.get_all_values()[1:]
        today = datetime.now(POLAND_TIME)
        warned_users = set()

        for row in rows:
            first, last, username, user_id, date_str, company = row[:6]
            last_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            delta = today - last_date
            if delta.days >= 14 and user_id not in warned_users:
                warned_users.add(user_id)
                bot.send_message(int(user_id), "⏰ Напоминание: вы не отправляли фактуру более 14 дней.")
                bot.send_message(ADMIN_ID, f"🔔 {first} {last} ({user_id}) не отправлял фактуру {delta.days} дней.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка в напоминании:\n{e}")

def scheduler_loop():
    schedule.every().day.at("09:00").do(check_reminders)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ==== Webhook ====
@app.route('/', methods=['POST'])
def webhook():
    try:
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка webhook:\n{e}")
    return 'OK', 200

# ==== Запуск ====
if __name__ == '__main__':
    threading.Thread(target=photo_watcher, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host='0.0.0.0', port=10000)




