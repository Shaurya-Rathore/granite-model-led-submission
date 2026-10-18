"""Exhaustive reasoning over model-produced atoms, with generic time refs."""
from __future__ import annotations

import itertools
from typing import Any

from .representation import symbol_table


def facts_from_rows(rows: dict[int, dict[str, Any]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = {line["line"]: line["text"] for line in sources}
    return [{"line": line_no, "quote": text[line_no], **claim}
            for line_no, row in sorted(rows.items()) if row["scope"] == "current_clue"
            for claim in row["claims"]]


def holds(claim, times, owners, header, symbols):
    def at(token):
        spec = symbols[token]
        if spec["kind"] == "person":
            return times[spec["name"]]
        if spec["kind"] == "station_holder":
            return times[owners[spec["name"]]]
        return header["blocks"].index(spec["name"])
    op = claim["op"]
    if op == "block":
        value = at(claim["person"]) == at(claim["block"])
    elif op == "station":
        value = owners[symbols[claim["station"]]["name"]] == symbols[claim["person"]]["name"]
    elif op == "before":
        value = at(claim["earlier"]) < at(claim["later"])
    elif op == "next":
        value = at(claim["later"]) == at(claim["earlier"]) + 1
    elif op == "between":
        a, b = (at(token) for token in claim["ends"])
        value = min(a, b) < at(claim["middle"]) < max(a, b)
    else:
        raise ValueError(f"Unsupported op: {op}")
    return value if claim["polarity"] == "affirmed" else not value


def enumerate_solutions(header, facts):
    symbols = symbol_table(header)
    result = []
    for people in itertools.permutations(header["staff"]):
        times = {name: i for i, name in enumerate(people)}
        for holders in itertools.permutations(header["station_holders"]):
            owners = dict(zip(header["stations"], holders))
            if all(holds(fact, times, owners, header, symbols) for fact in facts):
                assignment = {name: {"block": header["blocks"][times[name]]} for name in header["staff"]}
                for station, name in owners.items():
                    assignment[name]["station"] = station
                result.append(assignment)
    return result


def minimal_conflict(header, facts):
    if enumerate_solutions(header, facts):
        return []
    groups = {}
    for fact in facts:
        groups.setdefault(fact["line"], []).append(fact)
    kept = sorted(groups)
    for line_no in list(kept):
        trial = [n for n in kept if n != line_no]
        candidate = [fact for n in trial for fact in groups[n]]
        if not enumerate_solutions(header, candidate):
            kept = trial
    return [fact for n in kept for fact in groups[n]]


def derive_answer(header, facts):
    solutions = enumerate_solutions(header, facts)
    if len(solutions) == 1:
        return {"case": "unique", "assignment": solutions[0]}, solutions
    if not solutions:
        citations = list(dict.fromkeys(fact["quote"] for fact in minimal_conflict(header, facts)))
        return {"case": "inconsistent", "conflicts": citations}, solutions
    return {"case": "ambiguous", "assignments": solutions}, solutions
