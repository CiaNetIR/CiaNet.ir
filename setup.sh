#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  CiaNet.ir Selfbot — One-shot Installer v2.2
# ══════════════════════════════════════════════════════════════
# v2.2 fixes:
#   - Smart migration: legacy install path auto-detect
#   - Auto-backup sessions/DB before overwriting
#   - Env vars migrated from /etc/selfbot.env
#   - Service uses correct paths
#   - systemd warnings removed
# ══════════════════════════════════════════════════════════════

set -e

REPO_URL="https://github.com/DLSDT/CiaNet.ir.git"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_DIR="/opt/cianet"
SERVICE_NAME="cianet"
ENV_FILE="/etc/cianet.env"
WATCHDOG_DIR="/opt/cianet-watchdog"
BACKUP_ROOT="/opt/cianet-migration-backup"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

cat <<'BANNER'
   ╔════════════════════════════════════════════════════╗
   ║      One-shot Installer v2.2 · نصب یک‌دستوری       ║
   ╚════════════════════════════════════════════════════╝
BANNER

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Run with sudo: sudo bash setup.sh${NC}"
    exit 1
fi

if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    OS=ubuntu
fi
case "$OS" in
    ubuntu|debian) PKG_MGR="apt" ;;
    centos|rhel|fedora|rocky|almalinux) PKG_MGR="yum" ;;
    arch) PKG_MGR="pacman" ;;
    *) PKG_MGR="apt" ;;
esac

NON_INTERACTIVE=false
SKIP_MIGRATION=false
for arg in "$@"; do
    case $arg in
        --non-interactive|-y) NON_INTERACTIVE=true ;;
        --skip-migration) SKIP_MIGRATION=true ;;
        --help|-h) echo "Usage: sudo bash setup.sh [--non-interactive] [--skip-migration]"; exit 0 ;;
    esac
done

# ═══════════════════════════════════════════════════════════
#  STEP 0: Detect legacy install
# ═══════════════════════════════════════════════════════════
LEGACY_DIR=""

if [ "$SKIP_MIGRATION" = false ]; then
    echo -e "${BLUE}[0/7]${NC} Detecting legacy install..."

    # 1) From systemd service file
    if [ -f /etc/systemd/system/selfbot.service ]; then
        WD=$(grep -E "^WorkingDirectory" /etc/systemd/system/selfbot.service | sed 's/.*=//' | tr -d ' ' || true)
        if [ -n "$WD" ] && [ -d "$WD" ]; then
            LEGACY_DIR="$WD"
        fi
    fi

    # 2) Common paths
    if [ -z "$LEGACY_DIR" ]; then
        for candidate in /opt/selfbot /opt/cianet /www/self /www/self/self /root/selfbot /home/self/self /root/CiaNet.ir; do
            if [ -f "$candidate/main.py" ] || [ -f "$candidate/config.json" ] || [ -d "$candidate/sessions" ]; then
                LEGACY_DIR="$candidate"
                break
            fi
        done
    fi

    # 3) Fallback: search
    if [ -z "$LEGACY_DIR" ]; then
        LEGACY_DIR=$(find /opt /www /root /home -maxdepth 4 -name "main.py" -path "*selfbot*" 2>/dev/null | head -1 | xargs dirname 2>/dev/null || true)
    fi

    if [ -n "$LEGACY_DIR" ] && [ "$LEGACY_DIR" != "$INSTALL_DIR" ] && [ -d "$LEGACY_DIR" ]; then
        echo -e "  ${CYAN}Found legacy install: ${NC}$LEGACY_DIR"
    else
        echo -e "  ${CYAN}No legacy install found (fresh install)${NC}"
        LEGACY_DIR=""
    fi
fi

# ═══════════════════════════════════════════════════════════
#  STEP 1: System deps
# ═══════════════════════════════════════════════════════════
echo -e "${BLUE}[1/7]${NC} Installing system deps..."
case $PKG_MGR in
    apt)
        apt update -qq 2>/dev/null || true
        DEBIAN_FRONTEND=noninteractive apt install -y -qq python3 python3-pip python3-venv git curl wget 2>&1 | tail -2
        ;;
    yum)
        yum install -y python3 python3-pip git curl wget 2>&1 | tail -2
        ;;
    pacman)
        pacman -Sy --noconfirm python python-pip git curl wget 2>&1 | tail -2
        ;;
esac
echo -e "  ${GREEN}OK${NC} python3 $(python3 --version 2>&1 | cut -d' ' -f2)"

# ═══════════════════════════════════════════════════════════
#  STEP 2: Clone / Update repo
# ═══════════════════════════════════════════════════════════
echo -e "${BLUE}[2/7]${NC} Cloning/updating repo..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "  ${YELLOW}Already exists, pulling latest...${NC}"
    cd "$INSTALL_DIR"
    git fetch origin 2>&1 | tail -1
    git reset --hard origin/$REPO_BRANCH 2>&1 | tail -1
    echo -e "  ${GREEN}OK${NC} Updated"
else
    if [ -d "$INSTALL_DIR" ]; then
        echo -e "  ${YELLOW}Warning: $INSTALL_DIR exists but no .git. Backing up...${NC}"
        mkdir -p "$BACKUP_ROOT/manual-$(date +%s)"
        cp -a "$INSTALL_DIR" "$BACKUP_ROOT/manual-$(date +%s)/" 2>/dev/null || true
        rm -rf "$INSTALL_DIR"
    fi
    git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>&1 | tail -2
    echo -e "  ${GREEN}OK${NC} Cloned"
fi

cd "$INSTALL_DIR"

# ═══════════════════════════════════════════════════════════
#  STEP 3: Python venv + deps
# ═══════════════════════════════════════════════════════════
echo -e "${BLUE}[3/7]${NC} Setting up Python venv..."
if [ ! -d "venv" ]; then
    python3 -m venv venv 2>&1 | tail -1
fi
source venv/bin/activate
pip install --quiet --upgrade pip 2>&1 | tail -1
pip install --quiet -r requirements.txt 2>&1 | tail -3 || {
    echo -e "${RED}pip install failed${NC}"
    echo "Try manually: cd $INSTALL_DIR && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
}
echo -e "  ${GREEN}OK${NC} venv ready"

# ═══════════════════════════════════════════════════════════
#  STEP 4: Env vars
# ═══════════════════════════════════════════════════════════
echo -e "${BLUE}[4/7]${NC} Configuring environment..."

# Auto-migrate from /etc/selfbot.env (v2.2 NEW)
if [ -f /etc/selfbot.env ] && [ ! -f "$ENV_FILE" ]; then
    # Sanitize قبل از کپی: nano/editor فاصله‌ی انتهای خط اضافه می‌کنه
    # که systemd اون رو به‌عنوان بخشی از مقدار env می‌خونه و token/hash
    # رو خراب می‌کنه (ریشه‌ی bug: 'ADMIN_BOT_TOKEN تنظیم نشده').
    sed 's/[[:space:]]*$//' /etc/selfbot.env > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo -e "  ${GREEN}OK${NC} Migrated env from /etc/selfbot.env (sanitized)"
fi

if [ -f "$ENV_FILE" ]; then
    echo -e "  ${YELLOW}Existing env: $ENV_FILE${NC}"
    # Sanitize: حذف فاصله‌های انتهای خط (از nano/editor خراب می‌شه)
    # این کار لازمه چون systemd فاصله‌ی انتهای خط رو به‌عنوان بخشی
    # از مقدار env می‌خونه و token/hash رو خراب می‌کنه.
    if [ -w "$ENV_FILE" ]; then
        sed -i 's/[[:space:]]*$//' "$ENV_FILE"
    fi
    if [ "$NON_INTERACTIVE" = false ]; then
        read -p "      Keep existing values? [Y/n] " use_existing
        if [[ ! "$use_existing" =~ ^[Yy]$|^$ ]]; then
            rm -f "$ENV_FILE"
        fi
    fi
fi

API_ID="${API_ID:-}"
API_HASH="${API_HASH:-}"
ADMIN_BOT_TOKEN="${ADMIN_BOT_TOKEN:-}"
ADMIN_ID="${ADMIN_ID:-}"
HELPER_BOT_TOKEN="${HELPER_BOT_TOKEN:-}"

if [ ! -f "$ENV_FILE" ]; then
    if [ -z "$API_ID" ] && [ "$NON_INTERACTIVE" = false ]; then
        echo ""
        echo "Enter your credentials (my.telegram.org + @BotFather):"
        echo ""
        read -p "  API_ID: " API_ID
        read -p "  API_HASH: " API_HASH
        read -p "  ADMIN_BOT_TOKEN: " ADMIN_BOT_TOKEN
        read -p "  ADMIN_ID: " ADMIN_ID
        read -p "  HELPER_BOT_TOKEN (optional): " HELPER_BOT_TOKEN
    fi

    if [ -z "$API_ID" ] || [ -z "$API_HASH" ] || [ -z "$ADMIN_BOT_TOKEN" ] || [ -z "$ADMIN_ID" ]; then
        echo -e "${RED}API_ID, API_HASH, ADMIN_BOT_TOKEN, ADMIN_ID required${NC}"
        echo "Either set env vars or run interactively."
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
    echo -e "  ${GREEN}OK${NC} env file created"
fi

# ═══════════════════════════════════════════════════════════
#  STEP 5: Migrate data/sessions/config (v2.2 NEW)
# ═══════════════════════════════════════════════════════════
echo -e "${BLUE}[5/7]${NC} Migrating data and sessions..."

if [ -n "$LEGACY_DIR" ] && [ -d "$LEGACY_DIR" ] && [ "$LEGACY_DIR" != "$INSTALL_DIR" ]; then
    # Stop old service
    if systemctl list-unit-files 2>/dev/null | grep -q "^selfbot.service"; then
        echo -e "  ${YELLOW}Stopping selfbot.service...${NC}"
        systemctl stop selfbot 2>/dev/null || true
        systemctl disable selfbot 2>/dev/null || true
    fi

    # Backup
    BACKUP_PATH="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP_PATH"
    [ -d "$LEGACY_DIR/data" ] && cp -a "$LEGACY_DIR/data" "$BACKUP_PATH/" 2>/dev/null || true
    [ -d "$LEGACY_DIR/sessions" ] && cp -a "$LEGACY_DIR/sessions" "$BACKUP_PATH/" 2>/dev/null || true
    [ -f "$LEGACY_DIR/config.json" ] && cp "$LEGACY_DIR/config.json" "$BACKUP_PATH/" 2>/dev/null || true
    [ -f "$LEGACY_DIR/saas.db" ] && cp "$LEGACY_DIR/saas.db" "$BACKUP_PATH/" 2>/dev/null || true
    echo -e "  ${GREEN}OK${NC} Backup: $BACKUP_PATH"

    # Migrate data/
    if [ -d "$LEGACY_DIR/data" ]; then
        mkdir -p "$INSTALL_DIR/data"
        cp -rn "$LEGACY_DIR/data/"* "$INSTALL_DIR/data/" 2>/dev/null || true
        chown -R root:root "$INSTALL_DIR/data" 2>/dev/null || true
        echo -e "  ${GREEN}OK${NC} data/ migrated"
    fi

    # Migrate sessions/ (the critical part)
    if [ -d "$LEGACY_DIR/sessions" ]; then
        mkdir -p "$INSTALL_DIR/sessions"
        # rsync خیلی مطمئن‌تر از cp هست وقتی فایل‌ها حساس هستن
        # (cp -rpn می‌تونه در بعضی edge cases فایل رو خراب کنه اگه
        # در حین کپی، main.py هنوز در حال استفاده از session باشه).
        # --update: overwrite نکن فایل‌هایی که newer هستن در dest
        # --no-times: timestamp حفظ نکن (Telethon حساس به mtime)
        # --checksum: فقط بر اساس content مقایسه کنه
        if command -v rsync >/dev/null 2>&1; then
            rsync -au --no-times --checksum "$LEGACY_DIR/sessions/" "$INSTALL_DIR/sessions/" 2>/dev/null || true
        else
            # fallback: cp ساده (بدون -p که ممکنه timestamp خراب کنه)
            cp -un "$LEGACY_DIR/sessions/"* "$INSTALL_DIR/sessions/" 2>/dev/null || true
        fi
        chown -R root:root "$INSTALL_DIR/sessions" 2>/dev/null || true
        chmod 700 "$INSTALL_DIR/sessions" 2>/dev/null || true
        SESSION_COUNT=$(ls -1 "$INSTALL_DIR/sessions"/*.session 2>/dev/null | wc -l)
        echo -e "  ${GREEN}OK${NC} sessions/ migrated ($SESSION_COUNT accounts)"
    fi

    # Migrate config.json
    if [ -f "$LEGACY_DIR/config.json" ] && [ ! -f "$INSTALL_DIR/config.json" ]; then
        cp "$LEGACY_DIR/config.json" "$INSTALL_DIR/config.json"
        chown root:root "$INSTALL_DIR/config.json" 2>/dev/null || true
        chmod 600 "$INSTALL_DIR/config.json" 2>/dev/null || true
        echo -e "  ${GREEN}OK${NC} config.json migrated"
    fi

    # Migrate saas.db (critical for user/plan data)
    if [ -f "$LEGACY_DIR/saas.db" ] && [ ! -f "$INSTALL_DIR/saas.db" ]; then
        cp "$LEGACY_DIR/saas.db" "$INSTALL_DIR/saas.db"
        chown root:root "$INSTALL_DIR/saas.db" 2>/dev/null || true
        echo -e "  ${GREEN}OK${NC} saas.db migrated"
    fi
else
    echo -e "  ${CYAN}Fresh install, nothing to migrate${NC}"
fi

# ═══════════════════════════════════════════════════════════
#  STEP 6: Systemd service (FIXED v2.2)
# ═══════════════════════════════════════════════════════════
echo -e "${BLUE}[6/7]${NC} Creating systemd service..."

# Disable old selfbot.service (if exists)
if [ -f /etc/systemd/system/selfbot.service ]; then
    systemctl stop selfbot 2>/dev/null || true
    systemctl disable selfbot 2>/dev/null || true
    # Move aside instead of deleting
    if [ ! -f /etc/systemd/system/selfbot.service.disabled ]; then
        mv /etc/systemd/system/selfbot.service /etc/systemd/system/selfbot.service.disabled
    fi
    echo -e "  ${YELLOW}Old selfbot.service moved to .disabled${NC}"
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

[Install]
WantedBy=multi-user.target
EOF

# Watchdog timer
cat > /etc/systemd/system/$SERVICE_NAME-watchdog.timer <<EOF
[Unit]
Description=CiaNet Watchdog Timer (every 1 min)

[Timer]
OnBootSec=60
OnUnitActiveSec=60
AccuracySec=5

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/$SERVICE_NAME-watchdog.service <<EOF
[Unit]
Description=CiaNet Watchdog

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'systemctl is-active $SERVICE_NAME >/dev/null || systemctl restart $SERVICE_NAME'
EOF

# Auto-update timer
cat > /etc/systemd/system/$SERVICE_NAME-autoupdate.timer <<EOF
[Unit]
Description=CiaNet Auto-Update Timer (every 5 min)

[Timer]
OnBootSec=120
OnUnitActiveSec=300
AccuracySec=10

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/$SERVICE_NAME-autoupdate.service <<EOF
[Unit]
Description=CiaNet Auto-Update

[Service]
Type=oneshot
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/cianet_updater.py --check
EOF

systemctl daemon-reload
systemctl enable --now $SERVICE_NAME
systemctl enable --now $SERVICE_NAME-watchdog.timer
systemctl enable --now $SERVICE_NAME-autoupdate.timer

echo -e "  ${GREEN}OK${NC} Services enabled"

# ═══════════════════════════════════════════════════════════
#  STEP 7: Final report
# ═══════════════════════════════════════════════════════════
echo -e "${BLUE}[7/7]${NC} Finalizing..."
sleep 3

SERVICE_STATUS=$(systemctl is-active $SERVICE_NAME 2>/dev/null || echo "unknown")

echo ""
echo "════════════════════════════════════════════════════"
echo -e "  ${GREEN}Installation complete!${NC}"
echo "════════════════════════════════════════════════════"
echo ""
echo "  Install dir:  $INSTALL_DIR"
echo "  Service:      $SERVICE_NAME.service (status: $SERVICE_STATUS)"
echo "  Watchdog:     ${SERVICE_NAME}-watchdog.timer (every 1 min)"
echo "  Auto-update:  ${SERVICE_NAME}-autoupdate.timer (every 5 min)"
echo "  Env file:     $ENV_FILE"
echo ""
echo "  Logs:"
echo "    sudo journalctl -u $SERVICE_NAME -f"
echo "    tail -f /var/log/${SERVICE_NAME}-auto-update.log"
echo ""
if [ -n "$LEGACY_DIR" ]; then
    echo "  Migration backup: $BACKUP_ROOT/"
    echo "  Rollback: mv $BACKUP_ROOT/latest/* $LEGACY_DIR/"
    echo ""
fi
echo "  Go to your bot in Telegram and /start"
echo "════════════════════════════════════════════════════"

if [ "$SERVICE_STATUS" != "active" ]; then
    echo ""
    echo -e "${YELLOW}Service is not active. Check logs:${NC}"
    echo "  sudo journalctl -u $SERVICE_NAME -n 30 --no-pager"
fi

# Validate env vars are actually loaded by systemd
echo ""
echo -e "${BLUE}Validating env vars...${NC}"
sleep 1
LOADED_ENV=$(systemctl show $SERVICE_NAME -p Environment 2>/dev/null | sed 's/^Environment=//' | tr ' ' '\n' | grep -E "^API_|^ADMIN_" || true)
if [ -z "$LOADED_ENV" ]; then
    echo -e "${RED}WARN: systemd Environment is empty!${NC}"
    echo "  Most common cause: trailing whitespace in $ENV_FILE"
    echo "  Fix: sed -i 's/[[:space:]]*\$//' $ENV_FILE && systemctl restart $SERVICE_NAME"
else
    echo -e "${GREEN}OK${NC} env vars loaded:"
    echo "$LOADED_ENV" | sed 's/=.*/=***/' | head -4
fi
