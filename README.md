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
pip install telethon
python3 main.py all
```

### متغیرهای محیطی
```bash
export API_ID=...
export API_HASH=...
export BOT_TOKEN=...
export OWNER_ID=...                # فقط برای نمونه اصلی
export ADMIN_ID=...                # آیدی ادمین اصلی

# ربات اختصاصی (Dedicated Bot)
export SELFBOT_DEDICATED_BOT=1
export SELFBOT_DEDICATED_BOT_ID=123
export SELFBOT_GRANTS_DB_PATH=/path/to/main/saas.db
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
