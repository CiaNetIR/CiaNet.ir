<div align="center">

# 🤖 CiaNet.ir

### پنل مدیریت سلف‌بات تلگرام + سیستم SaaS کامل

ربات مدیریت چنداکانتی تلگرام + پنل وب + درگاه پرداخت + کیف پول + سیستم همکاری

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab.svg)](https://www.python.org)
[![Telethon](https://img.shields.io/badge/telethon-1.36+-28a8ea.svg)](https://docs.telethon.dev)
[![Version](https://img.shields.io/badge/version-2.11.5-blue.svg)](#-changelog)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

## ✨ امکانات

### 🤖 ربات سلف
- **مدیریت چند اکانت** — همزمان چند اکانت تلگرام رو روشن نگه دار
- **تبچی** — ارسال خودکار پیام تکراری در گروه/کانال
- **تایم و بیو** — ساعت زنده در اسم یا بیو
- **آنلاین دائمی** — اکانت همیشه آنلاین
- **تیک خودکار** — پیوی/گروه/کانال خودکار خوانده شود
- **سکوت** — حذف خودکار پیام‌های ورودی پیوی
- **ردیاب** — ذخیره پیام‌های حذف/ادیت‌شده
- **بازی‌های تضمینی** — تاس/دارت/بسکتبال/فوتبال/اسلات
- **قیمت لحظه‌ای** — طلا/تتر/ترون/تون
- **کپی و ذخیره** — کپی محتوای پیام با لینک
- **فونت** — bold/double/sans/mono برای اسم

### 🛡 حفاظت از Ban
- **محدودیت نرخ** — ۲۰۰ پیام/روز، ۱ ثانیه فاصله
- **گرم‌کردن اکانت** — اکانت جدید ۳۰ دقیقه با نرخ کم
- **مدیریت FloodWait** — ۶۰ ثانیه صبر بعد از Flood + هماهنگی بین همه loops
- **تشخیص هشدار تلگرام** — پیام از 777000 → شمارش + نوتیف OWNER
- **غیرفعال‌سازی خودکار** — اگه ban شد، اکانت متوقف می‌شه

### 💰 سیستم مالی
- **کیف پول کاربر** — شارژ/کسر/پرداخت با موجودی
- **درگاه پرداخت** — Zarinpal + Zibal + کارت به کارت + تتر TRC20
- **کد تخفیف** — درصد تخفیف + محدودیت استفاده
- **لایسنس چندبارمصرف** — max_uses قابل تنظیم (۱ تا ۱۰۰۰)
- **ساخت گروهی لایسنس** — تا ۱۰۰ لایسنس همزمان
- **تمدید خودکار** — از کیف پول وقتی اشتراک منقضی شد
- **ربات اختصاصی** — کاربر ربات خودش رو می‌خره + توکن می‌فرسته

### 👥 سیستم کاربری
- **۴ نقش** — OWNER / ADMIN / RESELLER / USER
- **نمایندگی** — مشتری جمع کن + مدیریت مشتری‌ها
- **همکاری (Affiliate)** — ۱۰٪ کمیسیون خودکار
- **دعوت دوستان** — جایزه اشتراک هدیه بعد از ۳ دعوت

### 🌐 پنل وب
- **پنل کاربر** — ورود با کد لایسنس (بدون رمز عبور)
  - داشبورد: موجودی + اشتراک + سلف‌بات‌ها
  - کیف پول: موجودی + تراکنش‌ها
  - سفارش‌ها: لیست + پرداخت با کیف پول
  - اکانت‌ها: انتخاب + Live Session
  - چت‌ها: لیست چت‌ها + ارسال پیام
  - تنظیمات: پروکسی + api_id + phone
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
- **۲FA به‌صورت hash** — salted SHA-256 (نه plaintext)
- **اکانت مالک** — 2FA غیرقابل تغییر

### 🔄 آپدیت خودکار
- **بررسی آپدیت** — هر ۶ ساعت
- **اعمال آپدیت** — git fetch + reset --hard + restart
- **rollback** — بازگشت به نسخه‌ی قبل (با صفحه‌بندی)
- **تشخیص تغییرات محلی** — اگه فایل‌ها دستی replace شده باشند

### ⏰ اتوماسیون
- **پیام زمان‌بندی‌شده** — ارسال در زمان مشخص
- **پاسخ خودکار** — بر اساس کلمه‌ی کلیدی

---

## 🚀 نصب

### روش اول: نصب خودکار (توصیه‌شده)

```bash
sudo bash <(curl -sL https://raw.githubusercontent.com/DLSDT/CiaNet.ir/main/install.sh)
```

ازت می‌پرسه:
- آیدی عددی تلگرام (از @userinfobot)
- توکن ربات ادمین (از @BotFather)
- api_id و api_hash (از my.telegram.org)
- نام کاربری و پسورد پنل ادمین
- دامنه‌ی پنل (اختیاری)

بعد از نصب:
1. در تلگرام `/start` بزن
2. اکانت اضافه کن (شماره + کد + 2FA)
3. پنل وب روی `https://your-domain/u/login.html`

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

---

## 📋 پیش‌نیازها

- Python 3.10+
- Ubuntu 20.04+ / Debian 11+
- Telegram API credentials (api_id + api_hash)
- Bot token (از @BotFather)
- دامنه + Cloudflare Tunnel (برای پنل وب از بیرون)

---

## 🏗 معماری

```
┌─────────────────────────────────────────────────┐
│                   Telegram                       │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ ربات ادمین │  │ ربات سلف  │  │ ربات کاربر│       │
│  │ (SaaSBot) │  │ (SelfBot) │  │ (Helper)  │       │
│  └─────┬─────┘  └─────┬─────┘  └──────────┘       │
│        │               │                           │
│        └───────┬───────┘                           │
│                │                                   │
├────────────────┼─────────────────────────────────┤
│           VPS (Server)                            │
│                │                                   │
│  ┌─────────────┴─────────────┐                    │
│  │     main.py (24K lines)    │                    │
│  │  ┌─────┐  ┌─────┐  ┌─────┐│                    │
│  │  │SaaSBot│  │SelfBot│  │AdminBot││                │
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
| 🟡 Zarinpal | آنلاین | کد مرچنت |
| 🟢 Zibal | آنلاین | کد مرچنت |
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

### ادمین (با session)
| Method | Path | توضیح |
|--------|------|------|
| GET | `/api/analytics/overview` | MRR + ARPU + churn |
| GET | `/api/analytics/daily-revenue` | نمودار درآمد |
| GET | `/api/analytics/export` | خروجی CSV |
| GET | `/api/users` | لیست کاربران |
| POST | `/api/users/{id}/wallet/credit` | شارژ کیف پول |

---

## 📝 Changelog

### v2.11.5
- ۴ باگ فیکس: admin guards، wallet race، deadlock، 2FA purge
- `_purge_old_2fa_plaintext` اضافه شد
- `owner_web_panel` از ADMIN حذف شد

### v2.11.4
- ۶ باگ فیکس: duplicate buttons، admin guards، dedicated bot rowcount
- `dedicated_bots` INSERT با reseller_id درست
- `_tabchi_loop` _flood_until با `(e.seconds or 30)`

### v2.11.3
- ۵ باگ فیکس: admin guards، double-charge، order-before-debit
- `dedicated_bot_price()` helper استفاده شد
- `_purge_old_2fa_plaintext` اضافه شد

### v2.11.0
- بازگشت به v2.10.5 base (پایدار)
- اضافه‌شدن: ربات اختصاصی + نمایندگی + 2FA block + connection cleanup

### v2.10.5
- ۸ باگ فیکس از ۵ ممیزی موازی
- wallet_transactions migration + auto_renew atomic + 2FA salted

### v2.10.0
- ۱۲ باگ فیکس از ۵ ممیزی
- فاز ۱-۵: تخفیف + کیف پول + سفارش + زمان‌بندی + affiliate

### v2.9.0
- فاز ۳: آنالیتیکس + نمودار
- فاز ۴: درگاه Zarinpal + auto-renew
- فاز ۵: زمان‌بندی + auto-reply + affiliate

### v2.8.0
- کیف پول کاربر + پنل وب غیرمتمرکز + ساخت گروهی لایسنس

### v2.7.0
- ساخت گروهی لایسنس (۱ تا ۱۰۰)

### v2.6.0
- UI حرفه‌ای + ۲۲ باگ فیکس

---

## 📄 License

MIT License — استفاده آزاد

---

## 🔗 لینک‌ها

- [گیت‌هاب](https://github.com/DLSDT/CiaNet.ir)
- [Issues](https://github.com/DLSDT/CiaNet.ir/issues)
- [Telegram](https://t.me/CiaNetSelf)
