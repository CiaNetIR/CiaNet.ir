<div align="center">

# 🤖 CiaNet.ir

### پنل مدیریت سلف‌بات تلگرام + سیستم SaaS کامل

ربات مدیریت چنداکانتی تلگرام + پنل وب + درگاه پرداخت + کیف پول + سیستم همکاری

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab.svg)](https://www.python.org)
[![Telethon](https://img.shields.io/badge/telethon-1.36+-28a8ea.svg)](https://docs.telethon.dev)
[![Version](https://img.shields.io/badge/version-2.12.29%20STABLE-blue.svg)](#-changelog)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-Production%20Ready-brightgreen.svg)](#-final-certification)

</div>

---

## ✨ امکانات

### 🤖 ربات سلف
- **مدیریت چند اکانت** — همزمان چند اکانت تلگرام رو روشن نگه دار
- **تبچی** — ارسال خودکار پیام تکراری در گروه/کانال
- **تایم و بیو** — ساعت زنده در اسم یا بیو (با fallback فونت)
- **آنلاین دائمی** — اکانت همیشه آنلاین
- **تیک خودکار** — پیوی/گروه/کانال خودکار خوانده شود
- **سکوت** — حذف خودکار پیام‌های ورودی پیوی
- **ردیاب** — ذخیره پیام‌های حذف/ادیت‌شده
- **بازی‌های تضمینی** — تاس/دارت/بسکتبال/فوتبال/اسلات
- **قیمت لحظه‌ای** — طلا/تتر/ترون/تون
- **کپی و ذخیره** — کپی محتوای پیام با لینک
- **فونت** — bold/double/sans/mono برای اسم
- **📨 ارسال دسته‌جمعی** — فوروارد به همه‌ی PV یا گروه‌ها با یک دستور

### 🔒 محافظت ورود (Login Guard)
- **منقضی‌سازی خودکار کد ورود** — هر کدی که از تلگرام (777000) بیاد فوراً منقضی می‌شه
- **حذف پیام کد** — پیام کد از چت‌هستوری پاک می‌شه
- **Cooldown ۶۰ ثانیه** — جلوگیری از infinite loop
- **FloodWait هماهنگ‌سازی** — coordination با سایر features
- **Persistence** — حالت حفظ می‌شه بعد از restart

### 🛡 حفاظت از Ban
- **محدودیت نرخ** — ۲۰۰ پیام/روز، ۱ ثانیه فاصله
- **گرم‌کردن اکانت** — اکانت جدید ۳۰ دقیقه با نرخ کم
- **مدیریت FloodWait** — ۶۰ ثانیه صبر بعد از Flood + هماهنگی بین همه loops
- **تشخیص هشدار تلگرام** — پیام از 777000 → شمارش + نوتیف OWNER
- **تشخیص فارسی + انگلیسی** — phrase-level matching با negation exclusion
- **غیرفعال‌سازی خودکار** — اگه ban شد (permanent)، اکانت disabled می‌شه
- **تفکیک ban دائمی از موقت** — AuthKeyError = موقت، UserDeactivated = دائمی
- **سقف روزانه‌ی broadcast** — حداکثر ۵ ارسال در روز

### 💰 سیستم مالی
- **کیف پول کاربر** — شارژ/کسر/پرداخت با موجودی (atomic + refund safety)
- **درگاه پرداخت** — Zarinpal + Zibal + کارت به کارت + تتر TRC20
- **کد تخفیف** — درصد تخفیف + محدودیت استفاده
- **لایسنس چندبارمصرف** — max_uses قابل تنظیم (۱ تا ۱۰۰۰)
- **ساخت گروهی لایسنس** — تا ۱۰۰ لایسنس همزمان
- **تمدید خودکار** — از کیف پول وقتی اشتراک منقضی شد
- **ربات اختصاصی** — کاربر ربات خودش رو می‌خره + توکن می‌فرسته
- **مدیریت رسید** — اگه کاربر متن به‌جای عکس بفرسته، خطای واضح
- **تأیید پرداخت فارسی** — بعد از پرداخت Zarinpal/Zibal، پیام فارسی در تلگرام
- **صفحه‌ی پرداخت فارسی** — HTML فارسی به‌جای JSON خام در مرورگر

### 👥 سیستم کاربری
- **۴ نقش** — OWNER / ADMIN / RESELLER / USER
- **نمایندگی** — مشتری جمع کن + مدیریت مشتری‌ها
- **همکاری (Affiliate)** — ۱۰٪ کمیسیون خودکار
- **دعوت دوستان** — جایزه اشتراک هدیه بعد از ۳ دعوت
- **Multi-OWNER** — پشتیبانی از OWNER_IDS env var

### 🌐 پنل وب
- **پنل کاربر** — ورود با کد لایسنس (بدون رمز عبور)
  - داشبورد: موجودی + اشتراک + سلف‌بات‌ها
  - کیف پول: موجودی + تراکنش‌ها
  - سفارش‌ها: لیست + پرداخت با کیف پول
  - اکانت‌ها: انتخاب + Live Session
  - چت‌ها: لیست چت‌ها + ارسال پیام
  - تنظیمات: پروکسی + api_id + phone
  - تمدید خودکار: toggle from web panel
- **پنل ادمین** — ورود با username/password
  - داشبورد: MRR + ARPU + churn rate
  - آنالیتیکس: نمودار درآمد + تفکیک اشتراک‌ها
  - کاربران: لیست + جستجو + مدیریت
  - درگاه‌های پرداخت: فعال/غیرفعال + مرچنت
  - خروجی CSV سفارش‌ها

### 🔐 امنیت
- **رمز دو مرحله‌ای (2FA)** — تغییر/حذف/بازیابی/ایمیل
- **دستگاه‌های لاگین‌شده** — لیست + بستن
- **کد لاگین** — دریافت کد ورود اکانت
- **🔒 محافظت ورود** — منقضی‌سازی خودکار کد + حذف پیام
- **۲FA به‌صورت hash** — salted SHA-256 (نه plaintext)
- **اکانت مالک** — 2FA غیرقابل تغییر
- **Session file chmod 0600** — فایل‌های سشن world-readable نیستن
- **Cookie HttpOnly + Secure + SameSite=Lax**
- **html.escape** — همه‌ی صفحات پرداخت XSS-safe
- **config.json chmod 0600** — اطلاعات حساس محافظت‌شده

### 🔄 آپدیت خودکار
- **بررسی آپدیت** — هر ۶ ساعت
- **اعمال آپدیت** — git fetch + reset --hard + restart
- **ast.parse safety check** — اگه کد جدید SyntaxError داشته باشه، rollback
- **rollback** — بازگشت به نسخه‌ی قبل (با صفحه‌بندی)
- **پاکسازی backup** — نگه‌داشتن فقط ۱۰ backup اخیر
- **تشخیص تغییرات محلی** — اگه فایل‌ها دستی replace شده باشند

### ⏰ اتوماسیون
- **پیام زمان‌بندی‌شده** — ارسال در زمان مشخص
- **پاسخ خودکار** — بر اساس کلمه‌ی کلیدی

---

## 🚀 نصب

### روش اول: نصب سریع (توصیه‌شده)

```bash
sudo bash <(curl -sL https://raw.githubusercontent.com/DLSDT/CiaNet.ir/main/quick_install.sh)
```

یا با env vars:

```bash
sudo API_ID=YOUR_API_ID \
     API_HASH=YOUR_API_HASH \
     ADMIN_BOT_TOKEN=YOUR_BOT_TOKEN \
     ADMIN_ID=YOUR_TELEGRAM_ID \
     bash <(curl -sL https://raw.githubusercontent.com/DLSDT/CiaNet.ir/main/quick_install.sh)
```

### روش دوم: نصب دستی

```bash
git clone https://github.com/DLSDT/CiaNet.ir.git /opt/cianet
cd /opt/cianet

# ساخت venv
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt

# ساخت env file
sudo tee /etc/selfbot.env > /dev/null << 'EOF'
API_ID=YOUR_API_ID
API_HASH=YOUR_API_HASH
ADMIN_BOT_TOKEN=YOUR_BOT_TOKEN
ADMIN_ID=YOUR_TELEGRAM_ID
PANEL_ADMIN_USER=admin
PANEL_ADMIN_PASS_HASH=sha256:YOUR_HASH
PANEL_URL=https://your-domain.com
EOF

# ساخت systemd service
sudo cp install_service.sh /etc/systemd/system/selfbot.service
sudo systemctl daemon-reload
sudo systemctl enable selfbot
sudo systemctl start selfbot
```

### آپدیت

```bash
cd /opt/cianet
sudo git fetch origin && sudo git reset --hard origin/main
sudo rm -rf __pycache__ && sudo systemctl restart selfbot
```

---

## 📋 پیش‌نیازها

- Python 3.10+
- Ubuntu 20.04+ / Debian 11+
- Telegram API credentials (api_id + api_hash from [my.telegram.org](https://my.telegram.org))
- Bot token (از [@BotFather](https://t.me/BotFather))
- دامنه + Cloudflare Tunnel (برای پنل وب از بیرون)

---

## 🏗 معماری

```
┌─────────────────────────────────────────────────┐
│                   Telegram                       │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ ربات ادمین │  │ ربات سلف  │  │ ربات کمکی │       │
│  │ (SaaSBot) │  │ (SelfBot) │  │ (Helper)  │       │
│  └─────┬─────┘  └─────┬─────┘  └──────────┘       │
│        │               │                           │
│        └───────┬───────┘                           │
│                │                                   │
├────────────────┼─────────────────────────────────┤
│           VPS (Server)                            │
│                │                                   │
│  ┌─────────────┴─────────────┐                    │
│  │     main.py (25K lines)    │                    │
│  │  ┌─────┐  ┌─────┐  ┌─────┐│                    │
│  │  │SaaSBot│  │SelfBot│  │AdminBot││              │
│  │  └─────┘  └─────┘  └─────┘│                    │
│  │       web_panel.py         │                    │
│  │  (embed uvicorn port 8000) │                    │
│  │       cianet_updater.py    │                    │
│  └───────────────────────────┘                    │
│                │                                   │
│  ┌──────┐  ┌──────┐  ┌──────┐                     │
│  │saas.db│  │bot.db│  │config│                     │
│  └──────┘  └──────┘  └──────┘                     │
│                │                                   │
├────────────────┼─────────────────────────────────┤
│           Cloudflare Tunnel                       │
│                │                                   │
│         https://your-domain                        │
│                                                   │
│  ┌──────────┐  ┌──────────┐                       │
│  │ /u/*     │  │ /app/*   │                       │
│  │ پنل کاربر│  │ پنل ادمین│                       │
│  └──────────┘  └──────────┘                       │
└─────────────────────────────────────────────────┘
```

---

## 🎛 تنظیمات درگاه پرداخت

در ربات تلگرام: `🎛 پنل مدیریت` → `💳 درگاه‌های پرداخت`

| درگاه | نوع | نیاز |
|-------|-----|------|
| 🟡 Zarinpal | آنلاین | کد مرچنت + PANEL_URL |
| 🟢 Zibal | آنلاین | کد مرچنت + PANEL_URL |
| 💳 کارت به کارت | دستی | تأیید OWNER |
| 💵 تتر TRC20 | خودکار | کیف پول USDT |
| 💰 کیف پول | فوری | شارژ OWNER |

---

## 📊 API Endpoints

### کاربر (با لایسنس)
| Method | Path | توضیح |
|--------|------|------|
| POST | `/api/user/login` | ورود با کد لایسنس |
| GET | `/api/user/me` | اطلاعات کاربر |
| GET | `/api/user/wallet` | موجودی + تراکنش‌ها |
| GET | `/api/user/orders` | لیست سفارش‌ها |
| GET | `/api/user/chats` | لیست چت‌ها |
| POST | `/api/user/chats/{id}/send` | ارسال پیام |
| GET | `/api/user/account/settings` | تنظیمات اکانت |
| POST | `/api/user/auto-renew` | toggle تمدید خودکار |
| GET | `/api/user/auto-renew` | وضعیت تمدید خودکار |

### ادمین (با session)
| Method | Path | توضیح |
|--------|------|------|
| GET | `/api/analytics/overview` | MRR + ARPU + churn |
| GET | `/api/analytics/daily-revenue` | نمودار درآمد |
| GET | `/api/analytics/export` | خروجی CSV |
| GET | `/api/users` | لیست کاربران |
| POST | `/api/users/{id}/wallet/credit` | شارژ کیف پول |

---

## 🔐 محافظت ورود (Login Guard)

قابلیت **🔒 محافظت ورود** در صفحه‌ی «دستگاه‌های لاگین‌شده» فعال می‌شه:

1. مدیر روی «🔓 محافظت ورود: خاموش» کلیک می‌کنه
2. دکمه به «🔒 محافظت ورود: روشن» تبدیل می‌شه
3. از اون به بعد، هر کد ورود از تلگرام (777000) فوراً منقضی می‌شه
4. پیام کد پاک می‌شه — هیچ‌کس نمی‌تونه بخونش
5. حتی اگه هکر شماره داشته باشه، کدی که می‌گیره دیگه کار نمی‌کنه

**نکته**: بعد از restart، حالت محافظت حفظ می‌شه.

---

## 📨 ارسال دسته‌جمعی (Broadcast)

دو دستور در Saved Messages:

| دستور | عملکرد |
|-------|--------|
| `ارسال به پیوی` | فوروارد پیام به همه‌ی PV |
| `ارسال به گروه` | فوروارد پیام به همه‌ی گروه‌ها |

**امنیت:**
- فقط در Saved Messages (نه گروه)
- ۶۰ ثانیه cooldown
- ۵ بار در روز سقف
- ۱-۳ ثانیه تأخیر تصادفی (ضد ban)
- FloodWait handling + coordination
- noforwards check — پیام محافظت‌شده رد می‌شه
- CancelledError handler — restart وسط broadcast = اطلاع کاربر

---

## 🛡 پایداری بلندمدت

| قابلیت | توضیح |
|--------|-------|
| Wizard TTL | پاکسازی خودار wizardهای رها‌شده بعد از ۳۰ دقیقه |
| DB trim | پاکسازی خودکار logs/wallet/orders/payments/subscriptions/broadcasts |
| Backup cleanup | نگه‌داشتن فقط ۱۰ backup اخیر در versions/ |
| Session file | فایل سشن بعد از حذف اکانت پاک می‌شه |
| Broadcast cancel | restart وسط broadcast = اطلاع + partial report |
| Config deepcopy | جلوگیری از cache corruption |
| Atomic migration | schema migration داخل BEGIN IMMEDIATE |
| 61 timeout-safe respond sites | همه‌ی callbackهای امن با ۱۵s timeout |

---

## 📝 Changelog

### v2.12.29 STABLE — 2026-10-06
**تکمیل‌شده‌ترین و پایدارترین نسخه — ۷۹ تست PASS**

#### v2.12.29 (۷ fix)
- _migrate_schema atomic (BEGIN IMMEDIATE)
- Broadcast daily cap (۵/day)
- _stop_and_disable checks ensure_stopped return
- Zero-amount order validation
- WIZ_PHONE state=sending_code (not None)
- Dedicated bot revoked is terminal
- _sweep_expired_dedicated_bots rmtree

#### v2.12.28 (۳ fix)
- Broadcast task cancel on shutdown
- load_config deepcopy (not shallow)
- delete_user_completely atomic (BEGIN IMMEDIATE)

#### v2.12.27 (۵ fix)
- _pay_order refund in except block
- auto_renew refund on create_subscription fail
- login_guard returns bool (lockout prevention)
- _toggle_login_guard persist first
- _guard cooldown after phone check

#### v2.12.25 (۴ fix)
- login_guard event.delete after success
- _pay_order race fix (rowcount)
- Persian negation expanded
- login_guard FloodWait check

#### v2.12.24 (login guard)
- 🔒 محافظت ورود — منقضی‌سازی خودکار کد ورود
- دکمه toggle در صفحه‌ی دستگاه‌های لاگین‌شده
- Persistence + cooldown + FloodWait handling

#### v2.12.23 (۷ long-term fix)
- time_enabled respects persisted state after restart
- Wizard TTL: _ts at ۱۳ creation sites + cleanup
- DB tables trim (۶+ queries)
- versions/ cleanup (keep last ۱۰)
- Broadcast CancelledError handler
- Broadcast noforwards check
- Broadcast cap warning (>۱۰۰۰ dialogs)

#### v2.12.17-22 (broadcast + stability)
- 📨 ارسال دسته‌جمعی (broadcast to PV/groups)
- Anti-ban: _spawn_bg + random delay + FloodWait coordination
- Helper bot broadcast topic
- Broadcast skips _gate_outbound (daily cap exempt)

#### v2.12.16 (UI)
- 🤖 سلف من removed for ALL roles

#### v2.12.12-15 (۲FA hang fix + UX)
- _respond_safe/_edit_safe with ۱۵s/۱۰s timeout
- Pre-warm dialog cache at startup
- ۶۱ timeout-safe callback sites
- ADMIN sec4 header conditional
- RESELLER ➖ کسر hidden

#### v2.12.10-11 (stability)
- ۷۷۰۰۰۰ phrase-level matching + negation exclusion
- PERMANENT_BAN vs SESSION_EXPIRED differentiation
- get_role OWNER_IDS multi-owner support
- auto_renew_enabled column + scheduler hook
- Invoice extension with payment_id guard (۳×۷=۲۱ days)
- review_payment cancels linked order on reject

#### v2.12.8-9 (security + UX)
- Proxy choice removed — direct login only
- Auto-updater ast.parse rollback
- html.escape on payment pages
- Text-in-receipt error message

#### v2.12.1-7 (security foundation)
- api_id/api_hash stripped from config
- Secure cookie (HttpOnly+Secure+SameSite=Lax)
- config.json chmod ۰۶۰۰
- CSV injection protection
- Mix-inline buttons fix
- 2FA page timeout-safe

### v2.11.0-5
- بازگشت به v2.10.5 base (پایدار)
- ربات اختصاصی + نمایندگی + 2FA block

### v2.10.0-5
- ۲۰ باگ فیکس از ۵ ممیزی موازی
- فاز ۱-۵: تخفیف + کیف پول + سفارش + زمان‌بندی + affiliate

### v2.9.0-9.9
- آنالیتیکس + درگاه Zarinpal + auto-renew + زمان‌بندی + auto-reply + affiliate

### v2.8.0-8.13
- کیف پول کاربر + پنل وب + ساخت گروهی لایسنس + auto-updater fixes

### v2.7.0
- ساخت گروهی لایسنس (۱ تا ۱۰۰)

### v2.6.0
- UI حرفه‌ای + ۲۲ باگ فیکس

---

## 🏆 Final Certification

```
╔═══════════════════════════════════════════════════════════════╗
║  FINAL RELEASE CERTIFICATION — CiaNet v2.12.29 STABLE         ║
║                                                               ║
║  ✅ PASSED:  79  |  ❌ FAILED:   0  |  TOTAL:  79            ║
║                                                               ║
║  ✅ Syntax: 3 files, 29,009 lines                             ║
║  ✅ Patches: 73 patches from v2.12.1 to v2.12.29 verified    ║
║  ✅ Cleanup: 6/6 checks passed (no debug code)               ║
║  ✅ Bug fixes: 19 critical/high/medium bugs fixed             ║
║  ✅ Functions: 712  |  Classes: 8  |  Safe sites: 61        ║
║                                                               ║
║  🎉 CERTIFIED FOR PRODUCTION                                  ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## 📄 License

MIT License — استفاده آزاد

---

## 🔗 لینک‌ها

- [گیت‌هاب](https://github.com/DLSDT/CiaNet.ir)
- [Issues](https://github.com/DLSDT/CiaNet.ir/issues)
- [Telegram](https://t.me/CiaNetSelf)
