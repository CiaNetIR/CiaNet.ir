<div align="center">

```
   ╔════════════════════════════════════════════════════╗
   ║                                                    ║
   ║      ▄████▄  ██▓ ▄▄▄      ███▄    █ ▓█████ ▄▄▄    ║
   ║     ▒██▀ ▀█  ▓██▒▒████▄    ██ ▀█   █ ▓█   ▀ ▒████▄  ║
   ║     ▒▓█    ▄ ▒██▒▒██  ▀█▄  ▓██  ▀█ ██▒▒███   ▒██  ▀█▄║
   ║     ▒▓▓▄ ▄██▒░██░░██▄▄▄▄██ ▓██▒  ▐▌██▒▒▓█  ▄ ░██▄▄▄▄██║
   ║     ▒ ▓███▀ ░██░ ▓█   ▓██▒▒██░   ▓██░░▒████▒ ▓█   ▓██║
   ║                                                    ║
   ║          سلف‌بات تلگرام · Telegram Selfbot           ║
   ╚════════════════════════════════════════════════════╝
```

**CiaNet.ir** — Telegram Selfbot SaaS Panel

پنل مدیریت چند‌اکانتی با رابط شیشه‌ای، سیستم مجوز متمرکز، و ربات‌های اختصاصی نمایندگان.
*Multi-account selfbot panel with inline UI, central authorization, and dedicated reseller bots.*

---

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab.svg)](https://www.python.org)
[![Telethon](https://img.shields.io/badge/telethon-1.36+-28a8ea.svg)](https://docs.telethon.dev)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests: 246](https://img.shields.io/badge/tests-246%20passing-success.svg)](#-tests)
[![Version: 2.0](https://img.shields.io/badge/version-2.0-blue.svg)](#-changelog)

[Quick Start](#-quick-start) · [Features](#-features) · [Architecture](#-architecture) · [Security](#-security) · [Changelog](#-changelog)

</div>

---

## ⚡ Quick Start / شروع سریع

> **One command. Everything automated.** / **یک دستور. همه چیز خودکار.**

### 🚀 The One-Liner / دستور جادویی

```bash
curl -sSL https://raw.githubusercontent.com/DLSDT/CiaNet.ir/main/setup.sh | sudo bash
```

یا **non-interactive** با env vars:

```bash
API_ID=12345 \
API_HASH=abc123def456 \
ADMIN_BOT_TOKEN=123456:ABC-DEF \
ADMIN_ID=123456789 \
curl -sSL https://raw.githubusercontent.com/DLSDT/CiaNet.ir/main/setup.sh | sudo bash -s -- --non-interactive
```

**بعد از ۲ دقیقه:**
- ✅ CiaNet در `/opt/cianet` نصب شده
- ✅ Python venv + dependencies
- ✅ systemd service (`cianet.service`) — **هرگز خاموش نمی‌شه**
- ✅ Watchdog (هر ۱ دقیقه چک می‌کنه)
- ✅ Auto-updater (هر ۵ دقیقه GitHub رو چک می‌کنه)
- ✅ اگه webhook تنظیم بشه: real-time update

**Send `/start` to your bot. Done. ✨**
**به ربات `/start` بفرستید. تمام. ✨**

> 💡 قبل از اجرا، این‌ها رو آماده داشته باشید: **API ID** (my.telegram.org), **API Hash**, **Admin Bot Token** (@BotFather), **Admin ID** (@userinfobot).

### 🔄 Self-Update Flow / آپدیت خودکار

```
شما روی GitHub push می‌کنید
         ↓
     [۱] polling (هر ۵ دقیقه) ────┐
     [۲] webhook (real-time) ─────┤
                                  ↓
                  cianet_updater.check_for_update()
                                  ↓
            ┌─ آپدیت پیدا شد؟ ──────┐
            ↓ YES                    ↓ NO
    apply_update()               (ادامه)
            ↓
    ① graceful disable همه‌ی اکانت‌ها
    ② backup main.py → versions/
    ③ git pull
    ④ systemd restart
            ↓
    ⑤ re-enable همه‌ی اکانت‌ها
    ⑥ notify admin (با commit hash)
```

**نکات کلیدی:**
- ⏸ **بدون قطعی برای کاربران**: اکانت‌ها disable می‌شن، آپدیت می‌شه، دوباره enable
- 🔐 **بدون data loss**: backup اتوماتیک قبل از هر آپدیت
- 🔄 **همیشه به‌روز**: اگه ۵ دقیقه polling از کار بیفته، webhook جبران می‌کنه
- 📊 **ادغام با پنل**: `Ⅳ سیستم → 🔄 به‌روزرسانی` (با badge تعداد commit‌ها)

### 📡 اختیاری: Webhook Setup (real-time) / وب‌هوک

اگه می‌خواهید آپدیت real-time باشه (نه ۵ دقیقه delay):

```bash
# 1. یه URL عمومی نیاز دارید (مثلاً cloudflared tunnel)
cloudflared tunnel --url http://localhost:9876

# 2. secret URL رو در env تنظیم کنید
export CIANET_WEBHOOK_SECRET=$(openssl rand -hex 16)
# مثلاً: webhook URL = https://your-tunnel.trycloudflare.com/webhook/abc123...

# 3. در GitHub:
#    Settings → Webhooks → Add
#    URL: https://your-tunnel.trycloudflare.com/webhook/abc123...
#    Content: application/json
#    Events: just the push event
```

حالا هر push شما بلافاصله ربات رو آپدیت می‌کنه (نه ۵ دقیقه delay).

---

## ✨ Features / قابلیت‌ها

### 🎛️ Admin Panel / پنل مدیریت

| EN | FA |
|---|---|
| **5-section hub** — Sales, Users, Support, System, Security | **هاب ۵ بخشی** — فروش، کاربران، پشتیبانی، سیستم، امنیت |
| **Roman-numeral navigation** (Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ) | **شماره‌گذاری رومی** برای تشخیص سریع |
| **Inline glass buttons** with Telegram's native `bg_success`/`bg_danger`/`bg_primary` | **دکمه‌های شیشه‌ای** با رنگ‌های بومی تلگرام |
| **Pending count badges** on action buttons | **شمارنده‌ی کارهای معوق** روی دکمه‌ها |
| **Two-column layout** for compact screens | **چیدمان دو ستونی** برای صفحات فشرده |

### 🔐 Security Core / لایه‌ی امنیتی مرکزی

| EN | FA |
|---|---|
| **Central authorization** — every sensitive action passes through `authorize_sensitive_account_action()` | **مجوزدهی مرکزی** — همه‌ی عملیات حساس از یک تابع واحد رد می‌شوند |
| **Scoped grants** — `reseller` / `dedicated_bot` / `account` | **مجوزهای مقید** — سه سطح |
| **Owner bypass** only in main instance (never in dedicated bots) | **دور زدن توسط Owner** فقط در نمونه اصلی |
| **Full audit trail** — every grant/revoke logged | **تاریخچه‌ی کامل** — همه‌چیز ثبت می‌شه |
| **2FA management** with two-step confirmation for resets | **مدیریت 2FA** با تأیید دو مرحله‌ای برای بازنشانی |
| **Replay protection** — txid / license redeem are atomic | **محافظت از تکرار** — تراکنش و لایسنس atomic |

### 🤖 Account Management / مدیریت اکانت

| EN | FA |
|---|---|
| **Multi-account** — run many selfbots from one panel | **چند‌اکانتی** — چند سلف از یک پنل |
| **Per-account features** — toggle individual capabilities | **قابلیت‌های مستقل** — هر اکانت تنظیم خودش |
| **Profile editor** — name + font (bold/double/sans/mono/normal) | **ویرایش پروفایل** — اسم + فونت |
| **Message send** — to Saved Messages or any chat | **ارسال پیام** — به Saved Messages یا هر چت |
| **Proxy support** — SOCKS5/SOCKS4/HTTP with optional auth | **پروکسی** — SOCKS5/4/HTTP با auth |
| **Device management** — list, kick, logout-all | **مدیریت دستگاه** — لیست، بستن، خروج‌کلی |

### 💳 Subscription & Payment / اشتراک و پرداخت

| EN | FA |
|---|---|
| **Flexible plans** — duration × price in pricing table | **پلن‌های منعطف** — قیمت‌گذاری پویا |
| **TRC20 (USDT)** verification via TronGrid | **تأیید TRC20** از طریق TronGrid |
| **Card payment** manual approval workflow | **پرداخت کارتی** با تأیید دستی |
| **License keys** with atomic redeem | **لایسنس** با فعال‌سازی atomic |
| **Auto-expiry** with 24h warning | **انقضای خودکار** با هشدار ۲۴ ساعته |
| **Live price feeds** — gold, USDT, TON, TRX, IRR | **قیمت لحظه‌ای** — طلا، تتر، تون، ترون، تومان |

### 🤝 Reseller Program / برنامه‌ی نمایندگی

| EN | FA |
|---|---|
| **Dedicated bot** per reseller (their own brand) | **ربات اختصاصی** برای هر نماینده |
| **Customer management** — list, sub status, license issuance | **مدیریت مشتریان** — لیست، وضعیت اشتراک، صدور لایسنس |
| **Auto income** — earnings calculated from sales | **درآمد خودکار** — محاسبه از فروش |
| **Self-service application** — users request from main panel | **درخواست خودکار** — کاربر از پنل اصلی |

### 🧭 Navigation & UX / ناوبری و تجربه

| EN | FA |
|---|---|
| **Per-user back stack** — `back` is always 1 real step back | **پشته‌ی بازگشت** — همیشه یک قدم واقعی به عقب |
| **`nav:home`** — always-safe exit from any depth | **منوی اصلی** — خروج امن از هر عمقی |
| **Sticky breadcrumbs** on every page | **مسیر شناور** در همه‌ی صفحات |
| **Single welcome block** — `/start` always returns to main menu | **منوی واحد** — `/start` همیشه به ریشه |

---

## 🏗️ Architecture / معماری

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram MTProto API                      │
└──────────────┬──────────────────────────┬───────────────────┘
               │                          │
       ┌───────▼──────┐         ┌─────────▼────────┐
       │  Admin Bot   │         │  Helper Bot      │
       │  (SaaS panel)│         │  (read-only FAQ) │
       │  Bot Token   │         │  Bot Token       │
       └───────┬──────┘         └──────────────────┘
               │
       ┌───────▼──────────────────────────────────────┐
       │           SaaSBot (Python)                    │
       │  ┌────────────┐  ┌────────────┐  ┌────────┐  │
       │  │  UI Class  │  │ NavStack   │  │  Auth  │  │
       │  │  (glass)   │  │ (per-user) │  │ (grant)│  │
       │  └────────────┘  └────────────┘  └────────┘  │
       │  ┌──────────────────────────────────────┐     │
       │  │  SelfBot × N (Telethon clients)      │     │
       │  │  Account 1 · Account 2 · Account N   │     │
       │  └──────────────────────────────────────┘     │
       └───────┬──────────────────────────────────────┘
               │
       ┌───────▼──────────────────────────────────────┐
       │      SQLite (saas.db · WAL mode)             │
       │  users · accounts · subscriptions · licenses │
       │  payments · tickets · dedicated_bots ·      │
       │  permission_grants · audit_log ·             │
       │  reseller_applications                       │
       └────────────────────────────────────────────┘
```

### Core Components / اجزای اصلی

| Component | Lines | Role |
|---|---:|---|
| `UI` | ~270 | Inline button factory, color palette, microcopy / ساخت دکمه، پالت، متن‌های ثابت |
| `NavStack` | ~180 | Per-user back-stack with loop-breaker / پشته‌ی ناوبری |
| `AdminBot` | ~2,600 | Standalone admin panel (legacy) / پنل ادمین مستقل |
| `SaaSBot` | ~5,500 | Main SaaS bot, role-based menus / ربات اصلی |
| `SelfBot` | ~1,500 | Single-account Telethon logic / منطق سلف |
| `RunningAccount` | ~480 | Runtime wrapper with state machine / wrapper اکانت |

### Database Schema / اسکیمای دیتابیس

**۲۲+ tables**, all created with `CREATE TABLE IF NOT EXISTS` (idempotent migration):

```
users              subscriptions      licenses           payments
accounts           plans              orders             tickets
admins             dedicated_bots     permission_grants  audit_log
banned_users       sales_users        reseller_apps      ...
sessions (table)   backups            notifications      ...
```

WAL mode · `foreign_keys=ON` · indexed hot paths.

---

## 🔒 Security / امنیت

### Three-layer model / مدل سه‌لایه

```
┌──────────────────────────────────────────────────┐
│  Layer 1: Owner Bypass (main instance only)       │  ← short-circuit
│  Layer 2: Central Auth (single decision point)   │  ← single chokepoint
│  Layer 3: Tag ownership (callback validates tag) │  ← per-action check
└──────────────────────────────────────────────────┘
```

### Guarantees / تضمین‌ها

| EN | FA |
|---|---|
| **No security-critical code bypasses central auth** | **هیچ کد حساسی از مجوزدهی مرکزی رد نمی‌شه** |
| **Replay-proof** — txid / license / 2FA-reset are atomic | **ضد تکرار** — تراکنش، لایسنس، بازنشانی 2FA همگی atomic |
| **Sessions stored in `chmod 700` directory** | **سشن‌ها در پوشه‌ی `chmod 700`** |
| **Backups never contain partial state** (validated before send) | **بکاپ‌ها هرگز ناقص نیستند** (قبل از ارسال validate می‌شن) |
| **SQLite WAL** for crash-safety + concurrent reads | **WAL** برای ایمنی در برابر crash |

---

## 🧪 Tests / تست‌ها

**246 automated tests, 100% pass rate.**

| Suite | Count | Coverage |
|---|---:|---|
| `test_panel_v2.py` | 18 | Panel structure, reseller flow |
| `test_selfbot_features.py` | 57 | All per-account features |
| `test_antiban.py` | 49 | Anti-ban heuristics |
| `test_v1_8_0.py` | 44 | v1.8.0 features |
| `test_backup_e2e.py` | 24 | Full backup-restore round-trip |
| `test_user_menu.py` | 23 | User menu state machine |
| `test_backup_scheduler.py` | 13 | Auto-backup scheduler |
| `test_backup.py` | 12 | Backup internals |
| `test_support_role.py` | 10 | Support ticket lifecycle |
| `test_price_apis.py` | 9* | Price-feed API mocks (live-skip) |

\* some require network; graceful in CI

```bash
# Run all
for t in test_*.py; do python3 "$t"; done
```

---

## 📦 Environment / متغیرهای محیطی

### Required / ضروری

| Variable | Example | Source |
|---|---|---|
| `API_ID` | `12345` | [my.telegram.org/apps](https://my.telegram.org/apps) |
| `API_HASH` | `abc123...` | [my.telegram.org/apps](https://my.telegram.org/apps) |
| `ADMIN_BOT_TOKEN` | `123456:ABC...` | [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | `123456789` | [@userinfobot](https://t.me/userinfobot) |

### Optional / اختیاری

| Variable | Default | Purpose |
|---|---|---|
| `HELPER_BOT_TOKEN` | — | Read-only FAQ bot (12 topics, FA+EN) |
| `HELPER_BOT_USERNAME` | `HelpBot` | Without `@` |
| `SELFBOT_DATA_DIR` | `./data` | Where DB, sessions, backups live |
| `SELFBOT_DEDICATED_BOT` | `0` | Set to `1` to run as a dedicated bot |
| `SELFBOT_DEDICATED_BOT_ID` | — | Required if `SELFBOT_DEDICATED_BOT=1` |
| `SELFBOT_GRANTS_DB_PATH` | — | Path to main instance's `saas.db` (for grants lookup) |
| `DEBUG` | `0` | Verbose logging |

### External APIs (graceful failure) / APIهای خارجی

| API | Use | Fallback chain |
|---|---|---|
| **Binance** · CoinGecko · Bybit · KuCoin | USDT, TON, TRX prices | Each other |
| **OKX** | Gold (XAU-USDT) | — |
| **Navasan (GitHub)** | Gold/coin IRR | Manual entry |
| **Nobitex** · Wallex · Exir · Bit24 | IRR prices | Each other |
| **TronGrid** | TRC20 transaction verification | — |

> If a price API is unreachable, pricing features degrade gracefully; the bot stays online. / اگه API قیمت قطع باشه، قابلیت قیمت‌گذاری gracefully degrade می‌شه؛ ربات آنلاین می‌مونه.

---

## 🗂️ Project Layout / ساختار پروژه

```
CiaNet.ir/
├── main.py              # SaaS bot (single file, ~20k lines)
├── requirements.txt
├── versions/            # Stable snapshots for rollback
│   └── v2.0_panel_redesign.py
├── test_*.py            # 246 automated tests
├── sessions/            # Telegram .session files (chmod 700)
├── data/                # SQLite, config, backups
│   ├── saas.db
│   ├── config.json
│   ├── admin_bot_admins.json
│   └── backups/
└── helper_bot/          # Read-only FAQ bot (optional)
```

---

## 🛠️ Operations / عملیات

### Daily / روزانه

```bash
# View logs
sudo journalctl -u selfbot -f

# Check status
sudo systemctl status selfbot

# Restart
sudo systemctl restart selfbot
```

### Backup & Restore / بکاپ و بازیابی

The bot ships a **self-update** command accessible from the admin panel:

1. **Auto backup** — 3× daily, sent to all OWNER/ADMIN
2. **Manual backup** — `/start` → Admin → System → Backup
3. **Restore** — OWNER-only, with rollback support

Backups are **validated before delivery** (no partial state ever sent).

### Update / به‌روزرسانی

```bash
cd /opt/selfbot && git pull
sudo systemctl restart selfbot
```

Snapshots in `versions/` allow instant rollback if needed.

---

## 🤝 Contributing / مشارکت

Pull requests welcome. For major changes, open an issue first.

**Code style:** *No comments unless asked* · Type hints required for new functions · Tests for new features.

**قبل از PR:**
- `for t in test_*.py; do python3 "$t"; done` ← همه پاس بشن
- تغییرات schema در `init_db()` با `IF NOT EXISTS` اضافه شوند

---

## 📜 License / لایسنس

[MIT](LICENSE) — use, modify, distribute freely. / استفاده، تغییر و توزیع آزاد.

---

## 📋 Changelog / تاریخچه

### v2.1 — Self-Update & One-Command Install (2026-10-01) / نصب یک‌دستوری

> **یک `curl` تا ربات کامل + آپدیت خودکار.**

- **setup.sh**: یک اسکریپت که `/opt/cianet` می‌سازه + venv + deps + systemd + watchdog + auto-updater
- **cianet_updater.py**: polling (۵min) + webhook (real-time) + propagation
- **پنل ادمین → Ⅳ سیستم → 🔄 به‌روزرسانی**: با badge تعداد commit
- **Propagation**: بعد از آپدیت، همه‌ی اکانت‌های کاربران re-enable می‌شن
- **Watchdog**: اگه ربات بمیره، ۱ دقیقه بعد بیدارش می‌کنه
- **۱۱ تست E2E** (همه پاس، lock، backup، propagation، git pull failure)

### v2.0 — Panel Redesign (2026-10-01) / بازطراحی پنل

> **5-section admin hub with Roman-numeral navigation + reseller flow.**

- **Ⅰ** Sales · **Ⅱ** Users · **Ⅲ** Support · **Ⅳ** System · **Ⅴ** Security (OWNER-only)
- Welcome block shortened from 8 lines to 2
- New `reseller_applications` table + `_show_reseller_info` flow
- `UI.section_header`, `UI.NUM`, `UI.microcopy()` helpers
- 18 new tests (257 total, 100% pass)

### v1.9.3 — Backup Timeout Fix (2026-10-01) / فیکس تایم‌اوت بکاپ

> SQLite backup hung indefinitely on locked sessions.

- 10s timeout in `_snapshot_db_to_temp`
- 60s timeout in handler + scheduler
- Better error message to user

### v1.9.0 — Flat Admin Hub (2026-09-xx) / پنل تخت

> All admin ops on one page.

- Replaced 4-level nested menus with single flat hub
- 12–15 buttons per page, 1-tap reach for daily tasks

### v1.8.0 — User/Reseller/Admin Unification (2026-09-xx) / یکپارچه‌سازی منوها

> One menu for all roles, with role-specific extensions.

- Common top section + privileged extensions below
- Reseller dashboard reachable from main menu

---

<div align="center">

**CiaNet.ir** · Made with care in Tehran · ساخته‌شده با دقت در تهران

[⬆ Back to top](#top)

</div>
