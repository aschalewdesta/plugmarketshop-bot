# alibaba_order.py
import time
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any
import re

from aiogram import Router, F, types
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, ContentType
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# ---------- tracker integration (safe) ----------
try:
    from tracker import record_event, record_order, find_order_by_id
except Exception:
    record_event = None
    record_order = None
    find_order_by_id = None

admin_reply_pending: Dict[int, Any] = {}

router = Router()
logger = logging.getLogger(__name__)

# -------------------- Config / Constants --------------------
ADMIN_ID = 6968325481

# Bank placeholders (easy to replace)
CBE_ACCOUNT = "1000476183921"
TELEBIRR_ACCOUNT = "0916253200"
ACCOUNT_NAME = "Aschalew Desta"

# In-memory order store: order_id -> dict
orders: dict[str, dict] = {}
archived_orders: dict[str, dict] = {}  # store completed/archived orders

# Tutorial video URL (replace with your real video)
TUTORIAL_YOUTUBE_URL = "https://youtu.be/VIDEO_ID"

# Telegram channel to ask users to join after completion
CHANNEL_USERNAME = "@plugmarketshop1"
CHANNEL_URL = "https://t.me/plugmarketshop1"

# -------------------- FSM States --------------------
class AlibabaStates(StatesGroup):
    choose = State()
    wait_name = State()
    wait_link = State()
    wait_photo = State()

    wait_address = State()
    wait_quantity = State()
    wait_payment_method = State()
    wait_payment_proof = State()

# -------------------- Helpers --------------------
def gen_order_id() -> str:
    return str(int(time.time() * 1000))

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def is_amharic_text(text: Optional[str]) -> bool:
    if not text:
        return False
    return any(ch in text for ch in ["የ", "አማርኛ", "ዕቃ", "ግዢ", "ብር", "ይህ", "ይህን"])

async def ensure_lang(state: FSMContext) -> str:
    data = await state.get_data()
    return data.get("lang", "en")

def kb_back(lang: str, target: str = "services") -> InlineKeyboardMarkup:
    cb = f"services_{lang}" if target == "services" else f"lang_{lang}"
    txt = "🔙 Back" if lang == "en" else "🔙 ተመለስ"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=txt, callback_data=cb)]])

def contact_support_button(lang="en") -> InlineKeyboardMarkup:
    txt = "📞 Contact Support" if lang == "en" else "📞 ድጋፍን አግኙ"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=txt, url="https://t.me/plugmarketshop")]])

def join_channel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Join", url=CHANNEL_URL)]])

def safe_get_order(order_id: str) -> Optional[dict]:
    """Return active order dict if exists, otherwise None (archived considered not found)."""
    return orders.get(order_id)

def format_admin_lang_text(lang: str, en_text: str, am_text: str) -> str:
    return en_text if lang == "en" else am_text

def format_quote_for_user(raw: str) -> str:
    """If admin typed only number (e.g. '12345' or '12345.50'), append ' ETB' for clarity.
    If string already contains ETB or 'ብር' or non-numeric words, return as-is.
    """
    s = raw.strip()
    # if contains etb or birr words already, return unchanged
    if re.search(r"\b(etb|ብር)\b", s, flags=re.IGNORECASE):
        return s
    # try to detect if it's basically a number (maybe 'Total: 12345' - extract number)
    m = re.search(r"(-?\d{1,3}(?:[,.\s]\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)", s.replace(",", ""))
    if m and m.group().strip() == s:
        # pure numeric
        return f"{s} ETB"
    # else, if entire string contains a number and little else, still append ETB to the detected number for user's code block
    if m:
        # don't mutate original textual message, but for codeblock we will show the number with ETB appended
        return s if "ETB" in s.upper() else s + " ETB"
    return s

def parse_etb_amount(text: str) -> Optional[float]:
    """Parse a numeric ETB amount from admin's reply text. Return float or None if not found."""
    if not text:
        return None
    # remove common currency words to isolate numbers
    cleaned = text.replace("ETB", "").replace("ብር", "").replace(",", "").strip()
    # find first number
    m = re.search(r"(-?\d+(?:\.\d+)?)", cleaned)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

# --------------------
# Open Alibaba menu (accepts multiple callback names used by main.py)
# --------------------
@router.callback_query(F.data.in_({"alibaba_menu_en", "alibaba_menu_am", "service_alibaba_order"}))
async def open_alibaba_order_menu(cb: CallbackQuery, state: FSMContext):
    if cb.data.endswith("_am"):
        lang = "am"
    elif cb.data.endswith("_en"):
        lang = "en"
    else:
        lang = await ensure_lang(state)

    await state.clear()
    await state.update_data(lang=lang)

    title = "📦 Order from AliExpress" if lang == "en" else "📦 ዕቃ ከAliExpress ይዘዙ"
    tutorial_text_en = (
        "Before ordering, please watch this short tutorial to learn how to pick the right product and send complete details.\n\n"
        "Important: watch to the end — it helps avoid delays and mistakes."
    )
    tutorial_text_am = (
        "የትዕዛዝ ሂደት እንዴት እንደሚሆን ለማወቅ እባክዎ ይህን አጭር ቪዲዮ ቀጥሎ ይመልከቱ።\n\n"
        "አስፈላጊ፡ የ ግድ ማወቅ ያለቦት ነገር ስላለ እስከ መጨረሻው ይመልከቱ።"
    )

    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=("▶ Watch tutorial" if lang == "en" else "▶ ቪዲዮ ይመልከቱ"), url=TUTORIAL_YOUTUBE_URL)],
            [InlineKeyboardButton(text=("🛒 Order Now" if lang == "en" else "🛒 አሁን ይዘዙ"), callback_data="alibaba_start_order")],
            [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
        ])
        await cb.message.edit_text(f"{title}\n\n{(tutorial_text_en if lang == 'en' else tutorial_text_am)}", reply_markup=kb)
    except Exception:
        try:
            await cb.message.answer(f"{title}\n\n{(tutorial_text_en if lang == 'en' else tutorial_text_am)}", reply_markup=kb)
        except Exception:
            logger.exception("open_alibaba_order_menu: failed to send tutorial card")

    await cb.answer()

@router.callback_query(F.data == "alibaba_start_order")
async def alibaba_start_order(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    title = "📦 Order from AliExpress" if lang == "en" else "📦 ዕቃ ከAliExpress ይዘዙ"
    txt_en = "Submit product name, product link (Alibaba/AliExpress), and a screenshot/photo.\n\nUse the buttons below to enter each item. When all three are provided we will send your request to admin."
    txt_am = "የእቃው ስም፣ የእቃው አገናኝ (Link) (AliExpress) እና የስክሪንሾት/ፎቶ ያስገቡ።\n\nእያንዳንዱን ዕቃ መረጃ በታች ያሉትን እባክዎ በቁልፍ አዝራሮች ይገብሩ። ሶስቱንም ስያንዱ ስያስገቡ እኛ ለአስተዳዳሪ እንልካለን።"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Product name", callback_data="alibaba_enter_name")],
        [InlineKeyboardButton(text="2️⃣ Product link", callback_data="alibaba_enter_link")],
        [InlineKeyboardButton(text="3️⃣ Product photo / screenshot", callback_data="alibaba_enter_photo")],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    try:
        await cb.message.edit_text(f"{title}\n\n{(txt_en if lang == 'en' else txt_am)}", reply_markup=kb)
    except Exception:
        try:
            await cb.message.answer(f"{title}\n\n{(txt_en if lang == 'en' else txt_am)}", reply_markup=kb)
        except Exception:
            logger.exception("alibaba_start_order: failed to show product info menu")

    await cb.answer()

@router.message(F.text.in_(["📦 Order from AliExpress", "📦 ከAliExpress ዕቃዎች ለማዘዝ"]))
async def alibaba_menu_text(msg: Message, state: FSMContext):
    lang = "am" if is_amharic_text(msg.text) else (await ensure_lang(state))
    await state.clear()
    await state.update_data(lang=lang)
    title = "📦 Order from AliExpress" if lang == "en" else "📦 ዕቃ ከAliExpress ይዘዙ"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Product name", callback_data="alibaba_enter_name")],
        [InlineKeyboardButton(text="2️⃣ Product link", callback_data="alibaba_enter_link")],
        [InlineKeyboardButton(text="3️⃣ Product photo / screenshot", callback_data="alibaba_enter_photo")],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    try:
        await msg.answer(f"{title}\n\nUse the buttons to submit your request." if lang == "en" else f"{title}\n\nእባክዎ እያንዳንዱን ክፍል በቁልፍ ቁልፍ ይሙሉ።", reply_markup=kb)
    except Exception:
        logger.exception("Failed to send alibaba_menu_text reply")

# --------------------
# Step 1: Product name
# --------------------
@router.callback_query(F.data == "alibaba_enter_name")
async def alibaba_enter_name(cb: CallbackQuery, state: FSMContext):
    logger.info("alibaba_enter_name triggered by %s", getattr(cb.from_user, "id", None))
    lang = await ensure_lang(state)
    await state.set_state(AlibabaStates.wait_name)
    prompt = "✍️ Please type the product name now." if lang == "en" else "✍️ እባክዎ የእቃውን ስም አሁን ይጻፉ።"
    kb = kb_back(lang)
    try:
        await cb.message.edit_text(prompt, reply_markup=kb)
    except Exception:
        await cb.message.answer(prompt, reply_markup=kb)
    await cb.answer()

@router.message(AlibabaStates.wait_name, F.text)
async def alibaba_received_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    lang = await ensure_lang(state)
    await state.update_data(product_name=name, lang=lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="2️⃣ Product link", callback_data="alibaba_enter_link")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"alibaba_enter_name")]
    ])
    prompt = "Saved product name. Now tap 2️⃣ Product link." if lang == "en" else "የእቃው ስም ተቀምጧል። አሁን 2️⃣ የእቃው አገናኝ ይጫኑ።"
    await msg.answer(prompt, reply_markup=kb)
    await state.set_state(AlibabaStates.choose)

# --------------------
# Step 2: Product link
# --------------------
@router.callback_query(F.data == "alibaba_enter_link")
async def alibaba_enter_link(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    await state.set_state(AlibabaStates.wait_link)
    prompt = "🔗 Please send the product link (Alibaba or AliExpress URL)." if lang == "en" else "🔗 እባክዎ የእቃውን አገናኝ (Link) ይላኩ።"
    kb = kb_back(lang)
    try:
        await cb.message.edit_text(prompt, reply_markup=kb)
    except Exception:
        await cb.message.answer(prompt, reply_markup=kb)
    await cb.answer()

@router.message(AlibabaStates.wait_link, F.text)
async def alibaba_received_link(msg: Message, state: FSMContext):
    link = msg.text.strip()
    lang = await ensure_lang(state)
    await state.update_data(product_link=link, lang=lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3️⃣ Product photo / screenshot", callback_data="alibaba_enter_photo")],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"alibaba_enter_link")]
    ])
    prompt = "Link saved. Now tap 3️⃣ Product photo / screenshot." if lang == "en" else "Link ተቀምጧል። አሁን 3️⃣ ፎቶ/ስክሪንሾት ይላኩ።"
    await msg.answer(prompt, reply_markup=kb)
    await state.set_state(AlibabaStates.choose)

# --------------------
# Step 3: Product photo
# --------------------
@router.callback_query(F.data == "alibaba_enter_photo")
async def alibaba_enter_photo(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    await state.set_state(AlibabaStates.wait_photo)
    prompt = "📸 Please upload a product photo / screenshot now (photo or document)." if lang == "en" else "📸 እባክዎ የእቃውን ፎቶ/ስክሪንሾት አሁን ያስገቡ (ፎቶ/ፋይል)."
    kb = kb_back(lang)
    try:
        await cb.message.edit_text(prompt, reply_markup=kb)
    except Exception:
        await cb.message.answer(prompt, reply_markup=kb)
    await cb.answer()

@router.message(AlibabaStates.wait_photo, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def alibaba_received_photo(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    name = data.get("product_name")
    link = data.get("product_link")
    # ensure required fields exist
    if not name or not link:
        missing = []
        if not name: missing.append("product name")
        if not link: missing.append("product link")
        if lang == "en":
            missing_text = ", ".join(missing)
            await msg.answer("Please provide the missing fields first: " + missing_text)
        else:
            am_map = {"product name": "የእቃው ስም", "product link": "የእቃው አገናኝ (Link)"}
            missing_am = ", ".join([am_map.get(m, m) for m in missing])
            await msg.answer("እባክዎ የባለውን " + missing_am + " ይሙሉ።")
        await state.set_state(AlibabaStates.choose)
        return

    order_id = gen_order_id()
    date = now_str()
    orders[order_id] = {
        "order_id": order_id,
        "user_id": msg.from_user.id,
        "username": msg.from_user.username or None,
        "product_name": name,
        "product_link": link,
        "product_photo_msg_id": None,
        "created_at": date,
        "lang": lang,
        "address": None,
        "quantity": None,
        "quote_etb": None,
        "quote_numeric": None,
        "payment_method": None,
        "payment_proof_msg_id": None,
        "status": "submitted",
        "admin_handled_by": None
    }

    # Record to tracker: order created (with zero ETB until admin quotes)
    try:
        if record_event:
            record_event("order_created", {
                "service": "alibaba",
                "order_id": order_id,
                "user_id": msg.from_user.id,
                "username": msg.from_user.username or "",
                "amount": None,
                "currency": "ALIBABA_PRODUCT",
                "total_etb": 0.0,  # will be updated when admin replies with quote
                "payment_method": None,
                "status": "submitted",
                "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
        else:
            if record_order:
                record_order("alibaba", {
                    "order_id": order_id,
                    "user_id": msg.from_user.id,
                    "username": msg.from_user.username or "",
                    "amount": None,
                    "currency": "ALIBABA_PRODUCT",
                    "total_etb": 0.0,
                    "status": "submitted",
                    "created_at": datetime.utcnow()
                })
    except Exception:
        pass

    # send product photo to admin with styled caption and copy buttons (do not just forward)
    try:
        caption = (
            f"📦 NEW ALIEXPRESS ORDER\nOrder ID: {order_id}\nDate: {date}\n"
            f"User: @{msg.from_user.username or msg.from_user.id}\n\n"
            f"Product name:\n{name}\n\n"
            f"Product link:\n{link}\n\n"
            f"(Product screenshot attached)"
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Accept Order", callback_data=f"admin_alibaba_accept_{order_id}")],
            [InlineKeyboardButton(text="❌ Decline Order", callback_data=f"admin_alibaba_decline_{order_id}")],
            [InlineKeyboardButton(text="📋 Copy Link", callback_data=f"alibaba_copy:{order_id}:link"),
             InlineKeyboardButton(text="📋 Copy Product Name", callback_data=f"alibaba_copy:{order_id}:product")]
        ])
        # If user sent photo
        if msg.photo:
            file_id = msg.photo[-1].file_id
            sent = await msg.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=caption, reply_markup=admin_kb)
            orders[order_id]["product_photo_msg_id"] = sent.message_id if sent else None
        elif getattr(msg, "document", None):
            file_id = msg.document.file_id
            sent = await msg.bot.send_document(chat_id=ADMIN_ID, document=file_id, caption=caption, reply_markup=admin_kb)
            orders[order_id]["product_photo_msg_id"] = sent.message_id if sent else None
        else:
            # fallback: send text admin summary
            await msg.bot.send_message(chat_id=ADMIN_ID, text=caption, reply_markup=admin_kb)
    except Exception as e:
        logger.exception("notify admin (product photo) failed: %s", e)

    confirm_text = ("All set — we sent your request to the admin. Please wait for confirmation."
                    if lang == "en"
                    else "ሁሉም ተሰርዟል — ጥያቄዎ ወደ አስተዳዳሪ ተልኳል። እባክዎ ለማረጋገጫ ይጠብቁ።")
    await msg.answer(confirm_text, reply_markup=kb_back(lang))
    await state.clear()

# --------------------
# Admin: Decline/Accept order
# --------------------
@router.callback_query(F.data.startswith("admin_alibaba_decline_"))
async def admin_alibaba_decline(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    lang = order.get("lang", "en")
    user_id = order.get("user_id")
    decline_text = (
        "Sorry, your request was declined by the admin. If you need help contact support."
        if lang == "en"
        else "ይቅርታ፣ ጥያቄዎ በአስተዳዳሪ ተሰርዟል። እባክዎ ለእገዛ ወደ ድጋፍ ይግቡ።"
    )
    try:
        await cb.bot.send_message(chat_id=user_id, text=decline_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")],
            [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
        ]))
    except Exception as e:
        logger.exception("failed to notify user about decline: %s", e)

    order["status"] = "declined"
    order["admin_handled_by"] = cb.from_user.id if cb.from_user else None

    # Track decline in tracker
    try:
        if record_event:
            record_event("admin_marked_not_paid", {"service": "alibaba", "order_id": order_id, "user_id": order.get("user_id"), "status": "declined"})
    except Exception:
        pass

    await cb.answer("Order declined.", show_alert=False)

@router.callback_query(F.data.startswith("admin_alibaba_accept_"))
async def admin_alibaba_accept(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    order["status"] = "address_pending"
    order["admin_handled_by"] = cb.from_user.id if cb.from_user else None

    user_id = order.get("user_id")
    lang = order.get("lang", "en")
    try:
        # Short prompt only — instruct user to click the 'Send full shipping address' button.
        await cb.bot.send_message(
            chat_id=user_id,
            text=("✅ Admin accepted your request. Please click the button below to send your full shipping address."
                  if lang == "en"
                  else "✅ አስተዳዳሪው ጥያቄዎን ተቀብሏል። እባክዎ የሙሉ የመላእክት አድራሻ ለማስገባት ታችኛውን አዝራር ይጫኑ።"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✉️ Send full shipping address" if lang == "en" else "✉️ ሙሉ የመላእክት አድራሻ ይላኩ", callback_data=f"user_send_address_{order_id}")],
                [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
            ])
        )
    except Exception as e:
        logger.exception("notify user for address (short) failed: %s", e)

    await cb.answer("User asked for address.", show_alert=False)

# --------------------
# User: tap Send full shipping address button OR send directly when prompted
# --------------------
@router.callback_query(F.data.startswith("user_send_address_"))
async def user_send_address_button(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    lang = order.get("lang", "en")
    await state.update_data(alibaba_pending_order=order_id)
    await state.set_state(AlibabaStates.wait_address)

    # Short instruction and a separate code-block template for copy & replace
    short_prompt = ("Please copy the template below, replace the fields with your details, then send the message back to us."
                    if lang == "en"
                    else "እባክዎ ከዚህ ቅጥ ይቅዱ፣ ክፍሎቹን በዝርዝር በሙሉ ይሙሉ እና ወደ ዚህ ይልኩ።")
    template = (
        "STREET (required):\n"
        "APT/SUITE (optional):\n"
        "STATE/PROVINCE (required):\n"
        "CITY (required):\n"
        "ZIP CODE (required):\n\n"
        "CONTACT NAME (required):\n"
        "MOBILE (+251...) (required):"
    )
    try:
        await cb.message.answer(short_prompt, reply_markup=kb_back(lang))
        # send the template as monospace code block so user can long-press and copy it to edit
        await cb.bot.send_message(chat_id=cb.from_user.id, text=f"`{template}`", parse_mode="Markdown")
    except Exception:
        try:
            await cb.bot.send_message(chat_id=order.get("user_id"), text=short_prompt, reply_markup=kb_back(lang))
            await cb.bot.send_message(chat_id=order.get("user_id"), text=template)
        except Exception:
            logger.exception("Failed to prompt user for address (short/template).")
    await cb.answer()

@router.message(AlibabaStates.wait_address)
async def user_send_address(msg: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("alibaba_pending_order")
    order = safe_get_order(order_id)
    if not order:
        await msg.answer("Order not found or expired.")
        await state.clear()
        return

    # Accept any message content for address (text, caption, multi-line). Prefer text, then caption.
    if msg.text and msg.text.strip():
        address_text = msg.text.strip()
    elif getattr(msg, "caption", None):
        address_text = msg.caption.strip()
    else:
        lang = order.get("lang", "en")
        retry = ("Please send your full shipping address as text." if lang == "en" else "እባክዎ ሙሉ የመላእክት አድራሻዎን እባክዎ በጽሑፍ ይላኩ።")
        await msg.answer(retry, reply_markup=kb_back(order.get("lang", "en")))
        return

    # Simple parser: look for required fields by labels (case-insensitive)
    def find_field(label: str, text: str) -> Optional[str]:
        for line in text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                if label.lower() in k.lower():
                    return v.strip()
        return None

    street = find_field("street", address_text) or find_field("STREET", address_text) or ""
    apt = find_field("apt", address_text) or find_field("suite", address_text) or find_field("APT", address_text) or ""
    state_prov = find_field("state", address_text) or find_field("province", address_text) or ""
    city = find_field("city", address_text) or ""
    zip_code = find_field("zip", address_text) or find_field("postal", address_text) or ""
    contact_name = find_field("contact", address_text) or find_field("recipient", address_text) or ""
    mobile = find_field("mobile", address_text) or find_field("phone", address_text) or ""

    missing = []
    if not street: missing.append("STREET")
    if not state_prov: missing.append("STATE/PROVINCE")
    if not city: missing.append("CITY")
    if not zip_code: missing.append("ZIP CODE")
    if not contact_name: missing.append("CONTACT NAME")
    if not mobile: missing.append("MOBILE (+251...)")

    # Basic mobile normalization / validation: accept +251... or 0xxxxxxxxx and convert to +2519...
    norm_mobile = mobile.strip()
    if norm_mobile.startswith("0") and len(norm_mobile) >= 9:
        if norm_mobile.startswith("09"):
            norm_mobile = "+251" + norm_mobile[1:]
    if not norm_mobile.startswith("+251"):
        # still accept but we won't block; just proceed with what user provided
        pass

    if missing:
        lang = order.get("lang", "en")
        miss_text = ", ".join(missing)
        if lang == "en":
            await msg.answer(f"Please provide all required fields. Missing: {miss_text}\nUse the template form or paste your filled template.", reply_markup=kb_back(lang))
        else:
            await msg.answer(f"እባክዎ ያስፈልጉትን ክፍሎች ይሙሉ። የጎደለው: {miss_text}", reply_markup=kb_back(lang))
        return

    # store address (no strict length restriction)
    order["address"] = address_text
    order["address_sent_at"] = now_str()
    order["status"] = "address_provided"
    lang = order.get("lang", "en")

    # Prepare admin message localized by user's language choice (so admin sees user's language)
    admin_title = "📦 NEW ALIEXPRESS ORDER - ADDRESS PROVIDED"
    admin_text_en = (
        f"{admin_title}\nOrder ID: {order_id}\nDate: {order['address_sent_at']}\n"
        f"User: @{msg.from_user.username or msg.from_user.id}\n\n"
        f"Product: {order.get('product_name')}\n"
        f"Link: {order.get('product_link')}\n\n"
        f"Shipping address:\n{address_text}"
    )
    admin_text_am = (
        f"{admin_title}\nOrder ID: {order_id}\nDate: {order['address_sent_at']}\n"
        f"ተጠቃሚ: @{msg.from_user.username or msg.from_user.id}\n\n"
        f"ዕቃ: {order.get('product_name')}\n"
        f"Link: {order.get('product_link')}\n\n"
        f"የመላእክት አድራሻ:\n{address_text}"
    )
    admin_text = admin_text_en if lang == "en" else admin_text_am

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Accept Address", callback_data=f"admin_address_accept_{order_id}")],
        [InlineKeyboardButton(text="❌ Decline Address", callback_data=f"admin_address_decline_{order_id}")],
        [InlineKeyboardButton(text="📋 Copy Address", callback_data=f"alibaba_copy:{order_id}:address")]
    ])
    try:
        # send admin summary and buttons
        await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=admin_kb)
        # also send a monospace code block to admin so they can long-press to copy the full address easily
        try:
            await msg.bot.send_message(chat_id=ADMIN_ID, text=f"`{address_text}`", parse_mode="Markdown")
        except Exception:
            # ignore formatting failures
            pass
    except Exception as e:
        logger.exception("notify admin with address failed: %s", e)

    # Also update tracker with address info (merge into existing order record)
    try:
        if record_event:
            record_event("order_updated", {
                "service": "alibaba",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "address": address_text,
                "status": "address_provided",
                "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
    except Exception:
        pass

    # Confirmation to user (short)
    await msg.answer(("Address sent to admin. Please wait." if lang == "en" else "አድራሻዎ ወደ አስተዳዳሪ ተልኳል። እባክዎ ይጠብቁ።"), reply_markup=kb_back(lang))
    await state.clear()

# --------------------
# Admin: Decline/Accept Address
# --------------------
@router.callback_query(F.data.startswith("admin_address_decline_"))
async def admin_address_decline(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    user_id = order.get("user_id")
    lang = order.get("lang", "en")
    try:
        await cb.bot.send_message(chat_id=user_id,
                                  text=("❌ Address declined. Please re-enter your shipping address. Example: Street, City, Postal code, Recipient name, Phone."
                                        if lang == "en"
                                        else "❌ አድራሻዎ አልተቀበለም። እባክዎ እንደገና የመላእክት አድራሻ ይላኩ። ምሳሌ፡ የጎዳና, ከተማ, ፖስታ ኮድ, የተቀባዩ ስም, ስልክ."),
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"user_send_address_{order_id}")],
                                      [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
                                  ]))
    except Exception as e:
        logger.exception("notify user address declined failed: %s", e)

    order["status"] = "address_declined"

    # tracker update
    try:
        if record_event:
            record_event("order_updated", {"service": "alibaba", "order_id": order_id, "status": "address_declined"})
    except Exception:
        pass

    await cb.answer("User notified (address declined).", show_alert=False)

@router.callback_query(F.data.startswith("admin_address_accept_"))
async def admin_address_accept(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    order["status"] = "address_accepted"
    user_id = order.get("user_id")
    lang = order.get("lang", "en")

    # tracker update
    try:
        if record_event:
            record_event("order_updated", {"service": "alibaba", "order_id": order_id, "status": "address_accepted"})
    except Exception:
        pass

    try:
        # localize prompt for admin acceptance to user
        await cb.bot.send_message(chat_id=user_id,
                                  text=("✅ Address accepted by admin.\nHow many units do you want? Choose below:"
                                        if lang == "en"
                                        else "✅ አድራሻዎ በአስተዳዳሪ ተቀምጧል።\nስንት አቅም ይፈልጋሉ? ከታች ይምረጡ።"),
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="1", callback_data=f"user_qty_1_{order_id}"),
                                       InlineKeyboardButton(text="2", callback_data=f"user_qty_2_{order_id}"),
                                       InlineKeyboardButton(text="3", callback_data=f"user_qty_3_{order_id}")],
                                      [InlineKeyboardButton(text="🔙 Back", callback_data=f"services_{lang}")]
                                  ]))
    except Exception as e:
        logger.exception("ask user quantity failed: %s", e)

    await cb.answer("User asked for quantity.", show_alert=False)

# --------------------
# User picks quantity -> forward to admin with Reply option
# --------------------
@router.callback_query(F.data.startswith("user_qty_"))
async def user_qty_choice(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 4:
        await cb.answer("Invalid data.", show_alert=True)
        return
    qty = parts[2]
    order_id = parts[3]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    order["quantity"] = int(qty)
    order["status"] = "quantity_selected"
    user_id = order.get("user_id")
    lang = order.get("lang", "en")

    # localized admin text
    admin_title = "📦 NEW ALIEXPRESS ORDER - QUANTITY SELECTED"
    admin_text_en = (
        f"{admin_title}\nOrder ID: {order_id}\nDate: {now_str()}\n"
        f"User: @{order.get('username') or order.get('user_id')}\n\n"
        f"Product: {order.get('product_name')}\n"
        f"Link: {order.get('product_link')}\n\n"
        f"Quantity: {order.get('quantity')}\n\n"
        "Click Reply to send a quoted ETB total for this order."
    )
    admin_text_am = (
        f"{admin_title}\nOrder ID: {order_id}\nDate: {now_str()}\n"
        f"ተጠቃሚ: @{order.get('username') or order.get('user_id')}\n\n"
        f"ዕቃ: {order.get('product_name')}\n"
        f"Link: {order.get('product_link')}\n\n"
        f"ብዛት: {order.get('quantity')}\n\n"
        "ለዚህ ትዕዛዝ የETB ድምር ለማስገባት Reply ይጫኑ።"
    )
    admin_text = admin_text_en if lang == "en" else admin_text_am

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Reply (send quote)", callback_data=f"admin_reply_{order_id}")],
        [InlineKeyboardButton(text="📋 Copy Link", callback_data=f"alibaba_copy:{order_id}:link")]
    ])
    try:
        await cb.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=admin_kb)
    except Exception as e:
        logger.exception("notify admin about quantity failed: %s", e)

    try:
        await cb.message.edit_text(("Quantity saved. Admin will quote the total soon." if lang == "en"
                                    else "ብዛት ተዘርዝሏል። አስተዳዳሪው የETB ድምር በቅርቡ ይልካል።"),
                                   reply_markup=kb_back(lang))
    except Exception:
        try:
            await cb.bot.send_message(chat_id=user_id, text=("Quantity saved. Admin will quote the total soon." if lang == "en"
                                                              else "ብዛት ተዘርዝሏል። አስተዳዳሪው የETB ድምር በቅርቡ ይልካል።"))
        except Exception:
            logger.exception("failed to confirm quantity to user")
    await cb.answer()

# --------------------
# Admin: click Reply (prepare to send quote)
# --------------------
@router.callback_query(F.data.startswith("admin_reply_"))
async def admin_reply_click(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    admin_id = cb.from_user.id if cb.from_user else None
    admin_reply_pending[admin_id] = order_id
    try:
        await cb.bot.send_message(chat_id=admin_id,
                                  text="Please type the quoted ETB total (a number) or any message to send to the buyer for this order.\n\n"
                                       "Example: Total: 12345 ETB (including shipping & fees).")
    except Exception as e:
        logger.exception("prompt admin to type reply failed: %s", e)
    await cb.answer("Please type your reply (it will be forwarded to the buyer).", show_alert=False)

# --------------------
# Admin: typed reply -> forward to user (quote)
# This handler listens for text messages from admin and forwards them
# only when admin_reply_pending contains a mapping for that admin.
# --------------------
@router.message(F.text)
async def admin_text_handler(msg: Message, state: FSMContext):
    global admin_reply_pending
    admin_id = msg.from_user.id
    # Only handle when the message is sent by admin and admin has pending reply
    if admin_id not in admin_reply_pending:
        return  # ignore as normal message (let other handlers process)
    order_id = admin_reply_pending.get(admin_id)
    order = safe_get_order(order_id)
    if not order:
        admin_reply_pending.pop(admin_id, None)
        await msg.answer("Order not found or expired.")
        return

    user_id = order.get("user_id")
    lang = order.get("lang", "en")
    quote_text = msg.text.strip()

    # Save raw quote but also prepare formatted for user display (append ETB when needed)
    order["quote_etb"] = quote_text
    order["status"] = "quoted"
    order["admin_handled_by"] = admin_id

    # Try to extract numeric ETB from admin reply and store as quote_numeric
    numeric = parse_etb_amount(quote_text)
    if numeric is not None:
        order["quote_numeric"] = numeric
    else:
        order["quote_numeric"] = None

    # Update tracker: merge quote amount into existing order record
    try:
        if record_event:
            # use generic "order_updated" so tracker will merge total_etb into existing order
            record_event("order_updated", {
                "service": "alibaba",
                "order_id": order_id,
                "total_etb": numeric if numeric is not None else 0.0,
                "quote_text": quote_text,
                "status": "quoted",
                "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
        else:
            if record_order:
                # fallback: record a new normalized record (best-effort)
                record_order("alibaba", {
                    "order_id": order_id,
                    "user_id": order.get("user_id"),
                    "username": order.get("username") or "",
                    "amount": None,
                    "currency": "ALIBABA_PRODUCT",
                    "total_etb": numeric if numeric is not None else 0.0,
                    "status": "quoted",
                    "created_at": datetime.utcnow()
                })
    except Exception:
        pass

    # If the admin typed a pure number or a string that's basically a number, ensure we show "ETB" to the buyer
    display_quote = format_quote_for_user(quote_text)

    # build user keyboard without inline copy button; send code block for long-press copy
    kb_user = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="I agree" if lang == "en" else "እስማማለው", callback_data=f"user_agree_{order_id}")],
        [InlineKeyboardButton(text="Decline" if lang == "en" else "አጥፋ", callback_data=f"user_decline_{order_id}")]
    ])
    try:
        # send quoted text with friendly label and keyboard
        await msg.bot.send_message(chat_id=user_id,
                                   text=(f"💬 Admin quoted:\n\n{display_quote}" if lang == "en"
                                         else f"💬 አስተዳዳሪ የሰጠው ዋጋ፦\n\n{display_quote}"),
                                   reply_markup=kb_user)
        # send code block with the quote so user can long-press to copy
        try:
            await msg.bot.send_message(chat_id=user_id, text=f"`{display_quote}`", parse_mode="Markdown")
        except Exception:
            pass
    except Exception as e:
        logger.exception("failed to forward admin quote to user: %s", e)

    try:
        await msg.answer("Quote forwarded to buyer.", reply_markup=kb_back("en"))
    except Exception:
        pass

    admin_reply_pending.pop(admin_id, None)

# --------------------
# User: Agree / Decline on quote
# --------------------
@router.callback_query(F.data.startswith("user_decline_"))
async def user_decline_quote(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    lang = order.get("lang", "en")
    user_id = order.get("user_id")
    try:
        await cb.bot.send_message(chat_id=user_id,
                                  text=("Your order is cancelled." if lang == "en" else "ትእዛዙ ተሰርዟል።"),
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")],
                                      [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
                                  ]))
    except Exception as e:
        logger.exception("notify user decline failed: %s", e)

    try:
        await cb.bot.send_message(chat_id=order.get("admin_handled_by") or ADMIN_ID,
                                  text=f"⚠️ Order {order_id} was declined by the buyer.")
    except Exception:
        pass

    order["status"] = "cancelled"

    # tracker update: cancelled
    try:
        if record_event:
            record_event("order_updated", {"service": "alibaba", "order_id": order_id, "status": "cancelled"})
    except Exception:
        pass

    await cb.answer("Order cancelled.", show_alert=False)

@router.callback_query(F.data.startswith("user_agree_"))
async def user_agree_quote(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    lang = order.get("lang", "en")
    user_id = order.get("user_id")
    order["status"] = "awaiting_payment"

    # If quote_numeric exists we can record that the user agreed to that total -> mark as pending payment (tracker update)
    try:
        if record_event:
            record_event("order_updated", {
                "service": "alibaba",
                "order_id": order_id,
                "status": "awaiting_payment",
                "agreed_etb": order.get("quote_numeric") or 0.0,
                "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
    except Exception:
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 CBE", callback_data=f"alibaba_pay_cbe_{order_id}"),
         InlineKeyboardButton(text="📱 Telebirr", callback_data=f"alibaba_pay_tele_{order_id}")],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    try:
        await cb.bot.send_message(chat_id=user_id,
                                  text=("Great — please choose payment method to send the quoted ETB total." if lang == "en"
                                        else "አሁን። እባክዎ የክፍያ ዘዴ ይምረጡ።"),
                                  reply_markup=kb)
    except Exception as e:
        logger.exception("ask user payment method failed: %s", e)

    await cb.answer("Please choose payment method.", show_alert=False)

# --------------------
# User chooses payment method
# --------------------
@router.callback_query(F.data.startswith("alibaba_pay_"))
async def alibaba_pay_choice(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_")
    if len(parts) < 4:
        await cb.answer("Invalid data.", show_alert=True)
        return
    method = parts[2]
    order_id = parts[3]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    lang = order.get("lang", "en")
    total_text = order.get("quote_etb") or "Total not provided"
    if method == "cbe":
        acc = CBE_ACCOUNT
        method_label = "CBE"
    else:
        acc = TELEBIRR_ACCOUNT
        method_label = "Telebirr"

    order["payment_method"] = method_label

    details_text = (
        (f"{'🏦' if method_label=='CBE' else '📱'} {method_label}\nAccount: {acc}\nName: {ACCOUNT_NAME}\n\n"
         f"Send the quoted amount: {total_text}\n\nSend payment, then press ✅ Done and upload payment proof.")
        if lang == "en"
        else
        (f"{'🏦' if method_label=='CBE' else '📱'} {method_label}\nመለያ: {acc}\nስም: {ACCOUNT_NAME}\n\n"
         f"{total_text} ይላኩ። ከዛ  ✅ ይጫኑ እና የክፍያ ማስረጃ ያስገቡ።")
    )
    # include inline copy buttons for account and total for convenience
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Done" if lang == "en" else "✅ ተጠናቋል", callback_data=f"alibaba_done_{order_id}")],
        [InlineKeyboardButton(text="📋 Copy Account", callback_data=f"alibaba_copy:{order_id}:account"),
         InlineKeyboardButton(text="📋 Copy Total", callback_data=f"alibaba_copy:{order_id}:quote")],
        [InlineKeyboardButton(text="❌ Cancel" if lang == "en" else "❌ ሰርዝ", callback_data=f"alibaba_cancel_{order_id}")]
    ])
    try:
        await cb.message.edit_text(details_text, reply_markup=kb)
    except Exception:
        try:
            await cb.bot.send_message(chat_id=order.get("user_id"), text=details_text, reply_markup=kb)
        except Exception as e:
            logger.exception("send payment details failed: %s", e)

    # send monospace code block for the account and total so user can long-press to copy
    try:
        account_block = f"Account: `{acc}`\nPrice: `{total_text}`"
        await cb.bot.send_message(chat_id=order.get("user_id"), text=account_block, parse_mode="Markdown")
    except Exception:
        logger.exception("failed to send account code block")

    await cb.answer()

# --------------------
# User: Done -> ask upload proof
# --------------------
@router.callback_query(F.data.startswith("alibaba_done_"))
async def alibaba_done_prompt(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found", show_alert=True)
        return
    lang = order.get("lang", "en")
    order["status"] = "waiting_payment_proof"
    try:
        await cb.message.edit_text("📸 Please upload the payment proof (photo or document) now." if lang == "en"
                                       else "📸 እባክዎ የክፍያ ማስረጃ ያስገቡ።",
                                       reply_markup=kb_back(lang))
    except Exception as e:
        logger.exception("alibaba done prompt failed: %s", e)
    await cb.answer()

@router.callback_query(F.data.startswith("alibaba_cancel_"))
async def alibaba_cancel(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if order:
        order["status"] = "cancelled"
    lang = order.get("lang", "en") if order else "en"
    try:
        await cb.message.edit_text("Your order is cancelled." if lang == "en" else "ትእዛዙ ተሰርዟል።", reply_markup=kb_back(lang))
    except Exception:
        pass
    await cb.answer()

# --------------------
# User uploads payment proof
# --------------------
@router.message(F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def alibaba_receive_payment_proof(msg: Message, state: FSMContext):
    # debug log to help find which module captures proofs
    logger.debug("[alibaba] potential payment proof from user=%s; checking orders...", msg.from_user.id)

    user_id = msg.from_user.id
    candidate = None
    # find latest order for this user that is waiting for proof (search descending by key)
    for oid, o in list(orders.items()):
        if o.get("user_id") == user_id and o.get("status") == "waiting_payment_proof":
            candidate = o
            break

    if not candidate:
        # Not related to Alibaba; ignore so other modules can handle it.
        logger.debug("[alibaba] no candidate order waiting for proof for user=%s", user_id)
        return

    order_id = candidate["order_id"]
    # Instead of forwarding, prefer to send the photo/document to admin with styled caption and copy buttons
    try:
        caption_title = "📦 NEW ALIEXPRESS ORDER"
        caption = (
            f"{caption_title}\nOrder ID: {order_id}\nDate: {now_str()}\n"
            f"User: @{candidate.get('username') or candidate.get('user_id')}\n\n"
            f"Product: {candidate.get('product_name')}\n"
            f"Link: {candidate.get('product_link')}\n\n"
            f"Quantity: {candidate.get('quantity')}\n"
            f"Quoted: {candidate.get('quote_etb')}\n\n"
            f"Address: {candidate.get('address')}\n\n"
            f"(Payment proof attached)"
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Payment Completed", callback_data=f"admin_alibaba_paid_{order_id}")],
            [InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_alibaba_notpaid_{order_id}")],
            [InlineKeyboardButton(text="📋 Copy Quote", callback_data=f"alibaba_copy:{order_id}:quote"),
             InlineKeyboardButton(text="📋 Copy Address", callback_data=f"alibaba_copy:{order_id}:address")]
        ])
        if msg.photo:
            file_id = msg.photo[-1].file_id
            sent = await msg.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=caption, reply_markup=admin_kb)
            candidate["payment_proof_msg_id"] = sent.message_id if sent else None
        elif getattr(msg, "document", None):
            file_id = msg.document.file_id
            sent = await msg.bot.send_document(chat_id=ADMIN_ID, document=file_id, caption=caption, reply_markup=admin_kb)
            candidate["payment_proof_msg_id"] = sent.message_id if sent else None
        else:
            await msg.bot.send_message(chat_id=ADMIN_ID, text=caption, reply_markup=admin_kb)
    except Exception as e:
        logger.exception("send admin payment summary (with photo) failed: %s", e)

    candidate["status"] = "payment_proof_sent"
    candidate["payment_proof_sent_at"] = now_str()

    # Record that payment proof was uploaded (tracker update)
    try:
        if record_event:
            record_event("order_updated", {
                "service": "alibaba",
                "order_id": order_id,
                "status": "payment_proof_sent",
                "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
    except Exception:
        pass

    lang = candidate.get("lang", "en")
    try:
        await msg.answer("⏳ Waiting for admin confirmation..." if lang == "en" else "⏳ ከአስተዳዳሪ ማረጋገጫ በመጠበቅ ላይ...")
    except Exception:
        pass
    await state.clear()

# --------------------
# Admin: Not paid / Paid handlers
# --------------------
@router.callback_query(F.data.startswith("admin_alibaba_notpaid_"))
async def admin_alibaba_notpaid(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    user_id = order.get("user_id")
    lang = order.get("lang", "en")
    try:
        await cb.bot.send_message(chat_id=user_id,
                                  text=("❌ Payment not received. Please pay again and reupload proof, or contact support."
                                        if lang == "en"
                                        else "❌ ክፍያ አልተቀበለም። እባክዎ ዳግመው ይክፈሉ እና ማስረጃ ያስገቡ ወይም ወደ ድጋፍ ይግቡ።"),
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")],
                                      [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
                                  ]))
    except Exception as e:
        logger.exception("notify user notpaid failed: %s", e)
    order["status"] = "payment_not_received"

    # tracker update
    try:
        if record_event:
            record_event("order_updated", {"service": "alibaba", "order_id": order_id, "status": "payment_not_received"})
    except Exception:
        pass

    await cb.answer("User notified (not paid).", show_alert=False)

@router.callback_query(F.data.startswith("admin_alibaba_paid_"))
async def admin_alibaba_paid(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    order["status"] = "payment_confirmed"
    order["payment_confirmed_at"] = now_str()
    order["admin_handled_by"] = cb.from_user.id if cb.from_user else None
    user_id = order.get("user_id")
    lang = order.get("lang", "en")

    # Record payment confirmed to tracker. Use quote_numeric if available as ETB received.
    try:
        if record_event:
            record_event("admin_confirmed_payment", {
                "service": "alibaba",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "total_etb": order.get("quote_numeric") if order.get("quote_numeric") is not None else (parse_etb_amount(order.get("quote_etb") or "") or 0.0),
                "status": "paid",
                "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
        else:
            if record_order:
                record_order("alibaba", {
                    "order_id": order_id,
                    "user_id": order.get("user_id"),
                    "username": order.get("username") or "",
                    "amount": None,
                    "currency": "ALIBABA_PRODUCT",
                    "total_etb": order.get("quote_numeric") if order.get("quote_numeric") is not None else (parse_etb_amount(order.get("quote_etb") or "") or 0.0),
                    "status": "paid",
                    "created_at": datetime.utcnow()
                })
    except Exception:
        pass

    try:
        # ask user to click Order Now and send code block with Order ID for long-press
        await cb.bot.send_message(chat_id=user_id,
                                  text=("✅ Payment confirmed. Please click Order Now button to place the order."
                                        if lang == "en"
                                        else "✅ ክፍያ ተረጋግጧል። እባክዎ የOrder Now Button ይጫኑ።"),
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="Order Now" if lang == "en" else "አሁን እዘዙ", callback_data=f"user_order_now_{order_id}")],
                                  ]))
        # send code block with order id & quoted price for long-press copy
        try:
            # make sure quoted price shows ETB if admin typed just number
            quote_display = format_quote_for_user(order.get('quote_etb') or "Not provided")
            block = f"Order ID: `{order_id}`\nQuoted: `{quote_display}`"
            await cb.bot.send_message(chat_id=user_id, text=block, parse_mode="Markdown")
        except Exception:
            pass
    except Exception as e:
        logger.exception("ask user to click order now failed: %s", e)

    await cb.answer("User will be asked to Order Now.", show_alert=False)

# --------------------
# User clicks Order Now
# --------------------
@router.callback_query(F.data.startswith("user_order_now_"))
async def user_order_now(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    user_id = order.get("user_id")
    lang = order.get("lang", "en")
    try:
        await cb.message.edit_text(("Your order is successfully created! Wait 5–10 minutes for us to proceed with your order."
                                    if lang == "en"
                                    else "ትእዛዙ Create ተደርጓል! እባክዎ 5–10 ደቂቃ ይጠብቁ እንዲከናወን እና ይዘው እንጀምር።"),
                                   reply_markup=contact_support_button(lang))
    except Exception as e:
        logger.exception("order now reply to user failed: %s", e)

    admin_title = "📦 USER PLACED ORDER"
    admin_text_en = (
        f"{admin_title}\nOrder ID: {order_id}\nUser: @{order.get('username') or order.get('user_id')}\n"
        f"Product: {order.get('product_name')}\nQuantity: {order.get('quantity')}\n"
        f"Address: {order.get('address')}\nQuoted: {order.get('quote_etb')}\n\n"
        "Click when you have placed the product on Alibaba/AliExpress."
    )
    admin_text_am = (
        f"{admin_title}\nOrder ID: {order_id}\nተጠቃሚ: @{order.get('username') or order.get('user_id')}\n"
        f"ዕቃ: {order.get('product_name')}\nብዛት: {order.get('quantity')}\n"
        f"አድራሻ: {order.get('address')}\nየተጠናቀቀ ዋጋ: {order.get('quote_etb')}\n\n"
        "በAlibaba/AliExpress ዕቃውን ሲያስቀምጡ ይጫኑ።"
    )
    admin_text = admin_text_en if lang == "en" else admin_text_am

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Product Ordered", callback_data=f"admin_product_ordered_{order_id}")],
        [InlineKeyboardButton(text="📋 Copy Link", callback_data=f"alibaba_copy:{order_id}:link")]
    ])
    try:
        await cb.bot.send_message(chat_id=order.get("admin_handled_by") or ADMIN_ID, text=admin_text, reply_markup=admin_kb)
    except Exception as e:
        logger.exception("notify admin product ordered failed: %s", e)

    order["status"] = "user_ordered"

    # tracker update: user placed order
    try:
        if record_event:
            record_event("order_updated", {"service": "alibaba", "order_id": order_id, "status": "user_ordered", "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")})
    except Exception:
        pass

    await cb.answer("Order placed.", show_alert=False)

# --------------------
# Admin: Product Ordered -> final confirmation to user
# --------------------
@router.callback_query(F.data.startswith("admin_product_ordered_"))
async def admin_product_ordered(cb: CallbackQuery):
    parts = cb.data.split("_")
    order_id = parts[-1]
    order = safe_get_order(order_id)
    if not order:
        await cb.answer("Order not found", show_alert=True)
        return

    # mark ordered and send final messages
    order["status"] = "ordered"
    order["ordered_at"] = now_str()
    user_id = order.get("user_id")
    lang = order.get("lang", "en")
    try:
        # Add a "Join channel" button at the end of order completion message
        final_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Join our channel for updates", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
        ])
        await cb.bot.send_message(chat_id=user_id,
                                  text=("🎉 Congratulations! Your product is successfully ordered. Wait for shipping and delivery (usually 15–30 days). If you need proof or have questions, click Contact Support. Thanks for ordering from us!"
                                        if lang == "en"
                                        else "🎉 እንኳን ደስ አለዎት! ዕቃዎ ታዟል። ወደ ፖስታ በት እንዲደርስዎ ወይም እስክደወልሎት ከ15–30 ቀናት ይጠብቁ። ማረጋገጫ ወይም ጥያቄ ካለዎት ወደ ድጋፍ ይግቡ። ከእኛ ስላዘዙ እናመሰግናለን!"),
                                  reply_markup=final_kb)
    except Exception as e:
        logger.exception("final notify user ordered failed: %s", e)

    # admin confirmation that includes the package and username + a small admin notification
    try:
        admin_chat = order.get("admin_handled_by") or ADMIN_ID
        await cb.bot.send_message(chat_id=admin_chat, text=(f"✅ User {order.get('username') or order.get('user_id')} order {order_id} marked as PRODUCT ORDERED."))
        # small notification to admin channel/main admin that order completed
        await cb.bot.send_message(chat_id=ADMIN_ID, text=(f"🔔 Order {order_id} completed by admin {cb.from_user.id or 'unknown'}"))
    except Exception:
        logger.exception("send admin confirmation failed")

    # Record completion to tracker so reports include ETB received for this order
    try:
        # prefer quote_numeric if available, otherwise try to parse quote_etb text
        quote_val = order.get("quote_numeric")
        if quote_val is None:
            quote_val = parse_etb_amount(order.get("quote_etb") or "") or 0.0

        if record_event:
            record_event("order_completed", {
                "service": "alibaba",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username") or "",
                "amount": None,
                "currency": "ALIBABA_PRODUCT",
                "total_etb": quote_val,
                "payment_method": order.get("payment_method") or "",
                "status": "completed",
                "created_at": order.get("created_at") or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                "completed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
            })
        else:
            if record_order:
                record_order("alibaba", {
                    "order_id": order_id,
                    "user_id": order.get("user_id"),
                    "username": order.get("username") or "",
                    "amount": None,
                    "currency": "ALIBABA_PRODUCT",
                    "total_etb": quote_val,
                    "status": "completed",
                    "created_at": order.get("created_at") or datetime.utcnow()
                })
    except Exception:
        logger.exception("tracker record for alibaba completion failed", exc_info=True)

    # ARCHIVE: move from orders to archived_orders so further clicks say "Order not found"
    try:
        archived = dict(order)
        archived["archived_at"] = now_str()
        archived_orders[order_id] = archived
        if order_id in orders:
            del orders[order_id]
        logger.info("Order %s archived and removed from active orders", order_id)
    except Exception:
        logger.exception("failed to archive completed order")

    await cb.answer("Admin confirmed product ordered.", show_alert=False)

# --------------------
# Copy handlers (namespaced) - show raw value so user/admin can long-press to copy
# Callback format: alibaba_copy:<order_id>:<field>
# supported fields: address, link, quote, account, product, product_name
# --------------------
@router.callback_query(F.data.startswith("alibaba_copy:"))
async def alibaba_copy_handler(cb: CallbackQuery):
    data = cb.data.split(":", 1)[1]  # "<order_id>:<field>"
    parts = data.split(":", 1)
    if len(parts) != 2:
        # fallback: show raw remainder
        try:
            await cb.message.answer(data)
        except Exception:
            logger.exception("alibaba_copy_handler fallback failed")
        await cb.answer("Value shown (long-press to copy).", show_alert=False)
        return

    order_id, field = parts
    order = orders.get(order_id)
    # If not in active orders maybe it's archived -> treat as not found
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    val = ""
    if field == "address":
        val = order.get("address") or ""
    elif field == "link":
        val = order.get("product_link") or ""
    elif field == "quote":
        # show the quote text or numeric
        val = order.get("quote_etb") or (str(order.get("quote_numeric")) if order.get("quote_numeric") is not None else "")
    elif field == "account":
        # return both bank accounts for convenience
        val = f"CBE: {CBE_ACCOUNT}\nTelebirr: {TELEBIRR_ACCOUNT}"
    elif field in ("product", "product_name"):
        val = order.get("product_name") or ""
    elif field == "username":
        val = order.get("username") or ""
    else:
        val = ""

    if not val:
        try:
            await cb.message.answer("(no value available)")
        except Exception:
            pass
        await cb.answer("No value available.", show_alert=False)
        return

    # send as code block for long-press copy
    try:
        await cb.message.answer(f"`{val}`")
    except Exception:
        try:
            await cb.message.answer(val)
        except Exception:
            try:
                await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=val)
            except Exception:
                logger.exception("alibaba_copy_handler: failed to return raw value")
    await cb.answer("Value shown (long-press to copy).", show_alert=False)

# --------------------
# Fallbacks: if user types or sends something unexpected, provide helpful guidance
# --------------------
@router.message()
async def alibaba_fallback(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    current_state = await state.get_state()
    if current_state:
        return  # let specific handlers handle it

    hint = ("Use the main Services menu to start an Alibaba order." if lang == "en"
            else "እባክዎ የServices ምናሌ ይጠቀሙ እና ከዛ የAlibaba ምንጭ ይጀምሩ።")
    try:
        await msg.answer(hint, reply_markup=kb_back(lang))
    except Exception:
        logger.exception("alibaba_fallback failed to send hint")

# End of file 
