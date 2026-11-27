# ==========================================
# ملف: tools.py
# ==========================================
# ==========================================
# ملف الأدوات المتنوعة (طقس، حاسبة، إلخ)
# ==========================================
import ast
import operator
import secrets
import random
import re
import requests

from config import bot_state, UA, TELEGRAM_TOKEN
from telegram_api import send_message, TG_SESSION
from utils import esc, log_error

# ============ الحاسبة الآمنة ============
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}

def safe_eval(expr):
    expr = expr.strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    if len(expr) > 100: raise ValueError("طويل")
    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool): return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and (abs(b) > 100 or abs(a) > 1e6): raise ValueError("كبير")
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS: return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("تعبير غير مسموح")
    return ev(ast.parse(expr, mode="eval"))

# ============ الطقس ============
WEATHER_CODES = {0: ("☀️", "صافٍ"), 1: ("🌤️", "صافٍ غالباً"), 2: ("⛅", "غائم جزئياً"), 3: ("☁️", "غائم"), 45: ("🌫️", "ضباب"), 48: ("🌫️", "ضباب"),
                 51: ("🌦️", "رذاذ"), 53: ("🌦️", "رذاذ"), 55: ("🌦️", "رذاذ كثيف"), 61: ("🌧️", "مطر خفيف"), 63: ("🌧️", "مطر"), 65: ("🌧️", "مطر غزير"),
                 71: ("🌨️", "ثلج خفيف"), 73: ("🌨️", "ثلج"), 75: ("❄️", "ثلج كثيف"), 80: ("🌦️", "زخات"), 81: ("🌧️", "زخات"), 82: ("⛈️", "زخات قوية"),
                 95: ("⛈️", "عاصفة رعدية"), 96: ("⛈️", "عاصفة وبَرَد"), 99: ("⛈️", "عاصفة وبَرَد")}

def cmd_weather(chat_id, place):
    try:
        lat = lon = None; label = ""
        if place:
            r = requests.get("https://nominatim.openstreetmap.org/search", params={"q": place[:100], "format": "json", "limit": 1, "accept-language": "ar"}, headers=UA, timeout=15).json()
            if not r:
                send_message(chat_id, "❌ لم أجد هذا المكان."); return
            lat, lon = float(r[0]["lat"]), float(r[0]["lon"]); label = ", ".join(x.strip() for x in r[0].get("display_name", place).split(",")[:2])
        else:
            loc = (bot_state["users"].get(str(chat_id)) or {}).get("loc")
            if not loc:
                send_message(chat_id, "🌦️ اكتب: <code>/طقس بغداد</code> أو حدّد موقعك بـ /مدينتي"); return
            lat, lon, label = loc["lat"], loc["lon"], loc.get("label", "موقعك")
        j = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}, timeout=15).json()
        c = j["current"]; ic, ds = WEATHER_CODES.get(c["weather_code"], ("🌡️", ""))
        lines = [f"{ic} <b>الطقس — {esc(label)}</b>", f"🌡️ الآن: <b>{c['temperature_2m']}°</b> (تُحسّ {c['apparent_temperature']}°) — {ds}",
                 f"💧 الرطوبة: {c['relative_humidity_2m']}% | 💨 الرياح: {c['wind_speed_10m']} كم/س", "━━━━━━━━━━━━"]
        d = j["daily"]
        for i in range(len(d["time"])):
            di, dn = WEATHER_CODES.get(d["weather_code"][i], ("🌡️", ""))
            lines.append(f"{di} {d['time'][i]}: {d['temperature_2m_min'][i]}° ← {d['temperature_2m_max'][i]}° — {dn} (☔ {d['precipitation_probability_max'][i]}%)")
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        log_error(chat_id, "weather", e)
        send_message(chat_id, "❌ تعذّر جلب الطقس حالياً.")

# ============ تحويل العملات ============
def cmd_currency(chat_id, rest):
    m = re.match(r'^\s*([\d.,]+)\s*([A-Za-z]{3})\s*(?:الى|إلى|to|->|=)?\s*([A-Za-z]{3})\s*$', rest)
    if not m:
        send_message(chat_id, "💱 الاستخدام: <code>/تحويل 100 USD IQD</code>"); return
    try:
        amt = float(m.group(1).replace(",", "")); a, b = m.group(2).upper(), m.group(3).upper()
        rates = requests.get(f"https://open.er-api.com/v6/latest/{a}", timeout=15).json()["rates"]
        if b not in rates:
            send_message(chat_id, "❌ عملة غير معروفة."); return
        send_message(chat_id, f"💱 <b>{amt:,.2f} {a}</b> = <b>{amt * rates[b]:,.2f} {b}</b>\n<i>سعر الصرف: 1 {a} = {rates[b]:,.4f} {b}</i>")
    except Exception as e:
        log_error(chat_id, "currency", e)
        send_message(chat_id, "❌ تعذّر جلب الأسعار حالياً.")

# ============ رمز QR ============
def cmd_qr(chat_id, data):
    if not data:
        send_message(chat_id, "🔳 الاستخدام: <code>/qr النص أو الرابط</code>"); return
    try:
        TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", json={
            "chat_id": chat_id, "caption": "🔳 رمز QR الخاص بك",
            "photo": "https://api.qrserver.com/v1/create-qr-code/?size=500x500&data=" + requests.utils.quote(data[:500])}, timeout=30)
    except Exception:
        send_message(chat_id, "❌ تعذّر إنشاء الرمز.")

# ============ الحاسبة ============
def cmd_calc(chat_id, expr):
    if not expr:
        send_message(chat_id, "🧮 الاستخدام: <code>/احسب 12*(3+4)</code>"); return
    try:
        v = safe_eval(expr)
        send_message(chat_id, f"🧮 <code>{esc(expr[:100])}</code>\n= <b>{v:,.10g}</b>")
    except ZeroDivisionError:
        send_message(chat_id, "🚫 لا يمكن القسمة على صفر.")
    except Exception:
        send_message(chat_id, "⚠️ تعبير غير صالح. المسموح: + - * / % ^ وأقواس.")

# ============ كلمة سر عشوائية ============
def cmd_password(chat_id, arg):
    n = int(arg) if arg.strip().isdigit() else 16
    n = max(8, min(64, n))
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*?"
    pw = "".join(secrets.choice(alphabet) for _ in range(n))
    send_message(chat_id, f"🔑 كلمة سر قوية ({n}):\n<code>{esc(pw)}</code>\n<i>انسخها واحفظها؛ لا يحتفظ البوت بها.</i>")

# ============ رقم عشوائي ============
def cmd_random(chat_id, arg):
    nums = re.findall(r'-?\d+', arg)
    lo, hi = (int(nums[0]), int(nums[1])) if len(nums) >= 2 else (1, int(nums[0]) if nums else 100)
    if lo > hi: lo, hi = hi, lo
    send_message(chat_id, f"🎯 الرقم العشوائي بين {lo} و{hi}: <b>{random.randint(lo, hi)}</b>")

# ============ القرعة ============
def cmd_pick(chat_id, arg):
    opts = [x.strip() for x in re.split(r'[,،|\n]', arg) if x.strip()]
    if len(opts) < 2:
        send_message(chat_id, "🎰 الاستخدام: <code>/قرعة أحمد، علي، سارة</code>"); return
    send_message(chat_id, f"🎰 القرعة اختارت: <b>{esc(random.choice(opts)[:100])}</b> 🎉")

# ============ النرد ============
def cmd_dice(chat_id, arg):
    try: TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDice", json={"chat_id": chat_id, "emoji": "🎲"}, timeout=10)
    except Exception: pass
