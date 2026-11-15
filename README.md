# Trailforge order support agent

One agent reads a customer message for Trailforge, a fictional outdoor retailer, and decides the next step:

- **Answer** from the policy documents and cite the file it used.
- **Call a tool** when the question needs a live order fact.
- **Refuse** when an order id is required and missing, or the policy it would need is not in the documents.
- **Escalate** to a person when an escalation rule applies, with a packet the person can act on.

The orders and policies are synthetic. This is a demo with a measured benchmark, not a production support desk.

## How it works

```
Customer message
  -> AgentCore Runtime: Strands agent (Claude Sonnet 4.6 on Amazon Bedrock)
       -> Bedrock managed knowledge base: policy chunks, each labeled with its file
       -> Lambda trailforge-tools
            lookup_order_status        reads the DynamoDB orders table
            check_return_eligibility   applies the 30-day rule to the order record
            escalate_to_human          stores a packet in the escalations table
  -> Reply to the customer, plus the tool calls and sources used
```

An escalation packet carries the conversation summary, the policy files used, the tool results already obtained, and a recommended next action. The customer is told a specialist will follow up within one business day. Neither the reply nor the packet may promise an outcome such as a refund.

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

### A larger set, in draft

`sandbox/cases-v2.json` grows the set to 39 cases, with several per outcome and 11 on boundaries. It is not frozen or scored yet. Its judge splits the work: code checks tools, arguments, citations, and order facts, and Claude Haiku 4.5 checks claims about what the reply says, quoting its evidence. Against 62 labeled claims, the judge agreed on all 62 (`sandbox/runs/2026-11-15-calibration.json`). How the set is marked is in `sandbox/README.md`.

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

- **Tools.** `python lambda/build.py` assembles the Lambda package in `build/function`. `infra/tools.yaml` is the stack: the Lambda and two DynamoDB tables. `python lambda/seed.py` loads `app/orders.json` into the orders table.
- **Runtime.** `infra/runtime.yaml` creates the execution role and the image repository. The image is ARM64, built from the `Dockerfile`. To push it, map the ECR registry to the Amazon ECR credential helper under `credHelpers` in `~/.docker/config.json`. On Windows, a `docker login` token is longer than Docker's credential store accepts.
- **Knowledge base.** A Bedrock managed knowledge base named `trailforge-policies`, synced from the `kb/` files in S3.

Every call to the runtime and the tools needs IAM credentials. There is no unauthenticated endpoint.

---

Copyright 2026 Scott Mackey. All rights reserved.
