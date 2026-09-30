#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anti-Ban Protection Test Suite
==============================
Tests the new Anti-Ban helper functions and integration.
"""

import asyncio
import sys
import os
import json
import time
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


RESULTS = []


def record(name, passed, details=""):
    RESULTS.append({"name": name, "passed": passed, "details": details})
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {details}")


def test_normalize_phone():
    print("─" * 60)
    print("📞 تست: نرمال‌سازی شماره تلفن")

    cases = [
        # (input, expected, description)
        ("+989123456789", "+989123456789", "ایران بین‌المللی"),
        ("+1 555 123 4567", "+15551234567", "آمریکا با فاصله"),
        ("09123456789", "+989123456789", "ایران موبایل با 0"),
        ("989123456789", "+989123456789", "ایران بدون + با 98"),
        ("+44 20 7946 0958", "+442079460958", "انگلیس"),
        ("+90 532 123 45 67", "+905321234567", "ترکیه"),
        ("+1-555-123-4567", "+15551234567", "آمریکا با خط‌تیره"),
        ("+98 912 345 6789", "+989123456789", "ایران با فاصله"),
        ("00989123456789", "+989123456789", "ایران با 00"),
        ("۰۹۱۲۳۴۵۶۷۸۹", "+989123456789", "اعداد فارسی"),
        ("", "", "خالی"),
        (None, "", "None"),
        ("abc", "", "نامعتبر"),
        ("+", "", "فقط +"),
    ]

    from main import normalize_phone
    for inp, expected, desc in cases:
        result = normalize_phone(inp)
        ok = result == expected
        record(f"normalize_phone({inp!r})", ok, f"→ {result!r} ({desc})")


def test_is_iranian_phone():
    print("─" * 60)
    print("🇮🇷 تست: تشخیص شماره ایرانی")

    from main import is_iranian_phone, normalize_phone
    cases = [
        ("+989123456789", True, "ایران"),
        ("09123456789", True, "موبایل ایران"),
        ("+15551234567", False, "آمریکا"),
        ("+442079460958", False, "انگلیس"),
        ("+905321234567", False, "ترکیه"),
        ("+971501234567", False, "امارات"),
        ("+992931234567", False, "تاجیکستان"),
        ("", False, "خالی"),
        (None, False, "None"),
    ]
    for phone, expected, desc in cases:
        result = is_iranian_phone(phone)
        ok = result is expected
        record(f"is_iranian({phone!r})", ok, f"→ {result} ({desc})")


def test_phone_country_hint():
    print("─" * 60)
    print("🌍 تست: تشخیص کشور شماره")

    from main import phone_country_hint
    cases = [
        ("+989123456789", "ایران"),
        ("+15551234567", "آمریکا"),
        ("+442079460958", "انگلیس"),
        ("+905321234567", "ترکیه"),
        ("+79991234567", "روسیه"),
        ("+380501234567", "اوکراین"),
        ("+971501234567", "امارات"),
        ("", "ناشناس"),
    ]
    for phone, expected_keyword in cases:
        result = phone_country_hint(phone)
        ok = expected_keyword in result
        record(f"country_hint({phone!r})", ok, f"→ {result}")


def test_is_dangerous_account():
    print("─" * 60)
    print("⚠️ تست: تشخیص اکانت خطرناک")

    from main import is_dangerous_account
    cases = [
        ({"phone": "+989123456789", "tag": "iran1"}, False, "اکانت ایرانی"),
        ({"phone": "+15551234567", "tag": "us1"}, True, "اکانت آمریکایی"),
        ({"phone": "", "tag": "nophone"}, True, "بدون شماره"),
        ({}, True, "اکانت خالی"),
        ({"phone": None, "tag": "nullphone"}, True, "شماره None"),
        ({"phone": "+442079460958", "tag": "uk1"}, True, "اکانت انگلیسی"),
    ]
    for acc, expected, desc in cases:
        result = is_dangerous_account(acc)
        ok = result is expected
        record(f"is_dangerous({acc.get('tag', '?')})", ok,
               f"→ {result} ({desc})")


def test_antiban_guarded_action():
    print("─" * 60)
    print("🛡️ تست: گارد Anti-Ban")

    from main import antiban_guarded_action, ADMIN_ID, IS_DEDICATED_BOT

    # Iran account + normal user → allowed
    iran_acc = {"phone": "+989123456789", "tag": "iran1"}
    ok, info = antiban_guarded_action(12345, iran_acc, "sessterm")
    record("ایران + کاربر عادی → allowed", ok is True,
           f"ok={ok} info={info}")

    # Foreign account + normal user → needs confirm
    foreign_acc = {"phone": "+15551234567", "tag": "us1"}
    result = antiban_guarded_action(12345, foreign_acc, "sessterm")
    ok = result[0]
    info = result[1]
    record("خارج + کاربر عادی → needs confirm",
           ok is False and info == "needs_confirm" and len(result) == 3,
           f"ok={ok} info={info} result_len={len(result)}")

    # Foreign account + admin → allowed (bypass)
    if not IS_DEDICATED_BOT:
        result = antiban_guarded_action(ADMIN_ID, foreign_acc, "sessterm")
        ok = result[0]
        info = result[1]
        record("خارج + admin → bypass", ok is True,
               f"ok={ok} info={info}")
    else:
        record("خارج + admin (dedicated) → needs confirm", True, "skipped (dedicated bot)")

    # Account with no phone → needs confirm
    nophone_acc = {"tag": "nophone"}
    result = antiban_guarded_action(12345, nophone_acc, "tfago")
    ok = result[0]
    info = result[1]
    record("بدون شماره → needs confirm",
           ok is False and info == "needs_confirm",
           f"ok={ok} info={info}")


def test_antiban_token_flow():
    print("─" * 60)
    print("🎫 تست: چرخه‌ی توکن تأیید")

    from main import (antiban_request_confirmation, antiban_consume,
                      _ANTIBAN_PENDING, _ANTIBAN_TTL)

    # 1. ساخت توکن
    token = antiban_request_confirmation("test_tag", "sessterm", 12345)
    record("ساخت توکن", len(token) == 12 and token in _ANTIBAN_PENDING,
           f"token={token}")

    # 2. مصرف توکن معتبر
    ok, info = antiban_consume(token, 12345)
    record("مصرف توکن معتبر",
           ok is True and isinstance(info, dict) and info.get("action") == "sessterm",
           f"ok={ok} action={info.get('action') if isinstance(info, dict) else '?'}")

    # 3. مصرف مجدد → ناموفق
    ok, info = antiban_consume(token, 12345)
    record("مصرف مجدد (replay attack) → blocked",
           ok is False, f"ok={ok} info={info}")

    # 4. توکن متعلق به کاربر دیگر
    token2 = antiban_request_confirmation("tag2", "tfago", 99999)
    ok, info = antiban_consume(token2, 12345)  # wrong user
    record("مصرف توکن کاربر دیگر → blocked",
           ok is False and info == "wrong_user",
           f"ok={ok} info={info}")

    # 5. توکن منقضی (شبیه‌سازی)
    token3 = antiban_request_confirmation("tag3", "sessterm", 12345)
    _ANTIBAN_PENDING[token3]["expires"] = time.time() - 1  # منقضی شد
    ok, info = antiban_consume(token3, 12345)
    record("مصرف توکن منقضی → blocked",
           ok is False, f"ok={ok} info={info}")


def test_integration_guarded_handlers():
    print("─" * 60)
    print("🔌 تست: integration با handlerها")

    # تست اینکه پس از اعمال گارد، handler باید متد show_antiban_warning رو صدا بزنه
    # این یه تست structural هست - بررسی می‌کنه که متدها patch شدن
    from main import AdminBot
    has_warning = hasattr(AdminBot, "_show_antiban_warning")
    has_confirm = hasattr(AdminBot, "_handle_antiban_confirm")
    has_guarded = "antiban_guarded_action" in dir(__import__("main"))

    record("AdminBot._show_antiban_warning", has_warning, "متد اضافه شده")
    record("AdminBot._handle_antiban_confirm", has_confirm, "متد اضافه شده")
    record("antiban_guarded_action در main", has_guarded, "تابع سراسری")


async def main():
    print("=" * 60)
    print("🛡️ Anti-Ban Protection Test Suite")
    print("=" * 60)

    try:
        test_normalize_phone()
        test_is_iranian_phone()
        test_phone_country_hint()
        test_is_dangerous_account()
        test_antiban_guarded_action()
        test_antiban_token_flow()
        test_integration_guarded_handlers()
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

    with open(os.path.join(os.path.dirname(__file__), "test_antiban_results.json"), "w", encoding="utf-8") as f:
        json.dump({
            "total": len(RESULTS),
            "passed": passed,
            "failed": failed,
            "results": RESULTS,
            "timestamp": time.time(),
        }, f, ensure_ascii=False, indent=2)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
