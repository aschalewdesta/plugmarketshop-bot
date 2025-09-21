# main.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# ---------------- Logging (show only warnings+ to hide aiogram INFO spam) ----------------
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
# Quiet noisy libraries
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ------------------ OWNER / ADMIN / TOKEN (set your real token) ------------------
OWNER_ID = 6781140962
ADMIN_ID = 6968325481

# Keep token here or load from env for production
BOT_TOKEN = "8198129558:AAE4SfG-AC8dbPbmAcG0wmoq2hzlO34fJVs"

# ------------------ Bot & Dispatcher ------------------
# Use Markdown default so messages with *bold* render properly
# change to HTML (fixes the "can't parse entities" error)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ------------------ Shop Hours Middleware ------------------
class ShopHoursMiddleware:
    """
    Enforce shop hours (Ethiopia / Africa/Addis_Ababa timezone).
    - Closed on Sunday (weekly break).
    - Open Monday-Saturday between open_hour .. close_hour (EAT).
    - If closed, middleware will reply with a polished message and not call handler.
    """

    def __init__(self,
                 tz_name: str = "Africa/Addis_Ababa",
                 open_hour: int = 7,   # EAT opening hour (localizable)
                 close_hour: int = 24  # EAT closing hour (localizable)
                 ):
        self.tz_name = tz_name
        self.open_hour = open_hour
        self.close_hour = close_hour
        self.tz = pytz.timezone(self.tz_name)

    def _now_eat(self) -> datetime:
        return datetime.now(self.tz)

    def _is_weekly_break(self, now: datetime) -> bool:
        # Python weekday(): Monday=0 ... Sunday=6
        return now.weekday() == 6  # Sunday

    def _is_open_now(self, now: datetime) -> bool:
        if self._is_weekly_break(now):
            return False
        # Check hour range: open <= now.hour < close
        return (self.open_hour <= now.hour < self.close_hour)

    def _next_open_datetime(self, now: datetime) -> datetime:
        """
        Return next opening datetime (EAT).
        - If today before open_hour and not Sunday -> today at open_hour.
        - If today after close or it's Sunday -> find next day that's Mon-Sat and set open_hour.
        """
        if not self._is_weekly_break(now) and now.hour < self.open_hour:
            return now.replace(hour=self.open_hour, minute=0, second=0, microsecond=0)

        candidate = (now + timedelta(days=1)).replace(hour=self.open_hour, minute=0, second=0, microsecond=0)
        for _ in range(0, 8):
            if not self._is_weekly_break(candidate):
                return candidate
            candidate = (candidate + timedelta(days=1)).replace(hour=self.open_hour, minute=0, second=0, microsecond=0)

        # fallback
        return (now + timedelta(days=1)).replace(hour=self.open_hour, minute=0, second=0, microsecond=0)

    async def __call__(self, handler, event, data):
        """
        Aiogram v3 middleware calling convention:
        `handler` is next handler, `event` is Update / event-like, `data` is handler data dict.
        We'll inspect message or callback_query and block if closed.
        """
        now = self._now_eat()
        open_now = self._is_open_now(now)
        weekly_break = self._is_weekly_break(now)

        # Determine incoming user/message objects
        upd = event
        message = getattr(upd, "message", None)
        cbq = getattr(upd, "callback_query", None)

        # If shop is open, continue
        if open_now:
            data["shop_open"] = True
            data["shop_now"] = now
            return await handler(event, data)

        # Shop is closed (either weekly break or outside hours)
        if weekly_break:
            # Weekly Sunday message
            next_open_dt = self._next_open_datetime(now)
            open_str = next_open_dt.strftime("%A, %Y-%m-%d at %H:%M")
            text_lines = [
                "⏸️ *We're taking a short weekly break (Sunday).*",
                "",
                "🙏 *Thank you for visiting Plug Market Shop!* We take Sundays to rest and improve our service — this helps us serve you better during the week.",
                "",
                f"🔁 *We will reopen on {open_str} EAT.*",
                "",
                "📌 You can still send a message now — we'll respond as soon as we're back.",
                "📩 Support / Quick help: @plugmarketshop",
                "",
                "💖 Thanks for your patience — we'll be happy to help when we're back!"
            ]
            text = "\n".join(text_lines)
        else:
            # Daily closed message (outside daily hours)
            next_open_dt = self._next_open_datetime(now)
            open_str = next_open_dt.strftime("%Y-%m-%d %H:%M")
            text_lines = [
                "⏸️ *We are currently closed*",
                "",
                f"🔁 *We will re-open on {open_str} EAT.*",
                "",
                "🙏 *Thank you for visiting Plug Market Shop!* — we appreciate you stopping by.",
                "",
                "📌 Meanwhile you can:",
                "  • 📞 Contact our support: @plugmarketshop",
                "  • 🔔 Join announcements: @plugmarketshop1",
                "",
                "💡 *Tip:* Place your order now and upload payment proof — we'll process it as soon as we open.",
                "",
                "💖 Thanks for your patience — we'll be happy to help when we're back!",
                "",
                "✨ Thanks for choosing Plug Market Shop — fast, trusted, and secure."
            ]
            text = "\n".join(text_lines)

        # Send response and DO NOT call handler (blocks processing)
        try:
            if cbq:
                # For callback queries, answer the query with alert if possible
                try:
                    await cbq.answer(text, show_alert=True)
                except Exception:
                    if cbq.message:
                        try:
                            await cbq.message.reply(text, parse_mode="Markdown")
                        except Exception:
                            pass
            elif message:
                # Regular message: reply
                try:
                    await message.reply(text, parse_mode="Markdown")
                except Exception:
                    try:
                        await message.answer(text, parse_mode="Markdown")
                    except Exception:
                        pass
            else:
                # No message or callback: try send_message
                user_id = None
                if cbq and cbq.from_user:
                    user_id = cbq.from_user.id
                elif message and message.from_user:
                    user_id = message.from_user.id
                if user_id:
                    try:
                        await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
                    except Exception:
                        pass
        except Exception:
            # swallow to avoid crashing middleware
            pass

        # Block further processing
        return None

# Register middleware (Aiogram v3 style)
dp.update.middleware.register(ShopHoursMiddleware())  # enforce Ethiopia hours; adjust open_hour/close_hour in ctor if needed

# ------------------ SERVICE ROUTERS (import your modules) ------------------
# Keep these imports as you had them (they import their routers)
try:
    from tracker import tracker_router
except Exception:
    tracker_router = None

try:
    from usdt import router as usdt_router
except Exception:
    usdt_router = None

try:
    from tiktok import router as tiktok_router
except Exception:
    tiktok_router = None

try:
    from star_ton import router as star_ton_router
except Exception:
    star_ton_router = None

try:
    from alibaba_order import router as alibaba_order_router
except Exception:
    alibaba_order_router = None

# --- FIXED: import digital_products router correctly (previously had a naming bug) ---
try:
    from digital_products import router as digital_products_router
except Exception:
    digital_products_router = None

# Include routers only if successfully imported
if tracker_router:
    dp.include_router(tracker_router)
if usdt_router:
    dp.include_router(usdt_router)
if tiktok_router:
    dp.include_router(tiktok_router)
if star_ton_router:
    dp.include_router(star_ton_router)
if alibaba_order_router:
    dp.include_router(alibaba_order_router)
if digital_products_router:
    dp.include_router(digital_products_router)

# ------------------ START / MENU HANDLERS ------------------
@dp.message(Command("start"))
async def start_command(message: types.Message):
    # middleware already enforces hours.
    welcome_text = (
        "👋 *Welcome to Plug Market Shop!* \n\n"
        "🚀 Fast, reliable digital services in Ethiopia 🇪🇹.\n\n"
        "💬 From order to delivery — many orders processed within minutes ⏱️.\n"
        "💼 Secure, trustworthy, and handled with care.\n\n"
        "📍 No stress — tell us what you need, send payment, and relax.\n\n"
        "🎯 Fast • Reliable • Professional — Plug Market Shop promise.\n\n"
        "✅ We support Amharic 🇪🇹 and English 🇬🇧.\n\n"
        "Thank you for visiting Plug Market Shop — we appreciate your trust and support! 💖"
    )
    start_btn = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="▶️ Start", callback_data="select_language")]]
    )
    await message.answer(welcome_text, reply_markup=start_btn)


@dp.callback_query(lambda c: c.data == "select_language")
async def select_language(callback: types.CallbackQuery):
    lang_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"),
                          InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")]]
    )
    try:
        await callback.message.edit_text("🌍 Please select your language:", reply_markup=lang_kb)
    except Exception:
        await callback.message.answer("🌍 Please select your language:", reply_markup=lang_kb)
    await callback.answer()


def main_menu(lang: str) -> InlineKeyboardMarkup:
    if lang == "en":
        buttons = [
            [InlineKeyboardButton(text="🛒 Services", callback_data="services_en")],
            [InlineKeyboardButton(text="💻 Digital Products", callback_data="digital_en")],
            [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="select_language")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="🛒 አገልግሎቶች", callback_data="services_am")],
            [InlineKeyboardButton(text="💻 ዲጂታል እቃዎች", callback_data="digital_am")],
            [InlineKeyboardButton(text="📞 ድጋፍ ያግኙ", url="https://t.me/plugmarketshop")],
            [InlineKeyboardButton(text="🔙 ተመለስ", callback_data="select_language")]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(lambda c: c.data.startswith("lang_"))
async def show_main_menu(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    text = "🏠 Main Menu" if lang == "en" else "🏠 ዋና ማውጫ"
    try:
        await callback.message.edit_text(text, reply_markup=main_menu(lang))
    except Exception:
        await callback.message.answer(text, reply_markup=main_menu(lang))
    await callback.answer()


def services_menu(lang: str) -> InlineKeyboardMarkup:
    if lang == "en":
        buttons = [
            [InlineKeyboardButton(text="💵 Buy/Sell USDT", callback_data="usdt_menu_en")],
            [InlineKeyboardButton(text="⭐ Buy Star & Ton", callback_data="star_menu_en")],
            [InlineKeyboardButton(text="📦 Order Products from AliExpress", callback_data="alibaba_menu_en")],
            [InlineKeyboardButton(text="💎 Get Telegram Premium", callback_data="telegram_menu_en")],
            [InlineKeyboardButton(text="🎵 Buy TikTok Coins", callback_data="tiktok_menu_en")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="lang_en")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="💵 USDT ግዢ/ሽያጭ", callback_data="usdt_menu_am")],
            [InlineKeyboardButton(text="⭐ Star እና TON ግዛ", callback_data="star_menu_am")],
            [InlineKeyboardButton(text="📦 ከ AliExpress ዕቃዎች ለማዘዝ", callback_data="alibaba_menu_am")],
            [InlineKeyboardButton(text="💎 የTelegram Premium ይግዙ", callback_data="telegram_menu_am")],
            [InlineKeyboardButton(text="🎵 TikTok ኮይኖችን ለመግዛት", callback_data="tiktok_menu_am")],
            [InlineKeyboardButton(text="🔙 ተመለስ", callback_data="lang_am")]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(lambda c: c.data.startswith("services_"))
async def show_services(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    text = "🛒 Services Menu" if lang == "en" else "🛒 የአገልግሎት ማውጫ"
    try:
        await callback.message.edit_text(text, reply_markup=services_menu(lang))
    except Exception:
        await callback.message.answer(text, reply_markup=services_menu(lang))
    await callback.answer()

# -----------------------------------------------------------------------------------------------

# ------------------ RUN BOT ------------------
async def main():
    print("✅ Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
