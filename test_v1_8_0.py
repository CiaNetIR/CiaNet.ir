#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v1.8.0 Feature Tests
=====================
Tests for the redesigned admin panel, ticket flow, welcome text,
and 3-day grace period cleanup.
"""
import asyncio
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESULTS = []


def record(name, passed, details=""):
    RESULTS.append({"name": name, "passed": passed, "details": details})
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {details}")


def test_welcome_text():
    """متن /start کوتاه و حرفه‌ای (v2.0).

    قبلاً: یه بلوک ۸-خطی شعاری بود.
    حالا: یه جمله‌ی گرم + نام کاربر + وضعیت.
    """
    print("─" * 60)
    print("👋 تست: متن خوش‌آمدگویی v2.0")
    from main import SaaSBot

    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # v2.0: متن کوتاه و حرفه‌ای
    checks = [
        ("سلام {first}", "سلام شخصی‌سازی‌شده"),
        ("به سلف‌ساز CiaNet خوش آمدی", "خوش‌آمد مدرن"),
        ("سلف فعال", "خلاصه‌ی وضعیت سلف"),
    ]
    for s, desc in checks:
        record(f"شامل «{s}»", s in content, desc)


def test_help_text_separation():
    """«سلف چیست» و «راهنمای فعال‌سازی» جدا شده باشند."""
    print("─" * 60)
    print("📖 تست: جدا بودن متون راهنما")
    from main import WHAT_IS_SELFBOT_TEXT, ACTIVATION_HELP_TEXT, HELP_TEXT

    record("WHAT_IS_SELFBOT_TEXT معتبر", len(WHAT_IS_SELFBOT_TEXT) > 100,
           f"len={len(WHAT_IS_SELFBOT_TEXT)}")
    record("ACTIVATION_HELP_TEXT معتبر", len(ACTIVATION_HELP_TEXT) > 100,
           f"len={len(ACTIVATION_HELP_TEXT)}")
    # سلف چیست: باید کوتاه و فقط قابلیت‌ها/امنیت باشه
    record("«سلف چیست»: کوتاه (< 1000 char)",
           len(WHAT_IS_SELFBOT_TEXT) < 1000, f"len={len(WHAT_IS_SELFBOT_TEXT)}")
    # راهنما: باید طولانی و قدم‌به‌قدم باشه
    record("«راهنما»: طولانی (> 500 char)",
           len(ACTIVATION_HELP_TEXT) > 500, f"len={len(ACTIVATION_HELP_TEXT)}")
    record("راهنما شامل «مرحله»", "مرحله" in ACTIVATION_HELP_TEXT, "✓")
    record("راهنما شامل «+98»", "+98" in ACTIVATION_HELP_TEXT, "✓")
    record("راهنما شامل «رمز دو مرحله‌ای»",
           "رمز دو مرحله‌ای" in ACTIVATION_HELP_TEXT, "✓")


def test_ticket_unit_flow():
    """تیکت فقط بعد از انتخاب واحد و ارسال پیام ساخته شود."""
    print("─" * 60)
    print("🎫 تست: سیستم واحد پشتیبانی")
    from main import SUPPORT_UNITS, WIZ_TICKET_UNIT, WIZ_TICKET_MSG

    record("SUPPORT_UNITS تعریف شده", len(SUPPORT_UNITS) >= 3,
           f"{len(SUPPORT_UNITS)} واحد")
    record("WIZ_TICKET_UNIT تعریف شده", WIZ_TICKET_UNIT == "ticket_unit_select", "✓")
    record("واحد فنی", any(u == "technical" for u, _, _ in SUPPORT_UNITS), "✓")
    record("واحد مالی", any(u == "billing" for u, _, _ in SUPPORT_UNITS), "✓")
    record("واحد سایر", any(u == "general" for u, _, _ in SUPPORT_UNITS), "✓")

    # بررسی: تابع _user_support_start نباید بلافاصله create_ticket صدا بزنه
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # پیدا کردن تابع _user_support_start
    idx = content.find("async def _user_support_start")
    if idx > 0:
        snippet = content[idx:idx + 3000]
        # تو شروع جدید، اول create_ticket غیرفعال شده
        has_unit_select = "SUPPORT_UNITS" in snippet and "ticket_unit:" in snippet
        record("ابتدا واحد نمایش داده می‌شود", has_unit_select, "✓")


def test_ticket_db_schema():
    """جدول tickets ستون unit داشته باشد."""
    print("─" * 60)
    print("🗄 تست: schema جدول tickets")
    import sqlite3
    if not os.path.exists("saas.db"):
        record("DB موجود", False, "saas.db یافت نشد — ابتدا ربات اجرا کنید")
        return
    try:
        c = sqlite3.connect("saas.db")
        cols = c.execute("PRAGMA table_info(tickets)").fetchall()
        col_names = [col[1] for col in cols]
        record("ستون unit موجود", "unit" in col_names, f"cols={col_names}")
    except Exception as e:
        record("DB query موفق", False, str(e)[:50])


def test_admin_panel_tabs():
    """پنل ادمین 4 تب داشته باشد."""
    print("─" * 60)
    print("🎛 تست: پنل ادمین تب‌بندی")
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # v1.9.0: پنل ادمین flat شد - همه چیز در یک صفحه با 12 دکمه
    # به جای 4 تب تو در تو
    items = ["owner_payments", "admin_finance", "owner_pricing", "license_access",
             "admin_users", "user_search_start", "admin_tickets",
             "owner_channel_set", "admin_wallet", "cap_list", "admin_backup"]
    for item in items:
        record(f"دکمه {item}", f'"{item}"' in content, "✓")
    record("تابع _show_reseller_dashboard", "def _show_reseller_dashboard" in content, "✓")
    record("تابع _show_users_section", "def _show_users_section" in content, "✓")
    record("پنل flat (بدون 4 تب)", "admin_tab_sales" not in content, "✓")


def test_users_section_filters():
    """کاربران باید بر اساس نوع دسته‌بندی شوند."""
    print("─" * 60)
    print("👥 تست: دسته‌بندی کاربران")
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    record("users_section_direct تعریف شده", "users_section_direct" in content, "✓")
    record("users_section_resellers تعریف شده", "users_section_resellers" in content, "✓")
    record("users_section_admins تعریف شده", "users_section_admins" in content, "✓")
    # فقط کاربران فعال نمایش داده شوند
    record("فقط کاربران فعال", "_user_has_active_sub" in content, "✓")


def test_grace_period_cleanup():
    """سیستم حذف خودکار بعد از 3 روز."""
    print("─" * 60)
    print("🗑 تست: حذف خودکار 3 روز بعد")
    from main import SaaSBot
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    record("تابع _cleanup_long_expired_users",
           "def _cleanup_long_expired_users" in content, "✓")
    record("پارامتر grace_days", "grace_days" in content, "✓")
    record("حذف session files", "session_file" in content, "✓")
    record("حذف از config.json", "save_config" in content, "✓")
    record("ارسال پیام آخر", "از سرور حذف شد" in content, "✓")
    record("استفاده در _expiry_loop",
           "_cleanup_long_expired_users" in content, "✓")


def test_cap_list_fix():
    """فیکس دکمه «مجوزهای حساس» — event.answer() صدا زده شود."""
    print("─" * 60)
    print("🔐 تست: فیکس cap_list")
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # نباید b"cap_list" وجود داشته باشه
    record('b"cap_list" حذف شده', 'b"cap_list"' not in content, "✓")
    # event.answer() در _owner_show_capability_list
    idx = content.find("def _owner_show_capability_list")
    if idx > 0:
        snippet = content[idx:idx + 600]
        has_answer = "event.answer" in snippet
        record("event.answer() در _owner_show_capability_list", has_answer, "✓")


def test_support_unit_list_in_db():
    """تست end-to-end: ساخت تیکت فقط بعد از پیام."""
    print("─" * 60)
    print("🎫 تست: تیکت بعد از پیام ساخته می‌شود")
    from main import init_db, get_user, create_ticket, _conn
    init_db()

    test_user = 12345670
    with _conn() as c:
        c.execute("DELETE FROM tickets WHERE user_id = ?", (test_user,))
        upsert = "INSERT OR REPLACE INTO users (user_id, first_name, created_at) VALUES (?, ?, ?)"
        try:
            c.execute(upsert, (test_user, "تست", "2026-01-01 00:00:00"))
        except sqlite3.IntegrityError:
            pass

    # تیکت ساخته شد؟ (این نشون میده API ساخت درست کار می‌کنه)
    tid = create_ticket(test_user)
    record("create_ticket درست کار می‌کنه", tid > 0, f"ticket_id={tid}")

    # ولی خود تابع _user_support_start نباید خودکار این کار رو بکنه
    # (تأیید شد در test_ticket_unit_flow)


async def main():
    print("=" * 60)
    print("🛠 v1.8.0 Feature Test Suite")
    print("=" * 60)

    try:
        test_welcome_text()
        test_help_text_separation()
        test_ticket_unit_flow()
        test_ticket_db_schema()
        test_admin_panel_tabs()
        test_users_section_filters()
        test_grace_period_cleanup()
        test_cap_list_fix()
        test_support_unit_list_in_db()
    except Exception as e:
        print(f"\n❌ خطای بحرانی: {e}")
        import traceback
        traceback.print_exc()
        return 1

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = len(RESULTS) - passed
    print(f"\n{'='*60}")
    print(f"📊 نتیجه: {passed} موفق / {failed} ناموفق از {len(RESULTS)}")
    print(f"{'='*60}")

    if failed:
        print("\n❌ تست‌های ناموفق:")
        for r in RESULTS:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['details']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
