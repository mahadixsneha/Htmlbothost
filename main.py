# -*- coding: utf-8 -*-
"""
HTML Hosting Bot - Full Feature Update
All features: Short URL, Analytics, User Profiles, Templates, Inline Mode,
Admin Dashboard, Image/Video Hosting, ZIP Auto-index, Webhook Mode, etc.
"""
import os
import re
import csv
import sqlite3
import time
import secrets
import zipfile
import shutil
import io
import json
import qrcode
import logging
import requests
import mimetypes
from flask import Flask, send_from_directory, abort, request, redirect, session, make_response, jsonify, Response
import telebot
from telebot import types
from threading import Thread
from datetime import datetime, timedelta
from functools import wraps

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 7936924851
DOMAIN = os.getenv("DOMAIN", "https://htmlbothost.onrender.com")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")   # Set this for webhook mode
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", secrets.token_hex(16))
FREE_LIMIT = 3
PREMIUM_LIMIT = 100
REF_REWARD_DAYS = 7
REF_REQUIRED = 3
MAX_FILE_SIZE_MB = 25
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
USE_WEBHOOK = bool(os.getenv("USE_WEBHOOK", ""))  # Set env var to enable webhook

# Supported media types for hosting
SUPPORTED_EXTENSIONS = ['html', 'zip', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mp3', 'pdf']
MEDIA_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mp3', 'pdf']

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

BASE = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE, "sites")
DB = os.path.join(BASE, "database.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= DATABASE =================
def get_con():
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def db_query(q, p=(), fetch=False, fetchone=False):
    con = get_con()
    try:
        cur = con.cursor()
        cur.execute(q, p)
        if fetchone:
            data = cur.fetchone()
        elif fetch:
            data = cur.fetchall()
        else:
            data = None
        con.commit()
        return data
    except Exception as e:
        logger.error(f"DB Error: {e} | Query: {q}")
        return None
    finally:
        con.close()

# ================= TABLE CREATION =================
db_query("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, ref_by INTEGER, invites INTEGER DEFAULT 0, lang TEXT DEFAULT 'bn', joined_date TEXT, username TEXT, balance REAL DEFAULT 0)")
db_query("CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY)")
db_query("CREATE TABLE IF NOT EXISTS files(user_id INTEGER, short_code TEXT PRIMARY KEY, name TEXT, type TEXT, date TEXT, custom_slug TEXT, views INTEGER DEFAULT 0, last_view TEXT, password TEXT, expiry TEXT, tags TEXT, is_public INTEGER DEFAULT 1, is_favorite INTEGER DEFAULT 0, scheduled_delete TEXT)")
db_query("CREATE TABLE IF NOT EXISTS premium(user_id INTEGER PRIMARY KEY, expiry TEXT, plan TEXT DEFAULT 'custom')")
db_query("CREATE TABLE IF NOT EXISTS force_channels(username TEXT PRIMARY KEY)")
db_query("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
db_query("CREATE TABLE IF NOT EXISTS site_views(short_code TEXT, ip TEXT, country TEXT, viewed_at TEXT, user_agent TEXT)")
db_query("CREATE TABLE IF NOT EXISTS payment_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount TEXT, txn_id TEXT, plan TEXT, status TEXT DEFAULT 'pending', date TEXT)")
db_query("CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER, short_code TEXT, reason TEXT, date TEXT, status TEXT DEFAULT 'pending')")
db_query("CREATE TABLE IF NOT EXISTS short_urls(code TEXT PRIMARY KEY, original_url TEXT, user_id INTEGER, date TEXT, clicks INTEGER DEFAULT 0, alias TEXT)")
db_query("CREATE TABLE IF NOT EXISTS url_aliases(alias TEXT PRIMARY KEY, short_code TEXT, user_id INTEGER)")
db_query("CREATE TABLE IF NOT EXISTS bot_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, detail TEXT, date TEXT)")
db_query("CREATE TABLE IF NOT EXISTS custom_domains(user_id INTEGER PRIMARY KEY, domain TEXT, verified INTEGER DEFAULT 0)")
db_query("CREATE TABLE IF NOT EXISTS coupons(code TEXT PRIMARY KEY, discount INTEGER, plan TEXT, uses_left INTEGER, expiry TEXT)")
db_query("CREATE TABLE IF NOT EXISTS affiliates(user_id INTEGER PRIMARY KEY, ref_code TEXT UNIQUE, earnings REAL DEFAULT 0, referrals INTEGER DEFAULT 0)")

# Migrations for new columns
try:
    db_query("ALTER TABLE files ADD COLUMN tags TEXT")
except: pass
try:
    db_query("ALTER TABLE files ADD COLUMN is_public INTEGER DEFAULT 1")
except: pass
try:
    db_query("ALTER TABLE files ADD COLUMN is_favorite INTEGER DEFAULT 0")
except: pass
try:
    db_query("ALTER TABLE files ADD COLUMN scheduled_delete TEXT")
except: pass
try:
    db_query("ALTER TABLE users ADD COLUMN username TEXT")
except: pass
try:
    db_query("ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0")
except: pass
try:
    db_query("ALTER TABLE site_views ADD COLUMN user_agent TEXT")
except: pass

# Default admin
db_query("INSERT OR IGNORE INTO admins VALUES(?)", (OWNER_ID,))

# ================= TRANSLATIONS =================
LANGS = {
    "bn": {
        "welcome": "👋 <b>স্বাগতম!</b> HTML বা ZIP সাইট হোস্ট করুন কাস্টম লিংকে।",
        "upload": "📤 সাইট আপলোড",
        "myfiles": "📂 আমার ফাইল",
        "account": "👤 আমার একাউন্ট",
        "referral": "👫 রেফারেল",
        "premium": "💎 প্রিমিয়াম কিনুন",
        "help": "❓ সাহায্য",
        "lang": "🌐 ভাষা পরিবর্তন",
        "templates": "📋 টেমপ্লেট",
        "shorturl": "🔗 Short URL",
    },
    "en": {
        "welcome": "👋 <b>Welcome!</b> Host your HTML or ZIP sites with custom links.",
        "upload": "📤 Upload Site",
        "myfiles": "📂 My Files",
        "account": "👤 My Account",
        "referral": "👫 Referral",
        "premium": "💎 Buy Premium",
        "help": "❓ Help",
        "lang": "🌐 Change Language",
        "templates": "📋 Templates",
        "shorturl": "🔗 Short URL",
    },
    "hi": {
        "welcome": "👋 <b>स्वागत है!</b> HTML या ZIP साइट होस्ट करें।",
        "upload": "📤 साइट अपलोड",
        "myfiles": "📂 मेरी फाइलें",
        "account": "👤 मेरा अकाउंट",
        "referral": "👫 रेफरल",
        "premium": "💎 प्रीमियम खरीदें",
        "help": "❓ सहायता",
        "lang": "🌐 भाषा बदलें",
        "templates": "📋 टेम्पलेट",
        "shorturl": "🔗 Short URL",
    },
    "ar": {
        "welcome": "👋 <b>مرحباً!</b> استضف مواقع HTML أو ZIP.",
        "upload": "📤 رفع موقع",
        "myfiles": "📂 ملفاتي",
        "account": "👤 حسابي",
        "referral": "👫 إحالة",
        "premium": "💎 اشترك بريميوم",
        "help": "❓ مساعدة",
        "lang": "🌐 تغيير اللغة",
        "templates": "📋 قوالب",
        "shorturl": "🔗 رابط قصير",
    }
}

def t(uid, key):
    lang = db_query("SELECT lang FROM users WHERE id=?", (uid,), fetchone=True)
    l = lang["lang"] if lang and lang["lang"] else "bn"
    return LANGS.get(l, LANGS["bn"]).get(key, key)

# ================= HELPERS =================
def is_admin(uid):
    return bool(db_query("SELECT 1 FROM admins WHERE id=?", (uid,), fetch=True))

def is_banned(uid):
    return bool(db_query("SELECT 1 FROM settings WHERE key=?", (f"ban_{uid}",), fetch=True))

def is_premium(uid):
    p = db_query("SELECT expiry FROM premium WHERE user_id=?", (uid,), fetchone=True)
    if p:
        if datetime.fromisoformat(p["expiry"]) > datetime.now():
            return True
        else:
            db_query("DELETE FROM premium WHERE user_id=?", (uid,))
    return False

def is_maintenance():
    r = db_query("SELECT value FROM settings WHERE key='maintenance'", fetchone=True)
    return r and r["value"] == "on"

def get_limit(uid):
    if is_admin(uid): return 9999
    return PREMIUM_LIMIT if is_premium(uid) else FREE_LIMIT

def get_lang(uid):
    r = db_query("SELECT lang FROM users WHERE id=?", (uid,), fetchone=True)
    return r["lang"] if r else "bn"

def check_join(uid):
    channels = db_query("SELECT username FROM force_channels", fetch=True)
    for ch in channels:
        try:
            status = bot.get_chat_member(f"@{ch['username']}", uid).status
            if status in ["left", "kicked"]:
                return False
        except:
            continue
    return True

def generate_short_code(length=6):
    while True:
        code = secrets.token_hex(3)
        if not db_query("SELECT 1 FROM files WHERE short_code=?", (code,), fetch=True):
            return code

def generate_url_code():
    while True:
        code = secrets.token_urlsafe(4)[:6]
        if not db_query("SELECT 1 FROM short_urls WHERE code=?", (code,), fetch=True):
            return code

def notify_admin_error(msg_text):
    try:
        bot.send_message(OWNER_ID, f"⚠️ <b>Bot Error:</b>\n<code>{msg_text[:3000]}</code>")
    except:
        pass

def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def log_action(user_id, action, detail=""):
    db_query("INSERT INTO bot_logs(user_id, action, detail, date) VALUES(?,?,?,?)",
             (user_id, action, detail[:500], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

def get_storage_used():
    total = 0
    for root, dirs, files in os.walk(UPLOAD_DIR):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except:
                pass
    return total

def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

def get_zip_file_list(zip_bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as z:
            return [n for n in z.namelist() if not n.endswith('/')]
    except:
        return []

def make_dir_listing_html(folder, slug, subpath=""):
    """ZIP Auto-index: index.html না থাকলে ফাইল লিস্ট দেখাও"""
    items = []
    full = os.path.join(folder, subpath)
    for name in sorted(os.listdir(full)):
        path = os.path.join(full, name)
        size = format_bytes(os.path.getsize(path)) if os.path.isfile(path) else "DIR"
        icon = "📁" if os.path.isdir(path) else "📄"
        href = f"/v/{slug}/{(subpath + '/' + name).strip('/')}"
        items.append(f'<tr><td>{icon}</td><td><a href="{href}">{name}</a></td><td>{size}</td></tr>')
    rows = "\n".join(items)
    parent = ""
    if subpath:
        parent_path = "/".join(subpath.split("/")[:-1])
        parent = f'<tr><td>⬆️</td><td><a href="/v/{slug}/{parent_path}">.. (উপরে)</a></td><td>-</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📂 ফাইল লিস্ট - {slug}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif;padding:24px}}
  h1{{font-size:22px;margin-bottom:16px;color:#5b5bd6}}
  table{{width:100%;border-collapse:collapse}}
  th,td{{padding:10px 14px;text-align:left;border-bottom:1px solid #222}}
  th{{background:#1a1a2e;color:#888;font-size:13px}}
  a{{color:#7c7cff;text-decoration:none}}
  a:hover{{text-decoration:underline}}
  tr:hover{{background:#1a1a2e}}
</style>
</head>
<body>
<h1>📂 ফাইল লিস্ট: /{subpath}</h1>
<table>
<tr><th>টাইপ</th><th>নাম</th><th>সাইজ</th></tr>
{parent}
{rows}
</table>
</body>
</html>"""

# ================= TEMPLATES =================
TEMPLATES = {
    "portfolio": {
        "name": "💼 Portfolio",
        "desc": "সুন্দর পোর্টফোলিও পেজ",
        "html": """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>My Portfolio</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:linear-gradient(135deg,#0f0f1a,#1a1a3e);color:#fff;font-family:'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{text-align:center;padding:48px 40px;max-width:500px}
.avatar{width:100px;height:100px;border-radius:50%;background:linear-gradient(135deg,#5b5bd6,#9b59b6);margin:0 auto 20px;display:flex;align-items:center;justify-content:center;font-size:40px}
h1{font-size:32px;margin-bottom:8px}
.subtitle{color:#888;margin-bottom:24px}
.skills{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-bottom:28px}
.skill{background:#1a1a2e;padding:6px 14px;border-radius:20px;font-size:13px;border:1px solid #5b5bd6}
.links{display:flex;gap:12px;justify-content:center}
.btn{background:#5b5bd6;color:#fff;padding:10px 22px;border-radius:8px;text-decoration:none;font-size:14px}
.btn.secondary{background:#1a1a2e;border:1px solid #5b5bd6}
</style>
</head>
<body>
<div class="card">
  <div class="avatar">👨‍💻</div>
  <h1>আপনার নাম</h1>
  <p class="subtitle">Web Developer & Designer</p>
  <div class="skills">
    <span class="skill">HTML/CSS</span>
    <span class="skill">JavaScript</span>
    <span class="skill">Python</span>
    <span class="skill">React</span>
  </div>
  <div class="links">
    <a href="#" class="btn">📧 যোগাযোগ</a>
    <a href="#" class="btn secondary">🐙 GitHub</a>
  </div>
</div>
</body>
</html>"""
    },
    "landing": {
        "name": "🚀 Landing Page",
        "desc": "প্রোডাক্ট ল্যান্ডিং পেজ",
        "html": """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>My Product</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif}
header{background:linear-gradient(135deg,#5b5bd6,#9b59b6);padding:80px 24px;text-align:center}
h1{font-size:42px;margin-bottom:12px}
.subtitle{font-size:18px;opacity:.85;margin-bottom:28px}
.cta{background:#fff;color:#5b5bd6;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;display:inline-block}
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:24px;padding:60px 24px;max-width:1000px;margin:0 auto}
.feature{background:#1a1a2e;padding:28px;border-radius:12px;border:1px solid #2a2a4e}
.feature .icon{font-size:36px;margin-bottom:12px}
.feature h3{margin-bottom:8px}
.feature p{color:#888;font-size:14px}
footer{text-align:center;padding:40px;color:#555}
</style>
</head>
<body>
<header>
  <h1>🚀 আপনার প্রোডাক্ট</h1>
  <p class="subtitle">সংক্ষেপে প্রোডাক্টের কথা বলুন এখানে</p>
  <a href="#" class="cta">এখনই শুরু করুন →</a>
</header>
<div class="features">
  <div class="feature"><div class="icon">⚡</div><h3>দ্রুত</h3><p>অতি দ্রুত পারফরম্যান্স</p></div>
  <div class="feature"><div class="icon">🔒</div><h3>নিরাপদ</h3><p>সম্পূর্ণ এনক্রিপ্টেড</p></div>
  <div class="feature"><div class="icon">💎</div><h3>প্রিমিয়াম</h3><p>উচ্চমানের সেবা</p></div>
</div>
<footer>© 2024 আপনার প্রোডাক্ট। সর্বস্বত্ব সংরক্ষিত।</footer>
</body>
</html>"""
    },
    "linkbio": {
        "name": "🔗 Link in Bio",
        "desc": "সোশ্যাল মিডিয়া লিংক পেজ",
        "html": """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Links</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:linear-gradient(180deg,#0f0f1a,#1a1a3e);color:#fff;font-family:'Segoe UI',sans-serif;min-height:100vh;padding:40px 20px}
.container{max-width:400px;margin:0 auto;text-align:center}
.avatar{width:80px;height:80px;border-radius:50%;background:#5b5bd6;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;font-size:36px}
h2{margin-bottom:4px}
.bio{color:#888;font-size:13px;margin-bottom:28px}
.links{display:flex;flex-direction:column;gap:12px}
.link{background:#1a1a2e;border:1px solid #2a2a4e;padding:14px 20px;border-radius:12px;text-decoration:none;color:#fff;font-size:15px;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:10px}
.link:hover{background:#2a2a4e;transform:translateY(-2px)}
</style>
</head>
<body>
<div class="container">
  <div class="avatar">😊</div>
  <h2>@username</h2>
  <p class="bio">Creator | Developer | Designer</p>
  <div class="links">
    <a href="#" class="link">🐦 Twitter / X</a>
    <a href="#" class="link">📸 Instagram</a>
    <a href="#" class="link">📺 YouTube</a>
    <a href="#" class="link">💬 Telegram</a>
    <a href="#" class="link">🌐 Website</a>
  </div>
</div>
</body>
</html>"""
    },
    "countdown": {
        "name": "⏳ Countdown",
        "desc": "ইভেন্ট কাউন্টডাউন পেজ",
        "html": """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Countdown</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:linear-gradient(135deg,#0f0f1a,#1a1a3e);color:#fff;font-family:'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px}
h1{font-size:36px;margin-bottom:8px}
p{color:#888;margin-bottom:40px}
.countdown{display:flex;gap:20px;justify-content:center;flex-wrap:wrap}
.box{background:#1a1a2e;border:1px solid #5b5bd6;padding:20px 28px;border-radius:12px;min-width:80px}
.num{font-size:48px;font-weight:bold;color:#5b5bd6;display:block}
.label{font-size:12px;color:#888;margin-top:4px}
</style>
</head>
<body>
<div>
  <h1>🚀 আসছে শীঘ্রই!</h1>
  <p>কিছু বড় ঘটতে চলেছে...</p>
  <div class="countdown">
    <div class="box"><span class="num" id="d">00</span><span class="label">দিন</span></div>
    <div class="box"><span class="num" id="h">00</span><span class="label">ঘণ্টা</span></div>
    <div class="box"><span class="num" id="m">00</span><span class="label">মিনিট</span></div>
    <div class="box"><span class="num" id="s">00</span><span class="label">সেকেন্ড</span></div>
  </div>
</div>
<script>
var target = new Date("2025-01-01T00:00:00").getTime();
function update(){
  var now = Date.now(), diff = target - now;
  if(diff < 0) diff = 0;
  var d = Math.floor(diff/86400000);
  var h = Math.floor((diff%86400000)/3600000);
  var m = Math.floor((diff%3600000)/60000);
  var s = Math.floor((diff%60000)/1000);
  document.getElementById('d').textContent = String(d).padStart(2,'0');
  document.getElementById('h').textContent = String(h).padStart(2,'0');
  document.getElementById('m').textContent = String(m).padStart(2,'0');
  document.getElementById('s').textContent = String(s).padStart(2,'0');
}
setInterval(update, 1000); update();
</script>
</body>
</html>"""
    },
}

# ================= KEYBOARDS =================
def main_menu(uid):
    lang = get_lang(uid)
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if lang == "bn":
        m.row("📤 সাইট আপলোড", "📂 আমার ফাইল")
        m.row("👤 আমার একাউন্ট", "👫 রেফারেল")
        m.row("💎 প্রিমিয়াম কিনুন", "❓ সাহায্য")
        m.row("📋 টেমপ্লেট", "🔗 Short URL")
        m.row("🌐 ভাষা পরিবর্তন")
    elif lang == "hi":
        m.row("📤 साइट अपलोड", "📂 मेरी फाइलें")
        m.row("👤 मेरा अकाउंट", "👫 रेफरल")
        m.row("💎 प्रीमियम खरीदें", "❓ सहायता")
        m.row("📋 टेम्पलेट", "🔗 Short URL")
        m.row("🌐 भाषा बदलें")
    elif lang == "ar":
        m.row("📤 رفع موقع", "📂 ملفاتي")
        m.row("👤 حسابي", "👫 إحالة")
        m.row("💎 اشترك بريميوم", "❓ مساعدة")
        m.row("📋 قوالب", "🔗 رابط قصير")
        m.row("🌐 تغيير اللغة")
    else:
        m.row("📤 Upload Site", "📂 My Files")
        m.row("👤 My Account", "👫 Referral")
        m.row("💎 Buy Premium", "❓ Help")
        m.row("📋 Templates", "🔗 Short URL")
        m.row("🌐 Change Language")
    if is_admin(uid):
        m.row("📊 Stats", "📣 Broadcast", "⚙ Admin Panel")
    return m

# ================= DECORATORS =================
def banned_check(func):
    @wraps(func)
    def wrapper(msg, *args, **kwargs):
        uid = msg.from_user.id if hasattr(msg, 'from_user') else msg.from_user.id
        if is_banned(uid):
            return
        if is_maintenance() and not is_admin(uid):
            bot.send_message(msg.chat.id if hasattr(msg, 'chat') else msg.message.chat.id,
                             "🔧 বট এখন মেইনটেন্যান্স মোডে আছে। পরে আসুন।")
            return
        return func(msg, *args, **kwargs)
    return wrapper

# ================= START / WELCOME =================
@bot.message_handler(commands=["start"])
@banned_check
def start(msg):
    uid = msg.from_user.id
    args = msg.text.split()

    # Update username
    uname = msg.from_user.username or ""
    if not db_query("SELECT 1 FROM users WHERE id=?", (uid,), fetch=True):
        ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
        joined = datetime.now().strftime("%Y-%m-%d %H:%M")
        db_query("INSERT INTO users (id, ref_by, joined_date, username) VALUES(?,?,?,?)", (uid, ref_id, joined, uname))
        if ref_id and ref_id != uid:
            db_query("UPDATE users SET invites = invites + 1 WHERE id=?", (ref_id,))
            invites = db_query("SELECT invites FROM users WHERE id=?", (ref_id,), fetchone=True)
            if invites and invites["invites"] % REF_REQUIRED == 0:
                expiry = (datetime.now() + timedelta(days=REF_REWARD_DAYS)).isoformat()
                db_query("INSERT OR REPLACE INTO premium VALUES(?,?,?)", (ref_id, expiry, "referral"))
                # Affiliate reward
                db_query("UPDATE affiliates SET earnings=earnings+50, referrals=referrals+1 WHERE user_id=?", (ref_id,))
                try:
                    bot.send_message(ref_id, f"🎁 সফল রেফারেলের জন্য আপনি {REF_REWARD_DAYS} দিনের Premium পেয়েছেন!")
                except:
                    pass
    else:
        db_query("UPDATE users SET username=? WHERE id=?", (uname, uid))

    # Generate affiliate code if not exists
    db_query("INSERT OR IGNORE INTO affiliates(user_id, ref_code) VALUES(?,?)", (uid, secrets.token_hex(4)))

    if not check_join(uid):
        kb = types.InlineKeyboardMarkup()
        for ch in db_query("SELECT username FROM force_channels", fetch=True):
            kb.add(types.InlineKeyboardButton(f"✅ Join @{ch['username']}", url=f"https://t.me/{ch['username']}"))
        kb.add(types.InlineKeyboardButton("🔄 ভেরিফাই করুন", callback_data="verify"))
        bot.send_message(msg.chat.id, "🚫 বট ব্যবহার করতে আমাদের চ্যানেলে জয়েন করুন:", reply_markup=kb)
        return

    log_action(uid, "start")
    send_welcome(msg.chat.id, uid)

def send_welcome(chat_id, uid):
    uname = db_query("SELECT username FROM users WHERE id=?", (uid,), fetchone=True)
    uname_text = f"@{uname['username']}" if uname and uname['username'] else f"#{uid}"
    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), fetch=True) or [])
    total_views = db_query("SELECT SUM(views) as v FROM files WHERE user_id=?", (uid,), fetchone=True)
    views = total_views['v'] or 0 if total_views else 0
    status = "💎 Premium" if is_premium(uid) else "🆓 Free"
    profile_url = f"{DOMAIN}/u/{uid}"

    welcome_text = f"""🌟 <b>HTML Hosting Bot-এ স্বাগতম!</b>

👤 {uname_text} | {status}
📂 সাইট: <b>{count}</b> | 👁 Views: <b>{views}</b>

<b>✨ ফিচারসমূহ:</b>
• HTML, ZIP, ছবি, ভিডিও হোস্টিং
• কাস্টম URL স্লাগ
• পাসওয়ার্ড প্রোটেকশন
• Analytics ও পরিসংখ্যান
• QR কোড জেনারেটর
• Short URL সিস্টেম
• রেডিমেড টেমপ্লেট
• ইমেজ/ভিডিও হোস্টিং

🌐 আপনার প্রোফাইল: <a href="{profile_url}">/u/{uid}</a>"""

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("📤 সাইট আপলোড", callback_data="btn_upload"),
        types.InlineKeyboardButton("📂 আমার ফাইল", callback_data="btn_myfiles")
    )
    kb.row(
        types.InlineKeyboardButton("📋 টেমপ্লেট", callback_data="show_templates"),
        types.InlineKeyboardButton("🔗 Short URL", callback_data="btn_shorturl")
    )
    kb.row(
        types.InlineKeyboardButton("👤 প্রোফাইল", url=profile_url),
        types.InlineKeyboardButton("💎 Premium", callback_data="btn_premium")
    )
    bot.send_message(chat_id, welcome_text, reply_markup=kb, disable_web_page_preview=True)
    bot.send_message(chat_id, "👇 নিচের মেনু থেকে যেকোনো অপশন বেছে নিন:", reply_markup=main_menu(uid))

@bot.callback_query_handler(func=lambda c: c.data == "verify")
def verify_callback(call):
    if check_join(call.from_user.id):
        safe_delete_message(call.message.chat.id, call.message.message_id)
        send_welcome(call.message.chat.id, call.from_user.id)
    else:
        bot.answer_callback_query(call.id, "❌ এখনো জয়েন করেননি!", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data in ["btn_upload", "btn_myfiles", "btn_premium", "btn_shorturl"])
def quick_buttons(call):
    uid = call.from_user.id
    if call.data == "btn_upload":
        ask_file_inline(call.message, uid)
    elif call.data == "btn_myfiles":
        list_files_for(call.message, uid)
    elif call.data == "btn_premium":
        show_premium(call.message, uid)
    elif call.data == "btn_shorturl":
        shorturl_menu(call.message, uid)

# ================= HELP =================
@bot.message_handler(commands=["help"])
@bot.message_handler(func=lambda m: m.text in ["❓ Help", "❓ সাহায্য", "❓ सहायता", "❓ مساعدة"])
@banned_check
def help_cmd(msg):
    text = f"""❓ <b>সাহায্য / Help</b>

📤 <b>সাইট আপলোড:</b> .html, .zip, ছবি, ভিডিও ফাইল পাঠান
📂 <b>আমার ফাইল:</b> সব হোস্টেড ফাইল দেখুন
👤 <b>একাউন্ট:</b> আপনার তথ্য দেখুন
👫 <b>রেফারেল:</b> বন্ধু আনুন, প্রিমিয়াম পান
💎 <b>প্রিমিয়াম:</b> বেশি সাইট হোস্ট করুন
📋 <b>টেমপ্লেট:</b> রেডিমেড টেমপ্লেট ব্যবহার করুন
🔗 <b>Short URL:</b> যেকোনো লিংক শর্ট করুন

<b>কমান্ড:</b>
/start - বট শুরু করুন
/help - সাহায্য
/myfiles - আমার ফাইল
/account - একাউন্ট তথ্য
/referral - রেফারেল লিংক
/shorturl [URL] - লিংক শর্ট করুন
/clone [URL_CODE] - পাবলিক সাইট ক্লোন করুন

<b>ফ্রি ইউজার:</b> {FREE_LIMIT} টি সাইট
<b>প্রিমিয়াম:</b> {PREMIUM_LIMIT} টি সাইট
<b>ফাইল সাইজ লিমিট:</b> {MAX_FILE_SIZE_MB}MB
<b>সাপোর্টেড:</b> HTML, ZIP, JPG, PNG, MP4, MP3, PDF"""
    bot.send_message(msg.chat.id, text)

# ================= LANGUAGE =================
@bot.message_handler(func=lambda m: m.text in ["🌐 ভাষা পরিবর্তন", "🌐 Change Language", "🌐 भाषा बदलें", "🌐 تغيير اللغة"])
@banned_check
def change_lang(msg):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"),
        types.InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")
    )
    kb.row(
        types.InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
        types.InlineKeyboardButton("🇸🇦 عربي", callback_data="lang_ar")
    )
    bot.send_message(msg.chat.id, "🌐 ভাষা বেছে নিন / Choose Language:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("lang_"))
def set_lang(call):
    lang = call.data.split("_")[1]
    db_query("UPDATE users SET lang=? WHERE id=?", (lang, call.from_user.id))
    bot.answer_callback_query(call.id, "✅ ভাষা পরিবর্তন হয়েছে!")
    safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, t(call.from_user.id, "welcome"), reply_markup=main_menu(call.from_user.id))

# ================= TEMPLATES =================
@bot.message_handler(func=lambda m: m.text in ["📋 টেমপ্লেট", "📋 Templates", "📋 टेम्पलेट", "📋 قوالب"])
@bot.callback_query_handler(func=lambda c: c.data == "show_templates")
@banned_check
def show_templates_menu(msg_or_call):
    if isinstance(msg_or_call, types.CallbackQuery):
        chat_id = msg_or_call.message.chat.id
        uid = msg_or_call.from_user.id
        bot.answer_callback_query(msg_or_call.id)
    else:
        chat_id = msg_or_call.chat.id
        uid = msg_or_call.from_user.id

    kb = types.InlineKeyboardMarkup()
    for key, tmpl in TEMPLATES.items():
        kb.add(types.InlineKeyboardButton(f"{tmpl['name']} — {tmpl['desc']}", callback_data=f"use_template_{key}"))
    bot.send_message(chat_id, "📋 <b>রেডিমেড টেমপ্লেট:</b>\n\nটেমপ্লেট বেছে নিন:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("use_template_"))
def use_template(call):
    uid = call.from_user.id
    key = call.data.replace("use_template_", "")
    if key not in TEMPLATES:
        bot.answer_callback_query(call.id, "❌ টেমপ্লেট পাওয়া যায়নি!", show_alert=True)
        return

    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), fetch=True) or [])
    if count >= get_limit(uid):
        bot.answer_callback_query(call.id, "⚠️ লিমিট শেষ! প্রিমিয়াম নিন।", show_alert=True)
        return

    tmpl = TEMPLATES[key]
    code = generate_short_code()
    path = os.path.join(UPLOAD_DIR, str(uid), code)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "index.html"), "w", encoding="utf-8") as f:
        f.write(tmpl["html"])

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    db_query("INSERT INTO files(user_id,short_code,name,type,date,views,is_public) VALUES(?,?,?,?,?,0,1)",
             (uid, code, f"template_{key}.html", "html", date))

    url = f"{DOMAIN}/v/{code}"
    bot.answer_callback_query(call.id, "✅ টেমপ্লেট হোস্ট হয়েছে!")
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🔗 দেখুন", url=url),
        types.InlineKeyboardButton("📝 এডিট করুন", callback_data=f"edit_{code}")
    )
    bot.send_message(call.message.chat.id,
                     f"✅ <b>{tmpl['name']} টেমপ্লেট হোস্ট হয়েছে!</b>\n\n🌐 URL: <code>{url}</code>\n\nএডিট করতে নিজের HTML পাঠান।",
                     reply_markup=kb)
    log_action(uid, "template_used", key)

# ================= SHORT URL =================
@bot.message_handler(func=lambda m: m.text in ["🔗 Short URL", "🔗 رابط قصير"])
@bot.message_handler(commands=["shorturl"])
@banned_check
def short_url_handler(msg):
    uid = msg.from_user.id
    args = msg.text.split()
    if len(args) > 1 and args[1].startswith("http"):
        create_short_url_for(msg, uid, args[1])
    else:
        shorturl_menu_msg(msg, uid)

def shorturl_menu(msg, uid):
    bot.send_message(msg.chat.id, "🔗 <b>Short URL সিস্টেম</b>\n\nশর্ট করতে চান এমন URL পাঠান:", reply_markup=types.ForceReply())
    bot.register_next_step_handler(msg, lambda m: create_short_url_for(m, uid, m.text.strip()))

def shorturl_menu_msg(msg, uid):
    bot.send_message(msg.chat.id, "🔗 <b>Short URL সিস্টেম</b>\n\nশর্ট করতে চান এমন URL পাঠান:")
    bot.register_next_step_handler(msg, lambda m: create_short_url_for(m, uid, m.text.strip()))

@bot.callback_query_handler(func=lambda c: c.data == "btn_shorturl")
def short_url_callback(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "🔗 <b>Short URL সিস্টেম</b>\n\nশর্ট করতে চান এমন URL পাঠান:")
    bot.register_next_step_handler(call.message, lambda m: create_short_url_for(m, uid, m.text.strip()))

def create_short_url_for(msg, uid, url):
    if not url.startswith("http"):
        bot.reply_to(msg, "❌ বৈধ URL দিন (http/https দিয়ে শুরু হতে হবে)।")
        return
    code = generate_url_code()
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    db_query("INSERT INTO short_urls(code, original_url, user_id, date) VALUES(?,?,?,?)",
             (code, url, uid, date))
    short = f"{DOMAIN}/s/{code}"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🔗 Short URL", url=short),
        types.InlineKeyboardButton("📊 Stats", callback_data=f"urlstats_{code}")
    )
    kb.add(types.InlineKeyboardButton("🗑 ডিলিট", callback_data=f"delurl_{code}"))
    bot.reply_to(msg, f"✅ <b>Short URL তৈরি হয়েছে!</b>\n\n🔗 <code>{short}</code>\n📄 Original: {url[:60]}...",
                 reply_markup=kb)
    log_action(uid, "short_url_created", url[:100])

@bot.callback_query_handler(func=lambda c: c.data.startswith("urlstats_"))
def url_stats(call):
    code = call.data.split("_")[1]
    r = db_query("SELECT * FROM short_urls WHERE code=? AND user_id=?", (code, call.from_user.id), fetchone=True)
    if not r:
        bot.answer_callback_query(call.id, "❌ পাওয়া যায়নি!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,
                     f"📊 <b>Short URL Stats</b>\n\n🔗 {DOMAIN}/s/{code}\n📄 {r['original_url'][:60]}\n"
                     f"👁 Clicks: {r['clicks']}\n📅 তৈরি: {r['date']}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("delurl_"))
def del_url(call):
    code = call.data.split("_")[1]
    db_query("DELETE FROM short_urls WHERE code=? AND user_id=?", (code, call.from_user.id))
    bot.answer_callback_query(call.id, "🗑 ডিলিট হয়েছে!", show_alert=True)
    bot.edit_message_text("🗑 Short URL ডিলিট হয়েছে।", call.message.chat.id, call.message.message_id)

# ================= SITE CLONE =================
@bot.message_handler(commands=["clone"])
@banned_check
def clone_site(msg):
    uid = msg.from_user.id
    args = msg.text.split()
    if len(args) < 2:
        bot.reply_to(msg, "ব্যবহার: /clone [site_code]\nউদাহরণ: /clone abc123")
        return
    slug = args[1]
    f = db_query("SELECT * FROM files WHERE (custom_slug=? OR short_code=?) AND is_public=1", (slug, slug), fetchone=True)
    if not f:
        bot.reply_to(msg, "❌ সাইটটি পাওয়া যায়নি বা পাবলিক নয়।")
        return
    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), fetch=True) or [])
    if count >= get_limit(uid):
        bot.reply_to(msg, "⚠️ লিমিট শেষ! প্রিমিয়াম নিন।")
        return

    src = os.path.join(UPLOAD_DIR, str(f["user_id"]), f["short_code"])
    if not os.path.exists(src):
        bot.reply_to(msg, "❌ সোর্স ফাইল পাওয়া যায়নি।")
        return

    new_code = generate_short_code()
    dst = os.path.join(UPLOAD_DIR, str(uid), new_code)
    shutil.copytree(src, dst)
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    db_query("INSERT INTO files(user_id,short_code,name,type,date,views,is_public) VALUES(?,?,?,?,?,0,1)",
             (uid, new_code, f"clone_{f['name']}", f["type"], date))
    url = f"{DOMAIN}/v/{new_code}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔗 দেখুন", url=url))
    bot.reply_to(msg, f"✅ <b>সাইট ক্লোন হয়েছে!</b>\n\n🌐 URL: <code>{url}</code>", reply_markup=kb)
    log_action(uid, "clone", f["short_code"])

# ================= UPLOAD LOGIC =================
@bot.message_handler(func=lambda m: m.text in ["📤 Upload Site", "📤 সাইট আপলোড", "📤 साइट अपलोड", "📤 رفع موقع"])
@banned_check
def ask_file(msg):
    uid = msg.from_user.id
    ask_file_inline(msg, uid)

def ask_file_inline(msg, uid):
    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), fetch=True) or [])
    limit = get_limit(uid)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⚙️ কাস্টম স্লাগ সেট করুন", callback_data="set_custom_slug"))
    bot.send_message(msg.chat.id,
        f"📤 <b>ফাইল আপলোড</b>\n\n"
        f"📁 সাপোর্টেড: HTML, ZIP, JPG, PNG, GIF, MP4, MP3, PDF\n"
        f"📦 সর্বোচ্চ সাইজ: {MAX_FILE_SIZE_MB}MB\n"
        f"📊 আপনার স্লট: {count}/{limit}\n\n"
        f"ফাইল পাঠান:",
        reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "set_custom_slug")
def ask_custom_slug(call):
    bot.send_message(call.message.chat.id, "🔗 কাস্টম slug লিখুন (শুধু a-z, 0-9, - ব্যবহার করুন):\nউদাহরণ: my-portfolio")
    bot.register_next_step_handler(call.message, save_custom_slug_temp)

def save_custom_slug_temp(msg):
    slug = msg.text.strip().lower().replace(" ", "-")
    if not re.match(r'^[a-z0-9\-]+$', slug):
        bot.reply_to(msg, "❌ অবৈধ slug! শুধু a-z, 0-9, - ব্যবহার করুন।")
        return
    if db_query("SELECT 1 FROM files WHERE custom_slug=?", (slug,), fetch=True):
        bot.reply_to(msg, "❌ এই slug ইতিমধ্যে ব্যবহৃত। অন্যটি বেছে নিন।")
        return
    db_query("INSERT OR REPLACE INTO settings VALUES(?,?)", (f"pending_slug_{msg.from_user.id}", slug))
    bot.reply_to(msg, f"✅ Slug সেট: <code>{slug}</code>\n\nএখন ফাইল পাঠান।")

@bot.message_handler(content_types=["document", "photo", "video", "audio"])
@banned_check
def handle_docs(msg):
    uid = msg.from_user.id
    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), fetch=True) or [])
    if count >= get_limit(uid):
        bot.reply_to(msg, "⚠️ লিমিট শেষ! প্রিমিয়াম নিন অথবা বন্ধু রেফার করুন।")
        return

    # Determine file type
    if msg.document:
        file_id = msg.document.file_id
        file_name = msg.document.file_name or "file"
        file_size = msg.document.file_size
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        file_name = "image.jpg"
        file_size = msg.photo[-1].file_size
    elif msg.video:
        file_id = msg.video.file_id
        file_name = msg.video.file_name or "video.mp4"
        file_size = msg.video.file_size
    elif msg.audio:
        file_id = msg.audio.file_id
        file_name = msg.audio.file_name or "audio.mp3"
        file_size = msg.audio.file_size
    else:
        return

    if file_size and file_size > MAX_FILE_SIZE_BYTES:
        bot.reply_to(msg, f"❌ ফাইল সাইজ {MAX_FILE_SIZE_MB}MB এর বেশি!")
        return

    ext = file_name.split('.')[-1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        bot.reply_to(msg, f"❌ সাপোর্টেড নয়। সাপোর্টেড: {', '.join(SUPPORTED_EXTENSIONS)}")
        return

    # Loading animation
    wait_msg = bot.reply_to(msg, "⏳ <b>স্টেপ ১/৩:</b> ফাইল ডাউনলোড হচ্ছে...")

    try:
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)
    except Exception as e:
        bot.edit_message_text("❌ ফাইল ডাউনলোডে সমস্যা হয়েছে।", msg.chat.id, wait_msg.message_id)
        return

    bot.edit_message_text("⏳ <b>স্টেপ ২/৩:</b> সাইট তৈরি হচ্ছে...", msg.chat.id, wait_msg.message_id)

    # Custom slug
    slug_row = db_query("SELECT value FROM settings WHERE key=?", (f"pending_slug_{uid}",), fetchone=True)
    custom_slug = slug_row["value"] if slug_row else None
    if custom_slug:
        db_query("DELETE FROM settings WHERE key=?", (f"pending_slug_{uid}",))

    code = generate_short_code()
    path = os.path.join(UPLOAD_DIR, str(uid), code)
    os.makedirs(path, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    file_type = "html"
    extra = ""

    if ext == 'html':
        with open(os.path.join(path, "index.html"), "wb") as f:
            f.write(downloaded)
        file_type = "html"
    elif ext == 'zip':
        zip_path = os.path.join(path, "site.zip")
        with open(zip_path, "wb") as f:
            f.write(downloaded)
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(path)
            os.remove(zip_path)
            file_type = "zip"
            all_files = get_zip_file_list(downloaded)
            preview_list = "\n".join([f"  📄 {f}" for f in all_files[:8]])
            if len(all_files) > 8:
                preview_list += f"\n  ...এবং আরো {len(all_files)-8}টি"
            extra = f"\n\n📦 <b>ফাইল লিস্ট ({len(all_files)}টি):</b>\n{preview_list}"
        except zipfile.BadZipFile:
            bot.edit_message_text("❌ বৈধ ZIP ফাইল নয়।", msg.chat.id, wait_msg.message_id)
            shutil.rmtree(path)
            return
    elif ext in MEDIA_EXTENSIONS:
        # For media files, create a nice viewer HTML and save the file
        save_path = os.path.join(path, file_name)
        with open(save_path, "wb") as f:
            f.write(downloaded)
        file_type = "media"
        # Create a viewer HTML
        mime, _ = mimetypes.guess_type(file_name)
        viewer = _make_media_viewer(file_name, mime or "", code)
        with open(os.path.join(path, "index.html"), "w", encoding="utf-8") as f:
            f.write(viewer)

    db_query("INSERT INTO files(user_id,short_code,name,type,date,custom_slug,views,is_public) VALUES(?,?,?,?,?,?,0,1)",
             (uid, code, file_name, file_type, date, custom_slug))

    url = f"{DOMAIN}/v/{custom_slug or code}"

    # Send to owner as backup
    try:
        backup_file = io.BytesIO(downloaded)
        backup_file.name = file_name
        bot.send_document(OWNER_ID, backup_file,
            caption=f"📦 <b>নতুন আপলোড</b>\n👤 <code>{uid}</code>\n📄 {file_name}\n🌐 {url}")
    except:
        pass

    bot.edit_message_text(
        f"✅ <b>স্টেপ ৩/৩: সফলভাবে হোস্ট হয়েছে!</b>\n\n"
        f"🌐 URL: <code>{url}</code>\n"
        f"📄 ফাইল: {file_name}\n"
        f"📅 তারিখ: {date}"
        f"{extra}",
        msg.chat.id, wait_msg.message_id
    )

    # Inline keyboard after upload
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🔗 দেখুন", url=url),
        types.InlineKeyboardButton("📊 Analytics", callback_data=f"analytics_{code}")
    )
    kb.row(
        types.InlineKeyboardButton("🔒 পাসওয়ার্ড", callback_data=f"setpass_{code}"),
        types.InlineKeyboardButton("🔗 QR কোড", callback_data=f"qr_{code}")
    )
    kb.row(
        types.InlineKeyboardButton("🏷 ট্যাগ", callback_data=f"settag_{code}"),
        types.InlineKeyboardButton("👁 Public/Private", callback_data=f"toggle_public_{code}")
    )
    bot.send_message(msg.chat.id, "⚙️ <b>সাইট অপশন:</b>", reply_markup=kb)
    log_action(uid, "upload", f"{file_name} -> {code}")

def _make_media_viewer(filename, mime, code):
    ext = filename.split('.')[-1].lower()
    if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
        media_tag = f'<img src="{filename}" alt="{filename}" style="max-width:100%;max-height:80vh;border-radius:8px">'
    elif ext in ['mp4', 'webm']:
        media_tag = f'<video src="{filename}" controls style="max-width:100%;max-height:80vh;border-radius:8px"></video>'
    elif ext in ['mp3']:
        media_tag = f'<audio src="{filename}" controls style="width:100%"></audio>'
    elif ext == 'pdf':
        media_tag = f'<embed src="{filename}" type="application/pdf" width="100%" height="80vh">'
    else:
        media_tag = f'<a href="{filename}" download class="btn">⬇️ Download</a>'
    return f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{filename}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px}}
h2{{margin-bottom:16px;font-size:18px;color:#888}}
.btn{{background:#5b5bd6;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:16px;display:inline-block}}
</style>
</head>
<body>
<h2>📄 {filename}</h2>
{media_tag}
<a href="{filename}" download class="btn">⬇️ Download</a>
</body>
</html>"""

# ================= SITE TAGS =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("settag_"))
def set_tag(call):
    code = call.data.split("_")[1]
    kb = types.InlineKeyboardMarkup()
    tags = ["portfolio", "landing-page", "blog", "store", "tool", "game", "media", "other"]
    rows = [tags[i:i+2] for i in range(0, len(tags), 2)]
    for row in rows:
        kb.row(*[types.InlineKeyboardButton(f"🏷 {t}", callback_data=f"dotag_{code}_{t}") for t in row])
    bot.send_message(call.message.chat.id, "🏷 সাইটের ট্যাগ বেছে নিন:", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dotag_"))
def do_tag(call):
    parts = call.data.split("_")
    code = parts[1]
    tag = parts[2]
    db_query("UPDATE files SET tags=? WHERE short_code=? AND user_id=?", (tag, code, call.from_user.id))
    bot.answer_callback_query(call.id, f"✅ ট্যাগ সেট: {tag}", show_alert=True)

# ================= PUBLIC/PRIVATE TOGGLE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("toggle_public_"))
def toggle_public(call):
    code = call.data.split("_")[2]
    f = db_query("SELECT is_public FROM files WHERE short_code=? AND user_id=?", (code, call.from_user.id), fetchone=True)
    if not f:
        bot.answer_callback_query(call.id, "❌ পাওয়া যায়নি!", show_alert=True)
        return
    new_val = 0 if f["is_public"] else 1
    db_query("UPDATE files SET is_public=? WHERE short_code=?", (new_val, code))
    status = "পাবলিক 🌐" if new_val else "প্রাইভেট 🔒"
    bot.answer_callback_query(call.id, f"✅ সাইট এখন {status}", show_alert=True)

# ================= FAVORITE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("fav_"))
def toggle_fav(call):
    code = call.data.split("_")[1]
    f = db_query("SELECT is_favorite FROM files WHERE short_code=? AND user_id=?", (code, call.from_user.id), fetchone=True)
    if not f:
        bot.answer_callback_query(call.id, "❌ পাওয়া যায়নি!", show_alert=True)
        return
    new_val = 0 if f["is_favorite"] else 1
    db_query("UPDATE files SET is_favorite=? WHERE short_code=?", (new_val, code))
    icon = "⭐" if new_val else "☆"
    bot.answer_callback_query(call.id, f"{icon} Favorite {'যোগ' if new_val else 'বাদ'} হয়েছে!", show_alert=True)

# ================= MY FILES =================
@bot.message_handler(commands=["myfiles"])
@bot.message_handler(func=lambda m: m.text in ["📂 My Files", "📂 আমার ফাইল", "📂 मेरी फाइलें", "📂 ملفاتي"])
@banned_check
def list_files(msg):
    uid = msg.from_user.id
    list_files_for(msg, uid)

def list_files_for(msg, uid):
    files = db_query("SELECT short_code, name, date, type, custom_slug, views, is_public, is_favorite, tags FROM files WHERE user_id=? ORDER BY is_favorite DESC, date DESC", (uid,), fetch=True)
    if not files:
        bot.send_message(msg.chat.id, "📂 আপনার কোনো হোস্টেড ফাইল নেই।\n\n📤 ফাইল আপলোড করুন!")
        return
    bot.send_message(msg.chat.id, f"📂 <b>আপনার {len(files)}টি ফাইল:</b>")
    for f in files[:10]:  # limit to 10 at a time
        code = f["short_code"]
        slug = f["custom_slug"] or code
        url = f"{DOMAIN}/v/{slug}"
        pub = "🌐" if f["is_public"] else "🔒"
        fav = "⭐" if f["is_favorite"] else "☆"
        tag = f" #{f['tags']}" if f["tags"] else ""
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("🔗 দেখুন", url=url),
            types.InlineKeyboardButton("🗑 ডিলিট", callback_data=f"del_{code}"),
            types.InlineKeyboardButton("📊 Analytics", callback_data=f"analytics_{code}")
        )
        row2 = [
            types.InlineKeyboardButton("📥 ব্যাকআপ", callback_data=f"backup_{code}"),
            types.InlineKeyboardButton("🔗 QR", callback_data=f"qr_{code}"),
            types.InlineKeyboardButton(fav + " Fav", callback_data=f"fav_{code}")
        ]
        if f["type"] == 'html':
            kb.row(*row2)
            kb.row(types.InlineKeyboardButton("📝 এডিট", callback_data=f"edit_{code}"))
        else:
            kb.row(*row2)
        kb.row(
            types.InlineKeyboardButton("🔒 পাসওয়ার্ড", callback_data=f"setpass_{code}"),
            types.InlineKeyboardButton("⏰ এক্সপায়ারি", callback_data=f"setexpiry_{code}"),
            types.InlineKeyboardButton("🔄 আপডেট", callback_data=f"update_{code}")
        )
        kb.row(
            types.InlineKeyboardButton(f"{pub} Public/Private", callback_data=f"toggle_public_{code}"),
            types.InlineKeyboardButton("🏷 ট্যাগ", callback_data=f"settag_{code}")
        )
        bot.send_message(
            msg.chat.id,
            f"{'⭐ ' if f['is_favorite'] else ''}📄 <b>{f['name']}</b>{tag}\n"
            f"📅 {f['date']} | {pub} | 👁 {f['views']}\n"
            f"🌐 <code>{url}</code>",
            reply_markup=kb
        )

# ================= QR CODE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("qr_"))
def send_qr(call):
    code = call.data.split("_")[1]
    f = db_query("SELECT custom_slug FROM files WHERE short_code=?", (code,), fetchone=True)
    slug = f["custom_slug"] if f and f["custom_slug"] else code
    url = f"{DOMAIN}/v/{slug}"
    qr = qrcode.make(url)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "qr.png"
    bot.send_photo(call.message.chat.id, buf, caption=f"🔗 QR Code\n<code>{url}</code>")
    bot.answer_callback_query(call.id)

# ================= ANALYTICS =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("analytics_"))
def show_analytics(call):
    code = call.data.split("_")[1]
    f = db_query("SELECT name, views, last_view FROM files WHERE short_code=? AND user_id=?",
                 (code, call.from_user.id), fetchone=True)
    if not f:
        bot.answer_callback_query(call.id, "❌ পাওয়া যায়নি!", show_alert=True)
        return

    # Country stats
    by_country = db_query(
        "SELECT country, COUNT(*) as cnt FROM site_views WHERE short_code=? GROUP BY country ORDER BY cnt DESC LIMIT 5",
        (code,), fetch=True) or []
    country_text = "".join(f"\n  🌍 {r['country'] or 'Unknown'}: {r['cnt']}" for r in by_country)

    # Daily stats (last 7 days)
    by_day = db_query(
        "SELECT substr(viewed_at,1,10) as day, COUNT(*) as cnt FROM site_views WHERE short_code=? GROUP BY day ORDER BY day DESC LIMIT 7",
        (code,), fetch=True) or []
    day_text = "".join(f"\n  📅 {r['day']}: {r['cnt']}" for r in by_day)

    # Unique IPs
    unique = db_query("SELECT COUNT(DISTINCT ip) as c FROM site_views WHERE short_code=?", (code,), fetchone=True)
    unique_v = unique['c'] if unique else 0

    # Browser/UA basic
    ua_rows = db_query(
        "SELECT user_agent, COUNT(*) as c FROM site_views WHERE short_code=? AND user_agent IS NOT NULL GROUP BY user_agent ORDER BY c DESC LIMIT 3",
        (code,), fetch=True) or []
    ua_text = ""
    for r in ua_rows:
        ua = r['user_agent'] or ""
        if "Mobile" in ua: br = "📱 Mobile"
        elif "Chrome" in ua: br = "🌐 Chrome"
        elif "Firefox" in ua: br = "🦊 Firefox"
        elif "Safari" in ua: br = "🍎 Safari"
        else: br = "💻 Desktop"
        ua_text += f"\n  {br}: {r['c']}"

    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,
        f"📊 <b>Analytics: {f['name']}</b>\n\n"
        f"👁 মোট Views: <b>{f['views']}</b>\n"
        f"👤 Unique Visitors: <b>{unique_v}</b>\n"
        f"🕐 শেষ Visit: {f['last_view'] or 'N/A'}\n\n"
        f"🌍 দেশ অনুযায়ী:{country_text or ' N/A'}\n\n"
        f"📅 সাপ্তাহিক:{day_text or ' N/A'}\n\n"
        f"🖥 ব্রাউজার:{ua_text or ' N/A'}"
    )

# ================= BACKUP =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("backup_"))
def send_backup(call):
    code = call.data.split("_")[1]
    uid = call.from_user.id
    f = db_query("SELECT name, type FROM files WHERE short_code=? AND user_id=?", (code, uid), fetchone=True)
    if not f:
        bot.answer_callback_query(call.id, "❌ পাওয়া যায়নি!", show_alert=True)
        return
    folder = os.path.join(UPLOAD_DIR, str(uid), code)
    if not os.path.exists(folder):
        bot.answer_callback_query(call.id, "❌ ফাইল পাওয়া যায়নি!", show_alert=True)
        return
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files_list in os.walk(folder):
            for file in files_list:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, folder)
                zf.write(filepath, arcname)
    buf.seek(0)
    buf.name = f"backup_{code}.zip"
    bot.send_document(call.message.chat.id, buf, caption=f"📥 Backup: <b>{f['name']}</b>")
    bot.answer_callback_query(call.id, "✅ ব্যাকআপ পাঠানো হয়েছে!")

# ================= PASSWORD =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("setpass_"))
def set_password(call):
    code = call.data.split("_")[1]
    bot.send_message(call.message.chat.id, "🔒 পাসওয়ার্ড লিখুন (মুছে দিতে 'remove' লিখুন):")
    bot.register_next_step_handler(call.message, save_password, code)

def save_password(msg, code):
    pw = msg.text.strip()
    if pw.lower() == "remove":
        db_query("UPDATE files SET password=NULL WHERE short_code=? AND user_id=?", (code, msg.from_user.id))
        bot.reply_to(msg, "✅ পাসওয়ার্ড সরানো হয়েছে!")
    else:
        db_query("UPDATE files SET password=? WHERE short_code=? AND user_id=?", (pw, code, msg.from_user.id))
        bot.reply_to(msg, f"✅ পাসওয়ার্ড সেট: <code>{pw}</code>")

# ================= EXPIRY / SCHEDULED DELETE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("setexpiry_"))
def set_expiry(call):
    code = call.data.split("_")[1]
    bot.send_message(call.message.chat.id, "⏰ কতদিন পরে সাইট ডিলিট হবে? (দিনের সংখ্যা লিখুন, মুছতে 'remove' লিখুন):")
    bot.register_next_step_handler(call.message, save_expiry, code)

def save_expiry(msg, code):
    val = msg.text.strip()
    if val.lower() == "remove":
        db_query("UPDATE files SET expiry=NULL WHERE short_code=? AND user_id=?", (code, msg.from_user.id))
        bot.reply_to(msg, "✅ এক্সপায়ারি সরানো হয়েছে!")
    elif val.isdigit():
        expiry = (datetime.now() + timedelta(days=int(val))).isoformat()
        db_query("UPDATE files SET expiry=? WHERE short_code=? AND user_id=?", (expiry, code, msg.from_user.id))
        bot.reply_to(msg, f"✅ সাইট {val} দিন পরে ডিলিট হবে।")
    else:
        bot.reply_to(msg, "❌ অবৈধ ইনপুট!")

# ================= UPDATE SITE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("update_"))
def update_site_ask(call):
    code = call.data.split("_")[1]
    bot.send_message(call.message.chat.id, "🔄 নতুন ফাইল পাঠান:")
    bot.register_next_step_handler(call.message, update_site_save, code)

def update_site_save(msg, code):
    if not msg.document:
        bot.reply_to(msg, "❌ ফাইল পাঠান।")
        return
    uid = msg.from_user.id
    f = db_query("SELECT type FROM files WHERE short_code=? AND user_id=?", (code, uid), fetchone=True)
    if not f:
        bot.reply_to(msg, "❌ পাওয়া যায়নি।")
        return
    ext = msg.document.file_name.split('.')[-1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        bot.reply_to(msg, "❌ সাপোর্টেড নয়।")
        return
    path = os.path.join(UPLOAD_DIR, str(uid), code)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    file_info = bot.get_file(msg.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    if ext == 'html':
        with open(os.path.join(path, "index.html"), "wb") as f_:
            f_.write(downloaded)
    elif ext == 'zip':
        zip_path = os.path.join(path, "site.zip")
        with open(zip_path, "wb") as f_:
            f_.write(downloaded)
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(path)
        os.remove(zip_path)
    else:
        with open(os.path.join(path, msg.document.file_name), "wb") as f_:
            f_.write(downloaded)
    db_query("UPDATE files SET name=?, type=?, date=? WHERE short_code=?",
             (msg.document.file_name, ext if ext in ['html','zip'] else 'media', datetime.now().strftime("%Y-%m-%d %H:%M"), code))
    bot.reply_to(msg, "✅ সাইট আপডেট হয়েছে!")

# ================= EDIT HTML =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_"))
def edit_init(call):
    code = call.data.split("_")[1]
    bot.send_message(call.message.chat.id, "📝 নতুন HTML কোড পাঠান অথবা .html ফাইল পাঠান:")
    bot.register_next_step_handler(call.message, edit_save, code)

def edit_save(msg, code):
    uid = msg.from_user.id
    path = os.path.join(UPLOAD_DIR, str(uid), code, "index.html")
    if msg.document:
        file_info = bot.get_file(msg.document.file_id)
        content = bot.download_file(file_info.file_path)
        with open(path, "wb") as f:
            f.write(content)
    elif msg.text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(msg.text)
    else:
        bot.reply_to(msg, "❌ HTML কোড বা ফাইল পাঠান।")
        return
    bot.reply_to(msg, "✅ সাইট আপডেট হয়েছে!")

# ================= DELETE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def delete_site(call):
    code = call.data.split("_")[1]
    f = db_query("SELECT user_id FROM files WHERE short_code=?", (code,), fetchone=True)
    if not f or (f["user_id"] != call.from_user.id and not is_admin(call.from_user.id)):
        bot.answer_callback_query(call.id, "❌ অনুমতি নেই!", show_alert=True)
        return
    db_query("DELETE FROM files WHERE short_code=?", (code,))
    db_query("DELETE FROM site_views WHERE short_code=?", (code,))
    try:
        shutil.rmtree(os.path.join(UPLOAD_DIR, str(f["user_id"]), code))
    except:
        pass
    bot.edit_message_text("🗑 সাইট ডিলিট হয়েছে!", call.message.chat.id, call.message.message_id)

# ================= REPORT SITE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("report_"))
def report_site(call):
    code = call.data.split("_")[1]
    bot.send_message(call.message.chat.id, "⚠️ রিপোর্টের কারণ লিখুন:")
    bot.register_next_step_handler(call.message, save_report, code)

def save_report(msg, code):
    db_query("INSERT INTO reports(reporter_id, short_code, reason, date) VALUES(?,?,?,?)",
             (msg.from_user.id, code, msg.text, datetime.now().strftime("%Y-%m-%d %H:%M")))
    bot.reply_to(msg, "✅ রিপোর্ট পাঠানো হয়েছে।")
    bot.send_message(OWNER_ID, f"🚨 <b>নতুন রিপোর্ট</b>\n👤 Reporter: <code>{msg.from_user.id}</code>\n🔗 Code: {code}\n📝 কারণ: {msg.text}")

# ================= ACCOUNT =================
@bot.message_handler(commands=["account"])
@bot.message_handler(func=lambda m: m.text in ["👤 My Account", "👤 আমার একাউন্ট", "👤 मेरा अकाउंट", "👤 حسابي"])
@banned_check
def my_account(msg):
    uid = msg.from_user.id
    status = "Premium 💎" if is_premium(uid) else "ফ্রি ইউজার"
    count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (uid,), fetch=True) or [])
    u = db_query("SELECT joined_date, invites, username FROM users WHERE id=?", (uid,), fetchone=True)
    prem = db_query("SELECT expiry, plan FROM premium WHERE user_id=?", (uid,), fetchone=True)
    aff = db_query("SELECT ref_code, earnings, referrals FROM affiliates WHERE user_id=?", (uid,), fetchone=True)
    prem_text = ""
    if prem and is_premium(uid):
        prem_text = f"\n💎 প্ল্যান: {prem['plan']}\n⏰ মেয়াদ: {prem['expiry'][:10]}"
    aff_text = ""
    if aff:
        aff_text = f"\n🔗 Ref Code: <code>{aff['ref_code']}</code>\n💰 Earnings: {aff['earnings']} পয়েন্ট"
    total_views = db_query("SELECT SUM(views) as v FROM files WHERE user_id=?", (uid,), fetchone=True)
    views = total_views['v'] or 0 if total_views else 0
    profile_url = f"{DOMAIN}/u/{uid}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🌐 পাবলিক প্রোফাইল", url=profile_url))
    bot.send_message(
        msg.chat.id,
        f"👤 <b>আপনার একাউন্ট</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Username: @{u['username'] if u and u['username'] else 'N/A'}\n"
        f"🌟 স্ট্যাটাস: {status}{prem_text}\n"
        f"📂 ফাইল: {count}/{get_limit(uid)}\n"
        f"👁 মোট Views: {views}\n"
        f"👫 রেফারেল: {u['invites'] if u else 0}{aff_text}\n"
        f"📅 যোগদান: {u['joined_date'] if u else 'N/A'}",
        reply_markup=kb
    )

# ================= REFERRAL =================
@bot.message_handler(commands=["referral"])
@bot.message_handler(func=lambda m: m.text in ["👫 Referral", "👫 রেফারেল", "👫 रेफरल", "👫 إحالة"])
@banned_check
def referral_sys(msg):
    uid = msg.from_user.id
    u = db_query("SELECT invites FROM users WHERE id=?", (uid,), fetchone=True)
    inv = u["invites"] if u else 0
    link = f"https://t.me/{bot.get_me().username}?start={uid}"
    bot.send_message(
        msg.chat.id,
        f"👫 <b>রেফারেল প্রোগ্রাম</b>\n\n"
        f"প্রতি {REF_REQUIRED} জন বন্ধু আনলে {REF_REWARD_DAYS} দিনের প্রিমিয়াম পাবেন!\n\n"
        f"✅ আপনার রেফারেল: <b>{inv}</b>\n"
        f"🎯 পরবর্তী পুরস্কারের জন্য আরো: <b>{REF_REQUIRED - (inv % REF_REQUIRED)}</b> জন\n"
        f"🔗 লিংক: <code>{link}</code>"
    )

# ================= BUY PREMIUM =================
@bot.message_handler(func=lambda m: m.text in ["💎 Buy Premium", "💎 প্রিমিয়াম কিনুন", "💎 प्रीमियम खरीदें", "💎 اشترك بريميوم"])
@banned_check
def buy_prem_msg(msg):
    show_premium(msg, msg.from_user.id)

def show_premium(msg, uid):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🥈 Silver - ৩০ দিন", callback_data="plan_silver"),
        types.InlineKeyboardButton("🥇 Gold - ৯০ দিন", callback_data="plan_gold")
    )
    kb.add(types.InlineKeyboardButton("💫 Lifetime", callback_data="plan_lifetime"))
    kb.add(types.InlineKeyboardButton("🎟 Coupon কোড", callback_data="use_coupon"))
    kb.add(types.InlineKeyboardButton("👨‍💻 Owner কে কনটাক্ট করুন", url=f"tg://user?id={OWNER_ID}"))
    bot.send_message(
        msg.chat.id,
        "💎 <b>Premium প্ল্যান:</b>\n\n"
        "🥈 <b>Silver (৩০ দিন):</b> ১০০টি সাইট, সব ফিচার\n"
        "🥇 <b>Gold (৯০ দিন):</b> সব ফিচার + প্রাধান্য সাপোর্ট\n"
        "💫 <b>Lifetime:</b> চিরস্থায়ী প্রিমিয়াম\n\n"
        "পেমেন্ট করতে Owner কে কনটাক্ট করুন:",
        reply_markup=kb
    )

# Coupon system
@bot.callback_query_handler(func=lambda c: c.data == "use_coupon")
def ask_coupon(call):
    bot.send_message(call.message.chat.id, "🎟 Coupon কোড লিখুন:")
    bot.register_next_step_handler(call.message, apply_coupon)

def apply_coupon(msg):
    code = msg.text.strip().upper()
    coupon = db_query("SELECT * FROM coupons WHERE code=?", (code,), fetchone=True)
    if not coupon:
        bot.reply_to(msg, "❌ অবৈধ coupon কোড!")
        return
    if coupon['uses_left'] <= 0:
        bot.reply_to(msg, "❌ এই coupon আর ব্যবহারযোগ্য নয়।")
        return
    if coupon['expiry'] and datetime.fromisoformat(coupon['expiry']) < datetime.now():
        bot.reply_to(msg, "❌ এই coupon মেয়াদোত্তীর্ণ।")
        return
    uid = msg.from_user.id
    # Apply discount: give premium days based on plan
    plan_days = {"silver": 30, "gold": 90, "lifetime": 99999}.get(coupon['plan'], 30)
    days = int(plan_days * (1 - coupon['discount'] / 100)) if coupon['discount'] < 100 else plan_days
    expiry = (datetime.now() + timedelta(days=days)).isoformat()
    db_query("INSERT OR REPLACE INTO premium VALUES(?,?,?)", (uid, expiry, f"coupon_{code}"))
    db_query("UPDATE coupons SET uses_left=uses_left-1 WHERE code=?", (code,))
    bot.reply_to(msg, f"🎉 Coupon সফলভাবে প্রয়োগ! আপনি {days} দিনের Premium পেয়েছেন!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_"))
def plan_selected(call):
    plan = call.data.split("_")[1]
    plans = {"silver": ("৩০ দিন", "30"), "gold": ("৯০ দিন", "90"), "lifetime": ("Lifetime", "99999")}
    plan_name, days = plans.get(plan, ("Custom", "30"))
    bot.send_message(
        call.message.chat.id,
        f"💳 <b>{plan_name} প্ল্যান</b>\n\nBkash/Nagad নম্বরে পাঠান এবং Transaction ID পাঠান:"
    )
    bot.register_next_step_handler(call.message, receive_txn, plan, days)

def receive_txn(msg, plan, days):
    txn = msg.text.strip()
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    db_query("INSERT INTO payment_requests(user_id, amount, txn_id, plan, date) VALUES(?,?,?,?,?)",
             (msg.from_user.id, days, txn, plan, date))
    bot.reply_to(msg, "✅ পেমেন্ট রিকোয়েস্ট পাঠানো হয়েছে! অ্যাডমিন যাচাই করবেন।")
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ অনুমোদন", callback_data=f"apppay_{msg.from_user.id}_{days}_{plan}"),
        types.InlineKeyboardButton("❌ প্রত্যাখ্যান", callback_data=f"rejpay_{msg.from_user.id}")
    )
    bot.send_message(OWNER_ID,
        f"💳 <b>নতুন পেমেন্ট রিকোয়েস্ট</b>\n"
        f"👤 User: <code>{msg.from_user.id}</code>\n"
        f"📦 প্ল্যান: {plan}\n"
        f"🔢 TXN ID: <code>{txn}</code>\n"
        f"📅 তারিখ: {date}", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("apppay_"))
def approve_payment(call):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.split("_")
    uid, days, plan = parts[1], parts[2], parts[3]
    expiry = (datetime.now() + timedelta(days=int(days))).isoformat()
    db_query("INSERT OR REPLACE INTO premium VALUES(?,?,?)", (int(uid), expiry, plan))
    db_query("UPDATE payment_requests SET status='approved' WHERE user_id=? ORDER BY id DESC LIMIT 1", (int(uid),))
    bot.answer_callback_query(call.id, "✅ অনুমোদিত!")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    try:
        bot.send_message(int(uid), f"🎉 আপনার প্রিমিয়াম অ্যাক্টিভ হয়েছে!\n💎 প্ল্যান: {plan}\n⏰ মেয়াদ: {days} দিন")
    except:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("rejpay_"))
def reject_payment(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.data.split("_")[1]
    db_query("UPDATE payment_requests SET status='rejected' WHERE user_id=? ORDER BY id DESC LIMIT 1", (int(uid),))
    bot.answer_callback_query(call.id, "❌ প্রত্যাখ্যান করা হয়েছে!")
    try:
        bot.send_message(int(uid), "❌ আপনার পেমেন্ট রিকোয়েস্ট প্রত্যাখ্যান হয়েছে।")
    except:
        pass

# ================= INLINE MODE =================
@bot.inline_handler(func=lambda q: True)
def inline_query(query):
    uid = query.from_user.id
    search = query.query.strip().lower()
    files = db_query("SELECT short_code, name, custom_slug, views, type FROM files WHERE user_id=? ORDER BY views DESC LIMIT 20", (uid,), fetch=True)
    results = []
    for f in (files or []):
        if search and search not in f['name'].lower():
            continue
        slug = f['custom_slug'] or f['short_code']
        url = f"{DOMAIN}/v/{slug}"
        type_icon = "📂" if f['type'] == 'zip' else "🖼" if f['type'] == 'media' else "📄"
        results.append(types.InlineQueryResultArticle(
            id=f['short_code'],
            title=f"{type_icon} {f['name']}",
            description=f"👁 {f['views']} views | {url}",
            input_message_content=types.InputTextMessageContent(
                f"🌐 <b>{f['name']}</b>\n\n🔗 {url}\n👁 Views: {f['views']}",
                parse_mode="HTML"
            ),
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔗 সাইট খুলুন", url=url)
            )
        ))
    if not results:
        results.append(types.InlineQueryResultArticle(
            id="none",
            title="📂 কোনো সাইট পাওয়া যায়নি",
            description="প্রথমে বটে সাইট আপলোড করুন",
            input_message_content=types.InputTextMessageContent(f"HTML Hosting Bot: {DOMAIN}")
        ))
    try:
        bot.answer_inline_query(query.id, results, cache_time=10)
    except Exception as e:
        logger.error(f"Inline error: {e}")

# ================= ADMIN PANEL =================
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Stats")
def bot_stats(msg):
    u = db_query("SELECT COUNT(*) as c FROM users", fetchone=True)["c"]
    f = db_query("SELECT COUNT(*) as c FROM files", fetchone=True)["c"]
    p = db_query("SELECT COUNT(*) as c FROM premium", fetchone=True)["c"]
    v = db_query("SELECT SUM(views) as c FROM files", fetchone=True)["c"] or 0
    storage = get_storage_used()
    today = datetime.now().strftime("%Y-%m-%d")
    today_uploads = db_query("SELECT COUNT(*) as c FROM files WHERE date LIKE ?", (f"{today}%",), fetchone=True)["c"] or 0
    today_users = db_query("SELECT COUNT(*) as c FROM users WHERE joined_date LIKE ?", (f"{today}%",), fetchone=True)["c"] or 0
    top_sites = db_query("SELECT name, views FROM files ORDER BY views DESC LIMIT 5", fetch=True) or []
    top_text = "".join(f"\n  {i+1}. {s['name'][:20]}: {s['views']} views" for i, s in enumerate(top_sites))
    bot.send_message(
        msg.chat.id,
        f"📊 <b>বট পরিসংখ্যান</b>\n\n"
        f"👥 মোট ইউজার: <b>{u}</b> (+{today_users} আজ)\n"
        f"📂 মোট সাইট: <b>{f}</b> (+{today_uploads} আজ)\n"
        f"💎 প্রিমিয়াম ইউজার: <b>{p}</b>\n"
        f"👁 মোট Views: <b>{v}</b>\n"
        f"💾 Storage: <b>{format_bytes(storage)}</b>\n\n"
        f"🏆 সর্বোচ্চ ভিজিটেড:{top_text or ' N/A'}"
    )

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📣 Broadcast")
def bc_init(msg):
    bot.send_message(msg.chat.id, "📣 ব্রডকাস্ট মেসেজ পাঠান:")
    bot.register_next_step_handler(msg, bc_process)

def bc_process(msg):
    users = db_query("SELECT id FROM users", fetch=True)
    count = 0
    for u in users:
        try:
            bot.copy_message(u["id"], msg.chat.id, msg.message_id)
            count += 1
            time.sleep(0.05)
        except:
            continue
    bot.send_message(msg.chat.id, f"✅ {count} জনকে ব্রডকাস্ট পাঠানো হয়েছে।")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "⚙ Admin Panel")
def admin_menu(msg):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🚫 Ban/Unban", callback_data="adm_ban"),
        types.InlineKeyboardButton("📢 Channels", callback_data="adm_ch")
    )
    kb.row(
        types.InlineKeyboardButton("💎 Premium দিন", callback_data="adm_give"),
        types.InlineKeyboardButton("💎 Premium লিস্ট", callback_data="adm_premlist")
    )
    kb.row(
        types.InlineKeyboardButton("👥 সব ইউজার", callback_data="adm_users"),
        types.InlineKeyboardButton("🔍 ইউজার খুঁজুন", callback_data="adm_search")
    )
    kb.row(
        types.InlineKeyboardButton("👤 Admin যোগ", callback_data="adm_addadmin"),
        types.InlineKeyboardButton("👤 Admin সরান", callback_data="adm_remadmin")
    )
    kb.row(
        types.InlineKeyboardButton("🔧 Maintenance", callback_data="adm_maintenance"),
        types.InlineKeyboardButton("🚨 Reports", callback_data="adm_reports")
    )
    kb.row(
        types.InlineKeyboardButton("💳 Payments", callback_data="adm_payments"),
        types.InlineKeyboardButton("🎟 Coupon", callback_data="adm_coupon")
    )
    kb.row(
        types.InlineKeyboardButton("📋 Logs", callback_data="adm_logs"),
        types.InlineKeyboardButton("💾 Storage", callback_data="adm_storage")
    )
    kb.row(
        types.InlineKeyboardButton("📤 User Export CSV", callback_data="adm_export"),
        types.InlineKeyboardButton("🗑 Bulk Delete", callback_data="adm_bulkdel")
    )
    kb.add(types.InlineKeyboardButton("🌐 Web Admin Panel", url=f"{DOMAIN}/admin"))
    bot.send_message(msg.chat.id, "⚙ <b>অ্যাডমিন প্যানেল</b>", reply_markup=kb)

# --- Premium List ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_premlist")
def premium_list(call):
    if not is_admin(call.from_user.id): return
    prems = db_query("SELECT user_id, expiry, plan FROM premium", fetch=True)
    if not prems:
        bot.answer_callback_query(call.id, "কোনো প্রিমিয়াম ইউজার নেই!", show_alert=True)
        return
    text = "💎 <b>প্রিমিয়াম ইউজার লিস্ট:</b>\n\n"
    kb = types.InlineKeyboardMarkup()
    for p in prems:
        exp = p["expiry"][:10]
        active = "✅" if datetime.fromisoformat(p["expiry"]) > datetime.now() else "❌"
        text += f"{active} <code>{p['user_id']}</code> | {p['plan']} | {exp}\n"
        kb.add(types.InlineKeyboardButton(f"🗑 Remove: {p['user_id']}", callback_data=f"rem_prem_{p['user_id']}"))
    bot.send_message(call.message.chat.id, text, reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rem_prem_"))
def remove_premium(call):
    if not is_admin(call.from_user.id): return
    uid = int(call.data.split("_")[2])
    db_query("DELETE FROM premium WHERE user_id=?", (uid,))
    bot.answer_callback_query(call.id, f"✅ User {uid} এর Premium সরানো হয়েছে!", show_alert=True)
    try:
        bot.send_message(uid, "⚠️ আপনার Premium মেম্বারশিপ সরানো হয়েছে।")
    except: pass

# --- User list ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_users")
def list_all_users(call):
    if not is_admin(call.from_user.id): return
    users = db_query("SELECT id, joined_date FROM users ORDER BY id DESC LIMIT 20", fetch=True)
    text = "👥 <b>সর্বশেষ ২০ জন ইউজার:</b>\n\n"
    for u in users:
        prem = "💎" if is_premium(u["id"]) else "🆓"
        text += f"{prem} <code>{u['id']}</code> | {u['joined_date'] or 'N/A'}\n"
    bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id)

# --- User Export CSV ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_export")
def export_users(call):
    if not is_admin(call.from_user.id): return
    bot.answer_callback_query(call.id, "⏳ CSV তৈরি হচ্ছে...")
    users = db_query("SELECT id, username, joined_date, invites FROM users ORDER BY id", fetch=True)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Username", "Joined", "Invites", "Premium", "Files"])
    for u in (users or []):
        prem = "Yes" if is_premium(u["id"]) else "No"
        fc = len(db_query("SELECT short_code FROM files WHERE user_id=?", (u["id"],), fetch=True) or [])
        writer.writerow([u["id"], u["username"] or "", u["joined_date"] or "", u["invites"], prem, fc])
    out = io.BytesIO(buf.getvalue().encode())
    out.name = f"users_{datetime.now().strftime('%Y%m%d')}.csv"
    bot.send_document(call.message.chat.id, out, caption="📤 ইউজার CSV এক্সপোর্ট")

# --- Storage Monitor ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_storage")
def storage_monitor(call):
    if not is_admin(call.from_user.id): return
    total = get_storage_used()
    file_count = db_query("SELECT COUNT(*) as c FROM files", fetchone=True)["c"]
    user_count = db_query("SELECT COUNT(DISTINCT user_id) as c FROM files", fetchone=True)["c"]
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,
                     f"💾 <b>Storage Monitor</b>\n\n"
                     f"📁 মোট ফাইল: {file_count}\n"
                     f"👥 Active Users: {user_count}\n"
                     f"💽 Total Used: <b>{format_bytes(total)}</b>")

# --- Bot Logs ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_logs")
def show_logs(call):
    if not is_admin(call.from_user.id): return
    logs = db_query("SELECT user_id, action, detail, date FROM bot_logs ORDER BY id DESC LIMIT 20", fetch=True) or []
    text = "📋 <b>সর্বশেষ ২০টি লগ:</b>\n\n"
    for l in logs:
        text += f"👤 <code>{l['user_id']}</code> | {l['action']} | {l['date'][:16]}\n"
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text[:4000])

# --- Coupon Admin ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_coupon")
def admin_coupon(call):
    if not is_admin(call.from_user.id): return
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("➕ নতুন Coupon", callback_data="coupon_create"),
        types.InlineKeyboardButton("📋 Coupon লিস্ট", callback_data="coupon_list")
    )
    bot.edit_message_text("🎟 <b>Coupon ম্যানেজমেন্ট</b>", call.message.chat.id, call.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "coupon_create")
def create_coupon_ask(call):
    if not is_admin(call.from_user.id): return
    bot.send_message(call.message.chat.id, "🎟 Coupon তৈরি করুন:\nফরম্যাট: CODE DISCOUNT_PERCENT PLAN USES_COUNT\nউদাহরণ: SAVE50 50 silver 100")
    bot.register_next_step_handler(call.message, create_coupon_save)

def create_coupon_save(msg):
    if not is_admin(msg.from_user.id): return
    try:
        parts = msg.text.split()
        code, discount, plan, uses = parts[0].upper(), int(parts[1]), parts[2], int(parts[3])
        expiry = (datetime.now() + timedelta(days=30)).isoformat()
        db_query("INSERT OR REPLACE INTO coupons VALUES(?,?,?,?,?)", (code, discount, plan, uses, expiry))
        bot.reply_to(msg, f"✅ Coupon তৈরি:\n🎟 Code: <code>{code}</code>\n💰 Discount: {discount}%\n📦 Plan: {plan}\n🔢 Uses: {uses}")
    except:
        bot.reply_to(msg, "❌ ভুল ফরম্যাট।")

@bot.callback_query_handler(func=lambda c: c.data == "coupon_list")
def list_coupons(call):
    if not is_admin(call.from_user.id): return
    coupons = db_query("SELECT * FROM coupons", fetch=True) or []
    if not coupons:
        bot.answer_callback_query(call.id, "কোনো coupon নেই!", show_alert=True)
        return
    text = "🎟 <b>Coupon লিস্ট:</b>\n\n"
    for c in coupons:
        text += f"• <code>{c['code']}</code> | {c['discount']}% | {c['plan']} | {c['uses_left']} uses\n"
    bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id)

# --- Bulk Delete ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_bulkdel")
def bulk_delete_ask(call):
    if not is_admin(call.from_user.id): return
    bot.send_message(call.message.chat.id, "🗑 Bulk Delete:\nকোন ইউজারের সব ফাইল ডিলিট করবেন? User ID পাঠান:")
    bot.register_next_step_handler(call.message, bulk_delete_do)

def bulk_delete_do(msg):
    if not is_admin(msg.from_user.id): return
    uid = msg.text.strip()
    if not uid.isdigit():
        bot.reply_to(msg, "❌ বৈধ ID দিন।")
        return
    files = db_query("SELECT short_code FROM files WHERE user_id=?", (int(uid),), fetch=True) or []
    for f in files:
        db_query("DELETE FROM site_views WHERE short_code=?", (f["short_code"],))
        try:
            shutil.rmtree(os.path.join(UPLOAD_DIR, uid, f["short_code"]))
        except: pass
    db_query("DELETE FROM files WHERE user_id=?", (int(uid),))
    bot.reply_to(msg, f"✅ User {uid} এর {len(files)}টি ফাইল ডিলিট হয়েছে।")

# --- Search user ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_search")
def search_user_ask(call):
    bot.send_message(call.message.chat.id, "🔍 ইউজার ID লিখুন:")
    bot.register_next_step_handler(call.message, search_user_show)

def search_user_show(msg):
    uid = msg.text.strip()
    if not uid.isdigit():
        bot.reply_to(msg, "❌ বৈধ ID দিন।")
        return
    u = db_query("SELECT * FROM users WHERE id=?", (int(uid),), fetchone=True)
    if not u:
        bot.reply_to(msg, "❌ ইউজার পাওয়া যায়নি।")
        return
    files_count = len(db_query("SELECT short_code FROM files WHERE user_id=?", (int(uid),), fetch=True) or [])
    prem = "💎 Premium" if is_premium(int(uid)) else "🆓 Free"
    banned = "🚫 Banned" if is_banned(int(uid)) else "✅ Active"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🚫 Ban/Unban", callback_data=f"ban_user_{uid}"),
        types.InlineKeyboardButton("💎 Premium দিন", callback_data=f"quick_prem_{uid}")
    )
    kb.add(types.InlineKeyboardButton("🗑 Premium সরান", callback_data=f"rem_prem_{uid}"))
    bot.send_message(msg.chat.id,
        f"👤 <b>ইউজার তথ্য</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Username: @{u['username'] or 'N/A'}\n"
        f"📂 ফাইল: {files_count}\n"
        f"🌟 স্ট্যাটাস: {prem}\n"
        f"⚡ অ্যাকাউন্ট: {banned}\n"
        f"📅 যোগদান: {u['joined_date'] or 'N/A'}", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ban_user_"))
def quick_ban(call):
    if not is_admin(call.from_user.id): return
    uid = call.data.split("_")[2]
    key = f"ban_{uid}"
    if db_query("SELECT 1 FROM settings WHERE key=?", (key,), fetch=True):
        db_query("DELETE FROM settings WHERE key=?", (key,))
        bot.answer_callback_query(call.id, f"✅ User {uid} Unban!", show_alert=True)
    else:
        db_query("INSERT INTO settings VALUES(?,?)", (key, "true"))
        bot.answer_callback_query(call.id, f"🚫 User {uid} Banned!", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("quick_prem_"))
def quick_premium(call):
    if not is_admin(call.from_user.id): return
    uid = int(call.data.split("_")[2])
    bot.send_message(call.message.chat.id, f"User {uid} কে কত দিনের প্রিমিয়াম দেবেন?")
    bot.register_next_step_handler(call.message, quick_prem_save, uid)

def quick_prem_save(msg, uid):
    if not msg.text.isdigit():
        bot.reply_to(msg, "❌ সংখ্যা দিন।")
        return
    days = int(msg.text)
    expiry = (datetime.now() + timedelta(days=days)).isoformat()
    db_query("INSERT OR REPLACE INTO premium VALUES(?,?,?)", (uid, expiry, "admin_gift"))
    bot.reply_to(msg, f"✅ User {uid} কে {days} দিনের Premium দেওয়া হয়েছে!")
    try:
        bot.send_message(uid, f"💎 আপনি {days} দিনের Premium পেয়েছেন!")
    except: pass

# --- Channels ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_ch")
def adm_ch_manage(call):
    channels = db_query("SELECT username FROM force_channels", fetch=True)
    text = "📢 <b>Force Join Channels:</b>\n"
    for ch in (channels or []):
        text += f"• @{ch['username']}\n"
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("➕ যোগ করুন", callback_data="ch_add"),
        types.InlineKeyboardButton("➖ সরান", callback_data="ch_rem")
    )
    bot.edit_message_text(text or "কোনো চ্যানেল নেই।", call.message.chat.id, call.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "ch_add")
def ch_add_ask(call):
    bot.send_message(call.message.chat.id, "চ্যানেল Username পাঠান (@ ছাড়া):")
    bot.register_next_step_handler(call.message, ch_add_save)

def ch_add_save(msg):
    db_query("INSERT OR IGNORE INTO force_channels VALUES(?)", (msg.text.strip(),))
    bot.send_message(msg.chat.id, "✅ চ্যানেল যোগ করা হয়েছে!")

@bot.callback_query_handler(func=lambda c: c.data == "ch_rem")
def ch_rem_ask(call):
    bot.send_message(call.message.chat.id, "সরাতে চ্যানেল Username পাঠান:")
    bot.register_next_step_handler(call.message, ch_rem_del)

def ch_rem_del(msg):
    db_query("DELETE FROM force_channels WHERE username=?", (msg.text.strip(),))
    bot.send_message(msg.chat.id, "🗑 চ্যানেল সরানো হয়েছে!")

# --- Give Premium ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_give")
def give_prem_ask(call):
    bot.send_message(call.message.chat.id, "UserID এবং দিন লিখুন (উদাহরণ: 123456 30):")
    bot.register_next_step_handler(call.message, give_prem_save)

def give_prem_save(msg):
    try:
        uid, days = msg.text.split()
        expiry = (datetime.now() + timedelta(days=int(days))).isoformat()
        db_query("INSERT OR REPLACE INTO premium VALUES(?,?,?)", (int(uid), expiry, "admin_gift"))
        bot.send_message(msg.chat.id, f"✅ User {uid} কে {days} দিনের Premium দেওয়া হয়েছে।")
        try:
            bot.send_message(int(uid), f"💎 আপনি {days} দিনের Premium পেয়েছেন!")
        except: pass
    except:
        bot.send_message(msg.chat.id, "❌ ভুল ফরম্যাট। উদাহরণ: 123456 30")

# --- Ban ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_ban")
def ban_ask(call):
    bot.send_message(call.message.chat.id, "Ban/Unban করতে User ID পাঠান:")
    bot.register_next_step_handler(call.message, ban_save)

def ban_save(msg):
    uid = msg.text.strip()
    key = f"ban_{uid}"
    if db_query("SELECT 1 FROM settings WHERE key=?", (key,), fetch=True):
        db_query("DELETE FROM settings WHERE key=?", (key,))
        bot.send_message(msg.chat.id, f"✅ User {uid} Unban করা হয়েছে।")
    else:
        db_query("INSERT INTO settings VALUES(?,?)", (key, "true"))
        bot.send_message(msg.chat.id, f"🚫 User {uid} Ban করা হয়েছে।")

# --- Add/Remove Admin ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_addadmin")
def add_admin_ask(call):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "শুধু Owner করতে পারবেন!", show_alert=True)
        return
    bot.send_message(call.message.chat.id, "নতুন Admin এর User ID পাঠান:")
    bot.register_next_step_handler(call.message, add_admin_save)

def add_admin_save(msg):
    uid = msg.text.strip()
    if uid.isdigit():
        db_query("INSERT OR IGNORE INTO admins VALUES(?)", (int(uid),))
        bot.send_message(msg.chat.id, f"✅ User {uid} কে Admin করা হয়েছে!")
        try:
            bot.send_message(int(uid), "🎉 আপনাকে Admin করা হয়েছে!")
        except: pass

@bot.callback_query_handler(func=lambda c: c.data == "adm_remadmin")
def rem_admin_ask(call):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "শুধু Owner করতে পারবেন!", show_alert=True)
        return
    admins = db_query("SELECT id FROM admins", fetch=True)
    text = "👤 <b>Admin লিস্ট:</b>\n"
    kb = types.InlineKeyboardMarkup()
    for a in admins:
        if a["id"] != OWNER_ID:
            text += f"• <code>{a['id']}</code>\n"
            kb.add(types.InlineKeyboardButton(f"❌ Remove {a['id']}", callback_data=f"remadm_{a['id']}"))
    bot.send_message(call.message.chat.id, text, reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("remadm_"))
def remove_admin(call):
    if call.from_user.id != OWNER_ID: return
    uid = int(call.data.split("_")[1])
    db_query("DELETE FROM admins WHERE id=?", (uid,))
    bot.answer_callback_query(call.id, f"✅ Admin {uid} সরানো হয়েছে!", show_alert=True)

# --- Maintenance ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_maintenance")
def toggle_maintenance(call):
    current = db_query("SELECT value FROM settings WHERE key='maintenance'", fetchone=True)
    if current and current["value"] == "on":
        db_query("UPDATE settings SET value='off' WHERE key='maintenance'")
        bot.answer_callback_query(call.id, "✅ Maintenance OFF!", show_alert=True)
    else:
        db_query("INSERT OR REPLACE INTO settings VALUES('maintenance','on')")
        bot.answer_callback_query(call.id, "🔧 Maintenance ON!", show_alert=True)

# --- Reports ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_reports")
def show_reports(call):
    reports = db_query("SELECT * FROM reports WHERE status='pending' LIMIT 10", fetch=True)
    if not reports:
        bot.answer_callback_query(call.id, "কোনো পেন্ডিং রিপোর্ট নেই!", show_alert=True)
        return
    for r in reports:
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("🗑 ডিলিট করুন", callback_data=f"del_{r['short_code']}"),
            types.InlineKeyboardButton("✅ Dismiss", callback_data=f"dismiss_report_{r['id']}")
        )
        bot.send_message(call.message.chat.id,
            f"🚨 <b>Report #{r['id']}</b>\n"
            f"👤 Reporter: <code>{r['reporter_id']}</code>\n"
            f"🔗 Code: {r['short_code']}\n"
            f"📝 কারণ: {r['reason']}\n"
            f"📅 তারিখ: {r['date']}", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dismiss_report_"))
def dismiss_report(call):
    rid = call.data.split("_")[2]
    db_query("UPDATE reports SET status='dismissed' WHERE id=?", (rid,))
    bot.answer_callback_query(call.id, "✅ Dismissed!", show_alert=True)

# --- Payments ---
@bot.callback_query_handler(func=lambda c: c.data == "adm_payments")
def show_payments(call):
    payments = db_query("SELECT * FROM payment_requests WHERE status='pending' LIMIT 10", fetch=True)
    if not payments:
        bot.answer_callback_query(call.id, "কোনো পেন্ডিং পেমেন্ট নেই!", show_alert=True)
        return
    plans_days = {"silver": "30", "gold": "90", "lifetime": "99999"}
    for p in payments:
        days = plans_days.get(p["plan"], "30")
        kb = types.InlineKeyboardMarkup()
        kb.row(
            types.InlineKeyboardButton("✅ অনুমোদন", callback_data=f"apppay_{p['user_id']}_{days}_{p['plan']}"),
            types.InlineKeyboardButton("❌ প্রত্যাখ্যান", callback_data=f"rejpay_{p['user_id']}")
        )
        bot.send_message(call.message.chat.id,
            f"💳 <b>Payment Request</b>\n"
            f"👤 User: <code>{p['user_id']}</code>\n"
            f"📦 প্ল্যান: {p['plan']}\n"
            f"🔢 TXN: <code>{p['txn_id']}</code>\n"
            f"📅 তারিখ: {p['date']}", reply_markup=kb)
    bot.answer_callback_query(call.id)

# ================= ERROR HANDLER =================
@bot.message_handler(func=lambda m: True)
@banned_check
def unknown_message(msg):
    # Don't reply to every unknown message, just ignore
    pass

# ================= FLASK ERROR PAGES =================
def custom_404(message="পেজটি পাওয়া যায়নি"):
    bot_username = ""
    try:
        bot_username = bot.get_me().username
    except: pass
    return f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>404 - পাওয়া যায়নি</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}}
  .box{{text-align:center;padding:40px}}
  .code{{font-size:120px;font-weight:900;color:#5b5bd6;line-height:1}}
  h1{{font-size:28px;margin:16px 0 8px}}
  p{{color:#888;font-size:16px;margin-bottom:28px}}
  a{{background:#5b5bd6;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-size:15px}}
  a:hover{{background:#4a4ac5}}
</style>
</head>
<body>
<div class="box">
  <div class="code">404</div>
  <h1>😕 {message}</h1>
  <p>আপনি যা খুঁজছেন তা এখানে নেই।</p>
  <a href="https://t.me/{bot_username}">🤖 বটে যান</a>
</div>
</body>
</html>""", 404

def custom_403():
    bot_username = ""
    try:
        bot_username = bot.get_me().username
    except: pass
    return f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<title>403 - অ্যাক্সেস নিষিদ্ধ</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}}
  .box{{text-align:center;padding:40px}}
  .code{{font-size:120px;font-weight:900;color:#e05252;line-height:1}}
  h1{{font-size:28px;margin:16px 0 8px}}
  p{{color:#888;font-size:16px;margin-bottom:28px}}
  a{{background:#5b5bd6;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-size:15px}}
</style>
</head>
<body>
<div class="box">
  <div class="code">403</div>
  <h1>🚫 অ্যাক্সেস নিষিদ্ধ</h1>
  <p>এই ফাইলে অ্যাক্সেস করার অনুমতি নেই।</p>
  <a href="https://t.me/{bot_username}">🤖 বটে যান</a>
</div>
</body>
</html>""", 403

def password_page(slug, error=False):
    err_html = '<p style="color:#e05252;margin-bottom:12px">❌ ভুল পাসওয়ার্ড!</p>' if error else ''
    return f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<title>🔒 পাসওয়ার্ড প্রয়োজন</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}}
  .card{{background:#1a1a2e;padding:40px;border-radius:16px;width:340px;box-shadow:0 8px 32px rgba(0,0,0,.4);text-align:center}}
  .lock{{font-size:56px;margin-bottom:16px}}
  h2{{margin-bottom:8px}}
  p.sub{{color:#888;font-size:14px;margin-bottom:24px}}
  input{{width:100%;padding:12px 16px;border-radius:8px;border:1px solid #333;background:#0f0f1a;color:#fff;font-size:15px;margin-bottom:12px}}
  input:focus{{outline:none;border-color:#5b5bd6}}
  button{{width:100%;padding:12px;background:#5b5bd6;color:#fff;border:none;border-radius:8px;font-size:15px;cursor:pointer}}
  button:hover{{background:#4a4ac5}}
</style>
</head>
<body>
<div class="card">
  <div class="lock">🔒</div>
  <h2>পাসওয়ার্ড প্রয়োজন</h2>
  <p class="sub">এই সাইটটি সুরক্ষিত।</p>
  {err_html}
  <form method="POST" action="/v/{slug}/auth">
    <input type="password" name="pw" placeholder="পাসওয়ার্ড দিন" autofocus required>
    <button type="submit">প্রবেশ করুন →</button>
  </form>
</div>
</body>
</html>"""

# ================= FLASK APP =================
app.secret_key = os.getenv("FLASK_SECRET", secrets.token_hex(32))

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if response.content_type and any(ct in response.content_type for ct in ['image/', 'text/css', 'javascript']):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

# ================= HOME PAGE =================
@app.route('/')
def home():
    try:
        username = bot.get_me().username
    except:
        username = "htmlhostbot"
    total_users = db_query("SELECT COUNT(*) as c FROM users", fetchone=True)["c"] or 0
    total_sites = db_query("SELECT COUNT(*) as c FROM files", fetchone=True)["c"] or 0
    total_views = db_query("SELECT SUM(views) as c FROM files", fetchone=True)["c"] or 0
    return f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🤖 HTML Hosting Bot</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif}}
header{{background:linear-gradient(135deg,#1a1a3e,#0f0f1a);padding:80px 24px;text-align:center;border-bottom:1px solid #1a1a2e}}
.logo{{font-size:64px;margin-bottom:16px}}
h1{{font-size:40px;margin-bottom:8px;background:linear-gradient(135deg,#5b5bd6,#9b59b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.sub{{color:#888;font-size:18px;margin-bottom:32px}}
.cta{{display:inline-block;background:#5b5bd6;color:#fff;padding:14px 36px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:600;transition:.2s}}
.cta:hover{{background:#4a4ac5;transform:translateY(-2px)}}
.stats{{display:flex;justify-content:center;gap:40px;padding:48px 24px;background:#111120;flex-wrap:wrap}}
.stat{{text-align:center}}
.stat .num{{font-size:36px;font-weight:bold;color:#5b5bd6}}
.stat .label{{color:#888;font-size:14px;margin-top:4px}}
.features{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px;padding:60px 24px;max-width:1100px;margin:0 auto}}
.feature{{background:#1a1a2e;padding:28px;border-radius:12px;border:1px solid #2a2a4e}}
.feature .icon{{font-size:36px;margin-bottom:12px}}
.feature h3{{margin-bottom:8px;color:#fff}}
.feature p{{color:#666;font-size:14px;line-height:1.6}}
footer{{text-align:center;padding:40px;color:#444;border-top:1px solid #1a1a2e}}
</style>
</head>
<body>
<header>
  <div class="logo">🤖</div>
  <h1>HTML Hosting Bot</h1>
  <p class="sub">Telegram-এ HTML, ZIP, ছবি, ভিডিও হোস্ট করুন বিনামূল্যে!</p>
  <a href="https://t.me/{username}" class="cta">🚀 Bot শুরু করুন</a>
</header>
<div class="stats">
  <div class="stat"><div class="num">{total_users:,}</div><div class="label">👥 ইউজার</div></div>
  <div class="stat"><div class="num">{total_sites:,}</div><div class="label">🌐 সাইট</div></div>
  <div class="stat"><div class="num">{total_views:,}</div><div class="label">👁 Views</div></div>
</div>
<div class="features">
  <div class="feature"><div class="icon">📤</div><h3>Multi-format Hosting</h3><p>HTML, ZIP, ছবি, ভিডিও, PDF সব ধরনের ফাইল হোস্ট করুন।</p></div>
  <div class="feature"><div class="icon">🔗</div><h3>কাস্টম URL</h3><p>নিজের পছন্দমতো URL slug সেট করুন।</p></div>
  <div class="feature"><div class="icon">📊</div><h3>Analytics</h3><p>ভিজিটর, দেশ, ব্রাউজার ও দৈনিক ভিউ ট্র্যাক করুন।</p></div>
  <div class="feature"><div class="icon">🔒</div><h3>পাসওয়ার্ড প্রোটেকশন</h3><p>সাইটকে পাসওয়ার্ড দিয়ে সুরক্ষিত রাখুন।</p></div>
  <div class="feature"><div class="icon">📋</div><h3>টেমপ্লেট</h3><p>রেডিমেড Portfolio, Landing Page, Link Bio টেমপ্লেট।</p></div>
  <div class="feature"><div class="icon">🔗</div><h3>Short URL</h3><p>যেকোনো লিংক ছোট করুন এবং ট্র্যাক করুন।</p></div>
</div>
<footer>© 2024 HTML Hosting Bot | <a href="https://t.me/{username}" style="color:#5b5bd6">@{username}</a></footer>
</body>
</html>"""

# ================= USER PROFILE PAGE =================
@app.route('/u/<int:uid>')
def user_profile(uid):
    u = db_query("SELECT username, joined_date FROM users WHERE id=?", (uid,), fetchone=True)
    if not u:
        return custom_404("ইউজার পাওয়া যায়নি")
    files = db_query("SELECT short_code, name, type, views, custom_slug, tags, date FROM files WHERE user_id=? AND is_public=1 ORDER BY views DESC", (uid,), fetch=True) or []
    total_views = sum(f['views'] for f in files)
    username = u['username'] or f"User#{uid}"

    cards = ""
    for f in files:
        slug = f['custom_slug'] or f['short_code']
        url = f"/v/{slug}"
        tag = f" <span style='background:#2a2a4e;padding:2px 8px;border-radius:4px;font-size:11px'>#{f['tags']}</span>" if f['tags'] else ""
        type_icon = "📂" if f['type'] == 'zip' else "🖼" if f['type'] == 'media' else "📄"
        cards += f"""<div class="card"><a href="{url}" target="_blank">
          <div class="card-icon">{type_icon}</div>
          <div class="card-name">{f['name'][:30]}{tag}</div>
          <div class="card-views">👁 {f['views']} views</div>
        </a></div>"""

    return f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>@{username} - Profile</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif;padding:32px 16px}}
.profile{{text-align:center;margin-bottom:32px}}
.avatar{{width:80px;height:80px;border-radius:50%;background:#5b5bd6;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;font-size:36px}}
h1{{font-size:24px;margin-bottom:4px}}
.stats{{color:#888;font-size:14px;margin-bottom:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;max-width:900px;margin:0 auto}}
.card{{background:#1a1a2e;border-radius:10px;border:1px solid #2a2a4e;overflow:hidden}}
.card a{{display:block;padding:16px;text-decoration:none;color:#fff}}
.card:hover{{border-color:#5b5bd6}}
.card-icon{{font-size:28px;margin-bottom:8px}}
.card-name{{font-size:13px;margin-bottom:4px;word-break:break-all}}
.card-views{{color:#666;font-size:12px}}
</style>
</head>
<body>
<div class="profile">
  <div class="avatar">{'@'[0] if username else '👤'}</div>
  <h1>@{username}</h1>
  <p class="stats">📂 {len(files)} পাবলিক সাইট | 👁 {total_views} মোট Views | 📅 {u['joined_date'] or 'N/A'}</p>
</div>
<div class="grid">{cards or '<p style="text-align:center;color:#666">কোনো পাবলিক সাইট নেই।</p>'}</div>
</body>
</html>"""

# ================= SHORT URL REDIRECT =================
@app.route('/s/<code>')
def redirect_short(code):
    r = db_query("SELECT original_url FROM short_urls WHERE code=?", (code,), fetchone=True)
    if not r:
        return custom_404("Short URL পাওয়া যায়নি")
    db_query("UPDATE short_urls SET clicks=clicks+1 WHERE code=?", (code,))
    return redirect(r['original_url'], 302)

# ================= SITE SERVER =================
@app.route('/v/<slug>/auth', methods=['POST'])
def auth_site(slug):
    res = db_query("SELECT short_code, password FROM files WHERE custom_slug=? OR short_code=?",
                   (slug, slug), fetchone=True)
    if not res:
        return custom_404()
    pw_input = request.form.get('pw', '')
    if pw_input == res['password']:
        session[f'auth_{res["short_code"]}'] = True
        return redirect(f'/v/{slug}')
    return password_page(slug, error=True)

@app.route('/v/<slug>')
@app.route('/v/<slug>/<path:subpath>')
def serve_site(slug, subpath=""):
    ip = request.remote_addr
    ua = request.headers.get('User-Agent', '')

    res = db_query(
        "SELECT user_id, type, short_code, password, expiry, views, name FROM files WHERE custom_slug=? OR short_code=?",
        (slug, slug), fetchone=True
    )
    if not res:
        return custom_404()

    # Expiry check
    if res["expiry"] and datetime.fromisoformat(res["expiry"]) < datetime.now():
        db_query("DELETE FROM files WHERE short_code=?", (res["short_code"],))
        return custom_404("এই সাইটের মেয়াদ শেষ হয়ে গেছে")

    # Password check
    if res["password"]:
        if not session.get(f'auth_{res["short_code"]}'):
            return password_page(slug)

    folder = os.path.join(UPLOAD_DIR, str(res["user_id"]), res["short_code"])
    if not os.path.exists(folder):
        return custom_404()

    # Determine actual path
    if res["type"] == "html" or res["type"] == "media":
        actual_path = subpath if subpath else "index.html"
    else:
        actual_path = subpath if subpath else ""

    # Path traversal protection
    if actual_path:
        full_path = os.path.realpath(os.path.join(folder, actual_path))
        if not full_path.startswith(os.path.realpath(folder)):
            return custom_403()
    else:
        full_path = os.path.realpath(folder)

    # Directory handling
    if os.path.isdir(full_path):
        index_path = os.path.join(full_path, 'index.html')
        if os.path.exists(index_path):
            actual_path = (actual_path + '/index.html').lstrip('/')
            full_path = index_path
        else:
            # ZIP Auto-index
            try:
                listing = make_dir_listing_html(folder, slug, actual_path)
                return listing, 200
            except:
                return custom_404("এই ফোল্ডারে index.html নেই")
    elif not os.path.exists(full_path):
        # Try as index.html
        idx = os.path.join(full_path if not actual_path else os.path.join(folder, actual_path), 'index.html')
        if not os.path.exists(idx):
            return custom_404(f"ফাইলটি পাওয়া যায়নি")
        actual_path = (actual_path + '/index.html').lstrip('/')

    # View count
    country = request.headers.get("CF-IPCountry", "Unknown")
    db_query("UPDATE files SET views=views+1, last_view=? WHERE short_code=?",
             (datetime.now().strftime("%Y-%m-%d %H:%M"), res["short_code"]))
    db_query("INSERT INTO site_views(short_code,ip,country,viewed_at,user_agent) VALUES(?,?,?,?,?)",
             (res["short_code"], ip, country, datetime.now().strftime("%Y-%m-%d %H:%M"), ua[:200]))

    mime_type, _ = mimetypes.guess_type(actual_path or "index.html")
    response = make_response(send_from_directory(folder, actual_path or "index.html"))
    if mime_type:
        response.headers['Content-Type'] = mime_type
    return response

# ================= ADMIN WEB PANEL =================
@app.route('/admin')
def admin_web():
    auth = request.args.get('key', '')
    admin_key = db_query("SELECT value FROM settings WHERE key='admin_web_key'", fetchone=True)
    if not admin_key:
        key = secrets.token_hex(16)
        db_query("INSERT OR REPLACE INTO settings VALUES('admin_web_key',?)", (key,))
        return f"Admin key set. Use: /admin?key={key}", 200
    if auth != admin_key['value']:
        return "❌ Unauthorized. Use /admin?key=YOUR_KEY", 403

    total_users = db_query("SELECT COUNT(*) as c FROM users", fetchone=True)["c"] or 0
    total_sites = db_query("SELECT COUNT(*) as c FROM files", fetchone=True)["c"] or 0
    total_views = db_query("SELECT SUM(views) as c FROM files", fetchone=True)["c"] or 0
    premium_count = db_query("SELECT COUNT(*) as c FROM premium", fetchone=True)["c"] or 0
    storage = format_bytes(get_storage_used())
    pending_pay = db_query("SELECT COUNT(*) as c FROM payment_requests WHERE status='pending'", fetchone=True)["c"] or 0
    pending_rep = db_query("SELECT COUNT(*) as c FROM reports WHERE status='pending'", fetchone=True)["c"] or 0
    top_sites = db_query("SELECT name, views, short_code FROM files ORDER BY views DESC LIMIT 10", fetch=True) or []
    top_rows = "".join(f"<tr><td>{i+1}</td><td>{s['name'][:30]}</td><td>{s['views']}</td><td><a href='/v/{s['short_code']}' target='_blank'>🔗</a></td></tr>" for i, s in enumerate(top_sites))

    return f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>⚙️ Admin Panel</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;color:#fff;font-family:'Segoe UI',sans-serif;padding:24px}}
h1{{font-size:24px;margin-bottom:24px;color:#5b5bd6}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;margin-bottom:32px}}
.card{{background:#1a1a2e;border-radius:10px;padding:20px;border:1px solid #2a2a4e;text-align:center}}
.card .num{{font-size:32px;font-weight:bold;color:#5b5bd6}}
.card .label{{color:#888;font-size:13px;margin-top:4px}}
table{{width:100%;border-collapse:collapse;background:#1a1a2e;border-radius:10px;overflow:hidden}}
th,td{{padding:10px 14px;text-align:left;border-bottom:1px solid #2a2a4e;font-size:13px}}
th{{background:#111120;color:#888}}
a{{color:#7c7cff}}
</style>
</head>
<body>
<h1>⚙️ Admin Dashboard</h1>
<div class="cards">
  <div class="card"><div class="num">{total_users}</div><div class="label">👥 ইউজার</div></div>
  <div class="card"><div class="num">{total_sites}</div><div class="label">🌐 সাইট</div></div>
  <div class="card"><div class="num">{total_views}</div><div class="label">👁 Views</div></div>
  <div class="card"><div class="num">{premium_count}</div><div class="label">💎 Premium</div></div>
  <div class="card"><div class="num">{storage}</div><div class="label">💾 Storage</div></div>
  <div class="card"><div class="num">{pending_pay}</div><div class="label">💳 Payments</div></div>
  <div class="card"><div class="num">{pending_rep}</div><div class="label">🚨 Reports</div></div>
</div>
<h2 style="margin-bottom:12px;font-size:18px">🏆 Top Sites</h2>
<table>
<tr><th>#</th><th>নাম</th><th>Views</th><th>লিংক</th></tr>
{top_rows}
</table>
</body>
</html>"""

# ================= WEBHOOK =================
@app.route(f'/webhook/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return '', 200
    return 'Bad request', 400

@app.errorhandler(404)
def not_found(e): return custom_404()

@app.errorhandler(403)
def forbidden(e): return custom_403()

@app.errorhandler(429)
def too_many(e): return "⛔ Too many requests.", 429

# ================= BACKGROUND TASKS =================
def expiry_checker():
    while True:
        try:
            # Site expiry
            files = db_query("SELECT short_code, user_id, expiry FROM files WHERE expiry IS NOT NULL", fetch=True)
            for f in (files or []):
                if datetime.fromisoformat(f["expiry"]) < datetime.now():
                    db_query("DELETE FROM files WHERE short_code=?", (f["short_code"],))
                    db_query("DELETE FROM site_views WHERE short_code=?", (f["short_code"],))
                    try:
                        shutil.rmtree(os.path.join(UPLOAD_DIR, str(f["user_id"]), f["short_code"]))
                    except: pass

            # Premium expiry notification
            prems = db_query("SELECT user_id, expiry FROM premium", fetch=True)
            for p in (prems or []):
                exp = datetime.fromisoformat(p["expiry"])
                if timedelta(days=0) < (exp - datetime.now()) < timedelta(days=3):
                    try:
                        bot.send_message(p["user_id"], f"⚠️ আপনার Premium {(exp - datetime.now()).days + 1} দিন পরে শেষ হবে!")
                    except: pass
        except Exception as e:
            logger.error(f"Expiry checker: {e}")
        time.sleep(3600)

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

# ================= MAIN =================
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    Thread(target=expiry_checker, daemon=True).start()

    if USE_WEBHOOK and WEBHOOK_URL:
        # Webhook mode
        webhook_full_url = f"{WEBHOOK_URL}/webhook/{WEBHOOK_SECRET}"
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=webhook_full_url)
        logger.info(f"Webhook set: {webhook_full_url}")
        # Flask serves webhook, keep main thread alive
        import signal
        signal.pause()
    else:
        # Polling mode
        logger.info("Bot is polling...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
