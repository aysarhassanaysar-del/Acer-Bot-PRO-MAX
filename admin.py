# ==========================================
# ملف لوحة الإدارة، كلمة السر I love Acer، وإدارة الملفات والمفاتيح
# ==========================================
import os
import re
import json
import time
import uuid
import shutil
import subprocess
import sys
import atexit
from datetime import datetime, timedelta
from collections import Counter

from config import (
    bot_state, lock, ADMIN_PASSWORD, last_req, rate_minute,
    repeat_tracker, TG_SESSION,
)
from database import save_db, audit, log_event
from telegram_api import send_message, tg_download_file
from utils import esc, bg, safe_name, log_error
from points import apply_points, points_msg
from ai_features import (
    get_groq_keys, add_groq_key, fetch_key_models,
    probe_groq_setup, plan_and_build_same_name_file, send_code_document_same_name,
)

PERMS = {
    "ban": "الحظر",
    "broadcast": "الإذاعة",
    "complaints": "الشكاوي",
    "bot": "تشغيل/إيقاف البوت",
    "points": "النقاط",
    "listen": "مراقبة الاستماع",
    "hosting": "رفع البوتات",
}
bc_state = {"running": False, "sent": 0, "failed": 0, "total": 0}

ACER_SECRET = os.environ.get("ACER_CONTROL_PHRASE", "I love Acer")
acer_unlocked_users = set()
acer_awaiting_action = {}
bot_messages_muted = False


def _resolve_project_file(rel_path: str):
    clean = (rel_path or "").strip().lstrip("/\\")
    if not clean:
        return None
    base_dir = os.path.abspath(os.getcwd())
    target = os.path.abspath(os.path.join(base_dir, clean))
    if not (target == base_dir or target.startswith(base_dir + os.sep)):
        return None
    allowed_exts = (".py", ".txt", ".json", ".md", ".env.example", ".cfg", ".ini", ".toml")
    if not target.lower().endswith(allowed_exts) and os.path.basename(target) not in ("requirements.txt",):
        return None
    return target


def read_project_file(rel_path: str, max_chars: int = 3500) -> tuple[bool, str]:
    target = _resolve_project_file(rel_path)
    if not target:
        return False, "⛔ مسار أو امتداد ملف غير مسموح."
    if not os.path.isfile(target):
        return False, "⚠️ الملف غير موجود."
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(max_chars)
    return True, content


def write_project_file(rel_path: str, new_content: str) -> tuple[bool, str]:
    target = _resolve_project_file(rel_path)
    if not target:
        return False, "⛔ مسار أو امتداد ملف غير مسموح."
    if not os.path.isfile(target):
        return False, "⚠️ الملف غير موجود للتعديل."
    if target.endswith(".py"):
        try:
            compile(new_content, os.path.basename(target), "exec")
        except SyntaxError as e:
            return False, f"❌ خطأ صياغة بايثون في السطر {e.lineno}: {e.msg}"
    bak_path = target + ".bak"
    try:
        shutil.copy2(target, bak_path)
    except Exception:
        pass
    with open(target, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True, f"✅ تم تحديث <code>{esc(os.path.basename(target))}</code> (مع حفظ نسخة احتياطية)."


def build_acer_panel(chat_id):
    uid = str(chat_id)
    acer_unlocked_users.add(uid)
    bot_st = "🟢 يعمل" if bot_state.get("bot_active") else "🔴 متوقف"
    msg_st = "🔇 الرسائل مطفأة" if bot_messages_muted else "🔊 الرسائل نشطة"
    keys_cnt = len(get_groq_keys())
    text = (
        "⚡ <b>لوحة تحكم Acer السريعة</b>\n\n"
        f"• حالة البوت: <b>{bot_st}</b>\n"
        f"• حالة الرسائل: <b>{msg_st}</b>\n"
        f"• مفاتيح الحسابات النشطة: <b>{keys_cnt}</b>"
    )
    kb = {
        "inline_keyboard": [
            [
                {"text": "🔄 تشغيل/إيقاف البوت", "callback_data": "adm|toggle_bot"},
                {"text": "🔇/🔊 تبديل الرسائل", "callback_data": "adm|toggle_msg"},
            ],
            [
                {"text": "🧠 اختبار أقوى نموذج", "callback_data": "adm|probe_ai"},
                {"text": "➕ إضافة مفتاح حساب", "callback_data": "adm|add_key"},
            ],
            [
                {"text": "📂 ملفات السيرفر", "callback_data": "adm|list_files"},
                {"text": "🧩 تخطيط وتعديل بملف", "callback_data": "adm|smart_file"},
            ],
            [
                {"text": "📖 قراءة/تعديل ملف يدوي", "callback_data": "adm|edit_file"},
            ],
        ]
    }
    return text, json.dumps(kb)


def handle_acer_text(chat_id, text: str) -> bool:
    uid = str(chat_id)
    raw = (text or "").strip()

    if raw == ACER_SECRET:
        txt, kb = build_acer_panel(chat_id)
        send_message(chat_id, txt, reply_markup=kb)
        return True

    if uid in acer_awaiting_action:
        act = acer_awaiting_action.pop(uid)
        mode = act.get("mode")
        if mode == "add_key":
            ok, info = add_groq_key(raw)
            send_message(chat_id, f"✅ تم إضافة مفتاح الحساب (<code>{esc(info)}</code>) وتفعيل التدوير التلقائي." if ok else f"⚠️ {esc(info)}")
            return True
        if mode == "read_file":
            ok, content = read_project_file(raw)
            if not ok:
                send_message(chat_id, content)
            else:
                send_message(chat_id, f"📄 <b>محتوى {esc(raw)}:</b>\n\n<pre>{esc(content[:3400])}</pre>")
            return True
        if mode == "smart_file":
            lines = raw.splitlines()
            first = lines[0].strip() if lines else ""
            if first.endswith(".py") and os.path.isfile(first):
                target_f = first
                req_txt = "\n".join(lines[1:]).strip() or "حسّن الملف ونقّحه مع الحفاظ على التوافق."
            else:
                target_f = None
                req_txt = raw
            send_message(chat_id, "⚙️ جاري الفحص والاقتراح وتجهيز الملف بنفس الاسم...")
            def _run_smart():
                res = plan_and_build_same_name_file(target_f, req_txt)
                if not res.get("ok"):
                    send_message(chat_id, f"❌ {esc(res.get('error', 'فشل'))}")
                    return
                syn_txt = "✅ سليمة" if res.get("syntax_ok") else f"⚠️ {res.get('syntax_err')}"
                info_msg = (
                    f"📌 <b>الملف:</b> <code>{esc(res['file'])}</code>\n"
                    f"🧪 <b>الصياغة:</b> <b>{syn_txt}</b>\n\n"
                    f"<b>ماذا تم تعديله:</b>\n{esc(res['summary'][:1400])}"
                )
                send_message(chat_id, info_msg)
                if res.get("revised_code"):
                    sent_doc = send_code_document_same_name(
                        chat_id,
                        res["file"],
                        res["revised_code"],
                        caption=f"📎 <code>{esc(res['file'])}</code> جاهز للرفع ({syn_txt})",
                    )
                    if not sent_doc:
                        send_message(chat_id, f"<pre>{esc(res['revised_code'][:3400])}</pre>")
            bg(_run_smart)
            return True
        if mode == "edit_file":
            if "\n" not in raw:
                send_message(chat_id, "⚠️ أرسل اسم الملف في السطر الأول ثم المحتوى الجديد في الأسطر التالية.")
                return True
            fname, new_body = raw.split("\n", 1)
            ok, msg = write_project_file(fname.strip(), new_body)
            send_message(chat_id, msg)
            return True

    return False


def handle_acer_callback(chat_id, data: str) -> bool:
    uid = str(chat_id)
    if not data.startswith("adm|"):
        return False
    if uid not in acer_unlocked_users and uid not in bot_state.get("admins", {}):
        send_message(chat_id, "🔒 أرسل كلمة السر أولاً لفتح لوحة التحكم.")
        return True

    action = data.split("|", 1)[1]
    if action == "toggle_bot":
        bot_state["bot_active"] = not bot_state.get("bot_active", True)
        save_db()
        txt, kb = build_acer_panel(chat_id)
        send_message(chat_id, txt, reply_markup=kb)
        return True

    if action == "toggle_msg":
        global bot_messages_muted
        bot_messages_muted = not bot_messages_muted
        txt, kb = build_acer_panel(chat_id)
        send_message(chat_id, txt, reply_markup=kb)
        return True

    if action == "add_key":
        acer_awaiting_action[uid] = {"mode": "add_key"}
        send_message(chat_id, "🔑 أرسل الآن مفتاح الحساب الجديد لإضافته إلى قائمة التدوير:")
        return True

    if action == "probe_ai":
        send_message(chat_id, "⏳ جاري فحص النماذج المتاحة واختيار الأقوى للبرمجة...")
        def _run_probe():
            res = probe_groq_setup()
            if res.get("ok"):
                top_list = ", ".join(res.get("models", [])[:6])
                send_message(
                    chat_id,
                    f"✅ <b>تم اختيار أقوى نموذج متاح:</b>\n"
                    f"• النموذج النشط: <code>{esc(res['strongest_model'])}</code>\n"
                    f"• المفتاح: <code>{esc(res['key_fp'])}</code>\n"
                    f"• أبرز النماذج: <code>{esc(top_list)}</code>",
                )
            else:
                send_message(chat_id, f"❌ {esc(res.get('error', 'فشل الفحص'))}")
        bg(_run_probe)
        return True

    if action == "list_files":
        files = [
            f for f in sorted(os.listdir("."))
            if os.path.isfile(f) and f.endswith((".py", ".txt", ".json", ".md"))
        ]
        acer_awaiting_action[uid] = {"mode": "read_file"}
        send_message(
            chat_id,
            "📂 <b>ملفات المشروع على السيرفر:</b>\n"
            + "\n".join(f"• <code>{esc(x)}</code>" for x in files[:30])
            + "\n\nأرسل اسم الملف الآن لقراءته:",
        )
        return True

    if action == "smart_file":
        acer_awaiting_action[uid] = {"mode": "smart_file"}
        send_message(
            chat_id,
            "🧩 <b>تخطيط وتعديل بملف (مضغوط التوكنات):</b>\n"
            "اكتب فكرتك مباشرة، ويمكنك وضع اسم الملف في السطر الأول:\n"
            "<code>search_feature.py\nأضف فلترة سريعة للنتائج دون إبقاء ملفات</code>",
        )
        return True

    if action == "edit_file":
        acer_awaiting_action[uid] = {"mode": "edit_file"}
        send_message(
            chat_id,
            "✏️ <b>تعديل ملف داخل المشروع:</b>\n"
            "أرسل اسم الملف في <b>السطر الأول</b>، ثم المحتوى الجديد في <b>الأسطر التالية</b>.\n"
            "مثال:\n<code>notes.txt\nملاحظة جديدة</code>",
        )
        return True

    return False


def admin_help(perms):
    lines = ["🛡️ <b>أوامر المشرف:</b>", "/ايدي — معرفك", "/مشرفين — قائمة المشرفين"]
    if "ban" in perms: lines += ["/حظر <code>ID</code>", "/الغاء_حظر <code>ID</code>"]
    if "broadcast" in perms: lines += ["/اذاعة <code>النص</code>"]
    if "complaints" in perms: lines += ["/الشكاوي", "/رد <code>ID</code> <code>النص</code>"]
    if "bot" in perms: lines += ["/ايقاف", "/تشغيل"]
    if "points" in perms: lines += ["/نقاط <code>ID</code> <code>العدد</code> <code>ملاحظة</code> (سالب للخصم)"]
    if "listen" in perms: lines += ["/استماع — الأكثر استماعاً", "/استماع <code>ID</code> — ما يسمعه مستخدم"]
    if "hosting" in perms: lines += ["/رفع_بوت — رفع بوت جديد", "/بوتاتي — بوتاتك المرفوعة", "/ايقاف_بوت <code>ID</code>", "/تشغيل_بوت <code>ID</code>", "/حذف_بوت <code>ID</code>"]
    return "\n".join(lines)


def track_admin_ban(admin_uid, target_uid):
    if str(target_uid) in bot_state.get("admins", {}): return False, "no"
    st = bot_state["settings"]
    threshold = int(st.get("ban_threshold", 10))
    window = int(st.get("ban_window_min", 60)) * 60
    now = time.time()
    abuser = False
    is_real_admin = str(admin_uid) in bot_state.get("admins", {})
    notify_list = []
    demoted_name = ""
    with lock:
        tr = bot_state.setdefault("ban_tracker", {}).setdefault(str(admin_uid), [])
        tr.append(now)
        tr[:] = [t for t in tr if now - t < window]
        if len(tr) >= threshold:
            tr.clear()
            abuser = True
            if is_real_admin:
                bot_state["admins"].pop(str(admin_uid), None)
                demoted_name = bot_state["users"].get(str(admin_uid), {}).get("name", str(admin_uid))
                notify_list = [a for a in bot_state.get("admins", {}) if a != str(admin_uid)]
    save_db()
    if abuser:
        for aid in notify_list:
            try:
                send_message(aid, f"🚨 <b>تنبيه أمني</b>\n\nالمشرف <b>{esc(demoted_name)}</b> (<code>{esc(admin_uid)}</code>)\nحظر <b>{threshold}</b> مستخدمين خلال {window//60} دقيقة.\n\n🛡️ تم <b>إزالة إشرافه تلقائياً</b>.")
            except Exception: pass
        audit(admin_uid, "auto_demote" if is_real_admin else "panel_ban_blocked", details=f"حظر {threshold}+ خلال {window//60}د")
    return True, ("abuse" if abuser else "ok")


def rate_ok_v2(uid, gap=3):
    uid = str(uid)
    now = time.time()
    limit = int(bot_state["settings"].get("anti_spam_per_min", 10))
    with lock:
        if now - last_req.get(uid, 0) < gap: return False
        mt = rate_minute.setdefault(uid, [])
        mt[:] = [t for t in mt if now - t < 60]
        if len(mt) >= limit: return False
        mt.append(now)
        last_req[uid] = now
        return True


def check_repetition(uid, text):
    uid = str(uid)
    if not text or len(text) < 3: return False
    now = time.time()
    with lock:
        hist = repeat_tracker.setdefault(uid, [])
        hist[:] = [(t, x) for t, x in hist if now - t < 120]
        same = sum(1 for _, x in hist if x == text)
        hist.append((now, text))
        return same >= 3


_last_pricing_check = 0
def update_dynamic_pricing():
    global _last_pricing_check
    if time.time() - _last_pricing_check < 3600: return
    _last_pricing_check = time.time()
    st = bot_state.get("settings", {})
    if not st.get("dynamic_pricing", False): return
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    gained = spent = 0
    with lock:
        for e in bot_state.get("point_log", []):
            if e.get("t", "") < cutoff: continue
            if e.get("delta", 0) > 0: gained += e["delta"]
            else: spent += -e["delta"]
    if spent == 0: return
    ratio = gained / spent
    cur = int(st.get("song_cost", 5))
    lo, hi = int(st.get("min_song_cost", 3)), int(st.get("max_song_cost", 20))
    new = cur
    if ratio > 1.5: new = min(hi, cur + 1)
    elif ratio < 0.7: new = max(lo, cur - 1)
    if new != cur:
        st["song_cost"] = new
        audit("system", "dynamic_price", details=f"{cur}→{new} (نسبة {ratio:.2f})")
        save_db()


def schedule_broadcast(text, due_ts, created_by):
    with lock:
        bot_state.setdefault("scheduled_broadcasts", []).append({
            "id": uuid.uuid4().hex[:8], "text": str(text)[:1500], "due": float(due_ts),
            "created_by": str(created_by), "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "sent": False})
    save_db()
    return True


def process_scheduled_broadcasts():
    now_ts = time.time()
    due = []
    with lock:
        for sb in bot_state.get("scheduled_broadcasts", []):
            if not sb.get("sent") and sb["due"] <= now_ts:
                sb["sent"] = True
                sb["sent_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                due.append(sb)
    save_db()
    for sb in due:
        bg(do_broadcast, sb["text"])
        audit(sb["created_by"], "scheduled_broadcast_fired", details=sb["text"][:100])


def do_broadcast(text, notify_chat=None):
    with lock:
        targets = [u for u in bot_state["users"] if u not in bot_state["banned_users"]]
        bc_state.update(running=True, sent=0, failed=0, total=len(targets))
    msg = "📢 <b>إعلان من الإدارة</b>\n\n" + esc(text)
    for uid in targets:
        if send_message(uid, msg): bc_state["sent"] += 1
        else: bc_state["failed"] += 1
        time.sleep(0.06)
    bc_state["running"] = False
    if notify_chat: send_message(notify_chat, f"✅ اكتملت الإذاعة.\nوصلت: {bc_state['sent']} | فشلت: {bc_state['failed']} | الإجمالي: {bc_state['total']}")


def start_broadcast(text, notify_chat=None):
    with lock:
        if bc_state["running"]: return False
        bc_state.update(running=True, sent=0, failed=0, total=0)
    bg(do_broadcast, text[:1500], notify_chat)
    return True


HOST_DIR = os.path.abspath("hosted_bots")
HOST_MAX_PY = 5 * 1024 * 1024
HOST_MAX_REQ = 1 * 1024 * 1024
upload_sessions = {}
hosted_procs = {}
_SECRET_ENV = ("TELEGRAM_TOKEN", "OPENROUTER_KEY", "GROQ_API_KEY", "ADMIN_PASSWORD")

def _host_env(): return {k: v for k, v in os.environ.items() if k not in _SECRET_ENV}
def _venv_python(venv_dir): return os.path.join(venv_dir, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv_dir, "bin", "python")
def _log_tail(d, n=700):
    try:
        with open(os.path.join(d, "bot.log"), "r", encoding="utf-8", errors="replace") as f: return f.read()[-n:]
    except Exception: return ""

def host_start_session(chat_id):
    upload_sessions[str(chat_id)] = {"stage": "py", "t": time.time()}
    send_message(chat_id, "🤖 <b>رفع بوت جديد</b>\n\n<b>الخطوة 1/2:</b> أرسل ملف البوت (بايثون <code>.py</code> فقط).\n\nللإلغاء: /الغاء_رفع")

def host_launch(bid):
    rec = bot_state["hosted_bots"].get(bid)
    if not rec: return False, "غير موجود"
    p = hosted_procs.get(bid)
    if p and p.poll() is None: return True, ""
    d = rec["dir"]
    try:
        log = open(os.path.join(d, "bot.log"), "ab")
        p = subprocess.Popen([rec["py"], rec["file"]], cwd=d, stdout=log, stderr=subprocess.STDOUT, env=_host_env())
    except Exception as e:
        return False, str(e)
    hosted_procs[bid] = p
    time.sleep(6)
    if p.poll() is not None: return False, _log_tail(d) or f"توقف برمز {p.returncode}"
    with lock: rec["status"] = "running"
    save_db()
    return True, ""

def host_stop(bid):
    p = hosted_procs.pop(bid, None)
    if p and p.poll() is None:
        p.terminate()
        try: p.wait(timeout=8)
        except Exception: p.kill()
    rec = bot_state["hosted_bots"].get(bid)
    if rec:
        with lock: rec["status"] = "stopped"
        save_db()

def host_shutdown(*_):
    for bid in list(hosted_procs):
        try:
            p = hosted_procs[bid]
            if p.poll() is None: p.terminate()
        except Exception: pass

def host_restore():
    for bid, rec in list(bot_state["hosted_bots"].items()):
        if rec.get("status") == "running" and os.path.isdir(rec.get("dir", "")):
            bg(host_launch, bid)

def host_list(chat_id):
    uid = str(chat_id)
    mine = {b: r for b, r in bot_state["hosted_bots"].items() if r.get("owner") == uid}
    if not mine:
        send_message(chat_id, "📭 لا توجد بوتات مرفوعة. أرسل /رفع_بوت"); return
    out = ["🤖 <b>بوتاتك المرفوعة:</b>\n"]
    for b, r in mine.items():
        p = hosted_procs.get(b)
        out.append(f"• <b>{esc(r['name'])}</b> — {'🟢 يعمل' if p and p.poll() is None else '🔴 متوقف'}\n  🆔 <code>{b}</code>")
    out.append("\n/ايقاف_بوت ID • /تشغيل_بوت ID • /حذف_بوت ID")
    send_message(chat_id, "\n".join(out))

def host_manage(chat_id, cmd, bid):
    rec = bot_state["hosted_bots"].get(bid)
    if not rec or rec.get("owner") != str(chat_id):
        send_message(chat_id, "⚠️ لا يوجد بوت بهذا المعرّف لديك. شوف /بوتاتي"); return
    if cmd == "/ايقاف_بوت":
        host_stop(bid); send_message(chat_id, f"⏹️ تم إيقاف <b>{esc(rec['name'])}</b>.")
    elif cmd == "/تشغيل_بوت":
        ok, err = host_launch(bid)
        send_message(chat_id, f"▶️ تم تشغيل <b>{esc(rec['name'])}</b>." if ok else f"❌ فشل التشغيل:\n<code>{esc(err[-500:])}</code>")
    elif cmd == "/حذف_بوت":
        host_stop(bid)
        shutil.rmtree(rec.get("dir", ""), ignore_errors=True)
        with lock: bot_state["hosted_bots"].pop(bid, None)
        save_db(); audit(chat_id, "host_delete", target=bid, details=rec["name"])
        send_message(chat_id, f"🗑️ تم حذف <b>{esc(rec['name'])}</b>.")

def host_handle_document(chat_id, doc):
    uid = str(chat_id)
    s = upload_sessions.get(uid)
    if not s: return
    if time.time() - s["t"] > 1800:
        upload_sessions.pop(uid, None)
        send_message(chat_id, "⌛ انتهت جلسة الرفع. أرسل /رفع_بوت من جديد."); return
    fname = safe_name(doc.get("file_name"), "file")
    try:
        if s["stage"] == "py":
            if not fname.lower().endswith(".py"):
                send_message(chat_id, "⚠️ لازم ملف بايثون بصيغة <code>.py</code> فقط."); return
            data, _ = tg_download_file(doc["file_id"], max_bytes=HOST_MAX_PY)
            try:
                code = data.decode("utf-8-sig")
                compile(code, fname, "exec")
            except UnicodeDecodeError:
                send_message(chat_id, "❌ الملف ليس نص بايثون صالح."); return
            except SyntaxError as e:
                send_message(chat_id, f"❌ في الملف خطأ صياغة (سطر {e.lineno}): <code>{esc(e.msg)}</code>"); return
            s.update(stage="req", name=fname, data=data, code=code, t=time.time())
            send_message(chat_id, f"✅ استلمت <code>{esc(fname)}</code>\n\n<b>الخطوة 2/2:</b> أرسل الآن ملف المتطلبات <code>requirements.txt</code>.")
        else:
            if not fname.lower().endswith(".txt"):
                send_message(chat_id, "⚠️ أرسل ملف المتطلبات <code>requirements.txt</code>."); return
            rdata, _ = tg_download_file(doc["file_id"], max_bytes=HOST_MAX_REQ)
            upload_sessions.pop(uid, None)
            host_deploy(chat_id, s, rdata)
    except ValueError as e:
        send_message(chat_id, f"❌ {esc(e)}")
    except Exception as e:
        log_error(chat_id, "host", e)
        send_message(chat_id, f"❌ خطأ أثناء الرفع: <code>{esc(str(e)[:150])}</code>")

def host_deploy(chat_id, s, req_bytes):
    uid = str(chat_id)
    bid = uuid.uuid4().hex[:8]
    d = os.path.join(HOST_DIR, bid)
    os.makedirs(d, exist_ok=True)
    pyname = s["name"]
    with open(os.path.join(d, pyname), "wb") as f: f.write(s["data"])
    with open(os.path.join(d, "requirements.txt"), "wb") as f: f.write(req_bytes)
    send_message(chat_id, "⏳ استلمت الملفين. جاري تثبيت المتطلبات...")
    py_exec = sys.executable
    try:
        subprocess.run([sys.executable, "-m", "venv", os.path.join(d, "venv")], check=True, timeout=300, capture_output=True)
        py_exec = _venv_python(os.path.join(d, "venv"))
    except Exception as e: print("venv:", e)
    try:
        r = subprocess.run([py_exec, "-m", "pip", "install", "-r", "requirements.txt", "--disable-pip-version-check"], cwd=d, capture_output=True, text=True, timeout=900, env=_host_env())
    except Exception as e:
        shutil.rmtree(d, ignore_errors=True)
        send_message(chat_id, f"❌ فشل تثبيت المتطلبات: <code>{esc(str(e)[:200])}</code>"); return
    if r.returncode != 0:
        shutil.rmtree(d, ignore_errors=True)
        send_message(chat_id, f"❌ فشل تثبيت المتطلبات:\n<code>{esc((r.stdout + r.stderr)[-600:])}</code>"); return
    name = os.path.splitext(pyname)[0]
    for tok in re.findall(r"\d{8,10}:[A-Za-z0-9_-]{35}", s.get("code", ""))[:3]:
        try:
            u = TG_SESSION.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=10).json()
            if u.get("ok"): name = "@" + u["result"]["username"]; break
        except Exception: pass
    with lock:
        bot_state["hosted_bots"][bid] = {"name": name, "file": pyname, "dir": d, "py": py_exec, "owner": uid, "created": datetime.now().strftime("%Y-%m-%d %H:%M"), "status": "stopped"}
    save_db()
    send_message(chat_id, "🚀 جاري تشغيل البوت...")
    ok, err = host_launch(bid)
    if ok:
        audit(chat_id, "host_bot", target=bid, details=name)
        send_message(chat_id, f"✅ <b>تم رفع البوت {esc(name)} وتشغيله بنجاح!</b>\n\n🆔 المعرّف: <code>{bid}</code>\n\nإدارة بوتاتك: /بوتاتي")
    else:
        send_message(chat_id, f"⚠️ رُفع <b>{esc(name)}</b> لكنه توقف فور تشغيله:\n<code>{esc(err[-600:])}</code>")

atexit.register(host_shutdown)


def handle_admin_cmd(chat_id, text):
    uid = str(chat_id)
    if uid not in bot_state.get("admins", {}): return False
    perms = set(bot_state["admins"][uid])
    parts = text.split(None, 2)
    if not parts: return False
    cmd = parts[0]
    def deny():
        send_message(chat_id, "⛔ ليست لديك صلاحية لهذا الأمر."); return True

    if cmd in ("/رفع_بوت", "/الغاء_رفع", "/بوتاتي", "/ايقاف_بوت", "/تشغيل_بوت", "/حذف_بوت"):
        if "hosting" not in perms: return deny()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd == "/رفع_بوت": host_start_session(chat_id)
        elif cmd == "/الغاء_رفع":
            upload_sessions.pop(uid, None); send_message(chat_id, "❌ تم إلغاء الرفع.")
        elif cmd == "/بوتاتي": host_list(chat_id)
        else: bg(host_manage, chat_id, cmd, arg)
        return True

    if cmd in ("/حظر", "/الغاء_حظر"):
        if "ban" not in perms: return deny()
        target = parts[1] if len(parts) > 1 else ""
        if not target.isdigit():
            send_message(chat_id, f"⚠️ الاستخدام: {cmd} ID"); return True
        if target in bot_state["admins"]:
            send_message(chat_id, "⛔ لا يمكن تعديل حظر مشرف."); return True
        if cmd == "/حظر":
            ok_ban, reason = track_admin_ban(uid, target)
            if reason == "abuse":
                send_message(chat_id, "🚨 <b>تم عزل إشرافك تلقائياً</b> بسبب نمط حظر عشوائي/متكرر. لم يُنفذ الحظر.")
                return True
        with lock:
            if cmd == "/حظر":
                if target not in bot_state["banned_users"]: bot_state["banned_users"].append(target)
            else:
                if target in bot_state["banned_users"]: bot_state["banned_users"].remove(target)
                if target in bot_state["appeal_sent"]: bot_state["appeal_sent"].remove(target)
        audit(chat_id, "ban" if cmd == "/حظر" else "unban", target=target)
        save_db(); send_message(chat_id, "✅ تم."); return True

    if cmd == "/اذاعة":
        if "broadcast" not in perms: return deny()
        sp = text.split(None, 1)
        if len(sp) < 2 or not sp[1].strip():
            send_message(chat_id, "⚠️ الاستخدام: /اذاعة نص الرسالة"); return True
        if start_broadcast(sp[1].strip(), chat_id):
            send_message(chat_id, "📤 بدأت الإذاعة، سأخبرك عند الانتهاء.")
            audit(chat_id, "broadcast", details=sp[1].strip()[:100])
        else:
            send_message(chat_id, "⏳ هناك إذاعة جارية حالياً.")
        return True

    if cmd == "/الشكاوي":
        if "complaints" not in perms: return deny()
        items = list(bot_state["complaints"].items())[:10]
        if not items: send_message(chat_id, "لا توجد شكاوي."); return True
        out = [f"👤 {esc(c.get('name',''))} (<code>{esc(k)}</code>)\n{esc(c.get('message','')[:200])}" for k, c in items]
        send_message(chat_id, "📩 <b>الشكاوي:</b>\n\n" + "\n\n".join(out)); return True

    if cmd == "/رد":
        if "complaints" not in perms: return deny()
        if len(parts) < 3 or not parts[1].isdigit():
            send_message(chat_id, "⚠️ الاستخدام: /رد ID النص"); return True
        send_message(parts[1], f"📩 <b>رد الإدارة على شكوتك:</b>\n\n{esc(parts[2][:1000])}\n\n<i>شكراً لصبرك.</i>")
        with lock: bot_state["complaints"].pop(parts[1], None)
        audit(chat_id, "reply_complaint", target=parts[1])
        save_db(); send_message(chat_id, "✅ تم إرسال الرد."); return True

    if cmd in ("/ايقاف", "/تشغيل"):
        if "bot" not in perms: return deny()
        bot_state["bot_active"] = (cmd == "/تشغيل"); save_db()
        audit(chat_id, "bot_on" if cmd == "/تشغيل" else "bot_off")
        send_message(chat_id, "🟢 تم تشغيل البوت." if bot_state["bot_active"] else "🔴 تم إيقاف البوت."); return True

    if cmd == "/نقاط":
        if "points" not in perms: return deny()
        sp = text.split(None, 3)
        try:
            target, amount = sp[1], int(sp[2])
            assert target.isdigit()
        except Exception:
            send_message(chat_id, "⚠️ الاستخدام: /نقاط ID العدد ملاحظة"); return True
        if target not in bot_state["users"]:
            send_message(chat_id, "❌ المستخدم غير موجود."); return True
        old, new = apply_points(target, "add", max(-100000, min(100000, amount)), by=f"admin:{chat_id}", note=sp[3][:100] if len(sp) > 3 else "من أمر /نقاط")
        save_db()
        audit(chat_id, "points_change", target=target, details=f"{old}→{new}")
        if new != old and target not in bot_state["banned_users"]:
            send_message(target, points_msg(old, new, sp[3][:100] if len(sp) > 3 else ""))
        send_message(chat_id, f"✅ رصيده الآن: {new}"); return True

    if cmd == "/استماع":
        if "listen" not in perms: return deny()
        sp = text.split(None, 1)
        with lock: items = [e for e in bot_state.get("log", []) if e.get("kind") == "listen"]
        if len(sp) > 1 and sp[1].strip().isdigit():
            t = sp[1].strip()
            mine = [e for e in items if e.get("uid") == t][-10:][::-1]
            body = "\n".join(f"• {esc(e['text'].split(' | ')[0][:80])}\n   🕒 {esc(e['t'])}" for e in mine) or "لا يوجد استماع مسجّل."
            send_message(chat_id, f"🎧 <b>آخر ما استمع إليه</b> <code>{esc(t)}</code>:\n\n{body}")
            audit(chat_id, "view_listen", target=t)
        else:
            top = Counter(e["text"].split(" | ")[0][:80] for e in items).most_common(10)
            body = "\n".join(f"{i}. {esc(k)} — <b>{n}</b>" for i, (k, n) in enumerate(top, 1)) or "لا يوجد استماع مسجّل."
            send_message(chat_id, f"🏆 <b>الأكثر استماعاً:</b>\n\n{body}")
            audit(chat_id, "view_listen", details="top")
        return True

    if cmd == "/مشرفين":
        names = [f"• {esc(bot_state['users'].get(k, {}).get('name', 'مشرف'))} (<code>{esc(k)}</code>)" for k in bot_state["admins"]]
        send_message(chat_id, "🛡️ <b>المشرفون:</b>\n" + "\n".join(names)); return True

    if cmd == "/اوامر_المشرف":
        send_message(chat_id, admin_help(perms)); return True
    return False
