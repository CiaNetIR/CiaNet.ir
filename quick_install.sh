#!/bin/bash
# ══════════════════════════════════════════════════════════
#  CiaNet — Quick Install (One-Shot)
#  نصب کامل با یک دستور — همه‌چیز در پس‌زمینه
# ══════════════════════════════════════════════════════════
#
#  استفاده:
#    sudo bash quick_install.sh
#    یا با env vars:
#    sudo API_ID=... API_HASH=... ADMIN_BOT_TOKEN=... ADMIN_ID=... bash quick_install.sh
#
#  این اسکریپت:
#    ۱. clone می‌کنه (اگه وجود نداره)
#    ۲. pip + venv نصب می‌کنه
#    ۳. env file می‌سازه
#    ۴. config.json خالی می‌سازه
#    ۵. systemd service selfbot + cianet-panel می‌سازه
#    ۶. هر دو سرویس رو start می‌کنه
#    ۷. پنل وب در port 8000 آماده می‌شه
# ══════════════════════════════════════════════════════════

set -e
set -o pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="/opt/cianet"
SERVICE_USER="cianet"

# ─── چک root ───
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ با sudo اجرا کن:${NC} sudo bash quick_install.sh"
    exit 1
fi

echo -e "${BLUE}╔═══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🚀 CiaNet Quick Install              ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════╝${NC}"
echo ""

# ─── ۱. Clone (اگه وجود نداره) ───
if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo -e "${YELLOW}۱. Clone پروژه...${NC}"
    git clone https://github.com/DLSDT/CiaNet.ir.git "$INSTALL_DIR" 2>&1 | tail -3
    git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true
else
    echo -e "${GREEN}۱. پروژه از قبل وجود داره — pull...${NC}"
    cd "$INSTALL_DIR"
    git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true
    git pull origin main 2>&1 | tail -3
fi

cd "$INSTALL_DIR"

# ─── ۲. نصب pip + venv + python3 ───
echo -e "${YELLOW}۲. نصب پیش‌نیازها...${NC}"
apt-get update -qq 2>/dev/null || true
apt-get install -y -qq python3 python3-pip python3-venv 2>&1 | tail -3

PYTHON_BIN=$(which python3)

# ─── ۳. ساخت کاربر cianet (اگه وجود نداره) ───
echo -e "${YELLOW}۳. ساخت کاربر سرویس...${NC}"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --shell /usr/sbin/nologin --home "$INSTALL_DIR" "$SERVICE_USER"
    echo -e "${GREEN}   کاربر $SERVICE_USER ساخته شد${NC}"
else
    echo -e "${GREEN}   کاربر $SERVICE_USER از قبل وجود داره${NC}"
fi

# ─── ۴. venv + requirements ───
echo -e "${YELLOW}۴. ساخت venv و نصب requirements...${NC}"
VENV_DIR="$INSTALL_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    $PYTHON_BIN -m venv "$VENV_DIR" 2>&1 | tail -2
fi
VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
$VENV_PY -m pip install --upgrade pip --quiet 2>&1 | tail -1
$VENV_PIP install -r "$INSTALL_DIR/requirements.txt" --quiet 2>&1 | tail -3
echo -e "${GREEN}   venv آماده${NC}"

# ─── انتخاب پسورد پنل (حذف پسورد پیش‌فرض hardcode شده — P1-8) ───
# اگه PANEL_ADMIN_PASS از سمت کاربر تنظیم شده باشه از همون استفاده می‌شه.
# در غیر این صورت پسورد تصادفی ۲۴ کاراکتری ساخته می‌شه و فقط همین یک‌بار
# در کنسول نصب نمایش داده می‌شه. در env file فقط hash ذخیره می‌شه (مثل قبل).
resolve_panel_pass() {
    if [ -n "$PANEL_ADMIN_PASS" ]; then
        PANEL_PASS="$PANEL_ADMIN_PASS"
        PANEL_PASS_SOURCE="user"
        return 0
    fi
    PANEL_PASS=""
    if command -v openssl >/dev/null 2>&1; then
        # P2-8: «|| true» تا اگر openssl موجود باشه ولی rand شکست بخوره،
        # set -e + pipefail کل اسکریپت رو سایلنت متوقف نکنه و مسیر
        # fallback (urandom) واقعاً قابل‌دسترس باشه.
        PANEL_PASS=$(openssl rand -hex 32 2>/dev/null | cut -c1-24 || true)
    fi
    if [ -z "$PANEL_PASS" ]; then
        PANEL_PASS=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')
    fi
    if [ -z "$PANEL_PASS" ] || [ "${#PANEL_PASS}" -lt 24 ]; then
        echo -e "${RED}❌ ساخت پسورد تصادفی برای پنل ناموفق بود${NC}"
        exit 1
    fi
    PANEL_PASS_SOURCE="random"
    echo ""
    echo -e "${YELLOW}🔐 پسورد تصادفی برای پنل وب ساخته شد — فقط همین یک‌بار نمایش داده می‌شه، حتماً یادداشتش کن:${NC}"
    echo -e "   👤 username: admin"
    echo -e "   🔑 password: ${BLUE}$PANEL_PASS${NC}"
    echo ""
}

# ─── ۵. env file ───
echo -e "${YELLOW}۵. ساخت env file...${NC}"
ENV_FILE="/etc/cianet.env"
# اگه env vars از environment آمده
if [ -n "$API_ID" ] && [ -n "$API_HASH" ] && [ -n "$ADMIN_BOT_TOKEN" ] && [ -n "$ADMIN_ID" ]; then
    resolve_panel_pass
    PANEL_HASH="sha256:$(echo -n "$PANEL_PASS" | sha256sum | cut -d' ' -f1)"
    SECRET=$(head -c64 /dev/urandom | xxd -p | tr -d '\n')
    cat > "$ENV_FILE" <<EOF
API_ID=$API_ID
API_HASH=$API_HASH
ADMIN_BOT_TOKEN=$ADMIN_BOT_TOKEN
ADMIN_ID=$ADMIN_ID
PANEL_ADMIN_USER=admin
PANEL_ADMIN_PASS_HASH=$PANEL_HASH
PANEL_SESSION_SECRET=$SECRET
PANEL_CORS_ORIGINS=http://localhost:8000
EOF
    echo -e "${GREEN}   env file با متغیرهای شما ساخته شد${NC}"
elif [ -f "$ENV_FILE" ]; then
    echo -e "${GREEN}   env file از قبل وجود داره${NC}"
    PANEL_PASS_SOURCE="existing"
else
    # interactive — اگه stdin بازه
    echo -e "${YELLOW}   متغیرهای محیطی وارد نشده. interactive...${NC}"
    read -p "   API_ID: " API_ID
    read -p "   API_HASH: " API_HASH
    read -p "   ADMIN_BOT_TOKEN: " ADMIN_BOT_TOKEN
    read -p "   ADMIN_ID: " ADMIN_ID
    resolve_panel_pass
    PANEL_HASH="sha256:$(echo -n "$PANEL_PASS" | sha256sum | cut -d' ' -f1)"
    SECRET=$(head -c64 /dev/urandom | xxd -p | tr -d '\n')
    cat > "$ENV_FILE" <<EOF
API_ID=$API_ID
API_HASH=$API_HASH
ADMIN_BOT_TOKEN=$ADMIN_BOT_TOKEN
ADMIN_ID=$ADMIN_ID
PANEL_ADMIN_USER=admin
PANEL_ADMIN_PASS_HASH=$PANEL_HASH
PANEL_SESSION_SECRET=$SECRET
PANEL_CORS_ORIGINS=http://localhost:8000
EOF
    if [ "$PANEL_PASS_SOURCE" = "random" ]; then
        echo -e "${GREEN}   env file ساخته شد (hash پسورد پنل در env ذخیره شد)${NC}"
    else
        echo -e "${GREEN}   env file ساخته شد (پسورد پنل: $PANEL_PASS)${NC}"
    fi
fi
chmod 600 "$ENV_FILE"

# همچنین برای install_service.sh که /etc/selfbot.env می‌خونه:
cp "$ENV_FILE" /etc/selfbot.env 2>/dev/null || true
chmod 600 /etc/selfbot.env

# ─── ۶. config.json ───
echo -e "${YELLOW}۶. ساخت config.json...${NC}"
if [ ! -f "$INSTALL_DIR/config.json" ]; then
    echo '{}' > "$INSTALL_DIR/config.json"
fi

# ─── ۷. مالکیت و permission ───
echo -e "${YELLOW}۷. تنظیم permission...${NC}"
mkdir -p "$INSTALL_DIR/sessions" "$INSTALL_DIR/data"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 700 "$INSTALL_DIR/sessions"
chmod 600 "$INSTALL_DIR/config.json" "$ENV_FILE" /etc/selfbot.env 2>/dev/null

# ─── ۸. systemd: selfbot ───
echo -e "${YELLOW}۸. ساخت systemd: selfbot.service...${NC}"
cat > /etc/systemd/system/selfbot.service <<EOF
[Unit]
Description=CiaNet Telegram Selfbot
After=network-online.target
Wants=network-online.target
StartLimitBurst=10
StartLimitIntervalSec=300

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=/etc/selfbot.env
ExecStart=$VENV_PY main.py all
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

# ─── ۹. systemd: cianet-panel ───
echo -e "${YELLOW}۹. ساخت systemd: cianet-panel.service...${NC}"
# ⚠️ workers=1 اجباریه: سشن‌های پنل در حافظه‌ی هر پروسه نگه داشته می‌شن
# (طراحی single-instance — rules §18.2). با workers>1 درخواست‌ها بین
# پروسه‌ها پخش می‌شن → سشن گم می‌شه → 401 تصادفی برای ادمین.
cat > /etc/systemd/system/cianet-panel.service <<EOF
[Unit]
Description=CiaNet Web Panel (FastAPI on port 8000)
After=network-online.target selfbot.service
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_PY -m uvicorn web_panel:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=10

StandardOutput=journal
StandardError=journal
SyslogIdentifier=cianet-panel

LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

# ─── ۱۰. Start services ───
echo -e "${YELLOW}۱۰. فعال‌سازی سرویس‌ها...${NC}"
systemctl daemon-reload
systemctl enable selfbot cianet-panel
systemctl restart selfbot cianet-panel
sleep 3

# ─── ۱۱. Status ───
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ نصب کامل شد!                     ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""

echo -e "${BLUE}📊 وضعیت سرویس‌ها:${NC}"
echo ""
echo "── selfbot ──"
systemctl is-active --quiet selfbot && echo -e "  ${GREEN}✅ فعال${NC}" || echo -e "  ${RED}❌ ناموفق${NC}"
echo "── cianet-panel ──"
systemctl is-active --quiet cianet-panel && echo -e "  ${GREEN}✅ فعال${NC}" || echo -e "  ${RED}❌ ناموفق${NC}"

# Health check
echo ""
echo -e "${BLUE}🌐 پنل وب:${NC}"
if curl -s http://localhost:8000/api/health 2>/dev/null | grep -q "ok"; then
    echo -e "  ${GREEN}✅ API health: OK${NC}"
    echo ""
    SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "SERVER_IP")
    echo -e "  📎 URL: ${BLUE}http://$SERVER_IP:8000/app/login.html${NC}"
    echo -e "  👤 username: ${BLUE}admin${NC}"
    if [ "$PANEL_PASS_SOURCE" = "random" ]; then
        echo -e "  🔑 password: ${YELLOW}پسورد تصادفی که در مرحله‌ی ۵ نمایش داده شد${NC}"
    elif [ "$PANEL_PASS_SOURCE" = "user" ]; then
        echo -e "  🔑 password: ${BLUE}$PANEL_ADMIN_PASS${NC}"
    else
        echo -e "  🔑 password: ${YELLOW}پسورد پنل از نصب قبلی بدون تغییر باقی مونده${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠️  پنل هنوز بالا نیومده — چند ثانیه صبر کن:${NC}"
    echo "  curl http://localhost:8000/api/health"
fi

echo ""
echo -e "${BLUE}🛠  دستورات:${NC}"
echo "   لاگ ربات:      sudo journalctl -u selfbot -f"
echo "   لاگ پنل:       sudo journalctl -u cianet-panel -f"
echo "   ری‌استارت:     sudo systemctl restart selfbot cianet-panel"
echo "   حذف کامل:      sudo bash $INSTALL_DIR/uninstall.sh"
echo ""
echo -e "${YELLOW}🔥 ربات آماده است! از پنل وب اکانت اضافه کن.${NC}"
