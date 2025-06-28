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
from googleapiclient.http import MediaFileUpload

TOKEN = os.getenv("BOT_TOKEN") or "8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A"
ADMIN_ID = 7889110301
DRIVE_FOLDERS = {
    "KOSA": "1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv",
    "ALFATTAH": "1RhO9MimAvO89T9hkSyWgd0wT0zg7n1RV",
    "SUNBUD": "1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS"
}
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]

creds = Credentials.from_service_account_file('certain-axis-463420-b5-1f4f58ac6291.json', scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open("Фактуры").sheet1
drive_service = build('drive', 'v3', credentials=creds)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_data = {}
photo_storage = {}

# START
@bot.message_handler(commands=['start'])
def start(message):
    user_data[message.chat.id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for name in DRIVE_FOLDERS:
        markup.add(name)
    bot.send_message(message.chat.id, "Выберите вашу Spółkę:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in DRIVE_FOLDERS.keys())
def handle_company_choice(message):
    user_data[message.chat.id]['company'] = message.text
    bot.send_message(message.chat.id, "Введите имя и фамилию:", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda msg: 'company' in user_data.get(msg.chat.id, {}) and 'name' not in user_data[msg.chat.id])
def get_name(message):
    user_data[message.chat.id]['name'] = message.text
    bot.send_message(message.chat.id, "Теперь отправьте фото фактуры (одно или несколько).")
    photo_storage[message.chat.id] = []

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if message.chat.id not in user_data or 'name' not in user_data[message.chat.id]:
        bot.send_message(message.chat.id, "Сначала введите имя и Spółку командой /start")
        return

    file_info = bot.get_file(message.photo[-1].file_id)
    file_path = file_info.file_path
    downloaded_file = bot.download_file(file_path)

    folder_id = DRIVE_FOLDERS[user_data[message.chat.id]['company']]
    folder_name = user_data[message.chat.id]['name']

    # Создаём личную папку водителя (если ещё нет)
    response = drive_service.files().list(q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{folder_id}' in parents and trashed=false", spaces='drive').execute()
    folders = response.get('files', [])
    if folders:
        personal_folder_id = folders[0]['id']
    else:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [folder_id]
        }
        folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        personal_folder_id = folder.get('id')

    # Сохраняем временно
    ts = int(time.time())
    file_name = f"{ts}.jpg"
    with open(file_name, 'wb') as f:
        f.write(downloaded_file)

    file_metadata = {
        'name': file_name,
        'parents': [personal_folder_id]
    }
    media = MediaFileUpload(file_name, mimetype='image/jpeg')
    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id,webViewLink').execute()

    file_id = uploaded_file.get('id')
    file_url = uploaded_file.get('webViewLink')

    # Проверка на дубликаты
    all_records = sheet.get_all_records()
    for row in all_records:
        if row['URL'] == file_url:
            bot.send_message(message.chat.id, "Этот чек уже был отправлен ранее.")
            return

    # Сохраняем в Google Таблицу
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([
        user_data[message.chat.id]['name'],
        message.from_user.username,
        message.chat.id,
        user_data[message.chat.id]['company'],
        now,
        file_url
    ])

    # Уведомление админу
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"Новая фактура от {user_data[message.chat.id]['name']}")

    bot.send_message(message.chat.id, "Фактура успешно принята. Спасибо!")
    os.remove(file_name)

# Schedule напоминание

def remind_users():
    all_data = sheet.get_all_records()
    now = datetime.now()
    reminded_users = set()

    for row in reversed(all_data):
        uid = row['User ID']
        last_date = datetime.strptime(row['Время'], "%Y-%m-%d %H:%M:%S")
        if now - last_date > timedelta(days=14) and uid not in reminded_users:
            try:
                bot.send_message(uid, "Напоминание: вы не отправляли фактуру более 2 недель!")
                bot.send_message(ADMIN_ID, f"Пользователь {row['Имя']} не отправлял фактуру более 14 дней.")
                reminded_users.add(uid)
            except:
                continue

schedule.every().day.at("10:00").do(remind_users)

@app.route('/', methods=['POST'])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "", 200

if __name__ == '__main__':
    threading.Thread(target=lambda: schedule.run_pending() or time.sleep(1)).start()
    app.run(host='0.0.0.0', port=8080)



