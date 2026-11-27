# ==========================================
# الجزء 3: media_downloader.py
# مسؤول عن تتبع روابط الخوادم (megamax, mega, mediafire, gofile, pixeldrain...)،
# تنزيل الفيديو أو الملف، التحقق من حجمه الفعلي لتفادي الإعلانات، إرساله للتيليغرام، وحذفه فوراً
# ==========================================
import os
import re
import io
import time
import json
import zipfile
from html import unescape
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from config import TELEGRAM_TOKEN, BROWSER_HEADERS
from telegram_api import send_message, TG_SESSION
from utils import esc, log_error, store_url, safe_url, safe_name
from search_core import (
    PIXELDRAIN_API_BASE,
    is_ad_media_url,
    is_404_page,
    is_waf_blocked,
    get_cookie_for_url,
    create_status_msg,
    update_status_msg,
    build_session,
    stealth_get,
    fmt_size_bytes,
)
from anime_sites import is_pixeldrain_url, extract_pixeldrain_ref

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from curl_cffi import requests as cffi_requests
except Exception:
    cffi_requests = None


def _resolve_gofile_direct(url: str, sess) -> str:
    """يستخرج رابط التحميل المباشر من gofile.io عبر API الرسمي العام."""
    m = re.search(r"gofile\.io/d/([A-Za-z0-9_-]+)", url, flags=re.I)
    if not m:
        return url
    content_id = m.group(1)
    try:
        acc_r = sess.post("https://api.gofile.io/accounts", timeout=10)
        token = (acc_r.json() or {}).get("data", {}).get("token")
        if not token:
            return url
        cr = sess.get(
            f"https://api.gofile.io/contents/{content_id}?wt=4fd6sg89d7s6",
            headers={"Authorization": f"Bearer {token}"},
            timeout=12,
        )
        children = (cr.json() or {}).get("data", {}).get("children", {})
        for _, item in children.items():
            link = item.get("link")
            if link:
                return link
    except Exception:
        pass
    return url


def _resolve_mediafire_direct(url: str, sess, headers: dict) -> str:
    """يستخرج رابط التحميل المباشر من صفحة mediafire.com."""
    try:
        r = sess.get(url, headers=headers, timeout=15, allow_redirects=True)
        html = r.text or ""
        m = re.search(r'href="(https?://download\d+\.mediafire\.com/[^"]+)"', html, flags=re.I)
        if m:
            return unescape(m.group(1))
    except Exception:
        pass
    return url


def _resolve_uqload_direct(url: str, sess, headers: dict) -> str:
    """يستخرج رابط mp4 المباشر من مشغل uqload."""
    try:
        r = sess.get(url, headers=headers, timeout=15, allow_redirects=True)
        html = r.text or ""
        m = re.search(r'sources\s*:\s*\[\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']', html, flags=re.I)
        if m:
            return unescape(m.group(1))
    except Exception:
        pass
    return url


def resolve_links_page_target(link_url, uid=None, referer_url=None, session=None):
    sess = session or build_session()
    headers = {
        **BROWSER_HEADERS,
        "Referer": referer_url or link_url,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    }
    ck = get_cookie_for_url(uid, link_url) if uid else ""
    if ck:
        headers["Cookie"] = ck

    low_in = (link_url or "").lower()
    if "gofile.io/d/" in low_in:
        return _resolve_gofile_direct(link_url, sess), None
    if "mediafire.com/" in low_in:
        return _resolve_mediafire_direct(link_url, sess, headers), None
    if "uqload." in low_in:
        return _resolve_uqload_direct(link_url, sess, headers), None

    time.sleep(1.5)

    r = sess.get(link_url, headers=headers, timeout=25, allow_redirects=True)
    final_u = str(getattr(r, "url", link_url) or link_url)
    ctype = (r.headers.get("Content-Type") or "").lower()

    if "text/html" not in ctype:
        return final_u, r

    html = r.text or ""
    candidates = []

    def _add_cand(u_raw):
        fu = urljoin(final_u, unescape((u_raw or "").strip()))
        if not fu.startswith(("http://", "https://")) or is_ad_media_url(fu):
            return
        if "/links/" in fu.lower() and fu == link_url:
            return
        if fu not in candidates:
            candidates.append(fu)

    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        for form in soup.find_all("form"):
            act = form.get("action") or ""
            if act:
                method = (form.get("method") or "get").lower()
                payload = {inp.get("name"): inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
                try:
                    fr = (
                        sess.post(urljoin(final_u, act), data=payload, headers={**headers, "Referer": final_u}, timeout=20, allow_redirects=True)
                        if method == "post"
                        else sess.get(urljoin(final_u, act), params=payload, headers={**headers, "Referer": final_u}, timeout=20, allow_redirects=True)
                    )
                    f_after = str(getattr(fr, "url", "") or "")
                    if f_after and f_after != final_u and not is_ad_media_url(f_after):
                        return f_after, fr
                    for a2 in BeautifulSoup(fr.text or "", "html.parser").find_all("a", href=True):
                        h2 = urljoin(f_after or final_u, a2["href"].strip())
                        if any(k in h2.lower() for k in ("mega.nz", "drive.google", "pixeldrain", "mediafire", "gofile", "/download/", ".mp4", ".mkv")):
                            return h2, None
                except Exception:
                    pass

        for a in soup.find_all("a", href=True):
            h = a["href"].strip()
            txt = a.get_text(" ", strip=True)
            if any(k in h.lower() for k in ("mega.nz", "drive.google", "pixeldrain", "mediafire", "gofile", "vikingfile", "workupload", "/download/", ".mp4", ".mkv")) or "متابع" in txt or "continue" in txt.lower():
                _add_cand(h)

    for m in re.findall(r"""https?://(?:mega\.nz/file/[^\s"'<>\\]+|drive\.google\.com/[^\s"'<>\\]+|pixeldrain\.com/[^\s"'<>\\]+|mediafire\.com/[^\s"'<>\\]+|gofile\.io/[^\s"'<>\\]+|[^\s"'<>\\]+(?:/download/[^\s"'<>\\]+|\.mp4|\.mkv|\.webm|\.m3u8))""", html, flags=re.I):
        _add_cand(m)

    for cand in candidates:
        low_c = cand.lower()
        if "mega.nz/file/" in low_c:
            return cand, None
        if "gofile.io/d/" in low_c:
            return _resolve_gofile_direct(cand, sess), None
        if "mediafire.com/" in low_c:
            return _resolve_mediafire_direct(cand, sess, headers), None
        if "uqload." in low_c:
            return _resolve_uqload_direct(cand, sess, headers), None
        try:
            cr = sess.get(cand, headers={**headers, "Referer": final_u}, timeout=25, allow_redirects=True, stream=True)
            if "text/html" not in (cr.headers.get("Content-Type") or "").lower():
                return str(getattr(cr, "url", cand) or cand), cr
            cr.close()
        except Exception:
            continue

    return final_u, None


def download_signed_video_and_send(chat_id, dl_url, referer_url=None, quality_label="", expected_duration=""):
    if not safe_url(dl_url):
        send_message(chat_id, "⛔ رابط غير مسموح.")
        return
    dur_hint = f"\n⏱️ مدة الحلقة المسجلة بالموقع: <b>{esc(expected_duration)}</b>" if expected_duration else ""
    st_id = create_status_msg(
        chat_id,
        f"🔍 <b>[1/3] جاري تتبع الرابط وفحص حجم الملف الفعلي ({esc(quality_label or 'مباشر')})...</b>{dur_hint}",
    )
    os.makedirs("downloads", exist_ok=True)
    out_path = None
    sess = build_session()
    try:
        resolved_url, stream_resp = resolve_links_page_target(dl_url, uid=chat_id, referer_url=referer_url, session=sess)

        if any(h in (resolved_url or "").lower() for h in ("mega.nz/", "vikingfile.com/", "workupload.com/", "megamax.me/")) and stream_resp is None:
            update_status_msg(
                chat_id,
                st_id,
                f"✅ <b>تم تجاوز الإعلانات وصفحة التحويل والوصول لرابط الخادم:</b>\n"
                f"🎞️ الخادم/الجودة: <b>{esc(quality_label or 'HD')}</b>{dur_hint}\n"
                f"🔗 {esc(resolved_url)}",
            )
            return

        if stream_resp is None:
            headers = {**BROWSER_HEADERS, "Referer": referer_url or dl_url}
            ck = get_cookie_for_url(chat_id, resolved_url)
            if ck:
                headers["Cookie"] = ck
            stream_resp = sess.get(resolved_url, headers=headers, timeout=45, allow_redirects=True, stream=True)

        if is_waf_blocked(stream_resp):
            stream_resp.close()
            update_status_msg(chat_id, st_id, f"🛡️ فشل التحقق (HTTP {stream_resp.status_code}) — أضف كوكيز للموقع.")
            return
        stream_resp.raise_for_status()

        total_bytes = int(stream_resp.headers.get("Content-Length") or 0)
        real_size_str = fmt_size_bytes(total_bytes)

        # رفض فوري لأي فيديو حجمه أقل من 4 MB لأنه غالباً إعلان قصير وليس حلقة كاملة
        if 0 < total_bytes < 4_000_000:
            stream_resp.close()
            update_status_msg(
                chat_id,
                st_id,
                f"🚫 <b>تم حجب الملف تلقائياً!</b>\n"
                f"📦 الحجم الفعلي من السيرفر: <b>{esc(real_size_str)}</b> (صغير جداً، يبدو كإعلان وليس حلقة كاملة).",
            )
            return

        cd = stream_resp.headers.get("Content-Disposition", "")
        m_fn = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', cd, flags=re.I)
        raw_name = m_fn.group(1).strip() if m_fn else (os.path.basename(urlparse(resolved_url).path) or f"episode_{quality_label or 'video'}.mp4")
        fname = safe_name(raw_name, f"episode_{chat_id}.mp4")
        if not any(fname.lower().endswith(ext) for ext in (".mp4", ".webm", ".mkv", ".mov")):
            fname += ".mp4"
        out_path = os.path.join("downloads", f"{chat_id}_{int(time.time())}_{fname}")

        downloaded = 0
        last_t = time.time()
        size_banner = f" | الحجم الفعلي: <b>{esc(real_size_str)}</b>" if real_size_str else ""
        update_status_msg(chat_id, st_id, f"⬇️ <b>[2/3] جاري تنزيل الحلقة ({esc(quality_label or 'فيديو')}{size_banner})...</b>{dur_hint}")

        with open(out_path, "wb") as f:
            for chunk in stream_resp.iter_content(chunk_size=1024 * 512):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if (time.time() - last_t) >= 2.0:
                    last_t = time.time()
                    dl_mb = downloaded / (1024 * 1024)
                    if total_bytes > 0:
                        tot_mb = total_bytes / (1024 * 1024)
                        pct = min(100, int((downloaded / total_bytes) * 100))
                        update_status_msg(
                            chat_id,
                            st_id,
                            f"⬇️ <b>[2/3] جاري تنزيل الحلقة ({pct}%)...</b>\n"
                            f"📦 {dl_mb:.1f} MB / {tot_mb:.1f} MB{dur_hint}",
                        )
                    else:
                        update_status_msg(chat_id, st_id, f"⬇️ <b>[2/3] جاري تنزيل الحلقة...</b>\n📦 {dl_mb:.1f} MB{dur_hint}")
        stream_resp.close()

        actual_bytes = os.path.getsize(out_path)
        if actual_bytes < 4_000_000:
            update_status_msg(
                chat_id,
                st_id,
                f"🚫 <b>تم إلغاء الإرسال:</b> حجم الملف المحمّل ({fmt_size_bytes(actual_bytes)}) صغير جداً ويبدو أنه إعلان.",
            )
            return

        size_mb = actual_bytes / (1024 * 1024)
        update_status_msg(chat_id, st_id, f"📤 <b>[3/3] جاري إرسال الحلقة كفيديو ({size_mb:.1f} MB)...</b>")
        with open(out_path, "rb") as f:
            resp_tg = TG_SESSION.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                data={
                    "chat_id": chat_id,
                    "caption": f"🎬 <b>{esc(fname)}</b>\n🎞️ الجودة: <b>{esc(quality_label or 'HD')}</b> | 📦 الحجم: <b>{size_mb:.1f} MB</b>",
                    "parse_mode": "HTML",
                    "supports_streaming": True,
                },
                files={"video": f},
                timeout=600,
            )
        if resp_tg.status_code != 200 or not resp_tg.json().get("ok"):
            update_status_msg(
                chat_id,
                st_id,
                f"⚠️ تعذّر رفع الفيديو إلى تيليغرام ({size_mb:.1f} MB — الحد الأقصى لبوتات تيليغرام 50 MB).\n"
                f"🔗 <b>رابط التحميل المباشر:</b>\n{esc(resolved_url)}",
            )
            return
        update_status_msg(chat_id, st_id, f"✅ <b>تم إرسال الحلقة كفيديو بنجاح!</b> ({size_mb:.1f} MB)")
    except Exception as e:
        log_error(chat_id, "signed_video_dl", e, dl_url)
        update_status_msg(chat_id, st_id, f"❌ <b>تعذّر تحميل الفيديو:</b> <code>{esc(str(e)[:120])}</code>")
    finally:
        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass


def fetch_chapter_content(url, quality="med", uid=None, status_msg_id=None, session=None):
    r = stealth_get(url, uid=uid, referer=url, timeout=12, status_msg_id=status_msg_id, session=session)
    if is_waf_blocked(r):
        raise RuntimeError(f"الموقع محمي ضد البوتات (HTTP {r.status_code}) — أضف كوكيز المتصفح للموقع")
    if is_404_page(r, html=getattr(r, "text", "") or ""):
        raise RuntimeError("الصفحة غير موجودة (404)")
    r.raise_for_status()
    html = r.text
    title = url
    paragraphs = []
    img_urls = []

    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        if is_404_page(r, title=title, html=html):
            raise RuntimeError("الصفحة غير موجودة (404)")
        for bad in soup(["script", "style", "nav", "header", "footer", "aside"]):
            bad.decompose()
        for img in soup.find_all("img"):
            src = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-original")
                or img.get("src")
                or ""
            )
            full = urljoin(url, src.strip())
            low = full.lower()
            if full.startswith("http") and not is_ad_media_url(full) and not any(x in low for x in ("logo", "icon", "avatar", "banner", "ads", "sprite", "svg", "404")):
                img_urls.append(full)
        for p in soup.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if len(txt) >= 35:
                paragraphs.append(txt)
        if not paragraphs:
            body_txt = soup.get_text("\n", strip=True)
            paragraphs = [line.strip() for line in body_txt.splitlines() if len(line.strip()) >= 35]
    else:
        tm = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if tm:
            title = unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
        if is_404_page(r, title=title, html=html):
            raise RuntimeError("الصفحة غير موجودة (404)")
        for src in re.findall(r'<img[^>]+(?:data-src|data-lazy-src|src)=["\']([^"\']+)["\']', html, re.I):
            full = urljoin(url, src.strip())
            if full.startswith("http") and not is_ad_media_url(full) and "404" not in full.lower():
                img_urls.append(full)
        cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.I | re.S)
        cleaned = re.sub(r"<[^>]+>", "\n", cleaned)
        paragraphs = [unescape(x).strip() for x in cleaned.splitlines() if len(unescape(x).strip()) >= 35]

    seen_i = set()
    uniq_imgs = []
    for u in img_urls:
        if u not in seen_i:
            seen_i.add(u)
            uniq_imgs.append(u)

    return {
        "title": title[:140],
        "paragraphs": paragraphs[:80],
        "images": uniq_imgs[:70],
        "quality": quality,
    }


def _compress_image_bytes(raw_bytes, quality="med"):
    if not Image or quality == "orig":
        return raw_bytes, "jpg"
    try:
        im = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        max_w = 1100 if quality == "med" else 760
        jpeg_q = 82 if quality == "med" else 62
        if im.width > max_w:
            ratio = max_w / float(im.width)
            im = im.resize((max_w, int(im.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=jpeg_q, optimize=True)
        return buf.getvalue(), "jpg"
    except Exception:
        return raw_bytes, "jpg"


def parallel_download_images(img_urls, referer_url, uid, quality, st_id, prefix=""):
    total = len(img_urls)
    if total == 0:
        return []
    ck = get_cookie_for_url(uid, referer_url)
    base_headers = {
        **BROWSER_HEADERS,
        "Referer": referer_url,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if ck:
        base_headers["Cookie"] = ck

    def fetch_one(item_tuple):
        idx, img_u = item_tuple
        if is_ad_media_url(img_u):
            return idx, None, None
        try:
            if cffi_requests:
                ir = cffi_requests.get(img_u, headers=base_headers, impersonate="chrome", timeout=7, allow_redirects=True)
            else:
                ir = requests.get(img_u, headers=base_headers, timeout=7, allow_redirects=True)
            if ir.status_code == 200 and ir.content and len(ir.content) > 800:
                data_b, ext = _compress_image_bytes(ir.content, quality=quality)
                return idx, f"{prefix}{idx:03d}.{ext}", data_b
        except Exception:
            pass
        return idx, None, None

    results = []
    done_cnt = 0
    ok_cnt = 0
    fail_cnt = 0
    last_ui = time.time()

    update_status_msg(
        uid,
        st_id,
        f"📥 <b>[3/4] جاري سحب {total} صورة بالتوازي...</b>\n✅ نجح: 0 | ❌ فشل: 0",
    )

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_one, (i, u)) for i, u in enumerate(img_urls, 1)]
        for fut in as_completed(futures):
            idx, fname, data_b = fut.result()
            done_cnt += 1
            if fname and data_b:
                ok_cnt += 1
                results.append((idx, fname, data_b))
            else:
                fail_cnt += 1
            if (time.time() - last_ui) >= 1.5 or done_cnt == total:
                last_ui = time.time()
                update_status_msg(
                    uid,
                    st_id,
                    f"📥 <b>[3/4] جاري سحب الصور ({done_cnt}/{total})...</b>\n"
                    f"✅ نجح: <b>{ok_cnt}</b> | ❌ فشل: <b>{fail_cnt}</b>",
                )

    results.sort(key=lambda x: x[0])
    return [(fname, data_b) for _, fname, data_b in results]


def send_single_chapter(chat_id, url, quality="med"):
    if not safe_url(url):
        send_message(chat_id, "⛔ رابط غير مسموح.")
        return
    st_id = create_status_msg(chat_id, "🔍 <b>[1/4] جاري التحقق من الموقع...</b>")
    os.makedirs("downloads", exist_ok=True)
    out_path = None
    sess = build_session()
    try:
        ch = fetch_chapter_content(url, quality=quality, uid=chat_id, status_msg_id=st_id, session=sess)
        safe_t = safe_name(ch["title"], f"chapter_{chat_id}")
        saved_imgs = 0

        if ch["images"] and ("manga" in url.lower() or "chapter" in url.lower() or "فصل" in ch["title"]):
            packed_imgs = parallel_download_images(ch["images"], url, chat_id, quality, st_id)
            if packed_imgs:
                out_path = os.path.join("downloads", f"{chat_id}_{safe_t}.cbz")
                with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for fname, data_b in packed_imgs:
                        zf.writestr(fname, data_b)
                        saved_imgs += 1

        if not out_path:
            fid = store_url(url)
            update_status_msg(chat_id, st_id, "🎬 <b>اختر جودة الحلقة للتحميل المباشر أو اضغط سحب فيديو.</b>")
            send_message(
                chat_id,
                f"🎬 <b>{esc(ch['title'])}</b>\n🔗 {esc(url)}",
                reply_markup=json.dumps({"inline_keyboard": [[{"text": "🎬 سحب فيديو", "callback_data": f"dl|{fid}"}]]}),
            )
            return

        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        update_status_msg(chat_id, st_id, f"📤 <b>[4/4] جاري رفع الملف إلى تيليغرام ({size_mb:.2f} MB)...</b>")
        with open(out_path, "rb") as f:
            TG_SESSION.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                data={"chat_id": chat_id, "caption": f"📚 <b>{esc(ch['title'])}</b>\n🖼️ صور مجمّعة ({saved_imgs})", "parse_mode": "HTML"},
                files={"document": f},
                timeout=300,
            )
        update_status_msg(chat_id, st_id, f"✅ <b>اكتمل بنجاح!</b> ({saved_imgs} صورة | {size_mb:.2f} MB)")
    except Exception as e:
        log_error(chat_id, "chapter_dl", e, url)
        update_status_msg(chat_id, st_id, f"❌ <b>توقف السحب:</b> <code>{esc(str(e)[:120])}</code>")
    finally:
        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass


def merge_chapters_range(chat_id, base_url, start_ch, end_ch, quality="med", chapters_map=None):
    chapters_map = chapters_map or {}
    if start_ch > end_ch:
        start_ch, end_ch = end_ch, start_ch
    if (end_ch - start_ch) > 25:
        end_ch = start_ch + 25
        send_message(chat_id, "⚡ الحد الأقصى للدمج السريع 25 فصلاً في المرة الواحدة.")

    target_nums = [n for n in sorted(chapters_map.keys()) if start_ch <= n <= end_ch]
    if not target_nums:
        send_message(chat_id, "⚠️ لا توجد فصول مستخرجة ضمن هذا النطاق.")
        return

    st_id = create_status_msg(chat_id, f"🔍 <b>[1/4] جاري التحقق وجلب {len(target_nums)} فصل...</b>")
    os.makedirs("downloads", exist_ok=True)
    out_path = None
    sess = build_session()
    try:
        chapters_data = []
        total_imgs = 0
        for idx_c, num in enumerate(target_nums, 1):
            ch_url = chapters_map.get(num)
            if not ch_url or not safe_url(ch_url):
                continue
            update_status_msg(chat_id, st_id, f"📄 <b>[2/4] فحص الفصل {num} ({idx_c}/{len(target_nums)})...</b>")
            try:
                ch = fetch_chapter_content(ch_url, quality=quality, uid=chat_id, session=sess)
                ch["num"] = num
                chapters_data.append(ch)
                total_imgs += len(ch["images"])
            except Exception:
                continue

        if not chapters_data:
            update_status_msg(chat_id, st_id, "❌ تعذّر جلب محتوى الفصول المطلوبة.")
            return

        saved_imgs = 0
        if total_imgs > 0:
            out_path = os.path.join("downloads", f"{chat_id}_merged_{start_ch}_{end_ch}.cbz")
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for ch in chapters_data:
                    packed = parallel_download_images(ch["images"], base_url, chat_id, quality, st_id, prefix=f"ch_{ch['num']}_")
                    for fname, data_b in packed:
                        zf.writestr(fname, data_b)
                        saved_imgs += 1
            if saved_imgs == 0 and os.path.exists(out_path):
                os.remove(out_path)
                out_path = None

        if not out_path:
            out_path = os.path.join("downloads", f"{chat_id}_merged_{start_ch}_{end_ch}.html")
            sections = []
            for ch in chapters_data:
                if ch["paragraphs"]:
                    ps = "".join(f"<p>{esc(p)}</p>\n" for p in ch["paragraphs"])
                    sections.append(f"<hr><h2>الفصل {ch['num']} - {esc(ch['title'])}</h2>\n{ps}")
            if not sections:
                update_status_msg(chat_id, st_id, "❌ لم يتم العثور على صور أو نصوص قابلة للدمج.")
                return
            doc = (
                "<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>"
                f"<title>الفصول {start_ch}-{end_ch}</title>"
                "<style>body{font-family:sans-serif;max-width:780px;margin:24px auto;line-height:1.9;padding:0 14px;background:#111;color:#eee}</style>"
                f"</head><body><h1>مجموعة الفصول ({start_ch} - {end_ch})</h1>{''.join(sections)}</body></html>"
            )
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(doc)
            cap = f"📖 <b>تم دمج {len(sections)} فصل في ملف واحد</b>"
        else:
            cap = f"📚 <b>تم دمج الفصول المحددة</b>\n🖼️ صور مجمّعة ({saved_imgs}) | الدقة: {quality}"

        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        update_status_msg(chat_id, st_id, f"📤 <b>[4/4] جاري رفع الملف المدمج ({size_mb:.2f} MB)...</b>")
        with open(out_path, "rb") as f:
            TG_SESSION.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                data={"chat_id": chat_id, "caption": cap, "parse_mode": "HTML"},
                files={"document": f},
                timeout=300,
            )
        update_status_msg(chat_id, st_id, f"✅ <b>اكتمل الدمج والرفع بنجاح!</b> ({size_mb:.2f} MB)")
    except Exception as e:
        log_error(chat_id, "chapter_merge", e, base_url)
        update_status_msg(chat_id, st_id, f"❌ سبب الفشل أثناء الدمج: <code>{esc(str(e)[:120])}</code>")
    finally:
        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass


def download_direct_file_with_cookie(chat_id, url):
    if is_ad_media_url(url):
        send_message(chat_id, "⛔ تم حجب رابط إعلاني.")
        return
    low = (url or "").lower()
    if any(k in low for k in ("/links/", "/download/", "gofile.io", "mediafire.com", "uqload.", "mega.nz")):
        download_signed_video_and_send(chat_id, url, referer_url=url, quality_label="مباشر")
        return
    if is_pixeldrain_url(url):
        kind, pid = extract_pixeldrain_ref(url)
        if pid and kind != "list":
            url = f"{PIXELDRAIN_API_BASE}/file/{pid}"

    if not safe_url(url):
        send_message(chat_id, "⛔ رابط غير مسموح.")
        return
    st_id = create_status_msg(chat_id, "🔍 <b>[1/3] جاري التحقق من رابط الفيديو وفحص حجمه...</b>")
    os.makedirs("downloads", exist_ok=True)
    out_path = None
    try:
        r = stealth_get(url, uid=chat_id, referer=url, timeout=60, status_msg_id=st_id)
        if is_waf_blocked(r):
            update_status_msg(chat_id, st_id, f"🛡️ فشل التحقق (HTTP {r.status_code}) — أضف كوكيز للموقع.")
            return
        if is_404_page(r, html=getattr(r, "text", "") or ""):
            update_status_msg(chat_id, st_id, "⚠️ الصفحة أو الفيديو غير موجود (404).")
            return
        r.raise_for_status()
        actual_len = len(r.content or b"")
        if actual_len < 4_000_000:
            update_status_msg(
                chat_id,
                st_id,
                f"🚫 <b>تم الحجب تلقائياً:</b> حجم الملف ({fmt_size_bytes(actual_len)}) صغير جداً ويبدو أنه إعلان.",
            )
            return
        cd = r.headers.get("Content-Disposition", "")
        m_fn = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', cd, flags=re.I)
        raw_name = m_fn.group(1).strip() if m_fn else (os.path.basename(urlparse(url).path) or "episode.mp4")
        fname = safe_name(raw_name, f"episode_{chat_id}.mp4")
        if not any(fname.lower().endswith(ext) for ext in (".mp4", ".webm", ".mkv", ".mov")):
            fname += ".mp4"
        out_path = os.path.join("downloads", f"{chat_id}_{fname}")
        with open(out_path, "wb") as f:
            f.write(r.content)
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        update_status_msg(chat_id, st_id, f"📤 <b>[3/3] جاري إرسال الحلقة كفيديو ({size_mb:.2f} MB)...</b>")
        with open(out_path, "rb") as f:
            TG_SESSION.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                data={"chat_id": chat_id, "caption": f"🎬 <b>{esc(fname)}</b> | 📦 <b>{size_mb:.1f} MB</b>", "parse_mode": "HTML", "supports_streaming": True},
                files={"video": f},
                timeout=600,
            )
        update_status_msg(chat_id, st_id, f"✅ <b>تم إرسال الفيديو بنجاح</b> ({size_mb:.2f} MB)")
    except Exception as e:
        update_status_msg(chat_id, st_id, f"❌ تعذّر تحميل الفيديو: <code>{esc(str(e)[:120])}</code>")
    finally:
        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass