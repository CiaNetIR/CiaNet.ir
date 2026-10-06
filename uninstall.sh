#!/bin/bash
# ══════════════════════════════════════════════════════════
#  CiaNet — Uninstall Script
#  حذف کامل CiaNet از سرور
# ══════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ─── پارامترها ───
# --no-backup : حذف اجباری بدون گرفتن بکاپ (پیش‌فرض = قبل از حذف بکاپ گرفته می‌شه)
NO_BACKUP=0
if [ "${1:-}" = "--no-backup" ]; then
    NO_BACKUP=1
fi

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ با sudo اجرا کن:${NC} sudo bash uninstall.sh"
    exit 1
fi

echo -e "${RED}╔═══════════════════════════════════════╗${NC}"
echo -e "${RED}║   🗑️  حذف کامل CiaNet               ║${NC}"
echo -e "${RED}╚═══════════════════════════════════════╝${NC}"
echo ""

echo -e "${YELLOW}ℹ️  قبل از حذف، از دیتابیس‌ها و تنظیمات بکاپ در /var/backups ذخیره می‌شه (حذف بدون بکاپ: --no-backup)${NC}"
read -p "آیا مطمئنی؟ همه‌ی داده‌ها پاک می‌شن! (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo -e "${GREEN}لغو شد.${NC}"
    exit 0
fi

echo ""
echo -e "${YELLOW}۱. توقف سرویس‌ها...${NC}"
systemctl stop selfbot 2>/dev/null || true
systemctl stop cianet-panel 2>/dev/null || true
systemctl stop cianet-tunnel 2>/dev/null || true
systemctl stop cianet 2>/dev/null || true

echo -e "${YELLOW}۲. غیرفعال‌سازی سرویس‌ها...${NC}"
systemctl disable selfbot 2>/dev/null || true
systemctl disable cianet-panel 2>/dev/null || true
systemctl disable cianet-tunnel 2>/dev/null || true
systemctl disable cianet 2>/dev/null || true

echo -e "${YELLOW}۳. حذف فایل‌های systemd...${NC}"
rm -f /etc/systemd/system/selfbot.service
rm -f /etc/systemd/system/cianet-panel.service
rm -f /etc/systemd/system/cianet-tunnel.service
rm -f /etc/systemd/system/cianet.service
rm -f /etc/systemd/system/multi-user.target.wants/selfbot.service
rm -f /etc/systemd/system/multi-user.target.wants/cianet-panel.service
# حذف sudoers ساخته‌شده توسط install.sh (برای auto-update)
rm -f /etc/sudoers.d/cianet
systemctl daemon-reload

echo -e "${YELLOW}۴. حذف nginx config...${NC}"
rm -f /etc/nginx/sites-enabled/cianet-panel 2>/dev/null || true
rm -f /etc/nginx/sites-available/cianet-panel 2>/dev/null || true
systemctl reload nginx 2>/dev/null || true

# ─── ۵. بکاپ دیتابیس‌ها و تنظیمات (پیش‌فرض — قابل رد با --no-backup) ───
# قبل از rm -rf از داده‌های حساس (saas.db / bot_data.db / config.json / sessions)
# نسخه‌ی پشتیبان timestamp دار ساخته می‌شه.
BACKUP_DIR="/var/backups/cianet-uninstall-$(date +%Y%m%d-%H%M%S)"
if [ "$NO_BACKUP" = "1" ]; then
    echo -e "${YELLOW}۵. بکاپ نادیده گرفته شد (--no-backup)${NC}"
else
    echo -e "${YELLOW}۵. بکاپ دیتابیس‌ها و تنظیمات...${NC}"
    mkdir -p "$BACKUP_DIR"
    BACKUP_FAILED=0
    for ITEM in saas.db bot_data.db config.json sessions; do
        if [ -e "/opt/cianet/$ITEM" ]; then
            cp -a "/opt/cianet/$ITEM" "$BACKUP_DIR/" || BACKUP_FAILED=1
        fi
    done
    if [ "$BACKUP_FAILED" = "1" ]; then
        echo -e "${RED}❌ بکاپ کامل نشد — برای جلوگیری از از دست رفتن داده‌ها حذف متوقف شد.${NC}"
        echo -e "${YELLOW}   مشکل رو برطرف کن و دوباره اجرا کن، یا برای حذف اجباری: sudo bash uninstall.sh --no-backup${NC}"
        exit 1
    fi
    if [ -n "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        chmod 700 "$BACKUP_DIR"
        echo -e "${GREEN}   ✅ بکاپ در این مسیر ذخیره شد: $BACKUP_DIR${NC}"
    else
        rmdir "$BACKUP_DIR" 2>/dev/null || true
        echo -e "${GREEN}   فایلی برای بکاپ وجود نداشت${NC}"
    fi
fi

echo -e "${YELLOW}۶. حذف فایل env...${NC}"
rm -f /etc/cianet.env /etc/selfbot.env

echo -e "${YELLOW}۷. حذف دایرکتوری پروژه...${NC}"
rm -rf /opt/cianet

echo -e "${YELLOW}۸. حذف کاربر cianet...${NC}"
userdel cianet 2>/dev/null || true

echo -e "${YELLOW}۹. حذف cloudflared...${NC}"
apt remove -y cloudflared 2>/dev/null || true
rm -f /usr/local/bin/cloudflared 2>/dev/null || true

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ حذف کامل انجام شد!              ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}تأیید:${NC}"
systemctl status selfbot 2>&1 | head -2
systemctl status cianet-panel 2>&1 | head -2
ls /opt/cianet 2>&1
