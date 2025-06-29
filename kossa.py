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

BOT_TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301
SPREADSHEET_NAME = 'Фактуры'
FOLDER_IDS = {
    'KOSA': '1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv',
    'ALFATTAH': '1RhO9MimAvO89T9hkSyWgd0wT0zg7n1RV',
    'SUNBUD': '1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS'
}
WEBHOOK_URL = 'https://telegram-bot-p1o6.onrender.com'

POLAND_TIME = timezone(timedelta(hours=2))
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

credentials = Credentials.from_service_account_info(
    json.loads(os.environ['GOOGLE_CREDENTIALS_JSON']),
    scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(credentials)
sheet = gc.open(SPREADSHEET_NAME).sheet1
drive_service = build('drive', 'v3', credentials=credentials)

user_data = {}
photo_queue = {}
photo_hashes = {}

@bot.message_handler(commands=['start'])
def start_handler(message):
    user_data[message.chat.id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for company in ['KOSA', 'ALFATTAH', 'SUNBUD']:
        markup.add(types.KeyboardButton(company))
    bot.send_message(message.chat.id, "👋 Привет! Выбери свою Spółkę:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in FOLDER_IDS)
def handle_company(msg):
    user_data[msg.chat.id]['company'] = msg.text
    bot.send_message(msg.chat.id, "✍️ Напиши своё *Имя и Фамилию*", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: 'company' in user_data.get(msg.chat.id, {}) and 'name' not in user_data.get(msg.chat.id, {}))
def handle_name(msg):
    user_data[msg.chat.id]['name'] = msg.text
    bot.send_message(msg.chat.id, "📸 Теперь отправь фото фактуры (можно несколько подряд)")

@bot.message_handler(content_types=['photo'])
def handle_photo(msg):
    if 'name' not in user_data.get(msg.chat.id, {}):
        bot.send_message(msg.chat.id, "⚠️ Сначала введи /start, выбери Spółkę и своё имя.")
        return

    file_id = msg.photo[-1].file_id
    file_info = bot.get_file(file_id)
    downloaded = bot.download_file(file_info.file_path)

    file_hash = hashlib.md5(downloaded).hexdigest()
    user_hashes = photo_hashes.setdefault(msg.chat.id, set())

    if file_hash in user_hashes:
        bot.send_message(msg.chat.id, "⚠️ Это фото уже было отправлено ранее и не будет загружено повторно.")
        return

    user_hashes.add(file_hash)
    queue = photo_queue.setdefault(msg.chat.id, {'photos': [], 'last_time': None})
    queue['photos'].append((file_id, msg, file_hash, downloaded))
    queue['last_time'] = datetime.now(POLAND_TIME)

def photo_watcher():
    while True:
        now = datetime.now(POLAND_TIME)
        for chat_id, queue in list(photo_queue.items()):
            if queue['last_time'] and (now - queue['last_time']).total_seconds() >= 5:
                try:
                    send_album(chat_id, queue['photos'])
                except Exception as e:
                    bot.send_message(ADMIN_ID, f"❌ Ошибка при отправке альбома:\n{e}")
                del photo_queue[chat_id]
        time.sleep(1)

def send_album(chat_id, photos):
    user = user_data[chat_id]
    name = user['name']
    company = user['company']
    username = photos[0][1].from_user.username or "—"
    user_id = photos[0][1].from_user.id
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

    caption = f"📄 Имя: {name}\n🆔 ID: {user_id}\n👤 Username: @{username}\n📅 Дата: {now_str}\n🏢 Spółka: {company}"
    media[0].caption = caption
    bot.send_media_group(ADMIN_ID, media)

    sheet.append_row([name, user_id, username, now_str, company, ", ".join(drive_links)])

def get_or_create_folder(name, parent_id):
    query = f"'{parent_id}' in parents and name = '{name}' and mimeType = 'application/vnd.google-apps.folder'"
    result = drive_service.files().list(q=query, fields="files(id)").execute()
    if result['files']:
        return result['files'][0]['id']
    else:
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

def check_reminders():
    try:
        rows = sheet.get_all_values()[1:]
        today = datetime.now(POLAND_TIME)

        warned_users = set()

        for row in rows:
            name, user_id, username, date_str, company = row[:5]
            last_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            delta = today - last_date
            if delta.days >= 14 and user_id not in warned_users:
                warned_users.add(user_id)
                bot.send_message(int(user_id), "⏰ Напоминание: вы не отправляли фактуру более 14 дней.")
                bot.send_message(ADMIN_ID, f"🔔 {name} ({user_id}) не отправлял фактуру {delta.days} дней.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка в check_reminders:\n{e}")

def scheduler_loop():
    schedule.every().day.at("09:00").do(check_reminders)
    while True:
        schedule.run_pending()
        time.sleep(60)

@app.route('/', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка webhook:\n{e}")
    return 'OK', 200

if __name__ == '__main__':
    threading.Thread(target=photo_watcher, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host='0.0.0.0', port=10000)




