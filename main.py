# -*- coding: utf-8 -*-
import os
import telebot
import sqlite3
import zipfile
from flask import Flask, send_from_directory
from telebot import types
from threading import Thread
from datetime import datetime, timedelta

# ================= CONFIG =================
TOKEN = "8262253293:AAHTMA4nrXcHWyQLwyYRI2vtBWH1ahyWmGg"
OWNER_ID = 7936924851
DOMAIN = "https://htmlbothost.onrender.com"
MAX_FILE_SIZE = 20 * 1024 * 1024

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "sites")
DB_PATH = os.path.join(BASE_DIR, "database.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS force_channels (chat_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS files (user_id INTEGER, filename TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS premium (user_id INTEGER PRIMARY KEY, expiry TEXT)")

    c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
    conn.commit()
    conn.close()

init_db()

def db(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    data = c.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return data

# ================= PREMIUM LIMIT =================
def get_limit(user_id):
    if user_id == OWNER_ID:
        return float("inf")

    admin = db("SELECT 1 FROM admins WHERE user_id=?", (user_id,), True)
    if admin:
        return float("inf")

    premium = db("SELECT expiry FROM premium WHERE user_id=?", (user_id,), True)
    if premium:
        expiry = datetime.fromisoformat(premium[0][0])
        if expiry > datetime.now():
            return 15
        else:
            db("DELETE FROM premium WHERE user_id=?", (user_id,))
            return 3

    return 3

# ================= FORCE JOIN =================
def get_channels():
    rows = db("SELECT chat_id FROM force_channels", fetch=True)
    return [r[0] for r in rows]

def check_join(user_id):
    for ch in get_channels():
        try:
            member = bot.get_chat_member(ch, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except:
            return False
    return True

# ================= FLASK =================
@app.route("/")
def home():
    return "HTML Hosting Bot Running 🚀"

@app.route("/site/<user_id>/<path:filename>")
def serve(user_id, filename):
    return send_from_directory(os.path.join(UPLOAD_DIR, user_id), filename)

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

Thread(target=run).start()

# ================= START =================
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    db("INSERT OR IGNORE INTO users VALUES (?)", (user_id,))

    channels = get_channels()
    if channels and not check_join(user_id):
        markup = types.InlineKeyboardMarkup()
        for ch in channels:
            markup.add(types.InlineKeyboardButton(f"📢 Join {ch}", url=f"https://t.me/{ch.replace('@','')}"))
        markup.add(types.InlineKeyboardButton("✅ I Joined", callback_data="recheck"))

        bot.send_message(
            message.chat.id,
            "🚨 *Access Restricted!*\n\nJoin required channels below 👇",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    bot.send_message(
        message.chat.id,
        "👋 Welcome!\n\n📤 Send .html or .zip file\n"
        "💎 /buy Premium\n📊 /stats\n👑 /admin"
    )

@bot.callback_query_handler(func=lambda c: c.data == "recheck")
def recheck(call):
    if check_join(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Verified!")
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ Still not joined!", show_alert=True)

# ================= FILE UPLOAD =================
@bot.message_handler(content_types=["document"])
def upload(message):
    user_id = message.from_user.id

    files = db("SELECT filename FROM files WHERE user_id=?", (user_id,), True)
    if len(files) >= get_limit(user_id):
        bot.reply_to(message, "⚠️ Upload limit reached!")
        return

    file = message.document

    if file.file_size > MAX_FILE_SIZE:
        bot.reply_to(message, "❌ File too large (20MB max)")
        return

    filename = file.file_name.lower()
    if not (filename.endswith(".html") or filename.endswith(".zip")):
        bot.reply_to(message, "❌ Only .html or .zip allowed")
        return

    file_info = bot.get_file(file.file_id)
    downloaded = bot.download_file(file_info.file_path)

    user_folder = os.path.join(UPLOAD_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    if filename.endswith(".html"):
        with open(os.path.join(user_folder, filename), "wb") as f:
            f.write(downloaded)
        url = f"{DOMAIN}/site/{user_id}/{filename}"
    else:
        zip_path = os.path.join(user_folder, filename)
        with open(zip_path, "wb") as f:
            f.write(downloaded)
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(user_folder)
        os.remove(zip_path)
        url = f"{DOMAIN}/site/{user_id}/index.html"

    db("INSERT INTO files VALUES (?,?)", (user_id, filename))
    bot.reply_to(message, f"✅ Hosted!\n🌐 {url}")

    # forward to admins
    admins = db("SELECT user_id FROM admins", fetch=True)
    for admin in admins:
        try:
            bot.forward_message(admin[0], message.chat.id, message.message_id)
        except:
            pass

# ================= BUY PREMIUM =================
@bot.message_handler(commands=["buy"])
def buy(message):
    user = message.from_user
    text = (
        "💎 Premium Request\n\n"
        f"User ID: {user.id}\n"
        f"Username: @{user.username}\n"
        f"Name: {user.first_name}"
    )
    bot.send_message(OWNER_ID, text)
    bot.reply_to(message, "✅ Request sent to admin!")

# ================= ADMIN PANEL =================
@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if not db("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return
    bot.send_message(
        message.chat.id,
        "👑 Admin Panel\n\n"
        "/addadmin ID\n"
        "/deladmin ID\n"
        "/addchannel @username\n"
        "/delchannel @username\n"
        "/addpremium USER_ID DAYS\n"
        "/removepremium USER_ID\n"
        "/stats"
    )

@bot.message_handler(commands=["addadmin"])
def add_admin(message):
    if message.from_user.id != OWNER_ID:
        return
    uid = int(message.text.split()[1])
    db("INSERT OR IGNORE INTO admins VALUES (?)", (uid,))
    bot.reply_to(message, "✅ Admin Added")

@bot.message_handler(commands=["deladmin"])
def del_admin(message):
    if message.from_user.id != OWNER_ID:
        return
    uid = int(message.text.split()[1])
    db("DELETE FROM admins WHERE user_id=?", (uid,))
    bot.reply_to(message, "❌ Admin Removed")

@bot.message_handler(commands=["addchannel"])
def add_channel(message):
    if not db("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return
    ch = message.text.split()[1]
    db("INSERT OR IGNORE INTO force_channels VALUES (?)", (ch,))
    bot.reply_to(message, f"✅ Channel Added: {ch}")

@bot.message_handler(commands=["delchannel"])
def del_channel(message):
    if not db("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return
    ch = message.text.split()[1]
    db("DELETE FROM force_channels WHERE chat_id=?", (ch,))
    bot.reply_to(message, f"❌ Channel Removed: {ch}")

@bot.message_handler(commands=["addpremium"])
def add_premium(message):
    if not db("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return
    parts = message.text.split()
    uid = int(parts[1])
    days = int(parts[2])
    expiry = datetime.now() + timedelta(days=days)
    db("INSERT OR REPLACE INTO premium VALUES (?,?)", (uid, expiry.isoformat()))
    bot.reply_to(message, f"✅ Premium Added\nExpires: {expiry}")

@bot.message_handler(commands=["removepremium"])
def remove_premium(message):
    if not db("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return
    uid = int(message.text.split()[1])
    db("DELETE FROM premium WHERE user_id=?", (uid,))
    bot.reply_to(message, "❌ Premium Removed")

# ================= STATS =================
@bot.message_handler(commands=["stats"])
def stats(message):
    users = len(db("SELECT user_id FROM users", fetch=True))
    files = len(db("SELECT filename FROM files", fetch=True))
    premium = len(db("SELECT user_id FROM premium", fetch=True))
    bot.reply_to(message, f"📊 Stats\n👤 Users: {users}\n📁 Files: {files}\n💎 Premium: {premium}")

# ================= RUN =================
bot.infinity_polling()
