# tiktok.py
# TikTok Coin purchase flow for Aiogram v3
# Fully FSM-based, Amharic & English, full back/cancel support, admin notifications
# Tracker integration: records orders/events to tracker via record_order()

import json
import os
from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# Tracker integration (optional - wrapped in try/except so file still runs if tracker not present)
try:
    from tracker import record_order, find_order_by_id  # tracker.py must be in same project
except Exception:
    record_order = None
    find_order_by_id = None

router = Router()
tiktok_router = router  # alias for import convenience

# ---------- CONFIG ----------
ADMIN_ID = 6968325481
SUPPORT_USERNAME = "plugmarketshop"
SUPPORT_LINK = f"https://t.me/{SUPPORT_USERNAME}"

CBE_ACCOUNT = "1000476183921"
CBE_NAME = "Aschalew Desta"

TELEBIRR_NUMBER = "0916253200"
TELEBIRR_NAME = "Aschalew Desta"

MIN_COINS = 100
COINS_BASE = 100
ETB_BASE = 265.0  # 100 coins = 270 ETB

ORDERS_FILE = "tiktok_orders.json"
ORDERS: Dict[str, Dict[str, Any]] = {}

# ---------- Persistence helpers ----------
def load_orders() -> None:
    global ORDERS
    try:
        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                ORDERS = json.load(f)
        else:
            ORDERS = {}
    except Exception:
        ORDERS = {}

def save_orders() -> None:
    try:
        with open(ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(ORDERS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

load_orders()

# ---------- FSM States ----------
class TikTokStates(StatesGroup):
    waiting_amount = State()
    waiting_payment_choice = State()
    waiting_payment_proof = State()
    waiting_user_after_paid = State()  # used for username -> login info flow

# ---------- Keyboard helpers ----------
def kb_back_to_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🔙 Back" if lang == "en" else "🔙 ተመለስ"),
                              callback_data="tiktok_back_to_menu")]
    ])

def kb_payment_methods(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=("🏦 CBE Bank" if lang == "en" else "🏦 CBE ባንክ"),
                              callback_data="tiktok_pay_cbe")],
        [InlineKeyboardButton(text="📱 Telebirr", callback_data="tiktok_pay_telebirr")],
        [InlineKeyboardButton(text=("❌ Cancel" if lang == "en" else "❌ ሰርዝ"),
                              callback_data="tiktok_cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_done_back_cancel(lang: str, total: Optional[float] = None, account_copy: Optional[str] = None) -> InlineKeyboardMarkup:
    # include copy buttons for total/account if provided (for user)
    rows = []
    copy_row = []
    if total is not None:
        copy_row.append(InlineKeyboardButton(text="📋 Copy Amount", callback_data=f"copy_val:{total:.2f}"))
    if account_copy is not None:
        copy_row.append(InlineKeyboardButton(text="📋 Copy Account", callback_data=f"copy_val:{account_copy}"))
    if copy_row:
        rows.append(copy_row)

    # Done / Back / Cancel rows
    rows.append([InlineKeyboardButton(text="✅ Done", callback_data="tiktok_done")])
    rows.append([
        InlineKeyboardButton(text=("◀ Back" if lang == "en" else "◀ ተመለስ"),
                             callback_data="tiktok_back_methods"),
        InlineKeyboardButton(text=("❌ Cancel" if lang == "en" else "❌ ሰርዝ"),
                             callback_data="tiktok_cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# NEW: Back keyboard for the "upload proof" page -> returns to previous payment detail page
def kb_proof_back(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("◀ Back" if lang == "en" else "◀ ተመለስ"),
                              callback_data="tiktok_back_to_detail")],
        [InlineKeyboardButton(text=("❌ Cancel" if lang == "en" else "❌ ሰርዝ"),
                              callback_data="tiktok_cancel")]
    ])

# Admin initial keyboard (only Paid / Not Paid)
def kb_admin_initial(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Paid", callback_data=f"admin_paid:{order_id}"),
         InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_notpaid:{order_id}")]
    ])

# Admin keyboard after user provided username & login: Payment Completed + copy buttons (coin amount, login info)
def kb_admin_after_login(order_id: str, coin_amount: int, login_info: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✅ Payment Completed", callback_data=f"admin_complete:{order_id}")],
        [
            InlineKeyboardButton(text="📋 Copy Coin Amount", callback_data=f"copy_val:{coin_amount}"),
            InlineKeyboardButton(text="📋 Copy Login Info", callback_data=f"copy_val:{login_info}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_user_after_paid(order_id: str, lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=("📞 Contact Support" if lang == "en" else "📞 ድጋፍ አግኙ"), url=SUPPORT_LINK)],
        [InlineKeyboardButton(text=("📤 Send Login Info to Admin" if lang == "en" else "📤 መግቢያ/login መረጃ ለአስተዳዳሪ ይላኩ"),
                              callback_data=f"user_sent_login:{order_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_contact_support(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("📞 Contact Support" if lang == "en" else "📞 ድጋፍ አግኙ"), url=SUPPORT_LINK)]
    ])

# ---------- Utilities ----------
def get_lang(data: Dict[str, Any], user_lang_code: Optional[str]) -> str:
    lang = data.get("lang")
    if lang:
        return lang
    if not user_lang_code:
        return "en"
    return "am" if user_lang_code.lower().startswith("am") else "en"

def fmt_total(amount: int) -> float:
    return round(amount * (ETB_BASE / COINS_BASE), 2)

def _start_text(lang: str) -> str:
    if lang == "en":
        return (
            "🎵 Buy TikTok Coins\n\n"
            f"Minimum: {MIN_COINS} coins\n\n"
            "Please enter the amount of TikTok Coins you want to purchase."
        )
    else:
        return (
            "🎵 የTikTok ኮይን ለመግዛት\n\n"
            f"ቢያንስ: {MIN_COINS} ኮይን\n\n"
            "እባክዎ የሚፈልጉትን የTikTok ኮይን መጠን ያስገቡ።"
        )

# ---------- Local Services menu helper (mirror of main.services_menu)
# We need this so "Back" can return the user to the Services menu without importing main.py.
def services_menu_local(lang: str) -> InlineKeyboardMarkup:
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

# ---------- Copy handler ----------
@router.callback_query(F.data.startswith("copy_val:"))
async def generic_copy_handler(cb: CallbackQuery):
    raw = cb.data.split(":", 1)[1]
    try:
        # send as code block so user can long-press to copy
        await cb.message.answer(f"`{raw}`", parse_mode="Markdown")
    except Exception:
        try:
            await cb.message.answer(raw)
        except Exception:
            try:
                await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=raw)
            except Exception:
                pass
    await cb.answer("Value shown (long-press to copy).", show_alert=False)

# ---------- Entry callbacks ----------
@router.callback_query(F.data == "tiktok_menu_en")
async def entry_en(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(lang="en")
    try:
        await cb.message.edit_text(_start_text("en"), reply_markup=kb_back_to_menu("en"))
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=_start_text("en"), reply_markup=kb_back_to_menu("en"))
    await state.set_state(TikTokStates.waiting_amount)
    await cb.answer()

@router.callback_query(F.data == "tiktok_menu_am")
async def entry_am(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(lang="am")
    try:
        await cb.message.edit_text(_start_text("am"), reply_markup=kb_back_to_menu("am"))
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=_start_text("am"), reply_markup=kb_back_to_menu("am"))
    await state.set_state(TikTokStates.waiting_amount)
    await cb.answer()

@router.callback_query(F.data == "tiktok_back_to_menu")
async def back_to_menu(cb: CallbackQuery, state: FSMContext):
    """
    FIXED: Previously this returned to the TikTok start text which could cause users to remain in the
    TikTok flow and also sometimes produced 'message is not modified' errors when the content/markup
    was identical. Now this explicitly returns the user to the Services menu (matching main.py behavior).
    If editing the message fails due to "message is not modified", we fallback to sending a fresh message.
    """
    data = await state.get_data()
    lang = get_lang(data, cb.from_user.language_code)

    # Show the services menu (same layout as main.services_menu)
    services_text = "🛒 Services Menu" if lang == "en" else "🛒 የአገልግሎት ማውጫ"
    kb = services_menu_local(lang)

    try:
        await cb.message.edit_text(services_text, reply_markup=kb)
    except Exception:
        # Fallback: send a new message to the user (avoids TelegramBadRequest: message is not modified)
        try:
            await cb.bot.send_message(chat_id=cb.from_user.id, text=services_text, reply_markup=kb)
        except Exception:
            # Last resort: ignore
            pass

    # Clear any TikTok-specific FSM state when leaving the TikTok flow
    try:
        await state.clear()
    except Exception:
        pass

    await cb.answer()

# ---------- Amount handler ----------
@router.message(TikTokStates.waiting_amount)
async def handle_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data, message.from_user.language_code)
    text = (message.text or "").strip()

    amount: Optional[int] = None
    try:
        amount = int(float(text))
    except Exception:
        import re
        m = re.search(r"\d+(\.\d+)?", text.replace(",", ""))
        if m:
            try:
                amount = int(float(m.group()))
            except Exception:
                amount = None

    if amount is None:
        await message.reply("❌ Please enter a valid number." if lang == "en" else "❌ እባክዎ ትክክለኛ ቁጥር ያስገቡ።")
        return

    if amount < MIN_COINS:
        await message.reply(
            f"⚠️ Minimum is {MIN_COINS} coins. Please enter again." if lang == "en"
            else f"⚠️ ቢያንስ {MIN_COINS} ኮይን ያስገቡ።"
        )
        return

    total_etb = fmt_total(amount)
    await state.update_data(amount=amount, total_etb=total_etb)

    if lang == "en":
        await message.answer(
            f"💳 Total Price: `{total_etb:.2f}` ETB\n\nPlease choose your payment method:",
            reply_markup=kb_payment_methods(lang),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"💳 ጠቅላላ ዋጋ: `{total_etb:.2f}` ብር\n\nየመክፈያ ዘዴ ይምረጡ፦",
            reply_markup=kb_payment_methods(lang),
            parse_mode="Markdown"
        )
    await state.set_state(TikTokStates.waiting_payment_choice)

# ---------- Payment choice handlers ----------
@router.callback_query(TikTokStates.waiting_payment_choice, F.data == "tiktok_pay_cbe")
async def pay_cbe(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data, cb.from_user.language_code)
    total = data.get("total_etb", 0.0)

    acct_en = (
        "🏦 Bank: Commercial Bank of Ethiopia\n"
        f"📄 Name: `{CBE_NAME}`\n"
        f"💳 Account: `{CBE_ACCOUNT}`"
    )
    acct_am = (
        "🏦 ባንክ: Commercial Bank of Ethiopia\n"
        f"📄 ስም: `{CBE_NAME}`\n"
        f"💳 አካውንት: `{CBE_ACCOUNT}`"
    )

    if lang == "en":
        text = (
            f"💳 Total to pay: *{total:.2f}* ETB\n\n"
            f"{acct_en}\n\n"
            "Please send the total amount to the account above. Once paid, click *✅ Done*."
        )
    else:
        text = (
            f"💳 የሚክፈሉት ጠቅላላ መጠን: *{total:.2f}* ብር\n\n"
            f"{acct_am}\n\n"
            "እባክዎ ጠቅላላውን መጠን ይላኩ። ክፍያ ካጨረሱ *✅ Done* ይጫኑ።"
        )

    # include copy buttons for user (total & account)
    try:
        await cb.message.edit_text(text, reply_markup=kb_done_back_cancel(lang, total=total, account_copy=CBE_ACCOUNT), parse_mode="Markdown")
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=text, reply_markup=kb_done_back_cancel(lang, total=total, account_copy=CBE_ACCOUNT), parse_mode="Markdown")
    await state.update_data(payment_method="CBE")
    await state.set_state(TikTokStates.waiting_payment_proof)
    await cb.answer()

@router.callback_query(TikTokStates.waiting_payment_choice, F.data == "tiktok_pay_telebirr")
async def pay_telebirr(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data, cb.from_user.language_code)
    total = data.get("total_etb", 0.0)

    acct_en = (
        f"📱 Telebirr Number: `{TELEBIRR_NUMBER}`\n"
        f"📄 Name: `{TELEBIRR_NAME}`"
    )
    acct_am = (
        f"📱 ቴሌብር ቁጥር: `{TELEBIRR_NUMBER}`\n"
        f"📄 ስም: `{TELEBIRR_NAME}`"
    )

    if lang == "en":
        text = (
            f"💳 Total to pay: *{total:.2f}* ETB\n\n"
            f"{acct_en}\n\n"
            "Please send the total amount to the account above. Once paid, click *✅ Done*."
        )
    else:
        text = (
            f"💳 የሚክፈሉት ጠቅላላ መጠን: *{total:.2f}* ብር\n\n"
            f"{acct_am}\n\n"
            "እባክዎ ጠቅላላውን መጠን ይላኩ። ክፍያ ካጨረሱ *✅ Done* ይጫኑ።"
        )

    try:
        await cb.message.edit_text(text, reply_markup=kb_done_back_cancel(lang, total=total, account_copy=TELEBIRR_NUMBER), parse_mode="Markdown")
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=text, reply_markup=kb_done_back_cancel(lang, total=total, account_copy=TELEBIRR_NUMBER), parse_mode="Markdown")
    await state.update_data(payment_method="Telebirr")
    await state.set_state(TikTokStates.waiting_payment_proof)
    await cb.answer()

@router.callback_query(F.data == "tiktok_back_methods")
async def back_methods(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data, cb.from_user.language_code)
    try:
        await cb.message.edit_text(
            "Please choose your payment method:" if lang == "en" else "የመክፈያ ዘዴ ይምረጡ፦",
            reply_markup=kb_payment_methods(lang)
        )
    except Exception:
        await cb.bot.send_message(
            chat_id=cb.from_user.id,
            text="Please choose your payment method:" if lang == "en" else "የመክፈያ ዘዴ ይምረጡ፦",
            reply_markup=kb_payment_methods(lang)
        )
    await state.set_state(TikTokStates.waiting_payment_choice)
    await cb.answer()

@router.callback_query(F.data == "tiktok_cancel")
async def cancel_flow(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data, cb.from_user.language_code)
    try:
        await cb.message.edit_text("❌ Your order has been cancelled." if lang == "en" else "❌ ትእዛዝዎ ተሰርዟል።")
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text="❌ Your order has been cancelled." if lang == "en" else "❌ ትእዛዝዎ ተሰርዟል።")
    await state.clear()
    await cb.answer()

# ---------- Done button -> ask for proof ----------
@router.callback_query(TikTokStates.waiting_payment_proof, F.data == "tiktok_done")
async def done_payment(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data, cb.from_user.language_code)
    text_en = "📤 Please upload a screenshot as proof of payment."
    text_am = "📤 የክፍያ ማረጋገጫ ስክሪንሾት ያስገቡ።"
    try:
        await cb.message.edit_text(text_en if lang == "en" else text_am, reply_markup=kb_proof_back(lang))
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=text_en if lang == "en" else text_am, reply_markup=kb_proof_back(lang))
    await cb.answer()

# NEW: From proof page, go back to the payment detail page (CBE/Telebirr)
@router.callback_query(TikTokStates.waiting_payment_proof, F.data == "tiktok_back_to_detail")
async def back_to_detail(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data, cb.from_user.language_code)
    total = data.get("total_etb", 0.0)
    method = data.get("payment_method")

    if not method:
        # If for some reason method is missing, go back to method list
        try:
            await cb.message.edit_text(
                "Please choose your payment method:" if lang == "en" else "የመክፈያ ዘዴ ይምረጡ፦",
                reply_markup=kb_payment_methods(lang)
            )
        except Exception:
            await cb.bot.send_message(chat_id=cb.from_user.id,
                                      text="Please choose your payment method:" if lang == "en" else "የመክፈያ ዘዴ ይምረጡ፦",
                                      reply_markup=kb_payment_methods(lang))
        await state.set_state(TikTokStates.waiting_payment_choice)
        await cb.answer()
        return

    if method == "CBE":
        acct_en = (
            "🏦 Bank: Commercial Bank of Ethiopia\n"
            f"📄 Name: `{CBE_NAME}`\n"
            f"💳 Account: `{CBE_ACCOUNT}`"
        )
        acct_am = (
            "🏦 ባንክ: Commercial Bank of Ethiopia\n"
            f"📄 ስም: `{CBE_NAME}`\n"
            f"💳 አካውንት: `{CBE_ACCOUNT}`"
        )
        text = (
            f"💳 Total to pay: *{total:.2f}* ETB\n\n{acct_en}\n\nPlease send the total amount to the account above. Once paid, click *✅ Done*."
            if lang == "en" else
            f"💳 የሚክፈሉት ጠቅላላ መጠን: *{total:.2f}* ብር\n\n{acct_am}\n\nእባክዎ ጠቅላላውን መጠን ይላኩ። ክፍያ ካጨረሱ *✅ Done* ይጫኑ።"
        )
        kb = kb_done_back_cancel(lang, total=total, account_copy=CBE_ACCOUNT)
    else:
        acct_en = (
            f"📱 Telebirr Number: `{TELEBIRR_NUMBER}`\n"
            f"📄 Name: `{TELEBIRR_NAME}`"
        )
        acct_am = (
            f"📱 ቴሌብር ቁጥር: `{TELEBIRR_NUMBER}`\n"
            f"📄 ስም: `{TELEBIRR_NAME}`"
        )
        text = (
            f"💳 Total to pay: *{total:.2f}* ETB\n\n{acct_en}\n\nPlease send the total amount to the account above. Once paid, click *✅ Done*."
            if lang == "en" else
            f"💳 የሚክፈሉት ጠቅላላ መጠን: *{total:.2f}* ብር\n\n{acct_am}\n\nእባክዎ ጠቅላላውን መጠን ይላኩ። ክፍያ ካጨረሱ *✅ Done* ይጫኑ።"
        )
        kb = kb_done_back_cancel(lang, total=total, account_copy=TELEBIRR_NUMBER)

    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=text, reply_markup=kb, parse_mode="Markdown")

    # Keep user in proof flow (so Done/Back/Cancel still work)
    await state.set_state(TikTokStates.waiting_payment_proof)
    await cb.answer()

# ---------- Payment proof ----------
@router.message(TikTokStates.waiting_payment_proof, F.photo)
async def handle_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data, message.from_user.language_code)
    amount = data.get("amount")
    total = data.get("total_etb")
    pay_method = data.get("payment_method")
    order_id = str(uuid4())[:8]

    proof_file_id = message.photo[-1].file_id if message.photo else None

    # Save order
    ORDERS[order_id] = {
        "user_id": message.from_user.id,
        "username": message.from_user.username or "",
        "amount": amount,
        "total": total,
        "payment_method": pay_method,
        "status": "waiting_admin",
        "lang": lang,
        "created_at": datetime.utcnow().isoformat(),
        "proof_file_id": proof_file_id,
        "tiktok_username": "",
        "login_info": ""
    }
    save_orders()

    # Record to tracker (if available)
    try:
        if record_order:
            record_order("tiktok", {
                "order_id": order_id,
                "user_id": message.from_user.id,
                "username": message.from_user.username or "",
                "amount": amount,
                "currency": "TIKTOK_COINS",
                "etb": total,
                "payment_method": pay_method,
                "status": "waiting_admin",
                "created_at": datetime.utcnow()
            })
    except Exception:
        # non-fatal: continue even if tracker fails
        pass

    # Send to admin: initial notification (ONLY Paid / Not Paid)
    admin_caption = (
        "🎵 New TikTok Coin order\n\n"
        f"👤 User: @{message.from_user.username or 'N/A'} (ID: {message.from_user.id})\n"
        f"🧮 Amount: {amount} coins\n"
        f"💳 Total: {total:.2f} ETB\n"
        f"🏦 Payment: {pay_method}\n"
        f"📅 Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"🆔 Order ID: {order_id}"
    )

    # Use message.bot (avoid Router.bot attribute issues)
    await message.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=proof_file_id,
        caption=admin_caption,
        reply_markup=kb_admin_initial(order_id)
    )

    # Confirm to user
    msg_user = (
        "✅ Payment proof sent! Please wait for admin confirmation."
        if lang == "en" else
        "✅ የክፍያ ማረጋገጫ ተልኳል! እባክዎ የአስተዳዳሪ ማረጋገጫን ይጠብቁ።"
    )
    await message.reply(msg_user, reply_markup=kb_contact_support(lang))
    await state.clear()

# ---------- Helpers for "order found" checks ----------
def _is_order_accessible(order_id: str) -> bool:
    """Return True if order exists and is NOT completed (i.e., actions allowed)."""
    order = ORDERS.get(order_id)
    if not order:
        return False
    if order.get("status") == "completed":
        return False
    return True

# ---------- Admin callbacks ----------
@router.callback_query(F.data.startswith("admin_paid:"))
async def admin_paid(cb: CallbackQuery):
    order_id = cb.data.split(":")[1]
    if not _is_order_accessible(order_id):
        await cb.answer("Order not found", show_alert=True)
        return

    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("❌ Order not found", show_alert=True)
        return

    order["status"] = "paid"
    save_orders()

    # Record status change to tracker (if available)
    try:
        if record_order:
            record_order("tiktok", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": order.get("amount"),
                "currency": "TIKTOK_COINS",
                "etb": order.get("total"),
                "payment_method": order.get("payment_method"),
                "status": "paid",
                "created_at": datetime.utcnow()
            })
    except Exception:
        pass

    user_id = order["user_id"]
    lang = order.get("lang", "en")

    msg = (
        "✅ Your order is successfully created!\n\n"
        "To receive your TikTok Coins, please tap *Contact Support* and type *TikTok Coin*.\n"
        "Support will request your TikTok account login info."
        if lang == "en"
        else
        "✅ ትእዛዝዎ Create ተደርጎዋል!\n\n"
        "የTikTok ኮይኖች ለማግኘት *ድጋፍ አግኙ* ይጫኑ እና *TikTok Coin* ይላኩ።"
    )

    await cb.bot.send_message(
        chat_id=user_id,
        text=msg,
        reply_markup=kb_user_after_paid(order_id, lang),
        parse_mode="Markdown"
    )
    await cb.answer("Marked as Paid", show_alert=True)

@router.callback_query(F.data.startswith("admin_notpaid:"))
async def admin_notpaid(cb: CallbackQuery):
    order_id = cb.data.split(":")[1]
    if not _is_order_accessible(order_id):
        await cb.answer("Order not found", show_alert=True)
        return

    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("❌ Order not found", show_alert=True)
        return

    order["status"] = "not_paid"
    save_orders()

    # Record status to tracker
    try:
        if record_order:
            record_order("tiktok", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": order.get("amount"),
                "currency": "TIKTOK_COINS",
                "etb": order.get("total"),
                "payment_method": order.get("payment_method"),
                "status": "not_paid",
                "created_at": datetime.utcnow()
            })
    except Exception:
        pass

    user_id = order["user_id"]
    lang = order.get("lang", "en")

    msg = (
        "⚠️ Payment not received. Please pay and try again."
        if lang == "en" else
        "⚠️ ክፍያ አልተቀበለም። እባክዎ ይክፈሉ እና እንደገና ይሞክሩ።"
    )

    await cb.bot.send_message(chat_id=user_id, text=msg, reply_markup=kb_contact_support(lang))
    await cb.answer("Marked as Not Paid", show_alert=True)

@router.callback_query(F.data.startswith("admin_complete:"))
async def admin_complete(cb: CallbackQuery):
    order_id = cb.data.split(":")[1]
    # If already completed or not found, treat as not found
    if not _is_order_accessible(order_id):
        await cb.answer("Order not found", show_alert=True)
        return

    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("❌ Order not found", show_alert=True)
        return

    order["status"] = "completed"
    order["completed_at"] = datetime.utcnow().isoformat()
    save_orders()

    # Record completion to tracker (if available)
    try:
        if record_order:
            record_order("tiktok", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": order.get("amount"),
                "currency": "TIKTOK_COINS",
                "etb": order.get("total"),
                "payment_method": order.get("payment_method"),
                "status": "completed",
                "direction": "sent",
                "extra": {"tiktok_username": order.get("tiktok_username", ""), "login_info": order.get("login_info", "")},
                "created_at": datetime.utcnow()
            })
    except Exception:
        pass

    user_id = order["user_id"]
    lang = order.get("lang", "en")
    coins = order.get("amount", 0)
    tiktok_username = order.get("tiktok_username", "").strip() or "@YourTikTok"

    if lang == "en":
        msg = (
            "🎉 Congratulations! Your TikTok Coins have been successfully added.\n\n"
            f"👤 TikTok: `{tiktok_username}`\n"
            f"💰 Amount Sent: *{coins}* coins\n"
            "🏅 Check your TikTok balance!\n\n"
            "💬 If you have any questions, click *Contact Support*.\n"
            "🙏 Thanks for trading with us!"
        )
    else:
        msg = (
            "🎉 እንኳን ደስ አለዎት! የTikTok ኮይኖችዎ በተሳካ ሁኔታ ተልኳል።\n\n"
            f"👤 TikTok: `{tiktok_username}`\n"
            f"💰 የተላከው መጠን: *{coins}* ኮይን\n"
            "🏅 የTikTok መለያ ቀር ህሳቦን ያረጋግጡ!\n\n"
            "💬 ጥያቄ ካለዎት *ድጋፍ አግኙ* ይጫኑ።\n"
            "🙏 ከእኛ ስላዘዙ እናመሰግናለን!"
        )

    # Add join channel button plus contact support
    join_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("📞 Contact Support" if lang == "en" else "📞 ድጋፍ አግኙ"), url=SUPPORT_LINK)],
        [InlineKeyboardButton(text=("🔔 Join Channel" if lang == "en" else "🔔 ለዜና ቻናል ይቀላቀሉ"), url="https://t.me/plugmarketshop1")]
    ])

    await cb.bot.send_message(chat_id=user_id, text=msg, reply_markup=join_btn, parse_mode="Markdown")
    await cb.answer("Marked as Completed", show_alert=True)

# ---------- User sends login info to admin (username first, then login info) ----------
@router.callback_query(F.data.startswith("user_sent_login:"))
async def user_sent_login(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split(":")[1]
    order = ORDERS.get(order_id)
    # If order not found or completed -> say "order not found"
    if not _is_order_accessible(order_id):
        await cb.answer("Order not found", show_alert=True)
        return

    if not order:
        await cb.answer("❌ Order not found", show_alert=True)
        return

    lang = order.get("lang", "en")
    # Ask for TikTok username first
    prompt_username = (
        "📤 Please type your TikTok username (e.g. @username). After that you'll be asked for login info."
        if lang == "en" else
        "📤 እባክዎ የTikTok መለያዎን (ለምሳሌ @username) ያስገቡ። ከዚያ በኋላ የመግቢያ/Login መረጃ ይጠይቃል።"
    )

    # Provide Back button here to return to after-paid menu (fix for the reported issue)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("◀ Back" if lang == "en" else "◀ ተመለስ"), callback_data=f"user_sent_login_back:{order_id}")]
    ])

    try:
        await cb.message.edit_text(prompt_username, reply_markup=back_kb)
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=prompt_username, reply_markup=back_kb)
    # store order we are expecting and stage
    await state.update_data(current_order_id=order_id, login_stage="username")
    await state.set_state(TikTokStates.waiting_user_after_paid)
    await cb.answer()

@router.callback_query(F.data.startswith("user_sent_login_back:"))
async def user_sent_login_back(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split(":")[1]
    # If order not found or completed -> say "order not found"
    if not _is_order_accessible(order_id):
        await cb.answer("Order not found", show_alert=True)
        return

    order = ORDERS.get(order_id)
    if not order:
        await cb.answer("❌ Order not found", show_alert=True)
        return

    lang = order.get("lang", "en")
    try:
        await cb.message.edit_text("Choose an option:" if lang == "en" else "አንዱን ይምረጡ።", reply_markup=kb_user_after_paid(order_id, lang))
    except Exception:
        try:
            await cb.bot.send_message(chat_id=order["user_id"], text="Choose an option:" if lang == "en" else "አንዱን ይምረጡ።", reply_markup=kb_user_after_paid(order_id, lang))
        except Exception:
            pass
    await state.clear()
    await cb.answer()

@router.message(TikTokStates.waiting_user_after_paid)
async def receive_user_login(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("current_order_id")
    stage = data.get("login_stage")  # "username" or "login"

    # fallback: if state lost order_id, find latest paid order for this user
    if not order_id:
        for oid, o in reversed(list(ORDERS.items())):
            if o.get("user_id") == message.from_user.id and o.get("status") == "paid":
                order_id = oid
                break

    if not order_id or order_id not in ORDERS:
        await message.reply("❌ No pending paid order found.", reply_markup=None)
        await state.clear()
        return

    # If order is completed or missing, inform user "order not found"
    if not _is_order_accessible(order_id):
        await message.reply("❌ Order not found", reply_markup=None)
        await state.clear()
        return

    order = ORDERS[order_id]
    lang = order.get("lang", "en")
    text = (message.text or "").strip()

    if not stage or stage == "username":
        # store username and ask for login info
        order["tiktok_username"] = text
        save_orders()
        # prompt for login info
        prompt_login = (
            "📤 Now please type your TikTok login info (email/phone & password). This will be forwarded to admin."
            if lang == "en" else
            "📤 እባክዎ አሁን የTikTok መግቢያ/Login መረጃዎን (ኢሜል/ስልክ & Password) ያስገቡ።"
        )
        await message.reply(prompt_login)
        await state.update_data(login_stage="login", current_order_id=order_id)
        return

    # stage == "login"
    if text.lower() == "skip":
        order["login_info"] = ""
    else:
        order["login_info"] = text
    save_orders()

    # Forward BOTH username and login info to admin.
    # Per request: do NOT include Paid/NotPaid under this admin message.
    # Include only Payment Completed button and copy buttons for coin amount and login info.
    coin_amount = order.get("amount", 0)
    login_info_val = order.get("login_info", "") or "N/A"
    t_username = order.get("tiktok_username", "")

    admin_msg = (
        f"📤 TikTok credentials from @{message.from_user.username or 'N/A'}\n\n"
        f"Username: `{t_username}`\n"
        f"Login info: `{login_info_val}`\n"
        f"Order ID: {order_id}\n"
        f"Amount: {coin_amount} coins\n"
    )

    # Send to admin with Payment Completed + copy coin & copy login info
    await message.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_msg,
        parse_mode="Markdown",
        reply_markup=kb_admin_after_login(order_id, coin_amount, login_info_val)
    )

    # Optionally record that credentials were provided (tracker)
    try:
        if record_order:
            record_order("tiktok", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": order.get("amount"),
                "currency": "TIKTOK_COINS",
                "etb": order.get("total"),
                "payment_method": order.get("payment_method"),
                "status": "credentials_sent",
                "extra": {"tiktok_username": t_username, "login_info_present": bool(login_info_val and login_info_val != "N/A")},
                "created_at": datetime.utcnow()
            })
    except Exception:
        pass

    # Confirm to user
    confirm = "✅ Info sent to admin!" if lang == "en" else "✅ መረጃ ለአስተዳዳሪ ተልኳል!"
    await message.reply(confirm, reply_markup=kb_contact_support(order.get("lang", "en")))
    await state.clear()

# ---------- Fallback: any other user callbacks that try to act on completed orders ----------
# (Generic protection for other user callbacks can be added as needed. The main required user action
# here was user_sent_login — we've guarded that. Admin buttons are guarded above.)

# End of file
