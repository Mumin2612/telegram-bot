import telebot
from flask import Flask
from datetime import datetime
import threading
from telebot import types

TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_photos = {}
user_timers = {}
user_states = {}
user_data = {}

def build_caption(user_id, user_info):
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "")
    last_name = user_info.get("last_name", "")
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_link = f"@{username}" if username else f"[профиль](tg://user?id={user_id})"
    return f"📸 Новые фото\n👤 Имя: {first_name} {last_name}\n🔗 {user_link}\n🆔 ID: {user_id}\n🕒 Время: {timestamp}"

def send_album(user_id, message):
    media = [types.InputMediaPhoto(media=file_id) for file_id in user_photos.get(user_id, [])]
    if media:
        caption = build_caption(user_id, user_data[user_id])
        bot.send_media_group(ADMIN_ID, media)
        bot.send_message(ADMIN_ID, caption, parse_mode="Markdown")
        bot.send_message(user_id, "✅ Спасибо! Фото отправлены.")
    user_photos.pop(user_id, None)
    user_timers.pop(user_id, None)
    user_states.pop(user_id, None)
    user_data.pop(user_id, None)

@bot.message_handler(commands=['start'])
def start_message(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    user_data[user_id] = {
        "username": username,
        "first_name": "",
        "last_name": ""
    }
    user_states[user_id] = 'waiting_for_name'
    bot.send_message(user_id, "👋 Привет! Напиши, пожалуйста, своё имя и фамилию перед отправкой фото.")

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'waiting_for_name')
def save_name(message):
    user_id = message.from_user.id
    name_parts = message.text.strip().split()
    first_name = name_parts[0] if len(name_parts) > 0 else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    if user_id not in user_data:
        user_data[user_id] = {"username": message.from_user.username or ""}
    user_data[user_id]["first_name"] = first_name
    user_data[user_id]["last_name"] = last_name
    user_states[user_id] = 'ready_for_photos'
    bot.send_message(user_id, "✅ Имя сохранено. Теперь отправь одно или несколько фото подряд.")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    user_id = message.from_user.id

    if user_states.get(user_id) != 'ready_for_photos':
        bot.send_message(user_id, "Сначала напиши своё имя и фамилию. Отправь /start.")
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



