#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backup Scheduler Test Suite
===========================
Tests the new multi-time backup scheduler (default 00:00 and 12:00 Iran time).
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


RESULTS = []


def record(name, passed, details=""):
    RESULTS.append({"name": name, "passed": passed, "details": details})
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {details}")


def test_backup_hours_constant():
    print("─" * 60)
    print("⏰ تست: ثابت BACKUP_HOURS_IRAN")

    from main import BACKUP_HOURS_IRAN, BACKUP_HOUR_IRAN
    record("BACKUP_HOURS_IRAN وجود دارد", isinstance(BACKUP_HOURS_IRAN, list),
           f"type={type(BACKUP_HOURS_IRAN).__name__}")
    record("BACKUP_HOURS_IRAN شامل 0 و 12",
           0 in BACKUP_HOURS_IRAN and 12 in BACKUP_HOURS_IRAN,
           f"={BACKUP_HOURS_IRAN}")
    record("BACKUP_HOUR_IRAN backward-compat",
           BACKUP_HOUR_IRAN == BACKUP_HOURS_IRAN[0],
           f"BACKUP_HOUR_IRAN={BACKUP_HOUR_IRAN}")


def test_next_backup_time():
    print("─" * 60)
    print("📅 تست: محاسبه‌ی زمان بکاپ بعدی")

    from main import AdminBot, BACKUP_HOURS_IRAN

    # تست ۱: الان ساعت ۱۰ صبح → بکاپ بعدی ۱۲ ظهر
    tz = timezone(timedelta(hours=3, minutes=30))  # Iran
    now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=tz)
    nxt = AdminBot._next_backup_time(now)
    expected = datetime(2024, 1, 15, 12, 0, 0, tzinfo=tz)
    record("۱۰ صبح → ۱۲ ظهر",
           nxt == expected,
           f"now=10:00 → next={nxt.strftime('%H:%M')} (expected 12:00)")

    # تست ۲: الان ساعت ۱۴ → بکاپ بعدی ۰۰:۰۰ فردا
    now = datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)
    nxt = AdminBot._next_backup_time(now)
    expected = datetime(2024, 1, 16, 0, 0, 0, tzinfo=tz)
    record("۱۴ ظهر → ۰۰:۰۰ فردا",
           nxt == expected,
           f"now=14:00 → next={nxt.strftime('%m-%d %H:%M')} (expected 01-16 00:00)")

    # تست ۳: الان ساعت ۰۰:۰۰ (همان ساعت بکاپ) → بعدی ۱۲:۰۰
    now = datetime(2024, 1, 15, 0, 0, 0, tzinfo=tz)
    nxt = AdminBot._next_backup_time(now)
    expected = datetime(2024, 1, 15, 12, 0, 0, tzinfo=tz)
    record("۰۰:۰۰ → ۱۲:۰۰ (همان روز)",
           nxt == expected,
           f"now=00:00 → next={nxt.strftime('%H:%M')} (expected 12:00)")

    # تست ۴: الان ساعت ۱۱:۵۹ → ۱۲:۰۰
    now = datetime(2024, 1, 15, 11, 59, 0, tzinfo=tz)
    nxt = AdminBot._next_backup_time(now)
    expected = datetime(2024, 1, 15, 12, 0, 0, tzinfo=tz)
    record("۱۱:۵۹ → ۱۲:۰۰",
           nxt == expected,
           f"now=11:59 → next={nxt.strftime('%H:%M')} (expected 12:00)")

    # تست ۵: الان ساعت ۱۲:۰۰ دقیق → ۰۰:۰۰ فردا
    now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=tz)
    nxt = AdminBot._next_backup_time(now)
    expected = datetime(2024, 1, 16, 0, 0, 0, tzinfo=tz)
    record("۱۲:۰۰ → ۰۰:۰۰ فردا",
           nxt == expected,
           f"now=12:00 → next={nxt.strftime('%m-%d %H:%M')} (expected 01-16 00:00)")

    # تست ۶: آخر روز (۲۳:۵۹) → ۰۰:۰۰ فردا
    now = datetime(2024, 1, 15, 23, 59, 0, tzinfo=tz)
    nxt = AdminBot._next_backup_time(now)
    expected = datetime(2024, 1, 16, 0, 0, 0, tzinfo=tz)
    record("۲۳:۵۹ → ۰۰:۰۰ فردا",
           nxt == expected,
           f"now=23:59 → next={nxt.strftime('%m-%d %H:%M')} (expected 01-16 00:00)")


def test_custom_hours():
    print("─" * 60)
    print("🔧 تست: ساعات سفارشی")

    # شبیه‌سازی BACKUP_HOURS_IRAN = [4, 16]
    import main
    original = main.BACKUP_HOURS_IRAN
    try:
        main.BACKUP_HOURS_IRAN = [4, 16]
        tz = timezone(timedelta(hours=3, minutes=30))
        now = datetime(2024, 1, 15, 8, 0, 0, tzinfo=tz)
        nxt = main.AdminBot._next_backup_time(now)
        expected = datetime(2024, 1, 15, 16, 0, 0, tzinfo=tz)
        record("سفارشی [4, 16] + ساعت ۸ → ۱۶",
               nxt == expected,
               f"→ {nxt.strftime('%H:%M')}")
    finally:
        main.BACKUP_HOURS_IRAN = original


def test_three_times_per_day():
    print("─" * 60)
    print("🔁 تست: سه نوبت در روز")

    import main
    original = main.BACKUP_HOURS_IRAN
    try:
        main.BACKUP_HOURS_IRAN = [0, 8, 16]  # سه نوبت
        tz = timezone(timedelta(hours=3, minutes=30))
        test_cases = [
            (datetime(2024, 1, 15, 1, 0, 0, tzinfo=tz), 8),    # ۱ صبح → ۸
            (datetime(2024, 1, 15, 9, 0, 0, tzinfo=tz), 16),   # ۹ صبح → ۱۶
            (datetime(2024, 1, 15, 17, 0, 0, tzinfo=tz), 0),   # ۵ عصر → ۰ فردا
        ]
        for now, exp_hour in test_cases:
            nxt = main.AdminBot._next_backup_time(now)
            record(f"سه‌نوبت: now={now.strftime('%H:%M')} → {nxt.strftime('%H:%M')}",
                   nxt.hour == exp_hour,
                   f"expected={exp_hour}:00")
    finally:
        main.BACKUP_HOURS_IRAN = original


async def main():
    print("=" * 60)
    print("⏰ Backup Scheduler Test Suite")
    print("=" * 60)

    try:
        test_backup_hours_constant()
        test_next_backup_time()
        test_custom_hours()
        test_three_times_per_day()
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
