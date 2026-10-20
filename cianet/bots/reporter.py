# -*- coding: utf-8 -*-
"""🎙 Reporter — بخش «ریپورتر» (v2.17.1 · آماده‌سازی بر پایه‌ی ZIP واقعی «Reporter-V2»)

این ماژول **اسکلتِ آماده** بخش ریپورتر است. طبق درخواست مالک، روشِ دقیقِ کار
بعداً اعلام می‌شود؛ تا آن زمان `REPORTER_ENABLED = False` می‌ماند و دکمه‌ی
«🎙 ریپورتر» صفحه‌ی «به‌زودی» نشان می‌دهد. فعال‌سازیِ آینده فقط با همین
سوییچ و منطقِ همین فایل انجام می‌شود.

════════════════════════════════════════════════════════════════════
 بخش ۱ — آنالیز ZIP «Reporter-V2» (دریافت‌شده ۲۰۲۶-۱۰-۲۰ · سالم و کامل)
════════════════════════════════════════════════════════════════════

فایل‌های ZIP (غیر از venv):
  • bot.py ............ 3,096 خط — کل ربات (همه‌چیز در یک فایل)
  • config.json ....... bot_token / admin_ids / default_delay=2 /
                        max_reports_per_day=100
  • reporter.db ....... SQLite با ۸ جدول (همه خالی — هنوز استفاده نشده)
  • sessions/ ......... خالی (سشن‌های تلثونی اکانت‌های گزارش‌دهنده)

وابستگی‌ها (از venv داخل ZIP):
  • python-telegram-bot 22.8 — لایه‌ی رابط کاربری (Bot API polling)
    ⚠️ این نسخه پارامتر `style` روی InlineKeyboardButton دارد (Bot API جدید)؛
       کدِ bot.py بدون آن کرش می‌کند — یعنی وابستگی به PTB≥22.8 واقعی است.
  • telethon 1.45.0 — هم‌نسخه‌ی خود CiaNet (سازگاری کامل)

معماری Reporter-V2 (دو-لایه):
  لایه‌ی UI:   ربات Bot-API (PTB) — منوها، ویزاردها، ConversationHandler
  لایه‌ی اجرا: اکانت‌های «کاربرِ» تلثونی (استخر اکانت) — گزارش‌ها از این‌ها
               با ReportRequest/ReportPeerRequest ارسال می‌شود.
  گیت دسترسی: فقط ADMIN_IDS (۳ نقطه: start / button_callback / handle_text).
  لاگین اکانت: ویزارد ۵-مرحله‌ای (api_id → api_hash → phone → proxy?
               → کد OTP → 2FA در صورت نیاز)؛ سشن در sessions/{phone}.session.

جدول‌های reporter.db:
  accounts (استخر اکانت: api_id/api_hash/phone/proxy/is_enabled/is_banned/آمار)
  email_accounts (استخر ایمیل Gmail) · email_report_logs · report_logs
  monitoring + monitoring_logs (رصد بنِ اهداف) · stats · settings

قابلیت‌ها (از ۸۰ مسیر callback استخراج شد — ۱۲ گروه):
   1) مدیریت اکانت‌ها (افزودن OTP/2FA، لیست، toggle، پروکسی، import/export)
   2) ارسال پیام به هدف از اکانت‌های استخر (N بار)
   3) گزارش تکی: هدف → دسته → زیردسته → کامنت(اختیاری) → اکانت/همه →
      تعداد (۱-۵۰) → تأیید → اجرا با نوار پیشرفت و تأخیر تصادفی
   4) گزارش چند-کاربر (لیست یوزرنیم‌ها در یک متن)
   5) گزارش استوری
   6) گزارش چند-پیام (چند message_id از یک چت)
   7) بلاکِ هدف از همه‌ی اکانت‌های استخر (BlockRequest)
   8) گزارش انبوه Bulk (لیست اهداف)
   9) مانیتورینگ بن (job تکرارشونده + هشدار به ادمین‌ها)
  10) گزارش ایمیلی (۹ قالب آماده → abuse@telegram.org و… از استخر ایمیل)
  11) چکِ وضعیت اکانت‌ها (بن/فعال)
  12) آمار / لاگ‌ها / تنظیمات / راهنما / پشتیبانی

هسته‌ی اجرایی (خطوط 685-717 و 718-815 و 1062-1108 در bot.py):
  • REPORT_REASONS_MAP: ۸ دسته → InputReportReason* تلثونی
    (نکته‌ی ظریف: دسته‌ی «other» در نقشه نیست → به‌صورت پیش‌فرض با
     دلیل Spam ارسال می‌شود — رفتار عیناً حفظ شده است)
  • LEVEL_1_CATEGORIES (۹ دسته) + LEVEL_2_SUBCATEGORIES +
    REQUIRE_COMMENT = [personal_data, copyright, other]
  • extract_from_link / extract_chat_from_link / extract_usernames_from_text
  • check_target_exists (get_entity + تشخیص نوع + خطاهای FloodWait/بن)
  • send_report_action: ReportRequest (پیام) / ReportPeerRequest (peer/استوری)
  • الگوی تأخیر: sleep(random.uniform(1,3)) بین گزارش‌ها؛ 2s بین اکانت‌ها؛
    ایمیل: uniform(5,10) بین ایمیل‌ها و uniform(10,20) بین اکانت‌ها

باگ‌های پیدا‌شده در ZIP (در پورتِ همین فایل رفع شده‌اند):
  • ZIP-BUG-3 (CRITICAL · خط 1100): در telethon 1.45.0 — یعنی نسخه‌ی
    داخل venv خودِ ZIP — امضای messages.ReportRequest دیگر «reason»
    ندارد و «option: bytes» گرفته است. کدِ اصلی
    `ReportRequest(peer=…, reason=…)` می‌سازد → در هر گزارشِ
    پیام‌محور (گزارش با msg_id / Multi-Message) TypeError پرتاب می‌شود،
    در except مهار می‌شود و نتیجه همیشه success=False است؛ یعنی این
    قابلیت در ربات اصلی «هرگز» روی این telethon کار نکرده است.
    (گزارشِ peer/استوری سالم است چون account.ReportPeerRequest همچنان
    reason می‌گیرد.)
    فیکسِ پورت: لایه‌ی سازگاری _REPORT_USES_OPTION — در اسکیمای جدید،
    گزینه با جریان کشف (ReportResultChooseOption → MessageReportOption)
    به‌دست می‌آید؛ برای telethonهای قدیمی مسیر reason حفظ شده است.
    ⚠️ تأییدِ زنده‌ی جریان option باید هنگام فعال‌سازی (گام تست) انجام شود.
  • ZIP-BUG-1 (HIGH · خط 797): `errors.UserBannedError` در telethon 1.45.0
    وجود ندارد (تأیید با venv داخل خود ZIP). در کد اصلی، ارزیابیِ بندِ
    except برای هر خطای عمومی → AttributeError → چکِ وجودِ هدف عملاً
    کرش است و صفحه‌ی «STARTING REPORT» گیر می‌کند.
    فیکسِ پورت: UserDeactivatedBanError + UserBlockedError (هر دو واقعی).
  • ZIP-BUG-2 (LOW): در add_report_log، ستون‌های attack_start و
    attack_end هر دو «در لحظه‌ی ثبت» با datetime.now() یکسان پر می‌شوند —
    زمان‌های واقعیِ شروع/پایانِ گزارش ثبت نمی‌شوند (duration_seconds
    درست است ولی start/end گزارشی از واقعیت ندارند).
  • نکته: stats جدولِ «total_reports» فقط با UPDATE +1 آپدیت می‌شود و
    سطرِ اولیه INSERT ندارد → اگر جدول stats خالی باشد، شمارنده هرگز
    افزایش نمی‌یابد (در پورت، INSERT OR IGNORE لازم است).
  • نکته‌ی تصمیم برای مالک: دسته‌ی «other» در ZIP به InputReportReasonSpam
    تبدیل می‌شود؛ در telethon 1.45.0 کلاس InputReportReasonOther هم هست —
    هنگام فعال‌سازی می‌توان other را به دلیلِ واقعیِ Other نگاشت کرد.

════════════════════════════════════════════════════════════════════
 بخش ۲ — نقشه‌ی ادغام در CiaNet (کجا و چطور اضافه می‌شود)
════════════════════════════════════════════════════════════════════

«اصل طلایی» (خواسته‌ی صریح مالک): بخش ریپورتر فقط برای کاربرانی است که
روی **اکانت خودشان** لاگین کرده‌اند. نتیجه‌ی معماری:
  ➜ استخرِ اکانتِ Reporter-V2 (جدول accounts + ویزارد افزودن اکانت + پروکسی
    per-اکانت + import/export) **حذف** می‌شود؛ به‌جای آن گزارش‌ها از خودِ
    SelfBot کاربر (کلاینتِ تلثونیِ لاگین‌شده در CiaNet) ارسال می‌شوند.

نگاشتِ جزء-به-جزء:
  ┌──────────────────────────────────┬───────────────────────────────────┐
  │ جزء Reporter-V2                  │ سرنوشت در CiaNet                  │
  ├──────────────────────────────────┼───────────────────────────────────┤
  │ دسته‌ها + Reasons + پارسرها +     │ PORT ۱:۱ → همین فایل (بخش ۳ —    │
  │ check_target_exists +            │ از v2.17.1 آماده و تست‌شده)       │
  │ send_report_action               │                                   │
  ├──────────────────────────────────┼───────────────────────────────────┤
  │ جریان گزارش تکی/چند‌کاربر/       │ ADAPT → ویزارد سلسله‌مراتبی با     │
  │ استوری/چند‌پیام                  │ callbackهای «reporter:» در همین  │
  │                                  │ فایل؛ صفحات UI.screen + UI.nav_row│
  ├──────────────────────────────────┼───────────────────────────────────┤
  │ report_logs / stats              │ ADAPT → جدول‌های جدید در          │
  │                                  │ bot_data.db با مالکیت user_id     │
  │                                  │ (الگوی ensure_block_schema در     │
  │                                  │ core.py → ensure_reporter_schema) │
  ├──────────────────────────────────┼───────────────────────────────────┤
  │ سقف روزانه (max_reports_per_day  │ ADAPT → تنظیم مالک (الگوی         │
  │ =100 در config)                  │ trial_enabled + audit)؛ برای      │
  │                                  │ اکانتِ خودِ کاربر مقدار           │
  │                                  │ محافظه‌کارانه‌تر پیشنهاد می‌شود    │
  ├──────────────────────────────────┼───────────────────────────────────┤
  │ گزارش ایمیلی (استخر ایمیل + ۹    │ DECIDE — نیاز به تصمیم مالک:      │
  │ قالب)                            │ حذف؟ یا از SMTP اختصاصی سرور      │
  │                                  │ با آدرس‌های Abuse بدون استخر؟     │
  ├──────────────────────────────────┼───────────────────────────────────┤
  │ مانیتورینگ بن (job + هشدار       │ DECIDE — پس‌زمینه per-user سنگین  │
  │ ادمین)                           │ است؛ شاید فقط ادمین/کانال هشدار   │
  ├──────────────────────────────────┼───────────────────────────────────┤
  │ افزودن اکانت/پروکسی/import‌      │ EXCLUDE — با اصل طلایی تناقض؛     │
  │                                  │ اکانت کاربر قبلاً در ویزارد لاگین │
  │                                  │ CiaNet ثبت شده است                │
  ├──────────────────────────────────┼───────────────────────────────────┤
  │ ارسال پیام انبوه + بلاک انبوه    │ EXCLUDE — خارج از قلمرو «ریپورتر» │
  │                                  │ و ریسک بن؛ بلاکِ امن کاربر از     │
  │                                  │ v2.17.0 (سطح SaaS) موجود است      │
  └──────────────────────────────────┴───────────────────────────────────┘

خطرات و ملاحظات (باید با مالک نهایی شود):
  • ToS تلگرام: گزارش‌دهیِ مکرر از یک اکانت → ریسک محدودشدنِ همان اکانتِ
    کاربر. سقفِ روزانه + کول‌داون بین گزارش‌ها (الگوی uniform(1,3) خودِ
    Reporter-V2) + شمارنده‌ی روزانه ضروری است.
  • ZIP اطلاعات حساس را plaintext نگه می‌داشت (api_id/api_hash/phone در
    accounts و bot_token در config.json). در CiaNet ذخیره‌ی جدیدی لازم نیست
    (اعتبارنامه‌ها هم‌اکنون در config.json و DATA_DIR/sessions هستند)؛
    ⚠️ bot_token داخل config.json ریپورتر دیگر لازم نیست — مالک باید آن
    را در @BotFather باطل (revoke) کند.
  • sessions/ و reporter.db داخل ZIP خالی‌اند → هیچ داده/مهاجرتی منتقل
    نمی‌شود؛ ادغام صرفاً کد-محور است.

دستورکارِ فعال‌سازی (وقتی مشخصات دقیق از مالک رسید):
  گام ۱ — core.py:
      ensure_reporter_schema() با جدول‌های پیشنهادی:
        reporter_logs (id, user_id, target, target_id, category,
                      subcategory, comment, report_count, success_count,
                      failed_count, status, duration_seconds, created_at)
        + کلیدِ settings برای reporter_daily_cap (پیش‌فرض مثلاً 30)
      و قلابش در init_db (الگوی ensure_block_schema).
  گام ۲ — همین فایل:
      render_reporter_page → منوی اصلی (گزارش تکی/چند‌کاربر/استوری/
      چند‌پیام + تاریخچه + سقف باقی‌مانده)
      handle_reporter_action → شاخه‌های «reporter:» (target → cat → sub →
      comment → count → confirm → اجرا با نوار پیشرفت، عین الگوی ZIP)
      اجرای گزارش: کلاینتِ خودِ SelfBot کاربر (از رجیستری ران‌تایم)،
      NOT استخر اکانت. ثبت در reporter_logs + آپدیت شمارنده‌ی روزانه.
  گام ۳ — saas.py (تنها تغییر لازم در ربات):
      یک شاخه‌ی جدید در callback_h کنارِ user_reporter:
          if data.startswith("reporter:"):
              await reporter_module.handle_reporter_action(event, self, data)
              return
  گام ۴ — پنل مالک: toggle فعال/غیرفعال + سقف روزانه (الگوی trial_enabled
      با ثبت audit برای کلیدهای حساس).
  گام ۵ — تست: scripts/test_reporter_features.py (الگوی test_v217_features.py)
  گام ۶ — REPORTER_ENABLED = True (تنها سوییچِ فعال‌سازی).

نقاط اتصالِ از-قبل-آماده (v2.17.0 — بدون هیچ تغییری کار می‌کنند):
  • دکمه‌ی «🎙 ریپورتر» در منوی اصلی — فقط با گیت has_account
    (SaaSBot._show_menu_for_role در cianet/bots/saas.py)
  • route «user_reporter» در callback_h + گیتِ لاگین
    _user_has_logged_in_account (saas.py — جستجو کنید: user_reporter)
  • دیسپچ به همین ماژول: reporter_module.render_reporter_page(event, self)

قواعد پروژه که پیاده‌سازیِ آینده باید رعایت کند:
  • مالکیتِ scoped: لاگ‌ها و آمار فقط مال خودِ کاربر (الگوی _account_visible).
  • ورودی کاربر فقط از طریق wizard یا callback با گارد نقش/لاگین.
  • صفحه‌ها با UI.screen(...) و دکمه‌های بازگشت با UI.nav_row().
  • هیچ write خارج از DATA_DIR؛ ارسال گزارش فقط با کلاینتِ خودِ کاربر.
"""

import re

REPORTER_ENABLED = False  # فلگِ فعال‌سازی — تا اعلامِ مشخصاتِ دقیق، خاموش

# ════════════════════════════════════════════════════════════════════
# بخش ۳ — بلوک‌های ساختیِ آماده (PORT ۱:۱ از Reporter-V2/bot.py)
# وابستگی: فقط telethon (هم‌نسخه‌ی خود CiaNet). این بلوک‌ها تا
# REPORTER_ENABLED=True شدن صرفاً تعریف‌اند و هیچ رفتاری ندارند.
# ════════════════════════════════════════════════════════════════════

from telethon.tl.functions.messages import ReportRequest
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.types import (
    InputReportReasonSpam,
    InputReportReasonViolence,
    InputReportReasonPornography,
    InputReportReasonChildAbuse,
    InputReportReasonCopyright,
    InputReportReasonIllegalDrugs,
    InputReportReasonPersonalDetails,
    InputReportReasonFake,
)

# ── دسته‌بندی گزارش‌ها (کلیدها = عین Reporter-V2؛ برچسب‌ها فارسی برای UI) ──
REPORTER_CATEGORIES = {
    "spam": "📢 اسپم",
    "violence": "🔫 خشونت",
    "child_abuse": "👶 سوءاستفاده از کودکان",
    "illegal_goods": "💊 کالا/خدمات غیرقانونی",
    "adult_content": "🔞 محتوای بزرگسالان",
    "personal_data": "🆔 افشای داده‌ی شخصی",
    "scam_fraud": "🎭 کلاهبرداری / جعل هویت",
    "copyright": "📜 نقض کپی‌رایت",
    "other": "❓ سایر",
}

# زیردسته‌ها — عین Reporter-V2 (انگلیسی؛ در UI آینده می‌توان ترجمه کرد)
REPORTER_SUBCATEGORIES = {
    "spam": ["Promoting others", "Irrelevant content", "Misleading",
             "Excessive posting", "Unsolicited messages", "Bot spam"],
    "violence": ["Graphic violence", "Threats", "Terrorism",
                 "Animal abuse", "Harassment", "Self-harm"],
    "child_abuse": ["Exploitation", "Abusive content",
                    "Solicitation", "Grooming"],
    "illegal_goods": ["Drugs", "Weapons", "Counterfeit", "Stolen data",
                      "Hacking", "Terrorism materials"],
    "adult_content": ["Non-consensual", "Extreme content", "Underage",
                      "Pornography"],
    "personal_data": ["Doxxing", "Private photos", "Location sharing",
                      "Identity theft"],
    "scam_fraud": ["Impersonation", "Fake channel", "Phishing",
                   "Investment scam", "Fake profile", "Romance scam"],
    "copyright": ["Copyrighted content", "Trademark", "Counterfeit goods"],
    "other": ["Other reason", "Not specified"],
}

# دسته‌هایی که توضیح متنی (comment) برایشان الزامی است — عین ZIP
REPORTER_REQUIRE_COMMENT = ("personal_data", "copyright", "other")

# نقشه‌ی دسته → شیء دلیل تلثونی — عین ZIP (۸ از ۹ دسته؛ «other» عمداً
# غایب است و در send_reporter_action به Spam برمی‌گردد — رفتار حفظ شد)
REPORTER_REASONS_MAP = {
    "spam": InputReportReasonSpam(),
    "violence": InputReportReasonViolence(),
    "adult_content": InputReportReasonPornography(),
    "child_abuse": InputReportReasonChildAbuse(),
    "copyright": InputReportReasonCopyright(),
    "illegal_goods": InputReportReasonIllegalDrugs(),
    "personal_data": InputReportReasonPersonalDetails(),
    "scam_fraud": InputReportReasonFake(),
}

# ── پارسرهای هدف (لینک/یوزرنیم/آیدی) — PORT ۱:۱ با همان رفتار ──

def _extract_from_link(text: str):
    """«t.me/user/123» → ('user', 123) · None, None اگر لینک پیام نبود."""
    patterns = [
        r'https?://t\.me/([^/]+)/(\d+)',
        r'https?://telegram\.me/([^/]+)/(\d+)',
        r't\.me/([^/]+)/(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1), int(match.group(2))
    return None, None


def _extract_chat_from_link(text: str):
    """«t.me/user» → 'user' (joinchat/+ کنار گذاشته می‌شود) · None."""
    patterns = [
        r'https?://t\.me/([^/\s]+)',
        r'https?://telegram\.me/([^/\s]+)',
        r't\.me/([^/\s]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            username = match.group(1)
            if username not in ['joinchat', '+']:
                return username
    return None


def extract_reporter_targets(text: str):
    """متن چندخطی → لیست یونیک اهداف (یوزرنیم/آیدی/لینک) — عین ZIP.

    ترتیب امتحان برای هر خط: لینکِ پیام → لینکِ چت → «@name» → خطِ خام.
    """
    usernames = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        username, _ = _extract_from_link(line)
        if username:
            usernames.append(username)
            continue
        username = _extract_chat_from_link(line)
        if username:
            usernames.append(username)
            continue
        if line.startswith('@'):
            usernames.append(line[1:])
        else:
            usernames.append(line)
    return list(dict.fromkeys(usernames))


# ── چک/اجرای گزارش — PORT با فیکسِ ZIP-BUG-3 (بدون نوشتن DB؛ ثبت لاگ
#    در گام ۲ دستورکار) ──

import inspect as _inspect

# ZIP-BUG-3 FIX: در telethon 1.45.0 امضای messages.ReportRequest از
# «reason: TypeReportReason» به «option: bytes» تغییر کرده است. این فلگ
# در زمانِ import تشخیص می‌دهد کد روی کدام اسکیما است (بدون شبکه).
_REPORT_USES_OPTION = 'option' in _inspect.signature(
    ReportRequest.__init__).parameters

# کلیدواژه‌های تطبیقِ دسته با متنِ گزینه‌هایی که سرور در جریان کشف
# برمی‌گرداند (فارسی + انگلیسی — متن گزینه‌ها به زبانِ اکانت است).
_REPORT_OPTION_KEYWORDS = {
    "spam": ("spam", "اسپم"),
    "violence": ("violence", "violent", "خشونت"),
    "child_abuse": ("child", "کودک"),
    "illegal_goods": ("drug", "illegal", "مخدر", "غیرقانونی"),
    "adult_content": ("pornograph", "adult", "بزرگسال"),
    "personal_data": ("personal", "detail", "شخصی"),
    "scam_fraud": ("fake", "scam", "fraud", "جعل", "کلاهبرداری"),
    "copyright": ("copyright", "کپی"),
    "other": ("other", "سایر", "دیگر"),
}


async def _resolve_message_report_option(client, peer, message_ids, category):
    """جریان کشفِ گزینه‌ی گزارشِ پیام در اسکیمای جدید تلثون (1.45+).

    مطابق پروتکل: فراخوانیِ اول با option خالی → سرور
    ReportResultChooseOption با گزینه‌ها برمی‌گرداند؛ گزینه‌ی متناظر با
    دسته انتخاب و option آن برگردانده می‌شود (در نبودِ تطابق، گزینه‌ی
    اول). اگر نتیجه ساختارِ موردانتظار نبود None برمی‌گردد (فراخواننده
    باید با پیامِ خطا عقبنشینی کند — هرگز کرش نمی‌کنیم).
    """
    from telethon.tl.types import ReportResultChooseOption

    result = await client(ReportRequest(peer=peer, id=list(message_ids),
                                        option=b"", message=""))
    if not isinstance(result, ReportResultChooseOption) or not result.options:
        return None
    keywords = _REPORT_OPTION_KEYWORDS.get(category, ())
    for opt in result.options:
        text_l = (opt.text or "").lower()
        if any(k in text_l for k in keywords):
            return opt.option
    return result.options[0].option


async def check_reporter_target(client, target):
    """وجود و نوع هدف را برمی‌گرداند — عین check_target_exists در ZIP.

    client = کلاینتِ تلثونیِ خودِ کاربر (SelfBot) در ادغامِ آینده.
    """
    from telethon import errors

    try:
        target = target.strip().lstrip('@')
        if target.lstrip('-').isdigit():
            entity = await client.get_entity(int(target))
        else:
            entity = await client.get_entity(target)

        info = {'exists': True, 'id': entity.id, 'type': 'unknown'}
        if hasattr(entity, 'first_name'):
            info['type'] = 'user' if not getattr(entity, 'bot', False) else 'bot'
            info['name'] = f"{entity.first_name} {getattr(entity, 'last_name', '')}".strip()
            info['username'] = (f"@{entity.username}"
                                if getattr(entity, 'username', None) else None)
        elif hasattr(entity, 'title'):
            info['type'] = 'channel' if getattr(entity, 'broadcast', False) else 'group'
            info['title'] = entity.title
            info['username'] = (f"@{entity.username}"
                                if getattr(entity, 'username', None) else None)
        return info
    except errors.FloodWaitError as e:
        return {'exists': False, 'error': f'Flood wait {e.seconds}s'}
    except errors.UserDeactivatedError:
        return {'exists': False, 'error': 'User deactivated'}
    # ZIP-BUG-1 FIX: در telethon 1.45.0 «UserBannedError» وجود ندارد و
    # ارزیابیِ آن داخل except باعث AttributeError می‌شد؛ این دو کلاس واقعی‌اند.
    except (errors.UserDeactivatedBanError, errors.UserBlockedError):
        return {'exists': False, 'error': 'User banned'}
    except errors.PeerFloodError:
        return {'exists': False, 'error': 'You have been limited'}
    except Exception as e:
        error_str = str(e).lower()
        if 'not found' in error_str or 'invalid' in error_str:
            return {'exists': False, 'error': 'Target not found'}
        return {'exists': False, 'error': str(e)[:50]}


async def send_reporter_action(client, peer, message_ids, category,
                               comment="", is_story=False):
    """ارسال یک گزارش تلگرامی — پورتِ send_report_action با فیکسِ ZIP-BUG-3.

    • استوری یا بدون پیام → ReportPeerRequest (در 1.45.0 سالم — reason دارد)
    • با message_ids:
        - تلثون قدیمی (reason) → ReportRequest(reason=…)
        - تلثون 1.45+ (option) → جریان کشفِ گزینه:
            ReportRequest(option=b'') → ReportResultChooseOption → انتخابِ
            گزینه‌ی دسته → ReportRequest(option=…, message=comment)؛
            اگر سرور ReportResultAddComment برگرداند و کامنت خالی باشد،
            نتیجه با needs_comment=True برمی‌گردد تا UI درخواستِ متن کند.
    • دسته‌ی «other» → دلیل Spam (عین رفتار ZIP؛ در نقشه نیست).
    """
    from telethon import errors
    from telethon.tl.types import ReportResultAddComment

    try:
        reason_obj = REPORTER_REASONS_MAP.get(category,
                                              InputReportReasonSpam())
        if is_story:
            # استوری — عین ZIP: گزارش در سطح peer
            await client(ReportPeerRequest(peer=peer, reason=reason_obj,
                                           message=comment))
            return {"success": True}
        if not message_ids or message_ids == [0]:
            # بدون پیام مشخص — عین ZIP: گزارش در سطح peer
            await client(ReportPeerRequest(peer=peer, reason=reason_obj,
                                           message=comment))
            return {"success": True}
        # ── گزارشِ پیام‌محور ──
        if not _REPORT_USES_OPTION:
            # تلثون قدیمی — امضای reason (رفتار عین ZIP)
            await client(ReportRequest(peer=peer, id=message_ids,
                                       reason=reason_obj, message=comment))
            return {"success": True}
        # اسکیمای جدید (telethon 1.45+ · ZIP-BUG-3 FIX)
        option = await _resolve_message_report_option(client, peer,
                                                      message_ids, category)
        if option is None:
            return {"success": False,
                    "error": "گزینه‌ی گزارش از سرور دریافت نشد"}
        result = await client(ReportRequest(peer=peer, id=list(message_ids),
                                            option=option, message=comment))
        if isinstance(result, ReportResultAddComment) and not comment:
            return {"success": False, "needs_comment": True,
                    "error": "این دسته به توضیح متنی نیاز دارد"}
        if isinstance(result, ReportResultAddComment):
            result = await client(ReportRequest(
                peer=peer, id=list(message_ids),
                option=result.option, message=comment))
        return {"success": True, "result": type(result).__name__}
    except errors.FloodWaitError as e:
        return {"success": False, "error": f"⏳ Flood wait {e.seconds}s"}
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}


# ════════════════════════════════════════════════════════════════════
# بخش ۴ — رابط عمومی (رفتار v2.17.0 حفظ شده؛ بدون تغییرِ معنایی)
# ════════════════════════════════════════════════════════════════════


async def render_reporter_page(event, saas_bot) -> None:
    """صفحه‌ی اصلیِ ریپورتر — تنها نقطه‌ی ورودِ بخش ریپورتر به ربات.

    فعلاً صفحه‌ی «به‌زودی» نشان می‌دهد. بعد از فعال‌سازی، این تابع
    منوی اصلیِ گزارش‌دهی را render می‌کند (گزارش تکی/چند‌کاربر/استوری/
    چند‌پیام + تاریخچه + سقف باقی‌مانده — طبق دستورکارِ داک‌استرینگ).
    """
    from cianet.bots.ui import UI  # import محلی — وابستگیِ زمانِ import صفر

    if not REPORTER_ENABLED:
        await event.edit(
            "🎙 **ریپورتر**\n\n"
            "🚧 این بخش در حال ساخت است و به‌زودی فعال می‌شود.\n"
            "⏳ لطفاً منتظر خبرهای بعدی باشید.",
            buttons=[UI.nav_row()],
        )
        return

    # ── منطق اصلی (آینده) — مشخصات از سمت مالک ──
    # الگوی پیشنهادی (طبق نقشه‌ی ادغام):
    #   uid = event.sender_id
    #   کلاینت گزارش‌دهنده = SelfBot خودِ کاربر (اکانتِ لاگین‌شده)،
    #   نه استخر اکانت. دسته‌بندی/پارسرها/ارسال از بخش ۳ همین فایل.
    await event.edit(
        "🎙 **ریپورتر**\n\n(منطق اصلی اینجا render می‌شود.)",
        buttons=[UI.nav_row()],
    )


async def handle_reporter_action(event, saas_bot, action: str) -> None:
    """هندلرِ اکشن‌های داخل بخش ریپورتر (پیشوندِ «reporter:»).

    فعلاً استفاده‌ای ندارد؛ بعد از فعال‌سازی، callback_h یک شاخه برای
    `data.startswith("reporter:")` اضافه می‌کند و action را به همین‌جا
    می‌فرستد (گام ۳ دستورکار در داک‌استرینگ).
    """
    from cianet.bots.ui import UI

    if not REPORTER_ENABLED:
        await event.answer("🎙 ریپورتر هنوز فعال نشده است.", alert=True)
        return
    # ── منطق اکشن‌ها (آینده) — مشخصات از سمت مالک ──
    await event.edit("🎙 ریپورتر — اکشن: " + action,
                     buttons=[UI.nav_row()])
