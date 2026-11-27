# ==========================================
# ملف ميزات الذكاء الاصطناعي: تحديد الملفات المستهدفة، قراءة كاملة، توزيع الأدوار، وحفظ حجم الملف
# ==========================================
import os
import re
import json
import base64
import requests
from config import (
    bot_state, GROQ_URL, GROQ_KEY, OPENROUTER_KEY,
    GROQ_TEXT_MODELS, GROQ_VISION_MODELS,
    VISION_MODELS_DEFAULT, TEXT_MODELS_DEFAULT,
    VISION_PROMPTS, VISION_TITLES, BOT_IDENTITY,
)
from telegram_api import send_message, tg_download_file, TG_SESSION, TELEGRAM_TOKEN
from utils import esc, log_error, bump_stat, log_event
from points import charge, refund, get_points, setting

chat_history = {}
pending_images = {}

GROQ_OPENAI_BASE = "https://api.groq.com/openai/v1"

CODING_MODEL_PRIORITY = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
    "moonshotai/kimi-k2-instruct",
    "llama-3.1-8b-instant",
]

DETAILED_CONTINUITY_CONTEXT = (
    "أنت جزء من فريق تطوير بوت تيليغرام بلغة Python (مشروع Acer-bot وملفاته: main.py, admin.py, "
    "ai_features.py, search_feature.py, downloader.py, database.py, config.py, telegram_api.py, utils.py, points.py).\n"
    "العمل على حاوية محدودة الموارد: حافظ على السرعة وتوفير المساحة وعدم ترك ملفات مؤقتة.\n"
    "اكتب دائماً بالعربية الواضحة والمختصرة دون رموز ماركدون مزعجة. "
    "عند تعديل ملف بايثون: أبقِ على كامل كود الملف الأصلي ودواله ولا تحذف أو تختصر أجزاءً كبيرة منه."
)

_runtime_groq_keys = []
_key_ranked_models_cache = {}


def _fp(key: str) -> str:
    k = (key or "").strip()
    if len(k) <= 12:
        return "***"
    return f"{k[:7]}...{k[-4:]}"


def get_groq_keys() -> list[str]:
    global _runtime_groq_keys
    if not _runtime_groq_keys:
        seeds = []
        for env_src in (os.environ.get("GROQ_API_KEYS", ""), os.environ.get("GROQ_API_KEY", ""), GROQ_KEY or ""):
            for part in str(env_src).split(","):
                k = part.strip()
                if k and k not in seeds:
                    seeds.append(k)
        _runtime_groq_keys = seeds
    return list(_runtime_groq_keys)


def add_groq_key(new_key: str) -> tuple[bool, str]:
    k = (new_key or "").strip()
    if not k or len(k) < 15:
        return False, "المفتاح غير صالح."
    get_groq_keys()
    if k not in _runtime_groq_keys:
        _runtime_groq_keys.append(k)
    _key_ranked_models_cache.pop(_fp(k), None)
    return True, _fp(k)


def _rank_groq_models(raw_ids: list[str]) -> list[str]:
    ranked = [m for m in CODING_MODEL_PRIORITY if m in raw_ids]
    extras = sorted(
        [m for m in raw_ids if m and m not in ranked],
        key=lambda m: (
            0 if any(tag in m.lower() for tag in ("120b", "70b", "coder", "qwen", "gpt-oss", "kimi", "deepseek")) else 1,
            m,
        ),
    )
    return ranked + extras


def fetch_key_models(api_key: str, force: bool = False) -> list[str]:
    fp = _fp(api_key)
    if not force and fp in _key_ranked_models_cache and _key_ranked_models_cache[fp]:
        return list(_key_ranked_models_cache[fp])
    try:
        r = requests.get(
            f"{GROQ_OPENAI_BASE}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=12,
        )
        r.raise_for_status()
        ids = [
            item.get("id")
            for item in (r.json() or {}).get("data", [])
            if item.get("id") and item.get("active", True)
        ]
        ranked = _rank_groq_models(ids)
        if ranked:
            _key_ranked_models_cache[fp] = ranked
            return list(ranked)
    except Exception:
        pass
    fallback = [
        m.strip().removeprefix("groq:")
        for m in (GROQ_TEXT_MODELS or "").split(",")
        if m.strip()
    ]
    return _rank_groq_models(fallback or CODING_MODEL_PRIORITY)


def pick_four_role_models() -> dict:
    keys = get_groq_keys()
    merged = []
    for k in keys:
        for m in fetch_key_models(k):
            if m not in merged:
                merged.append(m)
    ranked = _rank_groq_models(merged)
    if not ranked:
        ranked = list(CODING_MODEL_PRIORITY)

    if len(ranked) >= 4:
        strongest, inspector, proposer, router = ranked[0], ranked[1], ranked[2], ranked[-1]
    elif len(ranked) == 3:
        strongest = inspector = ranked[0]
        proposer = router = ranked[2]
    elif len(ranked) == 2:
        strongest = inspector = ranked[0]
        proposer = router = ranked[1]
    else:
        strongest = inspector = proposer = router = ranked[0]

    return {
        "strongest": strongest,
        "inspector": inspector,
        "proposer": proposer,
        "router": router,
        "all_ranked": ranked,
    }


def probe_groq_setup(api_key: str | None = None) -> dict:
    keys = [api_key.strip()] if api_key else get_groq_keys()
    if not keys:
        return {"ok": False, "error": "لا توجد مفاتيح Groq مضبوطة.", "strongest_model": None, "models": []}

    for k in keys:
        models = fetch_key_models(k, force=True)
        for m in models:
            try:
                r = requests.post(
                    f"{GROQ_OPENAI_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
                    json={
                        "model": m,
                        "messages": [{"role": "user", "content": "Reply with OK only."}],
                        "max_tokens": 16,
                        "temperature": 0.0,
                    },
                    timeout=15,
                )
                if r.status_code == 200:
                    return {
                        "ok": True,
                        "key_fp": _fp(k),
                        "strongest_model": m,
                        "models": models,
                    }
            except Exception:
                continue
    return {"ok": False, "error": "تعذّر العثور على نموذج مستجيب.", "strongest_model": None, "models": []}


def cfg_int(name, default):
    try:
        return int(bot_state.get("settings", {}).get(name, default))
    except Exception:
        return default


def feature_on(name):
    feats = bot_state.get("settings", {}).get("features", {}) or {}
    return bool(feats.get(name, True))


def model_list(key, default):
    raw = str(bot_state.get("settings", {}).get(key) or default)
    lst = [m.strip() for m in raw.split(",") if m.strip()]
    if not any(m.startswith("groq:") for m in lst):
        g = GROQ_TEXT_MODELS if key == "text_models" else (GROQ_VISION_MODELS if key == "vision_models" else "")
        lst = [m.strip() for m in g.split(",") if m.strip()] + lst
    return lst[:10]


def _call_single_groq_key_model(api_key: str, model_id: str, messages, max_tokens: int, timeout: int):
    fp = _fp(api_key)
    try:
        res = requests.post(
            f"{GROQ_OPENAI_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model_id, "messages": messages, "max_tokens": max_tokens},
            timeout=timeout,
        )
        if res.status_code == 200:
            content = ((res.json().get("choices") or [{}])[0].get("message") or {}).get("content")
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()
            if content:
                return content, ""
            return None, f"groq:{model_id} ({fp}): empty"
        return None, f"groq:{model_id} ({fp}): HTTP {res.status_code}"
    except Exception as e:
        return None, f"groq:{model_id} ({fp}): {e}"


def _groq_failover_call(messages, max_tokens, timeout, preferred_model=None, preferred_key=None):
    keys = get_groq_keys()
    if preferred_key and preferred_key in keys:
        keys = [preferred_key] + [x for x in keys if x != preferred_key]

    if not keys:
        return None, "no groq key"

    candidate_models = []
    if preferred_model:
        pm = preferred_model.removeprefix("groq:").strip()
        if pm:
            candidate_models.append(pm)

    for k in keys:
        for m in fetch_key_models(k):
            if m not in candidate_models:
                candidate_models.append(m)

    last_err = "no groq key"
    for mid in candidate_models:
        for k in keys:
            text, err = _call_single_groq_key_model(k, mid, messages, max_tokens, timeout)
            if text:
                return text, ""
            last_err = err
    return None, last_err


def llm_call(model, messages, max_tokens, timeout):
    if model.startswith("groq:"):
        return _groq_failover_call(messages, max_tokens, timeout, preferred_model=model[5:])

    url, key, mid = "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY, model
    try:
        res = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": mid, "messages": messages, "max_tokens": max_tokens},
            timeout=timeout,
        )
        if res.status_code == 200:
            content = ((res.json().get("choices") or [{}])[0].get("message") or {}).get("content")
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()
            return (content, "") if content else (None, f"{model}: empty")
        return None, f"{model}: HTTP {res.status_code} {res.text[:120]}"
    except Exception as e:
        return None, f"{model}: {e}"


def ask_ai(chat_id, prompt, system_prompt=None):
    cid = str(chat_id)
    history = chat_history.get(cid, [])

    base_sys = system_prompt or BOT_IDENTITY
    combined_sys = f"{base_sys}\n\n{DETAILED_CONTINUITY_CONTEXT}"

    messages = [{"role": "system", "content": combined_sys}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": prompt})

    last = "no model"
    for model in model_list("text_models", TEXT_MODELS_DEFAULT):
        text, err = llm_call(model, messages, 1300, 40)
        if text:
            history.append({"role": "user", "content": prompt[:450]})
            history.append({"role": "assistant", "content": text[:700]})
            chat_history[cid] = history[-8:]
            return text
        last = err

    return f"⚠️ عذراً، نماذج الذكاء الاصطناعي مشغولة حالياً. ({last})"


def vision_ask(img_bytes, mime, prompt):
    b64 = base64.b64encode(img_bytes).decode()
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": f"{DETAILED_CONTINUITY_CONTEXT}\n\n{prompt}"},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    }]
    last = "no model"
    for model in model_list("vision_models", VISION_MODELS_DEFAULT):
        text, err = llm_call(model, messages, 1200, 70)
        if text:
            return text
        last = err
    raise RuntimeError(last)


def process_image(chat_id, file_id, mode, question=""):
    if not feature_on("vision"):
        send_message(chat_id, "⚠️ ميزة الصور معطّلة حالياً من الإدارة.")
        return
    cost = cfg_int("vision_cost", 2)
    if not charge(chat_id, cost):
        send_message(chat_id, f"😅 <b>رصيدك لا يكفي!</b>\n💰 رصيدك: <b>{get_points(chat_id)}</b> | 🖼️ السعر: <b>{cost}</b>\n🎁 تحصل على +{setting('daily_bonus')} يومياً")
        return
    ok = False
    try:
        send_message(chat_id, "🖼️ جاري قراءة الصورة...")
        data, path = tg_download_file(file_id)
        pl = path.lower()
        mime = "image/png" if pl.endswith(".png") else ("image/webp" if pl.endswith(".webp") else "image/jpeg")
        prompt = (f"{question}\n\nأجب بالعربية وبإيجاز." if mode == "ask" else VISION_PROMPTS[mode])
        text = vision_ask(data, mime, prompt)
        send_message(chat_id, f"<b>{VISION_TITLES[mode]}</b>\n\n{esc(text[:2800])}\n\n<i>💸 خُصم {cost} نقاط | 💰 رصيدك: {get_points(chat_id)}</i>")
        ok = True
        bump_stat("visions")
        log_event("vision", chat_id, f"[{mode}] {text[:220]}")
    except Exception as e:
        log_error(chat_id, "vision", e)
        send_message(chat_id, "❌ تعذّر تحليل الصورة حالياً. حاول بعد قليل.\n🔄 أُعيدت نقاطك.")
    finally:
        if not ok:
            refund(chat_id, cost)


def _list_project_py_files() -> list[str]:
    base_dir = os.path.abspath(os.getcwd())
    try:
        return [
            f for f in sorted(os.listdir(base_dir))
            if os.path.isfile(os.path.join(base_dir, f)) and f.endswith(".py")
        ]
    except Exception:
        return []


def _read_full_code(rel_path: str, max_chars: int = 120000) -> tuple[bool, str]:
    clean = (rel_path or "").strip().lstrip("/\\")
    if not clean:
        return False, "اسم الملف فارغ."
    base_dir = os.path.abspath(os.getcwd())
    target = os.path.abspath(os.path.join(base_dir, clean))
    if not (target == base_dir or target.startswith(base_dir + os.sep)):
        return False, "مسار غير مسموح."
    if not os.path.isfile(target) or not target.endswith(".py"):
        return False, "يجب اختيار ملف بايثون (.py) موجود على السيرفر."
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        return True, f.read(max_chars)


def _clean_short_text(txt: str, limit: int = 650) -> str:
    t = re.sub(r"\[?/?SUMMARY\]?:?", "", txt or "", flags=re.I)
    t = re.sub(r"[#\*`]+", "", t)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    return t[:limit]


def _sanitize_python_code(code_text: str) -> str:
    if not code_text:
        return ""
    replacements = {
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
        "\u2014": "-", "\u2212": "-", "\u00a0": " ", "\u200b": "", "\ufeff": "",
        "“": '"', "”": '"', "‘": "'", "’": "'",
    }
    for bad, good in replacements.items():
        code_text = code_text.replace(bad, good)
    lines = code_text.splitlines()
    clean_lines = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(("# ---", "###", "## ", "**", "- **", "* **")):
            continue
        clean_lines.append(ln)
    return "\n".join(clean_lines).strip()


def send_code_document_same_name(chat_id, filename: str, code_text: str, caption: str = "") -> tuple[bool, str]:
    safe_fname = os.path.basename((filename or "output.py").strip()) or "output.py"
    if not safe_fname.endswith(".py"):
        safe_fname += ".py"
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        files = {"document": (safe_fname, code_text.encode("utf-8"), "text/x-python")}
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption[:900]
            data["parse_mode"] = "HTML"
        r = TG_SESSION.post(url, data=data, files=files, timeout=35)
        if r.status_code == 200:
            return True, ""
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, str(e)[:120]


def _call_role_agent(role_system: str, user_payload: str, preferred_model: str, preferred_key: str | None = None, max_tokens: int = 1200) -> str:
    messages = [
        {"role": "system", "content": f"{role_system}\n\n{DETAILED_CONTINUITY_CONTEXT}"},
        {"role": "user", "content": user_payload},
    ]
    text, err = _groq_failover_call(
        messages,
        max_tokens=max_tokens,
        timeout=60,
        preferred_model=preferred_model,
        preferred_key=preferred_key,
    )
    if text:
        return text
    for model in model_list("text_models", TEXT_MODELS_DEFAULT):
        t2, _ = llm_call(model, messages, max_tokens, 60)
        if t2:
            return t2
    raise RuntimeError(err)


def _match_files_from_request(user_request: str, py_files: list[str]) -> list[str]:
    """مطابقة مباشرة وموثوقة لأسماء الملفات من الطلب العربي/الإنكليزي."""
    req = (user_request or "").lower()
    matched = []

    # ذكر صريح لاسم ملف
    for f in py_files:
        if f.lower() in req and f not in matched:
            matched.append(f)

    keyword_map = {
        "downloader.py": ("تحميل", "التحميل", "تنزيل", "فيديو", "download", "downloader", "yt-dlp"),
        "search_feature.py": ("بحث", "البحث", "كوكيز", "فصول", "مانهوا", "روايات", "search"),
        "admin.py": ("ادارة", "إدارة", "مشرف", "لوحة", "حظر", "اذاعة", "إذاعة", "استضافة", "admin"),
        "ai_features.py": ("ذكاء", "نموذج", "نماذج", "مفاتيح", "تقييم", "اقتراح", "ai", "groq"),
        "points.py": ("نقاط", "رصيد", "خصم", "points"),
        "database.py": ("قاعدة", "بيانات", "حفظ", "database", "db"),
        "main.py": ("رئيسي", "الرئيسي", "حلقة", "main"),
    }
    for fname, words in keyword_map.items():
        if fname in py_files and fname not in matched:
            if any(w in req for w in words):
                matched.append(fname)

    return matched


def plan_and_build_same_name_file(target_file: str | None, user_request: str) -> dict:
    """
    1) يحدد الملفات المستهدفة من الطلب (عربي/إنكليزي) أو عبر النموذج الرابع المنسّق.
    2) يقرأ كل ملف مستهدف كاملاً ويعرف حجمه.
    3) ينفّذ الأدوار (اقتراح -> فحص -> برمجة الأقوى) مع ضمان عدم تقلّص حجم الملف الأصلي.
    """
    py_files = _list_project_py_files()
    keys = get_groq_keys()
    k1 = keys[0] if len(keys) >= 1 else None
    k2 = keys[1] if len(keys) >= 2 else k1
    k3 = keys[2] if len(keys) >= 3 else k2
    k4 = keys[3] if len(keys) >= 4 else k3

    models_info = pick_four_role_models()
    strongest_model = models_info["strongest"]
    inspector_model = models_info["inspector"]
    proposer_model = models_info["proposer"]
    router_model = models_info["router"]

    # النموذج الرابع (الأضعف): يفهم الرسالة والمراحل ويحدد القصد والملفات
    routing_out = _call_role_agent(
        "أنت النموذج الرابع المنسّق. اقرأ رسالة المستخدم وقائمة ملفات المشروع وأجب بصيغة JSON فقط بدون أي نص خارجه: "
        '{"mode":"INSPECT_ONLY|SUGGEST_ONLY|EDIT_CODE","files":["..."],"reason":"شرح قصير بالعربية"}',
        f"الملفات المتاحة: {py_files}\nالمطلوب: {user_request}",
        preferred_model=router_model,
        preferred_key=k4,
        max_tokens=300,
    )

    mode = "EDIT_CODE"
    ai_files = []
    reason = ""
    try:
        m_json = re.search(r"\{.*\}", routing_out, flags=re.S)
        if m_json:
            parsed = json.loads(m_json.group(0))
            if parsed.get("mode") in ("INSPECT_ONLY", "SUGGEST_ONLY", "EDIT_CODE"):
                mode = parsed["mode"]
            if isinstance(parsed.get("files"), list):
                ai_files = [str(x).strip() for x in parsed["files"] if str(x).strip() in py_files]
            reason = str(parsed.get("reason") or "").strip()
    except Exception:
        pass

    req_clean = (user_request or "").strip()
    if any(w in req_clean for w in ("تقييم", "قيم", "هيكل", "فحص", "افحص", "تحليل")) and not any(
        w in req_clean for w in ("عدل", "تعديل", "غير", "أضف", "اضف", "احذف", "برمج")
    ):
        mode = "INSPECT_ONLY"
    elif any(w in req_clean for w in ("اقتراح", "اقترح", "افكار", "أفكار")) and not any(
        w in req_clean for w in ("عدل", "تعديل", "غير", "أضف", "اضف", "برمج")
    ):
        mode = "SUGGEST_ONLY"

    selected_files = []
    if target_file and target_file.strip() in py_files:
        selected_files.append(target_file.strip())
    for f in _match_files_from_request(user_request, py_files):
        if f not in selected_files:
            selected_files.append(f)
    for f in ai_files:
        if f not in selected_files:
            selected_files.append(f)
    if not selected_files:
        selected_files = ["main.py"] if "main.py" in py_files else (py_files[:1] or ["main.py"])

    # قراءة الملفات كاملة
    loaded_files = {}
    for fname in selected_files[:3]:
        ok, src = _read_full_code(fname, max_chars=120000)
        if ok:
            loaded_files[fname] = src

    if not loaded_files:
        return {"ok": False, "error": "تعذّر قراءة الملفات المستهدفة."}

    results_per_file = []
    summaries = []

    for fname, src in loaded_files.items():
        orig_len = len(src)

        inspection = _call_role_agent(
            "أنت فاحص هيكل بايثون. اكتب بالعربية 3-4 نقاط مختصرة جداً عن هيكل الملف وما يخص الطلب.",
            f"الملف: {fname} (الطول: {orig_len} حرف)\nالطلب: {user_request}\nالكود الكامل:\n```python\n{src}\n```",
            preferred_model=inspector_model,
            preferred_key=k2,
            max_tokens=550,
        )
        short_insp = _clean_short_text(inspection, 450)

        if mode == "INSPECT_ONLY":
            summaries.append(f"• {fname}: {short_insp}")
            results_per_file.append({"file": fname, "code": "", "syntax_ok": True, "syntax_err": ""})
            continue

        suggestions = _call_role_agent(
            "أنت مقترح تعديلات بايثون. اكتب بالعربية 3 نقاط عملية ومختصرة جداً.",
            f"الملف: {fname}\nالطلب: {user_request}\nالفحص: {short_insp}",
            preferred_model=proposer_model,
            preferred_key=k3,
            max_tokens=450,
        )
        short_sugg = _clean_short_text(suggestions, 400)

        if mode == "SUGGEST_ONLY":
            summaries.append(f"• {fname}:\nفحص: {short_insp}\nاقتراح: {short_sugg}")
            results_per_file.append({"file": fname, "code": "", "syntax_ok": True, "syntax_err": ""})
            continue

        # النموذج الأقوى: يبرمج التعديل ويحافظ على كامل حجم الملف ومحتواه
        coder_out = _call_role_agent(
            "أنت مبرمج بايثون رئيسي. اكتب في البداية ملخصاً عربياً من سطرين يبدأ بـ [SUMMARY] يشرح ما تم تعديله، "
            "ثم أخرج كود الملف كاملاً داخل ```python فقط. "
            "تحذير صارم: لا تختصر الملف الأصلي ولا تحذف دواله أو أسطره، يجب أن يبقى الكود كاملاً وبنفس الشمولية.",
            (
                f"الملف: {fname}\nالطلب: {user_request}\n"
                f"الفحص: {short_insp}\nالاقتراح: {short_sugg}\n"
                f"الكود الكامل الأصلي:\n```python\n{src}\n```"
            ),
            preferred_model=strongest_model,
            preferred_key=k1,
            max_tokens=6500,
        )

        m = re.search(r"```python\s*(.*?)```", coder_out, flags=re.S | re.I)
        raw_code = (m.group(1) if m else "").strip()
        candidate_code = _sanitize_python_code(raw_code)

        summary_match = re.search(r"[SUMMARY]\s*(.*?)(?:```|$)", coder_out, flags=re.S | re.I)
        f_summary = _clean_short_text(summary_match.group(1) if summary_match else "", 350)
        if not f_summary:
            f_summary = f"تمت مراجعة وتعديل {fname} حسب المطلوب مع الحفاظ على الكود الأصلي."

        syntax_ok = False
        syntax_err = ""
        if candidate_code:
            try:
                compile(candidate_code, fname, "exec")
                syntax_ok = True
            except SyntaxError as e:
                syntax_err = f"سطر {e.lineno}: {e.msg}"

        # منع انكماش الملف بشكل غير طبيعي (إذا صار أقل من 75% من حجم الأصل نُبقي الأصل السليم)
        size_ok = len(candidate_code) >= int(orig_len * 0.75)
        if syntax_ok and size_ok:
            final_code = candidate_code
            status_note = "✅ سليم وكامل"
        else:
            final_code = _sanitize_python_code(src)
            status_note = "⚠️ تم الإبقاء على الكود الأصلي الكامل لتفادي النقص/الخطأ"

        summaries.append(f"• {fname} ({status_note}): {f_summary}")
        results_per_file.append({
            "file": fname,
            "code": final_code,
            "syntax_ok": syntax_ok and size_ok,
            "syntax_err": syntax_err or ("حجم الكود الناتج أصغر من المتوقع" if not size_ok else ""),
        })

    first = results_per_file[0]
    return {
        "ok": True,
        "mode": mode,
        "files": list(loaded_files.keys()),
        "file": first["file"],
        "reason": reason,
        "summary": "\n".join(summaries),
        "revised_code": first["code"],
        "syntax_ok": first["syntax_ok"],
        "syntax_err": first["syntax_err"],
        "files_results": results_per_file,
    }