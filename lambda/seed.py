"""Copy orders.json into the trailforge-orders table. Run from the checkout."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
TABLE = os.environ.get("ORDERS_TABLE", "trailforge-orders")


def item(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: item(inner) for key, inner in value.items() if inner is not None}
    if isinstance(value, list):
        return [item(inner) for inner in value]
    return value


def main() -> None:
    data = json.loads((ROOT / "orders.json").read_text(encoding="utf-8"))
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    table.put_item(Item={"order_id": "_meta", "as_of": data["as_of"]})
    for row in data["orders"]:
        table.put_item(Item=item(row))
    print(f"seeded {len(data['orders'])} orders into {TABLE}")


if __name__ == "__main__":
    main()
