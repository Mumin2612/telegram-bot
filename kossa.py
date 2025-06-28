import telebot
from telebot import types
from flask import Flask, request
import os
import json
import time
from datetime import datetime, timedelta
import threading
import schedule
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

TOKEN = os.getenv("BOT_TOKEN") or "8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A"
ADMIN_ID = 7889110301
WEBHOOK_URL = 'https://telegram-bot-p1o6.onrender.com'
DRIVE_PARENT_FOLDER = {
    "KOSA": "1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv",
    "ALFATTAH": "1RhO9MimAvO89T9hkSyWgd0wT0zg7n1RV",
    "SUNBUD": "1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS"
}
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
import io
creds = Credentials.from_service_account_file("telegrambot-463419-2dccdb710642.json", scopes=SCOPES)
creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
gsheet = gspread.authorize(creds)
sheet = gsheet.open("Фактуры").sheet1
drive_service = build('drive', 'v3', credentials=creds)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_data = {}
user_photos = {}
last_upload_time = {}

@app.route('/', methods=['POST', 'GET'])
def webhook():
    if request.method == 'POST':
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return 'OK', 200
    else:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        return 'Webhook set', 200

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Привет! Введи своё имя и фамилию:")
    user_data[message.chat.id] = {'step': 'name'}

@bot.message_handler(func=lambda msg: msg.chat.id in user_data and user_data[msg.chat.id]['step'] == 'name')
def get_name(msg):
    user_data[msg.chat.id]['name'] = msg.text.strip()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("KOSA", "ALFATTAH", "SUNBUD")
    bot.send_message(msg.chat.id, "Выбери свою Spółkę:", reply_markup=markup)
    user_data[msg.chat.id]['step'] = 'spolka'

@bot.message_handler(func=lambda msg: msg.chat.id in user_data and user_data[msg.chat.id]['step'] == 'spolka')
def get_spolka(msg):
    if msg.text not in DRIVE_PARENT_FOLDER:
        bot.send_message(msg.chat.id, "Пожалуйста, выбери одну из кнопок: KOSA, ALFATTAH или SUNBUD")
        return
    user_data[msg.chat.id]['spolka'] = msg.text
    user_data[msg.chat.id]['step'] = 'done'
    bot.send_message(msg.chat.id, "Теперь можешь отправлять фото-фактуры!", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if message.chat.id not in user_data or user_data[message.chat.id].get('step') != 'done':
        bot.send_message(message.chat.id, "Сначала напиши /start и введи данные")
        return

    user_photos.setdefault(message.chat.id, []).append(message.photo[-1].file_id)
    last_upload_time[message.chat.id] = time.time()

@bot.message_handler(func=lambda m: True)
def reset_state(m):
    if m.chat.id not in user_data:
        bot.send_message(m.chat.id, "Напиши /start чтобы начать")


def upload_photos_periodically():
    while True:
        now = time.time()
        for uid, photos in list(user_photos.items()):
            if photos and now - last_upload_time.get(uid, now) > 5:
                try:
                    upload_photos(uid, photos)
                    user_photos[uid] = []
                except Exception as e:
                    bot.send_message(ADMIN_ID, f"Ошибка при загрузке фото: {e}")
        time.sleep(2)

def upload_photos(uid, file_ids):
    user = user_data[uid]
    name = user['name']
    spolka = user['spolka']
    username = f"@{bot.get_chat(uid).username}" if bot.get_chat(uid).username else "-"
    user_id = uid
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

    folder_id = get_or_create_folder(name, DRIVE_PARENT_FOLDER[spolka])
    links = []
    media = []

    for file_id in file_ids:
        file = bot.get_file(file_id)
        downloaded = bot.download_file(file.file_path)
        file_name = f"{name}_{file_id[-6:]}.jpg"
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        media_body = {'name': file_name, 'mimeType': 'image/jpeg'}
        media_upload = drive_service.files().create(media_body=file_metadata, media=googleapiclient.http.MediaIoBaseUpload(io.BytesIO(downloaded), mimetype='image/jpeg')).execute()
        file_link = f"https://drive.google.com/file/d/{media_upload['id']}/view"
        links.append(file_link)
        media.append(types.InputMediaPhoto(media=file_id))

    caption = f"Имя: {name}\nUser: {username}\nID: {user_id}\nSpółka: {spolka}\nВремя: {timestamp}"
    bot.send_media_group(ADMIN_ID, media)
    sheet.append_row([name, username, user_id, spolka, timestamp, *links])

def get_or_create_folder(folder_name, parent_id):
    query = f"'{parent_id}' in parents and name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, spaces='drive').execute()
    if results['files']:
        return results['files'][0]['id']
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
    return folder['id']

def check_reminders():
    try:
        records = sheet.get_all_records()
        now = datetime.now()
        reminded = set()
        for row in records[::-1]:
            uid = row['user_id']
            date_str = row['дата'] if 'дата' in row else row['timestamp']
            dt = datetime.strptime(date_str, "%d.%m.%Y %H:%M")
            if (now - dt).days > 14 and uid not in reminded:
                reminded.add(uid)
                bot.send_message(uid, "Напоминаем: вы не отправляли фактуру более 14 дней")
                bot.send_message(ADMIN_ID, f"{row['имя']} не отправлял фактуру более 14 дней")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"Ошибка при проверке напоминаний: {e}")

schedule.every().day.at("09:00").do(check_reminders)

if __name__ == '__main__':
    threading.Thread(target=upload_photos_periodically).start()
    threading.Thread(target=lambda: schedule.run_pending()).start()
    app.run(host='0.0.0.0', port=8080)




