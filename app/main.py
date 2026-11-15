"""Local entrypoint. The same function is what a later AgentCore deploy calls.

    python app/main.py
    curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" -d "{\"prompt\": \"How much is standard shipping?\"}"
"""

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent import ask

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    turn = ask(prompt)
    return {
        "result": turn["text"],
        "tools": turn["calls"],
        "sources": turn["sources"],
        "agent_ms": turn["latency_ms"],
        "input_tokens": turn["input_tokens"],
        "output_tokens": turn["output_tokens"],
    }


if __name__ == "__main__":
    app.run()
