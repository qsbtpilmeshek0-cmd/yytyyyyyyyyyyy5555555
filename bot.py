# I LOVE DESH BEARCHHHHH

import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

TOKEN = "8471280186:AAETaSl-fgw7KAlWiqgrxvwCUqVW15eGv4k"
ADMIN_ID = 1958789302

bot = Bot(TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

db = sqlite3.connect("bot.db")
cur = db.cursor()

# Словарь для хранения, кому отвечает админ
admin_reply_to = {}  # {admin_id: {"chat_id": client_chat_id, "message_id": client_message_id}}

# Создаем таблицы
cur.execute("""
CREATE TABLE IF NOT EXISTS reviews(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    text TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER,
    username TEXT,
    status TEXT,
    description TEXT
)
""")
db.commit()

# Меню клиента
def client_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать художнице", callback_data="write")],
        [InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="review")],
        [InlineKeyboardButton(text="💬 Читать отзывы", callback_data="reviews")],
        [InlineKeyboardButton(text="🖼 Примеры работ", url="https://t.me/DeshBerch")],
        [InlineKeyboardButton(text="💳 Стоимость", callback_data="price")],
    ])

# Админ-панель
def admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text="📨 Последние сообщения", callback_data="admin_last")],
        [InlineKeyboardButton(text="⭐ Отзывы", callback_data="admin_reviews")],
    ])

# Кнопки изменения статуса заказа
def order_status_buttons(order_id):
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

# /start
@router.message(Command("start"))
async def start(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Админ-панель:", reply_markup=admin_panel())
    else:
        await message.answer("Добро пожаловать в арт-бот! 🎨\nВыберите действие:", reply_markup=client_menu())

# Клиент пишет сообщение
@router.callback_query(F.data == "write")
async def client_write(callback: CallbackQuery):
    await callback.message.answer("Напишите ваше сообщение художнице 👇")
    dp["awaiting_msg"] = callback.from_user.id

@router.message()
async def handle_user_message(message: Message):
    if dp.get("awaiting_msg") == message.from_user.id:
        client = message.from_user
        # Сохраняем текст сообщения или помечаем как "Медиа"
        text_for_order = message.text or "Медиа сообщение"

        # Сохраняем заказ
        cur.execute("SELECT id FROM orders WHERE client_id=?", (client.id,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO orders(client_id, username, status, description) VALUES (?, ?, ?, ?)",
                (client.id, client.username, "new", text_for_order)
            )
            db.commit()
            order_id = cur.lastrowid
        else:
            order_id = row[0]
            cur.execute("UPDATE orders SET description=? WHERE id=?", (text_for_order, order_id))
            db.commit()

        # Отправляем админу сообщение с кнопкой Ответить
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Ответить ✏", callback_data=f"reply_{client.id}_{message.message_id}")]
        ])
        await bot.send_message(ADMIN_ID, f"📩 Новое сообщение от @{client.username} (заказ #{order_id}):\n{text_for_order}", reply_markup=kb)
        await message.answer("Сообщение отправлено! ❤️")
        dp.pop("awaiting_msg", None)

# Админ нажал кнопку Ответить
@router.callback_query(F.data.startswith("reply_"))
async def start_reply(callback: CallbackQuery):
    parts = callback.data.split("_")
    client_id = int(parts[1])
    msg_id = int(parts[2])
    admin_reply_to[callback.from_user.id] = {"chat_id": client_id, "message_id": msg_id}
    await callback.message.answer("Напишите ответ клиенту 👇")

# Универсальный ответ админа
@router.message(F.from_user.id == ADMIN_ID)
async def admin_reply(message: Message):
    if message.from_user.id not in admin_reply_to:
        await message.answer("Выберите сначала, кому отвечать.")
        return

    info = admin_reply_to[message.from_user.id]
    chat_id = info["chat_id"]

    # Пересылаем любое сообщение клиента
    await message.copy_to(chat_id)
    await message.answer("Ответ отправлен ✔")
    del admin_reply_to[message.from_user.id]

# Оставление отзыва
@router.callback_query(F.data == "review")
async def review_start(callback: CallbackQuery):
    if callback.from_user.id == ADMIN_ID:
        await callback.message.answer("Админ не может оставлять отзывы.")
        return
    dp["await_review"] = callback.from_user.id
    await callback.message.answer("Напишите ваш отзыв 👇")

@router.message()
async def save_review(message: Message):
    if dp.get("await_review") == message.from_user.id:
        cur.execute("INSERT INTO reviews(user_id, username, text) VALUES (?, ?, ?)",
                    (message.from_user.id, message.from_user.username, message.text))
        db.commit()
        await message.answer("Спасибо за отзыв! ❤️")
        dp.pop("await_review", None)

@router.callback_query(F.data == "reviews")
async def show_reviews(callback: CallbackQuery):
    cur.execute("SELECT username, text FROM reviews")
    rows = cur.fetchall()
    if not rows:
        await callback.message.answer("Пока нет отзывов.")
        return
    text = "⭐ Отзывы:\n\n" + "\n\n".join([f"@{u}: {t}" for u, t in rows])
    await callback.message.answer(text)

@router.callback_query(F.data == "portfolio")
async def show_portfolio(callback: CallbackQuery):
    await callback.message.answer("🖼 *Примеры моих артов*\n\nСмотреть здесь 👉 https://t.me/DeshBerch", parse_mode="Markdown")

@router.callback_query(F.data == "price")
async def price_info(callback: CallbackQuery):
    await callback.message.answer("💳 Информация о стоимости:\n\nСкоро здесь появится подробный прайс ✨")

# Админ: показать заказы
@router.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    cur.execute("SELECT id, username, status, description FROM orders ORDER BY id DESC")
    rows = cur.fetchall()
    if not rows:
        await callback.message.answer("Нет заказов.")
        return
    for oid, username, status, desc in rows:
        await callback.message.answer(
            f"🔹 Заказ #{oid} — @{username}\nСтатус: {status}\nОписание: {desc}",
            reply_markup=order_status_buttons(oid)
        )

# Изменение статуса заказа
@router.callback_query(F.data.startswith("status_"))
async def change_status(callback: CallbackQuery):
    _, order_id, status = callback.data.split("_")
    cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    db.commit()
    await callback.message.answer(f"Статус заказа #{order_id} обновлён на {status}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
