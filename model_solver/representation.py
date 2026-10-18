"""Typed symbols, literal grounding and structural validation; no clue grammar."""
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


def claim_key(claim: dict[str, Any]) -> str:
    semantic = {k: v for k, v in claim.items() if k != "evidence"}
    if semantic.get("op") == "between" and isinstance(semantic.get("ends"), list):
        semantic["ends"] = sorted(semantic["ends"])
    return json.dumps(semantic, sort_keys=True, separators=(",", ":"))


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


def reading_signature(rows):
    # Ignore evidence formatting and the audit's reason when comparing meaning.
    return json.dumps({n: {"scope": row["scope"], "claims": sorted(claim_key(c) for c in row["claims"])}
                       for n, row in sorted(rows.items())}, sort_keys=True)
