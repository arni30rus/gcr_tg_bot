import telebot
from supabase import create_client, Client
import re
import json
import os
import logging
import time
from datetime import datetime 
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# Загружаем переменные из файла .env
load_dotenv()

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# === НАСТРОЙКИ ===
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
TABLE_NAME = os.getenv('TABLE_NAME', 'clients')
TARGET_GYM_ID = os.getenv('TARGET_GYM_ID')

admin_ids_str = os.getenv('ADMIN_CHAT_IDS', '')
ADMIN_CHAT_IDS = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip()]

SUB_TYPE_NAMES = {
    1: "VIP",
    2: "Дневной",
    3: "Безлимит",
    4: "Льготный"
}

EQUIP_DB_PATH = 'equipment.json'
GYM_INFO_PATH = 'gym_info.json'

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# === ФУНКЦИИ ДЛЯ JSON ===
def load_equipment():
    if not os.path.exists(EQUIP_DB_PATH):
        return {}
    with open(EQUIP_DB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_gym_info():
    if not os.path.exists(GYM_INFO_PATH):
        return {}
    with open(GYM_INFO_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

# === ФУНКЦИИ ГЕНЕРАЦИИ КЛАВИАТУР ===
def get_guest_menu_keyboard(chat_id):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("ℹ️ О нас", callback_data="menu_about"),
        InlineKeyboardButton("🔗 Подключить клубную карту", callback_data="menu_connect"),
        InlineKeyboardButton("✉️ Жалобы и предложения", callback_data="menu_feedback")
    )
    if chat_id in ADMIN_CHAT_IDS:
        markup.add(InlineKeyboardButton("🛠 Команды", callback_data="admin_commands"))
    return markup

def get_client_menu_keyboard(chat_id):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("ℹ️ О нас", callback_data="menu_about"),
        InlineKeyboardButton("📊 Статус абонемента", callback_data="menu_status"),
        InlineKeyboardButton("🏋️ Тренажеры", callback_data="menu_equipment"),
        InlineKeyboardButton("✉️ Жалобы и предложения", callback_data="menu_feedback")
    )
    if chat_id in ADMIN_CHAT_IDS:
        markup.add(InlineKeyboardButton("🛠 Команды", callback_data="admin_commands"))
    return markup

def get_current_main_menu(chat_id):
    response = supabase.table(TABLE_NAME).select('telegram_id').eq('telegram_id', str(chat_id)).eq('gym_id', TARGET_GYM_ID).execute()
    if response.data:
        return get_client_menu_keyboard(chat_id)
    else:
        return get_guest_menu_keyboard(chat_id)

def get_about_us_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🎟 Абонементы", callback_data="info_prices"),
        InlineKeyboardButton("🕒 График работы", callback_data="info_schedule"),
        InlineKeyboardButton("🔥 Акции", callback_data="info_promos"), # НОВАЯ КНОПКА
        InlineKeyboardButton("🏋️ Тренеры", callback_data="info_trainers"),
        InlineKeyboardButton("⬅️ Назад в главное меню", callback_data="menu_main")
    )
    return markup

def get_trainers_keyboard():
    info_db = load_gym_info()
    trainers = info_db.get('trainers', {})
    markup = InlineKeyboardMarkup(row_width=1)
    for t_key, t_data in trainers.items():
        markup.add(InlineKeyboardButton(t_data['name'], callback_data=f"trainer_{t_key}"))
    markup.add(InlineKeyboardButton("⬅️ Назад в раздел О нас", callback_data="menu_about"))
    return markup

def get_equipment_categories_keyboard():
    equip_db = load_equipment()
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for cat_key, cat_data in equip_db.items():
        buttons.append(InlineKeyboardButton(cat_data['name'], callback_data=f"cat_{cat_key}"))
    markup.add(*buttons)
    markup.add(InlineKeyboardButton("⬅️ Назад в главное меню", callback_data="menu_main"))
    return markup

def get_equipment_items_keyboard(cat_key):
    equip_db = load_equipment()
    items = equip_db.get(cat_key, {}).get('items', {})
    markup = InlineKeyboardMarkup(row_width=1)
    if not items:
        markup.add(InlineKeyboardButton("Тренажеров пока нет", callback_data="none"))
    else:
        for item_key, item_data in items.items():
            markup.add(InlineKeyboardButton(item_data['name'], callback_data=f"item_{cat_key}_{item_key}"))
    markup.add(InlineKeyboardButton("⬅️ Назад к мышцам", callback_data="menu_equipment"))
    return markup

def get_back_to_items_keyboard(cat_key):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("⬅️ Назад к списку", callback_data=f"cat_{cat_key}"))
    return markup

def get_cancel_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_feedback"))
    return markup

# === ЛОГИКА СТАТУСА ===
def send_status_message(chat_id):
    response = supabase.table(TABLE_NAME).select('*').eq('telegram_id', str(chat_id)).eq('gym_id', TARGET_GYM_ID).execute()
    if not response.data:
        bot.send_message(chat_id, "Вы еще не привязали карту к этому залу. Напишите /start и выберите пункт Подключить клубную карту")
        return
    client = response.data[0]
    name = client.get('full_name', 'Клиент')
    sub_code = client.get('sub_type', 0)
    end_date_str = client.get('end_date', None)
    sub_name = SUB_TYPE_NAMES.get(sub_code, f"Тип {sub_code}")
    
    status_emoji = "⚠️ Неизвестно"
    if end_date_str:
        try:
            date_part = end_date_str[:10]
            end_date_obj = datetime.strptime(date_part, "%Y-%m-%d").date()
            today = datetime.now().date()
            if end_date_obj >= today:
                status_emoji = "✅ Активен"
            else:
                status_emoji = "❌ Истек"
        except Exception as e:
            logging.error(f"Ошибка парсинга даты: {e}")
            status_emoji = "⚠️ Ошибка формата даты в базе"
    else:
        status_emoji = "⚠️ Дата окончания не указана"
    
    display_date = end_date_str[:10] if end_date_str else "Не указана"
    status_text = (
        f"🏋️‍♂️ <b>Статус вашего абонемента:</b>\n\n"
        f"👤 ФИО: {name}\n"
        f"📋 Тип: {sub_name}\n"
        f"📅 Действует до: {display_date}\n"
        f"Статус: {status_emoji}"
    )
    bot.send_message(chat_id, status_text, parse_mode="HTML")

# === функция для отправки информации ===
def send_info_section(chat_id, section_key, title, back_callback):
    info_db = load_gym_info()
    section_data = info_db.get(section_key, {})
    
    back_markup = InlineKeyboardMarkup()
    back_markup.add(InlineKeyboardButton("⬅️ Назад", callback_data=back_callback))
    
    if not section_data or not section_data.get("content"):
        bot.send_message(chat_id, f"{title}\n\nИнформация пока не добавлена.", reply_markup=back_markup)
        return

    if section_data.get("type") == "photo":
        caption_text = f"{title}\n{section_data.get('caption', '')}"
        bot.send_photo(chat_id, photo=section_data["content"], caption=caption_text, reply_markup=back_markup)
    else:
        bot.send_message(chat_id, f"{title}\n\n{section_data['content']}", reply_markup=back_markup)

# === ЛОГИКА ОТПРАВКИ ТРЕНАЖЕРА ===
def send_equipment_detail(chat_id, cat_key, item_key, prev_message_id):
    equip_db = load_equipment()
    item = equip_db.get(cat_key, {}).get('items', {}).get(item_key)
    if not item:
        bot.send_message(chat_id, "Тренажер не найден.")
        return
    name = item.get('name', 'Без названия')
    photos = item.get('photos', [])
    gifs = item.get('gifs', [])
    videos = item.get('videos', [])
    
    try:
        bot.edit_message_reply_markup(chat_id=chat_id, message_id=prev_message_id, reply_markup=None)
    except:
        pass

    back_keyboard = get_back_to_items_keyboard(cat_key)
    total_media = len(photos) + len(gifs) + len(videos)
    if total_media == 0:
        bot.send_message(chat_id, f"🏋️ <b>{name}</b>\n\n(Медиафайлы пока не добавлены)", parse_mode="HTML", reply_markup=back_keyboard)
        return

    media_index = 0 
    for photo_id in photos:
        media_index += 1
        caption = f"🏋️ <b>{name}</b>" if media_index == 1 else None
        is_last = (media_index == total_media)
        keyboard = back_keyboard if is_last else None
        bot.send_photo(chat_id, photo=photo_id, caption=caption, parse_mode="HTML", reply_markup=keyboard)

    for gif_id in gifs:
        media_index += 1
        if media_index == 1:
            caption = f"🏋️ <b>{name}</b>"
        elif media_index == len(photos) + 1:
            caption = "🎬 Выполнение упражнения:"
        else:
            caption = None
        is_last = (media_index == total_media)
        keyboard = back_keyboard if is_last else None
        bot.send_animation(chat_id, animation=gif_id, caption=caption, reply_markup=keyboard)

    for vid_id in videos:
        media_index += 1
        if media_index == 1:
            caption = f"🏋️ <b>{name}</b>"
        elif media_index == len(photos) + len(gifs) + 1:
            caption = "🎥 Видео упражнения:"
        else:
            caption = None
        is_last = (media_index == total_media)
        keyboard = back_keyboard if is_last else None
        bot.send_video(chat_id, video=vid_id, caption=caption, reply_markup=keyboard)

# === ОБРАБОТЧИКИ СООБЩЕНИЙ ===
def get_last_digits(phone_str, num_digits=10):
    digits = re.sub(r'\D', '', phone_str)
    return digits[-num_digits:]

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    response = supabase.table(TABLE_NAME).select('*').eq('telegram_id', str(chat_id)).eq('gym_id', TARGET_GYM_ID).execute()
    if response.data:
        bot.send_message(chat_id, f"С возвращением, {response.data[0]['full_name']}! Выберите действие:", reply_markup=get_client_menu_keyboard(chat_id))
    else:
        bot.send_message(chat_id, "Привет! Я бот фитнес-клуба. Здесь вы можете узнать о нас, подключить клубную карту или оставить обращение.\n\nВыберите действие:", reply_markup=get_guest_menu_keyboard(chat_id))

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    if message.contact is None: return
    chat_id = message.chat.id
    phone = message.contact.phone_number
    last_10_digits = get_last_digits(phone)
    bot.send_message(chat_id, "Ищу ваш номер в базе клуба...", reply_markup=telebot.types.ReplyKeyboardRemove())
    response = supabase.table(TABLE_NAME).select('*').like('phone', f'%{last_10_digits}').eq('gym_id', TARGET_GYM_ID).execute()
    if not response.data:
        bot.send_message(chat_id, "К сожалению, этот номер не найден в базе данного зала. Обратитесь на ресепшен.")
        return
    client_data = response.data[0]
    current_time_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
    supabase.table(TABLE_NAME).update({'telegram_id': str(chat_id), 'updated_at': current_time_str}).eq('id', client_data['id']).execute()
    bot.send_message(chat_id, f"Отлично, {client_data['full_name']}! Ваша карта клиента зала успешно привязана. Выберите действие:", reply_markup=get_client_menu_keyboard(chat_id))

# ===== КОМАНДЫ =====
@bot.message_handler(commands=['status'])
def cmd_status(message):
    send_status_message(message.chat.id)

@bot.message_handler(commands=['mail'])
def start_mailing(message):
    if message.chat.id not in ADMIN_CHAT_IDS: return
    msg = bot.send_message(message.chat.id, "📧 Введите текст рассылки или отправьте фото с подписью:")
    bot.register_next_step_handler(msg, process_mailing)

@bot.message_handler(commands=['users'])
def get_users_count(message):
    if message.chat.id not in ADMIN_CHAT_IDS: return
    response = supabase.table(TABLE_NAME).select('telegram_id').eq('gym_id', TARGET_GYM_ID).not_.is_('telegram_id', 'null').execute()
    users_count = len(response.data)
    bot.send_message(message.chat.id, f"👥 На данный момент к боту привязано пользователей: <b>{users_count}</b>", parse_mode="HTML")

# === АДМИН-КОМАНДЫ ДЛЯ ОБНОВЛЕНИЯ JSON ===
@bot.message_handler(commands=['prices'])
def cmd_edit_prices(message):
    if message.chat.id not in ADMIN_CHAT_IDS: return
    msg = bot.send_message(message.chat.id, "🎟 Пришлите новый текст или фото для раздела «Абонементы»:")
    bot.register_next_step_handler(msg, process_update_info, "prices")

@bot.message_handler(commands=['schedule'])
def cmd_edit_schedule(message):
    if message.chat.id not in ADMIN_CHAT_IDS: return
    msg = bot.send_message(message.chat.id, "🕒 Пришлите новый текст или фото для раздела «График работы»:")
    bot.register_next_step_handler(msg, process_update_info, "schedule")

# НОВАЯ КОМАНДА ДЛЯ АКЦИЙ
@bot.message_handler(commands=['promos'])
def cmd_edit_promos(message):
    if message.chat.id not in ADMIN_CHAT_IDS: return
    msg = bot.send_message(message.chat.id, "🔥 Пришлите новый текст или фото для раздела «Акции»:")
    bot.register_next_step_handler(msg, process_update_info, "promotions")

def process_update_info(message, section_key):
    if message.content_type == 'photo':
        content = message.photo[-1].file_id
        caption = message.caption or ""
        info_type = "photo"
    elif message.content_type == 'text' and not message.text.startswith('/'):
        content = message.text
        caption = ""
        info_type = "text"
    else:
        bot.send_message(message.chat.id, "❌ Ошибка: нужно прислать текст или фото. Обновление отменено.")
        return

    info_db = load_gym_info()
    info_db[section_key] = {"type": info_type, "content": content, "caption": caption}
    with open(GYM_INFO_PATH, 'w', encoding='utf-8') as f:
        json.dump(info_db, f, ensure_ascii=False, indent=4)
    bot.send_message(message.chat.id, f"✅ Раздел успешно обновлен!")

# === УДОБНОЕ ПОЛУЧЕНИЕ file_id ДЛЯ АДМИНОВ ===
@bot.message_handler(content_types=['photo', 'animation', 'video'])
def admin_get_file_id(message):
    if message.chat.id not in ADMIN_CHAT_IDS: return
    if message.photo:
        file_id = message.photo[-1].file_id
        bot.reply_to(message, f"📸 <b>Photo file_id:</b>\n\n<code>{file_id}</code>", parse_mode="HTML")
    elif message.animation:
        file_id = message.animation.file_id
        bot.reply_to(message, f"🎬 <b>GIF file_id:</b>\n\n<code>{file_id}</code>", parse_mode="HTML")
    elif message.video:
        file_id = message.video.file_id
        bot.reply_to(message, f"🎥 <b>Video file_id:</b>\n\n<code>{file_id}</code>", parse_mode="HTML")

# === ОБРАБОТЧИК НАЖАТИЙ НА INLINE КНОПКИ ===
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    data = call.data
    message_id = call.message.message_id
    bot.answer_callback_query(call.id)
    
    def safe_edit_text(text, markup=None):
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except:
            try:
                bot.delete_message(chat_id, message_id)
            except:
                pass
            bot.send_message(chat_id, text, reply_markup=markup)

    def safe_edit_markup(markup=None):
        try:
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=markup)
        except:
            pass

    if data == "menu_main":
        try:
            msg_to_del = bot.send_message(chat_id, ".", reply_markup=telebot.types.ReplyKeyboardRemove())
            bot.delete_message(chat_id, msg_to_del.message_id)
        except:
            pass
        safe_edit_text("Выберите действие:", get_current_main_menu(chat_id))
        
    elif data == "menu_about":
        safe_edit_text("Раздел 'О нас'. Выберите подраздел:", get_about_us_keyboard())

    # === ЛОГИКА РАЗДЕЛА "О НАС" ===
    elif data == "info_prices":
        safe_edit_markup(None)
        send_info_section(chat_id, "prices", "🎟 Абонементы", "menu_about")
        
    elif data == "info_schedule":
        safe_edit_markup(None)
        send_info_section(chat_id, "schedule", "🕒 График работы", "menu_about")
        
    # НОВЫЙ ОБРАБОТЧИК ДЛЯ АКЦИЙ
    elif data == "info_promos":
        safe_edit_markup(None)
        send_info_section(chat_id, "promotions", "🔥 Акции", "menu_about")
        
    elif data == "info_trainers":
        safe_edit_text("🏋️ Выберите тренера:", get_trainers_keyboard())
        
    elif data.startswith("trainer_"):
        safe_edit_markup(None)
        t_key = data[8:]
        info_db = load_gym_info()
        trainer = info_db.get("trainers", {}).get(t_key)
        if not trainer:
            bot.send_message(chat_id, "Тренер не найден.")
            return
        back_markup = InlineKeyboardMarkup()
        back_markup.add(InlineKeyboardButton("⬅️ Назад к тренерам", callback_data="info_trainers"))
        name = trainer.get("name", "Тренер")
        desc = trainer.get("desc", "")
        photo_id = trainer.get("photo_id")
        if photo_id:
            bot.send_photo(chat_id, photo=photo_id, caption=f"🏋️ <b>{name}</b>\n\n{desc}", parse_mode="HTML", reply_markup=back_markup)
        else:
            bot.send_message(chat_id, f"🏋️ <b>{name}</b>\n\n{desc}", parse_mode="HTML", reply_markup=back_markup)

    elif data == "menu_connect":
        back_markup = InlineKeyboardMarkup()
        back_markup.add(InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_main"))
        safe_edit_text("Для привязки карты клиента нажмите кнопку «📱 Отправить номер телефона» внизу экрана.\n\nЕсли передумали — нажмите «Назад в меню».", back_markup)
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        itembtn = telebot.types.KeyboardButton('📱 Отправить номер телефона', request_contact=True)
        markup.add(itembtn)
        bot.send_message(chat_id, "📱 Подтвердите отправку номера:", reply_markup=markup)
    
    elif data == "menu_status":
        response = supabase.table(TABLE_NAME).select('telegram_id').eq('telegram_id', str(chat_id)).eq('gym_id', TARGET_GYM_ID).execute()
        if not response.data:
            safe_edit_text("⚠️ Этот раздел доступен только для клиентов. Пожалуйста, подключите клубную карту.", get_guest_menu_keyboard(chat_id))
            return
        safe_edit_text("Загружаю статус...", None)
        send_status_message(chat_id)
        bot.send_message(chat_id, "Выберите действие:", reply_markup=get_current_main_menu(chat_id))
        
    elif data == "menu_equipment":
        response = supabase.table(TABLE_NAME).select('telegram_id').eq('telegram_id', str(chat_id)).eq('gym_id', TARGET_GYM_ID).execute()
        if not response.data:
            safe_edit_text("⚠️ Этот раздел доступен только для клиентов. Пожалуйста, подключите клубную карту.", get_guest_menu_keyboard(chat_id))
            return
        safe_edit_text("Выберите группу мышц:", get_equipment_categories_keyboard())
    
    elif data == "menu_feedback":
        safe_edit_markup(None)
        msg = bot.send_message(chat_id, "✉️ Напишите ваше сообщение или отправьте фото с подписью. \n(Следующее сообщение будет передано администрации).", reply_markup=get_cancel_keyboard())
        bot.register_next_step_handler(msg, process_feedback)

    elif data == "cancel_feedback":
        bot.clear_step_handler_by_chat_id(chat_id)
        safe_edit_text("🚫 Действие отменено.", None)
        bot.send_message(chat_id, "Выберите действие:", reply_markup=get_current_main_menu(chat_id))

    elif data.startswith("cat_"):
        cat_key = data[4:]
        equip_db = load_equipment()
        cat_name = equip_db.get(cat_key, {}).get('name', 'Тренажеры')
        safe_edit_markup(None)
        bot.send_message(chat_id, f"Группа: {cat_name}. Выберите тренажер:", reply_markup=get_equipment_items_keyboard(cat_key)) 
        
    elif data.startswith("item_"):
        parts = data.split("_", 2) 
        if len(parts) == 3:
            cat_key = parts[1]
            item_key = parts[2]
            send_equipment_detail(chat_id, cat_key, item_key, message_id)

    elif data == "admin_commands":
        if chat_id not in ADMIN_CHAT_IDS: return
        # ОБНОВЛЕНО: Добавлено описание команды /promos
        admin_text = (
            "🛠 Команды администратора:\n\n"
            "📧 /mail — Массовая рассылка пользователям (текст или фото)\n"
            "👥 /users — Показать количество привязанных пользователей\n"
            "🎟  /prices — Обновить раздел «Абонементы»\n"
            "🕒 /schedule — Обновить раздел «График работы»\n"
            "🔥 /promos — Обновить раздел «Акции»\n\n"
            "📸 Получение file_id:\n"
            "Просто отправьте боту фото, гифку или видео, и он ответит их уникальным ID для вставки в JSON-файлы."
        )
        back_markup = InlineKeyboardMarkup()
        back_markup.add(InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_main"))
        safe_edit_text(admin_text, back_markup)

# === ЛОГИКА ОБРАТНОЙ СВЯЗИ ===
def process_feedback(message):
    chat_id = message.chat.id
    if message.content_type == 'photo':
        feedback_text = message.caption
        photo_id = message.photo[-1].file_id
    else:
        feedback_text = message.text
        photo_id = None
    if feedback_text and feedback_text.startswith('/'):
        bot.send_message(chat_id, "Процесс отменен.", reply_markup=get_current_main_menu(chat_id))
        return
    if not feedback_text and not photo_id:
        bot.send_message(chat_id, "Пожалуйста, отправьте текст или фото. Попробуйте снова через меню.", reply_markup=get_current_main_menu(chat_id))
        return

    response = supabase.table(TABLE_NAME).select('full_name').eq('telegram_id', str(chat_id)).eq('gym_id', TARGET_GYM_ID).execute()
    user_name = response.data[0]['full_name'] if response.data else "Анонимный гость"

    # ВАРИАНТ 1: АНОНИМНО
    # admin_text = "📩 <b>Новое обращение (Анонимно):</b>\n\n"
    
    # ВАРИАНТ 2: С УКАЗАНИЕМ ФИО
    admin_text = f"📩 <b>Новое обращение:</b>\n👤 От: <b>{user_name}</b> (ID: {chat_id})\n\n"

    if feedback_text:
        admin_text += f"Текст:\n{feedback_text}"
    else:
        admin_text += "(Без текста, только фото)"

    success = False
    for admin_id in ADMIN_CHAT_IDS:
        try:
            if photo_id:
                bot.send_photo(admin_id, photo=photo_id, caption=admin_text, parse_mode="HTML")
            else:
                bot.send_message(admin_id, admin_text, parse_mode="HTML")
            success = True
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")
    if success:
        bot.send_message(chat_id, "✅ Ваше сообщение успешно отправлено администрации! Спасибо за обращение.", reply_markup=get_current_main_menu(chat_id))
    else:
        bot.send_message(chat_id, "❌ Произошла ошибка при отправке. Обратитесь на ресепшен.", reply_markup=get_current_main_menu(chat_id))

# === МАССОВАЯ РАССЫЛКА ===
def process_mailing(message):
    admin_chat_id = message.chat.id
    if message.content_type == 'photo':
        mailing_text = message.caption
        photo_id = message.photo[-1].file_id
    else:
        mailing_text = message.text
        photo_id = None
    if mailing_text and mailing_text.startswith('/'):
        bot.send_message(admin_chat_id, "Рассылка отменена.")
        return
    if not mailing_text and not photo_id:
        bot.send_message(admin_chat_id, "Ошибка: сообщение пустое. Рассылка отменена.")
        return
    bot.send_message(admin_chat_id, "⏳ Рассылка началась. Ожидайте...")
    response = supabase.table(TABLE_NAME).select('telegram_id').eq('gym_id', TARGET_GYM_ID).not_.is_('telegram_id', 'null').execute()
    success_count = 0
    fail_count = 0
    for client in response.data:
        tg_id = client.get('telegram_id')
        if not tg_id: continue
        try:
            if photo_id:
                bot.send_photo(tg_id, photo=photo_id, caption=mailing_text, parse_mode="HTML")
            else:
                bot.send_message(tg_id, mailing_text, parse_mode="HTML")
            success_count += 1
        except Exception as e:
            fail_count += 1
            logging.error(f"Не удалось отправить рассылку пользователю {tg_id}: {e}")
        time.sleep(0.05)
    bot.send_message(admin_chat_id, f"✅ Рассылка завершена!\n\nУспешно отправлено: {success_count}\nОшибок (заблокировали бота): {fail_count}")

if __name__ == '__main__':
    logging.info(f"Бот для зала ID {TARGET_GYM_ID} запущен (telebot)...")
    bot.infinity_polling()
