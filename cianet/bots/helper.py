"""HelperBot — ربات راهنما.

این فایل به‌صورت مکانیکی از main.py تک‌فایلی تفکیک شده است (v2.16.0).
بدنه‌ی کلاس‌ها بایت‌به‌بایت همان main.py است؛ فقط هدرِ import تولید شده.
"""

# stdlib / third-party — همان importهای اصلی main.py
from telethon import TelegramClient
import asyncio
from telethon import events
import os

# هسته‌ی مشترک — ثابت‌ها/توابع مشترک
from cianet.core import (
    HELPER_BOT_TOKEN,
    HELPER_HOME_EN,
    HELPER_HOME_FA,
    HELPER_ORDER,
    HELPER_SESSION_NAME,
    HELPER_TOPICS_EN,
    HELPER_TOPICS_FA,
    SESSIONS_DIR,
    _first_account_creds,
    _helper_is_trigger,
    _helper_normalize,
    load_config,
)

# کلاس‌های هم‌خانواده / توابعِ جابه‌جا‌شده
from cianet.bots.ui import UI


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


