# ==========================================
# ملف: account_lookup.py
# ==========================================
# ==========================================
# ملف جلب معلومات الحسابات العامة
# ==========================================
import re
import json
import html
import time  # تمت إضافة time لأنها ناقصة وتسبب مشاكل في الكاش
import requests
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse
from concurrent.futures import ThreadPoolExecutor

from config import (PLATFORMS, PLATFORM_NAMES, PLAT_CODES, PLAT_CODE_OF, PLAT_URLS, 
                    PLAT_DOMAINS, ACCOUNT_ACTORS, BROWSER_HEADERS, APIFY_TOKEN)
from ai_features import ask_ai
from utils import esc

USER_RE = re.compile(r"[A-Za-z0-9._\-]{1,60}")
_acct_cache = {}
ACCT_CACHE_SECS = 600
ACCT_SLOTS = threading.BoundedSemaphore(3)
ACCT_HELP = ("👤 <b>معلومات حساب عام</b>\n\n"
             "أرسل <code>@اسم_المستخدم</code> فتظهر لك أزرار اختيار المنصة أو البحث الشامل.\n\n"
             "أو مباشرة:\n<code>/حساب تيك mrbeast</code>\n<code>/حساب انستا nasa</code>\n<code>/حساب شامل mrbeast</code>\n"
             "أو رابط الحساب: <code>/حساب https://www.tiktok.com/@mrbeast</code>\n"
             "أضف كلمة <code>تحليل</code> في آخر الأمر ليحلّل الذكاء الاصطناعي الحساب.\n\n"
             "ℹ️ تُعرض البيانات العامة فقط.")

def _pick(d, *keys):
    for k in keys:
        cur = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur not in (None, "", []): return cur
    return None

def _num(v):
    try:
        if v is None or isinstance(v, bool): return None
        if isinstance(v, (int, float)): return int(v)
        s = str(v).replace(",", "").replace(" ", "").strip()
        mult = 1
        if s[-1:].upper() in ("K", "M", "B"):
            mult = {"K": 1e3, "M": 1e6, "B": 1e9}[s[-1].upper()]; s = s[:-1]
        return int(float(s) * mult)
    except Exception:
        return None

def _strip(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()

def _meta(page, prop):
    m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']*)["\']' % re.escape(prop), page, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(prop), page, re.I)
    return html.unescape(m.group(1)).strip() if m else None

def _get(url, headers=None, timeout=15):
    h = dict(BROWSER_HEADERS); h["Accept-Language"] = "en-US,en;q=0.9"
    if headers: h.update(headers)
    return requests.get(url, headers=h, timeout=timeout, allow_redirects=True)

def _new_prof(platform, user):
    return {"platform": platform, "username": user, "id": None, "name": None, "bio": None, "bio_link": None,
            "verified": None, "private": None, "region": None, "language": None, "created": None,
            "followers": None, "following": None, "likes": None, "posts": None, "friends": None,
            "avatar": None, "url": PLAT_URLS.get(platform, "").format(u=user), "source": ""}

def _merge_prof(a, b):
    if not a: return b
    if not b: return a
    for k, v in b.items():
        if a.get(k) in (None, "") and v not in (None, ""): a[k] = v
    return a

# ---------- قراءة صفحة الحساب العامة مباشرة ----------
def fetch_tiktok(user):
    r = _get(PLAT_URLS["tiktok"].format(u=user))
    if r.status_code == 404: return None, "الحساب غير موجود"
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m: return None, f"تيك توك رفض القراءة المباشرة (HTTP {r.status_code})"
    try:
        detail = (json.loads(m.group(1)).get("__DEFAULT_SCOPE__") or {}).get("webapp.user-detail") or {}
        ui = detail.get("userInfo")
    except Exception:
        return None, "تعذر تحليل صفحة تيك توك"
    if not ui or not ui.get("user"): return None, "الحساب غير موجود أو غير متاح"
    u = ui["user"]; st = ui.get("stats") or {}; st2 = ui.get("statsV2") or {}
    g = lambda k: st.get(k) if st.get(k) is not None else _num(st2.get(k))
    p = _new_prof("tiktok", u.get("uniqueId") or user)
    p.update(id=str(u.get("id") or "") or None, name=u.get("nickname"), bio=u.get("signature") or None,
             bio_link=(u.get("bioLink") or {}).get("link"), verified=bool(u.get("verified")), private=bool(u.get("privateAccount")),
             region=u.get("region") or None, language=u.get("language") or None, created=u.get("createTime") or None,
             followers=g("followerCount"), following=g("followingCount"), likes=g("heartCount"), posts=g("videoCount"),
             friends=g("friendCount"), avatar=u.get("avatarLarger") or u.get("avatarMedium"), source="direct")
    if not p["created"] and p["id"] and p["id"].isdigit():
        ts = int(p["id"]) >> 32
        if 1400000000 < ts < 4000000000: p["created"] = ts
    return p, ""

def fetch_instagram(user):
    try:
        r = _get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={user}",
                 headers={"X-IG-App-ID": "936619743392459", "Accept": "*/*", "Referer": f"https://www.instagram.com/{user}/"})
        if r.status_code == 200:
            u = (r.json().get("data") or {}).get("user")
            if u:
                p = _new_prof("instagram", user)
                p.update(id=u.get("id"), name=u.get("full_name"), bio=u.get("biography") or None, bio_link=u.get("external_url"),
                         verified=u.get("is_verified"), private=u.get("is_private"),
                         followers=(u.get("edge_followed_by") or {}).get("count"), following=(u.get("edge_follow") or {}).get("count"),
                         posts=(u.get("edge_owner_to_timeline_media") or {}).get("count"),
                         avatar=u.get("profile_pic_url_hd") or u.get("profile_pic_url"), source="direct")
                return p, ""
    except Exception:
        pass
    r = _get(PLAT_URLS["instagram"].format(u=user))
    if r.status_code == 404: return None, "الحساب غير موجود"
    desc = _meta(r.text, "og:description") or ""
    title = _meta(r.text, "og:title") or ""
    m = re.search(r"([\d.,]+[KMB]?)\s+Followers,\s*([\d.,]+[KMB]?)\s+Following,\s*([\d.,]+[KMB]?)\s+Posts", desc, re.I)
    if not m and (not title or title.strip().lower().startswith("instagram")):
        return None, "إنستجرام يطلب تسجيل الدخول للقراءة المباشرة"
    p = _new_prof("instagram", user)
    if m: p.update(followers=_num(m.group(1)), following=_num(m.group(2)), posts=_num(m.group(3)))
    p.update(name=re.sub(r"\s*\(@.*", "", title) or None, avatar=_meta(r.text, "og:image"), source="direct")
    return p, ""

def fetch_youtube(user):
    r = _get(PLAT_URLS["youtube"].format(u=user), headers={"Cookie": "CONSENT=YES+1; SOCS=CAI"})
    if r.status_code == 404: return None, "القناة غير موجودة"
    t = r.text
    title = _meta(t, "og:title")
    if not title or title.strip().lower() == "youtube": return None, "تعذر قراءة صفحة يوتيوب"
    p = _new_prof("youtube", user)
    subs = re.search(r"([\d.,]+[KMB]?)\s+subscribers", t, re.I); vids = re.search(r"([\d.,]+[KMB]?)\s+videos", t, re.I)
    cid = re.search(r'"channelId":"(UC[\w-]{20,})"', t)
    p.update(name=title, bio=_meta(t, "og:description"), avatar=_meta(t, "og:image"), id=cid.group(1) if cid else None,
             followers=_num(subs.group(1)) if subs else None, posts=_num(vids.group(1)) if vids else None, source="direct")
    return p, ""

def fetch_telegram(user):
    r = _get(PLAT_URLS["telegram"].format(u=user)); t = r.text
    mt = re.search(r'<div class="tgme_page_title"[^>]*>(.*?)</div>', t, re.S)
    if r.status_code != 200 or not mt: return None, "لم أجد حساباً عاماً بهذا الاسم"
    name = _strip(mt.group(1))
    md = re.search(r'<div class="tgme_page_description[^"]*"[^>]*>(.*?)</div>', t, re.S)
    me = re.search(r'<div class="tgme_page_extra">(.*?)</div>', t, re.S)
    extra = _strip(me.group(1)) if me else ""
    mf = re.search(r"([\d\s,.]+)\s*(?:subscribers|members)", extra, re.I)
    img = _meta(t, "og:image")
    if name.lower().lstrip("@") == user.lower() and not md and not mf and (not img or "t_logo" in img):
        return None, "لم أجد حساباً عاماً بهذا الاسم"
    p = _new_prof("telegram", user)
    p.update(name=name, bio=_strip(md.group(1)) if md else None, followers=_num(mf.group(1)) if mf else None,
             avatar=img if img and "t_logo" not in img else None, source="direct")
    return p, ""

def fetch_x(user):
    try:
        fr = _get(f"https://api.fxtwitter.com/{user}", headers={"Accept": "application/json"}, timeout=12)
        if fr.status_code == 200:
            fu = (fr.json() or {}).get("user")
            if fu:
                created = None
                try: created = int(datetime.strptime(fu.get("joined", ""), "%a %b %d %H:%M:%S %z %Y").timestamp())
                except Exception: pass
                ver = fu.get("verification") or {}
                p = _new_prof("x", fu.get("screen_name") or user)
                p.update(id=str(fu.get("id") or "") or None, name=fu.get("name"), bio=fu.get("description") or None,
                         bio_link=(fu.get("website") or {}).get("url") if isinstance(fu.get("website"), dict) else fu.get("website"),
                         verified=bool(ver.get("verified")) if isinstance(ver, dict) else None, private=bool(fu.get("protected")),
                         region=fu.get("location") or None, followers=fu.get("followers"), following=fu.get("following"),
                         posts=fu.get("tweets"), likes=fu.get("likes"), created=created, avatar=fu.get("avatar_url"), source="direct")
                return p, ""
        elif fr.status_code == 404:
            return None, "الحساب غير موجود"
    except Exception:
        pass
    r = _get(f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{user}")
    if r.status_code != 200: return None, f"X لا يسمح بالقراءة المباشرة (HTTP {r.status_code})"
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m: return None, "X لا يسمح بالقراءة المباشرة"
    try:
        entries = (((json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}).get("timeline") or {}).get("entries") or []
        u = next((((e.get("content") or {}).get("tweet") or {}).get("user") for e in entries
                  if ((e.get("content") or {}).get("tweet") or {}).get("user")), None)
    except Exception:
        u = None
    if not u: return None, "تعذر قراءة بيانات الحساب من X"
    p = _new_prof("x", u.get("screen_name") or user)
    created = None
    try: created = int(datetime.strptime(u.get("created_at", ""), "%a %b %d %H:%M:%S %z %Y").timestamp())
    except Exception: pass
    p.update(id=u.get("id_str"), name=u.get("name"), bio=u.get("description") or None,
             verified=bool(u.get("verified") or u.get("is_blue_verified")), private=bool(u.get("protected")),
             followers=u.get("followers_count"), following=u.get("friends_count"), posts=u.get("statuses_count"),
             likes=u.get("favourites_count"), created=created,
             avatar=(u.get("profile_image_url_https") or "").replace("_normal", "_400x400") or None, source="direct")
    return p, ""

def fetch_facebook(user):
    r = _get(PLAT_URLS["facebook"].format(u=user), headers={"User-Agent": "facebookexternalhit/1.1"})
    if r.status_code == 404: return None, "الصفحة غير موجودة"
    title = _meta(r.text, "og:title")
    if not title or title.strip().lower() in ("facebook", "log in or sign up to view", "error"):
        return None, "فيسبوك لا يعرض هذه الصفحة بدون تسجيل دخول"
    desc = _meta(r.text, "og:description") or ""
    mf = re.search(r"([\d.,]+[KMB]?)\s+(?:followers|likes)", desc, re.I)
    p = _new_prof("facebook", user)
    p.update(name=title, bio=desc[:300] or None, followers=_num(mf.group(1)) if mf else None, avatar=_meta(r.text, "og:image"), source="direct")
    return p, ""

FETCHERS = {"tiktok": fetch_tiktok, "instagram": fetch_instagram, "x": fetch_x, "youtube": fetch_youtube,
            "telegram": fetch_telegram, "facebook": fetch_facebook}

def fetch_direct(platform, user):
    try: return FETCHERS[platform](user)
    except Exception as e: return None, f"{type(e).__name__}: {str(e)[:100]}"

# ---------- البحث في الويب و Apify ----------
def web_search(query, n=6):
    out = []
    try:
        r = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=BROWSER_HEADERS, timeout=15)
        if r.status_code == 200:
            anchors = list(re.finditer(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S))
            for i, a in enumerate(anchors):
                end = anchors[i + 1].start() if i + 1 < len(anchors) else len(r.text)
                sn = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', r.text[a.end():end], re.S)
                href = a.group(1)
                if "uddg=" in href:
                    href = unquote((parse_qs(urlparse("https:" + href if href.startswith("//") else href).query).get("uddg") or [href])[0])
                out.append({"title": _strip(a.group(2)), "url": href, "snippet": _strip(sn.group(1)) if sn else ""})
    except Exception as e:
        print("ddg:", e)
    return out[:n]

def web_lookup(platform, user):
    if platform == "all": q = f'"@{user}" OR "{user}" profile social media'
    else: q = f'{user} {PLATFORM_NAMES[platform]} @{user}'
    results = web_search(q)
    if not results: return ""
    material = "\n".join(f"- {r['title']} | {r['url']} | {r['snippet'][:250]}" for r in results)[:3500]
    summary = ask_ai(0, f"نتائج بحث الويب عن الحساب «{user}»:\n{material}",
                     system_prompt="لخّص بالعربية في 3 إلى 6 أسطر فقط ما تذكره النتائج صراحةً عن هذا الحساب.")
    if summary.startswith("⚠️"):
        summary = "\n".join(f"• {r['title'][:80]}" for r in results[:4])
    links = [r["url"] for r in results if PLAT_DOMAINS.get(platform, "~") in r["url"] or platform == "all"][:3]
    return summary + (("\n🔗 " + "\n🔗 ".join(links)) if links else "")

def _apify_items(actor, run_input):
    url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(url, params={"timeout": 75, "limit": 1, "memory": 512, "format": "json", "clean": "true"},
                      headers={"Authorization": f"Bearer {APIFY_TOKEN}", "Content-Type": "application/json"},
                      json=run_input, timeout=90)
    if r.status_code in (200, 201):
        data = r.json()
        return data if isinstance(data, list) else []
    try: msg = (r.json().get("error") or {}).get("message") or r.text
    except Exception: msg = r.text
    raise RuntimeError(f"Apify HTTP {r.status_code}: {str(msg)[:150]}")

def apify_profile(platform, username):
    if platform not in ACCOUNT_ACTORS: return None, "لا يوجد Actor لهذه المنصة"
    if not APIFY_TOKEN: return None, "مفتاح Apify غير مضبوط."
    actor, mk = ACCOUNT_ACTORS[platform]
    try: items = _apify_items(actor, mk(username))
    except Exception as e: return None, str(e)[:200]
    if not items: return None, "لم أجد الحساب في Apify."
    it = items[0]
    p = _new_prof(platform, _pick(it, "uniqueId", "authorMeta.name", "username", "userName", "screen_name", "handle") or username)
    p.update(id=str(_pick(it, "authorMeta.id", "id", "userId", "channelId") or "") or None,
             name=_pick(it, "nickName", "authorMeta.nickName", "fullName", "name", "displayName", "channelName", "title"),
             bio=_pick(it, "signature", "authorMeta.signature", "biography", "bio", "description", "channelDescription"),
             followers=_num(_pick(it, "fans", "authorMeta.fans", "followersCount", "followers", "subscribersCount")),
             following=_num(_pick(it, "following", "authorMeta.following", "followsCount", "followingCount")),
             likes=_num(_pick(it, "heart", "authorMeta.heart", "likesCount")),
             posts=_num(_pick(it, "video", "authorMeta.video", "postsCount", "mediaCount", "videosCount")),
             avatar=_pick(it, "avatar", "authorMeta.avatar", "profilePicUrlHD", "profilePicUrl"), source="apify")
    return p, ""

# ---------- دمج الطرق الثلاث ----------
def lookup_account(platform, user, deep=False):
    key = (platform, user.lower(), bool(deep))
    hit = _acct_cache.get(key)
    if hit and time.time() - hit[0] < ACCT_CACHE_SECS: return hit[1]
    res = {"profiles": [], "web": "", "notes": []}
    if platform == "all":
        with ThreadPoolExecutor(max_workers=4) as ex:
            wf = ex.submit(web_lookup, "all", user)
            futs = {pl: ex.submit(fetch_direct, pl, user) for pl in PLATFORMS}
            for pl, f in futs.items():
                try: prof, err = f.result(timeout=60)
                except Exception as e: prof, err = None, str(e)[:100]
                if prof: res["profiles"].append(prof)
                else: res["notes"].append((pl, err))
            try: res["web"] = wf.result(timeout=60)
            except Exception: pass
    else:
        with ThreadPoolExecutor(max_workers=2) as ex:
            wf = ex.submit(web_lookup, platform, user)
            df = ex.submit(fetch_direct, platform, user)
            try: prof, err = df.result(timeout=60)
            except Exception as e: prof, err = None, str(e)[:100]
            if (not prof or deep) and platform in ACCOUNT_ACTORS:
                ap, aerr = apify_profile(platform, user)
                if ap: prof = _merge_prof(ap, prof) if prof else ap
                else: res["notes"].append(("apify", aerr))
            try: res["web"] = wf.result(timeout=60)
            except Exception: pass
        if prof: res["profiles"].append(prof)
        elif err: res["notes"].append((platform, err))
    if res["profiles"] or res["web"]:
        _acct_cache[key] = (time.time(), res)
        if len(_acct_cache) > 200:
            for k in sorted(_acct_cache, key=lambda x: _acct_cache[x][0])[:60]: _acct_cache.pop(k, None)
    return res

# ---------- العرض ----------
def _age_text(ts):
    d = datetime.fromtimestamp(ts, timezone.utc); now = datetime.now(timezone.utc)
    months = (now.year - d.year) * 12 + now.month - d.month - (1 if now.day < d.day else 0)
    y, m = divmod(max(months, 0), 12)
    return " و".join(x for x in ((f"{y} سنة" if y else ""), (f"{m} شهر" if m else "")) if x) or "أقل من شهر"

def _created_text(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d-%m-%Y %H:%M:%S")

def _n(v):
    try: return f"{int(v):,}"
    except Exception: return str(v)

def prof_public(p):
    q = dict(p); q["platform_name"] = PLATFORM_NAMES.get(p["platform"], p["platform"])
    if p.get("created"):
        try: q["created_txt"] = _created_text(int(p["created"])); q["age_txt"] = _age_text(int(p["created"]))
        except Exception: pass
    return q

def account_text(p):
    q = prof_public(p)
    yn = lambda v: "نعم" if v else "لا"
    L = [f"<b>{esc(q['platform_name'])}</b>", "• معلومات الحساب"]
    rows = [("ايدي الحساب", q.get("id")), ("المعرف", q.get("username")), ("الاسم", q.get("name")), ("البايو", (q.get("bio") or "")[:300] or None),
            ("موثق", yn(q["verified"]) if q.get("verified") is not None else None), ("حساب خاص", yn(q["private"]) if q.get("private") is not None else None),
            ("الرابط في البايو", q.get("bio_link")), ("منطقة الحساب", q.get("region")), ("لغة المستخدم", q.get("language")),
            ("وقت إنشاء الحساب (UTC)", q.get("created_txt")), ("عمر الحساب", q.get("age_txt"))]
    L += [f"- {k}: {esc(v)}" for k, v in rows if v not in (None, "")]
    st = [("المتابعين", q.get("followers")), ("يتابع", q.get("following")), ("الإعجابات", q.get("likes")), ("المنشورات", q.get("posts"))]
    st_txt = [f"{k}: <b>{_n(v)}</b>" for k, v in st if v is not None]
    if st_txt: L.append("• الإحصاءات\n" + " | ".join(st_txt))
    return "\n".join(L)

def account_buttons(username):
    rows = []
    for plat, code in PLAT_CODES.items():
        rows.append([{"text": f"🔍 {PLATFORM_NAMES[code]}", "callback_data": f"acc|{code}|{username}"}])
    rows.append([{"text": "🌐 بحث شامل", "callback_data": f"acc|all|{username}"}, {"text": "🧠 تحليل ذكي", "callback_data": f"acc|all|{username}|deep"}])
    return {"inline_keyboard": rows}

# ==========================================
# الدوال الناقصة التي تمت إضافتها لإصلاح البوت
# ==========================================

def show_account_picker(chat_id, username):
    """إظهار أزرار اختيار المنصة للمستخدم"""
    from telegram_api import send_message
    msg = f"👤 اختر المنصة للبحث عن الحساب: <code>{esc(username)}</code>"
    send_message(chat_id, msg, reply_markup=json.dumps(account_buttons(username)))

def cmd_account(chat_id, args):
    """معالجة أمر /حساب"""
    from telegram_api import send_message
    if not args:
        send_message(chat_id, ACCT_HELP)
        return
    
    parts = args.split()
    platform = None
    username = parts[-1]
    deep = False
    
    if len(parts) > 1 and parts[0].lower() in PLATFORM_ALIASES:
        platform = PLATFORM_ALIASES[parts[0].lower()]
    elif parts[-1].lower() == "تحليل":
        deep = True
        username = parts[-2] if len(parts) > 1 else ""
        if len(parts) > 2 and parts[0].lower() in PLATFORM_ALIASES:
            platform = PLATFORM_ALIASES[parts[0].lower()]

    if username.startswith("http"):
        for host, p in URL_HOSTS:
            if host in username:
                platform = p
                parsed = urlparse(username)
                path = parsed.path.strip("/")
                if path.startswith("@"):
                    username = path[1:].split("/")[0]
                elif p == "youtube" and path.startswith("c/"):
                    username = path[2:].split("/")[0]
                else:
                    username = path.split("/")[0]
                break
                
    username = username.lstrip("@")
    if not username:
        send_message(chat_id, ACCT_HELP)
        return
        
    if not platform or platform == "all":
        show_account_picker(chat_id, username)
    else:
        send_message(chat_id, f"🔍 جاري البحث عن <code>{esc(username)}</code> في {PLATFORM_NAMES.get(platform, platform)}...")
        res = lookup_account(platform, username, deep=deep)
        if res["profiles"]:
            for p in res["profiles"]:
                send_message(chat_id, account_text(p))
        if res["web"]:
            send_message(chat_id, f"🌐 <b>معلومات من الويب:</b>\n\n{esc(res['web'])}")
        if not res["profiles"] and not res["web"]:
            send_message(chat_id, "❌ لم يتم العثور على معلومات.")

def account_callback(chat_id, data):
    """معالجة ضغطات الأزرار (acc|tiktok|mrbeast)"""
    from telegram_api import send_message
    parts = data.split("|")
    if len(parts) < 3: return
    platform = parts[1]
    username = parts[2]
    deep = len(parts) > 3 and parts[3] == "deep"
    
    send_message(chat_id, f"🔍 جاري البحث عن <code>{esc(username)}</code>...")
    res = lookup_account(platform, username, deep=deep)
    
    if res["profiles"]:
        for p in res["profiles"]:
            send_message(chat_id, account_text(p))
    if res["web"]:
        send_message(chat_id, f"🌐 <b>معلومات من الويب:</b>\n\n{esc(res['web'])}")
    if not res["profiles"] and not res["web"]:
        send_message(chat_id, "❌ لم يتم العثور على معلومات.")