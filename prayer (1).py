# ==========================================
# ملف: prayer.py
# ==========================================
# ==========================================
# ملف مواقيت الصلاة، المناسبات، والتذكيرات
# ==========================================
import time
import json
import re
import uuid
import requests
from datetime import datetime, date, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from config import bot_state, lock, PRAYERS, PRAYER_METHODS, HIJRI_EVENTS, WEEKDAYS, UA
from database import save_db
from telegram_api import send_message
from utils import esc

# متغيرات محلية للمواقيت
pt_cache = {}
pt_retry = {}
adhan_sent = set()
occ_cache = {"day": "", "hijri": None, "items": []}

# ============ مواقيت الصلاة ============
def tz_of(name):
    try:
        return ZoneInfo(name) if (ZoneInfo and name) else None
    except Exception:
        return None

def get_prayer(uid, force=False):
    uid = str(uid)
    u = bot_state["users"].get(uid)
    if not u or not u.get("loc"): return None
    pc = pt_cache.get(uid)
    if pc and not force and time.time() - pc["at"] < 6 * 3600:
        tz = tz_of(pc["tz"])
        if not tz or datetime.now(tz).strftime("%Y-%m-%d") == pc["day"]:
            return pc
    if pt_retry.get(uid, 0) > time.time():
        raise RuntimeError("retry later")
    loc = u["loc"]
    try:
        r = requests.get(f"https://api.aladhan.com/v1/timings/{int(time.time())}",
                         params={"latitude": loc["lat"], "longitude": loc["lon"], "method": u.get("method", "3")}, timeout=15)
        j = r.json()["data"]
        tzname = j["meta"]["timezone"]
    except Exception:
        pt_retry[uid] = time.time() + 300
        raise
    tz = tz_of(tzname)
    day = datetime.now(tz).strftime("%Y-%m-%d") if tz else time.strftime("%Y-%m-%d")
    pc = {"at": time.time(), "t": j["timings"], "tz": tzname, "day": day,
          "hijri": j["date"]["hijri"], "greg": j["date"]["readable"]}
    pt_cache[uid] = pc
    with lock: u["tz"] = tzname
    return pc

def fmt_delta(td):
    m = int(td.total_seconds() // 60)
    h, m = divmod(m, 60)
    return (f"{h} س " if h else "") + f"{m} د"

def next_prayer(pc):
    tz = tz_of(pc["tz"])
    if not tz: return None
    now = datetime.now(tz)
    for key, ar, ic in PRAYERS:
        if key == "Sunrise": continue
        hh, mm = [int(x) for x in pc["t"][key][:5].split(":")]
        dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dt > now: return ar, ic, dt - now
    hh, mm = [int(x) for x in pc["t"]["Fajr"][:5].split(":")]
    dt = (now + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return "الفجر", "🌙", dt - now

def prayer_text(pc, u):
    t, h = pc["t"], pc["hijri"]
    lines = ["🕌✨ <b>مواقيت الصلاة</b> ✨🕌", f"📍 {esc(u['loc']['label'])}",
             f"📅 {esc(h['weekday']['ar'])} {esc(h['day'])} {esc(h['month']['ar'])} {esc(h['year'])}هـ — {esc(pc['greg'])}",
             "━━━━━━━━━━━━"]
    for key, ar, ic in PRAYERS:
        lines.append(f"{ic} {ar} — <b>{esc(t[key][:5])}</b>")
    lines.append("━━━━━━━━━━━━")
    nx = next_prayer(pc)
    if nx: lines.append(f"⏭️ القادمة: <b>{nx[0]}</b> {nx[1]} بعد <b>{fmt_delta(nx[2])}</b>")
    lines.append(f"🧮 الطريقة: {PRAYER_METHODS.get(u.get('method', '3'), '')}")
    return "\n".join(lines)

def ask_location(chat_id):
    kb = {"keyboard": [[{"text": "📍 مشاركة موقعي", "request_location": True}]], "resize_keyboard": True, "one_time_keyboard": True}
    send_message(chat_id, "📍 <b>حدّد موقعك لحساب المواقيت</b>\n\n1️⃣ اضغط «مشاركة موقعي» بالأسفل\n"
                          "2️⃣ أو اكتب: <code>/مدينتي بغداد، العراق</code>\n\n"
                          "🔒 نحفظ إحداثيات تقريبية فقط، ويمكنك حذفها بالأمر /حذف_موقعي", reply_markup=json.dumps(kb))

def save_loc(chat_id, lat, lon, label):
    with lock:
        u = bot_state["users"].get(str(chat_id))
        if not u: return False
        u["loc"] = {"lat": round(float(lat), 2), "lon": round(float(lon), 2), "label": str(label)[:80]}
    pt_cache.pop(str(chat_id), None)
    pt_retry.pop(str(chat_id), None)
    save_db()
    return True

def set_location_gps(chat_id, lat, lon):
    try:
        lat, lon = float(lat), float(lon)
        assert -90 <= lat <= 90 and -180 <= lon <= 180
    except Exception:
        send_message(chat_id, "⚠️ موقع غير صالح."); return
    if save_loc(chat_id, lat, lon, "موقعك المشارَك 📍"):
        send_message(chat_id, "✅ تم حفظ موقعك.", reply_markup=json.dumps({"remove_keyboard": True}))
        show_prayer(chat_id)

def set_city(chat_id, query):
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": query[:100], "format": "json", "limit": 1, "accept-language": "ar"}, headers=UA, timeout=15)
        j = r.json()
        if not j:
            send_message(chat_id, "❌ لم أجد هذا المكان. جرّب: <code>/مدينتي بغداد، العراق</code>"); return
        label = (j[0].get("display_name") or query).split(",")
        label = "، ".join(x.strip() for x in label[:2] + label[-1:])
        if save_loc(chat_id, j[0]["lat"], j[0]["lon"], label):
            send_message(chat_id, f"✅ تم تحديد الموقع: <b>{esc(label)}</b>", reply_markup=json.dumps({"remove_keyboard": True}))
            show_prayer(chat_id)
    except Exception as e:
        send_message(chat_id, f"❌ تعذّر تحديد المدينة: <code>{esc(str(e)[:80])}</code>")

def show_prayer(chat_id):
    u = bot_state["users"].get(str(chat_id))
    if not u or not u.get("loc"):
        ask_location(chat_id); return
    try:
        pc = get_prayer(chat_id)
    except Exception as e:
        send_message(chat_id, f"❌ تعذّر جلب المواقيت حالياً، حاول بعد قليل.\n<code>{esc(str(e)[:80])}</code>"); return
    adhan = bool(u.get("adhan"))
    kb = {"inline_keyboard": [[{"text": "🔔 تذكير الأذان: " + ("مفعّل ✅" if adhan else "متوقف ❌"), "callback_data": "pr_adhan"}],
                              [{"text": "📍 تغيير الموقع", "callback_data": "pr_loc"}, {"text": "🧮 طريقة الحساب", "callback_data": "pr_method"}]]}
    send_message(chat_id, prayer_text(pc, u), reply_markup=json.dumps(kb))

def toggle_adhan(chat_id):
    u = bot_state["users"].get(str(chat_id))
    if not u or not u.get("loc"):
        ask_location(chat_id); return
    with lock: u["adhan"] = not u.get("adhan", False)
    save_db()
    if u["adhan"]:
        try:
            pc = get_prayer(chat_id)
            if not tz_of(pc["tz"]):
                send_message(chat_id, "⚠️ جهاز البوت لا يملك قاعدة المناطق الزمنية، فلن تصل التذكيرات.\nعلى المدير تنفيذ: <code>pip install tzdata</code>")
        except Exception: pass
    show_prayer(chat_id)

def show_methods(chat_id):
    rows = [[{"text": name, "callback_data": f"pm|{k}"}] for k, name in PRAYER_METHODS.items()]
    send_message(chat_id, "🧮 <b>اختر طريقة حساب المواقيت:</b>", reply_markup=json.dumps({"inline_keyboard": rows}))

def set_method(chat_id, k):
    u = bot_state["users"].get(str(chat_id))
    if not u or k not in PRAYER_METHODS: return
    with lock: u["method"] = k
    pt_cache.pop(str(chat_id), None)
    save_db()
    show_prayer(chat_id)

# ============ المناسبات ============
def get_occasions():
    today = date.today()
    if occ_cache["day"] == today.isoformat() and occ_cache["items"]:
        return occ_cache
    hj = requests.get(f"https://api.aladhan.com/v1/gToH/{today.strftime('%d-%m-%Y')}", timeout=15).json()["data"]["hijri"]
    hy = int(hj["year"])
    items = []
    for name, d, mo in HIJRI_EVENTS:
        for y in (hy, hy + 1):
            try:
                g = requests.get(f"https://api.aladhan.com/v1/hToG/{d:02d}-{mo:02d}-{y}", timeout=15).json()["data"]["gregorian"]["date"]
                gd = datetime.strptime(g, "%d-%m-%Y").date()
            except Exception:
                continue
            if gd >= today:
                items.append((name, gd)); break
    items.sort(key=lambda x: x[1])
    occ_cache.update(day=today.isoformat(), hijri=hj, items=items)
    return occ_cache

def show_occasions(chat_id):
    try:
        oc = get_occasions()
    except Exception as e:
        send_message(chat_id, f"❌ تعذّر جلب المناسبات حالياً.\n<code>{esc(str(e)[:80])}</code>"); return
    hj, today = oc["hijri"], date.today()
    lines = ["📅✨ <b>المواعيد والمناسبات</b> ✨📅",
             f"🗓️ اليوم: <b>{esc(hj['weekday']['ar'])} {esc(hj['day'])} {esc(hj['month']['ar'])} {esc(hj['year'])}هـ</b>",
             f"📆 الميلادي: {today.strftime('%Y-%m-%d')}", "━━━━━━━━━━━━"]
    for name, gd in oc["items"][:7]:
        n = (gd - today).days
        left = "اليوم 🎉" if n == 0 else ("غداً" if n == 1 else f"بعد {n} يوم")
        lines.append(f"🌙 <b>{esc(name)}</b>\n     📌 {WEEKDAYS[gd.weekday()]} {gd.strftime('%Y-%m-%d')} — {left}")
    lines.append("━━━━━━━━━━━━\n<i>قد يختلف التاريخ يوماً حسب رؤية الهلال.</i>")
    mine = len([r for r in bot_state["reminders"] if r["uid"] == str(chat_id)])
    kb = {"inline_keyboard": [[{"text": "➕ كيف أضيف تذكيراً؟", "callback_data": "rem_help"}, {"text": f"📋 تذكيراتي ({mine})", "callback_data": "rem_list"}]]}
    send_message(chat_id, "\n".join(lines), reply_markup=json.dumps(kb))

# ============ التذكيرات ============
REM_HELP = ("⏰✨ <b>التذكيرات الشخصية</b> ✨⏰\n\n"
            "⏱️ بعد مدة:\n<code>/ذكرني بعد 30 دقيقة اشرب ماء</code>\n"
            "<code>/ذكرني بعد 2 ساعة موعد الطبيب</code>\n\n"
            "📆 في تاريخ محدد:\n<code>/ذكرني 2026-12-01 18:30 عيد ميلاد أحمد</code>\n\n"
            "📋 /تذكيراتي — عرض وإلغاء تذكيراتك")

def add_reminder(chat_id, rest):
    uid = str(chat_id)
    tz = tz_of((bot_state["users"].get(uid) or {}).get("tz"))
    if len([r for r in bot_state["reminders"] if r["uid"] == uid]) >= 20:
        send_message(chat_id, "⚠️ وصلت للحد الأقصى (20 تذكيراً). ألغِ بعضها أولاً."); return
    due = text = None
    m = re.match(r'^\s*بعد\s+(\d+)\s*(دقيقة|دقائق|دقيقه|ساعة|ساعات|ساعه|يوم|ايام|أيام)\s+(.+)$', rest, re.S)
    if m:
        n, unit, text = int(m.group(1)), m.group(2), m.group(3)
        secs = 60 if unit.startswith("دقيق") or unit == "دقائق" else (3600 if unit.startswith("ساع") else 86400)
        due = time.time() + n * secs
    else:
        m = re.match(r'^\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s+(.+)$', rest, re.S)
        if m:
            try:
                dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
                due = dt.replace(tzinfo=tz).timestamp() if tz else dt.timestamp()
                text = m.group(3)
            except Exception:
                pass
    if not due or not text:
        send_message(chat_id, "⚠️ صيغة غير صحيحة.\n\n" + REM_HELP); return
    if due < time.time() + 20 or due > time.time() + 400 * 86400:
        send_message(chat_id, "⚠️ الوقت يجب أن يكون في المستقبل (وخلال سنة)."); return
    with lock:
        bot_state["reminders"].append({"id": uuid.uuid4().hex[:6], "uid": uid, "due": due, "text": text.strip()[:200]})
    save_db()
    shown = datetime.fromtimestamp(due, tz) if tz else datetime.fromtimestamp(due)
    send_message(chat_id, f"✅⏰ <b>تم ضبط التذكير!</b>\n\n📝 {esc(text.strip()[:200])}\n🕒 {shown.strftime('%Y-%m-%d %H:%M')}")

def list_reminders(chat_id):
    uid = str(chat_id)
    tz = tz_of((bot_state["users"].get(uid) or {}).get("tz"))
    mine = sorted([r for r in bot_state["reminders"] if r["uid"] == uid], key=lambda r: r["due"])
    if not mine:
        send_message(chat_id, "📋 لا توجد تذكيرات.\n\n" + REM_HELP); return
    lines, rows = ["📋⏰ <b>تذكيراتك:</b>\n"], []
    for i, r in enumerate(mine, 1):
        shown = datetime.fromtimestamp(r["due"], tz) if tz else datetime.fromtimestamp(r["due"])
        lines.append(f"{i}. 🕒 {shown.strftime('%Y-%m-%d %H:%M')}\n    📝 {esc(r['text'][:60])}")
        rows.append([{"text": f"❌ إلغاء #{i}", "callback_data": f"rc|{r['id']}"}])
    send_message(chat_id, "\n".join(lines), reply_markup=json.dumps({"inline_keyboard": rows[:10]}))

def cancel_reminder(chat_id, rid):
    with lock:
        before = len(bot_state["reminders"])
        bot_state["reminders"] = [r for r in bot_state["reminders"] if not (r["id"] == rid and r["uid"] == str(chat_id))]
        removed = before - len(bot_state["reminders"])
    save_db()
    send_message(chat_id, "🗑️ تم إلغاء التذكير." if removed else "⚠️ التذكير غير موجود.")
