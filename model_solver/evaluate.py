"""Development-only scoring; this module is never imported by the runner."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import runpy

from .engine import holds
from .representation import symbol_table

PACKAGE = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("answers", help="saved model-led answers JSON")
    parser.add_argument("--items", default=str(PACKAGE / "items.json"))
    parser.add_argument("--key", default=str(PACKAGE / "visible_key.json"))
    parser.add_argument("--traces", help="optional saved model-led traces JSON")
    parser.add_argument("--out", help="optional combined score and diagnostics JSON")
    args = parser.parse_args()
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    items, answers, key = load(args.items), load(args.answers), load(args.key)
    item_ids = {item["id"] for item in items}
    # Subset by the requested input file, never by successfully returned answers.
    # Thus failed calls remain misses, rather than disappearing from the score.
    key = {n: value for n, value in key.items() if n in item_ids}
    if set(key) != item_ids:
        raise ValueError("The scoring key must contain every requested item")
    score = runpy.run_path(str(PACKAGE / "score.py"))["score"](key, answers, items)
    report = {"score": score, "requested_items": len(items), "returned_items": len(item_ids & set(answers))}
    if args.traces:
        traces = load(args.traces)
        phases, usage, invalid = Counter(), Counter(), []
        total_calls = 0
        flagged, excess, source_rules = [], [], []
        facts_checked, violated = 0, []
        for item in items:
            n = item["id"]
            trace = traces.get(n)
            if not trace:
                invalid.append({"item_id": n, "error": "missing trace"})
                continue
            calls, budget = trace.get("model_calls", 0), trace.get("budget")
            cap = {"1x": 1, "3x": 3, "10x": 10}.get(budget, 0)
            total_calls += calls
            if not 1 <= calls <= cap or calls != len(trace.get("extraction_reports", [])):
                invalid.append({"item_id": n, "budget": budget, "calls": calls})
            if trace.get("source_rules_enabled"):
                source_rules.append(n)
            if trace.get("unresolved_lines"):
                flagged.append(n)
            if trace.get("excess_solutions"):
                excess.append(n)
            phases.update(r["phase"] for r in trace.get("extraction_reports", []))
            for call in trace.get("call_metadata", []):
                usage.update({k: v for k, v in call.get("usage", {}).items()
                              if k in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, (int, float))})
            # One-sided extraction diagnostic: a source assertion must hold in
            # every keyed valid assignment. Passing this check cannot prove its
            # meaning is correct, and cannot detect missing constraints.
            if key[n]["case"] == "inconsistent":
                continue
            header = trace["header"]
            symbols = symbol_table(header)
            for fact in trace.get("facts", []):
                facts_checked += 1
                for assignment in key[n]["assignments"]:
                    times = {person: header["blocks"].index(value["block"]) for person, value in assignment.items()}
                    owners = {value["station"]: person for person, value in assignment.items() if "station" in value}
                    if not holds(fact, times, owners, header, symbols):
                        violated.append({"item_id": n, "line": fact["line"], "fact": fact})
                        break
        report["diagnostics"] = {"model_calls": total_calls, "phases": dict(phases), "usage": dict(usage),
                                 "budget_or_trace_errors": invalid, "unexpected_source_rules": source_rules,
                                 "items_with_unresolved_lines": flagged, "items_with_excess_solutions": excess,
                                 "facts_checked_against_valid_assignments": facts_checked,
                                 "facts_violating_a_keyed_assignment": violated,
                                 "extraction_diagnostic_is_one_sided": True}
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
