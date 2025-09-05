# telegram_premium.py  -- enhanced (added copy buttons, admin notifications, join channel, better i18n/admin flows)
import time
import logging
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, ContentType
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

router = Router()
logger = logging.getLogger(__name__)

# -------------------- Config / Constants --------------------
ADMIN_ID = 6968325481

CBE_ACCOUNT = "1000476183921"
TELEBIRR_ACCOUNT = "0916253200"
ACCOUNT_NAME = "Aschalew Desta"

PACKAGES = {
    "3m": {"en": "3 Month", "am": "3 ወር", "price": 2499},
    "6m": {"en": "6 Month", "am": "6 ወር", "price": 3199},
    "1y": {"en": "1 Year", "am": "1 ዓመት", "price": 5199},
}

ORDERS_FILE = "premium_orders.json"
ARCHIVE_FILE = "premium_orders_archive.json"

orders: Dict[str, Dict[str, Any]] = {}
archived_orders: Dict[str, Dict[str, Any]] = {}

# Try to import tracker (same project). We'll use record_order/record_event if available.
try:
    import tracker
except Exception:
    tracker = None


def track(event: str, payload: Optional[Dict] = None):
    """
    Generic tracking fallback that uses tracker's record_event or record_order when available.
    Backwards-compatible with previously attempted tracker APIs.
    """
    try:
        if not tracker:
            return
        # Prefer record_event for events
        if hasattr(tracker, "record_event"):
            try:
                tracker.record_event(event, payload or {})
                return
            except Exception:
                # fallthrough to other possible apis
                pass
        # If only record_order exists and payload looks like an order, use it
        if hasattr(tracker, "record_order") and isinstance(payload, dict):
            try:
                # If payload already contains 'service', use it; else use 'premium'
                svc = payload.get("service") if isinstance(payload, dict) and payload.get("service") else "premium"
                tracker.record_order(svc, payload)
                return
            except Exception:
                pass
        # Legacy: try tracker.track or tracker.increment if present (best-effort)
        if hasattr(tracker, "track"):
            try:
                tracker.track("premium", event, payload or {})
                return
            except Exception:
                pass
        if hasattr(tracker, "increment"):
            try:
                tracker.increment("premium")
                return
            except Exception:
                pass
    except Exception:
        # swallow tracking errors
        return


# -------------------- Persistence helpers --------------------
def load_orders() -> None:
    global orders
    try:
        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
                if isinstance(data, dict):
                    orders.update(data)
                else:
                    orders.clear()
        else:
            orders.clear()
    except Exception:
        logger.exception("Failed to load orders file; starting with empty orders.")
        orders.clear()


def save_orders() -> None:
    try:
        with open(ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(orders, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to save orders to file.")


def load_archived_orders() -> None:
    global archived_orders
    try:
        if os.path.exists(ARCHIVE_FILE):
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
                if isinstance(data, dict):
                    archived_orders.update(data)
                else:
                    archived_orders.clear()
        else:
            archived_orders.clear()
    except Exception:
        logger.exception("Failed to load archive file; starting with empty archive.")
        archived_orders.clear()


def save_archived_orders() -> None:
    try:
        with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(archived_orders, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to save archived orders to file.")


load_orders()
load_archived_orders()

# -------------------- FSM States --------------------
class PremiumStates(StatesGroup):
    wait_proof = State()
    wait_username = State()


# -------------------- Helpers --------------------
def gen_order_id() -> str:
    return str(int(time.time() * 1000))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_amharic_text(text: Optional[str]) -> bool:
    if not text:
        return False
    return any(ch in text for ch in ["አ", "ኡ", "ኢ", "ዕ", "የ", "ብር", "እባክ"])


def ensure_lang_from_state_data(d: dict) -> str:
    return d.get("lang", "en")


def contact_support_button(lang="en") -> InlineKeyboardMarkup:
    txt = "📞 Contact Support" if lang == "en" else "📞 ድጋፊ አግኙ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=txt, url="https://t.me/plugmarketshop")]
    ])


def kb_back_to_services(lang: str) -> InlineKeyboardMarkup:
    txt = "🔙 Back" if lang == "en" else "🔙 ተመለስ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=txt, callback_data=f"services_{lang}")]
    ])


def t(lang: str, key: str) -> str:
    EN = {
        "entry_title": "🎉 20% OFF — Choose your plan:",
        "pkg_3m": "3 Month",
        "pkg_6m": "6 Month",
        "pkg_1y": "1 Year",
        "back": "🔙 Back",
        "choose_payment": "💳 Price: {price} ETB\n\nPlease choose a payment method:",
        "method_cbe": "🏦 CBE",
        "method_tele": "📱 Telebirr",
        "details_cbe": "🏦 Bank: Commercial Bank of Ethiopia\n📄 Name: {name}\n💳 Account: {acc}",
        "details_tele": "📱 Telebirr Number: {acc}\n📄 Name: {name}",
        "after_details": "Please send the total amount to the selected account. Once paid, click '✅ Done'.",
        "done": "✅ Done",
        "cancel": "❌ Cancel",
        "ask_proof": "📸 Please upload your payment proof (screenshot/photo).",
        "cancelled": "❌ Your order has been cancelled.",
        "waiting_admin": "⏳ Waiting for admin confirmation...",
        "admin_new": "🌟 NEW TELEGRAM PREMIUM ORDER\nOrder ID: {oid}\nDate: {date}\nBuyer: @{username}\n\nPackage: {pkg}\nPrice: {price} ETB\nMethod: {method}\n\n(Payment proof forwarded above)",
        "admin_btn_paid": "✅ Paid",
        "admin_btn_notpaid": "❌ Not Paid",
        "user_notpaid": "⚠️ Payment not received. Please pay again and re-upload your proof, or contact support.",
        "ask_username": "Please send your Telegram username (e.g., @yourname).",
        "enter_username_btn": "Send Username",
        "username_saved": "Thanks! Your username has been received and sent to the admin.",
        "admin_username": "👤 USERNAME RECEIVED\nOrder ID: {oid}\nUser: @{username}\nPremium for: {pkg}\nTarget username: {target}\n\n(Click when completed)",
        "admin_btn_completed": "✅ Order Complete",
        "final_user": ("🎉 Congratulations! Your Telegram account is now Premium for: {pkg}\n"
                       "✅ Your package has been successfully sent to: {target}\n"
                       "🏅 Check your Telegram verification badge!\n"
                       "💬 If you have any questions or need proof, click 'Contact Support'.\n"
                       "🙏 Thanks for trading with us!"),
        "choose_plan_hint": "🎉 20% OFF — Choose your plan:",
        "admin_completed_confirm": "✅ Order {oid} completed — {pkg} applied to {target}.",
        "admin_btn_copy_price": "📋 Copy Price",
        "admin_btn_copy_username": "📋 Copy Username",
        "admin_btn_copy_account": "📋 Copy Account",
        "order_not_found": "Order not found",
    }
    AM = {
        "entry_title": "🎉 20% ቅናሽ — የምፈልጉትን ይምረጡ፦",
        "pkg_3m": "3 ወር",
        "pkg_6m": "6 ወር",
        "pkg_1y": "1 ዓመት",
        "back": "🔙 ተመለስ",
        "choose_payment": "💳 ዋጋ: {price} ብር\n\nእባክዎ የክፍያ መንገድ ይምረጡ፦",
        "method_cbe": "🏦 CBE",
        "method_tele": "📱 ቴሌብር",
        "details_cbe": "🏦 ባንክ፦ Commercial Bank of Ethiopia\n📄 ስም፦ {name}\n💳 መለያ፦ {acc}",
        "details_tele": "📱 ቴሌብር ቁጥር፦ {acc}\n📄 ስም፦ {name}",
        "after_details": "እባክዎ የተመረጠው መለያ ላይ ድምሩን ይላኩ። ከተከፈለ በኋላ '✅ ተጠናቋል' ይጫኑ።",
        "done": "✅ ተጠናቋል",
        "cancel": "❌ ሰርዝ",
        "ask_proof": "📸 የክፍያ ማስረጃ ፎቶ/ስክሪንሾት ያስገቡ።",
        "cancelled": "❌ ትእዛዙ ተሰርዟል።",
        "waiting_admin": "⏳ ከአስተዳዳሪ ማረጋገጫ በመጠበቅ ላይ...",
        "admin_new": "🌟 የTELEGRAM PREMIUM ትእዛዝ አዲስ\nOrder ID: {oid}\nቀን: {date}\nገዢ: @{username}\n\nፓኬጅ: {pkg}\nዋጋ: {price} ብር\nመንገድ: {method}\n\n(የክፍያ ማስረጃ ከላይ ተላክ)",
        "admin_btn_paid": "✅ ተከፍሏል",
        "admin_btn_notpaid": "❌ ክፍያ አልተቀበለም",
        "user_notpaid": "⚠️ ክፍያ አልተቀበለም። እባክዎ ዳግመው ይክፈሉ እና ማስረጃ ያስገቡ ወይም ድጋፍን ያግኙን ይጫኑ።",
        "ask_username": "እባክዎ የቴሌግራም ዩዘርኔም ይላኩ (ምሳሌ፦ @yourname).",
        "enter_username_btn": "ዩዘርኔም ይላኩ",
        "username_saved": "አመሰግናለሁ! ዩዘርኔም ተቀብሏል እና ለአስተዳዳሪ ተልኳል።",
        "admin_username": "👤 የዩዘርኔም ተቀብሏል\nOrder ID: {oid}\nተጠቃሚ: @{username}\nፕሪሚየም ለ፡ {pkg}\nየመቀበያ ዩዘርኔም: {target}\n\n(ተጠናቆ ሲሆን ይጫኑ)",
        "admin_btn_completed": "✅ ተጠናቋል",
        "final_user": ("🎉 እንኳን ደስ አለዎት! የቴሌግራም አካውንትዎ አሁን Premium ነው ለ፡ {pkg}\n"
                       "✅ ፓኬጅዎ ተልኳል ለ፡ {target}\n"
                       "🏅 የማረጋገጫ ባጅዎን/ Verification Badge ይመልከቱ!\n"
                       "💬 ጥያቄ ካለ ወይም ማስረጃ ከፈለጉ 'ድጋፍን አግኙ' ይጫኑ።\n"
                       "🙏 ከእኛ ስላዘዙ እናመሰግናለን!"),
        "choose_plan_hint": "🎉 20% ቅናሽ — የምፈልጉትን ይምረጡ፦",
        "admin_completed_confirm": "✅ Order {oid} completed — {pkg} applied to {target}.",
        "admin_btn_copy_price": "📋 ዋጋ ኮፒ",
        "admin_btn_copy_username": "📋 ዩዘርኔም ኮፒ",
        "admin_btn_copy_account": "📋 መለያ ኮፒ",
        "order_not_found": "ትእዛዙ አልተገኘም",
    }
    base = EN if lang == "en" else AM
    return base.get(key, key)


# -------------------- Utility: check active order or notify "Order not found" ----------
async def get_active_order_or_notify(cb: CallbackQuery, order_id: str) -> Optional[dict]:
    """
    Returns order dict if active (in orders). If not found (including archived), notify user/admin via alert.
    This enforces "Order not found" after completion/archiving.
    """
    order = orders.get(order_id)
    if not order:
        # If archived, treat as not found (per requirement)
        lang = "am" if (cb.from_user and getattr(cb.from_user, "language_code", "") == "am") else "en"
        try:
            await cb.answer(t(lang, "order_not_found"), show_alert=True)
        except Exception:
            try:
                await cb.bot.send_message(chat_id=cb.from_user.id if cb.from_user else None, text=t(lang, "order_not_found"))
            except Exception:
                pass
        return None
    return order


# -------------------- Entry Points --------------------
@router.callback_query(F.data.in_({"telegram_menu_en", "telegram_menu_am", "service_telegram_premium"}))
async def open_telegram_premium_menu(cb: CallbackQuery, state: FSMContext):
    if cb.data.endswith("_am"):
        lang = "am"
    elif cb.data.endswith("_en"):
        lang = "en"
    else:
        d = await state.get_data()
        lang = d.get("lang", "en")

    await state.clear()
    await state.update_data(lang=lang)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(lang, "pkg_3m"), callback_data="premium_pkg_3m"),
            InlineKeyboardButton(text=t(lang, "pkg_6m"), callback_data="premium_pkg_6m"),
            InlineKeyboardButton(text=t(lang, "pkg_1y"), callback_data="premium_pkg_1y"),
        ],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"services_{lang}")]
    ])
    try:
        await cb.message.edit_text(t(lang, "entry_title"), reply_markup=kb)
    except Exception:
        await cb.message.answer(t(lang, "entry_title"), reply_markup=kb)
    await cb.answer()


@router.message(F.text.in_(["Get Telegram Premium", "Telegram Premium ይውሰዱ"]))
async def premium_entry_text(msg: Message, state: FSMContext):
    lang = "am" if is_amharic_text(msg.text) else "en"
    await state.clear()
    await state.update_data(lang=lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(lang, "pkg_3m"), callback_data="premium_pkg_3m"),
            InlineKeyboardButton(text=t(lang, "pkg_6m"), callback_data="premium_pkg_6m"),
            InlineKeyboardButton(text=t(lang, "pkg_1y"), callback_data="premium_pkg_1y"),
        ],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"services_{lang}")]
    ])
    await msg.answer(t(lang, "choose_plan_hint"), reply_markup=kb)


# -------------------- Package selection and flow --------------------
@router.callback_query(F.data.startswith("premium_pkg_"))
async def premium_package_selected(cb: CallbackQuery, state: FSMContext):
    pkg_code = cb.data.split("_")[-1]
    d = await state.get_data()
    lang = ensure_lang_from_state_data(d)
    if pkg_code not in PACKAGES:
        await cb.answer("Invalid package", show_alert=True)
        return

    price = PACKAGES[pkg_code]["price"]
    order_id = gen_order_id()
    orders[order_id] = {
        "order_id": order_id,
        "user_id": cb.from_user.id,
        "username": cb.from_user.username or str(cb.from_user.id),
        "package": PACKAGES[pkg_code]["en"] if lang == "en" else PACKAGES[pkg_code]["am"],
        "package_code": pkg_code,
        "price_etb": price,
        "lang": lang,
        "status": "package_selected",
        "created_at": now_str(),
        "payment_method": None,
        "payment_proof_msg_id": None,
        "payment_proof": None,
        "target_username": None,
        "admin_handled_by": None,
    }
    save_orders()
    await state.update_data(premium_order_id=order_id, lang=lang)

    # Record to tracker (if available) as an order creation / package selected event
    try:
        if tracker and hasattr(tracker, "record_order"):
            try:
                tracker.record_order("premium", {
                    "order_id": order_id,
                    "user_id": cb.from_user.id,
                    "username": cb.from_user.username or "",
                    "amount": 1,
                    "currency": "PREMIUM",
                    "total_etb": price,
                    "etb": price,
                    "status": "package_selected",
                    "created_at": datetime.utcnow()
                })
            except Exception:
                # fallback to record_event
                try:
                    if hasattr(tracker, "record_event"):
                        tracker.record_event("order_created", {
                            "service": "premium",
                            "order_id": order_id,
                            "user_id": cb.from_user.id,
                            "username": cb.from_user.username or "",
                            "amount": 1,
                            "currency": "PREMIUM",
                            "total_etb": price,
                            "status": "package_selected",
                            "created_at": datetime.utcnow()
                        })
                except Exception:
                    pass
        elif tracker and hasattr(tracker, "record_event"):
            tracker.record_event("order_created", {
                "service": "premium",
                "order_id": order_id,
                "user_id": cb.from_user.id,
                "username": cb.from_user.username or "",
                "amount": 1,
                "currency": "PREMIUM",
                "total_etb": price,
                "status": "package_selected",
                "created_at": datetime.utcnow()
            })
    except Exception:
        pass

    txt = t(lang, "choose_payment").format(price=price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(lang, "method_cbe"), callback_data=f"premium_method_cbe_{order_id}"),
            InlineKeyboardButton(text=t(lang, "method_tele"), callback_data=f"premium_method_tele_{order_id}")
        ],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="telegram_menu_en" if lang == "en" else "telegram_menu_am")],
    ])
    try:
        await cb.message.edit_text(txt, reply_markup=kb)
    except Exception:
        await cb.message.answer(txt, reply_markup=kb)
    await cb.answer()
    track("package_selected", {"order_id": order_id, "pkg": orders[order_id]["package"], "price": price})


@router.callback_query(F.data.startswith("premium_method_"))
async def premium_method_selected(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_")
    method_code = parts[2]
    order_id = parts[3] if len(parts) > 3 else None
    if not order_id or order_id not in orders:
        await cb.answer(t("en", "order_not_found"), show_alert=True)
        return

    order = orders[order_id]
    lang = order.get("lang", "en")

    if method_code == "cbe":
        order["payment_method"] = "CBE"
        details = t(lang, "details_cbe").format(name=ACCOUNT_NAME, acc=CBE_ACCOUNT)
        account_to_copy = CBE_ACCOUNT
    else:
        order["payment_method"] = "Telebirr"
        details = t(lang, "details_tele").format(name=ACCOUNT_NAME, acc=TELEBIRR_ACCOUNT)
        account_to_copy = TELEBIRR_ACCOUNT

    order["status"] = "method_selected"
    save_orders()

    body = f"{details}\n\n{t(lang, 'after_details')}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "done"), callback_data=f"premium_done_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"premium_back_to_pay_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "cancel"), callback_data=f"premium_cancel_{order_id}")],
        # copy account for long-press convenience
        [InlineKeyboardButton(text=t(lang, "admin_btn_copy_account"), callback_data=f"premium_copy_account_{order_id}")],
    ])
    try:
        await cb.message.edit_text(body, reply_markup=kb)
    except Exception:
        await cb.message.answer(body, reply_markup=kb)

    try:
        code_block = f"Account: `{account_to_copy}`\nPrice: `{order.get('price_etb')}`"
        await cb.bot.send_message(chat_id=cb.from_user.id, text=code_block, parse_mode="Markdown")
    except Exception:
        logger.exception("premium: failed to send account code block")

    await cb.answer()
    track("method_selected", {"order_id": order_id, "method": order["payment_method"]})


@router.callback_query(F.data.startswith("premium_back_to_pay_"))
async def premium_back_to_pay(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer(t("en", "order_not_found"), show_alert=True)
        return
    lang = order.get("lang", "en")
    price = order.get("price_etb")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(lang, "method_cbe"), callback_data=f"premium_method_cbe_{order_id}"),
            InlineKeyboardButton(text=t(lang, "method_tele"), callback_data=f"premium_method_tele_{order_id}")
        ],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="telegram_menu_en" if lang == "en" else "telegram_menu_am")],
    ])
    try:
        await cb.message.edit_text(t(lang, "choose_payment").format(price=price), reply_markup=kb)
    except Exception:
        await cb.message.answer(t(lang, "choose_payment").format(price=price), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("premium_cancel_"))
async def premium_cancel(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    lang = order.get("lang", "en") if order else "en"
    if order:
        order["status"] = "cancelled"
        save_orders()
    try:
        await cb.message.edit_text(t(lang, "cancelled"), reply_markup=kb_back_to_services(lang))
    except Exception:
        await cb.message.answer(t(lang, "cancelled"), reply_markup=kb_back_to_services(lang))
    await cb.answer()
    # track cancellation with tracker if available
    try:
        track("cancelled", {"order_id": order_id})
        if tracker and hasattr(tracker, "record_event"):
            tracker.record_event("order_cancelled", {
                "service": "premium",
                "order_id": order_id,
                "user_id": order.get("user_id") if order else None,
                "username": order.get("username") if order else "",
                "status": "cancelled",
                "time": datetime.utcnow()
            })
    except Exception:
        pass


@router.callback_query(F.data.startswith("premium_done_"))
async def premium_done(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer(t("en", "order_not_found"), show_alert=True)
        return
    lang = order.get("lang", "en")
    order["status"] = "awaiting_proof"
    save_orders()

    await state.update_data(premium_order_id=order_id, lang=lang)
    await state.set_state(PremiumStates.wait_proof)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"premium_back_to_details_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "cancel"), callback_data=f"premium_cancel_{order_id}")],
    ])
    try:
        await cb.message.edit_text(t(lang, "ask_proof"), reply_markup=kb)
    except Exception:
        await cb.message.answer(t(lang, "ask_proof"), reply_markup=kb)
    await cb.answer()
    track("awaiting_proof", {"order_id": order_id})


@router.callback_query(F.data.startswith("premium_back_to_details_"))
async def premium_back_to_details(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        await cb.answer(t("en", "order_not_found"), show_alert=True)
        return
    lang = order.get("lang", "en")
    method = order.get("payment_method")
    if method == "CBE":
        details = t(lang, "details_cbe").format(name=ACCOUNT_NAME, acc=CBE_ACCOUNT)
        account_to_copy = CBE_ACCOUNT
    else:
        details = t(lang, "details_tele").format(name=ACCOUNT_NAME, acc=TELEBIRR_ACCOUNT)
        account_to_copy = TELEBIRR_ACCOUNT

    body = f"{details}\n\n{t(lang, 'after_details')}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "done"), callback_data=f"premium_done_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"premium_back_to_pay_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "cancel"), callback_data=f"premium_cancel_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "admin_btn_copy_account"), callback_data=f"premium_copy_account_{order_id}")],
    ])
    try:
        await cb.message.edit_text(body, reply_markup=kb)
    except Exception:
        await cb.message.answer(body, reply_markup=kb)

    try:
        code_block = f"Account: `{account_to_copy}`\nPrice: `{order.get('price_etb')}`"
        await cb.bot.send_message(chat_id=cb.from_user.id, text=code_block, parse_mode="Markdown")
    except Exception:
        logger.exception("premium: failed to send account code block on back_to_details")
    await cb.answer()


# -------------------- Receive Payment Proof handlers (RESTRICTED) --------------------
# Important: proof handlers now only accept PHOTO/DOCUMENT (not TEXT). This prevents hijacking text inputs
# from other services (amounts, product names, etc.).
@router.message(PremiumStates.wait_proof, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def premium_receive_proof_state(msg: Message, state: FSMContext):
    d = await state.get_data()
    order_id = d.get("premium_order_id")
    if not order_id:
        await state.clear()
        try:
            lang = d.get("lang", "en")
            await msg.answer("Internal: no order associated. Please start again.", reply_markup=kb_back_to_services(lang))
        except Exception:
            pass
        return
    await _process_premium_proof(msg, order_id)
    await state.clear()


@router.message(
    # Guarded: match only when the user has an awaiting_proof order and message is photo/document.
    lambda message, *args, **kwargs: any(
        o.get("user_id") == (message.from_user.id if message.from_user else None)
        and o.get("status") == "awaiting_proof"
        for o in orders.values()
    ),
    F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT})
)
async def premium_receive_proof_global(msg: Message, state: FSMContext):
    # find the candidate order for this user (most recent first)
    candidate_order_id = None
    for oid, o in sorted(orders.items(), key=lambda kv: kv[0], reverse=True):
        if o.get("user_id") == msg.from_user.id and o.get("status") == "awaiting_proof":
            candidate_order_id = oid
            break
    if not candidate_order_id:
        return

    await _process_premium_proof(msg, candidate_order_id)
    try:
        await state.clear()
    except Exception:
        pass


async def _process_premium_proof(msg: Message, order_id: str):
    order = orders.get(order_id)
    if not order:
        try:
            await msg.answer(t("en", "order_not_found"), reply_markup=kb_back_to_services("en"))
        except Exception:
            pass
        return

    lang = order.get("lang", "en")

    forwarded = None
    try:
        forwarded = await msg.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
        if forwarded:
            order["payment_proof_msg_id"] = forwarded.message_id
    except Exception:
        try:
            if getattr(msg, "photo", None):
                forwarded = await msg.bot.send_photo(chat_id=ADMIN_ID, photo=msg.photo[-1].file_id)
                if forwarded:
                    order["payment_proof_msg_id"] = forwarded.message_id
            elif getattr(msg, "document", None):
                forwarded = await msg.bot.send_document(chat_id=ADMIN_ID, document=msg.document.file_id)
                if forwarded:
                    order["payment_proof_msg_id"] = forwarded.message_id
            else:
                forwarded = await msg.bot.send_message(chat_id=ADMIN_ID, text=(msg.text or ""))
                if forwarded:
                    order["payment_proof_msg_id"] = forwarded.message_id
        except Exception:
            logger.exception("premium: fallback send proof to admin failed")

    order["status"] = "proof_received"
    order["proof_received_at"] = now_str()
    order["payment_proof"] = {
        "type": "photo" if getattr(msg, "photo", None) else ("document" if getattr(msg, "document", None) else "text"),
        "raw_text": (msg.text or "") if not (getattr(msg, "photo", None) or getattr(msg, "document", None)) else None
    }
    save_orders()

    # Record to tracker: update/create order record / event for proof_received
    try:
        if tracker and hasattr(tracker, "record_event"):
            tracker.record_event("order_created", {
                "service": "premium",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": 1,
                "currency": "PREMIUM",
                "total_etb": order.get("price_etb"),
                "payment_method": order.get("payment_method"),
                "status": "waiting_admin",
                "created_at": order.get("created_at") or datetime.utcnow()
            })
        elif tracker and hasattr(tracker, "record_order"):
            tracker.record_order("premium", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": 1,
                "currency": "PREMIUM",
                "total_etb": order.get("price_etb"),
                "payment_method": order.get("payment_method"),
                "status": "waiting_admin",
                "created_at": datetime.utcnow()
            })
    except Exception:
        pass

    # Build admin message with clear professional icons and details (language chosen by user)
    admin_text = t(lang, "admin_new").format(
        oid=order_id,
        date=order["proof_received_at"],
        username=order.get("username"),
        pkg=order.get("package"),
        price=order.get("price_etb"),
        method=order.get("payment_method") or "N/A",
    )
    # Admin keyboard with copy actions included
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(lang, "admin_btn_paid"), callback_data=f"premium_admin_paid_{order_id}"),
            InlineKeyboardButton(text=t(lang, "admin_btn_notpaid"), callback_data=f"premium_admin_notpaid_{order_id}")
        ],
        [
            InlineKeyboardButton(text=t(lang, "admin_btn_copy_price"), callback_data=f"premium_admin_copy_price_{order_id}"),
            InlineKeyboardButton(text=t(lang, "admin_btn_copy_username"), callback_data=f"premium_admin_copy_username_{order_id}"),
            InlineKeyboardButton(text=t(lang, "admin_btn_copy_account"), callback_data=f"premium_admin_copy_account_{order_id}")
        ]
    ])
    try:
        # send admin overview (proof forwarded above will show image)
        await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=admin_kb)
        # explicit code block for long-press convenience: price, account, buyer
        account_info = CBE_ACCOUNT if order.get("payment_method") == "CBE" else TELEBIRR_ACCOUNT
        code_block = f"Order ID: `{order_id}`\nPrice: `{order.get('price_etb')} ETB`\nBuyer: `@{order.get('username')}`\nAccount: `{account_info}`"
        await msg.bot.send_message(chat_id=ADMIN_ID, text=code_block, parse_mode="Markdown")
    except Exception:
        logger.exception("premium: send admin payment summary failed")

    try:
        await msg.answer(t(lang, "waiting_admin"), reply_markup=kb_back_to_services(lang))
    except Exception:
        pass

    track("proof_received", {"order_id": order_id})


# -------------------- Admin: Not Paid / Paid --------------------
@router.callback_query(F.data.startswith("premium_admin_notpaid_"))
async def premium_admin_notpaid(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = await get_active_order_or_notify(cb, order_id)
    if not order:
        return
    lang = order.get("lang", "en")
    order["status"] = "not_paid"
    save_orders()
    try:
        await cb.bot.send_message(
            chat_id=order.get("user_id"),
            text=t(lang, "user_notpaid"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"services_{lang}" )],
                [InlineKeyboardButton(text="📞 Contact Support" if lang == "en" else "📞 ድጋፊ አግኙ", url="https://t.me/plugmarketshop")]
            ])
        )
    except Exception:
        logger.exception("premium: notify user not paid failed")
    await cb.answer("User notified (Not Paid).", show_alert=False)
    track("not_paid", {"order_id": order_id})
    # record to tracker as not_paid
    try:
        if tracker and hasattr(tracker, "record_event"):
            tracker.record_event("not_paid", {
                "service": "premium",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "total_etb": order.get("price_etb"),
                "status": "not_paid",
                "time": datetime.utcnow()
            })
    except Exception:
        pass


@router.callback_query(F.data.startswith("premium_admin_paid_"))
async def premium_admin_paid(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split("_")[-1]
    order = await get_active_order_or_notify(cb, order_id)
    if not order:
        return
    order["status"] = "admin_paid"
    order["admin_handled_by"] = cb.from_user.id if cb.from_user else None
    save_orders()
    lang = order.get("lang", "en")

    # Record to tracker: admin confirmed payment (mark as paid)
    try:
        if tracker and hasattr(tracker, "record_event"):
            tracker.record_event("admin_confirmed_payment", {
                "service": "premium",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "total_etb": order.get("price_etb"),
                "payment_method": order.get("payment_method"),
                "status": "paid",
                "time": datetime.utcnow()
            })
        elif tracker and hasattr(tracker, "record_order"):
            tracker.record_order("premium", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": 1,
                "currency": "PREMIUM",
                "total_etb": order.get("price_etb"),
                "payment_method": order.get("payment_method"),
                "status": "paid",
                "created_at": order.get("created_at") or datetime.utcnow(),
                "completed_at": None
            })
    except Exception:
        pass

    # Include payment method in the message to the user so they always know which method they selected
    method_label = order.get("payment_method") or ""
    ask_text = t(lang, "ask_username")
    if method_label:
        ask_text = f"{ask_text}\n\nPayment method: {method_label}"

    try:
        kb_user = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "enter_username_btn"), callback_data=f"premium_enter_username_{order_id}")],
            [InlineKeyboardButton(text=t(lang, "back"), callback_data=f"services_{lang}")],
        ])
        await cb.bot.send_message(chat_id=order.get("user_id"), text=ask_text, reply_markup=kb_user)
    except Exception:
        logger.exception("premium: ask user username failed")

    await cb.answer("Asked user for Telegram username.", show_alert=False)
    track("admin_paid_marked", {"order_id": order_id})


# -------------------- User clicks 'Send Username' button -> set FSM in user's chat --------------------
@router.callback_query(F.data.startswith("premium_enter_username_"))
async def premium_enter_username_cb(cb: CallbackQuery, state: FSMContext):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        try:
            await cb.answer(t("en", "order_not_found"), show_alert=True)
        except Exception:
            pass
        return

    lang = order.get("lang", "en")
    try:
        await state.update_data(premium_order_id=order_id, lang=lang)
        await state.set_state(PremiumStates.wait_username)
        await cb.message.answer(t(lang, "ask_username"), reply_markup=kb_back_to_services(lang))
        await cb.answer()
        logger.info("Set wait_username FSM for user %s (order %s)", cb.from_user.id, order_id)
    except Exception:
        logger.exception("premium: failed to set username FSM for user")
        try:
            await cb.answer("Failed to prepare username flow. Please type your username now.", show_alert=True)
        except Exception:
            pass


# -------------------- USER USERNAME HANDLERS --------------------
@router.message(PremiumStates.wait_username, F.text)
async def premium_user_send_username(msg: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("premium_order_id")
    order = orders.get(order_id) if order_id else None

    if not order:
        # fallback: find admin_paid order for this user
        for oid, o in sorted(orders.items(), key=lambda kv: kv[0], reverse=True):
            if o.get("user_id") == msg.from_user.id and o.get("status") == "admin_paid":
                order = o
                order_id = oid
                break

    if not order:
        try:
            lang = data.get("lang", "en")
            await msg.answer(t(lang, "order_not_found"), reply_markup=kb_back_to_services(lang))
        except Exception:
            pass
        await state.clear()
        return

    lang = order.get("lang", "en")
    target_username = msg.text.strip()

    order["target_username"] = target_username
    order["status"] = "username_received"
    save_orders()
    logger.info("User %s submitted username %s for order %s", msg.from_user.id, target_username, order_id)

    try:
        await msg.answer(t(lang, "username_saved"), reply_markup=kb_back_to_services(lang))
    except Exception:
        pass

    admin_text = t(lang, "admin_username").format(
        oid=order_id,
        username=order.get("username"),
        pkg=order.get("package"),
        target=target_username
    )
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "admin_btn_copy_price"), callback_data=f"premium_admin_copy_price_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "admin_btn_copy_username"), callback_data=f"premium_admin_copy_username_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "admin_btn_copy_account"), callback_data=f"premium_admin_copy_account_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "admin_btn_completed"), callback_data=f"premium_admin_completed_{order_id}")]
    ])

    admin_chat_target = order.get("admin_handled_by") or ADMIN_ID
    sent_to_admin = False
    try:
        # Forward nicely and provide code block for copying
        await msg.bot.send_message(chat_id=admin_chat_target, text=admin_text, reply_markup=admin_kb)
        account_info = CBE_ACCOUNT if order.get("payment_method") == "CBE" else TELEBIRR_ACCOUNT
        code_block = f"Target username: `{target_username}`\nPackage: `{order.get('package')}`\nOrder ID: `{order_id}`\nPrice: `{order.get('price_etb')} ETB`\nAccount: `{account_info}`"
        await msg.bot.send_message(chat_id=admin_chat_target, text=code_block, parse_mode="Markdown")
        sent_to_admin = True
        logger.info("Forwarded username for order %s to admin %s", order_id, admin_chat_target)
    except Exception:
        logger.exception("premium: forward to admin failed (primary). Will try fallback ADMIN_ID.")
        if admin_chat_target != ADMIN_ID:
            try:
                await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=admin_kb)
                account_info = CBE_ACCOUNT if order.get("payment_method") == "CBE" else TELEBIRR_ACCOUNT
                code_block = f"Target username: `{target_username}`\nPackage: `{order.get('package')}`\nOrder ID: `{order_id}`\nPrice: `{order.get('price_etb')} ETB`\nAccount: `{account_info}`"
                await msg.bot.send_message(chat_id=ADMIN_ID, text=code_block, parse_mode="Markdown")
                sent_to_admin = True
                logger.info("Forwarded username for order %s to fallback admin %s", order_id, ADMIN_ID)
            except Exception:
                logger.exception("premium: fallback forward to ADMIN_ID also failed")

    if not sent_to_admin:
        try:
            await msg.answer("We received your username but failed to deliver it to the admin automatically. Support will handle it.", reply_markup=kb_back_to_services(lang))
        except Exception:
            logger.exception("premium: failed to notify user about admin delivery failure")

    await state.clear()
    track("username_received", {"order_id": order_id})


# -------------------- Guarded fallback username capture (ONLY when user has admin_paid) --------------------
@router.message(
    lambda message, *args, **kwargs: any(
        o.get("user_id") == (message.from_user.id if message.from_user else None)
        and o.get("status") == "admin_paid"
        for o in orders.values()
    ),
    F.text
)
async def premium_username_fallback(msg: Message):
    # This handler ONLY activates when the user actually has an admin_paid premium order.
    candidate = None
    for oid, o in sorted(orders.items(), key=lambda kv: kv[0], reverse=True):
        if o.get("user_id") == msg.from_user.id and o.get("status") == "admin_paid":
            candidate = o
            break
    if not candidate:
        return

    order = candidate
    order_id = order.get("order_id")
    lang = order.get("lang", "en")
    target_username = (msg.text or "").strip()
    if not target_username:
        return

    order["target_username"] = target_username
    order["status"] = "username_received"
    save_orders()
    logger.info("Fallback username capture: user %s -> order %s username %s", msg.from_user.id, order_id, target_username)

    try:
        await msg.answer(t(lang, "username_saved"), reply_markup=kb_back_to_services(lang))
    except Exception:
        pass

    admin_text = t(lang, "admin_username").format(
        oid=order_id,
        username=order.get("username"),
        pkg=order.get("package"),
        target=target_username
    )
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "admin_btn_copy_price"), callback_data=f"premium_admin_copy_price_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "admin_btn_copy_username"), callback_data=f"premium_admin_copy_username_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "admin_btn_copy_account"), callback_data=f"premium_admin_copy_account_{order_id}")],
        [InlineKeyboardButton(text=t(lang, "admin_btn_completed"), callback_data=f"premium_admin_completed_{order_id}")]
    ])
    admin_chat_target = order.get("admin_handled_by") or ADMIN_ID
    try:
        await msg.bot.send_message(chat_id=admin_chat_target, text=admin_text, reply_markup=admin_kb)
        account_info = CBE_ACCOUNT if order.get("payment_method") == "CBE" else TELEBIRR_ACCOUNT
        code_block = f"Target username: `{target_username}`\nPackage: `{order.get('package')}`\nOrder ID: `{order_id}`\nPrice: `{order.get('price_etb')} ETB`\nAccount: `{account_info}`"
        await msg.bot.send_message(chat_id=admin_chat_target, text=code_block, parse_mode="Markdown")
    except Exception:
        logger.exception("premium: forward username to admin (fallback) failed")
        try:
            await msg.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=admin_kb)
            account_info = CBE_ACCOUNT if order.get("payment_method") == "CBE" else TELEBIRR_ACCOUNT
            code_block = f"Target username: `{target_username}`\nPackage: `{order.get('package')}`\nOrder ID: `{order_id}`\nPrice: `{order.get('price_etb')} ETB`\nAccount: `{account_info}`"
            await msg.bot.send_message(chat_id=ADMIN_ID, text=code_block, parse_mode="Markdown")
        except Exception:
            logger.exception("premium: forward username to ADMIN_ID also failed")

    track("username_received_fallback", {"order_id": order_id})


# -------------------- Admin Copy buttons (long-press code blocks) --------------------
@router.callback_query(F.data.startswith("premium_admin_copy_price_"))
async def premium_admin_copy_price(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = await get_active_order_or_notify(cb, order_id)
    if not order:
        return
    try:
        # show with ETB suffix
        await cb.message.reply(f"`{order.get('price_etb')} ETB`", parse_mode="Markdown")
    except Exception:
        logger.exception("premium: failed to send copy price")
    await cb.answer()


@router.callback_query(F.data.startswith("premium_admin_copy_username_"))
async def premium_admin_copy_username(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = await get_active_order_or_notify(cb, order_id)
    if not order:
        return
    username = order.get("target_username") or ""
    try:
        await cb.message.reply(f"`{username}`", parse_mode="Markdown")
    except Exception:
        logger.exception("premium: failed to send copy username")
    await cb.answer()


@router.callback_query(F.data.startswith("premium_admin_copy_account_"))
async def premium_admin_copy_account(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = await get_active_order_or_notify(cb, order_id)
    if not order:
        return
    # Determine which account to show based on selected payment method
    method = order.get("payment_method")
    acc = CBE_ACCOUNT if method == "CBE" else TELEBIRR_ACCOUNT
    try:
        await cb.message.reply(f"`{acc}`", parse_mode="Markdown")
    except Exception:
        logger.exception("premium: failed to send copy account")
    await cb.answer()


# Also expose a generic copy_account for user's inline "Copy Account" button
@router.callback_query(F.data.startswith("premium_copy_account_"))
async def premium_copy_account_user(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        try:
            await cb.answer(t("en", "order_not_found"), show_alert=True)
        except Exception:
            pass
        return
    method = order.get("payment_method")
    acc = CBE_ACCOUNT if method == "CBE" else TELEBIRR_ACCOUNT
    try:
        await cb.message.answer(f"`{acc}`", parse_mode="Markdown")
    except Exception:
        try:
            await cb.message.answer(acc)
        except Exception:
            logger.exception("premium: failed to reply account to user")
    await cb.answer("Value shown (long-press to copy).")


# -------------------- Admin: Completed (archive + notifications) --------------------
@router.callback_query(F.data.startswith("premium_admin_completed_"))
async def premium_admin_completed(cb: CallbackQuery):
    order_id = cb.data.split("_")[-1]
    order = orders.get(order_id)
    if not order:
        try:
            await cb.answer(t("en", "order_not_found"), show_alert=True)
        except Exception:
            pass
        return

    order["status"] = "completed"
    order["completed_at"] = now_str()
    save_orders()

    lang = order.get("lang", "en")
    pkg = order.get("package")
    target = order.get("target_username") or "@unknown"

    # Record completion to tracker (order_completed)
    try:
        if tracker and hasattr(tracker, "record_event"):
            tracker.record_event("order_completed", {
                "service": "premium",
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": 1,
                "currency": "PREMIUM",
                "total_etb": order.get("price_etb"),
                "payment_method": order.get("payment_method"),
                "status": "completed",
                "created_at": order.get("created_at") or datetime.utcnow(),
                "completed_at": datetime.utcnow()
            })
        elif tracker and hasattr(tracker, "record_order"):
            tracker.record_order("premium", {
                "order_id": order_id,
                "user_id": order.get("user_id"),
                "username": order.get("username"),
                "amount": 1,
                "currency": "PREMIUM",
                "total_etb": order.get("price_etb"),
                "payment_method": order.get("payment_method"),
                "status": "completed",
                "created_at": order.get("created_at") or datetime.utcnow(),
                "completed_at": datetime.utcnow()
            })
    except Exception:
        pass

    # Build join + contact support keyboard for the user final message
    join_button = InlineKeyboardButton(text="🔔 Join Channel", url="https://t.me/plugmarketshop1")
    support_button = InlineKeyboardButton(text="📞 Contact Support" if lang == "en" else "📞 ድጋፊ አግኙ", url="https://t.me/plugmarketshop")
    final_kb = InlineKeyboardMarkup(inline_keyboard=[
        [join_button],
        [support_button]
    ])

    try:
        await cb.bot.send_message(
            chat_id=order.get("user_id"),
            text=t(lang, "final_user").format(pkg=pkg, target=target),
            reply_markup=final_kb
        )
    except Exception:
        logger.exception("premium: send final user message failed")

    # small admin notification about completion (language chosen by user is respected)
    try:
        admin_conf_text = t(lang, "admin_completed_confirm").format(oid=order_id, pkg=pkg, target=target)
        admin_chat = order.get("admin_handled_by") or ADMIN_ID
        await cb.bot.send_message(chat_id=admin_chat, text=f"🔔 {admin_conf_text}")
    except Exception:
        logger.exception("premium: send admin confirmation failed")

    # Archive order (move to archived_orders so further clicks say "Order not found")
    try:
        archived = dict(order)
        archived["archived_at"] = now_str()
        archived_orders[order_id] = archived
        if order_id in orders:
            del orders[order_id]
        save_orders()
        save_archived_orders()
        logger.info("Order %s archived after completion", order_id)
    except Exception:
        logger.exception("premium: failed to archive completed order")

    await cb.answer("User notified completed.", show_alert=False)
    track("completed", {"order_id": order_id})


# -------------------- Admin commands for inspection --------------------
@router.message(F.text & F.text.startswith("/premium_orders"))
async def admin_list_orders(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        await msg.reply("Not allowed.")
        return
    if not orders:
        await msg.reply("No orders saved.")
        return
    lines = []
    for oid, o in sorted(orders.items(), key=lambda kv: kv[0], reverse=True):
        lines.append(f"{oid} | @{o.get('username')} | {o.get('package')} | {o.get('status')}")
    text = "\n".join(lines[:50])
    await msg.reply(text)


@router.message(F.text & F.text.startswith("/premium_orders_archive"))
async def admin_list_archived(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        await msg.reply("Not allowed.")
        return
    if not archived_orders:
        await msg.reply("No archived orders.")
        return
    lines = []
    for oid, o in sorted(archived_orders.items(), key=lambda kv: kv[0], reverse=True):
        archived_at = o.get("archived_at", o.get("completed_at", ""))
        lines.append(f"{oid} | @{o.get('username')} | {o.get('package')} | archived_at: {archived_at}")
    text = "\n".join(lines[:50])
    await msg.reply(text)


# ------- helper for main.py wiring (optional) -------
def setup(dp):
    """
    Call this from main.py after creating Dispatcher:
        from telegram_premium import setup
        setup(dp)
    """
    dp.include_router(router)
