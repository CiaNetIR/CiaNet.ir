#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  CiaNet.ir Selfbot — One-shot Installer
#  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  یک دستور. همه چیز خودکار.
#  نصب + کانفیگ + systemd + watchdog + auto-update
#  سلف هرگز خاموش نمی‌شه.
#
#  Usage:
#    curl -sSL https://raw.githubusercontent.com/DLSDT/CiaNet.ir/main/setup.sh | sudo bash
#
#  یا با env vars (non-interactive):
#    API_ID=12345 API_HASH=abc ADMIN_BOT_TOKEN=... ADMIN_ID=123 \
#      curl -sSL ... | sudo bash -s -- --non-interactive
# ══════════════════════════════════════════════════════════════

set -e

# ─── Constants ───
REPO_URL="https://github.com/DLSDT/CiaNet.ir.git"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_DIR="/opt/cianet"
SERVICE_NAME="cianet"
ENV_FILE="/etc/cianet.env"
WATCHDOG_DIR="/opt/cianet-watchdog"

# رنگ‌ها
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── Banner ───
echo -e "${PURPLE}"
cat << 'EOF'
   ╔════════════════════════════════════════════════════╗
   ║                                                    ║
   ║      ▄████▄  ██▓ ▄▄▄      ███▄    █ ▓█████ ▄▄▄    ║
   ║     ▒██▀ ▀█  ▓██▒▒████▄    ██ ▀█   █ ▓█   ▀ ▒████▄  ║
   ║     ▒▓█    ▄ ▒██▒▒██  ▀█▄  ▓██  ▀█ ██▒▒███   ▒██  ▀█▄║
   ║     ▒▓▓▄ ▄██▒░██░░██▄▄▄▄██ ▓██▒  ▐▌██▒▒▓█  ▄ ░██▄▄▄▄██║
   ║     ▒ ▓███▀ ░██░ ▓█   ▓██▒▒██░   ▓██░░▒████▒ ▓█   ▓██║
   ║                                                    ║
   ║       One-shot Installer · نصب یک‌دستوری            ║
   ╚════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# ─── Pre-flight checks ───
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ لطفاً با sudo اجرا کن:${NC}"
    echo "   curl -sSL ... | sudo bash"
    exit 1
fi

# OS detection
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo -e "${RED}❌ OS شناسایی نشد.${NC}"
    exit 1
fi
case "$OS" in
    ubuntu|debian) PKG_MGR="apt" ;;
    centos|rhel|fedora|rocky|almalinux) PKG_MGR="yum" ;;
    arch) PKG_MGR="pacman" ;;
    *) PKG_MGR="apt" ;;  # fallback
esac
echo -e "${CYAN}ℹ️  OS: $OS · Package Manager: $PKG_MGR${NC}"

# ─── Args ───
NON_INTERACTIVE=false
for arg in "$@"; do
    case $arg in
        --non-interactive|-y) NON_INTERACTIVE=true ;;
    esac
done

# ─── Step 1: Install system deps ───
echo -e "${BLUE}[1/6]${NC} 📦 نصب پیش‌نیازهای سیستمی..."
case $PKG_MGR in
    apt)
        apt update -qq
        apt install -y -qq python3 python3-pip python3-venv git curl wget systemd
        ;;
    yum)
        yum install -y python3 python3-pip git curl wget systemd
        ;;
    pacman)
        pacman -Sy --noconfirm python python-pip git curl wget systemd
        ;;
esac
echo -e "  ${GREEN}✓${NC} python3 $(python3 --version) · git $(git --version | cut -d' ' -f3)"

# ─── Step 2: Clone / Update repo ───
echo -e "${BLUE}[2/6]${NC} 📂 کلون کردن مخزن..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "  ${YELLOW}ℹ️${NC}  پوشه موجوده، فقط آپدیت می‌کنم..."
    cd "$INSTALL_DIR"
    git fetch origin
    git reset --hard origin/$REPO_BRANCH
    echo -e "  ${GREEN}✓${NC} آپدیت شد"
else
    if [ -d "$INSTALL_DIR" ]; then
        echo -e "  ${YELLOW}⚠️${NC}  $INSTALL_DIR موجوده ولی git نیست. بکاپ و کلون مجدد..."
        mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%s)"
    fi
    git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    echo -e "  ${GREEN}✓${NC} کلون شد"
fi

cd "$INSTALL_DIR"

# ─── Step 3: Python venv + deps ───
echo -e "${BLUE}[3/6]${NC} 🐍 ساخت محیط مجازی Python..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo -e "  ${GREEN}✓${NC} venv ساخته و deps نصب شد"

# ─── Step 4: Environment configuration ───
echo -e "${BLUE}[4/6]${NC} 🔧 تنظیم env vars..."

if [ -f "$ENV_FILE" ]; then
    echo -e "  ${YELLOW}ℹ️${NC}  env file موجوده: $ENV_FILE"
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "      استفاده از مقادیر فعلی؟ [Y/n] " use_existing
        if [[ "$use_existing" =~ ^[Yy]$|^$ ]]; then
            source "$ENV_FILE"
        else
            rm -f "$ENV_FILE"
        fi
    fi
fi

# اگه env vars به صورت env داده شدن، استفاده کن
API_ID="${API_ID:-}"
API_HASH="${API_HASH:-}"
ADMIN_BOT_TOKEN="${ADMIN_BOT_TOKEN:-}"
ADMIN_ID="${ADMIN_ID:-}"
HELPER_BOT_TOKEN="${HELPER_BOT_TOKEN:-}"
UPDATE_WEBHOOK_URL="${UPDATE_WEBHOOK_URL:-}"

if [ ! -f "$ENV_FILE" ]; then
    if [ -z "$API_ID" ] && [ "$NON_INTERACTIVE" = false ]; then
        echo ""
        echo -e "${YELLOW}📝 لطفاً اطلاعات زیر رو وارد کن (از ${BLUE}my.telegram.org${YELLOW} و ${BLUE}@BotFather${YELLOW}):${NC}"
        echo ""
        read -p "  API_ID: " API_ID
        read -p "  API_HASH: " API_HASH
        read -p "  ADMIN_BOT_TOKEN (از @BotFather): " ADMIN_BOT_TOKEN
        read -p "  ADMIN_ID (آیدی عددی خودت، از @userinfobot): " ADMIN_ID
        read -p "  HELPER_BOT_TOKEN (اختیاری، Enter برای رد): " HELPER_BOT_TOKEN
    fi

    if [ -z "$API_ID" ] || [ -z "$API_HASH" ] || [ -z "$ADMIN_BOT_TOKEN" ] || [ -z "$ADMIN_ID" ]; then
        echo -e "${RED}❌ API_ID, API_HASH, ADMIN_BOT_TOKEN و ADMIN_ID ضروری هستند.${NC}"
        echo "   یا env vars بفرست، یا interactive اجرا کن."
        exit 1
    fi

    cat > "$ENV_FILE" <<EOF
# CiaNet Selfbot Configuration
# Generated by setup.sh at $(date -Iseconds)
API_ID=$API_ID
API_HASH=$API_HASH
ADMIN_BOT_TOKEN=$ADMIN_BOT_TOKEN
ADMIN_ID=$ADMIN_ID
EOF
    if [ -n "$HELPER_BOT_TOKEN" ]; then
        echo "HELPER_BOT_TOKEN=$HELPER_BOT_TOKEN" >> "$ENV_FILE"
    fi
    chmod 600 "$ENV_FILE"
    echo -e "  ${GREEN}✓${NC} env file ساخته شد (chmod 600)"
fi

# ─── Step 5: Systemd service (main) ───
echo -e "${BLUE}[5/6]${NC} ⚙️  ساخت systemd service..."

# چک کن اگه selfbot.service هست (migration)
if [ -f /etc/systemd/system/selfbot.service ] && [ ! -f /etc/systemd/system/$SERVICE_NAME.service ]; then
    echo -e "  ${YELLOW}ℹ️${NC}  selfbot.service قدیمی پیدا شد، مهاجرت به $SERVICE_NAME..."
    systemctl stop selfbot 2>/dev/null || true
    systemctl disable selfbot 2>/dev/null || true
    mv /etc/systemd/system/selfbot.service /etc/systemd/system/selfbot.service.disabled
fi

cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=CiaNet.ir Telegram Selfbot Panel
Documentation=https://github.com/DLSDT/CiaNet.ir
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$INSTALL_DIR/venv/bin/python3 main.py all
Restart=always
RestartSec=10
StartLimitBurst=20
StartLimitIntervalSec=300

# لاگ به journal
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cianet

# Performance
LimitNOFILE=65535
OOMScoreAdjust=-100
Nice=-5

[Install]
WantedBy=multi-user.target
EOF

# ─── Step 6: Watchdog + Auto-update daemon ───
echo -e "${BLUE}[6/6]${NC} 🐕 ساخت watchdog + auto-updater..."

mkdir -p "$WATCHDOG_DIR"

# 1. Watchdog: اگه سلف مرد، سریع بیدارش کن
cat > $WATCHDOG_DIR/watchdog.sh <<'WATCHDOG_EOF'
#!/bin/bash
# اگه ربات مرد → سریع بیدارش کن
# اگه هنوز start می‌شه → صبر کن
# اگه بیش از N بار fail شد → alert

SERVICE="cianet.service"
LOG="/var/log/cianet-watchdog.log"

if ! systemctl is-active --quiet "$SERVICE"; then
    echo "$(date): $SERVICE inactive, restarting..." >> "$LOG"
    systemctl restart "$SERVICE"
fi
WATCHDOG_EOF
chmod +x $WATCHDOG_DIR/watchdog.sh

# 2. Auto-updater: polling هر ۵ دقیقه + webhook receiver
cat > $WATCHDOG_DIR/auto_update.sh <<'UPDATE_EOF'
#!/bin/bash
# هر ۵ دقیقه چک کنه. اگه آپدیتی بود، pull + restart + notify admins.
# اگه UPDATE_WEBHOOK_URL تنظیم شده، اون رو هم هر ۱ دقیقه چک کن.

INSTALL_DIR="/opt/cianet"
SERVICE="cianet.service"
LOG="/var/log/cianet-auto-update.log"
CURRENT_COMMIT_FILE="$INSTALL_DIR/.last_seen_commit"

cd "$INSTALL_DIR" || exit 1

LAST_COMMIT=$(cat "$CURRENT_COMMIT_FILE" 2>/dev/null || git rev-parse HEAD)
NEW_COMMITS=$(git fetch origin main 2>/dev/null && git log --oneline "$LAST_COMMIT..origin/main" 2>/dev/null)

if [ -n "$NEW_COMMITS" ]; then
    echo "$(date): 📥 آپدیت پیدا شد! $NEW_COMMITS" >> "$LOG"
    # main.py خودش propagation رو handle می‌کنه (signal می‌فرسته)
    # ما فقط pull + restart می‌کنیم
    git pull origin main >> "$LOG" 2>&1
    NEW_COMMIT=$(git rev-parse HEAD)
    echo "$NEW_COMMIT" > "$CURRENT_COMMIT_FILE"
    systemctl restart "$SERVICE" >> "$LOG" 2>&1
    echo "$(date): ✅ آپدیت شد به $NEW_COMMIT" >> "$LOG"
fi
UPDATE_EOF
chmod +x $WATCHDOG_DIR/auto_update.sh

# 3. Webhook receiver (اگه PUBLIC_WEBHOOK_URL تنظیم شده)
if [ -n "$UPDATE_WEBHOOK_URL" ]; then
    cat > $WATCHDOG_DIR/webhook_listener.py <<PYEOF
#!/usr/bin/env python3
"""
Webhook receiver: وقتی GitHub push بشه، این endpoint صدا زده می‌شه.
سلف بلافاصله متوجه می‌شه و auto-pull می‌کنه.

این endpoint رو می‌تونی روی یه reverse proxy (nginx, caddy) ست کنی
یا از یه tunnel مثل cloudflared/ngrok استفاده کنی.

Security: shared secret در URL یا header.
"""
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("CIANET_WEBHOOK_SECRET", "${UPDATE_WEBHOOK_URL}")
INSTALL_DIR = "/opt/cianet"
SERVICE = "cianet.service"
LOG = "/var/log/cianet-webhook.log"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # چک secret در path: /webhook/<secret>
        path_secret = self.path.strip("/").split("/")[-1] if "/" in self.path else ""
        if path_secret != SECRET:
            self.send_response(403)
            self.end_headers()
            return
        # اجرای pull + restart
        with open(LOG, "a") as f:
            f.write(f"{self.log_date_time_string()}: webhook hit\n")
        try:
            subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=INSTALL_DIR, check=True, capture_output=True,
            )
            subprocess.run(
                ["systemctl", "restart", SERVICE],
                check=True, capture_output=True,
            )
            with open(LOG, "a") as f:
                f.write(f"  ✓ pulled and restarted\n")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except subprocess.CalledProcessError as e:
            with open(LOG, "a") as f:
                f.write(f"  ✗ {e.stderr.decode()}\n")
            self.send_response(500)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silent


if __name__ == "__main__":
    port = int(os.environ.get("CIANET_WEBHOOK_PORT", "9876"))
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
PYEOF
    chmod +x $WATCHDOG_DIR/webhook_listener.py
fi

# systemd timer برای auto_update (هر ۵ دقیقه)
cat > /etc/systemd/system/cianet-autoupdate.service <<EOF
[Unit]
Description=CiaNet Auto-Updater
After=network-online.target

[Service]
Type=oneshot
ExecStart=$WATCHDOG_DIR/auto_update.sh
User=root
EOF

cat > /etc/systemd/system/cianet-autoupdate.timer <<EOF
[Unit]
Description=CiaNet Auto-Update Timer (هر ۵ دقیقه)

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

# systemd timer برای watchdog (هر ۱ دقیقه)
cat > /etc/systemd/system/cianet-watchdog.service <<EOF
[Unit]
Description=CiaNet Watchdog
After=network-online.target

[Service]
Type=oneshot
ExecStart=$WATCHDOG_DIR/watchdog.sh
User=root
EOF

cat > /etc/systemd/system/cianet-watchdog.timer <<EOF
[Unit]
Description=CiaNet Watchdog Timer (هر ۱ دقیقه)

[Timer]
OnBootSec=30s
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
EOF

# ─── Activate everything ───
echo ""
echo -e "${YELLOW}🔄 فعال‌سازی همه چیز...${NC}"
systemctl daemon-reload
systemctl enable --now $SERVICE_NAME
systemctl enable --now cianet-watchdog.timer
systemctl enable --now cianet-autoupdate.timer

# چند ثانیه صبر کن
sleep 3

# ─── نمایش وضعیت ───
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                    ║${NC}"
echo -e "${GREEN}║   ✅ نصب CiaNet Selfbot کامل شد!                  ║${NC}"
echo -e "${GREEN}║                                                    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}📊 وضعیت سرویس:${NC}"
systemctl status $SERVICE_NAME --no-pager -l | head -8
echo ""
echo -e "${CYAN}🐕 Watchdog (هر ۱ دقیقه):${NC}"
systemctl status cianet-watchdog.timer --no-pager | head -3
echo ""
echo -e "${CYAN}🔄 Auto-Update (هر ۵ دقیقه):${NC}"
systemctl status cianet-autoupdate.timer --no-pager | head -3
echo ""
echo -e "${CYAN}📂 مسیر نصب:${NC}      $INSTALL_DIR"
echo -e "${CYAN}🔐 env file:${NC}      $ENV_FILE (chmod 600)"
echo -e "${CYAN}📜 لاگ اصلی:${NC}      sudo journalctl -u $SERVICE_NAME -f"
echo -e "${CYAN}📜 لاگ watchdog:${NC}   tail -f /var/log/cianet-watchdog.log"
echo -e "${CYAN}📜 لاگ auto-update:${NC} tail -f /var/log/cianet-auto-update.log"
echo ""
echo -e "${YELLOW}📱 به رباتت برو و /start بزن${NC}"
echo -e "${YELLOW}🔥 ربات هرگز خاموش نمی‌شه (watchdog هر دقیقه چک می‌کنه)${NC}"
echo -e "${YELLOW}🔄 وقتی کد آپدیت بشه، اتوماتیک propagate می‌شه${NC}"
echo ""
echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${PURPLE}  Update channels: polling (5min) ${UPDATE_WEBHOOK_URL:+ + webhook}${NC}"
echo -e "${PURPLE}  Restart: never (watchdog guarantees uptime)${NC}"
echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
