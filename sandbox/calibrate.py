"""Check the LLM judge against labeled replies before trusting its scores.

Each item in calibration.json is a reply with the verdict a person gave each
claim. The judge grades the same claims, and this reports where it agrees.
A disagreement is either a judge miss or a label to fix; read the evidence.

    python sandbox/calibrate.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import judge
import llm_judge


def main() -> int:
    cases = {case["id"]: case for case in json.loads((ROOT / "cases-v2.json").read_text(encoding="utf-8"))["cases"]}
    items = json.loads((ROOT / "calibration.json").read_text(encoding="utf-8"))["items"]
    grader = llm_judge.BedrockJudge()
    rows = []
    agree = total = 0
    tokens_in = tokens_out = 0
    for number, item in enumerate(items, 1):
        case = cases[item["case"]]
        claims = {claim["id"]: claim for claim in judge.claims_for(case)}
        calls = item.get("calls", [])
        asked = [{"id": key, "text": claims[key]["text"]} for key in item["expect"]]
        graded = grader.grade(
            case["customer"],
            item["reply"],
            asked,
            packet=llm_judge.packet_text(calls),
            tool_results=llm_judge.tool_results_text(calls),
        )
        tokens_in += graded["input_tokens"]
        tokens_out += graded["output_tokens"]
        for key, expected in item["expect"].items():
            verdict = graded["verdicts"][key]
            ok = verdict["holds"] == expected
            agree += ok
            total += 1
            rows.append({"item": number, "case": item["case"], "claim": key, "text": claims[key]["text"],
                         "label": expected, "judge": verdict["holds"], "agree": ok, "evidence": verdict["evidence"]})
            if not ok:
                print(f"item {number} {item['case']} {key}: label {expected}, judge {verdict['holds']}")
                print(f"  claim: {claims[key]['text']}")
                print(f"  evidence: {verdict['evidence']!r}")
    print(f"{agree} of {total} claims agree")
    out = ROOT / "runs" / f"{date.today().isoformat()}-calibration.json"
    out.write_text(json.dumps({
        "date": date.today().isoformat(),
        "judge": llm_judge.describe(),
        "agree": agree,
        "total": total,
        "judge_cost_usd": llm_judge.cost(tokens_in, tokens_out),
        "claims": rows,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0 if agree == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
