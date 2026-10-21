"""SelfBot — سلف‌بات تلگرام (مدیریت سشن، ارسال، ترکر).

این فایل به‌صورت مکانیکی از main.py تک‌فایلی تفکیک شده است (v2.16.0).
بدنه‌ی کلاس‌ها بایت‌به‌بایت همان main.py است؛ فقط هدرِ import تولید شده.
"""

# stdlib / third-party — همان importهای اصلی main.py
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.account import DeclinePasswordResetRequest
from telethon.tl.functions.account import GetAuthorizationsRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.account import GetPasswordRequest
from telethon.tl.functions.updates import GetStateRequest
from telethon.tl.types import InputMediaDice
from typing import Optional
from telethon.tl.types import PeerUser
from telethon.tl.functions.account import ResetAuthorizationRequest
from telethon.tl.functions.auth import ResetAuthorizationsRequest
from telethon.tl.types.account import ResetPasswordFailedWait
from telethon.tl.types.account import ResetPasswordOk
from telethon.tl.functions.account import ResetPasswordRequest
from telethon.tl.types.account import ResetPasswordRequestedWait
from telethon import TelegramClient
from telethon.tl.functions.contacts import UnblockRequest
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
import asyncio
from datetime import datetime
from telethon import errors
from telethon import events
import json
import os
import random
import re
import secrets
import time
from datetime import timezone

# هسته‌ی مشترک — ثابت‌ها/توابع مشترک
from cianet.core import (
    ACCOUNTS,
    BUILD_VERSION,
    DEBUG,
    DOWNLOADS_DIR,
    ENEMY_REPLIES,
    FLOOD_RECOVER_GRACE,
    FONT_FA,
    HELPER_ORDER,
    HELPER_TOPICS_FA,
    MAX_BASE_NAME_LEN,
    MAX_BULK_DELETE,
    OUT_COOLDOWN_SEC,
    OUT_DAILY_MAX,
    SESSIONS_DIR,
    TELEGRAM_SERVICE_ID,
    TRACKER_MEDIA_DIR,
    WARMUP_DURATION_SEC,
    WARMUP_RATE_MULTIPLIER,
    WARN_NOTIFY_THRESHOLD,
    _DICE_MAP,
    _DICE_SAFETY_CEILING,
    _FONT_DIGITS,
    _IRAN_TZ,
    _PRICE_MAP,
    _bot_db,
    _checkpoint_and_clean_session,
    _chmod_private,
    _fetch_crypto_price,
    _fetch_gold_iran,
    _fmt_dt_local,
    _fmt_price,
    _fmt_vol,
    _friendly_error,
    _is_fatal_auth_error,
    _is_permanent_ban_error,
    _owner_notify_async,
    _session_file_for,
    _set_bot_status,
    _spawn_bg,
    apply_font,
    authorize_sensitive_account_action,
    check_session_health,
    fa_digits,
    find_auto_reply,
    get_all_state,
    increment_broadcast_daily_count,
    iran_now,
    load_config,
    resource,
    save_config,
    set_state,
)

# کلاس‌های هم‌خانواده / توابعِ جابه‌جا‌شده
from cianet.bots.saas import _deliver_via_bot


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
        # v2.12.28 (HUNT-2 #1): broadcast task reference — برای cancel
        # در هنگام shutdown/reconnect. قبلاً task فقط در _BG_TASKS بود
        # و هیچ‌کس cancelش نمی‌کرد → restart وسط broadcast = user stuck.
        self._broadcast_task = None
        # BUG #6/#7: تسک‌های دایس و ری‌استارتِ معلق متعلق به همین نمونه‌اند و
        # در shutdownِ واقعی نمونه cancel می‌شوند.
        self._dice_task = None
        self._restart_task = None

        self._fatal_auth_error = False
        # PATCH (v2.0.10 ANTI-BAN): per-account ban counter — وقتی یک
        # اکانت ۳ بار در ۳۰ روز به خطای fatal-auth می‌خوره، خودکار
        # disabled می‌شه و OWNER notify می‌شه. این سیاست، اکانت‌های
        # مشکل‌دار رو از استمرار در retry و ریسکِ بیشتر به اشتراکِ
        # api_id محافظت می‌کنه.
        self.ban_count = 0
        self.ban_first_seen = 0.0
        self._BAN_THRESHOLD = 3
        self._BAN_WINDOW_SEC = 30 * 24 * 3600  # 30 days

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
        # v2.12.24 (USER-REQUEST): محافظتِ ورود — وقتی روشن باشه، هر کد
        # ورودی که از 777000 بیاد، خودکار با send_code_request منقضی می‌شه.
        # این یعنی حتی اگه هکر شماره داشته باشه و کد بگیره، کد فوراً نامعتبر
        # می‌شه. cooldown ۶۰ ثانیه برای جلوگیری از infinite loop.
        self.login_code_guard = False
        self._login_guard_last_invalidate = 0.0
        self._handlers_registered = False
        self._reconnecting = False
        # v2.9.1: state fields for ban protection + rate limiting
        self._flood_until = 0.0       # until this ts, all outbound blocked
        self._out_today = 0          # daily outbound counter
        self._out_window_start = 0.0  # when daily window started
        self._out_last_ts = 0.0       # last outbound timestamp
        self._warn_count = 0          # warnings received from 777000
        self._warmup_until = 0.0      # until this ts, reduced cadence
        self._account_age = 0.0       # seconds since account creation

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

    async def _on_fatal_auth(self, error_msg: str, exc: BaseException = None) -> None:
        """
        PATCH (v2.0.10): وقتی یک خطای احراز هویتِ غیرقابل‌بازیابی رخ می‌دهد:
        ۱. ban counter رو increment می‌کنه.
        ۲. اگه در ۳۰ روز ۳ بار رخ داده، اکانت رو در config.json disabled می‌کنه.
        ۳. OWNER رو notify می‌کنه.

        این سیاست از retry بی‌نهایتِ اکانت‌های مشک‌دار جلوگیری می‌کنه و
        ریسکِ ban شدنِ api_id مشترک رو کاهش می‌ده.

        v2.12.9 (QA-DEBUG C6 / AUDIT-10-G B3): قبلاً threshold سه-strike بود،
        ولی ban_count فقط در همون نمونه‌ی in-memory شمرده می‌شد و run_bot
        بعد از اولین fatal-auth از حلقه می‌برک (line 24181). یعنی
        threshold سه هرگز محقق نمی‌شد و auto-disable عملاً dead-code بود.
        حالا همون اولین خطا رو disabled می‌کنه — چون fatal-auth واقعاً
        non-recoverable هست و retry فقط ریسکِ api_id رو بیشتر می‌کنه.

        v2.12.10 (QA2-EXPERT/QA2-DEBUG C6): v2.12.9 روی همه‌ی fatal-auth
        ها (حتی AuthKeyError که می‌تونه transient باشه) DISABLE دائمی
        می‌کرد. این خیلی تهاجمی بود: یه hiccup موقت از تلگرام می‌تونست
        همه‌ی اکانت‌های روی یه api_id مشترک رو همزمان disable کنه. حالا
        تفکیک می‌کنیم:
          • PERMANENT_BAN (UserDeactivated/UserDeactivatedBan/AuthUnregistered/
            PhoneNumberBanned): DISABLE دائمی + stop. (بن واقعی)
          • SESSION_EXPIRED (AuthKeyError/AuthKeyDuplicated/Unauthorized):
            فقط stop + notify OWNER، بدون DISABLE. (ممکنه transient باشه)
        OWNER می‌تونه دستی re-login کنه یا صبر کنه تلگرام به‌حال بیاد.

        v2.12.11 (QA3-QUICK BUG#1): v2.12.10 از substring matching روی
        error_msg استفاده می‌کرد ولی str(UserDeactivatedError) شامل
        "UserDeactivated" نیست — پس هیچ‌وقت permanent تشخیص داده نمی‌شد.
        حالا پارامتر exc اضافه شده و از isinstance واقعی استفاده می‌کنه.
        """
        try:
            import time as _time
            now = _time.time()
            # reset counter اگه پنجره‌ی ۳۰ روز گذشته
            if self.ban_first_seen and (now - self.ban_first_seen > self._BAN_WINDOW_SEC):
                self.ban_count = 0
                self.ban_first_seen = 0.0
            if not self.ban_first_seen:
                self.ban_first_seen = now
            self.ban_count += 1

            # v2.12.11: تشخیص نوع خطا بر اساس isinstance (نه substring).
            # اگه exc عبور داده شده باشه، از helper استفاده می‌کنیم. اگه نه
            # (callers قدیمی)، fallback به substring matching (که imperfect
            # ولی بهتر از nothing).
            _is_permanent = False
            if exc is not None:
                _is_permanent = _is_permanent_ban_error(exc)
            else:
                _msg_lower = (error_msg or "").lower()
                _is_permanent = any(_w in _msg_lower for _w in (
                    "userdeactivated", "userdeactivatedban",
                    "authunregistered", "phonenumberbanned",
                    "user deactivated", "phone number banned",
                    "phone_number_banned",
                ))

            # notify OWNER
            short_err = error_msg[:200] if error_msg else "unknown"
            notify_text = (
                f"🛑 اکانت «{self.tag}» به خطای احراز هویت خورد.\n\n"
                f"⚠️ خطا: `{short_err}`\n"
                f"📊 تعداد در ۳۰ روز اخیر: {self.ban_count}\n"
            )
            if _is_permanent:
                notify_text += (
                    f"\n🔒 اکانت دائماً disabled شد — این خطا non-recoverable "
                    f"است (بن واقعی) و retry فایده نداره."
                )
            else:
                notify_text += (
                    f"\n⏸️ اکانت موقتاً stop شد (بدون DISABLE). این خطا ممکنه "
                    f"transient باشه (مثلاً سشن از دستگاه دیگه logout شده). "
                    f"در restart بعدی خودکار retry می‌شه. اگه دوباره تکرار شد، "
                    f"می‌تونی دستی re-login کنی."
                )
            try:
                await _owner_notify_async(notify_text)
            except Exception:
                pass

            # v2.12.10: فقط برای permanent ban ها، اکانت رو disabled کن.
            # برای session-expired، صبر کن تا restart بعدی.
            if _is_permanent:
                try:
                    cfg = load_config()
                    if self.tag in cfg and isinstance(cfg[self.tag], dict):
                        if not cfg[self.tag].get("disabled"):
                            cfg[self.tag]["disabled"] = True
                            cfg[self.tag]["disabled_reason"] = "auto_ban_counter"
                            save_config(cfg)
                            print(f"✅ [{self.tag}] اکانت disabled شد (permanent ban)")
                except Exception as e:
                    print(f"⚠️ [{self.tag}] خطا در disable خودکار اکانت: {e}")
        except Exception as e:
            # هرگز نباید این تابع exception بده — بهترین تلاش
            print(f"⚠️ [{self.tag}] خطا در _on_fatal_auth: {e}")

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
        # v2.9.1: warm-up logic — اگه اکانت تازه ساخته شده، ۳۰ دقیقه
        # با نرخ کاهش‌یافته فعالیت کنه تا تلگرام مشکوک نشه.
        # v2.9.2: از _bot_db استفاده می‌کنیم (bot_data.db) چون self_accounts
        # اونجاست، نه تو saas.db.
        import time as _t
        try:
            with _bot_db() as _c:
                _r = _c.execute(
                    "SELECT created_at FROM self_accounts WHERE tag = ?", (self.tag,)
                ).fetchone()
            if _r and _r[0]:
                from datetime import datetime
                try:
                    # created_at ممکنه TIMESTAMP یا ISO string باشه
                    _raw = _r[0]
                    if isinstance(_raw, str):
                        _created = datetime.fromisoformat(_raw.replace("Z", ""))
                    else:
                        _created = _raw  # datetime object
                    _age = (_t.time() - _created.timestamp())
                    self._account_age = max(0, _age)
                    if _age < WARMUP_DURATION_SEC:
                        self._warmup_until = _t.time() + (WARMUP_DURATION_SEC - _age)
                        print(f"🔥 [{self.tag}] warm-up فعال — {int(WARMUP_DURATION_SEC - _age)}s باقی‌مانده")
                except Exception:
                    pass
        except Exception as _e:
            print(f"⚠️ [{self.tag}] warm-up check failed: {_e}")
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

        # v2.9.1: handler for Telegram service messages (sender 777000)
        # این‌ها warning هستند: "Account 2FA Reset"، "Your account was deleted" و...
        @self.client.on(events.NewMessage(from_users=TELEGRAM_SERVICE_ID))
        async def _on_service_warning(event):
            try:
                self._warn_count += 1
                text = event.raw_text or ""
                print(f"⚠️ [{self.tag}] هشدار تلگرام: {text[:100]}")
                if self._warn_count >= WARN_NOTIFY_THRESHOLD:
                    # v2.9.4: اگه _owner_notify_async موجود نبود، فقط print کن
                    try:
                        await _owner_notify_async(
                            f"⚠️ [{self.tag}] {self._warn_count} هشدار از تلگرام\n"
                            f"آخرین: {text[:200]}"
                        )
                    except NameError:
                        print(f"⚠️ [{self.tag}] {self._warn_count} هشدار از تلگرام: {text[:100]}")
                    except Exception:
                        pass
                # اگه warning حاوی "deleted" یا "banned" بود، account رو disable کن
                _low = text.lower()
                # v2.12.10 (QA2-EXPERT/QA2-DEBUG C5): v2.12.9 از substring
                # matching استفاده می‌کرد که false-positive می‌داد: «حذف نشد»
                # با «حذف» match می‌شد، «not deleted» با «deleted» match می‌شد.
                # حالا به‌جای substring، phrase-level matching می‌کنیم با
                # exclusion صریحِ negationها. کلماتِ مثبت (حذف شده/has been
                # deleted) فعال می‌شن، negationها (حذف نشد/not deleted) نه.
                _CRITICAL_WARN_PHRASES_EN = (
                    "account has been deleted",
                    "your account was deleted",
                    "is deleted",
                    "account is banned",
                    "account has been banned",
                    "account has been terminated",
                    "your account has been terminated",
                    "violated telegram's terms",
                    "account was deactivated",
                    "account has been frozen",
                    "session was terminated",
                )
                _CRITICAL_WARN_PHRASES_FA = (
                    "حساب شما حذف شده",
                    "اکانت شما حذف شده",
                    "حساب شما حذف گردید",
                    "حساب شما حذف خواهد شد",
                    "حساب شما مسدود شد",
                    "اکانت شما مسدود شد",
                    "حساب شما محدود شد",
                    "حساب شما غیرفعال شد",
                    "حساب شما بسته شد",
                    "حساب شما نقض",
                    "حساب شما خلاف",
                    "از تلگرام حذف",
                    "از تلگرام خارج",
                )
                _NEGATION_HINTS = (
                    "حذف نشد", "حذف نشده", "حذف نخواهد شد",
                    "حذف شده نیست", "حذف شده اند نیست",  # v2.12.25 (DEEP-10-LOGIC #10)
                    "مسدود نیست", "محدود نیست", "غیرفعال نیست",
                    "بسته نشده", "بسته نیست",
                    "not deleted", "wasn't deleted", "was not deleted",
                    "not banned", "isn't banned", "is not banned",
                    "not terminated", "isn't terminated",
                    "تماس با پشتیبانی",  # support contact info — always benign
                )
                # اول چک کن negation هست — اگه هست، یقین false-positive است
                if (any(_n in _low for _n in _NEGATION_HINTS)
                        or any(_n in text for _n in _NEGATION_HINTS)):
                    print(f"⚠️ [{self.tag}] warning با negation شناسایی شد — ignored: {text[:80]}")
                elif (any(_p in _low for _p in _CRITICAL_WARN_PHRASES_EN)
                        or any(_p in text for _p in _CRITICAL_WARN_PHRASES_FA)):
                    print(f"⛔ [{self.tag}] warning بحرانی — غیرفعال‌سازی خودکار")
                    # v2.9.4: self.sb در SelfBot تعریف نشده — از
                    # module-level load_config/save_config استفاده می‌کنیم
                    try:
                        cfg = load_config()
                        if self.tag in cfg and isinstance(cfg[self.tag], dict):
                            cfg[self.tag]["disabled"] = True
                            cfg[self.tag]["disabled_reason"] = "telegram_warning"
                            save_config(cfg)
                            print(f"✅ [{self.tag}] اکانت غیرفعال شد (telegram_warning)")
                    except Exception as _e:
                        print(f"⚠️ [{self.tag}] disable failed: {_e}")
                    # v2.12.9 (QA-DEBUG C5/B2): قبلاً فقط disabled=True ست می‌شد
                    # ولی نمونه‌ی در حال اجرا به کار ادامه می‌داد تا restart بعدی.
                    # حالا مستقیم self.stop() رو صدا می‌زنیم تا همون لحظه قطع بشه
                    # و ریسکِ تشدیدِ ban کاهش پیدا کنه.
                    try:
                        await self.stop()
                        print(f"🛑 [{self.tag}] نمونه‌ی زنده متوقف شد (telegram_warning)")
                    except Exception as _e:
                        print(f"⚠️ [{self.tag}] stop after warning failed: {_e}")
            except Exception as _e:
                print(f"⚠️ [{self.tag}] service warning handler error: {_e}")

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
                except errors.FloodWaitError as _fe:
                    # v2.9.1: ثبت flood_until برای coordination
                    import time as _t
                    self._flood_until = _t.time() + (_fe.seconds or 30) + FLOOD_RECOVER_GRACE
                    print(f"⏳ [{self.tag}] FloodWait {_fe.seconds}s در watchdog — flood_until ست شد")
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
        # v2.12.23 (QA10-UX-LONG BUG#1): قبلاً در v2.12.5 هاردکد False
        # بود که persisted True رو override می‌کرد. این یعنی بعد از هر
        # restart، time کاربر خاموش می‌شد و باید دوباره `تایم روشن` می‌زد.
        # حالا persisted state رو احترام می‌ذاریم (مثل bio_enabled در خط
        # بعدی).
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
        # v2.12.24: load login code guard
        self.login_code_guard = state.get("login_code_guard", False)

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
            self._api_calls_today = getattr(self, "_api_calls_today", 0) + 1
            return await asyncio.wait_for(self.client(request), timeout=timeout)
        except errors.FloodWaitError as e:
            # v2.9.1: ثبت flood_until
            import time as _t
            self._flood_until = _t.time() + (e.seconds or 30) + FLOOD_RECOVER_GRACE
            print(f"⏳ [{self.tag}] FloodWait {e.seconds}s در bg_request — flood_until ست شد")
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
        # v2.19.4 (AUDIT-36 L6): دامنه‌ی telegram.me هم پشتیبانی می‌شود و در
        # پیامِ داخلِ تاپیک (t.me/g/5/9 → msg=9) آخرین id ملاک است، نه idِ
        # ریشه‌ی تاپیک — قبلاً پیامِ اشتباه یا «پیدا نشد» می‌داد.
        m = re.match(
            r'(?:https?://)?(?:t|telegram)\.me/(?:c/)?([^/?\s]+)/(?:\d+/)*(\d+)',
            link.strip())
        return (m.group(1), int(m.group(2))) if m else (None, None)

    # سقفِ کلِ عملیات کپی (ثانیه) و سقفِ حجمِ فایل. جدا از پوششِ ۹۰ ثانیه‌ی
    # _safe_handler، چون کپی می‌تواند مشروعاً چند دقیقه طول بکشد — ولی نه
    # ساعت‌ها.
    COPY_TIMEOUT = 300
    COPY_MAX_BYTES = 2 * 1024 * 1024 * 1024      # ۲ گیگابایت (سقفِ خودِ تلگرام)

    async def _do_broadcast(self, event, reply_msg, target_type: str) -> None:
        """
        v2.12.18: بدنه‌ی واقعیِ broadcast. خارج از پوششِ ۹۰ ثانیه‌ی
        _safe_handler اجرا می‌شه (با _spawn_bg صدا زده شده) تا بتونه
        ۱۰۰۰ تا ارسال رو در ۳۰+ دقیقه انجام بده.

        v2.12.20: skip _gate_outbound (daily cap) — فقط FloodWait رعایت می‌شه.
        v2.12.23: CancelledError handler (restart mid-broadcast no longer stuck).
        v2.12.23: noforwards check — رد کردن پیام‌های محافظت‌شده.

        anti-ban features:
        - delay تصادفی ۱-۳ ثانیه بین هر ارسال
        - FloodWait handling با _flood_until coordination
        - skip self/bot/non-matching dialogs

        گزارش نهایی به event.edit ارسال می‌شه.
        """
        sent_ok = 0
        sent_fail = 0
        skipped = 0
        import time as _t
        import random as _random

        # v2.12.23 (QA10-STRESS BUG#7): CancelledError handler.
        # اگه restart وسط broadcast بشه، task cancel می‌شه. بدون این handler،
        # کاربر روی «📨 شروع ارسال...» گیر می‌کرد. حالا یه پیام نهایی
        # فرستاده می‌شه (به‌حداکثر توان) تا کاربر بدونه چی شده.
        try:
            # v2.12.23 (QA10-TELEGRAM): noforwards check — اگه پیام
            # محافظت‌شده (noforwards) باشه، تلگرام اجازه فوروارد نمی‌ده.
            if getattr(reply_msg, 'noforwards', False):
                try:
                    await event.edit(
                        "❌ این پیام محافظت‌شده است و امکان فوروارد ندارد.\n"
                        "از یه پیام دیگه استفاده کن."
                    )
                except Exception:
                    pass
                return

            try:
                dialogs = await self.client.get_dialogs(limit=1000)
            except Exception as _e:
                try:
                    await event.edit(f"❌ خطا در گرفتن لیست: {_e}")
                except Exception:
                    pass
                return

            # v2.12.23 (QA10-STRESS BUG#3): اگه بیش از ۱۰۰۰ چت داشته باشه،
            # به کاربر اطلاع بده که فقط ۱۰۰۰ تای اول ارسال می‌شه.
            _total_dialogs = len(dialogs)
            if _total_dialogs >= 1000:
                try:
                    await event.edit(
                        f"⚠️ توجه: بیش از ۱۰۰۰ چت داری. فقط ۱۰۰۰ تای اول ارسال می‌شه.\n"
                        f"⏳ ادامه ارسال..."
                    )
                except Exception:
                    pass

            for d in dialogs:
                # فیلتر کردن بر اساس نوع
                if target_type == "pv":
                    if not d.is_user:
                        skipped += 1
                        continue
                    if d.entity and getattr(d.entity, "is_self", False):
                        skipped += 1
                        continue
                    if d.entity and getattr(d.entity, "bot", False):
                        skipped += 1
                        continue
                else:  # group
                    if not (d.is_group or d.is_megagroup):
                        skipped += 1
                        continue

                # v2.12.20: broadcast نباید از _gate_outbound استفاده کنه.
                # فقط FloodWait رو رعایت می‌کنه (نه daily cap).

                # چک کن FloodWait recovery فعال نیست
                import time as _t_chk
                if self._flood_until and _t_chk.time() < self._flood_until:
                    skipped += 1
                    continue

                _bcast_owner_key = str(self.cfg.get("owner_user_id") or self.cfg.get("tg_user_id") or self.tag)
                if not increment_broadcast_daily_count(_bcast_owner_key, 1, cap=OUT_DAILY_MAX):
                    skipped += 1
                    try:
                        await event.edit(
                            f"⚠️ سقف ارسال روزانه ({OUT_DAILY_MAX} پیام در روز) پر شد.\n"
                            f"✅ موفق: {sent_ok} | ❌ ناموفق: {sent_fail} | ⏭ ردشده: {skipped}"
                        )
                    except Exception:
                        pass
                    return
                # ارسال (forward)
                try:
                    await reply_msg.forward_to(d.id)
                    sent_ok += 1
                    # delay تصادفی ۱-۳ ثانیه برای anti-ban
                    _delay = 1.0 + _random.random() * 2.0
                    await asyncio.sleep(_delay)
                except errors.FloodWaitError as _fwe:
                    # صبر کن تا FloodWait تموم بشه
                    _wait_sec = (_fwe.seconds or 30) + 2
                    self._flood_until = _t.time() + _wait_sec
                    print(f"⏳ [broadcast:{self.tag}] FloodWait {_wait_sec}s "
                          f"(flood_until coordinated)")
                    await asyncio.sleep(_wait_sec)
                    # retry یک‌بار
                    try:
                        await reply_msg.forward_to(d.id)
                        sent_ok += 1
                    except Exception as _e:
                        sent_fail += 1
                        print(f"⚠️ [broadcast:{self.tag}] retry fail to {d.id}: "
                              f"{type(_e).__name__}")
                except Exception as _e:
                    sent_fail += 1
                    print(f"⚠️ [broadcast:{self.tag}] send fail to {d.id}: "
                          f"{type(_e).__name__}: {str(_e)[:80]}")
                    continue

        except asyncio.CancelledError:
            # v2.12.23 (QA10-STRESS BUG#7): restart وسط broadcast.
            # به کاربر اطلاع بده که ارسال ناقص مونده.
            _total = sent_ok + sent_fail + skipped
            print(f"⚠️ [broadcast:{self.tag}] CANCELLED — sent={sent_ok}, "
                  f"fail={sent_fail}, skipped={skipped}")
            try:
                await self.client.send_message(
                    "me",
                    f"⚠️ ارسال به {'پیوی' if target_type == 'pv' else 'گروه'}‌ها "
                    f"ناقص متوقف شد (restart).\n\n"
                    f"📊 آمار تا لحظه توقف:\n"
                    f"• ✅ موفق: {fa_digits(sent_ok)}\n"
                    f"• ❌ ناموفق: {fa_digits(sent_fail)}\n"
                    f"• ⏭ رد شده: {fa_digits(skipped)}\n"
                    f"• 📋 مجموع: {fa_digits(_total)}\n\n"
                    f"برای ادامه، دوباره `ارسال به پیوی` رو بزن."
                )
            except Exception:
                pass
            raise  # propagate cancellation
        except Exception as _e:
            # هر خطای غیرمنتظره دیگه
            print(f"❌ [broadcast:{self.tag}] unexpected error: {type(_e).__name__}: {_e}")
            try:
                await event.edit(
                    f"❌ خطای غیرمنتظره در ارسال: {_e}\n\n"
                    f"📊 آمار تا لحظه خطا:\n"
                    f"• ✅ موفق: {fa_digits(sent_ok)}\n"
                    f"• ❌ ناموفق: {fa_digits(sent_fail)}\n"
                    f"• ⏭ رد شده: {fa_digits(skipped)}"
                )
            except Exception:
                pass

        # گزارشِ نهایی
        _total = sent_ok + sent_fail + skipped
        try:
            await event.edit(
                f"✅ ارسال به {'پیوی' if target_type == 'pv' else 'گروه'}‌ها تمام شد!\n\n"
                f"📊 آمار:\n"
                f"• ✅ موفق: {fa_digits(sent_ok)}\n"
                f"• ❌ ناموفق: {fa_digits(sent_fail)}\n"
                f"• ⏭ رد شده: {fa_digits(skipped)}\n"
                f"• 📋 مجموع: {fa_digits(_total)}"
            )
        except Exception as _e:
            # اگه event.edit fail شد (مثلاً پیام پاک شده)، از send_message استفاده کن
            print(f"⚠️ [broadcast:{self.tag}] final report edit failed: "
                  f"{type(_e).__name__}")
            try:
                await self.client.send_message(
                    "me",
                    f"✅ ارسال به {'پیوی' if target_type == 'pv' else 'گروه'}‌ها "
                    f"تمام شد!\n\n"
                    f"📊 آمار:\n"
                    f"• ✅ موفق: {fa_digits(sent_ok)}\n"
                    f"• ❌ ناموفق: {fa_digits(sent_fail)}\n"
                    f"• ⏭ رد شده: {fa_digits(skipped)}\n"
                    f"• 📋 مجموع: {fa_digits(_total)}"
                )
            except Exception:
                pass

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
                # v2.19.4 (AUDIT-36 M11): None = گیتِ ضدبن رد کرد — پیامِ موفقیتِ
                # دروغ نده؛ کاربر بداند بعداً دوباره امتحان کند.
                _cp_sent = await self.client.send_file("me", dl, caption=caption)
                if _cp_sent is None:
                    await _edit("🛡️ محدودیتِ ارسالِ ضدبن فعال است — کپی الان انجام نشد؛ کمی بعد دوباره بزن.")
                else:
                    await _edit("✅ کپی شد ← Saved Messages")
            elif caption:
                _cp_sent = await self.client.send_message("me", caption)
                if _cp_sent is None:
                    await _edit("🛡️ محدودیتِ ارسالِ ضدبن فعال است — کمی بعد دوباره بزن.")
                else:
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
            # v2.9.1: ثبت flood_until
            import time as _t
            self._flood_until = _t.time() + (e.seconds or 30) + FLOOD_RECOVER_GRACE
            print(f"⏳ [{self.tag}] FloodWait {e.seconds}s در {name} — flood_until ست شد")
        except Exception as e:
            if _is_fatal_auth_error(e):
                print(f"🛑 [{self.tag}] خطای احراز هویت غیرقابل‌بازیابی در هندلر {name}: {e}")
                self._fatal_auth_error = True
                # PATCH (v2.0.10): notify OWNER + increment ban counter
                # v2.12.11 (QA3-QUICK BUG#1): اگه str(e) عبور بدیم، substring
                # matching روی نام کلاس کار نمی‌کنه چون str(UserDeactivatedError)
                # شامل "UserDeactivated" نیست. حالا خودِ exc عبور می‌دیم تا
                # isinstance در helper ها واقعاً کار کنه.
                await self._on_fatal_auth(str(e), exc=e)
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
        res = await asyncio.wait_for(self.client(GetAuthorizationsRequest()), timeout=30)
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
            pw = await asyncio.wait_for(self.client(GetPasswordRequest()), timeout=25)
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
            # v2.19.4 (AUDIT-36 L4): تشخیصِ زمانِ انتظار با isinstance +
            # فیلدِ seconds — نه با substringِ «FRESH» (نامِ خطا در str(e)
            # تلثون 1.45 نمی‌آید؛ فقط عدد می‌آید — هم‌خانواده‌ی باگِ v2.12.11).
            # حالا کاربر راهنمای «رمز به‌تازگی عوض شده؛ تا ~۲۴ ساعت اجازه
            # نمی‌دهد» را واقعاً می‌بیند.
            _pw_fresh_secs = getattr(e, "seconds", None)
            if _pw_fresh_secs:
                try:
                    secs = int(_pw_fresh_secs)
                except Exception:
                    secs = None
            else:
                m = re.search(r"(\d+)", msg)
                secs = int(m.group(1)) if m else None
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

    # PATCH (v2.6.2): تغییر یا حذف رمز 2FA با دانستن رمز فعلی
    async def change_2fa_password(self, old_pass: str, new_pass: str = "", hint: str = "") -> dict:
        """
        تغییر یا حذف رمز دو مرحله‌ای با رمز فعلی.

        v2.19.4 (AUDIT-36 H2 — HIGH · بازنویسی کامل): پیاده‌سازیِ قبلی
        «compute_password_hash» را import می‌کرد که در telethon 1.45 وجود
        ندارد (ImportError از متد بیرون می‌پرید → «❌ خطا: ImportError») و
        PasswordInputSettings را با کیوردهای ناموجود (flags/new_hint/new_email)
        می‌ساخت (TypeError) — یعنی «تغییر/حذف رمز» ۱۰۰٪ مرده بود. حالا از
        client.edit_2fa خودِ تلثون استفاده می‌کنیم که تمامِ جریانِ درست را
        دارد (SRP + نوسازیِ salt با new_algo + digest) — هم‌ارزشِ مرجعِ
        telethon/client/auth.py.

        Args:
            old_pass: رمز فعلی (الزامی)
            new_pass: رمز جدید (خالی = حذف رمز)
            hint: راهنمای رمز جدید (اختیاری)

        Returns:
            {"ok": True, "action": "changed"|"removed"} یا {"ok": False, "error": "..."}
        """
        from telethon.tl.functions.account import GetPasswordRequest
        try:
            pw_info = await asyncio.wait_for(
                self.client(GetPasswordRequest()), timeout=25
            )
            if not pw_info or not pw_info.has_password:
                return {"ok": False, "error": "no_password"}

            # edit_2fa: تغییر (هر دو رمز) یا حذف (فقط رمز فعلی). SRP با
            # primeهای بزرگ کند است → timeout بلندتر از قبل.
            if new_pass:
                ok = await asyncio.wait_for(
                    self.client.edit_2fa(current_password=old_pass,
                                         new_password=new_pass,
                                         hint=hint or ""),
                    timeout=90,
                )
            else:
                ok = await asyncio.wait_for(
                    self.client.edit_2fa(current_password=old_pass),
                    timeout=90,
                )
            if ok:
                return {"ok": True, "action": "changed" if new_pass else "removed"}
            return {"ok": False, "error": "no_change"}

        except Exception as e:
            if 'PASSWORD_HASH_INVALID' in str(e).upper():
                return {"ok": False, "error": "invalid_password"}
            return {"ok": False, "error": type(e).__name__, "raw": str(e)[:120]}

    # PATCH (v2.6.2): تغییر یا حذف ایمیل بازیابی 2FA
    async def change_2fa_email(self, old_pass: str, new_email: str = "") -> dict:
        """
        تغییر ایمیل بازیابی 2FA.

        v2.19.4 (AUDIT-36 H3 — HIGH · بازنویسی کامل): پیاده‌سازیِ قبلی
        PasswordInputSettings را با کیوردهای ناموجود (flags/new_hint/new_email)
        می‌ساخت → TypeError قبل از هر درخواستی → «❌ خطا: TypeError» — مرده‌ی
        ۱۰۰٪. حالا الگوی رسمیِ edit_2fa تلثون: نوسازیِ salt (new_algo) +
        digest با همان رمزِ فعلی (رمز تغییر نمی‌کند؛ فقط ایمیل) + فیلدِ email
        با نامِ درست. سرور برای ایمیلِ جدید کد تأیید می‌فرستد
        (EmailUnconfirmedError) — تا تأیید، ایمیلِ قبلی فعّال می‌ماند؛ چون
        ویزاردِ فعلی مرحله‌ی کد ندارد، همین حالت را صادقانه برمی‌گردانیم.

        Args:
            old_pass: رمز فعلی (الزامی)
            new_email: ایمیل جدید (خالی پذیرفته نمی‌شود — حذفِ ایمیلِ بازیابی
            در API تلگرام جریانِ جدا و پیچیده‌تری دارد که عمداً وارد نشدیم)

        Returns:
            {"ok": True} یا {"ok": True, "pending_email_confirm": True,
            "code_length": N} یا {"ok": False, "error": "..."}
        """
        from telethon.tl.functions.account import (GetPasswordRequest,
                                                   UpdatePasswordSettingsRequest)
        from telethon.tl.types import account as _account_types
        from telethon.password import compute_check, compute_digest
        if not new_email:
            return {"ok": False, "error": "email_required",
                    "hint": "حذفِ ایمیل بازیابی پشتیبانی نمی‌شود — ایمیلِ جدید بفرست."}
        try:
            pwd = await asyncio.wait_for(
                self.client(GetPasswordRequest()), timeout=25
            )
            if not pwd or not pwd.has_password:
                return {"ok": False, "error": "no_password"}

            old_check = compute_check(pwd, old_pass)
            if old_check is None:
                return {"ok": False, "error": "invalid_password"}

            # الگوی edit_2fa (telethon/client/auth.py): salt تازه + digest با
            # همان رمز — سرور رمز را «به همان مقدار» دوباره ثبت می‌کند و
            # ایمیل را pending می‌کند.
            pwd.new_algo.salt1 += os.urandom(32)
            new_settings = _account_types.PasswordInputSettings(
                new_algo=pwd.new_algo,
                new_password_hash=compute_digest(pwd.new_algo, old_pass),
                hint=pwd.hint,
                email=new_email,
                new_secure_settings=None,
            )

            await asyncio.wait_for(
                self.client(UpdatePasswordSettingsRequest(
                    password=old_check,
                    new_settings=new_settings,
                )),
                timeout=60,
            )
            return {"ok": True}

        except Exception as e:
            _en = type(e).__name__
            if _en == "EmailUnconfirmedError":
                # کد به ایمیلِ جدید رفت؛ تا ConfirmPasswordEmail(code) زده
                # نشود، ایمیلِ قبلی فعّال است. مرحله‌ی کد در ویزاردِ پنل هنوز
                # وجود ندارد — وضعیت را شفاف برمی‌گردانیم تا UI درست بگوید.
                return {"ok": True, "pending_email_confirm": True,
                        "code_length": getattr(e, "code_length", None)}
            if 'PASSWORD_HASH_INVALID' in str(e).upper():
                return {"ok": False, "error": "invalid_password"}
            return {"ok": False, "error": _en, "raw": str(e)[:120]}

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

    # v2.12.24 (USER-REQUEST): محافظتِ ورود — به‌محض رسیدن کد ورود از
    # 777000، خودکار با send_code_request کد قبلی رو منقضی کن. این یعنی
    # حتی اگه هکر شماره داشته باشه و کد بگیره، کد فوراً نامعتبر می‌شه.
    _LOGIN_GUARD_COOLDOWN = 60.0  # ثانیه — برای جلوگیری از infinite loop

    async def _guard_invalidate_code(self, event, code: str) -> bool:
        """
        کد ورود رو منقضی کن با صدا زدن send_code_request.
        تلگرام وقتی کد جدید می‌فرسته، phone_code_hash قبلی رو باطل می‌کنه.
        پس کدی که هکر داره دیگر کار نمی‌کنه.

        v2.12.27: برمی‌گرداند True اگه invalidation موفق بود، False اگه نه.
        اگه False باشه، _on_incoming به _maybe_capture_login_code
        fall through می‌کنه تا کاربر کدش رو بگیره.
        """
        import time as _t
        now = _t.time()
        # cooldown: اگه کمتر از ۶۰ ثانیه از آخر invalidation گذشته، skip.
        # این از infinite loop جلوگیری می‌کنه: send_code_request یه کد
        # جدید می‌فرسته → اون کد هم از 777000 میاد → ولی cooldown جلوی
        # invalidation مجدد رو می‌گیره.
        # v2.12.25 (DEEP-10-LOGIC #1): هم _flood_until رو چک کن — اگه در
        # recovery هستیم، skip کن تا FloodWait تشدید نشه.
        if now - self._login_guard_last_invalidate < self._LOGIN_GUARD_COOLDOWN:
            return False
        if self._flood_until and now < self._flood_until:
            return False  # در FloodWait recovery — skip کن

        phone = self.cfg.get("phone") or ""
        if not phone:
            print(f"⚠️ [{self.tag}] login guard: phone not found in config")
            return False
        # v2.12.27 (HUNT-1 #4): cooldown رو بعد از phone check ست کن
        self._login_guard_last_invalidate = now

        # v2.12.25 (DEEP-6-ERRORS #7): پیامِ کد رو بعد از موفقیتِ
        # invalidation پاک کن — نه قبل. قبلاً اگه send_code_request fail
        # می‌شد، کد پاک می‌شد ولی هنوز معتبر بود → کاربر کد رو از دست
        # می‌داد ولی هکر می‌تونست استفاده کنه.
        _invalidated = False
        try:
            await asyncio.wait_for(
                self.client.send_code_request(phone),
                timeout=15,
            )
            _invalidated = True
            print(f"🔒 [{self.tag}] login guard: code '{code}' INVALIDATED — "
                  f"new code sent (old code no longer works)")
        except errors.FloodWaitError as _fwe:
            _wait = (_fwe.seconds or 30) + 2
            self._flood_until = now + _wait
            # v2.12.25: cooldown رو slide کن تا بعد از FloodWait دوباره
            # تلاش نکنه
            self._login_guard_last_invalidate = now + _wait
            print(f"⏳ [{self.tag}] login guard: FloodWait {_wait}s — "
                  f"code NOT invalidated")
        except Exception as _e:
            print(f"⚠️ [{self.tag}] login guard: invalidation failed: "
                  f"{type(_e).__name__}: {_e}")

        # فقط اگه invalidation موفق بود، پیام رو پاک کن
        if _invalidated:
            try:
                await event.delete()
            except Exception:
                pass
        # v2.12.27: return the result
        return _invalidated

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
                # v2.19.4 (AUDIT-36 M11): گیتِ ضدبن وقتی ارسال را رد می‌کند،
                # بدونِ exception مقدارِ None برمی‌گرداند — این یعنی «تحویل
                # نشد». قبلاً delivered=True می‌شد و کد بی‌صدا گم می‌شد؛ حالا
                # مقصدِ بعدی / fallback امتحان می‌شود (کد در تاریخچه‌ی 777000
                # موجود است و دکمه‌ی «📲 دریافت کد» هم می‌تواند بخواندش).
                _code_sent = await self.client.send_message(t, text)
                if _code_sent is None:
                    print(f"🛡️ [{self.tag}] ارسالِ کد به {t} توسطِ گیتِ ضدبن رد شد — مقصدِ بعدی")
                    continue
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
            # v2.12.24: محافظتِ ورود — اگه روشن باشه و این پیام کد ورود
            # باشه، فوراً کد رو با send_code_request منقضی کن. این کار
            # قبل از capture انجام می‌شه چون اگه guard روشنه، نباید کد رو
            # به کسی تحویل بدیم — باید نامعتبرش کنیم.
            if self.login_code_guard:
                _code = self._extract_login_code(event.raw_text or "")
                if _code:
                    _ok = await self._guard_invalidate_code(event, _code)
                    if _ok:
                        return  # کد واقعاً منقضی شد — ادامه نده
                    # v2.12.27 (HUNT-1 #4): invalidation ناموفق بود —
                    # fall through to capture تا کاربر کدش رو بگیره
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
            except errors.FloodWaitError as _fwe:
                # v2.14.2 (P2-10 / §10.1 + §20.8): FloodWait هرگز بی‌صدا
                # بلعیده نمی‌شود — _flood_until ست می‌شود تا همه‌ی مسیرهای
                # ارسالِ این اکانت تا پایان دوره‌ی flood گیت شوند (همان
                # الگوی پاسخ خودکار در همین هندلر).
                _wait = (_fwe.seconds or 30) + 2
                self._flood_until = time.time() + _wait
                print(f"⏳ [enemy_reply:{self.tag}] FloodWait {_wait}s (flood_until coordinated)")
            except Exception:
                pass

        # BUG-1 (P1-4): پاسخ خودکار (auto-reply) — این قابلیت از طریق پنل وب
        # به کاربران فروخته می‌شود ولی find_auto_reply هیچ‌جا صدا زده نمی‌شد
        # و بنابراین هرگز کار نمی‌کرد. فقط برای پیام متنی از کاربر واقعی
        # (نه پیام سرویسِ 777000 و نه خودِ اکانت). عمداً قبل از «سکوت» قرار
        # گرفته — مثلِ الگوی «دشمن» بالا: سکوت فقط پیام را برای نمایش حذف
        # می‌کند و پاسخِ تنظیم‌شده‌ی مالک همچنان قابلِ ارسال است.
        # (Auto-reply wiring — BUG-1; fires before the silence-delete.)
        # user_id = owner_user_id اکانت از config تا فقط پاسخ‌های خودِ مالکِ
        # همین اکانت match شوند (auto_replies.user_id = آیدی پنلیِ مالک).
        if (
            self.enabled
            and sid != self.TELEGRAM_SERVICE_ID
            and sid != self.my_id
            # v2.19.4 (AUDIT-36 L5 — LOW/امنیتی): فقط چتِ خصوصی — قبلاً بدون
            # فیلترِ نوعِ چت، اگر کسی در یک گروهِ مشترک کلیدواژه را می‌گفت،
            # متنِ پاسخِ ساخته‌شده برای پیوی عمومی در گروه پست می‌شد (نشتِ
            # محتوای خصوصی + رفتار اسپم‌گونه). broadcast/گروه حالا مستثنی‌اند؛
            # اگر روزی «پاسخ در گروه» خواسته شد، باید toggle صریح اضافه شود.
            and event.is_private
            and (event.raw_text or "").strip()
            and not (self._flood_until and time.time() < self._flood_until)
        ):
            try:
                # v2.14.2 (P2-9 FLOW-4 edge): مالکیت اکانت ۳ اثبات دارد
                # (owner_user_id / tg_user_id / my_id — رجوع کنید به
                # account_belongs_to). ردیف‌های auto_replies با uid پنلِ
                # سازنده ذخیره می‌شوند؛ اگر کاربر فقط از مسیر tg_user_id
                # مالک باشد، قبلاً هرگز match نمی‌شد. حالا هر دو نامزد
                # امتحان می‌شوند (اول مالکِ صریح، بعد اکانتِ خودِ کاربر).
                _cfg_ar = self.cfg if isinstance(self.cfg, dict) else {}
                _ar_reply = None
                for _ar_uid in (_cfg_ar.get("owner_user_id"), _cfg_ar.get("tg_user_id")):
                    if not _ar_uid:
                        continue
                    _ar_reply = find_auto_reply(self.tag, event.raw_text or "", _ar_uid)
                    if _ar_reply:
                        break
                if _ar_reply:
                    # مسیر امنِ ارسالِ این کلاس: client.send_message که با
                    # _install_offline_preserving_sends گیت می‌شود
                    # (flood/daily-cap/cooldown) — مثل ردیاب و تبچی.
                    await self.client.send_message(event.chat_id, _ar_reply)
            except errors.FloodWaitError as _fwe:
                _wait = (_fwe.seconds or 30) + 2
                self._flood_until = time.time() + _wait
                print(f"⏳ [auto_reply:{self.tag}] FloodWait {_wait}s — پاسخ خودکار ارسال نشد (flood_until coordinated)")
            except Exception as e:
                print(f"⚠️ [auto_reply:{self.tag}] خطا در پاسخ خودکار: {type(e).__name__}")

        # سکوت — سیاست واحد: فقط وقتی سلف روشن است اعمال می‌شود و پیامِ سکوت‌شده هرگز auto-read نمی‌شود
        if self.enabled and self._is_silenced(event.chat_id, event.is_private):
            try:
                await self.client.delete_messages(event.chat_id, [event.id], revoke=True)
            except Exception:
                pass
            return

        # تیک خودکار
        do_read = False
        if self.enabled:
            is_broadcast_only = bool(event.is_channel and not event.is_group)
            if event.is_private and self.auto_read_pv:
                do_read = True
            elif is_broadcast_only and self.auto_read_channel:
                do_read = True
            elif event.is_group and self.auto_read_group:
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
                owner_dir = os.path.join(DOWNLOADS_DIR, str(self.cfg.get("owner_user_id") or self.tag))
                os.makedirs(owner_dir, mode=0o700, exist_ok=True)
                _chmod_private(owner_dir, 0o700)
                path = os.path.join(owner_dir, f"auto_{secrets.token_hex(8)}.{ext}")
                await event.download_media(file=path)
                _chmod_private(path, 0o600)
                _ttl_sent = None
                try:
                    _ttl_sent = await self.client.send_file(
                        "me", path,
                        caption=f"🔥 خودکار | از {sender} | ⏳{ttl}s")
                finally:
                    # v2.19.4 (AUDIT-36 M11 — MEDIUM): اگر گیتِ ضدبن ارسال را
                    # رد کرد (None)، فایلِ محلی پاک نمی‌شود — محتوای تایم‌دار
                    # فقط یک‌بار زندگی می‌کند و قبلاً با پاک‌شدنِ بی‌صدا برای
                    # همیشه از بین می‌رفت. فایل برای ارسالِ دستی/تلاشِ بعدی
                    # می‌ماند و مسیرش در لاگ ثبت می‌شود.
                    if _ttl_sent is not None and os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception:
                            pass
                if _ttl_sent is None:
                    print(f"🛡️ [{self.tag}] ارسالِ رسانه‌ی تایم‌دار توسطِ گیتِ ضدبن رد شد — فایل حفظ شد: {path}")

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
        except errors.FloodWaitError as _fwe:
            # v2.14.2 (P2-10 / §10.1 + §20.8): نوتیف ردیاب روی هر ادیتِ
            # پیامِ ردیابی‌شده فعال است؛ FloodWait بی‌صدا بلعیده نمی‌شود —
            # _flood_until ست می‌شود تا ارسال‌های بعدی این اکانت گیت شوند.
            _wait = (_fwe.seconds or 30) + 2
            self._flood_until = time.time() + _wait
            print(f"⏳ [tracker:{self.tag}] FloodWait {_wait}s در نوتیف ادیت (flood_until coordinated)")
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
        except errors.FloodWaitError as _fwe:
            # v2.14.2 (P2-10 / §10.1 + §20.8): همان الگوی نوتیف ادیت —
            # FloodWait بی‌صدا بلعیده نمی‌شود؛ _flood_until ست می‌شود.
            _wait = (_fwe.seconds or 30) + 2
            self._flood_until = time.time() + _wait
            print(f"⏳ [tracker:{self.tag}] FloodWait {_wait}s در نوتیف حذف (flood_until coordinated)")
        except Exception:
            pass

        try:
            html_path = await self._build_chat_html(chat_id, sender_name, deleted_ids=set(deleted_ids))
            if html_path:
                sent_res = None
                for _attempt in range(2):
                    await self._wait_outbound_cooldown()
                    try:
                        sent_res = await self.client.send_file(
                            "me", html_path,
                            caption=f"🗑 صفحه‌ی چت با «{sender_name}» — پیام‌های حذف‌شده با رنگ مشخص شده‌اند"
                        )
                        break
                    except errors.FloodWaitError as _fwe:
                        _wait = (_fwe.seconds or 30) + 2
                        self._flood_until = time.time() + _wait
                        print(f"⏳ [tracker:{self.tag}] FloodWait {_wait}s در ارسال HTML ردیاب")
                        await asyncio.sleep(_wait)
                if sent_res is not None:
                    try:
                        os.remove(html_path)
                    except OSError:
                        pass
                    for e in deleted_entries:
                        cache_entry = self._msg_cache.get((chat_id, e["msg_id"]))
                        if cache_entry is not None:
                            # v2.19.4 (AUDIT-36 M10 — MEDIUM): قبلاً خودِ dict
                            # به _forget_msg_bytes داده می‌شد → dict غیرقابلِ
                            # hash → TypeError پنهان در except بیرونی → نه
                            # شمارنده‌ی RAM کم می‌شد و نه media_bytes خالی می‌شد
                            # (نشتِ تدریجیِ RAM تا ۸MB برای هر پیامِ حذف‌شده).
                            # کلیدِ درست tuple (chat_id, msg_id) است.
                            self._forget_msg_bytes((chat_id, e["msg_id"]))
                            cache_entry["media_bytes"] = None
                else:
                    print(f"⚠️ [{self.tag}] ارسال فایل HTML ردیاب ناموفق بود — فایل حفظ شد: {html_path}")
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
                # PATCH (v2.0.9 ANTI-BAN): قبلاً `+ 0.1` ثابت بود — یعنی
                # همه‌ی اکانت‌ها در ثانیه‌ی ۰.۱ بعد از minute boundary هم‌زمان
                # UpdateProfileRequest می‌زدن. این الگوی synchronized به‌وضوح
                # bot-magnet است و تلگرام به‌سادگی تشخیصش می‌دهد. حالا هر
                # اکانت یک offset پایدار بر اساس hash تگش دارد (بین ۰ تا ۱۵
                # ثانیه) + jitter اضافی در هر iteration (۰.۵ تا ۲ ثانیه).
                # این الگو هرگز detectable نیست چون offset per-tag پایدار
                # است ولی بین اکانت‌ها متفاوت.
                import hashlib as _hl
                _tag_offset = (int(_hl.md5(self.tag.encode()).hexdigest(), 16) % 1500) / 100.0  # 0-15s
                _iter_jitter = random.uniform(0.5, 2.0)
                await asyncio.sleep(max(0.1, seconds_left + _tag_offset + _iter_jitter))
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
                # PATCH (v2.0.9 ANTI-BAN): jitter + tag-based offset مثل
                # _name_loop — الگوی synchronized برای ۱۰۰+ اکانت خطرناک
                # است. offset بر اساس tag پایدار ولی بین اکانت‌ها متفاوت.
                import hashlib as _hl
                _tag_offset = (int(_hl.md5(("bio_" + self.tag).encode()).hexdigest(), 16) % 1500) / 100.0
                _iter_jitter = random.uniform(0.5, 2.0)
                await asyncio.sleep(max(0.1, seconds_left + _tag_offset + _iter_jitter))
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
                #
                # PATCH (v2.0.9 ANTI-BAN): قبلاً `sleep(50)` / `sleep(180)`
                # ثابت بود — همه‌ی اکانت‌ها در ثانیه‌ی ۵۰ هم‌زمان presence
                # update می‌زدن. حالا jitter اضافه کردیم.
                if result is None and (not self.client or not self.client.is_connected()):
                    await asyncio.sleep(5)
                elif self.online_enabled:
                    await asyncio.sleep(50 + random.uniform(-10, 10))
                else:
                    await asyncio.sleep(180 + random.uniform(-20, 20))
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

    async def _wait_outbound_cooldown(self) -> None:
        """انتظار هوشمند (warmup-aware) برای عبور از فاصله‌ی اجباری _gate_outbound قبل از ارسال فایل."""
        now = time.time()
        if self._flood_until and now < self._flood_until:
            await asyncio.sleep(max(0.0, self._flood_until - now) + 0.1)
            now = time.time()
        cd = OUT_COOLDOWN_SEC / (WARMUP_RATE_MULTIPLIER if now < self._warmup_until else 1.0)
        if self._out_last_ts and (now - self._out_last_ts) < cd:
            await asyncio.sleep(cd - (now - self._out_last_ts) + 0.05)

    def _gate_outbound(self) -> bool:
        """v2.9.1: قبل از هر send_message/file صدا زده می‌شه.
        برمی‌گردونه True اگه مجاز باشه، False اگه باید skip بشه.

        سه چک:
        ۱. flood_until: اگه در FloodWait recovery هستیم، همه‌چیز block
        ۲. daily cap: OUT_DAILY_MAX پیام در روز
        ۳. cooldown: OUT_COOLDOWN_SEC بین پیام‌ها
        (در warmup: نرخ‌ها با WARMUP_RATE_MULTIPLIER ضرب می‌شن)
        """
        import time as _t
        now = _t.time()
        # flood recovery
        if self._flood_until and now < self._flood_until:
            return False
        # daily window reset
        if not self._out_window_start or (now - self._out_window_start) > 86400:
            self._out_window_start = now
            self._out_today = 0
        # daily cap (reduced during warmup)
        cap = int(OUT_DAILY_MAX * (WARMUP_RATE_MULTIPLIER if now < self._warmup_until else 1.0))
        if self._out_today >= cap:
            return False
        # cooldown (longer during warmup)
        cd = OUT_COOLDOWN_SEC / (WARMUP_RATE_MULTIPLIER if now < self._warmup_until else 1.0)
        if self._out_last_ts and (now - self._out_last_ts) < cd:
            return False
        # all checks passed — update counters
        self._out_today += 1
        self._out_last_ts = now
        return True

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

        async def _notify_ratelimit_drop(kind: str):
            now_ts = time.time()
            self._last_ratelimit_drop_ts = now_ts
            print(
                f"⚠️ [ratelimit:{self.tag}] ارسال ({kind}) به دلیل محدودیت نرخ/ضدبن متوقف شد "
                f"(out_today={self._out_today}, flood_until={self._flood_until:.0f})"
            )
            last_notif = getattr(self, "_last_ratelimit_notif_ts", 0.0)
            if now_ts - last_notif >= 60.0:
                self._last_ratelimit_notif_ts = now_ts
                try:
                    await orig_send_message(
                        "me",
                        f"⚠️ [ضدبن/محدودیت نرخ] یک پیام خروجی ({kind}) به دلیل سقف ارسال یا فاصله‌ی ضدبن متوقف شد."
                    )
                except Exception:
                    pass

        async def wrapped_send_message(*args, **kwargs):
            if not self._gate_outbound():
                await _notify_ratelimit_drop("message")
                return None
            result = await orig_send_message(*args, **kwargs)
            await self._preserve_offline()
            return result

        async def wrapped_send_file(*args, **kwargs):
            if not self._gate_outbound():
                await _notify_ratelimit_drop("file")
                return None
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

                # PATCH (v2.0.9 ANTI-BAN): قبلاً `interval * 60` ثابت بود
                # — دو reseller با همون interval دقیقاً هم‌زمان fire می‌کردن.
                # حالا jitter ±10% اضافه شده. jitter با _persist هم کار
                # می‌کنه چون فقط next_run_at رو جابجا می‌کنه، نه interval رو.
                _jitter = self.tabchi_interval * 60 * random.uniform(-0.1, 0.1)
                self.tabchi_next_run_at = time.time() + self.tabchi_interval * 60 + _jitter
                self._persist(tabchi_next_run_at=self.tabchi_next_run_at)
            except asyncio.CancelledError:
                raise
            except errors.FloodWaitError as e:
                import time as _t
                self._flood_until = _t.time() + (e.seconds or 30) + FLOOD_RECOVER_GRACE
                print(f"⏳ [{self.tag}] FloodWait {e.seconds}s در tabchi")
                await asyncio.sleep((e.seconds or 30) + 5)
                _jitter = self.tabchi_interval * 60 * random.uniform(-0.1, 0.1)
                self.tabchi_next_run_at = time.time() + self.tabchi_interval * 60 + _jitter
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

    async def _power_off_full(self) -> None:
        """خاموش‌سازی کامل سلف‌بات و توقف همه‌ی حلقه‌ها و فلگ‌های پس‌زمینه."""
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
        self.enemies = {}
        self._persist_enemies()
        await self._stop_time_loops()
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

    async def _handle(self, event, text: str):
        if not text:
            return
        # M-11: دستورات مدیریتی سلف در چت‌های گروهی/کانال عمومی اجرا نشوند (مگر دستورات ریپلای/ابزار مجاز)
        _GROUP_SAFE_CMDS = {
            "پینگ", "ping", "تایم", "time", "ایدی", "بلاک", "آنبلاک", "ذخیره",
            "فوروارد", "مشخصات", "سنجاق", "دشمن روشن", "دشمن خاموش",
            "سکوت پیوی روشن", "سکوت پیوی خاموش", "انتخاب تبچی",
            *_DICE_MAP.keys(), *_PRICE_MAP.keys(), "طلا",
        }
        if (event.is_group or event.is_channel) and text not in _GROUP_SAFE_CMDS and not text.startswith(("حذف", "انتخاب تبچی")):
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
                await self._power_off_full()
                await event.edit("✅ سلف‌بات **خاموش** — تمام قابلیت‌ها غیرفعال شدند")
                return

            # ─── تایم ────────────────────────────────────
            if text == "تایم روشن":
                if not self.enabled:
                    await event.edit("❌ ابتدا `سلف روشن` بزنید")
                    return
                # v2.12.21 (QA7-USER8 BUG#1): قبلاً False ست می‌شد که یه باگِ
                # v2.12.5 بود — _name_loop بعد از یک آپدیت exit می‌کرد. حالا
                # درست True ست می‌شه.
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
                await event.edit("✅ آنلاین خودکار غیرفعال شد")
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
                # v2.12.21 (QA7-USER8 BUG#2): قبلاً False ست می‌شد — باگِ v2.12.5
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
                await event.edit("✅ تیک خودکار پیوی غیرفعال شد")
                return

            if text == "تیک گروه روشن":
                self.auto_read_group = True
                self._persist(auto_read_group=True)
                await event.edit("✅ تیک خودکار در **گروه** فعال شد")
                return
            if text == "تیک گروه خاموش":
                self.auto_read_group = False
                self._persist(auto_read_group=False)
                await event.edit("✅ تیک خودکار گروه غیرفعال شد")
                return

            if text == "تیک کانال روشن":
                self.auto_read_channel = True
                self._persist(auto_read_channel=True)
                await event.edit("✅ تیک خودکار در **کانال** فعال شد")
                return
            if text == "تیک کانال خاموش":
                self.auto_read_channel = False
                self._persist(auto_read_channel=False)
                await event.edit("✅ تیک خودکار کانال غیرفعال شد")
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
                if r is None:
                    await event.edit("❌ پیام یافت نشد")
                    return
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
                if r is None:
                    await event.edit("❌ پیام یافت نشد")
                    return
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
                if r is None:
                    await event.edit("❌ پیام یافت نشد")
                    return
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
                await event.edit(f"✅ تبچی: هر {mins} دقیقه")
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
                await event.edit(f"✅ نام پایه: {new}")
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
                    await event.edit("ℹ️ روی عکس ریپلای کن")
                    return
                r = await event.get_reply_message()
                if r is None:
                    await event.edit("❌ پیام یافت نشد")
                    return
                if not r.photo:
                    await event.edit("❌ عکس ندارد")
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
                await event.edit("✅ عکس پروفایل به‌روزرسانی شد")
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
                    await event.edit("⏳ بازی دایس در حال اجراست.")
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
                    await event.edit("⏳ سرور پاسخ نداد")
                    return
                except Exception as e:
                    await event.edit(_friendly_error(e, "selfbot_cmd"))
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
                    await event.edit("⏳ سرور پاسخ نداد")
                    return
                except Exception as e:
                    await event.edit(_friendly_error(e, "selfbot_cmd"))
                    return

                if not p18 and not p24:
                    await event.edit("❌ دریافت قیمت ناموفق بود")
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
                await event.edit("...")
                ms = int((time.perf_counter() - t0) * 1000)
                await event.edit(f"`{ms}ms`")

            elif text in ("تایم", "time"):
                now = iran_now().strftime("%Y-%m-%d %H:%M:%S")
                await event.edit(f"🕒 {now}\n⏱ {self._uptime()}")

            elif text == "ریستارت":
                if self._restart_task and not self._restart_task.done():
                    await event.edit("⏳ ری‌استارت قبلاً در صف است.")
                    return
                await event.edit("⏳ ری‌استارت در ۳ ثانیه...")
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
                    await event.edit("⛔ حذف در کانال غیرفعال است")
                    return
                if len(parts) == 1:
                    if not event.is_reply:
                        await event.edit("ℹ️ مثال: حذف 5 یا روی پیام ریپلای کن")
                        return
                    r = await event.get_reply_message()
                    if r is None:
                        await event.edit("❌ پیام یافت نشد")
                        return
                    try:
                        await event.delete()
                        await self.client.delete_messages(event.chat_id, r.id, revoke=True)
                    except Exception:
                        pass
                    return
                try:
                    cnt = int(parts[1])
                except ValueError:
                    await event.edit("ℹ️ مثال: حذف 5")
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
                    await event.edit(_friendly_error(e, "selfbot_cmd"))
                return

            elif text == "ایدی":
                if event.is_reply:
                    r = await event.get_reply_message()
                    if r is None:
                        await event.edit("❌ پیام یافت نشد")
                        return
                    name = getattr(r.sender, 'first_name', 'نامشخص')
                    await event.edit(f"🆔 `{r.sender_id}` — {name}")
                else:
                    await event.edit("ℹ️ برای دیدن آیدی، روی یک پیام ریپلای کن و «ایدی» را بفرست")
                return

            elif text == "بلاک":
                if event.is_reply:
                    r = await event.get_reply_message()
                    if r is None:
                        await event.edit("❌ پیام یافت نشد")
                        return
                    try:
                        uid = r.sender_id
                        ent = await self.client.get_input_entity(uid)
                        await self.client(BlockRequest(id=ent))
                        await event.edit(f"🚫 بلاک شد: {uid}")
                    except Exception as e:
                        await event.edit(_friendly_error(e, "selfbot_cmd"))
                else:
                    await event.edit("ℹ️ روی پیام کاربر ریپلای کن")
                return

            elif text == "آنبلاک":
                if event.is_reply:
                    r = await event.get_reply_message()
                    if r is None:
                        await event.edit("❌ پیام یافت نشد")
                        return
                    try:
                        ent = await self.client.get_input_entity(r.sender_id)
                        await self.client(UnblockRequest(id=ent))
                        await event.edit("✅ رفع بلاک شد")
                    except Exception as e:
                        await event.edit(_friendly_error(e, "selfbot_cmd"))
                else:
                    await event.edit("ℹ️ روی پیام کاربر ریپلای کن")
                return

            elif text == "ذخیره":
                if not event.is_reply:
                    await event.edit("ℹ️ روی رسانه تایم‌دار ریپلای کن")
                    return
                r = await event.get_reply_message()
                if r is None:
                    await event.edit("❌ پیام یافت نشد")
                    return
                ttl = None
                if r.photo:
                    ttl = (getattr(r.photo, 'ttl_seconds', None)
                           or getattr(r.media, 'ttl_seconds', None))
                elif r.video:
                    ttl = (getattr(r.video, 'ttl_seconds', None)
                           or getattr(r.media, 'ttl_seconds', None))
                if not ttl:
                    await event.edit("❌ تایم‌دار نیست")
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
                await event.edit("✅ ذخیره شد")
                return

            # v2.12.17 (USER-REQUEST): ارسال دسته‌جمعی به همه‌ی پیوی/گروه‌ها
            # کاربر روی یه پیام ریپلای می‌کنه و می‌نویسه «ارسال به پیوی» یا
            # «ارسال به گروه». ربات اون پیام رو به همه‌ی PVها یا گروه‌های
            # کاربر فوروارد می‌کنه.
            # v2.12.18 (QA6-BROADCAST): FIX critical bugs:
            #   1. wrap در _spawn_bg تا از ۹۰ثانیه‌ی _safe_handler cancel نشه
            #   2. cooldown رو بلافاصله بعد از check ست کن (نه آخرِ loop)
            #   3. از _gate_outbound برای respect کردنِ anti-ban gate استفاده کن
            #   4. _flood_until رو در FloodWait به‌روز کن
            #   5. فقط در chat خودِ کاربر (is_private) کار کنه
            #   6. delay تصادفی ۱-۳ ثانیه
            elif text in ("ارسال به پیوی", "ارسال به گروه", "ارسال به pv", "ارسال به gp"):
                # v2.12.21 (QA7-USER7): فقط در Saved Messages (chat با خود)
                # کار کنه. قبلاً is_private چک می‌شد که شامل PV با هر کس
                # می‌شد — یعنی کاربر می‌تونست تو PV یه دوست دستور رو بزنه و
                # اون دوست هم متنِ دستور و آمار نهایی رو می‌دید. حالا فقط
                # در Saved Messages (self.my_id) مجاز هست.
                if event.chat_id != self.my_id:
                    await event.edit("ℹ️ این دستور فقط در Saved Messages (پیوی خودت) کار می‌کنه.")
                    return
                if not event.is_reply:
                    await event.edit("ℹ️ روی پیام مدنظر ریپلای کن و بنویس:\n• `ارسال به پیوی` (همه PV)\n• `ارسال به گروه` (همه گروه‌ها)")
                    return
                r = await event.get_reply_message()
                if r is None:
                    await event.edit("❌ پیام یافت نشد")
                    return

                # تعیین نوع: pv یا group
                _target_type = "pv" if "پیوی" in text or "pv" in text.lower() else "group"

                # rate limit: ۶۰ ثانیه cooldown بین هر بار استفاده از این
                # دستور. اگه کمتر از این فاصله دوباره بزنه، reject می‌شه.
                # v2.12.18: cooldown بلافاصله ست می‌شه (نه آخرِ loop) تا اگه
                # broadcast وسط کار cancel بشه، کاربر نتونه فوراً دوباره بزنه.
                import time as _time_mod
                _now = _time_mod.time()
                _last_broadcast = getattr(self, "_last_broadcast_at", 0.0)
                _BROADCAST_COOLDOWN = 60.0
                # v2.12.29 (DEEP-4 #2): daily broadcast cap — حداکثر ۵
                # broadcast در روز per SelfBot. این از mass-ban جلوگیری
                # می‌کنه.
                _BROADCAST_DAILY_MAX = 5
                # v2.12.31 (DEBUG-1 HIGH-2): Broadcast concurrency check.
                # بدون این چک، کاربر می‌توانست 5 broadcast را به‌صورت همزمان
                # اجرا کند (هر کدام 30 دقیقه طول می‌کشید) → 5000 پیام در 30
                # دقیقه = mass FloodWait → ban. حالا: فقط 1 broadcast همزمان
                # در هر اکانت مجاز است.
                _existing_task = getattr(self, "_broadcast_task", None)
                if _existing_task is not None and not _existing_task.done():
                    try:
                        await event.edit(
                            "⏳ یک ارسال قبلی هنوز در حال اجراست. لطفاً تا پایان "
                            "آن صبر کن. (می‌توانی با /stop آن را لغو کنی.)"
                        )
                    except Exception:
                        pass
                    return
                _broadcast_day = int(_now // 86400)
                _broadcast_today = getattr(self, "_broadcast_today_count", 0)
                _broadcast_day_id = getattr(self, "_broadcast_day_id", 0)
                if _broadcast_day_id != _broadcast_day:
                    _broadcast_day_id = _broadcast_day
                    _broadcast_today = 0
                if _broadcast_today >= _BROADCAST_DAILY_MAX:
                    await event.edit(
                        f"⏳ سقف روزانه‌ی ارسال ({_BROADCAST_DAILY_MAX} بار) "
                        f"تکمیل شده. فردا دوباره تلاش کن."
                    )
                    return
                # BUG-13 (P1-4, §20.9): شمارنده‌ی روزانه فقط بعد از همه‌ی چک‌های
                # رد شدن increment می‌شود — قبلاً قبل از چکِ cooldown زیاد می‌شد
                # و یک درخواستِ ردشده سهمیه‌ی روزانه (از ۵ broadcast) را می‌سوزاند.
                if _now - _last_broadcast < _BROADCAST_COOLDOWN:
                    _remain = int(_BROADCAST_COOLDOWN - (_now - _last_broadcast))
                    await event.edit(f"⏳ لطفاً {_remain} ثانیه دیگر صبر کن و دوباره امتحان کن.")
                    return
                self._broadcast_today_count = _broadcast_today + 1
                self._broadcast_day_id = _broadcast_day_id
                # v2.12.18: ست کنِ فوریِ cooldown
                self._last_broadcast_at = _now

                # شروع broadcast در پس‌زمینه — مهم: خارج از پوششِ ۹۰ ثانیه‌ی
                # _safe_handler اجرا می‌شه. با ۱۰۰۰ تا × ۲ ثانیه = ۳۰+ دقیقه،
                # اگه داخل _safe_handler باشه بعد از ۹۰ ثانیه cancel می‌شد و
                # کاربر روی «در حال ارسال» گیر می‌کرد.
                # v2.12.28: task رو روی self._broadcast_task ذخیره کن
                # تا در shutdown/reconnect بتونیم cancelش کنیم.
                self._broadcast_task = _spawn_bg(
                    self._do_broadcast(event, r, _target_type),
                    f"broadcast:{self.tag}"
                )
                await event.edit(
                    f"📨 شروع ارسال به {'پیوی‌ها' if _target_type == 'pv' else 'گروه‌ها'}...\n"
                    f"⏳ صبر کن، ممکنه چند دقیقه طول بکشه.\n"
                    f"📊 گزارشِ نهایی بعداً ارسال می‌شه."
                )
                return

            elif text == "فوروارد":
                if event.is_reply:
                    r = await event.get_reply_message()
                    if r is None:
                        await event.edit("❌ پیام یافت نشد")
                        return
                    await r.forward_to("me")
                    await event.edit("✅ فوروارد شد")
                else:
                    await event.edit("ℹ️ ریپلای کنید")
                return

            elif text == "مشخصات":
                if event.is_reply:
                    r = await event.get_reply_message()
                    if r is None:
                        await event.edit("❌ پیام یافت نشد")
                        return
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
                        await event.edit(_friendly_error(e, "selfbot_cmd"))
                else:
                    await event.edit("ℹ️ ریپلای کنید")
                return

            elif text == "سنجاق":
                if not event.is_reply:
                    await event.edit("ℹ️ روی پیام ریپلای کن")
                    return
                try:
                    reply_msg = await event.get_reply_message()
                    await self.client.pin_message(event.chat_id, reply_msg.id)
                    await event.edit("📌 سنجاق شد")
                except errors.ChatAdminRequiredError:
                    await event.edit("⛔ دسترسی ادمین لازم است")
                except Exception as e:
                    await event.edit(_friendly_error(e, "selfbot_cmd"))
                return

        except Exception as e:
            print(f"❌ [{self.tag}/{cmd}]: {e}")
            try:
                await event.edit(_friendly_error(e, "selfbot_cmd"))
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
                    print(f"⚠️ [{self.tag}] دایس {emoji} خطا در ارسال آزمایشی (توقف فوری): {e}")
                    return

                valid = [m for m in results if not isinstance(m, Exception)]
                flood_errors = [m for m in results if isinstance(m, errors.FloodWaitError)]
                other_errors = [
                    m for m in results
                    if isinstance(m, Exception) and not isinstance(m, errors.FloodWaitError)
                ]
                if other_errors and not valid:
                    print(f"⚠️ [{self.tag}] دایس {emoji} توقف فوری به دلیل خطا: {other_errors[0]}")
                    return

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
                    wait_s = max(getattr(e, "seconds", 2) for e in flood_errors)
                    await asyncio.sleep(wait_s + random.uniform(1.5, 3.5))
                else:
                    await asyncio.sleep(random.uniform(0.65, 1.85))

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
                    # PATCH (v2.0.10): notify OWNER + increment ban counter
                    await self._on_fatal_auth(str(e), exc=e)
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
                    # PATCH (v2.0.10): notify OWNER + increment ban counter
                    await self._on_fatal_auth(str(e), exc=e)
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
        # v2.12.28 (HUNT-2 #1): broadcast task رو cancel کن در shutdown.
        # CancelledError handler در _do_broadcast پیام «ناقص متوقف شد»
        # به Saved Messages می‌فرسته.
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            await asyncio.gather(self._broadcast_task, return_exceptions=True)
            self._broadcast_task = None

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
        # PATCH (v2.2.0 REGRESSION FIX): re-add None-check که در commit
        # 59a8baf (revert to v2.0) حذف شده بود ولی commit message صریحاً
        # نوشته بود «can be re-applied on top of v2.0 in a future commit
        # if needed». حالا re-apply می‌کنیم چون بدون این check، اگر
        # start() شکست بخوره و self.client = None بمونه، stop() در هر
        # finally بلوک ۳ AttributeError لاگ می‌کنه (disconnect, save,
        # close) و خطاهای نمایشی در journalctl تولید می‌کنه.
        if self.client is None:
            # تسک‌های پس‌زمینه‌ی مربوط به اکانت ممکنه هنوز زنده باشن —
            # بدون اطمینان از cancel شدنشون، تسک‌های مرده روی event loop
            # باقی می‌مونن.
            await self._cancel_background_tasks(destructive_tabchi=True)
            self._clear_tracker_cache()
            return
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

