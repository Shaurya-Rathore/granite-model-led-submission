"""Small model contract; bind literal names to the unchanged solver IR."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .representation import VERDICTS, literal_present, symbol_table, validate_row

STATUSES = ("asserted", "ignored", "unclear")
ACTIONS = ("keep", "remove", "replace", "unresolved")
OPS = ("block", "station", "before", "next", "between")


def references(header):
    symbols = symbol_table(header)
    counts = Counter(spec["name"] for spec in symbols.values())
    # Prefix only genuinely ambiguous labels; this is header identity binding.
    return {(spec["name"] if counts[spec["name"]] == 1 else spec["kind"] + ":" + spec["name"]): token
            for token, spec in symbols.items()}


def literal_references(text, header):
    symbols = symbol_table(header)
    return [label for label, token in references(header).items() if literal_present(symbols[token]["name"], text)]


def response_schema(lines, header, *, phase, stage="schema"):
    fact = {"type": "object", "properties": {
        "op": {"type": "string", "enum": list(OPS)},
        "args": {"type": "array", "items": {"type": "string", "enum": list(references(header))}, "minItems": 2, "maxItems": 3},
        "negated": {"type": "boolean"}}, "required": ["op", "args", "negated"], "additionalProperties": False}
    fields = {"line": {"type": "integer", "enum": [line["line"] for line in lines]}}
    if phase == "review":
        fields["action"] = {"type": "string", "enum": list(ACTIONS)}
    else:
        fields["status"] = {"type": "string", "enum": list(STATUSES)}
    if phase != "classify":
        fields["facts"] = {"type": "array", "items": fact, "minItems": 0, "maxItems": 3}
    if phase in ("audit", "repair"):
        # Retain v1's audit policy only in the first two incremental stages.
        fields["verdict"] = {"type": "string", "enum": list(VERDICTS)}
    row = {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    return {"type": "json_schema", "json_schema": {"name": "model_shift_" + phase, "strict": True,
            "schema": {"type": "object", "properties": {"lines": {"type": "array", "items": row,
                        "minItems": len(lines), "maxItems": len(lines)}}, "required": ["lines"], "additionalProperties": False}}}


def compile_fact(fact, source, header):
    """Only argument binding; no source-language interpretation occurs here."""
    if not isinstance(fact, dict) or set(fact) != {"op", "args", "negated"}:
        raise ValueError("fact must contain exactly op, args, and negated")
    op, args = fact["op"], fact["args"]
    if not isinstance(op, str) or op not in OPS:
        raise ValueError("unknown operator")
    if type(fact["negated"]) is not bool:
        raise ValueError("negated must be a JSON boolean")
    if not isinstance(args, list) or len(args) != (3 if op == "between" else 2):
        raise ValueError("operator has the wrong argument count")
    refs = references(header)
    if any(not isinstance(label, str) or label not in refs for label in args):
        raise ValueError("argument is not an exact header reference")
    tokens = [refs[label] for label in args]
    roles = ({"person": tokens[0], "block": tokens[1]} if op == "block" else
             {"person": tokens[0], "station": tokens[1]} if op == "station" else
             {"middle": tokens[0], "ends": tokens[1:]} if op == "between" else
             {"earlier": tokens[0], "later": tokens[1]})
    return {"op": op, **roles, "polarity": "negated" if fact["negated"] else "affirmed",
            "evidence": source["text"]}


def flat_fact(claim, header):
    labels = {token: label for label, token in references(header).items()}
    op = claim["op"]
    args = ([claim["person"], claim[op]] if op in ("block", "station") else
            [claim["middle"], *claim["ends"]] if op == "between" else
            [claim["earlier"], claim["later"]])
    return {"op": op, "args": [labels[token] for token in args], "negated": claim["polarity"] == "negated"}


def flat_row(row, header, *, include_verdict=False):
    status = "asserted" if row["scope"] == "current_clue" else "unclear" if row["scope"] == "uncertain" else "ignored"
    result = {"line": row["line"], "status": status, "facts": [flat_fact(c, header) for c in row["claims"]]}
    if include_verdict:
        result["verdict"] = row.get("verdict", "supported")
    return result


def compile_row(row, source, header, *, phase="extract", grounding=True):
    expected = {"line", "status", "facts"} | ({"verdict"} if phase in ("audit", "repair") else set())
    if not isinstance(row, dict) or set(row) != expected or type(row.get("line")) is not int or row["line"] != source["line"]:
        return None, ["invalid flat row fields or identifier"]
    if row.get("status") not in STATUSES or not isinstance(row.get("facts"), list):
        return None, ["invalid status or facts array"]
    if row["status"] == "asserted" and not 1 <= len(row["facts"]) <= 3:
        return None, ["asserted row needs one to three facts"]
    if row["status"] != "asserted" and row["facts"]:
        return None, ["ignored or unclear row must not assert facts"]
    try:
        claims = [compile_fact(fact, source, header) for fact in row["facts"]]
    except ValueError as error:
        return None, [str(error)]
    internal = {"line": row["line"], "scope": {"asserted": "current_clue", "ignored": "nonclue", "unclear": "uncertain"}[row["status"]],
                "claims": claims, **({"verdict": row["verdict"]} if phase in ("audit", "repair") else {})}
    errors = validate_row(internal, source, header, grounding=grounding)
    internal["structurally_valid"] = not errors
    internal["support"] = ("unresolved" if internal["scope"] == "uncertain" else
                           "supported" if phase in ("audit", "repair") and row["verdict"] == "supported" else "provisional")
    return internal, errors


def unknown(line_no):
    return {"line": line_no, "scope": "uncertain", "claims": [], "support": "unresolved", "structurally_valid": False}


def validate_output(obj, sources, header, *, phase="extract", grounding=True):
    source_map = {line["line"]: line for line in sources}
    rows, problems, seen = {}, [], set()
    for row in obj.get("lines", []):
        n = row.get("line") if isinstance(row, dict) else None
        if type(n) is not int or n not in source_map:
            problems.append({"line": None, "errors": ["unexpected source line"]})
            continue
        if n in seen:
            problems.append({"line": n, "errors": ["duplicate source row"]})
            rows[n] = unknown(n)
            continue
        seen.add(n)
        internal, errors = compile_row(row, source_map[n], header, phase=phase, grounding=grounding)
        if errors:
            problems.append({"line": n, "errors": errors, "rejected_row": row})
            rows[n] = unknown(n)
        else:
            rows[n] = internal
    for n in source_map.keys() - seen:
        problems.append({"line": n, "errors": ["omitted source row"]})
        rows[n] = unknown(n)
    return rows, problems


def validate_statuses(obj, sources):
    ids = {source["line"] for source in sources}
    statuses, problems, seen = {}, [], set()
    for row in obj.get("lines", []):
        n = row.get("line") if isinstance(row, dict) else None
        if type(n) is not int or n not in ids:
            problems.append({"line": None, "errors": ["unexpected source line"]})
            continue
        if n in seen:
            statuses[n] = "unclear"
            problems.append({"line": n, "errors": ["duplicate source row"]})
            continue
        seen.add(n)
        if set(row) != {"line", "status"} or row.get("status") not in STATUSES:
            statuses[n] = "unclear"
            problems.append({"line": n, "errors": ["invalid status row"]})
        else:
            statuses[n] = row["status"]
    for n in ids - seen:
        statuses[n] = "unclear"
        problems.append({"line": n, "errors": ["omitted source row"]})
    return statuses, problems


def review_row(row, source, header, prior, *, grounding=True):
    """An explicit model action, separate from JSON/type validity."""
    if not isinstance(row, dict) or set(row) != {"line", "action", "facts"} or type(row.get("line")) is not int or row["line"] != source["line"]:
        return None, ["invalid review row fields or identifier"]
    action, facts = row.get("action"), row.get("facts")
    if action not in ACTIONS or not isinstance(facts, list):
        return None, ["invalid review action or facts array"]
    if action == "replace":
        proposal, errors = compile_row({"line": row["line"], "status": "asserted", "facts": facts}, source, header, grounding=grounding)
        if not errors:
            proposal["support"] = "supported"
        return proposal, errors
    if facts:
        return None, ["only replace may contain new facts"]
    if action == "remove":
        return {"line": row["line"], "scope": "nonclue", "claims": [], "support": "supported", "structurally_valid": True}, []
    if action == "keep":
        if prior["scope"] == "uncertain":
            return None, ["cannot verify an unresolved candidate by keeping it"]
        return {**prior, "support": "supported"}, []
    # Preserve the existing interpretation as provisional, not source-verified.
    # Blindly withdrawing all uncertain rows lost the correct v1 conflict core.
    return {**prior, "support": "unresolved"}, []
