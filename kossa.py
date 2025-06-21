import telebot
import os
import json
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask
from datetime import datetime
import threading
from telebot import types

TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Google Sheets отключено (если нужно - подключим позже)

user_photos = {}
user_timers = {}
user_data = {}  # user_id: {'name': 'Имя Фамилия', 'ready': True}

def build_caption(message):
    user_id = message.from_user.id
    full_name = user_data.get(user_id, {}).get('name', '')
    username = message.from_user.username or ""
    sender_id = user_id
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_link = f"@{username}" if username else f"[профиль](tg://user?id={sender_id})"
    return f"📸 Новые фото\n👤 Имя: {full_name}\n🔗 {user_link}\n🆔 ID: {sender_id}\n🕒 Время: {timestamp}"

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
    user_id = message.chat.id
    user_data[user_id] = {'ready': False}
    bot.send_message(user_id, "👋 Привет! Пожалуйста, напиши своё имя и фамилию.")

@bot.message_handler(func=lambda message: message.text and message.chat.id in user_data and not user_data[message.chat.id]['ready'])
def save_name(message):
    user_id = message.chat.id
    user_data[user_id]['name'] = message.text
    user_data[user_id]['ready'] = True
    bot.send_message(user_id, "✅ Спасибо! Теперь отправь фото фактур.")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    user_id = message.from_user.id

    if user_id not in user_data or not user_data[user_id].get('ready'):
        bot.send_message(user_id, "❗ Сначала отправьте своё имя и фамилию с помощью команды /start.")
        return

    file_id = message.photo[-1].file_id
    user_photos.setdefault(user_id, []).append(file_id)

    if user_id in user_timers:
        user_timers[user_id].cancel()

    user_timers[user_id] = threading.Timer(5.0, send_album, args=(user_id, message))
    user_timers[user_id].start()

@app.route('/')
def index():
    return 'Бот работает!'

def run_bot():
    bot.infinity_polling()

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)

