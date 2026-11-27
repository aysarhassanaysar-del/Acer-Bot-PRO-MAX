# ==========================================
# الجزء 1: search_core.py
# مسؤول عن البحث، المحركات، الدومينات، والكوكيز، وتوحيد اسم الاستعلام بالذكاء الاصطناعي
# ==========================================
import os
import re
import time
import json
import asyncio
from urllib.parse import urlparse, quote
import requests
import yt_dlp
from duckduckgo_search import DDGS
from config import TELEGRAM_TOKEN, YDL_BASE, YT_CLIENTS, BROWSER_HEADERS
from telegram_api import send_message, TG_SESSION
from utils import esc, store_url

try:
    import cloudscraper
except Exception:
    cloudscraper = None

try:
    from curl_cffi import requests as cffi_requests
except Exception:
    cffi_requests = None

_LOCAL_URL_STORE = {}
_orig_store_url = store_url


def _store_url_safe(u):
    fid = _orig_store_url(u)
    if fid:
        _LOCAL_URL_STORE[str(fid)] = u
    return fid


def get_stored_url(fid):
    if not fid:
        return None
    if str(fid) in _LOCAL_URL_STORE:
        return _LOCAL_URL_STORE[str(fid)]
    return fid if str(fid).startswith(("http://", "https://")) else None


store_url = _store_url_safe

SEARCH_TIMEOUT = 8
search_sessions = {}
search_results_cache = {}
chapter_merge_sessions = {}
saved_user_domains = {}
user_domain_cookies = {}   # {uid: {domain: cookie_header_str}}
awaiting_cookie_for = {}   # {uid: domain}
_serper_key_idx = 0

_ENV_KEYS = [k.strip() for k in os.environ.get("SERPER_API_KEYS", "").split(",") if k.strip()]
SERPER_KEYS = _ENV_KEYS or [
    "b4631717b1ca67e92212356d35af58821957a7c5",
]

DEFAULT_PRIORITY_DOMAINS = ["pixeldrain.com"]
PIXELDRAIN_API_BASE = "https://pixeldrain.com/api"

PLATFORM_DOMAINS = {
    "all": [],
    "pd": ["pixeldrain.com"],
    "yt": ["youtube.com", "youtu.be"],
    "tt": ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"],
    "ig": ["instagram.com"],
    "x": ["x.com", "twitter.com"],
    "fb": ["facebook.com", "fb.watch"],
    "rd": ["reddit.com"],
    "pin": ["pinterest.com"],
}

PLATFORM_LABELS = {
    "all": "🌐 الكل + مواقع الأنمي",
    "pd": "📦 Pixeldrain (كرتون/أنمي/أفلام)",
    "yt": "🎬 يوتيوب",
    "tt": "🎵 تيك توك",
    "ig": "📸 إنستغرام",
    "x": "𝕏 إكس",
    "fb": "📘 فيسبوك",
    "rd": "💬 ريديت",
    "pin": "📌 بنترست",
}

SOCIAL_MODES = {"yt", "tt", "ig", "x", "fb"}

SEARCH_YDL_OPTS = {
    **YDL_BASE,
    "extract_flat": True,
    "skip_download": True,
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "nocheckcertificate": True,
    "socket_timeout": SEARCH_TIMEOUT,
    "retries": 1,
}

FILE_EXTS = (
    ".pdf", ".epub", ".cbz", ".cbr", ".zip", ".rar", ".7z", ".apk", ".xapk",
    ".mp3", ".m4a", ".wav", ".ogg", ".flac", ".doc", ".docx", ".txt", ".exe"
)
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".m3u8")
MANGA_KEYWORDS = (
    "manga", "manhwa", "manhua", "comic", "comics", "chapter", "chap",
    "hentai", "doujin", "مانجا", "مانهوا", "فصل", "الفصل"
)
NON_CONTENT_PATHS = (
    "/blog", "/ios", "/android", "/app", "/apps", "/privacy", "/terms",
    "/dmca", "/contact", "/about", "/login", "/register", "/faq", "/policy",
    "/updates", "/changelog", "/release-notes", "/404"
)
WAF_MARKERS = (
    "just a moment...",
    "cf-browser-verification",
    "challenge-platform",
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "ddos-guard",
)
AD_URL_MARKERS = (
    "ad", "ads", "adserver", "banner", "pop", "promo", "sponsor",
    "bc.game", "1xbet", "bet", "casino", "doubleclick", "googlesyndication",
    "taboola", "outbrain", "propeller", "adsterra", "size=adaptive",
    "preroll", "midroll", "postroll", "vast", "vpaid", "vip200mr",
    "popads", "popcash", "exoclick", "juicyads", "trafficjunky",
)


def is_ad_media_url(url: str) -> bool:
    low = (url or "").lower()
    if not low.startswith(("http://", "https://")):
        return True
    if any(m in low for m in AD_URL_MARKERS):
        return True
    if re.search(r"(?:^|[?&_])(?:w|width|h|height)=\d{2,3}(?:&|$)", low):
        return True
    return False


def clean_domain(raw_domain):
    d = (raw_domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/", 1)[0].strip()
    if d.startswith("site:"):
        d = d[5:].strip()
    if d.startswith("www."):
        d = d[4:]
    if not d or "." not in d or " " in d:
        return None
    return d


def is_404_page(resp, title="", html=""):
    final_url = str(getattr(resp, "url", "") or "").lower()
    path = (urlparse(final_url).path or "").lower()
    if getattr(resp, "status_code", 200) == 404 or path.endswith("/404") or "/404" in path:
        return True
    low_t = (title or "").lower()
    if "404" in low_t or "الصفحة غير موجودة" in low_t or "page not found" in low_t or "not found" in low_t:
        return True
    sample = (html or "")[:2000].lower()
    if "404 - الصفحة غير موجودة" in sample or "page not found" in sample:
        return True
    return False


def is_non_content_page(url: str, title: str = "") -> bool:
    path = (urlparse(url or "").path or "").lower()
    if any(path == p or path.startswith(p + "/") for p in NON_CONTENT_PATHS):
        return True
    low_t = (title or "").lower()
    if any(k in low_t for k in ("404", "الصفحة غير موجودة", "page not found", "أفضل 10 أنميات", "الترتيب العالمي", "سجل الإصدارات", "privacy policy", "terms of service", "dmca")):
        return True
    return False


def save_domain_for_user(uid, dom):
    dom = clean_domain(dom)
    if not dom or dom in DEFAULT_PRIORITY_DOMAINS:
        return
    lst = saved_user_domains.setdefault(str(uid), [])
    if dom in lst:
        lst.remove(dom)
    lst.insert(0, dom)
    saved_user_domains[str(uid)] = lst[:10]


def get_cookie_for_url(uid, url):
    dom = clean_domain(url)
    if not dom:
        return ""
    umap = user_domain_cookies.get(str(uid), {})
    if dom in umap:
        return umap[dom]
    for k, v in umap.items():
        if dom.endswith("." + k):
            return v
    return ""


def parse_cookie_input(raw_cookie):
    s = (raw_cookie or "").strip().strip("'\"")
    if s.lower().startswith("cookie:"):
        s = s.split(":", 1)[1].strip()
    if s.startswith("[") or s.startswith("{"):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                pairs = [f"{item.get('name')}={item.get('value')}" for item in data if isinstance(item, dict) and item.get("name")]
                return "; ".join(pairs)
            if isinstance(data, dict):
                return "; ".join(f"{k}={v}" for k, v in data.items())
        except Exception:
            pass
    lines = []
    for line in s.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            lines.append(f"{parts[5]}={parts[6]}")
        else:
            lines.append(line)
    return "; ".join(lines)


def create_status_msg(chat_id, text):
    try:
        sr = send_message(chat_id, text)
        data = sr.json() if sr is not None else {}
        if isinstance(data, dict) and data.get("ok"):
            return data.get("result", {}).get("message_id")
    except Exception:
        pass
    return None


def update_status_msg(chat_id, msg_id, text):
    if not msg_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
            json={"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"},
            timeout=6,
        )
    except Exception:
        pass


def engine_label(uid, url):
    eng = "curl_cffi (Chrome TLS)" if cffi_requests else ("cloudscraper" if cloudscraper else "requests")
    ck = "🍪 بالكوكيز" if (uid and get_cookie_for_url(uid, url)) else "بدون كوكيز"
    return f"{eng} | {ck}"


def build_session():
    if cffi_requests:
        return cffi_requests.Session(impersonate="chrome")
    if cloudscraper:
        return cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "android", "mobile": True})
    return requests.Session()


def is_waf_blocked(resp):
    if resp.status_code in (403, 429, 503):
        return True
    try:
        sample = (resp.text or "")[:3500].lower()
        return any(m in sample for m in WAF_MARKERS)
    except Exception:
        return False


def stealth_get(url, uid=None, referer=None, timeout=12, status_msg_id=None, session=None):
    if status_msg_id and uid:
        update_status_msg(
            uid,
            status_msg_id,
            f"🔍 <b>[1/4] جاري التحقق من الموقع...</b>\n⚙️ المحرك: <code>{engine_label(uid, url)}</code>",
        )

    headers = {
        **BROWSER_HEADERS,
        "Referer": referer or url,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Upgrade-Insecure-Requests": "1",
    }
    ck = get_cookie_for_url(uid, url) if uid else ""
    if ck:
        headers["Cookie"] = ck

    t0 = time.time()
    try:
        if session is not None:
            resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        elif cffi_requests:
            resp = cffi_requests.get(url, headers=headers, impersonate="chrome", timeout=timeout, allow_redirects=True)
        elif cloudscraper:
            sc = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "android", "mobile": True})
            resp = sc.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        else:
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)

        elapsed = f"{time.time() - t0:.1f}s"
        if is_waf_blocked(resp):
            if status_msg_id and uid:
                update_status_msg(
                    uid,
                    status_msg_id,
                    f"🛡️ <b>فشل التحقق — الموقع محمي (HTTP {resp.status_code})</b> ({elapsed})\n"
                    f"💡 أضف كوكيز حديثة من المتصفح (<code>cf_clearance</code>) للدومين ثم أعد المحاولة.",
                )
        elif is_404_page(resp, html=getattr(resp, "text", "") or ""):
            if status_msg_id and uid:
                update_status_msg(
                    uid,
                    status_msg_id,
                    f"⚠️ <b>الصفحة غير موجودة (404)</b> على الموقع ({elapsed}).",
                )
        elif status_msg_id and uid:
            update_status_msg(
                uid,
                status_msg_id,
                f"✅ <b>[2/4] تم التحقق بنجاح</b> (HTTP {resp.status_code} خلال {elapsed})\n"
                f"📄 جاري تحليل محتوى الصفحة واستخراج العناصر...",
            )
        return resp
    except Exception as e:
        if status_msg_id and uid:
            update_status_msg(
                uid,
                status_msg_id,
                f"❌ <b>توقف التحقق بسبب خطأ اتصال:</b>\n<code>{esc(str(e)[:120])}</code>",
            )
        raise


def extract_site_cookies(target_url, extra_cookie=""):
    if not target_url.startswith(("http://", "https://")):
        target_url = "https://" + target_url
    headers = {
        **BROWSER_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    }
    if extra_cookie:
        headers["Cookie"] = extra_cookie

    jar_pairs = []
    try:
        sess = build_session()
        resp = sess.get(target_url, headers=headers, timeout=12, allow_redirects=True)
        try:
            for k, v in sess.cookies.items():
                if k and v:
                    jar_pairs.append(f"{k}={v}")
        except Exception:
            for c in getattr(sess, "cookies", []):
                if getattr(c, "name", None) and getattr(c, "value", None):
                    jar_pairs.append(f"{c.name}={c.value}")
        if not jar_pairs and resp.headers.get("Set-Cookie"):
            for part in resp.headers.get("Set-Cookie").split(","):
                kv = part.split(";", 1)[0].strip()
                if "=" in kv:
                    jar_pairs.append(kv)
    except Exception:
        pass

    merged = []
    seen = set()
    for chunk in ([extra_cookie] + jar_pairs):
        for kv in (chunk or "").split(";"):
            kv = kv.strip()
            if "=" in kv:
                k = kv.split("=", 1)[0].strip()
                if k and k not in seen:
                    seen.add(k)
                    merged.append(kv)
    return "; ".join(merged)


def ai_normalize_search_query(raw_query: str) -> dict:
    q = (raw_query or "").strip()
    if not q or q.startswith(("http://", "https://")):
        return {"original": q, "canonical": q, "variants": [q] if q else []}
    try:
        from ai_features import ask_ai
        prompt = (
            "حوّل اسم العمل التالي (كرتون، أنميشن، أنمي، فيلم، أو مسلسل) إلى الاسم الإنكليزي الرسمي أو الاسم الأشهر عالمياً "
            "لتحسين دقة البحث. أرجع سطرين فقط بدون أي شرح أو مقدمات:\n"
            "السطر الأول: الاسم الإنكليزي الرسمي / الأشهر فقط\n"
            "السطر الثاني: اسم بديل مشهور أو كلمة مفتاحية مختصرة (أو نفس الاسم)\n"
            f"المدخل: {q}"
        )
        ans = ask_ai("search_query_normalizer", prompt)
        lines = [ln.strip(" -•\"'`*") for ln in (ans or "").splitlines() if ln.strip() and not ln.strip().startswith("⚠️")]
        primary = lines[0] if lines else q
        secondary = lines[1] if len(lines) > 1 else q
        variants = []
        for cand in (primary, secondary, q):
            if cand and cand.lower() not in [v.lower() for v in variants]:
                variants.append(cand)
        return {"original": q, "canonical": primary, "variants": variants[:3]}
    except Exception:
        return {"original": q, "canonical": q, "variants": [q]}


def url_matches_domains(url, allowed_domains):
    if not allowed_domains:
        return True
    try:
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return any(host == dom or host.endswith("." + dom) for dom in allowed_domains)
    except Exception:
        return False


def fmt_num(n):
    if n is None or n == "":
        return "—"
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fmt_dur(sec):
    try:
        sec = int(sec or 0)
    except Exception:
        return "—"
    if sec <= 0:
        return "—"
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size_bytes(size_bytes: int) -> str:
    try:
        b = int(size_bytes or 0)
    except Exception:
        return ""
    if b <= 0:
        return ""
    if b >= 1024 ** 3:
        return f"{b / (1024 ** 3):.2f} GB"
    return f"{b / (1024 ** 2):.1f} MB"


def fetch_video_card_meta(url, uid=None):
    clients = YT_CLIENTS if ("youtu" in url) else [None]
    ck = get_cookie_for_url(uid, url) if uid else ""
    for cl in clients:
        opts = {
            **YDL_BASE,
            "skip_download": True,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 5,
            "retries": 1,
        }
        if ck:
            opts["http_headers"] = {**BROWSER_HEADERS, "Cookie": ck}
        if cl:
            opts["extractor_args"] = {"youtube": {"player_client": [cl]}}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if not info:
                continue
            if info.get("entries"):
                info = info["entries"][0]
            if not (info.get("formats") or info.get("url") or info.get("duration")):
                continue
            uploader = info.get("uploader_id") or info.get("uploader") or info.get("channel") or "—"
            if uploader != "—" and not str(uploader).startswith("@"):
                uploader = f"@{uploader}"
            return {
                "title": info.get("title") or "فيديو",
                "thumb": info.get("thumbnail") or "",
                "uploader": uploader,
                "views": fmt_num(info.get("view_count")),
                "likes": fmt_num(info.get("like_count")),
                "comments": fmt_num(info.get("comment_count")),
                "duration": fmt_dur(info.get("duration")),
            }
        except Exception:
            continue
    return None


def query_variants(query, allowed_domains, mode="all"):
    q = (query or "").strip()
    if not q:
        return []
    clean_word = q.lstrip("#").strip()
    tag = "#" + clean_word.replace(" ", "") if clean_word else ""

    if mode == "pd":
        return [
            f"site:pixeldrain.com {clean_word}".strip(),
            f"site:pixeldrain.com/l {clean_word}".strip(),
            f"site:pixeldrain.com/u {clean_word}".strip(),
        ]
    if mode == "tt":
        return [
            f"site:tiktok.com/*/video {clean_word}",
            f"site:tiktok.com/*/video {tag}",
            f"site:tiktok.com {clean_word} video",
            f"site:tiktok.com {tag}",
        ]
    if mode == "ig":
        return [
            f"site:instagram.com/reel {clean_word}",
            f"site:instagram.com/p {clean_word}",
            f"site:instagram.com {tag}",
        ]
    if mode == "x":
        return [
            f"site:x.com/*/status {clean_word}",
            f"site:twitter.com/*/status {clean_word}",
            f"site:x.com {tag}",
        ]
    if mode == "fb":
        return [
            f"site:facebook.com/watch {clean_word}",
            f"site:facebook.com/reel {clean_word}",
            f"site:facebook.com {clean_word}",
        ]

    if allowed_domains:
        dom = allowed_domains[0]
        variants = [f"site:{dom} {clean_word}".strip()]
        if tag and f"site:{dom} {tag}".strip() not in variants:
            variants.append(f"site:{dom} {tag}".strip())
        if f"site:{dom}" not in variants:
            variants.append(f"site:{dom}")
        return variants[:3]

    variants = [q]
    if tag and tag not in variants:
        variants.append(tag)
    return variants[:3]


def serper_request_sync(query_str):
    global _serper_key_idx
    if not SERPER_KEYS:
        return None
    total_keys = len(SERPER_KEYS)
    for attempt in range(total_keys):
        idx = (_serper_key_idx + attempt) % total_keys
        key = SERPER_KEYS[idx]
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": key,
                    "Content-Type": "application/json",
                    "User-Agent": BROWSER_HEADERS.get("User-Agent", "Mozilla/5.0"),
                },
                json={"q": query_str, "num": 10},
                timeout=SEARCH_TIMEOUT,
            )
            if resp.status_code in (401, 402, 403, 429):
                _serper_key_idx = (idx + 1) % total_keys
                continue
            resp.raise_for_status()
            data = resp.json() or {}
            _serper_key_idx = idx
            return data.get("organic") or []
        except Exception:
            _serper_key_idx = (idx + 1) % total_keys
            continue
    return None


async def search_serper(query, allowed_domains, mode="all", classify_fn=None, supported_video_fn=None):
    variants = query_variants(query, allowed_domains, mode=mode)
    if not variants or not SERPER_KEYS:
        return []

    def run_serper():
        out = []
        seen = set()
        for vq in variants:
            organic = serper_request_sync(vq)
            if organic is None:
                return None
            for item in organic:
                href = (item.get("link") or "").strip()
                if not href or href in seen or is_ad_media_url(href):
                    continue
                if not url_matches_domains(href, allowed_domains):
                    continue
                if mode in SOCIAL_MODES and supported_video_fn and not supported_video_fn(href, mode=mode):
                    continue
                title_txt = item.get("title") or "نتيجة"
                if is_non_content_page(href, title_txt):
                    continue
                seen.add(href)
                kind_val = classify_fn(href, mode=mode, title=title_txt) if classify_fn else "web"
                out.append({
                    "kind": kind_val,
                    "title": title_txt,
                    "url": href,
                    "snippet": (item.get("snippet") or "")[:160],
                    "thumb": (item.get("imageUrl") or item.get("thumbnail") or "").strip(),
                })
                if len(out) >= 10:
                    return out
            if out:
                break
        return out

    res = await asyncio.wait_for(asyncio.to_thread(run_serper), timeout=SEARCH_TIMEOUT)
    return res or []


async def search_youtube(query):
    def extract():
        opts = dict(SEARCH_YDL_OPTS)
        opts["extractor_args"] = {"youtube": {"player_client": [YT_CLIENTS[0]] if YT_CLIENTS else ["android"]}}
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch8:{query}", download=False)
                out = []
                for v in (info or {}).get("entries") or []:
                    vid = v.get("id")
                    if vid:
                        u = f"https://www.youtube.com/watch?v={vid}"
                        out.append({
                            "kind": "video",
                            "title": v.get("title") or "بدون عنوان",
                            "url": u,
                            "snippet": "",
                            "meta": {
                                "title": v.get("title") or "فيديو",
                                "thumb": v.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                                "uploader": f"@{v.get('uploader')}" if v.get("uploader") else "—",
                                "views": fmt_num(v.get("view_count")),
                                "likes": fmt_num(v.get("like_count")),
                                "comments": fmt_num(v.get("comment_count")),
                                "duration": fmt_dur(v.get("duration")),
                            },
                        })
                return out
            except Exception:
                return []

    return await asyncio.wait_for(asyncio.to_thread(extract), timeout=SEARCH_TIMEOUT)


async def search_ddg_fallback(query, allowed_domains, mode="all", classify_fn=None, supported_video_fn=None):
    variants = query_variants(query, allowed_domains, mode=mode)

    def ddg_multi():
        out = []
        seen = set()
        with DDGS(timeout=SEARCH_TIMEOUT) as ddgs:
            for vq in variants:
                try:
                    for r in ddgs.text(vq, max_results=8):
                        href = (r.get("href") or "").strip()
                        if not href or href in seen or is_ad_media_url(href):
                            continue
                        if not url_matches_domains(href, allowed_domains):
                            continue
                        if mode in SOCIAL_MODES and supported_video_fn and not supported_video_fn(href, mode=mode):
                            continue
                        title_txt = r.get("title") or "نتيجة"
                        if is_non_content_page(href, title_txt):
                            continue
                        seen.add(href)
                        kind_val = classify_fn(href, mode=mode, title=title_txt) if classify_fn else "web"
                        out.append({
                            "kind": kind_val,
                            "title": title_txt,
                            "url": href,
                            "snippet": (r.get("body") or r.get("snippet") or "")[:160],
                            "thumb": "",
                        })
                        if len(out) >= 10:
                            return out
                except Exception:
                    continue
        return out

    return await asyncio.wait_for(asyncio.to_thread(ddg_multi), timeout=SEARCH_TIMEOUT)