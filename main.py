import telebot
from supabase import create_client, Client
import re
import json
import os
import logging
from datetime import datetime 
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv # Импорт библиотеки dotenv

# Загружаем переменные из файла .env
load_dotenv()

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# === НАСТРОЙКИ (теперь берутся из .env) ===
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
TABLE_NAME = os.getenv('TABLE_NAME', 'clients') # по умолчанию 'clients', если в .env пусто
TARGET_GYM_ID = os.getenv('TARGET_GYM_ID')

# Парсим список админов: берем строку из .env, делим по запятой, удаляем пробелы и переводим в числа (int)
admin_ids_str = os.getenv('ADMIN_CHAT_IDS', '')
ADMIN_CHAT_IDS = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip()]

# Расшифровка типов абонементов согласно базе в Supabase, ID - name из таблицы subscription_types
SUB_TYPE_NAMES = {
    1: "VIP",
    2: "Дневной",
    3: "Безлимит",
    4: "Льготный"
}

EQUIP_DB_PATH = 'equipment.json'

# Инициализация
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# === ФУНКЦИИ ДЛЯ JSON ===
def load_equipment():
    if not os.path.exists(EQUIP_DB_PATH):
        return {}
    with open(EQUIP_DB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

# === ФУНКЦИИ ГЕНЕРАЦИИ КЛАВИАТУР ===
def get_main_menu_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("💳 Статус абонемента", callback_data="menu_status"),
        InlineKeyboardButton("🏋️ Тренажеры", callback_data="menu_equipment"),
        InlineKeyboardButton("✉️ Жалобы и предложения", callback_data="menu_feedback")
    )
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
        bot.send_message(chat_id, "Вы еще не привязали карту к этому залу. Напишите /start")
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
    
    try:
        bot.edit_message_reply_markup(chat_id=chat_id, message_id=prev_message_id, reply_markup=None)
    except:
        pass

    back_keyboard = get_back_to_items_keyboard(cat_key)
    
    if not photos and not gifs:
        bot.send_message(chat_id, f"🏋️ <b>{name}</b>\n\n(Медиафайлы пока не добавлены)", parse_mode="HTML", reply_markup=back_keyboard)
        return

    for i, photo_id in enumerate(photos):
        caption = f"🏋️ <b>{name}</b>" if i == 0 else None
        is_last = (i == len(photos) - 1) and not gifs
        keyboard = back_keyboard if is_last else None
        bot.send_photo(chat_id, photo=photo_id, caption=caption, parse_mode="HTML", reply_markup=keyboard)

    for i, gif_id in enumerate(gifs):
        caption = "🎬 Выполнение упражнения:" if (i == 0 and not photos) else None
        is_last = (i == len(gifs) - 1)
        keyboard = back_keyboard if is_last else None
        bot.send_animation(chat_id, animation=gif_id, caption=caption, reply_markup=keyboard)

# === ОБРАБОТЧИКИ СООБЩЕНИЙ ===
def get_last_digits(phone_str, num_digits=10):
    digits = re.sub(r'\D', '', phone_str)
    return digits[-num_digits:]

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    response = supabase.table(TABLE_NAME).select('*').eq('telegram_id', str(chat_id)).eq('gym_id', TARGET_GYM_ID).execute()
    
    if response.data:
        bot.send_message(
            chat_id, 
            f"С возвращением, {response.data[0]['full_name']}! Выберите действие:", 
            reply_markup=get_main_menu_keyboard()
        )
    else:
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        itembtn = telebot.types.KeyboardButton('📱 Отправить номер телефона', request_contact=True)
        markup.add(itembtn)
        bot.send_message(chat_id, "Привет! Я бот фитнес-клуба. Для доступа к функциям привяжите карту клиента, отправьте боту ваш номер телефона нажав появившуюся кнопку ниже Отправить номер телефона", reply_markup=markup)


@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    if message.contact is None:
        return
        
    chat_id = message.chat.id
    phone = message.contact.phone_number
    last_10_digits = get_last_digits(phone)
    
    bot.send_message(chat_id, "Ищу ваш номер в базе клуба...", reply_markup=telebot.types.ReplyKeyboardRemove())

    response = supabase.table(TABLE_NAME).select('*').like('phone', f'%{last_10_digits}').eq('gym_id', TARGET_GYM_ID).execute()
        
    if not response.data:
        bot.send_message(chat_id, "К сожалению, этот номер не найден в базе данного зала. Обратитесь на ресепшен.")
        return

    client_data = response.data[0]
    
    # Генерируем текущее время в нужном формате (с микросекундами)
    current_time_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
    
    # Обновляем и telegram_id, и updated_at
    supabase.table(TABLE_NAME).update({
        'telegram_id': str(chat_id),
        'updated_at': current_time_str
    }).eq('id', client_data['id']).execute()
    
    bot.send_message(
        chat_id, 
        f"Отлично, {client_data['full_name']}! Ваша карта клиента зала успешно привязана. Выберите действие:", 
        reply_markup=get_main_menu_keyboard()
    )

@bot.message_handler(commands=['status'])
def cmd_status(message):
    send_status_message(message.chat.id)

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
            pass

    def safe_edit_markup(markup=None):
        try:
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=markup)
        except:
            pass

    if data == "menu_main":
        safe_edit_text("Выберите действие:", get_main_menu_keyboard())
        
    elif data == "menu_status":
        safe_edit_text("Загружаю статус...", None)
        send_status_message(chat_id)
        bot.send_message(chat_id, "Выберите действие:", reply_markup=get_main_menu_keyboard())
        
    elif data == "menu_equipment":
        safe_edit_text("Выберите группу мышц:", get_equipment_categories_keyboard())
    
    elif data == "menu_feedback":
        safe_edit_markup(None)
        msg = bot.send_message(
            chat_id, 
            "✉️ Напишите ваше сообщение или отправьте фото с подписью. \n(Следующее сообщение будет передано администрации).", 
            reply_markup=get_cancel_keyboard()
        )
        bot.register_next_step_handler(msg, process_feedback)

    elif data == "cancel_feedback":
        bot.clear_step_handler_by_chat_id(chat_id)
        safe_edit_text("🚫 Действие отменено.", None)
        bot.send_message(chat_id, "Выберите действие:", reply_markup=get_main_menu_keyboard())

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
        bot.send_message(chat_id, "Процесс отменен.", reply_markup=get_main_menu_keyboard())
        return
        
    if not feedback_text and not photo_id:
        bot.send_message(chat_id, "Пожалуйста, отправьте текст или фото. Попробуйте снова через меню.", reply_markup=get_main_menu_keyboard())
        return

    response = supabase.table(TABLE_NAME).select('full_name').eq('telegram_id', str(chat_id)).eq('gym_id', TARGET_GYM_ID).execute()
    user_name = response.data[0]['full_name'] if response.data else "Неизвестный клиент"

    # =========================================================
    # === ВЫБОР ВАРИАНТА ОТПРАВКИ АДМИНУ ===
    
    # ВАРИАНТ 1: АНОНИМНО
    # admin_text = "📩 <b>Новое обращение (Анонимно):</b>\n\n"
    
    # ВАРИАНТ 2: С УКАЗАНИЕМ ФИО
    admin_text = f"📩 <b>Новое обращение:</b>\n👤 От: <b>{user_name}</b> (ID: {chat_id})\n\n"
    
    # =========================================================

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
        bot.send_message(chat_id, "✅ Ваше сообщение успешно отправлено администрации спортзала! Спасибо за обращение.", reply_markup=get_main_menu_keyboard())
    else:
        bot.send_message(chat_id, "❌ Произошла ошибка при отправке. Обратитесь на ресепшен.", reply_markup=get_main_menu_keyboard())


# ===============================
# ВРЕМЕННЫЙ КОД ДЛЯ СБОРА file_id, закомментировать после сбора всех id
# ===============================
#@bot.message_handler(content_types=['photo', 'animation'])
#def get_file_id(message):
#    if message.photo:
        # Фото приходит в разных размерах, берем самое большое [-1]
#        file_id = message.photo[-1].file_id
#        bot.reply_to(message, f"📸 Photo file_id:\n{file_id}")
#    elif message.animation:
#        file_id = message.animation.file_id
#        bot.reply_to(message, f"🎬 GIF file_id:\n{file_id}")


# Запуск бота
if __name__ == '__main__':
    logging.info(f"Бот для зала ID {TARGET_GYM_ID} запущен (telebot)...")
    bot.infinity_polling()
