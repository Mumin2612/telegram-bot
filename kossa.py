import telebot
from telebot import types
from flask import Flask, request
import time
import hashlib
import os
import json
import gspread
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from threading import Thread
import schedule

TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301
DRIVE_FOLDER_ID = '1owM3Tx_MtX3aTqKSX1N0DfFQSkTXECI0'
SPOLKI = {
    "KOSA": '1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv',
    "ALFATTAH": '1RhO9MimAvO89T9hkSyWgd0wT0zg7N1RV',
    "SUNBUD": '1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS'
}
TABLE_NAME = 'Фактуры'

bot = telebot.TeleBot(TOKEN, threaded=True)
app = Flask(__name__)

user_data = {}
sent_hashes = set()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_file('certain-axis-463420-b5-1f4f58ac6291.json', scopes=SCOPES)
gsheet = gspread.authorize(creds)
sheet = gsheet.open(TABLE_NAME).sheet1
drive_service = build('drive', 'v3', credentials=creds)


def get_or_create_user_folder(full_name, spolka_folder_id):
    query = f"'{spolka_folder_id}' in parents and name = '{full_name}' and trashed = false"
    results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    items = results.get('files', [])
    if items:
        return items[0]['id']
    file_metadata = {
        'name': full_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [spolka_folder_id]
    }
    folder = drive_service.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')


def save_to_drive(file_path, full_name, spolka):
    folder_id = get_or_create_user_folder(full_name, SPOLKI[spolka])
    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = {'mimeType': 'image/jpeg', 'body': open(file_path, 'rb')}
    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = uploaded_file.get('id')
    drive_service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
    return f"https://drive.google.com/file/d/{file_id}/view"


def save_to_sheet(full_name, user_id, username, spolka, url):
    sheet.append_row([full_name, user_id, username, spolka, url, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])


def get_last_send_date(user_id):
    records = sheet.get_all_records()
    for row in reversed(records):
        if str(row['Telegram ID']) == str(user_id):
            return datetime.strptime(row['Дата'], '%Y-%m-%d %H:%M:%S')
    return None


@bot.message_handler(commands=['start'])
def start(message):
    user_data[message.chat.id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for spolka in SPOLKI:
        markup.add(spolka)
    bot.send_message(message.chat.id, "Выбери Spółkę:", reply_markup=markup)


@bot.message_handler(func=lambda msg: msg.text in SPOLKI)
def select_spolka(message):
    user_data[message.chat.id]['spolka'] = message.text
    bot.send_message(message.chat.id, "Теперь введи имя и фамилию:", reply_markup=types.ReplyKeyboardRemove())


@bot.message_handler(func=lambda msg: 'spolka' in user_data.get(msg.chat.id, {}) and 'name' not in user_data[msg.chat.id])
def save_name(message):
    user_data[message.chat.id]['name'] = message.text
    bot.send_message(message.chat.id, "Отправь фото фактуры.")


@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.chat.id
    if user_id not in user_data or 'name' not in user_data[user_id] or 'spolka' not in user_data[user_id]:
        bot.send_message(user_id, "Сначала напиши /start и выбери Spółkę и имя.")
        return

    file_id = message.photo[-1].file_id
    file_info = bot.get_file(file_id)
    file_path = file_info.file_path

    if not file_path.lower().endswith(('.jpg', '.jpeg', '.png')):
        bot.send_message(user_id, "⛔ Только фото чеков/фактуры.")
        return

    file_hash = hashlib.md5(file_path.encode()).hexdigest()
    if file_hash in sent_hashes:
        bot.send_message(user_id, "⛔ Эта фактура уже была отправлена.")
        return
    sent_hashes.add(file_hash)

    downloaded_file = bot.download_file(file_path)
    local_filename = f"{file_id}.jpg"
    with open(local_filename, 'wb') as f:
        f.write(downloaded_file)

    full_name = user_data[user_id]['name']
    spolka = user_data[user_id]['spolka']
    drive_url = save_to_drive(local_filename, full_name, spolka)

    save_to_sheet(full_name, user_id, message.from_user.username, spolka, drive_url)

    bot.send_message(user_id, "✅ Фактура получена и сохранена.")
    bot.send_message(ADMIN_ID, f"📥 Новая фактура от {full_name}\n{drive_url}")
    os.remove(local_filename)


@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok"


@app.route('/')
def index():
    return "Bot is running."


def check_reminders():
    records = sheet.get_all_records()
    now = datetime.now()
    reminded_users = set()
    for row in records:
        user_id = int(row['Telegram ID'])
        name = row['Имя и фамилия']
        date_str = row['Дата']
        if user_id in reminded_users:
            continue
        last_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        if now - last_date > timedelta(days=14):
            try:
                bot.send_message(user_id, f"⏰ Напоминание: Вы не отправляли фактуру более 14 дней!")
                bot.send_message(ADMIN_ID, f"⚠️ {name} не отправлял фактуру более 14 дней.")
                reminded_users.add(user_id)
            except Exception as e:
                print(f"Ошибка при отправке напоминания: {e}")


def run_scheduler():
    schedule.every().day.at("10:00").do(check_reminders)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    Thread(target=run_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)


