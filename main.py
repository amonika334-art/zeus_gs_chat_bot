
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
    if not update.message:
        return False
    chat = update.message.chat
    user = update.message.from_user
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
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
    if not context.args:
        return await update.message.reply_text("Формат: /allow @username [topic_id]. Можна без topic_id, якщо вводиш у гілці.")
    username = _norm_username(context.args[0])
    if not username:
        return await update.message.reply_text("⛔ Вкажи коректний @username.")
    topic_id = _get_topic_id_from_context(update, context.args[1:])
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")

    users = allowed_users_per_topic.setdefault(topic_id, [])
    if username not in users:
        users.append(username)
        await update.message.reply_text(f"✅ @{username} молодець, ти дзе бест, тільки ніякого контента 18+ {topic_id}")
    else:
        await update.message.reply_text(f"ℹ️ @{username} ай да молодець, як у такій бусі мона доступ забрати {topic_id}")

@require_admin
async def deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Формат: /deny @username [topic_id]. Можна без topic_id, якщо вводиш у гілці.")
    username = _norm_username(context.args[0])
    if not username:
        return await update.message.reply_text("⛔ Вкажи коректний @username.")
    topic_id = _get_topic_id_from_context(update, context.args[1:])
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")

    users = allowed_users_per_topic.setdefault(topic_id, [])
    if username in users:
        users.remove(username)
        await update.message.reply_text(f"🚫 @{username} нє нє, тобі сюди не мона писати {topic_id}")
    else:
        await update.message.reply_text(f"ℹ️ @{username} айяй, не мона, значит не мона {topic_id}")

@require_admin
async def set_autodelete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Формат: /set_autodelete <секунди> [topic_id]")
    try:
        seconds = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("⛔ <секунди> мають бути числом.")
    topic_id = _get_topic_id_from_context(update, context.args[1:])
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")

    auto_delete_settings[topic_id] = max(0, seconds)
    if seconds > 0:
        await update.message.reply_text(f"♻️ Автоочищення для гілки {topic_id}: {seconds} сек.")
    else:
        await update.message.reply_text(f"♻️ Автоочищення вимкнено для гілки {topic_id}.")

@require_admin
async def list_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_users_per_topic and not auto_delete_settings:
        return await update.message.reply_text("📭 Немає налаштувань доступів або автоочищення.")
    lines = ["📌 Налаштування:"]
    topic_ids = sorted(set(allowed_users_per_topic.keys()) | set(auto_delete_settings.keys()))
    for tid in topic_ids:
        users = allowed_users_per_topic.get(tid, None)
        clean = auto_delete_settings.get(tid, 0)
        if users is None:
            users_str = "(не контролюється)"
        else:
            users_str = ", ".join(f"@{u}" for u in users) if users else "— (заборонено всім)"
        lines.append(f"— Гілка {tid}: доступ: {users_str}; автоочищення: {clean}s")
    await update.message.reply_text("\n".join(lines))

@require_admin
async def deny_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заблокировать всех пользователей в ветке"""
    topic_id = _get_topic_id_from_context(update, context.args)
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")
    
    # Устанавливаем пустой список - значит запрещено всем
    allowed_users_per_topic[topic_id] = []
    await update.message.reply_text(f"🚫 Всі користувачі заблоковані в гілці {topic_id}")

@require_admin
async def allow_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разблокировать всех пользователей в ветке"""
    topic_id = _get_topic_id_from_context(update, context.args)
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")
    
    # Удаляем запись о ветке - значит доступ открыт всем
    if topic_id in allowed_users_per_topic:
        del allowed_users_per_topic[topic_id]
        await update.message.reply_text(f"✅ Всі користувачі розблоковані в гілці {topic_id}")
    else:
        await update.message.reply_text(f"ℹ️ Гілка {topic_id} не має обмежень доступу")

@require_admin
async def toggle_restricted_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включить/выключить режим ограниченного доступа для ветки"""
    topic_id = _get_topic_id_from_context(update, context.args)
    if not topic_id:
        return await update.message.reply_text("Не бачу ID гілки. Вкажи його або виконай команду прямо в потрібній гілці.")
    if topic_id in allowed_users_per_topic:
        # Если режим включен - выключаем (удаляем ограничения)
        del allowed_users_per_topic[topic_id]
        await update.message.reply_text(f"🔓 Режим обмеженого доступу вимкнено для гілки {topic_id}. Всі можуть писати.")
    else:
        # Если режим выключен - включаем (блокируем всех)
        allowed_users_per_topic[topic_id] = []
        await update.message.reply_text(f"🔒 Режим обмеженого доступу увімкнено для гілки {topic_id}. Тільки дозволені користувачі можуть писати.")

@require_admin
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответить на сообщение из другой темы"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    if not context.args or len(context.args) < 2:
        return await update.message.reply_text(
            "📝 Формат: /r <topic_id> <текст_ответа>\n\n"
            "Пример: /r 123 Привет! Это ответ из другой темы.\n\n"
            "💡 Используйте эту команду чтобы ответить на сообщения из других тем."
        )
    
    try:
        topic_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ ID темы должен быть числом!")
    
    # Получаем текст ответа (все аргументы после topic_id)
    reply_text = " ".join(context.args[1:])
    
    if not reply_text.strip():
        return await update.message.reply_text("❌ Введите текст для ответа!")
    
    try:
        # Отправляем сообщение в указанную тему
        chat_id = update.message.chat.id
        
        # Формируем сообщение с информацией об отправителе
        sender_name = update.message.from_user.first_name
        sender_username = update.message.from_user.username
        sender_info = f"@{sender_username}" if sender_username else sender_name
        
        formatted_reply = f"💬 **Ответ от {sender_info}:**\n\n{reply_text}"
        
        # Отправляем сообщение в указанную тему
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=formatted_reply,
            message_thread_id=topic_id,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Admin {user_info} sent reply to topic {topic_id}: {reply_text[:50]}...")
        
        # Подтверждаем отправку
        await update.message.reply_text(
            f"✅ Ответ отправлен в тему {topic_id}!\n\n"
            f"📝 Текст: {reply_text[:100]}{'...' if len(reply_text) > 100 else ''}"
        )
        
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Error sending reply to topic {topic_id}: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при отправке ответа в тему {topic_id}:\n{str(e)}"
        )

@require_admin
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все темы в чате"""
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    try:
        chat_id = update.message.chat.id
        
        # Получаем информацию о чате
        chat = await context.bot.get_chat(chat_id)
        
        if not chat.is_forum:
            return await update.message.reply_text("❌ Этот чат не является форумом! Команда работает только в форумах с темами.")
        
        # Получаем активные темы (последние 20)
        try:
            # Используем get_forum_topic_icon_stickers для получения информации о темах
            # К сожалению, Telegram API не предоставляет прямой доступ к списку тем
            # Поэтому показываем инструкцию
            await update.message.reply_text(
                "📋 **Как узнать ID темы:**\n\n"
                "1️⃣ **В теме:** ID темы показывается в заголовке\n"
                "2️⃣ **Из сообщения:** ID темы = message_thread_id\n"
                "3️⃣ **Команда /r:** используйте ID темы для ответа\n\n"
                "💡 **Пример использования:**\n"
                "`/r 123 Привет! Это ответ из другой темы.`\n\n"
                "🔍 **Чтобы найти ID темы:**\n"
                "• Перейдите в нужную тему\n"
                "• ID будет в заголовке или URL\n"
                "• Или используйте любое сообщение из темы"
            )
            
            logger.info(f"📋 Admin {user_info} requested topics list")
            
        except Exception as e:
            logger.error(f"❌ Error getting topics: {e}")
            await update.message.reply_text("❌ Ошибка при получении списка тем.")
            
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Error in list_topics: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global message_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    logger.info(f"🔔 Received /start command from user {user_info}")
    
    try:
        await update.message.reply_text(
            "🤖 Бот запущен!\n\n"
            "📋 Доступные команды (только для администраторов):\n"
            "• /allow @username [topic_id] - разрешить доступ пользователю\n"
            "• /deny @username [topic_id] - запретить доступ пользователю\n"
            "• /deny_all [topic_id] - заблокировать ВСЕХ пользователей\n"
            "• /allow_all [topic_id] - разблокировать ВСЕХ пользователей\n"
            "• /toggle_restricted [topic_id] - включить/выключить режим ограничений\n"
            "• /set_autodelete <секунды> [topic_id] - настроить автоудаление\n"
            "• /list - показать текущие настройки\n"
            "• /topics - как узнать ID тем\n"
            "• /r <topic_id> <текст> - ответить на сообщение из другой темы\n\n"
            "ℹ️ Принцип работы: если для ветки есть запись в списке доступов — писать могут только пользователи из этого списка. "
            "Пустой список = запрещено всем.\n\n"
            "💡 Команда /r решает проблему с пересылкой сообщений между темами на iOS!"
        )
        logger.info(f"✅ Start response sent successfully to user {user_info}")
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Error sending start response to user {user_info}: {e}")
        await update.message.reply_text("❌ Произошла ошибка при запуске бота")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global message_count
    message_count += 1
    
    if not update.message or not update.message.is_topic_message:
        return
    if update.message.from_user and update.message.from_user.is_bot:
        return
        
    topic_id = update.message.message_thread_id
    sender_username = _norm_username(update.message.from_user.username)
    
    logger.info(f"📨 Processing message from @{sender_username} in topic {topic_id}")

    # Администраторы всегда могут писать
    if await _is_chat_admin(update, context):
        logger.info(f"👑 Admin @{sender_username} message allowed in topic {topic_id}")
        pass
    else:
        # Если для ветки есть ограничения доступа
        if topic_id in allowed_users_per_topic:
            # Проверяем, есть ли пользователь в списке разрешенных
            if sender_username not in allowed_users_per_topic[topic_id]:
                try:
                    await update.message.delete()
                    logger.info(f"🚫 Deleted message from @{sender_username} in topic {topic_id} (no access)")
                except Exception as e:
                    error_count += 1
                    logger.error(f"❌ Error deleting message from @{sender_username} in topic {topic_id}: {e}")
                return
            else:
                logger.info(f"✅ User @{sender_username} message allowed in topic {topic_id}")
        else:
            # Если для ветки нет ограничений - все могут писать
            logger.info(f"✅ User @{sender_username} message allowed in topic {topic_id} (no restrictions)")
            pass

    # Применяем автоудаление если настроено
    delay = auto_delete_settings.get(topic_id, 0)
    if delay > 0:
        logger.info(f"⏰ Auto-delete scheduled for message in topic {topic_id} in {delay}s")
        asyncio.create_task(delete_after_delay(update, context, delay))

async def delete_after_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, delay: int):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    except Exception:
        pass

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
    """Health check endpoint for Render"""
    stats = get_stats()
    status_text = f"""🤖 Bot Status: RUNNING
⏱️ Uptime: {stats['uptime']}
📊 Messages processed: {stats['messages_processed']}
❌ Errors: {stats['errors']}
🕐 Last update: {stats['timestamp']}
✅ Bot is healthy and running!"""
    
    return web.Response(text=status_text, content_type="text/plain")

async def start_web_server():
    """Start web server for Render health checks"""
    app = web.Application()
    app.router.add_get("/", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    print(f"Web server listening on port {port}")
    return runner

async def keep_alive_ping():
    """Отправляет ping каждые 10 минут чтобы сервис не засыпал"""
    while True:
        await asyncio.sleep(600)  # 10 минут
        try:
            # Отправляем ping на свой же endpoint
            async with ClientSession() as session:
                async with session.get('http://localhost:10000/') as resp:
                    logger.info(f"🔄 Keep-alive ping: status {resp.status}")
        except Exception as e:
            logger.error(f"❌ Keep-alive error: {e}")

async def main_async():
    logger.info("🤖 Starting Telegram bot...")
    logger.info(f"🔑 Using token: {TOKEN[:20]}...")
    
    web_runner = None
    try:
        # Start web server first
        web_runner = await start_web_server()
        logger.info("🌐 Web server started successfully")
        
        # Initialize bot
        await application.initialize()
        logger.info("✅ Application initialized")
        
        await application.start()
        logger.info("✅ Application started")
        
        logger.info("🤖 Telegram bot started, starting polling...")
        # Start polling in background
        await application.updater.start_polling()
        logger.info("✅ Polling started successfully")
        
        # Start keep-alive ping
        logger.info("🔄 Starting keep-alive ping to prevent sleep...")
        asyncio.create_task(keep_alive_ping())
        
        # Keep running with monitoring
        logger.info("🔄 Bot is now running and monitoring messages...")
        while True:
            await asyncio.sleep(60)  # Логируем каждую минуту
            stats = get_stats()
            logger.info(f"📊 Bot status: {stats['uptime']} uptime, {stats['messages_processed']} messages, {stats['errors']} errors")
            
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Critical error in main_async: {e}")
        raise
    finally:
        # Cleanup
        logger.info("🧹 Starting cleanup...")
        if web_runner:
            await web_runner.cleanup()
            logger.info("🌐 Web server stopped")
        await application.stop()
        await application.shutdown()
        logger.info("🤖 Bot stopped and cleaned up")

if __name__ == "__main__":
    asyncio.run(main_async())
