# ==========================================
# ملف التشغيل الرئيسي وحلقة البوت (main.py)
# متوافق بالكامل مع النظام المقسّم (search_feature + anime_sites + media_downloader + search_core)
# ==========================================
import os
import re
import sys
import time
import json
import uuid
import atexit
import signal
import threading
from datetime import datetime, date

from config import bot_state, lock, TELEGRAM_TOKEN, BOT_USERNAME, SUPPORT_EMAIL
from database import save_db, flush_db, db_flusher, backup_loop, log_event
from telegram_api import send_message, TG_SESSION, fetch_bot_username, upload_media
from utils import bg, esc, classify, store_url, get_url
from points import setting, get_points, points_card, points_bar
from admin import (
    handle_admin_cmd, track_admin_ban, rate_ok_v2, check_repetition,
    host_restore, host_shutdown, host_handle_document, upload_sessions,
    handle_acer_text, handle_acer_callback, acer_awaiting_action, bot_messages_muted,
)
from prayer import (
    ask_location, set_city, show_prayer, show_occasions, REM_HELP,
    add_reminder, list_reminders, pt_cache, set_location_gps,
    toggle_adhan, show_methods, set_method, cancel_reminder,
)
from downloader import (
    get_video_info, download_and_send_file, download_and_send_video,
    search_and_download_audio, ai_explain, trim_sessions, parse_time_text,
    trim_and_send_audio, get_file_info, random_song, purge_downloads_dir,
)
from ai_features import process_image, ask_ai, feature_on, cfg_int, chat_history
from account_lookup import show_account_picker, cmd_account, account_callback
from scheduler import scheduler_loop
from web_ui import run_dashboard

# استيراد واجهة البحث الموحدة (تستدعي تلقائياً anime_sites و media_downloader و search_core)
from search_feature import (
    smart_search, show_search_platforms, handle_search_callback,
    handle_search_text_input, inspect_direct_url, search_sessions,
    chapter_merge_sessions, awaiting_cookie_for,
)


def ai_reply_cmd(chat_id, loading_msg, prompt):
    send_message(chat_id, loading_msg)
    reply = ask_ai(chat_id, prompt)
    send_message(chat_id, f"🤖 {esc(reply)}")


def ai_chat(chat_id, text):
    reply = ask_ai(chat_id, text)
    send_message(chat_id, esc(reply))


def delete_user_log(chat_id):
    uid = str(chat_id)
    with lock:
        before = len(bot_state.get("log", []))
        bot_state["log"] = [e for e in bot_state.get("log", []) if e.get("uid") != uid]
        removed = before - len(bot_state["log"])
    save_db()
    send_message(chat_id, f"🗑️ تم حذف {removed} عملية من سجل نشاطك.")


COMMANDS_HELP = (
    "🧰 <b>قائمة الأوامر:</b>\n\n"
    "🔍 <code>/بحث</code> أو <code>/بحث [موضوع]</code> - بحث سريع في مواقع الأنمي والويب بدون إبقاء ملفات على السيرفر\n"
    "🧠 <code>/تصفير</code> - مسح ذاكرة المحادثة\n"
    "🕌 <code>/صلاة</code> - مواقيت الصلاة\n"
    "📅 <code>/مواعيد</code> - المناسبات\n"
    "⏰ <code>/ذكرني ...</code> - إضافة تذكير\n"
    "🎵 <code>يوت [اسم الأغنية]</code> - تحميل أغنية\n"
    "🎲 <code>/اغنية</code> - أغنية عشوائية\n"
    "💰 <code>/نقاطي</code> - عرض رصيدك\n"
    "👤 <code>/حساب [اسم]</code> - معلومات حساب\n"
    "🖼️ أرسل صورة - لتحليلها أو استخراج نصها\n"
    "🔗 أرسل أي رابط - لتحميل الفيديو أو الحلقة مباشرة"
)

PRIVACY_TEXT = (
    "🔒 <b>خصوصيتك</b>\n\n"
    "يحفظ البوت: اسمك ومعرّفك، وطلباتك (الروابط، الأغاني، الأوامر)، وملخصاً قصيراً لنتائج الصور.\n"
    "لا نحفظ الصور نفسها.\n"
    "يطلع على هذا السجل مالك البوت ومشرفوه لتحسين الخدمة ومنع الإساءة.\n\n"
    "🗑️ لحذف سجل نشاطك: /حذف_سجلي"
)


def _is_anime_or_direct_media_link(url: str) -> bool:
    """يميز روابط مواقع الأنمي وروابط التحميل المباشرة/الوسيطة لتمريرها لمحرك الأنمي بدلاً من yt-dlp."""
    low = (url or "").strip().lower()
    if not low.startswith(("http://", "https://")):
        return False
    if any(k in low for k in ("/links/", "/download/", "/episodes/", "/seasons/", "pixeldrain.com")):
        return True
    try:
        from anime_sites import is_registered_anime_url
        if is_registered_anime_url(url):
            return True
    except Exception:
        pass
    return False


def bot_loop():
    last_update_id = 0
    try:
        TG_SESSION.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset=-1", timeout=5)
    except Exception:
        pass
    try:
        TG_SESSION.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook", timeout=5)
    except Exception:
        pass

    print("🤖 البوت يعمل...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=25"
            response = TG_SESSION.get(url, timeout=30)
            if response.status_code == 200:
                for update in response.json().get("result", []):
                    last_update_id = update["update_id"]

                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        user_data = update["message"]["from"]
                        text = update["message"]["text"].strip()
                        uid = str(chat_id)

                        if uid in bot_state["banned_users"]:
                            if uid in bot_state["appeal_sent"]:
                                send_message(chat_id, f"⛔ محظور مسبقاً.\n📧 {SUPPORT_EMAIL}")
                            elif text.startswith("شكوى") or text.startswith("/شكوى"):
                                appeal_msg = text.replace("/شكوى", "").replace("شكوى", "").strip()[:500]
                                if appeal_msg:
                                    with lock:
                                        bot_state["complaints"][uid] = {
                                            "name": user_data.get("first_name", "مستخدم"),
                                            "message": appeal_msg,
                                            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                        }
                                        bot_state["appeal_sent"].append(uid)
                                    save_db()
                                    send_message(chat_id, "✅ تم إرسال شكوتك.")
                            else:
                                send_message(chat_id, f"⛔ أنت محظور.\n📧 {SUPPORT_EMAIL}\n\n📩 شكوى واحدة:\n<code>/شكوى [النص]</code>")
                            continue

                        # 1. كلمة السر ولوحة التحكم السريعة وإدخال مفاتيح/ملفات لوحة التحكم
                        if handle_acer_text(chat_id, text):
                            continue

                        # 2. أوامر المشرفين التقليدية
                        if handle_admin_cmd(chat_id, text):
                            continue

                        # 3. أولوية قصوى لانتظار الكوكيز، الحلقات/الفصول، والبحث قبل الذكاء الاصطناعي
                        if uid in awaiting_cookie_for:
                            bg(handle_search_text_input, chat_id, text)
                            continue

                        if uid in chapter_merge_sessions and not text.startswith("/"):
                            ms = chapter_merge_sessions.get(uid) or {}
                            if time.time() - ms.get("t", 0) <= 600:
                                bg(handle_search_text_input, chat_id, text)
                                continue
                            chapter_merge_sessions.pop(uid, None)

                        if uid in search_sessions and not text.startswith("/"):
                            ss = search_sessions[uid]
                            if time.time() - ss.get("t", 0) <= 600 and ss.get("awaiting"):
                                bg(handle_search_text_input, chat_id, text)
                                continue
                            search_sessions.pop(uid, None)

                        if not bot_state["bot_active"]:
                            send_message(chat_id, "⚠️ البوت متوقف مؤقتاً.")
                            continue

                        if bot_messages_muted and not text.startswith("/"):
                            continue

                        if check_repetition(chat_id, text):
                            send_message(chat_id, "⚠️ أنت تكرر نفس الرسالة. توقف قليلاً.")
                            time.sleep(1)
                            continue

                        if not rate_ok_v2(chat_id):
                            send_message(chat_id, "⏳ تمهّل قليلاً.")
                            continue

                        from web_ui import register_user
                        register_user(chat_id, user_data)
                        log_event(classify(text), chat_id, text)

                        if text in ["/start", "/help", "الاوامر"]:
                            kb_rows = [
                                [{"text": "🕌 مواقيت الصلاة", "callback_data": "prayer"}, {"text": "📅 المناسبات", "callback_data": "occ"}],
                                [{"text": "📿 أذكار", "callback_data": "adhkar"}, {"text": "🤲 أدعية", "callback_data": "duas"}],
                                [{"text": f"🎲 أغنية عشوائية ({setting('song_cost')})", "callback_data": "song"}, {"text": "💰 نقاطي", "callback_data": "my_points"}],
                                [{"text": "🔍 بحث سريع / أنمي", "callback_data": "srch|menu"}, {"text": "🧰 كل الأوامر", "callback_data": "cmds"}],
                                [{"text": "💡 اقترح ميزة", "callback_data": "suggest"}, {"text": "📩 شكوى", "callback_data": "make_complaint"}],
                            ]
                            if BOT_USERNAME:
                                kb_rows.append([{"text": "➕ أضفني لمجموعتك", "url": f"https://t.me/{BOT_USERNAME}?startgroup=true"}])
                            keyboard = {"inline_keyboard": kb_rows}
                            menu = (
                                f"✨ <b>أهلاً بك في البوت الشامل!</b> ✨\n\n"
                                f"💰 <b>رصيدك:</b> <b>{get_points(chat_id)}</b> نقطة\n{points_bar(get_points(chat_id))}\n\n"
                                f"📥 <b>التحميل:</b> أرسل أي رابط (يوتيوب، تيك توك، أو موقع أنمي).\n"
                                f"🔍 <b>البحث السريع:</b> <code>/بحث</code> أو <code>/بحث [موضوع]</code>\n"
                                f"🧠 <b>AI:</b> أرسل أي سؤال، أو <code>/ترجم</code> / <code>/رسم</code>\n"
                                f"اختر من الأزرار: 👇"
                            )
                            send_message(chat_id, menu, reply_markup=json.dumps(keyboard))
                            continue

                        elif text == "/stats":
                            send_message(chat_id, f"📊 الطلبات: {bot_state['stats']['total_requests']} | المستخدمون: {len(bot_state['users'])}")
                            continue
                        elif text == "/ping":
                            send_message(chat_id, "🏓 Pong!")
                            continue
                        elif text == "/ايدي":
                            send_message(chat_id, f"🆔 <code>{chat_id}</code>")
                            continue
                        elif text == "/تصفير":
                            chat_history.pop(uid, None)
                            search_sessions.pop(uid, None)
                            chapter_merge_sessions.pop(uid, None)
                            awaiting_cookie_for.pop(uid, None)
                            acer_awaiting_action.pop(uid, None)
                            send_message(chat_id, "🧠 تم مسح ذاكرة المحادثة بنجاح. يمكنك البدء بموضوع جديد!")
                            continue
                        elif text == "/بحث" or text.startswith("/بحث "):
                            rest = text[len("/بحث"):].strip()
                            if rest:
                                bg(smart_search, chat_id, rest)
                            else:
                                bg(show_search_platforms, chat_id)
                            continue
                        elif text.startswith("/مدينتي"):
                            city_q = text[len("/مدينتي"):].strip()
                            if city_q:
                                bg(set_city, chat_id, city_q)
                            else:
                                ask_location(chat_id)
                            continue
                        elif text == "/حذف_موقعي":
                            with lock:
                                bot_state["users"][uid].pop("loc", None)
                                bot_state["users"][uid]["adhan"] = False
                            pt_cache.pop(uid, None)
                            save_db()
                            send_message(chat_id, "🗑️ تم حذف موقعك.")
                            continue
                        elif text in ("/صلاة", "/مواقيت", "مواقيت الصلاة"):
                            bg(show_prayer, chat_id)
                            continue
                        elif text in ("/مواعيد", "/مناسبات"):
                            bg(show_occasions, chat_id)
                            continue
                        elif text.startswith("/ذكرني"):
                            rem_rest = text[len("/ذكرني"):].strip()
                            if rem_rest:
                                add_reminder(chat_id, rem_rest)
                            else:
                                send_message(chat_id, REM_HELP)
                            continue
                        elif text == "/تذكيراتي":
                            list_reminders(chat_id)
                            continue
                        elif text in ("/اغنية", "اغنية عشوائية"):
                            bg(random_song, chat_id)
                            continue
                        elif text in ("/نقاطي", "/رصيدي", "نقاطي", "رصيدي"):
                            send_message(chat_id, points_card(chat_id))
                            continue
                        elif text == "/اوامر":
                            send_message(chat_id, COMMANDS_HELP)
                            continue
                        elif text == "/خصوصيتي":
                            send_message(chat_id, PRIVACY_TEXT)
                            continue
                        elif text == "/حذف_سجلي":
                            delete_user_log(chat_id)
                            continue
                        elif (text.split(None, 1) or [""])[0] == "/حساب":
                            bg(cmd_account, chat_id, text[len("/حساب"):].strip())
                            continue
                        elif text.startswith("/ترجم "):
                            bg(ai_reply_cmd, chat_id, "🌐 جاري الترجمة...", "ترجم إلى العربية:\n" + text.replace("/ترجم ", "", 1))
                            continue
                        elif text.startswith("/رسم "):
                            send_message(chat_id, "🎨 ميزة الرسم قيد التطوير.")
                            continue
                        elif uid in trim_sessions:
                            ts = trim_sessions[uid]
                            if time.time() - ts.get("t", 0) > 1800:
                                trim_sessions.pop(uid, None)
                                send_message(chat_id, "⌛ انتهت جلسة القص. اضغط «✂️ مقطع صوتي» من جديد.")
                                continue
                            pt = parse_time_text(text)
                            if pt:
                                t1, t2 = pt
                                if t2 <= t1:
                                    send_message(chat_id, "⚠️ نهاية المقطع يجب أن تكون بعد بدايته.")
                                    continue
                                trim_sessions.pop(uid, None)
                                bg(trim_and_send_audio, chat_id, ts["url"], t1, t2)
                            else:
                                send_message(chat_id, "⚠️ لم أفهم التوقيت. اكتبه هكذا:\n<code>1:25 - 3:40</code>")
                            continue
                        elif text.startswith("http"):
                            if feature_on("download"):
                                if _is_anime_or_direct_media_link(text):
                                    bg(inspect_direct_url, chat_id, text)
                                else:
                                    bg(get_video_info, chat_id, text, user_data)
                            else:
                                send_message(chat_id, "⚠️ التحميل معطّل حالياً.")
                        elif text.startswith("يوت "):
                            query = text.replace("يوت ", "", 1).strip()
                            if query:
                                bg(search_and_download_audio, chat_id, query)
                        else:
                            bg(ai_chat, chat_id, text)

                    elif "message" in update and "location" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        if str(chat_id) in bot_state["banned_users"] or not bot_state["bot_active"]:
                            continue
                        from web_ui import register_user
                        register_user(chat_id, update["message"]["from"])
                        lc = update["message"]["location"]
                        bg(set_location_gps, chat_id, lc.get("latitude"), lc.get("longitude"))

                    elif "message" in update and "document" in update["message"] and str(update["message"]["chat"]["id"]) in upload_sessions:
                        dm = update["message"]
                        dcid = dm["chat"]["id"]
                        if str(dcid) in bot_state["banned_users"] or "hosting" not in bot_state["admins"].get(str(dcid), []):
                            upload_sessions.pop(str(dcid), None)
                            continue
                        bg(host_handle_document, dcid, dm["document"])

                    elif "message" in update and ("photo" in update["message"] or str((update["message"].get("document") or {}).get("mime_type", "")).startswith("image/")):
                        pmsg = update["message"]
                        chat_id = pmsg["chat"]["id"]
                        if str(chat_id) in bot_state["banned_users"] or not bot_state["bot_active"]:
                            continue
                        if not feature_on("vision"):
                            send_message(chat_id, "⚠️ ميزة الصور معطّلة حالياً.")
                            continue
                        if not rate_ok_v2(chat_id):
                            send_message(chat_id, "⏳ تمهّل قليلاً.")
                            continue
                        from web_ui import register_user
                        register_user(chat_id, pmsg["from"])
                        img_id = pmsg["photo"][-1]["file_id"] if "photo" in pmsg else pmsg["document"]["file_id"]
                        cap = (pmsg.get("caption") or "").strip()
                        vcost = cfg_int("vision_cost", 2)
                        if cap:
                            lowcap = cap.lstrip("/").strip()
                            if lowcap.startswith(("نص", "استخراج")):
                                vmode = "ocr"
                            elif lowcap.startswith(("ترجم", "ترجمة")):
                                vmode = "translate"
                            elif lowcap.startswith(("حلل", "تحليل", "وصف")):
                                vmode = "analyze"
                            else:
                                vmode = "ask"
                            bg(process_image, chat_id, img_id, vmode, cap if vmode == "ask" else "")
                        else:
                            ifid = uuid.uuid4().hex[:10]
                            from ai_features import pending_images
                            pending_images[ifid] = (img_id, time.time())
                            vkb = {"inline_keyboard": [
                                [{"text": "📝 استخراج النص", "callback_data": f"vo|{ifid}|ocr"}, {"text": "🔍 تحليل الصورة", "callback_data": f"vo|{ifid}|analyze"}],
                                [{"text": "🌐 نص + ترجمة", "callback_data": f"vo|{ifid}|translate"}]]}
                            send_message(chat_id, f"🖼️ <b>استلمت الصورة!</b>\nاختر ما تريد ({vcost} نقاط):", reply_markup=json.dumps(vkb))

                    elif "callback_query" in update:
                        callback = update["callback_query"]
                        chat_id = callback["message"]["chat"]["id"]
                        data = callback["data"]
                        _ack = {"callback_query_id": callback["id"]}
                        if data.startswith("fr|"):
                            _ack["text"] = "⏳ جاري استخراج الفريم..."
                        TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", json=_ack, timeout=5)
                        if str(chat_id) in bot_state["banned_users"]:
                            continue

                        if data.startswith("adm|"):
                            handle_acer_callback(chat_id, data)
                            continue

                        if not bot_state["bot_active"]:
                            continue

                        if data.startswith("acc|"):
                            bg(account_callback, chat_id, data)
                            continue

                        if data.startswith("srch|"):
                            bg(handle_search_callback, chat_id, data)
                            continue

                        if data == "my_points":
                            send_message(chat_id, points_card(chat_id))
                        elif data == "prayer":
                            bg(show_prayer, chat_id)
                        elif data == "pr_adhan":
                            bg(toggle_adhan, chat_id)
                        elif data == "pr_loc":
                            ask_location(chat_id)
                        elif data == "pr_method":
                            show_methods(chat_id)
                        elif data.startswith("pm|"):
                            bg(set_method, chat_id, data.split("|", 1)[1])
                        elif data == "occ":
                            bg(show_occasions, chat_id)
                        elif data == "rem_help":
                            send_message(chat_id, REM_HELP)
                        elif data == "rem_list":
                            list_reminders(chat_id)
                        elif data.startswith("rc|"):
                            cancel_reminder(chat_id, data.split("|", 1)[1])
                        elif data == "song":
                            bg(random_song, chat_id)
                        elif data == "cmds":
                            send_message(chat_id, COMMANDS_HELP)
                        elif data == "cancel_dl":
                            send_message(chat_id, "❌ تم الإلغاء.")
                        elif data.startswith("dl_file|"):
                            fid = data.split("|", 1)[1]
                            u = get_url(fid)
                            if u:
                                from config import pending_files
                                pending_files.pop(fid, None)
                                bg(download_and_send_file, chat_id, u)
                            else:
                                send_message(chat_id, "⚠️ انتهت صلاحية الرابط.")
                        elif data.startswith("dl|"):
                            fid = data.split("|", 1)[1]
                            u = get_url(fid)
                            if u:
                                if _is_anime_or_direct_media_link(u):
                                    bg(inspect_direct_url, chat_id, u)
                                else:
                                    kb = {"inline_keyboard": [
                                        [{"text": "📺 360p", "callback_data": f"dq|{fid}|360"}, {"text": "📺 480p", "callback_data": f"dq|{fid}|480"}],
                                        [{"text": "📺 720p", "callback_data": f"dq|{fid}|720"}, {"text": "📺 1080p", "callback_data": f"dq|{fid}|1080"}],
                                        [{"text": "🎵 صوت كامل", "callback_data": f"dq|{fid}|a"}, {"text": "✂️ مقطع صوتي (من-إلى)", "callback_data": f"tr|{fid}"}]]}
                                    send_message(chat_id, "🎞️ <b>اختر الجودة:</b>", reply_markup=json.dumps(kb))
                            else:
                                send_message(chat_id, "⚠️ انتهت الصلاحية.")
                        elif data.startswith("dq|"):
                            bits = data.split("|")
                            u = get_url(bits[1]) if len(bits) == 3 else None
                            qk = bits[2] if len(bits) == 3 and bits[2] in ("a", "360", "480", "720", "1080") else "720"
                            if u:
                                bg(download_and_send_video, chat_id, u, qk)
                            else:
                                send_message(chat_id, "⚠️ انتهت الصلاحية.")
                        elif data.startswith("ai|"):
                            u = get_url(data.split("|", 1)[1])
                            if u:
                                bg(ai_explain, chat_id, u)
                            else:
                                send_message(chat_id, "⚠️ انتهت الصلاحية.")
                        elif data.startswith("tr|"):
                            fid = data.split("|", 1)[1]
                            u = get_url(fid)
                            if u:
                                trim_sessions[str(chat_id)] = {"url": u, "t": time.time()}
                                send_message(chat_id, "✂️ <b>تحميل مقطع صوتي من-إلى</b>\n\nاكتب البداية والنهاية بهذا الشكل:\n<code>1:25 - 3:40</code>")
                            else:
                                send_message(chat_id, "⚠️ انتهت الصلاحية.")
            time.sleep(0.25)
        except Exception as e:
            print("bot_loop:", e)
            time.sleep(3)


if __name__ == "__main__":
    purge_downloads_dir(0)
    fetch_bot_username()
    print(f"🤖 البوت: @{BOT_USERNAME}" if BOT_USERNAME else "⚠️ تعذر جلب اسم البوت")

    threading.Thread(target=bot_loop, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    threading.Thread(target=backup_loop, daemon=True).start()
    try:
        os.nice(10)
    except Exception:
        pass
    threading.Thread(target=db_flusher, daemon=True).start()
    atexit.register(flush_db)
    atexit.register(lambda: purge_downloads_dir(0))

    host_restore()
    try:
        signal.signal(signal.SIGTERM, lambda *a: (purge_downloads_dir(0), host_shutdown(), flush_db(), os._exit(0)))
    except Exception:
        pass

    print("=" * 50)
    print("✅ النظام المتكامل يعمل")
    print("=" * 50)
    run_dashboard()
