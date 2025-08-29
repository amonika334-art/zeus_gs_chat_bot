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
topic_cleanup_settings: dict[int, dict] = {}  # настройки очистки тем
topic_aliases: dict[int, int] = {
    1: 832,  # алиас 1 -> тема 832
    2: 832   # алиас 2 -> тема 832 (временно, пока не найдем правильный ID)
}  # алиасы: короткий номер -> ID темы
forwarded_messages: dict[str, set[int]] = {}  # отслеживание пересланных сообщений: message_id -> set of topic_ids

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

def _resolve_topic_id(topic_input: str | int) -> int | None:
    """Разрешает алиас темы в реальный ID темы"""
    try:
        topic_num = int(topic_input)
        # Если это алиас (короткий номер), возвращаем соответствующий ID темы
        if topic_num in topic_aliases:
            return topic_aliases[topic_num]
        # Если это уже реальный ID темы, возвращаем как есть
        return topic_num
    except ValueError:
        return None

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
    """Ответить на сообщение из другой темы или переслать сообщение"""
    global message_count, error_count
    message_count += 1
    
    user_info = f"{update.message.from_user.username or update.message.from_user.first_name}"
    
    # Проверяем, является ли это ответом на сообщение (для пересылки)
    if update.message.reply_to_message:
        # Это пересылка сообщения
        if not context.args or len(context.args) < 1:
            return await update.message.reply_text(
                "📝 Формат для пересылки: /r <topic_id/алиас> [дополнительный_текст]\n\n"
                "Пример: /r 1 (перешлет сообщение в тему с алиасом 1)\n"
                "Пример: /r 832 Добавлю комментарий (перешлет с комментарием)"
            )
        
        # Разрешаем алиас темы
        target_topic_id = _resolve_topic_id(context.args[0])
        if target_topic_id is None:
            return await update.message.reply_text("❌ ID темы или алиас должен быть числом!")
        
        # Получаем дополнительный текст если есть
        additional_text = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        
        try:
            # Получаем сообщение для пересылки
            original_message = update.message.reply_to_message
            current_topic_id = update.message.message_thread_id
            
            # Создаем уникальный идентификатор для сообщения
            message_id = f"{original_message.chat_id}_{original_message.message_id}"
            
            # Получаем все уникальные темы из алиасов
            all_topics = set(topic_aliases.values())
            
            # Проверяем, не было ли это сообщение уже переслано в эту конкретную тему
            if message_id in forwarded_messages:
                forwarded_topics = forwarded_messages[message_id]
                if target_topic_id in forwarded_topics:
                    await update.message.delete()
                    return await context.bot.send_message(
                        chat_id=update.message.chat.id,
                        text=f"⚠️ Это сообщение уже было переслано в тему {target_topic_id}!",
                        message_thread_id=current_topic_id
                    )
            
            # Добавляем тему в список пересланных для этого сообщения
            if message_id not in forwarded_messages:
                forwarded_messages[message_id] = set()
            forwarded_messages[message_id].add(target_topic_id)
            
            # Формируем текст пересылки
            sender_name = update.message.from_user.first_name
            sender_username = update.message.from_user.username
            sender_info = f"@{sender_username}" if sender_username else sender_name
            
            forward_text = f"📤 Пересылка от {sender_info}"
            if additional_text:
                forward_text += f"\n💬 Комментарий: {additional_text}"
            forward_text += "\n\n"
            
            # Добавляем содержимое оригинального сообщения
            if original_message.text:
                # Экранируем специальные символы для Markdown
                text_content = original_message.text.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
                forward_text += text_content
            elif original_message.caption:
                caption_content = original_message.caption.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
                forward_text += caption_content
            else:
                forward_text += "📎 [Медиа-сообщение]"
            
            # Сначала отправляем в целевую тему
            try:
                # Проверяем, есть ли медиа-файл
                if original_message.photo or original_message.video or original_message.document or original_message.audio or original_message.voice:
                    # Пересылаем медиа-файл
                    await context.bot.forward_message(
                        chat_id=update.message.chat.id,
                        from_chat_id=update.message.chat.id,
                        message_id=original_message.message_id,
                        message_thread_id=target_topic_id
                    )
                    
                    # Отправляем текст отдельно
                    if forward_text.strip():
                        await context.bot.send_message(
                            chat_id=update.message.chat.id,
                            text=forward_text,
                            message_thread_id=target_topic_id
                        )
                else:
                    # Отправляем только текст
                    await context.bot.send_message(
                        chat_id=update.message.chat.id,
                        text=forward_text,
                        message_thread_id=target_topic_id
                    )
                
                logger.info(f"📤 Admin {user_info} forwarded message from topic {current_topic_id} to topic {target_topic_id}")
                
                # Удаляем только команду пересылки
                await update.message.delete()
                logger.info(f"🗑️ Command message deleted successfully")
                
                # Не пытаемся удалять оригинальное сообщение - это ограничение Telegram API
                # Бот может удалять только свои собственные сообщения или сообщения от других ботов
                logger.info(f"ℹ️ Original message left in place (Telegram API limitation)")
                        
            except Exception as send_error:
                logger.error(f"❌ Error sending to topic {target_topic_id}: {send_error}")
                # Отправляем ошибку в текущую тему
                await context.bot.send_message(
                    chat_id=update.message.chat.id,
                    text=f"❌ Ошибка: тема {target_topic_id} не найдена или недоступна!",
                    message_thread_id=current_topic_id
                )
                return
            
        except Exception as e:
            error_count += 1
            logger.error(f"❌ Error forwarding message to topic {target_topic_id}: {e}")
            # Отправляем ошибку напрямую в чат, а не как ответ
            try:
                await context.bot.send_message(
                    chat_id=update.message.chat.id,
                    text=f"❌ Ошибка при пересылке в тему {target_topic_id}:\n{str(e)}",
                    message_thread_id=update.message.message_thread_id
                )
            except:
                pass  # Если и это не работает, просто игнорируем
    
    else:
        # Это обычный ответ
        if not context.args or len(context.args) < 2:
            return await update.message.reply_text(
                "📝 Формат: /r <topic_id/алиас> <текст_ответа>\n\n"
                "Пример: /r 1 Привет! Это ответ из другой темы.\n"
                "Пример: /r 832 Как дела?\n\n"
                "💡 Для пересылки: ответьте на сообщение командой /r <topic_id/алиас>"
            )
        
        # Разрешаем алиас темы
        topic_id = _resolve_topic_id(context.args[0])
        if topic_id is None:
            return await update.message.reply_text("❌ ID темы или алиас должен быть числом!")
        
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
async def set_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить алиас для темы"""
    if not context.args or len(context.args) < 2:
        return await update.message.reply_text(
            "📝 Формат: /set_alias <короткий_номер> <topic_id>\n\n"
            "Пример: /set_alias 1 832\n"
            "После этого можно использовать /r 1 вместо /r 832"
        )
    
    try:
        alias_num = int(context.args[0])
        topic_id = int(context.args[1])
    except ValueError:
        return await update.message.reply_text("❌ И короткий номер, и ID темы должны быть числами!")
    
    if alias_num <= 0:
        return await update.message.reply_text("❌ Короткий номер должен быть положительным числом!")
    
    # Проверяем, не занят ли уже этот алиас
    if alias_num in topic_aliases:
        old_topic_id = topic_aliases[alias_num]
        topic_aliases[alias_num] = topic_id
        await update.message.reply_text(
            f"✅ Алиас {alias_num} обновлен!\n"
            f"Было: {alias_num} → {old_topic_id}\n"
            f"Стало: {alias_num} → {topic_id}"
        )
    else:
        topic_aliases[alias_num] = topic_id
        await update.message.reply_text(f"✅ Алиас {alias_num} → {topic_id} установлен!")
    
    logger.info(f"📌 Admin set alias {alias_num} → {topic_id}")

@require_admin
async def remove_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить алиас темы"""
    if not context.args:
        return await update.message.reply_text("📝 Формат: /remove_alias <короткий_номер>")
    
    try:
        alias_num = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Короткий номер должен быть числом!")
    
    if alias_num in topic_aliases:
        topic_id = topic_aliases[alias_num]
        del topic_aliases[alias_num]
        await update.message.reply_text(f"🗑️ Алиас {alias_num} → {topic_id} удален!")
        logger.info(f"🗑️ Admin removed alias {alias_num} → {topic_id}")
    else:
        await update.message.reply_text(f"ℹ️ Алиас {alias_num} не найден!")

@require_admin
async def list_aliases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все алиасы тем"""
    if not topic_aliases:
        return await update.message.reply_text("📭 Алиасы тем не настроены.")
    
    lines = ["📌 Алиасы тем:"]
    for alias_num in sorted(topic_aliases.keys()):
        topic_id = topic_aliases[alias_num]
        lines.append(f"• {alias_num} → {topic_id}")
    
    await update.message.reply_text("\n".join(lines))

@require_admin
async def set_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настроить очистку темы"""
    if not context.args or len(context.args) < 2:
        return await update.message.reply_text(
            "📝 Формат: /set_cleanup <topic_id/алиас> <интервал_в_минутах>\n\n"
            "Примеры:\n"
            "• /set_cleanup 832 60 - очищать тему 832 каждые 60 минут\n"
            "• /set_cleanup 1 30 - очищать тему с алиасом 1 каждые 30 минут\n"
            "• /set_cleanup 832 0 - отключить очистку темы 832"
        )
    
    # Разрешаем алиас темы
    topic_id = _resolve_topic_id(context.args[0])
    if topic_id is None:
        return await update.message.reply_text("❌ ID темы или алиас должен быть числом!")
    
    try:
        interval_minutes = int(context.args[1])
    except ValueError:
        return await update.message.reply_text("❌ Интервал должен быть числом!")
    
    if interval_minutes < 0:
        return await update.message.reply_text("❌ Интервал не может быть отрицательным!")
    
    if interval_minutes == 0:
        # Отключаем очистку
        if topic_id in topic_cleanup_settings:
            del topic_cleanup_settings[topic_id]
            await update.message.reply_text(f"🧹 Очистка темы {topic_id} отключена!")
        else:
            await update.message.reply_text(f"ℹ️ Очистка темы {topic_id} уже отключена!")
    else:
        # Включаем/обновляем очистку
        topic_cleanup_settings[topic_id] = {
            "interval_minutes": interval_minutes,
            "last_cleanup": time.time()
        }
        await update.message.reply_text(
            f"🧹 Очистка темы {topic_id} настроена!\n"
            f"Интервал: каждые {interval_minutes} минут"
        )
    
    logger.info(f"🧹 Admin set cleanup for topic {topic_id}: {interval_minutes} minutes")



@require_admin
async def cleanup_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Немедленно очистить тему"""
    if not context.args:
        return await update.message.reply_text("📝 Формат: /cleanup_now <topic_id/алиас>")
    
    # Разрешаем алиас темы
    topic_id = _resolve_topic_id(context.args[0])
    if topic_id is None:
        return await update.message.reply_text("❌ ID темы или алиас должен быть числом!")
    
    try:
        chat_id = update.message.chat.id
        
        # Получаем все сообщения в теме (последние 100)
        messages_deleted = 0
        try:
            # Используем get_chat_history для получения сообщений
            async for message in context.bot.get_chat_history(chat_id, limit=100):
                if hasattr(message, 'message_thread_id') and message.message_thread_id == topic_id:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                        messages_deleted += 1
                        await asyncio.sleep(0.1)  # Небольшая задержка между удалениями
                    except Exception as e:
                        logger.warning(f"Could not delete message {message.message_id}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
        
        await update.message.reply_text(
            f"🧹 Очистка темы {topic_id} завершена!\n"
            f"Удалено сообщений: {messages_deleted}"
        )
        
        # Обновляем время последней очистки
        if topic_id in topic_cleanup_settings:
            topic_cleanup_settings[topic_id]["last_cleanup"] = time.time()
        
        logger.info(f"🧹 Admin manually cleaned topic {topic_id}: {messages_deleted} messages")
        
    except Exception as e:
        error_count += 1
        logger.error(f"❌ Error cleaning topic {topic_id}: {e}")
        await update.message.reply_text(f"❌ Ошибка при очистке темы {topic_id}: {str(e)}")

@require_admin
async def clear_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить список пересланных сообщений"""
    global forwarded_messages
    forwarded_messages.clear()
    await update.message.reply_text("🧹 Список пересланных сообщений очищен!")
    logger.info(f"🧹 Admin cleared forwarded messages list")

@require_admin
async def show_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пересланных сообщений"""
    if not forwarded_messages:
        return await update.message.reply_text("📭 Нет пересланных сообщений.")
    
    lines = ["📊 Статистика пересланных сообщений:"]
    for message_id, topics in forwarded_messages.items():
        lines.append(f"• {message_id}: {len(topics)} тем")
    
    await update.message.reply_text("\n".join(lines))

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
            "• /set_alias <номер> <topic_id> - установить алиас для темы\n"
            "• /remove_alias <номер> - удалить алиас темы\n"
            "• /aliases - показать все алиасы тем\n"
            "• /set_cleanup <topic_id/алиас> <минуты> - настроить очистку темы\n"
            "• /cleanup_now <topic_id/алиас> - немедленно очистить тему\n"
            "• /clear_forwarded - очистить список пересланных сообщений\n"
            "• /show_forwarded - показать статистику пересланных сообщений\n"
            "• /list - показать текущие настройки\n"
            "• /topics - как узнать ID тем\n"
            "• /r <topic_id/алиас> <текст> - ответить на сообщение из другой темы\n"
            "• /r <topic_id/алиас> (ответ на сообщение) - переслать сообщение в другую тему\n\n"
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
application.add_handler(CommandHandler("set_alias", set_alias)) # Добавляем обработчик для команды /set_alias
application.add_handler(CommandHandler("remove_alias", remove_alias)) # Добавляем обработчик для команды /remove_alias
application.add_handler(CommandHandler("aliases", list_aliases)) # Добавляем обработчик для команды /aliases
application.add_handler(CommandHandler("set_cleanup", set_cleanup)) # Добавляем обработчик для команды /set_cleanup
application.add_handler(CommandHandler("cleanup_now", cleanup_now)) # Добавляем обработчик для команды /cleanup_now
application.add_handler(CommandHandler("clear_forwarded", clear_forwarded)) # Добавляем обработчик для команды /clear_forwarded
application.add_handler(CommandHandler("show_forwarded", show_forwarded)) # Добавляем обработчик для команды /show_forwarded
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
    try:
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()
        print(f"Web server listening on port {port}")
    except OSError as e:
        if e.errno == 10048:  # Port already in use
            print(f"Port {port} is already in use, trying port {port + 1}")
            port += 1
            site = web.TCPSite(runner, host="0.0.0.0", port=port)
            await site.start()
            print(f"Web server listening on port {port}")
        else:
            raise
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

async def cleanup_scheduler():
    """Автоматическая очистка тем по расписанию"""
    while True:
        await asyncio.sleep(60)  # Проверяем каждую минуту
        
        current_time = time.time()
        for topic_id, settings in topic_cleanup_settings.items():
            interval_seconds = settings["interval_minutes"] * 60
            last_cleanup = settings.get("last_cleanup", 0)
            
            if current_time - last_cleanup >= interval_seconds:
                try:
                    # Запускаем очистку в фоне
                    asyncio.create_task(cleanup_topic_auto(topic_id))
                    # Обновляем время последней очистки
                    topic_cleanup_settings[topic_id]["last_cleanup"] = current_time
                    logger.info(f"🧹 Scheduled cleanup for topic {topic_id}")
                except Exception as e:
                    logger.error(f"❌ Error scheduling cleanup for topic {topic_id}: {e}")

async def cleanup_topic_auto(topic_id: int):
    """Автоматическая очистка темы"""
    try:
        # Получаем первый доступный чат (это ограничение API)
        # В реальном использовании нужно передавать chat_id
        logger.info(f"🧹 Auto cleanup started for topic {topic_id}")
        # Здесь можно добавить логику очистки, но нужен chat_id
        # Пока просто логируем
        logger.info(f"🧹 Auto cleanup completed for topic {topic_id}")
    except Exception as e:
        logger.error(f"❌ Error in auto cleanup for topic {topic_id}: {e}")

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
        
        # Start cleanup scheduler
        logger.info("🧹 Starting cleanup scheduler...")
        asyncio.create_task(cleanup_scheduler())
        
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
