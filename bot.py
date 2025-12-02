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

admin_reply_to = {}

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
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📩 Написать художнице", callback_data="write")],
            [InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="review")],
            [InlineKeyboardButton(text="💬 Читать отзывы", callback_data="reviews")],
            [InlineKeyboardButton(text="🖼 Примеры работ", url="https://t.me/DeshBerch")],
            [InlineKeyboardButton(text="💳 Стоимость", callback_data="price")],
        ]
    )

def admin_panel():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Мои заказы", callback_data="admin_orders")],
            [InlineKeyboardButton(text="📨 Последние сообщения", callback_data="admin_last")],
            [InlineKeyboardButton(text="⭐ Отзывы", callback_data="admin_reviews")],
        ]
    )

def order_status_buttons(order_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
        ]
    )

@router.message(Command("start"))
async def start(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Админ-панель:", reply_markup=admin_panel())
    else:
        await message.answer("Добро пожаловать в арт-бот! 🎨", reply_markup=client_menu())

@router.callback_query(F.data == "write")
async def client_write(callback: CallbackQuery):
    dp["awaiting_msg"] = callback.from_user.id
    await callback.message.answer("Напишите ваше сообщение художнице 👇")

@router.message(F.from_user.id != ADMIN_ID)
async def handle_user_message(message: Message):
    if dp.get("awaiting_msg") != message.from_user.id:
        return

    client = message.from_user
    text_for_order = message.text or "Медиа сообщение"

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

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ответить ✏", callback_data=f"reply_{client.id}")]
        ]
    )

    await bot.send_message(
        ADMIN_ID,
        f"📩 Сообщение от @{client.username} (заказ #{order_id}):\n{text_for_order}",
        reply_markup=kb
    )

    await message.answer("Сообщение отправлено! ❤️")
    dp.pop("awaiting_msg", None)

@router.callback_query(F.data.startswith("reply_"))
async def start_reply(callback: CallbackQuery):
    client_id = int(callback.data.split("_")[1])
    admin_reply_to[callback.from_user.id] = client_id
    await callback.message.answer("Напишите ответ клиенту 👇")

@router.message(F.from_user.id == ADMIN_ID)
async def admin_reply(message: Message):

    if message.from_user.id not in admin_reply_to:
        await message.answer("Выберите сначала, кому отвечать.")
        return

    client_id = admin_reply_to[message.from_user.id]

    if message.text:
        await bot.send_message(client_id, message.text)
    elif message.photo:
        await bot.send_photo(client_id, message.photo[-1].file_id, caption=message.caption or "")
    elif message.document:
        await bot.send_document(client_id, message.document.file_id, caption=message.caption or "")
    elif message.video:
        await bot.send_video(client_id, message.video.file_id, caption=message.caption or "")

    await message.answer("Ответ отправлен ✔")
    del admin_reply_to[message.from_user.id]

@router.callback_query(F.data == "review")
async def review_start(callback: CallbackQuery):
    if callback.from_user.id == ADMIN_ID:
        await callback.message.answer("Админ не может оставлять отзывы.")
        return

    dp["await_review"] = callback.from_user.id
    await callback.message.answer("Напишите ваш отзыв 👇")

@router.message(F.from_user.id != ADMIN_ID)
async def save_review(message: Message):
    if dp.get("await_review") != message.from_user.id:
        return

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

@router.callback_query(F.data == "price")
async def price_info(callback: CallbackQuery):
    await callback.message.answer("💳 Информация о стоимости появится скоро ✨")

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

@router.callback_query(F.data.startswith("status_"))
async def change_status(callback: CallbackQuery):
    _, order_id, status = callback.data.split("_")
    cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    db.commit()

    await callback.message.answer(f"Статус заказа #{order_id} обновлён: {status}")

async def main():
    print("Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
