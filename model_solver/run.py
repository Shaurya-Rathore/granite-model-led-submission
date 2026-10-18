"""Experimental model-led shift-note interpreter."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
import sys

from .pipeline import ABLATIONS, BUDGETS, STAGES, process_item
from .transport import load_env, parse_header


def save_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("items", help="JSON list of items, each containing id and text")
    parser.add_argument("--budget", required=True, choices=BUDGETS)
    parser.add_argument("--out", required=True, help="answers JSON path")
    parser.add_argument("--trace-out", help="optional extraction and call trace JSON path")
    parser.add_argument("--ablation", default="full", choices=ABLATIONS)
    parser.add_argument("--stage", default="named_review", choices=STAGES,
                        help="named_review is the current typed extraction/independent-read/correction stage; earlier stages remain selectable")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.trace_out and Path(args.trace_out).resolve() == Path(args.out).resolve():
        parser.error("answers and traces need different output paths")
    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    if not isinstance(items, list) or not items:
        parser.error("items must be a nonempty JSON list")
    ids = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("text"), str):
            parser.error("every item must contain string id and text fields")
        if item["id"] in ids:
            parser.error("duplicate item id")
        ids.add(item["id"])
        parse_header(item["text"])
    for output in (args.out, args.trace_out):
        if output and Path(output).resolve() == Path(args.items).resolve():
            parser.error("output must not overwrite the input items")
    env = load_env()
    answers, traces, failures = {}, {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_item, item, args.budget, env, args.ablation, stage=args.stage): item["id"] for item in items}
        for n, future in enumerate(concurrent.futures.as_completed(futures), 1):
            item_id = futures[future]
            try:
                answer, calls, trace = future.result()
            except Exception as error:
                failures.append(item_id)
                print(f"[{n}/{len(items)}] {item_id}: failed ({type(error).__name__}: {error})", file=sys.stderr, flush=True)
                continue
            answers[item_id], traces[item_id] = answer, trace
            save_json(args.out, answers)
            if args.trace_out:
                save_json(args.trace_out, traces)
            print(f"[{n}/{len(items)}] {item_id}: {answer['case']} ({calls} calls, {trace['solution_count']} schedules)", flush=True)
    if failures:
        print(f"Incomplete run: {len(failures)} items failed; completed answers were saved.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
