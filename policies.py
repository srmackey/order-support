"""Rank the Trailforge policy files for one customer message.

The score is term overlap. The result names the file, which is what a case
cites. This is not a managed knowledge base.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KB = ROOT / "kb"
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
