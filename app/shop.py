"""Order records and the return rule. The clock is the as_of date in orders.json."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ORDERS = ROOT / "orders.json"
RETURN_DAYS = 30


def load() -> tuple[date, dict[str, dict]]:
    data = json.loads(ORDERS.read_text(encoding="utf-8"))
    rows = {row["order_id"]: row for row in data["orders"]}
    return date.fromisoformat(data["as_of"]), rows


def lookup_row(order_id: str, order: dict | None, as_of: date) -> dict:
    """Every result carries today, so the agent can count days without guessing the date."""
    if order is None:
        return {"found": False, "order_id": order_id, "today": as_of.isoformat()}
    return {
        "today": as_of.isoformat(),
        "found": True,
        "order_id": order["order_id"],
        "status": order["status"],
        "tracking": order.get("tracking"),
        "eta": order.get("eta"),
        "delivered_on": order.get("delivered_on"),
        "total_usd": order.get("total_usd"),
        "items": order.get("items", []),
    }


def lookup_order(order_id: str) -> dict:
    as_of, rows = load()
    key = order_id.strip()
    return lookup_row(key, rows.get(key), as_of)


def check_return_row(order_id: str, order: dict | None, as_of: date, reason: str = "") -> dict:
    result = check_return_verdict(order_id, order, as_of, reason)
    return {"today": as_of.isoformat(), **result}


def check_return_verdict(order_id: str, order: dict | None, as_of: date, reason: str = "") -> dict:
    if order is None:
        return {"order_id": order_id, "eligible": False, "reason": "No order with that id."}
    items = order.get("items") or []
    blocked = (
        ("personalized", "Personalized items cannot be returned."),
        ("final_sale", "Final-sale items cannot be returned."),
        ("gift_card", "Gift cards cannot be returned."),
    )
    for flag, message in blocked:
        if any(item.get(flag) for item in items):
            return {"order_id": order_id, "eligible": False, "reason": message}
    delivered = order.get("delivered_on")
    if not delivered:
        return {
            "order_id": order_id,
            "eligible": False,
            "reason": "The order has not been delivered. The 30-day window starts on the delivery date.",
        }
    delivered_on = date.fromisoformat(delivered)
    closes = delivered_on + timedelta(days=RETURN_DAYS)
    if as_of > closes:
        return {
            "order_id": order_id,
            "eligible": False,
            "reason": f"The 30-day window closed on {closes.isoformat()}.",
        }
    result = {
        "order_id": order_id,
        "eligible": True,
        "reason": "Inside 30 days of delivery. The item still has to be unused and in its original packaging.",
        "delivered_on": delivered,
        "window_closes": closes.isoformat(),
    }
    if reason.strip():
        result["customer_reason"] = reason.strip()
    return result


def check_return(order_id: str, reason: str = "") -> dict:
    as_of, rows = load()
    key = order_id.strip()
    return check_return_row(key, rows.get(key), as_of, reason)


def escalation_record(arguments: dict, escalation_id: str, created_at: str) -> dict:
    return {
        "escalation_id": escalation_id,
        "order_id": arguments.get("order_id") or "",
        "summary": arguments.get("summary") or "",
        "policy_snippets": arguments.get("policy_snippets") or "",
        "tool_results": arguments.get("tool_results") or "",
        "recommended_action": arguments.get("recommended_action") or "",
        "created_at": created_at,
    }
