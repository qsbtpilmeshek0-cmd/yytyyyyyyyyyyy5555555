# I LOVE DESH BEARCHHHHH
import os
import dropbox
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
DROPBOX_TOKEN = os.getenv("DROPBOX_TOKEN")

SPECIAL_CODE = "Q_FBR_PASSPORTS/DATA.GB$04743"
DROPBOX_FOLDER = "/passports"

dbx = dropbox.Dropbox(DROPBOX_TOKEN)

async def upload_to_dropbox(local_path, remote_name):
    with open(local_path, "rb") as f:
        dbx.files_upload(f.read(), f"{DROPBOX_FOLDER}/{remote_name}", mode=dropbox.files.WriteMode.overwrite)

async def list_files():
    res = dbx.files_list_folder(DROPBOX_FOLDER)
    return res.entries

async def download_file(path, local_name):
    _, res = dbx.files_download(path)
    with open(local_name, "wb") as f:
        f.write(res.content)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.text == SPECIAL_CODE:
        files = await list_files()
        if not files:
            await msg.reply_text("Архив пуст.")
            return
        for f in files:
            await download_file(f.path_lower, f"temp_{f.name}")
            with open(f"temp_{f.name}", "rb") as photo_file:
                await msg.reply_photo(photo=photo_file)
            os.remove(f"temp_{f.name}")
        return

    if msg.photo:
        try:
            file = await msg.photo[-1].get_file()
            file_path = f"temp_{msg.from_user.id}.jpg"
            await file.download_to_drive(file_path)
            remote_name = os.path.basename(file_path)
            await upload_to_dropbox(file_path, remote_name)
            os.remove(file_path)
            await msg.reply_text("Архивация паспортных данных прошла успешно!✅")
        except Exception as e:
            await msg.reply_text(f"Что-то пошло не так на этапе архивации. Обратитесь к администратору архива @Qshka16\nОшибка: {e}")
        return

    await msg.reply_text("Не удалось распознать. Отправьте фото паспорта или спецкод.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот активен. Отправьте фото паспорта или спецкод.")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT, handle_message))

if name == "main":
    print("Бот запущен...")
    app.run_polling()
