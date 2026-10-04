#!/usr/bin/env bash
# CiaNet v2.12.0 — Universal Installer with License Gate
# کاربر باید کد لایسنس معتبر وارد کنه قبل از نصب
#
# روش استفاده:
#   sudo bash install.sh
#
# برای گرفتن لایسنس با OWNER تماس بگیرید.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_step() { echo -e "${BLUE}▶ $1${NC}"; }
print_ok() { echo -e "${GREEN}✅ $1${NC}"; }
print_warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_err() { echo -e "${RED}❌ $1${NC}"; }

if [ "$(id -u)" != "0" ]; then
    print_err "باید با sudo اجرا کنی: sudo bash $0"
    exit 1
fi

INSTALL_DIR="/opt/cianet"
SERVICE_NAME="selfbot"
VENV_DIR="$INSTALL_DIR/.venv"
REPO_URL="https://github.com/DLSDT/CiaNet.ir.git"
LICENSE_API="https://license.cianet.ir/api/verify"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  🤖 CiaNet v2.12.0 — Installer"
echo "═══════════════════════════════════════════════════════"
echo ""

# ─── License Gate ───────────────────────────────────────
print_step "بررسی لایسنس"
echo ""
echo "🔒 برای نصب CiaNet به لایسنس نیاز دارید."
echo "📡 برای دریافت لایسنس با OWNER تماس بگیرید:"
echo "   Telegram: @CiaNetOwner"
echo ""

LICENSE_VALID=false
MAX_ATTEMPTS=3
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT + 1))
    read -p "🎫 کد لایسنس را وارد کنید (یا 'exit' برای خروج): " LICENSE_KEY

    if [ "$LICENSE_KEY" = "exit" ] || [ -z "$LICENSE_KEY" ]; then
        print_err "نصب لغو شد."
        exit 1
    fi

    # بررسی لایسنس از طریق API (اگه سرور لایسنس در دسترس باشه)
    LICENSE_KEY=$(echo "$LICENSE_KEY" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')

    # روش ۱: بررسی آنلاین از طریق API
    if command -v curl &> /dev/null; then
        RESPONSE=$(curl -s --connect-timeout 10 --max-time 15 \
            -X POST "$LICENSE_API" \
            -H "Content-Type: application/json" \
            -d "{\"license\": \"$LICENSE_KEY\"}" 2>/dev/null || echo "")
    fi

    # روش ۲: بررسی آفلاین (کد‌های معتبر hardcoded)
    # لیست کد‌های معتبر — OWNER اینجا کد‌های فروخته‌شده رو اضافه می‌کنه
    # یا از API بررسی می‌کنه
    VALID_CODES=(
        "CIANET-DEMO-2024"
        # کد‌های جدید رو اینجا اضافه کن
    )

    # اگه API جواب داد
    if [ -n "$RESPONSE" ] && echo "$RESPONSE" | grep -q '"valid":true'; then
        LICENSE_VALID=true
        print_ok "لایسنس معتبر است!"
        break
    fi

    # اگه API جواب نداد، بررسی آفلاین
    for code in "${VALID_CODES[@]}"; do
        if [ "$LICENSE_KEY" = "$code" ]; then
            LICENSE_VALID=true
            break
        fi
    done

    if [ "$LICENSE_VALID" = true ]; then
        print_ok "لایسنس معتبر است!"
        break
    fi

    REMAINING=$((MAX_ATTEMPTS - ATTEMPT))
    if [ $REMAINING -gt 0 ]; then
        print_warn "کد لایسنس نامعتبر است. $REMAINING تلاش دیگر باقی مانده."
    fi
done

if [ "$LICENSE_VALID" != true ]; then
    print_err "کد لایسنس نامعتبر است یا سرور پاسخ نداد."
    echo ""
    echo "📡 برای دریافت لایسنس معتبر با OWNER تماس بگیرید:"
    echo "   Telegram: @CiaNetOwner"
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════"
print_ok "لایسنس تأیید شد! ادامه نصب..."
echo "═══════════════════════════════════════════════════════"
echo ""

# ─── Get credentials ─────────────────────────────────────
print_step "تنظیمات اولیه"
read -p "آیدی عددی تلگرام شما (از @userinfobot بپرس): " ADMIN_ID_INPUT
read -p "توکن ربات ادمین (از @BotFather): " ADMIN_BOT_TOKEN_INPUT
read -p "api_id (از my.telegram.org): " API_ID_INPUT
read -p "api_hash (از my.telegram.org): " API_HASH_INPUT
read -p "نام کاربری پنل ادمین وب (default: admin): " PANEL_ADMIN_USER_INPUT
PANEL_ADMIN_USER_INPUT=${PANEL_ADMIN_USER_INPUT:-admin}
read -p "پسورد پنل ادمین وب: " PANEL_ADMIN_PASS_INPUT
read -p "دامنه‌ی پنل (مثلاً panel.yourdomain.ir — اگه نداری، خالی بذار): " PANEL_DOMAIN_INPUT
read -p "کد مرچنت زرین‌پال (اختیاری — اگه نداری، خالی بذار): " ZARINPAL_MERCHANT_INPUT

if [ -z "$ADMIN_ID_INPUT" ] || [ -z "$ADMIN_BOT_TOKEN_INPUT" ] || [ -z "$API_ID_INPUT" ] || [ -z "$API_HASH_INPUT" ]; then
    print_err "همه‌ی فیلدهای اجباری رو پر کن"
    exit 1
fi

# ─── Install dependencies ───────────────────────────────
print_step "نصب پیش‌نیازها..."
apt-get update -y >/dev/null 2>&1
apt-get install -y python3 python3-pip python3-venv git sqlite3 curl nginx >/dev/null 2>&1
print_ok "پیش‌نیازها نصب شدند"

# ─── Create cianet user ─────────────────────────────────
print_step "ساخت user cianet..."
if ! id "cianet" &>/dev/null; then
    useradd -r -m -d "$INSTALL_DIR" -s /bin/bash cianet
    print_ok "user cianet ساخته شد"
else
    print_warn "user cianet از قبل وجود دارد"
fi

# ─── Clone repo ────────────────────────────────────────
print_step "clone کردن repo..."
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    sudo -u cianet git fetch origin >/dev/null 2>&1
    sudo -u cianet git reset --hard origin/main >/dev/null 2>&1
    print_ok "repo آپدیت شد"
else
    rm -rf "$INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR" >/dev/null 2>&1
    chown -R cianet:cianet "$INSTALL_DIR"
    print_ok "repo کلون شد"
fi

# ─── Create venv ────────────────────────────────────────
print_step "ساخت venv..."
if [ ! -d "$VENV_DIR" ]; then
    sudo -u cianet python3 -m venv "$VENV_DIR"
fi
sudo -u cianet "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null 2>&1
sudo -u cianet "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" >/dev/null 2>&1
print_ok "venv ساخته شد و پیش‌نیازها نصب شدند"

# ─── Create /etc/selfbot.env ────────────────────────────
print_step "ساخت /etc/selfbot.env..."
ENV_FILE="/etc/selfbot.env"
PASS_HASH=$(echo -n "$PANEL_ADMIN_PASS_INPUT" | sha256sum | awk '{print "sha256:"$1}')

cat > "$ENV_FILE" << EOF
# CiaNet environment
API_ID=$API_ID_INPUT
API_HASH=$API_HASH_INPUT
ADMIN_BOT_TOKEN=$ADMIN_BOT_TOKEN_INPUT
ADMIN_ID=$ADMIN_ID_INPUT
PANEL_ADMIN_USER=$PANEL_ADMIN_USER_INPUT
PANEL_ADMIN_PASS_HASH=$PASS_HASH
PANEL_SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(48))")
PANEL_CORS_ORIGINS=http://localhost:8000
CIANET_AUTO_UPDATE=1
EOF

if [ -n "$PANEL_DOMAIN_INPUT" ]; then
    echo "PANEL_URL=https://$PANEL_DOMAIN_INPUT" >> "$ENV_FILE"
fi
if [ -n "$ZARINPAL_MERCHANT_INPUT" ]; then
    echo "ZARINPAL_MERCHANT=$ZARINPAL_MERCHANT_INPUT" >> "$ENV_FILE"
    echo "PAY_ZARINPAL_ENABLED=1" >> "$ENV_FILE"
fi

chmod 600 "$ENV_FILE"
chown cianet:cianet "$ENV_FILE"
print_ok "env file ساخته شد"

# ─── Create systemd service ────────────────────────────
print_step "ساخت systemd service..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=CiaNet Telegram Selfbot
After=network-online.target
Wants=network-online.target
StartLimitBurst=10
StartLimitIntervalSec=300

[Service]
Type=simple
User=cianet
Group=cianet
WorkingDirectory=/opt/cianet
Environment=HOME=/opt/cianet
EnvironmentFile=/etc/selfbot.env
ExecStart=/opt/cianet/.venv/bin/python -u main.py all
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=selfbot

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
print_ok "service ساخته شد"

# ─── Install polkit + sudoers ───────────────────────────
print_step "نصب sudoers برای auto-update..."
echo "cianet ALL=(ALL) NOPASSWD: /bin/systemctl restart selfbot, /bin/systemctl start selfbot, /bin/systemctl stop selfbot" > /etc/sudoers.d/cianet
chmod 440 /etc/sudoers.d/cianet
print_ok "sudoers نصب شد — auto-update کار می‌کنه"

# ─── Start service ─────────────────────────────────────
print_step "شروع سرویس..."
systemctl start "$SERVICE_NAME"
sleep 5
if systemctl is-active --quiet "$SERVICE_NAME"; then
    print_ok "سرویس روشن شد"
else
    print_err "سرویس روشن نشد — لاگ‌ها:"
    journalctl -u "$SERVICE_NAME" --since "10 seconds ago" --no-pager | tail -20
    exit 1
fi

# ─── Show final status ─────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
print_ok "نصب کامل شد!"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "📊 آخرین لاگ‌ها:"
journalctl -u "$SERVICE_NAME" --since "10 seconds ago" --no-pager | tail -10
echo ""
echo "🤖 ربات تلگرام:"
echo "   با آیدی $ADMIN_ID_INPUT مالک هستی — /start بزن"
echo ""
if [ -n "$PANEL_DOMAIN_INPUT" ]; then
    echo "🌐 پنل وب:"
    echo "   https://$PANEL_DOMAIN_INPUT/u/login.html"
    echo "   https://$PANEL_DOMAIN_INPUT/app/login.html"
else
    echo "🌐 پنل وب (localhost):"
    echo "   http://localhost:8000/u/login.html"
    echo "   http://localhost:8000/app/login.html"
fi
echo ""
echo "📋 مراحل بعدی:"
echo "   ۱. /start بزن تو تلگرام"
echo "   ۲. «👤 حساب کاربری» → «📱 لاگین کردن سلف»"
echo "   ۳. شماره موبایل + کد تلگرام بزن"
echo "   ۴. اگه ۲FA داری، پسورد بزن"
echo ""
echo "🔧 برای آپدیت خودکار:"
echo "   /start → 🎛 پنل مدیریت → 🔄 آپدیت و ورژن → 🟢 آپدیت خودکار: فعال"
echo ""
echo "📞 پشتیبانی: @CiaNetOwner"
