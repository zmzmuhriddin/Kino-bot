import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import sqlalchemy
from sqlalchemy import Table, Column, String, Integer, DateTime, MetaData
import databases

# === Load env ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))
ADMINS = set(os.getenv("ADMINS", "").split(","))
CHANNELS = os.getenv("CHANNELS", "").split(",")
DATABASE_URL = os.getenv("DATABASE_URL")

# === DB Connection ===
database = databases.Database(DATABASE_URL)
metadata = MetaData()

movies = Table(
    "movies", metadata,
    Column("code", String, primary_key=True),
    Column("file_id", String),
    Column("title", String),
    Column("category", String, default="Yangi"),
    Column("views", Integer, default=0)
)

categories = Table(
    "categories", metadata,
    Column("name", String, primary_key=True)
)

users = Table(
    "users", metadata,
    Column("user_id", String, primary_key=True),
    Column("username", String),
    Column("last_seen", DateTime)
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

# === Telegram Application ===
app = ApplicationBuilder().token(BOT_TOKEN).build()

# === FastAPI App ===
fastapi_app = FastAPI()

# =================== FUNCTIONAL ===================

async def add_user(user_id, username):
    query = users.insert().values(
        user_id=user_id,
        username=username or "",
        last_seen=datetime.now(timezone.utc)
    ).on_conflict_do_update(
        index_elements=['user_id'],
        set_={"username": username or "", "last_seen": datetime.now(timezone.utc)}
    )
    await database.execute(query)

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

async def add_movie(code, file_id, title, category="Yangi"):
    query = movies.insert().values(
        code=code, file_id=file_id, title=title, category=category, views=0
    ).on_conflict_do_update(
        index_elements=['code'],
        set_={"file_id": file_id, "title": title, "category": category}
    )
    await database.execute(query)

async def delete_movie(code):
    query = movies.delete().where(movies.c.code == code)
    await database.execute(query)

async def add_category(name):
    query = categories.insert().values(name=name).on_conflict_do_nothing()
    await database.execute(query)

async def delete_category(name):
    query = categories.delete().where(categories.c.name == name)
    await database.execute(query)

async def get_movie(code):
    query = movies.select().where(movies.c.code == code)
    return await database.fetch_one(query)

async def get_all_movies():
    query = movies.select().order_by(movies.c.title)
    return await database.fetch_all(query)

async def get_movies_by_category(category):
    query = movies.select().where(movies.c.category == category)
    return await database.fetch_all(query)

async def search_movies(query_text):
    query = movies.select().where(movies.c.title.ilike(f"%{query_text}%"))
    return await database.fetch_all(query)

async def get_all_categories():
    query = categories.select().order_by(categories.c.name)
    rows = await database.fetch_all(query)
    return [row["name"] for row in rows]

async def get_user_count():
    query = sqlalchemy.select(sqlalchemy.func.count()).select_from(users)
    return await database.fetch_val(query)

async def get_movie_count():
    query = sqlalchemy.select(sqlalchemy.func.count()).select_from(movies)
    return await database.fetch_val(query)

async def get_top_movies(limit=10):
    query = movies.select().order_by(movies.c.views.desc()).limit(limit)
    return await database.fetch_all(query)

async def update_movie_views(code):
    query = movies.update().where(movies.c.code == code).values(
        views=movies.c.views + 1
    )
    await database.execute(query)

# =================== STATES ===================
adding_movie = {}
deleting_movie = {}
broadcasting = {}
adding_category = {}
deleting_category = {}

# =================== COMMANDS ===================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await add_user(str(user.id), user.username)
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

# =================== BUTTON HANDLER ===================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if not await is_subscribed(user_id, context):
        await query.message.reply_text("🚫 Obuna bo‘ling!")
        return

    if data == "movies":
        movies_list = await get_all_movies()
        if movies_list:
            buttons = [[InlineKeyboardButton(m["title"], callback_data=f"movie_{m['code']}")] for m in movies_list]
            await query.message.reply_text("🎬 Kinolar:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.message.reply_text("📭 Kinolar yo‘q.")
    elif data == "categories":
        categories_list = await get_all_categories()
        if categories_list:
            buttons = [[InlineKeyboardButton(c, callback_data=f"category_{c}")] for c in categories_list]
            await query.message.reply_text("🗂 Kategoriyalar:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.message.reply_text("📭 Kategoriya yo‘q.")
    elif data.startswith("category_"):
        category = data.split("_", 1)[1]
        movies_list = await get_movies_by_category(category)
        if movies_list:
            buttons = [[InlineKeyboardButton(m["title"], callback_data=f"movie_{m['code']}")] for m in movies_list]
            await query.message.reply_text(f"🎬 {category} kategoriyasidagi kinolar:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.message.reply_text("📭 Kino yo‘q.")
    elif data.startswith("movie_"):
        code = data.split("_", 1)[1]
        movie = await get_movie(code)
        if movie:
            await update_movie_views(code)
            await query.message.reply_video(movie["file_id"], caption=movie["title"])
        else:
            await query.message.reply_text("❌ Kino topilmadi.")
    elif data == "search":
        await query.message.reply_text("🔎 Kino nomi yoki kodini yuboring.")
    elif data == "info":
        await query.message.reply_text("ℹ️ @CinemaxUz bot. Kinolarni ko‘rish uchun foydalaning.")

# =================== TEXT HANDLER ===================

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
                await add_movie(code, file_id, title, category)
                adding_movie[user_id] = False
                await update.message.reply_text(f"✅ Qo‘shildi: {title}")
            else:
                await update.message.reply_text("⚠️ Format: kod;file_id;title;category")
            return

        if deleting_movie.get(user_id):
            await delete_movie(text)
            deleting_movie[user_id] = False
            await update.message.reply_text(f"❌ O‘chirildi: {text}")
            return

        if adding_category.get(user_id):
            await add_category(text)
            adding_category[user_id] = False
            await update.message.reply_text(f"✅ Kategoriya qo‘shildi: {text}")
            return

        if deleting_category.get(user_id):
            await delete_category(text)
            deleting_category[user_id] = False
            await update.message.reply_text(f"❌ Kategoriya o‘chirildi: {text}")
            return

        if broadcasting.get(user_id):
            broadcasting[user_id] = False
            users_list = await database.fetch_all(users.select())
            for user in users_list:
                try:
                    await context.bot.send_message(int(user["user_id"]), text)
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
            movies_list = await get_top_movies()
            msg = "🏆 Top kinolar:\n\n"
            for m in movies_list:
                msg += f"🎬 {m['title']} — {m['views']} ko‘rish\n"
            await update.message.reply_text(msg)
        elif text == "📊 Statistika":
            users_count = await get_user_count()
            movies_count = await get_movie_count()
            categories_count = len(await get_all_categories())
            await update.message.reply_text(
                f"👥 Foydalanuvchilar: {users_count}\n"
                f"🎥 Kinolar: {movies_count}\n"
                f"🗂 Kategoriyalar: {categories_count}"
            )
        elif text == "📤 Xabar yuborish":
            broadcasting[user_id] = True
            await update.message.reply_text("✉️ Xabar matnini yuboring.")
        return

    movie = await get_movie(text)
    if movie:
        await update_movie_views(text)
        await update.message.reply_video(movie["file_id"], caption=movie["title"])
        return

    results = await search_movies(text)
    if results:
        for m in results:
            await update.message.reply_video(m["file_id"], caption=m["title"])
    else:
        await update.message.reply_text("❌ Kino topilmadi.")

# =================== FILE ID HANDLER ===================

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.video:
        await update.message.reply_text(
            f"🎬 file_id: <code>{update.message.video.file_id}</code>", parse_mode="HTML"
        )

# =================== HANDLERS ===================

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.VIDEO, get_file_id))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

# =================== WEBHOOK API ===================

@fastapi_app.on_event("startup")
async def on_startup():
    await database.connect()
    await app.bot.set_webhook(WEBHOOK_URL)

@fastapi_app.on_event("shutdown")
async def on_shutdown():
    await database.disconnect()
    await app.bot.delete_webhook()

@fastapi_app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.update_queue.put(update)
    return {"ok": True}

# =================== RUN ===================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:fastapi_app", host="0.0.0.0", port=PORT)
