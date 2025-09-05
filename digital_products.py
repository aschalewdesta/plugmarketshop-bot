# digital_products.py
import datetime
import os
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# === CONFIG ===
ADMIN_ID = 6968325481     # admin
OWNER_ID = 6781140962     # owner fallback
JOIN_CHANNEL = "https://t.me/plugmarketshop1"
router = Router()

# === FSM States ===
class DigitalStates(StatesGroup):
    choosing_product = State()
    choosing_payment_method = State()
    waiting_done_click = State()
    waiting_payment_proof = State()

# === PRODUCTS (replace file/link placeholders) ===
PRODUCTS = [
    {
        "title_en": "🎬 50GB+ Editing Assets For Video Editors",
        "title_am": "🎬 50GB+ የቪዲዮ ኤዲቲንግ አሰባሰብ",
        "price": 500,
        "file": "https://example.com/sample_50gb.zip",
        "coming_soon": False
    },
    {
        "title_en": "🖼️ Full Thumbnail Asset For Thumbnail Designer",
        "title_am": "🖼️ ሙሉ የThumbnail አሰባሰብ",
        "price": 500,
        "file": "https://example.com/sample_thumbnail.zip",
        "coming_soon": False
    },
    {
        "title_en": "📚 Notion Templates That Will Change Your Life",
        "title_am": "📚 ሕይወትዎን የሚለውጡ የኖሽን ተምፕለቶች",
        "price": None,
        "file": None,
        "coming_soon": False
    }
]

# === PAYMENT METHODS ===
PAYMENT_METHODS = {
    "cbe": {"label": "🏦 CBE", "account": "1000476183921", "name": "Aschalew Desta"},
    "telebirr": {"label": "📲 Telebirr", "account": "0916253200", "name": "Aschalew Desta"}
}

# === In-memory order store ===
# user_id -> order dict
ORDERS = {}

# === Keyboards ===
def keyboard_row(btns):
    return InlineKeyboardMarkup(inline_keyboard=[[b for b in btns]])

def digital_menu_kb(lang_code):
    kb = []
    for idx, p in enumerate(PRODUCTS):
        label = p["title_en"] if lang_code == "en" else p["title_am"]
        kb.append([InlineKeyboardButton(text=label, callback_data=f"product_{idx}_{lang_code}")])
    # Back -> main menu (lang_x)
    kb.append([InlineKeyboardButton(text=("🔙 Back" if lang_code=="en" else "🔙 ተመለስ"), callback_data=f"lang_{lang_code}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def product_page_kb(product_index, lang_code):
    kb = [
        [InlineKeyboardButton(text=("💳 Choose payment" if lang_code=="en" else "💳 የክፍያ ይምረጡ"), callback_data=f"productpay_{product_index}_{lang_code}")],
        [InlineKeyboardButton(text=("🔙 Back" if lang_code=="en" else "🔙 ተመለስ"), callback_data=f"digital_{lang_code}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def payment_methods_kb(product_index, lang_code):
    kb = [
        [InlineKeyboardButton(text=PAYMENT_METHODS["cbe"]["label"], callback_data=f"pay_cbe_{product_index}_{lang_code}"),
         InlineKeyboardButton(text=PAYMENT_METHODS["telebirr"]["label"], callback_data=f"pay_telebirr_{product_index}_{lang_code}")],
        [InlineKeyboardButton(text=("🔙 Back" if lang_code=="en" else "🔙 ተመለስ"), callback_data=f"product_{product_index}_{lang_code}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def done_back_kb(product_index, lang_code):
    kb = [
        [InlineKeyboardButton(text=("✅ Done" if lang_code=="en" else "✅ ተጠናቀቀ"), callback_data=f"done_payment_{product_index}_{lang_code}")],
        [InlineKeyboardButton(text=("🔙 Back" if lang_code=="en" else "🔙 ተመለስ"), callback_data=f"product_{product_index}_{lang_code}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def notion_menu_kb(lang_code):
    labels_en = [
        ("gym", "🏋️ Gym full table — all features included"),
        ("business", "📈 Business strategy & rules full table"),
        ("money", "💰 Money management: income & expenses table"),
        ("content", "✍️ Content creation: full strategy & guide"),
        ("time", "⏱ Time management to reach a million from 0 in under a year"),
    ]
    labels_am = [
        ("gym", "🏋️ Gym full table - ሁሉንም ፉቸር ያለው"),
        ("business", "📈 የቢዝነስ ስትራቴጂና ህጎች full table"),
        ("money", "💰 የገንዘብ አስተዳደር: ገቢና ወጪ ሰንጠረዥ"),
        ("content", "✍️ የContent Creation: ሙሉ ስትራቴጂ"),
        ("time", "⏱ የጊዜ አያያዝ ከአንድ አመት በታች ከ 0 ወደ አንድ ሚሊዮን ለመድረስ")
    ]
    items = labels_en if lang_code=="en" else labels_am
    kb = [[InlineKeyboardButton(text=label, callback_data=f"notion_{key}_{lang_code}")] for key, label in items]
    kb.append([InlineKeyboardButton(text=("🔙 Back" if lang_code=="en" else "🔙 ተመለስ"), callback_data=f"product_2_{lang_code}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def proof_received_admin_kb(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Paid", callback_data=f"admin_paid_{user_id}"),
         InlineKeyboardButton(text="❌ Not Paid", callback_data=f"admin_notpaid_{user_id}")]
    ])

def copy_kb(account_text, lang_code):
    label = "📋 Copy" if lang_code=="en" else "📋 ኮፒ ያድርጉ"
    # use delimiter "__" to include the text after the language for parsing
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"copy_account_{lang_code}__{account_text}")]
    ])

# === Navigation helpers: send new menu message and try to delete old bot message ===
async def send_and_delete_old(old_message: types.Message, text: str, reply_markup: InlineKeyboardMarkup = None):
    # send new message with menu
    new_msg = await old_message.answer(text, reply_markup=reply_markup)
    # try to delete old bot message to avoid clutter (safe)
    try:
        await old_message.delete()
    except Exception:
        pass
    return new_msg

# === Routes ===

# Entry -> show digital menu
@router.callback_query(lambda c: c.data.startswith("digital_"))
async def show_digital_products(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split("_", 1)[1]
    text = "🛒 Choose a digital product:" if lang == "en" else "🛒 ዲጂታል እቃ ይምረጡ:"
    await send_and_delete_old(callback.message, text, reply_markup=digital_menu_kb(lang))
    await state.set_state(DigitalStates.choosing_product)
    await callback.answer()

# Show product page (price & choose payment)
@router.callback_query(lambda c: c.data.startswith("product_"))
async def on_choose_product(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, idx_str, lang = callback.data.split("_", 2)
        idx = int(idx_str)
    except Exception:
        await callback.answer("Invalid data.", show_alert=True)
        return

    if idx < 0 or idx >= len(PRODUCTS):
        await callback.answer("Product not found.", show_alert=True)
        return

    product = PRODUCTS[idx]
    if idx == 2:
        # Notion -> show notion submenu
        text = "📚 Select a Notion template:" if lang=="en" else "📚 ኖሽን ተምፕለት ይምረጡ:"
        await send_and_delete_old(callback.message, text, reply_markup=notion_menu_kb(lang))
        # keep state cleared so user can navigate normally
        await state.clear()
        await callback.answer()
        return

    price_text = f"Total price: {product['price']} ETB" if lang == "en" else f"ዋጋ: {product['price']} ብር"
    text = f"{product['title_en'] if lang=='en' else product['title_am']}\n\n{price_text}\n\nPress below to choose payment." if lang=="en" else f"{product['title_am']}\n\n{price_text}\n\nየክፍያ አማራጭ ለማምረጥ ከዚች ታች ይጫኑ።"
    await send_and_delete_old(callback.message, text, reply_markup=product_page_kb(idx, lang))
    await state.update_data(product_index=idx, lang=lang)
    await state.set_state(DigitalStates.choosing_payment_method)
    await callback.answer()

# product -> payment methods (from product page)
@router.callback_query(lambda c: c.data.startswith("productpay_"))
async def on_productpay(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, idx_str, lang = callback.data.split("_", 2)
        product_index = int(idx_str)
    except Exception:
        await callback.answer("Invalid data.", show_alert=True)
        return

    product = PRODUCTS[product_index]
    price_text = f"Total price: {product['price']} ETB" if lang == "en" else f"ዋጋ: {product['price']} ብር"
    text = f"{price_text}\n\nChoose a payment method:" if lang == "en" else f"{price_text}\n\nክፍያ ዘዴ ይምረጡ:"
    await send_and_delete_old(callback.message, text, reply_markup=payment_methods_kb(product_index, lang))
    await callback.answer()

# Choose CBE / Telebirr (includes product index)
@router.callback_query(lambda c: c.data.startswith("pay_"))
async def on_choose_payment_method(callback: types.CallbackQuery, state: FSMContext):
    # format: pay_{method}_{product_index}_{lang}
    try:
        _, method, idx_str, lang = callback.data.split("_", 3)
        product_index = int(idx_str)
    except Exception:
        await callback.answer("Invalid data.", show_alert=True)
        return

    pm = PAYMENT_METHODS.get(method)
    if not pm:
        await callback.answer("Unknown payment method.", show_alert=True)
        return

    # store minimal order info in FSM and won't rely only on FSM later
    await state.update_data(product_index=product_index, payment_method=method, lang=lang)

    product = PRODUCTS[product_index]
    price = product.get("price")
    if lang == "en":
        text = (
            f"💳 Pay {price} ETB to:\n\n"
            f"Account / Number: {pm['account']}\n"
            f"Name: {pm['name']}\n\n"
            "After payment: press ✅ Done and upload payment proof (screenshot/image)."
        )
    else:
        text = (
            f"💳 እባክዎ {price} ብርን ወደዚህ አካውንት ይክፈሉ።\n\n"
            f"አካውንት / ቁጥር: {pm['account']}\n"
            f"ስም: {pm['name']}\n\n"
            "ከክፍያ በኋላ ✅ ተጠናቀቀ ይጫኑ እና የክፍያ ማስረጃ ያስገቡ።"
        )

    await send_and_delete_old(callback.message, text, reply_markup=done_back_kb(product_index, lang))
    # helper copy message
    try:
        await callback.message.answer(("Tap to copy account number:" if lang=="en" else "የአካውንት ቁጥር ለመኮፒ ይጫኑ።"), reply_markup=copy_kb(pm["account"], lang))
    except Exception:
        pass

    await state.set_state(DigitalStates.waiting_done_click)
    await callback.answer()

# Done -> create minimal pending order so upload works even if FSM is lost
@router.callback_query(lambda c: c.data.startswith("done_payment_"))
async def on_done_payment(callback: types.CallbackQuery, state: FSMContext):
    # format: done_payment_{product_index}_{lang}
    try:
        _, _, idx_str, lang = callback.data.split("_", 3)
        product_index = int(idx_str)
    except Exception:
        await callback.answer("Invalid data.", show_alert=True)
        return

    data = await state.get_data()
    payment_method = data.get("payment_method")
    user_id = callback.from_user.id

    # create or update order
    ORDERS[user_id] = {
        "product_index": product_index,
        "payment_method": payment_method or "unknown",
        "proof": None,
        "status": "waiting_proof",
        "username": callback.from_user.username or (callback.from_user.first_name or ""),
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lang": lang
    }

    prompt = "📎 Please upload your payment proof (screenshot/image):" if lang == "en" else "📎 እባክዎ የክፍያ ማስረጃዎን ይላኩ (ስክሪንሾት/ምስል):"
    await send_and_delete_old(callback.message, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=("🔙 Back" if lang=="en" else "🔙 ተመለስ"), callback_data=f"product_{product_index}_{lang}")]]))
    await state.update_data(product_index=product_index, payment_method=(payment_method or "unknown"), lang=lang)
    await state.set_state(DigitalStates.waiting_payment_proof)
    await callback.answer()

# Copy button sends the text so user can long-press and copy
@router.callback_query(lambda c: c.data.startswith("copy_"))
async def on_copy_button(callback: types.CallbackQuery):
    try:
        head, text_to_copy = callback.data.split("__", 1)
        _, tag, lang = head.split("_", 2)
    except Exception:
        await callback.answer("Invalid copy data.", show_alert=True)
        return

    # send as code block to ease long-press copy (some clients)
    try:
        await callback.message.answer(f"`{text_to_copy}`", parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text_to_copy)
    await callback.answer("📋 Text sent. Long-press to copy." if lang=="en" else "📋 ጽሑፉ ተልኳል። ኮፒ ለማድረግ በረዥሙ ይጫኑ።", show_alert=False)

# Notion template click -> show coming soon with Back to NOTION menu
@router.callback_query(lambda c: c.data.startswith("notion_"))
async def on_notion_choice(callback: types.CallbackQuery):
    try:
        _, key, lang = callback.data.split("_", 2)
    except Exception:
        await callback.answer("Invalid data.", show_alert=True)
        return
    text = "⏳ Coming soon!" if lang=="en" else "⏳ በቅርቡ..."
    # Back returns to notion menu (product_2_{lang})
    await send_and_delete_old(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=("🔙 Back" if lang=="en" else "🔙 ተመለስ"), callback_data=f"product_2_{lang}")]]))
    await callback.answer()

# =========
# NEW: Proof handler (state-specific) — fixes the "swallowed by generic handler" issue
# =========
@router.message(DigitalStates.waiting_payment_proof, F.photo | F.document | F.video | F.text)
async def on_receive_payment_proof(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    # We are already in the waiting_payment_proof state so FSM data should contain order info.
    data = await state.get_data()
    product_index = data.get("product_index")
    payment_method = data.get("payment_method")
    lang = data.get("lang", "en")

    # Fallback to ORDERS if FSM lost data
    if product_index is None:
        order = ORDERS.get(user_id)
        if order and order.get("status") in ("waiting_proof", "pending"):
            product_index = order.get("product_index")
            payment_method = order.get("payment_method")
            lang = order.get("lang", lang)
        else:
            await message.reply("Order data missing. Start again." if lang=="en" else "የትእዛዝ መረጃ አልተገኘም። እባክዎ እንደገና ይጀምሩ።")
            await state.clear()
            return

    # capture proof
    username = message.from_user.username or (message.from_user.first_name or "")
    if message.photo:
        proof_info = ("photo", message.photo[-1].file_id)
    elif message.document:
        proof_info = ("document", message.document.file_id)
    elif message.video:
        proof_info = ("video", message.video.file_id)
    else:
        proof_info = ("text", message.text or "[no text]")

    # update ORDERS
    ORDERS[user_id] = {
        "product_index": product_index,
        "payment_method": payment_method or "unknown",
        "proof": proof_info,
        "status": "pending",
        "username": username,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lang": lang
    }

    # Confirm to user immediately
    try:
        await message.reply("✅ Payment proof received. Admin notified." if lang=="en" else "✅ የክፍያ ማስረጃ ተቀበልናል። አስተዳዳሪውን አሳውቋል።")
    except Exception:
        pass

    product = PRODUCTS[product_index]
    product_name = product["title_en"] if lang=="en" else product["title_am"]
    payment_label = PAYMENT_METHODS.get(payment_method, {"label": payment_method})["label"]
    proof_preview = proof_info[1] if proof_info[0] in ("photo", "document", "video") else proof_info[1]

    # Admin text in user's language. Note: per request include specific title "NEW TikTok COIN ORDER"
    if lang == "en":
        admin_text = (
            "🎵 NEW TikTok COIN ORDER\n\n"
            f"Product: {product_name}\n"
            f"User: @{username} (id: {user_id})\n"
            f"Payment method: {payment_label}\n"
            f"Proof: {proof_preview}\n"
            f"Date: {ORDERS[user_id]['created_at']}\n"
            f"Order stored under user id: {user_id}"
        )
    else:
        admin_text = (
            "🎵 NEW TikTok COIN ORDER\n\n"
            f"ምርት: {product_name}\n"
            f"ተጠቃሚ: @{username} (መለያ: {user_id})\n"
            f"የክፍያ ዘዴ: {payment_label}\n"
            f"ማረጋገጫ: {proof_preview}\n"
            f"ቀን: {ORDERS[user_id]['created_at']}\n"
            f"ትዕዛዝ በመለያ: {user_id} ይታያል"
        )

    # Try to send media/text to admin (as media if possible), with Paid/NotPaid buttons
    sent = False
    try:
        if proof_info[0] == "photo":
            await message.bot.send_photo(ADMIN_ID, proof_info[1], caption=admin_text, reply_markup=proof_received_admin_kb(user_id))
            sent = True
        elif proof_info[0] == "document":
            await message.bot.send_document(ADMIN_ID, proof_info[1], caption=admin_text, reply_markup=proof_received_admin_kb(user_id))
            sent = True
        elif proof_info[0] == "video":
            await message.bot.send_video(ADMIN_ID, proof_info[1], caption=admin_text, reply_markup=proof_received_admin_kb(user_id))
            sent = True
        else:
            await message.bot.send_message(ADMIN_ID, admin_text, reply_markup=proof_received_admin_kb(user_id))
            sent = True
    except Exception:
        sent = False

    if not sent:
        try:
            await message.bot.send_message(ADMIN_ID, admin_text, reply_markup=proof_received_admin_kb(user_id))
        except Exception:
            pass
        try:
            await message.bot.send_message(OWNER_ID, "Fallback: " + admin_text)
        except Exception:
            pass

    await state.clear()

# Admin actions
@router.callback_query(lambda c: c.data.startswith("admin_"))
async def on_admin_action(callback: types.CallbackQuery):
    parts = callback.data.split("_", 2)
    if len(parts) < 3:
        await callback.answer("Invalid data.", show_alert=True)
        return

    action = parts[1]
    target_user_id = parts[2]
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Not authorized.", show_alert=True)
        return

    try:
        user_id = int(target_user_id)
    except ValueError:
        await callback.answer("Invalid user id.", show_alert=True)
        return

    order = ORDERS.get(user_id)
    # If no order or not pending, treat as not found
    if not order or order.get("status") != "pending":
        # Only back should work after completion; admin actions should fail
        await callback.answer("Order not found", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        return

    if action == "notpaid":
        order["status"] = "not_paid"
        try:
            lang = order.get("lang", "en")
            msg_to_user = "❌ Payment not received. Please pay again and upload a valid proof/screenshot." if lang=="en" else "❌ ክፍያ አልተቀበለም። እባክዎ እንደገና ይክፈሉ እና የክፍያ ማስረጃ ይላኩ።"
            await callback.bot.send_message(user_id, msg_to_user)
        except Exception:
            pass
        await callback.answer("User notified.")
        try:
            # mark on admin message
            await callback.message.edit_text((callback.message.text or "") + "\n\nStatus: NOT PAID")
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        return

    if action == "paid":
        order["status"] = "completed"
        product = PRODUCTS[order["product_index"]]
        file_ref = product.get("file")
        lang = order.get("lang", "en")
        payment_label = PAYMENT_METHODS.get(order.get("payment_method"), {"label": order.get("payment_method")})["label"]

        # deliver product to user (try link/document)
        try:
            if not file_ref:
                user_msg = (
                    "🎉 Congratulations! Your digital product has been delivered.\n\n(Delivery file not set up.)"
                    if lang == "en" else
                    "🎉 እንኳን ደስ አለዎት! ዲጂታል ምርትዎ ተልኳል።\n\n(የማስተላለፊያ ፋይል አልተዘጋጀም)"
                )
                await callback.bot.send_message(user_id, user_msg)
            elif isinstance(file_ref, str) and file_ref.startswith(("http://", "https://")):
                user_msg = (
                    "🎉 Congratulations! Your product is ready:\n"
                    f"{file_ref}\n\n"
                    f"Payment method used: {payment_label}\n\n"
                    f"Join our channel for updates & weekly giveaways:"
                    if lang == "en" else
                    "🎉 እንኳን ደስ አለዎት! ምርትዎ ዝግጁ ነው:\n"
                )
                # send product link + join button
                kb_join = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=("Join" if lang=="en" else "ገና ተቀላቅሉ"), url=JOIN_CHANNEL)]
                ])
                await callback.bot.send_message(user_id,
                                                f"🎉 Congratulations! Your product is ready:\n{file_ref}\n\nPayment method used: {payment_label}",
                                                reply_markup=kb_join)
            elif isinstance(file_ref, str) and os.path.exists(file_ref):
                # local file
                caption = f"🎉 Here is your product. Thanks!\n\nPayment method: {payment_label}"
                kb_join = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=("Join" if lang=="en" else "ገና ተቀላቅሉ"), url=JOIN_CHANNEL)]
                ])
                await callback.bot.send_document(user_id, InputFile(file_ref), caption=caption, reply_markup=kb_join)
            else:
                kb_join = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=("Join" if lang=="en" else "ገና ተቀላቅሉ"), url=JOIN_CHANNEL)]
                ])
                await callback.bot.send_message(user_id, f"🎉 Your product: {file_ref}\n\nPayment method used: {payment_label}\n\nJoin for updates & giveaways:", reply_markup=kb_join)
        except Exception:
            await callback.answer("Could not send product to user (maybe blocked).", show_alert=True)
            try:
                await callback.message.edit_text((callback.message.text or "") + "\n\nStatus: PAID, but delivery failed.")
                await callback.message.edit_reply_markup(reply_markup=None)
            except:
                pass
            return

        # Small admin notification that order completed (per request)
        try:
            comp_msg = f"✅ Order for @{order.get('username','N/A')} (id: {user_id}) marked as COMPLETED."
            await callback.bot.send_message(ADMIN_ID, comp_msg)
            # Also notify owner as fallback
            try:
                await callback.bot.send_message(OWNER_ID, comp_msg)
            except Exception:
                pass
        except Exception:
            pass

        await callback.answer("Product delivered.")
        try:
            await callback.message.edit_text((callback.message.text or "") + "\n\nStatus: PAID and delivered.")
            await callback.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        return

# Generic safe handler (no-op but also enforces "only back works after completion" policy)
@router.callback_query(lambda c: True)
async def generic_callback_handler(callback: types.CallbackQuery):
    data = callback.data or ""
    user_id = callback.from_user.id

    # If this user has a completed order, block most callbacks except navigation/back ones
    user_order = ORDERS.get(user_id)
    if user_order and user_order.get("status") == "completed":
        # allow back navigation callbacks to work (so user can go back to menus)
        allowed_prefixes = ("product_", "digital_", "lang_", "product_2_")
        if not any(data.startswith(p) for p in allowed_prefixes):
            await callback.answer("Order not found", show_alert=True)
            return

    # ignore already-handled prefixes to avoid duplicate processing
    if data.startswith(("product_", "productpay_", "pay_", "done_payment_", "copy_", "admin_", "notion_", "digital_", "notion_")):
        # already handled by specific handlers
        return
    # fallthrough: just ack
    await callback.answer()
