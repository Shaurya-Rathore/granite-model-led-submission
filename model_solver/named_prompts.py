"""Compact fixed instruction contrasts for named typed roles."""
import json

from .flat import literal_references
from .named import named_fact

SCOPE = """Read each original line for its assertion about the CURRENT rota. Confidence/recall hedges retain full force. Keep direct constraints, including station-holder timing, exclusions and fragments expressing succession. Ignore explicitly historical arrangements, hypothetical alternatives, open questions, preferences and unrelated events. A report that someone requested a change does not alone specify their actual current block; distinguish the reported request from an explicit current exclusion. Use unclear if that scope cannot be resolved from the words. Preserve genuine contradictions. Check both clauses in contrasts.
status=asserted requires all directly stated current facts (1–3). status=ignored means no current constraint. status=unclear means unresolved meaning. Ignored/unclear rows have facts=[]. Return every requested line exactly once. Do not drop a line merely because its constraint is awkward to encode."""

OPERATORS = """Use exact header labels and named roles, never positional args:
block(person,block,negated): person's fixed block; station(person,station,negated): station assignment.
before(earlier,later,negated): strictly earlier, any gap; next(earlier,later,negated): immediately earlier.
between(middle,endpoint1,endpoint2,negated): strictly between in EITHER endpoint order.
Time roles accept persons, station labels (the time of their UNKNOWN HOLDER), or fixed blocks. Station timing does not assign that station to the named person. Only person roles accept people; only station roles accept stations; only block roles accept fixed blocks. Ordinary earlier/later/before/after/precedes does NOT imply immediate succession: use before. Choose next only when the source explicitly requires no intervening block.
negated=false asserts the whole relation; true explicitly denies it. A word like 'no' does not mechanically negate the relation: absence of an intervening block ASSERTS adjacency. 'Not necessarily adjacent' leaves betweenness asserted and imposes no adjacency or nonadjacency. Do not choose an endpoint order for betweenness. Echo entity labels occurring in the source. Code supplies verbatim quotes from line IDs."""

RELATIONS = """Fixed hypothetical examples (use this item's names):
Mira is not on inspection -> {"op":"station","person":"Mira","station":"inspection","negated":true}
Mira works at 07:00 -> {"op":"block","person":"Mira","block":"07:00","negated":false}
Mira is later than Jules -> {"op":"before","earlier":"Jules","later":"Mira","negated":false}
Mira precedes Jules -> {"op":"before","earlier":"Mira","later":"Jules","negated":false}
Mira immediately precedes Jules -> {"op":"next","earlier":"Mira","later":"Jules","negated":false}
Mira starts after whoever holds inspection -> {"op":"before","earlier":"inspection","later":"Mira","negated":false}
Mira hands immediately over to Jules -> {"op":"next","earlier":"Mira","later":"Jules","negated":false}
Jules is between Mira and Sana -> {"op":"between","middle":"Jules","endpoint1":"Mira","endpoint2":"Sana","negated":false}"""

CONTRASTS = """Fixed source-to-meaning contrasts, shared across every item:
I believe Mira works at 07:00 -> asserted block(Mira,07:00,false).
We debated whether Mira works at 07:00 -> ignored; discussing a proposition does not assert it.
Mira worked at 07:00 last year -> ignored; explicitly historical.
If Mira worked at 07:00, parking would be easier -> ignored; hypothetical.
Mira asked about changing shifts -> ignored; no actual current assignment is stated.
Mira is unavailable at 07:00 -> asserted block(Mira,07:00,true).
Mira is after one of Jules and Sana and before the other -> between(middle=Mira,endpoint1=Jules,endpoint2=Sana,negated=false), never two 'before' facts putting Mira after both.
That means (Jules < Mira < Sana) OR (Sana < Mira < Jules). Output exactly {"op":"between","middle":"Mira","endpoint1":"Jules","endpoint2":"Sana","negated":false}. Do not emit two next facts, and do not choose an endpoint ordering.
Mira is between Jules and Sana, not necessarily adjacent to either -> the same positive between fact.
No block separates Mira and Jules, in that order -> next(earlier=Mira,later=Jules,negated=false).
Mira then Jules, back to back -> the same positive next fact.
Mira does not immediately precede Jules -> next(earlier=Mira,later=Jules,negated=true).
Inspection is covered before Mira starts -> before(earlier=inspection,later=Mira,negated=false).
Inspection is covered earlier in the day than Mira, or precedes Mira -> {"op":"before","earlier":"inspection","later":"Mira","negated":false}; the gap is unspecified, so next would add an unsupported constraint.
Inspection is Mira's station -> station(person=Mira,station=inspection,negated=false).
Mira is not on inspection but is on dispatch -> both station(Mira,inspection,true) and station(Mira,dispatch,false)."""

REVIEW = """Resolve the selected source lines against two fallible readings. Independently check the original words for scope, complete clauses, operator, typed roles, direction and negation. Both readings may be wrong; agreement is not proof. Pay attention to ignored lines and rejected readings. Recheck every next claim: earlier/later/precedes alone supports before, not next. Recheck multi-fact temporal readings: after one endpoint and before the other is one between fact with either endpoint order, never a pair of immediate-successor constraints.
Return one action per selected line: keep preserves the complete PRIMARY reading; remove explicitly withdraws its current claim; replace supplies the COMPLETE corrected named facts; unresolved preserves the primary provisionally. Only replace has nonempty facts. Never union incompatible readings. Use replace to recover a clue lost by the primary. Keep correct relations even if they create a real contradiction. You receive no proposed schedule."""


def build_prompt(lines, header, phase, *, stage, rows=None, secondary=None,
                 examples=True, scope_examples=True, anchor_entities=True):
    task = {
        "classify": "Classify current scope for every original line.",
        "extract": "Extract current constraints independently from EVERY original line; classify and encode together.",
        "independent": "Read EVERY original source line afresh. First identify its current assertion, then encode the exact typed relation. There is no prior extraction to preserve. Do not skip negative, station-holder, or compound temporal statements.",
        "audit": "Recheck all original lines against the fallible candidate reading. Recover omissions and return complete corrected rows plus a verdict.",
        "review": REVIEW,
        "repair": "Re-read these original lines independently. Return complete corrected readings and verdicts.",
        "reread": "Re-read these original lines independently. Return complete corrected current facts.",
    }[phase]
    parts = [task, SCOPE, "HEADER:", json.dumps(header, ensure_ascii=False)]
    if phase != "classify":
        parts.append(OPERATORS)
        if examples:
            parts.append(RELATIONS)
    if examples and scope_examples:
        parts.append(CONTRASTS)
    if phase in ("audit", "repair"):
        parts.append("verdict: supported, missing_clue, wrong_scope, wrong_operator, wrong_reference, reversed, wrong_polarity, or uncertain.")
    source = [{"line": s["line"], "text": s["text"],
               **({"entities": literal_references(s["text"], header)} if anchor_entities else {})} for s in lines]
    parts.extend(["SOURCE:", json.dumps(source, ensure_ascii=False, separators=(",", ":"))])
    if phase in ("audit", "review"):
        def reading(row):
            return {"status": {"current_clue": "asserted", "uncertain": "unclear"}.get(row["scope"], "ignored"),
                    "facts": [named_fact(c, header) for c in row["claims"]]}
        ledger = [{"line": s["line"], "primary": reading(rows[s["line"]]),
                   **({"secondary": reading(secondary[s["line"]])} if secondary is not None else {})} for s in lines]
        parts.extend(["CANDIDATE READINGS:", json.dumps(ledger, ensure_ascii=False, separators=(",", ":"))])
    return "\n".join(parts)
