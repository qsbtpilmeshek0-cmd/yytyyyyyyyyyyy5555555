import os
import logging
import sqlite3
import asyncio
from contextlib import contextmanager
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.utils.exceptions import TelegramForbiddenError, BadRequest, RetryAfter, ChatNotFound

# ----------------------------
# Настройка логирования
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------------
# Конфигурация
# ----------------------------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.critical("BOT_TOKEN not set in environment. Exiting.")
    raise SystemExit("Set BOT_TOKEN env var")

# Укажи ID администратора(ов)
# Можно хранить строкой через запятую в env, например "12345,23456"
ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # optional
if ADMIN_IDS:
    ADMIN_IDS = {int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip().isdigit()}
else:
    # fallback — можно оставить пустым, но для разработки ставь свой ID
    ADMIN_IDS = set()

# ----------------------------
# Бот и диспетчер
# ----------------------------
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ----------------------------
# SQLite helper (thread-safe usage)
# ----------------------------
DB_PATH = os.getenv("DB_PATH", "bot.db")

# Always create a fresh connection per use to avoid threading issues.
# check_same_thread=False so connection object can be used across threads if needed.
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def db_conn():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()

# ----------------------------
# Инициализация БД
# ----------------------------
def init_db():
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            text TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            username TEXT,
            status TEXT NOT NULL,
            description TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Таблица для сохранения "состояний ожидания" — чтобы пережить рестарты
        cur.execute("""
        CREATE TABLE IF NOT EXISTS states(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            state TEXT NOT NULL,
            data TEXT, -- JSON-ish string (простые случаи)
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
    logger.info("Database initialized at %s", DB_PATH)

# ----------------------------
# Утилиты для состояний в БД
# ----------------------------
def set_state_db(user_id: int, state: str, data: Optional[str] = None):
    """Сохраняет или обновляет состояние пользователя (одна запись на user_id)."""
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM states WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE states SET state = ?, data = ?, created_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                        (state, data, user_id))
        else:
            cur.execute("INSERT INTO states(user_id, state, data) VALUES (?, ?, ?)", (user_id, state, data))

def get_state_db(user_id: int) -> Optional[Dict[str, Any]]:
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT state, data FROM states WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"state": row["state"], "data": row["data"]}

def clear_state_db(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM states WHERE user_id = ?", (user_id,))

# ----------------------------
# UI / клавиатуры
# ----------------------------
def client_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать художнице", callback_data="write")],
        [InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="review")],
        [InlineKeyboardButton(text="💬 Читать отзывы", callback_data="reviews")],
        [InlineKeyboardButton(text="🖼 Примеры работ", url="https://t.me/DeshBerch")],
        [InlineKeyboardButton(text="💳 Стоимость", callback_data="price")],
    ])

def admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text="📨 Последние сообщения", callback_data="admin_last")],
        [InlineKeyboardButton(text="⭐ Отзывы", callback_data="admin_reviews")],
    ])

def order_status_buttons(order_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🆕 Новый", callback_data=f"status_{order_id}_new"),
            InlineKeyboardButton(text="⏳ В обработке", callback_data=f"status_{order_id}_processing")
        ],
        [
            InlineKeyboardButton(text="🖌 В работе", callback_data=f"status_{order_id}_work"),
            InlineKeyboardButton(text="📦 Готов", callback_data=f"status_{order_id}_done")
        ],
        [
            InlineKeyboardButton(text="💰 Оплачен", callback_data=f"status_{order_id}_paid"),
            InlineKeyboardButton(text="❌ Отменён", callback_data=f"status_{order_id}_cancel")
        ]
    ])

# ----------------------------
# Helpers
# ----------------------------
def safe_username(user) -> str:
    return f"@{user.username}" if getattr(user, "username", None) else f"{user.full_name or user.first_name or 'User'}"

async def safe_send(chat_id: int, send_coro, *args, **kwargs):
    """Обёртка для безопасной отправки, возвращает (ok: bool, error_msg: Optional[str])"""
    try:
        await send_coro(chat_id, *args, **kwargs)
        return True, None
    except TelegramForbiddenError:
        return False, "forbidden"
    except ChatNotFound:
        return False, "chat_not_found"
    except RetryAfter as e:
        logger.warning("RetryAfter: sleeping %s sec", e.timeout)
        await asyncio.sleep(e.timeout)
        # пробуем повторно (один раз)
        try:
            await send_coro(chat_id, *args, **kwargs)
            return True, None
        except Exception as e2:
            logger.exception("Failed after retry: %s", e2)
            return False, str(e2)
    except BadRequest as e:
        logger.exception("BadRequest sending message: %s", e)
        return False, str(e)
    except Exception as e:
        logger.exception("Unexpected error sending message: %s", e)
        return False, str(e)

# ----------------------------
# Command handlers
# ----------------------------
@router.message(Command("start"))
async def start_handler(message: Message):
    uid = message.from_user.id
    if uid in ADMIN_IDS:
        await message.answer("Админ-панель:", reply_markup=admin_panel())
    else:
        await message.answer("Добро пожаловать в арт-бот! 🎨\nВыберите действие:", reply_markup=client_menu())

# ----------------------------
# Клиент: написать художнице
# ----------------------------
@router.callback_query(F.data == "write")
async def client_write_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    # Ставим состояние 'awaiting_write' и сохраняем
    set_state_db(user_id, "awaiting_write", None)
    await callback.message.answer("Напишите ваше сообщение художнице 👇\n(текст или медиа — бот поддерживает фото/video/document)")
    await callback.answer()

@router.message()
async def catch_all_messages(message: Message):
    """
    Универсальный обработчик — сначала выясняет, в каком состоянии пользователь,
    затем ведёт себя соответствующим образом.
    Это позволяет не конфликтовать с множественными @router.message() хендлерами.
    """
    uid = message.from_user.id
    state = get_state_db(uid)
    # Если пользователь в состоянии "awaiting_write"
    if state and state["state"] == "awaiting_write":
        await handle_client_write(message)
        return
    if state and state["state"] == "awaiting_review":
        await handle_client_review(message)
        return
    # Админ — есть ли у админа состояние "admin_reply"?
    if uid in ADMIN_IDS:
        if state and state["state"] == "admin_reply":
            await handle_admin_reply(message)
            return
    # иначе — ничего не ждём; можно подсказать меню
    # Чтобы не навязываться: только если сообщение - команда или текст короткий, покажем меню
    if message.text and message.text.startswith("/"):
        # позволим другие команды обрабатываться отдельно (если добавишь)
        return
    # Небольшая эвристика — если пользователь просто прислал сообщение без состояния, подскажем меню
    await message.answer("Выберите действие в меню:", reply_markup=client_menu())

async def handle_client_write(message: Message):
    client = message.from_user
    uid = client.id
    # собираем текст описания
    if message.text:
        desc = message.text
    else:
        # поддержка типа: фото, видео, документ — мы сохраняем маркер "медиа"
        desc = "Медиа сообщение"
    # сохраняем/обновляем заказ (уникален по client_id — один активный заказ)
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM orders WHERE client_id = ?", (uid,))
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO orders(client_id, username, status, description) VALUES (?, ?, ?, ?)",
                        (uid, client.username or "", "new", desc))
            order_id = cur.lastrowid
        else:
            order_id = row["id"]
            cur.execute("UPDATE orders SET description = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (desc, order_id))
    # Кнопка ответа ведёт админа к установке состояния admin_reply
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ответить ✏", callback_data=f"reply_{uid}")]
    ])
    # Отправляем сообщение админу(ам)
    admin_msg = f"📩 Новое сообщение от {safe_username(client)} (заказ #{order_id}):\n{desc}"
    for admin_id in (ADMIN_IDS or []):
        ok, err = await safe_send(admin_id, bot.send_message, admin_msg, reply_markup=kb)
        if not ok:
            logger.warning("Failed to notify admin %s: %s", admin_id, err)
    # Если нет админов — логируем
    if not ADMIN_IDS:
        logger.warning("No ADMIN_IDS set — message from %s will not be delivered to admins", uid)

    await message.answer("Сообщение отправлено художнице! ❤️")
    clear_state_db(uid)

# ----------------------------
# Клиент: отзыв
# ----------------------------
@router.callback_query(F.data == "review")
async def start_review_cb(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid in ADMIN_IDS:
        await callback.message.answer("Админ не может оставлять отзывы.")
        await callback.answer()
        return
    set_state_db(uid, "awaiting_review", None)
    await callback.message.answer("Напишите ваш отзыв 👇")
    await callback.answer()

async def handle_client_review(message: Message):
    uid = message.from_user.id
    text = message.text or ""
    if not text.strip():
        await message.answer("Пожалуйста, пришлите текстовый отзыв.")
        return
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO reviews(user_id, username, text) VALUES (?, ?, ?)",
                    (uid, message.from_user.username or "", text.strip()))
    await message.answer("Спасибо за отзыв! ❤️")
    clear_state_db(uid)

@router.callback_query(F.data == "reviews")
async def show_reviews_cb(callback: CallbackQuery):
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username, text, created_at FROM reviews ORDER BY id DESC LIMIT 30")
        rows = cur.fetchall()
    if not rows:
        await callback.message.answer("Пока нет отзывов.")
        await callback.answer()
        return
    txt = "⭐ Отзывы (последние 30):\n\n" + "\n\n".join(
        [f"{('@' + r['username']) if r['username'] else '(без username)'}: {r['text']}" for r in rows])
    # если текст длинный, разделяем
    if len(txt) > 4000:
        # отправим частями
        parts = [txt[i:i + 3500] for i in range(0, len(txt), 3500)]
        for p in parts:
            await callback.message.answer(p)
            await asyncio.sleep(0.05)
    else:
        await callback.message.answer(txt)
    await callback.answer()

# ----------------------------
# Админ: нажал "Ответить" — устанавливаем состояние admin_reply
# ----------------------------
@router.callback_query(F.data.startswith("reply_"))
async def begin_reply_cb(callback: CallbackQuery):
    # формируется как "reply_{client_id}"
    parts = callback.data.split("_", 1)
    if len(parts) != 2:
        await callback.answer("Неверные данные", show_alert=True)
        return
    try:
        client_id = int(parts[1])
    except ValueError:
        await callback.answer("Неверный ID клиента", show_alert=True)
        return
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Только админ может отвечать.", show_alert=True)
        return
    set_state_db(admin_id, "admin_reply", str(client_id))
    await callback.message.answer(f"Напишите ответ клиенту (id: {client_id}) 👇")
    await callback.answer()

async def handle_admin_reply(message: Message):
    admin_id = message.from_user.id
    state = get_state_db(admin_id)
    if not state or state["state"] != "admin_reply":
        await message.answer("Сначала выберите, кому отвечать (через кнопку).")
        return
    client_id_str = state.get("data")
    try:
        client_id = int(client_id_str)
    except (TypeError, ValueError):
        await message.answer("Ошибка внутреннего состояния. Повторите действие.")
        clear_state_db(admin_id)
        return

    # Отправка сообщения клиенту (поддержка текста и медиа)
    sent_ok = False
    error_msg = None
    if message.text:
        sent_ok, error_msg = await safe_send(client_id, bot.send_message, message.text)
    elif message.photo:
        file_id = message.photo[-1].file_id
        sent_ok, error_msg = await safe_send(client_id, bot.send_photo, file_id, caption=message.caption or "")
    elif message.document:
        sent_ok, error_msg = await safe_send(client_id, bot.send_document, message.document.file_id,
                                             caption=message.caption or "")
    elif message.video:
        sent_ok, error_msg = await safe_send(client_id, bot.send_video, message.video.file_id,
                                             caption=message.caption or "")
    else:
        await message.answer("Неподдерживаемый тип сообщения. Отправьте текст, фото, видео или документ.")
        return

    if sent_ok:
        await message.answer("Ответ отправлен ✔")
    else:
        # Расширенное сообщение об ошибке
        if error_msg == "forbidden":
            await message.answer("❌ Не удалось отправить сообщение: пользователь заблокировал бота или бот не имеет доступа.")
        elif error_msg == "chat_not_found":
            await message.answer("❌ Не удалось отправить сообщение: чат не найден.")
        else:
            await message.answer(f"❌ Ошибка при отправке: {error_msg}")
        logger.warning("Admin %s: failed to send message to %s: %s", admin_id, client_id, error_msg)

    clear_state_db(admin_id)

# ----------------------------
# Админ: заказы и изменение статусов
# ----------------------------
ALLOWED_STATUSES = {"new", "processing", "work", "done", "paid", "cancel"}

@router.callback_query(F.data == "admin_orders")
async def admin_orders_cb(callback: CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Только админ.", show_alert=True)
        return
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, status, description FROM orders ORDER BY id DESC LIMIT 50")
        rows = cur.fetchall()
    if not rows:
        await callback.message.answer("Нет заказов.")
        await callback.answer()
        return
    for r in rows:
        oid = r["id"]
        username = r["username"] or "(без username)"
        status = r["status"]
        desc = r["description"] or ""
        text = f"🔹 Заказ #{oid} — {username}\nСтатус: {status}\nОписание: {desc}"
        await callback.message.answer(text, reply_markup=order_status_buttons(oid))
        await asyncio.sleep(0.05)  # small throttle to avoid flood
    await callback.answer()

@router.callback_query(F.data.startswith("status_"))
async def change_status_cb(callback: CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Только админ.", show_alert=True)
        return
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("Неверные данные", show_alert=True)
        return
    _, order_id_str, status = parts
    try:
        order_id = int(order_id_str)
    except ValueError:
        await callback.answer("Неверный ID заказа", show_alert=True)
        return
    if status not in ALLOWED_STATUSES:
        await callback.answer("Неверный статус", show_alert=True)
        return
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    await callback.message.answer(f"Статус заказа #{order_id} обновлён на {status}")
    await callback.answer()

# ----------------------------
# Остальные коллбеки: price, portfolio, admin_last/admin_reviews (реализация)
# ----------------------------
@router.callback_query(F.data == "price")
async def price_cb(callback: CallbackQuery):
    await callback.message.answer("💳 Информация о стоимости:\n\nСкоро здесь появится подробный прайс ✨")
    await callback.answer()

@router.callback_query(F.data == "admin_last")
async def admin_last_cb(callback: CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Только админ.", show_alert=True)
        return
    # Покажем последние 20 заказов/сообщений
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, client_id, username, description, created_at FROM orders ORDER BY created_at DESC LIMIT 20")
        rows = cur.fetchall()
    if not rows:
        await callback.message.answer("Нет последних сообщений/заказов.")
        await callback.answer()
        return
    for r in rows:
        await callback.message.answer(
            f"#{r['id']} — {r['username'] or '(без username)'} (id:{r['client_id']})\n{r['description']}\n{r['created_at']}"
        )
        await asyncio.sleep(0.05)
    await callback.answer()

@router.callback_query(F.data == "admin_reviews")
async def admin_reviews_cb(callback: CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Только админ.", show_alert=True)
        return
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, text, created_at FROM reviews ORDER BY created_at DESC LIMIT 50")
        rows = cur.fetchall()
    if not rows:
        await callback.messa
