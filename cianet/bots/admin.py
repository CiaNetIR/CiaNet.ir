"""AdminBot — پنل مدیریت اکانت‌های سلف (ویزارد لاگین، تنظیمات، امنیت).

این فایل به‌صورت مکانیکی از main.py تک‌فایلی تفکیک شده است (v2.16.0).
بدنه‌ی کلاس‌ها بایت‌به‌بایت همان main.py است؛ فقط هدرِ import تولید شده.
"""

# stdlib / third-party — همان importهای اصلی main.py
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.account import ResetPasswordRequest
from telethon import TelegramClient
from telethon.tl.functions.account import UpdateStatusRequest
import asyncio
from datetime import datetime
from telethon import errors
from telethon import events
import json
import os
import re
import secrets
import tempfile
import time
from datetime import timedelta
from datetime import timezone

# هسته‌ی مشترک — ثابت‌ها/توابع مشترک
from cianet.core import (
    ACCOUNTS,
    ADMIN_BOT_SESSION_NAME,
    ADMIN_BOT_TOKEN,
    ADMIN_ID,
    ADMIN_LIST_FILE,
    BACKUP_HOURS_IRAN,
    BOT_STATUS,
    bot_error_alert_text,
    CAP_ACCOUNT_SECURITY,
    FEATURE_LABELS,
    FONT_CHOICES,
    NAV_BACK,
    NAV_HOME,
    NAV_NOOP,
    OWNER_IDS,
    PROVISION_LICENSE,
    PROVISION_MANUAL,
    PROVISION_SUBSCRIPTION,
    RESERVED_TAGS,
    ROLE_ADMIN,
    ROLE_OWNER,
    SECURITY_ROUTES,
    SIMPLE_BOOL_FEATURES,
    WIZ_2FA_EMAIL,
    WIZ_2FA_NEW_HINT,
    WIZ_2FA_NEW_PASS,
    WIZ_2FA_OLD_PASS,
    WIZ_ADD_ADMIN,
    WIZ_CODE,
    WIZ_CONFIRM_REPLACE,
    WIZ_EDIT_NAME,
    WIZ_PASSWORD,
    WIZ_PHONE,
    WIZ_PROXY_ADDR,
    WIZ_PROXY_PASSWORD,
    WIZ_PROXY_PORT,
    WIZ_PROXY_USERNAME,
    WIZ_SEND_MSG_TARGET,
    WIZ_SEND_MSG_TEXT,
    WIZ_TAG,
    _ADMIN_CLIENT_REF,
    _acc_ui_state,
    _chmod_private,
    _first_account_creds,
    _friendly_error,
    _is_nav_action,
    _is_safe_proxy_host,
    _load_account_delete_journal,
    _remove_session_files,
    _save_account_delete_journal,
    _save_last_2fa_password,
    _security_main_owner_id,
    _status_human,
    antiban_consume,
    antiban_guarded_action,
    authorize_sensitive_account_action,
    build_backup_zip,
    build_sessions_backup_zip,
    check_session_health,
    ensure_started,
    ensure_stopped,
    fa_digits,
    get_active_grants,
    get_active_subscription,
    is_dangerous_account,
    list_admins_and_resellers,
    log_action,
    phone_country_hint,
    restart,
    safe_callback_int,
    self_backup_enabled,
    self_backup_group,
)

# کلاس‌های هم‌خانواده / توابعِ جابه‌جا‌شده
from cianet.bots.ui import NavStack, UI


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
        # PATCH (v2.0.12): wizard TTL. هر wizard یک timestamp ست می‌شه و
        # وقتی از ۳۰ دقیقه بگذره، خودکار پاک می‌شه (و temp_client disconnect).
        # این از نشتِ TCP socket و session file lock در wizardهای رها‌شده
        # جلوگیری می‌کنه.
        self._WIZARD_TTL_SEC = 30 * 60
        self._last_wizard_gc = 0.0
        self.admin_ids: set = set()
        self._backup_task = None
        # v2.22.0 (OWNER-REQUEST): حلقهٔ بکاپِ ساعتیِ سشن‌های سلف به
        # گروهِ شخصیِ مالک (جدا از بکاپِ روزانهٔ کامل).
        self._self_backup_task = None
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

    # ─────────────────────────────────────────────────────────────────
    # v2.12.12 (QA4-DEBUG/EXPERT/OWNER): async helpers با timeout برای
    # event.respond و event.edit. قبلاً ۱۷ مکان در جریان 2FA (و sessions)
    # بدون timeout بودن و وقتی تلگرام FloodWait می‌داد یا entity cache
    # گرم نبود، بی‌نهایت hang می‌کردن → کل admin panel تحت _panel_lock
    # قفل می‌شد. حالا همه‌ی این مکان‌ها از این helper‌ها استفاده می‌کنن.
    # ─────────────────────────────────────────────────────────────────
    _RESPOND_TIMEOUT_SEC = 15
    _EDIT_TIMEOUT_SEC = 10

    async def _respond_safe(self, event, text: str, buttons=None,
                            link_preview: bool = False) -> bool:
        """event.respond با timeout. اگه timeout خورد یا خطا داد، fallback
        به event.answer با alert. برمی‌گرداند: True اگه respond موفق بود."""
        try:
            await asyncio.wait_for(
                event.respond(text, buttons=buttons, link_preview=link_preview),
                timeout=self._RESPOND_TIMEOUT_SEC,
            )
            return True
        except asyncio.TimeoutError:
            print(f"⚠️ [respond_safe] timeout after {self._RESPOND_TIMEOUT_SEC}s", flush=True)
            try:
                await event.answer("⏳ تلگرام پاسخ نداد. دوباره بزن.", alert=True)
            except Exception as _ae:
                print(f"⚠️ [respond_safe] alert fallback failed: "
                      f"{type(_ae).__name__}", flush=True)
            return False
        except Exception as _e:
            print(f"⚠️ [respond_safe] {type(_e).__name__}: {_e}", flush=True)
            try:
                await event.answer("❌ خطا در نمایش. دوباره بزن.", alert=True)
            except Exception as _ae:
                print(f"⚠️ [respond_safe] alert fallback failed: "
                      f"{type(_ae).__name__}", flush=True)
            return False

    async def _edit_safe(self, event, text: str = None, buttons=None,
                         link_preview: bool = False) -> bool:
        """event.edit با timeout. اگه timeout خورد، fallback به respond.
        اگه text مقدار نداشته باشه (None)، فقط message با buttons رو edit کن."""
        try:
            kwargs = {}
            if text is not None:
                kwargs["text"] = text
            if buttons is not None:
                kwargs["buttons"] = buttons
            kwargs["link_preview"] = link_preview
            await asyncio.wait_for(
                event.edit(**kwargs),
                timeout=self._EDIT_TIMEOUT_SEC,
            )
            return True
        except asyncio.TimeoutError:
            print(f"⚠️ [edit_safe] timeout after {self._EDIT_TIMEOUT_SEC}s", flush=True)
            if text is not None:
                return await self._respond_safe(event, text, buttons=buttons,
                                                 link_preview=link_preview)
            return False
        except Exception as _e:
            print(f"⚠️ [edit_safe] {type(_e).__name__}: {_e}", flush=True)
            # v2.12.13: از isinstance واقعی به‌جای string-match استفاده کن
            _mnt = getattr(errors, "MessageNotModifiedError", None)
            if _mnt is not None and isinstance(_e, _mnt):
                return True
            if _mnt is None and "MessageNotModified" in type(_e).__name__:
                return True
            if text is not None:
                try:
                    return await self._respond_safe(event, text, buttons=buttons,
                                                    link_preview=link_preview)
                except Exception:
                    pass
            return False

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
        # v2.14.2 (P2-2 flag / BUG-16a sibling): اگر start شکست بخورد یا
        # timeout شود کلاینت leak نمی‌شود — disconnectِ best-effort +
        # re-raise (همان الگوی SaaSBot.start).
        try:
            await asyncio.wait_for(self.client.start(bot_token=ADMIN_BOT_TOKEN), timeout=30)
        except Exception:
            try:
                if self.client.is_connected():
                    await self.client.disconnect()
            except Exception:
                pass
            raise
        # v2.12.12: pre-warm dialog cache (مشابه SaaSBot.start)
        # v2.12.13: timeout aggregate اضافه شد.
        try:
            print("🔄 [admin_bot] pre-warming dialog cache (limit=100)...")
            async def _warmup_admin():
                _warmup_count = 0
                async for _ in self.client.iter_dialogs(limit=100):
                    _warmup_count += 1
                    if _warmup_count >= 100:
                        break
                return _warmup_count
            _n = await asyncio.wait_for(_warmup_admin(), timeout=30)
            print(f"✅ [admin_bot] dialog cache warmed ({_n} dialogs)")
        except asyncio.TimeoutError:
            print(f"⚠️ [admin_bot] dialog cache warmup TIMED OUT after 30s (continuing)")
        except Exception as _e:
            print(f"⚠️ [admin_bot] dialog cache warmup failed (continuing): "
                  f"{type(_e).__name__}: {_e}")
        self._register_handlers()

        # PATCH (v2.0.10): reference به client رو در ماژول نگه دار تا
        # _owner_notify_async بتونه به OWNER پیام بفرسته (مثلاً وقتی یک
        # اکانت fatal-auth می‌خوره و باید notify بشه).
        global _ADMIN_CLIENT_REF
        _ADMIN_CLIENT_REF["client"] = self.client

        if self._backup_task is None or self._backup_task.done():
            self._backup_task = asyncio.create_task(self._daily_backup_loop())
        # v2.22.0 (OWNER-REQUEST): بکاپِ ساعتیِ سلف‌ها — در سرِ هر ساعت
        # (وقت ایران) اگر گروهِ مقصد تنظیم و کلید روشن باشد، یک ZIPِ
        # فقط-سشن به گروه ارسال می‌شود.
        if self._self_backup_task is None or self._self_backup_task.done():
            self._self_backup_task = asyncio.create_task(self._self_backup_loop())

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
        await self._edit_safe(
            event,
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
        ]
        # v2.12.14 (USER-REQUEST): دکمه‌ی «📨 ارسال پیام» فقط برای
        # OWNER/ADMIN نشون داده بشه. کاربرِ معمولی فقط باید قابلیت‌ها/
        # ظاهر/اتصال/وضعیت/توقف/حذف رو ببینه — ابزارِ ارسالِ پیام از طرفِ
        # اکانت، یه قابلیتِ مدیریتیه و برای کاربر عادی مفید نیست.
        # _role در SaaSBot تعریف شده (AdminBot مستقلیم doesn't have it)،
        # پس از self.saas استفاده می‌کنیم.
        _saas_ref = getattr(self, "saas", None)
        _viewer_role = _saas_ref._role(event.sender_id) if _saas_ref else None
        _can_send_msg = _viewer_role in (ROLE_OWNER, ROLE_ADMIN) if _viewer_role else True
        if _can_send_msg:
            buttons.append([
                UI.go("📨 ارسال پیام", f"send_msg:{tag}"),
                UI.go("🌐 اتصال و پروکسی", f"conn:{tag}"),
            ])
        else:
            buttons.append([UI.go("🌐 اتصال و پروکسی", f"conn:{tag}")])
        buttons.append([UI.go("📊 دیدن وضعیت کامل", f"status:{tag}")])
        # عملیاتِ حالت‌دار: سبز برای روشن‌کردن، خاکستری برای توقفِ موقت،
        # قرمز فقط برای حذفِ برگشت‌ناپذیر — تا رنگ‌ها با شدتِ عمل بخوانند.
        if disabled:
            buttons.append([UI.confirm("فعال‌سازی اکانت", f"enable:{tag}")])
        else:
            buttons.append([UI.neutral("توقف موقت SelfBot", f"disable:{tag}")])
        buttons.append([UI.danger("حذف کامل اکانت", f"del_confirm:{tag}")])
        buttons.append(UI.nav_row())

        await self._edit_safe(
            event,
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
        await self._edit_safe(
            event,
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
        # PATCH (audit-7): قبلاً دکمه‌های «✏️ تغییر اسم» و «🔤 تغییر فونت»
        # همیشه نشان داده می‌شدند، حتی وقتی اکانت روشن نبود. کلیک روی آن‌ها
        # در حالتِ non-running با `entry is None` در handler سایلنت fail
        # می‌کرد یا به صفحه‌ی مرده می‌رسید. حالا اگر اکانت non-running
        # است، دکمه‌ی «روشن کن» نشان داده می‌شود (mirror از _show_features).
        if entry:
            buttons = [
                [
                    UI.go("✏️ تغییر اسم", f"edit_name:{tag}"),
                    UI.go("🔤 تغییر فونت", f"font_menu:{tag}"),
                ],
                UI.nav_row(),
            ]
        else:
            # اکانت در حال حاضر اجرا نمی‌شود — فقط دکمه‌ی enable.
            buttons = [
                [UI.go("🟢 روشن کن", f"enable:{tag}", primary=True, tone="success")],
                UI.nav_row(),
            ]
        await self._edit_safe(
            event,
            UI.screen(f"🎨 ظاهر و پروفایل «{tag}»", body=body,
                      subtitle="ظاهر پیام‌ها و پروفایل این اکانت."),
            buttons=buttons,
        )

    async def _show_connection(self, event, tag: str):
        """🌐 اتصال و پروکسی — v2.11: فقط پروکسی + قابلیت‌ها.
        2FA/sessions/login-code به مدیریت اکانت منتقل شد.
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

        buttons = [
            [UI.go("🌐 تنظیم پروکسی", b"proxy_start:" + tag.encode())],
            [UI.go("📊 وضعیت", b"status:" + tag.encode())],
            UI.nav_row(),
        ]
        await self._edit_safe(
            event,
            UI.screen("🌐 اتصال و پروکسی", body=body,
                      subtitle=f"«{tag}»"),
            buttons=buttons,
        )


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
            # اکانت ممکن است هنوز در حال start باشد یا fail شده باشد
            cfg = self.sb.load_config()
            if tag in cfg:
                # NOTE: قبلاً `_RUNTIME_STATUS` استفاده می‌شد که در کل ماژول تعریف
                # نشده بود → NameError در callback و هندلر با swallow در WARNING
                # بی‌صدا از بین می‌رفت (همان «اسپینر سپس هیچی»). رجیستریِ واقعی
                # `BOT_STATUS` است (موجودیتِ per-tag وضعیت runtime).
                status = _status_human(BOT_STATUS.get(tag, "unknown"))
                await event.answer(
                    f"اکانت «{tag}» هنوز آماده نیست (وضعیت: {status}). "
                    f"چند ثانیه صبر کن و دوباره تلاش کن.", alert=True)
            else:
                await event.answer("این اکانت وجود ندارد.", alert=True)
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
            await self._edit_safe(
                event,
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
        # v2.8.11: دکمه‌ی «🔐 رمز دو مرحله‌ای» اضافه شد تا کاربر از
        # لیست دستگاه‌ها بتونه مستقیم به پنل 2FA بره — قبلاً اینجا
        # هیچ راهی نبود و کاربر در بن‌بست می‌ماند.
        buttons.append([UI.go("🔐 رمز دو مرحله‌ای", f"tfa:{tag}")])
        # v2.12.24: محافظتِ ورود — toggle on/off
        # v2.14.6 (USER-REQUEST): فقط مالک اصلی سلف (ADMIN_ID + OWNER_IDS) دکمه را می‌بیند.
        # هیچ‌کس دیگه‌ای — حتی صاحب خودِ اکانت، ADMIN، RESELLER یا USER —
        # دکمه را نمی‌بیند چون فقط مالک سلف می‌تواند login_guard را toggle کند.
        _viewer_id_for_btn = event.sender_id
        _main_owner_for_btn = _security_main_owner_id()
        try:
            _extra_owners_for_btn = OWNER_IDS
        except NameError:
            _extra_owners_for_btn = set()
        _show_guard_btn = (
            (_main_owner_for_btn and _viewer_id_for_btn == _main_owner_for_btn)
            or (_viewer_id_for_btn in _extra_owners_for_btn)
        )
        if _show_guard_btn:
            _guard_on = entry and getattr(entry.bot, "login_code_guard", False)
            _guard_label = "🔒 محافظت ورود: روشن" if _guard_on else "🔓 محافظت ورود: خاموش"
            buttons.append([UI.go(_guard_label, f"login_guard:{tag}", tone="success" if _guard_on else None)])
        buttons.append([UI.refresh(f"sessions:{tag}")])
        buttons.append(UI.nav_row())

        await self._edit_safe(
            event,
            UI.screen("🔒 دستگاه‌های لاگین‌شده", body=body,
                      subtitle=f"«{tag}» روی {fa_digits(len(sessions))} دستگاه فعال است.",
                      hint=("تیکِ چند دستگاه را بزن، بعد «بستنِ انتخاب‌شده‌ها»؛ یا «خروج از همه»."
                            if others else "🔐 برای تنظیمات رمز دو مرحله‌ای، روی دکمه‌ی پایین بزن.")),
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

    async def _kill_selected_sessions(self, event, tag: str, skip_antiban: bool = False):
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
        # Anti-Ban: اکانت شماره خارج/مجازی → تأیید اضافه لازم است.
        # PATCH (antiban-loop): قبلاً وقتی از مسیرِ _handle_antiban_confirm
        # فراخوانی می‌شد، دوباره antiban_guarded_action را صدا می‌زد و چون
        # کاربر مالکِ غیرِ owner است و اکانت dangerous است، یک token تازه
        # می‌ساخت و هشدار را دوباره نمایش می‌داد → حلقه‌ی بی‌نهایتِ
        # «تأیید → هشدار → تأیید → هشدار». حالا skip_antiban=True از مسیرِ
        # تأیید پاس داده می‌شود تا همان یک بارِ تأییدشده کافی باشد.
        if not skip_antiban:
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
        await self._edit_safe(
            event,
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
            await self._edit_safe(
                event,
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

        # عملیات تأیید شد → اجرای عملیات اصلی. PATCH (antiban-loop): تا
        # قبلش، این متدها دوباره antiban_guarded_action را صدا می‌زدند و
        # چون کاربر non-owner است و اکانت dangerous است، یک token تازه
        # می‌ساختند و هشدار را دوباره نشان می‌دادند → حلقه‌ی بی‌نهایتِ
        # «تأیید → هشدار → تأیید». حالا skip_antiban=True پاس داده می‌شود
        # تا همان یک بارِ تأییدِ کاربر کافی باشد. (تأییدِ کاربر در
        # antiban_consume بالا مصرف شد؛ اینجا دیگر نیاز به token نیست.)
        if action == "sessterm":
            await event.answer("تأیید شد — در حال بستن...")
            await self._terminate_sessions(event, tag, skip_antiban=True)
        elif action == "sesskill":
            await event.answer("تأیید شد — در حال بستن sessionهای انتخابی...")
            await self._kill_selected_sessions(event, tag, skip_antiban=True)
        elif action == "tfago":
            await event.answer("تأیید شد — در حال ارسال درخواست...")
            await self._do_2fa_reset(event, tag, skip_antiban=True)
        else:
            await self._edit_safe(
                event,
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
        await self._edit_safe(
            event,
            UI.screen("⚠️ خروج از همه‌ی دستگاه‌ها", body=body,
                      hint="این کار برگشت‌ناپذیر است؛ دستگاه‌ها باید دوباره لاگین کنند."),
            buttons=[
                [UI.danger(f"بله، هر {fa_digits(len(others))} تا را ببند", f"sessterm:{tag}")],
                [UI.neutral("انصراف", f"sessions:{tag}")],
            ],
        )

    async def _terminate_sessions(self, event, tag: str, skip_antiban: bool = False):
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
        # PATCH (antiban-loop): skip_antiban=True از مسیرِ _handle_antiban_confirm
        # پاس داده می‌شود تا حلقه‌ی بی‌نهایتِ «تأیید → هشدار» نشود.
        if not skip_antiban:
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
            await self._edit_safe(
                # PATCH (USER-REPORT v2.14.3): این صفحه — مثلِ بقیه‌ی صفحاتِ پنل —
                # درجا ویرایش می‌شود (نه پیامِ جدید برای هر تعامل). قبلاً هر
                # بازدید/بروزرسانی/بازگشت، کلِ صفحه را به‌صورت پیامِ جدید
                # می‌فرستاد و چت زیرِ پیام‌هایِ تکراری دفن می‌شد.
                event,
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
            await self._edit_safe(
                event,
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
            # v2.12.13 (USER-REPORT): اگه pending در گذشته باشه، یعنی
            # انتظارِ ۷ روزه تمام شده و کاربر می‌تونه رمز رو حذف کنه.
            # قبلاً حتی در این حالت هم «بعد از آن ادامه‌ی بازنشانی را بزن»
            # نشون می‌دادیم که گمراه‌کننده بود.
            try:
                _sec_left = (pending - datetime.now(timezone.utc)).total_seconds()
            except Exception:
                _sec_left = 0
            if _sec_left <= 0:
                # انتظار تمام شده
                body += [
                    UI.SEP,
                    f"{UI.GREEN} ✅ زمانِ انتظار به پایان رسیده!",
                    f"{UI.GRAY} حالا می‌توانی «ادامه‌ی بازنشانی» را بزنی تا "
                    f"رمز دو مرحله‌ای برای همیشه حذف شود.",
                ]
            else:
                body += [
                    UI.SEP,
                    f"{UI.AMBER} بازنشانی در جریان است",
                    f"{UI.GRAY} پایانِ انتظار: {st.get('pending_reset_date_local') or self._until_text(pending)}",
                    # PATCH (USER-REPORT v2.14.3): «دیگر» تکراری — خودِ _until_text
                    # همیشه با «دیگر» تمام می‌شود؛ پس اینجا فقط نقطه.
                    f"{UI.GRAY} {self._until_text(pending)}.",
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
            # PATCH (v2.6.2): دکمه‌های تغییر/حذف رمز و ایمیل
            buttons.append([UI.go("🔑 تغییر رمز", f"tfachange:{tag}")])
            buttons.append([UI.go("🗑 حذف رمز", f"tfaremove:{tag}", tone="danger")])
            buttons.append([UI.go("📧 تغییر ایمیل", f"tfaemail:{tag}")])
            buttons.append([UI.danger(
                f"درخواست بازنشانی رمز{antiban_mark3}", f"tfareset:{tag}")])
        buttons.append([UI.refresh(f"tfa:{tag}")])
        buttons.append(UI.nav_row())

        await self._edit_safe(
            event,
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
        # PATCH (USER-REPORT v2.14.3): pending_reset_date تا وقتی بازنشانی
        # نهایی/لغو نشده ست می‌ماند — حتی بعد از پایانِ دوره‌ی ۷ روزه. قبلاً
        # هر دو حالت یکسان رفتار می‌کردند (redirect به صفحه‌ی وضعیت) که دو
        # باگ می‌ساخت:
        #   ۱) در طولِ انتظار، هر کلیکِ «ادامه‌ی بازنشانی» همان صفحه را
        #      دوباره می‌فرستاد + مسیرِ tfareset در پشته‌ی ناوبری می‌ماند →
        #      «بازگشت» به تعدادِ کلیک‌ها همین صفحه را تکرار می‌فرستاد.
        #   ۲) بعد از پایانِ انتظار، هیچ راهی برای نهایی‌کردنِ حذفِ رمز
        #      باقی نمی‌ماند — با اینکه صفحه‌ی وضعیت قولِ «بعد از آن
        #      ادامه‌ی بازنشانی را بزن تا رمز حذف شود» می‌دهد.
        # حالا: انتظارِ فعال → فقط پاسخِ کوتاه + تمیزکاریِ پشته؛
        # انتظارِ تمام‌شده → صفحه‌ی تأییدِ نهایی (ادامه → حذفِ واقعی).
        if pending:
            try:
                _sec_left = (pending - datetime.now(timezone.utc)).total_seconds()
            except Exception:
                _sec_left = 0
            if _sec_left > 0:
                # انتظارِ فعال — هنوز کاری از دستِ کاربر برنمی‌آید. مسیرِ
                # tfareset که روتر موقعِ همین کلیک push کرده بود، مثلِ
                # NAV_BACK از پشته برداشته می‌شود تا «بازگشت» قدمِ اضافه
                # نخورد؛ کاربر فقط یک پاسخِ کوتاه می‌گیرد.
                self.nav.pop(event.sender_id)
                try:
                    await event.answer(
                        "⏳ زمانِ انتظار هنوز تمام نشده — "
                        f"{self._until_text(pending)} صبر کن و بعد دوباره «ادامه‌ی بازنشانی» را بزن.",
                        alert=True)
                except Exception:
                    pass
                return
            # انتظار تمام شده — به صفحه‌ی تأییدِ نهایی می‌رویم (fall through)
            # تا با «ادامه» رمز واقعاً حذف شود (ResetPasswordRequest دوم →
            # ResetPasswordOk).

        # ── متنِ صفحه‌ی تأیید: دو حالت ──
        #   شروعِ تازه (pending=None) یا نهایی‌کردن بعد از پایانِ انتظار.
        if pending:
            body = [
                "انتظارِ دوره‌ی بازنشانی به پایان رسیده است.",
                f"{UI.GREEN} با تأیید، رمز دو مرحله‌ای همین حالا برای همیشه حذف می‌شود.",
                "",
                f"{UI.GRAY} • ایمیلِ بازیابی هم بی‌اثر می‌شود.",
                f"{UI.AMBER} این عملیات برگشت‌پذیر نیست.",
            ]
            go_label = "بله، رمز را حذف کن"
        else:
            body = [
                "با تأیید این درخواست:",
                f"{UI.GRAY} • تلگرام یک دوره‌ی انتظار شروع می‌کند (معمولاً تا ۷ روز).",
                f"{UI.GRAY} • بعد از پایانِ انتظار، رمز کاملاً حذف می‌شود — نه زودتر.",
                f"{UI.GRAY} • ایمیلِ بازیابی هم بی‌اثر می‌شود.",
                "",
                f"{UI.AMBER} تا پایانِ انتظار، رمز همچنان فعال است و اکانت کار می‌کند.",
                f"{UI.GREEN} هر وقت خواستی می‌توانی درخواست را لغو کنی.",
            ]
            go_label = "بله، بازنشانی را شروع کن"
        await self._respond_safe(
            event,
            UI.screen(
                "⚠️ بازنشانی رمز دو مرحله‌ای",
                body=body,
                hint="این درخواست فقط با تأیید شما ثبت می‌شود."),
            buttons=[
                [UI.danger(go_label, f"tfago:{tag}")],
                [UI.neutral("انصراف", f"tfa:{tag}")],
            ],
        )

    async def _start_2fa_change_wizard(self, event, tag: str, mode: str = "change"):
        """شروع ویزارد تغییر/حذف رمز 2FA — از کاربر رمز قدیم را می‌گیرد."""
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        # PATCH-6 (TEST-WIZARD-FLOWS): پاک‌سازیِ ویزاردِ قبلیِ همین کاربر
        # قبل از شروع ویزاردِ جدید. بدون این، اگه کاربر وسطِ ویزارد لاگین
        # (که temp_client متصل دارد) این ویزارد رو شروع کنه، temp_client
        # لیک میشه (TCP socket + SQLite handle). الگوی مشابه با
        # start_login_wizard_for_user (خط 9880).
        await self._cleanup_wizard_temp_client(self.wizards.pop(event.sender_id, None))
        self.wizards[event.sender_id] = {
            "state": WIZ_2FA_OLD_PASS,
            "data": {"tag": tag, "mode": mode, "back": f"tfa:{tag}"},
            "_ts": time.time(),
        }
        title = "🔑 تغییر رمز دو مرحله‌ای" if mode == "change" else "🗑 حذف رمز دو مرحله‌ای"
        await self._respond_safe(
            event,
            f"**{title}**\n\nرمز فعلی را بفرست:\n"
            f"(برای امنیت، پیام شما پس از استفاده حذف می‌شود)",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def _start_2fa_email_wizard(self, event, tag: str):
        """شروع ویزارد تغییر ایمیل بازیابی 2FA — از کاربر رمز فعلی + ایمیل جدید را می‌گیرد."""
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        # PATCH-6 (TEST-WIZARD-FLOWS): پاک‌ سازیِ ویزاردِ قبلی — جلوگیری از
        # لیکِ temp_client اگه کاربر وسطِ ویزارد لاگین این ویزارد رو شروع کنه.
        await self._cleanup_wizard_temp_client(self.wizards.pop(event.sender_id, None))
        self.wizards[event.sender_id] = {
            "state": WIZ_2FA_OLD_PASS,
            "data": {"tag": tag, "mode": "email", "back": f"tfa:{tag}"},
            "_ts": time.time(),
        }
        await self._respond_safe(
            event,
            "**📧 تغییر ایمیل بازیابی**\n\nرمز فعلی را بفرست:\n"
            "(برای امنیت، پیام شما پس از استفاده حذف می‌شود)",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def _handle_2fa_wizard(self, event, wiz: dict):
        """مدیریت مراحل ویزارد تغییر/حذف رمز 2FA و تغییر ایمیل."""
        state = wiz["state"]
        data = wiz["data"]
        text = (event.raw_text or "").strip()
        tag = data["tag"]
        mode = data.get("mode", "change")

        # حذف پیام کاربر (رمز/ایمیل) برای امنیت
        try:
            await event.message.delete()
        except Exception:
            pass

        entry = self.sb.ACCOUNTS.get(tag)
        if not entry:
            await self._respond_safe(event, "❌ اکانت دیگر روشن نیست.")
            self.wizards.pop(event.sender_id, None)
            return

        if state == WIZ_2FA_OLD_PASS:
            data["old_pass"] = text
            if mode == "change":
                wiz["state"] = WIZ_2FA_NEW_PASS
                await self._respond_safe(
                    event,
                    "رمز جدید را بفرست:\n(خالی = حذف رمز، فقط «حذف» بنویس)",
                    buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
                )
            elif mode == "remove":
                # مستقیم حذف کن
                await self._execute_2fa_change(event, tag, data, new_pass="", hint="")
            elif mode == "email":
                wiz["state"] = WIZ_2FA_EMAIL
                await self._respond_safe(
                    event,
                    "📧 ایمیل بازیابی جدید را بفرست:\n(خالی = حذف ایمیل، فقط «حذف» بنویس)",
                    buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
                )
            return

        if state == WIZ_2FA_NEW_PASS:
            if text.lower() in ("حذف", "delete", ""):
                await self._execute_2fa_change(event, tag, data, new_pass="", hint="")
            else:
                data["new_pass"] = text
                wiz["state"] = WIZ_2FA_NEW_HINT
                await self._respond_safe(
                    event,
                    "💡 راهنمای رمز (اختیاری) — خالی بفرست تا بدون راهنما باشد:",
                    buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
                )
            return

        if state == WIZ_2FA_NEW_HINT:
            hint = text if text.lower() not in ("خالی", "بدون", "no", "-") else ""
            await self._execute_2fa_change(event, tag, data,
                                           new_pass=data.get("new_pass", ""), hint=hint)
            return

        if state == WIZ_2FA_EMAIL:
            email = text if text.lower() not in ("حذف", "delete", "") else ""
            await self._execute_2fa_email_change(event, tag, data, email=email)
            return

    async def _execute_2fa_change(self, event, tag: str, data: dict, new_pass: str, hint: str):
        """اجرای تغییر/حذف رمز 2FA."""
        self.wizards.pop(event.sender_id, None)
        try:
            entry = self.sb.ACCOUNTS.get(tag)
            if not entry:
                await self._respond_safe(event, "❌ اکانت روشن نیست.")
                return
            await self._respond_safe(event, "⏳ در حال اعمال تغییرات...")
            try:
                res = await entry.bot.change_2fa_password(
                    old_pass=data.get("old_pass", ""),
                    new_pass=new_pass,
                    hint=hint,
                )
                if res.get("ok"):
                    if res.get("action") == "removed":
                        await self._respond_safe(event, "✅ رمز دو مرحله‌ای حذف شد.")
                    else:
                        await self._respond_safe(event, "✅ رمز دو مرحله‌ای تغییر کرد.")
                    log_action(event.sender_id, "2fa_password_changed",
                               f"tag={tag} action={res.get('action', 'changed')}")
                else:
                    err = res.get("error", "unknown")
                    msg = {
                        "invalid_password": "❌ رمز فعلی اشتباه است.",
                        "no_password": "❌ رمزی روی این اکانت فعال نیست.",
                    }.get(err, f"❌ خطا: {err}")
                    await self._respond_safe(event, msg)
            except Exception as e:
                await self._respond_safe(event, f"❌ خطا: {type(e).__name__}")
        finally:
            # v2.13.0 (DEBUG-2 WIZARD): clear passwords from memory after use.
            # حالا که API call تمام شد (موفق یا ناموفق)، password fields رو
            # None می‌کنیم تا رشته‌های رمز از memory پاک بشن و در صورت dump
            # شدن memory قابل خواندن نباشن.
            if isinstance(data, dict):
                data["old_pass"] = None
                data["new_pass"] = None
                data["password"] = None

    async def _execute_2fa_email_change(self, event, tag: str, data: dict, email: str):
        """اجرای تغییر ایمیل بازیابی 2FA."""
        self.wizards.pop(event.sender_id, None)
        try:
            entry = self.sb.ACCOUNTS.get(tag)
            if not entry:
                await self._respond_safe(event, "❌ اکانت روشن نیست.")
                return
            await self._respond_safe(event, "⏳ در حال اعمال تغییرات...")
            try:
                res = await entry.bot.change_2fa_email(
                    old_pass=data.get("old_pass", ""),
                    new_email=email,
                )
                if res.get("ok"):
                    if email:
                        await self._respond_safe(event, f"✅ ایمیل بازیابی به‌روزرسانی شد: {email}")
                    else:
                        await self._respond_safe(event, "✅ ایمیل بازیابی حذف شد.")
                    log_action(event.sender_id, "2fa_email_changed", f"tag={tag}")
                else:
                    err = res.get("error", "unknown")
                    msg = {
                        "invalid_password": "❌ رمز فعلی اشتباه است.",
                        "no_password": "❌ رمزی روی این اکانت فعال نیست.",
                    }.get(err, f"❌ خطا: {err}")
                    await self._respond_safe(event, msg)
            except Exception as e:
                await self._respond_safe(event, f"❌ خطا: {type(e).__name__}")
        finally:
            # v2.13.0 (DEBUG-2 WIZARD): clear passwords from memory after use.
            if isinstance(data, dict):
                data["old_pass"] = None
                data["new_pass"] = None
                data["password"] = None

    async def _do_2fa_reset(self, event, tag: str, skip_antiban: bool = False):
        """اجرای درخواست بازنشانی، بازخوانیِ وضعیت از تلگرام، و گزارش."""
        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        # Anti-Ban: بازنشانی ۲FA روی شماره‌ی خارج می‌تواند منجر به قطع
        # دسترسی اکانت توسط تلگرام شود.
        # PATCH (antiban-loop): skip_antiban=True از مسیرِ _handle_antiban_confirm
        # پاس داده می‌شود تا حلقه‌ی بی‌نهایتِ «تأیید → هشدار» نشود.
        if not skip_antiban:
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
            await self._respond_safe(
                event,
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
        await self._edit_safe(
            event,
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
            await self._edit_safe(
                event,
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
        await self._edit_safe(
            event,
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

    # v2.12.24 (USER-REQUEST): محافظتِ ورود — toggle on/off
    async def _toggle_login_guard(self, event, tag: str):
        """🔒 محافظت ورود — وقتی روشن باشه، هر کد ورود از 777000 فوراً
        منقضی می‌شه (با send_code_request). این جلوی سرقتِ اکانت رو
        می‌گیره: حتی اگه هکر شماره داشته باشه، کدی که می‌گیره نامعتبره.

        v2.14.6 (USER-REQUEST): فقط **مالک اصلی سلف** (ADMIN_ID + OWNER_IDS)
        می‌تواند login_guard را toggle کند. هیچ‌کس دیگه‌ای — حتی صاحب خودِ
        اکانت (owner_user_id)، ADMIN، RESELLER یا USER — اجازه ندارد.
        این سیاست امنیتی سخت‌گیرانه است که کنترل کامل محافظت ورود را در
        دست مالک سلف نگه می‌دارد.
        """
        # v2.14.6 (USER-REQUEST): فقط مالک اصلی سلف (ADMIN_ID + OWNER_IDS) اجازه دارد.
        # این چک اول از همه اجرا می‌شه — قبل از _sess_guard — تا هیچ‌کس جز
        # مالک سلف نتواند login_guard را تغییر دهد.
        _viewer_id = event.sender_id
        _main_owner = _security_main_owner_id()

        if not _main_owner or _viewer_id != _main_owner:
            # بررسی OWNER_IDS برای multi-owner setups
            try:
                _extra_owners = OWNER_IDS
            except NameError:
                _extra_owners = set()

            if _viewer_id not in _extra_owners:
                log_action(_viewer_id, "login_guard_blocked",
                           f"tag={tag} (main_owner-only policy)")
                await event.answer(
                    "🔒 فقط مالک اصلی سلف می‌تواند محافظت ورود را تغییر دهد.",
                    alert=True,
                )
                return

        entry, ok = await self._sess_guard(event, tag)
        if not entry:
            return
        # v2.12.27 (HUNT-1 #5): persist اول، بعد mutate — تا اگه persist
        # fail شد، in-memory untouched بمونه و state desync نشه.
        _new_val = not entry.bot.login_code_guard
        try:
            entry.bot._persist(login_code_guard=_new_val)
            entry.bot.login_code_guard = _new_val
        except Exception as _e:
            print(f"⚠️ [login_guard] persist failed: {_e}")
            await event.answer("❌ خطا در ذخیره‌سازی. دوباره بزن.", alert=True)
            return
        _state = "روشن" if _new_val else "خاموش"
        _icon = "🔒" if _new_val else "🔓"
        log_action(event.sender_id, "login_guard_toggled",
                   f"tag={tag} state={_state}")
        await self._show_sessions(event, tag,
                                  flash=f"{_icon} محافظت ورود {_state} شد.")

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
        # TEST-G1-ACCOUNT (BUG: EDGE_CASE_CRASH — `not getattr(bot, feature)`
        # بدونِ مقدارِ پیش‌فرض، اگر کاربر با callback دستی یک feature نامعتبر
        # بفرستد (مثلاً toggle:TAG:not_a_feature)، getattr روی bot یک
        # AttributeError پرت می‌کنه که از این تابع فرار می‌کنه و در
        # dispatcherِ بیرونی به یک پیامِ عمومیِ «خطا در پردازش این دکمه»
        # تبدیل می‌شه — به‌جای پیامِ دقیقِ «قابلیت ناشناخته.» در else
        # پایین. با default=False، getattr برای attribute ناموجود False
        # برمی‌گردانه، new_value=True می‌شه، هیچِ if/elif مچ نمی‌شه و
        # کاربر پیامِ درستِ «قابلیت ناشناخته.» می‌بینه.)
        new_value = not getattr(bot, feature, False)

        try:
            if feature == "enabled":
                if new_value:
                    bot.enabled = True
                    bot._persist(enabled=True)
                else:
                    await bot._power_off_full()
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
            await event.answer(_friendly_error(e, "feature_toggle"), alert=True)
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
        # PATCH-6 (TEST-WIZARD-FLOWS): پاک‌سازیِ ویزاردِ قبلی — جلوگیری از لیکِ temp_client.
        await self._cleanup_wizard_temp_client(self.wizards.pop(event.sender_id, None))
        self.wizards[event.sender_id] = {"state": WIZ_EDIT_NAME, "data": {"tag": tag},
            "_ts": time.time(),
        }
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
        # v2.12.30: retry ۳ بار + fallback disable. قبلاً فقط ۱ بار
        # ensure_stopped صدا زده می‌شد و اگه timeout می‌خورد، کاربر
        # هیچ کاری نمی‌تونست بکنه. حالا ۳ بار retry می‌شه و حتی اگه
        # نشد، disabled=True در config ثبت می‌شه تا restart بعدی.
        stopped = False
        for _attempt in range(3):
            stopped = await ensure_stopped(tag, "AdminBot._disable_account")
            if stopped:
                break
            print(f"⚠️ [_disable_account] توقف «{tag}» ناموفق (تلاش {_attempt+1}/۳) — retry در ۳s")
            await asyncio.sleep(3)
        if not stopped:
            # حتی اگه stop ناموفق بود، disabled=True ثبت کن تا restart بعدی
            # اکانت روشن نشه. این بهتر از اینه که کاربر هیچ کاری نتونه بکنه.
            print(f"❌ [_disable_account] توقف کامل «{tag}» بعد از ۳ retry ممکن نشد — "
                  f"disabled=True در config ثبت می‌شه.")
            cfg[tag]["disabled"] = True
            cfg[tag]["disabled_reason"] = "manual"
            self.sb.save_config(cfg)
            await event.edit(
                f"⚠️ توقف کامل اکانت «{tag}» زمان‌بر بود، ولی غیرفعال‌سازی ثبت شد.\n"
                f"اکانت در restart بعدی روشن نمی‌شه.",
                buttons=[UI.nav_row()],
            )
            return
        cfg[tag]["disabled"] = True
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

    async def _safe_replace_self(self, tag: str) -> bool:
        """
        v2.15.3 (LOGIN-UX-3/BUG-1): حذفِ امنِ سلف قبلی برای لاگین مجدد —
        همان هسته‌ی امنِ _delete_account (journal → ensure_stopped → حذفِ
        فایل‌های سشن → config → clear_state) ولی بدون تعامل با UI، برای
        صدا زدن از داخل ویزارد لاگین. برمی‌گرداند True فقط اگر حذف کامل
        موفق بود؛ در شکستِ میانی، Recovery استارتاپی ادامه می‌دهد.
        """
        cfg = self.sb.load_config()
        if tag not in cfg:
            return True  # دیگر وجود ندارد — همین کافی است
        # ۱) ثبت Intent حذف — قبل از هر تغییر (Recovery-safe)
        journal = _load_account_delete_journal()
        journal[tag] = "DELETE_PENDING"
        _save_account_delete_journal(journal)
        try:
            # ۲) توقف کامل Runtime — نه حذفِ خامِ فایل روی پروسه‌ی شاید زنده
            stopped = await ensure_stopped(tag, "AdminBot._safe_replace_self")
            if not stopped:
                print(f"❌ [safe_replace] توقف کامل اکانت «{tag}» ممکن نشد — "
                      f"سشن هنوز باز است؛ حذف لغو شد.")
                journal = _load_account_delete_journal()
                journal.pop(tag, None)
                _save_account_delete_journal(journal)
                return False
            # ۳) پاک‌سازی session (فایل + sidecar) — نتیجه بررسی می‌شود
            if not _remove_session_files(tag):
                print(f"❌ [safe_replace] حذف فایل سشن «{tag}» ناقص ماند — "
                      f"config حذف نشد؛ journal حفظ شد.")
                return False
            # ۴) به‌روزرسانی config
            cfg = self.sb.load_config()
            cfg.pop(tag, None)
            self.sb.save_config(cfg)
            # ۵) پاک‌سازی state — تا تنظیماتِ اکانت قبلی (مثل login_guard)
            #    روی تگِ تکراری نچسبد و کدِ ویزاردِ بعدی را منقضی نکند
            try:
                self.sb.clear_state(tag)
            except Exception as e:
                print(f"⚠️ [safe_replace] پاک‌سازی state اکانت {tag} ناموفق: "
                      f"{type(e).__name__}")
        except Exception as e:
            print(f"❌ [safe_replace] حذف «{tag}» نیمه‌تمام ماند (Recovery "
                  f"استارتاپی ادامه می‌دهد): {type(e).__name__}: {str(e)[:120]}")
            return False
        # ۶) همه‌ی مراحل موفق → Mark Delete Completed
        journal = _load_account_delete_journal()
        journal.pop(tag, None)
        _save_account_delete_journal(journal)
        return True

    # ─────────────────────────────────────────────────────
    #  پروکسی — فقط برای اکانتِ موجود (تغییر/حذف پروکسی روی اکانتِ از‌قبل‌لاگین‌شده)
    # ─────────────────────────────────────────────────────
    # نکته‌ی مهم: از v2.12.8 به بعد، فرایند لاگینِ اکانتِ جدید همیشه
    # مستقیم انجام می‌شود (بدون پرسیدنِ پروکسی). اگر تلگرام IP این سرور
    # را برای ورود محدود کرده باشد، کاربر باید ابتدا اکانت را روی یک
    # سرورِ دیگر (با IP تمیز) لاگین کند و سپس فایل session را روی این
    # سرور کپی کند. پروکسی روی این پروژه فقط برای اکانتِ از‌قبل‌موجود
    # کاربرد دارد: از صفحه‌ی «🌐 اتصال و پروکسی» (دکمه‌ی «🌐 تنظیم
    # پروکسی») پروکسی را تنظیم می‌کنی، بعد از ری‌استارت زنده اعمال
    # می‌شود. مسیر ویزارد: نوع → آدرس → پورت → یوزرنیم/پسورد اختیاری.

    async def _show_proxy_type_buttons(self, event, title: str):
        buttons = [
            [UI.go("SOCKS5", b"proxy_type:socks5"),
             UI.go("SOCKS4", b"proxy_type:socks4"),
             UI.go("HTTP", b"proxy_type:http")],
            [UI.neutral(UI.L_CANCEL, "cancel_wizard")],
        ]
        # v2.12.3: use respond instead of edit (avoid mix inline error)
        await event.respond(title, buttons=buttons)

    async def _start_proxy_wizard(self, event, tag: str):
        # PATCH-6 (TEST-WIZARD-FLOWS): پاک‌سازیِ ویزاردِ قبلی — جلوگیری از لیکِ temp_client.
        await self._cleanup_wizard_temp_client(self.wizards.pop(event.sender_id, None))
        self.wizards[event.sender_id] = {
            "state": None,
            "data": {"tag": tag},
            "_ts": time.time(),
        }
        await self._show_proxy_type_buttons(event, f"🌐 **تنظیم پروکسی برای «{tag}»**\n\nنوع پروکسی رو انتخاب کن:")

    async def _proxy_type_chosen(self, event, proxy_type: str):
        wiz = self.wizards.get(event.sender_id)
        if not wiz:
            return
        wiz["data"]["proxy_type"] = proxy_type
        wiz["state"] = WIZ_PROXY_ADDR
        # v2.12.3: use respond
        await event.respond(
            "آدرس (IP یا دامنه‌ی) پروکسی رو بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def _finish_proxy(self, event, data: dict):
        if not _is_safe_proxy_host(data.get("addr", "")):
            self.wizards.pop(event.sender_id, None)
            await event.respond("⛔ آدرس پروکسی نامعتبر است (IP داخلی یا محلی مجاز نیست).")
            return
        proxy_cfg = {
            "proxy_type": data["proxy_type"],
            "addr": data["addr"],
            "port": data["port"],
            "rdns": True,
        }
        if data.get("username"):
            proxy_cfg["username"] = data["username"]
            proxy_cfg["password"] = data.get("password", "")

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
        # PATCH-6 (TEST-WIZARD-FLOWS): پاک‌سازیِ ویزاردِ قبلی — جلوگیری از لیکِ temp_client.
        await self._cleanup_wizard_temp_client(self.wizards.pop(event.sender_id, None))
        self.wizards[event.sender_id] = {"state": WIZ_SEND_MSG_TARGET, "data": {"tag": tag},
            "_ts": time.time(),
        }
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
            await event.respond(_friendly_error(e, "send_msg"))

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
        self.wizards[event.sender_id] = {"state": WIZ_ADD_ADMIN, "data": {},
            "_ts": time.time(),
        }
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

    @staticmethod
    def _next_self_backup_time(now) -> object:
        """
        v2.22.0: نزدیک‌ترین سرِ ساعتِ بعدی (وقت ایران) — بکاپِ ساعتیِ سلف‌ها
        دقیقاً روی مرزِ ساعت اجرا می‌شود تا «هر ساعت» معنای ثابتی داشته
        باشد (نه «هر ساعت از لحظهٔ روشن‌شدنِ ربات»).
        """
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    async def _self_backup_loop(self):
        """
        v2.22.0 (OWNER-REQUEST): حلقهٔ بکاپِ ساعتیِ سشن‌های سلف.

        در سرِ هر ساعت (وقت ایران) اگر گروهِ مقصد تنظیم شده و کلید روشن
        باشد، یک ZIPِ سبکِ فقط-سشن (snapshot با API backup خودِ SQLite +
        manifest + رمزگذاری Fernet با CIANET_BACKUP_PASS — همان مسیرِ
        امنِ build_backup_zip) ساخته و در گروه ارسال می‌شود. اگر تنظیم
        نباشد، فقط می‌خوابد — بدونِ هیچ تماسِ تلگرامی.
        """
        while True:
            try:
                now = self.sb.iran_now()
                target = self._next_self_backup_time(now)
                await asyncio.sleep(max(1.0, (target - now).total_seconds()))
                if not (self_backup_group() and self_backup_enabled()):
                    continue
                await self._send_self_backup()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [admin_bot] خطا در بکاپِ ساعتیِ سلف: {e}")
                await asyncio.sleep(600)

    async def _send_self_backup(self):
        """ساخت و ارسالِ بکاپِ فقط-سشن به گروهِ شخصیِ مالک (هر ساعت)."""
        group = self_backup_group()
        if not group or not self_backup_enabled():
            return
        backup_pass = os.environ.get("CIANET_BACKUP_PASS", "").strip()
        if not backup_pass:
            print("⛔ [admin_bot] CIANET_BACKUP_PASS تنظیم نشده است — بکاپِ"
                  " ساعتیِ سلف ارسال نشد (fail-closed).")
            return
        _fd_sbk, path = tempfile.mkstemp(prefix="cianet_selfbkp_", suffix=".zip")
        os.close(_fd_sbk)
        try:
            ok = await asyncio.wait_for(
                asyncio.to_thread(build_sessions_backup_zip, path, backup_pass),
                timeout=60.0,
            )
            if not ok:
                print("⚠️ [admin_bot] ساخت بکاپِ ساعتیِ سلف ناموفق بود — ارسال نشد.")
                return
            file_size = os.path.getsize(path)
            now = self.sb.iran_now()
            caption = (
                f"🗂 بکاپِ ساعتیِ سشن‌های سلف — {now.strftime('%Y-%m-%d %H:%M')}\n"
                f"🕐 هر ساعت، خودکار · فقط-سشن · رمز: CIANET_BACKUP_PASS"
            )
            try:
                await asyncio.wait_for(
                    self.client.send_file(group, path, caption=caption,
                                          force_document=True),
                    timeout=300,
                )
                print(f"✅ [admin_bot] بکاپِ ساعتیِ سلف {file_size:,} bytes"
                      f" به گروه {group} ارسال شد")
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                print(f"⚠️ [admin_bot] ارسال بکاپِ ساعتیِ سلف به گروه {group}"
                      f" ناموفق: {err}")
                # خطا به خودِ مالک هم می‌رود تا گروهِ خراب بی‌صدا نماند
                try:
                    await self.client.send_message(
                        ADMIN_ID,
                        f"⚠️ ارسالِ بکاپِ ساعتیِ سلف به گروه `{group}` ناموفق بود:\n"
                        f"{err[:200]}"
                    )
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ [admin_bot] خطای کلی در بکاپِ ساعتیِ سلف: {type(e).__name__}: {e}")
        finally:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

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
        """بکاپ کامل روزانه (manifest) و ارسال به OWNER/ADMIN ها (رمزگذاری‌شده با CIANET_BACKUP_PASS)."""
        backup_pass = os.environ.get("CIANET_BACKUP_PASS", "").strip()
        if not backup_pass:
            print("⛔ [admin_bot] متغیر محیطی CIANET_BACKUP_PASS تنظیم نشده است — بکاپ روزانه ارسال نشد (fail-closed).")
            return
        _fd_bkp, backup_path = tempfile.mkstemp(prefix="cianet_bkp_", suffix=".zip")
        os.close(_fd_bkp)
        try:
            ok = await asyncio.wait_for(
                asyncio.to_thread(build_backup_zip, backup_path, backup_pass),
                timeout=60.0,
            )
            if not ok:
                print("⚠️ [admin_bot] ساخت بکاپ روزانه ناموفق بود — ارسال نشد.")
                return
            file_size = os.path.getsize(backup_path)
            now = self.sb.iran_now()
            slot = f"{int(scheduled_hour):02d}:00" if scheduled_hour is not None                 else now.strftime("%H:%M")
            caption = (
                f"📦 پشتیبان خودکار — {now.strftime('%Y-%m-%d %H:%M')}\n"
                f"🕐 نوبت: {slot} (ایران) — برنامه: {', '.join(f'{int(h):02d}:00' for h in BACKUP_HOURS_IRAN)}"
            )
            recipients = self._backup_recipient_ids()
            print(f"📤 [admin_bot] ارسال بکاپ {file_size:,} bytes به {len(recipients)} نفر: {recipients}")
            for admin_id in recipients:
                try:
                    await asyncio.wait_for(
                        self.client.send_file(admin_id, backup_path, caption=caption,
                                              force_document=True),
                        timeout=300,  # ۵ دقیقه
                    )
                    print(f"✅ [admin_bot] بکاپ به {admin_id} ارسال شد")
                except asyncio.TimeoutError:
                    err_msg = f"⏰ ارسال بکاپ خودکار به شما بیش از ۵ دقیقه طول کشید."
                    print(f"⚠️ [admin_bot] Timeout ارسال به {admin_id}")
                    try:
                        await self.client.send_message(admin_id, err_msg)
                    except Exception:
                        pass
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
                    print(f"⚠️ [admin_bot] ارسال بکاپ به {admin_id} ناموفق: {err}")
                    # پیام خطا به خود admin بفرست
                    try:
                        await self.client.send_message(
                            admin_id,
                            f"⚠️ بکاپ خودکار ارسال نشد:\n{err[:200]}"
                        )
                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️ [admin_bot] خطای کلی در بکاپ: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
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
        # PATCH-6 (TEST-WIZARD-FLOWS): پاک‌سازیِ ویزاردِ قبلی — جلوگیری از لیکِ
        # temp_client. این ویزارد خودش temp_client می‌سازه، پس اگه ویزاردِ
        # قبلیِ همین کاربر هم temp_client داشته، باید قبل از overwrite
        # disconnect بشه.
        await self._cleanup_wizard_temp_client(self.wizards.pop(event.sender_id, None))
        data = dict(preset_data or {})
        if preset_owner_id is not None:
            # «افزودن SelfBot» توسط OWNER/ADMIN/RESELLER برای یک کاربر خاص:
            # از کلیدِ مجزا (for_user_id) استفاده می‌کنیم — نه owner_user_id —
            # تا در _finish_add_account با مسیر «لاگین مستقیم کاربر عادی»
            # (که owner_user_id صریح می‌گذارد) اشتباه گرفته نشود و ادمین
            # بعد از ساخت، در منوی USER فرود نیاید.
            data["for_user_id"] = preset_owner_id
        # v2.15.3 (LOGIN-UX-2): مرحله‌ی «تگ دستی» حذف شد — مستقیم از شماره؛
        # تگ نهایی بعد از لاگین موفق خودکار از اسم + آیدی تلگرام ساخته
        # می‌شود (_finish_add_account → _auto_tag).
        self.wizards[event.sender_id] = {"state": WIZ_PHONE, "data": data,
            "_ts": time.time(),
        }
        title = "➕ **افزودن SelfBot**" if preset_owner_id is not None else "➕ **افزودن اکانت جدید**"
        await event.edit(
            f"{title}\n\n"
            "شماره تلفن رو با کد کشور بفرست (مثلاً `+989123456789`):",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def _cleanup_wizard_temp_client(self, wiz: dict):
        # v2.13.0 (DEBUG-2 WIZARD): also clear any password fields from the
        # wizard data dict so secret strings can be GC'd promptly. این
        # متد هم به‌عنوان cleanup مشترک از همه‌ی مسیرهای discard (stale
        # TTL، cancel، stale-check در _handle_wizard_input) صدا زده می‌شه،
        # پس این‌جا پاک‌سازی رمزها رو متمرکز کردیم.
        if wiz and isinstance(wiz.get("data"), dict):
            wiz["data"]["old_pass"] = None
            wiz["data"]["new_pass"] = None
            wiz["data"]["password"] = None
        temp_client = wiz.get("data", {}).get("temp_client") if wiz else None
        if temp_client:
            try:
                await temp_client.disconnect()
            except Exception:
                pass

    async def _cleanup_stale_wizards(self):
        """
        PATCH (v2.0.12): پاکسازیِ دوره‌ایِ wizardهای قدیمی. هر بار که
        message handler صدا زده می‌شه، این متد (با فاصله‌ی حداقل ۵ دقیقه)
        wizardهایی که بیشتر از ۳۰ دقیقه از آخرین activity شون گذشته رو
        پاک می‌کنه و temp_client اونها رو disconnect می‌کنه.

        این متد idempotent است و در صورت concurrent invocation مشکل
        ایجاد نمی‌کنه (pop روی کلیدِ حذف‌شده هیچ‌کاری نمی‌کنه).

        v2.12.23 (QA10-STABILITY BUG#2): _ts حالا در همه‌ی creation sites
        ست می‌شه (هم AdminBot هم SaaSBot)، پس TTL واقعاً کار می‌کنه.
        """
        import time as _time
        now = _time.time()
        # هر ۵ دقیقه بیشتر از این فراخوانی نشه (حتی اگه message هربار صدا زده بشه)
        if now - self._last_wizard_gc < 300:
            return
        self._last_wizard_gc = now
        if not self.wizards:
            return
        expired_uids = [
            uid for uid, wiz in self.wizards.items()
            if (now - wiz.get("_ts", 0)) > self._WIZARD_TTL_SEC
        ]
        for uid in expired_uids:
            wiz = self.wizards.pop(uid, None)
            await self._cleanup_wizard_temp_client(wiz)
            print(f"🧹 [wizard TTL] wizard کاربر {uid} به‌دلیل عدم فعالیت ۳۰ دقیقه پاک شد")

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
        # PATCH (USER-REPORT v2.14.3): ویزاردهای 2FA (تغییر/حذف رمز، تغییر
        # ایمیل) مقصدِ بازگشتِ صریح دارند («back»: tfa:TAG) ولی این مقدار
        # هیچ‌جا خوانده نمی‌شد — بعد از لغو، کلِ منوی اصلیِ پنل به‌صورتِ
        # پیامِ جدید فرستاده می‌شد و کاربر جای خودش را گم می‌کرد. حالا
        # همان صفحه‌ی مقصد دوباره رندر می‌شود تا کاربر همان‌جا که بود
        # ادامه بدهد.
        back_route = ((wiz or {}).get("data") or {}).get("back") if wiz else None
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
            elif back_route:
                try:
                    await notify_event.answer("❌ لغو شد.")
                except Exception:
                    pass
                # v2.14.12: اگه back_route یک route ساده (مثل admin_tools)
                # هست، مستقیم به صفحه برگردون — نه nav stack.
                _saas_for_back = getattr(self, "saas", None)
                _router_for_back = getattr(_saas_for_back, "_router", None) if _saas_for_back else None
                if _router_for_back is not None:
                    # مسیرِ ویزارد (tfachange/tfaremove/tfaemail) که روتر موقعِ
                    # شروعِ ویزارد روی پشته گذاشته بود، مثلِ NAV_BACK از پشته
                    # برداشته می‌شود تا «بازگشت» بعدی قدمِ اضافه نخورد.
                    _cur = self.nav.current(notify_event.sender_id) or ""
                    if _cur.startswith(("tfachange:", "tfaremove:", "tfaemail:")):
                        self.nav.pop(notify_event.sender_id)
                    # dispatch از ابتدا — همه‌ی گاردهای مالکیت/نقش مثلِ کلیکِ
                    # مستقیم اجرا می‌شوند (همان الگوی NAV_BACK و _nav_heal).
                    await _router_for_back(notify_event, _route=back_route, _depth=1)
                elif back_route == "admin_tools" and _saas_for_back is not None:
                    # v2.14.12: خاص برای admin_tools — مستقیم صدا بزن
                    try:
                        _role = _saas_for_back._role(notify_event.sender_id)
                        await _saas_for_back._show_admin_tools(notify_event, _role)
                    except Exception as _e:
                        print(f"⚠️ [cancel_wizard] admin_tools fallback failed: {_e}")
                        await notify_event.edit(
                            "❌ لغو شد.",
                            buttons=[[UI.neutral(UI.L_BACK, back_route)]],
                        )
                else:
                    # حالت standalone: پیامِ کوتاهِ لغو + دکمه‌ی بازگشت به مقصد.
                    await notify_event.edit(
                        "❌ لغو شد.",
                        buttons=[[UI.neutral(UI.L_BACK, back_route)]],
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
            elif back_route:
                # اینجا event نداریم (لغو با متن «لغو»)؛ پس فقط پیامِ کوتاه +
                # دکمه‌ی بازگشت به صفحه‌ی مقصد — نه منوی کامل.
                await self.client.send_message(
                    chat, "❌ لغو شد.",
                    buttons=[[UI.neutral(UI.L_BACK, back_route)]],
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
        except errors.PhoneNumberBannedError:
            # PATCH (audit-5): شماره‌ی بلاک‌شده توسط تلگرام — پیام کاربرپسند،
            # نه خطای فنی. ویزارد لغو می‌شود چون هیچ retryای اینجا کمک
            # نمی‌کند.
            await event.respond(
                "❌ این شماره توسط تلگرام مسدود شده و نمی‌توان با آن لاگین کرد. "
                "ویزارد لغو شد."
            )
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            self.wizards.pop(event.sender_id, None)
            return
        except errors.PhoneNumberUnoccupiedError:
            # PATCH (audit-5): شماره‌ای که هیچ اکانت تلگرامی روی‌اش نیست
            # (مثلاً شماره‌ی جدید بدون ثبت‌نام). کاربر باید اول در اپ تلگرام
            # اکانت بسازد.
            await self._respond_safe(
                event,
                "❌ این شماره هنوز در تلگرام ثبت‌نام نشده است. اول در اپ "
                "تلگرام اکانت بساز و دوباره بیا. ویزارد لغو شد."
            )
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            self.wizards.pop(event.sender_id, None)
            return
        except errors.AuthKeyError:
            # PATCH (audit-5): کلیدِ احراز هویتِ معتبر نیست — معمولاً
            # api_id/api_hash خراب یا مسدود.
            await self._respond_safe(
                event,
                "❌ api_id/api_hash معتبر نیست (شاید توسط تلگرام مسدود شده). "
                "با پشتیبانی تماس بگیر. ویزارد لغو شد."
            )
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            self.wizards.pop(event.sender_id, None)
            return
        except Exception as e:
            # v2.12.9 (QA-EXPERT WATCH-2): hint قدیمی به کاربر می‌گفت «این‌بار
            # پروکسی رو انتخاب کن» ولی v2.12.8 سوالِ پروکسی رو در لاگینِ جدید
            # حذف کرده. hint دروغ بود. حالا فقط پیامِ خطا رو می‌فرستیم.
            await self._respond_safe(event, _friendly_error(e, "send_code") + "\nویزارد لغو شد.")
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            self.wizards.pop(event.sender_id, None)
            return

        data["temp_client"] = temp_client
        data["phone_code_hash"] = sent.phone_code_hash
        data["code_errors"] = 0
        data["resends"] = data.get("resends", 0)
        self.wizards[event.sender_id] = {"state": WIZ_CODE, "data": data,
            "_ts": time.time(),
        }
        # v2.15.3 (LOGIN-UX-1): متن قبلی می‌گفت «فاصله بین ارقام مهم نیست» —
        # دقیقاً برعکسِ واقعیت. تلگرام کدِ خام را در متنِ پیام تشخیص می‌دهد و
        # ممکن است سانسور/منقضی کند؛ فاصله بین ارقام الگو را می‌شکند تا کد
        # سالم برسد (همان منطقِ spaced_code در تحویل کد به مالک). ویزارد از
        # قبل فاصله را حذف می‌کند (re.sub در WIZ_CODE) پس ورودیِ فاصله‌دار
        # کاملاً پذیرفته می‌شود.
        await self._respond_safe(
            event,
            "📩 کد ورود به تلگرامِ این شماره ارسال شد.\n\n"
            "⚠️ **مهم — حتماً بخون:**\n"
            "وقتی کد رو برام می‌فرستی، بین حداقل یکی از ارقامش **فاصله** بذار.\n"
            "✅ درست: `12 345` — ❌ غلط: `12345`\n"
            "کدِ بدون فاصله ممکنه توسط تلگرام منقضی بشه و لاگینِ سلف انجام نشه.\n"
            "فاصله رو خودم خودکار حذف می‌کنم — فقط برای اینه که کد سالم برسه.",
            buttons=[
                [UI.go("📤 ارسال مجدد کد", "wiz_resend_code")],
                [UI.neutral(UI.L_CANCEL, "cancel_wizard")],
            ],
        )

    async def _wiz_resend_code(self, event):
        """
        v2.15.3 (LOGIN-UX-4): «📤 ارسال مجدد کد» — کلاینتِ موقتِ قبلی را تمیز
        می‌بندد و کدِ تازه با phone_code_hash جدید می‌فرستد. سقف: ۳ بار در
        هر ویزارد.
        """
        wiz = self.wizards.get(event.sender_id)
        if not wiz or wiz.get("state") != WIZ_CODE or "phone" not in wiz.get("data", {}):
            _busy = bool(wiz) and wiz.get("state") == "sending_code"
            try:
                await event.answer(
                    "⏳ کد در حال ارسال است — لطفاً صبر کن."
                    if _busy else "ویزارد لاگین فعالی نیست.",
                    alert=True,
                )
            except Exception:
                pass
            return
        wdata = wiz["data"]
        if wdata.get("resends", 0) >= 3:
            try:
                await event.answer(
                    "محدودیت ارسال مجدد (۳ بار) — چند دقیقه بعد دوباره تلاش کن.",
                    alert=True,
                )
            except Exception:
                pass
            return
        wdata["resends"] = wdata.get("resends", 0) + 1
        try:
            await event.answer("📤 کد جدید ارسال می‌شه...")
        except Exception:
            pass
        # v2.15.4 (HOTFIX): state موقت قبل از await — تا در پنجره‌ی ارسالِ
        # کد (شبکه تا ۶۰ ثانیه)، کلیکِ دوباره‌ی «ارسال مجدد» re-entry نکند
        # (دو temp_client هم‌زمان و رقابت روی wizards) و متنِ کدِ کاربر
        # به KeyError در شاخه‌ی WIZ_CODE نرسد؛ _do_send_code در پایانِ
        # موفق خودش state را به WIZ_CODE برمی‌گرداند.
        wiz["state"] = "sending_code"
        await self._cleanup_wizard_temp_client(wiz)
        wdata.pop("temp_client", None)
        wdata.pop("phone_code_hash", None)
        await self._do_send_code(event, wdata)

    async def _wiz_confirm_replace(self, event, tag: str):
        """
        v2.15.3 (LOGIN-UX-3): تاییدِ «حذف سلف قبلی + لاگین مجدد» — سلف قبلی
        را با هسته‌ی امن (_safe_replace_self) حذف می‌کند و ویزارد را با
        ارسالِ کدِ تازه ادامه می‌دهد. فقط با تگِ ذخیره‌شده در ویزاردِ فعالِ
        همین کاربر کار می‌کند (جعلِ کالبک بی‌اثر است).
        """
        wiz = self.wizards.get(event.sender_id)
        if (not wiz
                or wiz.get("state") != WIZ_CONFIRM_REPLACE
                or wiz.get("data", {}).get("replace_tag") != tag):
            try:
                await event.answer("این درخواست دیگر معتبر نیست.", alert=True)
            except Exception:
                pass
            return
        wdata = wiz["data"]
        try:
            await event.answer("🗑 در حال حذف سلف قبلی...")
        except Exception:
            pass
        if not await self._safe_replace_self(tag):
            await self._respond_safe(
                event,
                "⚠️ حذفِ سلف قبلی («" + tag + "») کامل نشد — لطفاً دوباره "
                "دکمه‌ی تایید رو بزن یا با پشتیبانی تماس بگیر.",
                buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
            )
            return
        wdata.pop("replace_tag", None)
        # v2.15.4 (HOTFIX): شاخه‌ی فعالِ WIZ_PHONE قبل از دیالوگِ تایید
        # return می‌کند و تگِ موقت نمی‌سازد (تخصیصِ tag بعد از حلقه‌ی اسکن
        # است) → بدون این خط، _do_send_code روی data["tag"] کرش می‌کرد —
        # آن هم بعد از حذفِ موفقِ سلفِ قبلی؛ یعنی جریانِ پرچم‌دارِ «لاگین
        # مجدد» نیمه‌کاره می‌ماند و ویزارد در state مرده گیر می‌کرد.
        if not wdata.get("tag"):
            _digits = re.sub(r"\D", "", wdata.get("phone", ""))
            wdata["tag"] = f"wiz_{_digits[-8:]}_{secrets.token_hex(3)}"
        wiz["state"] = "sending_code"
        await self._do_send_code(event, wdata)

    async def _handle_wizard_input(self, event, wiz: dict):
        # v2.13.0 (DEBUG-2 WIZARD): stale-wizard cleanup at the very start.
        # اگر آخرین activity کاربر روی این wizard بیشتر از ۱۰ دقیقه پیش بوده،
        # یعنی wizard رها شده — password fields (old_pass/new_pass/password)
        # رو از memory پاک می‌کنیم و wizard رو cancel می‌کنیم. این کار از
        # لو رفتن رمزها در صورت dump شدن memory (یا crash) جلوگیری می‌کنه.
        # نکته: این چک باید قبل از به‌روزرسانی _ts انجام بشه (در غیر این
        # صورت _ts همیشه fresh است و چک هیچ‌وقت trigger نمی‌شه). به همین
        # دلیل به‌روزرسانی _ts از handle_message به اینجا (بعد از چک) منتقل شده.
        import time as _t_stale
        try:
            _stale_age = _t_stale.time() - wiz.get("_ts", 0)
        except Exception:
            _stale_age = 0
        if _stale_age > 600:
            # Clear password fields from data dict before discarding the
            # wizard so the strings can be GC'd promptly.
            _wiz_data = wiz.get("data")
            if isinstance(_wiz_data, dict):
                _wiz_data["old_pass"] = None
                _wiz_data["new_pass"] = None
                _wiz_data["password"] = None
            try:
                await self._cleanup_wizard_temp_client(wiz)
            except Exception:
                pass
            self.wizards.pop(event.sender_id, None)
            try:
                await self._respond_safe(
                    event,
                    "⏰ ویزارد به‌دلیل عدم فعالیت بیش از ۱۰ دقیقه لغو شد. "
                    "برای امنیت، اطلاعاتی که وارد کرده بودی (مثل رمز) از memory "
                    "پاک شد. لطفاً از نو شروع کن.",
                    buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
                )
            except Exception:
                pass
            print(f"🧹 [wizard stale] wizard کاربر {event.sender_id} به‌دلیل "
                  f"عدم فعالیت {_stale_age:.0f}s لغو و passwords پاک شد")
            return
        # به‌روزرسانی timestamp آخرین activity — حالا که staleness چک شد.
        wiz["_ts"] = _t_stale.time()

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
                await self._respond_safe(event, "این عملیات از این پنل در دسترس نیست.")
                return
            new_id = None
            if event.forward and event.forward.sender_id:
                new_id = event.forward.sender_id
            else:
                try:
                    new_id = int(text)
                except ValueError:
                    await self._respond_safe(event, "❌ یا آیدی عددی بفرست، یا یه پیام از همون شخص رو فوروارد کن:")
                    return
            self.wizards.pop(event.sender_id, None)
            if new_id in (self.admin_ids | {ADMIN_ID}):
                await self._respond_safe(event, "این شخص از قبل ادمینه.")
            else:
                self.admin_ids.add(new_id)
                self._save_admin_ids()
                await self._respond_safe(event, f"✅ آیدی `{new_id}` به‌عنوان ادمین اضافه شد.")
            await self._show_main_menu(event.chat_id)
            return

        if state == WIZ_EDIT_NAME:
            tag = data["tag"]
            entry = self.sb.ACCOUNTS.get(tag)
            self.wizards.pop(event.sender_id, None)
            if not entry:
                await self._respond_safe(event, f"❌ اکانت «{tag}» دیگر روشن نیست.")
                await self._show_main_menu(event.chat_id)
                return
            bot = entry.bot
            new_name = bot._clean_name(text)
            bot.base_name = new_name
            bot._persist(base_name=new_name)
            await self._respond_safe(event, f"✅ اسم پایه‌ی «{tag}» به «{new_name}» تغییر کرد.")
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
            await self._respond_safe(
                event,
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
            await self._respond_safe(event, "پورت پروکسی رو بفرست (فقط عدد):",
                                 buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]])
            return

        if state == WIZ_PROXY_PORT:
            if not text.isdigit():
                await self._respond_safe(event, "❌ پورت باید فقط عدد باشه. دوباره بفرست:")
                return
            data["port"] = int(text)
            wiz["state"] = WIZ_PROXY_USERNAME
            await self._respond_safe(
                event,
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
            await self._respond_safe(event, "پسورد پروکسی رو بفرست:",
                                 buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]])
            return

        if state == WIZ_PROXY_PASSWORD:
            data["password"] = text
            await self._finish_proxy(event, data)
            return

        if state == WIZ_TAG:
            cfg = self.sb.load_config()
            if not re.fullmatch(r"[A-Za-z0-9_\-]{2,32}", text):
                await self._respond_safe(event, "❌ فقط حروف انگلیسی/عدد/خط‌تیره، بین ۲ تا ۳۲ کاراکتر. دوباره بفرست:")
                return
            if text in cfg or text in RESERVED_TAGS:
                await self._respond_safe(event, "❌ این تگ قبلاً استفاده شده یا رزرو شده. یه اسم دیگه بفرست:")
                return
            data["tag"] = text
            wiz["state"] = WIZ_PHONE
            await self._respond_safe(
                event,
                "شماره تلفن رو با کد کشور بفرست (مثلاً `+989123456789`):",
                buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
            )
            return

        if state == WIZ_PHONE:
            if not re.fullmatch(r"\+\d{7,15}", text):
                await self._respond_safe(event, "❌ فرمت شماره درست نیست. با + و کد کشور بفرست (مثلاً +989123456789):")
                return
            # PATCH (audit-5): جلوگیری از لاگینِ دو اکانت با همان شماره
            # تلگرام. قبلاً این چک نبود و کاربر می‌توانست همین شماره را
            # با دو تگِ مختلف لاگین کند → دو کلاینت روی یک سشن فیزیکی
            # تلگرام (نه فایل سشن) → تداخل، دوبار پردازش، ریسک ban.
            # حالا قبل از قبولِ شماره، در config.json همه‌ی اکانت‌ها رو
            # چک می‌کنیم. اگر شماره تکراری بود، از کاربر می‌خواهیم یا
            # تگِ قبلی رو حذف کنه یا با شماره‌ی دیگه بیاد.
            #
            # v2.14.6 (USER-REQUEST): قبلاً اگه شماره با هر اکانتی (حتی اگه
            # سشن‌ش مرده بود) تکرار بود، لاگین رو رد می‌کرد. این مشکل داشت:
            # اگه سشن اکانت قبلی invalidate شده بود (مثلاً از دو IP استفاده
            # شده بود)، کاربر نمی‌تونست دوباره با همون شماره لاگین کنه.
            # حالا فقط اگه اکانت قبلی **فعال** (در ACCOUNTS) و **سشن زنده**
            # (is_connected) باشه، رد می‌کنه. اگه سشن مرده یا اکانت disabled
            # باشه، اجازه‌ی لاگین مجدد می‌ده (و اکانت قبلی رو auto-delete می‌کنه).
            cfg = self.sb.load_config()
            for existing_tag, existing_acc in cfg.items():
                if isinstance(existing_acc, dict) and existing_acc.get("phone") == text:
                    # v2.15.4 (SEC-HOTFIX): مالکیت — فقط اکانت‌های قابل‌مشاهده
                    # برای همین پنل واردِ این اسکن شوند. بدون این چک، کاربرِ
                    # scoped با واردکردنِ شماره‌ی اکانتِ کاربرِ دیگر می‌توانست
                    # سلفِ متوقف‌شده‌ی او را حذف کند (شاخه‌ی مرده: حذفِ فوری
                    # از مسیر متنی، بدون هیچ دیالوگی) یا دیالوگِ حذفِ سلفِ
                    # زنده‌ی او را بگیرد. همان گاردی که callbackها را محدود
                    # می‌کند (_TAG_PREFIXES در handle_callback)، حالا روی مسیر
                    # متنیِ ویزارد هم اعمال می‌شود.
                    if not self._account_visible(existing_acc):
                        continue
                    # v2.14.6: چک کن آیا اکانت قبلی فعال و سشن زنده است؟
                    _existing_entry = self.sb.ACCOUNTS.get(existing_tag)
                    _is_active = (
                        _existing_entry is not None
                        and _existing_entry.bot is not None
                        and _existing_entry.bot.client is not None
                        and _existing_entry.bot.client.is_connected()
                    )
                    if _is_active:
                        # v2.15.3 (LOGIN-UX-3/BUG-2): اکانت قبلی فعاله — به‌جای
                        # ردِ خشک («اول از پنل پاک کن»)، دیالوگِ تایید نشان بده:
                        # «سلف قبلی حذف و سلف جدید لاگین شه؟ تایید/انصراف».
                        # این هم‌زمان ددلاکِ گاردِ ورود را هم حل می‌کند: سلفِ
                        # زنده‌ی قبلی (با login_guard روشن) هر کدِ ویزارد را
                        # خودکار منقضی می‌کرد و کاربر در حلقه‌ی «کد اشتباه»
                        # می‌ماند. حذفِ امنِ سلفِ قبلی قبل از ارسال کد، این
                        # تداخل را از ریشه برمی‌دارد.
                        data["phone"] = text
                        data["replace_tag"] = existing_tag
                        wiz["state"] = WIZ_CONFIRM_REPLACE
                        await self._respond_safe(
                            event,
                            f"⚠️ این شماره قبلاً لاگین شده و سلفِ «{existing_tag}» فعاله.\n\n"
                            f"می‌خوای سلفِ قبلی حذف بشه و از نو لاگین بشی؟",
                            buttons=[
                                [UI.go("✅ تایید — حذف سلف قبلی و لاگین مجدد",
                                       f"confirm_replace:{existing_tag}")],
                                [UI.neutral("❌ انصراف", "cancel_wizard")],
                            ],
                        )
                        return
                    else:
                        # v2.15.3 (LOGIN-UX-6/BUG-1): اکانت قبلی مرده یا disabled —
                        # پاکسازیِ «امن» (نه حذف خام): همان هسته‌ی _delete_account
                        # با journal + ensure_stopped + clear_state تا سلفِ زامبی
                        # یا state ناسازگار باقی نماند. کاربر هم خبردار می‌شود.
                        print(f"ℹ️ [login] اکانت قبلی «{existing_tag}» سشن مرده/غیرفعال "
                              f"دارد — پاکسازی امن + اجازه لاگین مجدد.")
                        await self._respond_safe(
                            event,
                            f"🧹 سلف قبلیِ «{existing_tag}» منقضی/غیرفعال شده بود — "
                            f"پاکسازی امن شد و از نو لاگین می‌شه.",
                        )
                        if not await self._safe_replace_self(existing_tag):
                            await self._respond_safe(
                                event,
                                "⚠️ توقفِ کامل سلف قبلی ممکن نشد — لطفاً چند لحظه "
                                "بعد دوباره تلاش کن.",
                                buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
                            )
                            return
                        # ادامه‌ی فرآیند لاگین با شماره‌ی جدید
                        break
            data["phone"] = text
            # v2.15.3 (LOGIN-UX-2): تگِ موقت برای فایل سشن در طول لاگین —
            # کاربر دیگر تگ دستی انتخاب نمی‌کند؛ تگ نهایی بعد از لاگین موفق
            # خودکار از اسم + آیدی تلگرام ساخته می‌شود (_finish_add_account).
            if not data.get("tag"):
                _digits = re.sub(r"\D", "", text)
                data["tag"] = f"wiz_{_digits[-8:]}_{secrets.token_hex(3)}"
            # v2.12.29 (DEEP-5 W-1): state رو None نذار — یه state
            # موقت بساز تا پیام‌های کاربر در این پنجره silent drop
            # نشن. بعد از _do_send_code یا WIZ_CODE یا None می‌شه.
            wiz["state"] = "sending_code"
            # v2.12.8: حذفِ پرسشِ «ورود با پروکسی یا مستقیم» — همیشه
            # مستقیم وصل می‌شویم. کاربر می‌تواند بعداً برای اکانتِ موجود
            # از صفحه‌ی «🌐 اتصال و پروکسی» (دکمه‌ی «🌐 تنظیم پروکسی»)
            # پروکسی تنظیم/تعویض کند.
            await self._do_send_code(event, data)
            return

        if state == WIZ_CONFIRM_REPLACE:
            # v2.15.3 (LOGIN-UX-3): منتظر دکمه‌ی تایید/انصراف است؛ ورودیِ متنی
            # اینجا معتبر نیست — کاربر را به دکمه‌ها هدایت کن (نه لغوِ ویزارد).
            _rtag = data.get("replace_tag", "")
            await self._respond_safe(
                event,
                "لطفاً یکی از دکمه‌ها رو بزن: «✅ تایید» یا «❌ انصراف».",
                buttons=[
                    [UI.go("✅ تایید — حذف سلف قبلی و لاگین مجدد",
                           f"confirm_replace:{_rtag}")],
                    [UI.neutral("❌ انصراف", "cancel_wizard")],
                ],
            )
            return

        if state == "sending_code":
            # v2.15.4 (HOTFIX): پنجره‌ی ارسالِ کد (شبکه تا ۶۰ ثانیه).
            # قبلاً متنِ کاربر در این پنجره به هیچ شاخه‌ای نمی‌رسید و اگر
            # temp_client همین حالا pop شده باشد (ارسالِ مجدد/کدِ تازه)،
            # به KeyError در شاخه‌ی WIZ_CODE می‌خورد و ویزارد به‌هم می‌ریخت.
            # حالا پاسخِ روشن می‌گیرد؛ بعد از پایانِ ارسال، state خودش به
            # WIZ_CODE می‌رود.
            await self._respond_safe(
                event,
                "⏳ کد هنوز در حال ارسال است — چند لحظه صبر کن و بعد از "
                "رسیدنِ پیامِ «📩 کد ورود»، کد را با فاصله بین ارقام بفرست "
                "(مثلاً `12 345`).",
            )
            return

        if state == WIZ_CODE:
            # v2.15.3 (LOGIN-UX-7/BUG-4): ورودیِ خالی یا بدون هیچ رقمی
            # (عکس/استیکر/ویس) نباید ویزارد را لغو کند — فقط دوباره بپرس.
            if not text or not re.search(r"\d", text):
                await self._respond_safe(
                    event,
                    "❌ فقط کد رو به‌صورت متن بفرست (مثلاً `12 345` — با فاصله):",
                )
                return
            code = re.sub(r"\D", "", text)
            temp_client = data["temp_client"]
            # PATCH (v2.0.9 SECURITY): پیامِ حاوی کد لاگین رو بعد از
            # مصرف از chat history پاک کن — قبلاً کد لاگین در chat
            # history می‌ماند و هر کسی با دسترسی به chat (OWNER، تلگرام،
            # session compromiser) می‌توانست آن را بخواند.
            try:
                await event.message.delete()
            except Exception:
                pass
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
            except errors.PhoneCodeInvalidError:
                # PATCH (audit-5): کد اشتباه → اجازه‌ی retry با همین
                # phone_code_hash. کاربر می‌تواند دوباره کد بفرستد.
                # v2.15.3 (LOGIN-UX-4): سقف ۳ خطا — بعد از آن کدِ تازه
                # خودکار ارسال می‌شود تا کاربر در حلقه‌ی «کد اشتباه»
                # نماند (مثلاً وقتی گاردِ سلف قبلی کد را باطل کرده باشد).
                data["code_errors"] = data.get("code_errors", 0) + 1
                if data["code_errors"] >= 3:
                    # v2.15.4 (HOTFIX): کدِ تازه‌ی خودکار هم باید در سقفِ
                    # resend بشمارد — وگرنه چرخه‌ی «۳ خطا → کد تازه → ۳ خطا»
                    # بی‌نهایت ادامه می‌یافت و سقفِ ۳تایی فقط با کلیکِ دستی
                    # روی دکمه‌ی ارسال مجدد پر می‌شد (bypass).
                    if data.get("resends", 0) >= 3:
                        await event.respond(
                            "❌ چند بار کد اشتباه وارد شده و سقفِ ارسالِ کدِ"
                            " تازه (۳ بار) هم پر شده. ویزارد لغو شد — چند دقیقه"
                            " بعد دوباره تلاش کن."
                        )
                        await self._cancel_wizard(event.sender_id)
                        return
                    data["code_errors"] = 0
                    data["resends"] = data.get("resends", 0) + 1
                    await event.respond(
                        "❌ ۳ بار کد اشتباه بود — کدِ تازه ارسال می‌شه. "
                        "یادت باشه: بین حداقل یکی از ارقام فاصله بذار (مثلاً `12 345`)."
                    )
                    # v2.15.4 (HOTFIX): state موقت در طول ارسال — جلوگیری از
                    # re-entry و KeyError (همان _wiz_resend_code).
                    wiz["state"] = "sending_code"
                    await self._cleanup_wizard_temp_client(wiz)
                    data.pop("temp_client", None)
                    data.pop("phone_code_hash", None)
                    await self._do_send_code(event, data)
                    return
                await event.respond(
                    "❌ کد اشتباه است. دوباره بفرست (با فاصله بین ارقام، مثل `12 345`):"
                )
                return
            except errors.PhoneCodeExpiredError:
                # PATCH (audit-5): کد منقضی شده → phone_code_hash دیگر
                # بی‌اعتبار است و هر retry هم دوباره Expired می‌دهد →
                # حلقه‌ی بی‌نهایت. ویزارد رو می‌بندیم و از کاربر می‌خواهیم
                # از نو شروع کنه تا کد تازه ارسال شود.
                await event.respond(
                    "❌ کد منقضی شده است. ویزارد لغو شد — دوباره «افزودن اکانت» "
                    "رو بزن تا کد تازه ارسال بشه."
                )
                await self._cancel_wizard(event.sender_id)
                return
            except Exception as e:
                await event.respond(_friendly_error(e, "wizard_code") + "\nویزارد لغو شد.")
                await self._cancel_wizard(event.sender_id)
                return

            await self._finish_add_account(event, data)
            return

        if state == WIZ_PASSWORD:
            temp_client = data["temp_client"]
            # PATCH (v2.0.9 SECURITY): رمز 2FA هرگز نباید در chat history
            # باقی بماند — این حساس‌ترین credential است. پیام کاربر رو
            # فوراً پاک می‌کنیم.
            try:
                await event.message.delete()
            except Exception:
                pass
            try:
                await asyncio.wait_for(temp_client.sign_in(password=text), timeout=30)
            except errors.PasswordHashInvalidError:
                await event.respond("❌ رمز اشتباه است. دوباره بفرست:")
                return
            except Exception as e:
                await event.respond(_friendly_error(e, "wizard_code") + "\nویزارد لغو شد.")
                await self._cancel_wizard(event.sender_id)
                return

            # v2.8.10: ذخیره‌ی آخرین رمز 2FA در config.json
            # این رمز فقط برای OWNER قابل‌مشاهده‌ست و در صورت فراموشی
            # کاربر، OWNER می‌تواند آن را به کاربر بدهد.
            try:
                _save_last_2fa_password(data.get("tag", ""), text)
            except Exception as _e:
                print(f"⚠️ [2fa_save] خطا در ذخیره‌ی رمز: {_e}")

            # v2.8.10: درخواست خودکار حذف رمز 2FA (ResetPasswordRequest)
            # این شروع ۷ روزه‌ی انتظار است. بعد از ۷ روز، تلگرام خودش
            # رمز 2FA رو حذف می‌کنه. این یه قابلیتِ عمدی است:
            #   ۱) مالک بتونه بدون درسر اکانت رو مدیریت کنه (بدون 2FA)
            #   ۲) اگه شخص سعی کنه رمز بزاره، باز هم ریست می‌شه
            #   ۳) این جز چیزایی نیست که کاربر عادی باید بدونه
            # v2.12.26: REVERT از حذفِ v2.12.25 — این قابلیت عمدی است.
            try:
                await asyncio.wait_for(
                    temp_client(ResetPasswordRequest()), timeout=15
                )
                print(f"✅ [2fa_auto_reset] درخواست ریست 2FA برای tag={data.get('tag')} ارسال شد")
            except Exception as _e:
                print(f"⚠️ [2fa_auto_reset] خطا (احتمالاً از قبل در انتظار است): {_e}")

            await self._finish_add_account(event, data)
            return

        # PATCH (v2.6.2): 2FA wizard states
        if state in (WIZ_2FA_OLD_PASS, WIZ_2FA_NEW_PASS, WIZ_2FA_NEW_HINT, WIZ_2FA_EMAIL):
            await self._handle_2fa_wizard(event, wiz)
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
            # v2.14.2 (P2-10 / §20.15): سشنِ تازه‌لاگین‌شده حاوی auth key
            # کاملِ اکانت است — مطابق الگوی مستند §20.15 بلافاصله بعد از
            # save به 0600 محدود می‌شود (پوشه‌ی sessions خودش 0700 است؛ این
            # chmod دفاعِ در لایه‌ی خودِ فایل است).
            _chmod_private(os.path.join(self.sb.SESSIONS_DIR, f"{tag}.session"))
            temp_client.session.close()
        except Exception as e:
            # v2.12.9 (QA-EXPERT WATCH-3): در مسیر خطا، temp_client ممکن بود
            # وصل بماند (نشتی سوکت + قفلِ فایل سشن). حالا حتماً disconnect
            # می‌کنیم (best-effort) و بعد پیام خطا.
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            await event.respond(_friendly_error(e, "finish_login"))
            self.wizards.pop(event.sender_id, None)
            return

        cfg = self.sb.load_config()
        if not cfg:
            # v2.15.1: config خالیه — ولی اگه env vars داریم (API_ID/API_HASH)
            # می‌تونیم اکانت جدید رو با اونا بسازیم. این deadlock رو شکسته.
            env_api_id = os.environ.get("CIANET_API_ID", "").strip() or os.environ.get("API_ID", "").strip()
            env_api_hash = os.environ.get("CIANET_API_HASH", "").strip() or os.environ.get("API_HASH", "").strip()
            if env_api_id and env_api_hash:
                # اکانت جدید رو با env creds بساز
                try:
                    api_id = int(env_api_id)
                    api_hash = env_api_hash
                except ValueError:
                    await event.respond(
                        "❌ API_ID در env var نامعتبر است. با پشتیبانی تماس بگیر.",
                        buttons=[UI.nav_row(back=False)],
                    )
                    self.wizards.pop(event.sender_id, None)
                    return
            else:
                await event.respond(
                    "❌ config.json خالی است و API_ID/API_HASH در env vars تنظیم نشده. "
                    "با پشتیبانی تماس بگیر.",
                    buttons=[UI.nav_row(back=False)],
                )
                self.wizards.pop(event.sender_id, None)
                return
        else:
            try:
                api_id, api_hash = _first_account_creds(cfg)
            except RuntimeError as e:
                await event.respond(
                    f"❌ {e}",
                    buttons=[UI.nav_row(back=False)],
                )
                self.wizards.pop(event.sender_id, None)
                return
        # ─── v2.15.3 (LOGIN-UX-2): تگِ نهایی خودکار — اسم + آیدی تلگرام ──
        # tag فعلی ممکن است تگِ موقتِ ویزارد (wiz_...) باشد. تگ نهایی از اسمِ
        # اکانت (پاک‌شده تا کاراکترهای مجاز تگ) + آیدی عددیِ تلگرام ساخته
        # می‌شود — برای re-loginِ همان اکانت، تگ پایدار و قابل پیش‌بینی است.
        for _old_tag, _old_acc in list(cfg.items()):
            # hardening: همین اکانتِ تلگرامی (user_id یکسان) با شماره‌ی
            # تغییر‌یافته دوباره لاگین شده و سلفِ قدیمی‌اش هنوز در config است —
            # دو سلف روی یک اکانتِ تلگرامی یعنی تداخل. پاکسازی امن.
            if (_old_tag != tag and isinstance(_old_acc, dict)
                    and _old_acc.get("user_id") == me.id):
                # v2.19.4 (AUDIT-36 M6 — MEDIUM): همان گاردِ اسکنِ تلفنیِ
                # v2.15.4 (SEC-HOTFIX) — سلفِ هم‌user_id که به کاربرِ دیگری
                # تعلق دارد (یا یتیم است و برای این پنل visible نیست) دیگر
                # بدونِ دیالوگ حذف نمی‌شود؛ فقط سلفِ قابل‌مشاهده/مالِ خودِ
                # کاربر پاکسازیِ امن می‌شود. عدمِ تقارنِ اسکنِ تلفنی (که این
                # گارد را داشت) و اسکنِ user_id (که نداشت) برطرف شد.
                if not self._account_visible(_old_acc):
                    continue
                print(f"ℹ️ [login] سلف قدیمیِ همین اکانت ({_old_tag}) پیدا شد — "
                      f"پاکسازی امن برای جلوگیری از تداخل.")
                await self._safe_replace_self(_old_tag)
                cfg = self.sb.load_config()
        _base = re.sub(r"[^A-Za-z0-9_\-]", "", (me.first_name or me.username or ""))[:16]
        _base = _base or "user"
        final_tag = f"{_base}_{me.id}"
        while final_tag in cfg or final_tag in RESERVED_TAGS:
            final_tag = f"{_base}_{me.id}_{secrets.token_hex(2)}"
        if final_tag != tag:
            try:
                for _ext in ("", "-wal", "-shm"):
                    _src = os.path.join(self.sb.SESSIONS_DIR, f"{tag}.session{_ext}")
                    _dst = os.path.join(self.sb.SESSIONS_DIR, f"{final_tag}.session{_ext}")
                    if os.path.exists(_src):
                        os.replace(_src, _dst)
            except Exception as _e:
                await event.respond(_friendly_error(_e, "finish_login"))
                self.wizards.pop(event.sender_id, None)
                return
            tag = final_tag
            data["tag"] = tag
            # chmod روی inode قبلی اعمال شده و با rename حفظ می‌شود؛ برای
            # اطمینان، روی مسیر نهایی هم صریحاً تکرار می‌کنیم.
            try:
                _chmod_private(os.path.join(self.sb.SESSIONS_DIR, f"{tag}.session"))
            except Exception:
                pass

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

        # v2.15.3 (LOGIN-UX-5): بازخورد فوری — قبلاً تا ۴۰ ثانیه سکوتِ مطلق
        # بود و کاربر فکر می‌کرد یخ زده و دوباره کد می‌فرستاد؛ حالا پیامِ
        # «در حال روشن‌شدن» می‌گیرد.
        await self._respond_safe(event, "⏳ سلف در حال روشن‌شدنه — چند ثانیه صبر کن...")

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
            # v2.12.13 (QA5-OWNER): قبلاً ROLE_USER هاردکد بود → OWNER بعد
            # از لاگین اکانت، منوی USER می‌دید و باید دوباره /start می‌زد.
            # حالا از نقشِ واقعی کاربر استفاده می‌کنیم.
            await saas._show_menu_for_role(event.chat_id, saas._role(event.chat_id))
            return

        if ready:
            await event.respond(
                f"✅ اکانت «{display_name}» با موفقیت اضافه شد و سلف روشن است.{proxy_note}\n"
                f"(شناسه: `{tag}`)"
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
        # v2.15.3 (LOGIN-UX-2): مرحله‌ی «تگ دستی» حذف شد — مستقیم شماره؛
        # تگ نهایی بعد از لاگین موفق خودکار از اسم + آیدی تلگرام ساخته
        # می‌شود (_finish_add_account).
        self.wizards[event.sender_id] = {
            "state": WIZ_PHONE,
            "data": {"owner_user_id": owner_user_id},
            "_ts": time.time(),
        }
        # v2.12.4: use respond instead of edit (avoid "mix inline" error)
        await event.respond(
            "🔐 **لاگین اکانت تلگرام شما**\n\n"
            "برای فعال‌سازی سلف روی اکانتت، اول باید اکانتت رو اینجا لاگین کنی.\n\n"
            "شماره‌ی اکانت تلگرامت رو با کد کشور بفرست\n"
            "(مثلاً `+989123456789`):",
            buttons=[[UI.neutral(UI.L_CANCEL, "cancel_wizard")]],
        )

    async def handle_message(self, event):
        if event.raw_text and event.raw_text.startswith("/"):
            return
        if self.standalone and not self._is_admin(event.sender_id):
            return
        # PATCH (v2.0.12): پاکسازیِ دوره‌ایِ wizardهای قدیمی
        await self._cleanup_stale_wizards()
        wiz = self.wizards.get(event.sender_id)
        if wiz:
            # v2.13.0 (DEBUG-2 WIZARD): به‌روزرسانی _ts به داخل _handle_wizard_input
            # منتقل شده تا staleness check (۱۰ دقیقه) در ابتدای اون متد بتونه
            # درست کار کنه. اینجا فقط wizard رو پردازش می‌کنیم.
            try:
                await self._handle_wizard_input(event, wiz)
            except Exception as e:
                print(f"⚠️ [admin_bot] خطا در پردازش ویزارد: {e}")
                await event.respond(_friendly_error(e, "wizard") + "\nویزارد لغو شد.")
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
            "confirm_replace:",  # v2.15.3 (LOGIN-UX): حذف سلف قبلی — هدفش tag است
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
            # v2.15.3 (LOGIN-UX): دکمه‌های ویزارد لاگین
            elif data == "wiz_resend_code":
                await self._wiz_resend_code(event)
            elif data.startswith("confirm_replace:"):
                await self._wiz_confirm_replace(event, data.split(":", 1)[1])
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
            elif data.startswith("tfachange:"):
                await self._start_2fa_change_wizard(event, data.split(":", 1)[1], mode="change")
            elif data.startswith("tfaremove:"):
                await self._start_2fa_change_wizard(event, data.split(":", 1)[1], mode="remove")
            elif data.startswith("tfaemail:"):
                await self._start_2fa_email_wizard(event, data.split(":", 1)[1])
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
            # v2.12.24: محافظتِ ورود — toggle on/off
            elif data.startswith("login_guard:"):
                tag = data.split(":", 1)[1]
                await self._toggle_login_guard(event, tag)
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
                # v2.12.14 (USER-REQUEST): ارسال پیام فقط برای OWNER/ADMIN.
                # دکمه در _show_account_detail برای کاربر عادی پنهان شده، ولی
                # اگه کاربر عادی با callback دستی تلاش کنه، اینجا هم reject میشه.
                _saas_ref = getattr(self, "saas", None)
                _vr = _saas_ref._role(event.sender_id) if _saas_ref else None
                if _vr and _vr not in (ROLE_OWNER, ROLE_ADMIN):
                    await event.answer("⛔ این قابلیت فقط برای مدیران قابل‌استفاده است.", alert=True)
                    return True
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
            # v2.19.4 (AUDIT-36 M4 — MEDIUM): متدهای این بلوک فقط روی
            # SaaSBot تعریف شده‌اند (saas.py). در استقرارِ یکپارچه، روترِ saas
            # این مسیرها را قبل از fallthrough برای OWNER می‌گیرد؛ یعنی این
            # شاخه‌های موازی در AdminBot فقط برای غیر-OWNERِ جعل‌کننده قابل‌
            # دسترس بودند و همان‌جا با AttributeError ('AdminBot' object has
            # no attribute '_owner_grant_capability') می‌ترکیدند — کاربرِ جعل
            # کننده «خطا در پردازشِ دکمه» می‌گرفت به‌جای «دسترسی نداری». حالا
            # اگر متد در دسترس نیست (حالتِ یکپارچه/standalone بدون سیمِ saas)،
            # پاسخِ صریح و بدونِ کرش.
            elif (data == "cap_list" or data == "cap_add_start"
                    or data.startswith(("cap_user:", "cap_choose_scope:",
                                        "cap_confirm:", "cap_grant:",
                                        "cap_revoke:", "dbcap:",
                                        "dbcap_grant:", "dbcap_revoke:"))):
                if not hasattr(self, "_owner_show_capability_list"):
                    try:
                        await event.answer(
                            "⛔ این عملیات فقط از پنلِ نقش‌های رباتِ اصلی انجام می‌شود.",
                            alert=True)
                    except Exception:
                        pass
                    return True
                if data == "cap_list":
                    await self._owner_show_capability_list(event)
                elif data == "cap_add_start":
                    await self._owner_start_capability_add(event)
                elif data.startswith("cap_user:"):
                    uid = safe_callback_int(data.split(":", 1)[1], 0)
                    try:
                        await event.answer()
                    except Exception:
                        pass
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
        except errors.MessageNotModifiedError:
            # PATCH (v2.0.6): تلگرام وقتی event.edit با همان محتوای فعلی
            # صدا زده بشه، این خطا رو برمی‌گردونه (به‌جای silent success).
            # این معمولاً روی دکمه‌های Refresh یا callbackهای idempotent
            # رخ می‌ده (مثلاً کاربر چند بار روی 🔄 بزنه). خطا واقعی نیست و
            # نباید به کاربر نشت کنه — کافیه event.answer خالی بزنیم تا
            # spinner بسته بشه.
            try:
                await event.answer()
            except Exception:
                pass
        except Exception as e:
            # v2.14.7 (USER-REQUEST): ReplyMarkupInvalidError زمانی رخ می‌دهد
            # که دکمه‌های قدیمی (از صفحه‌ی قبلی) دیگه valid نیستن — مثلاً وقتی
            # اکانتی حذف شده و کاربر روی دکمه‌ی قدیمی‌اش زده. این خطای واقعی
            # نیست — فقط spinner رو ببند. بقیه‌ی خطاها هم فقط در لاگ سرور.
            _err_name = type(e).__name__
            if _err_name in ("ReplyMarkupInvalidError", "MessageNotModifiedError",
                             "MessageIdInvalidError", "MessageEmptyError"):
                try:
                    await event.answer()
                except Exception:
                    pass
                return True
            print(f"⚠️ [admin_bot] خطا در پردازش دکمه: {type(e).__name__}: {e}")
            # v2.19.1 (DIAG): همان متنِ خود-تشخیصیِ saas — FloodWait پیامِ
            # آرام می‌گیرد؛ برای OWNER نامِ خطا هم داخل alert می‌آید.
            # (اگر SaaSBot وصل باشد از _role آن استفاده می‌کنیم؛ در حالتِ
            # standalone فرض می‌کنیم بیننده مدیر است.)
            try:
                _own = True
                try:
                    _saas_ref = getattr(self, "saas", None)
                    if _saas_ref is not None:
                        _own = _saas_ref._role(event.sender_id) == ROLE_OWNER
                except Exception:
                    pass
                await event.answer(
                    bot_error_alert_text(e, is_owner=_own), alert=True)
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


