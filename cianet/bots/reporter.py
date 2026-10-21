# -*- coding: utf-8 -*-
"""🎙 Reporter — بخش «ریپورتر» (v2.18.0 · فعال روی مسیرِ «اصل طلایی»)

گزارشِ کانال/گروه/اکانتِ **جعلی یا کلاهبردار** — با دو دسته‌ی درخواستی مالک:
🎭 کلاهبرداری (Scam) · 🃏 جعلی (Fake)؛ و سه نوع هدف: کانال / گروه / اکانت.
«ریپورت کل متن‌های کانال/گروه» به‌صورتِ پیوست‌کردنِ پیام‌های اخیر (تا ۱۰
مورد) به‌عنوان شواهد به همان گزارش پیاده شده است — دقیقاً همان رفتارِ
کلاینت رسمی تلگرام موقع گزارش.

⛔ مرزِ این بخش (اصل طلایی — خواسته‌ی ثبت‌شده‌ی خود مالک):
  هر گزارش فقط با **اکانتِ خودِ کاربرِ گزارش‌دهنده** ارسال می‌شود؛ یک گزارش
  برای هر هدف در ۲۴ ساعت؛ سقفِ روزانه. استخر اکانت/ارسال خودکار از
  سشن‌های دیگران هرگز به این ماژول اضافه نشود — سشنِ مشتری‌ها فقط برای
  سلف‌بات روی اکانتِ خودشان داده شده و گزارشِ انبوهِ هماهنگ هم بنِ آبشاری
  کل سرویس است (همان دلیلی که استخر ZIP در v2.17.1 حذف شد).

دو لایه‌ی سوییچ:
  • REPORTER_ENABLED (همین فایل، کامپایل-تایم) — کیل‌سوییچ اصلی.
  • settings.reporter_enabled (رانتایم، پنل مالک) — پیش‌فرض روشن.

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

REPORTER_ENABLED = True  # کیل‌سوییچِ کامپایل-تایم — v2.18.0: فعال‌سازی روی مسیرِ اصلِ طلایی

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
    InputReportReasonOther,
    InputReportReasonGeoIrrelevant,
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

# نقشه‌ی دسته → شیء دلیل تلثونی — ۸ دسته‌ی ZIP + دو کلیدِ جریان v2.18.0.
# نکته‌ی telethon 1.45: دلیلِ مستقلِ «Scam» در لایه‌ی عمومی وجود ندارد؛
# دسته‌ی کلاهبرداری با InputReportReasonOther + پیامِ «Scam» ارسال می‌شود
# (مسیر استاندارد انتقالِ این دسته در API عمومی) و در جریانِ گزینه‌محورِ
# پیام‌ها، کلیدواژه‌های scam/fraud با گزینه‌ی سرور تطبیق داده می‌شوند.
REPORTER_REASONS_MAP = {
    "spam": InputReportReasonSpam(),
    "violence": InputReportReasonViolence(),
    "adult_content": InputReportReasonPornography(),
    "child_abuse": InputReportReasonChildAbuse(),
    "copyright": InputReportReasonCopyright(),
    "illegal_goods": InputReportReasonIllegalDrugs(),
    "personal_data": InputReportReasonPersonalDetails(),
    "scam_fraud": InputReportReasonFake(),
    # ── v2.18.0: دو دسته‌ی جریانِ فعال ──
    "fake": InputReportReasonFake(),
    "scam": InputReportReasonOther(),
}

# دو دسته‌ی درخواستی مالک (v2.18.0) — برچسب‌های UI جریانِ فعال
REPORTER_QUICK_CATEGORIES = {
    "scam": "🎭 کلاهبرداری (Scam)",
    "fake": "🃏 جعلی (Fake)",
}

# سه نوع هدف (v2.18.0) — برچسب‌های UI
REPORTER_TARGET_TYPES = {
    "channel": "📡 کانال",
    "group": "👥 گروه",
    "user": "👤 اکانت",
}

# دسته‌ی کلاهبرداری در گزارشِ سطح-peer با این متن ارسال می‌شود (فیلدِ
# message گزارش — دلیلِ Other بدون متن بی‌معناست)
_REPORT_SCAM_COMMENT = "Scam / fraud"

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
            # v2.19.4 (AUDIT-36 M2): 'c' هم blacklist — لینکِ خصوصیِ
            # t.me/c/<id> بالاتر (در extract_reporter_targets) به آیدیِ
            # عددیِ -100... تبدیل می‌شود؛ اگر اینجا جدا نشود، سگمنتِ 'c'
            # به‌عنوانِ یوزرنیمِ ساختگی برگردد و پیامِ خطا مبهم می‌شد
            # («entity corresponding to "c"»).
            if username not in ['joinchat', '+', 'c']:
                return username
    return None


# v2.19.4 (AUDIT-36 M3): هدفِ قابلِ قبول در مسیرِ ویزارد — یوزرنیمِ
# لاتینِ تمیز یا عدد (خالی از متن/جمله). قبل از این، هر متنِ غیرخالی
# «هدف» تلقی می‌شد (شاخه‌ی «خطِ خام»ِ پورتِ ZIP برای ابزارِ batch) و
# پیامِ «هدفی پیدا نشد» کدِ مرده بود؛ متنِ «سلام» به‌عنوانِ یوزرنیم به
# get_entity می‌رفت و اگر اتفاقی حل می‌شد، جریانِ گزارشِ اکانتِ بی‌ربط
# ادامه پیدا می‌کرد.
_TARGET_OK_RE = re.compile(r'[A-Za-z][A-Za-z0-9_]{2,30}|-?\d{1,16}')


def extract_reporter_targets(text: str):
    """متن چندخطی → لیست یونیک اهداف (یوزرنیم/آیدی/لینک).

    ترتیب امتحان برای هر خط: لینکِ خصوصیِ t.me/c/<id> (v2.19.4 → آیدیِ
    عددیِ -100…) → لینکِ پیام → لینکِ چت → «@name» → خطِ خام.
    """
    usernames = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        # v2.19.4 (AUDIT-36 M2 — MEDIUM): لینکِ کانال/گروهِ خصوصی — قبلاً
        # سگمنتِ 'c' به‌عنوانِ یوزرنیم برمی‌گشت و هرگز حل نمی‌شد. حالا به
        # آیدیِ عددیِ مارک‌دارِ چنل تبدیل می‌شود (-100…) که کلاینتِ خودِ
        # کاربر (اگر عضو باشد) می‌تواند resolve کند. لینکِ پیامِ خصوصی هم
        # همین‌طور (msg_id فعلاً استفاده نمی‌شود — chat ملاک است).
        m_private = re.search(r'(?:https?://)?(?:t|telegram)\.me/c/(\d+)', line)
        if m_private:
            usernames.append(f"-100{m_private.group(1)}")
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
    # ── v2.18.0: دو دسته‌ی جریانِ فعال ──
    "fake": ("fake", "جعل"),
    "scam": ("scam", "fraud", "کلاهبرداری"),
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
# بخش ۴ — رابط عمومی (v2.18.0 · فعال‌سازی روی مسیرِ اصلِ طلایی)
# ════════════════════════════════════════════════════════════════════
#
# معماری فعال‌سازی:
#   • هر گزارش فقط با اکانتِ خودِ کاربرِ گزارش‌دهنده ارسال می‌شود (SelfBotِ
#     در حال اجرای او از رجیستری ACCOUNTS) — نه استخر اکانت، نه سشن دیگران.
#   • یک گزارش برای هر هدف در ۲۴ ساعت (reporter_recently_reported) +
#     سقفِ روزانه (reporter_daily_cap؛ پیش‌فرض ۱۰، مالک بین ۱ تا ۳۰).
#   • «ریپورت کل متن‌های کانال/گروه» = پیوستِ تا ۱۰ پیامِ اخیر به همان
#     گزارش به‌عنوان شواهد (فقط id عددی — محتوا ذخیره نمی‌شود).
#   • تاریخچه و آمار فقط scoped به همان کاربر (الگوی _account_visible).
#   • همه‌ی importهای cianet.core داخل توابع هستند تا خلوصِ importِ
#     سطح-ماژول (تست T21) حفظ شود.
#
# نقشه‌ی مسیرها (callbackهایی که saas.callback_h با پیشوند «reporter:»
# به handle_reporter_action می‌فرستد):
#   reporter:home             صفحه‌ی اصلی (لغو هر جریان باز)
#   reporter:new              انتخاب نوع هدف
#   reporter:ttype:<t>        دریافت متنِ هدف (ویزارد WIZ_REPORTER_TARGET)
#   reporter:scope:<s>        دامنه: فقط هدف | همراه با پیام‌های اخیر
#   reporter:cat:<c>          دسته: scam | fake
#   reporter:go               تأیید نهایی → اجرا با اکانت خودِ کاربر
#   reporter:cancel           انصراف از جریان
#   reporter:history          تاریخچه‌ی گزارش‌های خودِ کاربر
#   reporter:owner            پنل مالک (روشن/خاموش + سقف + آمار)
#   reporter:owner:toggle     سوییچ رانتایم مالک
#   reporter:owner:cap        دریافت سقفِ جدید (ویزارد WIZ_REPORTER_CAP)


def _eff_enabled() -> bool:
    """کیل‌سوییچِ کامپایل-تایم AND سوییچِ رانتایمِ مالک."""
    if not REPORTER_ENABLED:
        return False
    from cianet.core import reporter_enabled
    return reporter_enabled()


def _is_owner(saas_bot, uid: int) -> bool:
    from cianet.core import ROLE_OWNER
    try:
        return saas_bot._role(uid) == ROLE_OWNER
    except Exception:
        return False


def _park(saas_bot, uid: int, state: str, data: dict) -> None:
    """ثبتِ وضعیتِ جریان در ویزاردهای SaaSBot (با TTL و پاکسازی خودکار)."""
    saas_bot._start_own_wizard(uid, state, data)


def _flow(saas_bot, uid: int) -> dict:
    """داده‌ی جریانِ بازِ همین کاربر (یا None اگر جریانی باز نیست)."""
    wiz = saas_bot.wizards.get(uid)
    if wiz and wiz.get("state") == "reporter_flow":
        return wiz.get("data") or {}
    return {}


def _back_row(route: str = "reporter:home") -> list:
    """ردیف بازگشتِ داخلیِ ریپورتر + خروجِ همیشه-امن به منوی اصلی.

    v2.19.2 (PROD-BUGFIX): خروجی از «ردیفِ تخت» [b, b] به «لیستِ ردیف‌ها»
    [[b, b]] تغییر کرد. علت: call siteها یا `rows + _back_row()` بودند یا
    `buttons=_back_row()`؛ شکلِ قبلی در حالتِ اول ساختارِ مخلوط
    [[b,b],[b],b,b] می‌ساخت و telethon در build_reply_markup روی دکمه‌ی
    تکی «'KeyboardInlineButton' object is not iterable» می‌گرفت — همان
    خطای production که مالک در v2.19.1 با دیاگنوستیک دید. با شکلِ جدید
    هر دو الگوی call site ساختارِ معتبر می‌سازند.
    """
    from cianet.bots.ui import UI
    from cianet.core import NAV_HOME
    return [[UI.btn(f"{UI.BACK} {UI.L_BACK}", route, style="primary"),
             UI.btn(f"{UI.HOME} {UI.L_HOME}", NAV_HOME, style="primary")]]


def _quota_bar(left: int, cap: int) -> str:
    """نوارِ پیشرفتِ سهمیه — ▰ مصرف‌شده · ▱ باقی‌مانده (۱۰ خانه).

    v2.19.2 (OWNER-REQUEST «جذابش کن»): سهمیه فقط عددِ خشک نباشد؛ یک نوارِ
    کوچکِ بصری کنارش باشد که با هر گزارش پر می‌شود — کاربر در یک نگاه
    می‌بیند چقدر از سهمیه‌ی امروزش مانده.
    """
    cap = max(1, int(cap or 1))
    left = max(0, min(cap, int(left or 0)))
    used = cap - left
    filled = round(used * 10 / cap)
    return "▰" * filled + "▱" * (10 - filled)


async def _render_coming_soon(event) -> None:
    from cianet.bots.ui import UI
    # v2.19.4 (AUDIT-36 L3): این صفحه فقط برای کاربرِ عادی وقتی که مالک
    # ریپورتر را خاموش کرده رندر می‌شود — «در حال ساخت» دروغِ گمراه‌کننده‌ای
    # بود (بخش ساخته شده و فقط غیرفعال است) و برای پشتیبانی/اعتمادِ کاربر
    # بد بود. متنِ صادقانه جایگزین شد.
    await event.edit(
        "🎙 **ریپورتر**\n\n"
        "🔕 این بخش فعلاً توسط مدیریت غیرفعال شده است.\n"
        "⏳ به‌زودی دوباره فعال می‌شود.",
        buttons=[UI.nav_row()],
    )


def _user_client(saas_bot, uid: int):
    """کلاینتِ تلثونیِ «اکانتِ خودِ همین کاربر» که الان در حال اجراست.

    فقط اولین اکانتِ در حال اجرای متعلق به خودِ او — هرگز اکانت دیگری.
    خروجی: (tag, client) یا (None, None).
    """
    from cianet.core import ACCOUNTS, accounts_of_user, is_running
    try:
        cfg = saas_bot.sb.load_config()
    except Exception:
        return None, None
    for tag in accounts_of_user(cfg, uid):
        if is_running(tag):
            entry = ACCOUNTS.get(tag)
            client = getattr(getattr(entry, "bot", None), "client", None) if entry else None
            if client is not None:
                return tag, client
    return None, None


# ─────────────────────────── صفحه‌ها ───────────────────────────


async def render_reporter_page(event, saas_bot) -> None:
    """صفحه‌ی اصلیِ ریپورتر — تنها نقطه‌ی ورود (route: user_reporter).

    v2.19.2 (OWNER-REQUEST «جذابش کن»): بازنویسیِ صفحه — زیرعنوانِ
    دعوت‌کننده، قانون‌ها با نشانگرِ تصویری، نوارِ پیشرفتِ سهمیه و پنجره‌ی
    گزارشِ مجدد به‌صورتِ زنده از تنظیماتِ مالک.
    """
    from cianet.bots.ui import UI
    from cianet.core import (fa_digits, reporter_daily_cap,
                             reporter_dup_hours, reporter_quota_left)

    uid = event.sender_id

    if not _eff_enabled():
        # مالکِ خاموش‌شده باید بتواند دوباره روشن کند → دکمه‌ی تنظیمات
        if _is_owner(saas_bot, uid):
            await event.edit(
                UI.screen("🎙 ریپورتر",
                          body=["🚧 این بخش توسط مالک غیرفعال شده است.",
                                "",
                                "از «⚙️ تنظیمات ریپورتر» می‌توانید آن را دوباره روشن کنید."]),
                buttons=[[UI.go("⚙️ تنظیمات ریپورتر (مالک)", "reporter:owner")],
                         UI.nav_row()],
            )
        else:
            await _render_coming_soon(event)
        return

    # لغوِ هر جریانِ باز (ورودِ دوباره = شروعِ تمیز)
    saas_bot.wizards.pop(uid, None)

    cap = reporter_daily_cap()
    left = reporter_quota_left(uid)
    dup_h = reporter_dup_hours()
    rows = [
        [UI.go("🎯 گزارش جدید", "reporter:new", tone="success")],
        [UI.go("📜 تاریخچه گزارش‌ها", "reporter:history")],
    ]
    if _is_owner(saas_bot, uid):
        rows.insert(2, [UI.go("⚙️ تنظیمات ریپورتر (مالک)", "reporter:owner")])

    body = [
        "🛡 **سپرِ جامعه‌ی تلگرامِ فارسی** — کانال، گروه یا اکانتی که",
        "جعلی است یا کلاهبرداری می‌کند را همان‌طور که خودِ تلگرام می‌خواهد",
        "گزارش کن؛ با رسید، تاریخچه و سهمیه‌ی شفاف.",
        "",
        "**📋 قوانینِ ساده:**",
        f"👤 هر گزارش فقط با **اکانتِ خودِ تو** ارسال می‌شود",
        f"⏳ هر هدف تا **{fa_digits(dup_h)} ساعت** فقط یک‌بار قابل گزارشِ مجدد است",
        f"📅 سقفِ روزانه: **{fa_digits(cap)} گزارش** برای هر کاربر",
        "",
        f"🧮 سهمیه‌ی امروز: **{_quota_bar(left, cap)}**",
        f"      **{fa_digits(left)} از {fa_digits(cap)}** گزارشِ باقی‌مانده",
    ]
    await event.edit(
        UI.screen("🎙 ریپورتر", body=body,
                  subtitle="با اکانتِ خودت، به تلگرام گزارش بده — تمیز و مؤثر"),
        buttons=rows + [UI.nav_row()],
    )


async def _page_ttype(event) -> None:
    from cianet.bots.ui import UI
    body = [
        "چه چیزی را می‌خواهید گزارش کنید؟",
        "",
        "📡 کانال — کانالی که خودش را چیزی جا زده یا کلاهبرداری می‌کند",
        "👥 گروه — گروهِ کلاهبرداری/جعلی",
        "👤 اکانت — کاربری که جعلی است یا کلاهبرداری می‌کند",
    ]
    rows = [
        [UI.go("📡 کانال", "reporter:ttype:channel"),
         UI.go("👥 گروه", "reporter:ttype:group")],
        [UI.go("👤 اکانت", "reporter:ttype:user")],
    ]
    await event.edit(UI.screen("🎯 نوع هدف", body=body), buttons=rows + _back_row())


async def _page_target_prompt(event, ttype: str) -> None:
    from cianet.bots.ui import UI
    label = REPORTER_TARGET_TYPES.get(ttype, ttype)
    body = [
        f"هدفِ ({label}) را بفرستید — یکی از این سه شکل:",
        "",
        "• یوزرنیم: `@name`",
        "• لینک: `https://t.me/name`",
        "• آیدی عددی",
        "",
        "هر بار فقط **یک هدف**.",
    ]
    await event.edit(
        UI.screen("🎯 هدف را بفرستید", body=body),
        buttons=[_cancel_row()],
    )


def _cancel_row():
    from cianet.bots.ui import UI
    return [UI.neutral(UI.L_CANCEL, "reporter:cancel")]


async def _show(event, text, buttons=None) -> None:
    """v2.19.3 (PROD-BUGFIX · IMG_8254): رندرِ مسیر-آگنوستیکِ صفحات.

    باگِ production (۲۰۲۶-۱۰-۲۱): بعد از فرستادنِ هدفِ معتبر (لینک یا
    یوزرنیم) کاربر «❌ خطایی رخ داد. دوباره تلاش کن.» می‌گرفت. ریشه:
    صفحاتِ بعد از هدف با ``event.edit`` رندر می‌شدند؛ در مسیرِ متنِ
    ویزارد، event از نوعِ NewMessage است و ``edit``ِ آن از طریقِ
    ``__getattr__`` به ``Message.edit`` همان پیامِ **کاربر** واگذار
    می‌شود — ربات مؤلفِ آن پیام نیست → ``MessageAuthorRequiredError``
    → پیامِ عمومیِ خطا.

    نکته‌ی ظریف: ``hasattr(event, "edit")`` روی NewMessage واقعی هم
    True است (همان واگذاریِ ``__getattr__``) — پس تشخیصِ مسیر فقط با
    ``isinstance`` روی CallbackQuery درست است. صفحاتی که از مسیرِ متن
    هم رندر می‌شوند (اولین صفحه بعد از هدف: دامنه/دسته) با این هلپر
    رندر می‌شوند — در مسیرِ دکمه همان edit قبلی، در مسیرِ متن پیامِ
    جدیدِ ربات با همان دکمه‌ها.
    """
    from telethon import events as _tg_events
    if isinstance(event, _tg_events.CallbackQuery.Event):
        await event.edit(text, buttons=buttons)
    else:
        await event.respond(text, buttons=buttons)


async def _page_scope(event, d: dict) -> None:
    """دامنه‌ی گزارش برای کانال/گروه: فقط خودِ هدف یا همراه با شواهد."""
    from cianet.bots.ui import UI
    body = [
        f"**هدف:** {_target_label(d)}",
        "",
        "دامنه‌ی گزارش را انتخاب کنید:",
        "",
        "🎯 **فقط خودِ هدف** — گزارش روی خودِ کانال/گروه ثبت می‌شود",
        "📨 **همراه با پیام‌های اخیر** — تا ۱۰ پیامِ آخر به‌عنوان شواهد به"
        " همان گزارش پیوست می‌شود (مثل Report خودِ تلگرام)",
    ]
    rows = [
        [UI.go("🎯 فقط خودِ هدف", "reporter:scope:peer")],
        [UI.go("📨 همراه با پیام‌های اخیر", "reporter:scope:msgs")],
    ]
    await _show(event, UI.screen("📨 دامنه‌ی گزارش", body=body),
                buttons=rows + _back_row())


def _target_label(d: dict) -> str:
    ttype = REPORTER_TARGET_TYPES.get(d.get("ttype", ""), d.get("ttype", "?"))
    name = d.get("info", {}).get("title") or d.get("info", {}).get("name") or d.get("target", "?")
    username = d.get("info", {}).get("username")
    return f"{name} ({ttype}{(' · ' + username) if username else ''})"


async def _page_cat(event, d: dict) -> None:
    from cianet.bots.ui import UI
    body = [
        f"**هدف:** {_target_label(d)}",
        "",
        "این هدف چه مشکلی دارد؟",
        "",
        "🎭 **کلاهبرداری** — گرفتن پول/دارایی با فریب، سرمایه‌گذاریِ قلابی، فیشینگ",
        "🃏 **جعلی** — جا زدنِ خودش به کانال/شخص/برندِ دیگری، هویتِ قلابی",
    ]
    rows = [
        [UI.go("🎭 کلاهبرداری (Scam)", "reporter:cat:scam")],
        [UI.go("🃏 جعلی (Fake)", "reporter:cat:fake")],
    ]
    await _show(event, UI.screen("🎭 نوع تخلف", body=body),
                buttons=rows + _back_row())


async def _page_confirm(event, saas_bot, uid: int, d: dict) -> None:
    from cianet.bots.ui import UI
    from cianet.core import (fa_digits, reporter_dup_hours)
    dup_h = reporter_dup_hours()
    scope_txt = ("همراه با حداکثر ۱۰ پیامِ اخیر (شواهد)"
                 if d.get("scope") == "msgs" else "فقط خودِ هدف")
    cat_txt = REPORTER_QUICK_CATEGORIES.get(d.get("cat", ""), d.get("cat", "?"))
    body = [
        f"🎯 **هدف:** {_target_label(d)}",
        f"🎭 **دسته:** {cat_txt}",
        f"📨 **دامنه:** {scope_txt}",
        "👤 **ارسال با:** اکانتِ خودِ شما — **یک گزارش**",
        "",
        f"⚠️ بعد از ارسال، همین هدف تا **{fa_digits(dup_h)} ساعت** قابل گزارشِ مجدد",
        " توسط شما نیست و از سهمیه‌ی امروزتان یک گزارش کم می‌شود.",
    ]
    rows = [
        [UI.confirm("✅ ارسال گزارش", "reporter:go")],
        _cancel_row(),
    ]
    await event.edit(UI.screen("⚠️ تأیید نهایی", body=body,
                               subtitle="یک گزارش، با اکانتِ خودِ شما",
                               hint="مطمئن هستی؟ دکمه‌ی سبز را بزن"),
                     buttons=rows + _back_row())


async def _page_history(event, saas_bot, uid: int) -> None:
    from cianet.bots.ui import UI
    from cianet.core import jalali_date
    from datetime import datetime
    logs = list_reporter(uid)
    if not logs:
        body = ["هنوز گزارشی ثبت نشده است.",
                "", "اولین گزارش را از «🎯 گزارش جدید» شروع کنید."]
    else:
        body = [f"آخرین {len(logs)} گزارشِ شما:"]
        for r in logs:
            try:
                dt = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
                when = f"{jalali_date(dt)} · {dt.strftime('%H:%M')}"
            except Exception:
                when = r["created_at"]
            cat = REPORTER_QUICK_CATEGORIES.get(r["category"], r["category"])
            ttype = REPORTER_TARGET_TYPES.get(r["target_type"],
                                              r["target_type"] or "?")
            icon = "✅" if r["status"] == "ok" else "❌"
            body.append(f"{icon} `{r['target']}` · {ttype} · {cat} · {when}")
    await event.edit(UI.screen("📜 تاریخچه گزارش‌ها", body=body),
                     buttons=_back_row())


async def _page_owner(event, saas_bot, uid: int) -> None:
    from cianet.bots.ui import UI
    from cianet.core import (REPORTER_CAP_MAX, REPORTER_CAP_MIN,
                             REPORTER_DUP_MAX, REPORTER_DUP_MIN,
                             fa_digits, reporter_daily_cap, reporter_dup_hours,
                             reporter_enabled, reporter_stats)
    on = reporter_enabled()
    cap = reporter_daily_cap()
    dup_h = reporter_dup_hours()
    st = reporter_stats()
    cat_lines = [f"• {REPORTER_QUICK_CATEGORIES.get(k, k)}: {v}"
                 for k, v in sorted(st["by_category"].items())] or ["• هنوز گزارشی ثبت نشده"]
    body = [
        f"**وضعیت:** {'🟢 روشن' if on else '🔴 خاموش'} (پیش‌فرض: روشن)",
        "",
        "**⚖️ محدودیت‌ها (قابلِ تنظیم):**",
        f"• سقفِ روزانه‌ی هر کاربر: **{fa_digits(cap)}** گزارش "
        f"(بازه‌ی مجاز: {fa_digits(REPORTER_CAP_MIN)} تا {fa_digits(REPORTER_CAP_MAX)})",
        f"• فاصله‌ی گزارشِ مجددِ همان هدف: **{fa_digits(dup_h)} ساعت** "
        f"(بازه‌ی مجاز: {fa_digits(REPORTER_DUP_MIN)} تا {fa_digits(REPORTER_DUP_MAX)})",
        "",
        "**📊 آمار:**",
        f"• امروز: {st['today']} گزارش · مجموع: {st['total']} "
        f"({st['ok']} موفق)",
        f"• کاربرانی که گزارش داده‌اند: {st['users']}",
        "• تفکیک دسته:",
        *cat_lines,
    ]
    rows = [
        [UI.toggle("ریپورتر روشن/خاموش", on, "reporter:owner:toggle")],
        [UI.go(f"± سقفِ روزانه (فعلاً {fa_digits(cap)})", "reporter:owner:cap")],
        [UI.go(f"± فاصله‌ی گزارشِ مجدد (فعلاً {fa_digits(dup_h)} ساعت)", "reporter:owner:dup")],
        [UI.refresh("reporter:owner")],
    ]
    await event.edit(UI.screen("⚙️ تنظیمات ریپورتر", body=body,
                               subtitle="پنل مالک — سوییچ، محدودیت‌ها و آمار"),
                     buttons=rows + _back_row())


def list_reporter(uid: int):
    from cianet.core import list_reporter_logs
    return list_reporter_logs(uid, limit=10)


# ───────────────────── اجرای گزارش ─────────────────────


async def _exec_report(event, saas_bot, uid: int, d: dict) -> None:
    """اجرای یک گزارش — با اکانتِ خودِ کاربر، فقط یک گزارش."""
    from cianet.bots.ui import UI
    from cianet.core import (add_reporter_log, fa_digits, reporter_dup_hours,
                             reporter_quota_left, reporter_recently_reported)

    # گیت‌های لحظه‌ی ارسال (دوباره چک می‌شوند — وضعیت ممکن است عوض شده باشد)
    if not _eff_enabled():
        await event.answer("🎙 ریپورتر توسط مالک غیرفعال شده است.", alert=True)
        return
    if reporter_quota_left(uid) <= 0:
        await event.answer("⛔ سهمیه‌ی گزارشِ امروزِ شما تمام شده است — فردا.",
                           alert=True)
        return
    info = d.get("info", {})
    if info.get("id") is not None and reporter_recently_reported(uid, info.get("id"), target=str(d.get("target") or "")):
        await event.answer(f"⛔ این هدف را در {fa_digits(reporter_dup_hours())} ساعتِ اخیر"
                           " گزارش داده‌اید.", alert=True)
        return

    tag, client = _user_client(saas_bot, uid)
    if client is None:
        await event.edit(
            UI.screen("❌ اکانتِ شما روشن نیست",
                      body=["برای ارسال گزارش، اکانتِ خودِ شما باید در حال اجرا باشد.",
                            "",
                            "از «🔊 مدیریت اکانت‌ها» اکانت‌تان را روشن کنید و دوباره"
                            " به این بخش بیایید."],
                      hint="گزارش فقط با اکانتِ خودِ شما ارسال می‌شود — نه اکانت دیگران."),
            buttons=_back_row(),
        )
        return

    cat = d.get("cat", "")
    scope = d.get("scope", "peer")
    target = d.get("target", "")
    await event.answer()  # بستنِ اسپینر قبل از کارِ شبکه‌ای

    msg_ids = []
    try:
        entity = await client.get_entity(target)
        if scope == "msgs" and info.get("type") in ("channel", "group"):
            # «ریپورت کل متن‌ها»: تا ۱۰ پیامِ اخیر به‌عنوان شواهد — فقط id،
            # محتوا خوانده/ذخیره نمی‌شود (حریم خصوصی + پهنای باند).
            recent = await client.get_messages(entity, limit=10)
            msg_ids = [m.id for m in recent if getattr(m, "id", None)
                       and not getattr(m, "action", None)]
    except Exception as e:
        await _render_receipt(event, d, ok=False,
                              error=f"حل کردنِ هدف ناموفق بود: {str(e)[:60]}",
                              left=reporter_quota_left(uid))
        return

    comment = _REPORT_SCAM_COMMENT if cat == "scam" else ""
    result = await send_reporter_action(client, entity, msg_ids or None, cat,
                                        comment=comment)
    ok = bool(result.get("success"))
    err = result.get("error", "")
    if not ok and result.get("needs_comment"):
        err = "این دسته به توضیح متنی نیاز دارد — دوباره تلاش کنید"
    add_reporter_log(uid, target, info.get("id"), info.get("type", ""),
                     cat, with_messages=bool(msg_ids),
                     status="ok" if ok else f"error")
    saas_bot.wizards.pop(uid, None)
    await _render_receipt(event, d, ok=ok, error=err,
                          left=reporter_quota_left(uid), n_msgs=len(msg_ids))


async def _render_receipt(event, d: dict, ok: bool, left: int,
                          error: str = "", n_msgs: int = 0) -> None:
    from cianet.bots.ui import UI
    from cianet.core import fa_digits, reporter_daily_cap
    cat_txt = REPORTER_QUICK_CATEGORIES.get(d.get("cat", ""), d.get("cat", "?"))
    body = [
        ("🎉 **گزارش با موفقیت ارسال شد!**" if ok
         else "❌ **ارسال ناموفق بود**"),
        "",
        f"🎯 **هدف:** {_target_label(d)}",
        f"🎭 **دسته:** {cat_txt}",
        f"📨 **شواهد:** {n_msgs} پیام" if n_msgs else "📨 **شواهد:** بدون پیام",
    ]
    if ok:
        body += ["", "🫡 کارت درست انجام شد — تلگرام گزارشِ تو را دریافت کرد."]
    if error:
        body += ["", f"**علت خطا:** {error}"]
    body += ["", f"🧮 سهمیه‌ی امروز: **{_quota_bar(left, reporter_daily_cap())}**",
             f"      **{fa_digits(left)} از {fa_digits(reporter_daily_cap())}** باقی‌مانده"]
    rows = [
        [UI.go("🎯 گزارش جدید", "reporter:new", tone="success")],
        [UI.go("📜 تاریخچه", "reporter:history")],
    ]
    await event.edit(UI.screen("🧾 رسید گزارش", body=body,
                               hint="گزارشِ بعدی همین‌جا — چند ثانیه فاصله کافی است"),
                     buttons=rows + _back_row())


# ───────────────────── روترِ اکشن‌ها ─────────────────────


async def handle_reporter_action(event, saas_bot, action: str) -> None:
    """هندلرِ اکشن‌های داخل بخش ریپورتر (پیشوندِ «reporter:»)."""
    from cianet.core import (ROLE_OWNER, WIZ_REPORTER_CAP, WIZ_REPORTER_DUP,
                             WIZ_REPORTER_FLOW, WIZ_REPORTER_TARGET,
                             log_action, reporter_daily_cap,
                             reporter_enabled, set_setting,
                             REPORTER_CAP_MAX, REPORTER_CAP_MIN,
                             REPORTER_CAP_SETTING, REPORTER_ENABLED_SETTING)

    uid = event.sender_id

    # گیتِ لاگین (اول از همه — همان گیتِ route اصلی؛ دفاع‌در‌عمق)
    if not saas_bot._user_has_logged_in_account(uid):
        await event.answer(
            "🎙 ریپورتر فقط برای کاربرانی است که اکانت خودشان "
            "را در ربات لاگین کرده‌اند.", alert=True)
        return

    # ── پنل مالک — قبل از گیتِ فعال‌بودن، تا در حالتِ خاموش هم بتوان
    #    دوباره روشن کرد (وگرنه سوییچ در حالتِ خاموش برای همیشه قفل می‌شد)
    if action.startswith("reporter:owner"):
        if saas_bot._role(uid) != ROLE_OWNER:
            await event.answer("⛔ این بخش فقط برای مالک است.", alert=True)
            return
        if action == "reporter:owner":
            await _page_owner(event, saas_bot, uid)
            return
        if action == "reporter:owner:toggle":
            new_val = "0" if reporter_enabled() else "1"
            set_setting(REPORTER_ENABLED_SETTING, new_val, actor_id=uid)
            log_action(uid, "reporter_toggle", f"enabled={new_val}")
            await _page_owner(event, saas_bot, uid)
            return
        if action == "reporter:owner:cap":
            _park(saas_bot, uid, WIZ_REPORTER_CAP,
                  {"current": reporter_daily_cap()})
            from cianet.bots.ui import UI
            from cianet.core import fa_digits
            await event.edit(
                UI.screen("± سقفِ روزانه",
                          body=[f"سقفِ فعلی: **{fa_digits(reporter_daily_cap())}**",
                                "",
                                f"عددِ جدید را بفرستید (بین {fa_digits(REPORTER_CAP_MIN)} تا {fa_digits(REPORTER_CAP_MAX)})."],
                          hint="سقفِ بالاتر یعنی ریسکِ بیشتر برای اکانتِ خودِ کاربر —"
                               " مقدارِ محافظه‌کارانه توصیه می‌شود."),
                buttons=[_cancel_row()],
            )
            return
        # v2.19.2 (OWNER-REQUEST): پنجره‌ی گزارشِ مجددِ همان هدف هم
        # توسط مالک قابلِ تنظیم است — همان ویزاردِ سقف، با بازه‌ی ۱ تا ۷۲ ساعت.
        if action == "reporter:owner:dup":
            from cianet.core import (REPORTER_DUP_MAX, REPORTER_DUP_MIN,
                                     fa_digits, reporter_dup_hours)
            _park(saas_bot, uid, WIZ_REPORTER_DUP,
                  {"current": reporter_dup_hours()})
            from cianet.bots.ui import UI
            await event.edit(
                UI.screen("± فاصله‌ی گزارشِ مجدد",
                          body=[f"مقدارِ فعلی: **{fa_digits(reporter_dup_hours())} ساعت**",
                                "",
                                f"عددِ جدید را به ساعت بفرستید (بین {fa_digits(REPORTER_DUP_MIN)} تا {fa_digits(REPORTER_DUP_MAX)})."],
                          hint="پنجره‌ی کوچک‌تر یعنی کاربر زودتر می‌تواند همان"
                               " هدف را دوباره گزارش کند — ریسکِ اسپم‌شدنِ"
                               " گزارش به تلگرام بالاتر می‌رود."),
                buttons=[_cancel_row()],
            )
            return
        await event.answer("مسیر نامعتبر است.", alert=True)
        return

    if not _eff_enabled():
        # کیل‌سوییچِ خاموش → همان صفحه‌ی «به‌زودی» + هشدارِ کوتاه
        await _render_coming_soon(event)
        await event.answer("🎙 ریپورتر فعال نیست.", alert=True)
        return

    # ── مسیرهای بدون جریان ──
    if action == "reporter:home":
        saas_bot.wizards.pop(uid, None)
        await render_reporter_page(event, saas_bot)
        return
    if action == "reporter:new":
        saas_bot.wizards.pop(uid, None)
        await _page_ttype(event)
        return
    if action == "reporter:cancel":
        saas_bot.wizards.pop(uid, None)
        await render_reporter_page(event, saas_bot)
        return
    if action == "reporter:history":
        saas_bot.wizards.pop(uid, None)
        await _page_history(event, saas_bot, uid)
        return

    # ── جریانِ گزارشِ جدید ──
    if action.startswith("reporter:ttype:"):
        ttype = action.split(":", 2)[2]
        if ttype not in ("channel", "group", "user"):
            await event.answer("نوعِ هدف نامعتبر است.", alert=True)
            return
        _park(saas_bot, uid, WIZ_REPORTER_TARGET, {"ttype": ttype})
        await _page_target_prompt(event, ttype)
        return

    d = _flow(saas_bot, uid)
    if action.startswith("reporter:scope:"):
        if not d:
            await event.answer("جریان یافت نشد — از «گزارش جدید» شروع کنید.", alert=True)
            return
        d["scope"] = action.split(":", 2)[2]
        await _page_cat(event, d)
        return
    if action.startswith("reporter:cat:"):
        if not d:
            await event.answer("جریان یافت نشد — از «گزارش جدید» شروع کنید.", alert=True)
            return
        d["cat"] = action.split(":", 2)[2]
        if d["cat"] not in ("scam", "fake"):
            await event.answer("دسته نامعتبر است.", alert=True)
            return
        await _page_confirm(event, saas_bot, uid, d)
        return
    if action == "reporter:go":
        if not d or not d.get("cat") or not d.get("target"):
            await event.answer("جریان ناقص است — از «گزارش جدید» شروع کنید.", alert=True)
            return
        await _exec_report(event, saas_bot, uid, d)
        return

    await event.answer("مسیر نامعتبر است.", alert=True)


# ───────────────────── ورودیِ متنی (ویزارد) ─────────────────────


async def handle_reporter_text(event, saas_bot, wiz: dict) -> bool:
    """ورودیِ متنیِ جریانِ ریپورتر — از SaaSBot._handle_text_wizard صدا زده
    می‌شود. True یعنی «این پیام مصرف شد»."""
    from cianet.bots.ui import UI
    from cianet.core import (ROLE_OWNER, WIZ_REPORTER_CAP, WIZ_REPORTER_DUP,
                             WIZ_REPORTER_FLOW, WIZ_REPORTER_TARGET,
                             log_action, reporter_daily_cap,
                             reporter_dup_hours, reporter_quota_left,
                             reporter_recently_reported,
                             set_setting, REPORTER_CAP_MAX, REPORTER_CAP_MIN,
                             REPORTER_CAP_SETTING, REPORTER_DUP_MAX,
                             REPORTER_DUP_MIN, REPORTER_DUP_SETTING)

    state = wiz.get("state")
    uid = event.sender_id
    text = (event.raw_text or "").strip()

    # ── مرحله‌ی دکمه‌ایِ جریان: متن فرستاده شده → راهنمایی ──
    if state == WIZ_REPORTER_FLOW:
        await event.respond(
            "🎙 در این مرحله فقط از دکمه‌ها استفاده کنید."
            " برای لغو، «انصراف» را بزنید.",
            buttons=[_cancel_row()],
        )
        return True

    # ── سقفِ جدیدِ مالک ──
    if state == WIZ_REPORTER_CAP:
        # v2.19.4 (AUDIT-36 M1 — MEDIUM): pop فقط بعد از اعتبارسنجیِ موفق.
        # قبلاً pop در خطِ اول بود → ورودیِ نامعتبر (متن/اعشاری/خالی) پیامِ
        # «عدد بفرست» می‌داد ولی ویزارد مرده بود و عددِ بعدیِ مالک به
        # هیچ‌جا نمی‌رسید (سکوتِ مطلق — بازتولیدشده در شبیه‌سازِ 36-f).
        if saas_bot._role(uid) != ROLE_OWNER:
            saas_bot.wizards.pop(uid, None)
            await event.respond("⛔ این عملیات فقط برای مالک است.")
            return True
        raw = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        try:
            val = int(raw)
        except ValueError:
            await event.respond("❌ لطفاً فقط یک عدد بفرستید.")
            return True  # ویزارد باز می‌ماند تا عددِ درست برسد
        saas_bot.wizards.pop(uid, None)
        val = max(REPORTER_CAP_MIN, min(REPORTER_CAP_MAX, val))
        set_setting(REPORTER_CAP_SETTING, str(val), actor_id=uid)
        log_action(uid, "reporter_cap_changed", f"cap={val}")
        from cianet.core import fa_digits
        await event.respond(
            UI.screen("✅ سقف ثبت شد",
                      body=[f"سقفِ روزانه‌ی هر کاربر: **{fa_digits(val)} گزارش**"]),
            buttons=_back_row(),
        )
        return True

    # ── v2.19.2: پنجره‌ی جدیدِ گزارشِ مجدد از مالک ──
    if state == WIZ_REPORTER_DUP:
        # v2.19.4 (AUDIT-36 M1 — MEDIUM): مثل CAP — pop بعد از validate.
        if saas_bot._role(uid) != ROLE_OWNER:
            saas_bot.wizards.pop(uid, None)
            await event.respond("⛔ این عملیات فقط برای مالک است.")
            return True
        raw = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        try:
            val = int(raw)
        except ValueError:
            await event.respond("❌ لطفاً فقط یک عدد (به ساعت) بفرستید.")
            return True  # ویزارد باز می‌ماند
        saas_bot.wizards.pop(uid, None)
        val = max(REPORTER_DUP_MIN, min(REPORTER_DUP_MAX, val))
        set_setting(REPORTER_DUP_SETTING, str(val), actor_id=uid)
        log_action(uid, "reporter_dup_changed", f"dup_hours={val}")
        from cianet.core import fa_digits
        await event.respond(
            UI.screen("✅ فاصله ثبت شد",
                      body=[f"فاصله‌ی گزارشِ مجددِ هر هدف: **{fa_digits(val)} ساعت**"]),
            buttons=_back_row(),
        )
        return True

    # ── دریافتِ هدف ──
    if state != WIZ_REPORTER_TARGET:
        return False  # مربوط به ما نیست

    data = wiz.get("data") or {}
    ttype = data.get("ttype", "")

    if not _eff_enabled():
        saas_bot.wizards.pop(uid, None)
        await event.respond("🎙 ریپورتر توسط مالک غیرفعال شده است.")
        return True
    if reporter_quota_left(uid) <= 0:
        saas_bot.wizards.pop(uid, None)
        await event.respond(
            UI.screen("⛔ سهمیه‌ی امروز تمام شده",
                      body=["سقفِ گزارشِ امروزِ شما پر شده است — فردا دوباره بیایید.",
                            "", f"سهمیه‌ی باقی‌مانده: **0**"]),
            buttons=_back_row(),
        )
        return True

    targets = extract_reporter_targets(text)
    # v2.19.4 (AUDIT-36 L2): لینکِ دعوت (invite) از داخلش آیدی قابلِ استخراج
    # نیست — پیامِ صریح به‌جای خطای مبهمِ «get_entity روی کلِ URL».
    if re.search(r'(?:t|telegram)\.me/(?:joinchat|\+)', text, re.IGNORECASE):
        await event.respond(
            UI.screen("⛔ لینک دعوت پشتیبانی نمی‌شود",
                      body=["از لینک‌های دعوت (joinchat / +) نمی‌توان هدف ساخت —",
                            "آیدیِ عددیِ چنل/گروه یا یوزرنیمِ عمومیِ هدف را بفرستید.",
                            "اگر عضوِ همان چت هستید، آیدیِ عددی آن را از اطلاعات چت کپی کنید."],
                      hint="مثال: @cynetgap یا -1234567890"),
            buttons=[_cancel_row()],
        )
        return True  # ویزارد باز می‌ماند
    if not targets:
        await event.respond("❌ هدفی در پیام شما پیدا نشد — یوزرنیم/لینک/آیدی بفرستید.")
        return True  # ویزارد باز می‌ماند تا دوباره بفرستد
    if len(targets) > 1:
        await event.respond("⛔ هر بار فقط **یک هدف** — اولین گزارش را برای اولین هدف کامل کنید.")
        return True
    target = targets[0]
    # v2.19.4 (AUDIT-36 M3 — MEDIUM): فقط الگوی مجاز (یوزرنیمِ لاتینِ تمیز
    # یا عدد) — قبلاً هر متنِ غیرخالی هدف تلقی می‌شد و «سلام» به‌عنوانِ
    # یوزرنیم به سرور می‌رفت. ویزارد باز می‌ماند.
    if not _TARGET_OK_RE.fullmatch(target):
        await event.respond("❌ هدفی در پیام شما پیدا نشد — یوزرنیم/لینک/آیدی بفرستید.")
        return True

    tag, client = _user_client(saas_bot, uid)
    if client is None:
        saas_bot.wizards.pop(uid, None)
        await event.respond(
            UI.screen("❌ اکانتِ شما روشن نیست",
                      body=["برای ارسال گزارش، اکانتِ خودِ شما باید در حال اجرا باشد.",
                            "از «🔊 مدیریت اکانت‌ها» اکانت‌تان را روشن کنید و دوباره بیایید."],
                      hint="گزارش فقط با اکانتِ خودِ شما ارسال می‌شود — نه اکانت دیگران."),
            buttons=_back_row(),
        )
        return True

    info = await check_reporter_target(client, target)
    if not info.get("exists"):
        err = info.get("error", "نامشخص")
        await event.respond(
            UI.screen("❌ هدف پیدا نشد",
                      body=[f"**علت:** {err}",
                            "",
                            "یوزرنیم/لینک را دوباره چک کنید و دوباره بفرستید."],
                      hint="اگر هدف خصوصی/غیرعمومی است، فقط آیدی عددی کار می‌کند."),
            buttons=[_cancel_row()],
        )
        return True  # ویزارد باز می‌ماند

    # تطبیقِ نوعِ انتخاب‌شده با نوعِ واقعی (قابل ادامه — با نوعِ واقعی)
    actual = info.get("type", "unknown")
    if ttype and ttype != actual and not (ttype == "user" and actual == "bot"):
        ttype = actual  # نوعِ واقعی ملاک است؛ در صفحه‌ی بعد نمایش داده می‌شود

    if info.get("id") is not None and reporter_recently_reported(uid, info.get("id"), target=target):
        saas_bot.wizards.pop(uid, None)
        dup_h = reporter_dup_hours()
        from cianet.core import fa_digits
        await event.respond(
            UI.screen("⏳ قبلاً گزارش داده‌اید",
                      body=[f"این هدف را در **{fa_digits(dup_h)} ساعتِ اخیر** گزارش کرده‌اید.",
                            "گزارشِ دوباره از یک اکانت روی همان هدف اثری ندارد."],
                      hint=f"گزارشِ بعدی: پس از گذشتِ {fa_digits(dup_h)} ساعت."),
            buttons=_back_row(),
        )
        return True

    # جریان را park کن و به انتخابِ دامنه/دسته برو
    d = {"ttype": ttype, "target": target, "info": info, "scope": "peer"}
    _park(saas_bot, uid, WIZ_REPORTER_FLOW, d)
    if actual in ("channel", "group"):
        await _page_scope(event, d)
    else:
        await _page_cat(event, d)
    return True
