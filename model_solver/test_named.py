"""Synthetic checks for typed names and independent focused review."""
from copy import deepcopy
import json
import unittest

from . import flat, named
from .engine import derive_answer, facts_from_rows
from .incremental import process_item
from .named_prompts import build_prompt
from .legacy_v1.test_model_solver import HEADER, HEADER_TEXT, ITEM, SOURCES, fixture_rows


def rows():
    return [named.named_row(row, HEADER) for row in fixture_rows()]


def schema_ids(schema):
    row = schema["json_schema"]["schema"]["properties"]["lines"]["items"]
    props = row.get("properties", row.get("anyOf", [{}])[0].get("properties"))
    return props["line"]["enum"]


def keep_requested(prompt, schema):
    return {"lines": [{"line": n, "action": "keep", "facts": []} for n in schema_ids(schema)]}


class Client:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls, self.prompts, self.formats, self.raw_outputs = 0, [], [], []

    def call(self, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        self.formats.append(schema)
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            result = result(prompt, schema)
        self.raw_outputs.append(json.dumps(result))
        return result


class NamedContractTests(unittest.TestCase):
    def test_all_operator_polarity_round_trips(self):
        source = {"line": 2, "text": "Amal Bea Cora intake packing calibration 07:00 09:00 11:00"}
        facts = [dict(op="block", person="Amal", block="07:00"),
                 dict(op="station", person="Amal", station="intake"),
                 dict(op="before", earlier="packing", later="Bea"),
                 dict(op="next", earlier="Amal", later="09:00"),
                 dict(op="between", middle="Bea", endpoint1="Amal", endpoint2="Cora")]
        for fact in facts:
            for negated in (False, True):
                row = {"line": 2, "status": "asserted", "facts": [{**fact, "negated": negated}]}
                compiled, errors = named.compile_row(row, source, HEADER)
                self.assertEqual(errors, [])
                self.assertEqual(named.named_row(compiled, HEADER), row)

    def test_wrong_named_types_and_fields_rejected(self):
        source = {"line": 2, "text": "Amal Bea intake 07:00"}
        bad = [dict(op="station", person="intake", station="Amal", negated=False),
               dict(op="block", person="Amal", block="intake", negated=False),
               dict(op="station", person="Amal", station="intake", negated="false"),
               dict(op="before", args=["Amal", "Bea"], negated=False),
               dict(op="between", middle="Amal", endpoint1="Bea", negated=False),
               dict(op="before", earlier="Amal", later="Bea", invented=True, negated=False)]
        for fact in bad:
            _, errors = named.compile_row({"line": 2, "status": "asserted", "facts": [fact]}, source, HEADER)
            self.assertTrue(errors)

    def test_schema_roles_are_typed_and_fixed_across_wording(self):
        a = named.response_schema([{"line": 2, "text": "Amal holds intake."}], HEADER, phase="extract")
        b = named.response_schema([{"line": 2, "text": "Amal precedes Bea."}], HEADER, phase="extract")
        self.assertEqual(a, b)
        fact_variants = a["json_schema"]["schema"]["properties"]["lines"]["items"]["anyOf"][0]["properties"]["facts"]["items"]["anyOf"]
        self.assertEqual(len(fact_variants), 5)
        station = fact_variants[1]["properties"]
        self.assertIn("Amal", station["person"]["enum"])
        self.assertNotIn("intake", station["person"]["enum"])
        self.assertIn("intake", station["station"]["enum"])
        self.assertNotIn("Amal", station["station"]["enum"])
        self.assertEqual(fact_variants[0]["properties"]["block"]["enum"], HEADER["blocks"])
        self.assertLess(len(json.dumps(a)), 10000)

    def test_schema_does_not_grow_operator_branches_per_source(self):
        a = named.response_schema(SOURCES[:1], HEADER, phase="extract")
        b = named.response_schema([{"line": n, "text": "Amal before Bea"} for n in range(2, 102)], HEADER, phase="extract")
        self.assertLess(len(json.dumps(b))-len(json.dumps(a)), 1200)

    def test_status_and_review_fact_presence_enforced_by_schema(self):
        for phase in ("extract", "review"):
            s = named.response_schema(SOURCES, HEADER, phase=phase)
            branches = s["json_schema"]["schema"]["properties"]["lines"]["items"]["anyOf"]
            self.assertEqual(branches[0]["properties"]["facts"]["minItems"], 1)
            self.assertEqual(branches[1]["properties"]["facts"]["maxItems"], 0)

    def test_grounding_and_name_collision_binding_preserved(self):
        row = {"line": 2, "status": "asserted", "facts": [dict(op="block", person="Cora", block="07:00", negated=False)]}
        self.assertTrue(named.compile_row(row, SOURCES[0], HEADER)[1])
        self.assertFalse(named.compile_row(row, SOURCES[0], HEADER, grounding=False)[1])
        h = {**HEADER, "stations": ["Amal", "packing", "calibration"]}
        self.assertIn("person:Amal", named.label_groups(h)["person"])
        self.assertIn("station_holder:Amal", named.label_groups(h)["station"])

    def test_duplicate_and_missing_rows_are_not_silently_accepted(self):
        wire = rows()
        checked, errors = named.validate_output({"lines": [wire[0], wire[0], *wire[2:]]}, SOURCES, HEADER)
        self.assertEqual(checked[2]["scope"], "uncertain")
        self.assertEqual(checked[3]["scope"], "uncertain")
        self.assertEqual(len(errors), 2)

    def test_named_and_flat_compilers_preserve_same_answers(self):
        canonical = {r["line"]: r for r in fixture_rows()}
        compiled, errors = named.validate_output({"lines": rows()}, SOURCES, HEADER)
        self.assertEqual(errors, [])
        self.assertEqual(derive_answer(HEADER, facts_from_rows(canonical, SOURCES)),
                         derive_answer(HEADER, facts_from_rows(compiled, SOURCES)))


class NamedPromptTests(unittest.TestCase):
    def test_contrasts_and_named_fields_without_source_specific_candidates(self):
        p = build_prompt(SOURCES, HEADER, "extract", stage="named_review")
        self.assertIn('"person":"Mira"', p)
        self.assertIn("No block separates", p)
        self.assertIn("never two 'before'", p)
        self.assertIn("Inspection is covered before", p)
        self.assertIn("Mira precedes Jules", p)
        self.assertIn("OR (Sana < Mira < Jules)", p)
        self.assertIn("Do not emit two next facts", p)
        self.assertNotIn('"args":', p)
        self.assertNotIn("explicit declined slot request denies", p)

    def test_independent_read_contains_no_prior_ledger(self):
        p = build_prompt(SOURCES, HEADER, "independent", stage="named_review", rows={r["line"]:r for r in fixture_rows()})
        self.assertNotIn("CANDIDATE READINGS", p)
        self.assertTrue(all(s["text"] in p for s in SOURCES))

    def test_review_ledger_has_no_duplicated_english_meanings(self):
        r = {r["line"]:r for r in fixture_rows()}
        p = build_prompt(SOURCES, HEADER, "review", stage="named_review", rows=r, secondary=r)
        self.assertIn("CANDIDATE READINGS", p)
        self.assertNotIn('"meanings"', p)
        self.assertNotIn('"assignment"', p)

    def test_stages_and_example_ablation_are_distinct(self):
        a = build_prompt(SOURCES, HEADER, "extract", stage="named")
        b = build_prompt(SOURCES, HEADER, "extract", stage="named_examples")
        self.assertNotIn("Fixed source-to-meaning contrasts", a)
        self.assertIn("Fixed source-to-meaning contrasts", b)
        self.assertEqual(b, build_prompt(SOURCES, HEADER, "extract", stage="named_review"))
        no_examples = build_prompt(SOURCES, HEADER, "extract", stage="named_review", examples=False)
        self.assertNotIn("Fixed hypothetical examples", no_examples)
        self.assertNotIn("Fixed source-to-meaning contrasts", no_examples)


class NamedPipelineTests(unittest.TestCase):
    def test_one_call_for_every_named_stage(self):
        for stage in ("named", "named_examples", "named_review"):
            c = Client([{"lines": rows()}])
            a, calls, t = process_item(ITEM, "1x", {}, stage=stage, client=c)
            self.assertEqual((a["case"], calls), ("unique", 1))
            self.assertEqual(t["wire_contract"], "named_typed_roles")

    def test_three_x_uses_two_complete_independent_reads(self):
        c = Client([{"lines": rows()}, {"lines": rows()}, keep_requested])
        a, calls, t = process_item(ITEM, "3x", {}, stage="named_review", client=c)
        self.assertEqual((a["case"], calls), ("unique", 3))
        self.assertEqual([r["phase"] for r in t["extraction_reports"]], ["extract", "independent", "review"])
        self.assertEqual(t["extraction_reports"][1]["source_lines"], [s["line"] for s in SOURCES])
        self.assertNotIn("CANDIDATE READINGS", c.prompts[1])
        self.assertIsNone(t["scope_filter"])

    def test_named_stage_retains_old_allocation_for_ablation(self):
        first = {"lines": [{"line": s["line"], "status": "asserted"} for s in SOURCES]}
        audit = {"lines": [{**r, "verdict": "supported"} for r in rows()]}
        c = Client([first, {"lines": rows()}, audit])
        a, calls, t = process_item(ITEM, "3x", {}, stage="named", client=c)
        self.assertEqual((a["case"], calls), ("unique", 3))
        self.assertEqual([r["phase"] for r in t["extraction_reports"]], ["classify", "extract", "audit"])

    def test_focus_preserves_agreed_rows_and_recovers_missing_clue(self):
        first = rows()
        first[3] = {"line": 5, "status": "ignored", "facts": []}
        def recover(prompt, schema):
            reply = keep_requested(prompt, schema)
            for r in reply["lines"]:
                if r["line"] == 5:
                    r.update(action="replace", facts=rows()[3]["facts"])
            return reply
        c = Client([{"lines": first}, {"lines": rows()}, recover])
        a, _, t = process_item(ITEM, "3x", {}, stage="named_review", client=c)
        report = t["extraction_reports"][-1]
        self.assertEqual(a["case"], "unique")
        self.assertIn(5, report["changed_lines"])
        self.assertIn(5, report["source_lines"])
        self.assertTrue(report["untouched_lines"])
        self.assertIn("independent_disagreement", report["target_reasons"][5])

    def test_invalid_primary_falls_back_but_stays_targeted_for_review(self):
        first = rows()
        first[0]["facts"][0] = dict(op="block", person="07:00", block="Amal", negated=False)
        c = Client([{"lines": first}, {"lines": rows()}, keep_requested])
        a, _, t = process_item(ITEM, "3x", {}, stage="named_review", client=c)
        self.assertEqual(a["case"], "unique")
        self.assertIn(2, t["extraction_reports"][1]["primary_fallback_lines"])
        self.assertIn("invalid_reading", t["extraction_reports"][-1]["target_reasons"][2])

    def test_conflicting_independent_facts_are_not_unioned(self):
        second = rows()
        second[0]["facts"][0]["negated"] = True
        c = Client([{"lines": rows()}, {"lines": second}, keep_requested])
        a, _, t = process_item(ITEM, "3x", {}, stage="named_review", client=c)
        self.assertEqual(a["case"], "unique")
        self.assertFalse(any(f["polarity"]=="negated" for f in t["facts"]))

    def test_unresolved_and_invalid_replacements_preserve_prior(self):
        for action in ("unresolved", "bad_replace"):
            def output(prompt, schema):
                reply = keep_requested(prompt, schema)
                r = reply["lines"][0]
                if action == "unresolved":
                    r["action"] = "unresolved"
                else:
                    r.update(action="replace", facts=[dict(op="station", person="intake", station="Amal", negated=False)])
                return reply
            c = Client([{"lines": rows()}, {"lines": rows()}, output])
            a, _, t = process_item(ITEM, "3x", {}, stage="named_review", client=c)
            self.assertEqual(a["case"], "unique")
            self.assertTrue(t["unresolved_lines"])

    def test_ignored_entity_rich_lines_are_reviewed_without_word_matching(self):
        primary = {s["line"]:flat.unknown(s["line"]) for s in SOURCES}
        for r in primary.values():r.update(scope="nonclue", structurally_valid=True)
        reasons = named.review_targets(SOURCES, HEADER, primary, primary)
        self.assertTrue(reasons)
        self.assertTrue(all("ignored_with_multiple_header_entities" in why for why in reasons.values()))

    def test_no_focus_ablation_reviews_every_original_line(self):
        second = rows()
        second[0]["facts"][0]["negated"] = True
        c = Client([{"lines": rows()}, {"lines": second}, keep_requested])
        _, _, t = process_item(ITEM, "3x", {}, "no_focus", stage="named_review", client=c)
        self.assertEqual(t["extraction_reports"][-1]["source_lines"], [s["line"] for s in SOURCES])

    def test_remove_withdraws_an_explicitly_disputed_claim(self):
        item = {"id":"SYNTHETIC-NAMED-DISCUSSION", "text":ITEM["text"]+"\nWe debated whether Dev works at 15:00."}
        extra = {"line":9,"status":"asserted","facts":[dict(op="block",person="Dev",block="15:00",negated=False)]}
        def remove(prompt,schema):
            result = keep_requested(prompt,schema)
            for row in result["lines"]:
                if row["line"]==9:row["action"]="remove"
            return result
        c=Client([{"lines":rows()+[extra]},{"lines":rows()+[{"line":9,"status":"ignored","facts":[]}]},remove])
        a,_,t=process_item(item,"3x",{},stage="named_review",client=c)
        self.assertEqual(a["case"],"unique")
        self.assertFalse(any(f["line"]==9 for f in t["facts"]))

    def test_review_cannot_modify_an_unrequested_source_row(self):
        second=rows();second[0]["facts"][0]["negated"]=True
        def extra(prompt,schema):
            reply=keep_requested(prompt,schema)
            reply["lines"].append({"line":999,"action":"remove","facts":[]})
            return reply
        c=Client([{"lines":rows()},{"lines":second},extra])
        a,_,t=process_item(ITEM,"3x",{},stage="named_review",client=c)
        self.assertEqual(a["case"],"unique")
        self.assertTrue(t["extraction_reports"][-1]["problems"])

    def test_negated_and_compound_claims_are_review_targets(self):
        primary={r["line"]:r for r in fixture_rows()}
        primary[2]["claims"][0]["polarity"]="negated"
        primary[3]["claims"].append(deepcopy(primary[3]["claims"][0]))
        reasons=named.review_targets(SOURCES,HEADER,primary,primary)
        for line in (2,3):self.assertIn("negation_or_multiple_claims",reasons[line])

    def test_agreed_adjacency_is_still_rechecked(self):
        primary={r["line"]:r for r in fixture_rows()}
        primary[2]["claims"][0]={"op":"next","earlier":"P0","later":"P1","polarity":"affirmed","evidence":SOURCES[0]["text"]}
        reasons=named.review_targets(SOURCES,HEADER,primary,primary)
        self.assertIn("adjacency_claim",reasons[2])

    def test_call_allocation_ablations_fit_the_cap(self):
        for ablation,replies in [("no_audit",[{"lines":rows()},{"lines":rows()}]),
                                  ("no_independent",[{"lines":rows()},keep_requested])]:
            a,calls,_=process_item(ITEM,"3x",{},ablation,stage="named_review",client=Client(replies))
            self.assertEqual((a["case"],calls),("unique",2))

    def test_malformed_response_consumes_call_and_model_output_matters(self):
        a, calls, _ = process_item(ITEM, "1x", {}, stage="named_review", client=Client([ValueError("bad JSON")]))
        b, _, _ = process_item(ITEM, "1x", {}, stage="named_review", client=Client([{"lines": rows()}]))
        self.assertEqual(calls, 1)
        self.assertEqual(len(a["assignments"]), 720)
        self.assertEqual(b["case"], "unique")

    def test_ten_x_caps_and_named_schema_on_rereads(self):
        item = {"id":"SYNTHETIC-NAMED-LONG", "text":HEADER_TEXT+"\n"+"\n".join(["Amal precedes Bea."]*28)}
        def unclear(prompt, schema):
            phase = schema["json_schema"]["name"].removeprefix("named_shift_")
            return {"lines":[{"line":n, **({"action":"unresolved", "facts":[]} if phase=="review" else
                {"status":"unclear", **({"facts":[]} if phase!='classify' else {}), **({"verdict":"uncertain"} if phase in ('audit','repair') else {})})} for n in schema_ids(schema)]}
        for stage in ("named", "named_examples", "named_review"):
            c = Client([unclear]*10)
            _, calls, _ = process_item(item, "10x", {}, stage=stage, client=c)
            self.assertEqual(calls, 10)


if __name__ == "__main__":
    unittest.main()
