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

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ با sudo اجرا کن:${NC} sudo bash uninstall.sh"
    exit 1
fi

echo -e "${RED}╔═══════════════════════════════════════╗${NC}"
echo -e "${RED}║   🗑️  حذف کامل CiaNet               ║${NC}"
echo -e "${RED}╚═══════════════════════════════════════╝${NC}"
echo ""

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
systemctl daemon-reload

echo -e "${YELLOW}۴. حذف nginx config...${NC}"
rm -f /etc/nginx/sites-enabled/cianet-panel 2>/dev/null || true
rm -f /etc/nginx/sites-available/cianet-panel 2>/dev/null || true
systemctl reload nginx 2>/dev/null || true

echo -e "${YELLOW}۵. حذف فایل env...${NC}"
rm -f /etc/cianet.env /etc/selfbot.env

echo -e "${YELLOW}۶. حذف دایرکتوری پروژه...${NC}"
rm -rf /opt/cianet

echo -e "${YELLOW}۷. حذف کاربر cianet...${NC}"
userdel cianet 2>/dev/null || true

echo -e "${YELLOW}۸. حذف cloudflared...${NC}"
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
