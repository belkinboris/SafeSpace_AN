import os
import logging
import random
import datetime
import re

from flask import Flask
from threading import Thread

from telegram import (
    Update,
    BotCommand,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ------------------------------------------------------------------------
# 1) ЧТЕНИЕ ТОКЕНА ИЗ ОКРУЖЕНИЯ
# ------------------------------------------------------------------------
BOT_TOKEN = os.getenv("token_an")
if not BOT_TOKEN:
    raise ValueError("Не найден токен (token_an) в переменных окружения!")

# ------------------------------------------------------------------------
# 2) FLASK-СЕРВЕР ДЛЯ KEEP ALIVE
# ------------------------------------------------------------------------
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Бот активен!"

def run_flask_server():
    port = int(os.getenv("PORT", "8080"))  # для платформ типа Railway
    app_flask.run(host='0.0.0.0', port=port)

def start_keep_alive():
    thread = Thread(target=run_flask_server)
    thread.start()

# ------------------------------------------------------------------------
# 3) НАСТРОЙКА ЛОГИРОВАНИЯ
# ------------------------------------------------------------------------
logging.basicConfig(
    filename='bot_activity.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# ------------------------------------------------------------------------
# 4) ГЛОБАЛЬНЫЕ ДАННЫЕ И СТРУКТУРЫ
# ------------------------------------------------------------------------
active_users = {}      # { user_id: { nickname, code, chat_id, last_active } }
user_profiles = {}     # { user_id: { nickname, code, join_count } }
exited_users = []      # список кортежей (nickname, code, time)
direct_messages = {}   # { user_id: [ { from, text }, ... ] }
notification_settings = {}  # { user_id: { privates, replies, hug, interval } }
active_polls = {}      # { creator_id: { question, options, votes, active, msg_ids, chat_ids } }
reported_messages = [] # [ { reporter, offender, reason, time } ]
admin_ids = set()
moderator_ids = set()

# ------------------------------------------------------------------------
# 5) ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ------------------------------------------------------------------------
def create_random_nickname() -> str:
    """Генерация случайного никнейма."""
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    return f"🆔{''.join(random.choices(letters, k=6))}"

def create_unique_code() -> str:
    """Генерация уникального кода пользователя в формате #XXXX."""
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return f"#{''.join(random.choices(letters, k=4))}"

def initialize_user_settings(user_id: int):
    """Инициализировать данные для личных сообщений и уведомлений."""
    if user_id not in direct_messages:
        direct_messages[user_id] = []
    if user_id not in notification_settings:
        notification_settings[user_id] = {
            "privates": False,
            "replies": False,
            "hug": False,
            "interval": 5,
        }

def determine_user_role(user_id: int) -> str:
    """Определяем роль пользователя: admin | moderator | newbie | regular."""
    if user_id in admin_ids:
        return "admin"
    if user_id in moderator_ids:
        return "moderator"
    if user_id in user_profiles:
        count = user_profiles[user_id].get("join_count", 0)
        return "newbie" if count <= 1 else "regular"
    return "newbie"

def refresh_user_activity(user_id: int):
    """Обновить время последней активности пользователя."""
    if user_id in active_users:
        active_users[user_id]["last_active"] = datetime.datetime.now()

def broadcast_message(app_context, text: str, exclude_user: int = None):
    """Рассылаем текстовое сообщение всем активным пользователям, кроме указанного."""
    for uid, info in active_users.items():
        if uid == exclude_user:
            continue
        try:
            app_context.bot.send_message(chat_id=info["chat_id"], text=text)
        except Exception as err:
            logging.warning(f"Ошибка отправки сообщения для {info['nickname']}: {err}")

def broadcast_image(app_context, photo_id: str, caption: str = "", exclude_user: int = None):
    """Рассылаем фото всем активным пользователям, кроме указанного."""
    for uid, info in active_users.items():
        if uid == exclude_user:
            continue
        try:
            app_context.bot.send_photo(
                chat_id=info["chat_id"],
                photo=photo_id,
                caption=caption
            )
        except Exception as err:
            logging.warning(f"Ошибка отправки фото для {info['nickname']}: {err}")

def extract_replied_nickname(message_text: str) -> str:
    """Извлечь ник из ответа бота, если он присутствует (формат 'Nickname: ...')."""
    match = re.match(r"^(.+?):\s", message_text)
    if match:
        return match.group(1).strip()
    return ""

# ------------------------------------------------------------------------
# 6) ХЕНДЛЕРЫ КОМАНД
# ------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    initialize_user_settings(user_id)

    if user_id in active_users:
        nick = active_users[user_id]["nickname"]
        await update.message.reply_text(
            f"[Бот] Ты уже в чате под именем «{nick}». Чтобы выйти, используй /stop."
        )
        refresh_user_activity(user_id)
        return

    # Если пользователь уже был раньше
    if user_id in user_profiles:
        nick = user_profiles[user_id]["nickname"]
        code = user_profiles[user_id]["code"]
        user_profiles[user_id]["join_count"] = user_profiles[user_id].get("join_count", 0) + 1
        join_count = user_profiles[user_id]["join_count"]
    else:
        nick = create_random_nickname()
        code = create_unique_code()
        user_profiles[user_id] = {
            "nickname": nick,
            "code": code,
            "join_count": 1
        }
        join_count = 1

    active_users[user_id] = {
        "nickname": nick,
        "code": code,
        "chat_id": chat_id,
        "last_active": datetime.datetime.now()
    }

    welcome_msg = (
        f"[Бот] Добро пожаловать в анонимный чат для поддержки и обмена опытом!\n"
        f"Твой псевдоним: {nick}\n"
        f"Твой код: {code}\n"
        "Для выхода набери /stop.\n"
        "Приятного общения!"
    )
    await update.message.reply_text(welcome_msg)

    if join_count == 1:
        broadcast_text = f"[Системное] {code} {nick} присоединился(ась) к чату. Новый участник!"
    else:
        broadcast_text = f"[Системное] {code} {nick} вновь в чате."
    await broadcast_message(context.application, broadcast_text, exclude_user=user_id)
    logging.info(f"Пользователь {user_id} ({nick}), заход #{join_count}.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты не находишься в чате. Введи /start, чтобы войти.")
        return

    nick = active_users[user_id]["nickname"]
    code = active_users[user_id]["code"]
    active_users.pop(user_id)

    exited_users.insert(0, (nick, code, datetime.datetime.now()))
    if len(exited_users) > 20:
        exited_users.pop()

    await update.message.reply_text("[Бот] Ты вышел(а) из чата. Приходи ещё!")
    await broadcast_message(context.application, f"[Системное] {code} {nick} покинул(а) чат.", exclude_user=user_id)
    logging.info(f"Пользователь {user_id} ({nick}) вышел из чата.")

# ------------------------------------------------------------------------
# 7) СМЕНА НИКА (/nick)
# ------------------------------------------------------------------------
NICK_WAIT = range(1)

async def change_nick_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты не в чате. Введи /start, чтобы подключиться.")
        return ConversationHandler.END

    await update.message.reply_text("[Бот] Введи новый ник (не более 15 символов):")
    return NICK_WAIT

async def change_nick_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты уже покинул чат.")
        return ConversationHandler.END

    new_nick = update.message.text.strip()
    if len(new_nick) > 15:
        await update.message.reply_text("[Бот] Слишком длинный ник. Попробуй ещё раз.")
        return ConversationHandler.END

    old_nick = active_users[user_id]["nickname"]
    code = active_users[user_id]["code"]

    active_users[user_id]["nickname"] = new_nick
    user_profiles[user_id]["nickname"] = new_nick

    await update.message.reply_text(f"[Бот] Ник изменён на {new_nick}.")
    await broadcast_message(context.application, f"[Системное] {code} {old_nick} теперь известен(а) как {new_nick}.")
    refresh_user_activity(user_id)
    logging.info(f"Пользователь {user_id}: {old_nick} -> {new_nick}.")
    return ConversationHandler.END

async def cancel_nick_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("[Бот] Изменение ника отменено.")
    return ConversationHandler.END

# ------------------------------------------------------------------------
# 8) Список пользователей (/list) и статистика (/stats)
# ------------------------------------------------------------------------
async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_users:
        await update.message.reply_text("[Бот] В чате пока никого нет.")
        return

    total_possible = 100  # шутливое число
    lines = []
    now = datetime.datetime.now()

    for uid, info in active_users.items():
        seconds_diff = (now - info["last_active"]).total_seconds()
        # Символ активности по времени
        if seconds_diff < 60:
            activity_icon = "🌕"
        elif seconds_diff < 300:
            activity_icon = "🌖"
        elif seconds_diff < 900:
            activity_icon = "🌗"
        elif seconds_diff < 1800:
            activity_icon = "🌘"
        else:
            activity_icon = "🌑"
        role = determine_user_role(uid)
        lines.append(f"{activity_icon} [{role}] {info['code']} {info['nickname']}")
    text = f"[Бот] В чате {len(active_users)} (из {total_possible}):\n" + "\n".join(lines)
    await update.message.reply_text(text)
    refresh_user_activity(update.effective_user.id)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = len(user_profiles)
    active_count = len(active_users)
    await update.message.reply_text(f"[Бот] Статистика:\nВсего пользователей: {total_users}\nАктивных: {active_count}")
    refresh_user_activity(update.effective_user.id)

# ------------------------------------------------------------------------
# 9) Информация и помощь: /help, /rules, /about, /ping
# ------------------------------------------------------------------------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "[Бот] Доступные команды:\n\n"
        "/start - Присоединиться к чату\n"
        "/stop - Покинуть чат\n"
        "/nick - Изменить ник\n"
        "/list - Список пользователей\n"
        "/stats - Статистика чата\n"
        "/msg - Отправить ЛС\n"
        "/getmsg - Получить ЛС\n"
        "/hug - Обнять пользователя\n"
        "/search - Поиск по нику\n"
        "/poll - Создать опрос\n"
        "/polldone - Завершить опрос\n"
        "/notify - Настройка уведомлений\n"
        "/report - Пожаловаться на сообщение\n"
        "/ping - Проверка бота\n"
        "/rules - Правила чата\n"
        "/about - О боте\n"
        "/help - Справка\n\n"
        "Для «третьего лица» начинай сообщение с символа %."
    )
    await update.message.reply_text(help_text)
    refresh_user_activity(update.effective_user.id)

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules_text = (
        "[Бот] Правила чата:\n\n"
        "1. Соблюдай уважительный тон и поддерживай дружественную атмосферу.\n"
        "2. Запрещены оскорбления, спам и нецензурная лексика.\n"
        "3. Реклама, флуд и ссылки на сторонние ресурсы недопустимы.\n"
        "4. Общение только на русском языке (кириллица).\n"
        "5. Модераторы имеют право применять меры наказания.\n\n"
        "Нарушения будут рассмотрены. Будь вежлив!"
    )
    await update.message.reply_text(rules_text)
    refresh_user_activity(update.effective_user.id)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("[Бот] Это улучшенная версия анонимного чат-бота с новыми функциями. Приятного общения!")
    refresh_user_activity(update.effective_user.id)

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong!")
    refresh_user_activity(update.effective_user.id)

# ------------------------------------------------------------------------
# 10) Личные сообщения (/msg, /getmsg)
# ------------------------------------------------------------------------
MSG_SELECT, MSG_TEXT = range(2)

async def dm_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты не в чате. Введи /start, чтобы войти.")
        return ConversationHandler.END

    # Если команда выглядит как: /msg CODE сообщение
    if len(context.args) >= 2:
        code = context.args[0]
        message_text = " ".join(context.args[1:])
        target_id = None
        for uid, data in active_users.items():
            if data["code"].lower() == code.lower():
                target_id = uid
                break
        if not target_id:
            await update.message.reply_text("[Бот] Пользователь с таким кодом не найден.")
            return ConversationHandler.END

        from_nick = active_users[user_id]["nickname"]
        initialize_user_settings(target_id)
        direct_messages[target_id].append({"from": from_nick, "text": message_text})

        target_chat = active_users[target_id]["chat_id"]
        await context.application.bot.send_message(
            chat_id=target_chat,
            text=f"[ЛС от {from_nick}]: {message_text}"
        )

        await update.message.reply_text(f"[Бот] Сообщение отправлено пользователю {code}.")
        refresh_user_activity(user_id)
        return ConversationHandler.END

    # Иначе выводим inline-кнопки для выбора получателя
    kb = []
    row = []
    count = 0
    for uid, data in active_users.items():
        if uid == user_id:
            continue
        count += 1
        btn_label = f"{data['code']} {data['nickname']}"
        row.append(InlineKeyboardButton(btn_label, callback_data=f"dm_select|{uid}"))
        if count % 3 == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("❌ Отмена", callback_data="dm_cancel")])
    await update.message.reply_text(
        "[Бот] Выбери получателя для личного сообщения:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    refresh_user_activity(user_id)
    return MSG_SELECT

async def dm_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    parts = query.data.split("|")
    if len(parts) != 2:
        await query.answer("Ошибка выбора.")
        return ConversationHandler.END

    target_id = int(parts[1])
    context.user_data["dm_target"] = target_id

    target_info = active_users[target_id]
    await query.message.edit_text(
        f"[Бот] Напиши сообщение для {target_info['code']} {target_info['nickname']}:"
    )
    await query.answer()
    return MSG_TEXT

async def dm_text_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if "dm_target" not in context.user_data:
        await update.message.reply_text("[Бот] Ошибка: не выбран получатель.")
        return ConversationHandler.END

    target_id = context.user_data["dm_target"]
    if target_id not in active_users:
        await update.message.reply_text("[Бот] Получатель уже покинул чат.")
        return ConversationHandler.END

    from_nick = active_users[user_id]["nickname"]
    message_text = update.message.text

    target_info = active_users[target_id]
    initialize_user_settings(target_id)
    direct_messages[target_id].append({"from": from_nick, "text": message_text})

    target_chat = target_info["chat_id"]
    await context.application.bot.send_message(
        chat_id=target_chat,
        text=f"[ЛС от {from_nick}]: {message_text}"
    )

    await update.message.reply_text(f"[Бот] Сообщение отправлено {target_info['code']} {target_info['nickname']}.")
    logging.info(f"ЛС: {from_nick} -> {target_info['nickname']}: {message_text}")
    context.user_data.pop("dm_target", None)
    refresh_user_activity(user_id)
    return ConversationHandler.END

async def dm_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.message.edit_text("Отправка ЛС отменена.")
    await query.answer()
    return ConversationHandler.END

async def get_dm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты не в чате.")
        return

    initialize_user_settings(user_id)
    messages = direct_messages[user_id]
    if not messages:
        await update.message.reply_text("[Бот] У тебя нет новых сообщений.")
        return

    lines = [f"От {msg['from']}: {msg['text']}" for msg in messages]
    text = "[Бот] Личные сообщения:\n\n" + "\n".join(lines)
    await update.message.reply_text(text)
    refresh_user_activity(user_id)

# ------------------------------------------------------------------------
# 11) Обнимашки (/hug)
# ------------------------------------------------------------------------
HUG_SELECT = range(1)

async def hug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты не в чате.")
        return ConversationHandler.END

    # Если команда введена как: /hug CODE
    if context.args:
        code = context.args[0]
        target_id = None
        for uid, data in active_users.items():
            if data["code"].lower() == code.lower():
                target_id = uid
                break
        if not target_id:
            await update.message.reply_text("[Бот] Пользователь с таким кодом не найден.")
            return ConversationHandler.END

        from_info = active_users[user_id]
        to_info = active_users[target_id]
        msg = f"[Системное] {from_info['code']} {from_info['nickname']} обнял(а) {to_info['nickname']}!"
        await broadcast_message(context.application, msg)
        refresh_user_activity(user_id)
        return ConversationHandler.END

    # Inline выбор обнимаемого
    kb = []
    row = []
    count = 0
    for uid, data in active_users.items():
        if uid == user_id:
            continue
        count += 1
        btn_label = f"{data['code']} {data['nickname']}"
        row.append(InlineKeyboardButton(btn_label, callback_data=f"hug_select|{uid}"))
        if count % 3 == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("❌ Отмена", callback_data="hug_cancel")])
    await update.message.reply_text(
        "[Бот] Выбери, кого обнять:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    refresh_user_activity(user_id)
    return HUG_SELECT

async def hug_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    parts = query.data.split("|")
    if len(parts) != 2:
        await query.answer("Ошибка выбора.")
        return ConversationHandler.END

    target_id = int(parts[1])
    from_info = active_users[user_id]
    to_info = active_users[target_id]
    msg = f"[Системное] {from_info['code']} {from_info['nickname']} обнимает {to_info['nickname']}!"
    await broadcast_message(context.application, msg)
    await query.message.edit_text("Обнимашка отправлена!")
    await query.answer()
    refresh_user_activity(user_id)
    return ConversationHandler.END

async def hug_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.message.edit_text("Обнимашка отменена.")
    await query.answer()
    return ConversationHandler.END

# ------------------------------------------------------------------------
# 12) Поиск пользователя по нику (/search)
# ------------------------------------------------------------------------
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты не в чате.")
        return

    if not context.args:
        await update.message.reply_text("[Бот] Используй: /search <текст>")
        return

    pattern = " ".join(context.args).lower()
    results = []
    for data in active_users.values():
        if pattern in data["nickname"].lower():
            results.append(f"{data['code']} {data['nickname']}")
    if results:
        await update.message.reply_text("[Бот] Найдено:\n" + "\n".join(results))
    else:
        await update.message.reply_text("[Бот] Совпадений не найдено.")
    refresh_user_activity(user_id)

# ------------------------------------------------------------------------
# 13) Опросы (/poll и /polldone)
# ------------------------------------------------------------------------
POLL_WAIT = range(1)

async def poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты не в чате.")
        return ConversationHandler.END

    await update.message.reply_text(
        "[Бот] Создаём опрос.\n"
        "Введи вопрос и варианты ответа, каждый с новой строки.\n"
        "Пример:\n"
        "Как дела?\n"
        "Хорошо\n"
        "Нормально\n"
        "/cancel - отменить."
    )
    refresh_user_activity(user_id)
    return POLL_WAIT

async def poll_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        return ConversationHandler.END

    text = update.message.text.strip()
    lines = text.split("\n")
    if len(lines) < 2:
        await update.message.reply_text("[Бот] Нужно указать вопрос и минимум один вариант ответа.")
        return ConversationHandler.END

    question = lines[0]
    options = lines[1:]
    active_polls[user_id] = {
        "question": question,
        "options": options,
        "votes": {opt: set() for opt in options},
        "active": True,
        "msg_ids": {},
        "chat_ids": {}
    }

    from_info = active_users[user_id]
    header = f"[Опрос от {from_info['code']} {from_info['nickname']}]:\n{question}"

    def build_poll_markup(creator_id):
        kb = []
        for idx, option in enumerate(options, start=1):
            btn_text = f"{idx} - {option}"
            kb.append([InlineKeyboardButton(btn_text, callback_data=f"pollvote|{creator_id}|{idx}")])
        return InlineKeyboardMarkup(kb)

    markup = build_poll_markup(user_id)
    for uid, data in active_users.items():
        try:
            msg = await context.application.bot.send_message(
                chat_id=data["chat_id"],
                text=header,
                reply_markup=markup
            )
            active_polls[user_id]["msg_ids"][uid] = msg.message_id
            active_polls[user_id]["chat_ids"][uid] = data["chat_id"]
        except Exception as err:
            logging.warning(f"Не удалось отправить опрос для {data['nickname']}: {err}")
    refresh_user_activity(user_id)
    return ConversationHandler.END

async def poll_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("[Бот] Опрос отменён.")
    return ConversationHandler.END

async def poll_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_polls or not active_polls[user_id]["active"]:
        await update.message.reply_text("[Бот] У тебя нет активного опроса.")
        return

    active_polls[user_id]["active"] = False
    await update.message.reply_text("[Бот] Опрос завершён.")

    # Удаляем кнопки из всех сообщений
    for uid, msg_id in active_polls[user_id]["msg_ids"].items():
        chat_id = active_polls[user_id]["chat_ids"][uid]
        try:
            await context.application.bot.edit_message_reply_markup(chat_id=chat_id, message_id=msg_id, reply_markup=None)
        except Exception:
            pass
    refresh_user_activity(user_id)

async def poll_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("|")
    if len(parts) != 3 or parts[0] != "pollvote":
        await query.answer("Ошибка.")
        return

    creator_id = int(parts[1])
    option_index = int(parts[2]) - 1
    voter_id = update.effective_user.id

    if creator_id not in active_polls:
        await query.answer("Опрос не найден или завершён.")
        return
    poll = active_polls[creator_id]
    if not poll["active"]:
        await query.answer("Опрос завершён.")
        return

    options = poll["options"]
    if option_index < 0 or option_index >= len(options):
        await query.answer("Неверный вариант.")
        return

    chosen = options[option_index]
    # Убираем предыдущие голоса
    for opt in options:
        poll["votes"][opt].discard(voter_id)
    poll["votes"][chosen].add(voter_id)
    await query.answer("Голос учтён!")

    # Формируем новый текст опроса с результатами
    lines = [poll["question"]]
    for idx, opt in enumerate(options, start=1):
        count = len(poll["votes"][opt])
        mark = "✔️" if count > 0 else f"{idx}"
        lines.append(f"{mark} - {opt} ({count})")
    new_text = "\n".join(lines)

    for uid, msg_id in poll["msg_ids"].items():
        chat_id = poll["chat_ids"][uid]
        try:
            await context.application.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=new_text,
                reply_markup=query.message.reply_markup
            )
        except Exception as err:
            logging.warning(f"Не удалось обновить опрос для {uid}: {err}")
    refresh_user_activity(voter_id)

# ------------------------------------------------------------------------
# 14) Настройки уведомлений (/notify)
# ------------------------------------------------------------------------
def build_notify_markup(user_id: int):
    settings = notification_settings[user_id]
    def flag_text(flag: bool):
        return "✅" if flag else "❌"
    kb = [
        [
            InlineKeyboardButton(f"{flag_text(settings['privates'])} Личные", callback_data="notify|privates"),
            InlineKeyboardButton(f"{flag_text(settings['replies'])} Ответы", callback_data="notify|replies"),
            InlineKeyboardButton(f"{flag_text(settings['hug'])} Обнимашки", callback_data="notify|hug")
        ]
    ]
    row = []
    for val in [0, 1, 5, 10, 20, 30]:
        mark = "✅" if settings["interval"] == val else "❌"
        row.append(InlineKeyboardButton(f"{mark} {val}", callback_data=f"notify|interval|{val}"))
    kb.append(row)
    kb.append([InlineKeyboardButton("❌ Отмена", callback_data="notify|cancel")])
    return InlineKeyboardMarkup(kb)

async def notify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Ты не в чате.")
        return
    initialize_user_settings(user_id)
    kb = build_notify_markup(user_id)
    await update.message.reply_text("[Бот] Настройки уведомлений:", reply_markup=kb)
    refresh_user_activity(user_id)

async def notify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    parts = query.data.split("|")
    if parts[0] != "notify":
        return

    if len(parts) == 2:
        if parts[1] == "cancel":
            await query.message.delete()
            return
        key = parts[1]
        notification_settings[user_id][key] = not notification_settings[user_id][key]
    elif len(parts) == 3 and parts[1] == "interval":
        val = int(parts[2])
        notification_settings[user_id]["interval"] = val
    else:
        await query.answer("Неизвестная настройка.")
        return

    new_kb = build_notify_markup(user_id)
    try:
        await query.message.edit_reply_markup(new_kb)
    except Exception:
        pass
    await query.answer("Настройка сохранена.")
    refresh_user_activity(user_id)

# ------------------------------------------------------------------------
# 15) Жалобы на сообщения (/report)
# ------------------------------------------------------------------------
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("[Бот] Используй: /report <код пользователя> <причина>")
        return
    code = context.args[0]
    reason = " ".join(context.args[1:])
    offender_id = None
    for uid, data in active_users.items():
        if data["code"].lower() == code.lower():
            offender_id = uid
            break
    if not offender_id:
        await update.message.reply_text("[Бот] Пользователь с таким кодом не найден.")
        return
    from_nick = active_users[user_id]["nickname"]
    reported_messages.append({
        "reporter": from_nick,
        "offender": active_users[offender_id]["nickname"],
        "reason": reason,
        "time": datetime.datetime.now()
    })
    await update.message.reply_text("[Бот] Твоя жалоба принята к рассмотрению.")
    logging.info(f"Жалоба от {from_nick} на {active_users[offender_id]['nickname']}: {reason}")
    refresh_user_activity(user_id)

# ------------------------------------------------------------------------
# 16) Обработка входящих сообщений (текст и фото)
# ------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_users:
        await update.message.reply_text("[Бот] Для начала работы введи /start.")
        return

    nick = active_users[user_id]["nickname"]
    code = active_users[user_id]["code"]

    # Если сообщение содержит фото
    if update.message.photo:
        photo = update.message.photo[-1]
        file_id = photo.file_id
        caption = update.message.caption if update.message.caption else ""
        full_caption = f"{code} {nick} отправил(а) фото"
        if caption:
            full_caption += f"\n{caption}"
        await broadcast_image(context.application, file_id, caption=full_caption, exclude_user=user_id)
        refresh_user_activity(user_id)
        return

    # Если текстовое сообщение
    text = update.message.text.strip()
    replied_nick = ""
    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.application.bot.id:
        replied_nick = extract_replied_nickname(update.message.reply_to_message.text)

    if text.startswith("%"):
        content = text[1:].lstrip()
        final_text = f"{nick} (в ответ на {replied_nick}) {content}" if replied_nick else f"{nick} {content}"
        await broadcast_message(context.application, final_text, exclude_user=user_id)
    else:
        final_text = f"{nick} (в ответ на {replied_nick}): {text}" if replied_nick else f"{nick}: {text}"
        await broadcast_message(context.application, final_text, exclude_user=user_id)
    refresh_user_activity(user_id)

# ------------------------------------------------------------------------
# 17) Установка команд бота (меню)
# ------------------------------------------------------------------------
async def set_commands(app_bot):
    cmds = [
        BotCommand("start", "Присоединиться к чату"),
        BotCommand("stop", "Покинуть чат"),
        BotCommand("nick", "Изменить ник"),
        BotCommand("list", "Список пользователей"),
        BotCommand("stats", "Статистика чата"),
        BotCommand("msg", "Отправить ЛС"),
        BotCommand("getmsg", "Получить ЛС"),
        BotCommand("hug", "Обнять"),
        BotCommand("search", "Поиск по нику"),
        BotCommand("poll", "Создать опрос"),
        BotCommand("polldone", "Завершить опрос"),
        BotCommand("notify", "Настройка уведомлений"),
        BotCommand("report", "Пожаловаться на сообщение"),
        BotCommand("ping", "Проверка бота"),
        BotCommand("rules", "Правила чата"),
        BotCommand("about", "О боте"),
        BotCommand("help", "Справка")
    ]
    await app_bot.bot.set_my_commands(cmds)

async def post_init(app_bot):
    await set_commands(app_bot)

# ------------------------------------------------------------------------
# 18) ГЛАВНАЯ ФУНКЦИЯ
# ------------------------------------------------------------------------
def main():
    # Запускаем сервер для keep-alive
    start_keep_alive()

    # Создаём Telegram-приложение
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    logging.info("Запуск бота...")

    # ConversationHandler для смены ника
    nick_conv = ConversationHandler(
        entry_points=[CommandHandler("nick", change_nick_start)],
        states={
            NICK_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_nick_process)]
        },
        fallbacks=[CommandHandler("cancel", cancel_nick_change)]
    )

    # ConversationHandler для ЛС (/msg)
    dm_conv = ConversationHandler(
        entry_points=[CommandHandler("msg", dm_command_start)],
        states={
            MSG_SELECT: [
                CallbackQueryHandler(dm_select_callback, pattern="^dm_select\\|"),
                CallbackQueryHandler(dm_cancel_callback, pattern="^dm_cancel$")
            ],
            MSG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, dm_text_receive)]
        },
        fallbacks=[CallbackQueryHandler(dm_cancel_callback, pattern="^dm_cancel$")]
    )

    # ConversationHandler для опроса (/poll)
    poll_conv = ConversationHandler(
        entry_points=[CommandHandler("poll", poll_command)],
        states={
            POLL_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, poll_receive_text)]
        },
        fallbacks=[CommandHandler("cancel", poll_cancel)]
    )

    # ConversationHandler для обнимашек (/hug)
    hug_conv = ConversationHandler(
        entry_points=[CommandHandler("hug", hug_command)],
        states={
            HUG_SELECT: [
                CallbackQueryHandler(hug_select_callback, pattern="^hug_select\\|"),
                CallbackQueryHandler(hug_cancel_callback, pattern="^hug_cancel$")
            ]
        },
        fallbacks=[CallbackQueryHandler(hug_cancel_callback, pattern="^hug_cancel$")]
    )

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(nick_conv)
    application.add_handler(CommandHandler("list", list_users_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(dm_conv)
    application.add_handler(CommandHandler("getmsg", get_dm_command))
    application.add_handler(hug_conv)
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(poll_conv)
    application.add_handler(CommandHandler("polldone", poll_finish))
    application.add_handler(CommandHandler("notify", notify_command))
    application.add_handler(CallbackQueryHandler(notify_callback, pattern="^notify\\|"))
    application.add_handler(CallbackQueryHandler(poll_vote_callback, pattern="^pollvote\\|"))
    application.add_handler(CommandHandler("report", report_command))

    # Обработка сообщений (текст и фото)
    application.add_handler(MessageHandler(~filters.COMMAND & (filters.TEXT | filters.PHOTO), handle_message))

    # post_init для установки команд меню
    application.post_init = post_init

    # Запуск polling
    application.run_polling()

if __name__ == "__main__":
    main()
