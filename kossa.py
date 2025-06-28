import telebot
from telebot import types
import os
import time
import threading
import hashlib
from datetime import datetime, timedelta
import schedule
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 🔐 Конфигурация
TOKEN = '8011399758:AAGQaLTFK7M0iOLRkgps5znIc9rI5jjcu8A'
ADMIN_ID = 7889110301
FOLDER_IDS = {
    'KOSA': '1u1-F8I6cLNdbWQzbQbU4ujD7s2DqeFkv',
    'SUNBUD': '1vTLWnBDOKIbVpg4isM283leRkhJ8sHKS',
    'ALFATTAH': '1RhO9MimAvO89T9hkSyWgd0wT0zg7N1RV'
}
SHEET_NAME = 'Фактуры'

bot = telebot.TeleBot(TOKEN)

# 📄 Авторизация в Google
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open(SHEET_NAME).sheet1
drive_service = build('drive', 'v3', credentials=creds)

# 🧠 Хранение состояния пользователей
user_states = {}
user_photos = {}
user_hashes = {}

# ⏱️ Функция отправки фото через 5 сек
def schedule_send_photos(user_id):
    def send_group():
        if user_id not in user_photos:
            return
        photos = user_photos[user_id]
        name, company = user_states[user_id]['name'], user_states[user_id]['company']
        folder_id = FOLDER_IDS.get(company)
        subfolder_id = create_user_folder(folder_id, name)
        media_group = []
        for file_id, file_path in photos:
            file_name = os.path.basename(file_path)
            upload_to_drive(file_path, file_name, subfolder_id)
            media_group.append(types.InputMediaPhoto(open(file_path, 'rb')))
        caption = f"{name}\n{user_id}\n{datetime.now().strftime('%Y-%m-%d %H:%M')}"
        try:
            bot.send_media_group(ADMIN_ID, media_group)
            bot.send_message(ADMIN_ID, caption)
        except Exception as e:
            bot.send_message(ADMIN_ID, f"❌ Ошибка при отправке фото: {e}")
        for _, path in photos:
            os.remove(path)
        del user_photos[user_id]
        sheet.append_row([name, user_id, company, caption])
    threading.Timer(5, send_group).start()

# 📁 Создание папки водителя
def create_user_folder(parent_id, username):
    query = f"'{parent_id}' in parents and name='{username}' and mimeType='application/vnd.google-apps.folder'"
    response = drive_service.files().list(q=query, fields="files(id)").execute()
    if response['files']:
        return response['files'][0]['id']
    file_metadata = {
        'name': username,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    file = drive_service.files().create(body=file_metadata, fields='id').execute()
    return file['id']

# 📤 Загрузка файла в Google Drive
def upload_to_drive(file_path, file_name, folder_id):
    file_metadata = {'name': file_name, 'parents': [folder_id]}
    media = MediaFileUpload(file_path, mimetype='image/jpeg')
    drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()

# 📌 Команда /start
@bot.message_handler(commands=['start'])
def start_handler(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("KOSA", "ALFATTAH", "SUNBUD")
    bot.send_message(message.chat.id, "Выбери Spółkę:", reply_markup=markup)
    user_states[message.chat.id] = {}

# 🏢 Выбор Spółki
@bot.message_handler(func=lambda m: m.text in FOLDER_IDS)
def company_handler(message):
    user_states[message.chat.id]['company'] = message.text
    bot.send_message(message.chat.id, "Теперь введи имя и фамилию:")
    
# 🧾 Получение имени
@bot.message_handler(func=lambda m: 'company' in user_states.get(m.chat.id, {}) and 'name' not in user_states[m.chat.id])
def name_handler(message):
    user_states[message.chat.id]['name'] = message.text.strip()
    bot.send_message(message.chat.id, "Отправь фото фактуры или чека.")

# 📷 Получение фото
@bot.message_handler(content_types=['photo'])
def photo_handler(message):
    user_id = message.chat.id
    if user_id not in user_states or 'name' not in user_states[user_id] or 'company' not in user_states[user_id]:
        bot.send_message(user_id, "Напиши /start и следуй инструкциям.")
        return

    # Получение фото
    file_info = bot.get_file(message.photo[-1].file_id)
    file = bot.download_file(file_info.file_path)
    file_hash = hashlib.md5(file).hexdigest()

    # Проверка на дубликат
    if user_id in user_hashes and file_hash in user_hashes[user_id]:
        bot.send_message(user_id, "⛔ Такое фото уже было отправлено.")
        return

    file_path = f"{user_id}_{int(time.time())}.jpg"
    with open(file_path, 'wb') as f:
        f.write(file)

    user_photos.setdefault(user_id, []).append((message.photo[-1].file_id, file_path))
    user_hashes.setdefault(user_id, set()).add(file_hash)

    if len(user_photos[user_id]) == 1:
        schedule_send_photos(user_id)

# ❌ Все остальное
@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.send_message(message.chat.id, "⛔ Только фото чеков/фактуры.")

# ⏰ Проверка фактур раз в день
def check_old_invoices():
    data = sheet.get_all_values()[1:]  # Пропускаем заголовок
    now = datetime.now()
    notified_users = set()
    for row in data[::-1]:  # Последние — сверху
        name, uid, company, timestamp = row[0], row[1], row[2], row[3]
        if uid in notified_users:
            continue
        try:
            last_date = datetime.strptime(timestamp.strip().split('\n')[-1], "%Y-%m-%d %H:%M")
            if (now - last_date).days > 14:
                bot.send_message(int(uid), "⏰ Вы не отправляли фактуры более 2 недель. Пожалуйста, отправьте их.")
                bot.send_message(ADMIN_ID, f"📣 Напоминание отправлено водителю {name} ({uid})")
                notified_users.add(uid)
        except Exception as e:
            bot.send_message(ADMIN_ID, f"⚠️ Ошибка при проверке строк: {row} -> {e}")

# 🔁 Запуск schedule в фоновом потоке
def run_scheduler():
    schedule.every().day.at("10:00").do(check_old_invoices)
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=run_scheduler).start()

# ▶️ Запуск бота
bot.infinity_polling()



