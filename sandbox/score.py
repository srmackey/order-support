"""Score the Trailforge agent against a frozen case set.

cases.json is set v1, five cases, judged by the hand-written judge below.
cases-v2.json is schema 2: each case declares what is right, and judge.py
checks it, with the LLM judge in llm_judge.py for claims about meaning.

Usage:
  python score.py
  python score.py --cases cases-v2.json --label v2-local
  python score.py --only ship-standard
  python score.py --runtime <agent runtime arn> --label runtime --price-in 3 --price-out 15
  python score.py --rescore runs/2026-11-15-runtime.json --label runtime-rescored

With --runtime, each case goes to the hosted agent through InvokeAgentRuntime.
Latency is then the client's wall time for the call, and agent_ms is the time
the agent reported inside the runtime. --price-in and --price-out are USD per
million model tokens. Cost covers model tokens only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKOUT = ROOT.parent
APP = CHECKOUT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

CASES = ROOT / "cases.json"
RUNS = ROOT / "runs"

TOOLS = ("lookup_order_status", "check_return_eligibility", "escalate_to_human")
STATUS_PHRASES = ("in transit", "delivered", "not yet shipped", "out for delivery", "shipped")


def load_set(path: Path = CASES) -> dict:
    if not path.is_absolute() and not path.exists():
        path = ROOT / path
    return json.loads(path.read_text(encoding="utf-8"))


def load_cases() -> list[dict]:
    return load_set()["cases"]


def judge_for(case_set: dict):
    """The judge a set declares. Schema 2 grades claims with the LLM judge."""
    if case_set.get("schema") == 2:
        import judge as schema2
        from llm_judge import BedrockJudge

        grader = BedrockJudge()
        return lambda case, turn: schema2.judge(case, turn, grader)
    return judge


def set_meta(path: Path, case_set: dict) -> dict:
    meta = {"set": path.name, "set_frozen": case_set.get("frozen")}
    if case_set.get("schema") == 2:
        import llm_judge

        meta["judge"] = llm_judge.describe()
    return meta


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


NEGATION = re.compile(r"\b(not|no|n't|nothing|neither|nor|without)\b|n't\b")
POLICY_WORD = re.compile(r"\b(polic(y|ies)|excerpts?|documentation)\b")
RATE_WORD = re.compile(r"\b(points?|redeem\w*|redemption|rates?|(that|this) (information|detail))\b")


def says_rate_missing(reply: str) -> bool:
    """One sentence says the redemption rate is not in the policies.

    The sentence carries a negation, names the policies or excerpts, and points
    at the rate or at "that information". Wording is free; the meaning is not.
    """
    text = norm(reply).replace("’", "'").replace("*", "")
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if NEGATION.search(sentence) and POLICY_WORD.search(sentence) and RATE_WORD.search(sentence):
            return True
    return False


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
            prefix = text[max(0, match.start() - 32):match.start()]
            if re.search(r"\b(not|n't)\b(?:\s+\S+){0,2}\s*$", prefix):
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
        if not says_rate_missing(reply):
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
        "agent_ms": turn.get("agent_ms"),
        "input_tokens": turn.get("input_tokens"),
        "output_tokens": turn.get("output_tokens"),
        "cost_usd": None,
        "session_id": turn.get("session_id"),
        "sources": turn.get("sources", []),
        "tools": names,
        "calls": turn.get("calls", []),
        "text": reply,
    }


# These judges read only the reply and the tool names, so a stored row is enough.
TEXT_ONLY = {"ship-standard", "points-redeem", "return-window"}


def rescore(path: Path, label: str, cases_path: Path = CASES) -> int:
    old = json.loads(path.read_text(encoding="utf-8"))
    case_set = load_set(cases_path)
    grade = judge_for(case_set)
    cases = {case["id"]: case for case in case_set["cases"]}
    rows = []
    failed = 0
    for stored in old["cases"]:
        case = cases[stored["id"]]
        calls = stored.get("calls")
        if calls is None and (case_set.get("schema") == 2 or stored["id"] not in TEXT_ONLY):
            row = dict(stored, carried=True)
        else:
            sample = {
                "text": stored["text"],
                "calls": calls if calls is not None else [{"tool": name, "arguments": {}, "result": {}} for name in stored["tools"]],
                "sources": stored.get("sources", []),
            }
            row = grade(case, sample)
            for key in ("latency_ms", "agent_ms", "input_tokens", "output_tokens", "cost_usd", "session_id"):
                row[key] = stored.get(key)
            if calls is None:
                row.pop("calls")
            row["carried"] = False
        rows.append(row)
        if not row["pass"]:
            failed += 1
        mark = "pass" if row["pass"] else "fail"
        print(f"{row['id']}: {mark}{' (carried)' if row['carried'] else ''}")
    meta = {key: value for key, value in old.items() if key not in ("date", "cases")}
    meta.update(set_meta(Path(cases_path), case_set))
    meta["rescored_from"] = path.name
    meta["rescore_note"] = "Same replies, current judge. A carried row keeps its stored verdict because the file has no tool arguments to judge it again."
    out = write_run(rows, label, meta)
    print(f"wrote {out}")
    return 1 if failed else 0


def runtime_asker(arn: str, region: str):
    import boto3

    client = boto3.client("bedrock-agentcore", region_name=region)

    def ask(customer: str) -> dict:
        session_id = f"score-{uuid.uuid4().hex}"
        started = time.perf_counter()
        response = client.invoke_agent_runtime(
            agentRuntimeArn=arn,
            qualifier="DEFAULT",
            runtimeSessionId=session_id,
            contentType="application/json",
            accept="application/json",
            payload=json.dumps({"prompt": customer}).encode("utf-8"),
        )
        body = json.loads(response["response"].read())
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "text": body.get("result", ""),
            "calls": body.get("tools", []),
            "sources": body.get("sources", []),
            "latency_ms": latency_ms,
            "agent_ms": body.get("agent_ms"),
            "input_tokens": body.get("input_tokens"),
            "output_tokens": body.get("output_tokens"),
            "session_id": session_id,
        }

    return ask


def price(row: dict, price_in: float | None, price_out: float | None) -> None:
    if price_in is None or price_out is None:
        return
    if row["input_tokens"] is None or row["output_tokens"] is None:
        return
    row["cost_usd"] = round((row["input_tokens"] * price_in + row["output_tokens"] * price_out) / 1_000_000, 6)


def write_run(rows: list[dict], label: str = "", meta: dict | None = None) -> Path:
    RUNS.mkdir(exist_ok=True)
    stem = date.today().isoformat() + (f"-{label}" if label else "")
    path = RUNS / f"{stem}.json"
    if path.exists():
        print(f"{path} exists. Pass a different --label.", file=sys.stderr)
        raise SystemExit(2)
    record = {"date": date.today().isoformat(), **(meta or {}), "cases": rows}
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--cases", default="cases.json", help="case set file in sandbox/")
    parser.add_argument("--runtime", default="", help="agent runtime ARN; default runs the agent in this process")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--label", default="", help="suffix for the run file name")
    parser.add_argument("--price-in", type=float, default=None, help="USD per million input tokens")
    parser.add_argument("--price-out", type=float, default=None, help="USD per million output tokens")
    parser.add_argument("--price-source", default="", help="where the prices came from")
    parser.add_argument("--rescore", default="", help="judge the replies in a stored run file again; no model call")
    args = parser.parse_args()
    if args.rescore:
        if not args.label:
            print("--rescore needs --label so the original file is kept", file=sys.stderr)
            return 2
        return rescore(Path(args.rescore), args.label, Path(args.cases))
    if args.runtime:
        ask = runtime_asker(args.runtime, args.region)
    else:
        from agent import ask

    cases_path = Path(args.cases)
    case_set = load_set(cases_path)
    grade = judge_for(case_set)
    cases = case_set["cases"]
    if args.only:
        cases = [case for case in cases if case["id"] == args.only]
        if not cases:
            print(f"no case named {args.only}", file=sys.stderr)
            return 2
    rows = []
    failed = 0
    for case in cases:
        turn = ask(case["customer"])
        row = grade(case, turn)
        price(row, args.price_in, args.price_out)
        rows.append(row)
        mark = "pass" if row["pass"] else "fail"
        if not row["pass"]:
            failed += 1
        print(f"{row['id']}: {mark}")
        if row["failures"]:
            print("  " + "; ".join(row["failures"]))
    # The run file is public. Name the runtime, not its ARN, which carries the account id.
    target = f"AgentCore runtime {args.runtime.rsplit('/', 1)[-1]}, DEFAULT endpoint, {args.region}" if args.runtime else "local process"
    meta = {"target": target, **set_meta(cases_path, case_set)}
    if args.price_in is not None and args.price_out is not None:
        meta["cost_basis"] = {
            "covers": "model tokens only",
            "usd_per_million_input": args.price_in,
            "usd_per_million_output": args.price_out,
            "source": args.price_source,
        }
    path = write_run(rows, args.label, meta)
    print(f"{len(rows) - failed} of {len(rows)} passed")
    print(f"wrote {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
