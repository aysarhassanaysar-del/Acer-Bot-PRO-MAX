# ==========================================
# ملف واجهة تلغرام (API) والاتصال (الأصلي)
# ==========================================
import time
import requests
from requests.adapters import HTTPAdapter
import config
from config import TELEGRAM_TOKEN, photo_cache

# جلسة مشتركة مع تلغرام
TG_SESSION = requests.Session()
TG_SESSION.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=32, max_retries=1))

def fetch_bot_username():
    try:
        r = TG_SESSION.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=10)
        config.BOT_USERNAME = r.json()["result"]["username"]
    except Exception as e:
        print("fetch_bot_username:", e)

def send_message(chat_id, text, reply_markup=None):
    """دالة إرسال الرسائل الأصلية الخاصة بك"""
    payload = {"chat_id": chat_id, "text": str(text)[:4000], "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        r = TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print("send_message:", e); return False

def fetch_photo_url(uid, force=False):
    """جلب صورة المستخدم الأصلي"""
    uid = str(uid)
    now = time.time()
    c = photo_cache.get(uid)
    if c and not force and c[1] > now: return c[0]
    try:
        r = TG_SESSION.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUserProfilePhotos",
                         params={"user_id": uid, "limit": 1}, timeout=8)
        j = r.json()
        if not j.get("ok"):
            photo_cache[uid] = (None, now + 300); return None
        photos = j.get("result", {}).get("photos", [])
        if not photos:
            photo_cache[uid] = (None, now + 3600); return None
        sizes = photos[0]
        file_id = sizes[min(1, len(sizes) - 1)]["file_id"]
        r2 = TG_SESSION.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile", params={"file_id": file_id}, timeout=8)
        j2 = r2.json()
        if not j2.get("ok"):
            photo_cache[uid] = (None, now + 300); return None
        path = j2["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{path}"
        photo_cache[uid] = (url, now + 1800); return url
    except Exception as e:
        print("fetch_photo_url:", e); photo_cache[uid] = (None, now + 120); return None

def upload_media(chat_id, file_path, is_audio=False, caption=""):
    """رفع ملفات الميديا الأصلية"""
    method = "sendAudio" if is_audio else "sendVideo"
    key = 'audio' if is_audio else 'video'
    try:
        with open(file_path, 'rb') as f:
            res = TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
                                data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML', **({} if is_audio else {'supports_streaming': 'true'})}, files={key: f}, timeout=300)
        if res.status_code == 200: return True
        with open(file_path, 'rb') as f:
            res = TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                                data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}, files={'document': f}, timeout=300)
        return res.status_code == 200
    except Exception as e: print("upload_media:", e); return False

def tg_download_file(file_id, max_bytes=8 * 1024 * 1024):
    """تحميل ملف من سيرفرات تلغرام"""
    r = TG_SESSION.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile", params={"file_id": file_id}, timeout=15).json()
    if not r.get("ok"): raise ValueError("لم يتم العثور على الملف في تلغرام")
    info = r["result"]
    if info.get("file_size", 0) > max_bytes: raise ValueError("الملف كبير جداً")
    data = TG_SESSION.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{info['file_path']}", timeout=40).content
    return data, info["file_path"]