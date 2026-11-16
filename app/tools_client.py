"""Call the Trailforge tools. The default is the Lambda. TRAILFORGE_TOOLS=local uses orders.json."""

from __future__ import annotations

import json
import os

import shop

FUNCTION = "trailforge-tools"
REGION = "us-east-1"


def invoke(tool: str, arguments: dict) -> dict:
    if os.environ.get("TRAILFORGE_TOOLS") == "local":
        return local(tool, arguments)
    import boto3

    client = boto3.client("lambda", region_name=REGION)
    response = client.invoke(
        FunctionName=FUNCTION,
        Payload=json.dumps({"tool": tool, "arguments": arguments}).encode(),
    )
    body = json.loads(response["Payload"].read())
    if response.get("FunctionError"):
        raise RuntimeError(body)
    return body


def local(tool: str, arguments: dict) -> dict:
    if tool == "lookup_order_status":
        return shop.lookup_order(arguments.get("order_id") or "")
    if tool == "check_return_eligibility":
        return shop.check_return(arguments.get("order_id") or "", arguments.get("reason") or "")
    if tool == "escalate_to_human":
        return {"queued": True, "order_id": arguments.get("order_id") or ""}
    if tool == "record_policy_gap":
        return {"recorded": True, "stored": False}
    raise ValueError(f"unknown tool {tool}")
