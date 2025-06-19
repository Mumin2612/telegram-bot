import telebot
from datetime import datetime

TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, "Привет! Пожалуйста, отправь фото фактуры.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    username = message.from_user.username or "без username"
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    sender_id = message.from_user.id
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    file_id = message.photo[-1].file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    caption = (
        f"📸 Новое фото\n"
        f"👤 Имя: {first_name} {last_name}\n"
        f"🔗 Username: @{username}\n"
        f"🆔 ID: {sender_id}\n"
        f"🕒 Время: {timestamp}"
    )

    bot.send_photo(ADMIN_ID, downloaded_file, caption=caption)
    bot.send_message(message.chat.id, "✅ Спасибо! Фото отправлено.")

bot.polling()
