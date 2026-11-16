"""The policy owner's queue: questions the policies did not answer.

The runtime writes a gap record when the agent's note says the policies are
missing something. This prints the open records newest first, grouped by the
policy file cited near the question, since the free-text "missing" field will
not group by exact match.

    python sandbox/gaps.py
    python sandbox/gaps.py --md runs/gap-queue.md
    python sandbox/gaps.py --done <gap id> [<gap id> ...]
    python sandbox/gaps.py --all

--done marks records reviewed, so the queue drains. Records are kept; --all
shows reviewed ones too. Reads the trailforge-gaps table with your own AWS
credentials.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

TABLE = "trailforge-gaps"
REGION = "us-east-1"
NO_CITE = "no policy cited"


def table(name: str = TABLE, region: str = REGION):
    import boto3

    return boto3.resource("dynamodb", region_name=region).Table(name)


def scan(source) -> list[dict]:
    items = []
    kwargs: dict = {}
    while True:
        page = source.scan(**kwargs)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def group(records: list[dict], include_reviewed: bool = False) -> list[tuple[str, list[dict]]]:
    """Groups by the first cited policy, newest record first inside each group; the group with the newest record leads."""
    shown = [item for item in records if include_reviewed or item.get("status", "open") == "open"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in shown:
        cited = list(item.get("cited") or [])
        groups[cited[0] if cited else NO_CITE].append(item)
    for items in groups.values():
        items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return sorted(groups.items(), key=lambda pair: pair[1][0].get("created_at", ""), reverse=True)


def day(stamp: str) -> str:
    return (stamp or "")[:10] or "?"


def text_report(groups: list[tuple[str, list[dict]]]) -> str:
    total = sum(len(items) for _, items in groups)
    if not total:
        return "No open gaps.\n"
    lines = [f"{total} gap{'s' if total != 1 else ''} in {len(groups)} group{'s' if len(groups) != 1 else ''}", ""]
    for policy, items in groups:
        lines.append(f"{policy} ({len(items)})")
        for item in items:
            mark = "" if item.get("status", "open") == "open" else " [reviewed]"
            lines.append(f"  {day(item.get('created_at'))}  {item['gap_id']}{mark}")
            lines.append(f"    asked:   {item.get('question', '')}")
            lines.append(f"    missing: {item.get('missing', '')}")
            others = list(item.get("cited") or [])[1:]
            if others:
                lines.append(f"    also cited: {', '.join(others)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def md_report(groups: list[tuple[str, list[dict]]], generated: str) -> str:
    total = sum(len(items) for _, items in groups)
    lines = [
        "# Policy gaps",
        "",
        f"Questions the Trailforge policies did not answer. Generated {generated}. {total} open.",
        "",
    ]
    if not total:
        lines.append("No open gaps.")
    for policy, items in groups:
        lines += [f"## {policy}", "", "| Date | Customer asked | Missing from the policies | Id |", "|---|---|---|---|"]
        for item in items:
            cells = [day(item.get("created_at")), item.get("question", ""), item.get("missing", ""), f"`{item['gap_id']}`"]
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def mark_reviewed(source, gap_ids: list[str]) -> list[str]:
    """Marks each record reviewed. Returns ids that were not found or were already reviewed."""
    from botocore.exceptions import ClientError

    now = datetime.now(timezone.utc).isoformat()
    skipped = []
    for gap_id in gap_ids:
        try:
            source.update_item(
                Key={"gap_id": gap_id},
                UpdateExpression="SET #s = :reviewed, reviewed_at = :now",
                ConditionExpression="attribute_exists(gap_id) AND #s = :open",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":reviewed": "reviewed", ":open": "open", ":now": now},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            skipped.append(gap_id)
    return skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--md", default="", help="also write the report as a markdown file")
    parser.add_argument("--done", nargs="+", default=[], help="mark these gap ids reviewed")
    parser.add_argument("--all", action="store_true", help="include reviewed records")
    parser.add_argument("--table", default=TABLE)
    parser.add_argument("--region", default=REGION)
    args = parser.parse_args()

    source = table(args.table, args.region)
    if args.done:
        skipped = mark_reviewed(source, args.done)
        done = len(args.done) - len(skipped)
        print(f"marked {done} reviewed")
        if skipped:
            print(f"not open or not found: {', '.join(skipped)}", file=sys.stderr)
            return 1
        return 0

    groups = group(scan(source), include_reviewed=args.all)
    print(text_report(groups), end="")
    if args.md:
        path = Path(args.md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md_report(groups, datetime.now(timezone.utc).date().isoformat()), encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
