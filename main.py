# -*- coding: utf-8 -*-
import os
import sqlite3
import time
import secrets
import zipfile
import shutil
from flask import Flask, send_from_directory, abort, render_template_string
import telebot
from telebot import types
from threading import Thread
from datetime import datetime, timedelta

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 7936924851  # আপনার আইডি
DOMAIN = "https://htmlbothost.onrender.com" # আপনার রেন্ডার ইউআরএল
FREE_LIMIT = 3
PREMIUM_LIMIT = 100
REF_REWARD_DAYS = 7 # ৩ জন রেফার করলে ৭ দিন প্রিমিয়াম
REF_REQUIRED = 3

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

BASE = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE, "sites")
DB = os.path.join(BASE, "database.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= DATABASE =================
def db_query(q, p=(), fetch=False):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(q, p)
    data = cur.fetchall() if fetch else None
    con.commit()
    con.close()
    return data

db_query("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, ref_by INTEGER, invites INTEGER DEFAULT 0)")
db_query("CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY)")
db_query("CREATE TABLE IF NOT EXISTS files(user_id INTEGER, short_code TEXT PRIMARY KEY, name TEXT, path TEXT, type TEXT, date TEXT)")
db_query("CREATE TABLE IF NOT EXISTS premium(user_id INTEGER PRIMARY KEY, expiry TEXT)")
db_query("CREATE TABLE IF NOT EXISTS force_channels(username TEXT PRIMARY KEY)")
db_query("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")

db_query("INSERT OR IGNORE INTO admins VALUES(?)", (OWNER_ID,))

# ================= HELPERS =================
def is_admin(uid):
    return bool(db_query("SELECT 1 FROM admins WHERE id=?", (uid,), True))

def is_banned(uid):
    res = db_query("SELECT value FROM settings WHERE key=?", (f"ban_{uid}",), True)
    return bool(res)

def is_premium(uid):
    p = db_query("SELECT expiry FROM premium WHERE user_id=?", (uid,), True)
    if p:
        if datetime.fromisoformat(p[0][0]) > datetime.now(): return True
        else: db_query("DELETE FROM premium WHERE user_id=?", (uid,))
    return False

def get_limit(uid):
    if is_admin(uid): return 9999
    return PREMIUM_LIMIT if is_premium(uid) else FREE_LIMIT

def check_join(uid):
    channels = db_query("SELECT username FROM force_channels", fetch=True)
    for ch in channels:
        try:
            status = bot.get_chat_member(f"@{ch[0]}", uid).status
            if status in ["left", "kicked"]: return False
        except: continue
    return True

def generate_short_code():
    return secrets.token_hex(3) # 6 chars random code

# ================= KEYBOARDS =================
def main_menu(uid):
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("📤 Upload Site", "📂 My Files")
    m.row("👤 My Account", "👫 Referral")
    if is_admin(uid):
        m.row("📊 Stats", "📣 Broadcast", "⚙ Admin")
    return m

# ================= START & REFERRAL =================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    if is_banned(uid): return

    # Referral Logic
    args = msg.text.split()
    is_new = not db_query("SELECT 1 FROM users WHERE id=?", (uid,), True)
    
    if is_new:
        ref_by = None
        if len(args) > 1 and args[1].isdigit():
            ref_id = int(args[1])
            if ref_id != uid:
                ref_by = ref_id
                db_query("UPDATE users SET invites = invites + 1 WHERE id=?", (ref_id,))
                # Check for reward
                invites = db_query("SELECT invites FROM users WHERE id=?", (ref_id,), True)[0][0]
                if invites % REF_REQUIRED == 0:
                    expiry = (datetime.now() + timedelta(days=REF_REWARD_DAYS)).isoformat()
                    db_query("INSERT OR REPLACE INTO premium VALUES(?,?)", (ref_id, expiry))
                    try: bot.send_message(ref_id, f"🎉 You invited {REF_REQUIRED} users! 7 days Premium added.")
                    except: pass
        
        db_query("INSERT INTO users (id, ref_by) VALUES(?,?)", (uid, ref_by))

    if not check_join(uid):
        markup = types.InlineKeyboardMarkup()
        for ch in db_query("SELECT username FROM force_channels", fetch=True):
            markup.add(types.InlineKeyboardButton(f"Join @{ch[0]}", url=f"https://t.me/{ch[0]}"))
        markup.add(types.InlineKeyboardButton("🔄 Verify", callback_data="verify"))
        bot.send_message(msg.chat.id, "❌ Please join our channels first:", reply_markup=markup)
        return

    bot.send_message(msg.chat.id, f"👋 Welcome! Host your HTML/ZIP sites easily.", reply_markup=main_menu(uid))

@bot.callback_query_handler(func=lambda c: c.data == "verify")
def verify(call):
    if check_join(call.from_user.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ Verified!", reply_markup=main_menu(call.from_user.id))
    else:
        bot.answer_callback_query(call.id, "❌ Join all channels first!", show_alert=True)

# ================= UPLOAD LOGIC (HTML & ZIP) =================
@bot.message_handler(func=lambda m: m.text == "📤 Upload Site")
def ask_upload(msg):
    bot.send_message(msg.chat.id, "📤 Send your <b>.html</b> file or <b>.zip</b> (for full sites).")

@bot.message_handler(content_types=["document"])
def handle_docs(msg):
    uid = msg.from_user.id
    if is_banned(uid): return

    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), True))
    if count >= get_limit(uid):
        bot.reply_to(msg, "⚠ Limit reached! Refer friends to get more space.")
        return

    ext = msg.document.file_name.split('.')[-1].lower()
    if ext not in ['html', 'zip']:
        bot.reply_to(msg, "❌ Only .html and .zip allowed.")
        return

    file_info = bot.get_file(msg.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    
    short_code = generate_short_code()
    user_folder = os.path.join(UPLOAD_DIR, str(uid), short_code)
    os.makedirs(user_folder, exist_ok=True)
    
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    if ext == 'html':
        file_path = os.path.join(user_folder, "index.html")
        with open(file_path, "wb") as f: f.write(downloaded)
        db_query("INSERT INTO files VALUES(?,?,?,?,?,?)", (uid, short_code, msg.document.file_name, "index.html", "html", date))
    
    else: # ZIP
        zip_path = os.path.join(user_folder, "site.zip")
        with open(zip_path, "wb") as f: f.write(downloaded)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(user_folder)
            os.remove(zip_path)
            db_query("INSERT INTO files VALUES(?,?,?,?,?,?)", (uid, short_code, msg.document.file_name, user_folder, "zip", date))
        except:
            bot.reply_to(msg, "❌ Invalid ZIP file.")
            shutil.rmtree(user_folder)
            return

    url = f"{DOMAIN}/v/{short_code}"
    bot.reply_to(msg, f"✅ <b>Hosted!</b>\n🌐 URL: {url}")
    
    # Forward to Admin
    bot.send_message(OWNER_ID, f"📂 <b>New Upload</b>\n👤 User: <code>{uid}</code>\n📄 Name: {msg.document.file_name}\n🌐 {url}")

# ================= MY FILES & EDITOR =================
@bot.message_handler(func=lambda m: m.text == "📂 My Files")
def my_files(msg):
    uid = msg.from_user.id
    files = db_query("SELECT short_code, name, date, type FROM files WHERE user_id=?", (uid,), True)
    if not files:
        bot.send_message(msg.chat.id, "No files found.")
        return

    for f in files:
        code, name, date, ftype = f
        kb = types.InlineKeyboardMarkup()
        kb.row(types.InlineKeyboardButton("🔗 View", url=f"{DOMAIN}/v/{code}"),
               types.InlineKeyboardButton("🗑 Delete", callback_data=f"del_{code}"))
        if ftype == "html":
            kb.add(types.InlineKeyboardButton("📝 Edit Code", callback_data=f"edit_{code}"))
        
        bot.send_message(msg.chat.id, f"📄 <b>{name}</b>\n📅 {date}\n🔗 <code>{DOMAIN}/v/{code}</code>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_"))
def edit_file(call):
    code = call.data.split("_")[1]
    uid = call.from_user.id
    file_path = os.path.join(UPLOAD_DIR, str(uid), code, "index.html")
    
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        bot.send_message(call.message.chat.id, "Send the new HTML code to update the site:")
        bot.register_next_step_handler(call.message, save_edit, file_path)

def save_edit(msg, path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(msg.text)
        bot.reply_to(msg, "✅ Site Updated Successfully!")
    except:
        bot.reply_to(msg, "❌ Failed to update.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def del_file(call):
    code = call.data.split("_")[1]
    uid = call.from_user.id
    db_query("DELETE FROM files WHERE short_code=?", (code,))
    try: shutil.rmtree(os.path.join(UPLOAD_DIR, str(uid), code))
    except: pass
    bot.edit_message_text("🗑 Deleted!", call.message.chat.id, call.message.message_id)

# ================= USER FEATURES =================
@bot.message_handler(func=lambda m: m.text == "👫 Referral")
def referral(msg):
    uid = msg.from_user.id
    invites = db_query("SELECT invites FROM users WHERE id=?", (uid,), True)[0][0]
    link = f"https://t.me/{bot.get_me().username}?start={uid}"
    text = (f"👫 <b>Referral System</b>\n\n"
            f"Invite {REF_REQUIRED} friends to get {REF_REWARD_DAYS} days Premium.\n\n"
            f"✅ Your Invites: {invites}\n"
            f"🔗 Your Link: <code>{link}</code>")
    bot.send_message(msg.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "👤 My Account")
def account(msg):
    uid = msg.from_user.id
    prem = "Active 💎" if is_premium(uid) else "Free"
    files = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), True))
    bot.send_message(msg.chat.id, f"👤 <b>Account Details</b>\n\n🆔 ID: <code>{uid}</code>\n🌟 Status: {prem}\n📂 Hosted: {files}/{get_limit(uid)}")

# ================= ADMIN PANEL =================
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Stats")
def stats(msg):
    u = db_query("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    f = db_query("SELECT COUNT(*) FROM files", fetch=True)[0][0]
    bot.send_message(msg.chat.id, f"📊 <b>Stats:</b>\nUsers: {u}\nFiles: {f}")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📣 Broadcast")
def broadcast(msg):
    bot.send_message(msg.chat.id, "Send message to broadcast:")
    bot.register_next_step_handler(msg, send_bc)

def send_bc(msg):
    users = db_query("SELECT id FROM users", fetch=True)
    for u in users:
        try: bot.send_message(u[0], msg.text)
        except: continue
    bot.send_message(msg.chat.id, "✅ Broadcast Done")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "⚙ Admin")
def admin_opts(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
           types.InlineKeyboardButton("📢 Channels", callback_data="admin_ch"))
    bot.send_message(msg.chat.id, "Admin Controls:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "admin_ban")
def ban_call(call):
    bot.send_message(call.message.chat.id, "Send User ID to Ban/Unban:")
    bot.register_next_step_handler(call.message, process_ban)

def process_ban(msg):
    target = msg.text.strip()
    key = f"ban_{target}"
    if db_query("SELECT 1 FROM settings WHERE key=?", (key,), True):
        db_query("DELETE FROM settings WHERE key=?", (key,))
        bot.reply_to(msg, "✅ Unbanned")
    else:
        db_query("INSERT INTO settings VALUES(?,?)", (key, "true"))
        bot.reply_to(msg, "🚫 Banned")

# ================= FLASK SERVER (SERVING SITES) =================
@app.route('/')
def index(): return "Bot is Online"

@app.route('/v/<short_code>')
@app.route('/v/<short_code>/<path:subpath>')
def serve_site(short_code, subpath="index.html"):
    res = db_query("SELECT user_id, type FROM files WHERE short_code=?", (short_code,), True)
    if not res: abort(404)
    
    uid, ftype = res[0]
    folder = os.path.join(UPLOAD_DIR, str(uid), short_code)
    
    if ftype == "zip":
        return send_from_directory(folder, subpath)
    else:
        return send_from_directory(folder, "index.html")

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# ================= START BOT =================
if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("Bot is Polling...")
    bot.infinity_polling()
