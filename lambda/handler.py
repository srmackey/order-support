"""The three Trailforge tools. Orders and escalation packets live in DynamoDB."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import boto3

import shop

ORDERS = boto3.resource("dynamodb").Table(os.environ["ORDERS_TABLE"])
ESCALATIONS = boto3.resource("dynamodb").Table(os.environ["ESCALATIONS_TABLE"])


def plain(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def order_row(order_id: str) -> tuple[date, dict | None]:
    meta = ORDERS.get_item(Key={"order_id": "_meta"}).get("Item") or {}
    as_of = date.fromisoformat(meta["as_of"])
    item = ORDERS.get_item(Key={"order_id": order_id.strip()}).get("Item")
    if item is None or item.get("order_id") == "_meta":
        return as_of, None
    return as_of, plain(item)


def handler(event, _context):
    tool = event.get("tool")
    arguments = event.get("arguments") or {}
    if tool == "lookup_order_status":
        as_of, order = order_row(arguments.get("order_id") or "")
        return shop.lookup_row(arguments.get("order_id") or "", order, as_of)
    if tool == "check_return_eligibility":
        as_of, order = order_row(arguments.get("order_id") or "")
        return shop.check_return_row(arguments.get("order_id") or "", order, as_of, arguments.get("reason") or "")
    if tool == "escalate_to_human":
        record = shop.escalation_record(arguments, uuid4().hex, datetime.now(timezone.utc).isoformat())
        ESCALATIONS.put_item(Item=record)
        return {"queued": True, "order_id": record["order_id"], "escalation_id": record["escalation_id"]}
    raise ValueError(f"unknown tool {tool}")
