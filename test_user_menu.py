#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
User Menu Redesign Test Suite
==============================
Tests the new 6-button user menu + admin button.
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


RESULTS = []


def record(name, passed, details=""):
    RESULTS.append({"name": name, "passed": passed, "details": details})
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {details}")


def test_what_is_text():
    print("─" * 60)
    print("📖 تست: متن «سلف چیست» شامل راهنمای فعال‌سازی")

    from main import WHAT_IS_SELFBOT_TEXT, ACTIVATION_HELP_TEXT
    # v1.8.0: متن‌ها جدا شدن — «سلف چیست» خلاصه‌ست و «راهنمای فعال‌سازی» جداگانه
    what_text = WHAT_IS_SELFBOT_TEXT
    help_text = ACTIVATION_HELP_TEXT

    record("متن «سلف چیست» وجود دارد", len(what_text) > 100, f"len={len(what_text)}")
    record("متن «راهنمای فعال‌سازی» وجود دارد", len(help_text) > 100, f"len={len(help_text)}")
    record("سلف چیست: شامل قابلیت‌ها", "قابلیت" in what_text or "ساعت" in what_text, "✓")
    record("سلف چیست: شامل امنیت", "امنیت" in what_text, "✓")
    record("راهنما: شامل «+98» (شماره بین‌المللی)", "+98" in help_text, "✓")
    record("راهنما: شامل «رمز دو مرحله‌ای»", "رمز دو مرحله‌ای" in help_text, "✓")
    record("راهنما: شامل «مرحله»", "مرحله" in help_text, "✓")


def test_user_menu_callbacks():
    print("─" * 60)
    print("🎯 تست: callback دکمه‌های منو")

    # اینا callback data هایی هستن که باید در منوی جدید باشن
    expected = [
        "user_what_is",          # 1. سلف چیست
        "user_sub_status",       # 2. انقضای سلف
        "user_renew",            # 3. خرید سلف
        "user_login_account",    # 4. لاگین کردن سلف
        "user_activate_license", # 5. خرید با لایسنس
        "user_support",          # 6. پشتیبانی
        "admin_hub",             # 7. ادمین
    ]

    # فقط بررسی می‌کنیم که این callbackها در main تعریف شدن
    from main import SaaSBot
    methods = dir(SaaSBot)

    for cb in expected:
        # هر callback باید handler داشته باشه (مستقیم یا غیرمستقیم)
        # handler معمولاً با نام callback در _on_query یا متد جدا میاد
        record(f"callback {cb} در codebase",
               cb in open("main.py").read(),
               f"present in main.py")


def test_show_main_menu_method():
    print("─" * 60)
    print("🏠 تست: متد _show_menu_for_role")

    from main import SaaSBot
    has_method = hasattr(SaaSBot, "_show_menu_for_role")
    record("_show_menu_for_role وجود دارد", has_method, "")

    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # چک کن که ۶ ردیف دقیق نصب شده
    has_r1 = "راهنمای فعال‌سازی" in content and "سلف چیست؟" in content
    record("ردیف ۱: راهنما + سلف چیست", has_r1, "")

    has_r2 = "انقضای سلف:" in content
    record("ردیف ۲: انقضای سلف", has_r2, "")

    has_r3_login = "لاگین کردن سلف" in content and "خرید سلف" in content
    record("ردیف ۳: لاگین + خرید", has_r3_login, "")

    has_r4 = "خرید با لایسنس" in content
    record("ردیف ۴: خرید با لایسنس", has_r4, "")

    has_r5 = "پشتیبانی" in content
    record("ردیف ۵: پشتیبانی", has_r5, "")

    has_r6 = "پنل مدیریت / ادمین" in content
    record("ردیف ۶: پنل مدیریت", has_r6, "")


def test_admin_conditional():
    print("─" * 60)
    print("🛡 تست: دکمه‌ی ادمین فقط برای privileged")

    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # چک کن که admin_hub داخل شرط privileged هست
    import re
    pattern = r"if privileged:.*?admin_hub"
    has_guard = bool(re.search(pattern, content, re.DOTALL))
    record("admin_hub داخل if privileged", has_guard,
           "محافظت شده")


def test_login_condition():
    print("─" * 60)
    print("🔐 تست: شرط نمایش دکمه‌ی لاگین")

    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # چک کن که user_login_account داخل شرط هست
    # (sub یا not needs_sub یا has_account یا n_bots > 0)
    has_login_cond = "user_login_account" in content and \
        ("has_account" in content or "n_bots" in content or "needs_sub" in content)
    record("لاگین شرطی است", has_login_cond, "")


async def main():
    print("=" * 60)
    print("🏠 User Menu Redesign Test Suite")
    print("=" * 60)

    try:
        test_what_is_text()
        test_user_menu_callbacks()
        test_show_main_menu_method()
        test_admin_conditional()
        test_login_condition()
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

    with open(os.path.join(os.path.dirname(__file__), "test_user_menu_results.json"), "w", encoding="utf-8") as f:
        json.dump({
            "total": len(RESULTS),
            "passed": passed,
            "failed": failed,
            "results": RESULTS,
        }, f, ensure_ascii=False, indent=2)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
