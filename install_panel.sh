#!/bin/bash
# ══════════════════════════════════════════════════════════
#  CiaNet Web Panel — Install Script
#  سرویس systemd برای FastAPI backend روی port 8000
#  + nginx config برای reverse proxy از 443
# ══════════════════════════════════════════════════════════

set -e
set -o pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ لطفاً با sudo اجرا کن:${NC}"
    echo "   sudo bash install_panel.sh"
    exit 1
fi

echo -e "${BLUE}╔═══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🌐 نصب پنل وب CiaNet              ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════╝${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$SCRIPT_DIR/web_panel.py" ]; then
    echo -e "${RED}❌ web_panel.py پیدا نشد!${NC}"
    exit 1
fi

SERVICE_USER="cianet"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  کاربر cianet وجود نداره — اول install_service.sh رو اجرا کن${NC}"
    exit 1
fi

# ─── Install web panel Python deps ───
echo -e "${YELLOW}📦 نصب dependencies پنل وب...${NC}"
cd "$SCRIPT_DIR"
PYTHON_BIN=$(which python3)
$PYTHON_BIN -m pip install fastapi "uvicorn[standard]" pydantic "passlib[bcrypt]" python-multipart 2>&1 | tail -3

# ─── Generate password hash if not set ───
ENV_FILE="/etc/cianet.env"
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}📝 ساخت env file...${NC}"
    touch "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi

# اگر PANEL_ADMIN_PASS_HASH در env نیست، بپرس
if ! grep -q "PANEL_ADMIN_PASS_HASH" "$ENV_FILE" 2>/dev/null; then
    echo ""
    echo -e "${YELLOW}🔐 تنظیم پسورد ورود به پنل وب:${NC}"
    read -s -p "   Password: " PANEL_PASS
    echo ""
    if [ -z "$PANEL_PASS" ]; then
        echo -e "${RED}❌ Password نمی‌تونه خالی باشه${NC}"
        exit 1
    fi
    # Generate bcrypt hash
    PANEL_PASS_HASH=$($PYTHON_BIN -c "from passlib.hash import bcrypt; print(bcrypt.hash('$PANEL_PASS'))" 2>/dev/null)
    if [ -z "$PANEL_PASS_HASH" ]; then
        echo -e "${RED}❌ تولید hash ناموفق بود${NC}"
        exit 1
    fi
    # اگه PANEL_ADMIN_USER تنظیم نشده، default admin
    if ! grep -q "PANEL_ADMIN_USER" "$ENV_FILE" 2>/dev/null; then
        read -p "   Username (default: admin): " PANEL_USER
        PANEL_USER="${PANEL_USER:-admin}"
        echo "PANEL_ADMIN_USER=$PANEL_USER" >> "$ENV_FILE"
    fi
    echo "PANEL_ADMIN_PASS_HASH=$PANEL_PASS_HASH" >> "$ENV_FILE"
    # Session secret
    SESSION_SECRET=$($PYTHON_BIN -c "import secrets; print(secrets.token_hex(32))")
    echo "PANEL_SESSION_SECRET=$SESSION_SECRET" >> "$ENV_FILE"
    echo -e "${GREEN}✅ پسورد تنظیم شد${NC}"
else
    echo -e "${GREEN}✅ پسورد از قبل تنظیم شده${NC}"
fi

# اگر PANEL_CORS_ORIGINS تنظیم نشده، default localhost:3000
if ! grep -q "PANEL_CORS_ORIGINS" "$ENV_FILE" 2>/dev/null; then
    echo "PANEL_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000" >> "$ENV_FILE"
fi

chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# ─── systemd service ───
SERVICE_FILE="/etc/systemd/system/cianet-panel.service"
echo -e "${YELLOW}⚙️  ساخت systemd service...${NC}"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CiaNet Web Panel (FastAPI backend on port 8000)
After=network-online.target cianet.service
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN -m uvicorn web_panel:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=10
StartLimitBurst=10
StartLimitIntervalSec=300

StandardOutput=journal
StandardError=journal
SyslogIdentifier=cianet-panel

LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}✅ service file ساخته شد${NC}"

# ─── nginx config (optional) ───
NGINX_CONF="/etc/nginx/sites-available/cianet-panel"
NGINX_LINK="/etc/nginx/sites-enabled/cianet-panel"

if command -v nginx >/dev/null 2>&1; then
    echo ""
    echo -e "${YELLOW}🌐 nginx پیدا شد — ایجاد config...${NC}"
    read -p "   Domain or IP for panel (مثلاً panel.cianet.ir یا 127.0.0.1): " PANEL_DOMAIN
    PANEL_DOMAIN="${PANEL_DOMAIN:-panel.cianet.ir}"
    read -p "   Enable HTTPS via Let's Encrypt? (y/N): " ENABLE_SSL

    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

    if [ "$ENABLE_SSL" = "y" ] || [ "$ENABLE_SSL" = "Y" ]; then
        cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name $PANEL_DOMAIN;
    # Redirect HTTP → HTTPS
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $PANEL_DOMAIN;

    # SSL — توسط certbot --nginx اضافه می‌شه
    # ssl_certificate /etc/letsencrypt/live/$PANEL_DOMAIN/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/$PANEL_DOMAIN/privkey.pem;

    # Frontend (Next.js) on port 3000
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
    }

    # Backend API (FastAPI) on port 8000
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
        ln -sf "$NGINX_CONF" "$NGINX_LINK"
        echo -e "${YELLOW}⚠️  nginx config ساخته شد. برای SSL اجرا کن:${NC}"
        echo "   sudo certbot --nginx -d $PANEL_DOMAIN"
    else
        cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name $PANEL_DOMAIN;

    # Frontend (Next.js) on port 3000
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
    }

    # Backend API (FastAPI) on port 8000
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
        ln -sf "$NGINX_CONF" "$NGINX_LINK"
    fi
    nginx -t 2>&1 | tail -5
    systemctl reload nginx
    echo -e "${GREEN}✅ nginx config اعمال شد${NC}"
else
    echo -e "${YELLOW}⚠️  nginx نصب نیست — پنل روی port 8000 مستقیم در دسترس خواهد بود${NC}"
    echo -e "${YELLOW}   برای دسترسی از بیرون، nginx یا caddy نصب کن${NC}"
fi

# ─── Build frontend ───
if [ -f "$SCRIPT_DIR/web/package.json" ]; then
    echo ""
    echo -e "${YELLOW}🔨 build frontend Next.js...${NC}"
    cd "$SCRIPT_DIR/web"
    if ! command -v npm >/dev/null 2>&1; then
        echo -e "${YELLOW}📦 نصب Node.js...${NC}"
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y nodejs
    fi
    npm install --silent 2>&1 | tail -5
    npm run build 2>&1 | tail -5
    cd "$SCRIPT_DIR"
fi

# ─── Start services ───
echo -e "${YELLOW}🔄 فعال‌سازی services...${NC}"
systemctl daemon-reload
systemctl enable cianet-panel
systemctl restart cianet-panel

sleep 3
systemctl is-active --quiet cianet-panel && echo -e "${GREEN}✅ cianet-panel running${NC}" || {
    echo -e "${RED}❌ cianet-panel failed to start — checking logs...${NC}"
    journalctl -u cianet-panel --no-pager -n 20
    exit 1
}

# ─── Status ───
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ نصب پنل وب تمام شد!              ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📊 وضعیت:${NC}"
systemctl status cianet-panel --no-pager -l | head -10
echo ""
echo -e "${BLUE}🛠  دستورات مفید:${NC}"
echo "   لاگ real-time:    sudo journalctl -u cianet-panel -f"
echo "   ری‌استارت:        sudo systemctl restart cianet-panel"
echo "   وضعیت:            sudo systemctl status cianet-panel"
echo ""
echo -e "${BLUE}🌐 دسترسی:${NC}"
if [ -f "$NGINX_LINK" ]; then
    echo "   Panel URL:        http://$(grep -m1 server_name $NGINX_CONF | awk '{print $2}' | tr -d ';')"
else
    echo "   Backend API:     http://localhost:8000/api/docs"
    echo "   Frontend (dev):   http://localhost:3000"
fi
echo ""
echo -e "${YELLOW}💡 برای build frontend:${NC}"
echo "   cd $SCRIPT_DIR/web && npm install && npm run build && npm start"
