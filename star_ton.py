# star_ton.py (fixed & hardened)
# Notes:
#  - This is the user's original module with targeted fixes to make the "Buy Star & TON" entry button responsive.
#  - Improvements:
#      * open_star_ton_menu now accepts a wider set of callback_data variants and also accepts direct text commands
#        (in case the services menu uses slightly different callback strings).
#      * All callback handlers answer the callback to stop Telegram's loading spinner.
#      * Defensive handling when cb.message is None (fallback to send_message).
#      * Slight typing and persistence safety preserved.
#
# Keep this file as a drop-in replacement for the user's original star_ton.py.

import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Router, F, types
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, ContentType
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

router = Router()
logger = logging.getLogger(__name__)

# ---------- Tracker integration (safe import) ----------
try:
    from tracker import record_event, record_order, find_order_by_id
except Exception:
    record_event = None
    record_order = None
    find_order_by_id = None

# -------------------- Config / Constants --------------------
ADMIN_ID = 6968325481

# Prices (ETB)
STAR_PRICE = 2.27   # ETB per 1 Star (example)
TON_PRICE = 540.0   # ETB per 1 TON (example)

CBE_ACCOUNT = "1000476183921"
TELEBIRR_ACCOUNT = "0916253200"
ACCOUNT_NAME = "Aschalew Desta"

# In-memory order store
orders: Dict[str, Dict[str, Any]] = {}

MODULE = "star"  # prefix for this module's callback_data

# Channel to ask users to join after completion
CHANNEL_LINK = "https://t.me/plugmarketshop1"
CHANNEL_USERNAME = "@plugmarketshop1"


# -------------------- FSM States --------------------
class StarTonStates(StatesGroup):
    # Stars
    star_amount = State()
    star_payment_method = State()
    star_wait_proof = State()
    star_wait_username = State()

    # TON
    ton_amount = State()
    ton_payment_method = State()
    ton_wait_proof = State()
    ton_wait_wallet = State()


# -------------------- Helpers --------------------
def ns(name: str) -> str:
    """Namespace a callback key for this module."""
    return f"{MODULE}_{name}"


def gen_order_id() -> str:
    return str(int(time.time() * 1000))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_amharic_text(text: Optional[str]) -> bool:
    if not text:
        return False
    return any(ch in text for ch in ["ዩ", "አማርኛ", "ግዢ", "ሽያጭ", "ብር", "STAR", "TON"])


async def ensure_lang(state: FSMContext) -> str:
    data = await state.get_data()
    return data.get("lang", "en")


def kb_back_to_services(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])


def contact_support_button(lang="en") -> InlineKeyboardMarkup:
    txt = "📞 Contact Support" if lang == "en" else "📞 ድጋፍን አግኙ"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=txt, url="https://t.me/plugmarketshop")]])


def is_allowed_star_amount(n: int) -> bool:
    # ALLOWED: any whole number >= 100 (user requested remove fixed choices; minimum is 100)
    return n >= 100


# ----------------------------
# Entry: menu callbacks and text entry
# ----------------------------
# FIX: Accept multiple variants of callback_data that may come from main.py or other menus.
# Also accept the menu as a text message in case the user tapped a non-inline menu or sent the label.
@router.callback_query(
    F.data.in_({
        "star_menu_en", "star_menu_am", "service_star_ton",
        "star_menu", "service_star", "stars_menu_en", "stars_menu_am"
    })
)
async def open_star_ton_menu(cb: CallbackQuery, state: FSMContext):
    """
    Entry handler for the Star & TON menu.
    Robust: accepts several callback_data variants, clears/sets FSM language, always answers the callback,
    and falls back to sending a new message if editing the original fails.
    """
    # Determine language
    if cb.data and cb.data.endswith("_am"):
        lang = "am"
    elif cb.data and cb.data.endswith("_en"):
        lang = "en"
    else:
        # try to preserve existing FSM language, fallback to en
        try:
            lang = (await state.get_data()).get("lang", "en")
        except Exception:
            lang = "en"

    # Reset and store lang
    try:
        await state.clear()
    except Exception:
        pass
    try:
        await state.update_data(lang=lang)
    except Exception:
        pass

    title = "⭐️ Stars & 💎 TON" if lang == "en" else "⭐️ STAR & 💎 TON"
    txt = (
        "Choose Stars or TON. For Stars enter whole numbers starting at 100. Minimum 100.\nFor TON enter decimals (min 0.5)."
        if lang == "en"
        else
        "STAR ወይም TON ይምረጡ። ስታር ከ100 ጀምሮ ያስገቡ (አንዱ ቁጥር). አነስተኛው 100 ነው። TON ለ 0.5+ ያስገቡ።"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Stars", callback_data=ns("star_buy"))],
        [InlineKeyboardButton(text="💎 TON", callback_data=ns("ton_buy"))],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])

    # Try to edit the original message, fallback to sending new message
    try:
        if cb.message:
            await cb.message.edit_text(f"{title}\n\n{txt}", reply_markup=kb)
        else:
            # No message to edit (rare), send fresh message
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=f"{title}\n\n{txt}", reply_markup=kb)
    except Exception:
        try:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=f"{title}\n\n{txt}", reply_markup=kb)
        except Exception:
            logger.exception("[star] open_star_ton_menu: unable to show menu to user %s", getattr(cb.from_user, "id", None))

    # Set waiting choice state (optional but helpful)
    try:
        await state.set_state(StarTonStates.star_amount)  # lightweight placeholder to capture ensure_lang in later calls
        # clear again to ensure no accidental state retention
        await state.clear()
    except Exception:
        pass

    # Always answer callback to stop Telegram spinner
    try:
        await cb.answer()
    except Exception:
        pass

    logger.debug("[star] open_star_ton_menu lang=%s user=%s", lang, getattr(cb.from_user, "id", None))


# Accept text commands that may open the menu (if user tapped a different UI)
@router.message(F.text.in_(["⭐ Buy Star & Ton", "⭐ Star እና TON ግዛ", "Buy Star & Ton", "Star & TON"]))
async def open_star_ton_menu_via_text(msg: Message, state: FSMContext):
    lang = "am" if is_amharic_text(msg.text) else "en"
    await state.clear()
    await state.update_data(lang=lang)

    title = "⭐️ Stars & 💎 TON" if lang == "en" else "⭐️ STAR & 💎 TON"
    txt = (
        "Choose Stars or TON. For Stars enter whole numbers starting at 100. Minimum 100.\nFor TON enter decimals (min 0.5)."
        if lang == "en"
        else
        "STAR ወይም TON ይምረጡ። ስታር ከ100 ጀምሮ ያስገቡ (አንዱ ቁጥር). አነስተኛው 100 ነው። TON ለ 0.5+ ያስገቡ።"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Stars", callback_data=ns("star_buy"))],
        [InlineKeyboardButton(text="💎 TON", callback_data=ns("ton_buy"))],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    try:
        await msg.reply(f"{title}\n\n{txt}", reply_markup=kb)
    except Exception:
        try:
            await msg.answer(f"{title}\n\n{txt}", reply_markup=kb)
        except Exception:
            logger.exception("[star] open_star_ton_menu_via_text failed for user %s", msg.from_user.id)


@router.message(F.text.in_(["⭐️ Stars", "⭐️ Star", "star", "stars", "Star"]))
async def stars_text_entry(msg: types.Message, state: FSMContext):
    lang = "am" if is_amharic_text(msg.text) else "en"
    await state.clear()
    await state.update_data(lang=lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Buy Stars" if lang == "en" else "🛒 Star ግዢ", callback_data=ns("star_buy"))],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    await msg.answer("⭐️ Telegram Stars\n\nEnter the stars amount (minimum 100)" if lang == "en"
                     else "⭐️ የቴሌግራም Star\n\nየስታር መጠን ያስገቡ (አነስተኛው 100)", reply_markup=kb)
    logger.debug("[star] stars_text_entry user=%s", msg.from_user.id)


@router.message(F.text.in_(["💎 TON", "💎 TON", "ton", "TON", "TON"]))
async def ton_text_entry(msg: types.Message, state: FSMContext):
    lang = "am" if is_amharic_text(msg.text) else "en"
    await state.clear()
    await state.update_data(lang=lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Buy TON" if lang == "en" else "🛒 TON ግዢ", callback_data=ns("ton_buy"))],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    await msg.answer(f"💎 TON Service — Minimum 0.5 TON." if lang == "en"
                     else f"💎 የTON አገልግሎት — አነስተኛው 0.5 ነው።", reply_markup=kb)
    logger.debug("[star] ton_text_entry user=%s", msg.from_user.id)


# ============================================================
#                     STARS BUY FLOW
# ============================================================
@router.callback_query(F.data == ns("star_buy"))
async def star_ask_amount(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    await state.set_state(StarTonStates.star_amount)
    text = (
        "🪙 Enter the number of Stars you want (minimum 100)."
        if lang == "en" else
        "🪙 Star መጠን ያስገቡ (አነስተኛው 100)."
    )
    try:
        if cb.message:
            await cb.message.edit_text(text, reply_markup=kb_back_to_services(lang))
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=text, reply_markup=kb_back_to_services(lang))
    except Exception:
        try:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=text, reply_markup=kb_back_to_services(lang))
        except Exception:
            logger.exception("[star] star_ask_amount: failed to prompt user %s", getattr(cb.from_user, "id", None))
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] star_ask_amount user=%s", getattr(cb.from_user, "id", None))


@router.message(StarTonStates.star_amount)
async def star_amount_received(msg: Message, state: FSMContext):
    lang = (await state.get_data()).get("lang", "en")
    txt = (msg.text or "").strip()
    if not txt.isdigit():
        await msg.answer("❗️ Enter a whole number like 100, 150, 200." if lang == "en"
                         else "❗️ እባክዎ እንደ 100, 150, 200 ያሉ አንድ ቁጥር ያስገቡ።")
        return
    stars = int(txt)
    if not is_allowed_star_amount(stars):
        await msg.answer("❗️ Minimum is 100." if lang == "en"
                         else "❗️ አነስተኛው 100 ነው።")
        return

    total_etb = round(stars * STAR_PRICE, 2)
    await state.update_data(star_amount=stars, star_total=total_etb)
    await state.set_state(StarTonStates.star_payment_method)

    lines = [
        f"🧾 Stars: {stars}",
        f"Total to pay: {total_etb:.2f} ETB",
        "",
        ("Choose payment method:" if lang == "en" else "የክፍያ ዘዴ ይምረጡ:")
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏦 CBE", callback_data=ns("star_cbe")),
            InlineKeyboardButton(text="📱 Telebirr", callback_data=ns("star_telebirr"))
        ],
        [
            InlineKeyboardButton(text="📋 Copy Amount", callback_data=f"{ns('copy_val')}:{total_etb:.2f}")
        ],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=ns("star_buy"))]
    ])
    try:
        await msg.answer("\n".join(lines), reply_markup=kb)
    except Exception:
        logger.exception("[star] star_amount_received: failed to respond to user %s", msg.from_user.id)
    logger.debug("[star] star_amount_received user=%s stars=%s", msg.from_user.id, stars)


@router.callback_query(F.data.in_([ns("star_cbe"), ns("star_telebirr")]))
async def star_payment_method_choice(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    stars = data.get("star_amount")
    total = data.get("star_total")
    # method detection: callback endswith 'cbe' or 'telebirr'
    method = "CBE" if cb.data.endswith("cbe") else "Telebirr"
    acc = CBE_ACCOUNT if method == "CBE" else TELEBIRR_ACCOUNT
    name = ACCOUNT_NAME

    # store chosen method
    await state.update_data(star_payment_method=method)

    text = (
        f"{'🏦' if method=='CBE' else '📱'} {method}\n"
        f"Account: {acc}\nName: {name}\n\n"
        f"Send {total:.2f} ETB, then press ✅ Done and upload payment proof."
        if lang == "en" else
        f"{'🏦' if method=='CBE' else '📱'} {method}\n"
        f"መለያ: {acc}\nስም: {name}\n\n"
        f"{total:.2f} ብር ይላኩ ከዛ ✅ ይጫኑ እና የክፍያ ማስረጃ ያስገቡ።"
    )
    await state.set_state(StarTonStates.star_wait_proof)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Done" if lang == "en" else "✅ ተጠናቋል", callback_data=ns("star_done"))],
        [InlineKeyboardButton(text="❌ Cancel" if lang == "en" else "❌ ሰርዝ", callback_data=ns("star_cancel"))],
        [
            InlineKeyboardButton(text="📋 Copy Amount", callback_data=f"{ns('copy_val')}:{total:.2f}"),
            InlineKeyboardButton(text="📋 Copy Account", callback_data=f"{ns('copy_account')}:{acc}")
        ]
    ])
    try:
        if cb.message:
            await cb.message.edit_text(text, reply_markup=kb)
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=text, reply_markup=kb)
    except Exception:
        logger.exception("[star] star_payment_method_choice failed to show payment details to user %s", getattr(cb.from_user, "id", None))

    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] star_payment_method_choice user=%s method=%s", getattr(cb.from_user, "id", None), method)


@router.callback_query(F.data == ns("star_done"))
async def star_done_prompt(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    try:
        if cb.message:
            await cb.message.edit_text(
                "📸 Please upload the payment proof (photo or document) now." if lang == "en"
                else "📸 እባክዎ የክፍያ ማስረጃ (ፎቶ/ፋይል) አሁን ያስገቡ።",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=ns("star_buy"))]
                ])
            )
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None,
                                      text="📸 Please upload the payment proof (photo or document) now.")
    except Exception:
        logger.exception("[star] star_done_prompt: failed to request proof for user %s", getattr(cb.from_user, "id", None))
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] star_done_prompt user=%s", getattr(cb.from_user, "id", None))


@router.callback_query(F.data == ns("star_cancel"))
async def star_cancel(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    try:
        await state.clear()
    except Exception:
        pass
    try:
        if cb.message:
            await cb.message.edit_text("Your order is cancelled." if lang == "en" else "ትእዛዙ ተሰርዟል።",
                                       reply_markup=kb_back_to_services(lang))
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None,
                                      text="Your order is cancelled." if lang == "en" else "ትእዛዙ ተሰርዟል።")
    except Exception:
        logger.exception("[star] star_cancel: failed to notify user %s", getattr(cb.from_user, "id", None))
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] star_cancel user=%s", getattr(cb.from_user, "id", None))


@router.message(StarTonStates.star_wait_proof, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def star_receive_proof(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    stars = data.get("star_amount")
    total = data.get("star_total")
    payment_method = data.get("star_payment_method", "Unknown")
    order_id = gen_order_id()
    date = now_str()

    # Try to get an image file_id to send as photo to admin with a caption
    file_id = None
    is_image = False
    try:
        if msg.photo:
            file_id = msg.photo[-1].file_id
            is_image = True
        elif msg.document:
            file_id = msg.document.file_id
            mime = getattr(msg.document, "mime_type", "") or ""
            is_image = bool(mime.startswith("image/"))
    except Exception:
        file_id = None
        is_image = False

    # Save order including payment method & lang so admin receives localized caption
    orders[order_id] = {
        "service": "stars",
        "type": "buy",
        "user_id": msg.from_user.id,
        "username": msg.from_user.username or None,
        "stars": stars,
        "total_etb": total,
        "lang": lang,
        "created_at": date,
        "payment_method": payment_method
    }

    # Record to tracker: order created
    try:
        if record_event:
            record_event("order_created", {
                "service": "star",
                "order_id": order_id,
                "user_id": msg.from_user.id,
                "username": msg.from_user.username or "",
                "amount": stars,
                "currency": "STAR",
                "total_etb": total,
                "payment_method": payment_method,
                "status": "waiting_admin",
                "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
        elif record_order:
            record_order("star", {
                "order_id": order_id,
                "user_id": msg.from_user.id,
                "username": msg.from_user.username or "",
                "amount": stars,
                "currency": "STAR",
                "total_etb": total,
                "payment_method": payment_method,
                "status": "waiting_admin",
                "created_at": datetime.utcnow()
            })
    except Exception:
        pass

    # Build admin caption with icons, localized
    if lang == "en":
        admin_caption = (
            f"⭐️ NEW STAR ORDER\n\n"
            f"👤 User: @{msg.from_user.username or 'N/A'} (ID: {msg.from_user.id})\n"
            f"🧮 Stars: {stars}\n"
            f"💳 Total: {float(total):.2f} ETB\n"
            f"💸 Payment Method: {payment_method}\n"
            f"📅 Date: {date}\n"
            f"🆔 Order ID: {order_id}"
        )
    else:
        admin_caption = (
            f"⭐️ አዲስ STAR ትእዛዝ\n\n"
            f"👤 ተጠቃሚ: @{msg.from_user.username or 'N/A'} (መታወቂያ: {msg.from_user.id})\n"
            f"🧮 ስታሮች: {stars}\n"
            f"💳 አጠቃላይ: {float(total):.2f} ብር\n"
            f"💸 የክፍያ ዘዴ: {payment_method}\n"
            f"📅 ቀን: {date}\n"
            f"🆔 የትእዛዝ መለያ: {order_id}"
        )

    # Admin keyboard: Paid / Not Paid + copy buttons (order id, amount)
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Paid", callback_data=f"{ns('admin_star_paid')}_{msg.from_user.id}_{order_id}"),
         InlineKeyboardButton(text="❌ Not Paid", callback_data=f"{ns('admin_star_notpaid')}_{msg.from_user.id}_{order_id}")],
        [InlineKeyboardButton(text="📋 Copy Order ID", callback_data=f"{ns('copy_order')}:{order_id}"),
         InlineKeyboardButton(text="📋 Copy Amount", callback_data=f"{ns('copy_val')}:{stars}")]
    ])

    # Send image/document to admin with caption (try to send as photo if image)
    try:
        if file_id and is_image:
            await msg.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=admin_caption, reply_markup=admin_kb)
        elif file_id:
            await msg.bot.send_document(chat_id=ADMIN_ID, document=file_id, caption=admin_caption, reply_markup=admin_kb)
        else:
            await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
            await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_caption, reply_markup=admin_kb)
    except Exception:
        logger.exception("sending star proof to admin failed for order %s user %s", order_id, msg.from_user.id)
        try:
            await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
            await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_caption, reply_markup=admin_kb)
        except Exception:
            pass

    # Confirm to user
    try:
        await msg.answer("⏳ Waiting for admin confirmation..." if lang == "en"
                         else "⏳ ከአስተዳዳሪ ማረጋገጫ በመጠበቅ ላይ...")
    except Exception:
        pass
    await state.clear()
    logger.debug("[star] star_receive_proof order=%s user=%s", order_id, msg.from_user.id)


# Admin -> Star Not Paid
@router.callback_query(F.data.startswith(ns("admin_star_notpaid_")))
async def admin_star_not_paid(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 3:
        await cb.answer("Invalid callback.", show_alert=True)
        return
    try:
        user_id = int(parts[-2])
    except Exception:
        user_id = None
    order_id = parts[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    lang = order.get("lang", "en")

    # record not-paid event in tracker
    try:
        if record_event:
            record_event("admin_marked_not_paid", {"service": "star", "order_id": order_id, "user_id": user_id, "status": "not_paid"})
    except Exception:
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=ns("star_buy"))],
        [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
    ])
    try:
        if user_id:
            await cb.bot.send_message(
                chat_id=user_id,
                text=("❌ Payment not received. Please pay again and reupload proof, or contact support."
                      if lang == "en"
                      else
                      "❌ ክፍያ አልተቀበለም። እባክዎ ዳግመው ይክፈሉ እና ማስረጃ ያስገቡ ወይም ወደ ድጋፍ ይግቡ።"),
                reply_markup=kb
            )
    except Exception:
        logger.exception("notify star notpaid failed for order %s", order_id)
    await cb.answer("User notified." if user_id else "Done", show_alert=False)
    logger.debug("[star] admin_star_not_paid order=%s", order_id)


# Admin -> Star Paid => send buyer button to set their FSM for username
@router.callback_query(F.data.startswith(ns("admin_star_paid_")))
async def admin_star_paid(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 3:
        await cb.answer("Invalid callback.", show_alert=True)
        return
    try:
        user_id = int(parts[-2])
    except Exception:
        user_id = None
    order_id = parts[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    lang = order.get("lang", "en")
    payment_method = order.get("payment_method", "Unknown")

    # record admin confirmed payment to tracker
    try:
        if record_event:
            record_event("admin_confirmed_payment", {
                "service": "star",
                "order_id": order_id,
                "user_id": user_id,
                "payment_method": payment_method,
                "total_etb": order.get("total_etb") or 0.0,
                "status": "paid",
                "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
    except Exception:
        pass

    try:
        if user_id:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✉️ Send Username (without @)" if lang == "en" else "✉️ ዩዘርኔም ይላኩ (ከ@ ውጭ)", callback_data=f"{ns('user_send_star_username')}:{order_id}")],
                [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
            ])

            # Include payment method info for the user in the message
            if lang == "en":
                notify_text = (
                    f"✅ Admin marked your payment as received.\n\nPayment method: {payment_method}\n\n"
                    "Please press the button below and send your Telegram username (with @) so we can deliver Stars."
                )
            else:
                notify_text = (
                    f"✅ ክፍያዎ ተረጋግጧል።\n\nየክፍያ ዘዴ: {payment_method}\n\n"
                    "እባክዎ ታች ያለውን Button ይጫኑ እና የቴሌግራም ዩዘርኔምዎን ያስገቡ (ከ@ ጋር)."
                )

            await cb.bot.send_message(
                chat_id=user_id,
                text=notify_text,
                reply_markup=kb
            )
    except Exception:
        logger.exception("notify user (stars username request) failed for order %s", order_id)

    try:
        await cb.answer("Buyer notified." if user_id else "Done", show_alert=False)
    except Exception:
        pass
    logger.debug("[star] admin_star_paid notify buyer=%s order=%s", user_id, order_id)


# When buyer clicks the namespaced button, set their FSM to wait for username
@router.callback_query(F.data.startswith(ns("user_send_star_username") + ":"))
async def user_send_star_username_button(cb: CallbackQuery, state: FSMContext):
    # callback format: star_user_send_star_username:<order_id>
    try:
        order_id = cb.data.split(":", 1)[1]
    except Exception:
        await cb.answer("Invalid data.", show_alert=True)
        return

    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found or expired.", show_alert=True)
        return

    await state.update_data(star_pending_order=order_id)
    await state.set_state(StarTonStates.star_wait_username)
    lang = order.get("lang", "en")
    try:
        await cb.message.answer("Please send your Telegram username now (with @)." if lang == "en"
                                else "እባክዎ የቴሌግራም ዩዘርኔምዎን አሁን ይላኩ (ከ@ ጋር).")
    except Exception:
        try:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text="Please send your Telegram username now (with @).")
        except Exception:
            pass
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] user_send_star_username_button user=%s order=%s", getattr(cb.from_user, "id", None), order_id)


@router.message(StarTonStates.star_wait_username, F.text)
async def user_send_star_username(msg: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("star_pending_order")
    order = orders.get(order_id)
    if not order:
        await msg.answer("Order not found or expired.")
        await state.clear()
        return

    username = msg.text.strip().lstrip("@")
    order["username_to_credit"] = username
    order["username_sent_at"] = now_str()

    lang = order.get("lang", "en")
    # Build localized admin message and keyboard with copy buttons
    if lang == "en":
        admin_text = (
            f"⭐️ STAR — USERNAME RECEIVED\n\n"
            f"Order ID: {order_id}\nDate: {order['username_sent_at']}\n"
            f"Buyer: @{msg.from_user.username or msg.from_user.id}\n"
            f"Stars: {order.get('stars')}\n"
            f"Payment Method: {order.get('payment_method','Unknown')}\n"
            f"Send to username: @{username}"
        )
    else:
        admin_text = (
            f"⭐️ STAR — ዩዘርኔም ተቀብሏል\n\n"
            f"የትእዛዝ መለያ: {order_id}\nቀን: {order['username_sent_at']}\n"
            f"ገዢ: @{msg.from_user.username or msg.from_user.id}\n"
            f"ስታሮች: {order.get('stars')}\n"
            f"የክፍያ ዘዴ: {order.get('payment_method','Unknown')}\n"
            f"ይላኩ: @{username}"
        )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Payment Completed", callback_data=f"{ns('payment_completed')}_{order_id}")],
        [InlineKeyboardButton(text="📋 Copy Username", callback_data=f"{ns('copy_username')}:{username}"),
         InlineKeyboardButton(text="📋 Copy Amount", callback_data=f"{ns('copy_val')}:{order.get('stars')}")]
    ])
    try:
        await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=admin_kb)
    except Exception:
        logger.exception("send username to admin failed for order %s", order_id)

    try:
        await msg.answer("✅ Username sent to admin. Stars will be delivered shortly." if order.get("lang","en") == "en"
                         else "✅ ዩዘርኔም ለአስተዳዳሪ ተልኳል። Stars በቅርቡ ይላካሉ።")
    except Exception:
        pass
    await state.clear()
    logger.debug("[star] user_send_star_username saved order=%s username=%s", order_id, username)


@router.callback_query(F.data.startswith(ns("payment_completed_")))
async def star_payment_completed(cb: CallbackQuery):
    # callback format: star_payment_completed_<order_id>
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    user_id = order.get("user_id")
    lang = order.get("lang", "en")
    stars = order.get("stars")
    username_to_credit = order.get("username_to_credit", "")

    # Record completion to tracker BEFORE removing local order
    try:
        if record_event:
            record_event("order_completed", {
                "service": "star",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username") or "",
                "amount": stars,
                "currency": "STAR",
                "total_etb": float(order.get("total_etb") or 0.0),
                "payment_method": order.get("payment_method", ""),
                "status": "completed",
                "completed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
        elif record_order:
            record_order("star", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username") or "",
                "amount": stars,
                "currency": "STAR",
                "total_etb": float(order.get("total_etb") or 0.0),
                "payment_method": order.get("payment_method", ""),
                "status": "completed",
                "completed_at": datetime.utcnow()
            })
    except Exception:
        pass

    # Localized final text for user (also include join channel button)
    if lang == "en":
        final_text = (
            f"🎉 Congratulations! {stars} Stars were successfully sent to @{username_to_credit}.\n\n"
            "If you need proof or have questions, click Contact Support. Thanks for trading with us!"
        )
    else:
        final_text = (
            f"🎉 እንኳን ደስ አለዎት! {stars} ስታሮች ለ @{username_to_credit} ተልከዋል።\n\n"
            "ማረጋገጫ ወይም ጥያቄ ካለ ወደ ድጋፍ ይግቡ። እናመሰግናለን!"
        )

    final_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Contact Support" if lang == "en" else "📞 ድጋፍን አግኙ", url="https://t.me/plugmarketshop")],
        [InlineKeyboardButton(text="👉 Join Channel", url=CHANNEL_LINK)]
    ])

    try:
        if user_id:
            await cb.bot.send_message(chat_id=user_id, text=final_text, reply_markup=final_kb)
    except Exception:
        logger.exception("send stars final failed for order %s", order_id)

    # Small admin notification about completion (localized)
    try:
        admin_note = (f"✅ STAR order {order_id} completed." if lang == "en"
                      else f"✅ STAR ትእዛዝ {order_id} ተጠናቋል።")
        await cb.bot.send_message(chat_id=ADMIN_ID, text=admin_note)
    except Exception:
        pass

    # Remove order so further action buttons show "Order not found"
    orders.pop(order_id, None)
    try:
        await cb.answer("User notified (Stars completed).", show_alert=False)
    except Exception:
        pass
    logger.debug("[star] star_payment_completed order=%s", order_id)


# ============================================================
#                     TON BUY FLOW
# ============================================================
@router.callback_query(F.data == ns("ton_buy"))
async def ton_ask_amount(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    await state.set_state(StarTonStates.ton_amount)
    text = (
        "💠 Enter TON amount you want to buy (minimum 0.5). Example: 0.5, 1.25"
        if lang == "en" else
        "💠 የTON መጠን ያስገቡ (አነስተኛው 0.5)."
    )
    try:
        if cb.message:
            await cb.message.edit_text(text, reply_markup=kb_back_to_services(lang))
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=text, reply_markup=kb_back_to_services(lang))
    except Exception:
        logger.exception("[star] ton_ask_amount: failed to prompt user %s", getattr(cb.from_user, "id", None))
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] ton_ask_amount user=%s", getattr(cb.from_user, "id", None))


@router.message(StarTonStates.ton_amount)
async def ton_amount_received(msg: Message, state: FSMContext):
    lang = (await state.get_data()).get("lang", "en")
    txt = (msg.text or "").strip()
    try:
        ton_amount = float(txt.replace(",", ""))
    except Exception:
        await msg.answer("❗️ Please enter a valid number (e.g., 0.5)." if lang == "en"
                         else "❗️ እባክዎ ትክክለኛ ቁጥር ያስገቡ (ለምሳሌ 0.5)።")
        return
    if ton_amount < 0.5:
        await msg.answer("❗️ Minimum is 0.5 TON." if lang == "en" else "❗️ አነስተኛው 0.5 TON ነው።")
        return

    total_etb = round(ton_amount * TON_PRICE, 2)
    await state.update_data(ton_amount=ton_amount, ton_total=total_etb)
    await state.set_state(StarTonStates.ton_payment_method)

    lines = [
        f"🧾 TON: {ton_amount}",
        f"Total to pay: {total_etb:.2f} ETB",
        "",
        ("Choose payment method:" if lang == "en" else "የክፍያ ዘዴ ይምረጡ:")
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 CBE", callback_data=ns("ton_cbe")),
         InlineKeyboardButton(text="📱 Telebirr", callback_data=ns("ton_telebirr"))],
        [InlineKeyboardButton(text="📋 Copy Amount", callback_data=f"{ns('copy_val')}:{total_etb:.2f}")],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=ns("ton_buy"))]
    ])
    try:
        await msg.answer("\n".join(lines), reply_markup=kb)
    except Exception:
        logger.exception("[star] ton_amount_received: failed to respond to user %s", msg.from_user.id)
    logger.debug("[star] ton_amount_received user=%s ton=%s", msg.from_user.id, ton_amount)


@router.callback_query(F.data.in_([ns("ton_cbe"), ns("ton_telebirr")]))
async def ton_payment_method_choice(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    ton_amount = data.get("ton_amount")
    total = data.get("ton_total")
    method = "CBE" if cb.data.endswith("cbe") else "Telebirr"
    acc = CBE_ACCOUNT if method == "CBE" else TELEBIRR_ACCOUNT
    name = ACCOUNT_NAME

    # store chosen method
    await state.update_data(ton_payment_method=method)

    text = (
        f"{'🏦' if method=='CBE' else '📱'} {method}\n"
        f"Account: {acc}\nName: {name}\n\n"
        f"Send {total:.2f} ETB, then press ✅ Done and upload payment proof."
        if lang == "en" else
        f"{'🏦' if method=='CBE' else '📱'} {method}\n"
        f"መለያ: {acc}\nስም: {name}\n\n"
        f"{total:.2f} ብር ይላኩ ከዛ ✅ ይጫኑ እና የክፍያ ማስረጃ ያስገቡ።"
    )
    await state.set_state(StarTonStates.ton_wait_proof)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Done" if lang == "en" else "✅ ተጠናቋል", callback_data=ns("ton_done"))],
        [InlineKeyboardButton(text="❌ Cancel" if lang == "en" else "❌ ሰርዝ", callback_data=ns("ton_cancel"))],
        [
            InlineKeyboardButton(text="📋 Copy Amount", callback_data=f"{ns('copy_val')}:{total:.2f}"),
            InlineKeyboardButton(text="📋 Copy Account", callback_data=f"{ns('copy_account')}:{acc}")
        ]
    ])
    try:
        if cb.message:
            await cb.message.edit_text(text, reply_markup=kb)
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=text, reply_markup=kb)
    except Exception:
        logger.exception("[star] ton_payment_method_choice failed to show payment details to user %s", getattr(cb.from_user, "id", None))
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] ton_payment_method_choice user=%s method=%s", getattr(cb.from_user, "id", None), method)


@router.callback_query(F.data == ns("ton_done"))
async def ton_done_prompt(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    try:
        if cb.message:
            await cb.message.edit_text(
                "📸 Please upload the payment proof (photo or document) now." if lang == "en"
                else "📸 እባክዎ የክፍያ ማስረጃ (ፎቶ/ፋይል) አሁን ያስገቡ።",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=ns("ton_buy"))]
                ])
            )
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None,
                                      text="📸 Please upload the payment proof (photo or document) now.")
    except Exception:
        logger.exception("[star] ton_done_prompt failed for user %s", getattr(cb.from_user, "id", None))
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] ton_done_prompt user=%s", getattr(cb.from_user, "id", None))


@router.callback_query(F.data == ns("ton_cancel"))
async def ton_cancel(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    try:
        await state.clear()
    except Exception:
        pass
    try:
        if cb.message:
            await cb.message.edit_text("Your order is cancelled." if lang == "en" else "ትእዛዙ ተሰርዟል።",
                                       reply_markup=kb_back_to_services(lang))
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None,
                                      text="Your order is cancelled." if lang == "en" else "ትእዛዙ ተሰርዟል።")
    except Exception:
        logger.exception("[star] ton_cancel failed for user %s", getattr(cb.from_user, "id", None))
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] ton_cancel user=%s", getattr(cb.from_user, "id", None))


@router.message(StarTonStates.ton_wait_proof, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def ton_receive_proof(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    ton_amount = data.get("ton_amount")
    total = data.get("ton_total")
    payment_method = data.get("ton_payment_method", "Unknown")
    order_id = gen_order_id()
    date = now_str()

    # Try to get an image file_id to send as photo to admin with a caption
    file_id = None
    is_image = False
    try:
        if msg.photo:
            file_id = msg.photo[-1].file_id
            is_image = True
        elif msg.document:
            file_id = msg.document.file_id
            mime = getattr(msg.document, "mime_type", "") or ""
            is_image = bool(mime.startswith("image/"))
    except Exception:
        file_id = None
        is_image = False

    # Save order including payment method & lang so admin receives localized caption
    orders[order_id] = {
        "service": "ton",
        "type": "buy",
        "user_id": msg.from_user.id,
        "username": msg.from_user.username or None,
        "ton_amount": ton_amount,
        "total_etb": total,
        "lang": lang,
        "created_at": date,
        "payment_method": payment_method
    }

    # Record to tracker: order created
    try:
        if record_event:
            record_event("order_created", {
                "service": "ton",
                "order_id": order_id,
                "user_id": msg.from_user.id,
                "username": msg.from_user.username or "",
                "amount": ton_amount,
                "currency": "TON",
                "total_etb": total,
                "payment_method": payment_method,
                "status": "waiting_admin",
                "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
        elif record_order:
            record_order("ton", {
                "order_id": order_id,
                "user_id": msg.from_user.id,
                "username": msg.from_user.username or "",
                "amount": ton_amount,
                "currency": "TON",
                "total_etb": total,
                "payment_method": payment_method,
                "status": "waiting_admin",
                "created_at": datetime.utcnow()
            })
    except Exception:
        pass

    # Build admin caption localized
    if lang == "en":
        admin_caption = (
            f"💎 NEW TON ORDER\n\n"
            f"👤 User: @{msg.from_user.username or 'N/A'} (ID: {msg.from_user.id})\n"
            f"🔢 TON amount: {ton_amount}\n"
            f"💳 Total: {float(total):.2f} ETB\n"
            f"💸 Payment Method: {payment_method}\n"
            f"📅 Date: {date}\n"
            f"🆔 Order ID: {order_id}"
        )
    else:
        admin_caption = (
            f"💎 አዲስ TON ትእዛዝ\n\n"
            f"👤 ተጠቃሚ: @{msg.from_user.username or 'N/A'} (መታወቂያ: {msg.from_user.id})\n"
            f"🔢 TON መጠን: {ton_amount}\n"
            f"💳 አጠቃላይ: {float(total):.2f} ብር\n"
            f"💸 የክፍያ ዘዴ: {payment_method}\n"
            f"📅 ቀን: {date}\n"
            f"🆔 የትእዛዝ መለያ: {order_id}"
        )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Paid", callback_data=f"{ns('admin_ton_paid')}_{msg.from_user.id}_{order_id}"),
         InlineKeyboardButton(text="❌ Not Paid", callback_data=f"{ns('admin_ton_notpaid')}_{msg.from_user.id}_{order_id}")],
        [InlineKeyboardButton(text="📋 Copy Order ID", callback_data=f"{ns('copy_order')}:{order_id}"),
         InlineKeyboardButton(text="📋 Copy Amount", callback_data=f"{ns('copy_val')}:{ton_amount}")]
    ])

    try:
        if file_id and is_image:
            await msg.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=admin_caption, reply_markup=admin_kb)
        elif file_id:
            await msg.bot.send_document(chat_id=ADMIN_ID, document=file_id, caption=admin_caption, reply_markup=admin_kb)
        else:
            await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
            await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_caption, reply_markup=admin_kb)
    except Exception:
        logger.exception("sending ton proof to admin failed for order %s user %s", order_id, msg.from_user.id)
        try:
            await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
            await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_caption, reply_markup=admin_kb)
        except Exception:
            pass

    await msg.answer("⏳ Waiting for admin confirmation..." if lang == "en"
                     else "⏳ ከአስተዳዳሪ ማረጋገጫ በመጠበቅ ላይ...")
    await state.clear()
    logger.debug("[star] ton_receive_proof order=%s user=%s", order_id, msg.from_user.id)


@router.callback_query(F.data.startswith(ns("admin_ton_notpaid_")))
async def admin_ton_not_paid(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 3:
        await cb.answer("Invalid callback.", show_alert=True)
        return
    try:
        user_id = int(parts[-2])
    except Exception:
        user_id = None
    order_id = parts[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    try:
        if record_event:
            record_event("admin_marked_not_paid", {"service": "ton", "order_id": order_id, "user_id": user_id, "status": "not_paid"})
    except Exception:
        pass

    lang = order.get("lang", "en")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=ns("ton_buy"))],
        [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
    ])
    try:
        if user_id:
            await cb.bot.send_message(chat_id=user_id,
                                      text=("❌ Payment not received. Please pay again and reupload proof, or contact support."
                                            if lang == "en"
                                            else "❌ ክፍያ አልተቀበለም። እባክዎ ማስረጃዎን ደግመው ያስገቡ ወይም ወደ ድጋፍ ይግቡ።"),
                                      reply_markup=kb)
    except Exception:
        logger.exception("notify ton notpaid failed for order %s", order_id)
    await cb.answer("User notified." if user_id else "Done", show_alert=False)
    logger.debug("[star] admin_ton_not_paid order=%s", order_id)


@router.callback_query(F.data.startswith(ns("admin_ton_paid_")))
async def admin_ton_paid(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 3:
        await cb.answer("Invalid callback.", show_alert=True)
        return
    try:
        user_id = int(parts[-2])
    except Exception:
        user_id = None
    order_id = parts[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    lang = order.get("lang", "en")
    payment_method = order.get("payment_method", "Unknown")

    try:
        if record_event:
            record_event("admin_confirmed_payment", {
                "service": "ton",
                "order_id": order_id,
                "user_id": user_id,
                "payment_method": payment_method,
                "total_etb": float(order.get("total_etb") or 0.0),
                "status": "paid",
                "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
    except Exception:
        pass

    try:
        if user_id:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✉️ Send Wallet (TON)" if lang == "en" else "✉️ ዋሌት ይላኩ (TON)", callback_data=f"{ns('user_send_ton_wallet')}:{order_id}")],
                [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
            ])
            if lang == "en":
                notify_text = (
                    f"✅ Admin marked your payment as received.\n\nPayment method: {payment_method}\n\n"
                    "Please press the button below and send your TON wallet address so we can deliver TON."
                )
            else:
                notify_text = (
                    f"✅ ክፍያዎ ተረጋግጧል።\n\nየክፍያ ዘዴ: {payment_method}\n\n"
                    "እባክዎ ታች ያለውን አዝራር ይጫኑ እና የTON ዋሌት አድራሻዎን ያስገቡ።"
                )
            await cb.bot.send_message(chat_id=user_id, text=notify_text, reply_markup=kb)
    except Exception:
        logger.exception("notify user (TON wallet request) failed for order %s", order_id)

    try:
        await cb.answer("Buyer notified." if user_id else "Done", show_alert=False)
    except Exception:
        pass
    logger.debug("[star] admin_ton_paid notify buyer=%s order=%s", user_id, order_id)


@router.callback_query(F.data.startswith(ns("user_send_ton_wallet") + ":"))
async def user_send_ton_wallet_button(cb: CallbackQuery, state: FSMContext):
    try:
        order_id = cb.data.split(":", 1)[1]
    except Exception:
        await cb.answer("Invalid data.", show_alert=True)
        return

    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found or expired.", show_alert=True)
        return

    await state.update_data(ton_pending_order=order_id)
    await state.set_state(StarTonStates.ton_wait_wallet)
    lang = order.get("lang", "en")
    try:
        await cb.message.answer("Please send your TON wallet address now. (must start with UQ)" if lang == "en"
                                else "እባክዎ የTON ዋሌት አድራሻዎን አሁን ይላኩ። (UQ በጀርባ ጀምር)")
    except Exception:
        try:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text="Please send your TON wallet address now.")
        except Exception:
            pass
    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] user_send_ton_wallet_button user=%s order=%s", getattr(cb.from_user, "id", None), order_id)


@router.message(StarTonStates.ton_wait_wallet, F.text)
async def user_send_ton_wallet(msg: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("ton_pending_order")
    order = orders.get(order_id)
    if not order:
        await msg.answer("Order not found or expired.")
        await state.clear()
        return

    wallet = msg.text.strip()
    if not wallet.startswith("UQ"):
        lang = order.get("lang", "en")
        await msg.answer(
            "❗️ Invalid TON address. TON wallet addresses must start with 'UQ' (capital UQ). Please send the correct address."
            if lang == "en" else
            "❗️ የTON አድራሻ ትክክል አይደለም። ዋሌት አድራሻዎ በ 'UQ' (ከፊሉ ከፍ) መጨረሻ መጀመር አለበት። እባክዎ ደግመው ይላኩ።"
        )
        await state.update_data(ton_pending_order=order_id)
        return

    order["wallet"] = wallet
    order["wallet_sent_at"] = now_str()

    lang = order.get("lang", "en")
    if lang == "en":
        admin_text = (
            f"💎 TON ORDER — WALLET RECEIVED\n\n"
            f"Order ID: {order_id}\nDate: {order['wallet_sent_at']}\n"
            f"Buyer: @{msg.from_user.username or msg.from_user.id}\n"
            f"TON amount: {order.get('ton_amount')}\n"
            f"Total ETB: {float(order.get('total_etb') or 0.0):.2f}\n"
            f"Send to wallet: {wallet}"
        )
    else:
        admin_text = (
            f"💎 TON ትእዛዝ — ዋሌት ተቀብሏል\n\n"
            f"የትእዛዝ መለያ: {order_id}\nቀን: {order['wallet_sent_at']}\n"
            f"ገዢ: @{msg.from_user.username or msg.from_user.id}\n"
            f"TON መጠን: {order.get('ton_amount')}\n"
            f"አጠቃላይ (ETB): {float(order.get('total_etb') or 0.0):.2f}\n"
            f"ወደ ዋሌት: {wallet}"
        )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Payment Completed", callback_data=f"{ns('ton_payment_completed')}_{order_id}")],
        [InlineKeyboardButton(text="📋 Copy Wallet", callback_data=f"{ns('copy_wallet')}:{wallet}"),
         InlineKeyboardButton(text="📋 Copy Order ID", callback_data=f"{ns('copy_order')}:{order_id}")]
    ])
    try:
        await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=admin_kb)
    except Exception:
        logger.exception("send wallet to admin failed for order %s", order_id)

    try:
        await msg.answer("✅ Wallet sent to admin. TON will be delivered shortly." if order.get("lang","en") == "en"
                         else "✅ ዋሌት ተልኳል። TON በቅርቡ ይላካል።")
    except Exception:
        pass
    await state.clear()
    logger.debug("[star] user_send_ton_wallet saved order=%s wallet=%s", order_id, wallet)


@router.callback_query(F.data.startswith(ns("ton_payment_completed_")))
async def ton_payment_completed(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    user_id = order.get("user_id")
    lang = order.get("lang", "en")
    ton_amount = order.get("ton_amount")
    wallet = order.get("wallet", "")

    # Record completion to tracker BEFORE removing local order
    try:
        if record_event:
            record_event("order_completed", {
                "service": "ton",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username") or "",
                "amount": ton_amount,
                "currency": "TON",
                "total_etb": float(order.get("total_etb") or 0.0),
                "payment_method": order.get("payment_method", ""),
                "status": "completed",
                "completed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
        elif record_order:
            record_order("ton", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username") or "",
                "amount": ton_amount,
                "currency": "TON",
                "total_etb": float(order.get("total_etb") or 0.0),
                "payment_method": order.get("payment_method", ""),
                "status": "completed",
                "completed_at": datetime.utcnow()
            })
    except Exception:
        pass

    if lang == "en":
        final_text = (
            f"🎉 Congratulations! {ton_amount} TON were successfully sent to your wallet:\n`{wallet}`\n\n"
            "If you need proof or have questions, click Contact Support. Thanks for trading with us!"
        )
    else:
        final_text = (
            f"🎉 እንኳን ደስ አለዎት! {ton_amount} TON ወደ ዋሌትዎ ተልከዋል:\n`{wallet}`\n\n"
            "ማረጋገጫ ወይም ጥያቄ ካለ ወደ ድጋፍ ይግቡ። እናመሰግናለን!"
        )

    final_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Contact Support" if lang == "en" else "📞 ድጋፍን አግኙ", url="https://t.me/plugmarketshop")],
        [InlineKeyboardButton(text="👉 Join Channel", url=CHANNEL_LINK)]
    ])

    try:
        if user_id:
            await cb.bot.send_message(chat_id=user_id, text=final_text, reply_markup=final_kb)
    except Exception:
        logger.exception("send TON final failed for order %s", order_id)

    try:
        admin_note = (f"✅ TON order {order_id} completed." if lang == "en"
                      else f"✅ TON ትእዛዝ {order_id} ተጠናቋል።")
        await cb.bot.send_message(chat_id=ADMIN_ID, text=admin_note)
    except Exception:
        pass

    orders.pop(order_id, None)
    try:
        await cb.answer("User notified (TON completed).", show_alert=False)
    except Exception:
        pass
    logger.debug("[star] ton_payment_completed order=%s", order_id)


# ============================================================
#                 COPY HANDLER (namespaced only)
# ============================================================
@router.callback_query(F.data.startswith(ns("copy_")))
async def star_copy_cb(cb: CallbackQuery):
    """
    Handles namespaced copy callbacks like:
      - star_copy_account:<acc>
      - star_copy_order:<order_id>
      - star_copy_username:<username>
      - star_copy_wallet:<wallet>
      - star_copy_val:<value>
    Shows the raw value so user/admin can long-press to copy.
    """
    payload = cb.data.split(":", 1)
    if len(payload) == 2:
        raw = payload[1]
    else:
        # fallback: take last '_' segment
        raw = cb.data.rsplit("_", 1)[-1]

    try:
        # send as code block so user can long-press to copy
        if cb.message:
            await cb.message.answer(f"`{raw}`", parse_mode="Markdown")
        else:
            await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=f"`{raw}`", parse_mode="Markdown")
    except Exception:
        try:
            await cb.message.answer(raw)
        except Exception:
            try:
                await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=raw)
            except Exception:
                pass
    try:
        await cb.answer("Value shown (long-press to copy).")
    except Exception:
        pass
    logger.debug("[star] copy_cb payload=%s user=%s", raw, getattr(cb.from_user, "id", None))


# Unknown/leftover star callbacks -> give helpful message
@router.callback_query(F.data.startswith(MODULE + "_"))
async def star_unknown_cb(cb: CallbackQuery):
    """
    This will only fire for callbacks that start with this module's prefix.
    If the order id encoded in the callback no longer exists, tell the user 'Order not found'.
    Otherwise, just acknowledge silently.
    """
    tail = cb.data.rsplit("_", 1)[-1]
    if tail and tail.isdigit() and tail not in orders:
        try:
            await cb.answer("Order not found.", show_alert=True)
        except Exception:
            pass
        logger.debug("[star] star_unknown_cb order_not_found callback=%s user=%s", cb.data, getattr(cb.from_user, "id", None))
        return

    try:
        await cb.answer()
    except Exception:
        pass
    logger.debug("[star] star_unknown_cb callback=%s user=%s", cb.data, getattr(cb.from_user, "id", None))
