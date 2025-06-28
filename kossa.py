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
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
PARENT_FOLDERS = {
    "KOSA": "1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv",
    "ALFATTAH": "1RhO9MimAvO89T9hkSyWgd0wT0zg7n1RV",
    "SUNBUD": "1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS"
}

WEBHOOK_URL = 'https://telegram-bot-p1o6.onrender.com'

creds = Credentials.from_service_account_file('certain-axis-463420-b5-1f4f58ac6291.json', scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open("Фактуры").sheet1
drive_service = build('drive', 'v3', credentials=creds)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_states = {}
photo_buffers = {}

@app.route('/', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '!', 200
    else:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        return 'Webhook set!', 200

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_states[message.from_user.id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for company in PARENT_FOLDERS.keys():
        markup.add(types.KeyboardButton(company))
    bot.send_message(message.chat.id, "Выберите Spółkę:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in PARENT_FOLDERS.keys())
def handle_company_selection(message):
    user_id = message.from_user.id
    user_states[user_id]["company"] = message.text
    bot.send_message(message.chat.id, "Введите своё имя и фамилию:")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_name(message):
    user_id = message.from_user.id
    if "company" in user_states.get(user_id, {}):
        user_states[user_id]["name"] = message.text.strip()
        bot.send_message(message.chat.id, "Отправьте фото фактуры (можно несколько).")
    else:
        bot.send_message(message.chat.id, "Сначала нажмите /start и выберите Spółkę.")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    user_id = message.from_user.id
    state = user_states.get(user_id, {})
    if "name" not in state or "company" not in state:
        bot.send_message(message.chat.id, "Сначала нажмите /start, выберите Spółkę и введите имя.")
        return

    if user_id not in photo_buffers:
        photo_buffers[user_id] = []
    photo_buffers[user_id].append(message)

    state["last_photo_time"] = time.time()

@bot.message_handler(content_types=['document', 'video', 'audio', 'voice', 'sticker'])
def reject_unsupported(message):
    bot.send_message(message.chat.id, "⛔ Только фото чеков/фактуры.")


def check_and_send_albums():
    now = time.time()
    for user_id in list(photo_buffers):
        state = user_states.get(user_id, {})
        if "last_photo_time" in state and now - state["last_photo_time"] > 5:
            messages = photo_buffers.pop(user_id, [])
            if not messages:
                continue

            try:
                name = state["name"]
                company = state["company"]
                folder_id = get_or_create_driver_folder(company, name)
                media_group = []
                file_links = []

                for msg in messages:
                    file_info = bot.get_file(msg.photo[-1].file_id)
                    file_path = file_info.file_path
                    file_name = f"{msg.photo[-1].file_id}.jpg"
                    downloaded_file = bot.download_file(file_path)
                    with open(file_name, 'wb') as f:
                        f.write(downloaded_file)

                    file_metadata = {
                        'name': file_name,
                        'parents': [folder_id]
                    }
                    media = MediaFileUpload(file_name, resumable=True)
                    uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
                    file_links.append(uploaded['webViewLink'])
                    media_group.append(types.InputMediaPhoto(open(file_name, 'rb')))

                caption = f"👤 {name}\n🆔 {user_id}\n🏢 {company}\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                bot.send_media_group(ADMIN_ID, media_group)

                for f in media_group:
                    f.media.close()

                sheet.append_row([name, user_id, company, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ", ".join(file_links)])

            except Exception as e:
                bot.send_message(ADMIN_ID, f"❗ Ошибка при отправке фото: {e}")


def get_or_create_driver_folder(company, name):
    parent_id = PARENT_FOLDERS[company]
    query = f"'{parent_id}' in parents and name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get("files", [])
    if folders:
        return folders[0]['id']
    else:
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        file = drive_service.files().create(body=file_metadata, fields='id').execute()
        return file['id']


if __name__ == '__main__':
    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(1)

    threading.Thread(target=run_schedule).start()
    app.run(host='0.0.0.0', port=8080)




