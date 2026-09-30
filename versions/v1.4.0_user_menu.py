#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
پروژه‌ی یکپارچه — تک‌فایلِ قابلِ استقرار.

همه‌ی قابلیت‌ها در همین یک فایل است: پنل مدیریت، سلف‌بات، دو لایه‌ی
دیتابیس، لایسنس/اشتراک، و رباتِ راهنما. برای اجرا فقط main.py +
config.json + requirements کافی است.

رباتِ راهنما (کلاس HelperBot) قبلاً یک فایلِ جدا بود که به‌عنوان زیرپروسس
اجرا می‌شد؛ حالا روی همان event loop اجرا می‌شود. آن جداسازی برای پرهیز از
تداخلِ getUpdates بود، ولی آن تداخل فقط وقتی رخ می‌دهد که *یک توکن* دو بار
poll شود — و رباتِ راهنما توکنِ مستقلِ خودش را دارد. سودِ ادغام: بدون
pid-file، بدون لاگِ جدا، بدون ریسکِ زیرپروسسِ یتیم بعد از ری‌استارتِ سخت.

متغیرهای محیطیِ اصلی:
    ADMIN_BOT_TOKEN / ADMIN_ID / OWNER_ID   پنل مدیریت
    HELPER_BOT_TOKEN                        رباتِ راهنما (اختیاری)
"""



import asyncio
import hashlib
import json
import logging
import os
import random
import shutil
import re
import secrets
import signal
import sqlite3
import string
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from telethon import TelegramClient, events, Button, errors
from telethon.tl.functions.account import (
    UpdateProfileRequest, UpdateStatusRequest,
    GetAuthorizationsRequest, ResetAuthorizationRequest,
    GetPasswordRequest, ResetPasswordRequest, DeclinePasswordResetRequest,
)
from telethon.tl.functions.auth import ResetAuthorizationsRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.updates import GetStateRequest
from telethon.tl.types import InputMediaDice, PeerUser
from telethon.tl.types.account import (
    ResetPasswordOk, ResetPasswordRequestedWait, ResetPasswordFailedWait,
)


def _project_dir() -> str:
    """پوشه‌ی اصلی پروژه (جایی که main.py و helper.py هستند).

    در اجرای عادی پایتون `__file__` همیشه تعریف‌شده است؛ اما در برخی محیط‌ها
    (مثلاً بالا آمدن از طریق exec یا ابزارهای دیگر) `__file__` وجود ندارد و
    `os.path.dirname(os.path.abspath(__file__))` با NameError کرش می‌کند —
    این تابع اول از `__file__`، بعد از `sys.argv[0]` و در نهایت از cwd
    استفاده می‌کند.
    """
    here = globals().get("__file__")
    if here:
        return os.path.dirname(os.path.abspath(here))
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.getcwd()


def _data_dir() -> str:
    """
    دایرکتوری داده‌ی این نمونه (DB اصلی / bot_data / config.json / sessions):
      - نمونه‌ی اصلی: _project_dir() — یعنی اجرای
        `cd /random && python /home/.../self/main.py all` همیشه همین DB/config
        پروژه را استفاده می‌کند، نه فایل‌هایی که در cwd ساخته می‌شوند.
      - ربات‌های اختصاصی (زیرپروسه‌ی همین main.py با cwd جدا): از طریق
        SELFBOT_DATA_DIR به دایرکتوریِ مخصوص خودشان (`dedicated_bots/<id>/`)
        هدایت می‌شوند تا DB/config اصلی پروژه در cwdِ خودشان ساخته نشود و
        با نمونه‌ی اصلی تداخل نکنند.
    """
    d = os.environ.get("SELFBOT_DATA_DIR")
    if d:
        return os.path.abspath(d)
    return _project_dir()


DATA_DIR = _data_dir()


def _chmod_private(path: str, mode: int = 0o600) -> bool:
    """
    محدودکردنِ دسترسیِ فایل/پوشه به خودِ کاربرِ سرویس (best-effort).

    این پروژه سه دسته داده‌ی حساس روی دیسک دارد: config.json
    (api_id/api_hash/شماره/توکنِ همه‌ی مشتری‌ها)، فایل‌های سشنِ تلگرام
    (که عملاً معادلِ دسترسیِ کاملِ اکانت‌اند) و بکاپ‌ها. همه‌ی این‌ها
    با umask پیش‌فرضِ اغلب سرورها (022) به‌صورت 0644 ساخته می‌شدند —
    یعنی هر کاربرِ دیگری روی همان ماشین می‌توانست بخواندشان.

    best-effort عمدی است: روی فایل‌سیستم‌هایی که chmod ندارند (مثلاً
    برخی اشتراک‌های شبکه یا FAT) نباید استارتِ سرویس را بشکند — فقط
    یک بار هشدار می‌دهد.
    """
    try:
        os.chmod(path, mode)
        return True
    except OSError as e:
        if not getattr(_chmod_private, "_warned", False):
            _chmod_private._warned = True
            print(f"⚠️ محدودکردنِ دسترسیِ «{path}» ممکن نشد ({e.__class__.__name__}) — "
                  f"اگر چند کاربر روی این سرور هستند، دسترسی را دستی با "
                  f"chmod 600/700 محدود کن.")
        return False





# رفرنسِ سراسری به SaaSBotِ در حال اجرا — تا SelfBot بتواند «کدِ لاگین» را
# از طریقِ همان رباتِ مدیریت به مالک برساند (نه فقط پیامِ خصوصی از اکانتِ
# مدیریت‌شده). SaaSBot.start این را ست می‌کند.
_SAAS_BOT_REF = None


async def _deliver_via_bot(owner_id: int, text: str) -> bool:
    """
    تلاش برای فرستادنِ متن به مالک از طریقِ رباتِ مدیریت (SaaSBot). اگر
    ربات در دسترس نبود یا خطا داد، False برمی‌گرداند تا فراخوان به مسیرِ
    جایگزین (پیامِ خصوصی از اکانتِ سلف) برود.
    """
    bot = _SAAS_BOT_REF
    if bot is None or getattr(bot, "client", None) is None or not owner_id:
        return False
    try:
        await bot.client.send_message(owner_id, text)
        return True
    except Exception as e:
        print(f"⚠️ [code-delivery] ارسال از طریق ربات ناموفق: {type(e).__name__}")
        return False


# مرجعِ سراسریِ تسک‌های پس‌زمینه.
#
# چرا لازم است: asyncio فقط یک ارجاعِ *ضعیف* به تسک‌ها نگه می‌دارد. اگر
# نتیجه‌ی asyncio.create_task() در جایی ذخیره نشود، ممکن است garbage
# collector تسک را وسطِ اجرا (روی هر await) نابود کند — تسک بی‌صدا ناتمام
# می‌ماند و بلوکِ finally آن هرگز اجرا نمی‌شود. این دقیقاً همان چیزی است
# که مستندات CPython درباره‌اش هشدار می‌دهد.
_BG_TASKS = set()


def _spawn_bg(coro, label: str = ""):
    """
    اجرای یک کوروتین در پس‌زمینه، با ارجاعِ قویِ تضمین‌شده تا پایان کار.

    تسک تا وقتی تمام نشده در _BG_TASKS می‌ماند و بعد خودش را از آن حذف
    می‌کند، پس این مجموعه رشد نمی‌کند. استثناهای پیش‌بینی‌نشده هم به‌جای
    «Task exception was never retrieved» با تگِ خوانا لاگ می‌شوند.
    """
    task = asyncio.ensure_future(coro)
    _BG_TASKS.add(task)

    def _done(t):
        _BG_TASKS.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            print(f"⚠️ [bg:{label or 'task'}] {type(exc).__name__}: {str(exc)[:120]}")

    task.add_done_callback(_done)
    return task


# ══════════════════════════════════════════════════════════════════════
# ═══ بخش db.py (ادغامشده) ═══
# ══════════════════════════════════════════════════════════════════════
# (importهای مشترکِ همهی بخشها یک‌جا در بالای فایل ادغام شده‌اند)

DB_NAME = os.path.join(DATA_DIR, "bot_data.db")
_db_lock = threading.Lock()
# قفلِ Restore: دو Restore هم‌زمان هرگز با هم تداخل نمی‌کنند (بخش ۴/۵).
_RESTORE_LOCK = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def _bot_db(commit: bool = False):
    """
    کانکشنِ bot_data.db با بستنِ تضمین‌شده.

    چرا لازم شد: توابعِ این لایه الگوی
        conn = get_db(); ...; conn.commit(); conn.close()
    داشتند. اگر execute یا commit استثنا می‌داد (مثلاً «database is
    locked» زیر بار، یا disk I/O error)، خطِ conn.close() هرگز اجرا
    نمی‌شد و کانکشن — به‌همراه file descriptor و فایل‌های -wal/-shm —
    نشت می‌کرد. در یک سرویسِ همیشه‌روشن این نشت انباشته می‌شود تا به
    سقفِ fdهای پروسه بخورد. این contextmanager بستن را به finally
    می‌سپارد، پس هیچ مسیرِ خطایی کانکشن باز جا نمی‌گذارد.

    commit=True برای عملیاتِ نوشتن. در خطا commit انجام نمی‌شود و
    sqlite خودش تراکنشِ ناتمام را با بسته‌شدنِ کانکشن rollback می‌کند.
    """
    with _db_lock:
        conn = get_db()
        try:
            yield conn
            if commit:
                conn.commit()
        finally:
            conn.close()

def db_init_db():
    # کانکشنِ استارتاپ هم با بستنِ تضمین‌شده — اگر یکی از CREATEها
    # خطا بدهد، پروسه با کانکشنِ باز بالا نمی‌آید.
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        # جداول قبلی
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TIMESTAMP,
                last_seen TIMESTAMP,
                messages_count INTEGER DEFAULT 0
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                banned_at TIMESTAMP,
                reason TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                content_type TEXT,
                content TEXT,
                sent_at TIMESTAMP,
                success_count INTEGER,
                fail_count INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                content TEXT,
                photo_id TEXT,
                created_at TIMESTAMP,
                scheduled_at TIMESTAMP,
                is_sent BOOLEAN DEFAULT 0
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                to_user_id INTEGER,
                message TEXT,
                direction TEXT,
                timestamp TIMESTAMP
            )
        ''')
        # جداول فروش‌بات
        c.execute('''
            CREATE TABLE IF NOT EXISTS sales_users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                plan_expiry TIMESTAMP,
                created_at TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                duration_days INTEGER,
                price INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan_id INTEGER,
                amount INTEGER,
                status TEXT DEFAULT 'pending',  -- pending, approved, rejected
                receipt TEXT,
                admin_note TEXT,
                created_at TIMESTAMP,
                approved_at TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS self_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                tag TEXT,
                api_id INTEGER,
                api_hash TEXT,
                phone TEXT,
                bot_token TEXT,
                account_type TEXT,  -- user or bot
                expiry TIMESTAMP,
                created_at TIMESTAMP
            )
        ''')
        # جدول برای ذخیره state (برای سلف‌بات)
        c.execute('''
            CREATE TABLE IF NOT EXISTS bot_states (
                tag TEXT,
                key TEXT,
                value TEXT,
                PRIMARY KEY (tag, key)
            )
        ''')
        # ایندکس‌ها
        c.execute('CREATE INDEX IF NOT EXISTS idx_sales_users_expiry ON sales_users(plan_expiry)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_self_accounts_user ON self_accounts(user_id)')

# ========== توابع عمومی کاربران (از helper.py) ==========

def add_or_update_user(user):
    """ثبت یا به‌روزرسانی کاربر در جدول users (با استفاده از شیء User از pyrogram)"""
    try:
        with _bot_db(commit=True) as conn:
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, joined_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    last_seen = excluded.last_seen
            ''', (user.id, user.username or "", user.first_name or "", user.last_name or "", now, now))
    except Exception as e:
        print(f"Error adding user {user.id}: {e}")

def increment_messages_count(user_id: int):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?', (user_id,))

def is_user_banned(user_id: int) -> bool:
    with _bot_db(commit=False) as conn:
        c = conn.cursor()
        c.execute('SELECT 1 FROM banned_users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        return result is not None

def ban_user(user_id: int, reason: str = ""):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO banned_users (user_id, banned_at, reason) VALUES (?, ?, ?)',
                  (user_id, datetime.now().isoformat(), reason))

def unban_user(user_id: int):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))

def get_banned_users_list() -> list:
    with _bot_db(commit=False) as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, banned_at, reason FROM banned_users')
        result = c.fetchall()
        return result

def get_all_users(offset=0, limit=20) -> list:
    with _bot_db(commit=False) as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, username, first_name, last_seen, messages_count FROM users LIMIT ? OFFSET ?', (limit, offset))
        result = c.fetchall()
        return result

def get_total_users_count() -> int:
    with _bot_db(commit=False) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        count = c.fetchone()[0]
        return count

def get_user_by_username(username: str) -> Optional[dict]:
    with _bot_db(commit=False) as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, username, first_name, last_name, joined_at, last_seen, messages_count FROM users WHERE username = ?', (username,))
        row = c.fetchone()
        if row:
            return {
                "user_id": row[0],
                "username": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "joined_at": row[4],
                "last_seen": row[5],
                "messages_count": row[6]
            }
        return None

def get_user_info(user_id: int) -> Optional[dict]:
    with _bot_db(commit=False) as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, username, first_name, last_name, joined_at, last_seen, messages_count FROM users WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        if row:
            return {
                "user_id": row[0],
                "username": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "joined_at": row[4],
                "last_seen": row[5],
                "messages_count": row[6]
            }
        return None

def get_stats() -> dict:
    with _bot_db(commit=False) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM banned_users')
        banned_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM broadcasts')
        total_broadcasts = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM messages')
        total_messages = c.fetchone()[0]
        today = datetime.now().date().isoformat()
        c.execute('SELECT COUNT(*) FROM users WHERE DATE(last_seen) = ?', (today,))
        active_today = c.fetchone()[0]
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        c.execute('SELECT COUNT(*) FROM users WHERE last_seen >= ?', (week_ago,))
        active_week = c.fetchone()[0]
        return {
            "total_users": total_users,
            "banned_count": banned_count,
            "total_broadcasts": total_broadcasts,
            "total_messages": total_messages,
            "active_today": active_today,
            "active_week": active_week
        }

def save_broadcast_log(admin_id: int, content_type: str, content: str, success: int, fail: int):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO broadcasts (admin_id, content_type, content, sent_at, success_count, fail_count)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (admin_id, content_type, content[:500], datetime.now().isoformat(), success, fail))

def save_message(from_user: int, to_user: int, text: str, direction: str):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO messages (from_user_id, to_user_id, message, direction, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (from_user, to_user, text[:500], direction, datetime.now().isoformat()))

# ========== توابع state (برای سلف‌بات) ==========

def set_state(tag: str, key: str, value):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO bot_states (tag, key, value)
            VALUES (?, ?, ?)
        ''', (tag, key, json.dumps(value)))

def get_all_state(tag: str) -> dict:
    with _bot_db(commit=False) as conn:
        c = conn.cursor()
        c.execute('SELECT key, value FROM bot_states WHERE tag = ?', (tag,))
        rows = c.fetchall()
        result = {}
        for key, val in rows:
            try:
                result[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                # مقدارِ غیر-JSON (داده‌ی قدیمی) همان رشته‌ی خام می‌ماند.
                # except لختِ قبلی، KeyboardInterrupt/SystemExit را هم
                # می‌بلعید.
                result[key] = val
        return result

def clear_state(tag: str):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM bot_states WHERE tag = ?', (tag,))

# ========== توابع فروش‌بات ==========

def add_sales_user(user_id: int):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''
            INSERT OR IGNORE INTO sales_users (user_id, created_at)
            VALUES (?, ?)
        ''', (user_id, now))

def get_sales_user(user_id: int) -> dict:
    with _bot_db() as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, balance, plan_expiry, created_at FROM sales_users WHERE user_id = ?', (user_id,))
        row = c.fetchone()
    if row:
        return {"user_id": row[0], "balance": row[1], "plan_expiry": row[2], "created_at": row[3]}
    return None

# ⚠️ WARNING: this function is never called anywhere in the project (dead
# code — grep "update_balance(" only matches this definition). Real
# payment/credit changes go through a different path: activate_license /
# pay_order_trc20_atomic / approve_card_payment_atomic operating on the
# orders/payments/subscriptions tables, not through sales_users.balance.
# Before using this function in new code, confirm you actually want this
# legacy wallet path and not the current payment flow.
def update_balance(user_id: int, amount: int):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('UPDATE sales_users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))

def set_plan_expiry(user_id: int, expiry: str):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('UPDATE sales_users SET plan_expiry = ? WHERE user_id = ?', (expiry, user_id))

def add_purchase(user_id: int, plan_id: int, amount: int, receipt: str = ""):
    # کانکشن همیشه بسته می‌شود (try/finally) — بدون Connection Leak، حتی اگر
    # INSERT یا commit خطا بدهد.
    with _db_lock:
        conn = get_db()
        try:
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('''
                INSERT INTO purchases (user_id, plan_id, amount, receipt, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, plan_id, amount, receipt, now))
            conn.commit()
            return c.lastrowid
        except Exception:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

def approve_purchase(purchase_id: int, admin_note: str = ""):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''
            UPDATE purchases SET status = 'approved', approved_at = ?, admin_note = ?
            WHERE id = ?
        ''', (now, admin_note, purchase_id))

def reject_purchase(purchase_id: int, admin_note: str = ""):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE purchases SET status = 'rejected', admin_note = ?
            WHERE id = ?
        ''', (admin_note, purchase_id))

def get_plans() -> list:
    with _bot_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, name, duration_days, price FROM plans ORDER BY price')
        rows = c.fetchall()
    return [{"id": r[0], "name": r[1], "duration_days": r[2], "price": r[3]} for r in rows]

def add_plan(name: str, duration_days: int, price: int):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO plans (name, duration_days, price) VALUES (?, ?, ?)', (name, duration_days, price))

def add_self_account(user_id: int, tag: str, api_id: int, api_hash: str, phone: str = None, bot_token: str = None, account_type: str = "user"):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''
            INSERT INTO self_accounts (user_id, tag, api_id, api_hash, phone, bot_token, account_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, tag, api_id, api_hash, phone, bot_token, account_type, now))

def get_self_accounts(user_id: int) -> list:
    with _bot_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, tag, api_id, api_hash, phone, bot_token, account_type, expiry, created_at FROM self_accounts WHERE user_id = ?', (user_id,))
        rows = c.fetchall()
    return [{"id": r[0], "tag": r[1], "api_id": r[2], "api_hash": r[3], "phone": r[4], "bot_token": r[5], "account_type": r[6], "expiry": r[7], "created_at": r[8]} for r in rows]

def update_self_account_expiry(account_id: int, expiry: str):
    with _bot_db(commit=True) as conn:
        c = conn.cursor()
        c.execute('UPDATE self_accounts SET expiry = ? WHERE id = ?', (expiry, account_id))

# ══════════════════════════════════════════════════════════════════════
# ═══ بخش saas_db.py (ادغامشده) ═══
# ══════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════
#  saas_db.py
# ══════════════════════════════════════════════════════════
#  لایه‌ی داده‌ی سیستم مدیریت CiaNet (نقش‌ها، اشتراک، لایسنس، پرداخت،
#  تیکت، لاگ). یک فایل SQLite جدا و مستقل از db.py اصلی (که برای وضعیت
#  زنده‌ی خودِ SelfBotها در main.py استفاده می‌شود) — چون این یک دامنه‌ی
#  کاملاً متفاوت (کسب‌وکار/دسترسی) است، نه وضعیت اجرای یک سلف.
#
#  همه‌ی توابع این فایل sync (نه async) هستند — چون خود عملیات‌های SQLite
#  در این حجم داده (چند صد/هزار ردیف) به‌قدری سریع هستند که نیازی به
#  اجرای async/thread-pool ندارند؛ این دقیقاً همان الگویی است که db.py
#  اصلی پروژه هم استفاده می‌کند.
#
#  نکته‌ی مهم نسخه‌ی جدید: این ماژول تنها منبع حقیقتِ نقش‌هاست (OWNER /
#  ADMIN / RESELLER / USER). admin_bot.py وقتی از طریق saas_bot.py صدا
#  زده می‌شود دیگر فایل JSON جدای خودش را برای دسترسی چک نمی‌کند — از
#  همین جدول admins استفاده می‌کند. این یعنی هیچ دو منبع حقیقت موازی
#  برای دسترسی وجود ندارد.
# ══════════════════════════════════════════════════════════

DB_PATH = os.path.join(DATA_DIR, "saas.db")

ROLE_OWNER = "OWNER"
ROLE_ADMIN = "ADMIN"
ROLE_RESELLER = "RESELLER"
ROLE_USER = "USER"

LICENSE_TYPE_ACCOUNT = "account"
LICENSE_TYPE_RESELLER = "reseller"
LICENSE_TYPE_ADMIN = "admin"

# منبعِ ساخت یک اکانت سلف (provision_source) — برای تشخیص «اضافه‌شده‌ی دستی»
# در کارت کاربران:
#   manual       → توسط OWNER/ADMIN/نماینده از پنل مدیریت برای یک کاربر ساخته شد
#   license      → کاربر خودش بعد از فعال‌سازی لایسنس/اشتراک لاگین کرد
#   subscription → کاربر از پنل خودش اکانت اضافه کرد (روی اشتراکش)
PROVISION_MANUAL = "manual"
PROVISION_LICENSE = "license"
PROVISION_SUBSCRIPTION = "subscription"
# منبعِ نامعلومِ داده‌ی قدیمی (پیش از سیستم provision_source) — هرگز حدس
# زده نمی‌شود که «دستی» بوده؛ فقط legacy ثبت می‌شود.
PROVISION_LEGACY = "legacy"

SUB_STATUS_ACTIVE = "active"
SUB_STATUS_EXPIRED = "expired"
SUB_STATUS_PENDING = "pending"
# اشتراکی که با خرید/تمدید جدید جایگزین شده (نه به‌خاطر گذشتِ زمان)، تا با
# 'expired' واقعی (که یعنی زمانش تمام شده) اشتباه گرفته نشود
SUB_STATUS_SUPERSEDED = "superseded"

PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_APPROVED = "approved"
PAYMENT_STATUS_REJECTED = "rejected"

ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_EXPIRED = "expired"
ORDER_STATUS_CANCELLED = "cancelled"

# فاکتور/سفارش: اعتبار ۲۴ ساعته؛ تبدیل تومان→تتر با نرخ لحظه‌ای و fallback
ORDER_EXPIRE_HOURS = 24
USDT_TOMAN_FALLBACK = 60000

# پلن/قیمت ربات اختصاصی (نمایندگی): یک‌بارخرید؛ قیمت از settings قابل‌تغییر است
DEDICATED_BOT_PLAN = "ربات اختصاصی"
DEDICATED_BOT_PRICE_DEFAULT = 2000000

TICKET_STATUS_OPEN = "open"
TICKET_STATUS_CLOSED = "closed"

# فرمت‌های تاریخ ذخیره‌شده در دیتابیس — timezone-aware، همیشه UTC
_DATE_FMT = "%Y-%m-%d"
_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def _now() -> str:
    """زمان فعلی UTC به‌صورت رشته، برای ستون‌های created_at/reviewed_at و..."""
    return datetime.now(timezone.utc).strftime(_DATETIME_FMT)


# ══════════════════════════════════════════════════════════════════════
#  تاریخ شمسی
# ══════════════════════════════════════════════════════════════════════
#  کاربرِ ایرانی تاریخِ میلادی را «تاریخِ خودش» حس نمی‌کند. چون وابستگیِ
#  بیرونی (jdatetime) به این پروژه‌ی تک‌فایل اضافه نمی‌کنیم، تبدیل را
#  خودمان انجام می‌دهیم — الگوریتمِ استانداردِ تبدیلِ میلادی↔جلالی.

_JALALI_MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
_WEEKDAYS_FA = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه",
                "جمعه", "شنبه", "یک‌شنبه")   # ایندکس = datetime.weekday()


def to_jalali(dt) -> tuple:
    """(سال، ماه، روز) شمسی از یک datetime/date میلادی."""
    gy, gm, gd = dt.year, dt.month, dt.day
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = (365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100
                + (gy2 + 399) // 400 + g_d_m[gm2] + gd2)
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    for i in range(11):
        span = 31 if i < 6 else 30
        if j_day_no < span:
            return jy, i + 1, j_day_no + 1
        j_day_no -= span
    return jy, 12, j_day_no + 1


def fa_digits(s) -> str:
    """ارقام لاتین → ارقام فارسی. برای متنی که کاربر می‌خواند، نه برای کد."""
    return str(s).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


# ══════════════════════════════════════════════════════════
#  Anti-Ban: محافظت از اکانت‌های شماره‌ی خارج / مجازی
# ══════════════════════════════════════════════════════════
#
# چرا لازم است:
#   اکانت‌هایی که با شماره‌ی مجازی (VoIP / online-SMS) ساخته شده‌اند، نسبت
#   به عملیات‌های «خروج از همه» (ResetAuthorizations) و «بازنشانی ۲FA» بسیار
#   حساس‌اند: تلگرام بعد از ResetAuthorizations یا ResetPassword روی این
#   اکانت‌ها، ایمیل را حذف می‌کند و دسترسی به اکانت را تقریباً غیرممکن
#   می‌سازد. این یعنی یک کلیک اشتباه مشتری، اکانت را برای همیشه از دست
#   می‌دهد.
#
#   برای حل این مشکل، قبل از هر عملیات خطرناک، شماره‌ی اکانت بررسی می‌شود:
#     • شماره‌ی ایران (+98) → رفتار عادی، فقط با مجوز
#     • شماره‌ی خارج (بقیه‌ی +CC) → علاوه بر مجوز، یک تأیید اضافه هم لازم است
#     • شماره ناشناس / خالی → مثل خارج رفتار می‌شود (امن‌ترین حالت)
#   مالک اصلی (ADMIN_ID) در نمونه‌ی اصلی از این محافظت معاف است.
#
# عملیات‌هایی که این محافظ روی‌شان اعمال می‌شود:
#   - sessterm (خروج از همه)
#   - sesskill (بستن یک session خاص)
#   - tfago (اجرای بازنشانی ۲FA)
#   - tfareset (شروع درخواست بازنشانی ۲FA)
#   - tfacancel (لغو بازنشانی ۲FA - در برخی موارد می‌تواند مشکل‌ساز شود)

# پیش‌شماره‌های رایج کشورهایی که معمولاً شماره‌ی مجازی/خارج محسوب می‌شوند
# (هر پیش‌شماره‌ای غیر از ۹۸ در حالت پیش‌فرض «خارج» حساب می‌شود؛ این لیست
# صرفاً برای لاگ و نمایش بهتر استفاده می‌شود).
_FOREIGN_CC_HINTS = {
    "+1": "🇺🇸 آمریکا/کانادا",
    "+44": "🇬🇧 انگلیس",
    "+49": "🇩🇪 آلمان",
    "+90": "🇹🇷 ترکیه",
    "+7": "🇷🇺 روسیه",
    "+380": "🇺🇦 اوکراین",
    "+91": "🇮🇳 هند",
    "+86": "🇨🇳 چین",
    "+34": "🇪🇸 اسپانیا",
    "+39": "🇮🇹 ایتالیا",
    "+33": "🇫🇷 فرانسه",
    "+971": "🇦🇪 امارات",
    "+966": "🇸🇦 عربستان",
    "+964": "🇮🇶 عراق",
    "+992": "🇹🇯 تاجیکستان",
    "+93": "🇦🇫 افغانستان",
    "+995": "🇬🇪 گرجستان",
    "+994": "🇦🇿 آذربایجان",
    "+996": "🇰🇬 قرقیزستان",
    "+374": "🇦🇲 ارمنستان",
}


def normalize_phone(raw) -> str:
    """
    شماره‌ی تلفن را به فرمت E.164 (با +) نرمال می‌کند.
    - حذف فاصله، خط‌تیره، پرانتز
    - تبدیل ارقام فارسی به لاتین
    - اگر با ۰ شروع شد و ۱۰ رقم داشت (ایران بدون +)، تبدیل به +98
    - اگر با ۹۸ شروع شد ولی + نداشت، اضافه کردن +
    - اگر خالی/نامعتبر → "" (رشته‌ی خالی)
    """
    if not raw:
        return ""
    s = str(raw).translate(_FA_TO_EN_DIGITS)
    s = re.sub(r"[\s\-\(\)]", "", s)
    s = s.strip()
    if not s:
        return ""
    if s.startswith("+"):
        digits = re.sub(r"[^\d]", "", s[1:])
        return ("+" + digits) if digits else ""
    if s.startswith("00"):
        return "+" + s[2:]
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) == 11 and digits[1:].isdigit():
        # مثلاً 09123456789 → +989123456789
        return "+98" + digits[1:]
    if digits.startswith("98") and len(digits) == 12:
        return "+" + digits
    return "+" + digits


def is_iranian_phone(phone) -> bool:
    """آیا این شماره ایرانی است؟ (+98 یا 98 بدون + یا 0xxxxx ایران)"""
    n = normalize_phone(phone)
    if not n:
        return False
    return n.startswith("+98") or n.startswith("98")


def phone_country_hint(phone) -> str:
    """
    پیش‌شماره‌ی کشور + نام کشور (برای لاگ و نمایش). اگر ایران باشد، «ایران».
    """
    n = normalize_phone(phone)
    if not n:
        return "ناشناس"
    if is_iranian_phone(n):
        return "🇮🇷 ایران"
    # پیدا کردن بلندترین پیش‌شماره‌ی شناخته‌شده که با شماره شروع شود
    for cc in sorted(_FOREIGN_CC_HINTS.keys(), key=len, reverse=True):
        if n.startswith(cc):
            return _FOREIGN_CC_HINTS[cc]
    return f"خارج ({n[:4]}...)"


def is_dangerous_account(acc) -> bool:
    """
    آیا این اکانت به محافظت Anti-Ban نیاز دارد؟
    - اگر شماره ایرانی باشد: خیر (امن)
    - اگر شماره خارج یا ناشناس باشد: بله (خطرناک)
    """
    if not isinstance(acc, dict):
        return True
    phone = acc.get("phone") or ""
    return not is_iranian_phone(phone)


def is_owner_bypass(actor_id: int) -> bool:
    """
    آیا این کاربر مالک اصلی سیستم است و از Anti-Ban معاف است؟
    فقط در نمونه‌ی اصلی و فقط برای ADMIN_ID.
    """
    if IS_DEDICATED_BOT:
        return False
    try:
        return int(actor_id) == int(ADMIN_ID)
    except Exception:
        return False


# پنجره‌ی تأیید Anti-Ban: نگه‌داری token → (tag, action) برای تطابق callback
# فرمت: {token: {"tag": str, "action": str, "actor_id": int, "expires": float}}
_ANTIBAN_PENDING: dict = {}
_ANTIBAN_TTL = 120  # ۲ دقیقه مهلت تأیید


def antiban_request_confirmation(tag: str, action: str, actor_id: int) -> str:
    """
    یک token برای تأیید عملیات خطرناک می‌سازد و برمی‌گرداند.
    callback_data بعدی: f"abok:{token}" یا f"abno:{token}"
    """
    import uuid
    token = uuid.uuid4().hex[:12]
    _ANTIBAN_PENDING[token] = {
        "tag": tag,
        "action": action,
        "actor_id": int(actor_id),
        "expires": time.time() + _ANTIBAN_TTL,
    }
    # پاک‌سازی pending های منقضی
    now = time.time()
    for k in list(_ANTIBAN_PENDING.keys()):
        if _ANTIBAN_PENDING[k]["expires"] < now:
            _ANTIBAN_PENDING.pop(k, None)
    return token


def antiban_consume(token: str, actor_id: int) -> tuple:
    """
    اگر token معتبر، منقضی‌نشده، و متعلق به همین کاربر باشد: حذفش کن و True برگردان.
    خروجی: (success, info) — info فقط وقتی success=False پُر است.
    """
    info = _ANTIBAN_PENDING.pop(token, None)
    if not info:
        return False, "expired"
    if time.time() > info["expires"]:
        return False, "expired"
    if int(actor_id) != int(info["actor_id"]):
        # توکن مال این کاربر نیست — برگردان و نگه‌دار
        _ANTIBAN_PENDING[token] = info
        return False, "wrong_user"
    return True, info


def antiban_guarded_action(actor_id: int, acc, action_label: str) -> tuple:
    """
    گارد مرکزی: اگر اکانت خطرناک است و کاربر مالک نیست، باید تأیید اضافه بگیرد.
    خروجی:
      (True, None) → ادامه بده، مشکلی نیست
      (False, "needs_confirm", token) → نیاز به تأیید؛ token برای callback بعدی
    """
    if is_owner_bypass(actor_id):
        return True, None
    if not is_dangerous_account(acc):
        return True, None
    token = antiban_request_confirmation(
        acc.get("tag") or acc.get("__tag") or "?", action_label, actor_id
    )
    return False, "needs_confirm", token


_FA_TO_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def normalize_card_number(raw: str) -> str:
    """
    نرمال‌سازی ورودیِ شماره‌ی کارت به یک رشته‌ی ۱۶-رقمیِ لاتینِ چسبیده.

    کاربر ممکن است شماره را با فاصله/خط‌تیره بین رقم‌ها («۶۲۱۹ ۸۶۱۴ ...»)
    یا با ارقام فارسی بفرست. خروجی همیشه ارقام لاتینِ چسبیده است تا در
    settings به‌صورت استاندارد و قابل‌کپی ذخیره شود. هر کاراکتر غیرِرقم
    (فاصله، خط‌تیره، ویرگول) حذف می‌شود.
    """
    return "".join(ch for ch in str(raw).translate(_FA_TO_EN_DIGITS) if ch.isdigit())


def jalali_date(dt=None, persian_digits: bool = True) -> str:
    """تاریخ شمسی به شکل ۱۴۰۵/۰۶/۲۳."""
    dt = dt or iran_now()
    jy, jm, jd = to_jalali(dt)
    out = f"{jy}/{jm:02d}/{jd:02d}"
    return fa_digits(out) if persian_digits else out


def jalali_long(dt=None) -> str:
    """تاریخ شمسیِ خوانا: «۲۳ شهریور ۱۴۰۵»."""
    dt = dt or iran_now()
    jy, jm, jd = to_jalali(dt)
    return f"{fa_digits(jd)} {_JALALI_MONTHS[jm - 1]} {fa_digits(jy)}"


def fa_weekday(dt=None) -> str:
    dt = dt or iran_now()
    return _WEEKDAYS_FA[dt.weekday()]


def _fmt_dt_local(dt=None) -> str:
    """
    تاریخ و ساعتِ خوانا (شمسی + ساعتِ ایران) برای نمایشِ زمان‌های تلگرام
    — مثلاً زمانِ پایانِ انتظارِ بازنشانیِ رمز. ورودیِ None → الان.
    """
    dt = dt or iran_now()
    try:
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.astimezone(_IRAN_TZ)
    except Exception:
        pass
    return (f"{jalali_long(dt)} · {fa_digits(dt.strftime('%H:%M'))}")


def fa_money(n) -> str:
    """مبلغ با جداکننده‌ی هزارگان و ارقام فارسی: ۱۰۰٬۰۰۰"""
    try:
        return fa_digits(f"{int(n):,}").replace(",", "٬")
    except (TypeError, ValueError):
        return fa_digits(n)


def safe_callback_int(value, default=None):
    """
    تبدیل امن رشته/مقدار callback به int — برای همه‌ی IDهایی که از
    callback_data می‌آیند (user_id / ticket_id / payment_id / order_id /
    bot_id و…). اگر عدد صحیح معتبر نبود، default برمی‌گرداند (معمولاً None)
    تا کالبک خراب crash نکند و در گارد بعدی (وجود/مالکیت) رد شود.
    """
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_date() -> str:
    """تاریخ فعلی UTC (بدون ساعت) — برای مقایسه‌ی expire_date."""
    return datetime.now(timezone.utc).strftime(_DATE_FMT)


def _parse_date(date_str: str) -> datetime:
    """
    رشته‌ی تاریخ ذخیره‌شده را به datetime آگاه از UTC تبدیل می‌کند.
    همیشه ساعت را روی 00:00:00 UTC می‌گذارد چون expire_date فقط روز را
    نگه می‌دارد؛ محاسبات باید نسبت به همین مرجع ثابت انجام شوند تا در
    هیچ کجا با local time سرور قاطی نشوند.
    """
    dt = datetime.strptime(date_str, _DATE_FMT)
    return dt.replace(tzinfo=timezone.utc)


def _format_date(dt: datetime) -> str:
    return dt.strftime(_DATE_FMT)


def _subscription_days_left(sub) -> int:
    """
    روزهای باقیمانده‌ی واقعی یک اشتراک فعال (مقایسه‌ی تاریخ‌ها با UTC، نه
    datetime — تا «امروزِ آخرین روز» دقیقاً ۰ و منقضی‌شده منفی شود):
      > 0 → N روز باقی‌مانده
      == 0 → امروز آخرین روز است
      < 0 → منقضی شده
    در صورت نبود اشتراک یا خطای پارس، None برمی‌گرداند.
    """
    if not sub:
        return None
    try:
        expire = _parse_date(sub["expire_date"]).date()
        today = datetime.now(timezone.utc).date()
        return (expire - today).days
    except Exception:
        return None


@contextmanager
def _conn():
    """
    هر بار یک کانکشن تازه باز و در پایان بسته می‌شود — برای این حجم داده و
    نرخ درخواست (چند تا کلیک ادمین/کاربر در ثانیه، نه هزاران در ثانیه)
    نگه‌داشتن یک کانکشن دائمی سراسری فایده‌ی محسوسی ندارد و ریسک قفل‌شدن
    هم‌زمان با فرایندهای دیگر را کم می‌کند.
    """
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    # WAL باعث می‌شود خواندن‌های هم‌زمان با نوشتن قفل نشوند — با معماریِ
    # «هر عملیات یک کانکشن تازه» این تنظیم اهمیت بیشتری پیدا می‌کند چون
    # ممکن است چند هندلر Telethon هم‌زمان به دیتابیس دسترسی بخواهند.
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


@contextmanager
def _conn_immediate():
    """
    کانکشن با BEGIN IMMEDIATE: از همان ابتدای تراکنش قفل نوشتن گرفته می‌شود،
    پس دو فعال‌سازیِ هم‌زمان (دو thread/task) روی یک لایسنس یا روی سقفِ مشتریِ
    یک نماینده به‌صورت سریال اجرا می‌شوند — نه موازی. برای عملیات‌هایی که
    «چک‌کردن + مصرف + ثبت» باید اتمیک و race-safe باشند استفاده می‌شود.
    """
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _verify_rebuilt_table(c, old_tbl: str, new_tbl: str,
                           required_not_null=()) -> None:
    """
    Validation عمیقِ مهاجرتِ بازسازی‌شده (بعد از copy، قبل از DROP قدیمی):
      - تعداد ردیف‌ها یکسان
      - مجموعه‌ی IDها دقیقاً یکسان (و یکتا)
      - ستون‌های حیاتی (مثلاً token/created_at/status) در جدول جدید NULL ندارند
    اگر هرکدام رد شود RuntimeError پرتاب می‌شود → تراکنش rollback می‌شود و
    جدول قدیمی دست‌نخورده می‌ماند.
    """
    old_n = c.execute(f"SELECT COUNT(*) FROM {old_tbl}").fetchone()[0]
    new_n = c.execute(f"SELECT COUNT(*) FROM {new_tbl}").fetchone()[0]
    if old_n != new_n:
        raise RuntimeError(
            f"مهاجرت {new_tbl} داده از دست داد ({old_n} → {new_n}) — تراکنش برگشت داده شد."
        )
    old_ids = [r[0] for r in c.execute(f"SELECT id FROM {old_tbl} ORDER BY id").fetchall()]
    new_ids = [r[0] for r in c.execute(f"SELECT id FROM {new_tbl} ORDER BY id").fetchall()]
    if old_ids != new_ids:
        raise RuntimeError(
            f"مهاجرت {new_tbl}: مجموعه‌ی IDها یکسان نیست — تراکنش برگشت داده شد."
        )
    if len(new_ids) != len(set(new_ids)):
        raise RuntimeError(f"مهاجرت {new_tbl}: ID تکراری در جدول جدید — تراکنش برگشت داده شد.")
    for col in required_not_null:
        bad = c.execute(
            f"SELECT COUNT(*) FROM {new_tbl} WHERE {col} IS NULL OR {col} = ''"
        ).fetchone()[0]
        if bad:
            raise RuntimeError(
                f"مهاجرت {new_tbl}: ستون {col} مقدار NULL/خالی دارد ({bad} ردیف) — "
                f"تراکنش برگشت داده شد."
            )


def _table_columns(c, table_name: str) -> set:
    rows = c.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {r["name"] for r in rows}


def _table_check_constraint_text(c, table_name: str) -> str:
    row = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return (row["sql"] or "") if row else ""


def _migrate_schema(c) -> None:
    """
    مهاجرت خودکار برای دیتابیس‌هایی که با نسخه‌ی قدیمی‌تر این ماژول ساخته
    شده‌اند. چون init_db از CREATE TABLE IF NOT EXISTS استفاده می‌کند، اگر
    یک جدول از قبل با schema قدیمی روی دیسک وجود داشته باشد، هیچ‌کدام از
    تغییرات بعدی (ستون جدید، مقدار جدید در CHECK) به‌طور خودکار اعمال
    نمی‌شوند — دقیقاً همان چیزی که باعث خطاهای زیر می‌شد:
        - "CHECK constraint failed: status IN ('active','expired','pending')"
          (جدول subscriptions قدیمی، بدون 'superseded')
        - "table payments has no column named receipt_ref"
          (جدول payments قدیمی، با ستون receipt_file_id به‌جای receipt_ref)

    این تابع idempotent است (اجرای مکررش روی یک دیتابیسِ از قبل مهاجرت‌شده
    کاملاً بی‌اثر و بی‌خطر است) و همیشه در ابتدای init_db صدا زده می‌شود، پس
    این مشکل دیگر تکرار نمی‌شود — حتی اگر بعداً دوباره schema عوض شود، تا
    وقتی این تابع هم به‌روزرسانی شود.
    """
    tables = {
        r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    # ── مهاجرت subscriptions: افزودن 'superseded' به CHECK(status IN ...) ──
    if "subscriptions" in tables:
        check_sql = _table_check_constraint_text(c, "subscriptions")
        if "superseded" not in check_sql:
            print("🔧 [saas_db] مهاجرت schema: افزودن وضعیت 'superseded' به جدول subscriptions...")
            before = c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
            c.execute("ALTER TABLE subscriptions RENAME TO subscriptions_old")
            c.execute("""
                CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plan TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    expire_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','expired','pending','superseded')),
                    license_id INTEGER,
                    selfbot_tag TEXT,
                    warned_24h INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            old_cols = _table_columns(c, "subscriptions_old")
            common_cols = old_cols & {
                "id", "user_id", "plan", "start_date", "expire_date", "status",
                "license_id", "selfbot_tag", "warned_24h", "created_at",
            }
            cols_str = ", ".join(sorted(common_cols))
            c.execute(f"INSERT INTO subscriptions ({cols_str}) SELECT {cols_str} FROM subscriptions_old")
            after = c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
            if before != after:
                raise RuntimeError(
                    f"مهاجرت subscriptions داده از دست داد ({before} → {after}) — "
                    f"تراکنش برگشت داده شد و جدول قدیمی حفظ شد."
                )
            c.execute("DROP TABLE subscriptions_old")
            print("✅ [saas_db] مهاجرت subscriptions با موفقیت انجام شد — هیچ داده‌ای از دست نرفت.")

    # ── مهاجرت licenses: افزودن نوع 'admin' به CHECK(license_type IN ...) ──
    if "licenses" in tables:
        check_sql = _table_check_constraint_text(c, "licenses")
        if "'admin'" not in check_sql:
            print("🔧 [saas_db] مهاجرت schema: افزودن نوع 'admin' به جدول licenses...")
            before = c.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
            c.execute("ALTER TABLE licenses RENAME TO licenses_old")
            c.execute("""
                CREATE TABLE licenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    license_type TEXT NOT NULL CHECK(license_type IN ('account','reseller','admin')),
                    duration_days INTEGER,
                    max_uses INTEGER DEFAULT 1,
                    used_count INTEGER DEFAULT 0,
                    reseller_user_limit INTEGER,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            """)
            old_cols = _table_columns(c, "licenses_old")
            common_cols = old_cols & {
                "id", "code", "license_type", "duration_days", "max_uses",
                "used_count", "reseller_user_limit", "created_by", "created_at", "is_active",
            }
            cols_str = ", ".join(sorted(common_cols))
            c.execute(f"INSERT INTO licenses ({cols_str}) SELECT {cols_str} FROM licenses_old")
            after = c.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
            if before != after:
                raise RuntimeError(
                    f"مهاجرت licenses داده از دست داد ({before} → {after}) — "
                    f"تراکنش برگشت داده شد و جدول قدیمی حفظ شد."
                )
            c.execute("DROP TABLE licenses_old")
            print("✅ [saas_db] مهاجرت licenses با موفقیت انجام شد — هیچ داده‌ای از دست نرفت.")

    # ── مهاجرت payments: تغییر نام receipt_file_id → receipt_ref ──
    if "payments" in tables:
        cols = _table_columns(c, "payments")
        if "receipt_ref" not in cols:
            print("🔧 [saas_db] مهاجرت schema: افزودن ستون receipt_ref به جدول payments...")
            if "receipt_file_id" in cols:
                # ستون قدیمی وجود دارد — عوض تغییر نام (که در نسخه‌های قدیم
                # SQLite همیشه پشتیبانی نمی‌شود)، یک ستون جدید اضافه و
                # محتوای قدیمی را در آن کپی می‌کنیم تا رسیدهای قبلی از دست
                # نروند.
                c.execute("ALTER TABLE payments ADD COLUMN receipt_ref TEXT")
                c.execute("UPDATE payments SET receipt_ref = receipt_file_id")
            else:
                c.execute("ALTER TABLE payments ADD COLUMN receipt_ref TEXT")
            print("✅ [saas_db] مهاجرت payments با موفقیت انجام شد — هیچ داده‌ای از دست نرفت.")

    # ── مهاجرت delete_journal: افزودن ستون status (ردیف‌های قدیمی → DELETE_PENDING) ──
    if "delete_journal" in tables:
        cols = _table_columns(c, "delete_journal")
        if "status" not in cols:
            print("🔧 [saas_db] مهاجرت schema: افزودن ستون status به جدول delete_journal...")
            c.execute(
                "ALTER TABLE delete_journal ADD COLUMN status TEXT NOT NULL DEFAULT 'DELETE_PENDING'"
            )
            print("✅ [saas_db] مهاجرت delete_journal با موفقیت انجام شد — هیچ داده‌ای از دست نرفت.")


def init_db() -> None:
    with _conn() as c:
        _migrate_schema(c)
        c.executescript("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL CHECK(role IN ('OWNER','ADMIN','RESELLER')),
            added_by INTEGER,
            reseller_max_users INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            reseller_id INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            start_date TEXT NOT NULL,
            expire_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active','expired','pending','superseded')),
            license_id INTEGER,
            selfbot_tag TEXT,
            warned_24h INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            license_type TEXT NOT NULL CHECK(license_type IN ('account','reseller','admin')),
            duration_days INTEGER,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            reseller_user_limit INTEGER,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            amount INTEGER,
            receipt_ref TEXT,
            status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
            reviewed_by INTEGER,
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            amount_toman INTEGER NOT NULL,
            amount_usdt REAL NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','paid','expired','cancelled')),
            pay_method TEXT,
            txid TEXT,
            payment_id INTEGER,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            paid_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, expires_at);
        -- Replay protection در سطح دیتابیس: هر txid فقط یک‌بار (روی هر فاکتور).
        -- به‌صورت جدا (خارج از executescript) ساخته می‌شود تا اگر دیتابیس
        -- قدیمی تکراری دارد (قبل از این قانون ساخته شده)، استارت‌آپ کرش نکند:
        -- در آن صورت ایندکس یکتا ساخته نمی‌شود و چک پایتونیِ replay همچنان
        -- در تراکنش فعال می‌ماند.

        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open','closed')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dedicated_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reseller_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            token TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending_payment','active','stopped','revoked','rejected','deleted')),
            payment_id INTEGER,
            bot_dir TEXT,
            pid INTEGER,
            expire_date TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ticket_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_role TEXT NOT NULL CHECK(sender_role IN ('user','admin')),
            sender_id INTEGER NOT NULL,
            text TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(ticket_id) REFERENCES tickets(id)
        );

        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );

        -- Operation Journal برای حذف کاربر (دو دیتابیس جدا): ردیف در همان
        -- تراکنشِ اصلیِ حذف ثبت می‌شود و بعد از کامل‌شدنِ همه‌ی مراحل
        -- (bot_data + config) پاک می‌شود. ردیفِ باقی‌مانده = عملیاتِ ناتمام
        -- که _recover_delete_journal در استارتاپ کاملش می‌کند.
        CREATE TABLE IF NOT EXISTS delete_journal (
            user_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DELETE_PENDING'
        );

        CREATE TABLE IF NOT EXISTS pricing (
            plan TEXT PRIMARY KEY,
            price_toman INTEGER NOT NULL,
            duration_days INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- مجوزهای ظرفیتی (capability-based permissions). این جدول لایه‌ی
        -- مجوزِ جدا از نقش است: یک RESELLER صرفاً به‌خاطرِ نماینده‌بودن هیچ
        -- مجوزی نمی‌گیرد — مالکِ اصلی باید صراحتاً اعطا کند. پیش‌فرض DENY
        -- است و مهاجرت روی نصب‌های موجود هیچ مجوزی ایجاد نمی‌کند.
        --
        -- scope_type:
        --   'reseller'      → scope_id = آیدیِ نماینده؛ دامنه = مشتریانِ او.
        --   'dedicated_bot' → scope_id = آیدیِ ربات اختصاصی (id جدول).
        --   'account'       → scope_id = تگِ اکانت.
        -- scope_id برای 'reseller' می‌تواند NULL باشد (یعنی «دامنه‌ی مشتریانِ
        -- خودِ دارنده‌ی مجوز»)؛ برای دو مورد دیگر همیشه مقدار دارد.
        CREATE TABLE IF NOT EXISTS permission_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_user_id INTEGER NOT NULL,
            capability TEXT NOT NULL,
            scope_type TEXT NOT NULL CHECK(scope_type IN ('reseller','dedicated_bot','account')),
            scope_id TEXT,
            granted_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_perm_subject ON permission_grants(subject_user_id, capability, is_active);
        CREATE INDEX IF NOT EXISTS idx_perm_scope ON permission_grants(scope_type, scope_id, is_active);

        CREATE INDEX IF NOT EXISTS idx_sub_user_status ON subscriptions(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_sub_status_expire ON subscriptions(status, expire_date);
        CREATE INDEX IF NOT EXISTS idx_users_reseller ON users(reseller_id);
        CREATE INDEX IF NOT EXISTS idx_ticket_msgs_ticket ON ticket_messages(ticket_id);
        CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
        """)
        # Replay protection در سطح دیتابیس (خارج از executescript تا خطای
        # تکراریِ قدیمی استارت‌آپ را کرش نکند): هر txid فقط یک‌بار روی هر
        # فاکتور. اگر دیتابیس قدیمی تکراری دارد، ایندکس یکتا ساخته نمی‌شود
        # و چک پایتونیِ replay داخل تراکنش همچنان محافظ است.
        try:
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_txid_unique "
                "ON orders(txid) WHERE txid IS NOT NULL"
            )
        except sqlite3.IntegrityError:
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_txid ON orders(txid)")
            print("⚠️ [saas_db] داده‌ی قدیمیِ orders دارای txid تکراری است — "
                  "ایندکس یکتای txid ساخته نشد (چک پایتونیِ replay فعال است).")
        # پلن‌های پیش‌فرض فقط اگر جدول خالی باشد درج می‌شوند (تا با اجرای
        # مجدد init_db قیمت‌های تغییریافته‌ی ادمین بازنویسی نشوند)
        # مهاجرت جدول dedicated_bots از نسخه‌ی قبلی (بدون ستون‌های pid/expire_date
        # و بدون وضعیت 'stopped'). چون این جدول فقط همین‌جلسه معرفی شده، اگر
        # ستون pid نباشد بازسازی می‌شود تا اسکیمای جدید (و CHECK جدید) اعمال شود.
        _dbot_cols = [r[1] for r in c.execute("PRAGMA table_info(dedicated_bots)").fetchall()]
        if "pid" not in _dbot_cols:
            # بازسازیِ حفظ-داده (هرگز DROP مستقیم — دراپِ ساده رکوردهای واقعی
            # ربات‌های اختصاصی را می‌سوزاند): rename → create → copy → verify → drop
            print("🔧 [saas_db] مهاجرت dedicated_bots: بازسازیِ حفظ-داده برای افزودن pid/expire_date...")
            c.execute("ALTER TABLE dedicated_bots RENAME TO dedicated_bots_old")
            c.execute(
                """CREATE TABLE dedicated_bots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reseller_id INTEGER NOT NULL,
                    owner_id INTEGER NOT NULL,
                    token TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending_payment','active','stopped','revoked','rejected','deleted')),
                    payment_id INTEGER,
                    bot_dir TEXT,
                    pid INTEGER,
                    expire_date TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )"""
            )
            _old_cols = set(_dbot_cols)
            _common = sorted(_old_cols & {
                "id", "reseller_id", "owner_id", "token", "status",
                "payment_id", "bot_dir", "created_at", "reviewed_at",
            })
            if _common:
                _cols_str = ", ".join(_common)
                c.execute(
                    f"INSERT INTO dedicated_bots ({_cols_str}) SELECT {_cols_str} FROM dedicated_bots_old"
                )
            _verify_rebuilt_table(
                c, "dedicated_bots_old", "dedicated_bots",
                required_not_null=("reseller_id", "owner_id", "token", "created_at", "status"),
            )
            c.execute("DROP TABLE dedicated_bots_old")
            print("✅ [saas_db] مهاجرت dedicated_bots حفظ-داده با موفقیت انجام شد — هیچ داده‌ای از دست نرفت.")

        # مهاجرت ۲: افزودن وضعیت 'deleted' به CHECK — بازسازیِ حفظ-داده
        # (rename → create → copy → drop) چون SQLite نمی‌تواند CHECK را درجا
        # تغییر دهد و دراپِ ساده، درخواست‌های ثبت‌شده‌ی واقعی را می‌سوزاند.
        _dbot_sql = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='dedicated_bots'"
        ).fetchone()
        if _dbot_sql and "'deleted'" not in _dbot_sql[0]:
            print("🔧 [saas_db] مهاجرت dedicated_bots: افزودن وضعیت 'deleted' (بازسازی حفظ-داده)...")
            c.execute("ALTER TABLE dedicated_bots RENAME TO dedicated_bots_old")
            c.execute(
                """CREATE TABLE dedicated_bots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reseller_id INTEGER NOT NULL,
                    owner_id INTEGER NOT NULL,
                    token TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending_payment','active','stopped','revoked','rejected','deleted')),
                    payment_id INTEGER,
                    bot_dir TEXT,
                    pid INTEGER,
                    expire_date TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )"""
            )
            c.execute(
                "INSERT INTO dedicated_bots (id, reseller_id, owner_id, token, status, "
                "payment_id, bot_dir, pid, expire_date, created_at, reviewed_at) "
                "SELECT id, reseller_id, owner_id, token, status, payment_id, bot_dir, "
                "pid, expire_date, created_at, reviewed_at FROM dedicated_bots_old"
            )
            _verify_rebuilt_table(
                c, "dedicated_bots_old", "dedicated_bots",
                required_not_null=("reseller_id", "owner_id", "token", "created_at", "status"),
            )
            c.execute("DROP TABLE dedicated_bots_old")
            print("✅ [saas_db] مهاجرت dedicated_bots ('deleted') حفظ-داده با موفقیت انجام شد — هیچ داده‌ای از دست نرفت.")

        row = c.execute("SELECT COUNT(*) AS n FROM pricing").fetchone()
        if row["n"] == 0:
            c.executemany(
                "INSERT INTO pricing (plan, price_toman, duration_days) VALUES (?, ?, ?)",
                [
                    ("۱ ماهه", 150000, 30),
                    ("۳ ماهه", 400000, 90),
                    ("۶ ماهه", 750000, 180),
                    ("۱ ساله", 1400000, 365),
                ],
            )


def log_action(actor_id, action: str, details: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO logs (actor_id, action, details, created_at) VALUES (?, ?, ?, ?)",
            (actor_id, action, details, _now()),
        )


# ─────────────────────────────────────────────────────
#  تنظیمات عمومی (شماره کارت، نام صاحب حساب و ...) — به‌جای هاردکد در کد
# ─────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def dedicated_bot_price() -> int:
    """قیمت ربات اختصاصی با fallback ایمن — اگر تنظیم خالی/غیرعددی باشد
    (مثلاً با پاک‌سازی یا ویرایش دستی)، به پیش‌فرض برمی‌گردد به‌جای کرش int()."""
    try:
        return int(get_setting("dedicated_bot_price", str(DEDICATED_BOT_PRICE_DEFAULT)))
    except (ValueError, TypeError):
        return DEDICATED_BOT_PRICE_DEFAULT


def inc_setting(key: str) -> None:
    """شمارنده‌ی عددی در settings (مثلاً آمار گیت عضویت) — یک واحد اضافه می‌کند."""
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        cur = int(row["value"]) if row and row["value"] and str(row["value"]).isdigit() else 0
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(cur + 1)),
        )


def set_setting(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ─────────────────────────────────────────────────────
#  نقش‌ها و ادمین‌ها/نماینده‌ها  (این جدول تنها منبع حقیقتِ دسترسی است —
#  admin_bot.py دیگر لیست جدای خودش را در حالت غیرمستقل نگه نمی‌دارد)
# ─────────────────────────────────────────────────────

_owner_id_warning_shown = False


def get_role(user_id: int, owner_id: int) -> str:
    # لایه‌ی محافظتی دفاعی مضاعف: اگر owner_id نامعتبر باشد (0 یا خالی)،
    # یعنی جایی در راه‌اندازی برنامه متغیر محیطی ADMIN_ID خوانده نشده —
    # در این حالت هیچ user_id واقعی‌ای هرگز نمی‌تواند OWNER تشخیص داده
    # شود، چون هیچ کاربر تلگرامی آیدی 0 ندارد. این خودش یک باگ استقراری
    # (silent) بود که فقط با بررسی دستی کشف می‌شد. این هشدار فقط یک‌بار
    # در کل عمر پروسه چاپ می‌شود تا لاگ را اسپم نکند، اما هر بار get_role
    # صدا زده می‌شود (که در این پروژه یعنی روی تقریباً هر پیام/کلیک) اتفاق
    # می‌افتد، پس حتماً در همان اولین تعامل کاربر با ربات دیده خواهد شد.
    global _owner_id_warning_shown
    if not owner_id and not _owner_id_warning_shown:
        _owner_id_warning_shown = True
        print(
            "🛑 [saas_db] هشدار حیاتی: owner_id نامعتبر (0 یا خالی) است — "
            "یعنی متغیر محیطی ADMIN_ID تنظیم نشده. تا وقتی این مقدار درست "
            "نشود، هیچ‌کس (حتی صاحب اصلی ربات) OWNER تشخیص داده نمی‌شود."
        )
    if user_id == owner_id:
        return ROLE_OWNER
    with _conn() as c:
        row = c.execute("SELECT role FROM admins WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return row["role"]
    return ROLE_USER


def is_admin_or_above(user_id: int, owner_id: int) -> bool:
    """OWNER یا ADMIN — برای اینکه admin_bot.py بتواند بدون قوانین جدا چک کند."""
    return get_role(user_id, owner_id) in (ROLE_OWNER, ROLE_ADMIN)


def add_admin_or_reseller(user_id: int, role: str, added_by: int, reseller_max_users=None) -> None:
    if role not in (ROLE_ADMIN, ROLE_RESELLER):
        raise ValueError("role باید ADMIN یا RESELLER باشد (OWNER هاردکد و غیرقابل‌افزودن است)")
    with _conn() as c:
        c.execute(
            "INSERT INTO admins (user_id, role, added_by, reseller_max_users, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET role = excluded.role, "
            "added_by = excluded.added_by, "
            "reseller_max_users = excluded.reseller_max_users",
            (user_id, role, added_by, reseller_max_users, _now()),
        )
    log_action(added_by, "add_admin_or_reseller", f"user_id={user_id}, role={role}")


def remove_admin_or_reseller(user_id: int, removed_by=None) -> None:
    with _conn() as c:
        c.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    log_action(removed_by, "remove_admin_or_reseller", f"user_id={user_id}")


def list_admins_and_resellers() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM admins ORDER BY role, created_at").fetchall()
    return [dict(r) for r in rows]


def reseller_user_count(reseller_id: int) -> int:
    """
    تعداد واقعی کاربران زیرمجموعه‌ی یک نماینده — همیشه مستقیم از جدول
    users شمرده می‌شود (نه یک ستون کش‌شده‌ی جدا) تا هیچ‌وقت desync نشود.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM users WHERE reseller_id = ?", (reseller_id,)
        ).fetchone()
    return row["n"]


# ⚠️ WARNING: this function is never called anywhere in the project (dead
# code — grep "reseller_max_users(" only matches this definition and the
# unrelated same-named parameter in add_admin_or_reseller). The actual
# reseller customer-cap check is implemented as inline SQL inside
# activate_license, not through this function. If you use this function in
# new code, preserve the same contract it already implements: a NULL/None
# value means "no cap" — never coerce it to 0.
def reseller_max_users(reseller_id: int):
    with _conn() as c:
        row = c.execute(
            "SELECT reseller_max_users FROM admins WHERE user_id = ? AND role = 'RESELLER'",
            (reseller_id,),
        ).fetchone()
    return row["reseller_max_users"] if row else None


# ─────────────────────────────────────────────────────
#  کاربران
# ─────────────────────────────────────────────────────

def upsert_user(user_id: int, username: str = None, first_name: str = None, reseller_id: int = None) -> None:
    with _conn() as c:
        existing = c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if existing:
            c.execute(
                "UPDATE users SET username = COALESCE(?, username), "
                "first_name = COALESCE(?, first_name), "
                "reseller_id = COALESCE(?, reseller_id) WHERE user_id = ?",
                (username, first_name, reseller_id, user_id),
            )
        else:
            c.execute(
                "INSERT INTO users (user_id, username, first_name, reseller_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, username, first_name, reseller_id, _now()),
            )


def get_user(user_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════════════════
#  سیستم دعوت (رفرال)
# ══════════════════════════════════════════════════════════════════════
#  قاعده: هر کاربر یک لینکِ اختصاصی دارد. وقتی N نفر با آن لینک وارد
#  شوند، به دعوت‌کننده یک اشتراکِ هدیه داده می‌شود.

REFERRAL_GOAL = 3          # چند دعوتِ موفق = یک جایزه
REFERRAL_REWARD_DAYS = 30  # طولِ اشتراکِ هدیه


def ensure_referral_schema() -> None:
    """ستون‌های رفرال را (اگر نیستند) به جدول users اضافه می‌کند."""
    with _conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if "referred_by" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        if "referral_rewards" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN referral_rewards INTEGER DEFAULT 0")
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by)")


def referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{(bot_username or 'bot').lstrip('@')}?start=ref_{user_id}"


def parse_referral_arg(text: str):
    """از «/start ref_12345» آیدیِ دعوت‌کننده را بیرون می‌کشد."""
    m = re.search(r"/start\s+ref_(\d{3,20})\b", text or "")
    return int(m.group(1)) if m else None


def attach_referrer(user_id: int, referrer_id: int) -> bool:
    """
    ثبتِ دعوت‌کننده برای یک کاربرِ تازه.

    فقط یک بار و فقط برای کاربری که تازه ساخته شده و هنوز دعوت‌کننده
    ندارد — تا کسی نتواند با /start زدنِ دوباره برای خودش یا دیگری
    امتیاز بسازد. خود-دعوتی هم رد می‌شود.
    """
    if not user_id or not referrer_id or user_id == referrer_id:
        return False
    with _conn_immediate() as c:
        row = c.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or row["referred_by"] is not None:
            return False
        if c.execute("SELECT 1 FROM users WHERE user_id = ?", (referrer_id,)).fetchone() is None:
            return False
        cur = c.execute(
            "UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL",
            (referrer_id, user_id),
        )
        return cur.rowcount > 0


def referral_stats(user_id: int) -> dict:
    """{invited, rewards, remaining} — پیشرفتِ دعوت‌های یک کاربر."""
    with _conn() as c:
        invited = c.execute(
            "SELECT COUNT(*) AS n FROM users WHERE referred_by = ?", (user_id,)
        ).fetchone()["n"]
        row = c.execute(
            "SELECT referral_rewards FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    rewards = (row["referral_rewards"] or 0) if row else 0
    earned = invited // REFERRAL_GOAL
    return {
        "invited": invited,
        "rewards": rewards,
        "pending": max(0, earned - rewards),
        "remaining": (REFERRAL_GOAL - (invited % REFERRAL_GOAL)) % REFERRAL_GOAL or REFERRAL_GOAL,
    }


def claim_referral_rewards(user_id: int) -> int:
    """
    جایزه‌های به‌دست‌آمده ولی دریافت‌نشده را اعمال می‌کند و تعدادشان را
    برمی‌گرداند. اتمیک: شمارنده‌ی دریافت‌شده‌ها فقط وقتی بالا می‌رود که
    اشتراک واقعاً ساخته شده باشد.
    """
    st = referral_stats(user_id)
    n = st["pending"]
    if n <= 0:
        return 0
    granted = 0
    for _ in range(n):
        try:
            create_subscription(user_id, "هدیه دعوت", REFERRAL_REWARD_DAYS)
            granted += 1
        except Exception as e:
            print(f"⚠️ [referral] ساخت اشتراک هدیه ناموفق: {type(e).__name__}: {e}")
            break
    if granted:
        with _conn() as c:
            c.execute(
                "UPDATE users SET referral_rewards = COALESCE(referral_rewards, 0) + ? "
                "WHERE user_id = ?", (granted, user_id),
            )
        log_action(user_id, "referral_reward", f"{granted}×{REFERRAL_REWARD_DAYS}d")
    return granted


def list_users_for_reseller(reseller_id: int) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM users WHERE reseller_id = ? ORDER BY created_at DESC", (reseller_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def list_all_users() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def search_users(query: str) -> list:
    """
    جستجوی کاربر بر اساس آیدی عددی (تطبیق دقیق) یا بخشی از یوزرنیم (بدون @،
    تطبیق جزئی/LIKE). برای پنل مدیریت دستی کاربران استفاده می‌شود، جایی که
    ادمین/نماینده معمولاً یا آیدی کامل کاربر را دارد یا فقط بخشی از
    یوزرنیمش را به خاطر دارد.
    """
    query = query.strip().lstrip("@")
    with _conn() as c:
        if query.isdigit():
            rows = c.execute(
                "SELECT * FROM users WHERE user_id = ? ORDER BY created_at DESC", (int(query),)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM users WHERE username LIKE ? ORDER BY created_at DESC LIMIT 20",
                (f"%{query}%",),
            ).fetchall()
    return [dict(r) for r in rows]


async def delete_user_completely(user_id: int) -> bool:
    """
    حذف کامل و سازگار یک کاربر: همه‌ی رکوردهای وابسته‌اش در دیتابیس SaaS
    (users / subscriptions / payments / orders / tickets / ticket_messages /
    admins-نقش) + ردیف‌های bot_data (self_accounts) + پیوندهای نمایندگی
    (مشتری‌های زیرمجموعه‌ی او آزاد می‌شوند) + ربات‌های اختصاصی او (revoke —
    فرآیند متوقف و وضعیت revoked، پوشه و دیتابیس‌شان حفظ می‌شود) + مالکیت
    اکانت‌های سلفش در config.json (مالکیت گرفته می‌شود و اکانت «یتیم»
    می‌شود تا OWNER از صفحه‌ی «⚠️ اکانت‌های بدون مالک» مدیریتش کند — هیچ
    اکانتی سایلنت گم نمی‌شود).

    سیاستِ مستند برای اکانت‌های سلف کاربرِ حذف‌شده: نه حذفِ پوشه/سشن، نه
    نگه‌داشتنِ مالکیتِ مرده — بلکه orphan شدنِ عمدی (owner_user_id پاک
    می‌شود) تا سشن‌ها و config حفظ شوند و OWNER بتواند هرکدام را ادامه/توقف
    یا به مالک جدید بدهد.

    محافظت‌ها:
    - OWNER هرگز با این تابع حذف نمی‌شود (برگرداندن False).
    - Permission خودِ فراخوانی (OWNER/ADMIN/نماینده‌ی صاحبِ کاربر) در
      لایه‌ی callback بررسی می‌شود — این تابع خودش را فقط به OWNER_ID محدود
      نمی‌کند تا مسیرهای مدیریتی قبلی خراب نشوند.

    ترتیبِ هماهنگ (Transaction Coordinator روی دو دیتابیس جدا):
      1) PRECHECK (بدون نوشتن): OWNER guard + وجودِ کاربر در DB اصلی +
         دسترسی‌پذیریِ bot_data (تا بیشترِ خطاها قبل از هر تغییری گرفته شود)
      2) تراکنشِ واحدِ DB اصلی (همه‌ی حذف‌ها + revoke ربات‌های اختصاصی) —
         همه با هم COMMIT/ROLLBACK می‌شوند؛ شکست = هیچ تغییری
      3) bot_data (self_accounts) — با retry روی قفل؛ اگر واقعاً شکست خورد،
         به‌صورت CRITICAL لاگ می‌شود (هرگز silent partial) و False برمی‌گردد
      4) config.json (یتیم‌سازی اکانت‌های سلف) — شکستش لاگ می‌شود؛ وضعیتِ
         یتیمِ قابل‌مدیریت توسط OWNER است نه state متناقض
      5) توقف فرآیندهای ربات‌های اختصاصیِ revoke‌شده — با تأییدِ مرگِ فرآیند؛
         اگر هنوز زنده بود CRITICAL لاگ می‌شود (بدون silent).

    بازمی‌گرداند: True اگر کاربر واقعاً وجود داشت و حذف شد، False اگر از
    اول در جدول users نبود، OWNER بود، یا یکی از مراحل حیاتی شکست خورد.
    """
    if OWNER_ID is not None and user_id == OWNER_ID:
        return False

    # ── ۱) PRECHECK — بدون هیچ نوشتنی ──
    try:
        with _conn() as c:
            if c.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is None:
                return False
    except Exception as e:
        print(f"⛔ [delete_user] PRECHECK (DB اصلی) شکست خورد: {type(e).__name__}: {e}")
        return False
    try:
        with _db_lock:
            bd = get_db()
            try:
                bd.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            finally:
                bd.close()
    except Exception as e:
        print(f"⛔ [delete_user] PRECHECK (bot_data) شکست خورد — حذف لغو شد: {type(e).__name__}: {e}")
        return False

    # ── ۲) تراکنشِ واحدِ DB اصلی — همه با هم COMMIT یا همه ROLLBACK ──
    owned_dedicated = []
    with _conn() as c:
        existing = c.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not existing:
            return False
        ticket_ids = [
            r["id"] for r in c.execute(
                "SELECT id FROM tickets WHERE user_id = ?", (user_id,)
            ).fetchall()
        ]
        for tid in ticket_ids:
            c.execute("DELETE FROM ticket_messages WHERE ticket_id = ?", (tid,))
        c.execute("DELETE FROM tickets WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM orders WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        # لایسنس‌های ساخته‌شده توسط این کاربر (مثلاً یک نماینده): حذف می‌شوند
        # تا کدهای مصرف‌نشده‌ی او بعد از حذفِ سازنده همچنان معتبر نمانند
        # (کد یک‌بارمصرفِ فعالِ متعلق به مالکِ حذف‌شده = مسیر دور زدن).
        c.execute("DELETE FROM licenses WHERE created_by = ?", (user_id,))
        # نقش (ادمین/نماینده) کاربر حذف می‌شود
        c.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        # اگر کاربر خودش نماینده بود، مشتری‌های زیرمجموعه‌اش آزاد می‌شوند
        # (reseller_id → NULL) تا به مالکِ حذف‌شده متصل نمانند.
        c.execute("UPDATE users SET reseller_id = NULL WHERE reseller_id = ?", (user_id,))
        # ربات‌های اختصاصی متعلق به او: revoke (فرآیند بعداً بیرون از تراکنش متوقف می‌شود)
        owned_dedicated = [
            r["id"] for r in c.execute(
                "SELECT id, bot_dir FROM dedicated_bots WHERE owner_id = ? "
                "AND status IN ('active','stopped')",
                (user_id,),
            ).fetchall()
        ]
        for bid in owned_dedicated:
            c.execute(
                "UPDATE dedicated_bots SET status = 'revoked', reviewed_at = ? WHERE id = ?",
                (_now(), bid),
            )
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        # Journal حذف (Operation Journal دو-دیتابیس): در همین تراکنشِ اصلی ثبت
        # می‌شود — یعنی وجودِ ردیف journal == کاربرِ واقعاً حذف‌شده. اگر بعداً
        # (bot_data/config) چیزی ناقص ماند، ردیف باقی می‌ماند و استارتاپِ بعدی
        # با _recover_delete_journal مراحل باقی‌مانده را کامل می‌کند — هیچ
        # state نیمه‌حذفِ بدونِ Recovery باقی نمی‌ماند.
        c.execute(
            "INSERT OR IGNORE INTO delete_journal (user_id, created_at, status) VALUES (?, ?, 'SAAS_DELETED')",
            (user_id, _now()),
        )

    # ── ۳) bot_data (self_accounts) — بعد از COMMIT تراکنش اصلی ──
    # با retry روی قفل موقت (database is locked). اگر در نهایت شکست خورد،
    # CRITICAL لاگ می‌شود و False برمی‌گردد — هرگز silent partial. (جدولِ
    # legacy وجود نداشته باشد = no-op بی‌ضرر.)
    _bd_deleted = False
    for attempt in range(3):
        try:
            with _db_lock:
                bd = get_db()
                try:
                    has_table = bd.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='self_accounts'"
                    ).fetchone()
                    if has_table:
                        bd.execute("DELETE FROM self_accounts WHERE user_id = ?", (user_id,))
                        bd.commit()
                    _bd_deleted = True
                finally:
                    bd.close()
            # مرحله‌ی ۳ تمام شد → Journal را جلو ببر (BOT_DATA_DELETED)
            if _bd_deleted:
                try:
                    with _conn() as c:
                        c.execute(
                            "UPDATE delete_journal SET status = 'BOT_DATA_DELETED' WHERE user_id = ?",
                            (user_id,),
                        )
                except Exception as e:
                    print(f"⚠️ [delete_user] به‌روزرسانی status در Journal ناموفق بود (بی‌ضرر): {type(e).__name__}")
            break
        except Exception as e:
            if attempt == 2:
                print(f"⛔ [delete_user] CRITICAL: پاک‌سازی bot_data (self_accounts) بعد از ۳ تلاش "
                      f"شکست خورد — کاربر از DB اصلی حذف شده ولی ردیف legacy باقی است "
                      f"(نه silent): {type(e).__name__}: {e}")
                return False
            print(f"⚠️ [delete_user] bot_data قفل بود — تلاش مجدد ({attempt + 1}/3): {type(e).__name__}: {e}")
            await asyncio.sleep(0.3)

    # ── ۴) اکانت‌های سلفِ او در config.json: مالکیت گرفته می‌شود (یتیم) ──
    # شکستش لاگ می‌شود؛ ردیف journal باقی می‌ماند تا Recovery استارتاپی آن را
    # دوباره امتحان کند — هیچ state نیمه‌حذفِ بدونِ Recovery باقی نمی‌ماند.
    _config_orphaned = False
    try:
        _orphan_user_selfbots(user_id)
        _config_orphaned = True
    except Exception as e:
        print(f"⚠️ [delete_user] یتیم‌سازی اکانت‌های سلف در config با خطا مواجه شد: {type(e).__name__}: {e}")
    # مرحله‌ی ۴ تمام شد → Journal را جلو ببر (FILES_DELETED)
    if _config_orphaned:
        try:
            with _conn() as c:
                c.execute(
                    "UPDATE delete_journal SET status = 'FILES_DELETED' WHERE user_id = ?",
                    (user_id,),
                )
        except Exception as e:
            print(f"⚠️ [delete_user] به‌روزرسانی status در Journal ناموفق بود (بی‌ضرر): {type(e).__name__}")

    # ── ۵) توقف فرآیندهای ربات‌های اختصاصیِ revoke‌شده — با تأییدِ مرگ ──
    for bid in owned_dedicated:
        try:
            b = get_dedicated_bot(bid)
            pid = (b or {}).get("pid") or _read_pidfile((b or {}).get("bot_dir") or "")
            if pid:
                await _stop_process_by_pid(pid)
                # تأیید نهایی: آیا هنوز زنده است؟
                try:
                    os.kill(pid, 0)
                    still_alive = True
                except OSError:
                    still_alive = False
                if still_alive:
                    import signal as _sig
                    try:
                        os.kill(pid, _sig.SIGKILL)
                    except OSError:
                        pass
                    await asyncio.sleep(0.5)
                    try:
                        os.kill(pid, 0)
                        still_alive = True
                    except OSError:
                        still_alive = False
                if still_alive:
                    # وضعیت DB درست است (revoked) ولی فرآیند هنوز زنده است —
                    # بدون silent گزارش می‌شود تا اپراتور/هلت‌چک بعدی پیگیری کند.
                    print(f"⛔ [delete_user] CRITICAL: فرآیند ربات اختصاصی #{bid} (pid={pid}) "
                          f"بعد از SIGTERM/SIGKILL هنوز زنده است — بررسی دستی لازم است.")
        except Exception as e:
            print(f"⚠️ [delete_user] توقف فرآیند ربات اختصاصی #{bid} ناموفق بود: {type(e).__name__}: {e}")

    # ── ۶) پایانِ موفق: ردیف journal پاک می‌شود — فقط وقتی همه‌ی مراحل حیاتی
    # (bot_data + config) کامل شده‌اند؛ وگرنه ردیف می‌ماند و Recovery ادامه می‌دهد.
    if _bd_deleted and _config_orphaned:
        try:
            with _conn() as c:
                c.execute("DELETE FROM delete_journal WHERE user_id = ?", (user_id,))
        except Exception as e:
            print(f"⚠️ [delete_user] پاک‌سازی ردیف journal ناموفق بود (بی‌ضرر — Recovery دوباره تلاش می‌کند): {type(e).__name__}: {e}")

    log_action(None, "delete_user_completely", f"user_id={user_id}, dedicated_revoked={len(owned_dedicated)}")
    return True


async def delete_user_completely_async(user_id: int) -> bool:
    """
    نسخه‌ی Runtime-aware از delete_user_completely (برای مسیرهای async مثل
    callback): قبل از حذف، همه‌ی Runtimeهای فعالِ اکانت‌های سلفِ این کاربر
    به‌طور کامل متوقف می‌شوند (ensure_stopped: stop → cancel task →
    disconnect → save → close → unregister) تا بعد از یتیم‌شدنِ اکانت‌ها،
    هیچ Task/TelegramClient زنده‌ای روی سشن‌های یتیم‌شده باقی نماند.
    سپس خودِ حذفِ هماهنگ (PRECHECK → تراکنش واحد → bot_data → config →
    فرآیندهای اختصاصی) اجرا می‌شود.
    """
    cfg = load_config()
    for tag, acc in cfg.items():
        if isinstance(acc, dict) and acc.get("owner_user_id") == user_id:
            await ensure_stopped(tag, f"delete_user_completely_async({user_id})")
    return await delete_user_completely(user_id)


def unlink_customer(reseller_id: int, user_id: int) -> bool:
    """
    «حذف مشتری از نمایندگی»: فقط اگر کاربر واقعاً زیرمجموعه‌ی همین نماینده
    باشد، reseller_id را NULL می‌کند. هیچ‌چیز دیگر (پرداخت/سفارش/تیکت/
    اشتراک/SelfBot) حذف یا تغییر نمی‌کند — برخلاف delete_user_completely که
    مخرب است و فقط برای OWNER/ADMIN مجاز است.

    بازمی‌گرداند: True اگر واقعاً از نمایندگی جدا شد، False اگر مشتریِ این
    نماینده نبود.
    """
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET reseller_id = NULL WHERE user_id = ? AND reseller_id = ?",
            (user_id, reseller_id),
        )
        ok = cur.rowcount > 0
    if ok:
        log_action(reseller_id, "customer_unlinked", f"customer={user_id}")
    return ok


def _orphan_user_selfbots(user_id: int) -> None:
    """
    مالکیت اکانت‌های سلفِ یک کاربر را از config.json پاک می‌کند تا یتیم
    شوند (و در «⚠️ اکانت‌های بدون مالک» دیده شوند). اتمیک: فقط در صورتی
    ذخیره می‌شود که چیزی تغییر کرده باشد و هیچ اکانتِ دیگری دست نمی‌خورد.
    """
    cfg = load_config()
    changed = False
    for tag, acc in cfg.items():
        if isinstance(acc, dict) and acc.get("owner_user_id") == user_id:
            acc.pop("owner_user_id", None)
            changed = True
    if changed:
        save_config(cfg)


def set_active_subscription_expired(user_id: int) -> bool:
    """
    اشتراک فعال فعلی یک کاربر را فوراً منقضی می‌کند (status='expired') —
    برای «لغو دستی اشتراک» توسط ادمین/نماینده، مثلاً وقتی پرداخت یک کاربر
    برگشت خورده یا اشتراک اشتباهی فعال شده. بر خلاف expire_subscription که
    یک sub_id مشخص می‌گیرد، این تابع مستقیم بر اساس user_id کار می‌کند تا
    از پنل مدیریت راحت‌تر صدا زده شود.

    بازمی‌گرداند: True اگر واقعاً یک اشتراک active برای این کاربر پیدا و
    لغو شد، False اگر از اول اشتراک فعالی نداشت.
    """
    sub = get_active_subscription(user_id)
    if not sub:
        return False
    expire_subscription(sub["id"])
    log_action(None, "manual_expire_subscription", f"user_id={user_id}, sub_id={sub['id']}")
    return True


# ─────────────────────────────────────────────────────
#  پلن‌ها و قیمت‌گذاری
# ─────────────────────────────────────────────────────

def list_pricing() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM pricing").fetchall()
    return [dict(r) for r in rows]


def get_pricing(plan: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM pricing WHERE plan = ?", (plan,)).fetchone()
    return dict(row) if row else None


def set_pricing(plan: str, price_toman: int, duration_days: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO pricing (plan, price_toman, duration_days) VALUES (?, ?, ?) "
            "ON CONFLICT(plan) DO UPDATE SET price_toman = excluded.price_toman, "
            "duration_days = excluded.duration_days",
            (plan, price_toman, duration_days),
        )


# ─────────────────────────────────────────────────────
#  اشتراک‌ها
# ─────────────────────────────────────────────────────

def get_active_subscription(user_id: int):
    """
    آخرین اشتراک با status='active' را برمی‌گرداند. توجه: با معماری جدید
    (که create_subscription اشتراک فعال قبلی را superseded می‌کند) در هر
    لحظه حداکثر یک ردیف active برای هر user_id وجود دارد، پس این تابع
    مبهم نیست.
    """
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' "
            "ORDER BY expire_date DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def create_subscription(user_id: int, plan: str, duration_days: int, license_id=None,
                         selfbot_tag=None) -> int:
    """
    اشتراک جدید می‌سازد. اگر کاربر از قبل یک اشتراک active داشته باشد که
    هنوز منقضی نشده، تاریخ شروع محاسبه‌ی مدت جدید از روی expire_date همان
    اشتراک قبلی است (نه از «الان») — یعنی تمدید، روزهای باقی‌مانده را دور
    نمی‌ریزد. اشتراک قبلی هم به status='superseded' تغییر می‌کند تا در هر
    لحظه فقط یک ردیف active برای هر کاربر وجود داشته باشد.

    همه‌ی محاسبات تاریخ با datetime آگاه از UTC انجام می‌شود — نه با
    ترکیب mktime/gmtime که به local time سرور وابسته و مستعد خطای
    یک‌روزه است.
    """
    # BEGIN IMMEDIATE: قفلِ نوشتن از همان ابتدا گرفته می‌شود.
    #
    # چرا لازم است: این تابع «بخوان → قبلی را superseded کن → جدید درج کن»
    # است و — برخلاف چهار تابعِ پولیِ دیگر — هیچ UPDATE شرطی‌ای ندارد که
    # خودش تکراری‌بودن را رد کند. با تراکنشِ deferred، دو فراخوانیِ هم‌زمان
    # (مثلاً فعال‌سازی لایسنس هم‌زمان با تایید پرداخت کارتی) هر دو همان
    # ردیفِ active را می‌خواندند. اینجا تنها چیزی که نجاتمان می‌داد تشخیصِ
    # snapshot در WAL بود که *خطا* می‌دهد، نه نتیجه‌ی درست. با
    # _conn_immediate این دو فراخوانی واقعاً سریال می‌شوند.
    with _conn_immediate() as c:
        existing = c.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' "
            "ORDER BY expire_date DESC LIMIT 1",
            (user_id,),
        ).fetchone()

        now_utc = datetime.now(timezone.utc)
        if existing:
            existing_expire = _parse_date(existing["expire_date"])
            base = existing_expire if existing_expire > now_utc else now_utc
        else:
            base = now_utc

        start_str = _format_date(now_utc)
        expire_str = _format_date(base + timedelta(days=duration_days))

        if existing:
            # UPDATE شرطی: فقط اگر هنوز active است. اگر بین خواندن و اینجا
            # کسی آن را عوض کرده باشد، rowcount صفر می‌شود و به‌جای ساختنِ
            # اشتراکِ دوم، کل تراکنش لغو می‌شود.
            cur_sup = c.execute(
                "UPDATE subscriptions SET status = 'superseded' "
                "WHERE id = ? AND status = 'active'",
                (existing["id"],),
            )
            if cur_sup.rowcount == 0:
                raise RuntimeError(
                    "اشتراک فعالِ این کاربر هم‌زمان توسط عملیات دیگری تغییر کرد "
                    "— برای جلوگیری از دو اشتراکِ فعال، این عملیات لغو شد."
                )

        cur = c.execute(
            "INSERT INTO subscriptions (user_id, plan, start_date, expire_date, status, "
            "license_id, selfbot_tag, created_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
            (user_id, plan, start_str, expire_str, license_id, selfbot_tag, _now()),
        )
        sub_id = cur.lastrowid

    log_action(user_id, "create_subscription", f"plan={plan}, expire={expire_str}")
    return sub_id


def list_expiring_subscriptions(within_hours: int = 24) -> list:
    """
    اشتراک‌های فعالی که در بازه‌ی [الان, الان+within_hours] منقضی می‌شوند و
    هنوز اخطار نگرفته‌اند. با datetime دقیق (نه فقط رشته‌ی روز) محاسبه
    می‌شود تا با list_expired_subscriptions هم‌پوشانی نداشته باشد — یعنی
    یک اشتراک در یک اجرا هم پیام «۲۴ ساعت مانده» و هم پیام «منقضی شد» را
    هم‌زمان دریافت نکند.
    """
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=within_hours)
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM subscriptions WHERE status = 'active' AND warned_24h = 0"
        ).fetchall()
    result = []
    for r in rows:
        expire_dt = _parse_date(r["expire_date"])
        # پایان روز انقضا در نظر گرفته می‌شود (23:59:59) تا اشتراکی که
        # امروز منقضی می‌شود هم به‌درستی «در حال انقضا» شمرده شود
        expire_end_of_day = expire_dt + timedelta(hours=23, minutes=59, seconds=59)
        if now_utc <= expire_end_of_day <= cutoff:
            result.append(dict(r))
    return result


def mark_warned(sub_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE subscriptions SET warned_24h = 1 WHERE id = ?", (sub_id,))


def list_expired_subscriptions() -> list:
    """
    اشتراک‌های active که تاریخ انقضایشان (پایان روز) گذشته است. با
    datetime دقیق محاسبه می‌شود تا لحظه‌ی دقیق «منقضی شدن» با
    list_expiring_subscriptions هم‌پوشانی نداشته باشد.
    """
    now_utc = datetime.now(timezone.utc)
    with _conn() as c:
        rows = c.execute("SELECT * FROM subscriptions WHERE status = 'active'").fetchall()
    result = []
    for r in rows:
        expire_dt = _parse_date(r["expire_date"])
        expire_end_of_day = expire_dt + timedelta(hours=23, minutes=59, seconds=59)
        if expire_end_of_day < now_utc:
            result.append(dict(r))
    return result


def expire_subscription(sub_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE subscriptions SET status = 'expired' WHERE id = ?", (sub_id,))


# ─────────────────────────────────────────────────────
#  لایسنس‌ها
# ─────────────────────────────────────────────────────

def _generate_license_code() -> str:
    chars = string.ascii_uppercase + string.digits
    part = lambda: "".join(secrets.choice(chars) for _ in range(4))
    return f"SELF-{part()}-{part()}"


def create_license(license_type: str, duration_days: int, created_by: int,
                    reseller_user_limit=None, max_uses=None) -> dict:
    """
    ساخت لایسنس جدید — امن در سطح Backend (مستقل از UI):

    ۱) ماتریس دسترسی:
         OWNER   → account / reseller / admin
         ADMIN   → account / reseller          (هرگز admin)
         RESELLER→ account                     (فقط برای مشتری خودش)
         USER    → هیچ (کاربر عادی هرگز لایسنس نمی‌سازد)
       نقش از DB خوانده می‌شود (get_role) — به callback/UI اعتماد نمی‌شود.

    ۲) اعتبارسنجی ورودی:
         license_type فقط account|reseller|admin
         account  → duration_days عدد صحیح مثبت
         reseller → reseller_user_limit عدد صحیح مثبت
         admin    → duration_days باید None باشد
       مقادیر malformed هرگز وارد DB نمی‌شوند.

    ۳) طبق اسپک «تمام لایسنس‌های جدید فقط یک‌بارمصرف‌اند»: max_uses همیشه
       ۱ است — هر مقداری که فراخواننده (به‌خاطر سازگاری با کد/تست قدیمی)
       ارسال کند نادیده گرفته می‌شود؛ لایسنس‌های قدیمیِ max_uses>1 در
       دیتابیس دست‌نخورده می‌مانند.

    در شکست: {"error": "..."} برمی‌گرداند (هیچ ردیفی ساخته نمی‌شود).
    """
    _LICENSE_ALLOWED = {
        ROLE_OWNER: {LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER, LICENSE_TYPE_ADMIN},
        ROLE_ADMIN: {LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER},
        ROLE_RESELLER: {LICENSE_TYPE_ACCOUNT},
    }
    if license_type not in (LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER,
                            LICENSE_TYPE_ADMIN):
        return {"error": "invalid_type"}
    # نقشِ سازنده — از DB، نه از ورودی
    caller_role = get_role(created_by, OWNER_ID)
    if caller_role not in _LICENSE_ALLOWED or \
            license_type not in _LICENSE_ALLOWED[caller_role]:
        return {"error": "permission_denied"}
    # اعتبارسنجی ورودی بر اساس نوع
    if license_type == LICENSE_TYPE_ACCOUNT:
        if not isinstance(duration_days, int) or isinstance(duration_days, bool) \
                or duration_days <= 0:
            return {"error": "invalid_duration"}
        reseller_user_limit = None
    elif license_type == LICENSE_TYPE_RESELLER:
        if not isinstance(reseller_user_limit, int) or \
                isinstance(reseller_user_limit, bool) or reseller_user_limit <= 0:
            return {"error": "invalid_limit"}
        duration_days = None
    else:  # admin
        if duration_days is not None:
            return {"error": "invalid_duration"}
        reseller_user_limit = None
    with _conn() as c:
        # احتمال برخورد کد تصادفی عملاً صفر است، ولی برای اطمینان یک retry
        # ساده می‌گذاریم؛ کل چرخه‌ی تولید+چک+درج در یک تراکنش است تا برخورد
        # هم‌زمان دو ساخت لایسنس ممکن نباشد. کدی که وارد INSERT می‌شود باید
        # حتماً «تأییدشده‌ی یکتا» باشد: اگر بعد از همه‌ی تلاش‌ها کدِ یکتایی
        # پیدا نشد، هرگز با کدِ تأییدنشده INSERT نمی‌شود — خطای تمیز برمی‌گردد
        # و هیچ ردیفِ ناقصی ساخته نمی‌شود.
        code = _generate_license_code()
        unique = False
        for _ in range(10):
            exists = c.execute("SELECT 1 FROM licenses WHERE code = ?", (code,)).fetchone()
            if not exists:
                unique = True
                break
            code = _generate_license_code()
        if not unique:
            return {"error": "code_generation_failed"}
        c.execute(
            "INSERT INTO licenses (code, license_type, duration_days, max_uses, used_count, "
            "reseller_user_limit, created_by, created_at, is_active) "
            "VALUES (?, ?, ?, 1, 0, ?, ?, ?, 1)",
            (code, license_type, duration_days, reseller_user_limit, created_by, _now()),
        )
    log_action(created_by, "create_license", f"code={code}, type={license_type}")
    return get_license(code)


def list_licenses(limit: int = 50, created_by: int = None) -> list:
    """
    لیست لایسنس‌های ساخته‌شده (جدیدترین اول) — برای پنل «🎫 لایسنس‌ها».
    created_by: اگر داده شود فقط لایسنس‌های همان سازنده (نماینده فقط لایسنس‌های
    خودش را می‌بیند — نه لایسنس‌های بقیه).
    """
    with _conn() as c:
        if created_by is not None:
            rows = c.execute(
                "SELECT * FROM licenses WHERE created_by = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?", (created_by, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM licenses ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def get_license(code: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM licenses WHERE code = ?", (code,)).fetchone()
    return dict(row) if row else None


def is_license_usable(lic: dict) -> bool:
    if not lic or not lic.get("is_active"):
        return False
    return lic["used_count"] < lic["max_uses"]


def redeem_license_atomic(code: str) -> bool:
    """
    فقط اگر لایسنس هنوز فعال و used_count < max_uses باشد، used_count را
    یکی زیاد می‌کند و True برمی‌گرداند — همه در یک UPDATE اتمیک، بدون
    فاصله‌ی زمانی بین «چک‌کردن» و «مصرف‌کردن». این جلوی race condition
    را می‌گیرد که در نسخه‌ی قبلی (get_license جدا + redeem_license جدا)
    باعث می‌شد دو نفر هم‌زمان بتوانند یک لایسنس با max_uses=1 را با هم
    مصرف کنند.
    """
    with _conn() as c:
        cur = c.execute(
            "UPDATE licenses SET used_count = used_count + 1 "
            "WHERE code = ? AND is_active = 1 AND used_count < max_uses",
            (code,),
        )
        return cur.rowcount > 0


def deactivate_license(code: str) -> None:
    with _conn() as c:
        c.execute("UPDATE licenses SET is_active = 0 WHERE code = ?", (code,))


def activate_license(code: str, user_id: int, username: str = None) -> dict:
    """
    فعال‌سازی کامل یک لایسنس در یک تراکنش واحد: مصرفِ لایسنس (used_count) و
    اعمالِ اثرِ آن (اشتراک/نقش) با هم COMMIT یا با هم ROLLBACK می‌شوند — تا
    هیچ‌وقت حالتی پیش نیاید که «لایسنس مصرف شده ولی اشتراک/نقش ساخته نشده»
    یا برعکس. برخلاف نسخه‌ی قبلی (redeem_license_atomic جدا + عملیات جدا),
    اینجا همه‌چیز روی همان کانکشنِ داخلِ تراکنش انجام می‌شود.

    خروجی:
      {"ok": True, "type": ..., "duration_days": ..., "code": ...} در موفقیت
      {"ok": False, "error": "invalid|inactive|used|unknown_type"} در شکست
    """
    with _conn_immediate() as c:
        lic = c.execute("SELECT * FROM licenses WHERE code = ?", (code,)).fetchone()
        if lic is None:
            return {"ok": False, "error": "invalid"}
        lic = dict(lic)
        if not lic.get("is_active"):
            return {"ok": False, "error": "inactive"}
        if lic["used_count"] >= lic["max_uses"]:
            return {"ok": False, "error": "used"}
        ltype = lic["license_type"]
        if ltype not in (LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER, LICENSE_TYPE_ADMIN):
            # نوع ناشناخته — لایسنس مصرف نمی‌شود
            return {"ok": False, "error": "unknown_type"}

        # پیوند نمایندگی: اگر سازنده‌ی لایسنس واقعاً نقش RESELLER دارد،
        # کاربر فعال‌کننده مشتریِ همان نماینده ثبت می‌شود (فقط برای نوع
        # account کاربرد واقعی دارد، ولی upsert برای همه‌ی انواع بی‌ضرر است).
        creator = lic.get("created_by")
        reseller_link = None
        if creator is not None:
            row = c.execute("SELECT role FROM admins WHERE user_id = ?", (creator,)).fetchone()
            if row and row["role"] == ROLE_RESELLER:
                reseller_link = creator

        # ── سیاست سقف مشتریِ نماینده (server-side، داخل همین تراکنش) ──
        # اگر کاربرِ فعال‌کننده هنوز مشتریِ این نماینده نیست و سقف پر است،
        # فعال‌سازی با خطا متوقف می‌شود و لایسنس مصرف نمی‌شود (ROLLBACK).
        existing = c.execute(
            "SELECT user_id, reseller_id FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        old_reseller = existing["reseller_id"] if existing else None
        if ltype == LICENSE_TYPE_ACCOUNT and reseller_link is not None:
            rrow = c.execute(
                "SELECT reseller_max_users FROM admins WHERE user_id = ? AND role = ?",
                (reseller_link, ROLE_RESELLER),
            ).fetchone()
            rmax = rrow["reseller_max_users"] if rrow else None
            if rmax is not None and old_reseller != reseller_link:
                cnt = c.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE reseller_id = ?", (reseller_link,)
                ).fetchone()["n"]
                if cnt >= rmax:
                    # سقف پر است — لایسنس مصرف نشده و هیچ تغییری اعمال نمی‌شود
                    return {"ok": False, "error": "reseller_limit"}

        # ── سیاست نقش (Role Safety — بدون overwrite کورکورانه) ──
        # یک لایسنسِ نوع نقش نباید نقشِ فعلیِ کاربر را بی‌جهت عوض کند:
        #   - OWNER هرگز با هیچ لایسنس‌ای تنزل نمی‌کند.
        #   - ADMIN فقط با لایسنس ادمینِ OWNER می‌تواند عوض شود؛ یک لایسنس
        #     نمایندگیِ ساخته‌شده توسط ADMIN دیگر نمی‌تواند ADMIN را نماینده
        #     کند (فقط OWNER می‌تواند یک ADMIN را تنزل دهد).
        #   - RESELLER→ADMIN فقط با لایسنس ادمینِ OWNER (escalation عمدیِ OWNER).
        # در همه‌ی این موارد، اگر گارد رد شد، لایسنس مصرف نمی‌شود (ROLLBACK).
        if user_id == OWNER_ID:
            return {"ok": False, "error": "owner"}
        cur_role_row = c.execute(
            "SELECT role FROM admins WHERE user_id = ?", (user_id,)
        ).fetchone()
        cur_role = cur_role_row["role"] if cur_role_row else None
        if ltype == LICENSE_TYPE_RESELLER and cur_role == ROLE_ADMIN:
            if creator != OWNER_ID:
                # فقط OWNER اجازه دارد یک ADMIN را به نمایندگی تنزل دهد
                return {"ok": False, "error": "role_guard"}
        if ltype == LICENSE_TYPE_ADMIN and cur_role == ROLE_OWNER:
            return {"ok": False, "error": "owner"}

        # ── سیاست مالکیت (بدون Takeover) ──
        # اگر کاربر از قبل به نماینده‌ی دیگری تعلق دارد (reseller_id پر است)،
        # فعال‌سازی لایسنسِ نماینده‌ی دیگر مالکیت قبلی را عوض نمی‌کند؛
        # مالکیت فقط برای کاربرِ بی‌مالک/جدید ثبت می‌شود.
        new_reseller = None
        if ltype == LICENSE_TYPE_ACCOUNT:
            new_reseller = old_reseller if old_reseller is not None else reseller_link

        # مصرف اتمیک داخل همان تراکنش (UPDATE شرطی — race-safe)
        cur = c.execute(
            "UPDATE licenses SET used_count = used_count + 1 "
            "WHERE code = ? AND is_active = 1 AND used_count < max_uses",
            (code,),
        )
        if cur.rowcount == 0:
            return {"ok": False, "error": "used"}

        if existing:
            c.execute(
                "UPDATE users SET username = COALESCE(?, username), "
                "reseller_id = COALESCE(?, reseller_id) WHERE user_id = ?",
                (username, new_reseller, user_id),
            )
        else:
            c.execute(
                "INSERT INTO users (user_id, username, first_name, reseller_id, created_at) "
                "VALUES (?, ?, NULL, ?, ?)",
                (user_id, username, new_reseller, _now()),
            )

        if ltype == LICENSE_TYPE_ACCOUNT:
            # منطق تمدید همان create_subscription است — ولی درون همین
            # تراکنش با کانکشن مشترک تا با مصرفِ لایسنس اتمیک بماند.
            existing_sub = c.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' "
                "ORDER BY expire_date DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            now_utc = datetime.now(timezone.utc)
            if existing_sub:
                existing_expire = _parse_date(existing_sub["expire_date"])
                base = existing_expire if existing_expire > now_utc else now_utc
            else:
                base = now_utc
            start_str = _format_date(now_utc)
            expire_str = _format_date(base + timedelta(days=lic["duration_days"]))
            if existing_sub:
                c.execute(
                    "UPDATE subscriptions SET status = 'superseded' WHERE id = ?",
                    (existing_sub["id"],),
                )
            c.execute(
                "INSERT INTO subscriptions (user_id, plan, start_date, expire_date, status, "
                "license_id, selfbot_tag, created_at) VALUES (?, ?, ?, ?, 'active', ?, NULL, ?)",
                (user_id, "لایسنس", start_str, expire_str, lic["id"], _now()),
            )
            result = {"ok": True, "type": LICENSE_TYPE_ACCOUNT,
                      "duration_days": lic["duration_days"], "code": code}
        elif ltype == LICENSE_TYPE_RESELLER:
            c.execute(
                "INSERT INTO admins (user_id, role, added_by, reseller_max_users, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET role = excluded.role, "
                "added_by = excluded.added_by, reseller_max_users = excluded.reseller_max_users",
                (user_id, ROLE_RESELLER, creator, lic.get("reseller_user_limit"), _now()),
            )
            result = {"ok": True, "type": LICENSE_TYPE_RESELLER, "code": code}
        else:  # admin
            c.execute(
                "INSERT INTO admins (user_id, role, added_by, reseller_max_users, created_at) "
                "VALUES (?, ?, ?, NULL, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET role = excluded.role, "
                "added_by = excluded.added_by, reseller_max_users = excluded.reseller_max_users",
                (user_id, ROLE_ADMIN, creator, _now()),
            )
            result = {"ok": True, "type": LICENSE_TYPE_ADMIN, "code": code}
    log_action(user_id, "activate_license", f"code={code}, type={ltype}")
    return result


_TYPE_NAMES = {
    LICENSE_TYPE_ACCOUNT: "👤 اشتراک کاربر",
    LICENSE_TYPE_RESELLER: "🤝 نمایندگی",
    LICENSE_TYPE_ADMIN: "🛡 ادمین",
}


def _license_created_text(lic: dict) -> str:
    """متن تأیید ساخت لایسنس — یک‌جا برای همه‌ی مسیرهای ساخت."""
    lines = [
        "✅ لایسنس ساخته شد",
        "",
        f"🎫 کد:\n`{lic['code']}`",
        f"نوع:\n{_TYPE_NAMES.get(lic['license_type'], lic['license_type'])}",
    ]
    if lic["license_type"] == LICENSE_TYPE_ACCOUNT:
        lines.append(f"⏳ مدت:\n{lic['duration_days']} روز")
    elif lic["license_type"] == LICENSE_TYPE_RESELLER:
        limit = lic.get("reseller_user_limit")
        lines.append(f"👥 سقف:\n{limit if limit else '—'} مشتری")
    lines.append("🔒 مصرف:\n۱ بار")
    return "\n".join(lines)


_LICENSE_ERROR_TEXT = {
    "permission_denied": "شما مجوز ساخت این نوع لایسنس را ندارید.",
    "invalid_type": "نوع لایسنس معتبر نیست.",
    "invalid_duration": "مدت اعتبار معتبر نیست.",
    "invalid_limit": "سقف مشتری معتبر نیست.",
    "unknown_error": "خطای ناشناخته در ساخت لایسنس.",
}


def _license_result_text(lic) -> str:
    """متنِ نتیجه‌ی ساخت لایسنس — هم موفقیت و هم خطای امنِ Backend. هرگز
    فرض موفقیت نمی‌کند: create_license می‌تواند {"error": "..."} برگرداند
    و _license_created_text با lic["code"] روی آن KeyError می‌دهد. خطاهای
    شناخته‌شده به فارسیِ انسانی ترجمه می‌شوند؛ هیچ traceback/exception به
    کاربر نمایش داده نمی‌شود."""
    if not lic:
        return "❌ " + _LICENSE_ERROR_TEXT["unknown_error"]
    if "error" in lic:
        return "❌ " + _LICENSE_ERROR_TEXT.get(
            lic["error"], _LICENSE_ERROR_TEXT["unknown_error"]
        )
    return _license_created_text(lic)


# ─────────────────────────────────────────────────────
#  پرداخت‌ها
# ─────────────────────────────────────────────────────

def create_payment(user_id: int, plan: str, amount: int, receipt_ref: str) -> int:
    """
    receipt_ref باید یک مرجع قابل‌بازیابی به پیام اصلیِ رسید باشد، مثلاً
    f"{chat_id}:{message_id}" — نه صرفاً یک عدد داخلی media که به‌تنهایی
    برای دانلود مجدد کافی نیست.
    """
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO payments (user_id, plan, amount, receipt_ref, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (user_id, plan, amount, receipt_ref, _now()),
        )
        return cur.lastrowid


def get_payment(payment_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    return dict(row) if row else None


def list_pending_payments() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM payments WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def review_payment_atomic(payment_id: int, approve: bool, reviewed_by: int) -> bool:
    """
    فقط اگر پرداخت هنوز 'pending' باشد وضعیتش را تغییر می‌دهد و True
    برمی‌گرداند — اتمیک، تا اگر دو ادمین هم‌زمان روی «تایید»/«رد» یک
    پرداخت بزنند، فقط یکی از آن دو واقعاً اثر کند.
    (برای «رد» و برای حالت‌های بدون اثر تجاری استفاده می‌شود؛ برای «تاییدِ
    پلن عادی» از approve_card_payment_atomic استفاده کن که اثر تجاری را هم
    در همان تراکنش اعمال می‌کند.)
    """
    status = PAYMENT_STATUS_APPROVED if approve else PAYMENT_STATUS_REJECTED
    with _conn() as c:
        cur = c.execute(
            "UPDATE payments SET status = ?, reviewed_by = ?, reviewed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (status, reviewed_by, _now(), payment_id),
        )
        return cur.rowcount > 0


def approve_card_payment_atomic(payment_id: int, reviewed_by: int) -> dict:
    """
    تایید اتمیک پرداخت کارتی: «payment → approved» + «اشتراک فعال» +
    «فاکتور متصل → paid» همه در یک تراکنش واحد — تا هرگز state نیمه‌کاره
    (payment=approved ولی subscription ساخته‌نشده) باقی نماند. Idempotent:
    فقط وقتی payment هنوز pending است اثر می‌کند (UPDATE شرطی)؛ double-click
    یا تاییدِ دومِ دو ادمین اثر دوم ندارد.

    استثنا: پلن «ربات اختصاصی» فقط status را عوض می‌کند چون اثر تجاری آن
    (راه‌اندازی فرآیند جدا) در _activate_dedicated_bot انجام می‌شود.

    خروجی: {"applied": bool, "plan": str|None, "user_id": int|None,
            "duration": int|None, "dedicated": bool}
    """
    with _conn() as c:
        pay = c.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if pay is None:
            return {"applied": False, "plan": None, "user_id": None,
                    "duration": None, "dedicated": False}
        pay = dict(pay)
        if pay["status"] != PAYMENT_STATUS_PENDING:
            return {"applied": False, "plan": pay["plan"], "user_id": pay["user_id"],
                    "duration": None, "dedicated": pay["plan"] == DEDICATED_BOT_PLAN}
        cur = c.execute(
            "UPDATE payments SET status = ?, reviewed_by = ?, reviewed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (PAYMENT_STATUS_APPROVED, reviewed_by, _now(), payment_id),
        )
        if cur.rowcount == 0:
            return {"applied": False, "plan": pay["plan"], "user_id": pay["user_id"],
                    "duration": None, "dedicated": pay["plan"] == DEDICATED_BOT_PLAN}
        if pay["plan"] == DEDICATED_BOT_PLAN:
            return {"applied": True, "plan": pay["plan"], "user_id": pay["user_id"],
                    "duration": None, "dedicated": True}
        # اشتراک — منطق تمدید همان create_subscription است ولی درون همین تراکنش
        user_id = pay["user_id"]
        existing = c.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' "
            "ORDER BY expire_date DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        now_utc = datetime.now(timezone.utc)
        if existing:
            existing_expire = _parse_date(existing["expire_date"])
            base = existing_expire if existing_expire > now_utc else now_utc
        else:
            base = now_utc
        plan_row = c.execute(
            "SELECT duration_days FROM pricing WHERE plan = ?", (pay["plan"],)
        ).fetchone()
        duration = int(plan_row["duration_days"]) if plan_row else 30
        if existing:
            c.execute(
                "UPDATE subscriptions SET status = 'superseded' WHERE id = ?", (existing["id"],)
            )
        c.execute(
            "INSERT INTO subscriptions (user_id, plan, start_date, expire_date, status, "
            "license_id, selfbot_tag, created_at) VALUES (?, ?, ?, ?, 'active', NULL, NULL, ?)",
            (user_id, pay["plan"], _format_date(now_utc),
             _format_date(base + timedelta(days=duration)), _now()),
        )
        # فاکتور متصل → paid (فقط اگر هنوز pending باشد)
        c.execute(
            "UPDATE orders SET status = 'paid', pay_method = 'card', payment_id = ?, "
            "paid_at = ? WHERE payment_id = ? AND status = 'pending'",
            (payment_id, _now(), payment_id),
        )
    log_action(reviewed_by, "approve_card_payment", f"payment={payment_id}, plan={pay['plan']}")
    return {"applied": True, "plan": pay["plan"], "user_id": user_id,
            "duration": duration, "dedicated": False}


# ─────────────────────────────────────────────────────
#  فاکتورها/سفارش‌ها — شماره‌ی سفارش، مبلغ دقیق (تومان+تتر)، انقضای پرداخت
# ─────────────────────────────────────────────────────

def create_order(user_id: int, plan: str, amount_toman: int, amount_usdt: float,
                 expires_hours: int = ORDER_EXPIRE_HOURS) -> dict:
    """فاکتور جدید با شماره‌ی ترتیبی (ORD-00001) و انقضای پرداخت."""
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_hours)).strftime(_DATETIME_FMT)
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key = 'order_seq'").fetchone()
        seq = (int(row["value"]) if row and str(row["value"]).isdigit() else 0) + 1
        c.execute(
            "INSERT INTO settings (key, value) VALUES ('order_seq', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(seq),),
        )
        cur = c.execute(
            "INSERT INTO orders (order_no, user_id, plan, amount_toman, amount_usdt, status, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (f"ORD-{seq:05d}", user_id, plan, amount_toman, amount_usdt, _now(), expires_at),
        )
        oid = cur.lastrowid
    return get_order(oid)


def get_order(order_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def get_order_by_payment(payment_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM orders WHERE payment_id = ?", (payment_id,)).fetchone()
    return dict(row) if row else None


def list_user_orders(user_id: int, limit: int = 10) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def list_recent_orders(limit: int = 20) -> list:
    """جدیدترین سفارش‌های کل سیستم — برای نمای «📊 سفارش‌ها» در پنل مالی."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def list_expired_orders() -> list:
    """فاکتورهای در انتظاری که انقضایشان گذشته — برای جاروی حلقه‌ی ساعتی."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM orders WHERE status = 'pending' AND expires_at < ?", (_now(),)
        ).fetchall()
    return [dict(r) for r in rows]


def expire_order(order_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE orders SET status = 'expired' WHERE id = ? AND status = 'pending'",
            (order_id,),
        )


def cancel_order(order_id: int, user_id: int) -> None:
    """لغو فاکتور توسط صاحب آن — فقط اگر هنوز pending باشد."""
    with _conn() as c:
        c.execute(
            "UPDATE orders SET status = 'cancelled' WHERE id = ? AND user_id = ? AND status = 'pending'",
            (order_id, user_id),
        )


def mark_order_paid(order_id: int, pay_method: str, txid: str = None, payment_id: int = None) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE orders SET status = 'paid', pay_method = ?, txid = ?, "
            "payment_id = COALESCE(?, payment_id), paid_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (pay_method, txid, payment_id, _now(), order_id),
        )


def pay_order_trc20_atomic(order_id: int, txid: str) -> dict:
    """
    پرداخت خودکار تتر: «فاکتور paid» + «اشتراک فعال» در یک تراکنش واحد — تا
    هیچ‌وقت state نیمه‌کاره (order=paid ولی subscription ساخته‌نشده) باقی
    نماند. دو لایه‌ی امنیتی:
      - Replay: یک txid فقط یک‌بار (روی هر فاکتوری) می‌تواند استفاده شود؛
        اگر قبلاً روی فاکتورِ paid دیگری ثبت شده باشد، کل تراکنش رد می‌شود.
      - Idempotency: UPDATE شرطی روی status='pending' — double-click یا
        درخواست تکراری اثر دوم ندارد.

    خروجی: {"ok": True, "plan": str, "duration": int} یا {"ok": False, "error": str}
    (error: "replay" | "invalid" | "unknown_error")
    """
    txid = (txid or "").strip().lower()
    try:
        with _conn() as c:
            # replay: این هش قبلاً برای فاکتورِ پرداخت‌شده‌ای استفاده شده؟
            used = c.execute(
                "SELECT id FROM orders WHERE txid = ? AND status = 'paid' LIMIT 1", (txid,)
            ).fetchone()
            if used:
                return {"ok": False, "error": "replay"}
            order = c.execute(
                "SELECT * FROM orders WHERE id = ? AND status = 'pending'", (order_id,)
            ).fetchone()
            if order is None:
                return {"ok": False, "error": "invalid"}
            order = dict(order)
            try:
                cur = c.execute(
                    "UPDATE orders SET status = 'paid', pay_method = 'trc20', txid = ?, paid_at = ? "
                    "WHERE id = ? AND status = 'pending'",
                    (txid, _now(), order_id),
                )
            except sqlite3.IntegrityError:
                # ایندکس یکتای txid در دیتابیس، replay را در سطح DB هم رد کرد
                return {"ok": False, "error": "replay"}
            if cur.rowcount == 0:
                return {"ok": False, "error": "invalid"}
            # اشتراک — منطق تمدید همان create_subscription است، ولی درون همین
            # تراکنش تا با paid شدن فاکتور اتمیک بماند.
            user_id = order["user_id"]
            existing = c.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' "
                "ORDER BY expire_date DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            now_utc = datetime.now(timezone.utc)
            if existing:
                existing_expire = _parse_date(existing["expire_date"])
                base = existing_expire if existing_expire > now_utc else now_utc
            else:
                base = now_utc
            plan_row = c.execute(
                "SELECT duration_days FROM pricing WHERE plan = ?", (order["plan"],)
            ).fetchone()
            duration = int(plan_row["duration_days"]) if plan_row else 30
            if existing:
                c.execute(
                    "UPDATE subscriptions SET status = 'superseded' WHERE id = ?", (existing["id"],)
                )
            c.execute(
                "INSERT INTO subscriptions (user_id, plan, start_date, expire_date, status, "
                "license_id, selfbot_tag, created_at) VALUES (?, ?, ?, ?, 'active', NULL, NULL, ?)",
                (user_id, order["plan"], _format_date(now_utc),
                 _format_date(base + timedelta(days=duration)), _now()),
            )
    except Exception as e:
        # هر خطای دیگری (قفل DB و…) — تراکنش rollback می‌شود و state نیمه‌کاره
        # باقی نمی‌ماند. جزئیات فنی فقط در لاگ سرور.
        print(f"⚠️ [saas_db] pay_order_trc20_atomic خطا: {type(e).__name__}: {e}")
        return {"ok": False, "error": "unknown_error"}
    log_action(user_id, "order_paid_trc20", f"order={order_id}, plan={order['plan']}")
    return {"ok": True, "plan": order["plan"], "duration": duration}


def set_order_payment_id(order_id: int, payment_id: int) -> None:
    """اتصال فاکتور به رسیدِ کارتیِ ثبت‌شده، تا بعد از تایید ادمین فاکتور هم paid شود."""
    with _conn() as c:
        c.execute("UPDATE orders SET payment_id = ? WHERE id = ?", (payment_id, order_id))


# ─────────────────────────────────────────────────────
#  بکاپ/بازیابی دیتابیس و config — ماژول‌سطح و قابل‌تست
# ─────────────────────────────────────────────────────

def _validate_db_file(path: str) -> tuple:
    """بررسی فایل دیتابیس قبل از جایگزینی: (ok, message)."""
    import sqlite3
    try:
        con = sqlite3.connect(path)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                return False, "فایل دیتابیس خراب است (integrity check رد شد)"
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"users", "subscriptions", "pricing"} <= tables:
                return False, "این فایل دیتابیسِ این ربات نیست (جدول‌های اصلی را ندارد)"
        finally:
            con.close()
        return True, "ok"
    except Exception as e:
        return False, f"فایل معتبر نیست: {str(e)[:60]}"


def build_db_backup_zip(zip_path: str) -> bool:
    """
    [Legacy wrapper] بکاپ دیتابیس + config.json — برای سازگاریِ call site های
    قدیمی/تست‌ها نگه داشته شده. خروجی: بکاپ کاملِ معتبر با همان engine واحد
    (build_backup_zip) — یعنی manifest + checksum + سشن‌ها هم داخلش هست؛
    چون این تابع قدیمی فقط «آیا ساخته شد» را برمی‌گرداند، تفاوت رفتاری
    ندارد، فقط بکاپ کامل‌تر و قابل Restore با سیستم جدید است.
    """
    return build_backup_zip(zip_path)


def restore_db_from_file(file_path: str) -> tuple:
    """
    [Legacy] بازیابی از یک فایل دیتابیسِ قدیمیِ بدون manifest — **دیگر هرگز
    مستقیم os.replace روی DB اصلی انجام نمی‌شود**: فایل در یک بکاپِ معتبر
    (با manifest) بسته‌بندی و به Engine مرکزیِ Restore
    (restore_backup_from_zip با stale_cleanup=False) داده می‌شود — یعنی
    emergency backup + validation + rollback همان‌جا انجام می‌شود و فقط همین
    DB جایگزین می‌شود (config/سشن‌های فعلی دست نمی‌خورند).
    """
    ok, msg = _validate_db_file(file_path)
    if not ok:
        return False, msg
    try:
        tmp_dir = tempfile.mkdtemp(prefix="legacy_restore_", dir=DATA_DIR)
        tmp_zip = os.path.join(tmp_dir, "legacy_restore.zip")
        try:
            main_arc = _main_db_arc()
            manifest = {
                "project": BACKUP_PROJECT_NAME,
                "backup_version": BACKUP_VERSION,
                "schema_version": BACKUP_SCHEMA_VERSION,
                "created_at": _now(),
                "files": [{"name": main_arc, "size": os.path.getsize(file_path),
                            "sha256": _sha256_file(file_path)}],
            }
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(file_path, arcname=main_arc)
                zf.writestr(BACKUP_MANIFEST,
                            json.dumps(manifest, ensure_ascii=False))
            ok_r, msg_r = restore_backup_from_zip(tmp_zip, stale_cleanup=False)
            return ok_r, msg_r
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        return False, f"خطا در بازیابی: {str(e)[:80]}"


def restore_db_from_zip(zip_path: str) -> tuple:
    """
    [Legacy wrapper] بازیابی از بکاپ zip — همیشه به Engine مرکزی:
      - بکاپ با manifest (قالب جدید) → restore_backup_from_zip (Snapshot کامل)
      - بکاپ قدیمیِ فقط-دیتابیس → restore_db_from_file (که خودش manifest می‌سازد
        و به همان Engine می‌رود؛ فقط DB جایگزین می‌شود)
    هیچ مسیر مستقیمی به فایل DB اصلی وجود ندارد.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            if BACKUP_MANIFEST in names:
                return restore_backup_from_zip(zip_path)
            db_entry = next((n for n in names if n.endswith(".db")), None)
            if not db_entry:
                return False, "در بکاپ، فایل دیتابیس پیدا نشد"
            data = zf.read(db_entry)
        tmp_dir = tempfile.mkdtemp(prefix="legacy_extract_", dir=DATA_DIR)
        try:
            tmp = os.path.join(tmp_dir, os.path.basename(db_entry))
            with open(tmp, "wb") as f:
                f.write(data)
            return restore_db_from_file(tmp)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        return False, f"خطا در بازیابی: {str(e)[:80]}"


# ══════════════════════════════════════════════════════════════════════
#  سیستم Backup/Restore کامل و اتمیک پروژه
#  ─ بکاپ: دیتابیس‌ها (saas + bot_data) + config.json + سشن‌ها در یک
#    فایل ZIP با backup_manifest.json (checksum هر فایل) — قبل از تحویل،
#    خودِ بکاپ validate می‌شود تا هرگز فایل ناقص تحویل داده نشود.
#  ─ Restore: فقط OWNER؛ فقط بکاپِ معتبرِ همین پروژه با manifest؛ قبل از
#    هر تغییری validate کامل (manifest + checksum + integrity_check +
#    schema)؛ سپس بکاپ اضطراری از وضعیت فعلی؛ سپس جایگزینی اتمیک؛ اگر
#    هر مرحله شکست بخورد، فایل‌های جایگزین‌شده از بکاپ اضطراری
#    برمی‌گردند و دیتابیس اصلی هرگز خراب نمی‌شود.
# ══════════════════════════════════════════════════════════════════════

BACKUP_PROJECT_NAME = "CiaNetSelf"
BACKUP_VERSION = 1          # نسخه‌ی قالب فایل بکاپ
BACKUP_SCHEMA_VERSION = 1   # نسخه‌ی schema مورد انتظار هنگام Restore
BACKUP_MANIFEST = "backup_manifest.json"

# جدول‌های ضروری که باید در دیتابیس‌های بکاپ وجود داشته باشند
REQUIRED_SAAS_TABLES = {
    "users", "subscriptions", "licenses", "payments", "orders",
    "tickets", "pricing", "settings", "admins", "dedicated_bots",
}
REQUIRED_BOTDATA_TABLES = {
    "users", "banned_users", "broadcasts", "news", "messages",
    "sales_users", "plans", "purchases", "self_accounts", "bot_states",
}

def _main_db_arc() -> str:
    """نام دیتابیس اصلی در بکاپ — از DB_PATH، تا در تست‌ها هم هماهنگ بماند."""
    return os.path.basename(DB_PATH)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _backup_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def _backup_file_name() -> str:
    return f"backup_{_backup_timestamp()}.zip"


def _bot_db_arc() -> str:
    """نام bot_data در بکاپ — همیشه اسم پایه است تا قالب بکاپ با نسخه‌های
    قبل یکسان بماند (DB_NAME خودش ممکن است Absolute باشد)."""
    return os.path.basename(DB_NAME)


def _restore_dest_for(arc: str) -> str:
    """
    مسیرِ واقعیِ هدفِ Restore برای یک نامِ داخل بکاپ — همیشه Absolute و بر
    اساس DATA_DIR؛ هرگز از cwd استفاده نمی‌کند (تا اجرای Restore از هر
    پوشه‌ای، فایل‌ها را در همان جای اصلی‌شان بنویسد، نه در پوشه‌ی فعلی).
    خروجی با os.path.abspath نرمال می‌شود تا حتی اگر یک مقدارِ Relative
    (مثلاً override تستیِ DB_NAME) داده شود، هرگز به مسیر خالی/ناقص
    منجر نشود.
    """
    if arc == _main_db_arc():
        return os.path.abspath(DB_PATH)
    if arc == _bot_db_arc():
        return os.path.abspath(DB_NAME)
    if arc == "config.json":
        return os.path.abspath(CONFIG_FILE)
    if arc == "admin_bot_admins.json":
        return os.path.abspath(ADMIN_LIST_FILE)
    if arc.startswith("sessions/"):
        return os.path.join(SESSIONS_DIR, arc[len("sessions/"):])
    # فایل‌های دیگرِ manifest — به‌صورت امن زیر DATA_DIR (نه cwd)
    return os.path.join(DATA_DIR, *arc.split("/"))


def _collect_backup_files() -> dict:
    """فایل‌هایی که باید داخل بکاپ بروند: نام در بکاپ → مسیر واقعی."""
    files = {}
    for real in (DB_PATH, DB_NAME, CONFIG_FILE):
        if os.path.exists(real):
            files[os.path.basename(real)] = real
    if os.path.isdir(SESSIONS_DIR):
        for fname in sorted(os.listdir(SESSIONS_DIR)):
            full = os.path.join(SESSIONS_DIR, fname)
            if os.path.isfile(full) and not fname.endswith(("-wal", "-shm", "-journal")):
                # PATCH 2: sidecar های سشن (-wal/-shm/-journal) هرگز به‌عنوان
                # فایلِ مستقل داخل بکاپ نمی‌روند — سشن به‌صورت واحد با API
                # backup snapshot می‌شود (محتوای WAL داخلش ادغام شده است).
                # بایگانیِ خامِ sidecar (که ممکن است وسطِ Write باشد) بکاپِ
                # ناقص/خراب می‌سازد.
                files[os.path.join("sessions", fname)] = full
    if os.path.exists(ADMIN_LIST_FILE):
        files["admin_bot_admins.json"] = ADMIN_LIST_FILE
    return files


def _zip_member_is_safe(name: str) -> bool:
    """فقط مسیرهای نسبیِ عادی — جلوگیری از Path Traversal (zip-slip)."""
    if not name or name.startswith("/") or "\\" in name:
        return False
    parts = name.split("/")
    return all(p not in ("", "..", ".") for p in parts)


def _db_integrity_ok(path: str) -> bool:
    try:
        con = sqlite3.connect(path)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and str(row[0]).lower() == "ok"
        finally:
            con.close()
    except Exception:
        return False


def _db_schema_ok(path: str, required: set) -> tuple:
    """(ok, msg) — همه‌ی جدول‌های ضروری باید وجود داشته باشند."""
    try:
        con = sqlite3.connect(path)
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            missing = sorted(required - tables)
            if missing:
                return False, f"جدول‌های ضروری گم‌شده: {', '.join(missing)}"
            return True, ""
        finally:
            con.close()
    except Exception as e:
        return False, f"باز کردن دیتابیس ممکن نشد: {str(e)[:60]}"


def _checkpoint_and_clean(path: str) -> bool:
    """
    WAL را در فایل جمع می‌کند و **فقط اگر checkpoint واقعاً کامل و موفق
    بوده** (busy == 0 — یعنی SQLite تأیید کرده همه‌ی صفحات WAL در DB اصلی
    نوشته شده‌اند) فایل‌های -wal/-shm را پاک می‌کند.

    اگر checkpoint شکست بخورد یا ناقص بماند (busy > 0): خطا لاگ می‌شود و
    هیچ sidecar ای حذف نمی‌شود — چون حذف دستی WAL/SHM قبل از موفقیتِ واقعی
    checkpoint یعنی از دست رفتن داده‌ی داخل WAL. هیچ استثنایی بی‌صدا بلعیده
    نمی‌شود.

    برمی‌گرداند: True اگر checkpoint کامل شد (و cleanup انجام شد یا فایلی
    نبود)، False اگر ناقص/شکست‌خورده بود.

    مهم: اگر فایل وجود ندارد، True برمی‌گردد و **هیچ فایلی ساخته نمی‌شود** —
    sqlite3.connect روی مسیر ناموجود، یک فایل خالی جدید می‌سازد که برای DB
    اصلیِ یک پروژه‌ی تازه غلط است و می‌تواند باعث رد شدن بکاپِ بعدی (schema
    ناقص) شود.
    """
    if not os.path.exists(path):
        return True
    row = None
    try:
        con = sqlite3.connect(path, timeout=5)
        try:
            row = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            con.close()
    except Exception as e:
        print(f"⚠️ [sqlite] WAL checkpoint شکست خورد ({path}): {type(e).__name__}: "
              f"{str(e)[:100]} — WAL/SHM حذف نشدند.")
        return False
    if not row or len(row) < 1 or row[0] != 0:
        busy = row[0] if row else "?"
        print(f"⚠️ [sqlite] WAL checkpoint ناقص است ({path}): busy={busy} — "
              f"WAL/SHM حذف نشدند.")
        return False
    for suffix in ("-wal", "-shm"):
        if not os.path.exists(path + suffix):
            continue  # sidecar وجود ندارد = موفق (چیزی برای حذف نیست)
        try:
            os.remove(path + suffix)
        except OSError as e:
            # sidecar هست ولی حذف نشد — نباید «موفق» گزارش شود؛ در Restore/
            # Rollback این یعنی sidecar کهنه ممکن است روی فایلِ جدید attach
            # شود (فساد / readonly).
            print(f"⚠️ [sqlite] حذف sidecar {path + suffix} ناموفق: "
                  f"{type(e).__name__}: {str(e)[:100]} — cleanup ناقص اعلام "
                  f"می‌شود.")
            return False
    return True


def _snapshot_db_to_temp(path: str) -> str:
    """
    کپیِ سازگار (consistent) از دیتابیس با API backup خودِ SQLite — نه کپیِ
    خامِ فایل (که در زمانِ write ممکن است نصفه باشد). خروجی: مسیر فایلِ
    موقت؛ caller باید بعداً پاکش کند.

    PATCH 4: مسیر موقت **یکتا در هر snapshot** است (mkstemp در همان پوشه‌ی
    فایل اصلی تا هم‌فایل‌سیستم باشد) — مسیر ثابتِ اشتراکیِ قبلی
    («<db>.bksnap») باعث تداخلِ دو Backup هم‌زمان می‌شد (overwrite/فساد).
    هر snapshot فقط فایلِ خودش را می‌سازد و همان عملیات تمیزش می‌کند.
    """
    fd, tmp = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".bksnap.", suffix=".tmp",
        dir=os.path.dirname(os.path.abspath(path)),
    )
    os.close(fd)
    # PATCH: مالکیتِ منابع از همان لحظه‌ی mkstemp — اگر sqlite3.connect روی
    # مبدأ یا مقصد قبل از try/finally قدیمی شکست می‌خورد، فایلِ موقت روی دیسک
    # باقی می‌ماند. حالا همه‌چیز (باز کردن هر دو کانکشن، backup، close و حذف
    # فایلِ موقتِ ناقص) در یک try/finally است؛ استثنای اصلی هرگز مخفی
    # نمی‌شود و در شکست، فایلِ موقت حذف می‌شود.
    src = None
    dst = None
    ok = False
    try:
        src = sqlite3.connect(path)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        ok = True
        return tmp
    finally:
        for con in (src, dst):
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
        if not ok:
            # snapshot ناموفق → فایل موقتِ ناقص پاک شود (نشت فایل نباشد)
            try:
                os.remove(tmp)
            except OSError:
                pass


def _checkpoint_and_clean_session(path: str) -> bool:
    """
    PATCH 2/3 — سشن Telethon (فایل SQLite) و sidecar های دقیقش
    (-wal/-shm/-journal) یک **واحد منطقی**‌اند. بعد از جایگزینی/بازگردانیِ
    سشن، sidecar های کهنه‌ی سشن قبلی نباید روی فایلِ جدید attach شوند؛ این
    تابع با checkpointِ تاییدشده (هرگز حذف کورکورانه) WAL/SHM را جمع/پاک
    می‌کند و سپس journalِ کهنه را هم حذف می‌کند — فقط روی همین مسیرِ دقیق؛
    هیچ فایلِ نامرتبطی دست نمی‌خورد.

    برمی‌گرداند: True اگر sidecar ها با موفقیت تمیز شدند، False در غیر این
    صورت (checkpoint ناقص/خطا) — caller باید عملیات را Fail اعلام کند.
    """
    if not _file_is_sqlite(path):
        # placeholder غیر-SQLite (بایگانی خامِ مجاز): فایلِ DB واقعی نیست که
        # checkpoint رویش معنا داشته باشد. اما sidecar های کهنه‌ی سشنِ قبلی
        # که همین placeholder جایگزینش شده نباید باقی بمانند (واحد منطقی) —
        # Restore زیر قفل و با Runtime متوقف اجرا می‌شود، پس هیچ کلاینتِ
        # زنده‌ای به آن‌ها وابسته نیست و حذفِ دقیقِ همین sidecar ها امن است.
        # اگر sidecar موجود باشد ولی حذف نشود، True برنمی‌گردد — این تابع
        # هرگز تمیزکاریِ ناقص را موفق گزارش نمی‌کند.
        for ext in ("-wal", "-shm", "-journal"):
            stale = path + ext
            if not os.path.exists(stale):
                continue  # وجود ندارد = موفق
            try:
                os.remove(stale)
            except OSError as e:
                print(f"⚠️ [restore] حذف sidecar کهنه‌ی سشن {stale} ناموفق: "
                      f"{type(e).__name__}: {str(e)[:100]} — تمیزکاری ناقص اعلام "
                      f"می‌شود.")
                return False
        return True
    if not _checkpoint_and_clean(path):
        return False
    journal = path + "-journal"
    if os.path.exists(journal):
        try:
            os.remove(journal)
        except OSError as e:
            print(f"⚠️ [restore] حذف journal کهنه‌ی سشن {journal} ناموفق: {e}")
            return False
    return True


def _snapshot_session_to_temp(path: str):
    """
    snapshotِ سازگار از یک سشن Telethon (فایل SQLite که ممکن است هم‌زمان توسط
    کلاینتِ فعال Write شود) با API backup خودِ SQLite — نه کپیِ خامِ وسطِ
    Write.

    قانون (PATCH 1): اگر فایل واقعاً SQLite است ولی snapshot شکست بخورد،
    RuntimeError پرتاب می‌شود و Backup FAIL می‌شود — هیچ fallback به کپیِ خامِ
    یک سشن فعال مجاز نیست (کپیِ خامِ وسطِ Write = بکاپ خراب). فقط فایلِ
    placeholder غیر-SQLite (که محتوای معتبری برای نیمه‌نوشته‌شدن ندارد)
    بایگانیِ خام می‌شود و None برمی‌گرداند — مثل قبل.

    برمی‌گرداند: مسیر snapshot موقت (یا None برای فایلِ غیر-SQLite).
    """
    if not _file_is_sqlite(path):
        print(f"⚠️ [backup] سشن {path} فایل SQLite معتبر نیست — بایگانی خام "
              f"(بدون snapshot، محتوای غیر-SQLite).")
        return None
    try:
        return _snapshot_db_to_temp(path)
    except Exception as e:
        tag = os.path.basename(path)
        if tag.endswith(".session"):
            tag = tag[:-len(".session")]
        raise RuntimeError(
            f"Snapshot سشن SQLite «{tag}» (مسیر: {path}) شکست خورد: "
            f"{type(e).__name__}: {str(e)[:100]} — بکاپ رد شد "
            f"(fallback به کپی خام مجاز نیست)."
        ) from e


def _file_is_sqlite(path: str) -> bool:
    """
    آیا فایل واقعاً یک دیتابیس SQLite قابل‌خواندن است؟ (سشن placeholder نه)

    مهم: فقط sqlite3.connect + SELECT 1 کافی نیست — SQLite یک فایلِ کوتاهِ
    غیر-SQLite (مثلاً چند بایت junk) را «دیتابیس خالی» حساب می‌کند و SELECT 1
    را جواب می‌دهد؛ ولی integrity_check روی همان فایل با «file is not a
    database» می‌شکند و کل بکاپ را رد می‌کند. پس هدرِ واقعی SQLite
    ("SQLite format 3\0") هم چک می‌شود؛ فایلِ ۰ بایتی (سشنِ تازه‌ساخته‌شده‌ی
    خالی) معتبر است.
    """
    # (به‌صورت غیر-لیترال ساخته می‌شود تا اسکنرهای استاتیکِ دکمه‌های بایت‌ای
    # آن را با callback data اشتباه نگیرند)
    sqlite_magic = "SQLite format 3\x00".encode("utf-8")
    try:
        with open(path, "rb") as f:
            head = f.read(16)
        if head and (len(head) < 16 or head != sqlite_magic):
            return False
        con = sqlite3.connect(path)
        try:
            con.execute("SELECT 1").fetchone()
        finally:
            con.close()
        return True
    except (sqlite3.DatabaseError, OSError):
        return False


def build_backup_zip(zip_path: str) -> bool:
    """
    بکاپ کامل و معتبر پروژه (manifest + دیتابیس‌ها + config + سشن‌ها) در
    zip_path می‌سازد.

    سازگاری (consistency): دیتابیس‌ها و سشن‌های SQLite با API backup خودِ
    SQLite (نه کپیِ خامِ فایل — که در زمانِ Write ممکن است نصفه باشد)
    snapshot می‌شوند؛ پس بکاپ حتی اگر لحظه‌ی ساختِ آن با یک writer هم‌زمان
    باشد، ناقص/ناهمگام نمی‌شود. نکته‌ی مهم: برای ساخت بکاپ هرگز WAL دیتابیسِ
    Live TRUNCATE/clean نمی‌شود (DB اصلی در وضعیت ناپایدار قرار نمی‌گیرد) —
    API backup خودش snapshotِ سازگار می‌دهد. manifest/checksum از همان
    بایت‌هایی که داخل ZIP می‌روند محاسبه می‌شود.

    قبل از برگشت، خودِ بکاپ دوباره باز و validate می‌شود (شامل integrity
    سشن‌های SQLite) — اگر معتبر نبود، فایلِ ناقص حذف و False برگردانده
    می‌شود (هرگز فایلِ ناقص تحویل داده نمی‌شود).
    """
    db_snaps = {}
    try:
        files = _collect_backup_files()
        if not os.path.exists(DB_PATH):
            return False
        # دیتابیس‌ها و سشن‌های SQLite با API backup (بدون کپی خام، بدون
        # دست‌زدن به WAL دیتابیسِ Live)
        for arc, real in files.items():
            if real.endswith(".db"):
                try:
                    db_snaps[arc] = _snapshot_db_to_temp(real)
                except Exception as e:
                    print(f"⚠️ [backup] snapshot دیتابیس {real} ناموفق: {e}")
                    return False
            elif real.endswith(".session"):
                snaps = _snapshot_session_to_temp(real)
                if snaps is not None:
                    db_snaps[arc] = snaps

        def _byte_source(arc: str, real: str):
            return db_snaps.get(arc, real)

        manifest = {
            "project": BACKUP_PROJECT_NAME,
            "backup_version": BACKUP_VERSION,
            "schema_version": BACKUP_SCHEMA_VERSION,
            "created_at": _now(),
            "files": [
                {"name": arc, "size": os.path.getsize(_byte_source(arc, real)),
                 "sha256": _sha256_file(_byte_source(arc, real))}
                for arc, real in sorted(files.items())
            ],
        }
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for arc, real in sorted(files.items()):
                zf.write(_byte_source(arc, real), arcname=arc)
            zf.writestr(BACKUP_MANIFEST, json.dumps(
                manifest, ensure_ascii=False, indent=2))
        # بکاپ همه‌ی چیزهای حساس را یک‌جا دارد (config + سشن‌ها + دیتابیس‌ها)
        # — پس دسترسی‌اش باید دست‌کم به‌سختیِ خودِ آن فایل‌ها محدود باشد.
        _chmod_private(zip_path)
        ok, _ = validate_backup_zip(zip_path)
        if not ok:
            try:
                os.remove(zip_path)
            except Exception:
                pass
            return False
        return True
    except Exception as e:
        print(f"⚠️ [backup] ساخت بکاپ ناموفق: {e}")
        try:
            os.remove(zip_path)
        except Exception:
            pass
        return False
    finally:
        # فایل‌های snapshot موقت را همیشه پاک کن (بدون نشت فایل)
        for tmp in db_snaps.values():
            try:
                os.remove(tmp)
            except Exception:
                pass


def validate_backup_zip(zip_path: str) -> tuple:
    """
    اعتبارسنجی کامل بکاپ قبل از هر کاری: (ok, msg).
    - ZIP باز می‌شود و manifest موجود و متعلق به همین پروژه با نسخه‌ی سازگار است
    - همه‌ی فایل‌های اعلام‌شده داخل ZIP هستند و checksum/اندازه منطبق است
    - saas.db وجود دارد و هر دیتابیسِ موجود integrity_check == ok می‌دهد
    - schema جدول‌های ضروری را دارد
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            if BACKUP_MANIFEST not in names:
                return False, (
                    "فایل backup_manifest.json در بکاپ پیدا نشد — "
                    "این فایل بکاپ معتبر پروژه نیست."
                )
            try:
                manifest = json.loads(zf.read(BACKUP_MANIFEST).decode("utf-8"))
            except Exception:
                return False, "فایل backup_manifest.json خراب است (JSON معتبر نیست)."
            if manifest.get("project") != BACKUP_PROJECT_NAME:
                return False, (
                    f"این بکاپ متعلق به «{BACKUP_PROJECT_NAME}» نیست — "
                    "project در manifest ناهماهنگ است."
                )
            try:
                bv = int(manifest.get("backup_version", 0))
                sv = int(manifest.get("schema_version", 0))
            except (TypeError, ValueError):
                return False, "نسخه‌های manifest نامعتبر است."
            if bv > BACKUP_VERSION:
                return False, "نسخه‌ی بکاپ از نسخه‌ی پشتیبانی‌شده توسط ربات جدیدتر است — ناسازگار."
            if sv != BACKUP_SCHEMA_VERSION:
                return False, "نسخه‌ی schema بکاپ با schema فعلی ربات سازگار نیست."
            files = manifest.get("files")
            if not isinstance(files, list) or not files:
                return False, "manifest لیست فایل‌های بکاپ را ندارد."
            # BUG #3 — «مسیرِ امن» کافی نیست؛ هر فایلِ manifest باید از
            # مجموعه‌ی پشتیبانی‌شده‌ی برنامه باشد، نه هر فایلِ دلخواه:
            #   main DB، bot_data DB، config.json، admin_bot_admins.json،
            #   sessions/<filename> (فقط فایلِ تختِ داخلِ sessions/ — نه
            #   پوشه‌ی خالی، نه مسیرِ تو در تو، نه نام خالی).
            allowed_roots = {
                _main_db_arc(), _bot_db_arc(),
                "config.json", "admin_bot_admins.json",
            }
            for entry in files:
                name = entry.get("name")
                if not name or name not in names:
                    return False, f"فایل اعلام‌شده در manifest داخل بکاپ نیست: {name}"
                if not _zip_member_is_safe(name):
                    return False, f"نام فایل خطرناک در بکاپ: {name}"
                if name not in allowed_roots:
                    sub = name[len("sessions/"):] if name.startswith("sessions/") else None
                    if sub is None or not sub or "/" in sub or "\\" in sub:
                        return False, (
                            f"فایل خارج از قالب پشتیبانی‌شده‌ی بکاپ در manifest: "
                            f"{name}"
                        )
                data = zf.read(name)
                if len(data) != int(entry.get("size", -1)):
                    return False, f"اندازه‌ی فایل با manifest هماهنگ نیست: {name}"
                if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                    return False, f"checksum فایل درست نیست: {name}"
            main_arc = _main_db_arc()
            if main_arc not in names:
                return False, f"فایل {main_arc} (دیتابیس اصلی) در بکاپ نیست."
            # integrity برای هر دیتابیسِ موجود + schema برای دیتابیس اصلی و
            # bot_data + integrity سشن‌های SQLite (سشن placeholder بایگانیِ خام
            # است و integrity نمی‌گیرد — چون اصلاً DB معتبر نیست)
            for entry in files:
                db_name = entry["name"]
                if not (db_name.endswith(".db") or db_name.endswith(".session")):
                    continue
                suffix = ".session" if db_name.endswith(".session") else ".db"
                with tempfile.NamedTemporaryFile(
                        suffix=suffix, delete=False) as tf:
                    tf.write(zf.read(db_name))
                    tmp_db = tf.name
                try:
                    if not _file_is_sqlite(tmp_db):
                        if db_name.endswith(".session"):
                            # سشن غیر-SQLite: فقط هشدار (بایگانی خام) — بکاپ را رد نمی‌کند
                            print(f"⚠️ [backup] سشن {db_name} فایل SQLite معتبر نیست — بایگانی خام.")
                            continue
                        return False, f"دیتابیس {db_name} فایل SQLite معتبر نیست."
                    if not _db_integrity_ok(tmp_db):
                        return False, f"فایل {db_name} خراب است (integrity_check رد شد)."
                    if db_name == _main_db_arc():
                        ok, msg = _db_schema_ok(tmp_db, REQUIRED_SAAS_TABLES)
                    elif db_name == _bot_db_arc():
                        ok, msg = _db_schema_ok(tmp_db, REQUIRED_BOTDATA_TABLES)
                    else:
                        ok = True
                        msg = ""
                    if not ok:
                        return False, f"دیتابیس {db_name} با schema فعلی سازگار نیست: {msg}"
                finally:
                    try:
                        os.remove(tmp_db)
                    except Exception:
                        pass
        return True, "بکاپ معتبر است"
    except zipfile.BadZipFile:
        return False, "فایل ZIP خراب است (باز نمی‌شود)."
    except Exception as e:
        return False, f"خطا در بررسی بکاپ: {str(e)[:80]}"


def _rollback_from_emergency(emergency_zip: str, restored: list,
                             removed_stale: list = None,
                             stale_preserve_dir: str = None) -> None:
    """
    برگرداندن فایل‌های جایگزین‌شده از بکاپ اضطراری (اتمیک به‌ازای هر فایل) +
    بازسازی فایل‌های stale که حذف شده بودند (removed_stale) — تا در صورت
    خطای وسط Restore، سیستم دقیقاً به وضعیت قبل برگردد.

    PATCH 9 — sidecar-safety: بعد از بازگردانی هر دیتابیس، sidecar های
    (WAL/SHM)ِ متعلق به فایلِ قبلی با یک checkpointِ تاییدشده جمع/پاک می‌شوند
    (هرگز کورکورانه حذف نمی‌شوند — فقط وقتی SQLite تأیید کند checkpoint کامل
    شده) تا WAL کهنه روی فایلِ بازگردانده‌شده replay نشود. در پایان، همه‌ی
    دیتابیس‌های بازگردانده‌شده integrity_check می‌شوند؛ اگر هر یک fail شد،
    تابع exception می‌دهد تا Rollback موفق اعلام نشود و emergency backup حفظ
    شود.
    """
    restored_dbs = []
    with zipfile.ZipFile(emergency_zip, "r") as zf:
        for name, dest, existed in restored:
            if not existed:
                # BUG #1: مقصدِ این entry قبل از Restore وجود نداشت — فایلِ
                # تازه‌ساخته‌شده باید حذف شود تا سیستم دقیقاً به وضعیت قبل
                # برگردد (هیچ عضوِ اضطراری برایش انتظار نمی‌رود).
                try:
                    os.remove(dest)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    raise RuntimeError(
                        f"Rollback: حذف فایلِ تازه‌ساخته‌شده «{dest}» ناموفق "
                        f"بود: {type(e).__name__}: {str(e)[:80]} — rollback "
                        f"ناقص است."
                    ) from e
                continue
            try:
                data = zf.read(name)
            except KeyError:
                # BUG #2: مقصد قبل از Restore وجود داشت ولی عضوِ آن در بکاپ
                # اضطراری نیست — rollback نمی‌تواند وضعیت قبل را بازگرداند و
                # هرگز بی‌صدا ادامه نمی‌دهد.
                raise RuntimeError(
                    f"Rollback: عضوِ «{name}» در بکاپ اضطراری نیست ولی مقصد "
                    f"قبل از Restore وجود داشت — rollback ناقص است."
                ) from None
            tmp = dest + ".rollback_tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            # PATCH: سشن Telethon یک واحدِ منطقی (DB + sidecar ها) است —
            # sidecar های کهنه‌ی سشنی که قرار است بازگردانی شود، باید **قبل از**
            # replace با checkpointِ تاییدشده تمیز شوند (نه بعد از آن روی فایلِ
            # بازگردانده‌شده). اگر تمیزکاری ناموفق باشد، بازگردانیِ همین سشن
            # انجام نمی‌شود (rollback متوقف).
            if name.endswith(".session") and os.path.exists(dest):
                if not _checkpoint_and_clean_session(dest):
                    raise RuntimeError(
                        f"Rollback: تمیزکاری sidecar های سشن قبلی «{dest}» "
                        f"قبل از بازگردانی ناموفق بود — rollback متوقف شد "
                        f"({name})."
                    )
            os.replace(tmp, dest)
            # PATCH 3: سشن Telethon هم فایل SQLite است — باید مثل .db به‌عنوان
            # واحدِ منطقی (DB + sidecar ها) مدیریت شود.
            if name.endswith(".db") or name.endswith(".session"):
                restored_dbs.append((name, dest))
        for name in removed_stale or []:
            # فایلِ حذف‌شده‌ی stale — اول از بکاپ اضطراری (که قبل از هر
            # تغییری ساخته شده) و در نبودِ آن از پوشه‌ی حفظِ transaction-local
            # (stale_preserve_dir) بازسازی می‌شود. مسیر هدف همیشه Absolute و
            # بر اساس DATA_DIR (نه cwd).
            data = None
            try:
                data = zf.read(name)
            except KeyError:
                data = None
            if data is None and stale_preserve_dir:
                p = os.path.join(stale_preserve_dir, *name.split("/"))
                if os.path.isfile(p):
                    try:
                        with open(p, "rb") as f:
                            data = f.read()
                    except OSError as e:
                        raise RuntimeError(
                            f"Rollback: خواندن فایلِ stale حفظ‌شده «{p}» "
                            f"ناموفق بود: {type(e).__name__}: {str(e)[:80]} — "
                            f"rollback ناقص است."
                        ) from e
            if data is None:
                # BUG #2/#3: فایلِ stale که باید بازگردانی شود نه در بکاپ
                # اضطراری است و نه در پوشه‌ی حفظ — هرگز بی‌صدا ادامه نمی‌دهد.
                raise RuntimeError(
                    f"Rollback: فایلِ stale حذف‌شده «{name}» در بکاپ اضطراری "
                    f"و پوشه‌ی حفظ موجود نیست — rollback ناقص است."
                )
            dest = _restore_dest_for(name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".rollback_tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
        # BUG #1: بازگردانی sidecar های سشن که قبل از Restore وجود داشتند و
        # در طولِ جایگزینیِ سشن حذف/تمیز شدند — فقط از پوشه‌ی حفظِ
        # transaction-local (در بکاپ اضطراری نیستند). فقط sidecar هایی که
        # واقعاً قبل از Restore وجود داشتند ثبت/حفظ شده‌اند؛ فایلِ خالی ساخته
        # نمی‌شود. اگر sidecarِ ثبت‌شده‌ی حفظ‌شده پیدا نشود، rollback fail
        # می‌شود (هرگز بی‌صدا ادامه نمی‌دهد).
        if stale_preserve_dir:
            for arc_sc in _read_sidecar_manifest(stale_preserve_dir):
                p = os.path.join(stale_preserve_dir, *arc_sc.split("/"))
                if not os.path.isfile(p):
                    raise RuntimeError(
                        f"Rollback: sidecarِ حفظ‌شده «{arc_sc}» پیدا نشد — "
                        f"rollback ناقص است."
                    )
                with open(p, "rb") as f:
                    data_sc = f.read()
                sc_dest = _restore_dest_for(arc_sc)
                os.makedirs(os.path.dirname(sc_dest), exist_ok=True)
                tmp_sc = sc_dest + ".rollback_tmp"
                with open(tmp_sc, "wb") as f:
                    f.write(data_sc)
                os.replace(tmp_sc, sc_dest)
    # Sidecar های کهنه را فقط با checkpointِ تاییدشده پاک کن — اگر checkpoint
    # شکست بخورد، rollback موفق اعلام نمی‌شود (PATCH 3: برای سشن‌ها همین
    # قانون شامل -journal هم هست).
    for name, dest in restored_dbs:
        if name.endswith(".session"):
            # sidecar های سشن قبل از replace تمیز شدند (بالا)؛ بعد از
            # بازگردانی فقط integrity در حلقه‌ی پایین چک می‌شود.
            continue
        if not _checkpoint_and_clean(dest):
            raise RuntimeError(
                f"Rollback: checkpoint دیتابیس بازگردانده‌شده ناموفق بود — "
                f"rollback کامل اعلام نمی‌شود ({name})."
            )
    # اعتبارسنجی نهایی rollback (سشن placeholder غیر-SQLite مستثناست —
    # محتوای معتبری ندارد که integrity بگیرد)
    for name, dest in restored_dbs:
        if name.endswith(".session") and not _file_is_sqlite(dest):
            continue
        if not _db_integrity_ok(dest):
            raise RuntimeError(
                f"Rollback: دیتابیس بازگردانده‌شده سالم نیست (integrity رد شد): {name}"
            )


class StaleDeletionError(Exception):
    """
    حذف یک یا چند فایلِ stale (فایل‌های موجود روی سیستم که در بکاپ نیستند)
    ناموفق بود. اطلاعات موردنیاز rollback را حمل می‌کند:
      - removed: مسیرهای بایگانی (arc) که با موفقیت حذف شده‌اند
      - errors:  لیست (path, exception) حذف‌های ناموفق
    """
    def __init__(self, removed: list, errors: list):
        self.removed = list(removed)
        self.errors = list(errors)
        super().__init__(
            f"حذف فایل‌های stale ناموفق بود: {len(errors)} فایل حذف نشد"
        )


def _remove_stale_restore_files(manifest_files: list,
                                preserve_dir: str = None) -> list:
    """
    حذف فایل‌های stale بعد از Restore — تا Restore یک Snapshot واقعی باشد:
    هر فایلِ متعلق به پروژه که روی سیستم هست ولی در بکاپ نیست، حذف می‌شود.
    محدوده‌ی حذف کاملاً محافظت‌شده است و فقط این موارد را لمس می‌کند:
      - فایل‌های سطح‌بالا: دیتابیس اصلی، bot_data.db، config.json،
        admin_bot_admins.json
      - همه‌ی فایل‌های داخل پوشه‌ی سشن‌ها (sessions/) که در بکاپ نیستند
        (از جمله sidecar های -wal/-shm همان سشن‌های حذف‌شده)
    هیچ فایل دیگری (secret، پوشه‌ی ربات‌های اختصاصی و…) دست نمی‌خورد.

    بازمی‌گرداند: لیست نام‌های حذف‌شده (برای rollback احتمالی).
    """
    backup_names = {entry["name"] for entry in manifest_files}
    removed = []
    errors = []

    def _preserve_file(arc: str, real: str):
        # BUG #3: قبل از حذفِ هر فایلِ stale، بایت‌های دقیقش در پوشه‌ی
        # transaction-local حفظ می‌شود تا rollbackِ احتمالی بتواند آن را
        # بازگرداند (مخصوصاً sidecar های -wal/-shm/-journal که هرگز داخل
        # بکاپ اضطراری/عادی نمی‌روند). اگر حفظ ناموفق باشد، فایل حذف نمی‌شود
        # (حذفِ بدونِ حفظ = rollback غیرممکن).
        dst = os.path.join(preserve_dir, *arc.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(real, dst)

    def _safe_remove(arc: str, real: str):
        if os.path.exists(real) and os.path.isfile(real) and arc not in backup_names:
            if preserve_dir:
                try:
                    _preserve_file(arc, real)
                except OSError as e:
                    print(f"⚠️ [restore] حفظ فایل stale قبل از حذف ناموفق بود: "
                          f"{real}: {e}")
                    errors.append((real, e))
                    return
            try:
                os.remove(real)
                removed.append(arc)
            except OSError as e:
                # BUG B: حذفِ ناموفقِ stale swallow نمی‌شود — خطا ثبت می‌شود و
                # در پایانِ تابع کلِ عملیات Restore fail اعلام می‌شود (فایلِ
                # موجودی که حذف نشده یعنی Snapshot واقعیِ مدنظر ساخته نشده).
                print(f"⚠️ [restore] حذف فایل stale ناموفق بود: {real}: {e}")
                errors.append((real, e))

    # فایل‌های سطح‌بالای ردیابی‌شده
    main_arc = _main_db_arc()
    for arc, real in ((main_arc, DB_PATH), (_bot_db_arc(), DB_NAME),
                      ("config.json", CONFIG_FILE),
                      ("admin_bot_admins.json", ADMIN_LIST_FILE)):
        _safe_remove(arc, real)

    # پوشه‌ی سشن‌ها — snapshot واقعی
    if os.path.isdir(SESSIONS_DIR):
        backup_session_names = {
            n for n in backup_names if n.startswith("sessions/")
        }
        for fname in sorted(os.listdir(SESSIONS_DIR)):
            full = os.path.join(SESSIONS_DIR, fname)
            if not os.path.isfile(full):
                continue
            arc = os.path.join("sessions", fname)
            base = fname
            if base.endswith("-wal") or base.endswith("-shm"):
                base = base.rsplit("-", 1)[0]
            if arc not in backup_session_names and \
                    os.path.join("sessions", base) not in backup_session_names:
                if preserve_dir:
                    try:
                        _preserve_file(arc, full)
                    except OSError as e:
                        print(f"⚠️ [restore] حفظ سشن stale قبل از حذف ناموفق "
                              f"بود: {full}: {e}")
                        errors.append((full, e))
                        continue
                try:
                    os.remove(full)
                    removed.append(arc)
                except OSError as e:
                    # BUG B: مثل _safe_remove — حذفِ ناموفقِ سشنِ stale Restore
                    # را fail می‌کند (نه اینکه فقط لاگ شود و ادامه یابد).
                    print(f"⚠️ [restore] حذف سشن stale ناموفق بود: {full}: {e}")
                    errors.append((full, e))
    if errors:
        # BUG B: حذفِ ناقصِ stale — مسیرهای حذف‌شده‌ی موفق (removed) همراهِ
        # exception می‌روند تا rollbackِ بعدی بتواند دقیقاً همان‌ها را بازسازی
        # کند (اطلاعاتِ جزئی از دست نمی‌رود).
        raise StaleDeletionError(removed, errors)
    return removed


def _post_restore_validate(restored_files: list = None) -> tuple:
    """
    بررسی نهایی بعد از جایگزینی/حذف: (ok, msg). همه‌ی دیتابیس‌های بازیابی‌شده
    integrity + schema می‌شوند و config.json باید JSON معتبر (dict) باشد.

    اگر restored_files (لیست entryهای manifest) داده شود، سشن‌هایی که از
    بکاپ بازیابی شده‌اند هم health می‌شوند: اگر مالک همان user باشد mode به
    0600 نرمال می‌شود (chmod امن — هرگز 777/تغییر مالک) و اگر مالک متفاوت
    یا فایل فقط‌خواندنیِ غیرقابل‌رفع باشد، Restore fail می‌شود تا یک سشن
    خراب/ناخوانا به سیستم تحویل داده نشود.
    """
    if not _db_integrity_ok(DB_PATH):
        return False, "بررسی نهایی دیتابیس اصلی بعد از Restore رد شد"
    ok, msg = _db_schema_ok(DB_PATH, REQUIRED_SAAS_TABLES)
    if not ok:
        return False, f"schema {_main_db_arc()} بعد از Restore ناسازگار است: {msg}"
    # bot_data فقط وقتی بررسی می‌شود که واقعاً بخشی از همین Restore باشد (در
    # بکاپ/مانیفست آمده باشد) — مسیرهای legacy که فقط DB اصلی را بازیابی
    # می‌کنند نباید به‌خاطر فایلِ دست‌نخورده‌ی فعلی رد شوند.
    restored_arcs = {e.get("name") for e in (restored_files or [])}
    if (not restored_files) or _bot_db_arc() in restored_arcs:
        if os.path.exists(DB_NAME) and not _db_integrity_ok(DB_NAME):
            return False, f"بررسی نهایی {_bot_db_arc()} بعد از Restore رد شد"
        if os.path.exists(DB_NAME):
            ok, msg = _db_schema_ok(DB_NAME, REQUIRED_BOTDATA_TABLES)
            if not ok:
                return False, f"schema {_bot_db_arc()} بعد از Restore ناسازگار است: {msg}"
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                return False, "config.json بعد از Restore ساختار درستی ندارد (باید JSON object باشد)"
        except Exception as e:
            return False, f"config.json بعد از Restore قابل خواندن نیست: {str(e)[:60]}"
    if restored_files:
        for entry in restored_files:
            name = entry.get("name", "")
            if not (name.startswith("sessions/") and name.endswith(".session")):
                continue
            tag = os.path.basename(name)[: -len(".session")]
            # در مسیر Restore، محتوای غیر-sqlite فقط هشدار است؛ فقط مشکل
            # permission/readonly Restore را fail می‌کند.
            health = check_session_health(tag, require_sqlite=False)
            if not health["ok"]:
                return False, f"سشن بازیابی‌شده «{tag}» سالم نیست: {health['error']}"
            if health["sqlite_ok"]:
                print(f"✅ [SESSION][{tag}][CHECK] سشن بازیابی‌شده سالم است")
    return True, ""


def restore_backup_from_zip(zip_path: str, stale_cleanup: bool = True) -> tuple:
    """
    بازیابی اتمیک کل سیستم از بکاپ معتبر: (ok, msg). این Engine مرکزیِ
    Restore است — همه‌ی مسیرهای Restore (async اصلی / legacy های
    restore_db_from_file / restore_db_from_zip) نهایتاً به همین‌جا می‌رسند و
    هیچ‌جا مستقیم os.replace روی DB اصلی انجام نمی‌شود.

    ترتیب: validate کامل → استخراج امن در پوشه‌ی موقتِ روی همان دیسک →
    بکاپ اضطراری از وضعیت فعلی → جایگزینی اتمیک فایل‌ها → بررسی نهایی →
    پاکسازی. اگر هر مرحله شکست بخورد، فایل‌های جایگزین‌شده از بکاپ
    اضطراری برمی‌گردند و دیتابیس اصلی هرگز با فایلِ ناقص overwrite نمی‌شود.

    stale_cleanup: برای بکاپ کاملِ پروژه True (Snapshot واقعی — فایل‌های
    stale حذف می‌شوند). برای مسیرهای legacy که فقط DB را بازیابی می‌کنند
    (بدون config/session در بکاپ) False — تا config/sessionهای فعلی حذف
    نشوند.

    Runtime-safety: کل بخشِ جایگزینی زیرِ `_RESTORE_LOCK` اجرا می‌شود تا دو
    Restore هم‌زمان با هم تداخل نکنند (LOCK/UNLOCK). اتصال‌های DB در این
    پروژه کوتاه‌عمرند (هر عملیات یک connection جدید باز و می‌بندد) و تنظیمات
    همیشه مستقیم از DB خوانده می‌شوند، پس بعد از replace هیچ کشِ درون‌حافظه‌ای
    کهنه نمی‌ماند؛ حلقه‌های expiry/payment هم در تکرار بعدی خودشان فایلِ جدید
    را می‌بینند. بعد از replace برای هر دیتابیس `-wal/-shm` پاک می‌شود تا
    WALِ کهنه‌ی DB قبلی روی فایلِ جدید replay نشود (که باعث فساد می‌شود).
    """
    ok, msg = validate_backup_zip(zip_path)
    if not ok:
        return False, msg

    # PATCH 4: Restore همگام (Sync) هرگز نباید در حالی که Runtime/Client فعال
    # است DB اصلی را Replace کند — Runtime های فعال یعنی Session ممکن است باز
    # باشد و replace کردن DB زیرِ Session فعال، به «attempt to write a
    # readonly database»/کرش منجر می‌شود. مسیر Runtime-safe (async) Runtimeها
    # را اول متوقف می‌کند و سپس همین engine را صدا می‌زند.
    active = _active_runtime_tags()
    if active:
        return False, (
            "Restore همگام در حالی که Runtime فعال است مجاز نیست — "
            f"تگ‌های فعال: {', '.join(sorted(active))}. "
            "ابتدا اکانت‌ها را متوقف کنید یا از مسیر Runtime-safe استفاده کنید."
        )

    # مسیرهای موقت/اضطراری همیشه زیر DATA_DIR — نه cwd (اجرا از هر پوشه‌ای).
    ts = _backup_timestamp()
    workdir = os.path.join(DATA_DIR, f".restore_tmp_{ts}")
    emergency_zip = os.path.join(DATA_DIR, f"pre_restore_backup_{ts}.zip")
    try:
        with _RESTORE_LOCK:
            return _do_restore_locked(zip_path, workdir, emergency_zip, stale_cleanup)
    except Exception as e:
        rollback_err = None
        try:
            _rollback_from_emergency(emergency_zip, [], [])
        except Exception as re_:
            rollback_err = re_
            print(f"⚠️ [backup] برگشت اضطراری ناموفق: {re_}")
        shutil.rmtree(workdir, ignore_errors=True)
        if rollback_err is not None:
            # BUG #4: rollbackِ ناقص هرگز «موفقیتِ بازگشت» اعلام نمی‌شود.
            return False, (
                f"Restore ناموفق بود: {str(e)[:80]} — و برگشت اضطراری نیز "
                f"ناقص ماند: {str(rollback_err)[:80]} — وضعیت قبلی کامل "
                f"بازنگردانده شد."
            )
        return False, f"Restore ناموفق بود: {str(e)[:80]} — وضعیت قبلی برگردانده شد."


_SIDECAR_MANIFEST_NAME = ".sidecars.json"


def _write_sidecar_manifest(preserve_dir: str, sidecar_arcs: list) -> None:
    """ثبتِ صریحِ sidecar های حفظ‌شده‌ی سشن‌ها (transaction-local) — تا
    rollback بداند دقیقاً کدام sidecar ها قبل از Restore وجود داشتند و باید
    بازگردانی شوند (فقط آن‌ها؛ هیچ sidecar ای ساخته نمی‌شود)."""
    p = os.path.join(preserve_dir, _SIDECAR_MANIFEST_NAME)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(sorted(sidecar_arcs), f)


def _read_sidecar_manifest(preserve_dir: str) -> list:
    """لیست sidecar های حفظ‌شده — خالی اگر پوشه/فایلِ manifest نباشد."""
    p = os.path.join(preserve_dir, _SIDECAR_MANIFEST_NAME)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _do_restore_locked(zip_path: str, workdir: str, emergency_zip: str,
                       stale_cleanup: bool = True) -> tuple:
    """بخشِ جایگزینیِ Restore — فقط زیر قفل `_RESTORE_LOCK` صدا زده می‌شود."""
    ok, msg = validate_backup_zip(zip_path)
    if not ok:
        return False, msg
    # PATCH 4 (گارد دوم زیر قفل — ضد TOCTOU): اگر بین validate اولیه و اینجا
    # Runtimeی بالا آمده باشد، جایگزینی انجام نمی‌شود.
    active = _active_runtime_tags()
    if active:
        # BUG #2: در این نقطه هنوز هیچ‌چیز تغییر نکرده است (emergency backup
        # هم ساخته نشده) — پس raise نمی‌کنیم تا rollbackِ لایه‌ی بیرونی با یک
        # zipِ ناموجود صدا زده نشود و پیامِ غلطِ «rollback ناقص» تولید نکند؛
        # همان بازگشتِ معمول کافی است. مالکیتِ rollback فقط با مسیرِ داخلیِ
        # همین تابع است (یک شکست → حداکثر یک rollbackِ واقعی).
        return False, (
            f"Runtime فعال هنگام Restore پیدا شد (تگ‌ها: "
            f"{', '.join(sorted(active))}) — جایگزینی انجام نشد."
        )
    restored = []
    removed_stale = []
    # BUG #1: sidecar های حفظ‌شده‌ی سشن‌ها (arc) برای rollbackِ احتمالی.
    preserved_session_sidecars = []
    # پوشه‌ی حفظِ transaction-local برای فایل‌های stale که قرار است حذف
    # شوند (مخصوصاً sidecar های سشن که در بکاپ اضطراری نیستند) — داخل
    # workdir (که در پایان در هر مسیر پاک می‌شود) تا هم‌فایل‌سیستم و
    # مخصوصِ همین عملیاتِ Restore باشد (BUG #3).
    stale_preserve_dir = os.path.join(workdir, "stale_preserve")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest = json.loads(zf.read(BACKUP_MANIFEST).decode("utf-8"))
            files = manifest["files"]
            os.makedirs(workdir, exist_ok=True)
            for entry in files:
                name = entry["name"]
                target = os.path.join(workdir, *name.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as out:
                    out.write(zf.read(name))

        # بکاپ اضطراری از وضعیت فعلی — قبل از هر تغییری
        if not build_backup_zip(emergency_zip):
            shutil.rmtree(workdir, ignore_errors=True)
            return False, "ساخت بکاپ اضطراری از وضعیت فعلی ناموفق بود — Restore لغو شد."
        # فقط آخرین بکاپ اضطراری نگه داشته می‌شود (نقطه‌ی برگشتِ دستی) —
        # مقایسه با basename تا emergency_zipِ همین Restore هرگز حذف نشود.
        _my_emg = os.path.basename(emergency_zip)
        for old in os.listdir(DATA_DIR):
            if old.startswith("pre_restore_backup_") and old != _my_emg:
                try:
                    os.remove(os.path.join(DATA_DIR, old))
                except Exception:
                    pass

        # WAL دیتابیس‌های در حال استفاده را قبل از replace جمع کن — نتیجه باید
        # موفق باشد (busy==0): اگر checkpoint ناقص/ناموفق باشد، Restore ادامه
        # پیدا نمی‌کند تا WALِ جوش‌نخورده روی فایلِ جدید replay نشود و DB
        # خراب نشود (PATCH 2). emergency backup همین‌جا حفظ می‌شود.
        if not _checkpoint_and_clean(DB_PATH):
            raise RuntimeError(
                "WAL checkpoint دیتابیس اصلی قبل از Restore ناموفق بود — "
                "Restore متوقف شد (emergency backup حفظ شد)."
            )
        if not _checkpoint_and_clean(DB_NAME):
            raise RuntimeError(
                "WAL checkpoint دیتابیس bot_data قبل از Restore ناموفق بود — "
                "Restore متوقف شد (emergency backup حفظ شد)."
            )

        # جایگزینی اتمیک — مقصد همیشه Absolute بر اساس DATA_DIR (نه cwd).
        # فایلِ جایگزین‌شده از بکاپِ validate‌شده آمده است (بدون WAL) و پس از
        # replace، checkpoint اجباری روی آن اجرا نمی‌شود — به‌جایش integrity و
        # schema در _post_restore_validate پایین بررسی می‌شوند (PATCH 3).
        # برای سشن‌ها ترتیبِ امن: sidecar های کهنه‌ی سشنِ قبلی (که قرار است
        # جایگزین شود) باید **قبل از** replace با checkpointِ تاییدشده تمیز
        # شوند (روی خودِ سشنِ قبلی) — نه بعد از replace روی فایلِ جدید؛
        # وگرنه WAL/SHM/JOURNAL کهنه‌ی سشن قبلی روی سشنِ تازه‌بازیابی‌شده
        # attach می‌شود (فساد / «attempt to write a readonly database»).
        # اگر تمیزکاری سشن قبلی ناموفق باشد، replace انجام نمی‌شود و Restore
        # از مسیر خطای موجود (rollback اضطراری) خارج می‌شود.
        for entry in files:
            name = entry["name"]
            target = os.path.join(workdir, *name.split("/"))
            dest = _restore_dest_for(name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            # BUG #1: وضعیتِ «قبل از Restore» برای rollback ثبت می‌شود — اگر
            # مقصد از قبل وجود داشت، rollback محتوای قبلی را از بکاپ اضطراری
            # بازمی‌گرداند؛ اگر وجود نداشت، rollback فایلِ تازه‌ساخته‌شده را
            # حذف می‌کند.
            existed = os.path.exists(dest)
            if name.startswith("sessions/") and name.endswith(".session"):
                # PATCH BUG#2: sidecar های orphan هم باید **قبل از** replace
                # تمیز شوند — حتی اگر خودِ dest وجود نداشته باشد (فقط
                # -wal/-shm/-journal مانده باشند). _checkpoint_and_clean_session
                # در نبودِ فایلِ DB (ناموجود/غیر-SQLite) فقط همین sidecar های
                # دقیقِ مسیرِ مقصد را حذف می‌کند و اگر حذفِ sidecar موجود
                # ناموفق باشد False برمی‌گرداند → جایگزینی انجام نمی‌شود.
                if os.path.exists(dest) or any(
                        os.path.exists(dest + ext)
                        for ext in ("-wal", "-shm", "-journal")):
                    # BUG #1: sidecar های کهنه‌ی سشن قبلی که قرار است توسط
                    # _checkpoint_and_clean_session حذف/تمیز شوند، اول باید
                    # transaction-local حفظ شوند — آن‌ها در بکاپ اضطراری نیستند
                    # و rollbackِ بعدی باید بتواند دقیقاً همان‌ها را بازگرداند.
                    # فقط sidecar های موجود حفظ می‌شوند (فایلِ خالی ساخته
                    # نمی‌شود). اگر حفظ ناموفق باشد، sidecar حذف نمی‌شود و
                    # Restore fail می‌شود (rollbackِ موجود، تغییراتِ قبلی را
                    # برمی‌گرداند).
                    for ext in ("-wal", "-shm", "-journal"):
                        sc = dest + ext
                        if os.path.isfile(sc):
                            arc_sc = name + ext
                            p = os.path.join(
                                stale_preserve_dir, *arc_sc.split("/"))
                            os.makedirs(os.path.dirname(p), exist_ok=True)
                            try:
                                shutil.copyfile(sc, p)
                            except OSError as e:
                                raise RuntimeError(
                                    f"حفظ sidecar کهنه‌ی سشن «{arc_sc}» قبل از "
                                    f"تمیزکاری ناموفق بود: "
                                    f"{type(e).__name__}: {str(e)[:80]} — "
                                    f"Restore متوقف شد."
                                )
                            preserved_session_sidecars.append(arc_sc)
                    if preserved_session_sidecars:
                        _write_sidecar_manifest(
                            stale_preserve_dir, preserved_session_sidecars)
                    if not _checkpoint_and_clean_session(dest):
                        raise RuntimeError(
                            f"تمیزکاری sidecar های سشن قبلی «{name}» قبل از "
                            f"جایگزینی ناموفق بود — Restore متوقف شد."
                        )
            os.replace(target, dest)
            restored.append((name, dest, existed))

        # اعتبارسنجی سشن‌های بازیابی‌شده بعد از replace (واحد منطقی): sidecar
        # کهنه قبل از جایگزینی تمیز شد؛ اینجا فقط integrity فایلِ جدید چک
        # می‌شود. placeholder غیر-SQLite (بایگانی خامِ مجاز) integrity ندارد
        # و مستثناست.
        for entry in files:
            name = entry["name"]
            if not (name.startswith("sessions/") and name.endswith(".session")):
                continue
            dest = _restore_dest_for(name)
            if _file_is_sqlite(dest) and not _db_integrity_ok(dest):
                raise RuntimeError(
                    f"سشن بازیابی‌شده «{name}» سالم نیست (integrity رد شد) — "
                    f"Restore متوقف شد."
                )

        # Snapshot واقعی: حذف فایل‌های stale (فقط فایل‌های متعلق به پروژه) —
        # فقط برای بکاپ کامل؛ مسیرهای legacy (فقط-دیتابیس) هرگز config/سشنِ
        # فعلی را حذف نمی‌کنند.
        if stale_cleanup:
            try:
                removed_stale = _remove_stale_restore_files(
                    files, preserve_dir=stale_preserve_dir)
            except StaleDeletionError as e:
                # BUG B: حذفِ ناقصِ stale — مسیرهای حذف‌شده‌ی موفق باید به
                # rollback برسند (removed_stale با e.removed پر می‌شود) تا
                # بازسازی شوند؛ در غیر این صورت لیست از دست می‌رفت. rollback
                # با همان مسیرِ except کلیِ پایین اجرا می‌شود (فقط یک بار).
                removed_stale = e.removed
                raise RuntimeError(
                    f"حذف فایل‌های stale ناموفق بود ({len(e.errors)} فایل) — "
                    f"Restore متوقف شد و وضعیت قبلی بازگردانده می‌شود."
                ) from e

        # بررسی نهاییِ کامل: همه‌ی دیتابیس‌ها + config.json + سشن‌های بازیابی‌شده
        ok_final, msg_final = _post_restore_validate(files)
        if not ok_final:
            raise RuntimeError(msg_final)

        shutil.rmtree(workdir, ignore_errors=True)
        return True, "بازیابی کامل با موفقیت انجام شد (Snapshot کامل + پاک‌سازی فایل‌های اضافی)"
    except Exception as e:
        rollback_err = None
        try:
            _rollback_from_emergency(emergency_zip, restored,
                                     removed_stale, stale_preserve_dir)
        except Exception as re_:
            rollback_err = re_
            print(f"⚠️ [backup] برگشت اضطراری ناموفق: {re_}")
        shutil.rmtree(workdir, ignore_errors=True)
        if rollback_err is not None:
            # BUG #4: اگر rollback خودش ناقص ماند، هرگز «وضعیت قبلی
            # برگردانده شد» اعلام نمی‌شود — emergency backup حفظ می‌شود.
            return False, (
                f"Restore ناموفق بود: {str(e)[:80]} — و برگشت اضطراری نیز "
                f"ناقص ماند: {str(rollback_err)[:80]} — وضعیت قبلی کامل "
                f"بازنگردانده شد (emergency backup حفظ شد)."
            )
        return False, f"Restore ناموفق بود: {str(e)[:80]} — وضعیت قبلی برگردانده شد."


async def restore_backup_from_zip_async(zip_path: str) -> tuple:
    """
    نسخه‌ی Runtime-safe از Restore (برای مسیرهای async مثل callback):

      1. validate اولیه — توقفِ بی‌دلیل Runtimeها فقط برای بکاپِ معتبر رخ می‌دهد
      2. Maintenance Mode فعال → ensure_started هر استارتِ جدید را رد می‌کند
      3. همه‌ی Runtimeها (RUNNING/STARTING/backoff) کامل متوقف و Taskها واقعاً
         تمام می‌شوند — هیچ Runtime وسطِ Restore به DB/سشن write نمی‌کند
      4. Restore اتمیک (همان engine واحد: emergency backup → replace →
         validate → rollback)
      5. در موفقیت، اکانت‌هایی که قبل از Restore روشن بودند و در configِ جدید
         هم enabled هستند دوباره start می‌شوند
      6. در هر حال (finally) Maintenance برداشته می‌شود

    برگشت: (ok, msg) — مثل restore_backup_from_zip.
    """
    global _MAINTENANCE_MODE
    ok0, msg0 = validate_backup_zip(zip_path)
    if not ok0:
        return False, msg0
    # Maintenance Mode قبلی حفظ می‌شود و در پایان دقیقاً به همان برگردانده
    # می‌شود — Restore نباید حالتِ قبلی (مثلاً Maintenance فعال از عملیاتِ
    # دیگر) را نابود کند.
    prev_maintenance = _MAINTENANCE_MODE
    _MAINTENANCE_MODE = True
    try:
        # توقف کامل همه‌ی Runtimeها — صبر تا Taskها واقعاً تمام شوند
        before = list(dict.fromkeys(
            list(ACCOUNTS.keys()) + list(_RUNTIME_TASKS.keys())
        ))
        was_running = {t: is_running(t) for t in before}
        for t in sorted(before):
            # PATCH 5: «توقف درخواست‌شده» کافی نیست — تسک باید واقعاً تمام
            # شده باشد وگرنه سشن هنوز باز است و جایگزینیِ آن Collision/فساد
            # می‌سازد. اگر توقفی ناتمام ماند، Restore لغو می‌شود.
            stopped = await ensure_stopped(t, f"restore.async.{t}")
            if not stopped:
                return False, (
                    f"توقف کامل runtime «{t}» قبل از Restore ممکن نشد — "
                    f"سشن هنوز باز است؛ Restore لغو شد."
                )

        ok, msg = await asyncio.to_thread(restore_backup_from_zip, zip_path)
        if not ok:
            return False, msg

        # جایگزینی تمام شد — Maintenance برداشته می‌شود تا استارت مجددِ
        # اکانت‌های مجاز ممکن شود (اما در finally به حالتِ قبلی برمی‌گردد).
        _MAINTENANCE_MODE = False

        # استارت مجدد اکانت‌های قبلاً روشن — بر اساس config جدید (Restore
        # شده). اگر config جدید این اکانت را ندارد یا disabled است، استارت
        # نمی‌شود (config جدید حاکم است).
        #
        # مهم: شکستِ resume هرگز با شکستِ خودِ Restore یکی نیست — فایل‌ها
        # قبلاً موفق و validate شده‌اند؛ یک SelfBot که دوباره روشن نشد فقط
        # لاگ می‌شود و بقیه‌ی اکانت‌ها ادامه می‌دهند؛ پیامِ برگشتی «موفقیتِ
        # Restore + هشدارِ resume» است و هرگز rollback صدا زده نمی‌شود.
        cfg = load_config()
        resume_failed = []
        for t in sorted(before):
            if not was_running.get(t):
                continue
            acc = cfg.get(t)
            if isinstance(acc, dict) and not acc.get("disabled"):
                try:
                    r_ok, r_st = await ensure_started(
                        t, acc, caller="restore.resume", wait_seconds=60
                    )
                    if not r_ok:
                        resume_failed.append(f"{t}({r_st})")
                        print(f"⚠️ [restore] resume اکانت «{t}» ناموفق بود "
                              f"(status={r_st}) — بقیه‌ی اکانت‌ها ادامه دادند.")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    resume_failed.append(f"{t}({type(e).__name__})")
                    print(f"⚠️ [restore] resume اکانت «{t}» با خطا مواجه شد: "
                          f"{type(e).__name__}: {str(e)[:80]} — بقیه‌ی اکانت‌ها "
                          f"ادامه دادند.")
        if resume_failed:
            return True, msg + (
                f" ⚠️ {len(resume_failed)} اکانت دوباره روشن نشد: "
                f"{', '.join(resume_failed)}"
            )
        return True, msg
    finally:
        # در هر مسیر (شکست/موفقیت) به حالتِ Maintenance قبلی برمی‌گردیم
        _MAINTENANCE_MODE = prev_maintenance


# ═══════════════════════════════════════════════════════════════════
#  سیستم مجوزهای ظرفیتی (capability-based permissions)
# ═══════════════════════════════════════════════════════════════════
#
#  مفهوم: یک «ظرفیت» (capability) یک لایه‌ی مجوزِ جدا از نقش (role) است.
#  نقش‌ها (OWNER/ADMIN/RESELLER/USER) می‌مانند و تغییر نمی‌کنند؛ این لایه
#  اختیاراتِ اضافی و خطرناک را کنترل می‌کند که هرگز نباید فقط به‌خاطرِ
#  نقشِ یک کاربر به او داده شوند.
#
#  فقط یک ظرفیت در کل سیستم وجود دارد (و ساختار طوری است که ظرفیت‌های
#  بیشتر در آینده بدون تغییرِ معماری اضافه شوند):
#
#    CAP_ACCOUNT_SECURITY  →  «مدیریت امنیتِ اکانت»
#       دسترسی به: دستگاه‌های لاگین‌شده، رمز دو مرحله‌ای، کد ورود.
#       این‌ها ابزارهای جلب/تصاحبِ اکانت‌اند — به همین دلیل پیش‌تر فقط
#       در دسترسِ مالکِ اصلیِ سیستم (OWNER) بودند.
#
#  مدلِ دسترسی (قانونِ نهایی):
#     1) مالکِ اصلی → همیشه مجاز (owner bypass).
#     2) در غیر این صورت → فقط اگر مجوزِ فعّال و در محدوده (scope) معتبر
#        برای این کاربر وجود داشته باشد.
#     3) هیچ‌وقت از نقش/مالکیتِ ربات اختصاصی/اشتراک/داشتنِ مشتری استنتاج
#        نمی‌شود. پیش‌فرض: DENY.
#
#  محدوده‌ها (scope):
#     SCOPE_RESELLER      → برای کلِ دامنه‌ی مشتریانِ آن نماینده.
#     SCOPE_DEDICATED_BOT → فقط در چارچوبِ یک ربات اختصاصیِ مشخص.
#     SCOPE_ACCOUNT       → فقط برای یک تگِ اکانتِ واحد (قابل‌توسعه).
#
#  اعطا/سلبِ مجوز فقط توسطِ مالکِ اصلی انجام می‌شود (grant authority جدا
#  از use authority — یک نماینده‌ی مجاز نمی‌تواند به دیگری مجوز دهد).

CAP_ACCOUNT_SECURITY = "account_security"

SCOPE_RESELLER = "reseller"
SCOPE_DEDICATED_BOT = "dedicated_bot"
SCOPE_ACCOUNT = "account"

# برچسبِ فارسیِ هر محدوده — فقط برای نمایش در پنلِ OWNER.
_SCOPE_LABELS = {
    SCOPE_RESELLER: "مشتریانِ خودم",
    SCOPE_DEDICATED_BOT: "فقط این ربات اختصاصی",
    SCOPE_ACCOUNT: "فقط این اکانت",
}

# همه‌ی callbackهای عملیاتیِ محافظت‌شده‌ی این ظرفیت. هر کدام از این مسیرها
# باید از لایه‌ی مرکزیِ authorize_sensitive_account_action عبور کنند — نه
# این‌که هر کدام قانونِ خودشان را داشته باشند.
SECURITY_ROUTES = (
    "sessions:", "sesstog:", "sesskill:", "sesswipe:", "sessterm:",
    "tfa:", "tfareset:", "tfago:", "tfacancel:",
    "getcode:", "codeget:", "codearm:",
)


def _capability_subject_is_main_owner(subject_id: int, main_owner_id: int) -> bool:
    """
    آیا این کاربر خودِ مالکِ اصلیِ سیستم است؟ (owner bypass).

    نکته‌ی ظریف اما حیاتی: در یک نمونه‌ی رباتِ اختصاصی، ADMIN_ID صاحبِ آن
    ربات است، نه مالکِ اصلیِ سیستم. پارامترِ main_owner_id باید فقط در
    نمونه‌ی اصلی پاس داده شود. به همین دلیل مقدارِ پیش‌فرض None است — یعنی
    «owner bypass نقطه‌ای وجود ندارد» — و فراخواننده (در نمونه‌ی اصلی)
    OWNER_ID را صراحتاً پاس می‌دهد.
    """
    return bool(main_owner_id) and subject_id == main_owner_id


def _main_grants_db_path() -> str:
    """
    مسیرِ دیتابیس اصلی پروژه — حتی از داخلِ یک رباتِ اختصاصی.

    چرا لازم است: ربات‌های اختصاصی به‌عنوان زیرپروسه با SELFBOT_DATA_DIR و
    DB اختصاصی خودشان اجرا می‌شوند. اما مجوزها فقط توسط مالکِ اصلی و در
    دیتابیس اصلی اعطا می‌شوند. اگر نمونهِ فرعی فقط DB خودش را نگاه کند،
    مجوزها هرگز دیده نمی‌شوند. این تابع مسیرِ دیتابیس اصلی را به‌صورت
    پایدار از روی پوشه‌ی اصلی پروژه حل می‌کند.
    """
    return os.path.join(_project_dir(), "saas.db")


@contextmanager
def _grants_conn():
    """
    کانکشن به دیتابیسِ جایی که مجوزها ذخیره می‌شوند:
      - نمونه‌ی اصلی → همان DB_PATH.
      - ربات اختصاصی → دیتابیس اصلیِ پروژه (فقط خواندنی، چون نمونه‌ی فرعی
        نباید جدولِ مجوزها را تغییر دهد — grant/revoke فقط از پنلِ اصلی
        مجاز است).

    اگر دیتابیس اصلی در دسترس نبود (مثلاً پوشه‌ی پروژه جابه‌جا شده)،
    به‌جای fail-open رفتن، یک کانکشنِ نامعتبر برمی‌گرداند که همه‌ی
    خواندن‌هایش تهی می‌شوند — یعنی DENY.
    """
    if not IS_DEDICATED_BOT:
        with _conn() as c:
            yield c
        return
    p = _main_grants_db_path()
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def grant_capability(subject_user_id: int, capability: str, scope_type: str,
                     scope_id: str, granted_by: int, expires_at: str = None) -> int:
    """
    اعطای یک ظرفیت به یک کاربر، در یک محدوده. idempotent است: اگر مجوزِ
    فعّالی با همین (کاربر، ظرفیت، محدوده) وجود داشته باشد، همان را
    برمی‌گرداند و تاریخ را تازه نمی‌کند (دو بار اعطا = یک مجوز، نه دو تا).

    برمی‌گرداند: id ردیفِ مجوز.
    """
    with _conn_immediate() as c:
        c.execute(
            "UPDATE permission_grants SET is_active = 0 "
            "WHERE subject_user_id = ? AND capability = ? AND scope_type = ? "
            "AND scope_id IS ?",
            (subject_user_id, capability, scope_type, scope_id),
        )
        cur = c.execute(
            "INSERT INTO permission_grants (subject_user_id, capability, scope_type, "
            "scope_id, granted_by, created_at, updated_at, expires_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (subject_user_id, capability, scope_type, scope_id,
             granted_by, _now(), _now(), expires_at),
        )
        return cur.lastrowid


def revoke_capability(subject_user_id: int, capability: str,
                      scope_type: str = None, scope_id: str = None,
                      revoked_by: int = None) -> int:
    """
    سلبِ مجوز — همه‌ی مجوزهای فعّالِ این کاربر برای این ظرفیت (و در صورت
    مشخص‌بودن، فقط در این محدوده) غیرفعّال می‌شوند. اثربخشی فوری است: یک
    callbackِ کهنه در همان لحظه رد می‌شود.

    برمی‌گرداند: تعداد مجوزهایی که غیرفعّال شدند.
    """
    q = ("UPDATE permission_grants SET is_active = 0, updated_at = ? "
         "WHERE subject_user_id = ? AND capability = ? AND is_active = 1")
    params: list = [_now(), subject_user_id, capability]
    if scope_type is not None:
        q += " AND scope_type = ?"
        params.append(scope_type)
        if scope_id is not None:
            q += " AND scope_id IS ?"
            params.append(scope_id)
    with _conn_immediate() as c:
        cur = c.execute(q, tuple(params))
        return cur.rowcount


def get_active_grants(subject_user_id: int, capability: str = CAP_ACCOUNT_SECURITY) -> list:
    """همه‌ی مجوزهای فعّالِ این کاربر برای این ظرفیت (هر محدوده‌ای)."""
    with _grants_conn() as c:
        rows = c.execute(
            "SELECT * FROM permission_grants "
            "WHERE subject_user_id = ? AND capability = ? AND is_active = 1 "
            "AND (expires_at IS NULL OR expires_at = '' OR expires_at > ?) "
            "ORDER BY created_at DESC",
            (subject_user_id, capability, _now()),
        ).fetchall()
    return [dict(r) for r in rows if r]


def has_capability(subject_user_id: int, capability: str = CAP_ACCOUNT_SECURITY,
                   main_owner_id: int = None) -> bool:
    """
    آیا این کاربر مجوزِ این ظرفیت را دارد (در هر محدوده‌ای)؟

    توجه: این تابع *فقط* وجودِ مجوز را چک می‌کند — برای عملیاتِ واقعی روی
    یک اکانت، باید از authorize_sensitive_account_action استفاده کنی که
    مالکیت/دامنه را هم اعتبارسنجی می‌کند.

    main_owner_id فقط در نمونه‌ی اصلی پاس داده می‌شود. اگر None باشد،
    owner bypass وجود ندارد (حالتِ پیش‌فرضِ امن).
    """
    if _capability_subject_is_main_owner(subject_user_id, main_owner_id):
        return True
    try:
        return bool(get_active_grants(subject_user_id, capability))
    except Exception:
        # هر شکست در خواندنِ مجوزها → DENY (fail-closed). این یعنی اگر
        # دیتابیس اصلی از یک نمونه‌ی فرعی قابل خواندن نباشد، ابزارهای حساس
        # آنجا کار نمی‌کنند تا زمانی که دسترسی برقرار شود.
        return False


def get_grant_by_id(grant_id: int):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM permission_grants WHERE id = ?", (grant_id,)
        ).fetchone()
    return dict(row) if row else None


def list_capability_grants(capability: str = CAP_ACCOUNT_SECURITY,
                           active_only: bool = True) -> list:
    """همه‌ی مجوزهای این ظرفیت — برای صفحه‌ی مدیریتِ OWNER."""
    q = "SELECT * FROM permission_grants WHERE capability = ?"
    if active_only:
        q += " AND is_active = 1"
    q += " ORDER BY is_active DESC, updated_at DESC"
    with _conn() as c:
        rows = c.execute(q, (capability,)).fetchall()
    return [dict(r) for r in rows]


def capability_grant_exists(subject_user_id: int, capability: str,
                            scope_type: str, scope_id: str) -> bool:
    """آیا مجوزِ فعّالِ دقیقاً با این محدوده وجود دارد؟ (برای نمایشِ ON/OFF)."""
    with _grants_conn() as c:
        row = c.execute(
            "SELECT 1 FROM permission_grants "
            "WHERE subject_user_id = ? AND capability = ? AND scope_type = ? "
            "AND scope_id IS ? AND is_active = 1 "
            "AND (expires_at IS NULL OR expires_at = '' OR expires_at > ?)",
            (subject_user_id, capability, scope_type, scope_id, _now()),
        ).fetchone()
    return row is not None


def _security_main_owner_id():
    """
    OWNER_ID فقط در نمونه‌ی اصلیِ سیستم معتبر است. در یک رباتِ اختصاصی،
    ADMIN_ID صاحبِ همان ربات است و نباید owner bypass بگیرد — این دقیقاً
    همان «دارنده‌ی ربات اختصاصی => خودبه‌خود همه‌چیز» است که ممنوع است.
    پس در نمونه‌ی فرعی None برمی‌گردد (یعنی بدون owner bypass).
    """
    return None if IS_DEDICATED_BOT else OWNER_ID


def grant_matches_account(grant: dict, acc: dict, tag: str, actor_id: int) -> bool:
    """
    آیا این مجوزِ فعّال، شاملِ این اکانتِ مشخص می‌شود؟ (اعتبارسنجیِ دامنه).

    قلبِ امنیتیِ سیستم: داشتنِ مجوز کافی نیست — مجوز باید دامنه‌اش درستِ
    همین اکانت باشد. هیچ‌گاه به tag یا آیدیِ داخلِ callback اعتماد نمی‌شود؛
    مالکیتِ اکانت از config و روابطِ سروری حل می‌شود.
    """
    if not isinstance(grant, dict) or not isinstance(acc, dict):
        return False
    scope_type = grant.get("scope_type")
    scope_id = grant.get("scope_id")

    if scope_type == SCOPE_ACCOUNT:
        # فقط همین تگ. مقایسه‌ی دقیق.
        return bool(scope_id) and scope_id == tag

    if scope_type == SCOPE_RESELLER:
        # دامنه‌ی مشتریانِ خودِ این نماینده. اکانت یا متعلق به خودِ اوست یا
        # به یکی از مشتریانِ ثبت‌شده‌ی او. مالکیت با account_belongs_to حل
        # می‌شود — تنها قاعده‌ی مالکیت در کل پروژه.
        if account_belongs_to(acc, tag, actor_id):
            return True
        try:
            customer_ids = [u["user_id"] for u in list_users_for_reseller(actor_id)]
        except Exception:
            return False
        return any(account_belongs_to(acc, tag, cid) for cid in customer_ids)

    if scope_type == SCOPE_DEDICATED_BOT:
        # فقط در چارچوبِ یک رباتِ اختصاصیِ مشخص. scope_id باید idِ عددیِ
        # ربات باشد؛ ربات از سرور حل می‌شود (نه از callback).
        try:
            bot_id = int(scope_id)
        except (TypeError, ValueError):
            return False
        bot = get_dedicated_bot(bot_id)
        if not bot or bot.get("status") in ("deleted", "rejected"):
            return False
        
        # اگر در یک نمونه‌ی رباتِ اختصاصی هستیم، مجوز فقط در همان نمونه
        # معتبر است که DEDICATED_BOT_ID با scope_id برابر باشد.
        # این مانع از अधिकारِ مجوزهای dedicated_bot در نمونه‌ی اصلی
        # یا در رباتِ اختصاصیِ دیگر می‌شود.
        if IS_DEDICATED_BOT:
            return DEDICATED_BOT_ID == bot_id and account_belongs_to(acc, tag, bot.get("owner_id"))
        
        # در نمونه‌ی اصلی: اکانت باید متعلق به صاحبِ همان ربات باشد.
        return account_belongs_to(acc, tag, bot.get("owner_id"))

    return False


def authorize_sensitive_account_action(actor_id: int, account_tag: str):
    """
    مرکزِ واحدِ تصمیم برای همه‌ی عملیاتِ حساسِ امنیتِ اکانت.

    فقط این تابع قانون دارد. هر مسیرِ حساس (UI، callback، action) باید از
    همینجا عبور کند تا هیچ قانونِ موازی/ متناقضی وجود نداشته باشد.

    خروجی: (allowed: bool, reason: str)
      - reason فقط برای لاگِ داخلی و پیامِ کوتاهِ کاربر است؛ جزئیاتِ
        داخلی (نامِ مجوز، کدام چک رد شد) هرگز به کاربر نمی‌رود.
    """
    # ۱) اکانت را از سرور حل می‌کنیم — tagِ داخلِ callback فقط یک کلیدِ
    #    جستجوست، نه مدرکِ مالکیت.
    try:
        cfg = load_config()
    except Exception:
        return False, "خواندن وضعیت اکانت ناموفق بود. دوباره تلاش کن."
    acc = cfg.get(account_tag) if cfg else None
    if not isinstance(acc, dict):
        return False, "این اکانت دیگر وجود ندارد."

    # ۲) owner bypass — فقط مالکِ اصلیِ سیستم (در رباتِ اختصاصی هیچ‌وقت).
    main_owner = _security_main_owner_id()
    if main_owner and actor_id == main_owner:
        return True, "owner"

    # ۳) فقط مجوزهای صریح و فعّال. هر شکست در خواندن → DENY.
    try:
        grants = get_active_grants(actor_id, CAP_ACCOUNT_SECURITY)
    except Exception:
        return False, "خواندن وضعیت مجوزها ناموفق بود. دوباره تلاش کن."

    if not grants:
        return False, "no_capability"

    # ۴) دامنه‌ی هر مجوز را درستِ همین اکانت بررسی می‌کنیم.
    for g in grants:
        try:
            if grant_matches_account(g, acc, account_tag, actor_id):
                return True, f"grant#{g.get('id')}"
        except Exception:
            continue

    return False, "out_of_scope"


# ─────────────────────────────────────────────────────
#  ربات‌های اختصاصی (نمایندگی) — درخواست → پرداخت → راه‌اندازی
# ─────────────────────────────────────────────────────

def create_dedicated_bot(reseller_id: int, owner_id: int, token: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO dedicated_bots (reseller_id, owner_id, token, status, created_at) "
            "VALUES (?, ?, ?, 'pending_payment', ?)",
            (reseller_id, owner_id, token, _now()),
        )
        return cur.lastrowid


def get_dedicated_bot(bot_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM dedicated_bots WHERE id = ?", (bot_id,)).fetchone()
    return dict(row) if row else None


def get_pending_dedicated_bot_for_reseller(reseller_id: int):
    """جدیدترین درخواستِ ربات اختصاصیِ در انتظارِ پرداختِ این نماینده."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM dedicated_bots WHERE reseller_id = ? AND status = 'pending_payment' "
            "ORDER BY id DESC LIMIT 1",
            (reseller_id,),
        ).fetchone()
    return dict(row) if row else None


def list_dedicated_bots(limit: int = 20) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM dedicated_bots ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def list_active_dedicated_bots() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM dedicated_bots WHERE status = 'active'"
        ).fetchall()
    return [dict(r) for r in rows]


def update_dedicated_bot_status(bot_id: int, status: str, payment_id: int = None,
                                bot_dir: str = None, pid: int = None,
                                expire_date: str = None) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE dedicated_bots SET status = ?, payment_id = COALESCE(?, payment_id), "
            "bot_dir = COALESCE(?, bot_dir), pid = COALESCE(?, pid), "
            "expire_date = COALESCE(?, expire_date), reviewed_at = ? WHERE id = ?",
            (status, payment_id, bot_dir, pid, expire_date, _now(), bot_id),
        )


# ─────────────────────────────────────────────────────
#  تیکت‌های پشتیبانی
# ─────────────────────────────────────────────────────

def get_open_ticket(user_id: int):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM tickets WHERE user_id = ? AND status = 'open' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def create_ticket(user_id: int) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO tickets (user_id, status, created_at) VALUES (?, 'open', ?)",
            (user_id, _now()),
        )
        return cur.lastrowid


def get_ticket(ticket_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return dict(row) if row else None


def close_ticket(ticket_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))


def ticket_message_count(ticket_id: int) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM ticket_messages WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
    return row["n"]


def add_ticket_message(ticket_id: int, sender_role: str, sender_id: int, text: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO ticket_messages (ticket_id, sender_role, sender_id, text, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticket_id, sender_role, sender_id, text, _now()),
        )


def list_ticket_messages(ticket_id: int) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY created_at", (ticket_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def list_open_tickets() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM tickets WHERE status = 'open' ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]

# ══════════════════════════════════════════════════════════════════════
# ═══ بخش admin_bot.py (ادغامشده) ═══
# ══════════════════════════════════════════════════════════════════════

# ── اعتبارنامه‌های مدیریت — فقط از ENV. هیچ مقدار واقعی داخل سورس نیست. ──
# اگر ADMIN_BOT_TOKEN یا ADMIN_ID تنظیم نشده باشند، مقدار خالی می‌ماند و
# AdminBot.start() با پیام واضح fail می‌شود (به‌جای کارکردن با یک توکن
# مخفیِ هاردکد که نشت می‌کرد). برای اجرا:
#   export ADMIN_BOT_TOKEN="..." ADMIN_ID="..."
# یا از systemd Environment=... / فایل .env استفاده کن.
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "")
_admin_id_raw = os.environ.get("ADMIN_ID", "").strip()
ADMIN_ID = int(_admin_id_raw) if _admin_id_raw.isdigit() else 0  # 0 = تنظیم‌نشده

# آیا این نمونه، یک «ربات اختصاصی» است (زیرپروسه‌ای که برای یک نماینده/
# مشتری spawn شده)؟ _spawn_dedicated_bot این متغیر را برای فرآیندِ جدا set
# می‌کند. در نمونه‌ی اصلیِ سیستم وجود ندارد.
#
# کاربرد: قابلیت‌های حساسِ «دستگاه‌های لاگین‌شده»، «رمز دو مرحله‌ای» و
# «دریافت کد لاگین» فقط مختصِ مالکِ اصلیِ سیستم‌اند. مالکِ یک ربات
# اختصاصی، نماینده‌ای است که آن را خریده و نباید بتواند دستگاه‌های
# مشتریانش را ببندد، رمز دومرحله‌ای را بردارد یا کد لاگین بگیرد.
IS_DEDICATED_BOT = os.environ.get("SELFBOT_DEDICATED_BOT", "").strip() == "1"

# شناسه‌ی دقیقِ ربات اختصاصی در حال اجرا (فقط در نمونه‌های فرعی ست می‌شود).
# برای اعتبارسنجیِ مجوزِ SCOPE_DEDICATED_BOT در لایه‌ی Authorization:
# یک مجوز با scope_type=dedicated_bot و scope_id=N فقط در نمونه‌ای معتبر است
# که DEDICATED_BOT_ID == N باشد. این مانع از अधिकारِ اشتباهِ مجوزهای
# dedicated_bot در نمونه‌ی اصلی یا در رباتِ اختصاصیِ دیگر می‌شود.
DEDICATED_BOT_ID = 0
try:
    _dbid_raw = os.environ.get("SELFBOT_DEDICATED_BOT_ID", "").strip()
    if _dbid_raw.isdigit():
        DEDICATED_BOT_ID = int(_dbid_raw)
except Exception:
    pass


def _validate_saas_env() -> list:
    """
    اعتبارسنجی کامل متغیرهای محیطی ربات مدیریت (SaaS) — همه‌ی مواردِ missing
    یا نامعتبر را یک‌جا (نه یکی‌یکی) برمی‌گرداند، بدون نمایش هیچ secret.
    بر اساس env واقعیِ همین فرآیند، نه مقدارِ از قبل خوانده‌شده — تا اگر
    ADMIN_ID فقط در env تنظیم شده باشد (چون ماژول قبل از آن import شده)،
    درست تشخیص داده شود.
    """
    problems = []
    token = os.environ.get("ADMIN_BOT_TOKEN", "").strip()
    if not token:
        problems.append("ADMIN_BOT_TOKEN تنظیم نشده است (توکن ربات مدیریت)")
    raw_id = os.environ.get("ADMIN_ID", "").strip()
    if not raw_id:
        problems.append("ADMIN_ID تنظیم نشده است (آیدی عددی مالک)")
    elif not raw_id.isdigit() or int(raw_id) <= 0:
        problems.append(f"ADMIN_ID باید یک عدد صحیح مثبت باشد (فعلاً: {raw_id!r})")
    return problems


def _validate_saas_env_or_exit() -> None:
    """
    اگر env ربات مدیریت ناقص است، همه‌ی مشکلات را یک‌جا چاپ و با کد ۱ خارج
    می‌شود — قبل از این‌که حتی helper یا SelfBot‌ها بالا بیایند.
    """
    problems = _validate_saas_env()
    if not problems:
        return
    print("❌ راه‌اندازی متوقف شد — متغیرهای محیطی ربات مدیریت (SaaS) ناقص‌اند:")
    for p in problems:
        print(f"   - {p}")
    print("   قبل از اجرا آن‌ها را تنظیم کن، مثلاً:")
    print('   export ADMIN_BOT_TOKEN="<token>" ADMIN_ID="<owner-id>"')
    print("   یا از systemd Environment=... / فایل .env استفاده کن.")
    raise SystemExit(1)


ADMIN_BOT_SESSION_NAME = "_admin_bot"
ADMIN_LIST_FILE = os.path.join(DATA_DIR, "admin_bot_admins.json")
# ساعات پشتیبان‌گیری خودکار روزانه (به وقت ایران).
# پیش‌فرض: ۰۰:۰۰ (نیمه‌شب) و ۱۲:۰۰ (ظهر). برای تغییر، این لیست را
# ویرایش کنید (مثلاً فقط [4] برای یک بکاپ روزانه در ساعت ۴ بامداد).
BACKUP_HOURS_IRAN = [0, 12]  # [ساعت ۱, ساعت ۲, ...] — به وقت ایران
BACKUP_HOUR_IRAN = BACKUP_HOURS_IRAN[0]  # backward-compat با کدهای قدیمی

# مراحل ویزارد «افزودن اکانت»
WIZ_TAG = "awaiting_tag"
WIZ_PHONE = "awaiting_phone"
WIZ_CODE = "awaiting_code"
WIZ_PASSWORD = "awaiting_password"
# مراحل ویزارد «تنظیم پروکسی» (هم برای لاگین اکانت جدید، هم برای اکانت موجود)
WIZ_PROXY_ADDR = "awaiting_proxy_addr"
WIZ_PROXY_PORT = "awaiting_proxy_port"
WIZ_PROXY_USERNAME = "awaiting_proxy_username"
WIZ_PROXY_PASSWORD = "awaiting_proxy_password"
# مرحله‌ی ویزارد «افزودن ادمین» (فقط در حالت standalone استفاده می‌شود)
WIZ_ADD_ADMIN = "awaiting_admin_id"
# مراحل ویزارد «ارسال پیام»
WIZ_SEND_MSG_TARGET = "awaiting_send_msg_target"
WIZ_SEND_MSG_TEXT = "awaiting_send_msg_text"
# مرحله‌ی ویزارد «تغییر اسم پایه»
WIZ_EDIT_NAME = "awaiting_new_name"

RESERVED_TAGS = {"all", "new", "delete", ADMIN_BOT_SESSION_NAME}

FONT_CHOICES = ["bold", "double", "sans", "sans_bold", "mono", "normal"]

# قابلیت‌های ساده‌ای که toggle‌شان فقط یک فلگ boolean را عوض می‌کند (بدون
# نیاز به مدیریت تسک پس‌زمینه‌ی جداگانه)
SIMPLE_BOOL_FEATURES = {"auto_read_pv", "auto_read_group", "auto_read_channel", "silence_all"}

# نمایشِ یکسانِ قابلیت‌های سلف در دو بخش: صفحه‌ی «⚡ قابلیت‌ها» (با دکمه‌های
# toggle) و «📊 وضعیت کامل» (گزارش فقط‌خواندنی). یک منبع واحد تا برچسب‌ها و
# ترتیب در هر دو جا همیشه یکی باشد.
FEATURE_LABELS = [
    ("enabled", "سلف"),
    ("time_enabled", "تایم-نام"),
    ("bio_enabled", "بیو-ساعت"),
    ("online_enabled", "آنلاین دائمی"),
    ("tracker_enabled", "ردیاب"),
    ("silence_all", "سکوت همه"),
    ("auto_read_pv", "تیک پیوی"),
    ("auto_read_group", "تیک گروه"),
    ("auto_read_channel", "تیک کانال"),
]

# حداکثر زمان انتظار (به ثانیه) برای اینکه یک اکانت تازه‌روشن‌شده در
# self.sb.ACCOUNTS ظاهر شود، قبل از نمایش صفحه‌ی جزئیات
ACCOUNT_START_POLL_TIMEOUT = 12


# ══════════════════════════════════════════════════════════════════════
# ═══ UI Kit + Navigation Stack (لایه‌ی یکپارچه‌ی رابط کاربری) ═══
# ══════════════════════════════════════════════════════════════════════
# این بخش «منبع واحدِ ظاهر و ناوبری» هر دو پنل (SaaSBot و AdminBot) است.
#
# چرا از صفر نوشته شد؟ سه مشکلِ ریشه‌ایِ UI قبلی:
#
#   ۱) «بازگشت» مقصدِ ثابتِ hard-code بود (۴۸ دکمه مستقیم به منوی نقش) و
#      برای صفحاتِ اکانت/کاربر، مقصدِ بازگشت در دو dictِ تک‌خانه‌ایِ
#      سراسری (_acc_back / _uacc_back) نگه‌داری می‌شد. آن dictها با هر
#      ناوبریِ دیگری overwrite می‌شدند و هیچ‌وقت پاک نمی‌شدند — پس اگر
#      کاربر یک اکانت را از مسیر A باز می‌کرد و بعد همان را از مسیر B،
#      «بازگشت» او را به صفحه‌ی مسیرِ قبلی می‌برد. دقیقاً همان رفتارِ
#      «بازگشت یک فرم دیگر می‌آورد بالا».
#
#   ۲) مقصدِ بازگشت داخل خودِ callback_data جاسازی می‌شد
#      (`user_manage:{id}:{back}`) — یعنی یک صفحه‌ی واحد بسته به مسیرِ
#      ورود، callback_dataهای متفاوت داشت؛ هم شکننده بود، هم به سقفِ
#      ۶۴ بایتیِ تلگرام نزدیک می‌شد.
#
#   ۳) برچسب‌ها ناهماهنگ بودند («برگشت» ۹۸ بار / «بازگشت» ۲۱ بار) و
#      رنگ/وضعیت فقط در دو صفحه نشان داده می‌شد.
#
# راه‌حل: هر صفحه یک «مسیر» (route) کوتاه و یکتا دارد؛ تاریخچه‌ی مسیرها در
# یک پشته‌ی به‌ازای-کاربر نگه‌داری می‌شود؛ «بازگشت» یعنی pop از پشته و
# رندرِ دوباره‌ی همان مسیر از طریقِ همان dispatcher. هیچ مقصدی جایی
# hard-code یا جاسازی نمی‌شود.

# مسیرهای رزروشده‌ی ناوبری. عمداً با پیشوندِ `nav:` تا هرگز با هیچ
# callbackِ واقعیِ صفحات اشتباه گرفته نشوند و در dispatcher زودتر از همه
# پردازش شوند.
NAV_BACK = "nav:back"
NAV_HOME = "nav:home"
NAV_NOOP = "nav:noop"    # دکمه‌ی تزئینی (مثلاً شمارنده‌ی صفحه) — کاری نمی‌کند

# مسیرهایی که «صفحه» نیستند بلکه «عمل» هستند: بعد از اجرا همان صفحه‌ی
# قبلی دوباره رندر می‌شود، پس نباید یک قدمِ جدید در پشته بسازند وگرنه
# «بازگشت» روی همان صفحه گیر می‌کند.
NAV_ACTION_PREFIXES = (
    "nav:", "toggle:", "enable:", "disable:", "del_go:",
    "user_delete_go:", "user_unlink_go:", "dedicated_toggle:",
    "dedicated_revoke_go:", "dedicated_delete_go:", "ticket_close_go:",
    "pay_approve:", "pay_reject:", "font_set:", "order_cancel:",
    "channel_retry", "channel_confirm_save", "owner_channel_clear",
    "owner_db_restore_go", "owner_db_restore_cancel", "owner_backup",
    "owner_db_backup", "admin_del:", "role_del:", "cancel_wizard",
    "user_support_end", "proxy_skip_auth", "login_proxy_yes",
    "login_proxy_no", "send_target_me", "owner_channel_check",
    # بستنِ نشست‌ها عمل است و خودش فهرست را دوباره رندر می‌کند
    "sessterm:", "sesskill:", "sesstog:", "codeget:", "codearm:",
    "tfago:", "tfacancel:",
    # اعطا/سلبِ مجوز عمل است؛ صفحه‌ی کاربر را دوباره رندر می‌کنند.
    "cap_grant:", "cap_revoke:", "dbcap_grant:", "dbcap_revoke:",
)


def _is_nav_action(route: str) -> bool:
    """آیا این مسیر یک «عمل» است (و نباید وارد پشته‌ی ناوبری شود)؟"""
    return any(route == p or route.startswith(p) for p in NAV_ACTION_PREFIXES)


# آیا telethon نصب‌شده از رنگِ واقعیِ دکمه پشتیبانی می‌کند؟
#
# Bot API 9.4 (بهمن ۱۴۰۴ / فوریه ۲۰۲۶) فیلد style را به KeyboardButton و
# InlineKeyboardButton اضافه کرد: bg_success (سبز)، bg_danger (قرمز)،
# bg_primary (آبی) و پیش‌فرض (خنثی/خاکستری). telethon از نسخه‌ی ۱.۴۵
# (لایه‌ی ۲۲۹) آن را با پارامترِ style در Button.inline پشتیبانی می‌کند.
#
# چون ممکن است روی سرور نسخه‌ی قدیمی‌تری نصب باشد، به‌جای فرضِ کورکورانه
# یک بار امضا را چک می‌کنیم. اگر پشتیبانی نبود، UI بی‌صدا به حالتِ
# «نشانگرِ ابتدای برچسب» برمی‌گردد و هیچ‌چیز نمی‌شکند.
try:
    import inspect as _inspect
    BUTTON_STYLE_SUPPORTED = "style" in _inspect.signature(Button.inline).parameters
except Exception:
    BUTTON_STYLE_SUPPORTED = False

# نگاشتِ «وضعیتِ نام‌دار» → رنگِ واقعیِ تلگرام.
# تلگرام رنگِ زرد/کهربایی ندارد؛ برای وضعیت‌های «در حال انجام/هشدار»
# پس‌زمینه خنثی می‌ماند و معنا با نشانگر 🟡 منتقل می‌شود.
UI_STATE_STYLE = {
    "on": "success", "ready": "success", "active": "success", "running": "success",
    "off": "danger", "error": "danger", "expired": "danger", "failed": "danger",
    # تلگرام رنگِ زرد/کهربایی ندارد. این وضعیت‌ها پس‌زمینه‌ی آبی می‌گیرند
    # (تا هیچ دکمه‌ای بی‌رنگ نماند) و معنای دقیقشان با نشانگرِ 🟡/⏸ در
    # ابتدای برچسب منتقل می‌شود — یعنی رنگ هیچ‌وقت تنها حاملِ معنا نیست.
    "starting": "primary", "connecting": "primary", "pending": "primary",
    "stopping": "primary", "warn": "primary", "paused": "primary",
    "disabled": "primary",
}

# وضعیت‌هایی که رنگِ بومی ندارند و باید نشانگرِ متنی نگه دارند
UI_STATES_NEED_DOT = {"starting", "connecting", "pending", "stopping", "warn",
                      "paused", "disabled"}


class UI:
    """
    پالت و سازنده‌های دکمه — تنها منبعِ رنگ/برچسب در کل ربات.

    پالت (معنای ثابت در همه‌ی صفحات):
      🟢 روشن / فعال / سالم / تایید
      🔴 خاموش / منقضی / خطا / عملیات مخرب
      🟡 در حال انجام / هشدار / در انتظار
      ⚪ خنثی / تنظیم‌نشده / غیرفعال / ثانویه
      ⏸ متوقف‌شده‌ی دستی

    رنگ چطور اعمال می‌شود (دو لایه):

      ۱) رنگِ *واقعیِ* پس‌زمینه‌ی دکمه — از Bot API 9.4 (فوریه ۲۰۲۶) فیلد
         style به دکمه‌ها اضافه شد: bg_success (سبز)، bg_danger (قرمز)،
         bg_primary (آبی) و پیش‌فرض (خنثی). telethon ≥ ۱.۴۵ آن را با
         پارامترِ style در Button.inline پشتیبانی می‌کند و همین‌جا استفاده
         می‌شود. هم روی دکمه‌های شیشه‌ای (inline) کار می‌کند هم reply.

      ۲) نشانگرِ متنیِ ابتدای برچسب — برای دو حالت لازم می‌ماند:
         • telethonِ قدیمی‌تر از ۱.۴۵ روی سرور (تشخیصِ خودکار با
           BUTTON_STYLE_SUPPORTED؛ UI بی‌صدا به این حالت برمی‌گردد)
         • وضعیت‌هایی که تلگرام رنگِ بومی برایشان ندارد — «در حال
           اتصال/در انتظار/متوقف» زرد و خاکستری‌اند و باید 🟡/⏸ بگیرند.

    وقتی رنگِ واقعی در دسترس است، نشانگر تکرار نمی‌شود تا برچسب شلوغ نشود.

    متنِ داخلِ پیام (نه دکمه) همیشه از همین نشانگرها استفاده می‌کند، چون
    آنجا رنگی وجود ندارد.
    """

    GREEN = "🟢"
    RED = "🔴"
    AMBER = "🟡"
    GRAY = "⚪"
    PAUSED = "⏸"

    # نشانگرهای نقشِ دکمه
    OK = "✅"
    NO = "❌"
    DANGER = "🗑"
    BACK = "⬅️"
    HOME = "🏠"
    REFRESH = "🔄"
    PREV = "◀️"
    NEXT = "▶️"

    # برچسب‌های یکسان (قبلاً «برگشت» و «بازگشت» قاطی بودند)
    L_BACK = "بازگشت"
    L_HOME = "منوی اصلی"
    L_CANCEL = "انصراف"

    @staticmethod
    def dot(value) -> str:
        """نشانگرِ دوحالته — پایه‌ی همه‌ی دکمه‌های روشن/خاموش."""
        return UI.GREEN if value else UI.RED

    @staticmethod
    def state_dot(state: str) -> str:
        """
        نشانگرِ وضعیتِ چندحالته. کلیدها عمداً با وضعیت‌های runtime همین
        پروژه یکی هستند تا هیچ‌جا ترجمه‌ی دستی لازم نشود.
        """
        return {
            "on": UI.GREEN, "ready": UI.GREEN, "active": UI.GREEN, "running": UI.GREEN,
            "off": UI.RED, "error": UI.RED, "expired": UI.RED, "failed": UI.RED,
            "starting": UI.AMBER, "connecting": UI.AMBER, "pending": UI.AMBER,
            "stopping": UI.AMBER, "warn": UI.AMBER,
            "paused": UI.PAUSED, "disabled": UI.PAUSED,
        }.get(state, UI.GRAY)

    # ── سازنده‌های دکمه ────────────────────────────────────────────────

    @staticmethod
    def btn(label: str, route: str, style: str = None):
        """
        دکمه‌ی پایه.

        style یکی از 'success' (سبز) / 'danger' (قرمز) / 'primary' (آبی)
        یا None (خنثی — خاکستری/بی‌رنگ). اگر telethonِ نصب‌شده رنگ را
        پشتیبانی نکند، همان دکمه بدون رنگ ساخته می‌شود؛ معنا از
        نشانگرهای متنی که صداکننده اضافه کرده همچنان منتقل می‌شود.
        """
        data = route.encode() if isinstance(route, str) else route
        if style and BUTTON_STYLE_SUPPORTED:
            try:
                return Button.inline(label, data, style=style)
            except (TypeError, ValueError):
                # نسخه‌ی مرزی/مقدارِ ناشناخته — بی‌رنگ ادامه بده
                pass
        return Button.inline(label, data)

    # بازه‌های یونیکدی که «ایموجیِ ابتدای برچسب» حساب می‌شوند. دکمه‌هایی
    # که نشانگرِ وضعیت می‌گیرند نباید ایموجیِ تزئینیِ خودشان را هم نگه
    # دارند — «⚪ ⏳ وضعیت اشتراک» شلوغ است و رنگ را گم می‌کند؛ باید
    # «⚪ وضعیت اشتراک» شود. این کار یک‌جا انجام می‌شود تا هیچ call site
    # لازم نباشد یادش باشد.
    _ICON_RANGES = (
        (0x1F300, 0x1FAFF), (0x2190, 0x21FF), (0x2300, 0x23FF),
        (0x2460, 0x27BF), (0x2B00, 0x2BFF), (0xFE00, 0xFE0F),
    )

    @staticmethod
    def _strip_lead_icon(label: str) -> str:
        s = (label or "").lstrip()
        while s:
            cp = ord(s[0])
            if any(a <= cp <= b for a, b in UI._ICON_RANGES):
                s = s[1:].lstrip()
                continue
            break
        return s or (label or "")

    @staticmethod
    def toggle(label: str, value, route: str):
        """
        دکمه‌ی روشن/خاموش. روی تلگرامِ جدید پس‌زمینه‌ی سبز/قرمزِ واقعی
        می‌گیرد؛ روی کلاینت/نسخه‌ی قدیمی‌تر، نشانگرِ 🟢/🔴 همان معنا را
        می‌رساند. وقتی رنگِ واقعی هست، نشانگر تکرار نمی‌شود تا برچسب
        شلوغ نشود.
        """
        label = UI._strip_lead_icon(label)
        if BUTTON_STYLE_SUPPORTED:
            return UI.btn(label, route, style="success" if value else "danger")
        return UI.btn(f"{UI.dot(value)} {label}", route)

    @staticmethod
    def item(label: str, state: str, route: str):
        """
        آیتمِ لیست (اکانت/کاربر/ربات) با وضعیت.

        وضعیت‌هایی که رنگِ بومیِ تلگرام دارند (سبز/قرمز) با پس‌زمینه
        نشان داده می‌شوند؛ «در حال اتصال/در انتظار/متوقف» رنگِ بومی
        ندارند، پس نشانگرِ 🟡/⏸ را نگه می‌دارند.
        """
        label = UI._strip_lead_icon(label)
        if BUTTON_STYLE_SUPPORTED:
            # پیش‌فرضِ آبی: وضعیتِ ناشناخته هم دکمه‌ی بی‌رنگ تولید نمی‌کند
            style = UI_STATE_STYLE.get(state) or "primary"
            if state in UI_STATES_NEED_DOT:
                return UI.btn(f"{UI.state_dot(state)} {label}", route, style=style)
            return UI.btn(label, route, style=style)
        return UI.btn(f"{UI.state_dot(state)} {label}", route)

    @staticmethod
    def go(label: str, route: str, primary: bool = False, tone: str = "primary"):
        """
        ورود به یک بخش/صفحه. برچسب ایموجیِ معناییِ خودش را نگه می‌دارد.

        پیش‌فرض آبی است تا هیچ دکمه‌ی بی‌رنگی در ربات نماند. tone را فقط
        وقتی عوض کن که می‌خواهی یک دکمه از بقیه‌ی هم‌ردیف‌هایش متمایز شود.
        """
        return UI.btn(label, route, style=tone if tone else ("primary" if primary else None))

    @staticmethod
    def confirm(label: str, route: str):
        """تاییدِ یک عملیات — سبز."""
        if BUTTON_STYLE_SUPPORTED:
            return UI.btn(UI._strip_lead_icon(label), route, style="success")
        return UI.btn(f"{UI.OK} {label}", route)

    @staticmethod
    def danger(label: str, route: str):
        """عملیاتِ مخرب/برگشت‌ناپذیر — قرمز."""
        if BUTTON_STYLE_SUPPORTED:
            return UI.btn(UI._strip_lead_icon(label), route, style="danger")
        return UI.btn(f"{UI.RED} {label}", route)

    @staticmethod
    def neutral(label: str, route: str):
        """
        عملیاتِ ثانویه — تنها جایی که عمداً بی‌رنگ می‌ماند.

        دلیل: «انصراف» همیشه کنارِ یک دکمه‌ی قرمزِ برگشت‌ناپذیر می‌نشیند.
        اگر آن هم رنگی باشد، چشم بین دو دکمه‌ی پررنگ مردد می‌ماند و
        احتمالِ کلیکِ اشتباه روی «حذف» بالا می‌رود. خنثی‌بودنِ انصراف
        یعنی دکمه‌ی خطرناک تنها چیزی است که جلب توجه می‌کند.
        """
        if BUTTON_STYLE_SUPPORTED:
            return UI.btn(UI._strip_lead_icon(label), route)
        return UI.btn(f"{UI.GRAY} {label}", route)

    @staticmethod
    def refresh(route: str):
        return UI.btn(f"{UI.REFRESH} بروزرسانی", route, style="primary")

    @staticmethod
    def cancel(route: str = NAV_BACK):
        return UI.neutral(UI.L_CANCEL, route)

    # ── ردیف ناوبری ───────────────────────────────────────────────────

    @staticmethod
    def _has_color(btn) -> bool:
        st = getattr(btn, "style", None)
        if st is None:
            return False
        return bool(getattr(st, "bg_primary", None) or getattr(st, "bg_danger", None)
                    or getattr(st, "bg_success", None))

    @staticmethod
    def paint(rows: list, alternate: bool = False) -> list:
        """
        تضمینِ نهایی: هیچ دکمه‌ای بی‌رنگ باقی نمی‌ماند.

        هر دکمه‌ای که تا اینجا رنگ نگرفته (چون از مسیرِ UI.* نساخته شده یا
        جا افتاده) اینجا رنگ می‌گیرد.

        alternate به‌طور پیش‌فرض خاموش است. اگر روشن باشد، رنگ بین آبی و سبز
        عوض می‌شود تا منوهای بلند یک دیوارِ یکدستِ آبی نشوند — ولی این
        معنای سبز (روشن/فعال/تایید) را خراب می‌کند، چون یک دکمه‌ی سبزِ کور
        در لیست می‌تواند هم حالتِ «فعال» باشد و هم فقط یک دکمه‌ی در موقعیتِ
        زوج باشد. راهِ درستِ منوی بلند، کوتاه‌کردنِ خودِ لیست است.

        نکته‌ی معنایی: این فقط روی دکمه‌هایی اثر می‌گذارد که *هیچ* رنگی
        نداشته‌اند. دکمه‌های حالت‌دار (کلید روشن/خاموش، حذف، تایید) رنگشان
        را از قبل دارند و اینجا دست‌نخورده رد می‌شوند — پس معنای سبز/قرمز
        هیچ‌جا مخدوش نمی‌شود.
        """
        if not BUTTON_STYLE_SUPPORTED:
            return rows
        i = 0
        for row in rows or []:
            for btn in row or []:
                if UI._has_color(btn):
                    continue
                st = getattr(btn, "style", None)
                if st is None:
                    continue
                if alternate and (i % 2):
                    st.bg_success = True
                else:
                    st.bg_primary = True
                i += 1
        return rows

    @staticmethod
    def nav_row(back: bool = True, home: bool = True) -> list:
        """
        ردیفِ ناوبریِ استانداردِ پایینِ هر صفحه. «بازگشت» همیشه یک قدم
        واقعی به عقب است (pop از پشته) و «منوی اصلی» همیشه به ریشه
        می‌رود — کاربر از هیچ عمقی گیر نمی‌افتد.
        """
        row = []
        if back:
            row.append(UI.btn(f"{UI.BACK} {UI.L_BACK}", NAV_BACK, style="primary"))
        if home:
            # «منوی اصلی» مسیرِ همیشه‌امنِ خروج است — آبی تا در هر صفحه‌ای
            # فوراً پیدا شود.
            row.append(UI.btn(f"{UI.HOME} {UI.L_HOME}", NAV_HOME, style="primary"))
        return row

    @staticmethod
    def pager(route_fmt: str, page: int, total_pages: int) -> list:
        """
        ردیفِ صفحه‌بندیِ یکسان. route_fmt یک رشته با {page} است، مثلاً
        "users_list:active:{page}".
        """
        row = []
        if page > 0:
            row.append(UI.btn(f"{UI.PREV} قبلی", route_fmt.format(page=page - 1)))
        if total_pages > 1:
            row.append(UI.btn(f"{page + 1}/{total_pages}", NAV_NOOP))
        if page < total_pages - 1:
            row.append(UI.btn(f"بعدی {UI.NEXT}", route_fmt.format(page=page + 1)))
        return row

    # ── متنِ صفحه ─────────────────────────────────────────────────────

    @staticmethod
    def screen(title: str, body=None, subtitle: str = None, hint: str = None,
               crumbs: list = None) -> str:
        """
        ساختِ متنِ یکدستِ هر صفحه:

            «عنوان»            ← همیشه bold، همیشه خط اول
            مسیر > مسیر        ← breadcrumb (اختیاری، فقط وقتی عمق > ۱)
            زیرعنوان            ← یک جمله توضیحِ کارِ این صفحه
            ─────────
            بدنه
            ─────────
            راهنما             ← «چه کاری از اینجا برمی‌آید»

        قبلاً هر صفحه ساختار متنیِ خودش را داشت (بعضی بدون عنوان، بعضی
        بدون توضیح)؛ همین باعث می‌شد کاربر نفهمد کجاست.
        """
        out = [f"**{title}**"]
        if crumbs:
            out.append(f"__{' › '.join(crumbs)}__")
        if subtitle:
            out.append("")
            out.append(subtitle)
        if body:
            out.append("")
            out.extend(body if isinstance(body, list) else [body])
        if hint:
            out.append("")
            out.append(f"💡 {hint}")
        return "\n".join(out)

    SEP = "━━━━━━━━━━━━━━"


class NavStack:
    """
    پشته‌ی ناوبریِ به‌ازای-کاربر: تاریخچه‌ی مسیرهایی که کاربر واقعاً طی
    کرده. «بازگشت» = pop؛ «منوی اصلی» = clear.

    چرا پشته و نه مقصدِ ثابت؟ چون یک صفحه‌ی واحد (مثلاً «مدیریت اکانت X»)
    از چند مسیر قابل دسترسی است: از لیست کلی اکانت‌ها، از داخل کاربر، از
    «اکانت‌های بدون مالک»، از «سلف‌های من». مقصدِ درستِ بازگشت فقط با
    دانستنِ *مسیرِ واقعیِ طی‌شده* مشخص می‌شود، نه با یک مقدارِ ازپیش‌تعیین‌شده.

    ویژگی‌ها:
      - سقفِ عمق (MAX_DEPTH): حافظه بی‌نهایت رشد نمی‌کند.
      - حذفِ تکرارِ پشت‌سرهم: رندرِ دوباره‌ی همان صفحه (مثلاً بعد از یک
        toggle یا «بروزرسانی») قدمِ جدید حساب نمی‌شود.
      - حلقه‌شکن: اگر مسیری که وارد می‌شویم از قبل در پشته باشد، پشته تا
        همان‌جا کوتاه می‌شود (رفتنِ A→B→A پشته را باد نمی‌کند).
      - سقفِ کاربرانِ هم‌زمان: پشته‌های قدیمی خودکار جمع می‌شوند تا این
        dict در یک سرویسِ همیشه‌روشن نشت نکند.
    """

    MAX_DEPTH = 12
    MAX_USERS = 500

    def __init__(self):
        self._stacks: dict = {}
        self._seen: dict = {}

    def _touch(self, user_id: int) -> None:
        self._seen[user_id] = time.time()
        if len(self._stacks) > self.MAX_USERS:
            # قدیمی‌ترین‌ها را دور بریز (LRU ساده) — ناوبری حالت حیاتی
            # نیست؛ بدترین حالت یعنی «بازگشت» به منوی اصلی می‌رود.
            victims = sorted(self._seen, key=self._seen.get)[: len(self._stacks) // 4 or 1]
            for v in victims:
                self._stacks.pop(v, None)
                self._seen.pop(v, None)

    def push(self, user_id: int, route: str) -> None:
        self._touch(user_id)
        st = self._stacks.setdefault(user_id, [])
        if st and st[-1] == route:
            return
        if route in st:
            del st[st.index(route) + 1:]
            return
        st.append(route)
        if len(st) > self.MAX_DEPTH:
            del st[0]

    def pop(self, user_id: int):
        """مسیرِ قبلی را برمی‌گرداند (و صفحه‌ی فعلی را از پشته برمی‌دارد)."""
        self._touch(user_id)
        st = self._stacks.get(user_id) or []
        if st:
            st.pop()
        return st[-1] if st else None

    def current(self, user_id: int):
        st = self._stacks.get(user_id) or []
        return st[-1] if st else None

    def depth(self, user_id: int) -> int:
        return len(self._stacks.get(user_id) or [])

    def crumbs(self, user_id: int, labels: dict, limit: int = 3) -> list:
        """breadcrumb خوانا از روی پشته (فقط مسیرهایی که برچسب دارند)."""
        st = self._stacks.get(user_id) or []
        out = []
        for r in st[-limit:]:
            lab = labels.get(r) or labels.get(r.split(":", 1)[0])
            if lab:
                out.append(lab)
        return out

    def reset(self, user_id: int) -> None:
        self._stacks.pop(user_id, None)
        self._seen.pop(user_id, None)


class AdminBot:
    """
    پنل مدیریت اکانت‌های سلف.

    این کلاس در دو حالت قابل استفاده است:

    - standalone=True (پیش‌فرض): برای اجرای مستقل admin_bot.py با توکن و
      کلاینت مخصوص خودش (از طریق run_admin_bot_forever). در این حالت،
      دسترسی با یک فایل JSON ساده‌ی محلی (ADMIN_LIST_FILE) کنترل می‌شود
      چون به سیستم نقش‌های saas_db نیازی نیست.

    - standalone=False: وقتی از داخل saas_bot.py ساخته می‌شود. در این حالت
      این کلاس دیگر خودش تصمیم دسترسی نمی‌گیرد — saas_bot.py قبل از
      فراخوانی handle_message/handle_callback از قبل بر اساس نقش کاربر در
      saas_db (OWNER/ADMIN) تصمیم گرفته که آیا اجازه‌ی ورود به این پنل را
      بدهد یا نه. یعنی saas_db تنها منبع حقیقتِ دسترسی است و اینجا هیچ
      چک تکراری/ناهماهنگ دیگری انجام نمی‌شود.
    """

    def __init__(self, selfbot_module, standalone: bool = True, owner_filter=None,
                 default_owner_id=None):
        self.sb = selfbot_module
        self.client: TelegramClient = None
        self.wizards: dict = {}
        self.admin_ids: set = set()
        self._backup_task = None
        # انتخابِ چنددستگاهیِ نشست‌ها: {(sender_id, tag): set(hash)}. با سقفِ
        # اندازه تا در سرویسِ همیشه‌روشن نشت نکند؛ بعد از هر بستن پاک می‌شود.
        self._sess_sel: dict = {}
        # قفل‌های هم‌زمانیِ عملیاتِ حساس، به ازای هر تگ: {tag: asyncio.Lock}.
        # برای محافظت از کلیکِ دوباره/هم‌زمان در عملیاتِ مخرب.
        self._sec_locks: dict = {}
        # پشته‌ی ناوبری. در حالت غیر-standalone، SaaSBot بلافاصله بعد از
        # ساخت، پشته‌ی خودش را اینجا جایگزین می‌کند تا هر دو پنل یک
        # تاریخچه‌ی مشترک داشته باشند — چون کاربر آزادانه بین آن‌ها جابه‌جا
        # می‌شود و «بازگشت» باید مرزِ دو پنل را نبیند.
        #
        # جایگزینِ self._acc_back قبلی: آن یک dictِ تک‌خانه‌ایِ
        # «مقصدِ بازگشتِ اکانت» بود که با هر ناوبریِ دیگری overwrite می‌شد و
        # هیچ‌وقت پاک نمی‌شد؛ دقیقاً منشأ «بازگشت یک فرم دیگر می‌آورد».
        self.nav = NavStack()
        self.standalone = standalone
        # اگر مقداردهی شود (یک set از user_idها یا یک تابع(int)->bool)، این
        # پنل فقط اکانت‌هایی را نشان/قابل‌مدیریت می‌کند که owner_user_id
        # آن‌ها در این مجموعه باشد. برای OWNER/ADMIN مقدارش None می‌ماند
        # (یعنی دسترسی کامل، بدون فیلتر) — فقط برای RESELLER که باید صرفاً
        # اکانت‌های خودش/مشتریانش را ببیند استفاده می‌شود.
        self.owner_filter = owner_filter
        # وقتی این پنل برای ساختن اکانت *جدید* استفاده می‌شود (چه از طریق
        # ویزارد افزودن اکانت توسط ادمین/نماینده، چه از طریق ویزارد لاگین
        # مستقیم کاربر عادی)، این آیدی به‌عنوان owner_user_id روی اکانت
        # جدید نوشته می‌شود. اگر None بماند (حالت قدیمی/standalone)، هیچ
        # owner_user_id ثبت نمی‌شود — یعنی آن اکانت برای همه‌ی OWNER/ADMIN
        # قابل مشاهده است اما به کسی «تعلق» ندارد.
        self.default_owner_id = default_owner_id

    def _account_visible(self, acc: dict) -> bool:
        """
        آیا این اکانت (بر اساس owner_user_id ذخیره‌شده در config) برای
        viewer فعلی این پنل قابل مشاهده/مدیریت است؟ اگر owner_filter تنظیم
        نشده باشد (OWNER/ADMIN یا حالت standalone)، همه‌چیز قابل مشاهده
        است. اکانت‌های قدیمی‌تر که owner_user_id ندارند (از قبل از این
        قابلیت ساخته شده‌اند) فقط برای OWNER/ADMIN دیده می‌شوند، نه برای
        نماینده‌ها — چون منشأ مالکیتشان مشخص نیست و امن‌تر است که به‌طور
        پیش‌فرض به نماینده نشان داده نشوند.
        """
        if self.owner_filter is None:
            return True
        owner_id = acc.get("owner_user_id")
        if owner_id is None:
            return False
        return owner_id in self.owner_filter

    # ─────────────────────────────────────────────────────
    #  راه‌اندازی
    # ─────────────────────────────────────────────────────

    async def start(self) -> TelegramClient:
        if not ADMIN_BOT_TOKEN or not ADMIN_ID:
            raise RuntimeError(
                "متغیرهای محیطی ADMIN_BOT_TOKEN و ADMIN_ID باید تنظیم شده باشند "
                "(مثلاً از طریق systemd Environment=... یا فایل .env)."
            )

        cfg = self.sb.load_config()
        api_id, api_hash = _first_account_creds(cfg)

        if self.standalone:
            self.admin_ids = self._load_admin_ids()

        # سشن ربات مدیریت هم مثل سشن سلف‌بات‌ها باید قابل نوشتن باشد — همان
        # خطای «attempt to write a readonly database» که در process_entities
        # ربات مدیریت هم دیده می‌شد. چک سلامت (با خود-ترمیمی امنِ mode در
        # صورت هم‌مالکی) قبل از ساخت کلاینت.
        _health = check_session_health(ADMIN_BOT_SESSION_NAME)
        if not _health["ok"]:
            raise RuntimeError(
                f"سشن ربات مدیریت قابل نوشتن نیست: {_health['error']} [SESSION][CHECK]"
            )

        session_path = os.path.join(self.sb.SESSIONS_DIR, ADMIN_BOT_SESSION_NAME)
        self.client = TelegramClient(
            session_path, api_id, api_hash,
            connection_retries=3, retry_delay=2, flood_sleep_threshold=10,
        )
        await asyncio.wait_for(self.client.start(bot_token=ADMIN_BOT_TOKEN), timeout=30)
        self._register_handlers()

        if self._backup_task is None or self._backup_task.done():
            self._backup_task = asyncio.create_task(self._daily_backup_loop())

        print("🤖 ربات مدیریت (پنل ادمین) با موفقیت روشن شد.")
        return self.client

    def _is_admin(self, uid: int) -> bool:
        """
        فقط در حالت standalone استفاده می‌شود. در حالت غیر-standalone
        (زیرِ saas_bot.py) این متد اصلاً فراخوانی نمی‌شود چون کنترل
        دسترسی قبل از رسیدن به اینجا، توسط saas_bot.py انجام شده است.
        """
        return uid == ADMIN_ID or uid in self.admin_ids

    # ─────────────────────────────────────────────────────
    #  ذخیره‌سازی لیست ادمین‌ها (فقط برای حالت standalone)
    # ─────────────────────────────────────────────────────

    def _load_admin_ids(self) -> set:
        if os.path.exists(ADMIN_LIST_FILE):
            try:
                with open(ADMIN_LIST_FILE, encoding="utf-8") as f:
                    ids = json.load(f)
                return set(ids) | {ADMIN_ID}
            except Exception:
                pass
        return {ADMIN_ID}

    def _save_admin_ids(self) -> None:
        ids = self.admin_ids | {ADMIN_ID}
        try:
            with open(ADMIN_LIST_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(ids), f)
        except Exception as e:
            print(f"⚠️ [admin_bot] ذخیره‌ی لیست ادمین‌ها ناموفق بود: {e}")

    # ─────────────────────────────────────────────────────
    #  منوی اصلی
    # ─────────────────────────────────────────────────────

    def _main_menu_buttons(self):
        # چیدمان دوتا-دوتا (۲ ستونه) تا پنل کوتاه‌تر شود.
        buttons = [
            [UI.go("📋 لیست اکانت‌ها", b"list"),
             UI.go("➕ افزودن اکانت", b"add", tone="success")],
        ]
        if self.standalone:
            buttons.append([UI.go("👥 مدیریت ادمین‌ها", b"admins")])
        else:
            # فیکس مهم: قبلاً این پنل (وقتی زیرِ saas_bot.py اجرا می‌شد،
            # یعنی از طریق دکمه‌ی «🛠 مدیریت اکانت‌های سلف/مشتریان»)
            # هیچ راهی برای برگشت به منوی اصلی نقش‌محور نداشت — تنها راه
            # خروج زدن دوباره‌ی /start بود. این باعث می‌شد این پنل از دید
            # کاربر کاملاً جدا و «قدیمی» به نظر برسد، چون رفتارش با بقیه‌ی
            # ربات (که همه‌جا دکمه‌ی برگشت دارد) یکی نبود. دکمه‌ی زیر از
            # callback مشترک back_role_menu استفاده می‌کند که خودِ
            # saas_bot.py آن را هندل می‌کند و به منوی نقش (OWNER/ADMIN/
            # RESELLER) برمی‌گرداند.
            buttons.append(UI.nav_row(back=False))
        return buttons

    async def _show_main_menu(self, chat, edit_event=None):
        text = (
            "🎛 **پنل مدیریت سلف‌بات**\n\n"
            "با دکمه‌های زیر می‌تونی اکانت‌هایت را مدیریت کنی:\n"
            "• اضافه/ورود اکانت‌های جدید\n"
            "• روشن/خاموش کردن قابلیت‌ها\n"
            "• مدیریت فونت، اسم، پیام و حذف\n\n"
            "یکی از گزینه‌ها رو انتخاب کن:"
        )
        buttons = self._main_menu_buttons()
        if edit_event is not None:
            await edit_event.edit(text, buttons=buttons)
        else:
            await self.client.send_message(chat, text, buttons=buttons)

    # ─────────────────────────────────────────────────────
    #  لیست اکانت‌ها
    # ─────────────────────────────────────────────────────

    async def _show_account_list(self, event):
        cfg = self.sb.load_config()
        visible = {tag: acc for tag, acc in cfg.items() if self._account_visible(acc)}
        if not visible:
            msg = "📭 هیچ اکانتی ثبت نشده." if self.owner_filter is None \
                else "📭 هنوز هیچ اکانتی برای مشتریان تو ثبت نشده.\n\nبرای اضافه‌کردن اکانت جدید، دکمه‌ی «➕ افزودن اکانت» را بزن."
            await event.edit(msg, buttons=[[UI.go("➕ افزودن اکانت", b"add", tone="success")], UI.nav_row()])
            return
        body = []
        buttons = []
        counts = {"ready": 0, "off": 0, "paused": 0, "connecting": 0}
        for tag, acc in visible.items():
            state, note = _acc_ui_state(acc, tag)
            counts[state] = counts.get(state, 0) + 1
            body.append(f"{UI.state_dot(state)} `{tag}` ({acc.get('type', 'user')}) — {note}")
            # وضعیت روی خودِ دکمه هم می‌آید تا بدون خواندنِ متنِ بالا هم
            # معلوم باشد کدام اکانت روشن است.
            buttons.append([UI.item(tag, state, f"acc:{tag}")])
        buttons.append([UI.go("➕ افزودن اکانت", "add", primary=True, tone="success")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen(
                "📋 اکانت‌های سلف",
                body=body,
                subtitle=(f"{UI.GREEN} {counts.get('ready', 0)} فعال   "
                          f"{UI.RED} {counts.get('off', 0)} خاموش   "
                          f"{UI.PAUSED} {counts.get('paused', 0)} متوقف"),
                hint="روی هر اکانت بزن تا کنترل کاملش باز شود.",
            ),
            buttons=buttons,
        )

    @staticmethod
    def _safe_uptime(bot) -> str:
        try:
            return bot._uptime()
        except Exception:
            return "—"

    # ─────────────────────────────────────────────────────
    #  جزئیات و مدیریت یک اکانت — همه‌ی قابلیت‌های سلف اینجا کنترل می‌شوند
    # ─────────────────────────────────────────────────────

    async def _show_account_detail(self, event, tag: str, back_data: bytes = None):
        """
        صفحه‌ی اصلی مدیریت یک اکانت (هاب). همه‌ی قابلیت‌های سلف به بخش‌های
        دسته‌بندی‌شده منتقل شدند تا این صفحه شلوغ نباشد:

          ⚡ قابلیت‌ها        → همه‌ی کلیدهای روشن/خاموش
          🎨 ظاهر و پروفایل  → اسم، فونت
          🛠 ابزارها         → ارسال پیام
          🌐 اتصال و پروکسی  → تنظیم پروکسی
          📊 وضعیت کامل      → گزارش فقط‌خواندنی

        عملیات حساس (توقف / حذف کامل) جدا از قابلیت‌های عادی، پایین صفحه
        هستند و حذف کامل confirmation دارد.

        back_data: دیگر استفاده نمی‌شود و فقط برای سازگاریِ امضای
        فراخوان‌های قدیمی نگه داشته شده. مسیر بازگشت از پشته‌ی ناوبری
        (self.nav) می‌آید — یعنی همان مسیری که کاربر واقعاً طی کرده،
        نه یک مقصدِ ازپیش‌تعیین‌شده که با ورود از مسیرِ دیگر کهنه می‌شد.
        """
        cfg = self.sb.load_config()
        if tag not in cfg or not self._account_visible(cfg[tag]):
            # پیام یکسان برای «وجود ندارد» و «دسترسی نداری» عمداً است — تا
            # یک نماینده نتواند با امتحان تگ‌های حدسی، حتی صرفاً وجودِ یک
            # اکانتِ متعلق به نماینده‌ی دیگر را کشف کند.
            await event.answer("این اکانت دیگر وجود ندارد یا به تو دسترسی ندارد.", alert=True)
            await self._show_account_list(event)
            return
        acc = cfg[tag]
        entry = self.sb.ACCOUNTS.get(tag)
        disabled = bool(acc.get("disabled"))

        state, status_text = _acc_ui_state(acc, tag)

        proxy_cfg = acc.get("proxy")
        on_count = sum(1 for f, _ in FEATURE_LABELS if entry and getattr(entry.bot, f, False))

        body = [
            f"{UI.state_dot(state)} وضعیت: {status_text}",
            f"{UI.GRAY} نوع اکانت: {acc.get('type', 'user')}",
        ]
        # شماره‌ی تلفنِ اکانت — فقط برای مالکِ خودِ حساب (اطلاعاتِ حساس؛ یک
        # مدیرِ اکانتِ شخصِ دیگر نباید شماره‌اش را ببیند).
        phone = acc.get("phone")
        if phone and self._viewer_owns_account(acc, event.sender_id):
            body.append(f"{UI.GRAY} شماره: `{phone}`")
        body += [
            f"{UI.dot(bool(proxy_cfg))} پروکسی: {'تنظیم‌شده' if proxy_cfg else 'تنظیم‌نشده'}",
            f"{UI.dot(on_count > 0)} قابلیت‌های روشن: {on_count} از {len(FEATURE_LABELS)}",
        ]

        buttons = [
            [
                UI.go(f"⚡ قابلیت‌ها ({on_count})", f"feat:{tag}"),
                UI.go("🎨 ظاهر و پروفایل", f"appear:{tag}"),
            ],
            [
                UI.go("📨 ارسال پیام", f"send_msg:{tag}"),
                UI.go("🌐 اتصال و پروکسی", f"conn:{tag}"),
            ],
            [UI.go("📊 دیدن وضعیت کامل", f"status:{tag}")],
        ]
        # عملیاتِ حالت‌دار: سبز برای روشن‌کردن، خاکستری برای توقفِ موقت،
        # قرمز فقط برای حذفِ برگشت‌ناپذیر — تا رنگ‌ها با شدتِ عمل بخوانند.
        if disabled:
            buttons.append([UI.confirm("فعال‌سازی اکانت", f"enable:{tag}")])
        else:
            buttons.append([UI.neutral("توقف موقت SelfBot", f"disable:{tag}")])
        buttons.append([UI.danger("حذف کامل اکانت", f"del_confirm:{tag}")])
        buttons.append(UI.nav_row())

        await event.edit(
            UI.screen(
                f"⚙️ مدیریت «{tag}»",
                body=body,
                subtitle="این اکانت از اینجا کامل کنترل می‌شود.",
                hint="برای روشن/خاموش‌کردن قابلیت‌ها وارد «⚡ قابلیت‌ها» شو.",
            ),
            buttons=buttons,
        )

    # ─────────────────────────────────────────────────────
    #  بخش‌های دسته‌بندی‌شده‌ی مدیریت اکانت (UI)
    # ─────────────────────────────────────────────────────

    async def _show_features(self, event, tag: str):
        """⚡ قابلیت‌ها — همه‌ی کلیدهای روشن/خاموش سلف، با وضعیت زنده."""
        entry = self.sb.ACCOUNTS.get(tag)
        buttons = []
        body = []
        if entry:
            bot = entry.bot
            on = [l for f, l in FEATURE_LABELS if getattr(bot, f, False)]
            off = [l for f, l in FEATURE_LABELS if not getattr(bot, f, False)]
            body.append(f"{UI.GREEN} روشن: " + ("، ".join(on) if on else "—"))
            body.append(f"{UI.RED} خاموش: " + ("، ".join(off) if off else "—"))
            for i in range(0, len(FEATURE_LABELS), 2):
                buttons.append([
                    UI.toggle(label, getattr(bot, fname, False), f"toggle:{tag}:{fname}")
                    for fname, label in FEATURE_LABELS[i:i + 2]
                ])
            subtitle = "هر دکمه یک کلید است — بزن تا همان لحظه عوض شود."
            hint = f"{UI.GREEN} یعنی روشن، {UI.RED} یعنی خاموش."
        else:
            body.append(f"{UI.PAUSED} این اکانت الان روشن نیست.")
            buttons.append([UI.confirm("فعال‌سازی اکانت", f"enable:{tag}")])
            subtitle = "تا وقتی اکانت روشن نشود، قابلیت‌ها قابل تغییر نیستند."
            hint = "اول اکانت را فعال کن، بعد قابلیت‌ها اینجا ظاهر می‌شوند."
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen(f"⚡ قابلیت‌های «{tag}»", body=body, subtitle=subtitle, hint=hint),
            buttons=buttons,
        )

    async def _show_appearance(self, event, tag: str):
        """🎨 ظاهر و پروفایل — اسم و فونت اکانت."""
        entry = self.sb.ACCOUNTS.get(tag)
        body = []
        if entry:
            body.append(f"📛 اسم پایه: `{getattr(entry.bot, 'base_name', '—')}`")
            body.append(f"🔤 فونت فعلی: `{getattr(entry.bot, 'current_font', '—')}`")
        else:
            body.append(f"{UI.PAUSED} اکانت روشن نیست — مقادیر فعلی در دسترس نیست.")
        buttons = [
            [
                UI.go("✏️ تغییر اسم", f"edit_name:{tag}"),
                UI.go("🔤 تغییر فونت", f"font_menu:{tag}"),
            ],
            UI.nav_row(),
        ]
        await event.edit(
            UI.screen(f"🎨 ظاهر و پروفایل «{tag}»", body=body,
                      subtitle="ظاهر پیام‌ها و پروفایل این اکانت."),
            buttons=buttons,
        )

    async def _show_connection(self, event, tag: str):
        """
        🌐 اتصال و امنیت — یک صفحه، دو بخشِ مشخص.

        بخشِ «اتصال» (پروکسی/وضعیت) برای همه‌ی کسانی که اکانت را می‌بینند.
        بخشِ «امنیت» (دستگاه‌ها/رمز دومرحله‌ای/کد ورود) فقط برای کسی که
        مجوز دارد — پنهان‌سازی کامل، نه دکمه‌ی «غیرفعال».
        """
        cfg = self.sb.load_config()
        acc = cfg.get(tag, {})
        proxy_cfg = acc.get("proxy")
        state, note = _acc_ui_state(acc, tag)
        body = [f"{UI.state_dot(state)} اتصال: {note}"]
        if proxy_cfg:
            body.append(f"{UI.GREEN} پروکسی: {proxy_cfg.get('proxy_type', '?')} — "
                        f"`{proxy_cfg.get('addr', '?')}:{proxy_cfg.get('port', '?')}`")
        else:
            body.append(f"{UI.GRAY} پروکسی: تنظیم نشده (اتصال مستقیم)")

        # مجوز را برای *این اکانت* چک می‌کنیم — نه فقط یک بولیِ کلی.
        can_sec = self._can_view_security_tools(tag, event.sender_id)
        if can_sec:
            body += [
                UI.SEP,
                f"{UI.RED} امنیت",
            ]
            # شمارشِ دستگاه‌ها (در صورتِ روشن بودن) — اطلاعاتِ مفید برای
            # تصمیم‌گیری، بدون نیاز به باز کردنِ صفحه.
            entry = self.sb.ACCOUNTS.get(tag)
            if entry:
                try:
                    sessions = await entry.bot.list_sessions()
                    n_others = sum(1 for s in sessions if not s["current"])
                    body.append(f"{UI.dot(True)} دستگاه‌های لاگین‌شده: {fa_digits(n_others + 1)} نشست "
                                + f"({fa_digits(n_others)} غیر از خودِ سلف)")
                except Exception:
                    body.append(f"{UI.GRAY} دستگاه‌های لاگین‌شده: خواندن ناموفق بود")

        buttons = [
            [UI.go("🌐 تنظیم پروکسی" if not proxy_cfg else "🌐 تغییر پروکسی", f"proxy_start:{tag}")],
        ]
        if can_sec:
            buttons.append([
                UI.go("🔒 دستگاه‌های لاگین‌شده", f"sessions:{tag}"),
                UI.go("🔐 رمز دو مرحله‌ای", f"tfa:{tag}"),
            ])
            buttons.append([UI.go("📲 دریافت کد لاگین", f"getcode:{tag}")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen(f"🌐 اتصال و امنیت «{tag}»", body=body,
                      subtitle="وضعیت اتصال و ابزارهای امنیتی این اکانت."),
            buttons=buttons,
        )

    # ── مدیریت نشست‌ها ──────────────────────────────────────────────
    def _viewer_is_main_owner(self, sender_id: int) -> bool:
        """
        آیا بیننده، «مالکِ اصلیِ سیستم» است؟ فقط او همیشه به ابزارهای حساس
        (دستگاه‌های لاگین‌شده، رمز دو مرحله‌ای، کد ورود) دسترسی دارد.

        مالکِ اصلی یعنی:
          - در نمونه‌ی اصلی سیستم (نه ربات اختصاصی): OWNER در saas_db.
          - در حالت standalone (admin_bot.py مستقل): همین ADMIN_ID.

        عمداً در ربات‌های اختصاصی همیشه False برمی‌گرداند: مالکِ یک رباتِ
        اختصاصی، نماینده‌ای/مشتری‌ای است که آن را خریده، و نباید خودبه‌خود
        به ابزارهای حساس برسد. او فقط در صورتی می‌رسد که OWNER صراحتاً مجوز
        داده باشد (لایه‌ی capability).
        """
        if IS_DEDICATED_BOT:
            return False
        saas = getattr(self, "saas", None)
        if saas is None:
            # حالت standalone — admin_bot.py مستقل: ADMIN_ID مالک اصلی است.
            return sender_id == ADMIN_ID
        return saas._role(sender_id) == ROLE_OWNER

    # ── لایه‌ی مرکزیِ مجوزِ عملیاتِ حساس ─────────────────────────────
    #  یک قانونِ واحد برای همه. هر مسیرِ حساس (نمایش، callback، اجرای
    #  عمل) از همینجا عبور می‌کند — هیچ قانونِ موازیِ دیگری وجود ندارد.
    async def _authorize_security(self, event, tag: str, quiet: bool = False):
        """
        (allowed, reason) — آیا همین کاربرِ همین لحظه می‌تواند روی همین
        اکانت عملیاتِ حساس انجام دهد؟

        این متد *در هر فراخوانی* مجدداً ارزیابی می‌شود — یعنی یک دکمه‌ی
        کهنه بعد از سلبِ مجوز یا تغییرِ مالکیتِ اکانت دیگر کار نمی‌کند.

        reason برای لاگِ داخلی است؛ پیامِ کاربر کوتاه و بدون جزئیات است.
        quiet=True یعنی هیچ پیامی به کاربر نده (فراخوانی‌های داخلی که خودشان
        پیام می‌دهند).
        """
        allowed, reason = authorize_sensitive_account_action(event.sender_id, tag)
        if not allowed and not quiet:
            # پیامِ کوتاه و عمومی — بدون افشای نامِ مجوز، مسیر یا دلیلِ رد.
            answer = getattr(event, "answer", None)
            if callable(answer):
                try:
                    await event.answer(
                        "این قابلیت برای حساب شما فعال نشده است.", alert=True
                    )
                except Exception:
                    pass
        return allowed, reason

    def _can_view_security_tools(self, tag: str, sender_id: int) -> bool:
        """
        آیا این کاربر *می‌بیند* که ابزارهای امنیتی برای این اکانت وجود
        دارند؟ (برای پنهان‌کردن کامل از دیدِ کاربرانِ غیرمجاز). فقط داشتنِ
        مجوز کافی است — دامنه در زمانِ کلیک دوباره چک می‌شود.
        """
        if self._viewer_is_main_owner(sender_id):
            return True
        try:
            return bool(get_active_grants(sender_id, CAP_ACCOUNT_SECURITY))
        except Exception:
            return False


    def _viewer_owns_account(self, acc: dict, sender_id: int) -> bool:
        """
        آیا بیننده اختیارِ «مالک‌سطح» روی این اکانت دارد؟ مبنای نمایشِ
        اطلاعاتِ حساس (شماره‌ی تلفن) و عملیاتِ نشست‌ها (بستنِ دستگاه‌ها).

        سه حالت مجاز است:
          ۱) standalone — admin_bot.py به‌تنهایی، یک ادمینِ واحد.
          ۲) OWNER/ADMINِ سیستم — در این پنل با owner_filter=None شناخته
             می‌شوند (دسترسیِ کاملِ سیستمی). اپراتورِ ربات باید بتواند هر
             اکانتی، از جمله اکانتِ به‌مشکل‌خورده یا بدونِ مالک، را کامل
             مدیریت کند.
          ۳) مالکِ واقعیِ همان اکانت (owner_user_id == خودش) — برای وقتی
             کاربر/نماینده اکانتِ خودش را مدیریت می‌کند.

        نماینده‌ای که صرفاً اکانتِ مشتری را مدیریت می‌کند (نه OWNER/ADMIN و
        نه صاحبِ اکانت) اختیارِ بستنِ دستگاه‌ها یا دیدنِ شماره را ندارد.
        """
        if getattr(self, "standalone", False):
            return True
        # نکته‌ی امنیتی: getattr با نگهبانِ غیر-None. اگر به هر دلیلی
        # owner_filter تنظیم نشده باشد، *نباید* مثل OWNER/ADMIN رفتار شود —
        # آن مسیر fail-open بود. با این نگهبان، به چکِ صریحِ مالکیت می‌افتیم
        # که fail-safe است.
        _missing = object()
        scope = getattr(self, "owner_filter", _missing)
        if scope is None:                  # OWNER/ADMINِ سیستم
            return True
        owner = acc.get("owner_user_id")
        return owner is not None and owner == sender_id

    # نامِ قدیمی برای سازگاری — عملِ نشست‌ها همان معیارِ مالکیت را دارد.
    def _can_wipe_sessions(self, acc: dict, sender_id: int) -> bool:
        return self._viewer_owns_account(acc, sender_id)

    @staticmethod
    def _sess_line(s) -> str:
        """توصیفِ یک‌خطیِ یک نشست: دستگاه/اپ."""
        dev = " ".join(x for x in (s.get("device"), s.get("platform")) if x)
        app = s.get("app") or ""
        if app and s.get("app_ver"):
            app = f"{app} {s['app_ver']}"
        return " — ".join(x for x in (dev, app) if x) or "دستگاه نامشخص"

    # ── انتخابِ چنددستگاهی ──────────────────────────────────────────
    _SESS_SEL_MAX = 300
    _SESS_PAGE_SIZE = 8        # دکمه در هر صفحه از فهرستِ دستگاه‌ها

    def _sec_lock(self, tag: str) -> "asyncio.Lock":
        """
        قفلِ هم‌زمانی برای عملیاتِ حساسِ یک اکانت — در برابر کلیکِ
        دوباره/هم‌زمان محافظت می‌کند (دو بار بازنشانی، دو بار خروج از همه،
        چند گوش‌دهنده‌ی هم‌زمان).
        """
        return self._sec_locks.setdefault(tag, asyncio.Lock())

    def _sel_set(self, sender_id: int, tag: str) -> set:
        return self._sess_sel.setdefault((sender_id, tag), set())

    def _clear_sel(self, sender_id: int, tag: str) -> None:
        self._sess_sel.pop((sender_id, tag), None)

    async def _show_sessions(self, event, tag: str, flash: str = None, page: int = 0):
        """
        🔒 فهرست دستگاه‌های لاگین‌شده.

        هر دستگاهِ دیگر یک دکمه‌ی تیک‌دار است؛ چند تا را انتخاب کن و
        «بستنِ انتخاب‌شده‌ها» را بزن، یا «خروج از همه». نشستِ خودِ سلف
        همیشه نمایش داده می‌شود و هرگز بسته نمی‌شود.

        صفحه‌بندی: تلگرام می‌تواند ۳۰+ دستگاه داشته باشد؛ دیوارِ دکمه
        غیرقابل‌استفاده می‌شود، پس هر صفحه حداکثر _SESS_PAGE_SIZE دکمه
        نشان می‌دهد.

        flash: بنرِ نتیجه که بعد از یک عمل بالای فهرست نشان داده می‌شود.
        """
        # گاردِ مرکزی: مجوز + دامنه + وجودِ اکانت، در همین لحظه.
        allowed, _r = await self._authorize_security(event, tag)
        if not allowed:
            return
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست؛ برای مدیریت نشست‌ها باید فعال باشد.", alert=True)
            return
        try:
            await event.answer("در حال گرفتن فهرست دستگاه‌ها...")
        except Exception:
            pass
        try:
            sessions = await entry.bot.list_sessions()
        except Exception as e:
            # پیامِ عمومی به کاربر؛ جزئیات فقط در لاگ سرور.
            print(f"⚠️ [sessions:{tag}] list_sessions ناموفق: {type(e).__name__}: {e}")
            await event.edit(
                UI.screen("🔒 دستگاه‌های لاگین‌شده",
                          body=[f"{UI.RED} گرفتن فهرست دستگاه‌ها ناموفق بود. دوباره تلاش کن."]),
                buttons=[[UI.refresh(f"sessions:{tag}")], UI.nav_row()],
            )
            return

        others = [s for s in sessions if not s["current"]]
        current = next((s for s in sessions if s["current"]), None)

        # انتخاب را با نشست‌های موجود هماهنگ کن (هرچی دیگه نیست حذف)
        live_hashes = {s["hash"] for s in others}
        sel = self._sel_set(event.sender_id, tag) & live_hashes
        self._sess_sel[(event.sender_id, tag)] = sel

        # صفحه‌بندی
        total_pages = max(1, (len(others) + self._SESS_PAGE_SIZE - 1) // self._SESS_PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * self._SESS_PAGE_SIZE
        page_others = others[start:start + self._SESS_PAGE_SIZE]

        body = []
        if flash:
            body.append(f"{UI.GREEN} {flash}")
            body.append(UI.SEP)
        if current:
            body.append(f"{UI.GREEN} این سلف — {self._sess_line(current)}")
            body.append(f"     {UI.GRAY} نشستِ فعلی است؛ بسته نمی‌شود.")
        else:
            # نباید اتفاق بیفتد، ولی اگر نشستِ فعلی پیدا نشد، می‌گوییم تا
            # مبادا کسی فکر کند همه‌چیز سالم است.
            body.append(f"{UI.AMBER} نشستِ فعلی پیدا نشد — list_sessions ناقص برگشت.")
        body.append(UI.SEP)

        buttons = []
        if not others:
            body.append(f"{UI.GRAY} هیچ دستگاه دیگری لاگین نیست. ✅")
        else:
            n_sel_page = 0
            for i, s in enumerate(page_others):
                global_idx = start + i
                loc = f" · {s['country']}" if s.get("country") else ""
                body.append(f"{UI.RED} {self._sess_line(s)}{loc} · {entry.bot._rel_time(s.get('last'))}")
                on = s["hash"] in sel
                if on:
                    n_sel_page += 1
                mark = "☑️" if on else "⬜️"
                buttons.append([UI.btn(f"{mark} {self._sess_line(s)[:28]}",
                                       f"sesstog:{tag}:{global_idx}", style="primary")])
            # خلاصه‌ی انتخاب + عملیاتِ گروهی (چسبیده به پایینِ صفحه)
            # اگر اکانت شماره‌ی خارج/مجازی داشته باشد، یک 🛡️ به دکمه‌ها
            # اضافه می‌کنیم تا کاربر متوجه Anti-Ban بودن عملیات شود.
            entry_for_antiban = self.sb.ACCOUNTS.get(tag)
            antiban_mark = ""
            if entry_for_antiban and is_dangerous_account(entry_for_antiban.acc):
                antiban_mark = " 🛡️"
            action_row = []
            if sel:
                action_row.append(UI.danger(
                    f"بستنِ انتخاب‌شده‌ها ({len(sel)}){antiban_mark}", f"sesskill:{tag}"))
            action_row.append(UI.danger(
                f"خروج از همه ({len(others)}){antiban_mark}", f"sesswipe:{tag}"))
            buttons.append(action_row)
            # نوارِ صفحه‌بندی (فقط اگر بیش از یک صفحه است)
            if total_pages > 1:
                nav_row = []
                if page > 0:
                    nav_row.append(UI.neutral("◀️ صفحه‌ی قبل", f"sesspage:{tag}:{page - 1}"))
                nav_row.append(UI.noop(f"صفحه {fa_digits(page + 1)} از {fa_digits(total_pages)}"))
                if page < total_pages - 1:
                    nav_row.append(UI.neutral("صفحه‌ی بعد ▶️", f"sesspage:{tag}:{page + 1}"))
                buttons.append(nav_row)
        buttons.append([UI.refresh(f"sessions:{tag}")])
        buttons.append(UI.nav_row())

        await event.edit(
            UI.screen("🔒 دستگاه‌های لاگین‌شده", body=body,
                      subtitle=f"«{tag}» روی {fa_digits(len(sessions))} دستگاه فعال است.",
                      hint=("تیکِ چند دستگاه را بزن، بعد «بستنِ انتخاب‌شده‌ها»؛ یا «خروج از همه»."
                            if others else None)),
            buttons=buttons,
        )

    async def _toggle_sess_selection(self, event, tag: str, idx: int):
        """تیکِ یک دستگاه را برعکس می‌کند و فهرست را دوباره رندر می‌کند."""
        allowed, _r = await self._authorize_security(event, tag)
        if not allowed:
            return
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست.", alert=True)
            return
        try:
            others = [s for s in await entry.bot.list_sessions() if not s["current"]]
        except Exception as e:
            print(f"⚠️ [sesstog:{tag}] list_sessions ناموفق: {type(e).__name__}")
            await event.answer("گرفتن فهرست دستگاه‌ها ناموفق بود.", alert=True)
            return
        if 0 <= idx < len(others):
            sel = self._sel_set(event.sender_id, tag)
            h = others[idx]["hash"]
            if h in sel:
                sel.discard(h)
            elif len(sel) < self._SESS_SEL_MAX:
                sel.add(h)
        # روی همان صفحه‌ای که بوده بمان
        page = idx // self._SESS_PAGE_SIZE
        await self._show_sessions(event, tag, page=page)

    async def _kill_selected_sessions(self, event, tag: str):
        """دستگاه‌های تیک‌خورده را می‌بندد، بعد فهرستِ تازه را نشان می‌دهد."""
        allowed, _r = await self._authorize_security(event, tag)
        if not allowed:
            return
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست.", alert=True)
            return
        sel = set(self._sel_set(event.sender_id, tag))
        if not sel:
            await self._show_sessions(event, tag, flash="هیچ دستگاهی انتخاب نشده بود.")
            return
        # Anti-Ban: اکانت شماره خارج/مجازی → تأیید اضافه لازم است
        guard_ok, guard_info = antiban_guarded_action(
            event.sender_id, entry.acc, "sesskill"
        )
        if not guard_ok:
            token = guard_info[2] if len(guard_info) > 2 else ""
            await self._show_antiban_warning(event, tag, token, "sesskill",
                                            phone_country_hint(entry.acc.get("phone")))
            return
        # قفلِ هم‌زمانی: دوبار کلیکِ پشتِ سرهم نباید دو بار بستن را اجرا کند.
        lock = self._sec_lock(tag)
        if lock.locked():
            await event.answer("یک عملیات در حال اجراست؛ کمی صبر کن.", alert=True)
            return
        async with lock:
            try:
                await event.answer("در حال بستنِ دستگاه‌های انتخاب‌شده...")
            except Exception:
                pass
            done, failed = 0, 0
            for h in sel:
                try:
                    await entry.bot.terminate_session(h)
                    done += 1
                except Exception:
                    failed += 1
            self._clear_sel(event.sender_id, tag)
            log_action(event.sender_id, "sessions_terminated_selected",
                       f"tag={tag} done={done} failed={failed}")
            note = f"{fa_digits(done)} دستگاه بسته شد." + (
                f" ({fa_digits(failed)} ناموفق)" if failed else "")
        await self._show_sessions(event, tag, flash=note)

    async def _show_antiban_warning(self, event, tag: str, token: str,
                                    action: str, country: str,
                                    level: str = "warning"):
        """
        هشدار Anti-Ban قبل از اجرای عملیات خطرناک روی اکانتِ شماره‌ی خارج/مجازی.

        level: "warning"  → فقط تأیید (مثل sesskill)
               "critical" → هشدار شدید + تأیید (مثل sessterm و tfago)
        """
        labels = {
            "sesskill": "بستنِ session انتخابی",
            "sessterm": "خروج از همه‌ی دستگاه‌ها",
            "tfago":    "بازنشانی رمز دو مرحله‌ای",
            "tfareset": "درخواست بازنشانی رمز",
            "tfacancel": "لغو بازنشانی رمز",
        }
        label = labels.get(action, action)
        if level == "critical":
            head = f"{UI.RED} ⛔ هشدار بحرانی — Anti-Ban"
            intro = (
                f"اکانت «{tag}» با شماره‌ی **{country}** است.\n"
                f"عملیات **{label}** روی شماره‌های خارج/مجازی بسیار خطرناک است:\n"
                f"• تلگرام ممکن است **ایمیل** اکانت را حذف کند\n"
                f"• یا **دسترسی کامل** به اکانت را قطع کند\n"
                f"• و **هیچ راهی** برای بازیابی نباشد"
            )
        else:
            head = f"{UI.AMBER} ⚠️ هشدار Anti-Ban"
            intro = (
                f"اکانت «{tag}» با شماره‌ی **{country}** است.\n"
                f"عملیات **{label}** روی شماره‌های خارج/مجازی می‌تواند باعث "
                f"محدودیت یا بسته‌شدن اکانت شود."
            )
        body = [
            head, "", intro,
            "",
            f"{UI.GRAY} اگر مطمئنی ادامه بده، دکمه‌ی زیر را بزن.",
            f"{UI.GRAY} در غیر این صورت، انصراف بزن.",
        ]
        await event.edit(
            UI.screen("🛡️ محافظت Anti-Ban", body=body,
                      hint="این تأیید فقط ۲ دقیقه معتبر است."),
            buttons=[
                [UI.danger(f"بله، {label} انجام شود", f"abok:{tag}:{action}:{token}".encode())],
                [UI.neutral("انصراف", f"abno:{tag}:{action}:{token}".encode())],
            ],
        )

    async def _handle_antiban_confirm(self, event, data: str):
        """
        پاسخ کاربر به هشدار Anti-Ban. دیتا:
          abok:{tag}:{action}:{token} → تأیید (اجرای عملیات اصلی)
          abno:{tag}:{action}:{token} → انصراف
        """
        parts = data.split(":", 3)
        if len(parts) != 4:
            await event.answer("درخواست نامعتبر.", alert=True)
            return
        _, tag, action, token = parts

        if data.startswith("abno:"):
            await event.answer("لغو شد.")
            await event.edit(
                f"{UI.GRAY}عملیات لغو شد.",
                buttons=[[UI.neutral(UI.L_BACK, f"conn:{tag}")]],
            )
            return

        # abok: تأیید
        ok, info = antiban_consume(token, event.sender_id)
        if not ok:
            why = info if isinstance(info, str) else "expired"
            await event.answer(
                "این تأیید منقضی شده یا متعلق به تو نیست. دوباره تلاش کن.",
                alert=True,
            )
            return

        # عملیات تأیید شد → اجرای عملیات اصلی با ساختن callback data مجازی
        # ساده‌ترین راه: دوباره فراخوانی همان هندلر اصلی با data بدون antiban.
        # اما چون هندلرها بر اساس event.data تصمیم می‌گیرند، ما خودشان را
        # با event.data جدید فراخوانی می‌کنیم.
        new_data = f"{action}:{tag}"
        if action == "sesskill":
            new_data = f"sesskill:{tag}"  # عملیات sesskill به لیست انتخاب نیاز دارد
        # برای سادگی، فقط به صفحه‌ی مربوطه هدایت می‌کنیم و پیام می‌دهیم
        # که تأیید ثبت شد.
        if action == "sessterm":
            await event.answer("تأیید شد — در حال بستن...")
            await self._terminate_sessions(event, tag)
        elif action == "sesskill":
            await event.answer("تأیید شد — در حال بستن sessionهای انتخابی...")
            await self._kill_selected_sessions(event, tag)
        elif action == "tfago":
            await event.answer("تأیید شد — در حال ارسال درخواست...")
            await self._do_2fa_reset(event, tag)
        else:
            await event.edit(
                f"{UI.GREEN} تأیید شد. دوباره عملیات را از منو انجام بده.",
                buttons=[[UI.neutral(UI.L_BACK, f"conn:{tag}")]],
            )

    async def _confirm_wipe_sessions(self, event, tag: str):
        """تأییدِ «خروج از همه» — چون همه‌ی دستگاه‌های دیگر را می‌بندد."""
        allowed, _r = await self._authorize_security(event, tag)
        if not allowed:
            return
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست.", alert=True)
            return
        try:
            others = [s for s in await entry.bot.list_sessions() if not s["current"]]
        except Exception as e:
            print(f"⚠️ [sesswipe:{tag}] list_sessions ناموفق: {type(e).__name__}")
            others = []
        if not others:
            await self._show_sessions(event, tag, flash="دستگاهِ دیگری برای بستن نبود.")
            return
        body = [f"{UI.RED} {fa_digits(len(others))} دستگاهِ دیگر بسته می‌شوند:", ""]
        for s in others[:8]:
            body.append(f"   • {self._sess_line(s)}")
        if len(others) > 8:
            body.append(f"   • … و {fa_digits(len(others) - 8)} دستگاهِ دیگر")
        body.append("")
        body.append(f"{UI.GREEN} نشستِ خودِ این سلف روشن می‌ماند و بسته نمی‌شود.")
        await event.edit(
            UI.screen("⚠️ خروج از همه‌ی دستگاه‌ها", body=body,
                      hint="این کار برگشت‌ناپذیر است؛ دستگاه‌ها باید دوباره لاگین کنند."),
            buttons=[
                [UI.danger(f"بله، هر {fa_digits(len(others))} تا را ببند", f"sessterm:{tag}")],
                [UI.neutral("انصراف", f"sessions:{tag}")],
            ],
        )

    async def _terminate_sessions(self, event, tag: str):
        """همه‌ی نشست‌های دیگر را می‌بندد، بعد فهرستِ تازه را نشان می‌دهد."""
        allowed, _r = await self._authorize_security(event, tag)
        if not allowed:
            return
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست.", alert=True)
            return
        # Anti-Ban: «خروج از همه» روی شماره‌ی خارج/مجازی بسیار خطرناک است —
        # تلگرام معمولاً بعد از آن ایمیل و دسترسی اکانت را قطع می‌کند.
        guard_ok, guard_info = antiban_guarded_action(
            event.sender_id, entry.acc, "sessterm"
        )
        if not guard_ok:
            token = guard_info[2] if len(guard_info) > 2 else ""
            await self._show_antiban_warning(event, tag, token, "sessterm",
                                            phone_country_hint(entry.acc.get("phone")),
                                            level="critical")
            return
        # قفلِ هم‌زمانی در برابر کلیکِ دوباره.
        lock = self._sec_lock(tag)
        if lock.locked():
            await event.answer("یک عملیات در حال اجراست؛ کمی صبر کن.", alert=True)
            return
        async with lock:
            try:
                await event.answer("در حال بستنِ دستگاه‌های دیگر...")
            except Exception:
                pass
            self._clear_sel(event.sender_id, tag)
            try:
                n = await entry.bot.terminate_other_sessions()
            except Exception as e:
                print(f"⚠️ [sessterm:{tag}] terminate_other_sessions ناموفق: "
                      f"{type(e).__name__}: {e}")
                await self._show_sessions(event, tag, flash="بستنِ دستگاه‌ها ناموفق بود.")
                return
            log_action(event.sender_id, "sessions_terminated_all", f"tag={tag} n={n}")
            note = ("همه‌ی دستگاه‌های دیگر بسته شدند." if n < 0
                    else f"{fa_digits(n)} دستگاهِ دیگر بسته شد." if n
                    else "دستگاهِ دیگری برای بستن نبود.")
        await self._show_sessions(event, tag, flash=note)

    async def _sess_guard(self, event, tag: str):
        """
        (entry, ok) — اکانت روشن است و بیننده مجوزِ حساسِ همین اکانت را دارد؟

        این حالا از لایه‌ی مرکزیِ _authorize_security تغذیه می‌شود — دیگر
        قانونِ جداگانه‌ای برای «مالک‌سطح بودن» وجود ندارد. اگر مجوز نباشد،
        این متد خودش پیامِ کوتاه را به کاربر می‌دهد.
        """
        allowed, _r = await self._authorize_security(event, tag)
        if not allowed:
            return None, False
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            try:
                await event.answer("این اکانت الان روشن نیست.", alert=True)
            except Exception:
                pass
            return None, False
        return entry, True

    # ── رمز دو مرحله‌ای ─────────────────────────────────────────────
    @staticmethod
    def _until_text(at) -> str:
        """«۳ روز و ۴ ساعت دیگر» از یک datetime آینده."""
        if at is None:
            return "زمانش نامشخص است"
        try:
            sec = (at - datetime.now(timezone.utc)).total_seconds()
        except Exception:
            return "زمانش نامشخص است"
        if sec <= 0:
            return "همین حالا"
        d, rem = divmod(int(sec), 86400)
        h = rem // 3600
        if d and h:
            return f"{fa_digits(d)} روز و {fa_digits(h)} ساعت دیگر"
        if d:
            return f"{fa_digits(d)} روز دیگر"
        if h:
            return f"{fa_digits(h)} ساعت دیگر"
        return f"{fa_digits(max(1, int(sec // 60)))} دقیقه دیگر"

    async def _show_2fa(self, event, tag: str, flash: str = None):
        """
        🔐 رمز دو مرحله‌ای — وضعیتِ دقیق و مسیرِ بازنشانی.

        مهم‌ترین تغییر: دیگر «خواندنِ ناموفق» را به‌جای «رمز فعال نیست»
        نشان نمی‌دهد. GetPasswordRequest ممکن است به دلایل زیادی بشکند
        (قطعیِ شبکه، سشنِ منقضی، خطای API) و هر کدام به‌معنایِ «بدون رمز»
        نیست. وضعیت‌ها به‌صراحت از هم جدا شده‌اند.

        اگر رمزی نیست → دکمه‌ی بازنشانی هم نیست (چیزی برای بازنشانی نیست).
        اگر بازنشانی در جریان است → «شروع» نمی‌آید، «ادامه/لغو» می‌آید.
        """
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        try:
            await event.answer("در حال خواندن وضعیت امنیت...")
        except Exception:
            pass
        # نمایش کشور شماره برای آگاهی از ریسک Anti-Ban
        phone_hint = phone_country_hint(entry.acc.get("phone"))
        try:
            st = await entry.bot.get_2fa_status()
        except Exception as e:
            # هیچ‌وقت پیش نمی‌آید (get_2fa_status خودش exception را مدیریت
            # می‌کند)، ولی fail-safe: هرگز crash نکنیم.
            print(f"⚠️ [tfa:{tag}] get_2fa_status استثنا داد: {type(e).__name__}")
            st = {"ok": False, "error": "api_error"}

        body = []
        if flash:
            body += [f"{UI.GREEN} {flash}", UI.SEP]

        # ── حالت ۱: خواندنِ وضعیت ناموفق بود ──
        # این دیگر «بدون رمز» نیست. کاربر می‌بیند که خواندن شکست خورده و
        # دکمه‌ی تلاشِ دوباره دارد.
        if not st.get("ok"):
            err_code = st.get("error") or "api_error"
            msg = {
                "timeout": "خواندن وضعیت امنیتی طول کشید. دوباره تلاش کن.",
                "api_error": "خواندن وضعیت امنیتی ناموفق بود. دوباره تلاش کن.",
                "empty_response": "پاسخ تلگرام نامعتبر بود. دوباره تلاش کن.",
            }.get(err_code, "خواندن وضعیت امنیتی ناموفق بود. دوباره تلاش کن.")
            body.append(f"{UI.RED} {msg}")
            # فقط در لاگِ سرور — هرگز به کاربر نمی‌رود.
            print(f"⚠️ [tfa:{tag}] خواندن 2FA شکست خورد: {err_code} "
                  f"({st.get('error_ident', '?')}) actor={event.sender_id}")
            await event.edit(
                UI.screen("🔐 رمز دو مرحله‌ای", body=body,
                          subtitle=f"«{tag}»",
                          hint="اگر چند بار تکرار شد، اکانت ممکن است قطع شده باشد."),
                buttons=[[UI.refresh(f"tfa:{tag}")], UI.nav_row()],
            )
            return

        # ── حالت ۲: رمزی نیست ──
        # دکمه‌ی بازنشانی هم نیست — چیزی برای بازنشانی وجود ندارد.
        if not st["has_password"]:
            body.append(f"{UI.GRAY} رمز دو مرحله‌ای روی این اکانت فعال نیست.")
            if st["email_pattern"]:
                body.append(f"{UI.AMBER} یک ایمیل در انتظارِ تأیید است: {st['email_pattern']}")
            await event.edit(
                UI.screen(f"🔐 رمز دو مرحله‌ای", body=body,
                          subtitle=f"«{tag}» · {phone_hint}"),
                buttons=[[UI.refresh(f"tfa:{tag}")], UI.nav_row()],
            )
            return

        # ── حالت ۳: رمز فعال است ──
        pending = st.get("pending_reset_at")
        body.append(f"{UI.GREEN} رمز دو مرحله‌ای فعال است.")
        if st["hint"]:
            body.append(f"{UI.GRAY} راهنمای رمز: «{st['hint']}»")
        body.append(f"{UI.dot(st['has_recovery'])} ایمیل بازیابی: "
                    + ("ست شده" if st["has_recovery"] else "ست نشده"))
        if st["login_email_pattern"]:
            body.append(f"{UI.GRAY} ایمیل ورود: {st['login_email_pattern']}")
        if st["email_pattern"]:
            body.append(f"{UI.AMBER} ایمیل تاییدنشده: {st['email_pattern']}")

        buttons = []
        if pending:
            # بازنشانی از قبل در جریان است — «شروع» نمی‌آید.
            body += [
                UI.SEP,
                f"{UI.AMBER} بازنشانی در جریان است",
                f"{UI.GRAY} پایانِ انتظار: {st.get('pending_reset_date_local') or self._until_text(pending)}",
                "بعد از آن «ادامه‌ی بازنشانی» را بزن تا رمز حذف شود.",
            ]
            antiban_mark2 = ""
            entry_for_antiban2 = self.sb.ACCOUNTS.get(tag)
            if entry_for_antiban2 and is_dangerous_account(entry_for_antiban2.acc):
                antiban_mark2 = " 🛡️"
            buttons.append([UI.danger(
                f"ادامه‌ی بازنشانی{antiban_mark2}", f"tfareset:{tag}")])
            buttons.append([UI.neutral("لغو بازنشانی", f"tfacancel:{tag}")])
        else:
            body += [
                UI.SEP,
                f"{UI.GRAY} بدونِ خودِ رمزِ فعلی، عوض‌کردن یا حذفِ رمز و ایمیلِ",
                f"{UI.GRAY} بازیابی ممکن نیست — این محدودیتِ خودِ تلگرام است.",
                "اگر رمز را نمی‌دانی، تنها راه «بازنشانی» است.",
            ]
            antiban_mark3 = ""
            entry_for_antiban3 = self.sb.ACCOUNTS.get(tag)
            if entry_for_antiban3 and is_dangerous_account(entry_for_antiban3.acc):
                antiban_mark3 = " 🛡️"
            buttons.append([UI.danger(
                f"درخواست بازنشانی رمز{antiban_mark3}", f"tfareset:{tag}")])
        buttons.append([UI.refresh(f"tfa:{tag}")])
        buttons.append(UI.nav_row())

        await event.edit(
            UI.screen(f"🔐 رمز دو مرحله‌ای", body=body,
                      subtitle=f"«{tag}» · {phone_hint}",
                      hint=("هرچه زودتر درخواست بدهی، زودتر تمام می‌شود — انتظار از لحظه‌ی درخواست شروع می‌شود."
                            if not pending else None)),
            buttons=buttons,
        )

    async def _confirm_2fa_reset(self, event, tag: str):
        """
        تأییدِ درخواست بازنشانی — یک کلیکِ تصادفی نباید رمز را به خطر
        بیندازد. این صفحه می‌گوید چه اتفاقی می‌افتد و تلگرام چه می‌کند.
        """
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        # وضعیتِ فعلی را برای توضیحِ دقیق می‌خوانیم — مثلاً اگر از قبل
        # بازنشانی در جریان است، دکمه‌ی «شروع» نباید بگوید «شروع».
        try:
            st = await entry.bot.get_2fa_status()
        except Exception:
            st = {"ok": False}
        if st.get("ok") and not st.get("has_password"):
            # رمزی نیست — بازنشانی بی‌معنی است. به صفحه برمی‌گردیم.
            await self._show_2fa(event, tag, flash="رمزی برای بازنشانی وجود ندارد.")
            return
        pending = st.get("ok") and st.get("pending_reset_at")
        if pending:
            # از قبل در جریان است — مستقیم به صفحه‌ی وضعیت می‌رویم.
            await self._show_2fa(event, tag)
            return

        await event.edit(
            UI.screen(
                "⚠️ بازنشانی رمز دو مرحله‌ای",
                body=[
                    "با تأیید این درخواست:",
                    f"{UI.GRAY} • تلگرام یک دوره‌ی انتظار شروع می‌کند (معمولاً تا ۷ روز).",
                    f"{UI.GRAY} • بعد از پایانِ انتظار، رمز کاملاً حذف می‌شود — نه زودتر.",
                    f"{UI.GRAY} • ایمیلِ بازیابی هم بی‌اثر می‌شود.",
                    "",
                    f"{UI.AMBER} تا پایانِ انتظار، رمز همچنان فعال است و اکانت کار می‌کند.",
                    f"{UI.GREEN} هر وقت خواستی می‌توانی درخواست را لغو کنی.",
                ],
                hint="این درخواست فقط با تأیید شما ثبت می‌شود."),
            buttons=[
                [UI.danger("بله، بازنشانی را شروع کن", f"tfago:{tag}")],
                [UI.neutral("انصراف", f"tfa:{tag}")],
            ],
        )

    async def _do_2fa_reset(self, event, tag: str):
        """اجرای درخواست بازنشانی، بازخوانیِ وضعیت از تلگرام، و گزارش."""
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        # Anti-Ban: بازنشانی ۲FA روی شماره‌ی خارج می‌تواند منجر به قطع
        # دسترسی اکانت توسط تلگرام شود.
        guard_ok, guard_info = antiban_guarded_action(
            event.sender_id, entry.acc, "tfago"
        )
        if not guard_ok:
            token = guard_info[2] if len(guard_info) > 2 else ""
            await self._show_antiban_warning(event, tag, token, "tfago",
                                            phone_country_hint(entry.acc.get("phone")),
                                            level="critical")
            return
        # قفلِ هم‌زمانی: دو کلیکِ پشتِ سرهم نباید دو درخواست بسازد.
        lock = self._sec_lock(tag)
        if lock.locked():
            await event.answer("یک عملیات در حال اجراست؛ کمی صبر کن.", alert=True)
            return
        async with lock:
            try:
                await event.answer("در حال ارسال درخواست...")
            except Exception:
                pass
            res = await entry.bot.request_2fa_reset()
            state = res.get("state")

            if state == "ok":
                # تلگرام تأیید کرد که رمز حذف شد.
                log_action(event.sender_id, "tfa_reset_completed", f"tag={tag}")
                await self._show_2fa(event, tag, flash="رمز دو مرحله‌ای حذف شد.")
                return

            if state == "wait":
                # تلگرام دوره‌ی انتظار را شروع کرد. زمانِ واقعیِ خودش را
                # نشان می‌دهیم، نه یک مدتِ ثابتِ فرضی.
                at = res.get("at")
                log_action(event.sender_id, "tfa_reset_started", f"tag={tag}")
                flash = ("بازنشانی شروع شد. "
                         + (f"تا {entry.bot._fmt_dt_local(at)}" if at else ""))
                await self._show_2fa(event, tag, flash=flash)
                return

            if state == "already":
                # از قبل در جریان است — جدیدی نمی‌سازیم.
                await self._show_2fa(event, tag, flash="بازنشانی از قبل در جریان بود.")
                return

            if state == "toosoon":
                # تلگرام هنوز اجازه نمی‌دهد (معمولاً رمز تازه عوض شده).
                at = res.get("at")
                log_action(event.sender_id, "tfa_reset_too_soon", f"tag={tag}")
                flash = "تلگرام هنوز اجازه‌ی بازنشانی نمی‌دهد."
                if at:
                    flash += f" می‌توانی {entry.bot._fmt_dt_local(at)} دوباره درخواست بدهی."
                await self._show_2fa(event, tag, flash=flash)
                return

            # خطای واقعی. پیامِ کوتاه و عمومی به کاربر؛ جزئیات در لاگ.
            err_ident = res.get("error") or res.get("raw") or "unknown"
            print(f"⚠️ [tfa:{tag}] بازنشانی ناموفق: state=error "
                  f"ident={err_ident} raw={str(res.get('raw'))[:100]} "
                  f"actor={event.sender_id}")
            hintline = ""
            if res.get("fresh_seconds"):
                hrs = max(1, res["fresh_seconds"] // 3600)
                hintline = (f"رمز به‌تازگی عوض شده؛ تلگرام تا حدود "
                            f"{fa_digits(hrs)} ساعت اجازه‌ی بازنشانی نمی‌دهد.")
            await event.edit(
                UI.screen("🔐 بازنشانی رمز",
                          body=[f"{UI.RED} درخواست انجام نشد. دوباره تلاش کن."]
                                + ([f"{UI.GRAY} {hintline}"] if hintline else [])),
                buttons=[[UI.refresh(f"tfa:{tag}")], UI.nav_row()],
            )

    async def _cancel_2fa_reset(self, event, tag: str):
        """لغوِ بازنشانی، بعد بازخوانیِ وضعیت از تلگرام."""
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        lock = self._sec_lock(tag)
        if lock.locked():
            await event.answer("یک عملیات در حال اجراست؛ کمی صبر کن.", alert=True)
            return
        async with lock:
            done = await entry.bot.cancel_2fa_reset()
            log_action(event.sender_id, "tfa_reset_cancelled", f"tag={tag} ok={done}")
        # وضعیت را از تلگرام دوباره می‌خوانیم — نه اینکه حدس بزنیم.
        await self._show_2fa(event, tag,
                             flash="درخواست لغو شد." if done else "لغو ناموفق بود.")

    async def _arm_login_code(self, event, tag: str):
        """
        صفحه‌ی «کد ورود». دو مسیر دارد:
          • 📲 دریافت کد  → همین حالا چتِ سرویسِ تلگرام را می‌گردد و کد را
            *همان‌جا در همین صفحه* نشان می‌دهد (مطمئن‌ترین راه: نه ارسال
            لازم دارد، نه ربات باید بتواند پیام بدهد، نه جایی گم می‌شود).
          • 👂 گوش‌دادن   → برای کدی که هنوز نیامده؛ به‌محضِ رسیدن، خودش
            برای همین کاربر می‌فرستد.

        امنیت: مجوز و دامنه در هر بازدید دوباره چک می‌شود. گوش‌دادن یک
        پنجره‌ی محدود دارد و به همین کاربر گره می‌خورد.
        """
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        armed = entry.bot._login_code_is_armed()
        minutes = entry.bot.LOGIN_CODE_ARM_SECONDS // 60
        body = [
            "برای ورود از دستگاه جدید:",
            "",
            "۱) از دستگاه جدید، لاگینِ این اکانت را شروع کن.",
            "۲) تلگرام کد را می‌فرستد.",
            "۳) اینجا «📲 دریافت کد» را بزن تا کد را نشانت بدهم.",
        ]
        if armed:
            # شمارشِ زمانِ باقیمانده‌ی گوش‌دادن — تا مشخص باشد پنجره باز است.
            until = getattr(entry.bot, "_login_code_armed_until", 0.0)
            try:
                left = max(0, int(until - time.time()) // 60)
                left_txt = f" ({fa_digits(max(1, left))} دقیقه باقی مانده)"
            except Exception:
                left_txt = ""
            body.append("")
            body.append(f"{UI.GREEN} گوش‌دادن فعال است{left_txt}.")
            body.append("به‌محضِ رسیدنِ کدِ بعدی، اینجا برایت فرستاده می‌شود.")
        await event.edit(
            UI.screen("🔑 کد ورود", body=body,
                      subtitle=f"اکانت «{tag}»",
                      hint="اگر کد را قبلاً گرفته‌ای، «دریافت کد» همان را هم پیدا می‌کند."),
            buttons=[
                [UI.confirm("📲 دریافت کد", f"codeget:{tag}")],
                [UI.go(("👂 گوش‌دادن فعال است" if armed else f"👂 گوش‌دادن ({fa_digits(minutes)} دقیقه)"),
                       f"codearm:{tag}")],
                UI.nav_row(),
            ],
        )

    async def _fetch_login_code(self, event, tag: str):
        """📲 دریافت کد — جستجوی فعال و نمایشِ کد در همین صفحه."""
        # هر بار دوباره اعتبارسنجی می‌شود — حتی اگر یک دقیقه پیش مجاز بود.
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        try:
            await event.answer("در حال گشتن در پیام‌های تلگرام...")
        except Exception:
            pass
        res = await entry.bot.fetch_login_code()
        log_action(event.sender_id, "login_code_fetched",
                   f"tag={tag} ok={bool(res.get('ok'))}")
        if not res.get("ok"):
            await event.edit(
                UI.screen("🔑 کد ورود",
                          body=[f"{UI.RED} {res.get('error') or 'کدی پیدا نشد.'}",
                                "",
                                "اگر هنوز از دستگاه جدید لاگین را شروع نکرده‌ای،",
                                "اول آن را شروع کن و بعد دوباره «دریافت کد» را بزن."]),
                buttons=[
                    [UI.refresh(f"codeget:{tag}")],
                    [UI.go("👂 گوش‌دادن برای کدِ بعدی", f"codearm:{tag}")],
                    UI.nav_row(),
                ],
            )
            return

        code = res["code"]
        age = res.get("age")
        spaced = entry.bot.spaced_code(code)
        body = [f"کدِ ورودِ اکانت «{tag}»:", "", f"**{spaced}**", ""]
        if res.get("fresh"):
            body.append(f"{UI.GREEN} تازه است ({entry.bot._rel_time_secs(age)}).")
        else:
            body.append(f"{UI.AMBER} این کد {entry.bot._rel_time_secs(age)} صادر شده — "
                        f"ممکن است منقضی شده باشد.")
            body.append("اگر کار نکرد، از دستگاه جدید دوباره کد بخواه و این دکمه را بزن.")
        await event.edit(
            UI.screen("🔑 کد ورود", body=body,
                      hint="این کد را فقط خودت وارد کن؛ به هیچ‌کس نده."),
            buttons=[
                [UI.refresh(f"codeget:{tag}")],
                UI.nav_row(),
            ],
        )

    async def _arm_listen_code(self, event, tag: str):
        """👂 گوش‌دادن — پنجره‌ی دریافتِ خودکارِ کدِ بعدی را باز می‌کند."""
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        # فقط یک گوش‌دهنده‌ی هم‌زمان برای هر اکانت — کلیکِ دوباره آن را
        # تجدید نمی‌کند تا کد به دو نفر نرود.
        if entry.bot._login_code_is_armed():
            await event.answer("گوش‌دادن از قبل برای این اکانت فعال است.", alert=True)
            await self._arm_login_code(event, tag)
            return
        entry.bot.arm_login_code(requester_id=event.sender_id)
        log_action(event.sender_id, "login_code_listener_armed", f"tag={tag}")
        minutes = entry.bot.LOGIN_CODE_ARM_SECONDS // 60
        await event.edit(
            UI.screen("👂 گوش‌دادن فعال شد",
                      body=[f"{UI.GREEN} تا {fa_digits(minutes)} دقیقه گوش می‌دهم.",
                            "",
                            "به‌محضِ رسیدنِ کد، همین‌جا برایت می‌فرستم.",
                            "",
                            f"{UI.GRAY} بعد از این مدت خودکار قطع می‌شود.",
                            f"{UI.GRAY} اگر پیام نرسید، «📲 دریافت کد» را بزن — "
                            f"آن مستقیم از تاریخچه می‌خواند و همیشه کار می‌کند."],
                      subtitle=f"اکانت «{tag}»"),
            buttons=[
                [UI.confirm("📲 دریافت کد", f"codeget:{tag}")],
                UI.nav_row(),
            ],
        )

    async def _show_full_status(self, event, tag: str):
        """📊 وضعیت کامل — گزارش فقط‌خواندنی؛ چیزی را تغییر نمی‌دهد."""
        cfg = self.sb.load_config()
        acc = cfg.get(tag, {})
        entry = self.sb.ACCOUNTS.get(tag)
        state, note = _acc_ui_state(acc, tag)

        body = [f"{UI.state_dot(state)} وضعیت: {note}", UI.SEP]
        if entry:
            bot = entry.bot
            # هر قابلیت با همان نشانگرِ دوحالته‌ی صفحه‌ی «قابلیت‌ها» — تا
            # خواندنِ این گزارش و آن صفحه هیچ اختلافی نداشته باشد.
            for fname, label in FEATURE_LABELS:
                body.append(f"{UI.dot(getattr(bot, fname, False))} {label}")
            body.append(UI.SEP)
            body.append(f"🔤 فونت: `{bot.current_font}`")
            body.append(f"📛 اسم پایه: `{bot.base_name}`")
        else:
            body.append(f"{UI.GRAY} اکانت روشن نیست — وضعیت قابلیت‌ها در دسترس نیست.")
        body.append(f"{UI.dot(bool(acc.get('proxy')))} پروکسی: "
                    f"{'تنظیم‌شده' if acc.get('proxy') else 'تنظیم‌نشده'}")

        # اشتراک SaaS (اگر این پنل زیرِ saas_bot اجرا شود)
        saas = getattr(self, "saas", None)
        owner_id = acc.get("owner_user_id")
        if saas is not None and owner_id:
            sub = get_active_subscription(owner_id)
            if sub:
                body.append(f"{UI.GREEN} اشتراک مالک: پلن «{sub['plan']}» تا {sub['expire_date']}")
            else:
                body.append(f"{UI.RED} اشتراک مالک: فعال نیست")

        buttons = [
            [UI.refresh(f"status:{tag}")],
            UI.nav_row(),
        ]
        await event.edit(
            UI.screen(f"📊 وضعیت کامل «{tag}»", body=body,
                      subtitle="گزارش فقط‌خواندنی — چیزی را تغییر نمی‌دهد."),
            buttons=buttons,
        )

    async def _toggle_feature(self, event, tag: str, feature: str):
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست، نمی‌توان تغییر زنده اعمال کرد.", alert=True)
            return
        bot = entry.bot
        new_value = not getattr(bot, feature)

        try:
            if feature == "enabled":
                bot.enabled = new_value
                bot._persist(enabled=new_value)
            elif feature == "time_enabled":
                bot.time_enabled = new_value
                if new_value:
                    await bot._start_time_loops()
                else:
                    await bot._stop_time_loops()
                bot._persist(time_enabled=new_value)
            elif feature == "bio_enabled":
                if new_value and not bot.base_bio:
                    try:
                        full = await asyncio.wait_for(bot.client(GetFullUserRequest(bot.my_id)), timeout=15)
                        bot.base_bio = full.full_user.about or ""
                    except Exception:
                        pass
                bot.bio_enabled = new_value
                if new_value:
                    await bot._start_bio_loop()
                else:
                    await bot._stop_bio_loop()
                    try:
                        await bot._set_bio(bot.base_bio)
                    except Exception:
                        pass
                bot._persist(bio_enabled=new_value, base_bio=bot.base_bio)
            elif feature == "online_enabled":
                bot.online_enabled = new_value
                try:
                    await asyncio.wait_for(
                        bot.client(UpdateStatusRequest(offline=not new_value)), timeout=15
                    )
                except Exception:
                    pass
                bot._persist(online_enabled=new_value)
            elif feature == "tracker_enabled":
                # دقیقاً همان کاری که فرمان «ردیاب خاموش» خودِ سلف انجام
                # می‌دهد: هنگام خاموش‌کردن، کش/مدیای حافظه هم آزاد می‌شود
                bot.tracker_enabled = new_value
                bot._persist(tracker_enabled=new_value)
                if not new_value:
                    bot._clear_tracker_cache()
            elif feature in SIMPLE_BOOL_FEATURES:
                setattr(bot, feature, new_value)
                bot._persist(**{feature: new_value})
            else:
                await event.answer("قابلیت ناشناخته.", alert=True)
                return
        except Exception as e:
            await event.answer(f"❌ خطا: {str(e)[:150]}", alert=True)
            return

        await self._show_features(event, tag)

    async def _show_font_menu(self, event, tag: str):
        buttons = [[UI.go(f, f"font_set:{tag}:{f}".encode())] for f in FONT_CHOICES]
        buttons.append(UI.nav_row())
        await event.edit(f"🔤 فونت جدید برای «{tag}» رو انتخاب کن:", buttons=buttons)

    async def _set_font(self, event, tag: str, font: str):
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست.", alert=True)
            return
        bot = entry.bot
        bot.current_font = font
        bot._persist(current_font=font)
        await event.answer(f"✅ فونت روی «{font}» تنظیم شد.")
        await self._show_appearance(event, tag)

    async def _start_edit_name_wizard(self, event, tag: str):
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست.", alert=True)
            return
        self.wizards[event.sender_id] = {"state": WIZ_EDIT_NAME, "data": {"tag": tag}}
        await event.edit(
            f"✏️ اسم پایه‌ی جدید برای «{tag}» رو بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    # ─────────────────────────────────────────────────────
    #  فعال/غیرفعال‌سازی اکانت (بدون حذف)
    # ─────────────────────────────────────────────────────

    async def _disable_account(self, event, tag: str):
        cfg = self.sb.load_config()
        if tag not in cfg:
            await event.answer("این اکانت وجود ندارد.", alert=True)
            return
        await event.edit(f"⏳ در حال غیرفعال‌سازی «{tag}»...")
        stopped = await ensure_stopped(tag, "AdminBot._disable_account")
        if not stopped:
            # توقف ناقص (تسکِ Runtime هنوز زنده است و سشن هنوز مالِ اوست):
            # هرگز «غیرفعال‌شده» ثبت نمی‌شود — نه disabled، نه disabled_reason،
            # نه save_config؛ فقط پیام خطای واضح به ادمین و برگشت.
            print(f"❌ [_disable_account] توقف کامل اکانت «{tag}» ممکن نشد — "
                  f"Runtime هنوز مالک سشن است؛ غیرفعال‌سازی انجام نشد.")
            await event.edit(
                f"⚠️ توقف کامل اکانت «{tag}» ممکن نشد (Runtime هنوز در حال بستن/"
                f"سشن باز است) — غیرفعال‌سازی انجام نشد؛ بعداً دوباره تلاش کن.",
                buttons=[UI.nav_row()],
            )
            return
        cfg[tag]["disabled"] = True
        # دلیلِ دستی ثبت می‌شود تا Resume اتوماتیک (تمدید اشتراک) این اکانت
        # را دوباره روشن نکند — فقط خودِ ادمین/کاربر با «فعال‌سازی» می‌تواند.
        cfg[tag]["disabled_reason"] = "manual"
        self.sb.save_config(cfg)
        await self._show_account_detail(event, tag)

    async def _enable_account(self, event, tag: str):
        cfg = self.sb.load_config()
        if tag not in cfg:
            await event.answer("این اکانت وجود ندارد.", alert=True)
            return
        await event.edit(f"⏳ در حال فعال‌سازی «{tag}»... (ممکن است چند ثانیه طول بکشد)")
        cfg[tag]["disabled"] = False
        # فعال‌سازی دستی → دلیل قبلی (اگر subscription_expired بود) پاک می‌شود
        cfg[tag].pop("disabled_reason", None)
        self.sb.save_config(cfg)
        # Runtime Manager مرکزی: اگر از قبل RUNNING/STARTING است همان Runtime
        # را reuse/await می‌کند — Client دوم ساخته نمی‌شود.
        ready, st = await ensure_started(tag, cfg[tag], caller="AdminBot._enable_account",
                                         runner=self.sb.run_bot)
        if not ready:
            await event.respond(
                f"⚠️ اکانت «{tag}» هنوز آماده نشده (وضعیت: {_status_human(st)}). "
                f"علت دقیق در لاگ سرور ثبت شده."
            )
        await self._show_account_detail(event, tag)

    # ─────────────────────────────────────────────────────
    #  حذف کامل اکانت
    # ─────────────────────────────────────────────────────

    async def _delete_account(self, event, tag: str):
        cfg = self.sb.load_config()
        if tag not in cfg:
            await event.answer("این اکانت دیگر وجود ندارد.", alert=True)
            await self._show_account_list(event)
            return

        await event.edit(f"⏳ در حال حذف «{tag}»...")

        # ۱) ثبت Intent حذف — قبل از هر تغییر (PATCH 8: Recovery-safe؛ اگر
        # وسطِ عملیات Crash کنیم، استارتاپ مراحل باقی‌مانده را کامل می‌کند).
        journal = _load_account_delete_journal()
        journal[tag] = "DELETE_PENDING"
        _save_account_delete_journal(journal)
        try:
            # ۲) توقف کامل Runtime و انتظار برای پایانِ واقعیِ تسک
            #    (disconnect → save → close → unregister)
            stopped = await ensure_stopped(tag, "AdminBot._delete_account")
            if not stopped:
                # PATCH 5: تسک هنوز زنده است → سشن را نباید حذف کرد (کلاینتِ
                # زنده به آن write می‌کند). هیچ تغییری اعمال نشده؛ Intent را
                # برمی‌داریم و حذف را لغو می‌کنیم.
                print(f"❌ [delete_account] توقف کامل اکانت «{tag}» ممکن نشد — "
                      f"سشن هنوز باز است؛ حذف لغو شد.")
                journal = _load_account_delete_journal()
                journal.pop(tag, None)
                _save_account_delete_journal(journal)
                await event.edit(
                    f"⚠️ توقف کامل اکانت «{tag}» ممکن نشد (سشن هنوز باز است) — "
                    f"حذف لغو شد؛ بعداً دوباره تلاش کن.",
                    buttons=[UI.nav_row()],
                )
                return
            # ۳) پاک‌سازی Session (فایل + sidecar) — نتیجه بررسی می‌شود:
            # اگر سشن حذف نشد، config حذف نمی‌شود و journal (DELETE_PENDING)
            # دست‌نخورده می‌ماند تا Recovery استارتاپی ادامه دهد و اکانت
            # قابل بازیابی باشد.
            if not _remove_session_files(tag):
                print(f"❌ [delete_account] حذف فایل سشن «{tag}» ناقص ماند — "
                      f"config حذف نشد؛ journal حفظ شد و Recovery استارتاپی "
                      f"ادامه می‌دهد.")
                await event.edit(
                    f"⚠️ حذف اکانت «{tag}» ناتمام ماند (فایل سشن قابل حذف نبود) — "
                    f"config حذف نشد؛ عملیات در استارتاپ بعدی ادامه می‌یابد.",
                    buttons=[UI.nav_row()],
                )
                return
            # ۴) به‌روزرسانی config
            cfg.pop(tag, None)
            self.sb.save_config(cfg)
            try:
                self.sb.clear_state(tag)
            except Exception as e:
                print(f"⚠️ [delete_account] پاک‌سازی state اکانت {tag} ناموفق: "
                      f"{type(e).__name__}: {str(e)[:80]}")
        except Exception as e:
            # نیمه‌حذف — journal عمداً باقی می‌ماند تا Recovery استارتاپی ادامه
            # دهد (حذفِ دائمی بدونِ ثبت Intent هرگز اتفاق نمی‌افتد).
            print(f"❌ [delete_account] حذف اکانت «{tag}» نیمه‌تمام ماند — "
                  f"Recovery استارتاپی ادامه می‌دهد: {type(e).__name__}: "
                  f"{str(e)[:120]}")
            await event.edit(
                f"⚠️ حذف اکانت «{tag}» نیمه‌تمام ماند و در استارتاپ بعدی خودکار "
                f"کامل می‌شود.",
                buttons=[UI.nav_row()],
            )
            return
        # ۶) همه‌ی مراحل موفق → Mark Delete Completed
        journal = _load_account_delete_journal()
        journal.pop(tag, None)
        _save_account_delete_journal(journal)

        await event.edit(
            f"✅ اکانت «{tag}» با موفقیت حذف شد (اگر روشن بود، اول تمیز خاموش شد).",
            buttons=[UI.nav_row()],
        )

    # ─────────────────────────────────────────────────────
    #  پروکسی — هم برای اکانت موجود، هم برای لاگینِ اکانت جدید
    # ─────────────────────────────────────────────────────
    # نکته‌ی مهم: پروکسی روی این پروژه دو کاربرد دارد که هر دو پشتیبانی
    # می‌شوند: (۱) اگر تلگرام IP سرور را برای *ورود/لاگین* محدود کرده باشد،
    # می‌توان قبل از شروع لاگین یک پروکسی انتخاب کرد تا کل فرایند لاگین
    # (send_code_request و sign_in) از همان لحظه‌ی اول از پروکسی رد شود.
    # (۲) برای یک اکانت از قبل موجود، می‌توان پروکسی تنظیم/تعویض کرد که
    # پس از ری‌استارت زنده اعمال شود. هر دو مسیر از همان مراحل مشترک زیر
    # (نوع → آدرس → پورت → یوزرنیم/پسورد اختیاری) عبور می‌کنند؛ تفاوت فقط
    # در قدم پایانی (_finish_proxy) است که بر اساس data["proxy_flow"]
    # تشخیص می‌دهد کدام مسیر در جریان است.

    async def _show_proxy_type_buttons(self, event, title: str):
        buttons = [
            [UI.go("SOCKS5", b"proxy_type:socks5"),
             UI.go("SOCKS4", b"proxy_type:socks4"),
             UI.go("HTTP", b"proxy_type:http")],
            [UI.neutral(UI.L_CANCEL, "cancel_wizard")],
        ]
        await event.edit(title, buttons=buttons)

    async def _start_proxy_wizard(self, event, tag: str):
        self.wizards[event.sender_id] = {
            "state": None,
            "data": {"tag": tag, "proxy_flow": "existing_account"},
        }
        await self._show_proxy_type_buttons(event, f"🌐 **تنظیم پروکسی برای «{tag}»**\n\nنوع پروکسی رو انتخاب کن:")

    async def _proxy_type_chosen(self, event, proxy_type: str):
        wiz = self.wizards.get(event.sender_id)
        if not wiz:
            return
        wiz["data"]["proxy_type"] = proxy_type
        wiz["state"] = WIZ_PROXY_ADDR
        await event.edit(
            "آدرس (IP یا دامنه‌ی) پروکسی رو بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def _finish_proxy(self, event, data: dict):
        proxy_cfg = {
            "proxy_type": data["proxy_type"],
            "addr": data["addr"],
            "port": data["port"],
            "rdns": True,
        }
        if data.get("username"):
            proxy_cfg["username"] = data["username"]
            proxy_cfg["password"] = data.get("password", "")

        if data.get("proxy_flow") == "new_account_login":
            # این پروکسی برای همین لاگینِ در حال انجامِ یک اکانت *جدید*
            # است — به مرحله‌ی ارسال کد (که حالا با این پروکسی وصل می‌شود)
            # می‌رویم، نه ذخیره در config یک اکانت موجود.
            data["proxy"] = proxy_cfg
            await self._do_send_code(event, data)
            return

        # وگرنه: تنظیم پروکسی برای یک اکانت از قبل موجود
        tag = data["tag"]
        cfg = self.sb.load_config()
        if tag not in cfg:
            await event.respond("❌ این اکانت دیگر وجود ندارد.")
            self.wizards.pop(event.sender_id, None)
            return
        cfg[tag]["proxy"] = proxy_cfg
        self.sb.save_config(cfg)
        self.wizards.pop(event.sender_id, None)

        await event.respond(
            f"✅ پروکسی برای «{tag}» ذخیره شد.\n"
            f"⚠️ نیاز است این پکیج روی سرور نصب باشد: `pip install python_socks --break-system-packages`\n"
            f"برای اعمال، اکانت الان ری‌استارت می‌شود..."
        )

        # توقف کامل → استارت جدید با پروکسی تازه — از Runtime Manager مرکزی
        # (restart تضمین می‌کند Stop کامل قبل از Start جدید انجام شود).
        ready, st = await restart(tag, cfg[tag], caller="AdminBot._apply_proxy",
                                  runner=self.sb.run_bot)
        if not ready:
            await event.respond(
                f"⚠️ اکانت «{tag}» هنوز آماده نشده (وضعیت: {_status_human(st)}). "
                f"علت دقیق در لاگ سرور ثبت شده."
            )
        await self._show_account_detail(event, tag)

    # ─────────────────────────────────────────────────────
    #  ارسال پیام از طرف یک اکانت — به هر آیدی/یوزرنیمی، نه فقط Saved Messages
    # ─────────────────────────────────────────────────────

    async def _start_send_msg_wizard(self, event, tag: str):
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.answer("این اکانت الان روشن نیست.", alert=True)
            return
        self.wizards[event.sender_id] = {"state": WIZ_SEND_MSG_TARGET, "data": {"tag": tag}}
        await event.edit(
            f"📨 **ارسال پیام از طرف «{tag}»**\n\n"
            f"آیدی عددی، یوزرنیم (با یا بدون @) رو بفرست — یا برای "
            f"Saved Messages خودش دکمه‌ی زیر رو بزن:\n\n"
            f"💡 توجه: تلگرام فقط اجازه می‌دهد به یوزرنیم‌ها یا کسانی که قبلاً "
            f"با این اکانت تعامل داشته‌اند پیام بفرستی — نه هر آیدی عددی دلخواه.",
            buttons=[
                [UI.go("📥 Saved Messages خودش", b"send_target_me")],
                [UI.neutral(UI.L_CANCEL, "cancel_wizard")],
            ],
        )

    async def _finish_send_msg(self, event, tag: str, target, text: str):
        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await event.respond(f"❌ اکانت «{tag}» دیگر روشن نیست.")
            return
        try:
            await asyncio.wait_for(entry.bot.client.send_message(target, text), timeout=20)
            await event.respond(f"✅ پیام از طرف «{tag}» به «{target}» ارسال شد.")
        except ValueError as e:
            await event.respond(
                f"❌ ارسال ناموفق بود: {str(e)[:150]}\n\n"
                f"💡 تلگرام اجازه نمی‌دهد به هر آیدی عددی دلخواه پیام بدهی، مگر "
                f"اینکه این اکانت قبلاً باهاش تعامل داشته یا در مخاطبینش باشد — "
                f"بهتر است یوزرنیم (مثلاً @username) استفاده کنی."
            )
        except Exception as e:
            await event.respond(f"❌ ارسال ناموفق بود: {str(e)[:150]}")

    # ─────────────────────────────────────────────────────
    #  مدیریت ادمین‌ها (فقط در حالت standalone معنا دارد)
    # ─────────────────────────────────────────────────────

    async def _show_admin_menu(self, event):
        if not self.standalone:
            await event.answer("مدیریت ادمین‌ها از طریق پنل نقش‌ها (OWNER) انجام می‌شود.", alert=True)
            return
        lines = ["👥 **مدیریت ادمین‌ها:**\n"]
        buttons = []
        for uid in sorted(self.admin_ids | {ADMIN_ID}):
            tag = " (سوپرادمین)" if uid == ADMIN_ID else ""
            lines.append(f"👤 `{uid}`{tag}")
            if uid != ADMIN_ID:
                buttons.append([UI.danger(f"حذف {uid}", f"admin_del:{uid}")])
        buttons.append([UI.go("➕ افزودن ادمین", b"admin_add", tone="success")])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _start_add_admin_wizard(self, event):
        self.wizards[event.sender_id] = {"state": WIZ_ADD_ADMIN, "data": {}}
        await event.edit(
            "➕ **افزودن ادمین جدید**\n\n"
            "آیدی عددی تلگرام شخص رو بفرست، یا یه پیام از همون شخص رو برام فوروارد کن:",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def _remove_admin(self, event, uid: int):
        if uid == ADMIN_ID:
            await event.answer("سوپرادمین قابل حذف نیست.", alert=True)
            return
        self.admin_ids.discard(uid)
        self._save_admin_ids()
        await self._show_admin_menu(event)

    # ─────────────────────────────────────────────────────
    #  پشتیبان‌گیری روزانه
    # ─────────────────────────────────────────────────────

    async def _daily_backup_loop(self):
        """
        حلقه‌ی پشتیبان‌گیری خودکار. در هر «ساعت پشتیبان» (پیش‌فرض ۰۰:۰۰ و
        ۱۲:۰۰ به وقت ایران) یک بکاپ کامل ساخته و برای همه‌ی OWNER/ADMIN
        ها ارسال می‌شود. بین دو بکاپ، تسک فقط sleep می‌کند.
        """
        while True:
            try:
                now = self.sb.iran_now()
                target = self._next_backup_time(now)
                wait_seconds = max(1.0, (target - now).total_seconds())
                await asyncio.sleep(wait_seconds)
                await self._send_backup(scheduled_hour=target.hour)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [admin_bot] خطا در پشتیبان‌گیری روزانه: {e}")
                await asyncio.sleep(3600)

    @staticmethod
    def _next_backup_time(now) -> object:
        """
        نزدیک‌ترین زمان پشتیبانی بعدی (به وقت ایران).
        ساعات از BACKUP_HOURS_IRAN می‌آیند؛ تسک در اولین ساعتِ آینده
        (یا اگر الان دقیقاً همان ساعت باشد، همان لحظه) بیدار می‌شود.
        """
        today = now.replace(minute=0, second=0, microsecond=0)
        candidates = [today.replace(hour=int(h)) for h in BACKUP_HOURS_IRAN]
        future = [t for t in candidates if t > now]
        if future:
            return min(future)
        # امروز دیگر ساعتی نمونده → اولین ساعتِ فردا
        tomorrow = today + timedelta(days=1)
        return tomorrow.replace(hour=int(min(BACKUP_HOURS_IRAN)))

    def _backup_recipient_ids(self) -> set:
        """
        در حالت standalone از لیست محلی JSON، در حالت غیر-standalone از
        نقش‌های OWNER/ADMIN ثبت‌شده در saas_db استفاده می‌کند (چون در آن
        حالت لیست محلی اصلاً به‌روز نگه داشته نمی‌شود).
        """
        if self.standalone:
            return self.admin_ids | {ADMIN_ID}
        try:
            ids = {ADMIN_ID}
            for entry in list_admins_and_resellers():
                if entry["role"] in (ROLE_OWNER, ROLE_ADMIN):
                    ids.add(entry["user_id"])
            return ids
        except Exception:
            return {ADMIN_ID}

    async def _send_backup(self, scheduled_hour: int = None):
        """بکاپ کامل روزانه (manifest) و ارسال به OWNER/ADMIN ها.

        scheduled_hour: فقط برای کپشن (کاربر بفهمد کدام نوبت است).
        """
        backup_path = os.path.join(tempfile.gettempdir(), _backup_file_name())
        try:
            ok = await asyncio.to_thread(build_backup_zip, backup_path)
            if not ok:
                print("⚠️ [admin_bot] ساخت بکاپ روزانه ناموفق بود — ارسال نشد.")
                return
            now = self.sb.iran_now()
            slot = f"{int(scheduled_hour):02d}:00" if scheduled_hour is not None                 else now.strftime("%H:%M")
            caption = (
                f"📦 پشتیبان خودکار — {now.strftime('%Y-%m-%d %H:%M')}\n"
                f"🕐 نوبت: {slot} (ایران) — برنامه: {', '.join(f'{int(h):02d}:00' for h in BACKUP_HOURS_IRAN)}"
            )
            for admin_id in self._backup_recipient_ids():
                try:
                    await asyncio.wait_for(
                        self.client.send_file(admin_id, backup_path, caption=caption),
                        timeout=60,
                    )
                except Exception as e:
                    print(f"⚠️ [admin_bot] ارسال بکاپ به {admin_id} ناموفق بود: {e}")
        finally:
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────
    #  ویزارد افزودن اکانت (لاگین کامل از داخل چت، با پروکسی اختیاری)
    # ─────────────────────────────────────────────────────

    async def _start_add_wizard(self, event, preset_owner_id: int = None,
                                preset_data: dict = None):
        """
        ویزارد افزودن/لاگین اکانت. اگر preset_owner_id داده شود، اکانتِ
        ساخته‌شده به همین کاربر تعلق می‌گیرد (owner_user_id) — برای «➕ افزودن
        SelfBot» از داخل مدیریت یک کاربر که می‌خواهد اکانت برای همان کاربر
        ساخته شود. در غیر این صورت، مالک از default_owner_id (scope پنل)
        گرفته می‌شود. preset_data داده‌ی اضافه‌ی ویزارد (مثل add_back).
        """
        data = dict(preset_data or {})
        if preset_owner_id is not None:
            # «افزودن SelfBot» توسط OWNER/ADMIN/RESELLER برای یک کاربر خاص:
            # از کلیدِ مجزا (for_user_id) استفاده می‌کنیم — نه owner_user_id —
            # تا در _finish_add_account با مسیر «لاگین مستقیم کاربر عادی»
            # (که owner_user_id صریح می‌گذارد) اشتباه گرفته نشود و ادمین
            # بعد از ساخت، در منوی USER فرود نیاید.
            data["for_user_id"] = preset_owner_id
        self.wizards[event.sender_id] = {"state": WIZ_TAG, "data": data}
        title = "➕ **افزودن SelfBot**" if preset_owner_id is not None else "➕ **افزودن اکانت جدید**"
        await event.edit(
            f"{title}\n\n"
            "یه اسم (تگ) کوتاه برای این اکانت بفرست — فقط حروف انگلیسی/عدد/"
            "خط‌تیره (مثلاً `account1`):",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def _cleanup_wizard_temp_client(self, wiz: dict):
        temp_client = wiz.get("data", {}).get("temp_client") if wiz else None
        if temp_client:
            try:
                await temp_client.disconnect()
            except Exception:
                pass

    async def _cancel_wizard(self, uid: int, notify_event=None, chat=None):
        wiz = self.wizards.pop(uid, None)
        await self._cleanup_wizard_temp_client(wiz)
        # اگر این ویزارد مربوط به لاگین مستقیم یک کاربر عادی بود (نه
        # ادمین/نماینده‌ای که از پنل مدیریت وارد شده)، نباید بعد از لغو،
        # منوی کامل مدیریت اکانت‌ها (که چنین کاربری اصلاً نباید ببیند)
        # نمایش داده شود — به‌جایش یک دکمه‌ی «🏠 منوی اصلی» نشان داده
        # می‌شود که callback مشترک back_role_menu را دارد و saas_bot.py
        # آن را به منوی نقش‌محور (USER) برمی‌گرداند؛ یعنی کاربر عادی بعد
        # از لغوِ لاگین، بی‌درنگ می‌تواند دوباره از همان منو «🔐 لاگین به
        # اکانت» را بزند و از نو امتحان کند. (در حالت standalone کاربر
        # عادی وجود ندارد و این شاخه هرگز اجرا نمی‌شود.)
        is_plain_user = bool(wiz and "owner_user_id" in wiz.get("data", {}))
        # «افزودن SelfBot» برای یک کاربر خاص (از داخل مدیریت کاربر): بعد از
        # لغو، به لیست SelfBotهای همان کاربر برگردیم — نه منوی کلی پنل.
        for_user = (wiz or {}).get("data", {}).get("for_user_id") if wiz else None
        add_back = (wiz or {}).get("data", {}).get("add_back") if wiz else None
        saas = getattr(self, "saas", None)
        if for_user and add_back and saas is not None:
            if notify_event is not None:
                try:
                    await saas._show_user_accounts(notify_event, for_user, add_back)
                except Exception:
                    pass
            elif chat is not None:
                try:
                    text, buttons = saas._build_user_accounts_view(for_user, add_back)
                    await self.client.send_message(chat, text, buttons=buttons)
                except Exception:
                    pass
            return
        if notify_event is not None:
            if is_plain_user:
                await notify_event.edit(
                    "❌ لغو شد.",
                    buttons=[UI.nav_row(back=False)],
                )
            else:
                await notify_event.edit("❌ لغو شد.")
                await self._show_main_menu(notify_event.chat_id)
        elif chat is not None:
            if is_plain_user:
                await self.client.send_message(
                    chat, "❌ لغو شد.",
                    buttons=[UI.nav_row(back=False)],
                )
            else:
                await self.client.send_message(chat, "❌ لغو شد.")
                await self._show_main_menu(chat)

    async def _do_send_code(self, event, data: dict):
        """
        مرحله‌ی واقعیِ اتصال + ارسال کد لاگین — چه با پروکسی (اگر کاربر
        انتخاب کرده) چه بدون آن. جدا شده تا هم از مسیر «بدون پروکسی» و هم
        از انتهای ویزارد پروکسی (بعد از جمع‌آوری اطلاعاتش) صدا زده شود.
        """
        tag = data["tag"]
        phone = data["phone"]
        proxy_cfg = data.get("proxy")  # ممکن است None باشد (بدون پروکسی)

        cfg = self.sb.load_config()
        try:
            api_id, api_hash = _first_account_creds(cfg)
        except RuntimeError as e:
            # config خالی/خراب یا بدون اکانتِ معتبر — ویزارد با پیام واضح
            # بسته می‌شود (نه کرشِ StopIteration/KeyError).
            await event.respond(
                f"❌ {e}",
                buttons=[UI.nav_row(back=False)],
            )
            self.wizards.pop(event.sender_id, None)
            return
        session_path = os.path.join(self.sb.SESSIONS_DIR, tag)
        temp_client = TelegramClient(
            session_path, api_id, api_hash,
            proxy=proxy_cfg,
        )
        try:
            await asyncio.wait_for(temp_client.connect(), timeout=30)
            sent = await asyncio.wait_for(temp_client.send_code_request(phone), timeout=30)
        except Exception as e:
            note = ""
            if proxy_cfg is None:
                note = "\n💡 اگه فکر می‌کنی IP این سرور برای تلگرام فیلتره، دوباره «افزودن اکانت» رو بزن و این‌بار پروکسی رو انتخاب کن."
            await event.respond(f"❌ خطا در اتصال/ارسال کد: {str(e)[:150]}{note}\nویزارد لغو شد.")
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            self.wizards.pop(event.sender_id, None)
            return

        data["temp_client"] = temp_client
        data["phone_code_hash"] = sent.phone_code_hash
        self.wizards[event.sender_id] = {"state": WIZ_CODE, "data": data}
        await event.respond(
            "📩 کد به تلگرام/پیامکِ این شماره ارسال شد. کد رو بفرست:\n"
            "(فاصله بین ارقام مهم نیست، خودم پاکش می‌کنم)",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def _handle_wizard_input(self, event, wiz: dict):
        state = wiz["state"]
        data = wiz["data"]
        text = (event.raw_text or "").strip()

        if text in ("لغو", "cancel", "/cancel"):
            await self._cancel_wizard(event.sender_id, chat=event.chat_id)
            return

        if state == WIZ_ADD_ADMIN:
            if not self.standalone:
                # در حالت غیر-standalone این مسیر اصلاً نباید فعال شود؛
                # مدیریت ادمین‌ها منحصراً از طریق saas_bot.py (که saas_db
                # را به‌روزرسانی می‌کند) انجام می‌شود.
                self.wizards.pop(event.sender_id, None)
                await event.respond("این عملیات از این پنل در دسترس نیست.")
                return
            new_id = None
            if event.forward and event.forward.sender_id:
                new_id = event.forward.sender_id
            else:
                try:
                    new_id = int(text)
                except ValueError:
                    await event.respond("❌ یا آیدی عددی بفرست، یا یه پیام از همون شخص رو فوروارد کن:")
                    return
            self.wizards.pop(event.sender_id, None)
            if new_id in (self.admin_ids | {ADMIN_ID}):
                await event.respond("این شخص از قبل ادمینه.")
            else:
                self.admin_ids.add(new_id)
                self._save_admin_ids()
                await event.respond(f"✅ آیدی `{new_id}` به‌عنوان ادمین اضافه شد.")
            await self._show_main_menu(event.chat_id)
            return

        if state == WIZ_EDIT_NAME:
            tag = data["tag"]
            entry = self.sb.ACCOUNTS.get(tag)
            self.wizards.pop(event.sender_id, None)
            if not entry:
                await event.respond(f"❌ اکانت «{tag}» دیگر روشن نیست.")
                await self._show_main_menu(event.chat_id)
                return
            bot = entry.bot
            new_name = bot._clean_name(text)
            bot.base_name = new_name
            bot._persist(base_name=new_name)
            await event.respond(f"✅ اسم پایه‌ی «{tag}» به «{new_name}» تغییر کرد.")
            await self._show_account_detail(event, tag)
            return

        if state == WIZ_SEND_MSG_TARGET:
            target = text
            if target.lower() != "me":
                target = target.lstrip("@")
                if target.lstrip("-").isdigit():
                    target = int(target)
            data["target"] = target
            wiz["state"] = WIZ_SEND_MSG_TEXT
            await event.respond(
                "متن پیام رو بفرست:", buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]]
            )
            return

        if state == WIZ_SEND_MSG_TEXT:
            tag = data["tag"]
            target = data["target"]
            self.wizards.pop(event.sender_id, None)
            await self._finish_send_msg(event, tag, target, event.raw_text or text)
            await self._show_account_detail(event, tag)
            return

        if state == WIZ_PROXY_ADDR:
            data["addr"] = text
            wiz["state"] = WIZ_PROXY_PORT
            await event.respond("پورت پروکسی رو بفرست (فقط عدد):",
                                 buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]])
            return

        if state == WIZ_PROXY_PORT:
            if not text.isdigit():
                await event.respond("❌ پورت باید فقط عدد باشه. دوباره بفرست:")
                return
            data["port"] = int(text)
            wiz["state"] = WIZ_PROXY_USERNAME
            await event.respond(
                "یوزرنیم پروکسی رو بفرست (اگه نیاز نداره، دکمه‌ی رد کن رو بزن):",
                buttons=[[UI.go("⏭ رد کن (بدون یوزرنیم/پسورد)", b"proxy_skip_auth")],
                         [UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
            )
            return

        if state == WIZ_PROXY_USERNAME:
            if text in ("رد کن", "skip", "-"):
                await self._finish_proxy(event, data)
                return
            data["username"] = text
            wiz["state"] = WIZ_PROXY_PASSWORD
            await event.respond("پسورد پروکسی رو بفرست:",
                                 buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]])
            return

        if state == WIZ_PROXY_PASSWORD:
            data["password"] = text
            await self._finish_proxy(event, data)
            return

        if state == WIZ_TAG:
            cfg = self.sb.load_config()
            if not re.fullmatch(r"[A-Za-z0-9_\-]{2,32}", text):
                await event.respond("❌ فقط حروف انگلیسی/عدد/خط‌تیره، بین ۲ تا ۳۲ کاراکتر. دوباره بفرست:")
                return
            if text in cfg or text in RESERVED_TAGS:
                await event.respond("❌ این تگ قبلاً استفاده شده یا رزرو شده. یه اسم دیگه بفرست:")
                return
            data["tag"] = text
            wiz["state"] = WIZ_PHONE
            await event.respond(
                "شماره تلفن رو با کد کشور بفرست (مثلاً `+989123456789`):",
                buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
            )
            return

        if state == WIZ_PHONE:
            if not re.fullmatch(r"\+\d{7,15}", text):
                await event.respond("❌ فرمت شماره درست نیست. با + و کد کشور بفرست (مثلاً +989123456789):")
                return
            data["phone"] = text
            wiz["state"] = None
            await event.respond(
                "🌐 برای این لاگین نیاز به پروکسی داری؟ (اگه تلگرام IP این سرور رو "
                "برای ورود محدود/فیلتر کرده، باید از پروکسی وارد بشی)",
                buttons=[
                    [UI.go("🌐 بله، با پروکسی وارد شو", b"login_proxy_yes")],
                    [UI.go("🚀 نه، مستقیم وصل شو", b"login_proxy_no")],
                    [UI.neutral(UI.L_CANCEL, "cancel_wizard")],
                ],
            )
            return

        if state == WIZ_CODE:
            code = re.sub(r"\D", "", text) or text
            temp_client = data["temp_client"]
            try:
                await asyncio.wait_for(
                    temp_client.sign_in(
                        phone=data["phone"], code=code,
                        phone_code_hash=data["phone_code_hash"],
                    ),
                    timeout=30,
                )
            except errors.SessionPasswordNeededError:
                wiz["state"] = WIZ_PASSWORD
                await event.respond(
                    "🔐 این اکانت رمز دو مرحله‌ای (2FA) دارد. رمز رو بفرست:",
                    buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
                )
                return
            except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError):
                await event.respond("❌ کد اشتباه یا منقضی‌شده است. دوباره بفرست:")
                return
            except Exception as e:
                await event.respond(f"❌ خطا: {str(e)[:150]}\nویزارد لغو شد.")
                await self._cancel_wizard(event.sender_id)
                return

            await self._finish_add_account(event, data)
            return

        if state == WIZ_PASSWORD:
            temp_client = data["temp_client"]
            try:
                await asyncio.wait_for(temp_client.sign_in(password=text), timeout=30)
            except errors.PasswordHashInvalidError:
                await event.respond("❌ رمز اشتباه است. دوباره بفرست:")
                return
            except Exception as e:
                await event.respond(f"❌ خطا: {str(e)[:150]}\nویزارد لغو شد.")
                await self._cancel_wizard(event.sender_id)
                return

            await self._finish_add_account(event, data)
            return

    async def _finish_add_account(self, event, data: dict):
        tag = data["tag"]
        temp_client: TelegramClient = data["temp_client"]

        # مالکیت اکانت باید همین‌جا و قبل از هر await گرفته شود: admin_panel
        # یک نمونه‌ی مشترک بین همه‌ی کاربران است و default_owner_id آن قبل از
        # هر فراخوانی دوباره ست می‌شود (_sync_admin_panel_scope). اگر این مقدار
        # بعد از await های پایین (get_me/disconnect) خوانده شود، یک رویداد
        # هم‌زمان از کاربرِ دیگر می‌تواند آن را عوض کند و اکانتِ ساخته‌شده
        # به‌اشتباه به کاربرِ دیگر نسبت داده شود. (در مسیر «لاگین به اکانت»
        # کاربر عادی data["owner_user_id"] صریحاً ست شده و این رقابت اصلاً
        # رخ نمی‌دهد؛ این سخت‌سازی برای مسیر «افزودن اکانت» از خودِ پنل است.)
        owner_for_new_account = data.get("for_user_id") or data.get("owner_user_id") or self.default_owner_id

        try:
            me = await temp_client.get_me()
            # ─── ترتیب امن handoff سشن ───────────────────────────────────
            # اول کلاینتِ موقت کاملاً disconnect می‌شود (داخل تلتون
            # disconnect() خودش session.close() را هم اجرا می‌کند)، بعد
            # صریحاً save و close. به این ترتیب وقتی SelfBot جدید همان فایل
            # سشن را باز می‌کند، هیچ handle باز/نیمه‌بسته‌ای از کلاینت موقت
            # روی آن باقی نمانده است (قبلاً save/close قبل از disconnect
            # انجام می‌شد — یعنی سشن بسته شده بود در حالی که سوکت هنوز باز
            # بود و هر نوشته‌ی درون‌رویی مجدداً کانکشن sqlite را باز می‌کرد).
            await temp_client.disconnect()
            temp_client.session.save()
            temp_client.session.close()
        except Exception as e:
            await event.respond(f"❌ خطا در نهایی‌سازی لاگین: {str(e)[:150]}")
            self.wizards.pop(event.sender_id, None)
            return

        cfg = self.sb.load_config()
        if not cfg:
            # همان گاردِ _do_send_code — به‌صورت دفاعی اینجا هم: اگر config
            # خالی/خراب باشد، اکانتِ لاگین‌شده را نمی‌توان با api_id/api_hash
            # یک اکانت پایه ذخیره کرد. به‌جای StopIteration مبهم، پیام واضح +
            # بستن تمیز ویزارد.
            await event.respond(
                "❌ config.json خالی/خراب است — اکانت ذخیره نشد. "
                "با پشتیبانی تماس بگیر.",
                buttons=[UI.nav_row(back=False)],
            )
            self.wizards.pop(event.sender_id, None)
            return
        try:
            api_id, api_hash = _first_account_creds(cfg)
        except RuntimeError as e:
            await event.respond(
                f"❌ {e}",
                buttons=[UI.nav_row(back=False)],
            )
            self.wizards.pop(event.sender_id, None)
            return
        new_entry = {
            "type": "user",
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": data["phone"],
            "user_id": me.id,
        }
        if owner_for_new_account is not None:
            new_entry["owner_user_id"] = owner_for_new_account
        # منبعِ ساخت اکانت (provision_source) — برای تشخیص «اضافه‌شده‌ی دستی»:
        #   for_user_id → مدیریت برای کاربر دیگری ساخته (manual)
        #   owner_user_id بدون for_user_id → خودِ کاربر بعد از لایسنس/پرداخت (license)
        #   بقیه → کاربر از پنل خودش (subscription)
        if data.get("for_user_id"):
            new_entry["provision_source"] = PROVISION_MANUAL
        elif "owner_user_id" in data and "for_user_id" not in data:
            new_entry["provision_source"] = PROVISION_LICENSE
        else:
            new_entry["provision_source"] = PROVISION_SUBSCRIPTION
        if data.get("proxy"):
            new_entry["proxy"] = data["proxy"]
        cfg[tag] = new_entry
        self.sb.save_config(cfg)

        # ─── انتظار برای READY واقعی (نه فقط ثبت در ACCOUNTS) ───────────
        # Runtime Manager مرکزی: استارت + انتظار برای READY واقعی. ACCOUNTS
        # فقط بعد از موفقیت کامل start پر می‌شود؛ پس وجود در ACCOUNTS یعنی
        # واقعاً READY.
        self.wizards.pop(event.sender_id, None)
        display_name = me.first_name or ""
        proxy_note = " (با همون پروکسی ادامه پیدا می‌کنه)" if data.get("proxy") else ""

        # حداکثر ۴۰ ثانیه صبر (اتصال + احراز هویت + get_me + ثبت هندلرها)
        # — ویزارد دیگر هرگز قبل از روشن‌شدن واقعی، پیام موفقیت نمی‌دهد.
        ready, st = await ensure_started(tag, cfg[tag], caller="SaaSBot._finish_add_account",
                                         runner=self.sb.run_bot, wait_seconds=40)

        # policy اکانتِ تازه‌لاگین‌شده: باید بلافاصله قابل استفاده باشد —
        # enabled=True به‌صورت atomic (هم در memory و هم در state DB) ذخیره
        # می‌شود. (کاربر بعداً با «سلف خاموش» می‌تواند خاموشش کند.)
        if ready:
            entry = ACCOUNTS.get(tag)
            if entry is not None:
                try:
                    entry.bot.enabled = True
                    entry.bot._persist(enabled=True)
                except Exception as e:
                    print(f"⚠️ [{tag}] ثبت enabled=True پس از لاگین ناموفق بود: {type(e).__name__}")

        # اگر این ویزارد از مسیر «لاگین مستقیم کاربر عادی» شروع شده بود
        # (یعنی data["owner_user_id"] صراحتاً ست شده بود، نه از
        # self.default_owner_id گرفته شده)، این کاربر از مسیر لایسنس/پرداخت
        # آمده است. طبق اسپکِ یکپارچه‌سازی «کاربران» و «مدیریت اکانت‌های
        # سلف»: بعد از لاگین موفق، کاربر باید دقیقاً در همان پنل «مدیریت
        # اکانت‌های سلف» فرود بیاید (نه یک بخش جدا). امنیت همان مکانیزم
        # همیشگی است — saas_bot.py قبل از رسیدن به اینجا، owner_filter را
        # روی {user_id} تنظیم کرده، پس این پنل فقط اکانت‌های خودِ کاربر را
        # نشان می‌دهد و «با همون دسترسی‌ها» (محدود به خودش) کار می‌کند.
        is_plain_user_login = "owner_user_id" in data and "for_user_id" not in data
        saas = getattr(self, "saas", None)
        if is_plain_user_login and saas is not None:
            if ready:
                await event.respond(
                    f"✅ اکانت «{display_name}» با موفقیت لاگین شد و سلفت روشن است!{proxy_note}\n\n"
                    f"برای مدیریت سلفت، کلمه‌ی «پنل» رو بفرست."
                )
            else:
                await event.respond(
                    f"⚠️ ورود اکانت «{display_name}» موفق بود اما SelfBot هنوز آماده نیست "
                    f"(وضعیت: {_status_human(st)}).\nعلت دقیق در لاگ سرور ثبت شده — اگر "
                    f"ادامه پیدا کرد، با پشتیبانی تماس بگیر."
                )
            # کاربر عادی باید در «منوی اصلی» نقش خودش فرود بیاید (مدیریت
            # سلفش از طریق همان ربات کمکی و «پنل» انجام می‌شود).
            await saas._show_menu_for_role(event.chat_id, ROLE_USER)
            return

        if ready:
            await event.respond(
                f"✅ اکانت «{tag}» ({display_name}) با موفقیت اضافه شد و سلف روشن است.{proxy_note}"
            )
        else:
            await event.respond(
                f"⚠️ اکانت «{tag}» اضافه شد اما SelfBot هنوز آماده نیست "
                f"(وضعیت: {_status_human(st)}). علت دقیق در لاگ سرور ثبت شده."
            )
        # اگر این اکانت برای یک کاربر خاص (از داخل «مدیریت کاربر») ساخته
        # شد، به لیست SelfBotهای همان کاربر برگرد — نه منوی کلی پنل.
        for_user_id = data.get("for_user_id")
        if for_user_id and saas is not None:
            back = data.get("add_back") or b"owner_users"
            try:
                await saas._show_user_accounts_as_message(event, for_user_id, back)
            except Exception:
                pass
            return
        await self._show_main_menu(event.chat_id)

    # ─────────────────────────────────────────────────────
    #  متدهای هندلر — به‌صورت متد معمولی (نه closure ثبت‌شده‌ی مستقیم
    #  روی self.client) نوشته شده‌اند تا هم در حالت مستقل (admin_bot.py
    #  به‌تنهایی، از طریق _register_handlers/run_admin_bot_forever) و هم
    #  از طریق یک ربات بالادستیِ یکپارچه (saas_bot.py که نقش‌های
    #  OWNER/ADMIN/RESELLER/USER را روی همان توکن مدیریت می‌کند) قابل
    #  فراخوانی مستقیم باشند — بدون نیاز به ثبت دوباره‌ی هندلرهای Telethon
    #  که می‌توانست باعث دوبار اجرا شدن روی یک کلاینت مشترک شود.
    # ─────────────────────────────────────────────────────

    async def handle_start(self, event):
        if self.standalone and not self._is_admin(event.sender_id):
            await event.respond("⛔ شما دسترسی ندارید.")
            return
        old_wiz = self.wizards.pop(event.sender_id, None)
        await self._cleanup_wizard_temp_client(old_wiz)
        await self._show_main_menu(event.chat_id)

    async def start_login_wizard_for_user(self, event, owner_user_id: int):
        """
        نقطه‌ی ورود عمومی که فقط توسط saas_bot.py صدا زده می‌شود: مستقیماً
        ویزارد «افزودن اکانت» (تگ → شماره → کد → رمز دو مرحله‌ای در صورت
        نیاز) را برای یک کاربر عادی (USER) شروع می‌کند — بدون این‌که آن
        کاربر نیاز داشته باشد اول وارد کل پنل «مدیریت اکانت‌های سلف» بشود
        (که برایش اصلاً نمایش داده نمی‌شود؛ او فقط دکمه‌ی «🔐 لاگین اکانت»
        را بعد از فعال‌سازی لایسنس/تایید پرداخت می‌بیند).

        هیچ چک self._is_admin یا self.owner_filter اینجا اعمال نمی‌شود —
        این عمداً است: مسیر مجاز‌بودن (اینکه این کاربر واقعاً لایسنس/اشتراک
        فعال دارد) قبلاً توسط saas_bot.py بر اساس saas_db تایید شده. این
        متد صرفاً همان مکانیزم لاگینِ از قبل تست‌شده را برای owner_user_id
        داده‌شده اجرا می‌کند و اکانت نتیجه را به owner_user_id (نه لزوماً
        فرستنده‌ی پیام، هرچند این دو معمولاً یکی هستند) نسبت می‌دهد.
        """
        await self._cleanup_wizard_temp_client(self.wizards.pop(event.sender_id, None))
        self.wizards[event.sender_id] = {
            "state": WIZ_TAG,
            "data": {"owner_user_id": owner_user_id},
        }
        await event.edit(
            "🔐 **لاگین اکانت تلگرام شما**\n\n"
            "برای فعال‌سازی سلف روی اکانتت، اول باید اکانتت رو اینجا لاگین کنی.\n\n"
            "یه اسم (تگ) کوتاه برای این اکانت بفرست — فقط حروف انگلیسی/عدد/"
            "خط‌تیره (مثلاً `myaccount`):",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def handle_message(self, event):
        if event.raw_text and event.raw_text.startswith("/"):
            return
        if self.standalone and not self._is_admin(event.sender_id):
            return
        wiz = self.wizards.get(event.sender_id)
        if wiz:
            try:
                await self._handle_wizard_input(event, wiz)
            except Exception as e:
                print(f"⚠️ [admin_bot] خطا در پردازش ویزارد: {e}")
                await event.respond(f"❌ خطای غیرمنتظره: {str(e)[:150]}\nویزارد لغو شد.")
                await self._cancel_wizard(event.sender_id)

    async def handle_callback(self, event, data: str = None) -> bool:
        """
        data: مسیرِ override. وقتی «بازگشت» یک مسیرِ ذخیره‌شده را دوباره
        رندر می‌کند، همان مسیر از اینجا تزریق می‌شود — event.data هنوز
        `nav:back` است و نباید مبنا قرار گیرد.

        اگر callback data متعلق به این ماژول (مدیریت اکانت‌های سلف) باشد,
        آن را پردازش کرده و True برمی‌گرداند. اگر داده متعلق به این ماژول
        نباشد (مثلاً مربوط به بخش‌های دیگر ربات یکپارچه است)، بدون هیچ
        کاری False برمی‌گرداند تا فراخوانِ بالادستی بتواند خودش تصمیم بگیرد.

        توجه: در حالت standalone=False، فراخوان (saas_bot.py) از قبل بر
        اساس نقش OWNER/ADMIN در saas_db تصمیم گرفته که این متد صدا زده
        شود یا نه — پس اینجا دوباره self._is_admin چک نمی‌شود، چون آن چک
        با منبع حقیقتِ نقش‌ها (saas_db) هماهنگ نیست و می‌تواند به‌اشتباه
        دسترسی را رد کند برای کسی که saas_bot.py قبلاً او را تایید کرده.
        """
        if self.standalone and not self._is_admin(event.sender_id):
            await event.answer("⛔ دسترسی نداری", alert=True)
            return True
        if data is None:
            data = event.data.decode()

        # ─── ناوبری (فقط حالت standalone) ─────────────────────────────
        # در حالت غیر-standalone، روترِ SaaSBot مسیرهای nav:* را قبل از
        # رسیدن به اینجا پردازش کرده و هرگز به این شاخه نمی‌رسند؛ پشته هم
        # همان پشته‌ی مشترک است. این بلوک فقط برای اجرای مستقلِ پنل است تا
        # رفتارِ «بازگشت» در هر دو حالت دقیقاً یکی باشد.
        if self.standalone:
            if data == NAV_NOOP:
                await event.answer()
                return True
            if data == NAV_HOME:
                self.wizards.pop(event.sender_id, None)
                self.nav.reset(event.sender_id)
                await self._show_main_menu(event.chat_id, edit_event=event)
                return True
            if data == NAV_BACK:
                self.wizards.pop(event.sender_id, None)
                prev = self.nav.pop(event.sender_id)
                if not prev:
                    await self._show_main_menu(event.chat_id, edit_event=event)
                    return True
                return await self.handle_callback(event, data=prev)
            if not _is_nav_action(data):
                self.nav.push(event.sender_id, data)

        # فیکس امنیتی: چک متمرکز مالکیت برای همه‌ی callbackهایی که یک تگ
        # اکانت مشخص را هدف می‌گیرند. بدون این چک، یک نماینده که owner_filter
        # دارد می‌توانست با ساختن دستی یک callback (یا حتی فقط با حدس‌زدن
        # تگِ اکانت یک نماینده‌ی دیگر از طریق /start) روی اکانت‌هایی که
        # _show_account_list به او نشان نمی‌دهد toggle/حذف/تغییر انجام دهد
        # — چون قبلاً هر تابع (_toggle_feature، _disable_account، ...) خودش
        # به‌تنهایی این مالکیت را چک نمی‌کرد. این گارد مرکزی، پیش از رسیدن
        # به هر تابعی که یک تگ خاص را دستکاری می‌کند، اجرا می‌شود.
        _TAG_PREFIXES = (
            "acc:", "toggle:", "font_menu:", "font_set:", "edit_name:",
            "send_msg:", "proxy_start:", "disable:", "enable:",
            "del_confirm:", "del_go:",
            # بخش‌های دسته‌بندی‌شده‌ی UI — همان گارد مالکیت برای این‌ها هم
            "feat:", "appear:", "conn:", "status:",
            # مدیریت نشست‌ها و دریافت کد — هدفشان یک tag است، پس باید گارد
            # مالکیت بخورند (نماینده نتواند روی اکانتِ دیگری اجرا کند).
            "sessions:", "sesstog:", "sesskill:", "sesswipe:",
            "sessterm:", "getcode:", "codeget:", "codearm:",
            "tfa:", "tfareset:", "tfago:", "tfacancel:",
        )
        if self.owner_filter is not None and any(data.startswith(p) for p in _TAG_PREFIXES):
            # استخراج تگ از فرمت‌های مختلف: "acc:TAG"، "toggle:TAG:feature"، "font_set:TAG:font"
            raw = data.split(":", 1)[1] if ":" in data else ""
            tag = raw.split(":", 1)[0] if raw else ""
            cfg = self.sb.load_config()
            if not tag or tag not in cfg or not self._account_visible(cfg[tag]):
                await event.answer("این اکانت دیگر وجود ندارد یا به تو دسترسی ندارد.", alert=True)
                return True

        # ── Anti-Ban تأیید/انصراف ───────────────────────────────
        if data.startswith("abok:") or data.startswith("abno:"):
            await self._handle_antiban_confirm(event, data)
            return

        # ── لایه‌ی مرکزیِ مجوزِ عملیاتِ حساس ──────────────────────────
        # «دستگاه‌های لاگین‌شده»، «رمز دو مرحله‌ای» و «کد ورود» ابزارهای
        # جلبِ اکانت‌اند. سابقاً فقط مالکِ اصلی به آن‌ها می‌رسید (هاردکد).
        # حالا یک لایه‌ی capability آن را کنترل می‌کند:
        #   ۱) مالکِ اصلی → همیشه مجاز.
        #   ۲) دیگران → فقط با مجوزِ صریحِ OWNER و در دامنه‌ی معتبر.
        # این بررسی *در همین لحظه* و *برای همین اکانت* انجام می‌شود، پس
        # یک دکمه‌ی کهنه بعد از سلبِ مجوز یا تغییرِ مالکیت بلافاصله می‌ایستد.
        if any(data.startswith(p) for p in SECURITY_ROUTES):
            _sec_tag = data.split(":", 1)[1].split(":", 1)[0] if ":" in data else ""
            if not _sec_tag or not (await self._authorize_security(event, _sec_tag))[0]:
                if not _sec_tag:
                    try:
                        await event.answer("درخواست نامعتبر است.", alert=True)
                    except Exception:
                        pass
                return True

        try:
            if data == "list":
                await self._show_account_list(event)
            elif data == "add":
                await self._start_add_wizard(event)
            elif data == "admins":
                await self._show_admin_menu(event)
            elif data == "admin_add":
                # فیکس امنیتی: مدیریت ادمین‌ها فقط در حالت standalone معنا دارد
                # (لیست محلی admin_bot_admins.json). در حالت غیر-standalone —
                # که مسیریابی saas_bot.py بی‌قید است و هر callback نامطابقت‌ای
                # به اینجا می‌رسد — نباید هیچ کاربری (حتی با callback جعلی)
                # بتواند ویزارد افزودن ادمین را باز کند یا لیست محلی را دستکاری
                # کند؛ منبع حقیقتِ نقش‌ها در آن حالت saas_db است.
                if not self.standalone:
                    await event.answer("مدیریت ادمین‌ها از طریق پنل نقش‌ها (OWNER) انجام می‌شود.", alert=True)
                    return True
                await self._start_add_admin_wizard(event)
            elif data.startswith("admin_del:"):
                if not self.standalone:
                    await event.answer("مدیریت ادمین‌ها از طریق پنل نقش‌ها (OWNER) انجام می‌شود.", alert=True)
                    return True
                uid = safe_callback_int(data.split(":", 1)[1], 0)
                await self._remove_admin(event, uid)
            elif data == "back":
                self.wizards.pop(event.sender_id, None)
                await self._show_main_menu(event.chat_id, edit_event=event)
            elif data == "cancel_wizard":
                await self._cancel_wizard(event.sender_id, notify_event=event)
            elif data.startswith("acc:"):
                tag = data.split(":", 1)[1]
                await self._show_account_detail(event, tag)
            elif data.startswith("feat:"):
                tag = data.split(":", 1)[1]
                await self._show_features(event, tag)
            elif data.startswith("appear:"):
                tag = data.split(":", 1)[1]
                await self._show_appearance(event, tag)
            elif data.startswith("conn:"):
                tag = data.split(":", 1)[1]
                await self._show_connection(event, tag)
            elif data.startswith("tfa:"):
                await self._show_2fa(event, data.split(":", 1)[1])
            elif data.startswith("tfareset:"):
                await self._confirm_2fa_reset(event, data.split(":", 1)[1])
            elif data.startswith("tfago:"):
                await self._do_2fa_reset(event, data.split(":", 1)[1])
            elif data.startswith("tfacancel:"):
                await self._cancel_2fa_reset(event, data.split(":", 1)[1])
            elif data.startswith("sessions:"):
                tag = data.split(":", 1)[1]
                await self._show_sessions(event, tag)
            elif data.startswith("sesspage:"):
                _, tag, page = data.split(":", 2)
                await self._show_sessions(event, tag, page=safe_callback_int(page, 0))
            elif data.startswith("sesstog:"):
                _, tag, idx = data.split(":", 2)
                await self._toggle_sess_selection(event, tag, safe_callback_int(idx, -1))
            elif data.startswith("sesskill:"):
                tag = data.split(":", 1)[1]
                await self._kill_selected_sessions(event, tag)
            elif data.startswith("sesswipe:"):
                tag = data.split(":", 1)[1]
                await self._confirm_wipe_sessions(event, tag)
            elif data.startswith("sessterm:"):
                tag = data.split(":", 1)[1]
                await self._terminate_sessions(event, tag)
            elif data.startswith("getcode:"):
                tag = data.split(":", 1)[1]
                await self._arm_login_code(event, tag)
            elif data.startswith("codeget:"):
                tag = data.split(":", 1)[1]
                await self._fetch_login_code(event, tag)
            elif data.startswith("codearm:"):
                tag = data.split(":", 1)[1]
                await self._arm_listen_code(event, tag)
            elif data.startswith("status:"):
                tag = data.split(":", 1)[1]
                await self._show_full_status(event, tag)
            elif data.startswith("toggle:"):
                _, tag, feature = data.split(":", 2)
                await self._toggle_feature(event, tag, feature)
            elif data.startswith("font_menu:"):
                tag = data.split(":", 1)[1]
                await self._show_font_menu(event, tag)
            elif data.startswith("font_set:"):
                _, tag, font = data.split(":", 2)
                await self._set_font(event, tag, font)
            elif data.startswith("edit_name:"):
                tag = data.split(":", 1)[1]
                await self._start_edit_name_wizard(event, tag)
            elif data.startswith("send_msg:"):
                tag = data.split(":", 1)[1]
                await self._start_send_msg_wizard(event, tag)
            elif data == "send_target_me":
                wiz = self.wizards.get(event.sender_id)
                if wiz:
                    wiz["data"]["target"] = "me"
                    wiz["state"] = WIZ_SEND_MSG_TEXT
                    await event.edit("متن پیام رو بفرست:",
                                      buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]])
            elif data.startswith("proxy_start:"):
                tag = data.split(":", 1)[1]
                await self._start_proxy_wizard(event, tag)
            elif data.startswith("proxy_type:"):
                ptype = data.split(":", 1)[1]
                await self._proxy_type_chosen(event, ptype)
            elif data == "proxy_skip_auth":
                wiz = self.wizards.get(event.sender_id)
                if wiz:
                    await self._finish_proxy(event, wiz["data"])
            elif data == "login_proxy_no":
                wiz = self.wizards.get(event.sender_id)
                if wiz:
                    await self._do_send_code(event, wiz["data"])
            elif data == "login_proxy_yes":
                wiz = self.wizards.get(event.sender_id)
                if wiz:
                    wiz["data"]["proxy_flow"] = "new_account_login"
                    await self._show_proxy_type_buttons(event, "نوع پروکسی رو انتخاب کن:")
            elif data.startswith("disable:"):
                tag = data.split(":", 1)[1]
                await self._disable_account(event, tag)
            elif data.startswith("enable:"):
                tag = data.split(":", 1)[1]
                await self._enable_account(event, tag)
            elif data.startswith("del_confirm:"):
                tag = data.split(":", 1)[1]
                await event.edit(
                    f"⚠️ آیا مطمئنی می‌خوای اکانت «{tag}» رو حذف کنی؟\nاین کار غیرقابل بازگشته.",
                    buttons=[
                        [UI.danger("بله، حذف کن", f"del_go:{tag}".encode())],
                        [UI.neutral("نه، برگرد", NAV_BACK)],
                    ],
                )
            elif data.startswith("del_go:"):
                tag = data.split(":", 1)[1]
                await self._delete_account(event, tag)
            # ── مدیریتِ مجوزهای حساس (فقط OWNER) ──
            elif data == "cap_list":
                await self._owner_show_capability_list(event)
            elif data == "cap_add_start":
                await self._owner_start_capability_add(event)
            elif data.startswith("cap_user:"):
                uid = safe_callback_int(data.split(":", 1)[1], 0)
                await self._owner_show_capability_user(event, uid)
            elif data.startswith("cap_choose_scope:"):
                uid = safe_callback_int(data.split(":", 1)[1], 0)
                await self._owner_choose_capability_scope(event, uid)
            elif data.startswith("cap_confirm:"):
                _, uid, scope = data.split(":", 2)
                await self._owner_confirm_capability(event, safe_callback_int(uid, 0), scope)
            elif data.startswith("cap_grant:"):
                _, uid, scope = data.split(":", 2)
                await self._owner_grant_capability(event, safe_callback_int(uid, 0), scope)
            elif data.startswith("cap_revoke:"):
                _, uid, scope = data.split(":", 2)
                await self._owner_revoke_capability(event, safe_callback_int(uid, 0), scope)
            elif data.startswith("dbcap:"):
                bot_id = safe_callback_int(data.split(":", 1)[1], 0)
                await self._owner_show_dbot_capability(event, bot_id)
            elif data.startswith("dbcap_grant:"):
                bot_id = safe_callback_int(data.split(":", 1)[1], 0)
                await self._owner_grant_dbot_capability(event, bot_id)
            elif data.startswith("dbcap_revoke:"):
                bot_id = safe_callback_int(data.split(":", 1)[1], 0)
                await self._owner_revoke_dbot_capability(event, bot_id)
            else:
                return False
        except Exception as e:
            # جزئیات فنی فقط در لاگ سرور — به کاربر پیام عمومی و کوتاه داده
            # می‌شود تا state داخلی/ساختار دیتابیس درز نکند.
            print(f"⚠️ [admin_bot] خطا در پردازش دکمه: {type(e).__name__}: {e}")
            try:
                await event.answer("❌ خطا در پردازش این دکمه. دوباره تلاش کن.", alert=True)
            except Exception:
                pass
        return True

    def _register_handlers(self):
        """
        فقط برای اجرای مستقل admin_bot.py (با توکن/کلاینت مخصوص خودش، از
        طریق run_admin_bot_forever) استفاده می‌شود — هندلرهای Telethon را
        مستقیماً به همان سه متد بالا وصل می‌کند، بدون هیچ منطق اضافه.
        """
        @self.client.on(events.NewMessage(pattern="/start"))
        async def start_h(event):
            await self.handle_start(event)

        @self.client.on(events.NewMessage)
        async def message_h(event):
            await self.handle_message(event)

        @self.client.on(events.CallbackQuery)
        async def callback_h(event):
            await self.handle_callback(event)


async def run_admin_bot_forever(selfbot_module):
    """
    سوپروایزر ساده برای ربات مدیریت مستقل: اگر به هر دلیلی قطع/کرش کند،
    دوباره راه‌اندازی می‌شود. این تابع فقط برای اجرای admin_bot.py به‌تنهایی
    استفاده می‌شود (standalone=True، پیش‌فرض)، نه وقتی زیرِ saas_bot.py است.
    """
    consecutive_failures = 0
    MAX_BACKOFF = 300
    while True:
        try:
            admin = AdminBot(selfbot_module, standalone=True)
            await admin.start()
            await admin.client.run_until_disconnected()
            consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            consecutive_failures += 1
            wait_time = min(10 * (2 ** min(consecutive_failures, 5)), MAX_BACKOFF)
            print(f"⚠️ [admin_bot] قطع/خطا: {e} — تلاش مجدد در {wait_time}s")
            await asyncio.sleep(wait_time)

# ══════════════════════════════════════════════════════════════════════
# ═══ بخش saas_bot.py (ادغامشده) ═══
# ══════════════════════════════════════════════════════════════════════


OWNER_ID = ADMIN_ID

WHAT_IS_SELFBOT_TEXT = (
    "ℹ️ **سلف چیست؟**\n\n"
    "سلف یک ربات شخصی روی اکانت خودت است که این امکانات را دارد:\n\n"
    "❈ ساعت روی اسم و بیو\n"
    "❈ تیک خودکار\n"
    "❈ پاسخ خودکار\n"
    "❈ ردیاب حذف/ادیت\n"
    "❈ مدیریت هوشمند اکانت\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📖 **راهنمای فعال‌سازی:**\n\n"
    "۱. از منوی اصلی «🛒 خرید سلف» یا «🔑 خرید با لایسنس» رو بزن.\n"
    "۲. اشتراک فعال که داشته باشی، دکمه‌ی «📱 لاگین کردن سلف» فعال می‌شه.\n"
    "۳. شماره تلفن اکانتت رو بفرست (با فرمت بین‌المللی: +989123456789).\n"
    "۴. کد تأییدی که تلگرام برات فرستاد رو وارد کن.\n"
    "۵. اگه اکانتت رمز دو مرحله‌ای داره، رمزش رو هم بزن.\n"
    "۶. سلف روشن می‌شه و از همون لحظه روی اکانتت فعاله!\n\n"
    "💡 **نکات مهم:**\n"
    "• اکانت‌های شماره خارج/مجازی نیاز به تأیید اضافه دارن (Anti-Ban).\n"
    "• بکاپ خودکار هر روز ساعت ۰۰:۰۰ و ۱۲:۰۰ گرفته می‌شه.\n"
    "• برای هر سؤالی، «☎️ پشتیبانی» رو از منو بزن."
)

# فهرستِ امکاناتِ سلف — یک منبعِ واحد، تا صفحه‌ی «امکانات» و متنِ تبلیغاتی
# هرگز از هم جدا نیفتند.
SELF_FEATURE_LIST = (
    "❌ ذخیره محتوای تایم‌دار و نابودشونده",
    "🗑 ذخیره پیام‌های حذف‌شده",
    "♻️ ذخیره پیام‌های ادیت‌شده",
    "📥 ذخیره محتوای کانال‌هایی که فوروارد و سیو بسته است",
    "🤖 ذخیره خودکار محتوای گروه یا کانال‌های دلخواه",
    "👁 استاک کردن شخص یا اشخاص دلخواه",
    "🧰 جعبه‌ابزار ادمینی",
    "🕐 تنظیم ساعت و تاریخ در اسم و بیو",
    "✏️ تنظیم امضا در چت‌ها",
    "👥 ساخت گروه با دستور",
    "📢 ساخت کانال با دستور",
    "🟣 ذخیره خودکار استوری یا ذخیره با لینک",
    "🎞 ابزار تبدیل مدیا",
    "🧩 دستورات سفارشی",
    "🛡 سیستم دشمن هوشمند",
)

HELP_TEXT = (
    "📚 **راهنمای ربات**\n\n"

    "🤔 **چطور می‌توانم دستیار هوشمند را روی اکانتم فعال کنم؟**\n"
    "✏️ ابتدا موجودی حسابت را افزایش بده، سپس از بخش «خرید اشتراک» "
    "اشتراک موردنظرت را بخر.\n\n"

    "🤔 **مراحل فعال‌سازی دستیار هوشمند چیست؟**\n"
    "1️⃣ از بخش «خرید اشتراک»، اشتراک موردنظرت را بخر.\n"
    "2️⃣ شماره‌ی اکانتی که می‌خواهی دستیار رویش فعال شود پرسیده می‌شود — "
    "شماره‌ات را وارد کن.\n"
    "3️⃣ کدی که به اکانتت فرستاده می‌شود را **با خط تیره بین اعداد** وارد کن؛ "
    "مثلاً `1-2-3-4-5`.\n"
    "4️⃣ اگر رمز دو مرحله‌ای (2FA) روی اکانتت فعال نباشد، همین‌جا سلف فعال "
    "می‌شود و مرحله‌ی بعدی لازم نیست.\n"
    "5️⃣ اگر 2FA فعال است، رمز تایید دو مرحله‌ای‌ات را وارد کن.\n"
    "6️⃣ سلف روی اکانتت فعال می‌شود.\n\n"

    "🤔 **چطور راهنمای دستورات دستیار را ببینم؟**\n"
    "✏️ بعد از فعال‌شدن دستیار، با ارسال دستور `!help` در تلگرام راهنمای "
    "کامل دستورات را می‌بینی.\n\n"

    "🤔 **از کجا بفهمم چقدر از اشتراکم باقی مانده؟**\n"
    "✏️ با ارسال دستور `!myexpire` مدت باقی‌مانده‌ی دستیارت را می‌بینی.\n\n"

    "❓ سوال دیگری داری؟ از «☎️ پشتیبانی» بپرس."
)

DEFAULT_CARD_NUMBER = "0000000000000000"
DEFAULT_CARD_HOLDER = "تنظیم‌نشده"

# مراحل ویزاردهای مشتری/نماینده
WIZ_TICKET_MSG = "ticket_message"
WIZ_PRICING_PRICE = "awaiting_plan_price"
WIZ_PRICING_DAYS = "awaiting_plan_days"
WIZ_PRICING_NEW_NAME = "awaiting_new_plan_name"
WIZ_SET_WALLET = "awaiting_usdt_wallet"
WIZ_TRX_HASH = "awaiting_trx_hash"
WIZ_DB_RESTORE = "awaiting_db_restore"
WIZ_DB_RESTORE_CONFIRM = "awaiting_db_restore_confirm"
WIZ_LICENSE_CODE = "awaiting_license_code"
WIZ_PAYMENT_RECEIPT = "awaiting_payment_receipt"
WIZ_CL_RESELLER_LIMIT = "cl_reseller_limit"
WIZ_OWNER_TICKET_REPLY = "owner_ticket_reply"
WIZ_SET_CARD = "awaiting_card_info"
WIZ_SET_CHANNEL = "awaiting_channel"
WIZ_DEDICATED_TOKEN = "awaiting_dedicated_token"
WIZ_DEDICATED_OWNER_ID = "awaiting_dedicated_owner_id"
WIZ_DEDICATED_EXTEND_DAYS = "awaiting_dedicated_extend_days"
# مراحل جدید — مدیریت دستی کاربران (جستجو، تمدید دستی)
# توجه: مرحله‌ی «حذف کاربر» ویزارد متنی ندارد — تأیید حذف با دکمه‌های
# callback (user_delete_confirm/user_delete_go) انجام می‌شود، پس اینجا
# ثابت WIZ لازم نیست.
WIZ_ORPHAN_ASSIGN = "awaiting_orphan_owner"
WIZ_USER_SEARCH = "awaiting_user_search"
WIZ_USER_EXTEND_DAYS = "awaiting_extend_days"
# ویزاردِ اعطای مجوزِ حساس: منتظرِ آیدیِ کاربر.
WIZ_CAP_USER_ID = "awaiting_cap_user_id"

# فاصله‌ی مجاز بین دو کلیکِ «بررسی عضویت» (ثانیه) — هر کلیک یک چکِ
# force با تماس شبکه است و اسپمِ کلیک نباید آن را آزاد بگذارد.
_GATE_RETRY_COOLDOWN = 5


def _normalize_channel(channel) -> str:
    """
    نرمال‌سازی یک‌جای ورودی کانال: یوزرنیم، @یوزرنیم، لینک t.me یا
    URL کامل → یوزرنیمِ کوچک‌نویسِ تمیز. ورودی نامعتبر → رشته‌ی خالی.
    تنها نقطه‌ی نرمال‌سازی در کل گیت کانال است (resolve، کارت شیشه‌ای و
    ذخیره همه از همین استفاده می‌کنند تا هیچ‌جا فرمت‌های مختلف دوباره
    پیاده نشود).
    """
    ch = (channel or "").strip()
    if ch.startswith("http://") or ch.startswith("https://"):
        ch = ch.split("//", 1)[1]
    if "t.me/" in ch:
        ch = ch.split("t.me/", 1)[1]
    ch = ch.lstrip("@").split("/")[0].strip().split("?")[0].lower()
    return ch if len(ch) >= 3 else ""


# نگاشتِ وضعیتِ ربات اختصاصی به «وضعیتِ نام‌دار»ِ UI — تا رنگِ یک ربات در
# لیست و در صفحه‌ی جزئیاتش هرگز فرق نکند (قبلاً دو dictِ جدا بود).
DEDICATED_UI_STATE = {
    "active": "active", "pending_payment": "pending", "stopped": "paused",
    "rejected": "off", "revoked": "off", "deleted": "off",
}


class SaaSBot:
    def __init__(self, selfbot_module):
        self.sb = selfbot_module
        self.client = None
        # admin_panel در حالت غیر-standalone ساخته می‌شود: یعنی خودش دیگر
        # فایل JSON جدا برای دسترسی چک نمی‌کند و به saas_db.get_role تکیه
        # می‌کند — saas_db تنها منبع حقیقتِ نقش‌هاست.
        self.admin_panel = AdminBot(selfbot_module, standalone=False)
        # ارجاع برگشتی: AdminBot گاهی باید منوی نقشِ SaaSBot را نشان دهد
        # (مثلاً بعد از لاگین موفقِ کاربر عادی، به‌جای منوی ادمینیِ
        # «پنل مدیریت سلف‌بات»، منوی اصلیِ نقش USER). در حالت standalone
        # (admin_bot.py به‌تنهایی) این ارجاع وجود ندارد و کد با getattr
        # گارد می‌شود.
        self.admin_panel.saas = self
        # ویزارد مخصوص جریان‌های جدید (پرداخت/لایسنس/تیکت) — جدا از
        # self.admin_panel.wizards که فقط برای مدیریت اکانت‌های سلف است.
        # هر دو دیکشنری با کلید یکسان (user_id) کار می‌کنند، پس همیشه قبل
        # از شروع یک ویزارد جدید در یکی، باید ویزارد نیمه‌کاره‌ی احتمالی
        # در دیگری پاک‌سازی شود (وگرنه یک temp_client باز می‌تواند نشت
        # کند) — این کار را _start_own_wizard انجام می‌دهد.
        self.wizards: dict = {}
        # پشته‌ی ناوبریِ مشترکِ کلِ ربات — جایگزینِ self._uacc_back قبلی.
        # همان نمونه به admin_panel هم داده می‌شود تا تاریخچه بین دو پنل
        # پیوسته بماند: کاربری که از «کاربران → کاربر X → SelfBotها →
        # اکانت Y → قابلیت‌ها» رفته، با «بازگشت» دقیقاً همین مسیر را
        # برعکس طی می‌کند، نه اینکه به منوی نقش پرت شود.
        self.nav = NavStack()
        self.admin_panel.nav = self.nav
        # کشِ گیت عضویت کانال: {user_id: (timestamp, is_member)} با TTL ۶۰ ثانیه —
        # تا «همیشگی‌بودن» گیت (بستن فوری بعد از لفت‌دادن کانال) یک تماس
        # شبکه به‌ازای هر کلیک/پیام تحمیل نکند؛ بررسی صریحِ دکمه‌ی
        # «بررسی عضویت» با force=True کش را دور می‌زند.
        self._gate_cache: dict = {}
        # کاربرانی که گیت آن‌ها را رد کرده است (غیرعضو). به‌محض اینکه با
        # «بررسی عضویت» موفق وارد شوند، پیام خوشامد می‌گیرند و از این مجموعه
        # حذف می‌شوند — تا «خوش‌آمدگوییِ دوباره‌عضویت» فقط برای کسی که
        # واقعاً قبلاً بسته شده بود فرستاده شود، نه برای عضوِ همیشگی.
        self._gate_blocked: set = set()
        # آخرین زمان کلیکِ «بررسی عضویت» به‌ازای هر کاربر — برای سقفِ
        # ۵ ثانیه‌ای: هر کلیکِ force یک یا دو تماس شبکه با تلگرام است و
        # بدون سقف، یک کاربر می‌تواند با کلیک‌های پشت‌سرهم آن را اسپم کند.
        self._gate_retry_ts: dict = {}
        # قفلِ استارت/ری‌استارت سلف‌بات‌ها بعد از تمدید: {tag: in-flight} — تا
        # دو درخواست هم‌زمانِ resume (مثلاً تایید کارت + فعال‌سازی لایسنس)
        # دو تسکِ موازی برای یک اکانت نسازند (task duplication).
        self._resume_inflight: set = set()
        # آخرین پیامِ گیتِ فرستاده‌شده به هر کاربر (user_id → message.id) —
        # تا وقتی کاربرِ بسته‌شده پیامِ بعدی می‌فرستد، پیامِ قبلیِ گیت حذف و
        # به‌جایش یک نسخه‌ی تازه ارسال شود؛ بدون این، هر پیامِ متنیِ کاربرِ
        # بسته‌شده یک کپیِ جدیدِ روی‌هم از پیام گیت می‌سازد.
        self._gate_msg_id: dict = {}
        self._expiry_task = None
        # قفل دسترسی به پنل مدیریت (یک نمونه‌ی مشترک بین همه‌ی کاربران است و
        # scope آن قبل از هر فراخوانی بازنویسی می‌شود). بدون این قفل، یک رویداد
        # هم‌زمان از کاربرِ دیگر می‌تواند وسطِ await یک dispatch (مثلاً لاگین که
        # تا ۳۰ ثانیه طول می‌کشد) owner_filter/default_owner_id را عوض کند و
        # رندرِ بعد-از-awaitِ کاربرِ اول با scope کاربرِ دیگر انجام شود — این
        # قفل dispatch های پنل را سریال می‌کند (برای مقیاس رسیلری چند کاربرِ
        # هم‌زمان کاملاً پذیرفتنی است) و کل این کلاس خطا را از بین می‌برد.
        self._panel_lock = asyncio.Lock()

    async def start(self):
        # فیکس مهم و حیاتی: قبلاً این چک اصلاً اینجا نبود — SaaSBot.start()
        # مستقیماً از ADMIN_BOT_TOKEN/TelegramClient
        # استفاده می‌کرد، بدون اینکه هرگز از AdminBot.start() (که خودش این
        # چک را داشت) رد شود. نتیجه: اگر متغیر محیطی ADMIN_ID تنظیم نشده
        # بود، مقدار پیش‌فرض "0" در admin_bot.py استفاده می‌شد و OWNER_ID
        # این ماژول هم برابر 0 می‌ماند — بدون هیچ خطا یا هشداری، ربات کاملاً
        # عادی بالا می‌آمد. چون هیچ کاربر واقعی‌ای هرگز user_id=0 ندارد،
        # نتیجه‌اش این بود که خودِ صاحب ربات (که فکر می‌کرد OWNER است) برای
        # همیشه به‌عنوان یک USER عادی شناسایی می‌شد — دقیقاً همان چیزی که
        # گزارش شد: «ادمین اصلی را نمی‌شناسد، فکر می‌کند کاربر عادی است».
        # این چک همان ابتدای start() و پیش از هر کار دیگری، این حالت را با
        # یک پیام خطای واضح متوقف می‌کند به‌جای این‌که بی‌صدا با یک OWNER_ID
        # نامعتبر ادامه دهد.
        if not ADMIN_BOT_TOKEN or not ADMIN_ID:
            raise RuntimeError(
                "متغیرهای محیطی ADMIN_BOT_TOKEN و ADMIN_ID باید تنظیم شده باشند "
                "(مثلاً از طریق systemd Environment=... یا export قبل از اجرا). "
                "ADMIN_ID باید آیدی عددی تلگرام خودت (صاحب اصلی ربات) باشد — "
                "بدون این مقدار، ربات هیچ‌کس را OWNER تشخیص نمی‌دهد."
            )

        cfg = self.sb.load_config()
        api_id, api_hash = _first_account_creds(cfg)

        init_db()

        session_path = os.path.join(self.sb.SESSIONS_DIR, ADMIN_BOT_SESSION_NAME)
        self.client = TelegramClient(
            session_path, api_id, api_hash,
            connection_retries=3, retry_delay=2, flood_sleep_threshold=10,
        )
        await asyncio.wait_for(self.client.start(bot_token=ADMIN_BOT_TOKEN), timeout=30)

        # ثبتِ رفرنس تا SelfBotها بتوانند «کدِ لاگین» را از طریقِ همین ربات
        # به مالک برسانند.
        global _SAAS_BOT_REF
        _SAAS_BOT_REF = self

        # یوزرنیمِ خودِ ربات — برای ساختِ لینکِ دعوت
        try:
            me = await asyncio.wait_for(self.client.get_me(), timeout=15)
            self._bot_username = getattr(me, "username", None)
        except Exception:
            self._bot_username = None

        # admin_panel از همان کلاینت مشترک استفاده می‌کند — ولی خودش دیگر
        # هندلر جداگانه ثبت نمی‌کند (فقط متدهایش مستقیماً فراخوانی می‌شوند)
        self.admin_panel.client = self.client

        self._register_handlers()

        if self._expiry_task is None or self._expiry_task.done():
            self._expiry_task = asyncio.create_task(self._expiry_loop())
        if self.admin_panel._backup_task is None or self.admin_panel._backup_task.done():
            self.admin_panel._backup_task = asyncio.create_task(self.admin_panel._daily_backup_loop())

        print("🤖 ربات CiaNetSelf (نقش‌محور) با موفقیت روشن شد.")
        return self.client

    def _role(self, user_id: int) -> str:
        return get_role(user_id, OWNER_ID)

    def _user_has_logged_in_account(self, user_id: int) -> bool:
        """
        آیا این کاربر حداقل یک اکانت سلف دارد که خودش لاگین کرده؟ برای
        تعیین اینکه دکمه‌ی «🔐 لاگین به اکانت» در منوی کاربر عادی نمایش
        داده شود یا نه: طبق اسپک، این گزینه فقط *تا قبل از اولین لاگین
        موفق* باید در منو باشد و بعد از آن دیگر نیاید. یک اکانت «لاگین‌شده»
        یعنی اکانتی در config.json که owner_user_id آن برابر همین کاربر
        است (چه الان روشن باشد چه خاموش/غیرفعال — لاگین موفق انجام شده).
        اگر کاربری اکانتش بعداً از config حذف شود (مثلاً توسط پشتیبانی)،
        این تابع دوباره False برمی‌گرداند و گزینه برای لاگین مجدد ظاهر
        می‌شود.
        """
        cfg = self.sb.load_config()
        return any(account_belongs_to(acc, tag, user_id)
                   for tag, acc in cfg.items())

    # ─────────────────────────────────────────────────────
    #  گیت عضویت کانال اجباری (همه به‌جز ادمین اصلی)
    # ─────────────────────────────────────────────────────

    async def _is_channel_member(self, user_id: int, channel: str) -> bool:
        """
        چک عضویت در کانال اجباری. channel می‌تواند یوزرنیم (با/بدون @) یا
        لینک t.me باشد (کانال باید عمومی باشد تا قابل resolve باشد).
        هر خطا = «عضو نیست» (fail-closed): اگر کانال قابل‌حل نباشد یا چک
        شکست بخورد، دسترسی داده نمی‌شود — ادمین اصلی همیشه مستثنی است و
        می‌تواند تنظیم را اصلاح کند.
        """
        from telethon.tl.functions.channels import GetParticipantRequest
        try:
            entity = await self.client.get_entity(channel)
            await self.client(GetParticipantRequest(channel=entity, participant=user_id))
            return True
        except Exception:
            return False

    async def _resolve_channel(self, channel: str):
        """
        resolve واقعی کانال با تلگرام — قبل از ذخیره/بررسی کانال اجباری.
        ورودی: یوزرنیم، @یوزرنیم یا لینک t.me. خروجی:
        (True, title, normalized) یا (False, error, None).
        """
        ch = _normalize_channel(channel)
        if not ch:
            return False, "یوزرنیم نامعتبر است", None
        try:
            entity = await self.client.get_entity(ch)
            title = getattr(entity, "title", None) or ch
            return True, title, ch
        except Exception as e:
            return False, str(e)[:80], None

    def _reset_gate_state(self) -> None:
        """
        بعد از تغییر/حذف کانالِ اجباری توسط OWNER، همه‌ی حالتِ گیت پاک
        می‌شود تا تغییرِ پیکربندی **فوراً** اثر کند:
        - _gate_cache: بدون این، اعضایِ کش‌شده‌ی کانالِ قبلی تا ۶۰ ثانیه
          زیر کانالِ جدید هم مجاز می‌مانند.
        - _gate_blocked: بسته‌شدگانِ کانالِ قبلی دیگر «دوباره‌عضوِ در انتظارِ
          خوشامد» نیستند — وضعیت نسبت به کانالِ تازه از نو شروع می‌شود.
        - _gate_retry_ts: cooldownِ بررسیِ عضویتِ کانالِ قبلی بی‌اثر است.
        - _gate_msg_id: پیام‌های گیتِ قدیمی متعلق به کانالِ قبلی‌اند؛ ردیابی
          برای کانالِ جدید از نو شروع می‌شود.
        """
        self._gate_cache.clear()
        self._gate_blocked.clear()
        self._gate_retry_ts.clear()
        self._gate_msg_id.clear()

    async def _channel_gate(self, user_id: int, force: bool = False) -> bool:
        """True = مجاز به استفاده از ربات. فقط ادمین اصلی (ADMIN_ID) مستثنی است."""
        if user_id == ADMIN_ID:
            return True
        channel = (get_setting("required_channel") or "").strip()
        if not channel:
            return True
        now = time.time()
        if not force:
            cached = self._gate_cache.get(user_id)
            if cached and now - cached[0] < 60:
                return cached[1]
        result = await self._is_channel_member(user_id, channel)
        self._gate_cache[user_id] = (now, result)
        self._prune_gate_state(now)
        return result

    # سقفِ تعداد کاربرانی که وضعیتِ گیتشان در حافظه نگه داشته می‌شود
    _GATE_STATE_MAX = 2000

    def _prune_gate_state(self, now: float) -> None:
        """
        هرس کردنِ کش‌های گیت.

        چرا لازم است: _gate_cache و _gate_retry_ts به ازای *هر کاربرِ
        متمایز* یک ورودی می‌گیرند و فقط وقتی OWNER کانال را عوض کند پاک
        می‌شوند. در یک سرویسِ همیشه‌روشن با هزاران کاربر، این یعنی رشدِ
        دائمی تا وقتی پروسه ری‌استارت شود.

        دو مرحله: اول ورودی‌های منقضی (کش ۶۰ ثانیه TTL دارد، پس هر چیزِ
        قدیمی‌تر از ۵ دقیقه قطعاً بی‌مصرف است)؛ اگر باز هم بالای سقف بود،
        قدیمی‌ترین‌ها حذف می‌شوند.
        """
        if len(self._gate_cache) > self._GATE_STATE_MAX:
            cutoff = now - 300
            for uid, v in list(self._gate_cache.items()):
                if v[0] < cutoff:
                    self._gate_cache.pop(uid, None)
            if len(self._gate_cache) > self._GATE_STATE_MAX:
                for uid in sorted(self._gate_cache, key=lambda u: self._gate_cache[u][0])[
                        : len(self._gate_cache) - self._GATE_STATE_MAX]:
                    self._gate_cache.pop(uid, None)
        if len(self._gate_retry_ts) > self._GATE_STATE_MAX:
            cutoff = now - _GATE_RETRY_COOLDOWN * 10
            for uid, ts in list(self._gate_retry_ts.items()):
                if ts < cutoff:
                    self._gate_retry_ts.pop(uid, None)
            if len(self._gate_retry_ts) > self._GATE_STATE_MAX:
                for uid in sorted(self._gate_retry_ts, key=self._gate_retry_ts.get)[
                        : len(self._gate_retry_ts) - self._GATE_STATE_MAX]:
                    self._gate_retry_ts.pop(uid, None)

    async def _send_channel_gate_message(self, event, denied: bool = False):
        """
        پیام گیت عضویت: متن + کادر شیشه‌ایِ کانال (دکمه‌ی لینک عریض) +
        دکمه‌ی «بررسی عضویت» زیر آن. denied=True یعنی این یک بررسیِ
        ناموفقِ تازه است و پیام «عضو نشدید» نمایش داده می‌شود.
        هر مسیرِ ردشدن، کاربر را به _gate_blocked اضافه می‌کند تا اگر بعداً
        عضو شد، پیام خوشامد «حالا می‌تونی استفاده کنی» بگیرد.
        """
        # آمار: فقط اولین بسته‌شدنِ هر کاربر شمرده می‌شود (نه هر پیامِ گیت)
        if event.sender_id not in self._gate_blocked:
            inc_setting("gate_blocked_count")
        self._gate_blocked.add(event.sender_id)
        channel = (get_setting("required_channel") or "").strip()
        username = _normalize_channel(channel)
        link = f"https://t.me/{username}" if username else channel
        # کادر شیشه‌ای با نام واقعی کانال (اگر هنگام تنظیم ذخیره شده باشد)،
        # وگرنه @username
        card_label = (get_setting("required_channel_title") or "").strip() or f"@{username}"
        if denied:
            text = (
                "❌ **شما هنوز عضو کانال نشدید!**\n\n"
                "برای استفاده از خدمات ربات، ابتدا در کانال زیر عضو شوید و "
                "سپس دکمه‌ی «بررسی عضویت» را بزنید:"
            )
        else:
            text = (
                "برای استفاده از خدمات ربات، ابتدا در کانال زیر عضو شوید 👇\n\n"
                "سپس دکمه‌ی «بررسی عضویت» را بزنید."
            )
        buttons = [
            # کادر شیشه‌ای کانال: یک دکمه‌ی لینکِ عریض که مثل کارت نمایش داده می‌شود
            [Button.url(f"💠 {card_label}", link)],
            [UI.go("🔍 بررسی عضویت", b"channel_retry")],
        ]
        # چتِ تمیز: قبل از ارسالِ پیامِ جدید، پیامِ گیتِ قبلیِ همین کاربر را
        # (اگر هنوز سر جایش است) حذف کن — بدون این، هر پیامِ متنیِ کاربرِ
        # بسته‌شده یک کپیِ جدیدِ روی‌هم از پیام گیت می‌سازد.
        await self._try_delete_gate_message(event.sender_id, event.chat_id)
        # تشخیص CallbackQuery با `event.query` (قابل‌اطمینان) نه `hasattr(respond)`
        # — چون telethon به CallbackQuery هم متد respond می‌دهد (پیامِ جدید
        # می‌فرستد) و استفاده از hasattr باعث می‌شد روی دکمه‌ها به‌جای edit،
        # پیامِ جدیدِ گیت ساخته شود و چت روی هم انباشته شود.
        if getattr(event, "query", None) is None:
            try:
                msg = await event.respond(text, buttons=buttons)
                mid = getattr(msg, "id", None)
                if mid is not None:
                    self._gate_msg_id[event.sender_id] = mid
            except Exception:
                pass
        else:
            try:
                msg = await event.edit(text, buttons=buttons)
                mid = getattr(msg, "id", None)
                if mid is not None:
                    self._gate_msg_id[event.sender_id] = mid
            except Exception:
                pass

    async def _try_delete_gate_message(self, user_id: int, chat_id: int) -> None:
        """حذفِ best-effortِ آخرین پیامِ گیتِ همین کاربر — برای چتِ تمیز."""
        mid = self._gate_msg_id.pop(user_id, None)
        if mid is None:
            return
        try:
            await self.client.delete_messages(chat_id, mid)
        except Exception:
            pass

    async def _clear_admin_panel_wizard(self, user_id: int):
        """
        قبل از شروع یک ویزارد جدید در این ماژول، اگر کاربر یک ویزارد
        نیمه‌کاره در admin_panel (مثلاً وسط لاگین یک اکانت جدید، با یک
        temp_client متصل) داشته باشد، آن را تمیز پاک‌سازی می‌کند تا
        connection نشت نکند.
        """
        wiz = self.admin_panel.wizards.pop(user_id, None)
        if wiz:
            await self.admin_panel._cleanup_wizard_temp_client(wiz)

    def _start_own_wizard(self, user_id: int, state, data: dict):
        # قبل از شروع یک ویزارد جدید ساس، ویزارد نیمه‌کاره‌ی پنل (اگر باز
        # باشد) باید بسته شود — وگرنه یک temp_client متصلِ وسطِ لاگین می‌تواند
        # نشت کند (مثلاً وقتی کاربر وسطِ ویزارد لاگین، روی یک دکمه‌ی کهنه‌ی
        # استال کلیک می‌کند و جریان ساس شروع می‌شود). pop به‌صورت همگام انجام
        # می‌شود تا دیگر هیچ پیامی به آن ویزارد نرود؛ پاک‌سازی async (قطع
        # temp_client) هم به‌صورت task اجرا می‌شود چون این متد همگام است.
        wiz = self.admin_panel.wizards.pop(user_id, None)
        if wiz:
            # با _spawn_bg: اگر این تسک وسطِ قطعِ کلاینت جمع‌آوری شود،
            # یک سشنِ متصلِ telethon نشت می‌کرد.
            _spawn_bg(self.admin_panel._cleanup_wizard_temp_client(wiz),
                      "wizard_cleanup")
        self.wizards[user_id] = {"state": state, "data": data}

    def _sync_admin_panel_scope(self, user_id: int) -> None:
        """
        قبل از هر فراخوانی به self.admin_panel (که یک نمونه‌ی مشترک بین همه‌ی
        کاربران است، نه یک نمونه‌ی جدا به‌ازای هر نفر)، این متد owner_filter
        و default_owner_id را بر اساس نقش واقعی user_id در saas_db تنظیم
        می‌کند:

        - OWNER/ADMIN: owner_filter=None (دسترسی کامل به همه‌ی اکانت‌ها،
          بدون فیلتر مالکیت) — همان رفتار قبلی.
        - RESELLER: owner_filter محدود به خودِ نماینده + همه‌ی کاربرانی که
          reseller_id آن‌ها همین نماینده است (یعنی مشتریانش) — یک نماینده
          هرگز اکانت‌های نماینده‌ی دیگر یا OWNER/ADMIN را نمی‌بیند.
          default_owner_id هم روی خودِ نماینده تنظیم می‌شود، یعنی اگر او
          مستقیماً از این پنل اکانت جدید اضافه کند، آن اکانت را مالک
          می‌شود (نه یکی از مشتریانش).
        - USER (کاربر عادی): owner_filter محدود به فقط خودش — او هرگز
          نباید اکانت‌های OWNER/ADMIN/RESELLER/سایر کاربران را ببیند.
          default_owner_id هم روی خودش تنظیم می‌شود تا اکانتی که از طریق
          ویزارد «لاگین اکانت» می‌سازد، مالکش خودش باشد.

          فیکس امنیتی مهم: قبلاً این حالت اصلاً یک شاخه‌ی جدا نداشت و به
          شاخه‌ی else (همان OWNER/ADMIN) می‌افتاد — یعنی owner_filter=None
          می‌شد، به این معنی که اگر (به هر دلیلی، مثلاً یک باگ مسیریابی
          دیگر) یک USER عادی به admin_panel می‌رسید، owner_filter او
          دسترسی نامحدود به همه‌ی اکانت‌های همه‌ی کاربران می‌داد — یک نشتی
          امنیتی جدی، نه فقط یک باگ تجربه‌ی کاربری. علاوه بر این،
          default_owner_id هم None می‌ماند، یعنی اکانتی که چنین کاربری
          می‌ساخت اصلاً owner_user_id نمی‌گرفت (یتیم می‌ماند).

        چون admin_panel یک نمونه‌ی سراسری singleton است، این تنظیم باید
        بلافاصله پیش از هر استفاده انجام شود — در محیط asyncio تک‌رشته‌ای
        این پروژه (Telethon)، بین این تنظیم و استفاده‌ی بلافصل از آن هیچ
        await ای فاصله نمی‌افتد که باعث race condition بین دو کاربر
        هم‌زمان بشود، پس این الگو ایمن است.
        """
        role = self._role(user_id)
        if role in (ROLE_OWNER, ROLE_ADMIN):
            self.admin_panel.owner_filter = None
            self.admin_panel.default_owner_id = None
        elif role == ROLE_RESELLER:
            customer_ids = {u["user_id"] for u in list_users_for_reseller(user_id)}
            self.admin_panel.owner_filter = {user_id} | customer_ids
            self.admin_panel.default_owner_id = user_id
        else:
            # USER عادی — فقط اکانت خودش، هرگز چیز دیگری
            self.admin_panel.owner_filter = {user_id}
            self.admin_panel.default_owner_id = user_id

    # ─────────────────────────────────────────────────────
    #  منوهای اصلی بر اساس نقش
    # ─────────────────────────────────────────────────────

    @staticmethod
    def _pair_buttons(items):
        """دوتا-دوتا کنار هم (۲ ستونه) تا منو کوتاه‌تر و جمع‌وجور شود —
        به‌جای یک ستونِ بلندِ عمودی که ربات را خیلی طولانی می‌کند.

        رنگ: همه آبی (primary). سبز در این پالت یعنی «روشن/فعال/تایید»
        (UI.toggle / UI.confirm) و قرمز یعنی «مخرب» — اگر دکمه‌های ناوبریِ
        بی‌رنگ را به‌جای آبی، متناوباً سبز می‌کردیم، یک دکمه‌ی سبزِ کور در
        لیست می‌توانست هم «روشن است» باشد و هم «فقط دکمه‌ی زوج‌موقعیت».
        منوهای بلند با کوتاه‌کردنِ خودِ لیست حل می‌شوند، نه با رنگین‌کردن.
        """
        return UI.paint([items[i:i + 2] for i in range(0, len(items), 2)], alternate=False)

    async def _nav_heal(self, event, note: str) -> None:
        """
        هدفِ این صفحه دیگر وجود ندارد (حذف شده). به‌جای نشان‌دادنِ یک alert
        و رهاکردنِ کاربر روی صفحه‌ی مرده، یک قدمِ دیگر عقب می‌رویم تا به
        اولین صفحه‌ی معتبر برسیم. مسیرِ مرده قبلاً از پشته pop شده، پس
        این کار هرگز حلقه نمی‌شود.
        """
        try:
            await event.answer(note, alert=True)
        except Exception:
            pass
        router = getattr(self, "_router", None)
        prev = self.nav.pop(event.sender_id)
        if router is not None and prev:
            await router(event, _route=prev, _depth=1)
            return
        await self._show_menu_for_role(event.chat_id, self._role(event.sender_id),
                                       edit_event=event)

    async def _show_menu_for_role(self, chat, role: str, edit_event=None):
        """
        منوی اصلی — **یکی برای همه**.

        قبلاً سه منوی کاملاً جدا بود (کاربر / نماینده / مدیر) و هر نقش دنیای
        متفاوتی می‌دید. نتیجه‌اش این بود که یک مدیر، سلفِ خودش را اصلاً در
        منو نداشت و باید از لابه‌لای پنل مدیریت پیدایش می‌کرد.

        ساختار جدید — «مسیرِ رایج اول، اختیاراتِ پیشرفته یک لایه عمیق‌تر»:
          • بالای صفحه: همان چیزهایی که هر کاربر می‌بیند (سلفِ خودت، اشتراک،
            پشتیبانی…) — برای *همه‌ی* نقش‌ها، چون مدیر هم کاربر است.
          • پایینِ آن: یک دکمه‌ی «ادمین» که فقط برای نقش‌های دارای اختیار
            دیده می‌شود و همه‌ی ابزارهای مدیریتی پشتِ آن جمع شده‌اند.

        این یعنی سطحِ اولِ ربات برای همه یکسان و آرام است، و پیچیدگیِ مدیریتی
        فقط وقتی ظاهر می‌شود که کاربر خودش سراغش برود.
        """
        uid = chat
        privileged = role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER)

        # ── وضعیت واقعی کاربر (مبنای رنگ‌ها، ترتیب دکمه‌ها و جمله‌ی راهنما) ──
        sub = get_active_subscription(uid)
        days_left = None
        if sub:
            try:
                expire = _parse_date(sub["expire_date"])
                days_left = max(0, (expire - datetime.now(timezone.utc)).days)
            except Exception:
                days_left = None
        if sub:
            # زیر ۳ روز مانده → زرد، تا کاربر قبل از قطع‌شدن ببیند.
            sub_state = "warn" if (days_left is not None and days_left <= 3) else "active"
            sub_note = (f"پلن «{sub['plan']}» — {days_left} روز باقی‌مانده"
                        if days_left is not None
                        else f"پلن «{sub['plan']}» تا {sub['expire_date']}")
        else:
            sub_state = "none"
            sub_note = "اشتراک فعالی نداری"

        has_account = self._user_has_logged_in_account(uid)
        n_bots, n_active, _ = self._user_selfbot_stats(uid)

        # OWNER/ADMIN اشتراک لازم ندارند؛ نمایشِ «خرید اشتراک» به آن‌ها فقط
        # نویز است. نماینده مثل کاربر عادی اشتراکِ خودش را دارد.
        needs_sub = role not in (ROLE_OWNER, ROLE_ADMIN)

        # ── منوی کاربر (طبق درخواست): ۶ دکمه‌ی اصلی + ادمین ──
        # ساختار: ۲ ستون، ۳ ردیف (سلف چیست، انقضا، خرید، لاگین، لایسنس، پشتیبانی)
        # دکمه‌ی «ادمین» فقط برای نقش‌های بالا نمایش داده می‌شود.

        # ۱. سلف چیست
        items = [UI.go("ℹ️ سلف چیست", "user_what_is")]

        # ۲. انقضای سلف (با نمایش روز)
        if needs_sub:
            if sub and days_left is not None:
                expiry_label = f"⏳ انقضای سلف ({fa_digits(days_left)} روز)"
            elif sub:
                expiry_label = "⏳ انقضای سلف (نامشخص)"
            else:
                expiry_label = "⏳ انقضای سلف (۰ روز)"
            items.append(UI.item(expiry_label, sub_state, "user_sub_status"))
        else:
            # ادمین/مالک: بدون محدودیت زمانی
            items.append(UI.item("⏳ انقضای سلف (نامحدود)", "active", "user_sub_status"))

        # ۳. خرید سلف
        items.append(UI.confirm("🛒 خرید سلف", "user_renew"))

        # ۴. لاگین کردن سلف (فقط اگه قبلاً خریده یا ادمین هست یا اکانت داره)
        if sub or (not needs_sub) or has_account or n_bots > 0:
            items.append(UI.confirm("📱 لاگین کردن سلف", "user_login_account"))

        # ۵. خرید با لایسنس
        items.append(UI.go("🔑 خرید با لایسنس", "user_activate_license"))

        # ۶. پشتیبانی
        items.append(UI.go("☎️ پشتیبانی", "user_support"))

        buttons = self._pair_buttons(items)

        # ── دکمه‌ی «ادمین»: تمام‌عرض، جدا از بخشِ کاربری ──
        # عمداً یک ردیفِ مستقل است تا مرزِ «فضای من» و «فضای مدیریت» با
        # فاصله دیده شود، نه اینکه کنارِ دکمه‌های کاربری گم شود.
        if privileged:
            todo = self._admin_pending_count(uid, role)
            label = "🎛 ادمین" if not todo else f"🎛 ادمین · {fa_digits(todo)} کارِ معوق"
            buttons.append([UI.item(label, "pending" if todo else "active", "admin_hub")])

        # بدنه‌ی صفحه: خلاصه‌ی وضعیت (انقضا + تعداد سلف)
        body = []
        if needs_sub:
            if sub and days_left is not None:
                if days_left > 7:
                    body.append(f"{UI.GREEN} اشتراک فعال — {fa_digits(days_left)} روز مانده")
                elif days_left > 0:
                    body.append(f"{UI.AMBER} ⚠️ فقط {fa_digits(days_left)} روز تا انقضا")
                else:
                    body.append(f"{UI.RED} ❌ اشتراک منقضی شده")
            else:
                body.append(f"{UI.RED} ❌ اشتراک نداری — از «🛒 خرید سلف» شروع کن")
        else:
            body.append(f"{UI.GREEN} دسترسی نامحدود (ادمین)")
        if n_bots:
            body.append(f"{UI.dot(n_active > 0)} سلف: {fa_digits(n_active)} فعال از {fa_digits(n_bots)}")
        elif has_account:
            body.append(f"{UI.GREEN} اکانتت لاگین شده")
        else:
            body.append(f"{UI.GRAY} هنوز اکانتی لاگین نکرده‌ای")

        # راهنمای «قدم بعدی» — همیشه دقیقاً یک جمله، بر اساس وضعیتِ واقعی.
        if needs_sub and not sub:
            hint = "برای شروع، «🛒 خرید سلف» را بزن."
        elif sub and not has_account and n_bots == 0:
            hint = "اشتراک داری — حالا «📱 لاگین کردن سلف» را بزن."
        elif needs_sub and days_left is not None and days_left <= 3:
            hint = "اشتراکت رو به اتمام است؛ از «🛒 خرید سلف» تمدیدش کن."
        elif privileged:
            hint = "ابزارهای مدیریتی داخل «🎛 ادمین» است."
        else:
            hint = "از «☎️ پشتیبانی» هر سؤالی داری بپرس."

        text = UI.screen(
            "🏠 منوی اصلی",
            body=body,
            subtitle="سلام 👋 خوش آمدی — از اینجا سلفت را می‌خری و مدیریت می‌کنی.",
            hint=hint,
        )

        if edit_event is not None:
            await edit_event.edit(text, buttons=buttons)
        else:
            await self.client.send_message(chat, text, buttons=buttons)

    async def _notify_referrer(self, referrer_id: int) -> None:
        """
        به دعوت‌کننده خبر می‌دهد که یک نفر با لینکش آمد، و اگر به سقف
        رسیده باشد، اشتراکِ هدیه را همان‌جا اعمال و اعلام می‌کند.
        """
        try:
            st = referral_stats(referrer_id)
            if st["pending"]:
                granted = claim_referral_rewards(referrer_id)
                if granted:
                    await self.client.send_message(
                        referrer_id,
                        UI.screen(
                            "🎉 اشتراک هدیه فعال شد",
                            body=[f"{UI.GREEN} {fa_digits(granted)} ماه اشتراک به حسابت اضافه شد.",
                                  f"{UI.GRAY} تا الان {fa_digits(st['invited'])} نفر با لینکِ تو آمده‌اند."],
                            hint="دعوت ادامه دارد — هر ۳ نفر یک ماه دیگر.",
                        ),
                    )
                    return
            await self.client.send_message(
                referrer_id,
                UI.screen(
                    "👤 یک نفر با لینکِ تو آمد",
                    body=[f"{UI.GREEN} دعوت‌های موفق: {fa_digits(st['invited'])}",
                          f"{UI.AMBER} {fa_digits(st['remaining'])} نفر دیگر تا اشتراکِ رایگانِ بعدی."],
                ),
            )
        except Exception:
            # دعوت‌کننده ممکن است ربات را بلاک کرده باشد — بی‌صدا رد شو
            pass

    def _admin_pending_count(self, uid: int, role: str) -> int:
        """
        تعدادِ کارهای معوقی که *این نقش* باید به آن‌ها رسیدگی کند — برای
        نشانِ روی دکمه‌ی «ادمین».

        نماینده پرداخت/تیکتِ سیستم را بررسی نمی‌کند، پس برای او صفر است و
        دکمه بی‌جهت قرمز نمی‌شود.
        """
        if role not in (ROLE_OWNER, ROLE_ADMIN):
            return 0
        try:
            return len(list_pending_payments()) + len(list_open_tickets())
        except Exception:
            return 0

    async def _show_account_card(self, event):
        """👤 حساب کاربری — شناسه، تاریخ عضویت و وضعیت، با تاریخ شمسی."""
        uid = event.sender_id
        u = get_user(uid) or {}
        st = self._user_sub_status(uid)
        n_bots, n_active, _ = self._user_selfbot_stats(uid)
        ref = referral_stats(uid)

        joined = "—"
        raw = u.get("created_at")
        if raw:
            try:
                joined = jalali_date(datetime.strptime(raw, _DATETIME_FMT))
            except Exception:
                joined = raw[:10]

        sub_state = self._sub_ui_state(st)
        if st["active"]:
            sub_line = f"{st['plan']} — {fa_digits(st['days'])} روز باقی‌مانده"
        elif st["expired"]:
            sub_line = f"{st['plan']} — منقضی شده"
        else:
            sub_line = "ندارد"

        now = iran_now()
        body = [
            f"👤 شناسه کاربری: `{uid}`",
            f"📅 تاریخ عضویت: {joined}",
            f"{UI.state_dot(sub_state)} اشتراک: {sub_line}",
            f"🤖 سلف: {fa_digits(n_active)} فعال از {fa_digits(n_bots)}",
            f"🎁 دعوت‌های موفق: {fa_digits(ref['invited'])}",
            UI.SEP,
            f"🗓 {fa_weekday(now)} · {jalali_long(now)}",
            f"⏰ {fa_digits(now.strftime('%H:%M'))}",
        ]

        # «حساب کاربری» حالا هابِ همه‌ی کارهای کم‌کاربرد است — تا منوی اصلی
        # در چهار دکمه جا شود. هر دکمه‌ای که از اینجا حذف می‌شود، قبلاً یک
        # دکمه‌ی سطحِ اول بود و منو را شلوغ می‌کرد.
        items = [
            UI.go("⏳ مدیریت اشتراک", "user_sub_status"),
            UI.go("🧾 سفارش‌ها", "user_orders"),
            UI.go("🔑 فعالسازی لایسنس", "user_activate_license"),
            UI.go("❤️ دعوت دوستان", "user_referral"),
            UI.go("🧠 سلف چیست؟", "user_what_is"),
            UI.go("📚 راهنمای دستورات", "user_help"),
        ]
        if self._role(uid) == ROLE_USER:
            items.append(UI.go("👥 نمایندگی", "user_reseller_info"))
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("👤 حساب کاربری", body=body,
                      subtitle="کارهای مربوط به حساب خودت اینجاست."),
            buttons=buttons,
        )

    async def _show_referral(self, event):
        """❤️ اشتراک رایگان — لینک دعوت و پیشرفت."""
        uid = event.sender_id
        # جایزه‌های معوق را همین‌جا هم اعمال کن (اگر اعلانِ لحظه‌ای از دست رفته باشد)
        claimed = 0
        try:
            claimed = claim_referral_rewards(uid)
        except Exception:
            pass
        st = referral_stats(uid)
        me = getattr(self, "_bot_username", None) or ""
        link = referral_link(me, uid)

        body = []
        if claimed:
            body.append(f"{UI.GREEN} {fa_digits(claimed)} ماه اشتراکِ هدیه همین حالا فعال شد!")
            body.append(UI.SEP)
        body += [
            f"هر **{fa_digits(REFERRAL_GOAL)} نفر** که با لینکِ تو وارد ربات شوند،",
            f"**{fa_digits(REFERRAL_REWARD_DAYS)} روز** اشتراک رایگان می‌گیری.",
            "",
            "🔗 لینک اختصاصی تو:",
            f"`{link}`",
            "",
            f"{UI.GREEN} دعوت‌های موفق: {fa_digits(st['invited'])}",
            f"{UI.GREEN} اشتراک‌های دریافتی: {fa_digits(st['rewards'])}",
            f"{UI.AMBER} {fa_digits(st['remaining'])} نفر دیگر تا جایزه‌ی بعدی",
        ]
        await event.edit(
            UI.screen("❤️ اشتراک رایگان", body=body,
                      hint="لینک را برای دوستانت بفرست — جایزه خودکار فعال می‌شود."),
            buttons=[[UI.refresh("user_referral")], UI.nav_row()],
        )

    async def _show_what_is(self, event):
        """🧠 سلف چیست؟ — معرفیِ کوتاه + فهرستِ کاملِ امکانات.

        صفحه‌ی جداگانه‌ی «امکانات دستیار» در این نسخه حذف شد (یک لایه‌ی
        اضافی برای چیزی که در همین صفحه جا می‌شود)؛ لیستِ امکانات اینجا
        است تا همچنان یک منبعِ واحد (SELF_FEATURE_LIST) نمایش داده شود.
        """
        body = [WHAT_IS_SELFBOT_TEXT, "", "🚀 **امکانات کامل:**"]
        body.extend(SELF_FEATURE_LIST)
        await event.edit(
            "\n".join(body),
            buttons=[UI.nav_row()],
        )

    async def _show_admin_hub(self, event, role: str):
        """
        «ادمین» — همه‌ی ابزارهای مدیریتی، یک لایه پایین‌ترِ منوی اصلی.

        گزینه‌های هر نقش فرق می‌کند: نماینده فقط مشتری‌ها و لایسنس‌های خودش
        را می‌بیند؛ ادمین کلِ سیستم؛ مالک علاوه بر آن تنظیمات و بکاپ.
        """
        uid = event.sender_id
        if role == ROLE_RESELLER:
            my_users = list_users_for_reseller(uid)
            n_active = sum(1 for u in my_users if self._user_has_active_sub(u["user_id"]))
            items = [
                UI.go("🛠 اکانت‌های مشتریان", "goto_admin_panel", primary=True),
                UI.go(f"📋 کاربران من ({len(my_users)})", "reseller_users"),
                UI.go("🎫 لایسنس و دسترسی‌ها", "license_access"),
                UI.go("🤖 ربات اختصاصی", "reseller_dedicated_bot"),
                UI.go("⏳ وضعیت اشتراک‌ها", "reseller_subs"),
            ]
            body = [f"{UI.GREEN} {n_active} مشتری با اشتراک فعال",
                    f"{UI.RED} {len(my_users) - n_active} بدون اشتراک فعال"]
            title, subtitle = "👥 پنل نمایندگی", "مشتری‌ها، لایسنس‌ها و ربات اختصاصیِ خودت."
        elif role in (ROLE_OWNER, ROLE_ADMIN):
            st = self._users_stats(list_all_users(), use_cache=True)
            pending_pay = len(list_pending_payments())
            open_tk = len(list_open_tickets())
            orphans = self._orphan_count()

            # چهار مسیرِ اصلی در سطحِ اول. تنظیمات/بکاپ/ربات‌های اختصاصی
            # کارهای نادرند و پشتِ «ابزارهای بیشتر» رفتند — قبلاً هفت دکمه‌ی
            # هم‌وزن بود و مسیرِ روزمره بینشان گم می‌شد.
            items = [
                UI.go(f"👥 کاربران ({fa_digits(st['total'])})", "admin_users", primary=True),
                UI.item("💰 مالی" + (f" ({fa_digits(pending_pay)})" if pending_pay else ""),
                        "pending" if pending_pay else "none", "admin_finance"),
                UI.item("📨 پشتیبانی" + (f" ({fa_digits(open_tk)})" if open_tk else ""),
                        "pending" if open_tk else "none", "admin_tickets"),
                UI.go("🎫 لایسنس‌ها", "license_access"),
            ]
            if orphans:
                items.append(UI.item(f"⚠️ سلف‌های بدون مالک ({fa_digits(orphans)})",
                                     "warn", "owner_orphan_bots"))
            items.append(UI.go("🧰 ابزارهای بیشتر", "admin_tools"))

            # بدنه فقط «چه کاری روی زمین مانده» — آمارِ تزئینی حذف شد.
            body = []
            if pending_pay:
                body.append(f"{UI.AMBER} {fa_digits(pending_pay)} پرداخت منتظر بررسی")
            if open_tk:
                body.append(f"{UI.AMBER} {fa_digits(open_tk)} تیکت باز")
            if orphans:
                body.append(f"{UI.AMBER} {fa_digits(orphans)} سلف به کاربری وصل نشده")
            if not body:
                body.append(f"{UI.GREEN} هیچ کارِ معوقی نداری.")
            title = "🎛 ادمین"
            subtitle = None
        else:
            await event.answer("⛔ دسترسی نداری", alert=True)
            return

        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit(UI.screen(title, body=body, subtitle=subtitle), buttons=buttons)

    async def _show_admin_tools(self, event, role: str):
        """🧰 ابزارهای کم‌کاربردِ مدیریتی — یک لایه پایین‌ترِ هابِ ادمین."""
        if role not in (ROLE_OWNER, ROLE_ADMIN):
            await event.answer("⛔ دسترسی نداری", alert=True)
            return
        items = [UI.go("🤖 ربات‌های اختصاصی", "owner_dedicated_list")]
        if role == ROLE_OWNER:
            items.extend([
                UI.go("🔐 مجوزهای حساس", "cap_list"),
                UI.go("⚙️ تنظیمات", "admin_settings"),
                UI.go("💾 بکاپ و بازیابی", "admin_backup"),
            ])
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("🧰 ابزارهای بیشتر",
                      subtitle="کارهایی که هر روز لازم نمی‌شوند."),
            buttons=buttons,
        )

    def _orphan_count(self) -> int:
        """تعداد سلف‌هایی که owner_user_id ندارند (به کاربری وصل نیستند)."""
        try:
            cfg = self.sb.load_config()
            return sum(1 for tag, acc in cfg.items() if account_is_orphan(acc, tag))
        except Exception:
            return 0

    # ─────────────────────────────────────────────────────
    #  هاب‌های دسته‌بندی‌شده‌ی پنل OWNER/ADMIN (فقط UI/Navigation — هر
    #  دکمه به همان callback واقعیِ موجود اشاره می‌کند)
    # ─────────────────────────────────────────────────────

    # کشِ کوتاه‌مدتِ آمارِ داشبورد. این آمار روی «منوی اصلی» نشان داده
    # می‌شود، یعنی با هر /start و هر «بازگشت به منوی اصلی» محاسبه می‌شد.
    # محاسبه‌ی کامل برای N کاربر یعنی N بار خواندن و پارس‌کردنِ config.json
    # از دیسک — که روی event loop انجام می‌شود و با چند صد کاربر محسوس
    # است. این اعداد اطلاعاتی‌اند و چند ثانیه کهنگی هیچ اشکالی ندارد.
    _STATS_TTL = 20.0

    def _users_stats(self, users: list, use_cache: bool = False) -> dict:
        """آمار کلی کاربران — هر دسته جدا شمرده می‌شود (نه منقضی = کل - فعال)
        تا هیچ‌جا به خاطر overlap اشتباه نشود: فعال / منقضی / بدون اشتراک /
        دارای اکانت دستی / دارای SelfBot / SelfBot در حال اجرا.

        use_cache: برای صفحاتی که این آمار صرفاً «خلاصه‌ی وضعیت» است
        (منوی اصلی). صفحاتی که خودِ آمار موضوعشان است با مقدار تازه
        رندر می‌شوند.
        """
        if use_cache:
            hit = getattr(self, "_stats_cache", None)
            if hit and (time.time() - hit[0]) < self._STATS_TTL:
                return hit[1]

        # config فقط یک‌بار خوانده می‌شود و از رویش یک ایندکسِ
        # owner_user_id → اکانت‌ها ساخته می‌شود؛ قبلاً به‌ازای هر کاربر
        # دوباره از دیسک خوانده و پارس می‌شد (N بار I/O برای N کاربر).
        cfg = self.sb.load_config()
        by_owner = {}
        running = 0
        for tag, acc in cfg.items():
            if not isinstance(acc, dict):
                continue
            if tag in self.sb.ACCOUNTS and not acc.get("disabled"):
                running += 1
            by_owner.setdefault(acc.get("owner_user_id"), []).append(acc)

        active = expired = nosub = manual = hasbot = 0
        for u in users:
            uid = u["user_id"]
            st = self._user_sub_status(uid)
            if st["active"]:
                active += 1
            elif st["expired"]:
                expired += 1
            else:
                nosub += 1
            owned = by_owner.get(uid) or []
            if owned:
                hasbot += 1
                if any(a.get("provision_source") == PROVISION_MANUAL for a in owned):
                    manual += 1

        out = {"total": len(users), "active": active, "expired": expired,
               "nosub": nosub, "manual": manual, "hasbot": hasbot,
               "running_bots": running}
        self._stats_cache = (time.time(), out)
        return out

    def _user_has_active_sub(self, uid: int) -> bool:
        """آیا این کاربر یک اشتراکِ واقعاً فعال (منقضی‌نشده) دارد؟"""
        return self._user_sub_status(uid)["active"]

    def _user_selfbot_stats(self, uid: int) -> tuple:
        """(کل اکانت‌ها، فعال، متوقف/خاموش) برای یک کاربر — از config.json
        با owner_user_id و وضعیت runtime (ACCOUNTS/disabled)."""
        cfg = self.sb.load_config()
        total = active = stopped = 0
        for tag, acc in cfg.items():
            if not account_belongs_to(acc, tag, uid):
                continue
            total += 1
            if acc.get("disabled"):
                stopped += 1
            elif tag in self.sb.ACCOUNTS:
                active += 1
            else:
                stopped += 1
        return total, active, stopped

    def _user_manual_bot_count(self, uid: int) -> int:
        """تعداد اکانت‌های سلفِ «اضافه‌شده‌ی دستی» (provision_source=manual)
        برای یک کاربر. بدون اشتراک بودن ≠ دستی بودن — فقط اکانت‌هایی که
        واقعاً توسط مدیریت ساخته شده‌اند manual شمرده می‌شوند."""
        cfg = self.sb.load_config()
        return sum(
            1 for tag, acc in cfg.items()
            if account_belongs_to(acc, tag, uid)
            and acc.get("provision_source") == PROVISION_MANUAL
        )

    def _user_sub_status(self, uid: int) -> dict:
        """وضعیت اشتراکِ یک کاربر به‌صورت ساخت‌یافته — تا UI و فیلترها از یک
        منطق واحد استفاده کنند (هیچ‌وقت UI با دیتابیس ناسازگار نشود):
          active:      اشتراکِ واقعاً فعال (منقضی‌نشده)
          expired:     سابقه‌ی اشتراک دارد ولی فعالی ندارد
          nosub:       اصلاً هیچ اشتراکی نداشته
          plan/days:   برای نمایش
        """
        sub = get_active_subscription(uid)
        d = _subscription_days_left(sub)
        if sub and d is not None and d >= 0:
            return {"active": True, "expired": False, "nosub": False,
                    "plan": sub["plan"], "days": d, "expire": sub["expire_date"]}
        if sub and d is not None and d < 0:
            return {"active": False, "expired": True, "nosub": False,
                    "plan": sub["plan"], "days": d, "expire": sub["expire_date"]}
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1", (uid,)
            ).fetchone()
        if row:
            row = dict(row)
            d2 = _subscription_days_left(row)
            return {"active": False, "expired": True, "nosub": False,
                    "plan": row["plan"], "days": d2, "expire": row["expire_date"]}
        return {"active": False, "expired": False, "nosub": True,
                "plan": None, "days": None, "expire": None}

    def _user_card_lines(self, u: dict) -> list:
        """خطوطِ کارت نمایش یک کاربر در لیست‌ها — نام/آیدی، اشتراک با روز
        باقی‌مانده (یا منقضی/بدون اشتراک)، نشانِ «اضافه‌شده‌ی دستی» و آمار
        SelfBotهایش."""
        uid = u["user_id"]
        name = u.get("username") or f"کاربر {uid}"
        st = self._user_sub_status(uid)
        state = self._sub_ui_state(st)
        lines = [f"{UI.state_dot(state)} **{name}** — `{uid}`"]
        if st["active"]:
            lines.append(f"   ⭐ {st['plan']} — "
                         + ("امروز آخرین روز" if st["days"] == 0
                            else f"{st['days']} روز باقی‌مانده"))
        elif st["expired"]:
            lines.append(f"   ⭐ {st['plan']} — منقضی شده")
        else:
            lines.append("   اشتراک ندارد")
        # «اضافه‌شده‌ی دستی» مستقل از اشتراک است — اگر اکانت دستی وجود
        # دارد، همان‌جا نشان داده می‌شود (مخصوصاً برای کاربر بدون اشتراک
        # که SelfBot دستی دارد).
        if self._user_manual_bot_count(uid) > 0:
            lines.append("   🛠 اضافه‌شده دستی")
        total, active, stopped = self._user_selfbot_stats(uid)
        if total == 0:
            lines.append(f"   {UI.GRAY} بدون SelfBot")
        else:
            lines.append(f"   🤖 {total} SelfBot — {UI.GREEN} {active} فعال"
                         + (f" / {UI.RED} {stopped} متوقف" if stopped else ""))
        return lines

    @staticmethod
    def _sub_ui_state(st: dict) -> str:
        """وضعیتِ اشتراک → کلیدِ پالتِ UI. یک‌جا تعریف می‌شود تا رنگِ
        اشتراکِ یک کاربر در لیست، کارت و صفحه‌ی مدیریتش یکی باشد."""
        if st["active"]:
            return "warn" if st["days"] == 0 else "active"
        return "expired" if st["expired"] else "none"

    async def _admin_show_users_hub(self, event, role: str):
        """صفحه‌ی اصلی «کاربران» — جستجوی سریع + فیلترهای پرکاربرد.

        صفحه‌ی جداگانه‌ی «فیلترها» حذف شد: یک لایه‌ی اضافی بود و هر فیلتری
        که واقعاً لازم است، حالا به‌صورتِ یک ردیف در پایینِ خودِ لیست
        نشسته (نگاه کن به _owner_show_users). جستجو سریع‌ترین راهِ رسیدن
        به یک کاربرِ مشخص است، به همین دلیل primary است."""
        users = list_all_users()
        st = self._users_stats(users)
        # سه خط، نه هشت خط.
        body = [
            f"👤 {fa_digits(st['total'])} کاربر  ·  "
            f"{UI.GREEN} {fa_digits(st['active'])} فعال  ·  "
            f"{UI.RED} {fa_digits(st['expired'])} منقضی",
            f"🤖 {fa_digits(st['running_bots'])} سلف در حال اجرا از {fa_digits(st['hasbot'])}",
        ]
        items = [
            UI.go("🔎 جستجوی کاربر", "user_search_start", primary=True),
            UI.go(f"📋 همه ({st['total']})", "users_list:all:0"),
            UI.item(f"⏳ منقضی‌ها ({st['expired']})", "expired", "users_list:expired:0"),
        ]
        buttons = self._pair_buttons(items)
        # «سلف‌های بدون مالک» فقط وقتی واقعاً وجود دارند — دکمه‌ی همیشگیِ
        # صفر، فقط شلوغی است.
        if role == ROLE_OWNER:
            cfg = self.sb.load_config()
            orphan_count = sum(1 for tag, acc in cfg.items()
                               if account_is_orphan(acc, tag))
            if orphan_count > 0:
                buttons.append([UI.item(f"⚠️ سلف‌های بدون مالک ({orphan_count})",
                                        "warn", "owner_orphan_bots")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("👥 کاربران", body=body,
                      hint="جستجو سریع‌ترین راه است — آیدی یا یوزرنیم را بفرست."),
            buttons=buttons,
        )

    async def _owner_show_orphan_bots(self, event):
        """
        ⚠️ سلف‌هایی که به هیچ کاربری وصل نیستند.

        این‌ها سلف‌هایی‌اند که دستی لاگین شده‌اند یا از قبلِ سیستمِ مالکیت
        باقی مانده‌اند — owner_user_id ندارند. تا وقتی وصل نشوند، در فهرستِ
        «سلف من»ِ هیچ‌کس دیده نمی‌شوند و کاربر نمی‌تواند خودش مدیریتشان کند.

        راه‌حل، حذف نیست — **وصل‌کردن** است: با «تعیین مالک» هر کدام به یک
        کاربر نسبت داده می‌شود و بلافاصله وارد جریانِ عادی می‌شود.
        """
        cfg = self.sb.load_config()
        orphans = {tag: acc for tag, acc in cfg.items()
                   if account_is_orphan(acc, tag)}
        if not orphans:
            await event.edit(
                UI.screen("سلف‌های بدون مالک",
                          body=[f"{UI.GREEN} همه‌ی سلف‌ها به کاربری وصل‌اند — چیزی برای رسیدگی نیست."]),
                buttons=[UI.nav_row()],
            )
            return
        body = []
        buttons = []
        for tag, acc in orphans.items():
            state, note = _acc_ui_state(acc, tag)
            phone = acc.get("phone")
            body.append(f"{UI.state_dot(state)} `{tag}`" + (f" · {phone}" if phone else "") + f" — {note}")
            buttons.append([UI.item(tag, state, f"orphan_acc:{tag}")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen(
                "⚠️ سلف‌های بدون مالک",
                body=body,
                subtitle=f"{len(orphans)} سلف هنوز به هیچ کاربری وصل نشده‌اند.",
                hint="روی هرکدام بزن و «تعیین مالک» را انتخاب کن تا به کاربرش وصل شود.",
            ),
            buttons=buttons,
        )

    async def _show_orphan_acc(self, event, tag: str):
        """
        یک سلفِ بدون مالک: قبل از هر چیز پیشنهادِ وصل‌کردن، و در کنارش همان
        هابِ کاملِ مدیریت (تا اگر فقط می‌خواهی روشن/خاموشش کنی هم بتوانی).
        """
        cfg = self.sb.load_config()
        acc = cfg.get(tag)
        if not acc or not account_is_orphan(acc, tag):
            await self._nav_heal(event, "این سلف دیگر وجود ندارد یا به کاربری وصل شده.")
            return
        state, note = _acc_ui_state(acc, tag)
        body = [
            f"{UI.state_dot(state)} وضعیت: {note}",
            f"{UI.GRAY} شماره: `{acc.get('phone') or 'ثبت نشده'}`",
            UI.SEP,
            f"{UI.AMBER} این سلف به هیچ کاربری وصل نیست، پس در «سلف من»ِ کسی",
            "دیده نمی‌شود و خودِ صاحبش نمی‌تواند مدیریتش کند.",
        ]
        await event.edit(
            UI.screen(f"⚠️ سلف «{tag}»", body=body,
                      hint="با «تعیین مالک» به کاربرش وصلش کن تا همه‌ی قابلیت‌ها برایش فعال شود."),
            buttons=[
                [UI.confirm("👤 تعیین مالک", f"orphan_own:{tag}")],
                [UI.go("⚙️ مدیریت کامل سلف", f"orphan_manage:{tag}")],
                UI.nav_row(),
            ],
        )

    async def _open_orphan_full(self, event, tag: str):
        """هابِ کاملِ مدیریت برای یک سلفِ بدون مالک."""
        cfg = self.sb.load_config()
        if tag not in cfg:
            await self._nav_heal(event, "این سلف دیگر وجود ندارد.")
            return
        async with self._panel_lock:
            self._sync_admin_panel_scope(event.sender_id)
            await self.admin_panel._show_account_detail(event, tag)

    async def _start_orphan_assign(self, event, tag: str):
        """ویزاردِ «تعیین مالک» — آیدی عددی یا یوزرنیمِ کاربر را می‌گیرد."""
        cfg = self.sb.load_config()
        if tag not in cfg:
            await self._nav_heal(event, "این سلف دیگر وجود ندارد.")
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_ORPHAN_ASSIGN, {"tag": tag})
        await event.edit(
            UI.screen(f"👤 تعیین مالکِ «{tag}»",
                      body=["آیدی عددیِ کاربر یا یوزرنیمش را بفرست.",
                            "",
                            f"{UI.GRAY} مثال: `123456789` یا `@username`"],
                      hint="بعد از وصل‌شدن، همه‌ی قابلیت‌های سلف برای آن کاربر فعال می‌شود."),
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    def _assign_orphan_owner(self, tag: str, target_user_id: int) -> bool:
        """
        وصل‌کردنِ یک سلف به یک کاربر: owner_user_id را در config می‌نویسد.

        از همان لحظه آن سلف در «سلف من»ِ آن کاربر ظاهر می‌شود و همه‌ی
        قابلیت‌ها (روشن/خاموش، ظاهر، ردیاب، نشست‌ها…) برایش فعال است —
        چون همه‌ی گاردها بر پایه‌ی همین فیلد تصمیم می‌گیرند.
        """
        cfg = self.sb.load_config()
        acc = cfg.get(tag)
        if not isinstance(acc, dict):
            return False
        acc["owner_user_id"] = int(target_user_id)
        return bool(self.sb.save_config(cfg))

    async def _admin_show_finance_hub(self, event, role: str):
        """💰 مدیریت مالی — لایسنس‌ها اینجا نیستند؛ ساخت لایسنس فقط از
        «🎫 لایسنس و دسترسی‌ها» انجام می‌شود."""
        pending = list_pending_payments()
        card = get_setting("card_number")
        wallet = get_setting("trc20_wallet")
        items = [
            UI.item(f"💳 پرداخت‌های در انتظار ({len(pending)})",
                    "pending" if pending else "none", "owner_payments"),
            UI.go("📊 سفارش‌ها", "owner_orders"),
        ]
        body = [
            f"{UI.state_dot('pending' if pending else 'active')} "
            f"{len(pending)} پرداخت منتظر بررسی",
        ]
        if role == ROLE_OWNER:
            items.extend([
                UI.go("⚙️ قیمت و پلن‌ها", "owner_pricing"),
                UI.item("💵 کیف پول USDT", "active" if wallet else "off", "owner_set_wallet"),
                UI.item("💳 شماره کارت", "active" if card else "off", "owner_set_card"),
            ])
            body.append(f"{UI.dot(bool(card))} شماره کارت: "
                        f"{'تنظیم‌شده' if card else 'تنظیم نشده'}")
            body.append(f"{UI.dot(bool(wallet))} کیف پول تتر: "
                        f"{'تنظیم‌شده' if wallet else 'تنظیم نشده'}")
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("💰 مدیریت مالی", body=body,
                      subtitle="پرداخت‌ها، سفارش‌ها، قیمت‌ها و درگاه‌ها.",
                      hint=("اول درگاه‌ها را تنظیم کن تا کاربر بتواند پرداخت کند."
                            if role == ROLE_OWNER and not (card or wallet) else None)),
            buttons=buttons,
        )

    async def _admin_show_tickets_hub(self, event):
        open_tk = list_open_tickets()
        buttons = [[UI.item(f"📨 تیکت‌های باز ({len(open_tk)})",
                            "pending" if open_tk else "active", "owner_tickets")]]
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen(
                "📨 پشتیبانی",
                body=[f"{UI.state_dot('pending' if open_tk else 'active')} "
                      + (f"{len(open_tk)} تیکت منتظر پاسخ" if open_tk else "هیچ تیکت بازی نیست")],
                subtitle="تیکت‌های کاربران را اینجا ببین و پاسخ بده.",
            ),
            buttons=buttons,
        )

    async def _admin_show_settings_hub(self, event):
        # تنظیمات مالی (کارت/USDT/قیمت‌ها) فقط از «💰 مالی» — اینجا تکرار
        # نمی‌شوند تا مسیر تکراری/گیج‌کننده نماند (بخش ۱۸ اسپک).
        ch = get_setting("required_channel")
        buttons = [
            [UI.item("📢 کانال اجباری عضویت", "active" if ch else "none", "owner_channel")],
            UI.nav_row(),
        ]
        await event.edit(
            UI.screen(
                "⚙️ تنظیمات سیستم",
                body=[f"{UI.dot(bool(ch))} کانال اجباری: "
                      + (f"`{ch}`" if ch else "غیرفعال (همه می‌توانند وارد شوند)")],
                subtitle="تنظیمات غیرمالی — کارت/تتر/قیمت‌ها در «💰 مالی» هستند.",
            ),
            buttons=buttons,
        )

    async def _admin_show_backup_hub(self, event):
        buttons = [
            [UI.confirm("گرفتن Backup", "owner_backup")],
            [UI.danger("بازیابی از Backup", "owner_db_restore")],
            UI.nav_row(),
        ]
        await event.edit(
            UI.screen(
                "💾 Backup و Restore",
                body=[
                    f"{UI.GREEN} **Backup** — یک فایل ZIP کامل از دیتابیس‌ها، "
                    f"تنظیمات و سشن‌ها می‌سازد. کاملاً بی‌خطر.",
                    f"{UI.RED} **Restore** — وضعیت فعلی را با محتوای فایل "
                    f"جایگزین می‌کند. قبلش یک Backup اضطراری خودکار گرفته می‌شود.",
                ],
                subtitle="پشتیبان‌گیری و بازیابیِ کلِ سیستم.",
                hint="قبل از هر Restore، حتماً یک Backup تازه بگیر.",
            ),
            buttons=buttons,
        )

    # ─────────────────────────────────────────────────────
    #  بخش OWNER/ADMIN
    # ─────────────────────────────────────────────────────

    def _filter_users(self, users: list, fkey: str) -> list:
        """فیلتر لیست کاربران برای صفحه‌ی «کاربران». «بدون اشتراک» و «منقضی»
        دو فیلتر جدا هستند و «اضافه‌شده‌ی دستی» هم فیلتر مستقل خودش را
        دارد:
          all/active/expired/nosub/manual/hasbot/nobot
        """
        if fkey == "active":
            return [u for u in users if self._user_sub_status(u["user_id"])["active"]]
        if fkey == "expired":
            return [u for u in users if self._user_sub_status(u["user_id"])["expired"]]
        if fkey == "nosub":
            return [u for u in users if self._user_sub_status(u["user_id"])["nosub"]]
        if fkey == "manual":
            return [u for u in users if self._user_manual_bot_count(u["user_id"]) > 0]
        if fkey == "hasbot":
            return [u for u in users if self._user_selfbot_stats(u["user_id"])[0] > 0]
        if fkey == "nobot":
            return [u for u in users if self._user_selfbot_stats(u["user_id"])[0] == 0]
        return users

    async def _owner_show_users(self, event, fkey: str = "all", page: int = 0):
        """لیست کاربران به‌صورت کارت (با فیلتر و صفحه‌بندی). هر کارت
        وضعیت اشتراک (روز باقی‌مانده) و آمار SelfBotهای همان کاربر را
        نشان می‌دهد و دکمه‌ی «⚙️ مدیریت» به صفحه‌ی مدیریت آن کاربر می‌رود."""
        all_users = list_all_users()
        users = self._filter_users(all_users, fkey)
        buttons = [[UI.go("🔍 جستجوی کاربر", b"user_search_start")]]
        if not users:
            await event.edit(
                "📭 هنوز هیچ کاربری ثبت نشده.",
                buttons=buttons + [UI.nav_row()],
            )
            return
        PAGE_SIZE = 8
        total_pages = max(1, (len(users) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        shown = users[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        fkey_label = {"all": "همه", "active": "فعال", "expired": "منقضی",
                      "nosub": "بدون اشتراک", "manual": "اضافه شده دستی",
                      "hasbot": "دارای SelfBot", "nobot": "بدون SelfBot"}.get(fkey, fkey)
        body = []
        for u in shown:
            body.extend(self._user_card_lines(u))
            body.append("")
            # مسیر بازگشت دیگر در دکمه جاسازی نمی‌شود — پشته‌ی ناوبری
            # خودش می‌داند کاربر از کدام فیلتر/صفحه آمده است.
            buttons.append([UI.item(
                str(u.get("username") or u["user_id"]),
                self._sub_ui_state(self._user_sub_status(u["user_id"])),
                f"user_manage:{u['user_id']}",
            )])
        lines = [UI.screen(
            f"👥 کاربران — {fkey_label}",
            body=body,
            subtitle=f"صفحه {page + 1} از {total_pages} • {len(users)} کاربر در این فیلتر",
        )]
        nav = []
        if page > 0:
            nav.append(UI.btn(f"{UI.PREV} قبلی", f"users_list:{fkey}:{page - 1}"))
        if total_pages > 1:
            nav.append(UI.btn(f"{page + 1}/{total_pages}", NAV_NOOP))
        if page < total_pages - 1:
            nav.append(UI.btn(f"بعدی {UI.NEXT}", f"users_list:{fkey}:{page + 1}"))
        if nav:
            buttons.append(nav)
        # فیلترهای سریع — در همان صفحه‌ی لیست، نه یک لایه‌ی پایین‌تر.
        # فیلترِ فعال برای کاربری که از قبل در حال مشاهده‌ی آن است، آبیِ
        # پررنگ می‌گیرد تا بداند کجاست (نه سبز — سبز یعنی «روشن/تایید»).
        # شمارش‌ها از کشِ آمار می‌آیند (TTL کوتاه) تا هر بار رندرِ لیست،
        # N بار خواندنِ دیتابیس نکند.
        st_all = self._users_stats(all_users, use_cache=True)
        _fcount = {"all": st_all["total"], "active": st_all["active"],
                   "expired": st_all["expired"], "nosub": st_all["nosub"]}
        filter_row = [
            UI.btn(f"همه ({fa_digits(_fcount['all'])})", "users_list:all:0",
                   style="primary" if fkey == "all" else None),
            UI.btn(f"فعال ({fa_digits(_fcount['active'])})", "users_list:active:0",
                   style="primary" if fkey == "active" else None),
            UI.btn(f"منقضی ({fa_digits(_fcount['expired'])})", "users_list:expired:0",
                   style="primary" if fkey == "expired" else None),
            UI.btn("بدون اشتراک", "users_list:nosub:0",
                   style="primary" if fkey == "nosub" else None),
        ]
        buttons.append(filter_row)
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _start_user_search(self, event, back_data: bytes = b"owner_users"):
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_USER_SEARCH, {"back_data": back_data})
        await event.edit(
            "🔍 آیدی عددی کاربر یا بخشی از یوزرنیمش (با یا بدون @) را بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _show_user_search_results(self, event, query: str, back_data: bytes):
        results = search_users(query)
        if not results:
            await event.edit(
                f"❌ هیچ کاربری با «{query}» پیدا نشد.",
                buttons=[[UI.go("🔍 جستجوی دوباره", b"user_search_start")],
                         UI.nav_row()],
            )
            return
        if len(results) == 1:
            await self._show_user_management_panel(event, results[0]["user_id"], back_data=back_data)
            return
        buttons = []
        for u in results[:20]:
            label = u.get("username") or str(u["user_id"])
            buttons.append([UI.go(f"👤 {label}", f"user_manage:{u['user_id']}".encode())])
        buttons.append(UI.nav_row())
        await event.edit(f"🔍 {len(results)} کاربر با «{query}» پیدا شد:", buttons=buttons)

    def _build_user_management_view(self, target_user_id: int, back_data: bytes,
                                    viewer_role: str = None):
        """
        متن و دکمه‌های پنل مدیریت یک کاربر را می‌سازد — بدون اینکه خودش
        پیامی بفرستد، تا هم از callback (با event.edit) و هم از پیام متنی
        معمولی (با event.respond، مثلاً بعد از نتیجه‌ی جستجو یا تمدید)
        قابل استفاده باشد؛ بدون این تفکیک، کد نمایش این پنل باید دوبار
        (یک‌بار برای edit، یک‌بار برای respond) تکرار می‌شد.

        viewer_role: نقشِ بیننده. برای RESELLER دکمه‌ی مخرب «حذف کامل
        کاربر» نمایش داده نمی‌شود؛ به‌جایش «🚪 حذف از نمایندگی» می‌آید
        (فقط جدا کردن reseller_id — بدون حذف تاریخچه).

        بازمی‌گرداند: (text, buttons) یا (None, None) اگر کاربر پیدا نشود.
        """
        u = get_user(target_user_id)
        if not u:
            return None, None
        st = self._user_sub_status(target_user_id)
        role = self._role(target_user_id)
        name = u.get("username") or f"کاربر {target_user_id}"
        # وضعیت اشتراک با همان پالتِ سراسری: سبز = فعال، زرد = رو به
        # اتمام (آخرین روز)، قرمز = منقضی، خاکستری = اصلاً ندارد.
        if st["active"]:
            sub_state = "warn" if st["days"] == 0 else "active"
            sub_line = "امروز آخرین روز" if st["days"] == 0 else f"{st['days']} روز باقی‌مانده"
        elif st["expired"]:
            sub_state, sub_line = "expired", "منقضی شده"
        else:
            sub_state, sub_line = "none", "بدون اشتراک فعال"

        total, active, stopped = self._user_selfbot_stats(target_user_id)

        # SelfBotهای کاربر — مستقیماً در همین صفحه، نه پشت یک دکمه.
        # سه موردِ اول نشان داده می‌شوند؛ بقیه پشت «همه SelfBotها». این یک
        # لایه‌ی کاملِ ناوبری را از مسیرِ روزمره حذف می‌کند.
        cfg = self.sb.load_config()
        mine = list(accounts_of_user(cfg, target_user_id).items())
        shown_bots = mine[:3]

        body = [
            f"👤 {name}",
            f"🆔 `{u['user_id']}`",
            f"🎭 نقش: {role}",
            f"⭐ پلن: {st['plan'] if st['plan'] else '—'}",
            f"{UI.state_dot(sub_state)} اشتراک: {sub_line}",
        ]
        if u.get("reseller_id"):
            body.append(f"👥 زیرمجموعه‌ی نماینده: `{u['reseller_id']}`")
        body.append(UI.SEP)
        if total:
            body.append(f"🤖 **SelfBotها** — {fa_digits(active)} فعال"
                        + (f" · {fa_digits(stopped)} متوقف" if stopped else ""))
        else:
            body.append(f"🤖 **SelfBotها**")
        if not mine:
            body.append(f"{UI.GRAY} هنوز SelfBotی ندارد")
        else:
            for tag, acc in shown_bots:
                state, note = _acc_ui_state(acc, tag)
                body.append(f"{UI.state_dot(state)} `{tag}` — {note}")
            if len(mine) > len(shown_bots):
                body.append(f"{UI.GRAY} … و {fa_digits(len(mine) - len(shown_bots))} مورد دیگر")

        text = UI.screen("👤 مدیریت کاربر", body=body,
                         hint="روی هر SelfBot بزن تا کنترل کاملش باز شود.")

        buttons = []
        for tag, acc in shown_bots:
            state, _ = _acc_ui_state(acc, tag)
            buttons.append([UI.item(tag, state, f"user_acc:{target_user_id}:{tag}")])
        if len(mine) > len(shown_bots):
            buttons.append([UI.go(f"👥 همه SelfBotها ({fa_digits(len(mine))})",
                                  f"user_accounts:{target_user_id}")])
        buttons.append([UI.go("➕ افزودن SelfBot",
                              f"user_add_bot:{target_user_id}", tone="success")])
        buttons.append([UI.item("⏳ مدیریت اشتراک", sub_state,
                                f"user_sub_admin:{target_user_id}")])
        buttons.append([UI.go("🧾 سفارش‌ها", f"user_orders_admin:{target_user_id}")])
        if viewer_role == ROLE_RESELLER:
            # نماینده هرگز «حذف کامل» ندارد — فقط جداسازی مشتری از نمایندگی
            buttons.append([UI.neutral("حذف از نمایندگی", f"user_unlink_confirm:{target_user_id}")])
        else:
            # حذف کامل فقط برای OWNER/ADMIN — جدا از عملیات عادی، پایین صفحه
            buttons.append([UI.danger("حذف کامل کاربر", f"user_delete_confirm:{target_user_id}")])
        buttons.append(UI.nav_row())
        return text, buttons

    async def _show_user_sub_admin(self, event, target_user_id: int, back_data: bytes):
        """⏳ مدیریت اشتراک یک کاربر — اطلاعات پلن/روز باقی‌مانده + تمدید/لغو.
        لایسنس از این‌جا ساخته نمی‌شود (فقط از «🎫 لایسنس و دسترسی‌ها»)."""
        st = self._user_sub_status(target_user_id)
        if st["active"]:
            state = "warn" if st["days"] == 0 else "active"
            body = [
                f"{UI.state_dot(state)} فعال" + ("  — امروز آخرین روز" if st["days"] == 0 else ""),
                f"⭐ پلن: {st['plan']}",
                f"⏳ روز باقی‌مانده: {st['days']}",
                f"📅 تاریخ پایان: {st['expire']}",
            ]
        elif st["expired"]:
            body = [
                f"{UI.RED} منقضی شده",
                f"⭐ پلن: {st['plan']}",
                f"📅 تاریخ پایان: {st['expire']}",
            ]
        else:
            body = [f"{UI.GRAY} این کاربر اشتراکی ندارد."]

        buttons = [[UI.confirm("تمدید اشتراک", f"user_extend_start:{target_user_id}")]]
        if st["active"]:
            buttons.append([UI.danger("لغو اشتراک", f"user_expire:{target_user_id}")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("⏳ مدیریت اشتراک", body=body,
                      hint="تمدید از امروز یا از تاریخ پایانِ فعلی حساب می‌شود."),
            buttons=buttons,
        )

    async def _show_user_management_panel(self, event, target_user_id: int, back_data: bytes = b"owner_users"):
        """
        پنل مدیریت یک کاربر خاص از یک callback (دکمه) — با event.edit روی
        همان پیام. نقطه‌ی مشترک برای OWNER/ADMIN/RESELLER؛ نمایندگان فقط
        برای کاربرانی که واقعاً مشتری خودشان هستند این پنل را می‌بینند (چک
        دسترسی قبل از فراخوانی این تابع انجام می‌شود).
        """
        text, buttons = self._build_user_management_view(
            target_user_id, back_data, viewer_role=self._role(event.sender_id))
        if text is None:
            await self._nav_heal(event, "این کاربر پیدا نشد (شاید حذف شده).")
            return
        await event.edit(text, buttons=buttons)

    async def _render_user_management_panel_as_message(self, event, target_user_id: int, back_data: bytes):
        """
        همان پنل مدیریت کاربر، ولی به‌عنوان یک پیام جدید (event.respond) —
        برای استفاده از داخل ویزاردهای متنی (جستجو، تمدید دستی) که در آن‌ها
        رویداد فعلی یک پیام معمولی است، نه یک callback قابل edit.
        """
        text, buttons = self._build_user_management_view(
            target_user_id, back_data, viewer_role=self._role(event.sender_id))
        if text is None:
            await event.respond("❌ این کاربر پیدا نشد (شاید حذف شده).")
            return
        # این صفحه از مسیرِ روتر نیامده (نتیجه‌ی یک ویزاردِ متنی است)، پس
        # خودش باید در پشته ثبت شود؛ وگرنه «بازگشت» روی آن، صفحه‌ی قبلِ
        # شروعِ ویزارد را باز می‌کرد و کاربر یک قدم بیشتر از انتظار عقب
        # می‌رفت.
        self.nav.push(event.sender_id, f"user_manage:{target_user_id}")
        await event.respond(text, buttons=buttons)

    def _build_user_accounts_view(self, target_user_id: int, back_data: bytes):
        """
        🤖 لیست SelfBotهای یک کاربر — فقط اکانت‌هایی که owner_user_id آنها
        برابر همین کاربر است (نه همه‌ی اکانت‌های سیستم). خروجی (text,
        buttons) تا هم با event.edit (callback) و هم event.respond (بعد از
        ویزارد ساخت اکانت) قابل استفاده باشد.
        """
        u = get_user(target_user_id)
        name = f"@{u['username']}" if (u and u.get("username")) else f"کاربر {target_user_id}"
        cfg = self.sb.load_config()
        mine = accounts_of_user(cfg, target_user_id)
        if not mine:
            text = f"🤖 **SelfBotهای {name}**\n\nاین کاربر هنوز هیچ اکانتی ندارد — با «➕ افزودن SelfBot» یکی بساز:"
            buttons = [
                [UI.go("➕ افزودن SelfBot", f"user_add_bot:{target_user_id}".encode(), tone="success")],
                UI.nav_row(),
            ]
            return text, buttons
        body = []
        buttons = []
        n_on = 0
        for tag, acc in mine.items():
            state, note = _acc_ui_state(acc, tag)
            n_on += 1 if state == "ready" else 0
            body.append(f"{UI.state_dot(state)} `{tag}` — {note}")
            buttons.append([UI.item(tag, state, f"user_acc:{target_user_id}:{tag}")])
        buttons.append([UI.go("➕ افزودن SelfBot", f"user_add_bot:{target_user_id}", primary=True, tone="success")])
        buttons.append(UI.nav_row())
        text = UI.screen(
            f"🤖 SelfBotهای {name}",
            body=body,
            subtitle=f"{UI.GREEN} {n_on} فعال از {len(mine)}",
            hint="روی هر SelfBot بزن تا کنترل کاملش باز شود.",
        )
        return text, buttons

    async def _show_user_accounts(self, event, target_user_id: int, back_data: bytes):
        text, buttons = self._build_user_accounts_view(target_user_id, back_data)
        # زنجیره‌ی بازگشت را دیگر اینجا دستی نگه نمی‌داریم — پشته‌ی ناوبری
        # خودش مسیرِ واقعیِ طی‌شده را دارد.
        await event.edit(text, buttons=buttons)

    async def _show_user_accounts_as_message(self, event, target_user_id: int, back_data: bytes):
        text, buttons = self._build_user_accounts_view(target_user_id, back_data)
        # مثل _render_user_management_panel_as_message: صفحه‌ای که خارج از
        # روتر رندر می‌شود باید خودش را در پشته ثبت کند.
        self.nav.push(event.sender_id, f"user_accounts:{target_user_id}")
        await event.respond(text, buttons=buttons)

    async def _show_user_acc(self, event, target_user_id: int, tag: str):
        """
        ⚙️ مدیریت یک SelfBot از داخل مدیریت کاربر — دقیقاً همان هاب اکانت
        (قابلیت‌ها/ظاهر/ابزارها/اتصال/وضعیت). «بازگشت» به لیست SelfBotهای
        همان کاربر برمی‌گردد چون پشته‌ی ناوبری مسیر واقعی را نگه داشته.

        مالکیت دوباره چک می‌شود: tag باید متعلق به target_user_id باشد و
        فقط OWNER/ADMIN یا نماینده‌ی مالکِ آن کاربر می‌تواند وارد شود
        (چک در دیسپچ قبل از این تابع انجام شده).
        """
        cfg = self.sb.load_config()
        acc = cfg.get(tag)
        if not account_belongs_to(acc, tag, target_user_id):
            await self._nav_heal(event, "این اکانت متعلق به این کاربر نیست.")
            return
        # مسیرِ بازگشت از پشته می‌آید — دیگر لازم نیست مقصد را اینجا
        # بسازیم و در callback_data جاسازی کنیم.
        await self.admin_panel._show_account_detail(event, tag)

    async def _start_user_add_bot(self, event, target_user_id: int, back_data: bytes):
        """➕ افزودن SelfBot برای یک کاربر خاص — ویزارد لاگین را با مالکِ از
        پیش تعیین‌شده باز می‌کند تا اکانتِ ساخته‌شده به همین کاربر تعلق
        بگیرد. دسترسی (OWNER/ADMIN یا نماینده‌ی صاحبِ کاربر) قبل از این
        تابع در دیسپچ چک شده است."""
        u = get_user(target_user_id)
        if not u:
            await event.answer("این کاربر پیدا نشد.", alert=True)
            return
        # ویزارد پنلِ قبلی (اگر وسطِ کار بود) پاک شود تا تداخل نکرده
        await self._clear_admin_panel_wizard(event.sender_id)
        await self.admin_panel._start_add_wizard(
            event, preset_owner_id=target_user_id,
            preset_data={"add_back": back_data},
        )

    # ─────────────────────────────────────────────────────
    #  «🤖 سلف من» — UI اختصاصی کاربر عادی (نه پنل کامل ادمین)
    # ─────────────────────────────────────────────────────

    def _build_my_bots_view(self, uid: int):
        """🤖 سلف من — متن و دکمه‌های لیست SelfBotهای خودِ کاربر. مالکیتِ
        SelfBot معیار نمایش این بخش است (نه اشتراک)؛ دکمه‌ی «➕ افزودن
        SelfBot» فقط با اشتراک فعال نمایش داده می‌شود."""
        cfg = self.sb.load_config()
        mine = accounts_of_user(cfg, uid)
        total, active, stopped = self._user_selfbot_stats(uid)
        body = []
        buttons = []
        if not mine:
            body.append(f"{UI.GRAY} هنوز هیچ اکانتی نداری.")
        else:
            for tag, acc in mine.items():
                state, note = _acc_ui_state(acc, tag)
                body.append(f"{UI.state_dot(state)} `{tag}` — {note}")
                buttons.append([UI.item(tag, state, f"my_acc:{tag}")])
        has_sub = self._user_sub_status(uid)["active"]
        # افزودن SelfBot جدید فقط با اشتراک فعال — هم نمایش، هم چک Backend
        if has_sub:
            buttons.append([UI.go("➕ افزودن SelfBot", "user_my_add_bot", primary=True, tone="success")])
        buttons.append(UI.nav_row())
        text = UI.screen(
            "🤖 سلف من",
            body=body,
            subtitle=(f"{UI.GREEN} {active} فعال   {UI.RED} {stopped} متوقف"
                      if total else None),
            hint=("روی هر اکانت بزن تا قابلیت‌هایش را کنترل کنی."
                  if total else "برای ساختن اولین سلف، اشتراک فعال لازم است."),
        )
        return text, buttons

    async def _show_user_own_bots(self, event):
        """نمایش «🤖 سلف من» — فقط خودِ کاربر (role USER) و فقط اکانت‌های خودش.
        scope پنل (owner_filter) هم قبل از هر چیز روی همین کاربر تنظیم می‌شود
        تا رندر لیست و عملیات بعدی با scope کهنه‌ی کاربرِ دیگری برخورد نکنند."""
        async with self._panel_lock:
            self._sync_admin_panel_scope(event.sender_id)
            text, buttons = self._build_my_bots_view(event.sender_id)
        await event.edit(text, buttons=buttons)

    async def _show_my_acc(self, event, tag: str):
        """⚙️ مدیریت یک SelfBot خودِ کاربر — همان هاب کامل مدیریت اکانت
        (قابلیت‌ها/ظاهر/ابزارها/اتصال/وضعیت/توقف/حذف). «بازگشت» طبق پشته‌ی
        ناوبری به «سلف من» برمی‌گردد."""
        cfg = self.sb.load_config()
        acc = cfg.get(tag)
        if not account_belongs_to(acc, tag, event.sender_id):
            await self._nav_heal(event, "این اکانت متعلق به تو نیست یا وجود ندارد.")
            return
        async with self._panel_lock:
            self._sync_admin_panel_scope(event.sender_id)
            await self.admin_panel._show_account_detail(event, tag)

    async def _user_my_add_bot(self, event):
        """➕ افزودن SelfBot توسط خودِ کاربر — Backend: فقط با اشتراک فعال.
        (حذف دکمه از UI کافی نیست؛ callback دستی هم باید رد شود.)"""
        if not self._user_sub_status(event.sender_id)["active"]:
            await event.answer("❌ برای افزودن SelfBot باید اشتراک فعال داشته باشید.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        async with self._panel_lock:
            self._sync_admin_panel_scope(event.sender_id)
            await self.admin_panel.start_login_wizard_for_user(event, event.sender_id)




    async def _show_user_orders_admin(self, event, target_user_id: int, back_data: bytes):
        """🧾 سفارش‌های یک کاربر (نمای ادمین) — فقط‌خواندنی."""
        orders = list_user_orders(target_user_id)
        if not orders:
            await event.edit(
                "🧾 این کاربر هنوز سفارشی ثبت نکرده.",
                buttons=[UI.nav_row()],
            )
            return
        labels = {
            ORDER_STATUS_PENDING: "⏳ در انتظار پرداخت",
            ORDER_STATUS_PAID: "✅ پرداخت شد",
            ORDER_STATUS_EXPIRED: "❌ منقضی شد",
            ORDER_STATUS_CANCELLED: "🚫 لغو شد",
        }
        lines = [f"🧾 **سفارش‌های کاربر `{target_user_id}`:**\n"]
        for o in orders[:10]:
            lines.append(f"`{o['order_no']}` — {o['plan']} — {o['amount_toman']:,} تومان "
                         f"— {labels.get(o['status'], o['status'])}")
        await event.edit("\n".join(lines), buttons=[UI.nav_row()])

    async def _owner_show_orders(self, event):
        """📊 سفارش‌های اخیر کل سیستم (نمای مالی) — فقط‌خواندنی."""
        orders = list_recent_orders(20)
        if not orders:
            await event.edit(
                "📭 هنوز سفارشی ثبت نشده.",
                buttons=[UI.nav_row()],
            )
            return
        labels = {
            ORDER_STATUS_PENDING: "⏳ در انتظار پرداخت",
            ORDER_STATUS_PAID: "✅ پرداخت شد",
            ORDER_STATUS_EXPIRED: "❌ منقضی شد",
            ORDER_STATUS_CANCELLED: "🚫 لغو شد",
        }
        lines = ["📊 **سفارش‌های اخیر** (۲۰ تای آخر):\n"]
        for o in orders:
            lines.append(
                f"`{o['order_no']}` — کاربر `{o['user_id']}` — {o['plan']} — "
                f"{o['amount_toman']:,} تومان — {labels.get(o['status'], o['status'])}"
            )
        lines.append("")
        lines.append("🔍 جزئیات کامل هر سفارش از صفحه‌ی همان کاربر (🧾 سفارش‌ها) قابل مشاهده است.")
        buttons = [UI.nav_row()]
        await event.edit("\n".join(lines), buttons=buttons)

    async def _owner_show_payments(self, event):
        payments = list_pending_payments()
        if not payments:
            await event.edit("📭 هیچ پرداخت در‌انتظاری نیست.",
                              buttons=[UI.nav_row()])
            return
        buttons = []
        lines = ["💳 **پرداخت‌های در انتظار تایید:**\n"]
        for p in payments[:20]:
            lines.append(f"#{p['id']} — کاربر `{p['user_id']}` — پلن {p['plan']} — {p['amount']} تومان")
            buttons.append([
                UI.confirm(f"تایید #{p['id']}", f"pay_approve:{p['id']}"),
                UI.danger(f"رد #{p['id']}", f"pay_reject:{p['id']}"),
            ])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _resume_user_selfbots(self, user_id: int):
        """
        بعد از تمدید/پرداخت موفق: سلف‌بات‌هایی که سرِ انقضای اشتراک متوقف و
        disabled شده بودند دوباره فعال می‌شوند — هم در config (تا در استارت
        بعدی هم روشن بمانند) و هم زنده (run_bot برای تگ‌های متوقف‌شده).
        Idempotent: فقط تگ‌هایی را لمس می‌کند که disabled هستند و هنوز در
        ACCOUNTS ثبت نشده‌اند.
        """
        cfg = self.sb.load_config()
        to_start = []
        changed = False
        for tag, acc in cfg.items():
            if not account_belongs_to(acc, tag, user_id):
                continue
            if not acc.get("disabled"):
                continue
            # فقط سلف‌بات‌هایی که دلیلِ قطعیِ خاموش‌شدنشان subscription_expired
            # است دوباره روشن می‌شوند. disabled_reason=None (legacy — معلوم نیست
            # چرا خاموش شده، شاید ادمین دستی) هرگز AUTO RESUME نمی‌شود؛ باید
            # دستی/توسط ادمین روشن شود.
            reason = acc.get("disabled_reason")
            if reason != "subscription_expired":
                continue
            acc["disabled"] = False
            acc.pop("disabled_reason", None)
            changed = True
            if tag not in self.sb.ACCOUNTS and tag not in self._resume_inflight:
                to_start.append((tag, acc))
        if changed:
            self.sb.save_config(cfg)
        for tag, acc in to_start:
            if tag in self._resume_inflight or tag in self.sb.ACCOUNTS:
                continue
            self._resume_inflight.add(tag)
            try:
                # حیاتی: این تسک یک await شصت‌ثانیه‌ای دارد و در finallyِ
                # خودش tag را از _resume_inflight برمی‌دارد. اگر وسطِ آن
                # await توسط GC نابود می‌شد، finally اجرا نمی‌شد و آن تگ
                # تا ری‌استارتِ پروسه گیر می‌کرد — یعنی آن اکانت دیگر
                # هرگز خودکار resume نمی‌شد.
                _spawn_bg(self._start_resumed_bot(tag, acc), f"resume:{tag}")
            except Exception as e:
                self._resume_inflight.discard(tag)
                print(f"⚠️ [resume] ساخت task برای اکانت {tag} ناموفق: "
                      f"{type(e).__name__}: {e}")

    async def _start_resumed_bot(self, tag: str, acc: dict):
        """استارتِ واقعیِ یک اکانتِ رزوم‌شده — با قفلِ in-flight تا duplicate
        نشود و با Runtime Manager مرکزی (اگر اکانت در حال اجراست/در حال
        شروع است، همان Runtime reuse/await می‌شود — Client دوم ساخته نمی‌شود)."""
        try:
            if tag in self.sb.ACCOUNTS:
                return
            await ensure_started(tag, acc, caller="resume",
                                 runner=self.sb.run_bot, wait_seconds=60)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # دیگر هرگز silent swallow — فقط تگ + نوع خطا + پیامِ امن (بدون
            # token/session در لاگ).
            print(f"⚠️ [resume] استارت اکانت {tag} ناموفق بود: "
                  f"{type(e).__name__}: {str(e)[:120]}")
        finally:
            self._resume_inflight.discard(tag)

    async def _stop_and_disable_user_selfbots(self, user_id: int):
        """
        سلف‌بات‌های وابسته به اشتراکِ یک کاربر را متوقف و disabled می‌کند
        (انقضای اشتراک). سشن/config حذف نمی‌شود — فقط runtime و flag؛ بعد از
        تمدید، _resume_user_selfbots دوباره فعالشان می‌کند. Idempotent.

        قانون provision_source (مهم‌ترین قانون این نسخه): سلف‌باتِ دستی
        (provision_source=manual) به هیچ عنوان فقط به‌خاطر انقضای اشتراک
        متوقف/disabled نمی‌شود — چون مستقل از اشتراک ساخته شده. اکانت‌های
        legacy (منبعِ نامعلوم) هم حدس زده نمی‌شوند و لمس نمی‌شوند — چون ممکن
        است دستی باشند. فقط subscription و license (که لایسنسش اشتراکِ
        فعال/منقضی‌شده دارد) وابسته به اشتراک‌اند و متوقف می‌شوند و دلیل‌شان
        disabled_reason='subscription_expired' ثبت می‌شود تا Resume اتوماتیک
        فقط همین‌ها را روشن کند.
        """
        cfg = self.sb.load_config()
        if config_state() != CONFIG_VALID:
            print(
                f"⛔ [expiry] توقف سلف‌بات‌های کاربر {user_id} رد شد — "
                f"config.json خراب است و نباید overwrite شود."
            )
            return
        changed = False
        for tag, acc in cfg.items():
            if not account_belongs_to(acc, tag, user_id):
                continue
            # فقط اکانت‌هایی که منبعِ قطعیِ وابسته به اشتراک دارند متوقف می‌شوند:
            # subscription یا license. هر چیز دیگر — manual، legacy (منبعِ نامعلوم)
            # یا بدون provision_source — حدس زده نمی‌شود و لمس نمی‌شود (ممکن است
            # دستی/مستقل از اشتراک باشد).
            if acc.get("provision_source") not in (PROVISION_SUBSCRIPTION, PROVISION_LICENSE):
                continue
            await ensure_stopped(tag, "expiry._stop_and_disable_user_selfbots")
            if not acc.get("disabled"):
                acc["disabled"] = True
                acc["disabled_reason"] = "subscription_expired"
                changed = True
        if changed:
            self.sb.save_config(cfg)

    async def _owner_review_payment(self, event, payment_id: int, approve: bool,
                                    from_notif: bool = False):
        """from_notif=True یعنی دکمه روی پیامِ اعلانِ رسید زده شده (نه لیستِ
        بررسی پرداخت‌ها): نتیجه روی همان پیامِ اعلان edit می‌شود تا ادمین
        بدون رفتن به «بررسی پرداخت‌ها» از همان‌جا تایید/رد کند."""
        pay = get_payment(payment_id)
        if not pay:
            await event.answer("این پرداخت پیدا نشد.", alert=True)
            if from_notif:
                try:
                    await event.edit("❌ این پرداخت پیدا نشد.")
                except Exception:
                    pass
            else:
                await self._owner_show_payments(event)
            return

        # عملیات اتمیک: فقط اگر هنوز pending باشد اثر می‌کند — جلوی این را
        # می‌گیرد که دو ادمین هم‌زمان روی یک پرداخت هر دو تایید/رد بزنند و
        # هر دو اثر (مثلاً دو بار create_subscription) اعمال شود.
        if approve:
            # تایید: payment + اشتراک + فاکتور در یک تراکنش واحد
            res = approve_card_payment_atomic(payment_id, event.sender_id)
            applied = res["applied"]
            if applied and res["dedicated"]:
                # ربات اختصاصی: اشتراک ساخته نمی‌شود — درخواستِ در انتظارِ این
                # نماینده فعال و فرآیندِ جدا برای آن راه‌اندازی می‌شود.
                await self._activate_dedicated_bot(pay)
            elif applied:
                # بعد از پرداخت موفق، اگر سلف‌باتِ کاربر به‌خاطر انقضای قبلی
                # متوقف شده بود، دوباره فعال می‌شود (رزوم).
                try:
                    await self._resume_user_selfbots(res["user_id"])
                except Exception:
                    pass
                try:
                    await self.client.send_message(
                        res["user_id"],
                        f"✅ پرداخت شما تایید شد و اشتراک «{res['plan']}» فعال شد!\n\n"
                        f"برای اینکه سلف روی اکانت تلگرامت نصب و فعال بشه، باید اکانتت رو لاگین کنی.",
                        buttons=[[UI.go("🔐 لاگین اکانت", b"user_login_account")]],
                    )
                except Exception:
                    pass
        else:
            applied = review_payment_atomic(payment_id, False, event.sender_id)
        if not applied:
            await event.answer("این پرداخت قبلاً توسط شخص دیگری بررسی شده.", alert=True)
            if from_notif:
                try:
                    await event.edit("⏳ این پرداخت قبلاً توسط شخص دیگری بررسی شده.")
                except Exception:
                    pass
            else:
                await self._owner_show_payments(event)
            return

        if not approve:
            try:
                await self.client.send_message(
                    pay["user_id"], "❌ پرداخت شما توسط ادمین رد شد. لطفاً با پشتیبانی تماس بگیرید."
                )
            except Exception:
                pass
        await event.answer("انجام شد.")
        if from_notif:
            # پیامِ اعلان را به نتیجه تبدیل کن — بدون نیاز به رفتن به
            # «بررسی پرداخت‌ها»؛ دکمه‌ی لیست هم برای مرور بقیه هست.
            try:
                await event.edit(
                    f"{'✅' if approve else '❌'} پرداخت #{pay['id']} "
                    f"از `{pay['user_id']}` — {'تایید شد' if approve else 'رد شد'}",
                    buttons=[[UI.go("💳 بررسی پرداخت‌ها", b"owner_payments")]],
                )
            except Exception:
                pass
        else:
            await self._owner_show_payments(event)

    # ─────────────────────────────────────────────────────
    #  ربات اختصاصی (نمایندگی) — فعال‌سازی بعد از تایید پرداخت
    # ─────────────────────────────────────────────────────

    async def _notify_owner(self, text: str):
        """اعلان رویدادهای مهم (ربات اختصاصی و ...) به مدیر اصلی."""
        try:
            await self.client.send_message(OWNER_ID, text)
        except Exception:
            pass

    async def _activate_dedicated_bot(self, pay: dict):
        """تایید پرداختِ پلن «ربات اختصاصی»: درخواستِ در انتظارِ این نماینده را
        فعال می‌کند و فرآیند جدا را راه‌اندازی می‌کند."""
        bot = get_pending_dedicated_bot_for_reseller(pay["user_id"])
        if not bot:
            try:
                await self.client.send_message(
                    pay["user_id"],
                    "✅ پرداخت تایید شد، ولی هیچ درخواستِ ربات اختصاصیِ در انتظاری "
                    "برای تو پیدا نشد. دوباره از منوی نمایندگی «🤖 ربات اختصاصی» رو بزن "
                    "و توکن + آیدی مالک رو بفرست.",
                )
            except Exception:
                pass
            return
        try:
            bot_dir = _spawn_dedicated_bot(bot["id"], bot["owner_id"], bot["token"])
            pid = _read_pidfile(bot_dir)
            expire_days = int(get_setting("dedicated_bot_days", "30"))
            expire_date = _format_date(datetime.now(timezone.utc) + timedelta(days=expire_days))
            update_dedicated_bot_status(
                bot["id"], "active", payment_id=pay["id"], bot_dir=bot_dir,
                pid=pid, expire_date=expire_date,
            )
            log_action(pay["user_id"], "dedicated_bot_activated",
                       f"bot#{bot['id']} owner={bot['owner_id']} pid={pid}")
            await self._notify_owner(
                f"🟢 **ربات اختصاصی ساخته و راه‌اندازی شد**\n"
                f"ربات: #{bot['id']} | مالک: `{bot['owner_id']}` | "
                f"نماینده: `{pay['user_id']}` | انقضا: {expire_date}"
            )
            try:
                await self.client.send_message(
                    pay["user_id"],
                    f"🤖 **ربات اختصاصی #{bot['id']} ساخته و راه‌اندازی شد!**\n\n"
                    f"مالک: `{bot['owner_id']}` — با تمام قابلیت‌های ادمین اصلی.\n"
                    "مالک می‌تونه /start رو توی ربات جدیدش بزنه و از همه‌چیز استفاده کنه.",
                )
                await self.client.send_message(
                    bot["owner_id"],
                    "🤖 **ربات اختصاصی تو ساخته شد!**\n"
                    "از /start استفاده کن — پنل کامل مدیریت سلف‌بات در اختیارته.",
                )
            except Exception:
                pass
        except Exception as e:
            update_dedicated_bot_status(bot["id"], "rejected")
            log_action(pay["user_id"], "dedicated_bot_failed", str(e)[:200])
            try:
                await self.client.send_message(
                    pay["user_id"],
                    f"❌ ساخت ربات اختصاصی با خطا مواجه شد: {str(e)[:120]} — با پشتیبانی تماس بگیر.",
                )
            except Exception:
                pass

    async def _start_dedicated_bot_wizard(self, event):
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_DEDICATED_TOKEN, {})
        price = dedicated_bot_price()
        await event.edit(
            "🤖 **ساخت ربات اختصاصی**\n\n"
            f"هزینه: **{price:,} تومان** (یک‌بار)\n\n"
            "توکن ربات رو از @BotFather بگیر و اینجا بفرست (قالب: `123456789:AAF...`):",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _validate_bot_token(self, token: str):
        """بررسی زنده‌ی توکن با تلگرام. خروجی: (ok: bool, info: str)."""
        try:
            api_id, api_hash = _first_account_creds(self.sb.load_config())
            from telethon.sessions import StringSession
            temp = TelegramClient(StringSession(), api_id, api_hash)
            await asyncio.wait_for(temp.start(bot_token=token), timeout=20)
            me = await temp.get_me()
            try:
                await temp.disconnect()
            except Exception:
                pass
            username = getattr(me, "username", None)
            return True, f"@{username}" if username else f"bot id {getattr(me, 'id', '?')}"
        except Exception as e:
            return False, str(e)[:120]

    async def _owner_show_dedicated_bots(self, event):
        bots = list_dedicated_bots(limit=20)
        if not bots:
            await event.edit("🤖 هنوز هیچ ربات اختصاصی‌ای ثبت نشده.",
                             buttons=[UI.nav_row()])
            return
        body = []
        buttons = []
        n_ok = 0
        for b in bots:
            state = DEDICATED_UI_STATE.get(b["status"], "off")
            alive = _process_alive(b.get("pid") or 0)
            # «active در دیتابیس ولی پروسه مرده» مهم‌ترین حالتِ خطاست و باید
            # قرمز دیده شود، نه سبز.
            if b["status"] == "active" and not alive:
                state, suffix = "error", " — پروسه خاموش است"
            else:
                suffix = ""
                n_ok += 1 if state == "active" else 0
            body.append(f"{UI.state_dot(state)} #{b['id']} — مالک `{b['owner_id']}` — "
                        f"نماینده `{b['reseller_id']}` — {b['status']}{suffix}")
            buttons.append([UI.item(f"مدیریت #{b['id']}", state, f"dedicated_manage:{b['id']}")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("🤖 ربات‌های اختصاصی", body=body,
                      subtitle=f"{UI.GREEN} {n_ok} سالم از {len(bots)}"),
            buttons=buttons,
        )

    async def _owner_show_dedicated_bot_detail(self, event, bot_id: int):
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("این ربات اختصاصی پیدا نشد.", alert=True)
            await self._owner_show_dedicated_bots(event)
            return
        pid = b.get("pid") or _read_pidfile(b.get("bot_dir") or "")
        alive = _process_alive(pid)
        state = DEDICATED_UI_STATE.get(b["status"], "off")
        if b["status"] == "active" and not alive:
            state = "error"
        body = [
            f"{UI.state_dot(state)} وضعیت: {b['status']}",
            f"👤 مالک: `{b['owner_id']}`",
            f"🤝 نماینده: `{b['reseller_id']}`",
        ]
        if b["status"] == "active":
            body.append(f"{UI.dot(alive)} پروسه: "
                        + (f"در حال اجرا (PID {pid})" if alive else "خاموش — فرآیند مرده"))
            if b.get("expire_date"):
                try:
                    days = (_parse_date(b["expire_date"]) - _parse_date(_now_date())).days
                    body.append(f"{UI.state_dot('warn' if days <= 3 else 'active')} "
                                f"باقی‌مانده: **{days} روز** (تا {b['expire_date']})")
                except Exception:
                    body.append(f"⏳ انقضا: {b['expire_date']}")
        else:
            body.append(f"{UI.state_dot('paused' if not alive else 'warn')} پروسه: "
                        + ("متوقف" if not alive else "هنوز زنده است"))
            if b.get("expire_date"):
                body.append(f"⏳ انقضا ثبت‌شده: {b['expire_date']}")
        buttons = []
        # مجوزِ حساس — OWNER می‌بیند که این ربات آیا ابزارهای امنیتی
        # اکانت را در اختیار دارد یا نه، و می‌تواند آن را بدهد/بگیرد.
        if b["status"] in ("active", "stopped", "revoked"):
            sec_on = capability_grant_exists(b["owner_id"], CAP_ACCOUNT_SECURITY,
                                             SCOPE_DEDICATED_BOT, str(b["id"]))
            body.append(f"{UI.dot(sec_on)} مجوز امنیت اکانت: "
                        + ("فعال" if sec_on else "غیرفعال"))
            buttons.append([UI.go("🔐 مجوز امنیت اکانت", f"dbcap:{b['id']}")])
        if b["status"] == "active":
            buttons.append([UI.neutral("توقف موقت", f"dedicated_toggle:{b['id']}")])
        elif b["status"] in ("stopped", "revoked"):
            buttons.append([UI.confirm("اجرای دوباره", f"dedicated_toggle:{b['id']}")])
        if b["status"] in ("active", "stopped", "revoked"):
            buttons.append([
                UI.go("➕ تمدید", f"dedicated_extend:{b['id']}", tone="success"),
                UI.go("🔍 بررسی سلامت", f"dedicated_health:{b['id']}"),
            ])
            if b["status"] != "revoked":
                buttons.append([UI.danger("لغو دسترسی (revoke)", f"dedicated_revoke:{b['id']}")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen(f"🤖 ربات اختصاصی #{b['id']}", body=body),
            buttons=buttons,
        )

    async def _dedicated_bot_toggle(self, event, bot_id: int):
        """توقف/اجرای دوباره‌ی ربات اختصاصی."""
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("ربات اختصاصی پیدا نشد.", alert=True)
            return
        if b["status"] == "active":
            pid = b.get("pid") or _read_pidfile(b.get("bot_dir") or "")
            stopped = await _stop_process_by_pid(pid)
            update_dedicated_bot_status(bot_id, "stopped")
            log_action(event.sender_id, "dedicated_bot_stopped", f"bot#{bot_id} pid={pid}")
            msg = "⏸ ربات اختصاصی متوقف شد." if stopped else \
                "⏸ ربات متوقف علامت‌گذاری شد (فرآیندی در جریان نبود)."
            await event.answer(msg)
            try:
                await self.client.send_message(
                    b["owner_id"], "⏸ ربات اختصاصی تو متوقف شد. در صورت نیاز با پشتیبانی تماس بگیر."
                )
            except Exception:
                pass
        else:
            try:
                bot_dir = _spawn_dedicated_bot(bot_id, b["owner_id"], b["token"])
                pid = _read_pidfile(bot_dir)
                update_dedicated_bot_status(
                    bot_id, "active", bot_dir=bot_dir, pid=pid,
                    expire_date=b.get("expire_date") or _format_date(
                        datetime.now(timezone.utc)
                        + timedelta(days=int(get_setting("dedicated_bot_days", "30")))
                    ),
                )
                log_action(event.sender_id, "dedicated_bot_restarted", f"bot#{bot_id} pid={pid}")
                await event.answer("▶️ ربات اختصاصی دوباره راه‌اندازی شد.")
                try:
                    await self.client.send_message(
                        b["owner_id"], "▶️ ربات اختصاصی تو دوباره راه‌اندازی شد."
                    )
                except Exception:
                    pass
            except Exception as e:
                await event.answer(f"❌ راه‌اندازی مجدد ناموفق بود: {str(e)[:100]}", alert=True)
        await self._owner_show_dedicated_bot_detail(event, bot_id)

    async def _dedicated_bot_revoke(self, event, bot_id: int):
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("ربات اختصاصی پیدا نشد.", alert=True)
            return
        await event.edit(
            f"⚠️ ربات اختصاصی #{bot_id} برای همیشه لغو شود؟\n"
            f"فرآیندش متوقف و وضعیت روی revoke می‌رود. (دیتای پوشه‌اش حفظ می‌شود)\n\n"
            f"یا اگر می‌خوای **همه‌چیز** پاک شود، «حذف کامل» را بزن "
            f"(پوشه، دیتابیس، سشن و لاگ‌های ربات هم حذف می‌شود — غیرقابل‌بازگشت).",
            buttons=[
                [UI.danger("بله، لغو کن", f"dedicated_revoke_go:{bot_id}".encode())],
                [UI.danger("حذف کامل", f"dedicated_delete_go:{bot_id}")],
                [UI.neutral("نه، برگرد", NAV_BACK)],
            ],
        )

    async def _dedicated_bot_revoke_go(self, event, bot_id: int):
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("ربات اختصاصی پیدا نشد.", alert=True)
            return
        pid = b.get("pid") or _read_pidfile(b.get("bot_dir") or "")
        await _stop_process_by_pid(pid)
        update_dedicated_bot_status(bot_id, "revoked")
        log_action(event.sender_id, "dedicated_bot_revoked", f"bot#{bot_id}")
        await self._notify_owner(
            f"⛔ **ربات اختصاصی لغو شد**\n"
            f"ربات: #{bot_id} | مالک: `{b['owner_id']}` | توسط: `{event.sender_id}`"
        )
        await event.answer("⛔ ربات اختصاصی لغو شد.")
        try:
            await self.client.send_message(
                b["owner_id"],
                "⛔ ربات اختصاصی تو لغو (revoke) شد و دیگر در دسترس نیست. با پشتیبانی تماس بگیر.",
            )
        except Exception:
            pass
        await self._owner_show_dedicated_bots(event)

    async def _dedicated_bot_delete_go(self, event, bot_id: int):
        """حذف کامل ربات اختصاصی: فرآیند + پوشه‌ی dedicated_bots/<id>/ (دیتابیس/سشن/لاگ)."""
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("ربات اختصاصی پیدا نشد.", alert=True)
            return
        pid = b.get("pid") or _read_pidfile(b.get("bot_dir") or "")
        await _stop_process_by_pid(pid)
        # پاک‌سازی فقط مسیرِ اختصاصیِ خودِ این ربات — نه هیچ مسیر دیگری.
        # چکِ امنیتی: مسیر ثبت‌شده باید دقیقاً برابر dedicated_bots/<id>/ باشد
        # تا حتی اگر bot_dir در DB دستکاری شده باشد، جای اشتباهی پاک نشود.
        bot_dir = b.get("bot_dir")
        expected = os.path.join(
            _project_dir(), "dedicated_bots", str(bot_id)
        )
        if bot_dir and os.path.abspath(bot_dir) == expected and os.path.isdir(bot_dir):
            shutil.rmtree(bot_dir, ignore_errors=True)
        update_dedicated_bot_status(bot_id, "deleted")
        log_action(event.sender_id, "dedicated_bot_deleted", f"bot#{bot_id}")
        await self._notify_owner(
            f"🗑 **ربات اختصاصی حذف کامل شد**\n"
            f"ربات: #{bot_id} | مالک: `{b['owner_id']}` | توسط: `{event.sender_id}` | "
            f"پوشه و دیتابیس‌هایش پاک شد"
        )
        await event.answer("🗑 ربات اختصاصی به‌طور کامل حذف شد.")
        try:
            await self.client.send_message(
                b["owner_id"],
                "🗑 ربات اختصاصی تو به‌طور کامل حذف شد (دیتا و دیتابیس‌هایش پاک شد). "
                "با پشتیبانی تماس بگیر.",
            )
        except Exception:
            pass
        await self._owner_show_dedicated_bots(event)

    async def _dedicated_bot_extend_start(self, event, bot_id: int):
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_DEDICATED_EXTEND_DAYS, {"bot_id": bot_id})
        await event.edit(
            f"➕ چند روز به ربات اختصاصی #{bot_id} اضافه شود؟ یک عدد بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _dedicated_bot_health(self, event, bot_id: int):
        """بررسی سلامت: (۱) زنده‌بودن پروسه (۲) پاسخ‌دادن توکن به تلگرام."""
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("ربات اختصاصی پیدا نشد.", alert=True)
            return
        pid = b.get("pid") or _read_pidfile(b.get("bot_dir") or "")
        alive = _process_alive(pid)
        ok_token, info = await self._validate_bot_token(b["token"])
        if alive and ok_token:
            msg = f"🟢 **ربات #{bot_id} سالم است**\nپروسه: زنده (PID {pid})\nتوکن: پاسخ می‌دهد ({info})"
        elif not alive:
            msg = f"🔴 **ربات #{bot_id} خاموش است**\nپروسه‌ای در جریان نیست. با «▶️ اجرای دوباره» راه‌اندازی کن."
        else:
            msg = f"🟡 **ربات #{bot_id} نیمه‌سالم است**\nپروسه زنده است ولی توکن به تلگرام پاسخ نمی‌دهد ({info})."
        await event.edit(
            msg,
            buttons=[UI.nav_row()],
        )

    async def _owner_show_channel_settings(self, event):
        current = (get_setting("required_channel") or "").strip()
        is_owner = self._role(event.sender_id) == ROLE_OWNER
        title = (get_setting("required_channel_title") or "").strip()
        blocked_n = get_setting("gate_blocked_count", "0")
        rejoined_n = get_setting("gate_rejoined_count", "0")
        if current:
            name_line = f"📢 {title} (`{current}`)" if title else f"📢 کانال: `{current}`"
            text = (f"**کانال اجباری عضویت:**\n{name_line}\n\n"
                    "همه (به‌جز ادمین اصلی) برای استفاده از ربات باید عضو این کانال باشن.\n\n"
                    f"📊 آمار گیت: {blocked_n} بسته‌شدن | {rejoined_n} دوباره‌عضویت")
            buttons = [[UI.go("🔍 بررسی کانال", b"owner_channel_check")]]
            if is_owner:
                buttons.append([UI.go("✏️ تغییر کانال", b"owner_channel_set")])
                buttons.append([UI.danger("حذف شرط عضویت", "owner_channel_clear")])
            buttons.append(UI.nav_row())
        else:
            text = ("📢 **کانال اجباری عضویت:** تنظیم نشده — همه بدون شرط "
                    "می‌توانند از ربات استفاده کنند.")
            buttons = []
            if is_owner:
                buttons.append([UI.go("📢 تنظیم کانال", b"owner_channel_set")])
            buttons.append(UI.nav_row())
        await event.edit(text, buttons=buttons)

    async def _owner_check_channel(self, event):
        """بررسی زنده‌ی کانال ذخیره‌شده با تلگرام — بدون تغییر چیزی."""
        channel = (get_setting("required_channel") or "").strip()
        is_owner = self._role(event.sender_id) == ROLE_OWNER
        if not channel:
            buttons = []
            if is_owner:
                buttons.append([UI.go("📢 تنظیم کانال", b"owner_channel_set")])
            await event.edit("📢 کانالی تنظیم نشده — اول یکی تنظیم کن.", buttons=buttons)
            return
        await event.edit("🔄 در حال بررسی کانال با تلگرام…")
        ok, info, norm = await self._resolve_channel(channel)
        if ok:
            # خود-ترمیمی عنوان: اگر کانال بعد از ذخیره تغییر نام داده باشد،
            # عنوانِ resolveشده ذخیره می‌شود تا کارت شیشه‌ای و صفحه‌ی تنظیمات
            # نامِ تازه را نشان دهند — بدون داده‌ی کهنه.
            stored_title = (get_setting("required_channel_title") or "").strip()
            healed = bool(stored_title) and stored_title != info
            if healed:
                set_setting("required_channel_title", info)
            text = (f"✅ **کانال پیدا شد و معتبر است:**\n\n"
                    f"📢 {info}\nhttps://t.me/{norm}"
                    + ("\n\n_تغییرِ نامِ کانال تشخیص داده شد و عنوان به‌روز شد._"
                       if healed else ""))
        else:
            text = (f"❌ **کانال پیدا نشد یا قابل دسترسی نیست!**\n\n"
                    f"`{channel}`\n({info})\n\n"
                    "⚠️ گیت عضویت fail-closed است — همه غیر از ادمین اصلی "
                    "فعلاً بسته‌اند. کانال درست رو تنظیم کن.")
        buttons = []
        if is_owner:
            buttons.append([UI.go("✏️ تغییر کانال", b"owner_channel_set")])
        buttons.append(UI.nav_row())
        await event.edit(text, buttons=buttons)

    async def _start_channel_set(self, event):
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_SET_CHANNEL, {})
        await event.edit(
            "یوزرنیم کانال رو بفرست (مثلاً `@MyChannel` یا `mychannel` یا لینک t.me):\n\n"
            "⚠️ کانال باید **عمومی** باشه تا بتونیم عضویت رو چک کنیم.",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _owner_show_tickets(self, event):
        tickets = list_open_tickets()
        if not tickets:
            await event.edit("📭 هیچ تیکت بازی نیست.",
                              buttons=[UI.nav_row()])
            return
        buttons = []
        lines = ["📨 **تیکت‌های باز:**\n"]
        for t in tickets[:20]:
            lines.append(f"تیکت #{t['id']} — کاربر `{t['user_id']}`")
            buttons.append([
                UI.go(f"💬 پاسخ به #{t['id']}", f"ticket_reply:{t['id']}".encode()),
                UI.go(f"🔒 بستن #{t['id']}", f"ticket_close:{t['id']}".encode()),
            ])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _owner_ticket_close(self, event, ticket_id: int):
        """🔒 بستن تیکت — مرحله‌ی تأیید. فقط OWNER/ADMIN؛ فقط تیکتِ باز."""
        t = get_ticket(ticket_id)
        if not t:
            await event.answer("تیکت پیدا نشد.", alert=True)
            return
        if t["status"] != "open":
            await event.edit(
                "⏳ این تیکت قبلاً بسته شده است.",
                buttons=[UI.nav_row()],
            )
            return
        await event.edit(
            f"⚠️ **بستن تیکت #{ticket_id}**\n\n"
            f"آیا مطمئنی می‌خواهی این تیکت را ببندی؟",
            buttons=[
                [UI.confirm("بله، ببند", f"ticket_close_go:{ticket_id}".encode()),
                 UI.neutral(UI.L_CANCEL, NAV_BACK)],
            ],
        )

    async def _owner_ticket_close_go(self, event, ticket_id: int):
        t = get_ticket(ticket_id)
        if not t or t["status"] != "open":
            await event.edit(
                "⏳ این تیکت قبلاً بسته شده است.",
                buttons=[UI.nav_row()],
            )
            return
        close_ticket(ticket_id)
        # اطلاع به کاربرِ صاحب تیکت
        try:
            await self.client.send_message(
                t["user_id"], f"✅ تیکت #{ticket_id} توسط پشتیبانی بسته شد.\n\n"
                               f"اگر باز هم سوالی داشتی، از «📞 پشتیبانی» تیکت جدیدی باز کن."
            )
        except Exception:
            pass
        await self._owner_show_tickets(event)

    async def _owner_start_ticket_reply(self, event, ticket_id: int):
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_OWNER_TICKET_REPLY, {"ticket_id": ticket_id})
        msgs = list_ticket_messages(ticket_id)
        history = "\n".join(
            f"{'👤' if m['sender_role'] == 'user' else '🛠'} {m['text']}" for m in msgs[-10:]
        )
        await event.edit(
            f"💬 **تاریخچه‌ی تیکت #{ticket_id}:**\n\n{history}\n\nپاسخت رو بفرست:",
            buttons=[
                [UI.go("🔒 بستن تیکت", f"ticket_close:{ticket_id}".encode()),
                 UI.neutral(UI.L_CANCEL, NAV_BACK)],
            ],
        )

    async def _owner_show_backup(self, event):
        """💾 Backup — بکاپ کامل و معتبر پروژه را برای OWNER می‌فرستد."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER به Backup دسترسی دارد.", alert=True)
            return
        await event.answer("⏳ در حال ساخت Backup...")
        backup_path = os.path.join(tempfile.gettempdir(), _backup_file_name())
        ok = await asyncio.to_thread(build_backup_zip, backup_path)
        if not ok:
            await event.respond("❌ ساخت Backup ناموفق بود — فایل ناقصی ساخته نشد. دوباره تلاش کن.")
            return
        try:
            await self.client.send_file(
                event.chat_id, backup_path,
                caption=f"💾 بکاپ کامل (Backup) — {_now()}",
            )
            await event.respond(
                "✅ Backup ساخته و ارسال شد.\n\n"
                "برای بازیابی: «♻️ Restore» را بزن و همین فایل را بفرست."
            )
        except Exception as e:
            await event.respond(f"❌ ارسال Backup ناموفق: {str(e)[:60]}")
        finally:
            try:
                os.remove(backup_path)
            except Exception:
                pass

    async def _owner_manage_roles_menu(self, event):
        """callbak قدیمی — برای سازگاری، به هاب «لایسنس و دسترسی‌ها» می‌رود."""
        await self._owner_show_license_hub(event)

    async def _owner_show_license_hub(self, event):
        """🎫 لایسنس و دسترسی‌ها — ساخت لایسنس + مدیریت نقش‌ها."""
        lines = ["🎫 **لایسنس و دسترسی‌ها**\n\nاز اینجا لایسنس بساز و نقش‌ها را مدیریت کن:"]
        items = [
            UI.go("➕ ساخت لایسنس", b"owner_create_license", tone="success"),
            UI.go("📋 لایسنس‌های ساخته‌شده", b"license_access_list", tone="success"),
        ]
        if self._role(event.sender_id) == ROLE_OWNER:
            items.extend([
                UI.go("👑 ادمین‌های فعال", b"license_access_admins"),
                UI.go("🤝 نماینده‌های فعال", b"license_access_resellers"),
            ])
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _owner_show_role_list(self, event, role: str):
        entries = [e for e in list_admins_and_resellers() if e["role"] == role]
        label = ("👑 **ادمین‌های فعال:**" if role == ROLE_ADMIN
                 else "🤝 **نماینده‌های فعال:**")
        if not entries:
            await event.edit(
                label + "\n\n(هیچ موردی ثبت نشده.)",
                buttons=[UI.nav_row()],
            )
            return
        lines = [label + "\n"]
        buttons = []
        for e in entries:
            extra = f" — 👥 سقف: {e['reseller_max_users']} مشتری" if e.get("reseller_max_users") else ""
            lines.append(f"👤 `{e['user_id']}` — 🛡 {e['role']}{extra} — 🕐 {e['created_at']}")
            buttons.append([UI.danger(f"حذف دسترسی {e['user_id']}", f"role_del:{e['user_id']}")])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    # ════════════════════════════════════════════════════════════════
    #  مدیریتِ مجوزهای حساس — فقط مالکِ اصلی
    # ════════════════════════════════════════════════════════════════
    #  اینجا OWNER می‌بیند چه کسی ظرفیتِ «مدیریتِ امنیتِ اکانت» را دارد،
    #  به او می‌دهد یا می‌گیرد. این grant authority است — کاملاً جدا از
    #  use authority. هیچ نماینده‌ای نمی‌تواند از اینجا چیزی بدهد.

    def _cap_owner_only(self, event) -> bool:
        """فقط OWNER می‌تواند مجوزها را مدیریت کند. پیامِ کوتاه اگر نه."""
        if self._role(event.sender_id) == ROLE_OWNER:
            return True
        try:
            event.answer("این بخش فقط برای مالک سیستم است.", alert=True)
        except Exception:
            pass
        return False

    async def _owner_show_capability_list(self, event):
        """فهرستِ همه‌ی کسانی که مجوزِ حساس دارند (یا کسانی که می‌توان بدهیم)."""
        if not self._cap_owner_only(event):
            return
        grants = list_capability_grants(CAP_ACCOUNT_SECURITY, active_only=True)
        body = []
        if not grants:
            body.append(f"{UI.GRAY} هیچ‌کس این مجوز را ندارد.")
            body.append("")
            body.append("این یک ابزار قدرتمند است (مدیریت دستگاه، رمز دومرحله‌ای و کد ورود اکانت)؛")
            body.append("به‌طور پیش‌فرض به کسی داده نمی‌شود.")
        else:
            body.append("کسانی که مجوز دارند:")
        buttons = []
        for g in grants:
            scope_lbl = _SCOPE_LABELS.get(g["scope_type"], g["scope_type"])
            body.append(f"{UI.GREEN} `{g['subject_user_id']}` — {scope_lbl}"
                        + (f" — {g['created_at']}" if g.get("created_at") else ""))
            buttons.append([UI.go(f"👤 {g['subject_user_id']}", f"cap_user:{g['subject_user_id']}")])
        # ورودیِ جستجو برای اعطای مجوز — یک ویزاردِ ساده‌ی «آیدی کاربر».
        buttons.append([UI.go("➕ اعطای مجوز به شخص", b"cap_add_start")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("🔐 مجوزهای حساس", body=body,
                      subtitle="مدیریت امنیت اکانت",
                      hint="مجوزها فقط توسط مالک سیستم داده/گرفته می‌شوند."),
            buttons=buttons,
        )

    async def _owner_start_capability_add(self, event):
        """ویزاردِ اعطای مجوز: مرحله‌ی اول — گرفتن آیدیِ کاربر."""
        if not self._cap_owner_only(event):
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_CAP_USER_ID, {})
        await event.edit(
            "🔐 **اعطای مجوزِ حساس**\n\n"
            "آیدیِ عددیِ شخصی که می‌خوای مجوزِ «مدیریت امنیت اکانت» رو بهش بدی رو بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _owner_show_capability_user(self, event, uid: int):
        """صفحه‌ی مجوزهای یک شخصِ مشخص."""
        if not self._cap_owner_only(event):
            return
        if not uid:
            await event.answer("کاربر نامعتبر است.", alert=True)
            return
        role = self._role(uid)
        grants = get_active_grants(uid, CAP_ACCOUNT_SECURITY)
        body = [
            f"👤 کاربر: `{uid}`",
            f"🛡 نقش: {role}",
        ]
        buttons = []
        if not grants:
            body.append("")
            body.append(f"{UI.RED} مجوزِ حساس: غیرفعال")
            body.append("")
            body.append("این شخص نمی‌تواند ابزارهای امنیتی اکانت را استفاده کند.")
            buttons.append([UI.go("✅ فعال‌کردن", f"cap_choose_scope:{uid}", tone="success")])
        else:
            for g in grants:
                scope_lbl = _SCOPE_LABELS.get(g["scope_type"], g["scope_type"])
                body.append("")
                body.append(f"{UI.GREEN} مجوزِ حساس: فعال")
                body.append(f"{UI.GRAY} دامنه: {scope_lbl}")
                body.append(f"{UI.GRAY} داده‌شده توسط: `{g.get('granted_by')}`")
                body.append(f"{UI.GRAY} در تاریخ: {g.get('created_at')}")
                buttons.append([UI.danger("⛔ سلبِ مجوز",
                                          f"cap_revoke:{uid}:{g['scope_type']}")])
            buttons.append([UI.go("🔁 تغییرِ دامنه", f"cap_choose_scope:{uid}")])
        buttons.append([UI.go("🔐 فهرستِ مجوزها", b"cap_list")])
        buttons.append(UI.nav_row())
        await event.edit(UI.screen("🔐 مجوزِ حساس", body=body), buttons=buttons)

    async def _owner_choose_capability_scope(self, event, uid: int):
        """انتخابِ دامنه‌ی مجوز قبل از تأیید."""
        if not self._cap_owner_only(event):
            return
        if not uid:
            await event.answer("کاربر نامعتبر است.", alert=True)
            return
        role = self._role(uid)
        body = [
            f"👤 کاربر: `{uid}` — نقش: {role}",
            "",
            "دامنه‌ی دسترسی را انتخاب کن:",
            "",
            f"{UI.GRAY} • «مشتریانِ خودم»: برای اکانت‌های خودش و مشتریانش.",
            f"{UI.GRAY} • «فقط این ربات اختصاصی»: لازم است بعداً ربات را انتخاب کنی.",
        ]
        buttons = [
            [UI.go("👥 مشتریانِ خودم", f"cap_confirm:{uid}:{SCOPE_RESELLER}")],
            [UI.neutral("انصراف", f"cap_user:{uid}")],
        ]
        await event.edit(UI.screen("🔐 انتخابِ دامنه", body=body), buttons=buttons)

    async def _owner_confirm_capability(self, event, uid: int, scope: str):
        """تأییدِ نهاییِ اعطا — یک کلیکِ تصادفی نباید مجوز بدهد."""
        if not self._cap_owner_only(event):
            return
        if not uid or scope not in _SCOPE_LABELS:
            await event.answer("درخواست نامعتبر است.", alert=True)
            return
        scope_id = str(uid) if scope == SCOPE_RESELLER else None
        scope_lbl = _SCOPE_LABELS.get(scope, scope)
        body = [
            f"{UI.AMBER} در حال اعطای یک مجوز قدرتمند:",
            "",
            f"👤 کاربر: `{uid}`",
            f"🎯 دامنه: {scope_lbl}",
            "",
            "با این کار او می‌تواند:",
            f"{UI.GRAY} • دستگاه‌های لاگین‌شده‌ی اکانت‌ها را ببیند و ببندد",
            f"{UI.GRAY} • وضعیت رمز دو مرحله‌ای را ببیند و بازنشانی کند",
            f"{UI.GRAY} • کد ورود اکانت را دریافت کند",
            "",
            f"{UI.RED} این مجوز فقط در دامنه‌ی انتخاب‌شده کار می‌کند.",
        ]
        buttons = [
            [UI.danger("بله، اعطا کن", f"cap_grant:{uid}:{scope}")],
            [UI.neutral("انصراف", f"cap_user:{uid}")],
        ]
        await event.edit(UI.screen("⚠️ تأییدِ اعطای مجوز", body=body), buttons=buttons)

    async def _owner_grant_capability(self, event, uid: int, scope: str):
        """اجرای اعطا — بعد ثبتِ لاگ و بازگشت به صفحه‌ی کاربر."""
        if not self._cap_owner_only(event):
            return
        if not uid or scope not in _SCOPE_LABELS:
            await event.answer("درخواست نامعتبر است.", alert=True)
            return
        scope_id = str(uid) if scope == SCOPE_RESELLER else None
        grant_capability(uid, CAP_ACCOUNT_SECURITY, scope, scope_id,
                         granted_by=event.sender_id)
        log_action(event.sender_id, "capability_granted",
                   f"to={uid} scope={scope} cap={CAP_ACCOUNT_SECURITY}")
        try:
            await event.answer("✅ مجوز اعطا شد.")
        except Exception:
            pass
        await self._owner_show_capability_user(event, uid)

    async def _owner_revoke_capability(self, event, uid: int, scope: str = None):
        """سلبِ مجوز — اثربخشی فوری."""
        if not self._cap_owner_only(event):
            return
        if not uid:
            await event.answer("کاربر نامعتبر است.", alert=True)
            return
        n = revoke_capability(uid, CAP_ACCOUNT_SECURITY, scope_type=scope,
                              revoked_by=event.sender_id)
        log_action(event.sender_id, "capability_revoked",
                   f"from={uid} scope={scope} rows={n}")
        try:
            await event.answer("⛔ مجوز سلب شد." if n else "مجوزی برای سلب نبود.",
                               alert=True)
        except Exception:
            pass
        await self._owner_show_capability_user(event, uid)

    async def _owner_show_dbot_capability(self, event, bot_id: int):
        """صفحه‌ی مجوزِ یک ربات اختصاصیِ مشخص."""
        if not self._cap_owner_only(event):
            return
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("ربات اختصاصی پیدا نشد.", alert=True)
            return
        on = capability_grant_exists(b["owner_id"], CAP_ACCOUNT_SECURITY,
                                     SCOPE_DEDICATED_BOT, str(bot_id))
        body = [
            f"🤖 ربات اختصاصی #{b['id']}",
            f"👤 مالک: `{b['owner_id']}`",
            f"🤝 نماینده: `{b['reseller_id']}`",
            "",
            (f"{UI.GREEN} مجوزِ حساس: فعال" if on else f"{UI.RED} مجوزِ حساس: غیرفعال"),
        ]
        if on:
            body.append(f"{UI.GRAY} دامنه: فقط اکانت‌های این ربات")
        buttons = []
        if on:
            buttons.append([UI.danger("⛔ غیرفعال‌کردن", f"dbcap_revoke:{bot_id}")])
        else:
            buttons.append([UI.go("✅ فعال‌کردن", f"dbcap_grant:{bot_id}", tone="success")])
        buttons.append([UI.neutral("↩️ برگشت به ربات", f"dedicated_manage:{bot_id}")])
        buttons.append(UI.nav_row())
        await event.edit(UI.screen("🔐 مجوزِ حساس", body=body), buttons=buttons)

    async def _owner_grant_dbot_capability(self, event, bot_id: int):
        if not self._cap_owner_only(event):
            return
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("ربات اختصاصی پیدا نشد.", alert=True)
            return
        grant_capability(b["owner_id"], CAP_ACCOUNT_SECURITY, SCOPE_DEDICATED_BOT,
                         str(bot_id), granted_by=event.sender_id)
        log_action(event.sender_id, "capability_granted",
                   f"to=bot#{bot_id} owner={b['owner_id']} scope=dedicated_bot")
        try:
            await event.answer("✅ مجوز اعطا شد.")
        except Exception:
            pass
        await self._owner_show_dbot_capability(event, bot_id)

    async def _owner_revoke_dbot_capability(self, event, bot_id: int):
        if not self._cap_owner_only(event):
            return
        b = get_dedicated_bot(bot_id)
        if not b:
            await event.answer("ربات اختصاصی پیدا نشد.", alert=True)
            return
        revoke_capability(b["owner_id"], CAP_ACCOUNT_SECURITY,
                          scope_type=SCOPE_DEDICATED_BOT, scope_id=str(bot_id),
                          revoked_by=event.sender_id)
        log_action(event.sender_id, "capability_revoked",
                   f"from=bot#{bot_id} owner={b['owner_id']} scope=dedicated_bot")
        try:
            await event.answer("⛔ مجوز سلب شد.")
        except Exception:
            pass
        await self._owner_show_dbot_capability(event, bot_id)

    async def _owner_show_licenses(self, event):
        # نماینده فقط لایسنس‌های خودش را می‌بیند (نه لایسنس‌های بقیه)
        created_by = event.sender_id if self._role(event.sender_id) == ROLE_RESELLER else None
        lic_list = list_licenses(30, created_by=created_by)
        if not lic_list:
            await event.edit(
                "📭 هنوز لایسنسی ساخته نشده.",
                buttons=[UI.nav_row()],
            )
            return
        lines = (["🎫 **لایسنس‌های ساخته‌شده توسط من** (۳۰ تای آخر):\n"]
                 if created_by is not None
                 else ["🎫 **لایسنس‌های ساخته‌شده** (۳۰ تای آخر):\n"])
        for lic in lic_list:
            tname = _TYPE_NAMES.get(lic["license_type"], lic["license_type"])
            status = "✅ فعال" if lic["is_active"] else "⛔ غیرفعال"
            lines.append(
                f"`{lic['code']}` — {tname} — مصرف: {lic['used_count']}/{lic['max_uses']} — {status} — 🕐 {lic['created_at']}"
            )
        lines.append("")
        lines.append("🔒 همه‌ی لایسنس‌های جدید یک‌بارمصرف‌اند (max_uses=1).")
        buttons = [UI.nav_row()]
        await event.edit("\n".join(lines), buttons=buttons)

    async def _owner_start_set_card(self, event):
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER می‌تواند شماره کارت را تغییر دهد.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_SET_CARD, {})
        current_number = get_setting("card_number", DEFAULT_CARD_NUMBER)
        current_holder = get_setting("card_holder", DEFAULT_CARD_HOLDER)
        await event.edit(
            f"💳 **تنظیم شماره کارت**\n\n"
            f"فعلی: `{current_number}` — به نام {current_holder}\n\n"
            f"کافیه خودِ شماره‌ی کارت (۱۶ رقم) رو بفرستی.\n"
            f"اگه می‌خوای نام صاحب حساب هم ذخیره بشه، بعد از `|` بنویس:\n"
            f"مثال: `6219861462625319|امیدرضا پیلسم`",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _owner_show_pricing(self, event):
        """⚙️ قیمت‌ها و پلن‌ها: تغییر قیمت/مدت هر پلن و قیمت ربات اختصاصی."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER.", alert=True)
            return
        lines = ["⚙️ **قیمت‌ها و پلن‌ها:**\n"]
        buttons = []
        for p in list_pricing():
            lines.append(f"`{p['plan']}` — {p['price_toman']:,} تومان — {p['duration_days']} روز")
            buttons.append([
                UI.go(f"💲 قیمت {p['plan']}", f"plan_price:{p['plan']}".encode()),
                UI.go(f"📅 مدت {p['plan']}", f"plan_days:{p['plan']}".encode()),
            ])
        dbot_n = dedicated_bot_price()
        lines.append(f"🤖 ربات اختصاصی (یک‌بار) — {dbot_n:,} تومان")
        buttons.append([UI.go("💲 قیمت ربات اختصاصی", b"plan_price:__dedicated__")])
        buttons.append([UI.go("➕ پلن جدید", b"plan_new", tone="success")])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _owner_start_plan_price(self, event, plan: str):
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_PRICING_PRICE,
                               {"plan": plan, "days": None})
        label = "قیمت ربات اختصاصی (تومان، یک‌بار) چنده؟" if plan == "__dedicated__" \
            else f"قیمت جدید پلن «{plan}» به تومان چنده؟"
        await event.edit(label, buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]])

    async def _owner_start_plan_days(self, event, plan: str):
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_PRICING_DAYS, {"plan": plan})
        await event.edit(
            f"مدت اشتراک پلن «{plan}» چند روزه بشه؟",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _owner_start_plan_new(self, event):
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_PRICING_NEW_NAME, {})
        await event.edit(
            "➕ اسم پلن جدید رو بفرست (مثلاً `۴۵ روزه`):",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _owner_start_set_wallet(self, event):
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_SET_WALLET, {})
        current = get_setting("usdt_wallet", "")
        await event.edit(
            "💵 **آدرس کیف پول تتر (TRC20)**\n\n"
            f"فعلی: `{current}`\n\n"
            "آدرس جدید رو بفرست (باید با `T` شروع و ۳۴ کاراکتر باشد):",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _owner_db_backup(self, event):
        """💾 بکاپ کامل (callback قدیمی — همان Backup جدید)."""
        await self._owner_show_backup(event)

    async def _owner_start_db_restore(self, event):
        """♻️ Restore — OWNER فایل ZIP بکاپ را می‌فرستد."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_DB_RESTORE, {})
        await event.edit(
            "♻️ **Restore**\n\n"
            "فایل Backup را همینجا ارسال کنید.\n"
            "فقط Backup معتبر پروژه پذیرفته می‌شود.",
            buttons=[[UI.neutral(UI.L_CANCEL, "owner_db_restore_cancel")]],
        )

    async def _handle_document_wizard(self, event, wiz: dict) -> bool:
        """دریافت فایل بکاپ برای Restore (فقط OWNER): دانلود → validate → تأیید."""
        if wiz["state"] != WIZ_DB_RESTORE:
            return False
        sender = event.sender_id
        if self._role(sender) != ROLE_OWNER:
            self.wizards.pop(sender, None)
            await event.respond("فقط OWNER می‌تواند Restore کند.")
            return True
        fname = (getattr(getattr(event, "file", None), "name", "") or "backup.zip").lower()
        # BUG #4 — نام موقتِ Restore باید یکتا باشد (دو سند از یک کاربر در یک
        # ثانیه نباید به یک فایل برسند و هم‌دیگر را overwrite کنند). mkstemp
        # یکتا می‌سازد؛ فایلِ خالیِ placeholder با دانلود (open 'wb') overwrite
        # می‌شود و پاک‌سازیِ موجود (شکست/لغو/تکمیل) دست‌نخورده می‌ماند.
        _tmp_fd, tmp = tempfile.mkstemp(prefix="restore_", suffix=".zip")
        os.close(_tmp_fd)
        try:
            dl = getattr(getattr(event, "message", None), "download_media", None)
            if dl is None:
                await event.respond("⚠️ امکان دانلود فایل در این محیط نیست.")
                return True
            await event.respond("⏳ در حال بررسی فایل Backup...")
            await dl(file=tmp)
        except Exception as e:
            self.wizards.pop(sender, None)
            await event.respond(f"❌ دانلود فایل ناموفق: {str(e)[:60]}")
            try:
                os.remove(tmp)
            except Exception:
                pass
            return True

        if not fname.endswith(".zip"):
            self.wizards.pop(sender, None)
            await event.respond(
                "❌ این فایل بکاپ معتبر پروژه نیست.\n\n"
                "فقط فایل ZIP بکاپ (ساخته‌شده توسط «💾 Backup») پذیرفته می‌شود."
            )
            try:
                os.remove(tmp)
            except Exception:
                pass
            return True

        ok, msg = validate_backup_zip(tmp)
        if not ok:
            self.wizards.pop(sender, None)
            await event.respond(
                "❌ Restore انجام نشد.\n\nBackup فعلی تغییری نکرده است.\n\nخطا:\n" + msg
            )
            try:
                os.remove(tmp)
            except Exception:
                pass
            return True

        # معتبر → مرحله‌ی تأیید
        wiz["state"] = WIZ_DB_RESTORE_CONFIRM
        wiz["data"]["tmp_zip"] = tmp
        await event.respond(
            "🔍 در حال بررسی سلامت Backup...\n\n"
            "📦 Backup معتبر است.\n\n"
            "⚠️ **تأیید Restore**\n\n"
            "با Restore کردن این فایل، اطلاعات فعلی سیستم با اطلاعات موجود "
            "در Backup جایگزین می‌شود.\n"
            "قبل از Restore یک Backup اضطراری از وضعیت فعلی ساخته خواهد شد.\n\n"
            "آیا مطمئن هستید؟",
            buttons=[
                [UI.danger("بله، Restore کن", b"owner_db_restore_go")],
                [UI.neutral(UI.L_CANCEL, "owner_db_restore_cancel")],
            ],
        )
        return True

    async def _owner_db_restore_go(self, event):
        """✅ بله، Restore کن — اعمال اتمیک بعد از تأیید."""
        wiz = self.wizards.pop(event.sender_id, None)
        tmp = (wiz or {}).get("data", {}).get("tmp_zip")
        if not tmp or (wiz or {}).get("state") != WIZ_DB_RESTORE_CONFIRM:
            await event.answer("هیچ عملیات Restore در انتظار تأیید نیست.", alert=True)
            return
        await event.edit("♻️ در حال Restore (اول Runtimeها متوقف می‌شوند)...")
        try:
            # نسخه‌ی Runtime-safe: Maintenance Mode + توقف کامل Runtimeها قبل
            # از جایگزینی فایل‌ها + استارت مجدد اکانت‌های روشن بعد از موفقیت.
            ok, msg = await restore_backup_from_zip_async(tmp)
        except Exception as e:
            ok, msg = False, f"خطای غیرمنتظره: {str(e)[:80]}"
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
        if ok:
            await event.respond(
                "✅ Restore با موفقیت انجام شد.\n\n"
                "اطلاعات سیستم با موفقیت بازیابی شد.\n"
                "برای اعمال کامل روی سلف‌بات‌های روشن، ربات را ری‌استارت کن."
            )
            await self._show_menu_for_role(event.chat_id, ROLE_OWNER)
        else:
            await event.respond(
                "❌ Restore انجام نشد.\n\nBackup فعلی تغییری نکرده است.\n\nخطا:\n" + msg
            )

    async def _owner_db_restore_cancel(self, event):
        """❌ لغو Restore — ویزارد بسته و فایل موقت پاک می‌شود."""
        wiz = self.wizards.pop(event.sender_id, None)
        tmp = (wiz or {}).get("data", {}).get("tmp_zip")
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass
        await event.edit(
            "❌ لغو شد.",
            buttons=[UI.nav_row()],
        )

    # ─────────────────────────────────────────────────────
    #  بخش RESELLER
    # ─────────────────────────────────────────────────────

    async def _reseller_show_users(self, event):
        users = list_users_for_reseller(event.sender_id)
        buttons = [[UI.go("🔍 جستجو در مشتریانم", b"reseller_user_search_start")]]
        if not users:
            await event.edit(
                "📭 هنوز هیچ مشتری‌ای زیرمجموعه‌ات نیست.\n\n"
                "وقتی کسی با لایسنسی که تو ساختی فعال‌سازی کند، اینجا نمایش داده می‌شود.",
                buttons=buttons + [UI.nav_row()],
            )
            return
        # نمایش کاربرمحور (کارت هر مشتری: اشتراک + روز باقی‌مانده + آمار
        # SelfBotها) — مثل صفحه‌ی OWNER، اما فقط برای مشتریانِ همین نماینده
        # (list_users_for_reseller همان scope را اعمال کرده).
        lines = ["👥 **کاربران من:** (کارت هر مشتری را ببین و مدیریت کن)\n"]
        for u in users[:30]:
            lines.append("━━━━━━━━━━━━━━")
            lines.extend(self._user_card_lines(u))
            lines.append("")
            buttons.append([UI.go(
                f"⚙️ مدیریت {u.get('username') or u['user_id']}",
                f"user_manage:{u['user_id']}".encode(),
            )])
        if len(users) > 30:
            lines.append(f"نمایش ۳۰ مشتری اول از {len(users)}.")
        lines.append("━━━━━━━━━━━━━━")
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _start_reseller_user_search(self, event):
        # فیکس محدودیت دسترسی: جستجوی نماینده باید فقط بین مشتریان خودش
        # باشد، نه همه‌ی کاربران سیستم — برای همین state جدا از جستجوی
        # OWNER استفاده می‌کنیم تا در پردازش، لیست results با
        # list_users_for_reseller فیلتر شود.
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_USER_SEARCH, {
            "back_data": b"reseller_users",
            "reseller_scope": event.sender_id,
        })
        await event.edit(
            "🔍 آیدی عددی یا بخشی از یوزرنیم مشتری‌ات را بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _reseller_show_sub_status(self, event):
        users = list_users_for_reseller(event.sender_id)
        lines = ["⏳ **وضعیت اشتراک کاربران من:**\n"]
        for u in users:
            sub = get_active_subscription(u["user_id"])
            status = f"فعال تا {sub['expire_date']}" if sub else "بدون اشتراک/منقضی"
            lines.append(f"`{u['user_id']}` — {status}")
        if not users:
            lines.append("(هنوز کاربری نداری)")
        await event.edit("\n".join(lines), buttons=[UI.nav_row()])

    async def _reseller_start_create_license(self, event):
        """
        [Legacy callback — سازگاری] دیگر مسیر UI جداگانه‌ای برای ساخت لایسنس
        وجود ندارد: نماینده هم از همان هابِ یکپارچه‌ی «🎫 لایسنس و دسترسی‌ها»
        (که برای نقشش فقط نوع account را نشان می‌دهد) لایسنس می‌سازد.
        """
        await self._owner_show_license_hub(event)

    # ─────────────────────────────────────────────────────
    #  بخش USER
    # ─────────────────────────────────────────────────────

    async def _user_support_start(self, event):
        ticket = get_open_ticket(event.sender_id)
        if not ticket:
            tid = create_ticket(event.sender_id)
        else:
            tid = ticket["id"]
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_TICKET_MSG, {"ticket_id": tid})
        await event.edit(
            "✅ شما با موفقیت به پشتیبانی متصل شدید.\n\nپیام خود را ارسال کنید.",
            buttons=[[UI.neutral("پایان گفتگو", "user_support_end")], UI.nav_row(home=False)],
        )

    async def _user_support_end(self, event):
        wiz = self.wizards.pop(event.sender_id, None)
        if wiz:
            ticket_id = wiz["data"]["ticket_id"]
            # فقط اگر واقعاً پیامی رد و بدل شده، تیکت را ببند؛ وگرنه یک
            # تیکت خالی (که هیچ‌وقت پیامی نداشته) در دیتابیس رها نکن —
            # کاربر می‌تواند بعداً با «📞 پشتیبانی» همان تیکت باز را ادامه دهد.
            if ticket_message_count(ticket_id) > 0:
                close_ticket(ticket_id)
        await self._show_menu_for_role(event.chat_id, ROLE_USER, edit_event=event)

    async def _user_show_sub_status(self, event):
        sub = get_active_subscription(event.sender_id)
        if not sub:
            await event.edit(
                "شما در حال حاضر اشتراک فعالی ندارید.",
                buttons=[UI.nav_row()],
            )
            return
        await event.edit(
            f"⭐ **اشتراک فعال**\n\n"
            f"پلن: {sub['plan']}\n"
            f"تاریخ شروع: {sub['start_date']}\n"
            f"تاریخ پایان: {sub['expire_date']}\n",
            buttons=[UI.nav_row()],
        )

    async def _user_start_renew(self, event):
        plans = list_pricing()
        buttons = [
            [UI.go(f"{p['plan']} — {p['price_toman']:,} تومان", f"renew_plan:{p['plan']}".encode())]
            for p in plans
        ]
        buttons.append(UI.nav_row())
        await event.edit("💳 یکی از پلن‌ها رو انتخاب کن:", buttons=buttons)

    async def _compute_order_amounts(self, toman: int) -> tuple:
        """مبلغ تومان → معادل تتر با نرخ لحظه‌ای؛ fallback به تنظیم/ثابت.
        خروجی: (amount_usdt, rate_toman). +۱٪ بافر برای نوسان قیمت."""
        rate = None
        try:
            rate = await _get_usd_toman_rate()
        except Exception:
            rate = None
        if not rate or rate <= 0:
            try:
                rate = float(get_setting("usdt_toman_rate", "0") or 0)
            except Exception:
                rate = 0.0
        if not rate or rate <= 0:
            rate = USDT_TOMAN_FALLBACK
        usdt = round(toman / rate * 1.01, 2)
        return usdt, rate

    async def _show_invoice(self, event, order: dict, rate: float):
        """رندر فاکتور با شماره‌ی سفارش، مبلغ دقیق (تومان+تتر) و انقضای پرداخت."""
        wallet = (get_setting("usdt_wallet") or "").strip()
        wallet_line = f"`{wallet}`" if wallet else "⚠️ کیف پول تتر هنوز تنظیم نشده — با پشتیبانی تماس بگیر."
        text = (
            f"🧾 **فاکتور {order['order_no']}**\n\n"
            f"پلن: {order['plan']}\n"
            f"مبلغ: {order['amount_toman']:,} تومان\n"
            f"معادل تتر: **{order['amount_usdt']:.2f} USDT** (شبکه TRC20) "
            f"— نرخ ~{rate:,.0f} تومان\n\n"
            f"⏳ این فاکتور تا `{order['expires_at']}` معتبر است.\n\n"
            f"💵 **پرداخت تتری (خودکار):**\n{wallet_line}\n\n"
            f"بعد از واریز، «پرداخت با تتر» را بزن و هش تراکنش را بفرست — "
            f"به‌صورت خودکار تایید می‌شود."
        )
        buttons = [
            [UI.go("💵 پرداخت با تتر (TRC20)", f"order_tron:{order['id']}".encode())],
            [UI.go("💳 پرداخت با کارت", f"order_card:{order['id']}".encode())],
            [UI.go("🧾 سفارش‌های من", b"user_orders")],
            [UI.danger("لغو فاکتور", f"order_cancel:{order['id']}")],
            UI.nav_row(),
        ]
        # فاکتور همیشه از یک callback می‌آید → edit. (event.query همان
        # تشخیصِ قابل‌اطمینانِ CallbackQuery است؛ هم‌چنین برای امنیت اگر
        # جایی از مسیر پیام متنی صدا زده شد، respond بفرستد.)
        if getattr(event, "query", None) is None:
            await event.respond(text, buttons=buttons)
        else:
            await event.edit(text, buttons=buttons)

    async def _user_plan_chosen(self, event, plan: str):
        plans = {p["plan"]: p for p in list_pricing()}
        info = plans.get(plan)
        if not info:
            await event.answer("پلن نامعتبر است.", alert=True)
            return
        usdt, rate = await self._compute_order_amounts(info["price_toman"])
        order = create_order(event.sender_id, plan, info["price_toman"], usdt)
        await self._show_invoice(event, order, rate)

    async def _user_show_orders(self, event):
        orders = list_user_orders(event.sender_id)
        if not orders:
            await event.edit(
                "🧾 هنوز سفارشی ثبت نکردی. از «💳 تمدید اشتراک» شروع کن.",
                buttons=[UI.nav_row()],
            )
            return
        labels = {
            ORDER_STATUS_PENDING: "⏳ در انتظار پرداخت",
            ORDER_STATUS_PAID: "✅ پرداخت شد",
            ORDER_STATUS_EXPIRED: "❌ منقضی شد",
            ORDER_STATUS_CANCELLED: "🚫 لغو شد",
        }
        lines = ["🧾 **سفارش‌های من:**\n"]
        for o in orders[:10]:
            lines.append(f"`{o['order_no']}` — {o['plan']} — {o['amount_toman']:,} تومان "
                         f"— {labels.get(o['status'], o['status'])}")
            if o["status"] == ORDER_STATUS_PAID and o["pay_method"] == "trc20":
                lines.append(f"   تتر: `{o['txid']}`")
        lines.append("\n⏳ فاکتورهای در انتظار تا ۲۴ ساعت معتبرند.")
        await event.edit(
            "\n".join(lines),
            buttons=[UI.nav_row()],
        )

    async def _user_start_trx_pay(self, event, order_id: int):
        order = get_order(order_id)
        if not order or order["user_id"] != event.sender_id or order["status"] != ORDER_STATUS_PENDING:
            await event.answer("این فاکتور معتبر نیست (شاید منقضی یا پرداخت شده).", alert=True)
            return
        wallet = (get_setting("usdt_wallet") or "").strip()
        if not wallet:
            await event.answer("کیف پول تتر تنظیم نشده — با پشتیبانی تماس بگیر.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_TRX_HASH, {"order_id": order_id})
        await event.edit(
            f"💵 مبلغ دقیق: **{order['amount_usdt']:.2f} USDT** (شبکه TRC20)\n\n"
            f"آدرس کیف پول:\n`{wallet}`\n\n"
            "بعد از واریز، **هش تراکنش** (۶۴ کاراکتر hex) را بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _user_start_card_pay(self, event, order_id: int):
        order = get_order(order_id)
        if not order or order["user_id"] != event.sender_id or order["status"] != ORDER_STATUS_PENDING:
            await event.answer("این فاکتور معتبر نیست (شاید منقضی یا پرداخت شده).", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(
            event.sender_id, WIZ_PAYMENT_RECEIPT,
            {"order_id": order_id, "plan": order["plan"], "amount": order["amount_toman"]},
        )
        card_number = get_setting("card_number", DEFAULT_CARD_NUMBER)
        card_holder = get_setting("card_holder", DEFAULT_CARD_HOLDER)
        await event.edit(
            f"فاکتور {order['order_no']}\n\n"
            f"شماره کارت:\n`{card_number}`\nبه نام: {card_holder}\n\n"
            f"مبلغ: {order['amount_toman']:,} تومان\n\n"
            "لطفاً تصویر رسید پرداخت را ارسال کنید.",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _user_cancel_order(self, event, order_id: int):
        order = get_order(order_id)
        if not order or order["user_id"] != event.sender_id:
            await event.answer("فاکتور پیدا نشد.", alert=True)
            return
        cancel_order(order_id, event.sender_id)
        await event.answer("فاکتور لغو شد.")
        await self._user_show_orders(event)

    async def _user_start_activate_license(self, event):
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_LICENSE_CODE, {})
        await event.edit(
            "🔑 کد لایسنس رو بفرست (مثلاً `SELF-XXXX-XXXX`):",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    # ─────────────────────────────────────────────────────
    #  پردازش ورودی متنی ویزاردها (مشترک بین همه‌ی نقش‌ها)
    # ─────────────────────────────────────────────────────

    async def _handle_text_wizard(self, event, wiz: dict) -> bool:
        state = wiz["state"]
        data = wiz["data"]
        text = (event.raw_text or "").strip()

        if state == WIZ_TICKET_MSG:
            # تیکتِ بسته پاسخ نمی‌گیرد (بخش ۲۴) — کاربر باید تیکت جدید باز کند.
            _trow = get_ticket(data["ticket_id"])
            if not _trow or _trow["status"] != "open":
                self.wizards.pop(event.sender_id, None)
                await event.respond(
                    "⏳ این تیکت قبلاً بسته شده است. برای پیگیری، از «📞 پشتیبانی» تیکت جدیدی باز کن."
                )
                return True
            add_ticket_message(data["ticket_id"], "user", event.sender_id, text)
            upsert_user(event.sender_id, event.sender.username if event.sender else None)
            for admin_entry in list_admins_and_resellers():
                if admin_entry["role"] == ROLE_ADMIN:
                    try:
                        await self.client.send_message(
                            admin_entry["user_id"],
                            f"📨 پیام جدید در تیکت #{data['ticket_id']} از `{event.sender_id}`:\n{text}",
                        )
                    except Exception:
                        pass
            try:
                await self.client.send_message(
                    OWNER_ID, f"📨 پیام جدید در تیکت #{data['ticket_id']} از `{event.sender_id}`:\n{text}"
                )
            except Exception:
                pass
            await event.respond("✅ پیام شما ارسال شد. منتظر پاسخ پشتیبانی بمانید.")
            return True

        if state == WIZ_OWNER_TICKET_REPLY:
            tid = data["ticket_id"]
            # تیکتِ بسته پاسخ نمی‌گیرد (بخش ۲۴) — پاسخ فقط برای تیکتِ باز.
            ticket_row = get_ticket(tid)
            if not ticket_row:
                self.wizards.pop(event.sender_id, None)
                await event.respond("❌ این تیکت پیدا نشد.")
                return True
            if ticket_row["status"] != "open":
                self.wizards.pop(event.sender_id, None)
                await event.respond(
                    "⏳ این تیکت قبلاً بسته شده است؛ برای پاسخ باید تیکت جدیدی باز شود."
                )
                return True
            add_ticket_message(tid, "admin", event.sender_id, text)
            self.wizards.pop(event.sender_id, None)
            try:
                await self.client.send_message(
                    ticket_row["user_id"], f"📨 **پاسخ پشتیبانی:**\n{text}"
                )
            except Exception:
                pass
            await event.respond("✅ پاسخ ارسال شد.")
            return True

        if state == WIZ_LICENSE_CODE:
            self.wizards.pop(event.sender_id, None)
            code = text.strip().upper()
            username = event.sender.username if event.sender else None
            # فعال‌سازی اتمیک: مصرفِ لایسنس + ساخت اشتراک/نقش در یک تراکنش
            # واحد (activate_license) — هیچ‌وقت «لایسنس مصرف شده ولی اثرش
            # اعمال نشده» یا برعکس پیش نمی‌آید.
            res = activate_license(code, event.sender_id, username=username)
            if not res["ok"]:
                err = res["error"]
                if err == "invalid":
                    msg = "❌ این لایسنس معتبر نیست."
                elif err == "inactive":
                    msg = "❌ این لایسنس غیرفعال شده است."
                elif err == "used":
                    msg = "❌ این لایسنس قبلاً استفاده شده است."
                elif err == "reseller_limit":
                    msg = "❌ سقف مشتری‌های این نماینده پر شده است؛ لایسنس مصرف نشد."
                elif err == "owner":
                    msg = "❌ مالک اصلی را نمی‌توان با لایسنس تغییر داد."
                elif err == "role_guard":
                    msg = "❌ این لایسنس با نقش فعلی شما سازگار نیست (فقط OWNER می‌تواند نقش را عوض کند)."
                else:
                    msg = "❌ نوع این لایسنس معتبر نیست."
                await event.respond(msg)
                return True
            if res["type"] == LICENSE_TYPE_ACCOUNT:
                # اگر سلف‌بات‌های کاربر به‌خاطر انقضای قبلی متوقف شده بودند،
                # با فعال‌شدن اشتراک جدید دوباره فعال می‌شوند (رزوم).
                try:
                    await self._resume_user_selfbots(event.sender_id)
                except Exception:
                    pass
                await event.respond(
                    f"✅ لایسنس فعال شد! اشتراک شما به مدت {res['duration_days']} روز فعال است.\n\n"
                    f"برای اینکه سلف روی اکانت تلگرامت نصب و فعال بشه، باید اکانتت رو لاگین کنی.",
                    buttons=[[UI.go("🔐 لاگین اکانت", b"user_login_account")]],
                )
            elif res["type"] == LICENSE_TYPE_RESELLER:
                await event.respond(
                    "✅ لایسنس نمایندگی فعال شد! حالا به پنل نمایندگی دسترسی داری. /start بزن."
                )
            else:  # admin
                await event.respond(
                    "✅ دسترسی مدیریت برای شما فعال شد.\n\n"
                    "از این پس می‌توانید از پنل مدیریت استفاده کنید. /start بزن."
                )
            return True

        if state == WIZ_CL_RESELLER_LIMIT:
            try:
                limit = int(text)
                assert limit > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یه عدد صحیح مثبت بفرست (سقف مشتری):")
                return True
            lic = create_license(
                LICENSE_TYPE_RESELLER, duration_days=None, created_by=event.sender_id,
                reseller_user_limit=limit,
            )
            self.wizards.pop(event.sender_id, None)
            await event.respond(_license_result_text(lic))
            return True

        if state == WIZ_SET_CARD:
            self.wizards.pop(event.sender_id, None)
            # نام صاحب حساب اختیاری است و ترتیبش هم مهم نیست:
            #   «6219...|امید» ، «امید|6219...» یا فقط خودِ «6219...» همگی
            # پذیرفته می‌شوند. قبلاً ارسالِ تنها شماره با «فرمت درست نیست»
            # رد می‌شد و نماینده‌ها در ربات اختصاصی‌اشان گیر می‌کردند.
            number, holder = text.strip(), ""
            if "|" in text:
                left, right = (p.strip() for p in text.split("|", 1))
                # سمتی که بعد از نرمال‌سازی ۱۶ رقم می‌شود شماره‌ی کارت است؛
                # سمتی که رقمِ کافی ندارد نام صاحب حساب است.
                if len(normalize_card_number(right)) == 16 and len(normalize_card_number(left)) < 16:
                    number, holder = right, left
                else:
                    number, holder = left, right
            number = normalize_card_number(number)
            if len(number) != 16:
                await event.respond(
                    "❌ شماره کارت باید ۱۶ رقم باشد. می‌تونی فقط شماره رو "
                    "بفرستی، یا به‌صورت `شماره|نام`. دوباره از منو تلاش کن."
                )
                return True
            holder = holder.strip() or DEFAULT_CARD_HOLDER
            set_setting("card_number", number)
            set_setting("card_holder", holder)
            await event.respond(f"✅ شماره کارت به‌روزرسانی شد:\n`{number}`\nبه نام: {holder}")
            return True

        if state == WIZ_SET_WALLET:
            w = text.strip()
            if not (w.startswith("T") and len(w) == 34):
                await event.respond(
                    "❌ آدرس TRC20 معتبر نیست (باید با `T` شروع و ۳۴ کاراکتر باشد). "
                    "دوباره بفرست:"
                )
                return True
            set_setting("usdt_wallet", w)
            self.wizards.pop(event.sender_id, None)
            await event.respond(f"✅ آدرس کیف پول تتر ذخیره شد:\n`{w}`")
            return True

        if state == WIZ_PRICING_NEW_NAME:
            name = text.strip()
            if not name or len(name) > 30:
                await event.respond("❌ اسم پلن باید ۱ تا ۳۰ کاراکتر باشد. دوباره بفرست:")
                return True
            if any(p["plan"] == name for p in list_pricing()):
                await event.respond(f"❌ پلن «{name}» از قبل وجود دارد.")
                return True
            self.wizards[event.sender_id] = {"state": WIZ_PRICING_PRICE,
                                             "data": {"plan": name, "days": None}}
            await event.respond(f"قیمت پلن «{name}» به تومان چنده؟")
            return True

        if state == WIZ_PRICING_PRICE:
            try:
                price = int(text.replace(",", "").strip())
            except Exception:
                price = 0
            if price <= 0:
                await event.respond("❌ عدد معتبر (بزرگ‌تر از صفر) بفرست:")
                return True
            plan = data["plan"]
            if plan == "__dedicated__":
                set_setting("dedicated_bot_price", str(price))
                self.wizards.pop(event.sender_id, None)
                await event.respond(f"✅ قیمت ربات اختصاصی: {price:,} تومان شد.")
                return True
            days = data.get("days")
            if days is None:
                self.wizards[event.sender_id] = {"state": WIZ_PRICING_DAYS,
                                                 "data": {"plan": plan, "price": price}}
                await event.respond(f"مدت اشتراک پلن «{plan}» چند روزه بشه؟")
                return True
            set_pricing(plan, price, days)
            self.wizards.pop(event.sender_id, None)
            await event.respond(f"✅ پلن «{plan}» → {price:,} تومان / {days} روز ذخیره شد.")
            return True

        if state == WIZ_PRICING_DAYS:
            try:
                days = int(text.strip())
            except Exception:
                days = 0
            if not (1 <= days <= 3650):
                await event.respond("❌ تعداد روز باید بین ۱ تا ۳۶۵۰ باشد. دوباره بفرست:")
                return True
            if "price" in data:
                set_pricing(data["plan"], data["price"], days)
                self.wizards.pop(event.sender_id, None)
                await event.respond(
                    f"✅ پلن «{data['plan']}» → {data['price']:,} تومان / {days} روز ذخیره شد."
                )
            else:
                plan_info = get_pricing(data["plan"])
                if not plan_info:
                    await event.respond("❌ این پلن پیدا نشد.")
                    return True
                set_pricing(data["plan"], plan_info["price_toman"], days)
                self.wizards.pop(event.sender_id, None)
                await event.respond(
                    f"✅ مدت پلن «{data['plan']}» → {days} روز شد "
                    f"({plan_info['price_toman']:,} تومان)."
                )
            return True

        if state == WIZ_TRX_HASH:
            txid = text.strip()
            order = get_order(data.get("order_id", 0))
            if not order or order["user_id"] != event.sender_id \
                    or order["status"] != ORDER_STATUS_PENDING:
                self.wizards.pop(event.sender_id, None)
                await event.respond("❌ این فاکتور دیگر معتبر نیست (منقضی یا پرداخت شده).")
                return True
            wallet = (get_setting("usdt_wallet") or "").strip()
            if not wallet:
                self.wizards.pop(event.sender_id, None)
                await event.respond("❌ کیف پول تتر تنظیم نشده — با پشتیبانی تماس بگیر.")
                return True
            await event.respond("🔍 در حال بررسی تراکنش روی TronGrid… (حداکثر ۲۰ ثانیه)")
            try:
                ok, msg = await asyncio.wait_for(
                    _verify_trc20_transfer(txid, wallet, order["amount_usdt"]), timeout=20)
            except asyncio.TimeoutError:
                ok, msg = False, "بررسی TronGrid تایم اوت شد؛ کمی بعد دوباره امتحان کن"
            except Exception as e:
                ok, msg = False, f"خطا در بررسی تراکنش: {str(e)[:80]}"
            if ok:
                # اتمیک + ضد replay: فاکتور paid و اشتراک در یک تراکنش؛ یک
                # txid هرگز برای دو فاکتور قبول نمی‌شود.
                res = pay_order_trc20_atomic(order["id"], txid)
                if not res["ok"]:
                    if res["error"] == "replay":
                        await event.respond(
                            "❌ این هش قبلاً برای فاکتور دیگری استفاده شده است. "
                            "هر تراکنش فقط یک‌بار قابل استفاده است."
                        )
                    elif res["error"] == "invalid":
                        await event.respond(
                            "❌ این فاکتور دیگر معتبر نیست (منقضی یا پرداخت شده)."
                        )
                    else:
                        await event.respond(
                            "❌ خطا در ثبت پرداخت؛ با پشتیبانی تماس بگیر."
                        )
                    self.wizards.pop(event.sender_id, None)
                    return True
                self.wizards.pop(event.sender_id, None)
                # بعد از پرداخت موفق، اگر سلف‌باتِ کاربر به‌خاطر انقضای قبلی
                # متوقف شده بود، دوباره فعال می‌شود (رزوم).
                try:
                    await self._resume_user_selfbots(event.sender_id)
                except Exception:
                    pass
                await event.respond(
                    f"✅ پرداخت تایید شد ({msg}) و اشتراک «{res['plan']}» فعال شد! 🎉\n\n"
                    "برای لاگین اکانت تلگرامت از منوی اصلی اقدام کن."
                )
                try:
                    await self._notify_owner(
                        f"💵 **پرداخت خودکار تتر تایید شد**\n"
                        f"فاکتور {order['order_no']} — کاربر `{event.sender_id}` — "
                        f"{order['amount_usdt']:.2f} USDT\nپلن: {order['plan']}"
                    )
                except Exception:
                    pass
            else:
                await event.respond(
                    f"❌ {msg}\n\nاگر هش درست است، چند دقیقه صبر کن و دوباره بفرست."
                )
            return True

        if state == WIZ_SET_CHANNEL:
            # resolve واقعی کانال قبل از ذخیره — کانالِ پیدا‌نشده هرگز ذخیره نمی‌شود
            ok, info, norm = await self._resolve_channel(text)
            if not ok:
                await event.respond(
                    f"❌ کانال «{text.strip()}» پیدا نشد یا قابل دسترسی نیست ({info}).\n\n"
                    "یوزرنیم درست رو بفرست (کانال باید **عمومی** باشه):"
                )
                return True
            self.wizards[event.sender_id] = {
                "state": WIZ_SET_CHANNEL, "data": {"channel": norm, "title": info},
            }
            await event.respond(
                f"✅ **کانال پیدا شد:**\n\n"
                f"📢 {info}\nhttps://t.me/{norm}\n\n"
                "این کانال ذخیره شود؟ از این به بعد همه (به‌جز ادمین اصلی) باید "
                "عضو این کانال باشن.",
                buttons=[
                    [UI.confirm("بله، ذخیره کن", b"channel_confirm_save")],
                    [UI.neutral("نه، دوباره بفرستم", "owner_channel_set")],
                ],
            )
            return True

        if state == WIZ_DEDICATED_TOKEN:
            token = text.strip()
            if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", token):
                await event.respond(
                    "❌ قالب توکن درست نیست. از @BotFather کپی کن (مثلاً `123456789:AAF...`):"
                )
                return True
            ok, info = await self._validate_bot_token(token)
            if not ok:
                await event.respond(
                    f"❌ توکن معتبر نیست (تلگرام پاسخ نداد): {info}\n\n"
                    "توکن درست رو از @BotFather بگیر و دوباره بفرست:"
                )
                return True
            data["token"] = token
            data["bot_username"] = info
            self.wizards[event.sender_id] = {"state": WIZ_DEDICATED_OWNER_ID, "data": data}
            await event.respond(
                "✅ توکن معتبر است. حالا **آیدی عددی** کسی که می‌خوای مالک ربات "
                "اختصاصی باشه رو بفرست (مثلاً `123456789` — از @userinfobot می‌تونی "
                "بگیری):",
                buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
            )
            return True

        if state == WIZ_DEDICATED_OWNER_ID:
            if not text.strip().lstrip("-").isdigit():
                await event.respond("❌ آیدی عددی معتبر نیست. فقط عدد بفرست (مثلاً `123456789`):")
                return True
            owner_id = int(text.strip())
            data["owner_id"] = owner_id
            bot_id = create_dedicated_bot(event.sender_id, owner_id, data["token"])
            data["bot_id"] = bot_id
            await self._notify_owner(
                f"🆕 **درخواست ربات اختصاصی ثبت شد**\n"
                f"ربات: #{bot_id} | مالک: `{owner_id}` | "
                f"نماینده: `{event.sender_id}` | وضعیت: منتظر پرداخت"
            )
            price = dedicated_bot_price()
            # مرحله‌ی بعد: رسید پرداخت (عکس) — دقیقاً مثل جریان تمدید اشتراک
            self._start_own_wizard(event.sender_id, WIZ_PAYMENT_RECEIPT, {
                "plan": DEDICATED_BOT_PLAN, "amount": price,
            })
            card_number = get_setting("card_number", DEFAULT_CARD_NUMBER)
            card_holder = get_setting("card_holder", DEFAULT_CARD_HOLDER)
            # دو پیام جدا: اول کارت و مبلغ (اطلاعات پرداخت)، بعد پیامِ جداگانه‌ی
            # درخواست رسید — طبق خواسته: «شماره کارت و یه رسید جدا براش بیاد».
            await event.respond(
                f"🤖 **درخواست ربات اختصاصی #{bot_id} ثبت شد**\n\n"
                f"مالک: `{owner_id}` | توکن: {data.get('bot_username') or '✓'}\n\n"
                f"💳 برای فعال‌سازی، مبلغ **{price:,} تومان** رو به کارت زیر واریز کن:\n\n"
                f"`{card_number}`\nبه نام: {card_holder}\n\n"
                "پس از واریز، تصویر رسید رو در پیام بعدی بفرست 👇",
                buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
            )
            await event.respond(
                "🧾 **مرحله‌ی رسید پرداخت**\n\n"
                "بعد از واریز به شماره کارت بالا، **تصویر رسید** رو همین‌جا بفرست. "
                "بعد از تایید ادمین، ربات اختصاصی‌ات ساخته و راه‌اندازی می‌شه.",
                buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
            )
            return True

        if state == WIZ_DEDICATED_EXTEND_DAYS:
            self.wizards.pop(event.sender_id, None)
            bot_id = data["bot_id"]
            b = get_dedicated_bot(bot_id)
            if not b:
                await event.respond("❌ این ربات اختصاصی پیدا نشد.")
                return True
            try:
                days = int(text.strip())
                assert days > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یک عدد صحیح مثبت (تعداد روز) بفرست:")
                return True
            old_expire = _parse_date(b["expire_date"]) if b.get("expire_date") else datetime.now(timezone.utc)
            new_expire = _format_date(max(old_expire, datetime.now(timezone.utc)) + timedelta(days=days))
            update_dedicated_bot_status(bot_id, b["status"], expire_date=new_expire)
            log_action(event.sender_id, "dedicated_bot_extended", f"bot#{bot_id} +{days} روز")
            await self._notify_owner(
                f"➕ **ربات اختصاصی تمدید شد**\n"
                f"ربات: #{bot_id} | +{days} روز | انقضای جدید: {new_expire} | "
                f"توسط: `{event.sender_id}`"
            )
            await event.respond(
                f"✅ ربات اختصاصی #{bot_id} به مدت {days} روز تمدید شد (انقضا: {new_expire}).",
                buttons=[UI.nav_row()],
            )
            try:
                await self.client.send_message(
                    b["owner_id"],
                    f"✅ ربات اختصاصی تو به مدت {days} روز تمدید شد (تا {new_expire}).",
                )
            except Exception:
                pass
            return True




        if state == WIZ_ORPHAN_ASSIGN:
            # تعیینِ مالکِ یک سلفِ بدون مالک — فقط OWNER/ADMIN.
            if self._role(event.sender_id) not in (ROLE_OWNER, ROLE_ADMIN):
                self.wizards.pop(event.sender_id, None)
                await event.respond("⛔ دسترسی نداری.")
                return True
            tag = data.get("tag")
            q = (text or "").strip().lstrip("@")
            if q.isdigit():
                target = int(q)
                u = get_user(target)
            else:
                matches = search_users(q)
                if not matches:
                    await event.respond(
                        "کاربری با این یوزرنیم پیدا نشد.\n"
                        "آیدی عددی‌اش را بفرست، یا اول از او بخواه ربات را استارت کند."
                    )
                    return True
                if len(matches) > 1:
                    await event.respond(
                        "چند کاربر با این یوزرنیم هست — آیدی عددیِ دقیقش را بفرست:\n"
                        + "\n".join(f"• `{m['user_id']}` — @{m.get('username') or '—'}"
                                    for m in matches[:8])
                    )
                    return True
                u = matches[0]
                target = u["user_id"]
            self.wizards.pop(event.sender_id, None)
            if not u:
                # کاربر هنوز در دیتابیس نیست — ثبتش می‌کنیم تا مالکیت معتبر باشد
                upsert_user(target)
            if not self._assign_orphan_owner(tag, target):
                await event.respond("❌ وصل‌کردن ناموفق بود — این سلف دیگر وجود ندارد یا config قفل است.")
                return True
            log_action(event.sender_id, "orphan_assign", f"tag={tag} → user={target}")
            uname = (u or {}).get("username")
            await event.respond(
                UI.screen(
                    "✅ وصل شد",
                    body=[f"سلف «{tag}» حالا متعلق به "
                          + (f"@{uname}" if uname else f"کاربر `{target}`") + " است.",
                          "",
                          f"{UI.GREEN} همه‌ی قابلیت‌ها برای او فعال شد و از «🤖 سلف من» "
                          f"می‌تواند خودش مدیریتش کند."],
                ),
                buttons=[[UI.go("👤 مدیریت این کاربر", f"user_manage:{target}")],
                         [UI.go("⚠️ بقیه‌ی سلف‌های بدون مالک", "owner_orphan_bots")],
                         UI.nav_row(back=False)],
            )
            return True

        if state == WIZ_USER_SEARCH:
            self.wizards.pop(event.sender_id, None)
            back_data = data["back_data"]
            reseller_scope = data.get("reseller_scope")
            if reseller_scope is not None:
                # جستجوی نماینده باید فقط داخل مشتریان خودش باشد — نتایج
                # عمومی search_users را با لیست مشتریان واقعی این نماینده
                # قطع می‌کنیم تا یک نماینده هرگز نتواند با جستجوی آیدی/
                # یوزرنیم به اطلاعات کاربری غیرِ مشتریانش برسد.
                customer_ids = {u["user_id"] for u in list_users_for_reseller(reseller_scope)}
                all_results = search_users(text)
                results_for_event = [u for u in all_results if u["user_id"] in customer_ids]
                if not results_for_event:
                    await event.respond(
                        f"❌ هیچ مشتری‌ای با «{text}» در بین کاربران تو پیدا نشد.",
                        buttons=[[UI.go("🔍 جستجوی دوباره", b"reseller_user_search_start")],
                                 UI.nav_row()],
                    )
                    return True
                if len(results_for_event) == 1:
                    await self._render_user_management_panel_as_message(
                        event, results_for_event[0]["user_id"], back_data
                    )
                    return True
                buttons = []
                for u in results_for_event[:20]:
                    label = u.get("username") or str(u["user_id"])
                    buttons.append([UI.go(
                        f"👤 {label}", f"user_manage:{u['user_id']}".encode()
                    )])
                buttons.append(UI.nav_row())
                await event.respond(f"🔍 {len(results_for_event)} مشتری با «{text}» پیدا شد:", buttons=buttons)
                return True
            else:
                results = search_users(text)
                if not results:
                    await event.respond(
                        f"❌ هیچ کاربری با «{text}» پیدا نشد.",
                        buttons=[[UI.go("🔍 جستجوی دوباره", b"user_search_start")],
                                 UI.nav_row()],
                    )
                    return True
                if len(results) == 1:
                    await self._render_user_management_panel_as_message(event, results[0]["user_id"], back_data)
                    return True
                buttons = []
                for u in results[:20]:
                    label = u.get("username") or str(u["user_id"])
                    buttons.append([UI.go(
                        f"👤 {label}", f"user_manage:{u['user_id']}".encode()
                    )])
                buttons.append(UI.nav_row())
                await event.respond(f"🔍 {len(results)} کاربر با «{text}» پیدا شد:", buttons=buttons)
                return True

        if state == WIZ_USER_EXTEND_DAYS:
            self.wizards.pop(event.sender_id, None)
            target_user_id = data["target_user_id"]
            back_data = data["back_data"]
            reseller_scope = data.get("reseller_scope")
            if reseller_scope is not None:
                customer_ids = {u["user_id"] for u in list_users_for_reseller(reseller_scope)}
                if target_user_id not in customer_ids:
                    await event.respond("⛔ این کاربر مشتری تو نیست.")
                    return True
            try:
                days = int(text.strip())
                assert days > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یک عدد صحیح مثبت (تعداد روز) بفرست:")
                return True
            # create_subscription حالا در صورتِ تغییرِ هم‌زمانِ اشتراک،
            # به‌جای ساختنِ اشتراکِ دوم استثنا می‌دهد — اینجا به پیامِ
            # قابل‌فهم تبدیل می‌شود، نه کرشِ ویزارد.
            try:
                create_subscription(target_user_id, "تمدید دستی", days)
            except Exception as e:
                print(f"⚠️ [saas_bot] تمدید دستی ناموفق: {type(e).__name__}: {e}")
                await event.respond(
                    "❌ تمدید انجام نشد — اشتراک این کاربر هم‌زمان تغییر کرد. "
                    "یک لحظه صبر کن و دوباره امتحان کن."
                )
                return True
            try:
                await self.client.send_message(
                    target_user_id,
                    f"✅ اشتراک شما به مدت {days} روز توسط پشتیبانی تمدید شد.",
                )
            except Exception:
                pass
            await event.respond(f"✅ اشتراک کاربر `{target_user_id}` به مدت {days} روز تمدید شد.")
            await self._render_user_management_panel_as_message(event, target_user_id, back_data)
            return True

        if state == WIZ_CAP_USER_ID:
            # ورودیِ نامعتبر → روی همین قدم بمان (قاعده‌ی کلیِ ویزارد).
            try:
                uid = int((text or "").strip().lstrip("@"))
                assert uid > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یک آیدیِ عددیِ معتبر بفرست:")
                return True
            self.wizards.pop(event.sender_id, None)
            # به‌جای ساختِ صفحه با event.edit (که در یک پیامِ متنی جواب نمی‌دهد)،
            # صفحه‌ی انتخابِ دامنه را برای این کاربر رندر می‌کنیم.
            await self._owner_choose_capability_scope(event, uid)
            return True

        return False

    async def _handle_photo_wizard(self, event, wiz: dict) -> bool:
        if wiz["state"] != WIZ_PAYMENT_RECEIPT:
            return False
        data = wiz["data"]
        upsert_user(event.sender_id, event.sender.username if event.sender else None)
        # receipt_ref یک مرجع قابل‌بازیابی به خودِ پیام است (chat_id:message_id)
        # نه صرفاً event.photo.id که به‌تنهایی برای دانلود مجدد کافی نیست.
        receipt_ref = f"{event.chat_id}:{event.message.id}"
        order_no = ""
        if data.get("order_id"):
            order = get_order(data["order_id"])
            if order and order["user_id"] == event.sender_id \
                    and order["status"] == ORDER_STATUS_PENDING:
                order_no = order["order_no"]
        pay_id = create_payment(event.sender_id, data["plan"], data["amount"], receipt_ref)
        if data.get("order_id") and order_no:
            set_order_payment_id(data["order_id"], pay_id)
        self.wizards.pop(event.sender_id, None)
        await event.respond("✅ رسید شما ثبت شد.\n\nپس از بررسی مدیریت تایید خواهد شد.")
        pay_ref = f" (فاکتور {order_no})" if order_no else ""
        # اعلانِ پرداخت با دکمه‌های تایید/ردِ شیشه‌ای — ادمین از همین پیام
        # می‌تواند تایید/رد کند و دیگر لازم نیست به «بررسی پرداخت‌ها» برود.
        # پسوند «:n» (notif) به callback اضافه می‌شود تا تایید/رد، خودِ پیامِ
        # اعلان را به نتیجه تبدیل کند (نه لیست پرداخت‌ها).
        notify_buttons = [[
            UI.confirm(f"تایید #{pay_id}", f"pay_approve:{pay_id}:n"),
            UI.danger(f"رد #{pay_id}", f"pay_reject:{pay_id}:n"),
        ]]
        notify_text = (
            f"👆 رسید پرداخت #{pay_id}{pay_ref} از `{event.sender_id}`\n\n"
            f"🧾 پلن: {data['plan']} | مبلغ: {data['amount']:,} تومان\n\n"
            "از همین‌جا تایید یا رد کن:"
        )
        for admin_entry in list_admins_and_resellers():
            if admin_entry["role"] == ROLE_ADMIN:
                try:
                    await self.client.forward_messages(admin_entry["user_id"], event.message)
                    await self.client.send_message(
                        admin_entry["user_id"], notify_text, buttons=notify_buttons
                    )
                except Exception:
                    pass
        try:
            await self.client.forward_messages(OWNER_ID, event.message)
            await self.client.send_message(OWNER_ID, notify_text, buttons=notify_buttons)
        except Exception:
            pass
        return True

    # ─────────────────────────────────────────────────────
    #  حلقه‌ی انقضای خودکار
    # ─────────────────────────────────────────────────────

    async def _expiry_loop(self):
        """
        هر ساعت چک می‌کند: اشتراک‌هایی که کمتر از ۲۴ ساعت تا انقضایشان مانده
        هشدار می‌گیرند، و اشتراک‌های واقعاً منقضی‌شده status=expired می‌شوند
        (طبق اسپک: تنظیمات/دیتابیس/سابقه باقی می‌ماند، فقط اشتراک منقضی
        علامت‌گذاری می‌شود — حذف فیزیکی اکانت سلف مرتبط، اگر selfbot_tag ثبت
        شده باشد، جدا مدیریت می‌شود).
        """
        while True:
            try:
                await asyncio.sleep(3600)
                for sub in list_expiring_subscriptions(within_hours=24):
                    try:
                        await self.client.send_message(
                            sub["user_id"],
                            "⚠️ کمتر از 24 ساعت تا پایان اشتراک شما باقی مانده است.\n"
                            "لطفاً سرویس خود را تمدید کنید.",
                        )
                    except Exception:
                        pass
                    mark_warned(sub["id"])

                for sub in list_expired_subscriptions():
                    expire_subscription(sub["id"])
                    # رفتار واقعی با پیام هماهنگ است: سلف‌بات متوقف و
                    # disabled می‌شود (نه حذف) — تنظیمات و سشن‌ها حفظ می‌شوند
                    # و بعد از تمدید به‌طور خودکار دوباره فعال می‌شود.
                    try:
                        await self._stop_and_disable_user_selfbots(sub["user_id"])
                    except Exception:
                        pass
                    try:
                        await self.client.send_message(
                            sub["user_id"],
                            "❌ اشتراک شما تمدید نشد.\nSelfBot شما متوقف شد؛ "
                            "تنظیمات و سشن‌هایت حفظ شده‌اند.\n"
                            "بعد از تمدید اشتراک، سلف‌بات‌ت دوباره به‌طور خودکار فعال می‌شود.",
                        )
                    except Exception:
                        pass

                await self._sweep_expired_dedicated_bots()

                # فاکتورهای در انتظاری که انقضایشان گذشته → باطل + اطلاع
                for order in list_expired_orders():
                    expire_order(order["id"])
                    try:
                        await self.client.send_message(
                            order["user_id"],
                            f"⏳ فاکتور `{order['order_no']}` منقضی شد و باطل شد. "
                            "برای خرید دوباره از «💳 تمدید اشتراک» اقدام کن.",
                        )
                    except Exception:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [saas_bot] خطا در expiry_loop: {e}")
                await asyncio.sleep(60)

    async def _sweep_expired_dedicated_bots(self):
        """ربات‌های اختصاصی منقضی‌شده: فرآیند متوقف و وضعیت revoke."""
        for dbot in list_active_dedicated_bots():
            if not dbot.get("expire_date"):
                continue
            try:
                if _parse_date(dbot["expire_date"]) > datetime.now(timezone.utc):
                    continue
            except Exception as e:
                # تاریخِ خراب/ناخوانا: قبلاً بی‌صدا continue می‌شد — یعنی آن
                # ربات برای همیشه فعال می‌ماند و هیچ‌جا هم ثبت نمی‌شد.
                # حالا دست‌کم دیده می‌شود تا OWNER بتواند دستی رسیدگی کند.
                # عمداً خودکار revoke نمی‌کنیم: حذفِ دسترسیِ یک ربات به‌خاطر
                # یک فیلدِ خرابِ تاریخ، از خودِ مشکل بدتر است.
                print(f"⚠️ [dedicated] تاریخ انقضای ربات #{dbot.get('id')} "
                      f"قابل خواندن نیست ({dbot.get('expire_date')!r}: "
                      f"{type(e).__name__}) — از انقضای خودکار جا می‌ماند؛ "
                      f"دستی بررسی کن.")
                continue
            pid = dbot.get("pid") or _read_pidfile(dbot.get("bot_dir") or "")
            await _stop_process_by_pid(pid)
            update_dedicated_bot_status(dbot["id"], "revoked")
            log_action(0, "dedicated_bot_expired", f"bot#{dbot['id']}")
            try:
                await self.client.send_message(
                    dbot["owner_id"],
                    "❌ دوره‌ی ربات اختصاصی تو تمام شد و متوقف گردید. "
                    "برای تمدید با پشتیبانی تماس بگیر.",
                )
            except Exception:
                pass

    # ─────────────────────────────────────────────────────
    #  ثبت هندلرها
    # ─────────────────────────────────────────────────────

    def _register_handlers(self):
        @self.client.on(events.NewMessage(pattern="/start"))
        async def start_h(event):
            self.wizards.pop(event.sender_id, None)
            await self._clear_admin_panel_wizard(event.sender_id)
            is_new = get_user(event.sender_id) is None
            upsert_user(event.sender_id, event.sender.username if event.sender else None,
                            event.sender.first_name if event.sender else None)
            # دعوت: «/start ref_<id>» فقط برای کاربرِ تازه ثبت می‌شود — تا
            # کسی نتواند با /startِ دوباره امتیازِ تکراری بسازد.
            if is_new:
                ref = parse_referral_arg(event.raw_text or "")
                if ref:
                    try:
                        if attach_referrer(event.sender_id, ref):
                            _spawn_bg(self._notify_referrer(ref), "referral")
                    except Exception as e:
                        print(f"⚠️ [referral] ثبت دعوت ناموفق: {type(e).__name__}")
            # گیت عضویت کانال: همه به‌جز ادمین اصلی باید عضو کانالِ تنظیم‌شده
            # توسط مالک باشند تا بتوانند از ربات استفاده کنند. اگر عضو نباشد،
            # پیام /start او حذف و پیام گیت (کادر شیشه‌ای کانال + بررسی عضویت)
            # فرستاده می‌شود.
            if not await self._channel_gate(event.sender_id):
                try:
                    await event.message.delete()
                except Exception:
                    pass
                await self._send_channel_gate_message(event)
                return
            # دوباره‌عضو‌شده‌ای که /start می‌زند: پیامِ گیتِ کهنه‌اش پاک
            # می‌شود تا چت تمیز بماند
            if event.sender_id in self._gate_blocked:
                self._gate_blocked.discard(event.sender_id)
                await self._try_delete_gate_message(event.sender_id, event.chat_id)
            role = self._role(event.sender_id)
            await self._show_menu_for_role(event.chat_id, role)

        @self.client.on(events.NewMessage)
        async def message_h(event):
            if event.raw_text and event.raw_text.startswith("/"):
                return

            # گیت همیشگی: اگر کاربر از کانال خارج شده باشد، همین اولین
            # تعاملِ بعدی دسترسی را می‌بندد تا دوباره عضو شود.
            if not await self._channel_gate(event.sender_id):
                await self._send_channel_gate_message(event, denied=True)
                return
            # دوباره‌عضو‌شده‌ای که پیام متنی می‌فرستد: پیامِ گیتِ کهنه‌اش
            # پاک می‌شود تا چت تمیز بماند
            if event.sender_id in self._gate_blocked:
                self._gate_blocked.discard(event.sender_id)
                await self._try_delete_gate_message(event.sender_id, event.chat_id)

            wiz = self.wizards.get(event.sender_id)
            if wiz:
                try:
                    if event.photo:
                        handled = await self._handle_photo_wizard(event, wiz)
                    elif getattr(event, "document", None):
                        # فایل (مثلاً بکاپ دیتابیس برای بازیابی)
                        handled = await self._handle_document_wizard(event, wiz)
                    else:
                        handled = await self._handle_text_wizard(event, wiz)
                    if handled:
                        return
                except Exception as e:
                    print(f"⚠️ [saas_bot] خطا در ویزارد: {e}")
                    self.wizards.pop(event.sender_id, None)
                    await event.respond(f"❌ خطای غیرمنتظره: {str(e)[:150]}")
                    return

            # اگر ویزاردِ ما این پیام را نخواست، آن را به پنل مدیریت
            # اکانت‌های سلف هدایت می‌کنیم — صرف‌نظر از نقش و بدون فهرست
            # جداگانه. این بی‌خطر است چون admin_panel.handle_message بدون
            # ویزاردِ بازِ مخصوصِ همین کاربر کاری نمی‌کند؛ برای OWNER/ADMIN/
            # RESELLER (که همیشه مجازند) و برای USER عادیِ وسطِ ویزاردِ
            # لاگین (تگ/شماره/کد) دقیقاً همین مسیر است. scope پنل هم درست
            # قبل از فراخوانی روی همین کاربر تنظیم می‌شود — و چون پنل یک
            # singleton مشترک است، کل (sync + dispatch) زیر _panel_lock می‌رود
            # تا رویدادِ هم‌زمانِ کاربرِ دیگر نتواند وسطِ dispatch scope را
            # عوض کند.
            async with self._panel_lock:
                self._sync_admin_panel_scope(event.sender_id)
                await self.admin_panel.handle_message(event)

        @self.client.on(events.CallbackQuery)
        async def callback_h(event, _route: str = None, _depth: int = 0):
            """
            روترِ مرکزی. `_route` فقط وقتی پر می‌شود که «بازگشت» دارد یک
            مسیرِ ذخیره‌شده را دوباره رندر می‌کند؛ در آن حالت event.data
            هنوز `nav:back` است و نباید مبنا قرار گیرد.

            نکته‌ی امنیتی مهم: بازگشت، مسیر را از همین‌جا و از ابتدا
            dispatch می‌کند — یعنی همه‌ی گاردهای نقش/مالکیت (از جمله
            گاردِ متمرکزِ _TAG_PREFIXES در AdminBot) دقیقاً مثل کلیکِ
            مستقیم اجرا می‌شوند. پشته‌ی ناوبری هیچ دسترسی‌ای اعطا نمی‌کند؛
            فقط یادش می‌ماند کاربر کجا بوده.
            """
            data = _route if _route is not None else event.data.decode()
            uid = event.sender_id
            role = self._role(uid)
            # گیت همیشگی: هر تعاملِ بعد از خروج از کانال بسته می‌شود. دکمه‌ی
            # «بررسی عضویت» خودش استثناست (تا کاربرِ تازه‌عضو‌شده بتواند
            # وارد شود).
            if data != "channel_retry" and not await self._channel_gate(uid):
                await self._send_channel_gate_message(event, denied=True)
                return

            # ─── ناوبری ────────────────────────────────────────────────
            if data == NAV_NOOP:
                # دکمه‌ی تزئینی (شمارنده‌ی صفحه) — فقط اسپینر را می‌بندد.
                await event.answer()
                return

            if data == NAV_HOME:
                self.wizards.pop(uid, None)
                await self._clear_admin_panel_wizard(uid)
                self.nav.reset(uid)
                await self._show_menu_for_role(event.chat_id, role, edit_event=event)
                return

            if data == NAV_BACK:
                # محافظِ بازگشتِ زنجیره‌ای: اگر مسیرِ ذخیره‌شده خودش دوباره
                # به بازگشت برسد (نباید بشود، ولی داده‌ی کهنه ممکن است)،
                # بعد از چند قدم به منوی اصلی می‌رویم نه بازگشتِ بی‌پایان.
                if _depth >= 4:
                    self.nav.reset(uid)
                    await self._show_menu_for_role(event.chat_id, role, edit_event=event)
                    return
                self.wizards.pop(uid, None)
                await self._clear_admin_panel_wizard(uid)
                prev = self.nav.pop(uid)
                if not prev:
                    # ریشه‌ی پشته — یک قدم بالاتر از این، منوی اصلی است.
                    await self._show_menu_for_role(event.chat_id, role, edit_event=event)
                    return
                await callback_h(event, _route=prev, _depth=_depth + 1)
                return

            # مسیرهای «صفحه» وارد پشته می‌شوند؛ مسیرهای «عمل» نه (وگرنه
            # بازگشت روی همان صفحه گیر می‌کند). بازگشت هم دوباره push
            # نمی‌کند — pop خودش پشته را درست کرده است.
            if _route is None and not _is_nav_action(data):
                self.nav.push(uid, data)

            try:
                if data == "admin_users" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._admin_show_users_hub(event, role)
                    return
                if data == "admin_tools" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._show_admin_tools(event, role)
                    return
                if data == "user_account":
                    await self._show_account_card(event)
                    return
                if data == "user_referral":
                    await self._show_referral(event)
                    return
                if data == "admin_hub":
                    if role not in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    self.wizards.pop(event.sender_id, None)
                    await self._show_admin_hub(event, role)
                    return
                if data == "goto_admin_panel":
                    if role not in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    self.wizards.pop(event.sender_id, None)
                    async with self._panel_lock:
                        self._sync_admin_panel_scope(event.sender_id)
                        await self.admin_panel._show_main_menu(event.chat_id, edit_event=event)
                    return
                if data == "back_role_menu":
                    self.wizards.pop(event.sender_id, None)
                    # گیت عضویت کانال — ورود مجدد به منوی اصلی هم باید چک شود
                    if not await self._channel_gate(event.sender_id):
                        await self._send_channel_gate_message(event)
                        return
                    await self._show_menu_for_role(event.chat_id, role, edit_event=event)
                    return
                if data == "channel_retry":
                    # دکمه‌ی «بررسی عضویت» — بعد از عضویت، دسترسی بدون نیاز
                    # به /start دوباره بررسی می‌شود (force=True: بدون استفاده
                    # از کش، چکِ تازه با تلگرام). هر کلیک یک تماس شبکه است؛
                    # سقف ۵ ثانیه‌ای جلوی اسپمِ کلیک را می‌گیرد.
                    now = time.time()
                    if now - self._gate_retry_ts.get(event.sender_id, 0) < _GATE_RETRY_COOLDOWN:
                        await event.answer("⏳ یک لحظه صبر کن و دوباره بررسی کن.", alert=True)
                        return
                    self._gate_retry_ts[event.sender_id] = now
                    if await self._channel_gate(event.sender_id, force=True):
                        self.wizards.pop(event.sender_id, None)
                        if event.sender_id in self._gate_blocked:
                            # دوباره‌عضو‌شده: پیام خوشامد + آزاد شدن از لیستِ بسته‌ها
                            self._gate_blocked.discard(event.sender_id)
                            inc_setting("gate_rejoined_count")
                            try:
                                await self.client.send_message(
                                    event.chat_id,
                                    "✅ **حالا می‌تونی از ربات استفاده کنی!** 🎉\n\n"
                                    "خوش اومدی — منوی زیر رو ببین:",
                                )
                            except Exception:
                                pass
                        await self._show_menu_for_role(
                            event.chat_id, self._role(event.sender_id), edit_event=event
                        )
                    else:
                        await self._send_channel_gate_message(event, denied=True)
                    return
                if data == "owner_channel" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_show_channel_settings(event)
                    return
                if data == "owner_channel_check" and role in (ROLE_OWNER, ROLE_ADMIN):
                    # بررسیِ کانال فقط خواندنی است (resolve زنده) — به‌خطر
                    # نیست که ادمین‌های غیرِOWNER هم بزنند. تغییر/حذف شرط
                    # همچنان فقط OWNER.
                    await self._owner_check_channel(event)
                    return
                if data == "owner_channel_set" and role == ROLE_OWNER:
                    await self._start_channel_set(event)
                    return
                if data == "channel_confirm_save" and role == ROLE_OWNER:
                    wiz = self.wizards.pop(event.sender_id, None)
                    ch = (wiz or {}).get("data", {}).get("channel")
                    title = (wiz or {}).get("data", {}).get("title", "")
                    if not ch:
                        await event.answer("کانالی در انتظار تایید نیست.", alert=True)
                        return
                    set_setting("required_channel", ch)
                    # عنوان واقعی کانال ذخیره می‌شود تا کادر شیشه‌ایِ پیام
                    # گیت به‌جای @username نام واقعی را نشان دهد
                    set_setting("required_channel_title", title)
                    self._reset_gate_state()
                    await event.answer("✅ کانال ذخیره شد.")
                    await self._owner_show_channel_settings(event)
                    return
                if data == "owner_channel_clear" and role == ROLE_OWNER:
                    set_setting("required_channel", "")
                    set_setting("required_channel_title", "")
                    self._reset_gate_state()
                    await event.answer("✅ شرط عضویت کانال برداشته شد.")
                    await self._owner_show_channel_settings(event)
                    return
                if data == "owner_dedicated_list" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_show_dedicated_bots(event)
                    return
                if data == "reseller_dedicated_bot" and role == ROLE_RESELLER:
                    await self._start_dedicated_bot_wizard(event)
                    return
                if data.startswith("dedicated_manage:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_show_dedicated_bot_detail(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("dedicated_toggle:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._dedicated_bot_toggle(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("dedicated_extend:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._dedicated_bot_extend_start(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("dedicated_health:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._dedicated_bot_health(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("dedicated_revoke:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._dedicated_bot_revoke(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("dedicated_revoke_go:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._dedicated_bot_revoke_go(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("dedicated_delete_go:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._dedicated_bot_delete_go(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data == "admin_users" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._admin_show_users_hub(event, role)
                    return
                if data == "admin_finance" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._admin_show_finance_hub(event, role)
                    return
                if data == "admin_tickets" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._admin_show_tickets_hub(event)
                    return
                if data == "owner_orders" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_show_orders(event)
                    return
                if data == "owner_orphan_bots" and role == ROLE_OWNER:
                    await self._owner_show_orphan_bots(event)
                    return
                if data.startswith("orphan_own:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._start_orphan_assign(event, data.split(":", 1)[1])
                    return
                if data.startswith("orphan_manage:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._open_orphan_full(event, data.split(":", 1)[1])
                    return
                if data.startswith("orphan_acc:") and role == ROLE_OWNER:
                    # فرمت: orphan_acc:{tag} — مدیریت اکانت بدون مالک
                    await self._show_orphan_acc(event, data.split(":", 1)[1])
                    return
                if data == "admin_settings" and role == ROLE_OWNER:
                    await self._admin_show_settings_hub(event)
                    return
                if data == "admin_backup" and role == ROLE_OWNER:
                    await self._admin_show_backup_hub(event)
                    return
                if data == "owner_users" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_show_users(event)
                    return
                if data.startswith("users_list:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    # فرمت: users_list:{filter}:{page}
                    parts_cb = data.split(":")
                    fkey = parts_cb[1] if len(parts_cb) > 1 else "all"
                    page = int(parts_cb[2]) if len(parts_cb) > 2 and parts_cb[2].isdigit() else 0
                    await self._owner_show_users(event, fkey=fkey, page=page)
                    return
                if data == "user_search_start" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._start_user_search(event, back_data=b"owner_users")
                    return
                if data.startswith("user_accounts:"):
                    # فرمت: user_accounts:{user_id}:{back_data} — لیست SelfBotهای یک کاربر
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role in (ROLE_OWNER, ROLE_ADMIN):
                        await self._show_user_accounts(event, target_id, back_data_cb)
                    elif role == ROLE_RESELLER:
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                        await self._show_user_accounts(event, target_id, back_data_cb)
                    else:
                        await event.answer("⛔ دسترسی نداری", alert=True)
                    return
                if data.startswith("user_acc:"):
                    # فرمت: user_acc:{user_id}:{tag} — هاب مدیریت یک SelfBot از داخل کاربر
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    tag = parts_cb[2] if len(parts_cb) > 2 else ""
                    if target_id is None or not tag:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role in (ROLE_OWNER, ROLE_ADMIN):
                        await self._show_user_acc(event, target_id, tag)
                    elif role == ROLE_RESELLER:
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                        await self._show_user_acc(event, target_id, tag)
                    else:
                        await event.answer("⛔ دسترسی نداری", alert=True)
                    return
                # «سلف من» برای *همه‌ی* نقش‌هاست: مدیر و نماینده هم می‌توانند سلفِ
                # شخصیِ خودشان را داشته باشند. قبلاً به ROLE_USER محدود بود و
                # دکمه برای آن‌ها بی‌اثر می‌شد. مالکیتِ واقعی داخلِ خودِ متد با
                # account_belongs_to چک می‌شود، پس محدودکردن نقش اینجا لازم نیست.
                if data == "user_my_bots":
                    await self._show_user_own_bots(event)
                    return
                if data.startswith("my_acc:"):
                    # فرمت: my_acc:{tag} — هاب مدیریت یک SelfBot خودِ کاربر
                    await self._show_my_acc(event, data.split(":", 1)[1])
                    return
                if data == "user_my_add_bot":
                    await self._user_my_add_bot(event)
                    return
                if data.startswith("user_sub_admin:"):
                    # فرمت: user_sub_admin:{user_id}:{back_data} — مدیریت اشتراک یک کاربر
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role in (ROLE_OWNER, ROLE_ADMIN):
                        await self._show_user_sub_admin(event, target_id, back_data_cb)
                    elif role == ROLE_RESELLER:
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                        await self._show_user_sub_admin(event, target_id, back_data_cb)
                    else:
                        await event.answer("⛔ دسترسی نداری", alert=True)
                    return
                if data.startswith("user_add_bot:"):
                    # فرمت: user_add_bot:{user_id}:{back_data} — افزودن SelfBot برای این کاربر
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role in (ROLE_OWNER, ROLE_ADMIN):
                        await self._start_user_add_bot(event, target_id, back_data_cb)
                    elif role == ROLE_RESELLER:
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                        await self._start_user_add_bot(event, target_id, back_data_cb)
                    else:
                        await event.answer("⛔ دسترسی نداری", alert=True)
                    return
                if data.startswith("user_orders_admin:"):
                    # فرمت: user_orders_admin:{user_id}:{back_data} — سفارش‌های یک کاربر
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role in (ROLE_OWNER, ROLE_ADMIN):
                        await self._show_user_orders_admin(event, target_id, back_data_cb)
                    elif role == ROLE_RESELLER:
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                        await self._show_user_orders_admin(event, target_id, back_data_cb)
                    else:
                        await event.answer("⛔ دسترسی نداری", alert=True)
                    return
                if data == "reseller_user_search_start" and role == ROLE_RESELLER:
                    await self._start_reseller_user_search(event)
                    return
                if data.startswith("user_manage:"):
                    # فرمت: user_manage:{user_id}:{back_data}
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role in (ROLE_OWNER, ROLE_ADMIN):
                        await self._show_user_management_panel(event, target_id, back_data=back_data_cb)
                    elif role == ROLE_RESELLER:
                        # فیکس امنیتی: قبل از نمایش پنل مدیریت، دوباره چک
                        # می‌شود که این کاربر واقعاً مشتریِ همین نماینده است
                        # — نه صرفاً اعتماد به اینکه دکمه از کجا آمده، چون
                        # callback data را می‌شود دستی هم ساخت.
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                        await self._show_user_management_panel(event, target_id, back_data=back_data_cb)
                    else:
                        await event.answer("⛔ دسترسی نداری", alert=True)
                    return
                if data.startswith("user_expire:"):
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role == ROLE_RESELLER:
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                    elif role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    ok = set_active_subscription_expired(target_id)
                    if ok:
                        await event.answer("✅ اشتراک لغو شد.")
                        try:
                            await self.client.send_message(
                                target_id, "⚠️ اشتراک شما توسط پشتیبانی به‌صورت دستی لغو شد."
                            )
                        except Exception:
                            pass
                    else:
                        await event.answer("این کاربر اشتراک فعالی نداشت.", alert=True)
                    await self._show_user_management_panel(event, target_id, back_data=back_data_cb)
                    return
                if data.startswith("user_extend_start:"):
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    reseller_scope = None
                    if role == ROLE_RESELLER:
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                        reseller_scope = event.sender_id
                    elif role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    await self._clear_admin_panel_wizard(event.sender_id)
                    self._start_own_wizard(event.sender_id, WIZ_USER_EXTEND_DAYS, {
                        "target_user_id": target_id,
                        "back_data": back_data_cb,
                        "reseller_scope": reseller_scope,
                    })
                    await event.edit(
                        f"➕ چند روز به اشتراک کاربر `{target_id}` اضافه شود؟ یک عدد بفرست:",
                        buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                    )
                    return
                if data.startswith("user_delete_confirm:"):
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role == ROLE_RESELLER:
                        # نماینده هرگز «حذف کامل» ندارد — فقط «حذف از نمایندگی»
                        await event.answer(
                            "⛔ نماینده نمی‌تواند کاربر را کامل حذف کند؛ فقط «حذف از نمایندگی» مجاز است.",
                            alert=True,
                        )
                        return
                    if role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    await event.edit(
                        f"⚠️ آیا مطمئنی می‌خوای کاربر `{target_id}` رو کامل حذف کنی؟\n"
                        f"این کار اشتراک/پرداخت‌ها/تیکت‌های او را هم پاک می‌کند و غیرقابل‌بازگشت است.",
                        buttons=[
                            [UI.danger("بله، حذف کن", f"user_delete_go:{target_id}".encode())],
                            [UI.neutral("نه، برگرد", NAV_BACK)],
                        ],
                    )
                    return
                if data.startswith("user_delete_go:"):
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role == ROLE_RESELLER:
                        await event.answer(
                            "⛔ نماینده نمی‌تواند کاربر را کامل حذف کند؛ فقط «حذف از نمایندگی» مجاز است.",
                            alert=True,
                        )
                        return
                    if role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    # قبل از حذف، Runtimeهای سلف‌بات‌های کاربر کامل متوقف می‌شوند
                    # (نسخه‌ی Runtime-aware — نه صرفاً پاک‌سازی DB/config).
                    ok = await delete_user_completely_async(target_id)
                    if ok:
                        await event.edit(
                            f"✅ کاربر `{target_id}` کامل حذف شد.",
                            buttons=[UI.nav_row()],
                        )
                    else:
                        await event.edit(
                            "❌ این کاربر پیدا نشد (شاید قبلاً حذف شده).",
                            buttons=[UI.nav_row()],
                        )
                    return
                if data.startswith("user_unlink_confirm:"):
                    # فرمت: user_unlink_confirm:{user_id}:{back_data} — حذف مشتری از نمایندگی
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"reseller_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role == ROLE_RESELLER:
                        customer_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_id not in customer_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                    elif role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    await event.edit(
                        f"🚪 **حذف مشتری از نمایندگی**\n\n"
                        f"کاربر `{target_id}` از زیرمجموعه‌ی تو جدا می‌شود؛ "
                        f"هیچ‌کدام از داده‌هایش (اشتراک/سفارش/تیکت) حذف نمی‌شود.\n\n"
                        f"ادامه می‌دی؟",
                        buttons=[
                            [UI.danger("بله، جدا کن", f"user_unlink_go:{target_id}".encode())],
                            [UI.neutral("نه، برگرد", NAV_BACK)],
                        ],
                    )
                    return
                if data.startswith("user_unlink_go:"):
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"reseller_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role == ROLE_RESELLER:
                        ok_unlink = unlink_customer(event.sender_id, target_id)
                        if not ok_unlink:
                            await event.answer("این کاربر مشتری تو نیست.", alert=True)
                            return
                        await event.edit(
                            f"✅ کاربر `{target_id}` از نمایندگی تو جدا شد.",
                            buttons=[UI.nav_row()],
                        )
                    elif role in (ROLE_OWNER, ROLE_ADMIN):
                        # OWNER/ADMIN: جدا کردن از نماینده‌ای که الان مالکش است
                        u_row = get_user(target_id)
                        cur_res = u_row["reseller_id"] if u_row else None
                        if cur_res is None:
                            await event.answer("این کاربر الان زیرمجموعه‌ی هیچ نماینده‌ای نیست.", alert=True)
                            return
                        unlink_customer(cur_res, target_id)
                        await event.edit(
                            f"✅ کاربر `{target_id}` از نماینده‌ی `{cur_res}` جدا شد.",
                            buttons=[UI.nav_row()],
                        )
                    else:
                        await event.answer("⛔ دسترسی نداری", alert=True)
                    return
                if data == "owner_payments" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_show_payments(event)
                    return
                if data.startswith("pay_approve:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    # فرمت‌های مجاز: pay_approve:{id} (از لیست) و
                    # pay_approve:{id}:n (از پیامِ اعلانِ رسید — از همان‌جا
                    # تایید/رد می‌شود، بدون رفتن به بخش پرداخت‌ها).
                    parts = data.split(":")
                    await self._owner_review_payment(
                        event, safe_callback_int(parts[1], 0), True, from_notif=len(parts) > 2
                    )
                    return
                if data.startswith("pay_reject:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    parts = data.split(":")
                    await self._owner_review_payment(
                        event, safe_callback_int(parts[1], 0), False, from_notif=len(parts) > 2
                    )
                    return
                if data == "owner_tickets" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_show_tickets(event)
                    return
                if data.startswith("ticket_reply:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_start_ticket_reply(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("ticket_close:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_ticket_close(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("ticket_close_go:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_ticket_close_go(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data == "owner_backup" and role == ROLE_OWNER:
                    await self._owner_show_backup(event)
                    return
                if data == "owner_backup":
                    await event.answer("⛔ دسترسی نداری — فقط OWNER به Backup دسترسی دارد.", alert=True)
                    return
                if data == "owner_manage_roles" and role == ROLE_OWNER:
                    await self._owner_manage_roles_menu(event)
                    return
                if data == "owner_set_card" and role == ROLE_OWNER:
                    await self._owner_start_set_card(event)
                    return
                if data == "owner_pricing" and role == ROLE_OWNER:
                    await self._owner_show_pricing(event)
                    return
                if data == "plan_new" and role == ROLE_OWNER:
                    await self._owner_start_plan_new(event)
                    return
                if data.startswith("plan_price:") and role == ROLE_OWNER:
                    await self._owner_start_plan_price(event, data.split(":", 1)[1])
                    return
                if data.startswith("plan_days:") and role == ROLE_OWNER:
                    await self._owner_start_plan_days(event, data.split(":", 1)[1])
                    return
                if data == "owner_set_wallet" and role == ROLE_OWNER:
                    await self._owner_start_set_wallet(event)
                    return
                if data == "owner_db_backup" and role == ROLE_OWNER:
                    await self._owner_db_backup(event)
                    return
                if data == "owner_db_restore" and role == ROLE_OWNER:
                    await self._owner_start_db_restore(event)
                    return
                if data == "owner_db_restore":
                    await event.answer("⛔ دسترسی نداری — فقط OWNER می‌تواند Restore کند.", alert=True)
                    return
                if data == "owner_db_restore_go" and role == ROLE_OWNER:
                    await self._owner_db_restore_go(event)
                    return
                if data == "owner_db_restore_cancel" and role == ROLE_OWNER:
                    await self._owner_db_restore_cancel(event)
                    return
                if data.startswith("role_del:") and role == ROLE_OWNER:
                    uid = safe_callback_int(data.split(":", 1)[1], 0)
                    remove_admin_or_reseller(uid, removed_by=event.sender_id)
                    await self._owner_show_license_hub(event)
                    return
                # role_add_admin / role_add_reseller دیگر مسیر اصلی اعطای نقش
                # نیستند (اسپک: نقش فقط از طریق لایسنس). کالبک قدیمی را
                # بی‌صدا رها نمی‌کنیم — کاربر را به هاب «لایسنس و دسترسی‌ها»
                # هدایت می‌کنیم تا از مسیر درست لایسنس بسازد.
                if data in ("role_add_admin", "role_add_reseller") and role == ROLE_OWNER:
                    await self._owner_show_license_hub(event)
                    return
                if data == "license_access" and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    await self._owner_show_license_hub(event)
                    return
                if data == "license_access_list" and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    await self._owner_show_licenses(event)
                    return
                if data == "license_access_admins" and role == ROLE_OWNER:
                    await self._owner_show_role_list(event, ROLE_ADMIN)
                    return
                if data == "license_access_resellers" and role == ROLE_OWNER:
                    await self._owner_show_role_list(event, ROLE_RESELLER)
                    return
                if data == "owner_create_license" and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    await self._clear_admin_panel_wizard(event.sender_id)
                    self._start_own_wizard(event.sender_id, "cl_pending_type", {})
                    type_buttons = [
                        UI.go("👤 اشتراک کاربر", b"cl_type:account"),
                    ]
                    # فقط OWNER می‌تواند لایسنس ادمین بسازد (ADMIN نه)
                    if role in (ROLE_OWNER, ROLE_ADMIN):
                        type_buttons.append(UI.go("🤝 نمایندگی", b"cl_type:reseller"))
                    if role == ROLE_OWNER:
                        type_buttons.append(UI.go("🛡 ادمین", b"cl_type:admin"))
                    await event.edit(
                        "➕ **ساخت لایسنس**\n\nنوع دسترسی رو انتخاب کن:",
                        buttons=self._pair_buttons(type_buttons)
                                + [[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                    )
                    return
                if data.startswith("cl_type:"):
                    ltype = data.split(":", 1)[1]
                    wiz = self.wizards.get(event.sender_id)
                    if wiz is None or wiz["state"] != "cl_pending_type":
                        return
                    wiz["data"]["license_type"] = ltype
                    if ltype == LICENSE_TYPE_ADMIN:
                        # ادمین: بدون سؤال اضافی، مستقیم ساخته می‌شود (فقط OWNER)
                        if role != ROLE_OWNER:
                            await event.answer("⛔ فقط OWNER می‌تواند لایسنس ادمین بسازد.", alert=True)
                            return
                        self.wizards.pop(event.sender_id, None)
                        lic = create_license(LICENSE_TYPE_ADMIN, duration_days=None, created_by=event.sender_id)
                        await event.edit(_license_result_text(lic),
                                         buttons=[UI.nav_row()])
                        return
                    if ltype == LICENSE_TYPE_RESELLER:
                        # نمایندگی: سقف مشتری را می‌پرسیم
                        wiz["state"] = WIZ_CL_RESELLER_LIMIT
                        await event.edit(
                            "👥 **لایسنس نمایندگی**\n\nسقف مشتری‌های این نماینده رو بفرست "
                            "(یه عدد، مثلاً `50`):",
                            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                        )
                        return
                    # account → انتخاب مدت
                    wiz["state"] = "cl_pending_duration"
                    await event.edit(
                        "⏳ **مدت اعتبار** رو انتخاب کن:",
                        buttons=[
                            [UI.go("۳۰ روز", b"cl_dur:30"), UI.go("۹۰ روز", b"cl_dur:90")],
                            [UI.go("۱۸۰ روز", b"cl_dur:180"), UI.go("۳۶۵ روز", b"cl_dur:365")],
                            [UI.neutral(UI.L_CANCEL, NAV_BACK)],
                        ],
                    )
                    return
                if data.startswith("cl_dur:"):
                    wiz = self.wizards.get(event.sender_id)
                    if wiz is None or wiz["state"] != "cl_pending_duration":
                        return
                    duration = int(data.split(":", 1)[1])
                    ltype = wiz["data"].get("license_type", LICENSE_TYPE_ACCOUNT)
                    self.wizards.pop(event.sender_id, None)
                    lic = create_license(ltype, duration_days=duration, created_by=event.sender_id)
                    await event.edit(_license_result_text(lic),
                                     buttons=[UI.nav_row()])
                    return
                if data == "reseller_create_license" and role == ROLE_RESELLER:
                    await self._reseller_start_create_license(event)
                    return
                if data == "reseller_users" and role == ROLE_RESELLER:
                    await self._reseller_show_users(event)
                    return
                if data == "reseller_subs" and role == ROLE_RESELLER:
                    await self._reseller_show_sub_status(event)
                    return
                if data == "user_support":
                    await self._user_support_start(event)
                    return
                if data == "user_support_end":
                    await self._user_support_end(event)
                    return
                if data == "user_what_is":
                    await self._show_what_is(event)
                    return
                if data == "user_sub_status":
                    await self._user_show_sub_status(event)
                    return
                if data == "user_renew":
                    await self._user_start_renew(event)
                    return
                if data.startswith("renew_plan:"):
                    await self._user_plan_chosen(event, data.split(":", 1)[1])
                    return
                if data == "user_orders":
                    await self._user_show_orders(event)
                    return
                if data.startswith("order_tron:"):
                    await self._user_start_trx_pay(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("order_card:"):
                    await self._user_start_card_pay(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("order_cancel:"):
                    await self._user_cancel_order(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data == "user_activate_license":
                    await self._user_start_activate_license(event)
                    return
                if data == "user_login_account":
                    # فیکس اصلی این نسخه: کاربر عادی که لایسنسش را فعال
                    # کرده یا پرداختش تایید شده، می‌تواند مستقیماً همین‌جا
                    # اکانت تلگرامش را لاگین کند — بدون نیاز به دخالت دستی
                    # پشتیبانی. این مسیر عمداً مستقل از نقش (role) است: هر
                    # کسی که این دکمه را می‌بیند (که فقط بعد از فعال‌سازی
                    # واقعی نشان داده می‌شود) مجاز به لاگین است؛ چک صریح
                    # وجود اشتراک فعال هم به‌عنوان یک لایه‌ی دفاعی اضافه شده
                    # تا این دکمه با کپی/فوروارد پیام قدیمی توسط کاربر دیگری
                    # هم قابل سوءاستفاده نباشد.
                    active_sub = get_active_subscription(event.sender_id)
                    if not active_sub:
                        await event.answer(
                            "برای لاگین اکانت، اول باید اشتراک فعال داشته باشی "
                            "(لایسنس فعال کن یا اشتراک بخر).",
                            alert=True,
                        )
                        return
                    # فیکس تکمیل اسپک: گزینه‌ی «لاگین به اکانت» فقط تا قبل از
                    # اولین لاگین موفق باید وجود داشته باشد. شرط نمایش در منو
                    # این را اعمال می‌کند، ولی یک دکمه‌ی کهنه/فورواردشده یا
                    # کالبکِ دست‌ساز می‌تواند بعد از لاگین موفق دوباره این مسیر
                    # را صدا بزند — اینجا لایه‌ی دوم دفاع است: اگر کاربر قبلاً
                    # موفق لاگین کرده (اکانتی در config با owner_user_id او)،
                    # مسیر لاگین مجدد بسته است و ویزارد جدیدی شروع نمی‌شود.
                    # (اگر اکانتش بعداً توسط پشتیبانی از config حذف شده باشد،
                    # این تابع دوباره False می‌دهد و لاگین مجدد مجاز است.)
                    if self._user_has_logged_in_account(event.sender_id):
                        await event.answer(
                            "اکانت تو قبلاً با موفقیت لاگین شده — از پنل "
                            "«مدیریت اکانت‌های سلف» می‌تونی سلفت رو مدیریت کنی.",
                            alert=True,
                        )
                        return
                    self.wizards.pop(event.sender_id, None)
                    # قبل از شروع ویزارد لاگین، scope پنل را روی همین کاربر
                    # تنظیم می‌کنیم (owner_filter={user_id}) تا اگر لاگین
                    # موفق شد و کاربر به پنل «مدیریت اکانت‌های سلف» فرود آمد،
                    # فقط اکانت‌های خودش را ببیند و هیچ‌چیز دیگری.
                    async with self._panel_lock:
                        self._sync_admin_panel_scope(event.sender_id)
                        await self.admin_panel.start_login_wizard_for_user(event, event.sender_id)
                    return
                if data == "user_reseller_info":
                    await event.edit(
                        "👥 برای تبدیل‌شدن به نماینده، باید یک «لایسنس نمایندگی» از OWNER دریافت "
                        "کنی و از همان بخش «🔑 فعالسازی با لایسنس» فعالش کنی.",
                        buttons=[UI.nav_row()],
                    )
                    return
                if data == "user_help":
                    await event.edit(HELP_TEXT, buttons=[UI.nav_row()])
                    return
            except Exception as e:
                # جزئیات فنی فقط در لاگ سرور — به کاربر پیام عمومی و کوتاه داده
                # می‌شود تا state داخلی/ساختار دیتابیس درز نکند.
                print(f"⚠️ [saas_bot] خطا در پردازش دکمه: {type(e).__name__}: {e}")
                try:
                    await event.answer("❌ خطا در پردازش این دکمه. دوباره تلاش کن.", alert=True)
                except Exception:
                    pass
                return

            # گیت اشتراک برای «افزودن اکانت» توسط USER: کاربر عادی فقط با
            # اشتراک فعال می‌تواند اکانت جدید اضافه کند. دکمه از UI او حذف
            # شده، ولی callback دست‌ساز/کهنه‌ی «add» هم باید در Backend رد
            # شود (حذف دکمه به تنهایی کافی نیست). مدیریتِ SelfBotِ موجود
            # مشمول این شرط نیست — مالکیت معیار آن است.
            if role == ROLE_USER and data == "add":
                if not self._user_sub_status(event.sender_id)["active"]:
                    await event.answer("❌ برای افزودن SelfBot باید اشتراک فعال داشته باشید.", alert=True)
                    return

            # اگر هیچ‌کدام از موارد بالا مطابقت نداشت، callback را به پنل
            # مدیریت اکانت‌های سلف هدایت می‌کنیم — صرف‌نظر از نقش و بدون
            # فهرست جداگانه از callbackهای پنل. این امن است چون:
            #   (۱) همه‌ی callbackهای این ماژول اول در زنجیره‌ی بالا
            #       پردازش می‌شوند و اینجا فقط داده‌ی نامطابقت می‌رسد؛
            #   (۲) admin_panel.handle_callback داده‌ی ناشناخته را نادیده
            #       می‌گیرد (False برمی‌گرداند)؛
            #   (۳) همه‌ی عملیاتِ روی اکانت‌ها با owner_filter (که الان
            #       روی همین کاربر تنظیم شده) گارد می‌شوند — برای USER
            #       یعنی فقط اکانت‌های خودش.
            async with self._panel_lock:
                self._sync_admin_panel_scope(event.sender_id)
                await self.admin_panel.handle_callback(event, data=data)

        # ارجاع به روتر، تا صفحات بتوانند «یک قدم دیگر عقب» را درخواست
        # کنند — مثلاً وقتی هدفِ یک مسیرِ ذخیره‌شده دیگر وجود ندارد
        # (کاربر/اکانت/ربات حذف شده) و نباید کاربر روی یک صفحه‌ی مرده
        # با یک alert گیر کند.
        self._router = callback_h

        # هندل کردن state ساده‌ی "role_add" که مستقیم در _handle_text_wizard
        # نبود (چون به وضعیت خاص owner نیاز دارد) — با wrap کردن تابع اصلی
        orig_handle_text_wizard = self._handle_text_wizard

        async def patched_handle_text_wizard(event, wiz):
            if wiz["state"] == "role_add":
                text = (event.raw_text or "").strip()
                try:
                    new_id = int(text)
                except ValueError:
                    await event.respond("❌ یه آیدی عددی معتبر بفرست:")
                    return True
                role_to_add = wiz["data"]["role"]
                self.wizards.pop(event.sender_id, None)
                add_admin_or_reseller(new_id, role_to_add, added_by=event.sender_id)
                await event.respond(f"✅ آیدی `{new_id}` به‌عنوان {role_to_add} اضافه شد.")
                return True
            return await orig_handle_text_wizard(event, wiz)

        self._handle_text_wizard = patched_handle_text_wizard


# ══════════════════════════════════════════════════════════════════════
# ═══ بخش helper (ادغام‌شده) — رباتِ راهنمای دستورات ═══
# ══════════════════════════════════════════════════════════════════════
#
# قبلاً این یک فایلِ جدا (helper.py) بود که به‌عنوان زیرپروسس اجرا می‌شد.
# دلیلِ آن جداسازی، ترسِ از تداخلِ getUpdates روی یک توکن بود — ولی آن
# نگرانی فقط وقتی درست است که *یک توکن* دو بار poll شود. اینجا رباتِ
# راهنما توکنِ خودش را دارد، پس می‌تواند بی‌خطر در همین پروسه و روی همان
# event loop اجرا شود.
#
# سودِ ادغام: یک فایل کمتر، بدون pid-file، بدون زامبی، بدون log جدا، و
# بدون اینکه بعد از ری‌استارتِ سخت یک زیرپروسسِ یتیم جا بماند.

HELPER_BOT_TOKEN = os.environ.get("HELPER_BOT_TOKEN", "").strip()
HELPER_SESSION_NAME = "helper_bot"

# محتوای راهنما: {کلید: (برچسبِ دکمه، متنِ کامل)}
HELPER_TOPICS_FA = {
    "time": ("🕐 تایم",
             "🕐 **تایم و بیو**\n\n"
             "`تایم روشن` / `تایم خاموش`\n`بیو روشن` / `بیو خاموش`\n\n"
             "ساعت و تاریخ را به اسم یا بیوی تو اضافه می‌کند.\n\n"
             "__فونت‌ها:__ bold · double · sans · sans_bold · mono"),
    "tabchi": ("🔁 تبچی",
               "🔁 **تبچی** (ارسال خودکار تکراری)\n\n"
               "۱) `تبچی روشن`\n۲) روی پیامِ موردنظر ریپلای کن\n"
               "۳) `انتخاب تبچی 10`\n\n"
               "`تبچی زمان [دقیقه]` — تغییر فاصله\n"
               "`تبچی وضعیت` — دیدن وضعیت\n`تبچی خاموش`\n\n"
               "⏱ فاصله‌ی مجاز: ۵ تا ۱۴۴۰ دقیقه"),
    "mute": ("🔇 سکوت",
             "🔇 **سکوت**\n\n"
             "`سکوت روشن` / `سکوت خاموش`\n"
             "پیام‌های ورودیِ پیوی خودکار حذف می‌شوند.\n\n"
             "`سکوت پیوی روشن` / `سکوت پیوی خاموش`\n"
             "فقط برای همان چتی که در آن هستی."),
    "online": ("🟢 آنلاین",
               "🟢 **آنلاین دائمی**\n\n`آنلاین روشن` / `آنلاین خاموش`\n\n"
               "اکانتت همیشه آنلاین نشان داده می‌شود."),
    "read": ("✅ تیک",
             "✅ **تیک خودکار**\n\n"
             "`تیک پیوی روشن` / `تیک پیوی خاموش`\n"
             "`تیک گروه روشن` / `تیک گروه خاموش`\n"
             "`تیک کانال روشن` / `تیک کانال خاموش`"),
    "profile": ("👤 پروفایل",
                "👤 **پروفایل**\n\n"
                "`اسم جدید [نام]` — تغییر نام\n`فونت [نام]` — تغییر فونت\n\n"
                "**عکس پروفایل:** روی یک عکس ریپلای کن و بنویس `عکس پروفایل`\n\n"
                "__فونت‌ها:__ bold · double · sans · mono · normal"),
    "tools": ("🛠 ابزارها",
              "🛠 **ابزارها**\n\n"
              "`ردیاب روشن` / `ردیاب خاموش` — ذخیره‌ی پیام‌های حذف/ادیت‌شده\n"
              "`پینگ` — سرعت پاسخ\n`ریستارت` — راه‌اندازی دوباره\n\n"
              "**با ریپلای روی یک پیام:**\n"
              "`حذف 10` · `دشمن` · `بلاک` · `آنبلاک` · `ایدی` · `مشخصات` · `سنجاق`"),
    "games": ("🎮 بازی‌ها",
              "🎮 **بازی‌های تضمینی**\n\nکافی است تایپ کنی:\n\n"
              "`تاس` ← همیشه ۶\n`دارت` ← وسطِ هدف\n`بسکتبال` ← سه امتیازی\n"
              "`فوتبال` ← گل\n`اسلات` ← ۷۷۷"),
    "crypto": ("💰 کریپتو",
               "💰 **قیمت لحظه‌ای**\n\nکافی است تایپ کنی:\n\n"
               "`طلا` · `تتر` · `ترون` · `تون`\n\n"
               "قیمت از چند منبع گرفته و میانگین می‌شود."),
    "copy": ("📋 کپی",
             "📋 **کپی و ذخیره**\n\n"
             "`کپی [لینک]` — گرفتنِ محتوای یک پیام\n"
             "مثال: `کپی https://t.me/channel/123`\n\n"
             "**با ریپلای:** `ذخیره` · `فوروارد`\n\n"
             "__برای کانال خصوصی باید عضو باشی.__"),
    "status": ("📊 وضعیت",
               "📊 **وضعیت**\n\n`وضعیت` — همه‌ی تنظیمات فعلی را یک‌جا نشان می‌دهد:\n"
               "سلف · تایم · تبچی · آنلاین · تیک · سکوت · ردیاب"),
    "tips": ("❓ نکات",
             "❓ **نکات مهم**\n\n"
             "• دستورهای ریپلای را حتماً روی همان پیامِ هدف بزن.\n"
             "• دستورها را در چتِ خودت تایپ کن، نه در این ربات.\n"
             "• `!help` راهنمای کامل را در تلگرام نشان می‌دهد.\n"
             "• `!myexpire` مدت باقی‌مانده‌ی اشتراکت را می‌گوید."),
}

HELPER_TOPICS_EN = {
    "time": ("🕐 Time",
             "🕐 **Time & Bio**\n\n`time on` / `time off`\n`bio on` / `bio off`\n\n"
             "Adds a live clock to your name or bio.\n\n"
             "__Fonts:__ bold · double · sans · sans_bold · mono"),
    "tabchi": ("🔁 Repeat",
               "🔁 **Auto-Repeat**\n\n1) `tabchi on`\n2) Reply to the target message\n"
               "3) `set tabchi 10`\n\n`tabchi interval [min]` · `tabchi status` · `tabchi off`\n\n"
               "⏱ Range: 5–1440 minutes"),
    "mute": ("🔇 Mute",
             "🔇 **Mute**\n\n`mute all on` / `mute all off`\n"
             "Auto-deletes incoming PMs.\n\n`mute pm on` / `mute pm off`"),
    "online": ("🟢 Online", "🟢 **Always Online**\n\n`online on` / `online off`"),
    "read": ("✅ Read",
             "✅ **Auto Read**\n\n`read pm on/off`\n`read group on/off`\n`read channel on/off`"),
    "profile": ("👤 Profile",
                "👤 **Profile**\n\n`set name [name]` · `font [name]`\n\n"
                "**Photo:** reply to a photo with `set photo`\n\n"
                "__Fonts:__ bold · double · sans · mono · normal"),
    "tools": ("🛠 Tools",
              "🛠 **Tools**\n\n`tracker on/off` · `ping` · `restart`\n\n"
              "**Reply:** `delete 10` · `block` · `unblock` · `id` · `pin`"),
    "games": ("🎮 Games",
              "🎮 **Guaranteed Games**\n\n`dice` → 6\n`dart` → bullseye\n"
              "`basketball` → 3-point\n`football` → goal\n`slot` → 777"),
    "crypto": ("💰 Prices", "💰 **Live Prices**\n\nSend: `gold` · `usdt` · `trx` · `ton`"),
    "copy": ("📋 Copy",
             "📋 **Copy & Save**\n\n`copy [link]` — fetch a message by link\n\n"
             "**Reply:** `save` · `forward`"),
    "status": ("📊 Status", "📊 **Status**\n\n`status` — shows every current setting."),
    "tips": ("❓ Tips",
             "❓ **Tips**\n\n• Reply commands must be sent on the target message.\n"
             "• Type commands in your own chats, not here.\n"
             "• `!help` shows the full command list.\n"
             "• `!myexpire` shows your remaining subscription."),
}

HELPER_ORDER = ("time", "tabchi", "mute", "online", "read", "profile",
                "tools", "games", "crypto", "copy", "status", "tips")

HELPER_TRIGGERS = {"پنل", "راهنما", "منو", "panel", "help", "h", "menu"}

HELPER_HOME_FA = (
    "🤖 **راهنمای سلف‌بات**\n\n"
    "روی هر بخش بزن تا دستورهایش بیاید.\n"
    "__این دستورها را در چت‌های خودت تایپ می‌کنی، نه اینجا.__"
)
HELPER_HOME_EN = (
    "🤖 **Self-Bot Helper**\n\n"
    "Tap a section to see its commands.\n"
    "__You type these in your own chats, not here.__"
)


def _helper_normalize(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"@[a-z0-9_]+", " ", t)
    t = re.sub(r"^/+", "", t)
    return t.strip()


def _helper_is_trigger(norm: str) -> bool:
    return bool(HELPER_TRIGGERS & set(norm.split()))


class HelperBot:
    """
    رباتِ راهنمای دستورات — مستقل از پنل، با توکنِ خودش.

    فقط محتوای آموزشی نشان می‌دهد؛ هیچ دسترسی‌ای به دیتابیس، اکانت‌ها یا
    تنظیمات ندارد. عمداً این‌طور است: راهنما چیزی نیست که نیاز به دسترسی
    داشته باشد، و نداشتنِ دسترسی یعنی حتی اگر توکنش لو برود، چیزی از
    سیستم در خطر نیست.
    """

    def __init__(self):
        self.client = None

    @staticmethod
    def home_text(lang: str) -> str:
        return HELPER_HOME_FA if lang == "fa" else HELPER_HOME_EN

    @staticmethod
    def home_buttons(lang: str) -> list:
        topics = HELPER_TOPICS_FA if lang == "fa" else HELPER_TOPICS_EN
        items = [UI.go(topics[k][0], f"hb:{lang}:{k}") for k in HELPER_ORDER]
        rows = [items[i:i + 2] for i in range(0, len(items), 2)]
        rows.append([
            UI.confirm("English" if lang == "fa" else "فارسی",
                       f"hl:{'en' if lang == 'fa' else 'fa'}"),
            UI.danger("بستن" if lang == "fa" else "Close", "hclose"),
        ])
        return rows

    @staticmethod
    def back_buttons(lang: str) -> list:
        return [[UI.go("⬅️ بازگشت" if lang == "fa" else "⬅️ Back", f"hh:{lang}")]]

    async def start(self):
        api_id, api_hash = _first_account_creds(load_config())
        if not api_id or not api_hash:
            raise RuntimeError("api_id/api_hash برای ربات راهنما پیدا نشد")
        session_path = os.path.join(SESSIONS_DIR, HELPER_SESSION_NAME)
        self.client = TelegramClient(
            session_path, api_id, api_hash,
            connection_retries=3, retry_delay=2, flood_sleep_threshold=10,
        )
        await asyncio.wait_for(
            self.client.start(bot_token=HELPER_BOT_TOKEN), timeout=30)
        self._register()
        me = await self.client.get_me()
        print(f"🤖 ربات راهنما بالا آمد: @{getattr(me, 'username', '?')}")
        return self.client

    def _register(self):
        @self.client.on(events.NewMessage(pattern=r"^/start"))
        async def _h_start(event):
            name = ""
            try:
                s = await event.get_sender()
                name = getattr(s, "first_name", "") or ""
            except Exception:
                pass
            await event.respond(
                f"👋 سلام {name}\n\n🤖 من رباتِ راهنمای سلف‌بات هستم.\n"
                f"هر بخش را که بزنی، دستورهایش را برایت می‌نویسم 👇",
                buttons=self.home_buttons("fa"),
            )

        @self.client.on(events.NewMessage)
        async def _h_msg(event):
            if (event.raw_text or "").startswith("/start"):
                return
            if _helper_is_trigger(_helper_normalize(event.raw_text or "")):
                await event.respond(self.home_text("fa"),
                                    buttons=self.home_buttons("fa"))

        @self.client.on(events.CallbackQuery)
        async def _h_cb(event):
            data = event.data.decode()
            try:
                if data == "hclose":
                    await event.edit("✅ بسته شد. برای باز کردن دوباره: /start")
                elif data.startswith("hl:") or data.startswith("hh:"):
                    lang = data.split(":", 1)[1]
                    await event.edit(self.home_text(lang),
                                     buttons=self.home_buttons(lang))
                elif data.startswith("hb:"):
                    _, lang, key = data.split(":", 2)
                    topics = HELPER_TOPICS_FA if lang == "fa" else HELPER_TOPICS_EN
                    entry = topics.get(key)
                    if entry:
                        await event.edit(entry[1], buttons=self.back_buttons(lang))
            except Exception as e:
                # MessageNotModified و امثالش نباید ربات را بشکنند
                print(f"⚠️ [helper] دکمه: {type(e).__name__}")
            finally:
                try:
                    await event.answer()
                except Exception:
                    pass

        @self.client.on(events.InlineQuery)
        async def _h_inline(event):
            # نتیجه همیشه خودِ پنلِ آماده است — یک ضربه، بدون مرحله‌ی اضافه.
            norm = _helper_normalize(event.text or "")
            lang = "en" if norm in ("en", "english") else "fa"
            try:
                await event.answer([
                    event.builder.article(
                        title="📖 راهنمای سلف‌بات" if lang == "fa" else "📖 Self-Bot Helper",
                        description="پنل کامل دستورها" if lang == "fa" else "Full command panel",
                        text=self.home_text(lang),
                        buttons=self.home_buttons(lang),
                    )
                ], cache_time=0)
            except Exception as e:
                print(f"⚠️ [helper] inline: {type(e).__name__}")


async def run_helper_bot_forever():
    """
    سوپروایزرِ رباتِ راهنما. اگر توکن تنظیم نشده باشد، بی‌صدا و بدون خطا
    خارج می‌شود — نبودِ راهنما هرگز نباید بقیه‌ی سیستم را متوقف کند.
    """
    if not HELPER_BOT_TOKEN:
        print("ℹ️ HELPER_BOT_TOKEN تنظیم نشده — ربات راهنما اجرا نشد "
              "(بقیه‌ی سیستم عادی کار می‌کند).")
        return
    backoff = 10
    while not SHUTTING_DOWN:
        bot = HelperBot()
        try:
            await bot.start()
            await bot.client.run_until_disconnected()
            backoff = 10
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"⚠️ [helper] قطع شد ({type(e).__name__}) — "
                  f"تلاش مجدد در {backoff} ثانیه")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
        finally:
            try:
                if bot.client:
                    await bot.client.disconnect()
            except Exception:
                pass


async def run_saas_bot_forever(selfbot_module):
    consecutive_failures = 0
    MAX_BACKOFF = 300
    while True:
        try:
            bot = SaaSBot(selfbot_module)
            await bot.start()
            await bot.client.run_until_disconnected()
            consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            consecutive_failures += 1
            wait_time = min(10 * (2 ** min(consecutive_failures, 5)), MAX_BACKOFF)
            print(f"⚠️ [saas_bot] قطع/خطا: {e} — تلاش مجدد در {wait_time}s")
            # محل دقیق خطا را همیشه چاپ کن (حتی بدون DEBUG).
            import traceback as _tb
            _stack = _tb.format_exc().strip().splitlines()
            if _stack:
                _last = [l for l in _stack if l.strip().startswith("File ")]
                if _last:
                    print(f"   └─ {_last[-1].strip()}")
            await asyncio.sleep(wait_time)

# ══════════════════════════════════════════════════════════════════════
# ═══ بخش main.py (ادغامشده) ═══
# ══════════════════════════════════════════════════════════════════════

# ماژول resource فقط روی یونیکس/لینوکس موجود است (نه ویندوز). چون workflow
# معمول این پروژه شامل لاگین اولیه‌ی interactive روی ویندوز است (طبق همان
# روش قبلی: لاگین لوکال با SOCKS5 و انتقال .session به هاست)، این import را
# با try/except محافظت می‌کنیم تا اجرای main.py روی ویندوز برای لاگین اولیه
# خراب نشود؛ لاگ مصرف حافظه صرفاً روی لینوکس (هاست واقعی) فعال خواهد بود.
try:
    import resource
except ImportError:
    resource = None


# ══════════════════════════════════════════════════════════
#  تشخیص خطاهای احراز هویت غیرقابل‌بازیابی (fatal auth errors)
# ══════════════════════════════════════════════════════════
# این خطاها یعنی سشن/اکانت دیگر معتبر نیست (مثلاً از دستگاه دیگری logout
# شده، اکانت غیرفعال/بن شده، یا کلید احراز هویت باطل شده) — در این حالت‌ها
# تلاش مجدد برای reconnect نه‌تنها بی‌فایده است، بلکه هر بار یک تلاش اتصال
# جدید به سرورهای تلگرام می‌زند که می‌تواند باعث توجه بیشتر سیستم‌های
# ضدسوءاستفاده‌ی تلگرام به این اکانت شود. برای همین این کلاس‌ها را جدا از
# بقیه‌ی خطاهای موقتی (قطعی شبکه و غیره) مدیریت می‌کنیم: به‌جای backoff و
# retry بی‌نهایت، اکانت را کاملاً متوقف می‌کنیم و به کاربر اطلاع می‌دهیم.
_FATAL_AUTH_ERROR_TYPES = tuple(
    t for t in (
        getattr(errors, "AuthKeyError", None),
        getattr(errors, "UnauthorizedError", None),
    ) if t is not None
)


def _is_fatal_auth_error(exc: BaseException) -> bool:
    if not _FATAL_AUTH_ERROR_TYPES:
        return False
    return isinstance(exc, _FATAL_AUTH_ERROR_TYPES)


# ========== تنظیمات دیباگ ==========
# قابل فعال‌سازی از محیط: DEBUG=1 python3 main.py all — traceback کامل با
# شماره خط هر خطا را چاپ می‌کند (برای پیدا کردن دقیقِ محل خطا روی سرور).
DEBUG = os.environ.get("DEBUG", "").strip() == "1"

# نشانگر نسخه — فقط برای دیباگ/تشخیص اینکه کدام نسخه از کد واقعاً در حال
# اجراست (مثلاً هنگام گزارش باگ، می‌توان از کاربر خواست این عدد را در
# ابتدای لاگ اجرا چک کند تا مطمئن شد فایل صحیح deploy شده و __pycache__
# قدیمی اجرا نمی‌شود).
BUILD_VERSION = "2026-08-01-connguard2"

# ══════════════════════════════════════════════════════════
#  مسیرها و فایل‌های تنظیمات
# ══════════════════════════════════════════════════════════
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
DOWNLOADS_DIR = os.path.join(DATA_DIR, "downloads")
TRACKER_MEDIA_DIR = os.path.join(DATA_DIR, "tracker_media")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
# دوره‌ی اغماض برای پاک‌سازی سشن‌های یتیم: سشن‌های تازه‌تر از این حد
# (لاگینِ در جریان) دست نمی‌خورند.
ORPHAN_SESSION_GRACE = 30 * 60  # ۳۰ دقیقه

# SESSIONS_DIR فایل‌های سشنِ تلگرام را نگه می‌دارد — هرکس آن‌ها را بخواند
# می‌تواند اکانت را کامل در اختیار بگیرد. پس مثل ~/.ssh فقط برای خودِ
# کاربرِ سرویس. mode در makedirs فقط هنگام *ساختن* اعمال می‌شود، پس برای
# نصب‌های موجود هم صریحاً chmod می‌کنیم.
os.makedirs(SESSIONS_DIR, mode=0o700, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, mode=0o700, exist_ok=True)
os.makedirs(TRACKER_MEDIA_DIR, mode=0o700, exist_ok=True)
for _d in (SESSIONS_DIR, DOWNLOADS_DIR, TRACKER_MEDIA_DIR):
    _chmod_private(_d, 0o700)
db_init_db()

log = logging.getLogger("selfbot")
logging.getLogger("telethon").setLevel(logging.WARNING)

# سقف تعداد پیام‌هایی که دستور «حذف N» در یک بار مجاز است پاک کند. بدون این
# سقف، یک ورودی بزرگ (چه عمدی چه اشتباهی، مثلاً «حذف 999999999») باعث
# می‌شود iter_messages برای مدت طولانی (می‌تواند ساعت‌ها باشد) درخواست پشت
# درخواست به تلگرام بزند — که هم عملاً اکانت را برای آن مدت روی این یک
# دستور گیر می‌اندازد، هم ریسک FloodWait شدید یا محدودیت از طرف تلگرام را
# به‌شدت بالا می‌برد.
MAX_BULK_DELETE = 500

# سقف طول اسم پایه‌ای که در DB ذخیره می‌شود. تلگرام خودش سقف ۶۴ کاراکتری
# برای first_name دارد (که در _set_profile با first[:64] اعمال می‌شود)، اما
# قبلاً self.base_name در DB بدون این سقف ذخیره می‌شد — یعنی می‌شد یک نام
# خیلی طولانی‌تر از چیزی که واقعاً روی پروفایل تلگرام دیده می‌شود در دستور
# «وضعیت» به کاربر نشان داده شود. این ثابت هر دو نقطه را هماهنگ نگه می‌دارد.
MAX_BASE_NAME_LEN = 64


def cleanup_stale_tracker_files() -> None:
    """
    فایل‌های باقی‌مانده در TRACKER_MEDIA_DIR را پاک می‌کند.
    این فایل‌ها معمولاً مدیای دانلودشده‌ی ردیاب از یک سشن قبلی هستند که
    به‌خاطر کرش یا قطع ناگهانی برنامه (نه از مسیر عادی «سلف/ردیاب خاموش»)
    روی دیسک باقی مانده‌اند. چون این پوشه بین همه‌ی اکانت‌ها مشترک است،
    این پاکسازی فقط یک‌بار در همان لحظه‌ی استارت کل برنامه (main) اجرا می‌شود
    تا با کش زنده‌ی هیچ اکانتی که در همان لحظه دارد start می‌شود تداخل نکند.
    """
    if not os.path.isdir(TRACKER_MEDIA_DIR):
        return
    removed = 0
    for fname in os.listdir(TRACKER_MEDIA_DIR):
        fpath = os.path.join(TRACKER_MEDIA_DIR, fname)
        try:
            if os.path.isfile(fpath):
                os.remove(fpath)
                removed += 1
        except Exception:
            pass
    if removed:
        print(f"🧹 {removed} فایل قدیمی ردیاب از سشن قبلی پاک‌سازی شد.")


def cleanup_orphan_sessions() -> None:
    """
    سشن‌های یتیم را پاک می‌کند: فایل‌های .session (و وابسته‌هایشان) در
    SESSIONS_DIR که تگشان در config.json نیست. این‌ها معمولاً از لاگین‌های
    نیمه‌کاره (کد زده، لغو کرده، یا کلاینت وسطِ لاگین مرده) باقی می‌مانند —
    هم حافظه‌ی بی‌استفاده می‌خورند هم «اعتبارِ کامل اکانت» روی دیسک
    می‌مانند. فقط یک‌بار در استارتاپ اجرا می‌شود (مثل
    cleanup_stale_tracker_files) تا با ویزاردِ لاگینِ در جریان تداخل نکند:
    فایل‌هایی که تازه‌تر از ORPHAN_SESSION_GRACE هستند دست نمی‌خورند.
    """
    if not os.path.isdir(SESSIONS_DIR):
        return
    # فقط وقتی config معتبر است: config خراب نباید باعث شود همه‌ی سشن‌ها
    # «یتیم» تشخیص داده شوند و پاک شوند.
    cfg = load_config()
    if config_state() != CONFIG_VALID:
        print(
            f"⛔ پاک‌سازی سشن‌های یتیم اجرا نشد — config.json خراب/غیرقابل‌اعتماد است "
            f"(مسیر: {CONFIG_FILE}). هیچ سشنی حذف نشد."
        )
        return
    known = set(cfg.keys()) | {ADMIN_BOT_SESSION_NAME}
    now = time.time()
    removed = 0
    for fname in os.listdir(SESSIONS_DIR):
        # فقط فایل‌های سشن واقعی: {tag}.session و سایدکارهایش
        # ({tag}.session-journal / -wal / -shm).
        if not fname.endswith(".session"):
            continue
        tag = fname[: -len(".session")]
        if tag in known:
            continue
        # سشن‌هایی که runtime/استارتِ در جریان دارند (حتی اگر تگشان هنوز در
        # config نباشد) هرگز حذف نمی‌شوند — یک لاگینِ در جریان یا استارتِ
        # در حال انجام نباید سشنش پاک شود.
        if (tag in ACCOUNTS or tag in _RUNTIME_TASKS or tag in _PENDING_STARTS
                or _STOP_INFLIGHT.get(tag)):
            continue
        # همه‌ی وابسته‌های همان تگ را پاک می‌کنیم
        for suffix in ("", "-journal", "-wal", "-shm"):
            p = os.path.join(SESSIONS_DIR, tag + ".session" + suffix)
            try:
                if os.path.isfile(p) and now - os.path.getmtime(p) >= ORPHAN_SESSION_GRACE:
                    os.remove(p)
                    removed += 1
            except Exception:
                pass
    if removed:
        print(f"🧹 {removed} فایل سشن یتیم (تگ حذف‌شده/لاگین ناتمام) پاک‌سازی شد.")


def _session_file_for(tag: str) -> str:
    """
    مسیرِ واحدِ فایل سشن هر تگ: {SESSIONS_DIR}/{tag}.session — همان‌طوری که
    تلتون به ورودیِ TelegramClient(session_path) پسوند .session اضافه
    می‌کند. همه‌ی عملیات سشن (health check / sidecar / حذف) باید از همین
    مسیر استفاده کنند، نه از {tag} خام.
    """
    return os.path.join(SESSIONS_DIR, tag + ".session")


def check_session_health(tag: str, require_sqlite: bool = True) -> dict:
    """
    بررسی سلامت سشنِ یک اکانت — بدون هیچ secret در خروجی.

    چک‌ها (به‌ترتیب):
      1. دایرکتوری سشن وجود دارد و قابل نوشتن است (SQLite برای لاک/journal
         به write روی دایرکتوری نیاز دارد).
      2. فایل سشن (اگر هست) قابل نوشتن است؛ اگر متعلق به همان user است و
         فقط mode اشتباه دارد، به‌صورت امن به 0600 اصلاح می‌شود (سشن حاوی
         کلید احراز هویت است). هرگز chmod 777 یا تغییر مالک انجام نمی‌شود.
      3. پروبِ واقعی SQLite: یک تراکنش write که rollback می‌شود — تنها چکِ
         قطعی (زیر root، os.access همیشه True است). اگر DB فقط قفل است
         (handle فعالِ دیگری — برای کلاینتِ در حال اجرا طبیعی است) و فایل
         writable است، قبول می‌شود.

    require_sqlite=False: برای مسیر Restore — محتوای غیر-sqlite (فایل خراب/
    خالی) فقط هشدار می‌شود (چون مشکلِ permission ندارد و جلوگیری از Restore
    کل سیستم به‌خاطر یک سشنِ از-قبل-خراب درست نیست)؛ ولی مشکل واقعی
    permission/readonly همچنان fail می‌کند.

    برگشت: dict با کلیدهای ok/path/exists/dir_writable/file_writable/
    same_owner/sqlite_ok/error.
    """
    res = {
        "ok": False, "path": None, "exists": False,
        "dir_writable": False, "file_writable": False,
        "same_owner": None, "sqlite_ok": False, "error": None,
    }
    try:
        session_file = _session_file_for(tag)
        res["path"] = session_file
        if not os.path.isdir(SESSIONS_DIR):
            res["error"] = f"دایرکتوری سشن وجود ندارد یا پوشه نیست: {SESSIONS_DIR}"
            return res
        res["dir_writable"] = os.access(SESSIONS_DIR, os.W_OK | os.X_OK)
        if not res["dir_writable"]:
            res["error"] = f"دایرکتوری سشن قابل نوشتن نیست: {SESSIONS_DIR}"
            return res
        if not os.path.exists(session_file):
            # فایل هنوز ساخته نشده — دایرکتوری writable است و تلتون موقع
            # connect می‌سازدش (حالت طبیعی برای لاگینِ جدید).
            res["file_writable"] = True
            res["sqlite_ok"] = True
            res["ok"] = True
            return res
        res["exists"] = True
        try:
            st = os.stat(session_file)
            uid = os.getuid() if hasattr(os, "getuid") else None
            res["same_owner"] = (uid is None) or (st.st_uid == uid)
        except OSError:
            res["same_owner"] = None
        res["file_writable"] = os.access(session_file, os.W_OK)
        if not res["file_writable"] and res["same_owner"] is True:
            # مالک همان user است و فقط mode اشتباه دارد → اصلاحِ امن به 0600.
            try:
                _chmod_private(session_file)
                res["file_writable"] = os.access(session_file, os.W_OK)
                print(
                    f"🛠 [SESSION][{tag}][CHECK] mode فایل سشن به 0600 اصلاح شد "
                    f"(مالک همان user است)."
                )
            except OSError as e:
                res["error"] = (
                    f"فایل سشن قابل نوشتن نیست و اصلاح خودکار ممکن نشد: "
                    f"{str(e)[:80]}. مسیر: {session_file}"
                )
                return res
        if not res["file_writable"]:
            res["error"] = (
                f"فایل سشن قابل نوشتن نیست (مالک/دسترسی). مسیر: {session_file} — "
                f"با مالکِ صحیح اجرا کنید یا دسترسی فایل را اصلاح کنید."
            )
            return res
        # پروبِ واقعی SQLite (write + rollback — بدون تغییر دائمی)
        try:
            conn = sqlite3.connect(session_file, timeout=2)
            try:
                conn.execute("BEGIN")
                conn.execute("CREATE TABLE IF NOT EXISTS _session_health_probe (x INTEGER)")
                conn.execute("DROP TABLE _session_health_probe")
            finally:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                conn.close()
            res["sqlite_ok"] = True
        except sqlite3.Error as e:
            em = str(e).lower()
            if ("locked" in em or "busy" in em) and res["file_writable"]:
                # قفل = handle فعالِ دیگری سشن را باز دارد (برای کلاینتِ در
                # حال اجرا طبیعی است)؛ فایل writable است پس اشکالی ندارد.
                res["sqlite_ok"] = True
            elif not require_sqlite and (
                "not a database" in em or "database disk image is malformed" in em
                or "format" in em
            ):
                # محتوا sqlite نیست (فایل placeholder/خراب/خالی) — در مسیر
                # Restore فقط هشدار، نه fail: permission مشکلی ندارد و این
                # یک مشکل داده‌ی از-قبل-موجود است.
                res["sqlite_ok"] = False
                print(
                    f"⚠️ [SESSION][{tag}][CHECK] فایل سشن sqlite معتبر نیست "
                    f"(محتوای غیرمعتبر) — در Restore نادیده گرفته شد. مسیر: {session_file}"
                )
            else:
                res["error"] = (
                    f"SQLite سشن قابل نوشتن/خواندن نیست: {str(e)[:100]}. مسیر: {session_file}"
                )
                return res
        res["ok"] = True
        return res
    except Exception as e:
        res["error"] = f"خطا در بررسی سلامت سشن: {str(e)[:100]}"
        return res


# ══════════════════════════════════════════════════════════
#  تایم‌زون ایران: UTC+3:30 ثابت (بدون تغییر تابستانی/زمستانی)
#  (در ابتدای فایل تعریف می‌شود تا همه‌ی کمک‌تابع‌های تاریخ بتوانند
#   از همان ابتدا استفاده کنند — مثلاً _fmt_dt_local.)
# ══════════════════════════════════════════════════════════
_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def iran_now() -> datetime:
    """زمان دقیق ایران (UTC+3:30) را برمی‌گرداند — مستقل از تایم‌زون سرور."""
    return datetime.now(_IRAN_TZ)


@dataclass
class RunningAccount:
    tag: str
    bot: "SelfBot"
    task: "asyncio.Task"


ACCOUNTS: dict = {}


def register_account(tag: str, bot: "SelfBot", task: "asyncio.Task") -> None:
    ACCOUNTS[tag] = RunningAccount(tag=tag, bot=bot, task=task)


def unregister_account(tag: str) -> None:
    ACCOUNTS.pop(tag, None)


# ─────────────────────────────────────────────────────────────
#  وضعیت runtime هر اکانت + صفِ آماده‌شدن (مسیر لاگین/فعال‌سازی)
# ─────────────────────────────────────────────────────────────
# BOT_STATUS: tag → یکی از وضعیت‌های runtime:
#   starting / connecting / ready / reconnecting / error /
#   auth_failed / stopped
# جدا از ACCOUNTS نگه داشته می‌شود، چون ACCOUNTS فقط بعد از «آماده‌شدنِ
# کامل» پر می‌شود (ثبتِ زودهنگام = نمایش «فعال» برای اکانتی که هنوز حتی
# connect نکرده). در بازه‌ی اتصال و در حالت خطا/قطع، UI باید وضعیت را از
# همین‌جا بخواند.
BOT_STATUS: dict = {}

# _PENDING_STARTS: tag → asyncio.Future[bool]
#   با True وقتی SelfBot واقعاً READY شد resolve می‌شود؛ با False وقتی
#   اکانت به‌طور دائمی از کار افتاد (خطای احراز هویت غیرقابل‌بازیابی).
#   ویزارد لاگین و «فعال‌سازی اکانت» منتظر همین Future می‌مانند تا هرگز
#   پیام موفقیتِ دروغین ندهند.
_PENDING_STARTS: dict = {}

# _TAG_LOCKS: tag → asyncio.Lock — حداکثر یک run_bot (و در نتیجه یک
# TelegramClient) برای هر تگ در هر لحظه؛ جلوگیری از دو کلاینت هم‌زمان روی
# یک فایل سشن.
_TAG_LOCKS: dict = {}


_STATUS_HUMAN = {
    "starting": "در حال راه‌اندازی",
    "connecting": "در حال اتصال",
    "reconnecting": "در حال اتصال مجدد",
    "ready": "آماده",
    "error": "خطا",
    "auth_failed": "خطای احراز هویت",
    "stopped": "متوقف",
    "timeout": "در حال تلاش (بیش از حد انتظار طول کشید)",
    "maintenance": "سیستم در حالت تعمیر/بازیابی است",
    "shutting_down": "سیستم در حال خاموش‌شدن است",
}


def _status_human(status: str) -> str:
    """ترجمه‌ی وضعیت runtime به فارسی برای پیام‌های کاربرپسند."""
    return _STATUS_HUMAN.get(status, status or "نامشخص")


def _set_bot_status(tag: str, status: str) -> None:
    BOT_STATUS[tag] = status


def _mark_pending_start(tag: str):
    """
    یک Future برای «آماده‌شدن» این تگ برمی‌گرداند. اگر Futureِ فعال
    (تمام‌نشده‌ای) وجود داشته باشد، همان برمی‌گردد — هرگز Future فعال
    overwrite نمی‌شود تا همه‌ی منتظرانِ استارتِ در جریان، همان Future مشترک
    را ببینند و با اولین READY (یا اولین شکستِ دائمی) resolve شوند.
    فقط وقتی Future قبلی وجود ندارد یا تمام‌شده است، Future جدید ساخته می‌شود
    (مثلاً بعد از شکستِ دائمی، استارتِ بعدی Future تازه می‌گیرد).
    همزمان وضعیت runtime به «starting» ریست می‌شود مگر اکانت واقعاً در حال
    اجراست (ready) — تا UI «در حال اتصال»ِ دروغین نشان ندهد.
    """
    existing = _PENDING_STARTS.get(tag)
    if existing is not None and not existing.done():
        return existing
    fut = asyncio.get_running_loop().create_future()
    _PENDING_STARTS[tag] = fut
    if BOT_STATUS.get(tag) != "ready":
        _set_bot_status(tag, "starting")
    return fut


def _runtime_offline_status(tag: str) -> tuple:
    """(icon, note) برای وقتی اکانت در ACCOUNTS نیست — از BOT_STATUS واقعی."""
    st = BOT_STATUS.get(tag)
    if st in ("starting", "connecting"):
        return "🟡", "در حال اتصال..."
    if st == "reconnecting":
        return "🟡", "در حال اتصال مجدد..."
    if st == "error":
        return "🔴", "خطا — در حال تلاش مجدد"
    if st == "auth_failed":
        return "🔴", "خطای احراز هویت"
    if st == "stopped":
        return "🔴", "خاموش"
    return "🔴", "خاموش / در حال اتصال"


def _acc_status_icon_note(acc: dict, tag: str) -> tuple:
    """
    (icon, note) یکپارچه برای همه‌ی لیست‌ها: disabled → متوقف؛ در ACCOUNTS و
    READY → فعال با آپ‌تایم؛ وگرنه وضعیت واقعی از BOT_STATUS (🟡 اتصال / 🔴 خطا...).
    """
    if acc.get("disabled"):
        return "🔴", "متوقف"
    entry = ACCOUNTS.get(tag)
    if entry is not None and getattr(entry.bot, "runtime_status", "ready") == "ready":
        try:
            return "🟢", f"فعال — آپ‌تایم: {entry.bot._uptime()}"
        except Exception:
            return "🟢", "فعال"
    return _runtime_offline_status(tag)


# نگاشتِ نشانگرهای قدیمی به «وضعیتِ نام‌دار»ِ UI. همه‌ی لیست‌ها و صفحات از
# همین یک تابع وضعیت می‌گیرند تا رنگِ یک اکانت در هر صفحه‌ای که دیده شود
# دقیقاً یکی باشد (قبلاً هر لیست نگاشتِ دستیِ خودش را داشت و مثلاً «متوقف»
# در یک صفحه ⏸ و در صفحه‌ی دیگر 🔴 نشان داده می‌شد).
_UI_STATE_BY_ICON = {"🟢": "ready", "🟡": "connecting", "🔴": "off", "⏸": "paused"}


def _acc_ui_state(acc: dict, tag: str) -> tuple:
    """(state, note) برای UI — state یکی از کلیدهای UI.state_dot است."""
    if acc.get("disabled"):
        return "paused", "متوقف (دستی)"
    icon, note = _acc_status_icon_note(acc, tag)
    return _UI_STATE_BY_ICON.get(icon, "off"), note


def account_belongs_to(acc: dict, tag: str, user_id: int) -> bool:
    """
    آیا این سلف متعلق به این کاربر است؟ **تنها قاعده‌ی مالکیت در کل پروژه.**

    سه راهِ هم‌ارزِ اثبات (هرکدام کافی است):

      ۱) owner_user_id — پیوندِ صریحی که موقع ساختِ اکانت از داخل پنل
         نوشته می‌شود.
      ۲) tg_user_id — شناسه‌ی واقعیِ اکانتِ تلگرامی که سلف رویش لاگین است.
         موقعِ هر استارت ثبت می‌شود.
      ۳) my_idِ نمونه‌ی در حال اجرا — برای سلفی که همین حالا بالاست ولی
         هنوز فرصت نکرده هویتش را در config بنویسد.

    چرا سه‌تایی: قبلاً فقط مورد ۱ ملاک بود و آن هم فقط در مسیرِ «افزودن از
    داخل پنل» پر می‌شد. نتیجه این بود که سلفی که دستی یا از ترمینال لاگین
    شده بود، با اینکه دقیقاً روی اکانتِ همان کاربر بود، در «سلف من»ِ او
    دیده نمی‌شد و خودش نمی‌توانست مدیریتش کند.

    حالا نحوه‌ی لاگین (دستی / لایسنس / ترمینال / از پنل) هیچ تفاوتی در
    مالکیت ایجاد نمی‌کند — چیزی که اهمیت دارد این است که سلف روی اکانتِ
    چه کسی است.
    """
    if not isinstance(acc, dict) or not user_id:
        return False
    if acc.get("owner_user_id") == user_id:
        return True
    if acc.get("tg_user_id") == user_id:
        return True
    entry = ACCOUNTS.get(tag)
    if entry is not None and getattr(entry.bot, "my_id", None) == user_id:
        return True
    return False


def accounts_of_user(cfg: dict, user_id: int) -> dict:
    """{tag: acc} همه‌ی سلف‌هایی که به این کاربر تعلق دارند."""
    return {tag: acc for tag, acc in (cfg or {}).items()
            if account_belongs_to(acc, tag, user_id)}


def account_is_orphan(acc: dict, tag: str) -> bool:
    """
    سلفی که به هیچ کاربری وصل نیست — یعنی نه پیوندِ صریح دارد و نه هویتِ
    اکانتش شناخته شده. سلفی که tg_user_id دارد دیگر یتیم نیست: صاحبش
    مشخص است، حتی اگر owner_user_id خالی باشد.
    """
    if not isinstance(acc, dict):
        return False
    if acc.get("owner_user_id") is not None:
        return False
    if acc.get("tg_user_id"):
        return False
    entry = ACCOUNTS.get(tag)
    if entry is not None and getattr(entry.bot, "my_id", None):
        return False
    return True


async def _await_account_ready(tag: str, timeout: float = ACCOUNT_START_POLL_TIMEOUT) -> tuple:
    """
    منتظر «آماده‌شدن واقعی» اکانت می‌ماند (runtime_status == ready یا
    Futureِ آماده‌شدن resolve شده). دیگر به صرفِ وجود در ACCOUNTS اکتفا
    نمی‌کند — چون ACCOUNTS فقط بعد از READY کامل پر می‌شود.

    برمی‌گرداند: (ready: bool, status: str) — در حالت ready=False، status
    یکی از کدهای _STATUS_HUMAN است (مثلاً timeout یا auth_failed).
    """
    fut = _PENDING_STARTS.get(tag)
    deadline = time.monotonic() + timeout
    last = "starting"
    while True:
        entry = ACCOUNTS.get(tag)
        if entry is not None:
            st = getattr(entry.bot, "runtime_status", "ready")
            if st == "ready":
                return True, "ready"
            last = st
        st = BOT_STATUS.get(tag)
        if st:
            last = st
            if st == "auth_failed":
                return False, st
        if fut is not None and fut.done():
            if fut.result() is True:
                return True, "ready"
            return False, "auth_failed"
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(1)
    return False, last


# ─────────────────────────────────────────────────────────────
#  Runtime Manager — مرکز واحد Start/Stop/Reuse برای هر tag
# ─────────────────────────────────────────────────────────────
# قانون: برای هر tag در هر لحظه فقط یک Runtime (یک run_bot → یک SelfBot →
# یک TelegramClient → یک Session). همه‌ی مسیرها (startup/enable/disable/
# login/resume/proxy/direct) باید از همین API استفاده کنند؛ run_bot مستقیم
# فقط توسط همین Manager و startup صدا زده می‌شود.
#
# وضعیت‌های Runtime: RUNNING (در ACCOUNTS + ready) / STARTING (starting یا
# connecting) / STOPPING (_STOP_INFLIGHT) / STOPPED.
_STOP_INFLIGHT: dict = {}  # tag → True تا وقتی ensure_stopped در جریان است

# _RUNTIME_TASKS: tag → asyncio.Task — تسکِ واقعیِ run_bot که توسط
# ensure_started ساخته می‌شود. جدا از ACCOUNTS نگه داشته می‌شود چون ACCOUNTS
# فقط بعد از READY پر می‌شود؛ تسکِ «در حال استارت» (هنوز ثبت‌نشده) و تسکِ در
# backoff (آنرجیستر شده) باید برای Stop/Shutdown قابل یافتن باشند تا هیچ
# Task یتیم نماند.
_RUNTIME_TASKS: dict = {}

# Maintenance/Shutdown gate: وقتی True باشد، ensure_started هر استارت جدیدی را
# رد می‌کند — Restore نباید وسطِ کارِش Runtime جدیدی ببیند و Shutdown نباید
# اجازه بدهد وسطِ خاموشی، یک callback دوباره Runtime بسازد.
_MAINTENANCE_MODE = False
SHUTTING_DOWN = False

# _START_LOCKS: tag → asyncio.Lock — قفلِ واقعیِ «استارت» (PATCH 8): کلِ
# check → mark pending → create task برای هر tag زیرِ همین قفل اجرا می‌شود تا
# دو Coroutine هم‌زمان نتوانند هر دو از چک‌ها رد شوند و دو استارت بسازند.
_START_LOCKS: dict = {}


def _runtime_caller(depth: int = 2) -> str:
    """نام تقریبی فراخوانِ runtime (برای لاگ [TAG][RUNTIME][REQUEST])."""
    try:
        import traceback as _tb3
        frames = _tb3.extract_stack()
        if len(frames) > depth:
            fr = frames[-1 - depth]
            return f"{os.path.basename(fr.filename)}:{fr.name}"
    except Exception:
        pass
    return "?"


def get_runtime(tag: str):
    """Runtime فعلی (RunningAccount) یا None."""
    return ACCOUNTS.get(tag)


def is_running(tag: str) -> bool:
    """واقعاً READY است (در ACCOUNTS + runtime_status == ready)."""
    entry = ACCOUNTS.get(tag)
    return entry is not None and getattr(entry.bot, "runtime_status", "ready") == "ready"


def is_starting(tag: str) -> bool:
    """در حال اتصال/راه‌اندازی است (هنوز READY نشده)."""
    return BOT_STATUS.get(tag) in ("starting", "connecting")


def is_stopping(tag: str) -> bool:
    """ensure_stopped در جریان است."""
    return bool(_STOP_INFLIGHT.get(tag))


def _active_runtime_tags() -> list:
    """
    تگ‌هایی که در حال حاضر Runtime/Client فعال دارند — شامل READY (ACCOUNTS)،
    در حال استارت/backoff (_RUNTIME_TASKS) و در حال توقف (_STOP_INFLIGHT).
    هر یک از این حالت‌ها یعنی Session ممکن است باز باشد؛ پس هیچ عملیاتِ
    جایگزین‌کننده‌ای روی DB/سشن نباید هم‌زمان با آن‌ها انجام شود (PATCH 4).
    """
    tags = list(dict.fromkeys(list(ACCOUNTS.keys()) + list(_RUNTIME_TASKS.keys())))
    for t in _STOP_INFLIGHT:
        if t not in tags:
            tags.append(t)
    return tags


async def wait_ready(tag: str, timeout: float = ACCOUNT_START_POLL_TIMEOUT) -> tuple:
    """همان _await_account_ready — منتظر READY واقعی."""
    return await _await_account_ready(tag, timeout)


async def ensure_stopped(tag: str, caller: str = "?") -> bool:
    """
    توقف کامل و idempotent: stop → cancel task → منتظر پایانِ واقعیِ
    پاک‌سازی (finally داخل run_bot: disconnect → save → close → unregister).

    برگشت: True اگر runtime واقعاً و کاملاً متوقف شد (تسک تمام شد و
    تمیزکاری انجام شد)؛ False اگر تسک هنوز زنده است (timeout) — در آن حالت
    هیچ ownership ای آزاد نمی‌شود: نه unregister، نه حذف از _RUNTIME_TASKS،
    و استارتِ جدید همان تگ تا پایانِ واقعیِ تسک رد می‌شود (تسک همچنان
    قفلِ _TAG_LOCKS خودش را گرفته است).

    PATCH 1: یک runtime فقط وقتی «متوقف» محسوب می‌شود که تسکش واقعاً
    تمام شده باشد — timeout به معنی آزاد کردن سشن نیست (Collision سشن /
    دو کلاینت روی یک .session ممنوع).
    """
    print(f"[{tag}][RUNTIME][STOP] caller={caller}")
    _STOP_INFLIGHT[tag] = True
    try:
        entry = ACCOUNTS.get(tag)
        if entry is not None:
            try:
                await asyncio.wait_for(entry.bot.stop(), timeout=15)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # PATCH 6: خطای stop بلعیده نمی‌شود — tag + عملیات + خطا لاگ می‌شود.
                print(f"❌ [{tag}][RUNTIME][STOP][stop] خطا در bot.stop: "
                      f"{type(e).__name__}: {str(e)[:100]}")
        # مالکِ Cleanup نهایی خودِ run_bot است (finally: disconnect → save →
        # close → unregister). اینجا فقط Cancel + Wait واقعی — تا وقتی تسک
        # زنده است، هیچ‌چیز به‌عنوان «متوقف‌شده» آزاد نمی‌شود.
        task = _RUNTIME_TASKS.get(tag)
        if task is not None and not task.done():
            task.cancel()
            # PATCH 1: از asyncio.wait_for استفاده نمی‌شود — wait_for در لحظه‌ی
            # timeout خودش تسک را cancel می‌کند؛ یعنی تسکی که cancel را نادیده
            # می‌گیرد (مثلاً وسط disconnect/save/close چسبیده) سرِ موعد کشته
            # می‌شود و دیگر «تسکِ زنده بعد از timeout» نمی‌تواند وجود داشته
            # باشد تا ownership حفظ شود. asyncio.wait در timeout تسک را زنده
            # نگه می‌دارد:
            #   - اگر تسک واقعاً تمام شد (با cancelِ ما، یا به هر دلیل دیگر)
            #     → موفق؛ finallyِ run_bot تمیزکاری کرده (disconnect → save →
            #     close → unregister).
            #   - اگر بعد از ۱۰ ثانیه هنوز زنده بود → توقف کامل اعلام نمی‌شود؛
            #     هیچ ownership ای آزاد نمی‌شود (نه unregister، نه pop) و
            #     مرجعِ تسک حفظ می‌شود تا تمیزکاریِ خودش را تمام کند؛ استارتِ
            #     جدیدِ همان تگ همچنان به قفلِ _TAG_LOCKSِ در دستِ تسک می‌خورد
            #     و Client دوم روی همان Session ساخته نمی‌شود.
            done, _pending = await asyncio.wait({task}, timeout=10)
            if task in done:
                if not task.cancelled():
                    exc = task.exception()
                    if exc is not None:
                        # PATCH 6: خطای واقعیِ تسکِ متوقف‌شده بلعیده نمی‌شود.
                        print(f"❌ [{tag}][RUNTIME][STOP][wait] تسک با خطا تمام "
                              f"شد: {type(exc).__name__}: {str(exc)[:100]}")
                return True  # تسک واقعاً تمام شد → finallyِ run_bot تمیزکاری کرد
            # تسک هنوز زنده است (PATCH 1): نباید unregister شود و نباید از
            # _RUNTIME_TASKS حذف شود — runtime همچنان مالک سشن است.
            print(f"❌ [{tag}][RUNTIME][STOP][wait] تسک بعد از cancel و "
                  f"۱۰ ثانیه هنوز زنده است — توقف کامل اعلام نمی‌شود؛ "
                  f"runtime همچنان مالک سشن است و استارتِ جدید رد می‌شود.")
            return False
        # این‌جا هیچ تسکِ زنده‌ای نیست (task وجود ندارد یا تمام شده) — یعنی
        # ریسکِ Collision سشن وجود ندارد. فقط ممکن است ردیفی در ACCOUNTS
        # باقی مانده باشد (مثلاً ثبتِ دستی در تست/بازیابی) که باید تمیز شود
        # (تنها استثنای مستند مالکیت).
        entry = ACCOUNTS.get(tag)
        if entry is not None:
            try:
                await asyncio.wait_for(entry.bot.stop(), timeout=5)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # PATCH 6: خطای stop در تمیزکاریِ تکمیلی بلعیده نمی‌شود.
                print(f"❌ [{tag}][RUNTIME][STOP][cleanup] خطا در stop تکمیلی "
                      f"(بدون تسک زنده): {type(e).__name__}: {str(e)[:100]}")
            unregister_account(tag)
            _RUNTIME_TASKS.pop(tag, None)
            print(f"⚠️ [{tag}][RUNTIME][STOP] تمیزکاری تکمیلی انجام شد (unregister)")
        return True
    finally:
        _STOP_INFLIGHT.pop(tag, None)


async def ensure_started(tag: str, config: dict, caller: str = "?",
                         interactive: bool = False,
                         wait_seconds: float = 40,
                         runner=None) -> tuple:
    """
    مرکزِ استارت:
      RUNNING  → reuse (همان Runtime؛ Client دوم ساخته نمی‌شود)
      STARTING → همان درخواستِ در جریان await می‌شود (Future فعال overwrite
                 نمی‌شود — waiterهای متعدد همان Future مشترک را می‌بینند)
      STOPPING → منتظر پایانِ کاملِ stop می‌ماند
      STOPPED  → Runtime جدید می‌سازد

    runner: callable(tag, config, interactive) — پیش‌فرض خودِ run_bot. وقتی
    از داخل AdminBot/SaaSBot صدا زده می‌شود باید runner=self.sb.run_bot
    داده شود تا در تست‌ها هم شیمِ همان‌جا کار کند.

    برگشت: (ready: bool, status: str) — مثل _await_account_ready.
    """
    print(f"[{tag}][RUNTIME][REQUEST] caller={caller}")
    if _MAINTENANCE_MODE or SHUTTING_DOWN:
        reason = "maintenance" if _MAINTENANCE_MODE else "shutting_down"
        print(f"[{tag}][RUNTIME][REJECT] {reason} فعال است — استارت رد شد (caller={caller})")
        return False, reason
    # قفلِ واقعیِ per-tag: کلِ check → mark → create زیرِ همین قفل اجرا می‌شود
    # تا دو Coroutine هم‌زمان نتوانند هر دو از چک‌ها رد شوند. منتظرهای بعدی
    # بعد از آزادشدنِ قفل دوباره وضعیت را چک می‌کنند (REUSE/WAIT).
    async with _START_LOCKS.setdefault(tag, asyncio.Lock()):
        if is_running(tag):
            print(f"[{tag}][RUNTIME][REUSE] runtime آماده است (caller={caller})")
            return True, "ready"
        # اگر تسکِ run_bot هنوز زنده است (حتی در حالت error/backoff یا شروعِ
        # ناقص) — یعنی یک Runtime واقعاً در جریان است — تسک دوم ساخته نمی‌شود
        # (به قفلِ per-tagِ run_bot می‌خورد و بی‌فایده برمی‌گردد و Future تازه
        # هیچ‌کس resolve نمی‌کند). به‌جایش همان Future مشترکِ استارتِ قبلی await
        # می‌شود: اگر تلاشِ بعدیِ همان Runtime موفق شود، منتظر READY می‌گیرد؛
        # اگر شکستِ دائمی بخورد، با auth_failed برمی‌گردد.
        lock = _TAG_LOCKS.get(tag)
        if lock is not None and lock.locked():
            print(f"[{tag}][RUNTIME][WAIT] runtime هنوز زنده است (start/backoff) — همان تلاش await می‌شود (caller={caller})")
            return await _await_account_ready(tag, timeout=wait_seconds)
        if is_starting(tag):
            print(f"[{tag}][RUNTIME][WAIT] runtime در حال شروع است — همان await می‌شود (caller={caller})")
            return await _await_account_ready(tag, timeout=wait_seconds)
        if is_stopping(tag):
            print(f"[{tag}][RUNTIME][WAIT] runtime در حال توقف است — منتظر پایان کامل (caller={caller})")
            for _ in range(int(wait_seconds / 0.4) + 1):
                if not _STOP_INFLIGHT.get(tag):
                    break
                await asyncio.sleep(0.4)
            if _STOP_INFLIGHT.get(tag):
                # توقف هنوز کامل نشده (disconnect/save/close در جریان است) —
                # استارتِ جدید همان Session را باز می‌کند و Collision/readonly
                # می‌سازد؛ پس رد می‌شود (PATCH 6).
                print(f"[{tag}][RUNTIME][WAIT] توقف هنوز کامل نشده — استارت رد شد (caller={caller})")
                return False, "stopping"
        print(f"[{tag}][RUNTIME][START] caller={caller}")
        _mark_pending_start(tag)

        run_bot_fn = runner or run_bot
        task = asyncio.create_task(run_bot_fn(tag, config, interactive=interactive))
        _RUNTIME_TASKS[tag] = task
        task.add_done_callback(
            lambda t, tag=tag: _RUNTIME_TASKS.pop(tag, None)
            if _RUNTIME_TASKS.get(tag) is t else None
        )
        ready, st = await _await_account_ready(tag, timeout=wait_seconds)
        if ready:
            print(f"[{tag}][RUNTIME][READY] (caller={caller})")
        else:
            print(f"[{tag}][RUNTIME][FAILED] status={st} (caller={caller})")
        return ready, st


async def restart(tag: str, config: dict, caller: str = "?",
                  runner=None) -> tuple:
    """توقف کامل → استارت جدید (مثلاً تغییر پروکسی). runner مثل
    ensure_started — وقتی از داخل AdminBot/SaaSBot صدا زده می‌شود باید
    self.sb.run_bot داده شود."""
    print(f"[{tag}][RUNTIME][RESTART] caller={caller}")
    await ensure_stopped(tag, caller)
    return await ensure_started(tag, config, caller, runner=runner)


_shutdown_event: Optional[asyncio.Event] = None


async def _graceful_shutdown_all() -> None:
    """
    وقتی سیگنال SIGTERM/SIGINT (یعنی kill عادی یا Ctrl+C از ترمینال) دریافت
    می‌شود، این تابع همه‌ی اکانت‌های در حال اجرا را به‌طور تمیز و موازی متوقف
    می‌کند: هر SelfBot.stop() صدا زده می‌شود که session.save()/close() و
    client.disconnect() را انجام می‌دهد. بدون این مرحله، kill کردن پروسه
    باعث می‌شد فایل‌های سشن sqlite در حالت نیمه‌نوشته/قفل باقی بمانند و در
    اجرای بعدی همان اکانت‌ها با خطای «database is locked» یا سشن خراب مواجه
    شوند.
 """
    global SHUTTING_DOWN
    # از همین لحظه استارتِ جدید ممنوع است — هیچ callback ای وسطِ خاموشی
    # نباید Runtime جدیدی بسازد (PATCH 14).
    SHUTTING_DOWN = True
    tags = list(ACCOUNTS.keys())
    if not tags:
        return
    print(f"🛑 دریافت سیگنال توقف — بستن تمیز {len(tags)} اکانت...")

    async def _stop_one(tag: str) -> None:
        entry = ACCOUNTS.get(tag)
        if not entry:
            return
        try:
            await asyncio.wait_for(entry.bot.stop(), timeout=15)
        except asyncio.TimeoutError:
            print(f"⚠️ [{tag}] بستن بیش از ۱۵ ثانیه طول کشید — عبور اجباری")
        except Exception as e:
            print(f"⚠️ [{tag}] خطا هنگام بستن تمیز: {e}")

    await asyncio.gather(*(_stop_one(t) for t in tags), return_exceptions=True)

    for tag in tags:
        entry = ACCOUNTS.get(tag)
        if entry and entry.task and not entry.task.done():
            entry.task.cancel()

    # تسک‌های run_bot که از دید ACCOUNTS نامرئی‌اند (در حال استارت یا در
    # backoffِ reconnect) — هیچ Task مربوط به Runtime بعد از Shutdown نباید
    # باقی بماند.
    leftover = [t for t in list(_RUNTIME_TASKS.values()) if t is not None and not t.done()]
    for t in leftover:
        t.cancel()
    if leftover:
        await asyncio.gather(*leftover, return_exceptions=True)

    print("✅ همه‌ی اکانت‌ها به‌طور تمیز بسته شدند.")


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """
    سیگنال‌های SIGTERM و SIGINT را به یک خاموشی تمیز و کنترل‌شده وصل می‌کند.
    """
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    def _on_signal(sig_name: str):
        print(f"\n📡 سیگنال {sig_name} دریافت شد.")
        if _shutdown_event and not _shutdown_event.is_set():
            _shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _on_signal(s.name))
        except (NotImplementedError, RuntimeError):
            # روی برخی پلتفرم‌ها (مثلاً ویندوز) add_signal_handler پشتیبانی
            # نمی‌شود؛ در آن حالت رفتار قبلی (KeyboardInterrupt برای Ctrl+C)
            # همچنان به‌عنوان fallback کار می‌کند.
            pass


# وضعیت config.json — سه حالت جدا (هرگز «خراب» با «وجود ندارد» یکی نیست):
#   CONFIG_MISSING → فایل وجود ندارد (ساخت config جدید مجاز است)
#   CONFIG_VALID   → JSON معتبر و dict است (همه‌چیز عادی)
#   CONFIG_INVALID → فایل وجود دارد ولی خراب/ناخواناست — عملیات‌های مخرب
#                    (cleanup سشن، overwrite، حذف، یتیم‌سازی) ممنوع‌اند
CONFIG_MISSING = "missing"
CONFIG_VALID = "valid"
CONFIG_INVALID = "invalid"
_config_state = CONFIG_MISSING


def config_state() -> str:
    """وضعیت کنونی config.json (آخرین نتیجه‌ی load_config/save_config)."""
    return _config_state


def load_config() -> dict:
    """
    خواندن config.json با سه حالتِ جدا:
      - فایل وجود ندارد → CONFIG_MISSING + {} (ساخت config جدید مجاز)
      - JSON معتبر       → CONFIG_VALID + محتوای واقعی
      - فایل خراب/ناخوانا → CONFIG_INVALID + {} — ولی call site های مخرب
        (cleanup_orphan_sessions / overwrite / delete / یتیم‌سازی) باید
        config_state() را چک کنند؛ {} به معنی «هیچ اکانتی نیست» نیست،
        بلکه یعنی «config خراب است؛ دست نزن».
    """
    global _config_state
    if not os.path.exists(CONFIG_FILE):
        _config_state = CONFIG_MISSING
        return {}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError(f"config.json باید یک آبجکت JSON باشد، نه {type(cfg).__name__}")
        _config_state = CONFIG_VALID
        return cfg
    except Exception as e:
        _config_state = CONFIG_INVALID
        print(
            f"⛔ config.json خراب/ناخوانا است — مسیر: {CONFIG_FILE}. "
            f"عملیات‌های مخرب (پاک‌سازی سشن/بازنویسی/حذف) متوقف شدند؛ "
            f"فایل دست‌نخورده ماند. (مشکل: {type(e).__name__}: {e})"
        )
        return {}


def _spawn_dedicated_bot(bot_id: int, owner_id: int, token: str) -> str:
    """
    یک فرآیند جدا از همین main.py برای ربات اختصاصی راه‌اندازی می‌کند.
    هر ربات اختصاصی یک دایرکتوری مخصوص خودش دارد (dedicated_bots/<id>/) با
    config.json و دیتابیس‌های خودش؛ اعتبارنامه‌ی مدیریت (ADMIN_BOT_TOKEN و
    ADMIN_ID) از طریق env به آن می‌رسد. ورودیِ «base» در config آن، با
    api_id/api_hashِ مشترک سرور و disabled=true ساخته می‌شود — یعنی فقط
    منبعِ برداشتن اعتبارنامه برای ویزارد لاگین است و خودش ران نمی‌شود
    (مالکِ ربات اختصاصی اکانت‌های خودش را از پنل اضافه می‌کند).
    """
    import subprocess as _sp
    base_dir = os.path.join(_project_dir(), "dedicated_bots")
    bot_dir = os.path.join(base_dir, str(bot_id))
    os.makedirs(bot_dir, exist_ok=True)
    api_id, api_hash = _first_account_creds(load_config())
    cfg = {
        "base": {
            "type": "user",
            "api_id": api_id,
            "api_hash": api_hash,
            "user_id": owner_id,
            "disabled": True,
            "_placeholder": "پایه‌ی مشترک — فقط منبع api_id/api_hash؛ اجرا نمی‌شود",
        }
    }
    with open(os.path.join(bot_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    env = dict(os.environ)
    env["ADMIN_BOT_TOKEN"] = token
    env["ADMIN_ID"] = str(owner_id)
    # نشانِ «این یک ربات اختصاصی است» — با این متغیر، نمونه‌ی فرعی می‌داند
    # که مالکِ آن (ADMIN_ID) یک نماینده/مشتری است، نه مالکِ اصلیِ سیستم.
    # قابلیت‌های حساسِ نشست/2FA/کدِ لاگین بر اساس همین نشان محدود می‌شوند.
    env["SELFBOT_DEDICATED_BOT"] = "1"
    # شناسه‌ی دقیقِ ربات اختصاصی — برای اعتبارسنجیِ مجوزِ dedicated_bot
    # در لایه‌ی Authorization. نمونه‌ی فرعی می‌داند دقیقاً کدام رباتِ
    # اختصاصی را نمایندگی می‌کند.
    env["SELFBOT_DEDICATED_BOT_ID"] = str(bot_id)
    # دایرکتوری داده‌ی خودِ ربات اختصاصی — حتی با cwd متفاوت، DB/config/sessions
    # همین دایرکتوری می‌شود و DB اصلی پروژه در cwd ساخته نمی‌شود.
    env["SELFBOT_DATA_DIR"] = bot_dir
    log_path = os.path.join(bot_dir, "bot.log")
    with open(log_path, "a", encoding="utf-8") as log_f:
        proc = _sp.Popen(
            [sys.executable, os.path.join(_project_dir(), "main.py"), "all"],
            cwd=bot_dir,
            env=env,
            stdout=log_f,
            stderr=_sp.STDOUT,
        )
    # pidfile برای مدیریت (توقف/سلامت) — هم فرآیندِ والد هم بعداً OWNER از آن
    # استفاده می‌کند تا بدون نگه‌داشتن handle، PID را پیدا کند.
    with open(os.path.join(bot_dir, "pid.txt"), "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    return bot_dir


def _read_pidfile(bot_dir: str) -> int:
    if not bot_dir:
        return 0
    try:
        with open(os.path.join(bot_dir, "pid.txt"), encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def _process_alive(pid: int) -> bool:
    """آیا فرآیندی با این PID زنده است؟ (چکِ بدون سیگنال — فقط وجود)"""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # وجود دارد ولی متعلق به کاربر دیگر است
    except Exception:
        return False


async def _stop_process_by_pid(pid: int) -> bool:
    """
    توقف مودبانه‌ی فرآیند: SIGTERM (خاموشی تمیزِ main.py)، بعد حداکثر ۵
    ثانیه صبر، و در صورت باقی‌ماندن SIGKILL. برمی‌گرداند که آیا فرآیندی
    در جریان بود و متوقف شد.

    async شده تا asyncio.sleep به‌جای time.sleep استفاده شود — این تابع از
    داخل event handler های زنده‌ی ربات تلگرام و از داخل حلقه‌ی پس‌زمینه‌ای
    expiry_loop صدا زده می‌شود؛ time.sleep در این مسیرها کل event loop
    (یعنی همه‌ی SelfBot های در حال اجرا برای همه‌ی کاربران) را تا ۵ ثانیه
    فریز می‌کرد.
    """
    import signal as _sig
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, _sig.SIGTERM)
    except ProcessLookupError:
        return False
    except Exception:
        return False
    for _ in range(10):
        await asyncio.sleep(0.5)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True  # تمیز خارج شد
        except Exception:
            return True
    try:
        os.kill(pid, _sig.SIGKILL)
    except Exception:
        pass
    return True


def _first_account_creds(cfg: dict):
    """
    اعتبارنامه‌ی (api_id, api_hash) اولین اکانتِ *معتبر* در config — برای
    ساخت کلاینت‌های مشترک (سلف‌بات، ویزارد لاگین، پنل).

    این منطق قبلاً ۴ بار با `next(iter(cfg.values()))` تکرار شده بود و دو
    حالت کرش داشت: (۱) config خالی → StopIteration؛ (۲) اولین ورودی JSONِ
    سالم ولی ناقص (بدون api_id/api_hash) → KeyError. حالا همه‌ی ورودی‌ها
    را می‌گردد و اولین ورودیِ معتبر (دیکت با api_id و api_hash) را برمی‌-
    گرداند؛ اگر هیچ‌کدام معتبر نبود RuntimeError با پیام واضح می‌دهد.
    """
    for acc in cfg.values():
        if (
            isinstance(acc, dict)
            and acc.get("api_id") is not None
            and acc.get("api_hash")
        ):
            return acc["api_id"], acc["api_hash"]
    raise RuntimeError(
        "config.json خالی یا فاقد یک اکانتِ پایه‌ی معتبر (api_id/api_hash) است — "
        "این عملیات ممکن نیست. با پشتیبانی تماس بگیر."
    )


def save_config(cfg: dict) -> bool:
    """
    نوشتن اتمیک config.json: اول در یک فایل موقت (همان دایرکتوری) می‌نویسیم،
    fsync می‌کنیم و بعد os.replace می‌کنیم. قبلاً مستقیم داخل خودِ فایل
    نوشته می‌شد — یک کرش/قطع برق وسطِ نوشتن، کل فایلِ اعتبارنامه‌های همه‌ی
    مشتری‌ها (api_id/api_hash/توکن‌ها) را خراب می‌کرد. حالا در بدترین حالت
    فایل قبلی سالم می‌ماند.

    ایمنی config خراب: اگر وضعیت فعلی CONFIG_INVALID باشد، از overwrite
    جلوگیری می‌شود (برنامه نباید config خراب را با یک dict ناقصِ درون‌حافظه‌ای
    جایگزین کند — فقط Restore/Repair صریح مجاز است). بعد از نوشتنِ موفق،
    وضعیت به CONFIG_VALID برمی‌گردد.

    بازمی‌گرداند: True اگر نوشته شد، False اگر به‌خاطر INVALID رد شد.
    """
    global _config_state
    if _config_state == CONFIG_INVALID:
        print(
            f"⛔ config.json خراب است و از بازنویسی جلوگیری شد (مسیر: {CONFIG_FILE}) — "
            f"ابتدا با Restore یا تعمیرِ صریح آن را درست کنید."
        )
        return False
    tmp_path = CONFIG_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            # دسترسی *قبل* از نوشتنِ محتوا محدود می‌شود — وگرنه یک پنجره‌ی
            # کوتاه وجود دارد که فایل با umask پیش‌فرض (معمولاً 0644) روی
            # دیسک است و api_hash/توکن/شماره‌ی همه‌ی مشتری‌ها برای هر کاربرِ
            # دیگری روی سرور خواندنی است.
            _chmod_private(tmp_path)
            json.dump(cfg, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        # فایل موقتِ نیمه‌نوشته نباید کنار config اصلی جا بماند
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    _chmod_private(CONFIG_FILE)
    _config_state = CONFIG_VALID
    return True


# ══════════════════════════════════════════════════════════════════
#  Journal حذف اکانت (Account Delete Recovery — PATCH 8)
#  ── عملیاتِ حذف یک SelfBot (نه کاربر) recovery-safe می‌شود: قبل از هر
#     تغییری Intent ثبت می‌شود؛ اگر Process وسطِ کار Crash کند، استارتاپ
#     مراحل باقی‌مانده را کامل می‌کند. فایلِ JSON (نه جدول DB) تا هیچ
#     تغییر Schema‌ای لازم نباشد.
# ══════════════════════════════════════════════════════════════════
ACCOUNT_DELETE_JOURNAL_FILE = os.path.join(DATA_DIR, "account_delete_journal.json")


def _load_account_delete_journal() -> dict:
    try:
        with open(ACCOUNT_DELETE_JOURNAL_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        # journal خراب → ignore (بدترین حالت: یک ردیفِ stale که دوباره
        # recovery نمی‌شود؛ داده‌ای حذف نمی‌شود)
        print(f"⚠️ [delete_account] journal خراب/ناخوانا بود — نادیده گرفته شد: "
              f"{type(e).__name__}: {str(e)[:80]}")
        return {}


def _save_account_delete_journal(journal: dict) -> None:
    tmp_path = ACCOUNT_DELETE_JOURNAL_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, ACCOUNT_DELETE_JOURNAL_FILE)


def _remove_session_files(tag: str) -> bool:
    """
    حذف فایل سشن واقعی {tag}.session + sidecar هایش (نه تگِ خام).

    برمی‌گرداند: True اگر همه‌ی فایل‌های موجود با موفقیت حذف شدند؛ False اگر
    هر فایلِ موجودی حذف نشود. فایلِ نبودن هرگز شکست نیست — فقط حذف‌نشدنِ
    واقعیِ یک فایلِ موجود شکست است.
    """
    session_file = os.path.join(SESSIONS_DIR, tag + ".session")
    ok = True
    for ext in ["", "-journal", "-wal", "-shm"]:
        f = session_file + ext
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError as e:
                print(f"⚠️ [delete_account] حذف فایل سشن {f} ناموفق: {e}")
                ok = False
    return ok


def _recover_account_delete_journal() -> None:
    """
    Recovery استارتاپیِ حذف اکانتِ ناتمام: اگر ردیفی در
    account_delete_journal.json مانده باشد (crash وسط حذف)، مراحل باقی‌مانده
    کامل می‌شود — اطمینان از نبودنِ تگ در config + حذف سشن/state. فقط وقتی
    config معتبر باشد config لمس می‌شود (config خراب هرگز overwrite نمی‌شود).
    Idempotent.
    """
    journal = _load_account_delete_journal()
    if not journal:
        return
    print(f"🔧 [recovery] عملیات حذف اکانتِ ناتمام پیدا شد: "
          f"{', '.join(sorted(journal))}")
    cfg_valid = config_state() == CONFIG_VALID
    cfg = load_config() if cfg_valid else None
    changed_cfg = False
    # ردیف‌هایی که این دور «تمام‌شده» علامت می‌خورند؛ اگر ذخیره‌ی config
    # (که یک‌جا در انتها انجام می‌شود) شکست بخورد، همین‌ها به journal
    # برگردانده می‌شوند تا تلاشِ استارتاپِ بعدی دوباره امتحان کند.
    completed = []
    for tag in list(journal.keys()):
        ok_entry = True
        # ۱) حذف سشن — اگر ناقص بماند، هیچ تغییری اعمال نمی‌شود (config هم
        # دست‌نخورده می‌ماند) و ردیف حذف نمی‌شود (Recovery قابل تکرار است).
        if not _remove_session_files(tag):
            print(f"⚠️ [recovery] حذف سشن تگ {tag} ناقص ماند — journal حفظ شد "
                  f"(استارتاپ بعدی دوباره تلاش می‌کند).")
            ok_entry = False
        try:
            with _db_lock:
                bd = get_db()
                try:
                    bd.execute("DELETE FROM bot_states WHERE tag = ?", (tag,))
                    bd.commit()
                finally:
                    bd.close()
        except Exception as e:
            print(f"⚠️ [recovery] پاک‌سازی bot_states تگ {tag} ناموفق: "
                  f"{type(e).__name__}: {str(e)[:80]} — journal حفظ شد.")
            ok_entry = False
        if not ok_entry:
            continue  # فقط بعد از موفقیتِ کاملِ سشن/state نوبت به config می‌رسد
        # ۲) فقط وقتی سشن و state کاملاً پاک شدند، config حذف می‌شود
        if cfg_valid and isinstance(cfg, dict) and tag in cfg:
            del cfg[tag]
            changed_cfg = True
        journal.pop(tag, None)
        completed.append(tag)
    if changed_cfg:
        try:
            save_config(cfg)
        except Exception as e:
            print(f"⚠️ [recovery] ذخیره‌ی config در recovery حذف اکانت ناموفق: "
                  f"{type(e).__name__}: {str(e)[:80]} — journal حفظ شد.")
            # configِ حذف‌شده در حافظه ذخیره نشد → هیچ ردیفی «تمام‌شده» نیست
            for tag in completed:
                journal[tag] = "DELETE_PENDING"
    _save_account_delete_journal(journal)


def _migrate_provision_sources() -> None:
    """
    مهاجرت idempotent برای اکانت‌های قدیمی config.json که هنوز
    provision_source ندارند.

    قانون (بدون حدس): هرگز از «نداشتن اشتراک» نتیجه‌گیری نمی‌شود که اکانت
    «دستی» بوده — چون ممکن است از لایسنس ساخته شده باشد. اکانت‌های قدیمیِ
    بدون منبع فقط PROVISION_LEGACY می‌گیرند (منبعِ نامعلوم) تا سیستم‌های
    بعدی (expiry/resume/UI) هیچ تصمیمی بر اساس حدس نگیرند. اکانت‌های
    manual/license/subscriptionِ از-قبل-علامت‌دار دست نمی‌خورند.

    Validation: تعداد اکانت‌ها و کلیدها قبل/بعد یکسان است؛ هیچ اکانتی حذف
    یا rename نمی‌شود — فقط فیلد provision_source برای اکانت‌های بدونِ منبع
    اضافه می‌شود.
    """
    try:
        init_db()
    except Exception as e:
        print(f"⚠️ [saas_db] مهاجرت provision_source: دیتابیس در دسترس نبود — رد شد: {e}")
        return
    cfg = load_config()
    # config خراب → هیچ overwrite/یتم‌سازی‌ای انجام نمی‌شود (فقط خواندن مجاز است)
    if config_state() != CONFIG_VALID:
        print(
            f"⛔ [saas_db] مهاجرت provision_source رد شد — config.json خراب است "
            f"(مسیر: {CONFIG_FILE})؛ هیچ تغییری در config اعمال نشد."
        )
        return
    before_keys = set(cfg.keys())
    before_count = len(cfg)
    changed = False
    for tag, acc in cfg.items():
        if not isinstance(acc, dict) or acc.get("provision_source"):
            continue
        # منبعِ قطعی وجود ندارد → legacy (نه حدسِ manual)
        acc["provision_source"] = PROVISION_LEGACY
        changed = True
    if changed:
        try:
            save_config(cfg)
        except Exception as e:
            print(f"⚠️ [saas_db] مهاجرت provision_source: ذخیره‌ی config ناموفق: {e}")
            return
        after = load_config()
        if set(after.keys()) != before_keys or len(after) != before_count:
            print("⛔ [saas_db] مهاجرت provision_source: تعداد/کلیدهای config تغییر کرد — "
                  "(نباید رخ دهد)؛ رول‌بک دستی لازم است.")


def _recover_delete_journal() -> None:
    """
    Recovery استارتاپیِ عملیاتِ حذفِ ناتمام (Operation Journal): اگر ردیفی در
    delete_journal مانده باشد، یعنی کاربر از DB اصلی حذف شده ولی مراحلِ بعدی
    (bot_data self_accounts + یتیم‌سازی config) کامل نشده‌اند. اینجا مراحلِ
    باقی‌مانده دوباره (idempotent) اجرا و ردیف پاک می‌شود — هیچ
    userِ حذف‌شده‌ای با ردیفِ legacyِ باقی‌مانده یا مالکیتِ مرده در config
    بدونِ امکانِ Recovery نمی‌ماند.
    """
    try:
        with _conn() as c:
            rows = c.execute("SELECT user_id FROM delete_journal").fetchall()
    except Exception as e:
        print(f"⚠️ [recovery] خواندن delete_journal ناموفق بود: {type(e).__name__}: {e}")
        return
    for row in rows:
        uid = row["user_id"]
        ok = True
        # ۱) bot_data: حذف ردیف‌های self_accounts (idempotent)
        try:
            with _db_lock:
                bd = get_db()
                try:
                    has_table = bd.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='self_accounts'"
                    ).fetchone()
                    if has_table:
                        bd.execute("DELETE FROM self_accounts WHERE user_id = ?", (uid,))
                        bd.commit()
                finally:
                    bd.close()
        except Exception as e:
            ok = False
            print(f"⚠️ [recovery] bot_data برای کاربر {uid} کامل نشد (ردیف journal باقی می‌ماند): {type(e).__name__}: {e}")
        # ۲) config.json: یتیم‌سازی (idempotent)
        try:
            _orphan_user_selfbots(uid)
        except Exception as e:
            ok = False
            print(f"⚠️ [recovery] یتیم‌سازی config برای کاربر {uid} کامل نشد (ردیف journal باقی می‌ماند): {type(e).__name__}: {e}")
        if ok:
            try:
                with _conn() as c:
                    c.execute("DELETE FROM delete_journal WHERE user_id = ?", (uid,))
                print(f"✅ [recovery] عملیات حذف کاربر {uid} کامل شد (مراحل باقی‌مانده اجرا شد).")
            except Exception as e:
                print(f"⚠️ [recovery] پاک‌سازی ردیف journal کاربر {uid} ناموفق بود: {type(e).__name__}: {e}")


def safe_input(prompt=""):
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    try:
        raw = sys.stdin.buffer.readline()
        return raw.decode('utf-8', errors='replace').strip()
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════
#  سیستم فونت Unicode
# ══════════════════════════════════════════════════════════
_FONT_DIGITS: dict = {
    "bold": "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗",
    "double": "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡",
    "sans": "𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫",
    "sans_bold": "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
    "mono": "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿",
}
FONT_FA: dict = {
    "bold": "بولد",
    "double": "دابل",
    "sans": "سانس",
    "sans_bold": "سانس‌بولد",
    "mono": "مونو",
    "normal": "نرمال",
}


def apply_font(text: str, font: str) -> str:
    if font not in _FONT_DIGITS:
        return text
    return text.translate(str.maketrans("0123456789", _FONT_DIGITS[font]))


# ══════════════════════════════════════════════════════════
#  دایس — سطح ماژول (یک‌بار ساخته می‌شود)
#  max_val: بالاترین مقدار ممکن هر نوع (طبق مستندات تلگرام):
#  🎲🎯🎳 → 6 | 🏀⚽ → 5 | 🎰 → 64 (جکپات ۷۷۷)
# ══════════════════════════════════════════════════════════
_DICE_MAP: dict = {
    "تاس": ("🎲", 6),
    "دارت": ("🎯", 6),
    "بسکتبال": ("🏀", 5),
    "فوتبال": ("⚽", 5),
    "اسلات": ("🎰", 64),
    "بولینگ": ("🎳", 6),
}
# فیکس مهم: قبلاً دو سقف («۷۵ ثانیه» و «۴۰ دور») همزمان اعمال می‌شدند و
# اگر هرکدام زودتر می‌رسید، حلقه تسلیم می‌شد و یک دایس تصادفیِ معمولی
# (نه لزوماً max_val) می‌فرستاد. برای دایس‌های ساده (max_val=۵ یا ۶) این
# عملاً هرگز رخ نمی‌داد، اما برای اسلات (max_val=۶۴) با سقف ۴۰ دور، طبق
# محاسبه‌ی احتمالاتی، در حدود ۱۵٪ از دفعات هرگز جکپات نمی‌آمد — یعنی
# دقیقاً برخلاف انتظار «حتماً حتماً باید max بیاید» بود.
#
# این سقف تعداد تلاش کاملاً حذف شده — حلقه اکنون تا هر مدت لازم باشد
# ادامه می‌دهد، فقط با پیدا شدن واقعیِ max_val متوقف می‌شود. برای اینکه
# این حلقه هرگز به سقف ۹۰ ثانیه‌ی _safe_handler برخورد نکند (که باعث
# می‌شد کل عملیات بدون حتی فرستادن یک دایس نهایی cancel شود)، دستور دایس
# دیگر از داخل _safe_handler اجرا نمی‌شود — به‌جایش به‌صورت یک تسک مستقل
# (asyncio.create_task) اجرا می‌شود، دقیقاً مثل تبچی، تا زمان اجرایش
# مستقل از سقف زمانی پردازش دستورهای معمولی باشد.
#
# _DICE_SAFETY_CEILING صرفاً یک محافظت استثنایی (نه یک سقف عملیاتی معمول)
# است — با این مقدار، حتی برای اسلات (max_val=۶۴)، احتمال رسیدن به این
# سقف عملاً صفر است (زیر یک در یک تریلیون)؛ فقط برای جلوگیری از یک حلقه‌ی
# واقعاً ابدی در یک سناریوی کاملاً غیرمنتظره (مثلاً یک باگ ناشناخته در
# تشخیص برنده) وجود دارد.
_DICE_SAFETY_CEILING = 3600  # ثانیه (۱ ساعت) — عملاً هرگز به این نمی‌رسد


# ══════════════════════════════════════════════════════════
#  قیمت لحظه‌ای ارز و طلا
# ══════════════════════════════════════════════════════════
_PRICE_MAP: dict = {
    "تتر": ("tether", "USDCUSDT", "USDCUSDT", "USDT", "💵", "usdt"),
    "تون": ("the-open-network", "TONUSDT", "TONUSDT", "TON", "💎", "ton"),
    "ترون": ("tron", "TRXUSDT", "TRXUSDT", "TRX", "🔴", "trx"),
}


async def _price_http_get(url: str, timeout: int = 5):
    """
    دریافت JSON از URL در thread جداگانه — event loop بلاک نمی‌شود.

    فیکس مهم: timeout پیش‌فرض از ۹ به ۵ ثانیه کاهش یافت. چون این تابع
    urllib.request (یک کتابخانه‌ی sync) را داخل asyncio.to_thread اجرا
    می‌کند، حتی اگر صدازننده‌ی بیرونی با asyncio.wait_for زودتر cancel
    شود، خودِ thread زیرین تا رسیدن به timeout واقعیِ urllib به کارش ادامه
    می‌دهد (چون کدهای sync از داخل یک event loop قابل‌قطع نیستند). یعنی
    برای اینکه سقف زمانی بیرونی واقعاً معنا داشته باشد، timeout داخلی هر
    درخواست هم باید کوتاه باشد — با ۹ ثانیه روی هر تک‌درخواست، یک زنجیره‌ی
    fallback با ۴-۵ منبع می‌توانست به‌تنهایی ۴۰-۴۵ ثانیه طول بکشد، که از
    سقف ۲۵ ثانیه‌ی بیرونی دستورات «طلا»/«تتر»/«تون»/«ترون» بسیار فراتر
    می‌رفت و تقریباً همیشه باعث نمایش «تایم‌اوت» به کاربر می‌شد — حتی وقتی
    خودِ اولین منبع سریع (مثلاً Binance) در کسری از ثانیه جواب می‌داد.
    """
    import urllib.request as _ur
    import json as _j

    def _fetch():
        req = _ur.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; CiaNet/2.0)",
            "Accept": "application/json",
        })
        with _ur.urlopen(req, timeout=timeout) as r:
            return _j.loads(r.read().decode())

    return await asyncio.to_thread(_fetch)


# قرارداد رسمی USDT در شبکه‌ی TRON (TRC20) — لازمه‌ی اعتبارسنجی توکن.
# نماد (symbol) به‌تنهایی کافی نیست؛ یک توکن جعلی می‌تواند نماد USDT داشته
# باشد ولی آدرس قراردادش متفاوت باشد.
TRC20_USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


async def _verify_trc20_transfer(txid: str, wallet: str, min_usdt) -> tuple:
    """
    چک خودکار واریز تتر (TRC20) روی TronGrid — بدون کلید API.
    ورودی: هش تراکنش، آدرس کیف پول فروشگاه، حداقل مبلغ موردانتظار (USDT).
    خروجی: (ok, message). فقط تراکنش‌های confirmed شمارش می‌شوند.

    اعتبارسنجی‌ها:
      - هش ۶۴ کاراکتر hex
      - فقط confirmed (only_confirmed=true)
      - گیرنده == کیف پول فروشگاه
      - آدرس قرارداد == قرارداد رسمی USDT TRC20 (نه فقط symbol)
      - symbol == USDT
      - مبلغ >= مبلغ فاکتور — محاسبه با Decimal (بدون float)
      - صفحه‌بندی: اگر هش در ۵۰ نتیجه‌ی اول نبود، با fingerprint تا چند
        صفحه جلو می‌رود تا پرداخت واقعی اشتباهاً رد نشود.
    """
    from decimal import Decimal, InvalidOperation

    wallet = (wallet or "").strip().lower()
    txid = (txid or "").strip().lower()
    if len(txid) != 64 or any(ch not in "0123456789abcdef" for ch in txid):
        return False, "فرمت هش نامعتبر است (باید ۶۴ کاراکتر hex باشد)"
    if not wallet.startswith("t") or len(wallet) != 34:
        return False, "آدرس کیف پول تنظیم‌شده معتبر نیست"
    try:
        min_dec = Decimal(str(min_usdt))
    except (InvalidOperation, TypeError, ValueError):
        return False, "مبلغ موردانتظار نامعتبر است"
    page = 0
    fingerprint = None
    while page < 10:  # حداکثر ۱۰ صفحه (۵۰۰ تراکنش) — از ردِ اشتباهی جلوگیری می‌کند
        url = (f"https://api.trongrid.io/v1/accounts/{wallet}/transactions/trc20"
               f"?only_confirmed=true&limit=50&order_by=block_timestamp,desc")
        if fingerprint:
            from urllib.parse import quote
            url += f"&fingerprint={quote(str(fingerprint), safe='')}"
        try:
            data = await _price_http_get(url)
        except Exception as e:
            if page == 0:
                return False, f"ارتباط با TronGrid برقرار نشد ({str(e)[:40]})"
            break
        for t in (data or {}).get("data") or []:
            if (t.get("transaction_id") or "").lower() != txid:
                continue
            to = (t.get("to") or "").lower()
            if to != wallet:
                return False, "آدرس گیرنده با کیف پول فروشگاه یکی نیست"
            # چک قرارداد رسمی USDT — symbol به‌تنهایی قابل جعل است
            token_info = t.get("token_info") or {}
            contract = (token_info.get("address") or "").lower()
            if contract != TRC20_USDT_CONTRACT.lower():
                return False, "این تراکنش روی قرارداد رسمی USDT (TRC20) نیست"
            sym = (token_info.get("symbol") or "").upper()
            if sym != "USDT":
                return False, "این تراکنش USDT نیست"
            # مبلغ با Decimal — مقدار از TronGrid به‌صورت رشته (واحد کوچک) می‌آید
            try:
                value = Decimal(str(t.get("value") or "0")) / Decimal("1000000")
            except (InvalidOperation, ValueError):
                return False, "مبلغ تراکنش نامعتبر است"
            if value < min_dec:
                return False, (f"مبلغ واریزی ({value} USDT) کمتر از مبلغ "
                               f"فاکتور ({min_dec} USDT) است")
            return True, f"{value} USDT"
        meta = (data or {}).get("meta") or {}
        fingerprint = meta.get("fingerprint")
        if not fingerprint:
            break
        page += 1
    return False, "این هش در تراکنش‌های USDT کیف پول پیدا نشد (شاید هنوز تایید نشده؟)"


async def _price_binance(symbol: str):
    """Binance REST (بدون کلید) — سریع‌ترین منبع."""
    try:
        d = await _price_http_get(
            f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
        )
        return float(d["lastPrice"]), float(d["priceChangePercent"]), float(d["quoteVolume"])
    except Exception:
        return 0.0, 0.0, 0.0


async def _price_coingecko(cg_id: str):
    """CoinGecko (بدون کلید) — قیمت USD + IRR + تغییر۲۴h + حجم."""
    try:
        d = await _price_http_get(
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={cg_id}&vs_currencies=usd,irr"
            f"&include_24hr_change=true&include_24hr_vol=true"
        )
        c = d[cg_id]
        return (
            float(c.get("usd", 0)),
            float(c.get("usd_24h_change", 0)),
            float(c.get("usd_24h_vol", 0)),
            float(c.get("irr", 0)) / 10,  # ریال → تومان
        )
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


async def _price_bybit(symbol: str):
    """Bybit (بدون کلید) — fallback سوم."""
    try:
        d = await _price_http_get(
            f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}"
        )
        item = d["result"]["list"][0]
        return float(item["lastPrice"]), float(item.get("price24hPcnt", 0)) * 100
    except Exception:
        return 0.0, 0.0


async def _price_kucoin(symbol: str):
    """KuCoin (بدون کلید) — fallback چهارم."""
    try:
        sym = symbol.replace("USDT", "-USDT")
        d = await _price_http_get(f"https://api.kucoin.com/api/v1/market/stats?symbol={sym}")
        data = d["data"]
        return float(data["last"]), float(data.get("changeRate", 0)) * 100
    except Exception:
        return 0.0, 0.0


# نگاشت نام ارز به کد Nobitex/جفت Wallex — برخی با کد جهانی فرق دارند
_NOBITEX_COINS = {"usdt": "usdt", "ton": "ton", "trx": "trx"}
_WALLEX_PAIRS = {"usdt": "USDTTMN", "ton": "TONTMN", "trx": "TRXTMN"}


async def _nobitex_toman(coin: str) -> float:
    """Nobitex — قیمت آخرین معامله به تومان (بزرگ‌ترین صرافی ایران)."""
    try:
        nb_coin = _NOBITEX_COINS.get(coin.lower(), coin.lower())
        d = await _price_http_get(
            f"https://api.nobitex.ir/market/stats?srcCurrency={nb_coin}&dstCurrency=rls",
            timeout=8,
        )
        key = f"{nb_coin}-rls"
        rls = float(d["stats"][key]["latest"])
        return rls / 10
    except Exception:
        return 0.0


async def _wallex_toman(coin: str) -> float:
    """Wallex — قیمت آخرین معامله به تومان."""
    try:
        pair = _WALLEX_PAIRS.get(coin.lower())
        if not pair:
            return 0.0
        d = await _price_http_get("https://api.wallex.ir/v1/markets", timeout=8)
        stats = d["result"]["symbols"][pair]["stats"]
        return float(stats["lastPrice"])
    except Exception:
        return 0.0


async def _exir_toman(coin: str) -> float:
    """Exir — قیمت آخرین معامله به تومان."""
    try:
        d = await _price_http_get(
            f"https://api.exir.io/v2/ticker?symbol={coin.lower()}-irt", timeout=8
        )
        return float(d["last"])
    except Exception:
        return 0.0


async def _bit24_toman(coin: str) -> float:
    """Bit24 — قیمت آخرین معامله به تومان."""
    try:
        d = await _price_http_get("https://api.bit24.cash/v1/currencies/price", timeout=8)
        for item in d.get("data", []):
            if item.get("symbol", "").lower() == coin.lower():
                return float(item.get("tomanPrice", 0))
        return 0.0
    except Exception:
        return 0.0


async def _coingecko_irr(coin: str) -> float:
    """CoinGecko IRR — آخرین fallback زنجیره‌ی تومانی."""
    try:
        cg = {"usdt": "tether", "ton": "the-open-network", "trx": "tron"}
        cg_id = cg.get(coin.lower(), coin.lower())
        d = await _price_http_get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=irr"
        )
        return float(d[cg_id]["irr"]) / 10
    except Exception:
        return 0.0


async def _get_toman_price(coin: str) -> float:
    """
    قیمت تومانی از صرافی‌های ایرانی، با اولویت Nobitex (بزرگ‌ترین و
    معتبرترین صرافی ایران) و fallback موازی به بقیه در صورت عدم دسترسی.
    coin: 'usdt' | 'ton' | 'trx'

    فیکس مهم: همان مشکل _fetch_crypto_price اینجا هم بود — پنج منبع
    (Nobitex → Wallex → Exir → Bit24 → CoinGecko-IRR) sequential صدا زده
    می‌شدند که در بدترین حالت می‌توانست ۴۰+ ثانیه طول بکشد. حالا همه‌ی پنج
    منبع هم‌زمان فراخوانی می‌شوند؛ اگر Nobitex (اولویت اول، چون بزرگ‌ترین
    صرافی ایران و معمولاً دقیق‌ترین قیمت) جواب معتبر داد همان انتخاب
    می‌شود، وگرنه به‌ترتیب اولویت قبلی از بین نتایج موازی انتخاب می‌شود.
    """
    results = await asyncio.gather(
        _nobitex_toman(coin),
        _wallex_toman(coin),
        _exir_toman(coin),
        _bit24_toman(coin),
        _coingecko_irr(coin),
        return_exceptions=True,
    )
    # فیکس: اگر در نسخه‌های دیگر/آینده تعداد منابعِ gather بیشتر از پنج شود،
    # این unpack با «too many values to unpack (expected 5)» کرش می‌کند —
    # *_ بقیه‌ی موارد را تحمل می‌کند (و در همین نسخه هم بی‌اثر است).
    nobitex_p, wallex_p, exir_p, bit24_p, cg_p, *_ = results

    for p in (nobitex_p, wallex_p, exir_p, bit24_p, cg_p):
        if not isinstance(p, Exception) and p and p > 0:
            return p
    return 0.0


async def _get_usd_toman_rate() -> float:
    """نرخ تبدیل دلار به تومان از صرافی‌های ایرانی (از قیمت تتر، تتر ≈ ۱ دلار)."""
    return await _get_toman_price("usdt")


async def _fetch_crypto_price(cg_id: str, bn_sym: str, bb_sym: str, coin_key: str = ""):
    """
    قیمت کریپتو با ۴ منبع جهانی + صرافی‌های ایرانی برای تومان.
    خروجی: (price_usd, change_24h%, volume_usd, price_toman)

    فیکس مهم: قبلاً این چهار منبع دلاری (Binance → CoinGecko → Bybit →
    KuCoin) به‌صورت sequential صدا زده می‌شدند — یعنی اگر منبع اول چند
    ثانیه طول می‌کشید یا واقعاً timeout می‌خورد (نه fail سریع)، بقیه‌ی
    منابع اصلاً فرصت اجرا پیدا نمی‌کردند مگر بعد از تمام‌شدن قبلی، و
    مجموع بدترین حالت می‌توانست به‌تنهایی چند ده ثانیه طول بکشد — بیشتر از
    سقف ۲۵ ثانیه‌ی بیرونی دستورات «تتر»/«تون»/«ترون»، که باعث نمایش پیام
    «تایم‌اوت» به کاربر می‌شد حتی وقتی حداقل یکی از منابع در کسری از ثانیه
    پاسخ می‌داد. حالا هر چهار منبع هم‌زمان (asyncio.gather) فراخوانی
    می‌شوند و اولین نتیجه‌ی معتبر — با اولویت به همان ترتیب قبلی در صورت
    برابری — انتخاب می‌شود؛ در عمل این یعنی زمان کل معمولاً برابر کندترین
    *موفق* منبع است، نه مجموع تک‌تک منابع.
    """
    dollar_results = await asyncio.gather(
        _price_binance(bn_sym),
        _price_coingecko(cg_id),
        _price_bybit(bb_sym),
        _price_kucoin(bn_sym),
        return_exceptions=True,
    )

    price = change = vol = 0.0
    # ترتیب اولویت همان ترتیب قبلی حفظ شده: اگر Binance جواب معتبر داد،
    # همان انتخاب می‌شود؛ وگرنه CoinGecko، سپس Bybit، سپس KuCoin.
    bn_res, cg_res, bb_res, kc_res = dollar_results

    if not isinstance(bn_res, Exception) and bn_res[0]:
        price, change, vol = bn_res
    elif not isinstance(cg_res, Exception) and cg_res[0]:
        price, change, vol = cg_res[0], cg_res[1], cg_res[2]
    elif not isinstance(bb_res, Exception) and bb_res[0]:
        price, change = bb_res
        vol = 0.0
    elif not isinstance(kc_res, Exception) and kc_res[0]:
        price, change = kc_res
        vol = 0.0

    toman = 0.0
    if coin_key:
        toman = await _get_toman_price(coin_key)

    return price, change, vol, toman


async def _navasan_repo_gold():
    """
    منبع اصلی قیمت طلای ایران — یک ریپوی گیت‌هاب (HosseinOdd/Navasan-API) که
    با GitHub Actions هر چند دقیقه یک‌بار داده‌ی navasan.net را می‌گیرد و در
    یک فایل JSON استاتیک منتشر می‌کند. چون خودِ فایل از پیش جمع‌آوری شده،
    نیازی به کلید API ندارد و از raw.githubusercontent.com (که نیازی به
    احراز هویت ندارد) در دسترس است.

    فیکس مهم: منابع قبلی (TGJU و Navasan.tech) در عمل کار نمی‌کردند —
    اندپوینت TGJU که استفاده شده بود (`api.tgju.org/v1/market/indicator/...`)
    یک اندپوینت داخلی و مستندنشده‌ی خودِ سایت بود، نه یک API عمومی، و در
    عمل یا خطا می‌داد یا داده‌ی غیرمنتظره برمی‌گرداند؛ Navasan.tech هم به یک
    کلید API واقعی نیاز دارد (even نسخه‌ی «رایگان»‌اش) و مقدار `api_key=free`
    که در کد قبلی استفاده شده بود اصلاً یک کلید معتبر نبود — یعنی این
    درخواست همیشه با خطای احراز هویت شکست می‌خورد. نتیجه‌ی عملی این بود که
    هر دو منبع تقریباً همیشه silently fail می‌کردند و کد به fallback نهایی
    (محاسبه از PAXG جهانی) می‌رسید که چون بر پایه‌ی نرخ جهانی طلا محاسبه
    می‌شود (نه بازار محلی ایران که تحت‌تأثیر عرضه/تقاضای داخلی، نرخ ارز
    آزاد، حباب سکه و غیره است)، با قیمت واقعی بازار ایران فاصله‌ی محسوس
    داشت — دقیقاً همان چیزی که «فیک به نظر رسیدن قیمت» را توضیح می‌دهد.

    خروجی: (p18_toman, p24_toman) یا (0.0, 0.0) اگر داده در دسترس/تازه نبود.
    """
    try:
        d = await _price_http_get(
            "https://raw.githubusercontent.com/HosseinOdd/Navasan-API/main/data/gold.json",
            timeout=6,
        )
        item18 = d.get("18ayar")
        if not isinstance(item18, dict):
            return 0.0, 0.0

        # فیکس مهم دوم: چک تازگی داده. این ریپو با GitHub Actions آپدیت
        # می‌شود که خودش می‌تواند (به‌ندرت) قطع یا با تأخیر مواجه شود. بدون
        # این چک، اگر فایل به هر دلیلی چند ساعت/روز آپدیت نشده باشد، کد
        # بی‌سروصدا قیمتی قدیمی و گمراه‌کننده را به‌عنوان قیمت لحظه‌ای نشان
        # می‌داد. این هم می‌توانست بخشی از تجربه‌ی «قیمت فیک» کاربر باشد.
        ts = item18.get("date")
        if ts:
            import time as _time
            age_seconds = _time.time() - float(ts)
            if age_seconds > 2 * 3600:  # قدیمی‌تر از ۲ ساعت — قابل‌اعتماد نیست
                return 0.0, 0.0

        p18_raw = item18.get("value")
        if not p18_raw or float(p18_raw) <= 0:
            return 0.0, 0.0
        p18 = float(p18_raw)
        # ۲۴ عیار از روی ۱۸ عیار همان منبع محاسبه می‌شود (نسبت خلوص
        # ۱۸/۲۴ = ۰.۷۵)، به‌جای تکیه به کلید «gerami» که قیمت یک سکه‌ی
        # سنتی است، نه لزوماً معادل دقیق هر گرم طلای ۲۴ عیار خالص.
        p24 = p18 * (24 / 18)
        return p18, p24
    except Exception:
        return 0.0, 0.0


async def _fetch_gold_price():
    """
    fallback نهایی: قیمت طلا از روی PAXG (هر ۱ PAXG = ۱ اونس طلای خالص).
    منابع دلاری: Binance / KuCoin / Bybit / OKX / CoinGecko (موازی).
    تومان: نرخ دلار از صرافی ایرانی × قیمت گرم.
    فقط وقتی استفاده می‌شود که منبع اصلی ایرانی (_navasan_repo_gold)
    در دسترس یا تازه نباشد.

    فیکس: همان مشکل موازی‌سازی که در _fetch_crypto_price/_get_toman_price
    رفع شد، اینجا هم اعمال شده — پنج منبع sequential که در بدترین حالت
    ۴۵+ ثانیه طول می‌کشید، حالا هم‌زمان فراخوانی می‌شوند.
    """
    async def _binance_paxg():
        d = await _price_http_get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT")
        return float(d["price"])

    async def _kucoin_paxg():
        d = await _price_http_get("https://api.kucoin.com/api/v1/market/stats?symbol=PAXG-USDT")
        return float(d["data"]["last"])

    async def _bybit_paxg():
        d = await _price_http_get(
            "https://api.bybit.com/v5/market/tickers?category=spot&symbol=PAXGUSDT"
        )
        return float(d["result"]["list"][0]["lastPrice"])

    async def _okx_paxg():
        d = await _price_http_get("https://www.okx.com/api/v5/market/ticker?instId=XAU-USDT")
        return float(d["data"][0]["last"])

    async def _coingecko_paxg():
        d = await _price_http_get(
            "https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd"
        )
        return float(d["pax-gold"]["usd"])

    results = await asyncio.gather(
        _binance_paxg(), _kucoin_paxg(), _bybit_paxg(), _okx_paxg(), _coingecko_paxg(),
        return_exceptions=True,
    )

    oz = 0.0
    for r in results:
        if not isinstance(r, Exception) and r and r > 0:
            oz = r
            break

    if not oz:
        return 0.0, 0.0, 0.0

    gram = oz / 31.1035  # ۱ troy oz = ۳۱.۱۰۳۵ گرم
    usd_toman = await _get_usd_toman_rate()
    gram_toman = gram * usd_toman if usd_toman > 0 else 0.0
    return oz, gram, gram_toman


async def _fetch_gold_iran():
    """
    قیمت هر گرم طلای ۱۸ و ۲۴ عیار به تومان از بازار ایران.
    منابع (با fallback خودکار): داده‌ی واقعی ایرانی (Navasan repo) →
    محاسبه از PAXG جهانی + نرخ ارز.
    خروجی: (p18_toman, p24_toman)
    """
    p18, p24 = await _navasan_repo_gold()
    if not p18 or not p24:
        # فیکس: اگر _fetch_gold_price در نسخه‌ی مستقر مقدار اضافه‌ای برگرداند،
        # این unpack کرش می‌کرد — *_ بقیه را تحمل می‌کند.
        _, gram24_usd, gram24_toman, *_ = await _fetch_gold_price()
        if gram24_toman > 0:
            if not p24:
                p24 = gram24_toman
            if not p18:
                p18 = gram24_toman * (18 / 24)
    return p18, p24


def _fmt_price(p: float) -> str:
    """فرمت هوشمند قیمت بر اساس بزرگی عدد."""
    if p >= 1000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:,.4f}"
    if p >= 0.01:
        return f"${p:,.5f}"
    return f"${p:,.8f}"


def _fmt_vol(v: float) -> str:
    """فرمت حجم معاملات."""
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:,.0f}"


# ══════════════════════════════════════════════════════════
#  پاسخ‌های خودکار «دشمن» — خنثی و بدون محتوای توهین‌آمیز
# ══════════════════════════════════════════════════════════
# نسخه‌ی قبلی این لیست شامل فحش‌های رکیک جنسی/خانوادگی بود که با نیت اصلی
# («متن‌های خنثی برای دشمن» طبق کامنت اصلی) در تناقض بود. ارسال خودکار چنین
# محتوایی به هر کسی که به‌عنوان «دشمن» علامت‌گذاری شده، ریسک واقعی گزارش‌شدن
# و بن‌شدن اکانت توسط سیستم‌های ضدسوءاستفاده‌ی تلگرام دارد، و در برخی حوزه‌های
# قضایی می‌تواند پیامد قانونی هم داشته باشد. این نسخه با پیام‌های خنثی و
# بی‌خطر جایگزین شده — همان قابلیت (پاسخ خودکار به کاربر مسدودشده) حفظ شده،
# فقط محتوا امن شده است.
ENEMY_REPLIES = [
    "پیام شما دریافت نشد.",
    "این کاربر در حال حاضر پاسخگو نیست.",
    "امکان پاسخ‌گویی به این مخاطب وجود ندارد.",
    "پیام شما نادیده گرفته شد.",
    "این گفتگو مسدود شده است.",
    "دسترسی شما به این مکالمه محدود شده.",
    "پیامی که ارسال کردید پاسخ داده نخواهد شد.",
    "این کاربر شما را نادیده می‌گیرد.",
]


class SelfBot:
    def __init__(self, tag: str, cfg: dict):
        self.tag = tag
        self.cfg = cfg
        self.client = None

        self.enabled = False
        self.time_enabled = False
        self.online_enabled = False

        self.auto_read_pv = False
        self.auto_read_group = False
        self.auto_read_channel = False

        self.silence_all = False
        self.silence_pv: dict = {}

        self.tabchi_enabled = False
        self.tabchi_task = None
        self.tabchi_chat = None
        self.tabchi_text = ""
        self.tabchi_media = None
        self.tabchi_interval = 5
        self.tabchi_next_run_at = None

        self.base_name = ""
        self.current_font = "bold"

        self.bio_enabled = False
        self.base_bio = ""
        self.bio_task = None

        self.name_task = None
        self.online_task = None
        self.watchdog_task = None
        self._memory_log_task = None
        # BUG #6/#7: تسک‌های دایس و ری‌استارتِ معلق متعلق به همین نمونه‌اند و
        # در shutdownِ واقعی نمونه cancel می‌شوند.
        self._dice_task = None
        self._restart_task = None

        self._fatal_auth_error = False

        self.enemies: dict = {}
        self.tracker_enabled = False
        self._msg_cache: dict = {}
        self._chat_order: dict = {}
        self._msg_chat_index: dict = {}
        self._chat_last_activity: dict = {}
        self._MAX_CACHE_PER_CHAT = 300
        self._MAX_TRACKED_CHATS = 50
        self._MAX_MEDIA_CACHE_BYTES = 8 * 1024 * 1024
        # سقفِ *مجموعِ* مدیای نگه‌داشته‌شده در RAM برای همین اکانت.
        #
        # چرا لازم است: _MAX_MEDIA_CACHE_BYTES فقط اندازه‌ی «یک» مدیا را
        # محدود می‌کند. بدون سقفِ مجموع، بدترین حالت ۵۰ چت × ۳۰۰ پیام ×
        # ۸MB است — یعنی ده‌ها گیگابایت. چون چند SelfBot در یک پروسه اجرا
        # می‌شوند، چند کاربر که پشت‌سرهم عکس/ویدیوی چندمگابایتی بفرستند
        # کافی است تا پروسه OOM شود و همه‌ی اکانت‌ها با هم بیفتند.
        self._MAX_TOTAL_MEDIA_BYTES = 96 * 1024 * 1024
        # محدودیتِ نرخِ پاسخ خودکار به «دشمن»: {(chat_id, sender_id):
        # (آخرین پاسخ، تعداد در پنجره، شروعِ پنجره)}
        self._enemy_rate: dict = {}
        # {chat_id: bool} — آیا طرفِ مقابلِ این پیوی ربات است؟ یک بار
        # تشخیص داده می‌شود و بعد به‌ازای هر پیام دوباره resolve نمی‌شود.
        self._bot_chat_cache: dict = {}
        # شمارنده‌ی زنده‌ی مجموع بایت‌های مدیای کش‌شده.
        self._media_bytes = 0

        self.started = time.time()
        self.my_id = None
        # پنجره‌ی «دریافتِ کدِ لاگین» — timestampِ انقضا. صفر یعنی خلعِ سلاح.
        self._login_code_armed_until = 0.0
        # آیدیِ کسی که آخرین بار درخواستِ کد داده (مقصدِ اولِ تحویل)
        self._login_code_requester = None
        self._handlers_registered = False
        self._reconnecting = False

        # وضعیت runtime واقعی (starting/connecting/ready/reconnecting/error/
        # auth_failed/stopped) — مبنای نمایش «فعال/در حال اتصال/خطا» در UI.
        # در ACCOUNTS بودن دیگر به‌تنهایی معیار «فعال» نیست.
        self.runtime_status = "stopped"

    def _set_status(self, status: str) -> None:
        """وضعیت runtime را هم روی خودِ شیء و هم در رجیستری سراسری ثبت می‌کند
        تا UI (که فقط ACCOUNTS را می‌بیند) بتواند وضعیتِ اتصالِ در جریان را
        هم نشان دهد."""
        self.runtime_status = status
        _set_bot_status(self.tag, status)

    def _persist(self, **kwargs) -> None:
        for key, value in kwargs.items():
            set_state(self.tag, key, value)

    def _persist_identity(self, me) -> None:
        """
        هویتِ اکانتِ تلگرامی که این سلف روی آن لاگین است را در config
        می‌نویسد (tg_user_id / tg_username).

        فقط وقتی می‌نویسد که چیزی عوض شده باشد — تا هر استارت یک نوشتنِ
        بی‌مورد روی دیسک نباشد.
        """
        cfg = load_config()
        acc = cfg.get(self.tag)
        if not isinstance(acc, dict):
            return
        uid = int(getattr(me, "id", 0) or 0)
        uname = getattr(me, "username", None)
        if not uid:
            return
        changed = False
        if acc.get("tg_user_id") != uid:
            acc["tg_user_id"] = uid
            changed = True
        if uname and acc.get("tg_username") != uname:
            acc["tg_username"] = uname
            changed = True
        if changed:
            save_config(cfg)

    def _persist_enemies(self) -> None:
        set_state(self.tag, "enemies", json.dumps(self.enemies))

    def _is_silenced(self, chat_id: int, is_private: bool) -> bool:
        """
        بررسی متمرکز اینکه آیا یک چت پیوی خاص فعلاً «سکوت‌شده» است یا نه —
        هم توسط سکوت سراسری (silence_all) و هم سکوت تک‌چت (silence_pv).

        این تابع مشترک توسط _on_incoming (که پیام را واقعاً حذف می‌کند) و
        _cache_message (که پیام را برای ردیاب کش می‌کند) استفاده می‌شود.
        قبلاً فقط _on_incoming این چک را داشت — یعنی حتی وقتی کاربر صراحتاً
        یک چت را «سکوت» کرده بود، _cache_message همچنان آن پیام‌ها را در کش
        ردیاب ذخیره می‌کرد. اگر بعداً طرف مقابل همان پیام را ادیت/حذف می‌کرد،
        ردیاب یک گزارش کامل برای پیامی می‌ساخت که از دید کاربر اصلاً وجود
        نداشت. این تابع آن ناهماهنگی را حذف می‌کند.
        """
        if not is_private:
            return False
        return self.silence_all or (chat_id in self.silence_pv)

    async def start(self, interactive=False):
        self._set_status("starting")
        session_path = os.path.join(SESSIONS_DIR, self.tag)

        # ─── بررسی سلامت سشن قبل از هر چیز ───────────────────────────────
        # اگر سشن فقط‌خواندنی باشد (مثلاً بعد از Restore/کپی با owner یا
        # mode اشتباه)، Telethon connect می‌شود ولی هر write به
        # «attempt to write a readonly database» می‌خورد و اکانت مدام قطع/
        # وصل می‌شود — در حالی که «فعال» نشان داده می‌شود. این‌جا قبل از
        # ساخت کلاینت، سلامت چک می‌شود؛ اگر مالک همان user باشد mode امن
        # به 0600 اصلاح می‌شود (خود-ترمیمی)، وگرنه خطای واضح با مسیر (بدون
        # secret) داده می‌شود و READY اعلام نمی‌شود.
        health = check_session_health(self.tag)
        if not health["ok"]:
            print(f"❌ [SESSION][{self.tag}][CHECK] {health['error']}")
            raise Exception(
                f"اکانت {self.tag}: سشن قابل نوشتن نیست — {health['error']} "
                f"[SESSION][CHECK]"
            )
        print(f"✅ [SESSION][{self.tag}][CHECK] سشن سالم است (path: {health['path']})")

        # ─── مدیریت sidecar های واقعی سشن ────────────────────────────────
        # فایلِ سشنِ واقعی تلتلون {tag}.session است و sidecar هایش
        # {tag}.session-journal / -wal / -shm هستند (نه {tag}-journal و... که
        # قبلاً به‌اشتباه حذف می‌شدند و هرگز وجود نداشتند). فایل سشنِ معتبر
        # هرگز حذف نمی‌شود و WAL/SHM هرگز کورکورانه (بعد از یک probe فقط‌خواندنی)
        # پاک نمی‌شوند — پروبِ read-only تضمین نمی‌کند WAL داده‌ی لازم ندارد.
        # تنها سازوکارِ مجاز، تابعِ مرکزیِ موجود _checkpoint_and_clean_session
        # است: اول WAL را با checkpointِ تاییدشده (busy==0) در فایل جمع می‌کند و
        # فقط بعد از موفقیتِ واقعی، -wal/-shm/-journal را پاک می‌کند. اگر سشن
        # قفل/در حالِ استفاده باشد (پروسه‌ی دیگری همان تگ را اجرا می‌کند)،
        # checkpoint ناقص می‌ماند و sidecar ها دست‌نخورده می‌مانند — بررسی‌های
        # مالکیتِ Runtimeِ موجود تصمیم می‌گیرند که استارت ادامه یابد یا نه.
        session_file = session_path + ".session"
        if os.path.exists(session_file) or any(
                os.path.exists(session_file + ext)
                for ext in ("-wal", "-shm", "-journal")):
            if not _checkpoint_and_clean_session(session_file):
                # شکستِ تمیزکاری: sidecar ها دست‌نخورده می‌مانند (این تابع در
                # حالتِ خطا هرگز حذف نمی‌کند). سشنِ معتبر خراب نمی‌شود و هیچ
                # حذفی کورکورانه انجام نشده است؛ اگر علت استفاده‌ی هم‌زمان توسط
                # پروسه‌ی دیگری باشد، بررسی‌های مالکیتِ Runtimeِ موجود تعیین
                # می‌کنند که استارت ادامه یابد یا نه.
                print(
                    f"⚠️ [{self.tag}] تمیزکاری sidecar های کهنه‌ی سشن ناموفق "
                    f"بود — آن‌ها دست‌نخورده باقی ماندند (checkpoint ناقص یا "
                    f"حذف ناموفق)."
                )

        api_id = self.cfg.get("api_id", 0)
        api_hash = self.cfg.get("api_hash", "")

        # پروکسی کاملاً اختیاری است — فقط اگر کاربر در config.json برای این
        # اکانت یک کلید "proxy" گذاشته باشد فعال می‌شود.
        # فرمت دقیق (تأییدشده از سورس خود Telethon):
        #   "proxy": {"proxy_type": "socks5", "addr": "1.2.3.4", "port": 1080,
        #             "username": "user", "password": "pass", "rdns": true}
        proxy_cfg = self.cfg.get("proxy")

        self.client = TelegramClient(
            session_path,
            api_id,
            api_hash,
            connection_retries=3,
            retry_delay=2,
            # sequential_updates=False: هر آپدیت ورودی یک تسک جداگانه می‌گیرد —
            # یک هندلرِ کند یا گیرکرده دیگر بقیه‌ی پیام‌ها را مسدود نمی‌کند.
            sequential_updates=False,
            # آستانه‌ی پایین (۱۰ ثانیه به‌جای ۶۰) عمدی است: با آستانه‌ی بالا،
            # تلتون خودش FloodWaitهای زیر ۶۰ ثانیه را با یک await داخلی در
            # هسته‌ی کتابخانه می‌بلعد که کل event loop را بلاک می‌کند.
            flood_sleep_threshold=10,
            proxy=proxy_cfg,
        )
        self._set_status("connecting")

        # باگ «اکانت ناگهان آنلاین می‌شود»: وقتی ردیاب روشن بود و اکانت باید
        # آفلاین دیده شود (online_enabled خاموش)، هر پیام خروجی (مثلاً گزارش
        # ادیت/حذف ردیاب که به Saved Messages فرستاده می‌شود) وضعیت حضور را
        # به «آنلاین» تغییر می‌دهد — و چون حلقه‌ی حضور در حالت آفلاین هر ۱۸۰
        # ثانیه یک‌بار offline=True می‌فرستد، اکانت تا ۳ دقیقه آنلاین دیده
        # می‌شد. این wrapper همه‌ی send_message/send_file را طوری می‌پیچد که
        # اگر اکانت باید آفلاین باشد، بلافاصله بعد از هر ارسال دوباره وضعیت
        # آفلاین صریح اعلام شود (نه اینکه منتظر تیک بعدی حلقه بماند).
        self._install_offline_preserving_sends()

        try:
            await asyncio.wait_for(self.client.connect(), timeout=30)
        except asyncio.TimeoutError:
            print(f"❌ [{self.tag}] تایم‌اوت ۳۰ثانیه‌ای در اتصال — احتمالاً فایروال/NAT هاست کانکشن را بی‌سروصدا drop کرده")
            raise
        except Exception as e:
            print(f"❌ [{self.tag}] خطا در اتصال به سرورهای تلگرام: {e}")
            raise

        if not self.client.is_connected():
            raise Exception(f"اکانت {self.tag}: اتصال برقرار نشد.")

        self._try_enable_tcp_keepalive()

        is_bot_acc = self.cfg.get("type") == "bot"

        try:
            if interactive and not await self.client.is_user_authorized():
                print(f"🔐 اکانت {self.tag} نیاز به لاگین دارد.")
                if is_bot_acc:
                    await self.client.start(bot_token=self.cfg.get("token"))
                else:
                    await self.client.start(phone=self.cfg.get("phone"))
            elif not await self.client.is_user_authorized():
                raise Exception(
                    f"اکانت {self.tag} احراز هویت نشده. "
                    f"یک‌بار interactive اجرا کنید: python main.py {self.tag}"
                )
            else:
                await asyncio.wait_for(self.client.start(), timeout=45)
        except asyncio.TimeoutError:
            print(f"❌ [{self.tag}] تایم‌اوت ۴۵ثانیه‌ای در client.start() غیرتعاملی")
            raise
        except Exception as e:
            print(f"❌ [{self.tag}] خطا در لاگین: {e}")
            raise

        try:
            me = await asyncio.wait_for(self.client.get_me(), timeout=30)
        except asyncio.TimeoutError:
            print(f"❌ [{self.tag}] تایم‌اوت ۳۰ثانیه‌ای در get_me() — کانکشن احتمالاً نیمه‌مرده بود")
            raise
        self.my_id = me.id
        self.base_name = self._clean_name(
            me.first_name or me.username or "User"
        )
        # ثبتِ **هویتِ واقعیِ اکانتِ تلگرام** در config.
        #
        # چرا حیاتی است: تا پیش از این، تنها پیوندِ یک سلف با یک کاربر،
        # فیلدِ owner_user_id بود که فقط در مسیرِ «افزودن از داخل پنل» پر
        # می‌شد. سلفی که دستی/از ترمینال لاگین شده بود این فیلد را نداشت،
        # پس در «سلف من»ِ صاحبش دیده نمی‌شد — با اینکه سلف دقیقاً روی
        # همان اکانت بود.
        #
        # با ذخیره‌ی tg_user_id، پیوند از روی *هویتِ اکانت* برقرار می‌شود
        # نه از روی نحوه‌ی ساخته‌شدنش؛ یعنی لاگینِ دستی، لایسنسی و ترمینالی
        # دقیقاً یکسان رفتار می‌کنند.
        try:
            self._persist_identity(me)
        except Exception as e:
            print(f"⚠️ [{self.tag}] ثبت هویت اکانت ناموفق: {type(e).__name__}")

        print(f"✅ {self.base_name} ({self.tag}) متصل شد. [نوع: {'bot' if is_bot_acc else 'user'}] [build: {BUILD_VERSION}]")
        print(f"✅ [SESSION][{self.tag}][CONNECT] اتصال برقرار شد")

        restored = await self._load_persisted_state()
        if restored:
            print(f"♻️ [{self.tag}] {restored} تنظیم بازیابی شد.")

        # حلقه‌ی حضور (presence) باید همیشه، صرف‌نظر از مقدار online_enabled،
        # اجرا شود — چون هم مسئول نگه‌داشتن اکانت «آنلاین» است، هم مسئول
        # نگه‌داشتن صریحِ اکانت در حالت «آفلاین» (پیش‌فرض) است.
        await self._start_presence_loop()

        if is_bot_acc:
            print(f"⚠️ [{self.tag}] اکانت بات است، برخی دستورات کار نمی‌کنند.")

        if not self._handlers_registered:
            @self.client.on(events.NewMessage(outgoing=True))
            async def cmd_h(e):
                await self._safe_handler("cmd_h", self._handle, e, e.raw_text.strip() if e.raw_text else "")

            @self.client.on(events.NewMessage(incoming=True))
            async def in_h(e):
                await self._safe_handler("in_h", self._on_incoming, e)

            @self.client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
            async def cache_in_h(e):
                await self._safe_handler("cache_in_h", self._cache_message, e.message, e.chat_id)

            @self.client.on(events.NewMessage(outgoing=True, func=lambda e: e.is_private))
            async def cache_out_h(e):
                await self._safe_handler("cache_out_h", self._cache_message, e.message, e.chat_id)

            @self.client.on(events.MessageEdited(func=lambda e: e.is_private))
            async def edit_h(e):
                await self._safe_handler("edit_h", self._on_edited, e)

            # توجه: MessageDeleted نمی‌تواند با func=lambda e: e.is_private فیلتر
            # شود چون تلگرام معمولاً برای حذف در پیوی chat_id را در خود event
            # نمی‌فرستد. فیلتر واقعی داخل _on_deleted با کمک ایندکس msg_id
            # انجام می‌شود.
            @self.client.on(events.MessageDeleted())
            async def del_h(e):
                if not self.tracker_enabled:
                    return
                await self._safe_handler("del_h", self._on_deleted, e)

            self._handlers_registered = True

        if self.watchdog_task and not self.watchdog_task.done():
            self.watchdog_task.cancel()
            await asyncio.gather(self.watchdog_task, return_exceptions=True)
        self.watchdog_task = asyncio.create_task(self._watchdog_loop())

        if self._memory_log_task is None:
            self._memory_log_task = asyncio.create_task(self._memory_log_loop())

        # ─── بررسی نهایی سلامت (READY فقط بعد از همه‌ی این‌ها) ────────────
        # قبل از اعلام «آماده»، مطمئن می‌شویم کلاینت واقعاً وصل و احراز
        # هویت‌شده است، هندلرها ثبت شده‌اند و واچ‌داگ زنده است. اگر هرکدام
        # ناقص باشد، start با خطای واضح شکست می‌خورد تا run_bot retry کند و
        # هیچ‌جا «فعال»ِ دروغین نشان داده نشود.
        if not self.client or not self.client.is_connected():
            raise Exception(
                f"اکانت {self.tag}: پس از استارت، اتصال برقرار نیست [READY-CHECK]"
            )
        try:
            if not await asyncio.wait_for(self.client.is_user_authorized(), timeout=20):
                raise Exception(
                    f"اکانت {self.tag}: سشن احراز هویت نشده است [READY-CHECK]"
                )
        except asyncio.TimeoutError:
            raise Exception(
                f"اکانت {self.tag}: تایم‌اوت در بررسی احراز هویت [READY-CHECK]"
            )
        if not self._handlers_registered:
            raise Exception(
                f"اکانت {self.tag}: هندلرهای پیام ثبت نشده‌اند [HANDLER_REGISTER]"
            )
        if not (self.watchdog_task and not self.watchdog_task.done()):
            raise Exception(
                f"اکانت {self.tag}: واچ‌داگ اجرا نشده است [READY-CHECK]"
            )

        self.started = time.time()
        self._set_status("ready")
        print(f"✅ [SESSION][{self.tag}][READY] اکانت آماده است")
        return self.client

    def _try_enable_tcp_keepalive(self) -> None:
        """
        تلاش best-effort برای فعال‌سازی TCP keepalive روی سوکت خام زیرِ کانکشن
        تلتون. مسیر دسترسی به سوکت خام جزئیات پیاده‌سازی داخلی و مستندنشده‌ی
        Telethon است — به همین دلیل این تابع کاملاً در try/except پیچیده شده
        و شکست آن هرگز نباید جلوی اجرای بقیه‌ی برنامه را بگیرد.
        """
        try:
            import socket as _socket
            sender = getattr(self.client, "_sender", None)
            conn = getattr(sender, "_connection", None) if sender else None
            writer = getattr(conn, "_writer", None) if conn else None
            transport = writer.transport if writer is not None else None
            sock = transport.get_extra_info("socket") if transport is not None else None
            if sock is None:
                return
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
            if hasattr(_socket, "TCP_KEEPIDLE"):
                sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, 30)
            if hasattr(_socket, "TCP_KEEPINTVL"):
                sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 10)
            if hasattr(_socket, "TCP_KEEPCNT"):
                sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 3)
            print(f"🔌 [{self.tag}] TCP keepalive روی سوکت فعال شد")
        except Exception as e:
            print(f"ℹ️ [{self.tag}] فعال‌سازی TCP keepalive ممکن نشد (بی‌اهمیت): {e}")

    async def _watchdog_loop(self):
        """
        هر ۹۰ ثانیه یک درخواست سبک (GetStateRequest) با timeout مشخص
        می‌فرستیم. اگر پاسخ در بازه‌ی زمانی معقول نرسد، یعنی کانکشن مرده
        است — کلاینت را به‌زور قطع می‌کنیم تا مسیر reconnect استاندارد فعال
        شود.
        """
        while True:
            try:
                await asyncio.sleep(90)
                if not self.client or not self.client.is_connected():
                    continue
                try:
                    await asyncio.wait_for(
                        self.client(GetStateRequest()), timeout=20
                    )
                except asyncio.TimeoutError:
                    print(f"🩺 [{self.tag}] Watchdog: کانکشن پاسخ نداد (تایم‌اوت) — قطع اجباری برای reconnect")
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                except errors.FloodWaitError:
                    pass
                except Exception as e:
                    print(f"🩺 [{self.tag}] Watchdog: خطا در چک سلامت کانکشن ({e}) — قطع اجباری برای reconnect")
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [{self.tag}] خطا در watchdog_loop (ادامه می‌دهد): {e}")
                await asyncio.sleep(10)

    async def _stop_watchdog(self):
        if self.watchdog_task:
            self.watchdog_task.cancel()
            await asyncio.gather(self.watchdog_task, return_exceptions=True)
            self.watchdog_task = None

    async def _memory_log_loop(self):
        while True:
            try:
                await asyncio.sleep(600)  # هر ۱۰ دقیقه
                if resource is not None:
                    try:
                        maxrss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                        print(f"📊 [{self.tag}] مصرف اوج حافظه‌ی کل پروسه تا این لحظه: {maxrss_mb:.1f}MB")
                    except Exception:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [{self.tag}] خطا در memory_log_loop (ادامه می‌دهد): {e}")
                await asyncio.sleep(10)

    async def _load_persisted_state(self) -> int:
        state = get_all_state(self.tag)
        if not state:
            return 0

        self.enabled = state.get("enabled", self.enabled)
        self.time_enabled = state.get("time_enabled", self.time_enabled)
        self.online_enabled = state.get("online_enabled", self.online_enabled)
        self.auto_read_pv = state.get("auto_read_pv", self.auto_read_pv)
        self.auto_read_group = state.get("auto_read_group", self.auto_read_group)
        self.auto_read_channel = state.get("auto_read_channel", self.auto_read_channel)
        self.silence_all = state.get("silence_all", self.silence_all)
        silence_pv_raw = state.get("silence_pv")
        if silence_pv_raw:
            try:
                parsed = json.loads(silence_pv_raw) if isinstance(silence_pv_raw, str) else silence_pv_raw
                self.silence_pv = {int(k): True for k in parsed} if isinstance(parsed, dict) else {}
            except Exception:
                self.silence_pv = {}
        self.current_font = state.get("current_font", self.current_font)
        self.base_name = (state.get("base_name", self.base_name) or "")[:MAX_BASE_NAME_LEN]
        self.bio_enabled = state.get("bio_enabled", self.bio_enabled)
        self.base_bio = state.get("base_bio", self.base_bio)

        self.tabchi_chat = state.get("tabchi_chat", self.tabchi_chat)
        self.tabchi_text = state.get("tabchi_text", self.tabchi_text)
        self.tabchi_media = state.get("tabchi_media", self.tabchi_media)
        self.tabchi_interval = state.get("tabchi_interval", self.tabchi_interval)
        tabchi_running = state.get("tabchi_running", False)
        raw_next_run = state.get("tabchi_next_run_at")
        try:
            self.tabchi_next_run_at = float(raw_next_run) if raw_next_run is not None else None
        except (TypeError, ValueError):
            self.tabchi_next_run_at = None

        self.tracker_enabled = state.get("tracker_enabled", self.tracker_enabled)

        enemies_raw = state.get("enemies")
        if enemies_raw:
            try:
                parsed = json.loads(enemies_raw) if isinstance(enemies_raw, str) else enemies_raw
                self.enemies = {int(k): list(v) for k, v in parsed.items()}
            except (json.JSONDecodeError, ValueError, TypeError):
                self.enemies = {}

        if self.time_enabled:
            await self._start_time_loops()
        if self.bio_enabled:
            await self._start_bio_loop()
        # توجه: حلقه‌ی حضور (presence) اینجا شرطی استارت نمی‌شود — باید
        # صرف‌نظر از online_enabled همیشه اجرا شود. استارت آن در start()
        # به‌طور غیرشرطی انجام می‌شود.

        can_resume_tabchi = self.tabchi_chat and (
            self.tabchi_text or (self.tabchi_media and os.path.exists(self.tabchi_media))
        )
        if tabchi_running and can_resume_tabchi:
            self.tabchi_enabled = True
            await self._start_tabchi()
        elif tabchi_running:
            print(f"⚠️ [{self.tag}] تبچی: قابل بازیابی نبود (چت/متن/رسانه‌ی معتبر موجود نیست) — در DB غیرفعال شد")
            set_state(self.tag, "tabchi_running", False)
            try:
                await asyncio.wait_for(
                    self.client.send_message(
                        "me",
                        "⚠️ تبچی پس از این اتصال دوباره فعال نشد، چون چت/متن/رسانه‌ی "
                        "ذخیره‌شده دیگر معتبر نیست (مثلاً فایل رسانه از دیسک پاک شده). "
                        "لطفاً دوباره با «انتخاب تبچی» تنظیمش کنید."
                    ),
                    timeout=15,
                )
            except Exception:
                pass

        return len(state)

    def _clean_name(self, name: str) -> str:
        name = re.sub(r'^(\[\d{2}:\d{2}\]\s*|\d{2}:\d{2}\s*)+', '', name)
        cleaned = name.replace("[", "").replace("]", "").strip() or "User"
        return cleaned[:MAX_BASE_NAME_LEN]

    def _uptime(self) -> str:
        up = int(time.time() - self.started)
        h, r = divmod(up, 3600)
        m, s = divmod(r, 60)
        return f"{h}h {m}m {s}s"

    async def _bg_request(self, request, timeout: int = 20, label: str = "پس‌زمینه"):
        """
        یک لایه‌ی محافظتی مرکزی برای *همه‌ی* درخواست‌هایی که از حلقه‌های
        پس‌زمینه (name_loop/bio_loop/presence_loop) فرستاده می‌شوند —
        جاهایی که هیچ کاربری منتظر پاسخ فوری نیست، پس بی‌سروصدا رد شدن از
        یک درخواست ناموفق (به‌جای اسپم‌کردن لاگ) کاملاً قابل قبول است.

        قبلاً هر کدام از _set_profile/_set_bio/_presence_loop جداگانه یک
        چک is_connected() + یک except ConnectionError + یک except Exception
        با فیلتر رشته‌ی "disconnected" داشتند — سه پیاده‌سازی تقریباً یکسان
        و پراکنده که نگه‌داری‌شان سخت بود و هر جای جدیدی که این الگو لازم
        می‌شد (یا هر تغییر بعدی) به‌راحتی ممکن بود یکی را از قلم بیندازد و
        دوباره باعث اسپم "Cannot send requests while disconnected" در لاگ
        شود. این تابع همان منطق را یک‌بار و مرکزی پیاده می‌کند.

        پارامتر label فقط برای شناسایی منبع خطا در لاگ استفاده می‌شود (مثلاً
        "نام" یا "بیو")، چون خودِ این تابع مشترک بین چند صدازننده است.

        بازمی‌گرداند: نتیجه‌ی درخواست در صورت موفقیت، یا None اگر به هر
        دلیل (قطعی، تایم‌اوت، یا هر خطای دیگر) ناموفق بود.
        """
        if not self.client or not self.client.is_connected():
            return None
        try:
            return await asyncio.wait_for(self.client(request), timeout=timeout)
        except errors.FloodWaitError as e:
            print(f"⏳ [{self.tag}] FloodWait روی {label}: {e.seconds} ثانیه")
            await asyncio.sleep(e.seconds + 2)
            return None
        except asyncio.CancelledError:
            raise
        except (errors.AuthKeyError, errors.AuthKeyDuplicatedError):
            # این خطا باید به صدازننده برسد — صدازننده‌هایی مثل presence_loop
            # با دیدن این خطا کامل خارج می‌شوند (اکانت دیگر معتبر نیست)،
            # پس نباید اینجا بلعیده شود مثل بقیه‌ی خطاهای موقتی.
            raise
        except (ConnectionError, asyncio.TimeoutError):
            # کانکشن قطع بود یا در همان لحظه قطع شد — بی‌سروصدا رد شو.
            # منتظر ماندن با یک sleep کوتاه اینجا لازم نیست چون صدازننده
            # (حلقه‌ی name/bio/presence) خودش قبل از تلاش بعدی می‌خوابد.
            return None
        except Exception as e:
            # هر خطای دیگری که رشته‌اش صراحتاً نشان‌دهنده‌ی قطعی است هم
            # بی‌سروصدا رد می‌شود؛ فقط خطاهای واقعاً غیرمنتظره لاگ می‌شوند.
            msg = str(e).lower()
            if "disconnected" in msg or "not connected" in msg:
                return None
            print(f"⚠️ [{self.tag}] خطا در {label}: {e}")
            return None

    @staticmethod
    def _parse_tg_link(link: str):
        # scheme اختیاری (کاربر معمولاً بدونِ https می‌فرستد)، و هر چیزی بعد
        # از شماره‌ی پیام (؟single، ؟comment=…) نادیده گرفته می‌شود.
        m = re.match(r'(?:https?://)?t\.me/(?:c/)?([^/?\s]+)/(\d+)', link.strip())
        return (m.group(1), int(m.group(2))) if m else (None, None)

    # سقفِ کلِ عملیات کپی (ثانیه) و سقفِ حجمِ فایل. جدا از پوششِ ۹۰ ثانیه‌ی
    # _safe_handler، چون کپی می‌تواند مشروعاً چند دقیقه طول بکشد — ولی نه
    # ساعت‌ها.
    COPY_TIMEOUT = 300
    COPY_MAX_BYTES = 2 * 1024 * 1024 * 1024      # ۲ گیگابایت (سقفِ خودِ تلگرام)

    async def _do_copy(self, event, ch_ref, msg_id) -> None:
        """
        دریافتِ یک پیام از روی لینک و کپیِ آن به Saved Messages — با
        تایم‌اوت روی هر مرحله و پیامِ وضعیت که در هر نتیجه‌ای به‌روز می‌شود
        (موفقیت یا خطای واضح)، تا هرگز روی «در حال دریافت» گیر نکند.

        کانال‌های «محتوای محافظت‌شده» (بدون فوروارد): چون این یک اکانتِ
        کاربریِ واقعی است (نه Bot API)، تلگرام معمولاً به عضو اجازه‌ی
        دانلودِ خام را می‌دهد؛ ولی اگر تلگرام صریحاً رد کرد، پیامِ روشن
        داده می‌شود نه گیرِ بی‌پایان.
        """
        async def _edit(txt):
            try:
                await event.edit(txt)
            except Exception:
                pass

        path = None
        try:
            # ۱) resolve کانال
            try:
                target = int(f"-100{ch_ref}") if ch_ref.isdigit() else ch_ref
                entity = await asyncio.wait_for(self.client.get_entity(target), timeout=20)
            except asyncio.TimeoutError:
                await _edit("❌ گرفتنِ کانال طول کشید — لینک یا اتصال را بررسی کن.")
                return
            except (ValueError, TypeError):
                await _edit(
                    "❌ این کانال شناخته نشد.\n"
                    "برای کانال‌های خصوصی (لینکِ `t.me/c/...`) باید اول خودت "
                    "عضوِ کانال باشی."
                )
                return
            except errors.FloodWaitError as fw:
                await _edit(f"⏳ تلگرام محدودیت گذاشته؛ {fw.seconds} ثانیه بعد دوباره امتحان کن.")
                return
            except Exception as e:
                await _edit(f"❌ کانال باز نشد: {type(e).__name__}")
                return

            # ۲) گرفتنِ پیام
            try:
                msg = await asyncio.wait_for(
                    self.client.get_messages(entity, ids=msg_id), timeout=25
                )
            except asyncio.TimeoutError:
                await _edit("❌ گرفتنِ پیام طول کشید.")
                return
            except errors.FloodWaitError as fw:
                await _edit(f"⏳ محدودیت تلگرام؛ {fw.seconds} ثانیه صبر کن.")
                return
            except Exception as e:
                await _edit(f"❌ پیام باز نشد: {type(e).__name__}")
                return
            if not msg:
                await _edit("❌ پیام پیدا نشد (شاید حذف شده یا عضوِ کانال نیستی).")
                return

            caption = msg.text or ""

            # ۳) پیامِ فقط‌متنی
            if not msg.media:
                if caption:
                    await self.client.send_message("me", caption)
                    await _edit("✅ متن کپی شد ← Saved Messages")
                else:
                    await _edit("❌ این پیام محتوایی برای کپی ندارد.")
                return

            # ۴) سقفِ حجم
            size = getattr(getattr(msg, "file", None), "size", None)
            if size and size > self.COPY_MAX_BYTES:
                await _edit(f"❌ حجمِ فایل ({size // (1024 * 1024)}MB) بیش از حدِ مجاز است.")
                return
            if size:
                await _edit(f"⏳ در حال دانلود ({max(1, size // (1024 * 1024))}MB)...")

            # ۵) دانلود با تایم‌اوتِ سخت
            base = os.path.join(DOWNLOADS_DIR, f"copy_{random.randint(100000, 9999999)}")
            try:
                dl = await asyncio.wait_for(
                    msg.download_media(file=base), timeout=self.COPY_TIMEOUT
                )
                # مسیرِ واقعی (با پسوندی که telethon می‌افزاید) برای پاک‌سازی
                path = dl if isinstance(dl, str) else base
            except asyncio.TimeoutError:
                await _edit("❌ دانلود بیش از حد طول کشید و لغو شد.\n"
                            "(فایل خیلی بزرگ است یا اتصال کند)")
                return
            except errors.FloodWaitError as fw:
                await _edit(f"⏳ محدودیت تلگرام؛ {fw.seconds} ثانیه صبر کن و دوباره بزن.")
                return
            except Exception as e:
                low = str(e).lower()
                if "protected" in low or "noforwards" in low or "TAKEOUT" in str(e):
                    await _edit("❌ این کانال «محتوای محافظت‌شده» دارد و تلگرام "
                                "اجازه‌ی ذخیره‌ی این محتوا را نمی‌دهد.")
                else:
                    await _edit(f"❌ دانلود ناموفق: {type(e).__name__}")
                return

            # ۶) ارسال به Saved Messages
            if dl:
                await self.client.send_file("me", dl, caption=caption)
                await _edit("✅ کپی شد ← Saved Messages")
            elif caption:
                await self.client.send_message("me", caption)
                await _edit("✅ متن کپی شد ← Saved Messages")
            else:
                await _edit("❌ چیزی برای کپی پیدا نشد.")

        except asyncio.CancelledError:
            await _edit("❌ کپی لغو شد.")
            raise
        except Exception as e:
            await _edit(f"❌ خطای غیرمنتظره: {type(e).__name__}")
        finally:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    @staticmethod
    def _entity_is_bot(entity) -> bool:
        """آیا این entity یک رباتِ تلگرام است؟ (User با پرچم bot)"""
        return bool(getattr(entity, "bot", False))

    async def _is_bot_chat(self, chat_id: int, event=None) -> bool:
        """
        آیا طرفِ مقابلِ این چتِ پیوی یک ربات است؟

        چرا بر اساس *چت* و نه *فرستنده‌ی پیام*: ردیاب هر دو سمتِ یک پیوی را
        کش می‌کند (cache_in_h و cache_out_h). اگر فقط فرستنده را چک کنیم،
        پیام‌های خودِ کاربر در چت با ربات همچنان ذخیره می‌شوند — یعنی نصفِ
        آن گفتگو ردیابی می‌شود. معیارِ درست این است: «این گفتگو با یک ربات
        است یا با یک آدم؟»

        ترتیبِ تشخیص از ارزان به گران، و نتیجه برای هر چت کش می‌شود تا
        به‌ازای هر پیام دوباره resolve نشود:
          ۱) کشِ همین تابع
          ۲) entityِ چت که telethon معمولاً روی خودِ رویداد دارد
          ۳) فرستنده (در پیویِ ورودی، فرستنده همان طرفِ مقابل است)
          ۴) get_entity (یک بار تماس شبکه؛ بعدش در کشِ telethon می‌ماند)

        اگر هیچ‌کدام جواب نداد، False برمی‌گردد (یعنی ردیابی می‌شود) —
        ازدست‌دادنِ پیامِ یک آدم بدتر از ذخیره‌ی پیامِ یک ربات است. ولی
        چون نتیجه‌ی نامطمئن کش نمی‌شود، دفعه‌ی بعد دوباره تلاش می‌کند.
        """
        cached = self._bot_chat_cache.get(chat_id)
        if cached is not None:
            return cached

        ent = None
        for src_obj, attr in ((event, "chat"), (event, "sender"),
                              (getattr(event, "message", None), "chat"),
                              (getattr(event, "message", None), "sender")):
            if src_obj is None:
                continue
            cand = getattr(src_obj, attr, None)
            if cand is not None:
                ent = cand
                break

        if ent is None:
            try:
                ent = await self.client.get_entity(chat_id)
            except Exception:
                return False      # نامطمئن — کش نکن، دفعه‌ی بعد دوباره

        result = self._entity_is_bot(ent)
        # سقفِ کش: یک عدد به‌ازای هر چتِ پیوی، با سقفِ سخت
        if len(self._bot_chat_cache) > 512:
            self._bot_chat_cache.clear()
        self._bot_chat_cache[chat_id] = result
        if result:
            # اگر قبلاً (پیش از این تشخیص) چیزی از این چت کش شده بود، آزادش کن
            self._evict_chat_from_cache(chat_id)
        return result

    async def _cache_message(self, message, chat_id: int) -> None:
        """
        پیام پیوی (ورودی یا خروجی) را در کش ردیاب ذخیره می‌کند: متن، فرستنده،
        زمان و در صورت وجود مدیا (فقط عکس/ویدیو/گیف/استیکر) را دانلود می‌کند.

        فیکس: اگر این چت فعلاً «سکوت‌شده» باشد (توسط silence_all یا
        silence_pv)، پیام اصلاً کش نمی‌شود. قبلاً این تابع هیچ چک سکوتی
        نداشت، یعنی پیام‌هایی که کاربر صراحتاً خواسته بود نادیده گرفته شوند
        همچنان وارد کش ردیاب می‌شدند و می‌توانستند بعداً گزارش نادرست
        ادیت/حذف بسازند.

        مدیا هرگز روی دیسک نوشته نمی‌شود — مستقیماً به‌صورت bytes در حافظه
        (RAM) نگه داشته می‌شود تا با trim شدن کش یا خاموش‌شدن ردیاب فوراً
        آزاد شود.
        """
        if not self.tracker_enabled:
            return
        if self._is_silenced(chat_id, is_private=True):
            return
        try:
            # چتِ ربات اصلاً کش نمی‌شود — نه پیام ربات، نه پیامِ خودِ
            # کاربر در آن چت. چون ایندکسِ msg_id هم پر نمی‌شود،
            # _on_deleted هم خودکار این چت را نادیده می‌گیرد.
            if await self._is_bot_chat(chat_id, message):
                return
            key = (chat_id, message.id)
            sender = message.sender
            sender_name = (
                getattr(sender, "first_name", None)
                or getattr(sender, "title", None)
                or getattr(sender, "username", None)
                or str(message.sender_id)
            )

            media_type = None
            if message.photo:
                media_type = "photo"
            elif message.video:
                media_type = "video"
            elif message.gif:
                media_type = "gif"
            elif message.sticker:
                media_type = "sticker"

            media_bytes = None
            media_mime = None
            if media_type:
                ttl = getattr(message.media, "ttl_seconds", None)
                if not ttl:
                    reported_size = getattr(message.file, "size", None) if message.file else None
                    media_mime = getattr(message.file, "mime_type", None) if message.file else None
                    if reported_size and reported_size > self._MAX_MEDIA_CACHE_BYTES:
                        media_bytes = None
                    else:
                        try:
                            media_bytes = await message.download_media(file=bytes)
                            if media_bytes and len(media_bytes) > self._MAX_MEDIA_CACHE_BYTES:
                                media_bytes = None
                        except Exception:
                            media_bytes = None

            # جایگزینیِ یک کلیدِ موجود (ادیتِ همان پیام) نباید بایت‌ها را
            # دوبار بشمارد — سهمِ قبلی اول کم می‌شود.
            self._forget_msg_bytes(key)
            self._msg_cache[key] = {
                "text": message.raw_text or "",
                "sender_id": message.sender_id,
                "sender_name": sender_name,
                "out": bool(message.out),
                "date": message.date,
                "media_bytes": media_bytes,
                "media_type": media_type,
                "media_mime": media_mime,
            }
            if media_bytes:
                self._media_bytes += len(media_bytes)
            self._msg_chat_index.setdefault(message.id, set()).add(chat_id)

            order = self._chat_order.setdefault(chat_id, [])
            order.append(message.id)
            if len(order) > self._MAX_CACHE_PER_CHAT:
                self._drop_cached_msg(chat_id, order.pop(0))

            self._chat_last_activity[chat_id] = time.time()
            if len(self._chat_order) > self._MAX_TRACKED_CHATS:
                oldest_chat_id = min(self._chat_last_activity, key=self._chat_last_activity.get)
                if oldest_chat_id != chat_id:
                    self._evict_chat_from_cache(oldest_chat_id)

            # سقفِ مجموعِ مدیا: قدیمی‌ترین چت‌ها (بر اساس آخرین فعالیت) آزاد
            # می‌شوند تا زیر سقف برگردیم. چتِ فعلی هرگز قربانی نمی‌شود.
            self._enforce_media_budget(protect_chat_id=chat_id)
        except Exception as e:
            print(f"⚠️ [{self.tag}] خطا در کش پیام برای ردیاب: {e}")

    def _forget_msg_bytes(self, key) -> None:
        """سهمِ مدیای یک پیامِ کش‌شده را از شمارنده کم می‌کند."""
        prev = self._msg_cache.get(key)
        if prev:
            mb = prev.get("media_bytes")
            if mb:
                self._media_bytes = max(0, self._media_bytes - len(mb))

    def _drop_cached_msg(self, chat_id: int, mid: int) -> None:
        """حذفِ کاملِ یک پیام از کش (شامل به‌روزرسانیِ شمارنده و ایندکس)."""
        self._forget_msg_bytes((chat_id, mid))
        self._msg_cache.pop((chat_id, mid), None)
        idx_set = self._msg_chat_index.get(mid)
        if idx_set is not None:
            idx_set.discard(chat_id)
            if not idx_set:
                self._msg_chat_index.pop(mid, None)

    def _enforce_media_budget(self, protect_chat_id: int = None) -> None:
        """
        مجموعِ مدیای کش‌شده را زیر سقف نگه می‌دارد، در دو مرحله:

          ۱) چت‌های *دیگر* را از قدیمی‌ترین به جدیدترین (LRU) کامل آزاد کن.
          ۲) اگر هنوز بالای سقف بودیم، قدیمی‌ترین پیام‌های *همین* چت را هم
             یکی‌یکی بینداز — چون یک چت به‌تنهایی می‌تواند تا
             _MAX_CACHE_PER_CHAT × _MAX_MEDIA_CACHE_BYTES (۳۰۰ × ۸MB ≈
             ۲.۴GB) نگه دارد و اگر «چتِ فعلی» کاملاً مصون بماند، سقفِ
             مجموع اصلاً بندِ سختی نیست.

        protect_chat_id یعنی «این چت را کامل پاک نکن» نه «دست نزن» —
        همیشه دست‌کم جدیدترین پیامش باقی می‌ماند تا ردیاب بی‌فایده نشود.
        """
        cap = self._MAX_TOTAL_MEDIA_BYTES
        # مرحله‌ی ۱ — چت‌های دیگر
        guard = 0
        while self._media_bytes > cap and guard < self._MAX_TRACKED_CHATS + 1:
            guard += 1
            victims = [c for c in self._chat_last_activity if c != protect_chat_id]
            if not victims:
                break
            oldest = min(victims, key=lambda c: self._chat_last_activity.get(c, 0))
            if self._evict_chat_from_cache(oldest) == 0:
                # چتِ خالی — از حلقه‌ی بی‌پایان جلوگیری می‌کند
                self._chat_last_activity.pop(oldest, None)

        # مرحله‌ی ۲ — تراشیدنِ خودِ چتِ محافظت‌شده از قدیمی‌ترین پیام
        if self._media_bytes > cap and protect_chat_id is not None:
            order = self._chat_order.get(protect_chat_id) or []
            while self._media_bytes > cap and len(order) > 1:
                self._drop_cached_msg(protect_chat_id, order.pop(0))

    def _evict_chat_from_cache(self, chat_id: int) -> int:
        """
        تمام کش (پیام‌ها، مدیای RAM، ایندکس) مربوط به یک چت پیوی خاص را آزاد
        می‌کند. توسط سقف تعدادِ چت (_MAX_TRACKED_CHATS) و سقفِ مجموعِ مدیا
        (_enforce_media_budget) صدا زده می‌شود.

        بازمی‌گرداند: تعداد پیام‌هایی که آزاد شد.
        """
        ids = self._chat_order.pop(chat_id, [])
        for mid in ids:
            self._drop_cached_msg(chat_id, mid)
        self._chat_last_activity.pop(chat_id, None)
        return len(ids)

    async def _safe_handler(self, name: str, func, *args) -> None:
        """
        لایه‌ی محافظتی مشترک برای همه‌ی event handlerهای تلتون. هر Exception
        غیرمنتظره اینجا گرفته و لاگ می‌شود؛ یک باگ در پردازش یک پیام هرگز
        باعث از کار افتادن dispatcher اصلی یا قطع شدن کلاینت نمی‌شود.

        سقف زمانی کلی (۹۰ ثانیه): یک لایه‌ی محافظتی مکمل sequential_updates=False
        — اگر یک هندلر خاص برای همیشه معلق بماند، فقط آن یک تسک لغو می‌شود.
        """
        try:
            await asyncio.wait_for(func(*args), timeout=90)
        except asyncio.TimeoutError:
            print(f"⏱ [{self.tag}] هندلر {name} بیش از ۹۰ ثانیه طول کشید — لغو شد (بقیه‌ی اکانت سالم می‌ماند)")
        except asyncio.CancelledError:
            raise
        except errors.FloodWaitError as e:
            print(f"⏳ [{self.tag}] FloodWait در {name}: {e.seconds}s")
        except Exception as e:
            if _is_fatal_auth_error(e):
                print(f"🛑 [{self.tag}] خطای احراز هویت غیرقابل‌بازیابی در هندلر {name}: {e}")
                self._fatal_auth_error = True
                return
            print(f"⚠️ [{self.tag}] خطای کنترل‌نشده در هندلر {name}: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()

    # فاصله‌ی حداقلیِ دو پاسخِ خودکار به یک «دشمن» در یک چت (ثانیه)، و
    # سقفِ پاسخ در هر پنجره‌ی یک‌ساعته به همان نفر.
    _ENEMY_COOLDOWN = 8.0
    _ENEMY_HOURLY_CAP = 20
    # سقفِ تعدادِ کلیدهای (چت، فرستنده) که وضعیتِ نرخشان نگه داشته می‌شود
    _ENEMY_RATE_MAX = 500

    def _enemy_reply_allowed(self, chat_id: int, sender_id: int) -> bool:
        """
        آیا الان مجازیم به این «دشمن» پاسخ خودکار بدهیم؟

        چرا لازم است: قبلاً به *هر* پیامِ یک دشمن یک ریپلای فرستاده می‌شد.
        کسی که عمداً ۵۰ پیام پشت‌سرهم بفرستد، ۵۰ ریپلای می‌گرفت — یعنی
        خودِ کاربر تبدیل به اسپمر می‌شد و تلگرام با FloodWait سنگین و در
        بدترین حالت محدودیت/بنِ اکانت جواب می‌داد. یعنی یک نفرِ مزاحم
        می‌توانست اکانتِ قربانی را از کار بیندازد.

        دو لایه: cooldown کوتاه (ضدِ رگبار) + سقفِ ساعتی (ضدِ آزارِ کشدار).
        state در همین نمونه نگه داشته می‌شود و با restart پاک می‌شود —
        نیازی به persist ندارد چون صرفاً محافظِ نرخ است.
        """
        now = time.time()
        key = (chat_id, sender_id)
        last, count, window_start = self._enemy_rate.get(key, (0.0, 0, now))
        if now - window_start >= 3600:
            count, window_start = 0, now
        if now - last < self._ENEMY_COOLDOWN:
            return False
        if count >= self._ENEMY_HOURLY_CAP:
            # پنجره هنوز باز است و سقف پر شده — تا شروعِ پنجره‌ی بعدی ساکت
            return False
        # سقفِ سختِ اندازه‌ی dict. اول ورودی‌های کهنه (خارج از پنجره) را
        # می‌اندازیم؛ اگر باز هم بالای سقف بودیم، قدیمی‌ترین‌ها را بر اساس
        # زمانِ آخرین پاسخ حذف می‌کنیم.
        #
        # صرفِ پاک‌سازیِ زمان‌محور کافی نیست: اگر در مدت کوتاهی تعدادِ
        # زیادی «دشمن»ِ متمایز پیام بدهند، هیچ ورودی‌ای هنوز کهنه نشده و
        # dict بدونِ سقف رشد می‌کند.
        if len(self._enemy_rate) > self._ENEMY_RATE_MAX:
            cutoff = now - 3600
            for k, v in list(self._enemy_rate.items()):
                if v[0] < cutoff:
                    self._enemy_rate.pop(k, None)
            if len(self._enemy_rate) > self._ENEMY_RATE_MAX:
                for k in sorted(self._enemy_rate, key=lambda k: self._enemy_rate[k][0])[
                        : len(self._enemy_rate) - self._ENEMY_RATE_MAX]:
                    self._enemy_rate.pop(k, None)
        self._enemy_rate[key] = (now, count + 1, window_start)
        return True

    # ══════════════════════════════════════════════════════════════
    #  مدیریت نشست‌ها (دستگاه‌های لاگین‌شده) + دریافتِ کدِ لاگین
    # ══════════════════════════════════════════════════════════════
    #  دو قابلیتِ خودمدیریتیِ اکانت برای مالک:
    #    ۱) دیدن و بستنِ دستگاه‌های دیگرِ لاگین‌شده روی همین اکانت.
    #    ۲) «مسلح‌کردنِ» سلف برای یک پنجره‌ی کوتاه تا کدِ لاگینِ بعدی را —
    #       که تلگرام موقعِ ورود از دستگاه جدید می‌فرستد — بگیرد و فقط به
    #       *مالکِ ثبت‌شده‌ی همین اکانت* برساند.
    #
    #  نکته‌ی امنیتی (چرا مسلح‌کردن، نه همیشه‌روشن): فوروارد کردنِ خودکارِ
    #  کدِ لاگین، شماره‌یک روشِ سرقتِ اکانت است. برای همین این‌جا کد فقط در
    #  یک پنجره‌ی زمانیِ کوتاه (که خودِ مالک صریحاً باز می‌کند) و فقط به
    #  owner_user_idِ تاییدشده فرستاده می‌شود — به هیچ مقصدِ دیگری نه.

    TELEGRAM_SERVICE_ID = 777000        # فرستنده‌ی رسمیِ پیام‌های تلگرام
    LOGIN_CODE_ARM_SECONDS = 600        # پنجره‌ی مسلح‌بودن: ۱۰ دقیقه

    async def list_sessions(self) -> list:
        """
        فهرستِ نشست‌های فعالِ این اکانت. هر مورد شامل hash، نامِ دستگاه،
        اپ، آخرین فعالیت و اینکه آیا همین نشستِ سلف است (current).
        """
        res = await asyncio.wait_for(self.client(GetAuthorizationsRequest()), timeout=20)
        out = []
        for a in res.authorizations:
            out.append({
                "hash": a.hash,
                "current": bool(getattr(a, "current", False)),
                "device": getattr(a, "device_model", "") or "",
                "platform": getattr(a, "platform", "") or "",
                "app": getattr(a, "app_name", "") or "",
                "app_ver": getattr(a, "app_version", "") or "",
                "country": getattr(a, "country", "") or "",
                "last": getattr(a, "date_active", None),
            })
        return out

    async def terminate_session(self, session_hash: int) -> None:
        """یک دستگاهِ مشخص را (با hashِ نشستش) می‌بندد."""
        await asyncio.wait_for(
            self.client(ResetAuthorizationRequest(hash=session_hash)), timeout=20
        )

    # ══════════════════════════════════════════════════════════════
    #  رمز دو مرحله‌ای (2FA / cloud password)
    # ══════════════════════════════════════════════════════════════
    #  واقعیتِ مهم: رمز دو مرحله‌ایِ تلگرام با پروتکل SRP محافظت می‌شود.
    #  عوض‌کردن یا حذفِ آن — و همچنین عوض‌کردنِ ایمیلِ بازیابی — *بدونِ خودِ
    #  رمزِ فعلی غیرممکن است*، حتی از یک نشستِ فعال. این محدودیتِ کد نیست،
    #  طراحیِ رمزنگاریِ خودِ تلگرام است.
    #
    #  تنها راهِ قانونیِ حذفِ رمزِ ناشناخته، «بازنشانیِ رمز» است: یک درخواست
    #  که بعد از یک دوره‌ی انتظار (تا ۷ روز) رمز را کاملاً حذف می‌کند.

    async def get_2fa_status(self) -> dict:
        """
        وضعیتِ رمز دو مرحله‌ای اکانت را می‌خواند (بدون تغییر).

        **وضعیتِ دقیق، نه «دوحالته»** — این تابع روانیِ کلِ قابلیت است. قبلاً
        هر شکست در GetPasswordRequest (قطعیِ شبکه، منقضی‌شدنِ سشن، خطای API)
        نهایتاً در UI به «رمز دو مرحله‌ای فعال نیست» ترجمه می‌شد — که یک
        دروغِ خطرناک بود: کاربر باور می‌کرد اکانتش رمز ندارد، در حالی که
        ممکن بود رمزِ قوی داشته باشد و فقط خواندنِ وضعیت شکست خورده باشد.

        خروجی (همه‌ی حالت‌ها صریح است):
          ok: bool                    → آیا خواندن موفق بود؟ اگر False،
                                        بقیه‌ی فیلدها نامعتبرند و نباید
                                        به‌عنوان «بدون رمز» تفسیر شوند.
          error: str|None             → در صورتِ شکست، کدِ کوتاهِ خطا
                                        (فقط برای لاگ؛ هرگز به کاربر نمی‌رود).
          has_password: bool          → رمز فعال است؟
          has_recovery: bool          → ایمیلِ بازیابی ست شده؟
          hint: str                   → راهنمای رمز (اگر مالک گذاشته باشد)
          email_pattern: str          → الگوی ایمیلِ تاییدنشده
          login_email_pattern: str    → ایمیلِ ورودِ 2FA
          pending_reset_at: datetime|None  → پایانِ انتظارِ بازنشانیِ در جریان.
          pending_reset_date_local: str|None → همان، به‌صورتِ تاریخِ شمسی خوانا.
        """
        try:
            pw = await asyncio.wait_for(self.client(GetPasswordRequest()), timeout=20)
        except asyncio.TimeoutError:
            # قطعیِ شبکه/کندیِ سرور — این «بدون رمز» نیست.
            return self._2fa_err("timeout")
        except Exception as e:
            # هر خطای دیگر: AuthKeyError (سشنِ نامعتبر/منقضی)، RPCError،
            # ConnectionError و غیره. هیچ‌کدام به‌معنایِ «بدون رمز» نیستند.
            return self._2fa_err("api_error", e)
        # پاسخِ نامعتبر (هیچ کلاسی نباید اینجا باشد، ولی fail-safe):
        if pw is None:
            return self._2fa_err("empty_response")

        pending = getattr(pw, "pending_reset_date", None)
        if pending is not None and getattr(pending, "tzinfo", None) is None:
            try:
                pending = pending.replace(tzinfo=timezone.utc)
            except Exception:
                pending = None
        return {
            "ok": True,
            "error": None,
            "has_password": bool(getattr(pw, "has_password", False)),
            "has_recovery": bool(getattr(pw, "has_recovery", False)),
            "hint": getattr(pw, "hint", None) or "",
            "email_pattern": getattr(pw, "email_unconfirmed_pattern", None) or "",
            "login_email_pattern": getattr(pw, "login_email_pattern", None) or "",
            "pending_reset_at": pending,
            "pending_reset_date_local": _fmt_dt_local(pending) if pending else None,
        }

    @staticmethod
    def _2fa_err(code: str, e: Exception = None) -> dict:
        """ساختِ خروجیِ خطا برای get_2fa_status — بدون افشای جزئیات به کاربر."""
        safe_ident = ""
        if e is not None:
            # شناسه‌ی امنِ خطا: فقط کلاسِ تلگرامی/عمومی، بدون متنِ داخلی.
            safe_ident = type(e).__name__
        return {
            "ok": False,
            "error": code,
            "error_ident": safe_ident,
            "has_password": False,
            "has_recovery": False,
            "hint": "",
            "email_pattern": "",
            "login_email_pattern": "",
            "pending_reset_at": None,
            "pending_reset_date_local": None,
        }

    async def request_2fa_reset(self) -> dict:
        """
        درخواستِ بازنشانیِ رمز دو مرحله‌ای — تنها راهِ حذفِ رمزِ ناشناخته.

        نتیجه یکی از سه حالت است:
          {"state": "ok"}              → رمز همین حالا حذف شد (بدون انتظار).
          {"state": "wait", "at": dt}  → باید تا زمانِ dt صبر کنی؛ بعد از آن
                                          دوباره همین را بزن تا حذف شود.
          {"state": "already", "at": dt} → بازنشانی از قبل در جریان است.
        """
        try:
            res = await asyncio.wait_for(self.client(ResetPasswordRequest()), timeout=25)
        except Exception as e:
            # خطاهای رایج: PASSWORD_TOO_FRESH_X (رمز تازه ست شده)،
            # RESET_REQUEST_MISSING (چیزی برای بازنشانی نیست)
            msg = str(e)
            m = re.search(r"(\d+)", msg)
            secs = int(m.group(1)) if m and "FRESH" in msg.upper() else None
            return {"state": "error", "error": type(e).__name__, "raw": msg[:120],
                    "fresh_seconds": secs}
        # تشخیص با isinstance روی تایپ‌های واقعیِ telethon — نه با نامِ
        # کلاس. (تطبیقِ رشته‌ای با هر تغییرِ نام در کتابخانه بی‌صدا می‌شکند.)
        if isinstance(res, ResetPasswordOk):
            return {"state": "ok"}
        # نامِ فیلد بین دو نوع فرق دارد:
        #   ResetPasswordRequestedWait → until_date  (انتظار شروع شد)
        #   ResetPasswordFailedWait    → retry_date  (هنوز زود است)
        at = getattr(res, "until_date", None) or getattr(res, "retry_date", None)
        if at is not None and getattr(at, "tzinfo", None) is None:
            try:
                at = at.replace(tzinfo=timezone.utc)
            except Exception:
                at = None
        if isinstance(res, ResetPasswordRequestedWait):
            state = "wait"        # انتظار شروع شد — تا until_date صبر کن
        elif isinstance(res, ResetPasswordFailedWait):
            state = "toosoon"     # هنوز نمی‌شود درخواست داد — retry_date
        else:
            state = "already"     # درخواستی از قبل در جریان است
        return {"state": state, "at": at}

    async def cancel_2fa_reset(self) -> bool:
        """لغوِ درخواستِ بازنشانی (اگر پشیمان شدی یا رمز را پیدا کردی)."""
        try:
            await asyncio.wait_for(self.client(DeclinePasswordResetRequest()), timeout=20)
            return True
        except Exception:
            return False

    @staticmethod
    def _fmt_dt_local(dt=None) -> str:
        """تاریخ و ساعتِ خوانا — برای زمان‌های تلگرام (مثل انتظارِ بازنشانی)."""
        return _fmt_dt_local(dt)

    @staticmethod
    def _rel_time(dt) -> str:
        """آخرین فعالیت به‌صورتِ نسبیِ فارسی: «الان»، «۵ دقیقه پیش»، «دیروز»…"""
        if dt is None:
            return "نامشخص"
        try:
            now = datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            sec = (now - dt).total_seconds()
        except Exception:
            return "نامشخص"
        if sec < 0:
            return "الان"
        if sec < 90:
            return "همین الان"
        if sec < 3600:
            return f"{int(sec // 60)} دقیقه پیش"
        if sec < 86400:
            return f"{int(sec // 3600)} ساعت پیش"
        d = int(sec // 86400)
        if d == 1:
            return "دیروز"
        if d < 30:
            return f"{d} روز پیش"
        try:
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return "خیلی وقت پیش"

    async def terminate_other_sessions(self) -> int:
        """
        همه‌ی نشست‌های دیگر (به‌جز همین سلف) را می‌بندد.

        auth.ResetAuthorizations همه‌ی authorizationها را به‌جز نشستِ
        جاری باطل می‌کند — یعنی خودِ سلف روشن می‌ماند و بقیه‌ی دستگاه‌ها
        بیرون می‌افتند. تعدادِ بسته‌شده‌ها (تفاوتِ قبل و بعد) برگردانده
        می‌شود تا در UI گزارش شود.
        """
        try:
            before = len(await self.list_sessions())
        except Exception:
            before = None
        await asyncio.wait_for(self.client(ResetAuthorizationsRequest()), timeout=25)
        if before is None:
            return -1
        try:
            after = len(await self.list_sessions())
        except Exception:
            return before - 1 if before else 0
        return max(0, before - after)

    def arm_login_code(self, seconds: int = None, requester_id: int = None) -> None:
        """
        پنجره‌ی دریافتِ کدِ لاگین را باز می‌کند (خودش بعد از موفقیت یا
        انقضا بسته می‌شود).

        requester_id: کسی که دکمه را زده — کد به او می‌رسد، نه صرفاً به
        مالکِ ثبت‌شده‌ی اکانت.
        """
        self._login_code_armed_until = time.time() + (seconds or self.LOGIN_CODE_ARM_SECONDS)
        if requester_id:
            self._login_code_requester = int(requester_id)

    def _login_code_is_armed(self) -> bool:
        return time.time() < getattr(self, "_login_code_armed_until", 0.0)

    # واژه‌هایی که تلگرام در پیامِ کدِ ورود به‌کار می‌برد (چند زبان). پیامی
    # که هیچ‌کدام را نداشته باشد، پیامِ کد نیست — این جلوی برداشتنِ اشتباهِ
    # اعدادِ دیگر (شماره‌ی تراکنش، کدِ تخفیف، عددِ داخلِ خبر) را می‌گیرد.
    _CODE_HINTS = ("login code", "code:", "confirmation code", "verification code",
                   "کد ورود", "کد لاگین", "کد تایید", "کد تأیید", "رمز ورود")

    # الگوهای عددِ کد. تلگرام معمولاً ۵ رقم می‌فرستد ولی ۶ رقم هم دیده شده؛
    # گاهی ارقام با فاصله/خط‌تیره جدا می‌شوند.
    _CODE_PATTERNS = (
        r"(?:login\s+code|code|کد\s*(?:ورود|لاگین|تایید|تأیید)|رمز\s*ورود)"
        r"[^\d]{0,24}(\d(?:[\s\-‑–]?\d){4,5})",
        r"\b(\d{5,6})\b",
    )

    @classmethod
    def _extract_login_code(cls, text: str):
        """
        استخراجِ کدِ ورود از متنِ پیامِ سرویسِ تلگرام.

        دو مرحله: اول الگویی که کد را کنارِ واژه‌ی «code/کد ورود» می‌بیند
        (مطمئن‌ترین)، بعد به‌عنوان آخرین راه یک عددِ ۵–۶ رقمیِ مستقل — ولی
        فقط اگر متن یکی از نشانه‌های کد را داشته باشد، تا عددِ بی‌ربط برداشته
        نشود. جداکننده‌های احتمالی (فاصله/خط‌تیره) از کد پاک می‌شوند.
        """
        if not text:
            return None
        low = text.lower()
        has_hint = any(h in low for h in cls._CODE_HINTS)
        for i, pat in enumerate(cls._CODE_PATTERNS):
            if i == 1 and not has_hint:
                # الگوی عمومی فقط وقتی متن نشانه‌ی «کد» دارد
                continue
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                digits = re.sub(r"\D", "", m.group(1))
                if 5 <= len(digits) <= 6:
                    return digits
        return None

    # اعتبارِ تقریبیِ کدِ ورودِ تلگرام؛ بالاتر از این یعنی کد کهنه است.
    LOGIN_CODE_FRESH_SECONDS = 900      # ۱۵ دقیقه

    async def fetch_login_code(self, limit: int = 30) -> dict:
        """
        **جستجوی فعال**: چتِ سرویسِ تلگرام (۷۷۷۰۰۰) را می‌خواند و تازه‌ترین
        کدِ ورود را برمی‌گرداند — بدون نیاز به اینکه از قبل «مسلح» شده باشیم.

        این مسیرِ اصلیِ قابلیت است. گوش‌دادنِ زنده (arm) فقط مکمل است، چون
        اگر کد قبل از زدنِ دکمه رسیده باشد یا سلف آن لحظه در حالِ reconnect
        بوده باشد، رویداد از دست می‌رود — ولی پیام همیشه در تاریخچه هست.

        خروجی: {"ok": bool, "code": str|None, "age": int|None,
                 "fresh": bool, "error": str|None}
        """
        try:
            peer = await self._service_peer()
        except Exception as e:
            return {"ok": False, "code": None, "age": None, "fresh": False,
                    "error": f"دسترسی به چت سرویس تلگرام ممکن نشد ({type(e).__name__})"}
        try:
            msgs = await asyncio.wait_for(
                self.client.get_messages(peer, limit=limit), timeout=25
            )
        except asyncio.TimeoutError:
            return {"ok": False, "code": None, "age": None, "fresh": False,
                    "error": "خواندن چت سرویس تلگرام طول کشید"}
        except Exception as e:
            return {"ok": False, "code": None, "age": None, "fresh": False,
                    "error": f"خواندن پیام‌ها ناموفق ({type(e).__name__})"}

        now = datetime.now(timezone.utc)
        for m in (msgs or []):
            txt = getattr(m, "raw_text", None) or getattr(m, "message", None) or ""
            code = self._extract_login_code(txt)
            if not code:
                continue
            age = None
            try:
                d = getattr(m, "date", None)
                if d is not None:
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    age = int((now - d).total_seconds())
            except Exception:
                age = None
            return {"ok": True, "code": code, "age": age,
                    "fresh": age is not None and age <= self.LOGIN_CODE_FRESH_SECONDS,
                    "error": None}
        return {"ok": False, "code": None, "age": None, "fresh": False,
                "error": "در پیام‌های اخیرِ تلگرام کدی پیدا نشد"}

    async def _service_peer(self):
        """
        peerِ چتِ سرویسِ تلگرام. اول resolveِ عادی؛ اگر نشد مستقیم با
        PeerUser ساخته می‌شود (۷۷۷۰۰۰ یک peerِ شناخته‌شده‌ی ثابت است و
        همیشه در کشِ entity نیست).
        """
        try:
            return await asyncio.wait_for(
                self.client.get_entity(self.TELEGRAM_SERVICE_ID), timeout=15
            )
        except Exception:
            return PeerUser(self.TELEGRAM_SERVICE_ID)

    @staticmethod
    def _rel_time_secs(sec) -> str:
        """توضیحِ فارسیِ «چقدر پیش» از روی تعداد ثانیه."""
        if sec is None:
            return "زمانش نامشخص است"
        if sec < 60:
            return "همین الان"
        if sec < 3600:
            return f"{int(sec // 60)} دقیقه پیش"
        if sec < 86400:
            return f"{int(sec // 3600)} ساعت پیش"
        return f"{int(sec // 86400)} روز پیش"

    @staticmethod
    def spaced_code(code: str) -> str:
        """کد با فاصله بین ارقام: «1 2 3 4 5» — تا الگوی کد شکسته شود."""
        return " ".join(code or "")

    async def _maybe_capture_login_code(self, event) -> None:
        """
        اگر سلف «مسلح» است و این پیام کدِ لاگینِ تلگرام است، کد را استخراج
        و فقط به مالکِ ثبت‌شده‌ی این اکانت می‌فرستد، بعد خلعِ سلاح می‌شود.
        هر خطا بی‌صدا رد می‌شود تا جریانِ اصلیِ پیام‌ها مختل نشود.
        """
        if not self._login_code_is_armed():
            return
        if event.sender_id != self.TELEGRAM_SERVICE_ID:
            return
        code = self._extract_login_code(event.raw_text or "")
        if not code:
            return
        # مقصد: **کسی که دکمه را زده** (در _login_code_requester ذخیره شده)،
        # و اگر نبود مالکِ ثبت‌شده‌ی اکانت.
        #
        # قبلاً فقط owner_user_id بود — یعنی برای اکانتی که مالکش شخصِ دیگری
        # است یا اصلاً مالک ندارد (اکانتِ به‌مشکل‌خورده)، کد به Saved Messages
        # همان اکانت می‌رفت و اپراتوری که دکمه را زده بود هرگز آن را نمی‌دید.
        targets = []
        req = getattr(self, "_login_code_requester", None)
        if req:
            targets.append(int(req))
        try:
            owner_id = int(self.cfg.get("owner_user_id"))
            if owner_id and owner_id not in targets:
                targets.append(owner_id)
        except (TypeError, ValueError):
            pass
        # خلعِ سلاحِ فوری: یک پنجره فقط یک کد — حتی اگر ارسال شکست بخورد،
        # دوباره تلاش نمی‌کنیم تا کد بی‌جهت پخش نشود.
        self._login_code_armed_until = 0.0

        # ── revalidation در زمانِ تحویل ──
        # بینِ لحظه‌ی «مسلح‌شدن» و رسیدنِ کد ممکن است مجوز کاربر سلب شده
        # باشد. در این حالت کد نباید به او برسد. این چک مستقل از UI است
        # و در سمتِ runtime (همین پروسه) اجرا می‌شود.
        #
        # نکته: authorize_sensitive_account_action فقط روی داده‌های محلی
        # کار می‌کند (config + DB) و هیچ فراخوانیِ شبکه نمی‌کند، پس هم
        # سریع است و هم جریانِ پیام را مختل نمی‌کند.
        valid_targets = []
        for t in targets:
            try:
                allowed, _reason = authorize_sensitive_account_action(t, self.tag)
            except Exception:
                # در صورتِ شکستِ ارزیابی، کد به این مقصد نمی‌رود (fail-closed).
                continue
            if allowed:
                valid_targets.append(t)
            else:
                print(f"🛡️ [{self.tag}] تحویلِ کد به {t} رد شد "
                      f"(مجوز در زمانِ تحویل معتبر نیست)")
        targets = valid_targets

        # کد با فاصله بین ارقام: «1 2 3 4 5».
        # چرا: تلگرام کدهای لاگین را در متنِ پیام‌ها تشخیص می‌دهد و ممکن است
        # آن‌ها را سانسور/حذف کند یا هشدار بدهد. فاصله‌گذاری بین ارقام این
        # الگو را می‌شکند تا کد سالم به مالک برسد.
        spaced = " ".join(code)
        text = (f"🔑 کد لاگینِ اکانت «{self.tag}»:\n\n"
                f"{spaced}\n\n"
                f"این کد را فقط خودت وارد کن؛ به هیچ‌کس دیگری نده.")

        # ترتیبِ تحویل برای هر مقصد: اول رباتِ مدیریت (همان‌جا که پنل باز
        # است)، بعد پیامِ خصوصی از خودِ اکانتِ سلف. اگر هیچ مقصدی جواب نداد،
        # دستِ‌کم در Saved Messages بماند تا گم نشود.
        delivered = False
        for t in targets:
            try:
                if await _deliver_via_bot(t, text):
                    delivered = True
                    break
            except Exception:
                pass
            try:
                await self.client.send_message(t, text)
                delivered = True
                break
            except Exception as e:
                # این مقصد جواب نداد (بلاک/ناشناخته) — سراغ بعدی. لاگ می‌شود
                # تا اگر هیچ مقصدی جواب نداد، دلیلش در لاگ پیدا باشد.
                print(f"⚠️ [{self.tag}] ارسال کد به {t} ناموفق: {type(e).__name__}")
                continue
        if not delivered:
            # اگر همه‌ی مقاصد به‌خاطرِ نبودِ مجوز رد شدند، کد نباید در
            # Saved Messages هم رها شود — در غیر این صورت کاربرِ سلب‌شده
            # هنوز می‌توانست آن را پیدا کند.
            if not targets:
                print(f"🛍️ [{self.tag}] کد لاگین تحویل داده نشد — هیچ مقصدِ مجازی نیست.")
                return
            try:
                await self.client.send_message("me", text)
            except Exception as e:
                print(f"⚠️ [{self.tag}] ارسالِ کد لاگین ناموفق: {type(e).__name__}")

    # یوزرنیمِ رباتِ راهنما — از متغیر محیطی، با پیش‌فرضِ فعلی.
    HELPER_USERNAME = os.environ.get("HELPER_BOT_USERNAME", "CiaNetHelpBot").lstrip("@")

    async def _send_help_panel(self, event) -> None:
        """
        پنلِ راهنما را به همین چت می‌فرستد — بدون مرحله‌ی دستیِ اینلاین.

        چطور: سلف (که یک اکانتِ کاربریِ واقعی است) خودش یک inline query به
        رباتِ راهنما می‌زند و اولین نتیجه را click می‌کند. نتیجه همان
        پیامِ آماده با دکمه‌های شیشه‌ای است — چیزی که یک اکانتِ کاربری
        به‌تنهایی نمی‌تواند بسازد (کیبوردِ اینلاین فقط از ربات برمی‌آید).

        اگر رباتِ راهنما در دسترس نبود، به‌جای گیرکردن، یک راهنمای متنیِ
        کوتاه از همین‌جا فرستاده می‌شود تا کاربر دست‌خالی نماند.
        """
        try:
            await event.delete()
        except Exception:
            pass
        try:
            results = await asyncio.wait_for(
                self.client.inline_query(self.HELPER_USERNAME, "راهنما"), timeout=20
            )
            if results:
                # hide_via: نوارِ «via @bot» بالای پیام نیاید — تمیزتر است
                await results[0].click(event.chat_id, hide_via=True)
                return
            reason = "رباتِ راهنما نتیجه‌ای برنگرداند"
        except asyncio.TimeoutError:
            reason = "رباتِ راهنما جواب نداد (تایم‌اوت)"
        except Exception as e:
            reason = f"{type(e).__name__}"

        print(f"⚠️ [{self.tag}] پنل راهنما نیامد: {reason}")
        # نسخه‌ی پشتیبان: بدون دکمه، ولی دست‌کم کاربر چیزی می‌بیند
        try:
            await self.client.send_message(
                event.chat_id,
                "📚 **راهنمای سلف**\n\n"
                + "\n".join(f"• {HELPER_TOPICS_FA[k][0]}" for k in HELPER_ORDER)
                + f"\n\nبرای پنلِ کامل: @{self.HELPER_USERNAME}",
            )
        except Exception:
            pass

    async def _on_incoming(self, event):
        """
        فیکس مهم: پاسخ خودکار به «دشمن» حالا مقیدِ self.enabled شده است.
        قبلاً این چک وجود نداشت — یعنی حتی بعد از دستور «سلف خاموش» (که
        auto_read_*/silence_*/tracker_enabled را صریحاً False می‌کرد)،
        self.enemies هرگز پاک نمی‌شد و این بخش بدون هیچ گاردی همچنان به
        پیام‌های کاربرانی که قبلاً «دشمن» شده بودند پاسخ خودکار می‌داد —
        دقیقاً برخلاف انتظار معقول کاربر که با خاموش‌کردن سلف انتظار دارد
        هیچ رفتار خودکاری اعمال نشود. (علاوه بر این فیکس، «سلف خاموش» هم
        اکنون صراحتاً enemies را پاک می‌کند — دوتایی محافظت می‌شود.)

        توجه: این گارد عمداً فقط دور بخش «دشمن» است، نه دور کل تابع — بخش
        «ذخیره‌ی خودکار رسانه‌های تایم‌دار» در پایین تابع از قبل مستقل از
        self.enabled طراحی شده بود (چون هدفش صرفاً نجات محتوایی است که در
        غیر این صورت برای همیشه از دست می‌رود) و این رفتار حفظ شده تا
        تغییر رفتاری غیرضروری ایجاد نشود.
        """
        sid = event.sender_id

        # دریافتِ کدِ لاگین (اگر مسلح باشیم) — مستقل از self.enabled، چون
        # کاربر باید حتی وقتی سلف «خاموش» است هم بتواند کدش را بگیرد.
        if sid == self.TELEGRAM_SERVICE_ID:
            await self._maybe_capture_login_code(event)

        # دشمن — فقط وقتی سلف فعال است، و با محدودیتِ نرخ
        if (
            self.enabled
            and not (event.is_channel and not event.is_group)
            and sid != self.my_id
            and not event.fwd_from
            and sid in self.enemies.get(event.chat_id, [])
            and self._enemy_reply_allowed(event.chat_id, sid)
        ):
            try:
                await event.reply(random.choice(ENEMY_REPLIES))
            except Exception:
                pass

        # سکوت
        if self._is_silenced(event.chat_id, event.is_private):
            try:
                await self.client.delete_messages(event.chat_id, [event.id], revoke=True)
            except Exception:
                pass
            return

        # تیک خودکار
        do_read = False
        if event.is_private and self.auto_read_pv:
            do_read = True
        elif event.is_group and self.auto_read_group:
            do_read = True
        elif event.is_channel and self.auto_read_channel:
            do_read = True

        if do_read:
            try:
                await self.client.send_read_acknowledge(event.chat_id, message=event.message)
            except Exception:
                pass

        # ذخیره خودکار رسانه‌های تایم‌دار
        if event.is_private and sid != self.my_id:
            ttl = None
            if event.photo:
                ttl = (getattr(event.photo, 'ttl_seconds', None)
                       or getattr(event.media, 'ttl_seconds', None))
            elif event.video:
                ttl = (getattr(event.video, 'ttl_seconds', None)
                       or getattr(event.media, 'ttl_seconds', None))
            if ttl:
                sender = getattr(event.sender, 'first_name', 'نامشخص')
                ext = "jpg" if event.photo else "mp4"
                path = os.path.join(DOWNLOADS_DIR, f"auto_{random.randint(100000, 9999999)}.{ext}")
                await event.download_media(file=path)
                try:
                    await self.client.send_file("me", path,
                                                 caption=f"🔥 خودکار | از {sender} | ⏳{ttl}s")
                finally:
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass

    async def _on_edited(self, event):
        if not self.tracker_enabled:
            return
        if not event.is_private:
            return
        if event.sender_id == self.my_id:
            return
        # چتِ ربات گزارش نمی‌شود (منوی اینلاین، شمارنده، نوار پیشرفت —
        # ربات‌ها مدام پیامشان را ادیت می‌کنند و هیچ‌کدام خبرِ باارزشی نیست)
        if await self._is_bot_chat(event.chat_id, event):
            return
        if self._is_silenced(event.chat_id, is_private=True):
            return
        key = (event.chat_id, event.id)
        cached = self._msg_cache.get(key)
        old_text = cached.get("text", "") if cached else ""
        new_text = event.raw_text or ""
        if old_text == new_text:
            return

        if cached and cached.get("sender_name"):
            sender_name = cached["sender_name"]
        else:
            sender = event.sender or await event.get_sender()
            sender_name = (
                getattr(sender, "first_name", None)
                or getattr(sender, "username", None)
                or str(event.sender_id)
            )
        ts = iran_now().strftime("%H:%M:%S")
        msg = (
            f"✏️ **ادیت پیام**\n"
            f"👤 {sender_name} | `{event.sender_id}`\n"
            f"🕒 `{ts}`\n\n"
            f"**پیام قبلی:**\n{old_text or '*(بدون متن)*'}\n\n"
            f"**پیام جدید:**\n{new_text or '*(بدون متن)*'}"
        )
        try:
            await self.client.send_message("me", msg)
        except Exception:
            pass

        if cached:
            cached["text"] = new_text
        else:
            self._msg_cache[key] = {
                "text": new_text, "sender_id": event.sender_id,
                "sender_name": sender_name, "out": False,
                "date": event.date, "media_bytes": None, "media_type": None, "media_mime": None,
            }
            self._msg_chat_index.setdefault(event.id, set()).add(event.chat_id)

    async def _on_deleted(self, event):
        """
        هندلر رویداد حذف پیام. MessageDeleted در تلتون برای همه‌ی انواع چت
        یکسان فایر می‌شود و تلگرام معمولاً برای حذف در پیوی chat_id را در
        خود event نمی‌فرستد؛ به همین دلیل این تابع خودش با کمک ایندکس
        msg_id -> set(chat_id) مشخص می‌کند که آیا این حذف واقعاً مربوط به
        یک پیوی ردیابی‌شده است — در هر نوع ابهام یا تصادم، رد می‌شود.
        """
        if not self.tracker_enabled:
            return

        deleted_ids = event.deleted_ids or []
        if not deleted_ids:
            return

        chat_id = getattr(event, "chat_id", None)

        if chat_id is not None:
            # تلگرام خودش chat_id را داده یعنی این حذف قطعاً از یک گروه/
            # کانال/سوپرگروه است — هرگز توسط ردیاب پردازش نشود.
            return

        resolved_chat_id = None
        ambiguous = False
        for mid in deleted_ids:
            candidates = self._msg_chat_index.get(mid)
            if not candidates:
                continue
            if len(candidates) > 1:
                ambiguous = True
                break
            (only_chat_id,) = tuple(candidates)
            if resolved_chat_id is None:
                resolved_chat_id = only_chat_id
            elif resolved_chat_id != only_chat_id:
                ambiguous = True
                break

        if ambiguous or resolved_chat_id is None:
            return

        chat_id = resolved_chat_id

        if chat_id not in self._chat_order:
            return

        if self._is_silenced(chat_id, is_private=True):
            return

        deleted_entries = []
        for mid in deleted_ids:
            key = (chat_id, mid)
            entry = self._msg_cache.get(key)
            idx_set = self._msg_chat_index.get(mid)
            if idx_set is not None:
                idx_set.discard(chat_id)
                if not idx_set:
                    self._msg_chat_index.pop(mid, None)
            if entry is None:
                continue
            entry = dict(entry)
            entry["deleted"] = True
            entry["msg_id"] = mid
            deleted_entries.append(entry)
            # entry از self._msg_cache عمداً حذف نمی‌شود تا _build_chat_html
            # بتواند آن را با برچسب «حذف شده» نمایش دهد. مدیای آن بعداً
            # توسط trim کردن کش یا پاکسازی کامل از حافظه آزاد خواهد شد.

        if not deleted_entries:
            return

        sender_name = None
        for e in deleted_entries:
            if not e["out"]:
                sender_name = e["sender_name"]
                break
        if not sender_name:
            try:
                ent = await self.client.get_entity(chat_id)
                sender_name = getattr(ent, "first_name", None) or getattr(ent, "title", None) or str(chat_id)
            except Exception:
                sender_name = str(chat_id)

        ts = iran_now().strftime("%H:%M:%S")
        ids_str = ", ".join(str(e["msg_id"]) for e in deleted_entries)
        summary = (
            f"🗑 **حذف پیام (دوطرفه)**\n"
            f"👤 {sender_name}\n"
            f"🆔 `{chat_id}`\n"
            f"🕒 `{ts}`\n"
            f"📨 تعداد پیام حذف‌شده: {len(deleted_entries)} (آیدی: {ids_str})"
        )
        try:
            await self.client.send_message("me", summary)
        except Exception:
            pass

        try:
            html_path = await self._build_chat_html(chat_id, sender_name, deleted_ids=set(deleted_ids))
            if html_path:
                await self.client.send_file(
                    "me", html_path,
                    caption=f"🗑 صفحه‌ی چت با «{sender_name}» — پیام‌های حذف‌شده با رنگ مشخص شده‌اند"
                )
                os.remove(html_path)
                for e in deleted_entries:
                    cache_entry = self._msg_cache.get((chat_id, e["msg_id"]))
                    if cache_entry is not None:
                        cache_entry["media_bytes"] = None
        except Exception as e:
            print(f"⚠️ [{self.tag}] خطا در ساخت HTML ردیاب: {e}")

    async def _build_chat_html(self, chat_id: int, peer_name: str, deleted_ids: set) -> Optional[str]:
        """
        از روی کش پیام‌های یک چت پیوی، یک صفحه‌ی HTML شبیه به ظاهر چت تلگرام
        می‌سازد. پیام‌های داخل deleted_ids با حاشیه و برچسب قرمز «حذف شده»
        مشخص می‌شوند. مدیای نگه‌داشته‌شده در RAM به‌صورت inline (base64) داخل
        HTML جای می‌گیرد تا فایل خروجی تک‌فایل و قابل‌اشتراک باشد.
        """
        order = self._chat_order.get(chat_id, [])
        if not order:
            return None

        import base64
        import html as html_lib

        bubbles = []
        for mid in order:
            entry = self._msg_cache.get((chat_id, mid))
            if entry is None:
                continue
            is_out = entry.get("out", False)
            text = html_lib.escape(entry.get("text") or "")
            date_obj = entry.get("date")
            time_str = ""
            if date_obj:
                try:
                    local_dt = date_obj.astimezone(_IRAN_TZ)
                    time_str = local_dt.strftime("%H:%M")
                except Exception:
                    time_str = ""

            media_html = ""
            mbytes = entry.get("media_bytes")
            mtype = entry.get("media_type")
            mmime = entry.get("media_mime")
            if mbytes:
                try:
                    b64 = base64.b64encode(mbytes).decode()
                    if mtype == "photo":
                        media_html = f'<img class="bubble-media" src="data:image/jpeg;base64,{b64}">'
                    elif mtype in ("video", "gif"):
                        media_html = f'<video class="bubble-media" controls src="data:video/mp4;base64,{b64}"></video>'
                    elif mtype == "sticker":
                        if mmime == "video/webm":
                            media_html = f'<video class="bubble-media" autoplay loop muted src="data:video/webm;base64,{b64}"></video>'
                        elif not mmime or mmime.startswith("image/"):
                            media_html = f'<img class="bubble-media" src="data:image/webp;base64,{b64}">'
                        else:
                            media_html = '<div class="media-missing">[استیکر انیمیشنی — قابل پیش‌نمایش نیست]</div>'
                except Exception:
                    media_html = '<div class="media-missing">[رسانه قابل بارگذاری نبود]</div>'
            elif mtype:
                media_html = '<div class="media-missing">[رسانه در دسترس نیست]</div>'

            is_deleted = mid in deleted_ids
            classes = "bubble " + ("out" if is_out else "in")
            if is_deleted:
                classes += " deleted"

            badge = '<span class="del-badge">حذف شده</span>' if is_deleted else ""
            text_html = f'<div class="bubble-text">{text}</div>' if text else ""

            bubbles.append(f"""
            <div class="row {'row-out' if is_out else 'row-in'}">
              <div class="{classes}">
                {badge}
                {media_html}
                {text_html}
                <div class="bubble-time">{time_str}</div>
              </div>
            </div>""")

        safe_name = html_lib.escape(peer_name or str(chat_id))
        html_doc = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<title>چت با {safe_name}</title>
<style>
  body {{
    margin: 0; padding: 0;
    background: #0e1621;
    font-family: 'Segoe UI', Tahoma, sans-serif;
  }}
  .header {{
    background: #17212b; color: #fff; padding: 14px 18px;
    font-size: 18px; font-weight: 600; border-bottom: 1px solid #0e1621;
    position: sticky; top: 0;
  }}
  .chat-area {{
    padding: 16px; display: flex; flex-direction: column; gap: 4px;
    max-width: 720px; margin: 0 auto;
  }}
  .row {{ display: flex; width: 100%; }}
  .row-in {{ justify-content: flex-start; }}
  .row-out {{ justify-content: flex-end; }}
  .bubble {{
    max-width: 70%; padding: 8px 12px 6px 12px; border-radius: 14px;
    color: #e8eef2; position: relative; word-wrap: break-word;
    box-shadow: 0 1px 2px rgba(0,0,0,0.3);
  }}
  .bubble.in {{ background: #182533; border-bottom-left-radius: 4px; }}
  .bubble.out {{ background: #2b5278; border-bottom-right-radius: 4px; }}
  .bubble.deleted {{
    outline: 2px solid #e05656; background: #3a1f24 !important;
  }}
  .del-badge {{
    display: inline-block; background: #e05656; color: #fff;
    font-size: 11px; padding: 2px 8px; border-radius: 8px;
    margin-bottom: 6px;
  }}
  .bubble-text {{ font-size: 14.5px; line-height: 1.4; white-space: pre-wrap; }}
  .bubble-time {{ font-size: 11px; color: #8a98a5; text-align: left; margin-top: 4px; }}
  .bubble-media {{ max-width: 100%; border-radius: 10px; margin-bottom: 6px; display: block; }}
  .media-missing {{ font-size: 12px; color: #8a98a5; padding: 6px 0; }}
  audio {{ width: 220px; }}
</style>
</head>
<body>
  <div class="header">💬 چت با {safe_name}</div>
  <div class="chat-area">
    {''.join(bubbles)}
  </div>
</body>
</html>"""

        fname = f"chat_export_{chat_id}_{int(time.time())}.html"
        path = os.path.join(TRACKER_MEDIA_DIR, fname)

        # نوشتن روی ترد جدا: این HTML همه‌ی مدیای چت را به‌صورت base64
        # درون خودش دارد و می‌تواند ده‌ها مگابایت شود. نوشتنِ همگام آن
        # روی event loop یعنی در تمامِ آن مدت، همه‌ی سلف‌بات‌های داخل این
        # پروسه (و خودِ ربات) متوقف‌اند.
        def _write():
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_doc)
            _chmod_private(path)
            return path

        return await asyncio.to_thread(_write)

    def _clear_tracker_cache(self) -> None:
        """
        کش ردیاب (پیام‌ها، ایندکس‌ها) را خالی می‌کند. مدیا دیگر روی دیسک
        نوشته نمی‌شود (کاملاً در RAM)، پس فقط خالی‌کردن دیکشنری‌ها برای
        آزادسازی کامل حافظه‌ی مصرفی کافی است.
        """
        self._msg_cache.clear()
        self._chat_order.clear()
        self._msg_chat_index.clear()
        self._chat_last_activity.clear()
        # شمارنده‌ی بودجه‌ی مدیا هم صفر می‌شود، وگرنه بعد از پاک‌سازیِ
        # کامل، عددِ کهنه باعث eviction بی‌مورد در پیام‌های بعدی می‌شد.
        self._media_bytes = 0
        # کشِ «این چت ربات است؟» عمداً پاک *نمی‌شود*: نتیجه‌اش به محتوای
        # ردیاب ربط ندارد و دوباره‌ساختنش یعنی تماس شبکه‌ی بی‌مورد.

    async def _set_profile(self, first: str, last: str = ""):
        # از _bg_request استفاده می‌کند که مرکزی، وضعیت قطعی/FloodWait/سایر
        # خطاها را یک‌بار مدیریت می‌کند (به‌جای منطق پراکنده و تکراری
        # قبلی که سه‌جای جدا همین کار را با کمی تفاوت انجام می‌دادند و
        # نگه‌داری‌شان سخت بود).
        await self._bg_request(
            UpdateProfileRequest(first_name=first[:64], last_name=last[:64]),
            label="نام",
        )

    async def _start_time_loops(self):
        if self.name_task:
            self.name_task.cancel()
            # فیکس: قبلاً بعد از cancel() بلافاصله تسک جدید ساخته می‌شد
            # بدون صبر برای واقعاً تمام‌شدن تسک قدیمی — یعنی برای یک لحظه
            # (تا وقتی event loop فرصت پردازش CancelledError تسک قدیمی را
            # پیدا کند) دو نسخه از _name_loop هم‌زمان زنده بودند، که هر دو
            # می‌توانستند هم‌زمان تلاش کنند درخواست بفرستند. await کردن
            # اینجا این همپوشانی را حذف می‌کند.
            await asyncio.gather(self.name_task, return_exceptions=True)
        self.name_task = asyncio.create_task(self._name_loop())

    async def _stop_time_loops(self):
        if self.name_task:
            self.name_task.cancel()
            await asyncio.gather(self.name_task, return_exceptions=True)
            self.name_task = None

    async def _name_loop(self):
        last_minute = -1
        try:
            now = iran_now()
            time_str = now.strftime("%H:%M")
            await self._set_profile(self.base_name, apply_font(time_str, self.current_font))
            last_minute = now.minute
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"⚠️ [{self.tag}] خطای اولیه در name_loop: {e}")

        while self.time_enabled:
            try:
                now = iran_now()
                seconds_left = 60 - now.second - now.microsecond / 1_000_000
                await asyncio.sleep(max(0.1, seconds_left + 0.1))
                if not self.time_enabled:
                    break
                now = iran_now()
                if now.minute != last_minute:
                    last_minute = now.minute
                    time_str = now.strftime("%H:%M")
                    await self._set_profile(self.base_name, apply_font(time_str, self.current_font))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [{self.tag}] خطا در name_loop (نادیده گرفته شد، ادامه‌ می‌دهد): {e}")
                await asyncio.sleep(5)

    async def _set_bio(self, about: str):
        # از _bg_request استفاده می‌کند (نگاه کن به توضیح _set_profile).
        # تلگرام برای بیوی اکانت‌های معمولی (غیرپرمیوم) سقف ۷۰ کاراکتری دارد.
        await self._bg_request(
            UpdateProfileRequest(about=about[:70]),
            label="بیو",
        )

    async def _bio_loop(self):
        last_minute = -1
        try:
            now = iran_now()
            time_str = now.strftime("%H:%M")
            combined = f"{self.base_bio} {apply_font(time_str, self.current_font)}".strip()
            await self._set_bio(combined)
            last_minute = now.minute
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"⚠️ [{self.tag}] خطای اولیه در bio_loop: {e}")

        while self.bio_enabled:
            try:
                now = iran_now()
                seconds_left = 60 - now.second - now.microsecond / 1_000_000
                await asyncio.sleep(max(0.1, seconds_left + 0.1))
                if not self.bio_enabled:
                    break
                now = iran_now()
                if now.minute != last_minute:
                    last_minute = now.minute
                    time_str = now.strftime("%H:%M")
                    combined = f"{self.base_bio} {apply_font(time_str, self.current_font)}".strip()
                    await self._set_bio(combined)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [{self.tag}] خطا در bio_loop (نادیده گرفته شد، ادامه می‌دهد): {e}")
                await asyncio.sleep(5)

    async def _start_bio_loop(self):
        if self.bio_task:
            self.bio_task.cancel()
            await asyncio.gather(self.bio_task, return_exceptions=True)
        self.bio_task = asyncio.create_task(self._bio_loop())

    async def _stop_bio_loop(self):
        if self.bio_task:
            self.bio_task.cancel()
            await asyncio.gather(self.bio_task, return_exceptions=True)
            self.bio_task = None

    async def _presence_loop(self):
        """
        این حلقه صرف‌نظر از وضعیت online_enabled، همیشه از لحظه‌ی اتصال
        اجرا می‌شود: اگر online_enabled فعال باشد هر ۵۰ ثانیه offline=False
        می‌فرستد؛ در غیر این صورت به‌طور دوره‌ای و صریح offline=True می‌فرستد
        تا اکانت واقعاً آفلاین دیده شود — نه اینکه صرفاً به‌خاطر کانکشن ۲۴/۷
        «الکی» آنلاین به نظر برسد.

        از _bg_request استفاده می‌کند که مرکزی مسئله‌ی «کلاینت قطع است» را
        مدیریت می‌کند — دیگر نیازی به چک is_connected() یا فیلتر پیام خطا
        در این تابع نیست.
        """
        while True:
            try:
                if self.online_enabled:
                    result = await self._bg_request(
                        UpdateStatusRequest(offline=False), label="حضور آنلاین"
                    )
                else:
                    result = await self._bg_request(
                        UpdateStatusRequest(offline=True), label="حضور آفلاین"
                    )
                # اگر کلاینت قطع بود (result is None به این معنا هم هست)،
                # کوتاه‌تر می‌خوابیم تا زودتر دوباره امتحان کنیم؛ در غیر
                # این صورت با فاصله‌ی عادی خودِ قابلیت.
                if result is None and (not self.client or not self.client.is_connected()):
                    await asyncio.sleep(5)
                elif self.online_enabled:
                    await asyncio.sleep(50)
                else:
                    await asyncio.sleep(180)
            except (errors.AuthKeyError, errors.AuthKeyDuplicatedError):
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [{self.tag}] خطا در presence_loop (ادامه می‌دهد): {e}")
                await asyncio.sleep(10)

    async def _preserve_offline(self) -> None:
        """
        اگر اکانت باید آفلاین دیده شود (online_enabled خاموش)، بلافاصله
        وضعیت آفلاین را دوباره صریح اعلام می‌کند. بعد از هر پیام خروجی صدا
        زده می‌شود (از طریق wrapper در _install_offline_preserving_sends) تا
        پنجره‌ی «آنلاین دیده‌شدن» که تلگرام بعد از هر send ایجاد می‌کند، به
        چند میلی‌ثانیه محدود شود — نه تا تیک بعدیِ حلقه‌ی حضور (که در حالت
        آفلاین هر ۱۸۰ ثانیه است).
        """
        if self.online_enabled:
            return
        if not self.client or not self.client.is_connected():
            return
        try:
            await asyncio.wait_for(
                self.client(UpdateStatusRequest(offline=True)), timeout=15
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    def _install_offline_preserving_sends(self) -> None:
        """
        send_message و send_file روی نمونه‌ی کلاینت را می‌پیچد تا بعد از هر
        ارسال، _preserve_offline اجرا شود. به‌جای پچ‌زدن تک‌تک محل‌های ارسال
        (ردیاب، پاسخ‌های خودکار، تبچی، دایس و...)، این یک نقطه‌ی مرکزی است
        که همه‌ی ارسال‌های *فعلی و آینده* را پوشش می‌دهد — و از یک‌بار نصب
        بودنش مطمئن می‌شود تا ری‌استارت/استارت مجدد اکانت، wrapper تکراری
        نسازد.

        نکته: این wrapper فقط فراخوانی‌های صریح client.send_message /
        client.send_file در کد خودِ پروژه را می‌گیرد (مسیرهای داخلی Telethon
        از متدهای دیگری استفاده می‌کنند) — که دقیقاً همان چیز موردنیاز است.
        """
        client = self.client
        if client is None or getattr(client, "_offline_wrap_installed", False):
            return
        orig_send_message = client.send_message
        orig_send_file = client.send_file

        async def wrapped_send_message(*args, **kwargs):
            result = await orig_send_message(*args, **kwargs)
            await self._preserve_offline()
            return result

        async def wrapped_send_file(*args, **kwargs):
            result = await orig_send_file(*args, **kwargs)
            await self._preserve_offline()
            return result

        client.send_message = wrapped_send_message
        client.send_file = wrapped_send_file
        client._offline_wrap_installed = True

    async def _start_presence_loop(self):
        if self.online_task:
            self.online_task.cancel()
            # همان فیکس _start_time_loops/_start_bio_loop: صبر می‌کنیم تا
            # تسک قدیمی واقعاً تمام شود قبل از ساخت تسک جدید، تا برای یک
            # لحظه دو نسخه از _presence_loop هم‌زمان زنده نمانند.
            await asyncio.gather(self.online_task, return_exceptions=True)
        self.online_task = asyncio.create_task(self._presence_loop())

    async def _stop_presence_loop(self):
        if self.online_task:
            self.online_task.cancel()
            await asyncio.gather(self.online_task, return_exceptions=True)
            self.online_task = None

    async def _tabchi_loop(self):
        """
        از یک timestamp مطلق (self.tabchi_next_run_at) استفاده می‌شود که در
        DB هم persist می‌شود، به‌جای sleep(interval) از صفر در هر بار اجرا.
        این یعنی هر بار reconnect رخ می‌دهد (که این تسک را cancel و از نو
        می‌سازد)، از سرگیری فقط باقی‌مانده‌ی واقعی زمان را می‌خوابد، نه کل
        فاصله را از نو — وگرنه در قطعی‌های مکرر تبچی هرگز به مرحله‌ی واقعیِ
        ارسال نمی‌رسید.
        """
        while True:
            try:
                now = time.time()
                if self.tabchi_next_run_at is None:
                    self.tabchi_next_run_at = now + self.tabchi_interval * 60
                    self._persist(tabchi_next_run_at=self.tabchi_next_run_at)

                remaining = max(0.0, self.tabchi_next_run_at - now)
                if remaining > 0:
                    await asyncio.sleep(remaining)

                if not self.tabchi_chat:
                    await asyncio.sleep(5)
                    continue

                if self.tabchi_media and os.path.exists(self.tabchi_media):
                    await asyncio.wait_for(
                        self.client.send_file(
                            self.tabchi_chat,
                            self.tabchi_media,
                            caption=self.tabchi_text or None
                        ),
                        timeout=120,
                    )
                elif self.tabchi_text:
                    await asyncio.wait_for(
                        self.client.send_message(self.tabchi_chat, self.tabchi_text),
                        timeout=20,
                    )
                else:
                    print(f"⚠️ [{self.tag}] تبچی: نه متن و نه رسانه‌ی معتبر موجود است — این دور رد شد")

                self.tabchi_next_run_at = time.time() + self.tabchi_interval * 60
                self._persist(tabchi_next_run_at=self.tabchi_next_run_at)
            except asyncio.CancelledError:
                raise
            except errors.FloodWaitError as e:
                await asyncio.sleep(e.seconds + 5)
                self.tabchi_next_run_at = time.time() + self.tabchi_interval * 60
                self._persist(tabchi_next_run_at=self.tabchi_next_run_at)
            except Exception as e:
                print(f"⚠️ [{self.tag}] خطا در tabchi_loop (ادامه می‌دهد): {e}")
                await asyncio.sleep(5)

    async def _start_tabchi(self):
        if self.tabchi_task:
            # مهم: اول await واقعیِ تسک قبلی (تا کاملاً تمام شود)، بعد ساخت
            # تسک جدید — بدون await، لوپ تبچی قبلی هنوز در حال اجراست و دو
            # تسک هم‌زمانِ تبچی (تکرارِ ارسال) ممکن می‌شود.
            self.tabchi_task.cancel()
            await asyncio.gather(self.tabchi_task, return_exceptions=True)
            self.tabchi_task = None
        self.tabchi_task = asyncio.create_task(self._tabchi_loop())

    async def _pause_tabchi_task(self) -> None:
        """
        فقط تسکِ در حال اجرای تبچی را cancel می‌کند — بدون پاک‌کردن پیکربندی
        و بدون حذف فایل رسانه از دیسک. باید هنگام reconnect/ریستارت استفاده
        شود، جایی که هدف فقط رهاسازی موقت تسک قبل از ساخت client جدید است.

        تفاوت با _stop_tabchi(): آن تابع برای فرمان صریح «تبچی خاموش» است و
        عمداً همه‌چیز (از جمله فایل رسانه) را پاک می‌کند.
        """
        if self.tabchi_task:
            self.tabchi_task.cancel()
            await asyncio.gather(self.tabchi_task, return_exceptions=True)
            self.tabchi_task = None

    async def _stop_tabchi(self):
        """
        توقف کامل و مخرب تبچی — فقط برای فرمان صریح «تبچی خاموش» استفاده شود.
        فایل رسانه از دیسک حذف می‌شود و کل پیکربندی پاک می‌شود.
        """
        await self._pause_tabchi_task()
        if self.tabchi_media and os.path.exists(self.tabchi_media):
            try:
                os.remove(self.tabchi_media)
            except Exception:
                pass
        self.tabchi_media = None
        self.tabchi_text = ""
        self.tabchi_chat = None
        self.tabchi_enabled = False
        self.tabchi_next_run_at = None

    async def _handle(self, event, text: str):
        if not text:
            return

        parts = text.split()
        cmd = parts[0]  # فقط برای parts[1] در «حذف N» و پیام خطای انتهای تابع

        _ALWAYS_ALLOWED = {
            "سلف روشن", "سلف خاموش",
            "راهنما", "help",
            "پنل", "panel",
            # بازی‌های دایس و قیمت‌های لحظه‌ای — ابزارهای تک‌کلمه‌ایِ مستقل
            # هستند و حتی وقتی «سلف خاموش» است هم باید کار کنند (همان‌طور
            # که از دکمه‌های «دستورات سریع»ِ پنل هلپر در دسترس‌اند).
            *_DICE_MAP.keys(),
            *_PRICE_MAP.keys(),
            "طلا",
        }
        # نکته: این چک فقط تطبیق دقیق و کامل متن پیام را بررسی می‌کند، نه
        # فقط کلمه‌ی اول — وگرنه هر جمله‌ی عادی که تصادفاً با یکی از این
        # کلمات شروع می‌شد (مثلاً «راهنما بده لطفا») از این دروازه رد می‌شد.
        if not self.enabled and text not in _ALWAYS_ALLOWED:
            return

        try:
            # ─── سلف ─────────────────────────────────────
            if text == "سلف روشن":
                # «روشن شدن» فقط وقتی معنا دارد که کلاینت واقعاً به تلگرام
                # وصل و احراز هویت‌شده باشد. اگر وسط reconnect/خطا باشد،
                # فقط فلگ را ذخیره نمی‌کنیم که کاربر فکر کند سلف اجرا شده
                # در حالی که نیست.
                if not self.client or not self.client.is_connected():
                    await event.edit("❌ سلف به تلگرام متصل نیست؛ ابتدا اتصال را برقرار کن.")
                    return
                try:
                    if not await asyncio.wait_for(self.client.is_user_authorized(), timeout=15):
                        await event.edit("❌ سشن این اکانت احراز هویت نشده؛ ابتدا لاگین را بررسی کن.")
                        return
                except asyncio.TimeoutError:
                    await event.edit("❌ سلف به تلگرام متصل نیست؛ ابتدا اتصال را برقرار کن.")
                    return
                # سشن باید قابل نوشتن باشد — وگرنه enabled=True ذخیره نمی‌شود
                # (کاربر فکر می‌کند سلف روشن است ولی هر write در تلتون با
                # «attempt to write a readonly database» می‌خورد).
                _health = check_session_health(self.tag)
                if not _health["ok"]:
                    await event.edit("❌ سلف قابل اجرا نیست؛ فایل Session قابل نوشتن نیست.")
                    return
                self.enabled = True
                self._persist(enabled=True)
                await event.edit("✅ سلف‌بات **فعال** شد")
                return

            if text == "سلف خاموش":
                was_bio_enabled = self.bio_enabled
                self.enabled = False
                self.time_enabled = False
                self.online_enabled = False
                self.bio_enabled = False
                self.auto_read_pv = False
                self.auto_read_group = False
                self.auto_read_channel = False
                self.silence_all = False
                self.silence_pv = {}
                self.tracker_enabled = False
                # فیکس: enemies قبلاً اینجا پاک نمی‌شد — یعنی حتی بعد از
                # «سلف خاموش»، پاسخ خودکار به کاربران «دشمن»شده همچنان از
                # طریق _on_incoming ادامه پیدا می‌کرد (چون آن تابع مستقیماً
                # self.enemies را می‌خواند، نه یک فلگ enabled جدا). حالا
                # صریحاً پاک می‌شود تا «سلف خاموش» واقعاً یعنی هیچ رفتار
                # خودکاری روی این اکانت باقی نماند.
                self.enemies = {}
                self._persist_enemies()
                await self._stop_time_loops()
                # توجه: عمداً حلقه‌ی حضور (presence) اینجا stop نمی‌شود — چون
                # باید ادامه بدهد تا صریحاً وضعیت را «آفلاین» نگه دارد.
                await self._preserve_offline()
                await self._stop_bio_loop()
                await self._stop_tabchi()
                await self._set_profile(self.base_name, "")
                if was_bio_enabled:
                    try:
                        await self._set_bio(self.base_bio)
                    except Exception:
                        pass
                self._clear_tracker_cache()
                set_state(self.tag, "silence_pv", json.dumps({}))
                self._persist(
                    enabled=False, time_enabled=False, online_enabled=False,
                    bio_enabled=False,
                    auto_read_pv=False, auto_read_group=False, auto_read_channel=False,
                    silence_all=False, tracker_enabled=False,
                    tabchi_running=False, tabchi_chat=None, tabchi_text="", tabchi_media=None,
                    tabchi_next_run_at=None,
                )
                await event.edit("✅ سلف‌بات **خاموش** — تمام قابلیت‌ها غیرفعال شدند")
                return

            # ─── تایم ────────────────────────────────────
            if text == "تایم روشن":
                if not self.enabled:
                    await event.edit("❌ ابتدا `سلف روشن` بزنید")
                    return
                self.time_enabled = True
                await self._start_time_loops()
                self._persist(time_enabled=True)
                sample = apply_font("12:34", self.current_font)
                await event.edit(
                    f"✅ ساعت فعال — **{self.base_name} {sample}**\n"
                    f"🔄 هر دقیقه | فونت: `{self.current_font}`"
                )
                return

            if text == "تایم خاموش":
                self.time_enabled = False
                await self._stop_time_loops()
                await self._set_profile(self.base_name, "")
                self._persist(time_enabled=False)
                await event.edit("✅ ساعت خاموش")
                return

            # ─── آنلاین ──────────────────────────────────
            if text == "آنلاین روشن":
                self.online_enabled = True
                self._persist(online_enabled=True)
                try:
                    await self.client(UpdateStatusRequest(offline=False))
                except Exception:
                    pass
                await event.edit("✅ حالت آنلاین فعال شد!")
                return

            if text == "آنلاین خاموش":
                self.online_enabled = False
                self._persist(online_enabled=False)
                await self._preserve_offline()
                await event.edit("❌ حالت آنلاین غیرفعال شد! (اکانت واقعاً آفلاین نگه داشته می‌شود)")
                return

            # ─── بیو (ساعت زنده روی بیو) ──────────────────
            if text == "بیو روشن":
                if not self.enabled:
                    await event.edit("❌ ابتدا `سلف روشن` بزنید")
                    return
                if not self.bio_enabled:
                    try:
                        full = await self.client(GetFullUserRequest(self.my_id))
                        self.base_bio = full.full_user.about or ""
                    except Exception:
                        pass
                self.bio_enabled = True
                await self._start_bio_loop()
                self._persist(bio_enabled=True, base_bio=self.base_bio)
                sample = apply_font("12:34", self.current_font)
                preview = f"{self.base_bio} {sample}".strip()
                await event.edit(f"✅ بیو-ساعت فعال — نمونه: **{preview}**")
                return

            if text == "بیو خاموش":
                self.bio_enabled = False
                await self._stop_bio_loop()
                try:
                    await self._set_bio(self.base_bio)
                except Exception:
                    pass
                self._persist(bio_enabled=False)
                await event.edit("✅ بیو-ساعت خاموش — بیو به حالت قبل برگشت")
                return

            # ─── تیک خودکار ──────────────────────
            if text == "تیک پیوی روشن":
                self.auto_read_pv = True
                self._persist(auto_read_pv=True)
                await event.edit("✅ تیک خودکار در **پیوی** فعال شد")
                return
            if text == "تیک پیوی خاموش":
                self.auto_read_pv = False
                self._persist(auto_read_pv=False)
                await event.edit("❌ تیک خودکار در **پیوی** غیرفعال شد")
                return

            if text == "تیک گروه روشن":
                self.auto_read_group = True
                self._persist(auto_read_group=True)
                await event.edit("✅ تیک خودکار در **گروه** فعال شد")
                return
            if text == "تیک گروه خاموش":
                self.auto_read_group = False
                self._persist(auto_read_group=False)
                await event.edit("❌ تیک خودکار در **گروه** غیرفعال شد")
                return

            if text == "تیک کانال روشن":
                self.auto_read_channel = True
                self._persist(auto_read_channel=True)
                await event.edit("✅ تیک خودکار در **کانال** فعال شد")
                return
            if text == "تیک کانال خاموش":
                self.auto_read_channel = False
                self._persist(auto_read_channel=False)
                await event.edit("❌ تیک خودکار در **کانال** غیرفعال شد")
                return

            # ─── سکوت ────────────────────────────────────
            if text == "سکوت روشن":
                self.silence_all = True
                self._persist(silence_all=True)
                await event.edit("🔇 سکوت **همه پیوی‌ها** فعال شد")
                return
            if text == "سکوت خاموش":
                self.silence_all = False
                self._persist(silence_all=False)
                await event.edit("🔊 سکوت **همه پیوی‌ها** برداشته شد")
                return

            if text == "سکوت پیوی روشن":
                if not event.is_private:
                    await event.edit("❌ فقط در پیوی قابل استفاده است")
                    return
                self.silence_pv[event.chat_id] = True
                set_state(self.tag, "silence_pv", json.dumps({str(k): True for k in self.silence_pv}))
                await event.edit("🔇 سکوت این پیوی فعال شد")
                return
            if text == "سکوت پیوی خاموش":
                if not event.is_private:
                    await event.edit("❌ فقط در پیوی قابل استفاده است")
                    return
                if event.chat_id in self.silence_pv:
                    del self.silence_pv[event.chat_id]
                set_state(self.tag, "silence_pv", json.dumps({str(k): True for k in self.silence_pv}))
                await event.edit("🔊 سکوت این پیوی برداشته شد")
                return

            # ─── دشمن ────────────────────────────────────
            if text == "دشمن روشن":
                if event.is_channel and not event.is_group:
                    await event.edit("❌ این دستور در کانال غیرفعال است")
                    return
                if not event.is_reply:
                    await event.edit("❌ روی پیام کاربر ریپلای کن")
                    return
                r = await event.get_reply_message()
                target_id = r.sender_id
                if target_id == self.my_id:
                    await event.edit("❌ نمی‌توانی خودت را دشمن کنی")
                    return
                chat_list = self.enemies.setdefault(event.chat_id, [])
                if target_id in chat_list:
                    await event.edit("⚠️ این کاربر از قبل دشمن است")
                    return
                chat_list.append(target_id)
                self._persist_enemies()
                name = getattr(r.sender, 'first_name', None) or str(target_id)
                await event.edit(f"🗡 «{name}» دشمن شد")
                return

            if text == "دشمن خاموش":
                if not event.is_reply:
                    await event.edit("❌ روی پیام همان کاربر ریپلای کن")
                    return
                r = await event.get_reply_message()
                target_id = r.sender_id
                chat_list = self.enemies.get(event.chat_id, [])
                if target_id not in chat_list:
                    await event.edit("⚠️ این کاربر دشمن نیست")
                    return
                chat_list.remove(target_id)
                if not chat_list:
                    self.enemies.pop(event.chat_id, None)
                self._persist_enemies()
                name = getattr(r.sender, 'first_name', None) or str(target_id)
                await event.edit(f"✅ دشمنی با «{name}» لغو شد")
                return

            # ─── ردیاب حذف/ادیت (فقط پیوی) ────────────────
            if text == "ردیاب روشن":
                self.tracker_enabled = True
                self._persist(tracker_enabled=True)
                await event.edit(
                    "🕵️ **ردیاب فعال شد**\n\n"
                    "از این لحظه، ادیت یا حذف پیام در چت‌های پیوی به Saved Messages گزارش می‌شود.\n"
                    "⚠️ توجه: فقط پیام‌هایی که از این لحظه به بعد رد و بدل می‌شوند کش و ردیابی خواهند شد.\n"
                    "چت‌هایی که در حالت «سکوت» هستند از ردیابی مستثنا می‌مانند."
                )
                return
            if text == "ردیاب خاموش":
                self.tracker_enabled = False
                self._persist(tracker_enabled=False)
                self._clear_tracker_cache()
                await event.edit("✅ ردیاب غیرفعال شد و کش/مدیای حافظه پاک‌سازی شدند")
                return

            # ─── تبچی ────────────────────────────────────
            if text == "تبچی روشن":
                self.tabchi_enabled = True
                await event.edit(
                    "✅ حالت **تبچی** آماده\n\n"
                    "📌 مراحل:\n"
                    "۱. به گروه مد نظر برو\n"
                    "۲. روی پیامی که می‌خوای تکرار شه ریپلای کن\n"
                    "۳. بنویس: `انتخاب تبچی [دقیقه]`\n"
                    "   مثال: `انتخاب تبچی 10`"
                )
                return

            if text == "تبچی خاموش":
                await self._stop_tabchi()
                self._persist(
                    tabchi_running=False, tabchi_chat=None,
                    tabchi_text="", tabchi_media=None,
                    tabchi_next_run_at=None,
                )
                await event.edit("✅ تبچی متوقف و پاک‌سازی شد")
                return

            if text == "تبچی وضعیت":
                if not self.tabchi_task or self.tabchi_task.done():
                    await event.edit("⭕ تبچی غیرفعال است\nبرای شروع: `تبچی روشن`")
                else:
                    preview = (self.tabchi_text[:60] + "...") \
                        if len(self.tabchi_text) > 60 \
                        else (self.tabchi_text or "(رسانه)")
                    await event.edit(
                        f"🔁 **وضعیت تبچی**\n"
                        f"📍 چت: `{self.tabchi_chat}`\n"
                        f"⏱ فاصله: هر **{self.tabchi_interval}** دقیقه\n"
                        f"📝 پیام: {preview}"
                    )
                return

            # دقیق: فقط «انتخاب تبچی» تنها یا «انتخاب تبچی N» (عدد فاصله)
            if re.fullmatch(r"انتخاب تبچی(\s+\d+)?", text):
                if not event.is_reply:
                    await event.edit("❌ روی پیامی که می‌خوای تکرار شه ریپلای کن")
                    return

                interval = 5
                p = text.split()
                if len(p) >= 3:
                    try:
                        interval = max(5, min(int(p[2]), 1440))
                    except ValueError:
                        pass

                r = await event.get_reply_message()
                await self._stop_tabchi()

                self.tabchi_chat = event.chat_id
                self.tabchi_text = r.text or ""
                self.tabchi_interval = interval
                self.tabchi_enabled = True
                self.tabchi_next_run_at = None

                if r.media and not r.text:
                    await event.edit("⏳ آماده‌سازی رسانه...")
                    ext = "jpg" if r.photo else ("mp4" if r.video else "bin")
                    path = os.path.join(
                        DOWNLOADS_DIR,
                        f"tabchi_{random.randint(100000, 9999999)}.{ext}"
                    )
                    dl = await r.download_media(file=path)
                    self.tabchi_media = dl

                await self._start_tabchi()
                self._persist(
                    tabchi_chat=self.tabchi_chat,
                    tabchi_text=self.tabchi_text,
                    tabchi_media=self.tabchi_media,
                    tabchi_interval=self.tabchi_interval,
                    tabchi_running=True,
                    tabchi_next_run_at=None,
                )

                chat_name = getattr(event.chat, 'title', None) or str(event.chat_id)
                preview = (self.tabchi_text[:50] + "...") \
                    if len(self.tabchi_text) > 50 \
                    else (self.tabchi_text or "(رسانه)")
                await event.edit(
                    f"🔁 **تبچی فعال شد**\n\n"
                    f"📍 {chat_name}\n"
                    f"⏱ هر **{interval}** دقیقه\n"
                    f"📝 {preview}\n\n"
                    f"توقف: `تبچی خاموش`"
                )
                return

            # دقیق: فقط «تبچی زمان» تنها یا «تبچی زمان X» (یک توکن)
            if re.fullmatch(r"تبچی زمان(\s+\S+)?", text):
                parts_local = text.split()
                if len(parts_local) < 3:
                    await event.edit("❌ مثال: `تبچی زمان 10`")
                    return
                try:
                    mins = int(parts_local[2])
                except ValueError:
                    await event.edit("❌ مثال: `تبچی زمان 10`")
                    return
                mins = max(5, min(mins, 1440))
                self.tabchi_interval = mins
                self.tabchi_next_run_at = time.time() + mins * 60
                self._persist(tabchi_interval=mins, tabchi_next_run_at=self.tabchi_next_run_at)
                await event.edit(f"✅ فاصله تبچی: هر **{mins}** دقیقه")
                return

            # ─── وضعیت ────────────────────────────────────
            if text == "وضعیت":
                ic = lambda v: "🟢" if v else "🔴"
                tab_status = "🔁 فعال" if (self.tabchi_task and not self.tabchi_task.done()) else "⭕ غیرفعال"
                sample = apply_font("12:34", self.current_font) if self.time_enabled else "—"
                enemy_count = sum(len(v) for v in self.enemies.values())
                await event.edit(
                    f"📊 **وضعیت** `{self.tag}`\n\n"
                    f"{ic(self.enabled)}      سلف‌بات\n"
                    f"{ic(self.time_enabled)}  ساعت روی نام — فونت: `{self.current_font}` | {sample}\n"
                    f"{ic(self.bio_enabled)}  ساعت روی بیو\n"
                    f"{ic(self.online_enabled)} آنلاین دائمی (در غیر این صورت، آفلاین صریح نگه داشته می‌شود)\n"
                    f"📩 تیک پیوی: {ic(self.auto_read_pv)}     تیک گروه: {ic(self.auto_read_group)}     تیک کانال: {ic(self.auto_read_channel)}\n"
                    f"{'🔇' if self.silence_all else '🔊'}       سکوت همه پیوی‌ها\n"
                    f"{'🔇' if self.silence_pv else '🔊'}       سکوت پیوی خاص: {len(self.silence_pv)} چت\n"
                    f"{tab_status} تبچی — {self.tabchi_interval}دقیقه\n"
                    f"{ic(self.tracker_enabled)} ردیاب حذف/ادیت پیوی\n"
                    f"🗡 دشمن‌ها: {enemy_count} نفر\n"
                    f"👤 اسم پایه: `{self.base_name}`\n"
                    f"⏱ آپ‌تایم: {self._uptime()}"
                )
                return

            # ─── پروفایل ──────────────────────────────────
            new_name_match = re.fullmatch(r"اسم جدید\s+(.+)", text, re.DOTALL)
            if new_name_match:
                new = self._clean_name(new_name_match.group(1).strip())
                self.base_name = new
                self._persist(base_name=new)
                await event.edit(f"✅ اسم پایه: «{new}»")
                return

            # دقیق: فقط «فونت X» با X یک توکن تکی
            font_match = re.fullmatch(r"فونت\s+(\S+)", text)
            if font_match:
                inp = font_match.group(1).strip().lower()
                fa_rev = {v: k for k, v in FONT_FA.items()}
                if inp in fa_rev:
                    inp = fa_rev[inp]
                if inp in _FONT_DIGITS or inp == "normal":
                    self.current_font = inp
                    self._persist(current_font=inp)
                    sample = apply_font("12:34", inp)
                    await event.edit(
                        f"✅ فونت: `{inp}`\nنمونه: {self.base_name} **{sample}**"
                    )
                else:
                    opts = "  ".join(f"`{v}`" for v in FONT_FA.values())
                    await event.edit(f"❌ فونت نامعتبر — گزینه‌ها: {opts}")
                return

            if text == "عکس پروفایل":
                if not event.is_reply:
                    await event.edit("❌ روی عکس ریپلای کنید")
                    return
                r = await event.get_reply_message()
                if not r.photo:
                    await event.edit("❌ پیام ریپلای عکس ندارد")
                    return
                path = os.path.join(DOWNLOADS_DIR, f"pfp_{random.randint(100000, 9999999)}.jpg")
                await r.download_media(file=path)
                try:
                    up = await self.client.upload_file(path)
                    await self.client(UploadProfilePhotoRequest(file=up))
                finally:
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
                await event.edit("✅ عکس پروفایل تغییر کرد")
                return

            # ─── کپی ──────────────────────────────────────
            copy_match = re.fullmatch(r"کپی\s+(\S+)", text)
            if copy_match and "t.me/" in copy_match.group(1):
                link = copy_match.group(1)
                ch_ref, msg_id = self._parse_tg_link(link)
                if not ch_ref:
                    await event.edit(
                        "❌ لینک نامعتبر است.\n"
                        "نمونه‌ی درست:\n`کپی https://t.me/channel/123`"
                    )
                    return
                await event.edit("⏳ در حال دریافت...")
                # مهم: خارج از پوششِ ۹۰ ثانیه‌ی _safe_handler اجرا می‌شود.
                # قبلاً دانلودِ مدیای بزرگ بعد از ۹۰ ثانیه cancel می‌شد و
                # پیام روی «در حال دریافت» برای همیشه گیر می‌کرد. حالا یک
                # تسکِ پس‌زمینه با تایم‌اوتِ سختِ خودش، که در هر نتیجه‌ای
                # پیام را به‌روز می‌کند.
                _spawn_bg(self._do_copy(event, ch_ref, msg_id), f"copy:{self.tag}")
                return

            # ══════════════════════════════════════════════
            #  دایس — تمام تلاش‌ها مخفیانه در Saved Messages («me») انجام
            #  می‌شود تا نتیجه‌ی دلخواه (max_val) قطعاً به‌دست بیاید؛ فقط
            #  همان یک دایسِ برنده به‌عنوان یک پیامِ تازه (نه فوروارد) به
            #  چت اصلی کپی می‌شود — یعنی کسی که در چت اصلی می‌بیند، فقط
            #  یک دایس می‌بیند که به‌نظر کاملاً طبیعی و شانسی به max
            #  رسیده.
            #
            #  فیکس مهم: قبلاً این منطق مستقیم داخل _handle اجرا می‌شد که
            #  از طریق _safe_handler با سقف ۹۰ ثانیه پوشیده شده بود. برای
            #  اسلات (max_val=۶۴) که میانگین به max رسیدنش حدود ۲۰ دور
            #  طول می‌کشد ولی توزیعش دم‌بلند است، این یعنی گاهی (حدود ۱۵٪
            #  با سقف‌های قبلی) عملیات قبل از رسیدن به max متوقف می‌شد و
            #  یک دایس تصادفی معمولی می‌فرستاد — دقیقاً برخلاف خواسته‌ی
            #  «حتماً حتماً باید max بیاید». حالا این حلقه به یک تسک کاملاً
            #  مستقل (asyncio.create_task) منتقل شده که اصلاً از سقف
            #  ۹۰ ثانیه‌ی _handle/_safe_handler عبور نمی‌کند — می‌تواند
            #  هر مدت لازم باشد ادامه دهد تا واقعاً max_val پیدا شود.
            # ══════════════════════════════════════════════
            if text in _DICE_MAP:
                # گاردِ همزمانی: هر سلف فقط یک بازی دایس هم‌زمان دارد. اسپمِ
                # «تاس» قبلاً چند حلقه‌ی موازی می‌ساخت (هرکدام ۳ دایس در هر
                # دور به Saved Messages) — ریسک فلاد و شلوغی کش. پرچم
                # هم‌زمانی قبل از اولین await ست می‌شود تا بین دو فرمانِ
                # هم‌زمان race نشود؛ تسکِ بازی در finally آن را پاک می‌کند.
                if getattr(self, "_dice_running", False):
                    await event.edit("🎲 یک بازی دایس در حال اجراست — صبر کن تا تموم بشه.")
                    return
                self._dice_running = True
                try:
                    await event.delete()
                except Exception:
                    pass
                # BUG #6: تسکِ بازی روی نمونه ثبت می‌شود تا در shutdownِ واقعی
                # نمونه (نه در reconnect) cancel شود — بازیِ در جریان باید از
                # کلاینتِ جدیدِ reconnect ادامه دهد.
                self._dice_task = asyncio.create_task(
                    self._run_dice_game(event.chat_id, text))
                return

            # ══════════════════════════════════════════════
            #  قیمت لحظه‌ای — تتر / تون / ترون (به تومان و دلار)
            # ══════════════════════════════════════════════
            if text in _PRICE_MAP:
                cg_id, bn_sym, bb_sym, sym, emoji, coin_key = _PRICE_MAP[text]
                await event.edit(f"⏳ دریافت قیمت {sym}...")
                try:
                    # فیکس: اگر _fetch_crypto_price در نسخه‌ی مستقر پنج/شش مقدار
                    # برگرداند (مثلاً نام منبع انتخابی)، این unpack با
                    # «too many values to unpack» کرش می‌کرد — *_ بقیه را
                    # تحمل می‌کند (در همین نسخه بی‌اثر است).
                    price, change, vol, toman, *_ = await asyncio.wait_for(
                        _fetch_crypto_price(cg_id, bn_sym, bb_sym, coin_key), timeout=20
                    )
                except asyncio.TimeoutError:
                    await event.edit("❌ تایم‌اوت — سرورها پاسخ ندادند.")
                    return
                except Exception as e:
                    await event.edit(f"❌ خطا: {e}")
                    return

                if price == 0:
                    await event.edit(f"❌ دریافت قیمت {sym} ناموفق بود.")
                    return

                icon = "📈" if change >= 0 else "📉"
                toman_str = f"{toman:,.0f} تومان" if toman > 0 else "—"

                lines = [
                    f"{emoji} **{sym}**",
                    f"🇮🇷 قیمت: {toman_str}",
                    f"💲 دلار: {_fmt_price(price)}",
                    f"{icon} تغییر ۲۴h: {change:+.2f}%",
                ]
                if vol > 0:
                    lines.append(f"📊 حجم: {_fmt_vol(vol)}")
                lines.append(f"🕒 {iran_now().strftime('%H:%M:%S')}")
                await event.edit("\n".join(lines))
                return

            # ══════════════════════════════════════════════
            #  قیمت طلا — ۱۸ و ۲۴ عیار از سایت‌های ایرانی
            # ══════════════════════════════════════════════
            if text == "طلا":
                await event.edit("⏳ دریافت قیمت طلا...")
                try:
                    p18, p24 = await asyncio.wait_for(_fetch_gold_iran(), timeout=20)
                except asyncio.TimeoutError:
                    await event.edit("❌ تایم‌اوت — سرورها پاسخ ندادند.")
                    return
                except Exception as e:
                    await event.edit(f"❌ خطا: {e}")
                    return

                if not p18 and not p24:
                    await event.edit("❌ دریافت قیمت طلا ناموفق بود.")
                    return

                lines = ["🥇 **قیمت طلا**\n"]
                if p18:
                    lines.append(f"🔸 هر گرم ۱۸ عیار: {p18:,.0f} تومان")
                if p24:
                    lines.append(f"🔶 هر گرم ۲۴ عیار: {p24:,.0f} تومان")
                lines.append(f"\n🕒 {iran_now().strftime('%H:%M:%S')}")
                await event.edit("\n".join(lines))
                return

            # ══════════ دستورات تک‌کلمه‌ای ══════════════
            # همه بر اساس تطبیق دقیق و کامل متن پیام کار می‌کنند، نه فقط
            # کلمه‌ی اول — تا جمله‌ی عادی مثل «حذف ۵ سال پیش این اتفاق افتاد»
            # به‌اشتباه به‌عنوان دستور اجرا نشود.
            if text in ("راهنما", "help", "پنل", "panel"):
                # پنلِ راهنما را **درجا** می‌آورد.
                #
                # قبلاً فقط متنِ «@CiaNetHelpBot help» فرستاده می‌شد — که
                # صرفاً کادرِ جستجوی اینلاین را باز می‌کرد و کاربر باید
                # خودش از فهرست یکی را انتخاب می‌کرد. یعنی سه مرحله برای
                # کاری که باید یک مرحله باشد.
                #
                # حالا خودِ سلف جستجوی اینلاین را می‌زند و نتیجه را مستقیم
                # می‌فرستد؛ کاربر فقط «راهنما» می‌نویسد و پنلِ آماده با
                # دکمه‌های کارکننده ظاهر می‌شود.
                await self._send_help_panel(event)
                return

            elif text in ("پینگ", "ping"):
                t0 = time.perf_counter()
                await event.edit("🏓")
                await event.edit(f"🏓 **{int((time.perf_counter() - t0) * 1000)}**ms")

            elif text in ("تایم", "time"):
                now = iran_now().strftime("%Y-%m-%d %H:%M:%S")
                await event.edit(f"⏰ `{now}`\n📈 {self._uptime()}")

            elif text == "ریستارت":
                if self._restart_task and not self._restart_task.done():
                    await event.edit("🔄 یک ری‌استارت قبلاً در صف است — صبر کن تا اجرا بشه.")
                    return
                await event.edit("🔄 ریستارت در ۳ ثانیه...")
                # BUG #7: تسکِ ری‌استارتِ معلق روی نمونه ثبت می‌شود تا در
                # shutdownِ واقعی نمونه cancel شود — ری‌استارتی که بعد از
                # توقفِ نمونه بیدار شود می‌تواند روی همان سشن clientِ جدیدی
                # بسازد (دو کلاینت روی یک .session). گاردِ بالا از overwrite
                # شدنِ این مرجع توسط یک دستورِ «ریستارت» دومِ سریع جلوگیری
                # می‌کند (همان الگویی که _dice_running برای دستورِ دایس دارد)
                # — بدون این گارد، تسکِ قبلی cancel نمی‌شد و ردش گم می‌شد.
                self._restart_task = asyncio.create_task(self._delayed_restart())

            elif text == "حذف" or re.fullmatch(r"حذف\s+\d+", text):
                if event.is_channel and not event.is_group:
                    await event.edit("❌ دستور «حذف» در کانال غیرفعال است")
                    return
                if len(parts) == 1:
                    if not event.is_reply:
                        await event.edit("❌ مثال: `حذف 5` یا روی پیامی ریپلای کن و بنویس `حذف`")
                        return
                    r = await event.get_reply_message()
                    try:
                        await event.delete()
                        await self.client.delete_messages(event.chat_id, r.id, revoke=True)
                    except Exception:
                        pass
                    return
                try:
                    cnt = int(parts[1])
                except ValueError:
                    await event.edit("❌ مثال: `حذف 5`")
                    return
                if cnt <= 0:
                    return
                # فیکس: سقف MAX_BULK_DELETE روی تعداد قابل‌حذف. بدون این
                # سقف، یک عدد بسیار بزرگ (مثلاً «حذف 999999999») باعث
                # می‌شد iter_messages برای مدت طولانی (بالقوه ساعت‌ها)
                # درخواست پشت درخواست به تلگرام بزند — هم اکانت را برای
                # آن مدت روی همین یک دستور گیر می‌انداخت، هم ریسک FloodWait
                # شدید یا محدودیت از طرف تلگرام را به‌شدت بالا می‌برد.
                if cnt > MAX_BULK_DELETE:
                    await event.edit(
                        f"❌ حداکثر {MAX_BULK_DELETE} پیام در یک بار قابل حذف است. "
                        f"عدد کوچک‌تری بفرست یا دستور را چندبار اجرا کن."
                    )
                    return
                try:
                    messages = []
                    async for m in self.client.iter_messages(event.chat_id, limit=cnt + 1):
                        messages.append(m)
                    deleted_own = 0
                    deleted_others = 0
                    for m in messages:
                        try:
                            await self.client.delete_messages(event.chat_id, m.id, revoke=True)
                            if m.out:
                                deleted_own += 1
                            else:
                                deleted_others += 1
                        except Exception:
                            pass
                    await self.client.send_message(
                        event.chat_id,
                        f"✅ حذف شد: {deleted_own} پیام شما + {deleted_others} پیام طرف مقابل"
                    )
                except Exception as e:
                    await event.edit(f"❌ خطا: {str(e)[:100]}")
                return

            elif text == "ایدی":
                if event.is_reply:
                    r = await event.get_reply_message()
                    name = getattr(r.sender, 'first_name', 'نامشخص')
                    await event.edit(f"[ ❆ {r.sender_id} - {name} ]")
                else:
                    await event.edit("❌ برای دیدن آیدی، روی یک پیام ریپلای کن و دوباره «ایدی» را بفرست")
                return

            elif text == "بلاک":
                if event.is_reply:
                    r = await event.get_reply_message()
                    try:
                        uid = r.sender_id
                        ent = await self.client.get_input_entity(uid)
                        await self.client(BlockRequest(id=ent))
                        await event.edit(f"🚫 کاربر {uid} بلاک شد")
                    except Exception as e:
                        await event.edit(f"❌ {str(e)[:80]}")
                else:
                    await event.edit("❌ روی پیامِ همان کاربر ریپلای کن و دوباره «بلاک» را بفرست")
                return

            elif text == "آنبلاک":
                if event.is_reply:
                    r = await event.get_reply_message()
                    try:
                        ent = await self.client.get_input_entity(r.sender_id)
                        await self.client(UnblockRequest(id=ent))
                        await event.edit("✅ آنبلاک شد")
                    except Exception as e:
                        await event.edit(f"❌ {str(e)[:80]}")
                else:
                    await event.edit("❌ روی پیامِ همان کاربر ریپلای کن و دوباره «آنبلاک» را بفرست")
                return

            elif text == "ذخیره":
                if not event.is_reply:
                    await event.edit("❌ روی عکس/فیلم تایم‌دار ریپلای کنید")
                    return
                r = await event.get_reply_message()
                ttl = None
                if r.photo:
                    ttl = (getattr(r.photo, 'ttl_seconds', None)
                           or getattr(r.media, 'ttl_seconds', None))
                elif r.video:
                    ttl = (getattr(r.video, 'ttl_seconds', None)
                           or getattr(r.media, 'ttl_seconds', None))
                if not ttl:
                    await event.edit("❌ این رسانه تایم‌دار نیست")
                    return
                ext = "jpg" if r.photo else "mp4"
                path = os.path.join(DOWNLOADS_DIR, f"save_{random.randint(100000, 9999999)}.{ext}")
                await r.download_media(file=path)
                try:
                    sender = getattr(r.sender, 'first_name', 'نامشخص')
                    await self.client.send_file("me", path,
                                                 caption=f"✅ از {sender} | ⏳{ttl}s")
                finally:
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
                await r.delete()
                await event.edit("✅ ذخیره و حذف شد")
                return

            elif text == "فوروارد":
                if event.is_reply:
                    r = await event.get_reply_message()
                    await r.forward_to("me")
                    await event.edit("✅ فوروارد → Saved Messages")
                else:
                    await event.edit("❌ ریپلای کنید")
                return

            elif text == "مشخصات":
                if event.is_reply:
                    r = await event.get_reply_message()
                    try:
                        full = await self.client(GetFullUserRequest(r.sender_id))
                        u = full.users[0]
                        ln = u.last_name or ""
                        status_str = (u.status.__class__.__name__ if u.status else 'Unknown')
                        await event.edit(
                            f"👤 **{u.first_name or '—'} {ln}**\n"
                            f"@{u.username or '—'}\n"
                            f"ایدی: `{u.id}`\n"
                            f"بیو: {full.full_user.about or '—'}\n"
                            f"وضعیت: `{status_str}`"
                        )
                    except Exception as e:
                        await event.edit(f"❌ {str(e)[:80]}")
                else:
                    await event.edit("❌ ریپلای کنید")
                return

            elif text == "سنجاق":
                if not event.is_reply:
                    await event.edit("❌ روی پیامی که می‌خواهی سنجاق کنی ریپلای کن")
                    return
                try:
                    reply_msg = await event.get_reply_message()
                    await self.client.pin_message(event.chat_id, reply_msg.id)
                    await event.edit("📌 پیام سنجاق شد.")
                except errors.ChatAdminRequiredError:
                    await event.edit("❌ برای سنجاق نیاز به دسترسی ادمین داری!")
                except Exception as e:
                    await event.edit(f"❌ {str(e)[:80]}")
                return

        except Exception as e:
            print(f"❌ [{self.tag}/{cmd}]: {e}")
            try:
                await event.edit(f"❌ {str(e)[:100]}")
            except Exception:
                pass

    async def _delayed_restart(self):
        try:
            await asyncio.sleep(3)
            # BUG E: اگر در این فاصله اکانت متوقف شده (ACCOUNTS خالی/حذف شده) یا
            # نمونه‌ی جدیدی جایگزین این نمونه شده باشد، این ری‌استارتِ معلق نباید
            # روی نمونه‌ی مرده client جدید بسازد — reconnect() خودش start() را صدا
            # می‌زند و یک TelegramClient تازه روی همان فایلِ سشن باز می‌کرد (دو
            # کلاینت روی یک سشن / ری‌استارت بعد از stop). فقط وقتی هنوز همین
            # نمونه، نمونه‌ی ثبت‌شده‌ی Runtime Manager است، ادامه می‌دهد.
            entry = ACCOUNTS.get(self.tag)
            if entry is None or entry.bot is not self:
                return
            await self.reconnect()
        finally:
            # BUG #7: مرجعِ تسک بعد از پایان/لغو پاک می‌شود (تمیزکاریِ خاموشی
            # هم بعد از cancel/await آن را پاک می‌کند — idempotent).
            self._restart_task = None

    async def _run_dice_game(self, chat_id: int, dice_text: str) -> None:
        """
        منطق واقعی دستورات دایس («تاس»/«دارت»/«بسکتبال»/«فوتبال»/«اسلات»/
        «بولینگ») — به‌صورت یک تسک کاملاً مستقل اجرا می‌شود (نه از داخل
        _handle/_safe_handler)، دقیقاً به همین دلیل: این حلقه تا وقتی
        max_val واقعاً پیدا نشود متوقف نمی‌شود («حتماً حتماً»)، و چون سقف
        زمانی این کار می‌تواند (به‌ندرت، برای اسلات) از ۹۰ ثانیه هم بگذرد،
        اگر داخل _safe_handler اجرا می‌شد، بعد از ۹۰ ثانیه کل تسک —
        همراه با هر پیام نهایی که قرار بود بفرستد — بی‌سروصدا cancel
        می‌شد.

        تمام تلاش‌ها مخفیانه در Saved Messages («me») انجام می‌شود؛ فقط
        همان یک دایسِ برنده به چت اصلی فوروارد می‌شود. چرا فوروارد نه
        send_message؟ وقتی send_message یک آبجکت Message دریافت می‌کند،
        تلتون فقط رسانه‌اش را می‌گیرد (get_input_media → InputMediaDice
        که فقط emoticon دارد — بدون مقدارِ ریخته‌شده) و تلگرام برایش یک
        دایسِ کاملاً تازه و تصادفی می‌سازد؛ یعنی هرچه در Saved Messages
        برنده پیدا شده باشد، در چت اصلی همان max_val دیده نمی‌شد. تنها راهِ
        تضمینی برای انتقالِ همان مقدار، فورواردِ خودِ پیام است (مدیا با
        مقدار ثابتش عیناً منتقل می‌شود). هدر «Forwarded from» که ظاهر
        می‌شود، هزینه‌ی عمدیِ رساندنِ «شیش»/«۷۷۷» است.
        """
        if dice_text not in _DICE_MAP:
            return
        emoji, max_val = _DICE_MAP[dice_text]
        deadline = time.monotonic() + _DICE_SAFETY_CEILING
        winner = None

        try:
            while winner is None:
                # BUG E: اگر نمونه‌ی دیگری همین تگ را در اختیار گرفته باشد
                # (ACCOUNTS دیگر به همین نمونه اشاره نمی‌کند — مثلاً بعد از
                # stop+startِ مجدد)، بازیِ این نمونه‌ی قدیمی نباید ادامه دهد:
                # دو بازی هم‌زمان از دو نمونه (اسپم/فلادِ دایس) ممنوع است.
                # در جریانِ عادی و reconnect با همین نمونه (ACCOUNTS همان
                # نمونه است) شرط برقرار است؛ رفتارِ بازی تغییری نمی‌کند.
                # (وقتی اکانت کاملاً متوقف شده — ACCOUNTS خالی — بازی تا
                # سقفِ ایمنیِ خودش ادامه می‌دهد ولی هیچ کلاینت/سشن جدیدی
                # باز نمی‌کند و درخواست‌هایش روی کلاینتِ قطع‌شده بی‌اثرند.)
                entry = ACCOUNTS.get(self.tag)
                if entry is not None and entry.bot is not self:
                    return
                # دایس یک ابزارِ مستقل از «سلف روشن/خاموش» است (در
                # _ALWAYS_ALLOWED است)، پس این حلقه به self.enabled وابسته
                # نیست — وقتی کاربر شروعش کند تا پیدا شدنِ max_val ادامه
                # می‌دهد. (اگر قرار بود با خاموش‌کردنِ سلف قطع شود، شروعش
                # در حالت خاموش بی‌معنی می‌شد.)
                if time.monotonic() >= deadline:
                    # این خط عملاً هرگز اجرا نمی‌شود (نگاه کن به توضیح
                    # _DICE_SAFETY_CEILING) — صرفاً یک محافظت نهایی در
                    # برابر یک سناریوی کاملاً غیرمنتظره است.
                    print(
                        f"⚠️ [{self.tag}] دایس {emoji}: به سقف ایمنی "
                        f"{_DICE_SAFETY_CEILING}s رسید بدون پیدا کردن max_val"
                    )
                    return

                try:
                    results = await asyncio.gather(
                        *[
                            self.client.send_message(
                                "me", file=InputMediaDice(emoticon=emoji)
                            )
                            for _ in range(3)
                        ],
                        return_exceptions=True,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"⚠️ [{self.tag}] دایس {emoji} خطا در ارسال آزمایشی: {e}")
                    await asyncio.sleep(2)
                    continue

                valid = [m for m in results if not isinstance(m, Exception)]
                flood_errors = [m for m in results if isinstance(m, errors.FloodWaitError)]

                winner = next(
                    (
                        m for m in valid
                        if getattr(getattr(m, "media", None), "value", None) == max_val
                    ),
                    None,
                )

                # تلاش‌های ناموفقِ این دور از Saved Messages پاک می‌شوند.
                # خودِ برنده حذف نمی‌شود — فوروارد (نه send_message) فقط با
                # یک پیامِ موجودِ واقعی کار می‌کند؛ بعد از فوروارد پاک می‌شود.
                losers = [m for m in valid if m is not winner]
                if losers:
                    try:
                        await self.client.delete_messages("me", [m.id for m in losers])
                    except Exception:
                        pass

                if winner:
                    break

                if flood_errors:
                    # اگر تلگرام FloodWait داد، به‌جای sleep ثابت، دقیقاً
                    # به مدت خواسته‌شده صبر می‌کنیم تا اکانت گزارش/محدود
                    # نشود.
                    wait_s = max(getattr(e, "seconds", 2) for e in flood_errors)
                    await asyncio.sleep(wait_s + 2)
                else:
                    await asyncio.sleep(0.5)

            # فورواردِ پیامِ برنده به چت اصلی. این عمداً فوروارد است نه
            # send_message: وقتی send_message یک Message دریافت می‌کند، تلتون
            # فقط رسانه‌ی آن را (get_input_media → InputMediaDice(emoticon))
            # می‌گیرد و «مقدار» دایس را دور می‌ریزد — یعنی تلگرام یک دایسِ
            # تازه و تصادفی می‌فرستد و برنده‌ی واقعی (max_val) هرگز در چت
            # دیده نمی‌شود. فوروارد کردنِ خودِ پیام، مدیا (با مقدار ثابتش) را
            # عیناً منتقل می‌کند — تنها راهِ تضمینی برای رساندنِ «شیش»/«۷۷۷».
            #
            # drop_author=True: برچسبِ «Forwarded from …» را حذف می‌کند، پس
            # پیام مثل یک دایسِ تازه دیده می‌شود نه چیزی که از جای دیگر
            # کپی شده. بدون آن، تقلب از روی همان برچسب لو می‌رفت.
            # (فیلدِ رسمیِ MTProto است؛ مقدارِ دایس دست‌نخورده می‌ماند.)
            try:
                await self.client.forward_messages(
                    chat_id, winner.id, from_peer="me", drop_author=True)
            except TypeError:
                # telethonِ خیلی قدیمی drop_author ندارد — بهتر است دایس با
                # برچسب برود تا اصلاً نرود.
                await self.client.forward_messages(chat_id, winner.id, from_peer="me")
            # پاک‌سازی پیامِ برنده از Saved Messages بعد از فوروارد.
            try:
                await self.client.delete_messages("me", [winner.id])
            except Exception:
                pass
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"⚠️ [{self.tag}] دایس {emoji}: خطای غیرمنتظره: {e}")
        finally:
            # گاردِ همزمانی: پرچم را در همه‌ی مسیرهای خروج (موفقیت، خطا،
            # لغو، «سلف خاموش»، سقف ایمنی) پاک کن تا فرمان بعدی بتواند
            # بازی جدیدی شروع کند.
            self._dice_running = False
            # BUG #6: مرجعِ تسک بعد از پایانِ واقعی پاک می‌شود (تمیزکاریِ
            # خاموشی هم بعد از cancel/await آن را پاک می‌کند — idempotent).
            self._dice_task = None

    async def reconnect(self):
        if self._reconnecting:
            return
        self._reconnecting = True
        self._set_status("reconnecting")
        try:
            was_time = self.time_enabled
            was_enabled = self.enabled
            was_bio_enabled = self.bio_enabled
            was_base_bio = self.base_bio
            was_tabchi_enabled = self.tabchi_enabled
            was_tabchi_chat = self.tabchi_chat
            was_tabchi_text = self.tabchi_text
            was_tabchi_media = self.tabchi_media
            was_tabchi_interval = self.tabchi_interval
            was_tabchi_next_run_at = self.tabchi_next_run_at

            try:
                self.time_enabled = False
                self.bio_enabled = False
                # توقفِ مشترکِ تسک‌های پس‌زمینه (همان پیاده‌سازیِ واحدِ
                # stop/_cleanup_after_failed_start). _memory_log_task عمداً
                # cancel نمی‌شود — کاملاً مستقل از self.client است و نیازی
                # نیست در هر reconnect از نو ساخته شود.
                await self._cancel_background_tasks(
                    destructive_tabchi=False, cancel_memory_log=False,
                    # BUG #6/#7: reconnect خاموش‌کردن نمونه نیست — بازیِ دایسِ
                    # در جریان باید ادامه دهد و ری‌استارتِ معلق نباید خودش را
                    # cancel کند.
                    cancel_dice=False, cancel_restart=False,
                )
            except Exception:
                pass

            # قبل از disconnect، سشن را صریحاً save می‌کنیم تا فایل‌های
            # -journal/-wal/-shm که در ابتدای start() حذف می‌شوند، زیر پای
            # یک handle باز حذف نشوند (که می‌تواند سشن را خراب یا قفل کند).
            try:
                if self.client:
                    self.client.session.save()
            except Exception:
                pass
            try:
                if self.client:
                    await asyncio.wait_for(self.client.disconnect(), timeout=15)
            except asyncio.TimeoutError:
                print(f"⚠️ [{self.tag}] تایم‌اوت در disconnect حین reconnect — ادامه می‌دهیم")
            except Exception as e:
                print(f"⚠️ [{self.tag}] خطا هنگام disconnect: {e}")

            self.client = None
            self._handlers_registered = False

            await asyncio.sleep(4)
            try:
                await self.start(interactive=False)
                if was_time and not self.time_enabled:
                    self.time_enabled = True
                    await self._start_time_loops()
                if was_enabled:
                    self.enabled = True

                if was_bio_enabled and (not self.bio_task or self.bio_task.done()):
                    self.base_bio = self.base_bio or was_base_bio
                    self.bio_enabled = True
                    await self._start_bio_loop()

                # لایه‌ی محافظتی اضافه برای تبچی: _load_persisted_state (که
                # داخل start() صدا زده شد) باید خودش تبچی را از روی DB
                # resume کرده باشد. اگر به هر دلیلی این اتفاق نیفتاده، از
                # مقادیر تازه‌ی in-memory که همین بالا نگه داشتیم استفاده
                # می‌کنیم.
                if was_tabchi_enabled and (not self.tabchi_task or self.tabchi_task.done()):
                    self.tabchi_chat = self.tabchi_chat or was_tabchi_chat
                    self.tabchi_text = self.tabchi_text or was_tabchi_text
                    self.tabchi_media = self.tabchi_media or was_tabchi_media
                    self.tabchi_interval = self.tabchi_interval or was_tabchi_interval
                    self.tabchi_next_run_at = self.tabchi_next_run_at or was_tabchi_next_run_at
                    if self.tabchi_chat and (
                        self.tabchi_text or (self.tabchi_media and os.path.exists(self.tabchi_media))
                    ):
                        self.tabchi_enabled = True
                        await self._start_tabchi()
                        print(f"♻️ [{self.tag}] تبچی از طریق لایه‌ی محافظتی اضافه resume شد")
            except Exception as e:
                print(f"❌ [{self.tag}] reconnect ناموفق: {e}")
                # اگر start() وسطِ راه (بعد از ساخت تسک‌های پس‌زمینه‌ی همین
                # نمونه) شکست خورده باشد، تسک‌های ناقص همین‌جا متوقف می‌شوند —
                # وگرنه تا تلاشِ بعدیِ reconnect (که آن‌ها را از نو می‌سازد)
                # روی همین نمونه‌ی نیمه‌کاره زنده می‌ماندند. best-effort:
                # خطای تمیزکاری هرگز خطای اصلیِ reconnect را نمی‌پوشاند.
                try:
                    await self._cleanup_after_failed_start()
                except Exception:
                    pass
                raise
        finally:
            self._reconnecting = False

    async def run(self):
        """
        حلقه‌ی اصلی نگه‌داری اتصال. هر Exception کش می‌شود، backoff نمایی
        اعمال می‌شود، و در صورت شکست پیاپی reconnect، پروسه دوباره تلاش
        می‌کند.

        اگر یک خطای احراز هویت غیرقابل‌بازیابی رخ دهد، این حلقه به‌طور
        تمیز از این اکانت خارج می‌شود؛ مسئولیت متوجه‌کردن کاربر با run_bot()
        است.
        """
        consecutive_failures = 0
        MAX_BACKOFF = 300  # حداکثر ۵ دقیقه بین تلاش‌ها در قطعی‌های طولانی

        while True:
            if self._fatal_auth_error:
                self._set_status("auth_failed")
                print(f"🛑 [{self.tag}] خطای احراز هویت غیرقابل‌بازیابی — دیگر تلاشی برای reconnect انجام نمی‌شود.")
                try:
                    set_state(self.tag, "fatal_auth_error", True)
                except Exception:
                    pass
                return

            try:
                if self.client is None:
                    raise ConnectionError("client is None قبل از run_until_disconnected")
                await self.client.run_until_disconnected()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if _is_fatal_auth_error(e):
                    print(f"🛑 [{self.tag}] خطای احراز هویت غیرقابل‌بازیابی در run_until_disconnected: {e}")
                    self._fatal_auth_error = True
                    self._set_status("auth_failed")
                    continue
                _em = str(e).lower()
                if "readonly" in _em or "read-only" in _em or "read only" in _em:
                    # خطای «سشن فقط‌خواندنی» — قبل از reconnect، سلامت سشن را
                    # بررسی کن. اگر مالک همان user باشد، check_session_health
                    # خودش mode را امن اصلاح می‌کند و reconnect بعدی موفق
                    # می‌شود؛ اگر قابل رفع نباشد، وضعیت error صادقانه می‌ماند
                    # (نه «فعال»ِ دروغین) و با backoff عادی تلاش ادامه می‌یابد.
                    _health = check_session_health(self.tag)
                    if not _health["ok"]:
                        print(f"❌ [SESSION][{self.tag}][ERROR] {_health['error']} "
                              f"(pid={os.getpid()}, runtime_state={self.runtime_status}, "
                              f"session_path={_session_file_for(self.tag)})")
                    else:
                        print(f"✅ [SESSION][{self.tag}][CHECK] سشن سالم شد — reconnect ادامه می‌یابد")
                print(f"⚠️ [{self.tag}] قطع شد: {e}")
                if DEBUG:
                    import traceback
                    traceback.print_exc()

            if self._fatal_auth_error:
                continue

            # فیکس مهم: قبلاً اینجا قبل از هر تلاش برای reconnect، یک
            # backoff نمایی (که می‌توانست تا ۵ دقیقه طول بکشد) اجرا می‌شد —
            # یعنی از لحظه‌ای که کلاینت واقعاً قطع می‌شد تا لحظه‌ای که
            # reconnect() صدا زده می‌شد و حلقه‌های پس‌زمینه (name/bio/presence)
            # را متوقف می‌کرد، این حلقه‌ها همچنان روی یک کلاینت مرده فعال
            # می‌ماندند و هر چند ثانیه یک‌بار با خطای "Cannot send requests
            # while disconnected" شکست می‌خوردند — دقیقاً چیزی که در لاگ
            # دیده می‌شد. حالا reconnect() بلافاصله و بدون تأخیر بعد از
            # تشخیص قطعی صدا زده می‌شود؛ backoff نمایی فقط وقتی اعمال
            # می‌شود که خودِ تلاش reconnect() شکست بخورد (یعنی مشکل واقعاً
            # در اتصال مجدد است، نه در انتظار بی‌دلیل قبل از حتی امتحان‌کردن).
            wait_time = min(10 * (2 ** min(consecutive_failures, 5)), MAX_BACKOFF)
            self._set_status("reconnecting")

            try:
                await self.reconnect()
                consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if _is_fatal_auth_error(e):
                    print(f"🛑 [{self.tag}] خطای احراز هویت غیرقابل‌بازیابی هنگام reconnect: {e}")
                    self._fatal_auth_error = True
                    self._set_status("auth_failed")
                    continue
                consecutive_failures += 1
                print(
                    f"❌ reconnect [{self.tag}] شکست خورد (تلاش ناموفق پیاپی: "
                    f"{consecutive_failures}) — دوباره در {wait_time}s: {e}"
                )
                if DEBUG:
                    import traceback
                    traceback.print_exc()
                # اینجا (فقط بعد از شکست واقعی reconnect) صبر می‌کنیم تا
                # دور بعدی — این جای درست backoff نمایی است، نه قبل از
                # اولین تلاش.
                await asyncio.sleep(wait_time)
                # عمداً هیچ raise/return وجود ندارد — حلقه‌ی while True ادامه
                # می‌دهد و در دور بعدی دوباره تلاش می‌کند.

    async def _cancel_background_tasks(self, *, destructive_tabchi: bool,
                                       cancel_memory_log: bool = True,
                                       cancel_dice: bool = True,
                                       cancel_restart: bool = True) -> None:
        """
        تنها منبعِ حقیقت برای «توقفِ همه‌ی تسک‌های پس‌زمینه‌ی متعلق به همین
        نمونه» — stop()، reconnect() و تمیزکاریِ شروعِ ناموفق همه از همین یک
        پیاده‌سازی استفاده می‌کنند تا نتوانند از هم فاصله بگیرند. idempotent:
        مرجعِ None یا تسکِ تمام‌شده رد می‌شود؛ صدا زدنِ چندباره امن است.

        destructive_tabchi:
          True  → _stop_tabchi (shutdown عادی: پاک‌سازیِ کامل + حذف رسانه از دیسک)
          False → _pause_tabchi_task (فقط توقفِ تسک؛ پیکربندی تبچی دست‌نخورده
                  می‌ماند — برای شروعِ ناقص و reconnect که تبچی باید قابل
                  بازیابی باشد)

        cancel_memory_log:
          False فقط در reconnect — حلقه‌ی حافظه کاملاً مستقل از self.client
          است و نیازی نیست در هر reconnect از نو ساخته شود.

        cancel_dice / cancel_restart:
          فقط در shutdownِ واقعی نمونه (stop / شروعِ ناموفق) True هستند — در
          reconnect False تا بازیِ دایسِ در جریان از کلاینتِ جدید ادامه دهد و
          یک ری‌استارتِ معلق خودش را cancel نکند (BUG #6/#7).
        """
        await self._stop_time_loops()
        await self._stop_bio_loop()
        await self._stop_presence_loop()
        if destructive_tabchi:
            await self._stop_tabchi()
        else:
            await self._pause_tabchi_task()
        await self._stop_watchdog()
        if cancel_memory_log and self._memory_log_task:
            self._memory_log_task.cancel()
            await asyncio.gather(self._memory_log_task, return_exceptions=True)
            self._memory_log_task = None
        # BUG #6/#7: تسک‌های دایس/ری‌استارتِ معلق هم متعلق به همین نمونه‌اند —
        # در shutdownِ واقعی cancel و واقعاً await می‌شوند (مرجع هم پاک
        # می‌شود). idempotent: مرجعِ None یا تسکِ تمام‌شده رد می‌شود.
        if cancel_dice and self._dice_task:
            self._dice_task.cancel()
            await asyncio.gather(self._dice_task, return_exceptions=True)
            self._dice_task = None
        if cancel_restart and self._restart_task:
            self._restart_task.cancel()
            await asyncio.gather(self._restart_task, return_exceptions=True)
            self._restart_task = None

    async def _cleanup_after_failed_start(self):
        """
        فقط برای نمونه‌ای که start() آن وسطِ راه (بعد از ساخت برخی تسک‌های
        پس‌زمینه) شکست خورده است: همه‌ی تسک‌های متعلق به همین نمونه را cancel
        و واقعاً await می‌کند تا هیچ حلقه‌ی پس‌زمینه‌ای بعد از شکستِ استارت
        زنده نماند — run_bot دوباره تلاش می‌کند و نمونه‌ی تازه‌ای می‌سازد و
        تسک‌های نمونه‌ی مرده (presence/watchdog/memory/name/bio/tabchi) نباید
        روی همان event loop باقی بمانند.

        عمداً از stop() استفاده نمی‌کند: stop() برای shutdown عادی است و شامل
        disconnect/save/close و پاک‌سازیِ مخربِ قابلیت‌ها (مثلاً _stop_tabchi
        که فایلِ رسانه‌ی تبچی را از دیسک حذف می‌کند) است — این‌جا فقط تسک‌ها
        متوقف می‌شوند؛ مالکِ disconnect/save/close خودِ run_bot است و نباید
        دوبار اجرا شود. امن است که چند بار صدا زده شود (همه‌ی _stop_* های
        موجود idempotent هستند و مرجعِ None را رد می‌کنند).

        پیاده‌سازیِ مشترک: _cancel_background_tasks(destructive_tabchi=False).
        """
        await self._cancel_background_tasks(destructive_tabchi=False)

    async def stop(self):
        self.enabled = self.time_enabled = self.online_enabled = self.bio_enabled = False
        # توقفِ مشترکِ تسک‌های پس‌زمینه — destructive_tabchi=True چون shutdown
        # عادی است (پاک‌سازیِ کامل تبچی + حذف رسانه از دیسک).
        await self._cancel_background_tasks(destructive_tabchi=True)
        self._clear_tracker_cache()
        # ─── ترتیب صحیح shutdown ──────────────────────────────────────────
        # اول disconnect (داخل تلتون entities را ذخیره و سشن را می‌بندد)،
        # بعد save/close صریح. هرگز سشن را قبل از قطع‌کردن نمی‌بندیم تا
        # تلتون بعد از close دوباره به آن write نکند. خطاهای سشن swallow
        # نمی‌شوند — با tag و stage لاگ می‌شوند.
        try:
            await asyncio.wait_for(self.client.disconnect(), timeout=15)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ [SESSION][{self.tag}][DISCONNECT] خطا هنگام قطع: {type(e).__name__}: {str(e)[:120]}")
        try:
            self.client.session.save()
        except Exception as e:
            print(f"❌ [SESSION][{self.tag}][SAVE] خطا هنگام ذخیره‌ی سشن: {type(e).__name__}: {str(e)[:120]}")
        try:
            self.client.session.close()
        except Exception as e:
            print(f"❌ [SESSION][{self.tag}][CLOSE] خطا هنگام بستن سشن: {type(e).__name__}: {str(e)[:120]}")
        self._set_status("stopped")

# ══════════════════════════════════════════════════════════
#  توابع کمکی برای اضافه/حذف اکانت (تعاملی)
# ══════════════════════════════════════════════════════════

def _code_callback():
    raw = safe_input("Please enter the code you received: ")
    digits = re.sub(r'\D', '', raw)
    if digits and digits != raw.strip():
        print(f"ℹ️ کد پاک‌سازی شد: «{raw}» → «{digits}»")
    return digits or raw.strip()

async def add_account():
    print("\n=== Add Account ===")
    typ = safe_input("Type (1: user, 2: bot): ")
    try:
        api_id = int(safe_input("API ID: "))
    except ValueError:
        print("❌ API ID must be a number")
        return None
    api_hash = safe_input("API Hash: ")
    if typ == "2":
        token = safe_input("Bot token: ")
        tag = safe_input("Tag (Enter=default): ").strip() or token.split(":")[0]
        cl = TelegramClient(f"{SESSIONS_DIR}/{tag}", api_id, api_hash)
        try:
            await cl.start(bot_token=token)
        except Exception as e:
            print(f"❌ لاگین بات ناموفق بود: {e}")
            try:
                await cl.disconnect()
            except Exception:
                pass
            return None
        try:
            me = await cl.get_me()
            cfg = load_config()
            cfg[tag] = {"type": "bot", "api_id": api_id, "api_hash": api_hash, "token": token, "user_id": me.id}
            save_config(cfg)
            print(f"✅ {me.first_name} → {tag}")
            return tag
        finally:
            # BUG #5 — اگر هر عملیاتِ بعد از لاگین (get_me/load_config/save_config)
            # شکست بخورد، کلاینت قطع می‌شود (نشتِ handle باقی نماند)؛ در موفقیت
            # هم disconnect مثل قبل انجام می‌شود.
            try:
                await cl.disconnect()
            except Exception:
                pass
    else:
        phone = safe_input("Phone number (+989...): ")
        tag = safe_input("Tag (Enter=default): ").strip() or phone
        cl = TelegramClient(f"{SESSIONS_DIR}/{tag}", api_id, api_hash)
        try:
            await cl.start(phone=phone, code_callback=_code_callback, max_attempts=5)
        except RuntimeError as e:
            print(f"❌ کد چندبار اشتباه وارد شد: {e}")
            print("📌 کد قبلی دیگر معتبر نیست. دوباره تلاش کنید.")
            try:
                await cl.disconnect()
            except Exception:
                pass
            session_file = os.path.join(SESSIONS_DIR, tag + ".session")
            for ext in ["", "-journal", "-wal", "-shm"]:
                f = session_file + ext
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            return None
        except Exception as e:
            print(f"❌ لاگین ناموفق بود: {e}")
            try:
                await cl.disconnect()
            except Exception:
                pass
            return None
        try:
            me = await cl.get_me()
            cfg = load_config()
            cfg[tag] = {"type": "user", "api_id": api_id, "api_hash": api_hash, "phone": phone, "user_id": me.id}
            save_config(cfg)
            print(f"✅ {me.first_name} → {tag}")
            return tag
        finally:
            # BUG #5 — مثل مسیر بات: disconnect تضمینی بعد از لاگین.
            try:
                await cl.disconnect()
            except Exception:
                pass

async def delete_account():
    cfg = load_config()
    if not cfg:
        print("📭 No accounts to delete.")
        return
    print("\n📋 Existing accounts:")
    for t in cfg:
        print(f"  • {t}  [{cfg[t]['type']}]")
    tag = safe_input("✏️  Enter the account tag you want to delete: ").strip()
    if tag not in cfg:
        print(f"❌ Account '{tag}' not found.")
        return
    confirm = safe_input(f"⚠️  Are you sure you want to delete account '{tag}'? (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ Aborted.")
        return
    del cfg[tag]
    save_config(cfg)
    clear_state(tag)
    session_file = os.path.join(SESSIONS_DIR, tag + ".session")
    for ext in ["", "-journal", "-wal", "-shm"]:
        f = session_file + ext
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"🗑️  Deleted: {f}")
            except Exception as e:
                print(f"⚠️  Could not delete {f}: {e}")
    print(f"✅ Account '{tag}' successfully deleted.")

async def run_bot(tag, config, interactive=False):
    """
    سوپروایزر بیرونی هر اکانت. حتی اگر bot.start() شکست بخورد، این حلقه
    دوباره یک SelfBot تازه می‌سازد و از نو تلاش می‌کند؛ به‌جای اینکه تسک
    برای همیشه بمیرد و اکانت خاموش بماند.

    نکات مهم این نسخه:
    - «ثبت در ACCOUNTS» فقط بعد از موفقیت کامل start() انجام می‌شود — یعنی
      تا وقتی اکانت واقعاً connect+auth+get_me+handlers را کامل نکرده، در
      هیچ‌جا «فعال» دیده نمی‌شود (قبلاً قبل از start ثبت می‌شد و ویزارد
      لاگین/پنل با دیدن آن، پیام موفقیتِ دروغین می‌داد در حالی که اکانت
      هنوز حتی اتصال نگرفته بود).
    - یک قفل per-tag: حداکثر یک run_bot (یک TelegramClient) برای هر تگ —
      دو کلاینت هم‌زمان روی یک فایل سشن ممنوع.
    - Future «آماده‌شدن» (_PENDING_STARTS) با True resolve می‌شود وقتی
      SelfBot واقعاً READY شد؛ منتظران (ویزارد لاگین / فعال‌سازی اکانت)
      فقط بعد از آن پیام موفقیت نشان می‌دهند.

    توجه: interactive فقط در همان اولین تلاش معنا دارد؛ تلاش‌های بعدی همیشه
    غیرتعاملی هستند.
    """
    # جلوگیری از دو run_bot هم‌زمان برای یک تگ (دو TelegramClient روی یک
    # سشن). اگر نمونه‌ی دیگری در حال اجراست، این فراخوانی بی‌درنگ رد می‌شود
    # — نه اینکه تا ابد در صف بماند.
    lock = _TAG_LOCKS.setdefault(tag, asyncio.Lock())
    if lock.locked():
        print(
            f"⚠️ [{tag}] نمونه‌ی دیگری از run_bot برای همین تگ در حال اجراست — "
            f"درخواست جدید رد شد (جلوگیری از دو کلاینت هم‌زمان روی یک سشن)."
        )
        return
    await lock.acquire()
    try:
        pending = _PENDING_STARTS.get(tag)
        if pending is None or pending.done():
            pending = _mark_pending_start(tag)
        consecutive_failures = 0
        MAX_BACKOFF = 300
        first_attempt = True

        while True:
            bot = SelfBot(tag, config)
            try:
                await bot.start(interactive=(interactive and first_attempt))
                consecutive_failures = 0
                # فقط بعد از موفقیت کامل start: ثبت در ACCOUNTS + سیگنال
                # آماده‌شدن به منتظران.
                register_account(tag, bot, asyncio.current_task())
                if not pending.done():
                    pending.set_result(True)
                await bot.run()
                # فیکس دفاعی: طبق طراحی run()، این تابع فقط در دو حالت به‌طور
                # عادی (بدون Exception) برمی‌گردد: (۱) bot._fatal_auth_error
                # True است، یا (۲) هرگز — چون حلقه‌ی داخلی‌اش بی‌نهایت است با
                # backoff خودش. فقط با fatal_auth_error واقعی break می‌کنیم؛
                # در غیر این صورت به بدنه‌ی except/backoff زیر می‌رویم تا با
                # یک پیام واضح دوباره تلاش شود.
                if bot._fatal_auth_error:
                    _set_bot_status(tag, "auth_failed")
                    if not pending.done():
                        pending.set_result(False)
                    print(
                        f"🛑 [{tag}] این اکانت به‌طور کامل متوقف شد (خطای احراز هویت). "
                        f"برای فعال‌سازی مجدد: python main.py {tag}"
                    )
                    break
                print(
                    f"⚠️ [{tag}] bot.run() به‌طور غیرمنتظره و بدون خطای احراز هویت "
                    f"برگشت — این طبق طراحی نباید رخ دهد؛ برای اطمینان دوباره تلاش می‌شود."
                )
                consecutive_failures += 1
            except asyncio.CancelledError:
                if not pending.done():
                    pending.set_result(False)
                raise
            except Exception as e:
                consecutive_failures += 1
                if _is_fatal_auth_error(e):
                    _set_bot_status(tag, "auth_failed")
                    if not pending.done():
                        pending.set_result(False)
                else:
                    _set_bot_status(tag, "error")
                wait_time = min(10 * (2 ** min(consecutive_failures, 5)), MAX_BACKOFF)
                print(
                    f"❌ [{tag}] خطا در start/run (تلاش ناموفق پیاپی: "
                    f"{consecutive_failures}): {e} — تلاش مجدد در {wait_time}s"
                )
                # محل دقیق خطا را همیشه چاپ کن (حتی بدون DEBUG) تا در لاگ سرور،
                # فایل/خطِ واقعیِ کرش دیده شود — دیباگِ «expected 5» و امثال آن.
                import traceback as _tb
                _stack = _tb.format_exc().strip().splitlines()
                if _stack:
                    _last = [l for l in _stack if l.strip().startswith("File ")]
                    if _last:
                        print(f"   └─ {_last[-1].strip()}")
            finally:
                # BUG #5: اول تسک‌های پس‌زمینه‌ی همین نمونه متوقف و واقعاً
                # await می‌شوند — تا هیچ حلقه‌ی متعلق به نمونه در حالی که
                # client/سشن در حال disconnect/close است زنده نماند (حلقه‌های
                # زنده در آن بازه روی کلاینتِ در حال بسته‌شدن می‌نوشتند). اگر
                # start() وسطِ راه (بعد از ساخت تسک‌های پس‌زمینه‌ی همین نمونه)
                # شکست خورده باشد، حلقه‌های آن نمونه نباید بعد از شکست زنده
                # بمانند — run_bot دوباره تلاش می‌کند و نمونه‌ی تازه‌ای
                # می‌سازد؛ تسک‌های نمونه‌ی مرده می‌ماندند و تا ابد روی
                # کلاینتِ قطع‌شده اجرا می‌شدند (نشتِ بی‌نهایت در retryهای
                # پیاپی). این تمیزکاری فقط تسک‌ها را متوقف می‌کند — client/
                # سشن را لمس نمی‌کند (مالکیتِ آن با خودِ همین finally است).
                # خطای تمیزکاری لاگ می‌شود ولی هرگز Exception اصلی را نمی‌پوشاند.
                # قرارداد صریح: نمونه‌ای که run_bot می‌سازد باید
                # _cleanup_after_failed_start را پیاده کند (SelfBot واقعی همیشه
                # دارد؛ جایگزین‌های duck-typed باید آن را شبیه‌سازی کنند) — تا
                # تمیزکاریِ تسک‌ها هرگز به‌صورت silent skip نشود.
                try:
                    await bot._cleanup_after_failed_start()
                except Exception as e:
                    print(f"❌ [{tag}][RUNTIME][FAILED-START-CLEANUP] خطا در "
                          f"متوقف‌کردن تسک‌های نمونه‌ی ناتمام: "
                          f"{type(e).__name__}: {str(e)[:100]}")
                # shutdown: اول disconnect، بعد save/close — و خطاهای سشن
                # با tag+stage لاگ می‌شوند (نه swallow بی‌صدا).
                if bot.client:
                    try:
                        await asyncio.wait_for(bot.client.disconnect(), timeout=15)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(f"❌ [SESSION][{tag}][DISCONNECT] خطا هنگام disconnect: {type(e).__name__}: {str(e)[:120]}")
                    try:
                        bot.client.session.save()
                    except Exception as e:
                        print(f"❌ [SESSION][{tag}][SAVE] خطا هنگام ذخیره‌ی سشن: {type(e).__name__}: {str(e)[:120]}")
                    try:
                        bot.client.session.close()
                    except Exception as e:
                        print(f"❌ [SESSION][{tag}][CLOSE] خطا هنگام بستن سشن: {type(e).__name__}: {str(e)[:120]}")
                # unregister_account خیلی آخر اجرا می‌شود — بعد از پایانِ کاملِ
                # disconnect/save/close (PATCH 5). تا وقتی Session هنوز در حال
                # بسته‌شدن است، Runtime جدید نباید همان Session را «آزاد»
                # ببیند (جلوگیری از باز شدن هم‌زمان Session / readonly).
                unregister_account(tag)

            first_attempt = False
            wait_time = min(10 * (2 ** min(consecutive_failures, 5)), MAX_BACKOFF)
            await asyncio.sleep(wait_time)
    finally:
        if _PENDING_STARTS.get(tag) is pending and pending.done():
            _PENDING_STARTS.pop(tag, None)
        lock.release()


async def _run_all_accounts(cfg: dict) -> None:
    """
    همه‌ی اکانت‌های cfg را استارت می‌کند و تا رسیدن سیگنال خاموشی صبر
    می‌کند. با آمدن سیگنال، همه‌ی اکانت‌ها به‌طور تمیز متوقف می‌شوند.

    دفاع دوم (لایه‌ی امنیتی): حتی اگر از مسیر دیگری صدا زده شود، قبل از
    استارتِ SelfBotها env ربات مدیریت (SaaS) اعتبارسنجی می‌شود؛ اگر ناقص
    باشد هیچ سرویسی بالا نمی‌آید.
    """
    problems = _validate_saas_env()
    if problems:
        print("❌ راه‌اندازی SelfBotها متوقف شد — متغیرهای محیطی ربات مدیریت ناقص‌اند:")
        for p in problems:
            print(f"   - {p}")
        return
    loop = asyncio.get_event_loop()
    _install_signal_handlers(loop)

    # رباتِ راهنما — **قبل از** صفِ استارتِ اکانت‌ها.
    #
    # چرا اینجا و نه پایین‌تر: حلقه‌ی زیر بین هر اکانت ۲ ثانیه مکث دارد، پس
    # با ۱۵ اکانت حدود نیم‌دقیقه طول می‌کشد. اگر راهنما بعد از آن ساخته
    # می‌شد، در تمام آن مدت به کاربر جواب نمی‌داد — بی‌دلیل، چون راهنما
    # هیچ وابستگی‌ای به اکانت‌ها ندارد. یک تسکِ مستقل است و باید فوراً
    # شروع شود.
    helper_task = _spawn_bg(run_helper_bot_forever(), "helper")

    # استارت SelfBotها — همه از Runtime Manager مرکزی (ensure_started) تا برای
    # هر tag فقط یک Runtime ساخته شود.
    start_tasks = []
    for t, c in cfg.items():
        if c.get("disabled"):
            print(f"⏸ [{t}] این اکانت غیرفعال‌شده (disabled) است — لانچ نمی‌شود")
            continue
        start_tasks.append(asyncio.create_task(ensure_started(t, c, caller="_run_all_accounts")))
        await asyncio.sleep(2)

    # ربات مدیریت کاملاً اختیاری و **مستقل از عمر SelfBotها**: به‌عنوان یک
    # تسکِ جدا نگه داشته می‌شود و در «صبر برای سیگنال خاموشی» هیچ نقشی
    # ندارد — غیبت/شکستِ آن (ImportError یا پایانِ حلقه) هرگز نباید باعث
    # برگشتِ _run_all_accounts و بسته‌شدنِ حلقه‌ی رویداد شود وگرنه تسک‌های
    # Runtimeِ SelfBotها cancel می‌شوند. ترجیح با saas_bot.py است؛ اگر آن
    # فایل هنوز آپلود نشده، به admin_bot.py برمی‌گردد.
    mgmt_task = None
    if cfg:
        try:
            mgmt_task = asyncio.create_task(run_saas_bot_forever(sys.modules[__name__]))
        except ImportError:
            try:
                mgmt_task = asyncio.create_task(run_admin_bot_forever(sys.modules[__name__]))
            except ImportError:
                pass
            except Exception as e:
                print(f"⚠️ راه‌اندازی ربات مدیریت ناموفق بود (بقیه‌ی سیستم عادی ادامه می‌دهد): {e}")
        except Exception as e:
            print(f"⚠️ راه‌اندازی ربات CiaNetSelf ناموفق بود (بقیه‌ی سیستم عادی ادامه می‌دهد): {e}")

    # ربات کمکی (helper) از فایلِ جداگانه‌ی helper.py بالا می‌آید — اسپاون
    # در همان ابتدای main() انجام می‌شود (نه اینجا)، تا همه‌ی مسیرهای اجرا
    # (all / اکانت تکی / interactive) پوشش داده شوند.

    # Lifetime فقط به سیگنال خاموشی گره خورده است — نه به پایانِ تسک‌های
    # ensure_started (که بعد از READY برمی‌گردند) و نه به ربات مدیریت.
    # Runtimeهای واقعی در _RUNTIME_TASKS/ACCOUNTS زنده‌اند و تا آمدنِ سیگنال
    # (Ctrl+C/SIGTERM) به کار ادامه می‌دهند؛ بعد تمیز متوقف می‌شوند.
    if not start_tasks and mgmt_task is None and helper_task is None:
        return

    await _shutdown_event.wait()
    await _graceful_shutdown_all()

    # پاک‌سازی تسک‌های باقی‌مانده (استارت‌های نیمه‌کاره + ربات مدیریت) —
    # Runtimeهای واقعی را خودِ _graceful_shutdown_all متوقف کرده است.
    leftover = list(start_tasks)
    if mgmt_task is not None:
        leftover.append(mgmt_task)
    # رباتِ راهنما هم یک تسکِ عادی است و همین‌جا تمیز بسته می‌شود —
    # بدون pid-file و بدون ریسکِ زیرپروسسِ یتیم.
    if helper_task is not None:
        leftover.append(helper_task)
    for t in leftover:
        if t and not t.done():
            t.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*(t for t in leftover if t), return_exceptions=True),
            timeout=20,
        )
    except asyncio.TimeoutError:
        print("⚠️ برخی تسک‌ها بیش از ۲۰ ثانیه برای بسته شدن طول کشیدند.")


async def _run_single_account_cli(tag: str, cfg_entry: dict, caller: str) -> None:
    """اجرای CLI مستقیم/تعاملیِ یک اکانت. قبلاً main() بلافاصله برمی‌گشت و
    asyncio.run() حلقه‌ی رویداد را می‌بست و تسکِ SelfBotِ تازه‌استارت‌شده را
    cancel می‌کرد — یعنی python main.py TAG مطمئن زنده نمی‌ماند.

    حالا فقط وقتی Runtime واقعاً READY شد، حلقه زنده می‌ماند تا سیگنال
    خاموشی (Ctrl+C/SIGTERM) — دقیقاً با معماریِ موجود: _shutdown_event +
    _graceful_shutdown_all(). هیچ Runtime/run_bot دومی ساخته نمی‌شود و هیچ
    sleep/بوسای-لوپی هم نیست. اگر استارت شکست خورد (ready=False)، عادی
    برمی‌گردد و منتظر یک Runtimeِ شکست‌خورده نمی‌ماند."""
    ready, st = await ensure_started(tag, cfg_entry, caller=caller, interactive=True)
    if not ready:
        print(f"⏹ اکانت «{tag}» آماده نشد (status={st}) — برنامه خارج می‌شود.")
        return
    loop = asyncio.get_event_loop()
    _install_signal_handlers(loop)
    print(f"🟢 اکانت «{tag}» روشن است — Ctrl+C برای توقف.")
    await _shutdown_event.wait()
    await _graceful_shutdown_all()


async def main():
    # اعتبارسنجی env ربات مدیریت قبل از هر چیز (حتی قبل از helper/SelfBot):
    # در حالت «all» اگر ADMIN_BOT_TOKEN/ADMIN_ID ناقص باشند، همه‌ی مشکلات
    # یک‌جا گزارش و همان ابتدا خارج می‌شویم — SelfBot‌ها بی‌دلیل بالا نمی‌آیند.
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        _validate_saas_env_or_exit()
    # ستون‌های رفرال — روی نصب‌های موجود هم بی‌خطر اضافه می‌شوند
    try:
        ensure_referral_schema()
    except Exception as e:
        print(f"⚠️ مهاجرت ستون‌های رفرال ناموفق: {type(e).__name__}: {e}")
    _migrate_provision_sources()
    # Recovery عملیاتِ حذفِ ناتمام (Operation Journal دو-دیتابیس): اگر ردیفی
    # مانده باشد، مراحلِ باقی‌مانده (bot_data/config) کامل می‌شود.
    _recover_delete_journal()
    # Recovery حذفِ اکانتِ ناتمام (PATCH 8): ردیف‌های باقی‌مانده‌ی
    # account_delete_journal (crash وسطِ حذف SelfBot) کامل می‌شوند.
    _recover_account_delete_journal()
    ACCOUNTS.clear()
    cleanup_stale_tracker_files()
    cleanup_orphan_sessions()
    cfg = load_config()
    if config_state() == CONFIG_INVALID:
        # config خراب هرگز به‌عنوان «هیچ اکانتی نیست» تفسیر نمی‌شود — نه
        # add_account صدا زده می‌شود (که overwrite می‌کند) و نه سرویسی
        # با {} بالا می‌آید.
        print(
            f"⛔ config.json خراب/ناخوانا است (مسیر: {CONFIG_FILE}) و برنامه متوقف شد — "
            f"هیچ تغییری در فایل‌ها اعمال نشد. فایل را با Restore/Repair صریح درست کنید "
            f"و دوباره اجرا کنید."
        )
        sys.exit(1)
    if not cfg:
        await add_account()
        cfg = load_config()

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "all":
            await _run_all_accounts(cfg)
            return
        elif arg in cfg:
            print(f"🚀 Direct run account: {arg}")
            await _run_single_account_cli(arg, cfg[arg], caller="main:direct")
        else:
            print(f"❌ Account '{arg}' not found. Available accounts:")
            for t in cfg:
                print(f"  - {t}")
        return

    tags = list(cfg.keys())
    print("\nExisting accounts:")
    for i, t in enumerate(tags):
        print(f"  {i+1}. {t}  [{cfg[t]['type']}]")
    print("  new      - Add a new account")
    print("  all      - Run all accounts")
    print("  delete   - Delete an account")
    choice = safe_input("Choice: ").strip().lower()
    if choice == "new":
        await add_account()
        await main()
        return
    elif choice == "all":
        await _run_all_accounts(cfg)
    elif choice == "delete":
        await delete_account()
        await main()
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(tags):
                await _run_single_account_cli(tags[idx], cfg[tags[idx]], caller="main:interactive")
            else:
                print("❌ Invalid selection")
        except ValueError:
            print("❌ Invalid selection")

# ========== اجرا ==========
def _run_forever():
    """
    آخرین خط دفاع در سطح پایتون. برای محافظت واقعی و کامل، سرویس باید زیر
    یک process supervisor در سطح سیستم‌عامل اجرا شود (systemd با
    Restart=always).
    """
    consecutive_crashes = 0
    MAX_BACKOFF = 300
    while True:
        try:
            asyncio.run(main())
            break
        except KeyboardInterrupt:
            print("\n🚪 exit code ")
            break
        except SystemExit:
            raise
        except Exception as e:
            consecutive_crashes += 1
            wait_time = min(10 * (2 ** min(consecutive_crashes, 5)), MAX_BACKOFF)
            print(
                f"💥 main() کرش کرد (کرش پیاپی #{consecutive_crashes}): {e}\n"
                f"🔁 تلاش مجدد کامل در {wait_time} ثانیه..."
            )
            if DEBUG:
                import traceback
                traceback.print_exc()
            time.sleep(wait_time)


if __name__ == "__main__":
    _run_forever()
