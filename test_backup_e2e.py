#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تست end-to-end سیستم بکاپ و ری‌استور
- چرخه کامل: backup → خراب کردن → restore
- چک کردن فایل‌های ارسالی
- چک کردن همه‌ی فایل‌های موجود در بکاپ
"""
import asyncio
import os
import sys
import json
import tempfile
import unittest.mock as mock
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


RESULTS = []


def record(name, passed, details=""):
    RESULTS.append({"name": name, "passed": passed, "details": details})
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {details}")


async def test_full_backup_cycle():
    """تست کامل: backup → خراب کردن → restore → چک همه چیز"""
    print("─" * 60)
    print("🔄 تست: چرخه کامل backup → restore")

    os.environ['ADMIN_ID'] = '12345678'

    from main import (
        init_db, _conn, upsert_user, ROLE_OWNER, SaaSBot,
        CONFIG_FILE, restore_backup_from_zip, build_backup_zip,
        _backup_file_name
    )

    init_db()
    test_owner = 12345678

    # پاک کردن همه‌ی کاربران تست قبلی
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id NOT IN (?, ?, ?)",
                  (12345670, 12345678, 87654321))
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)

    # setup
    upsert_user(test_owner, "owner", "مالک")
    backup_users = {test_owner}
    backup_config = {
        "acc_1": {"owner_user_id": test_owner, "phone": "+989000000001"},
        "acc_2": {"owner_user_id": test_owner, "phone": "+989009990002"}
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(backup_config, f)

    # ساخت بکاپ
    backup_path = os.path.join("/tmp", _backup_file_name())
    ok = build_backup_zip(backup_path)
    record("ساخت بکاپ موفق", ok, f"size={os.path.getsize(backup_path):,}")

    # چک محتوا
    import zipfile
    with zipfile.ZipFile(backup_path, "r") as zf:
        names = set(zf.namelist())
    expected = {"saas.db", "bot_data.db", "config.json", "backup_manifest.json"}
    record("شامل فایل‌های ضروری", expected.issubset(names), f"got={names}")

    # خراب کردن
    with open(CONFIG_FILE, "w") as f:
        json.dump({"corrupted": True}, f)
    upsert_user(99999999, "garbage", "زباله")

    # restore
    ok, msg = restore_backup_from_zip(backup_path)
    record("ری‌استور موفق", ok, f"msg={msg[:60]}")

    # بررسی config
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        record("config.json برگشت", set(cfg.keys()) == {"acc_1", "acc_2"},
               f"keys={list(cfg.keys())}")

    # بررسی users - فقط مطمئن می‌شیم garbage حذف شده
    with _conn() as c:
        users = {row["user_id"] for row in c.execute("SELECT user_id FROM users")}
    record("garbage user حذف شد", 99999999 not in users, f"users={users}")
    record("OWNER باقی موند", test_owner in users, f"users={users}")

    # پاک کردن
    os.remove(backup_path)
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)


async def test_send_backup_through_dispatcher():
    """تست: send_backup از طریق dispatcher واقعی ربات"""
    print("─" * 60)
    print("📤 تست: ارسال بکاپ از طریق dispatcher")

    os.environ['ADMIN_ID'] = '12345678'
    from main import init_db, _conn, upsert_user, SaaSBot

    init_db()
    test_owner = 12345678
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (test_owner,))
    upsert_user(test_owner, "owner", "مالک")

    class FakeClient:
        def __init__(self):
            self.handlers = {}
            self.sent_files = []
            self.sent_messages = []
        def on(self, event_type):
            def decorator(f):
                self.handlers[str(event_type)] = f
                return f
            return decorator
        async def send_file(self, chat, path, caption="", **kwargs):
            self.sent_files.append({"path": path, "caption": caption})
            return mock.MagicMock()
        async def send_message(self, chat, msg, **kwargs):
            self.sent_messages.append({"chat": chat, "msg": msg})

    client = FakeClient()
    bot = SaaSBot(client)
    bot.client = client
    bot._register_handlers()

    cb_handler = None
    for k, v in client.handlers.items():
        if 'CallbackQuery' in k:
            cb_handler = v
            break

    class MockEvent:
        def __init__(self, data, sender_id):
            self.data = data.encode() if isinstance(data, str) else data
            self.sender_id = sender_id
            self.chat_id = sender_id
            self.raw_text = ""
            self.message = mock.MagicMock()
            self.query = "mock"
            self.sender = type('S', (), {'id': sender_id, 'first_name': 'مالک'})()
        async def answer(self, text=None, alert=False):
            pass
        async def edit(self, text, buttons=None):
            pass
        async def respond(self, text, buttons=None):
            pass
        async def delete(self):
            pass

    event = MockEvent("owner_backup", test_owner)
    await cb_handler(event)

    record("فایل بکاپ ارسال شد", len(client.sent_files) == 1, f"files={len(client.sent_files)}")
    if client.sent_files:
        path = client.sent_files[0]["path"]
        record("فایل بکاپ معتبر zip", path.endswith(".zip"), os.path.basename(path))
        # فایل بعد از ارسال پاک می‌شه (در finally)، پس قبل از اون چک کنیم
        # یا اگه پاک شده از log سایز بگیریم
        caption = client.sent_files[0]["caption"]
        record("کپشن معتبر", "Backup" in caption or "بکاپ" in caption,
               f"caption={caption[:60]}")

    record("پیام تأیید ارسال شد", len(client.sent_messages) >= 1,
           f"messages={len(client.sent_messages)}")
    if client.sent_messages:
        msg = client.sent_messages[0]["msg"]
        record("پیام تأیید محتوای درست", "Backup" in msg or "بکاپ" in msg,
               f"msg={msg[:60]}")


def test_scheduler_recipients():
    """تست: scheduler همه OWNER/ADMIN ها رو می‌شناسه"""
    print("─" * 60)
    print("⏰ تست: scheduler recipients")

    os.environ['ADMIN_ID'] = '12345678'
    from main import init_db, _conn, upsert_user, ROLE_OWNER, ROLE_ADMIN, AdminBot

    init_db()
    test_owner = 12345678
    test_admin = 11111111
    test_user = 22222222
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id IN (?, ?, ?)",
                  (test_owner, test_admin, test_user))
    upsert_user(test_owner, "owner", "مالک")
    upsert_user(test_admin, "admin", "ادمین")
    upsert_user(test_user, "user", "کاربر")

    # تنظیم نقش - از طریق add_admin
    from main import add_admin_or_reseller
    add_admin_or_reseller(test_admin, ROLE_ADMIN, test_owner)

    admin_bot = AdminBot.__new__(AdminBot)
    admin_bot.standalone = False
    admin_bot.admin_ids = set()

    recipients = admin_bot._backup_recipient_ids()
    record("OWNER در recipients", test_owner in recipients, f"recipients={recipients}")
    record("ADMIN در recipients", test_admin in recipients, f"recipients={recipients}")
    record("USER عادی حذف", test_user not in recipients, f"recipients={recipients}")


def test_event_respond_in_callback():
    """تست: confirm که event.respond در CallbackQuery کار نمی‌کنه (regression)"""
    print("─" * 60)
    print("🔍 تست: event.respond در CallbackQuery")

    from telethon.events import CallbackQuery
    # confirm که CallbackQuery.respond وجود نداره (این دلیل باگ قبلی بود)
    record("CallbackQuery ندارد respond", not hasattr(CallbackQuery, 'respond'),
           "تایید شد - این دلیل اصلی باگ قبلی بود")


def test_backup_includes_all_files():
    """تست: بکاپ شامل همه فایل‌های مهم هست"""
    print("─" * 60)
    print("📦 تست: محتوای بکاپ")

    from main import _collect_backup_files
    files = _collect_backup_files()
    record("شامل saas.db", "saas.db" in files, f"keys={list(files.keys())}")
    record("شامل bot_data.db", "bot_data.db" in files, f"keys={list(files.keys())}")


def test_restore_validates_zip():
    """تست: restore فایل نامعتبر رو رد می‌کنه"""
    print("─" * 60)
    print("🛡 تست: validation")

    import zipfile
    # یه فایل ZIP نامعتبر
    bad_zip = "/tmp/bad_backup.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("random.txt", "not a backup")

    from main import validate_backup_zip, restore_backup_from_zip
    valid, msg = validate_backup_zip(bad_zip)
    record("ZIP نامعتبر رد شد", not valid, f"msg={msg[:60]}")

    ok, msg = restore_backup_from_zip(bad_zip)
    record("restore فایل نامعتبر رو رد کرد", not ok, f"msg={msg[:60]}")

    os.remove(bad_zip)


async def test_backup_race_condition():
    """تست: اگه کاربر چندبار بکاپ بزنه، فقط یکی اجرا بشه."""
    print("─" * 60)
    print("🔒 تست: race condition روی backup")
    os.environ['ADMIN_ID'] = '12345678'
    from main import init_db, _conn, upsert_user, SaaSBot

    init_db()
    test_owner = 12345678
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id = ?", (test_owner,))
    upsert_user(test_owner, "owner", "مالک")

    class FakeClient:
        def __init__(self):
            self.sent_files = []
            self.sent_messages = []
        async def send_file(self, chat, path, caption="", **kwargs):
            await asyncio.sleep(0.2)
            self.sent_files.append({"path": path})
            return mock.MagicMock()
        async def send_message(self, chat, msg, **kwargs):
            self.sent_messages.append({"msg": msg})

    client = FakeClient()
    bot = SaaSBot(client)
    bot.client = client

    class MockEvent:
        def __init__(self, sender_id):
            self.sender_id = sender_id
            self.chat_id = sender_id
            self.raw_text = ""
            self.data = b"owner_backup"
            self.message = mock.MagicMock()
            self.query = "mock"
            self.sender = type('S', (), {'id': sender_id, 'first_name': 'مالک'})()
        async def answer(self, text=None, alert=False):
            pass
        async def edit(self, text, buttons=None):
            pass
        async def respond(self, text, buttons=None):
            pass
        async def delete(self):
            pass

    await asyncio.gather(
        bot._owner_show_backup(MockEvent(test_owner)),
        bot._owner_show_backup(MockEvent(test_owner)),
        bot._owner_show_backup(MockEvent(test_owner)),
    )
    record("فقط یک بکاپ ارسال شد (race condition)", len(client.sent_files) == 1,
           f"files={len(client.sent_files)}")


async def main():
    print("=" * 60)
    print("🧪 تست جامع سیستم بکاپ و ری‌استور")
    print("=" * 60)

    try:
        await test_full_backup_cycle()
        await test_send_backup_through_dispatcher()
        test_scheduler_recipients()
        test_event_respond_in_callback()
        test_backup_includes_all_files()
        test_restore_validates_zip()
        await test_backup_race_condition()
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
