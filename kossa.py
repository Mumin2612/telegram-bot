import telebot
from flask import Flask, request
from datetime import datetime
import threading
from telebot import types

TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301  # ← замени на свой Telegram ID

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Временное хранилище фото
user_photos = {}

def build_caption(message):
    username = message.from_user.username
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    sender_id = message.from_user.id
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if username:
        user_link = f"@{username}"
    else:
        user_link = f"[профиль](tg://user?id={sender_id})"

    return (
        f"📸 Новые фото\n"
        f"👤 Имя: {first_name} {last_name}\n"
        f"🔗 {user_link}\n"
        f"🆔 ID: {sender_id}\n"
        f"🕒 Время: {timestamp}"
    )

def send_album(user_id, message):
    media = []
    for file_id in user_photos[user_id]:
        media.append(types.InputMediaPhoto(media=file_id))

    if media:
        bot.send_media_group(ADMIN_ID, media)
        bot.send_message(ADMIN_ID, build_caption(message), parse_mode="Markdown")
        bot.send_message(user_id, "✅ Спасибо! Фото отправлены.")
    user_photos.pop(user_id, None)

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, "Привет! Отправь мне одно или несколько фото фактур подряд.")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    user_id = message.from_user

    timer_send()
