# usdt.py
import time
import logging
from datetime import datetime
from typing import Optional

from aiogram import Router, F, types
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, ContentType
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from tracker import record_order

router = Router()
logger = logging.getLogger(__name__)

# Attempt to import tracker integration (optional)
try:
    import tracker
except Exception:
    tracker = None

def send_to_tracker(event: str, payload: dict):
    """
    Send event to tracker module if available.
    Preference order:
      1. If a direct `record_order(service, data)` is imported (we imported record_order above) use it for order-like events.
      2. Fall back to tracker.* methods if present (record_event, record_order, record, store).
    This keeps backward compatibility with different tracker implementations.
    """
    # 1) prefer the imported record_order for order-like events
    try:
        # If payload has 'service' use it as first arg, otherwise default to 'usdt'
        svc = payload.get("service") if isinstance(payload, dict) and payload.get("service") else "usdt"
        # If the imported record_order is callable, call it
        if callable(record_order):
            # We convert the payload to a normalized dict expected by tracker.record_order:
            # Many tracker implementations expect (service, data) where data is a dict containing keys like:
            # order_id, user_id, username, amount, currency, etb, payment_method, status, created_at, extra
            try:
                record_order(svc, payload)
                return
            except Exception:
                # If direct call fails, we'll try other fallbacks
                logger.exception("Direct record_order call failed, falling back to tracker.* methods")
    except Exception:
        # any failure here we fall back
        logger.exception("Error attempting direct record_order call")

    # 2) fallback to tracker module methods if available
    if not tracker:
        return
    try:
        if hasattr(tracker, "record_event"):
            tracker.record_event(event, payload)
        elif hasattr(tracker, "record_order"):
            # Some trackers have (service, data) signature, some accept single dict
            try:
                # prefer (service, data) if possible
                svc = payload.get("service") if isinstance(payload, dict) and payload.get("service") else "usdt"
                tracker.record_order(svc, payload)
            except Exception:
                # fallback: single-arg call
                try:
                    tracker.record_order(payload)
                except Exception:
                    logger.exception("tracker.record_order call attempts failed")
        elif hasattr(tracker, "record"):
            tracker.record(event, payload)
        else:
            # last effort: try storing under a generic function if exists
            getattr(tracker, "store", lambda *a, **k: None)(event, payload)
    except Exception:
        logger.exception("Tracker call failed for event %s", event)

# -------------------- Config / Constants --------------------
ADMIN_ID = 6968325481

# Prices (ETB) — change as you need
BUY_PRICE = 167.0   # ETB per 1 USDT (customers buy USDT)
SELL_PRICE = 158.0  # ETB per 1 USDT (customers sell USDT)

# Bank/Telebirr Info (replace anytime)
CBE_ACCOUNT = "1000476183921"
TELEBIRR_ACCOUNT = "0916253200"
ACCOUNT_NAME = "Aschalew Desta"

# USDT Wallet (where sellers send USDT)
USDT_WALLET = "TQPqqXBD3jKn9XcfMDNdWaFsL3q9qrUGQv"

# Telegram channel to prompt users to join after completion
CHANNEL_LINK = "https://t.me/plugmarketshop1"
CHANNEL_USERNAME = "@plugmarketshop1"

# In-memory order store: order_id -> dict
orders: dict[str, dict] = {}

# -------------------- FSM States --------------------
class USDTStates(StatesGroup):
    choose_action = State()
    buy_amount = State()
    buy_payment_method = State()
    buy_wait_proof = State()
    buy_wait_wallet = State()

    sell_amount = State()
    sell_wait_proof = State()
    sell_wait_bank_details = State()

# -------------------- Helpers --------------------
def gen_order_id() -> str:
    return str(int(time.time() * 1000))  # ms timestamp as unique id

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def is_amharic_text(text: Optional[str]) -> bool:
    if not text:
        return False
    return any(ch in text for ch in ["ዩ", "አማርኛ", "ግዢ", "ሽያጭ", "ብር"])

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

# Generic copy handler (long-press copy pattern) — same UX as tiktok.py / telegram_premium.py
@router.callback_query(F.data.startswith("copy_val:"))
async def generic_copy_handler(cb: CallbackQuery):
    raw = cb.data.split(":", 1)[1]
    try:
        # send as code block so user/admin can long-press to copy
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

# --------------------
# Open USDT menu (accepts multiple callback names used by main.py)
# --------------------
@router.callback_query(F.data.in_({"usdt_menu_en", "usdt_menu_am", "service_usdt"}))
async def open_usdt_menu(cb: CallbackQuery, state: FSMContext):
    if cb.data.endswith("_am"):
        lang = "am"
    elif cb.data.endswith("_en"):
        lang = "en"
    else:
        lang = await ensure_lang(state)

    await state.clear()
    await state.update_data(lang=lang)

    buy_text = "🟢 Buy USDT" if lang == "en" else "🟢 USDT ግዢ"
    sell_text = "🔴 Sell USDT" if lang == "en" else "🔴 USDT ሽያጭ"
    back_text = "🔙 Back" if lang == "en" else "🔙 ተመለስ"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=buy_text, callback_data="buy_usdt"),
         InlineKeyboardButton(text=sell_text, callback_data="sell_usdt")],
        [InlineKeyboardButton(text=back_text, callback_data=f"services_{lang}")]
    ])
    title = "💱 USDT Service — Choose Buy or Sell" if lang == "en" else "💱 የUSDT አገልግሎት — ግዢ ወይም ሽያጭ ይምረጡ"
    try:
        await cb.message.edit_text(title, reply_markup=kb)
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=title, reply_markup=kb)
    await cb.answer()

# -------------------- Entry from text (fallback) --------------------
@router.message(F.text.in_(["💸 Buy/Sell USDT", "💸 ዩኤስዲቲ ግዢ/ሽያጭ"]))
async def usdt_menu_text(msg: types.Message, state: FSMContext):
    lang = "am" if is_amharic_text(msg.text) else "en"
    await state.clear()
    await state.update_data(lang=lang)

    buy_text = "🟢 Buy USDT" if lang == "en" else "🟢 USDT ግዢ"
    sell_text = "🔴 Sell USDT" if lang == "en" else "🔴 USDT ሽያጭ"
    back_text = "🔙 Back" if lang == "en" else "🔙 ተመለስ"  # fallback (should not reach here)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=buy_text, callback_data="buy_usdt"),
         InlineKeyboardButton(text=sell_text, callback_data="sell_usdt")],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    title = "💱 USDT Service — Choose Buy or Sell" if lang == "en" else "💱 የUSDT አገልግሎት — ግዢ ወይም ሽያጭ ይምረጡ"
    await msg.answer(title, reply_markup=kb)

# -------------------- BUY FLOW --------------------
@router.callback_query(F.data == "buy_usdt")
async def buy_step1(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    await state.update_data(lang=lang)
    await state.set_state(USDTStates.buy_amount)

    prompt_en = (
        f"💰 Current buying price: {BUY_PRICE} ETB per 1 USDT.\n\n"
        "How much USDT do you want to buy? Write the amount (minimum $3).\n\n"
        "Fee rule: If you choose UNDER $50 a $1 service fee applies — example: if you choose $49, you will receive $(49 - 1) = $48 USDT.\n"
        "The Total ETB shown is calculated from the full amount you entered (amount × price)."
    )
    prompt_am = (
        f"💰 የመግዥዐ ዋጋ: 1 USDT = {BUY_PRICE} ብር\n\n"
        "እባክዎ ምን ያህል USDT መግዛት ይፈልጋሉ? መጠን ያስገቡ (ከ $3 ይበልጥ).\n\n"
        "የክፍያ ደንብ: ከ $50 በታች ከመረጡ 1$ ለክፍያ fee ይቆረጣል — ምሳሌ: 49$ ከመረጡ እኛ 48$ USDT እንሰጣለን።\n"
        "አጠቃላይ ብር የተገለፀው እርስዎ የመረጡት የሙሉ መጠንን ነው።"
    )
    prompt = prompt_en if lang == "en" else prompt_am

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    try:
        await cb.message.edit_text(prompt, reply_markup=kb)
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=prompt, reply_markup=kb)
    await cb.answer()

@router.message(USDTStates.buy_amount)
async def buy_amount_received(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    txt = (msg.text or "").strip()
    try:
        amount = float(txt.replace(",", ""))
    except:
        await msg.answer("❗️ Please enter a valid number." if lang == "en" else "❗️ እባክዎ ትክክለኛ ቁጥር ያስገቡ።")
        return

    if amount < 3:
        await msg.answer("❗️ Minimum is $3." if lang == "en" else "❗️ አነስተኛው $3 ነው።")
        return

    fee = 1.0 if amount < 50.0 else 0.0
    recv_usdt = amount - fee
    total_etb = round(amount * BUY_PRICE, 2)  # **IMPORTANT: total uses full amount entered**

    await state.update_data(buy_amount=amount, buy_fee=fee, buy_recv_usdt=recv_usdt, buy_total=total_etb)
    await state.set_state(USDTStates.buy_payment_method)

    if lang == "en":
        lines = [
            f"🧾 You requested: ${amount:.2f}",
            f"Service fee: ${fee:.2f}" if fee > 0 else "Service fee: $0.00",
            f"You will receive: {recv_usdt:.2f} USDT (after fee)",
            f"Total to pay (ETB) based on full amount: {total_etb:.2f} ETB",
            "",
            "Choose payment method:"
        ]
    else:
        lines = [
            f"🧾 የተጠየቀው: ${amount:.2f}",
            (f"የአገልግሎት ክፍያ: ${fee:.2f}" if fee > 0 else "የአገልግሎት ክፍያ: $0.00"),
            f"የምትቀበሉት: {recv_usdt:.2f} USDT (ከክፍያ በኋላ)",
            f"አጠቃላይ የሚከፈለው (ብር) የሙሉ መጠን በዋጋ: {total_etb:.2f} ብር",
            "",
            "የክፍያ ዘዴ ይምረጡ፦"
        ]
    prompt = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 CBE", callback_data="buy_cbe"),
         InlineKeyboardButton(text="📱 Telebirr", callback_data="buy_telebirr")],
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data="buy_usdt")]
    ])
    await msg.answer(prompt, reply_markup=kb)

@router.callback_query(F.data.in_(["buy_cbe", "buy_telebirr"]))
async def buy_payment_method_choice(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    amount = data.get("buy_amount")
    recv_usdt = data.get("buy_recv_usdt")
    total_etb = data.get("buy_total")

    method = "CBE" if cb.data == "buy_cbe" else "Telebirr"
    acc = CBE_ACCOUNT if method == "CBE" else TELEBIRR_ACCOUNT
    name = ACCOUNT_NAME

    # store payment method to be available later when creating order
    await state.update_data(payment_method=method)

    if lang == "en":
        details = f"{'🏦' if method=='CBE' else '📱'} {method}\nAccount: `{acc}`\nName: `{name}`\n\nSend *{total_etb:.2f}* ETB to the above account and then press ✅ Done and upload payment proof."
    else:
        details = f"{'🏦' if method=='CBE' else '📱'} {method}\nመለያ: `{acc}`\nስም: `{name}`\n\nእባክዎ *{total_etb:.2f}* ብር ይላኩ ከዛ ይጫኑ ✅ እና የክፍያ ማስረጃ ያስገቡ።"

    await state.set_state(USDTStates.buy_wait_proof)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Done" if lang == "en" else "✅ ተጠናቋል", callback_data="buy_done")],
        [InlineKeyboardButton(text="❌ Cancel" if lang == "en" else "❌ ሰርዝ", callback_data="cancel_usdt")],
        # copy uses generic copy_val handler for long-press copy UX
        [InlineKeyboardButton(text="📋 Copy Account", callback_data=f"copy_val:{acc}")]
    ])
    try:
        await cb.message.edit_text(details, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=details, reply_markup=kb, parse_mode="Markdown")
    await cb.answer()

@router.callback_query(F.data == "buy_done")
async def buy_done_prompt(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    try:
        await cb.message.edit_text(
            "📸 Please upload the payment proof (photo or document) now." if lang == "en"
            else "📸 እባክዎ የክፍያ ማስረጃውን (ፎቶ ወይም ፋይል) አሁን ያስገቡ።",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data="buy_usdt")]
            ])
        )
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id,
                                  text="📸 Please upload the payment proof (photo or document) now." if lang == "en"
                                  else "📸 እባክዎ የክፍያ ማስረጃውን (ፎቶ ወይም ፋይል) አሁን ያስገቡ።",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data="buy_usdt")]
                                  ]))
    await cb.answer()

@router.message(USDTStates.buy_wait_proof, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def buy_receive_proof(msg: Message, state: FSMContext):
    """
    When user uploads proof for a BUY order:
    - create an order entry (incl. payment_method)
    - send the proof (photo/document) to admin with a nice caption and initial Paid/Not Paid buttons
    - use copy_val for copy buttons (long-press copy UX)
    """
    data = await state.get_data()
    lang = data.get("lang", "en")
    amount = data.get("buy_amount")
    recv_usdt = data.get("buy_recv_usdt")
    fee = data.get("buy_fee", 0.0)
    total = data.get("buy_total")
    payment_method = data.get("payment_method", "Unknown")
    order_id = gen_order_id()
    date = now_str()

    # Determine file_id and send to admin as a new message (not a forward) with caption
    file_id = None
    try:
        if msg.content_type == ContentType.PHOTO and msg.photo:
            file_id = msg.photo[-1].file_id
            # caption
            if lang == "en":
                admin_caption = (
                    "🎵 🔔 NEW BUY ORDER\n\n"
                    f"🆔 Order ID: `{order_id}`\n"
                    f"📅 Date: {date}\n"
                    f"👤 User: @{msg.from_user.username or msg.from_user.id}\n"
                    f"🧾 Requested: ${amount:.2f}\n"
                    f"💸 Fee: ${fee:.2f}\n"
                    f"🎯 Will receive: {recv_usdt:.2f} USDT\n"
                    f"💳 Total ETB (full amount): {total:.2f} ETB\n"
                    f"💳 Payment method: {payment_method}\n\n"
                    "(See attached proof image)"
                )
            else:
                admin_caption = (
                    "🎵 🔔 አዲስ የUSDT ግዢ ትእዛዝ\n\n"
                    f"🆔 የትእዛዝ መለያ: `{order_id}`\n"
                    f"📅 ቀን: {date}\n"
                    f"👤 ተጠቃሚ: @{msg.from_user.username or msg.from_user.id}\n"
                    f"🧾 የተጠየቀው: ${amount:.2f}\n"
                    f"💸 ክፍያ: ${fee:.2f}\n"
                    f"🎯 የምትቀበሉት: {recv_usdt:.2f} USDT\n"
                    f"💳 አጠቃላይ ብር (ሙሉ መጠን): {total:.2f} ብር\n"
                    f"💳 የክፍያ ዘዴ: {payment_method}\n\n"
                    "(የክፍያ ማስረጃ ምስል ተያይዞ ነው)"
                )
            # send photo with admin caption + simple Paid/NotPaid keyboard
            admin_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Paid", callback_data=f"admin_buy_paid_{msg.from_user.id}_{order_id}"),
                 InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_buy_notpaid_{msg.from_user.id}_{order_id}")]
            ])
            await msg.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=admin_caption, parse_mode="Markdown", reply_markup=admin_kb)
        else:
            # document or other: send document with caption
            if msg.document:
                file_id = msg.document.file_id
                if lang == "en":
                    admin_caption = (
                        "🎵 🔔 NEW BUY ORDER (document)\n\n"
                        f"🆔 Order ID: `{order_id}`\n"
                        f"📅 Date: {date}\n"
                        f"👤 User: @{msg.from_user.username or msg.from_user.id}\n"
                        f"🧾 Requested: ${amount:.2f}\n"
                        f"💸 Fee: ${fee:.2f}\n"
                        f"🎯 Will receive: {recv_usdt:.2f} USDT\n"
                        f"💳 Total ETB (full amount): {total:.2f} ETB\n"
                        f"💳 Payment method: {payment_method}\n\n"
                        "(See attached proof document)"
                    )
                else:
                    admin_caption = (
                        "🎵 🔔 አዲስ የUSDT ግዢ ትእዛዝ (ዶክመንት)\n\n"
                        f"🆔 የትእዛዝ መለያ: `{order_id}`\n"
                        f"📅 ቀን: {date}\n"
                        f"👤 ተጠቃሚ: @{msg.from_user.username or msg.from_user.id}\n"
                        f"🧾 የተጠየቀው: ${amount:.2f}\n"
                        f"💸 ክፍያ: ${fee:.2f}\n"
                        f"🎯 የምትቀበሉት: {recv_usdt:.2f} USDT\n"
                        f"💳 አጠቃላይ ብር (ሙሉ መጠን): {total:.2f} ብር\n"
                        f"💳 የክፍያ ዘዴ: {payment_method}\n\n"
                        "(የክፍያ ማስረጃ ዶክመንት ተያይዞ ነው)"
                    )
                admin_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Paid", callback_data=f"admin_buy_paid_{msg.from_user.id}_{order_id}"),
                     InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_buy_notpaid_{msg.from_user.id}_{order_id}")]
                ])
                await msg.bot.send_document(chat_id=ADMIN_ID, document=file_id, caption=admin_caption, parse_mode="Markdown", reply_markup=admin_kb)
            else:
                # fallback - forward if we couldn't access content type
                forwarded_msg = await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
                if lang == "en":
                    admin_caption = (
                        "🎵 🔔 NEW BUY ORDER\n\n"
                        f"🆔 Order ID: `{order_id}`\n"
                        f"📅 Date: {date}\n"
                        f"👤 User: @{msg.from_user.username or msg.from_user.id}\n"
                        f"🧾 Requested: ${amount:.2f}\n"
                        f"💸 Fee: ${fee:.2f}\n"
                        f"🎯 Will receive: {recv_usdt:.2f} USDT\n"
                        f"💳 Total ETB (full amount): {total:.2f} ETB\n"
                        f"💳 Payment method: {payment_method}\n\n"
                        "(Proof forwarded above)"
                    )
                else:
                    admin_caption = (
                        "🎵 🔔 አዲስ የUSDT ግዢ ትእዛዝ\n\n"
                        f"🆔 የትእዛዝ መለያ: `{order_id}`\n"
                        f"📅 ቀን: {date}\n"
                        f"👤 ተጠቃሚ: @{msg.from_user.username or msg.from_user.id}\n"
                        f"🧾 የተጠየቀው: ${amount:.2f}\n"
                        f"💸 ክፍያ: ${fee:.2f}\n"
                        f"🎯 የምትቀበሉት: {recv_usdt:.2f} USDT\n"
                        f"💳 አጠቃላይ ብር (ሙሉ መጠን): {total:.2f} ብር\n"
                        f"💳 የክፍያ ዘዴ: {payment_method}\n\n"
                        "(Proof forwarded above)"
                    )
                admin_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Paid", callback_data=f"admin_buy_paid_{msg.from_user.id}_{order_id}"),
                     InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_buy_notpaid_{msg.from_user.id}_{order_id}")]
                ])
                await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_caption, parse_mode="Markdown", reply_markup=admin_kb)
    except Exception as e:
        logger.exception("Failed sending proof to admin: %s", e)
        # fallback: forward message to admin if send_photo/send_document fails
        try:
            await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception:
            logger.exception("Final fallback forward failed.")

    # Save order with payment_method and lang so admin/user flows can reference them
    orders[order_id] = {
        "type": "buy",
        "user_id": msg.from_user.id,
        "username": msg.from_user.username or None,
        "amount": amount,
        "recv_usdt": recv_usdt,
        "fee": fee,
        "total": total,
        "lang": lang,
        "created_at": date,
        "payment_method": payment_method,
        "wallet": None,
        "wallet_sent_at": None,
        "status": "waiting_admin"
    }

    # Send to tracker: order created
    try:
        send_to_tracker("order_created", {
            "service": "usdt",
            "subtype": "buy",
            "order_id": order_id,
            "user_id": msg.from_user.id,
            "username": msg.from_user.username,
            "order_id_display": order_id,
            "amount": amount,
            "amount_usd": amount,
            "recv_usdt": recv_usdt,
            "fee_usd": fee,
            "etb": total,
            "total_etb": total,
            "payment_method": payment_method,
            "status": "waiting_admin",
            "created_at": date
        })
    except Exception:
        logger.exception("Failed to send buy order to tracker")

    # Send confirmation to user
    await msg.answer("⏳ Waiting for admin confirmation..." if lang == "en" else "⏳ ከአስተዳዳሪ ማረጋገጫ በመጠበቅ ላይ...")
    await state.clear()

# -------------------- Admin handlers for BUY --------------------
@router.callback_query(F.data.startswith("admin_buy_paid_"))
async def admin_buy_paid(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 5:
        await cb.answer("Invalid callback data.", show_alert=True)
        return
    user_id = int(parts[3])
    order_id = parts[4]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    # mark status in order store (optional)
    order["status"] = "paid_by_admin"

    lang = order.get("lang", "en")
    payment_method = order.get("payment_method", "Unknown")
    acc_info = CBE_ACCOUNT if payment_method == "CBE" else TELEBIRR_ACCOUNT if payment_method == "Telebirr" else ""

    # build message text robustly to avoid syntax issues
    if lang == "en":
        msg_text = "✅ Admin marked your payment as received.\n\n"
        msg_text += f"Payment method: *{payment_method}*\n"
        if acc_info:
            msg_text += f"Account: `{acc_info}`\n\n"
        msg_text += "Please send your TRC20 wallet address (start with a capital 'T') now."
    else:
        msg_text = "✅ አስተዳዳሪው ክፍያዎን ተቀብሏል።\n\n"
        msg_text += f"የክፍያ ዘዴ: *{payment_method}*\n"
        if acc_info:
            msg_text += f"መለያ: `{acc_info}`\n\n"
        msg_text += "እባክዎ የTRC20 ዋሌት አድራሻዎን አሁን ይላኩ። (ዋሌቱ በ' T ' ትክክለኛ ፊደል ይጀምር)"

    try:
        kb_rows = [
            [InlineKeyboardButton(text="✉️ Send Wallet (TRC20)", callback_data=f"user_send_wallet_{order_id}")]
        ]
        if acc_info:
            kb_rows.append([InlineKeyboardButton(text="📋 Copy Account", callback_data=f"copy_val:{acc_info}")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        await cb.bot.send_message(chat_id=user_id, text=msg_text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.exception("notify buyer after admin_paid failed: %s", e)

    # Tracker: admin marked proof as paid (awaiting wallet)
    try:
        send_to_tracker("admin_confirmed_payment", {
            "service": "usdt",
            "subtype": "buy",
            "order_id": order_id,
            "admin_id": cb.from_user.id,
            "user_id": user_id,
            "time": now_str(),
            "status": "paid_by_admin"
        })
    except Exception:
        logger.exception("Failed to send admin_confirmed_payment to tracker")

    await cb.answer("Buyer notified.", show_alert=False)

@router.callback_query(F.data.startswith("admin_buy_notpaid_"))
async def admin_buy_notpaid(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 5:
        await cb.answer("Invalid callback data.", show_alert=True)
        return
    user_id = int(parts[3])
    order_id = parts[4]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    lang = order.get("lang", "en")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"buy_usdt")],
        [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
    ])
    try:
        await cb.bot.send_message(chat_id=user_id,
                                  text=("❌ Payment not received. Please pay again and reupload proof, or contact support."
                                        if lang == "en"
                                        else "❌ ክፍያ አልተቀበለም። እባክዎ ዳግመው ይክፈሉ እና ማስረጃዎን ያስገቡ።"),
                                  reply_markup=kb)
    except Exception as e:
        logger.exception("notify buyer notpaid failed: %s", e)

    # Tracker: admin marked as not paid
    try:
        send_to_tracker("admin_marked_not_paid", {
            "service": "usdt",
            "subtype": "buy",
            "order_id": order_id,
            "admin_id": cb.from_user.id,
            "user_id": user_id,
            "time": now_str(),
            "status": "not_paid"
        })
    except Exception:
        logger.exception("Failed to send admin_marked_not_paid to tracker")

    await cb.answer("User notified (not paid).", show_alert=False)

# -------------------- Buyer sends wallet (after admin_paid) --------------------
@router.callback_query(F.data.startswith("user_send_wallet_"))
async def user_send_wallet_button(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found", show_alert=True)
        return
    await state.update_data(pending_order=order_id)
    await state.set_state(USDTStates.buy_wait_wallet)
    lang = order.get("lang", "en")
    await cb.message.answer("Please send your TRC20 wallet address now. (include TRC20 text; address must start with capital 'T')" if lang == "en"
                            else "እባክዎ የTRC20 ዋሌት አድራሻዎን አሁን ይላኩ። (TRC20 እና አድራሻው በታላቅ 'T' እንዲጀምር ያረጋግጡ)")
    await cb.answer()

@router.message(USDTStates.buy_wait_wallet, F.text)
async def user_send_wallet(msg: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("pending_order")
    order = orders.get(order_id)
    if not order:
        await msg.answer("Order not found or expired.")
        await state.clear()
        return

    wallet = (msg.text or "").strip()
    # Validate that wallet starts with capital 'T'
    if not wallet or not wallet.startswith("T"):
        lang = order.get("lang", "en")
        err_msg = ("❌ Wallet address must start with capital 'T'. Please send again (start with 'T')."
                   if lang == "en" else
                   "❌ የዋሌት አድራሻ በታላቅ 'T' መጀመር አለታ እባክዎ እንደገና ይላኩ።")
        await msg.answer(err_msg)
        return  # keep state so user can resend

    order["wallet"] = wallet
    order["wallet_sent_at"] = now_str()

    # Notify admin with wallet and provide Payment Completed + copy button (use copy_val)
    lang = order.get("lang", "en")
    if lang == "en":
        admin_text = (
            f"🔔 BUY ORDER WALLET\n\n"
            f"🆔 Order ID: {order_id}\n"
            f"📅 Wallet sent at: {order['wallet_sent_at']}\n"
            f"👤 User: @{msg.from_user.username or msg.from_user.id}\n"
            f"🧾 Requested Amount: ${order.get('amount'):.2f}\n"
            f"💳 Total ETB (full amount): {order.get('total'):.2f}\n"
            f"🔗 Wallet: `{wallet}`"
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Payment Completed", callback_data=f"payment_completed_{order_id}")],
            [InlineKeyboardButton(text="📋 Copy Wallet", callback_data=f"copy_val:{wallet}")],
        ])
    else:
        admin_text = (
            f"🔔 የUSDT ግዢ ዋሌት\n\n"
            f"🆔 የትእዛዝ መለያ: {order_id}\n"
            f"📅 የዋሌት ላክለት: {order['wallet_sent_at']}\n"
            f"👤 ተጠቃሚ: @{msg.from_user.username or msg.from_user.id}\n"
            f"🧾 የተጠየቀው: ${order.get('amount'):.2f}\n"
            f"💳 አጠቃላይ ብር (ሙሉ መጠን): {order.get('total'):.2f} ብር\n"
            f"🔗 ዋሌት: `{wallet}`"
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Payment Completed", callback_data=f"payment_completed_{order_id}")],
            [InlineKeyboardButton(text="📋 ዋሌት ኮፒ", callback_data=f"copy_val:{wallet}")],
        ])

    try:
        await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="Markdown", reply_markup=admin_kb)
    except Exception as e:
        logger.exception("Failed to send wallet to admin: %s", e)

    # Tracker: wallet provided by user (admin will complete)
    try:
        send_to_tracker("wallet_sent", {
            "service": "usdt",
            "subtype": "buy",
            "order_id": order_id,
            "user_id": order.get("user_id"),
            "username": order.get("username"),
            "wallet": wallet,
            "time": order.get("wallet_sent_at"),
            "status": "wallet_sent"
        })
    except Exception:
        logger.exception("Failed to send wallet_sent to tracker")

    await msg.answer("✅ Wallet sent to admin. They will deliver USDT shortly." if order.get("lang","en") == "en"
                     else "✅ ዋሌትዎ አስተዳዳሪው ወደ እኛ ተልኳል።")
    await state.clear()

# Keep the old copy_wallet_ handler for backwards compatibility if used elsewhere
@router.callback_query(F.data.startswith("copy_wallet_"))
async def copy_wallet_cb(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    wallet = order.get("wallet")
    if not wallet:
        await cb.answer("Wallet not found.", show_alert=True)
        return
    try:
        await cb.message.answer(f"`{wallet}`", parse_mode="Markdown")
    except Exception:
        await cb.message.answer(wallet)
    await cb.answer("Value shown (long-press to copy).")

# -------------------- SELL FLOW --------------------
@router.callback_query(F.data == "sell_usdt")
async def sell_step1(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    await state.update_data(lang=lang)
    await state.set_state(USDTStates.sell_amount)

    prompt_en = (
        f"💰 Current selling price: {SELL_PRICE} ETB per 1 USDT.\n\n"
        "How much USDT do you want to sell? Write the amount (minimum $3).\n\n"
        "Fee rule: If you send UNDER $50 a $1 fee is taken from the USDT we receive. Example:\n"
        "- If you send $49 we receive $(49 - 1) = $48 → ETB = 48 * price.\n"
        "- If you want us to receive $49 you must SEND $50."
    )
    prompt_am = (
        f"💰 የመሽጫ ዋጋ: 1 USDT = {SELL_PRICE} ብር\n\n"
        "እባክዎ ምን ያህል USDT ለማሽጥ ይፈልጋሉ? መጠን ያስገቡ (ከ $3 ይበልጥ).\n\n"
        "የክፍያ ደንብ: ከ $50 በታች ካስገቡ 1$ ለክፍያ fee ይቆረጣል ይተካል። ምሳሌ: 49$ ካላኩ እኛ 48$ እንቀበላለን።"
    )
    prompt = prompt_en if lang == "en" else prompt_am

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"services_{lang}")]
    ])
    try:
        await cb.message.edit_text(prompt, reply_markup=kb)
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text=prompt, reply_markup=kb)
    await cb.answer()

@router.message(USDTStates.sell_amount)
async def sell_amount_received(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    txt = (msg.text or "").strip()
    try:
        amount = float(txt.replace(",", ""))
    except:
        await msg.answer("❗️ Please enter a valid number." if lang == "en" else "❗️ እባክዎ ትክክለኛ ቁጥር ያስገቡ።")
        return

    if amount < 3:
        await msg.answer("❗️ Minimum is $3." if lang == "en" else "❗️ አነስተኛው $3 ነው።")
        return

    fee = 1.0 if amount < 50.0 else 0.0
    recv_usdt = amount - fee
    total_etb = round(recv_usdt * SELL_PRICE, 2)

    await state.update_data(sell_amount=amount, sell_fee=fee, sell_recv_usdt=recv_usdt, sell_total=total_etb)
    await state.set_state(USDTStates.sell_wait_proof)

    if lang == "en":
        prompt = (
            f"📥 Send {amount:.2f} USDT (TRC20) to this wallet:\n`{USDT_WALLET}`\n\n"
            f"Fee: ${fee:.2f}\n"
            f"USDT we receive (after fee): {recv_usdt:.2f}\n"
            f"Total ETB you will get: {total_etb:.2f}\n\n"
            "After sending, click ✅ Done and upload transfer proof (photo or document)."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Done", callback_data="sell_done")],
            [InlineKeyboardButton(text="📋 Copy Address", callback_data=f"copy_val:{USDT_WALLET}")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="sell_usdt")]
        ])
    else:
        prompt = (
            f"📥 {amount:.2f} USDT (TRC20) ወደዚህ ዋሌት ይላኩ፦\n`{USDT_WALLET}`\n\n"
            f"ክፍያ: ${fee:.2f}\n"
            f"እኛ የምንቀበልዎት (ከክፍያ በኋላ): {recv_usdt:.2f} USDT\n"
            f"የሚከፈለው ብር: {total_etb:.2f}\n\n"
            "ከላኩ በኋላ ✅ ይጫኑ እና የግብዣ ማስረጃ ያስገቡ።"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ተጠናቋል", callback_data="sell_done")],
            [InlineKeyboardButton(text="📋 አድራሻ ኮፒ", callback_data=f"copy_val:{USDT_WALLET}")],
            [InlineKeyboardButton(text="🔙 ተመለስ", callback_data="sell_usdt")]
        ])

    await msg.answer(prompt, reply_markup=kb)

@router.callback_query(F.data == "sell_done")
async def sell_done_prompt(cb: CallbackQuery, state: FSMContext):
    lang = await ensure_lang(state)
    await state.set_state(USDTStates.sell_wait_proof)
    try:
        await cb.message.edit_text("📸 Please upload the transfer proof (photo or document) now." if lang == "en"
                                   else "📸 እባክዎ የግብዣ ማስረጃዎን አሁን ያስገቡ።")
    except Exception:
        await cb.bot.send_message(chat_id=cb.from_user.id, text="📸 Please upload the transfer proof (photo or document) now." if lang == "en"
                                  else "📸 እባክዎ የግብዣ ማስረጃዎን አሁን ያስገቡ።")
    await cb.answer()

@router.message(USDTStates.sell_wait_proof, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def sell_receive_proof(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    amount = data.get("sell_amount")
    recv_usdt = data.get("sell_recv_usdt")
    fee = data.get("sell_fee", 0.0)
    total = data.get("sell_total")
    order_id = gen_order_id()
    date = now_str()

    # Send proof to admin as photo/document (not forwarded) with a localized caption and initial Paid/Not Paid buttons
    try:
        if msg.content_type == ContentType.PHOTO and msg.photo:
            file_id = msg.photo[-1].file_id
            if lang == "en":
                admin_caption = (
                    "🎵 🔔 NEW SELL ORDER\n\n"
                    f"🆔 Order ID: `{order_id}`\n"
                    f"📅 Date: {date}\n"
                    f"👤 User: @{msg.from_user.username or msg.from_user.id}\n"
                    f"📤 Amount sent: ${amount:.2f}\n"
                    f"💸 Fee: ${fee:.2f}\n"
                    f"🎯 USDT we receive: {recv_usdt:.2f}\n"
                    f"💳 ETB to send: {total:.2f}\n\n"
                    "(See attached proof image)"
                )
            else:
                admin_caption = (
                    "🎵 🔔 አዲስ የUSDT ሽያጭ ትእዛዝ\n\n"
                    f"🆔 የትእዛዝ መለያ: `{order_id}`\n"
                    f"📅 ቀን: {date}\n"
                    f"👤 ተጠቃሚ: @{msg.from_user.username or msg.from_user.id}\n"
                    f"📤 የተላከ መጠን: ${amount:.2f}\n"
                    f"💸 ክፍያ: ${fee:.2f}\n"
                    f"🎯 እኛ የምንቀበልዎት: {recv_usdt:.2f}\n"
                    f"💳 የሚከፈለው ብር: {total:.2f}\n\n"
                    "(የግብዣ ማስረጃ ምስል ተያይዞ ነው)"
                )
            admin_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Paid", callback_data=f"admin_sell_paid_{msg.from_user.id}_{order_id}"),
                 InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_sell_notpaid_{msg.from_user.id}_{order_id}")],
            ])
            await msg.bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=admin_caption, parse_mode="Markdown", reply_markup=admin_kb)
        else:
            # document
            if msg.document:
                file_id = msg.document.file_id
                if lang == "en":
                    admin_caption = (
                        "🎵 🔔 NEW SELL ORDER (document)\n\n"
                        f"🆔 Order ID: `{order_id}`\n"
                        f"📅 Date: {date}\n"
                        f"👤 User: @{msg.from_user.username or msg.from_user.id}\n"
                        f"📤 Amount sent: ${amount:.2f}\n"
                        f"💸 Fee: ${fee:.2f}\n"
                        f"🎯 USDT we receive: {recv_usdt:.2f}\n"
                        f"💳 ETB to send: {total:.2f}\n\n"
                        "(See attached proof document)"
                    )
                else:
                    admin_caption = (
                        "🎵 🔔 አዲስ የUSDT ሽያጭ ትእዛዝ (ዶክመንት)\n\n"
                        f"🆔 የትእዛዝ መለያ: `{order_id}`\n"
                        f"📅 ቀን: {date}\n"
                        f"👤 ተጠቃሚ: @{msg.from_user.username or msg.from_user.id}\n"
                        f"📤 የተላከ መጠን: ${amount:.2f}\n"
                        f"💸 ክፍያ: ${fee:.2f}\n"
                        f"🎯 እኛ የምንቀበልዎት: {recv_usdt:.2f}\n"
                        f"💳 የሚከፈለው ብር: {total:.2f}\n\n"
                        "(የግብዣ ማስረጃ ዶክመንት ተያይዞ ነው)"
                    )
                admin_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Paid", callback_data=f"admin_sell_paid_{msg.from_user.id}_{order_id}"),
                     InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_sell_notpaid_{msg.from_user.id}_{order_id}")],
                ])
                await msg.bot.send_document(chat_id=ADMIN_ID, document=file_id, caption=admin_caption, parse_mode="Markdown", reply_markup=admin_kb)
            else:
                # fallback
                forwarded_msg = await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
                if lang == "en":
                    admin_caption = (
                        f"🔴 NEW SELL ORDER\nOrder ID: {order_id}\n(Proof forwarded above)"
                    )
                else:
                    admin_caption = (
                        f"🔴 አዲስ የUSDT ሽያጭ ትእዛዝ\n(Proof forwarded above)"
                    )
                admin_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Paid", callback_data=f"admin_sell_paid_{msg.from_user.id}_{order_id}"),
                     InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_sell_notpaid_{msg.from_user.id}_{order_id}")],
                ])
                await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_caption, reply_markup=admin_kb)

    except Exception as e:
        logger.exception("forward sell proof failed: %s", e)
        try:
            await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception:
            logger.exception("fallback forward failed")

    orders[order_id] = {
        "type": "sell",
        "user_id": msg.from_user.id,
        "username": msg.from_user.username or None,
        "amount": amount,
        "recv_usdt": recv_usdt,
        "fee": fee,
        "total": total,
        "lang": lang,
        "created_at": date,
        "bank_info": None,
        "bank_info_sent_at": None,
        "bank_type": None,
        "status": "pending"
    }

    # Send to tracker: order created
    try:
        send_to_tracker("order_created", {
            "service": "usdt",
            "subtype": "sell",
            "order_id": order_id,
            "user_id": msg.from_user.id,
            "username": msg.from_user.username,
            "amount": amount,
            "amount_usd": amount,
            "recv_usdt": recv_usdt,
            "fee_usd": fee,
            "etb": total,
            "total_etb": total,
            "status": "waiting_admin",
            "created_at": date
        })
    except Exception:
        logger.exception("Failed to send sell order to tracker")

    await msg.answer("⏳ Waiting for admin confirmation..." if lang == "en" else "⏳ ከአስተዳዳሪ ማረጋገጫ በመጠበቅ ላይ...")
    await state.clear()

# -------------------- Admin handlers for SELL --------------------
@router.callback_query(F.data.startswith("admin_sell_paid_"))
async def admin_sell_paid(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 5:
        await cb.answer("Invalid callback data.", show_alert=True)
        return
    user_id = int(parts[3])
    order_id = parts[4]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    order["status"] = "paid_by_admin"

    lang = order.get("lang", "en")
    try:
        if lang == "en":
            final_msg = (
                "✅ Admin confirmed your transfer. Choose how you want to receive ETB: CBE or Telebirr."
            )
        else:
            final_msg = (
                "✅ አስተዳዳሪው የሚከፈለውን ክፍያ አረጋግጧል። እባክዎ ክፍያዎትን በምን መቀበል ይፈልጋሉ ይምረጡ፦ CBE ወይም Telebirr."
            )
        await cb.bot.send_message(
            chat_id=user_id,
            text=final_msg,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏦 CBE", callback_data=f"seller_choose_bank_cbe_{order_id}")],
                [InlineKeyboardButton(text="📱 Telebirr", callback_data=f"seller_choose_bank_tele_{order_id}")]
            ])
        )
    except Exception as e:
        logger.exception("notify seller after admin_paid failed: %s", e)

    # Tracker: admin confirmed sell payment
    try:
        send_to_tracker("admin_confirmed_payment", {
            "service": "usdt",
            "subtype": "sell",
            "order_id": order_id,
            "admin_id": cb.from_user.id,
            "user_id": user_id,
            "time": now_str(),
            "status": "paid_by_admin"
        })
    except Exception:
        logger.exception("Failed to send admin_confirmed_payment (sell) to tracker")

    await cb.answer("Seller notified.", show_alert=False)

@router.callback_query(F.data.startswith("admin_sell_notpaid_"))
async def admin_sell_notpaid(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 5:
        await cb.answer("Invalid callback data.", show_alert=True)
        return
    user_id = int(parts[3])
    order_id = parts[4]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    lang = order.get("lang", "en")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back" if lang == "en" else "🔙 ተመለስ", callback_data=f"sell_usdt")],
        [InlineKeyboardButton(text="📞 Contact Support", url="https://t.me/plugmarketshop")]
    ])
    try:
        await cb.bot.send_message(chat_id=user_id,
                                  text=("❌ Payment not received. Please re-upload proof or contact support."
                                        if lang == "en"
                                        else "❌ ክፍያ አልተቀበለም። እባክዎ ማስረጃዎን ደግመው ያስገቡ ወይም ወደ ድጋፍ ይግቡ።"),
                                  reply_markup=kb)
    except Exception as e:
        logger.exception("notify seller notpaid failed: %s", e)

    # Tracker: admin marked sell not paid
    try:
        send_to_tracker("admin_marked_not_paid", {
            "service": "usdt",
            "subtype": "sell",
            "order_id": order_id,
            "admin_id": cb.from_user.id,
            "user_id": user_id,
            "time": now_str(),
            "status": "not_paid"
        })
    except Exception:
        logger.exception("Failed to send admin_marked_not_paid (sell) to tracker")

    await cb.answer("User notified (not paid).", show_alert=False)

# -------------------- Seller chooses payout bank and sends details --------------------
@router.callback_query(F.data.startswith("seller_choose_bank_"))
async def seller_choose_bank(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_")
    if len(parts) < 4:
        await cb.answer("Invalid callback data.", show_alert=True)
        return
    bank = parts[3]
    order_id = parts[4] if len(parts) > 4 else None
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found", show_alert=True)
        return

    await state.update_data(pending_order=order_id, chosen_bank=bank)
    await state.set_state(USDTStates.sell_wait_bank_details)
    lang = order.get("lang", "en")
    if bank == "cbe":
        await cb.message.answer("Please send your CBE account number and full name in one message." if lang == "en"
                                else "እባክዎ የCBE መለያ ቁጥር እና ሙሉ ስም በአንድ መልዕክት ይላኩ።")
    else:
        await cb.message.answer("Please send your Telebirr number and full name in one message." if lang == "en"
                                else "እባክዎ የTelebirr ቁጥር እና ሙሉ ስም በአንድ መልዕክት ይላኩ።")
    await cb.answer()

@router.message(USDTStates.sell_wait_bank_details, F.text)
async def seller_send_bank_details(msg: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("pending_order")
    bank_type = data.get("chosen_bank")
    order = orders.get(order_id)
    if not order:
        await msg.answer("Order not found or expired.")
        await state.clear()
        return

    bank_info = msg.text.strip()
    order["bank_type"] = bank_type
    order["bank_info"] = bank_info
    order["bank_info_sent_at"] = now_str()

    lang = order.get("lang", "en")
    if lang == "en":
        admin_text = (
            f"✅ SELL ORDER BANK INFO\n\n"
            f"🆔 Order ID: {order_id}\n"
            f"📅 Date: {order['bank_info_sent_at']}\n"
            f"👤 User: @{msg.from_user.username or msg.from_user.id}\n"
            f"💰 Amount: {order.get('amount')} USDT\n"
            f"💳 Total: {order.get('total')} ETB\n\n"
            f"Bank/Telebirr details provided by user:\n{bank_info}"
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Payment Completed", callback_data=f"payment_completed_{order_id}")],
            [InlineKeyboardButton(text="📋 Copy Bank Info", callback_data=f"copy_val:{bank_info}")],
        ])
    else:
        admin_text = (
            f"✅ የSELL ትእዛዝ የባንክ መረጃ\n\n"
            f"🆔 የትእዛዝ መለያ: {order_id}\n"
            f"📅 ቀን: {order['bank_info_sent_at']}\n"
            f"👤 ተጠቃሚ: @{msg.from_user.username or msg.from_user.id}\n"
            f"💰 መጠን: {order.get('amount')} USDT\n"
            f"💳 አጠቃላይ: {order.get('total')} ETB\n\n"
            f"🏦 የባንክ/Telebirr ዝርዝሮች ተሰጡ:\n{bank_info}"
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Payment Completed", callback_data=f"payment_completed_{order_id}")],
            [InlineKeyboardButton(text="📋 ኮፒ የባንክ መረጃ", callback_data=f"copy_val:{bank_info}")],
        ])

    await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="Markdown", reply_markup=admin_kb)

    # Tracker: seller provided bank details
    try:
        send_to_tracker("seller_bank_details", {
            "service": "usdt",
            "subtype": "sell",
            "order_id": order_id,
            "user_id": order.get("user_id"),
            "username": order.get("username"),
            "bank_type": bank_type,
            "bank_info": bank_info,
            "time": order.get("bank_info_sent_at"),
            "status": "bank_info_provided"
        })
    except Exception:
        logger.exception("Failed to send seller_bank_details to tracker")

    await msg.answer("✅ Bank details sent to admin. They will pay you shortly." if order.get("lang","en") == "en"
                     else "✅ የባንክ ዝርዝሮችዎ ወደ አስተዳዳሪ ተልኸዋል።")
    await state.clear()

# Keep old copy_bank_ handler for backwards compatibility
@router.callback_query(F.data.startswith("copy_bank_"))
async def copy_bank_cb(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return
    bank_info = order.get("bank_info")
    if not bank_info:
        await cb.answer("Bank info not found.", show_alert=True)
        return
    try:
        await cb.message.answer(f"`{bank_info}`", parse_mode="Markdown")
    except Exception:
        await cb.message.answer(bank_info)
    await cb.answer("Value shown (long-press to copy).")

# -------------------- Payment completed handler (applies for both buy & sell) --------------------
@router.callback_query(F.data.startswith("payment_completed_"))
async def payment_completed_by_admin(cb: CallbackQuery):
    parts = cb.data.split("_", 2)
    if len(parts) < 3:
        await cb.answer("Invalid callback data.", show_alert=True)
        return

    order_id = parts[2]
    order = orders.get(order_id)
    if not order:
        await cb.answer("Order not found.", show_alert=True)
        return

    user_id = order.get("user_id")
    lang = order.get("lang", "en")

    try:
        # Buy completed: USDT sent to wallet
        if order.get("type") == "buy":
            wallet = order.get("wallet", "unknown")
            if lang == "en":
                final_text = (
                    "🎉 Congratulations! The USDT you requested has been successfully sent.\n\n"
                    f"🔗 Wallet: `{wallet}`\n"
                    f"💰 Amount Sent: ${order.get('amount'):.2f}\n\n"
                    "Check your wallet balance! If you need payment proof or have any questions click Contact Support.\n\n"
                    "🙏 Thanks for trading with us!"
                )
            else:
                final_text = (
                    "🎉 እንኳን ደስ አለዎት! የUSDT የጠየቀው መጠን በተሳካ ሁኔታ ተልኳል።\n\n"
                    f"🔗 ዋሌት: `{wallet}`\n"
                    f"💰 የተላከው መጠን: ${order.get('amount'):.2f}\n\n"
                    "የዋሌትዎን ሂሳብ ይፈትሹ! የክፍያ ማረጋገጫ ወይም ጥያቄ ካለዎት የድጋፍ አገኙን ይጫኑ።\n\n"
                    "🙏 እናመሰግናለን!"
                )

        # Sell completed: ETB sent to bank_info
        else:
            etb_amount = order.get("total")
            bank_info = order.get("bank_info", "unknown")
            bank_type = order.get("bank_type", "account")
            if lang == "en":
                final_text = (
                    "🎉 Congratulations! Your ETB payout has been successfully sent.\n\n"
                    f"🏦 Payout method: {bank_type.upper()}\n"
                    f"🔗 Details: `{bank_info}`\n"
                    f"💰 Amount Sent: {etb_amount:.2f} ETB\n\n"
                    "Check your bank/Telebirr balance! If you need payment proof or have any questions click Contact Support.\n\n"
                    "🙏 Thanks for trading with us!"
                )
            else:
                final_text = (
                    "🎉 እንኳን ደስ አለዎት! የETB ክፍያዎ በተሳካ ሁኔታ ተልኳል።\n\n"
                    f"🏦 የክፍያ ዘዴ: {bank_type.upper()}\n"
                    f"🔗 ዝርዝሮች: `{bank_info}`\n"
                    f"💰 የተላከው: {etb_amount:.2f} ብር\n\n"
                    "የባንክ/Telebirr ሂሳብዎን ይፈትሹ! የክፍያ ማረጋገጫ ወይም ጥያቄ ካለዎት የድጋፍ አገኙን ይጫኑ።\n\n"
                    "🙏 እናመሰግናለን!"
                )
    except Exception as e:
        logger.exception("Payment completion failed: %s", e)
        final_text = "🎉 Completed. Contact support." if order.get("lang") == "en" else "🎉 ተጠናቀቀ። እባክዎ ወደ ድጋፍ ይግቡ።"

    # Build a keyboard that includes Contact Support and Join Channel
    support_txt = "📞 Contact Support" if lang == "en" else "📞 ድጋፍን አግኙ"
    join_txt = "🔔 Join Channel" if lang == "en" else "🔔 ለዜና ቻናል ይቀላቀሉ"
    final_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=support_txt, url="https://t.me/plugmarketshop")],
        [InlineKeyboardButton(text=join_txt, url=CHANNEL_LINK)]
    ])

    # Send final message to user plus join button
    try:
        await cb.bot.send_message(chat_id=user_id, text=final_text, parse_mode="Markdown", reply_markup=final_kb)
    except Exception as e:
        logger.exception("Failed to send final message to user: %s", e)

    # Tracker: order completed
    try:
        send_to_tracker("order_completed", {
            "service": "usdt",
            "subtype": order.get("type"),
            "order_id": order_id,
            "user_id": order.get("user_id"),
            "username": order.get("username"),
            "amount": order.get("amount"),
            "amount_usd": order.get("amount"),
            "total_etb": order.get("total"),
            "etb": order.get("total"),
            "payment_method": order.get("payment_method"),
            "completed_by": cb.from_user.id,
            "completed_at": now_str(),
            "status": "completed"
        })
    except Exception:
        logger.exception("Failed to send order_completed to tracker")

    # Remove order and notify admin (small notification)
    orders.pop(order_id, None)

    # Notify admin that order was completed (small notification)
    try:
        admin_notify_text = f"✅ Order `{order_id}` marked completed by @{cb.from_user.username or cb.from_user.id}."
        await cb.bot.send_message(chat_id=ADMIN_ID, text=admin_notify_text, parse_mode="Markdown")
    except Exception:
        pass

    await cb.answer("User notified (completed).", show_alert=False)

# Backwards-compatible simple copy_address fallback (kept for older keyboards if any)
@router.callback_query(F.data == "copy_address")
async def copy_address_cb(cb: CallbackQuery):
    try:
        await cb.message.answer(f"`{USDT_WALLET}`", parse_mode="Markdown")
    except Exception:
        await cb.message.answer(USDT_WALLET)
    await cb.answer("Address shown (long-press to copy).")
