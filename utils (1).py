# ==========================================
# ملف: utils.py
# ==========================================
# ==========================================
# ملف الأدوات المساعدة
# ==========================================
import os
import re
import time
import uuid
import html
import hmac
import socket
import ipaddress
import threading
from urllib.parse import urlparse
from flask import request

from config import ADMIN_PASSWORD, pending_files, bot_state, lock
from database import log_event

def esc(t):
    """تنظيف النصوص من رموز HTML"""
    return html.escape(str(t))

def safe_url(url):
    """التأكد من أن الرابط آمن ولا يشير إلى شبكة محلية (SSRF)"""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for i in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(i[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except Exception:
        return False

def safe_name(name, default):
    """إنشاء اسم ملف آمن"""
    name = os.path.basename(name or "")
    name = re.sub(r'[^\w.\- ]', '_', name).strip(". ")
    return name[:100] or default

def store_url(url):
    """حفظ رابط مؤقتاً في الذاكرة لاستخدامه في الأزرار (Inline)"""
    now = time.time()
    for k in [k for k, v in list(pending_files.items()) if now - v[1] > 1800]:
        pending_files.pop(k, None)
    fid = uuid.uuid4().hex[:10]
    pending_files[fid] = (url, now)
    return fid

def get_url(fid):
    """استرجاع رابط محفوظ"""
    v = pending_files.get(fid)
    return v[0] if v else None

def bg(fn, *args):
    """تشغيل دالة في الخلفية (Thread)"""
    threading.Thread(target=fn, args=args, daemon=True).start()

def check_admin():
    """التحقق من كلمة مرور المشرف (لواجهة الويب)"""
    d = request.get_json(silent=True) or {}
    ok = hmac.compare_digest(str(d.get('password', '')).encode(), ADMIN_PASSWORD.encode())
    return ok, d

def classify(text):
    """تصنيف نوع النص/الرسالة"""
    if text.startswith("http"): return "link"
    if text.startswith("يوت "): return "music"
    if text.startswith("/رسم "): return "draw"
    if text.startswith("/"): return "cmd"
    return "ai"

def resolve_path(p):
    """البحث عن مسار الملف الفعلي بعد التحميل (لأن الصيغة قد تتغير مثل .mp3)"""
    if p and os.path.exists(p): return p
    if p:
        base = os.path.splitext(p)[0]
        for ext in (".mp3", ".mp4", ".m4a", ".webm", ".mkv", ".opus"):
            if os.path.exists(base + ext): return base + ext
    return None

def bump_stat(name):
    """زيادة الإحصائيات"""
    with lock:
        bot_state["stats"][name] = int(bot_state["stats"].get(name, 0)) + 1

# ============ تمت إضافة الدالة الناقصة هنا ============
def count_download(chat_id, url_info=""):
    """تسجيل التحميلات الناجحة في الإحصائيات"""
    bump_stat("successful_downloads")
    log_event("download", chat_id, str(url_info)[:300])
# ========================================================

def log_listen(chat_id, title, url=""):
    """تسجيل استماع المستخدم"""
    bump_stat("listens")
    log_event("listen", chat_id, f"{str(title)[:150]} | {url}"[:300])

def log_error(chat_id, where, err, url=""):
    """تسجيل الأخطاء"""
    bump_stat("errors")
    log_event("error", chat_id, f"[{where}] {str(err).replace(chr(10), ' ')[:150]} | {url}"[:300])

def explain_error(e):
    """ترجمة أخطاء yt-dlp والمواقع إلى رسائل مفهومة للمستخدم"""
    s = str(e).lower()
    rules = [
        (("sign in to confirm", "not a bot"), "🔐 المنصة تطلب إثبات أنك لست روبوتاً. المدير يحلّها بإضافة كوكيز من لوحة الإدارة."),
        (("private video", "this video is private"), "🔒 الفيديو خاص."),
        (("login required", "log in", "empty media response", "requires authentication"), "🔐 المحتوى يحتاج تسجيل دخول (فيسبوك/إنستجرام غالباً). الحل: كوكيز من لوحة الإدارة."),
        (("confirm your age", "age-restricted", "age restricted"), "🔞 الفيديو مقيّد بالعمر."),
        (("unsupported url",), "🔗 الرابط غير مدعوم كفيديو."),
        (("requested format is not available",), "🎞️ هذه الجودة غير متوفرة. جرّب جودة أخرى أو «صوت فقط»."),
        (("50mb", "larger than"), "⚠️ الملف أكبر من 50 ميجابايت حتى بأقل جودة. جرّب «صوت فقط»."),
        (("http error 403", "forbidden"), "🚫 الموقع رفض الاتصال (403). حدّث yt-dlp من اللوحة أو أضف كوكيز."),
        (("http error 429", "too many requests"), "⏳ الموقع حدّد الطلبات مؤقتاً. حاول بعد قليل."),
        (("video unavailable", "has been removed", "not available", "does not exist"), "❓ الفيديو غير متاح أو محذوف."),
        (("geo", "your country"), "🌍 المحتوى محجوب في بلد السيرفر."),
        (("unable to extract", "extractor error"), "🛠️ تعذّر الاستخراج — غالباً yt-dlp قديم. المدير يحدّثه من اللوحة."),
        (("ffmpeg",), "🎬 هذه العملية تحتاج ffmpeg وهو غير مثبت."),
        (("timed out", "timeout"), "⌛ انتهت مهلة الاتصال، حاول مجدداً."),
    ]
    for keys, msg in rules:
        if any(k in s for k in keys): return msg
    return "❌ تعذّر التنفيذ."