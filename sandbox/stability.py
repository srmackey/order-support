"""Apply the stop rule to repeated runs of one case set.

A case is broken when it fails in more than half of the runs (two of three).
A case that fails less often than that is noise: it is listed, not fixed.

    python sandbox/stability.py runs/A.json runs/B.json runs/C.json
    python sandbox/stability.py <new runs> --against <baseline runs>

With --against, the gate passes only if no case is broken in the new runs
that was not broken in the baseline. The exit code is 1 when the gate fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load(paths: list[str]) -> tuple[dict[str, list[bool]], set[str]]:
    results: dict[str, list[bool]] = defaultdict(list)
    sets = set()
    for name in paths:
        path = Path(name) if Path(name).exists() else ROOT / name
        run = json.loads(path.read_text(encoding="utf-8"))
        sets.add(run.get("set", "?"))
        for row in run["cases"]:
            results[row["id"]].append(bool(row["pass"]))
    return results, sets


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
    args = parser.parse_args()

    results, sets = load(args.runs)
    if len(sets) != 1:
        print(f"runs mix case sets: {sorted(sets)}")
        return 2
    now = summarize(results)
    print(f"{sets.pop()}: {now['cases']} cases, {now['runs']} runs, {now['pass_rate']:.1%} of case runs passed")
    print(f"broken (fails in more than half of runs): {', '.join(now['broken']) or 'none'}")
    print(f"noise (failed once or less often): {', '.join(now['noise']) or 'none'}")
    if now["uneven"]:
        print(f"cases missing from some runs: {', '.join(now['uneven'])}")

    if not args.against:
        return 0
    before, _ = load(args.against)
    was = set(summarize(before)["broken"])
    newly = [case for case in now["broken"] if case not in was]
    fixed = sorted(was - set(now["broken"]))
    print(f"gate: {'FAIL' if newly else 'pass'}. Newly broken: {', '.join(newly) or 'none'}. Fixed: {', '.join(fixed) or 'none'}.")
    return 1 if newly else 0


if __name__ == "__main__":
    sys.exit(main())
