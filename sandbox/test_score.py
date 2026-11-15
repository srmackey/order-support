"""The judge, without a model. Run from the checkout: python sandbox/test_score.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKOUT = ROOT.parent
sys.path.insert(0, str(CHECKOUT / "app"))
sys.path.insert(0, str(ROOT))

import policies
import shop
from score import judge, load_cases

CASES = {case["id"]: case for case in load_cases()}


def turn(text, calls=None, sources=None):
    return {"text": text, "calls": calls or [], "sources": sources or [], "latency_ms": 1}


def expect_pass(case_id, sample):
    row = judge(CASES[case_id], sample)
    if not row["pass"]:
        raise SystemExit(f"{case_id} should pass: {row['failures']}")


def expect_fail(case_id, sample, needle):
    row = judge(CASES[case_id], sample)
    if row["pass"] or not any(needle in item for item in row["failures"]):
        raise SystemExit(f"{case_id} should fail on {needle}: {row['failures']}")


def test_escalation_record():
    record = shop.escalation_record(
        {
            "order_id": "TF-20911",
            "summary": "Refund of $220 because the color is wrong",
            "policy_snippets": "kb/04-escalation-guidelines.md",
            "tool_results": "",
            "recommended_action": "Review the refund request",
        },
        "abc",
        "2026-11-14T00:00:00+00:00",
    )
    if record["escalation_id"] != "abc" or "220" not in record["summary"] or "color" not in record["summary"]:
        raise SystemExit(f"escalation record: {record}")


def test_shop():
    found = shop.lookup_order("TF-10482")
    if found["status"] != "in_transit" or found["tracking"] != "1ZTRF10482":
        raise SystemExit(f"lookup: {found}")
    missing = shop.lookup_order("TF-00000")
    if missing["found"]:
        raise SystemExit("missing order was found")
    early = shop.check_return("TF-10482")
    if early["eligible"]:
        raise SystemExit("in-transit order was eligible")
    open_return = shop.check_return("TF-20911", "color is wrong")
    if not open_return["eligible"] or open_return["customer_reason"] != "color is wrong":
        raise SystemExit(f"open return: {open_return}")
    closed = shop.check_return("TF-30001")
    if closed["eligible"]:
        raise SystemExit("old order was eligible")
    final = shop.check_return("TF-30002")
    if final["eligible"] or "Final-sale" not in final["reason"]:
        raise SystemExit(f"final sale: {final}")


def test_source_path():
    hit = {"location": {"s3Location": {"uri": "s3://example/kb/02-shipping-policy.md"}}}
    if policies.source_path(hit) != "kb/02-shipping-policy.md":
        raise SystemExit(f"source path: {policies.source_path(hit)}")
    https = {
        "location": {"s3Location": {"uri": "https://example.s3.amazonaws.com/kb/02-shipping-policy.md"}},
        "documentId": "s3://example/kb/02-shipping-policy.md",
    }
    if policies.source_path(https) != "kb/02-shipping-policy.md":
        raise SystemExit(f"https path: {policies.source_path(https)}")
    titled = {"metadata": {"_source_uri": "s3://example/kb/09-account-faq.md"}}
    if policies.source_path(titled) != "kb/09-account-faq.md":
        raise SystemExit(f"source uri: {policies.source_path(titled)}")
    labeled = {"metadata": {"x-amz-bedrock-kb-source-uri": "s3://example/kb/01-return-policy.md"}}
    if policies.source_path(labeled) != "kb/01-return-policy.md":
        raise SystemExit(f"metadata path: {policies.source_path(labeled)}")
    if policies.source_path({"location": {}}) is not None:
        raise SystemExit("empty location should not invent a path")


def test_retrieve():
    ship = policies.retrieve("How much is standard shipping, and when is it free?")
    if not ship or ship[0]["path"] != "kb/02-shipping-policy.md":
        raise SystemExit(f"shipping retrieve: {[item['path'] for item in ship]}")
    window = [item["path"] for item in policies.retrieve(
        "I changed my mind about a jacket that was delivered last week. How long do I have to return it?"
    )]
    if "kb/01-return-policy.md" not in window:
        raise SystemExit(f"return retrieve: {window}")
    points = [item["path"] for item in policies.retrieve("How many points do I need for $10 off?")]
    if "kb/09-account-faq.md" not in points:
        raise SystemExit(f"points retrieve: {points}")


def test_judge():
    expect_pass(
        "ship-standard",
        turn("Standard ground is $5.95, free on orders over $75, and takes 5 to 7 business days. Source: kb/02-shipping-policy.md"),
    )
    expect_fail(
        "ship-standard",
        turn("Standard ground is $5.95.", calls=[{"tool": "lookup_order_status", "arguments": {"order_id": "x"}, "result": {}}]),
        "Call a tool",
    )
    expect_pass(
        "order-tf-10482",
        turn(
            "Order TF-10482 is in transit. Tracking 1ZTRF10482. ETA 2026-11-18.",
            calls=[{
                "tool": "lookup_order_status",
                "arguments": {"order_id": "TF-10482"},
                "result": {"status": "in_transit", "tracking": "1ZTRF10482", "eta": "2026-11-18"},
            }],
        ),
    )
    expect_fail(
        "order-tf-10482",
        turn("It is delivered.", calls=[{
            "tool": "lookup_order_status",
            "arguments": {"order_id": "TF-10482"},
            "result": {"status": "in_transit", "tracking": "1ZTRF10482"},
        }]),
        "State a delivery status",
    )
    expect_fail("order-tf-10482", turn("I don't know yet."), "lookup_order_status")
    expect_pass(
        "points-redeem",
        turn("You earn 1 point per dollar. The number of points that buys $10 off is not in the policies."),
    )
    expect_pass(
        "points-redeem",
        turn("The specific redemption rate is not included in the policies available to me. You earn 1 point per dollar."),
    )
    expect_pass(
        "points-redeem",
        turn(
            "That information isn't available in the policies I have access to. You earn **1 point per dollar spent**, "
            "but the specific redemption rates (such as how many points equal $10 off) are not included in the policy excerpts."
        ),
    )
    expect_pass(
        "points-redeem",
        turn("That information isn’t in the policies. Points can be redeemed for discounts."),
    )
    expect_fail(
        "points-redeem",
        turn("You need 100 points for $10 off. That rate is not in the policies."),
        "Name a number of points",
    )
    expect_fail(
        "points-redeem",
        turn("Points can be redeemed for discounts on future orders. Check your account dashboard."),
        "is not in the policies",
    )
    expect_fail(
        "points-redeem",
        turn("Chat isn't covered in the policies. You earn 1 point per dollar."),
        "is not in the policies",
    )
    expect_fail(
        "points-redeem",
        turn("The redemption rate is listed in the policies. Ask support for details."),
        "is not in the policies",
    )
    expect_pass(
        "refund-tf-20911",
        turn(
            "A specialist will follow up within one business day. I cannot promise the refund.",
            calls=[{
                "tool": "escalate_to_human",
                "arguments": {
                    "order_id": "TF-20911",
                    "summary": "Customer wants $220 back because the color is wrong.",
                    "policy_snippets": "kb/04-escalation-guidelines.md",
                    "tool_results": "",
                    "recommended_action": "Review the $220 refund. Do not promise it.",
                },
                "result": {"queued": True},
            }],
        ),
    )
    expect_fail(
        "refund-tf-20911",
        turn("We will refund you $220 and ship the correct jacket."),
        "escalate_to_human",
    )
    expect_fail(
        "refund-tf-20911",
        turn(
            "A specialist will follow up within one business day. I cannot promise the refund.",
            calls=[{
                "tool": "escalate_to_human",
                "arguments": {
                    "order_id": "TF-20911",
                    "summary": "Customer wants $220 back because the color is wrong.",
                    "policy_snippets": "kb/04-escalation-guidelines.md",
                    "tool_results": "",
                    "recommended_action": "Verify the claim, issue a prepaid return label, and process a full refund of $220.",
                },
                "result": {"queued": True},
            }],
        ),
        "Promise that the refund will be approved",
    )
    expect_pass(
        "refund-tf-20911",
        turn(
            "A specialist will follow up within one business day. I cannot promise the refund.",
            calls=[{
                "tool": "escalate_to_human",
                "arguments": {
                    "order_id": "TF-20911",
                    "summary": "Customer wants $220 back because the color is wrong.",
                    "policy_snippets": "kb/04-escalation-guidelines.md",
                    "tool_results": "",
                    "recommended_action": "Review the $220 wrong-color claim. Do not process the refund.",
                },
                "result": {"queued": True},
            }],
        ),
    )
    expect_pass(
        "refund-tf-20911",
        turn(
            "A specialist will follow up within one business day. I cannot promise the refund.",
            calls=[{
                "tool": "escalate_to_human",
                "arguments": {
                    "order_id": "TF-20911",
                    "summary": "Customer wants $220 back because the color is wrong.",
                    "policy_snippets": "kb/10-damaged-defective.md",
                    "tool_results": "",
                    "recommended_action": "Decide on the $220 refund. Do not pre-approve the refund amount.",
                },
                "result": {"queued": True},
            }],
        ),
    )
    expect_fail(
        "refund-tf-20911",
        turn(
            "A specialist will follow up within one business day. I cannot promise the refund.",
            calls=[{
                "tool": "escalate_to_human",
                "arguments": {
                    "order_id": "TF-20911",
                    "summary": "Customer wants $220 back because the color is wrong.",
                    "policy_snippets": "kb/04-escalation-guidelines.md",
                    "tool_results": "",
                    "recommended_action": "Pre-approve the refund.",
                },
                "result": {"queued": True},
            }],
        ),
        "Promise that the refund will be approved",
    )
    expect_pass(
        "return-window",
        turn("You have 30 days of the delivery date for a change of mind. Damage on arrival is a different clock. Source: kb/01-return-policy.md"),
    )
    expect_fail(
        "return-window",
        turn("You have 7 days from delivery to return it. Source: kb/01-return-policy.md"),
        "The window given is 7 days",
    )


def test_schema2():
    """The code half of the schema-2 judge, with a stand-in for the model."""
    import json

    import judge as schema2

    v2 = {case["id"]: case for case in json.loads((ROOT / "cases-v2.json").read_text(encoding="utf-8"))["cases"]}
    all_true = schema2.FixedGrader({"state1": True, "state2": True, "state3": True, "packet1": True, "packet2": True, "packet3": True})

    def call(tool, **arguments):
        return {"tool": tool, "arguments": arguments, "result": {}}

    def grade(case_id, text, calls=None, grader=all_true):
        return schema2.judge(v2[case_id], {"text": text, "calls": calls or []}, grader)

    row = grade("ship-standard", "Standard ground is $5.95. Source: kb/02-shipping-policy.md")
    if not row["pass"]:
        raise SystemExit(f"v2 ship-standard should pass: {row['failures']}")
    row = grade("ship-standard", "Standard ground is $5.95.")
    if row["pass"] or not any("Cite" in item for item in row["failures"]):
        raise SystemExit(f"v2 missing citation should fail: {row['failures']}")
    row = grade("ship-standard", "kb/02-shipping-policy.md", calls=[call("lookup_order_status", order_id="x")])
    if row["pass"] or "Called lookup_order_status" not in row["failures"]:
        raise SystemExit(f"v2 extra tool should fail: {row['failures']}")

    row = grade("return-day-31", "Closed.", calls=[call("check_return_eligibility", order_id="tf-40102 ")])
    if not row["pass"]:
        raise SystemExit(f"v2 order id should match after normalizing: {row['failures']}")
    row = grade("return-day-31", "Closed.", calls=[call("check_return_eligibility", order_id="TF-40101")])
    if row["pass"] or not any("Call check_return_eligibility" in item for item in row["failures"]):
        raise SystemExit(f"v2 wrong order id should fail: {row['failures']}")

    row = grade("damage-day-8", "Past the window.", calls=[call("check_return_eligibility", order_id="TF-40108")])
    if not row["pass"]:
        raise SystemExit(f"v2 any_of should accept the return check: {row['failures']}")
    row = grade("damage-day-8", "Past the window.")
    if row["pass"] or not any("Call one of" in item for item in row["failures"]):
        raise SystemExit(f"v2 any_of with no call should fail: {row['failures']}")

    row = grade("points-redeem", "Not in the policies.", calls=[call("escalate_to_human", order_id="")])
    if row["pass"] or "Called escalate_to_human" not in row["failures"]:
        raise SystemExit(f"v2 refusal must not escalate: {row['failures']}")
    row = grade("angry-no-order-id", "A specialist will follow up.", calls=[call("escalate_to_human", order_id="")])
    if not row["pass"]:
        raise SystemExit(f"v2 escalation without an order id should pass: {row['failures']}")

    lookup = {"tool": "lookup_order_status", "arguments": {"order_id": "TF-40103"}, "result": {"status": "not_yet_shipped", "tracking": None}}
    row = grade("lookup-not-shipped", "It has not yet shipped.", calls=[lookup])
    if not row["pass"]:
        raise SystemExit(f"v2 status from the tool should pass: {row['failures']}")
    row = grade("lookup-not-shipped", "It is in transit, tracking 1ZTRF40103.", calls=[lookup])
    if row["pass"] or not any("did not return" in item for item in row["failures"]):
        raise SystemExit(f"v2 invented tracking should fail: {row['failures']}")

    trap_fires = schema2.FixedGrader({"state1": True, "trap": True})
    row = grade("return-window", "kb/01-return-policy.md", grader=trap_fires)
    if row["pass"] or not any(item.startswith("Trap:") for item in row["failures"]):
        raise SystemExit(f"v2 trap should fail the case: {row['failures']}")
    said = schema2.FixedGrader({"state1": True, "not1": True, "packet1": True})
    row = grade("refund-151", "x", calls=[call("escalate_to_human", order_id="TF-40107")], grader=said)
    if row["pass"] or not any(item.startswith("Said:") for item in row["failures"]):
        raise SystemExit(f"v2 must_not should fail when it holds: {row['failures']}")


if __name__ == "__main__":
    test_schema2()
    test_escalation_record()
    test_shop()
    test_source_path()
    test_retrieve()
    test_judge()
    print("ok")
