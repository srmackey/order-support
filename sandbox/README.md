# Sandbox

The runner is `score.py`. The frozen case set is `cases.json`. It is not a customer environment.

The benchmark in `../README.md` is the contract for a score. This file says how that contract is marked. Policies are in `../kb/`.

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

Cost and latency are recorded per case on the run. They do not change the pass bit. A run row keeps the full tool calls, so `score.py --rescore <file> --label <name>` can judge stored replies again without a model call. The original file is never overwritten. The live-runtime score is `runs/2026-11-15-runtime.json`. What each run covers is in `../README.md`.

## Set v2 (draft)

`cases-v2.json` holds 39 cases: 13 answers, 10 tool calls, 8 refusals, and 8 escalations. 11 sit on a boundary, such as exactly $75 for free shipping, day 30 and day 31 of the return window, and $150 against $151 for escalation. The five v1 cases come first, with the same messages. The set is a draft until its `frozen` field holds a date. After that, cases are not edited.

A v2 case declares what is right, and one judge marks every case (`judge.py`):

- **Code checks what is exact.** `tools.required` calls happened with those argument values. `tools.any_of` names alternatives. A tool not in `required`, `any_of`, or `allowed` fails the case. `cite_any` names the files the reply may cite. With `facts_from_tool`, every tracking number, date, and status phrase in the reply has to appear in what the tools returned.
- **A model checks what is meaning** (`llm_judge.py`). `must_state`, `must_not`, `trap`, and `packet_facts` are plain claims about the reply or the escalation packet. Claude Haiku 4.5 on Bedrock, at temperature 0, marks each claim true or false and quotes the text that decided it. The quotes are in the run file, so any verdict can be audited.

The run file records the judge model and prompt version, because changing either can move scores.

`calibrate.py` checks the judge against `calibration.json`, replies a person labeled, good and bad, including the runtime refusal the phrase-matching judge failed. On 2026-11-15 it agreed on 46 of 46 claims, three runs in a row, after one claim was reworded: "will process your refund" was not being read as a promise. Run it again after changing the judge prompt, the judge model, or a claim's wording.

The judge tests run without AWS: `test_score.py` covers the code half with a stand-in for the model.

## Tools

`lookup_order_status` takes `order_id`.

`check_return_eligibility` takes `order_id`, and `reason` only when the customer stated one. The delivery date is looked up. The agent does not pass it. No v1 case requires this tool. Several v2 cases do.

`escalate_to_human` takes `order_id`, `summary`, `policy_snippets`, `tool_results`, and `recommended_action`. The customer is told a person will follow up within one business day. Neither the reply nor the recommended action promises a specific outcome. Telling the specialist to process, approve, or issue the refund fails the case.

Order ids in the set are not in the policies. The order table is `../app/orders.json`, and its clock is the `as_of` date in that file. The case file itself still holds no order records.
