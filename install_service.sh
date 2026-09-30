#!/bin/bash
# ══════════════════════════════════════════════════════════
#  Selfbot Auto-Install & Systemd Setup
#  کافیه این رو اجرا کنی تا ربات همیشه روشن بمونه
# ══════════════════════════════════════════════════════════

set -e

# ─── رنگ‌ها ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ─── چک کاربر ───
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ لطفاً با sudo یا root اجرا کن:${NC}"
    echo "   sudo bash install_service.sh"
    exit 1
fi

echo -e "${BLUE}╔═══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🚀 نصب Selfbot به عنوان Systemd     ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════╝${NC}"
echo ""

# ─── پیدا کردن مسیر پروژه ───
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo -e "${GREEN}📂 مسیر پروژه:${NC} $SCRIPT_DIR"

if [ ! -f "$SCRIPT_DIR/main.py" ]; then
    echo -e "${RED}❌ main.py پیدا نشد!${NC}"
    echo "   اسکریپت رو داخل پوشه‌ی پروژه اجرا کن."
    exit 1
fi

# ─── پیدا کردن python3 ───
PYTHON_BIN=$(which python3)
if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}❌ python3 نصب نیست!${NC}"
    apt update && apt install -y python3 python3-pip
    PYTHON_BIN=$(which python3)
fi
echo -e "${GREEN}🐍 Python:${NC} $PYTHON_BIN"

# ─── نصب requirements ───
echo -e "${YELLOW}📦 نصب requirements...${NC}"
cd "$SCRIPT_DIR"
$PYTHON_BIN -m pip install -r requirements.txt 2>&1 | tail -5 || {
    echo -e "${RED}❌ pip install شکست خورد!${NC}"
    exit 1
}

# ─── ساخت env file ───
ENV_FILE="/etc/selfbot.env"
if [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}⚠️  فایل env از قبل وجود داره:${NC} $ENV_FILE"
    echo "   برای حفظ مقادیر فعلی، تغییرش نمی‌دم."
else
    echo -e "${YELLOW}📝 ساخت فایل env...${NC}"
    read -p "   API_ID: " API_ID
    read -p "   API_HASH: " API_HASH
    read -p "   ADMIN_BOT_TOKEN: " ADMIN_BOT_TOKEN
    read -p "   ADMIN_ID: " ADMIN_ID
    read -p "   HELPER_BOT_TOKEN (اختیاری، Enter برای رد): " HELPER_BOT_TOKEN

    cat > "$ENV_FILE" <<EOF
API_ID=$API_ID
API_HASH=$API_HASH
ADMIN_BOT_TOKEN=$ADMIN_BOT_TOKEN
ADMIN_ID=$ADMIN_ID
EOF
    if [ -n "$HELPER_BOT_TOKEN" ]; then
        echo "HELPER_BOT_TOKEN=$HELPER_BOT_TOKEN" >> "$ENV_FILE"
    fi
    chmod 600 "$ENV_FILE"
    echo -e "${GREEN}✅ env file ساخته شد${NC}"
fi

# ─── ساخت systemd service ───
SERVICE_FILE="/etc/systemd/system/selfbot.service"
echo -e "${YELLOW}⚙️  ساخت systemd service...${NC}"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Telegram Selfbot SaaS Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN main.py all
Restart=always
RestartSec=10
StartLimitBurst=10
StartLimitIntervalSec=300

StandardOutput=journal
StandardError=journal
SyslogIdentifier=selfbot

LimitNOFILE=65535
OOMScoreAdjust=-100

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}✅ service file ساخته شد${NC}"

# ─── ساخت watchdog (اختیاری) ───
WATCHDOG="$SCRIPT_DIR/watchdog.sh"
cat > "$WATCHDOG" <<'EOF'
#!/bin/bash
# اگه ربات بیش از ۳۰ ثانیه پاسخ نده → ری‌استارتش کن
SERVICE="selfbot.service"
if ! systemctl is-active --quiet "$SERVICE"; then
    echo "$(date): $SERVICE is not active, restarting..." >> /var/log/selfbot-watchdog.log
    systemctl restart "$SERVICE"
    exit 0
fi

# چک کن پروسه‌ی پایتون هست
if ! pgrep -f "python3 main.py all" > /dev/null; then
    echo "$(date): python3 process not found, restarting..." >> /var/log/selfbot-watchdog.log
    systemctl restart "$SERVICE"
fi
EOF
chmod +x "$WATCHDOG"

# ─── فعال‌سازی ───
echo -e "${YELLOW}🔄 فعال‌سازی service...${NC}"
systemctl daemon-reload
systemctl enable selfbot
systemctl start selfbot

sleep 2

# ─── نمایش وضعیت ───
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ نصب تمام شد!                    ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📊 وضعیت:${NC}"
systemctl status selfbot --no-pager -l | head -15
echo ""
echo -e "${BLUE}🛠  دستورات مفید:${NC}"
echo "   لاگ real-time:    sudo journalctl -u selfbot -f"
echo "   ری‌استارت:        sudo systemctl restart selfbot"
echo "   خاموش:            sudo systemctl stop selfbot"
echo "   روشن:             sudo systemctl start selfbot"
echo "   وضعیت:            sudo systemctl status selfbot"
echo ""
echo -e "${YELLOW}🔥 حالا ربات حتی بعد از ری‌استارت سرور هم روشن می‌شه!${NC}"
