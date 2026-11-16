"""Apply the stop rule to repeated runs of one case set.

A case is broken when it fails in more than half of the runs (two of three).
A case that fails less often than that is noise: it is listed, not fixed.

    python sandbox/stability.py runs/A.json runs/B.json runs/C.json
    python sandbox/stability.py <new runs> --against <baseline runs>

With --against, the gate passes only if no case is broken in the new runs
that was not broken in the baseline. The exit code is 1 when the gate fails.

The gap check takes the same rule on its own terms. A case is gap-broken when
it fails the gap check in more than half of the runs that recorded one. Gap-
broken cases are reported as known failures and do not change the exit code
(decided 2026-11-16, for the demo stage). --strict-gap restores the absolute
bar: any gap-broken case fails, with or without --against.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load(paths: list[str]) -> tuple[dict[str, list[bool]], set[str], dict[str, list[bool]]]:
    results: dict[str, list[bool]] = defaultdict(list)
    gaps: dict[str, list[bool]] = defaultdict(list)
    sets = set()
    for name in paths:
        path = Path(name) if Path(name).exists() else ROOT / name
        run = json.loads(path.read_text(encoding="utf-8"))
        sets.add(run.get("set", "?"))
        for row in run["cases"]:
            results[row["id"]].append(bool(row["pass"]))
            if row.get("gap_ok") is not None:
                gaps[row["id"]].append(bool(row["gap_ok"]))
    return results, sets, gaps


def broken(passes: list[bool]) -> bool:
    return passes.count(False) * 2 > len(passes)


def summarize(results: dict[str, list[bool]]) -> dict:
    runs = max(len(passes) for passes in results.values())
    return {
        "runs": runs,
        "cases": len(results),
        "broken": sorted(case for case, passes in results.items() if broken(passes)),
        "noise": sorted(case for case, passes in results.items() if False in passes and not broken(passes)),
        "pass_rate": sum(sum(passes) for passes in results.values()) / sum(len(passes) for passes in results.values()),
        "uneven": sorted(case for case, passes in results.items() if len(passes) != runs),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--against", nargs="+", default=[])
    parser.add_argument("--strict-gap", action="store_true", help="fail on any gap-broken case")
    args = parser.parse_args()

    results, sets, gaps = load(args.runs)
    if len(sets) != 1:
        print(f"runs mix case sets: {sorted(sets)}")
        return 2
    now = summarize(results)
    print(f"{sets.pop()}: {now['cases']} cases, {now['runs']} runs, {now['pass_rate']:.1%} of case runs passed")
    print(f"broken (fails in more than half of runs): {', '.join(now['broken']) or 'none'}")
    print(f"noise (failed once or less often): {', '.join(now['noise']) or 'none'}")
    if now["uneven"]:
        print(f"cases missing from some runs: {', '.join(now['uneven'])}")

    gap_broken = []
    if gaps:
        gap = summarize(gaps)
        gap_broken = gap["broken"]
        print(f"gap check: {gap['pass_rate']:.1%} of case runs right")
        print(f"gap-broken (gap check fails in more than half of runs): {', '.join(gap_broken) or 'none'}")
        print(f"gap noise (failed once or less often): {', '.join(gap['noise']) or 'none'}")

    newly = []
    if args.against:
        before, _, _ = load(args.against)
        was = set(summarize(before)["broken"])
        newly = [case for case in now["broken"] if case not in was]
        fixed = sorted(was - set(now["broken"]))
        print(f"gate: {'FAIL' if newly else 'pass'}. Newly broken: {', '.join(newly) or 'none'}. Fixed: {', '.join(fixed) or 'none'}.")
    if gap_broken and args.strict_gap:
        print(f"gap gate: FAIL. Gap-broken: {', '.join(gap_broken)}.")
    elif gap_broken:
        print(f"gap check: known failures, reported and not gated: {', '.join(gap_broken)}.")
    elif gaps:
        print("gap check: no case gap-broken.")
    return 1 if newly or (gap_broken and args.strict_gap) else 0


if __name__ == "__main__":
    sys.exit(main())
