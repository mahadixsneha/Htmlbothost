# -*- coding: utf-8 -*-
import os
import telebot
import sqlite3
import zipfile
import shutil
from flask import Flask, send_from_directory
from telebot import types
from threading import Thread
from datetime import datetime, timedelta

# ================= CONFIG =================
TOKEN = "YOUR_BOT_TOKEN"
OWNER_ID = 123456789
DOMAIN = "https://yourdomain.com"  # no trailing slash
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
    c.execute("CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, expiry TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS force_channels (chat_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS files (user_id INTEGER, filename TEXT)")

    c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
    conn.commit()
    conn.close()

init_db()

def db_query(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    data = c.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return data

# ================= FORCE JOIN =================
def get_force_channels():
    rows = db_query("SELECT chat_id FROM force_channels", fetch=True)
    return [r[0] for r in rows]

def check_join(user_id):
    for ch in get_force_channels():
        try:
            member = bot.get_chat_member(ch, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except:
            return False
    return True

# ================= FLASK ROUTES =================
@app.route("/")
def home():
    return "HTML Hosting Bot Running 🚀"

@app.route("/site/<user_id>/<path:filename>")
def serve_file(user_id, filename):
    user_folder = os.path.join(UPLOAD_DIR, user_id)
    return send_from_directory(user_folder, filename)

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_flask).start()

# ================= USER LIMIT =================
def get_limit(user_id):
    if user_id == OWNER_ID:
        return float("inf")

    admin = db_query("SELECT 1 FROM admins WHERE user_id=?", (user_id,), True)
    if admin:
        return 999

    sub = db_query("SELECT expiry FROM subscriptions WHERE user_id=?", (user_id,), True)
    if sub:
        expiry = datetime.fromisoformat(sub[0][0])
        if expiry > datetime.now():
            return 15
        else:
            db_query("DELETE FROM subscriptions WHERE user_id=?", (user_id,))

    return 3

def get_file_count(user_id):
    return len(db_query("SELECT filename FROM files WHERE user_id=?", (user_id,), True))

# ================= START =================
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    db_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))

    if get_force_channels():
        if not check_join(user_id):
            markup = types.InlineKeyboardMarkup()
            for ch in get_force_channels():
                markup.add(types.InlineKeyboardButton("📢 Join", url=f"https://t.me/{ch.replace('@','')}"))
            markup.add(types.InlineKeyboardButton("✅ I've Joined", callback_data="recheck"))
            bot.send_message(message.chat.id, "⚠️ Join required channels first!", reply_markup=markup)
            return

    bot.send_message(message.chat.id,
        "👋 Welcome to HTML Hosting Bot\n\n"
        "📤 Send .html or .zip file\n"
        "📊 /stats\n"
        "👑 /admin (admin only)"
    )

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda call: call.data == "recheck")
def recheck(call):
    if check_join(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Verified")
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ Still not joined", show_alert=True)

# ================= FILE UPLOAD =================
@bot.message_handler(content_types=["document"])
def handle_file(message):
    user_id = message.from_user.id
    file = message.document

    if file.file_size > MAX_FILE_SIZE:
        bot.reply_to(message, "❌ File too large (20MB max)")
        return

    if get_file_count(user_id) >= get_limit(user_id):
        bot.reply_to(message, "⚠️ File limit reached")
        return

    file_info = bot.get_file(file.file_id)
    downloaded = bot.download_file(file_info.file_path)

    user_folder = os.path.join(UPLOAD_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    filename = file.file_name.lower()

    if filename.endswith(".html"):
        with open(os.path.join(user_folder, filename), "wb") as f:
            f.write(downloaded)

        db_query("INSERT INTO files VALUES (?,?)", (user_id, filename))
        url = f"{DOMAIN}/site/{user_id}/{filename}"
        bot.reply_to(message, f"✅ Hosted!\n{url}")

    elif filename.endswith(".zip"):
        zip_path = os.path.join(user_folder, filename)
        with open(zip_path, "wb") as f:
            f.write(downloaded)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(user_folder)

        os.remove(zip_path)

        db_query("INSERT INTO files VALUES (?,?)", (user_id, "index.html"))
        url = f"{DOMAIN}/site/{user_id}/index.html"
        bot.reply_to(message, f"✅ Website Hosted!\n{url}")

    else:
        bot.reply_to(message, "❌ Only .html or .zip allowed")

# ================= ADMIN =================
@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if not db_query("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return

    bot.reply_to(message,
        "👑 Admin Commands:\n"
        "/addadmin ID\n"
        "/deladmin ID\n"
        "/addchannel @username\n"
        "/delchannel @username\n"
        "/addsub ID days\n"
        "/broadcast text"
    )

@bot.message_handler(commands=["addadmin"])
def add_admin(message):
    if message.from_user.id != OWNER_ID:
        return
    uid = int(message.text.split()[1])
    db_query("INSERT INTO admins VALUES (?)", (uid,))
    bot.reply_to(message, "✅ Admin Added")

@bot.message_handler(commands=["addchannel"])
def add_channel(message):
    if not db_query("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return
    ch = message.text.split()[1]
    db_query("INSERT INTO force_channels VALUES (?)", (ch,))
    bot.reply_to(message, "✅ Channel Added")

@bot.message_handler(commands=["addsub"])
def add_sub(message):
    if not db_query("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return
    parts = message.text.split()
    uid = int(parts[1])
    days = int(parts[2])
    expiry = datetime.now() + timedelta(days=days)
    db_query("INSERT OR REPLACE INTO subscriptions VALUES (?,?)", (uid, expiry.isoformat()))
    bot.reply_to(message, "✅ Subscription Added")

@bot.message_handler(commands=["broadcast"])
def broadcast(message):
    if not db_query("SELECT 1 FROM admins WHERE user_id=?", (message.from_user.id,), True):
        return
    text = message.text.replace("/broadcast ", "")
    users = db_query("SELECT user_id FROM users", fetch=True)
    for u in users:
        try:
            bot.send_message(u[0], text)
        except:
            pass
    bot.reply_to(message, "✅ Broadcast Sent")

# ================= STATS =================
@bot.message_handler(commands=["stats"])
def stats(message):
    total_users = len(db_query("SELECT user_id FROM users", fetch=True))
    total_files = len(db_query("SELECT filename FROM files", fetch=True))
    bot.reply_to(message,
        f"📊 Stats:\nUsers: {total_users}\nFiles: {total_files}"
    )

# ================= RUN =================
bot.infinity_polling()
