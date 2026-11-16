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

## Set v2

`cases-v2.json` holds 39 cases: 13 answers, 10 tool calls, 8 refusals, and 8 escalations. 11 sit on a boundary, such as exactly $75 for free shipping, day 30 and day 31 of the return window, and $150 against $151 for escalation. The five v1 cases come first, with the same messages. The set was frozen on 2026-11-15, and cases are not edited after a miss. Its first score is `runs/2026-11-15-v2-runtime.json`.

A v2 case declares what is right, and one judge marks every case (`judge.py`):

- **Code checks what is exact.** `tools.required` calls happened with those argument values. `tools.any_of` names alternatives. A tool not in `required`, `any_of`, or `allowed` fails the case. `cite_any` names the files the reply may cite. With `facts_from_tool`, every tracking number, date, and status phrase in the reply has to appear in what the tools returned.
- **A model checks what is meaning** (`llm_judge.py`). `must_state`, `must_not`, `trap`, and `packet_facts` are plain claims about the reply or the escalation packet. Claude Haiku 4.5 on Bedrock, at temperature 0, marks each claim true or false and quotes the text that decided it. The quotes are in the run file, so any verdict can be audited.

The run file records the judge model and prompt version, because changing either can move scores.

`calibrate.py` checks the judge against `calibration.json`, replies labeled good and bad, including the runtime refusal the phrase-matching judge failed. On 2026-11-15 it agreed on 62 of 62 claims, three runs in a row. One claim was reworded along the way: "will process your refund" was not being read as a promise. Run it again after changing the judge prompt, the judge model, or a claim's wording.

The judge tests run without AWS: `test_score.py` covers the code half with a stand-in for the model.

## Holdout set

`cases-holdout.json` holds 14 cases: 3 answers, 2 tool calls, 6 refusals, and 3 escalations. It was written and frozen on 2026-11-15, before the runtime version 6 prompt change, and scored on version 5 first as the baseline (`runs/2026-11-15-holdout-runtime-v5.json`). It leans toward refusals and exception requests, where version 5 regressed. Prompt changes are checked against v2 cases, never against this set, so its score is on cases the agent was not tuned against. The same agent that wrote the cases made the prompt changes, so they are not fully independent of them. It is judged the same way as set v2.

Each run row also carries `decision`: the agent's note on which move it chose and why, which the runtime keeps out of the reply. It is recorded, not scored.

## When a miss gets fixed

One run of a case is one sample, and the agent does not answer the same way every time. A single miss is not evidence of a defect, so a change is never made because of one.

- **Score each set three times.** A case is broken when it fails in at least two of the three runs. A case that fails once is noise: it is listed and left alone.
- **Gate every change.** A change to the prompt or the code ships only if no case is broken on v2 or the holdout that was not broken before. A change that fixes one case and breaks another is rejected, not followed by another change.
- **Put rules that must always hold in code.** The model follows instructions most of the time, not every time. Where a rule has one right output, code makes it: the runtime removes the decision note from the reply, and when an escalation is queued and the reply does not say when a person will follow up, the runtime adds that sentence.

`stability.py` applies the rule to a group of run files, and with `--against` applies the gate to a baseline group. Its exit code is 1 when the gate fails.

## Tools

`lookup_order_status` takes `order_id`.

`check_return_eligibility` takes `order_id`, and `reason` only when the customer stated one. The delivery date is looked up. The agent does not pass it. No v1 case requires this tool. Several v2 cases do.

`escalate_to_human` takes `order_id`, `summary`, `policy_snippets`, `tool_results`, and `recommended_action`. The customer is told a person will follow up within one business day. Neither the reply nor the recommended action promises a specific outcome. Telling the specialist to process, approve, or issue the refund fails the case.

Order ids in the set are not in the policies. The order table is `../app/orders.json`, and its clock is the `as_of` date in that file. The case file itself still holds no order records.
