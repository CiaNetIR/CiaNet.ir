#!/bin/bash
# ══════════════════════════════════════════════════════════
#  CiaNet Web Panel — Install Script (v2 — auto-detect)
#  سرویس systemd برای FastAPI backend روی port 8000
#  + nginx config برای reverse proxy از 443
#
#  PATCH (v2.1.1): تشخیص خودکار service name و user
#  - اولین service فعال بین cianet / selfbot رو پیدا می‌کنه
#  - user از همان service رو detect می‌کنه (systemctl show -p User)
#  - اگه هیچ کدام نبود، خودش user cianet می‌سازه
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
echo -e "${BLUE}║   🌐 نصب پنل وب CiaNet (v2)            ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════╝${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$SCRIPT_DIR/web_panel.py" ]; then
    echo -e "${RED}❌ web_panel.py پیدا نشد!${NC}"
    exit 1
fi

# ─── Detect existing CiaNet service ─────────────────────
# Try service names in order: cianet (most common in this deployment),
# selfbot (install_service.sh default), then anything with cianet in name.
EXISTING_SERVICE=""
for svc in cianet selfbot; do
    if systemctl is-enabled --quiet "$svc" 2>/dev/null \
        || systemctl is-active --quiet "$svc" 2>/dev/null; then
        EXISTING_SERVICE="$svc"
        break
    fi
done
# fallback: any unit with cianet in the name
if [ -z "$EXISTING_SERVICE" ]; then
    FOUND=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
            | awk '{print $1}' | grep -i 'cianet\|selfbot' | head -1)
    if [ -n "$FOUND" ]; then
        EXISTING_SERVICE="${FOUND%.service}"
    fi
fi

# Detect service user
SERVICE_USER=""
if [ -n "$EXISTING_SERVICE" ]; then
    echo -e "${GREEN}✓ سرویس موجود پیدا شد: ${EXISTING_SERVICE}.service${NC}"
    SERVICE_USER=$(systemctl show -p User "${EXISTING_SERVICE}.service" 2>/dev/null | cut -d= -f2)
    if [ -z "$SERVICE_USER" ] || [ "$SERVICE_USER" = "" ]; then
        SERVICE_USER="root"
    fi
    echo -e "${GREEN}  user: ${SERVICE_USER}${NC}"
else
    echo -e "${YELLOW}⚠️  هیچ سرویس cianet/selfbot پیدا نشد${NC}"
    echo -e "${YELLOW}   اول install_service.sh رو اجرا کن یا خودت سرویس بساز${NC}"
    echo ""
    read -p "  با این حال ادامه بدیم و user cianet رو بسازیم؟ (y/N): " CONFIRM
    if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
        exit 1
    fi
    SERVICE_USER="cianet"
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
        echo -e "${YELLOW}👤 ساخت کاربر سرویس: ${SERVICE_USER}${NC}"
        useradd --system --shell /usr/sbin/nologin --home "$SCRIPT_DIR" "$SERVICE_USER" || {
            echo -e "${RED}❌ ساخت کاربر ${SERVICE_USER} شکست خورد!${NC}"
            exit 1
        }
    fi
    EXISTING_SERVICE="cianet"  # برای reference در systemd After=
fi

# اگر user پیدا شده root نباشه ولی وجود نداشته باشه، fallback
if [ "$SERVICE_USER" != "root" ] && ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  کاربر ${SERVICE_USER} وجود نداره — استفاده از root${NC}"
    SERVICE_USER="root"
fi

echo ""
echo -e "${BLUE}📊 تنظیمات:${NC}"
echo "  service user:    $SERVICE_USER"
echo "  existing service: $EXISTING_SERVICE"
echo "  install dir:     $SCRIPT_DIR"
echo ""

# ─── Install web panel Python deps (in venv) ───────────────
echo -e "${YELLOW}📦 نصب dependencies پنل وب...${NC}"
cd "$SCRIPT_DIR"
PYTHON_BIN=$(which python3)
# اگه python3.11+ در دسترسه از اون استفاده کن (سریع‌تر)
for p in python3.12 python3.11 python3.10 python3; do
    if command -v "$p" >/dev/null 2>&1; then
        PYTHON_BIN=$(which "$p")
        break
    fi
done
echo "  using: $PYTHON_BIN"

# PATCH (v2.1.2): استفاده از venv به‌جای نصب در system Python.
# این مشکل "Cannot uninstall typing_extensions 4.10.0, RECORD file not
# found" رو حل می‌کنه — وقتی پایتون سیستمی پکیج‌ها رو با apt نصب کرده،
# pip نمی‌تونه uninstall شون کنه. venv هم ایزوله‌تر و امن‌تره.
VENV_DIR="$SCRIPT_DIR/.venv"
echo -e "${YELLOW}🐍 ساخت virtualenv در $VENV_DIR...${NC}"
if [ ! -d "$VENV_DIR" ]; then
    $PYTHON_BIN -m venv "$VENV_DIR" 2>&1 | tail -3 || {
        echo -e "${RED}❌ venv creation شکست خورد${NC}"
        echo -e "${YELLOW}   احتمالاً python3-venv نصب نیست. نصب کن:${NC}"
        echo "   sudo apt install -y python3-venv python3.12-venv"
        exit 1
    }
fi
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Upgrade pip در venv (بدون مشکل uninstall)
echo "  upgrading pip in venv..."
$VENV_PYTHON -m pip install --upgrade pip --quiet 2>&1 | tail -2 || true

# نصب requirements کامل (شامل telethon هم) در venv
echo "  installing requirements..."
$VENV_PIP install -r "$SCRIPT_DIR/requirements.txt" --quiet 2>&1 | tail -5 || {
    echo -e "${RED}❌ pip install شکست خورد!${NC}"
    echo -e "${YELLOW}   لگ کامل:${NC}"
    $VENV_PIP install -r "$SCRIPT_DIR/requirements.txt" 2>&1 | tail -30
    exit 1
}

# اگر telethon از قبل در system نصب بوده و در venv هم لازمه، نصب کن
# (مثلاً main.py telethon رو import می‌کنه)
if ! $VENV_PYTHON -c "import telethon" 2>/dev/null; then
    echo "  installing telethon..."
    $VENV_PIP install "telethon>=1.36.0" --quiet 2>&1 | tail -2 || true
fi

echo -e "${GREEN}✅ venv آماده${NC}"
echo "  venv python: $VENV_PYTHON"
$VENV_PYTHON --version

# مالکیت venv رو به service user تغییر بده (اگه non-root)
if [ "$SERVICE_USER" != "root" ]; then
    chown -R "$SERVICE_USER:$SERVICE_USER" "$VENV_DIR" 2>/dev/null || true
fi

# اگه service user != root، باید venv رو برای اون قابل خواندن باشه
# (system venv با root ساخته می‌شه ولی service ممکنه با omid اجرا بشه)
# در این مورد، یه venv جدید برای اون user می‌سازیم
if [ "$SERVICE_USER" != "root" ]; then
    echo -e "${YELLOW}👤 venv برای service user ($SERVICE_USER) ساخته شد${NC}"
    # chown قبلی این رو حل می‌کنه
fi

# از این به بعد، PYTHON_BIN به venv python اشاره می‌کنه
PYTHON_BIN="$VENV_PYTHON"

# ─── Find env file ───────────────────────────────────────
# چندین مسیر ممکن برای env file
ENV_FILE=""
for candidate in /etc/cianet.env /etc/selfbot.env "$SCRIPT_DIR/.env" "$SCRIPT_DIR/cianet.env"; do
    if [ -f "$candidate" ]; then
        ENV_FILE="$candidate"
        break
    fi
done
# اگر هیچ کدام نبود، /etc/cianet.env رو به‌عنوان default بساز
if [ -z "$ENV_FILE" ]; then
    ENV_FILE="/etc/cianet.env"
    echo -e "${YELLOW}📝 ساخت env file در ${ENV_FILE}${NC}"
    touch "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi
echo -e "${GREEN}✓ env file: ${ENV_FILE}${NC}"

# اگر فایل env متعلق به user دیگه‌ای هست، مالکیت رو با service user هم‌اهنگ کن
if [ "$SERVICE_USER" != "root" ]; then
    chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE" 2>/dev/null || true
    chmod 600 "$ENV_FILE"
fi

# ─── Generate password hash if not set ───
if ! grep -q "PANEL_ADMIN_PASS_HASH" "$ENV_FILE" 2>/dev/null; then
    echo ""
    echo -e "${YELLOW}🔐 تنظیم پسورد ورود به پنل وب${NC}"
    echo -e "${YELLOW}   (نکته: کاراکترها موقع تایپ نشون داده نمی‌شن — عمداً برای امنیت)${NC}"
    echo ""
    while true; do
        # بدون -s هم نشون داده نمی‌شه چون terminal suppressed است.
        # ولی اگه کاربر هرچی تایپ کرد رو ببینه بهتر از اینه که فکر کنه چیزی وارد نشده.
        # پس از -s استفاده می‌کنیم ولی قبلش به کاربر می‌گیم.
        printf "   Password (حداقل ۸ کاراکتر): "
        read -s PANEL_PASS
        echo ""
        if [ -z "$PANEL_PASS" ]; then
            echo -e "${RED}   ❌ Password خالی است — دوباره وارد کن${NC}"
            continue
        fi
        if [ ${#PANEL_PASS} -lt 8 ]; then
            echo -e "${RED}   ❌ Password باید حداقل ۸ کاراکتر باشه (شما ${#PANEL_PASS} کاراکتر وارد کردی)${NC}"
            continue
        fi
        printf "   Confirm password: "
        read -s PANEL_PASS_CONFIRM
        echo ""
        if [ "$PANEL_PASS" != "$PANEL_PASS_CONFIRM" ]; then
            echo -e "${RED}   ❌ Passwords مطابقت ندارند — دوباره امتحان کن${NC}"
            continue
        fi
        echo -e "${GREEN}   ✓ Password پذیرفته شد (طول: ${#PANEL_PASS} کاراکتر)${NC}"
        break
    done

    # Generate bcrypt hash با passlib
    # PATCH (v2.1.4): به‌دلیل set -e در ابتدای اسکریپت، اگه $PYTHON_BIN شکست
    # بخوره (مثلاً bcrypt C extension نصب نباشه)، کل اسکریپت بدون پیام خطا
    # متوقف می‌شد. حالا یا || true اضافه می‌کنیم یا set +e موقتاً غیرفعال.
    set +e
    PANEL_PASS_HASH=$($PYTHON_BIN -c "
from passlib.hash import bcrypt
print(bcrypt.encrypt('$PANEL_PASS'))
" 2>/dev/null)
    set -e
    if [ -z "$PANEL_PASS_HASH" ]; then
        # fallback با هش ساده‌تر (sha256) — بهتر از هیچ
        echo -e "${YELLOW}   ⚠️  passlib/bcrypt در venv کار نکرد — استفاده از sha256 (کم‌امن‌تر)${NC}"
        echo -e "${YELLOW}   برای استفاده از bcrypt بعد از نصب:${NC}"
        echo -e "${YELLOW}   $PYTHON_BIN -m pip install --upgrade 'passlib[bcrypt]'${NC}"
        PANEL_PASS_HASH="sha256:"$(echo -n "$PANEL_PASS" | sha256sum | awk '{print $1}')
    fi

    # تنظیم PANEL_ADMIN_USER اگه نباشه
    if ! grep -q "PANEL_ADMIN_USER" "$ENV_FILE" 2>/dev/null; then
        # PATCH (v2.1.4): در حالت non-interactive یا stdin pipe شده،
        # read -p می‌تونه بدون ورودی هم ادامه بده و empty پاس بده. اگر
        # PANEL_USER empty شد، default کن.
        set +e
        read -p "   Username (default: admin): " PANEL_USER
        set -e
        PANEL_USER="${PANEL_USER:-admin}"
        echo "PANEL_ADMIN_USER=$PANEL_USER" >> "$ENV_FILE"
    fi
    echo "PANEL_ADMIN_PASS_HASH=$PANEL_PASS_HASH" >> "$ENV_FILE"
    # Session secret
    SESSION_SECRET=$($PYTHON_BIN -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
    echo "PANEL_SESSION_SECRET=$SESSION_SECRET" >> "$ENV_FILE"
    echo -e "${GREEN}✅ پسورد تنظیم شد (hash type: ${PANEL_PASS_HASH%%:*})${NC}"
else
    echo -e "${GREEN}✅ پسورد از قبل تنظیم شده${NC}"
fi

# اگه PANEL_CORS_ORIGINS تنظیم نشده، default localhost:3000
if ! grep -q "PANEL_CORS_ORIGINS" "$ENV_FILE" 2>/dev/null; then
    echo "PANEL_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000" >> "$ENV_FILE"
fi

# ─── systemd service ───
SERVICE_FILE="/etc/systemd/system/cianet-panel.service"
echo -e "${YELLOW}⚙️  ساخت systemd service...${NC}"

# After dependency: اگه service اصلی هست، به اون وابسته باش
AFTER_DEP="network-online.target"
if [ -n "$EXISTING_SERVICE" ]; then
    AFTER_DEP="network-online.target ${EXISTING_SERVICE}.service"
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CiaNet Web Panel (FastAPI backend on port 8000)
After=$AFTER_DEP
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=${SERVICE_USER}
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

# مالکیت scripts رو به service user تغییر بده (اگه non-root)
if [ "$SERVICE_USER" != "root" ]; then
    chown "$SERVICE_USER:$SERVICE_USER" "$SCRIPT_DIR/web_panel.py" 2>/dev/null || true
    chown "$SERVICE_USER:$SERVICE_USER" "$SCRIPT_DIR/main.py" 2>/dev/null || true
    chown "$SERVICE_USER:$SERVICE_USER" "$SCRIPT_DIR/cianet_updater.py" 2>/dev/null || true
    # data dir رو هم دسترسی بده
    if [ -d "$SCRIPT_DIR/data" ]; then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$SCRIPT_DIR/data" 2>/dev/null || true
    fi
fi

echo -e "${GREEN}✅ service file ساخته شد${NC}"

# ─── nginx config (optional) ───
NGINX_CONF="/etc/nginx/sites-available/cianet-panel"
NGINX_LINK="/etc/nginx/sites-enabled/cianet-panel"

if command -v nginx >/dev/null 2>&1; then
    echo ""
    echo -e "${YELLOW}🌐 nginx پیدا شد — ایجاد config...${NC}"
    read -p "   Domain or IP for panel (مثلاً panel.cianet.ir یا 127.0.0.1، Enter برای skip): " PANEL_DOMAIN
    if [ -n "$PANEL_DOMAIN" ]; then
        read -p "   Enable HTTPS via Let's Encrypt? (y/N): " ENABLE_SSL

        mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

        if [ "$ENABLE_SSL" = "y" ] || [ "$ENABLE_SSL" = "Y" ]; then
            cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name $PANEL_DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $PANEL_DOMAIN;

    # SSL — توسط certbot --nginx اضافه می‌شه
    # ssl_certificate /etc/letsencrypt/live/$PANEL_DOMAIN/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/$PANEL_DOMAIN/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

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
        else
            cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    server_name $PANEL_DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

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
        fi
        ln -sf "$NGINX_CONF" "$NGINX_LINK"
        if nginx -t 2>&1 | tail -5; then
            systemctl reload nginx
            echo -e "${GREEN}✅ nginx config اعمال شد${NC}"
            if [ "$ENABLE_SSL" = "y" ] || [ "$ENABLE_SSL" = "Y" ]; then
                echo -e "${YELLOW}⚠️  برای SSL اجرا کن:${NC}"
                echo "   sudo certbot --nginx -d $PANEL_DOMAIN"
            fi
        else
            echo -e "${YELLOW}⚠️  nginx config نامعتبر — بررسی کن${NC}"
        fi
    else
        echo -e "${YELLOW}   nginx config skip شد (port 8000 مستقیم در دسترس است)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  nginx نصب نیست — پنل روی port 8000 مستقیم در دسترس خواهد بود${NC}"
fi

# ─── Frontend: static web_static/ رو پیشنهاد می‌دهیم (no npm needed) ───
echo ""
if [ -d "$SCRIPT_DIR/web_static" ]; then
    echo -e "${GREEN}✅ frontend استاتیک (web_static/) آماده است — نیاز به npm build نیست${NC}"
    echo -e "${GREEN}   پنل در http://localhost:8000/app/login.html در دسترس است${NC}"
fi

# ─── Build frontend Next.js (اختیاری — فقط اگه خواستی) ───
if [ -f "$SCRIPT_DIR/web/package.json" ]; then
    echo ""
    echo -e "${YELLOW}📦 Next.js frontend هم موجود است (اختیاری)${NC}"
    read -p "   Next.js build رو اجرا کنم؟ (y/N): " BUILD_NEXT
    if [ "$BUILD_NEXT" = "y" ] || [ "$BUILD_NEXT" = "Y" ]; then
        cd "$SCRIPT_DIR/web"
        if ! command -v npm >/dev/null 2>&1; then
            echo -e "${YELLOW}📦 نصب Node.js 20...${NC}"
            if command -v apt-get >/dev/null 2>&1; then
                curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>&1 | tail -3
                apt-get install -y nodejs 2>&1 | tail -3
            elif command -v yum >/dev/null 2>&1; then
                curl -fsSL https://rpm.nodesource.com/setup_20.x | bash - 2>&1 | tail -3
                yum install -y nodejs 2>&1 | tail -3
            fi
        fi
        if command -v npm >/dev/null 2>&1; then
            npm install --silent 2>&1 | tail -5 || {
                echo -e "${YELLOW}⚠️  npm install ناموفق${NC}"
            }
            npm run build 2>&1 | tail -5 || {
                echo -e "${YELLOW}⚠️  build ناموفق${NC}"
            }
            cd "$SCRIPT_DIR"
        else
            echo -e "${YELLOW}⚠️  npm در دسترس نیست${NC}"
        fi
    else
        echo -e "${GREEN}   skip شد (frontend استاتیک در web_static/ کافیه)${NC}"
    fi
fi

# ─── Start services ───
echo ""
echo -e "${YELLOW}🔄 فعال‌سازی services...${NC}"
systemctl daemon-reload
systemctl enable cianet-panel
systemctl restart cianet-panel

sleep 3
if systemctl is-active --quiet cianet-panel; then
    echo -e "${GREEN}✅ cianet-panel running${NC}"
else
    echo -e "${RED}❌ cianet-panel failed to start — checking logs...${NC}"
    journalctl -u cianet-panel --no-pager -n 30
    echo ""
    echo -e "${YELLOW}نکته‌های عیب‌یابی:${NC}"
    echo "  ۱. اگه خطا 'Permission denied' روی data/ هست:"
    echo "     sudo chown -R $SERVICE_USER:$SERVICE_USER $SCRIPT_DIR/data"
    echo "  ۲. اگه خطا 'No module named telethon' یا 'No module named fastapi' هست:"
    echo "     venv خراب شده. دوباره بساز:"
    echo "     sudo rm -rf $VENV_DIR && sudo bash install_panel.sh"
    echo "  ۳. اگه خطا 'PANEL_ADMIN_PASS_HASH not set' هست:"
    echo "     echo \"PANEL_ADMIN_PASS_HASH=\$(python3 -c 'from passlib.hash import bcrypt; print(bcrypt.encrypt(\"PASS\"))')\" >> /etc/cianet.env"
    echo "  ۴. اگه خطا 'Address already in use' روی port 8000:"
    echo "     sudo lsof -i :8000  # چه پروسه‌ای داره اشغال می‌کنه"
    echo "  ۵. اگه خطا 'Permission denied' روی .venv/:"
    echo "     sudo chown -R $SERVICE_USER:$SERVICE_USER $VENV_DIR"
    exit 1
fi

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
    DOMAIN=$(grep -m1 server_name "$NGINX_CONF" 2>/dev/null | head -1 | awk '{print $2}' | tr -d ';')
    echo "   Panel URL:        http://$DOMAIN/app/login.html"
else
    echo "   Frontend:         http://localhost:8000/app/login.html"
    echo "   Backend API docs: http://localhost:8000/api/docs"
    echo ""
    echo -e "${YELLOW}💡 برای دسترسی از بیرون:${NC}"
    echo "   ۱. nginx یا caddy نصب کن و port 8000 رو proxy کن (443 → 8000)"
    echo "   ۲. یا فایروال رو روی port 8000 باز کن و مستقیم به /app/login.html برو"
fi
echo ""
echo -e "${BLUE}📋 ورود:${NC}"
echo "   username: $(grep '^PANEL_ADMIN_USER=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo 'admin')"
echo "   password: همان که در نصب وارد کردی"
