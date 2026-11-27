# ==========================================
# ملف: web_ui.py
# ==========================================
import os
import re
import json
import time
import uuid
import requests
from datetime import datetime, date # تمت إضافة date هنا لحل المشكلة
from flask import Flask, request, jsonify, Response
from urllib.parse import urlparse

from config import (bot_state, ADMIN_PASSWORD, login_tokens, lock, photo_cache, 
                    BROWSER_HEADERS, YDL_BASE, TELEGRAM_TOKEN, BOT_IDENTITY,
                    VISION_MODELS_DEFAULT, TEXT_MODELS_DEFAULT, FEATURE_DEFAULTS,
                    URL_HOSTS, PLATFORM_ALIASES)
from database import save_db, flush_db, audit, log_points, log_event, LOG_GROUPS
from utils import esc, check_admin, bg, log_error, safe_url, safe_name, store_url, get_url
from points import setting, get_points, apply_points, notify_points, points_bar, POINTS_DEFAULTS
from telegram_api import TG_SESSION, send_message
from admin import start_broadcast, schedule_broadcast, bc_state, PERMS
from downloader import ytdlp_info, do_update_ytdlp, ytdlp_status, cookies_info
from account_lookup import lookup_account, prof_public, PLATFORMS, PLATFORM_NAMES, USER_RE, ACCOUNT_ACTORS

app = Flask(__name__)

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>لوحة التحكم</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
:root{--p:#5eead4;--s:#c084fc;--b:#60a5fa;--txt:#f8fafc;--mut:rgba(226,232,240,.62)}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font-family:'Cairo',system-ui,sans-serif;color:var(--txt);min-height:100vh;background:#060914;overflow-x:hidden;padding:14px 14px 40px}
.orb{position:fixed;border-radius:50%;z-index:-1;will-change:transform;pointer-events:none;animation:float 26s ease-in-out infinite}
.o1{width:620px;height:620px;top:-220px;right:-240px;background:radial-gradient(circle,rgba(20,184,166,.75),rgba(20,184,166,0) 68%)}
.o2{width:600px;height:600px;bottom:-230px;left:-230px;background:radial-gradient(circle,rgba(147,51,234,.75),rgba(147,51,234,0) 68%);animation-delay:-9s}
.o3{width:520px;height:520px;top:36%;left:-240px;background:radial-gradient(circle,rgba(37,99,235,.7),rgba(37,99,235,0) 68%);animation-delay:-16s}
@keyframes float{0%,100%{transform:translate3d(0,0,0)}50%{transform:translate3d(36px,-44px,0)}}
.glass{position:relative;overflow:hidden;border-radius:26px;background:linear-gradient(135deg,rgba(255,255,255,.17),rgba(255,255,255,.05));-webkit-backdrop-filter:blur(18px) saturate(170%);backdrop-filter:blur(18px) saturate(170%);border:1px solid rgba(255,255,255,.2);box-shadow:0 10px 36px rgba(0,0,0,.38),inset 0 1.5px 0 rgba(255,255,255,.4)}
.glass::before{content:'';position:absolute;inset:0;pointer-events:none;border-radius:inherit;background:radial-gradient(120% 70% at 85% -10%,rgba(255,255,255,.28),transparent 55%)}
.glass>*{position:relative}
.wrap{max-width:900px;margin:0 auto}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:14px 18px;margin-bottom:16px;position:sticky;top:10px;z-index:20}
.top h1{font-size:20px;font-weight:900;background:linear-gradient(90deg,var(--p),var(--s),var(--b));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.top small{display:flex;align-items:center;gap:6px;color:var(--mut);font-size:11px;font-weight:600}
.live i{width:8px;height:8px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 0 rgba(74,222,128,.7);animation:pulse 2s infinite}
@keyframes pulse{70%{box-shadow:0 0 0 8px rgba(74,222,128,0)}100%{box-shadow:0 0 0 0 rgba(74,222,128,0)}}
.btn{font-family:inherit;font-weight:700;font-size:13px;color:#fff;cursor:pointer;border-radius:14px;padding:9px 15px;border:1px solid rgba(255,255,255,.28);background:linear-gradient(135deg,rgba(255,255,255,.2),rgba(255,255,255,.06));box-shadow:inset 0 1px 0 rgba(255,255,255,.35);transition:transform .2s,border-color .2s;display:inline-flex;align-items:center;gap:6px}
.btn:hover{transform:translateY(-2px);border-color:var(--p)}
.btn:active{transform:scale(.96)}
.btn[disabled]{opacity:.5;pointer-events:none}
.btn.red{color:#fecaca;border-color:rgba(248,113,113,.5);background:linear-gradient(135deg,rgba(239,68,68,.3),rgba(239,68,68,.08))}
.btn.green{color:#bbf7d0;border-color:rgba(74,222,128,.5);background:linear-gradient(135deg,rgba(34,197,94,.3),rgba(34,197,94,.08))}
.btn.blue{color:#bfdbfe;border-color:rgba(96,165,250,.5);background:linear-gradient(135deg,rgba(59,130,246,.3),rgba(59,130,246,.08))}
.btn.sm{padding:6px 11px;font-size:12px;border-radius:11px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-bottom:18px}
@media(min-width:720px){.grid{grid-template-columns:repeat(4,1fr)}}
.card{font-family:inherit;color:inherit;text-align:center;padding:22px 10px 16px;cursor:pointer;transition:transform .3s,border-color .3s;animation:rise .6s ease both}
.card:hover{transform:translateY(-6px) scale(1.03);border-color:rgba(255,255,255,.5)}
.card:active{transform:scale(.96)}
.card .ic{font-size:34px}
.card h3{font-size:13px;color:var(--mut);font-weight:700;margin:6px 0 2px}
.num{font-size:34px;font-weight:900;line-height:1.3;height:1.3em;overflow:hidden;display:flex;justify-content:center}
.card .more{display:inline-block;margin-top:6px;font-size:11px;color:var(--p);font-weight:700}
.sec{padding:16px;margin-bottom:18px}
.sec h2{font-size:16px;font-weight:900;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.big{width:100%;justify-content:center;padding:14px;font-size:15px}
.row{display:flex;gap:12px;align-items:flex-start;padding:12px;margin-bottom:10px;border-radius:20px;background:linear-gradient(135deg,rgba(255,255,255,.12),rgba(255,255,255,.03));border:1px solid rgba(255,255,255,.14);box-shadow:inset 0 1px 0 rgba(255,255,255,.25)}
.row.in{animation:rise .45s ease both}
.av{flex:0 0 46px;height:46px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:19px;position:relative;overflow:hidden;background:linear-gradient(135deg,hsl(var(--h),85%,60%),hsl(calc(var(--h) + 50),85%,45%));border:2px solid rgba(255,255,255,.45)}
.av img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:50%;z-index:1}
.meta{flex:1;min-width:0}
.line{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin-bottom:6px}
.line b{font-size:15px;font-weight:900}
.un{color:var(--p);font-size:12px;font-weight:700}
.tag{font-size:11px;font-weight:800;padding:3px 10px;border-radius:20px;border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.1)}
.txt{background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:9px 11px;font-size:13px;line-height:1.55;word-break:break-all;color:#e2e8f0;max-height:110px;overflow:auto}
.foot{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px;font-size:11px;color:var(--mut);font-weight:600}
.foot .sp{flex:1}
.bar{display:flex;align-items:center;gap:10px;padding:12px 14px;margin-bottom:14px}
.bar h2{flex:1;font-size:18px;font-weight:900}
.cnt{font-size:12px;color:var(--mut);font-weight:700}
.search{width:100%;padding:13px 16px;margin-bottom:12px;border-radius:16px;font-family:inherit;font-size:14px;color:#fff;outline:none;background:linear-gradient(135deg,rgba(255,255,255,.13),rgba(255,255,255,.04));border:1px solid rgba(255,255,255,.22)}
.search::placeholder{color:var(--mut)}
.search:focus{border-color:var(--p)}
textarea.search{min-height:110px;resize:vertical;line-height:1.6}
.chips{display:flex;gap:8px;overflow-x:auto;padding-bottom:10px}
.chip{flex:0 0 auto;font-family:inherit;font-size:12px;font-weight:700;color:var(--txt);cursor:pointer;padding:7px 14px;border-radius:20px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18)}
.chip.on{background:linear-gradient(135deg,rgba(94,234,212,.4),rgba(96,165,250,.3));border-color:var(--p)}
.empty{text-align:center;padding:36px 16px;color:var(--mut);font-weight:600;line-height:1.8}
.empty .ei{font-size:42px;display:block;margin-bottom:8px}
.pill{display:inline-block;font-size:12px;font-weight:800;padding:4px 11px;border-radius:20px;background:rgba(251,191,36,.18);border:1px solid rgba(251,191,36,.45);color:#fde68a}
.pill.c{background:rgba(94,234,212,.15);border-color:rgba(94,234,212,.45);color:#99f6e4}
.bc-bar{height:10px;border-radius:10px;background:rgba(255,255,255,.12);overflow:hidden;margin:12px 0 6px}
.bc-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--p),var(--b));transition:width .4s}
.bc-txt{font-size:12px;color:var(--mut);font-weight:700}
.modal{display:none;position:fixed;inset:0;z-index:100;background:rgba(2,6,23,.6);align-items:center;justify-content:center;padding:20px}
.mc{width:100%;max-width:420px;padding:26px 22px;text-align:center;animation:zoom .3s ease;max-height:90vh;overflow-y:auto}
.mc h2{font-size:20px;font-weight:900;margin-bottom:4px}
.mc p{color:var(--mut);font-size:13px;margin-bottom:14px}
.mc input:not([type=checkbox]){width:100%;padding:14px;margin-bottom:14px;border-radius:14px;text-align:center;font-family:inherit;font-size:16px;color:#fff;outline:none;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.25)}
.mc input:not([type=checkbox]):focus{border-color:var(--p)}
.mc .btn{width:100%;justify-content:center;padding:13px;font-size:15px;margin-top:8px}
.chk{display:flex;align-items:center;gap:10px;text-align:right;padding:11px 14px;margin-bottom:8px;border-radius:14px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);font-weight:700;font-size:14px;cursor:pointer}
.chk input{width:20px;height:20px;accent-color:#5eead4}
.fld{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 4px;font-weight:700;font-size:14px}
.fld input:not([type=checkbox]){width:110px;padding:9px 10px;border-radius:12px;text-align:center;font-family:inherit;font-size:15px;color:#fff;outline:none;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.25)}
.fld input[type=checkbox]{width:24px;height:24px;accent-color:#5eead4}
.quick{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;justify-content:center}
.toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%) translateY(90px);padding:11px 20px;border-radius:16px;font-weight:700;font-size:13px;z-index:200;transition:transform .4s}
.toast.show{transform:translateX(-50%) translateY(0)}
.footer{text-align:center;color:var(--mut);font-size:12px;margin-top:10px;font-weight:600}
@keyframes rise{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}
@keyframes zoom{from{opacity:0;transform:scale(.85)}to{opacity:1;transform:none}}
.ud-tabs{display:flex;gap:6px;margin-bottom:12px}
.ud-tabs .chip{flex:1;text-align:center;font-size:11px}
.ud-body{max-height:340px;overflow-y:auto;text-align:right}
.ud-row{display:flex;justify-content:space-between;padding:9px 12px;margin-bottom:6px;border-radius:12px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);font-size:13px}
.ud-row .k{color:var(--mut);font-weight:700}
.ud-row .v{color:#fff;font-weight:800;text-align:left}
.ud-tx{display:flex;justify-content:space-between;align-items:center;padding:9px 12px;margin-bottom:6px;border-radius:12px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);font-size:12px}
.ud-tx.pos{border-color:rgba(74,222,128,.4);background:rgba(74,222,128,.08)}
.ud-tx.neg{border-color:rgba(248,113,113,.4);background:rgba(248,113,113,.08)}
.ud-tx .d{font-size:16px;font-weight:900}
.ud-tx.pos .d{color:#86efac}
.ud-tx.neg .d{color:#fca5a5}
.ud-act{padding:8px 12px;margin-bottom:6px;border-radius:12px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);font-size:12px}
.ud-act .t{color:var(--mut);font-size:10px;margin-top:2px}
.ud-empty{text-align:center;padding:22px;color:var(--mut);font-size:12px}
.topbox{padding:12px 14px;margin-bottom:12px;border-radius:18px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14)}
.topbox>b{display:block;margin-bottom:8px;font-size:14px}
</style>
</head>
<body>
<div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>
<div class="wrap">
  <div class="top glass">
    <div><h1>🤖 مركز التحكم</h1><small class="live"><i></i>مباشر</small></div>
    <div>
      <button class="btn" id="login-btn" onclick="openModal()">🔐 دخول الأدمن</button>
      <button class="btn red" id="logout-btn" style="display:none" onclick="logout()">خروج</button>
    </div>
  </div>

  <div id="home">
    <div class="grid">
      <button class="card glass" onclick="go('requests')"><div class="ic">📥</div><h3>الطلبات</h3><div class="num" id="val-requests">0</div><span class="more">عرض ‹</span></button>
      <button class="card glass" onclick="go('downloads')"><div class="ic">✅</div><h3>التحميلات</h3><div class="num" id="val-downloads">0</div><span class="more">عرض ‹</span></button>
      <button class="card glass" onclick="go('ai')"><div class="ic">🧠</div><h3>شروحات AI</h3><div class="num" id="val-ai">0</div><span class="more">عرض ‹</span></button>
      <button class="card glass" onclick="go('users')"><div class="ic">👥</div><h3>المستخدمون</h3><div class="num" id="val-users">0</div><span class="more">عرض ‹</span></button>
    </div>
    <div class="grid" style="grid-template-columns:repeat(3,1fr)">
      <button class="card glass" onclick="go('listen')"><div class="ic">🎧</div><h3>الاستماع</h3><div class="num" id="val-listen">0</div><span class="more">عرض ‹</span></button>
      <button class="card glass" onclick="go('vision')"><div class="ic">🖼️</div><h3>الصور</h3><div class="num" id="val-vision">0</div><span class="more">عرض ‹</span></button>
      <button class="card glass" onclick="go('errors')"><div class="ic">⚠️</div><h3>الأخطاء</h3><div class="num" id="val-errors">0</div><span class="more">عرض ‹</span></button>
    </div>
    <div class="sec glass" id="admin-panel" style="display:none"><h2>⚙️ التحكم بالبوت</h2><button class="btn big" id="bot-btn" onclick="toggleBot()">...</button></div>
    <div class="sec glass" id="bc-sec" style="display:none">
      <h2>📢 إذاعة فورية</h2>
      <textarea class="search" id="bc-text" maxlength="1500" placeholder="نص الرسالة..."></textarea>
      <button class="btn green big" id="bc-btn" onclick="sendBroadcast()">📤 إرسال للجميع</button>
      <div id="bc-prog" style="display:none"><div class="bc-bar"><i id="bc-fill"></i></div><span class="bc-txt" id="bc-txt"></span></div>
    </div>
    <div class="sec glass" id="schedule-sec" style="display:none">
      <h2>⏰ إذاعة مجدولة</h2>
      <textarea class="search" id="sb-text" placeholder="نص الرسالة..." maxlength="1500"></textarea>
      <input class="search" id="sb-due" placeholder="الوقت: 2026-12-01 18:30">
      <button class="btn blue big" onclick="addSchedule()">📅 جدولة</button>
      <div id="scheduled-list" style="margin-top:14px"></div>
    </div>
    <div class="sec glass" id="adm-sec" style="display:none"><h2>🛡️ المشرفون</h2><div id="adm-list"></div></div>
    <div class="sec glass" id="set-sec" style="display:none"><h2>💰 إعدادات النقاط</h2>
      <label class="fld">🎁 نقاط البداية <input type="number" id="st-start" min="0"></label>
      <label class="fld">📆 المكافأة اليومية <input type="number" id="st-daily" min="0"></label>
      <label class="fld">🎲 سعر الأغنية <input type="number" id="st-song" min="0"></label>
      <button class="btn green big" onclick="saveSettings()">💾 حفظ</button></div>
    <div class="sec glass" id="feat-sec" style="display:none"><h2>🧩 المميزات والرؤية</h2>
      <div id="feat-toggles"></div>
      <label class="fld">🖼️ سعر تحليل الصورة (نقاط) <input type="number" id="ft-vcost" min="0" oninput="featDirty=true"></label>
      <label class="fld">👤 سعر معلومات الحساب (نقاط) <input type="number" id="ft-acost" min="0" oninput="featDirty=true"></label>
      <p class="bc-txt" style="margin:8px 0 4px">نماذج الرؤية (مفصولة بفاصلة — الأسماء المجانية تتغير):</p>
      <input class="search" id="ft-vmodels" dir="ltr" oninput="featDirty=true">
      <p class="bc-txt" style="margin:8px 0 4px">نماذج النص (للأسئلة والأدوات):</p>
      <input class="search" id="ft-tmodels" dir="ltr" oninput="featDirty=true">
      <button class="btn green big" onclick="saveFeatures()">💾 حفظ</button>
    </div>
    <div class="sec glass" id="acct-sec" style="display:none"><h2>👤 معلومات حساب (ويب + مباشر + Apify)</h2>
      <label class="fld">المنصة <select id="ac-plat" class="search"><option value="all">🔎 بحث شامل</option><option value="tiktok">TikTok</option><option value="instagram">Instagram</option><option value="x">X / Twitter</option><option value="youtube">YouTube</option><option value="telegram">Telegram</option><option value="facebook">Facebook</option></select></label>
      <input class="search" id="ac-user" dir="ltr" placeholder="username أو رابط الحساب">
      <label class="fld">🧩 تعمّق باستخدام Apify (يستهلك رصيد Apify) <input type="checkbox" id="ac-deep"></label>
      <button class="btn blue big" id="ac-btn" onclick="acctLookup()">🔎 جلب المعلومات</button>
      <div class="bc-txt" id="ac-msg" style="margin:8px 0"></div>
      <div id="ac-out"></div>
    </div>
    <div class="sec glass" id="fix-sec" style="display:none"><h2>🛠️ إصلاح التحميل</h2>
      <div class="ud-row"><span class="k">إصدار yt-dlp</span><span class="v" id="yd-ver">—</span></div>
      <div class="bc-txt" id="yd-msg" style="margin:6px 0 10px"></div>
      <button class="btn blue big" id="yd-btn" onclick="updateYtdlp()">⬆️ تحديث yt-dlp</button>
      <p class="bc-txt" style="margin:14px 0 6px">🍪 كوكيز بصيغة Netscape لحل «سجّل الدخول / لست روبوتاً» (يوتيوب، فيسبوك، إنستجرام). استخدم حساباً ثانوياً:</p>
      <div class="ud-row"><span class="k">الحالة</span><span class="v" id="ck-state">—</span></div>
      <textarea class="search" id="ck-text" dir="ltr" placeholder="# Netscape HTTP Cookie File ..."></textarea>
      <button class="btn green big" onclick="saveCookies()">💾 حفظ الكوكيز</button>
      <button class="btn red big" style="margin-top:8px" onclick="clearCookies()">🗑️ حذف الكوكيز</button>
    </div>
    <div class="sec glass" id="spam-sec" style="display:none">
      <h2>🛡️ الحماية ومكافحة الإساءة</h2>
      <label class="fld">🚫 حد الحظر لكل مشرف <input type="number" id="sp-ban-th" min="1"></label>
      <label class="fld">⏱️ نافذة الحظر (دقائق) <input type="number" id="sp-ban-w" min="1"></label>
      <label class="fld">💬 حد الرسائل/دقيقة <input type="number" id="sp-spm" min="1"></label>
      <label class="fld">🧮 تسعير ديناميكي <input type="checkbox" id="sp-dyn"></label>
      <label class="fld">📉 أقل سعر <input type="number" id="sp-min" min="1"></label>
      <label class="fld">📈 أعلى سعر <input type="number" id="sp-max" min="1"></label>
      <button class="btn green big" onclick="saveSpamSettings()">💾 حفظ</button>
    </div>
    <div class="sec glass" id="audit-sec" style="display:none"><h2>📋 سجل العمليات</h2><div id="audit-list"></div></div>
    <div class="sec glass" id="suggest-sec" style="display:none"><h2>💡 اقتراحات المستخدمين</h2><div id="suggest-list"></div></div>
    <div class="sec glass" id="changelog-sec" style="display:none">
      <h2>🎉 إدارة التحديثات</h2>
      <input class="search" id="cl-ver" placeholder="رقم الإصدار (مثال: 2.1)" maxlength="20">
      <textarea class="search" id="cl-items" placeholder="ميزات التحديث (كل ميزة في سطر)"></textarea>
      <label class="chk"><input type="checkbox" id="cl-announce" checked> 📢 إرسال إعلان للمستخدمين</label>
      <button class="btn green big" onclick="addChangelog()">➕ نشر التحديث</button>
      <div id="changelog-list" style="margin-top:14px"></div>
    </div>
    <div class="sec glass" id="banned-sec" style="display:none"><h2>🚫 المحظورون</h2><div id="banned-list"></div></div>
    <div class="sec glass" id="comp-sec" style="display:none"><h2>📩 الشكاوي</h2><div id="comp-list"></div></div>
    <div class="sec glass" id="hint-sec"><div class="empty"><span class="ei">🔐</span>اضغط على أي بطاقة لعرض التفاصيل.<br>التفاصيل تظهر للأدمن فقط.</div></div>
  </div>

  <div id="detail" style="display:none">
    <div class="bar glass"><button class="btn" onclick="go('home')">› رجوع</button><h2 id="d-title"></h2><span class="cnt" id="d-count"></span></div>
    <input class="search" id="q" placeholder="🔎 ابحث..." oninput="q=this.value.trim().toLowerCase();sigDetail='';renderDetail()">
    <div class="chips" id="chips"></div>
    <div id="d-extra"></div>
    <div id="d-list"></div>
  </div>
  <div class="footer">⏱️ بدأت الجلسة: __START__ | يتحدث تلقائياً</div>
</div>

<div class="modal" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="mc glass"><h2>🔐 دخول الأدمن</h2><p>أدخل كلمة السر</p>
    <input type="password" id="pwd" placeholder="كلمة السر..." onkeypress="if(event.key==='Enter')verify()">
    <button class="btn green" onclick="verify()">دخول</button></div>
</div>
<div class="modal" id="pmodal" onclick="if(event.target===this)closePerms()">
  <div class="mc glass"><h2>🛡️ صلاحيات المشرف</h2><p id="p-name"></p>
    <label class="chk"><input type="checkbox" id="pm-ban"> 🚫 الحظر</label>
    <label class="chk"><input type="checkbox" id="pm-broadcast"> 📢 الإذاعة</label>
    <label class="chk"><input type="checkbox" id="pm-complaints"> 📩 الشكاوي</label>
    <label class="chk"><input type="checkbox" id="pm-points"> 💰 النقاط</label>
    <label class="chk"><input type="checkbox" id="pm-listen"> 🎧 مراقبة الاستماع</label>
    <label class="chk"><input type="checkbox" id="pm-bot"> ⚙️ تشغيل/إيقاف</label>
    <label class="chk"><input type="checkbox" id="pm-hosting"> 🤖 رفع بوتات</label>
    <button class="btn blue" onclick="allPerms()">✨ كل الصلاحيات</button>
    <button class="btn green" onclick="savePerms()">💾 حفظ</button>
    <button class="btn red" id="p-remove" onclick="removeRole()">إزالة الإشراف</button>
  </div>
</div>
<div class="modal" id="ptmodal" onclick="if(event.target===this)closePoints()">
  <div class="mc glass"><h2>💰 التحكم بالنقاط</h2><p id="pt-name"></p>
    <input type="number" id="pt-amount" placeholder="العدد (سالب للخصم)">
    <div class="quick"><button class="btn sm" onclick="quick(10)">+10</button><button class="btn sm" onclick="quick(50)">+50</button><button class="btn sm" onclick="quick(100)">+100</button><button class="btn red sm" onclick="quick(-10)">-10</button></div>
    <input type="text" id="pt-note" maxlength="100" placeholder="ملاحظة (اختياري)">
    <label class="chk"><input type="checkbox" id="pt-notify" checked> 📨 إرسال إشعار</label>
    <button class="btn green" onclick="savePoints()">✅ تطبيق</button>
  </div>
</div>
<div class="modal" id="udmodal" onclick="if(event.target===this)closeUserDetail()">
  <div class="mc glass" style="max-width:560px;text-align:right">
    <div style="display:flex;gap:14px;align-items:center;margin-bottom:16px">
      <div id="ud-avatar"></div>
      <div style="flex:1"><h2 id="ud-name" style="font-size:18px;margin:0;text-align:right"></h2><p id="ud-username" style="margin:2px 0 0;color:var(--mut);font-size:12px;text-align:right"></p></div>
    </div>
    <div class="ud-tabs">
      <button class="chip on" id="ud-tab-info" onclick="udTab('info')">ℹ️ معلومات</button>
      <button class="chip" id="ud-tab-points" onclick="udTab('points')">💰 النقاط</button>
      <button class="chip" id="ud-tab-activity" onclick="udTab('activity')">📋 النشاط</button>
      <button class="chip" id="ud-tab-listen" onclick="udTab('listen')">🎧 يسمع</button>
    </div>
    <div class="ud-body" id="ud-content"></div>
    <button class="btn red" style="width:100%;margin-top:12px" onclick="closeUserDetail()">إغلاق</button>
  </div>
</div>
<div class="toast glass" id="toast"></div>

<script>
let isAdmin=false,pwd='',authToken='',view='home',filter='all',q='',pending=null,S=null,LOG=[],SHOWN=[],permUid=null;
let sigHome='',sigDetail='',seen=new Set(),firstLoad=true;
const $=id=>document.getElementById(id);
const LOGVIEWS=['requests','downloads','ai','listen','vision','errors'];
const PKEYS=['ban','broadcast','complaints','bot','points','listen','hosting'];
const PLABEL={ban:'🚫 الحظر',broadcast:'📢 الإذاعة',complaints:'📩 الشكاوي',bot:'⚙️ التشغيل',points:'💰 النقاط',listen:'🎧 الاستماع',hosting:'🤖 رفع بوتات'};
const KIND={link:['🔗','رابط'],music:['🎵','أغنية'],ai:['🧠','سؤال'],cmd:['⌨️','أمر'],draw:['🎨','رسم'],download:['✅','تحميل'],ai_explain:['🤖','شرح'],listen:['🎧','استماع'],vision:['🖼️','صورة'],error:['⚠️','خطأ']};
const TITLES={requests:'📥 الطلبات',downloads:'✅ التحميلات',ai:'🧠 شروحات',users:'👥 المستخدمون',listen:'🎧 الاستماع',vision:'🖼️ الصور',errors:'⚠️ أخطاء التحميل'};
const REQ_FILTERS=[['all','الكل'],['link','🔗'],['music','🎵'],['ai','🧠'],['cmd','⌨️'],['draw','🎨']];

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function api(url,extra){return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({password:pwd},extra||{}))});}
function hue(id){let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))%360;return h;}
function avatar(name,id){
  const ch=esc(Array.from((name||'?').trim())[0]||'?').toUpperCase();
  const base='<div class="av" style="--h:'+hue(id)+'"><span>'+ch+'</span>';
  if(isAdmin&&authToken)return base+'<img src="/api/avatar/'+encodeURIComponent(id)+'?t='+encodeURIComponent(authToken)+'" loading="lazy" onerror="this.remove()"></div>';
  return base+'</div>';
}
function ago(t){const d=new Date(String(t).replace(' ','T'));if(isNaN(d))return esc(t);const s=Math.max(0,Math.floor((Date.now()-d)/1000));
  if(s<60)return 'الآن';if(s<3600)return 'قبل '+Math.floor(s/60)+'د';if(s<86400)return 'قبل '+Math.floor(s/3600)+'س';return 'قبل '+Math.floor(s/86400)+'ي';}
function toast(m){const t=$('toast');t.innerText=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),1900);}
function copyTxt(i){const txt=SHOWN[i]||'';if(navigator.clipboard){navigator.clipboard.writeText(txt).then(()=>toast('تم النسخ ✅'));}else{const a=document.createElement('textarea');a.value=txt;document.body.appendChild(a);a.select();try{document.execCommand('copy');toast('تم النسخ ✅');}catch(e){}a.remove();}}
function setNum(id,val){const el=$(id);const nv=String(val);if(el.dataset.v===nv)return;el.textContent=nv;el.dataset.v=nv;}

function openModal(){$('modal').style.display='flex';$('pwd').focus();}
function closeModal(){$('modal').style.display='none';pending=null;}
function verify(){const p=$('pwd').value;
  fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:p})}).then(r=>r.json()).then(d=>{
    if(d.status==='success'){isAdmin=true;pwd=p;authToken=d.token;$('pwd').value='';$('modal').style.display='none';const v=pending;pending=null;sigHome='';if(v){go(v);}else{refresh();}}
    else{toast('❌ كلمة السر غير صحيحة');}}).catch(()=>toast('❌ خطأ'));}
function logout(){isAdmin=false;pwd='';authToken='';LOG=[];view='home';sigHome='';sigDetail='';refresh();}

function go(v){if(v!=='home'&&!isAdmin){pending=v;openModal();return;}view=v;filter='all';q='';$('q').value='';LOG=[];seen=new Set();sigDetail='';window.scrollTo({top:0});refresh();}
function setFilter(k){filter=k;sigDetail='';renderDetail();}
function toggleBot(){api('/api/toggle_bot').then(refresh);}
function banUser(u){if(!confirm('حظر المستخدم؟'))return;api('/api/ban',{uid:u}).then(refresh);}
function unbanUser(u){api('/api/unban',{uid:u}).then(refresh);}
function delComp(u){api('/api/delete_complaint',{uid:u}).then(refresh);}
function replyComp(u){const m=prompt('أدخل نص الرد:');if(!m)return;api('/api/reply_complaint',{uid:u,message:m}).then(()=>{toast('تم ✅');refresh();});}

function sendBroadcast(){const m=$('bc-text').value.trim();if(!m){toast('اكتب الرسالة');return;}
  if(!confirm('إرسال لكل المستخدمين؟'))return;
  api('/api/broadcast',{message:m}).then(r=>r.json()).then(d=>{if(d.status==='success'){$('bc-text').value='';toast('بدأت الإذاعة 📢');}else{toast(d.error||'خطأ');}refresh();});}

function openPerms(uid){permUid=uid;const u=(S.users||{})[uid]||{name:'مستخدم'};const cur=(S.admins||{})[uid]||[];
  $('p-name').innerText=u.name+' — ID: '+uid;PKEYS.forEach(k=>{$('pm-'+k).checked=cur.includes(k);});
  $('p-remove').style.display=cur.length?'inline-flex':'none';$('pmodal').style.display='flex';}
function closePerms(){$('pmodal').style.display='none';}
function allPerms(){PKEYS.forEach(k=>{$('pm-'+k).checked=true;});}
function savePerms(){const perms=PKEYS.filter(k=>$('pm-'+k).checked);
  api('/api/set_role',{uid:permUid,perms:perms}).then(()=>{closePerms();toast(perms.length?'تم الحفظ ✅':'تمت الإزالة');refresh();});}
function removeRole(uid){api('/api/set_role',{uid:uid||permUid,perms:[]}).then(()=>{closePerms();toast('تمت الإزالة');refresh();});}

let ptUid=null;
function openPoints(uid){ptUid=uid;const u=(S.users||{})[uid]||{name:'مستخدم',points:0};
  $('pt-name').innerText=u.name+' — رصيده: '+(u.points||0);
  $('pt-amount').value='';$('pt-note').value='';$('pt-notify').checked=true;$('ptmodal').style.display='flex';}
function closePoints(){$('ptmodal').style.display='none';}
function quick(n){$('pt-amount').value=n;}
function savePoints(){const a=parseInt($('pt-amount').value,10);if(isNaN(a)){toast('أدخل رقماً');return;}
  api('/api/points',{uid:ptUid,mode:'add',amount:a,note:$('pt-note').value.trim(),notify:$('pt-notify').checked}).then(r=>r.json()).then(d=>{
    if(d.status==='success'){closePoints();toast('تم ✅');}else{toast(d.error||'خطأ');}refresh();});}
function saveSettings(){api('/api/settings',{start_points:$('st-start').value,daily_bonus:$('st-daily').value,song_cost:$('st-song').value}).then(()=>{toast('تم ✅');refresh();});}

function loadSpamSettings(){const st=S.settings||{};$('sp-ban-th').value=st.ban_threshold||10;$('sp-ban-w').value=st.ban_window_min||60;$('sp-spm').value=st.anti_spam_per_min||10;$('sp-dyn').checked=!!st.dynamic_pricing;$('sp-min').value=st.min_song_cost||3;$('sp-max').value=st.max_song_cost||20;}
function saveSpamSettings(){api('/api/spam_settings',{ban_threshold:$('sp-ban-th').value,ban_window_min:$('sp-ban-w').value,anti_spam_per_min:$('sp-spm').value,dynamic_pricing:$('sp-dyn').checked,min_song_cost:$('sp-min').value,max_song_cost:$('sp-max').value}).then(()=>{toast('تم ✅');refresh();});}

async function loadAudit(){const r=await api('/api/audit_log');const d=await r.json();let h='';
  (d.items||[]).forEach(e=>{h+=`<div class="ud-row"><div style="flex:1"><b>${esc(e.by_name)}</b> — <span style="color:var(--p)">${esc(e.action)}</span>${e.target?` → <code>${esc(e.target)}</code>`:''}${e.details?`<div class="ud-act" style="margin-top:6px;padding:6px 10px">${esc(e.details)}</div>`:''}<div style="color:var(--mut);font-size:10px;margin-top:4px">${esc(e.t)}</div></div></div>`;});
  $('audit-list').innerHTML=h||'<div class="empty">لا توجد عمليات.</div>';}
async function loadSuggestions(){const r=await api('/api/suggestions');const d=await r.json();let h='';
  Object.entries(d.items||{}).forEach(([uid,s])=>{h+=`<div class="row"><div class="meta"><div class="line"><b>${esc(s.name)}</b>${s.username?`<span class="un">@${esc(s.username)}</span>`:''}<span class="un">ID: ${esc(uid)}</span></div><div class="txt">${esc(s.message)}</div><div class="foot"><span>🕒 ${esc(s.date)}</span><span class="sp"></span><button class="btn red sm" onclick="delSuggestion('${esc(uid)}')">🗑️ حذف</button></div></div></div>`;});
  $('suggest-list').innerHTML=h||'<div class="empty">لا توجد اقتراحات.</div>';}
function delSuggestion(uid){api('/api/delete_suggestion',{uid}).then(()=>refresh());}
function addChangelog(){const v=$('cl-ver').value.trim(),it=$('cl-items').value.trim();if(!v||!it){toast('املأ الحقول');return;}
  api('/api/changelog',{version:v,items:it,announce:$('cl-announce').checked}).then(r=>r.json()).then(d=>{
    if(d.status==='success'){$('cl-ver').value='';$('cl-items').value='';toast('نُشر ✅');refresh();}else toast(d.error||'خطأ');});}
async function loadChangelog(){const r=await api('/api/changelog');const d=await r.json();let h='';
  (d.items||[]).forEach(c=>{h+=`<div class="row"><div class="meta"><div class="line"><b>v${esc(c.version)}</b><span class="un">${esc(c.date)}</span></div><div class="txt">${c.items.map(i=>'✨ '+esc(i)).join('<br>')}</div></div></div>`;});
  $('changelog-list').innerHTML=h||'<div class="empty">لا توجد تحديثات.</div>';}
function addSchedule(){const t=$('sb-text').value.trim(),due=$('sb-due').value.trim();if(!t||!due){toast('املأ الحقول');return;}
  api('/api/schedule_broadcast',{text:t,due}).then(r=>r.json()).then(d=>{
    if(d.status==='success'){$('sb-text').value='';$('sb-due').value='';toast('تمت الجدولة ✅');refresh();}else toast(d.error||'خطأ');});}
async function loadScheduled(){const r=await api('/api/scheduled_list');const d=await r.json();let h='';
  (d.items||[]).forEach(s=>{const when=new Date(s.due*1000).toLocaleString('ar');h+=`<div class="row"><div class="meta"><div class="line"><b>⏰ ${esc(when)}</b></div><div class="txt">${esc(s.text)}</div><div class="foot"><span class="sp"></span><button class="btn red sm" onclick="delScheduled('${esc(s.id)}')">🗑️ إلغاء</button></div></div></div>`;});
  $('scheduled-list').innerHTML=h||'<div class="empty">لا توجد جدولة.</div>';}
function delScheduled(id){api('/api/delete_scheduled',{id}).then(()=>refresh());}

let udData=null,udTabCur='info';
function openUserDetail(uid){$('udmodal').style.display='flex';$('ud-name').innerText='...';$('ud-content').innerHTML='<div class="ud-empty">جاري التحميل...</div>';udTabCur='info';
  ['info','points','activity','listen'].forEach(t=>$('ud-tab-'+t).classList.toggle('on',t==='info'));
  api('/api/user_detail',{uid}).then(r=>r.json()).then(d=>{if(d.status==='error'){$('ud-content').innerHTML='<div class="ud-empty">❌</div>';return;}
    udData=d;$('ud-name').innerText=d.info.name;$('ud-username').innerText=d.info.username?('@'+d.info.username):'بدون معرف';$('ud-avatar').innerHTML=avatar(d.info.name,d.info.uid);renderUd();});}
function closeUserDetail(){$('udmodal').style.display='none';}
function udTab(t){udTabCur=t;['info','points','activity','listen'].forEach(x=>$('ud-tab-'+x).classList.toggle('on',x===t));if(udData)renderUd();}
function renderUd(){if(!udData)return;const i=udData.info;let h='';
  if(udTabCur==='info'){h+=row('💰 النقاط',i.points);h+=row('📥 الطلبات',i.requests);h+=row('📅 الانضمام',i.join_date);h+=row('🕐 آخر ظهور',i.last_seen);h+=row('🎁 آخر مكافأة',i.last_bonus||'—');h+=row('⏰ التذكيرات',i.reminders_count);h+=row('📍 الموقع',i.loc?i.loc.label:'لم يحدد');h+=row('🔔 الأذان',i.adhan?'✅':'❌');}
  else if(udTabCur==='points'){if(!udData.ptrans.length)h='<div class="ud-empty">لا يوجد سجل.</div>';else udData.ptrans.forEach(t=>{const pos=t.delta>0;h+=`<div class="ud-tx ${pos?'pos':'neg'}"><div style="flex:1"><div style="font-weight:800">${pos?'+':''}${t.delta}</div><div style="color:var(--mut);font-size:10px">${esc(t.t)} · ${esc(t.by)}</div></div><div class="d">${pos?'+':''}${t.delta}</div></div>`;});}
  else if(udTabCur==='listen'){if(!(udData.listen||[]).length)h='<div class="ud-empty">لا يوجد استماع مسجّل.</div>';else udData.listen.forEach(e=>{const p=(e.text||'').split(' | ');h+=`<div class="ud-act"><div><b>🎧 ${esc(p[0])}</b></div><div class="t">${esc(e.t)}${p[1]?' · '+esc(p[1]):''}</div></div>`;});}
  else{if(!udData.recent.length)h='<div class="ud-empty">لا يوجد نشاط.</div>';else udData.recent.forEach(e=>{const k=KIND[e.kind]||['•',e.kind];h+=`<div class="ud-act"><div><b>${k[0]} ${esc(k[1])}</b> — ${esc(e.text)}</div><div class="t">${esc(e.t)}</div></div>`;});}
  $('ud-content').innerHTML=h;}
function row(k,v){return '<div class="ud-row"><span class="k">'+k+'</span><span class="v">'+esc(v)+'</span></div>';}

const FEAT_LABELS={download:'📥 تحميل الفيديو والملفات',audio:'🎵 تحميل الأغاني (يوت)',song:'🎲 الأغنية العشوائية',vision:'🖼️ تحليل الصور واستخراج النص',ai:'🧠 أسئلة الذكاء الاصطناعي',tools:'🧰 الأدوات (طقس، عملات، حاسبة...)',account:'👤 معلومات الحسابات (Apify)'};
function acctDone(m){$('ac-btn').disabled=false;$('ac-msg').innerText=m||'';}
function acctLookup(){const u=$('ac-user').value.trim();if(!u){toast('اكتب اسم الحساب');return;}
  $('ac-btn').disabled=true;$('ac-msg').innerText='⏳ جاري البحث (قد يستغرق حتى دقيقة)...';$('ac-out').innerHTML='';
  api('/api/account',{platform:$('ac-plat').value,username:u,deep:$('ac-deep').checked}).then(r=>r.json()).then(d=>{if(d.status!=='success'){acctDone(d.error||'خطأ');return;}acctPoll(d.job,0);}).catch(()=>acctDone('تعذر الاتصال'));}
const AC_LBL=[['id','الايدي'],['username','المعرّف'],['name','الاسم'],['bio','النبذة'],['verified','موثّق'],['private','حساب خاص'],['bio_link','رابط النبذة'],['region','المنطقة'],['language','اللغة'],['created_txt','وقت الإنشاء'],['age_txt','عمر الحساب'],['followers','المتابعون'],['following','يتابع'],['likes','الإعجابات'],['posts','المنشورات'],['friends','الأصدقاء'],['url','الرابط']];
function acctCard(p){const rows=AC_LBL.map(a=>{let v=p[a[0]];if(v===null||v===undefined||v==='')return '';if(typeof v==='boolean')v=v?'نعم':'لا';if(typeof v==='number')v=v.toLocaleString('en-US');return '<div class="ud-row"><span class="k">'+esc(a[1])+'</span><span class="v">'+esc(String(v))+'</span></div>';}).join('');
  return '<div class="topbox"><b>'+esc(p.platform_name||'')+'</b>'+(p.avatar?'<br><img src="'+esc(p.avatar)+'" style="width:64px;height:64px;border-radius:50%;margin:6px 0" referrerpolicy="no-referrer">':'')+rows+'</div>';}
function acctPoll(job,n){if(n>80){acctDone('انتهت المهلة');return;}
  api('/api/account_result',{job:job}).then(r=>r.json()).then(d=>{
    if(d.state==='running'){setTimeout(()=>acctPoll(job,n+1),3000);return;}
    if(d.state!=='done'){acctDone(d.error||'فشل الجلب');return;}
    const r=d.result;acctDone(r.profiles.length||r.web?'✅ تم':'لم أجد معلومات');
    let h=r.profiles.map(acctCard).join('');
    if(r.web)h+='<div class="topbox"><b>🌐 من البحث في الويب</b><div class="bc-txt" style="white-space:pre-wrap">'+esc(r.web)+'</div></div>';
    if(r.notes.length)h+='<div class="bc-txt" style="margin-top:6px">'+r.notes.map(x=>'❌ '+esc(x[0])+': '+esc(x[1])).join('<br>')+'</div>';
    $('ac-out').innerHTML=h;
  }).catch(()=>acctDone('انقطع الاتصال'));}
let featDirty=false;
function loadFeatures(){const st=S.settings||{};const f=st.features||{};const box=$('feat-toggles');
  if(!box.children.length){box.innerHTML=Object.keys(FEAT_LABELS).map(k=>'<label class="fld">'+FEAT_LABELS[k]+' <input type="checkbox" data-f="'+k+'" onchange="featDirty=true"></label>').join('');}
  if(!featDirty){box.querySelectorAll('input[data-f]').forEach(i=>{i.checked=f[i.dataset.f]!==false;});
    [['ft-vcost',st.vision_cost],['ft-acost',st.account_cost],['ft-vmodels',st.vision_models],['ft-tmodels',st.text_models]].forEach(a=>{const e=$(a[0]);if(document.activeElement!==e&&a[1]!==undefined&&a[1]!==null)e.value=a[1];});}
  const y=S.ytdlp||{};$('yd-ver').innerText=y.version||'—';$('yd-msg').innerText=y.msg||'';$('yd-btn').disabled=!!y.running;
  const c=S.cookies||{};$('ck-state').innerText=c.exists?('✅ موجود ('+Math.round(c.size/1024)+'KB — '+c.updated+')'):'❌ غير مضاف';}
function saveFeatures(){const feats={};$('feat-toggles').querySelectorAll('input[data-f]').forEach(i=>{feats[i.dataset.f]=i.checked;});
  api('/api/features',{features:feats,vision_cost:$('ft-vcost').value,account_cost:$('ft-acost').value,vision_models:$('ft-vmodels').value,text_models:$('ft-tmodels').value}).then(r=>r.json()).then(d=>{featDirty=false;toast(d.status==='success'?'تم الحفظ ✅':(d.error||'خطأ'));refresh();});}
function updateYtdlp(){if(!confirm('تحديث yt-dlp الآن؟ (يحتاج إنترنت وقد يستغرق دقيقة)'))return;api('/api/ytdlp_update').then(r=>r.json()).then(d=>{toast(d.status==='success'?'بدأ التحديث ⏳':(d.error||'خطأ'));refresh();});}
function saveCookies(){const t=$('ck-text').value.trim();if(!t){toast('الصق محتوى cookies.txt');return;}
  api('/api/cookies',{cookies:t}).then(r=>r.json()).then(d=>{if(d.status==='success'){$('ck-text').value='';toast('تم حفظ الكوكيز ✅');}else toast(d.error||'خطأ');refresh();});}
function clearCookies(){if(!confirm('حذف الكوكيز؟'))return;api('/api/cookies_clear').then(()=>{toast('تم الحذف');refresh();});}
function renderExtra(items){const el=$('d-extra');let h='';
  if(view==='listen'||view==='errors'){const cnt={};
    LOG.forEach(e=>{let k;if(view==='listen'){k=(e.text||'').split(' | ')[0].trim();}else{const m=(e.text||'').match(/https?:\/\/([^\/\s]+)/);k=m?m[1].replace(/^www\./,''):((e.text||'').match(/^\[(\w+)\]/)||[0,'—'])[1];}
      if(k)cnt[k]=(cnt[k]||0)+1;});
    const top=Object.entries(cnt).sort((a,b)=>b[1]-a[1]).slice(0,6);
    if(top.length)h='<div class="topbox"><b>'+(view==='listen'?'🏆 الأكثر استماعاً':'📊 أكثر المصادر فشلاً')+'</b>'+top.map(t=>'<div class="ud-row"><span class="k">'+esc(t[0].slice(0,60))+'</span><span class="v">'+t[1]+'</span></div>').join('')+'</div>';}
  el.innerHTML=h;}

async function refresh(){try{const r=await api('/api/stats');S=await r.json();
  if(isAdmin&&LOGVIEWS.includes(view)){const l=await api('/api/log',{view});if(l.ok)LOG=(await l.json()).items;}}catch(e){console.log(e);}render();}
async function loop(){if(!document.hidden){await refresh();}setTimeout(loop,(S&&S.broadcast&&S.broadcast.running)?1200:3500);}

function render(){if(!S)return;
  setNum('val-requests',S.stats.total_requests);setNum('val-downloads',S.stats.successful_downloads);setNum('val-ai',S.stats.ai_explanations);setNum('val-users',S.users_count);setNum('val-listen',S.stats.listens||0);setNum('val-vision',S.stats.visions||0);setNum('val-errors',S.stats.errors||0);
  $('login-btn').style.display=isAdmin?'none':'inline-flex';$('logout-btn').style.display=isAdmin?'inline-flex':'none';
  const home=view==='home';$('home').style.display=home?'block':'none';$('detail').style.display=home?'none':'block';
  if(home)renderHome();else renderDetail();}

function renderHome(){
  $('hint-sec').style.display=isAdmin?'none':'block';
  ['admin-panel','bc-sec','schedule-sec','adm-sec','set-sec','feat-sec','acct-sec','fix-sec','spam-sec','audit-sec','suggest-sec','changelog-sec','banned-sec','comp-sec'].forEach(i=>{$(i).style.display=isAdmin?'block':'none';});
  if(!isAdmin)return;
  const b=$('bot-btn');if(S.bot_active){b.innerText='🟢 البوت يعمل';b.className='btn green big';}else{b.innerText='🔴 متوقف';b.className='btn red big';}
  const bc=S.broadcast||{};$('bc-btn').disabled=!!bc.running;
  if(bc.total>0){$('bc-prog').style.display='block';const done=bc.sent+bc.failed;$('bc-fill').style.width=Math.min(100,Math.round(done/bc.total*100))+'%';$('bc-txt').innerText=(bc.running?'⏳ ':'✅ ')+'وصلت:'+bc.sent+' فشلت:'+bc.failed+' إجمالي:'+bc.total;}
  const st=S.settings||{};[['st-start','start_points'],['st-daily','daily_bonus'],['st-song','song_cost']].forEach(a=>{const e=$(a[0]);if(document.activeElement!==e&&st[a[1]]!==undefined)e.value=st[a[1]];});
  const sig=JSON.stringify([S.banned_users,S.complaints,S.admins,Object.keys(S.users||{}).length,isAdmin,authToken?1:0,S.settings]);
  if(sig!==sigHome){sigHome=sig;
    let h='';
    Object.keys(S.admins||{}).forEach(uid=>{const u=S.users[uid]||{name:'مشرف'};const perms=S.admins[uid];
      h+='<div class="row">'+avatar(u.name,uid)+'<div class="meta"><div class="line"><b>'+esc(u.name)+'</b><span class="un">'+esc(uid)+'</span></div><div class="line">'+perms.map(p=>'<span class="tag">'+(PLABEL[p]||esc(p))+'</span>').join('')+'</div><div class="foot"><button class="btn blue sm" onclick="openPerms(\''+esc(uid)+'\')">✏️</button><button class="btn red sm" onclick="removeRole(\''+esc(uid)+'\')">إزالة</button></div></div></div>';});
    $('adm-list').innerHTML=h||'<div class="empty">لا يوجد مشرفون.</div>';
    h='';(S.banned_users||[]).forEach(uid=>{const u=S.users[uid]||{name:'محظور'};h+='<div class="row">'+avatar(u.name,uid)+'<div class="meta"><div class="line"><b>'+esc(u.name)+'</b><span class="un">'+esc(uid)+'</span></div><button class="btn green sm" onclick="unbanUser(\''+esc(uid)+'\')">✅ إزالة</button></div></div>';});
    $('banned-list').innerHTML=h||'<div class="empty">لا يوجد محظورون.</div>';
    h='';for(const uid in (S.complaints||{})){const c=S.complaints[uid];h+='<div class="row">'+avatar(c.name,uid)+'<div class="meta"><div class="line"><b>'+esc(c.name)+'</b></div><div class="txt">'+esc(c.message)+'</div><div class="foot"><button class="btn blue sm" onclick="replyComp(\''+esc(uid)+'\')">✉️ رد</button><button class="btn red sm" onclick="delComp(\''+esc(uid)+'\')">🗑️</button></div></div></div>';}
    $('comp-list').innerHTML=h||'<div class="empty">لا يوجد شكاوي.</div>';
  }
  loadAudit();loadSpamSettings();loadSuggestions();loadChangelog();loadScheduled();loadFeatures();
}

function renderDetail(){if(!S||view==='home')return;
  const sig=[view,filter,q,isAdmin,authToken?1:0,JSON.stringify(view==='users'?[S.users,S.banned_users,S.admins]:LOG)].join('|');
  if(sig===sigDetail)return;sigDetail=sig;
  $('d-title').innerText=TITLES[view]||'';
  $('chips').innerHTML=view==='requests'?REQ_FILTERS.map(f=>'<button class="chip '+(filter===f[0]?'on':'')+'" onclick="setFilter(\''+f[0]+'\')">'+f[1]+'</button>').join(''):'';
  const fresh=seen.size===0;let items,html='',keys=[];
  if(view==='users'){items=Object.keys(S.users||{}).map(uid=>Object.assign({uid},S.users[uid])).filter(u=>!q||(String(u.name)+' '+String(u.username)+' '+u.uid).toLowerCase().includes(q));
    items.forEach((u,i)=>{const banned=(S.banned_users||[]).includes(u.uid);const mod=(S.admins||{})[u.uid];const key='u'+u.uid;keys.push(key);
      html+='<div class="row'+(seen.has(key)?'':' in')+'">'+avatar(u.name,u.uid)+'<div class="meta"><div class="line"><b>'+esc(u.name)+'</b><span class="un">'+(u.username?'@'+esc(u.username):'')+'</span>'+(mod?'<span class="tag">🛡️</span>':'')+'</div><div class="foot"><span class="pill">'+esc(u.points||0)+'💰</span><span class="pill c">'+esc(u.requests)+'طلب</span><span>'+esc(u.uid)+'</span></div><div class="foot"><button class="btn sm" onclick="openUserDetail(\''+esc(u.uid)+'\')">👤</button><button class="btn sm" onclick="openPoints(\''+esc(u.uid)+'\')">💰</button><button class="btn blue sm" onclick="openPerms(\''+esc(u.uid)+'\')">🛡️</button>'+(banned?'<button class="btn green sm" onclick="unbanUser(\''+esc(u.uid)+'\')">✅</button>':'<button class="btn red sm" onclick="banUser(\''+esc(u.uid)+'\')">🚫</button>')+'</div></div></div>';});
    SHOWN=[];}
  else{items=LOG.filter(e=>(filter==='all'||e.kind===filter)&&(!q||(String(e.name)+' '+String(e.username)+' '+e.uid+' '+e.text).toLowerCase().includes(q)));
    SHOWN=items.map(e=>e.text);
    items.forEach((e,i)=>{const k=KIND[e.kind]||['•',e.kind];const key=e.t+'|'+e.uid+'|'+e.text;keys.push(key);
      html+='<div class="row'+(seen.has(key)?'':' in')+'">'+avatar(e.name,e.uid)+'<div class="meta"><div class="line"><b>'+esc(e.name)+'</b>'+(e.username?'<span class="un">@'+esc(e.username)+'</span>':'')+'<span class="tag">'+k[0]+' '+k[1]+'</span></div><div class="txt">'+esc(e.text)+'</div><div class="foot"><span>🕒 '+ago(e.t)+'</span><span>'+esc(e.uid)+'</span><span class="sp"></span><button class="btn sm" onclick="copyTxt('+i+')">📋</button></div></div></div>';});}
  keys.forEach(k=>seen.add(k));
  $('d-count').innerText=items.length+' عنصر';renderExtra(items);
  $('d-list').innerHTML=html||'<div class="glass"><div class="empty"><span class="ei">🫧</span>لا توجد عناصر.</div></div>';}

window.onload=loop;
</script>
</body>
</html>
"""

# ============ مسارات الـ Flask (API) ============

@app.route('/')
def dashboard():
    return Response(HTML_TEMPLATE.replace("__START__", esc(bot_state["stats"]["start_time"])), mimetype="text/html")

@app.route('/api/login', methods=['POST'])
def api_login():
    ok, _ = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    token = uuid.uuid4().hex
    login_tokens[token] = time.time()
    for t in [t for t, c in list(login_tokens.items()) if time.time() - c > 86400]:
        login_tokens.pop(t, None)
    return jsonify({"status": "success", "token": token})

@app.route('/api/avatar/<uid>')
def api_avatar(uid):
    t = request.args.get('t', '')
    created = login_tokens.get(t)
    if not created or time.time() - created > 86400: return '', 403
    if not uid.isdigit(): return '', 404
    url = fetch_photo_url(uid)
    if not url: return '', 404
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return Response(r.content, mimetype='image/jpeg', headers={'Cache-Control': 'public, max-age=1800'})
    except Exception as e:
        print("avatar:", e)
    return '', 404

@app.route('/api/stats', methods=['POST'])
def api_stats():
    ok, _ = check_admin()
    with lock:
        data = {"stats": bot_state["stats"], "users_count": len(bot_state["users"]), "bot_active": bot_state["bot_active"],
                "users": {}, "banned_users": [], "complaints": {}, "admins": {}, "broadcast": {}}
        if ok:
            pub = {k: {"name": v.get("name"), "username": v.get("username", ""), "requests": v.get("requests", 0),
                       "points": v.get("points", 0), "loc": bool(v.get("loc"))} for k, v in bot_state["users"].items()}
            st = {k: setting(k) for k in POINTS_DEFAULTS}
            st.update({k: bot_state["settings"].get(k) for k in ("ban_threshold","ban_window_min","anti_spam_per_min",
                                                                  "dynamic_pricing","min_song_cost","max_song_cost")})
            sget = bot_state.get("settings", {})
            st["features"] = {k: feature_on(k) for k in FEATURE_DEFAULTS}
            st["vision_cost"] = cfg_int("vision_cost", 2)
            st["account_cost"] = cfg_int("account_cost", 5)
            st["vision_models"] = sget.get("vision_models") or VISION_MODELS_DEFAULT
            st["text_models"] = sget.get("text_models") or TEXT_MODELS_DEFAULT
            data.update(users=pub, banned_users=bot_state["banned_users"], complaints=bot_state["complaints"],
                        admins=bot_state["admins"], broadcast=dict(bc_state), settings=st,
                        ytdlp=ytdlp_info(), cookies=cookies_info())
        return jsonify(data)

@app.route('/api/user_detail', methods=['POST'])
def api_user_detail():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    uid = str(d.get("uid", ""))
    with lock:
        u = bot_state["users"].get(uid)
        if not u: return jsonify({"status": "error", "error": "المستخدم غير موجود"}), 404
        recent = [e for e in bot_state.get("log", []) if e.get("uid") == uid][-40:][::-1]
        ptrans = [t for t in bot_state.get("point_log", []) if t.get("uid") == uid][-40:][::-1]
        listen = [e for e in bot_state.get("log", []) if e.get("uid") == uid and e.get("kind") == "listen"][-40:][::-1]
        rem_count = len([r for r in bot_state.get("reminders", []) if r["uid"] == uid])
        info = {"uid": uid, "name": u.get("name", ""), "username": u.get("username", ""),
                "points": u.get("points", 0), "requests": u.get("requests", 0),
                "join_date": u.get("join_date", "غير معروف"), "last_seen": u.get("last_seen", "غير معروف"),
                "last_bonus": u.get("last_bonus", ""), "loc": u.get("loc", None), "adhan": u.get("adhan", False),
                "method": u.get("method", "3"), "tz": u.get("tz", ""),
                "banned": uid in bot_state["banned_users"], "admin_perms": bot_state["admins"].get(uid, []),
                "reminders_count": rem_count}
    return jsonify({"info": info, "recent": recent, "ptrans": ptrans, "listen": listen})

@app.route('/api/set_role', methods=['POST'])
def api_set_role():
    ok, d = check_admin()
    uid = str(d.get('uid', ''))
    if not ok or not uid.isdigit(): return jsonify({"status": "error"}), 403
    perms = [p for p in (d.get('perms') or []) if p in PERMS]
    with lock:
        old = bot_state["admins"].get(uid)
        if perms: bot_state["admins"][uid] = perms
        else: bot_state["admins"].pop(uid, None)
    save_db()
    audit("panel", "set_role", target=uid, details=",".join(perms) or "removed")
    if perms and set(perms) != set(old or []):
        send_message(uid, "🛡️ <b>تم تعيينك مشرفاً!</b>\n\nصلاحياتك: " + "، ".join(PERMS[p] for p in perms)
                     + ("\n\n🤖 لرفع بوت أرسل: /رفع_بوت" if "hosting" in perms else ""))
    elif not perms and old:
        send_message(uid, "ℹ️ تم إلغاء صلاحيات الإشراف.")
    return jsonify({"status": "success"})

@app.route('/api/points', methods=['POST'])
def api_points():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    uid = str(d.get('uid', ''))
    mode = d.get('mode', 'add')
    try: amount = int(d.get('amount'))
    except Exception: return jsonify({"status": "error", "error": "رقم غير صالح"}), 400
    amount = max(-100000, min(100000, amount))
    note = str(d.get('note', ''))[:100]
    if mode not in ("add", "set"): return jsonify({"status": "error"}), 400
    if uid in bot_state["users"]: targets = [uid]
    else: return jsonify({"status": "error", "error": "مستخدم غير موجود"}), 404
    changes = []
    for t in targets:
        old, new = apply_points(t, mode, amount, by="admin-panel", note=note or "من اللوحة")
        changes.append((t, old, new))
    save_db()
    audit("panel", "points", target=uid, details=f"{mode} {amount}: {changes[0][1]}→{changes[0][2]}")
    if d.get('notify', True): bg(notify_points, changes, note)
    return jsonify({"status": "success", "count": len(changes)})

@app.route('/api/settings', methods=['POST'])
def api_settings():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    st = bot_state.setdefault("settings", {})
    for k in POINTS_DEFAULTS:
        if k in d:
            try: st[k] = max(0, min(10000, int(d[k])))
            except Exception: pass
    save_db()
    audit("panel", "settings")
    return jsonify({"status": "success"})

@app.route('/api/spam_settings', methods=['POST'])
def api_spam_settings():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    st = bot_state.setdefault("settings", {})
    for k in ("ban_threshold", "ban_window_min", "anti_spam_per_min", "min_song_cost", "max_song_cost"):
        if k in d:
            try: st[k] = max(1, min(1000, int(d[k])))
            except Exception: pass
    if "dynamic_pricing" in d: st["dynamic_pricing"] = bool(d["dynamic_pricing"])
    save_db()
    audit("panel", "spam_settings")
    return jsonify({"status": "success"})

@app.route('/api/broadcast', methods=['POST'])
def api_broadcast():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    msg = str(d.get('message', '')).strip()
    if not msg: return jsonify({"status": "error", "error": "فارغة"}), 400
    if not start_broadcast(msg): return jsonify({"status": "error", "error": "جارية"}), 409
    audit("panel", "broadcast", details=msg[:100])
    return jsonify({"status": "success"})

@app.route('/api/schedule_broadcast', methods=['POST'])
def api_schedule_broadcast():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    text = str(d.get('text', '')).strip(); due_str = str(d.get('due', '')).strip()
    if not text or not due_str: return jsonify({"status": "error", "error": "مطلوب"}), 400
    try:
        dt = datetime.strptime(due_str, "%Y-%m-%d %H:%M"); due_ts = dt.timestamp()
    except Exception: return jsonify({"status": "error", "error": "صيغة: YYYY-MM-DD HH:MM"}), 400
    if due_ts < time.time() + 30: return jsonify({"status": "error", "error": "مستقبلي فقط"}), 400
    schedule_broadcast(text, due_ts, "panel")
    audit("panel", "schedule_bc", details=f"{due_str}: {text[:60]}")
    return jsonify({"status": "success"})

@app.route('/api/scheduled_list', methods=['POST'])
def api_scheduled_list():
    ok, _ = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    with lock:
        items = [s for s in bot_state.get("scheduled_broadcasts", []) if not s.get("sent")]
    return jsonify({"items": items})

@app.route('/api/delete_scheduled', methods=['POST'])
def api_delete_scheduled():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    with lock:
        bot_state["scheduled_broadcasts"] = [s for s in bot_state.get("scheduled_broadcasts", []) if s.get("id") != str(d.get("id"))]
    save_db(); return jsonify({"status": "success"})

@app.route('/api/audit_log', methods=['POST'])
def api_audit_log():
    ok, _ = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    with lock: return jsonify({"items": bot_state.get("admin_log", [])[-200:][::-1]})

@app.route('/api/suggestions', methods=['POST'])
def api_suggestions():
    ok, _ = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    with lock: return jsonify({"items": bot_state.get("suggestions", {})})

@app.route('/api/delete_suggestion', methods=['POST'])
def api_delete_suggestion():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    bot_state.get("suggestions", {}).pop(str(d.get("uid")), None)
    save_db(); return jsonify({"status": "success"})

@app.route('/api/changelog', methods=['POST'])
def api_changelog():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    if d.get('version'):
        items = [x.strip() for x in str(d.get('items', '')).split('\n') if x.strip()]
        with lock:
            bot_state.setdefault("changelog", []).insert(0, {"version": str(d['version'])[:20], "items": items[:20],
                                                              "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
            del bot_state["changelog"][30:]
        save_db()
        if d.get('announce'):
            txt = f"🎉 <b>تحديث جديد — v{d['version']}</b>\n\n" + "\n".join(f"✨ {esc(i)}" for i in items)
            bg(do_broadcast, txt)
        audit("panel", "changelog", details=d['version'])
        return jsonify({"status": "success"})
    with lock: return jsonify({"items": bot_state.get("changelog", [])})

@app.route('/api/features', methods=['POST'])
def api_features():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    st = bot_state.setdefault("settings", {})
    feats = st.setdefault("features", {})
    for k, v in (d.get("features") or {}).items():
        if k in FEATURE_DEFAULTS: feats[k] = bool(v)
    try: st["vision_cost"] = max(0, min(1000, int(d.get("vision_cost", st.get("vision_cost", 2)))))
    except Exception: pass
    try: st["account_cost"] = max(0, min(1000, int(d.get("account_cost", st.get("account_cost", 5)))))
    except Exception: pass
    for key in ("vision_models", "text_models"):
        if key in d:
            clean = re.sub(r'[^A-Za-z0-9_./:\-, ]', '', str(d[key]))[:300].strip()
            if clean: st[key] = clean
    save_db()
    audit("panel", "features")
    return jsonify({"status": "success"})

@app.route('/api/ytdlp_update', methods=['POST'])
def api_ytdlp_update():
    ok, _ = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    if ytdlp_status["running"]: return jsonify({"status": "error", "error": "التحديث جارٍ"}), 409
    bg(do_update_ytdlp)
    audit("panel", "ytdlp_update")
    return jsonify({"status": "success"})

@app.route('/api/cookies', methods=['POST'])
def api_cookies():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    text = str(d.get("cookies", ""))
    if len(text) > 400000 or "\t" not in text:
        return jsonify({"status": "error", "error": "الصيغة غير صالحة (Netscape cookies.txt)"}), 400
    with open(COOKIES_FILE, "w", encoding="utf-8") as f: f.write(text if text.endswith("\n") else text + "\n")
    try: os.chmod(COOKIES_FILE, 0o600)
    except Exception: pass
    YDL_BASE['cookiefile'] = COOKIES_FILE
    audit("panel", "cookies_saved")
    return jsonify({"status": "success"})

@app.route('/api/cookies_clear', methods=['POST'])
def api_cookies_clear():
    ok, _ = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    try: os.remove(COOKIES_FILE)
    except FileNotFoundError: pass
    YDL_BASE.pop('cookiefile', None)
    audit("panel", "cookies_cleared")
    return jsonify({"status": "success"})

@app.route('/api/log', methods=['POST'])
def api_log():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    kinds = LOG_GROUPS.get(d.get('view'), set())
    with lock:
        items = [e for e in bot_state.get("log", []) if e.get("kind") in kinds]
    return jsonify({"items": items[::-1][:300]})

@app.route('/api/toggle_bot', methods=['POST'])
def api_toggle_bot():
    ok, _ = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    bot_state["bot_active"] = not bot_state["bot_active"]; save_db()
    audit("panel", "toggle_bot", details=str(bot_state["bot_active"]))
    return jsonify({"status": "success"})

@app.route('/api/ban', methods=['POST'])
def api_ban_user():
    ok, d = check_admin()
    uid = str(d.get('uid', ''))
    if not ok or not uid.isdigit(): return jsonify({"status": "error"}), 403
    if uid in bot_state["admins"]: return jsonify({"status": "error", "error": "لا يمكن حظر مشرف"}), 400
    if uid not in bot_state["banned_users"]: bot_state["banned_users"].append(uid)
    save_db(); audit("panel", "ban", target=uid)
    return jsonify({"status": "success"})

@app.route('/api/unban', methods=['POST'])
def api_unban_user():
    ok, d = check_admin()
    uid = str(d.get('uid', ''))
    if not ok or not uid.isdigit(): return jsonify({"status": "error"}), 403
    if uid in bot_state["banned_users"]: bot_state["banned_users"].remove(uid)
    if uid in bot_state["appeal_sent"]: bot_state["appeal_sent"].remove(uid)
    save_db(); audit("panel", "unban", target=uid)
    return jsonify({"status": "success"})

@app.route('/api/delete_complaint', methods=['POST'])
def api_delete_complaint():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    bot_state["complaints"].pop(str(d.get('uid')), None); save_db()
    return jsonify({"status": "success"})

@app.route('/api/reply_complaint', methods=['POST'])
def api_reply_complaint():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    uid = str(d.get('uid')); msg = esc(str(d.get('message', ''))[:1000])
    send_message(uid, f"📩 <b>رد الإدارة على شكوتك:</b>\n\n{msg}\n\n<i>شكراً لصبرك.</i>")
    bot_state["complaints"].pop(uid, None); save_db()
    audit("panel", "reply_complaint", target=uid)
    return jsonify({"status": "success"})

acct_jobs = {}

# دالة مساعدة تمت إضافتها لتفادي خطأ لوحة التحكم عند وضع رابط
def parse_account_arg(text):
    t = text.lower()
    hosts = [("tiktok.com", "tiktok"), ("instagram.com", "instagram"), ("twitter.com", "x"), ("x.com", "x"),
             ("youtube.com", "youtube"), ("t.me", "telegram"), ("facebook.com", "facebook"), ("fb.com", "facebook")]
    for host, plat in hosts:
        if host in t:
            p = urlparse(text)
            path = p.path.strip("/")
            if path.startswith("@"):
                return plat, path[1:].split("/")[0]
            return plat, path.split("/")[0]
    return None

@app.route('/api/account', methods=['POST'])
def api_account():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error", "error": "غير مصرح"}), 403
    raw = str(d.get('username', '')).strip()
    plat = str(d.get('platform', '')).strip().lower()
    if raw.lower().startswith("http"):
        parsed = parse_account_arg(raw)
        if not parsed or not parsed[0]: return jsonify({"status": "error", "error": "رابط غير صالح"}), 400
        plat, user = parsed[0], parsed[1]
    else:
        user = raw.lstrip("@")
        if (plat not in PLATFORMS and plat != "all") or not USER_RE.fullmatch(user):
            return jsonify({"status": "error", "error": "اسم الحساب أو المنصة غير صالحة"}), 400
    deep = bool(d.get('deep')) and plat in ACCOUNT_ACTORS
    now = time.time()
    for k in [k for k, v in list(acct_jobs.items()) if now - v["t"] > 900]: acct_jobs.pop(k, None)
    job = uuid.uuid4().hex[:10]
    acct_jobs[job] = {"t": now, "state": "running"}
    def work():
        try:
            res = lookup_account(plat, user, deep=deep)
            acct_jobs[job].update(state="done", result={"profiles": [prof_public(p) for p in res["profiles"]], "web": res["web"],
                                                         "notes": [[PLATFORM_NAMES.get(a, a), b] for a, b in res["notes"]]})
        except Exception as e:
            acct_jobs[job].update(state="error", error=str(e)[:200])
        audit("panel", "account_lookup", target=f"{plat}:{user}")
    bg(work)
    return jsonify({"status": "success", "job": job})

@app.route('/api/account_result', methods=['POST'])
def api_account_result():
    ok, d = check_admin()
    if not ok: return jsonify({"status": "error"}), 403
    j = acct_jobs.get(str(d.get('job', '')))
    if not j: return jsonify({"state": "error", "error": "انتهت صلاحية الطلب"})
    return jsonify({"state": j["state"], "result": j.get("result"), "error": j.get("error", "")})

def get_port():
    for k in ("PORT", "SERVER_PORT", "APP_PORT"):
        v = os.environ.get(k, "")
        if v.isdigit(): return int(v)
    return 11960

def run_dashboard():
    app.run(host='0.0.0.0', port=get_port(), debug=False, use_reloader=False, threaded=True)

def fetch_photo_url(uid, force=False):
    uid = str(uid)
    now = time.time()
    c = photo_cache.get(uid)
    if c and not force and c[1] > now: return c[0]
    try:
        r = TG_SESSION.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUserProfilePhotos",
                         params={"user_id": uid, "limit": 1}, timeout=8)
        j = r.json()
        if not j.get("ok"):
            photo_cache[uid] = (None, now + 300); return None
        photos = j.get("result", {}).get("photos", [])
        if not photos:
            photo_cache[uid] = (None, now + 3600); return None
        sizes = photos[0]
        file_id = sizes[min(1, len(sizes) - 1)]["file_id"]
        r2 = TG_SESSION.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile", params={"file_id": file_id}, timeout=8)
        j2 = r2.json()
        if not j2.get("ok"):
            photo_cache[uid] = (None, now + 300); return None
        path = j2["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{path}"
        photo_cache[uid] = (url, now + 1800); return url
    except Exception as e:
        print("fetch_photo_url:", e); photo_cache[uid] = (None, now + 120); return None

def register_user(chat_id, user_data):
    uid = str(chat_id)
    is_new = False; bonus_given = False; old_points = 0
    start_pts = setting("start_points"); daily_pts = setting("daily_bonus")
    with lock:
        if uid not in bot_state["users"]:
            bot_state["users"][uid] = {"name": user_data.get("first_name", "مستخدم"),
                                       "username": user_data.get("username", ""),
                                       "requests": 0, "points": 0, "last_bonus": ""}
            is_new = True
        u = bot_state["users"][uid]
        old_points = int(u.get("points", 0))
        today = date.today().isoformat() # هنا كان الخطأ وتم إصلاحه
        if u.get("last_bonus") != today:
            u["points"] = old_points + daily_pts; u["last_bonus"] = today; bonus_given = True
        if is_new: u["points"] = int(u.get("points", 0)) + start_pts
        u.setdefault("join_date", date.today().isoformat()) # وهنا أيضاً
        u["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        u["requests"] += 1
        bot_state["stats"]["total_requests"] += 1
        new_points = int(u["points"])
    save_db()
    if is_new:
        send_message(chat_id, welcome_bonus_msg(new_points, start_pts, daily_pts))
        try: log_points(uid, new_points, 0, new_points, by="welcome", note="ترحيب")
        except Exception: pass
    elif bonus_given:
        send_message(chat_id, daily_bonus_msg(new_points, daily_pts, old_points))
        try: log_points(uid, daily_pts, old_points, new_points, by="daily", note="مكافأة يومية")
        except Exception: pass