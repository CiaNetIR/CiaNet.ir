<div align="center">

# 🤖 CiaNet.ir

### Telegram Selfbot SaaS Panel

پنل مدیریت چند‌اکانتی با ربات تلگرام + پنل وب + آپدیت خودکار

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab.svg)](https://www.python.org)
[![Telethon](https://img.shields.io/badge/telethon-1.36+-28a8ea.svg)](https://docs.telethon.dev)
[![Version](https://img.shields.io/badge/version-2.1.7-blue.svg)](#-changelog)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[Quick Start](#-quick-start) · [Features](#-features) · [Web Panel](#-web-panel) · [Architecture](#-architecture) · [Changelog](#-changelog)

</div>

---

## ⚡ Quick Start

### نصب ربات سلف

```bash
git clone https://github.com/DLSDT/CiaNet.ir.git /opt/cianet
cd /opt/cianet
sudo bash install_service.sh
```

اسکریپت:
- ✅ کاربر `cianet` می‌سازه
- ✅ venv در `/opt/cianet/.venv/` می‌سازه
- ✅ وابستگی‌ها (telethon) رو نصب می‌کنه
- ✅ env file `/etc/cianet.env` با chmod 600 می‌سازه
- ✅ systemd service `cianet` (با auto-restart)
- ✅ session‌ها و config.json رو محدود می‌کنه به 600

### نصب پنل وب (اختیاری ولی توصیه‌شده)

```bash
cd /opt/cianet
sudo bash install_panel.sh
```

اسکریپت:
- ✅ venv رو extend می‌کنه با FastAPI + uvicorn + passlib
- ✅ bcrypt password hash می‌سازه (با sha256 fallback)
- ✅ systemd service `cianet-panel` روی port 8000
- ✅ ۳ گزینه برای دسترسی:
  - **Cloudflare Tunnel** + Zero Trust (توصیه‌شده برای IP متغیر)
  - **nginx + Let's Encrypt** (برای IP ثابت)
  - بدون reverse proxy (فقط localhost یا SSH tunnel)

---

## ✨ Features

### 🤖 ربات سلف (Telegram)

| قابلیت | توضیح |
|--------|------|
| **چند اکانتی** | مدیریت unlimited اکانت کاربر از یک پنل |
| **پنل شیشه‌ای** | UI کامل با callback buttons + nav stack |
| **قابلیت‌های خودکار** | name/bio loop, presence, tabchi, dice |
| **پروفایل پویا** | ساعت در name، bio متغیر |
| **antiban** | jitter per-tag, detection بدونه الگوی synchronized |
| **session guard** | auto-recovery، corruption detection |
| **proxy support** | SOCKS5/HTTP/MTProto per-account |

### 👥 نقش‌ها

- **OWNER** — کل سیستم + auto-updater + web panel
- **ADMIN** — مدیریت کاربران و اکانت‌ها
- **RESELLER** — مشتری‌های خودش + ربات اختصاصی
- **USER** — اکانت خودش + اشتراک

### 🌐 Web Panel

- 🔐 ورود با bcrypt (PANEL_ADMIN_USER + PANEL_ADMIN_PASS_HASH)
- 📊 ۹ صفحه: داشبورد، کاربران، سلف‌بات‌ها، مالی، تیکت‌ها، audit، نسخه، هش، تنظیمات
- 🎨 Dark theme (Vercel/Linear-inspired) + RTL
- ⚡ Frontend استاتیک در `web_static/` (بدون نیاز به npm)
- 🔄 در دسترس از: `http://localhost:8000/app/login.html` یا `https://panel.domain.ir/app/login.html`

### 🔒 امنیت

- bcrypt password hashing (با sha256 fallback)
- ۸-hour session cookies با random 32-byte token
- session در memory (در restart پاک می‌شه)
- فقط OWNER می‌تونه login کنه (single-user model)
- `(Optional)` Cloudflare Zero Trust access policy برای 2FA

### 🔄 آپدیت خودکار + Rollback

- دکمه‌ی «🔄 آپدیت و ورژن» در پنل OWNER
- backup خودکار از main.py قبل از هر آپدیت
- rollback به هر نسخه‌ی قدیمی با یک کلیک
- (Optional) `CIANET_MIN_COMMIT` env برای supply chain protection

---

## 🌐 Web Panel

### Frontend

| آدرس | محتوا |
|------|------|
| `/app/login.html` | ورود |
| `/app/dashboard.html` | داشبورد آمار |
| `/app/users.html` | مدیریت کاربران |
| `/app/accounts.html` | مدیریت سلف‌بات‌ها |
| `/app/finance.html` | پرداخت‌ها |
| `/app/tickets.html` | تیکت‌ها |
| `/app/audit.html` | Audit log |
| `/app/version.html` | آپدیت/rollback |
| `/app/tools.html` | api_id/api_hash |
| `/app/settings.html` | تنظیمات |

### Backend API

| آدرس | محتوا |
|------|------|
| `GET /api/health` | Health check (public) |
| `POST /api/auth/login` | Login |
| `GET /api/dashboard` | آمار کلی |
| `GET /api/users` | لیست کاربران |
| `GET /api/accounts` | لیست سلف‌بات‌ها |
| `GET /api/finance/payments` | پرداخت‌ها |
| `GET /api/tickets` | تیکت‌ها |
| `GET /api/audit-log` | Audit log |
| `GET /api/version` | اطلاعات نسخه |
| `GET /api/tools/api-creds` | api_id/api_hash pool |
| `/api/docs` | Swagger UI (interactive) |

---

## 📁 File Structure

```
/opt/cianet/
├── main.py              # ربات اصلی (selfbot + admin + saas)
├── cianet_updater.py    # auto-updater module
├── web_panel.py         # FastAPI backend (port 8000)
├── web_static/          # Frontend استاتیک (vanilla JS)
│   ├── app.js
│   ├── styles.css
│   └── *.html           # 9 pages
├── web/                 # (اختیاری) Next.js frontend
├── install_service.sh   # نصب ربات
├── install_panel.sh     # نصب پنل وب
├── setup.sh             # legacy install (interactive)
├── requirements.txt
└── data/
    ├── config.json      # api_id, api_hash, sessions per account
    ├── saas.db          # users, subscriptions, payments, tickets
    ├── bot_data.db      # account metadata
    └── sessions/        # .session files (chmod 600)
```

---

## ⚙️ Environment Variables

در `/etc/cianet.env`:

### ضروری

```bash
API_ID=12345                       # از my.telegram.org
API_HASH=abc123def456...           # از my.telegram.org
ADMIN_BOT_TOKEN=123456:ABC-DEF      # از @BotFather
ADMIN_ID=123456789                 # Telegram user_id شما
```

### اختیاری

```bash
# Multi-OWNER (اگه چند صاحب داری)
OWNER_IDS=123456789,987654321

# Bootstrap api_id (اگه config.json خالی شد)
CIANET_API_ID=12345
CIANET_API_HASH=abc123def456...

# Auto-updater supply chain protection
CIANET_MIN_COMMIT=<40-char SHA از آخرین شناخته‌شده‌ی خوب>

# Web panel auth
PANEL_ADMIN_USER=admin
PANEL_ADMIN_PASS_HASH=$2b$12$...   # bcrypt hash
PANEL_SESSION_SECRET=<32-byte hex>

# Web panel URL (برای دکمه‌ی «پنل وب» در ربات)
PANEL_URL=https://panel.cianet.ir

# CORS
PANEL_CORS_ORIGINS=https://panel.cianet.ir,http://localhost:3000

# Helper bot (اختیاری)
HELPER_BOT_TOKEN=...
```

---

## 🛠️ Operations

### سرویس‌ها

```bash
# ربات اصلی
sudo systemctl status cianet
sudo systemctl restart cianet
sudo journalctl -u cianet -f

# پنل وب
sudo systemctl status cianet-panel
sudo systemctl restart cianet-panel
sudo journalctl -u cianet-panel -f

# (اگه Cloudflare Tunnel انتخاب کردی)
sudo systemctl status cianet-tunnel
sudo journalctl -u cianet-tunnel -f
```

### بکاپ

```bash
# بکاپ کامل (config + sessions + databases):
cd /opt/cianet
sudo tar -czf /tmp/cianet-backup-$(date +%F).tar.gz data/

# یا از داخل ربات: پنل OWNER → 💾 بکاپ و بازیابی
```

### آپدیت

```bash
# روش ۱: از داخل ربات (توصیه‌شده)
# پنل OWNER → 🔄 آپدیت و ورژن → 📥 اعمال آپدیت

# روش ۲: manual
cd /opt/cianet
sudo git pull origin main
sudo systemctl restart cianet cianet-panel
```

### Rollback

```bash
# از داخل ربات: پنل OWNER → 🔄 آپدیت و ورژن → ↩️ لیست نسخه‌های قابل rollback
# یا از web panel: /app/version.html
```

---

## 🔐 Security Notes

- **session files** = کلید takeover اکانت‌ها. همیشه با `chmod 600` ذخیره می‌شن
- **config.json** = شامل api_id, api_hash, phone. با `chmod 600` ذخیره می‌شه
- **saas.db / bot_data.db** = PII + payments. با `chmod 600` بعد از init
- **دکمه‌ی antiban** = قبل از عملیات حساس (terminate sessions, 2FA reset) روی اکانت‌های خارجی، تأیید دوم می‌خواد

### توصیه‌ها

1. **حتماً** توکن GitHub و سرویس‌های ابری رو بعد از استفاده revoke کن
2. اگه از Cloudflare Tunnel استفاده می‌کنی، Zero Trust Access Policy فعال کن
3. password پنل وب رو قوی بزار (۱۲+ کاراکتر)
4. هر چند ماه یک‌بار از `/app/audit.html` لاگ‌ها رو بررسی کن

---

## 🐛 Troubleshooting

### پنل بالا نمیاد

```bash
sudo systemctl status cianet-panel
sudo journalctl -u cianet-panel --no-pager -n 30
```

### خطای "Cannot uninstall typing_extensions"

این یعنی apt و pip conflict دارن. راه‌حل: از venv استفاده کن (در install_panel.sh خودکار انجام می‌شه).

```bash
sudo rm -rf /opt/cianet/.venv
sudo bash /opt/cianet/install_panel.sh
```

### خطای "Address already in use" (port 8000)

```bash
sudo lsof -i :8000
sudo kill <PID>
sudo systemctl restart cianet-panel
```

### Cloudflare Tunnel وصل نمی‌شه

```bash
sudo systemctl status cianet-tunnel
sudo journalctl -u cianet-tunnel --no-pager -n 20
```

اگه خطای "token invalid" داد، tunnel رو در Cloudflare dashboard دوباره بساز.

### ربات کرش می‌کنه

```bash
sudo journalctl -u cianet --no-pager -n 50
# یا:
DEBUG=1 sudo systemctl restart cianet
```

---

## 📋 Changelog

### v2.1.7 (current)

- ✅ دکمه‌ی «🌐 پنل وب» در ربات با URL buttons که مستقیم مرورگر رو باز می‌کنن
- ✅ تشخیص خودکار وضعیت cianet-panel و cianet-tunnel
- ✅ README مرتب و تمیز

### v2.1.6

- ☁️ پشتیبانی از Cloudflare Tunnel + Zero Trust در install_panel.sh
- ✅ نصب خودکار `cloudflared` با apt/yum/binary fallback
- ✅ systemd service `cianet-tunnel` با auto-restart
- ✅ ثبت خودکار `PANEL_URL` در env

### v2.1.5

- 🔐 Username case-insensitive در login
- 🐛 فیکس DB schema در ۵ endpoint (amount, approved_at, text, etc.)
- 🌐 Frontend استاتیک (web_static/) — بدون نیاز به npm
- 🤖 دکمه‌ی «🌐 پنل وب» در پنل OWNER ربات

### v2.1.0 — v2.1.4

- 🌐 پنل وب کامل (FastAPI + Next.js frontend)
- 🐛 فیکس venv برای typing_extensions conflict
- 🐛 فیکس password prompt UX

### v2.0.8 — v2.0.13

- 🔄 آپدیت خودکار + Rollback (دکمه‌ی «🔄 آپدیت و ورژن»)
- 🚀 Owner quick-actions panel
- 🔒 Supply chain protection (CIANET_MIN_COMMIT)
- 📊 Resilience fixes (wizard TTL, logs trim)

### v2.0.0 — v2.0.7

- 🤖 پایه‌ی ربات سلف + پنل ادمین
- 🐛 ۱۴ باگ critical فیکس شد
- 🎨 UI overhaul با nav stack

---

## 🗑️ Uninstall / حذف کامل

برای حذف کامل CiaNet از سرور:

```bash
# ۱. توقف سرویس‌ها
sudo systemctl stop selfbot cianet-panel cianet-tunnel 2>/dev/null

# ۲. غیرفعال‌سازی سرویس‌ها
sudo systemctl disable selfbot cianet-panel cianet-tunnel 2>/dev/null

# ۳. حذف فایل‌های systemd
sudo rm -f /etc/systemd/system/selfbot.service
sudo rm -f /etc/systemd/system/cianet-panel.service
sudo rm -f /etc/systemd/system/cianet-tunnel.service
sudo systemctl daemon-reload

# ۴. حذف nginx config (اگه تنظیم کردی)
sudo rm -f /etc/nginx/sites-enabled/cianet-panel
sudo rm -f /etc/nginx/sites-available/cianet-panel
sudo systemctl reload nginx 2>/dev/null

# ۵. حذف فایل env (شامل credentials)
sudo rm -f /etc/cianet.env /etc/selfbot.env

# ۶. حذف دایرکتوری پروژه
sudo rm -rf /opt/cianet

# ۷. (اختیاری) حذف کاربر cianet
sudo userdel cianet 2>/dev/null

# ۸. (اختیاری) حذف cloudflared
sudo apt remove -y cloudflared 2>/dev/null
sudo rm -f /usr/local/bin/cloudflared

# ۹. (اختیاری) حذف nginx config بکاپ
sudo rm -f /etc/nginx/sites-available/cianet-panel*

# ۱۰. تأیید حذف
systemctl status selfbot 2>&1 | head -3
systemctl status cianet-panel 2>&1 | head -3
ls /opt/cianet 2>&1
```

---

## 📜 License

MIT License — see [LICENSE](LICENSE) file.

---

## 🤝 Contributing

PR ها welcome هستن. لطفاً قبل از submit:

1. `python3 -c "import ast; ast.parse(open('main.py').read())"` رو اجرا کن
2. shell syntax رو با `bash -n install_panel.sh` بررسی کن
3. commit message مطابق با conventional commits باشه

---

<div align="center">

**ساخته‌شده با ❤️ توسط [DLSDT](https://github.com/DLSDT)**

اگه این پروژه بهت کمک کرد، یه ⭐ بده!

</div>
