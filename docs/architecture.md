# Architecture sketch

This is the design the project started from. What was built and measured is in the README. Where the two differ, the README is current. The benchmark, for example, was in scope from the start even though this sketch lists an evaluation harness as out of scope.

**Goal**: A proof of concept for an LLM-in-the-loop customer support agent that can resolve common requests via retrieval + tools or escalate with a clear human-in-the-loop path.

**Stack**: Strands Agents SDK + Amazon Bedrock AgentCore Runtime + Amazon Bedrock Managed Knowledge Base + Lambda tools + DynamoDB (sample orders) + S3 (KB documents).

---

## High-Level Flow

```
Customer message
    → Entry point (API Gateway / simple front end / AgentCore endpoint)
        → Strands Agent (running on AgentCore Runtime)
            ├─ Reasoning + tool selection
            ├─ Knowledge Base (policies, FAQs, shipping, returns)
            ├─ Tool: lookup_order_status
            ├─ Tool: check_return_eligibility
            └─ Tool: escalate_to_human
        → Final response to customer
           or escalation packet for human review
```

Traces and logs flow to CloudWatch / AgentCore Observability throughout.

---

## Core Components

### 1. Agent (Strands on AgentCore Runtime)
- **Role**: Owns the decision loop. Given a goal and instructions, it decides whether to retrieve from the Knowledge Base, call a tool, escalate, or respond.
- **Instructions focus**:
  - Prefer Knowledge Base for policy/FAQ questions.
  - Use order tools only when an order identifier is available.
  - Escalate when confidence is low, request is ambiguous, customer is upset, or policy thresholds are crossed.
  - Always produce an auditable trail.
- **Deployment**: AgentCore Runtime (consumption-based microVM, scales to zero).

### 2. Knowledge Base (RAG)
- **Type**: Amazon Bedrock Managed Knowledge Base.
- **Content**: Synthetic company policies and FAQs (returns, shipping, warranty, escalation rules, product basics).
- **Storage**: S3 source → Managed KB (chunking, embedding, and retrieval handled by the service).
- **Usage**: Agent queries it when it needs grounded policy or product information. Citations/sources available in traces.

### 3. Tools (Action Groups / Lambda)
Minimal set of three tools:

| Tool | Purpose | Backing |
|------|---------|---------|
| `lookup_order_status` | Return status, tracking, items, ETA for a given order ID | Lambda + small DynamoDB table (or static JSON for earliest prototype) |
| `check_return_eligibility` | Check whether an order qualifies for return given reason and dates | Lambda (policy logic + order data) |
| `escalate_to_human` | Create a structured review packet and notify that a human will follow up | Lambda → DynamoDB (or S3) ticket/escalation record |

Tool contracts are explicit (input parameters, expected return shape, error cases) so the agent’s behavior stays predictable and auditable.

### 4. Human-in-the-Loop Path
- Triggered by the `escalate_to_human` tool.
- Escalation packet contains:
  - Conversation summary
  - Relevant Knowledge Base snippets
  - Tool results already obtained
  - Agent’s recommended next action and confidence notes
- Customer receives a clear message that a human will follow up.
- Packet is stored for review (DynamoDB or S3).

### 5. Observability
- AgentCore / Strands traces showing reasoning steps, tool calls, and retrievals.
- CloudWatch logs for full interaction (input, tool I/O, final response, latency, token usage).
- Optional simple trace viewer in the demo UI so the decision path is visible to a reviewer or client.

### 6. Cost-Aware Design
- Prefer cheaper models (Haiku / Nova class) during development; use stronger model for final demos if needed.
- AgentCore Runtime and Managed Knowledge Base are consumption-based (scale to zero when idle).
- Prompt caching on stable instruction prefixes where supported.
- Billing alarms set at low thresholds ($25 / $50).

---

## Data

### Synthetic Knowledge Base
- 15–30 short Markdown or text documents covering:
  - Return and refund policy
  - Shipping times and costs
  - Warranty information
  - Common product FAQs
  - When and how to escalate
- Generated specifically for the POC so retrieval matches the tools and demo scenarios.

### Sample Order Data
- Small DynamoDB table (or JSON file) with 5–10 example orders covering:
  - In-transit
  - Delivered (within and outside return window)
  - Already returned
  - High-value / exception cases

---

## Entry Point
Single entry point that receives the customer message and invokes the agent. For the POC this can be:
- Direct AgentCore endpoint
- API Gateway + Lambda proxy
- Minimal chat UI (Streamlit, simple HTML, or existing demo harness)

No separate classification service is required; the agent performs intent understanding as part of its reasoning.

---

## Design choices
- Agent owns the loop (not a fixed pipeline).
- Explicit tool contracts and escalation criteria.
- Grounded retrieval via Managed Knowledge Base.
- Full decision traces.
- Human-in-the-loop path with structured packet.
- Consumption-based runtime that scales to zero.
- Clear separation between agent logic (Strands) and operational runtime (AgentCore).

---

## Out of Scope for Initial Version
- Multi-agent supervisor/specialist pattern
- Full CRM or ticketing system integration
- Authentication / multi-tenant identity (can be added later via AgentCore Identity)
- Advanced evaluation harness
