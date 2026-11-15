# AGENTS.md — order-support

Kind: node under applied/smb. The line standard in `../AGENTS.md` applies. The project shape in `../../AGENTS.md` applies.

## Offer

Rapport band. A demo where one agent decides the next step on an order-support case. Not priced. Not a monthly service. The orders and the policies are synthetic. This is not a production support desk.

## Where this can go

The goal below is the slice that has a benchmark. Making this a viable, working product is part of the work: a clearer decision rule, a wider set of cases, a stronger demo. An agent should say what would help. The feedback matches this stage. This project is rapport, so the stage is a demo that can be shown and a claim the sandbox measured. When the offer steps up, the feedback steps up with it. A proposal is written up when it is ready to build. It becomes the goal here when the principal locks it.

## Goal

On each customer message, one agent chooses among answering from a source, calling a tool, refusing, or escalating to a person.

The tools are order status, return eligibility, and escalate. An escalation packet carries the conversation summary, the source snippets, the tool results already obtained, and the agent's recommended next action.

The agent refuses when an order id is required and missing, or when the policy it would need is not in the source.

## Benchmark

On a frozen sandbox set, each case is right or wrong:

- One grounded answer that names its source.
- One tool call that is the right tool with the right arguments.
- One refusal when the order id or the policy is missing.
- One escalation that the case requires.
- One known wrong answer. A run that gives that answer fails.

Cost and latency are recorded per case.

The numbers come from the sandbox run. A claim that was not measured is not stated.

## This set

`sandbox/cases.json` is the frozen set, five cases, one decision each.

The score against the live runtime is `sandbox/runs/2026-11-15-runtime.json`: four of five passed. `points-redeem` failed on the judge's wording check: the reply refused correctly, and the judge only accepted fixed phrases. Latency is the client's wall time per call. Cost is per case, for model tokens only, at the rates the file names.

The judge now reads the refusal by meaning, with tests that still fail a reply naming a rate or not saying the rate is missing. The same replies re-scored under that judge are `sandbox/runs/2026-11-15-runtime-rescored.json`: five of five. Two tool cases there carry their original verdicts, because that run did not store tool arguments. The 4/5 file stays as recorded. A fresh run is the next full score.

The first score ran the agent in this checkout: `sandbox/runs/2026-11-14.json`, all five passed, cost blank. Two partial runs followed it. The citation cases passed against the managed knowledge base (`sandbox/runs/2026-11-14-kb.json`). The order lookup and the required escalation passed through the order tools (`sandbox/runs/2026-11-14-tools.json`).

## Shape

- Checkout: this folder. The git remote is `https://github.com/tech-forge-labs/order-support`.
- Sandbox: `sandbox/`. The runner is `sandbox/score.py`. The benchmark is the contract for a score. The runner can change, and more than one may be used.
- Release: not cut. The project is release-capable when install and config can put it on another machine.

## Architecture note

`20262224-agentic-customer-support-architecture.md` is the starting sketch. Where it disagrees with this file, this file wins. The sketch marks an evaluation harness out of scope. The benchmark above is in scope. It was scored before the cloud runtime. The runtime hosts the same agent.

## Insitu

Subscribed 2026-11-14. This file stays the constitution. Project rules stay here until something is reused. Nothing new was written for this chair. The map holds the node and project-dev roles, the shared global set, Context Forge, and Envoy status and mail. Insitu orientation is on demand.

## Not part of the release

`_status/`, `project.yaml`, `_envoy/`, `_contextforge/`, `_system/`, `PROTOCOL.md`, and the generated host copies under `.grok/`, `.claude/`, and `.cursor/` are this install's records. They stay out of the repo and out of a release. `.gitignore` names them.

## This file

Changes only with the principal's explicit approval.
