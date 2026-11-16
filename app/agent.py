"""One Trailforge support turn. Sources are retrieved here. The three tools are described in the README."""

from __future__ import annotations

import json
import re
import time

from strands import Agent, tool

import policies
import tools_client

SYSTEM = """You are Trailforge support. Trailforge sells outdoor apparel, footwear, packs, and hardware in the United States and Canada.

The message includes policy excerpts. They are the only policies you may use. When you use one, cite its path exactly, for example kb/02-shipping-policy.md.

Choose one next step. Check them in this order and take the first that fits:
1. An escalation rule in the excerpts applies. Call escalate_to_human. Tell the customer a specialist will follow up within one business day. Do not promise a refund, a replacement, or any other outcome. The amount rule is a refund or compensation above $150, which means more than $150; $150 or less does not escalate on amount alone. A missing order number never delays an escalation: pass an empty order id. The exception rule applies only when the customer asks for an exception to a policy written in the excerpts. A request for something no written policy covers is step 4, even when the customer calls it an exception. When a window has closed and the customer has not asked for one, tell them it closed; do not escalate.
2. The question needs a live order fact (status, tracking, ETA, delivery date, final-sale, or personalized). Call lookup_order_status or check_return_eligibility. Report only what the tool returned. Do not guess. If the customer gave no order number, ask for it.
3. The excerpts answer the question. Answer from them and cite the path. Do not call a tool.
4. The policy the customer needs is not in the excerpts. Say it is not in the policies. Do not invent a rule, a price, or a points redemption rate. A policy that does not mention something has not ruled on it; do not infer a yes or a no from what the excerpts leave out. Do not escalate that question, and do not say a person will follow up on it.

When a policy says only, anything of the kind it lists that it does not list is a no, and that is an answer from the policy, not step 4. A closed list rules only on the kind of thing it lists: a list of shipping methods does not say whether a customer can choose a delivery date, and a list of payment methods does not overrule a different written policy.

A question can have parts. Answer each part from the excerpts where you can, and say a part is not in the policies where it is not.

Before anything else, write your decision inside <decision></decision>. Its first line is exactly this form, alone on its line: step: N | missing: WHAT. N is the step that applies. WHAT is what the policies do not say, in a few words, when step 4 applies to the question or to any part of it, even when another part is answered from the excerpts; otherwise it is none. Write the policy line or tool result the decision rests on on the next line. Examples: step: 4 | missing: whether reward points can be transferred. For a question about the warranty length and about a military discount: step: 3 | missing: whether there is a military discount. The customer never sees the decision block. After it, write the reply to the customer, and never mention the steps in it. Cite the policy path in the reply itself, because the customer cannot see the decision block. Never state an answer and then take it back. A rule written about one thing does not apply to a different thing, however similar.

Tool results include today's date as "today". Use it for any window counted in days, such as the 7 days to report damage.

check_return_eligibility takes the order id, and a reason only when the customer stated one. Do not pass a delivery date. The order record has the date.
lookup_order_status takes the order id only.
escalate_to_human takes the order id, a short summary, the policy paths you used, any tool results you already have (or an empty string), and a recommended next action that does not promise an outcome.
"""


def build_prompt(customer: str, sources: list[dict]) -> str:
    return (
        f"Policy excerpts:\n\n{policies.format_sources(sources)}\n\n"
        f"Customer message:\n{customer}"
    )


def build_tools(calls: list[dict]):
    @tool
    def lookup_order_status(order_id: str) -> str:
        """Look up live status, tracking, ETA, and delivery date for one order. The result includes today's date.

        Args:
            order_id: The order id from the customer, such as TF-10482.
        """

        arguments = {"order_id": order_id}
        result = tools_client.invoke("lookup_order_status", arguments)
        calls.append({"tool": "lookup_order_status", "arguments": arguments, "result": result})
        return json.dumps(result)

    @tool
    def check_return_eligibility(order_id: str, reason: str = "") -> str:
        """Check whether an order can be returned. The delivery date comes from the order record.

        Args:
            order_id: The order id from the customer.
            reason: The customer's stated reason, or an empty string.
        """

        arguments = {"order_id": order_id, "reason": reason}
        result = tools_client.invoke("check_return_eligibility", arguments)
        calls.append({"tool": "check_return_eligibility", "arguments": arguments, "result": result})
        return json.dumps(result)

    @tool
    def escalate_to_human(
        summary: str,
        policy_snippets: str,
        tool_results: str,
        recommended_action: str,
        order_id: str = "",
    ) -> str:
        """Hand the case to a person. Do not promise an outcome.

        Args:
            summary: What the customer asked for.
            policy_snippets: Policy paths already used.
            tool_results: Tool results already obtained, or an empty string.
            recommended_action: What the person should do. Review the claim and leave the money undecided. Example: "Review the wrong-color claim and decide the refund. Do not approve it."
            order_id: The order id. Optional. Leave it empty when the customer gave none; do not wait for it.
        """

        arguments = {
            "order_id": order_id,
            "summary": summary,
            "policy_snippets": policy_snippets,
            "tool_results": tool_results,
            "recommended_action": recommended_action,
        }
        result = tools_client.invoke("escalate_to_human", arguments)
        calls.append({"tool": "escalate_to_human", "arguments": arguments, "result": result})
        return json.dumps(result)

    return [lookup_order_status, check_return_eligibility, escalate_to_human]


def result_text(result) -> str:
    message = getattr(result, "message", None)
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            parts = [block["text"] for block in content if isinstance(block, dict) and block.get("text")]
            if parts:
                return "\n".join(parts)
        if isinstance(content, str):
            return content
    return str(result)


def result_usage(result) -> dict:
    metrics = getattr(result, "metrics", None)
    usage = getattr(metrics, "accumulated_usage", None) or {}
    if not isinstance(usage, dict):
        usage = dict(usage) if usage else {}
    return {
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
    }


DECISION = re.compile(r"<decision>(.*?)</decision>", re.S)


def split_decision(messages: list) -> list[str]:
    """The agent decides in a tagged block before it replies. The block is kept for the record and never sent."""
    decisions = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for block in message.get("content", []):
            if isinstance(block, dict) and block.get("text"):
                decisions += [found.strip() for found in DECISION.findall(block["text"])]
    return decisions


def strip_decision(text: str) -> str:
    return DECISION.sub("", text).replace("<decision>", "").replace("</decision>", "").strip()


def reply_text(text: str) -> str:
    """Only what follows the last decision block goes to the customer.

    The agent sometimes decides, writes a sentence reconsidering, and decides
    again. Text before the final decision is reasoning, not the reply.
    """
    if "</decision>" in text:
        tail = strip_decision(text.rsplit("</decision>", 1)[1])
        if tail:
            return tail
    return strip_decision(text)


NOTE_LINE = re.compile(r"^[\s*_`#>-]*step\s*:\s*(\d)\s*(?:\|\s*missing\s*:\s*(.*?))?[\s*_`]*$", re.I | re.M)
NO_GAP = re.compile(r"^(none|nothing|n/?a|-)?\b", re.I)
SENTENCE_END = re.compile(r"\.(?:\s|$)|\s[—–-]\s")
CITED = re.compile(r"kb/[\w.-]+\.md")


def parse_note(decisions: list[str]) -> dict:
    """The agent's final note line, as code reads it: step: N | missing: WHAT.

    The last line wins, because the agent sometimes revises its decision in the
    same note. WHAT ends at the first sentence break, since the agent often keeps
    writing its reasons on the same line.
    """
    found = [match for text in decisions for match in NOTE_LINE.finditer(text)]
    if not found:
        return {"step": None, "missing": ""}
    last = found[-1]
    missing = SENTENCE_END.split((last.group(2) or "").strip(), maxsplit=1)[0].strip().strip("*_`").strip()
    none = NO_GAP.match(missing)
    if not missing or (none and none.group(1)):
        missing = ""
    return {"step": int(last.group(1)), "missing": missing}


def cited_paths(*texts: str) -> list[str]:
    seen = []
    for text in texts:
        for path in CITED.findall(text.replace("\\", "/")):
            if path not in seen:
                seen.append(path)
    return seen


def record_gap(customer: str, note: dict, reply: str, decisions: list[str]) -> dict | None:
    """A question the policies do not answer leaves a record for the policy owner. Code writes it from the note; the model has no tool for it."""
    if not note["missing"]:
        return None
    arguments = {
        "question": customer,
        "missing": note["missing"],
        "step": note["step"],
        "cited": cited_paths(reply, *decisions),
    }
    result = tools_client.invoke("record_policy_gap", arguments)
    return {**arguments, **result}


FOLLOW_UP = "A specialist will follow up within one business day."
SAYS_FOLLOW_UP = re.compile(r"\b(one|1) business day\b", re.I)


def with_follow_up(text: str, calls: list[dict]) -> str:
    """A customer whose case was queued is always told when a person will reply. Code guarantees it; the prompt only phrases it."""
    queued = any(
        call["tool"] == "escalate_to_human" and isinstance(call.get("result"), dict) and call["result"].get("queued")
        for call in calls
    )
    if not queued or SAYS_FOLLOW_UP.search(text):
        return text
    return f"{text}\n\n{FOLLOW_UP}"


def ask(customer: str) -> dict:
    sources = policies.with_rulebook(policies.retrieve_index(customer))
    calls: list[dict] = []
    agent = Agent(system_prompt=SYSTEM, tools=build_tools(calls))
    started = time.perf_counter()
    result = agent(build_prompt(customer, sources))
    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = result_usage(result)
    text = with_follow_up(reply_text(result_text(result)), calls)
    decisions = split_decision(agent.messages)
    note = parse_note(decisions)
    return {
        "text": text,
        "decision": decisions,
        "note": note,
        "gap": record_gap(customer, note, text, decisions),
        "calls": calls,
        "sources": [item["path"] for item in sources],
        "latency_ms": latency_ms,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
    }
