"""پکیج CiaNet — از v2.16.0 کد از تک‌فایلِ main.py به این ساختار منتقل شد.

ساختار:
    cianet/core.py          هسته‌ی مشترک: ثابت‌ها، دیتابیس، ژورنال‌ها،
                           توابع کمکی و راه‌اندازها
    cianet/bots/ui.py       UI + NavStack
    cianet/bots/admin.py    AdminBot (پنل مدیریت سلف‌ها)
    cianet/bots/saas.py     SaaSBot (ربات کاربران/اشتراک)
    cianet/bots/helper.py   HelperBot (ربات راهنما)
    cianet/bots/self.py     SelfBot (سلف‌بات تلگرام)

نقطه‌ی ورود: main.py (ریشه‌ی ریپو) — سازگار با systemd/updater قبلی.
"""
