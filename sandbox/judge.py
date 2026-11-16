"""Judge one turn against a schema-2 case.

A case declares what is right. Code checks what is exact:

- tools.required   every listed call happened, with these argument values
- tools.any_of     at least one of these calls happened
- tools.allowed    other tools that may also run; anything else fails
- cite_any         the reply names at least one of these policy files
- facts_from_tool  every tracking number, date, or status phrase in the reply
                   appears in what the tools returned

The LLM judge checks what is meaning, as claims about the reply:

- must_state     each claim must hold
- must_not       each claim must not hold
- trap           the known wrong answer for this case; it must not hold
- packet_facts   claims about the escalation packet; each must hold
"""

from __future__ import annotations

import re

import llm_judge

STATUS_PHRASES = ("in transit", "delivered", "not yet shipped", "out for delivery", "shipped")


def _norm(text: str) -> str:
    flat = str(text).lower().replace("_", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", flat).strip()


def _matches(call: dict, spec: dict) -> bool:
    if call.get("tool") != spec["tool"]:
        return False
    arguments = call.get("arguments") or {}
    return all(_norm(arguments.get(key, "")) == _norm(value) for key, value in spec.get("arguments", {}).items())


def _describe(spec: dict) -> str:
    args = ", ".join(f"{key}={value}" for key, value in spec.get("arguments", {}).items())
    return f"{spec['tool']}({args})"


def invented_tokens(reply: str, tool_text: str) -> list[str]:
    text = _norm(reply)
    known = _norm(tool_text)
    found = []
    for token in re.findall(r"\b1z[a-z0-9]+\b", text):
        if token not in known:
            found.append(token)
    for day in re.findall(r"\b20\d\d-\d\d-\d\d\b", text):
        if day not in known:
            found.append(day)
    for phrase in STATUS_PHRASES:
        if phrase in text and phrase not in known:
            found.append(phrase)
    return found


def tool_failures(case: dict, calls: list[dict]) -> list[str]:
    tools = case.get("tools", {})
    required = tools.get("required", [])
    any_of = tools.get("any_of", [])
    failures = []
    for spec in required:
        if not any(_matches(call, spec) for call in calls):
            failures.append(f"Call {_describe(spec)}")
    if any_of and not any(_matches(call, spec) for spec in any_of for call in calls):
        failures.append("Call one of " + ", ".join(_describe(spec) for spec in any_of))
    permitted = {spec["tool"] for spec in required + any_of} | set(tools.get("allowed", []))
    for name in sorted({call.get("tool") for call in calls} - permitted):
        failures.append(f"Called {name}")
    return failures


def claims_for(case: dict) -> list[dict]:
    claims = []
    for index, text in enumerate(case.get("must_state", []), 1):
        claims.append({"id": f"state{index}", "text": text, "expect": True, "label": "Did not say"})
    for index, text in enumerate(case.get("must_not", []), 1):
        claims.append({"id": f"not{index}", "text": text, "expect": False, "label": "Said"})
    if case.get("trap"):
        claims.append({"id": "trap", "text": case["trap"], "expect": False, "label": "Trap"})
    for index, text in enumerate(case.get("packet_facts", []), 1):
        claims.append({"id": f"packet{index}", "text": text, "expect": True, "label": "Packet missing"})
    return claims


def judge(case: dict, turn: dict, grader) -> dict:
    reply = turn.get("text", "")
    calls = turn.get("calls", [])
    failures = tool_failures(case, calls)

    cites = case.get("cite_any", [])
    flat_reply = reply.replace("\\", "/").lower()
    if cites and not any(path.lower() in flat_reply for path in cites):
        failures.append("Cite " + " or ".join(cites))

    tool_text = llm_judge.tool_results_text(calls)
    if case.get("facts_from_tool"):
        invented = invented_tokens(reply, tool_text)
        if invented:
            failures.append("Stated order facts the tools did not return: " + ", ".join(invented))

    claims = claims_for(case)
    graded = grader.grade(
        case["customer"],
        reply,
        [{"id": claim["id"], "text": claim["text"]} for claim in claims],
        packet=llm_judge.packet_text(calls),
        tool_results=tool_text,
    )
    checks = []
    for claim in claims:
        verdict = graded["verdicts"][claim["id"]]
        ok = verdict["holds"] == claim["expect"]
        checks.append({
            "id": claim["id"],
            "claim": claim["text"],
            "expect": claim["expect"],
            "holds": verdict["holds"],
            "evidence": verdict["evidence"],
        })
        if not ok:
            failures.append(f"{claim['label']}: {claim['text']}")

    return {
        "id": case["id"],
        "outcome": case.get("outcome"),
        "boundary": case.get("boundary"),
        "pass": not failures,
        "failures": failures,
        "checks": checks,
        "judge_input_tokens": graded["input_tokens"],
        "judge_output_tokens": graded["output_tokens"],
        "judge_cost_usd": llm_judge.cost(graded["input_tokens"], graded["output_tokens"]),
        "latency_ms": turn.get("latency_ms"),
        "agent_ms": turn.get("agent_ms"),
        "input_tokens": turn.get("input_tokens"),
        "output_tokens": turn.get("output_tokens"),
        "cost_usd": None,
        "session_id": turn.get("session_id"),
        "sources": turn.get("sources", []),
        "tools": [call.get("tool") for call in calls],
        "calls": calls,
        "decision": turn.get("decision", []),
        "text": reply,
    }


class FixedGrader:
    """A stand-in for the model in offline tests: returns preset verdicts."""

    def __init__(self, verdicts: dict[str, bool]):
        self.verdicts = verdicts

    def grade(self, customer, reply, claims, packet="", tool_results=""):
        return {
            "verdicts": {claim["id"]: {"holds": self.verdicts.get(claim["id"], False), "evidence": ""} for claim in claims},
            "input_tokens": 0,
            "output_tokens": 0,
        }
