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

`python main.py` serves the same agent at `http://127.0.0.1:8080/invocations`. That process is the local stand-in for a later AgentCore deploy. It does not create Runtime or other account resources.

The three tools run as one Lambda, `trailforge-tools`. It reads `trailforge-orders` and writes escalation packets to `trailforge-escalations`. `TRAILFORGE_TOOLS=local` keeps the tools on `orders.json` and does not store the packet. The stack is `infra/tools.yaml`.

## Sandbox

`sandbox/cases.json` is the frozen set. `sandbox/score.py` is the runner. The score reads orders through `trailforge-tools`. `orders.json` is the seed for that table and the local fallback. The score retrieves chunks from the Bedrock knowledge base named `trailforge-policies`. A chunk is labeled with its key, `kb/<file>.md`, and the reply has to cite that path. `sandbox/test_score.py` still ranks the local files and does not call AWS.

## Release

No release is cut.
