# -*- coding: utf-8 -*-
import os
import sqlite3
import time
import secrets
import zipfile
import shutil
from flask import Flask, send_from_directory, abort
import telebot
from telebot import types
from threading import Thread
from datetime import datetime, timedelta

# ================= CONFIG (নিজের তথ্য দিন) =================
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 7936924851  # আপনার আইডি
DOMAIN = "https://htmlbothost.onrender.com" # আপনার রেন্ডার ডোমেইন ইউআরএল
FREE_LIMIT = 3
PREMIUM_LIMIT = 100
REF_REWARD_DAYS = 7
REF_REQUIRED = 3

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

BASE = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE, "sites")
DB = os.path.join(BASE, "database.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= DATABASE LOGIC =================
def db_query(q, p=(), fetch=False):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(q, p)
    data = cur.fetchall() if fetch else None
    con.commit()
    con.close()
    return data

# টেবিল তৈরি
db_query("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, ref_by INTEGER, invites INTEGER DEFAULT 0)")
db_query("CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY)")
db_query("CREATE TABLE IF NOT EXISTS files(user_id INTEGER, short_code TEXT PRIMARY KEY, name TEXT, type TEXT, date TEXT)")
db_query("CREATE TABLE IF NOT EXISTS premium(user_id INTEGER PRIMARY KEY, expiry TEXT)")
db_query("CREATE TABLE IF NOT EXISTS force_channels(username TEXT PRIMARY KEY)")
db_query("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")

# ডিফল্ট অ্যাডমিন
db_query("INSERT OR IGNORE INTO admins VALUES(?)", (OWNER_ID,))

# ================= HELPERS =================
def is_admin(uid):
    return bool(db_query("SELECT 1 FROM admins WHERE id=?", (uid,), True))

def is_banned(uid):
    return bool(db_query("SELECT 1 FROM settings WHERE key=?", (f"ban_{uid}",), True))

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
            user_status = bot.get_chat_member(f"@{ch[0]}", uid).status
            if user_status in ["left", "kicked"]: return False
        except: continue
    return True

def generate_short_code():
    while True:
        code = secrets.token_hex(3)
        if not db_query("SELECT 1 FROM files WHERE short_code=?", (code,), True):
            return code

# ================= KEYBOARDS =================
def main_menu(uid):
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("📤 Upload Site", "📂 My Files")
    m.row("👤 My Account", "👫 Referral")
    m.row("💎 Buy Premium")
    if is_admin(uid):
        m.row("📊 Stats", "📣 Broadcast", "⚙ Admin Panel")
    return m

# ================= START & REFERRAL =================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    if is_banned(uid): return

    # Referral system
    args = msg.text.split()
    if not db_query("SELECT 1 FROM users WHERE id=?", (uid,), True):
        ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
        db_query("INSERT INTO users (id, ref_by) VALUES(?,?)", (uid, ref_id))
        if ref_id and ref_id != uid:
            db_query("UPDATE users SET invites = invites + 1 WHERE id=?", (ref_id,))
            invites = db_query("SELECT invites FROM users WHERE id=?", (ref_id,), True)[0][0]
            if invites % REF_REQUIRED == 0:
                expiry = (datetime.now() + timedelta(days=REF_REWARD_DAYS)).isoformat()
                db_query("INSERT OR REPLACE INTO premium VALUES(?,?)", (ref_id, expiry))
                try: bot.send_message(ref_id, "🎁 You got 7 days Premium for successful referrals!")
                except: pass

    if not check_join(uid):
        kb = types.InlineKeyboardMarkup()
        for ch in db_query("SELECT username FROM force_channels", fetch=True):
            kb.add(types.InlineKeyboardButton(f"Join @{ch[0]}", url=f"https://t.me/{ch[0]}"))
        kb.add(types.InlineKeyboardButton("🔄 Verify Join", callback_data="verify"))
        bot.send_message(msg.chat.id, "🚫 You must join our channels to use the bot:", reply_markup=kb)
        return

    bot.send_message(msg.chat.id, "👋 <b>Welcome!</b> Host your HTML or ZIP sites with custom links.", reply_markup=main_menu(uid))

@bot.callback_query_handler(func=lambda c: c.data == "verify")
def verify_callback(call):
    if check_join(call.from_user.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ Verified! Now you can use the bot.", reply_markup=main_menu(call.from_user.id))
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined yet!", show_alert=True)

# ================= UPLOAD LOGIC =================
@bot.message_handler(func=lambda m: m.text == "📤 Upload Site")
def ask_file(msg):
    bot.send_message(msg.chat.id, "Please send your <b>.html</b> file or a <b>.zip</b> file.")

@bot.message_handler(content_types=["document"])
def handle_docs(msg):
    uid = msg.from_user.id
    if is_banned(uid): return

    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), True))
    if count >= get_limit(uid):
        bot.reply_to(msg, "⚠️ Limit reached! Upgrade to Premium or refer friends.")
        return

    ext = msg.document.file_name.split('.')[-1].lower()
    if ext not in ['html', 'zip']:
        bot.reply_to(msg, "❌ Only .html and .zip files are supported.")
        return

    file_info = bot.get_file(msg.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    
    code = generate_short_code()
    path = os.path.join(UPLOAD_DIR, str(uid), code)
    os.makedirs(path, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    if ext == 'html':
        with open(os.path.join(path, "index.html"), "wb") as f: f.write(downloaded)
        db_query("INSERT INTO files VALUES(?,?,?,?,?)", (uid, code, msg.document.file_name, "html", date))
    else:
        zip_path = os.path.join(path, "site.zip")
        with open(zip_path, "wb") as f: f.write(downloaded)
        try:
            with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(path)
            os.remove(zip_path)
            db_query("INSERT INTO files VALUES(?,?,?,?,?)", (uid, code, msg.document.file_name, "zip", date))
        except:
            bot.reply_to(msg, "❌ Invalid ZIP file.")
            shutil.rmtree(path)
            return

    url = f"{DOMAIN}/v/{code}"
    bot.reply_to(msg, f"✅ <b>Site Hosted Successfully!</b>\n\n🌐 URL: {url}")
    bot.send_message(OWNER_ID, f"📂 <b>New Upload</b>\n👤 User: <code>{uid}</code>\n📄 {msg.document.file_name}\n🌐 {url}")

# ================= MY FILES & EDITOR =================
@bot.message_handler(func=lambda m: m.text == "📂 My Files")
def list_files(msg):
    uid = msg.from_user.id
    files = db_query("SELECT short_code, name, date, type FROM files WHERE user_id=?", (uid,), True)
    if not files:
        bot.send_message(msg.chat.id, "You have no hosted files.")
        return
    for f in files:
        code, name, date, ftype = f
        url = f"{DOMAIN}/v/{code}"
        kb = types.InlineKeyboardMarkup()
        kb.row(types.InlineKeyboardButton("🔗 View", url=url),
               types.InlineKeyboardButton("🗑 Delete", callback_data=f"del_{code}"))
        if ftype == 'html':
            kb.add(types.InlineKeyboardButton("📝 Edit HTML", callback_data=f"edit_{code}"))
        bot.send_message(msg.chat.id, f"📄 {name}\n📅 {date}\n🌐 <code>{url}</code>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_"))
def edit_init(call):
    code = call.data.split("_")[1]
    bot.send_message(call.message.chat.id, "Send the new HTML code to update the site:")
    bot.register_next_step_handler(call.message, edit_save, code)

def edit_save(msg, code):
    path = os.path.join(UPLOAD_DIR, str(msg.from_user.id), code, "index.html")
    if os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f: f.write(msg.text)
        bot.reply_to(msg, "✅ Successfully Updated!")
    else:
        bot.reply_to(msg, "❌ Error: File not found.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def delete_site(call):
    code = call.data.split("_")[1]
    db_query("DELETE FROM files WHERE short_code=?", (code,))
    try: shutil.rmtree(os.path.join(UPLOAD_DIR, str(call.from_user.id), code))
    except: pass
    bot.edit_message_text("🗑 Site Deleted!", call.message.chat.id, call.message.message_id)

# ================= USER FEATURES =================
@bot.message_handler(func=lambda m: m.text == "👤 My Account")
def my_account(msg):
    uid = msg.from_user.id
    status = "Premium 💎" if is_premium(uid) else "Free User"
    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), True))
    bot.send_message(msg.chat.id, f"👤 <b>Account Details</b>\n\n🆔 ID: <code>{uid}</code>\n🌟 Status: {status}\n📂 Files: {count}/{get_limit(uid)}")

@bot.message_handler(func=lambda m: m.text == "👫 Referral")
def referral_sys(msg):
    uid = msg.from_user.id
    inv = db_query("SELECT invites FROM users WHERE id=?", (uid,), True)[0][0]
    link = f"https://t.me/{bot.get_me().username}?start={uid}"
    bot.send_message(msg.chat.id, f"👫 <b>Referral Program</b>\n\nInvite {REF_REQUIRED} friends to get {REF_REWARD_DAYS} days Premium.\n\n✅ Your Invites: {inv}\n🔗 Link: <code>{link}</code>")

@bot.message_handler(func=lambda m: m.text == "💎 Buy Premium")
def buy_prem(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("👨‍💻 Contact Owner", url=f"tg://user?id={OWNER_ID}"))
    bot.send_message(msg.chat.id, "💎 <b>Premium Features:</b>\n\n- Upload up to 100 files\n- ZIP file hosting support\n- Permanent storage\n- No ads\n\n<b>To buy, contact owner:</b>", reply_markup=kb)

# ================= ADMIN PANEL =================
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Stats")
def bot_stats(msg):
    u = db_query("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    f = db_query("SELECT COUNT(*) FROM files", fetch=True)[0][0]
    bot.send_message(msg.chat.id, f"📊 <b>Bot Statistics</b>\n\nUsers: {u}\nSites Hosted: {f}")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📣 Broadcast")
def bc_init(msg):
    bot.send_message(msg.chat.id, "Send the message for broadcast (Text):")
    bot.register_next_step_handler(msg, bc_process)

def bc_process(msg):
    users = db_query("SELECT id FROM users", fetch=True)
    count = 0
    for u in users:
        try:
            bot.send_message(u[0], msg.text)
            count += 1
            time.sleep(0.05)
        except: continue
    bot.send_message(msg.chat.id, f"✅ Broadcast sent to {count} users.")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "⚙ Admin Panel")
def admin_menu(msg):
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"),
           types.InlineKeyboardButton("📢 Channels", callback_data="adm_ch"))
    kb.add(types.InlineKeyboardButton("💎 Give Premium", callback_data="adm_give"))
    bot.send_message(msg.chat.id, "⚙ <b>Admin Settings</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "adm_ch")
def adm_ch_manage(call):
    channels = db_query("SELECT username FROM force_channels", fetch=True)
    text = "📢 <b>Force Join Channels:</b>\n"
    for ch in channels: text += f"• @{ch[0]}\n"
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("➕ Add", callback_data="ch_add"),
           types.InlineKeyboardButton("➖ Remove", callback_data="ch_rem"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "ch_add")
def ch_add_ask(call):
    bot.send_message(call.message.chat.id, "Send Channel Username (without @):")
    bot.register_next_step_handler(call.message, ch_add_save)

def ch_add_save(msg):
    db_query("INSERT OR IGNORE INTO force_channels VALUES(?)", (msg.text.strip(),))
    bot.send_message(msg.chat.id, "✅ Channel Added!")

@bot.callback_query_handler(func=lambda c: c.data == "ch_rem")
def ch_rem_ask(call):
    bot.send_message(call.message.chat.id, "Send Channel Username to remove:")
    bot.register_next_step_handler(call.message, ch_rem_del)

def ch_rem_del(msg):
    db_query("DELETE FROM force_channels WHERE username=?", (msg.text.strip(),))
    bot.send_message(msg.chat.id, "🗑 Channel Removed!")

@bot.callback_query_handler(func=lambda c: c.data == "adm_give")
def give_prem_ask(call):
    bot.send_message(call.message.chat.id, "Send UserID and Days (Example: 123456 30):")
    bot.register_next_step_handler(call.message, give_prem_save)

def give_prem_save(msg):
    try:
        uid, days = msg.text.split()
        expiry = (datetime.now() + timedelta(days=int(days))).isoformat()
        db_query("INSERT OR REPLACE INTO premium VALUES(?,?)", (int(uid), expiry))
        bot.send_message(msg.chat.id, f"✅ User {uid} is now Premium for {days} days.")
        bot.send_message(uid, f"💎 You received {days} days of Premium Membership!")
    except: bot.send_message(msg.chat.id, "❌ Invalid format.")

@bot.callback_query_handler(func=lambda c: c.data == "adm_ban")
def ban_ask(call):
    bot.send_message(call.message.chat.id, "Send User ID to Ban/Unban:")
    bot.register_next_step_handler(call.message, ban_save)

def ban_save(msg):
    uid = msg.text.strip()
    key = f"ban_{uid}"
    if db_query("SELECT 1 FROM settings WHERE key=?", (key,), True):
        db_query("DELETE FROM settings WHERE key=?", (key,))
        bot.send_message(msg.chat.id, f"✅ User {uid} Unbanned.")
    else:
        db_query("INSERT INTO settings VALUES(?,?)", (key, "true"))
        bot.send_message(msg.chat.id, f"🚫 User {uid} Banned.")

# ================= SERVER (SITE SERVING) =================
@app.route('/')
def home(): return "HTML Hosting Bot is Running!"

@app.route('/v/<short_code>')
@app.route('/v/<short_code>/<path:subpath>')
def serve_site(short_code, subpath="index.html"):
    res = db_query("SELECT user_id, type FROM files WHERE short_code=?", (short_code,), True)
    if not res: abort(404)
    uid, ftype = res[0]
    folder = os.path.join(UPLOAD_DIR, str(uid), short_code)
    # ZIP এর জন্য সাব-পাথ কাজ করবে, HTML এর জন্য শুধু index.html
    actual_path = subpath if ftype == "zip" else "index.html"
    return send_from_directory(folder, actual_path)

def run_flask(): app.run(host="0.0.0.0", port=10000)

# ================= MAIN RUN =================
if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("Bot is polling...")
    bot.infinity_polling()
