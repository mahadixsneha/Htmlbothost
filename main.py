# -*- coding: utf-8 -*-
import os
import telebot
import sqlite3
from flask import Flask, send_from_directory
from telebot import types
from threading import Thread
from datetime import datetime, timedelta

# ================= CONFIG =================
TOKEN = "8262253293:AAHTMA4nrXcHWyQLwyYRI2vtBWH1ahyWmGg"
OWNER_ID = 7936924851
DOMAIN = "https://htmlbothost.onrender.com"
MAX_FILE_SIZE = 20 * 1024 * 1024

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "sites")
DB_PATH = os.path.join(BASE_DIR, "database.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===== DATABASE =====
def db(q, p=(), f=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(q, p)
    data = c.fetchall() if f else None
    conn.commit()
    conn.close()
    return data

db("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY)")
db("CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY)")
db("CREATE TABLE IF NOT EXISTS files(user_id INTEGER, filename TEXT)")
db("CREATE TABLE IF NOT EXISTS premium(user_id INTEGER PRIMARY KEY, expiry TEXT)")

db("INSERT OR IGNORE INTO admins VALUES(?)", (OWNER_ID,))

# ===== LIMIT SYSTEM =====
def get_limit(uid):
    if uid == OWNER_ID:
        return float("inf")

    if db("SELECT 1 FROM admins WHERE user_id=?", (uid,), True):
        return float("inf")

    p = db("SELECT expiry FROM premium WHERE user_id=?", (uid,), True)
    if p:
        expiry = datetime.fromisoformat(p[0][0])
        if expiry > datetime.now():
            return 15
        else:
            db("DELETE FROM premium WHERE user_id=?", (uid,))
    return 3

# ===== MENU =====
def user_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("📤 Upload File", "📂 Check Files")
    m.row("📢 Updates Channel", "💎 Buy Premium")
    return m

def admin_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("📤 Upload File", "📂 Check Files")
    m.row("📊 Statistics", "📣 Broadcast")
    m.row("💎 Subscriptions", "🔒 Lock Bot")
    m.row("👑 Admin Panel")
    return m

# ===== START =====
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    db("INSERT OR IGNORE INTO users VALUES(?)", (uid,))

    if db("SELECT 1 FROM admins WHERE user_id=?", (uid,), True):
        bot.send_message(msg.chat.id, "👑 Welcome Admin", reply_markup=admin_menu())
    else:
        bot.send_message(msg.chat.id, "👋 Welcome User", reply_markup=user_menu())

# ===== UPLOAD =====
@bot.message_handler(func=lambda m: m.text == "📤 Upload File")
def ask_upload(msg):
    bot.send_message(msg.chat.id, "📤 Send .html file")

@bot.message_handler(content_types=["document"])
def upload(msg):
    uid = msg.from_user.id

    files = db("SELECT filename FROM files WHERE user_id=?", (uid,), True)
    if len(files) >= get_limit(uid):
        bot.reply_to(msg, "⚠ Upload limit reached!")
        return

    file = msg.document
    filename = file.file_name

    file_info = bot.get_file(file.file_id)
    downloaded = bot.download_file(file_info.file_path)

    user_folder = os.path.join(UPLOAD_DIR, str(uid))
    os.makedirs(user_folder, exist_ok=True)

    with open(os.path.join(user_folder, filename), "wb") as f:
        f.write(downloaded)

    db("INSERT INTO files VALUES(?,?)", (uid, filename))

    url = f"{DOMAIN}/site/{uid}/{filename}"
    bot.reply_to(msg, f"✅ Hosted!\n🌐 {url}")

# ===== CHECK FILES =====
@bot.message_handler(func=lambda m: m.text == "📂 Check Files")
def check_files(msg):
    uid = msg.from_user.id
    files = db("SELECT filename FROM files WHERE user_id=?", (uid,), True)

    if not files:
        bot.send_message(msg.chat.id, "❌ No files uploaded.")
        return

    for f in files:
        filename = f[0]
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🛑 Stop", callback_data=f"stop|{filename}"),
            types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart|{filename}")
        )
        markup.row(
            types.InlineKeyboardButton("🗑 Delete", callback_data=f"delete|{filename}"),
            types.InlineKeyboardButton("📜 Logs", callback_data=f"logs|{filename}")
        )

        bot.send_message(
            msg.chat.id,
            f"📂 Controls for: {filename}\n"
            f"👤 User: {uid}\n"
            f"🟢 Status: Running",
            reply_markup=markup
        )

# ===== CALLBACKS =====
@bot.callback_query_handler(func=lambda c: True)
def callbacks(call):
    action, filename = call.data.split("|")
    uid = call.from_user.id

    if action == "delete":
        db("DELETE FROM files WHERE user_id=? AND filename=?", (uid, filename))
        bot.edit_message_text("🗑 Deleted Successfully",
                              call.message.chat.id,
                              call.message.message_id)

    elif action == "logs":
        bot.answer_callback_query(call.id, "📜 Log empty")

    else:
        bot.answer_callback_query(call.id, f"{action.upper()} clicked")

# ===== PREMIUM BUY =====
@bot.message_handler(func=lambda m: m.text == "💎 Buy Premium")
def buy(msg):
    user = msg.from_user
    bot.send_message(
        OWNER_ID,
        f"💎 Premium Request\nUser: {user.id}\nUsername: @{user.username}"
    )
    bot.reply_to(msg, "✅ Request sent to Admin!")

# ===== STATS =====
@bot.message_handler(func=lambda m: m.text == "📊 Statistics")
def stats(msg):
    users = len(db("SELECT user_id FROM users", f=True))
    files = len(db("SELECT filename FROM files", f=True))
    bot.send_message(msg.chat.id, f"📊 Users: {users}\n📁 Files: {files}")

# ===== FLASK =====
@app.route("/site/<uid>/<filename>")
def serve(uid, filename):
    return send_from_directory(os.path.join(UPLOAD_DIR, uid), filename)

def run():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run).start()

bot.infinity_polling()
