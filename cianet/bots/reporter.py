"""🎙 Reporter — ساختار آماده‌ی بخش «ریپورتر» (v2.17.0)

این ماژول **اسکلتِ آماده** برای بخش ریپورتر است — طبق درخواست مالک،
منطقِ دقیقِ کار بعداً اعلام می‌شود و فعلاً فقط زیرساخت و نقطه‌ی اتصال
فراهم شده است. فعال‌سازیِ آینده فقط با `REPORTER_ENABLED = True` و
پیاده‌سازیِ هندلرهای همین فایل انجام می‌شود؛ هیچ فایل دیگری از پروژه
نباید تغییر کند.

════════════════════════════════════════════════════════════════════
 نقطه‌ی اتصال به ربات (کجا و چطور بعداً اضافه می‌شود)
════════════════════════════════════════════════════════════════════

۱) مسیر ورود (route):
   • callback دکمه‌ی «🎙 ریپورتر» → `user_reporter`
     (تعریف دکمه: SaaSBot._show_menu_for_role — فقط برای کاربری که
     اکانتِ خودش را لاگین کرده است؛ گیتِ لاگین در خودِ route هم هست)
   • دیسپچر: داخل SaaSBot.callback_h در cianet/bots/saas.py این خط
     قرار دارد (تنها نقطه‌ی اتصال):
         await reporter_module.render_reporter_page(event, self)

۲) دسترسی:
   • فقط کاربری که `_user_has_logged_in_account(uid)` برایش True است
     (یعنی در config.json اکانتی با owner_user_id خودش دارد).
   • گیتِ اشتراک لازم نیست چون خودِ لاگین، تابعِ داشتنِ اشتراک است.

۳) داده‌های در دسترس برای منطق آینده:
   • `saas_bot.sb` → ماژول سلف (load_config، ACCOUNTS، …)
   • توابع core: `cianet.core` (دیتابیس saas.db/bot_data.db، تنظیمات، …)
   • `event` → رویداد تلگرام (chat، sender، reply، edit/respond)

۴) فعال‌سازی (وقتی مشخصاتِ دقیق از سمت مالک رسید):
   a. `REPORTER_ENABLED = True` کنید.
   b. منطق را داخل `render_reporter_page` (صفحه‌ی اصلی) و
      `handle_reporter_action` (اکشن‌های دکمه‌ها) بنویسید.
   c. اگر callback اختصاصی لازم شد، پیشوندِ `reporter:` را برای
      data استفاده کنید و یک شاخه‌ی `data.startswith("reporter:")`
      کنارِ شاخه‌ی `user_reporter` در callback_h اضافه کنید.

۵) قواعد پروژه که باید رعایت شوند:
   • مالکیتِ scoped: هیچ داده‌ای از اکانتِ کاربرِ دیگر نمایش داده نشود
     (الگوی `_account_visible` / `account_belongs_to`).
   • ورودی کاربر فقط از طریق wizard یا callback با گارد نقش.
   • صفحه‌ها با `UI.screen(...)` و دکمه‌های بازگشت با `UI.nav_row()`.
"""

REPORTER_ENABLED = False  # فلگِ فعال‌سازی — تا اعلامِ مشخصاتِ دقیق، خاموش


async def render_reporter_page(event, saas_bot) -> None:
    """صفحه‌ی اصلیِ ریپورتر — تنها نقطه‌ی ورودِ بخش ریپورتر به ربات.

    فعلاً صفحه‌ی «به‌زودی» نشان می‌دهد. بعد از فعال‌سازی، این تابع
    صفحه‌ی اصلی (گزارش‌ها/آمار/…) را render می‌کند.
    """
    from cianet.bots.ui import UI  # import محلی — وابستگیِ زمانِ import صفر

    if not REPORTER_ENABLED:
        await event.edit(
            "🎙 **ریپورتر**\n\n"
            "🚧 این بخش در حال ساخت است و به‌زودی فعال می‌شود.\n"
            "⏳ لطفاً منتظر خبرهای بعدی باشید.",
            buttons=[UI.nav_row()],
        )
        return

    # ── منطق اصلی (آینده) — مشخصات از سمت مالک ──
    # نمونه‌ی ساختار پیشنهادی:
    #   cfg = saas_bot.sb.load_config()
    #   uid = event.sender_id
    #   my_accounts = {t: a for t, a in cfg.items()
    #                  if account_belongs_to(a, t, uid)}
    #   ... ساخت گزارش بر اساس my_accounts ...
    await event.edit(
        "🎙 **ریپورتر**\n\n(منطق اصلی اینجا render می‌شود.)",
        buttons=[UI.nav_row()],
    )


async def handle_reporter_action(event, saas_bot, action: str) -> None:
    """هندلرِ اکشن‌های داخل بخش ریپورتر (پیشوندِ `reporter:`).

    فعلاً استفاده‌ای ندارد؛ بعد از فعال‌سازی، callback_h یک شاخه برای
    `data.startswith("reporter:")` اضافه می‌کند و action را به همین‌جا
    می‌فرستد.
    """
    from cianet.bots.ui import UI

    if not REPORTER_ENABLED:
        await event.answer("🎙 ریپورتر هنوز فعال نشده است.", alert=True)
        return
    # ── منطق اکشن‌ها (آینده) ──
    await event.edit("🎙 ریپورتر — اکشن: " + action,
                     buttons=[UI.nav_row()])
