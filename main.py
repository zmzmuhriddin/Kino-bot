import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from telegram.ext.webhook import WebhookServer

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = set(os.getenv("ADMINS", "").split(","))
CHANNELS = os.getenv("CHANNELS", "").split(",")
DB_FILE = os.getenv("DB_FILE", "cinemaxuz.db")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS movies (
    code TEXT PRIMARY KEY,
    file_id TEXT,
    title TEXT,
    category TEXT,
    views INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    last_seen TIMESTAMP
)
""")
conn.commit()

# === Funksiyalar ===
def add_user(user_id, username):
    with conn:
        conn.execute(
            "REPLACE INTO users VALUES (?, ?, ?)",
            (user_id, username or "", datetime.now(timezone.utc))
        )

def is_admin(user_id):
    return str(user_id) in ADMINS

async def is_subscribed(user_id, context):
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel.strip(), user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except:
            return False
    return True

def add_movie(code, file_id, title, category="Yangi"):
    with conn:
        conn.execute(
            "REPLACE INTO movies VALUES (?, ?, ?, ?, 0)",
            (code, file_id, title, category)
        )

def delete_movie(code):
    with conn:
        conn.execute("DELETE FROM movies WHERE code=?", (code,))

def add_category(name):
    with conn:
        conn.execute("INSERT OR IGNORE INTO categories VALUES (?)", (name,))

def delete_category(name):
    with conn:
        conn.execute("DELETE FROM categories WHERE name=?", (name,))

def get_movie(code):
    cursor.execute("SELECT * FROM movies WHERE code=?", (code,))
    return cursor.fetchone()

def get_all_movies():
    cursor.execute("SELECT * FROM movies ORDER BY title")
    return cursor.fetchall()

def get_movies_by_category(category):
    cursor.execute("SELECT * FROM movies WHERE category=?", (category,))
    return cursor.fetchall()

def search_movies(query):
    cursor.execute("SELECT * FROM movies WHERE title LIKE ?", (f"%{query}%",))
    return cursor.fetchall()

def get_all_categories():
    cursor.execute("SELECT name FROM categories ORDER BY name")
    return [row[0] for row in cursor.fetchall()]

def get_user_count():
    cursor.execute("SELECT COUNT(*) FROM users")
    return cursor.fetchone()[0]

def get_movie_count():
    cursor.execute("SELECT COUNT(*) FROM movies")
    return cursor.fetchone()[0]

def get_top_movies(limit=10):
    cursor.execute("SELECT * FROM movies ORDER BY views DESC LIMIT ?", (limit,))
    return cursor.fetchall()

def update_movie_views(code):
    with conn:
        conn.execute(
            "UPDATE movies SET views = views + 1 WHERE code=?", (code,)
        )

# === Holatlar ===
adding_movie = {}
deleting_movie = {}
broadcasting = {}
adding_category = {}
deleting_category = {}

# === Komandalar ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(str(user.id), user.username)
    if not await is_subscribed(user.id, context):
        await update.message.reply_text("🚫 Kanalga obuna bo‘ling!")
        return

    buttons = [
        [InlineKeyboardButton("🎬 Kinolar", callback_data="movies")],
        [InlineKeyboardButton("🗂 Kategoriyalar", callback_data="categories")],
        [InlineKeyboardButton("🔎 Qidiruv", callback_data="search")],
        [InlineKeyboardButton("ℹ️ Ma'lumot", callback_data="info")]
    ]
    markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "🎬 CinemaxUZ botiga xush kelibsiz!", reply_markup=markup
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Siz admin emassiz.")
        return
    keyboard = [
        ["📊 Statistika", "➕ Kino qo‘shish"],
        ["❌ Kino o‘chirish", "🗂 Kategoriya qo‘shish"],
        ["🗑 Kategoriya o‘chirish", "📥 Top kinolar"],
        ["📤 Xabar yuborish"]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("👑 Admin panel:", reply_markup=markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if not await is_subscribed(user_id, context):
        await query.message.reply_text("🚫 Obuna bo‘ling!")
        return

    if data == "movies":
        movies = get_all_movies()
        if movies:
            buttons = [[InlineKeyboardButton(m[2], callback_data=f"movie_{m[0]}")] for m in movies]
            await query.message.reply_text("🎬 Kinolar:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.message.reply_text("📭 Kinolar yo‘q.")
    elif data == "categories":
        categories = get_all_categories()
        if categories:
            buttons = [[InlineKeyboardButton(c, callback_data=f"category_{c}")] for c in categories]
            await query.message.reply_text("🗂 Kategoriyalar:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.message.reply_text("📭 Kategoriya yo‘q.")
    elif data.startswith("category_"):
        category = data.split("_", 1)[1]
        movies = get_movies_by_category(category)
        if movies:
            buttons = [[InlineKeyboardButton(m[2], callback_data=f"movie_{m[0]}")] for m in movies]
            await query.message.reply_text(f"🎬 {category} kategoriyasidagi kinolar:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.message.reply_text("📭 Kino yo‘q.")
    elif data.startswith("movie_"):
        code = data.split("_", 1)[1]
        movie = get_movie(code)
        if movie:
            update_movie_views(code)
            await query.message.reply_video(movie[1], caption=movie[2])
        else:
            await query.message.reply_text("❌ Kino topilmadi.")
    elif data == "search":
        await query.message.reply_text("🔎 Kino nomi yoki kodini yuboring.")
    elif data == "info":
        await query.message.reply_text("ℹ️ @CinemaxUz bot. Kinolarni ko‘rish uchun foydalaning.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()

    if not await is_subscribed(update.effective_user.id, context):
        await update.message.reply_text("🚫 Obuna bo‘ling!")
        return

    if is_admin(user_id):
        if adding_movie.get(user_id):
            parts = text.split(";")
            if len(parts) >= 4:
                code, file_id, title, category = map(str.strip, parts)
                add_movie(code, file_id, title, category)
                adding_movie[user_id] = False
                await update.message.reply_text(f"✅ Qo‘shildi: {title}")
            else:
                await update.message.reply_text("⚠️ Format: kod;file_id;title;category")
            return

        if deleting_movie.get(user_id):
            delete_movie(text)
            deleting_movie[user_id] = False
            await update.message.reply_text(f"❌ O‘chirildi: {text}")
            return

        if adding_category.get(user_id):
            add_category(text)
            adding_category[user_id] = False
            await update.message.reply_text(f"✅ Kategoriya qo‘shildi: {text}")
            return

        if deleting_category.get(user_id):
            delete_category(text)
            deleting_category[user_id] = False
            await update.message.reply_text(f"❌ Kategoriya o‘chirildi: {text}")
            return

        if broadcasting.get(user_id):
            broadcasting[user_id] = False
            cursor.execute("SELECT user_id FROM users")
            for (uid,) in cursor.fetchall():
                try:
                    await context.bot.send_message(int(uid), text)
                except:
                    continue
            await update.message.reply_text("✅ Xabar yuborildi!")
            return

        if text == "➕ Kino qo‘shish":
            adding_movie[user_id] = True
            await update.message.reply_text("📝 Format: kod;file_id;title;category")
        elif text == "❌ Kino o‘chirish":
            deleting_movie[user_id] = True
            await update.message.reply_text("🗑 Kino kodini yuboring.")
        elif text == "🗂 Kategoriya qo‘shish":
            adding_category[user_id] = True
            await update.message.reply_text("➕ Kategoriya nomini yuboring.")
        elif text == "🗑 Kategoriya o‘chirish":
            deleting_category[user_id] = True
            await update.message.reply_text("❌ Kategoriya nomini yuboring.")
        elif text == "📥 Top kinolar":
            movies = get_top_movies()
            msg = "🏆 Top kinolar:\n\n"
            for m in movies:
                msg += f"🎬 {m[2]} — {m[4]} ko‘rish\n"
            await update.message.reply_text(msg)
        elif text == "📊 Statistika":
            await update.message.reply_text(
                f"👥 Foydalanuvchilar: {get_user_count()}\n"
                f"🎥 Kinolar: {get_movie_count()}\n"
                f"🗂 Kategoriya: {len(get_all_categories())}"
            )
        elif text == "📤 Xabar yuborish":
            broadcasting[user_id] = True
            await update.message.reply_text("✉️ Xabar matnini yuboring.")
        return

    # Foydalanuvchi uchun qidiruv
    movie = get_movie(text)
    if movie:
        update_movie_views(text)
        await update.message.reply_video(movie[1], caption=movie[2])
        return

    results = search_movies(text)
    if results:
        for m in results:
            await update.message.reply_video(m[1], caption=m[2])
    else:
        await update.message.reply_text("❌ Kino topilmadi.")

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.video:
        await update.message.reply_text(f"🎬 file_id: <code>{update.message.video.file_id}</code>", parse_mode="HTML")

# === Bot va webhook ===
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.VIDEO, get_file_id))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

fastapi_app = FastAPI()

@fastapi_app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.update_queue.put(update)
    return {"ok": True}

@app.on_startup
async def startup():
    await app.bot.set_webhook(url=WEBHOOK_URL)

@app.on_shutdown
async def shutdown():
    await app.bot.delete_webhook()

if __name__ == "__main__":
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
        fastapi=fastapi_app
        )
