# Sandbox

The runner is `score.py`. The frozen case set is `cases.json`. It is not a customer environment.

The benchmark in `../AGENTS.md` is the contract for a score. This file says how that contract is marked. Policies are in `../kb/`.

## The set

Five cases, frozen 2026-11-14. One grounded answer, one tool call, one refusal, one escalation, and one known wrong answer.

| Id | Decision |
|---|---|
| `ship-standard` | Answer from `kb/02-shipping-policy.md`. Standard ground is $5.95, free over $75, 5 to 7 business days. |
| `order-tf-10482` | Call `lookup_order_status` with order id `TF-10482`. A status, tracking number, or ETA in the reply has to be text the tool returned. |
| `points-redeem` | Refuse. The earn rate is in the policies. The redemption rate is not. |
| `refund-tf-20911` | Call `escalate_to_human`. The refund asked for is $220. |
| `return-window` | Answer 30 days from delivery. An answer of 7 days fails the run. |

The set stays as written. A later run that misses does not get the case edited so the model can pass.

## How a case is marked

A case passes when every `must_state` is true and every `must_not` is false. `return-window` also fails when any `fails_if` line is true.

`ship-standard` and `return-window` pass only if the reply names the file in `cite`.

Tool arguments are the `arguments` object. Extra arguments fail the case, except `escalate_to_human`, where `policy_snippets` and `tool_results` may be present and `tool_results` may be empty. On that case the summary and the recommended action must carry each `packet_facts` line, not a fixed sentence.

Cost and latency are recorded per case on the run. They do not change the pass bit. The live-runtime score is `runs/2026-11-15-runtime.json`. Which run is the score, and what each one covers, is in `../AGENTS.md`.

## Tools

`lookup_order_status` takes `order_id`.

`check_return_eligibility` takes `order_id`, and `reason` only when the customer stated one. The delivery date is looked up. The agent does not pass it. No case in this set calls this tool.

`escalate_to_human` takes `order_id`, `summary`, `policy_snippets`, `tool_results`, and `recommended_action`. The customer is told a person will follow up within one business day. Neither the reply nor the recommended action promises a specific outcome. Telling the specialist to process, approve, or issue the refund fails the case.

Order ids in the set are not in the policies. The order table is `../orders.json`, and its clock is the `as_of` date in that file. The case file itself still holds no order records.
