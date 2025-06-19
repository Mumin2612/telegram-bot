import telebot
from datetime import datetime
from telebot import types
import threading
import time
import sqlite3

# Создание базы и таблицы, если их ещё нет
conn = sqlite3.connect('database.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    file_id TEXT,
    timestamp TEXT
)
''')
conn.commit()


TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301  # ← вставь свой Telegram ID

bot = telebot.TeleBot(TOKEN)
user_photos = {}
timers = {}

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
    media = [types.InputMediaPhoto(media=file_id) for file_id in user_photos[user_id]]
    if media:
        bot.send_media_group(ADMIN_ID, media)
        bot.send_message(ADMIN_ID, build_caption(message), parse_mode="Markdown")
        bot.send_message(user_id, "✅ Спасибо! Фото отправлены.")
    user_photos.pop(user_id, None)
    timers.pop(user_id, None)

def timer_send(user_id, message):
    def task():
        time.sleep(5)  # ждём 5 секунд после последнего фото
        send_album(user_id, message)
    if user_id in timers:
        timers[user_id].cancel()
    timers[user_id] = threading.Timer(5.0, task)
    timers[user_id].start()

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, "Привет! Отправь мне одно или несколько фото фактур подряд.")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id
    # Сохраняем в базу
cursor.execute('''
    INSERT INTO photos (user_id, username, first_name, last_name, file_id, timestamp)
    VALUES (?, ?, ?, ?, ?, ?)
''', (
    message.from_user.id,
    message.from_user.username,
    message.from_user.first_name,
    message.from_user.last_name,
    message.photo[-1].file_id,
    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
))
conn.commit()


    if user_id not in user_photos:
        user_photos[user_id] = []

    user_photos[user_id].append(file_id)
    timer_send(user_id, message)

# Запуск бота через polling
bot.polling(none_stop=True)

