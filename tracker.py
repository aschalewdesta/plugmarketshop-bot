# tracker.py
"""
Tracker module for Plug Market Shop bot (Aiogram v3)
- Stores standardized order records (JSON file).
- Provides `record_order(service, data)` and `record_event(event, payload)` functions.
- Exposes an Aiogram Router with `/report` command for owner/admin to query:
    - /report             -> last 24 hours (rolling)
    - /report today       -> last 24 hours (alias)
    - /report w / week    -> last 7 days
    - /report m / month   -> last 30 days
    - /report YYYY-MM-DD  -> that date (ISO) (e.g. 2025-08-12)
    - /report DD/MM/YYYY  -> that date (e.g. 12/08/2025)
    - /report M/D/YYYY    -> that date (e.g. 9/2/2025)
- Access control: only OWNER_ID and ADMIN_IDS can run /report.
- Important: The tracker tries to accept both direct record_order calls and generic record_event events.
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from aiogram import Router
from aiogram.types import Message
from aiogram import F

# ---------- CONFIG ----------
OWNER_ID = 6781140962
ADMIN_IDS = [6968325481]  # list (you can extend)
TRACKER_FILE = "tracker_orders.json"
# ISO-like format without timezone suffix for storage (UTC)
DATE_FORMAT_ISO = "%Y-%m-%dT%H:%M:%S"

router = Router()
tracker_router = router  # alias to import into main.py

# ---------- In-memory storage ----------
ORDERS: List[Dict[str, Any]] = []  # each order is a normalized dict

# ---------- Persistence ----------
def load_orders() -> None:
    global ORDERS
    try:
        if os.path.exists(TRACKER_FILE):
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                ORDERS = json.load(f)
        else:
            ORDERS = []
    except Exception:
        ORDERS = []

def save_orders() -> None:
    try:
        tmp = TRACKER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ORDERS, f, ensure_ascii=False, indent=2)
        os.replace(tmp, TRACKER_FILE)
    except Exception:
        # best-effort; don't fail application if saving fails
        pass

load_orders()

# ---------- Helpers ----------
def _now_utc_iso() -> str:
    return datetime.utcnow().strftime(DATE_FORMAT_ISO)

def _parse_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, DATE_FORMAT_ISO)
    except Exception:
        # try to accept full ISO with timezone fallback
        try:
            return datetime.fromisoformat(s).replace(tzinfo=None)
        except Exception:
            return None

def _ensure_order_schema(service: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize an incoming order dictionary into a consistent schema.
    Important fields:
      - order_id (str)
      - service (str)
      - subtype (str) optional (e.g. 'buy'/'sell' for usdt)
      - user_id (int)
      - username (str)
      - amount (numeric) primary numeric (USDT amount, coins, stars, ton)
      - currency (str)
      - etb (numeric) ETB amount relevant to the order (total ETB from user or ETB sent)
      - total_etb (numeric) alias for etb
      - status (str): waiting_admin, paid, completed, not_paid, etc
      - created_at (ISO str UTC)
      - completed_at (ISO str UTC) optional
      - extra (dict) optional
    """
    o = dict(data)  # shallow copy
    o.setdefault("service", service)
    # order_id: accept many common keys or generate
    if not o.get("order_id"):
        # try common alternatives
        o["order_id"] = o.get("id") or o.get("orderId") or f"{service}-{_now_utc_iso()}"
    # user fields
    o.setdefault("user_id", o.get("user_id") or o.get("tg_user_id") or None)
    o.setdefault("username", o.get("username") or o.get("tg_username") or "")
    # numeric amount normalization
    # try several possible keys for unit amount
    amount = None
    for k in ("amount", "amount_usd", "coins", "count", "qty"):
        if k in o and o[k] is not None:
            try:
                amount = float(o[k])
                break
            except Exception:
                pass
    o["amount"] = amount if amount is not None else 0.0
    # currency
    o.setdefault("currency", (o.get("currency") or o.get("unit") or "").upper())
    # ETB heuristics
    etb_val = None
    for k in ("etb", "total_etb", "total", "price", "etb_amount"):
        if k in o and o[k] is not None:
            try:
                etb_val = float(o[k])
                break
            except Exception:
                pass
    o["etb"] = etb_val if etb_val is not None else 0.0
    # other normalized keys
    o.setdefault("payment_method", o.get("payment_method") or o.get("pay_method") or "")
    o.setdefault("status", (o.get("status") or "unknown").lower())
    o.setdefault("subtype", (o.get("subtype") or o.get("type") or "").lower())
    o.setdefault("extra", o.get("extra") or {})
    # created_at: accept datetime or string; store as DATE_FORMAT_ISO
    created = o.get("created_at")
    if created:
        if isinstance(created, datetime):
            o["created_at"] = created.strftime(DATE_FORMAT_ISO)
        else:
            # try parse common formats
            parsed = _parse_iso(created) or _try_parse_common_date(created)
            o["created_at"] = parsed.strftime(DATE_FORMAT_ISO) if parsed else _now_utc_iso()
    else:
        o["created_at"] = _now_utc_iso()
    # completed_at normalization if present
    completed = o.get("completed_at")
    if completed:
        if isinstance(completed, datetime):
            o["completed_at"] = completed.strftime(DATE_FORMAT_ISO)
        else:
            parsed = _parse_iso(completed) or _try_parse_common_date(completed)
            o["completed_at"] = parsed.strftime(DATE_FORMAT_ISO) if parsed else None
    else:
        # keep absent unless status is completed and no timestamp provided -> set now
        if o.get("status") == "completed" and not o.get("completed_at"):
            o["completed_at"] = _now_utc_iso()
        else:
            o["completed_at"] = o.get("completed_at")  # may be None

    return o

def _try_parse_common_date(s: str) -> Optional[datetime]:
    # Accept common date strings like "2025-09-03 16:00:00" or "2025-09-03T16:00:00"
    if not s or not isinstance(s, str):
        return None
    # Try several patterns
    patterns = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ]
    for p in patterns:
        try:
            return datetime.strptime(s, p)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

# ---------- Public API: record_order ----------
def record_order(service: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Record an order event directly (service-specific callers).
    Returns the stored normalized order dict.
    """
    try:
        rec = _ensure_order_schema(service, data)
        ORDERS.append(rec)
        save_orders()
        return rec
    except Exception:
        # best-effort fallback
        return {}

# ---------- Public API: record_event ----------
def record_event(event: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Generic event ingestion for services that prefer to emit events instead of full records.
    Recognized events (best-effort mapping):
      - "order_created": payload should contain service, order_id, user_id, amount_usd/amount, total_etb, payment_method, subtype
      - "order_completed": payload should contain service, subtype, order_id, user_id, amount_usd/amount, total_etb, completed_at (optional)
      - "admin_confirmed_payment": admin action (maps to status 'paid')
      - "wallet_sent", "seller_bank_details", "admin_marked_not_paid", etc - recorded as extra events
    The function will translate these into a stored order record or update an existing order if matching order_id exists.
    """
    try:
        ev = (event or "").lower()
        data = dict(payload or {})
        svc = (data.get("service") or data.get("svc") or "unknown").lower()

        # If order_id present try to find and update existing order
        order_id = data.get("order_id") or data.get("id") or data.get("orderId")
        if order_id:
            # try update existing
            for o in ORDERS:
                if str(o.get("order_id")) == str(order_id):
                    # update fields smartly
                    if ev == "order_completed" or data.get("status") == "completed":
                        o["status"] = "completed"
                        comp_at = data.get("completed_at") or data.get("time") or _now_utc_iso()
                        if isinstance(comp_at, datetime):
                            o["completed_at"] = comp_at.strftime(DATE_FORMAT_ISO)
                        else:
                            parsed = _parse_iso(comp_at) or _try_parse_common_date(str(comp_at))
                            o["completed_at"] = parsed.strftime(DATE_FORMAT_ISO) if parsed else _now_utc_iso()
                        # fill etb/amount if present
                        if "total_etb" in data:
                            try:
                                o["etb"] = float(data["total_etb"])
                            except Exception:
                                pass
                        if "amount_usd" in data or "amount" in data:
                            try:
                                a = data.get("amount_usd", data.get("amount"))
                                o["amount"] = float(a) if a is not None else o.get("amount", 0.0)
                            except Exception:
                                pass
                    elif ev in ("admin_confirmed_payment", "admin_confirmed"):
                        o["status"] = "paid"
                    elif ev in ("admin_marked_not_paid", "not_paid"):
                        o["status"] = "not_paid"
                    # merge extra
                    extra = o.get("extra", {})
                    extra.update({k: v for k, v in data.items() if k not in o})
                    o["extra"] = extra
                    save_orders()
                    return o

        # No existing order found — create a new normalized order depending on event type
        if ev == "order_created":
            payload_to_store = {
                "order_id": order_id or (f"{svc}-{_now_utc_iso()}"),
                "service": svc,
                "subtype": (data.get("subtype") or data.get("type") or "").lower(),
                "user_id": data.get("user_id") or data.get("user"),
                "username": data.get("username") or data.get("tg_username") or "",
                "amount": _safe_float(data.get("amount_usd") or data.get("amount") or data.get("recv_usdt") or 0.0),
                "currency": (data.get("currency") or "").upper(),
                "etb": _safe_float(data.get("total_etb") or data.get("etb") or data.get("total") or 0.0),
                "payment_method": data.get("payment_method") or data.get("pay_method") or "",
                "status": (data.get("status") or "waiting_admin"),
                "created_at": data.get("created_at") or data.get("time") or _now_utc_iso(),
                "extra": {k: v for k, v in data.items() if k not in ("order_id", "service", "subtype", "user_id", "username", "amount", "amount_usd", "total_etb", "etb", "payment_method", "status", "created_at", "time")}
            }
            rec = _ensure_order_schema(svc, payload_to_store)
            ORDERS.append(rec)
            save_orders()
            return rec

        if ev == "order_completed":
            # create a finished order record
            payload_to_store = {
                "order_id": order_id or (f"{svc}-completed-{_now_utc_iso()}"),
                "service": svc,
                "subtype": (data.get("subtype") or data.get("type") or "").lower(),
                "user_id": data.get("user_id") or data.get("user"),
                "username": data.get("username") or "",
                "amount": _safe_float(data.get("amount_usd") or data.get("amount") or 0.0),
                "currency": (data.get("currency") or "").upper(),
                "etb": _safe_float(data.get("total_etb") or data.get("etb") or data.get("total") or 0.0),
                "payment_method": data.get("payment_method") or data.get("pay_method") or "",
                "status": "completed",
                "created_at": data.get("created_at") or data.get("time") or _now_utc_iso(),
                "completed_at": data.get("completed_at") or data.get("time") or _now_utc_iso(),
                "extra": {k: v for k, v in data.items() if k not in ("order_id", "service", "subtype", "user_id", "username", "amount", "amount_usd", "total_etb", "etb", "payment_method", "status", "created_at", "completed_at", "time")}
            }
            rec = _ensure_order_schema(svc, payload_to_store)
            ORDERS.append(rec)
            save_orders()
            return rec

        # generic fallback: record as a generic event record
        payload_to_store = {
            "order_id": order_id or f"{svc}-evt-{_now_utc_iso()}",
            "service": svc,
            "subtype": ev,
            "user_id": data.get("user_id") or data.get("user"),
            "username": data.get("username") or "",
            "amount": _safe_float(data.get("amount") or data.get("amount_usd") or 0.0),
            "currency": (data.get("currency") or "").upper(),
            "etb": _safe_float(data.get("total_etb") or data.get("etb") or 0.0),
            "payment_method": data.get("payment_method") or "",
            "status": data.get("status") or "unknown",
            "created_at": data.get("time") or data.get("created_at") or _now_utc_iso(),
            "extra": data
        }
        rec = _ensure_order_schema(svc, payload_to_store)
        ORDERS.append(rec)
        save_orders()
        return rec
    except Exception:
        return None

def _safe_float(v) -> float:
    try:
        return float(v) if v is not None and v != "" else 0.0
    except Exception:
        return 0.0

# ---------- Query utils ----------
def get_orders_in_range(start_dt: datetime, end_dt: datetime, only_completed: bool = True) -> List[Dict[str, Any]]:
    """
    Return orders where the relevant timestamp (completed_at if present, otherwise created_at)
    is >= start_dt and < end_dt. Use naive UTC datetimes.
    If only_completed is True, only include orders whose status == 'completed'.
    """
    res: List[Dict[str, Any]] = []
    for o in ORDERS:
        # prefer completed_at if present for reporting, otherwise created_at
        tstamp = o.get("completed_at") or o.get("created_at")
        if not tstamp:
            continue
        try:
            ts = _parse_iso(tstamp) or _try_parse_common_date(tstamp)
        except Exception:
            continue
        if not ts:
            continue
        if ts >= start_dt and ts < end_dt:
            if only_completed:
                if (o.get("status") or "").lower() == "completed":
                    res.append(o)
            else:
                res.append(o)
    # sort ascending by timestamp
    res.sort(key=lambda x: x.get("completed_at") or x.get("created_at"))
    return res

# ---------- Business logic: summary builder ----------
def _fmt_num(n: float, decimals: int = 2) -> str:
    try:
        if decimals == 0:
            return f"{int(round(n)):,}"
        fmt = f"{{:,.{decimals}f}}"
        return fmt.format(n)
    except Exception:
        return str(n)

def summarize_orders(orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create the professional summary expected by the owner.
    The summary includes:
      - USDT: sent (bot->user), received (user->bot) and ETB sent/received breakdown
      - Star, TON: delivered counts and ETB received
      - Alibaba orders: count and ETB
      - Telegram premium: count and ETB
      - TikTok coins: coins delivered and ETB
      - Totals: total ETB received & total ETB sent
    Note: Heuristics used across services (service name, subtype, currency, etc).

    IMPORTANT CHANGE:
      - Total ETB received is calculated as the sum of ETB for all completed orders EXCEPT USDT 'sell' subtype
        (because USDT 'sell' means bot paid ETB to user — an ETB SENT).
      - Total ETB sent is the sum of ETB for USDT 'sell' completed orders.
      This matches your rule: "we sent money only for selling usdt, from other service we recieved only."
    """
    s = {
        "usdt_sent_usd": 0.0,     # bot sent USDT to buyers (users bought from bot)
        "usdt_received_usd": 0.0, # bot received USDT from sellers (users sold to bot)
        "etb_received": 0.0,      # ETB coming into bot (users paid to bot)
        "etb_sent": 0.0,          # ETB sent by bot to users (only for usdt sell)
        "stars_sent": 0.0,
        "stars_etb": 0.0,
        "ton_sent": 0.0,
        "ton_etb": 0.0,
        "alibaba_count": 0,
        "alibaba_etb": 0.0,
        "telegram_count": 0,
        "telegram_etb": 0.0,
        "tiktok_coins": 0.0,
        "tiktok_etb": 0.0,
        "orders_count": len(orders),
        "per_service": {}
    }

    def _svc_add(svc, key, val):
        svc = svc or "unknown"
        ps = s["per_service"].setdefault(svc, {})
        ps[key] = ps.get(key, 0) + val

    # iterate and fill per-service and totals according to the rule
    for o in orders:
        svc = (o.get("service") or "").lower()
        subtype = (o.get("subtype") or "").lower()
        amount = _safe_float(o.get("amount") or 0.0)
        etb = _safe_float(o.get("etb") or 0.0)
        currency = (o.get("currency") or "").upper()
        status = (o.get("status") or "").lower()

        # For completed orders only (orders list passed to this function should already be filtered),
        # decide whether ETB is incoming or outgoing. According to the user's rule, the bot only sends ETB
        # for USDT 'sell' type. All other services are ETB received.
        if svc == "usdt" or currency == "USDT":
            if subtype == "buy":
                # user bought USDT from bot => bot sent USDT, user paid ETB to bot
                recv_usdt = _safe_float(o.get("recv_usdt") or o.get("amount") or amount)
                s["usdt_sent_usd"] += recv_usdt
                s["etb_received"] += etb
                _svc_add("usdt", "sent_usd", recv_usdt)
                _svc_add("usdt", "etb_received", etb)
            elif subtype == "sell":
                # user sold USDT to bot => bot received USDT and paid ETB to user (ETB sent)
                recv_usdt = _safe_float(o.get("recv_usdt") or o.get("amount") or amount)
                s["usdt_received_usd"] += recv_usdt
                s["etb_sent"] += etb
                _svc_add("usdt", "received_usd", recv_usdt)
                _svc_add("usdt", "etb_sent", etb)
            else:
                # If subtype unknown: decide by presence of etb and other hints
                # Default: consider ETB as received (income) unless there's a clear 'sell' marker
                s["etb_received"] += etb
                _svc_add("usdt", "etb_received", etb)

        elif svc in ("star", "stars", "star_ton", "star_ton.py") or currency in ("STAR", "STARS"):
            s["stars_sent"] += amount
            s["stars_etb"] += etb
            _svc_add("stars", "sent", amount)
            _svc_add("stars", "etb", etb)
            # these orders contribute to ETB received:
            s["etb_received"] += etb

        elif svc in ("ton", "tons", "star_ton", "star_ton.py") or currency in ("TON",):
            s["ton_sent"] += amount
            s["ton_etb"] += etb
            _svc_add("ton", "sent", amount)
            _svc_add("ton", "etb", etb)
            s["etb_received"] += etb

        elif svc in ("telegram_premium", "premium", "telegram") or "telegram" in svc:
            s["telegram_count"] += 1
            s["telegram_etb"] += etb
            _svc_add("telegram", "count", 1)
            _svc_add("telegram", "etb", etb)
            s["etb_received"] += etb

        elif svc in ("tiktok", "tiktok.py", "tiktok_coins", "tiktok_coin") or currency in ("TIKTOK", "COIN", "COINS"):
            s["tiktok_coins"] += amount
            s["tiktok_etb"] += etb
            _svc_add("tiktok", "coins", amount)
            _svc_add("tiktok", "etb", etb)
            s["etb_received"] += etb

        elif svc in ("alibaba", "aliexpress", "alibaba_orders", "alibaba_order"):
            s["alibaba_count"] += 1
            s["alibaba_etb"] += etb
            _svc_add("alibaba", "count", 1)
            _svc_add("alibaba", "etb", etb)
            s["etb_received"] += etb

        else:
            # Unknown service: assume ETB is income (user paid the bot), unless there are clear markers
            s["etb_received"] += etb
            _svc_add(svc or "other", "etb", etb)

    # Final totals: as per user's rule, ETB sent is only from USDT sell orders; ETB received is everything else
    s["total_etb_received"] = round(s["etb_received"], 2)
    s["total_etb_sent"] = round(s["etb_sent"], 2)

    # Round & format other numeric fields
    s["etb_received"] = round(s["etb_received"], 2)
    s["etb_sent"] = round(s["etb_sent"], 2)
    s["usdt_sent_usd"] = round(s["usdt_sent_usd"], 6)
    s["usdt_received_usd"] = round(s["usdt_received_usd"], 6)
    s["stars_sent"] = round(s["stars_sent"], 6)
    s["stars_etb"] = round(s["stars_etb"], 2)
    s["ton_sent"] = round(s["ton_sent"], 6)
    s["ton_etb"] = round(s["ton_etb"], 2)
    s["alibaba_etb"] = round(s["alibaba_etb"], 2)
    s["telegram_etb"] = round(s["telegram_etb"], 2)
    s["tiktok_etb"] = round(s["tiktok_etb"], 2)

    return s

# ---------- Report formatter ----------
def _build_report_text(summary: Dict[str, Any], title: str) -> str:
    """
    Build a concise, professional Markdown-ready report string with icons.
    """
    lines = []
    lines.append(f"*{title}*")
    lines.append("")
    # USDT block
    lines.append("💵 *USDT*")
    lines.append(f"  • 🔗 Sent (to buyers): `{_fmt_num(summary['usdt_sent_usd'], 6)}` USDT")
    lines.append(f"  • 🔗 Received (from sellers): `{_fmt_num(summary['usdt_received_usd'], 6)}` USDT")
    lines.append(f"  • 💸 ETB received (from buys & other services): `{_fmt_num(summary['per_service'].get('usdt', {}).get('etb_received', summary.get('etb_received', 0.0)), 2)}` ETB")
    lines.append(f"  • 💸 ETB sent (for sells): `{_fmt_num(summary['per_service'].get('usdt', {}).get('etb_sent', summary.get('etb_sent', 0.0)), 2)}` ETB")
    lines.append("")

    # Stars
    lines.append("⭐ *Star*")
    lines.append(f"  • ⭐ Delivered: `{_fmt_num(summary['stars_sent'], 0)}`")
    lines.append(f"  • 💸 ETB received: `{_fmt_num(summary['stars_etb'], 2)}` ETB")
    lines.append("")

    # TON
    lines.append("⚡ *TON*")
    lines.append(f"  • ⚡ Delivered: `{_fmt_num(summary['ton_sent'], 0)}`")
    lines.append(f"  • 💸 ETB received: `{_fmt_num(summary['ton_etb'], 2)}` ETB")
    lines.append("")

    # Alibaba
    lines.append("🛒 *AliExpress / Alibaba*")
    lines.append(f"  • 📦 Orders: `{summary['alibaba_count']}`")
    lines.append(f"  • 💸 ETB received: `{_fmt_num(summary['alibaba_etb'], 2)}` ETB")
    lines.append("")

    # Telegram Premium
    lines.append("💎 *Telegram Premium*")
    lines.append(f"  • 👥 Subscriptions: `{summary['telegram_count']}`")
    lines.append(f"  • 💸 ETB received: `{_fmt_num(summary['telegram_etb'], 2)}` ETB")
    lines.append("")

    # TikTok
    lines.append("🎵 *TikTok Coins*")
    lines.append(f"  • 🪙 Coins sold/delivered: `{_fmt_num(summary['tiktok_coins'], 0)}`")
    lines.append(f"  • 💸 ETB received: `{_fmt_num(summary['tiktok_etb'], 2)}` ETB")
    lines.append("")

    # Totals
    lines.append("📌 *TOTALS*")
    lines.append(f"  • ✅ Total ETB received: `{_fmt_num(summary['total_etb_received'], 2)}` ETB")
    lines.append(f"  • ❗ Total ETB sent: `{_fmt_num(summary['total_etb_sent'], 2)}` ETB")
    lines.append(f"  • 🧾 Orders counted: `{summary.get('orders_count', 0)}`")
    lines.append("")

    return "\n".join(lines)

# ---------- Command handlers ----------
@router.message(F.text.startswith("/report"))
async def cmd_report(message: Message):
    """
    Handle /report variants:
      /report
      /report today
      /report w | week
      /report m | month
      /report YYYY-MM-DD or DD/MM/YYYY or M/D/YYYY
    """
    user_id = message.from_user.id
    if user_id != OWNER_ID and user_id not in ADMIN_IDS:
        await message.reply("❌ You are not authorized to use this command.")
        return

    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    now = datetime.utcnow()
    if not arg or arg in ("today",):
        end_dt = now
        start_dt = now - timedelta(days=1)
        title = f"Daily Report ({now.strftime('%Y-%m-%d')})"
    elif arg in ("w", "week", "lastweek"):
        end_dt = now
        start_dt = now - timedelta(days=7)
        title = f"7-day Report ending {now.strftime('%Y-%m-%d')}"
    elif arg in ("m", "month", "lastmonth"):
        end_dt = now
        start_dt = now - timedelta(days=30)
        title = f"30-day Report ending {now.strftime('%Y-%m-%d')}"
    else:
        # try to parse as single date in many formats
        dt = None
        # accept YYYY-MM-DD or YYYY/MM/DD
        try:
            dt = datetime.strptime(arg, "%Y-%m-%d")
        except Exception:
            try:
                dt = datetime.strptime(arg, "%Y/%m/%d")
            except Exception:
                dt = _try_parse_common_date(arg)
        if not dt:
            await message.reply("Invalid date or option. Use `/report`, `/report w`, `/report m`, or `/report YYYY-MM-DD`.", parse_mode="Markdown")
            return
        start_dt = datetime(year=dt.year, month=dt.month, day=dt.day)
        end_dt = start_dt + timedelta(days=1)
        title = f"Report: {start_dt.strftime('%Y-%m-%d')}"

    # Get completed orders in range (use completed_at where possible)
    orders = get_orders_in_range(start_dt, end_dt, only_completed=True)
    summary = summarize_orders(orders)
    text_report = _build_report_text(summary, title)

    # Split into chunks safe for Telegram (avoid cutting Markdown)
    MAX_LEN = 3900
    chunks = []
    if len(text_report) <= MAX_LEN:
        chunks = [text_report]
    else:
        lines = text_report.splitlines()
        cur = []
        cur_len = 0
        for ln in lines:
            lnl = len(ln) + 1
            if cur_len + lnl > MAX_LEN:
                chunks.append("\n".join(cur))
                cur = [ln]
                cur_len = lnl
            else:
                cur.append(ln)
                cur_len += lnl
        if cur:
            chunks.append("\n".join(cur))

    for c in chunks:
        try:
            await message.reply(c, parse_mode="Markdown")
        except Exception:
            try:
                await message.reply(c)
            except Exception:
                # if even reply fails, attempt send_message to owner
                try:
                    await message.bot.send_message(chat_id=OWNER_ID, text=c)
                except Exception:
                    pass

# ---------- Utility search ----------
def find_order_by_id(order_id: str) -> Optional[Dict[str, Any]]:
    for o in ORDERS:
        if str(o.get("order_id")) == str(order_id):
            return o
    return None

# ---------- If someone imports tracker.record (compat) ----------
# Provide backward-compatible aliases
def record(service_or_payload, maybe_payload=None):
    """
    Compatibility helper:
      - record_order(service, data)
      - record_event(event, payload) if first arg looks like event string and second arg dict.
    """
    if isinstance(service_or_payload, str) and isinstance(maybe_payload, dict):
        # ambiguous: treat as record_order if maybe_payload contains user/order keys OR as record_event
        # Heuristics: if maybe_payload contains 'service' or 'order_id' treat as order; else if first arg contains '_' treat as event
        if "service" in maybe_payload or "order_id" in maybe_payload or service_or_payload.lower().startswith("usdt") or "/" in service_or_payload:
            return record_order(service_or_payload, maybe_payload)
        else:
            return record_event(service_or_payload, maybe_payload)
    elif isinstance(service_or_payload, dict) and maybe_payload is None:
        # call record_event generic with payload only
        return record_event("event", service_or_payload)
    else:
        return None

# expose functions
__all__ = [
    "tracker_router", "router",
    "record_order", "record_event", "get_orders_in_range",
    "summarize_orders", "find_order_by_id", "record"
]
