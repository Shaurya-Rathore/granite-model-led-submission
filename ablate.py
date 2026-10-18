"""Print or execute applicable component removals through the required ./run."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CAPS = {"1x": 1, "3x": 3, "10x": 10}
ARMS = {"full": tuple(CAPS), "no_examples": tuple(CAPS),
        "no_scope_examples": tuple(CAPS), "no_grounding": tuple(CAPS),
        "no_independent": ("3x", "10x"), "no_audit": ("3x", "10x"),
        "no_focus": ("3x", "10x"), "no_chunking": ("10x",)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("items")
    parser.add_argument("--key", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--execute", action="store_true", help="Make live model calls; default is plan only")
    args = parser.parse_args()
    items = Path(args.items).resolve()
    key = Path(args.key).resolve()
    target = Path(args.out_dir).resolve()
    population = json.loads(items.read_text())
    if not isinstance(population, list) or not population:
        parser.error("items must be a nonempty list")
    ids = [item["id"] for item in population]
    if len(ids) != len(set(ids)):
        parser.error("duplicate item IDs")
    plans = []
    for arm, budgets in ARMS.items():
        for budget in budgets:
            prefix = target / (arm + "-" + budget)
            command = [str(ROOT / "run"), str(items), "--budget", budget,
                       "--stage", "named_review", "--ablation", arm, "--workers", "1",
                       "--out", str(prefix) + "-answers.json", "--trace-out", str(prefix) + "-traces.json"]
            plans.append({"arm": arm, "budget": budget, "command": command,
                          "request_upper_bound": len(population) * CAPS[budget], "status": "planned"})
    manifest = {"mode": "live" if args.execute else "dry_run_no_api_calls",
                "created_at": datetime.now(timezone.utc).isoformat(), "stage": "named_review",
                "item_ids": ids, "items_sha256": hashlib.sha256(items.read_bytes()).hexdigest(),
                "key_sha256": hashlib.sha256(key.read_bytes()).hexdigest(),
                "request_upper_bound": sum(p["request_upper_bound"] for p in plans), "plans": plans}
    print(json.dumps(manifest, indent=2))
    if not args.execute:
        return 0
    if target.exists():
        parser.error("Use a fresh output directory; refusing to overwrite earlier results")
    target.mkdir(parents=True)
    manifest_path = target / "manifest.json"
    save = lambda: manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    manifest["status"] = "running"
    save()
    for plan in plans:
        prefix = target / (plan["arm"] + "-" + plan["budget"])
        plan["status"] = "running"
        save()
        with Path(str(prefix) + ".log").open("x") as log:
            result = subprocess.run(plan["command"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        plan["returncode"] = result.returncode
        plan["status"] = "complete" if result.returncode == 0 else "incomplete"
        answers = Path(str(prefix) + "-answers.json")
        traces = Path(str(prefix) + "-traces.json")
        if answers.exists():
            command = [sys.executable, "-m", "model_solver.evaluate", str(answers), "--items", str(items),
                       "--key", str(key), "--out", str(prefix) + "-score.json"]
            if traces.exists():
                command += ["--traces", str(traces)]
            scored = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            plan["scoring_returncode"] = scored.returncode
            if scored.returncode:
                plan["status"] = "scoring_failed"
                plan["scoring_error"] = scored.stderr[-1500:]
        save()
        if plan["status"] != "complete":
            manifest["status"] = "stopped_incomplete"
            save()
            return 2
    manifest["status"] = "complete"
    save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
