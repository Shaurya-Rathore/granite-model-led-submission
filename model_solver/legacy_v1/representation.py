"""Typed symbols, literal grounding, and model schemas; no clue grammar."""
from __future__ import annotations

import json
import re
from typing import Any

SCOPES = ("current_clue", "nonclue", "historical", "hypothetical", "open_question", "possible_only", "uncertain")
VERDICTS = ("supported", "missing_clue", "wrong_scope", "wrong_operator", "wrong_reference", "reversed", "wrong_polarity", "uncertain")


def symbol_table(header: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {f"{prefix}{i}": {"kind": kind, "name": name}
            for prefix, kind, field in (("P", "person", "staff"), ("S", "station_holder", "stations"), ("T", "block", "blocks"))
            for i, name in enumerate(header[field])}


def literal_present(value: str, text: str) -> bool:
    # Entity anchoring only: this never selects an operator or interpretation.
    return re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.IGNORECASE) is not None


def mentioned_symbols(text: str, symbols: dict[str, dict[str, str]]) -> list[str]:
    return [token for token, spec in symbols.items() if literal_present(spec["name"], text)]


def claim_key(claim: dict[str, Any]) -> str:
    semantic = {k: v for k, v in claim.items() if k != "evidence"}
    if semantic.get("op") == "between" and isinstance(semantic.get("ends"), list):
        semantic["ends"] = sorted(semantic["ends"])
    return json.dumps(semantic, sort_keys=True, separators=(",", ":"))


def response_schema(lines: list[dict[str, Any]], header: dict[str, Any], *, phase: str, anchor_entities: bool = True) -> dict[str, Any]:
    symbols = symbol_table(header)
    variants = []
    for line in lines:
        mentioned = set(mentioned_symbols(line["text"], symbols))
        def tokens(kinds):
            all_tokens = [k for k, spec in symbols.items() if spec["kind"] in kinds]
            present = [k for k in all_tokens if k in mentioned]
            return {"type": "string", "enum": present if anchor_entities and present else all_tokens}
        people = tokens({"person"})
        stations = tokens({"station_holder"})
        blocks = tokens({"block"})
        times = tokens({"person", "station_holder", "block"})
        claims = []
        for op, roles in (
            ("block", {"person": people, "block": blocks}),
            ("station", {"person": people, "station": stations}),
            ("before", {"earlier": times, "later": times}),
            ("next", {"earlier": times, "later": times}),
            ("between", {"middle": times, "ends": {"type": "array", "items": times, "minItems": 2, "maxItems": 2}}),
        ):
            fields = {"op": {"type": "string", "enum": [op]},
                      "polarity": {"type": "string", "enum": ["affirmed", "negated"]},
                      "evidence": {"type": "string"}, **roles}
            claims.append({"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False})
        for current in (True, False):
            fields = {"line": {"type": "integer", "enum": [line["line"]]},
                      "scope": {"type": "string", "enum": ["current_clue"] if current else [x for x in SCOPES if x != "current_clue"]}}
            if phase == "classify":
                # Scope filtering is a deliberately smaller, separate task.
                if not current:
                    fields["scope"]["enum"] = [x for x in SCOPES if x != "current_clue"]
            else:
                fields["claims"] = {"type": "array", "items": {"anyOf": claims}, "minItems": 1 if current else 0, "maxItems": 3 if current else 0}
                if phase in ("audit", "repair"):
                    fields["verdict"] = {"type": "string", "enum": list(VERDICTS)}
            variants.append({"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False})
    return {"type": "json_schema", "json_schema": {"name": "model_shift_" + phase, "strict": True,
            "schema": {"type": "object", "properties": {"lines": {"type": "array", "items": {"anyOf": variants}, "minItems": len(lines), "maxItems": len(lines)}},
                       "required": ["lines"], "additionalProperties": False}}}


def render_claim(claim: dict[str, Any], symbols: dict[str, dict[str, str]]) -> str:
    def ref(token):
        spec = symbols[token]
        if spec["kind"] == "person":
            return "the time of " + spec["name"]
        if spec["kind"] == "station_holder":
            return "the time of whoever holds " + spec["name"]
        return "the fixed " + spec["name"] + " block"
    op = claim["op"]
    if op == "block":
        text = symbols[claim["person"]]["name"] + " is assigned to " + symbols[claim["block"]]["name"]
    elif op == "station":
        text = symbols[claim["person"]]["name"] + " holds " + symbols[claim["station"]]["name"]
    elif op in ("before", "next"):
        text = ref(claim["earlier"]) + (" is immediately before " if op == "next" else " is strictly before ") + ref(claim["later"])
    else:
        a, b = claim["ends"]
        text = ref(claim["middle"]) + " is strictly between " + ref(a) + " and " + ref(b) + "; either endpoint order is allowed"
    return "The source denies that: " + text if claim["polarity"] == "negated" else "The source asserts that: " + text


def validate_row(row: dict[str, Any], line: dict[str, Any], header: dict[str, Any], *, grounding: bool = True) -> list[str]:
    errors = []
    if not isinstance(row, dict) or type(row.get("line")) is not int or row["line"] != line["line"] or row.get("scope") not in SCOPES:
        return ["invalid line identifier or scope"]
    claims = row.get("claims")
    if not isinstance(claims, list):
        return ["missing claims array"]
    if row["scope"] != "current_clue" and claims:
        return ["noncurrent or uncertain row contains hard claims"]
    if row["scope"] == "current_clue" and not 1 <= len(claims) <= 3:
        return ["current clue must contain one to three atomic claims"]
    if "verdict" in row and row["verdict"] not in VERDICTS:
        return ["invalid audit verdict"]
    if row.get("verdict") == "uncertain" and row["scope"] == "current_clue":
        return ["audit marked a proposed hard claim uncertain"]
    symbols = symbol_table(header)
    shapes = {"block": {"person", "block"}, "station": {"person", "station"},
              "before": {"earlier", "later"}, "next": {"earlier", "later"}, "between": {"middle", "ends"}}
    seen = set()
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("op"), str) or claim["op"] not in shapes:
            errors.append("unknown atomic operator")
            continue
        op = claim["op"]
        if set(claim) != {"op", "polarity", "evidence", *shapes[op]} or claim["polarity"] not in ("affirmed", "negated") or not isinstance(claim["evidence"], str):
            errors.append("invalid claim shape or polarity")
            continue
        if op == "between" and (not isinstance(claim["ends"], list) or len(claim["ends"]) != 2):
            errors.append("between requires exactly two endpoints")
            continue
        roles = []
        for field in shapes[op]:
            value = claim[field]
            if field == "ends":
                roles.extend(value)
            else:
                roles.append(value)
        if any(not isinstance(token, str) or token not in symbols for token in roles):
            errors.append("reference is not in this item's symbol table")
            continue
        if op in ("block", "station"):
            if symbols[claim["person"]]["kind"] != "person" or symbols[claim[op]]["kind"] != ("block" if op == "block" else "station_holder"):
                errors.append("assignment uses the wrong reference types")
        elif len(roles) != len(set(roles)):
            errors.append("temporal relation repeats an identical reference")
        evidence = claim["evidence"]
        if not evidence.strip() or evidence not in line["text"]:
            errors.append("evidence is not copied verbatim from this line")
        elif grounding:
            for token in roles:
                if not literal_present(symbols[token]["name"], evidence):
                    errors.append(f"{token} is not named in the quoted evidence")
        signature = claim_key(claim)
        if signature in seen:
            errors.append("duplicate atomic claim")
        seen.add(signature)
    return errors


def validate_output(obj: dict[str, Any], lines: list[dict[str, Any]], header: dict[str, Any], *, grounding: bool = True, phase: str = "extract"):
    """Quarantine malformed/ungrounded rows without inventing their meaning."""
    source = {line["line"]: line for line in lines}
    rows, problems, seen = {}, [], set()
    for row in obj.get("lines", []):
        if not isinstance(row, dict) or type(row.get("line")) is not int or row["line"] not in source:
            problems.append({"line": None, "errors": ["unexpected source line"]})
            continue
        line_no = row["line"]
        if line_no in seen:
            problems.append({"line": line_no, "errors": ["duplicate source row"]})
            rows[line_no] = {"line": line_no, "scope": "uncertain", "claims": []}
            continue
        seen.add(line_no)
        errors = validate_row(row, source[line_no], header, grounding=grounding)
        if phase in ("audit", "repair") and row.get("verdict") not in VERDICTS:
            errors.append("audit or repair omitted its verdict")
        if errors:
            problems.append({"line": line_no, "errors": errors, "rejected_row": row})
            rows[line_no] = {"line": line_no, "scope": "uncertain", "claims": []}
        else:
            rows[line_no] = row
    for line_no in source.keys() - seen:
        problems.append({"line": line_no, "errors": ["omitted source row"]})
        rows[line_no] = {"line": line_no, "scope": "uncertain", "claims": []}
    return rows, problems
