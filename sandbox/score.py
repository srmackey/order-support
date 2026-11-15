"""Score one turn of the Trailforge agent against sandbox/cases.json.

A case passes when every required fact is present and every banned move is
absent. Cost is not priced here. The run records tokens and latency.

Usage:
  python score.py
  python score.py --only ship-standard
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKOUT = ROOT.parent
if str(CHECKOUT) not in sys.path:
    sys.path.insert(0, str(CHECKOUT))

CASES = ROOT / "cases.json"
RUNS = ROOT / "runs"

TOOLS = ("lookup_order_status", "check_return_eligibility", "escalate_to_human")
STATUS_PHRASES = ("in transit", "delivered", "not yet shipped", "out for delivery", "shipped")


def load_cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def norm(text: str) -> str:
    flat = text.lower().replace("_", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", flat)


def tool_names(turn: dict) -> list[str]:
    return [call["tool"] for call in turn.get("calls", [])]


def packet_text(turn: dict) -> str:
    chunks = []
    for call in turn.get("calls", []):
        if call["tool"] == "escalate_to_human":
            chunks.append(json.dumps(call.get("arguments", {})))
            chunks.append(json.dumps(call.get("result", {})))
    return norm(" ".join(chunks))


def lookup_result_text(turn: dict) -> str:
    chunks = []
    for call in turn.get("calls", []):
        if call["tool"] == "lookup_order_status":
            chunks.append(json.dumps(call.get("result", {})))
    return norm(" ".join(chunks))


def cites(reply: str, path: str) -> bool:
    return path.lower() in reply.replace("\\", "/").lower()


def has_30_day_window(reply: str) -> bool:
    text = norm(reply)
    return bool(re.search(r"\b30\s+days\b", text)) and "delivery" in text


def gives_7_day_window(reply: str) -> bool:
    text = norm(reply)
    seven = bool(re.search(r"\b(7|seven)\s+days\b", text))
    return seven and not re.search(r"\b30\s+days\b", text)


def names_points_rate(reply: str) -> bool:
    text = norm(reply)
    for count in re.findall(r"\b(\d+)\s+points?\b", text):
        if count != "1":
            return True
    return bool(re.search(r"\bpoints?\s*(needed|required|equal|=)\s*\d+\b", text))


def invented_status(reply: str, source: str) -> bool:
    text = norm(reply)
    known = norm(source)
    for token in re.findall(r"\b1z[a-z0-9]+\b", text):
        if token not in known:
            return True
    for phrase in STATUS_PHRASES:
        if phrase in text and phrase not in known:
            return True
    for day in re.findall(r"\b20\d\d-\d\d-\d\d\b", text):
        if day not in known:
            return True
    return False


def promises_refund(reply: str) -> bool:
    text = norm(reply)
    patterns = (
        r"refund (is|has been|will be) approved",
        r"(i have|i've|we have|we've) refunded",
        r"you will receive (a |the )?\$?220",
        r"we will refund",
        r"i will refund",
        r"refund of \$220 has been",
        r"\b(?:process|processing|approve|grant)\b(?:\s+\S+){0,4}\s+refunds?\b",
        r"\bissue\b(?:\s+\S+){0,3}\s+refunds?\b",
        r"\brefunds?\b(?:\s+\S+){0,4}\s+(?:processed|issued|approved)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            prefix = text[max(0, match.start() - 16):match.start()]
            if re.search(r"\b(not|n't)\s+$", prefix):
                continue
            return True
    return False


def recommended_actions(turn: dict) -> str:
    chunks = []
    for call in turn.get("calls", []):
        if call["tool"] == "escalate_to_human":
            chunks.append(str((call.get("arguments") or {}).get("recommended_action") or ""))
    return " ".join(chunks)


def promises_replacement(reply: str) -> bool:
    text = norm(reply)
    patterns = (
        r"(i|we) will (ship|send) (a |the )?(correct|replacement)",
        r"(sending|shipped) a replacement",
        r"replacement is on the way",
        r"we will replace",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def wrong_standard_price(reply: str) -> bool:
    text = norm(reply)
    return bool(re.search(r"standard\s+(ground\s+)?(shipping\s+)?(is|costs)\s+\$?(12\.95|24\.95|0)\b", text))


def judge(case: dict, turn: dict) -> dict:
    expect = case["expect"]
    reply = turn.get("text", "")
    names = tool_names(turn)
    failures = []

    if case["id"] == "ship-standard":
        if names:
            failures.append("Call a tool")
        if not cites(reply, expect["cite"]):
            failures.append(expect["cite"])
        text = norm(reply)
        if "$5.95" not in reply and "5.95" not in text:
            failures.append("Standard ground is $5.95")
        if not ("free" in text and "75" in text):
            failures.append("It is free on orders over $75")
        if not re.search(r"\b5\s*(to|-)\s*7\b", text) or "business day" not in text:
            failures.append("Standard ground takes 5 to 7 business days")
        if wrong_standard_price(reply):
            failures.append("Name a different standard-ground price")

    elif case["id"] == "order-tf-10482":
        lookups = [call for call in turn.get("calls", []) if call["tool"] == "lookup_order_status"]
        if not lookups:
            failures.append("lookup_order_status")
        elif any(norm(str(call["arguments"].get("order_id", ""))) != "tf-10482" for call in lookups):
            failures.append("order_id TF-10482")
        if any(name != "lookup_order_status" for name in names):
            failures.append("Call check_return_eligibility" if "check_return_eligibility" in names else "Call escalate_to_human")
        if invented_status(reply, lookup_result_text(turn)):
            failures.append("State a delivery status, a tracking number, or an ETA")

    elif case["id"] == "points-redeem":
        text = norm(reply)
        if not (
            "not in the policies" in text
            or "not included in the policies" in text
            or "not available in the polic" in text
        ):
            failures.append("The number of points that buys $10 off is not in the policies")
        if names_points_rate(reply):
            failures.append("Name a number of points that equals $10 off")
        if "escalate_to_human" in names:
            failures.append("Escalate")

    elif case["id"] == "refund-tf-20911":
        escalations = [call for call in turn.get("calls", []) if call["tool"] == "escalate_to_human"]
        if not escalations:
            failures.append("escalate_to_human")
        elif any(norm(str(call["arguments"].get("order_id", ""))) != "tf-20911" for call in escalations):
            failures.append("order_id TF-20911")
        packet = packet_text(turn)
        if "220" not in packet:
            failures.append("The refund requested is $220")
        if "color" not in packet:
            failures.append("The reason is that the color is wrong")
        text = norm(reply)
        if "one business day" not in text and "1 business day" not in text:
            failures.append("A specialist will follow up within one business day")
        action = recommended_actions(turn)
        if promises_refund(reply) or promises_refund(action):
            failures.append("Promise that the refund will be approved")
        if promises_replacement(reply) or promises_replacement(action):
            failures.append("Treat the $220 refund as an automatic replacement under the wrong-item policy")

    elif case["id"] == "return-window":
        if not cites(reply, expect["cite"]):
            failures.append(expect["cite"])
        if not has_30_day_window(reply):
            failures.append("30 days of the delivery date")
        if gives_7_day_window(reply):
            failures.append("The window given is 7 days")

    else:
        failures.append(f"no judge for {case['id']}")

    return {
        "id": case["id"],
        "pass": not failures,
        "failures": failures,
        "latency_ms": turn.get("latency_ms"),
        "input_tokens": turn.get("input_tokens"),
        "output_tokens": turn.get("output_tokens"),
        "cost_usd": None,
        "sources": turn.get("sources", []),
        "tools": names,
        "text": reply,
    }


def write_run(rows: list[dict]) -> Path:
    RUNS.mkdir(exist_ok=True)
    path = RUNS / f"{date.today().isoformat()}.json"
    path.write_text(json.dumps({"date": date.today().isoformat(), "cases": rows}, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    from agent import ask

    cases = load_cases()
    if args.only:
        cases = [case for case in cases if case["id"] == args.only]
        if not cases:
            print(f"no case named {args.only}", file=sys.stderr)
            return 2
    rows = []
    failed = 0
    for case in cases:
        turn = ask(case["customer"])
        row = judge(case, turn)
        rows.append(row)
        mark = "pass" if row["pass"] else "fail"
        if not row["pass"]:
            failed += 1
        print(f"{row['id']}: {mark}")
        if row["failures"]:
            print("  " + "; ".join(row["failures"]))
    path = write_run(rows)
    print(f"wrote {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
