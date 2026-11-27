# ==========================================
# الجزء 2: anime_sites.py
# ملف مواقع الأنمي وتفرعاتها:
# - دعم witanime.site + y.mpta00a.shop (Anime4up) + jet.animerco.org + pixeldrain.com
# - استخراج جدول التحميل الحقيقي (الخادم + الجودة + الحجم الفعلي من الموقع/الرابط)
# - استخراج مدة الحلقة من الصفحة للتحقق من أنها حلقة كاملة وليست إعلاناً
# - حظر الإعلانات (1xbet, vip200mr, النوافذ المنبثقة)
# ==========================================
import os
import re
from html import unescape
from urllib.parse import urlparse, urljoin, quote
from config import BROWSER_HEADERS
from telegram_api import TG_SESSION
from search_core import (
    PIXELDRAIN_API_BASE,
    FILE_EXTS,
    VIDEO_EXTS,
    MANGA_KEYWORDS,
    is_ad_media_url,
    clean_domain,
    is_404_page,
    is_non_content_page,
    stealth_get,
    get_cookie_for_url,
    url_matches_domains,
    fmt_size_bytes,
    fmt_dur,
)

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

try:
    from curl_cffi import requests as cffi_requests
except Exception:
    cffi_requests = None


# سجل مواقع الأنمي وتفرعاتها (أضف أي موقع جديد هنا بسهولة)
ANIME_SITES_REGISTRY = {
    "witanime.site": {
        "name": "WitAnime",
        "watch_paths": ["/watch/"],
        "anime_paths": ["/anime/"],
        "ep_url_template": "https://witanime.site/watch/{slug}/{ep}/",
    },
    "y.mpta00a.shop": {
        "name": "Anime4up",
        "watch_paths": ["/episode/", "/watch/"],
        "anime_paths": ["/anime/"],
        "ep_url_template": "https://y.mpta00a.shop/episode/{slug}-%d8%a7%d9%84%d8%ad%d9%84%d9%82%d8%a9-{ep}/",
    },
    "jet.animerco.org": {
        "name": "Animerco",
        "watch_paths": ["/episodes/"],
        "anime_paths": ["/seasons/"],
        "ep_url_template": "https://jet.animerco.org/episodes/{slug}-%d8%a7%d9%84%d8%ad%d9%84%d9%82%d8%a9-{ep}/",
    },
}

DEFAULT_ANIME_DOMAINS = list(ANIME_SITES_REGISTRY.keys())

KNOWN_HOST_SERVERS = (
    "megamax.me", "mega.nz", "mediafire.com", "gofile.io", "vikingfile.com",
    "workupload.com", "mp4upload.com", "uqload.vc", "uqload.com", "dsvplay.com",
    "pixeldrain.com", "drive.google.com", "yonaplay", "hgcloud", "vidmoly", "dood",
)


def is_registered_anime_url(url: str) -> bool:
    dom = clean_domain(url)
    if not dom:
        return False
    return any(dom == k or dom.endswith("." + k) for k in ANIME_SITES_REGISTRY)


def _build_slug_candidates(name_str: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s-]", "", (name_str or "").strip(), flags=re.U).strip()
    if not cleaned:
        return []
    hyphenated = re.sub(r"[\s_]+", "-", cleaned).strip("-").lower()
    spaced_enc = quote(cleaned)
    out = []
    for cand in (hyphenated, spaced_enc):
        if cand and cand not in out:
            out.append(cand)
    return out


def build_domain_entry_candidates(domain: str, query_variants: list[str], original_query: str) -> list[dict]:
    dom = clean_domain(domain)
    if not dom:
        return []
    names = []
    for n in ([original_query] + list(query_variants or [])):
        if n and n.strip() and n.strip().lower() not in [x.lower() for x in names]:
            names.append(n.strip())

    out = []
    seen_urls = set()
    for n in names[:2]:
        slugs = _build_slug_candidates(n)
        if not slugs:
            continue
        slug = slugs[0]
        if dom in ANIME_SITES_REGISTRY:
            tpl = ANIME_SITES_REGISTRY[dom]["ep_url_template"]
            ep1_url = tpl.format(slug=slug, ep=1)
            anime_path = ANIME_SITES_REGISTRY[dom]["anime_paths"][0]
            anime_url = f"https://{dom}{anime_path}{slug}/"
            candidates = [
                ("chapter", f"{n} - الحلقة 1 ({dom})", ep1_url, f"حلقة مباشرة من الاسم: {n}"),
                ("chapter", f"{n} ({dom})", anime_url, f"صفحة الأنمي: {n}"),
            ]
        else:
            ep1_slug = quote(f"{slug}-الحلقة-1", safe="-")
            candidates = [
                ("chapter", f"{n} - الحلقة 1 ({dom})", f"https://{dom}/episodes/{ep1_slug}/", f"حلقة مباشرة من الاسم: {n}"),
                ("chapter", f"{n} ({dom})", f"https://{dom}/seasons/{slug}/", f"صفحة الموسم/العمل: {n}"),
            ]
        for kind_c, title_c, u_c, snip_c in candidates:
            if u_c not in seen_urls:
                seen_urls.add(u_c)
                out.append({
                    "kind": kind_c,
                    "title": title_c,
                    "url": u_c,
                    "snippet": snip_c,
                    "thumb": "",
                })
    return out


def is_pixeldrain_url(url: str) -> bool:
    try:
        host = (urlparse(url or "").netloc or "").lower()
        return "pixeldrain.com" in host
    except Exception:
        return False


def extract_pixeldrain_ref(url_or_text: str) -> tuple[str, str]:
    raw = (url_or_text or "").strip()
    m_list = re.search(r"pixeldrain\.com/(?:api/list|l)/([A-Za-z0-9_-]+)", raw, flags=re.I)
    if m_list:
        return "list", m_list.group(1)
    m_file = re.search(r"pixeldrain\.com/(?:api/file|u)/([A-Za-z0-9_-]+)", raw, flags=re.I)
    if m_file:
        return "file", m_file.group(1)
    return "", ""


def extract_episode_number(text: str):
    s = (text or "").strip()
    if not s:
        return None
    patterns = [
        r"(?:الحلقة|حلقة|episode|ep\.?|s\d+\s*e)\s*[:#\-_\s]*0*(\d{1,4})(?!\d)",
        r"/watch/[^/]+/0*(\d{1,4})/?$",
        r"(?:^|[\s_\-\.\[\(]+)0*(\d{1,4})(?:$|[\s_\-\.\]\)]|\.(?:mp4|mkv|avi|webm|m4v|zip|cbz))",
    ]
    for pat in patterns:
        m = re.search(pat, s, flags=re.I)
        if m:
            try:
                num = int(m.group(1))
                if 0 < num < 5000:
                    return num
            except Exception:
                pass
    return None


def count_episodes_in_items(items: list[dict]) -> int:
    ep_nums = set()
    for it in (items or []):
        if is_non_content_page(it.get("url", ""), it.get("title", "")):
            continue
        if it.get("episode_count"):
            return int(it["episode_count"])
        title = f"{it.get('title', '')} {it.get('url', '')}"
        n = extract_episode_number(title)
        if n is not None:
            ep_nums.add(n)
    return len(ep_nums)


def fetch_pixeldrain_metadata(url: str) -> dict:
    kind, pid = extract_pixeldrain_ref(url)
    info = {
        "kind": kind or "file",
        "id": pid,
        "title": url,
        "files": [],
        "episode_count": 0,
        "direct_url": url,
        "thumb": "",
        "size_text": "",
    }
    if not pid:
        return info

    try:
        if kind == "list":
            r = TG_SESSION.get(f"{PIXELDRAIN_API_BASE}/list/{pid}", timeout=12)
            if r.status_code == 200:
                data = r.json() or {}
                list_title = data.get("title") or f"قائمة Pixeldrain ({pid})"
                raw_files = data.get("files") or []
                parsed_files = []
                ep_nums = set()
                for f in raw_files:
                    fid = f.get("id")
                    if not fid:
                        continue
                    fname = f.get("name") or f"file_{fid}"
                    fsize = fmt_size_bytes(f.get("size", 0))
                    lbl = f"{fname} ({fsize})" if fsize else fname
                    f_url = f"{PIXELDRAIN_API_BASE}/file/{fid}"
                    ep_n = extract_episode_number(fname)
                    if ep_n is not None:
                        ep_nums.add(ep_n)
                    parsed_files.append((ep_n if ep_n is not None else 10**9, lbl, f_url, f.get("size", 0)))
                parsed_files.sort(key=lambda x: (x[0], x[1].lower()))
                info["title"] = list_title
                info["files"] = [(lbl, f_url) for _, lbl, f_url, _ in parsed_files]
                info["episode_count"] = len(ep_nums) if ep_nums else len(parsed_files)
                if parsed_files:
                    info["direct_url"] = parsed_files[0][2]
        else:
            r = TG_SESSION.get(f"{PIXELDRAIN_API_BASE}/file/{pid}/info", timeout=12)
            info["direct_url"] = f"{PIXELDRAIN_API_BASE}/file/{pid}"
            info["thumb"] = f"{PIXELDRAIN_API_BASE}/file/{pid}/thumbnail"
            if r.status_code == 200:
                data = r.json() or {}
                fname = data.get("name") or f"Pixeldrain_{pid}"
                fsize = fmt_size_bytes(data.get("size", 0))
                info["size_text"] = fsize
                info["title"] = fname
                lbl = f"{fname} ({fsize})" if fsize else fname
                info["files"] = [(lbl, info["direct_url"])]
                ep_n = extract_episode_number(fname)
                info["episode_count"] = 1 if ep_n is not None else 0
    except Exception:
        if pid and kind != "list":
            info["direct_url"] = f"{PIXELDRAIN_API_BASE}/file/{pid}"
    return info


def is_supported_video_url(url, mode="all"):
    low = (url or "").lower()
    if is_ad_media_url(low):
        return False
    if "/links/" in low or "/download/" in low or "/watch/" in low or "/episode/" in low or "/episodes/" in low:
        return True
    if is_pixeldrain_url(low):
        return ("/api/file/" in low) or ("/u/" in low)
    if any(bad in low for bad in ("/discover/", "/tag/", "/music/", "/photo/", "/search", "/login", "/explore/")):
        return False
    if "tiktok.com" in low:
        return ("/video/" in low) or ("vm.tiktok.com" in low) or ("vt.tiktok.com" in low) or ("/t/" in low)
    if "instagram.com" in low:
        return any(p in low for p in ("/reel/", "/reels/", "/p/", "/tv/"))
    if "youtube.com" in low or "youtu.be" in low:
        return ("watch?v=" in low) or ("youtu.be/" in low) or ("/shorts/" in low)
    if "x.com" in low or "twitter.com" in low:
        return "/status/" in low
    if "facebook.com" in low or "fb.watch" in low:
        return any(p in low for p in ("/watch", "/videos/", "/reel/", "fb.watch"))
    return False


def is_manga_or_chapter_context(url, title=""):
    if is_non_content_page(url, title):
        return False
    path = (urlparse(url or "").path or "").lower()
    if any(p in path for p in ("/seasons/", "/episodes/", "/watch/", "/episode/", "/anime/")):
        return True
    if is_registered_anime_url(url):
        return True
    comb = f"{url} {title}".lower()
    if "/search" in path:
        return False
    return any(k in comb for k in MANGA_KEYWORDS)


def extract_real_chapter_number(url, anchor_text=""):
    if is_non_content_page(url, anchor_text):
        return None
    if "/search" in urlparse(url).path.lower():
        return None
    m_watch = re.search(r"/watch/[^/]+/0*(\d+)/?$", urlparse(url).path, flags=re.I)
    if m_watch:
        val = int(m_watch.group(1))
        return val if val > 0 else None
    comb = f"{url} {anchor_text}"
    m = re.search(
        r"(?:الحلقة|حلقة|episode|ep|chapter|ch|chap|فصل|الفصل)[-_:\s=%d8%a7%d9%84%d8%ad%d9%84%d9%82%d8%a9]*0*(\d+(?:\.\d+)?)",
        comb,
        re.IGNORECASE,
    )
    if m:
        try:
            val = float(m.group(1))
            if val <= 0:
                return None
            return int(val) if val.is_integer() else val
        except Exception:
            return None
    return None


def _extract_size_from_text(txt: str) -> str:
    """يستخرج الحجم الفعلي كما هو مكتوب في صفحة الموقع (مثل 420 MB أو 1.2 GB) بدون افتراض."""
    if not txt:
        return ""
    m = re.search(r"(\d+(?:[.,]\d+)?\s*(?:GB|MB|KB|جيجا|ميجا))", txt, flags=re.I)
    return m.group(1).strip() if m else ""


def _probe_remote_size(url: str, referer_url: str, uid=None) -> str:
    """يجلب الحجم الحقيقي للملف من ترويسة Content-Length إذا كان متاحاً مباشرة."""
    low = (url or "").lower()
    if "pixeldrain.com" in low:
        kind, pid = extract_pixeldrain_ref(url)
        if pid and kind != "list":
            try:
                r = TG_SESSION.get(f"{PIXELDRAIN_API_BASE}/file/{pid}/info", timeout=4)
                if r.status_code == 200:
                    return fmt_size_bytes((r.json() or {}).get("size", 0))
            except Exception:
                pass
        return ""
    if any(low.split("?", 1)[0].endswith(ext) for ext in VIDEO_EXTS):
        try:
            headers = {**BROWSER_HEADERS, "Referer": referer_url}
            ck = get_cookie_for_url(uid, url) if uid else ""
            if ck:
                headers["Cookie"] = ck
            hr = TG_SESSION.head(url, headers=headers, timeout=4, allow_redirects=True)
            cl = int(hr.headers.get("Content-Length") or 0)
            if cl > 500_000:
                return fmt_size_bytes(cl)
        except Exception:
            pass
    return ""


def _extract_episode_duration_from_page(html_text: str, soup=None) -> str:
    """يستخرج مدة الحلقة الحقيقية من صفحة الموقع (مثل: مدة الحلقة: 23 دقيقة) للتمييز عن الإعلانات."""
    full_txt = soup.get_text(" ", strip=True) if soup is not None else re.sub(r"<[^>]+>", " ", html_text or "")
    patterns = [
        r"مدة\s*الحلقة\s*[:\-]?\s*([^\n|•]{2,25})",
        r"المدة\s*[:\-]?\s*(\d+\s*(?:دقيقة|دقائق|ساعة|ثانية|min|m))",
        r"Duration\s*[:\-]?\s*(\d+\s*(?:min|minutes|hr|h))",
    ]
    for pat in patterns:
        m = re.search(pat, full_txt, flags=re.I)
        if m:
            val = re.sub(r"\s+", " ", m.group(1)).strip()
            if len(val) <= 25:
                return val
    return ""


def extract_download_table_links(html_text: str, page_url: str, soup=None, uid=None) -> list[dict]:
    """
    يستخرج جدول التحميل من witanime.site و Anime4up و Animerco:
    (الرابط + الخادم مثل megamax.me / mega.nz / mediafire / gofile + الجودة FHD 1080p / HD 720p / SD 480p + الحجم الحقيقي إن وجد).
    """
    results = []
    seen = set()
    q_pat = re.compile(r"\b(2160p|1080p|720p|480p|360p|240p|FHD|HD|SD|متعدد\s*الجودات)\b", re.I)

    def _detect_server(txt: str, href_u: str) -> str:
        comb = f"{txt} {href_u}".lower()
        for srv in KNOWN_HOST_SERVERS:
            if srv in comb:
                if "megamax.me 2" in comb or "megamax 2" in comb:
                    return "megamax.me 2"
                return srv
        host = clean_domain(href_u)
        page_host = clean_domain(page_url)
        if host and host != page_host:
            return host
        return ""

    def _add_entry(u_raw: str, row_txt: str = "", idx_fallback: int = 1, explicit_qual: str = ""):
        full_u = urljoin(page_url, unescape((u_raw or "").strip()))
        if not full_u.startswith(("http://", "https://")) or full_u in seen:
            return
        if is_ad_media_url(full_u):
            return
        low_u = full_u.lower()
        srv_name = _detect_server(row_txt, full_u)
        is_dl_link = (
            "/links/" in low_u
            or "/download/" in low_u
            or "_token=" in low_u
            or "signature=" in low_u
            or bool(srv_name)
            or any(low_u.split("?", 1)[0].endswith(ext) for ext in VIDEO_EXTS)
        )
        if not is_dl_link:
            return
        seen.add(full_u)

        qm = q_pat.search(explicit_qual or "") or q_pat.search(row_txt or "") or q_pat.search(full_u)
        qual = qm.group(1) if qm else f"خادم {idx_fallback}"
        if qual.upper() in ("FHD", "1080P"):
            qual = "FHD 1080p"
        elif qual.upper() in ("HD", "720P"):
            qual = "HD 720p"
        elif qual.upper() in ("SD", "480P"):
            qual = "SD 480p"

        size_str = _extract_size_from_text(row_txt)
        parts_lbl = [qual]
        if srv_name:
            parts_lbl.append(srv_name)
        if size_str:
            parts_lbl.append(size_str)

        results.append({
            "quality": qual,
            "server": srv_name,
            "size": size_str,
            "label": " | ".join(parts_lbl),
            "url": full_u,
        })

    if soup is not None:
        for tr in soup.find_all("tr"):
            tr_txt = tr.get_text(" ", strip=True)
            for idx, a in enumerate(tr.find_all("a", href=True), 1):
                _add_entry(a["href"], tr_txt, idx)

        for container in soup.find_all(["div", "ul", "li", "section"]):
            c_txt = container.get_text(" ", strip=True)
            if len(c_txt) > 600:
                continue
            q_head = q_pat.search(c_txt[:80])
            for idx, a in enumerate(container.find_all("a", href=True), 1):
                href = a.get("href") or ""
                a_txt = a.get_text(" ", strip=True)
                parent_txt = a.parent.get_text(" ", strip=True) if a.parent else a_txt
                _add_entry(href, f"{parent_txt} {a_txt}", idx, explicit_qual=q_head.group(1) if q_head else "")

        for idx, a in enumerate(soup.find_all("a", href=True), 1):
            href = a.get("href") or ""
            row = a.find_parent(["tr", "li", "div"])
            row_txt = row.get_text(" ", strip=True) if row else a.get_text(" ", strip=True)
            _add_entry(href, row_txt, idx)

    for idx, m in enumerate(re.findall(r"""https?://[^\s"'<>\\]+/(?:links|download)/[^\s"'<>\\]+""", html_text or "", flags=re.I), 1):
        _add_entry(m, "", idx)

    probed = 0
    for item in results:
        if not item["size"] and probed < 3:
            sz = _probe_remote_size(item["url"], page_url, uid=uid)
            if sz:
                item["size"] = sz
                item["label"] = f"{item['label']} | {sz}"
            probed += 1

    q_rank = {
        "2160p": 0,
        "FHD 1080p": 1,
        "1080p": 1,
        "متعدد الجودات": 2,
        "HD 720p": 3,
        "720p": 3,
        "SD 480p": 4,
        "480p": 4,
        "360p": 5,
        "240p": 6,
    }
    results.sort(key=lambda x: q_rank.get(x["quality"], 9))
    return results


def extract_html_episodes(html_text: str, page_url: str, soup=None) -> tuple[list[int], dict]:
    ep_nums = set()
    ep_links = {}
    ep_pat = re.compile(r"(?:الحلقة|حلقة|episode|ep\.?|s\d+\s*e)\s*[:#\-_\s]*0*(\d{1,4})(?!\d)", re.I)

    if soup is not None:
        for el in soup.find_all(["a", "button", "div", "li", "span", "h2", "h3", "h4"]):
            txt = el.get_text(" ", strip=True)
            href = el.get("href") if el.name == "a" else None
            if not href and el.name != "a":
                a_child = el.find("a", href=True)
                if a_child:
                    href = a_child.get("href")
            full_h = urljoin(page_url, href.strip()) if href else ""
            m_w = re.search(r"/watch/[^/]+/0*(\d+)/?$", urlparse(full_h).path, flags=re.I) if full_h else None
            m = ep_pat.search(txt or "") or (ep_pat.search(full_h) if any(p in full_h.lower() for p in ("/episodes/", "/episode/", "/watch/")) else None)
            if m_w:
                n = int(m_w.group(1))
                if 0 < n < 3000:
                    ep_nums.add(n)
                    if full_h.startswith("http") and n not in ep_links:
                        ep_links[n] = full_h
            elif m:
                n = int(m.group(1))
                if 0 < n < 3000:
                    ep_nums.add(n)
                    if full_h.startswith("http") and any(p in full_h.lower() for p in ("/episodes/", "/episode/", "/watch/")) and n not in ep_links:
                        ep_links[n] = full_h
    else:
        for m in ep_pat.finditer(html_text or ""):
            n = int(m.group(1))
            if 0 < n < 3000:
                ep_nums.add(n)

    return sorted(ep_nums), ep_links


def extract_script_media_urls(html_text: str, page_url: str) -> list[str]:
    found = []
    if not html_text:
        return found
    for m in re.findall(r"""https?://[^\s"'<>\\]+(?:/(?:links|download)/[^\s"'<>\\]+|\.m3u8|\.mp4|\.webm|\.mkv)[^\s"'<>\\]*""", html_text, flags=re.I):
        clean_u = unescape(m.strip().rstrip("\\"))
        if not is_ad_media_url(clean_u) and clean_u not in found:
            found.append(clean_u)
    return found[:8]


def build_episode_navigation_map(page_url: str, existing_nums: list[int], existing_map: dict) -> tuple[list[int], dict]:
    nums = list(existing_nums or [])
    emap = dict(existing_map or {})
    if len(nums) >= 2 and len(emap) >= len(nums):
        return sorted(emap.keys()), emap

    parsed = urlparse(page_url or "")
    path = parsed.path or ""
    total_n = nums[-1] if nums else 12
    gen_nums = list(range(1, min(total_n + 1, 2000)))

    m_wit = re.match(r"^(/watch/[^/]+)/(\d+)/?$", path, flags=re.I)
    if m_wit:
        base_watch = m_wit.group(1)
        cur_ep = int(m_wit.group(2))
        max_n = max(total_n, cur_ep)
        gen_nums = list(range(1, min(max_n + 1, 2000)))
        for n in gen_nums:
            if n not in emap:
                emap[n] = f"{parsed.scheme}://{parsed.netloc}{base_watch}/{n}/"
        return gen_nums, emap

    if "/episodes/" in path.lower() or "/episode/" in path.lower():
        m = re.match(r"^(.*?)[-_]?(?:الحلقة|episode|ep)[-_]?(\d+)/?$", path, flags=re.I)
        if m:
            prefix = m.group(1)
            for n in gen_nums:
                if n not in emap:
                    emap[n] = f"{parsed.scheme}://{parsed.netloc}{prefix}-{quote('الحلقة')}-{n}/"
            return gen_nums, emap

    if "/seasons/" in path.lower() or "/anime/" in path.lower():
        slug_part = path.rstrip("/").split("/")[-1]
        dom = clean_domain(page_url)
        for n in gen_nums:
            if n not in emap:
                if dom == "witanime.site":
                    emap[n] = f"{parsed.scheme}://{parsed.netloc}/watch/{slug_part}/{n}/"
                elif dom == "y.mpta00a.shop":
                    emap[n] = f"{parsed.scheme}://{parsed.netloc}/episode/{slug_part}-{quote('الحلقة')}-{n}/"
                else:
                    emap[n] = f"{parsed.scheme}://{parsed.netloc}/episodes/{slug_part}-{quote('الحلقة')}-{n}/"
        return gen_nums, emap

    return sorted(nums), emap


def inspect_page_resources(url, uid=None, title_hint=""):
    info = {
        "banner": "",
        "title": "",
        "duration": "",
        "chapters_map": {},
        "chapter_nums": [],
        "episodes": [],
        "episodes_map": {},
        "download_links": [],
        "direct_files": [],
        "direct_videos": [],
        "episode_count": 0,
        "is_chapter_page": is_manga_or_chapter_context(url, title_hint),
        "is_non_content": is_non_content_page(url, title_hint),
    }

    if is_pixeldrain_url(url):
        pd = fetch_pixeldrain_metadata(url)
        info["title"] = pd.get("title") or url
        info["banner"] = pd.get("thumb") or ""
        info["episode_count"] = pd.get("episode_count", 0)
        for lbl, f_u in pd.get("files") or []:
            info["direct_files"].append((lbl[:42], f_u))
            if (any(lbl.lower().endswith(ext) for ext in VIDEO_EXTS) or "/api/file/" in f_u) and not is_ad_media_url(f_u):
                if f_u not in info["direct_videos"]:
                    info["direct_videos"].append(f_u)
        return info

    self_num = extract_real_chapter_number(url)
    if self_num is not None:
        info["chapters_map"][self_num] = url

    try:
        r = stealth_get(url, uid=uid, referer=url, timeout=10)
        if is_404_page(r, html=getattr(r, "text", "") or ""):
            info["is_non_content"] = True
            return info
        if r.status_code != 200 or not r.text:
            return info
        html = r.text
        dom = clean_domain(url)
        links = []
        soup_obj = None

        if BeautifulSoup:
            soup_obj = BeautifulSoup(html, "html.parser")
            if soup_obj.title and soup_obj.title.string:
                info["title"] = soup_obj.title.string.strip()
            if is_non_content_page(url, f"{title_hint} {info['title']}"):
                info["is_non_content"] = True
                return info

            for prop in ("og:image", "twitter:image", "og:image:secure_url"):
                tag = soup_obj.find("meta", attrs={"property": prop}) or soup_obj.find("meta", attrs={"name": prop})
                if tag and tag.get("content"):
                    cand = urljoin(url, tag["content"].strip())
                    if cand.startswith("http") and not is_ad_media_url(cand):
                        info["banner"] = cand
                        break
            if not info["banner"]:
                for img in soup_obj.find_all("img"):
                    src = img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src") or ""
                    full = urljoin(url, src.strip())
                    low = full.lower()
                    if full.startswith("http") and not is_ad_media_url(full) and not any(b in low for b in ("logo", "icon", "avatar", "emoji", "sprite", "svg")):
                        info["banner"] = full
                        break

            for a in soup_obj.find_all("a", href=True):
                full_u = urljoin(url, a["href"].strip())
                txt = a.get_text(" ", strip=True)
                links.append((full_u, txt))
        else:
            tm = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            if tm:
                info["title"] = unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
            if is_non_content_page(url, f"{title_hint} {info['title']}"):
                info["is_non_content"] = True
                return info
            mm = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
            if mm:
                info["banner"] = urljoin(url, mm.group(1).strip())
            for href_m, txt_m in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
                full_u = urljoin(url, href_m.strip())
                txt = re.sub(r"<[^>]+>", " ", txt_m)
                links.append((full_u, unescape(txt).strip()))

        info["duration"] = _extract_episode_duration_from_page(html, soup=soup_obj)

        dl_table = extract_download_table_links(html, url, soup=soup_obj, uid=uid)
        info["download_links"] = dl_table
        for dl_entry in dl_table:
            if dl_entry["url"] not in info["direct_videos"]:
                info["direct_videos"].append(dl_entry["url"])

        for m_u in extract_script_media_urls(html, url):
            if m_u not in info["direct_videos"]:
                info["direct_videos"].append(m_u)

        ep_nums, ep_links = extract_html_episodes(html, url, soup=soup_obj)
        info["episodes"] = ep_nums
        info["episodes_map"] = ep_links

        m_cnt = re.search(r"(?:عدد\s*الحلقات|الحلقات)\s*[:\s]*(\d+)", html)
        if m_cnt:
            info["episode_count"] = int(m_cnt.group(1))
        elif ep_nums:
            info["episode_count"] = len(ep_nums)

        if is_manga_or_chapter_context(url, f"{title_hint} {info['title']}"):
            info["is_chapter_page"] = True

        seen_files = set()
        for full_u, txt in links:
            if not full_u.startswith(("http://", "https://")) or is_ad_media_url(full_u):
                continue
            if is_pixeldrain_url(full_u) and full_u not in seen_files:
                seen_files.add(full_u)
                lbl = (txt[:30] or "Pixeldrain").strip()
                info["direct_files"].append((f"PD: {lbl}", full_u))
                continue
            clean_path = full_u.lower().split("?", 1)[0]
            if any(clean_path.endswith(ext) for ext in VIDEO_EXTS):
                if full_u not in info["direct_videos"]:
                    info["direct_videos"].append(full_u)
                continue
            if any(clean_path.endswith(ext) for ext in FILE_EXTS):
                if full_u not in seen_files:
                    seen_files.add(full_u)
                    ext_name = os.path.splitext(clean_path)[1].lstrip(".").upper()
                    lbl = (txt[:28] or ext_name).strip()
                    info["direct_files"].append((f"{ext_name}: {lbl}", full_u))
                continue
            if info["is_chapter_page"] and (not dom or url_matches_domains(full_u, [dom])):
                cnum = extract_real_chapter_number(full_u, txt)
                if cnum is not None and cnum not in info["chapters_map"]:
                    info["chapters_map"][cnum] = full_u

        path_low = (urlparse(url).path or "").lower()
        if any(p in path_low for p in ("/seasons/", "/episodes/", "/watch/", "/episode/", "/anime/")):
            nav_nums, nav_map = build_episode_navigation_map(url, ep_nums, {**ep_links, **info["chapters_map"]})
            info["chapters_map"] = nav_map
            info["chapter_nums"] = nav_nums
            if not info["episode_count"] and nav_nums:
                info["episode_count"] = len(nav_nums)
        else:
            info["chapter_nums"] = sorted(info["chapters_map"].keys())
    except Exception:
        pass
    return info


def classify_url(url, mode="all", title=""):
    low = (url or "").lower()
    if "/links/" in low or "/download/" in low:
        return "video"
    if is_pixeldrain_url(url):
        return "file"
    clean_p = low.split("?", 1)[0]
    if any(clean_p.endswith(ext) for ext in VIDEO_EXTS) or is_supported_video_url(url, mode=mode):
        if any(p in low for p in ("/watch/", "/episode/", "/episodes/", "/seasons/", "/anime/")):
            return "chapter"
        return "video"
    if any(clean_p.endswith(ext) for ext in FILE_EXTS):
        return "file"
    if is_manga_or_chapter_context(url, title) or extract_real_chapter_number(url) is not None:
        return "chapter"
    return "web"