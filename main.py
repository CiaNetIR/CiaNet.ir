#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نقطه‌ی ورود پروژه (shim) — v2.16.0.

کد از فایلِ تک‌پارچه‌ی main.py به پکیج cianet/ منتقل شد؛ این فایل فقط:

  ۱) cianet.core و کلاس‌های cianet.bots را بارگذاری می‌کند،
  ۲) نام کلاس‌ها را در namespace مشترکِ core تزریق می‌کند (توابعِ راه‌اندازِ
     داخل core — مثل run_admin_bot_forever — این نام‌ها را در زمانِ
     فراخوانی از globals خودشان resolve می‌کنند)،
  ۳) همان سطحِ ماژولِ قبلیِ main را برای web_panel و cianet_updater که
     «import main» می‌کنند بازتولید می‌کند (شامل نام‌های underscore),
  ۴) بلوک __main__ را اجرا می‌کند (دقیقاً مثل قبل).

چیدمان داده‌ها تغییری نکرده: config.json / sessions/ / downloads/ /
tracker_media/ / dedicated_bots/ همان DATA_DIR قبلی (کنارِ ریشه) هستند.
"""
import cianet.core as _core
from cianet.bots.ui import UI, NavStack
from cianet.bots.admin import AdminBot
from cianet.bots.saas import SaaSBot
from cianet.bots.saas import _deliver_via_bot as _deliver_via_bot  # re-export
from cianet.bots.helper import HelperBot
from cianet.bots.self import SelfBot

# تزریق کلاس‌ها در namespace مشترکِ core — قبل از هر فراخوانیِ توابعِ
# راه‌انداز. بدون این، run_*_forever در core روی NameError می‌خورد.
for _cls in (UI, NavStack, AdminBot, SaaSBot, HelperBot, SelfBot):
    setattr(_core, _cls.__name__, _cls)

# بازتولید سطحِ ماژولِ main (شامل نام‌های underscore) — سازگاریِ کامل با
# «import main» در web_panel.py و cianet_updater.py.
globals().update(
    {k: v for k, v in vars(_core).items() if not k.startswith("__")}
)

# اتصال صریح برای خوانایی و linter — globals().update هم همین نام را
# می‌آورد، ولی اینجا مستقیم روشنش می‌کنیم.
_run_forever = _core._run_forever

if __name__ == "__main__":
    _run_forever()
