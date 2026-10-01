#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تست‌های پنل v2.0:
- ساختار ۵ بخشی پنل ادمین (Ⅰ..Ⅴ)
- دکمه‌ی نمایندگی در پنل کاربر
- صفحه‌ی اطلاعات نمایندگی
- درخواست نمایندگی و ثبت در DB
"""
import asyncio
import os
import sys
import unittest.mock as mock

sys.path.insert(0, ".")
os.environ.setdefault("ADMIN_ID", "12345678")

from main import (
    init_db, _conn, upsert_user,
    ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER, ROLE_USER,
    SaaSBot, UI, NAV_HOME,
)


def record(name, passed, details=""):
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {details}")
    return passed


# ─────────────────────────────────────────────────────
#  Mock ها
# ─────────────────────────────────────────────────────

class FakeSelfbot:
    def load_config(self):
        return {}

    def iran_now(self):
        from datetime import datetime, timezone, timedelta
        return datetime.now(timezone(timedelta(hours=3, minutes=30)))

    def _user_has_logged_in_account(self, uid):
        return False

    def _user_selfbot_stats(self, uid):
        return (0, 0, [])


class FakeClient:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat, msg, buttons=None, **kwargs):
        self.sent_messages.append({
            "chat": chat, "msg": msg, "buttons": buttons or [],
        })

    async def send_file(self, *a, **k):
        return mock.MagicMock()


class MockEvent:
    def __init__(self, sender_id, data=b"x"):
        self.sender_id = sender_id
        self.chat_id = sender_id
        self.raw_text = ""
        self.data = data if isinstance(data, bytes) else data.encode()
        self.message = mock.MagicMock()
        self.query = "mock"
        self.sender = type('S', (), {
            'id': sender_id, 'first_name': 'علی', 'username': 'ali'
        })()

    async def answer(self, text=None, alert=False):
        pass

    async def edit(self, text, buttons=None):
        self.last_edit = {"text": text, "buttons": buttons or []}


# ─────────────────────────────────────────────────────
#  تست‌ها
# ─────────────────────────────────────────────────────

async def test_admin_hub_has_5_sections():
    """پنل ادمین باید ۵ بخش با شماره رومی داشته باشه."""
    print("─" * 60)
    print("🎛 تست: پنل ادمین ۵ بخشی")
    init_db()
    owner_id = 12345678
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (owner_id,))
    upsert_user(owner_id, "owner", "مالک")

    bot = SaaSBot(FakeSelfbot())
    bot.client = FakeClient()
    event = MockEvent(owner_id, b"admin_hub")
    await bot._show_admin_hub(event, ROLE_OWNER)

    text = event.last_edit['text']
    buttons = event.last_edit['buttons']

    # ۵ شماره رومی باید در دکمه‌ها باشه
    all_labels = [b.text for row in buttons for b in row]
    record("Ⅰ فروش در پنل", any("Ⅰ" in l and "فروش" in l for l in all_labels),
           f"labels={[l for l in all_labels if 'Ⅰ' in l]}")
    record("Ⅱ کاربران در پنل", any("Ⅱ" in l and "کاربران" in l for l in all_labels),
           f"labels={[l for l in all_labels if 'Ⅱ' in l]}")
    record("Ⅲ پشتیبانی در پنل", any("Ⅲ" in l and "پشتیبانی" in l for l in all_labels),
           f"labels={[l for l in all_labels if 'Ⅲ' in l]}")
    record("Ⅳ سیستم در پنل", any("Ⅳ" in l and "سیستم" in l for l in all_labels),
           f"labels={[l for l in all_labels if 'Ⅳ' in l]}")
    record("Ⅴ امنیت در پنل", any("Ⅴ" in l and "امنیت" in l for l in all_labels),
           f"labels={[l for l in all_labels if 'Ⅴ' in l]}")

    # متن کوتاه باشه (نه بلوک شعاری)
    record("متن کوتاه (< 200 کاراکتر)",
           len(text) < 200, f"len={len(text)}")
    record("بدون شعار قدیمی",
           "بهترین باش" not in text, f"text={text[:80]}")


async def test_admin_hub_no_security_for_admin():
    """ADMIN (non-owner) نباید بخش Ⅴ امنیت رو ببینه."""
    print("─" * 60)
    print("🎛 تست: ADMIN بخش امنیت نمی‌بینه")
    init_db()
    admin_id = 87654321
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (admin_id,))
    upsert_user(admin_id, "admin", "ادمین")

    bot = SaaSBot(FakeSelfbot())
    bot.client = FakeClient()
    event = MockEvent(admin_id, b"admin_hub")
    await bot._show_admin_hub(event, ROLE_ADMIN)

    all_labels = [b.text for row in event.last_edit['buttons'] for b in row]
    record("بدون Ⅴ امنیت", not any("Ⅴ" in l for l in all_labels),
           f"labels={all_labels}")
    record("با Ⅰ فروش", any("Ⅰ" in l for l in all_labels), "")


async def test_user_panel_has_reseller_button():
    """پنل USER باید دکمه‌ی نمایندگی داشته باشه."""
    print("─" * 60)
    print("🤝 تست: دکمه نمایندگی در پنل کاربر")
    init_db()
    user_id = 11111111
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM reseller_applications WHERE user_id = ?", (user_id,))
    upsert_user(user_id, "user", "کاربر تست")

    bot = SaaSBot(FakeSelfbot())
    bot.client = FakeClient()
    event = MockEvent(user_id, b"start")
    await bot._show_menu_for_role(user_id, ROLE_USER, edit_event=event)

    all_labels = [b.text for row in event.last_edit['buttons'] for b in row]
    record("دکمه '🤝 نمایندگی سلف' وجود داره",
           any("نمایندگی سلف" in l for l in all_labels),
           f"labels={[l for l in all_labels if 'نمایند' in l]}")


async def test_user_panel_no_reseller_for_owner():
    """پنل OWNER نباید دکمه‌ی نمایندگی داشته باشه."""
    print("─" * 60)
    print("🤝 تست: OWNER دکمه نمایندگی نداره")
    init_db()
    owner_id = 12345678
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (owner_id,))
        c.execute("DELETE FROM reseller_applications WHERE user_id = ?", (owner_id,))
    upsert_user(owner_id, "owner", "مالک")

    bot = SaaSBot(FakeSelfbot())
    bot.client = FakeClient()
    event = MockEvent(owner_id, b"start")
    await bot._show_menu_for_role(owner_id, ROLE_OWNER, edit_event=event)

    all_labels = [b.text for row in event.last_edit['buttons'] for b in row]
    record("بدون دکمه نمایندگی", not any("نمایندگی سلف" in l for l in all_labels),
           f"labels={[l for l in all_labels if 'نمایند' in l]}")


async def test_reseller_info_page():
    """صفحه اطلاعات نمایندگی باید مزایا و دکمه درخواست داشته باشه."""
    print("─" * 60)
    print("🤝 تست: صفحه اطلاعات نمایندگی")
    init_db()
    user_id = 22222222
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM reseller_applications WHERE user_id = ?", (user_id,))
    upsert_user(user_id, "user", "کاربر")

    bot = SaaSBot(FakeSelfbot())
    bot.client = FakeClient()
    event = MockEvent(user_id, b"user_reseller_info")
    await bot._show_reseller_info(event)

    text = event.last_edit['text']
    buttons = event.last_edit['buttons']
    all_labels = [b.text for row in buttons for b in row]

    record("متن شامل 'ربات اختصاصی'", "ربات اختصاصی" in text, "")
    record("متن شامل 'درآمد خودکار'", "درآمد خودکار" in text or "درآمد" in text, "")
    record("دکمه درخواست نمایندگی", any("درخواست نمایندگی" in l for l in all_labels), "")
    record("دکمه بازگشت", any("بازگشت" in l or "منوی اصلی" in l for l in all_labels), "")


async def test_apply_reseller_creates_record():
    """درخواست نمایندگی باید رکورد در DB ثبت کنه."""
    print("─" * 60)
    print("🤝 تست: ثبت درخواست نمایندگی")
    init_db()
    user_id = 33333333
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM reseller_applications WHERE user_id = ?", (user_id,))
    upsert_user(user_id, "user", "کاربر")

    bot = SaaSBot(FakeSelfbot())
    bot.client = FakeClient()
    event = MockEvent(user_id, b"user_reseller_apply")
    await bot._apply_reseller(event)

    # چک کن رکورد ثبت شده
    with _conn() as c:
        row = c.execute(
            "SELECT status FROM reseller_applications WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    record("رکورد ثبت شد", row is not None, f"row={dict(row) if row else None}")
    record("وضعیت pending", row and row["status"] == "pending",
           f"status={row['status'] if row else None}")


async def test_apply_reseller_idempotent():
    """درخواست تکراری نباید ثبت بشه."""
    print("─" * 60)
    print("🤝 تست: درخواست تکراری idempotent")
    init_db()
    user_id = 44444444
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM reseller_applications WHERE user_id = ?", (user_id,))
    upsert_user(user_id, "user", "کاربر")

    bot = SaaSBot(FakeSelfbot())
    bot.client = FakeClient()

    # اول
    event = MockEvent(user_id, b"user_reseller_apply")
    await bot._apply_reseller(event)

    # دوم (باید alert بشه نه ثبت جدید)
    event2 = MockEvent(user_id, b"user_reseller_apply")
    await bot._apply_reseller(event2)

    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM reseller_applications WHERE user_id = ?",
            (user_id,)
        ).fetchall()

    record("فقط ۱ رکورد", len(rows) == 1, f"count={len(rows)}")


async def main():
    passed = 0
    failed = 0
    tests = [
        test_admin_hub_has_5_sections,
        test_admin_hub_no_security_for_admin,
        test_user_panel_has_reseller_button,
        test_user_panel_no_reseller_for_owner,
        test_reseller_info_page,
        test_apply_reseller_creates_record,
        test_apply_reseller_idempotent,
    ]
    for t in tests:
        try:
            await t()
            # شمارش تقریبی بر اساس ✅ در خروجی
        except Exception as e:
            print(f"❌ خطای بحرانی: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    # شمارش بر اساس تعداد ✅ در خروجی
    print()
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
