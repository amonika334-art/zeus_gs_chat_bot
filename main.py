
# main.py — user's bot logic wrapped for Render Web Service (Free)
import os
import asyncio
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from aiohttp import web, ClientSession

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# load_dotenv()
# load_dotenv(dotenv_path="env/config")
TOKEN = "7730139842:AAF8mnKPvwL2I0LYGtFABBBjFZoxx4D77RY"
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не знайдено. Додай його в Environment на Render або у .env/env локально.")

# Глобальные переменные для мониторинга
start_time = time.time()
message_count = 0
error_count = 0

def get_uptime():
    """Получить время работы бота"""
    uptime = time.time() - start_time
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    seconds = int(uptime % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def get_stats():
    """Получить статистику бота"""
    return {
        "uptime": get_uptime(),
        "messages_processed": message_count,
        "errors": error_count,
        "timestamp": datetime.now().isoformat()
    }

allowed_users_per_topic: dict[int, list[str]] = {}
auto_delete_settings: dict[int, int] = {}

def _get_topic_id_from_context(update: Update, args: list[str]) -> int | None:
    if args:
        try:
            return int(args[-1])
        except ValueError:
            pass
    if update.message and update.message.is_topic_message:
        return update.message.message_thread_id
    return None

async def _is_chat_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Перевірити чи є користувач адміністратором чату"""
    if not update.message:
        return False
    chat = update.message.chat
    user = update.message.from_user
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        is_admin = member.status in ("administrator", "creator")
        if is_admin:
            logger.debug(f"👑 Користувач @{user.username} є адміністратором у чаті {chat.id}")
        return is_admin
    except Exception as e:
        logger.error(f"❌ Помилка перевірки статусу адміністратора для користувача @{user.username} у чаті {chat.id}: {e}")
        return False

def require_admin(func):
    """Декоратор для проверки прав администратора"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await _is_chat_admin(update, context):
            await update.message.reply_text("⛔ У вас нет прав администратора для использования этой команды!")
            return
        return await func(update, context)
    return wrapper

def _norm_username(u: str | None) -> str:
    return (u or "").lstrip("@").lower().strip()

@require_admin
async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Дозволити доступ користувачу до теми"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    if not context.args:
        return await update.message.reply_text("📝 Формат: /allow @username [topic_id]. Можна без topic_id, якщо вводиш у гілці.")
    username = _norm_username(context.args[0])
    if not username:
        return await update.message.reply_text("⛔ Вкажи коректний @username.")
    topic_id = _get_topic_id_from_context(update, context.args[1:])
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")

    users = allowed_users_per_topic.setdefault(topic_id, [])
    if username not in users:
        users.append(username)
        logger.info(f"✅ Admin {user_info} дозволив користувачу @{username} в темі {topic_id}")
        await update.message.reply_text(f"✅ @{username} молодець, ти дзе бест, тільки ніякого контента 18+ {topic_id}")
    else:
        logger.info(f"ℹ️ Admin {user_info} намагався дозволити вже дозволеному користувачу @{username} в темі {topic_id}")
        await update.message.reply_text(f"ℹ️ @{username} ай да молодець, як у такій бусі мона доступ забрати {topic_id}")

@require_admin
async def deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заборонити доступ користувачу до теми"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    if not context.args:
        return await update.message.reply_text("📝 Формат: /deny @username [topic_id]. Можна без topic_id, якщо вводиш у гілці.")
    username = _norm_username(context.args[0])
    if not username:
        return await update.message.reply_text("⛔ Вкажи коректний @username.")
    topic_id = _get_topic_id_from_context(update, context.args[1:])
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")

    users = allowed_users_per_topic.setdefault(topic_id, [])
    if username in users:
        users.remove(username)
        logger.info(f"🚫 Admin {user_info} заборонив користувачу @{username} в темі {topic_id}")
        await update.message.reply_text(f"🚫 @{username} нє нє, тобі сюди не мона писати {topic_id}")
    else:
        logger.info(f"ℹ️ Admin {user_info} намагався заборонити вже забороненому користувачу @{username} в темі {topic_id}")
        await update.message.reply_text(f"ℹ️ @{username} айяй, не мона, значит не мона {topic_id}")

@require_admin
async def set_autodelete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Налаштувати автоочищення повідомлень"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    if not context.args:
        return await update.message.reply_text("📝 Формат: /set_autodelete <секунди> [topic_id]")
    try:
        seconds = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("⛔ <секунди> мають бути числом.")
    topic_id = _get_topic_id_from_context(update, context.args[1:])
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")

    auto_delete_settings[topic_id] = max(0, seconds)
    if seconds > 0:
        logger.info(f"⏰ Admin {user_info} налаштував автоочищення для теми {topic_id}: {seconds} сек.")
        await update.message.reply_text(f"♻️ Автоочищення для гілки {topic_id}: {seconds} сек.")
    else:
        logger.info(f"⏰ Admin {user_info} вимкнув автоочищення для теми {topic_id}")
        await update.message.reply_text(f"♻️ Автоочищення вимкнено для гілки {topic_id}.")

@require_admin
async def list_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показати поточні налаштування доступів"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    if not allowed_users_per_topic and not auto_delete_settings:
        return await update.message.reply_text("📭 Немає налаштувань доступів або автоочищення.")
    
    lines = ["📌 **Поточні налаштування:**"]
    topic_ids = sorted(set(allowed_users_per_topic.keys()) | set(auto_delete_settings.keys()))
    
    for tid in topic_ids:
        users = allowed_users_per_topic.get(tid, None)
        clean = auto_delete_settings.get(tid, 0)
        
        if users is None:
            users_str = "(не контролюється)"
        else:
            users_str = ", ".join(f"@{u}" for u in users) if users else "— (заборонено всім)"
        
        lines.append(f"**— Тема {tid}:** доступ: {users_str}; автоочищення: {clean}с")
    
    logger.info(f"📋 Admin {user_info} переглянув налаштування доступів")
    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')

@require_admin
async def deny_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заблокувати всіх користувачів у темі"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    topic_id = _get_topic_id_from_context(update, context.args)
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")
    
    # Встановлюємо порожній список - значить заборонено всім
    allowed_users_per_topic[topic_id] = []
    logger.info(f"🚫 Admin {user_info} заблокував всіх користувачів у темі {topic_id}")
    await update.message.reply_text(f"🚫 Всі користувачі заблоковані в гілці {topic_id}")

@require_admin
async def allow_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Розблокувати всіх користувачів у темі"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    topic_id = _get_topic_id_from_context(update, context.args)
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")
    
    # Видаляємо запис про тему - значить доступ відкритий всім
    if topic_id in allowed_users_per_topic:
        del allowed_users_per_topic[topic_id]
        logger.info(f"✅ Admin {user_info} розблокував всіх користувачів у темі {topic_id}")
        await update.message.reply_text(f"✅ Всі користувачі розблоковані в гілці {topic_id}")
    else:
        logger.info(f"ℹ️ Admin {user_info} намагався розблокувати тему {topic_id} без обмежень")
        await update.message.reply_text(f"ℹ️ Гілка {topic_id} не має обмежень доступу")

@require_admin
async def toggle_restricted_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Увімкнути/вимкнути режим обмеженого доступу для теми"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    topic_id = _get_topic_id_from_context(update, context.args)
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")
    
    if topic_id in allowed_users_per_topic:
        # Якщо режим увімкнено - вимикаємо (видаляємо обмеження)
        del allowed_users_per_topic[topic_id]
        logger.info(f"🔓 Admin {user_info} вимкнув режим обмеженого доступу для теми {topic_id}")
        await update.message.reply_text(f"🔓 Режим обмеженого доступу вимкнено для гілки {topic_id}. Всі можуть писати.")
    else:
        # Якщо режим вимкнено - увімикаємо (блокуємо всіх)
        allowed_users_per_topic[topic_id] = []
        logger.info(f"🔒 Admin {user_info} увімкнув режим обмеженого доступу для теми {topic_id}")
        await update.message.reply_text(f"🔒 Режим обмеженого доступу увімкнено для гілки {topic_id}. Тільки дозволені користувачі можуть писати.")

@require_admin
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Відповісти на повідомлення з іншої теми"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    if not context.args or len(context.args) < 2:
        return await update.message.reply_text(
            "📝 **Формат:** `/r <topic_id> <текст_відповіді>`\n\n"
            "**Приклад:** `/r 123 Привіт! Це відповідь з іншої теми.`\n\n"
            "💡 **Використовуйте цю команду щоб відповісти на повідомлення з інших тем.**\n\n"
            "🇺🇦 **Працює українською мовою!**"
        , parse_mode='Markdown')
    
    try:
        topic_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ ID теми має бути числом!")
    
    # Отримуємо текст відповіді (всі аргументи після topic_id)
    reply_text = " ".join(context.args[1:])
    
    if not reply_text.strip():
        return await update.message.reply_text("❌ Введіть текст для відповіді!")
    
    try:
        # Відправляємо повідомлення в вказану тему
        chat_id = update.message.chat.id
        
        # Формуємо повідомлення з інформацією про відправника
        sender_name = update.message.from_user.first_name
        sender_username = update.message.from_user.username
        sender_info = f"@{sender_username}" if sender_username else sender_name
        
        formatted_reply = f"💬 **Відповідь від {sender_info}:**\n\n{reply_text}"
        
        # Відправляємо повідомлення в вказану тему
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=formatted_reply,
            message_thread_id=topic_id,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Адмін {user_info} відправив відповідь у тему {topic_id}: {reply_text[:50]}...")
        
        # Підтверджуємо відправку
        await update.message.reply_text(
            f"✅ **Відповідь відправлено у тему {topic_id}!**\n\n"
            f"📝 **Текст:** {reply_text[:100]}{'...' if len(reply_text) > 100 else ''}\n\n"
            f"🇺🇦 **Команда працює українською!**"
        , parse_mode='Markdown')
        
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Помилка при відправці відповіді у тему {topic_id}: {e}")
        await update.message.reply_text(
            f"❌ **Помилка при відправці відповіді у тему {topic_id}:**\n{str(e)}"
        )

@require_admin
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показати всі теми у чаті"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    try:
        chat_id = update.message.chat.id
        
        # Отримуємо інформацію про чат
        chat = await context.bot.get_chat(chat_id)
        
        if not chat.is_forum:
            return await update.message.reply_text("❌ Цей чат не є форумом! Команда працює тільки у форумах з темами.")
        
        # Отримуємо активні теми (останні 20)
        try:
            # Використовуємо get_forum_topic_icon_stickers для отримання інформації про теми
            # На жаль, Telegram API не надає прямий доступ до списку тем
            # Тому показуємо інструкцію
            await update.message.reply_text(
                "📋 **Як дізнатися ID теми:**\n\n"
                "1️⃣ **У темі:** ID теми показується у заголовку\n"
                "2️⃣ **З повідомлення:** ID теми = message_thread_id\n"
                "3️⃣ **Команда `/r`:** використовуйте ID теми для відповіді\n\n"
                "💡 **Приклад використання:**\n"
                "`/r 123 Привіт! Це відповідь з іншої теми.`\n\n"
                "🔍 **Щоб знайти ID теми:**\n"
                "• Перейдіть у потрібну тему\n"
                "• ID буде у заголовку або URL\n"
                "• Або використовуйте будь-яке повідомлення з теми\n\n"
                "🇺🇦 **Працює українською мовою!**"
            , parse_mode='Markdown')
            
            logger.info(f"📋 Адмін {user_info} запитав список тем")
            
        except Exception as e:
            logger.error(f"❌ Помилка отримання тем: {e}")
            await update.message.reply_text("❌ Помилка при отриманні списку тем.")
            
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Помилка в list_topics: {e}")
        await update.message.reply_text(f"❌ Помилка: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    logger.info(f"🔔 Отримано команду /start від користувача {user_info}")
    
    try:
        await update.message.reply_text(
            "🤖 **Бот запущений!**\n\n"
            "📋 **Доступні команди (тільки для адміністраторів):**\n"
            "• `/allow @username [topic_id]` - дозволити доступ користувачу\n"
            "• `/deny @username [topic_id]` - заборонити доступ користувачу\n"
            "• `/deny_all [topic_id]` - заблокувати ВСІХ користувачів\n"
            "• `/allow_all [topic_id]` - розблокувати ВСІХ користувачів\n"
            "• `/toggle_restricted [topic_id]` - увімкнути/вимкнути режим обмежень\n"
            "• `/set_autodelete <секунди> [topic_id]` - налаштувати автоочищення\n"
            "• `/list` - показати поточні налаштування\n"
            "• `/topics` - як дізнатися ID тем\n"
            "• `/r <topic_id> <текст>` - відповісти на повідомлення з іншої теми\n\n"
            "ℹ️ **Принцип роботи:** якщо для теми є запис у списку доступів — писати можуть тільки користувачі з цього списку. "
            "Порожній список = заборонено всім.\n\n"
            "💡 **Команда `/r` вирішує проблему з пересиланням повідомлень між темами на iOS!**\n\n"
            "🇺🇦 **Бот працює українською мовою!**"
        , parse_mode='Markdown')
        logger.info(f"✅ Відповідь на /start відправлено успішно користувачу {user_info}")
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Помилка при відправці відповіді на /start користувачу {user_info}: {e}")
        await update.message.reply_text("❌ Сталася помилка при запуску бота")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global message_count
    message_count += 1
    
    if not update.message or not update.message.is_topic_message:
        return
    if update.message.from_user and update.message.from_user.is_bot:
        return
        
    topic_id = update.message.message_thread_id
    sender_username = _norm_username(update.message.from_user.username)
    
    logger.info(f"📨 Обробка повідомлення від @{sender_username} у темі {topic_id}")

    # Адміністратори завжди можуть писати
    if await _is_chat_admin(update, context):
        logger.info(f"👑 Адмін @{sender_username} повідомлення дозволено у темі {topic_id}")
        pass
    else:
        # Якщо для теми є обмеження доступу
        if topic_id in allowed_users_per_topic:
            # Перевіряємо, чи є користувач у списку дозволених
            if sender_username not in allowed_users_per_topic[topic_id]:
                try:
                    await update.message.delete()
                    logger.info(f"🚫 Видалено повідомлення від @{sender_username} у темі {topic_id} (немає доступу)")
                except Exception as e:
                    error_count += 1
                    logger.error(f"❌ Помилка при видаленні повідомлення від @{sender_username} у темі {topic_id}: {e}")
                return
            else:
                logger.info(f"✅ Користувач @{sender_username} повідомлення дозволено у темі {topic_id}")
        else:
            # Якщо для теми немає обмежень - всі можуть писати
            logger.info(f"✅ Користувач @{sender_username} повідомлення дозволено у темі {topic_id} (немає обмежень)")
            pass

    # Застосовуємо автоочищення якщо налаштовано
    delay = auto_delete_settings.get(topic_id, 0)
    if delay > 0:
        logger.info(f"⏰ Автоочищення заплановано для повідомлення у темі {topic_id} через {delay}с")
        asyncio.create_task(delete_after_delay(update, context, delay))

async def delete_after_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, delay: int):
    """Автоматично видалити повідомлення через вказаний час"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
        logger.info(f"🗑️ Автоматично видалено повідомлення {update.message.message_id} у чаті {update.message.chat_id} через {delay}с")
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Помилка автоматичного видалення повідомлення {update.message.message_id}: {e}")

# Telegram app
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("allow", allow))
application.add_handler(CommandHandler("deny", deny))
application.add_handler(CommandHandler("deny_all", deny_all))
application.add_handler(CommandHandler("allow_all", allow_all))
application.add_handler(CommandHandler("toggle_restricted", toggle_restricted_mode))
application.add_handler(CommandHandler("set_autodelete", set_autodelete))
application.add_handler(CommandHandler("list", list_access))
application.add_handler(CommandHandler("r", reply)) # Добавляем обработчик для команды /r
application.add_handler(CommandHandler("topics", list_topics)) # Добавляем обработчик для команды /topics
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

async def health_check(request):
    """Endpoint для перевірки здоров'я Render"""
    stats = get_stats()
    status_text = f"""🤖 **Статус бота: ПРАЦЮЄ**
⏱️ **Час роботи:** {stats['uptime']}
📊 **Оброблено повідомлень:** {stats['messages_processed']}
❌ **Помилок:** {stats['errors']}
🕐 **Останнє оновлення:** {stats['timestamp']}
✅ **Бот здоровий та працює!**
🇺🇦 **Мова: Українська**"""
    
    return web.Response(text=status_text, content_type="text/plain")

async def start_web_server():
    """Запустити веб-сервер для перевірок здоров'я Render"""
    app = web.Application()
    app.router.add_get("/", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info(f"🌐 Веб-сервер прослуховує порт {port}")
    return runner

async def keep_alive_ping():
    """Відправляє ping кожні 10 хвилин щоб сервіс не засинав"""
    while True:
        await asyncio.sleep(600)  # 10 хвилин
        try:
            # Відправляємо ping на свій же endpoint
            async with ClientSession() as session:
                async with session.get('http://localhost:10000/') as resp:
                    logger.info(f"🔄 Keep-alive ping: статус {resp.status}")
        except Exception as e:
            logger.error(f"❌ Помилка keep-alive: {e}")

async def main_async():
    logger.info("🤖 Запуск Telegram бота...")
    logger.info(f"🔑 Використовуємо токен: {TOKEN[:20]}...")
    
    web_runner = None
    try:
        # Спочатку запускаємо веб-сервер
        web_runner = await start_web_server()
        logger.info("🌐 Веб-сервер успішно запущено")
        
        # Ініціалізуємо бота
        await application.initialize()
        logger.info("✅ Додаток ініціалізовано")
        
        await application.start()
        logger.info("✅ Додаток запущено")
        
        logger.info("🤖 Telegram бот запущений, починаємо polling...")
        # Запускаємо polling у фоновому режимі
        await application.updater.start_polling()
        logger.info("✅ Polling успішно запущено")
        
        # Запускаємо keep-alive ping
        logger.info("🔄 Запуск keep-alive ping для запобігання сну...")
        asyncio.create_task(keep_alive_ping())
        
        # Продовжуємо роботу з моніторингом
        logger.info("🔄 Бот тепер працює та моніторить повідомлення...")
        while True:
            await asyncio.sleep(60)  # Логуємо кожну хвилину
            stats = get_stats()
            logger.info(f"📊 Статус бота: {stats['uptime']} час роботи, {stats['messages_processed']} повідомлень, {stats['errors']} помилок")
            
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Критична помилка в main_async: {e}")
        raise
    finally:
        # Очищення
        logger.info("🧹 Початок очищення...")
        if web_runner:
            await web_runner.cleanup()
            logger.info("🌐 Веб-сервер зупинено")
        await application.stop()
        await application.shutdown()
        logger.info("🤖 Бот зупинено та очищено")

if __name__ == "__main__":
    asyncio.run(main_async())
