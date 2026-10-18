"""A fixed typed wire contract; no source-language interpretation."""
from __future__ import annotations

from copy import deepcopy

from . import flat
from .representation import VERDICTS, symbol_table

ROLES = {
    "block": ("person", "block"),
    "station": ("person", "station"),
    "before": ("earlier", "later"),
    "next": ("earlier", "later"),
    "between": ("middle", "endpoint1", "endpoint2"),
}
unknown = flat.unknown


def label_groups(header):
    symbols = symbol_table(header)
    refs = flat.references(header)
    return {
        "person": [label for label, token in refs.items() if symbols[token]["kind"] == "person"],
        "block": [label for label, token in refs.items() if symbols[token]["kind"] == "block"],
        "station": [label for label, token in refs.items() if symbols[token]["kind"] == "station_holder"],
        "time": list(refs),
    }


def response_schema(lines, header, *, phase, stage="named_review"):
    groups = label_groups(header)
    variants = []
    for op, roles in ROLES.items():
        properties = {"op": {"type": "string", "enum": [op]}}
        for role in roles:
            kind = role if op in ("block", "station") else "time"
            properties[role] = {"type": "string", "enum": groups[kind]}
        properties["negated"] = {"type": "boolean"}
        variants.append({"type": "object", "properties": properties,
                         "required": list(properties), "additionalProperties": False})
    # Five fixed operator branches, independent of the wording/number of notes.
    facts = {"type": "array", "items": {"anyOf": variants}, "maxItems": 3}
    base = {"line": {"type": "integer", "enum": [s["line"] for s in lines]}}
    if phase == "classify":
        properties = {**base, "status": {"type": "string", "enum": list(flat.STATUSES)}}
        row = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    else:
        row_variants = []
        categories = ([("action", ["replace"], 1, 3),
                       ("action", ["keep", "remove", "unresolved"], 0, 0)] if phase == "review" else
                      [("status", ["asserted"], 1, 3), ("status", ["ignored", "unclear"], 0, 0)])
        for field, values, minimum, maximum in categories:
            properties = {**base, field: {"type": "string", "enum": values},
                          "facts": {**deepcopy(facts), "minItems": minimum, "maxItems": maximum}}
            if phase in ("audit", "repair"):
                properties["verdict"] = {"type": "string", "enum": list(VERDICTS)}
            row_variants.append({"type": "object", "properties": properties,
                                 "required": list(properties), "additionalProperties": False})
        row = {"anyOf": row_variants}
    return {"type": "json_schema", "json_schema": {"name": "named_shift_" + phase, "strict": True,
            "schema": {"type": "object", "properties": {"lines": {
                "type": "array", "items": row, "minItems": len(lines), "maxItems": len(lines)}},
                "required": ["lines"], "additionalProperties": False}}}


def to_flat_fact(fact, header):
    if not isinstance(fact, dict) or not isinstance(fact.get("op"), str) or fact["op"] not in ROLES:
        raise ValueError("unknown named operator")
    op = fact["op"]
    if set(fact) != {"op", "negated", *ROLES[op]}:
        raise ValueError("named fact has incorrect role fields")
    if type(fact["negated"]) is not bool:
        raise ValueError("negated must be a JSON boolean")
    groups = label_groups(header)
    args = []
    for role in ROLES[op]:
        value = fact[role]
        kind = role if op in ("block", "station") else "time"
        if not isinstance(value, str) or value not in groups[kind]:
            raise ValueError("named role uses the wrong reference type: " + role)
        args.append(value)
    return {"op": op, "args": args, "negated": fact["negated"]}


def named_fact(claim, header):
    wire = flat.flat_fact(claim, header)
    return {"op": wire["op"], **dict(zip(ROLES[wire["op"]], wire["args"])), "negated": wire["negated"]}


def compile_row(row, source, header, *, phase="extract", grounding=True):
    if not isinstance(row, dict) or not isinstance(row.get("facts"), list):
        return None, ["invalid named row or facts array"]
    try:
        converted = {**row, "facts": [to_flat_fact(fact, header) for fact in row["facts"]]}
    except ValueError as error:
        return None, [str(error)]
    return flat.compile_row(converted, source, header, phase=phase, grounding=grounding)


def validate_output(obj, sources, header, *, phase="extract", grounding=True):
    source_map = {s["line"]: s for s in sources}
    rows, problems, seen = {}, [], set()
    for row in obj.get("lines", []):
        n = row.get("line") if isinstance(row, dict) else None
        if type(n) is not int or n not in source_map:
            problems.append({"line": None, "errors": ["unexpected source line"]})
            continue
        if n in seen:
            rows[n] = unknown(n)
            problems.append({"line": n, "errors": ["duplicate source row"]})
            continue
        seen.add(n)
        compiled, errors = compile_row(row, source_map[n], header, phase=phase, grounding=grounding)
        rows[n] = unknown(n) if errors else compiled
        if errors:
            problems.append({"line": n, "errors": errors, "rejected_row": row})
    for n in source_map.keys() - seen:
        rows[n] = unknown(n)
        problems.append({"line": n, "errors": ["omitted source row"]})
    return rows, problems


def review_row(row, source, header, prior, *, grounding=True):
    if not isinstance(row, dict) or not isinstance(row.get("facts"), list):
        return None, ["invalid named review row"]
    try:
        converted = {**row, "facts": [to_flat_fact(fact, header) for fact in row["facts"]]}
    except ValueError as error:
        return None, [str(error)]
    return flat.review_row(converted, source, header, prior, grounding=grounding)


def review_targets(sources, header, primary, secondary, invalid_lines=()):
    """Prioritize disagreement/structure, never match relationship words."""
    from .representation import reading_signature
    reasons = {}
    for source in sources:
        n = source["line"]
        first, second = primary[n], secondary[n] if secondary is not None else primary[n]
        why = []
        if reading_signature({n: first}) != reading_signature({n: second}):
            why.append("independent_disagreement")
        if n in invalid_lines or not first.get("structurally_valid", True) or not second.get("structurally_valid", True):
            why.append("invalid_reading")
        if any(r["scope"] == "uncertain" for r in (first, second)):
            why.append("unclear_reading")
        if first["scope"] == second["scope"] == "nonclue" and len(flat.literal_references(source["text"], header)) >= 2:
            why.append("ignored_with_multiple_header_entities")
        if any(len(r["claims"]) > 1 or any(c["polarity"] == "negated" for c in r["claims"]) for r in (first, second)):
            why.append("negation_or_multiple_claims")
        if any(c["op"] == "next" for r in (first, second) for c in r["claims"]):
            why.append("adjacency_claim")
        if why:
            reasons[n] = why
    return reasons
