import telebot
from flask import Flask
from datetime import datetime
import threading
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telebot import types



TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_photos = {}
user_timers = {}
user_states = {}
user_data = {}
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("certain-axis-463420-b5-1f4f58ac6291.json", scope)
client = gspread.authorize(creds)

# Открой нужную таблицу по названию
sheet = client.open("telegram-bot-sheets").sheet1


def escape_markdown(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return ''.join(['\\' + char if char in escape_chars else char for char in text])

def build_caption(user_id):
    info = user_data.get(user_id, {})
    first_name = escape_markdown(info.get("first_name", ""))
    last_name = escape_markdown(info.get("last_name", ""))
    username = escape_markdown(info.get("username", ""))
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_link = f"@{username}" if username else f"[профиль](tg://user?id={user_id})"
    return f"📸 Новые фото\n👤 Имя: {first_name} {last_name}\n🔗 {user_link}\n🆔 ID: {user_id}\n🕒 Время: {timestamp}"

def send_album(user_id, message):
    info = user_data.get(user_id, {})
timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
first_name = info.get("first_name", "")
last_name = info.get("last_name", "")
username = info.get("username", "")
sheet.append_row([first_name, last_name, username, user_id, timestamp])

    media_files = user_photos.get(user_id, [])
    if media_files:
        caption = build_caption(user_id)
        media_group = []

        for i, file_id in enumerate(media_files):
            if i == 0:
                media_group.append(types.InputMediaPhoto(media=file_id, caption=caption, parse_mode="Markdown"))
            else:
                media_group.append(types.InputMediaPhoto(media=file_id))

        bot.send_media_group(ADMIN_ID, media_group)
        bot.send_message(user_id, "✅ Спасибо! Фото отправлены.")

    # Очистка
    user_photos.pop(user_id, None)
    user_timers.pop(user_id, None)
    user_states.pop(user_id, None)
    user_data.pop(user_id, None)

@bot.message_handler(commands=['start'])
def start_message(message):
    user_id = message.from_user.id
    bot.send_message(user_id, "👋 Привет! Напиши, пожалуйста, своё имя и фамилию перед отправкой фото.")
    user_states[user_id] = 'waiting_for_name'
    user_data[user_id] = {
        "username": message.from_user.username or "",
        "telegram_id": user_id
    }

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == 'waiting_for_name')
def save_name(message):
    user_id = message.from_user.id
    name_parts = message.text.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
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

    user_timers[user_id] = threading.Timer(10.0, send_album, args=(user_id, message))
    user_timers[user_id].start()

@app.route('/')
def index():
    return 'Бот работает!'

def run_bot():
    bot.infinity_polling()

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)

