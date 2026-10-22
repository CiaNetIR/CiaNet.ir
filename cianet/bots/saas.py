"""SaaSBot — ربات کاربران: اشتراک/لایسنس، کیف پول، فعال‌سازی، پشتیبانی.

این فایل به‌صورت مکانیکی از main.py تک‌فایلی تفکیک شده است (v2.16.0).
بدنه‌ی کلاس‌ها بایت‌به‌بایت همان main.py است؛ فقط هدرِ import تولید شده.
"""

# stdlib / third-party — همان importهای اصلی main.py
from telethon import Button
from telethon import TelegramClient
import asyncio
from datetime import datetime
from telethon import errors
from telethon import events
import hashlib
import os
import re
import secrets
import shutil
import tempfile
import time
from datetime import timedelta
from datetime import timezone

# هسته‌ی مشترک — ثابت‌ها/توابع مشترک
from cianet.core import (
    ACTIVATION_HELP_TEXT,
    ADMIN_BOT_SESSION_NAME,
    ADMIN_BOT_TOKEN,
    ADMIN_ID,
    BACKUP_HOURS_IRAN,
    BATCH_LICENSE_MAX,
    bot_error_alert_text,
    CAP_ACCOUNT_SECURITY,
    CIANET_LANG,
    CONFIG_VALID,
    DEDICATED_BOT_PLAN,
    DEDICATED_UI_STATE,
    DEFAULT_CARD_HOLDER,
    DEFAULT_CARD_NUMBER,
    FEATURE_LABELS,
    GROUP_SEATS_CHOICES,
    GROUP_SUB_SETTING_KEY,
    LICENSE_TYPE_ACCOUNT,
    LICENSE_TYPE_ADMIN,
    LICENSE_TYPE_RESELLER,
    NAV_BACK,
    NAV_HOME,
    NAV_NOOP,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING,
    OWNER_ID,
    OWNER_IDS,
    PROVISION_LICENSE,
    PROVISION_MANUAL,
    PROVISION_SUBSCRIPTION,
    REFERRAL_GOAL,
    REFERRAL_REWARD_DAYS,
    ROLE_ADMIN,
    ROLE_OWNER,
    ROLE_RESELLER,
    ROLE_USER,
    SCOPE_DEDICATED_BOT,
    SCOPE_RESELLER,
    SELF_BACKUP_ENABLED_SETTING,
    SELF_BACKUP_GROUP_SETTING,
    SELF_FEATURE_LIST,
    SESSIONS_DIR,
    SUPPORT_UNITS,
    TRIAL_DAYS_MAX,
    TRIAL_DAYS_MIN,
    TRIAL_DAYS_SETTING,
    TRIAL_SETTING_KEY,
    USDT_TOMAN_FALLBACK,
    WHAT_IS_SELFBOT_TEXT,
    WIZ_CAP_USER_ID,
    WIZ_CL_BATCH_MAX_USES,
    WIZ_CL_BATCH_QTY,
    WIZ_CL_BATCH_RESELLER_LIMIT,
    WIZ_CL_MAX_USES,
    WIZ_CL_RESELLER_LIMIT,
    WIZ_DB_RESTORE,
    WIZ_DB_RESTORE_CONFIRM,
    WIZ_DB_RESTORE_PASS,
    WIZ_DEDICATED_EXTEND_DAYS,
    WIZ_DEDICATED_OWNER_ID,
    WIZ_DEDICATED_TOKEN,
    WIZ_DISCOUNT_APPLY_CODE,
    WIZ_DISCOUNT_MAX_USES,
    WIZ_DISCOUNT_PERCENT,
    WIZ_LICENSE_CODE,
    WIZ_ORPHAN_ASSIGN,
    WIZ_OWNER_TICKET_REPLY,
    WIZ_PAYMENT_RECEIPT,
    WIZ_PRICING_DAYS,
    WIZ_PRICING_NEW_NAME,
    WIZ_PRICING_PRICE,
    WIZ_REPORTER_CAP,
    WIZ_REPORTER_DUP,
    WIZ_REPORTER_FLOW,
    WIZ_REPORTER_TARGET,
    WIZ_SELF_BACKUP_GROUP,
    WIZ_SET_CARD,
    WIZ_SET_CHANNEL,
    WIZ_TRIAL_DAYS,
    WIZ_SET_WALLET,
    WIZ_TICKET_MSG,
    WIZ_TICKET_UNIT,
    WIZ_TRX_HASH,
    WIZ_USER_EXTEND_DAYS,
    WIZ_USER_SEARCH,
    WIZ_WALLET_CREDIT_AMOUNT,
    WIZ_WALLET_CREDIT_REASON,
    WIZ_WALLET_DEBIT_AMOUNT,
    WIZ_WALLET_DEBIT_REASON,
    _ADMIN_CLIENT_REF,
    _AUTO_UPDATE_TASK,
    _DATETIME_FMT,
    _GATE_RETRY_COOLDOWN,
    _SAAS_BOT_REF,
    _SCOPE_LABELS,
    _TYPE_NAMES,
    _acc_ui_state,
    _auto_update_loop_wrapper,
    _conn,
    _conn_immediate,
    _first_account_creds,
    _format_date,
    _friendly_error,
    _get_usd_toman_rate,
    _is_nav_action,
    _license_batch_result_text,
    _license_result_text,
    _normalize_channel,
    _now,
    _now_date,
    _parse_date,
    _process_alive,
    _project_dir,
    _read_pidfile,
    _security_main_owner_id,
    _set_lang,
    _spawn_bg,
    _spawn_dedicated_bot,
    _stop_process_by_pid,
    _subscription_days_left,
    _to_int,
    _update_reseller_application,
    _verify_trc20_transfer,
    account_belongs_to,
    account_is_orphan,
    accounts_of_user,
    activate_license,
    add_admin_or_reseller,
    add_ticket_message,
    apply_discount_code,
    approve_card_payment_atomic,
    attach_referrer,
    auto_renew_subscription,
    block_saas_user,
    build_backup_zip,
    cancel_order,
    capability_grant_exists,
    claim_referral_rewards,
    close_ticket,
    config_state,
    create_dedicated_bot,
    create_discount_code,
    create_license,
    create_license_batch,
    create_order,
    create_payment,
    create_subscription,
    create_ticket,
    create_zarinpal_payment,
    create_zibal_payment,
    deactivate_license,
    dedicated_bot_price,
    delete_license,
    delete_user_completely_async,
    ensure_started,
    ensure_stopped,
    expire_order,
    expire_subscription,
    extend_order,
    fa_digits,
    fa_weekday,
    get_active_grants,
    get_active_subscription,
    get_auto_renew_enabled,
    get_dedicated_bot,
    get_license,
    get_open_ticket,
    get_order,
    get_payment,
    get_pending_dedicated_bot_for_reseller,
    get_pricing,
    get_required_chats,
    get_reseller_application,
    get_role,
    get_setting,
    get_ticket,
    get_user,
    get_wallet_balance,
    grant_capability,
    grant_trial_if_eligible,
    group_sub_discount_percent,
    group_sub_enabled,
    inc_setting,
    init_db,
    iran_now,
    is_group_plan,
    is_user_blocked,
    jalali_date,
    jalali_long,
    list_active_dedicated_bots,
    list_admins_and_resellers,
    list_all_users,
    list_capability_grants,
    list_dedicated_bots,
    list_discount_codes,
    list_expired_orders,
    list_expired_subscriptions,
    list_expiring_subscriptions,
    list_licenses,
    list_open_tickets,
    list_pending_payments,
    list_pending_reseller_applications,
    list_pricing,
    list_recent_orders,
    list_ticket_messages,
    list_user_orders,
    list_users_for_reseller,
    list_wallet_transactions,
    log_action,
    mark_warned,
    normalize_card_number,
    parse_referral_arg,
    pay_order_trc20_atomic,
    pay_order_wallet_atomic,
    referral_link,
    referral_stats,
    register_group_plan,
    remove_admin_or_reseller,
    REQUIRED_CHATS_MAX,
    reseller_user_count,
    restore_backup_from_zip_async,
    _decrypt_cnb1_to_temp,
    review_payment_atomic,
    revoke_capability,
    safe_callback_int,
    search_users,
    self_backup_enabled,
    self_backup_group,
    set_active_subscription_expired,
    set_order_payment_id,
    set_pricing,
    set_required_chats,
    set_setting,
    ticket_message_count,
    trial_days,
    trial_enabled,
    toggle_discount_code,
    unblock_saas_user,
    unlink_customer,
    update_dedicated_bot_status,
    upsert_user,
    validate_backup_zip,
    wallet_credit,
    wallet_debit,
    wallet_pay_from_balance,
)

# کلاس‌های هم‌خانواده / توابعِ جابه‌جا‌شده
from cianet.bots.ui import NavStack, UI
from cianet.bots.admin import AdminBot
# v2.17.0: اسکلتِ بخش «ریپورتر» — نقطه‌ی اتصالِ آینده (فعلاً غیرفعال)
from cianet.bots import reporter as reporter_module


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
        # v2.15.0: announce feature — بدون wizard، ساده و قابل اعتماد
        self._announce_pending: set = set()
        self._announce_text: dict = {}
        # PATCH (v2.0.12): wizard TTL. هر wizard یک timestamp ست می‌شه و
        # وقتی از ۳۰ دقیقه بگذره، خودکار پاک می‌شه (و temp_client disconnect).
        # این از نشتِ TCP socket و session file lock در wizardهای رها‌شده
        # جلوگیری می‌کنه.
        self._WIZARD_TTL_SEC = 30 * 60
        self._last_wizard_gc = 0.0
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
        # BUG-26: مهرِ زمانیِ آخرین بسته‌شدنِ هر کاربر (user_id → ts) — فقط
        # برای هرسِ TTL محدودِ _gate_blocked در _prune_gate_state؛ خودِ
        # مجموعه همان set می‌ماند تا بقیه‌ی کد (discard) تغییر نکند.
        self._gate_blocked_ts: dict = {}
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
        # BUG-16a: اگر start بعد از ساختِ کلاینت شکست بخورد (مثلاً
        # timeout یا خطای احراز هویت)، کلاینتِ نیمه‌استارت‌شده باید قطع شود
        # تا connection نشت نکند؛ خطا عیناً به بالا برمی‌گردد.
        try:
            await asyncio.wait_for(self.client.start(bot_token=ADMIN_BOT_TOKEN), timeout=30)
        except Exception:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            raise

        # ثبتِ رفرنس تا SelfBotها بتوانند «کدِ لاگین» را از طریقِ همین ربات
        # به مالک برسانند.
        global _SAAS_BOT_REF
        _SAAS_BOT_REF = self

        # PATCH (v2.0.10): reference به client رو در ماژول نگه دار تا
        # _owner_notify_async بتونه به OWNER پیام بفرسته.
        global _ADMIN_CLIENT_REF
        _ADMIN_CLIENT_REF["client"] = self.client

        # یوزرنیمِ خودِ ربات — برای ساختِ لینکِ دعوت
        try:
            me = await asyncio.wait_for(self.client.get_me(), timeout=15)
            self._bot_username = getattr(me, "username", None)
        except Exception:
            self._bot_username = None

        # admin_panel از همان کلاینت مشترک استفاده می‌کند — ولی خودش دیگر
        # هندلر جداگانه ثبت نمی‌کند (فقط متدهایش مستقیماً فراخوانی می‌شوند)
        self.admin_panel.client = self.client

        # v2.12.12 (QA4-DEBUG/OWNER): pre-warm dialog cache برای جلوگیری از
        # hang در event.respond / event.edit. وقتی کاربر روی دکمه می‌زنه و
        # event.respond صدا زده می‌شه، telethon داخلی get_input_chat() رو
        # صدا می‌زنه که اگه entity cache گرم نباشه، iter_dialogs(100) رو
        # فراخوانی می‌کنه که می‌تونه hang کنه. اینجا در startup، cache رو
        # گرم می‌کنیم تا در runtime این مشکل پیش نیاد. best-effort — اگه
        # ناموفق بود، ربات بالا میاد ولی ممکنه بعضی callbackها کند باشن.
        # v2.12.13 (QA5-EXPERT): timeout aggregate اضافه شد تا خودِ startup
        # هم hang نکنه اگه iter_dialogs هم هنگ کنه.
        try:
            print("🔄 [saas_bot] pre-warming dialog cache (limit=100)...")
            async def _warmup():
                _warmup_count = 0
                async for _ in self.client.iter_dialogs(limit=100):
                    _warmup_count += 1
                    if _warmup_count >= 100:
                        break
                return _warmup_count
            _n = await asyncio.wait_for(_warmup(), timeout=30)
            print(f"✅ [saas_bot] dialog cache warmed ({_n} dialogs)")
        except asyncio.TimeoutError:
            print(f"⚠️ [saas_bot] dialog cache warmup TIMED OUT after 30s (continuing)")
        except Exception as _e:
            print(f"⚠️ [saas_bot] dialog cache warmup failed (continuing): "
                  f"{type(_e).__name__}: {_e}")

        self._register_handlers()

        if self._expiry_task is None or self._expiry_task.done():
            self._expiry_task = asyncio.create_task(self._expiry_loop())
        if self.admin_panel._backup_task is None or self.admin_panel._backup_task.done():
            self.admin_panel._backup_task = asyncio.create_task(self.admin_panel._daily_backup_loop())
        # v2.22.1 (AUDIT-39/a#1 + c#1 · CRITICAL): بکاپِ ساعتیِ سلف‌ها هم در
        # مسیرِ اصلی production اسپاون می‌شود. این حلقه قبلاً فقط در
        # AdminBot.start() (مسیرِ fallbackِ standalone) ساخته می‌شد — یعنی
        # فیچرِ پرچمدارِ v2.22.0 در production کاملاً مرده بود: مالک گروه را
        # تنظیم می‌کرد، «روشن» می‌دید و هیچ بکاپی نمی‌گرفت. (الگویِ همان
        # دو خطِ بالا که مسیرِ درست را نشان می‌داد.)
        if (self.admin_panel._self_backup_task is None
                or self.admin_panel._self_backup_task.done()):
            self.admin_panel._self_backup_task = asyncio.create_task(
                self.admin_panel._self_backup_loop())

        print("🤖 ربات CiaNetSelf (نقش‌محور) با موفقیت روشن شد.")
        return self.client

    async def _cancel_bg_tasks(self):
        """
        v2.22.1 (AUDIT-39/c#3): لغوِ تمیزِ تسک‌های پس‌زمینه‌ی این نمونه —
        expiry + بکاپِ روزانه + بکاپِ ساعتیِ سلف‌ها.

        چرا لازم است: حلقه‌های forever در هر سیکلِ reconnect یک شیءِ تازهٔ
        ربات می‌سازند؛ guardِ None/done روی نمونهٔ تازه پاس می‌شود در حالی که
        تسک‌های نمونهٔ قبلی هنوز زده‌اند و تا ابد زنده می‌مانند (نشتِ تسک +
        ارسالِ بکاپِ تکراری از کلاینتِ کهنه که ممکن است خودش را دوباره وصل
        کند). run_saas_bot_forever بعد از هر قطعی این متد را صدا می‌زند.
        """
        tasks = [self._expiry_task,
                 self.admin_panel._backup_task,
                 self.admin_panel._self_backup_task]
        for t in tasks:
            if t is not None and not t.done():
                t.cancel()
        for t in tasks:
            if t is None:
                continue
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    def _role(self, user_id: int) -> str:
        return get_role(user_id, OWNER_ID)

    def _user_has_logged_in_account(self, user_id: int) -> bool:
        """
        آیا این کاربر حداقل یک اکانت سلف دارد که خودش لاگین کرده؟
        v2.15.3 (LOGIN-UX-3): این تابع دیگر «دروازه‌ی لاگین مجدد» نیست (هارد‌بلاک
        حذف شد و کاربر می‌تواند دوباره ویزارد لاگین را شروع کند). کاربرد فعلی:
        نمایش/آمار منوی کاربر (مثلاً نمایش دکمه‌ی «لاگین کردن سلف»). یک اکانت
        «لاگین‌شده» یعنی اکانتی در config.json که owner_user_id آن برابر همین
        کاربر است (چه الان روشن باشد چه خاموش/غیرفعال).
        """
        cfg = self.sb.load_config()
        return any(account_belongs_to(acc, tag, user_id)
                   for tag, acc in cfg.items())

    # ─────────────────────────────────────────────────────
    #  گیت عضویت کانال اجباری (همه به‌جز ادمین اصلی)
    # ─────────────────────────────────────────────────────

    async def _chat_entity(self, chat: str):
        """
        resolve چت بر اساسِ نوعِ ورودی — v2.22.0: آیدیِ عددی (گروهِ
        خصوصی/سوپرگروه؛ ربات باید آن را بشناسد یعنی عضو باشد) یا
        یوزرنیم/لینک (چتِ عمومی). تنها نقطهٔ resolve گیتِ چندچتی.
        """
        s = str(chat or "").strip()
        if s.lstrip("-").isdigit():
            return await self.client.get_entity(int(s))
        return await self.client.get_entity(s)

    async def _is_channel_member(self, user_id: int, channel: str) -> bool:
        """
        چک عضویت در یک کانال/گروهِ اجباری. channel می‌تواند یوزرنیم
        (با/بدون @)، لینک t.me یا آیدیِ عددیِ چت باشد (v2.22.0 — گروه‌های
        خصوصی هم پشتیبانی می‌شوند؛ ربات باید عضو باشد تا بتواند resolve
        و چک کند).
        هر خطا = «عضو نیست» (fail-closed): اگر چت قابل‌حل نباشد یا چک
        شکست بخورد، دسترسی داده نمی‌شود — ادمین اصلی همیشه مستثنی است و
        می‌تواند تنظیم را اصلاح کند.
        """
        from telethon.tl.functions.channels import GetParticipantRequest
        try:
            entity = await self._chat_entity(channel)
            await self.client(GetParticipantRequest(channel=entity, participant=user_id))
            return True
        except Exception:
            return False

    async def _resolve_channel(self, channel: str):
        """
        resolve واقعی کانال/گروه با تلگرام — قبل از ذخیره/بررسی.
        ورودی: یوزرنیم، @یوزرنیم، لینک t.me یا آیدیِ عددی (v2.22.0 — گروهِ
        خصوصی؛ ربات باید عضو باشد). خروجی:
        (True, title, normalized, needs_invite) یا (False, error, None, None).
        needs_invite=True یعنی چتِ خصوصیِ بدونِ یوزرنیم است و برای کارتِ
        لینک در پیامِ گیت به لینکِ دعوت نیاز داریم (گامِ بعدِ ویزارد).
        """
        s = str(channel or "").strip()
        if s.lstrip("-").isdigit():
            try:
                entity = await self.client.get_entity(int(s))
            except Exception as e:
                return False, str(e)[:80], None, None
            title = getattr(entity, "title", None) or s
            username = (getattr(entity, "username", None) or "").strip().lower()
            if username:
                # چتی که آیدیِ عددی‌اش را فرستادیم ولی یوزرنیم عمومی دارد
                # → مثل چتِ عمومی ذخیره می‌شود (لینک t.me سالم است)
                return True, title, username, False
            return True, title, str(int(s)), True
        ch = _normalize_channel(s)
        if not ch:
            return False, "یوزرنیم نامعتبر است", None, None
        try:
            entity = await self.client.get_entity(ch)
            title = getattr(entity, "title", None) or ch
            return True, title, ch, False
        except Exception as e:
            return False, str(e)[:80], None, None

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
        self._gate_blocked_ts.clear()
        self._gate_retry_ts.clear()
        self._gate_msg_id.clear()

    async def _channel_gate(self, user_id: int, force: bool = False) -> bool:
        """True = مجاز به استفاده از ربات. فقط ادمین اصلی (ADMIN_ID) مستثنی است.

        v2.22.0 (OWNER-REQUEST): همهٔ کانال‌ها و گروه‌های لیست چک می‌شوند —
        کاربر باید عضوِ **همهٔ** آنها باشد؛ عضویت در یکی کافی نیست. نتیجهٔ
        کل (نه هر چت) کش می‌شود — همان ۶۰ ثانیهٔ قبل.
        """
        if user_id == ADMIN_ID:
            return True
        chats = get_required_chats()
        if not chats:
            return True
        now = time.time()
        if not force:
            cached = self._gate_cache.get(user_id)
            if cached and now - cached[0] < 60:
                return cached[1]
        result = True
        for ch in chats:
            if not await self._is_channel_member(user_id, ch["u"]):
                result = False
                break
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

        BUG-26: _gate_blocked (با مهرِ زمانیِ _gate_blocked_ts) و
        _gate_msg_id هم فقط با تغییر کانال پاک می‌شدند و برای کاربرانی
        که هرگز برنمی‌گردند بی‌سقف رشد می‌کردند. حالا با همان الگو هرس
        می‌شوند: _gate_blocked با TTL ۴۸ ساعته (ورودیِ قدیمی فقط پیامِ
        «خوشامدِ دوباره‌ی عضویت» را عقب می‌اندازد — گیتِ واقعی هر بار
        جداگانه چک می‌شود، پس رفتارِ کاربرانِ زنده تغییر نمی‌کند) و
        _gate_msg_id با سقفِ تعداد (مقدارش فقط برای حذفِ پیامِ گیتِ قبلی
        است — صرفاً آراستگیِ چت).
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
        # BUG-26: _gate_blocked — TTL ۴۸ ساعته با مهرِ زمانی؛ بعد از آن
        # اگر هنوز بالای سقف بود، قدیمی‌ترین‌ها حذف می‌شوند. (tsهایِ مربوط
        # به کاربرانی که قبلاً عضو شده‌اند هم در همین گذر تمیز می‌شوند.)
        if (len(self._gate_blocked) > self._GATE_STATE_MAX
                or len(self._gate_blocked_ts) > self._GATE_STATE_MAX):
            cutoff = now - 48 * 3600
            for uid, ts in list(self._gate_blocked_ts.items()):
                if ts < cutoff:
                    self._gate_blocked_ts.pop(uid, None)
                    self._gate_blocked.discard(uid)
            if len(self._gate_blocked) > self._GATE_STATE_MAX:
                for uid in sorted(self._gate_blocked_ts, key=self._gate_blocked_ts.get)[
                        : len(self._gate_blocked_ts) - self._GATE_STATE_MAX]:
                    self._gate_blocked.discard(uid)
                    self._gate_blocked_ts.pop(uid, None)
        # BUG-26: _gate_msg_id — dict ترتیبِ درج را حفظ می‌کند، پس
        # قدیمی‌ترین‌ها (اولین‌های درج‌شده) حذف می‌شوند تا سقف رعایت شود.
        if len(self._gate_msg_id) > self._GATE_STATE_MAX:
            for uid in list(self._gate_msg_id)[: len(self._gate_msg_id) - self._GATE_STATE_MAX]:
                self._gate_msg_id.pop(uid, None)

    async def _send_channel_gate_message(self, event, denied: bool = False):
        """
        پیام گیت عضویت: متن + کادر(های) شیشه‌ایِ کانال‌ها/گروه‌ها (هر چت
        یک دکمه‌ی لینکِ عریض — v2.22.0 چندچتی) + دکمه‌ی «بررسی عضویت»
        زیر آنها. denied=True یعنی این یک بررسیِ ناموفقِ تازه است و پیام
        «عضو نشدید» نمایش داده می‌شود.
        هر مسیرِ ردشدن، کاربر را به _gate_blocked اضافه می‌کند تا اگر بعداً
        عضو شد، پیام خوشامد «حالا می‌تونی استفاده کنی» بگیرد.
        """
        # آمار: فقط اولین بسته‌شدنِ هر کاربر شمرده می‌شود (نه هر پیامِ گیت)
        if event.sender_id not in self._gate_blocked:
            inc_setting("gate_blocked_count")
        self._gate_blocked.add(event.sender_id)
        # BUG-26: به‌روزرسانی مهرِ زمانی برای هرسِ TTL (ورودی‌های تازه
        # هرگز مشمول حذفِ قدیمی‌ها نمی‌شوند).
        self._gate_blocked_ts[event.sender_id] = time.time()
        chats = get_required_chats()
        # کادرهای شیشه‌ای: هر چت یک دکمه‌ی لینکِ عریض با نامِ واقعی
        # (ذخیره‌شده هنگامِ تنظیم) یا @یوزرنیم. چتِ خصوصیِ بدونِ لینکِ
        # دعوت لینک‌پذیر نیست — نامش در متن می‌آید تا کاربر گم نشود.
        buttons = []
        unlinked = []
        for ch in chats:
            is_id = ch["u"].lstrip("-").isdigit()
            label = ch["t"] or (f"@{ch['u']}" if not is_id else ch["u"])
            # v2.22.1 (AUDIT-39/b#11): سقفِ برچسبِ دکمه در تلگرام ۶۴ نویسه
            # است — عنوانِ بلندِ چت، کلِ پیامِ گیت را بی‌صدا می‌شکست و کاربرِ
            # بسته‌شده بدونِ هیچ پیامی می‌ماند. کوتاه‌سازیِ دفاعی همین‌جا.
            if len(label) > 48:
                label = label[:47] + "…"
            if ch["l"]:
                link = ch["l"]
            elif not is_id:
                link = f"https://t.me/{ch['u']}"
            else:
                link = None
            if link:
                buttons.append([Button.url(f"💠 {label}", link)])
            else:
                unlinked.append(label)
        if denied:
            text = (
                "❌ **شما هنوز عضوِ همه‌ی کانال‌ها/گروه‌ها نشدید!**\n\n"
                "برای استفاده از خدمات ربات، ابتدا در چت‌های زیر عضو شو و "
                "سپس دکمه‌ی «بررسی عضویت» را بزن:"
            )
        else:
            text = (
                "برای استفاده از خدمات ربات، ابتدا در کانال‌ها/گروه‌های زیر "
                "عضو شو 👇\n\nسپس دکمه‌ی «بررسی عضویت» را بزن."
            )
        if unlinked:
            text += "\n\n" + " · ".join(
                f"{UI.GRAY} «{lbl}» (لینک ندارد — از مدیرِ ربات بخواه)"
                for lbl in unlinked)
        buttons.append([UI.go("🔍 بررسی عضویت", b"channel_retry")])
        # چتِ تمیز: قبل از ارسالِ پیامِ جدید (مسیرِ متنی)، پیامِ گیتِ قبلیِ
        # همین کاربر حذف می‌شود — ولی در مسیرِ CallbackQuery (دکمهٔ «بررسی
        # عضویت» که رد شده) هرگز! آن پیام همان پیامی است که دکمهٔ کلیک‌شده
        # را حمل می‌کند؛ حذفش + editِ بعدی یعنی کاربر هیچ بازخوردی نمی‌گیرد
        # (v2.22.1 · AUDIT-39/b#2 + d#1: پیام خورده می‌شد و چت خالی می‌ماند).
        # تشخیص CallbackQuery با `event.query` (قابل‌اطمینان) نه
        # `hasattr(respond)` — چون telethon به CallbackQuery هم respond می‌دهد.
        is_callback = getattr(event, "query", None) is not None
        if not is_callback:
            await self._try_delete_gate_message(event.sender_id, event.chat_id)
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

    async def _show_page(self, event, text: str, buttons):
        """
        رندرِ route-agnostic صفحه (الگوی v2.19.3 در reporter.py): دکمه‌ی
        CallbackQuery → edit همان پیام؛ پیامِ متنی (ویزارد) → respond
        به‌عنوان پیامِ جدیدِ بات با همان دکمه‌ها. بدون این، فراخوانیِ صفحه‌های
        مالک بعد از ذخیرهٔ ویزاردِ متنی با MessageAuthorRequiredError
        می‌شکست (بات نویسندهٔ پیامِ کاربر نیست).
        """
        try:
            from telethon import events as _tl_events
            if isinstance(event, _tl_events.CallbackQuery.Event):
                await event.edit(text, buttons=buttons)
                return
        except Exception:
            pass
        await event.respond(text, buttons=buttons)

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
        # v2.12.23 (QA10-STABILITY BUG#2): timestamp ست کن برای TTL cleanup.
        # قبلاً _ts ست نمی‌شد → _cleanup_stale_wizards هرگز expire نمی‌کرد.
        import time as _t_wiz
        self.wizards[user_id] = {"state": state, "data": data, "_ts": _t_wiz.time()}

    # v2.19.4 (AUDIT-36 H1 — HIGH): سه call-site در callback_h (set_merchant:
    # خطِ ~۹۷۷۸ + order_zarinpal: و order_zibal: بعد از ساختِ موفقِ پرداخت)
    # «self._respond_safe» را صدا می‌زدند در حالی که این متد فقط روی
    # AdminBot تعریف شده بود → AttributeError: 'SaaSBot' object has no
    # attribute '_respond_safe'. اثر: مالک هرگز نمی‌توانست مرچنتِ
    # زرین‌پال/زیبال را از داخلِ ربات تنظیم کند و کاربر بعد از درست‌شدنِ
    # پرداختِ آنلاین، لینک را هرگز نمی‌گرفت (لینک ساخته می‌شد ولی respond
    # می‌ترکید). این متد — هم‌شکلِ AdminBot._respond_safe (admin.py) —
    # نسخه‌ی SaaSBot است: respond با timeout + fallback به alert.
    async def _respond_safe(self, event, text: str, buttons=None,
                            link_preview: bool = False) -> bool:
        try:
            await asyncio.wait_for(
                event.respond(text, buttons=buttons, link_preview=link_preview),
                timeout=30,
            )
            return True
        except asyncio.TimeoutError:
            print("⚠️ [saas respond_safe] timeout after 30s", flush=True)
            try:
                await event.answer("⏳ تلگرام پاسخ نداد. دوباره بزن.", alert=True)
            except Exception:
                pass
            return False
        except Exception as _e:
            print(f"⚠️ [saas respond_safe] {type(_e).__name__}: {_e}", flush=True)
            try:
                await event.answer("❌ خطا در نمایش. دوباره بزن.", alert=True)
            except Exception:
                pass
            return False

    # v2.13.0 (TEST-WIZARD-FLOWS): SaaSBot-side wizard TTL GC. قبلاً فقط
    # AdminBot.wizards پاک می‌شد (AdminBot._cleanup_stale_wizards از
    # AdminBot.handle_message صدا زده می‌شد) ولی SaaSBot.wizards هرگز
    # پاک نمی‌شد → wizardهای رها‌شده (set_card، set_wallet، pricing،
    # dedicated_bot_token، license_create، discount_create، set_merchant،
    # announce) برای همیشه در memory می‌ماندند تا وقتی کاربر /start بزند.
    # این متد الگوی مشابه با AdminBot دارد (خط 9258+) ولی روی
    # self.wizards (SaaSBot) عمل می‌کند.
    async def _cleanup_wizard_temp_client(self, wiz: dict):
        """پاک‌سازیِ central wizard: temp_client disconnect + password clearing."""
        if wiz and isinstance(wiz.get("data"), dict):
            wiz["data"]["old_pass"] = None
            wiz["data"]["new_pass"] = None
            wiz["data"]["password"] = None
        # SaaSBot wizards معمولاً temp_client ندارند، ولی برای defense-in-depth
        # اگر داشت، disconnectش کن.
        temp_client = wiz.get("data", {}).get("temp_client") if wiz else None
        if temp_client:
            try:
                await temp_client.disconnect()
            except Exception:
                pass

    async def _cleanup_stale_wizards(self):
        """پاکسازیِ دوره‌ایِ wizardهای قدیمیِ SaaSBot — الگوی مشابه با
        AdminBot._cleanup_stale_wizards (خط 9258). هر بار که message_h صدا
        زده میشه (با فاصله‌ی حداقل ۵ دقیقه)، wizardهایی که بیشتر از ۳۰
        دقیقه از آخرین activity شون گذشته رو pop می‌کنه و
        _cleanup_wizard_temp_client صدا می‌زنه.

        v2.13.0 (TEST-WIZARD-FLOWS): این متد درست شده تا SaaSBot.wizards
        هم مثل AdminBot.wizards از TTL GC بهره‌مند بشه. قبلاً ثابت‌های
        _WIZARD_TTL_SEC/_last_wizard_gc در __init__ (خط 10666-10667)
        تعریف می‌شدن ولی این متد وجود نداشت → wizardهای رها‌شده برای همیشه
        در memory می‌ماندند.
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
            print(f"🧹 [saas_bot wizard TTL] wizard کاربر {uid} به‌دلیل عدم فعالیت ۳۰ دقیقه پاک شد")

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
        # v2.22.1 (AUDIT-39/d#2): همان محاسبهٔ استانداردِ همهٔ جای دیگر
        # (کارتِ حساب/لیست‌های ادمین) — قبلاً اینجا (expire-now).days خام
        # بود که با گرد‌کردنِ به پایین، روزِ اولِ اشتراکِ ۳روزه «۲ روز»
        # و اشتراکِ ۱روزه «۰ روز» (به‌ظاهر منقضی!) نشان می‌داد.
        days_left = _subscription_days_left(sub) if sub else None
        if sub:
            # زیر ۳ روز مانده → زرد، تا کاربر قبل از قطع‌شدن ببیند.
            sub_state = "warn" if (days_left is not None and days_left <= 3) else "active"
        else:
            sub_state = "none"

        has_account = self._user_has_logged_in_account(uid)
        n_bots, n_active, _ = self._user_selfbot_stats(uid)

        # OWNER/ADMIN اشتراک لازم ندارند؛ نمایشِ «خرید اشتراک» به آن‌ها فقط
        # نویز است. نماینده مثل کاربر عادی اشتراکِ خودش را دارد.
        needs_sub = role not in (ROLE_OWNER, ROLE_ADMIN)

        # ── منوی کاربر (v2.22.0 MENU-REORG · OWNER-REQUEST): فشرده، جفت‌شده
        # و هر بخش در جایِ خودش — ایموجی‌های ثابتِ معنادار ──
        # ردیف ۱ (تکی):    [انقضای سلف: {days} روز]
        # ردیف ۲ (شرطی):   اگه اشتراک فعال/ادمین بود: [لاگین] | [خرید سلف]
        #                  در غیر این صورت: [خرید سلف]
        # ردیف ۳ (تکی):    [ریپورتر] | [فعال‌سازی با لایسنس] — ابزارها
        # ردیف ۴ (شرطی):   [حساب کاربری] | [نمایندگی سلف] برای USER؛
        #                  [حساب کاربری] تنها برای بقیه — بخشِ نمایندگی از
        #                  داخلِ «حساب کاربری» به جایگاهِ خودش در منوی اصلی آمد
        # ردیف ۵ (تکی):    [پشتیبانی]
        # ردیف ۶ (شرطی):   فقط برای admin/owner: [پنل مدیریت / ادمین]
        #
        # v2.17.0: «📖 راهنمای فعال‌سازی»، «ℹ️ سلف چیست؟» و «🔑 خرید با
        # لایسنس» از سطح اول حذف و به «👤 حساب کاربری» منتقل شدند — همه‌ی
        # routeها زنده‌اند و ساختار منوها سالم است؛ فقط سطح اول کوتاه‌تر شد.

        buttons = []

        # ── ردیف ۲ (تکی): انقضای سلف با نمایش روز
        if needs_sub:
            if sub and days_left is not None:
                expiry_text = f"انقضای سلف: {fa_digits(days_left)} روز"
            elif sub:
                expiry_text = "انقضای سلف: نامشخص"
            else:
                expiry_text = "انقضای سلف: ۰ روز"
        else:
            # ادمین/مالک: بدون محدودیت زمانی
            expiry_text = "انقضای سلف: نامحدود"
        buttons.append([UI.item(expiry_text, sub_state, "user_sub_status")])

        # ── ردیف ۲ (شرطی): اشتراک داره/ادمینه → دوتایی؛ عادی → تکی
        has_active_or_admin = bool(sub) or (not needs_sub) or has_account or n_bots > 0
        if has_active_or_admin:
            if needs_sub:
                # لاگین کردن سلف + خرید سلف
                buttons.append([
                    UI.confirm("📱 لاگین کردن سلف", "user_login_account"),
                    UI.confirm("🛒 خرید سلف", "user_renew"),
                ])
            else:
                # v2.22.1 (AUDIT-39/d#8): OWNER/ADMIN اشتراک لازم ندارند —
                # «🛒 خرید سلف» برایشان فقط نویز است (کدِ قدیمی خودش این را
                # می‌گفت ولی باز هم دکمهٔ خرید را نشان می‌داد).
                buttons.append([UI.confirm("📱 لاگین کردن سلف", "user_login_account")])
        else:
            # فقط خرید سلف
            buttons.append([UI.confirm("🛒 خرید سلف", "user_renew")])

        # v2.8.6 BUGFIX: دکمه‌ی «👤 حساب کاربری» اضافه شد — این دکمه
        # مسیرِ دسترسی به کیف پول، سفارش‌ها، دعوت دوستان و راهنماست.
        # v2.19.0 (OWNER-REQUEST): «🔑 فعال‌سازی با لایسنس» به سطح اولِ منو
        # برگشت — فعال‌سازی برای کاربرِ تازه مهم‌ترین عمل است و نباید یک
        # لایه عمیق باشد. v2.22.0 (MENU-REORG): با ریپورتر هم‌ردیف شد.

        # v2.12.16 (USER-REQUEST): دکمه‌ی «🤖 سلف من» کاملاً حذف شد.
        # قبلاً برای همه‌ی نقش‌ها وجود داشت و کاربر عادی بعد از cancel به
        # پنل مدیریتِ ادمین می‌افتاد (باگ UX). v2.12.15 برای USER پنهان
        # شد ولی الان OWNER/ADMIN/RESELLER هم نمی‌خوان. کلاً حذف می‌شه.

        # ── ردیف ۳ (v2.22.0 MENU-REORG): ابزارها — ریپورتر + لایسنس.
        # ریپورتر از v2.19.2 برای **همه‌ی کاربران** نمایش داده می‌شود
        # (خواسته‌ی مالک). الزامِ استفاده هنوز همان است: کاربر باید اکانتِ
        # خودش را در ربات لاگین کرده باشد — گیتِ استفاده در route
        # (user_reporter) و در خودِ ماژول چک می‌شود و کاربرِ لاگین‌نکرده
        # صفحه‌ی راهنما با دکمه‌ی لاگین می‌بیند.
        buttons.append([
            UI.go("🎙 ریپورتر", "user_reporter"),
            UI.go("🔑 فعال‌سازی با لایسنس", "user_activate_license"),
        ])

        # ── ردیف ۴ (v2.22.0 MENU-REORG · OWNER-REQUEST): حساب کاربری —
        # «👥 نمایندگی» از داخلِ کارتِ حساب به جایگاهِ خودش در منوی اصلی
        # آمد (هر بخش در جایِ شخصیِ خودش).
        # v2.22.1 (AUDIT-39/d#3): برای **همهٔ** USERها دیده می‌شود — درخواست‌دهندهٔ
        # در حالِ بررسی هم باید بتواند وضعیتِ درخواستش را ببیند («⏳ در حال
        # بررسی» در _show_reseller_info)؛ قبلاً دکمه برایش پنهان بود و پس از
        # حذفِ دکمهٔ داخلِ کارتِ حساب، صفحهٔ وضعیت برایِ دقیقاً مخاطبِ اصلی‌اش
        # غیرقابل‌دسترس شده بود.
        if role == ROLE_USER:
            buttons.append([
                UI.go("👤 حساب کاربری", "user_account"),
                UI.go("🤝 نمایندگی سلف", "user_reseller_info"),
            ])
        else:
            buttons.append([UI.go("👤 حساب کاربری", "user_account")])

        # ── ردیف ۵ (تکی): پشتیبانی
        buttons.append([UI.go("☎️ پشتیبانی", "user_support")])

        # ── ردیف ۶ (شرطی): فقط برای privileged
        if privileged:
            todo = self._admin_pending_count(uid, role)
            label = "🎛 پنل مدیریت / ادمین"
            if todo:
                label = f"🎛 ادمین · {fa_digits(todo)} کارِ معوق"
            buttons.append([UI.item(label, "pending" if todo else "active", "admin_hub")])

        # v2.22.1 (AUDIT-39/d#6): بلوکِ bodyِ مرده حذف شد — از v2.0 ساخته
        # می‌شد ولی هرگز رندر نمی‌شد (متنِ منو فقط greeting + status_line
        # است). راهنمای «قدم بعدی» (hint) که همان بلوک محاسبه‌اش را داشت
        # حالا واقعاً به متن اضافه می‌شود — کاربرِ تازه دقیقاً یک جملهٔ
        # «حالا چه کنم» می‌بیند.

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

        # گرفتن نام کاربر برای خوش‌آمدگویی شخصی‌سازی‌شده (v1.8.0)
        first_name = ""
        try:
            u = get_user(uid) or {}
            first_name = (u.get("first_name") or "").strip()
        except Exception:
            first_name = ""

        # v2.0: خوش‌آمد کوتاه و حرفه‌ای. اصل "Simplicity": هر عنصر جای خودش.
        # قبلاً یه بلوک ۸-خطی شعاری بود که ۸۰٪ صفحه رو می‌گرفت.
        # حالا: نام + یه جمله‌ی گرم + خلاصه‌ی وضعیت (در صورت نیاز).
        first = first_name or "کاربر"
        status_line = ""
        if n_bots:
            status_line = f" · {UI.dot(n_active > 0)} {fa_digits(n_active)}/{fa_digits(n_bots)} سلف فعال"
        elif sub and days_left is not None:
            status_line = f" · {UI.GREEN} {fa_digits(days_left)} روز مانده"

        if needs_sub and not sub:
            status_line = f" · {UI.AMBER} بدون اشتراک"

        # متن کوتاه — دو خط، نه بلوک (+ یک خطِ راهنمای قدمِ بعدی)
        text = (
            f"**سلام {first}** 👋\n"
            f"به سلف‌ساز CiaNet خوش آمدی.{status_line}"
        )
        if hint:
            text += f"\n\n💡 {hint}"

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

        # v2.8.12: موجودی کیف پول اضافه شد تا کاربر بدون کلیک روی «💰 کیف پول»
        # موجودی رو ببینه.
        balance = get_wallet_balance(uid)
        now = iran_now()
        body = [
            f"👤 شناسه کاربری: `{uid}`",
            f"📅 تاریخ عضویت: {joined}",
            f"{UI.state_dot(sub_state)} اشتراک: {sub_line}",
            f"🤖 سلف: {fa_digits(n_active)} فعال از {fa_digits(n_bots)}",
            f"💰 موجودی کیف پول: **{fa_digits(balance)} Toman**",
            f"🎁 دعوت‌های موفق: {fa_digits(ref['invited'])}",
            UI.SEP,
            f"🗓 {fa_weekday(now)} · {jalali_long(now)}",
            f"⏰ {fa_digits(now.strftime('%H:%M'))}",
        ]

        # «حساب کاربری» حالا هابِ همه‌ی کارهای کم‌کاربرد است — تا منوی اصلی
        # در چهار ردیفِ جفت‌شده جا شود. هر دکمه‌ای که از اینجا حذف می‌شود،
        # قبلاً یک دکمه‌ی سطحِ اول بود و منو را شلوغ می‌کرد.
        # v2.8.7: آیتم‌های تکراری (که در منوی اصلی هم هستن) حذف شدند.
        # _show_account_card فقط چیزهایی رو نشون می‌ده که در منوی
        # اصلی نیستن — یعنی کیف پول، سفارش‌ها، دعوت دوستان.
        # v2.22.0 (OWNER-REQUEST · MENU-REORG): «👥 نمایندگی» از اینجا
        # حذف شد — بخشِ نمایندگی جایِ خودش را در منوی اصلی دارد (ردیفِ
        # «👤 حساب کاربری | 🤝 نمایندگی سلف») و اینجا دیگر تکرار نمی‌شود.
        items = [
            UI.go("💰 کیف پول", "user_wallet"),
            UI.go("🧾 سفارش‌ها", "user_orders"),
            UI.go("❤️ دعوت دوستان", "user_referral"),
        ]
        # v2.17.0 (MENU-CLEANUP): راهنماها از سطح اولِ منو به اینجا
        # منتقل شدند — routeها بدون تغییر، فقط یک لایه عمیق‌تر.
        # v2.19.0 (OWNER-REQUEST): «🔑 فعال‌سازی با لایسنس» به منوی اصلی
        # (ردیفِ ابزارها) برگشت — اینجا دیگر تکرار نمی‌شود.
        items.append(UI.go("📖 راهنمای فعال‌سازی", "user_help"))
        items.append(UI.go("ℹ️ سلف چیست؟", "user_what_is"))
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.respond(
            UI.screen("👤 حساب کاربری", body=body,
                      subtitle="کیف پول، سفارش‌ها، دعوت دوستان و راهنماها — همه اینجاست."),
            buttons=buttons,
        )

    async def _user_show_wallet(self, event):
        """💰 کیف پولِ کاربر — موجودی + آخرین تراکنش‌ها + دکمه‌ی شارژ (در صورت مجاز بودن)."""
        uid = event.sender_id
        balance = get_wallet_balance(uid)
        txs = list_wallet_transactions(uid, limit=10)
        body = [
            f"💳 موجودی فعلی: **{fa_digits(balance)} Toman**",
            "",
            "آخرین تراکنش‌ها:" if txs else "(تراکنشی ثبت نشده)",
        ]
        if txs:
            for tx in txs[:10]:
                amt = int(tx["amount"])
                sign = "+" if amt > 0 else ""
                t_short = (tx["created_at"] or "")[:16].replace("T", " ")
                reason = (tx.get("reason") or tx.get("ref") or "")[:30]
                body.append(f"{sign}{fa_digits(amt)} · {t_short} · {reason}")
        text = UI.screen("💰 کیف پول", body=body,
                        hint="برای شارژ، با پشتیبانی یا OWNER/ADMIN تماس بگیر.")
        buttons = [
            [UI.go("🧾 همه‌ی تراکنش‌ها", "user_wallet_tx")],
            UI.nav_row(),
        ]
        await event.edit(text, buttons=buttons)

    async def _user_show_wallet_tx(self, event):
        """🧾 تاریخچه‌ی کاملِ تراکنش‌های کیف پول کاربر (۲۰ مورد اخیر)."""
        uid = event.sender_id
        txs = list_wallet_transactions(uid, limit=20)
        if not txs:
            await event.edit(
                UI.screen("🧾 تراکنش‌ها", body=["(هیچ تراکنشی ثبت نشده.)"],
                          hint="بازگشت برای بازگشت."),
                buttons=UI.nav_row(),
            )
            return
        body = []
        for tx in txs:
            amt = int(tx["amount"])
            sign = "+" if amt > 0 else ""
            t_short = (tx["created_at"] or "")[:16].replace("T", " ")
            t_type = tx["type"] or ""
            reason = (tx.get("reason") or tx.get("ref") or "")[:40]
            body.append(f"`{tx['id']}` {sign}{fa_digits(amt)} · {t_short}")
            body.append(f"   نوع: {t_type}" + (f" — {reason}" if reason else ""))
            body.append(f"   موجودی بعد از این: {fa_digits(int(tx['balance_after']))} Toman")
            body.append("")
        await event.edit(
            UI.screen("🧾 تراکنش‌ها", body=body,
                      hint="۲۰ تراکنش آخر نمایش داده می‌شود."),
            buttons=UI.nav_row(),
        )

    async def _admin_show_user_wallet(self, event, target_uid: int):
        """💰 کیف پول یک کاربر از دید OWNER/ADMIN/RESELLER — موجودی +
        تراکنش‌ها + شارژ/کسر. RESELLER فقط می‌تونه شارژ کنه (کسر ممنوع)."""
        u = get_user(target_uid)
        if not u:
            await self._nav_heal(event, "این کاربر پیدا نشد.")
            return
        balance = get_wallet_balance(target_uid)
        txs = list_wallet_transactions(target_uid, limit=10)
        name = u.get("username") or f"کاربر {target_uid}"
        body = [
            f"👤 {name}",
            f"🆔 `{target_uid}`",
            f"💳 موجودی: **{fa_digits(balance)} Toman**",
            "",
            "آخرین تراکنش‌ها:" if txs else "(تراکنشی ثبت نشده)",
        ]
        if txs:
            for tx in txs[:10]:
                amt = int(tx["amount"])
                sign = "+" if amt > 0 else ""
                t_short = (tx["created_at"] or "")[:16].replace("T", " ")
                reason = (tx.get("reason") or tx.get("ref") or "")[:30]
                body.append(f"{sign}{fa_digits(amt)} · {t_short} · {reason}")
        # v2.12.12 (QA4-RESELLER): دکمه‌ی «➖ کسر» فقط برای OWNER/ADMIN.
        # قبلاً برای RESELLER هم نمایش داده می‌شد ولی callback رد می‌شد →
        # silent no-op. حالا با viewer_role چک می‌کنیم.
        _viewer_role = self._role(event.sender_id)
        _wallet_buttons = [
            [UI.go("➕ شارژ", f"user_wallet_credit:{target_uid}", tone="success")],
        ]
        if _viewer_role in (ROLE_OWNER, ROLE_ADMIN):
            _wallet_buttons.append(
                [UI.go("➖ کسر", f"user_wallet_debit:{target_uid}", tone="danger")])
        _wallet_buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("💰 کیف پول کاربر", body=body,
                      hint="با دکمه‌های زیر می‌توانی شارژ کنی" +
                           (" یا کسر کنی." if _viewer_role in (ROLE_OWNER, ROLE_ADMIN)
                            else ".")),
            buttons=_wallet_buttons,
        )

    async def _admin_wallet_credit_start(self, event, target_uid: int):
        """شروع ویزارد شارژ کیف پول کاربر."""
        u = get_user(target_uid)
        if not u:
            await self._nav_heal(event, "این کاربر پیدا نشد.")
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_WALLET_CREDIT_AMOUNT,
                                {"target_uid": target_uid})
        name = u.get("username") or f"کاربر {target_uid}"
        # PATCH (TEST-G2-USERMGMT FIX#2a): قبلاً prompt می‌گفت «مثبت برای
        # شارژ، منفی برای کسر» — ولی این مسیرِ «شارژ» است و کاربر دکمه‌ی
        # «➕ شارژ» را زده. برای کسر، دکمه‌ی جداگانه‌ی «➖ کسر» وجود دارد.
        # علاوه‌براین، RESELLER اصلاً اجازه‌ی debit ندارد؛ اگر منفی
        # می‌فرستاد، در مرحله‌ی بعد با «permission_denied» مواجه می‌شد
        # که گمراه‌کننده بود. حالا prompt فقط شارژ را پشتیبانی می‌کند.
        await event.respond(
            f"➕ **شارژ کیف پول**\n\n"
            f"👤 کاربر: {name} (`{target_uid}`)\n"
            f"💳 موجودی فعلی: {fa_digits(get_wallet_balance(target_uid))} Toman\n\n"
            f"مبلغ مثبت به Toman بفرست (شارژ):"
        )

    async def _admin_wallet_debit_start(self, event, target_uid: int):
        """شروع ویزارد کسر دستی از کیف پول کاربر."""
        u = get_user(target_uid)
        if not u:
            await self._nav_heal(event, "این کاربر پیدا نشد.")
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_WALLET_DEBIT_AMOUNT,
                                {"target_uid": target_uid})
        name = u.get("username") or f"کاربر {target_uid}"
        await event.respond(
            f"➖ **کسر از کیف پول**\n\n"
            f"👤 کاربر: {name} (`{target_uid}`)\n"
            f"💳 موجودی فعلی: {fa_digits(get_wallet_balance(target_uid))} Toman\n\n"
            f"مبلغ کسر به Toman رو بفرست (مثبت):"
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
        پنل مدیریت v2.0 — ساختار ۵ بخشی با شماره‌گذاری رومی.

        هر بخش یه شماره‌ی رومی ثابت داره (Ⅰ تا Ⅴ) که به‌عنوان
        signature element عمل می‌کنه و در همه‌ی صفحات تکرار می‌شه.
        کاربر با دیدن «Ⅰ» می‌فهمه توی بخش فروشه.

        ۵ بخش:
          Ⅰ  فروش         (سفارش، قیمت، لایسنس)        — همه
          Ⅱ  کاربران      (لیست، جستجو)                — همه
          Ⅲ  پشتیبانی     (تیکت‌ها)                    — همه
          Ⅳ  سیستم        (کانال، کیف پول، بکاپ)       — همه
          Ⅴ  امنیت        (مجوزها، ابزارهای حساس)       — فقط OWNER

        اصل «Simplicity»: کارهای روزمره یک صفحه (با badge شمارنده).
        کارهای کم‌کاربرد (cap_list، admin_tools) یک لایه پایین‌تر.
        """
        try:
            await event.answer()
        except Exception:
            pass

        if role == ROLE_RESELLER:
            await self._show_reseller_dashboard(event)
            return
        if role not in (ROLE_OWNER, ROLE_ADMIN):
            await event.answer("⛔ دسترسی نداری", alert=True)
            return

        # ── آمارها (یک‌بار محاسبه) ──
        pending_pay = len(list_pending_payments())
        open_tk = len(list_open_tickets())
        st = self._users_stats(list_all_users(), use_cache=True)
        active_users = st["active"]

        def badge(n, sep=" "):
            return f"{sep}({fa_digits(n)})" if n else ""

        # ── ۵ بخش با ساختار یکدست ──
        # Ⅰ فروش و مالی
        sec1 = [
            UI.go(f"💳 سفارشات در انتظار{badge(pending_pay)}", "owner_payments", primary=True),
            UI.go("💰 تأیید پرداخت", "admin_finance"),
            UI.go("🎫 لایسنس و دسترسی", "license_access"),
        ]
        if role == ROLE_OWNER:
            sec1.append(UI.go("🏷 قیمت‌گذاری", "owner_pricing"))
            sec1.append(UI.go("🎟 کدهای تخفیف", "owner_discount_codes"))
            sec1.append(UI.go("💳 درگاه‌های پرداخت", "owner_payment_gateways"))
        # Ⅱ کاربران
        sec2 = [
            # v2.8.9: دکمه‌ی «📋 لیست همه کاربران» — از تابع _owner_show_users
            # استفاده می‌کنه که از قبل وجود داشت ولی هیچ دکمه‌ای بهش وصل نبود.
            # حالا کاربر بدون سرچ مستقیم لیست صفحه‌بندی‌شده با کلیک می‌بینه.
            UI.go("📋 لیست همه کاربران", "owner_users", primary=True),
            UI.go(f"👥 آمار کاربران{badge(active_users)}", "admin_users"),
            UI.go("🔎 جستجوی کاربر", "user_search_start"),
        ]
        # Ⅲ پشتیبانی
        # PATCH (audit-7): دکمه‌های «💬 پاسخ‌های آماده» و «📊 آمار تیکت‌ها»
        # بدون handler بودند (کلیک = no-op + nav-stack pollution). تا زمانی
        # که handler ننویسیم، آن‌ها را از UI حذف می‌کنیم تا کاربر فریب
        # نخورد. پیاده‌سازیِ کاملِ آن‌ها در v2.1 + آمار تیکت‌ها.
        sec3 = [
            UI.go(f"📨 تیکت‌های باز{badge(open_tk)}", "admin_tickets", primary=True),
        ]
        # Ⅳ سیستم
        # PATCH (audit-7): «💼 کیف پول USDT» handler نداشت؛ حذف شد تا وقتی
        # که `owner_set_wallet` به‌عنوان alias پیاده‌سازی شود.
        # PATCH (v2.0.8): دکمه‌ی «🔄 آپدیت و ورژن» فقط برای OWNER اضافه شد.
        sec4 = []
        if role == ROLE_OWNER:
            # v2.22.0: به صفحهٔ فهرستِ کانال‌ها/گروه‌ها می‌رود (نه مستقیمِ
            # ویزاردِ افزودن) — چون لیست چندچتی است و مدیریتش آنجاست.
            sec4.append(UI.go("📢 کانال‌های عضویت", "owner_channel", primary=True))
            sec4.append(UI.go("💾 بکاپ و بازیابی", "admin_backup"))
            sec4.append(UI.go("🔄 آپدیت و ورژن", "owner_update", primary=True, tone="success"))
            sec4.append(UI.go("🌐 پنل وب", "owner_web_panel", tone="success"))
        else:
            # v2.12.9: ADMIN هیچ دکمه‌ای در sec4 نداشت ولی قبلاً «🌐 پنل وب»
            # به‌اشتباه append می‌شد (pass نویسه بود ولی خطِ بعدی همچنان اجرا
            # می‌شد). ADMIN دکمه‌ی «🌐 پنل وب» رو می‌دید ولی callback فقط برای
            # ROLE_OWNER کار می‌کرد → silent no-op. حالا واقعاً چیزی append
            # نمی‌شه.
            pass
        # Ⅴ امنیت (فقط OWNER)
        sec5 = []
        if role == ROLE_OWNER:
            sec5 = [
                UI.go("🔐 مجوزهای حساس", "cap_list", primary=True, tone="danger"),
                UI.go("🧰 ابزارهای بیشتر", "admin_tools"),
            ]

        # ── چیدمان دکمه‌ها: دو ستون، با فاصله‌ی گروه‌ها ──
        buttons = []
        # سربرگ Ⅰ فروش
        buttons.append([UI.section_header(0)])
        for row in UI.admin_section_buttons(0, sec1):
            buttons.append(row)
        # سربرگ Ⅱ کاربران
        buttons.append([UI.section_header(1)])
        for row in UI.admin_section_buttons(0, sec2):
            buttons.append(row)
        # سربرگ Ⅲ پشتیبانی
        buttons.append([UI.section_header(2)])
        for row in UI.admin_section_buttons(0, sec3):
            buttons.append(row)
        # سربرگ Ⅳ سیستم (اگه sec4 دکمه‌ای داشته باشه — v2.12.12: قبلاً
        # برای ADMIN یه header خالی نشون می‌داد چون sec4 خالی بود ولی
        # header همیشه append می‌شد. حالا فقط اگه sec4 پر باشه.)
        if sec4:
            buttons.append([UI.section_header(3)])
            for row in UI.admin_section_buttons(0, sec4):
                buttons.append(row)
        # سربرگ Ⅴ امنیت (اگه OWNER)
        if sec5:
            buttons.append([UI.section_header(4)])
            for row in UI.admin_section_buttons(0, sec5):
                buttons.append(row)
        # نوار ناوبری پایین
        buttons.append(UI.nav_row())

        # ── خلاصه‌ی وضعیت: یک خط، نه بلوک ──
        status_parts = []
        if pending_pay:
            status_parts.append(f"{UI.AMBER} {fa_digits(pending_pay)} پرداخت در انتظار")
        if open_tk:
            status_parts.append(f"{UI.AMBER} {fa_digits(open_tk)} تیکت باز")
        if not status_parts:
            status_parts.append(f"{UI.GREEN} {UI.microcopy()['ok_all']}")
        status_line = " · ".join(status_parts)

        # ── خوش‌آمد کوتاه و حرفه‌ای (نه بلوک شعاری) ──
        first_name = (getattr(event.sender, "first_name", "") or "").strip() or "مدیر"
        text = (
            f"**پنل مدیریت** — {first_name}\n"
            f"_{status_line}_"
        )

        await event.edit(text, buttons=buttons)

    async def _show_users_section(self, event, section: str, role: str):
        """
        نمایش یکی از 3 بخش کاربران (v1.8.0):
        - direct: کاربرانی که از ربات اصلی خرید کرده‌اند (و نماینده ندارند)
        - resellers: نمایندگان و تمام زیرمجموعه‌هایشان
        - admins: ادمین‌ها و اپراتورها
        - active_only: فقط کاربرانی که سلف فعال دارند (طبق درخواست)
        """
        try:
            await event.answer()
        except Exception:
            pass

        # فقط کاربرانی که سلف فعال دارند (طبق درخواست کاربر)
        # PATCH (TEST-G9-ANALYTICS FIX-G): قبلاً فقط `_user_has_active_sub`
        # چک می‌شد → OWNER/ADMIN بدون اشتراکِ فعال از همه‌ی بخش‌ها (حتی بخشِ
        # «👮 ادمین‌ها») حذف می‌شدند و در لیستِ خودشان دیده نمی‌شدند. حالا
        # نقش‌های OWNER/ADMIN همیشه عبور می‌کنند (subscription-agnostic).
        all_users = list_all_users()
        active_only = [u for u in all_users
                       if self._user_has_active_sub(u["user_id"])
                       or self._role(u["user_id"]) in (ROLE_OWNER, ROLE_ADMIN)]

        if section == "direct":
            # کاربرانی که نماینده ندارند (از ربات اصلی گرفتن)
            section_users = [u for u in active_only if not self._get_user_reseller(u["user_id"])]
            title = "👤 اشتراک‌های مستقیم (ربات اصلی)"
            subtitle = f"{fa_digits(len(section_users))} کاربر فعال بدون نماینده"
        elif section == "resellers":
            # نمایندگان + زیرمجموعه‌هایشان
            resellers = [u for u in active_only if self._role(u["user_id"]) == ROLE_RESELLER]
            # همه‌ی کاربران فعال که نماینده دارند (زیرمجموعه)
            reseller_ids = {u["user_id"] for u in resellers}
            sub_users = [u for u in active_only
                         if self._get_user_reseller(u["user_id"]) in reseller_ids]
            section_users = resellers + sub_users
            title = "🤝 نمایندگان و زیرمجموعه‌ها"
            subtitle = f"{fa_digits(len(resellers))} نماینده + {fa_digits(len(sub_users))} مشتری"
        elif section == "admins":
            # ادمین‌ها
            section_users = [u for u in active_only
                             if self._role(u["user_id"]) in (ROLE_OWNER, ROLE_ADMIN)]
            title = "👮 ادمین‌ها و اپراتورها"
            subtitle = f"{fa_digits(len(section_users))} نفر"
        else:
            await event.answer("بخش ناشناس", alert=True)
            return

        if not section_users:
            body = [f"{UI.GRAY} کاربری در این بخش نیست."]
        else:
            body = []
            for u in section_users[:30]:  # نهایتاً 30 تا نمایش بده
                uid = u["user_id"]
                name = (u.get("first_name") or "").strip() or (u.get("username") or "") or str(uid)
                username = f"@{u['username']}" if u.get("username") else ""
                role_label = {"OWNER": "👑", "ADMIN": "👮", "RESELLER": "🤝"}.get(
                    self._role(uid), "👤"
                )
                body.append(f"{role_label} {name} {username} — `{uid}`")
            if len(section_users) > 30:
                body.append(f"{UI.GRAY} ... و {fa_digits(len(section_users) - 30)} نفر دیگر")
                body.append("از «🔎 جستجو» برای پیدا کردنشان استفاده کن")

        # دکمه‌ها: جستجو + بازگشت
        buttons = [[UI.go("🔎 جستجو در این بخش", f"user_search_section:{section}")]]
        buttons.append([UI.go("🔙 بازگشت به کاربران", "admin_tab_users")])
        buttons.append([UI.go("🏠 بازگشت به پنل", "admin_back_to_hub")])

        await event.edit(
            UI.screen(title, body=body, subtitle=subtitle),
            buttons=buttons,
        )

    def _get_user_reseller(self, uid: int) -> int:
        """آیدی نماینده‌ی این کاربر (اگه داشته باشه) — 0 اگه نداره."""
        try:
            u = get_user(uid) or {}
            return int(u.get("reseller_id") or 0)
        except Exception:
            return 0


    # v2.11: خرید ربات اختصاصی
    async def _start_dedicated_bot_purchase(self, event):
        """کاربر ربات اختصاصی می‌خره."""
        uid = event.sender_id
        price = dedicated_bot_price()
        bal = get_wallet_balance(uid)
        body = [
            "🤖 **ربات اختصاصی**\n",
            f"💰 مبلغ: {fa_digits(price)} Toman",
            f"💳 موجودی کیف پول: {fa_digits(bal)} Toman",
            "",
            "با این کار:",
            "• یه ربات اختصاصی با توکن خودت می‌گیری",
            "• مالک ربات می‌شی (بدون قابلیت مدیریت اکانت)",
            "• می‌تونی مشتری جمع کنی و فروش داشته باشی",
        ]
        buttons = []
        if bal >= price:
            buttons.append([UI.go(f"💰 پرداخت با کیف پول ({fa_digits(bal)} Toman)",
                                   "dedicated_pay:wallet", tone="success")])
        buttons.append([UI.go("💳 پرداخت با کارت", "dedicated_pay:card")])
        buttons.append(UI.nav_row())
        await event.respond(
            UI.screen("🤖 ربات اختصاصی", body=body,
                      subtitle="ربات اختصاصی با توکن خودت."),
            buttons=buttons,
        )

    async def _process_dedicated_bot_payment(self, event, method: str):
        """پرداخت ربات اختصاصی."""
        uid = event.sender_id
        price = dedicated_bot_price()
        if method == "wallet":
            bal = get_wallet_balance(uid)
            if bal < price:
                await event.answer("❌ موجودی کافی نیست.", alert=True)
                return
            # v2.11.3: اول order بساز، بعد پول کم کن (با محاسبه‌ی مبلغ واقعی USDT)
            _ded_usdt, _ded_rate = await self._compute_order_amounts(price)
            order = create_order(uid, "ربات اختصاصی", price, _ded_usdt)
            if not isinstance(order, dict) or "id" not in order:
                await event.answer("❌ خطا در ساخت سفارش.", alert=True)
                return
            pay_result = wallet_pay_from_balance(uid, price, ref="dedicated_bot")
            if not pay_result.get("ok"):
                await event.answer(f"❌ خطا در پرداخت: {pay_result.get('error')}", alert=True)
                return
            if isinstance(order, dict) and "id" in order:
                with _conn_immediate() as c:
                    cur = c.execute("UPDATE orders SET status = 'paid', pay_method = 'wallet', paid_at = ? WHERE id = ? AND status = 'pending'",
                              (_now(), order["id"]))
                    if cur.rowcount == 0:
                        pass  # handle refund outside lock
                # v2.11.5: refund outside lock
                if cur.rowcount == 0:
                    wallet_credit(uid, price, OWNER_ID, reason="refund: already paid")
                    await event.answer("❌ این فاکتور قبلاً پرداخت شده — مبلغ برگشت.", alert=True)
                    return
            await self._clear_admin_panel_wizard(uid)
            self._start_own_wizard(uid, "dedicated_bot_token", {"user_id": uid})
            await event.respond(
                "✅ **پرداخت موفق!**\n\n"
                f"💰 موجودی جدید: {fa_digits(pay_result['balance'])} Toman\n\n"
                "🤖 حالا توکن رباتت رو بفرست:\n"
                "از @BotFather یه ربات بساز و توکنش رو اینجا بفرست.",
                buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
            )
        elif method == "card":
            _ded_usdt, _ded_rate = await self._compute_order_amounts(price)
            order = create_order(uid, "ربات اختصاصی", price, _ded_usdt)
            if isinstance(order, dict) and "id" in order:
                await self._show_invoice(event, order, _ded_rate)
            else:
                await event.answer("❌ خطا در ساخت سفارش.", alert=True)

    async def _show_reseller_info(self, event):
        """
        v2.0: صفحه‌ی اطلاعات نمایندگی سلف.
        وقتی USER معمولی روی «🤝 نمایندگی سلف» می‌زنه، این صفحه نشون
        داده می‌شه: توضیح مزایا + دو گزینه (درخواست / انصراف).
        """
        try:
            await event.answer()
        except Exception:
            pass

        uid = event.sender_id
        if self._role(uid) in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
            await event.answer("شما از قبل دسترسی ویژه دارید.", alert=True)
            return

        # آیا قبلاً درخواست ثبت شده؟
        try:
            with _conn() as c:
                row = c.execute(
                    "SELECT status, created_at FROM reseller_applications "
                    "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                    (uid,)
                ).fetchone()
        except Exception:
            row = None

        body = [
            f"{UI.GREEN} چه چیزهایی به‌عنوان نماینده به دست می‌آوری:",
            "",
            "🤖 **ربات اختصاصی**",
            "  ربات تلگرام با نام و لینک اختصاصی خودت — مشتریانت مستقیم",
            "  به تو وصل می‌شن، نه به ربات اصلی.",
            "",
            "💸 **سیستم درآمد خودکار**",
            "  هر مشتری که از طریق لینک یا رباتت بیاد، سهم فروش تو فعال",
            "  می‌شه. درآمدت به‌صورت خودکار محاسبه و پرداخت می‌شه.",
            "",
            "👥 **پنل مشتریان**",
            "  لیست مشتری‌ها + وضعیت اشتراک هرکدوم + ابزار صدور لایسنس.",
            "",
            "📊 **گزارش درآمد**",
            "  هر ماه گزارش کامل فروش و درآمدت رو می‌بینی.",
        ]
        if row:
            status = row["status"]
            created = row["created_at"]
            if status == "pending":
                body.append("")
                body.append(f"{UI.AMBER} ⏳ درخواست شما در تاریخ {created} در حال بررسی است.")
            elif status == "approved":
                body.append("")
                body.append(f"{UI.GREEN} ✅ شما نماینده‌ی فعال هستید!")
            elif status == "rejected":
                body.append("")
                body.append(f"{UI.RED} ❌ درخواست قبلی شما رد شده. می‌توانید دوباره درخواست دهید.")

        text = UI.screen("🤝 نمایندگی سلف CiaNet", body=body,
                         subtitle="کسب درآمد با فروش اشتراک سلف به مشتریان خودت")

        # دکمه‌ها: درخواست (اصلی) + انصراف
        buttons = []
        if not row or row["status"] in ("rejected",):
            buttons.append([UI.go("🤖 ربات اختصاصی", "dedicated_bot_buy", tone="success")])
            buttons.append([UI.go("🤝 درخواست نمایندگی", "user_reseller_apply", tone="success")])
        buttons.append(UI.nav_row())

        # v2.12.2: use respond instead of edit to avoid "mix inline with normal buttons"
        await event.respond(text, buttons=buttons)

    async def _apply_reseller(self, event):
        """
        v2.0: ثبت درخواست نمایندگی. فقط USER معمولی.
        پس از ثبت، وضعیت به «pending» می‌ره و OWNER می‌تونه در پنلش
        ببینه و تأیید/رد کنه.
        """
        try:
            await event.answer()
        except Exception:
            pass

        uid = event.sender_id
        if self._role(uid) in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
            await event.answer("شما از قبل دسترسی ویژه دارید.", alert=True)
            return

        # جدول reseller_applications در init_db ساخته می‌شه.

        # ثبت درخواست
        try:
            with _conn() as c:
                # اگه قبلاً pending یا approved داره، ثبت نکن
                existing = c.execute(
                    "SELECT id FROM reseller_applications "
                    "WHERE user_id = ? AND status IN ('pending', 'approved')",
                    (uid,)
                ).fetchone()
                if existing:
                    await event.answer("شما قبلاً درخواست داده‌اید.", alert=True)
                    return
                c.execute(
                    "INSERT INTO reseller_applications (user_id, status, created_at) "
                    "VALUES (?, 'pending', ?)",
                    (uid, _now())
                )
            log_action(uid, "reseller_apply", "درخواست نمایندگی ثبت شد")

            # اطلاع به همه‌ی OWNER ها
            try:
                with _conn() as c:
                    owner_rows = c.execute(
                        "SELECT user_id FROM admins WHERE role = 'OWNER'"
                    ).fetchall()
                u = get_user(uid) or {}
                name = (u.get("first_name") or "کاربر").strip()
                username = f"@{u['username']}" if u.get("username") else ""
                for o in owner_rows:
                    try:
                        await self.client.send_message(
                            o["user_id"],
                            f"📥 **درخواست نمایندگی جدید**\n\n"
                            f"👤 {name} {username} — `{uid}`\n"
                            f"🕐 {_now()}\n\n"
                            f"برای بررسی: پنل ادمین → کاربران → جستجو"
                        )
                    except Exception:
                        pass
            except Exception as e:
                print(f"⚠️ [reseller] اطلاع به OWNER: {e}")

        except Exception as e:
            print(f"⚠️ [reseller] ثبت درخواست ناموفق: {e}")
            await event.answer("خطا در ثبت درخواست. دوباره امتحان کن.", alert=True)
            return

        # تأیید به کاربر
        body = [
            f"{UI.GREEN} درخواست نمایندگی شما با موفقیت ثبت شد.",
            "",
            f"{UI.GRAY} پس از بررسی توسط تیم، نتیجه به شما اطلاع داده می‌شود.",
            f"{UI.GRAY} معمولاً کمتر از ۲۴ ساعت طول می‌کشد.",
        ]
        await event.respond(
            UI.screen("✋ درخواست ثبت شد", body=body,
                     subtitle="منتظر تأیید تیم CiaNet باشید"),
            buttons=[[UI.go("🏠 منوی اصلی", NAV_HOME)]],
        )

    async def _show_admin_tab(self, event, tab: str, role: str):
        """رندر هر یک از 4 تب ادمین (v1.8.0)."""
        try:
            await event.answer()
        except Exception:
            pass
        if role not in (ROLE_OWNER, ROLE_ADMIN):
            await event.answer("⛔ دسترسی نداری", alert=True)
            return

        if tab == "sales":
            pending_pay = len(list_pending_payments())
            items = [
                UI.go("💳 سفارشات در انتظار" + (f" ({fa_digits(pending_pay)})" if pending_pay else ""),
                      "owner_payments", primary=True),
                UI.go("💰 تأیید پرداخت‌ها", "admin_finance"),
                UI.go("🏷 قیمت‌گذاری و پلن‌ها", "owner_pricing"),
                UI.go("🎫 لایسنس و دسترسی", "license_access"),
            ]
            title, subtitle = "🛒 فروش", "سفارشات، پرداخت‌ها و لایسنس"
        elif tab == "users":
            # 3 بخش جداگانه مطابق درخواست کاربر
            items = [
                UI.go("👤 اشتراک‌های مستقیم (ربات اصلی)", "users_section_direct", primary=True),
                UI.go("🤝 نمایندگان و زیرمجموعه", "users_section_resellers"),
                UI.go("👮 ادمین‌ها و اپراتورها", "users_section_admins"),
                UI.go("🔎 جستجوی کاربر", "user_search_start"),
            ]
            title, subtitle = "👥 کاربران", "3 بخش جدا برای دسترسی سریع‌تر"
        elif tab == "support":
            # PATCH (audit-7): «📊 آمار تیکت‌ها» و «💬 پاسخ‌های آماده»
            # بدون handler بودند → حذف شدند. پیاده‌سازی در v2.1.
            items = [
                UI.go("📨 تیکت‌های باز", "admin_tickets", primary=True),
            ]
            title, subtitle = "📨 پشتیبانی", "تیکت‌های دریافتی"
        elif tab == "settings":
            # PATCH (audit-7): «💼 کیف پول USDT» بدون handler بود → حذف شد.
            items = [
                UI.go("📢 تنظیم کانال عضویت", "owner_channel_set", primary=True),
            ]
            if role == ROLE_OWNER:
                items.extend([
                    UI.go("🔐 مجوزهای حساس", "cap_list"),
                    UI.go("💾 بکاپ و بازیابی", "admin_backup"),
                    UI.go("🧰 ابزارهای بیشتر", "admin_tools"),
                ])
            title, subtitle = "⚙️ تنظیمات", "پیکربندی سیستم"
        else:
            await event.answer("تب ناشناس", alert=True)
            return

        buttons = self._pair_buttons(items)
        buttons.append([UI.go("🔙 بازگشت به پنل", "admin_back_to_hub")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen(title, subtitle=subtitle),
            buttons=buttons,
        )

    async def _show_reseller_dashboard(self, event):
        """داشبورد نماینده (v1.8.0) — فقط مشتریان و لایسنس‌های خودش."""
        try:
            await event.answer()
        except Exception:
            pass
        uid = event.sender_id
        my_users = list_users_for_reseller(uid)
        n_active = sum(1 for u in my_users if self._user_has_active_sub(u["user_id"]))
        items = [
            UI.go("👥 مشتریان من" + f" ({fa_digits(len(my_users))})", "reseller_users", primary=True),
            UI.go("🎫 لایسنس و دسترسی", "license_access"),
            UI.go("🤖 ربات اختصاصی", "reseller_dedicated_bot"),
            UI.go("⏳ وضعیت اشتراک‌ها", "reseller_subs"),
        ]
        body = [
            f"{UI.GREEN} {n_active} مشتری با اشتراک فعال",
            f"{UI.RED} {len(my_users) - n_active} بدون اشتراک فعال",
        ]
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("👥 پنل نمایندگی", body=body,
                      subtitle="مشتری‌ها و لایسنس‌های خودت"),
            buttons=buttons,
        )

    async def _show_admin_tools(self, event, role: str):
        """🧰 ابزارهای کم‌کاربردِ مدیریتی — یک لایه پایین‌ترِ هابِ ادمین.

        v2.8.8: تکرارها حذف شدند. قبلاً «🔐 مجوزهای حساس» و «💾 بکاپ و بازیابی»
        هم در هاب اصلی و هم اینجا نمایش داده می‌شدند. حالا فقط چیزهایی
        که در هاب اصلی نیستن (ربات اختصاصی + تنظیمات) اینجا هستن.
        """
        if role not in (ROLE_OWNER, ROLE_ADMIN):
            await event.answer("⛔ دسترسی نداری", alert=True)
            return
        items = [UI.go("🤖 ربات‌های اختصاصی", "owner_dedicated_list")]
        if role == ROLE_OWNER:
            items.extend([
                UI.go("⚙️ تنظیمات", "admin_settings"),
                # TEST-G6-SYSTEM: دکمه‌ی «ارسال پیام همگانی» — قبلاً callback
                # owner_announce/announce_send: وجود نداشتند (silent no-op).
                # حالا که handler پیاده‌سازی شده، دکمه‌اش هم در دسترس OWNER
                # قرار می‌گیرد.
                UI.go("📨 ارسال پیام همگانی", "owner_announce", tone="success"),
            ])
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("🧰 ابزارهای بیشتر",
                      subtitle="کارهایی که هر روز لازم نمی‌شوند."),
            buttons=buttons,
        )


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
        """v1.9.0: صفحه‌ی «کاربران» با 3 بخش جداگانه مطابق درخواست کاربر.

        کاربر گفت: «اگر نمایندگی بدم، آن نماینده باید به بخش نمایندگان و
        اکانت‌های نماینده برود؛ اگر ادمین باشد، همین‌طور. اگر از طریق ربات
        اصلی اشتراک خریده باشند، آن‌ها نیز در بخش‌های جداگانه باشند.»

        فقط کاربرانی که سلف فعال دارند (طبق درخواست: «سلف نخریده را نمایش نده»).
        """
        try:
            await event.answer()
        except Exception:
            pass

        all_users = list_all_users()
        # فقط کاربران فعال
        # PATCH (TEST-G9-ANALYTICS FIX-G): قبلاً فقط `self._user_has_active_sub`
        # چک می‌شد → OWNER/ADMIN بدون اشتراکِ فعال از همه‌ی بخش‌ها (حتی بخشِ
        # «👮 ادمین‌ها») حذف می‌شدند و در لیستِ خودشان دیده نمی‌شدند. حالا
        # نقش‌های OWNER/ADMIN همیشه عبور می‌کنند (subscription-agnostic).
        active_users = [u for u in all_users
                        if self._user_has_active_sub(u["user_id"])
                        or self._role(u["user_id"]) in (ROLE_OWNER, ROLE_ADMIN)]

        # شمارش هر بخش
        direct = [u for u in active_users if not self._get_user_reseller(u["user_id"])]
        resellers = [u for u in active_users
                     if self._role(u["user_id"]) == ROLE_RESELLER]
        reseller_ids = {u["user_id"] for u in resellers}
        sub_of_resellers = [u for u in active_users
                            if self._get_user_reseller(u["user_id"]) in reseller_ids]
        admins = [u for u in active_users
                  if self._role(u["user_id"]) in (ROLE_OWNER, ROLE_ADMIN)]

        body = [
            f"{UI.GREEN} {fa_digits(len(direct))} اشتراک مستقیم (ربات اصلی)",
            f"{UI.AMBER} {fa_digits(len(resellers))} نماینده + {fa_digits(len(sub_of_resellers))} مشتری",
            f"{UI.BLUE} {fa_digits(len(admins))} ادمین",
        ]

        # 3 دکمه‌ی اصلی + جستجو
        items = [
            UI.go(f"👤 اشتراک‌های مستقیم ({fa_digits(len(direct))})",
                  "users_section_direct", primary=True),
            UI.go(f"🤝 نمایندگان و زیرمجموعه ({fa_digits(len(resellers)+len(sub_of_resellers))})",
                  "users_section_resellers"),
            UI.go(f"👮 ادمین‌ها ({fa_digits(len(admins))})",
                  "users_section_admins"),
            UI.go("🔎 جستجوی کاربر", "user_search_start"),
        ]
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("👥 کاربران", body=body,
                      subtitle="3 بخش جدا برای دسترسی سریع"),
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
        wallet = get_setting("usdt_wallet")
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
        chats = get_required_chats()
        # PATCH (v2.4.0): language toggle button
        lang_label = "🌐 زبان: فارسی" if CIANET_LANG == "fa" else "🌐 Language: English"
        # v2.17.0: گزینه‌های مالک — آزمایشی + اشتراک دسته‌جمعی.
        # v2.22.0 (OWNER-REQUEST): کانال‌های اجباری چندتایی شدند (کانال +
        # گروه) و آزمایشی صفحهٔ مخصوصِ خودش را گرفت (روشن/خاموش + تعدادِ
        # روزهایِ قابلِ تنظیم).
        trial_on = trial_enabled()
        days = trial_days()
        group_on = group_sub_enabled()
        group_discount = group_sub_discount_percent()
        buttons = [
            [UI.item(f"📢 کانال‌های اجباری عضویت ({fa_digits(len(chats))})",
                     "active" if chats else "none", "owner_channel")],
            [UI.item(f"🎁 اشتراک آزمایشی ({fa_digits(days)} روزه)",
                     "active" if trial_on else "off", "owner_trial")],
            [UI.item("👥 اشتراک دسته‌جمعی", "active" if group_on else "off",
                     "owner_toggle_group_sub")],
            [UI.go(lang_label, "owner_toggle_lang")],
            UI.nav_row(),
        ]
        if chats:
            ch_lines = " · ".join(
                (c["t"] or f"@{c['u']}") if not c["u"].lstrip("-").isdigit()
                else (c["t"] or c["u"])
                for c in chats)
        else:
            ch_lines = "غیرفعال (همه می‌توانند وارد شوند)"
        await event.edit(
            UI.screen(
                "⚙️ تنظیمات سیستم",
                body=[f"{UI.dot(bool(chats))} عضویت اجباری ({fa_digits(len(chats))} چت): " + ch_lines,
                      f"🌐 زبان فعلی: {'فارسی' if CIANET_LANG == 'fa' else 'English'}",
                      f"{UI.dot(trial_on)} اشتراک آزمایشیِ کاربران جدید: "
                      + (f"روشن — {fa_digits(days)} روزه" if trial_on else "خاموش"),
                      f"{UI.dot(group_on)} اشتراک دسته‌جمعی: "
                      + ("روشن" if group_on else "خاموش")
                      + f" (تخفیف گروهی: {fa_digits(group_discount)}٪)"],
                subtitle="تنظیمات غیرمالی — کارت/تتر/قیمت‌ها در «💰 مالی» هستند.",
            ),
            buttons=buttons,
        )

    async def _owner_show_trial_settings(self, event):
        """
        🎁 صفحهٔ تنظیماتِ اشتراکِ آزمایشی (v2.22.0 · OWNER-REQUEST):
        روشن/خاموش + تعدادِ روزهایِ دوره (۱ تا ۳۰) — قبلاً فقط کلیدِ
        روشن/خاموش با ۷ روزِ ثابت وجود داشت.
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط مالک.", alert=True)
            return
        on = trial_enabled()
        days = trial_days()
        body = [
            f"{UI.dot(on)} اعطایِ خودکار به کاربرانِ جدید: "
            + ("روشن" if on else "خاموش"),
            f"📅 طولِ دوره: {fa_digits(days)} روز",
            "",
            "کاربرِ تازه که /start بزند، یک‌بار در طول عمرش این اشتراک را"
            " می‌گیرد (تغییرِ تعدادِ روزها باعثِ اعطایِ دوباره به همان"
            " کاربر نمی‌شود).",
        ]
        buttons = [
            [UI.toggle("اعطایِ خودکار", on, "owner_toggle_trial")],
            [UI.go(f"📅 تعدادِ روزها: {fa_digits(days)}", "owner_trial_days")],
            UI.nav_row(),
        ]
        await self._show_page(
            event,
            UI.screen("🎁 اشتراک آزمایشی", body=body,
                      subtitle="دورهٔ رایگانِ کاربرانِ جدید — تعدادِ روزها"
                               " از ۱ تا ۳۰ قابلِ تنظیم است.",
                      hint="از «📅 تعدادِ روزها» طولِ دوره را عوض کن."),
            buttons,
        )

    async def _start_trial_days_wizard(self, event):
        """ویزاردِ تعدادِ روزهایِ دورهٔ آزمایشی (OWNER)."""
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_TRIAL_DAYS, {})
        await event.edit(
            f"طولِ دورهٔ آزمایشی چند روز باشد؟ (۱ تا {fa_digits(TRIAL_DAYS_MAX)})\n\n"
            "یک عدد بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    async def _admin_show_backup_hub(self, event):
        # PATCH (v2.3.0): نمایش وضعیت scheduled backup
        backup_hours_str = ", ".join(str(h) for h in BACKUP_HOURS_IRAN)
        # v2.22.0 (OWNER-REQUEST): بکاپِ ساعتیِ سشن‌های سلف به گروهِ شخصی
        grp = self_backup_group()
        sb_on = self_backup_enabled() and bool(grp)
        sb_state = "active" if sb_on else ("off" if grp else "none")
        sb_line = (f"🗂 **بکاپِ ساعتیِ سلف‌ها**: هر ساعت در سرِ ساعت به «"
                   + (f"گروه `{grp}`" if grp else "گروهِ تنظیم‌نشده")
                   + "» — " + ("روشن" if sb_on else "خاموش"))
        body = [
            f"{UI.GREEN} **Backup** — یک فایل ZIP کامل از دیتابیس‌ها، "
            f"تنظیمات و سشن‌ها می‌سازد. کاملاً بی‌خطر.",
            f"{UI.RED} **Restore** — وضعیت فعلی را با محتوای فایل "
            f"جایگزین می‌کند. قبلش یک Backup اضطراری خودکار گرفته می‌شود.",
            "",
            f"⏰ **بکاپ خودکار**: روزانه در ساعت‌های {backup_hours_str} (وقت ایران)",
            sb_line,
            f"{UI.GRAY} برای تغییرِ برنامهٔ روزانه، در فایل env: CIANET_BACKUP_HOURS=\"0,12\"",
        ]
        buttons = [
            [UI.confirm("گرفتن Backup", "owner_backup")],
            [UI.danger("بازیابی از Backup", "owner_db_restore")],
            [UI.item("🗂 بکاپِ ساعتیِ سلف‌ها به گروه", sb_state,
                     "owner_self_backup")],
            UI.nav_row(),
        ]
        await event.edit(
            UI.screen(
                "💾 Backup و Restore",
                body=body,
                subtitle="پشتیبان‌گیری و بازیابیِ کلِ سیستم.",
                hint="بکاپِ ساعتیِ سلف‌ها از «🗂» جداگانه تنظیم می‌شود.",
            ),
            buttons=buttons,
        )

    async def _owner_show_self_backup(self, event):
        """
        🗂 تنظیماتِ بکاپِ ساعتیِ سشن‌های سلف (v2.22.0 · OWNER-REQUEST):
        گروهِ شخصیِ مقصد + کلیدِ روشن/خاموش. هر ساعت در سرِ ساعت، یک
        ZIPِ سبکِ فقط-سشن (رمزگذاری‌شده با همان CIANET_BACKUP_PASS)
        در گروه ارسال می‌شود.
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط مالک.", alert=True)
            return
        grp = self_backup_group()
        enabled = self_backup_enabled()
        on = enabled and bool(grp)
        body = [
            "بکاپِ سبکِ **فقط سشن‌های سلف**، هر ساعت در سرِ ساعت، به یک"
            " گروهِ شخصیِ تلگرامی — اگر سرور بیاید پایین یا فایل‌ها"
            " از بین بروند، لاگینِ هیچ کاربری از دست نمی‌رود.",
            "",
            (f"{UI.GREEN} گروه مقصد: `{grp}`" if grp
             else f"{UI.GRAY} گروه مقصد: تنظیم نشده"),
            f"{UI.dot(on)} وضعیت: " + ("روشن" if on else "خاموش"),
            "",
            f"{UI.GRAY} رمزِ فایل همان CIANET_BACKUP_PASS است و فایل"
            " فقط-سشن است (دیتابیس‌ها در بکاپِ روزانهٔ کامل می‌مانند).",
        ]
        buttons = []
        if grp:
            buttons.append([UI.toggle("ارسالِ ساعتی", on,
                                      "owner_self_backup_toggle")])
        buttons.append([UI.go("✏️ تنظیم گروه", "owner_self_backup_set")])
        if grp:
            buttons.append([UI.danger("⛔ حذف گروه", "owner_self_backup_clear")])
        buttons.append(UI.nav_row())
        await self._show_page(
            event,
            UI.screen("🗂 بکاپِ ساعتیِ سلف‌ها", body=body,
                      subtitle="گروهِ شخصی + هر ساعت یک بکاپِ سبک از سشن‌ها.",
                      hint="ربات باید عضوِ گروه باشد؛ آیدی عددی یا فوروارد"
                           " از خودِ گروه کافی است."),
            buttons,
        )

    async def _owner_start_self_backup_set(self, event):
        """ویزاردِ تنظیمِ گروهِ بکاپِ ساعتی (OWNER) — آیدی عددی یا فوروارد."""
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_SELF_BACKUP_GROUP, {})
        await event.edit(
            "آیدیِ عددیِ گروهِ مقصد را بفرست (مثل `-1001234567890`) **یا"
            " یک پیام از همان گروه را فوروارد کن** — آیدی از رویِ فوروارد"
            " خودکار خوانده می‌شود.\n\n"
            "⚠️ ربات باید عضوِ آن گروه باشد.",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )

    # ─────────────────────────────────────────────────────
    #  بخش OWNER/ADMIN
    # ─────────────────────────────────────────────────────

    # BUG-30: اندازه‌ی قطعه‌ی کوئری‌های IN — پایین‌تر از سقفِ پارامترهای
    # sqlite (999) تا روی همه‌ی نسخه‌ها کار کند.
    _SUB_QUERY_CHUNK = 500

    def _users_sub_status_map(self, users: list) -> dict:
        """BUG-30: وضعیت اشتراکِ همه‌ی کاربرانِ لیست با «دو» کوئریِ مجموعه‌ای
        (IN) به‌جای N+1 کوئری — دقیقاً هم‌ارزِ فراخوانیِ _user_sub_status
        به‌ازای هر کاربر (همان کوئری‌ها با همان ORDER BY و همان منطقِ
        انشعاب)، فقط یک‌جا و دسته‌ای. خروجی: {user_id: وضعیت}."""
        uids = []
        seen = set()
        for u in users:
            uid = u["user_id"]
            if uid not in seen:
                seen.add(uid)
                uids.append(uid)
        # ۱) آخرین اشتراکِ active هر کاربر — معادلِ get_active_subscription
        #    (ORDER BY expire_date DESC LIMIT 1 به‌ازای هر کاربر؛ اولینِ
        #    دیده‌شده در مرتب‌سازیِ کلی همان MAXِ هر کاربر است).
        active_sub = {}
        if uids:
            with _conn() as c:
                for i in range(0, len(uids), self._SUB_QUERY_CHUNK):
                    chunk = uids[i:i + self._SUB_QUERY_CHUNK]
                    q = ("SELECT * FROM subscriptions WHERE status = 'active' "
                         f"AND user_id IN ({','.join('?' * len(chunk))}) "
                         "ORDER BY expire_date DESC")
                    for row in c.execute(q, chunk):
                        d = dict(row)
                        if d["user_id"] not in active_sub:
                            active_sub[d["user_id"]] = d
        # ۲) fallback — فقط برای کاربرانی که اشتراکِ active ندارند یا
        #    روزِ باقی‌مانده‌شان قابل‌محاسبه نیست (معادلِ کوئریِ دومِ
        #    _user_sub_status: ORDER BY created_at DESC, id DESC LIMIT 1).
        need_fallback = []
        for uid in uids:
            sub = active_sub.get(uid)
            if not (sub and _subscription_days_left(sub) is not None):
                need_fallback.append(uid)
        latest_sub = {}
        if need_fallback:
            with _conn() as c:
                for i in range(0, len(need_fallback), self._SUB_QUERY_CHUNK):
                    chunk = need_fallback[i:i + self._SUB_QUERY_CHUNK]
                    q = ("SELECT * FROM subscriptions "
                         f"WHERE user_id IN ({','.join('?' * len(chunk))}) "
                         "ORDER BY created_at DESC, id DESC")
                    for row in c.execute(q, chunk):
                        d = dict(row)
                        if d["user_id"] not in latest_sub:
                            latest_sub[d["user_id"]] = d
        # ۳) همان منطقِ انشعابِ _user_sub_status — بیت‌به‌بیت.
        out = {}
        for uid in uids:
            sub = active_sub.get(uid)
            d = _subscription_days_left(sub)
            if sub and d is not None and d >= 0:
                out[uid] = {"active": True, "expired": False, "nosub": False,
                            "plan": sub["plan"], "days": d, "expire": sub["expire_date"]}
                continue
            if sub and d is not None and d < 0:
                out[uid] = {"active": False, "expired": True, "nosub": False,
                            "plan": sub["plan"], "days": d, "expire": sub["expire_date"]}
                continue
            row = latest_sub.get(uid)
            if row:
                d2 = _subscription_days_left(row)
                out[uid] = {"active": False, "expired": True, "nosub": False,
                            "plan": row["plan"], "days": d2, "expire": row["expire_date"]}
            else:
                out[uid] = {"active": False, "expired": False, "nosub": True,
                            "plan": None, "days": None, "expire": None}
        return out

    def _users_selfbot_stats_map(self, users: list) -> dict:
        """BUG-30: (کلِ اکانت‌ها، اکانت‌های دستی) برای همه‌ی کاربرانِ لیست
        با «یک» بارِ load_config — قبلاً _filter_users به‌ازای هر کاربر
        _user_selfbot_stats یا _user_manual_bot_count صدا می‌زد که هرکدام
        config.json را کامل از دیسک می‌خواند و پارس می‌کرد (N+1). همان
        منطقِ آن دو تابع (account_belongs_to و provision_source) عیناً
        استفاده می‌شود، پس نتیجه هم‌ارزِ دقیقِ قبلی است."""
        cfg = self.sb.load_config()
        out = {}
        for u in users:
            uid = u["user_id"]
            total = manual = 0
            for tag, acc in cfg.items():
                if not account_belongs_to(acc, tag, uid):
                    continue
                total += 1
                if acc.get("provision_source") == PROVISION_MANUAL:
                    manual += 1
            out[uid] = (total, manual)
        return out

    def _filter_users(self, users: list, fkey: str) -> list:
        """فیلتر لیست کاربران برای صفحه‌ی «کاربران». «بدون اشتراک» و «منقضی»
        دو فیلتر جدا هستند و «اضافه‌شده‌ی دستی» هم فیلتر مستقل خودش را
        دارد:
          all/active/expired/nosub/manual/hasbot/nobot
        """
        # BUG-30: فیلترهای active/expired/nosub قبلاً به‌ازای هر کاربر
        # کوئریِ DB و فیلترهای manual/hasbot/nobot به‌ازای هر کاربر
        # خواندنِ کاملِ config.json داشتند (N+1)؛ حالا هر گروه با یک
        # محاسبه‌ی دسته‌ای انجام می‌شود و خروجیِ فیلتر (انتخاب و ترتیب)
        # بیت‌به‌بیت با قبل یکسان است.
        if fkey in ("active", "expired", "nosub"):
            st = self._users_sub_status_map(users)
            return [u for u in users if st[u["user_id"]][fkey]]
        if fkey in ("manual", "hasbot", "nobot"):
            stats = self._users_selfbot_stats_map(users)
            if fkey == "manual":
                return [u for u in users if stats[u["user_id"]][1] > 0]
            if fkey == "hasbot":
                return [u for u in users if stats[u["user_id"]][0] > 0]
            return [u for u in users if stats[u["user_id"]][0] == 0]
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

    async def _start_section_search(self, event, section: str):
        """v1.8.0: جستجوی کاربر در یک بخش خاص (direct/resellers/admins)."""
        try:
            await event.answer()
        except Exception:
            pass
        await self._clear_admin_panel_wizard(event.sender_id)
        # ویزارد رو با section فعال کن
        back_data = f"users_section_{section}".encode()
        self._start_own_wizard(
            event.sender_id, WIZ_USER_SEARCH,
            {"back_data": back_data, "section": section},
        )
        section_name = {
            "direct": "اشتراک‌های مستقیم",
            "resellers": "نمایندگان و زیرمجموعه‌ها",
            "admins": "ادمین‌ها و اپراتورها",
        }.get(section, "این بخش")
        await event.edit(
            f"🔍 جستجو در بخش «{section_name}»\n\n"
            "آیدی عددی یا بخشی از یوزرنیم کاربر رو بفرست:",
            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
        )


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
            f"💰 کیف پول: {fa_digits(get_wallet_balance(target_user_id))} Toman",
        ]
        if u.get("reseller_id"):
            body.append(f"👥 زیرمجموعه‌ی نماینده: `{u['reseller_id']}`")
        # v2.17.0: وضعیت بلاک — اگر بلاک شده باشد مشخص و پررنگ باشد
        if u.get("is_blocked"):
            reason_txt = f" — {u['block_reason']}" if u.get("block_reason") else ""
            body.append(f"⛔ وضعیت: **بلاک شده**{reason_txt}")
        # v2.17.0: وضعیت بلاک — اگر بلاک شده باشد مشخص و پررنگ باشد
        if u.get("is_blocked"):
            reason_txt = f" — {u['block_reason']}" if u.get("block_reason") else ""
            body.append(f"⛔ وضعیت: **بلاک شده**{reason_txt}")
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
        buttons.append([UI.go("💰 کیف پول", f"user_wallet_admin:{target_user_id}", tone="success")])
        buttons.append([UI.go("🧾 سفارش‌ها", f"user_orders_admin:{target_user_id}")])
        # v2.17.0: بلاک/رفع بلاک — فقط OWNER/ADMIN (نه RESELLER)؛ OWNER
        # هرگز بلاک نمی‌شود و بلاکِ ADMIN فقط توسط OWNER. گاردها در
        # Backend (block_saas_user) هم دوباره چک می‌شوند.
        vrole = viewer_role or ROLE_USER
        if vrole in (ROLE_OWNER, ROLE_ADMIN):
            target_role = self._role(target_user_id)
            if target_role != ROLE_OWNER and (
                    target_role != ROLE_ADMIN or vrole == ROLE_OWNER):
                if u.get("is_blocked"):
                    buttons.append([UI.go("✅ رفع بلاک کاربر",
                                          f"user_unblock:{target_user_id}",
                                          tone="success")])
                else:
                    buttons.append([UI.danger("⛔ بلاک کاربر",
                                              f"user_block:{target_user_id}")])
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

    # ══════════════════════════════════════════════════════════════
    #  v2.17.0: بلاک کاربر — گیتِ اجرا + UI مدیریتی
    # ══════════════════════════════════════════════════════════════

    async def _enforce_block(self, user_id: int, event, role: str = None) -> bool:
        """گیت بلاک — اگر کاربر بلاک شده باشد، پیامِ مناسب می‌دهد و True
        برمی‌گرداند تا فراخواننده همان‌جا return کند. مدیران عملاً بلاک
        نمی‌شوند (گارد در block_saas_user)، ولی نقش هم اینجا دوباره چک
        می‌شود تا حتی ویرایشِ دستیِ DB نتواند مدیریت را قفل کند."""
        try:
            r = role if role is not None else self._role(user_id)
            if r in (ROLE_OWNER, ROLE_ADMIN):
                return False
            if not is_user_blocked(user_id):
                return False
        except Exception:
            # خطای DB نباید ربات را برای بقیه خراب کند — fail-open فقط برای
            # همین چکِ اضافی؛ بقیه‌ی مسیر همچنان گاردهای خودش را دارد.
            return False
        try:
            if getattr(event, "query", None) is not None:
                await event.answer("⛔ حساب شما توسط مدیریت مسدود شده است.",
                                   alert=True)
            else:
                await event.respond(
                    "⛔ **دسترسی شما به این ربات مسدود شده است.**\n\n"
                    "در صورت نیاز، از طریق پشتیبانی پیگیری کنید.")
        except Exception:
            pass
        return True

    async def _show_user_block_confirm(self, event, target_user_id: int,
                                        back_data: bytes = b"owner_users"):
        """صفحه‌ی تأییدِ بلاک — کار خطرناک، پس یک قدمِ اضافه دارد."""
        viewer_role = self._role(event.sender_id)
        target_role = self._role(target_user_id)
        if viewer_role not in (ROLE_OWNER, ROLE_ADMIN) \
                or target_role == ROLE_OWNER \
                or (target_role == ROLE_ADMIN and viewer_role != ROLE_OWNER) \
                or not get_user(target_user_id):
            await event.answer("⛔ اجازه‌ی این کار را نداری.", alert=True)
            return
        u = get_user(target_user_id)
        name = u.get("username") or f"کاربر {target_user_id}"
        n_bots, n_active, _ = self._user_selfbot_stats(target_user_id)
        buttons = [
            [UI.danger("⛔ تأیید بلاک", f"user_block_go:{target_user_id}:{back_data.decode()}")],
            [UI.go("↩️ انصراف", f"user_manage:{target_user_id}:{back_data.decode()}")],
        ]
        await event.edit(
            UI.screen(
                "⛔ بلاک کاربر",
                body=[
                    f"👤 {name} — `{target_user_id}`",
                    f"🤖 سلف‌ها: {fa_digits(n_active)} فعال از {fa_digits(n_bots)}",
                    "",
                    "با تأیید، دسترسیِ کاملِ این کاربر به ربات قطع و همه‌ی",
                    "سلف‌هایش متوقف می‌شود. داده‌ها/کیف پول/تاریخچه حفظ",
                    "می‌شوند و با «رفع بلاک» همه‌چیز برگردد.",
                ],
                hint="این عمل در لاگ حسابرسی ثبت می‌شود.",
            ),
            buttons=buttons,
        )

    async def _do_block_user(self, event, target_user_id: int,
                             back_data: bytes = b"owner_users"):
        """اجرای بلاک — چک دسترسی دوباره در Backend (block_saas_user) +
        توقف سلف‌های کاربر + رندر دوباره‌ی پنل مدیریت."""
        res = block_saas_user(target_user_id, event.sender_id)
        if not res.get("ok"):
            err_map = {
                "permission_denied": "⛔ اجازه‌ی این کار را نداری.",
                "cannot_block_owner": "⛔ مالک قابل بلاک‌کردن نیست.",
                "admin_needs_owner": "⛔ بلاکِ ادمین فقط توسط مالک ممکن است.",
                "user_not_found": "❌ این کاربر پیدا نشد.",
            }
            await event.answer(
                err_map.get(res.get("error"), "❌ خطای نامشخص."), alert=True)
            return
        try:
            await self._stop_user_selfbots_for_block(target_user_id)
        except Exception as e:
            print(f"⚠️ [block] توقف سلف‌های {target_user_id} ناموفق: {e}")
        try:
            await self.client.send_message(
                target_user_id,
                "⛔ حساب شما توسط مدیریت مسدود شد و سلف‌های شما متوقف شد.",
            )
        except Exception:
            pass
        try:
            await event.answer("✅ کاربر بلاک شد.")
        except Exception:
            pass
        await self._show_user_management_panel(event, target_user_id,
                                                back_data=back_data)

    async def _do_unblock_user(self, event, target_user_id: int,
                               back_data: bytes = b"owner_users"):
        """رفع بلاک — اگر اشتراکِ فعال داشته باشد، سلف‌هایش که فقط به‌خاطر
        بلاک خاموش شده بودند دوباره روشن می‌شوند."""
        res = unblock_saas_user(target_user_id, event.sender_id)
        if not res.get("ok"):
            await event.answer("⛔ رفع بلاک انجام نشد (دسترسی/کاربر).", alert=True)
            return
        try:
            await self._resume_user_selfbots(
                target_user_id, reason="user_blocked", require_active_sub=True)
        except Exception as e:
            print(f"⚠️ [unblock] روشن‌کردن سلف‌های {target_user_id} ناموفق: {e}")
        try:
            await self.client.send_message(
                target_user_id,
                "✅ حساب شما بازگردانده شد. اگر اشتراک فعال داشته باشی، "
                "سلف‌هایت به‌زودی دوباره روشن می‌شوند.",
            )
        except Exception:
            pass
        try:
            await event.answer("✅ بلاک برداشته شد.")
        except Exception:
            pass
        await self._show_user_management_panel(event, target_user_id,
                                                back_data=back_data)

    async def _stop_user_selfbots_for_block(self, user_id: int):
        """توقفِ همه‌ی سلف‌های یک کاربرِ بلاک‌شده — بدون حذف چیزی. دلیلِ قطع
        'user_blocked' ثبت می‌شود تا رفعِ بلاک فقط همین‌ها را روشن کند.
        برخلاف انقضای اشتراک، اینجا همه‌ی اکانت‌های خودِ کاربر (حتی manual)
        متوقف می‌شوند چون دسترسیِ او به سرویس به‌طور کامل قطع شده؛ ولی
        scope با account_belongs_to به همین کاربر محدود است و config خراب
        هرگز overwrite نمی‌شود."""
        cfg = self.sb.load_config()
        if config_state() != CONFIG_VALID:
            print("⛔ [block] توقف سلف‌های کاربر بلاک‌شده رد شد — config.json خراب است.")
            return
        changed = False
        for tag, acc in cfg.items():
            if not account_belongs_to(acc, tag, user_id):
                continue
            stopped_ok = await ensure_stopped(tag, "block._stop_user_selfbots_for_block")
            if not stopped_ok:
                print(f"⚠️ [block] ensure_stopped({tag}) failed — بعداً دوباره تلاش می‌شود")
                continue
            if not acc.get("disabled"):
                acc["disabled"] = True
                acc["disabled_reason"] = "user_blocked"
                changed = True
        if changed:
            self.sb.save_config(cfg)

    # ══════════════════════════════════════════════════════════════
    #  v2.17.0: اشتراک دسته‌جمعی — ویزارد خرید (فقط کاربرِ بدون اشتراک)
    # ══════════════════════════════════════════════════════════════

    def _group_sub_gate_ok(self, event) -> bool:
        """گیتِ مشترکِ صفحاتِ خریدِ دسته‌جمعی: فعال باشد + خریدار نقش مدیریتی
        نداشته باشد + اشتراکِ فعالی نداشته باشد (خواسته‌ی مالک: فقط برای
        کاربرانی که اشتراک ندارند)."""
        if not group_sub_enabled():
            return False
        if self._role(event.sender_id) in (ROLE_OWNER, ROLE_ADMIN):
            return False
        if get_active_subscription(event.sender_id):
            return False
        return True

    async def _user_start_group_sub(self, event):
        """👥 ورود به خریدِ دسته‌جمعی — انتخاب پلنِ پایه."""
        if not self._group_sub_gate_ok(event):
            await event.answer(
                "👥 خرید دسته‌جمعی فقط برای کاربرانِ بدونِ اشتراکِ فعال است "
                "(و اگر مالک آن را خاموش کرده باشد، غیرفعال).",
                alert=True)
            return
        plans = [p for p in list_pricing() if not is_group_plan(p["plan"])]
        if not plans:
            await event.answer("هنوز پلنی ثبت نشده است.", alert=True)
            return
        discount = group_sub_discount_percent()
        buttons = [
            [UI.go(f"{p['plan']} — {p['price_toman']:,} تومان",
                   f"group_plan:{p['plan']}".encode())]
            for p in plans
        ]
        buttons.append(UI.nav_row())
        await event.edit(
            "👥 **اشتراک دسته‌جمعی**\n\n"
            "یک فاکتور برای کلِ گروه می‌دی؛ اشتراکِ خودت همان‌جا فعال "
            "می‌شه و برای بقیه‌ی اعضا کدِ لایسنس می‌گیری (هر کد = یک "
            "اشتراک کامل).\n\n"
            f"🎁 تخفیف گروهی: {fa_digits(discount)}٪ روی مجموع\n"
            "👇 پلنِ پایه رو انتخاب کن:",
            buttons=buttons,
        )

    async def _user_group_seats(self, event, base_plan: str):
        """انتخاب تعداد نفرات (شامل خودِ خریدار)."""
        if not self._group_sub_gate_ok(event):
            await event.answer("این گزینه فعلاً در دسترس نیست.", alert=True)
            return
        base = next((p for p in list_pricing()
                     if p["plan"] == base_plan and not is_group_plan(p["plan"])), None)
        if not base:
            await event.answer("پلن نامعتبر است.", alert=True)
            return
        discount = group_sub_discount_percent()
        buttons = []
        for seats in GROUP_SEATS_CHOICES:
            total = int(round(base["price_toman"] * seats * (100 - discount)
                             / 100 / 1000.0)) * 1000
            total = max(1000, total)
            per = total // seats
            buttons.append([UI.go(
                f"👥 {fa_digits(seats)} نفره — مجموع {fa_digits(total)} تومان "
                f"(~{fa_digits(per)} به‌ازای هر نفر)",
                f"group_seats:{base_plan}:{seats}".encode())])
        buttons.append(UI.nav_row())
        await event.edit(
            f"👥 **دسته‌جمعی — {base_plan}**\n\n"
            "چند نفره؟ (شامل خودت)\n"
            f"🎁 تخفیف {fa_digits(discount)}٪ روی کلِ مبلغ",
            buttons=buttons,
        )

    async def _user_group_chosen(self, event, base_plan: str, seats: int):
        """ساختِ فاکتورِ دسته‌جمعی — پلنِ گروهی در pricing ثبت می‌شود و بعد
        سفارش از همان مسیر عادی می‌رود؛ یعنی همه‌ی روش‌های پرداخت (کیف
        پول/کارت/تتر/درگاه) بدون هیچ تغییری کار می‌کنند."""
        if not self._group_sub_gate_ok(event):
            await event.answer("این گزینه فعلاً در دسترس نیست.", alert=True)
            return
        if seats not in GROUP_SEATS_CHOICES:
            await event.answer("تعداد نفرات نامعتبر است.", alert=True)
            return
        base = next((p for p in list_pricing()
                     if p["plan"] == base_plan and not is_group_plan(p["plan"])), None)
        if not base:
            await event.answer("پلن نامعتبر است.", alert=True)
            return
        ginfo = register_group_plan(base, seats)
        usdt, rate = await self._compute_order_amounts(ginfo["price_toman"])
        order = create_order(event.sender_id, ginfo["plan"],
                             ginfo["price_toman"], usdt)
        # بقیه‌اش مثل هر فاکتور دیگری است؛ بعد از پرداخت، مسیرِ عادی
        # اشتراکِ خریدار را فعال می‌کند و maybe_fulfill_group_order
        # (core) کدهای بقیه‌ی اعضا را می‌سازد و می‌فرستد.
        await self._show_invoice(event, order, rate)

    # ══════════════════════════════════════════════════════════════
    #  v2.17.0: گزینه‌های مالک — آزمایشی/دسته‌جمعی
    # ══════════════════════════════════════════════════════════════

    async def _owner_toggle_trial(self, event):
        """🎁 روشن/خاموش‌کردنِ اعطایِ خودکارِ اشتراکِ آزمایشی به کاربرانِ جدید.
        v2.22.0: برگشت به صفحهٔ مخصوصِ آزمایشی (نه هابِ تنظیمات) — چون
        تعدادِ روزها هم آنجاست و کلِ بخش یک‌جا دیده می‌شود."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط مالک.", alert=True)
            return
        new_val = "0" if trial_enabled() else "1"
        set_setting(TRIAL_SETTING_KEY, new_val, actor_id=event.sender_id)
        log_action(event.sender_id, "trial_toggled", f"new={new_val}")
        try:
            await event.answer(
                "🎁 اعطایِ خودکار: " + ("روشن" if new_val == "1" else "خاموش"))
        except Exception:
            pass
        await self._owner_show_trial_settings(event)

    async def _owner_toggle_group_sub(self, event):
        """👥 روشن/خاموش‌کردن خرید اشتراک دسته‌جمعی."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط مالک.", alert=True)
            return
        new_val = "0" if group_sub_enabled() else "1"
        set_setting(GROUP_SUB_SETTING_KEY, new_val, actor_id=event.sender_id)
        log_action(event.sender_id, "group_sub_toggled", f"new={new_val}")
        try:
            await event.answer(
                "👥 اشتراک دسته‌جمعی: " + ("روشن" if new_val == "1" else "خاموش"))
        except Exception:
            pass
        await self._admin_show_settings_hub(event)

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
        ⚙️ مدیریت یک SelfBot از داخل مدیریت کاربر — برای OWNER یک «صفحه‌ی
        اکشن‌های سریع» مخصوص نشان داده می‌شود که در یک نگاه همه‌ی عملیاتِ
        مهم (قابلیت‌ها / اتصال و پروکسی / وضعیت / ارسال پیام / فعال‌سازی /
        توقف / حذف) را در دسترس دارد، بدون اینکه اول وارد هاب اکانت بشود
        و بعد زیر-دکمه‌ها را کلیک کند.

        PATCH (v2.0.7 UX): قبلاً کلیک روی یک SelfBot از داخل پنل مدیریت
        کاربر، مستقیم به admin_panel._show_account_detail می‌رفت — یعنی OWNER
        باید اول وارد هاب اکانت می‌شد، بعد «🌐 اتصال و پروکسی» را باز می‌کرد،
        بعد تنظیم می‌کرد، بعد برگشت و «⚡ قابلیت‌ها» را باز می‌کرد، و الی
        آخر. حالا برای OWNER یک صفحه‌ی «اکشن‌های سریع» نشان داده می‌شود که
        مستقیماً از همین نقطه، هر کدام از آن زیر-صفحه‌ها را با یک کلیک باز
        می‌کند. مسیرِ بازگشت هم همان جایی است که از آن آمده‌ایم (پشته‌ی
        ناوبری)، پس هیچ پیچیدگی اضافه نشده.

        مالکیت دوباره چک می‌شود: tag باید متعلق به target_user_id باشد و
        فقط OWNER/ADMIN یا نماینده‌ی مالکِ آن کاربر می‌تواند وارد شود
        (چک در دیسپچ قبل از این تابع انجام شده).
        """
        cfg = self.sb.load_config()
        acc = cfg.get(tag)
        if not account_belongs_to(acc, tag, target_user_id):
            await self._nav_heal(event, "این اکانت متعلق به این کاربر نیست.")
            return

        viewer_role = self._role(event.sender_id)
        # PATCH (v2.0.7): برای OWNER و ADMIN صفحه‌ی «اکشن‌های سریع» اختصاصی
        # نشان داده می‌شود؛ برای RESELLER همان هاب اکانت قبلی. (نماینده‌ها
        # نیازی به bulk fast-access ندارند چون معمولاً فقط ۱-۲ کاربرِ
        # محدود دارند و کل آن‌ها را پشت یک کلیک دیده می‌شوند.)
        if viewer_role in (ROLE_OWNER, ROLE_ADMIN):
            await self._show_user_acc_quick_actions(event, target_user_id, tag)
        else:
            # مسیرِ بازگشت از پشته می‌آید — دیگر لازم نیست مقصد را اینجا
            # بسازیم و در callback_data جاسازی کنیم.
            await self.admin_panel._show_account_detail(event, tag)

    async def _show_user_acc_quick_actions(self, event, target_user_id: int, tag: str):
        """
        🚀 اکشن‌های سریع برای یک SelfBot از داخل پنلِ OWNER/ADMIN — همه‌ی
        عملیاتِ مهم در یک صفحه، بدون نیاز به ورود به هاب اکانت و بعد
        باز کردن زیر-دکمه‌ها.

        دکمه‌ها:
          ردیف ۱: ⚡ قابلیت‌ها  |  🎨 ظاهر
          ردیف ۲: 🌐 اتصال/پروکسی  |  📊 وضعیت
          ردیف ۳: 📨 ارسال پیام  |  🔒 دستگاه‌ها/2FA
          ردیف ۴: 🟢 فعال‌سازی / ⏸ توقف موقت
          ردیف ۵: ❌ حذف کامل
          ردیف ۶: 🔙 بازگشت

        هر دکمه به همان callbackهای ازپیش‌موجود در AdminBot هدایت می‌شود،
        ولی از طریق prefix `uacc_act:{action}:{user_id}:{tag}` تا ROLE و
        ownership دوباره در dispatch چک شود (دفاع در عمق).
        """
        cfg = self.sb.load_config()
        acc = cfg.get(tag, {})
        entry = self.sb.ACCOUNTS.get(tag)
        disabled = bool(acc.get("disabled"))
        state, status_text = _acc_ui_state(acc, tag)
        proxy_cfg = acc.get("proxy")
        on_count = sum(1 for f, _ in FEATURE_LABELS if entry and getattr(entry.bot, f, False))
        total_feats = len(FEATURE_LABELS)

        # شماره‌ی تلفن فقط برای OWNER/ADMIN (دارنده‌ی خودِ حساب هم آن را
        # می‌بیند در _show_account_detail، ولی اینجا در پنلِ مدیریت کاربر
        # فقط OWNER/ADMIN این صفحه را می‌بیند).
        phone = acc.get("phone") or "—"

        body = [
            f"🏷 تگ: `{tag}`",
            f"{UI.state_dot(state)} وضعیت: {status_text}",
            f"{UI.GRAY} نوع: {acc.get('type', 'user')} · شماره: `{phone}`",
            f"{UI.dot(bool(proxy_cfg))} پروکسی: {'تنظیم‌شده' if proxy_cfg else 'ندارد'}",
            f"{UI.dot(on_count > 0)} قابلیت‌های روشن: {fa_digits(on_count)} از {fa_digits(total_feats)}",
        ]

        # callback format: uacc_act:{action}:{user_id}:{tag}
        # action یکی از: feat, appear, conn, status, send, sess, tfa, enable, disable, del
        def _act(action: str) -> str:
            return f"uacc_act:{action}:{target_user_id}:{tag}"

        buttons = [
            [
                UI.go(f"⚡ قابلیت‌ها ({fa_digits(on_count)})", _act("feat")),
                UI.go("🎨 ظاهر", _act("appear")),
            ],
            [
                UI.go("🌐 اتصال و پروکسی", _act("conn")),
                UI.go("📊 وضعیت", _act("status")),
            ],
        ]
        # v2.8.11: دکمه‌های امنیتی برای OWNER و ADMIN
        # (قبلاً فقط OWNER بود — ADMIN نمی‌دید)
        # v2.8.11: دکمه‌ی «🔒 دستگاه‌ها/2FA» فقط دستگاه‌ها رو باز می‌کرد
        # ولی ظاهرش قول 2FA هم می‌داد. حالا به دو دکمه‌ی جدا تقسیم شده:
        #   "📱 دستگاه‌ها" — فقط دستگاه‌های لاگین‌شده
        #   "🔐 2FA" — رمز دو مرحله‌ای (تغییر/حذف/ریست)
        viewer_role = self._role(event.sender_id)
        if viewer_role in (ROLE_OWNER, ROLE_ADMIN):
            buttons.append([
                UI.go("📱 دستگاه‌ها", _act("sess")),
                UI.go("🔐 2FA", _act("tfa")),
            ])
            buttons.append([
                UI.go("📲 کد لاگین", _act("getcode")),
                UI.go("📨 ارسال پیام", _act("send")),
            ])
            # v2.12.24: محافظتِ ورود — toggle
            # v2.14.6 (USER-REQUEST): فقط مالک اصلی سلف دکمه را می‌بیند.
            _viewer_id_for_btn2 = event.sender_id
            _main_owner_for_btn2 = _security_main_owner_id()
            try:
                _extra_owners_for_btn2 = OWNER_IDS
            except NameError:
                _extra_owners_for_btn2 = set()
            _show_guard_btn2 = (
                (_main_owner_for_btn2 and _viewer_id_for_btn2 == _main_owner_for_btn2)
                or (_viewer_id_for_btn2 in _extra_owners_for_btn2)
            )
            if _show_guard_btn2:
                _entry = self.sb.ACCOUNTS.get(tag)
                _guard_on = _entry and getattr(_entry.bot, "login_code_guard", False)
                _guard_label = "🔒 محافظت ورود: روشن" if _guard_on else "🔓 محافظت ورود: خاموش"
                buttons.append([UI.go(_guard_label, _act("guard"))])
        else:
            buttons.append([UI.go("📨 ارسال پیام", _act("send"))])
        # عملیات حالت‌دار: سبز برای فعال‌سازی (اگر disabled)، خاکستری برای
        # توقف موقت (اگر enabled).
        if disabled:
            buttons.append([UI.confirm("🟢 فعال‌سازی اکانت", _act("enable"))])
        else:
            buttons.append([UI.neutral("⏸ توقف موقت SelfBot", _act("disable"))])
        # حذف کامل — قرمز، جدا از بقیه
        buttons.append([UI.danger("❌ حذف کامل اکانت", _act("del"))])
        # بازگشت از پشته‌ی ناوبری
        buttons.append(UI.nav_row())

        await event.edit(
            UI.screen(
                f"🚀 اکشن‌های سریع — {tag}",
                body=body,
                subtitle="یک کلیک تا هر عملیات — بدون ورود به هاب.",
                hint="📱 برای دستگاه‌های لاگین‌شده و 🔐 برای رمز دو مرحله‌ای.",
            ),
            buttons=buttons,
        )

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

    async def _resume_user_selfbots(self, user_id: int,
                                    reason: str = "subscription_expired",
                                    require_active_sub: bool = False):
        """
        بعد از تمدید/پرداخت موفق: سلف‌بات‌هایی که سرِ انقضای اشتراک متوقف و
        disabled شده بودند دوباره فعال می‌شوند — هم در config (تا در استارت
        بعدی هم روشن بمانند) و هم زنده (run_bot برای تگ‌های متوقف‌شده).
        Idempotent: فقط تگ‌هایی را لمس می‌کند که disabled هستند و هنوز در
        ACCOUNTS ثبت نشده‌اند.

        v2.17.0: پارامتر reason — دلیلِ قطعِ موردِ نظر (پیش‌فرض همان
        انقضای اشتراک؛ رفع بلاک با 'user_blocked' صدا می‌زند).
        require_active_sub=True یعنی فقط اگر اشتراکِ فعالی باشد ادامه بده
        (برای رفعِ بلاک — کاربرِ بدون اشتراک نباید سلفِ روشن داشته باشد).
        """
        if require_active_sub and not get_active_subscription(user_id):
            return
        cfg = self.sb.load_config()
        to_start = []
        changed = False
        for tag, acc in cfg.items():
            if not account_belongs_to(acc, tag, user_id):
                continue
            if not acc.get("disabled"):
                continue
            # فقط سلف‌بات‌هایی که دلیلِ قطعیِ خاموش‌شدنشان با reasonِ درخواستی
            # یکی است دوباره روشن می‌شوند (مثلاً subscription_expired یا
            # user_blocked). disabled_reason=None (legacy — معلوم نیست چرا
            # خاموش شده، شاید ادمین دستی) هرگز AUTO RESUME نمی‌شود؛ باید
            # دستی/توسط ادمین روشن شود.
            acc_reason = acc.get("disabled_reason")
            if acc_reason != reason:
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
            # v2.12.29 (DEEP-5 D-1): check return of ensure_stopped
            stopped_ok = await ensure_stopped(tag, "expiry._stop_and_disable_user_selfbots")
            if not stopped_ok:
                print(f"⚠️ [expiry] ensure_stopped({tag}) failed — "
                      f"account NOT disabled, will retry next loop")
                continue
            if not acc.get("disabled"):
                acc["disabled"] = True
                acc["disabled_reason"] = "subscription_expired"
                changed = True
        if changed:
            self.sb.save_config(cfg)

    # ══════════════════════════════════════════════════════════════════
    #  PATCH (v2.0.8): آپدیت خودکار و Rollback — فقط OWNER
    #  ─────────────────────────────────────────────────────────────────
    #  این بخش با ماژولِ cianet_updater.py که از قبل موجود بود (ولی به
    #  main.py متصل نبود) کار می‌کند. ماژول اصلی کارهای آپدیت (git fetch /
    #  git pull / backup / restart / propagation) را انجام می‌دهد؛ اینجا
    #  فقط UI و routing برای OWNER اضافه می‌شود.
    #
    #  همه‌ی توابع این بخش فقط برای ROLE_OWNER کار می‌کنند — چک صریح
    #  در callback_h و دوباره در اینجا با `self._role` انجام می‌شود.
    # ══════════════════════════════════════════════════════════════════

    def _import_updater_safe(self):
        """
        cianet_updater.py را به‌صورت lazy import می‌کند تا اگه import
        شکست خورد (مثلاً git نصب نیست یا فایل حذف شده)، ربات کرش نکند.
        """
        try:
            import cianet_updater
            return cianet_updater, None
        except Exception as e:
            return None, f"❌ cianet_updater import نشد: {type(e).__name__}: {e}"

    async def _show_owner_web_panel(self, event):
        """
        🌐 پنل وب — نشون‌دادن لینک به web panel و وضعیت service.

        PATCH (v2.1.7): حالا روی دکمه کلیک کنی، مستقیم URL باز می‌شه (با
        Telegram's URL button). قبلاً فقط یه صفحه نمایش داده می‌شد.

        URL از env var PANEL_URL خوانده می‌شه (مثلاً https://panel.cianet.ir
        یا http://localhost:8000). اگه تنظیم نشه، یه صفحه‌ی راهنما نشون
        داده می‌شه که چطور فعال کنه.

        همچنین وضعیت systemd service `cianet-panel` و `cianet-tunnel` رو
        چک می‌کنه (اگه روی همون سرور باشیم) و اگه running بود به کاربر
        می‌گه.
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return

        # URL از env
        panel_url = os.environ.get("PANEL_URL", "").strip().rstrip("/")
        # اگه تنظیم نباشه، یه حدس از PORT پیشنهاد می‌دیم
        # backend روی port 8000، frontend static روی همون port (path /app/*)
        backend_url = os.environ.get("PANEL_BACKEND_URL", "http://localhost:8000").strip().rstrip("/")

        # URL نهایی برای ورود: panel_url اگه تنظیم شده، وگرنه backend_url
        # frontend static روی /app/login.html هست
        if panel_url:
            login_url = f"{panel_url}/app/login.html"
            dashboard_url = f"{panel_url}/app/dashboard.html"
            docs_url = f"{panel_url}/api/docs"
        else:
            login_url = f"{backend_url}/app/login.html"
            dashboard_url = f"{backend_url}/app/dashboard.html"
            docs_url = f"{backend_url}/api/docs"

        # وضعیت service cianet-panel (اگه هست)
        panel_status = "نامشخص"
        try:
            import subprocess as _sp
            # BUG-19a: اجرا در thread — subprocess.runِ همگام روی event
            # loop تا ~۳ ثانیه آن را block می‌کرد (asyncio.to_thread با
            # همان آرگومان‌ها/timeout و همان مدیریتِ return-code).
            r = await asyncio.to_thread(
                _sp.run,
                ["systemctl", "is-active", "cianet-panel"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                panel_status = "✅ در حال اجرا" if r.stdout.strip() == "active" else f"⚠️ {r.stdout.strip()}"
            else:
                # اگه service نیست، inactive یا failed
                panel_status = "❌ نصب نشده"
        except Exception:
            panel_status = "❓ (امکان بررسی نبود)"

        # وضعیت service cianet-tunnel (اگه هست — از v2.1.6)
        # PATCH (v2.2.0): تمایز بین "نصب نشده" (returncode ۳/۴ از systemctl)
        # و "غیرفعال" (returncode ۱). قبلاً هر دو رو "غیرفعال" نشون می‌دادیم.
        tunnel_status = "نامشخص"
        try:
            import subprocess as _sp
            # BUG-19a: اجرا در thread — مثل بالا (بدون block شدنِ loop).
            r = await asyncio.to_thread(
                _sp.run,
                ["systemctl", "is-active", "cianet-tunnel"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                tunnel_status = "✅ متصل" if r.stdout.strip() == "active" else f"⚠️ {r.stdout.strip()}"
            elif r.returncode == 3 or r.returncode == 4:
                # exit 3 = unit is masked or not found; exit 4 = not loaded
                tunnel_status = "نصب نشده"
            else:
                # exit 1 = inactive; exit 2 = failed
                tunnel_status = "غیرفعال"
        except Exception:
            tunnel_status = "❓"

        body = []
        if panel_url:
            body.append(f"🌐 آدرس پنل:")
            body.append(f"   {login_url}")
            body.append("")
            body.append(f"{UI.GRAY} برای ورود از همون username/password که در")
            body.append(f"{UI.GRAY} نصب تنظیم کردی استفاده کن.")
        else:
            body.append(f"{UI.AMBER} ⚠️  PANEL_URL تنظیم نشده")
            body.append("")
            body.append(f"{UI.GRAY} پنل روی این آدرس در دسترس است (local):")
            body.append(f"   🌐 Login:  {login_url}")
            body.append(f"   📊 API:    {docs_url}")
            body.append("")
            body.append(f"{UI.GRAY} برای دسترسی از بیرون سرور، در فایل env:")
            body.append(f"{UI.GRAY} PANEL_URL=https://panel.your-domain.ir")
            body.append(f"{UI.GRAY} بعد از تنظیم، cianet رو restart کن.")

        body.append("")
        body.append(f"📊 وضعیت cianet-panel: {panel_status}")
        body.append(f"☁️  وضعیت cianet-tunnel: {tunnel_status}")
        body.append(f"{UI.GRAY} user: {os.environ.get('PANEL_ADMIN_USER', 'admin')}")

        # دکمه‌ها — URL button‌ها با کلیک مستقیم مرورگر رو باز می‌کنن
        from telethon import Button as _Button
        buttons = []
        # دکمه‌ی اصلی: باز کردن پنل
        buttons.append([_Button.url("🌐 باز کردن پنل (ورود)", login_url)])
        buttons.append([_Button.url("📊 داشبورد", dashboard_url)])
        buttons.append([_Button.url("📚 API docs (Swagger)", docs_url)])
        buttons.append(UI.nav_row())

        await event.edit(
            UI.screen("🌐 پنل وب CiaNet",
                      body=body,
                      subtitle="مدیریت کاملِ سلف‌بات‌ها از مرورگر",
                      hint="روی «🌐 باز کردن پنل» بزن تا مستقیم در مرورگر باز بشه"),
            buttons=buttons,
        )

    async def _show_owner_update(self, event):
        """
        صفحه‌ی اصلی «🔄 آپدیت و ورژن»:
          - ورژن محلی (commit hash و تاریخ)
          - آخرین commit روی remote
          - تعداد commit‌های pending
          - دکمه‌های: چک آپدیت / اعمال آپدیت / لیست نسخه‌های rollback
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return

        updater, err = self._import_updater_safe()
        if err:
            await event.edit(err, buttons=[UI.nav_row()])
            return

        try:
            # v2.19.4 (AUDIT-36 H7 — HIGH): get_version_info بدنه‌اش sync است
            # و دو git fetch با timeout=30s دارد — قبلاً مستقیم روی event loop
            # اجرا می‌شد و هنگامِ کندی/قطعیِ شبکه، کلِ ربات (همه‌ی هندلرها و
            # همه‌ی سلف‌بات‌ها) تا ~۶۰ ثانیه کامل فریز می‌شد. حالا در thread
            # جدا (الگوی موجودِ apply_update در همین فایل).
            info = await asyncio.to_thread(updater.get_version_info)
        except Exception as e:
            await event.edit(
                f"❌ خطا در گرفتن اطلاعات ورژن: {type(e).__name__}: {e}",
                buttons=[UI.nav_row()],
            )
            return

        local = info.get("local_commit") or "نامشخص"
        remote = info.get("remote_commit") or "نامشخص"
        pending = info.get("pending_commits") or []
        last_check = info.get("last_check", 0)
        last_update = info.get("last_update_at", 0)
        # v2.8.1: تشخیص تغییرات محلی (rollback یا replace دستی)
        has_local_mods = info.get("has_local_mods", False)
        rolled_back = info.get("rolled_back", False)
        rolled_back_at = info.get("rolled_back_at", 0)

        # فرمت‌سازی تاریخ‌ها به فارسی
        def _fmt_ts(ts: int) -> str:
            if not ts:
                return "—"
            try:
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
                return fa_digits(dt.strftime("%Y/%m/%d %H:%M"))
            except Exception:
                return str(ts)

        # v2.8.1: شرط «آپ‌تو‌دِیت» اکنون تعدیل شده — اگه فایل‌ها نسبت
        # به git HEAD تغییر کرده باشند (rollback/replace)، کاربر آپ‌تو‌دِیت
        # نیست، حتی اگه local == remote باشه. این جلوی bug 3 رو می‌گیره.
        # v2.8.13 C2: اگه git شکست خورده (local/remote = "نامشخص")، هرگز
        # آپ‌تو‌دِیت محسوب نشه — دکمه‌ی «اعمال آپدیت» نشون داده بشه تا کاربر
        # بتونه retry کنه. قبلاً "نامشخص" == "نامشخص" → True → دکمه پنهان
        # می‌شد و کاربر هیچ راهی نداشت.
        git_failed = (local == "نامشخص" or remote == "نامشخص")
        is_up_to_date = (not git_failed) and (local == remote) and not pending and not has_local_mods and not rolled_back
        body = [
            f"🏷 ورژن محلی: `{local[:8]}`" if local != "نامشخص" else "🏷 ورژن محلی: نامشخص",
            f"🌐 آخرین ورژن remote: `{remote[:8]}`" if remote != "نامشخص" else "🌐 ورژن remote: نامشخص",
        ]
        # v2.8.13 C2: اگه git شکست خورده، پیام خطا نشون بده
        if git_failed:
            body.append(f"{UI.RED} ⚠️ git در خواندن ورژن شکست خورد")
            body.append(f"{UI.GRAY} ممکن است مشکل permission یا ownership باشد.")
            body.append(f"{UI.GRAY} در لاگ سرور جزئیات هست. دکمه‌ی «اعمال آپدیت» رو بزن.")
        if is_up_to_date:
            body.append(f"{UI.GREEN} ✅ آپ‌تو‌دِیت هستی")
        elif git_failed:
            body.append(f"{UI.AMBER} ⚠️ وضعیت نامشخص — دکمه‌ی «اعمال آپدیت از git» رو بزن")
        else:
            if pending:
                body.append(f"{UI.AMBER} 📥 {fa_digits(len(pending))} commit جدید منتظر apply")
                for line in pending[:5]:
                    body.append(f"   `{line[:8]}` {line[9:60]}")
                if len(pending) > 5:
                    body.append(f"   {UI.GRAY}… و {fa_digits(len(pending) - 5)} commit دیگر")
            if rolled_back:
                # v2.8.1: کاربر rollback کرده — پیام واضح نشون بده
                body.append(f"{UI.AMBER} ↩️ به نسخه‌ی قدیمی rollback شده")
                if rolled_back_at:
                    body.append(f"{UI.GRAY} زمان rollback: {_fmt_ts(int(rolled_back_at))}")
            elif has_local_mods:
                # v2.8.1: فایل‌ها دستی replace شده — پیام نشون بده
                body.append(f"{UI.AMBER} ⚠️ فایل‌های محلی با git HEAD هم‌خوانی ندارند")
                body.append(f"{UI.GRAY} (ممکن است rollback یا replace دستی انجام شده باشد)")
        body.append("")
        body.append(f"{UI.GRAY} آخرین چک: {_fmt_ts(last_check)}")
        body.append(f"{UI.GRAY} آخرین آپدیت: {_fmt_ts(last_update)}")

        buttons = []
        if not is_up_to_date or git_failed:
            # v2.8.13: دکمه‌ی «اعمال آپدیت» همیشه نشون داده می‌شه —
            # چه commit جدید باشه، چه rollback، چه فایل‌ها دستی replace
            # شده باشند، چه git شکست خورده باشه. در همه‌ی این موارد،
            # apply_update کار درستی انجام می‌ده.
            buttons.append([UI.confirm("📥 اعمال آپدیت از git", "owner_update_apply")])
        buttons.append([UI.go("🔄 چک آپدیت", "owner_update_check")])
        buttons.append([UI.go("↩️ لیست نسخه‌های قابل rollback", "owner_rollback_list")])
        # PATCH (v2.3.0): auto-update toggle
        auto_enabled = os.environ.get("CIANET_AUTO_UPDATE", "0").strip() in ("1", "true", "yes")
        if auto_enabled:
            buttons.append([UI.go("🟢 آپدیت خودکار: فعال", "owner_toggle_auto_update")])
        else:
            buttons.append([UI.go("⚫ آپدیت خودکار: خاموش", "owner_toggle_auto_update")])
        buttons.append(UI.nav_row())

        await event.edit(
            UI.screen("🔄 آپدیت و ورژن",
                      body=body,
                      subtitle="آپدیت‌های جدید یا بازگشت به نسخه‌ی قبل.",
                      hint="📥 اعمال آپدیت → restart خودکار. ↩️ rollback → جایگزینی main.py."),
            buttons=buttons,
        )

    async def _owner_check_update(self, event):
        """دکمه‌ی «🔄 چک آپدیت» — صرفاً دوباره fetch می‌کند و صفحه را refresh."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return
        try:
            await event.answer("🔄 در حال چک کردن...")
        except Exception:
            pass
        await self._show_owner_update(event)

    async def _owner_apply_update(self, event):
        """
        دکمه‌ی «📥 اعمال آپدیت»:
        1. backup main.py (به versions/main.py.pre-auto-update.<ts>)
        2. git fetch + reset --hard origin/main
        3. systemctl restart (با auto-detect service name)
        4. بعد از restart، cianet_updater.propagate_to_accounts به‌صورت
           خودکار اکانت‌ها را enable می‌کند.

        v2.9.5: پیام «لطفاً صبر کنید...» قبل از شروع آپدیت نشون داده می‌شه
        تا کاربر بفهمه چیزی داره اتفاق می‌افته. قبلاً سایلنت بود.
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return

        updater, err = self._import_updater_safe()
        if err:
            await event.answer(err, alert=True)
            return

        # v2.9.5: پیام واضح قبل از شروع — قبلاً فقط یه alert کوچیک بود
        try:
            await event.edit(
                UI.screen("📥 در حال آپدیت...",
                          body=[
                              "⏳ لطفاً صبر کنید...",
                              "",
                              f"{UI.GRAY} ۱. بکاپ از main.py فعلی",
                              f"{UI.GRAY} ۲. git fetch + reset --hard",
                              f"{UI.GRAY} ۳. systemctl restart",
                              f"{UI.GRAY} ۴. اکانت‌ها دوباره وصل می‌شن",
                              "",
                              f"{UI.AMBER} این ممکنه ۱۰-۳۰ ثانیه طول بکشه.",
                          ],
                          subtitle="اگه بیش از ۶۰ ثانیه طول کشید، SSH بزن."),
                buttons=[],
            )
        except Exception:
            pass

        # P2-2 (BUG-18c wiring / §14.1 گام ۷ — طبق الگوی مستندشده در گزارش
        # P1-9): main_loop را به apply_update پاس بده تا hookِ غیرفعال‌سازی
        # اکانت‌ها (_disable_all_accounts_for_update) از طریق
        # run_coroutine_threadsafe روی همینِ loopِ در حالِ اجرا schedule شود.
        # قبلاً main_loop=None بود و hook فقط در مسیر auto-update اجرا می‌شد.
        import functools
        loop = asyncio.get_running_loop()
        try:
            success, msg = await loop.run_in_executor(
                None, functools.partial(updater.apply_update, main_loop=loop)
            )
        except Exception as e:
            await event.edit(
                f"❌ خطا در apply_update: {type(e).__name__}: {e}",
                buttons=[UI.go("🔄 بازگشت", "owner_update"), UI.nav_row()],
            )
            return

        if success:
            await event.edit(
                UI.screen("✅ آپدیت اعمال شد",
                          body=[
                              msg,
                              "",
                              f"{UI.GRAY} سرویس در حال restart است.",
                              f"{UI.GRAY} بعد از بالا آمدن، اکانت‌ها خودکار re-enable می‌شوند.",
                          ],
                          subtitle="اگه تا ۳۰ ثانیه دیگر ربات پاسخ نداد، SSH بزن و لاگ رو ببین."),
                buttons=[UI.nav_row()],
            )
        else:
            await event.edit(
                f"❌ آپدیت ناموفق بود:\n\n{msg}",
                buttons=[UI.go("🔄 بازگشت", "owner_update"), UI.nav_row()],
            )

    async def _owner_toggle_auto_update(self, event):
        """
        🔄 روشن/خاموش‌کردنِ آپدیت خودکار (هر ۶ ساعت).

        PATCH (v2.3.0): با toggle این دکمه، متغیر CIANET_AUTO_UPDATE در
        فایل env file ست/پاک می‌شه. برای اعمال، cianet restart لازمه.

        اگه فعال باشه، _auto_update_loop (که در _run_all_accounts صدا
        زده می‌شه) هر ۶ ساعت یک‌بار check_for_update می‌کنه و اگه آپدیت
        جدیدی باشه، apply_update اجرا می‌شه (با notify به OWNER قبل از
        restart).
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return

        # پیدا کردن env file
        env_file = None
        _proj_dir = os.path.dirname(os.path.abspath(__file__))
        for candidate in ["/etc/cianet.env", "/etc/selfbot.env",
                          os.path.join(_proj_dir, ".env"),
                          os.path.join(_proj_dir, "cianet.env")]:
            if os.path.exists(candidate):
                env_file = candidate
                break
        if env_file is None:
            await event.answer("❌ فایل env پیدا نشد — دستی در env تنظیم کن: CIANET_AUTO_UPDATE=1", alert=True)
            return

        # مقدار فعلی
        auto_enabled = os.environ.get("CIANET_AUTO_UPDATE", "0").strip() in ("1", "true", "yes")
        # toggle
        new_value = "0" if auto_enabled else "1"

        # ست کردن در env file (اضافه یا replace)
        # v2.8.13: Wrap in try/except — اگه permission denied شد،
        # به‌جای crash با «خطا در پردازش این دکمه»، پیام واضح بده.
        import re
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                content = f.read()
            if re.search(r"^CIANET_AUTO_UPDATE=", content, re.MULTILINE):
                content = re.sub(r"^CIANET_AUTO_UPDATE=.*$", f"CIANET_AUTO_UPDATE={new_value}", content, flags=re.MULTILINE)
            else:
                content = content.rstrip() + f"\nCIANET_AUTO_UPDATE={new_value}\n"
            with open(env_file, "w", encoding="utf-8") as f:
                f.write(content)
        except PermissionError as _e:
            await event.answer(
                f"❌ Permission denied — فایل {env_file} قابل نوشتن نیست.\n"
                f"دستی بزن:\n"
                f"  sudo sed -i '/^CIANET_AUTO_UPDATE=/d' {env_file}\n"
                f"  echo CIANET_AUTO_UPDATE={new_value} | sudo tee -a {env_file}\n"
                f"  sudo systemctl restart selfbot",
                alert=True,
            )
            return
        except Exception as _e:
            await event.answer(f"❌ خطا در نوشتن env file: {_e}", alert=True)
            return

        # also update in-process env
        os.environ["CIANET_AUTO_UPDATE"] = new_value

        # v2.8.13 C6: اگه فعال شد، loop رو همین حالا spawn کن —
        # نیاز به restart نباشه.
        if new_value == "1":
            # BUG-17a (§20.7): قبلاً asyncio.create_task خامِ fire-and-forget
            # بود — ریسکِ GC و duplicate. طبق الگوی مستند، تسک در متغیرِ
            # ماژول‌سطح با done-check نگه داشته می‌شود و _spawn_bg ارجاعِ
            # قوی و لاگِ خطا را تضمین می‌کند.
            global _AUTO_UPDATE_TASK
            try:
                if _AUTO_UPDATE_TASK is None or _AUTO_UPDATE_TASK.done():
                    _AUTO_UPDATE_TASK = _spawn_bg(
                        _auto_update_loop_wrapper(), "auto-update"
                    )
                    print("🌐 [auto_update] loop هم‌اکنون spawn شد")
            except Exception as _e:
                print(f"⚠️ [auto_update] spawn loop ناموفق: {_e}")

        msg = "🟢 آپدیت خودکار فعال شد" if new_value == "1" else "⚫ آپدیت خودکار خاموش شد"
        if new_value == "1":
            msg += "\n\n✅ loop هم‌اکنون شروع شد — نیازی به restart نیست."
        else:
            msg += "\n\n⚠️ loop در next iteration متوقف می‌شه (تا ۵ دقیقه)."
        await event.answer(msg, alert=True)
        # refresh صفحه
        await self._show_owner_update(event)

    async def _owner_show_rollback_list(self, event):
        """
        لیست نسخه‌های قابل rollback:
          - فایل‌های `versions/main.py.pre-auto-update.<ts>` (آپدیت‌های اخیر)
          - فایل‌های `versions/v*.py` (نسخه‌های قدیمی‌تر)
          - فایل‌های `versions/stable/*.py`
        برای هر کدام، دکمه‌ای نشان داده می‌شود تا OWNER بتواند rollback کند.
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return

        import os as _os
        from pathlib import Path as _Path
        install_dir = _os.environ.get("CIANET_INSTALL_DIR", _os.path.dirname(_os.path.abspath(__file__)))
        versions_dir = _Path(install_dir) / "versions"

        try:
            candidates = []
            if versions_dir.exists():
                # ۱. فایل‌های pre-auto-update.<ts>
                for f in sorted(versions_dir.glob("main.py.pre-auto-update.*"), reverse=True):
                    if f.is_file():
                        try:
                            size = f.stat().st_size
                        except Exception:
                            size = 0
                        candidates.append((f.name, "backup خودکار", f, size))
                # ۲. فایل‌های v*.py (نسخه‌های قدیمی‌تر)
                for f in sorted(versions_dir.glob("v*.py"), reverse=True):
                    if f.is_file():
                        try:
                            size = f.stat().st_size
                        except Exception:
                            size = 0
                        candidates.append((f.name, "نسخه‌ی قدیمی", f, size))
                # ۳. versions/stable/*.py
                stable = versions_dir / "stable"
                if stable.exists():
                    for f in sorted(stable.glob("*.py"), reverse=True):
                        if f.is_file():
                            try:
                                size = f.stat().st_size
                            except Exception:
                                size = 0
                            candidates.append((f"stable/{f.name}", "stable", f, size))
        except Exception as e:
            await event.edit(
                f"❌ خطا در لیست نسخه‌ها: {type(e).__name__}: {e}",
                buttons=[UI.nav_row()],
            )
            return

        if not candidates:
            body = [
                f"{UI.GRAY} هنوز هیچ نسخه‌ی پشتیبان یا قدیمی موجود نیست.",
                "",
                f"{UI.GRAY} بعد از اولین آپدیت، فایل main.py قبل از آپدیت در",
                f"{UI.GRAY} پوشه‌ی versions/ ذخیره می‌شود و قابل rollback خواهد بود.",
            ]
            buttons = [UI.nav_row()]
            await event.edit(
                UI.screen("↩️ Rollback", body=body,
                          subtitle="هیچ نسخه‌ی پشتیبان موجود نیست."),
                buttons=buttons,
            )
            return

        # v2.8.1: pagination — ۱۰ نسخه در هر صفحه + دکمه‌های «صفحه‌ی قبل/بعد».
        # قبلاً فقط candidates[:10] نشون داده می‌شد و بقیه مخفی می‌موندن.
        # حالا با page number از callback data می‌آد.
        page = 1
        # اگه از pagination callback اومده، page رو از data بگیر
        if hasattr(event, "_rollback_page"):
            page = max(1, int(getattr(event, "_rollback_page", 1)))
        per_page = 10
        total = len(candidates)
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages
        start = (page - 1) * per_page
        shown = candidates[start:start + per_page]
        body = [
            f"📦 {fa_digits(total)} نسخه‌ی قابل rollback موجود:",
            f"{UI.GRAY} صفحه‌ی {fa_digits(page)} از {fa_digits(total_pages)}",
            "",
        ]
        buttons = []
        for name, kind, path, size in shown:
            size_kb = fa_digits(max(1, size // 1024))
            body.append(f"• `{name}` ({size_kb} KB) — {kind}")
            import urllib.parse as _up
            encoded = _up.quote(name, safe="")
            buttons.append([UI.danger(f"↩️ {name}", f"owner_rollback_go:{encoded}")])
        # دکمه‌های pagination
        nav_btns = []
        if page > 1:
            nav_btns.append(UI.neutral(f"« صفحه‌ی {fa_digits(page - 1)}",
                                       f"owner_rollback_page:{page - 1}"))
        if page < total_pages:
            nav_btns.append(UI.neutral(f"صفحه‌ی {fa_digits(page + 1)} »",
                                       f"owner_rollback_page:{page + 1}"))
        if nav_btns:
            buttons.append(nav_btns)
        buttons.append(UI.nav_row())

        await event.edit(
            UI.screen("↩️ Rollback به نسخه",
                      body=body,
                      subtitle=f"روی هر کدام بزن تا main.py جایگزین شود. — صفحه {fa_digits(page)}/{fa_digits(total_pages)}",
                      hint="⚠️ قبل از rollback، main.py فعلی به‌صورت خودکار backup می‌شود."),
            buttons=buttons,
        )

    async def _owner_rollback_go(self, event, encoded_name: str):
        """
        اجرای rollback: جایگزینی main.py با نسخه‌ی انتخاب‌شده.
        قبل از جایگزینی، main.py فعلی به‌صورت خودکار به
        versions/main.py.pre-rollback.<ts> backup می‌شود.
        بعد از جایگزینی، systemctl restart cianet.
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return

        import urllib.parse as _up
        import os as _os
        from pathlib import Path as _Path
        import shutil as _shutil
        import time as _time

        name = _up.unquote(encoded_name)
        install_dir = _os.environ.get("CIANET_INSTALL_DIR", _os.path.dirname(_os.path.abspath(__file__)))
        versions_dir = _Path(install_dir) / "versions"
        main_py = _Path(install_dir) / "main.py"
        if not main_py.exists():
            main_py = _Path(_os.path.abspath(__file__))

        # TEST-G6-SYSTEM (BUG: EDGE_CASE_CRASH / SECURITY — path traversal.
        # The previous code had a third fallback `_Path(name)` that allowed
        # `name` like `../../etc/passwd` (after URL-decoding) to escape
        # `versions_dir` and replace main.py with arbitrary content.
        # Even though `name` normally comes from server-generated buttons,
        # a crafted callback (e.g. an attacker who controls an inline
        # button's `data`, or a planted file named `..` inside
        # `versions_dir`) could exploit this. Now: reject any `name`
        # containing path separators / traversal segments, and verify
        # the resolved `src_path` actually stays inside `versions_dir`.)
        #
        # v2.19.4 (AUDIT-36 M5 — MEDIUM): لیستِ rollback خودِ ربات نام‌های
        # stable/... را می‌سازد و گاردِ قبلی صددرصدشان را رد می‌کرد — یعنی
        # rollback به نسخه‌های stable همیشه «نامِ نسخه نامعتبر» می‌گرفت با
        # اینکه دکمه‌اش را خودِ ربات نمایش داده بود. حالا فقط همین پیشوندِ
        # دقیقِ یک‌سطحی مجاز است و روی sub-name همان گاردِ traversal اجرا
        # می‌شود؛ resolve-check پایین‌تر همچنان لایه‌ی دوم است.
        _stable_ok = False
        if name.startswith("stable/") and name.count("/") == 1:
            _sub = name[len("stable/"):]
            if _sub and "\\" not in _sub and _sub not in (".", ".."):
                _stable_ok = True
        if (not name or name in (".", "..")
                or (("/" in name or "\\" in name) and not _stable_ok)):
            await event.edit(
                f"❌ نام نسخه نامعتبر است: `{name}`",
                buttons=[UI.go("↩️ بازگشت", "owner_rollback_list"), UI.nav_row()],
            )
            return

        # پیدا کردن فایلِ مبدا
        src_path = None
        candidate1 = versions_dir / name
        if candidate1.is_file():
            src_path = candidate1
        if src_path is None:
            candidate2 = versions_dir / "stable" / name
            if candidate2.is_file():
                src_path = candidate2
        # TEST-G6-SYSTEM: حذفِ fallbackِ `_Path(name)` — فقط فایل‌های
        # داخلِ versions_dir/ یا versions_dir/stable/ قابل rollback
        # هستند. گارد نهایی: src_path حتماً باید زیر versions_dir باشد.
        if src_path is not None:
            try:
                _src_resolved = src_path.resolve()
                _ver_resolved = versions_dir.resolve()
                if _src_resolved != _ver_resolved and _ver_resolved not in _src_resolved.parents:
                    src_path = None
            except Exception:
                src_path = None

        if src_path is None:
            await event.edit(
                f"❌ نسخه‌ی `{name}` پیدا نشد.",
                buttons=[UI.go("↩️ بازگشت", "owner_rollback_list"), UI.nav_row()],
            )
            return

        # backup main.py فعلی
        try:
            ts = int(_time.time())
            backup_name = f"main.py.pre-rollback.{ts}"
            backup_path = versions_dir / backup_name
            versions_dir.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(main_py, backup_path)
        except Exception as e:
            await event.edit(
                f"❌ backup main.py قبل از rollback ناموفق: {e}",
                buttons=[UI.go("↩️ بازگشت", "owner_rollback_list"), UI.nav_row()],
            )
            return

        # اعتبارسنجی AST قبل از جایگزینی (M-21)
        try:
            import ast as _ast
            _ast.parse(src_path.read_text(encoding="utf-8"))
        except Exception as _ast_e:
            await event.edit(
                f"❌ فایل نسخه‌ی انتخابی معتبر نیست (خطای سینتکس AST): {_ast_e}",
                buttons=[UI.go("↩️ بازگشت", "owner_rollback_list"), UI.nav_row()],
            )
            return

        # جایگزینی
        try:
            _shutil.copy2(src_path, main_py)
            # v2.8.1: بعد از rollback موفق، flag «rolled_back» را در state ست کن
            # و .last_seen_commit را پاک کن تا آپدیتر بعد از restart بدونه
            # باید re-detect کنه (bug 3 fix).
            try:
                updater_mod, _ = self._import_updater_safe()
                if updater_mod is not None:
                    updater_mod.mark_rolled_back()
            except Exception as _re:
                print(f"⚠️ [rollback] mark_rolled_back failed: {_re}")
        except Exception as e:
            try:
                _shutil.copy2(backup_path, main_py)
            except Exception:
                pass
            await event.edit(
                f"❌ جایگزینی ناموفق: {e}\n\nmain.py به حالت قبل برگردانده شد.",
                buttons=[UI.go("↩️ بازگشت", "owner_rollback_list"), UI.nav_row()],
            )
            return

        # restart
        # v2.9.5: auto-detect service name (قبلاً hardcoded "cianet" بود)
        try:
            import subprocess as _sp
            _svc = os.environ.get("CIANET_SERVICE_NAME", "").strip()
            if not _svc:
                for _cand in ("cianet", "selfbot"):
                    try:
                        # BUG-19a: اجرا در thread — مثل سایر فراخوانی‌های
                        # systemctl (بدون block شدنِ event loop).
                        _r = await asyncio.to_thread(
                            _sp.run,
                            ["systemctl", "is-enabled", _cand],
                            capture_output=True, text=True, timeout=3,
                        )
                        if _r.returncode == 0:
                            _svc = _cand
                            break
                    except Exception:
                        continue
            if not _svc:
                _svc = "selfbot"  # fallback
            _sp.Popen(
                ["systemctl", "restart", _svc],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            )
            restart_msg = f"🔄 سرویس در حال restart ({_svc})..."
        except Exception as e:
            restart_msg = f"⚠️ restart ناموفق (دستی بزن): {e}"

        await event.edit(
            UI.screen("✅ Rollback انجام شد",
                      body=[
                          f"✅ main.py با `{name}` جایگزین شد.",
                          f"📦 backupِ نسخه‌ی قبلی: `{backup_name}`",
                          "",
                          restart_msg,
                          "",
                          f"{UI.GRAY} اگه بعد از restart مشکلی دیدی، باز از همین منو",
                          f"{UI.GRAY} rollback کن و `{backup_name}` را انتخاب کن.",
                      ],
                      subtitle="روی نسخه‌ی پشتیبان، دوباره rollback کن تا برگردی."),
            buttons=[UI.nav_row()],
        )

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
                # v2.14.2 (T10 residual / §17.3): جزئیات استثنا به کاربر نه —
                # پیام عمومی فارسی + لاگ کامل سمت سرور.
                print(f"❌ [dedicated_spawn] خطا در ساخت ربات اختصاصی: {type(e).__name__}: {e}")
                await self.client.send_message(
                    pay["user_id"],
                    "❌ ساخت ربات اختصاصی با خطا مواجه شد — با پشتیبانی تماس بگیرید.",
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
            # BUG-16b: قطعِ کلاینتِ موقت در finally — قبلاً اگر
            # wait_for(start) تایم‌اوت می‌شد یا get_me خطا می‌داد، temp
            # هرگز disconnect نمی‌شد و به‌ازای هر اعتبارسنجیِ ناموفق یک
            # connection نشت می‌کرد.
            try:
                await asyncio.wait_for(temp.start(bot_token=token), timeout=20)
                me = await temp.get_me()
            finally:
                try:
                    if temp.is_connected():
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
        # v2.12.29 (DEEP-5 DB-1): revoked terminal — no reactivation.
        if b["status"] == "revoked":
            await event.answer(
                "⛔ این ربات اختصاصی منقضی شده. برای فعال‌سازی دوباره "
                "باید تمدید کنید.", alert=True)
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
            # v2.12.31 (DEBUG-1 NEXT-DB-1): Gate on status. قبلاً هر
            # status غیر از 'active' و 'revoked' باعث spawn می‌شد، حتی
            # 'pending_payment' یا 'rejected'. حالا: فقط از 'stopped'
            # مجاز به reactivation. برای 'pending_payment' باید first
            # payment انجام بشه. برای 'rejected' یا 'deleted' هیچ action
            # ممکن نیست. برای expired_date گذشته، fresh 30-day window
            # ست می‌شه (DB-2).
            if b["status"] not in ("stopped",):
                _reason = {
                    "pending_payment": "این ربات هنوز پرداخت نشده — اول فاکتور رو پرداخت کن.",
                    "rejected": "این درخواست ربات اختصاصی رد شده — با پشتیبانی تماس بگیر.",
                    "deleted": "این ربات حذف شده و قابل بازگشت نیست.",
                }.get(b["status"], f"وضعیت فعلی ({b['status']}) اجازه‌ی reactivation نمی‌دهد.")
                await event.answer(_reason, alert=True)
                return
            # DB-2: اگر expire_date گذشته، fresh 30-day window ست کن
            _fresh_expire = b.get("expire_date")
            if _fresh_expire:
                try:
                    _exp_dt = _parse_date(_fresh_expire)
                    if _exp_dt < datetime.now(timezone.utc):
                        _fresh_expire = _format_date(
                            datetime.now(timezone.utc)
                            + timedelta(days=int(get_setting("dedicated_bot_days", "30")))
                        )
                        print(f"ℹ️ [dedicated_bot] bot#{bot_id} expired — fresh 30d window set.")
                except Exception:
                    _fresh_expire = _format_date(
                        datetime.now(timezone.utc)
                        + timedelta(days=int(get_setting("dedicated_bot_days", "30")))
                    )
            else:
                _fresh_expire = _format_date(
                    datetime.now(timezone.utc)
                    + timedelta(days=int(get_setting("dedicated_bot_days", "30")))
                )
            try:
                bot_dir = _spawn_dedicated_bot(bot_id, b["owner_id"], b["token"])
                pid = _read_pidfile(bot_dir)
                update_dedicated_bot_status(
                    bot_id, "active", bot_dir=bot_dir, pid=pid,
                    expire_date=_fresh_expire,
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
        # v2.13.1 (TEST-G5-DEDICATED / DED-7): revoke کردنِ ربات باید
        # مجوزِ CAP_ACCOUNT_SECURITY با scope=dedicated_bot/scope_id=bot_id
        # را هم پاک کند. این مجوز به ربات اجازه می‌داد ابزارهای امنیتیِ
        # اکانت‌ها را در scopeِ همین ربات استفاده کند. بعد از revoke، ربات
        # قطع شده و این مجوز دیگر کاربردی ندارد. بدون این cleanup، grant
        # در DB باقی می‌ماند و در فهرستِ مجوزهای OWNER (cap_list) همچنان
        # «فعّال» نشان داده می‌شود — گمراه‌کننده است و در صورت بازگشتی
        # نبودن ربات، گندِ داده است.
        try:
            _n_rev = revoke_capability(
                b["owner_id"], CAP_ACCOUNT_SECURITY,
                scope_type=SCOPE_DEDICATED_BOT, scope_id=str(bot_id),
                revoked_by=event.sender_id,
            )
            if _n_rev:
                log_action(event.sender_id, "capability_revoked",
                           f"from=bot#{bot_id} owner={b['owner_id']} "
                           f"scope=dedicated_bot rows={_n_rev} (on revoke)")
        except Exception as _e:
            print(f"⚠️ [dedicated_revoke_go] revoke_capability failed: {_e}")
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
        # v2.13.1 (TEST-G5-DEDICATED / DED-7): مانند revoke، حذفِ کامل هم
        # باید مجوزِ CAP_ACCOUNT_SECURITY با scope=dedicated_bot/scope_id=
        # bot_id را پاک کند. حتی بیشتر از revoke چون ربات دیگر هرگز
        # برنمی‌گردد (deleted ترمینال است) و grant باید قطع شود تا در
        # فهرستِ مجوزهای OWNER به‌عنوان «فعّال» نماند.
        try:
            _n_rev = revoke_capability(
                b["owner_id"], CAP_ACCOUNT_SECURITY,
                scope_type=SCOPE_DEDICATED_BOT, scope_id=str(bot_id),
                revoked_by=event.sender_id,
            )
            if _n_rev:
                log_action(event.sender_id, "capability_revoked",
                           f"from=bot#{bot_id} owner={b['owner_id']} "
                           f"scope=dedicated_bot rows={_n_rev} (on delete)")
        except Exception as _e:
            print(f"⚠️ [dedicated_delete_go] revoke_capability failed: {_e}")
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
        """
        📢 صفحهٔ کانال‌ها/گروه‌های اجباری (v2.22.0 چندچتی): فهرستِ همهٔ
        چت‌ها با دکمهٔ حذفِ هرکدام + افزودن + بررسیِ همه + حذفِ همه.
        """
        chats = get_required_chats()
        is_owner = self._role(event.sender_id) == ROLE_OWNER

        def _stat_int(v):
            try:
                return int(str(v))
            except (TypeError, ValueError):
                return 0

        blocked_n = _stat_int(get_setting("gate_blocked_count", "0"))
        rejoined_n = _stat_int(get_setting("gate_rejoined_count", "0"))
        if chats:
            body = [
                f"همه (به‌جز ادمین اصلی) برای استفاده از ربات باید عضوِ **همهٔ"
                f" {fa_digits(len(chats))} چتِ** زیر باشند:",
                "",
            ]
            buttons = []
            for i, ch in enumerate(chats):
                is_id = ch["u"].lstrip("-").isdigit()
                name = ch["t"] or (f"@{ch['u']}" if not is_id else ch["u"])
                kind = "گروهِ خصوصی" if (is_id or ch["l"]) else "کانال/گروه"
                body.append(f"{fa_digits(i + 1)}. {name} — {kind}"
                            + (f" (`{ch['u']}`)" if is_id else ""))
                if is_owner:
                    # v2.22.1: callback هویتِ چت را هم حمل می‌کند —
                    # channel_remove:{index}:{u} (رفع حذفِ اشتباه از صفحهٔ کهنه)
                    buttons.append([
                        UI.danger(f"🗑 حذف {fa_digits(i + 1)}",
                                  f"channel_remove:{i}:{ch['u']}"),
                    ])
            body += [
                "",
                f"📊 آمار گیت: {fa_digits(blocked_n)} بسته‌شدن | "
                f"{fa_digits(rejoined_n)} دوباره‌عضویت",
            ]
            buttons.append([UI.go("🔍 بررسی همه", b"owner_channel_check")])
            if is_owner:
                buttons.append([UI.go("➕ افزودن کانال/گروه", b"owner_channel_set")])
                buttons.append([UI.danger("🗑 حذف همه", "owner_channel_clear")])
            buttons.append(UI.nav_row())
        else:
            body = [
                "هیچ کانال/گروهی تنظیم نشده — همه بدون شرط می‌توانند از"
                " ربات استفاده کنند.",
            ]
            buttons = []
            if is_owner:
                buttons.append([UI.go("➕ افزودن کانال/گروه", b"owner_channel_set")])
            buttons.append(UI.nav_row())
        await self._show_page(
            event,
            UI.screen(f"📢 کانال‌های اجباری عضویت ({fa_digits(len(chats))})",
                      body=body,
                      subtitle="کانال و گروه — تا ۱۰ چت؛ عضویت در همه الزامی است.",
                      hint=("«➕ افزودن» یوزرنیم/لینک/آیدی عددی می‌پذیرد."
                            if is_owner else
                            "نمایندگیِ فقط-خواندنی — تغییرات فقط با مالک.")),
            buttons,
        )

    async def _owner_check_channel(self, event):
        """بررسی زندهٔ همهٔ چت‌های ذخیره‌شده با تلگرام — بدون تغییر چیزی.

        v2.22.1 (AUDIT-39/b#1 + e#2): ترمیمِ عنوان‌ها فقط با الگویِ
        read-merge-write ایمن انجام می‌شود — لیستِ تازه از DB خوانده و
        فقط عنوان‌هایِ ترمیم‌شده روی آن merge می‌شود تا افزودنِ هم‌زمانِ
        مالکِ دیگر (در پنجرهٔ چندثانیه‌ایِ resolveهایِ شبکه) گم نشود.
        ذخیره‌سازی فقط برای OWNER؛ ADMIN فقط گزارشِ خواندنی می‌بیند
        (قابلِ اعتماد بودنِ write-path، هم‌راستا با بقیهٔ تنظیماتِ گیت).
        """
        chats = get_required_chats()
        is_owner = self._role(event.sender_id) == ROLE_OWNER
        if not chats:
            buttons = []
            if is_owner:
                buttons.append([UI.go("➕ افزودن کانال/گروه", b"owner_channel_set")])
            await event.edit("📢 هیچ چتی تنظیم نشده — اول یکی اضافه کن.",
                             buttons=buttons)
            return
        await event.edit("🔄 در حال بررسی چت‌ها با تلگرام…")
        lines = ["نتیجهٔ بررسیِ چت‌ها:"]
        n_ok = 0
        healed_titles = {}
        for ch in chats:
            ok, info, norm, _ni = await self._resolve_channel(ch["u"])
            name = ch["t"] or ch["u"]
            if ok:
                n_ok += 1
                if info and info != ch["t"]:
                    healed_titles[ch["u"].lower()] = info
                    lines.append(f"{UI.GREEN} {name} — سالم"
                                 f" (عنوان تازه شد: {info})")
                else:
                    lines.append(f"{UI.GREEN} {name} — سالم")
            else:
                lines.append(f"{UI.RED} {name} — پیدا نشد ({info})")
        # v2.22.1: mergeِ ایمن — لیستِ تازه از DB + فقط عنوان‌ها؛ هیچ
        # تغییری که در فاصلهٔ resolveها روی لیست آمده گم نمی‌شود.
        if is_owner and healed_titles:
            try:
                fresh = get_required_chats()
                changed = False
                for f in fresh:
                    t = healed_titles.get(f["u"].lower())
                    if t and t != f["t"]:
                        f["t"] = t
                        changed = True
                if changed:
                    set_required_chats(fresh)
            except Exception:
                pass
        lines += [
            "",
            f"{fa_digits(n_ok)} از {fa_digits(len(chats))} چت سالم.",
        ]
        if n_ok < len(chats):
            lines.append(
                "⚠️ گیتِ عضویت fail-closed است — چتِ خراب را اصلاح یا حذف کن"
                " تا کاربران قفل نشوند (ادمین اصلی همیشه مستثنی است)."
            )
        buttons = []
        if is_owner:
            buttons.append([UI.go("➕ افزودن کانال/گروه", b"owner_channel_set")])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _start_channel_set(self, event):
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_SET_CHANNEL, {})
        await event.edit(
            "یوزرنیم یا لینک چت را بفرست (مثلاً `@MyChannel` یا `mychannel`"
            " یا لینک t.me) — یا برای **گروهِ خصوصی**، آیدیِ عددیِ گروه را"
            " بفرست (مثل `-1001234567890`):\n\n"
            "⚠️ چتِ عمومی باید قابلِ resolve باشد؛ برای گروهِ خصوصی، ربات"
            " باید عضوِ گروه باشد (لینکِ دعوت در گامِ بعد پرسیده می‌شود).",
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
        """💾 Backup — بکاپ کامل و معتبر پروژه را برای OWNER می‌فرستد.

        v1.9.2: استفاده از _panel_lock برای جلوگیری از race condition.
        قبلاً اگه کاربر دوبار روی دکمه می‌زد (یا تأخیر شبکه)، دو بکاپ
        هم‌زمان ساخته می‌شد و ممکن بود فایل‌های ZIP خراب شوند یا send_file
        دو بار صدا زده بشه.
        """
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("فقط OWNER به Backup دسترسی دارد.", alert=True)
            return
        if self._panel_lock.locked():
            await event.answer("⏳ یک عملیات پنل در حال اجراست؛ کمی صبر کن.", alert=True)
            return
        async with self._panel_lock:
            await self._owner_show_backup_locked(event)

    async def _owner_show_backup_locked(self, event):
        """بدنه‌ی واقعی _owner_show_backup زیر _panel_lock."""
        await event.answer("⏳ در حال ساخت Backup...")

        # فیکس مهم v1.7.0: قبل از بکاپ، مطمئن می‌شیم که DB schema آماده‌ست.
        # اگه main.py به‌تازگی آپدیت شده باشه و init_db هنوز اجرا نشده باشه،
        # validate_backup_zip شکست می‌خوره. اینجا init_db رو فراخوانی می‌کنیم
        # تا DB آماده باشه.
        try:
            await asyncio.to_thread(init_db)
        except Exception as e:
            print(f"⚠️ [backup] init_db در حین بکاپ خطا داد: {e}")

        _fd_bkp, backup_path = tempfile.mkstemp(prefix="cianet_bkp_", suffix=".zip")
        os.close(_fd_bkp)
        # v2.13.0 (DEBUG-2-BACKUP-SEC): رمزگذاری فایل بکاپ با Fernet.
        # رمز در پیامِ جداگانه به Saved Messages ("me") ارسال می‌شود، نه
        # در همان چتی که فایل می‌رود — تا اگه فایل بکاپ به سرورِ تلگرام
        # نشت کنه یا فوروارد بشه، بدون پیامِ رمز غیرقابل‌بازیابی باشد.
        # secrets قبلاً در line 31 import شده.
        backup_password = secrets.token_urlsafe(16)
        try:
            # v1.9.3: timeout ۶۰ ثانیه. اگه session قفل باشه، sqlite.backup()
            # بی‌نهایت hang می‌کرد. callback تلگرام بعد از ۳۰ ثانیه بسته
            # می‌شد و کاربر فکر می‌کرد بکاپ نرفت.
            ok = await asyncio.wait_for(
                asyncio.to_thread(build_backup_zip, backup_path, backup_password),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            print(f"⚠️ [backup] build_backup_zip بیش از ۶۰ ثانیه طول کشید — احتمالاً Session قفل است")
            ok = False
        except Exception as e:
            print(f"⚠️ [backup] build_backup_zip exception: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            ok = False
        if not ok:
            # v1.9.3: پیام دقیق‌تر + پیشنهاد حل مشکل قفل سشن.
            # قبلاً همیشه یه پیام عمومی می‌فرستاد. حالا اگه Runtime سشن‌ها
            # فعال باشن، راهنمای توقف اکانت‌ها رو می‌ده.
            active = self._active_runtime_tags_safe() if hasattr(self, "_active_runtime_tags_safe") else []
            msg = (
                "❌ ساخت Backup ناموفق بود — فایل ناقصی ساخته نشد.\n\n"
                "💡 علت احتمالی: سشن یا دیتابیس قفل شده.\n"
            )
            if active:
                tags_short = ", ".join(active[:5])
                if len(active) > 5:
                    tags_short += f" و {len(active)-5} اکانت دیگر"
                msg += (
                    f"⚠️ {len(active)} اکانت الان روشن و Session قفل است: {tags_short}\n\n"
                    "۱. اکانت‌ها را از پنل «مدیریت اکانت‌ها» خاموش کن.\n"
                    "۲. یا ربات را ری‌استارت کن:\n"
                    "`sudo systemctl restart selfbot`\n"
                    "۳. بعد دوباره بکاپ بزن."
                )
            else:
                msg += (
                    "یک‌بار ربات را ری‌استارت کنید:\n"
                    "`sudo systemctl restart selfbot`"
                )
            try:
                await self.client.send_message(event.chat_id, msg)
                print(f"✅ [backup] پیام خطای مفصل به کاربر ارسال شد")
            except Exception as ee:
                print(f"⚠️ [backup] حتی پیام خطا هم ارسال نشد: {ee}")
            return
        print(f"✅ [backup] ساخته شد: {backup_path} ({os.path.getsize(backup_path):,} bytes) — رمزگذاری‌شده با Fernet")
        # TEST-G6-SYSTEM (BUG: CRITICAL — admin client uses bot_token, so
        # `self.client.send_message("me", ...)` raises an exception
        # because Telegram bots have no "Saved Messages" / cannot
        # message themselves. The previous code silently swallowed the
        # exception, leaving password_sent=False but still telling the
        # OWNER "رمز در Saved Messages ارسال شده است" — a lie. The
        # encrypted backup was then delivered but unrecoverable. Now:
        # try "me" first (works only in userbot mode), then fall back to
        # event.chat_id (OWNER's chat with the bot) so the OWNER actually
        # receives the password. The caption / success message report
        # the *real* delivery target.)
        password_sent = False
        password_target = ""
        _pw_body = (
            f"🔐 رمز بکاپ CiaNet — {_now()}\n\n"
            f"```\n{backup_password}\n```\n\n"
            f"این رمز فقط برای بکاپی که الان در چتِ بات دریافت می‌کنی "
            f"استفاده می‌شود. در جای امن نگه دار.\n\n"
            # v2.23.1 (AUDIT-43 #4): قبلاً اینجا یک اسنیپتِ پایتونی برای
            # دیکریپتِ دستی داده می‌شد که (۱) کلیدش با فرمتِ واقعیِ CNB1
            # (PBKDF2 + salt) هم‌خوان نبود و (۲) از اونرِ یک رباتِ تلگرامی
            # انتظارِ اجرای پایتون روی سرور را داشت. حالا Restore خودش
            # رمز را می‌پرسد — همان فایلِ رمزگذاری‌شده را بفرست.
            f"برای Restore: همین فایل را به ربات بفرست؛ وقتی رمز خواست، "
            f"همین رمز را به‌صورت پیام بفرست."
        )
        try:
            await asyncio.wait_for(
                self.client.send_message("me", _pw_body),
                timeout=30.0,
            )
            password_sent = True
            password_target = "Saved Messages"
            print(f"✅ [backup] رمز بکاپ به Saved Messages ارسال شد")
        except Exception as e:
            print(f"⚠️ [backup] ارسال رمز به Saved Messages ناموفق بود (حذف fallback ارسال در همان چت طبق M-12): {type(e).__name__}")
        # v1.9.2: کل فرآیند send_file و send_message زیر یه try/except مستقل
        # و با لاگ کامل. قبلاً اگه send_file فیل می‌شد، حتی پیام خطا هم
        # به کاربر نمی‌رسید (silent fail). حالا هر خطا با traceback کامل
        # لاگ می‌شه + حداقل یه پیام کوتاه به کاربر می‌رسه.
        send_error = None
        file_sent = False
        file_size = os.path.getsize(backup_path)
        print(f"📤 [backup] در حال ارسال فایل {file_size:,} bytes به {event.chat_id}...")
        try:
            # v1.9.2: timeout ۵ دقیقه برای فایل‌های بزرگ. اگه network کند باشه
            # یا session فایل‌ها چند ده MB باشن، upload زمان می‌بره.
            # TEST-G6-SYSTEM: caption به‌روز می‌شه تا مقصدِ واقعیِ رمز رو
            # بگه — نه یک lieِ سخت‌کد‌شده «Saved Messages». اگه هر دو send
            # ناموفق بوده، OWNER را آگاه کن که فایل بدون رمز غیرقابل‌بازیابی است.
            if password_sent:
                _pw_caption_line = f"رمز در {password_target} ارسال شده است.\n"
            else:
                _pw_caption_line = (
                    "⚠️ ارسال رمز ناموفق بود — این فایل بدون رمز غیرقابل‌بازیابی است. "
                    "دوباره بکاپ بزن.\n"
                )
            enc_caption = (
                f"💾 بکاپ کامل (Backup) — {_now()}\n"
                f"🔐 این فایل با Fernet (AES-128-CBC + HMAC-SHA256) رمزگذاری شده.\n"
                + _pw_caption_line +
                f"برای Restore، اول فایل را با رمز دیکریپت کن، سپس ZIP را بفرست."
            )
            await asyncio.wait_for(
                self.client.send_file(
                    event.chat_id, backup_path,
                    caption=enc_caption,
                    force_document=True,
                ),
                timeout=300,  # ۵ دقیقه
            )
            file_sent = True
            print(f"✅ [backup] فایل به {event.chat_id} ارسال شد")
        except asyncio.TimeoutError:
            send_error = "ارسال فایل بیش از ۵ دقیقه طول کشید (Timeout)"
            print(f"⚠️ [backup] send_file Timeout: {send_error}")
        except Exception as e:
            send_error = f"{type(e).__name__}: {e}"
            print(f"⚠️ [backup] send_file فیل شد: {send_error}")
            import traceback
            traceback.print_exc()
        if file_sent:
            # پیام تأیید - اختیاری، اگه فیل شد مهم نیست
            # TEST-G6-SYSTEM: پیام به مقصدِ واقعی اشاره می‌کند، نه lie.
            try:
                if password_sent:
                    _confirm_msg = (
                        "✅ Backup ساخته و ارسال شد.\n\n"
                        f"🔐 فایل با Fernet رمزگذاری شده؛ رمز در {password_target} ارسال شده است.\n"
                        "برای بازیابی: فایل را با رمز دیکریپت کن و ZIP خروجی را بفرست،"
                        " سپس «♻️ Restore» را بزن."
                    )
                else:
                    _confirm_msg = (
                        "✅ Backup ساخته و ارسال شد.\n\n"
                        "⚠️ ولی ارسال رمز ناموفق بود — این فایل بدون رمز غیرقابل‌بازیابی است.\n"
                        "برای بکاپ قابل‌بازیابی، دوباره بکاپ بزن."
                    )
                await self.client.send_message(event.chat_id, _confirm_msg)
            except Exception as e:
                print(f"⚠️ [backup] پیام تأیید فیل شد (اما فایل ارسال شده): {e}")
        elif send_error:
            # send_file فیل شده - حتماً پیام خطا بفرست
            # v2.13.0 (DEBUG-2-BACKUP-SEC): اگه فایل فیل شده ولی رمز در
            # Saved Messages ارسال شده، OWNER را آگاه کن که آن رمز بدون فایل
            # بی‌فایده است و باید دوباره بکاپ بزند.
            err_extra = ""
            # TEST-G6-SYSTEM: مقصدِ واقعیِ رمز رو در warning ذکر کن.
            if password_sent:
                err_extra = f"\n\n⚠️ توجه: رمز بکاپ در {password_target} ارسال شده ولی فایل ارسال نشد. آن رمز دیگر بی‌فایده است — دوباره بکاپ بزن."
            try:
                await self.client.send_message(
                    event.chat_id,
                    f"❌ ارسال Backup ناموفق:\n{send_error[:300]}{err_extra}"
                )
                print(f"✅ [backup] پیام خطا به کاربر ارسال شد")
            except Exception as ee:
                print(f"⚠️ [backup] حتی پیام خطا هم به کاربر نرسید: {ee}")
        # پاک کردن فایل موقت - حتی اگه ارسال نشد
        try:
            os.remove(backup_path)
        except Exception as e:
            print(f"⚠️ [backup] حذف فایل موقت فیل شد: {e}")

    async def _owner_manage_roles_menu(self, event):
        """
        TEST-G6-SYSTEM: callback قدیمی `owner_manage_roles` — این یک
        **legacy redirect** است (نه silent no-op مثلِ ادعای extractor).
        به هاب «🎫 لایسنس و دسترسی‌ها» می‌رود که از آنجا می‌توان لایسنس ساخت
        و نقش‌های ADMIN/RESELLER را لیست/حذف کرد. منطقِ مدیریتیِ واقعی در
        `_owner_show_license_hub` و `_owner_show_role_list` است.
        """
        await self._owner_show_license_hub(event)

    # v2.8.12: کدهای تخفیف
    async def _owner_show_discount_codes(self, event):
        """🎟 کدهای تخفیف — لیست + ساخت + حذف."""
        if self._role(event.sender_id) not in (ROLE_OWNER, ROLE_ADMIN):
            await event.answer("⛔ فقط OWNER/ADMIN", alert=True)
            return
        codes = list_discount_codes(limit=20)
        body = []
        buttons = []
        if not codes:
            body.append(f"{UI.GRAY} هنوز هیچ کد تخفیفی ساخته نشده.")
        else:
            body.append(f"📦 {fa_digits(len(codes))} کد تخفیف:")
            body.append("")
            for c in codes:
                used = c["used_count"]
                mx = c["max_uses"]
                act = "🟢" if c["is_active"] else "⚫"
                body.append(f"{act} `{c['code']}` — {fa_digits(c['percent'])}% · {fa_digits(used)}/{fa_digits(mx)}")
                # TEST-G4-PAYMENT (BUG: discount_toggle: missing — هر کد
                # فقط یک خطِ read-only بود و هیچ دکمه‌ای برای فعال/غیرفعال
                # کردنش وجود نداشت. حالا یک دکمه‌ی toggle برای هر کد اضافه
                # شده؛ برچسب: «🔴 غیرفعال» وقتی فعال است (کلیک = غیرفعال)،
                # «🟢 فعال» وقتی غیرفعال (کلیک = فعال).
                if c["is_active"]:
                    toggle_btn = UI.danger(
                        f"🔴 غیرفعال {c['code']}",
                        f"discount_toggle:{c['code']}".encode(),
                    )
                else:
                    toggle_btn = UI.go(
                        f"🟢 فعال {c['code']}",
                        f"discount_toggle:{c['code']}".encode(),
                        tone="success",
                    )
                buttons.append([toggle_btn])
        buttons.append([UI.go("➕ ساخت کد تخفیف", b"owner_discount_create", tone="success")])
        buttons.append(UI.nav_row())
        await event.edit(
            UI.screen("🎟 کدهای تخفیف", body=body,
                      subtitle="کدهای تخفیف برای کاربران هنگام خرید اشتراک."),
            buttons=buttons,
        )

    async def _owner_show_payment_gateways(self, event):
        """v2.10.2: درگاه‌های پرداخت — فعال/غیرفعال."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return
        zarinpal_on = get_setting("pay_zarinpal_enabled", "0") == "1"
        zibal_on = get_setting("pay_zibal_enabled", "0") == "1"
        card_on = get_setting("pay_card_enabled", "1") == "1"
        trc20_on = get_setting("pay_trc20_enabled", "1") == "1"
        zarinpal_m = (get_setting("zarinpal_merchant") or "").strip()
        zibal_m = (get_setting("zibal_merchant") or "").strip()
        body = [
            "💳 **درگاه‌های پرداخت**\n",
            f"🟡 زرین‌پال: {'✅ فعال' if zarinpal_on else '❌ غیرفعال'}" + (f" — مرچنت: `{zarinpal_m[:8]}...`" if zarinpal_m else " — مرچنت ست نشده"),
            f"🟢 زیبال: {'✅ فعال' if zibal_on else '❌ غیرفعال'}" + (f" — مرچنت: `{zibal_m[:8]}...`" if zibal_m else " — مرچنت ست نشده"),
            f"💳 کارت به کارت: {'✅ فعال' if card_on else '❌ غیرفعال'}",
            f"💵 تتر TRC20: {'✅ فعال' if trc20_on else '❌ غیرفعال'}",
            f"💰 کیف پول: ✅ همیشه فعال",
        ]
        buttons = [
            # TEST-G4-PAYMENT (BUG: WRONG_MESSAGE — button labels were
            # inverted relative to the rest of the codebase (🟢 = active
            # elsewhere, e.g. line 13431 «🟢 آپدیت خودکار: فعال»)، به‌جای
            # نشان دادنِ «وضعیت فعلی» دکمه «اکشنِ بعدی» رو نشون می‌داد.
            # حالا برچسب = وضعیت فعلی، مطابق با بقیه‌ی پنل.
            [UI.go(("🟢 " if zarinpal_on else "🔴 ") + "زرین‌پال", b"toggle_pay:zarinpal")],
            [UI.go(("🟢 " if zibal_on else "🔴 ") + "زیبال", b"toggle_pay:zibal")],
            [UI.go(("🟢 " if card_on else "🔴 ") + "کارت به کارت", b"toggle_pay:card")],
            [UI.go(("🟢 " if trc20_on else "🔴 ") + "تتر TRC20", b"toggle_pay:trc20")],
            [UI.go("🔑 مرچنت زرین‌پال", b"set_merchant:zarinpal")],
            [UI.go("🔑 مرچنت زیبال", b"set_merchant:zibal")],
            UI.nav_row(),
        ]
        await event.edit(
            UI.screen("💳 درگاه‌های پرداخت", body=body,
                      subtitle="فعال/غیرفعال‌کردن درگاه‌ها."),
            buttons=buttons,
        )

    async def _owner_show_license_hub(self, event):
        """🎫 لایسنس و دسترسی‌ها — ساخت لایسنس + مدیریت نقش‌ها."""
        lines = ["🎫 **لایسنس و دسترسی‌ها**\n\nاز اینجا لایسنس بساز و نقش‌ها را مدیریت کن:"]
        items = [
            UI.go("➕ ساخت لایسنس", b"owner_create_license", tone="success"),
            UI.go("📦 ساخت گروهی", b"owner_create_license_batch", tone="success"),
            UI.go("📋 لایسنس‌های ساخته‌شده", b"license_access_list", tone="success"),
        ]
        if self._role(event.sender_id) == ROLE_OWNER:
            items.extend([
                UI.go("👑 ادمین‌های فعال", b"license_access_admins"),
                # TEST-G7-RESELLER: «نماینده‌ها + درخواست‌ها» جایگزینِ دکمه‌ی
                # قدیمی شد. این دکمه به owner_resellers می‌رود که RESELLERهای
                # فعال + شمارشِ درخواست‌های pending + دکمه‌ی لیستِ درخواست‌ها
                # را نشان می‌دهد. دکمه‌ی قدیمی license_access_resellers به‌عنوان
                # مسیرِ fallback در callback_h باقی مانده.
                UI.go("🤝 نماینده‌ها + درخواست‌ها", b"owner_resellers"),
            ])
        buttons = self._pair_buttons(items)
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    # ───────────────────────────────────────────────────────────────────
    #  TEST-G6-SYSTEM: Announcements (owner_announce / announce_send:)
    # ───────────────────────────────────────────────────────────────────
    #  BUG: این دو callback در spec گفته شده بود ولی کاملاً غایب بودند —
    #  هیچ dispatcher و handlerای برای‌شان وجود نداشت (silent no-op). حالا
    #  یک پیاده‌سازیِ ساده‌ی broadcast به همه‌ی کاربران (که ربات را start
    #  کرده‌اند) اضافه می‌شود. flow:
    #    ۱) OWNER روی `owner_announce` می‌زند → wizard باز می‌شه، متن می‌خواد.
    #    ۲) OWNER متن را می‌فرسته → wizard متن را ذخیره می‌کنه، preview +
    #       دکمه‌ی «ارسال» نشون می‌ده.
    #    ۳) OWNER روی `announce_send:` می‌زند → broadcast واقعی به همه‌ی
    #       user_id های جدولِ users. گزارش success/fail بعد از اتمام.
    # v2.15.0: Announce — بدون wizard، ساده و قابل اعتماد
    # flow:
    #   ۱) OWNER روی owner_announce می‌زند → _announce_pending ست می‌شه
    #   ۲) OWNER متن را می‌فرسته → message_h متن را در _announce_text ذخیره + preview
    #   ۳) OWNER روی announce_send: می‌زند → broadcast واقعی
    async def _owner_start_announce(self, event):
        """📨 OWNER می‌خواهد پیامی به همه‌ی کاربران بفرستد."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return
        # پاک‌سازی wizard قبلی (اگه هست)
        self._announce_pending.discard(event.sender_id)
        self._announce_text.pop(event.sender_id, None)
        # ست کردن pending
        self._announce_pending.add(event.sender_id)
        from telethon import Button
        await event.respond(
            "**📨 ارسال پیام همگانی**\n\n"
            "متن پیام رو بفرست (همان چیزی که همه‌ی کاربران باید ببینند).\n\n"
            "⚠️ فقط کاربرانی که ربات را start کرده‌اند پیام را دریافت می‌کنند.\n"
            "⚠️ بین هر پیام ۵۰ms تأخیر است.",
            buttons=[[Button.inline("انصراف", b"announce_cancel")]],
        )

    async def _owner_announce_send(self, event):
        """✅ اجرای broadcast واقعی به همه‌ی کاربران."""
        if self._role(event.sender_id) != ROLE_OWNER:
            await event.answer("⛔ فقط OWNER", alert=True)
            return
        text = self._announce_text.get(event.sender_id)
        if not text:
            await event.answer("هیچ پیامی در انتظار ارسال نیست.", alert=True)
            return
        self._announce_text.pop(event.sender_id, None)
        self._announce_pending.discard(event.sender_id)
        try:
            await event.answer("📤 در حال ارسال...")
        except Exception:
            pass
        users = list_all_users()
        sent_ok = 0
        failed = 0
        for u in users:
            try:
                uid = int(u["user_id"])
            except (TypeError, ValueError):
                continue
            try:
                await self.client.send_message(uid, text)
                sent_ok += 1
            except errors.FloodWaitError as e:
                await asyncio.sleep(e.seconds + 2)
                failed += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
        await event.edit(
            UI.screen(
                "✅ ارسال همگانی انجام شد",
                body=[
                    f"📊 موفق: {fa_digits(sent_ok)}",
                    f"⚠️ ناموفق: {fa_digits(failed)}",
                    f"📦 کل کاربران: {fa_digits(len(users))}",
                    "",
                    f"{UI.GRAY} ناموفق‌ها = کاربرانی که ربات را start نکرده‌اند یا بلاک کرده‌اند.",
                ],
            ),
            buttons=[UI.nav_row()],
        )

    async def _owner_show_role_list(self, event, role: str):
        entries = [e for e in list_admins_and_resellers() if e["role"] == role]
        label = ("👑 **ادمین‌های فعال:**" if role == ROLE_ADMIN
                 else "🤝 **نماینده‌های فعال:**")
        # TEST-G7-RESELLER (BUG: owner_resellers فقط RESELLERهای فعال را
        # نشان می‌داد؛ نه درخواست‌های pending را. حالا برای role==RESELLER
        # شمارشِ pending را هم نشان می‌دهیم + دکمه‌ی مشاهده‌ی درخواست‌ها).
        pending_count = 0
        if role == ROLE_RESELLER:
            try:
                pending_count = len(list_pending_reseller_applications())
            except Exception:
                pending_count = 0
        if not entries and pending_count == 0:
            await event.edit(
                label + "\n\n(هیچ موردی ثبت نشده.)",
                buttons=[UI.nav_row()],
            )
            return
        lines = [label + "\n"]
        if pending_count:
            lines.append(f"📥 درخواست‌های در انتظار: {fa_digits(pending_count)}")
        lines.append("")
        buttons = []
        # TEST-G7-RESELLER: دکمه‌ی «درخواست‌های در انتظار» (اگه هست).
        if pending_count:
            buttons.append([UI.go(
                f"🔍 درخواست‌های در انتظار ({fa_digits(pending_count)})",
                "reseller_applications", tone="success",
            )])
        for e in entries:
            extra = f" — 👥 سقف: {e['reseller_max_users']} مشتری" if e.get("reseller_max_users") else ""
            cust_count = ""
            if role == ROLE_RESELLER:
                try:
                    cust_count = f" — 👥 {fa_digits(reseller_user_count(e['user_id']))} مشتری"
                except Exception:
                    cust_count = ""
            lines.append(f"👤 `{e['user_id']}` — 🛡 {e['role']}{extra}{cust_count} — 🕐 {e['created_at']}")
            # TEST-G7-RESELLER: هر RESELLER یک دکمه‌ی «👥 مشتریان» دارد
            # که به reseller_customers:{uid} می‌رود — قبلاً فقط «حذف
            # دسترسی» بود و OWNER نمی‌توانست مشتریانِ یک نماینده را ببیند.
            if role == ROLE_RESELLER:
                buttons.append([
                    UI.go(f"👥 مشتریان {e['user_id']}",
                          f"reseller_customers:{e['user_id']}"),
                    UI.danger(f"حذف {e['user_id']}",
                              f"role_del:{e['user_id']}"),
                ])
            else:
                buttons.append([UI.danger(f"حذف دسترسی {e['user_id']}", f"role_del:{e['user_id']}")])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    # ════════════════════════════════════════════════════════════════
    #  مدیریتِ درخواست‌های نمایندگی — فقط مالکِ اصلی — TEST-G7-RESELLER
    # ════════════════════════════════════════════════════════════════
    #  BUG (extractor): reseller_applications INSERT-only بود — هیچ UPDATE‌ای
    #  وجود نداشت، پس OWNER هرگز نمی‌توانست درخواستی را تأیید/رد کند و
    #  کاربر برای همیشه «pending» می‌ماند. حالا _update_reseller_application
    #  پیاده‌سازی شده و این هندلرها آن را فرا می‌خوانند.

    async def _owner_show_reseller_applications(self, event):
        """TEST-G7-RESELLER: لیست همه‌ی درخواست‌های pending نمایندگی."""
        try:
            await event.answer()
        except Exception:
            pass
        if self._role(event.sender_id) != ROLE_OWNER:
            try:
                await event.answer("⛔ فقط OWNER", alert=True)
            except Exception:
                pass
            return
        try:
            apps = list_pending_reseller_applications()
        except Exception as e:
            print(f"⚠️ [TEST-G7-RESELLER] list_pending_reseller_applications: {e}")
            apps = []
        body = ["📥 **درخواست‌های نمایندگی در انتظار**\n"]
        if not apps:
            body.append(f"{UI.GRAY} هیچ درخواستِ pending‌ای ثبت نشده.")
        else:
            body.append(f"📊 تعداد: {fa_digits(len(apps))}\n")
            for a in apps:
                uid = a["user_id"]
                name = (a.get("first_name") or "").strip()
                uname = f"@{a['username']}" if a.get("username") else ""
                body.append(f"👤 {name} {uname} — `{uid}`")
                body.append(f"   🕐 {a['created_at']}")
        buttons = []
        for a in apps[:30]:
            uid = a["user_id"]
            name = (a.get("first_name") or "").strip() or str(uid)
            buttons.append([UI.go(
                f"👤 {name} — {uid}",
                f"reseller_application:{uid}",
            )])
        if len(apps) > 30:
            body.append(f"\n{UI.GRAY} … و {fa_digits(len(apps) - 30)} درخواست دیگر")
        buttons.append([UI.go("🔄 بازخوانی", "reseller_applications")])
        buttons.append(UI.nav_row())
        text = UI.screen("🤝 درخواست‌های نمایندگی", body=body,
                         subtitle="تأیید/رد درخواست‌های نمایندگی")
        await event.edit(text, buttons=buttons)

    async def _owner_show_reseller_application(self, event, applicant_uid: int):
        """TEST-G7-RESELLER: نمایش یک درخواست + دکمه‌های تأیید/رد."""
        try:
            await event.answer()
        except Exception:
            pass
        if self._role(event.sender_id) != ROLE_OWNER:
            try:
                await event.answer("⛔ فقط OWNER", alert=True)
            except Exception:
                pass
            return
        if not applicant_uid:
            try:
                await event.answer("❌ آیدی کاربر نامعتبر است.", alert=True)
            except Exception:
                pass
            return
        app = get_reseller_application(applicant_uid)
        if not app:
            await event.edit(
                f"❌ هیچ درخواستی از `{applicant_uid}` پیدا نشد.",
                buttons=[UI.go("🔙 بازگشت", "reseller_applications"), UI.nav_row()],
            )
            return
        u = get_user(applicant_uid) or {}
        name = (u.get("first_name") or app.get("first_name") or "").strip()
        uname = f"@{u['username']}" if u.get("username") else (
            f"@{app['username']}" if app.get("username") else ""
        )
        # بررسی اینکه آیا از قبل RESELLER است (مانع تأیید مجدد).
        cur_role = self._role(applicant_uid)
        already_reseller = cur_role == ROLE_RESELLER
        body = [
            "📥 **درخواست نمایندگی**\n",
            f"👤 نام: {name or '—'}",
            f"👤 یوزرنیم: {uname or '—'}",
            f"🆔 آیدی: `{applicant_uid}`",
            f"🕐 ثبت: {app['created_at']}",
            f"📌 وضعیت: {app['status']}",
        ]
        if app.get("reviewed_at"):
            body.append(f"✅ بررسی‌شده: {app['reviewed_at']}")
            body.append(f"👤 بررسی‌کننده: `{app.get('reviewed_by') or '—'}`")
        if already_reseller:
            body.append("")
            body.append(f"{UI.AMBER} ⚠️ این کاربر در حال حاضر RESELLER فعال است.")
        body.append("")
        if already_reseller:
            body.append("با تأیید مجدد، فقط وضعیت درخواست به «approved» تغییر "
                        "می‌کند (نقش کاربر تکراری نمی‌شود).")
        else:
            body.append("با تأیید، این کاربر RESELLER می‌شود (سقفِ پیش‌فرض: ۵۰ "
                        "مشتری — بعداً قابل تغییر).")
        buttons = []
        if app["status"] == "pending":
            buttons.append([
                UI.go("✅ تأیید", f"reseller_approve:{applicant_uid}",
                      tone="success"),
                UI.danger("❌ رد", f"reseller_reject:{applicant_uid}"),
            ])
        else:
            buttons.append([UI.item(
                f"وضعیت نهایی: {app['status']}", "active", NAV_NOOP,
            )])
        buttons.append([UI.go("🔙 بازگشت به درخواست‌ها", "reseller_applications")])
        buttons.append(UI.nav_row())
        text = UI.screen("📥 درخواست نمایندگی", body=body,
                         subtitle=f"کاربر {applicant_uid}")
        await event.edit(text, buttons=buttons)

    async def _owner_approve_reseller_application(self, event, applicant_uid: int):
        """TEST-G7-RESELLER: تأیید درخواست — INSERT/UPSERT به admins +
        UPDATE روی reseller_applications + اطلاع به کاربر."""
        try:
            await event.answer()
        except Exception:
            pass
        if self._role(event.sender_id) != ROLE_OWNER:
            try:
                await event.answer("⛔ فقط OWNER", alert=True)
            except Exception:
                pass
            return
        if not applicant_uid:
            try:
                await event.answer("❌ آیدی کاربر نامعتبر است.", alert=True)
            except Exception:
                pass
            return
        app = get_reseller_application(applicant_uid)
        if not app:
            try:
                await event.answer("❌ درخواستی برای این کاربر پیدا نشد.", alert=True)
            except Exception:
                pass
            return
        if app["status"] != "pending":
            try:
                await event.answer(
                    f"⚠️ این درخواست قبلاً {app['status']} شده.",
                    alert=True,
                )
            except Exception:
                pass
            return
        # اگه کاربر از قبل RESELLER نیست، او را اضافه کن.
        cur_role = self._role(applicant_uid)
        if cur_role != ROLE_RESELLER:
            try:
                # سقفِ پیش‌فرض: ۵۰ مشتری. OWNER می‌تواند بعداً با حذف و
                # افزودنِ مجدد، عددِ دیگری را set کند.
                add_admin_or_reseller(
                    applicant_uid, ROLE_RESELLER,
                    added_by=event.sender_id,
                    reseller_max_users=50,
                )
            except Exception as e:
                print(f"⚠️ [TEST-G7-RESELLER] add_admin_or_reseller failed: {e}")
                try:
                    await event.answer(
                        "❌ خطا در افزودن نقش — دوباره تلاش کن.", alert=True,
                    )
                except Exception:
                    pass
                return
        # UPDATE درخواست به 'approved'.
        try:
            ok = _update_reseller_application(
                applicant_uid, "approved", decided_by=event.sender_id,
            )
        except Exception as e:
            print(f"⚠️ [TEST-G7-RESELLER] _update_reseller_application failed: {e}")
            ok = False
        log_action(event.sender_id, "reseller_approve",
                   f"applicant={applicant_uid}, update_ok={ok}")
        # اطلاع به کاربر.
        try:
            await self.client.send_message(
                applicant_uid,
                "✅ **تبریک! درخواست نمایندگی‌ات تأیید شد.**\n\n"
                "حالا یک نماینده‌ی فعال هستی. از «🎛 پنل مدیریت / ادمین» "
                "می‌تونی لایسنس بسازی و مشتری جمع کنی.",
            )
        except Exception:
            pass  # کاربر ممکنه ربات را block کرده باشد.
        await event.edit(
            f"✅ درخواستِ `{applicant_uid}` تأیید شد و نقش RESELLER به او داده شد.",
            buttons=[
                [UI.go("🔙 بازگشت به درخواست‌ها", "reseller_applications")],
                [UI.go("🤝 لیست نماینده‌ها", "owner_resellers")],
                UI.nav_row(),
            ],
        )

    async def _owner_reject_reseller_application(self, event, applicant_uid: int):
        """TEST-G7-RESELLER: رد درخواست — UPDATE روی reseller_applications
        + اطلاع به کاربر. نقشی تغییر نمی‌کند."""
        try:
            await event.answer()
        except Exception:
            pass
        if self._role(event.sender_id) != ROLE_OWNER:
            try:
                await event.answer("⛔ فقط OWNER", alert=True)
            except Exception:
                pass
            return
        if not applicant_uid:
            try:
                await event.answer("❌ آیدی کاربر نامعتبر است.", alert=True)
            except Exception:
                pass
            return
        app = get_reseller_application(applicant_uid)
        if not app:
            try:
                await event.answer("❌ درخواستی برای این کاربر پیدا نشد.", alert=True)
            except Exception:
                pass
            return
        if app["status"] != "pending":
            try:
                await event.answer(
                    f"⚠️ این درخواست قبلاً {app['status']} شده.",
                    alert=True,
                )
            except Exception:
                pass
            return
        try:
            ok = _update_reseller_application(
                applicant_uid, "rejected", decided_by=event.sender_id,
            )
        except Exception as e:
            print(f"⚠️ [TEST-G7-RESELLER] _update_reseller_application failed: {e}")
            ok = False
        log_action(event.sender_id, "reseller_reject",
                   f"applicant={applicant_uid}, update_ok={ok}")
        # اطلاع به کاربر.
        try:
            await self.client.send_message(
                applicant_uid,
                "❌ **درخواست نمایندگی‌ات رد شد.**\n\n"
                "متأسفیم — در این زمان نمی‌توانیم این درخواست را بپذیریم. "
                "اگر فکر می‌کنی اشتباهی رخ داده، با پشتیبانی تماس بگیر.",
            )
        except Exception:
            pass
        await event.edit(
            f"❌ درخواستِ `{applicant_uid}` رد شد و به او اطلاع داده شد.",
            buttons=[
                [UI.go("🔙 بازگشت به درخواست‌ها", "reseller_applications")],
                UI.nav_row(),
            ],
        )

    async def _owner_show_reseller_customers(self, event, reseller_uid: int):
        """TEST-G7-RESELLER: لیست کاربرانی که reseller_id = X.
        قبلاً هیچ راهی برای OWNER وجود نداشت تا مشتریانِ یک نماینده
        مشخص را ببیند — فقط RESELLERِ خودش می‌توانست مشتریانش را ببیند."""
        try:
            await event.answer()
        except Exception:
            pass
        if self._role(event.sender_id) != ROLE_OWNER:
            try:
                await event.answer("⛔ فقط OWNER", alert=True)
            except Exception:
                pass
            return
        if not reseller_uid:
            try:
                await event.answer("❌ آیدی نماینده نامعتبر است.", alert=True)
            except Exception:
                pass
            return
        # بررسی اینکه آیا این آیدی واقعاً RESELLER است.
        reseller_entry = None
        for e in list_admins_and_resellers():
            if e["user_id"] == reseller_uid and e["role"] == ROLE_RESELLER:
                reseller_entry = e
                break
        body = [f"👥 **مشتریانِ نماینده‌ی `{reseller_uid}`**\n"]
        if not reseller_entry:
            body.append(f"{UI.RED} این آیدی در لیست نماینده‌های فعال نیست.")
            body.append(f"{UI.GRAY} (ممکن است حذف شده باشد یا اصلاً نماینده نباشد.)")
            await event.edit(
                "\n".join(body),
                buttons=[
                    [UI.go("🤝 لیست نماینده‌ها", "owner_resellers")],
                    UI.nav_row(),
                ],
            )
            return
        try:
            customers = list_users_for_reseller(reseller_uid)
        except Exception as e:
            print(f"⚠️ [TEST-G7-RESELLER] list_users_for_reseller failed: {e}")
            customers = []
        cap = reseller_entry.get("reseller_max_users")
        body.append(f"📊 تعداد مشتریان: {fa_digits(len(customers))}"
                    + (f" / سقف: {fa_digits(cap)}" if cap else " / سقف: نامحدود"))
        body.append("")
        if not customers:
            body.append(f"{UI.GRAY} این نماینده هنوز مشتری ندارد.")
        else:
            for c in customers[:30]:
                cid = c["user_id"]
                name = (c.get("first_name") or "").strip()
                uname = f"@{c['username']}" if c.get("username") else ""
                body.append(f"👤 {name} {uname} — `{cid}`")
            if len(customers) > 30:
                body.append(f"{UI.GRAY} … و {fa_digits(len(customers) - 30)} مشتری دیگر")
        # دکمه‌ی مدیریتِ هر مشتری (به پنل مدیریتِ کاربر هدایت می‌کند).
        buttons = []
        for c in customers[:15]:
            cid = c["user_id"]
            name = (c.get("first_name") or "").strip() or str(cid)
            buttons.append([UI.go(
                f"👤 {name} — {cid}",
                f"user_manage:{cid}",
            )])
        if len(customers) > 15:
            buttons.append([UI.neutral(
                f"… و {fa_digits(len(customers) - 15)} مشتری دیگر (از جستجو پیدا کن)",
                NAV_NOOP,
            )])
        buttons.append([UI.go("🔙 بازگشت به لیست نماینده‌ها", "owner_resellers")])
        buttons.append(UI.nav_row())
        text = UI.screen("👥 مشتریان نماینده", body=body,
                         subtitle=f"نماینده: {reseller_uid}")
        await event.edit(text, buttons=buttons)

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
        # v1.8.0: فیکس - قبلاً event.answer() صدا زده نمی‌شد و تلگرام spinner
        # رو نشون می‌داد تا timeout. این باعث می‌شد کاربر فکر کنه دکمه خرابه.
        try:
            await event.answer()
        except Exception:
            pass
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
        buttons.append([UI.go("➕ اعطای مجوز به شخص", "cap_add_start")])
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
        buttons.append([UI.go("🔐 فهرستِ مجوزها", "cap_list")])
        buttons.append(UI.nav_row())
        await event.edit(UI.screen("🔐 مجوزِ حساس", body=body), buttons=buttons)

    async def _owner_choose_capability_scope(self, event, uid: int):
        """انتخابِ دامنه‌ی مجوز قبل از تأیید.

        v2.8.8 BUGFIX: این تابع ممکن است از دو جا صدا زده بشه:
        ۱. از callback (event.edit کار می‌کنه)
        ۲. از text wizard (event.edit کار نمی‌کنه — BadRequestError)
        تابع خودش تشخیص می‌ده و از روش درست استفاده می‌کنه.
        """
        if not self._cap_owner_only(event):
            return
        if not uid:
            # event.answer فقط روی callback‌ها کار می‌کنه
            if hasattr(event, "answer"):
                await event.answer("کاربر نامعتبر است.", alert=True)
            else:
                await event.respond("❌ کاربر نامعتبر است.")
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
        screen_text = UI.screen("🔐 انتخابِ دامنه", body=body)
        # v2.8.8: تشخیص نوع event — اگه CallbackQuery.Event هست (با edit)،
        # وگرنه از respond استفاده کن.
        if hasattr(event, "edit") and hasattr(event, "message_id"):
            try:
                await event.edit(screen_text, buttons=buttons)
                return
            except Exception:
                pass  # fallback به respond
        # حالت پیام متنی — از respond استفاده کن
        # nav.push رو هم بزن تا back درست کار کنه
        try:
            self.nav.push(event.sender_id, f"cap_user:{uid}")
        except Exception:
            pass
        await event.respond(screen_text, buttons=buttons)

    async def _owner_confirm_capability(self, event, uid: int, scope: str):
        """تأییدِ نهاییِ اعطا — یک کلیکِ تصادفی نباید مجوز بدهد."""
        if not self._cap_owner_only(event):
            return
        if not uid or scope not in _SCOPE_LABELS:
            await event.answer("درخواست نامعتبر است.", alert=True)
            return
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

    async def _owner_show_licenses(self, event, filter_type: str = None):
        """
        لیستِ لایسنس‌های ساخته‌شده با دکمه‌های مدیریتِ هر لایسنس.

        v2.13.0 (TEST-G3-LICENSE FIX#1 + FIX#2):
        - FIX#1: دکمه‌ی «مدیریت» برای هر لایسنس اضافه شد — از آن مسیر،
          OWNER/ADMIN می‌توانند لایسنس را غیرفعال یا حذف کنند (قبلاً این
          توابع وجود داشتند ولی هیچ callback/UI آن‌ها را صدا نمی‌زد).
        - FIX#2: فیلتر بر اساس نوع (همه/اشتراک/نمایندگی/ادمین) — قبلاً
          همه‌ی لایسنس‌ها بدون فیلتر نمایش داده می‌شدند.
        - RESELLER همچنان فقط لایسنس‌های خودش را می‌بیند.
        - برای مدیریتِ یک لایسنس (deactivate/delete) به مسیر
          lic_view:{code} می‌رود — صفحه‌ی جزئیات، با دکمه‌های اکشن.
        """
        # normalize filter
        if filter_type not in (LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER,
                              LICENSE_TYPE_ADMIN, None):
            filter_type = None
        # نماینده فقط لایسنس‌های خودش را می‌بیند (نه لایسنس‌های بقیه)
        role = self._role(event.sender_id)
        created_by = event.sender_id if role == ROLE_RESELLER else None
        lic_list = list_licenses(15, created_by=created_by,
                                 license_type=filter_type)
        # Header
        title = ("🎫 **لایسنس‌های ساخته‌شده توسط من**"
                 if created_by is not None
                 else "🎫 **لایسنس‌های ساخته‌شده**")
        # Filter buttons — برای OWNER/ADMIN همه‌ی فیلترها، برای RESELLER
        # فقط account (چون RESELLER فقط account می‌سازد)
        filter_buttons = []
        if role != ROLE_RESELLER:
            filter_buttons = [
                UI.go("همه", b"lic_filter:all",
                      tone="success" if filter_type is None else "neutral"),
                UI.go("👤 اشتراک", b"lic_filter:account",
                      tone="success" if filter_type == LICENSE_TYPE_ACCOUNT else "neutral"),
                UI.go("🤝 نمایندگی", b"lic_filter:reseller",
                      tone="success" if filter_type == LICENSE_TYPE_RESELLER else "neutral"),
                UI.go("🛡 ادمین", b"lic_filter:admin",
                      tone="success" if filter_type == LICENSE_TYPE_ADMIN else "neutral"),
            ]
        if not lic_list:
            body_lines = [title, ""]
            if filter_type is not None:
                body_lines.append(
                    f"📭 هیچ لایسنسی از این نوع پیدا نشد "
                    f"({_TYPE_NAMES.get(filter_type, filter_type)})."
                )
            else:
                body_lines.append("📭 هنوز لایسنسی ساخته نشده.")
            body_lines.append("")
            body_lines.append("🔒 هر لایسنس تا max_uses بار قابل‌استفاده (پیش‌فرض ۱).")
            buttons = []
            if filter_buttons:
                buttons.append(filter_buttons)
            buttons.append(UI.nav_row())
            await event.edit("\n".join(body_lines), buttons=buttons)
            return
        # Body — ۱۵ ردیف آخر (برای جا دادنِ دکمه‌های مدیریت در همان پیام)
        lines = [title + f" (۱۵ تای آخر):", ""]
        for lic in lic_list:
            tname = _TYPE_NAMES.get(lic["license_type"], lic["license_type"])
            status = "✅ فعال" if lic["is_active"] else "⛔ غیرفعال"
            lines.append(
                f"`{lic['code']}` — {tname} — "
                f"مصرف: {lic['used_count']}/{lic['max_uses']} — {status}"
            )
        lines.append("")
        lines.append("🔒 هر لایسنس تا max_uses بار قابل‌استفاده (پیش‌فرض ۱).")
        lines.append("👉 برای غیرفعال‌کردن یا حذف، روی کد لایسنس بزن.")
        # Per-license management buttons — یک ردیف برای هر لایسنس
        # (تلگرام تا ۱۰۰ دکمه در هر پیام را پشتیبانی می‌کند)
        buttons = []
        if filter_buttons:
            buttons.append(filter_buttons)
        for lic in lic_list:
            # برچسب: ۱۰ کاراکتر اولِ کد + وضعیت
            short_code = lic["code"][:14] + ("…" if len(lic["code"]) > 14 else "")
            badge = "✅" if lic["is_active"] else "⛔"
            buttons.append([
                UI.go(f"{badge} {short_code}", f"lic_view:{lic['code']}".encode())
            ])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(lines), buttons=buttons)

    async def _owner_show_license_detail(self, event, code: str):
        """
        صفحه‌ی جزئیاتِ یک لایسنس — با دکمه‌های «غیرفعال‌کردن» و «حذف».

        v2.13.0 (TEST-G3-LICENSE FIX#1): قبلاً هیچ مسیری برای مدیریتِ
        یک لایسنسِ ساخته‌شده وجود نداشت — `deactivate_license` تعریف
        شده بود ولی هیچ callback‌ای آن را صدا نمی‌زد (dead code). حالا
        از طریق دکمه‌ی `lic_view:{code}` در لیستِ لایسنس‌ها قابل دسترس
        است. دسترسی فقط برای OWNER/ADMIN/RESELLER (با محدودیتِ
        مالکیت: RESELLER فقط لایسنس‌های خودش را می‌بیند).
        """
        role = self._role(event.sender_id)
        if role not in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
            try:
                await event.answer("⛔ این بخش فقط برای OWNER/ADMIN/RESELLER است.",
                                   alert=True)
            except Exception:
                pass
            return
        lic = get_license(code)
        if not lic:
            try:
                await event.answer("❌ این لایسنس پیدا نشد.", alert=True)
            except Exception:
                pass
            await self._owner_show_licenses(event)
            return
        # مالکیت: RESELLER فقط لایسنس‌های خودش
        if role == ROLE_RESELLER and lic.get("created_by") != event.sender_id:
            try:
                await event.answer("⛔ این لایسنس توسط شما ساخته نشده.",
                                   alert=True)
            except Exception:
                pass
            await self._owner_show_licenses(event)
            return
        tname = _TYPE_NAMES.get(lic["license_type"], lic["license_type"])
        status = "✅ فعال" if lic["is_active"] else "⛔ غیرفعال"
        used = lic["used_count"]
        mu = lic["max_uses"]
        rul = lic.get("reseller_user_limit")
        dur = lic.get("duration_days")
        body_lines = [
            "🎫 **جزئیات لایسنس**",
            "",
            f"🆔 کد:\n`{lic['code']}`",
            f"🏷 نوع: {tname}",
            f"📊 مصرف: {used} از {mu}",
            f"وضعیت: {status}",
            f"🕐 ساخته‌شده: {lic['created_at']}",
        ]
        if lic["license_type"] == LICENSE_TYPE_ACCOUNT and dur is not None:
            body_lines.append(f"⏳ مدت: {dur} روز")
        if lic["license_type"] == LICENSE_TYPE_RESELLER:
            body_lines.append(f"👥 سقف مشتری: {rul if rul else 'نامحدود'}")
        if lic.get("created_by") is not None:
            body_lines.append(f"👤 سازنده: `{lic['created_by']}`")
        # دکمه‌های اکشن
        buttons = []
        if lic["is_active"]:
            buttons.append([UI.danger("⛔ غیرفعال‌کردن",
                                       f"lic_deactivate:{lic['code']}".encode())])
        # حذف — فقط لایسنس‌های مصرف‌نشده (یا غیرفعال) قابل حذف‌اند تا
        # history اشتراک‌های فعال (که از طریق license_id به لایسنس
        # متصل‌اند) سالم بماند. اگر لایسنس فعال و مصرف‌شده است، حذف
        # مسدود می‌شود تا referential integrity حفظ شود.
        can_delete = (used == 0) or (not lic["is_active"])
        if can_delete:
            buttons.append([UI.danger("🗑 حذف لایسنس",
                                       f"lic_delete:{lic['code']}".encode())])
        else:
            body_lines.append("")
            body_lines.append(
                f"{UI.AMBER} این لایسنس فعال و در حال استفاده است — "
                f"برای حذف، اول آن را غیرفعال کن."
            )
        buttons.append([UI.go("↩️ برگشت به لیست", b"license_access_list")])
        buttons.append(UI.nav_row())
        await event.edit("\n".join(body_lines), buttons=buttons)

    async def _owner_deactivate_license(self, event, code: str):
        """Callback handler for `lic_deactivate:{code}`."""
        role = self._role(event.sender_id)
        if role not in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
            try:
                await event.answer("⛔ مجوز کافی نیست.", alert=True)
            except Exception:
                pass
            return
        lic = get_license(code)
        if not lic:
            try:
                await event.answer("❌ لایسنس پیدا نشد.", alert=True)
            except Exception:
                pass
            await self._owner_show_licenses(event)
            return
        # مالکیت: RESELLER فقط لایسنس‌های خودش
        if role == ROLE_RESELLER and lic.get("created_by") != event.sender_id:
            try:
                await event.answer("⛔ این لایسنس توسط شما ساخته نشده.",
                                   alert=True)
            except Exception:
                pass
            return
        changed = deactivate_license(code, actor_id=event.sender_id)
        try:
            await event.answer(
                "✅ لایسنس غیرفعال شد." if changed
                else "ℹ️ این لایسنس از قبل غیرفعال بود.",
                alert=True,
            )
        except Exception:
            pass
        # Refresh detail view
        await self._owner_show_license_detail(event, code)

    async def _owner_delete_license(self, event, code: str):
        """
        Callback handler for `lic_delete:{code}` — با تأییدِ دوم‌مرحله‌ای.
        اول بار: هشدار. دوم بار (lic_delete_go:): حذف واقعی.
        """
        role = self._role(event.sender_id)
        if role not in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
            try:
                await event.answer("⛔ مجوز کافی نیست.", alert=True)
            except Exception:
                pass
            return
        lic = get_license(code)
        if not lic:
            try:
                await event.answer("❌ لایسنس پیدا نشد.", alert=True)
            except Exception:
                pass
            await self._owner_show_licenses(event)
            return
        # مالکیت: RESELLER فقط لایسنس‌های خودش
        if role == ROLE_RESELLER and lic.get("created_by") != event.sender_id:
            try:
                await event.answer("⛔ این لایسنس توسط شما ساخته نشده.",
                                   alert=True)
            except Exception:
                pass
            return
        # اگر فعال و مصرف‌شده است، حذف ممنوع — لایه‌ی دوم دفاع
        if lic["is_active"] and lic["used_count"] > 0:
            try:
                await event.answer(
                    "❌ این لایسنس فعال و در حال استفاده است — "
                    "اول آن را غیرفعال کن.",
                    alert=True,
                )
            except Exception:
                pass
            await self._owner_show_license_detail(event, code)
            return
        # تأییدِ نهایی
        body = [
            "🗑 **حذف لایسنس**",
            "",
            f"🆔 `{lic['code']}`",
            f"🏷 نوع: {_TYPE_NAMES.get(lic['license_type'], lic['license_type'])}",
            f"📊 مصرف: {lic['used_count']}/{lic['max_uses']}",
            "",
            f"{UI.RED} ⚠️ این عمل قابل بازگشت نیست.",
            "اگر مطمئنی، دکمه‌ی «بله، حذف کن» را بزن.",
        ]
        buttons = [
            [UI.danger("✅ بله، حذف کن", f"lic_delete_go:{lic['code']}".encode())],
            [UI.go("↩️ برگشت به جزئیات", f"lic_view:{lic['code']}".encode())],
        ]
        await event.edit("\n".join(body), buttons=buttons)

    async def _owner_delete_license_go(self, event, code: str):
        """Callback handler for `lic_delete_go:{code}` — تأییدِ نهایی."""
        role = self._role(event.sender_id)
        if role not in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
            try:
                await event.answer("⛔ مجوز کافی نیست.", alert=True)
            except Exception:
                pass
            return
        lic = get_license(code)
        if not lic:
            try:
                await event.answer("❌ لایسنس پیدا نشد (شاید قبلاً حذف شده).",
                                    alert=True)
            except Exception:
                pass
            await self._owner_show_licenses(event)
            return
        if role == ROLE_RESELLER and lic.get("created_by") != event.sender_id:
            try:
                await event.answer("⛔ این لایسنس توسط شما ساخته نشده.",
                                   alert=True)
            except Exception:
                pass
            return
        # لایه‌ی دوم دفاع: اگر در بینِ کاربر دیدنِ تأیید و کلیک کردن،
        # لایسنس فعال شده و مصرف شده، حذف ممنوع است.
        if lic["is_active"] and lic["used_count"] > 0:
            try:
                await event.answer(
                    "❌ این لایسنس الان فعال و در حال استفاده است — "
                    "اول آن را غیرفعال کن.",
                    alert=True,
                )
            except Exception:
                pass
            await self._owner_show_license_detail(event, code)
            return
        deleted = delete_license(code, actor_id=event.sender_id)
        if deleted:
            try:
                await event.answer("🗑 لایسنس حذف شد.", alert=True)
            except Exception:
                pass
            await self._owner_show_licenses(event)
        else:
            try:
                await event.answer("❌ حذف ناموفق بود (شاید قبلاً حذف شده).",
                                    alert=True)
            except Exception:
                pass
            await self._owner_show_licenses(event)

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
            "فقط Backup معتبر پروژه پذیرفته می‌شود.\n\n"
            "⚠️ **توجه:** قبل از Restore، ابتدا یک Backup بگیرید.\n"
            "سلف‌بات‌های روشن در حین Restore متوقف می‌شوند.",
            buttons=[[UI.neutral(UI.L_CANCEL, "owner_db_restore_cancel")]],
        )

    async def _handle_document_wizard(self, event, wiz: dict) -> bool:
        """دریافت فایل بکاپ برای Restore (فقط OWNER): دانلود → validate → تأیید."""
        if wiz["state"] != WIZ_DB_RESTORE:
            return False
        # v2.23.1 (AUDIT-43 #5): فعالیت → تمدید TTL.
        wiz["_ts"] = time.time()
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
            await event.respond(_friendly_error(e, "download"))
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

        # v2.23.1 (AUDIT-43 #4): بکاپ‌های خودِ ربات همیشه CNB1 (رمزگذاری‌شده)
        # هستند — قبلاً اینجا مستقیم validate_backup_zip صدا زده می‌شد و فایلِ
        # CNB1 با پیامِ گیج‌کننده‌ی «فایل ZIP خراب است» رد می‌شد؛ یعنی
        # بکاپ‌های خودِ سیستم عملاً غیرقابلِ Restore بودند. حالا رمز در
        # مرحله‌ی بعد پرسیده و درجا دیکریپت می‌شود.
        _is_cnb1 = False
        try:
            with open(tmp, "rb") as _f:
                _is_cnb1 = _f.read(4) == b"CNB1"
        except Exception:
            pass
        if _is_cnb1:
            wiz["state"] = WIZ_DB_RESTORE_PASS
            wiz["data"]["tmp_enc"] = tmp
            await event.respond(
                "🔐 این فایل بکاپ **رمزگذاری‌شده** است.\n\n"
                "رمزِ آن را همینجا به‌صورت پیام بفرست تا دیکریپت و بررسی شود.\n"
                "(رمزِ بکاپ موقعِ گرفتنِ بکاپ، جدا از فایل برایتان ارسال شده است.)",
                buttons=[[UI.neutral(UI.L_CANCEL, "owner_db_restore_cancel")]],
            )
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
        # v2.22.2: edit پیشرفت نباید Restore را قطع کند (پیامِ کهنه/قفل) —
        # در بدترین حالت بدونِ نشانگرِ پیشرفت ادامه می‌دهیم.
        try:
            await event.edit("♻️ در حال Restore (اول Runtimeها متوقف می‌شوند)...")
        except Exception:
            pass
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
            # v2.22.2 (AUDIT-40): تک‌رندر — قبلاً برای همین یک کلیک سه رندر
            # انجام می‌شد (edit پیشرفت + respond موفقیت + منوی نقش به‌صورت
            # پیامِ جدا). حالا همان پیامِ تأیید درجا به متنِ موفقیت + دکمه‌ی
            # خانه تبدیل می‌شود.
            try:
                await event.edit(
                    "✅ Restore با موفقیت انجام شد.\n\n"
                    "اطلاعات سیستم با موفقیت بازیابی شد.\n"
                    "برای اعمال کامل روی سلف‌بات‌های روشن، ربات را ری‌استارت کن.",
                    buttons=[UI.nav_row(back=False)],
                )
            except Exception:
                await event.respond(
                    "✅ Restore با موفقیت انجام شد.\n\n"
                    "اطلاعات سیستم با موفقیت بازیابی شد.\n"
                    "برای اعمال کامل روی سلف‌بات‌های روشن، ربات را ری‌استارت کن.",
                    buttons=[UI.nav_row(back=False)],
                )
        else:
            await event.respond(
                "❌ Restore انجام نشد.\n\nBackup فعلی تغییری نکرده است.\n\nخطا:\n" + msg
            )

    async def _owner_db_restore_cancel(self, event):
        """❌ لغو Restore — ویزارد بسته و فایل موقت پاک می‌شود."""
        wiz = self.wizards.pop(event.sender_id, None)
        # v2.23.1 (AUDIT-43 #4): فایلِ رمزگذاری‌شده‌ی CNB1 هم باید پاک شود.
        for _key in ("tmp_zip", "tmp_enc"):
            tmp = ((wiz or {}).get("data", {}) or {}).get(_key)
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
        """
        v1.8.0: شروع پشتیبانی - ابتدا واحد رو بپرس، تیکت نساز الکی.

        قبلاً با زدن «☎️ پشتیبانی» بلافاصله یه تیکت ساخته می‌شد حتی اگه
        کاربر پیامی نمی‌فرستاد. این باعث می‌شد لیست تیکت‌های باز پر از
        تیکت‌های خالی بشه. حالا:
        1. لیست واحدهای پشتیبانی نمایش داده می‌شه
        2. کاربر یکی رو انتخاب می‌کنه
        3. پیامش رو می‌فرسته
        4. تیکت ساخته می‌شه
        """
        try:
            await event.answer()
        except Exception:
            pass
        # اگه از قبل تیکت باز داره، مستقیم بره سراغش
        existing = get_open_ticket(event.sender_id)
        if existing and ticket_message_count(existing["id"]) > 0:
            # تیکت فعال داره (حداقل یه پیام) - مستقیم بره
            await self._clear_admin_panel_wizard(event.sender_id)
            self._start_own_wizard(
                event.sender_id, WIZ_TICKET_MSG,
                {"ticket_id": existing["id"]},
            )
            await event.edit(
                f"✅ تیکت #{existing['id']} باز داری.\n\n"
                "پیام بعدیت رو بفرست:",
                buttons=[[UI.neutral("پایان گفتگو", "user_support_end")],
                         UI.nav_row(home=False)],
            )
            return

        # تیکت بازِ خالی (که هیچ پیامی نداره) رو می‌بندیم
        if existing:
            close_ticket(existing["id"])

        # نمایش واحدهای پشتیبانی
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, WIZ_TICKET_UNIT, {})
        buttons = []
        for unit_id, unit_name, unit_desc in SUPPORT_UNITS:
            buttons.append([UI.go(unit_name, f"ticket_unit:{unit_id}")])
        buttons.append(UI.nav_row(home=False))
        await event.edit(
            "☎️ **پشتیبانی**\n\n"
            "لطفاً واحد مورد نظرت رو انتخاب کن، بعد پیامت رو بفرست.\n"
            "(تیکت فقط بعد از ارسال پیام ساخته می‌شه)",
            buttons=buttons,
        )

    async def _select_ticket_unit(self, event, unit_id: str):
        """v1.8.0: کاربر واحد رو انتخاب کرد - ویزارد پیام فعال بشه."""
        try:
            await event.answer()
        except Exception:
            pass
        unit_name = next((n for u, n, _ in SUPPORT_UNITS if u == unit_id), unit_id)
        # ویزارد رو به حالت پیام تغییر بده
        self._start_own_wizard(
            event.sender_id, WIZ_TICKET_MSG,
            {"unit": unit_id, "unit_name": unit_name},
        )
        await event.edit(
            f"✅ واحد «{unit_name}» انتخاب شد.\n\n"
            "پیام خود را ارسال کنید. هر چه جزئیات بیشتر = پاسخ بهتر.",
            buttons=[[UI.neutral("پایان گفتگو", "user_support_end")],
                     UI.nav_row(home=False)],
        )

    async def _user_support_end(self, event):
        wiz = self.wizards.pop(event.sender_id, None)
        if wiz:
            # v2.22.1 (AUDIT-39/d#4): «پایان گفتگو» قبل از اولین پیام (بلافاصله
            # بعد از انتخابِ واحد) → ticket_id هنوز ساخته نشده — قبلاً
            # KeyError("ticket_id") می‌خورد و کاربر پیامِ «خطایی رخ داد» +
            # از دستِ دادنِ ویزارد می‌گرفت. حالا get با پیش‌فرض.
            ticket_id = (wiz.get("data") or {}).get("ticket_id")
            if ticket_id and ticket_message_count(ticket_id) > 0:
                close_ticket(ticket_id)
        # فیکس v1.7.1: نقش واقعی کاربر رو بگیر، نه ROLE_USER رو hardcode کن.
        # قبلاً اینجا همیشه ROLE_USER پاس داده می‌شد — یعنی اگه OWNER یا
        # ADMIN یا RESELLER می‌زد «پایان گفتگو»، تبدیل به کاربر عادی
        # می‌شد (دکمه‌ی «ادمین» از منوش ناپدید می‌شد).
        real_role = self._role(event.sender_id)
        await self._show_menu_for_role(event.chat_id, real_role, edit_event=event)

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
        # v2.17.0: پلن‌های دسته‌جمعی از فهرستِ عادی حذف می‌شوند (مالِ مسیر
        # خودشان‌اند) و اگر خریدارِ فاقدِ اشتراک باشد، گزینه‌ی دسته‌جمعی
        # با تخفیف گروهی هم پایینِ فهرست پیشنهاد می‌شود.
        plans = [p for p in list_pricing() if not is_group_plan(p["plan"])]
        buttons = []
        for _pi, p in enumerate(plans):
            _cb = f"renew_plan:{p['plan']}"
            # v2.19.4 (AUDIT-36 M12 — MEDIUM): نامِ بلند (۲۷+ حرف فارسی =
            # ۶۵+ بایت با prefix) از سقفِ callback-data تلگرام (۶۴ بایت) رد
            # می‌شد و ValueError در زمانِ ساختِ دکمه، کلِ صفحه‌ی خرید را برای
            # همه‌ی کاربران می‌کشت. پلن‌های با نامِ کوتاه همان callback نامیِ
            # قبلی را می‌گیرند (سازگاری کامل با پلن‌های موجود)؛ نامِ بلند
            # به index ارجاع می‌دهد و در _user_plan_chosen resolve می‌شود.
            if len(_cb.encode("utf-8")) > 64:
                _cb = f"renew_plan:idx{_pi}"
            buttons.append([UI.go(f"{p['plan']} — {p['price_toman']:,} تومان", _cb.encode())])
        if group_sub_enabled() \
                and self._role(event.sender_id) not in (ROLE_OWNER, ROLE_ADMIN) \
                and not get_active_subscription(event.sender_id):
            buttons.append([UI.go("👥 اشتراک دسته‌جمعی (تخفیف گروهی)",
                                  "user_group_sub", tone="success")])
        buttons.append(UI.nav_row())
        await event.edit("💳 یکی از پلن‌ها رو انتخاب کن:", buttons=buttons)

    async def _compute_order_amounts(self, toman: int) -> tuple:
        """مبلغ تومان → معادل تتر با نرخ لحظه‌ای؛ fallback به تنظیم/ثابت.
        خروجی: (amount_usdt, rate_toman). +۱٪ بافر برای نوسان قیمت.

        v2.9.2: timeout ۵ ثانیه اضافه شد — قبلاً اگه همه‌ی صرافی‌های ایرانی
        timeout می‌شدن، ۳۰+ ثانیه طول می‌کشید و کاربر «خطا در پردازش این دکمه»
        می‌دید. حالا بعد از ۵ ثانیه، به fallback ثابت برمی‌گرده.
        """
        rate = None
        try:
            # v2.9.2: timeout کوتاه — اگه صرافی‌ها جواب ندادن، سریع fallback کن
            rate = await asyncio.wait_for(_get_usd_toman_rate(), timeout=5.0)
        except (asyncio.TimeoutError, Exception):
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
                # v2.10.2: فقط درگاه‌های فعال
                # v2.10.3: فقط درگاه‌های فعال — با برچسب‌های فارسی درست
        buttons = []
        if (
            get_setting("pay_trc20_enabled", "1") == "1"
            and order.get("plan") != DEDICATED_BOT_PLAN
            and float(order.get("amount_usdt") or 0) > 0
        ):
            buttons.append([UI.go("💵 پرداخت با تتر (TRC20)", f"order_tron:{order['id']}".encode())])
        if get_setting("pay_card_enabled", "1") == "1":
            buttons.append([UI.go("💳 پرداخت با کارت", f"order_card:{order['id']}".encode())])
        if get_setting("pay_zarinpal_enabled", "0") == "1" and (get_setting("zarinpal_merchant") or "").strip():
            buttons.append([UI.go("🟡 پرداخت آنلاین (زرین‌پال)", f"order_zarinpal:{order['id']}".encode())])
        if get_setting("pay_zibal_enabled", "0") == "1" and (get_setting("zibal_merchant") or "").strip():
            buttons.append([UI.go("🟢 پرداخت آنلاین (زیبال)", f"order_zibal:{order['id']}".encode())])
        try:
            bal = get_wallet_balance(order["user_id"])
            if bal >= int(order["amount_toman"]):
                buttons.append([UI.go(f"💰 پرداخت با کیف پول ({fa_digits(bal)} Toman)",
                                       f"order_wallet:{order['id']}".encode(), tone="success")])
        except Exception:
            pass
        if not order.get("discount_code"):
            buttons.append([UI.go("🎁 کد تخفیف داری؟", f"order_discount:{order['id']}".encode())])
        buttons.append([UI.go("🧾 سفارش‌های من", b"user_orders")])
        buttons.append([UI.danger("لغو فاکتور", f"order_cancel:{order['id']}")])
        buttons.append(UI.nav_row())        # فاکتور همیشه از یک callback می‌آید → edit. (event.query همان
        # تشخیصِ قابل‌اطمینانِ CallbackQuery است؛ هم‌چنین برای امنیت اگر
        # جایی از مسیر پیام متنی صدا زده شد، respond بفرستد.)
        if getattr(event, "query", None) is None:
            await event.respond(text, buttons=buttons)
        else:
            await event.edit(text, buttons=buttons)

    async def _user_plan_chosen(self, event, plan: str):
        # v2.19.4 (AUDIT-36 M12): ارجاعِ index برای پلن‌های با نامِ بلند —
        # callback «renew_plan:idxN» (ساخته‌شده در _user_start_renew وقتی نام
        # از سقفِ ۶۴ بایتِ تلگرام رد می‌شود) اینجا به نامِ واقعی resolve
        # می‌شود. اگر لیست بینِ رندر و کلیک عوض شده باشد، answerِ تمیز.
        if isinstance(plan, str) and plan.startswith("idx"):
            try:
                _pi = int(plan[3:])
            except ValueError:
                _pi = -1
            _plans = [p for p in list_pricing() if not is_group_plan(p["plan"])]
            if 0 <= _pi < len(_plans):
                plan = _plans[_pi]["plan"]
            else:
                await event.answer("❌ این پلن دیگر موجود نیست — لیست را دوباره باز کنید.", alert=True)
                return
        plans = {p["plan"]: p for p in list_pricing()}
        info = plans.get(plan)
        if not info:
            await event.answer("پلن نامعتبر است.", alert=True)
            return
        usdt, rate = await self._compute_order_amounts(info["price_toman"])
        order = create_order(event.sender_id, plan, info["price_toman"], usdt)
        await self._show_invoice(event, order, rate)

    # v2.9.0: کد تخفیف در فاکتور
    async def _start_discount_wizard(self, event, oid: int):
        """شروع ویزارد برای ورود کد تخفیف."""
        order = get_order(oid)
        if not order or order["user_id"] != event.sender_id:
            await event.answer("❌ فاکتور پیدا نشد.", alert=True)
            return
        if order.get("discount_code"):
            await event.answer("❌ این فاکتور قبلاً کد تخفیف دارد.", alert=True)
            return
        await self._clear_admin_panel_wizard(event.sender_id)
        self._start_own_wizard(event.sender_id, "discount_apply_code", {"order_id": oid})
        await event.respond(
            f"🎁 **کد تخفیف**\n\n"
            f"فاکتور: `{order['order_no']}` — {order['plan']}\n"
            f"مبلغ فعلی: {fa_digits(order['amount_toman'])} Toman\n\n"
            f"کد تخفیف رو بفرست:"
        )

    # v2.9.0: پرداخت با کیف پول
    async def _pay_order_from_wallet(self, event, oid: int):
        """پرداخت اتمیک فاکتور از موجودی کیف پول در یک تراکنش واحد (M-14)."""
        order = get_order(oid)
        if not order or order["user_id"] != event.sender_id:
            await event.answer("❌ فاکتور پیدا نشد.", alert=True)
            return
        amount = int(order["amount_toman"])
        try:
            pay_result = pay_order_wallet_atomic(event.sender_id, oid)
            if not pay_result.get("ok"):
                err = pay_result.get("error")
                if err == "insufficient_balance":
                    bal = pay_result.get("balance", 0)
                    await event.answer(
                        f"❌ موجودی کافی نیست.\nمبلغ فاکتور: {fa_digits(amount)} Toman\nموجودی شما: {fa_digits(bal)} Toman",
                        alert=True,
                    )
                else:
                    await event.answer("❌ این فاکتور قابل پرداخت نیست.", alert=True)
                return
            plan_name = pay_result["plan"]
            if plan_name == DEDICATED_BOT_PLAN:
                # v2.23.1 (AUDIT-43 #3): قبلاً اینجا event.sender_id (int)
                # پاس داده می‌شد ولی تابع dict با کلیدهای user_id/id
                # می‌خواهد → TypeError در هر پرداختِ کیف‌پولیِ پلنِ اختصاصی.
                # دیک سینتتیک: payment_id نال‌پذیر است (COALESCE در
                # update_dedicated_bot_status) — پرداختِ کیف‌پولی ردیفِ
                # payments ندارد.
                await self._activate_dedicated_bot({"id": None, "user_id": event.sender_id})
            # v2.12.21 (QA7-USER6 BUG#5): _pay_order_from_wallet،
            # _resume_user_selfbots رو صدا نمی‌زد. این یعنی کاربر بعد از
            # تمدید، SelfBotش همچنان disabled می‌موند تا restart بعدی.
            # حالا مثل بقیه‌ی مسیرها (admin card-pay، license، TRC20)
            # resume می‌کنه.
            try:
                await self._resume_user_selfbots(event.sender_id)
            except Exception as _re:
                print(f"⚠️ [wallet_pay] resume selfbots failed: {_re}")
            await event.edit(
                f"✅ پرداخت با کیف پول انجام شد\n\n"
                f"🧾 فاکتور: `{order['order_no']}`\n"
                f"💰 مبلغ: {fa_digits(amount)} Toman\n"
                f"💳 موجودی جدید: {fa_digits(pay_result['balance'])} Toman\n\n"
                f"✅ اشتراک «{plan_name}» فعال شد!",
                buttons=[UI.nav_row()],
            )
        except Exception as _e:
            print(f"⚠️ [wallet_pay] خطا در تأیید فاکتور: {_e}")
            # v2.12.27 (HUNT-1 #1/HUNT-5 #4): refund در صورت خطا — قبلاً
            # wallet debited بود ولی create_subscription یا UPDATE fail
            # می‌کرد و هیچ refund‌ای نبود. کاربر پولش رو از دست می‌داد.
            try:
                wallet_credit(event.sender_id, amount, OWNER_ID,
                              reason="refund: order confirm failed")
                print(f"✅ [wallet_pay] refund شد: {amount}")
            except Exception as _re:
                print(f"❌ [wallet_pay] refund FAILED: {_re}")
            await event.answer(f"❌ خطا در تأیید فاکتور — مبلغ برگشت.", alert=True)

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
        # TEST-G4-PAYMENT (BUG: SILENT_NOOP — لیست سفارش‌ها هیچ دکمه‌ای
        # نداشت؛ کاربر فقط می‌توانست شماره‌ها را بخواند و اگر فاکتور منقضی
        # شده بود، هیچ راهی برای تمدید/بازگرداندن یا حتی دیدنِ دوباره‌ی
        # فاکتور نداشت. حالا برای هر فاکتورِ pending/expired دکمه‌های
        # «مشاهده/پرداخت» و «تمدید ۲۴ ساعت» اضافه شده.)
        buttons = []
        for o in orders[:10]:
            lines.append(f"`{o['order_no']}` — {o['plan']} — {o['amount_toman']:,} تومان "
                         f"— {labels.get(o['status'], o['status'])}")
            if o["status"] == ORDER_STATUS_PAID and o["pay_method"] == "trc20":
                lines.append(f"   تتر: `{o['txid']}`")
            if o["status"] == ORDER_STATUS_PENDING:
                # فاکتور هنوز معتبر است — دکمه‌ی «پرداخت/مشاهده فاکتور»
                buttons.append([UI.go(
                    f"💳 {o['order_no']}",
                    f"order_view:{o['id']}".encode(),
                    primary=True,
                )])
            elif o["status"] == ORDER_STATUS_EXPIRED:
                # فاکتور منقضی — کاربر می‌تواند ۲۴ ساعت دیگر تمدید کند
                buttons.append([UI.go(
                    f"🔄 تمدید {o['order_no']}",
                    f"order_extend:{o['id']}".encode(),
                    tone="success",
                )])
        lines.append("\n⏳ فاکتورهای در انتظار تا ۲۴ ساعت معتبرند.")
        lines.append("🔄 فاکتورهای منقضی را می‌توانی ۲۴ ساعت تمدید کنی.")
        if not buttons:
            buttons = [UI.nav_row()]
        else:
            buttons.append(UI.nav_row())
        await event.edit(
            "\n".join(lines),
            buttons=buttons,
        )

    async def _user_start_trx_pay(self, event, order_id: int):
        order = get_order(order_id)
        if not order or order["user_id"] != event.sender_id or order["status"] != ORDER_STATUS_PENDING:
            await event.answer("این فاکتور معتبر نیست (شاید منقضی یا پرداخت شده).", alert=True)
            return
        if order.get("plan") == DEDICATED_BOT_PLAN or float(order.get("amount_usdt") or 0) <= 0:
            await event.answer("❌ پرداخت تتری برای این فاکتور مجاز نیست.", alert=True)
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

    # TEST-G4-PAYMENT: تمدید پنجره‌ی پرداخت یک فاکتور منقضی (یا هنوز
    # pending) توسط صاحبش. پیاده‌سازیِ دو مرحله‌ای مطابق بقیه‌ی flow
    # های sensitive (مثل user_delete): «order_extend:» صفحه‌ی تأیید را
    # نشان می‌دهد، «order_extend_go:» عمل را انجام می‌دهد.
    async def _user_extend_order(self, event, order_id: int):
        order = get_order(order_id)
        if not order or order["user_id"] != event.sender_id:
            await event.answer("فاکتور پیدا نشد.", alert=True)
            return
        if order["status"] not in (ORDER_STATUS_PENDING, ORDER_STATUS_EXPIRED):
            await event.answer(
                "این فاکتور قابل تمدید نیست (پرداخت‌شده/لغو).", alert=True
            )
            return
        await event.edit(
            f"🔄 **تمدید فاکتور**\n\n"
            f"🧾 `{order['order_no']}` — {order['plan']}\n"
            f"💰 {order['amount_toman']:,} تومان\n"
            f"📦 وضعیت فعلی: {order['status']}\n\n"
            f"با تأیید، ۲۴ ساعت به پنجره‌ی پرداخت اضافه می‌شود و اگر فاکتور "
            f"منقضی شده بود، دوباره قابل پرداخت می‌شود.",
            buttons=[
                [UI.confirm("✅ تمدید کن", f"order_extend_go:{order_id}".encode())],
                [UI.neutral(UI.L_CANCEL, NAV_BACK)],
            ],
        )

    async def _user_extend_order_go(self, event, order_id: int):
        order = get_order(order_id)
        if not order or order["user_id"] != event.sender_id:
            await event.answer("فاکتور پیدا نشد.", alert=True)
            return
        r = extend_order(order_id, event.sender_id, hours=24)
        if r.get("ok"):
            await event.answer("✅ فاکتور ۲۴ ساعت تمدید شد.", alert=True)
            # حالا فاکتور pending است — کاربر را به فاکتور/درگاه‌ها می‌بریم.
            refreshed = get_order(order_id)
            rate = (await self._compute_order_amounts(refreshed["amount_toman"]))[1]
            await self._show_invoice(event, refreshed, rate)
        else:
            err_map = {
                "not_found": "❌ فاکتور پیدا نشد.",
                "invalid_state": "❌ این فاکتور قابل تمدید نیست.",
                "invalid_hours": "❌ مدت نامعتبر.",
            }
            await event.answer(err_map.get(r.get("error"), "❌ خطا"), alert=True)

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
        # v2.23.1 (AUDIT-43 #5): هر فعالیتِ واقعی، TTL ویزارد را تمدید می‌کند
        # (همان الگوی AdminBot) — قبلاً _ts فقط موقعِ شروع/انتقال ست می‌شد و
        # فرآیندهایِ طولانیِ طبیعی (تیکت، رسید پرداخت، TRX، لایسنس) وسطِ کار
        # با «سکوتِ مطلق» می‌مُردند: نه پاسخی، نه خطایی — پیام کاربر در
        # fall-through گم می‌شد و او فکر می‌کرد ربات پیامش را خورده.
        wiz["_ts"] = time.time()

        # v2.22.1 (AUDIT-39/e#5): ویزاردهای تنظیمیِ مالک فقط در چتِ خصوصی
        # مصرف می‌شوند — تکمیلِ ویزارد در گروه، صفحه‌هایِ تنظیماتِ مالک را
        # در همان گروه پاس می‌داد. دامنهٔ محدود به سه ویزاردِ تازه (نکته‌ای
        # تغییرِ رفتار برای ویزاردهایِ قدیمی نمی‌کنیم). پیش‌فرضِ نبودِ
        # attribute (رویدادهایِ غیرِاستاندارد/تست) = مجاز.
        if state in (WIZ_SET_CHANNEL, WIZ_TRIAL_DAYS, WIZ_SELF_BACKUP_GROUP) \
                and getattr(event, "is_private", True) is False:
            await event.respond(
                "⚠️ این تنظیم فقط در چتِ خصوصیِ ربات قابلِ انجام است —"
                " همین پیام را در PV بفرست.",
            )
            return True

        # v2.12.9 (QA-USER): کاربر تو حالِ انتظارِ رسید (عکس) بود ولی متن
        # فرستاد. قبلاً این پیام سایلنت no-op می‌شد و کاربر گیر می‌کرد. حالا
        # پیامِ واضح می‌دیم و ویزارد رو باز نگه می‌داریم تا عکس رو بفرسته.
        if state == WIZ_PAYMENT_RECEIPT:
            await event.respond(
                "❌ این یک متن است، نه تصویرِ رسید.\n\n"
                "📷 لطفاً **عکسِ رسید پرداخت** رو بفرست (مثل اسکرین‌شات از اپلیکیشن بانکی).\n"
                "اگه می‌خوای انصراف بدی، دکمه‌ی «بازگشت» رو بزن.",
                buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
            )
            return True

        # v2.19.4 (AUDIT-36 L7): ویزارد Restore فقط document هندل می‌کرد و
        # پیامِ متنیِ مالک در وسطِ Restore سایلنت دراپ می‌شد (تا TTL ۳۰
        # دقیقه). حالا پاسخِ دوستانه + ویزارد باز — الگوی همان QA-USER.
        if state == WIZ_DB_RESTORE:
            await event.respond(
                "♻️ در انتظارِ **فایل ZIP بکاپ** هستم — لطفاً فایل را بفرست.\n"
                "متن پذیرفته نیست؛ برای لغو دکمه‌ی «بازگشت» را بزن.",
                buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
            )
            return True

        # v2.23.1 (AUDIT-43 #4): رمزِ فایلِ بکاپِ CNB1 — دیکریپت درجا،
        # سپس همان مسیرِ validate/تأییدِ ZIP خام.
        if state == WIZ_DB_RESTORE_PASS:
            pw = (event.raw_text or "").strip()
            if not pw:
                await event.respond(
                    "🔐 رمزِ فایل بکاپ را بفرست (متنِ خالی پذیرفته نیست).",
                    buttons=[[UI.neutral(UI.L_CANCEL, "owner_db_restore_cancel")]],
                )
                return True
            enc = wiz.get("data", {}).get("tmp_enc")
            dec = _decrypt_cnb1_to_temp(enc, pw) if enc else None
            if dec is None:
                # رمز غلط — ویزارد باز می‌ماند تا دوباره امتحان کند.
                await event.respond(
                    "❌ رمز درست نیست (یا فایل خراب است).\n\n"
                    "دوباره رمز را بفرست، یا با دکمه‌ی لغو منصرف شو.",
                    buttons=[[UI.neutral(UI.L_CANCEL, "owner_db_restore_cancel")]],
                )
                return True
            # فایلِ رمزگشایی‌شده جایگزینِ فایلِ رمز می‌شود.
            try:
                os.remove(enc)
            except Exception:
                pass
            wiz["data"].pop("tmp_enc", None)
            ok, msg = validate_backup_zip(dec)
            if not ok:
                self.wizards.pop(event.sender_id, None)
                await event.respond(
                    "❌ Restore انجام نشد.\n\nBackup فعلی تغییری نکرده است.\n\nخطا:\n" + msg
                )
                for _p in (dec,):
                    try:
                        os.remove(_p)
                    except Exception:
                        pass
                return True
            wiz["state"] = WIZ_DB_RESTORE_CONFIRM
            wiz["data"]["tmp_zip"] = dec
            await event.respond(
                "🔓 فایل با موفقیت رمزگشایی شد.\n\n"
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

        # v2.18.0: ورودی‌های متنیِ ریپورتر (هدف / سقف مالک / مرحله‌ی دکمه‌ای).
        # v2.19.2: پنجره‌ی گزارشِ مجدد (WIZ_REPORTER_DUP) هم اضافه شد.
        # کل منطق در cianet/bots/reporter.py — اینجا فقط دیلگیت.
        if state in (WIZ_REPORTER_TARGET, WIZ_REPORTER_FLOW, WIZ_REPORTER_CAP,
                     WIZ_REPORTER_DUP):
            return await reporter_module.handle_reporter_text(event, self, wiz)

        if state == WIZ_TICKET_MSG:
            # v1.8.0: اگه تیکت هنوز ساخته نشده (اولین پیام بعد از انتخاب واحد)،
            # الان بساز. این کار از ساختن تیکت‌های الکی جلوگیری می‌کنه.
            if "ticket_id" not in data or not data.get("ticket_id"):
                tid = create_ticket(event.sender_id)
                # واحد رو در description ذخیره کن (اگه موجوده)
                unit_name = data.get("unit_name", "")
                if unit_name:
                    try:
                        with _conn() as c:
                            c.execute(
                                "UPDATE tickets SET unit = ? WHERE id = ?",
                                (data.get("unit", ""), tid),
                            )
                    except Exception:
                        pass
                data["ticket_id"] = tid
                # ذخیره در ویزارد state
                self.wizards[event.sender_id]["data"] = data

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

        # v2.10.1: max_uses for single license
        if state == "set_merchant":
            gw = wiz["data"].get("gw", "")
            merchant = (text or "").strip()
            if not merchant or len(merchant) < 5:
                await event.respond("❌ کد معتبر نیست. دوباره بفرست:")
                return True
            self.wizards.pop(event.sender_id, None)
            # v2.13.0 (DEBUG-2 BUG#2): audit log مرچنت درگاه
            set_setting(f"{gw}_merchant", merchant, actor_id=event.sender_id)
            await event.respond(f"✅ مرچنت {gw} تنظیم شد\n🔑 `{merchant[:10]}...`\nحالا از پنل فعالش کن.")
            return True

        if state == WIZ_CL_MAX_USES:
            try:
                mu = _to_int(text)
                assert 1 <= mu <= 1000
            except (ValueError, AssertionError):
                await event.respond("❌ یه عدد بین ۱ و ۱۰۰۰ بفرست:")
                return True
            ltype = wiz["data"].get("license_type", LICENSE_TYPE_ACCOUNT)
            duration = wiz["data"].get("duration_days", 30)
            self.wizards.pop(event.sender_id, None)
            lic = create_license(ltype, duration_days=duration,
                                created_by=event.sender_id, max_uses=mu)
            await event.respond(_license_result_text(lic))
            return True

        # v2.10.1: max_uses for batch license
        if state == WIZ_CL_BATCH_MAX_USES:
            try:
                mu = _to_int(text)
                assert 1 <= mu <= 1000
            except (ValueError, AssertionError):
                await event.respond("❌ یه عدد بین ۱ و ۱۰۰۰ بفرست:")
                return True
            wiz["data"]["max_uses"] = mu
            wiz["state"] = WIZ_CL_BATCH_QTY
            await event.respond(
                "🔢 حالا تعداد لایسنس‌ها رو بفرست (۱ تا ۱۰۰):",
            )
            return True

        # v2.11: دریافت توکن ربات اختصاصی
        if state == "dedicated_bot_token":
            token = (text or "").strip()
            if not token or len(token) < 20 or ":" not in token:
                await event.respond("❌ توکن معتبر نیست. از @BotFather بگیر و بفرست:")
                return True
            uid = wiz["data"].get("user_id")
            self.wizards.pop(event.sender_id, None)
            try:
                with _conn_immediate() as c:
                    c.execute(
                        "INSERT INTO dedicated_bots (token, owner_id, status, created_at, reseller_id) "
                        "VALUES (?, ?, 'pending_payment', ?, ?)",
                        (token, uid, _now(), uid),
                    )
                # v2.12.31 (DEBUG-1 LOW-2): قبلاً ۲۰ کاراکتر اول token لاگ
                # می‌شد که bot_id + ':' + ~15 char از secret را افشا می‌کرد.
                # حالا فقط 6 کاراکتر اول (bot_id prefix، که public هست) لاگ
                # می‌شود و secret کاملاً protected است.
                log_action(uid, "dedicated_bot_request", f"token={token[:6]}...")
                await event.respond(
                    f"✅ **ربات اختصاصی ثبت شد!**\n\n"
                    f"🤖 توکن: `{token[:20]}...`\n"
                    f"⏳ OWNER باید فعالش کنه."
                )
            except Exception as e:
                # PATCH (P2-3 §17.3): خطای دیتابیس نباید به کاربر برود —
                # جزئیات فقط در لاگ سرور، پیام generic فارسی به کاربر.
                print(f"❌ [dedicated_bot_token] DB error: {type(e).__name__}: {e}")
                await event.respond("❌ خطا در ثبت ربات اختصاصی — دوباره تلاش کن یا با پشتیبانی تماس بگیر.")
            return True

        if state == WIZ_CL_BATCH_RESELLER_LIMIT:
            try:
                limit = int(text)
                assert limit > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یه عدد صحیح مثبت بفرست (سقف مشتری):")
                return True
            wiz["data"]["reseller_user_limit"] = limit
            wiz["state"] = WIZ_CL_BATCH_QTY
            await event.respond(
                "🔢 حالا تعداد لایسنس‌ها رو بفرست (۱ تا ۱۰۰):",
            )
            return True

        if state == WIZ_CL_BATCH_QTY:
            try:
                qty = int(text)
                assert 1 <= qty <= BATCH_LICENSE_MAX
            except (ValueError, AssertionError):
                await event.respond(
                    f"❌ یه عدد صحیح بین ۱ و {BATCH_LICENSE_MAX} بفرست:"
                )
                return True
            ltype = wiz["data"].get("license_type", LICENSE_TYPE_ACCOUNT)
            duration = wiz["data"].get("duration_days")
            reseller_limit = wiz["data"].get("reseller_user_limit")
            mu = wiz["data"].get("max_uses", 1)  # v2.10.1
            self.wizards.pop(event.sender_id, None)
            result = create_license_batch(
                license_type=ltype,
                duration_days=duration,
                created_by=event.sender_id,
                count=qty,
                reseller_user_limit=reseller_limit,
                max_uses=mu,
            )
            summary = _license_batch_result_text(result)
            await event.respond(summary)
            # اگر بیش از ۱۰ کد ساخته شد، لیست کامل را در یک فایل متنی بفرست
            # تا کاربر راحت کپی کند — پیام تلگرام محدودیت ۴۰۹۶ کاراکتر دارد.
            if isinstance(result, dict) and result.get("ok") and len(result.get("licenses", [])) > 10:
                try:
                    import io
                    lines = []
                    for lic in result["licenses"]:
                        lines.append(lic["code"])
                    file_body = "\n".join(lines)
                    buf = io.BytesIO(file_body.encode("utf-8"))
                    buf.name = "licenses.txt"
                    await event.respond(file=buf, force_document=True)
                except Exception as _e:
                    print(f"⚠️ [batch_license] send_file failed: {_e}")
            return True

        if state == WIZ_WALLET_CREDIT_AMOUNT:
            target_uid = wiz["data"].get("target_uid")
            try:
                amount = int(text)
                # PATCH (TEST-G2-USERMGMT FIX#2b): قبلاً فقط `assert amount != 0`
                # بود و prompt می‌گفت «منفی برای کسر» — ولی این مسیرِ «شارژ»
                # است. عدد منفی در مرحله‌ی بعد منجر به wallet_debit می‌شد که
                # برای RESELLER «permission_denied» می‌داد و برای OWNER/ADMIN
                # یک debit غیرمنتظره از مسیرِ credit بود. حالا فقط مثبت قبول
                # می‌شود؛ برای debit مسیرِ جداگانه‌ای (WIZ_WALLET_DEBIT_*)
                # وجود دارد.
                assert amount > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یه عدد صحیح مثبت بفرست (مبلغ شارژ به Toman):")
                return True
            wiz["data"]["amount"] = amount
            wiz["state"] = WIZ_WALLET_CREDIT_REASON
            await event.respond("📝 دلیل/توضیح این تراکنش رو بفرست (یا '-' بزن بدون توضیح):")
            return True

        if state == WIZ_WALLET_CREDIT_REASON:
            target_uid = wiz["data"].get("target_uid")
            amount = wiz["data"].get("amount", 0)
            reason = text if text.strip() and text.strip() != "-" else ""
            self.wizards.pop(event.sender_id, None)
            # PATCH (TEST-G2-USERMGMT FIX#2b): با مثبت‌شدنِ amount در مرحله‌ی
            # قبلی، این branchِ else دیگر قابل دسترس نیست، ولی به‌عنوان
            # defensive نگه داشته شده (در صورت data corruption یا migrated
            # wizard از نسخه‌ی قدیمی).
            if amount > 0:
                r = wallet_credit(target_uid, amount, event.sender_id, reason=reason)
            else:
                r = wallet_debit(target_uid, -amount, event.sender_id, reason=reason)
            if r.get("ok"):
                sign = "+" if amount > 0 else ""
                await event.respond(
                    f"✅ تراکنش ثبت شد\n"
                    f"👤 کاربر: `{target_uid}`\n"
                    f"💰 مبلغ: {sign}{fa_digits(abs(amount))} Toman\n"
                    f"💳 موجودی جدید: {fa_digits(r['balance'])} Toman\n"
                    + (f"📝 دلیل: {reason}" if reason else "")
                )
            else:
                err_map = {
                    "permission_denied": "⛔ شما مجاز به این عمل نیستید.",
                    "user_not_found": "❌ کاربر پیدا نشد.",
                    "invalid_amount": "❌ مبلغ نامعتبر.",
                    "insufficient_balance": "❌ موجودی کاربر کافی نیست.",
                }
                await event.respond(err_map.get(r.get("error"), "❌ خطای ناشناخته."))
            return True

        #debit wizard is similar but uses dedicated states for clarity
        if state == WIZ_WALLET_DEBIT_AMOUNT:
            target_uid = wiz["data"].get("target_uid")
            try:
                amount = int(text)
                assert amount > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یه عدد صحیح مثبت بفرست (مبلغ کسر به Toman):")
                return True
            wiz["data"]["amount"] = amount
            wiz["state"] = WIZ_WALLET_DEBIT_REASON
            await event.respond("📝 دلیل این کسر رو بفرست (یا '-' بدون توضیح):")
            return True

        if state == WIZ_WALLET_DEBIT_REASON:
            target_uid = wiz["data"].get("target_uid")
            amount = wiz["data"].get("amount", 0)
            reason = text if text.strip() and text.strip() != "-" else ""
            self.wizards.pop(event.sender_id, None)
            r = wallet_debit(target_uid, amount, event.sender_id, reason=reason)
            if r.get("ok"):
                await event.respond(
                    f"✅ کسر ثبت شد\n"
                    f"👤 کاربر: `{target_uid}`\n"
                    f"💰 مبلغ: -{fa_digits(amount)} Toman\n"
                    f"💳 موجودی جدید: {fa_digits(r['balance'])} Toman\n"
                    + (f"📝 دلیل: {reason}" if reason else "")
                )
            else:
                err_map = {
                    "permission_denied": "⛔ شما مجاز نیستید.",
                    "user_not_found": "❌ کاربر پیدا نشد.",
                    "invalid_amount": "❌ مبلغ نامعتبر.",
                    "insufficient_balance": "❌ موجودی کاربر کافی نیست.",
                }
                await event.respond(err_map.get(r.get("error"), "❌ خطای ناشناخته."))
            return True

        # v2.8.12: کدهای تخفیف
        # v2.9.0: اعمال کد تخفیف در فاکتور
        if state == WIZ_DISCOUNT_APPLY_CODE:
            oid = wiz["data"].get("order_id")
            code = (text or "").strip().upper()
            if not code:
                await event.respond("❌ کد رو بفرست:")
                return True
            order = get_order(oid)
            if not order or order["user_id"] != event.sender_id:
                # v2.14.2 (P2-10 / §20.10): مسیرهای مرده (فاکتور پیدا نشد /
                # قابل ویرایش نیست) همان‌جا pop می‌شوند — retry بی‌معنی است.
                self.wizards.pop(event.sender_id, None)
                await event.respond("❌ فاکتور پیدا نشد.")
                return True
            if order["status"] != ORDER_STATUS_PENDING or order.get("discount_code"):
                self.wizards.pop(event.sender_id, None)
                await event.respond("❌ این فاکتور قابل ویرایش نیست یا قبلاً کد تخفیف روی آن اعمال شده است.")
                return True
            # اعمال تخفیف
            new_amount = apply_discount_code(code, int(order["amount_toman"]))
            if not new_amount.get("ok"):
                # v2.14.2 (P2-10 / §20.10): کدِ نامعتبر/منقضی/تمام‌شده ویزارد
                # را نمی‌سوزاند — کاربر می‌تواند همان‌جا کد درست را بفرست
                # (قبلاً pop قبل از این اعتبارسنجی بود).
                err_map = {
                    "not_found": "❌ کد تخفیف پیدا نشد.",
                    "expired": "❌ کد تخفیف منقضی شده.",
                    "max_uses_reached": "❌ این کد دیگه قابل استفاده نیست.",
                }
                await event.respond(err_map.get(new_amount.get("error"), "❌ خطا."))
                return True
            self.wizards.pop(event.sender_id, None)
            # ذخیره‌ی تخفیف در فاکتور
            # PATCH (P2-3 BUG-14-verify): پرچمِ _order_saved تضمین می‌کند که
            # rollback فقط وقتی اجرا شود که خودِ UPDATE فاکتور شکست خورده
            # باشد. قبلاً respondِ موفقیت هم داخلِ try بود؛ اگر UPDATE
            # commit می‌شد ولی respond (مثلاً FloodWait) خطا می‌داد،
            # used_count به‌اشتباه کم می‌شد و بعداً cancel_order دوباره
            # کم می‌کرد (rollbackِ دوگانه — §11.4).
            _order_saved = False
            try:
                from decimal import Decimal, ROUND_HALF_UP
                _old_salt = Decimal(str(order.get("amount_salt") or "0.00"))
                _base_u = max(Decimal("0.00"), Decimal(str(order["amount_usdt"])) - _old_salt)
                _disc_u = (_base_u * Decimal(100 - new_amount["percent"]) / Decimal(100)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                _new_salt = (Decimal(secrets.randbelow(99) + 1) / Decimal(100)).quantize(Decimal("0.01"))
                _final_u = float(_disc_u + _new_salt) if _disc_u > 0 else 0.0
                with _conn_immediate() as c:
                    c.execute(
                        "UPDATE orders SET discount_code = ?, discount_percent = ?, "
                        "amount_toman = ?, amount_usdt = ?, amount_salt = ?, original_amount_toman = ? "
                        "WHERE id = ? AND status = 'pending' AND discount_code IS NULL",
                        (code, new_amount["percent"], new_amount["amount"],
                         _final_u, str(_new_salt),
                         int(order["amount_toman"]), oid),
                    )
                _order_saved = True
                await event.respond(
                    f"✅ تخفیف اعمال شد\n\n"
                    f"🎁 کد: `{code}`\n"
                    f"📊 تخفیف: {fa_digits(new_amount['percent'])}%\n"
                    f"💰 مبلغ قبلی: {fa_digits(order['amount_toman'])} Toman\n"
                    f"💰 مبلغ جدید: {fa_digits(new_amount['amount'])} Toman"
                )
            except Exception as _e:
                # PATCH (P1-3 BUG-14): apply_discount_code کد را در یک تراکنشِ
                # جداگانه مصرف می‌کند؛ اگر ذخیره‌ی تخفیف در فاکتور شکست بخورد،
                # کد «سوخته» می‌ماند بی‌آنکه چیزی اعمال شده باشد. برای
                # اتمیک‌ماندنِ نتیجه، used_count را برگردان می‌داریم (همان
                # الگوی rollback در cancel_order).
                if not _order_saved:
                    try:
                        with _conn_immediate() as c:
                            c.execute(
                                "UPDATE discount_codes SET used_count = MAX(0, used_count - 1) "
                                "WHERE UPPER(code) = UPPER(?) AND used_count > 0",
                                (code,),
                            )
                    except Exception as _rb:
                        print(f"⚠️ [discount_apply] rollback used_count failed: {_rb}")
                # PATCH (P2-3 §17.3): جزئیات exception فقط در لاگ سرور؛
                # به کاربر پیامِ generic فارسی (قبلاً {e} به کاربر می‌رفت).
                print(f"❌ [discount_apply] error (order_saved={_order_saved}): "
                      f"{type(_e).__name__}: {_e}")
                await event.respond("❌ خطا در اعمال تخفیف — لطفاً دوباره تلاش کن.")
            return True

        if state == WIZ_DISCOUNT_PERCENT:
            try:
                pct = int(text)
                assert 1 <= pct <= 100
            except (ValueError, AssertionError):
                await event.respond("❌ یه عدد بین ۱ و ۱۰۰ بفرست (درصد تخفیف):")
                return True
            wiz["data"]["percent"] = pct
            wiz["state"] = WIZ_DISCOUNT_MAX_USES
            await event.respond("🔢 تعداد استفاده‌های مجاز رو بفرست (مثلاً ۱ یا ۱۰):")
            return True

        if state == WIZ_DISCOUNT_MAX_USES:
            try:
                mx = int(text)
                assert mx > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یه عدد مثبت بفرست (تعداد استفاده‌ها):")
                return True
            pct = wiz["data"].get("percent", 0)
            self.wizards.pop(event.sender_id, None)
            r = create_discount_code(percent=pct, created_by=event.sender_id, max_uses=mx)
            if r.get("ok"):
                await event.respond(
                    f"✅ کد تخفیف ساخته شد\n"
                    f"🎟 کد: `{r['code']}`\n"
                    f"📊 درصد: {fa_digits(pct)}%\n"
                    f"🔢 استفاده‌های مجاز: {fa_digits(mx)}"
                )
            else:
                err_map = {
                    "permission_denied": "⛔ شما مجاز نیستید.",
                    "invalid_percent": "❌ درصد نامعتبر.",
                    "invalid_max_uses": "❌ تعداد نامعتبر.",
                }
                await event.respond(err_map.get(r.get("error"), "❌ خطای ناشناخته."))
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
            log_action(event.sender_id, "set_card_number", f"card=****{number[-4:]}")
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
            log_action(event.sender_id, "set_usdt_wallet", f"wallet={w[:6]}...{w[-4:]}")
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
                                             "data": {"plan": name, "days": None},
                                             "_ts": time.time()}
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
                                                 "data": {"plan": plan, "price": price},
                                                 "_ts": time.time()}
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
                    or order["status"] != ORDER_STATUS_PENDING \
                    or order.get("plan") == DEDICATED_BOT_PLAN \
                    or float(order.get("amount_usdt") or 0) <= 0:
                self.wizards.pop(event.sender_id, None)
                await event.respond("❌ این فاکتور برای پرداخت تتر معتبر نیست.")
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
                # PATCH (P2-3 §17.3): جزئیات exception شبکه/درگاه فقط در لاگ
                # سرور؛ به کاربر پیام generic فارسی.
                print(f"❌ [trx_hash] verify error: {type(e).__name__}: {e}")
                ok, msg = False, "خطا در بررسی تراکنش — کمی بعد دوباره امتحان کن"
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
            # v2.22.0 (OWNER-REQUEST): افزودن به لیستِ چندچتی — گامِ ۱:
            # یوزرنیم/لینک/آیدیِ عددی با resolve زنده (چتِ پیدا‌نشده هرگز
            # ذخیره نمی‌شود)؛ گامِ ۲ (فقط چتِ خصوصیِ بدونِ یوزرنیم): لینکِ
            # دعوت. سقف و تکراری‌بودن قبل از تأیید چک می‌شود.
            data = data or {}
            if data.get("phase") == "invite":
                link = (text or "").strip()
                # v2.22.1 (AUDIT-39/b#3 + e#1): فقط لینکِ دعوتِ واقعی پذیرفته
                # می‌شود — قبلاً هر URLای که «t.me» در آن بود (حتی
                # evil.com/?t.me/x یا لینکِ کانالِ عمومیِ دیگر) می‌گذشت؛ لینکِ
                # عمومیِ اشتباه = کارتِ گیتِ غلط = قفلِ دائمیِ کاربران.
                s = link
                for _pref in ("https://", "http://"):
                    if s.lower().startswith(_pref):
                        s = s[len(_pref):]
                        break
                s = s.strip().rstrip("/")
                if not re.fullmatch(
                        r"(?:t\.me|telegram\.me)/(?:\+[A-Za-z0-9_-]{3,}|"
                        r"joinchat[/][A-Za-z0-9_-]{3,})",
                        s, re.IGNORECASE):
                    await event.respond(
                        "❌ این یک لینکِ دعوتِ گروه نیست. لینکِ دعوت را بفرست "
                        "(مثل `https://t.me/+AbCdEf` یا `t.me/joinchat/...`):"
                    )
                    return True
                data["l"] = f"https://{s}"
                self.wizards[event.sender_id] = {
                    "state": WIZ_SET_CHANNEL, "data": data, "_ts": time.time(),
                }
                await event.respond(
                    f"✅ **گروهِ خصوصی:**\n\n"
                    f"👥 {data.get('t') or data.get('u')}\n"
                    f"🔗 {link}\n\n"
                    "این گروه به لیستِ عضویتِ اجباری اضافه شود؟ از این به بعد"
                    " همه (به‌جز ادمین اصلی) باید عضوِ همهٔ چت‌های لیست باشند.",
                    buttons=[
                        [UI.confirm("بله، اضافه کن", b"channel_confirm_save")],
                        [UI.neutral("نه، دوباره بفرستم", "owner_channel_set")],
                    ],
                )
                return True
            # گامِ ۱ — resolve زندهٔ چت
            ok, info, norm, needs_invite = await self._resolve_channel(text)
            if not ok:
                await event.respond(
                    f"❌ چت «{text.strip()}» پیدا نشد یا قابلِ دسترسی نیست ({info}).\n\n"
                    "یوزرنیم/لینکِ درست را بفرست — یا برای گروهِ خصوصی، آیدیِ"
                    " عددی‌اش را (ربات باید عضوِ گروه باشد):"
                )
                return True
            existing = {c["u"].lower().lstrip("@")
                        for c in get_required_chats()}
            # v2.22.1 (AUDIT-39/b#8): dedupe بر اساسِ هویتِ entity — چتی که
            # با آیدیِ عددی ذخیره شده، اگر با یوزرنیمِ عمومی‌اش دوباره
            # اضافه شود، قبلاً رد نمی‌شد و دو ورودیِ هم‌مقصد می‌ساخت (برعکسش
            # گرفته می‌شد). آیدیِ entityِ چتِ تازه با آیدی‌هایِ موجود مقایسه
            # می‌شود (resolve دوباره ارزان است — entity کش می‌شود).
            try:
                _new_ent = await self._chat_entity(norm)
                _new_eid = abs(int(getattr(_new_ent, "id", 0) or 0))
            except Exception:
                _new_eid = 0
            if norm.lower() in existing:
                await event.respond(
                    "⚠️ این چت از قبل در لیست هست.",
                    buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                )
                return True
            if _new_eid:
                for c in get_required_chats():
                    if not c["u"].lstrip("-").isdigit():
                        continue
                    try:
                        _e2 = await self._chat_entity(c["u"])
                        if abs(int(getattr(_e2, "id", 0) or 0)) == _new_eid:
                            await event.respond(
                                "⚠️ این چت از قبل در لیست هست "
                                "(با آیدیِ عددی ذخیره شده).",
                                buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                            )
                            return True
                    except Exception:
                        continue
            if len(existing) >= REQUIRED_CHATS_MAX:
                await event.respond(
                    f"⚠️ لیست پر است (سقف: {fa_digits(REQUIRED_CHATS_MAX)} چت). "
                    "اول یکی را از صفحهٔ کانال‌ها حذف کن.",
                    buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                )
                return True
            if needs_invite:
                self.wizards[event.sender_id] = {
                    "state": WIZ_SET_CHANNEL,
                    "data": {"phase": "invite", "u": norm, "t": info, "l": ""},
                    "_ts": time.time(),
                }
                await event.respond(
                    f"✅ **گروهِ خصوصی پیدا شد:** {info}\n\n"
                    "این گروه یوزرنیمِ عمومی ندارد؛ برای اینکه کاربران بتوانند"
                    " عضو شوند، **لینکِ دعوتِ گروه** را بفرست (مثل"
                    " `https://t.me/+AbCdEf` یا `t.me/joinchat/...`):",
                    buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                )
                return True
            self.wizards[event.sender_id] = {
                "state": WIZ_SET_CHANNEL, "data": {"u": norm, "t": info, "l": ""},
                "_ts": time.time(),
            }
            await event.respond(
                f"✅ **چت پیدا شد:**\n\n"
                f"📢 {info}\nhttps://t.me/{norm}\n\n"
                "این چت به لیستِ عضویتِ اجباری اضافه شود؟ از این به بعد همه "
                "(به‌جز ادمین اصلی) باید عضوِ همهٔ چت‌های لیست باشند.",
                buttons=[
                    [UI.confirm("بله، اضافه کن", b"channel_confirm_save")],
                    [UI.neutral("نه، دوباره بفرستم", "owner_channel_set")],
                ],
            )
            return True

        if state == WIZ_TRIAL_DAYS:
            # v2.22.0 (OWNER-REQUEST): تعدادِ روزهایِ دورهٔ آزمایشی — pop
            # فقط بعد از اعتبارسنجی (الگوی v2.19.4: پیامِ خطا ویزارد را
            # نمی‌سوزاند و کاربر بدونِ شروعِ دوباره تصحیح می‌کند).
            raw = (text or "").strip()
            s = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            # v2.22.1 (AUDIT-39/b#7 + e#8): isdecimal به‌جای isdigit —
            # «²».isdigit() هم True است ولی int() رویش ValueError می‌دهد و
            # ویزارد با خطای عمومی می‌سوخت؛ isdecimal فقط رقم‌های واقعی.
            if not s.isdecimal():
                await event.respond(
                    f"❌ فقط یک عدد بفرست (بین {fa_digits(TRIAL_DAYS_MIN)} و"
                    f" {fa_digits(TRIAL_DAYS_MAX)}):"
                )
                return True
            days = int(s)
            if not (TRIAL_DAYS_MIN <= days <= TRIAL_DAYS_MAX):
                await event.respond(
                    f"❌ عدد باید بین {fa_digits(TRIAL_DAYS_MIN)} و"
                    f" {fa_digits(TRIAL_DAYS_MAX)} باشد. دوباره بفرست:"
                )
                return True
            self.wizards.pop(event.sender_id, None)
            set_setting(TRIAL_DAYS_SETTING, str(days), actor_id=event.sender_id)
            log_action(event.sender_id, "trial_days_set", f"days={days}")
            await self._owner_show_trial_settings(event)
            return True

        if state == WIZ_SELF_BACKUP_GROUP:
            # v2.22.0 (OWNER-REQUEST): گروهِ مقصدِ بکاپِ ساعتیِ سلف — آیدیِ
            # عددی یا فورواردِ پیام از خودِ گروه (آیدی از رویِ فوروارد
            # خوانده می‌شود). resolve زنده قبل از ذخیره — گروهِ پیدا‌نشده
            # هرگز ذخیره نمی‌شود.
            raw = (text or "").strip()
            fwd = getattr(event.message, "fwd_from", None)
            fwd_chat = getattr(fwd, "chat_id", None) if fwd else None
            if fwd_chat:
                candidate = str(int(fwd_chat))
            else:
                s = raw.replace(" ", "")
                if not s.lstrip("-").isdigit():
                    await event.respond(
                        "❌ آیدیِ عددیِ گروه را بفرست (مثل `-1001234567890`) یا"
                        " یک پیام از خودِ گروه را **فوروارد** کن:"
                    )
                    return True
                candidate = s
            try:
                entity = await self.client.get_entity(int(candidate))
                title = getattr(entity, "title", None) or candidate
            except Exception as e:
                await event.respond(
                    f"❌ گروه پیدا نشد ({str(e)[:60]}).\n\n"
                    "⚠️ ربات باید عضوِ گروه باشد — ربات را به گروه اضافه کن،"
                    " یک پیام در گروه بفرست و دوباره تلاش کن:"
                )
                return True
            self.wizards[event.sender_id] = {
                "state": WIZ_SELF_BACKUP_GROUP,
                "data": {"group": int(candidate), "title": title},
                "_ts": time.time(),
            }
            await event.respond(
                f"✅ **گروه پیدا شد:**\n\n"
                f"👥 {title}\nآیدی: `{candidate}`\n\n"
                "بکاپِ ساعتیِ سشن‌های سلف به این گروه ارسال شود؟ (هر ساعت"
                " در سرِ ساعت، یک فایلِ فقط-سشنِ رمزگذاری‌شده)",
                buttons=[
                    [UI.confirm("بله، ذخیره کن", b"self_backup_confirm_save")],
                    [UI.neutral("نه، دوباره بفرستم", "owner_self_backup_set")],
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
            self.wizards[event.sender_id] = {"state": WIZ_DEDICATED_OWNER_ID, "data": data,
                                             "_ts": time.time()}
            await event.respond(
                "✅ توکن معتبر است. حالا **آیدی عددی** کسی که می‌خوای مالک ربات "
                "اختصاصی باشه رو بفرست (مثلاً `123456789` — از @userinfobot می‌تونی "
                "بگیری):",
                buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
            )
            return True

        if state == WIZ_DEDICATED_OWNER_ID:
            # v2.13.1 (TEST-G5-DEDICATED / EDGE): قبلاً
            # text.strip().lstrip("-").isdigit() بود که ورودیِ «-123» را
            # می‌پذیرفت (lstrip("-") → «123» → isdigit True)، بعد
            # int("-123") = -123 به‌عنوان owner_id ثبت می‌شد. آیدیِ تلگرامِ
            # کاربر همیشه عددی مثبت است (چت‌های گروه/کانال آیدیِ منفی دارند
            # که مالکِ ربات اختصاصی نمی‌توانند باشند). حالا فقط اعدادِ مثبت.
            _raw_oid = text.strip()
            if not _raw_oid.isdigit() or int(_raw_oid) <= 0:
                await event.respond("❌ آیدی عددی معتبر نیست. فقط یک عدد مثبت بفرست (مثلاً `123456789`):")
                return True
            owner_id = int(_raw_oid)
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
            # v2.14.2 (P2-10 / §20.10): pop فقط بعد از اعتبارسنجی ورودی —
            # قبلاً pop اولِ branch بود و خطای «عدد بفرست» حالتِ ویزارد را
            # می‌سوزاند (کاربر برای تلاش مجدد باید کل جریان تمدید را از نو
            # شروع می‌کرد). مسیر «ربات پیدا نشد» (غیرقابلِ retry) همان‌جا
            # pop می‌شود.
            bot_id = data["bot_id"]
            b = get_dedicated_bot(bot_id)
            if not b:
                self.wizards.pop(event.sender_id, None)
                await event.respond("❌ این ربات اختصاصی پیدا نشد.")
                return True
            try:
                days = int(text.strip())
                assert days > 0
            except (ValueError, AssertionError):
                await event.respond("❌ یک عدد صحیح مثبت (تعداد روز) بفرست:")
                return True
            self.wizards.pop(event.sender_id, None)
            old_expire = _parse_date(b["expire_date"]) if b.get("expire_date") else datetime.now(timezone.utc)
            new_expire = _format_date(max(old_expire, datetime.now(timezone.utc)) + timedelta(days=days))
            # v2.13.1 (TEST-G5-DEDICATED / G5-LOGIC): تمدیدِ یک رباتِ
            # revoked باید وضعیت را به «stopped» برگرداند تا کاربر بتواند
            # با dedicated_toggle آن را restart کند. قبلاً update فقط
            # expire_date را ست می‌کرد و status روی «revoked» می‌ماند.
            # اما پیامِ toggle روی revoked می‌گفت: «برای فعال‌سازی دوباره
            # باید تمدید کنید». این یعنی کاربر تمدید می‌کرد ولی باز هم
            # toggle می‌گفت «منقضی شده» — تجربه‌ی کاربری متناقض. حالا
            # تمدید، وضعیت revoked را به stopped تغییر می‌دهد تا toggle
            # بتواند spawn کند. (active/stopped بدون تغییر می‌مانند.)
            _new_status = "stopped" if b["status"] == "revoked" else b["status"]
            _was_revoked = b["status"] == "revoked"
            update_dedicated_bot_status(bot_id, _new_status, expire_date=new_expire)
            log_action(event.sender_id, "dedicated_bot_extended",
                       f"bot#{bot_id} +{days} روز (status: {b['status']}→{_new_status})")
            await self._notify_owner(
                f"➕ **ربات اختصاصی تمدید شد**\n"
                f"ربات: #{bot_id} | +{days} روز | انقضای جدید: {new_expire} | "
                f"توسط: `{event.sender_id}`"
                + (f"\n♻️ وضعیت از revoked به stopped تغییر یافت — اکنون از طریق «اجرای دوباره» قابل restart است." if _was_revoked else "")
            )
            await event.respond(
                f"✅ ربات اختصاصی #{bot_id} به مدت {days} روز تمدید شد (انقضا: {new_expire})."
                + ("\n\n♻️ چون revoked بود، اکنون روی «stopped» است. برای فعال‌سازی، «اجرای دوباره» را بزن." if _was_revoked else ""),
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

        # v2.15.0: WIZ_ANNOUNCE / WIZ_ANNOUNCE_CONFIRM حذف شدند —
        # announce feature حالا بدون wizard کار می‌کند (در message_h).

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
            # PATCH (TEST-G2-USERMGMT FIX#1): قبلاً wizards.pop در همان
            # ابتدای handler صدا زده می‌شد → اگر کاربر ورودی نامعتبر (مثل
            # «abc» یا عدد منفی) می‌فرستاد، wizard از بین می‌رفت و کاربر
            # برای تلاشِ مجباً مجبور بود به پنل مدیریت برگردد و دوباره
            # دکمه‌ی «تمدید اشتراک» را بزند (silent no-op روی retry). حالا
            # pop فقط بعد از عبورِ موفق از validation انجام می‌شود تا
            # کاربر بتواند همان‌جا عدد دیگری بفرستد. در صورت‌های hard
            # failure (مثل reseller_scope mismatch) هم pop انجام می‌شود
            # چون تلاشِ مجباً روی همان target بی‌فایده است.
            target_user_id = data["target_user_id"]
            back_data = data["back_data"]
            reseller_scope = data.get("reseller_scope")
            if reseller_scope is not None:
                customer_ids = {u["user_id"] for u in list_users_for_reseller(reseller_scope)}
                if target_user_id not in customer_ids:
                    self.wizards.pop(event.sender_id, None)
                    await event.respond("⛔ این کاربر مشتری تو نیست.")
                    return True
            try:
                days = int(text.strip())
                assert days > 0
            except (ValueError, AssertionError):
                # ویزارد زنده می‌ماند — کاربر می‌تواند عدد دیگری بفرستد.
                await event.respond("❌ یک عدد صحیح مثبت (تعداد روز) بفرست:")
                return True
            self.wizards.pop(event.sender_id, None)
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
        # v2.23.1 (AUDIT-43 #5): فعالیت → تمدید TTL (رسیدِ عکسِ کارت‌به‌کارت
        # اغلب دیرتر از ۳۰ دقیقه‌ی پنجره‌ی اولیه می‌رسد — پنجره‌ی پرداخت
        # خودِ سفارش ۲۴ ساعت است).
        wiz["_ts"] = time.time()
        upsert_user(event.sender_id, event.sender.username if event.sender else None)
        # receipt_ref یک مرجع قابل‌بازیابی به خودِ پیام است (chat_id:message_id)
        # نه صرفاً event.photo.id که به‌تنهایی برای دانلود مجدد کافی نیست.
        receipt_ref = f"{event.chat_id}:{event.message.id}"
        photo_bytes = None
        try:
            photo_bytes = await event.download_media(bytes)
        except Exception:
            photo_bytes = None
        if photo_bytes:
            receipt_file_uid = hashlib.sha256(photo_bytes).hexdigest()
        else:
            _pid = getattr(getattr(event, "photo", None), "id", None) or f"{event.chat_id}:{event.message.id}"
            receipt_file_uid = f"tgphoto:{_pid}"
        order_no = ""
        if data.get("order_id"):
            order = get_order(data["order_id"])
            if order and order["user_id"] == event.sender_id \
                    and order["status"] == ORDER_STATUS_PENDING:
                order_no = order["order_no"]
        try:
            pay_id = create_payment(
                event.sender_id, data["plan"], data["amount"],
                receipt_ref, receipt_file_uid=receipt_file_uid
            )
        except ValueError as _ve:
            await event.respond(f"❌ {_ve}")
            return True
        if data.get("order_id") and order_no:
            set_order_payment_id(
                data["order_id"], pay_id,
                user_id=event.sender_id, receipt_file_uid=receipt_file_uid
            )
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
                    # v2.12.10 (QA2-USER C8 / AUDIT-10-C C1): قبل از انقضای
                    # واقعی، اگه auto-renewal فعاله و کیف پول کافیه، اشتراک رو
                    # خودکار تمدید کن. قبلاً این قابلیت در README تبلیغ می‌شد
                    # ولی هیچ scheduler ای صداش نمی‌زد.
                    try:
                        if get_auto_renew_enabled(sub["user_id"]):
                            _rn = auto_renew_subscription(sub["user_id"])
                            if _rn.get("renewed"):
                                try:
                                    await self.client.send_message(
                                        sub["user_id"],
                                        f"🔄 اشتراک شما به‌صورت خودکار تمدید شد!\n\n"
                                        f"🧾 پلن: {_rn.get('plan', '?')}\n"
                                        f"📅 مدت: {_rn.get('days', 0)} روز\n"
                                        f"💰 موجودی باقی‌مانده: {_rn.get('balance', 0):,} تومان\n\n"
                                        f"SelfBot شما روشن می‌ماند.",
                                    )
                                except Exception:
                                    pass
                                continue  # تمدید شد — به expire_subscription نرو
                            else:
                                # تمدید ناموفق (مثلاً موجودی کم) — به کاربر اطلاع بده
                                _reason = _rn.get("reason", "unknown")
                                try:
                                    if _reason == "insufficient_balance":
                                        await self.client.send_message(
                                            sub["user_id"],
                                            "⚠️ تمدید خودکار ناموفق بود — موجودی کیف پول کافی نیست.\n"
                                            "برای جلوگیری از توقف سلف، کیف پولت رو شارژ کن یا دستی تمدید کن.",
                                        )
                                except Exception:
                                    pass
                                # fall through به انقضای معمولی
                    except Exception as _e:
                        print(f"⚠️ [expiry_loop] auto_renew check failed uid={sub['user_id']}: {_e}")
                        # fall through به انقضای معمولی
                    expire_subscription(sub["id"])
                    # رفتار واقعی با پیام هماهنگ است: سلف‌بات متوقف و
                    # disabled می‌شود (نه حذف) — تنظیمات و سشن‌ها حفظ می‌شوند
                    # و بعد از تمدید به‌طور خودکار دوباره فعال می‌شود.
                    try:
                        await self._stop_and_disable_user_selfbots(sub["user_id"])
                    except Exception:
                        pass
                    # v1.8.0: پیام هشدار انقضا با پیشنهاد تمدید (طبق درخواست)
                    try:
                        await self.client.send_message(
                            sub["user_id"],
                            "❌ **اشتراک شما منقضی شد**\n\n"
                            "SelfBot شما متوقف شد. تنظیمات و سشن‌هایت حفظ "
                            "شده‌اند، اما اگر تا **۳ روز** دیگر تمدید نکنید، "
                            "اکانت شما از سرور حذف خواهد شد.\n\n"
                            "💡 برای تمدید، از منوی اصلی «🛒 خرید سلف» رو بزنید.\n"
                            "⚠️ بعد از حذف، تمام اطلاعات شما (اکانت‌ها، تنظیمات، "
                            "لاگ‌ها) از سرور پاک می‌شود و قابل بازیابی نیست.",
                        )
                    except Exception:
                        pass

                # v1.8.0: حذف خودکار اکانت‌هایی که 3 روز از انقضایشان گذشته
                # (طبق درخواست کاربر: «بعد از سه روز از سرور حذفش کن»)
                await self._cleanup_long_expired_users(grace_days=3)

                await self._sweep_expired_dedicated_bots()

                # فاکتورهای در انتظاری که انقضایشان گذشته → باطل + اطلاع
                # v2.12.10 (QA2-USER C10 / AUDIT-10-C M2): قبلاً هر فاکتورِ
                # pending بعد از ۲۴ ساعت منقضی می‌شد، حتی اگه کاربر عکسِ رسید
                # رو آپلود کرده بود ولی OWNER هنوز تایید نکرده بود. این یعنی
                # کاربر پول داده ولی فاکتور باطل می‌شد. حالا اگه payment_id
                # ست شده (یعنی رسید آپلود شده و در صفِ بررسی OWNER است)،
                # انقضا رو ۷ روز اکستند می‌کنیم به‌جای باطل کردن. فقط فاکتورهای
                # بدون رسید (که کاربر کلاً پرداخت نکرده) بعد از ۲۴ ساعت باطل
                # می‌شن.
                # v2.12.11 (QA3-QUICK BUG#2): v2.12.10 بدون cap بود → هر ۷ روز
                # دوباره اکستند می‌شد و فاکتور هیچ‌وقت باطل نمی‌شد. حالا حداکثر
                # ۳ اکستند (۳×۷=۲۱ روز) مجاز است. بعد از اون، فاکتور واقعاً
                # باطل می‌شه.
                _EXTEND_SECONDS = 7 * 24 * 3600  # 7 روز
                _MAX_EXTENSIONS = 3
                _now_ts = _now()
                for order in list_expired_orders():
                    # اگه رسید آپلود شده (payment_id ست) و هنوز زیر cap، اکستند
                    if order.get("payment_id"):
                        _ext_count = int(order.get("extensions_applied") or 0)
                        if _ext_count < _MAX_EXTENSIONS:
                            try:
                                with _conn() as c:
                                    c.execute(
                                        "UPDATE orders SET expires_at = ?, "
                                        "extensions_applied = extensions_applied + 1 "
                                        "WHERE id = ? AND status = 'pending'",
                                        (_now_ts + _EXTEND_SECONDS, order["id"]),
                                    )
                                    c.commit()
                                print(f"⏰ [expiry_loop] فاکتور {order['order_no']} انقضاش اکستند شد "
                                      f"(رسید آپلود شده، اکستند {_ext_count + 1}/{_MAX_EXTENSIONS})")
                                try:
                                    await self.client.send_message(
                                        order["user_id"],
                                        f"⏰ فاکتور `{order['order_no']}` هنوز در صفِ بررسیِ "
                                        f"مدیریت است. ۷ روز به انقضای فاکتور اضافه شد "
                                        f"({fa_digits(_ext_count + 1)}/{fa_digits(_MAX_EXTENSIONS)}). "
                                        f"پس از تایید، اشتراک شما فعال می‌شود.",
                                    )
                                except Exception:
                                    pass
                                continue
                            except Exception as _e:
                                print(f"⚠️ [expiry_loop] extend failed for {order['order_no']}: {_e}")
                                # fall through به expire
                        else:
                            # به سقف اکستند رسیدیم — فاکتور رو واقعاً باطل کن
                            print(f"⏰ [expiry_loop] فاکتور {order['order_no']} به سقف اکستند "
                                  f"({_MAX_EXTENSIONS}×7 روز) رسید — باطل می‌شه")
                    # وگرنه: فاکتور بدون رسید یا بعد از سقف اکستند → باطل
                    expire_order(order["id"])
                    try:
                        await self.client.send_message(
                            order["user_id"],
                            f"⏳ فاکتور `{order['order_no']}` منقضی شد و باطل شد. "
                            "برای خرید دوباره از «🛒 خرید سلف» اقدام کن.",
                        )
                    except Exception:
                        pass

                # PATCH (v2.0.12): trim جدولِ logs هر ۲۴ ساعت. قبلاً این
                # جدول فقط نوشته می‌شد و هرگز خونده یا trim نمی‌شد → در ۱ سال
                # ۱۰۰M رکورد قابل تصور بود. حالا رکوردهای قدیمی‌تر از ۹۰ روز
                # هر ساعت چک و حذف می‌شن (یه round ساده).
                try:
                    with _conn() as c:
                        c.execute(
                            "DELETE FROM logs WHERE created_at < datetime('now', '-90 days')"
                        )
                        # v2.12.23 (QA10-STABILITY BUG#4): trim سایر جدول‌ها
                        # که قبلاً بدون محدودیت رشد می‌کردن.
                        c.execute(
                            "DELETE FROM wallet_transactions WHERE created_at < datetime('now', '-365 days')"
                        )
                        c.execute(
                            "DELETE FROM orders WHERE status IN ('expired', 'cancelled') "
                            "AND created_at < datetime('now', '-90 days')"
                        )
                        c.execute(
                            "DELETE FROM payments WHERE status IN ('rejected') "
                            "AND created_at < datetime('now', '-90 days')"
                        )
                        c.execute(
                            "DELETE FROM subscriptions WHERE status = 'expired' "
                            "AND expire_date < datetime('now', '-30 days')"
                        )
                        # broadcasts table اگر وجود داره
                        # FIX (TEST-G8-G10-MISSING #1): ستون created_at روی
                        # broadcasts وجود ندارد — schema فقط sent_at دارد
                        # (ببین lines 259-268). قبلاً این DELETE همیشه
                        # OperationalError می‌داد و توسط except pass زیر
                        # می‌شد → trim واقعاً هیچ‌وقت اجرا نمی‌شد. حالا روی
                        # ستونِ درست (sent_at) کار می‌کند.
                        try:
                            c.execute(
                                "DELETE FROM broadcasts WHERE sent_at < datetime('now', '-90 days')"
                            )
                        except Exception:
                            pass  # table ممکنه وجود نداشته باشه
                        # PATCH (v2.5.1): c.connection.commit() نادرست بود.
                        c.commit()
                except Exception as e:
                    print(f"⚠️ [saas_bot] trim DB tables ناموفق (بی‌ضرر): {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ [saas_bot] خطا در expiry_loop: {e}")
                await asyncio.sleep(60)

    async def _cleanup_long_expired_users(self, grace_days: int = 3):
        """
        v1.8.0: حذف خودکار اکانت‌هایی که بیش از N روز از انقضایشان گذشته.

        طبق درخواست کاربر: «اگر سلفی منقضی شد، خودکار به او پیام بده و
        اگر تمدید نکرد، بعد از سه روز از سرور حذفش کن تا این‌قدر زیاد نشوند.»

        کارهایی که انجام می‌دهد:
        1. پیدا کردن اشتراک‌هایی که status=expired و expire_date بیش از
           grace_days روز قبل بوده.
        2. توقف و غیرفعال‌سازی سلف‌بات‌هایشان (اگر هنوز فعال بودن).
        3. حذف session files (فایل‌های .session در sessions/).
        4. حذف اکانت‌هایشان از config.json.
        5. حذف رکوردهایشان از جداول users, subscriptions, tickets.
        6. ارسال پیام آخر «اکانت شما حذف شد» (اگر ممکن باشه).
        """
        import glob as _glob
        import os as _os
        from datetime import datetime, timedelta, timezone as _tz

        cutoff_date = (datetime.now(_tz.utc) - timedelta(days=grace_days)).strftime("%Y-%m-%d")

        # پیدا کردن اشتراک‌های منقضی + کاربرانشون
        with _conn() as c:
            # v2.12.21 (QA7-USER6 BUG#6): قبلاً فقط 'expired' بودن رو چک
            # می‌کرد، ولی کاربری که تمدید کرده (sub1 expired + sub2 active)
            # هم 'expired' داره و حذف می‌شد! حالا فقط کاربرانی که هیچ
            # اشتراکِ active فعلی ندارن حذف می‌شن.
            # v2.12.22 (re-audit): از _now_date() (date-only) استفاده می‌کنیم
            # نه _now() (datetime) — چون expire_date فقط date ذخیره می‌شه
            # و lexicographic comparison با datetime فرمت‌مطابقت نداره.
            # هم از >= استفاده می‌کنیم (نه >) چون در روزِ آخرِ اشتراک،
            # expire_date == today و اشتراک هنوز فعال هست (end-of-day semantic).
            rows = c.execute(
                "SELECT DISTINCT s1.user_id FROM subscriptions s1 "
                "WHERE s1.status = 'expired' AND s1.expire_date < ? "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM subscriptions s2 "
                "  WHERE s2.user_id = s1.user_id "
                "  AND s2.status = 'active' "
                "  AND s2.expire_date >= ?"
                ")",
                (cutoff_date, _now_date()),
            ).fetchall()
        expired_user_ids = [r["user_id"] for r in rows]
        if not expired_user_ids:
            return

        for uid in expired_user_ids:
            try:
                # 1. توقف و disable سلف‌بات‌ها (اگر هنوز فعال بودن)
                try:
                    await self._stop_and_disable_user_selfbots(uid)
                except Exception:
                    pass

                # 2 + 3. محاسبه‌ی tag-های این کاربر، حذف session files و
                # حذف از config.json. PATCH: قبلاً در یک passِ جدا،
                # `glob(sessions/*_{uid}.session)` می‌زد — این pattern با
                # ساختارِ واقعی (`{tag}.session`، نه `{tag}_{uid}.session`)
                # هیچ matchی نداشت؛ یعنی session files هرگز پاک نمی‌شدند. حالا
                # tagها از config استخراج می‌شوند و برای هر tag، فایلِ سشن
                # (با اسمِ واقعی) و رکورد config هم‌زمان حذف می‌شوند. ضمناً
                # شرطِ `or account_is_orphan(...)` حذف شد (PATCH قبلی) تا
                # یتیم‌های سامانه به‌اشتباه پاک نشوند.
                tags_to_remove: list = []
                try:
                    cfg = self.sb.load_config()
                    if cfg and config_state() == CONFIG_VALID:
                        tags_to_remove = [
                            tag for tag, acc in cfg.items()
                            if isinstance(acc, dict)
                            and acc.get("owner_user_id") == uid
                            and not acc.get("provision_source") == PROVISION_MANUAL
                        ]
                except Exception:
                    pass

                # 2. حذف session files (با اسمِ واقعی {tag}.session و
                # snapshot-های احتمالی {tag}.session-journal و {tag}.session-shm
                # و {tag}.session-wal که SQLite ممکن است ساخته باشد).
                if tags_to_remove:
                    try:
                        for tag in tags_to_remove:
                            for suffix in ("", "-journal", "-shm", "-wal"):
                                p = os.path.join(
                                    SESSIONS_DIR, f"{tag}.session{suffix}"
                                )
                                try:
                                    _os.remove(p)
                                except OSError:
                                    pass
                    except Exception:
                        pass

                # 3. حذف از config.json
                try:
                    cfg = self.sb.load_config()
                    if cfg and config_state() == CONFIG_VALID and tags_to_remove:
                        for tag in tags_to_remove:
                            cfg.pop(tag, None)
                        self.sb.save_config(cfg)
                except Exception:
                    pass

                # 4. حذف از دیتابیس — PATCH (audit-6): قبلاً یک DELETE
                # cascade دستیِ ناقص اینجا بود که جدولِ `ticket_messages`
                # (که به `tickets.id` FK دارد) را پاک نمی‌کرد → FK violation
                # → rollbackِ سایلنت → رکوردهای کاربر در saas.db باقی می‌ماند
                # ولی session files و config پاک شده بودند + پیام «حذف شد»
                # به کاربر فرستاده می‌شد. علاوه بر این، `permission_grants`،
                # `dedicated_bots`، و `bot_data.db` هم لمس نمی‌شدند. حالا
                # به‌جای این بلوکِ دستی، از `delete_user_completely_async`
                # استفاده می‌کنیم که قبل از این، Runtimeها را هم متوقف
                # می‌کند و در یک تراکنشِ واحد و اتمیک همه‌ی جداول را
                # (با FK order درست) پاک می‌کند. مرحله‌ی ۱ و ۲ و ۳ بالا
                # هم اکنون اضافی هستند (delete_user_completely_async خودش
                # آن‌ها را انجام می‌دهد) ولی برای اطمینانِ idempotent بودن
                # نگه داشته شدیم.
                try:
                    await delete_user_completely_async(uid)
                except Exception as e:
                    print(f"⚠️ [cleanup] delete_user_completely_async error for uid={uid}: {e}")

                # 5. پیام آخر (اگر بتونه)
                try:
                    await self.client.send_message(
                        uid,
                        "🗑 اکانت شما به دلیل عدم تمدید اشتراک، "
                        f"بعد از {grace_days} روز از سرور حذف شد.\n\n"
                        "تمام اطلاعات شما (اکانت‌ها، تنظیمات، لاگ‌ها) پاک شد.\n"
                        "برای استفاده‌ی مجدد، می‌توانید با /start ربات اکانت جدید بسازید.",
                    )
                except Exception:
                    pass

                print(f"✅ [cleanup] کاربر {uid} بعد از {grace_days} روز انقضا حذف شد.")
            except Exception as e:
                print(f"⚠️ [cleanup] خطا در حذف کاربر {uid}: {e}")

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
            # v2.12.29 (DEEP-9 #9): پوشه‌ی ربات رو پاک کن — قبلاً
            # rmtree نمی‌شد و فایل‌های سشن + دیتابیس روی دیسک می‌موندن
            # (نشتیِ دیسک + امنیتی: فایل سشن حاوی credentials).
            bot_dir = dbot.get("bot_dir")
            if bot_dir and os.path.isdir(bot_dir):
                try:
                    import shutil as _shutil
                    _shutil.rmtree(bot_dir)
                    print(f"✅ [dedicated] bot_dir پاک شد: {bot_dir}")
                except Exception as _re:
                    print(f"⚠️ [dedicated] rmtree({bot_dir}) failed: {_re}")
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
            # v2.17.0 (BLOCK): کاربرِ بلاک‌شده اصلاً وارد نمی‌شود — قبل از
            # دعوت، آزمایشی، گیت کانال و هر منطق دیگری.
            if await self._enforce_block(event.sender_id, event):
                return
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
            # گیت عضویت کانال/گروه‌ها: همه به‌جز ادمین اصلی باید عضوِ همهٔ
            # چت‌هایِ تنظیم‌شده توسط مالک باشند تا بتوانند از ربات استفاده
            # کنند. اگر عضو نباشند، پیام /start او حذف و پیام گیت (کادرهای
            # شیشه‌ای + بررسی عضویت) فرستاده می‌شود.
            if not await self._channel_gate(event.sender_id):
                try:
                    await event.message.delete()
                except Exception:
                    pass
                await self._send_channel_gate_message(event)
                return
            # v2.22.1 (AUDIT-39/d#7): اعطای آزمایشی بعد از گیت — قبلاً قبل
            # از گیت اعطا می‌شد و کاربرِ بیرونِ کانال، روزهایِ آزمایشی‌اش را
            # بی‌استفاده می‌سوزاند. حالا فقط کاربری که از گیت رد شده آزمایشی
            # می‌گیرد؛ کاربرِ گیت‌خورده بعد از عضویت، در مسیرِ «بررسی عضویت»
            # همین اعطا را (idempotent — فقط یک‌بار در طول عمر) می‌گیرد.
            if is_new:
                try:
                    grant_trial_if_eligible(event.sender_id)
                except Exception as e:
                    print(f"⚠️ [trial] اعطای اشتراک آزمایشی ناموفق: {type(e).__name__}: {e}")
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

            # v2.17.0 (BLOCK): کاربرِ بلاک‌شده هیچ پیامی پردازش نمی‌شود
            if await self._enforce_block(event.sender_id, event):
                return

            # v2.15.0: announce feature — بدون wizard
            uid = event.sender_id
            if uid in self._announce_pending:
                text = (event.raw_text or "").strip()
                if not text:
                    await event.respond("❌ متن پیام خالی است. دوباره بفرست:")
                    return
                self._announce_pending.discard(uid)
                self._announce_text[uid] = text
                from telethon import Button
                await event.respond(
                    "**📨 پیش‌نمایش پیام همگانی**\n\n"
                    "این پیام به همه‌ی کاربران (که ربات را start کرده‌اند) ارسال می‌شود:\n\n"
                    f"━━━━━━━━━━━━━━\n{text}\n━━━━━━━━━━━━━━\n\n"
                    "🟡 برای ارسال، دکمه‌ی زیر را بزن.",
                    buttons=[
                        [Button.inline("📨 ارسال به همه", b"announce_send:go")],
                        [Button.inline("انصراف", b"announce_cancel")],
                    ],
                )
                return

            # v2.13.0 (TEST-WIZARD-FLOWS): پاکسازیِ دوره‌ایِ wizardهای قدیمیِ
            # SaaSBot — قبلاً فقط AdminBot.wizards پاک می‌شد (از
            # admin_panel.handle_message صدا زده می‌شد). حالا self.wizards
            # (SaaSBot) هم به‌طور دوره‌ای پاک می‌شه تا wizardهای رها‌شده
            # (pricing، set_card، set_wallet، dedicated_bot_token، license_create،
            # discount_create، set_merchant، announce) نشت نکنن.
            await self._cleanup_stale_wizards()

            # v2.23.1 (AUDIT-43 #5): انقضای TTL دیگر سایلنت نیست — قبل از
            # lookup، ویزاردِ همین کاربر چک می‌شود؛ اگر ۳۰ دقیقه بی‌فعالیت
            # منقضی شده باشد، با پیامِ روشن اطلاع داده می‌شود (GC دوره‌ایِ هر
            # ۵ دقیقه‌ای قبلاً ویزارد را می‌بُرید و پیامِ بعدیِ کاربر — مثلِ
            # رسیدِ پرداخت یا تیکت — بدونِ هیچ واکنشی در fall-through گم می‌شد).
            _wiz_mine = self.wizards.get(event.sender_id)
            if _wiz_mine and (time.time() - _wiz_mine.get("_ts", 0)) > self._WIZARD_TTL_SEC:
                self.wizards.pop(event.sender_id, None)
                _spawn_bg(self._cleanup_wizard_temp_client(_wiz_mine),
                          "wizard_ttl_expire")
                await event.respond(
                    "⏳ فرآیندِ باز به‌دلیلِ ۳۰ دقیقه بی‌فعالیت بسته شد.\n"
                    "لطفاً از منو دوباره شروع کن و این پیام را دوباره بفرست.",
                    buttons=[UI.nav_row(back=False)],
                )
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
                    # v2.22.1 (AUDIT-39/b#4): فورواردِ رسانه‌ای (عکس/فایل) از
                    # گروه، برای ویزاردِ «گروهِ بکاپِ ساعتی» هم مسیرِ متنی
                    # می‌گیرد — قبلاً فقط پیام‌هایِ متنیِ فورواردی کار می‌کردند
                    # و فورواردِ عکس (رایج‌ترین شکلِ پیام در گروه‌ها) سایلنت
                    # بی‌اثر می‌شد. شاخهٔ WIZ_SELF_BACKUP_GROUP آیدی را از
                    # fwd_from می‌خواند و به متن نیاز ندارد.
                    _is_media_fwd = bool(
                        getattr(event.message, "fwd_from", None)
                        and (event.photo or getattr(event, "document", None))
                        and wiz.get("state") == WIZ_SELF_BACKUP_GROUP)
                    if _is_media_fwd:
                        handled = await self._handle_text_wizard(event, wiz)
                    elif event.photo:
                        handled = await self._handle_photo_wizard(event, wiz)
                    elif getattr(event, "document", None):
                        # فایل (مثلاً بکاپ دیتابیس برای بازیابی)
                        handled = await self._handle_document_wizard(event, wiz)
                    else:
                        handled = await self._handle_text_wizard(event, wiz)
                    if handled:
                        return
                except Exception as e:
                    print(f"⚠️ [saas_bot] خطا در ویزارد: {type(e).__name__}: {e}")
                    self.wizards.pop(event.sender_id, None)
                    # v2.19.3 (DIAG · IMG_8254): همین مسیرِ متنی بود که باگِ
                    # «خطایی رخ داد» ریپورتر را پنهان نگه داشت — پیامِ عمومیِ
                    # بدونِ نامِ خطا. حالا همان هشدارِ خود-تشخیصیِ دیسپچرِ
                    # دکمه (v2.19.1) اینجا هم هست: FloodWait پیامِ آرام می‌گیرد
                    # و OWNER نامِ خطا + جزئیاتِ کوتاهش را می‌بیند؛ فقط «base»
                    # پیام‌محور است چون اینجا دکمه‌ای در کار نیست.
                    try:
                        _own = False
                        try:
                            _own = self._role(event.sender_id) == ROLE_OWNER
                        except Exception:
                            pass
                        await event.respond(bot_error_alert_text(
                            e, is_owner=_own,
                            base="❌ خطا در پردازش پیامِ شما. دوباره تلاش کن."))
                    except Exception:
                        pass
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
            # v2.17.0 (BLOCK): هیچ دکمه‌ای برای کاربرِ بلاک‌شده کار نمی‌کند
            if await self._enforce_block(uid, event, role=role):
                return
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
                # v1.8.0: تب‌های جدید پنل ادمین
                if data == "admin_back_to_hub" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._show_admin_hub(event, role)
                    return
                if data.startswith("admin_tab_") and role in (ROLE_OWNER, ROLE_ADMIN):
                    tab = data[len("admin_tab_"):]
                    await self._show_admin_tab(event, tab, role)
                    return
                if data.startswith("users_section_") and role in (ROLE_OWNER, ROLE_ADMIN):
                    section = data[len("users_section_"):]
                    await self._show_users_section(event, section, role)
                    return
                if data.startswith("user_search_section:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    section = data.split(":", 1)[1]
                    await self._start_section_search(event, section)
                    return
                # v1.9.0: فیکس critical - قبلاً cap_list/cap_add_start/cap_user/cap_grant/cap_revoke
                # فقط در AdminBot.handle_callback بود ولی وقتی SaaSBot می‌فرسته
                # به admin_panel.handle_callback، این متدها روی instance خودش
                # فراخوانی می‌شد (AdminBot) و چون توابع در SaaSBot تعریف شدن،
                # AttributeError می‌داد و کاربر ارور «خطا در پردازش» می‌دید.
                if data == "cap_list" and role == ROLE_OWNER:
                    await self._owner_show_capability_list(event)
                    return
                if data == "cap_add_start" and role == ROLE_OWNER:
                    await self._owner_start_capability_add(event)
                    return
                if data.startswith("cap_user:") and role == ROLE_OWNER:
                    uid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_show_capability_user(event, uid)
                    return
                if data.startswith("cap_choose_scope:") and role == ROLE_OWNER:
                    uid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_choose_capability_scope(event, uid)
                    return
                if data.startswith("cap_confirm:") and role == ROLE_OWNER:
                    _, uid, scope = data.split(":", 2)
                    await self._owner_confirm_capability(event, safe_callback_int(uid, 0), scope)
                    return
                if data.startswith("cap_grant:") and role == ROLE_OWNER:
                    _, uid, scope = data.split(":", 2)
                    await self._owner_grant_capability(event, safe_callback_int(uid, 0), scope)
                    return
                if data.startswith("cap_revoke:") and role == ROLE_OWNER:
                    _, uid, scope = data.split(":", 2)
                    await self._owner_revoke_capability(event, safe_callback_int(uid, 0), scope)
                    return
                # v2.13.1 (TEST-G5-DEDICATED / DED-5 fix-complete): قبلاً
                # فقط cap_list/cap_add_start/cap_user/cap_grant/cap_revoke
                # از SaaSBot.handle_callback روت شده بودند (فیکس v1.9.0).
                # اما dbcap:/dbcap_grant:/dbcap_revoke: که از صفحه‌ی جزئیاتِ
                # ربات اختصاصی (دکمه‌ی «🔐 مجوز امنیت اکانت») صدا زده می‌شوند،
                # در این شاخه نبودند. در نتیجه به admin_panel.handle_callback
                # می‌رسیدند و آنجا به self._owner_show_dbot_capability و
                # هم‌خانواده‌هایش روی instanceِ AdminBot سوار می‌شدند. متدها
                # فقط روی SaaSBot تعریف شده‌اند → AttributeError → کاربر
                # «❌ خطا در پردازش این دکمه» می‌دید. حالا در همین شاخه
                # (SaaSBot) روت می‌شوند تا روی instanceِ درست فراخوانی شوند.
                if data.startswith("dbcap:") and role == ROLE_OWNER:
                    bot_id = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_show_dbot_capability(event, bot_id)
                    return
                if data.startswith("dbcap_grant:") and role == ROLE_OWNER:
                    bot_id = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_grant_dbot_capability(event, bot_id)
                    return
                if data.startswith("dbcap_revoke:") and role == ROLE_OWNER:
                    bot_id = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_revoke_dbot_capability(event, bot_id)
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
                # v2.0: سربرگ‌های بخش‌های پنل ادمین (Ⅰ..Ⅴ) — فقط نمایشی،
                # کلیک بی‌اثر، اما اگه کلاینت کلیک کنه ما فقط پنل رو
                # دوباره رندر می‌کنیم تا کاربر حس کنه «اتفاقی افتاد».
                if data.startswith("hdr:"):
                    await event.answer()
                    await self._show_admin_hub(event, role)
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
                        # v2.22.1 (AUDIT-39/d#7): کاربرِ گیت‌خورده‌ای که حالا
                        # عضو شده، آزمایشی‌اش را همین‌جا می‌گیرد (اگر سهمش
                        # نبود — اعطا idempotent است و فقط یک‌بار در طول عمر
                        # اتفاق می‌افتد؛ در /start دیگر به دستش نمی‌رسید).
                        try:
                            grant_trial_if_eligible(event.sender_id)
                        except Exception:
                            pass
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
                        # v2.22.1: بازخوردِ فوریِ کلیک (پیامِ گیتِ رد شده با
                        # edit روی همان پیام رندر می‌شود و بدونِ answer، چرخشِ
                        # loading در کلاینت می‌ماند).
                        try:
                            await event.answer()
                        except Exception:
                            pass
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
                    # v2.22.0: افزودن به لیستِ چندچتی (کلید‌های ویزارد:
                    # u/t/l). تکراری و سقفِ ۱۰ چت اینجا هم چک می‌شود —
                    # دفاعِ دوم بعد از ویزارد.
                    # v2.22.1 (AUDIT-39/b#5): اعتبارسنجی قبل از pop — قبلاً
                    # ویزارد اول pop می‌شد و در شاخهِٔ «تکراری/سقف» داده‌ها
                    # می‌سوخت و کاربر باید کل جریان را از نو تایپ می‌کرد؛
                    # شاخهٔ سقف هم صفحه را دوباره رندر نمی‌کرد.
                    wiz = self.wizards.get(event.sender_id) or {}
                    wd = (wiz or {}).get("data", {}) or {}
                    u = (wd.get("u") or "").strip()
                    if not u:
                        self.wizards.pop(event.sender_id, None)
                        await event.answer("چتی در انتظار تایید نیست.", alert=True)
                        return
                    chats = get_required_chats()
                    if any(c["u"].lower().lstrip("@") == u.lower().lstrip("@")
                           for c in chats):
                        self.wizards.pop(event.sender_id, None)
                        await event.answer("⚠️ این چت از قبل در لیست هست.", alert=True)
                        await self._owner_show_channel_settings(event)
                        return
                    if len(chats) >= REQUIRED_CHATS_MAX:
                        await event.answer(
                            f"⚠️ سقفِ {fa_digits(REQUIRED_CHATS_MAX)} چت پر است.",
                            alert=True)
                        await self._owner_show_channel_settings(event)
                        return
                    self.wizards.pop(event.sender_id, None)
                    chats.append({"u": u, "t": (wd.get("t") or "").strip(),
                                  "l": (wd.get("l") or "").strip()})
                    set_required_chats(chats)
                    self._reset_gate_state()
                    log_action(event.sender_id, "required_chat_added", f"u={u}")
                    await event.answer("✅ چت به لیست اضافه شد.")
                    await self._owner_show_channel_settings(event)
                    return
                if data.startswith("channel_remove:") and role == ROLE_OWNER:
                    # v2.22.0: حذفِ یک چت از لیست. v2.22.1 (AUDIT-39/b#6 +
                    # e#7): callback علاوه بر ایندکس، «هویت» چت (u) را هم
                    # حمل می‌کند — کلیک روی صفحهٔ کهنه (لیستِ تغییرکرده)
                    # دیگر بی‌صدا چتِ اشتباه را حذف نمی‌کند؛ یا همان چت را
                    # (اگر جابه‌جا شده) حذف می‌کند یا هشدارِ تازگیِ صفحه می‌دهد.
                    _parts = data.split(":", 2)
                    if len(_parts) < 3:
                        await event.answer("❌ فرمت نامعتبر.", alert=True)
                        return
                    try:
                        idx = int(_parts[1])
                    except ValueError:
                        await event.answer("❌ ایندکس نامعتبر.", alert=True)
                        return
                    target_u = _parts[2]
                    chats = get_required_chats()
                    # تطابقِ هویت: اول ایندکس، بعد جست‌وجوی u (جابه‌جاشدگی)
                    if not (0 <= idx < len(chats)) \
                            or chats[idx]["u"] != target_u:
                        target_i = next(
                            (i for i, c in enumerate(chats)
                             if c["u"] == target_u), None)
                        if target_i is None:
                            await event.answer(
                                "⚠️ این چت دیگر در لیست نیست — صفحه را"
                                " دوباره باز کن.", alert=True)
                            await self._owner_show_channel_settings(event)
                            return
                        idx = target_i
                    removed = chats.pop(idx)
                    set_required_chats(chats)
                    self._reset_gate_state()
                    log_action(event.sender_id, "required_chat_removed",
                               f"u={removed.get('u')}")
                    await event.answer("🗑 چت حذف شد.")
                    await self._owner_show_channel_settings(event)
                    return
                if data == "owner_channel_clear" and role == ROLE_OWNER:
                    set_required_chats([])
                    self._reset_gate_state()
                    await event.answer("✅ همهٔ شرط‌های عضویت برداشته شد.")
                    await self._owner_show_channel_settings(event)
                    return
                # ── v2.22.0 (OWNER-REQUEST): صفحهٔ آزمایشی + بکاپِ ساعتی ──
                if data == "owner_trial" and role == ROLE_OWNER:
                    await self._owner_show_trial_settings(event)
                    return
                if data == "owner_trial_days" and role == ROLE_OWNER:
                    await self._start_trial_days_wizard(event)
                    return
                if data == "owner_self_backup" and role == ROLE_OWNER:
                    await self._owner_show_self_backup(event)
                    return
                if data == "owner_self_backup_set" and role == ROLE_OWNER:
                    await self._owner_start_self_backup_set(event)
                    return
                if data == "self_backup_confirm_save" and role == ROLE_OWNER:
                    wiz = self.wizards.pop(event.sender_id, None)
                    grp = (wiz or {}).get("data", {}).get("group")
                    if not grp:
                        await event.answer("گروهی در انتظار تایید نیست.", alert=True)
                        return
                    set_setting(SELF_BACKUP_GROUP_SETTING, str(grp),
                                actor_id=event.sender_id)
                    set_setting(SELF_BACKUP_ENABLED_SETTING, "1",
                                actor_id=event.sender_id)
                    log_action(event.sender_id, "self_backup_group_set",
                               f"group={grp}")
                    await event.answer("✅ گروهِ بکاپِ ساعتی ذخیره شد.")
                    await self._owner_show_self_backup(event)
                    return
                if data == "owner_self_backup_toggle" and role == ROLE_OWNER:
                    if not self_backup_group():
                        await event.answer("اول گروه را تنظیم کن.", alert=True)
                        return
                    new_val = "0" if self_backup_enabled() else "1"
                    set_setting(SELF_BACKUP_ENABLED_SETTING, new_val,
                                actor_id=event.sender_id)
                    log_action(event.sender_id, "self_backup_toggled",
                               f"new={new_val}")
                    try:
                        await event.answer(
                            "🗂 ارسالِ ساعتی: "
                            + ("روشن" if new_val == "1" else "خاموش"))
                    except Exception:
                        pass
                    await self._owner_show_self_backup(event)
                    return
                if data == "owner_self_backup_clear" and role == ROLE_OWNER:
                    set_setting(SELF_BACKUP_GROUP_SETTING, "",
                                actor_id=event.sender_id)
                    log_action(event.sender_id, "self_backup_group_cleared", "")
                    await event.answer("✅ گروهِ بکاپِ ساعتی حذف شد.")
                    await self._owner_show_self_backup(event)
                    return
                # ───────────────────────────────────────────────────────────
                # TEST-G6-SYSTEM (BUG: BROKEN — many spec-named callbacks
                # were entirely missing from the dispatcher. Clicking any
                # of them was a silent no-op. Now: aliases to existing
                # handlers + new owner_announce / announce_send:).
                # ───────────────────────────────────────────────────────────
                # Aliases for the update/version hub.
                if data == "update_status" and role == ROLE_OWNER:
                    await self._show_owner_update(event)
                    return
                if data.startswith("update_check:") and role == ROLE_OWNER:
                    await self._owner_check_update(event)
                    return
                if data.startswith("update_apply:") and role == ROLE_OWNER:
                    await self._owner_apply_update(event)
                    return
                # Aliases for the panel-link hub (actual callback is
                # owner_web_panel — these names are spec-mentioned but
                # had no handler).
                if data == "owner_panel_link" and role == ROLE_OWNER:
                    await self._show_owner_web_panel(event)
                    return
                if data.startswith("panel_link:") and role == ROLE_OWNER:
                    await self._show_owner_web_panel(event)
                    return
                # Alias for the active-admins list (owner_resellers was
                # already added by TEST-G7-RESELLER, but owner_admins
                # was still missing).
                if data == "owner_admins" and role == ROLE_OWNER:
                    await self._owner_show_role_list(event, ROLE_ADMIN)
                    return
                # Alias for the legacy `owner_db_backup_go:` callback —
                # same as `owner_db_backup` (which redirects to
                # `_owner_show_backup`).
                if data == "owner_db_backup_go" and role == ROLE_OWNER:
                    await self._owner_db_backup(event)
                    return
                if data.startswith("owner_db_backup_go:") and role == ROLE_OWNER:
                    await self._owner_db_backup(event)
                    return
                # Aliases for `channel_set:` / `channel_clear:` (parameterized
                # variants — arg is ignored, behavior is the same as
                # `owner_channel_set` / `owner_channel_clear`).
                if data.startswith("channel_set:") and role == ROLE_OWNER:
                    await self._start_channel_set(event)
                    return
                if data.startswith("channel_clear:") and role == ROLE_OWNER:
                    set_required_chats([])
                    self._reset_gate_state()
                    await event.answer("✅ همهٔ شرط‌های عضویت برداشته شد.")
                    await self._owner_show_channel_settings(event)
                    return
                # Generic `setting_save:{key}:{value}` — previously
                # missing entirely. Whitelist keys to prevent a crafted
                # callback from writing arbitrary settings (e.g.
                # `setting_save:admin_password:...`).
                if data.startswith("setting_save:") and role == ROLE_OWNER:
                    _parts = data.split(":", 2)
                    if len(_parts) < 3:
                        await event.answer("❌ فرمت: setting_save:{key}:{value}", alert=True)
                        return
                    _key, _val = _parts[1], _parts[2]
                    _SETTING_SAVE_WHITELIST = {
                        "card_number", "usdt_wallet", "zarinpal_merchant",
                        "zibal_merchant",
                        "pay_zarinpal_enabled", "pay_zibal_enabled",
                        "pay_card_enabled", "pay_trc20_enabled",
                        # v2.22.1 (AUDIT-39/a#3): required_channel و
                        # required_channel_title از لیست حذف شدند — گیتِ
                        # عضویت حالا لیستِ JSONِ ساخت‌یافته (required_chats)
                        # است و نوشتنِ مستقیمِ کلیدِ legacy از پشتِ آن، بعد از
                        # خالی‌کردنِ لیست توسط مالک، گیت را به‌صورتِ خاموش
                        # «احیا» می‌کرد (نه مسیرِ UI و نه شمارشِ سقف). هیچ
                        # دکمه‌ای این کلیدها را از این مسیر نمی‌نویسد.
                    }
                    if _key not in _SETTING_SAVE_WHITELIST:
                        await event.answer(
                            f"⛔ کلید '{_key}' قابل تنظیم از این مسیر نیست.",
                            alert=True,
                        )
                        return
                    set_setting(_key, _val, actor_id=event.sender_id)
                    await event.answer(f"✅ تنظیم شد: {_key}", alert=True)
                    return
                # Announcements — v2.15.0: بدون wizard
                if data == "owner_announce" and role == ROLE_OWNER:
                    await self._owner_start_announce(event)
                    return
                if data == "owner_announce" and role != ROLE_OWNER:
                    await event.answer("⛔ فقط OWNER", alert=True)
                    return
                if data == "announce_cancel" and role == ROLE_OWNER:
                    self._announce_pending.discard(event.sender_id)
                    self._announce_text.pop(event.sender_id, None)
                    await event.answer("❌ لغو شد.")
                    await self._show_admin_tools(event, role)
                    return
                if data.startswith("announce_send:") and role == ROLE_OWNER:
                    await self._owner_announce_send(event)
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
                # PATCH (v2.0.8): آپدیت خودکار و rollback — فقط OWNER
                if data == "owner_update" and role == ROLE_OWNER:
                    await self._show_owner_update(event)
                    return
                if data == "owner_update_check" and role == ROLE_OWNER:
                    await self._owner_check_update(event)
                    return
                if data == "owner_update_apply" and role == ROLE_OWNER:
                    await self._owner_apply_update(event)
                    return
                # PATCH (v2.3.0): auto-update toggle
                if data == "owner_toggle_auto_update" and role == ROLE_OWNER:
                    await self._owner_toggle_auto_update(event)
                    return
                # v2.19.4 (AUDIT-36 H4 — HIGH): سیم‌کشی جاافتاده. متدها از
                # v2.17.0 موجود بودند (با گارد نقشِ داخلیِ کامل) ولی شاخه‌ی
                # دیسپچر هرگز نوشته نشد → هر دو دکمه در «⚙️ تنظیمات سیستم»
                # نمایش داده می‌شدند ولی کلیک = سکوتِ مطلق (نه answer، نه
                # alert) — مالک فکر می‌کرد ربات هنگ کرده.
                if data == "owner_toggle_trial" and role == ROLE_OWNER:
                    await self._owner_toggle_trial(event)
                    return
                if data == "owner_toggle_group_sub" and role == ROLE_OWNER:
                    await self._owner_toggle_group_sub(event)
                    return
                # PATCH (v2.4.0): language toggle
                if data == "owner_toggle_lang" and role == ROLE_OWNER:
                    new_lang = "en" if CIANET_LANG == "fa" else "fa"
                    _set_lang(new_lang)
                    # ذخیره در env file
                    try:
                        _proj_dir = os.path.dirname(os.path.abspath(__file__))
                        _env_file = None
                        for _cand in ["/etc/cianet.env", "/etc/selfbot.env",
                                       os.path.join(_proj_dir, ".env")]:
                            if os.path.exists(_cand):
                                _env_file = _cand
                                break
                        if _env_file:
                            import re as _re
                            with open(_env_file, "r", encoding="utf-8") as _f:
                                _content = _f.read()
                            if _re.search(r"^CIANET_LANG=", _content, _re.MULTILINE):
                                _content = _re.sub(r"^CIANET_LANG=.*$", f"CIANET_LANG={new_lang}", _content, flags=_re.MULTILINE)
                            else:
                                _content = _content.rstrip() + f"\nCIANET_LANG={new_lang}\n"
                            with open(_env_file, "w", encoding="utf-8") as _f:
                                _f.write(_content)
                    except Exception:
                        pass
                    lang_name = "فارسی" if new_lang == "fa" else "English"
                    try:
                        await event.answer(f"🌐 زبان: {lang_name}", alert=True)
                    except Exception:
                        pass
                    await self._admin_show_settings_hub(event)
                    return
                if data == "owner_rollback_list" and role == ROLE_OWNER:
                    await self._owner_show_rollback_list(event)
                    return
                # v2.8.1: pagination برای rollback list
                if data.startswith("owner_rollback_page:") and role == ROLE_OWNER:
                    try:
                        page = int(data.split(":", 1)[1])
                    except (ValueError, IndexError):
                        page = 1
                    # page را به event تخصیص می‌دهیم تا _owner_show_rollback_list بخواندش
                    event._rollback_page = page
                    await self._owner_show_rollback_list(event)
                    return
                if data.startswith("owner_rollback_go:") and role == ROLE_OWNER:
                    # فرمت: owner_rollback_go:{urlencoded_name}
                    encoded_name = data[len("owner_rollback_go:"):]
                    await self._owner_rollback_go(event, encoded_name)
                    return
                # PATCH (v2.1.5): دکمه‌ی «🌐 پنل وب» برای OWNER
                if data == "owner_web_panel" and role == ROLE_OWNER:
                    await self._show_owner_web_panel(event)
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
                if data.startswith("uacc_act:"):
                    # PATCH (v2.0.7): اکشن‌های سریعِ SelfBot از داخل پنل
                    # مدیریت کاربر. فرمت: uacc_act:{action}:{user_id}:{tag}
                    # این callback فقط برای OWNER/ADMIN است. قبل از اجرای
                    # هر action، مالکیت دوباره چک می‌شود (دفاع در عمق).
                    parts_cb = data.split(":", 3)
                    if len(parts_cb) < 4:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    action = parts_cb[1]
                    target_id = safe_callback_int(parts_cb[2])
                    tag = parts_cb[3]
                    if target_id is None or not tag:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    # مالکیتِ تگ به target_id دوباره چک می‌شود
                    cfg = self.sb.load_config()
                    acc = cfg.get(tag)
                    # TEST-G1-ACCOUNT (BUG: WRONG_MESSAGE — قبلاً وقتی tag در
                    # cfg نبود، acc=None به account_belongs_to پاس داده می‌شد
                    # و چون None dict نیست، False برمی‌گرداند و کاربر پیامِ
                    # «این اکانت متعلق به این کاربر نیست» می‌دید — در حالی که
                    # اکانت اصلاً وجود نداشت. این پیام برای مدیر/مالک که
                    # لیستِ اکانت‌ها را می‌بیند گمراه‌کننده است. حالا بین
                    # «وجود ندارد» و «مالکیت ندارد» تمایز قائل می‌شویم.)
                    if acc is None:
                        await event.answer("❌ این اکانت وجود ندارد.", alert=True)
                        return
                    if not account_belongs_to(acc, tag, target_id):
                        await event.answer("❌ این اکانت متعلق به این کاربر نیست.", alert=True)
                        return
                    # each action maps to an existing AdminBot handler.
                    # we use the same tag-based callback paths the AdminBot
                    # already understands (feat: / appear: / conn: / etc.).
                    # this avoids duplicating handlers and keeps everything
                    # in sync with the account hub.
                    action_to_route = {
                        "feat":   f"feat:{tag}",
                        "appear": f"appear:{tag}",
                        "conn":   f"conn:{tag}",
                        "status": f"status:{tag}",
                        "send":   f"send_msg:{tag}",
                        "sess":   f"sessions:{tag}",
                        "tfa":    f"tfa:{tag}",
                        "getcode": f"getcode:{tag}",
                        "guard":  f"login_guard:{tag}",  # v2.12.24
                        "enable": f"enable:{tag}",
                        "disable": f"disable:{tag}",
                        "del":    f"del_confirm:{tag}",
                    }
                    route = action_to_route.get(action)
                    if not route:
                        await event.answer("❌ اکشن نامعتبر است.", alert=True)
                        return
                    # نباید خود event.data را دستکاری کنیم — telethon آن را
                    # read-only نگه می‌دارد. به‌جایش admin_panel.handle_callback
                    # را با data override صدا می‌زنیم.
                    async with self._panel_lock:
                        self._sync_admin_panel_scope(event.sender_id)
                        await self.admin_panel.handle_callback(event, data=route)
                    return
                # v2.12.16 (USER-REQUEST): «🤖 سلف من» کاملاً حذف شد.
                # callback handlers موندن برای defensive rejection (اگه
                # کسی با callback دستی تلاش کنه).
                if data == "user_my_bots" or data.startswith("my_acc:") or data == "user_my_add_bot":
                    await event.answer("⛔ این بخش دیگر فعال نیست.", alert=True)
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
                # v2.19.4 (AUDIT-36 H5 — HIGH): سیم‌کشی زنجیره‌ی «بلاک کاربر»
                # (v2.17.0) — دکمه‌ها و Backend کامل بودند ولی هیچ شاخه‌ی
                # دیسپچری وجود نداشت → بلاک/رفع‌بلاک از هیچ UIای قابل‌اجرا
                # نبود و _enforce_block فقط با ویرایشِ دستیِ DB فعال می‌شد.
                # گاردهای دقیقِ نقش (OWNER برای بلاکِ ADMIN و…) داخل خودِ
                # متدها + re-check در block_saas_user هستند (دفاع در عمق).
                # ترتیب مهم: user_block_go قبل از user_block چک می‌شود چون
                # پیشوندِ آن هم هست.
                if data.startswith("user_block_go:"):
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    await self._do_block_user(event, target_id, back_data_cb)
                    return
                if data.startswith("user_block:"):
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    await self._show_user_block_confirm(event, target_id, back_data_cb)
                    return
                if data.startswith("user_unblock:"):
                    parts_cb = data.split(":", 2)
                    target_id = safe_callback_int(parts_cb[1])
                    back_data_cb = parts_cb[2].encode() if len(parts_cb) > 2 else b"owner_users"
                    if target_id is None:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                        return
                    if role not in (ROLE_OWNER, ROLE_ADMIN):
                        await event.answer("⛔ دسترسی نداری", alert=True)
                        return
                    await self._do_unblock_user(event, target_id, back_data_cb)
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
                # TEST-G4-PAYMENT (BUG: SILENT_NOOP — non-admin click on
                # pay_approve: was silently ignored; on a forwarded button
                # the user got no feedback. Mirror the owner_backup pattern.)
                if data.startswith("pay_approve:"):
                    await event.answer("⛔ فقط OWNER/ADMIN می‌توانند پرداخت را تأیید کنند.", alert=True)
                    return
                if data.startswith("pay_reject:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    parts = data.split(":")
                    await self._owner_review_payment(
                        event, safe_callback_int(parts[1], 0), False, from_notif=len(parts) > 2
                    )
                    return
                # TEST-G4-PAYMENT (BUG: SILENT_NOOP — same as pay_approve:)
                if data.startswith("pay_reject:"):
                    await event.answer("⛔ فقط OWNER/ADMIN می‌توانند پرداخت را رد کنند.", alert=True)
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
                # v2.13.0 (TEST-G3-LICENSE FIX#2): فیلتر لایسنس بر اساس نوع
                if data.startswith("lic_filter:") and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    fval = data.split(":", 1)[1]
                    ftype = None if fval == "all" else fval
                    # normalize
                    if ftype not in (LICENSE_TYPE_ACCOUNT, LICENSE_TYPE_RESELLER,
                                     LICENSE_TYPE_ADMIN, None):
                        ftype = None
                    await self._owner_show_licenses(event, filter_type=ftype)
                    return
                # v2.13.0 (TEST-G3-LICENSE FIX#1): مسیر مدیریت تک‌تک لایسنس‌ها
                if data.startswith("lic_view:") and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    code = data.split(":", 1)[1]
                    await self._owner_show_license_detail(event, code)
                    return
                if data.startswith("lic_deactivate:") and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    code = data.split(":", 1)[1]
                    await self._owner_deactivate_license(event, code)
                    return
                if data.startswith("lic_delete:") and not data.startswith("lic_delete_go:") \
                        and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    code = data.split(":", 1)[1]
                    await self._owner_delete_license(event, code)
                    return
                if data.startswith("lic_delete_go:") and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    code = data.split(":", 1)[1]
                    await self._owner_delete_license_go(event, code)
                    return
                if data == "license_access_admins" and role == ROLE_OWNER:
                    await self._owner_show_role_list(event, ROLE_ADMIN)
                    return
                if data == "license_access_resellers" and role == ROLE_OWNER:
                    await self._owner_show_role_list(event, ROLE_RESELLER)
                    return
                # TEST-G7-RESELLER (BUG: owner_resellers / reseller_application:
                # / reseller_approve: / reseller_reject: / reseller_customers:
                # — هیچ‌کدام از این ۵ مسیر در callback_h وجود نداشتند.
                # `_update_reseller_application` نیز وجود نداشت (PATCH-8
                # فراموش شده بود). این بلاک همه‌شان را وصل می‌کند).
                if data == "owner_resellers" and role == ROLE_OWNER:
                    await self._owner_show_role_list(event, ROLE_RESELLER)
                    return
                if data == "reseller_applications" and role == ROLE_OWNER:
                    await self._owner_show_reseller_applications(event)
                    return
                if data.startswith("reseller_application:") and role == ROLE_OWNER:
                    applicant_uid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_show_reseller_application(event, applicant_uid)
                    return
                if data.startswith("reseller_approve:") and role == ROLE_OWNER:
                    applicant_uid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_approve_reseller_application(event, applicant_uid)
                    return
                if data.startswith("reseller_reject:") and role == ROLE_OWNER:
                    applicant_uid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_reject_reseller_application(event, applicant_uid)
                    return
                if data.startswith("reseller_customers:") and role == ROLE_OWNER:
                    reseller_uid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._owner_show_reseller_customers(event, reseller_uid)
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
                    wiz["data"]["duration_days"] = duration
                    wiz["data"]["license_type"] = ltype
                    wiz["state"] = "cl_pending_max_uses"
                    await event.edit(
                        "🔢 **تعداد استفاده‌ی مجاز**\n\n"
                        "این لایسنس چند بار قابل استفاده باشه?\n"
                        "۱ = یک‌بارمصرف (پیشفرض)\n"
                        "۵ = ۵ کاربر می‌تونن استفاده کنن\n\n"
                        "یه عدد بفرست (۱ تا ۱۰۰۰):",
                        buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                    )
                    return
                # ──────── ساخت گروهی لایسنس (v2.7.0) ────────
                # v2.8.12: کدهای تخفیف
                if data == "owner_discount_codes" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._owner_show_discount_codes(event)
                    return
                if data == "owner_discount_create" and role in (ROLE_OWNER, ROLE_ADMIN):
                    await self._clear_admin_panel_wizard(event.sender_id)
                    self._start_own_wizard(event.sender_id, "discount_pending_percent", {})
                    await event.edit(
                        "🎟 **ساخت کد تخفیف**\n\n"
                        "درصد تخفیف رو بفرست (۱ تا ۱۰۰):",
                        buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                    )
                    return
                # TEST-G4-PAYMENT (BUG: discount_toggle: was entirely
                # missing — UI listed codes but the toggle callback had
                # no handler, so the (also newly-added) per-code toggle
                # buttons did nothing).
                if data.startswith("discount_toggle:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    code = data.split(":", 1)[1]
                    r = toggle_discount_code(code, event.sender_id)
                    if r.get("ok"):
                        await event.answer(
                            "✅ فعال شد" if r["is_active"] else "⚫ غیرفعال شد",
                            alert=True,
                        )
                    else:
                        await event.answer(
                            f"❌ {r.get('error', 'خطا')}", alert=True
                        )
                    await self._owner_show_discount_codes(event)
                    return
                # v2.10.2: درگاه‌های پرداخت
                if data == "owner_payment_gateways" and role == ROLE_OWNER:
                    await self._owner_show_payment_gateways(event)
                    return
                if data.startswith("toggle_pay:") and role == ROLE_OWNER:
                    gw = data.split(":", 1)[1]
                    key_map = {"zarinpal": "pay_zarinpal_enabled", "zibal": "pay_zibal_enabled",
                               "card": "pay_card_enabled", "trc20": "pay_trc20_enabled"}
                    setting_key = key_map.get(gw)
                    if setting_key:
                        current = get_setting(setting_key, "1" if gw in ("card", "trc20") else "0")
                        # v2.13.0 (DEBUG-2 BUG#2): audit log تغییر وضعیت درگاه پرداخت
                        set_setting(setting_key, "0" if current == "1" else "1", actor_id=event.sender_id)
                    await self._owner_show_payment_gateways(event)
                    return
                if data.startswith("set_merchant:") and role == ROLE_OWNER:
                    gw = data.split(":", 1)[1]
                    # TEST-G4-PAYMENT (BUG: EDGE_CASE — gw مستقیماً از
                    # callback می‌آمد و بدون whitelist در set_setting استفاده
                    # می‌شد؛ یک callback دست‌ساز مثل set_merchant:admin_password
                    # یک setting به‌نام admin_password_merchant می‌ساخت. حالا
                    # فقط زرین‌پال/زیبال پذیرفته می‌شوند.
                    if gw not in ("zarinpal", "zibal"):
                        await event.answer("⛔ درگاه نامعتبر است.", alert=True)
                        return
                    await self._clear_admin_panel_wizard(event.sender_id)
                    self._start_own_wizard(event.sender_id, "set_merchant", {"gw": gw})
                    await self._respond_safe(event, f"🔑 **مرچنت {gw}**\n\nکد مرچنت رو بفرست:")
                    return
                if data.startswith("order_zarinpal:"):
                    oid = safe_callback_int(data.split(":", 1)[1], 0)
                    order = get_order(oid)
                    if not order or order["user_id"] != event.sender_id:
                        await event.answer("❌ فاکتور پیدا نشد.", alert=True)
                        return
                    # v2.12.21 (QA7-USER3): status check — جلوگیری از double-pay
                    if order["status"] != ORDER_STATUS_PENDING:
                        await event.answer("❌ این فاکتور قابل پرداخت نیست.", alert=True)
                        return
                    import os as _os
                    panel_url = (_os.environ.get("PANEL_URL") or "").strip().rstrip("/")
                    if not panel_url:
                        await event.answer(
                            "❌ پنل وب تنظیم نشده. لطفاً با پشتیبانی تماس بگیرید "
                            "یا از روش پرداخت دیگه‌ای استفاده کنید.",
                            alert=True,
                        )
                        return
                    cb = f"{panel_url}/api/payment/zarinpal/callback"
                    # PATCH (P1-3 BUG-19b): این تابع urllib.request همزمان
                    # (blocking) است — از روترِ async نباید مستقیم صدا زده
                    # شود؛ با to_thread در thread جدا اجرا می‌شود.
                    result = await asyncio.to_thread(create_zarinpal_payment, oid, cb)
                    if result.get("ok"):
                        await self._respond_safe(event,
                            f"🟡 **زرین‌پال**\n\n🧾 `{order['order_no']}`\n💰 {fa_digits(order['amount_toman'])} Toman\n\n🔗 [پرداخت]({result['url']})",
                            buttons=[UI.nav_row()])
                    else:
                        _gw_err = result.get("error", "خطا")
                        # PATCH (P2-3 §17.3): پاسخ خام/exception درگاه نباید به
                        # کاربر برسد (همان الگوی _safe_gateway_error در
                        # web_panel) — لاگ سرور + پیام generic فارسی. کدهای
                        # کنترل‌شده (مثل «merchant ست نشده») دست‌نخورده می‌مانند.
                        if "request_failed" in _gw_err or "zarinpal_error:" in _gw_err:
                            print(f"❌ [order_zarinpal] gateway error: {_gw_err}")
                            _gw_err = "خطا در ارتباط با درگاه پرداخت — با پشتیبانی تماس بگیرید."
                        await event.answer(f"❌ {_gw_err}", alert=True)
                    return
                if data.startswith("order_zibal:"):
                    oid = safe_callback_int(data.split(":", 1)[1], 0)
                    order = get_order(oid)
                    if not order or order["user_id"] != event.sender_id:
                        await event.answer("❌ فاکتور پیدا نشد.", alert=True)
                        return
                    # v2.12.21 (QA7-USER3): status check
                    if order["status"] != ORDER_STATUS_PENDING:
                        await event.answer("❌ این فاکتور قابل پرداخت نیست.", alert=True)
                        return
                    import os as _os
                    panel_url = (_os.environ.get("PANEL_URL") or "").strip().rstrip("/")
                    if not panel_url:
                        await event.answer(
                            "❌ پنل وب تنظیم نشده. لطفاً با پشتیبانی تماس بگیرید "
                            "یا از روش پرداخت دیگه‌ای استفاده کنید.",
                            alert=True,
                        )
                        return
                    cb = f"{panel_url}/api/payment/zibal/callback"
                    # PATCH (P1-3 BUG-19b): همان‌طور که در Zarinpal — فراخوانیِ
                    # blocking از روترِ async ممنوع است.
                    result = await asyncio.to_thread(create_zibal_payment, oid, cb)
                    if result.get("ok"):
                        await self._respond_safe(event,
                            f"🟢 **زیبال**\n\n🧾 `{order['order_no']}`\n💰 {fa_digits(order['amount_toman'])} Toman\n\n🔗 [پرداخت]({result['url']})",
                            buttons=[UI.nav_row()])
                    else:
                        _gw_err = result.get("error", "خطا")
                        # PATCH (P2-3 §17.3): مانند زرین‌پال — جزئیات خام درگاه
                        # فقط در لاگ سرور؛ کاربر پیام generic می‌گیرد.
                        if "request_failed" in _gw_err or "zibal_error:" in _gw_err:
                            print(f"❌ [order_zibal] gateway error: {_gw_err}")
                            _gw_err = "خطا در ارتباط با درگاه پرداخت — با پشتیبانی تماس بگیرید."
                        await event.answer(f"❌ {_gw_err}", alert=True)
                    return
                if data == "owner_create_license_batch" and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    await self._clear_admin_panel_wizard(event.sender_id)
                    self._start_own_wizard(event.sender_id, "cl_batch_pending_type", {})
                    type_buttons = [
                        UI.go("👤 اشتراک کاربر", b"cl_batch_type:account"),
                    ]
                    if role in (ROLE_OWNER, ROLE_ADMIN):
                        type_buttons.append(UI.go("🤝 نمایندگی", b"cl_batch_type:reseller"))
                    if role == ROLE_OWNER:
                        type_buttons.append(UI.go("🛡 ادمین", b"cl_batch_type:admin"))
                    await event.edit(
                        "📦 **ساخت گروهی لایسنس**\n\n"
                        "نوع دسترسی رو انتخاب کن — همه‌ی لایسنس‌ها از همین نوع خواهند بود:",
                        buttons=self._pair_buttons(type_buttons)
                                + [[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                    )
                    return
                if data.startswith("cl_batch_type:"):
                    ltype = data.split(":", 1)[1]
                    wiz = self.wizards.get(event.sender_id)
                    if wiz is None or wiz["state"] != "cl_batch_pending_type":
                        return
                    wiz["data"]["license_type"] = ltype
                    if ltype == LICENSE_TYPE_ADMIN:
                        if role != ROLE_OWNER:
                            await event.answer("⛔ فقط OWNER می‌تواند لایسنس ادمین بسازد.", alert=True)
                            return
                        # ادمین: مستقیم به سؤال تعداد
                        wiz["state"] = WIZ_CL_BATCH_QTY
                        await event.edit(
                            "🔢 **تعداد لایسنس ادمین** رو بفرست (۱ تا ۱۰۰):",
                            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                        )
                        return
                    if ltype == LICENSE_TYPE_RESELLER:
                        # نمایندگی: اول سقف مشتری، بعد تعداد
                        wiz["state"] = WIZ_CL_BATCH_RESELLER_LIMIT
                        await event.edit(
                            "👥 **لایسنس نمایندگی گروهی**\n\n"
                            "سقف مشتری‌های هر نماینده رو بفرست (یه عدد مثبت):",
                            buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                        )
                        return
                    # account → انتخاب مدت
                    wiz["state"] = "cl_batch_pending_duration"
                    await event.edit(
                        "⏳ **مدت اعتبارِ همه‌ی لایسنس‌ها** رو انتخاب کن:",
                        buttons=[
                            [UI.go("۳۰ روز", b"cl_batch_dur:30"), UI.go("۹۰ روز", b"cl_batch_dur:90")],
                            [UI.go("۱۸۰ روز", b"cl_batch_dur:180"), UI.go("۳۶۵ روز", b"cl_batch_dur:365")],
                            [UI.neutral(UI.L_CANCEL, NAV_BACK)],
                        ],
                    )
                    return
                if data.startswith("cl_batch_dur:"):
                    wiz = self.wizards.get(event.sender_id)
                    if wiz is None or wiz["state"] != "cl_batch_pending_duration":
                        return
                    duration = int(data.split(":", 1)[1])
                    wiz["data"]["duration_days"] = duration
                    wiz["state"] = "cl_batch_pending_max_uses"
                    await event.edit(
                        "🔢 **تعداد استفاده‌ی مجاز برای هر لایسنس**\n\n"
                        "هر لایسنس چند بار قابل استفاده باشه?\n"
                        "۱ = یک‌بارمصرف (پیشفرض)\n"
                        "۵ = ۵ کاربر می‌تونن استفاده کنن\n\n"
                        "یه عدد بفرست (۱ تا ۱۰۰۰):",
                        buttons=[[UI.neutral(UI.L_CANCEL, NAV_BACK)]],
                    )
                    return
                # ──────── کیف پول کاربر (v2.8.0) ────────
                if data == "user_wallet":
                    await self._user_show_wallet(event)
                    return
                if data == "user_wallet_tx":
                    await self._user_show_wallet_tx(event)
                    return
                # v2.8.12: RESELLER هم می‌تونه کیف پول مشتری‌های خودش رو ببینه
                # PATCH (TEST-G2-USERMGMT FIX#3): قبلاً فقط role check می‌شد
                # بدون این‌که مطمئن بشیم target_uid واقعاً مشتری همین
                # نماینده است. یک RESELLER می‌توانست با ساختنِ دستیِ
                # callback مثل «user_wallet_admin:12345» کیف پولِ هر کاربر
                # دلخواه (از جمله کاربرانِ نماینده‌ی دیگر یا OWNER) را ببیند
                # — info leak (موجودی + تراکنش‌ها). حالا برای RESELLER،
                # customer_ids چک می‌شود. همان الگویی که برای
                # user_sub_admin و user_orders_admin و user_manage وجود داشت.
                if data.startswith("user_wallet_admin:") and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    target_uid = safe_callback_int(data.split(":", 1)[1], 0)
                    if role == ROLE_RESELLER:
                        _cust_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_uid not in _cust_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                    await self._admin_show_user_wallet(event, target_uid)
                    return
                # v2.8.12: RESELLER هم می‌تونه شارژ کنه
                # PATCH (TEST-G2-USERMGMT FIX#3): همان gate برای credit.
                if data.startswith("user_wallet_credit:") and role in (ROLE_OWNER, ROLE_ADMIN, ROLE_RESELLER):
                    target_uid = safe_callback_int(data.split(":", 1)[1], 0)
                    if role == ROLE_RESELLER:
                        _cust_ids = {u["user_id"] for u in list_users_for_reseller(event.sender_id)}
                        if target_uid not in _cust_ids:
                            await event.answer("⛔ این کاربر مشتری تو نیست.", alert=True)
                            return
                    await self._admin_wallet_credit_start(event, target_uid)
                    return
                if data.startswith("user_wallet_debit:") and role in (ROLE_OWNER, ROLE_ADMIN):
                    target_uid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._admin_wallet_debit_start(event, target_uid)
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
                if data == "user_reporter":
                    # v2.17.0: بخش «ریپورتر» — v2.19.2 (OWNER-REQUEST): دکمه
                    # برای همه نمایش داده می‌شود؛ الزامِ استفاده همان لاگینِ
                    # اکانتِ خودِ کاربر است. کاربرِ لاگین‌نکرده به‌جای alert،
                    # صفحه‌ی راهنمایِ دوستانه با دکمه‌ی مستقیمِ لاگین می‌رود
                    # (قیفِ فروش: ریپورتر ← لاگین ← اشتراک).
                    if not self._user_has_logged_in_account(event.sender_id):
                        from cianet.bots.ui import UI as _UI
                        await event.edit(
                            _UI.screen(
                                "🎙 ریپورتر",
                                body=[
                                    "🎙 برای استفاده از ریپورتر، اول باید اکانتِ"
                                    " **خودت** را در ربات لاگین کنی.",
                                    "",
                                    "چرا؟ چون هر گزارش فقط با اکانتِ خودِ"
                                    " کاربر ارسال می‌شود — این قانونِ همیشگیِ"
                                    " این بخش است.",
                                    "",
                                    "📱 با لاگین کردن، هم ریپورتر برایت باز"
                                    " می‌شود هم سلف‌باتِ خودت فعال می‌شود.",
                                ],
                                subtitle="یک دقیقه بیشتر طول نمی‌کشد",
                                hint="پس از لاگین، دوباره «🎙 ریپورتر» را بزن"),
                            buttons=[
                                [_UI.confirm("📱 لاگین اکانتِ من",
                                             "user_login_account")],
                                _UI.nav_row(),
                            ],
                        )
                        return
                    await reporter_module.render_reporter_page(event, self)
                    return
                # v2.18.0: اکشن‌های داخل بخش ریپورتر (پیشوندِ «reporter:»).
                # همان گیتِ لاگین دوباره چک می‌شود (دفاع‌در‌عمق) و کل منطق
                # در cianet/bots/reporter.py است.
                if data.startswith("reporter:"):
                    if not self._user_has_logged_in_account(event.sender_id):
                        await event.answer(
                            "🎙 ریپورتر فقط برای کاربرانی است که اکانت خودشان "
                            "را در ربات لاگین کرده‌اند.", alert=True)
                        return
                    await reporter_module.handle_reporter_action(event, self, data)
                    return
                if data.startswith("ticket_unit:"):  # v1.8.0
                    unit_id = data.split(":", 1)[1]
                    await self._select_ticket_unit(event, unit_id)
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
                # v2.17.0: اشتراک دسته‌جمعی (فقط کاربرِ بدون اشتراکِ فعال)
                if data == "user_group_sub":
                    await self._user_start_group_sub(event)
                    return
                if data.startswith("group_plan:"):
                    await self._user_group_seats(event, data.split(":", 1)[1])
                    return
                if data.startswith("group_seats:"):
                    parts_g = data.split(":", 2)
                    if len(parts_g) == 3 and parts_g[2].isdigit():
                        await self._user_group_chosen(event, parts_g[1], int(parts_g[2]))
                    else:
                        await event.answer("❌ داده‌ی دکمه نامعتبر است.", alert=True)
                    return
                if data.startswith("renew_plan:"):
                    await self._user_plan_chosen(event, data.split(":", 1)[1])
                    return
                if data == "user_orders":
                    await self._user_show_orders(event)
                    return
                # v2.9.0: کد تخفیف
                if data.startswith("order_discount:"):
                    oid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._start_discount_wizard(event, oid)
                    return
                # v2.9.0: پرداخت با کیف پول
                if data.startswith("order_wallet:"):
                    oid = safe_callback_int(data.split(":", 1)[1], 0)
                    await self._pay_order_from_wallet(event, oid)
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
                # TEST-G4-PAYMENT (BUG: order_view: / order_extend: /
                # order_extend_go: were entirely missing — user_orders
                # screen had no per-order buttons, so a pending order could
                # not be re-opened for payment and an expired order could
                # not be revived.)
                if data.startswith("order_view:"):
                    oid = safe_callback_int(data.split(":", 1)[1], 0)
                    order = get_order(oid)
                    if not order or order["user_id"] != event.sender_id:
                        await event.answer("❌ فاکتور پیدا نشد.", alert=True)
                        return
                    if order["status"] != ORDER_STATUS_PENDING:
                        await event.answer(
                            "❌ این فاکتور قابل پرداخت نیست (منقضی/پرداخت‌شده/لغو).",
                            alert=True,
                        )
                        return
                    rate = (await self._compute_order_amounts(order["amount_toman"]))[1]
                    await self._show_invoice(event, order, rate)
                    return
                if data.startswith("order_extend:"):
                    await self._user_extend_order(event, safe_callback_int(data.split(":", 1)[1], 0))
                    return
                if data.startswith("order_extend_go:"):
                    await self._user_extend_order_go(event, safe_callback_int(data.split(":", 1)[1], 0))
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
                    #
                    # PATCH (admin/owner login): قبلاً OWNER و ADMIN هم در
                    # این گیرِ `get_active_subscription` می‌افتادند — چون طبق
                    # طراحی، اشتراک فعال ندارند و سیستم براشون همچون
                    # "کاربر عادی بدون اشتراک" رفتار می‌کرد → دکمه‌ی "📱 لاگین
                    # کردن سلف" بهشون نشان داده می‌شد ولی با کلیک، خطای
                    # "اول باید اشتراک فعال داشته باشی" می‌داد. حالا OWNER و
                    # ADMIN از این gate عبور می‌کنند و مستقیماً وارد ویزارد
                    # لاگین می‌شوند. این دقیقاً با نیتِ طراحی منطبق است:
                    # پنلِ لاگین برای «هر کسی که دکمه را می‌بیند» مجاز است،
                    # و دکمه از قبل فقط برای کسانی نمایش داده می‌شود که
                    # اشتراک دارند یا نقش admin/owner دارند.
                    role = self._role(event.sender_id)
                    if role not in (ROLE_OWNER, ROLE_ADMIN):
                        active_sub = get_active_subscription(event.sender_id)
                        if not active_sub:
                            await event.answer(
                                "برای لاگین اکانت، اول باید اشتراک فعال داشته باشی "
                                "(لایسنس فعال کن یا اشتراک بخر).",
                                alert=True,
                            )
                            return
                    # v2.15.3 (LOGIN-UX-3): هارد‌بلاکِ لاگین مجدد حذف شد —
                    # کاربری که قبلاً لاگین کرده می‌تواند دوباره وارد ویزارد شود؛
                    # اگر شماره‌اش سلفِ زنده‌ی قبلی داشته باشد، در WIZ_PHONE
                    # دیالوگِ «حذف سلف قبلی و لاگین مجدد؟ تایید/انصراف» نشان
                    # داده می‌شود (جریان self-service بدون دخالت پشتیبانی).
                    # گیتِ اشتراکِ بالا (get_active_subscription) همچنان برقرار است.
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
                    # PATCH (v2.0.10): revive _show_reseller_info — این متد
                    # تعریف شده بود ولی audit-7 اشتباهاً آن را unreachable کرد.
                    # حالا دوباره فراخوانی می‌شه تا صفحه‌ی توصیفیِ برنامه‌ی
                    # نمایندگی (با اطلاعات کامل + دکمه‌ی درخواست) نشون داده بشه.
                    await self._show_reseller_info(event)
                    return
                if data == "user_help":
                    # v1.8.0: قبلاً HELP_TEXT (یه متن طولانی ترکیبی) نمایش
                    # داده می‌شد. حالا ACTIVATION_HELP_TEXT نمایش داده می‌شه
                    # که راهنمای قدم‌به‌قدم فعال‌سازیه — دقیقاً همون چیزی که
                    # کاربر در این صفحه انتظار داره.
                    await event.edit(ACTIVATION_HELP_TEXT, buttons=[UI.nav_row()])
                    # PATCH (audit-7): اینجا return افتاده بود → ادامه‌ی
                    # کد به یک handler دومِ user_reseller_info می‌رسید که
                    # صفحه را overwrite می‌کرد. حالا بعد از edit، return
                    # می‌کنیم تا همان صفحه‌ی راهنما باقی بماند.
                    return
                # v2.0: نمایندگی سلف — PATCH (audit-7): این بلوکِ
                # `user_reseller_info` یک duplicate است (اولی بالاتر هندل
                # می‌شود). چون اولی return دارد، اینجا هیچ‌وقت اجرا نمی‌شود
                # ولی برای اطمینان از ناپدید شدنِ تله‌ی fallthrough، آن
                # را حذف کردیم. `user_reseller_apply` معتبر است و باقی مانده.
                # v2.11: خرید ربات اختصاصی
                if data == "dedicated_bot_buy":
                    await self._start_dedicated_bot_purchase(event)
                    return
                if data.startswith("dedicated_pay:"):
                    method = data.split(":", 1)[1]
                    await self._process_dedicated_bot_payment(event, method)
                    return
                if data == "user_reseller_apply":
                    await self._apply_reseller(event)
                    return
                # PATCH (audit-7): این return غیرقابل‌دسترس (unreachable)
                # حذف شد — خطِ بعد از آن در `except Exception` قرار دارد و
                # این return هیچ‌وقت اجرا نمی‌شد.
            except errors.MessageNotModifiedError:
                # PATCH (v2.0.6): تلگرام وقتی event.edit با همان محتوای
                # فعلی صدا زده بشه، این خطا رو برمی‌گردونه (به‌جای silent
                # success). این معمولاً روی دکمه‌های Refresh یا callbackهای
                # idempotent رخ می‌ده (مثلاً کاربر چند بار روی 🔄 بزنه).
                # خطا واقعی نیست و نباید به کاربر نشت کنه — کافیه
                # event.answer خالی بزنیم تا spinner بسته بشه.
                try:
                    await event.answer()
                except Exception:
                    pass
            except Exception as e:
                # v2.14.7 (USER-REQUEST): ReplyMarkupInvalidError زمانی رخ
                # می‌دهد که دکمه‌های قدیمی (از صفحه‌ی قبلی) دیگه valid نیستن —
                # مثلاً وقتی اکانتی حذف شده و کاربر روی دکمه‌ی قدیمی‌اش زده.
                # این خطای واقعی نیست — فقط spinner رو ببند و یه alert کوتاه بده.
                # بقیه‌ی خطاها هم فقط در لاگ سرور — به کاربر پیام عمومی داده می‌شود.
                _err_name = type(e).__name__
                if _err_name in ("ReplyMarkupInvalidError", "MessageNotModifiedError",
                                 "MessageIdInvalidError", "MessageEmptyError"):
                    # این خطاها non-fatal هستن — فقط spinner ببند
                    try:
                        await event.answer()
                    except Exception:
                        pass
                    return
                print(f"⚠️ [saas_bot] خطا در پردازش دکمه: {type(e).__name__}: {e}")
                # v2.19.1 (DIAG): متنِ alert خود-تشخیصی — FloodWait پیامِ
                # آرام می‌گیرد (خطای گذرای تلگرام است، نه خطای ربات) و
                # برای OWNER نامِ خطا + جزئیات کوتاهش هم داخل همان alert
                # می‌آید تا اسکرین‌شاتِ بعدی بدون لاگِ سرور قابلِ تشخیص باشد.
                try:
                    _own = False
                    try:
                        _own = self._role(event.sender_id) == ROLE_OWNER
                    except Exception:
                        pass
                    await event.answer(
                        bot_error_alert_text(e, is_owner=_own), alert=True)
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

