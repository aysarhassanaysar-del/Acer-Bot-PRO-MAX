# ==========================================
# الجزء 4: search_feature.py
# واجهة البوت الموحدة، الأزرار، عرض الحجم الحقيقي لكل دقة ومدة الحلقة، والتنقل
# (تستدعي تلقائياً search_core + anime_sites + media_downloader)
# ==========================================
import time
import json
import asyncio
from urllib.parse import urlparse
from config import TELEGRAM_TOKEN
from telegram_api import send_message, TG_SESSION
from utils import esc, log_error, store_url, safe_url

from search_core import (
    PLATFORM_DOMAINS,
    PLATFORM_LABELS,
    search_sessions,
    search_results_cache,
    chapter_merge_sessions,
    saved_user_domains,
    user_domain_cookies,
    awaiting_cookie_for,
    get_stored_url,
    is_ad_media_url,
    clean_domain,
    is_non_content_page,
    save_domain_for_user,
    get_cookie_for_url,
    parse_cookie_input,
    create_status_msg,
    update_status_msg,
    extract_site_cookies,
    stealth_get,
    ai_normalize_search_query,
    fetch_video_card_meta,
    search_serper,
    search_youtube,
    search_ddg_fallback,
)
from anime_sites import (
    ANIME_SITES_REGISTRY,
    DEFAULT_ANIME_DOMAINS,
    build_domain_entry_candidates,
    is_pixeldrain_url,
    extract_episode_number,
    count_episodes_in_items,
    is_supported_video_url,
    inspect_page_resources,
    classify_url,
)
from media_downloader import (
    download_signed_video_and_send,
    send_single_chapter,
    merge_chapters_range,
    download_direct_file_with_cookie,
)


def show_search_platforms(chat_id):
    uid = str(chat_id)
    search_sessions[uid] = {"mode": "all", "domain": None, "awaiting": False, "t": time.time()}
    kb_rows = [
        [{"text": "🌐 الكل + مواقع الأنمي", "callback_data": "srch|set|all"}, {"text": "📦 Pixeldrain", "callback_data": "srch|set|pd"}],
        [{"text": "🎌 WitAnime", "callback_data": "srch|usedom|witanime.site"}, {"text": "🎌 Anime4up", "callback_data": "srch|usedom|y.mpta00a.shop"}],
        [{"text": "🎌 Animerco", "callback_data": "srch|usedom|jet.animerco.org"}, {"text": "🎬 يوتيوب", "callback_data": "srch|set|yt"}],
        [{"text": "🎵 تيك توك", "callback_data": "srch|set|tt"}, {"text": "📸 إنستغرام", "callback_data": "srch|set|ig"}],
        [{"text": "𝕏 إكس", "callback_data": "srch|set|x"}, {"text": "📘 فيسبوك", "callback_data": "srch|set|fb"}],
    ]
    for dom in saved_user_domains.get(uid, [])[:4]:
        if dom in ANIME_SITES_REGISTRY:
            continue
        has_ck = "✅" if get_cookie_for_url(uid, dom) else ""
        kb_rows.append([{"text": f"📌 بحث في: {dom} {has_ck}", "callback_data": f"srch|usedom|{dom}"}])
    kb_rows.append([
        {"text": "➕ دومين مخصص", "callback_data": "srch|dom"},
        {"text": "🍪 كوكيز المواقع", "callback_data": "srch|ckmenu"},
    ])
    send_message(
        chat_id,
        "⚡ <b>اختر موقع الأنمي أو المنصة للبحث:</b>\n"
        "✨ <i>مواقع الأنمي المسجلة (WitAnime, Anime4up, Animerco) مدمجة مع كشف مدة الحلقة وحجم كل جودة وحجب الإعلانات.</i>",
        reply_markup=json.dumps({"inline_keyboard": kb_rows}),
    )


def _show_domain_picker(chat_id):
    uid = str(chat_id)
    saved = saved_user_domains.get(uid, [])
    rows = [
        [{"text": "🎌 witanime.site", "callback_data": "srch|usedom|witanime.site"}],
        [{"text": "🎌 y.mpta00a.shop (Anime4up)", "callback_data": "srch|usedom|y.mpta00a.shop"}],
        [{"text": "🎌 jet.animerco.org", "callback_data": "srch|usedom|jet.animerco.org"}],
        [{"text": "📦 pixeldrain.com", "callback_data": "srch|set|pd"}],
    ]
    rows += [[{"text": f"📌 {dom}", "callback_data": f"srch|usedom|{dom}"}] for dom in saved[:6] if dom not in ANIME_SITES_REGISTRY]
    send_message(
        chat_id,
        "🎯 <b>إضافة أو اختيار دومين للبحث داخله</b>\nأرسل رابط أو دومين الموقع لحفظه والبحث داخله:",
        reply_markup=json.dumps({"inline_keyboard": rows}),
    )


def _show_cookie_menu(chat_id):
    uid = str(chat_id)
    session = search_sessions.get(uid) or {}
    cur_dom = session.get("domain") or (saved_user_domains.get(uid) or [None])[0]
    rows = []
    all_doms = list(dict.fromkeys(DEFAULT_ANIME_DOMAINS + saved_user_domains.get(uid, [])))[:6]
    for dom in all_doms:
        ck_badge = "🍪 محفوظ" if get_cookie_for_url(uid, dom) else "بدون كوكيز"
        rows.append([
            {"text": f"🍪 {dom} ({ck_badge})", "callback_data": f"srch|ckset|{dom}"},
            {"text": "⚡ استخراج تلقائي", "callback_data": f"srch|ckauto|{dom}"},
        ])
    if cur_dom and cur_dom not in all_doms:
        rows.append([{"text": f"⚡ استخراج كوكيز {cur_dom}", "callback_data": f"srch|ckauto|{cur_dom}"}])
    rows.append([{"text": "⬅️ رجوع", "callback_data": "srch|menu"}])
    send_message(
        chat_id,
        "🍪 <b>إدارة واستخراج كوكيز المواقع المحمية</b>\n"
        "• اختر <b>استخراج تلقائي</b> لمحاولة سحب كوكيز الموقع\n"
        "• أو اختر اسم الموقع ثم ألصق نص الكوكيز",
        reply_markup=json.dumps({"inline_keyboard": rows}),
    )


def handle_search_callback(chat_id, data):
    uid = str(chat_id)
    session = search_sessions.setdefault(uid, {"mode": "all", "domain": None, "awaiting": False, "t": time.time()})
    session["t"] = time.time()
    parts = data.split("|")

    if len(parts) >= 2 and parts[1] == "menu":
        show_search_platforms(chat_id)
        return

    if len(parts) >= 2 and parts[1] == "ckmenu":
        _show_cookie_menu(chat_id)
        return

    if len(parts) >= 3 and parts[1] == "ckset":
        dom = clean_domain(parts[2])
        if dom:
            awaiting_cookie_for[uid] = dom
            send_message(chat_id, f"🍪 أرسل الآن كوكيز الموقع <code>{esc(dom)}</code>:")
        return

    if len(parts) >= 3 and parts[1] == "ckauto":
        dom = clean_domain(parts[2])
        if dom:
            st_id = create_status_msg(chat_id, f"⏳ <b>جاري التحقق واستخراج كوكيز {esc(dom)}...</b>")
            extracted = extract_site_cookies(dom, extra_cookie=get_cookie_for_url(uid, dom))
            if extracted:
                user_domain_cookies.setdefault(uid, {})[dom] = extracted
                save_domain_for_user(uid, dom)
                update_status_msg(chat_id, st_id, f"✅ <b>تم التحقق وحفظ كوكيز {esc(dom)} بنجاح.</b>")
            else:
                update_status_msg(chat_id, st_id, "⚠️ <b>فشل الاستخراج التلقائي</b> — ألصق الكوكيز يدوياً عبر اختيار اسم الموقع.")
        return

    if len(parts) >= 2 and parts[1] == "dom":
        session["mode"] = "domain"
        session["awaiting"] = True
        _show_domain_picker(chat_id)
        return

    if len(parts) >= 3 and parts[1] == "usedom":
        dom = clean_domain(parts[2])
        if dom:
            save_domain_for_user(uid, dom)
            session["mode"] = "domain"
            session["domain"] = dom
            session["awaiting"] = True
            send_message(chat_id, f"🎯 الموقع المحدد: <code>{esc(dom)}</code>\nاكتب الآن اسم الأنمي للبحث:")
        return

    if len(parts) >= 3 and parts[1] == "set":
        mode = parts[2] if parts[2] in PLATFORM_DOMAINS else "all"
        session["mode"] = mode
        session["domain"] = None
        session["awaiting"] = True
        label = PLATFORM_LABELS.get(mode, "بحث")
        send_message(chat_id, f"⚡ <b>{label}</b> — اكتب اسم الأنمي أو الكرتون أو <code>#هاشتاغ</code>:")
        return

    if len(parts) >= 3 and parts[1] == "dlfile":
        u = get_stored_url(parts[2])
        if u:
            download_direct_file_with_cookie(chat_id, u)
        return

    if len(parts) >= 4 and parts[1] == "dlq":
        sid = parts[2]
        try:
            q_idx = int(parts[3])
        except Exception:
            return
        entry = search_results_cache.get(sid)
        if not entry:
            send_message(chat_id, "⚠️ انتهت الجلسة، أعد البحث.")
            return
        cur_item = entry["items"][entry.get("cur_idx", 0)]
        dl_links = entry.get("active_dl_links") or cur_item.get("download_links") or []
        exp_dur = entry.get("active_duration") or cur_item.get("duration") or ""
        if 0 <= q_idx < len(dl_links):
            chosen = dl_links[q_idx]
            ref_u = entry.get("active_url") or cur_item.get("url")
            download_signed_video_and_send(
                chat_id,
                chosen["url"],
                referer_url=ref_u,
                quality_label=chosen.get("label", ""),
                expected_duration=exp_dur,
            )
        return

    if len(parts) >= 3 and parts[1] == "dlpage":
        u = get_stored_url(parts[2])
        if u:
            send_single_chapter(chat_id, u, quality="med")
        return

    if len(parts) >= 4 and parts[1] == "pg":
        sid = parts[2]
        try:
            idx = int(parts[3])
        except Exception:
            return
        _render_result_page(chat_id, sid, idx)
        return

    if len(parts) >= 4 and parts[1] == "ch":
        sid = parts[2]
        action = parts[3]
        entry = search_results_cache.get(sid)
        if not entry:
            send_message(chat_id, "⚠️ انتهت الجلسة، أعد البحث.")
            return
        cur_idx = entry.get("cur_idx", 0)
        cur_item = entry["items"][cur_idx]
        cur_url = entry.get("active_url") or cur_item["url"]
        q_level = entry.get("quality", "med")
        chapters_map = cur_item.get("chapters_map") or {}
        sorted_nums = cur_item.get("chapter_nums") or []

        if action in ("prev", "next") and sorted_nums:
            cur_n = entry.get("active_ch_num", sorted_nums[0])
            pos = sorted_nums.index(cur_n) if cur_n in sorted_nums else 0
            new_pos = max(0, pos - 1) if action == "prev" else min(len(sorted_nums) - 1, pos + 1)
            new_num = sorted_nums[new_pos]
            new_url = chapters_map.get(new_num, cur_url)
            entry["active_ch_num"] = new_num
            entry["active_url"] = new_url
            entry["active_dl_links"] = None
            entry["active_duration"] = ""
            _render_result_page(chat_id, sid, cur_idx)
            return

        if action == "pick":
            if not sorted_nums:
                send_message(chat_id, "⚠️ لم يتم العثور على حلقات/فصول في هذا الرابط.")
                return
            chapter_merge_sessions[uid] = {
                "sid": sid,
                "url": cur_url,
                "quality": q_level,
                "chapters_map": chapters_map,
                "chapter_nums": sorted_nums,
                "t": time.time(),
            }
            send_message(
                chat_id,
                f"🔢 <b>الحلقات المتاحة ({len(sorted_nums)}):</b>\n"
                f"من <b>{sorted_nums[0]}</b> إلى <b>{sorted_nums[-1]}</b>\n\n"
                f"• أرسل رقم حلقة مثل: <code>{sorted_nums[0]}</code>\n"
                f"• أو أرسل نطاقاً مثل: <code>{sorted_nums[0]}-{sorted_nums[min(len(sorted_nums)-1, 4)]}</code>"
            )
            return

        if action == "dl":
            send_single_chapter(chat_id, cur_url, quality=q_level)
            return

        if action == "qual":
            order = {"orig": "med", "med": "low", "low": "orig"}
            entry["quality"] = order.get(q_level, "med")
            _render_result_page(chat_id, sid, cur_idx)
            return

        if action == "merge":
            if not sorted_nums:
                send_message(chat_id, "⚠️ لا توجد فصول متاحة للدمج في هذا الرابط.")
                return
            chapter_merge_sessions[uid] = {
                "sid": sid,
                "url": cur_url,
                "quality": q_level,
                "chapters_map": chapters_map,
                "chapter_nums": sorted_nums,
                "t": time.time(),
            }
            send_message(
                chat_id,
                f"📚 <b>دمج الفصول</b> (الدقة الحالية: <b>{q_level}</b>)\n"
                f"المتاح: <b>{sorted_nums[0]} → {sorted_nums[-1]}</b> — أرسل النطاق مثل <code>{sorted_nums[0]}-{sorted_nums[min(len(sorted_nums)-1, 4)]}</code>:"
            )
            return


def handle_search_text_input(chat_id, text):
    import re
    uid = str(chat_id)
    raw = text.strip()

    if uid in awaiting_cookie_for:
        dom = awaiting_cookie_for.pop(uid)
        parsed = parse_cookie_input(raw)
        if parsed:
            user_domain_cookies.setdefault(uid, {})[dom] = parsed
            save_domain_for_user(uid, dom)
            send_message(chat_id, f"✅ تم حفظ الكوكيز للدومين: <code>{esc(dom)}</code>")
        else:
            send_message(chat_id, "⚠️ صيغة الكوكيز غير واضحة.")
        return

    if uid in chapter_merge_sessions:
        m_sess = chapter_merge_sessions.get(uid) or {}
        cmap = m_sess.get("chapters_map") or {}
        m_range = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[-–—: إلى]+\s*(\d+(?:\.\d+)?)\s*$", raw)
        if m_range:
            chapter_merge_sessions.pop(uid, None)
            s_n = int(float(m_range.group(1))) if float(m_range.group(1)).is_integer() else float(m_range.group(1))
            e_n = int(float(m_range.group(2))) if float(m_range.group(2)).is_integer() else float(m_range.group(2))
            merge_chapters_range(chat_id, m_sess["url"], s_n, e_n, quality=m_sess.get("quality", "med"), chapters_map=cmap)
            return
        m_single = re.match(r"^\s*(\d+(?:\.\d+)?)\s*$", raw)
        if m_single:
            chapter_merge_sessions.pop(uid, None)
            val = float(m_single.group(1))
            target_n = int(val) if val.is_integer() else val
            if target_n in cmap:
                sid = m_sess.get("sid")
                if sid and sid in search_results_cache:
                    entry = search_results_cache[sid]
                    entry["active_ch_num"] = target_n
                    entry["active_url"] = cmap[target_n]
                    entry["active_dl_links"] = None
                    entry["active_duration"] = ""
                    _render_result_page(chat_id, sid, entry.get("cur_idx", 0))
                else:
                    inspect_direct_url(chat_id, cmap[target_n])
            else:
                send_message(chat_id, f"⚠️ الحلقة/الفصل <b>{target_n}</b> غير موجود.")
            return
        chapter_merge_sessions.pop(uid, None)

    session = search_sessions.get(uid) or {"mode": "all", "domain": None, "t": time.time()}
    mode = session.get("mode", "all")
    saved_domain = session.get("domain")
    parts = raw.split(None, 1)
    maybe_dom = clean_domain(parts[0]) if parts else None

    if mode == "domain":
        if maybe_dom and len(parts) == 2:
            save_domain_for_user(uid, maybe_dom)
            session["domain"] = maybe_dom
            session["awaiting"] = False
            smart_search(chat_id, parts[1], mode="domain", domain=maybe_dom)
            return
        if maybe_dom and len(parts) == 1:
            save_domain_for_user(uid, maybe_dom)
            session["domain"] = maybe_dom
            session["awaiting"] = True
            send_message(chat_id, f"✅ تم حفظ الدومين: <code>{esc(maybe_dom)}</code>\nاكتب الآن اسم الأنمي للبحث:")
            return
        if saved_domain and not raw.startswith(("http://", "https://")):
            session["awaiting"] = False
            smart_search(chat_id, raw, mode="domain", domain=saved_domain)
            return

    if raw.startswith(("http://", "https://")):
        low_r = raw.lower()
        if "/links/" in low_r or "/download/" in low_r:
            download_signed_video_and_send(chat_id, raw, referer_url=raw, quality_label="مباشر")
            return
        inspect_direct_url(chat_id, raw)
        return

    session["awaiting"] = False
    smart_search(chat_id, raw, mode=mode, domain=saved_domain)


def inspect_direct_url(chat_id, url):
    if not safe_url(url):
        send_message(chat_id, "⛔ رابط غير مسموح.")
        return
    low = url.lower()
    if "/links/" in low or "/download/" in low:
        download_signed_video_and_send(chat_id, url, referer_url=url, quality_label="مباشر")
        return
    kind = classify_url(url, mode="all")
    sid = f"{chat_id}_{int(time.time() * 1000)}"
    item = {"kind": kind, "title": url, "url": url, "snippet": ""}
    search_results_cache[sid] = {"items": [item], "cur_idx": 0, "active_url": url, "quality": "med", "t": time.time()}
    _send_or_edit_item(chat_id, sid, 0, edit=False)


async def _search_pixeldrain_catalog(query_variants: list[str]) -> list[dict]:
    merged = []
    seen = set()
    for qv in (query_variants or [])[:2]:
        res = await search_serper(qv, ["pixeldrain.com"], mode="pd", classify_fn=classify_url, supported_video_fn=is_supported_video_url)
        if not res:
            res = await search_ddg_fallback(qv, ["pixeldrain.com"], mode="pd", classify_fn=classify_url, supported_video_fn=is_supported_video_url)
        for item in (res or []):
            u = item.get("url")
            if u and u not in seen:
                seen.add(u)
                merged.append(item)
        if len(merged) >= 8:
            break
    return merged


async def _search_registered_anime_sites(query_variants: list[str], original_query: str) -> list[dict]:
    primary_q = (query_variants or [original_query])[0]
    tasks = []
    for dom in DEFAULT_ANIME_DOMAINS:
        tasks.append(
            search_serper(primary_q, [dom], mode="domain", classify_fn=classify_url, supported_video_fn=is_supported_video_url)
        )
    results = await asyncio.gather(*tasks, return_exceptions=True)
    merged = []
    seen = set()
    for dom, bucket in zip(DEFAULT_ANIME_DOMAINS, results):
        if isinstance(bucket, list) and bucket:
            for item in bucket[:3]:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    merged.append(item)
        else:
            for cand in build_domain_entry_candidates(dom, query_variants, original_query)[:1]:
                if cand["url"] not in seen:
                    seen.add(cand["url"])
                    merged.append(cand)
    return merged


async def _run_fast_search(query, mode="all", domain=None, query_variants=None, original_query=""):
    clean_dom = clean_domain(domain)
    allowed = [clean_dom] if clean_dom else PLATFORM_DOMAINS.get(mode, [])
    variants = query_variants or [query]
    primary_q = variants[0]
    direct_entries = build_domain_entry_candidates(clean_dom, variants, original_query or query) if clean_dom else []

    if mode == "pd" or clean_dom == "pixeldrain.com":
        pd_items = await _search_pixeldrain_catalog(variants)
        return direct_entries + pd_items

    if mode == "yt" and not clean_dom:
        return await search_youtube(primary_q)

    if mode == "all" and not clean_dom:
        anime_task = asyncio.create_task(_search_registered_anime_sites(variants, original_query or query))
        pd_task = asyncio.create_task(_search_pixeldrain_catalog(variants))
        web_task = asyncio.create_task(search_serper(primary_q, [], mode="all", classify_fn=classify_url, supported_video_fn=is_supported_video_url))
        anime_res, pd_res, web_res = await asyncio.gather(anime_task, pd_task, web_task, return_exceptions=True)

        merged = []
        seen = set()
        for bucket in (anime_res, pd_res, web_res):
            if isinstance(bucket, list):
                for item in bucket:
                    if item["url"] not in seen:
                        seen.add(item["url"])
                        merged.append(item)
        if merged:
            return merged
        return await search_ddg_fallback(primary_q, [], mode="all", classify_fn=classify_url, supported_video_fn=is_supported_video_url)

    serper_res = await search_serper(primary_q, allowed, mode=mode, classify_fn=classify_url, supported_video_fn=is_supported_video_url)
    ddg_res = serper_res if serper_res else await search_ddg_fallback(primary_q, allowed, mode=mode, classify_fn=classify_url, supported_video_fn=is_supported_video_url)

    merged = []
    seen = set()
    for it in (direct_entries + (ddg_res or [])):
        u = it.get("url")
        if u and u not in seen:
            seen.add(u)
            merged.append(it)
    return merged


def _download_banner_bytes(banner_url, page_url, uid=None):
    if not banner_url or is_ad_media_url(banner_url):
        return None
    try:
        r = stealth_get(banner_url, uid=uid, referer=page_url, timeout=8)
        if r.status_code == 200 and r.content and len(r.content) > 600:
            return r.content
    except Exception:
        pass
    return None


def _build_item_view(sid, entry, idx, uid=None):
    items = entry["items"]
    total = len(items)
    idx = max(0, min(idx, total - 1))
    entry["cur_idx"] = idx
    item = items[idx]
    active_ch_url = entry.get("active_url") if (idx == entry.get("prev_ch_idx") and entry.get("active_url")) else item["url"]
    url = item["url"]
    kind = item.get("kind") or classify_url(url, title=item.get("title", ""))

    if not item.get("inspected"):
        item["inspected"] = True
        if kind == "video" and not is_pixeldrain_url(url) and "/links/" not in url.lower() and "/download/" not in url.lower():
            meta = fetch_video_card_meta(url, uid=uid)
            if meta:
                item["meta"] = meta
                item["title"] = meta["title"]
        else:
            res = inspect_page_resources(url, uid=uid, title_hint=f"{item.get('title', '')} {item.get('snippet', '')}")
            if res["banner"]:
                item["thumb"] = res["banner"]
            if res["title"] and (item.get("title") in ("نتيجة", url) or any(p in urlparse(url).path for p in ("/seasons/", "/episodes/", "/watch/", "/episode/", "/anime/"))):
                item["title"] = res["title"]
            item["duration"] = res.get("duration") or ""
            item["chapters_map"] = res["chapters_map"]
            item["chapter_nums"] = res["chapter_nums"]
            item["episodes"] = res.get("episodes") or []
            item["episodes_map"] = res.get("episodes_map") or {}
            item["download_links"] = res.get("download_links") or []
            item["direct_files"] = res["direct_files"]
            item["direct_videos"] = [v for v in (res["direct_videos"] or []) if not is_ad_media_url(v)]
            item["episode_count"] = res.get("episode_count", 0)

            if res["is_chapter_page"] or res["chapter_nums"]:
                item["kind"] = "chapter"
            elif res["direct_files"]:
                item["kind"] = "file"
            elif res["direct_videos"]:
                item["kind"] = "video"
                item["media_url"] = res["direct_videos"][0]

    kind = item.get("kind") or kind
    meta = item.get("meta")
    thumb = (meta.get("thumb") if meta else "") or item.get("thumb") or ""
    title = esc((meta["title"] if meta else item["title"])[:150])
    snippet = esc(item.get("snippet") or "")
    cnums = item.get("chapter_nums") or []
    eps = item.get("episodes") or []
    dfiles = item.get("direct_files") or []
    dl_links = item.get("download_links") or []
    ep_duration = item.get("duration") or ""

    if kind == "chapter" and active_ch_url != url and entry.get("active_dl_links") is None:
        sub_res = inspect_page_resources(active_ch_url, uid=uid)
        dl_links = sub_res.get("download_links") or dl_links
        entry["active_dl_links"] = dl_links
        if sub_res.get("duration"):
            ep_duration = sub_res["duration"]
            entry["active_duration"] = ep_duration
        if sub_res.get("title"):
            title = esc(sub_res["title"][:150])
    elif entry.get("active_dl_links"):
        dl_links = entry["active_dl_links"]
        if entry.get("active_duration"):
            ep_duration = entry["active_duration"]

    item_ep_count = item.get("episode_count") or len(eps) or count_episodes_in_items(
        [{"title": lbl, "url": u} for lbl, u in dfiles]
    )
    canon_q = entry.get("canonical_query") or ""
    orig_q = entry.get("original_query") or ""

    query_banner = ""
    if canon_q and orig_q and canon_q.lower() != orig_q.lower():
        query_banner = f"\n🧠 <b>الاسم المعتمد للبحث:</b> <code>{esc(canon_q)}</code>"

    ep_line = ""
    if item_ep_count > 0:
        ep_line = f"\n🎬 <b>عدد الحلقات:</b> <b>{item_ep_count}</b>"

    dur_line = ""
    if ep_duration:
        dur_line = f"\n⏱️ <b>مدة الحلقة (من الموقع):</b> <b>{esc(ep_duration)}</b>"

    display_url = active_ch_url if kind == "chapter" else url

    if meta:
        text = (
            f"🎬 <b>النتيجة {idx + 1} من {total}</b>{query_banner}{ep_line}\n\n"
            f"📌 <b>{title}</b>\n"
            f"👤 <b>الحساب:</b> {esc(meta['uploader'])}\n"
            f"👁️ {meta['views']}  |  👍 {meta['likes']}  |  💬 {meta['comments']}  |  ⏱️ {meta['duration']}\n"
            f"🔗 {esc(display_url)}"
        )
    else:
        text = f"⚡ <b>النتيجة {idx + 1} من {total}:</b>{query_banner}{ep_line}{dur_line}\n\n<b>{title}</b>"
        if snippet:
            text += f"\n{snippet}"
        if kind == "chapter" and cnums:
            cur_num = entry.get("active_ch_num") if entry.get("active_ch_num") in cnums else cnums[0]
            text += f"\n📺 <b>الحلقة المحددة:</b> <b>{cur_num}</b> من <b>{cnums[-1]}</b>"
        if dl_links:
            lines_q = []
            for x in dl_links[:8]:
                sz_part = f" — 📦 <b>{esc(x['size'])}</b>" if x.get("size") else " — 📦 <i>يُفحص عند السحب</i>"
                srv_part = f" ({esc(x['server'])})" if x.get("server") else ""
                lines_q.append(f"• <b>{esc(x['quality'])}</b>{srv_part}{sz_part}")
            text += "\n\n🎞️ <b>سيرفرات وجُودات التحميل من الموقع:</b>\n" + "\n".join(lines_q)
        if dfiles:
            text += f"\n📦 <b>ملفات متاحة:</b> {len(dfiles)}"
        text += f"\n🔗 {esc(display_url)}"

    rows = []
    fid = store_url(display_url)

    if dl_links:
        q_row = []
        seen_q_lbl = set()
        for q_i, q_obj in enumerate(dl_links):
            btn_lbl = q_obj["label"]
            if btn_lbl in seen_q_lbl:
                continue
            seen_q_lbl.add(btn_lbl)
            q_row.append({"text": f"🎬 {btn_lbl[:28]}", "callback_data": f"srch|dlq|{sid}|{q_i}"})
            if len(q_row) == 2:
                rows.append(q_row)
                q_row = []
            if len(seen_q_lbl) >= 8:
                break
        if q_row:
            rows.append(q_row)

    if kind == "video":
        if not dl_links:
            rows.append([{"text": "🎬 إرسال كفيديو", "callback_data": f"dl|{fid}"}, {"text": "🎵 صوت", "callback_data": f"dq|{fid}|a"}])
    elif kind == "file":
        if dfiles:
            for lbl, f_u in dfiles[:6]:
                ffid = store_url(f_u)
                rows.append([{"text": f"📦 {lbl[:32]}", "callback_data": f"srch|dlfile|{ffid}"}])
        elif not dl_links:
            rows.append([{"text": "🎬 إرسال كفيديو", "callback_data": f"dl|{fid}"}])
    elif kind == "chapter":
        entry["prev_ch_idx"] = idx
        entry["active_url"] = active_ch_url
        if cnums:
            cur_num = entry.get("active_ch_num") if entry.get("active_ch_num") in cnums else cnums[0]
            entry["active_ch_num"] = cur_num
            rows.append([
                {"text": "⬅️ السابق", "callback_data": f"srch|ch|{sid}|prev"},
                {"text": f"🔢 حلقة ({cur_num}/{cnums[-1]})", "callback_data": f"srch|ch|{sid}|pick"},
                {"text": "التالي ➡️", "callback_data": f"srch|ch|{sid}|next"},
            ])
        if not dl_links:
            rows.append([{"text": "🎬 سحب الحلقة فيديو", "callback_data": f"dl|{fid}"}])
    else:
        if not dl_links:
            rows.append([{"text": "🎬 سحب فيديو", "callback_data": f"dl|{fid}"}])

    nav = []
    if idx > 0:
        nav.append({"text": "⬅️ النتيجة السابقة", "callback_data": f"srch|pg|{sid}|{idx - 1}"})
    if idx < total - 1:
        nav.append({"text": "النتيجة التالية ➡️", "callback_data": f"srch|pg|{sid}|{idx + 1}"})
    if nav:
        rows.append(nav)

    rows.append([
        {"text": "🍪 كوكيز الموقع", "callback_data": "srch|ckmenu"},
        {"text": "🔄 تغيير الموقع/المنصة", "callback_data": "srch|menu"},
    ])
    return text, json.dumps({"inline_keyboard": rows}), thumb, display_url


def _send_or_edit_item(chat_id, sid, idx, edit=True):
    entry = search_results_cache.get(sid)
    if not entry or not entry.get("items"):
        send_message(chat_id, "⚠️ انتهت نتائج البحث، أعد البحث بـ <code>/بحث</code>.")
        return
    text, markup, thumb, page_url = _build_item_view(sid, entry, idx, uid=chat_id)
    msg_id = entry.get("msg_id")
    is_photo = entry.get("is_photo", False)

    banner_bytes = _download_banner_bytes(thumb, page_url, uid=chat_id) if thumb else None

    if edit and msg_id:
        if is_photo and banner_bytes:
            r = TG_SESSION.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageMedia",
                data={
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "media": json.dumps({"type": "photo", "media": "attach://banner", "caption": text[:1020], "parse_mode": "HTML"}),
                    "reply_markup": markup,
                },
                files={"banner": ("banner.jpg", banner_bytes, "image/jpeg")},
                timeout=12,
            )
            if r.status_code == 200 or "not modified" in r.text:
                return
        elif not is_photo and not banner_bytes:
            r = TG_SESSION.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                json={"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML", "reply_markup": markup},
                timeout=10,
            )
            if r.status_code == 200 or "not modified" in r.text:
                return
        try:
            TG_SESSION.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage",
                json={"chat_id": chat_id, "message_id": msg_id},
                timeout=5,
            )
        except Exception:
            pass

    if banner_bytes:
        sr = TG_SESSION.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            data={"chat_id": chat_id, "caption": text[:1020], "parse_mode": "HTML", "reply_markup": markup},
            files={"photo": ("banner.jpg", banner_bytes, "image/jpeg")},
            timeout=14,
        )
        if sr.status_code == 200 and sr.json().get("ok"):
            try:
                entry["msg_id"] = sr.json()["result"]["message_id"]
                entry["is_photo"] = True
            except Exception:
                pass
            return

    sr = send_message(chat_id, text, reply_markup=markup)
    try:
        entry["msg_id"] = sr.json()["result"]["message_id"]
        entry["is_photo"] = False
    except Exception:
        pass


def _render_result_page(chat_id, sid, idx):
    _send_or_edit_item(chat_id, sid, idx, edit=True)


def smart_search(chat_id, query, mode="all", domain=None):
    raw_q = query.strip()
    if raw_q.startswith(("http://", "https://")):
        low_q = raw_q.lower()
        if "/links/" in low_q or "/download/" in low_q:
            download_signed_video_and_send(chat_id, raw_q, referer_url=raw_q, quality_label="مباشر")
            return
        inspect_direct_url(chat_id, raw_q)
        return

    if mode == "all" and not domain:
        parts = raw_q.split(None, 1)
        dom_candidate = clean_domain(parts[0]) if parts else None
        if dom_candidate and len(parts) == 2:
            mode = "domain"
            domain = dom_candidate
            raw_q = parts[1]

    norm = ai_normalize_search_query(raw_q)
    canon_q = norm.get("canonical") or raw_q
    variants = norm.get("variants") or [canon_q, raw_q]

    try:
        items = asyncio.run(_run_fast_search(canon_q, mode=mode, domain=domain, query_variants=variants, original_query=raw_q))
        items = [it for it in (items or []) if not is_non_content_page(it.get("url", ""), it.get("title", ""))]
        if not items:
            target = domain or PLATFORM_LABELS.get(mode, "مواقع الأنمي / الويب")
            send_message(
                chat_id,
                f"❌ لا توجد نتائج مطابقة داخل <b>{esc(target)}</b>.\n"
                f"🧠 الاسم الذي تم البحث به: <code>{esc(canon_q)}</code>",
            )
            return

        items.sort(key=lambda it: (
            0 if any(p in urlparse(it.get("url", "")).path for p in ("/watch/", "/episode/", "/episodes/", "/seasons/", "/anime/")) else (1 if is_pixeldrain_url(it.get("url", "")) else 2),
            extract_episode_number(it.get("title", "")) or 10**9,
        ))
        total_eps = count_episodes_in_items(items)

        sid = f"{chat_id}_{int(time.time() * 1000)}"
        search_results_cache[sid] = {
            "items": items,
            "cur_idx": 0,
            "active_url": items[0]["url"],
            "quality": "med",
            "original_query": raw_q,
            "canonical_query": canon_q,
            "total_episodes": total_eps,
            "t": time.time(),
        }
        if len(search_results_cache) > 200:
            oldest = sorted(search_results_cache.items(), key=lambda x: x[1].get("t", 0))[:50]
            for k, _ in oldest:
                search_results_cache.pop(k, None)

        _send_or_edit_item(chat_id, sid, 0, edit=False)

    except asyncio.TimeoutError:
        send_message(chat_id, "⚡ انتهت مهلة البحث السريع، جرّب كلمة أدق.")
    except Exception as e:
        log_error(chat_id, "smart_search", e, raw_q)
        send_message(chat_id, f"❌ خطأ: <code>{esc(str(e)[:100])}</code>")