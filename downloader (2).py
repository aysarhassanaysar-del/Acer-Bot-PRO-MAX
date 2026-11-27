# ==========================================
# ملف: downloader.py
# ==========================================
# ==========================================
# ملف محرك التحميل والميديا (الأصلي الخاص بك)
# ==========================================
import os
import re
import glob
import time
import json
import random
import shutil
import subprocess
import threading
import yt_dlp
import requests
from datetime import datetime

from config import (bot_state, lock, TELEGRAM_TOKEN, YDL_BASE, YT_CLIENTS,
                    HAS_FFMPEG, MAX_DOWNLOAD, TG_LIMIT, BROWSER_HEADERS,
                    COOKIES_FILE)
from telegram_api import send_message, TG_SESSION, upload_media
from utils import (bg, esc, safe_url, safe_name, store_url, get_url, resolve_path,
                   explain_error, log_error, log_event, count_download, log_listen)
from points import charge, refund, get_points, points_bar, setting
from ai_features import ask_ai, feature_on


def _cleanup_paths(*paths):
    for p in paths:
        if not p:
            continue
        try:
            if os.path.isfile(p):
                os.remove(p)
        except Exception:
            pass


def _cleanup_user_files(chat_id):
    for p in glob.glob(f"downloads/{chat_id}_*") + glob.glob(f"downloads/frame_*"):
        _cleanup_paths(p)


def purge_downloads_dir(max_age_sec=0):
    if not os.path.isdir("downloads"):
        return
    now = time.time()
    for name in os.listdir("downloads"):
        p = os.path.join("downloads", name)
        try:
            if os.path.isfile(p) and (max_age_sec <= 0 or (now - os.path.getmtime(p)) > max_age_sec):
                os.remove(p)
        except Exception:
            pass


# تنظيف أي ملفات عالقة من جلسات سابقة عند تشغيل البوت
purge_downloads_dir(0)


# ============ أدوات yt-dlp الأساسية ============
def ydl_try(url, opts):
    clients = YT_CLIENTS if ("youtu" in url or url.startswith("ytsearch")) else [None]
    last = None
    for c in clients:
        o = dict(opts)
        if c:
            o["extractor_args"] = {"youtube": {"player_client": c}}
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=True)
                item = info["entries"][0] if info.get("entries") else info
                return item, ydl.prepare_filename(item)
        except Exception as e:
            last = e
    raise last


def ydl_info(url):
    clients = YT_CLIENTS if "youtu" in url else [None]
    last = None
    for c in clients:
        o = {**YDL_BASE, "skip_download": True, "socket_timeout": 8, "retries": 1}
        if c:
            o["extractor_args"] = {"youtube": {"player_client": c}}
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=False)
                return info["entries"][0] if info.get("entries") else info
        except Exception as e:
            last = e
    raise last


# ============ الأغنية العشوائية ============
SONG_QUERIES = ["أغاني عربية جديدة", "أغاني عراقية", "أغاني خليجية", "أغاني مصرية", "أغاني لبنانية", "أغاني هادئة",
                "أغاني حزينة", "أغاني طرب", "أغاني شبابية", "أغاني قديمة كلاسيك", "Arabic pop hits", "chill music", "top hits"]
song_busy = set()


def random_song(chat_id):
    uid = str(chat_id)
    if not feature_on("song"):
        send_message(chat_id, "⚠️ هذه الميزة معطّلة حالياً من الإدارة.")
        return
    if uid in song_busy:
        send_message(chat_id, "⏳ لديك أغنية قيد التحضير، انتظر قليلاً.")
        return
    cost = setting("song_cost")
    if not charge(uid, cost):
        send_message(chat_id, f"😅 <b>رصيدك لا يكفي!</b>\n\n💰 رصيدك: <b>{get_points(uid)}</b>\n🎲 سعر الأغنية: <b>{cost}</b>\n🎁 تحصل على +{setting('daily_bonus')} نقاط كل يوم 🌟")
        return
    song_busy.add(uid)
    ok = False
    try:
        send_message(chat_id, "🎲✨ جاري اختيار أغنية عشوائية لك...")
        with yt_dlp.YoutubeDL({**YDL_BASE, "extract_flat": True, "skip_download": True, "socket_timeout": 8}) as ydl:
            res = ydl.extract_info(f"ytsearch15:{random.choice(SONG_QUERIES)}", download=False)
        entries = []
        for e in (res.get("entries") or []):
            d = (e or {}).get("duration")
            if e and e.get("id") and (not d or 60 <= d <= 480):
                entries.append(e)
        if entries:
            pick = random.choice(entries)
            ok = download_and_send_video(chat_id, f"https://www.youtube.com/watch?v={pick['id']}", "a")
    except Exception as e:
        print("random_song:", e)
        log_error(chat_id, "song", e)
    finally:
        song_busy.discard(uid)
    if ok:
        send_message(chat_id, f"🎶🎲 <b>استمتع بالأغنية!</b> 🎲🎶\n\n💸 خُصم: <b>{cost}</b> نقاط\n💰 رصيدك الآن: <b>{get_points(uid)}</b>\n{points_bar(get_points(uid))}")
    else:
        refund(uid, cost)
        send_message(chat_id, f"❌ تعذّر تجهيز الأغنية.\n🔄 أُعيدت لك نقاطك (+{cost}) 💰")


# ============ إصلاح التحميل ============
ytdlp_status = {"running": False, "msg": ""}


def ytdlp_info():
    try:
        ver = yt_dlp.version.__version__
    except Exception:
        ver = "?"
    return {"version": ver, "running": ytdlp_status["running"], "msg": ytdlp_status["msg"]}


def cookies_info():
    if os.path.exists(COOKIES_FILE):
        return {"exists": True, "size": os.path.getsize(COOKIES_FILE),
                "updated": datetime.fromtimestamp(os.path.getmtime(COOKIES_FILE)).strftime("%Y-%m-%d %H:%M")}
    return {"exists": False}


def do_update_ytdlp():
    import sys
    ytdlp_status.update(running=True, msg="⏳ جاري التحديث...")
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], capture_output=True, text=True, timeout=300)
        tail = (r.stdout + r.stderr).strip().splitlines()
        ytdlp_status["msg"] = ("✅ تم — أعد تشغيل البوت لتفعيل الإصدار الجديد. " if r.returncode == 0 else "❌ فشل: ") + (tail[-1][:160] if tail else "")
    except Exception as e:
        ytdlp_status["msg"] = f"❌ {str(e)[:150]}"
    finally:
        ytdlp_status["running"] = False


# ============ غلاف عالي الدقة + فريمات الفيديو + مقاطع الصوت ============
cover_msgs = {}
trim_sessions = {}


def best_thumbnail(info):
    ths = info.get("thumbnails") or []
    try:
        real = [t for t in ths if (t.get("width") or 0) >= 640 and t.get("url")]
        if real:
            best = max(real, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
            return best["url"]
    except Exception:
        pass
    vid = info.get("id") or ""
    if vid and "youtu" in (info.get("webpage_url") or ""):
        for name in ("maxresdefault", "sddefault", "hqdefault"):
            u = f"https://i.ytimg.com/vi/{vid}/{name}.jpg"
            try:
                if requests.head(u, timeout=6, headers=BROWSER_HEADERS).status_code == 200:
                    return u
            except Exception:
                pass
    return info.get("thumbnail") or ""


def fmt_time(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def parse_time_text(text):
    t = str(text).translate(_AR_DIGITS).replace("−", "-").replace("‎", "").strip()
    m = re.match(r"^\s*(\d{1,3}):(\d{1,2})(?::(\d{1,2}))?\s*(?:-|–|—|‐|‑|‒|―|>|→|»| إلى | الى | إلي | الي | to )\s*(\d{1,3}):(\d{1,2})(?::(\d{1,2}))?\s*$", t, re.I)
    if not m:
        return None
    if m.group(3) is not None:
        t1 = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        t2 = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6))
    else:
        t1 = int(m.group(1)) * 60 + int(m.group(2))
        t2 = int(m.group(4)) * 60 + int(m.group(5))
    return t1, t2


def probe_height(path):
    if not HAS_FFMPEG:
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-select_stream", "v:0", "-show_entries",
                            "stream=height", "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return None


frame_src_cache = {}
HAS_ARIA2 = shutil.which("aria2c") is not None


def _speed_opts():
    if HAS_ARIA2:
        return {"external_downloader": "aria2c", "concurrent_fragment_downloads": 16,
                "external_downloader_args": {"aria2c": ["-x", "16", "-s", "16", "-j", "16", "-k", "1M", "--file-allocation=none", "--summary-interval=0"]}}
    return {"concurrent_fragment_downloads": 16, "hls_prefer_native": True}


def _frame_source(url, fid):
    c = frame_src_cache.get(fid)
    if c and time.time() - c["t"] < 1500:
        return c["direct"], c["dur"]
    clients = YT_CLIENTS if "youtu" in url else [None]
    last = None
    for cl in clients:
        o = {**YDL_BASE, "skip_download": True, "socket_timeout": 8}
        if cl:
            o["extractor_args"] = {"youtube": {"player_client": cl}}
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=False)
            fmts = info.get("formats") or []
            vids = [f for f in fmts if f.get("url") and (f.get("vcodec") or "none") not in ("none", "")]
            if not vids and info.get("url") and (info.get("vcodec") or "none") != "none":
                vids = [info]
            if not vids:
                raise RuntimeError("empty formats")
            best = max(vids, key=lambda f: (f.get("height") or 0))
            dur = int(info.get("duration") or 0)
            frame_src_cache[fid] = {"direct": best["url"], "dur": dur, "t": time.time(), "headers": best.get("http_headers") or info.get("http_headers") or {}}
            now = time.time()
            for k in [k for k, v in list(frame_src_cache.items()) if now - v["t"] > 1800]:
                frame_src_cache.pop(k, None)
            return best["url"], dur
        except Exception as e:
            last = e
    raise RuntimeError(f"لا توجد صيغة فيديو متاحة ({str(last)[:80]})")


def _cover_keyboard(fid, sec):
    return json.dumps({"inline_keyboard": [
        [{"text": "⏪ 30-", "callback_data": f"fr|{fid}|-30"}, {"text": "⏪ 10-", "callback_data": f"fr|{fid}|-10"},
         {"text": "⏩ 10+", "callback_data": f"fr|{fid}|10"}, {"text": "⏩ 30+", "callback_data": f"fr|{fid}|30"}],
        [{"text": "🎬 منتصف الفيديو", "callback_data": f"fr|{fid}|mid"}],
        [{"text": "📥 تحميل (اختر الجودة)", "callback_data": f"dl|{fid}"}],
        [{"text": "🎵 صوت كامل", "callback_data": f"dq|{fid}|a"}, {"text": "✂️ مقطع صوتي (من-إلى)", "callback_data": f"tr|{fid}"}],
        [{"text": "🤖 شرح AI", "callback_data": f"ai|{fid}"}]]})


def send_photo_with_buttons(chat_id, photo_url, caption, fid):
    st = cover_msgs.setdefault(fid, {"sec": 0, "dur": 0, "t": time.time()})
    st["caption"] = caption
    keyboard = _cover_keyboard(fid, st.get("sec", 0))
    ok = False
    if photo_url:
        try:
            r = TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                              json={"chat_id": chat_id, "photo": photo_url, "caption": caption,
                                    "parse_mode": "HTML", "reply_markup": keyboard}, timeout=12)
            ok = r.status_code == 200
            if ok:
                try:
                    st["msg_id"] = r.json()["result"]["message_id"]
                except Exception:
                    pass
        except Exception:
            pass
    if not ok:
        send_message(chat_id, caption, reply_markup=keyboard)


_frame_locks = {}


def _ffmpeg_frame(direct, headers, sec, out):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if str(direct).startswith("http"):
        h = {k.lower(): v for k, v in (headers or {}).items()}
        ua = h.pop("user-agent", None) or BROWSER_HEADERS["User-Agent"]
        extra = "".join(f"{k}: {v}\r\n" for k, v in h.items() if k in ("referer", "cookie", "origin", "accept-language"))
        cmd += ["-user_agent", ua]
        if extra:
            cmd += ["-headers", extra]
        cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "2", "-rw_timeout", "15000000"]
    cmd += ["-ss", str(sec), "-threads", "2", "-i", direct, "-frames:v", "1", "-q:v", "3", "-an", "-sn", "-dn", out]
    _cleanup_paths(out)
    r = subprocess.run(cmd, capture_output=True, timeout=45)
    ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
    tail = (r.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
    return ok, (tail[-1][:120] if tail else "")


def seek_frame(chat_id, fid, delta):
    if not HAS_FFMPEG:
        send_message(chat_id, "⚠️ استخراج الفريمات يتطلب ffmpeg على السيرفر.")
        return
    url = get_url(fid)
    if not url:
        send_message(chat_id, "⚠️ انتهت صلاحية الرابط. أرسله مرة أخرى.")
        return
    st = cover_msgs.setdefault(fid, {"sec": 0, "dur": 0, "t": time.time()})
    now = time.time()
    for k in [k for k, v in list(cover_msgs.items()) if now - v.get("t", 0) > 1800]:
        cover_msgs.pop(k, None)
    lock_ = _frame_locks.setdefault(fid, threading.Lock())
    if not lock_.acquire(blocking=False):
        if delta == "mid":
            st["pend_mid"] = True
        else:
            try:
                st["pend"] = st.get("pend", 0) + int(delta)
            except Exception:
                pass
        return
    out = None
    try:
        while True:
            direct, dur = _frame_source(url, fid)
            if dur:
                st["dur"] = dur
            if delta == "mid":
                st["sec"] = dur // 2 if dur else 30
            else:
                st["sec"] = max(0, min(st.get("sec", 0) + int(delta), (dur - 1) if dur else 10**6))
            st["t"] = time.time()
            os.makedirs("downloads", exist_ok=True)
            out = f"downloads/frame_{fid}_{st['sec']}.jpg"
            c = frame_src_cache.get(fid) or {}
            ok, err = _ffmpeg_frame(direct, c.get("headers"), st["sec"], out)
            if not ok:
                frame_src_cache.pop(fid, None)
                direct, dur = _frame_source(url, fid)
                c = frame_src_cache.get(fid) or {}
                ok, err = _ffmpeg_frame(direct, c.get("headers"), st["sec"], out)
            if not ok:
                raise RuntimeError(f"تعذّر استخراج الفريم {err}")
            kb = _cover_keyboard(fid, st["sec"])
            cap = f"🎞️ فريم عند {fmt_time(st['sec'])}" + (f" / {fmt_time(st['dur'])}" if st.get("dur") else "")
            done = False
            msg_id = st.get("msg_id")
            if msg_id:
                with open(out, "rb") as f:
                    er = TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageMedia",
                                         data={"chat_id": chat_id, "message_id": msg_id,
                                               "media": json.dumps({"type": "photo", "media": "attach://frame", "caption": cap, "parse_mode": "HTML"}),
                                               "reply_markup": kb}, files={"frame": f}, timeout=30)
                done = er.status_code == 200 or "not modified" in er.text
            if not done:
                with open(out, "rb") as f:
                    sr = TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                                         data={"chat_id": chat_id, "caption": cap, "parse_mode": "HTML", "reply_markup": kb},
                                         files={"photo": f}, timeout=30)
                if sr.status_code != 200:
                    raise RuntimeError("فشل إرسال الصورة")
                try:
                    st["msg_id"] = sr.json()["result"]["message_id"]
                except Exception:
                    pass
            _cleanup_paths(out)
            if st.pop("pend_mid", False):
                delta = "mid"
                continue
            pend = st.pop("pend", 0)
            if pend:
                delta = pend
                continue
            break
    except Exception as e:
        log_error(chat_id, "frame", e, url)
        send_message(chat_id, f"❌ تعذّر استخراج الفريم: <code>{esc(str(e)[:140])}</code>")
    finally:
        lock_.release()
        _cleanup_paths(out)


def _audio_direct(url):
    clients = YT_CLIENTS if "youtu" in url else [None]
    last = None
    for cl in clients:
        o = {**YDL_BASE, "skip_download": True, "socket_timeout": 8}
        if cl:
            o["extractor_args"] = {"youtube": {"player_client": cl}}
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=False)
            fmts = info.get("formats") or []
            auds = [f for f in fmts if f.get("url") and (f.get("acodec") or "none") not in ("none", "") and (f.get("vcodec") or "none") in ("none", "", None)]
            if not auds and info.get("url"):
                auds = [info]
            if not auds:
                raise RuntimeError("empty audio formats")
            best = max(auds, key=lambda f: (f.get("abr") or f.get("tbr") or 0))
            return best["url"], (info.get("title") or "مقطع صوتي"), int(info.get("duration") or 0)
        except Exception as e:
            last = e
    raise RuntimeError(f"لا توجد صيغة صوت متاحة ({str(last)[:80]})")


def trim_and_send_audio(chat_id, url, start_s, end_s):
    if not HAS_FFMPEG:
        send_message(chat_id, "⚠️ قصّ المقاطع يتطلب ffmpeg على السيرفر.")
        return
    send_message(chat_id, f"⏳ جاري تحميل المقطع الصوتي <b>{fmt_time(start_s)} → {fmt_time(end_s)}</b>...")
    os.makedirs("downloads", exist_ok=True)
    out = None
    fp = None
    try:
        out = f"downloads/{chat_id}_trim.mp3"
        try:
            direct, title, dur = _audio_direct(url)
            start_s = min(start_s, max(0, dur - 1)) if dur else start_s
            r = subprocess.run(["ffmpeg", "-y", "-ss", str(start_s), "-threads", "2", "-i", direct,
                                "-t", str(end_s - start_s), "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
                                "-ac", "2", out], capture_output=True, timeout=300)
            if r.returncode != 0 or not os.path.exists(out):
                raise RuntimeError("direct failed")
        except Exception:
            opts = {**YDL_BASE, **_speed_opts(), "format": "bestaudio/best",
                    "outtmpl": f"downloads/{chat_id}_%(id)s_src.%(ext)s",
                    "noplaylist": True, "max_filesize": MAX_DOWNLOAD}
            info, fp = ydl_try(url, opts)
            fp = resolve_path(fp)
            if not fp or not os.path.exists(fp):
                raise RuntimeError("تعذّر تحميل المصدر")
            r = subprocess.run(["ffmpeg", "-y", "-ss", str(start_s), "-i", fp,
                                "-t", str(end_s - start_s), "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
                                "-ac", "2", out], capture_output=True, timeout=600)
            if r.returncode != 0 or not os.path.exists(out):
                raise RuntimeError("فشل قصّ المقطع")
            title = info.get("title") or "مقطع صوتي"
        if os.path.getsize(out) > TG_LIMIT + 1024 * 1024:
            raise RuntimeError("المقطع أكبر من حد تلغرام (50MB)")
        if upload_media(chat_id, out, is_audio=True, caption=f"🎵 {esc(str(title)[:150])}\n\n✂️ المقطع: <b>{fmt_time(start_s)} → {fmt_time(end_s)}</b>"):
            count_download(chat_id, f"{url} [trim {start_s}-{end_s}]")
            log_listen(chat_id, str(title), url)
        else:
            send_message(chat_id, "❌ فشل رفع المقطع.")
    except Exception as e:
        log_error(chat_id, "trim", e, url)
        send_message(chat_id, f"❌ {esc(str(e)[:150])}")
    finally:
        _cleanup_paths(out, fp)
        _cleanup_user_files(chat_id)


def get_file_info(chat_id, url):
    if "play.google.com" in url:
        send_message(chat_id, "⚠️ روابط جوجل بلاي غير مدعومة.")
        return
    if not safe_url(url):
        send_message(chat_id, "⛔ رابط غير مسموح.")
        return
    send_message(chat_id, "🔍 جاري فحص الملف...")
    try:
        head = requests.head(url, allow_redirects=True, timeout=15, headers=BROWSER_HEADERS)
        if not safe_url(head.url):
            send_message(chat_id, "⛔ يحوّل لعنوان غير مسموح.")
            return
        if head.status_code != 200:
            send_message(chat_id, f"❌ رفض الموقع ({head.status_code}).")
            return
        size = int(head.headers.get("content-length", 0) or 0)
        if size > MAX_DOWNLOAD:
            send_message(chat_id, "⛔ أكبر من 1GB.")
            return
        mb = size / (1024 * 1024)
        size_str = f"{mb:.2f} MB" if size else "غير معروف"
        warn = "\n⚠️ <i>(أكبر من حد تلغرام 50MB — سأرسل لك رابط التحميل المباشر بدل الملف)</i>" if size > TG_LIMIT else ""
        cd = head.headers.get("content-disposition", "")
        raw = cd.split("filename=")[1].strip("\"'") if "filename=" in cd else url.split("/")[-1].split("?")[0]
        filename = safe_name(raw, "file.apk")
        fid = store_url(url)
        caption = f"📦 <b>معلومات الملف:</b>\n\n📄 <code>{esc(filename)}</code>\n📏 {size_str}{warn}\n\nهل ترغب في تحميله؟ 👇"
        keyboard = {"inline_keyboard": [[{"text": f"📥 تحميل ({size_str})", "callback_data": f"dl_file|{fid}"}],
                                        [{"text": "❌ إلغاء", "callback_data": "cancel_dl"}]]}
        TG_SESSION.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": caption, "parse_mode": "HTML", "reply_markup": json.dumps(keyboard)}, timeout=15)
    except Exception as e:
        send_message(chat_id, f"❌ خطأ: <code>{esc(str(e)[:100])}</code>")


def send_too_big(chat_id, url, size):
    send_message(chat_id, f"⚠️ حجم الملف ({size/(1024*1024):.1f}MB) أكبر من الحد الذي تسمح به تلغرام للبوتات (50MB)، لذلك لا يمكن إرساله هنا.\n"
                          f"🔗 حمّله مباشرة من الرابط:\n{esc(url)}")


def download_and_send_file(chat_id, url):
    if not safe_url(url):
        send_message(chat_id, "⛔ رابط غير مسموح.")
        return
    send_message(chat_id, "📥 جاري التحميل...")
    file_path = None
    try:
        os.makedirs("downloads", exist_ok=True)
        with requests.get(url, stream=True, timeout=60, headers=BROWSER_HEADERS) as r:
            r.raise_for_status()
            declared = int(r.headers.get("content-length", 0) or 0)
            if declared > TG_LIMIT:
                send_too_big(chat_id, url, declared)
                return
            cd = r.headers.get("content-disposition", "")
            raw = cd.split("filename=")[1].strip("\"'") if "filename=" in cd else url.split("/")[-1].split("?")[0]
            filename = safe_name(raw, f"file_{chat_id}.apk")
            file_path = os.path.join("downloads", f"{chat_id}_{filename}")
            total = 0
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1048576):
                    total += len(chunk)
                    if total > TG_LIMIT:
                        send_too_big(chat_id, url, max(total, declared))
                        return
                    f.write(chunk)
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with open(file_path, "rb") as f:
            res = TG_SESSION.post(tg_url, data={"chat_id": chat_id, "caption": f"📦 {filename}"}, files={"document": f}, timeout=300)
        if res.status_code == 200:
            count_download(chat_id, url)
        else:
            send_message(chat_id, "❌ فشل الرفع.")
    except Exception as e:
        log_error(chat_id, "file", e, url)
        send_message(chat_id, f"{explain_error(e)}\n<code>{esc(str(e)[:100])}</code>")
    finally:
        _cleanup_paths(file_path)
        _cleanup_user_files(chat_id)


def get_video_info(chat_id, url, user_data):
    if not safe_url(url):
        send_message(chat_id, "⛔ رابط غير مسموح.")
        return
    low = url.lower()
    if any(e in low for e in [".apk", ".zip", ".pdf", ".rar", ".exe", ".mp3", ".xapk"]) or "apkpure" in low or "apkmirror" in low:
        get_file_info(chat_id, url)
        return
    send_message(chat_id, "🔍 جاري تحليل الرابط...")
    try:
        info = ydl_info(url)
    except Exception as e:
        if "unsupported url" in str(e).lower():
            send_message(chat_id, "⚠️ ليس رابط فيديو معروفاً. جاري فحصه كملف مباشر...")
            get_file_info(chat_id, url)
            return
        log_error(chat_id, "info", e, url)
        send_message(chat_id, f"{explain_error(e)}\n<code>{esc(str(e)[:120])}</code>")
        return

    def fmt(n):
        return "—" if n is None else (f"{n/1e6:.1f}M" if n >= 1e6 else (f"{n/1e3:.1f}K" if n >= 1e3 else str(n)))

    d = int(info.get("duration") or 0)
    duration_str = f"{d//60}:{d%60:02d}" if d else "—"
    title = esc((info.get("title") or "بدون عنوان")[:200])
    uploader = esc((info.get("uploader") or "—")[:80])
    caption = (f"🌟 <b>{title}</b>\n👤 {uploader}\n👁️ {fmt(info.get('view_count'))} | 👍 {fmt(info.get('like_count'))}\n"
               f"⏱️ {duration_str} | 🌐 {esc(info.get('extractor_key') or '—')}\n\n<i>اضغط زر التحميل.</i>")
    fid = store_url(url)
    cover_msgs[fid] = {"sec": 0, "dur": int(info.get("duration") or 0), "t": time.time()}
    send_photo_with_buttons(chat_id, best_thumbnail(info), caption, fid)


QUALITIES = {"360": 360, "480": 480, "720": 720, "1080": 1080}


def _probe_duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip().splitlines()[0])
    except Exception:
        return None


def split_video_parts(path):
    size = os.path.getsize(path)
    dur = _probe_duration(path)
    if not dur or dur <= 0:
        return None
    base = os.path.splitext(path)[0]
    seg = max(3, int(dur * (TG_LIMIT / size) * 0.80))
    faststart = True
    for _ in range(6):
        for old in glob.glob(glob.escape(base) + "_part*.mp4"):
            _cleanup_paths(old)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-map", "0:v:0", "-map", "0:a?",
               "-c", "copy", "-f", "segment", "-segment_time", str(seg), "-reset_timestamps", "1"]
        if faststart:
            cmd += ["-segment_format_options", "movflags=+faststart"]
        cmd += [base + "_part%03d.mp4"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=900)
        except Exception:
            return None
        parts = sorted(glob.glob(glob.escape(base) + "_part*.mp4"))
        if r.returncode != 0:
            if faststart:
                faststart = False
                continue
            return None
        if parts and all(os.path.getsize(x) <= TG_LIMIT for x in parts):
            return parts
        seg = max(3, int(seg * 0.7))
    for old in glob.glob(glob.escape(base) + "_part*.mp4"):
        _cleanup_paths(old)
    return None


def download_and_send_video(chat_id, url, quality="720"):
    audio_only = (quality == "a")
    req_q = quality if quality in QUALITIES else "720"
    label = "صوت" if audio_only else f"{req_q}p"
    if audio_only and not feature_on("audio"):
        send_message(chat_id, "⚠️ تحميل الصوت معطّل حالياً من الإدارة.")
        return False
    send_message(chat_id, f"⏳ جاري التحميل ({label})...")
    os.makedirs("downloads", exist_ok=True)
    if audio_only:
        ladder = ["a"]
    elif HAS_FFMPEG:
        ladder = [req_q]
    else:
        ladder = [q for q in ("1080", "720", "480", "360") if int(q) <= int(req_q)]
    file_path = None
    ok = False
    last_err = None
    info = None
    used = req_q
    parts = []
    try:
        outtmpl = f"downloads/{chat_id}_%(id)s.%(ext)s"
        for qk in ladder:
            if audio_only:
                opts = {**YDL_BASE, **_speed_opts(), "format": "bestaudio[filesize<?50M]/bestaudio/best", "outtmpl": outtmpl, "noplaylist": True, "max_filesize": TG_LIMIT + 1024 * 1024}
                if HAS_FFMPEG:
                    opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
            else:
                h = QUALITIES.get(qk, 720)
                if HAS_FFMPEG:
                    fmt = f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/best"
                else:
                    fmt = f"best[ext=mp4][height<={h}][filesize<?50M]/best[ext=mp4][height<={h}]/best[height<={h}]/best"
                opts = {**YDL_BASE, **_speed_opts(), "format": fmt, "outtmpl": outtmpl, "noplaylist": True, "max_filesize": (MAX_DOWNLOAD if HAS_FFMPEG else TG_LIMIT + 1024 * 1024)}
                if HAS_FFMPEG:
                    opts["merge_output_format"] = "mp4"
            try:
                info, fp = ydl_try(url, opts)
            except Exception as e:
                last_err = e
                continue
            fp = resolve_path(fp)
            if not fp:
                last_err = RuntimeError("الملف أكبر من 50MB أو لم يُحمَّل")
                continue
            if os.path.getsize(fp) > TG_LIMIT + 1024 * 1024 and not (HAS_FFMPEG and not audio_only):
                _cleanup_paths(fp)
                last_err = RuntimeError("larger than 50MB")
                continue
            file_path = fp
            used = qk
            break
        if not file_path:
            raise last_err or RuntimeError("تعذّر التحميل")
        if not audio_only:
            label = f"{used}p"
        note = "\n⬇️ خُفّضت الجودة تلقائياً لتناسب حد 50MB." if (not audio_only and used != req_q) else ""
        if not audio_only:
            actual_h = probe_height(file_path)
            if actual_h:
                label = f"{actual_h}p"
                if actual_h < int(used):
                    note += f"\n⚠️ الجودة الفعلية للمصدر {actual_h}p (أقل من المطلوبة {used}p)."
        title = esc((info.get("title") or "ملف")[:200])
        icon = "🎵" if audio_only else "🎬"
        if (not audio_only) and os.path.getsize(file_path) > TG_LIMIT:
            mb = os.path.getsize(file_path) / (1024 * 1024)
            send_message(chat_id, f"✂️ حجم الفيديو {mb:.0f}MB أكبر من 50MB، جاري تقسيمه إلى أجزاء وإرسالها...")
            parts = split_video_parts(file_path)
            if not parts:
                raise RuntimeError("تعذّر تقسيم الفيديو إلى أجزاء")
            sent = 0
            for i, part in enumerate(parts, 1):
                if upload_media(chat_id, part, caption=f"{icon} {title}\n\n📦 الجزء {i}/{len(parts)} ({label})"):
                    sent += 1
                else:
                    send_message(chat_id, f"❌ فشل رفع الجزء {i}/{len(parts)}.")
                _cleanup_paths(part)
            if sent == len(parts):
                count_download(chat_id, f"{url} [{label} x{len(parts)}]")
                ok = True
        elif upload_media(chat_id, file_path, is_audio=audio_only, caption=f"{icon} {title}\n\n✅ ({label}){note}"):
            count_download(chat_id, f"{url} [{label}]")
            ok = True
            if audio_only:
                log_listen(chat_id, info.get("title") or "ملف", url)
        else:
            send_message(chat_id, "❌ فشل الرفع إلى تيليجرام.")
    except Exception as e:
        log_error(chat_id, "download", e, url)
        send_message(chat_id, f"{explain_error(e)}\n<code>{esc(str(e)[:120])}</code>")
    finally:
        _cleanup_paths(file_path, *parts)
        _cleanup_user_files(chat_id)
    return ok


def search_and_download_audio(chat_id, search_query):
    if not feature_on("audio"):
        send_message(chat_id, "⚠️ تحميل الأغاني معطّل حالياً من الإدارة.")
        return
    search_query = search_query[:100]
    send_message(chat_id, f"🔍 جاري البحث: <b>{esc(search_query)}</b>...")
    os.makedirs("downloads", exist_ok=True)
    file_path = None
    try:
        opts = {**YDL_BASE, **_speed_opts(), "format": "bestaudio[filesize<?50M]/bestaudio/best", "outtmpl": f"downloads/{chat_id}_%(id)s.%(ext)s", "noplaylist": True, "max_filesize": TG_LIMIT + 1024 * 1024}
        if HAS_FFMPEG:
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        video_info, file_path = ydl_try(f"ytsearch1:{search_query}", opts)
        file_path = resolve_path(file_path)
        if not file_path:
            raise RuntimeError("larger than 50MB")
        title = video_info.get("title") or "أغنية"
        if upload_media(chat_id, file_path, is_audio=True, caption=f"🎵 {esc(title[:200])}\n\n✅ استمتع!"):
            count_download(chat_id, search_query)
            log_listen(chat_id, title, f"https://youtu.be/{video_info.get('id', '')}")
        else:
            send_message(chat_id, "❌ فشل رفع الصوت.")
    except Exception as e:
        log_error(chat_id, "audio", e, search_query)
        send_message(chat_id, f"{explain_error(e)}\n<code>{esc(str(e)[:120])}</code>")
    finally:
        _cleanup_paths(file_path)
        _cleanup_user_files(chat_id)


HEAVY_SLOTS = threading.BoundedSemaphore(int(os.environ.get("MAX_HEAVY_JOBS", 3)))


def heavy(fn):
    def wrapper(chat_id, *a, **k):
        if not HEAVY_SLOTS.acquire(blocking=False):
            send_message(chat_id, "⏳ السيرفر مشغول بتحميلات أخرى، طلبك في الانتظار وسيبدأ تلقائياً...")
            HEAVY_SLOTS.acquire()
        try:
            return fn(chat_id, *a, **k)
        finally:
            HEAVY_SLOTS.release()
    wrapper.__name__ = fn.__name__
    return wrapper


download_and_send_video = heavy(download_and_send_video)
download_and_send_file = heavy(download_and_send_file)
search_and_download_audio = heavy(search_and_download_audio)


def ai_explain(chat_id, url):
    send_message(chat_id, "🧠 جاري التحليل...")
    try:
        title = ydl_info(url).get("title", "")
        reply = ask_ai(chat_id, "اشرح باختصار:\n" + title, is_explanation=True)
        log_event("ai_explain", chat_id, title)
        send_message(chat_id, f"🤖 {esc(reply)}")
    except Exception:
        send_message(chat_id, "❌ خطأ.")