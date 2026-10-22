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
from dataclasses import dataclass, field
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
        # v2.16.0 (SPLIT): cianet/core.py → یک dirname اضافه تا همچنان
        # ریشه‌ی ریپو (کنارِ main.py) برگردد، نه پوشه‌ی cianet/.
        return os.path.dirname(os.path.dirname(os.path.abspath(here)))
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.getcwd()


# PATCH (v2.5.5 CRITICAL): اضافه‌کردن مسیر پروژه به sys.path تا import
# cianet_updater (و هر ماژول دیگر در همین دایرکتوری) کار کنه.
# قبلاً این خط نبود → در systemd که sys.path شامل WorkingDirectory نیست،
# import cianet_updater با ModuleNotFoundError شکست می‌خورد.
sys.path.insert(0, _project_dir())


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
        c.execute("UPDATE self_accounts SET api_hash = '[REDACTED]', bot_token = '[REDACTED]' WHERE api_hash IS NOT NULL OR bot_token IS NOT NULL")

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

# حداکثر تعداد لایسنس در یک درخواستِ ساخت گروهی — محدودیتِ امنیتی تا
#-DDOS/اسپمِ جدول licenses جلوگیری می‌کند و در همان زمان اجازه می‌دهد
# OWNER/ADMIN در یک حرکت تا ۱۰۰ کد بسازند.
BATCH_LICENSE_MAX = 100

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

# v2.17.0: اشتراک آزمایشی ۷ روزه برای کاربران جدید (قابل روشن/خاموش توسط مالک)
TRIAL_PLAN = "آزمایشی ۷ روزه"
TRIAL_DAYS = 7
TRIAL_SETTING_KEY = "trial_enabled"  # "1" = روشن (پیش‌فرض)
# v2.22.0 (OWNER-REQUEST): طولِ دورهٔ آزمایشی هم قابلِ تنظیمِ مالک شد
# (۱ تا ۳۰ روز؛ پیش‌فرض همان ۷ روزِ قبلی — بدونِ تغییرِ رفتار تا وقتی
# مالک دست نزند). نامِ پلنِ ذخیره‌شده داینامیک است و تشخیصِ «قبلاً
# آزمایشی گرفته» با پیشوندِ «آزمایشی» انجام می‌شود تا تغییرِ تعدادِ
# روزها باعثِ اعطای دوباره به همان کاربر نشود.
TRIAL_DAYS_SETTING = "trial_days"
TRIAL_DAYS_MIN = 1
TRIAL_DAYS_MAX = 30
TRIAL_DAYS_DEFAULT = 7

# v2.17.0: اشتراک دسته‌جمعی — یک پرداخت، چند صندلی با تخفیف برای گروه
# پلنِ دسته‌جمعی با همین پیشوند در جدول pricing ثبت می‌شود تا همه‌ی مسیرهای
# پرداخت (کیف پول/کارت/تتر/درگاه) مدت را درست بخوانند؛ از فهرست‌های
# کاربری با is_group_plan() فیلتر می‌شود.
GROUP_PLAN_PREFIX = "👥 گروهی"
GROUP_SEATS_CHOICES = (2, 3, 5)
GROUP_SUB_SETTING_KEY = "group_sub_enabled"               # "1" = روشن (پیش‌فرض)
GROUP_DISCOUNT_SETTING_KEY = "group_sub_discount_percent"  # پیش‌فرض ۱۵٪
GROUP_DISCOUNT_DEFAULT = 15

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
    فقط در نمونه‌ی اصلی و فقط برای ADMIN_ID یا هر کس که در OWNER_IDS باشد.
    PATCH (v2.0.10): OWNER_IDS env support.
    """
    if IS_DEDICATED_BOT:
        return False
    try:
        actor_id_int = int(actor_id)
        # OWNER_IDS در module load time ست می‌شه و شامل ADMIN_ID هم هست
        # (اگه ADMIN_ID تنظیم شده باشه). این چک idempotent و thread-safe است.
        return actor_id_int in OWNER_IDS or actor_id_int == int(ADMIN_ID)
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
    شده‌اند.

    v2.12.29 (DEEP-6 #6): این تابع داخل یک _conn_immediate صدا زده
    می‌شه (از init_db) که BEGIN IMMEDIATE داره. DDL‌های sqlite در حالت
    default isolation_level auto-commit می‌شن، ولی چون ما از _conn_immediate
    استفاده می‌کنیم، همه DDL‌ها و DML‌ها در یک تراکنش هستن. اگه خطا
    رخ بده، rollback می‌شن و دیتابیس در حالت نیمه‌مهاجرت‌شده نمی‌مونه.
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
        if "receipt_file_uid" not in cols:
            c.execute("ALTER TABLE payments ADD COLUMN receipt_file_uid TEXT")

    # ── مهاجرت delete_journal: افزودن ستون status (ردیف‌های قدیمی → DELETE_PENDING) ──
    if "delete_journal" in tables:
        cols = _table_columns(c, "delete_journal")
        if "status" not in cols:
            print("🔧 [saas_db] مهاجرت schema: افزودن ستون status به جدول delete_journal...")
            c.execute(
                "ALTER TABLE delete_journal ADD COLUMN status TEXT NOT NULL DEFAULT 'DELETE_PENDING'"
            )
            print("✅ [saas_db] مهاجرت delete_journal با موفقیت انجام شد — هیچ داده‌ای از دست نرفت.")

    # v2.9.3: مهاجرت orders — افزودن ستون‌های تخفیف (discount_code, discount_percent,
    # original_amount_toman) که در v2.9.0 اضافه شدن ولی برای DB‌های قدیمی وجود ندارن.
    # بدون این migration، create_order شکست می‌خورد و کاربر «خطا در پردازش این دکمه» می‌بینه.
    if "orders" in tables:
        cols = _table_columns(c, "orders")
        added = False
        if "discount_code" not in cols:
            print("🔧 [saas_db] مهاجرت schema: افزودن ستون discount_code به orders...")
            c.execute("ALTER TABLE orders ADD COLUMN discount_code TEXT")
            added = True
        if "discount_percent" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN discount_percent INTEGER DEFAULT 0")
            added = True
        if "original_amount_toman" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN original_amount_toman INTEGER")
            added = True
        if "amount_salt" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN amount_salt TEXT DEFAULT '0.00'")
            added = True
        if "receipt_file_uid" not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN receipt_file_uid TEXT")
            added = True
        if added:
            print("✅ [saas_db] مهاجرت orders با موفقیت انجام شد — ستون‌های تخفیف اضافه شدند.")

    # v2.10.5: مهاجرت wallet_transactions CHECK
    if "wallet_transactions" in tables:
        try:
            c.execute("INSERT INTO wallet_transactions (user_id, amount, balance_after, type, created_at) VALUES (0, 0, 0, 'reseller_credit', 'test')")
            c.execute("DELETE FROM wallet_transactions WHERE user_id = 0 AND amount = 0")
        except Exception:
            print("🔧 [saas_db] مهاجرت wallet_transactions: افزودن reseller_credit...")
            c.execute("ALTER TABLE wallet_transactions RENAME TO wallet_transactions_old")
            c.execute("CREATE TABLE wallet_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount INTEGER NOT NULL, balance_after INTEGER NOT NULL, type TEXT NOT NULL CHECK(type IN ('credit','debit','payment','admin_adjust','refund','reseller_credit')), ref TEXT, reason TEXT, created_by INTEGER, created_at TEXT NOT NULL)")
            c.execute("INSERT INTO wallet_transactions SELECT * FROM wallet_transactions_old")
            c.execute("DROP TABLE wallet_transactions_old")
            print("✅ [saas_db] مهاجرت wallet_transactions انجام شد.")


def init_db() -> None:
    if os.path.exists(DB_PATH):
        try:
            _bak_date = datetime.now(timezone.utc).strftime("%Y%m%d")
            _bak_path = f"{DB_PATH}.bak.{_bak_date}"
            if not os.path.exists(_bak_path):
                shutil.copy2(DB_PATH, _bak_path)
                _chmod_private(_bak_path, 0o600)
        except Exception as _be:
            print(f"⚠️ [saas_db] pre-migration backup failed: {_be}")
    with _conn_immediate() as c:
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
            -- v2.19.4 (AUDIT-36 C1): این ستون قبلاً فقط در شاخه‌ی مهاجرت
            -- ساخته می‌شد نه در CREATE TABLE — یعنی هر نصبِ تازه (یا رباتِ
            -- اختصاصی با DB تازه) در «ارسال رسید کارتی» با OperationalError
            -- می‌شکست (create_payment). حالا از اول ساخته می‌شود.
            receipt_file_uid TEXT,
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
            paid_at TEXT,
            -- v2.9.0: تخفیف
            discount_code TEXT,
            discount_percent INTEGER DEFAULT 0,
            original_amount_toman INTEGER,
            -- v2.19.4 (AUDIT-36 C1): این دو ستون مثل receipt_file_uidِ
            -- payments فقط در مهاجرت ساخته می‌شدند — DB تازه یعنی
            -- create_order با «no such column: amount_salt» می‌ترکید و کلِ
            -- جریان خرید روی نصبِ تازه مرده بود. حالا در CREATE TABLE هم هست.
            amount_salt TEXT DEFAULT '0.00',
            receipt_file_uid TEXT
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
            unit TEXT,
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
        # v2.0: درخواست‌های نمایندگی (جدول جدا از admins تا تاریخچه‌ی
        # درخواست‌ها، تأیید/رد و توضیحات نگه داشته شود).
        c.execute("""
            CREATE TABLE IF NOT EXISTS reseller_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_reseller_app_user
            ON reseller_applications(user_id)
        """)

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

        # v1.8.0: migration — اضافه کردن ستون unit به tickets اگه نبود
        try:
            c.execute("ALTER TABLE tickets ADD COLUMN unit TEXT")
        except Exception:
            pass  # ستون از قبل وجود داره

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

    # v2.12.31 (DEBUG-1 SCHEMA): ensure_wallet_schema() تا حالا فقط در
    # main() runtime صدا زده می‌شد، نه در module-load. این یعنی اگر
    # web_panel.py تنها main.py را import کند (بدون اجرای asyncio main())،
    # جداول wallet_transactions, scheduled_messages, auto_replies,
    # affiliate_commissions و ستون wallet_balance روی users وجود نداشتند
    # و endpoint‌های web_panel با 500 error شکست می‌کردند. حالا اینجا هم
    # صدا می‌زنیم تا DB بعد از init_db() همیشه schema کامل داشته باشه.
    # v2.19.4 (AUDIT-36 M8): wallet/block هم مثل reporter (v2.19.0) سه
    # تلاش با فاصله می‌گیرند — قفلِ لحظه‌ایِ DB موقعِ بوتِ هم‌زمانِ bot و
    # web_panel دیگر جریان را «خطا در پردازشِ» همیشگی نمی‌کند.
    for _attempt_w in range(3):
        try:
            ensure_wallet_schema()
            break
        except Exception as _e:
            if _attempt_w == 2:
                print(f"⚠️ [init_db] ensure_wallet_schema failed after retries: "
                      f"{type(_e).__name__}: {_e}")
            else:
                time.sleep(1.0)
    # v2.17.0: ستون‌های بلاک کاربر
    for _attempt_b in range(3):
        try:
            ensure_block_schema()
            break
        except Exception as _e:
            if _attempt_b == 2:
                print(f"⚠️ [init_db] ensure_block_schema failed after retries: "
                      f"{type(_e).__name__}: {_e}")
            else:
                time.sleep(1.0)
    # v2.19.4 (AUDIT-36 C2 — CRITICAL): ستون‌های رفرال (referred_by /
    # referral_rewards) تا حالا فقط از main() ساخته می‌شدند (فراخوانیِ
    # fire-once بدون retry)؛ شواهدِ production: بکاپ‌های واقعیِ سرور این
    # ستون را ندارند و «👤 حساب کاربری» — هابِ کیف پول/سفارش‌ها/دعوت —
    # با OperationalError می‌شکست. حالا مثل reporter: سه تلاش در init_db
    # + لایه‌ی دومِ self-heal در لحظه‌ی استفاده (_ensure_referral_ready).
    for _attempt_rf in range(3):
        try:
            ensure_referral_schema()
            break
        except Exception as _e:
            if _attempt_rf == 2:
                print(f"⚠️ [init_db] ensure_referral_schema failed after retries: "
                      f"{type(_e).__name__}: {_e}")
            else:
                time.sleep(1.0)
    # v2.18.0: جدول لاگ ریپورتر (متادیتا فقط — بدون محتوا)
    # v2.19.0 (SELF-HEAL): سه تلاش با فاصله — قفلِ لحظه‌ایِ DB موقعِ بوت
    # (تراکنشِ هم‌زمانِ web_panel) باعث شده بود جدول ساخته نشود و دکمه‌های
    # ریپورتر روی سرورِ واقعی با «خطا در پردازش» بشکنند. لایه‌ی دومِ درمان،
    # _ensure_reporter_ready در لحظه‌ی استفاده است.
    for _attempt_r in range(3):
        try:
            ensure_reporter_schema()
            break
        except Exception as _e:
            if _attempt_r == 2:
                print(f"⚠️ [init_db] ensure_reporter_schema failed after retries: "
                      f"{type(_e).__name__}: {_e}")
            else:
                time.sleep(1.0)


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
    # PATCH (P1-1 BUG-29): read-then-write قبلاً خارج از قفل نوشتن انجام می‌شد
    # و دو فراخوانیِ هم‌زمان می‌توانستند یک شمارش را گم کنند. حالا کلِ
    # «خواندن + نوشتن» داخل یک تراکنش BEGIN IMMEDIATE است (ستون value از
    # نوع TEXT است، پس افزایش در Python انجام می‌شود نه در SQL).
    with _conn_immediate() as c:
        row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        cur = int(row["value"]) if row and row["value"] and str(row["value"]).isdigit() else 0
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(cur + 1)),
        )


def set_setting(key: str, value: str, actor_id: int = None) -> None:
    """
    v2.13.0 (DEBUG-2 BUG#2): اگر کلید حساس باشد (مرچنت درگاه، آدرس کیف پول،
    switch درگاه پرداخت، min_commit_hash)، تغییر با audit log ثبت می‌شود
    تا OWNER نتواند بدون رد، پرداخت‌ها را به مرچنت خودش هدایت کند.
    """
    with _conn() as c:
        old_row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        old_val = old_row["value"] if old_row else None
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    # v2.13.0: audit logging برای کلیدهای حساس — خارج از تراکنشِ settings
    # تا در صورت بروز استثنا در لاگ، تغییر settings rollback نشود.
    if _is_sensitive_setting_key(key):
        try:
            old_disp = (str(old_val)[:50] if old_val is not None else "None")
            new_disp = (str(value)[:50] if value is not None else "None")
            log_action(
                actor_id or 0,
                "setting_changed",
                f"key={key} old={old_disp} new={new_disp}",
            )
        except Exception:
            # لاگ نباید باعث شکست set_setting شود
            pass


def _is_sensitive_setting_key(key: str) -> bool:
    """v2.13.0 (DEBUG-2 BUG#2): کلیدهای حساس که تغییر آن‌ها باید audit شود."""
    if not key:
        return False
    sensitive_prefixes = (
        "zarinpal_merchant",
        "zibal_merchant",
        "pay_",
        "wallet_address",
        "min_commit_hash",
    )
    return key.startswith(sensitive_prefixes)


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
    # v2.12.10 (QA2-EXPERT/QA2-OWNER C7 / AUDIT-10-D HIGH#1): قبلاً فقط
    # user_id == owner_id چک می‌شد (یعنی فقط ADMIN_ID اصلی). اگه کسی در
    # OWNER_IDS env var اضافه شده بود، is_owner_bypass و notify_owner_global
    # او را به‌عنوان OWNER می‌شناختن ولی get_role نه → تو منوی ربات، فقط
    # USER می‌دید و به هیچ OWNER-only صفحات دسترسی نداشت. حالا OWNER_IDS
    # هم چک می‌شه (defensive: در زمان تعریفِ تابع OWNER_IDS هنوز موجود
    # نیست ولی در زمان فراخوانی هست — Python late-binding).
    try:
        _extra_owners = OWNER_IDS
    except NameError:
        _extra_owners = set()
    if user_id == owner_id or (_extra_owners and user_id in _extra_owners):
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
#  v2.17.0: بلاک کاربر (SaaS) — قطع دسترسی کامل به ربات
#  (جدا از banned_users دیتابیسِ خودِ سلف‌بات که مال چت‌های اکانت است)
# ══════════════════════════════════════════════════════════════════════

def ensure_block_schema() -> None:
    """ستون‌های بلاک روی users — همان الگوی ensure_wallet_schema:
    ALTER TABLE فقط وقتی ستون نباشد، تا دیتابیس‌های قدیمی بدون dump/restore
    هم مهاجرت شوند."""
    with _conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        for col, ddl in (
            ("is_blocked", "ALTER TABLE users ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0"),
            ("blocked_at", "ALTER TABLE users ADD COLUMN blocked_at TEXT"),
            ("blocked_by", "ALTER TABLE users ADD COLUMN blocked_by INTEGER"),
            ("block_reason", "ALTER TABLE users ADD COLUMN block_reason TEXT"),
        ):
            if col not in cols:
                c.execute(ddl)
                print(f"✅ [block] ستون {col} به users اضافه شد")


def is_user_blocked(user_id: int) -> bool:
    """آیا این کاربر توسط مدیریت بلاک شده؟ یک SELECT روی کلید اصلی —
    ارزان‌تر از کارهایی که هر پیام از قبل انجام می‌دهد (مثل گیت کانال)."""
    with _conn() as c:
        row = c.execute(
            "SELECT is_blocked FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return bool(row and row["is_blocked"])


def block_saas_user(target_id: int, blocked_by: int, reason: str = "") -> dict:
    """بلاک کاربر — ماتریس دسترسی در Backend (مستقل از UI):
      • فقط OWNER/ADMIN می‌توانند بلاک کنند
      • OWNER هرگز بلاک نمی‌شود
      • ADMIN فقط توسط OWNER بلاک می‌شود
    داده‌ها/کیف پول/تاریخچه حفظ می‌شوند (بلاک قابل برگشت است)؛ توقفِ
    سلف‌بات‌ها جداگانه در لایه‌ی ربات انجام می‌شود. خروجی:
    {"ok": True} یا {"ok": False, "error": "..."}."""
    actor_role = get_role(blocked_by, OWNER_ID)
    if actor_role not in (ROLE_OWNER, ROLE_ADMIN):
        return {"ok": False, "error": "permission_denied"}
    target_role = get_role(target_id, ROLE_USER)
    if target_role == ROLE_OWNER:
        return {"ok": False, "error": "cannot_block_owner"}
    if target_role == ROLE_ADMIN and actor_role != ROLE_OWNER:
        return {"ok": False, "error": "admin_needs_owner"}
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET is_blocked = 1, blocked_at = ?, blocked_by = ?, block_reason = ? "
            "WHERE user_id = ?",
            (_now(), blocked_by, (reason or "").strip()[:200] or None, target_id),
        )
        if cur.rowcount == 0:
            return {"ok": False, "error": "user_not_found"}
    log_action(blocked_by, "user_blocked",
               f"target={target_id}" + (f" reason={reason[:80]}" if reason else ""))
    return {"ok": True}


def unblock_saas_user(target_id: int, unblocked_by: int) -> dict:
    """رفع بلاک — همان ماتریس دسترسیِ بلاک. ادامه‌ی سلف‌ها (در صورت فعال
    بودن اشتراک) در لایه‌ی ربات انجام می‌شود."""
    actor_role = get_role(unblocked_by, OWNER_ID)
    if actor_role not in (ROLE_OWNER, ROLE_ADMIN):
        return {"ok": False, "error": "permission_denied"}
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET is_blocked = 0, blocked_at = NULL, blocked_by = NULL, "
            "block_reason = NULL WHERE user_id = ?",
            (target_id,),
        )
        if cur.rowcount == 0:
            return {"ok": False, "error": "user_not_found"}
    log_action(unblocked_by, "user_unblocked", f"target={target_id}")
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════
#  v2.17.0: اشتراک آزمایشی ۷ روزه — فقط کاربرانِ تازه‌وارد
# ══════════════════════════════════════════════════════════════════════

def trial_enabled() -> bool:
    """گزینه‌ی مالک: اعطای اشتراک آزمایشی به کاربران جدید (پیش‌فرض روشن)."""
    return str(get_setting(TRIAL_SETTING_KEY, "1")).strip() == "1"


def trial_days() -> int:
    """
    v2.22.0 (OWNER-REQUEST): تعدادِ روزهایِ اشتراکِ آزمایشی — قابلِ تنظیمِ
    مالک از «🎁 اشتراک آزمایشی» (۱ تا ۳۰). مقدارِ خارج از بازه به نزدیک‌ترین
    لبه می‌چسبد و مقدارِ خراب به پیش‌فرضِ ۷ روزِ همیشگی برمی‌گردد؛ هیچ
    ورودی‌ای نمی‌تواند اعطای آزمایشی را کاملاً غیرممکن (۰ روز) یا غیرواقعی
    کند.
    """
    try:
        v = int(str(get_setting(TRIAL_DAYS_SETTING, str(TRIAL_DAYS_DEFAULT))).strip())
    except (TypeError, ValueError):
        return TRIAL_DAYS_DEFAULT
    return max(TRIAL_DAYS_MIN, min(TRIAL_DAYS_MAX, v))


def trial_plan_name(days: int = None) -> str:
    """نامِ پلنِ آزمایشی برای ذخیره در subscriptions — «آزمایشی N روزه».

    برای days=7 دقیقاً همان رشتهٔ تاریخیِ «آزمایشی ۷ روزه» را می‌سازد
    (fa_digits) تا ردیف‌های قدیمی و کوئری‌های موجود هم‌خوان بمانند.
    """
    d = trial_days() if days is None else int(days)
    return f"آزمایشی {fa_digits(d)} روزه"


def grant_trial_if_eligible(user_id: int) -> bool:
    """اعطای اشتراکِ آزمایشیِ چندروزه — صرفاً یک‌بار در طول عمرِ هر کاربر.
    شرط‌ها: آزمایشی روشن باشد؛ کاربر نقش مدیریتی نداشته باشد؛ اشتراک
    فعالی نداشته باشد؛ قبلاً آزمایشی نگرفته باشد (حتی منقضی‌شده — با
    پیشوندِ «آزمایشی»، مستقل از تعدادِ روزهایِ دوره‌های مختلف). تعدادِ
    روزها از تنظیمِ مالک (trial_days) خوانده می‌شود. True یعنی اعطا شد.
    فراخوانی‌اش فقط از مسیرِ ثبتِ کاربرِ تازه (/start با is_new) است —
    کاربرانِ قدیمی که از قبل users دارند هرگز شامل نمی‌شوند."""
    if not trial_enabled():
        return False
    if get_role(user_id, ROLE_USER) in (ROLE_OWNER, ROLE_ADMIN):
        return False
    with _conn() as c:
        active = c.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND status = 'active' LIMIT 1",
            (user_id,),
        ).fetchone()
        if active:
            return False
        prior_trial = c.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND plan LIKE 'آزمایشی%' "
            "LIMIT 1",
            (user_id,),
        ).fetchone()
        if prior_trial:
            return False
    days = trial_days()
    create_subscription(user_id, trial_plan_name(days), days)
    log_action(user_id, "trial_granted", f"days={days}")
    return True


# ══════════════════════════════════════════════════════════════════════
#  v2.22.0 (OWNER-REQUEST): عضویت اجباریِ چندکاناله/چندگروهی
#  (لیستِ JSON در settings؛ سازگار با تک‌کانالِ قدیمی required_channel)
# ══════════════════════════════════════════════════════════════════════

REQUIRED_CHATS_SETTING = "required_chats"  # JSON: [{"u","t","l"}, ...]
REQUIRED_CHATS_MAX = 10


def get_required_chats() -> list:
    """لیستِ کانال‌ها/گروه‌هایِ عضویتِ اجباری.

    ساختارِ هر آیتم: {"u": یوزرنیمِ نرمال‌شده یا آیدیِ عددیِ چت,
                      "t": عنوانِ ذخیره‌شده، "l": لینکِ دعوت (چتِ خصوصی)}.

    مهاجرتِ نرم: اگر لیستِ جدید خالی باشد ولی تنظیمِ تک‌کانالیِ قدیمی
    (required_channel) تنظیم شده باشد، همان به‌عنوانِ تک‌عضویِ لیست
    برگردد — استقرارهایِ قدیمی بدونِ دست‌زدنِ مالک همین‌طور کار می‌کنند.
    خروجی همیشه dedupe شده و سقفش REQUIRED_CHATS_MAX است.

    v2.22.1 (AUDIT-39/a#4): آیتمِ با u غیرِاسکالر (dict/list — فقط از طریقِ
    دست‌کاریِ مستقیمِ DB ممکن است) نادیده گرفته می‌شود تا گیت برایِ همه
    fail-closed نشود.
    """
    raw = (get_setting(REQUIRED_CHATS_SETTING) or "").strip()
    chats = []
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for it in data:
                    if isinstance(it, dict):
                        u = it.get("u")
                        if not isinstance(u, (str, int)) or isinstance(u, bool):
                            continue
                        u = str(u).strip()
                        if u:
                            chats.append({"u": u,
                                          "t": str(it.get("t") or "").strip(),
                                          "l": str(it.get("l") or "").strip()})
        except Exception:
            chats = []
    if not chats:
        legacy = (get_setting("required_channel") or "").strip()
        if legacy:
            chats = [{"u": legacy,
                      "t": (get_setting("required_channel_title") or "").strip(),
                      "l": ""}]
    seen, out = set(), []
    for ch in chats:
        key = ch["u"].lower().lstrip("@")
        if key not in seen:
            seen.add(key)
            out.append(ch)
    return out[:REQUIRED_CHATS_MAX]


def set_required_chats(chats: list) -> None:
    """ذخیرهٔ لیستِ کانال‌ها/گروه‌هایِ اجباری (نوشتنِ کاملِ لیست).

    dedupe بر اساسِ u انجام می‌شود؛ بیش از REQUIRED_CHATS_MAX آیتم
    ValueError می‌دهد (UI قبل از رسیدن به اینجا سقف را چک می‌کند).
    کلیدهایِ legacy هم برایِ هم‌خوانیِ مسیرهایِ قدیمی همگام می‌شوند:
    required_channel = یوزرنیمِ اولینِ آیتمِ غیرعددی (یا خالی) و
    required_channel_title = عنوانِ همان.
    """
    clean, seen = [], set()
    for it in chats or []:
        if not isinstance(it, dict):
            continue
        u = it.get("u")
        if not isinstance(u, (str, int)) or isinstance(u, bool):
            continue
        u = str(u).strip()
        if not u or u.lower().lstrip("@") in seen:
            continue
        seen.add(u.lower().lstrip("@"))
        clean.append({"u": u,
                      "t": str(it.get("t") or "").strip(),
                      "l": str(it.get("l") or "").strip()})
    if len(clean) > REQUIRED_CHATS_MAX:
        raise ValueError(f"max {REQUIRED_CHATS_MAX} chats")
    set_setting(REQUIRED_CHATS_SETTING,
                json.dumps(clean, ensure_ascii=False))
    legacy_u, legacy_t = "", ""
    for ch in clean:
        if not ch["u"].lstrip("-").isdigit():
            legacy_u, legacy_t = ch["u"], ch["t"]
            break
    set_setting("required_channel", legacy_u)
    set_setting("required_channel_title", legacy_t)


# ══════════════════════════════════════════════════════════════════════
#  v2.22.0 (OWNER-REQUEST): بکاپِ ساعتیِ سشن‌های سلف به گروهِ شخصی
# ══════════════════════════════════════════════════════════════════════

SELF_BACKUP_GROUP_SETTING = "self_backup_group"    # آیدیِ عددیِ گروه
SELF_BACKUP_ENABLED_SETTING = "self_backup_enabled"  # "1" = روشن (پیش‌فرض)


def self_backup_group():
    """آیدیِ عددیِ گروهِ مقصدِ بکاپِ ساعتی — None یعنی تنظیم نشده."""
    raw = str(get_setting(SELF_BACKUP_GROUP_SETTING, "") or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    return v or None


def self_backup_enabled() -> bool:
    """کلیدِ روشن/خاموشِ بکاپِ ساعتی (فقط وقتی معنا دارد که گروه تنظیم شده
    باشد — حلقهٔ ارسال هر دو را چک می‌کند)."""
    return str(get_setting(SELF_BACKUP_ENABLED_SETTING, "1")).strip() == "1"


# ══════════════════════════════════════════════════════════════════════
#  v2.18.0: ریپورتر — گزارشِ کانال/گروه/اکانتِ جعلی یا کلاهبردار
#  (هر گزارش فقط با اکانتِ خودِ کاربر، یک گزارش در ۲۴ ساعت برای هر هدف،
#   سقفِ روزانه‌ی قابل‌تنظیم توسط مالک — «اصل طلایی» حفظ شده است)
# ══════════════════════════════════════════════════════════════════════

REPORTER_ENABLED_SETTING = "reporter_enabled"       # "1" = روشن (پیش‌فرض)
REPORTER_CAP_SETTING = "reporter_daily_cap"         # سقف گزارش هر کاربر در روز
REPORTER_CAP_DEFAULT = 10
REPORTER_CAP_MIN = 1
# v2.19.2 (OWNER-REQUEST): سقف تا ۱۰۰ بالا رفت — مالک می‌خواهد محدودیتِ
# ریپورتر را خودش تنظیم کند؛ این سقفِ «هر کاربر در روز، با اکانتِ خودش»
# است و ریسکش متوجهِ همان اکانتِ کاربر است.
REPORTER_CAP_MAX = 100
REPORTER_DUP_HOURS = 24                              # فاصله‌ی حداقلی گزارشِ مجددِ همان هدف
# v2.19.2 (OWNER-REQUEST): پنجره‌ی «گزارشِ مجددِ همان هدف» هم قابلِ تنظیمِ
# مالک شد (پیش‌فرض همان ۲۴ ساعتِ قبلی — بدون تغییرِ رفتار تا وقتی مالک
# دست نزند).
REPORTER_DUP_SETTING = "reporter_dup_hours"
REPORTER_DUP_MIN = 1
REPORTER_DUP_MAX = 72
# v2.21.0 (OWNER-REQUEST «ریپورت بهتر»): حالتِ چنداکانته — بستهٔ گزارش
# به‌جایِ فقطِ اکانتِ خودِ کاربر، به‌صورتِ «همزمان» از همهٔ اکانت‌های در
# حالِ اجرای سیستم شلیک می‌شود (سهمیهٔ همان کاربر بینشان تقسیم می‌شود).
# مالک می‌تواند از پنلِ ریپورتر خاموش/روشنش کند. سیاستِ v2.18.0–v2.20.0
# («فقط اکانتِ خودِ کاربر») با خواستهٔ صریحِ مالک عوض شد.
REPORTER_MULTI_SETTING = "reporter_multi_account"
REPORTER_MULTI_MAX_ACCOUNTS = 15   # سقفِ امنِ اکانت‌های شرکت‌کننده در یک بسته


def reporter_multi_account() -> bool:
    """v2.21.0: سوییچِ حالتِ چنداکانتهٔ مالک (پیش‌فرض روشن — خواستهٔ
    صریحِ مالک در ۲۰۲۶-10-22). خاموش یعنی رفتارِ v2.20.0: فقط اکانتِ
    خودِ کاربرِ گزارش‌دهنده."""
    return str(get_setting(REPORTER_MULTI_SETTING, "1")).strip() == "1"


def running_report_clients(exclude_ids=None, limit=None):
    """همهٔ کلاینت‌های READY سیستم — برای بستهٔ چنداکانتهٔ ریپورتر.

    خروجی: [(tag, client, my_id)] — بدونِ کلاینتِ تکرار، با سقفِ امنِ
    REPORTER_MULTI_MAX_ACCOUNTS. exclude_ids: آیدی‌های تلگرامی که نباید
    شلیک کنند (مثلاً خودِ هدف، اگر اتفاقی در سیستم لاگین باشد).
    نکته: ACCOUNTS/is_running پایین‌تر در همین ماژول تعریف شده‌اند —
    فراخوانیِ زمان-اجرا است و ترتیبِ تعریفِ ماژول مشکلی نمی‌سازد.
    """
    out, seen = [], set()
    excl = {i for i in (exclude_ids or []) if i is not None}
    cap = int(limit or REPORTER_MULTI_MAX_ACCOUNTS)
    for tag, entry in list(ACCOUNTS.items()):
        try:
            if not is_running(tag):
                continue
            client = getattr(getattr(entry, "bot", None), "client", None)
            if client is None or id(client) in seen:
                continue
            my_id = getattr(getattr(entry, "bot", None), "my_id", None)
            if my_id is not None and my_id in excl:
                continue
            seen.add(id(client))
            out.append((tag, client, my_id))
            if len(out) >= cap:
                break
        except Exception:
            continue
    return out


def ensure_reporter_schema() -> None:
    """جدول لاگ ریپورتر — الگوی ensure_block_schema (ایده‌مپوتنت، بدون dump/restore).

    ⚠️ حریم خصوصی: فقط متادیتا ذخیره می‌شود (هدف، دسته، وضعیت، زمان).
    متن پیام‌ها/محتوای هدف هرگز ذخیره نمی‌شود — پیام‌های اخیر صرفاً به‌عنوان
    شناسه‌های عددی به API گزارش تلگرام پاس داده می‌شوند و در DB نمی‌مانند.
    """
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS reporter_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                target TEXT NOT NULL,
                target_id INTEGER,
                target_type TEXT,
                category TEXT NOT NULL,
                with_messages INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ok',
                created_at TEXT NOT NULL
            )"""
        )
        # v2.20.0 (SPAM-MODE): هر ردیف دیگر «یک گزارش» نیست — تعداد شلیکِ
        # همان بسته است (burst). ردیف‌های قدیمی با DEFAULT 1 معتبر می‌مانند.
        cols = {r[1] for r in c.execute(
            "PRAGMA table_info(reporter_logs)").fetchall()}
        if "report_count" not in cols:
            c.execute("ALTER TABLE reporter_logs "
                      "ADD COLUMN report_count INTEGER NOT NULL DEFAULT 1")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_reporter_user_time "
            "ON reporter_logs (user_id, created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_reporter_target "
            "ON reporter_logs (user_id, target_id, created_at)"
        )


def _ensure_reporter_ready() -> bool:
    """v2.19.0 (SELF-HEAL): جدولِ reporter_logs واقعاً قابلِ پرس‌وجوست؟

    ریشه‌یابیِ باگِ production (۲۰۲۶-۱۰-۲۱): مالک روی سرورِ واقعی با فشارِ
    دکمه‌ی ریپورتر «❌ خطا در پردازش این دکمه» می‌گرفت. علت: init_db در
    سطحِ ماژول اجرا می‌شود و اگر ensure_reporter_schema در همان لحظه‌ی بوت
    به قفلِ لحظه‌ایِ DB (مثلاً تراکنشِ web_panel) بخورد، هشدار فقط در کنسول
    چاپ می‌شود، ربات بوت می‌شود و از آن پس هر خواندنِ سهمیه
    OperationalError("no such table: reporter_logs") می‌دهد — که در
    dispatcher به پیامِ عمومیِ خطا ترجمه می‌شود.

    درمان: قبل از هر خواندن/نوشتنِ جدول، یک SELECT ارزان (LIMIT 1)؛ اگر
    جدول نبود همین‌جا ساخته می‌شود و دوباره چک می‌شود. اگر DB واقعاً
    ناتوان بود (دیسک پر/فایل فقط‌خواندنی)، False برمی‌گردد تا caller
    به‌جای exception با مقدارِ امن (0/False/[]) ادامه دهد — لاگِ ریپورتر
    متادیتای غیرحیاتی است و نباید تعاملِ کاربر را بشکند.
    """
    try:
        with _conn() as c:
            c.execute("SELECT 1 FROM reporter_logs LIMIT 1")
        return True
    except sqlite3.OperationalError:
        pass  # جدول نیست → ساخت (پایین)
    except Exception as _e:
        print(f"⚠️ [core] reporter readiness check failed: {type(_e).__name__}: {_e}")
        return False
    try:
        ensure_reporter_schema()
    except Exception as _e:
        print(f"⚠️ [core] reporter self-heal failed: {type(_e).__name__}: {_e}")
        return False
    try:
        with _conn() as c:
            c.execute("SELECT 1 FROM reporter_logs LIMIT 1")
        return True
    except Exception:
        return False


def reporter_enabled() -> bool:
    """سوییچِ رانتایمِ مالک (پیش‌فرض روشن). جدا از REPORTER_ENABLEDِ
    کامپایل-تایم در cianet/bots/reporter.py که کیل‌سوییچِ اصلی است."""
    return str(get_setting(REPORTER_ENABLED_SETTING, "1")).strip() == "1"


def reporter_daily_cap() -> int:
    """سقفِ روزانه‌ی هر کاربر — همیشه بین REPORTER_CAP_MIN و MAX clamp می‌شود."""
    try:
        val = int(get_setting(REPORTER_CAP_SETTING, str(REPORTER_CAP_DEFAULT)))
    except (TypeError, ValueError):
        val = REPORTER_CAP_DEFAULT
    return max(REPORTER_CAP_MIN, min(REPORTER_CAP_MAX, val))


def reporter_today_count(user_id: int) -> int:
    """مجموعِ گزارش‌های شلیک‌شدهٔ همین کاربر در امروزِ UTC — روزانه بودن
    سهمیه. v2.20.0 (SPAM-MODE): با آمدنِ burst، COUNT ردیف‌ها دیگر عددِ
    واقعی نیست؛ SUM(report_count) ملاک است (ردیف‌های قدیمی = ۱).
    گزارش‌های ناموفق هم شمرده می‌شوند تا خطای سرور تبدیل به حلقه‌ی
    تلاشِ بی‌سقف نشود."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not _ensure_reporter_ready():
        return 0  # جدول قابلِ ساخت/خواندن نیست — سهمیه را محدود نشان نده
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(report_count), 0) AS n FROM reporter_logs "
            "WHERE user_id = ? AND created_at >= ?",
            (user_id, today),
        ).fetchone()
    return int(row["n"]) if row else 0


def reporter_quota_left(user_id: int) -> int:
    """سهمیه‌ی باقی‌مانده‌ی امروز همین کاربر (هرگز منفی نمی‌شود)."""
    return max(0, reporter_daily_cap() - reporter_today_count(user_id))


def reporter_dup_hours() -> int:
    """v2.19.2: پنجره‌ی گزارشِ مجددِ همان هدف (ساعت) — قابلِ تنظیمِ مالک.
    پیش‌فرض ۲۴ (رفتارِ v2.18.0) و همیشه در بازه‌ی مجاز clamp می‌شود."""
    try:
        val = int(get_setting(REPORTER_DUP_SETTING, str(REPORTER_DUP_HOURS)))
    except (TypeError, ValueError):
        val = REPORTER_DUP_HOURS
    return max(REPORTER_DUP_MIN, min(REPORTER_DUP_MAX, val))


def reporter_recently_reported(user_id: int, target_id, hours: int = None,
                              target: str = None) -> bool:
    """آیا همین کاربر همین هدف را در INTERVAL ساعتِ اخیر گزارش داده؟
    target_id ممکن است None باشد (هدفِ حل‌نشده) — در آن حالت مقایسه با
    رشته‌ی هدف انجام می‌شود تا دورزدنِ سهمیه با یوزرنیم/آیدیِ متناوب سخت بماند.
    v2.19.2: hours=None یعنی مقدارِ تنظیم‌شده‌ی مالک (reporter_dup_hours).
    v2.19.4 (AUDIT-36 L8): fallback رشته‌ای که docstring وعده می‌داد بالاخره
    پیاده شد — وقتی target_id هست همان مقایسه‌ی عددی؛ وقتی None است و
    target (رشته) داده شده، مقایسه روی ستونِ target انجام می‌شود."""
    if hours is None:
        hours = reporter_dup_hours()
    if not _ensure_reporter_ready():
        return False  # جدول نیست → «قبلاً گزارش داده» فرض نکن (fail-open امن)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(_DATETIME_FMT)
    if target_id is not None:
        with _conn() as c:
            row = c.execute(
                "SELECT 1 FROM reporter_logs "
                "WHERE user_id = ? AND target_id = ? AND created_at >= ? LIMIT 1",
                (user_id, int(target_id), cutoff),
            ).fetchone()
        return row is not None
    if not target:
        return False
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM reporter_logs "
            "WHERE user_id = ? AND target_id IS NULL AND target = ? "
            "AND created_at >= ? LIMIT 1",
            (user_id, str(target)[:120], cutoff),
        ).fetchone()
    return row is not None


def add_reporter_log(user_id: int, target: str, target_id, target_type: str,
                     category: str, with_messages: bool = False,
                     status: str = "ok", report_count: int = 1) -> None:
    """ثبتِ یک بستهٔ گزارش در تاریخچهٔ scoped کاربر (متادیتا فقط).

    v2.20.0 (SPAM-MODE): report_count = تعداد شلیکِ همین بسته (پیش‌فرض ۱ =
    رفتارِ قدیمی). سهمیهٔ روزانه با SUM همین ستون مصرف می‌شود؛ target_id
    را فقط برای بستهٔ «تمام‌شده» پر کنید (بستهٔ ناتمام با NULL ثبت می‌شود
    تا پنجرهٔ dup هدف را قفل نکند و کاربر بتواند بقیهٔ سهمیه را بعداً
    روی همان هدف شلیک کند)."""
    if not _ensure_reporter_ready():
        # گزارشِ واقعی ممکن است به تلگرام رسیده باشد — شکستِ لاگ نباید
        # رسیدِ کاربر را خراب کند؛ فقط در کنسول هشدار می‌دهیم.
        print("⚠️ [core] add_reporter_log skipped: reporter table unavailable")
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO reporter_logs "
            "(user_id, target, target_id, target_type, category, with_messages, status, report_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, str(target)[:120],
             int(target_id) if target_id is not None else None,
             str(target_type or "")[:20], str(category)[:40],
             1 if with_messages else 0, str(status)[:20],
             max(1, int(report_count or 1)), _now()),
        )


def list_reporter_logs(user_id: int, limit: int = 10) -> list:
    """آخرین گزارش‌های همین کاربر — جدیدترین اول (الگوی scoped مالکیت)."""
    if not _ensure_reporter_ready():
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT target, target_id, target_type, category, with_messages, status, report_count, created_at "
            "FROM reporter_logs WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, max(1, min(50, limit))),
        ).fetchall()
    return [dict(r) for r in rows]


def reporter_stats() -> dict:
    """آمار تجمعی برای پنل مالک — بدون محتوای شخصی کاربران."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not _ensure_reporter_ready():
        # v2.19.0 SELF-HEAL: پنل مالک هم نباید روی جدولِ ناتواب بشکند
        return {"total": 0, "users": 0, "today": 0, "by_category": {}, "ok": 0}
    with _conn() as c:
        # v2.20.0 (SPAM-MODE): همهٔ شمارنده‌ها SUM(report_count) — با آمدنِ
        # بسته‌های چندتایی، COUNT ردیف‌ها «بسته» می‌شمرد نه «گزارش».
        total = c.execute("SELECT COALESCE(SUM(report_count), 0) AS n "
                          "FROM reporter_logs").fetchone()["n"]
        users = c.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM reporter_logs").fetchone()["n"]
        today_n = c.execute(
            "SELECT COALESCE(SUM(report_count), 0) AS n FROM reporter_logs "
            "WHERE created_at >= ?",
            (today,),
        ).fetchone()["n"]
        by_cat = {
            r["category"]: r["n"]
            for r in c.execute(
                "SELECT category, COALESCE(SUM(report_count), 0) AS n "
                "FROM reporter_logs GROUP BY category"
            ).fetchall()
        }
        ok_n = c.execute(
            "SELECT COALESCE(SUM(report_count), 0) AS n FROM reporter_logs "
            "WHERE status != 'error'"
        ).fetchone()["n"]
    return {"total": int(total), "users": int(users), "today": int(today_n),
            "by_category": by_cat, "ok": int(ok_n)}


# ══════════════════════════════════════════════════════════════════════
#  v2.17.0: اشتراک دسته‌جمعی — یک پرداخت، چند صندلی با تخفیف
# ══════════════════════════════════════════════════════════════════════

def is_group_plan(plan_name: str) -> bool:
    """آیا این نام پلن، پلنِ دسته‌جمعیِ ثبت‌شده در pricing است؟"""
    return bool(plan_name) and str(plan_name).startswith(GROUP_PLAN_PREFIX)


def group_sub_enabled() -> bool:
    """گزینه‌ی فعال‌بودن خرید دسته‌جمعی (پیش‌فرض روشن)."""
    return str(get_setting(GROUP_SUB_SETTING_KEY, "1")).strip() == "1"


def group_sub_discount_percent() -> int:
    """درصد تخفیف دسته‌جمعی — همیشه بین ۰ و ۵۰ clamp می‌شود."""
    try:
        val = int(get_setting(GROUP_DISCOUNT_SETTING_KEY, str(GROUP_DISCOUNT_DEFAULT)))
    except (TypeError, ValueError):
        val = GROUP_DISCOUNT_DEFAULT
    return max(0, min(50, val))


def group_plan_label(base_plan: str, seats: int) -> str:
    """نامِ یکتای پلن دسته‌جمعی — تعداد نفرات و پلن پایه داخل خودش است."""
    return f"{GROUP_PLAN_PREFIX} {seats} نفره · {base_plan}"


def register_group_plan(base_plan_row: dict, seats: int) -> dict:
    """پلنِ دسته‌جمعی را با قیمتِ تخفیف‌دار در pricing ثبت/به‌روز می‌کند و
    ردیفِ نهایی را برمی‌گرداند. ثبت در pricing لازم است تا همه‌ی مسیرهای
    پرداخت، مدتِ درست را از همان‌جا بخوانند (همان مکانیزمِ پلن‌های عادی).
    قیمت به‌صورت مجموعِ تخفیف‌دار و رُند‌شده به هزار تومان محاسبه می‌شود."""
    base_price = int(base_plan_row["price_toman"])
    base_days = int(base_plan_row["duration_days"])
    discount = group_sub_discount_percent()
    total = int(round(base_price * seats * (100 - discount) / 100 / 1000.0)) * 1000
    total = max(1000, total)
    label = group_plan_label(base_plan_row["plan"], seats)
    set_pricing(label, total, base_days)
    return {"plan": label, "price_toman": total, "duration_days": base_days,
            "seats": seats, "base_plan": base_plan_row["plan"],
            "discount_percent": discount}


def _create_group_licenses_internal(buyer_id: int, count: int,
                                    duration_days: int, order_id: int) -> list:
    """ساخت لایسنس‌های اشتراک برای اعضای گروه — مسیر سیستمی. create_license()
    عادی، خریدارِ USER را رد می‌کند (ماتریس دسترسی‌اش فقط به مدیران اجازه
    می‌دهد)؛ اینجا همان INSERT با همان retry یکتایی انجام می‌شود و
    created_by = خریدار (برای ردیابی در لیست لایسنس‌های مالک)."""
    codes = []
    with _conn() as c:
        for _seat in range(max(0, count)):
            code = _generate_license_code()
            unique = False
            for _try in range(10):
                exists = c.execute(
                    "SELECT 1 FROM licenses WHERE code = ?", (code,)
                ).fetchone()
                if not exists:
                    unique = True
                    break
                code = _generate_license_code()
            if not unique:
                break
            c.execute(
                "INSERT INTO licenses (code, license_type, duration_days, max_uses, used_count, "
                "reseller_user_limit, created_by, created_at, is_active) "
                "VALUES (?, ?, ?, 1, 0, NULL, ?, ?, 1)",
                (code, LICENSE_TYPE_ACCOUNT, duration_days, buyer_id, _now()),
            )
            codes.append(code)
    if codes:
        log_action(buyer_id, "group_licenses_created",
                   f"order={order_id}, count={len(codes)}, days={duration_days}")
    return codes


def maybe_fulfill_group_order(order_id: int = None, payment_id: int = None) -> None:
    """پس از paid شدن فاکتورِ دسته‌جمعی: صندلی‌های باقی‌مانده را به‌صورت
    لایسنس می‌سازد و کدها را برای خریدار می‌فرستد. خریدار خودش اشتراکش
    را از همان مسیر عادیِ فاکتور می‌گیرد؛ کدها مالِ بقیه‌ی اعضاست.

    • idempotent — نشانگرِ settings با تراکنشِ اتمیک قفل می‌شود؛
      دوباره صدا زدن (مثلاً double-callback درگاه) کد تکراری نمی‌سازد.
    • best-effort — هر خطی فقط لاگ می‌شود؛ پرداختِ تأییدشده هرگز
      نمی‌شکند. شناسه‌ی فاکتور یا payment_id (مسیر کارت) داده می‌شود."""
    try:
        with _conn_immediate() as c:
            if order_id is None and payment_id is not None:
                row = c.execute(
                    "SELECT * FROM orders WHERE payment_id = ? AND status = ?",
                    (payment_id, ORDER_STATUS_PAID),
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT * FROM orders WHERE id = ?", (order_id,)
                ).fetchone()
            if row is None or row["status"] != ORDER_STATUS_PAID \
                    or not is_group_plan(row["plan"]):
                return
            marker = f"groupsub_done:{row['id']}"
            cur = c.execute(
                "INSERT INTO settings (key, value) VALUES (?, '1') "
                "ON CONFLICT(key) DO NOTHING",
                (marker,),
            )
            if cur.rowcount == 0:
                return  # قبلاً انجام شده
            order = dict(row)
        # تعداد نفرات و پلنِ پایه از نام پلن خوانده می‌شود:
        # «👥 گروهی ۳ نفره · ۱ ماهه» → seats=3, base=۱ ماهه
        seats, base_plan = 0, ""
        try:
            rest = order["plan"][len(GROUP_PLAN_PREFIX):]
            head, _, tail = rest.partition("·")
            m = re.match(r"\s*(\d+)", head)
            seats = int(m.group(1)) if m else 0
            base_plan = tail.strip()
        except Exception:
            seats, base_plan = 0, ""
        if seats < 2 or not base_plan:
            print(f"⚠️ [group_sub] نام پلن قابل تجزیه نیست: {order['plan']}")
            return
        base_row = get_pricing(base_plan)
        duration = int(base_row["duration_days"]) if base_row else 30
        codes = _create_group_licenses_internal(
            order["user_id"], seats - 1, duration, order["id"])
        if codes:
            codes_block = "\n".join(f"`{cd}`" for cd in codes)
            _spawn_bg(_notify_user_async(
                int(order["user_id"]),
                f"👥 **اشتراک دسته‌جمعی فعال شد**\n\n"
                f"🧾 فاکتور: `{order['order_no']}`\n"
                f"👥 نفرات: {seats}\n"
                f"📅 مدت هر صندلی: {duration} روز\n\n"
                f"اشتراکِ خودت همین حالا فعال شد. کدهای زیر مالِ "
                f"{len(codes)} عضو دیگر گروه‌تان است — هر کد، یک اشتراک "
                f"کامل برای یک نفر است:\n\n{codes_block}\n\n"
                f"هر عضو در ربات «🔑 فعال‌سازی با لایسنس» را بزند و کد خودش را "
                f"وارد کند.",
            ), "groupsub_codes")
    except Exception as e:
        print(f"⚠️ [group_sub] fulfillment ناموفق: {type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════════════
#  سیستم دعوت (رفرال)
# ══════════════════════════════════════════════════════════════════════
#  قاعده: هر کاربر یک لینکِ اختصاصی دارد. وقتی N نفر با آن لینک وارد
#  شوند، به دعوت‌کننده یک اشتراکِ هدیه داده می‌شود.

# v2.9.1: محدودیت‌های سراسری برای حفاظت از ban
OUT_DAILY_MAX = 200          # حداکثر ۲۰۰ پیام خروجی در روز
OUT_COOLDOWN_SEC = 1.0        # حداقل ۱ ثانیه بین پیام‌های خروجی
FLOOD_RECOVER_GRACE = 60      # بعد از FloodWait، ۶۰ ثانیه صبر
WARMUP_DURATION_SEC = 1800    # ۳۰ دقیقه گرم‌کردن اکانت جدید
WARMUP_RATE_MULTIPLIER = 0.3  # در warmup، ۳۰٪ نرخ عادی
WARN_NOTIFY_THRESHOLD = 2     # بعد از ۲ هشدار، به OWNER نوتیف بده
# v2.9.2: TELEGRAM_SERVICE_ID در module level (قبلاً فقط داخل یه متد بود)
TELEGRAM_SERVICE_ID = 777000   # فرستنده‌ی رسمیِ پیام‌های تلگرام

# v2.9.5: helper برای parse اعداد فارسی/عربی با comma
def _to_int(text) -> int:
    """تبدیل رشته به int — اعداد فارسی/عربی و comma رو handle می‌کنه.
    مثلاً: "۱٬۲۳۴" → 1234, "50" → 50, "abc" → ValueError.
    """
    if text is None:
        raise ValueError("None")
    s = str(text).strip()
    # حذف comma و space
    s = s.replace(",", "").replace("،", "").replace(" ", "")
    # تبدیل ارقام فارسی/عربی به لاتین
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    for i, c in enumerate(fa):
        s = s.replace(c, str(i))
    for i, c in enumerate(ar):
        s = s.replace(c, str(i))
    return int(s)

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


def _ensure_referral_ready() -> bool:
    """v2.19.4 (AUDIT-36 C2 — لایه‌ی دوم): probe ارزان + خوددرمانیِ لحظه‌ای.

    اگر ستون‌های رفرال به هر دلیلی (DB قدیمی، بوتِ ناقص، مهاجرتِ از دست
    رفته) وجود نداشته باشند، همین‌جا ساخته می‌شوند تا «👤 حساب کاربری»
    (هابِ کیف پول/سفارش‌ها/دعوت) هرگز با OperationalError نشکند — همان
    الگوی _ensure_reporter_ready (v2.19.0). بازگشتِ False یعنی حتی بعد
    از تلاشِ بازسازی هم آماده نیست (fail-open امن: آمارِ رفرال صفر).
    """
    try:
        with _conn() as c:
            c.execute("SELECT referred_by, referral_rewards FROM users LIMIT 1")
        return True
    except Exception:
        try:
            ensure_referral_schema()
            return True
        except Exception as _e:
            print(f"⚠️ [referral] self-heal failed: {type(_e).__name__}: {_e}")
            return False


def ensure_wallet_schema() -> None:
    """Schema کیف پول کاربر — ستونِ موجودی روی users + جدولِ تراکنش‌ها.

    ستون wallet_balance روی users به‌صورت ALTER TABLE اضافه می‌شود (اگه نباشد)
    تا دیتابیس‌های قدیمی بدون dump/restore هم آپدیت شوند.

    جدول wallet_transactions:
      - id           — کلید اصلی
      - user_id      — کاربر صاحب کیف پول (FK به users.user_id، ON DELETE CASCADE)
      - amount       — مثبت = شارژ، منفی = برداشت/پرداخت (Toman)
      - balance_after — موجودی بعد از این تراکنش (برای تاریخچه‌ی حسابرسی)
      - type         — credit|debit|payment|admin_adjust|refund
      - ref          — مرجع اختیاری (مثلاً شماره سفارش)
      - reason       — یادداشتِ انسانی (مثلاً «شارژ دستی توسط OWNER»)
      - created_by   — کاربری که این تراکنش را ایجاد کرده (OWNER/ADMIN یا خود کاربر)
      - created_at   — timestamp ISO
    """
    with _conn() as c:
        # ۱) ستون wallet_balance روی users — اگر قدیمی است، ALTER اضافه کن
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if "wallet_balance" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN wallet_balance INTEGER NOT NULL DEFAULT 0")
            print("✅ [wallet] ستون wallet_balance به users اضافه شد")
        # v2.12.10 (QA2-USER C8 / AUDIT-10-C C1): ستون auto_renew_enabled
        # روی users — برای auto-renewal واقعی. قبلاً auto_renew_subscription
        # وجود داشت ولی هیچ scheduler ای صداش نمی‌زد و هیچ فلگی هم ذخیره
        # نمی‌شد. حالا فلگ رو ذخیره می‌کنیم و در _expiry_loop قبل از انقضا
        # صدا می‌زنیمش.
        if "auto_renew_enabled" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN auto_renew_enabled INTEGER NOT NULL DEFAULT 0")
            print("✅ [auto_renew] ستون auto_renew_enabled به users اضافه شد")
        if "api_id" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN api_id INTEGER DEFAULT NULL")
        if "api_hash" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN api_hash TEXT DEFAULT NULL")
        # v2.12.11 (QA3-QUICK BUG#2): ستون extensions_applied روی orders
        # — برای محدود کردنِ دفعاتِ اکستندِ فاکتورِ pending با رسیدِ آپلود
        # شده. قبلاً expiry_loop هر ۷ روز دوباره اکستند می‌کرد → حلقه‌ی
        # بی‌نهایت. حالا حداکثر ۳ اکستند (۳×۷=۲۱ روز). بعد از ۳ اکستند،
        # اگه هنوز OWNER تایید نکرده، فاکتور واقعاً باطل می‌شه.
        try:
            _order_cols = {r[1] for r in c.execute("PRAGMA table_info(orders)").fetchall()}
            if "extensions_applied" not in _order_cols:
                c.execute("ALTER TABLE orders ADD COLUMN extensions_applied INTEGER NOT NULL DEFAULT 0")
                print("✅ [expiry] ستون extensions_applied به orders اضافه شد")
        except Exception as _e:
            print(f"⚠️ [expiry] add column extensions_applied failed: {_e}")
        # v2.19.4 (AUDIT-36 C1 — لایه‌ی دومِ خوددرمانی): سه ستونی که قبلاً
        # فقط در _migrate_schema ساخته می‌شدند، اینجا هم به‌صورت ALTERِ
        # idempotent اضافه می‌شوند. دلیل: CREATE TABLE IF NOT EXISTS روی
        # نصبِ تازه‌ای که با نسخه‌ی خرابِ قبلی ساخته شده (جدول بدون ستون)
        # هیچ ستونی اضافه نمی‌کند؛ این بلوک همان نصب‌ها را هم نجات می‌دهد —
        # همان الگویی که برای extensions_applied بالاتر رفت.
        try:
            _pay_cols = {r[1] for r in c.execute("PRAGMA table_info(payments)").fetchall()}
            if "receipt_file_uid" not in _pay_cols:
                c.execute("ALTER TABLE payments ADD COLUMN receipt_file_uid TEXT")
                print("✅ [saas_db] ستون receipt_file_uid به payments اضافه شد (self-heal v2.19.4)")
        except Exception as _e:
            print(f"⚠️ [saas_db] self-heal payments.receipt_file_uid: {_e}")
        try:
            _ord_cols = {r[1] for r in c.execute("PRAGMA table_info(orders)").fetchall()}
            _ord_added = False
            if "amount_salt" not in _ord_cols:
                c.execute("ALTER TABLE orders ADD COLUMN amount_salt TEXT DEFAULT '0.00'")
                _ord_added = True
            if "receipt_file_uid" not in _ord_cols:
                c.execute("ALTER TABLE orders ADD COLUMN receipt_file_uid TEXT")
                _ord_added = True
            if _ord_added:
                print("✅ [saas_db] ستون‌های amount_salt/receipt_file_uid به orders اضافه شد (self-heal v2.19.4)")
        except Exception as _e:
            print(f"⚠️ [saas_db] self-heal orders columns: {_e}")
        # ۲) جدول تراکنش‌ها
        c.execute(
            "CREATE TABLE IF NOT EXISTS wallet_transactions ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  user_id INTEGER NOT NULL,"
            "  amount INTEGER NOT NULL,"  # مثبت=شارژ، منفی=برداشت
            "  balance_after INTEGER NOT NULL,"
            "  type TEXT NOT NULL CHECK(type IN ('credit','debit','payment','admin_adjust','refund','reseller_credit')),"
            "  ref TEXT,"                  # مرجع سفارش/پرداخت (اختیاری)
            "  reason TEXT,"
            "  created_by INTEGER,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_transactions(user_id, created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_wallet_created ON wallet_transactions(created_at DESC)")
        # v2.8.12: جدول کدهای تخفیف
        c.execute(
            "CREATE TABLE IF NOT EXISTS discount_codes ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  code TEXT UNIQUE NOT NULL,"
            "  percent INTEGER NOT NULL CHECK(percent > 0 AND percent <= 100),"
            "  max_uses INTEGER NOT NULL DEFAULT 1,"
            "  used_count INTEGER NOT NULL DEFAULT 0,"
            "  expires_at TEXT,"  # ISO timestamp یا None برای بدون انقضا
            "  created_by INTEGER NOT NULL,"
            "  created_at TEXT NOT NULL,"
            "  is_active INTEGER NOT NULL DEFAULT 1"
            ")"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_discount_code ON discount_codes(code)")
        # v2.9.9: پیام زمان‌بندی‌شده + auto-reply + affiliate
        c.execute(
            "CREATE TABLE IF NOT EXISTS scheduled_messages ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  user_id INTEGER NOT NULL,"
            "  tag TEXT NOT NULL,"
            "  chat_id INTEGER NOT NULL,"
            "  text TEXT NOT NULL,"
            "  scheduled_at TEXT NOT NULL,"
            "  sent INTEGER DEFAULT 0,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS auto_replies ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  user_id INTEGER NOT NULL,"
            "  tag TEXT NOT NULL,"
            "  keyword TEXT NOT NULL,"
            "  reply TEXT NOT NULL,"
            "  is_active INTEGER DEFAULT 1,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS broadcast_counters ("
            "  owner_id TEXT NOT NULL,"
            "  date TEXT NOT NULL,"
            "  count INTEGER NOT NULL DEFAULT 0,"
            "  PRIMARY KEY (owner_id, date)"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS affiliate_commissions ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  referrer_id INTEGER NOT NULL,"
            "  referred_id INTEGER NOT NULL,"
            "  order_id INTEGER,"
            "  amount_toman INTEGER NOT NULL,"
            "  commission_percent INTEGER NOT NULL,"
            "  commission_toman INTEGER NOT NULL,"
            "  paid INTEGER DEFAULT 0,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_sched_msg ON scheduled_messages(scheduled_at, sent)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_aff_referrer ON affiliate_commissions(referrer_id, paid)")
        # F-06: unique index on order_id to prevent duplicate commission awards
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_aff_order ON affiliate_commissions(order_id)")


def referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{(bot_username or 'bot').lstrip('@')}?start=ref_{user_id}"


def parse_referral_arg(text: str):
    """از «/start ref_12345» آیدیِ دعوت‌کننده را بیرون می‌کشد."""
    m = re.search(r"/start\s+ref_(\d{3,20})\b", text or "")
    return int(m.group(1)) if m else None


_REFERRAL_RATE_WINDOW = {}

def attach_referrer(user_id: int, referrer_id: int) -> bool:
    """
    ثبتِ دعوت‌کننده برای یک کاربرِ تازه.

    فقط یک بار و فقط برای کاربری که تازه ساخته شده و هنوز دعوت‌کننده
    ندارد — تا کسی نتواند با /start زدنِ دوباره برای خودش یا دیگری
    امتیاز بسازد. خود-دعوتی هم رد می‌شود.
    """
    if not _ensure_referral_ready():
        return False
    if not user_id or not referrer_id or user_id == referrer_id:
        return False
    now_ts = time.time()
    hist = [t for t in _REFERRAL_RATE_WINDOW.get(referrer_id, []) if now_ts - t < 3600]
    if len(hist) >= 20:
        return False
    hist.append(now_ts)
    _REFERRAL_RATE_WINDOW[referrer_id] = hist
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
    """{invited, rewards, remaining} — پیشرفتِ دعوت‌های یک کاربر.

    v2.19.4 (AUDIT-36 C2): اگر ستون‌ها نباشند، اول ساخته می‌شوند و اگر
    حتی بعد از آن هم نباشند، آمارِ صفرِ امن برگردانده می‌شود — صفحهٔ
    «حساب کاربری» هرگز به‌خاطرِ رفرال نمی‌شکند.
    """
    if not _ensure_referral_ready():
        return {"invited": 0, "rewards": 0, "pending": 0,
                "remaining": REFERRAL_GOAL if REFERRAL_GOAL else 0}
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
    """اعطای اتمیک جایزه دعوت در یک تراکنش BEGIN IMMEDIATE همراه با قید یکتایی."""
    if not _ensure_referral_ready():
        return 0
    granted = 0
    with _conn_immediate() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS referral_reward_grants ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  referrer_id INTEGER NOT NULL,"
            "  slot_index INTEGER NOT NULL,"
            "  reward_type TEXT NOT NULL,"
            "  created_at TEXT NOT NULL,"
            "  UNIQUE(referrer_id, slot_index, reward_type)"
            ")"
        )
        invited = c.execute(
            "SELECT COUNT(*) AS n FROM users WHERE referred_by = ?", (user_id,)
        ).fetchone()["n"]
        row = c.execute(
            "SELECT referral_rewards FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        rewards = int((row["referral_rewards"] or 0) if row else 0)
        earned = invited // REFERRAL_GOAL
        pending = max(0, earned - rewards)
        if pending <= 0:
            return 0
        for idx in range(rewards + 1, rewards + pending + 1):
            try:
                c.execute(
                    "INSERT INTO referral_reward_grants (referrer_id, slot_index, reward_type, created_at) "
                    "VALUES (?, ?, 'sub_gift', ?)",
                    (user_id, idx, _now()),
                )
            except sqlite3.IntegrityError:
                continue
            existing = c.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' "
                "ORDER BY expire_date DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            now_utc = datetime.now(timezone.utc)
            if existing:
                existing_expire = _parse_date(existing["expire_date"])
                base = existing_expire if existing_expire > now_utc else now_utc
                c.execute("UPDATE subscriptions SET status = 'superseded' WHERE id = ?", (existing["id"],))
            else:
                base = now_utc
            c.execute(
                "INSERT INTO subscriptions (user_id, plan, start_date, expire_date, status, "
                "license_id, selfbot_tag, created_at) VALUES (?, 'هدیه دعوت', ?, ?, 'active', NULL, NULL, ?)",
                (user_id, _format_date(now_utc), _format_date(base + timedelta(days=REFERRAL_REWARD_DAYS)), _now()),
            )
            granted += 1
        if granted:
            c.execute(
                "UPDATE users SET referral_rewards = COALESCE(referral_rewards, 0) + ? WHERE user_id = ?",
                (granted, user_id),
            )
    if granted:
        log_action(user_id, "referral_reward", f"{granted}×{REFERRAL_REWARD_DAYS}d")
    return granted


# ══════════════════════════════════════════════════════════════════════
#  سیستم کیف پول کاربر (User Wallet) — v2.8.0
# ══════════════════════════════════════════════════════════════════════
#  موجودی به Toman ذخیره می‌شود (INTEGER — فراکشن‌ها فقط در USDT/کریپتو).
#  هر تغییر در موجودی در یک UPDATE اتمیک + INSERT تراکنش ثبت می‌شود.
#  هیچ مسیری مستقیماً wallet_balance را UPDATE نمی‌کند — فقط از طریق این
#  توابع (wallet_credit / wallet_debit / wallet_pay_from_balance) که هم
#  موجودی را آپدیت می‌کنند و هم ردِ تراکنش را با balance_after می‌سازند.

def get_wallet_balance(user_id: int) -> int:
    """موجودی کیف پول کاربر به Toman (۰ اگر کاربر/ستون نباشد).

    v2.19.4 (AUDIT-36 M8 — لایه‌ی دوم): اگر ستونِ wallet_balance به هر
    دلیلی (بوتِ ناقص/قفلِ لحظه‌ایِ DB) وجود نداشته باشد، یک بار
    بازسازی می‌شود و دوباره تلاش می‌شود — منوی کاربر دیگر «خطا در
    پردازشِ» همیشگی نمی‌گیرد. شکستِ نهایی = ۰ (fail-open امن).
    """
    try:
        with _conn() as c:
            row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return int(row["wallet_balance"]) if row and row["wallet_balance"] is not None else 0
    except Exception:
        try:
            ensure_wallet_schema()
            with _conn() as c:
                row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return int(row["wallet_balance"]) if row and row["wallet_balance"] is not None else 0
        except Exception:
            return 0


# v2.12.10 (QA2-USER C8 / AUDIT-10-C C1): getter/setter برای auto_renew_enabled.
def get_auto_renew_enabled(user_id: int) -> bool:
    """آیا auto-renewal برای این کاربر فعاله؟ (ستون auto_renew_enabled در users)"""
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT auto_renew_enabled FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return bool(row and row["auto_renew_enabled"])
    except Exception:
        return False


def set_auto_renew_enabled(user_id: int, enabled: bool) -> bool:
    """تنظیم فلگ auto-renewal برای کاربر. بازگشت: True اگه ست شد."""
    try:
        with _conn() as c:
            # اگه کاربر هنوز در جدول users نیست، upsert کن
            existing = c.execute(
                "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not existing:
                c.execute(
                    "INSERT INTO users (user_id, auto_renew_enabled, created_at) VALUES (?, ?, ?)",
                    (user_id, 1 if enabled else 0, _now()),
                )
            else:
                c.execute(
                    "UPDATE users SET auto_renew_enabled = ? WHERE user_id = ?",
                    (1 if enabled else 0, user_id),
                )
            c.commit()
        return True
    except Exception as _e:
        print(f"⚠️ [auto_renew] set failed for uid={user_id}: {_e}")
        return False


def wallet_credit(user_id: int, amount: int, created_by: int,
                  reason: str = "", tx_type: str = "admin_adjust") -> dict:
    """شارژِ کیف پول کاربر — فقط OWNER/ADMIN مجازند.

    بازگشت:
      {"ok": True, "balance": new_balance, "tx_id": N}
      {"error": "invalid_amount"}     — amount <= 0
      {"error": "user_not_found"}     — کاربر در DB نیست
      {"error": "permission_denied"} — سازنده OWNER/ADMIN نیست
    """
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return {"error": "invalid_amount"}
    # نقشِ سازنده را از DB بخوان — اعتماد به callback نیست
    actor_role = get_role(created_by, OWNER_ID)
    # v2.8.12: RESELLER هم می‌تونه کیف پول مشتری‌های خودش رو شارژ کنه
    # ولی فقط اگه user_id یکی از مشتری‌های خودش باشه (reseller_id == created_by)
    if actor_role not in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
        return {"error": "permission_denied"}
    if actor_role == ROLE_RESELLER:
        # چک کن که آیا user_id یکی از مشتری‌های این نماینده است
        with _conn() as _check_c:
            _u = _check_c.execute("SELECT reseller_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if _u is None or _u["reseller_id"] != created_by:
            return {"error": "permission_denied"}
        # RESELLER فقط credit می‌تونه بده (نه debit) — برای debit OWNER/ADMIN لازم است
    with _conn_immediate() as c:
        row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return {"error": "user_not_found"}
        current = int(row["wallet_balance"] or 0)
        new_balance = current + amount
        c.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?",
                  (new_balance, user_id))
        # v2.8.12: اگه RESELLER شارژ کرده، type = "reseller_credit"
        actual_tx_type = "reseller_credit" if actor_role == ROLE_RESELLER else tx_type
        cur = c.execute(
            "INSERT INTO wallet_transactions "
            "(user_id, amount, balance_after, type, reason, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, amount, new_balance, actual_tx_type, reason, created_by, _now()),
        )
        tx_id = cur.lastrowid
    log_action(created_by, "wallet_credit",
                f"user={user_id}, amount={amount}, reason={reason or '-'}")
    return {"ok": True, "balance": new_balance, "tx_id": tx_id}


def wallet_debit(user_id: int, amount: int, created_by: int,
                 reason: str = "") -> dict:
    """کسر دستی از کیف پول کاربر — فقط OWNER/ADMIN (مثلاً برای اصلاح اشتباه).

    اگر موجودی کافی نباشد خطای insufficient_balance برمی‌گرداند و هیچ
    تغییری در DB داده نمی‌شود.
    """
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return {"error": "invalid_amount"}
    actor_role = get_role(created_by, OWNER_ID)
    if actor_role not in (ROLE_OWNER, ROLE_ADMIN):
        return {"error": "permission_denied"}
    with _conn_immediate() as c:
        row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return {"error": "user_not_found"}
        current = int(row["wallet_balance"] or 0)
        if current < amount:
            return {"error": "insufficient_balance", "balance": current}
        new_balance = current - amount
        c.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?",
                  (new_balance, user_id))
        cur = c.execute(
            "INSERT INTO wallet_transactions "
            "(user_id, amount, balance_after, type, reason, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, -amount, new_balance, "admin_adjust", reason, created_by, _now()),
        )
        tx_id = cur.lastrowid
    log_action(created_by, "wallet_debit",
                f"user={user_id}, amount={amount}, reason={reason or '-'}")
    return {"ok": True, "balance": new_balance, "tx_id": tx_id}


def wallet_pay_from_balance(user_id: int, amount: int, ref: str = "") -> dict:
    """پرداخت از کیف پول کاربر — برای خرید سفارش/تمدید اشتراک.

    فرقش با wallet_debit: نیازی به نقش OWNER/ADMIN ندارد (کاربر خودش
    از موجودی‌اش خرج می‌کند)، و نوع تراکنش 'payment' است با مرجعِ سفارش.
    """
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return {"error": "invalid_amount"}
    with _conn_immediate() as c:
        row = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return {"error": "user_not_found"}
        current = int(row["wallet_balance"] or 0)
        if current < amount:
            return {"error": "insufficient_balance", "balance": current}
        new_balance = current - amount
        c.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?",
                  (new_balance, user_id))
        cur = c.execute(
            "INSERT INTO wallet_transactions "
            "(user_id, amount, balance_after, type, ref, reason, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, -amount, new_balance, "payment", ref, "خرج از کیف پول",
             user_id, _now()),
        )
        tx_id = cur.lastrowid
    log_action(user_id, "wallet_payment",
                f"amount={amount}, ref={ref or '-'}, new_balance={new_balance}")
    return {"ok": True, "balance": new_balance, "tx_id": tx_id}



def pay_order_wallet_atomic(user_id: int, order_id: int) -> dict:
    """پرداخت اتمیک فاکتور از موجودی کیف پول در یک تراکنش واحد BEGIN IMMEDIATE (M-14)."""
    with _conn_immediate() as c:
        order = c.execute(
            "SELECT * FROM orders WHERE id = ? AND user_id = ?",
            (order_id, user_id),
        ).fetchone()
        if not order:
            return {"ok": False, "error": "order_not_found"}
        order = dict(order)
        if order["status"] != ORDER_STATUS_PENDING:
            return {"ok": False, "error": "order_not_pending"}
        amount = int(order["amount_toman"])
        urow = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if urow is None:
            return {"ok": False, "error": "user_not_found"}
        current = int(urow["wallet_balance"] or 0)
        if current < amount:
            return {"ok": False, "error": "insufficient_balance", "balance": current}
        new_balance = current - amount
        c.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?", (new_balance, user_id))
        c.execute(
            "INSERT INTO wallet_transactions "
            "(user_id, amount, balance_after, type, ref, reason, created_by, created_at) "
            "VALUES (?, ?, ?, 'payment', ?, 'خرج از کیف پول', ?, ?)",
            (user_id, -amount, new_balance, f"order:{order['order_no']}", user_id, _now()),
        )
        cur = c.execute(
            "UPDATE orders SET status = 'paid', pay_method = 'wallet', paid_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (_now(), order_id),
        )
        if cur.rowcount == 0:
            raise RuntimeError("order_already_paid_race")
        plan_name = order["plan"]
        days = 30
        if plan_name != DEDICATED_BOT_PLAN:
            prow = c.execute("SELECT duration_days FROM pricing WHERE plan = ?", (plan_name,)).fetchone()
            if prow and prow["duration_days"]:
                days = int(prow["duration_days"])
            existing = c.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' "
                "ORDER BY expire_date DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            now_utc = datetime.now(timezone.utc)
            if existing:
                existing_expire = _parse_date(existing["expire_date"])
                base = existing_expire if existing_expire > now_utc else now_utc
                c.execute("UPDATE subscriptions SET status = 'superseded' WHERE id = ?", (existing["id"],))
            else:
                base = now_utc
            c.execute(
                "INSERT INTO subscriptions (user_id, plan, start_date, expire_date, status, "
                "license_id, selfbot_tag, created_at) VALUES (?, ?, ?, ?, 'active', NULL, NULL, ?)",
                (user_id, plan_name, _format_date(now_utc), _format_date(base + timedelta(days=days)), _now()),
            )
    log_action(user_id, "wallet_payment_atomic", f"order={order_id}, amount={amount}, new_balance={new_balance}")
    # v2.17.0: اگر این فاکتور دسته‌جمعی بود، لایسنس‌های اعضا را بساز/بفرست
    maybe_fulfill_group_order(order_id=order_id)
    return {"ok": True, "balance": new_balance, "plan": plan_name, "days": days, "amount": amount, "order_no": order["order_no"]}

def list_wallet_transactions(user_id: int, limit: int = 20) -> list:
    """آخرین N تراکنشِ کیف پول کاربر — جدیدترین اول."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM wallet_transactions WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# v2.8.12: کدهای تخفیف
def _generate_discount_code() -> str:
    """تولید کد تخفیف ۸-کاراکتری."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بدون ا chars مبهم
    return "".join(secrets.choice(chars) for _ in range(8))


def create_discount_code(percent: int, created_by: int,
                          max_uses: int = 1, expires_at: str = None) -> dict:
    """ساخت کد تخفیف جدید — فقط OWNER/ADMIN."""
    if not isinstance(percent, int) or percent <= 0 or percent > 100:
        return {"error": "invalid_percent"}
    if not isinstance(max_uses, int) or max_uses <= 0:
        return {"error": "invalid_max_uses"}
    actor_role = get_role(created_by, OWNER_ID)
    if actor_role not in (ROLE_OWNER, ROLE_ADMIN):
        return {"error": "permission_denied"}
    code = _generate_discount_code()
    with _conn() as c:
        # اگه کد تصادفی تکراری بود، retry کن
        for _ in range(10):
            exists = c.execute("SELECT 1 FROM discount_codes WHERE code = ?", (code,)).fetchone()
            if not exists:
                break
            code = _generate_discount_code()
        c.execute(
            "INSERT INTO discount_codes (code, percent, max_uses, used_count, expires_at, "
            "created_by, created_at, is_active) VALUES (?, ?, ?, 0, ?, ?, ?, 1)",
            (code, percent, max_uses, expires_at, created_by, _now()),
        )
    log_action(created_by, "create_discount_code", f"code={code}, percent={percent}%")
    return {"ok": True, "code": code}


def toggle_discount_code(code: str, actor_id: int) -> dict:
    """فعال/غیرفعال‌کردن یک کد تخفیف — فقط OWNER/ADMIN.

    TEST-G4-PAYMENT (BUG: discount_toggle: was missing entirely — the UI
    listed codes but had no per-code action; `discount_toggle:` callback
    had no handler and there was no function to flip is_active).
    """
    actor_role = get_role(actor_id, OWNER_ID)
    if actor_role not in (ROLE_OWNER, ROLE_ADMIN):
        return {"error": "permission_denied"}
    with _conn() as c:
        row = c.execute(
            "SELECT id, is_active FROM discount_codes WHERE code = ?", (code,)
        ).fetchone()
        if row is None:
            return {"error": "not_found"}
        new_active = 0 if row["is_active"] else 1
        c.execute(
            "UPDATE discount_codes SET is_active = ? WHERE id = ?",
            (new_active, row["id"]),
        )
    log_action(actor_id, "toggle_discount_code",
               f"code={code} -> {'active' if new_active else 'inactive'}")
    return {"ok": True, "is_active": bool(new_active)}


def get_discount_code(code: str) -> dict:
    """گرفتن کد تخفیف با کد."""
    with _conn() as c:
        row = c.execute("SELECT * FROM discount_codes WHERE code = ? AND is_active = 1", (code,)).fetchone()
    return dict(row) if row else None


def apply_discount_code(code: str, original_amount: int) -> dict:
    """اعمال کد تخفیف — مبلغ بعد از تخفیف رو برمی‌گردونه.

    بازگشت:
      {"ok": True, "amount": new_amount, "percent": p}
      {"error": "not_found"}
      {"error": "expired"}
      {"error": "max_uses_reached"}
    """
    with _conn_immediate() as c:
        row = c.execute("SELECT * FROM discount_codes WHERE code = ? AND is_active = 1", (code,)).fetchone()
        if row is None:
            return {"error": "not_found"}
        d = dict(row)
        if d["used_count"] >= d["max_uses"]:
            return {"error": "max_uses_reached"}
        if d["expires_at"]:
            try:
                from datetime import datetime
                exp = datetime.fromisoformat(d["expires_at"])
                if datetime.utcnow() > exp:
                    return {"error": "expired"}
            except Exception:
                pass
        new_amount = max(1, int(original_amount * (100 - d["percent"]) / 100))
        c.execute("UPDATE discount_codes SET used_count = used_count + 1 WHERE code = ?", (code,))
    return {"ok": True, "amount": new_amount, "percent": d["percent"]}


def list_discount_codes(limit: int = 50) -> list:
    """لیست کدهای تخفیف — برای OWNER/ADMIN."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM discount_codes ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# v2.9.8: درگاه پرداخت ایرانی (Zarinpal)
# این توابع با فراخوانی API Zarinpal یه payment می‌سازه و بعد از پرداخت
# callback رو handle می‌کنه. OWNER باید merchant_id رو در settings ست کنه.
def create_zarinpal_payment(order_id: int, callback_url: str) -> dict:
    """ساخت پرداخت Zarinpal — redirect URL برمی‌گردونه.
    بازگشت: {"ok": True, "url": "..."} یا {"error": "..."}
    """
    import urllib.request, urllib.parse, json as _json
    merchant = (get_setting("zarinpal_merchant") or "").strip()
    if not merchant:
        return {"error": "zarinpal_merchant ست نشده — در پنل ادمین تنظیم کن"}
    order = get_order(order_id)
    if not order:
        return {"error": "order_not_found"}
    amount = int(order["amount_toman"])
    # Zarinpal API request
    try:
        payload = _json.dumps({
            "merchant_id": merchant,
            "amount": amount * 10,  # Zarinpal تومان را به ریال تبدیل می‌کند
            "callback_url": callback_url,
            "description": f"CiaNet اشتراک {order['plan']}",
        }).encode()
        req = urllib.request.Request(
            "https://api.zarinpal.com/pg/v4/payment/request.json",
            data=payload, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = _json.loads(r.read().decode())
        if resp.get("data", {}).get("code") == 100:
            authority = resp["data"]["authority"]
            # ثبت authority در سفارش
            with _conn_immediate() as c:
                c.execute(
                    "UPDATE orders SET pay_method = 'zarinpal', txid = ? WHERE id = ?",
                    (authority, order_id),
                )
            url = f"https://www.zarinpal.com/pg/StartPay/{authority}"
            return {"ok": True, "url": url, "authority": authority}
        return {"error": f"zarinpal_error: {resp}"}
    except Exception as e:
        return {"error": f"zarinpal_request_failed: {e}"}


# v2.10.2: درگاه Zibal
def create_zibal_payment(order_id: int, callback_url: str) -> dict:
    """ساخت پرداخت Zibal — redirect URL برمی‌گردونه."""
    import urllib.request, json as _json
    merchant = (get_setting("zibal_merchant") or "").strip()
    if not merchant:
        return {"error": "zibal_merchant ست نشده"}
    order = get_order(order_id)
    if not order:
        return {"error": "order_not_found"}
    amount = int(order["amount_toman"])
    try:
        payload = _json.dumps({
            "merchant": merchant,
            "amount": amount * 10,
            "callbackUrl": callback_url,
            "description": f"CiaNet {order['plan']}",
        }).encode()
        req = urllib.request.Request(
            "https://gateway.zibal.ir/v1/request",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = _json.loads(r.read().decode())
        if resp.get("result") == 100:
            track_id = resp.get("trackId")
            with _conn_immediate() as c:
                c.execute(
                    "UPDATE orders SET pay_method = 'zibal', txid = ? WHERE id = ?",
                    (str(track_id), order_id),
                )
            url = f"https://gateway.zibal.ir/start/{track_id}"
            return {"ok": True, "url": url, "track_id": track_id}
        return {"error": f"zibal_error: {resp}"}
    except Exception as e:
        return {"error": f"zibal_request_failed: {e}"}


def verify_zibal_payment(track_id: str, amount_toman: int) -> dict:
    """تأیید پرداخت Zibal."""
    import urllib.request, json as _json
    merchant = (get_setting("zibal_merchant") or "").strip()
    if not merchant:
        return {"error": "zibal_merchant ست نشده"}
    try:
        payload = _json.dumps({
            "merchant": merchant,
            "trackId": int(track_id),
            "amount": amount_toman * 10,
        }).encode()
        req = urllib.request.Request(
            "https://gateway.zibal.ir/v1/verify",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = _json.loads(r.read().decode())
        if resp.get("result") in (100, 101):
            return {"ok": True, "ref_id": resp.get("refId")}
        return {"error": f"verify_failed: result={resp.get('result')}"}
    except Exception as e:
        return {"error": f"verify_request_failed: {e}"}


def verify_zarinpal_payment(authority: str, amount_toman: int) -> dict:
    """تأیید پرداخت Zarinpal بعد از redirect به callback."""
    import urllib.request, json as _json
    merchant = (get_setting("zarinpal_merchant") or "").strip()
    if not merchant:
        return {"error": "zarinpal_merchant ست نشده"}
    try:
        payload = _json.dumps({
            "merchant_id": merchant,
            "amount": amount_toman * 10,  # ریال
            "authority": authority,
        }).encode()
        req = urllib.request.Request(
            "https://api.zarinpal.com/pg/v4/payment/verify.json",
            data=payload, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = _json.loads(r.read().decode())
        code = resp.get("data", {}).get("code")
        if code in (100, 101):  # 100=paid, 101=already verified
            return {"ok": True, "ref_id": resp["data"].get("ref_id")}
        return {"error": f"verify_failed: code={code}"}
    except Exception as e:
        return {"error": f"verify_request_failed: {e}"}


# v2.9.8: تمدید خودکار از کیف پول
def auto_renew_subscription(user_id: int) -> dict:
    """اگه اشتراک کاربر منقضی شده و auto_renoval فعال است و موجودی
    کیف پول کافی است، خودکار یه اشتراک جدید بساز.
    بازگشت: {"ok": True, "renewed": True/False, "reason": "..."}

    v2.10.0: کل عملیات در یک _conn_immediate برای جلوگیری از race.
    v2.12.21 (QA7-USER6 BUG#3): قبلاً already_active guard فقط status='active'
    رو چک می‌کرد، ولی _expiry_loop قبل از expire_subscription، auto_renew رو
    صدا می‌زنه — یعنی هنوز 'active' هست. حالا expiry-imminent (active با
    expire_date گذشته) هم به‌عنوان «نیاز به تمدید» در نظر گرفته می‌شه.
    """
    # v2.10.0: atomic lock — دو فراخوانی هم‌زمان نمی‌تونن هر دو succeed کنن
    try:
        with _conn_immediate() as c:
            active = c.execute(
                "SELECT 1 FROM subscriptions WHERE user_id = ? AND status = 'active' "
                "AND expire_date >= ? LIMIT 1",
                (user_id, _now_date())
            ).fetchone()
            if active:
                return {"ok": True, "renewed": False, "reason": "already_active"}
            last_sub = c.execute(
                "SELECT plan FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if not last_sub:
                return {"ok": True, "renewed": False, "reason": "no_previous_plan"}
            plan_name = last_sub["plan"]
            pricing = c.execute("SELECT * FROM pricing WHERE plan = ?", (plan_name,)).fetchone()
            if not pricing:
                return {"ok": True, "renewed": False, "reason": "plan_not_found"}
            amount = int(pricing["price_toman"])
            days = int(pricing["duration_days"] or 30)
            urow = c.execute("SELECT wallet_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            current_bal = int(urow["wallet_balance"] or 0) if urow else 0
            if current_bal < amount:
                return {"ok": True, "renewed": False, "reason": "insufficient_balance"}
            new_balance = current_bal - amount
            c.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?", (new_balance, user_id))
            c.execute(
                "INSERT INTO wallet_transactions "
                "(user_id, amount, balance_after, type, ref, reason, created_by, created_at) "
                "VALUES (?, ?, ?, 'payment', ?, 'تمدید خودکار اشتراک', ?, ?)",
                (user_id, -amount, new_balance, f"auto_renew:{plan_name}", user_id, _now()),
            )
            existing = c.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' "
                "ORDER BY expire_date DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            now_utc = datetime.now(timezone.utc)
            if existing:
                existing_expire = _parse_date(existing["expire_date"])
                base = existing_expire if existing_expire > now_utc else now_utc
                c.execute("UPDATE subscriptions SET status = 'superseded' WHERE id = ?", (existing["id"],))
            else:
                base = now_utc
            c.execute(
                "INSERT INTO subscriptions (user_id, plan, start_date, expire_date, status, "
                "license_id, selfbot_tag, created_at) VALUES (?, ?, ?, ?, 'active', NULL, NULL, ?)",
                (user_id, plan_name, _format_date(now_utc), _format_date(base + timedelta(days=days)), _now()),
            )
    except Exception as _e:
        print(f"⚠️ [auto_renew] atomic transaction failed: {_e}")
        return {"ok": False, "renewed": False, "reason": f"tx_failed: {type(_e).__name__}"}
    log_action(user_id, "auto_renew", f"plan={plan_name}, amount={amount}, days={days}")
    return {"ok": True, "renewed": True, "plan": plan_name, "days": days, "balance": new_balance}


# v2.9.9: پیام زمان‌بندی‌شده
def create_scheduled_message(user_id: int, tag: str, chat_id: int, text: str,
                              scheduled_at: str) -> dict:
    """ساخت پیام زمان‌بندی‌شده. scheduled_at به فرمت ISO."""
    # v2.10.0: validation
    if not tag or not text or not scheduled_at:
        return {"error": "missing_fields"}
    if not isinstance(chat_id, int) or chat_id <= 0:
        return {"error": "invalid_chat_id"}
    try:
        from datetime import datetime
        # v2.14.2 (P2-9 FLOW-3B): نرمال‌سازی فرمت قبل از ذخیره — قبلاً رشته‌ی
        # خام ISO (با «T» یا پسوند Z) ذخیره می‌شد ولی حلقه‌ی ارسال با فرمت
        # «%Y-%m-%d %H:%M:%S» مقایسه‌ی لغت‌نامه‌ای می‌کند؛ چون 'T' > ' '
        # است، پیام‌های T-فرمت تا ~۲۴ ساعت دیر due می‌شدند.
        _dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        if _dt.tzinfo is not None:
            _dt = _dt.astimezone().replace(tzinfo=None)  # → ساعت محلی سرور
        scheduled_at = _dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return {"error": "invalid_scheduled_at"}
    # PATCH (P1-1 BUG-2d): چک مالکیت — قبلاً هر جفتِ (user_id, tag) پذیرفته
    # می‌شد و از طریق پنل می‌شد برای اکانتِ کاربرِ دیگر پیام زمان‌بندی‌شده
    # ساخت (cross-tenant). دفاع عمقی در کنار چکِ web_panel؛ OWNER طبق §20.1
    # قوانین همیشه مجاز است (is_owner_bypass).
    cfg = load_config()
    acc = cfg.get(tag) if isinstance(cfg, dict) else None
    if not (account_belongs_to(acc, tag, user_id) or is_owner_bypass(user_id)):
        return {"error": "account_not_owned"}
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO scheduled_messages (user_id, tag, chat_id, text, "
            "scheduled_at, sent, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (user_id, tag, chat_id, text, scheduled_at, _now()),
        )
    return {"ok": True, "id": cur.lastrowid}


def list_scheduled_messages(user_id: int, limit: int = 50) -> list:
    """لیست پیام‌های زمان‌بندی‌شده‌ی کاربر."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM scheduled_messages WHERE user_id = ? "
            "ORDER BY scheduled_at ASC LIMIT ?", (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_scheduled_message(msg_id: int, user_id: int) -> bool:
    """حذف پیام زمان‌بندی‌شده (با مالکیت چک)."""
    with _conn_immediate() as c:
        cur = c.execute(
            "DELETE FROM scheduled_messages WHERE id = ? AND user_id = ? AND sent = 0",
            (msg_id, user_id),
        )
    return cur.rowcount > 0


# v2.9.9: auto-reply templates
def create_auto_reply(user_id: int, tag: str, keyword: str, reply: str) -> dict:
    """ساخت پاسخ خودکار بر اساس کلمه‌ی کلیدی."""
    # v2.10.0: validation
    if not tag or not keyword or not reply:
        return {"error": "missing_fields"}
    keyword = keyword.strip()[:100]
    reply = reply.strip()[:1000]
    if not keyword or not reply:
        return {"error": "empty_after_trim"}
    # PATCH (P2-1 BUG-2d residual): چک مالکیت — همان دروازه‌ای که P1-1 به
    # create_scheduled_message اضافه کرد. قبلاً هر جفتِ (user_id, tag)
    # پذیرفته می‌شد و از طریق پنل می‌شد برای اکانتِ کاربرِ دیگر auto-reply
    # ساخت (cross-tenant). دفاع عمقی در کنار چکِ web_panel؛ OWNER طبق §20.1
    # قوانین همیشه مجاز است (is_owner_bypass).
    cfg = load_config()
    acc = cfg.get(tag) if isinstance(cfg, dict) else None
    if not (account_belongs_to(acc, tag, user_id) or is_owner_bypass(user_id)):
        return {"error": "account_not_owned"}
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO auto_replies (user_id, tag, keyword, reply, is_active, "
            "created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (user_id, tag, keyword, reply, _now()),
        )
    return {"ok": True, "id": cur.lastrowid}


def list_auto_replies(user_id: int) -> list:
    """لیست auto-replies کاربر."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM auto_replies WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_auto_reply(reply_id: int, user_id: int) -> bool:
    """حذف auto-reply."""
    with _conn_immediate() as c:
        cur = c.execute(
            "DELETE FROM auto_replies WHERE id = ? AND user_id = ?",
            (reply_id, user_id),
        )
    return cur.rowcount > 0


def find_auto_reply(tag: str, text: str, user_id: int = None) -> str:
    """جستجوی auto-reply برای کلمه‌ی کلیدی در text."""
    text_lower = (text or "").lower().strip()
    with _conn() as c:
        rows = c.execute(
            "SELECT keyword, reply FROM auto_replies "
            "WHERE tag = ? AND is_active = 1 AND (? IS NULL OR user_id = ?)",
            (tag, user_id, user_id),
        ).fetchall()
    for r in rows:
        if r["keyword"].lower() in text_lower:
            return r["reply"]
    return None


# v2.9.9: affiliate commission

def get_broadcast_daily_count(owner_key: str) -> int:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT count FROM broadcast_counters WHERE owner_id = ? AND date = ?",
                (str(owner_key), today_str),
            ).fetchone()
            return int(row["count"]) if row else 0
    except Exception:
        return 0


def increment_broadcast_daily_count(owner_key: str, delta: int = 1, cap: int = 200) -> bool:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with _conn_immediate() as c:
            row = c.execute(
                "SELECT count FROM broadcast_counters WHERE owner_id = ? AND date = ?",
                (str(owner_key), today_str),
            ).fetchone()
            cur_val = int(row["count"]) if row else 0
            if cur_val + delta > cap:
                return False
            c.execute(
                "INSERT INTO broadcast_counters (owner_id, date, count) VALUES (?, ?, ?) "
                "ON CONFLICT(owner_id, date) DO UPDATE SET count = count + ?",
                (str(owner_key), today_str, delta, delta),
            )
            return True
    except Exception:
        return False

def create_affiliate_commission(referrer_id: int, referred_id: int,
                                order_id: int, amount_toman: int,
                                commission_percent: int = 10) -> dict:
    """ثبت کمیسیون affiliate."""
    # v2.10.0: validation
    if not isinstance(commission_percent, int) or commission_percent < 0 or commission_percent > 100:
        return {"error": "invalid_commission_percent"}
    if not isinstance(amount_toman, int) or amount_toman < 0:
        return {"error": "invalid_amount"}
    if referrer_id == referred_id:
        return {"error": "self_referral"}
    commission = int(amount_toman * commission_percent / 100)
    with _conn() as c:
        # F-06: INSERT OR IGNORE for dedup (unique index on order_id)
        cur = c.execute(
            "INSERT OR IGNORE INTO affiliate_commissions (referrer_id, referred_id, "
            "order_id, amount_toman, commission_percent, commission_toman, "
            "paid, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (referrer_id, referred_id, order_id, amount_toman,
             commission_percent, commission, _now()),
        )
        if cur.rowcount == 0:
            return {"ok": True, "dedup": True}
    log_action(referrer_id, "affiliate_commission",
               f"referred={referred_id}, amount={amount_toman}, commission={commission}")
    return {"ok": True, "commission_toman": commission, "id": cur.lastrowid}


def list_affiliate_commissions(referrer_id: int, limit: int = 50) -> list:
    """لیست کمیسیون‌های affiliate یک کاربر."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM affiliate_commissions WHERE referrer_id = ? "
            "ORDER BY id DESC LIMIT ?", (referrer_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def affiliate_stats(referrer_id: int) -> dict:
    """آمار affiliate: تعداد، مجموع کمیسیون، پرداخت‌شده."""
    with _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(commission_toman),0) AS s, "
            "SUM(CASE WHEN paid=1 THEN commission_toman ELSE 0 END) AS p "
            "FROM affiliate_commissions WHERE referrer_id = ?",
            (referrer_id,),
        ).fetchone()
    # v2.10.0: COALESCE برای جلوگیری از NULL در paid_commission
    s_val = int(total["s"] or 0)
    p_val = int(total["p"] or 0)
    return {
        "total_referrals": int(total["n"] or 0),
        "total_commission": s_val,
        "paid_commission": p_val,
        "pending_commission": s_val - p_val,
    }


def list_users_for_reseller(reseller_id: int) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM users WHERE reseller_id = ? ORDER BY created_at DESC", (reseller_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────
#  درخواست‌های نمایندگی (reseller_applications) — TEST-G7-RESELLER
# ─────────────────────────────────────────────────────
#  BUG (extractor): جدولِ reseller_applications فقط INSERT می‌شد — هیچ
#  UPDATE‌ای در کل کد وجود نداشت، پس وضعیتِ pending تا ابد می‌ماند و
#  OWNER هیچ راهی برای تأیید/رد نداشت. PATCH-8 قرار بود
#  _update_reseller_application را اضافه کند ولی این تابع در main.py
#  وجود نداشت. این تابع‌ها آن مسیر را سَرِ سَری پیاده می‌کنند.

def list_pending_reseller_applications() -> list:
    """TEST-G7-RESELLER: همه‌ی درخواست‌های pending — برای پنلِ OWNER."""
    with _conn() as c:
        rows = c.execute(
            "SELECT a.id AS app_id, a.user_id, a.status, a.created_at, "
            "a.reviewed_at, a.reviewed_by, "
            "u.username, u.first_name "
            "FROM reseller_applications a "
            "LEFT JOIN users u ON u.user_id = a.user_id "
            "WHERE a.status = 'pending' "
            "ORDER BY a.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_reseller_application(user_id: int) -> Optional[dict]:
    """TEST-G7-RESELLER: جدیدترین درخواستِ این کاربر (هر وضعیت)."""
    with _conn() as c:
        row = c.execute(
            "SELECT a.id AS app_id, a.user_id, a.status, a.created_at, "
            "a.reviewed_at, a.reviewed_by, "
            "u.username, u.first_name "
            "FROM reseller_applications a "
            "LEFT JOIN users u ON u.user_id = a.user_id "
            "WHERE a.user_id = ? "
            "ORDER BY a.created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
    return dict(row) if row else None


def _update_reseller_application(user_id: int, status: str,
                                 decided_by: int = None) -> bool:
    """
    TEST-G7-RESELLER (BUG: reseller_applications was INSERT-only —
    no UPDATE anywhere — so approved/rejected state never persisted.
    PATCH-8 was supposed to wire this up but the function did not
    exist in main.py). این تابع وضعیتِ جدید روی همه‌ی درخواست‌های
    pendingِ این کاربر اعمال می‌کند و reviewed_at/reviewed_by را ست
    می‌کند. True برمی‌گرداند اگه رکوردی affected شد.

    فقط 'approved' یا 'rejected' مجاز است؛ مقدار دیگر ValueError پرتاب
    می‌کند تا صدا زننده‌ی اشتباهی در یافت‌زود بمیرد.
    """
    if status not in ("approved", "rejected"):
        raise ValueError(
            "status باید 'approved' یا 'rejected' باشد — مقدارِ دریافتی: %r" % (status,)
        )
    with _conn_immediate() as c:
        cur = c.execute(
            "UPDATE reseller_applications "
            "SET status = ?, reviewed_at = ?, reviewed_by = ? "
            "WHERE user_id = ? AND status = 'pending'",
            (status, _now(), decided_by, user_id),
        )
        return cur.rowcount > 0


def list_all_users() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def list_active_bot_users() -> list:
    """v2.14.5: فقط کاربرانی که ربات را /start کرده‌اند (در bot_data.db هستند).

    این تابع برای broadcast/announce استفاده می‌شه تا فقط به کاربرانی که
    واقعاً ربات رو start کردن پیام بفرستیم — نه همه‌ی ثبت‌شده‌ها. این کار
    FloodWait رو کم می‌کنه و پیام به کاربرانی که ربات رو بلاک کردن یا
    start نکردن ارسال نمی‌شه.

    Returns:
        list of dicts with user_id, username, first_name, last_seen
    """
    try:
        with _bot_db() as c:
            rows = c.execute(
                "SELECT user_id, username, first_name, last_seen "
                "FROM users ORDER BY last_seen DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"⚠️ [list_active_bot_users] fallback به list_all_users: {e}")
        return list_all_users()


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
    # v2.12.28 (HUNT-5 #8): atomic predicate check inside write transaction.
    # قبلاً PRECHECK بدون lock بود و بین SELECT و DELETE یه اشتراک فعال
    # ساخته می‌شد ولی حذف از قلم می‌افتاد. حالا داخل _conn_immediate
    # چک می‌کنیم.
    owned_dedicated = []
    with _conn_immediate() as c:
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
    """Set subscription status to 'expired'.

    v2.12.31 (DEBUG-1 NEXT-S-1): اضافه‌کردن WHERE status='active' برای
    جلوگیری از overwrite کردن status های دیگر (مثل 'superseded' که
    بعداً SET شده). قبلاً اگر expire_subscription روی یک sub_id که
    قبلاً superseded شده بود صدا زده می‌شد، آن را به 'expired' تبدیل
    می‌کرد که از نظر تراکنشی اشتباه بود.
    """
    with _conn() as c:
        c.execute(
            "UPDATE subscriptions SET status = 'expired' "
            "WHERE id = ? AND status = 'active'",
            (sub_id,),
        )


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

    ۳) v2.10.1: max_uses از پارامتر خوانده می‌شه (default=1).
       می‌تونه ۱ تا ۱۰۰۰ باشه — یعنی یه لایسنس رو می‌شه چند بار استفاده کرد.
       مثلاً max_uses=5 یعنی ۵ کاربر می‌تونن با همین کد اشتراک فعال کنن.

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
    # v2.10.1: اعتبارسنجی max_uses
    if max_uses is None:
        max_uses = 1
    if not isinstance(max_uses, int) or isinstance(max_uses, bool) or max_uses < 1 or max_uses > 1000:
        return {"error": "invalid_max_uses"}
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
            "VALUES (?, ?, ?, ?, 0, ?, ?, ?, 1)",
            (code, license_type, duration_days, max_uses, reseller_user_limit, created_by, _now()),
        )
    log_action(created_by, "create_license", f"code={code}, type={license_type}, max_uses={max_uses}")
    return get_license(code)


def create_license_batch(license_type: str, duration_days, created_by: int,
                         count: int, reseller_user_limit=None, max_uses: int = 1) -> dict:
    """
    ساخت گروهیِ لایسنس — همان اعتبارسنجیِ create_license، ولی N بار در یک
    تراکنشِ اتمیک. اگر کدی تصادفاً تکرار شد (احتمال عملاً صفر)، فقط همان
    ردیف skip می‌شود و بقیه ساخته می‌شوند — ساخت گروهی هرگز با کدِ تأیید-
    نشده INSERT نمی‌کند.

    ورودی:
      license_type  — "account" | "reseller" | "admin"
      duration_days — برای account (مثبت)، None برای reseller/admin
      created_by    — user_id سازنده (OWNER/ADMIN/RESELLER)
      count         — تعداد لایسنس (1..BATCH_LICENSE_MAX)
      reseller_user_limit — فقط برای reseller (مثبت)

    بازگشت:
      {"ok": True, "licenses": [...], "failed": k}  — k ردیف ناموفق
      {"error": "..."}                              — خطای ورودی
    """
    # اعتبارسنجیِ count — جلوگیری از مقادیر بیمعتنا و DoS
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return {"error": "invalid_count"}
    if count > BATCH_LICENSE_MAX:
        return {"error": "too_many"}
    # همان ماتریس دسترسیِ create_license
    _LICENSE_ALLOWED = {
        ROLE_OWNER: {LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER, LICENSE_TYPE_ADMIN},
        ROLE_ADMIN: {LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER},
        ROLE_RESELLER: {LICENSE_TYPE_ACCOUNT},
    }
    if license_type not in (LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER,
                            LICENSE_TYPE_ADMIN):
        return {"error": "invalid_type"}
    caller_role = get_role(created_by, OWNER_ID)
    if caller_role not in _LICENSE_ALLOWED or \
            license_type not in _LICENSE_ALLOWED[caller_role]:
        return {"error": "permission_denied"}
    # اعتبارسنجیِ ورودی بر اساس نوع — دقیقاً مثل create_license
    if license_type == LICENSE_TYPE_ACCOUNT:
        if not isinstance(duration_days, int) or isinstance(duration_days, bool) \
                or duration_days <= 0:
            return {"error": "invalid_duration"}
        reseller_user_limit = None
    elif license_type == LICENSE_TYPE_RESELLER:
        if not isinstance(reseller_user_limit, int) \
                or isinstance(reseller_user_limit, bool) or reseller_user_limit <= 0:
            return {"error": "invalid_limit"}
        duration_days = None
    else:  # admin
        if duration_days is not None:
            return {"error": "invalid_duration"}
        reseller_user_limit = None
    licenses = []
    failed = 0
    # v2.10.1: اعتبارسنجی max_uses
    if not isinstance(max_uses, int) or isinstance(max_uses, bool) or max_uses < 1 or max_uses > 1000:
        return {"error": "invalid_max_uses"}
    with _conn() as c:
        for _i in range(count):
            code = _generate_license_code()
            unique = False
            for _ in range(10):
                exists = c.execute("SELECT 1 FROM licenses WHERE code = ?", (code,)).fetchone()
                if not exists:
                    unique = True
                    break
                code = _generate_license_code()
            if not unique:
                failed += 1
                continue
            c.execute(
                "INSERT INTO licenses (code, license_type, duration_days, max_uses, used_count, "
                "reseller_user_limit, created_by, created_at, is_active) "
                "VALUES (?, ?, ?, ?, 0, ?, ?, ?, 1)",
                (code, license_type, duration_days, max_uses, reseller_user_limit, created_by, _now()),
            )
            row = c.execute("SELECT * FROM licenses WHERE code = ?", (code,)).fetchone()
            licenses.append(dict(row))
    log_action(created_by, "create_license_batch",
                f"type={license_type}, count={count}, ok={len(licenses)}, failed={failed}")
    return {"ok": True, "licenses": licenses, "failed": failed}


def list_licenses(limit: int = 50, created_by: int = None,
                  license_type: str = None) -> list:
    """
    لیست لایسنس‌های ساخته‌شده (جدیدترین اول) — برای پنل «🎫 لایسنس‌ها».
    created_by: اگر داده شود فقط لایسنس‌های همان سازنده (نماینده فقط لایسنس‌های
    خودش را می‌بیند — نه لایسنس‌های بقیه).
    license_type: v2.13.0 (TEST-G3-LICENSE FIX#2) — فیلتر بر اساس نوع
    (account|reseller|admin). None یعنی همه‌ی نوع‌ها. مقدار نامعتبر
    silently به None تبدیل می‌شود (defensive).
    """
    # normalize filter — فقط مقادیر معتبر پذیرفته می‌شوند
    if license_type not in (LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER,
                            LICENSE_TYPE_ADMIN, None):
        license_type = None
    with _conn() as c:
        if created_by is not None and license_type is not None:
            rows = c.execute(
                "SELECT * FROM licenses WHERE created_by = ? AND license_type = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (created_by, license_type, limit),
            ).fetchall()
        elif created_by is not None:
            rows = c.execute(
                "SELECT * FROM licenses WHERE created_by = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?", (created_by, limit),
            ).fetchall()
        elif license_type is not None:
            rows = c.execute(
                "SELECT * FROM licenses WHERE license_type = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (license_type, limit),
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


def deactivate_license(code: str, actor_id: int = None) -> bool:
    """
    فعال‌سازی یک لایسنس را False می‌کند (is_active=0) — کد و ردیف حفظ
    می‌شوند تا تاریخچه/گزارش دست‌نخورده باقی بماند. اگر لایسنس از قبل
    غیرفعال بود، این عمل idempotent است.

    v2.13.0 (TEST-G3-LICENSE FIX#1): قبلاً این تابع تعریف می‌شد ولی
    هیچ callback/UI آن را صدا نمی‌زد (dead code) و در نتیجه OWNER
    نمی‌توانست لایسنس ساخته‌شده را غیرفعال کند. حالا با callback
    `lic_deactivate:{code}` به آن وصل شده و audit log می‌نویسد.
    خروجی: True اگر چیزی واقعاً تغییر کرد، False اگر ردیف پیدا نشد یا
    از قبل غیرفعال بود.
    """
    with _conn() as c:
        cur = c.execute(
            "UPDATE licenses SET is_active = 0 WHERE code = ? AND is_active = 1",
            (code,),
        )
        changed = cur.rowcount > 0
    if changed:
        log_action(actor_id, "deactivate_license", f"code={code}")
    return changed


def delete_license(code: str, actor_id: int = None) -> bool:
    """
    حذف کامل یک ردیف لایسنس از جدول — فقط برای لایسنس‌هایی که هنوز
    استفاده نشده‌اند (used_count=0) یا غیرفعال‌اند. این عمل قابل بازگشت
    نیست؛ برای «غیرفعال‌کردنِ موقتی» از deactivate_license استفاده کن.

    v2.13.0 (TEST-G3-LICENSE FIX#1): تابعِ جدید — قبلاً هیچ مسیری برای
    حذف تک‌تکِ لایسنس‌ها وجود نداشت (فقط cascade حذف کاربر در
    purge_user_records، که مربوط به حذف کاربر است نه لایسنس).
    خروجی: True اگر ردیف واقعاً حذف شد.
    """
    with _conn() as c:
        cur = c.execute("DELETE FROM licenses WHERE code = ?", (code,))
        deleted = cur.rowcount > 0
    if deleted:
        log_action(actor_id, "delete_license", f"code={code}")
    return deleted


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
    mu = lic.get("max_uses", 1)
    if mu > 1:
        lines.append(f"🔒 مصرف:\n{fa_digits(mu)} بار")
    else:
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


def _license_batch_result_text(result: dict) -> str:
    """متنِ نتیجه‌ی ساختِ گروهی — هم موفقیت و هم خطای امنِ Backend.
    برای ≤۱۰ کد، همه‌ی کدها در یک پیام؛ برای بیشتر، فقط خلاصه را برمی‌گرداند
    (لیست کامل از طریق فایل ارسال می‌شود — فراخواننده مسئول send_file است)."""
    if not result or "error" in result:
        err = result.get("error", "unknown_error") if result else "unknown_error"
        return "❌ " + _LICENSE_ERROR_TEXT.get(err, _LICENSE_ERROR_TEXT["unknown_error"])
    licenses = result.get("licenses", [])
    failed = result.get("failed", 0)
    if not licenses:
        return "❌ هیچ لایسنسی ساخته نشد."
    lines = [f"✅ {len(licenses)} لایسنس ساخته شد"]
    if failed:
        lines.append(f"⚠️ {failed} لایسنس به‌دلیل تصادف کد ساخته نشد (دوباره تلاش کن).")
    lines.append("")
    if len(licenses) <= 10:
        for lic in licenses:
            lines.append(f"`{lic['code']}`")
    else:
        lines.append(f"📋 {len(licenses)} کد ساخته شد — لیست کامل را در فایل پیوست ببین.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────
#  پرداخت‌ها
# ─────────────────────────────────────────────────────

def create_payment(user_id: int, plan: str, amount: int, receipt_ref: str, receipt_file_uid: str = None) -> int:
    """
    receipt_ref باید یک مرجع قابل‌بازیابی به پیام اصلیِ رسید باشد، مثلاً
    f"{chat_id}:{message_id}" — نه صرفاً یک عدد داخلی media که به‌تنهایی
    برای دانلود مجدد کافی نیست.

    v2.13.0 (DEBUG-2 BUG#1): جلوگیری از استفاده‌ی مجدد از رسید — قبلاً
    کاربر می‌توانست یک رسید را برای چندین پرداخت ثبت کند و OWNER هر دو را
    تأیید کند → durations stack (2× days for one payment). حالا: اگر رسید
    قبلاً ثبت شده (pending یا approved)، رد می‌شود.
    """
    if not receipt_ref:
        raise ValueError("receipt_ref الزامی است")
    with _conn_immediate() as c:
        # v2.13.0: dedup check — atomic با INSERT
        existing = c.execute(
            "SELECT id, status FROM payments WHERE (receipt_ref = ? OR (? IS NOT NULL AND receipt_file_uid = ?)) "
            "AND status IN ('pending', 'approved') LIMIT 1",
            (receipt_ref, receipt_file_uid, receipt_file_uid),
        ).fetchone()
        if existing:
            raise ValueError(
                f"این تصویر رسید قبلاً برای پرداخت #{existing['id']} "
                f"(وضعیت: {existing['status']}) ثبت شده — هر رسید فقط یک‌بار قابل استفاده است."
            )
        cur = c.execute(
            "INSERT INTO payments (user_id, plan, amount, receipt_ref, receipt_file_uid, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (user_id, plan, amount, receipt_ref, receipt_file_uid, _now()),
        )
        return cur.lastrowid


def get_payment(payment_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    return dict(row) if row else None


def cleanup_stale_approved_payments() -> int:
    with _conn_immediate() as c:
        cur = c.execute(
            "UPDATE orders SET status = 'paid', pay_method = 'card', paid_at = COALESCE(paid_at, ?) "
            "WHERE status = 'pending' AND payment_id IN (SELECT id FROM payments WHERE status = 'approved')",
            (_now(),),
        )
        return cur.rowcount


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

    v2.12.11 (QA3-QUICK BUG#2): در حالتِ reject، فاکتورِ متصل هم باید
    cancelled بشه. قبلاً فقط payment.status=rejected ست می‌شد ولی order
    در حالت pending می‌موند و expiry_loop هر ۷ روز پیام «هنوز در صف بررسی
    است» به کاربر می‌فرستاد — گمراه‌کننده و آزاردهنده.
    """
    status = PAYMENT_STATUS_APPROVED if approve else PAYMENT_STATUS_REJECTED
    with _conn() as c:
        cur = c.execute(
            "UPDATE payments SET status = ?, reviewed_by = ?, reviewed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (status, reviewed_by, _now(), payment_id),
        )
        if cur.rowcount == 0:
            return False
        # v2.12.11: در reject، فاکتور متصل رو cancelled کن تا expiry_loop
        # دیگه اون رو اکستند نکنه و پیام گمراه‌کننده نفرسته.
        if not approve:
            c.execute(
                "UPDATE orders SET status = 'cancelled', paid_at = NULL "
                "WHERE payment_id = ? AND status = 'pending'",
                (payment_id,),
            )
        return True


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
    # v2.17.0: اگر فاکتورِ متصل دسته‌جمعی بود، لایسنس‌های اعضا را بساز/بفرست
    maybe_fulfill_group_order(payment_id=payment_id)
    return {"applied": True, "plan": pay["plan"], "user_id": user_id,
            "duration": duration, "dedicated": False}


# ─────────────────────────────────────────────────────
#  فاکتورها/سفارش‌ها — شماره‌ی سفارش، مبلغ دقیق (تومان+تتر)، انقضای پرداخت
# ─────────────────────────────────────────────────────

def create_order(user_id: int, plan: str, amount_toman: int, amount_usdt: float,
                 expires_hours: int = ORDER_EXPIRE_HOURS,
                 discount_code: str = None) -> dict:
    """فاکتور جدید با شماره‌ی ترتیبی (ORD-00001) و انقضای پرداخت.

    v2.9.0: اگه discount_code داده بشه، کد تخفیف رو اعمال می‌کنه و
    amount_toman/amount_usdt رو با تخفیف می‌سازه. original_amount_toman
    و discount_percent و discount_code هم در DB ذخیره می‌شن.
    """
    original_amount = amount_toman
    discount_percent = 0
    applied_code = None
    # v2.12.29 (DEEP-7 #7): zero-amount validation — اگه amount <= 0
    # باشه، order گیر می‌کنه و قابل پرداخت نیست.
    if amount_toman <= 0:
        return {"error": "invalid_amount"}
    from decimal import Decimal, ROUND_HALF_UP
    base_usdt_dec = Decimal(str(amount_usdt or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if discount_code:
        result = apply_discount_code(discount_code, amount_toman)
        if result.get("ok"):
            amount_toman = result["amount"]
            discount_percent = result["percent"]
            applied_code = discount_code
            base_usdt_dec = (base_usdt_dec * Decimal(100 - discount_percent) / Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            return {"error": result.get("error", "discount_failed")}
    salt_cents = secrets.randbelow(99) + 1
    salt_dec = (Decimal(salt_cents) / Decimal(100)).quantize(Decimal("0.01"))
    if base_usdt_dec > Decimal("0"):
        final_usdt_dec = base_usdt_dec + salt_dec
    else:
        final_usdt_dec = Decimal("0.00")
        salt_dec = Decimal("0.00")
    amount_usdt = float(final_usdt_dec)
    amount_salt_str = str(salt_dec)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_hours)).strftime(_DATETIME_FMT)
    try:
        with _conn_immediate() as c:
            row = c.execute("SELECT value FROM settings WHERE key = 'order_seq'").fetchone()
            seq = (int(row["value"]) if row and str(row["value"]).isdigit() else 0) + 1
            c.execute(
                "INSERT INTO settings (key, value) VALUES ('order_seq', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(seq),),
            )
            cur = c.execute(
                "INSERT INTO orders (order_no, user_id, plan, amount_toman, amount_usdt, amount_salt, status, "
                "created_at, expires_at, discount_code, discount_percent, original_amount_toman) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                (f"ORD-{seq:05d}", user_id, plan, amount_toman, amount_usdt, amount_salt_str, _now(), expires_at,
                 applied_code, discount_percent, original_amount),
            )
            oid = cur.lastrowid
    except Exception:
        # PATCH (P2-1 residual): apply_discount_code کد را در تراکنشِ جداگانه‌ای
        # مصرف می‌کند (used_count += 1)؛ اگر ثبتِ خودِ سفارش شکست بخورد، کد
        # «سوخته» می‌ماند بی‌آنکه سفارشی ساخته شده باشد. برای اتمیک‌ماندنِ
        # نتیجه، used_count را برگردان می‌داریم (همان الگوی rollback در
        # cancel_order و ویزارد تخفیفِ P1-3). سپس خطا مثل قبل به caller
        # برگردانده می‌شود (مسیر موفق دست‌نخورده است).
        if applied_code:
            try:
                with _conn_immediate() as c:
                    c.execute(
                        "UPDATE discount_codes SET used_count = MAX(0, used_count - 1) "
                        "WHERE UPPER(code) = UPPER(?) AND used_count > 0",
                        (applied_code,),
                    )
            except Exception as _rb:
                print(f"⚠️ [create_order] discount rollback failed: {_rb}")
        raise
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
    # v2.14.2 (P2-3 flag / §11.4): rollback used_count کد تخفیف هنگام
    # انقضا — v2.14.0 در changelog ادعایش را داشت ولی پیاده نشده بود.
    # الگوی دقیقاً همان cancel_order (DEBUG-1 MEDIUM-2).
    with _conn_immediate() as c:
        row = c.execute(
            "SELECT discount_code FROM orders WHERE id = ? AND status = 'pending'",
            (order_id,),
        ).fetchone()
        if row is None:
            return
        discount_code = row["discount_code"] if "discount_code" in row.keys() else None
        cur = c.execute(
            "UPDATE orders SET status = 'expired' WHERE id = ? AND status = 'pending'",
            (order_id,),
        )
        if cur.rowcount > 0 and discount_code:
            try:
                c.execute(
                    "UPDATE discount_codes SET used_count = MAX(0, used_count - 1) "
                    "WHERE UPPER(code) = UPPER(?) AND used_count > 0",
                    (discount_code,),
                )
            except Exception as _e:
                # rollback failure is not fatal — log and continue
                print(f"⚠️ [expire_order] discount rollback failed: {_e}")


def extend_order(order_id: int, user_id: int, hours: int = 24) -> dict:
    """تمدید پنجره‌ی پرداخت یک فاکتورِ pending (یا بازگرداندن یک فاکتورِ
    expired به pending) توسط صاحبِ آن — بدون تغییر مبلغ/پلن.

    TEST-G4-PAYMENT (BUG: order_extend: / order_extend_go: were entirely
    missing — the user_orders screen listed orders but had no action
    buttons; an expired pending order with no receipt could never be
    revived from the UI, forcing the user to abandon it and start a
    new purchase). این تابع idempotent است: فقط روی فاکتورهای pending
    یا expired که متعلق به همین کاربرند اثر می‌کند.

    بازگشت:
      {"ok": True, "order_no": str, "new_expires_at": str}
      {"error": "not_found"}      — فاکتور متعلق به این کاربر نیست
      {"error": "invalid_state"}  — فاکتور paid/cancelled است
      {"error": "invalid_hours"}  — hours باید عدد مثبت باشد
    """
    if not isinstance(hours, int) or hours <= 0 or hours > 24 * 30:
        return {"error": "invalid_hours"}
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM orders WHERE id = ? AND user_id = ?",
            (order_id, user_id),
        ).fetchone()
        if row is None:
            return {"error": "not_found"}
        if row["status"] not in (ORDER_STATUS_PENDING, ORDER_STATUS_EXPIRED):
            return {"error": "invalid_state"}
        new_expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime(_DATETIME_FMT)
        c.execute(
            "UPDATE orders SET status = 'pending', expires_at = ? WHERE id = ?",
            (new_expires, order_id),
        )
    log_action(user_id, "extend_order", f"order={order_id} +{hours}h")
    return {"ok": True, "order_no": row["order_no"], "new_expires_at": new_expires}


def cancel_order(order_id: int, user_id: int) -> None:
    """لغو فاکتور توسط صاحب آن — فقط اگر هنوز pending باشد.

    v2.12.31 (DEBUG-1 MEDIUM-2): rollback used_count از کد تخفیف.
    قبلاً وقتی کاربر فاکتور با کد تخفیف می‌ساخت و بعد لغو می‌کنه،
    `used_count` کد تخفیف هنوز incremented می‌موند. این یعنی یک کاربر
    مخرب می‌توانست 10 فاکتور با کد max_uses=10 بسازه و همه رو لغو کنه
    تا کد تخفیف رو برای همه‌ی کاربران دیگر غیرقابل استفاده کنه.
    حالا: در لغو فاکتور، اگه کد تخفیف داشت، used_count را decrement کن.
    """
    with _conn_immediate() as c:
        # First fetch the order to find its discount_code
        row = c.execute(
            "SELECT discount_code FROM orders WHERE id = ? AND user_id = ? AND status = 'pending'",
            (order_id, user_id),
        ).fetchone()
        if row is None:
            return  # nothing to cancel
        discount_code = row["discount_code"] if "discount_code" in row.keys() else None
        # Mark cancelled
        cur = c.execute(
            "UPDATE orders SET status = 'cancelled' WHERE id = ? AND user_id = ? AND status = 'pending'",
            (order_id, user_id),
        )
        # Rollback discount_code used_count if applicable
        if cur.rowcount > 0 and discount_code:
            try:
                c.execute(
                    "UPDATE discount_codes SET used_count = MAX(0, used_count - 1) "
                    "WHERE UPPER(code) = UPPER(?) AND used_count > 0",
                    (discount_code,),
                )
            except Exception as _e:
                # rollback failure is not fatal — log and continue
                print(f"⚠️ [cancel_order] discount rollback failed: {_e}")


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
        with _conn_immediate() as c:
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
            # v2.12.31 (DEBUG-1 MEDIUM-4): DEDICATED_BOT_PLAN نباید
            # subscription بسازد. قبلاً pay_order_trc20_atomic به‌صورت
            # unconditional برای همه‌ی plan‌ها (حتی "ربات اختصاصی") subscription
            # می‌ساخت، که باعث می‌شد کاربر با پرداخت 1 USDT برای فاکتور ربات
            # اختصاصی، اشتراک 30 روزه‌ی regular رایگان دریافت کند. حالا:
            # برای DEDICATED_BOT_PLAN، فقط status='paid' set کن و dedicated
            # bot را activate کن (نه subscription).
            user_id = order["user_id"]
            if order["plan"] == DEDICATED_BOT_PLAN:
                # Activate dedicated bot instead of creating subscription.
                # _activate_dedicated_bot در main.py وجود دارد ولی برای
                # جلوگیری از circular dependency، فقط log می‌کنیم و
                # _process_dedicated_bot_payment در callback path آن را
                # activate می‌کند.
                log_action(user_id, "order_paid_trc20_dedicated",
                           f"order={order_id}, plan=DEDICATED_BOT_PLAN")
                return {"ok": True, "plan": order["plan"],
                        "duration": 0, "dedicated": True}
            # اشتراک — منطق تمدید همان create_subscription است، ولی درون همین
            # تراکنش تا با paid شدن فاکتور اتمیک بماند.
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
    try:
        urow = get_user(user_id)
        if urow and urow.get("referred_by"):
            # F-05: درصد کمیسیون از تنظیمات خوانده می‌شود (قبلاً همیشه 10 پیش‌فرض
            # بود و تنظیم affiliate_commission_percent فقط در تابع مرده خوانده می‌شد)
            _aff_pct = int(get_setting("affiliate_commission_percent", "10") or "10")
            create_affiliate_commission(int(urow["referred_by"]), user_id, order_id, int(order.get("amount_toman") or 0), _aff_pct)
    except Exception:
        pass
    log_action(user_id, "order_paid_trc20", f"order={order_id}, plan={order['plan']}")
    # v2.17.0: اگر این فاکتور دسته‌جمعی بود، لایسنس‌های اعضا را بساز/بفرست
    maybe_fulfill_group_order(order_id=order_id)
    return {"ok": True, "plan": order["plan"], "duration": duration}


def set_order_payment_id(order_id: int, payment_id: int, user_id: int = None, receipt_file_uid: str = None) -> bool:
    """اتصال یک‌بارنویس فاکتور به رسید کارتی ثبت‌شده با بررسی اجباری مالکیت (ضد IDOR)."""
    with _conn_immediate() as c:
        if user_id is None:
            prow = c.execute("SELECT user_id FROM payments WHERE id = ?", (payment_id,)).fetchone()
            user_id = int(prow["user_id"]) if prow else -1
        cur = c.execute(
            "UPDATE orders SET payment_id = ?, receipt_file_uid = COALESCE(?, receipt_file_uid) "
            "WHERE id = ? AND payment_id IS NULL AND status = 'pending' AND user_id = ?",
            (payment_id, receipt_file_uid, order_id, user_id),
        )
        return cur.rowcount > 0


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
        # v1.9.3: timeout=10 ثانیه برای جلوگیری از hang بی‌نهایت روی DB
        # قفل. قبلاً اگه سشن یا DB قفل بود، src.backup() بی‌نهایت
        # صبر می‌کرد (default timeout = 5 ثانیه برای connect ولی backup
        # بدون timeout) و callback تلگرام بعد از ۳۰ ثانیه بسته می‌شد.
        # در نتیجه کاربر هیچ پیامی نمی‌دید و فکر می‌کرد بکاپ نرفت.
        # حالا: اگه ۱۰ ثانیه طول بکشه، RuntimeError با پیام روشن.
        import time as _t
        deadline = _t.monotonic() + 10.0
        src = sqlite3.connect(path, timeout=10.0)
        try:
            dst = sqlite3.connect(tmp, timeout=10.0)
            try:
                # backup با sleep بین صفحات تا بتونیم timeout کنیم
                def _progress(remaining, total, page_size):
                    if _t.monotonic() > deadline:
                        raise RuntimeError(
                            f"sqlite backup timeout بعد از ۱۰ ثانیه روی {path}"
                        )
                    return False  # ادامه بده
                src.backup(dst, progress=_progress)
                ok = True
                return tmp
            finally:
                try:
                    dst.close()
                except Exception:
                    pass
        finally:
            try:
                src.close()
            except Exception:
                pass
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

    v2.22.1 (AUDIT-39/c#4): «database is locked/busy» دیگر «غیر-SQLite»
    تفسیر نمی‌شود — قبلاً OperationalErrorِ قفلِ نوشتن هم زیرِ چترِ
    DatabaseError می‌آمد و False برمی‌گشت و نتیجه‌اش بایگانیِ خامِ یک سشنِ
    وسطِ نوشتن در بکاپ بود (به‌ویژه در بکاپِ ساعتیِ سلف‌ها که فاصله‌ی
    زدنی با سشن‌های فعال دارد). حالا قفل = خطا (fail-closed): caller یا
    retry می‌کند یا بکاپ را رد می‌کند — هرگز کپیِ خامِ ناسالم نمی‌سازد.
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
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "locked" in msg or "busy" in msg:
            # قفلِ نوشتنِ یک سشنِ واقعی — placeholder نیست؛ fail-closed
            raise
        return False
    except (sqlite3.DatabaseError, OSError):
        return False


def _encrypt_file_inplace(path: str, password: str) -> bool:
    """
    رمزگذاریِ in-place فایل با PBKDF2+Fernet (فرمت CNB1).

    v2.13.0 همین بلوک داخلِ build_backup_zip بود؛ v2.22.0 به‌عنوانِ هلپرِ
    مشترک استخراج شد تا بکاپِ ساعتیِ سشن‌ها هم از همان مسیرِ امن استفاده
    کند. False یعنی شکست (caller باید فایل را حذف کند)؛ فایلِ موفق همان
    path با ciphertext جایگزین می‌شود.
    """
    tmp_enc = path + ".enc.tmp"
    if not password:
        return False
    try:
        import base64
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
        fernet = Fernet(key)
        with open(path, "rb") as src:
            plain = src.read()
        enc = b"CNB1" + salt + fernet.encrypt(plain)
        with open(tmp_enc, "wb") as dst:
            dst.write(enc)
        os.replace(tmp_enc, path)
        _chmod_private(path)
        return True
    except Exception as e:
        print(f"⛔ [backup] رمزگذاری PBKDF2+Fernet ناموفق (fail-closed): {e}")
        try:
            os.remove(tmp_enc)
        except Exception:
            pass
        return False


def build_sessions_backup_zip(zip_path: str, password: Optional[str] = None) -> bool:
    """
    v2.22.0 (OWNER-REQUEST): بکاپِ سبکِ «فقط سشن‌های سلف» برای حلقهٔ ساعتی.

    همان قواعدِ امنیتیِ build_backup_zip، بدونِ دیتابیس‌ها و config:
      - هر سشن با API backup خودِ SQLite snapshot می‌شود (نه کپیِ خام)
        و sidecarهای -wal/-shm هرگز به‌صورتِ مستقل داخل نمی‌روند؛ سشنِ
        قفل‌شده (وسطِ نوشتنِ یک کلاینتِ فعال) با خطا رد می‌شود (fail-closed
        — v2.22.1/AUDIT-39: کپیِ خامِ سشنِ قفل‌شده ممنوع)؛
      - سشن‌های خودِ ربات‌ها (_admin_bot و helper_bot) داخلش نمی‌روند
        (v2.22.1/AUDIT-39/c#9): این بکاپ «سلف‌ها» است و هر ساعت به یک
        گروه می‌رود — سشنِ پنلِ مدیریت نباید شعاعِ انفجارش را وسع دهد؛
        در بکاپِ کاملِ روزانه (که به DM مالک می‌رود) همچنان هستند؛
      - هر snapshot با integrity_check اعتبارسنجی می‌شود (v2.22.1) —
        فایلِ پاره داخل ZIP نمی‌رود؛
      - manifest با sha256 همان بایت‌هایی که داخل ZIP می‌روند ساخته می‌شود
        (نشانِ kind="sessions-only" تا از بکاپِ کامل قابلِ تشخیص باشد)؛
      - قبل از تحویل، خودِ ZIP باز و تست می‌شود (testzip + manifest)؛
      - رمزگذاری Fernet اجباری است — بدونِ CIANET_BACKUP_PASS هیچ
        فایلی ساخته نمی‌شود (fail-closed، مثلِ بکاپِ کامل).
    """
    snaps = {}
    try:
        if not os.path.isdir(SESSIONS_DIR):
            return False
        files = {}
        for fname in sorted(os.listdir(SESSIONS_DIR)):
            full = os.path.join(SESSIONS_DIR, fname)
            if os.path.isfile(full) and fname.endswith(".session"):
                # v2.22.1: سشن‌های ربات‌های خودِ سیستم — در بکاپِ ساعتیِ
                # «سلف‌ها» جایی ندارند (در بکاپِ کاملِ روزانه هستند).
                if fname in (f"{ADMIN_BOT_SESSION_NAME}.session",
                             f"{HELPER_SESSION_NAME}.session"):
                    continue
                files[os.path.join("sessions", fname)] = full
        if not files:
            return False
        for arc, real in files.items():
            s = _snapshot_session_to_temp(real)
            if s is not None:
                # v2.22.1 (AUDIT-39/c#4): اعتبارسنجیِ هر snapshot قبل از
                # بایگانی — همان استانداردِ بکاپِ کامل (validate_backup_zip)
                # که نسخهٔ فقط-سشن قبلاً از آن بی‌بهره بود.
                if not _db_integrity_ok(s):
                    print(f"⛔ [backup] snapshot سشن {real} integrity_check"
                          " را پاس نکرد — بکاپِ ساعتی رد شد (fail-closed).")
                    try:
                        os.remove(s)
                    except Exception:
                        pass
                    return False
                snaps[arc] = s
        manifest = {
            "project": BACKUP_PROJECT_NAME,
            "backup_version": BACKUP_VERSION,
            "schema_version": BACKUP_SCHEMA_VERSION,
            "kind": "sessions-only",
            "created_at": _now(),
            "files": [
                {"name": arc, "size": os.path.getsize(snaps.get(arc, real)),
                 "sha256": _sha256_file(snaps.get(arc, real))}
                for arc, real in sorted(files.items())
            ],
        }
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for arc, real in sorted(files.items()):
                zf.write(snaps.get(arc, real), arcname=arc)
            zf.writestr(BACKUP_MANIFEST, json.dumps(
                manifest, ensure_ascii=False, indent=2))
        _chmod_private(zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            if zf.testzip() is not None or BACKUP_MANIFEST not in zf.namelist():
                try:
                    os.remove(zip_path)
                except Exception:
                    pass
                return False
        if password is None:
            password = os.environ.get("CIANET_BACKUP_PASS", "").strip()
        if not password:
            print("⛔ [backup] CIANET_BACKUP_PASS تنظیم نشده است — بکاپِ ساعتیِ سشن "
                  "بدون رمزنگاری متوقف شد (fail-closed).")
            try:
                os.remove(zip_path)
            except Exception:
                pass
            return False
        if not _encrypt_file_inplace(zip_path, password):
            try:
                os.remove(zip_path)
            except Exception:
                pass
            return False
        return True
    except Exception as e:
        print(f"⚠️ [backup] ساخت بکاپِ سشن‌ها ناموفق: {e}")
        try:
            os.remove(zip_path)
        except Exception:
            pass
        return False
    finally:
        for tmp in snaps.values():
            try:
                os.remove(tmp)
            except Exception:
                pass


def build_backup_zip(zip_path: str, password: Optional[str] = None) -> bool:
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

    v2.13.0 (DEBUG-2-BACKUP-SEC): اگر password داده شود، فایل ZIP بعد از
    validate شدن به‌صورت in-place با Fernet (AES-128-CBC + HMAC-SHA256،
    از کتابخانه‌ی `cryptography`) رمزگذاری می‌شود. کلید از
    `SHA-256(password)` و با base64url-encoding ساخته می‌شود (مطابق
    فرمت 32-byte‌ی Fernet). فایل خروجی همان `zip_path` است ولی محتوایش
    Fernet ciphertext است. این محافظت در برابر دسترسیِ server-side
    تلگرام یا نشتِ فایل است (نه در برابر کسی که هم پیامِ رمز و هم فایل را
    داشته باشد) — رمز باید در کانال/چتِ جدا از فایل ارسال شود تا
    defense-in-depth معنا داشته باشد. اگر `cryptography` نصب نباشد،
    fallback می‌کنیم به ZipCrypto ضعیف (setpassword) — بهتر از هیچ.
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
        # v2.13.0 (DEBUG-2-BACKUP-SEC): رمزگذاری اختیاری فایل ZIP با Fernet.
        # فقط وقتی password داده شده انجام می‌شود. فایلِ validate‌شده
        # in-place (همان مسیر) با Fernet ciphertext جایگزین می‌شود تا
        # caller بدون تغییرِ مسیر بتواند آن را send_file کند.
        if password is None:
            password = os.environ.get("CIANET_BACKUP_PASS", "").strip()
        if not password:
            print("⛔ [backup] CIANET_BACKUP_PASS تنظیم نشده است — ساخت بکاپ بدون رمزنگاری متوقف شد (fail-closed).")
            try:
                os.remove(zip_path)
            except Exception:
                pass
            return False
        if password:
            if not _encrypt_file_inplace(zip_path, password):
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
            # v2.14.2 (P2-10 / §20.3): فایلِ موقت با umask پیش‌فرض (0644)
            # ساخته شده و os.replace همان inode/mode را به مقصد می‌آورد —
            # پس مقصدِ جایگزین‌شده (config/DB/سشن) باید دوباره 0600 شود.
            _chmod_private(dest)
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
            # v2.14.2 (P2-10 / §20.3): مثل بالا — بعد از replace، mode به
            # 0600 برگردانده می‌شود (فایل موقت 0644 بود).
            _chmod_private(dest)
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
                # v2.14.2 (P2-10 / §20.3): sidecar های بازگردانده‌شده هم
                # داده‌های حساس دارند — مثل بقیه‌ی مقاصد 0600 می‌شوند.
                _chmod_private(sc_dest)
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
            # v2.14.2 (P2-10 / §20.3): استخراجِ بکاپ (config/DB/سشن‌ها) داخل
            # workdir با umask پیش‌فرض 0644 نوشته می‌شود — خودِ پوشه‌ی
            # workdir باید 0700 باشد تا در طولِ عملیاتِ Restore (که می‌تواند
            # طولانی باشد) برای دیگر کاربرانِ همان ماشین خوانا نباشد.
            _chmod_private(workdir, 0o700)
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
            # v2.14.2 (P2-10 / §20.3): فایلِ استخراج‌شده در workdir با umask
            # پیش‌فرض (0644) ساخته شده و os.replace همان inode/mode را به
            # مقصد می‌آورد — config.json و دیتابیس‌ها (و سشن‌ها، دفاع در
            # لایه‌ی فایل علاوه بر پوشه‌ی 0700) باید دوباره 0600 شوند؛
            # مثل الگوی save_config (chmod بعد از replace).
            _chmod_private(dest)
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
    "sesspage:",  # v2.12.31 (DEBUG-1 LOW-1): complete central gate
    "tfa:", "tfareset:", "tfago:", "tfacancel:",
    "tfachange:", "tfaremove:", "tfaemail:",  # v2.12.31 (DEBUG-1 LOW-1)
    "getcode:", "codeget:", "codearm:",
    "login_guard:",  # v2.12.24: محافظتِ ورود
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
        # v2.12.31 (DEBUG-1 HIGH-1): OWNER نباید بتواند login_guard را روی
        # اکانتِ کاربرِ دیگر (USER/RESELLER) فعال کند — این یک حمله‌ی DoS
        # بود که در آن OWNER می‌توانست اکانت کاربر را قفل کند تا کاربر
        # نتواند از دستگاه جدیدی لاگین کند.OWNER فقط می‌تواند login_guard
        # را روی اکانت‌های خودش toggle کند. عملیاتِ حساسِ دیگر (مانند
        # disable/enable) همچنان روی همه مجاز است — چون برای disable/enable
        # مسیر recovery از web panel وجود دارد، ولی login_guard هیچ راه
        # recovery از داخل ربات ندارد.
        # این restriction فقط برای login_guard:Capability_login_guard
        # applies نیست (چون فقط در _toggle_login_guard چک می‌شود)، ولی
        # چون authorize_sensitive_account_action در همه‌ی مسیرهای حساس
        # فراخوانی می‌شود، چک را اینجا نکنیم تا جلوی عملیاتِ legit_admin
        # را نگیریم. به‌جای آن، چک را در خود _toggle_login_guard اضافه
        # می‌کنیم تا فقط برای آن مسیر اعمال شود.
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
ADMIN_ID = int(_admin_id_raw) if _admin_id_raw.isdigit() else 0
# v2.8.6 BUGFIX: warning واضح اگه ADMIN_ID ست نشده — قبلاً فقط یه هشدار
# تو init_db چاپ می‌شد که گاهی جا می‌افتاد. حالا در همان ابتدای اجرای main.py
# این warning نشون داده می‌شه تا کاربر بفهمه چرا نقش OWNER نمی‌گیره.
if ADMIN_ID == 0:
    print("\n" + "=" * 60)
    print("🚨 خطای حیاتی: متغیر ADMIN_ID تنظیم نشده!")
    print("🚨 بدون این متغیر، کاربر به‌عنوان ROLE_USER شناخته می‌شه و")
    print("🚨 منوی OWNER/ADMIN (شامل لایسنس، آپدیت، پنل وب و...) رو نمی‌بینه.")
    print("🚨 راه‌حل:")
    print("🚨   echo ADMIN_ID=YOUR_TELEGRAM_ID | sudo tee -a /etc/selfbot.env")
    print("🚨   sudo systemctl restart selfbot")
    print("=" * 60 + "\n")  # 0 = تنظیم‌نشده

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
# PATCH (v2.3.0): قابلیت override با env var CIANET_BACKUP_HOURS
# مثلاً CIANET_BACKUP_HOURS="0,12" یا CIANET_BACKUP_HOURS="3"
_backup_hours_env = os.environ.get("CIANET_BACKUP_HOURS", "").strip()
if _backup_hours_env:
    try:
        BACKUP_HOURS_IRAN = [int(h.strip()) for h in _backup_hours_env.split(",") if h.strip().isdigit() and 0 <= int(h.strip()) < 24]
        if not BACKUP_HOURS_IRAN:
            BACKUP_HOURS_IRAN = [0, 12]
    except Exception:
        BACKUP_HOURS_IRAN = [0, 12]
else:
    BACKUP_HOURS_IRAN = [0, 12]  # [ساعت ۱, ساعت ۲, ...] — به وقت ایران

# مراحل ویزارد «افزودن اکانت»
WIZ_TAG = "awaiting_tag"
WIZ_PHONE = "awaiting_phone"
WIZ_CODE = "awaiting_code"
WIZ_PASSWORD = "awaiting_password"
# v2.15.3 (LOGIN-UX): منتظر تاییدِ «حذف سلف قبلی + لاگین مجدد» (دکمه‌ای)
WIZ_CONFIRM_REPLACE = "awaiting_confirm_replace"
# PATCH (v2.6.2): wizard states برای تغییر/حذف رمز 2FA و تغییر ایمیل
WIZ_2FA_OLD_PASS = "awaiting_2fa_old_pass"
WIZ_2FA_NEW_PASS = "awaiting_2fa_new_pass"
WIZ_2FA_NEW_HINT = "awaiting_2fa_new_hint"
WIZ_2FA_EMAIL = "awaiting_2fa_email"
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
    # v2.15.3 (LOGIN-UX): دکمه‌های ویزارد لاگین «عمل» هستند نه «صفحه»
    "wiz_resend_code", "confirm_replace:",
    "user_support_end", "proxy_skip_auth",
    "send_target_me", "owner_channel_check",
    # بستنِ نشست‌ها عمل است و خودش فهرست را دوباره رندر می‌کند
    "sessterm:", "sesskill:", "sesstog:", "codeget:", "codearm:",
    "tfago:", "tfacancel:", "login_guard:",  # v2.12.24
    # PATCH (USER-REPORT v2.14.3): تأیید/انصرافِ Anti-Ban «عمل» است نه «صفحه» —
    # توکنِ آن یک‌بارمصرف است (uuid)؛ push شدنش در پشته‌ی ناوبری ورودیِ
    # مُرده می‌ساخت: «بازگشت» به آن برمی‌گشت، توکن مصرف‌شده فقط alertِ
    # «منقضی شده» می‌داد و صفحه‌ای رندر نمی‌شد — دکمه‌ی بازگشت از دیدِ
    # کاربر «کار نمی‌کرد» و باید چندبار پشتِ‌سرهم می‌زد.
    "abok:", "abno:",
    # اعطا/سلبِ مجوز عمل است؛ صفحه‌ی کاربر را دوباره رندر می‌کنند.
    "cap_grant:", "cap_revoke:", "dbcap_grant:", "dbcap_revoke:",
    # TEST-G4-PAYMENT: عملیات‌های جدید که اکشن هستند (re-render، نه نویگیت).
    "discount_toggle:", "order_extend_go:",
    # TEST-G7-RESELLER: تأیید/رد درخواست نمایندگی عمل است (re-render
    # لیست درخواست‌ها). push به پشته‌ی ناوبری نکنند.
    "reseller_approve:", "reseller_reject:",
    # TEST-G6-SYSTEM: action-style aliases that re-render a page or
    # perform an operation in-place (mirroring the existing non-aliased
    # variants: owner_db_backup and owner_channel_clear ARE actions).
    # Aliases that *navigate* (update_status, owner_panel_link,
    # panel_link:, owner_admins, channel_set:, owner_announce) are
    # intentionally NOT here — they need to push the current page onto
    # the nav stack so Back works correctly.
    "update_check:", "update_apply:",
    "owner_db_backup_go:", "channel_clear:",
    # v2.22.1 (AUDIT-39): عمل‌های v2.22.0 که صفحه را دوباره رندر می‌کنند —
    # بدونِ این‌ها، اولین «بازگشت» بعد از ذخیره، ویزاردِ مُرده را دوباره
    # باز می‌کرد به‌جای صفحهٔ والد (یافتهٔ 39-d #5).
    "channel_remove:", "self_backup_confirm_save",
    "owner_self_backup_toggle", "owner_self_backup_clear",
    # v2.22.1 (AUDIT-39): toggle آزمایشی هم عمل است (صفحهٔ آزمایشی را
    # دوباره رندر می‌کند، مثل owner_toggle_group_sub).
    "owner_toggle_trial", "owner_trial_days",
    "setting_save:", "announce_send:", "announce_cancel",
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


def bot_error_alert_text(exc: Exception, is_owner: bool = False,
                         base: str = None) -> str:
    """v2.19.1 (DIAG): متنِ هشدارِ catch-all دیسپچر — خود-تشخیصی.

    پس از باگِ production ریپورتر (۲۰۲۶-۱۰-۲۱) معلوم شد پیامِ عمومیِ
    «خطا در پردازش این دکمه» برای مالک هیچ سرنخی به جا نمی‌گذارد و
    تشخیصِ ریشه بدون journalctl ممکن نیست. دو بهبود:

    • FloodWaitError خطای واقعی نیست — تلگرام به‌صورتِ گذرا ویرایشِ
      سریعِ پیام‌ها را محدود می‌کند (مخصوصاً بلافاصله بعد از restart،
      وقتی ربات مشغلِ جبرانِ اعلان‌هاست و کاربر پشت‌سرهم منو را
      می‌کلیکد). به‌جای «❌ خطا»، پیامِ آرامِ «چند ثانیه صبر کن» با
      خودِ مدت نشان می‌دهیم تا کاربر نترسد و منتظر بماند.
    • برای OWNER، نامِ نوعِ خطا + پیامِ کوتاهش به همان alert اضافه
      می‌شود — اسکرین‌شاتِ بعدیِ مالک، بدون لاگِ سرور هم قابلِ تشخیص
      است. (مثلاً «OperationalError: no such table» همان چیزی بود که
      باگِ v2.19.0 را در یک نگاه لو می‌داد.)

    متنِ برگشتی همیشه ≤ ۲۰۰ کاراکتر است (سقفِ alert تلگرام).

    v2.19.3 (IMG_8254): پارامترِ ``base`` اضافه شد — دیسپچرِ **متن**ِ
    ویزارد (saas.py) هم همین تابع را استفاده می‌کند ولی متنِ پایه‌اش
    «پیام» است نه «دکمه». پیش‌فرض دقیقاً همان متنِ قبلی است (سازگار
    با v2.19.1).
    """
    name = type(exc).__name__
    # v2.19.4 (AUDIT-36 L1): خواهرهای دارایِ «seconds» هم پیامِ آرام می‌گیرند
    # (SlowModeWaitError و هم‌خانواده‌ها — همان منطقِ FloodWait).
    _has_wait_secs = bool(getattr(exc, "seconds", None))
    if name == "FloodWaitError" or (name.endswith("WaitError") and _has_wait_secs):
        try:
            secs = int(getattr(exc, "seconds", 0) or 0)
        except Exception:
            secs = 0
        if secs > 0:
            return (f"⏳ تلگرام فعلاً محدودش کرده — حدود {secs} ثانیه صبر کن"
                    " و دوباره بزن.")
        return "⏳ تلگرام فعلاً محدودش کرده — چند ثانیه صبر کن و دوباره بزن."
    if base is None:
        base = "❌ خطا در پردازش این دکمه. دوباره تلاش کن."
    if not is_owner:
        return base
    # str(exc) ممکن است چندخطی/طولانی باشد → یک‌خطی و بریده
    detail = " ".join(str(exc).split())[:90]
    return f"{base}\n🔍 {name}: {detail}" if detail else f"{base}\n🔍 {name}"


async def run_admin_bot_forever(selfbot_module):
    """
    سوپروایزر ساده برای ربات مدیریت مستقل: اگر به هر دلیلی قطع/کرش کند،
    دوباره راه‌اندازی می‌شود. این تابع فقط برای اجرای admin_bot.py به‌تنهایی
    استفاده می‌شود (standalone=True، پیش‌فرض)، نه وقتی زیرِ saas_bot.py است.
    """
    consecutive_failures = 0
    MAX_BACKOFF = 300
    # PATCH (P1-1 BUG-24): بک‌آف فقط وقتی ریست می‌شود که اتصال مدتی (۳۰۰s)
    # پایدار مانده باشد. قبلاً هر قطعِ تمیز بک‌آف را صفر می‌کرد؛ اگر سرورِ
    # تلگرام به‌طور مکرر (و تمیز) قطع می‌کرد، ری‌استارت فوری و بدون فاصله
    # اتفاق می‌افتاد. قطعِ تمیزِ زودهنگام حالا مثل خطا شمرده می‌شود.
    STABLE_UPTIME_SEC = 300
    while True:
        try:
            admin = AdminBot(selfbot_module, standalone=True)
            await admin.start()
            connected_at = time.monotonic()
            await admin.client.run_until_disconnected()
            if time.monotonic() - connected_at >= STABLE_UPTIME_SEC:
                # اتصال پایدار بود → ریست بک‌آف (رفتار سالمِ قبلی)
                consecutive_failures = 0
            else:
                # قطعِ تمیزِ زودهنگام → بک‌آف حفظ/افزایش می‌شود
                consecutive_failures += 1
                wait_time = min(10 * (2 ** min(consecutive_failures, 5)), MAX_BACKOFF)
                print(f"⚠️ [admin_bot] قطع تمیز پیش از {STABLE_UPTIME_SEC}s — تلاش مجدد در {wait_time}s")
                await asyncio.sleep(wait_time)
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

# PATCH (v2.0.10): پشتیبانی از multi-OWNER. OWNER_IDS env (comma-separated)
# اجازه می‌ده چند کاربر نقش OWNER داشته باشن. اگه تنظیم نشه، فقط ADMIN_ID
# مالک است (همان رفتار قبلی). هر کس که در OWNER_IDS باشه هم به‌عنوان OWNER
# شناخته می‌شه و در is_owner_bypass و notify ها مشمول می‌شه.
_owner_ids_raw = os.environ.get("OWNER_IDS", "").strip()
OWNER_IDS: set = set()
if _owner_ids_raw:
    for _oid in _owner_ids_raw.split(","):
        _oid = _oid.strip()
        if _oid.isdigit():
            OWNER_IDS.add(int(_oid))
if ADMIN_ID:
    OWNER_IDS.add(ADMIN_ID)

# دو متن جداگانه: «سلف چیست» (معرفی کوتاه با ویژگی‌ها) و
# «راهنمای فعال‌سازی» (مراحل قدم‌به‌قدم).
# v1.8.0: این دو متن قبلاً با هم ترکیب شده بودن و کاربر شکایت داشت.

WHAT_IS_SELFBOT_TEXT = (
    "ℹ️ **سلف چیست؟**\n\n"
    "سلف یک دستیار هوشمند روی اکانت تلگرام خودته که "
    "بدون نیاز به گوشی روشن، ۲۴ ساعته کار می‌کنه.\n\n"
    "**قابلیت‌های کلیدی:**\n"
    "🕐 ساعت روی اسم و بیو\n"
    "✅ تیک خودکار پیام‌ها\n"
    "💬 پاسخ خودکار هوشمند\n"
    "🗑 ذخیره پیام‌های حذف‌شده\n"
    "✏️ ذخیره پیام‌های ادیت‌شده\n"
    "👁 استاک (ذخیره استوری‌ها)\n"
    "📥 سیو خودکار از کانال‌ها\n"
    "🧰 جعبه‌ابزار ادمینی\n\n"
    "**امنیت:**\n"
    "🔐 سشن رمزگذاری‌شده\n"
    "🛡 محافظت Anti-Ban برای شماره‌های خارج\n"
    "💾 بکاپ خودکار روزانه\n\n"
    "💡 برای فعال‌سازی، از منوی اصلی «📖 راهنمای فعال‌سازی» رو بزن."
)

ACTIVATION_HELP_TEXT = (
    "📖 **راهنمای فعال‌سازی سلف — قدم به قدم**\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "**مرحله ۱: خرید اشتراک**\n"
    "از منوی اصلی یکی رو انتخاب کن:\n"
    "• «🛒 خرید سلف» → پرداخت ریالی/تتری\n"
    "• «🔑 خرید با لایسنس» → اگه لایسنس از ادمین داری\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "**مرحله ۲: لاگین اکانت**\n"
    "بعد از فعال شدن اشتراک، دکمه‌ی «📱 لاگین کردن سلف» "
    "در منوی اصلی نمایش داده می‌شه. روش بزن.\n\n"
    "اگه قبلاً لاگین کرده بودی، موقع وارد کردن شماره ازت می‌پرسه سلفِ "
    "قبلی حذف بشه و از نو لاگین بشی (تایید/انصراف).\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "**مرحله ۳: وارد کردن شماره**\n"
    "شماره‌ی اکانت تلگرامت رو بفرست:\n"
    "• ایران: `+989123456789`\n"
    "• خارج: `+1234567890` (بدون صفر اول)\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "**مرحله ۴: کد تأیید**\n"
    "تلگرام یه کد به اکانتت می‌فرسته.\n"
    "⚠️ موقع فرستادنِ کد، بین حداقل یکی از ارقامش فاصله بذار:\n"
    "✅ `12 345` — ❌ `12345`\n"
    "(کدِ بدون فاصله ممکنه منقضی بشه و لاگین انجام نشه)\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "**مرحله ۵: رمز دو مرحله‌ای (اختیاری)**\n"
    "اگه اکانتت رمز ۲FA داره، ازت می‌پرسه. وگرنه نیازی نیست.\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "**🎉 تبریک!**\n"
    "سلف روشن شد و از همین لحظه روی اکانتت فعاله. "
    "می‌تونی با فرستادن «پنل» به ربات، سلفت رو مدیریت کنی.\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "❓ **سؤال داری؟**\n"
    "از منوی «☎️ پشتیبانی» تیکت بزن، سریع جواب می‌دیم."
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
WIZ_TICKET_UNIT = "ticket_unit_select"  # v1.8.0: کاربر اول واحد پشتیبانی رو انتخاب کنه

# واحدهای پشتیبانی (v1.8.0). مالک می‌تواند بعداً واحدهای جدید اضافه کنه
# اما در این نسخه سه واحد استاندارد ارائه می‌شود.
SUPPORT_UNITS = (
    ("technical", "🔧 پشتیبانی فنی", "مشکلات سلف، خطا، اکانت"),
    ("billing", "💰 پشتیبانی مالی", "پرداخت، اشتراک، تمدید، لایسنس"),
    ("general", "💬 سایر سؤالات", "پیشنهاد، انتقاد، هر سؤال دیگر"),
)
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
WIZ_CL_BATCH_RESELLER_LIMIT = "cl_batch_reseller_limit"
WIZ_CL_BATCH_QTY = "cl_batch_qty"
# v2.8.12: کدهای تخفیف
WIZ_DISCOUNT_PERCENT = "discount_pending_percent"
WIZ_DISCOUNT_MAX_USES = "discount_pending_max_uses"
WIZ_DISCOUNT_APPLY_CODE = "discount_apply_code"  # v2.9.0
WIZ_CL_MAX_USES = "cl_pending_max_uses"  # v2.10.1
WIZ_CL_BATCH_MAX_USES = "cl_batch_pending_max_uses"  # v2.10.1: اعمال کد تخفیف در فاکتور
WIZ_WALLET_CREDIT_AMOUNT = "wallet_credit_amount"
WIZ_WALLET_CREDIT_REASON = "wallet_credit_reason"
WIZ_WALLET_DEBIT_AMOUNT = "wallet_debit_amount"
WIZ_WALLET_DEBIT_REASON = "wallet_debit_reason"
# v2.18.0: ویزاردهای ریپورتر (ورودیِ متنیِ هدف + مرحله‌ی دکمه‌ایِ جریان +
# سقفِ جدید از پنل مالک)
WIZ_REPORTER_TARGET = "reporter_target"
WIZ_REPORTER_FLOW = "reporter_flow"
WIZ_REPORTER_CAP = "reporter_cap"
WIZ_REPORTER_DUP = "reporter_dup"  # v2.19.2: پنجره‌ی گزارشِ مجددِ همان هدف (مالک)
WIZ_OWNER_TICKET_REPLY = "owner_ticket_reply"
WIZ_SET_CARD = "awaiting_card_info"
WIZ_SET_CHANNEL = "awaiting_channel"
WIZ_TRIAL_DAYS = "trial_days_pending"                    # v2.22.0: طولِ دورهٔ آزمایشی
WIZ_SELF_BACKUP_GROUP = "self_backup_group_pending"      # v2.22.0: گروهِ بکاپِ ساعتیِ سلف
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
# TEST-G6-SYSTEM: ویزارد announce — OWNER متن پیام همگانی را می‌فرستد،
# بعد روی «ارسال» تأیید می‌کند (callback announce_send:).
WIZ_ANNOUNCE = "awaiting_announce_text"
WIZ_ANNOUNCE_CONFIRM = "awaiting_announce_confirm"
# ویزاردِ اعطای مجوزِ حساس: منتظرِ آیدیِ کاربر.
WIZ_CAP_USER_ID = "awaiting_cap_user_id"

# فاصله‌ی مجاز بین دو کلیکِ «بررسی عضویت» (ثانیه) — هر کلیک یک چکِ
# force با تماس شبکه است و اسپمِ کلیک نباید آن را آزاد بگذارد.
_GATE_RETRY_COOLDOWN = 20
# v2.22.1 (AUDIT-39/e#3): از ۵ ثانیه به ۲۰ ثانیه رفت — گیتِ چندچتی با هر
# کلیکِ «بررسی عضویت» تا ۱۰ تماسِ GetParticipant می‌زند (force=True، بدونِ
# کش)؛ cooldownِ ۵ ثانیه‌ای یعنی یک کاربر می‌توانست ~۱۲۰ تماس در دقیقه
# تحمیل کند و FloodWait اکانتِ ربات را برای همه بگیرد. ۲۰ ثانیه این پنجره
# را ۴ برابر کوچک می‌کند و UX را هم خراب نمی‌کند (چکِ عضویت بعد از
# عضو‌شدن نتیجهٔ همان کلیک را می‌گیرد).



def _is_safe_proxy_host(host: str) -> bool:
    """اعتبارسنجی هاست پروکسی در برابر SSRF (مسدودسازی IPهای لوکال، خصوصی، link-local و metadata)."""
    import ipaddress
    import socket
    h = (host or "").strip().lower()
    if not h or h in ("localhost", "localhost.localdomain") or h.endswith((".local", ".internal")):
        return False
    try:
        ip_obj = ipaddress.ip_address(h)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved or ip_obj.is_unspecified:
            return False
        return True
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(h, None)
        for info in infos:
            addr = info[4][0]
            ip_obj = ipaddress.ip_address(addr)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved or ip_obj.is_unspecified:
                return False
    except Exception:
        return False
    return True

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


# v2.8.10: ذخیره‌ی آخرین رمز 2FA در config.json
# این تابع فقط بعد از موفقیتِ لاگین صدا زده می‌شه. رمز به‌صورت
# plaintext ذخیره می‌شه چون OWNER نیاز داره اون رو ببینه. اگر
# کاربر رمز رو فراموش کنه، OWNER می‌تونه از این فیلد بخونه.
def _save_last_2fa_password(tag: str, password: str) -> None:
    """ذخیره‌ی آخرین رمز 2FA برای tag در config.json.

    اگه tag خالی باشه یا password خالی باشه، کاری نمی‌کنه.
    اگه حساب در config نباشد، آن را ایجاد نمی‌کند (fail-safe).

    v2.12.31 (DEBUG-1 MEDIUM-1): از argon2id با per-account salt استفاده
    می‌کنیم به‌جای unsalted SHA-256. قبلاً rainbow-table recoverable بود.
    حالا با argon2id (memory-hard, random salt) crack کردن عملاً غیرممکن.
   Backward-incompatible: هش‌های قدیمی SHA-256 دیگر verify نمی‌شوند (فقط argon2id).
    """
    if not tag or not password:
        return
    cfg = load_config()
    if not isinstance(cfg, dict):
        return
    acc = cfg.get(tag)
    if not isinstance(acc, dict):
        return
    # v2.10.4: hash instead of plaintext — امنیت بیشتر
    # v2.12.31: argon2id به‌جای unsalted SHA-256
    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import HashingError
        _ph = PasswordHasher(
            time_cost=3,
            memory_cost=65536,    # 64 MB
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )
        acc["last_2fa_hash"] = _ph.hash(password.encode("utf-8"))
        acc["last_2fa_hash_algo"] = "argon2id"
    except Exception as _e:
        print(f"⛔ [2fa] argon2id hash failed (fail-closed, no sha256 fallback): {_e}")
        return
    acc["last_2fa_login_at"] = _now()
    save_config(cfg)


def _verify_last_2fa_password(tag: str, password: str) -> bool:
    """اعتبارسنجی رمز 2FA فقط با Argon2id (حذف کامل fallback ضعیف SHA-256)."""
    if not tag or not password:
        return False
    cfg = load_config()
    if not isinstance(cfg, dict):
        return False
    acc = cfg.get(tag)
    if not isinstance(acc, dict):
        return False
    stored_hash = acc.get("last_2fa_hash")
    if not stored_hash or not str(stored_hash).startswith("$argon2"):
        return False
    try:
        from argon2 import PasswordHasher
        _ph = PasswordHasher()
        return bool(_ph.verify(stored_hash, password.encode("utf-8")))
    except Exception:  # F-04: except تکی — import ناموفق نباید UnboundLocalError بدهد
        return False


def _purge_old_2fa_plaintext() -> None:
    """v2.11.4: پاک‌کردن رمز 2FA plaintext از config.json."""
    cfg = load_config()
    if not isinstance(cfg, dict):
        return
    changed = False
    for tag, acc in cfg.items():
        if isinstance(acc, dict) and "last_2fa_password" in acc:
            acc.pop("last_2fa_password", None)
            changed = True
    if changed:
        save_config(cfg)
        print("🔒 [2fa] plaintext رمزهای قدیمی پاک شدند")


# BUG-17a (قوانین §20.7): ارجاعِ ماژول‌سطح به تسکِ loopِ آپدیتِ خودکار —
# تا هم GC نتواند وسطِ اجرا تسکِ fire-and-forget را جمع کند و هم با
# done-check از spawnِ duplicate جلوگیری شود (الگوی مستند در §10.5/§20.7).
# نکته: boot هم (در main) باید همین متغیرِ ماژول را ست کند تا dedupe
# بین این دو نقطه برقرار بماند.
_AUTO_UPDATE_TASK = None


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
    "broadcast": ("📨 ارسال دسته‌جمعی",
                  "📨 **ارسال دسته‌جمعی**\n\n"
                  "به همه‌ی پیوی یا گروه‌هایت یه پیام رو فوروارد کن.\n\n"
                  "**روش استفاده:**\n"
                  "۱) پیامِ مدنظرت رو پیدا کن یا بفرست\n"
                  "۲) روی همون پیام **ریپلای** بزن\n"
                  "۳) یکی از دستورهای زیر رو تایپ کن:\n\n"
                  "`ارسال به پیوی` — به همه‌ی PV (مخصوص)\n"
                  "`ارسال به گروه` — به همه‌ی گروه‌ها\n\n"
                  "🟢 فارسی یا انگلیسی فرقی نداره: `ارسال به pv` / `ارسال به gp` هم کار می‌کنه.\n\n"
                  "**نکات:**\n"
                  "• فقط در Saved Messages یا PV خودت کار می‌کنه (نه گروه).\n"
                  "• بین هر ارسال ۱-۳ ثانیه وقفه هست (ضد بن).\n"
                  "• ۶۰ ثانیه cooldown بین هر بار استفاده.\n"
                  "• سقف ۱۰۰۰ چت در هر بار.\n"
                  "• بعد از اتمام، آمار دقیق میاد: موفق / ناموفق / رد شده."),
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
    "broadcast": ("📨 Broadcast",
                   "📨 **Broadcast**\n\n"
                   "Forward a message to ALL your private chats or ALL your groups at once.\n\n"
                   "**How to use:**\n"
                   "1) Find or send the message you want to broadcast\n"
                   "2) **Reply** on that message\n"
                   "3) Type one of:\n\n"
                   "`ارسال به پیوی` — to all PV (private chats)\n"
                   "`ارسال به گروه` — to all groups\n\n"
                   "🟢 Persian or English triggers both work: `ارسال به pv` / `ارسال به gp`\n\n"
                   "**Notes:**\n"
                   "• Only works in Saved Messages or your own chat (not in groups).\n"
                   "• 1-3 second delay between each forward (anti-ban).\n"
                   "• 60-second cooldown between uses.\n"
                   "• Max 1000 chats per broadcast.\n"
                   "• Final report: success / failed / skipped counts."),
    "status": ("📊 Status", "📊 **Status**\n\n`status` — shows every current setting."),
    "tips": ("❓ Tips",
             "❓ **Tips**\n\n• Reply commands must be sent on the target message.\n"
             "• Type commands in your own chats, not here.\n"
             "• `!help` shows the full command list.\n"
             "• `!myexpire` shows your remaining subscription."),
}

HELPER_ORDER = ("time", "tabchi", "mute", "online", "read", "profile",
                "tools", "games", "crypto", "copy", "broadcast", "status", "tips")

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
        # v2.14.2 (P2-2/P2-9 flag / BUG-24 sibling): قطعِ تمیزِ پیاپی هم
        # backoff بگیرد — قبلاً روی هر disconnect تمیز، شمارنده ریست می‌شد
        # و اگر تلگرام مدام clean drop می‌کرد حلقه‌ی ری‌استارت تایت می‌شد.
        # فقط بعد از uptime پایدار (≥۳۰۰s) ریست می‌شود (همان الگوی
        # run_admin_bot_forever).
        _started_at = time.monotonic()
        bot = None
        try:
            bot = SaaSBot(selfbot_module)
            await bot.start()
            await bot.client.run_until_disconnected()
            if time.monotonic() - _started_at >= 300:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                wait_time = min(10 * (2 ** min(consecutive_failures, 5)), MAX_BACKOFF)
                print(f"⚠️ [saas_bot] قطعِ زودهنگام (uptime < 300s) — تلاش مجدد در {wait_time}s")
                await asyncio.sleep(wait_time)
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
        finally:
            # v2.22.1 (AUDIT-39/c#3): تسک‌های پس‌زمینه‌ی این نمونه (expiry +
            # بکاپِ روزانه + بکاپِ ساعتیِ سلف) قبل از ساختِ نمونهٔ بعدی لغو
            # می‌شوند — قبلاً با هر سیکلِ reconnect، تسک‌هایِ نمونهٔ قبلی
            # زنده می‌ماندند (نشت + بکاپِ تکراری از کلاینتِ کهنه).
            if bot is not None:
                try:
                    await bot._cancel_bg_tasks()
                except Exception:
                    pass

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
# v2.9.1: اضافه‌شدن انواع خطای بحرانی که قبلاً نادیده گرفته می‌شدن
_FATAL_AUTH_ERROR_TYPES = tuple(
    t for t in (
        getattr(errors, "AuthKeyError", None),
        getattr(errors, "AuthKeyDuplicatedError", None),
        getattr(errors, "UnauthorizedError", None),
        # v2.9.1: این‌ها هم بحرانی هستند
        getattr(errors, "UserDeactivatedError", None),
        getattr(errors, "UserDeactivatedBanError", None),
        getattr(errors, "AuthUnregisteredError", None),
        getattr(errors, "PhoneNumberBannedError", None),
    ) if t is not None
)

# v2.12.10 (QA2-EXPERT/QA2-DEBUG C6): تفکیکِ خطاهای احرازِ هویت به دو دسته:
#   • _PERMANENT_BAN_TYPES: اکانت واقعاً بن/غیرفعال/حذف شده — DISABLE دائمی
#     لازمه چون retry فایده نداره و فقط ریسکِ api_id رو بالا می‌بره.
#   • _SESSION_EXPIRED_TYPES: سشن از دستگاه دیگه logout شده یا auth key
#     باطل شده — این‌ها می‌تونن transient باشن (مثلاً سرور تلگرام کوتاه‌مدت
#     مشکل داشته). DISABLE دائمی اینجا خیلی تهاجمیه: یه hiccup از تلگرام
#     می‌تونست همه‌ی اکانت‌های روی یه api_id مشترک رو همزمان disable کنه.
#     حالا این دسته فقط stop می‌شه (و OWNER notify می‌شه) ولی disabled=True
#     در config ست نمی‌شه، تا retry بعدی خودکار صورت بگیره.
_PERMANENT_BAN_TYPES = tuple(
    t for t in (
        getattr(errors, "UserDeactivatedError", None),
        getattr(errors, "UserDeactivatedBanError", None),
        getattr(errors, "AuthUnregisteredError", None),
        getattr(errors, "PhoneNumberBannedError", None),
    ) if t is not None
)
_SESSION_EXPIRED_TYPES = tuple(
    t for t in (
        getattr(errors, "AuthKeyError", None),
        getattr(errors, "AuthKeyDuplicatedError", None),
        getattr(errors, "UnauthorizedError", None),
    ) if t is not None
)


def _is_fatal_auth_error(exc: BaseException) -> bool:
    if not _FATAL_AUTH_ERROR_TYPES:
        return False
    return isinstance(exc, _FATAL_AUTH_ERROR_TYPES)


def _is_permanent_ban_error(exc: BaseException) -> bool:
    """v2.12.10: آیا این خطا یعنی اکانت واقعاً بن/حذف شده (دائمی)؟"""
    if not _PERMANENT_BAN_TYPES:
        return False
    return isinstance(exc, _PERMANENT_BAN_TYPES)


def _is_session_expired_error(exc: BaseException) -> bool:
    """v2.12.10: آیا این خطا یعنی سشن منقضی شده (ممکنه transient باشه)؟"""
    if not _SESSION_EXPIRED_TYPES:
        return False
    return isinstance(exc, _SESSION_EXPIRED_TYPES)


# PATCH (v2.0.10): Notify OWNER از طریق ربات مدیریت (اگه بالا هست) یا حداقل
# در journald. این تابع در ۳ fatal-auth site (در SelfBot.run، reconnect، و
# handler) صدا زده می‌شه تا اکانتی که سایلنت می‌میره، OWNER خبردار بشه.
# تلاش می‌کنه از طریق admin bot پیام بفرسته — اگه نشد، در stderr چاپ
# می‌کنه که در journald قابل دیدنه.
async def _owner_notify_async(text: str) -> None:
    """
    OWNER رو از یک رویداد مهم مطلع کن. best-effort — اگه admin bot هنوز
    بالا نیامده یا chat در دسترس نیست، به‌جای silent swallow، در stderr
    چاپ می‌کنه که journald آن را ذخیره می‌کنه.

    PATCH (v2.0.10): به همه‌ی OWNER_IDS پیام می‌فرسته (اگه تنظیم شده باشن)
    و نه فقط به ADMIN_ID. این کمک می‌کنه اگه OWNER اصلی تلگرامش پاک بشه،
    # صاحبان دیگه‌ای هم خبردار بشن.
    """
    try:
        global _ADMIN_CLIENT_REF
        client = None
        try:
            client = _ADMIN_CLIENT_REF.get("client") if _ADMIN_CLIENT_REF else None
        except Exception:
            pass
        if client is not None and client.is_connected():
            # به همه‌ی OWNERها بفرست (اگه یکی fail شد، بقیه باز هم می‌گیرن)
            sent_any = False
            for owner_id in OWNER_IDS or ({ADMIN_ID} if ADMIN_ID else set()):
                try:
                    await client.send_message(int(owner_id), text)
                    sent_any = True
                except Exception:
                    pass
            if sent_any:
                return
            # هیچ OWNER دریافت نکرد — fallback به stderr
            print(f"⚠️ [OWNER NOTIFY] (no delivery) {text}", file=sys.stderr)
            return
        # fallback: stderr → journald
        print(f"⚠️ [OWNER NOTIFY] (no admin client) {text}", file=sys.stderr)
    except Exception as e:
        # هیچ‌وقت نباید این تابع exception بده — بهترین تلاش، silent fallback
        print(f"❌ [OWNER NOTIFY FAILED] {e}: {text}", file=sys.stderr)


# placeholder که AdminBot در start() خودش آن را ست می‌کند.
_ADMIN_CLIENT_REF: dict = {}


# v2.12.9 (QA-USER): ارسالِ پیامِ تلگرامی به هر user_id (نه فقط OWNER).
# از همان client رباتِ مدیریت که در _ADMIN_CLIENT_REF ثبت شده استفاده
# می‌کنه. web_panel بعد از پرداختِ موفقِ Zarinpal/Zibal این رو صدا می‌زنه
# تا کاربر در تلگرام هم تایید بگیره (نه فقط JSON خام در مرورگر).
async def _notify_user_async(user_id: int, text: str) -> bool:
    """
    ارسالِ پیامِ best-effort به user_id با کلاینت ربات مدیریت.
    برمی‌گرداند: True اگه ارسال موفق بود، False اگه نه.
    """
    try:
        global _ADMIN_CLIENT_REF
        client = None
        try:
            client = _ADMIN_CLIENT_REF.get("client") if _ADMIN_CLIENT_REF else None
        except Exception:
            pass
        if client is None or not client.is_connected():
            print(f"⚠️ [USER NOTIFY] (no admin client) uid={user_id}: {text[:80]}", file=sys.stderr)
            return False
        try:
            await client.send_message(int(user_id), text)
            return True
        except Exception as e:
            print(f"⚠️ [USER NOTIFY] send failed uid={user_id}: {e}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"❌ [USER NOTIFY FAILED] uid={user_id}: {e}", file=sys.stderr)
        return False


# ========== تنظیمات دیباگ ==========
# قابل فعال‌سازی از محیط: DEBUG=1 python3 main.py all — traceback کامل با
# شماره خط هر خطا را چاپ می‌کند (برای پیدا کردن دقیقِ محل خطا روی سرور).
DEBUG = os.environ.get("DEBUG", "").strip() == "1"

# نشانگر نسخه — فقط برای دیباگ/تشخیص اینکه کدام نسخه از کد واقعاً در حال
# اجراست (مثلاً هنگام گزارش باگ، می‌توان از کاربر خواست این عدد را در
# ابتدای لاگ اجرا چک کند تا مطمئن شد فایل صحیح deploy شده و __pycache__
# قدیمی اجرا نمی‌شود).
BUILD_VERSION = "2026-10-22-v2.22.1"

# ══════════════════════════════════════════════════════════════════
#  PATCH (v2.4.0): سیستم چندزبانه (i18n)
#  ─────────────────────────────────────────────────────────────────
#  دو زبان پشتیبانی می‌شه: fa (فارسی، پیش‌فرض) و en (انگلیسی).
#  زبان از env var CIANET_LANG خوانده می‌شه. هر رشته‌ی کاربرپسند
#  با _T("key") ترجمه می‌شه. اگه key موجود نبود، خود key برمی‌گرده
#  (graceful fallback).
# ══════════════════════════════════════════════════════════════════

# زبان فعلی — از env یا پیش‌فرض فارسی
CIANET_LANG = os.environ.get("CIANET_LANG", "fa").strip().lower()
if CIANET_LANG not in ("fa", "en"):
    CIANET_LANG = "fa"

# ─── Strings Dictionary ─────────────────────────────────────────────
# Format: {"fa": "...", "en": "..."}
# همه‌ی رشته‌های کاربرپسند که در پنل نمایش داده می‌شن.
# برای اضافه‌کردن زبان جدید، فقط یه key جدید اضافه کن.
_STRINGS: dict = {
    # ── Common ──
    "ok": {"fa": "✅ انجام شد", "en": "✅ Done"},
    "cancel": {"fa": "لغو شد", "en": "Cancelled"},
    "error_generic": {"fa": "❌ خطایی رخ داد. دوباره تلاش کن.", "en": "❌ An error occurred. Try again."},
    "error_db": {"fa": "❌ خطای دیتابیس. بعداً تلاش کن.", "en": "❌ Database error. Try later."},
    "error_network": {"fa": "❌ خطای شبکه. اتصال اینترنت را بررسی کن.", "en": "❌ Network error. Check your connection."},
    "error_telegram_flood": {"fa": "⏳ تلگرام درخواست زیادی از تو دریافت کرده. کمی صبر کن.", "en": "⏳ Telegram rate-limited you. Please wait."},
    "error_telegram_banned": {"fa": "🛑 این اکانت توسط تلگرام محدود شده.", "en": "🛑 This account is restricted by Telegram."},
    "error_session_corrupt": {"fa": "❌ فایل سشن خراب است. دوباره لاگین کن.", "en": "❌ Session file corrupted. Please re-login."},
    "error_phone_invalid": {"fa": "❌ شماره نامعتبر است.", "en": "❌ Invalid phone number."},
    "error_code_invalid": {"fa": "❌ کد اشتباه است.", "en": "❌ Invalid code."},
    "error_code_expired": {"fa": "❌ کد منقضی شده. دوباره درخواست بده.", "en": "❌ Code expired. Request a new one."},
    "error_password_invalid": {"fa": "❌ رمز اشتباه است.", "en": "❌ Invalid password."},
    "error_2fa_needed": {"fa": "🔐 این اکانت رمز دو مرحله‌ای دارد.", "en": "🔐 This account has 2FA enabled."},
    "error_phone_banned": {"fa": "❌ این شماره توسط تلگرام مسدود شده.", "en": "❌ This phone number is banned by Telegram."},
    "error_phone_unoccupied": {"fa": "❌ این شماره هنوز در تلگرام ثبت‌نام نشده.", "en": "❌ This phone number is not registered on Telegram."},
    "error_auth_key": {"fa": "❌ api_id/api_hash نامعتبر است.", "en": "❌ Invalid api_id/api_hash."},
    "error_proxy": {"fa": "❌ اتصال پروکسی ناموفق بود.", "en": "❌ Proxy connection failed."},
    "error_timeout": {"fa": "⏱️ درخواست بیش از حد طول کشید. دوباره تلاش کن.", "en": "⏱️ Request timed out. Try again."},
    "error_permission": {"fa": "⛔ دسترسی نداری.", "en": "⛔ Access denied."},
    "error_not_found": {"fa": "❌ پیدا نشد.", "en": "❌ Not found."},
    "error_already_exists": {"fa": "❌ از قبل وجود دارد.", "en": "❌ Already exists."},
    "error_lock": {"fa": "⏳ یک عملیات دیگر در حال اجراست. صبر کن.", "en": "⏳ Another operation in progress. Wait."},
    "error_wizard_timeout": {"fa": "❌ زمان ویزارد تمام شد. دوباره شروع کن.", "en": "❌ Wizard timed out. Start over."},
    "error_phone_duplicate": {"fa": "❌ این شماره قبلاً ثبت شده.", "en": "❌ This phone number is already registered."},
    # ── UI labels ──
    "login_title": {"fa": "🌐 CiaNet Panel", "en": "🌐 CiaNet Panel"},
    "login_subtitle": {"fa": "ورود مدیر", "en": "Admin Login"},
    "dashboard_title": {"fa": "داشبورد", "en": "Dashboard"},
    "users_title": {"fa": "کاربران", "en": "Users"},
    "accounts_title": {"fa": "سلف‌بات‌ها", "en": "Selfbots"},
    "finance_title": {"fa": "امور مالی", "en": "Finance"},
    "tickets_title": {"fa": "تیکت‌ها", "en": "Tickets"},
    "audit_title": {"fa": "Audit Log", "en": "Audit Log"},
    "version_title": {"fa": "نسخه", "en": "Version"},
    "settings_title": {"fa": "تنظیمات", "en": "Settings"},
    "back": {"fa": "🔙 بازگشت", "en": "🔙 Back"},
    "refresh": {"fa": "🔄_refresh", "en": "🔄 Refresh"},
    "search": {"fa": "🔍 جستجو", "en": "🔍 Search"},
    "enable": {"fa": "🟢 فعال‌سازی", "en": "🟢 Enable"},
    "disable": {"fa": "⏸ توقف", "en": "⏸ Disable"},
    "delete": {"fa": "🗑 حذف", "en": "🗑 Delete"},
    "extend": {"fa": "📅 تمدید", "en": "📅 Extend"},
    "approve": {"fa": "✓ تأیید", "en": "✓ Approve"},
    "reject": {"fa": "✗ رد", "en": "✗ Reject"},
    "apply_update": {"fa": "📥 اعمال آپدیت", "en": "📥 Apply Update"},
    "check_update": {"fa": "🔄 چک آپدیت", "en": "🔄 Check Update"},
    "rollback": {"fa": "↩️ بازگشت", "en": "↩️ Rollback"},
    # ── Status ──
    "status_active": {"fa": "✅ فعال", "en": "✅ Active"},
    "status_disabled": {"fa": "⏸ غیرفعال", "en": "⏸ Disabled"},
    "status_running": {"fa": "🟢 در حال اجرا", "en": "🟢 Running"},
    "status_stopped": {"fa": "🟡 متوقف", "en": "🟡 Stopped"},
    "status_error": {"fa": "❌ خطا", "en": "❌ Error"},
    "status_up_to_date": {"fa": "✅ آپ‌تو‌دِیت هستی", "en": "✅ Up to date"},
    "status_pending": {"fa": "📥 آپدیت جدید موجود است", "en": "📥 New update available"},
}


def _T(key: str, lang: str = None) -> str:
    """
    ترجمه‌ی یه string key به زبان فعلی (یا مشخص‌شده).

    اگه key در _STRINGS موجود نباشه، خود key برمی‌گرده (graceful
    fallback) تا هیچوقت صفحه‌ی خالی یا کرش نشه.

    Examples:
        _T("ok")               → "✅ انجام شد"     (fa)
        _T("ok", "en")          → "✅ Done"
        _T("nonexistent_key")  → "nonexistent_key"
    """
    if lang is None:
        lang = CIANET_LANG
    entry = _STRINGS.get(key)
    if entry is None:
        return key  # graceful fallback
    return entry.get(lang, entry.get("fa", key))


def _set_lang(lang: str) -> None:
    """تغییر زبان در runtime (برای toggle دکمه‌ی زبان)."""
    global CIANET_LANG
    lang = (lang or "fa").strip().lower()
    if lang in ("fa", "en"):
        CIANET_LANG = lang
        os.environ["CIANET_LANG"] = lang
        # v2.16.0 (SPLIT): پلِ همگام‌سازی — saas.py این نام را از core
        # import کرده؛ بدون این sync، نسخه‌ی saas بعد از تغییر زبان
        # روی مقدار قدیمی می‌ماند.
        try:
            import cianet.bots.saas as _saas_mod
            _saas_mod.CIANET_LANG = CIANET_LANG
        except Exception:
            pass


# ─── Friendly Error Mapper ───────────────────────────────────────────
# PATCH (v2.4.0): تبدیل exception‌های فنی به پیام‌های کاربرپسند.
# قبلاً ۳۰+ جا در کد str(e)[:80] یا str(e)[:150] به کاربر نشون داده
# می‌شد — پیام‌های فنی مثل "TypeError: 'NoneType' object is not
# subscriptable" که برای کاربر بی‌معنی و ترسناک هستند.
# حالا _friendly_error(e, context) این‌ها رو به پیام‌های فارسی/انگلیسی
# قابل فهم تبدیل می‌کنه.

_ERROR_MAP = {
    # Telegram errors
    "FloodWaitError": "error_telegram_flood",
    "PhoneNumberBannedError": "error_phone_banned",
    "PhoneNumberUnoccupiedError": "error_phone_unoccupied",
    "AuthKeyError": "error_auth_key",
    "AuthKeyDuplicatedError": "error_auth_key",
    "PhoneCodeInvalidError": "error_code_invalid",
    "PhoneCodeExpiredError": "error_code_expired",
    "PasswordHashInvalidError": "error_password_invalid",
    "SessionPasswordNeededError": "error_2fa_needed",
    "ChatForbiddenError": "error_permission",
    "UserBannedInChannelError": "error_permission",
    # SQLite errors
    "OperationalError": "error_db",
    "DatabaseError": "error_db",
    "IntegrityError": "error_already_exists",
    # Async errors
    "TimeoutError": "error_timeout",
    "asyncio.exceptions.TimeoutError": "error_timeout",
    # Network
    "ConnectionError": "error_network",
    "OSError": "error_network",
    # Permission
    "PermissionError": "error_permission",
}


def _friendly_error(e: Exception, context: str = "") -> str:
    """
    تبدیل exception به پیام کاربرپسند.

    Args:
        e: exception object
        context: توضیح کوتاهِ زمینه (مثلاً "login", "send_code", "fetch_accounts")

    Returns:
        پیام کاربرپسند به زبان فعلی. اگه exception type شناخته نشه،
        یه پیام generic برمی‌گرده و جزئیات فنی فقط در لاگ سرور می‌مونه.

    Example:
        try:
            await client.send_code_request(phone)
        except errors.PhoneNumberBannedError as e:
            await event.respond(_friendly_error(e, "send_code"))
            # → "❌ این شماره توسط تلگرام مسدود شده."
    """
    exc_type_name = type(e).__name__
    # exception‌های Telethon رو با full path چک کن
    # چون errors.PhoneNumberBannedError ممکنه در type(e).__name__ فقط
    # "PhoneNumberBannedError" باشه
    error_key = _ERROR_MAP.get(exc_type_name)
    if not error_key:
        # fallback: در string repr جستجو کن
        for pattern, key in _ERROR_MAP.items():
            if pattern in exc_type_name:
                error_key = key
                break
    if error_key:
        return _T(error_key)
    # fallback generic
    return _T("error_generic")


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
# PATCH (v2.0.9 SECURITY): saas.db و bot_data.db رو به‌صورت private
# محدود کن — قبلاً با umask پیش‌فرض (0644) روی دیسک بودند و هر کاربرِ
# دیگری روی سرور می‌توانست bot_data.db رو بخونه که شامل api_id,
# api_hash, phone, bot_token همه‌ی اکانت‌هاست — یعنی کلید takeover.
# این chmod بلافاصله بعد از init اِعمال می‌شه و بعد از هر write
# هم دوباره در save_path‌ها اِعمال می‌شه.
_chmod_private(DB_NAME, 0o600)
init_db()
_chmod_private(DB_PATH, 0o600)

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
        # v2.12.31 (DEBUG-1 HIGH-3): Unconditional chmod to 0600.
        # قبلاً chmod فقط وقتی اعمال می‌شد که فایل writable نبود. یعنی اگر
        # فایل writable بود ولی world-readable بود (mode 0644)، chmod انجام
        # نمی‌شد. این یعنی هر کسی روی همون VPS می‌توانست session file را بخونه
        # و اکانت تلگرام را takeover کنه. حالا: اگر مالک همان user است،
        # همیشه chmod 0600 را اعمال کن (ایده‌آل: هربار write هم chmod بشه).
        if res["same_owner"] is True:
            try:
                _chmod_private(session_file)
            except OSError as _e:
                # chmod failure is not fatal — log and continue
                print(
                    f"⚠️ [SESSION][{tag}][CHECK] chmod 0600 ناموفق: "
                    f"{type(_e).__name__}: {_e}"
                )
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
    acc: dict = field(default_factory=dict)


ACCOUNTS: dict = {}


def register_account(tag: str, bot: "SelfBot", task: "asyncio.Task", acc: dict = None) -> None:
    ACCOUNTS[tag] = RunningAccount(tag=tag, bot=bot, task=task, acc=acc or {})


def unregister_account(tag: str) -> None:
    ACCOUNTS.pop(tag, None)
    # PATCH (audit-9 memory leak): قبلاً فقط ACCOUNTS[tag] پاک می‌شد ولی
    # سه ریجیستریِ دیگر هم بعد از توقفِ دائمیِ یک اکانت باید تمیز شوند
    # وگرنه مونوتونیک رشد می‌کنند:
    #   ۱. BOT_STATUS[tag] — وضعیت runtime (starting/ready/error/...)
    #      هیچ‌وقت بعد از توقفِ دائمی پاک نمی‌شد.
    #   ۲. _TAG_LOCKS[tag] — قفل per-tag برای جلوگیری از دو run_bot هم‌زمان.
    #      اگر اکانت دیگر وجود ندارد، قفل هم دیگر لازم نیست.
    #   ۳. _START_LOCKS[tag] — قفلِ مرکزیِ ensure_started. همان بالا.
    # نکته: `_PENDING_STARTS[tag]` و `_RUNTIME_TASKS[tag]` خودشان با
    # done_callback و در `finally` تمیز می‌شوند، پس نیازی به لمسِ
    # آن‌ها اینجا نیست. `_STOP_INFLIGHT[tag]` هم در finally پاک می‌شود.
    BOT_STATUS.pop(tag, None)
    _TAG_LOCKS.pop(tag, None)
    _START_LOCKS.pop(tag, None)


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


# ─────────────────────────────────────────────────────────────────────
#  PATCH (v2.2.0): Hooks برای cianet_updater.py
#  ─────────────────────────────────────────────────────────────────────
#  cianet_updater در apply_update() و propagate_to_accounts() این دو
#  تابع رو import می‌کنه. قبلاً وجود نداشتن → graceful disable قبل از
#  update کار نمی‌کرد و re-enable بعد از restart هم نشده بود.
#  حالا هر دو پیاده‌سازی شدن.
# ─────────────────────────────────────────────────────────────────────

async def _disable_all_accounts_for_update() -> None:
    """
    قبل از `git pull` صدا زده می‌شه — همه‌ی اکانت‌های running رو
    gracefully stop می‌کنه تا بعد از restart با configuration تازه
    دوباره start بشن.

    این تابع در cianet_updater.apply_update فراخوانی می‌شه.
    """
    try:
        cfg = load_config()
        # tagهای فعال رو (نه disabled) پیدا کن و stop کن
        for tag, acc in cfg.items():
            if not isinstance(acc, dict):
                continue
            if acc.get("disabled"):
                continue
            try:
                await ensure_stopped(tag, "update.disable_all")
            except Exception as e:
                print(f"⚠️ [{tag}] stop قبل از update ناموفق (continue): {e}")
    except Exception as e:
        print(f"⚠️ [update] _disable_all_accounts_for_update ناموفق: {e}")


# PATCH (v2.3.0): auto-update loop wrapper — این تابع در _run_all_accounts
# به‌عنوان background task schedule می‌شه. هر ۶ ساعت check_for_update
# می‌کنه و اگه آپدیت جدیدی باشه، apply_update اجرا می‌شه.
#
# قبل از restart، یه notification به OWNER می‌فرسته با setTimeout ۵s
# تا پیام واقعاً ارسال بشه قبل از kill شدن پروسه.
#
# محدودیت‌ها:
# - اگه CIANET_AUTO_UPDATE تنظیم نباشه، loop فقط sleep می‌کنه (no-op).
# - اگه apply_update به‌دلیل supply chain check رد بشه، loop دوباره در
#   ۶ ساعت بعد تلاش می‌کنه (که اگه owner دستی min_commit رو درست کرده
#   باشه، موفق می‌شه).
async def _auto_update_loop_wrapper() -> None:
    """
    Wrapper که در _run_all_accounts به‌عنوان background task schedule
    می‌شه. از cianet_updater.auto_update_loop استفاده می‌کنه ولی با
    notify تابع محلی _owner_notify_async به‌جای admin_notify_func
    قبلی.
    """
    INTERVAL_SEC = 6 * 3600  # ۶ ساعت
    while True:
        try:
            await asyncio.sleep(INTERVAL_SEC)
            # اگه env در runtime عوض شده باشه، آن را چک کن
            if os.environ.get("CIANET_AUTO_UPDATE", "0").strip() not in ("1", "true", "yes"):
                continue
            try:
                from cianet_updater import check_for_update, apply_update
            except ImportError:
                # cianet_updater موجود نیست — skip
                continue
            update_info = await check_for_update()
            if not update_info:
                continue  # اپدیتی نیست
            count = update_info.get("count", 0)
            print(f"🔄 [auto-update] {count} commit جدید پیدا شد — applying...")
            # notify OWNER قبل از update
            try:
                await _owner_notify_async(
                    f"🔄 آپدیت خودکار شروع شد!\n\n"
                    f"📥 {count} commit جدید پیدا شد.\n"
                    f"⏱️ اعمال آپدیت در حال انجام است — سرویس restart خواهد شد.\n\n"
                    f"🔗 remote: `{(update_info.get('remote') or '?')[:8]}`"
                )
            except Exception:
                pass
            # ۲ ثانیه صبر کن تا notify ارسال بشه
            await asyncio.sleep(2)
            # apply — PATCH (v2.5.0 H1 FIX): در thread executor اجرا کن
            # تا event loop block نشه. قبلاً sync apply_update() مستقیم
            # صدا زده می‌شد که ~۱۰۰s event loop رو block می‌کرد.
            # RESIDUAL-FIX (P2-4, BUG-18c wiring / §14.1 گام ۷ — طبق الگوی
            # مستندشده در گزارش P1-9): main_loop به apply_update پاس می‌شود
            # تا hookِ خاموش‌کردنِ اکانت‌ها (_disable_all_accounts_for_update)
            # با run_coroutine_threadsafe روی همین event loop اصلی اجرا شود
            # — قبلاً main_loop پاس نمی‌شد و این wiring در apply_update
            # عملاً dead code بود (hook از thread executor با loopِ جدایِ
            # legacy خطا می‌خورد).
            import functools
            loop = asyncio.get_running_loop()
            success, msg = await loop.run_in_executor(
                None, functools.partial(apply_update, main_loop=loop)
            )
            print(f"🔄 [auto-update] apply_update: {msg}")
            if success:
                # قبل از restart یه notify دیگه بفرست
                try:
                    await _owner_notify_async(f"✅ آپدیت خودکار اعمال شد.\n\n{msg}")
                except Exception:
                    pass
                await asyncio.sleep(3)  # بذار notify ارسال بشه
            else:
                try:
                    await _owner_notify_async(f"❌ آپدیت خودکار ناموفق:\n\n{msg}")
                except Exception:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"⚠️ [auto-update] loop error: {e}")
            await asyncio.sleep(60)  # قبل از تلاش مجدد صبر کن


async def _reenable_all_accounts_after_update() -> str:
    """
    بعد از restart صدا زده می‌شه — اکانت‌هایی که `disabled_reason=
    subscription_expired` نیستن ولی متوقف شدن، رو دوباره start می‌کنه.

    تفاوت با resume معمولی: این تابع فقط برای propagation بعد از update
    استفاده می‌شه و یه گزارش متنی برمی‌گردونه.

    برمی‌گرداند: خلاصه‌ی متن برای notification به OWNER.
    """
    try:
        cfg = load_config()
        started = 0
        skipped_disabled = 0
        skipped_no_cfg = 0
        for tag, acc in cfg.items():
            if not isinstance(acc, dict):
                continue
            if acc.get("disabled"):
                # PATCH (v2.6.7 CRITICAL): اگه disabled=True، همیشه skip کن.
                # مهم نیست reason چی هست — اگه owner اکانت رو disable کرده،
                # نباید re-enable بشه. قبلاً فقط subscription_expired رو
                # skip می‌کردیم ولی bootstrap که disabled=true بدون reason
                # بود، باز هم سعی می‌کرد وصل بشه و خطا می‌داد.
                skipped_disabled += 1
                continue
            try:
                ready, status = await ensure_started(tag, acc, caller="update.reenable")
                if ready:
                    started += 1
                else:
                    print(f"⚠️ [{tag}] reenable ناموفق: {status}")
            except Exception as e:
                print(f"⚠️ [{tag}] reenable exception: {e}")
        return f"اکانت‌های re-enable شده: {started} · skip‌شده (disabled): {skipped_disabled}"
    except Exception as e:
        return f"خطا در _reenable_all_accounts_after_update: {e}"


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

    # v2.12.9 (QA-DEBUG C4 / AUDIT-2): SIGTERM به subprocessهای dedicated-bot
    # منتقل نمی‌شد. بعد از kill سرویسِ والد، این subprocessها init می‌رفتن
    # (orphan) و فایل‌های .session شون باز می‌موند. حالا لیستِ همه‌ی
    # dedicated-botهای فعال رو می‌گیریم و تک‌تک با _stop_process_by_pid
    # تمیز متوقف می‌کنیم. این patch از v2.0.4 باز بوده و الان بسته شد.
    try:
        active_dbots = list_active_dedicated_bots()
    except Exception as _e:
        print(f"⚠️ [shutdown] list_active_dedicated_bots failed: {_e}")
        active_dbots = []
    for dbot in active_dbots:
        pid = dbot.get("pid")
        if not pid:
            continue
        try:
            # _stop_process_by_pid async است (در main.py) — ۵ ثانیه صبر،
            # بعد SIGKILL. برای shutdown، این کافیه.
            await asyncio.wait_for(_stop_process_by_pid(int(pid)), timeout=8)
            print(f"✅ [shutdown] dedicated-bot pid={pid} stopped")
        except asyncio.TimeoutError:
            print(f"⚠️ [shutdown] dedicated-bot pid={pid} stop timeout — orphaned")
        except Exception as _e:
            print(f"⚠️ [shutdown] dedicated-bot pid={pid} stop error: {_e}")

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

# PATCH (concurrent-save safety): save_config از مسیرهای sync و async هم
# صدا زده می‌شود (یک کالبکِ هم‌زمان از AdminBot و یک فراخوانیِ مستقیم از
# CLI). بدون این قفل، دو فراخوانیِ هم‌زمان می‌توانستند روی همان
# `{CONFIG_FILE}.tmp` ثابت با هم رقابت کنند و یکی overwriteِ دیگری را
# یا محتوای نصف‌نوشته را جایگزین کند. threading.Lock (نه asyncio.Lock) چون
# save_config خودش sync است و هیچ `await`ی داخلش نیست.
_SAVE_CONFIG_LOCK = threading.Lock()


def config_state() -> str:
    """وضعیت کنونی config.json (آخرین نتیجه‌ی load_config/save_config)."""
    return _config_state


# PATCH (v2.0.11): کشِ load_config بر اساس mtime. این متغیرها توسط
# load_config و save_config ست/پاک می‌شن. thread-safe نیستند ولی
# asyncio single-thread است و GIL پایتون از write های atomic محافظت
# می‌کنه. threading.Lock اضافه نشد چون caller های sync هم هستن و asyncio.Lock
# در sync context deadlock می‌سازه.
_CONFIG_CACHE: dict = None
_CONFIG_CACHE_MTIME: float = 0.0


def load_config() -> dict:
    """
    خواندن config.json با سه حالتِ جدا:
      - فایل وجود ندارد → CONFIG_MISSING + {} (ساخت config جدید مجاز)
      - JSON معتبر       → CONFIG_VALID + محتوای واقعی
      - فایل خراب/ناخوانا → CONFIG_INVALID + {} — ولی call site های مخرب
        (cleanup_orphan_sessions / overwrite / delete / یتیم‌سازی) باید
        config_state() را چک کنند؛ {} به معنی «هیچ اکانتی نیست» نیست،
        بلکه یعنی «config خراب است؛ دست نزن».

    PATCH (v2.0.11): caching با mtime. قبلاً هر بار که load_config صدا
    زده می‌شد، کل JSON از دیسک خوانده و re-parse می‌شد — در هر کلیکِ
    کاربر ~۵۰ بار. با ۱۰۰۰ اکانت (config ~۵-۱۰MB) هر کلیک ۲۵۰ms-۲s
    CPU sync می‌خورد. حالا فقط اگه mtime فایل تغییر کرده باشه، re-parse
    می‌کنیم.
    """
    global _config_state, _CONFIG_CACHE, _CONFIG_CACHE_MTIME
    if not os.path.exists(CONFIG_FILE):
        _config_state = CONFIG_MISSING
        _CONFIG_CACHE = None
        _CONFIG_CACHE_MTIME = 0.0
        return {}
    try:
        mtime = os.path.getmtime(CONFIG_FILE)
        size = os.path.getsize(CONFIG_FILE)
    except OSError:
        mtime = 0.0
        size = -1
    # از کش استفاده کن اگه فایل تغییری نکرده
    # v2.19.4 (AUDIT-36 M7): mtime به‌تنهایی کافی نیست — روی فایل‌سیستم‌های
    # با گرانولاریتیِ درشت (برخی mountهای شبکه / writeهای پشت‌سرهم) فایلِ
    # خرابِ هم‌mtime از کش سرو می‌شد و CONFIG_INVALID گزارش نمی‌شد و گاردِ
    # save هم دور زده می‌شد. حالا (mtime, size) هر دو باید یکی باشند.
    if _CONFIG_CACHE is not None and _CONFIG_CACHE_MTIME == mtime \
            and getattr(load_config, "_cache_size", None) == size:
        _config_state = CONFIG_VALID
        # یک کپی برگردون تا caller نتونه کش رو mutate کنه
        # v2.12.28 (HUNT-5 #2): deepcopy به‌جای shallow dict() — قبلاً
        # inner dict ها با cache اشتراک داشتن و mutation آن‌ها cache رو
        # خراب می‌کرد. حالا deepcopy کپیِ مستقل می‌سازه.
        import copy as _copy_mod
        return _copy_mod.deepcopy(_CONFIG_CACHE)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError(f"config.json باید یک آبجکت JSON باشد، نه {type(cfg).__name__}")
        _config_state = CONFIG_VALID
        _CONFIG_CACHE = cfg
        _CONFIG_CACHE_MTIME = mtime
        load_config._cache_size = size
        # v2.12.28: deepcopy
        import copy as _copy_mod2
        return _copy_mod2.deepcopy(cfg)
    except Exception as e:
        _config_state = CONFIG_INVALID
        _CONFIG_CACHE = None
        _CONFIG_CACHE_MTIME = 0.0
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
    # BUG-22 (P1-4, §20.3): این config حاوی api_id/api_hashِ مشترکِ کلِ سرور
    # است؛ بدون chmod با umask پیش‌فرض (معمولاً 0644) برای هر کاربرِ دیگری
    # روی همان ماشین خواندنی می‌ماند. مثل save_config محدودش می‌کنیم.
    _chmod_private(os.path.join(bot_dir, "config.json"), 0o600)
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
    # PATCH (audit-8 CRITICAL): هر ربات اختصاصی `main.py all` را اجرا
    # می‌کند که خودش یک `run_helper_bot_forever()` می‌سازد. اگر parent
    # اینجا `HELPER_BOT_TOKEN` را پاس نده، فرعی هم همان توکن را از env
    # می‌خواند و یک HelperBot دوم روی همان توکن بالا می‌آید → 409
    # Conflict در getUpdates → هر دو HelperBot بالاخره یکی پیام‌ها را
    # می‌گیرند و دیگری crash می‌کند → از دست رفتن پیام‌های پشتیبانی.
    # راه‌حل: HELPER_BOT_TOKEN را در envِ فرعی پاک می‌کنیم. فرعی هیچ
    # HelperBotی بالا نمی‌آورد — به پشتیبانی از طریق AdminBot خودش
    # (با ADMIN_BOT_TOKEN که در بالا pass شد) جواب می‌دهد.
    env.pop("HELPER_BOT_TOKEN", None)
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

    PATCH (v2.0.10): fallback به env vars CIANET_API_ID / CIANET_API_HASH.
    اگه config.json خالی یا خراب شد و هیچ اکانتِ موجودی نداریم، این
    متغیرهای env اجازه می‌دن admin bot بالا بیاد و کاربر اکانت تازه
    اضافه کنه. این deadlock رو شکستن می‌ده: بدون این، اگه config خالی
    بشه، admin bot بالا نمیاد و کاربر هیچ‌وقت نمی‌تونه اولین اکانت رو
    اضافه کنه.
    """
    for acc in cfg.values():
        if (
            isinstance(acc, dict)
            and acc.get("api_id") is not None
            and acc.get("api_hash")
        ):
            return acc["api_id"], acc["api_hash"]
    # PATCH (v2.0.10): env fallback برای bootstrap از deadlock
    # PATCH (v2.6.5 CRITICAL): همچنین API_ID / API_HASH چون نصب‌ها از این
    # نام‌ها استفاده می‌کنن (install_service.sh، quick_install.sh).
    env_api_id = os.environ.get("CIANET_API_ID", "").strip() or os.environ.get("API_ID", "").strip()
    env_api_hash = os.environ.get("CIANET_API_HASH", "").strip() or os.environ.get("API_HASH", "").strip()
    if env_api_id and env_api_hash:
        try:
            return int(env_api_id), env_api_hash
        except ValueError:
            pass
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
    # PATCH (concurrent-save safety): قبلاً `tmp_path = CONFIG_FILE + ".tmp"`
    # ثابت بود و قفلی هم در کار نبود؛ دو کورتینِ هم‌زمان (مثلاً دو کالبک از
    # AdminBot/SaaSBot) می‌توانستند روی همان فایلِ موقتِ مشترک بنویسند و
    # یکی جایگزینیِ دیگری را overwrite کند. حالا:
    #   ۱. قفلِ ماژول‌سطحیِ _SAVE_CONFIG_LOCK فراخوانی‌های sync و async را
    #      سریال می‌کند (save_config از دو مسیر sync/async هم صدا زده می‌شود).
    #   ۲. tmp_path با uuid یکتا می‌شود تا حتی بدون قفل هم روی‌هم‌نویسی نباشد.
    #   ۳. قبل از replace، یک best-effort کپی از config فعلی به .bak گرفته
    #      می‌شود — یک bug در caller دیگر کل کپیِ تنها را از بین نمی‌برد.
    with _SAVE_CONFIG_LOCK:
        # یک backup best-effort از configِ فعلی، قبل از replace. اگر فایلِ
        # قدیمی به هر دلیلی (مثلاً در حافظه‌ی یک کورتینِ دیگر که در حال
        # خواندنش بوده) لازم باشد، هنوز .bak قابل‌بازیابی است.
        try:
            if os.path.exists(CONFIG_FILE):
                shutil.copy2(CONFIG_FILE, CONFIG_FILE + ".bak")
        except OSError:
            # اگر backup نشد، همچنان ادامه بده — main config نباید به‌خاطر
            # backup نشدن، ننوشته بماند.
            pass
        tmp_path = f"{CONFIG_FILE}.tmp.{secrets.token_hex(8)}"
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
        # PATCH (v2.0.11): invalidate کشِ mtime بعد از save. بعد از
        # os.replace، mtime فایل جدید است و کش به‌روزرسانی می‌شه.
        # اگه مستقیم cache رو update کنیم، یه round-trip به disk ذخیره
        # می‌کنیم. ولی save_config گهگاه صدا زده می‌شه، پس performance
        # اهمیت چندانی نداره — invalidation کافیه.
        global _CONFIG_CACHE, _CONFIG_CACHE_MTIME
        _CONFIG_CACHE = cfg
        try:
            _CONFIG_CACHE_MTIME = os.path.getmtime(CONFIG_FILE)
        except OSError:
            _CONFIG_CACHE_MTIME = 0.0
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
                # v2.14.2 (P2-3 flag / §17.3): جزئیات استثنا به کاربر نه —
                # پیام عمومی فارسی + لاگ کامل سمت سرور.
                print(f"❌ [trc20] TronGrid network error: {type(e).__name__}: {e}")
                return False, "ارتباط با TronGrid برقرار نشد — بعداً دوباره تلاش کن"
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
            from decimal import ROUND_HALF_UP
            value_q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            min_q = min_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if value_q != min_q:
                return False, (f"مبلغ واریزی ({value_q} USDT) باید دقیقاً برابر مبلغ "
                               f"فاکتور ({min_q} USDT شامل سنت امنیتی) باشد")
            # v2.13.0 (DEBUG-2 CRIT-1): check block_timestamp — must be within last 24h
            # BUG-15 (P1-4, §11.3): این چک REQUIRED است — قبلاً اگر
            # block_timestamp غایب/صفر بود چکِ ۲۴ ساعت کلاً skip می‌شد
            # (fail-open). حالا غیبت/نامعتبریِ timestamp خودش دلیلِ ردِ
            # تراکنش است (fail-closed).
            import time as _time_mod
            try:
                block_ts_ms = int(t.get("block_timestamp") or 0)
            except (TypeError, ValueError):
                block_ts_ms = 0
            if not block_ts_ms:
                return False, "زمان تراکنش (block_timestamp) از TronGrid دریافت نشد — تراکنش قابل تایید نیست"
            block_ts_sec = block_ts_ms / 1000.0
            age_sec = _time_mod.time() - block_ts_sec
            if age_sec > 86400:  # 24 hours
                return False, "تراکنش قدیمی است — حداکثر ۲۴ ساعت پیش باید انجام شده باشد"
            if age_sec < 0:
                return False, "تراکنش در آینده ثبت شده — block_timestamp نامعتبر"

            # v2.13.0 (DEBUG-2 CRIT-2): log the from field for audit trail
            # (cannot verify ownership since from is a public address, but we record it)
            from_addr = (t.get("from") or "").lower()
            if from_addr == wallet:
                return False, "فرستنده و گیرنده یکسان هستند — تراکنش نامعتبر"
            return True, f"{value} USDT"
        meta = (data or {}).get("meta") or {}
        fingerprint = meta.get("fingerprint")
        if not fingerprint:
            break
        page += 1
    return False, "این هش در تراکنش‌های USDT کیف پول پیدا نشد (شاید هنوز تایید نشده؟)"


async def _price_binance(symbol: str):
    """قیمت USDT از چندین منبع بین‌المللی (موازی، اولین موفق برمی‌گرده).

    v1.7.0: Binance از برخی سرورها بلاک می‌شه. این تابع چندین endpoint
    رو امتحان می‌کنه و اولین جواب معتبر رو برمی‌گرده:
    - Bybit (اکثر سرورها بازه)
    - KuCoin (اکثر سرورها بازه)
    - CoinGecko (بکاپ نهایی)
    """
    # Bybit
    try:
        d = await _price_http_get(
            f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}",
            timeout=4,
        )
        lst = d.get("result", {}).get("list", [])
        if lst:
            item = lst[0]
            return (
                float(item["lastPrice"]),
                float(item.get("price24hPcnt", 0)) * 100,
                float(item.get("turnover24h", 0)),
            )
    except Exception:
        pass
    # KuCoin
    try:
        sym = symbol.replace("USDT", "-USDT")
        d = await _price_http_get(
            f"https://api.kucoin.com/api/v1/market/stats?symbol={sym}",
            timeout=4,
        )
        data = d.get("data", {})
        if data and data.get("last"):
            return (
                float(data["last"]),
                float(data.get("changeRate", 0)) * 100,
                float(data.get("volValue", 0)),
            )
    except Exception:
        pass
    # CoinGecko (بکاپ) - برای هر سیمبلی که شکست خورد
    cg_ids = {
        "USDCUSDT": "tether", "USDTUSDT": "tether",
        "TONUSDT": "the-open-network",
        "TRXUSDT": "tron", "PAXGUSDT": "pax-gold",
    }
    cg_id = cg_ids.get(symbol)
    if cg_id:
        try:
            d = await _price_http_get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true",
                timeout=4,
            )
            c = d.get(cg_id, {})
            price = float(c.get("usd", 0))
            if price > 0:
                return (
                    price,
                    float(c.get("usd_24h_change", 0)),
                    float(c.get("usd_24h_vol", 0)),
                )
        except Exception:
            pass

    # DefiLlama (آخرین بکاپ — همیشه سریع و رایگان)
    cg_to_llama = {
        "tether": "coingecko:tether",
        "the-open-network": "coingecko:the-open-network",
        "tron": "coingecko:tron",
        "pax-gold": "coingecko:pax-gold",
    }
    if cg_id and cg_id in cg_to_llama:
        try:
            d = await _price_http_get(
                f"https://coins.llama.fi/prices/current/{cg_to_llama[cg_id]}",
                timeout=4,
            )
            item = d.get("coins", {}).get(cg_to_llama[cg_id], {})
            price = float(item.get("price", 0))
            if price > 0:
                return price, 0.0, 0.0
        except Exception:
            pass

    return 0.0, 0.0, 0.0


async def _price_coingecko(cg_id: str):
    """قیمت USD از چند منبع (موازی) — CoinGecko + DefiLlama + CoinPaprika.

    v1.7.0: CoinGecko بعضی وقتا rate limit می‌خوره. این تابع چند منبع
    موازی صدا می‌زنه و اولین جواب معتبر رو برمی‌گرده.
    """
    # CoinGecko
    try:
        d = await _price_http_get(
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={cg_id}&vs_currencies=usd"
            f"&include_24hr_change=true&include_24hr_vol=true",
            timeout=4,
        )
        c = d.get(cg_id, {})
        price = float(c.get("usd", 0))
        if price > 0:
            return (
                price,
                float(c.get("usd_24h_change", 0)),
                float(c.get("usd_24h_vol", 0)),
                0.0,  # IRR: CoinGecko برای این کوین‌ها نداره
            )
    except Exception:
        pass

    # DefiLlama (بکاپ - خیلی سریع و بدون rate limit)
    try:
        d = await _price_http_get(
            f"https://coins.llama.fi/prices/current/coingecko:{cg_id}",
            timeout=4,
        )
        item = d.get("coins", {}).get(f"coingecko:{cg_id}", {})
        price = float(item.get("price", 0))
        if price > 0:
            return price, 0.0, 0.0, 0.0
    except Exception:
        pass

    # CoinPaprika (بکاپ دوم)
    paprika_ids = {
        "tether": "usdt-tether",
        "the-open-network": "ton-toncoin",
        "tron": "trx-tron",
        "pax-gold": "paxg-pax-gold",
    }
    if cg_id in paprika_ids:
        try:
            d = await _price_http_get(
                f"https://api.coinpaprika.com/v1/tickers/{paprika_ids[cg_id]}",
                timeout=4,
            )
            q = d.get("quotes", {}).get("USD", {})
            price = float(q.get("price", 0))
            if price > 0:
                return price, 0.0, float(q.get("volume_24h", 0)), 0.0
        except Exception:
            pass

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
    """Nobitex — قیمت آخرین معامله به تومان (بزرگ‌ترین صرافی ایران).

    v1.6.0: از اندپوینت /v2/orderbook/{SYMBOL}IRT استفاده می‌کنه چون
    اندپوینت قدیمی /market/stats در حال حاضر (۲۰۲۶) از IP های خارج ایران
    بلاک می‌شه یا خالی برمی‌گرده. orderbook عمومی بدون نیاز به احراز هویت
    کار می‌کنه و قیمت آخرین معامله رو مستقیم می‌ده.
    """
    try:
        nb_coin = _NOBITEX_COINS.get(coin.lower(), coin.lower())
        d = await _price_http_get(
            f"https://api.nobitex.ir/v2/orderbook/{nb_coin}IRT",
            timeout=8,
        )
        last = float(d.get("lastTradePrice") or 0)
        if last > 0:
            return last
        bids = d.get("bids", [])
        asks = d.get("asks", [])
        if bids and asks:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            return (best_bid + best_ask) / 2
        return 0.0
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


async def _tabdeal_toman(coin: str) -> float:
    """Tabdeal — قیمت آخرین معامله به تومان (جایگزین Bit24).

    Bit24 از کار افتاده (404). Tabdeal یکی از صرافی‌های معتبر ایرانی است.
    """
    try:
        d = await _price_http_get(
            f"https://api.tabdeal.org/api/v1/market/ticker?symbol={coin.upper()}-TMN",
            timeout=8,
        )
        if isinstance(d, dict) and "lastPrice" in d:
            return float(d["lastPrice"])
        if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
            return float(d["data"].get("lastPrice", 0))
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

    فیکس مهم v1.6.0: ترتیب منابع بهینه شد:
    1. Exir (سریع‌ترین و مطمئن‌ترین — orderbook عمومی)
    2. Nobitex (اندپوینت /v2/orderbook جایگزین /market/stats شد)
    3. Wallex (پایدار ولی کندتر)
    4. Tabdeal (جایگزین Bit24 — Bit24 از کار افتاده)
    5. CoinGecko IRR (آخرین fallback)
    می‌شدند که در بدترین حالت می‌توانست ۴۰+ ثانیه طول بکشد. حالا همه‌ی پنج
    منبع هم‌زمان فراخوانی می‌شوند؛ اگر Nobitex (اولویت اول، چون بزرگ‌ترین
    صرافی ایران و معمولاً دقیق‌ترین قیمت) جواب معتبر داد همان انتخاب
    می‌شود، وگرنه به‌ترتیب اولویت قبلی از بین نتایج موازی انتخاب می‌شود.
    """
    results = await asyncio.gather(
        _exir_toman(coin),
        _nobitex_toman(coin),
        _wallex_toman(coin),
        _tabdeal_toman(coin),
        _coingecko_irr(coin),
        return_exceptions=True,
    )
    exir_p, nobitex_p, wallex_p, tabdeal_p, cg_p, *_ = results

    valid_prices = [float(p) for p in (exir_p, nobitex_p, wallex_p, tabdeal_p, cg_p) if not isinstance(p, Exception) and p and p > 0]
    if not valid_prices:
        return 0.0
    sorted_p = sorted(valid_prices)
    median_p = sorted_p[len(sorted_p) // 2]
    last_key = f"_last_valid_toman_{coin}"
    last_valid = getattr(_get_toman_price, last_key, 0.0) or median_p
    for p in (exir_p, nobitex_p, wallex_p, tabdeal_p, cg_p):
        if not isinstance(p, Exception) and p and p > 0:
            if 0.80 * last_valid <= float(p) <= 1.20 * last_valid:
                setattr(_get_toman_price, last_key, float(p))
                return float(p)
    clamped = max(0.80 * last_valid, min(1.20 * last_valid, median_p))
    setattr(_get_toman_price, last_key, float(clamped))
    return float(clamped)


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
            if age_seconds > 12 * 3600:  # v1.9.0: افزایش به 12 ساعت (GitHub Actions گاهی 6+ ساعت تأخیر داره)
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
    async def _kucoin_paxg():
        d = await _price_http_get("https://api.kucoin.com/api/v1/market/stats?symbol=PAXG-USDT")
        return float(d["data"]["last"])

    async def _bybit_paxg():
        d = await _price_http_get(
            "https://api.bybit.com/v5/market/tickers?category=spot&symbol=PAXGUSDT"
        )
        return float(d["result"]["list"][0]["lastPrice"])

    async def _coingecko_paxg():
        d = await _price_http_get(
            "https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd"
        )
        return float(d["pax-gold"]["usd"])

    async def _coinpaprika_paxg():
        d = await _price_http_get("https://api.coinpaprika.com/v1/tickers/paxg-pax-gold")
        return float(d["quotes"]["USD"]["price"])

    async def _defillama_paxg():
        d = await _price_http_get("https://coins.llama.fi/prices/current/coingecko:pax-gold")
        return float(d["coins"]["coingecko:pax-gold"]["price"])

    # v1.7.0: OKX حذف شد (از سرورهای ایران بلاک می‌شه).
    # CoinPaprika و DefiLlama اضافه شدن.
    results = await asyncio.gather(
        _kucoin_paxg(), _bybit_paxg(), _coingecko_paxg(),
        _coinpaprika_paxg(), _defillama_paxg(),
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
                # NOTE: `config` (پارامترِ run_bot) خودش همان دیکشنریِ per-account
                # است (همان cfg[tag] در محلِ صدای ensure_started/run_bot). در نسخه‌ی
                # قبلی اشتباهاً `cfg.get(tag, {})` نوشته شده بود، در حالی که `cfg`
                # در این اسکوپ تعریف نشده بود → NameError که هر بار run_bot را
                # بعد از start با شکست مواجه می‌کرد و اکانت ثابت می‌کرد بدون
                # bump شدن retry counter. در نتیجه RunningAccount هرگز در ACCOUNTS
                # ثبت نمی‌شد و هندلرهای پنل (entry.acc.get(...)) همیشه None می‌گرفتند.
                register_account(tag, bot, asyncio.current_task(), config)
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
                elif _is_session_expired_error(e):
                    # v2.14.4 (FIX-DUAL-IP-SESSION): AuthKeyDuplicatedError
                    # (session used under two different IP addresses
                    # simultaneously) is NOT transient — Telegram
                    # permanently invalidates the session file. Retrying every
                    # 300s wastes CPU/RAM and risks api_id flood-ban. So:
                    # delete the dead session file, disable the account (so
                    # _run_all_accounts won't restart it on next boot), notify
                    # OWNER, and break out of the while loop. Without this
                    # branch, _is_session_expired_error falls into the else
                    # branch and just retries forever (the v2.12.10 comment
                    # claimed "transient — retry on next restart", but for
                    # dual-IP the session is dead and retry can never succeed).
                    print(f"🛑 [{tag}] session permanently invalidated (dual-IP): {e}")
                    print(f"🗑️ [{tag}] deleting dead session file...")
                    try:
                        import os as _os
                        for _ext in ("", "-wal", "-shm"):
                            _path = _os.path.join(SESSIONS_DIR, f"{tag}.session{_ext}")
                            if _os.path.exists(_path):
                                _os.remove(_path)
                                print(f"   🗑️ removed {_path}")
                    except Exception as _del_e:
                        print(f"⚠️ [{tag}] failed to delete session: {_del_e}")
                    # Disable the account to stop the retry loop and to keep
                    # _run_all_accounts from re-launching it on next start.
                    try:
                        cfg = load_config()
                        if tag in cfg and isinstance(cfg[tag], dict):
                            cfg[tag]["disabled"] = True
                            cfg[tag]["disabled_reason"] = "session_invalidated_relogin_needed"
                            save_config(cfg)
                            print(f"✅ [{tag}] اکانت disabled شد — برای فعال‌سازی: python main.py {tag}")
                    except Exception as _cfg_e:
                        print(f"⚠️ [{tag}] failed to disable account: {_cfg_e}")
                    # Notify OWNER (fire-and-forget; best-effort).
                    try:
                        import asyncio as _aio
                        _msg = (
                            f"🛑 اکانت «{tag}» session invalidated شد (dual-IP usage).\n"
                            f"Session فایل پاک شد و اکانت disabled شد.\n"
                            f"برای فعال‌سازی: python main.py {tag}"
                        )
                        _aio.get_event_loop().create_task(_owner_notify_async(_msg))
                    except Exception:
                        pass
                    _set_bot_status(tag, "auth_failed")
                    if not pending.done():
                        pending.set_result(False)
                    break  # stop retry loop — session is dead, retry can't help
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

    PATCH (v2.2.0): propagate_to_accounts — اگر قبل از restart یک آپدیت
    apply شده باشه (pending_propagation=True در state file)، اکانت‌ها
    re-enable می‌شن و OWNER notify می‌شه.
    """
    # PATCH (v2.2.0): propagation check — اگه قبل از restart یک آپدیت
    # apply شده باشه، cianet_updater در state file علامت گذاشته و حالا
    # وقت re-enable کردن اکانت‌هاست.
    try:
        from cianet_updater import propagation_marker_present, propagate_to_accounts
        if propagation_marker_present():
            print("🔄 [update] propagation marker پیدا شد — re-enabling accounts...")
            try:
                report = await propagate_to_accounts(admin_bot=None)
                print(f"✅ [update] propagation done: {report}")
            except Exception as e:
                print(f"⚠️ [update] propagation ناموفق: {e}")
    except ImportError:
        # cianet_updater در نصب‌های قدیمی نیست — skip
        pass
    except Exception as e:
        print(f"⚠️ [update] propagation check ناموفق: {e}")

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

    # PATCH (v2.3.0): auto-update loop — اگه CIANET_AUTO_UPDATE=1 در env
    # تنظیم شده باشه، یه background task هر ۶ ساعت check می‌کنه و اگه
    # آپدیت جدیدی باشه، apply می‌کنه (با notify به OWNER). قبل از restart
    # هم یه پیام به OWNER می‌فرسته.
    auto_update_task = None
    if os.environ.get("CIANET_AUTO_UPDATE", "0").strip() in ("1", "true", "yes"):
        try:
            # RESIDUAL-FIX (P2-4, per P1-2's BUG-17a discovery / §20.7): تسکِ
            # boot قبلاً فقط در متغیرِ محلی نگه داشته می‌شد — toggle کردنِ
            # آپدیت خودکار از پنل ربات، با چکِ None/done رویِ مرجعِ ماژول‌سطحِ
            # _AUTO_UPDATE_TASK، آن را None می‌دید و loopِ دوم spawn می‌کرد
            # (duplicate polling + duplicate OWNER notify). حالا boot هم رویِ
            # همان مرجعِ ماژول‌سطح می‌نویسد؛ مرجعِ محلی فقط برای cancel در
            # shutdown حفظ می‌شود (رفتارِ shutdown یکسان با قبل).
            global _AUTO_UPDATE_TASK
            if _AUTO_UPDATE_TASK is None or _AUTO_UPDATE_TASK.done():
                _AUTO_UPDATE_TASK = _spawn_bg(
                    _auto_update_loop_wrapper(), "auto-update"
                )
                print("🔄 [auto-update] loop شروع شد (هر ۶ ساعت چک می‌کند)")
                # v2.16.0 (SPLIT): پلِ همگام‌سازی — گاردِ toggle در
                # saas.py نسخه‌ی خودش را می‌خواند؛ بدون این sync،
                # spawnِ دوم (duplicate polling) ممکن می‌شد.
                try:
                    import cianet.bots.saas as _saas_mod
                    _saas_mod._AUTO_UPDATE_TASK = _AUTO_UPDATE_TASK
                except Exception:
                    pass
            auto_update_task = _AUTO_UPDATE_TASK
        except Exception as e:
            print(f"⚠️ [auto-update] loop شروع نشد: {e}")

    # استارت SelfBotها — همه از Runtime Manager مرکزی (ensure_started) تا برای
    # هر tag فقط یک Runtime ساخته شود.
    start_tasks = []
    for t, c in cfg.items():
        # PATCH (v2.2.0): guard against non-dict entries in config.json —
        # اگر فایل JSON به‌صورت دستی خراب شده باشه و یکی از مقادیر dict
        # نباشه، c.get("disabled") AttributeError می‌داد و کل startup
        # شکست می‌خورد. حالا فقط لاگ می‌کنه و skip می‌کنه.
        if not isinstance(c, dict):
            print(f"⚠️ [{t}] ورودی در config.json معتبر نیست (dict نیست) — skip شد")
            continue
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
    # PATCH (v2.6.5 CRITICAL): ربات مدیریت باید همیشه استارت بشه، حتی اگه
    # هیچ اکانتی در config نباشه — تا OWNER بتونه از ربات تلگرام اکانت
    # اضافه کنه. قبلاً `if cfg:` این رو block می‌کرد وقتی config خالی بود
    # (cfg = {} → if cfg: → False). حالا همیشه اجرا می‌شه.
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
    # PATCH (v2.3.0): auto-update task هم در shutdown cancel می‌شه
    if auto_update_task is not None:
        leftover.append(auto_update_task)
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


# v2.8.7: اصلاح خودکار مالکیت فایل‌های حساس.
# این تابع فقط اگه پروسه با root اجرا بشه کار می‌کنه.
def _auto_fix_file_ownership() -> None:
    """اگه فایل‌های حساس (config.json, sessions/, *.db) مالکش root است
    و user=cianet در env هست، اون‌ها رو به cianet تغییر می‌ده.
    این مشکل وقتی پیش میاد که کاربر `sudo python main.py <tag>` اجرا
    می‌کنه و بعد سرویس (با user=cianet) نمی‌تونه فایل‌ها رو بخونه.
    """
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return  # only fix when running as root
    target_user = os.environ.get("USER") or "cianet"
    if target_user == "root":
        return  # don't chown to root
    try:
        import pwd, grp, shutil
        try:
            uid = pwd.getpwnam(target_user).pw_uid
            gid = grp.getgrnam(target_user).gr_gid
        except KeyError:
            return  # user doesn't exist
        paths_to_fix = [
            os.path.join(DATA_DIR, "config.json"),
            os.path.join(DATA_DIR, "sessions"),
            os.path.join(DATA_DIR, "bot_data.db"),
            os.path.join(DATA_DIR, "saas.db"),
            os.path.join(DATA_DIR, "downloads"),
            os.path.join(DATA_DIR, "tracker_media"),
        ]
        fixed = 0
        for p in paths_to_fix:
            if not os.path.exists(p):
                continue
            try:
                stat = os.stat(p)
                if stat.st_uid != uid or stat.st_gid != gid:
                    if os.path.isdir(p):
                        shutil.chown(p, uid, gid)
                        for root, dirs, files in os.walk(p):
                            for name in dirs + files:
                                try:
                                    shutil.chown(os.path.join(root, name), uid, gid)
                                except OSError:
                                    pass
                    else:
                        shutil.chown(p, uid, gid)
                    fixed += 1
            except (OSError, PermissionError):
                pass
        if fixed > 0:
            print(f"🔧 [auto_fix_ownership] مالکیت {fixed} فایل/پوشه به user={target_user} تغییر کرد")
    except Exception as _e:
        print(f"⚠️ [auto_fix_ownership] خطا: {_e}")


async def main():
    # v2.8.6 BUGFIX: _validate_saas_env_or_exit() حالا در همه‌ی حالت‌ها
    # اجرا می‌شه (نه فقط "all"). این جلوی حالت سایلنت fail رو می‌گیره وقتی
    # کاربر interactive یا single-tag اجرا می‌کنه.
    try:
        _validate_saas_env_or_exit()
    except SystemExit:
        raise
    except Exception as _e:
        print(f"⚠️ [validate_saas_env] خطای غیربحرانی: {_e}")

    # v2.8.7: auto-fix ownership of critical files if running as root.
    # اگه کاربر interactive رو با sudo اجرا کنه، فایل‌ها مالکش root می‌شه
    # و سرویس (که با user=cianet اجرا می‌شه) نمی‌تونه بخونتشون. این تابع
    # اون مشکل رو خودکار حل می‌کنه.
    try:
        _auto_fix_file_ownership()
    except Exception as _e:
        print(f"⚠️ [auto_fix_ownership] خطای غیربحرانی: {_e}")

    # v2.12.1: chmod 0600 config.json
    try:
        import stat as _stat
        os.chmod(CONFIG_FILE, _stat.S_IRUSR | _stat.S_IWUSR)
    except Exception:
        pass
    # ستون‌های رفرال — روی نصب‌های موجود هم بی‌خطر اضافه می‌شوند
    try:
        ensure_referral_schema()
        ensure_wallet_schema()
    except Exception as e:
        print(f"⚠️ مهاجرت ستون‌های رفرال ناموفق: {type(e).__name__}: {e}")

    # v2.11.5: پاک‌کردن plaintext 2FA قدیمی
    try:
        _purge_old_2fa_plaintext()
    except Exception as _e:
        print(f"⚠️ [2fa_purge] خطا: {_e}")
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
        # PATCH (v2.5.2 CRITICAL): در حالت systemd (argv = "all")،
        # add_account() را صدا نزن — چون interactive است و در systemd
        # stdin بسته است، فقط خطای "API ID must be a number" چاپ
        # می‌کنه و گیج‌کننده است. به‌جاش، فقط بگو «هیچ اکانتی نیست»
        # و منتظر بمون — OWNER از پنل وب یا ربات اکانت اضافه می‌کنه.
        if len(sys.argv) > 1 and sys.argv[1] == "all":
            print(
                "ℹ️ هیچ اکانتی در config.json نیست. "
                "برای اضافه‌کردن اکانت: از پنل وب (port 8000) یا ربات تلگرام استفاده کن."
            )
        else:
            # در حالت interactive (CLI مستقیم)، wizard رو نشان بده
            await add_account()
            cfg = load_config()

    # v2.8.6 BUGFIX: embed panel در همه‌ی حالت‌ها شروع می‌شه، نه فقط "all".
    # این تضمین می‌کنه که اگه کاربر `python main.py <tag>` یا interactive
    # اجرا کنه، پنل وب هم بالا بیاد.
    embed_panel_env = os.environ.get("CIANET_EMBED_PANEL", "1").strip().lower()
    if embed_panel_env in ("1", "true", "yes"):
        panel_port = int(os.environ.get("CIANET_PANEL_PORT", "8000"))
        # BUG-17b (P1-4, §20.7): قبلاً با asyncio.create_task خام و بدون هیچ
        # مرجعی spawn می‌شد — تسک ممکن بود توسط GC وسطِ اجرا نابود شود.
        # حالا با _spawn_bg (ارجاع قوی در _BG_TASKS) + گاردِ ماژول-سطح
        # ضد spawn دوباره (main در حالت interactive بازگشتی صدا زده می‌شود).
        global _EMBED_PANEL_TASK
        if _EMBED_PANEL_TASK is None or _EMBED_PANEL_TASK.done():
            _EMBED_PANEL_TASK = _spawn_bg(
                _embed_web_panel(port=panel_port), "embed_web_panel"
            )
            print(f"🌐 [embed_panel] web panel در همین پروسه روی port {panel_port} شروع شد")

    # BUG-1 (P1-4): حلقه‌ی ارسالِ پیام‌های زمان‌بندی‌شده — این قابلیت از طریق
    # پنل وب به کاربران فروخته می‌شود (جدول scheduled_messages) ولی حلقه‌اش
    # هیچ‌جا spawn نمی‌شد، پس پیام‌ها هرگز ارسال نمی‌شدند. فقط در نمونه‌ی
    # اصلی spawn می‌شود: زیرپروسه‌های «ربات اختصاصی» (SELFBOT_DEDICATED_BOT)
    # دیتابیسِ جدا و خالی از scheduled_messages دارند و حلقه‌ی بی‌اثر
    # نمی‌خواهند؛ ثبتِ این جدول فقط از طریق پنلِ نمونه‌ی اصلی انجام می‌شود.
    global _SCHEDULED_MESSAGE_LOOP_TASK
    if not IS_DEDICATED_BOT and (
        _SCHEDULED_MESSAGE_LOOP_TASK is None
        or _SCHEDULED_MESSAGE_LOOP_TASK.done()
    ):
        _SCHEDULED_MESSAGE_LOOP_TASK = _spawn_bg(
            _scheduled_message_loop(), "scheduled_messages_loop"
        )
        print("⏰ [sched] حلقه‌ی پیام‌های زمان‌بندی‌شده شروع شد (هر ۶۰ ثانیه)")

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


# ─── v2.8.5: Embed Web Panel into selfbot process ─────────────────────
# این تابع uvicorn را در همین event loop اجرا می‌کند تا web panel
# دسترسی مستقیم به ACCOUNTS dict و Telethon clients داشته باشد.

async def _embed_web_panel(host: str = "127.0.0.1", port: int = 8000):
    """شروع web panel در همین پروسه — برای دسترسی به Telethon clients."""
    try:
        import uvicorn
        config = uvicorn.Config(
            "web_panel:app",
            host=host,
            port=port,
            log_level="warning",
            workers=1,  # حتماً 1 — workers>1 پروسه‌های جدا می‌سازد
        )
        server = uvicorn.Server(config)
        # در همین event loop اجرا کن — نه پروسه‌ی جدا
        await server.serve()
    except Exception as e:
        print(f"⚠️ [embed_panel] خطا در شروع web panel: {e}")



# BUG-1 (P1-4) / BUG-17b (P1-4): مراجع ماژول-سطح برای حلقه‌های singleton —
# الگوی §20.7: global + چکِ None/done تا فراخوانیِ بازگشتیِ main()
# (حالت interactive) یا restart دوباره spawn نکند.
_SCHEDULED_MESSAGE_LOOP_TASK = None
_EMBED_PANEL_TASK = None


# v2.10.0: حلقه‌ی ارسال پیام‌های زمان‌بندی‌شده
async def _scheduled_message_loop():
    """هر ۶۰ ثانیه چک می‌کنه اگه پیام زمان‌بندی‌شده‌ای due شده، بفرسته."""
    while True:
        try:
            with _conn() as c:
                rows = c.execute(
                    "SELECT * FROM scheduled_messages "
                    "WHERE sent = 0 AND scheduled_at <= ? "
                    "ORDER BY scheduled_at ASC LIMIT 20",
                    (_now(),),
                ).fetchall()
            for row in rows:
                msg = dict(row)
                entry = ACCOUNTS.get(msg["tag"])
                if entry is None or entry.bot is None or entry.bot.client is None:
                    continue  # account not running
                try:
                    # BUG-1 (P1-4): ارسال از مسیرِ واقعیِ این کلاس — قبلاً
                    # entry.bot.send_message صدا زده می‌شد در حالی که SelfBot
                    # متد send_message ندارد (AttributeError) و پیام هرگز
                    # ارسال نمی‌شد. الگوی درست entry.bot.client.send_message
                    # است. این send از مسیرِ wrapperِ نصب‌شده در start()
                    # می‌رود و flood/daily-cap/cooldown را رعایت می‌کند.
                    _res = await entry.bot.client.send_message(msg["chat_id"], msg["text"])
                    if _res is None:
                        # wrapper به‌خاطر گیتِ anti-ban ارسال را silent skip
                        # کرد — ردیف sent نمی‌شود تا در چرخه‌ی بعدی (۶۰
                        # ثانیه بعد) دوباره تلاش شود.
                        continue
                    with _conn_immediate() as c2:
                        c2.execute(
                            "UPDATE scheduled_messages SET sent = 1 WHERE id = ?",
                            (msg["id"],),
                        )
                    print(f"✅ [sched] پیام {msg['id']} به {msg['chat_id']} ارسال شد")
                except errors.FloodWaitError as _fwe:
                    # v2.14.2 (P2-10 flag / §20.8): FloodWait هرگز بی‌صدا
                    # بلعیده نمی‌شود — گیت flood اکانت ست می‌شود، صبر
                    # می‌کنیم و ردیف در چرخه‌ی بعدی دوباره تلاش می‌شود
                    # (sent نمی‌شود). ادامه‌ی همین چرخه بی‌معنی است.
                    _wait = (_fwe.seconds or 30) + 2
                    try:
                        entry.bot._flood_until = time.time() + _wait
                    except Exception:
                        pass
                    print(f"⏳ [sched] FloodWait {_wait}s برای پیام {msg['id']} (flood_until coordinated)")
                    await asyncio.sleep(_wait)
                    break
                except Exception as e:
                    print(f"⚠️ [sched] خطا در ارسال پیام {msg['id']}: {e}")
        except Exception as e:
            print(f"⚠️ [sched_loop] خطا: {e}")
        await asyncio.sleep(60)



# ══════════════════════════════════════════════════════════════════════
# Task ID: TEST-G4-PAYMENT
# ══════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════
# Task ID: TEST-G5-DEDICATED
# ══════════════════════════════════════════════════════════════════════
# G5: Dedicated Bot Management — 11 features tested:
#   1. owner_dedicated_list               ✓ routing + list render OK
#   2. owner_dedicated_show: (→ dedicated_manage:)  ✓ render OK
#   3. dedicated_show: / dedicated_detail: → dedicated_manage:  ✓ OK
#   4. dedicated_toggle:                  ✓ "stopped" gate verified
#   5. dedicated_revoke: / dedicated_revoke_go:  ✓ DED-7 fix (revoke_capability)
#   6. dedicated_delete: / dedicated_delete_go:  ✓ DED-7 fix (revoke_capability)
#   7. dedicated_extend: / dedicated_extend_go:  ✓ expire_date extension OK
#      + G5-LOGIC fix: extending a revoked bot now un-revokes (status→stopped)
#   8. cap_grant: / cap_revoke:            ✓ SaaSBot callback_h routing OK
#   9. dbcap_grant: / dbcap_revoke:        ✓ DED-5 fix-complete (SaaSBot routing)
#  10. dbcap: (show capability screen)    ✓ DED-5 fix-complete (SaaSBot routing)
#  11. _start_dedicated_bot_wizard (RESELLER)  ✓ EDGE fix (negative owner_id)
# ══════════════════════════════════════════════════════════════════════
# Task ID: TEST-G6-SYSTEM
# ══════════════════════════════════════════════════════════════════════
# G6: System — 22-feature audit (handler existence + behavior).
#
# Status per feature (callback name → outcome):
# ────────────────────────────────────────────────────────────────────
# Auto-update:
#   1. owner_update_check           ✓ Works (refreshes update page)
#   2. owner_update_apply           ✓ Works (git apply + restart)
#   3. update_check:                ✗→✓ FIXED: alias for owner_update_check
#   4. update_apply:                ✗→✓ FIXED: alias for owner_update_apply
#   5. update_status                ✗→✓ FIXED: alias for _show_owner_update
#
# Rollback:
#   6. owner_rollback_list          ✓ Works (paginated list)
#   7. owner_rollback_go:            ⚠→✓ FIXED: removed `_Path(name)` path-
#        traversal fallback; now validates name + resolved path under
#        versions_dir.
#
# Settings:
#   8. admin_settings                ✓ Works (channel + lang toggles)
#   9. setting_save:                 ✗→✓ FIXED: new handler with whitelist
#        (key:{value} guarded against arbitrary-key writes).
#
# Panel link:
#  10. owner_panel_link              ✗→✓ FIXED: alias for _show_owner_web_panel
#  11. panel_link:                   ✗→✓ FIXED: alias for _show_owner_web_panel
#        (real button uses owner_web_panel — these were spec-only names)
#
# Backup:
#  12. owner_backup                  ⚠→✓ FIXED: password was sent to
#        "me" which fails for bot-token clients → silent password loss
#        + lie caption "password is in Saved Messages". Now: try "me"
#        first, fall back to event.chat_id; caption reports real target.
#  13. owner_db_backup               ✓ Works (alias → _owner_show_backup)
#  14. owner_db_backup_go:           ✗→✓ FIXED: alias for _owner_db_backup
#
# Restore:
#  15. owner_db_restore              ✓ Works (wizard start)
#  16. owner_db_restore_go:          ✓ Works (PATCH-7 path-traversal fix
#        verified — _zip_member_is_safe rejects .., abs, backslash)
#
# Announcements:
#  17. owner_announce                ✗→✓ FIXED: new wizard (asks text,
#        shows preview, calls _owner_announce_send on confirm).
#  18. announce_send:                 ✗→✓ FIXED: new broadcast handler
#        — iterates list_all_users(), 50ms throttle per send, reports
#        success/fail count. Button added in _show_admin_tools.
#
# Channel set/clear:
#  19. owner_channel_set              ✓ Works (wizard + channel_confirm_save)
#  20. channel_set:                  ✗→✓ FIXED: alias for _start_channel_set
#  21. channel_clear:                ✗→✓ FIXED: alias for owner_channel_clear
#
# Orphan accounts:
#  22. orphan_acc:                    ✓ Works — _owner_show_orphan_bots
#        lists tag→orphan_acc:{tag} → _show_orphan_acc; assigns owner.
#
# Admins list:
#  23. owner_admins                   ✗→✓ FIXED: alias for
#        _owner_show_role_list(ROLE_ADMIN).
#  24. owner_resellers                ✓ Works (TEST-G7-RESELLER already
#        added this dispatcher + role list).
#
# Manage roles:
#  25. owner_manage_roles             ✓ Works — it's a *legacy redirect*
#        (NOT a silent no-op as extractor claimed) → _owner_show_license_hub
#        which lists/dismisses ADMIN and RESELLER roles. Docstring updated.
#
# Total fixes applied: 12 (8 BROKEN aliases + 1 CRITICAL backup password
# loss + 1 SECURITY path traversal + 1 WRONG_MESSAGE (caption) + 1
# new feature announce_send:). All 22 features now functional.
# ══════════════════════════════════════════════════════════════════════


# ─── ثبتِ سطحِ ماژول (v2.16.0 split) ─────────────────────────────
# ماژول‌های cianet.bots.* این نام‌ها را با «from cianet.core import ...»
# مصرف می‌کنند؛ __all__ هم مصرفِ مجدد را برای linterها روشن می‌کند.
__all__ = [
    'ACCOUNTS',
    'ACCOUNT_DELETE_JOURNAL_FILE',
    'ACCOUNT_START_POLL_TIMEOUT',
    'ACTIVATION_HELP_TEXT',
    'ADMIN_BOT_SESSION_NAME',
    'ADMIN_BOT_TOKEN',
    'ADMIN_ID',
    'ADMIN_LIST_FILE',
    'BACKUP_HOURS_IRAN',
    'BACKUP_MANIFEST',
    'BACKUP_PROJECT_NAME',
    'BACKUP_SCHEMA_VERSION',
    'BACKUP_VERSION',
    'BATCH_LICENSE_MAX',
    'BOT_STATUS',
    'BUILD_VERSION',
    'BUTTON_STYLE_SUPPORTED',
    'BlockRequest',
    'Button',
    'CAP_ACCOUNT_SECURITY',
    'CIANET_LANG',
    'CONFIG_FILE',
    'CONFIG_INVALID',
    'CONFIG_MISSING',
    'CONFIG_VALID',
    'DATA_DIR',
    'DB_NAME',
    'DB_PATH',
    'DEBUG',
    'DEDICATED_BOT_ID',
    'DEDICATED_BOT_PLAN',
    'DEDICATED_BOT_PRICE_DEFAULT',
    'DEDICATED_UI_STATE',
    'DEFAULT_CARD_HOLDER',
    'DEFAULT_CARD_NUMBER',
    'DOWNLOADS_DIR',
    'DeclinePasswordResetRequest',
    'ENEMY_REPLIES',
    'FEATURE_LABELS',
    'FLOOD_RECOVER_GRACE',
    'FONT_CHOICES',
    'FONT_FA',
    'GetAuthorizationsRequest',
    'GetFullUserRequest',
    'GetPasswordRequest',
    'GetStateRequest',
    'HELPER_BOT_TOKEN',
    'HELPER_HOME_EN',
    'HELPER_HOME_FA',
    'HELPER_ORDER',
    'HELPER_SESSION_NAME',
    'HELPER_TOPICS_EN',
    'HELPER_TOPICS_FA',
    'HELPER_TRIGGERS',
    'HELP_TEXT',
    'IS_DEDICATED_BOT',
    'InputMediaDice',
    'LICENSE_TYPE_ACCOUNT',
    'LICENSE_TYPE_ADMIN',
    'LICENSE_TYPE_RESELLER',
    'MAX_BASE_NAME_LEN',
    'MAX_BULK_DELETE',
    'NAV_ACTION_PREFIXES',
    'NAV_BACK',
    'NAV_HOME',
    'NAV_NOOP',
    'ORDER_EXPIRE_HOURS',
    'ORDER_STATUS_CANCELLED',
    'ORDER_STATUS_EXPIRED',
    'ORDER_STATUS_PAID',
    'ORDER_STATUS_PENDING',
    'ORPHAN_SESSION_GRACE',
    'OUT_COOLDOWN_SEC',
    'OUT_DAILY_MAX',
    'OWNER_ID',
    'OWNER_IDS',
    'Optional',
    'PAYMENT_STATUS_APPROVED',
    'PAYMENT_STATUS_PENDING',
    'PAYMENT_STATUS_REJECTED',
    'PROVISION_LEGACY',
    'PROVISION_LICENSE',
    'PROVISION_MANUAL',
    'PROVISION_SUBSCRIPTION',
    'PeerUser',
    'REFERRAL_GOAL',
    'REFERRAL_REWARD_DAYS',
    'REQUIRED_BOTDATA_TABLES',
    'REQUIRED_SAAS_TABLES',
    'RESERVED_TAGS',
    'ROLE_ADMIN',
    'ROLE_OWNER',
    'ROLE_RESELLER',
    'ROLE_USER',
    'ResetAuthorizationRequest',
    'ResetAuthorizationsRequest',
    'ResetPasswordFailedWait',
    'ResetPasswordOk',
    'ResetPasswordRequest',
    'ResetPasswordRequestedWait',
    'RunningAccount',
    'SCOPE_ACCOUNT',
    'SCOPE_DEDICATED_BOT',
    'SCOPE_RESELLER',
    'SECURITY_ROUTES',
    'SELF_FEATURE_LIST',
    'SESSIONS_DIR',
    'SHUTTING_DOWN',
    'SIMPLE_BOOL_FEATURES',
    'SUB_STATUS_ACTIVE',
    'SUB_STATUS_EXPIRED',
    'SUB_STATUS_PENDING',
    'SUB_STATUS_SUPERSEDED',
    'SUPPORT_UNITS',
    'StaleDeletionError',
    'TELEGRAM_SERVICE_ID',
    'TICKET_STATUS_CLOSED',
    'TICKET_STATUS_OPEN',
    'TRACKER_MEDIA_DIR',
    'TRC20_USDT_CONTRACT',
    'TelegramClient',
    'UI_STATES_NEED_DOT',
    'UI_STATE_STYLE',
    'USDT_TOMAN_FALLBACK',
    'UnblockRequest',
    'UpdateProfileRequest',
    'UpdateStatusRequest',
    'UploadProfilePhotoRequest',
    'WARMUP_DURATION_SEC',
    'WARMUP_RATE_MULTIPLIER',
    'WARN_NOTIFY_THRESHOLD',
    'WHAT_IS_SELFBOT_TEXT',
    'WIZ_2FA_EMAIL',
    'WIZ_2FA_NEW_HINT',
    'WIZ_2FA_NEW_PASS',
    'WIZ_2FA_OLD_PASS',
    'WIZ_ADD_ADMIN',
    'WIZ_ANNOUNCE',
    'WIZ_ANNOUNCE_CONFIRM',
    'WIZ_CAP_USER_ID',
    'WIZ_CL_BATCH_MAX_USES',
    'WIZ_CL_BATCH_QTY',
    'WIZ_CL_BATCH_RESELLER_LIMIT',
    'WIZ_CL_MAX_USES',
    'WIZ_CL_RESELLER_LIMIT',
    'WIZ_CODE',
    'WIZ_CONFIRM_REPLACE',
    'WIZ_DB_RESTORE',
    'WIZ_DB_RESTORE_CONFIRM',
    'WIZ_DEDICATED_EXTEND_DAYS',
    'WIZ_DEDICATED_OWNER_ID',
    'WIZ_DEDICATED_TOKEN',
    'WIZ_DISCOUNT_APPLY_CODE',
    'WIZ_DISCOUNT_MAX_USES',
    'WIZ_DISCOUNT_PERCENT',
    'WIZ_EDIT_NAME',
    'WIZ_LICENSE_CODE',
    'WIZ_ORPHAN_ASSIGN',
    'WIZ_OWNER_TICKET_REPLY',
    'WIZ_PASSWORD',
    'WIZ_PAYMENT_RECEIPT',
    'WIZ_PHONE',
    'WIZ_PRICING_DAYS',
    'WIZ_PRICING_NEW_NAME',
    'WIZ_PRICING_PRICE',
    'WIZ_PROXY_ADDR',
    'WIZ_PROXY_PASSWORD',
    'WIZ_PROXY_PORT',
    'WIZ_PROXY_USERNAME',
    'WIZ_SEND_MSG_TARGET',
    'WIZ_SEND_MSG_TEXT',
    'WIZ_SET_CARD',
    'WIZ_SET_CHANNEL',
    'WIZ_SET_WALLET',
    'WIZ_TAG',
    'WIZ_TICKET_MSG',
    'WIZ_TICKET_UNIT',
    'WIZ_TRX_HASH',
    'WIZ_USER_EXTEND_DAYS',
    'WIZ_USER_SEARCH',
    'WIZ_WALLET_CREDIT_AMOUNT',
    'WIZ_WALLET_CREDIT_REASON',
    'WIZ_WALLET_DEBIT_AMOUNT',
    'WIZ_WALLET_DEBIT_REASON',
    '_ADMIN_CLIENT_REF',
    '_ANTIBAN_PENDING',
    '_ANTIBAN_TTL',
    '_AUTO_UPDATE_TASK',
    '_BG_TASKS',
    '_CONFIG_CACHE',
    '_CONFIG_CACHE_MTIME',
    '_DATETIME_FMT',
    '_DATE_FMT',
    '_DICE_MAP',
    '_DICE_SAFETY_CEILING',
    '_EMBED_PANEL_TASK',
    '_ERROR_MAP',
    '_FATAL_AUTH_ERROR_TYPES',
    '_FA_TO_EN_DIGITS',
    '_FONT_DIGITS',
    '_FOREIGN_CC_HINTS',
    '_GATE_RETRY_COOLDOWN',
    '_IRAN_TZ',
    '_JALALI_MONTHS',
    '_LICENSE_ERROR_TEXT',
    '_MAINTENANCE_MODE',
    '_NOBITEX_COINS',
    '_PENDING_STARTS',
    '_PERMANENT_BAN_TYPES',
    '_PRICE_MAP',
    '_REFERRAL_RATE_WINDOW',
    '_RESTORE_LOCK',
    '_RUNTIME_TASKS',
    '_SAAS_BOT_REF',
    '_SAVE_CONFIG_LOCK',
    '_SCHEDULED_MESSAGE_LOOP_TASK',
    '_SCOPE_LABELS',
    '_SESSION_EXPIRED_TYPES',
    '_SIDECAR_MANIFEST_NAME',
    '_START_LOCKS',
    '_STATUS_HUMAN',
    '_STOP_INFLIGHT',
    '_STRINGS',
    '_T',
    '_TAG_LOCKS',
    '_TYPE_NAMES',
    '_UI_STATE_BY_ICON',
    '_WALLEX_PAIRS',
    '_WEEKDAYS_FA',
    '_acc_status_icon_note',
    '_acc_ui_state',
    '_active_runtime_tags',
    '_admin_id_raw',
    '_auto_fix_file_ownership',
    '_auto_update_loop_wrapper',
    '_await_account_ready',
    '_backup_file_name',
    '_backup_hours_env',
    '_backup_timestamp',
    '_bot_db',
    '_bot_db_arc',
    '_capability_subject_is_main_owner',
    '_checkpoint_and_clean',
    '_checkpoint_and_clean_session',
    '_chmod_private',
    '_code_callback',
    '_coingecko_irr',
    '_collect_backup_files',
    '_config_state',
    '_conn',
    '_conn_immediate',
    '_data_dir',
    '_db_integrity_ok',
    '_db_lock',
    '_db_schema_ok',
    '_dbid_raw',
    '_disable_all_accounts_for_update',
    '_do_restore_locked',
    '_embed_web_panel',
    '_exir_toman',
    '_fetch_crypto_price',
    '_fetch_gold_iran',
    '_fetch_gold_price',
    '_file_is_sqlite',
    '_first_account_creds',
    '_fmt_dt_local',
    '_fmt_price',
    '_fmt_vol',
    '_format_date',
    '_friendly_error',
    '_generate_discount_code',
    '_generate_license_code',
    '_get_toman_price',
    '_get_usd_toman_rate',
    '_graceful_shutdown_all',
    '_grants_conn',
    '_helper_is_trigger',
    '_helper_normalize',
    '_inspect',
    '_install_signal_handlers',
    '_is_fatal_auth_error',
    '_is_nav_action',
    '_is_permanent_ban_error',
    '_is_safe_proxy_host',
    '_is_sensitive_setting_key',
    '_is_session_expired_error',
    '_license_batch_result_text',
    '_license_created_text',
    '_license_result_text',
    '_load_account_delete_journal',
    '_main_db_arc',
    '_main_grants_db_path',
    '_mark_pending_start',
    '_migrate_provision_sources',
    '_migrate_schema',
    '_navasan_repo_gold',
    '_nobitex_toman',
    '_normalize_channel',
    '_notify_user_async',
    '_now',
    '_now_date',
    '_orphan_user_selfbots',
    '_owner_id_warning_shown',
    '_owner_ids_raw',
    '_owner_notify_async',
    '_parse_date',
    '_post_restore_validate',
    '_price_binance',
    '_price_bybit',
    '_price_coingecko',
    '_price_http_get',
    '_price_kucoin',
    '_process_alive',
    '_project_dir',
    '_purge_old_2fa_plaintext',
    '_read_pidfile',
    '_read_sidecar_manifest',
    '_recover_account_delete_journal',
    '_recover_delete_journal',
    '_reenable_all_accounts_after_update',
    '_remove_session_files',
    '_remove_stale_restore_files',
    '_restore_dest_for',
    '_rollback_from_emergency',
    '_run_all_accounts',
    '_run_forever',
    '_run_single_account_cli',
    '_runtime_caller',
    '_runtime_offline_status',
    '_save_account_delete_journal',
    '_save_last_2fa_password',
    '_scheduled_message_loop',
    '_security_main_owner_id',
    '_session_file_for',
    '_set_bot_status',
    '_set_lang',
    '_sha256_file',
    '_shutdown_event',
    '_snapshot_db_to_temp',
    '_snapshot_session_to_temp',
    '_spawn_bg',
    '_spawn_dedicated_bot',
    '_status_human',
    '_stop_process_by_pid',
    '_subscription_days_left',
    '_tabdeal_toman',
    '_table_check_constraint_text',
    '_table_columns',
    '_to_int',
    '_update_reseller_application',
    '_validate_db_file',
    '_validate_saas_env',
    '_validate_saas_env_or_exit',
    '_verify_last_2fa_password',
    '_verify_rebuilt_table',
    '_verify_trc20_transfer',
    '_wallex_toman',
    '_write_sidecar_manifest',
    '_zip_member_is_safe',
    'account_belongs_to',
    'account_is_orphan',
    'accounts_of_user',
    'activate_license',
    'add_account',
    'add_admin_or_reseller',
    'add_or_update_user',
    'add_plan',
    'add_purchase',
    'add_sales_user',
    'add_self_account',
    'add_ticket_message',
    'affiliate_stats',
    'antiban_consume',
    'antiban_guarded_action',
    'antiban_request_confirmation',
    'apply_discount_code',
    'apply_font',
    'approve_card_payment_atomic',
    'approve_purchase',
    'asyncio',
    'attach_referrer',
    'authorize_sensitive_account_action',
    'auto_renew_subscription',
    'ban_user',
    'build_backup_zip',
    'build_db_backup_zip',
    'cancel_order',
    'capability_grant_exists',
    'check_session_health',
    'claim_referral_rewards',
    'cleanup_orphan_sessions',
    'cleanup_stale_approved_payments',
    'cleanup_stale_tracker_files',
    'clear_state',
    'close_ticket',
    'config_state',
    'contextmanager',
    'create_affiliate_commission',
    'create_auto_reply',
    'create_dedicated_bot',
    'create_discount_code',
    'create_license',
    'create_license_batch',
    'create_order',
    'create_payment',
    'create_scheduled_message',
    'create_subscription',
    'create_ticket',
    'create_zarinpal_payment',
    'create_zibal_payment',
    'dataclass',
    'datetime',
    'db_init_db',
    'deactivate_license',
    'dedicated_bot_price',
    'delete_account',
    'delete_auto_reply',
    'delete_license',
    'delete_scheduled_message',
    'delete_user_completely',
    'delete_user_completely_async',
    'ensure_referral_schema',
    'ensure_started',
    'ensure_stopped',
    'ensure_wallet_schema',
    'errors',
    'events',
    'expire_order',
    'expire_subscription',
    'extend_order',
    'fa_digits',
    'fa_money',
    'fa_weekday',
    'field',
    'find_auto_reply',
    'get_active_grants',
    'get_active_subscription',
    'get_all_state',
    'get_all_users',
    'get_auto_renew_enabled',
    'get_banned_users_list',
    'get_broadcast_daily_count',
    'get_db',
    'get_dedicated_bot',
    'get_discount_code',
    'get_grant_by_id',
    'get_license',
    'get_open_ticket',
    'get_order',
    'get_order_by_payment',
    'get_payment',
    'get_pending_dedicated_bot_for_reseller',
    'get_plans',
    'get_pricing',
    'get_reseller_application',
    'get_role',
    'get_runtime',
    'get_sales_user',
    'get_self_accounts',
    'get_setting',
    'get_stats',
    'get_ticket',
    'get_total_users_count',
    'get_user',
    'get_user_by_username',
    'get_user_info',
    'get_wallet_balance',
    'grant_capability',
    'grant_matches_account',
    'has_capability',
    'hashlib',
    'inc_setting',
    'increment_broadcast_daily_count',
    'increment_messages_count',
    'init_db',
    'iran_now',
    'is_admin_or_above',
    'is_dangerous_account',
    'is_iranian_phone',
    'is_license_usable',
    'is_owner_bypass',
    'is_running',
    'is_starting',
    'is_stopping',
    'is_user_banned',
    'jalali_date',
    'jalali_long',
    'json',
    'list_active_bot_users',
    'list_active_dedicated_bots',
    'list_admins_and_resellers',
    'list_affiliate_commissions',
    'list_all_users',
    'list_auto_replies',
    'list_capability_grants',
    'list_dedicated_bots',
    'list_discount_codes',
    'list_expired_orders',
    'list_expired_subscriptions',
    'list_expiring_subscriptions',
    'list_licenses',
    'list_open_tickets',
    'list_pending_payments',
    'list_pending_reseller_applications',
    'list_pricing',
    'list_recent_orders',
    'list_scheduled_messages',
    'list_ticket_messages',
    'list_user_orders',
    'list_users_for_reseller',
    'list_wallet_transactions',
    'load_config',
    'log',
    'log_action',
    'logging',
    'main',
    'mark_order_paid',
    'mark_warned',
    'normalize_card_number',
    'normalize_phone',
    'os',
    'parse_referral_arg',
    'pay_order_trc20_atomic',
    'pay_order_wallet_atomic',
    'phone_country_hint',
    'random',
    're',
    'redeem_license_atomic',
    'referral_link',
    'referral_stats',
    'register_account',
    'reject_purchase',
    'remove_admin_or_reseller',
    'reseller_max_users',
    'reseller_user_count',
    'resource',
    'restart',
    'restore_backup_from_zip',
    'restore_backup_from_zip_async',
    'restore_db_from_file',
    'restore_db_from_zip',
    'review_payment_atomic',
    'revoke_capability',
    'run_admin_bot_forever',
    'run_bot',
    'run_helper_bot_forever',
    'run_saas_bot_forever',
    'safe_callback_int',
    'safe_input',
    'save_broadcast_log',
    'save_config',
    'save_message',
    'search_users',
    'secrets',
    'set_active_subscription_expired',
    'set_auto_renew_enabled',
    'set_order_payment_id',
    'set_plan_expiry',
    'set_pricing',
    'set_setting',
    'set_state',
    'shutil',
    'signal',
    'sqlite3',
    'string',
    'sys',
    'tempfile',
    'threading',
    'grant_trial_if_eligible',
    'group_plan_label',
    'group_sub_discount_percent',
    'group_sub_enabled',
    'is_group_plan',
    'is_user_blocked',
    'block_saas_user',
    'unblock_saas_user',
    'ensure_block_schema',
    'maybe_fulfill_group_order',
    'register_group_plan',
    'trial_enabled',
    'trial_days',
    'trial_plan_name',
    'TRIAL_DAYS_SETTING',
    'TRIAL_DAYS_MIN',
    'TRIAL_DAYS_MAX',
    'TRIAL_DAYS_DEFAULT',
    'get_required_chats',
    'set_required_chats',
    'REQUIRED_CHATS_SETTING',
    'REQUIRED_CHATS_MAX',
    'self_backup_group',
    'self_backup_enabled',
    'SELF_BACKUP_GROUP_SETTING',
    'SELF_BACKUP_ENABLED_SETTING',
    'build_sessions_backup_zip',
    'WIZ_TRIAL_DAYS',
    'WIZ_SELF_BACKUP_GROUP',
    'ticket_message_count',
    'ensure_reporter_schema',
    'reporter_enabled',
    'reporter_daily_cap',
    'reporter_today_count',
    'reporter_quota_left',
    'reporter_dup_hours',
    'reporter_recently_reported',
    'add_reporter_log',
    'list_reporter_logs',
    'reporter_stats',
    'REPORTER_ENABLED_SETTING',
    'REPORTER_CAP_SETTING',
    'REPORTER_CAP_DEFAULT',
    'REPORTER_CAP_MIN',
    'REPORTER_CAP_MAX',
    'REPORTER_DUP_HOURS',
    'REPORTER_DUP_SETTING',
    'REPORTER_DUP_MIN',
    'REPORTER_DUP_MAX',
    'WIZ_REPORTER_TARGET',
    'WIZ_REPORTER_FLOW',
    'WIZ_REPORTER_CAP',
    'WIZ_REPORTER_DUP',
    'time',
    'timedelta',
    'timezone',
    'to_jalali',
    'toggle_discount_code',
    'TRIAL_DAYS',
    'TRIAL_PLAN',
    'TRIAL_SETTING_KEY',
    'GROUP_PLAN_PREFIX',
    'GROUP_SEATS_CHOICES',
    'GROUP_SUB_SETTING_KEY',
    'GROUP_DISCOUNT_SETTING_KEY',
    'GROUP_DISCOUNT_DEFAULT',
    'unban_user',
    'unlink_customer',
    'unregister_account',
    'update_balance',
    'update_dedicated_bot_status',
    'update_self_account_expiry',
    'upsert_user',
    'validate_backup_zip',
    'verify_zarinpal_payment',
    'verify_zibal_payment',
    'wait_ready',
    'wallet_credit',
    'wallet_debit',
    'wallet_pay_from_balance',
    'zipfile',
]
