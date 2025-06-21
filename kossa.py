import telebot
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask
from datetime import datetime
import threading
from telebot import types
import psycopg2

TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Google Sheets setup через переменную окружения
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
google_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if not google_creds_json:
    raise Exception("GOOGLE_CREDENTIALS_JSON не задана!")
creds_dict = json.loads(google_creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1wjYkcXWUbfk6BBAnTaT80xP9M98K3upVSlugWC7Ddow/edit").sheet1


user_photos = {}
user_timers = {}

def build_caption(message):
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    sender_id = message.from_user.id
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_link = f"@{username}" if username else f"[профиль](tg://user?id={sender_id})"
    return f"📸 Новые фото\n👤 Имя: {first_name} {last_name}\n🔗 {user_link}\n🆔 ID: {sender_id}\n🕒 Время: {timestamp}"

def send_album(user_id, message):
    media = [types.InputMediaPhoto(media=file_id) for file_id in user_photos.get(user_id, [])]
    if media:
        bot.send_media_group(ADMIN_ID, media)
        bot.send_message(ADMIN_ID, build_caption(message), parse_mode="Markdown")
        bot.send_message(user_id, "✅ Спасибо! Фото отправлены.")
    user_photos.pop(user_id, None)
    user_timers.pop(user_id, None)

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, "Привет! Отправь мне одно или несколько фото фактур подряд.")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    user_photos.setdefault(user_id, []).append(file_id)

    if user_id in user_timers:
        user_timers[user_id].cancel()

    user_timers[user_id] = threading.Timer(5.0, send_album, args=(user_id, message))
    user_timers[user_id].start()

    # Google Sheets запись
    sheet.append_row([user_id, username, first_name, last_name, file_id, timestamp])

@app.route('/')
def index():
    return 'Бот работает!'

def run_bot():
    bot.infinity_polling()

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)

