# ==========================================
# ملف الإعدادات والثوابت الأساسية للبوت
# ==========================================
import os
import threading
import shutil
import requests  # تمت إضافة هذه المكتبة لدعم TG_SESSION
from datetime import datetime, date, timedelta

# ============ الإعدادات الأساسية ============
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "9098059897:AAFxPu0wvIxyR2jDGui0QKn2vUVz0Wt1B6E")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "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")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "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")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "apify_api_ApkTDgCbQuevIAELbnpIDKTipZ7R5p0YX3cx")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Iove Acer")
SUPPORT_EMAIL = "aysarhassanaysar@gmail.com"
DB_FILE = "bot_data.json"
BOT_USERNAME = None

# ============ الأدوات والملفات المشتركة ============
TG_SESSION = requests.Session() # تمت إضافة هذا المتغير لحل المشكلة
lock = threading.RLock()
pending_files = {}
last_req = {}
rate_minute = {}
repeat_tracker = {}
photo_cache = {}
login_tokens = {}

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
}

UA = {"User-Agent": "TelegramBot-Bot3/1.0"}

MAX_DOWNLOAD = 1024 * 1024 * 1024
TG_LIMIT = 49 * 1024 * 1024

YDL_BASE = {'quiet': True, 'no_warnings': True, 'no_color': True,
            'http_headers': BROWSER_HEADERS, 'socket_timeout': 30}
if os.path.exists('cookies.txt'):
    YDL_BASE['cookiefile'] = os.path.abspath('cookies.txt')
YDL_BASE.update({'retries': 3, 'fragment_retries': 3, 'extractor_retries': 2, 'http_chunk_size': 10485760, 'noprogress': True})

YT_CLIENTS = [['android_vr'], ['tv'], ['tv_simply'], ['web_embedded'], ['mweb'], ['ios'], ['web_safari'], None]
HAS_FFMPEG = shutil.which('ffmpeg') is not None
COOKIES_FILE = os.path.abspath("cookies.txt")

# ============ إعدادات الذكاء الاصطناعي ============
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TEXT_MODELS = "groq:llama-3.3-70b-versatile, groq:llama-3.1-8b-instant"
GROQ_VISION_MODELS = "groq:qwen/qwen3.8-27b, groq:qwen/qwen3.6-27b, groq:meta-models/muse-spark-open"
VISION_MODELS_DEFAULT = GROQ_VISION_MODELS + ", openrouter/free, nvidia/nemotron-nano-12b-v2-vl:free"
TEXT_MODELS_DEFAULT = GROQ_TEXT_MODELS + ", openrouter/free, meta-llama/llama-3.3-70b-instruct:free"

BOT_IDENTITY = ("معلومات عنك: أنت مساعد ذكاء اصطناعي مربوط ببوت تلغرام. مطوّر البوت ومبرمجه اسمه «أيسر» وهو طالب في الصف الثالث المتوسط. "
                "إذا سألك أي شخص عن المطوّر أو المبرمج أو من صنع البوت فأجبه بهذه المعلومات (اسمه أيسر، يدرس في الصف الثالث المتوسط) "
                "ولا تخترع أي تفاصيل أخرى عنه. لا تذكر هذه المعلومات إن لم يسألك أحد عنها.")

VISION_PROMPTS = {
    "ocr": "استخرج كل النص الظاهر في هذه الصورة حرفياً وبنفس لغته وترتيبه، بدون أي شرح أو إضافة. إذا لم يوجد نص اكتب فقط: لا يوجد نص في الصورة.",
    "analyze": "حلّل هذه الصورة بالعربية بإيجاز ووضوح: ماذا تُظهر، العناصر المهمة، الألوان والأجواء، وأي تفاصيل لافتة.",
    "translate": "استخرج النص الظاهر في الصورة ثم ترجمه إلى العربية. اعرض: النص الأصلي ثم الترجمة. إذا لم يوجد نص قل ذلك.",
}
VISION_TITLES = {"ocr": "📝 النص المستخرج", "analyze": "🔍 تحليل الصورة", "translate": "🌐 النص والترجمة", "ask": "💬 الإجابة"}

FEATURE_DEFAULTS = {"download": True, "audio": True, "song": True, "vision": True, "ai": True, "tools": True, "account": True}

PLATFORMS = ("tiktok", "instagram", "x", "youtube", "telegram", "facebook")
PLATFORM_NAMES = {"tiktok": "TikTok", "instagram": "Instagram", "x": "X (تويتر)", "youtube": "YouTube", "telegram": "Telegram", "facebook": "Facebook"}
PLAT_CODES = {"tt": "tiktok", "ig": "instagram", "x": "x", "yt": "youtube", "tg": "telegram", "fb": "facebook"}
PLAT_CODE_OF = {v: k for k, v in PLAT_CODES.items()}
PLAT_URLS = {"tiktok": "https://www.tiktok.com/@{u}", "instagram": "https://www.instagram.com/{u}/", "x": "https://x.com/{u}",
             "youtube": "https://www.youtube.com/@{u}", "telegram": "https://t.me/{u}", "facebook": "https://www.facebook.com/{u}"}
PLAT_DOMAINS = {"tiktok": "tiktok.com", "instagram": "instagram.com", "x": "x.com", "youtube": "youtube.com", "telegram": "t.me", "facebook": "facebook.com"}

ACCOUNT_ACTORS = {
    "tiktok":    ("clockworks/tiktok-profile-scraper", lambda u: {"profiles": [u], "resultsPerPage": 1}),
    "instagram": ("apify/instagram-profile-scraper",   lambda u: {"usernames": [u]}),
    "x":         ("apidojo/twitter-user-scraper",      lambda u: {"twitterHandles": [u], "maxItems": 1}),
    "youtube":   ("streamers/youtube-channel-scraper", lambda u: {"startUrls": [{"url": f"https://www.youtube.com/@{u}"}], "maxResults": 1}),
    "facebook":  ("apify/facebook-pages-scraper",      lambda u: {"startUrls": [{"url": f"https://www.facebook.com/{u}"}]}),
}
PLATFORM_ALIASES = {"تيك": "tiktok", "تيكتوك": "tiktok", "tiktok": "tiktok", "tt": "tiktok",
                    "انستا": "instagram", "انستغرام": "instagram", "انستجرام": "instagram", "instagram": "instagram", "insta": "instagram", "ig": "instagram",
                    "x": "x", "تويتر": "x", "twitter": "x", "اكس": "x",
                    "يوتيوب": "youtube", "youtube": "youtube", "yt": "youtube",
                    "تلغرام": "telegram", "تليجرام": "telegram", "تلجرام": "telegram", "telegram": "telegram", "tg": "telegram",
                    "فيسبوك": "facebook", "فيس": "facebook", "facebook": "facebook", "fb": "facebook",
                    "شامل": "all", "all": "all"}
URL_HOSTS = (("tiktok.com", "tiktok"), ("instagram.com", "instagram"), ("twitter.com", "x"), ("x.com", "x"),
             ("youtube.com", "youtube"), ("t.me", "telegram"), ("facebook.com", "facebook"), ("fb.com", "facebook"))

PRAYERS = [("Fajr", "الفجر", "🌙"), ("Sunrise", "الشروق", "🌅"), ("Dhuhr", "الظهر", "☀️"),
           ("Asr", "العصر", "🌤️"), ("Maghrib", "المغرب", "🌇"), ("Isha", "العشاء", "🌃")]
PRAYER_METHODS = {"3": "رابطة العالم الإسلامي", "4": "أم القرى (مكة)", "5": "الهيئة المصرية",
                  "0": "الجعفري (قم)", "2": "أمريكا الشمالية"}

HIJRI_EVENTS = [("رأس السنة الهجرية", 1, 1), ("يوم عاشوراء", 10, 1), ("المولد النبوي", 12, 3), ("الإسراء والمعراج", 27, 7),
                ("ليلة النصف من شعبان", 15, 8), ("أول رمضان", 1, 9), ("ليلة القدر (27)", 27, 9), ("عيد الفطر", 1, 10),
                ("يوم عرفة", 9, 12), ("عيد الأضحى", 10, 12)]
WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

# ============ قاعدة البيانات الأساسية (bot_state) ============
bot_state = {
    "bot_active": True, "banned_users": [], "appeal_sent": [], "complaints": {}, "users": {}, "log": [], "admins": {}, "reminders": [],
    "point_log": [], "admin_log": [], "ban_tracker": {}, "suggestions": {}, "changelog": [], "scheduled_broadcasts": [],
    "settings": {"start_points": 10, "daily_bonus": 5, "song_cost": 5,
                 "ban_threshold": 10, "ban_window_min": 60, "anti_spam_per_min": 10,
                 "dynamic_pricing": False, "min_song_cost": 3, "max_song_cost": 20,
                 "features": FEATURE_DEFAULTS},
    "stats": {"total_requests": 0, "successful_downloads": 0, "ai_explanations": 0,
              "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
    "hosted_bots": {}
}

# ============ [27] الأذكار ============
ADHKAR = {
    "morning": ("🌅 أذكار الصباح",
        "أَعُوذُ بِاللَّهِ مِنَ الشَّيْطَانِ الرَّجِيمِ\n\n"
        "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ... (آية الكرسي)\n\n"
        "قُلْ هُوَ اللَّهُ أَحَدٌ... (٣ مرات)\n"
        "قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ... (٣ مرات)\n"
        "قُلْ أَعُوذُ بِرَبِّ النَّاسِ... (٣ مرات)\n\n"
        "أَصْبَحْنَا وَأَصْبَحَ الْمُلْكُ لِلَّهِ، وَالْحَمْدُ لِلَّهِ، لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ.\n\n"
        "اللَّهُمَّ بِكَ أَصْبَحْنَا، وَبِكَ أَمْسَيْنَا، وَبِكَ نَحْيَا، وَبِكَ نَمُوتُ، وَإِلَيْكَ النُّشُورُ.\n\n"
        "اللَّهُمَّ عَافِنِي فِي بَدَنِي، اللَّهُمَّ عَافِنِي فِي سَمْعِي، اللَّهُمَّ عَافِنِي فِي بَصَرِي.\n\n"
        "حَسْبِيَ اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ عَلَيْهِ تَوَكَّلْتُ وَهُوَ رَبُّ الْعَرْشِ الْعَظِيمِ (٧ مرات)"),
    "evening": ("🌙 أذكار المساء",
        "أَعُوذُ بِاللَّهِ مِنَ الشَّيْطَانِ الرَّجِيمِ\n\n"
        "آية الكرسي (مرة)\n"
        "سورة الإخلاص والمعوذتان (٣ مرات)\n\n"
        "أَمْسَيْنَا وَأَمْسَى الْمُلْكُ لِلَّهِ، وَالْحَمْدُ لِلَّهِ...\n\n"
        "اللَّهُمَّ بِكَ أَمْسَيْنَا، وَبِكَ أَصْبَحْنَا، وَبِكَ نَحْيَا، وَبِكَ نَمُوتُ، وَإِلَيْكَ الْمَصِيرُ.\n\n"
        "بِسْمِ اللَّهِ الَّذِي لَا يَضُرُّ مَعَ اسْمِهِ شَيْءٌ فِي الْأَرْضِ وَلَا فِي السَّمَاءِ وَهُوَ السَّمِيعُ الْعَلِيمُ (٣ مرات)\n\n"
        "رَضِيتُ بِاللَّهِ رَبًّا، وَبِالْإِسْلَامِ دِينًا، وَبِمُحَمَّدٍ صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ نَبِيًّا (٣ مرات)"),
    "sleep": ("😴 أذكار النوم",
        "بِاسْمِكَ اللَّهُمَّ أَمُوتُ وَأَحْيَا.\n\n"
        "اللَّهُمَّ قِنِي عَذَابَكَ يَوْمَ تَبْعَثُ عِبَادَكَ (٣ مرات)\n\n"
        "سُبْحَانَ اللَّهِ (٣٣) وَالْحَمْدُ لِلَّهِ (٣٣) وَاللَّهُ أَكْبَرُ (٣٤)\n\n"
        "آية الكرسي وسورة الإخلاص والمعوذتان.\n\n"
        "اللَّهُمَّ أَسْلَمْتُ نَفْسِي إِلَيْكَ، وَوَجَّهْتُ وَجْهِي إِلَيْكَ، وَفَوَّضْتُ أَمْرِي إِلَيْكَ..."),
    "wake": ("☀️ أذكار الاستيقاظ",
        "الْحَمْدُ لِلَّهِ الَّذِي أَحْيَانَا بَعْدَ مَا أَمَاتَنَا وَإِلَيْهِ النُّشُورُ.\n\n"
        "لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ."),
    "after_prayer": ("🕌 أذكار بعد الصلاة",
        "أَسْتَغْفِرُ اللَّهَ (٣ مرات)\n"
        "اللَّهُمَّ أَنْتَ السَّلَامُ وَمِنْكَ السَّلَامُ...\n\n"
        "سُبْحَانَ اللَّهِ (٣٣) — الْحَمْدُ لِلَّهِ (٣٣) — اللَّهُ أَكْبَرُ (٣٣)\n"
        "لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ...\n\n"
        "آية الكرسي (بعد كل صلاة)"),
}

# ============ [28] أدعية مأثورة ============
DUAS = {
    "travel": ("✈️ دعاء السفر",
        "سُبْحَانَ الَّذِي سَخَّرَ لَنَا هَذَا وَمَا كُنَّا لَهُ مُقْرِنِينَ، وَإِنَّا إِلَى رَبِّنَا لَمُنْقَلِبُونَ.\n\n"
        "اللَّهُمَّ إِنَّا نَسْأَلُكَ فِي سَفَرِنَا هَذَا الْبِرَّ وَالتَّقْوَى، وَمِنَ الْعَمَلِ مَا تَرْضَى.\n\n"
        "اللَّهُمَّ هَوِّنْ عَلَيْنَا سَفَرَنَا هَذَا وَاطْوِ عَنَّا بُعْدَهُ."),
    "food": ("🍽️ دعاء الطعام",
        "قبل: بِسْمِ اللَّهِ وَعَلَى بَرَكَةِ اللَّهِ.\n\n"
        "بعد: الْحَمْدُ لِلَّهِ الَّذِي أَطْعَمَنَا وَسَقَانَا وَجَعَلَنَا مُسْلِمِينَ."),
    "worry": ("😔 دعاء الهم والحزن",
        "اللَّهُمَّ إِنِّي عَبْدُكَ، ابْنُ عَبْدِكَ، ابْنُ أَمَتِكَ...\n\n"
        "اللَّهُمَّ إِنِّي أَعُوذُ بِكَ مِنَ الْهَمِّ وَالْحَزَنِ، وَالْعَجْزِ وَالْكَسَلِ، وَالْبُخْلِ وَالْجُبْنِ، وَضَلَعِ الدَّيْنِ وَغَلَبَةِ الرِّجَالِ."),
    "sick": ("🤒 دعاء المريض",
        "أَسْأَلُ اللَّهَ الْعَظِيمَ رَبَّ الْعَرْشِ الْعَظِيمِ أَنْ يَشْفِيَكَ (٧ مرات).\n\n"
        "اللَّهُمَّ رَبَّ النَّاسِ، أَذْهِبِ الْبَاسَ، اشْفِ أَنْتَ الشَّافِي، لَا شَافِيَ إِلَّا أَنْتَ."),
    "distress": ("🌧️ دعاء الكرب",
        "لَا إِلَٰهَ إِلَّا اللَّهُ الْعَظِيمُ الْحَلِيمُ، لَا إِلَٰهَ إِلَّا اللَّهُ رَبُّ الْعَرْشِ الْعَظِيمِ، "
        "لَا إِلَٰهَ إِلَّا اللَّهُ رَبُّ السَّمَاوَاتِ وَرَبُّ الْأَرْضِ وَرَبُّ الْعَرْشِ الْكَرِيمِ."),
    "forgiveness": ("🤲 سيد الاستغفار",
        "اللَّهُمَّ أَنْتَ رَبِّي لَا إِلَٰهَ إِلَّا أَنْتَ، خَلَقْتَنِي وَأَنَا عَبْدُكَ، وَأَنَا عَلَى عَهْدِكَ وَوَعْدِكَ مَا اسْتَطَعْتُ، "
        "أَعُوذُ بِكَ مِنْ شَرِّ مَا صَنَعْتُ، أَبُوءُ لَكَ بِنِعْمَتِكَ عَلَيَّ، وَأَبُوءُ بِذَنْبِي فَاغْفِرْ لِي، "
        "فَإِنَّهُ لَا يَغْفِرُ الذُّنُوبَ إِلَّا أَنْتَ."),
    "rain": ("🌧️ دعاء نزول المطر",
        "اللَّهُمَّ صَيِّبًا نَافِعًا.\n\n"
        "اللَّهُمَّ اغْفِرْ لَنَا وَارْحَمْنَا وَعَافِنَا وَارْزُقْنَا."),
    "anger": ("😤 دعاء عند الغضب",
        "أَعُوذُ بِاللَّهِ مِنَ الشَّيْطَانِ الرَّجِيمِ."),
}