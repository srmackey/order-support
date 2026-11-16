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
    for result in (found, missing, early, open_return, closed, final):
        if result.get("today") != "2026-11-14":
            raise SystemExit(f"result has no clock date: {result}")


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


def test_reply_guards():
    import agent

    text = "<decision>Step 1: refund above $150.</decision>\n\nYour case is queued. A specialist will be in touch shortly."
    queued = [{"tool": "escalate_to_human", "arguments": {}, "result": {"queued": True}}]
    reply = agent.with_follow_up(agent.strip_decision(text), queued)
    assert "decision" not in reply.lower() and "step 1" not in reply.lower()
    assert reply.endswith(agent.FOLLOW_UP)
    assert agent.split_decision([{"role": "assistant", "content": [{"text": text}]}]) == ["Step 1: refund above $150."]

    # Seen on 2026-11-15 (ship-same-day): a reconsidering sentence between two decisions reached the customer.
    revised = "<decision>step: 4 | missing: same-day</decision>\nWait, let me reconsider.\n<decision>step: 3 | missing: none</decision>\n\nWe do not offer same-day delivery."
    assert agent.reply_text(revised) == "We do not offer same-day delivery."
    assert agent.reply_text("<decision>step: 3 | missing: none</decision>\nStandard is $5.95.") == "Standard is $5.95."
    assert agent.reply_text("Standard is $5.95.\n<decision>step: 3 | missing: none</decision>") == "Standard is $5.95."
    assert agent.reply_text("No decision here.") == "No decision here."

    said = "A specialist will follow up within 1 business day."
    assert agent.with_follow_up(said, queued) == said
    assert agent.with_follow_up("Here is our shipping policy.", []) == "Here is our shipping policy."
    failed = [{"tool": "escalate_to_human", "arguments": {}, "result": {"error": "timeout"}}]
    assert agent.with_follow_up("Sorry, something went wrong.", failed) == "Sorry, something went wrong."


def test_gap_note():
    import os

    import agent

    parse = agent.parse_note
    assert parse(["step: 4 | missing: whether points transfer\nkb/09 is silent."]) == {"step": 4, "missing": "whether points transfer"}
    assert parse(["**step: 3 | missing: none**\nkb/02 lists Overnight."]) == {"step": 3, "missing": ""}
    assert parse(["Step: 3 | Missing: gift receipts.\nkb/05 gives wrap."]) == {"step": 3, "missing": "gift receipts"}
    assert parse(["step: 1\nRefund above $150."]) == {"step": 1, "missing": ""}
    assert parse(["I think this is about shipping."]) == {"step": None, "missing": ""}
    # Seen on 2026-11-15: reasons on the same line, and a revised decision.
    assert parse(["step: 3 | missing: none. kb/09-account-faq.md states 1 point per dollar."]) == {"step": 3, "missing": ""}
    assert parse(["step: 4 | missing: whether PO box delivery is supported. The policy is silent."]) == {"step": 4, "missing": "whether PO box delivery is supported"}
    assert parse(["step: 4 | missing: same-day delivery. Actually the list is closed.\nstep: 3 | missing: none."]) == {"step": 3, "missing": ""}
    assert parse(["step: 3 | missing: none", "step: 4 | missing: post-purchase price adjustment policy"]) == {"step": 4, "missing": "post-purchase price adjustment policy"}
    assert parse(["step: 4 | missing: nonexistent rental terms"]) == {"step": 4, "missing": "nonexistent rental terms"}
    assert agent.cited_paths("See kb/02-shipping-policy.md.", "kb\\02-shipping-policy.md and kb/11-promotions.md") == [
        "kb/02-shipping-policy.md",
        "kb/11-promotions.md",
    ]

    os.environ["TRAILFORGE_TOOLS"] = "local"
    try:
        note = {"step": 4, "missing": "PO box shipping"}
        gap = agent.record_gap("Can you ship to a PO box?", note, "Not in kb/02-shipping-policy.md.", [])
        assert gap["recorded"] and not gap["stored"] and gap["missing"] == "PO box shipping"
        assert gap["cited"] == ["kb/02-shipping-policy.md"]
        assert agent.record_gap("How much is shipping?", {"step": 3, "missing": ""}, "", []) is None
    finally:
        del os.environ["TRAILFORGE_TOOLS"]

    record = shop.gap_record({"question": "q", "missing": "m", "cited": ["kb/02-shipping-policy.md", ""], "step": 4}, "g1", "2026-11-15T00:00:00+00:00")
    assert record == {
        "gap_id": "g1",
        "question": "q",
        "missing": "m",
        "cited": ["kb/02-shipping-policy.md"],
        "step": 4,
        "status": "open",
        "created_at": "2026-11-15T00:00:00+00:00",
    }


def test_gap_judge():
    import json

    import judge as schema3
    import score

    expect = {}
    for name in ("cases-v2.json", "cases-holdout.json", "cases-v3.json"):
        cases = json.loads((ROOT / name).read_text(encoding="utf-8"))["cases"]
        expect[name] = sum(bool(score.gap_expected(case, name)) for case in cases)
    assert expect == {"cases-v2.json": 5, "cases-holdout.json": 6, "cases-v3.json": 6}, expect
    assert score.gap_expected({"id": "ship-standard"}, "cases.json") is None

    v3 = json.loads((ROOT / "cases-v3.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in v3["cases"]}
    checks = v3["checks"]
    gap = {"question": "Can you ship to a PO box?", "missing": "PO box shipping", "cited": []}
    holds = schema3.FixedGrader({"state1": True, "gap1": True})

    row = schema3.judge(cases["ship-po-box"], {"text": "That is not in our policies.", "gap": gap}, holds, checks, True)
    assert row["pass"] and row["gap_ok"] is True and row["gap_written"] is True, row["failures"]

    row = schema3.judge(cases["ship-po-box"], {"text": "That is not in our policies.", "gap": None}, holds, checks, True)
    assert row["gap_ok"] is False and not row["pass"]
    assert any(item.startswith("Gap record missing") for item in row["failures"])

    row = schema3.judge(cases["pay-venmo"], {"text": "We accept only cards. See kb/08-payment-billing-faq.md.", "gap": gap}, holds, checks, False)
    assert row["gap_ok"] is False, "a gap written where none is expected fails the gap check"

    leaked = schema3.judge(cases["ship-po-box"], {"text": "Step 4 applies: not in the policies.", "gap": gap}, holds, checks, True)
    assert any(item.startswith("Showed internal text") for item in leaked["failures"])

    once = {"text": "TF-77777 was not found. A tracking number is emailed once it has shipped.", "calls": [
        {"tool": "lookup_order_status", "arguments": {"order_id": "TF-77777"}, "result": {"found": False, "order_id": "TF-77777"}}
    ], "gap": None}
    row = schema3.judge(cases["lookup-unknown-shipped"], once, schema3.FixedGrader({"state1": True}), checks, False)
    assert row["pass"], f"schema 3 leaves status phrases to the trap claim: {row['failures']}"
    assert schema3.invented_tokens(once["text"], "{}"), "schema 2 still checks status phrases in code"

    old = schema3.judge(cases["ship-po-box"], {"text": "Not in the policies."}, holds, checks, True)
    assert old["gap_ok"] is None and old["gap_written"] is None, "a turn from before the gap record has no gap check"


def test_gap_stability():
    import json
    import tempfile

    import stability

    with tempfile.TemporaryDirectory() as folder:
        paths = []
        for index, gap_oks in enumerate(([True, False], [True, False], [True, True])):
            run = {"set": "cases-v3.json", "cases": [
                {"id": "a", "pass": True, "gap_ok": gap_oks[0]},
                {"id": "b", "pass": True, "gap_ok": gap_oks[1]},
            ]}
            path = Path(folder) / f"r{index}.json"
            path.write_text(json.dumps(run), encoding="utf-8")
            paths.append(str(path))
        _, _, gaps = stability.load(paths)
        assert stability.summarize(gaps)["broken"] == ["b"]
        sys.argv = ["stability.py", *paths]
        assert stability.main() == 0, "a gap-broken case is reported, not gated, by default"
        sys.argv = ["stability.py", *paths, "--strict-gap"]
        assert stability.main() == 1, "--strict-gap fails a gap-broken case without a baseline"


def test_gap_report():
    import gaps

    records = [
        {"gap_id": "old", "question": "PO box?", "missing": "PO boxes", "cited": ["kb/02-shipping-policy.md"], "status": "open", "created_at": "2026-11-14T10:00:00+00:00"},
        {"gap_id": "new", "question": "Date pick?", "missing": "choosing a date", "cited": ["kb/02-shipping-policy.md", "kb/06-order-tracking-faq.md"], "status": "open", "created_at": "2026-11-15T10:00:00+00:00"},
        {"gap_id": "tent", "question": "Rent a tent?", "missing": "rental", "cited": [], "status": "open", "created_at": "2026-11-15T09:00:00+00:00"},
        {"gap_id": "seen", "question": "Gift receipt?", "missing": "gift receipts", "cited": ["kb/05-product-faq-general.md"], "status": "reviewed", "created_at": "2026-11-15T11:00:00+00:00"},
    ]
    grouped = gaps.group(records)
    assert [policy for policy, _ in grouped] == ["kb/02-shipping-policy.md", gaps.NO_CITE]
    assert [item["gap_id"] for item in grouped[0][1]] == ["new", "old"]
    assert len(gaps.group(records, include_reviewed=True)) == 3
    text = gaps.text_report(grouped)
    assert text.startswith("3 gaps in 2 groups") and "also cited: kb/06-order-tracking-faq.md" in text
    md = gaps.md_report(grouped, "2026-11-15")
    assert "## kb/02-shipping-policy.md" in md and "| 2026-11-15 | Date pick? | choosing a date | `new` |" in md
    assert gaps.text_report([]) == "No open gaps.\n"


if __name__ == "__main__":
    test_gap_note()
    test_gap_judge()
    test_gap_stability()
    test_gap_report()
    test_schema2()
    test_escalation_record()
    test_shop()
    test_source_path()
    test_retrieve()
    test_judge()
    test_reply_guards()
    print("ok")
