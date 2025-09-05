# main.py
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# === SERVICE IMPORTS ===
from usdt import router as usdt_router
from star_ton import router as star_ton_router
from alibaba_order import router as alibaba_order_router
from tiktok import router as tiktok_router
from telegram_premium import router as telegram_premium_router

# === OWNER / ADMIN IDS ===
OWNER_ID = 6781140962
ADMIN_ID = 6968325481

# === BOT TOKEN ===
BOT_TOKEN = "8198129558:AAFt8HoXUBmJU4OkpWHb4RCCnziR_Yry8F8"

# === BOT & DISPATCHER ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# === START COMMAND ===
@dp.message(Command("start"))
async def start_command(message: types.Message):
    welcome_text = (
        "👋 Welcome to Plug Market Shop!\n\n"
        "🚀 Fastest and most reliable digital services in Ethiopia 🇪🇹.\n\n"
        "💬 From order to delivery — everything is done in under 20 minutes ⏱️.\n"
        "💼 100% safe, secure, and handled with care.\n"
        "💳 Pay in ETB — we handle the rest.\n"
        "🛡 Trusted by hundreds of happy customers daily.\n\n"
        "📍 No stress, no complicated steps — just tell us what you need, send your payment, and relax.\n\n"
        "🎯 Fast • Reliable • Professional — Plug Market Shop promise.\n\n"
        "✅ Full support in Amharic 🇪🇹 and English 🇬🇧."
    )
    start_btn = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="▶️ Start", callback_data="select_language")]]
    )
    await message.answer(welcome_text, reply_markup=start_btn)

# === LANGUAGE SELECTION ===
@dp.callback_query(F.data == "select_language")
async def select_language(callback: types.CallbackQuery):
    lang_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"),
                InlineKeyboardButton(text="🇪🇹 አማርኛ", callback_data="lang_am")
            ]
        ]
    )
    await callback.message.edit_text("🌍 Please select your language:", reply_markup=lang_kb)

# === MAIN MENU ===
def main_menu(lang):
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

@dp.callback_query(F.data.startswith("lang_"))
async def show_main_menu(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    text = "🏠 Main Menu" if lang == "en" else "🏠 ዋና ማውጫ"
    await callback.message.edit_text(text, reply_markup=main_menu(lang))

# === SERVICES MENU ===
def services_menu(lang):
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

@dp.callback_query(F.data.startswith("services_"))
async def show_services(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    text = "🛒 Services Menu" if lang == "en" else "🛒 የአገልግሎት ማውጫ"
    await callback.message.edit_text(text, reply_markup=services_menu(lang))

# === REPORT COMMAND ===
@dp.message(Command("report"))
async def report_command(message: types.Message):
    if message.from_user.id not in [OWNER_ID, ADMIN_ID]:
        await message.reply("❌ You are not allowed to view reports.")
        return
    args = message.text.strip().split(maxsplit=1)
    date_str = args[1] if len(args) > 1 else None
    await message.reply(f"📊 Report requested for: {date_str or 'today'}")

# === REGISTER ALL SERVICE ROUTERS ===
dp.include_router(usdt_router)
dp.include_router(star_ton_router)
dp.include_router(alibaba_order_router)
dp.include_router(tiktok_router)
dp.include_router(telegram_premium_router)  # order no longer matters

# === RUN BOT ===
async def main():
    print("✅ Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
