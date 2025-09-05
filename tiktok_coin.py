# tiktok_coin.py
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

router = Router()
logger = logging.getLogger(__name__)

# -------------------- Config / Constants --------------------
ADMIN_ID = 6968325481
SUPPORT_USERNAME = "plugmarketshop"

# Payment placeholders (replaceable)
CBE_ACCOUNT = "1000476183921"
CBE_NAME = "Aschalew Desta"
TELEBIRR_NUMBER = "0956241518"
TELEBIRR_NAME = "Aschalew Desta"

# ===== PRICING =====
# 100 coins = 270 ETB -> 1 coin = 2.7 ETB
COIN_RATE_PER_100 = 270.0
COIN_UNIT_RATE = COIN_RATE_PER_100 / 100.0
MIN_COINS = 100

# ===== IN-MEMORY STORES =====
ORDERS = {}       # order_id -> dict
USER_ACTIVE = {}  # user_id -> current order_id

# ===== I18N =====
def t(lang: str, key: str, **kw):
    en = {
        "start": "Please enter the amount of TikTok Coins you want to purchase. Minimum is 100 coins.",
        "min_warn": f"Minimum is {MIN_COINS} coins.",
        "invalid_amount": "Please enter a valid number (minimum 100).",
        "total_price": "💳 Total Price: {etb} ETB",
        "choose_payment": "Please choose your payment method:",
        "cbe": "🏦 CBE",
        "tele": "📱 Telebirr",
        "cbe_details": "🏦 Bank: Commercial Bank of Ethiopia\n📄 Name: {name}\n💳 Account: {acc}",
        "tele_details": "📱 Telebirr Number: {num}\n📄 Name: {name}",
        "pay_instr": "Please send the total amount to the selected account. Once paid, click '✅ Done'.",
        "done": "✅ Done",
        "back": "↩ Back",
        "cancel": "❌ Cancel",
        "ask_upload": "Please upload a screenshot as proof of payment.",
        "admin_notify": ("🎵 TikTok Coin Order\nOrder ID: {order_id}\nUser: @{user}\nCoins: {coins}\nTotal ETB: {etb}\nMethod: {method}\nDate: {date}"),
        "admin_paid": "✅ Paid",
        "admin_not_paid": "❌ Not Paid",
        "payment_received_user": "✅ Payment proof received. Admin will review shortly.",
        "not_paid_user": "⚠️ Payment not received. Please pay and try again.",
        "contact_support": "📞 Contact Support",
        "after_paid_user": ("✅ Your order is successfully created! To receive your TikTok Coins, please click 'Contact Support' and type 'TikTok Coin'. Support will request your TikTok account login info."),
        "send_login_button": "📤 Send Login Info to Admin",
        "admin_login_notify": "📢 User sent login info for Order ID: {order_id}\nUser: @{user}\nPlease purchase their coins and click 'Payment Completed'.",
        "admin_payment_completed": "✅ Payment Completed",
        "final_user": ("🎉 Congratulations! Your TikTok Coins have been successfully added to your account: @{username}\n"
                       "💰 Amount Sent: {coins} coins\n"
                       "🏅 Check your TikTok balance!\n"
                       "💬 If you have any questions, click 'Contact Support'.\n"
                       "🙏 Thanks for trading with us!"),
        "copied_value": "Value shown — long-press to copy",
        "no_order": "No active order found.",
        "cancelled": "❌ Your order has been cancelled.",
        "something_wrong": "Something went wrong. Please try again."
    }
    am = {
        "start": "እባክዎ የሚፈልጉትን የTikTok ኮይኖች መጠን ያስገቡ። ዝቅተኛ 100 ኮይን ነው.",
        "min_warn": f"ዝቅተኛ {MIN_COINS} ኮይን ነው።",
        "invalid_amount": "እባክዎ ትክክለኛ ቁጥር ያስገቡ (ዝቅተኛ 100).",
        "total_price": "💳 አጠቃላይ ዋጋ: {etb} ETB",
        "choose_payment": "የክፍያ ዘዴ ይምረጡ:",
        "cbe": "🏦 CBE",
        "tele": "📱 Telebirr",
        "cbe_details": "🏦 ባንክ: Commercial Bank of Ethiopia\n📄 ስም: {name}\n💳 ቁጥር: {acc}",
        "tele_details": "📱 Telebirr ቁጥር: {num}\n📄 ስም: {name}",
        "pay_instr": "እባክዎ አጠቃላይ ዋጋውን ወደ የተመረጠው አካውንት ይላኩ። ክፍያ ካደረጉ '✅ Done' ይጫኑ።",
        "done": "✅ ተጠናቀቀ",
        "back": "↩ መመለስ",
        "cancel": "❌ ሰርዝ",
        "ask_upload": "እባክዎ የክፍያ ማስረጃ ስክሪንሾት ያስገቡ።",
        "admin_notify": ("🎵 የTikTok ኮይን ትዕዛዝ\nOrder ID: {order_id}\nተጠቃሚ: @{user}\nኮይን: {coins}\nአጠቃላይ ETB: {etb}\nዘዴ: {method}\nቀን: {date}"),
        "admin_paid": "✅ ተከፈለ",
        "admin_not_paid": "❌ አልተከፈለም",
        "payment_received_user": "✅ የክፍያ ማስረጃ ተቀባ። አስተዳዳሪ ይመርምራል።",
        "not_paid_user": "⚠️ ክፍያ አልተቀበለም። እባክዎ ዳግም ይክፈሉ እና ደግሞ ማስረጃ ይስቀሉ።",
        "contact_support": "📞 ወደ ድጋፊ ይገናኙ",
        "after_paid_user": ("✅ ትክክለኛ ትዕዛዝ ተፈጥሯል! ለTikTok ኮይኖች መቀበል እባክዎ 'Contact Support' ይጫኑ እና 'TikTok Coin' ይጻፉ. ድጋፊ የTikTok ማስተካከያ መረጃዎን ይጠይቃል."),
        "send_login_button": "📤 መግቢያ መረጃ ወደ አስተዳዳሪ ይላኩ",
        "admin_login_notify": "📢 ተጠቃሚው የመግቢያ መረጃ ላከ። Order ID: {order_id}\nተጠቃሚ: @{user}\nእባክዎ ኮይኖቹን ይገዙ እና 'Payment Completed' ይጫኑ።",
        "admin_payment_completed": "✅ ክፍያ ተጠናቀቀ",
        "final_user": ("🎉 እንኳን ደስ አለ! TikTok ኮይኖች በተሳካ ሁኔታ ወደ አካውንትዎ ተጨመሩ: @{username}\n"
                       "💰 ተላከው: {coins} ኮይን\n"
                       "🏅 የTikTok ሚዛንዎን ይመልከቱ!\n"
                       "💬 ማንኛውንም ጥያቄ ካለዎት 'Contact Support' ይጫኑ።\n"
                       "🙏 ስለ ግብዣዎ እናመሰግናለን!"),
        "copied_value": "ዋጋው ታይቷል — ለኮፒ ለማድረግ ይይዙ",
        "no_order": "አሁን የሚሰራ ትዕዛዝ የለም።",
        "cancelled": "❌ ትዕዛዝዎ ተሰርዟል።",
        "something_wrong": "ችግኝ ተፈጥሯል። እባክዎ ዳግም ይሞክሩ።"
    }
    d = am if lang == "am" else en
    return d[key].format(**kw)

# ===== FSM STATES =====
class TiktokStates(StatesGroup):
    waiting_amount = State()
    waiting_payment = State()
    waiting_proof = State()
    waiting_after_paid = State()  # user returns after contacting support to send login
    waiting_login_send = State()

# ===== HELPERS & KEYBOARDS =====
def gen_order_id():
    ts = datetime.utcnow().strftime("%y%m%d%H%M%S")
    rnd = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"TK-{ts}{rnd}"

def kb_back_cancel(lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"back"), callback_data="tk_back")],
        [InlineKeyboardButton(text=t(lang,"cancel"), callback_data="tk_cancel")]
    ])

def kb_payment_methods(order_id, etb, lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"cbe"), callback_data=f"tk_pay_cbe:{order_id}:{etb}"),
         InlineKeyboardButton(text=t(lang,"tele"), callback_data=f"tk_pay_tele:{order_id}:{etb}")],
        [InlineKeyboardButton(text=t(lang,"back"), callback_data=f"tk_back_to_amount:{order_id}"),
         InlineKeyboardButton(text=t(lang,"cancel"), callback_data="tk_cancel")]
    ])

def kb_done_cancel_back(lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"done"), callback_data="tk_done"),
         InlineKeyboardButton(text=t(lang,"back"), callback_data="tk_back"),
         InlineKeyboardButton(text=t(lang,"cancel"), callback_data="tk_cancel")]
    ])

def kb_admin_actions(order_id, lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"admin_paid"), callback_data=f"tk_admin_paid:{order_id}"),
         InlineKeyboardButton(text=t(lang,"admin_not_paid"), callback_data=f"tk_admin_not_paid:{order_id}")],
    ])

def kb_admin_payment_completed(order_id, lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"admin_payment_completed"), callback_data=f"tk_admin_completed:{order_id}")]
    ])

def kb_send_login_button(order_id, lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"send_login_button"), callback_data=f"tk_user_sent_login:{order_id}")],
        [InlineKeyboardButton(text=t(lang,"contact_support"), url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(text=t(lang,"back"), callback_data="tk_back")]
    ])

def kb_contact_support(lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang,"contact_support"), url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(text=t(lang,"back"), callback_data="tk_back")]
    ])

def kb_copy(value: str, lang="en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Copy", callback_data=f"tk_copy:{value}")]
    ])

# ===== ENTRY / helper for main.py =====
@router.callback_query(F.data.in_({"tiktok_menu_en", "tiktok_menu_am", "service_tiktok_coin"}))
async def open_tiktok_coin_menu(cb: CallbackQuery, state: FSMContext):
    if cb.data.endswith("_am"):
        lang = "am"
    elif cb.data.endswith("_en"):
        lang = "en"
    else:
        lang = await ensure_lang(state)

    await state.clear()
    await state.update_data(lang=lang)

async def start_tiktok_flow(message: Message):
    await message.answer(t("en","start"))

# ===== NAV HANDLERS =====
@router.callback_query(F.data == "tk_back")
async def tk_back(cb: CallbackQuery, state: FSMContext):
    # return to the amount prompt
    data = await state.get_data()
    lang = data.get("lang") or data.get("language") or "en"
    await cb.message.edit_text(t(lang,"start"), reply_markup=kb_back_cancel(lang))
    await state.set_state(TiktokStates.waiting_amount)
    await cb.answer()

@router.callback_query(F.data == "tk_cancel")
async def tk_cancel(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang") or data.get("language") or "en"
    uid = cb.from_user.id
    oid = USER_ACTIVE.pop(uid, None)
    if oid:
        ORDERS.pop(oid, None)
    await cb.message.edit_text(t(lang,"cancelled"), reply_markup=kb_contact_support(lang))
    await state.clear()
    await cb.answer()

# ===== AMOUNT INPUT =====
@router.message(TiktokStates.waiting_amount, F.text)
async def receive_amount(msg: Message, state: FSMContext):
    lang = (await state.get_data()).get("lang") or (await state.get_data()).get("language") or "en"
    text = msg.text.strip().replace(",", "")
    try:
        coins = int(float(text))
    except:
        await msg.answer(t(lang,"invalid_amount")); return
    if coins < MIN_COINS:
        await msg.answer(t(lang,"invalid_amount")); return

    # calculate total
    total_etb = coins * COIN_UNIT_RATE
    total_etb_display = f"{total_etb:,.2f}"

    # create order
    uid = msg.from_user.id
    oid = gen_order_id()
    USER_ACTIVE[uid] = oid
    ORDERS[oid] = {
        "user_id": uid,
        "coins": coins,
        "total_etb": total_etb,
        "created_at": datetime.utcnow().isoformat(),
        "status": "awaiting_payment",
        "lang": lang
    }
    # send total and payment choices
    await msg.answer(t(lang,"total_price", etb=total_etb_display), reply_markup=kb_payment_methods(oid, total_etb_display, lang))
    await state.set_state(TiktokStates.waiting_payment)
    # tracker: record quote shown
    try:
        tracker.record_order(service="tiktok", admin_id=ADMIN_ID, user_id=uid, amount=total_etb, currency="ETB", extra_info={"order_id": oid, "stage": "quoted", "coins": coins})
    except:
        pass

# helper order id generator
def gen_order_id():
    ts = datetime.utcnow().strftime("%y%m%d%H%M%S")
    rnd = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"TK-{ts}{rnd}"

# ===== PAYMENT METHOD CHOSEN =====
@router.callback_query(F.data.startswith("tk_pay_cbe:"))
async def tk_pay_cbe(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    if len(parts) < 3:
        await cb.answer("Invalid"); return
    _, order_id, etb = parts
    ctx = ORDERS.get(order_id)
    if not ctx:
        await cb.answer(t("en","something_wrong")); return
    lang = ctx.get("lang","en")
    ctx["chosen_payment"] = "CBE"
    ctx["chosen_payment_etb"] = float(str(etb).replace(",",""))
    USER_ACTIVE[ctx["user_id"]] = order_id
    await cb.message.edit_text(t(lang,"cbe_details", name=CBE_NAME, acc=CBE_ACCOUNT), reply_markup=kb_copy(CBE_ACCOUNT, lang))
    await cb.message.answer(t(lang,"pay_instr"), reply_markup=kb_done_cancel_back(lang))
    await state.set_state(TiktokStates.waiting_proof)
    await cb.answer()

@router.callback_query(F.data.startswith("tk_pay_tele:"))
async def tk_pay_tele(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    if len(parts) < 3:
        await cb.answer("Invalid"); return
    _, order_id, etb = parts
    ctx = ORDERS.get(order_id)
    if not ctx:
        await cb.answer(t("en","something_wrong")); return
    lang = ctx.get("lang","en")
    ctx["chosen_payment"] = "Telebirr"
    ctx["chosen_payment_etb"] = float(str(etb).replace(",",""))
    USER_ACTIVE[ctx["user_id"]] = order_id
    await cb.message.edit_text(t(lang,"tele_details", num=TELEBIRR_NUMBER, name=TELEBIRR_NAME), reply_markup=kb_copy(TELEBIRR_NUMBER, lang))
    await cb.message.answer(t(lang,"pay_instr"), reply_markup=kb_done_cancel_back(lang))
    await state.set_state(TiktokStates.waiting_proof)
    await cb.answer()

@router.callback_query(F.data == "tk_done")
async def tk_done(cb: CallbackQuery):
    await cb.answer("Please upload your payment proof now.", show_alert=False)

# ===== USER UPLOADS PROOF =====
@router.message(TiktokStates.waiting_proof, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def tk_receive_proof(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    order_id = USER_ACTIVE.get(uid)
    if not order_id:
        lang = (await state.get_data()).get("lang") or (await state.get_data()).get("language") or "en"
        await msg.answer(t(lang,"no_order")); return
    ctx = ORDERS.get(order_id)
    if not ctx:
        await msg.answer(t("en","something_wrong")); return
    # save proof
    if msg.photo:
        ctx["payment_proof"] = msg.photo[-1].file_id
    elif msg.document:
        ctx["payment_proof"] = msg.document.file_id
    ctx["status"] = "proof_submitted"
    ctx["proof_at"] = datetime.utcnow().isoformat()
    method = ctx.get("chosen_payment", "Unknown")
    coins = ctx.get("coins")
    etb = ctx.get("total_etb")
    admin_text = t(ctx.get("lang","en"), "admin_notify", order_id=order_id, user=(msg.from_user.username or msg.from_user.full_name), coins=coins, etb=f"{etb:,.2f}", method=method, date=ctx["proof_at"])
    try:
        if ctx.get("payment_proof"):
            await msg.bot.send_photo(ADMIN_ID, ctx["payment_proof"], caption=admin_text, reply_markup=kb_admin_actions(order_id, ctx.get("lang","en")))
        else:
            await msg.bot.send_message(ADMIN_ID, admin_text, reply_markup=kb_admin_actions(order_id, ctx.get("lang","en")))
    except:
        await msg.bot.send_message(ADMIN_ID, admin_text, reply_markup=kb_admin_actions(order_id, ctx.get("lang","en")))
    await msg.answer(t(ctx.get("lang","en"), "payment_received_user"))
    # tracker: record proof uploaded
    try:
        tracker.record_order(service="tiktok", admin_id=ADMIN_ID, user_id=uid, amount=etb, currency="ETB", extra_info={"order_id": order_id, "stage": "proof_submitted", "coins": coins})
    except:
        pass
    await state.set_state(None)

# ===== ADMIN: Not Paid / Paid =====
@router.callback_query(F.data.startswith("tk_admin_not_paid:"))
async def tk_admin_not_paid(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("Only admin can use this.", show_alert=True); return
    order_id = cb.data.split(":",1)[1]
    ctx = ORDERS.get(order_id)
    if not ctx:
        await cb.answer("Order not found."); return
    ctx["status"] = "payment_not_received"
    uid = ctx["user_id"]
    lang = ctx.get("lang","en")
    await cb.bot.send_message(uid, t(lang,"not_paid_user"), reply_markup=kb_contact_support(lang))
    await cb.answer("User notified (not paid).")

@router.callback_query(F.data.startswith("tk_admin_paid:"))
async def tk_admin_paid(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("Only admin can use this.", show_alert=True); return
    order_id = cb.data.split(":",1)[1]
    ctx = ORDERS.get(order_id)
    if not ctx:
        await cb.answer("Order not found."); return
    ctx["status"] = "payment_confirmed"
    uid = ctx["user_id"]
    lang = ctx.get("lang","en")
    # tell user to contact support; provide Contact Support button
    await cb.bot.send_message(uid, t(lang,"after_paid_user"), reply_markup=kb_contact_support(lang))
    await cb.answer("Marked as paid. User instructed to contact support.")

# ===== USER: after talking to support -> returns and clicks "Send Login Info to Admin" =====
@router.callback_query(F.data.startswith("tk_user_sent_login:"))
async def tk_user_sent_login(cb: CallbackQuery):
    parts = cb.data.split(":")
    if len(parts) != 2:
        await cb.answer("Invalid"); return
    order_id = parts[1]
    ctx = ORDERS.get(order_id)
    if not ctx:
        await cb.answer("Order not found."); return
    uid = ctx["user_id"]
    # only allow the owner to press
    if cb.from_user.id != uid:
        await cb.answer("This is not your order.", show_alert=True); return
    # send admin a notification that user sent login info
    admin_msg = t(ctx.get("lang","en"), "admin_login_notify", order_id=order_id, user=(cb.from_user.username or cb.from_user.full_name))
    await cb.bot.send_message(ADMIN_ID, admin_msg, reply_markup=kb_admin_payment_completed(order_id, ctx.get("lang","en")))
    ctx["status"] = "login_info_sent"
    # tracker: note user sent login info
    try:
        tracker.record_order(service="tiktok", admin_id=ADMIN_ID, user_id=uid, amount=0.0, currency="ETB", extra_info={"order_id": order_id, "stage": "login_info_sent", "coins": ctx.get("coins")})
    except:
        pass
    await cb.answer("Login info forwarded to admin.", show_alert=True)
    await cb.bot.send_message(uid, "✅ Notified admin. Wait for them to confirm payment completed.")

# ===== ADMIN: mark Payment Completed (coins sent) =====
@router.callback_query(F.data.startswith("tk_admin_completed:"))
async def tk_admin_completed(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("Only admin can use this.", show_alert=True); return
    order_id = cb.data.split(":",1)[1]
    ctx = ORDERS.get(order_id)
    if not ctx:
        await cb.answer("Order not found."); return
    ctx["status"] = "completed"
    uid = ctx["user_id"]
    # get the tiktok username - ideally support had it and forwarded to admin; allow using delivery_username field if set
    tiktok_username = ctx.get("tiktok_username", "(unknown)")
    # If admin wants to store username, they can set ctx["tiktok_username"] before pressing the button (out of scope)
    await cb.bot.send_message(uid, t(ctx.get("lang","en"), "final_user", username=tiktok_username, coins=ctx.get("coins")))
    # tracker: record completed
    try:
        tracker.record_order(service="tiktok", admin_id=cb.from_user.id, user_id=uid, amount=ctx.get("total_etb",0.0), currency="ETB", extra_info={"order_id": order_id, "stage": "completed", "coins": ctx.get("coins")})
    except:
        pass
    await cb.answer("Marked completed and user notified.")

# ===== COPY callback (shows value so users/admins can copy) =====
@router.callback_query(F.data.startswith("tk_copy:"))
async def tk_copy(cb: CallbackQuery):
    value = cb.data.split("tk_copy:",1)[1]
    try:
        await cb.message.answer(f"`{value}`")
    except:
        await cb.message.answer(value)
    # try to get language
    try:
        state = router.current_state(user=cb.from_user.id)
        data = await state.get_data()
        lang = data.get("lang") or data.get("language") or "en"
    except:
        lang = "en"
    await cb.answer(t(lang,"copied_value"))

# ===== FALLBACK / unknown text handler (used to accept tiktok username if you want to set it manually) =====
@router.message(F.text)
async def fallback_text(msg: Message):
    # This handler is intentionally lightweight: we don't want to capture unrelated text.
    # If user sends text while in a flow that expects it (states), the other handlers will catch it.
    return

# End of tiktok.py
