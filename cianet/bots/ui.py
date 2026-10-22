"""کلاس‌های UI (دکمه‌ها/برچسب‌های مشترک پنل‌ها) و NavStack (پیمایش).

این فایل به‌صورت مکانیکی از main.py تک‌فایلی تفکیک شده است (v2.16.0).
بدنه‌ی کلاس‌ها بایت‌به‌بایت همان main.py است؛ فقط هدرِ import تولید شده.
"""

# stdlib / third-party — همان importهای اصلی main.py
from telethon import Button
import time

# هسته‌ی مشترک — ثابت‌ها/توابع مشترک
from cianet.core import (
    BUTTON_STYLE_SUPPORTED,
    NAV_BACK,
    NAV_HOME,
    NAV_NOOP,
    UI_STATES_NEED_DOT,
    UI_STATE_STYLE,
)


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
    BLUE = "🔵"
    PAUSED = "⏸"

    # نشانگرهای نقشِ دکمه
    OK = "✅"
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
    def noop(label: str):
        """
        v2.19.4 (AUDIT-36 H6 — HIGH): دکمه‌ی تزئینیِ بی‌اثر (شمارنده‌ی صفحه).

        admin.py:852 (نوارِ صفحه‌بندیِ «دستگاه‌های لاگین‌شده») این متد را
        صدا می‌زد ولی هرگز تعریف نشده بود → هر اکانتی با بیش از ۸ دستگاهِ
        دیگر، کلِ صفحه‌ی نشست‌ها را با AttributeError از دست می‌داد
        («خطا در پردازش این دکمه»). مسیرِ ثابتِ NAV_NOOP («nav:noop») از
        قبل در دیسپچرِ هر دو ربات جوابِ بی‌اثرِ امن می‌گیرد — فقط سازنده‌اش
        جا افتاده بود. خروجی: یک دکمه‌ی خنثی که کلیک روی آن answer
        می‌شود و هیچ کاری نمی‌کند.
        """
        return UI.neutral(label, NAV_NOOP)

    @staticmethod
    def refresh(route: str):
        return UI.btn(f"{UI.REFRESH} بروزرسانی", route, style="primary")

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

    # v2.23.0 (AUDIT-40): pager حذف شد — saas.py صفحه‌بندی را inline می‌سازد.

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
    THIN_SEP = "─────────────────"

    # ۵ شماره‌ی رومی برای ۵ بخش اصلی پنل ادمین (به جای ایموجی شلوغ‌کننده)
    # اصل "Boldness spent in one place": یه signature element
    NUM = ("Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ")

    @staticmethod
    def section_header(num: int, label: str = None) -> "Button.inline":
        """
        سربرگِ یک بخش در پنل ادمین: یه دکمه‌ی «غیرکلیک» که عنوان بخش
        رو نشون می‌ده. در تلگرام، دکمه‌های «بدون callback data معتبر»
        فقط برچسب‌شون نمایش داده می‌شه. این الگو signature element
        پنل ادمین ماست.

        num: 0..4 (Ⅰ تا Ⅴ)
        label: اگه None باشه از microcopy می‌گیره.
        """
        n = UI.NUM[num] if 0 <= num < len(UI.NUM) else f"{num+1}."
        hints = UI.microcopy()["section_hint"]
        sections = ("فروش", "کاربران", "پشتیبانی", "سیستم", "امنیت")
        if label is None:
            label = sections[num] if 0 <= num < len(sections) else "—"
        hint = hints.get(
            ("sales", "users", "support", "system", "security")[num]
            if 0 <= num < 5 else "", ""
        )
        text = f"{n}  {label}  ·  {hint}" if hint else f"{n}  {label}"
        # callback data خالی = دکمه نمایش داده می‌شه ولی کلیک نمی‌شه
        # (در تلگرامِ client‌های جدید؛ در برخی کلاینت‌ها ممکنه کلیک بشه
        # و answer بیاد — handler ما این رو هندل می‌کنه)
        return UI.btn(text, f"hdr:{num}", style=None)

    # v2.23.0 (AUDIT-40): section_title حذف شد — هیچ مصرف‌کننده‌ای نداشت.

    @staticmethod
    def admin_section_buttons(num: int, items: list) -> list:
        """
        یک ردیفِ عنوان + لیست دکمه برای یکی از ۵ بخش پنل ادمین.
        خروجی: لیستی از ردیف‌های دکمه (بدون عنوان متنی؛ عنوان
        در خودِ body صفحه میاد).

        items: لیستی از Button.inline که قبلاً ساخته شدن.
        """
        # فقط دکمه‌ها، بدون هیچ ترفند بصریِ اضافی. گروه‌بندی در body
        # صفحه با NUM شماره‌گذاری می‌شه.
        rows = []
        # جفت‌کردن دکمه‌ها در دو ستون
        for i in range(0, len(items), 2):
            row = items[i:i+2]
            rows.append(row)
        return rows

    @staticmethod
    def microcopy() -> dict:
        """
        متن‌های ثابت رابط (microcopy) — همه‌ی صفحات از همین دیکشنری
        می‌گیرن تا لحن یکدست باشه.

        قبلاً هر صفحه متنِ خودش را می‌نوشت («همه چیز مرتبه»، «سالم ✓»)
        که باعث می‌شد لحن یکدست نباشه.
        """
        # v2.23.0 (AUDIT-40): فقط کلیدهای مصرف‌شده نگه داشته شدند
        # (ok_all + section_hint) — بقیه هیچ‌جا خوانده نمی‌شدند.
        return {
            "ok_all":         "✓ همه چیز مرتبه",
            "section_hint": {
                "sales":      "سفارش، قیمت، لایسنس",
                "users":      "کاربران و دسترسی‌ها",
                "support":    "تیکت‌ها و پاسخ‌ها",
                "system":     "کانال، کیف پول، بکاپ",
                "security":   "مجوزها و ابزارهای حساس",
            },
        }


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


