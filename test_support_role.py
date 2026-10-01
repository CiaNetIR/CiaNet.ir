#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Support Ticket Role Preservation Test (v1.7.1)
=================================================
Tests that OWNER/ADMIN/RESELLER keep their role after closing a support ticket.
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


def test_owner_role_preserved():
    """مهم‌ترین تست: OWNER بعد از بستن تیکت، همچنان OWNER است."""
    print("─" * 60)
    print("👑 تست: OWNER نقش خود را بعد از بستن تیکت حفظ می‌کند")

    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. باید self._role رو صدا بزنه
    uses_real_role = (
        'self._role(event.sender_id)' in content
    )
    record("استفاده از self._role", uses_real_role,
           "real_role گرفته می‌شه ✓" if uses_real_role else "")

    # 2. نباید hardcode شده باشه در _user_support_end
    # جستجو در اطراف _user_support_end
    idx = content.find("async def _user_support_end")
    if idx == -1:
        record("پیدا کردن _user_support_end", False, "not found")
        return
    snippet = content[idx:idx + 1500]
    has_hardcoded_user = "ROLE_USER" in snippet and "real_role" not in snippet
    record("بدون ROLE_USER هاردکد", not has_hardcoded_user,
           "فیکس شده ✓" if not has_hardcoded_user else "هنوز هاردکده")


def test_other_handlers():
    print("─" * 60)
    print("🔍 تست: سایر handler ها از self._role استفاده می‌کنن")
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()

    # تمام موارد _show_menu_for_role بعد از اکشن‌ها
    import re
    matches = re.findall(
        r"await\s+self\._show_menu_for_role\([^)]*\)",
        content
    )
    record("همه _show_menu_for_role بررسی شدن", len(matches) > 0,
           f"{len(matches)} مورد یافت شد")

    # چک کن hardcode‌های نامربوط
    suspicious = []
    for m in matches:
        if "ROLE_USER" in m and "self._role" not in m and "real_role" not in m:
            suspicious.append(m)
    record("بدون hardcode ROLE_USER", len(suspicious) == 0,
           f"{len(suspicious)} مورد مشکوک" if suspicious else "همه از real_role استفاده می‌کنن")


def test_ticket_end_to_end():
    print("─" * 60)
    print("🎫 تست: end-to-end ticket flow")
    from main import (
        get_role, get_open_ticket, create_ticket,
        close_ticket, ticket_message_count, init_db
    )

    # init db
    init_db()

    # set test owner
    test_owner_id = 7777777
    test_admin_id = 8888888
    test_user_id = 9999999

    with sqlite3.connect("saas.db") as c:
        c.execute("DELETE FROM admins WHERE user_id IN (?, ?)",
                  (test_owner_id, test_admin_id))
        c.execute("INSERT OR REPLACE INTO admins (user_id, role, created_at) VALUES (?, ?, ?)",
                  (test_admin_id, "ADMIN", "2026-01-01 00:00:00"))
        c.execute("DELETE FROM tickets WHERE user_id IN (?, ?, ?)",
                  (test_owner_id, test_admin_id, test_user_id))
        c.commit()

    # mock OWNER (use env)
    import os
    old_env = os.environ.get("ADMIN_ID")
    os.environ["ADMIN_ID"] = str(test_owner_id)

    try:
        # 1. Owner بزنه پشتیبانی → تیکت ساخته می‌شه
        ticket = get_open_ticket(test_owner_id)
        if not ticket:
            tid = create_ticket(test_owner_id)
        else:
            tid = ticket["id"]
        record("ساخت تیکت برای OWNER", tid > 0, f"ticket_id={tid}")

        # 2. OWNER نقش OWNER داره
        role_owner = get_role(test_owner_id, test_owner_id)
        record("OWNER شناسایی می‌شه",
               role_owner == "OWNER",
               f"role={role_owner}")

        # 3. ADMIN نقش ADMIN داره
        role_admin = get_role(test_admin_id, test_owner_id)
        record("ADMIN شناسایی می‌شه",
               role_admin == "ADMIN",
               f"role={role_admin}")

        # 4. USER عادی نقش USER داره
        role_user = get_role(test_user_id, test_owner_id)
        record("USER عادی شناسایی می‌شه",
               role_user == "USER",
               f"role={role_user}")

        # 5. نقش بعد از بستن تیکت نباید عوض شه
        # این دقیقاً همون چیزیه که قبلاً باگ داشت
        close_ticket(tid)
        role_after = get_role(test_owner_id, test_owner_id)
        record("OWNER بعد از بستن تیکت هنوز OWNER است",
               role_after == "OWNER",
               f"role={role_after}")

    finally:
        # cleanup
        if old_env:
            os.environ["ADMIN_ID"] = old_env
        else:
            os.environ.pop("ADMIN_ID", None)
        with sqlite3.connect("saas.db") as c:
            c.execute("DELETE FROM tickets WHERE user_id IN (?, ?, ?)",
                      (test_owner_id, test_admin_id, test_user_id))
            c.execute("DELETE FROM admins WHERE user_id = ?",
                      (test_admin_id,))
            c.commit()


def test_show_menu_for_role_signature():
    print("─" * 60)
    print("🔍 تست: تابع _show_menu_for_role درست تعریف شده")
    from main import SaaSBot
    import inspect

    sig = inspect.signature(SaaSBot._show_menu_for_role)
    params = list(sig.parameters.keys())
    record("پارامترهای صحیح",
           params == ["self", "chat", "role", "edit_event"],
           f"params={params}")


async def main():
    print("=" * 60)
    print("🛠 Support Ticket Role Test Suite (v1.7.1)")
    print("=" * 60)

    try:
        test_owner_role_preserved()
        test_other_handlers()
        test_show_menu_for_role_signature()
        test_ticket_end_to_end()
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
