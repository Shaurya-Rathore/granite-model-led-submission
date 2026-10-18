"""Budgeted model interpretation and source review, followed by exact solving."""
from __future__ import annotations

import json
import math
from typing import Any

from .engine import derive_answer, facts_from_rows, minimal_conflict
from .prompts import build_prompt
from .representation import SCOPES, claim_key, response_schema, symbol_table, validate_output
from .transport import GraniteClient, line_records, parse_header

BUDGETS = {"1x": 1, "3x": 3, "10x": 10}
ABLATIONS = ("full", "no_filter", "no_audit", "no_chunking", "no_examples", "no_grounding")


def unknown(line_no):
    return {"line": line_no, "scope": "uncertain", "claims": []}


def validate_scopes(obj, sources):
    """Validate identifiers and labels, without making a language judgement."""
    source_ids = {line["line"] for line in sources}
    scopes, problems, seen = {}, [], set()
    for row in obj.get("lines", []):
        if not isinstance(row, dict) or type(row.get("line")) is not int or row["line"] not in source_ids:
            problems.append({"line": None, "errors": ["unexpected source line"]})
            continue
        line_no = row["line"]
        if line_no in seen:
            scopes[line_no] = "uncertain"
            problems.append({"line": line_no, "errors": ["duplicate source row"]})
            continue
        seen.add(line_no)
        if set(row) != {"line", "scope"} or row.get("scope") not in SCOPES:
            scopes[line_no] = "uncertain"
            problems.append({"line": line_no, "errors": ["invalid scope row"]})
        else:
            scopes[line_no] = row["scope"]
    for line_no in source_ids - seen:
        scopes[line_no] = "uncertain"
        problems.append({"line": line_no, "errors": ["omitted source row"]})
    return scopes, problems


def reading_signature(rows):
    # Ignore evidence formatting and the audit's reason when comparing meaning.
    return json.dumps({n: {"scope": row["scope"], "claims": sorted(claim_key(c) for c in row["claims"])}
                       for n, row in sorted(rows.items())}, sort_keys=True)


def process_item(item: dict[str, Any], budget: str, env: dict[str, str], ablation: str = "full", *, client=None):
    if budget not in BUDGETS or ablation not in ABLATIONS:
        raise ValueError("Unsupported budget or ablation")
    header = parse_header(item["text"])
    sources = line_records(item["text"])
    if not sources:
        raise ValueError("An item must contain source notes after its header")
    cap = BUDGETS[budget]
    client = client if client is not None else GraniteClient(env, item["id"])
    grounding = ablation != "no_grounding"
    examples = ablation != "no_examples"
    rows = {line["line"]: unknown(line["line"]) for line in sources}
    reports, pending = [], set()
    calls_made = 0

    def request(phase, selected, *, candidate_rows=None):
        nonlocal calls_made
        if calls_made >= cap:
            raise RuntimeError("Refusing a model call beyond this item's budget")
        prompt = build_prompt(selected, header, phase, rows=candidate_rows,
                              examples=examples, anchor_entities=grounding)
        schema = response_schema(selected, header, phase=phase, anchor_entities=grounding)
        report = {"phase": phase, "source_lines": [x["line"] for x in selected],
                  "prompt_chars": len(prompt), "schema_chars": len(json.dumps(schema)),
                  "literal_grounding": grounding, "source_rule_hints": False}
        calls_made += 1  # A failed request consumes its slot too; no automatic retry.
        try:
            obj = client.call(prompt, schema)
        except ValueError as error:
            # A malformed model response is an observed extraction failure.
            # HTTP/transport errors propagate, so they never become a fake score.
            obj = {"lines": []}
            report["parse_error"] = str(error)
        reports.append(report)
        return obj, report

    def read(phase, selected, *, candidate_rows=None):
        obj, report = request(phase, selected, candidate_rows=candidate_rows)
        proposed, problems = validate_output(obj, selected, header, grounding=grounding, phase=phase)
        invalid = {problem["line"] for problem in problems if problem["line"] is not None}
        changed, retained = [], []
        for line in selected:
            n = line["line"]
            candidate = proposed[n]
            # A failed review must not erase an earlier usable interpretation.
            if (n in invalid or candidate["scope"] == "uncertain") and rows[n]["scope"] != "uncertain":
                retained.append(n)
                pending.add(n)
                continue
            if reading_signature({n: candidate}) != reading_signature({n: rows[n]}):
                changed.append(n)
            rows[n] = candidate
            if n in invalid or candidate["scope"] == "uncertain":
                pending.add(n)
            else:
                pending.discard(n)
        report.update({"problems": problems, "proposed_rows": list(proposed.values()),
                       "changed_lines": changed, "retained_previous_lines": retained})

    scopes = None
    if budget == "1x":
        read("extract", sources)
    else:
        obj, report = request("classify", sources)
        scopes, problems = validate_scopes(obj, sources)
        report.update({"problems": problems, "scopes": scopes})
        if ablation == "no_filter":
            selected = sources
        else:
            selected = [line for line in sources if scopes[line["line"]] in ("current_clue", "uncertain")]
            for line in sources:
                n = line["line"]
                if scopes[n] not in ("current_clue", "uncertain"):
                    rows[n] = {"line": n, "scope": scopes[n], "claims": []}
        # Even an all-noise filter gets a fresh interpretation call. The full
        # source audit also sees discarded rows, so filtering is reversible.
        if not selected:
            selected = sources
        if budget == "10x" and ablation != "no_chunking":
            chunk_size = max(4, math.ceil(len(selected) / 6))
            chunks = [selected[i:i + chunk_size] for i in range(0, len(selected), chunk_size)]
        else:
            chunks = [selected]
        for chunk in chunks:
            read("extract", chunk)
        if ablation != "no_audit":
            # Audit receives source + backtranslated meanings, no solver result.
            read("audit", sources, candidate_rows=rows)

    repairs = 0
    reviewed = set()
    while budget == "10x" and calls_made < cap and repairs < 2:
        facts = facts_from_rows(rows, sources)
        _, solutions = derive_answer(header, facts)
        targets = set(pending) | {n for n, row in rows.items() if row["scope"] == "uncertain"}
        if not solutions:
            targets.update(fact["line"] for fact in minimal_conflict(header, facts))
        elif len(solutions) > 4:
            # More than four schedules violates the task's ambiguity bound;
            # this diagnoses missing/misread constraints without choosing one.
            targets.update(n for n, row in rows.items() if row["scope"] == "current_clue")
            if not targets:
                targets.update(rows)
        targets -= reviewed
        if not targets:
            break
        ordered = sorted(targets, key=lambda n: (n not in pending, n))[:6]
        selected = [line for line in sources if line["line"] in ordered]
        before = reading_signature(rows)
        read("repair", selected)  # Independent source reading, no candidate ledger.
        repairs += 1
        reviewed.update(ordered)
        if reading_signature(rows) != before:
            reviewed.clear()
        elif targets <= reviewed:
            break

    facts = facts_from_rows(rows, sources)
    answer, solutions = derive_answer(header, facts)
    unresolved = sorted(pending | {n for n, row in rows.items() if row["scope"] == "uncertain"})
    trace = {"architecture": "model_led_typed_atoms_v1", "budget": budget, "ablation": ablation,
             "header": header, "symbols": symbol_table(header), "source_rules_enabled": False,
             "literal_grounding_enabled": grounding, "scope_filter": scopes,
             "extraction_reports": reports, "final_rows": list(rows.values()), "facts": facts,
             "unresolved_lines": unresolved, "solution_count": len(solutions),
             "excess_solutions": len(solutions) > 4, "model_calls": calls_made,
             "raw_model_outputs": getattr(client, "raw_outputs", []),
             "call_metadata": getattr(client, "call_metadata", [])}
    return answer, calls_made, trace
