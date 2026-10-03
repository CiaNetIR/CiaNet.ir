#!/bin/bash
# ══════════════════════════════════════════════════════════
#  Selfbot Auto-Install & Systemd Setup
#  کافیه این رو اجرا کنی تا ربات همیشه روشن بمونه
# ══════════════════════════════════════════════════════════

set -e
set -o pipefail

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

# ─── ساخت کاربر سرویس (non-root) ───
SERVICE_USER="cianet"
SERVICE_GROUP="cianet"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo -e "${YELLOW}👤 ساخت کاربر سرویس: ${SERVICE_USER}${NC}"
    useradd --system --shell /usr/sbin/nologin --home "$SCRIPT_DIR" "$SERVICE_USER" || {
        echo -e "${RED}❌ ساخت کاربر ${SERVICE_USER} شکست خورد!${NC}"
        exit 1
    }
else
    echo -e "${GREEN}👤 کاربر ${SERVICE_USER} از قبل وجود داره${NC}"
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
    chown "$SERVICE_USER:$SERVICE_GROUP" "$ENV_FILE" 2>/dev/null || true
    echo -e "${GREEN}✅ env file ساخته شد${NC}"
fi
if [ -f "$ENV_FILE" ]; then
    chown "$SERVICE_USER:$SERVICE_GROUP" "$ENV_FILE" 2>/dev/null || true
    chmod 600 "$ENV_FILE"
fi

# ─── ساخت systemd service ───
SERVICE_FILE="/etc/systemd/system/selfbot.service"
echo -e "${YELLOW}⚙️  ساخت systemd service...${NC}"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Telegram Selfbot SaaS Panel
After=network-online.target
Wants=network-online.target
StartLimitBurst=10
StartLimitIntervalSec=300

[Service]
Type=simple
User=cianet
Group=cianet
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN main.py all
Restart=always
RestartSec=10

StandardOutput=journal
StandardError=journal
SyslogIdentifier=selfbot

LimitNOFILE=65535
OOMScoreAdjust=-100

[Install]
WantedBy=multi-user.target
EOF

# محدودسازی دسترسی فایل‌های حساس به کاربر سرویس (سشن‌ها/کانفیگ/بکاپ‌ها)
# PATCH (v2.5.2): اگه config.json وجود نداره، یه فایل خالی معتبر بساز
# تا ربات در حالت "all" به‌جای interactive add_account، منتظر بمونه.
if [ ! -f "$SCRIPT_DIR/config.json" ]; then
    echo '{}' > "$SCRIPT_DIR/config.json"
fi
chown -R cianet:cianet "$SCRIPT_DIR/sessions" "$SCRIPT_DIR/downloads" "$SCRIPT_DIR/tracker_media" "$SCRIPT_DIR/bot_data.db" "$SCRIPT_DIR/saas.db" "$SCRIPT_DIR/config.json" 2>/dev/null || true
chmod 700 "$SCRIPT_DIR/sessions" "$SCRIPT_DIR/downloads" "$SCRIPT_DIR/tracker_media" 2>/dev/null || true
chmod 600 "$SCRIPT_DIR/bot_data.db" "$SCRIPT_DIR/saas.db" "$SCRIPT_DIR/config.json" 2>/dev/null || true

# محدودسازی دسترسی فایل‌های سشن موجود به 600
if [ -d "$SCRIPT_DIR/sessions" ]; then
    find "$SCRIPT_DIR/sessions" -type f -name "*.session*" -exec chmod 600 {} \; 2>/dev/null || true
fi

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

# ─── مالکیت دایرکتوری پروژه برای کاربر سرویس ───
echo -e "${YELLOW}🔧 تنظیم مالکیت فایل‌ها برای ${SERVICE_USER}...${NC}"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$SCRIPT_DIR" 2>/dev/null || {
    echo -e "${YELLOW}⚠️  chown کامل شکست خورد؛ حداقل فایل‌های حساس را محدود می‌کنم${NC}"
    chown "$SERVICE_USER:$SERVICE_GROUP" "$SCRIPT_DIR/main.py" "$SCRIPT_DIR/requirements.txt" 2>/dev/null || true
}

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
