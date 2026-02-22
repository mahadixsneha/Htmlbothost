# -*- coding: utf-8 -*-
import os
import sqlite3
from flask import Flask, send_from_directory, abort
import telebot
from telebot import types
from threading import Thread
from datetime import datetime, timedelta

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 7936924851
DOMAIN = "https://htmlbothost.onrender.com"
FREE_LIMIT = 3
PREMIUM_LIMIT = 50

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

BASE = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE, "sites")
DB = os.path.join(BASE, "database.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= DATABASE =================
def db(q, p=(), f=False):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(q, p)
    data = cur.fetchall() if f else None
    con.commit()
    con.close()
    return data

db("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY)")
db("CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY)")
db("CREATE TABLE IF NOT EXISTS files(user_id INTEGER, name TEXT, size INTEGER, date TEXT)")
db("CREATE TABLE IF NOT EXISTS premium(user_id INTEGER PRIMARY KEY, expiry TEXT)")
db("CREATE TABLE IF NOT EXISTS force_channels(username TEXT)")
db("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")

db("INSERT OR IGNORE INTO admins VALUES(?)", (OWNER_ID,))

# ================= HELPERS =================
def is_admin(uid):
    return bool(db("SELECT 1 FROM admins WHERE id=?", (uid,), True))

def is_locked():
    r = db("SELECT value FROM settings WHERE key='lock'", f=True)
    return r and r[0][0] == "on"

def is_premium(uid):
    p = db("SELECT expiry FROM premium WHERE user_id=?", (uid,), True)
    if p:
        if datetime.fromisoformat(p[0][0]) > datetime.now():
            return True
        else:
            db("DELETE FROM premium WHERE user_id=?", (uid,))
    return False

def limit(uid):
    if is_admin(uid):
        return 999
    if is_premium(uid):
        return PREMIUM_LIMIT
    return FREE_LIMIT

def check_join(uid):
    channels = db("SELECT username FROM force_channels", f=True)
    for ch in channels:
        try:
            member = bot.get_chat_member(ch[0], uid)
            if member.status in ["left", "kicked"]:
                return False
        except:
            return False
    return True

# ================= MENUS =================
def user_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("📤 Upload File", "📂 My Files")
    m.row("📢 Required Channels", "💎 Buy Premium")
    m.row("👤 My Account")
    return m

def admin_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("📤 Upload File", "📂 My Files")
    m.row("📊 Statistics", "📣 Broadcast")
    m.row("👥 Manage Channels", "💎 Premium Users")
    m.row("⚙ Admin Settings")
    return m

# ================= START =================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    db("INSERT OR IGNORE INTO users VALUES(?)", (uid,))

    if is_locked() and not is_admin(uid):
        bot.send_message(msg.chat.id, "🔒 Bot is temporarily locked.")
        return

    if not check_join(uid):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Verify", callback_data="verify"))
        text = "🚫 Please join required channels first:\n"
        for ch in db("SELECT username FROM force_channels", f=True):
            text += f"👉 @{ch[0]}\n"
        bot.send_message(msg.chat.id, text, reply_markup=markup)
        return

    if is_admin(uid):
        bot.send_message(msg.chat.id, "👑 Admin Panel", reply_markup=admin_menu())
    else:
        bot.send_message(msg.chat.id, "👋 User Panel", reply_markup=user_menu())

# ================= VERIFY =================
@bot.callback_query_handler(func=lambda c: c.data=="verify")
def verify(call):
    if check_join(call.from_user.id):
        bot.edit_message_text("✅ Verified! Use /start again.",
                              call.message.chat.id,
                              call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ Still not joined!")

# ================= UPLOAD =================
@bot.message_handler(func=lambda m: m.text=="📤 Upload File")
def ask_upload(msg):
    bot.send_message(msg.chat.id, "📤 Send .html file")

@bot.message_handler(content_types=["document"])
def upload(msg):
    uid = msg.from_user.id
    if not msg.document.file_name.endswith(".html"):
        bot.reply_to(msg, "❌ Only .html allowed")
        return

    files = db("SELECT name FROM files WHERE user_id=?", (uid,), True)
    if len(files) >= limit(uid):
        bot.reply_to(msg, "⚠ Upload limit reached.")
        return

    info = bot.get_file(msg.document.file_id)
    file_data = bot.download_file(info.file_path)

    user_folder = os.path.join(UPLOAD_DIR, str(uid))
    os.makedirs(user_folder, exist_ok=True)

    path = os.path.join(user_folder, msg.document.file_name)
    with open(path, "wb") as f:
        f.write(file_data)

    size = msg.document.file_size
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    db("INSERT INTO files VALUES(?,?,?,?)",
       (uid, msg.document.file_name, size, date))

    url = f"{DOMAIN}/site/{uid}/{msg.document.file_name}"

    bot.reply_to(msg, f"✅ Hosted Successfully!\n🌐 {url}")

    # Forward to Owner
    bot.send_message(
        OWNER_ID,
        f"📂 New Upload\n👤 {msg.from_user.username}\n🆔 {uid}\n📄 {msg.document.file_name}\n📦 {size//1024} KB"
    )

# ================= MY FILES =================
@bot.message_handler(func=lambda m: m.text=="📂 My Files")
def myfiles(msg):
    uid = msg.from_user.id
    files = db("SELECT name,size,date FROM files WHERE user_id=?", (uid,), True)

    if not files:
        bot.send_message(msg.chat.id, "❌ No files.")
        return

    for f in files:
        name, size, date = f
        url = f"{DOMAIN}/site/{uid}/{name}"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🗑 Delete", callback_data=f"del|{name}"))

        bot.send_message(
            msg.chat.id,
            f"📂 {name}\n🌐 {url}\n📅 {date}\n📦 {size//1024} KB",
            reply_markup=markup
        )

# ================= DELETE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("del|"))
def delete(call):
    uid = call.from_user.id
    name = call.data.split("|")[1]

    path = os.path.join(UPLOAD_DIR, str(uid), name)
    if os.path.exists(path):
        os.remove(path)

    db("DELETE FROM files WHERE user_id=? AND name=?", (uid, name))
    bot.edit_message_text("🗑 Deleted Successfully",
                          call.message.chat.id,
                          call.message.message_id)

# ================= ADMIN COMMANDS =================
@bot.message_handler(commands=["addadmin"])
def addadmin(msg):
    if msg.from_user.id != OWNER_ID: return
    _, uid = msg.text.split()
    db("INSERT OR IGNORE INTO admins VALUES(?)", (int(uid),))
    bot.reply_to(msg, "✅ Admin added")

@bot.message_handler(commands=["addpremium"])
def addpremium(msg):
    if not is_admin(msg.from_user.id): return
    _, uid, days = msg.text.split()
    expiry = datetime.now()+timedelta(days=int(days))
    db("INSERT OR REPLACE INTO premium VALUES(?,?)",(int(uid),expiry.isoformat()))
    bot.reply_to(msg,"✅ Premium Added")

@bot.message_handler(func=lambda m:m.text=="📊 Statistics")
def stats(msg):
    if not is_admin(msg.from_user.id): return
    users=len(db("SELECT id FROM users",f=True))
    files=len(db("SELECT name FROM files",f=True))
    prem=len(db("SELECT user_id FROM premium",f=True))
    bot.send_message(msg.chat.id,
        f"👥 Users: {users}\n📂 Files: {files}\n💎 Premium: {prem}")

# ================= FLASK =================
@app.route("/site/<uid>/<filename>")
def serve(uid,filename):
    folder=os.path.join(UPLOAD_DIR,uid)
    if os.path.exists(os.path.join(folder,filename)):
        return send_from_directory(folder,filename)
    return abort(404)

def run():
    app.run(host="0.0.0.0",port=10000)

Thread(target=run).start()
bot.infinity_polling()
