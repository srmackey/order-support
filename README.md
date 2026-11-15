# order-support

A rapport-band demo on the SMB line. One agent decides the next step on an order-support case. The goal and the benchmark are in `AGENTS.md`.

The standard for this line is `../AGENTS.md`.

The starting architecture is `20262224-agentic-customer-support-architecture.md`.

The policies are in `kb/`. The shop is Trailforge. The orders are synthetic.

## Install

Python 3.11 or newer. From this folder:

```
uv venv .venv
uv pip install -r requirements.txt --python .venv\Scripts\python.exe
```

The score does not need a server:

```
.venv\Scripts\python sandbox\score.py
```

That calls Bedrock for the model. Credentials are the usual AWS ones, or `AWS_BEARER_TOKEN_BEDROCK`. The run writes `sandbox/runs/`. The judge without a model is `sandbox/test_score.py`.

`--runtime <agent runtime arn>` sends each case to the hosted agent instead. Latency is then the client's wall time for the call. `--price-in` and `--price-out` (USD per million tokens) fill in cost per case, for model tokens only. `--label` names the run file so a second run on the same day does not overwrite the first.

`python main.py` serves the same agent at `http://127.0.0.1:8080/invocations`. AgentCore Runtime hosts that process as `trailforge_support`. The image is the `order-support` repository, tag `v4`. The response carries the token counts for the turn. The process is instrumented, so a call can leave a trace. To push the image, map the ECR registry to the Amazon ECR credential helper under `credHelpers` in `~/.docker/config.json` rather than running `docker login`. On Windows the login token is longer than Docker's credential store accepts. The role and the repository are `infra/runtime.yaml`. A call needs IAM.

The three tools run as one Lambda, `trailforge-tools`. It reads `trailforge-orders` and writes escalation packets to `trailforge-escalations`. `TRAILFORGE_TOOLS=local` keeps the tools on `orders.json` and does not store the packet. The stack is `infra/tools.yaml`.

## Sandbox

`sandbox/cases.json` is the frozen set. `sandbox/score.py` is the runner. The score reads orders through `trailforge-tools`. `orders.json` is the seed for that table and the local fallback. The score retrieves chunks from the Bedrock knowledge base named `trailforge-policies`. A chunk is labeled with its key, `kb/<file>.md`, and the reply has to cite that path. `sandbox/test_score.py` still ranks the local files and does not call AWS.

## Release

No release is cut.
