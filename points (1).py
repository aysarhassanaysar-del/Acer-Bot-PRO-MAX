# ==========================================
# ملف: points.py
# ==========================================
# ==========================================
# ملف نظام النقاط والمكافآت
# ==========================================
import time
from config import bot_state, lock
from database import save_db, log_points
from telegram_api import send_message
from utils import esc

POINTS_DEFAULTS = {"start_points": 10, "daily_bonus": 5, "song_cost": 5}

def setting(name):
    try: return int(bot_state.get("settings", {}).get(name, POINTS_DEFAULTS[name]))
    except Exception: return POINTS_DEFAULTS[name]

def get_points(uid):
    try: return int(bot_state["users"].get(str(uid), {}).get("points", 0))
    except Exception: return 0

def charge(uid, cost, note="أغنية عشوائية", by="song"):
    with lock:
        u = bot_state["users"].get(str(uid))
        if not u or int(u.get("points", 0)) < cost: return False
        old = int(u.get("points", 0))
        u["points"] = old - cost
    save_db()
    try: log_points(uid, -cost, old, old - cost, by=by, note=note)
    except Exception: pass
    return True

def refund(uid, cost, note="استرجاع أغنية فاشلة"):
    with lock:
        u = bot_state["users"].get(str(uid))
        if u:
            old = int(u.get("points", 0))
            u["points"] = old + cost
    save_db()
    try: log_points(uid, cost, old, old + cost, by="refund", note=note)
    except Exception: pass

def apply_points(uid, mode, amount, by="system", note=""):
    with lock:
        u = bot_state["users"][uid]
        old = int(u.get("points", 0))
        new = max(0, old + amount) if mode == "add" else max(0, amount)
        u["points"] = new
    if new != old:
        log_points(uid, new - old, old, new, by, note)
    return old, new

def points_bar(n):
    f = min(10, n // 10)
    return "🟡" * f + "⚪" * (10 - f)

def points_msg(old, new, note=""):
    d = new - old
    if d > 0:
        head = "🎁✨🎉🎊 <b>هدية من الإدارة!</b> 🎊🎉✨🎁"
        line = f"🌟 أُضيف إلى رصيدك: <b>+{d}</b> نقطة 💰"
        tail = "🎊 استمتع بنقاطك واستخدمها في 🎲 الأغنية العشوائية! 🎶\n🌟 وتذكّر: مكافأة يومية جديدة بانتظارك!"
    else:
        head = "⚠️💸🎈 <b>تعديل على رصيدك</b> 🎈💸⚠️"
        line = f"📉 تم خصم: <b>{-d}</b> نقطة"
        tail = "💡 تحصل على نقاط جديدة كل يوم عند استخدام البوت 🌟"
    txt = (f"{head}\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"{line}\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"💎 رصيدك السابق: <b>{old}</b>\n"
           f"💰 <b>رصيدك الآن: {new}</b> نقطة\n"
           f"{points_bar(new)}\n"
           f"━━━━━━━━━━━━━━━━━━━━\n")
    if note:
        txt += f"📝 <i>{esc(note)}</i>\n\n"
    return txt + tail

def welcome_bonus_msg(points, start, daily):
    return (f"🎉🎊✨ <b>أهلاً بك في البوت الشامل!</b> ✨🎊🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎁 <b>هدية الترحيب:</b> <b>+{start}</b> نقطة\n"
            f"📆 <b>مكافأة اليوم الأول:</b> <b>+{daily}</b> نقطة\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>رصيدك الآن: {points}</b> نقطة\n"
            f"{points_bar(points)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎲 استخدم نقاطك في <b>الأغنية العشوائية</b>! 🎶\n"
            f"🌟 مكافأة يومية <b>+{daily}</b> تصلك في أول رسالة كل يوم جديد.\n"
            f"🎊 استمتع بكل ميزات البوت! ✨")

def daily_bonus_msg(points, daily, old):
    return (f"🌅✨🎁 <b>مكافأتك اليومية وصلت!</b> 🎁✨🌅\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌟 أُضيف إلى رصيدك: <b>+{daily}</b> نقطة 💰\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 رصيدك السابق: <b>{old}</b>\n"
            f"💰 <b>رصيدك الآن: {points}</b> نقطة\n"
            f"{points_bar(points)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎊 عُد غداً لمكافأة جديدة!\n"
            f"🎲 استمتع بأغنية عشوائية من نقاطك! 🎶")

def notify_points(changes, note=""):
    for uid, old, new in changes:
        if new == old or uid in bot_state["banned_users"]: continue
        send_message(uid, points_msg(old, new, note))
        time.sleep(0.06)

def points_card(chat_id):
    p = get_points(chat_id)
    return (f"💰✨ <b>رصيدك</b> ✨💰\n\n💎 <b>{p}</b> نقطة\n{points_bar(p)}\n━━━━━━━━━━━━\n"
            f"🎁 مكافأة يومية: <b>+{setting('daily_bonus')}</b>\n"
            f"🎲 أغنية عشوائية: <b>{setting('song_cost')}</b> نقاط\n\n<i>استخدم البوت يومياً لتجمع المزيد 🌟</i>")
