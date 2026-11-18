# Order support agent

One agent reads a customer message for a fictional outdoor shop and decides the next step:

- **Answer** from the policy documents and cite the file it used.
- **Call a tool** when the question needs a live order fact.
- **Refuse** when an order id is required and missing, or the policy it would need is not in the documents.
- **Escalate** to a person when an escalation rule applies, with a packet the person can act on.

The orders and policies are synthetic. This is a demo with a measured benchmark, not a production support desk.

## What the endpoint serves

The DEFAULT endpoint runs the container image `order-support:v9`. That image was scored on 2026-11-15: three runs of the 39-case set with no case broken, and 14 of 14 on the holdout in all three runs. Those runs are the measured claim.

Version 10 added a policy-gap flag. On 2026-11-16 it scored 39 of 39 three times on the 39-case set. The 15-case set was 15, 14, and 14, and no case failed twice. The holdout was 14, 13, and 13: `cancel-exception` told the customer a specialist would follow up and never queued the escalation. That failed the gate, so version 10 was taken off the endpoint the same day.

AgentCore does not move the default endpoint back to an older version number. The rollback is runtime version 11 running the version 9 image. The knowledge base was re-indexed to the policy text that image was scored against. Two later edits, the word "only" on the shipping and payment lists, stay in `kb/` and are not in the index. The tools Lambda can store a gap record. The served image does not call it.

A sync from the `kb/` files in this repo would put those two edits back into the index.

## How it works

The code in this checkout:

```
Customer message
  -> AgentCore Runtime: Strands agent (Claude Sonnet 4.6 on Amazon Bedrock)
       -> Bedrock managed knowledge base: policy chunks, each labeled with its file
       -> Lambda trailforge-tools
            lookup_order_status        reads the DynamoDB orders table
            check_return_eligibility   applies the 30-day rule to the order record
            escalate_to_human          stores a packet in the escalations table
            record_policy_gap          stores a gap record (called by the runtime, not the model)
  -> Reply to the customer, plus the tool calls and sources used
```

In this checkout, when the policies do not answer a question, the customer is told so and the runtime leaves a gap record for the policy owner: the question, what was missing, and the policy cited nearby. The model does not call a tool for it; code reads the agent's note and writes the record. `sandbox/gaps.py` is the owner's queue. The endpoint does not run this code. See above.

An escalation packet carries the conversation summary, the policy files used, the tool results already obtained, and a recommended next action. The customer is told a specialist will follow up within one business day. Neither the reply nor the packet may promise an outcome such as a refund.

Before replying, the agent writes down which move it chose and the policy line or tool result behind it. The runtime removes that note from the reply and returns it separately, so every scored run shows why the agent did what it did.

The runtime is instrumented with OpenTelemetry, so each call leaves a trace in CloudWatch showing retrieval, model turns, and tool calls.

| Folder | What is in it |
|---|---|
| `app/` | The agent, the runtime entrypoint, retrieval, the tool client, and the order rules |
| `lambda/` | The tools Lambda, a seed script for the orders table, and the package build |
| `infra/` | CloudFormation for the runtime role and image repository, and for the tools stack |
| `kb/` | The sixteen policy documents behind the knowledge base |
| `sandbox/` | The frozen case set, the scorer, the judge tests, and every scored run |
| `docs/` | The architecture sketch the project started from |

## Benchmark

`sandbox/cases.json` is a frozen set of five cases, one decision each. Each case passes or fails.

| Case | The right move |
|---|---|
| `ship-standard` | Answer from the shipping policy and cite it. |
| `order-tf-10482` | Call `lookup_order_status` with the right order id. Any status in the reply must come from the tool. |
| `points-redeem` | Refuse. The policies give the points earn rate but not the redemption rate. |
| `refund-tf-20911` | Escalate a $220 refund without promising it. |
| `return-window` | Answer 30 days from delivery. Giving the 7-day damage window fails the run. |

Cost and latency are recorded per case. A case is never edited after a miss so the model can pass. How each case is marked is in `sandbox/README.md`.

### Results

The live runtime was scored on 2026-11-15, all five cases in one run (`sandbox/runs/2026-11-15-runtime.json`):

- **4 of 5 passed.** `points-redeem` was marked failed. The reply refused correctly and named no rate, but the judge only accepted three fixed phrasings.
- The judge was then changed to read the refusal by meaning, with tests that still fail a reply that invents a rate. The same stored replies re-scored **5 of 5** (`sandbox/runs/2026-11-15-runtime-rescored.json`). Two tool cases in that file keep their original verdicts, because that run did not store tool arguments. Runs store them now.
- Model cost for the five cases was **$0.08** in total, at the on-demand Bedrock rate recorded in the run file. Infrastructure cost is not included.
- Wall-clock latency per case was 4.1 to 14.3 seconds. Time inside the agent was 1.9 to 9.2 seconds.

Earlier runs scored the agent in this checkout before it was deployed (`sandbox/runs/2026-11-14*.json`).

### A larger set: 39 cases

`sandbox/cases-v2.json` grows the set to 39 cases, with several per outcome and 11 on boundaries. It was frozen on 2026-11-15. Its judge splits the work: code checks tools, arguments, citations, and order facts, and Claude Haiku 4.5 checks claims about what the reply says, quoting its evidence. Before the run, the judge agreed with all 62 labeled claims it was checked against (`sandbox/runs/2026-11-15-calibration.json`). How the set is marked is in `sandbox/README.md`.

The live runtime was scored on 2026-11-15 (`sandbox/runs/2026-11-15-v2-runtime.json`):

- **35 of 39 passed.** Answers 12 of 13, tool calls 9 of 10, refusals 8 of 8, escalations 6 of 8. Boundary cases 8 of 11.
- `stove-fire-no-order-id` and `angry-no-order-id`: the agent asked for an order number instead of escalating. The escalation rules say a safety concern or strong frustration escalates on its own.
- `damage-day-8`: the agent found the delivery date but did not know the current date, so it could not say the 7-day damage window had closed.
- `ship-standard`: the reply gave the price and the free-shipping threshold but left out the 5 to 7 day delivery time.
- Agent model cost for the run was **$0.58**, and the judge cost **$0.07**. Wall-clock latency per case was 2.7 to 10.4 seconds. Time inside the agent was 1.2 to 9.0 seconds.

Runtime version 5 changed the agent, not the cases. Tool results now carry the current date, the escalation guidelines are in every prompt instead of depending on retrieval (the safety rule had not been retrieved for the stove case), and the prompt checks escalation rules first and lets an escalation go ahead without an order number. Scored the same day (`sandbox/runs/2026-11-15-v2-runtime-v5.json`):

- **37 of 39 passed.** Answers 13 of 13, tool calls 10 of 10, escalations 8 of 8, refusals 6 of 8. Boundary cases 10 of 11.
- The four earlier misses all passed. Two refusals that passed before now failed: `points-expire` said points never expire, and `bulk-exception` escalated a request the policies do not cover. On the earlier prompt both passed four of four local runs; on version 5 they passed two of four and three of four. The new prompt caused them.
- Agent model cost was **$0.66** and the judge **$0.08**. Wall-clock latency per case was 2.3 to 12.4 seconds.

Before the next change, a 14-case holdout set was written and frozen (`sandbox/cases-holdout.json`). Prompt changes are tested on v2 cases only, so the holdout scores cases the agent was not tuned against. Version 5 scored 13 of 14 on it: `layaway-exception` escalated a request no policy covers.

Versions 6 to 8 changed the prompt again. The exception rule now covers only exceptions to a written policy, and a policy that says nothing about a question is not read as a yes or a no. Reading the version 6 replies showed the agent naming its internal decision steps to the customer, which the judge does not check. Version 7 moved that reasoning into a note the runtime removes from the reply. Version 8 told the agent to cite the policy in the reply itself, after two answers cited it only inside the removed note. Version 8, scored the same day:

- **v2: 38 of 39** (`sandbox/runs/2026-11-15-v2-runtime-v8.json`). Answers 13 of 13, tool calls 10 of 10, refusals 8 of 8, escalations 7 of 8. Boundary cases 11 of 11. `chargeback-threat` escalated, but told the customer a specialist would be in touch "shortly" instead of within one business day.
- **Holdout: 14 of 14** (`sandbox/runs/2026-11-15-holdout-runtime-v8.json`).
- Versions 6, 7, and 8 each scored 38 of 39 on v2, each missing a different case. At this set size, one miss per run is within the variation between runs, so version 8's gain is the hidden note and the holdout result, not a higher v2 score.
- A code check across both sets found no reply that named a decision step or showed the note.
- Agent model cost was **$0.66** on v2 and **$0.22** on the holdout, and the judge **$0.07** and **$0.03**. Wall-clock latency per case was 2.8 to 14.0 seconds.

The holdout cases were written by the same agent that changed the prompt, so they are not fully independent of the change.

### Repeated runs

A single run is one sample, and the agent does not answer the same way every time, so from version 9 each set is scored three times. A case counts as broken only if it fails in two of the three runs, and a change ships only if no case becomes broken. The rule and the script that applies it are in `sandbox/README.md`. Version 9 also has the runtime add the follow-up sentence when an escalation is queued and the reply leaves it out, so that rule no longer depends on the model.

Version 9, three runs of each set on 2026-11-15 (`sandbox/runs/2026-11-15-*-runtime-v9-r*.json`):

- **v2: 38, 39, and 38 of 39. No case is broken.** Two cases failed once each. `giftcard-return` left out its citation. `lookup-unknown` was marked down for "a tracking number (once shipped)", which the code check reads as an order status; the reply was correct, so that miss belongs to the judge. The judge was not changed after the run.
- **Holdout: 14 of 14 in all three runs.**
- No reply named a decision step or showed the note. The model said when a specialist would follow up in all 33 escalations, so the runtime never had to add the sentence.
- Agent model cost for the six runs was **$2.69** and the judge **$0.30**. Wall-clock latency per case was 2.9 to 18.2 seconds.

This is the score the endpoint serves. Version 10's runs are in `sandbox/runs/2026-11-16-*-runtime-v10-r*.json`. They did not replace this baseline.

## Run it

Python 3.11 or newer.

```
uv venv .venv
uv pip install -r requirements.txt --python .venv\Scripts\python.exe
```

The judge tests need no AWS account:

```
.venv\Scripts\python sandbox\test_score.py
```

Score the five cases with the agent running locally. This calls Bedrock for the model and the knowledge base, and the tools Lambda for orders:

```
.venv\Scripts\python sandbox\score.py
```

Score against the deployed runtime instead, with cost per case:

```
.venv\Scripts\python sandbox\score.py --runtime <agent runtime arn> --label runtime --price-in 3 --price-out 15
```

`--cases cases-v2.json` scores the larger set. `python sandbox/calibrate.py` checks its judge first. `--label` names the run file so an earlier run is never overwritten. `--rescore <run file> --label <name>` judges stored replies again without calling the model.

`python app/main.py` serves the agent at `http://127.0.0.1:8080/invocations`, the same entrypoint the runtime hosts. `TRAILFORGE_TOOLS=local` runs the tools against `app/orders.json` instead of the Lambda and does not store escalation packets.

## Deploy

- **Tools.** `python lambda/build.py` assembles the Lambda package in `build/function`. `infra/tools.yaml` is the stack: the Lambda and three DynamoDB tables (orders, escalations, policy gaps). `python lambda/seed.py` loads `app/orders.json` into the orders table.
- **Runtime.** `infra/runtime.yaml` creates the execution role and the image repository. The image is ARM64, built from the `Dockerfile`. To push it, map the ECR registry to the Amazon ECR credential helper under `credHelpers` in `~/.docker/config.json`. On Windows, a `docker login` token is longer than Docker's credential store accepts.
- **Knowledge base.** A Bedrock managed knowledge base named `trailforge-policies`, synced from the `kb/` files in S3. The endpoint's index is the text from before the "only" edits in `kb/02-shipping-policy.md` and `kb/08-payment-billing-faq.md`. Syncing this repo's copies would change that.

Every call to the runtime and the tools needs IAM credentials. There is no unauthenticated endpoint.

---

Copyright 2026 Scott Mackey. All rights reserved.
