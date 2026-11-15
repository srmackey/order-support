"""Policy excerpts for one customer message.

`retrieve` ranks the local files by term overlap. The judge tests use it.
`retrieve_index` asks the Bedrock knowledge base named trailforge-policies.
A chunk is labeled with its S3 key, such as kb/02-shipping-policy.md.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KB = ROOT.parent / "kb"
TOKEN = re.compile(r"[a-z0-9]+")
STOP = {
    "a",
    "an",
    "the",
    "is",
    "it",
    "of",
    "for",
    "to",
    "and",
    "or",
    "do",
    "i",
    "my",
    "me",
    "how",
    "what",
    "when",
    "where",
    "can",
    "on",
    "in",
    "you",
    "your",
}


def tokens(text: str) -> list[str]:
    return [item for item in TOKEN.findall(text.lower()) if item not in STOP and len(item) > 1]


def documents() -> list[dict]:
    found = []
    for path in sorted(KB.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        found.append({"path": f"kb/{path.name}", "text": text, "tokens": tokens(text)})
    return found


def retrieve(question: str, limit: int = 4) -> list[dict]:
    question_tokens = tokens(question)
    scored = []
    for doc in documents():
        counts: dict[str, int] = {}
        for token in doc["tokens"]:
            counts[token] = counts.get(token, 0) + 1
        score = sum(counts.get(token, 0) for token in question_tokens)
        if score:
            scored.append((score, doc["path"], doc["text"]))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [{"path": path, "text": text} for _, path, text in scored[:limit]]


def format_sources(docs: list[dict]) -> str:
    if not docs:
        return "No policy excerpts matched this message."
    blocks = [f"[{doc['path']}]\n{doc['text'].strip()}" for doc in docs]
    return "\n\n".join(blocks)


KB_NAME = "trailforge-policies"
REGION = "us-east-1"
_kb_id: str | None = None


def source_path(result: dict) -> str | None:
    """Return kb/<file>.md from a Retrieve hit, when the source key has that shape."""

    candidates: list[str] = []
    location = result.get("location") or {}
    s3 = location.get("s3Location") or {}
    if isinstance(s3, dict) and isinstance(s3.get("uri"), str):
        candidates.append(s3["uri"])
    document_id = result.get("documentId")
    if isinstance(document_id, str):
        candidates.append(document_id)
    metadata = result.get("metadata") or {}
    for key in ("_source_uri", "x-amz-bedrock-kb-source-uri"):
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.append(value)
    for uri in candidates:
        normalized = uri.replace("\\", "/")
        index = normalized.rfind("kb/")
        if index < 0:
            continue
        path = normalized[index:].split("?", 1)[0]
        if path.endswith(".md"):
            return path
    return None


def knowledge_base_id() -> str:
    global _kb_id
    if _kb_id:
        return _kb_id
    import boto3

    client = boto3.client("bedrock-agent", region_name=REGION)
    token = None
    while True:
        kwargs: dict = {"maxResults": 20}
        if token:
            kwargs["nextToken"] = token
        page = client.list_knowledge_bases(**kwargs)
        for item in page.get("knowledgeBaseSummaries", []):
            if item.get("name") == KB_NAME:
                _kb_id = item["knowledgeBaseId"]
                return _kb_id
        token = page.get("nextToken")
        if not token:
            break
    raise RuntimeError(f"No knowledge base named {KB_NAME}")


def retrieve_index(question: str, limit: int = 4) -> list[dict]:
    import boto3

    client = boto3.client("bedrock-agent-runtime", region_name=REGION)
    response = client.retrieve(
        knowledgeBaseId=knowledge_base_id(),
        retrievalQuery={"text": question},
        retrievalConfiguration={"managedSearchConfiguration": {"numberOfResults": limit}},
    )
    docs = []
    for item in response.get("retrievalResults", []):
        text = ((item.get("content") or {}).get("text")) or ""
        if not text.strip():
            continue
        docs.append({"path": source_path(item) or "kb/unlabeled.md", "text": text})
    return docs
