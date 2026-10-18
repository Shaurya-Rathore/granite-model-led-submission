"""Three independently selectable revisions of the model interpretation path."""
from __future__ import annotations

from copy import deepcopy
import json
import math

from .engine import derive_answer, facts_from_rows, minimal_conflict
from .flat import response_schema, review_row, unknown, validate_output, validate_statuses
from .incremental_prompts import build_prompt
from .legacy_v1.pipeline import reading_signature
from .representation import symbol_table
from .transport import GraniteClient, line_records, parse_header

STAGES = ('schema', 'examples', 'review', 'legacy', 'named', 'named_examples', 'named_review', 'named_json', 'named_json_short')
BUDGETS = {"1x": 1, "3x": 3, "10x": 10}
ABLATIONS = ("full", "no_filter", "no_audit", "no_chunking", "no_examples", "no_grounding", "no_scope_examples", "no_independent", "no_focus", "no_partial_atoms")


def process_item(item, budget, env, ablation="full", *, stage="schema", client=None):
    if stage not in STAGES or budget not in BUDGETS or ablation not in ABLATIONS:
        raise ValueError("Unsupported stage, budget, or ablation")
    if stage in ('named_json','named_json_short'):
        client=client if client is not None else GraniteClient(env,item['id'])
        prior_mode=getattr(client,'wire_mode','json_schema')
        client.wire_mode='json_object_deepinfra_short' if stage=='named_json_short' else 'json_object_deepinfra'
        try:
            answer,calls,trace=process_item(item,budget,env,ablation,stage='named_review',client=client)
        finally:
            client.wire_mode=prior_mode
        trace.update(development_stage=stage,wire_mode='json_object_deepinfra_short' if stage=='named_json_short' else 'json_object_deepinfra')
        return answer,calls,trace
    if stage == "legacy":
        from .legacy_v1.pipeline import ABLATIONS as legacy_ablations, process_item as old_process
        if ablation not in legacy_ablations:
            raise ValueError("This ablation is unavailable in the archived v1 model variant")
        answer, calls, trace = old_process(item, budget, env, ablation, client=client)
        trace["development_stage"] = "legacy"
        return answer, calls, trace
    named = stage.startswith("named")
    base_stage = {"named": "schema", "named_examples": "examples", "named_review": "review"}.get(stage, stage)
    schema_builder, output_validator, review_validator, prompt_builder = response_schema, validate_output, review_row, build_prompt
    if named:
        from . import named as contract
        from .named_prompts import build_prompt as named_prompt
        schema_builder, output_validator = contract.response_schema, contract.validate_output
        review_validator, prompt_builder = contract.review_row, named_prompt
    header = parse_header(item["text"])
    sources = line_records(item["text"])
    if not sources:
        raise ValueError("An item must contain source notes after its header")
    cap = BUDGETS[budget]
    client = client if client is not None else GraniteClient(env, item["id"])
    grounding, examples = ablation != "no_grounding", ablation != "no_examples"
    rows = {line["line"]: unknown(line["line"]) for line in sources}
    reports, pending = [], set()
    calls, scopes, secondary = 0, None, None

    def request(phase, selected, *, primary=None, alternative=None):
        nonlocal calls
        if calls >= cap:
            raise RuntimeError("Refusing a model call beyond this item's budget")
        prompt = prompt_builder(selected, header, phase, stage=stage, rows=primary, secondary=alternative,
                              examples=examples, scope_examples=ablation != "no_scope_examples", anchor_entities=grounding)
        schema = schema_builder(selected, header, phase=phase, stage=stage)
        report = {"phase": phase, "source_lines": [line["line"] for line in selected],
                  "prompt_chars": len(prompt), "schema_chars": len(json.dumps(schema)),
                  "literal_grounding": grounding, "source_rule_hints": False}
        calls += 1
        try:
            obj = client.call(prompt, schema)
        except ValueError as error:
            obj = {"lines": []}
            report["parse_error"] = str(error)
        reports.append(report)
        return obj, report

    def extract(phase, selected, *, apply=True, candidate=None):
        obj, report = request(phase, selected, primary=candidate)
        proposals, problems = output_validator(obj, selected, header, phase=phase, grounding=grounding)
        invalid = {problem["line"] for problem in problems if problem["line"] is not None}
        changed, retained = [], []
        if apply:
            for source in selected:
                n, proposal = source["line"], proposals[source["line"]]
                if (n in invalid or proposal["scope"] == "uncertain") and rows[n]["scope"] != "uncertain":
                    rows[n]["support"] = "provisional"
                    retained.append(n)
                    pending.add(n)
                    continue
                if reading_signature({n: proposal}) != reading_signature({n: rows[n]}):
                    changed.append(n)
                rows[n] = proposal
                if n in invalid or proposal["scope"] == "uncertain":
                    pending.add(n)
                else:
                    pending.discard(n)
        report.update({"problems": problems, "proposed_rows": list(proposals.values()),
                       "changed_lines": changed, "retained_previous_lines": retained})
        return proposals

    def review():
        selected, reasons = sources, {}
        if named and ablation != "no_focus":
            invalid = {p["line"] for r in reports for p in r.get("problems", []) if p["line"] is not None}
            reasons = contract.review_targets(sources, header, rows, secondary, invalid)
            selected = [s for s in sources if s["line"] in reasons] or sources
        selected_ids = {s["line"] for s in selected}
        obj, report = request("review", selected, primary=rows, alternative=secondary)
        if named:
            report.update(target_reasons=reasons, untouched_lines=sorted(set(rows) - selected_ids))
        grouped, problems = {}, []
        for proposal in obj.get("lines", []):
            n = proposal.get("line") if isinstance(proposal, dict) else None
            if type(n) is not int or n not in selected_ids:
                problems.append({"line": None, "errors": ["unexpected source line"]})
                continue
            grouped.setdefault(n, []).append(proposal)
        before = deepcopy(rows)
        changed, unresolved = [], []
        for source in selected:
            n = source["line"]
            candidates = grouped.get(n, [])
            if len(candidates) != 1:
                proposal, errors = None, ["duplicate source row" if candidates else "omitted source row"]
            else:
                proposal, errors = review_validator(candidates[0], source, header, before[n], grounding=grounding)
            if errors:
                problems.append({"line": n, "errors": errors, "rejected_rows": candidates})
                rows[n] = {**before[n], "support": "provisional"}
                pending.add(n)
                unresolved.append(n)
                continue
            rows[n] = proposal
            if reading_signature({n: proposal}) != reading_signature({n: before[n]}):
                changed.append(n)
            if proposal["support"] == "unresolved":
                pending.add(n)
                unresolved.append(n)
            else:
                pending.discard(n)
        report.update({"problems": problems, "actions": obj.get("lines", []), "proposed_rows": list(rows.values()),
                       "changed_lines": changed, "unresolved_review_lines": unresolved,
                       "retained_previous_lines": unresolved})

    def chunks(selected):
        if budget != "10x" or ablation == "no_chunking":
            return [selected]
        size = max(4, math.ceil(len(selected) / 6))
        return [selected[i:i + size] for i in range(0, len(selected), size)]

    if budget == "1x":
        extract("extract", sources)
    elif base_stage != "review":
        obj, report = request("classify", sources)
        scopes, problems = validate_statuses(obj, sources)
        report.update({"statuses": scopes, "problems": problems})
        selected = sources if ablation == "no_filter" else [line for line in sources if scopes[line["line"]] != "ignored"]
        if ablation != "no_filter":
            for n, status in scopes.items():
                if status == "ignored":
                    rows[n] = {"line": n, "scope": "nonclue", "claims": [], "support": "provisional", "structurally_valid": True}
        for chunk in chunks(selected or sources):
            extract("extract", chunk)
        if ablation != "no_audit":
            extract("audit", sources, candidate=rows)
    else:
        # No hard scope filter: both independent reads see every original line.
        for chunk in chunks(sources):
            extract("extract", chunk)
        if ablation != "no_independent":
            secondary = extract("independent", sources, apply=False)
            fallback = []
            for n, proposal in secondary.items():
                if rows[n]["scope"] == "uncertain" and proposal["scope"] != "uncertain":
                    rows[n] = deepcopy(proposal)
                    fallback.append(n)
            reports[-1]["primary_fallback_lines"] = fallback
        if ablation != "no_audit":
            review()

    repair_count, reviewed = 0, set()
    while budget == "10x" and calls < cap and repair_count < 2:
        facts = facts_from_rows(rows, sources)
        _, solutions = derive_answer(header, facts)
        targets = pending | {n for n, row in rows.items() if row["scope"] == "uncertain"}
        if not solutions:
            targets |= {fact["line"] for fact in minimal_conflict(header, facts)}
        elif len(solutions) > 4:
            targets |= {n for n, row in rows.items() if row["scope"] == "current_clue"}
            if not targets:
                targets = set(rows)
        targets -= reviewed
        if not targets:
            break
        ordered = sorted(targets, key=lambda n: (n not in pending, n))[:6]
        selected = [source for source in sources if source["line"] in ordered]
        previous = reading_signature(rows)
        extract("reread" if base_stage == "review" else "repair", selected)
        repair_count += 1
        reviewed.update(ordered)
        if previous != reading_signature(rows):
            reviewed.clear()
        elif targets <= reviewed:
            break

    facts = facts_from_rows(rows, sources)
    answer, solutions = derive_answer(header, facts)
    trace = {"architecture": "model_led_named_v3" if named else "model_led_incremental_v2", "development_stage": stage,
             "wire_contract": "named_typed_roles" if named else "flat_readable_names", "budget": budget, "ablation": ablation,
             "components": {"named_typed_roles": named,
                            "focused_review": named and base_stage == "review" and budget != "1x" and ablation not in ("no_audit", "no_focus"),
                            "paired_examples": base_stage in ("examples", "review") and examples and ablation != "no_scope_examples",
                            "independent_read": base_stage == "review" and budget != "1x" and ablation != "no_independent",
                            "action_review": base_stage == "review" and budget != "1x" and ablation != "no_audit"},
             "header": header, "symbols": symbol_table(header), "source_rules_enabled": False,
             "literal_grounding_enabled": grounding, "scope_filter": scopes,
             "extraction_reports": reports, "final_rows": list(rows.values()), "facts": facts,
             "secondary_rows": list(secondary.values()) if secondary is not None else None,
             "unresolved_lines": sorted(pending | {n for n, row in rows.items() if row["scope"] == "uncertain"}),
             "provisional_lines": sorted(n for n, row in rows.items() if row.get("support") != "supported"),
             "solution_count": len(solutions), "excess_solutions": len(solutions) > 4,
             "model_calls": calls, "raw_model_outputs": getattr(client, "raw_outputs", []),
             "call_metadata": getattr(client, "call_metadata", [])}
    return answer, calls, trace
