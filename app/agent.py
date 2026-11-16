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
4. The policy the customer needs is not in the excerpts. Say it is not in the policies. Do not invent a rule, a price, or a points redemption rate. A policy that does not mention something has not ruled on it; do not infer a yes or a no from what the excerpts leave out. Do not escalate that question.

Before anything else, write your decision inside <decision></decision>: the step that applies and the policy line or tool result it rests on. The customer never sees the decision block. After it, write the reply to the customer, and never mention the steps in it. Cite the policy path in the reply itself, because the customer cannot see the decision block. Never state an answer and then take it back. A rule written about one thing does not apply to a different thing, however similar.

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
    return DECISION.sub("", text).replace("<decision>", "").strip()


def ask(customer: str) -> dict:
    sources = policies.with_rulebook(policies.retrieve_index(customer))
    calls: list[dict] = []
    agent = Agent(system_prompt=SYSTEM, tools=build_tools(calls))
    started = time.perf_counter()
    result = agent(build_prompt(customer, sources))
    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = result_usage(result)
    return {
        "text": strip_decision(result_text(result)),
        "decision": split_decision(agent.messages),
        "calls": calls,
        "sources": [item["path"] for item in sources],
        "latency_ms": latency_ms,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
    }
