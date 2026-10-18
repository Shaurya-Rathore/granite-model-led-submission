"""Selectable prompt increments; all source interpretation stays with Granite."""
import json

from .flat import flat_fact, literal_references
from .representation import render_claim, symbol_table

SCOPE = """Decide what this line asserts about the current rota. A declarative claim is fully asserted even with a confidence/recall hedge. Explicit old arrangements, counterfactuals, open questions, preferences, and unrelated facility facts supply no current constraint. Mere possibilities supply no hard constraint. An explicit declined slot request denies the requested assignment. Use unclear when you cannot decide. Genuine current contradictions must be preserved.
status=asserted: this line asserts one or more encodable current-rota constraints.
status=ignored: this line asserts no current-rota constraint.
status=unclear: you cannot safely choose a current constraint; emit no facts."""

OPERATORS = """Use exact readable references from the header and these five operators:
block args=[person, fixed block]: person occupies that block.
station args=[person, station]: person holds that station.
before args=[earlier, later]: strictly earlier, any positive gap.
next args=[earlier, later]: immediately preceding block.
between args=[middle, endpoint1, endpoint2]: strictly between, either endpoint order.
A person reference in a time relation means that person's time. A station reference means the time of its UNKNOWN HOLDER, not an inferred ownership assignment. A fixed block means its header position.
negated=false asserts the operator. negated=true explicitly denies it. Confidence is not negation. Negated betweenness stays between with negated=true. 'Not necessarily next to' adds neither adjacency nor nonadjacency. 'No intervening block' denotes immediate succession when its direction is stated. Ordinary before/after does not assert next. Assignment contrast can assert an exclusion and an inclusion; 'not only' is not an exclusion.
Emit only what the source states, without inferring named times or station ownership. Arguments must occur in their source line. Facts contain exactly op, args, and negated. Return every requested line. Asserted rows need 1–3 facts; ignored and unclear rows need none. Quotes need not be repeated: code binds each line identifier to its original verbatim text."""

RELATION_EXAMPLES = """Small semantic contrasts with hypothetical names; use the actual header names for this item:
Source: Mira is earlier than Jules.
Fact: {"op":"before","args":["Mira","Jules"],"negated":false}
Source: Jules is later than Mira.
Fact: {"op":"before","args":["Mira","Jules"],"negated":false}
Source: Mira starts after whoever holds inspection.
Fact: {"op":"before","args":["inspection","Mira"],"negated":false}
Source: Mira finishes before whoever holds inspection starts.
Fact: {"op":"before","args":["Mira","inspection"],"negated":false}
Source: Mira hands immediately over to Jules.
Fact: {"op":"next","args":["Mira","Jules"],"negated":false}
Source: Jules is surrounded in time by Mira and Sana, with no required adjacency.
Fact: {"op":"between","args":["Jules","Mira","Sana"],"negated":false}
These teach argument slots, not candidate meanings of the input."""

PAIRED_EXAMPLES = """Read the outer assertion before extracting an embedded proposition. A hedge on a direct assignment does not weaken it. A report of discussion, uncertainty, or a question does not assert the assignment discussed. Here are hypothetical complete rows; names are teaching examples:
Source line 2: I believe Mira works at 07:00.
{"line":2,"status":"asserted","facts":[{"op":"block","args":["Mira","07:00"],"negated":false}]}
Source line 3: We debated whether Mira works at 07:00.
{"line":3,"status":"ignored","facts":[]}
Source line 4: Nobody remembered whether Mira works at 07:00.
{"line":4,"status":"ignored","facts":[]}
Source line 5: Mira worked at 07:00 last year.
{"line":5,"status":"ignored","facts":[]}
Source line 6: If Mira worked at 07:00, parking would be easier.
{"line":6,"status":"ignored","facts":[]}
Source line 7: Mira requested 07:00 and was refused.
{"line":7,"status":"asserted","facts":[{"op":"block","args":["Mira","07:00"],"negated":true}]}
Source line 8: I am fairly sure Mira is not on inspection.
{"line":8,"status":"asserted","facts":[{"op":"station","args":["Mira","inspection"],"negated":true}]}
Source line 9: Mira is after one of Jules and Sana and before the other.
{"line":9,"status":"asserted","facts":[{"op":"between","args":["Mira","Jules","Sana"],"negated":false}]}
Source line 10: Mira then Jules, back to back.
{"line":10,"status":"asserted","facts":[{"op":"next","args":["Mira","Jules"],"negated":false}]}
These are fixed paired examples for all items; no source-matched semantic hints are supplied."""

REVIEW = """Check every original source line independently against its proposed reading, including rows currently ignored. Output one action per requested line:
keep: the PRIMARY reading accurately and completely captures the current assertion, or correctly ignores a nonclue. facts=[]
remove: the primary asserted a current constraint that the source does not assert. facts=[]
replace: the primary omitted or misread a current constraint; supply its complete corrected facts.
unresolved: you cannot safely decide. facts=[]
The secondary reading is another fallible model interpretation, not authority. If it is correct, use replace with its facts; never merge incompatible readings. Verify operator, complete clause set, direction, reference type, and explicit negation. Betweenness does not choose which endpoint comes first. Keep confidence hedges at full force. Do not decide using a proposed schedule or try to eliminate genuine contradictions."""


def build_prompt(lines, header, phase, *, stage, rows=None, secondary=None, examples=True, scope_examples=True, anchor_entities=True):
    source = [{"line": line["line"], "text": line["text"],
               **({"literal_entities": literal_references(line["text"], header)} if anchor_entities else {})} for line in lines]
    task = {
        "classify": "Classify scope only. Return one line/status row for every source line.",
        "extract": "Interpret each source line independently into literal current-rota facts.",
        "independent": "Read the complete original source afresh. Identify exactly what each line asserts before choosing its operator and arguments. You have no prior extraction to preserve.",
        "audit": "Compare every source line with its candidate reading and return the correct complete line/status/facts row plus a verdict. Recover omitted current clues; candidate readings are fallible.",
        "repair": "Independently reinterpret these selected source lines. Preserve genuine contradictions and do not infer a schedule.",
        "reread": "Independently reinterpret these selected source lines. Preserve genuine contradictions and do not infer a schedule.",
        "review": REVIEW,
    }[phase]
    prompt = task + "\n" + SCOPE + "\nHEADER:\n" + json.dumps(header, ensure_ascii=False)
    if phase != "classify":
        prompt += "\n" + OPERATORS
        if examples:
            prompt += "\n" + RELATION_EXAMPLES
    if stage in ("examples", "review") and examples and scope_examples:
        prompt += "\n" + PAIRED_EXAMPLES
    if phase in ("audit", "repair"):
        prompt += "\nverdict: supported, missing_clue, wrong_scope, wrong_operator, wrong_reference, reversed, wrong_polarity, or uncertain."
    prompt += "\nSOURCE:\n" + json.dumps(source, ensure_ascii=False)
    if phase in ("audit", "review"):
        symbols = symbol_table(header)
        def reading(row):
            row = row or {"scope": "uncertain", "claims": []}
            return {"status": "asserted" if row["scope"] == "current_clue" else "unclear" if row["scope"] == "uncertain" else "ignored",
                    "facts": [flat_fact(c, header) for c in row["claims"]],
                    "meanings": [render_claim(c, symbols) for c in row["claims"]]}
        ledger = [{"line": line["line"], "primary": reading((rows or {}).get(line["line"])),
                   **({"secondary": reading((secondary or {}).get(line["line"]))} if phase == "review" else {})} for line in lines]
        prompt += "\nCANDIDATE READINGS:\n" + json.dumps(ledger, ensure_ascii=False)
    return prompt
