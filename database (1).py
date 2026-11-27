# ==========================================
# ملف: database.py
# ==========================================
# ==========================================
# ملف قاعدة البيانات والسجلات
# ==========================================
import os
import json
import time
from datetime import datetime, date # تمت إضافة date للاحتياط
from config import bot_state, DB_FILE, lock

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                bot_state.update(loaded)
                for k in ("admin_log", "ban_tracker", "suggestions", "changelog", "scheduled_broadcasts"):
                    bot_state.setdefault(k, {} if k in ("ban_tracker", "suggestions") else [])
                for k, v in {"ban_threshold":10, "ban_window_min":60, "anti_spam_per_min":10,
                             "dynamic_pricing":False, "min_song_cost":3, "max_song_cost":20}.items():
                    bot_state.setdefault("settings", {}).setdefault(k, v)
        except Exception as e:
            print("load_db:", e)

_db_dirty = False

def save_db():
    global _db_dirty
    _db_dirty = True

def flush_db():
    global _db_dirty
    if not _db_dirty: return
    _db_dirty = False
    with lock:
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(bot_state, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, DB_FILE)

def db_flusher():
    while True:
        time.sleep(3)
        try: 
            flush_db()
        except Exception as e: 
            print("flush_db:", e)

# ============ سجل العمليات ============
LOG_GROUPS = {"requests": {"link", "music", "ai", "cmd", "draw", "account"},
              "downloads": {"download"},
              "ai": {"ai_explain"},
              "listen": {"listen"},
              "vision": {"vision"},
              "errors": {"error"}}

def log_event(kind, chat_id, text):
    uid = str(chat_id)
    with lock:
        u = bot_state["users"].get(uid, {})
        bot_state.setdefault("log", []).append({
            "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "uid": uid,
            "name": u.get("name", "مستخدم"), "username": u.get("username", ""),
            "kind": kind, "text": str(text)[:300]})
        del bot_state["log"][:-2000]
    save_db()

def count_download(chat_id, text):
    with lock:
        bot_state["stats"]["successful_downloads"] += 1
    log_event("download", chat_id, text)

# ============ سجل عمليات المشرفين ============
def audit(admin_uid, action, target="", details=""):
    with lock:
        bot_state.setdefault("admin_log", []).append({
            "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "by": str(admin_uid),
            "by_name": bot_state["users"].get(str(admin_uid), {}).get("name", "لوحة الإدارة" if str(admin_uid)=="panel" else "مشرف"),
            "action": str(action)[:40],
            "target": str(target)[:40],
            "details": str(details)[:200]
        })
        del bot_state["admin_log"][:-1000]
    save_db()

# ============ سجل النقاط ============
def log_points(uid, delta, old, new, by="system", note=""):
    with lock:
        bot_state.setdefault("point_log", []).append({
            "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "uid": str(uid), "delta": int(delta), "old": int(old), "new": int(new),
            "by": str(by)[:24], "note": str(note)[:100]
        })
        del bot_state["point_log"][:-2000]
    save_db()

# ============ النسخ الاحتياطي ============
def backup_loop():
    import shutil
    os.makedirs("backups", exist_ok=True)
    while True:
        try:
            time.sleep(6 * 3600)
            if os.path.exists(DB_FILE):
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dst = f"backups/bot_data_{stamp}.json"
                shutil.copy2(DB_FILE, dst)
                files = sorted([os.path.join("backups", f) for f in os.listdir("backups") if f.startswith("bot_data_")])
                for old in files[:-20]:
                    try: os.remove(old)
                    except Exception: pass
                print(f"💾 نسخة احتياطية: {dst}")
        except Exception as e:
            print("backup_loop:", e)

load_db()