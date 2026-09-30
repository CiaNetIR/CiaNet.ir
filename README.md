# CiaNet.ir — Telegram Selfbot SaaS Panel

پنل SaaS سلف‌بات تلگرام با قابلیت‌های کامل مدیریت اکانت، سیستم مجوزهای امنیتی، ربات راهنما، و ربات‌های اختصاصی.

## ✨ قابلیت‌ها

### 🏠 پنل مدیریت (Admin Panel)
- لیست/افزودن/حذف اکانت‌های سلف
- مدیریت ادمین‌ها (در حالت standalone)
- ناوبری شیشه‌ای با دکمه‌های inline

### 👤 مدیریت هر اکانت
- **قابلیت‌ها (Features)**: toggle هر ویژگی
- **ظاهر و پروفایل**: تغییر اسم + فونت (bold, double, sans, mono, normal)
- **ارسال پیام**: به Saved Messages یا مخاطب
- **اتصال و پروکسی**: SOCKS5/SOCKS4/HTTP با auth اختیاری

### 🔐 امنیت اکانت (سیستم مجوز متمرکز)
- **دستگاه‌های لاگین‌شده**: لیست، انتخاب، بستن انتخاب‌شده‌ها، خروج از همه
- **رمز دو مرحله‌ای (2FA)**: مدیریت + بازنشانی با تأیید دو مرحله‌ای
- **دریافت کد لاگین**: arm listener + خواندن کد بعدی

### 🛡️ Security Core (لایه مرکزی)
- **`permission_grants`** — جدول مجوزها با `scope_type` (reseller/dedicated_bot/account)
- **`authorize_sensitive_account_action()`** — تنها مرجع تصمیم‌گیری برای همه‌ی عملیات حساس
- **`SECURITY_ROUTES`** — لیست prefixهایی که قبل از اجرا از لایه مرکزی رد می‌شوند
- **Owner Bypass** — فقط در نمونه اصلی (نه ربات اختصاصی)
- **Grant/Revoke** — با Audit Trail کامل

### 👥 نقش‌ها
- `OWNER` — مالک اصلی (owner bypass)
- `ADMIN` — مدیران
- `RESELLER` — نمایندگان (با محدودیت تعداد کاربر)
- `USER` — کاربران عادی

### 💳 اشتراک و پرداخت
- پلن‌های قیمت‌گذاری شده (pricing)
- پرداخت TRC20 (تتر) و کارت
- لایسنس با redeem_atomic (replay protection)
- اشتراک خودکار منقضی می‌شود
- هشدار انقضا (24 ساعت قبل)

### 🤖 ربات‌های اختصاصی (Dedicated Bots)
- نماینده می‌تواند ربات اختصاصی راه‌اندازی کند
- قیمت ثابت (`dedicated_bot_price()`)
- چرخه: pending_payment → active
- Grant امنیتی `SCOPE_DEDICATED_BOT` فقط در bot_id همان ربات

### 🧭 ناوبری
- `nav:back` — برگشت (با پشته)
- `nav:home` — منوی اصلی
- `nav:noop` — دکمه تزئینی

### 🤖 Helper Bot (ربات راهنما)
- توکن مستقل، بدون دسترسی به DB/اکانت‌ها
- ۱۲ موضوع (time, tabchi, mute, online, read, profile, tools, games, crypto, copy, status, tips)
- دو زبانه (فارسی + انگلیسی)
- Trigger: `پنل` / `راهنما` / `منو` / `panel` / `help` / `h` / `menu`

### 🗄️ دیتابیس (SQLite)
- ۲۲+ جدول (users, accounts, subscriptions, licenses, payments, orders, tickets, dedicated_bots, permission_grants, audit_log, …)
- `idempotent migration` (CREATE TABLE IF NOT EXISTS)
- WAL mode + foreign_keys

## 📊 ساختار کد

| کلاس | خط | کاربرد |
|------|-----|--------|
| `UI` | 4764 | ساخت دکمه‌های شیشه‌ای |
| `NavStack` | 5067 | پشته ناوبری per-user |
| `AdminBot` | 5146 | پنل ادمین (standalone) |
| `SaaSBot` | 7791 | ربات SaaS اصلی |
| `HelperBot` | 12732 | ربات راهنما (read-only) |
| `RunningAccount` | 13210 | اکانت‌های در حال اجرا |
| `SelfBot` | 14783 | منطق سلف‌بات |

- **۲۵۸ تابع** (def/async def)
- **۸ کلاس**
- **۱۸۸۱۲ خط**

## 🚀 نصب

```bash
git clone https://github.com/DLSDT/CiaNet.ir.git
cd CiaNet.ir
pip install -r requirements.txt
python3 main.py all
```

## 📦 پیش‌نیازها (Requirements)

### ۱. نرم‌افزار
- **Python 3.10+** (tested on 3.10, 3.11, 3.12)
- **Linux/Unix** یا WSL (systemd اختیاری ولی توصیه‌شده)
- **SQLite 3.35+** (با JSONB و RETURNING)

### ۲. کتابخانه‌های Python
| پکیج | ضروری؟ | کاربرد |
|------|--------|--------|
| `telethon>=1.36.0` | ✅ بله | کلاینت تلگرام |
| `python_socks>=2.0.0` | اختیاری | پروکسی SOCKS5/4/HTTP برای لاگین اکانت‌ها |

بقیه (asyncio, sqlite3, urllib, hashlib, secrets) جزو **کتابخانه استاندارد** پایتون هستند.

### ۳. تلگرام — ۳ نوع توکن/اکانت
| نوع | منبع | استفاده |
|------|------|---------|
| **API ID + API Hash** | [my.telegram.org](https://my.telegram.org/apps) | `api_id` و `api_hash` برای همه کلاینت‌ها |
| **Admin Bot Token** | [@BotFather](https://t.me/BotFather) → `/newbot` | ربات اصلی (پنل SaaS) |
| **Helper Bot Token** | [@BotFather](https://t.me/BotFather) → `/newbot` (دوم) | ربات راهنما (read-only) |
| **User Account** | شماره تلفن اکانت کاربر | خود اکانت‌های سلف (لاگین با کد) |

### ۴. متغیرهای محیطی (Environment Variables)

#### نمونه اصلی (Main Instance)
```bash
# ضروری
export API_ID=12345                      # از my.telegram.org
export API_HASH=abc123...                # از my.telegram.org
export ADMIN_BOT_TOKEN=123456:ABC...     # از @BotFather
export ADMIN_ID=123456789                # آیدی عددی تلگرام شما

# اختیاری
export HELPER_BOT_TOKEN=789:XYZ...       # ربات راهنما
export HELPER_BOT_USERNAME=HelpBot       # یوزرنیم بدون @
export SELFBOT_DATA_DIR=/path/to/data    # پیش‌فرض: /opt/selfbot/data
export DEBUG=1                           # لاگ verbose
```

#### ربات اختصاصی (Dedicated Bot)
```bash
export SELFBOT_DEDICATED_BOT=1
export SELFBOT_DEDICATED_BOT_ID=42       # ID ربات اختصاصی در DB
export SELFBOT_GRANTS_DB_PATH=/path/to/main/saas.db   # مسیر DB مرکزی
export SELFBOT_DATA_DIR=/path/to/dedicated/42
```

### ۵. دسترسی‌های سیستمی (System Access)
| دسترسی | دلیل |
|--------|------|
| **فایل سیستم** (read/write) | ذخیره DB، session files، پروکسی، بکاپ |
| **پوشه `sessions/` با `chmod 700`** | فایل session تلگرام (sensitive) |
| **پورت خروجی HTTPS (443)** | دسترسی به API تلگرام + قیمت‌ها |
| **DNS** | resolve کردن telegram.org و APIها |

### ۶. APIهای خارجی (اختیاری ولی در کد استفاده شده)

#### قیمت لحظه‌ای (طلا/تتر/تون/ترون)
| API | URL | استفاده |
|-----|-----|---------|
| **Binance** | `api.binance.com` | قیمت USDT/TON/TRX |
| **CoinGecko** | `api.coingecko.com` | fallback + قیمت IRR |
| **Bybit** | `api.bybit.com` | fallback |
| **KuCoin** | `api.kucoin.com` | fallback |
| **OKX** | `www.okx.com` | قیمت طلا (XAU-USDT) |
| **Nobitex** | `api.nobitex.ir` | قیمت تومان |
| **Wallex** | `api.wallex.ir` | قیمت تومان (fallback) |
| **Exir** | `api.exir.io` | قیمت تومان (fallback) |
| **Bit24** | `api.bit24.cash` | قیمت تومان (fallback) |
| **Navasan (GitHub)** | `raw.githubusercontent.com/.../gold.json` | قیمت طلا/سکه |

#### تأیید پرداخت TRC20
| API | URL | استفاده |
|-----|-----|---------|
| **TronGrid** | `api.trongrid.io` | تأیید تراکنش USDT روی شبکه TRON |

⚠️ **اگر اینترنت به این APIها محدود باشد، قابلیت قیمت و پرداخت TRC20 کار نمی‌کند** (ولی بقیه ربات سالم می‌ماند).

### ۷. ساختار پوشه‌ها (خودکار ساخته می‌شود)
```
$DATA_DIR/
├── saas.db                  # دیتابیس اصلی (SQLite)
├── config.json              # کانفیگ اکانت‌ها
├── admin_bot_admins.json    # لیست ادمین‌ها (standalone mode)
├── account_delete_journal.json
├── sessions/                # فایل session هر اکانت (chmod 700)
│   ├── helper_bot.session
│   ├── admin_bot.session
│   └── myaccount.session
├── downloads/               # فایل‌های دانلودشده
└── tracker_media/           # پیام‌های حذف/ادیت‌شده
```

### ۸. نصب استاندارد (Systemd)

```bash
# 1. کلون + نصب
git clone https://github.com/DLSDT/CiaNet.ir.git /opt/selfbot
cd /opt/selfbot
pip install -r requirements.txt

# 2. env file
sudo tee /etc/selfbot.env <<EOF
API_ID=12345
API_HASH=abc...
ADMIN_BOT_TOKEN=...
ADMIN_ID=123456789
EOF
sudo chmod 600 /etc/selfbot.env

# 3. systemd service
sudo tee /etc/systemd/system/selfbot.service <<'EOF'
[Unit]
Description=Telegram Selfbot SaaS Panel
After=network-online.target

[Service]
Type=simple
User=selfbot
WorkingDirectory=/opt/selfbot
EnvironmentFile=/etc/selfbot.env
ExecStart=/usr/bin/python3 main.py all
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 4. شروع
sudo systemctl daemon-reload
sudo systemctl enable --now selfbot.service
```

## 🔒 امنیت

- **Owner Bypass** فقط در نمونه اصلی (نه Dedicated Bot)
- **Central Auth** — همه عملیات حساس از `authorize_sensitive_account_action()` رد می‌شوند
- **Tag ownership check** — callback‌های حساس اول مالکیت tag رو چک می‌کنن
- **Audit log** — همه grant/revoke در `audit_log` ثبت می‌شه
- **Replay protection** — هر txid فقط یک‌بار روی هر فاکتور
- **Idempotent license redeem** — atomic

## 📜 License

MIT
