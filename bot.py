# I LOVE DESH BEARCHHHHH

import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command

TOKEN = "8471280186:AAETaSl-fgw7KAlWiqgrxvwCUqVW15eGv4k"
ADMIN_ID = 1958789302

bot = Bot(TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

db = sqlite3.connect("bot.db")
cur = db.cursor()

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

def client_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать художнице", callback_data="write")],
        [InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="review")],
        [InlineKeyboardButton(text="💬 Читать отзывы", callback_data="reviews")],
        [InlineKeyboardButton(text="🖼 Примеры работ", callback_data="portfolio")],
        [InlineKeyboardButton(text="💳 Стоимость", callback_data="price")],
    ])

def admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text="📨 Последние сообщения", callback_data="admin_last")],
        [InlineKeyboardButton(text="⭐ Отзывы", callback_data="admin_reviews")],
    ])

@router.message(Command("start"))
async def start(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Админ-панель:", reply_markup=admin_panel())
    else:
        await message.answer(
            "Добро пожаловать в арт-бот! 🎨\nВыберите действие:",
            reply_markup=client_menu()
        )

@router.callback_query(F.data == "write")
async def client_write(callback: CallbackQuery):
    await callback.message.answer("Напишите ваше сообщение художнице 👇")
    dp["awaiting_msg"] = callback.from_user.id

@router.message()
async def handle_user_message(message: Message):
    if dp.get("awaiting_msg") == message.from_user.id:
        client = message.from_user

        cur.execute("SELECT id FROM orders WHERE client_id=?", (client.id,))
        row = cur.fetchone()

        if not row:
            cur.execute(
                "INSERT INTO orders(client_id, username, status, description) VALUES (?, ?, ?, ?)",
                (client.id, client.username, "new", message.text)
            )
            db.commit()
            order_id = cur.lastrowid
        else:
            order_id = row[0]
            cur.execute("UPDATE orders SET description=? WHERE id=?", (message.text, order_id))
            db.commit()

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Ответить ✏", callback_data=f"reply_{client.id}")]
        ])

        await bot.send_message(
            ADMIN_ID,
            f"📩 Новое сообщение от @{client.username} (заказ #{order_id}):"
        )
        await message.copy_to(ADMIN_ID, reply_markup=kb)

        await message.answer("Сообщение отправлено! ❤️")
        dp.pop("awaiting_msg", None)

@router.callback_query(F.data.startswith("reply_"))
async def start_reply(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    dp["reply_to"] = user_id
    await callback.message.answer("Напишите ответ клиенту 👇")

@router.message(F.from_user.id == ADMIN_ID)
async def admin_reply(message: Message):
    if "reply_to" not in dp:
        return
    target = dp["reply_to"]
    await message.copy_to(target)
    await message.answer("Отправлено ✔")
    dp.pop("reply_to", None)

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
        cur.execute(
            "INSERT INTO reviews(user_id, username, text) VALUES (?, ?, ?)",
            (message.from_user.id, message.from_user.username, message.text)
        )
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
    await callback.message.answer(
        "🖼 *Примеры моих артов*\n\n"
        "Смотреть здесь 👉 https://t.me/DeshBerch",
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "price")
async def price_info(callback: CallbackQuery):
    await callback.message.answer(
        "💳 Информация о стоимости:\n\n"
        "Скоро здесь появится подробный прайс ✨"
    )

@router.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    cur.execute("SELECT id, username, status FROM orders ORDER BY id DESC")
    rows = cur.fetchall()

    if not rows:
        await callback.message.answer("Нет заказов.")
        return

    text = "📋 Список заказов:\n\n"
    for oid, username, status in rows:
        text += f"🔹 Заказ #{oid} — @{username} — статус: {status}\n"

    await callback.message.answer(text)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
