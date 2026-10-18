"""Generic semantic instructions and synthetic contrasts; no matched hints."""
import json

from .representation import render_claim, symbol_table, mentioned_symbols


SCOPE_GUIDE = """Decide what this line asserts about the current rota. A declarative claim is fully asserted even with a confidence/recall hedge. Explicit old arrangements, counterfactuals, open questions, preferences, and unrelated facility facts supply no current constraint. 'Could/might' alone is possible_only. An explicit declined slot request denies the requested assignment. Use uncertain when you cannot decide, instead of guessing a schedule fact. A real item may contain contradictory current claims: preserve them literally."""

OPERATORS = """Choose meaning, then encode it with these five operators:
block(person=P, block=T): named person occupies that fixed time block.
station(person=P, station=S): named person holds that station.
before(earlier=X, later=Y): time(X) < time(Y), any positive gap.
next(earlier=X, later=Y): Y is the immediate next block after X.
between(middle=X, ends=[Y,Z]): X is strictly between Y and Z; either endpoint order.
P symbols mean the named person's time. S symbols in a time relation mean the time of WHOEVER HOLDS THAT STATION; they never name a guessed person. T symbols mean a fixed block's time. Only station(...) assigns ownership.
polarity=affirmed means the source asserts the operator. negated means it explicitly denies the operator; polarity is never confidence. A negated between stays between with negated polarity. 'Not necessarily next to' imposes neither next nor not-next; preserve the affirmed middle relation. 'No intervening block' is next, not a negated between. Ordinary before/after does not assert next. A takes over from B: preserve the stated time direction, using next only when the gap is explicitly immediate. For assignment contrast, 'not X but Y' denies X and affirms Y; 'not only X but also Y' affirms both.
Do not solve or infer named times/ownership from a relation. Emit only the stated atomic claims. Each claim quotes evidence EXACTLY from its source line, including its named entities. Never import an entity or a clue from another line. Return one row per requested line; a current_clue row needs 1–3 claims, all other scopes need zero."""

EXAMPLES = """Small semantic contrasts, using hypothetical symbols A/B for people and I for the inspection-holder's time (use the actual symbol table for this item):
'A is earlier than B' -> before(A,B), affirmed.
'B is later than A' -> before(A,B), affirmed: the later subject goes SECOND.
'A starts after whoever holds inspection' -> before(I,A), affirmed; NOT station(A,I).
'A finishes before whoever holds inspection starts' -> before(A,I), affirmed.
'A hands immediately over to B' -> next(A,B), affirmed.
'B is surrounded in time by A and C, with no required adjacency' -> between(B,[A,C]), affirmed.
The wording explains the slots; these are teaching examples, not candidate interpretations of the input lines."""


def build_prompt(lines, header, phase, *, rows=None, examples=True, anchor_entities=True):
    symbols = symbol_table(header)
    table = {token: {**spec, "time_meaning": ("named person's block" if spec["kind"] == "person" else "unknown holder's block" if spec["kind"] == "station_holder" else "fixed block")}
             for token, spec in symbols.items()}
    source = [{"line": line["line"], "text": line["text"],
               **({"literal_symbols": mentioned_symbols(line["text"], symbols)} if anchor_entities else {})} for line in lines]
    setup = "Five distinct person blocks, ordered as in the header; three specified people each hold one distinct station. All other people hold none.\n" + json.dumps({"header": header, "symbols": table}, ensure_ascii=False)
    if phase == "classify":
        return "Task: filter scope only, not interpretation or solving. Return exactly one line/scope row for each source line.\n" + SCOPE_GUIDE + "\n" + setup + "\nSOURCE:\n" + json.dumps(source, ensure_ascii=False)
    task = "Interpret each source line independently into the five atomic operators."
    if phase == "audit":
        task = "Compare every original source line with its candidate reading. Verify current scope, operator, temporal direction, reference types, and polarity. Recover clues omitted by the filter. Return the correct complete row, with a verdict, for EVERY source line. The ledger is fallible; do not preserve it merely because another pass produced it."
    elif phase == "repair":
        task = "Independently reinterpret these selected source lines. They were flagged by the source audit, evidence/type checks, or solver diagnostics. Return a corrected complete row and verdict for each. Contradictions can be real: don't weaken the wording to make a schedule possible."
    prompt = task + "\n" + SCOPE_GUIDE + "\n" + OPERATORS + "\n" + setup
    if examples:
        prompt += "\n" + EXAMPLES
    prompt += "\nSOURCE:\n" + json.dumps(source, ensure_ascii=False)
    if phase == "audit" and rows is not None:
        readings = []
        for line in lines:
            row = rows.get(line["line"], {})
            meanings = [render_claim(claim, symbols) for claim in row.get("claims", [])]
            readings.append({"line": line["line"], "candidate_scope": row.get("scope", "not_extracted"), "candidate_meanings": meanings})
        prompt += "\nCANDIDATE READINGS (interpretations of model outputs, not source-rule answers):\n" + json.dumps(readings, ensure_ascii=False)
    return prompt
