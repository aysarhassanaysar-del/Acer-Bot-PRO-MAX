# ==========================================
# ملف: scheduler.py
# ==========================================
# ==========================================
# ملف المجدول التلقائي (التذكيرات، الأذان، الإذاعة)
# ==========================================
import time
from datetime import datetime
from config import bot_state, lock, PRAYERS
from database import save_db
from telegram_api import send_message
from utils import esc
from prayer import get_prayer, tz_of, adhan_sent
from admin import process_scheduled_broadcasts, update_dynamic_pricing

def scheduler_loop():
    while True:
        try:
            now_ts = time.time()
            
            # 1. التذكيرات
            with lock:
                due = [r for r in bot_state["reminders"] if r["due"] <= now_ts]
                if due:
                    bot_state["reminders"] = [r for r in bot_state["reminders"] if r["due"] > now_ts]
            for r in due:
                send_message(r["uid"], f"⏰✨ <b>تذكير!</b> ✨⏰\n\n📝 {esc(r['text'])}")
            if due: 
                save_db()

            # 2. الإذاعات المجدولة
            process_scheduled_broadcasts()
            
            # 3. التسعير الديناميكي (مرة كل ساعة)
            update_dynamic_pricing()

            # 4. تنبيهات الأذان
            for uid, u in list(bot_state["users"].items()):
                if not (u.get("adhan") and u.get("loc")) or uid in bot_state["banned_users"]: 
                    continue
                try:
                    pc = get_prayer(uid)
                    tz = tz_of(pc["tz"]) if pc else None
                    if not tz: continue
                    now = datetime.now(tz)
                    hm = now.strftime("%H:%M")
                    for key, ar, ic in PRAYERS:
                        if key == "Sunrise": continue
                        mark = (uid, str(now.date()), key)
                        if pc["t"][key][:5] == hm and mark not in adhan_sent:
                            adhan_sent.add(mark)
                            send_message(uid, f"🕌🔔 <b>حان الآن موعد أذان {ar}</b> 🔔🕌\n\n📍 {esc(u['loc']['label'])}\n⏰ {hm}\n\n<i>حيّ على الصلاة</i> 🤲")
                except Exception as e:
                    print("adhan:", uid, e)
                    
            if len(adhan_sent) > 5000: 
                adhan_sent.clear()
                
        except Exception as e:
            print("scheduler:", e)
            
        # الانتظار 20 ثانية قبل الفحص التالي لتخفيف الحمل على السيرفر
        time.sleep(20)
