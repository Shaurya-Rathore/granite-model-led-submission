"""Synthetic checks for the separate schema, examples, and review increments."""
from copy import deepcopy
import json
import unittest

from .engine import derive_answer, facts_from_rows
from .flat import compile_row, flat_row, references, response_schema, review_row, validate_output
from .incremental import process_item
from .incremental_prompts import build_prompt
from .legacy_v1.test_model_solver import HEADER, HEADER_TEXT, ITEM, SOURCES, ScriptedClient, fixture_rows
from .representation import claim_key
from .transport import line_records


def wire_rows(rows=None, *, verdict=None):
    result = [flat_row(row, HEADER) for row in (rows if rows is not None else fixture_rows())]
    if verdict is not None:
        for row in result:
            row["verdict"] = verdict
    return result


def statuses(ignored=()):
    return {"lines": [{"line": source["line"], "status": "ignored" if source["line"] in ignored else "asserted"}
                      for source in SOURCES]}


def actions(sources=SOURCES):
    return {"lines": [{"line": source["line"], "action": "keep", "facts": []} for source in sources]}


class AllUnclearClient(ScriptedClient):
    def __init__(self):
        super().__init__([])

    def call(self, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        self.formats.append(schema)
        phase = schema["json_schema"]["name"].removeprefix("model_shift_")
        fields = schema["json_schema"]["schema"]["properties"]["lines"]["items"]["properties"]
        ids = fields["line"]["enum"]
        if phase == "review":
            result = {"lines": [{"line": n, "action": "unresolved", "facts": []} for n in ids]}
        else:
            result = {"lines": [{"line": n, "status": "unclear",
                                  **({"facts": []} if "facts" in fields else {}),
                                  **({"verdict": "uncertain"} if "verdict" in fields else {})} for n in ids]}
        self.raw_outputs.append(json.dumps(result))
        return result


class FlatContractTests(unittest.TestCase):
    def test_readable_names_and_no_per_line_schema_branches(self):
        schema = response_schema(SOURCES, HEADER, phase="extract")
        encoded = json.dumps(schema)
        self.assertNotIn('"anyOf"', encoded)
        self.assertNotIn('"P0"', encoded)
        self.assertIn('"Amal"', encoded)
        self.assertLess(len(encoded), 2000)

    def test_schema_growth_is_only_line_identifiers(self):
        short = response_schema(SOURCES[:1], HEADER, phase="extract")
        long_sources = [{"line": n, "text": "Amal precedes Bea."} for n in range(2, 102)]
        long = response_schema(long_sources, HEADER, phase="extract")
        self.assertLess(len(json.dumps(long)) - len(json.dumps(short)), 500)

    def test_relation_words_do_not_select_operators_direction_or_polarity(self):
        a = response_schema([{"line": 2, "text": "Amal precedes Bea."}], HEADER, phase="extract")
        b = response_schema([{"line": 2, "text": "Amal does not follow Bea."}], HEADER, phase="extract")
        self.assertEqual(a, b)
        fact = a["json_schema"]["schema"]["properties"]["lines"]["items"]["properties"]["facts"]["items"]
        self.assertEqual(fact["properties"]["op"]["enum"], ["block", "station", "before", "next", "between"])
        self.assertEqual(fact["properties"]["negated"], {"type": "boolean"})

    def test_all_operator_and_polarity_round_trips(self):
        source = {"line": 2, "text": "Amal Bea Cora intake packing calibration 07:00 09:00 11:00"}
        facts = [{"op": "block", "args": ["Amal", "07:00"], "negated": False},
                 {"op": "station", "args": ["Amal", "intake"], "negated": False},
                 {"op": "before", "args": ["packing", "Bea"], "negated": False},
                 {"op": "next", "args": ["Amal", "09:00"], "negated": False},
                 {"op": "between", "args": ["Bea", "Amal", "Cora"], "negated": False}]
        for fact in facts:
            for negated in (False, True):
                proposed = {"line": 2, "status": "asserted", "facts": [{**fact, "negated": negated}]}
                compiled, errors = compile_row(proposed, source, HEADER)
                self.assertEqual(errors, [])
                self.assertEqual(flat_row(compiled, HEADER), proposed)
                self.assertEqual(compiled["claims"][0]["evidence"], source["text"])
                self.assertTrue(compiled["structurally_valid"])

    def test_wrong_arity_types_negation_and_references_are_rejected(self):
        source = {"line": 2, "text": "Amal precedes Bea near intake at 07:00."}
        bad = [{"op": "before", "args": ["Amal", "Bea", "07:00"], "negated": False},
               {"op": "between", "args": ["Amal", "Bea", 7], "negated": False},
               {"op": "between", "args": ["Amal", "Bea", {}, "intake"], "negated": False},
               {"op": "station", "args": ["intake", "Amal"], "negated": False},
               {"op": "block", "args": ["Amal", "intake"], "negated": False},
               {"op": "next", "args": ["Amal", "Amal"], "negated": False},
               {"op": "before", "args": ["Amal", "Bea"], "negated": "false"},
               {"op": ["before"], "args": ["Amal", "Bea"], "negated": False},
               {"op": "block", "args": ["Cora", "07:00"], "negated": False}]
        for fact in bad:
            with self.subTest(fact=fact):
                _, errors = compile_row({"line": 2, "status": "asserted", "facts": [fact]}, source, HEADER)
                self.assertTrue(errors)

    def test_grounding_ablation_only_relaxes_literal_identity(self):
        row = {"line": 2, "status": "asserted", "facts": [{"op": "block", "args": ["Cora", "07:00"], "negated": False}]}
        _, errors = compile_row(row, SOURCES[0], HEADER)
        self.assertTrue(errors)
        compiled, errors = compile_row(row, SOURCES[0], HEADER, grounding=False)
        self.assertEqual(errors, [])
        self.assertEqual(compiled["claims"][0]["evidence"], SOURCES[0]["text"])

    def test_name_collisions_require_transparent_typed_labels(self):
        header = {**HEADER, "stations": ["Amal", "packing", "calibration"]}
        refs = references(header)
        self.assertIn("person:Amal", refs)
        self.assertIn("station_holder:Amal", refs)
        self.assertNotIn("Amal", refs)

    def test_duplicate_and_missing_rows_are_quarantined(self):
        rows = wire_rows()
        checked, problems = validate_output({"lines": [rows[0], rows[0], *rows[2:]]}, SOURCES, HEADER)
        self.assertEqual(checked[2]["scope"], "uncertain")
        self.assertEqual(checked[3]["scope"], "uncertain")
        self.assertEqual(len(problems), 2)

    def test_status_and_claim_presence_are_checked_in_code(self):
        for status, facts in [("asserted", []), ("ignored", wire_rows()[0]["facts"]), ("unclear", wire_rows()[0]["facts"])]:
            _, errors = compile_row({"line": 2, "status": status, "facts": facts}, SOURCES[0], HEADER)
            self.assertTrue(errors)

    def test_round_trip_preserves_solution_set(self):
        original = {row["line"]: row for row in fixture_rows()}
        compiled, problems = validate_output({"lines": wire_rows()}, SOURCES, HEADER)
        self.assertEqual(problems, [])
        before, _ = derive_answer(HEADER, facts_from_rows(original, SOURCES))
        after, _ = derive_answer(HEADER, facts_from_rows(compiled, SOURCES))
        self.assertEqual(before, after)
        for n, row in original.items():
            self.assertEqual([claim_key(c) for c in row["claims"]], [claim_key(c) for c in compiled[n]["claims"]])


class PromptStagesTests(unittest.TestCase):
    def test_scope_examples_are_separate_from_schema_stage(self):
        first = build_prompt(SOURCES, HEADER, "extract", stage="schema")
        second = build_prompt(SOURCES, HEADER, "extract", stage="examples")
        self.assertNotIn("Read the outer assertion", first)
        self.assertIn("Read the outer assertion", second)
        self.assertIn("We debated whether Mira works", second)
        self.assertIn("was refused", second)
        self.assertNotIn('"P0"', first)

    def test_scope_example_ablation_keeps_relation_demonstrations(self):
        prompt = build_prompt(SOURCES, HEADER, "extract", stage="examples", scope_examples=False)
        self.assertNotIn("Read the outer assertion", prompt)
        self.assertIn("Small semantic contrasts", prompt)

    def test_review_stage_at_one_x_has_same_prompt_as_examples_stage(self):
        a = build_prompt(SOURCES, HEADER, "extract", stage="examples")
        b = build_prompt(SOURCES, HEADER, "extract", stage="review")
        self.assertEqual(a, b)

    def test_review_actions_replace_the_error_taxonomy(self):
        schema = response_schema(SOURCES, HEADER, phase="review", stage="review")
        fields = schema["json_schema"]["schema"]["properties"]["lines"]["items"]["properties"]
        self.assertEqual(fields["action"]["enum"], ["keep", "remove", "replace", "unresolved"])
        self.assertNotIn("verdict", fields)


class ReviewPolicyTests(unittest.TestCase):
    def setUp(self):
        self.prior = fixture_rows()[0]
        self.source = SOURCES[0]

    def test_keep_marks_model_support(self):
        row, errors = review_row({"line": 2, "action": "keep", "facts": []}, self.source, HEADER, self.prior)
        self.assertEqual(errors, [])
        self.assertEqual(row["support"], "supported")
        self.assertEqual(row["claims"], self.prior["claims"])

    def test_remove_is_an_explicit_semantic_decision(self):
        row, errors = review_row({"line": 2, "action": "remove", "facts": []}, self.source, HEADER, self.prior)
        self.assertEqual(errors, [])
        self.assertEqual((row["scope"], row["claims"]), ("nonclue", []))

    def test_unresolved_preserves_reading_without_certifying_it(self):
        row, errors = review_row({"line": 2, "action": "unresolved", "facts": []}, self.source, HEADER, self.prior)
        self.assertEqual(errors, [])
        self.assertEqual(row["claims"], self.prior["claims"])
        self.assertEqual(row["support"], "unresolved")

    def test_replace_needs_a_valid_complete_fact_set(self):
        fact = {"op": "block", "args": ["Amal", "07:00"], "negated": True}
        row, errors = review_row({"line": 2, "action": "replace", "facts": [fact]}, self.source, HEADER, self.prior)
        self.assertEqual(errors, [])
        self.assertEqual(row["claims"][0]["polarity"], "negated")
        _, errors = review_row({"line": 2, "action": "replace", "facts": []}, self.source, HEADER, self.prior)
        self.assertTrue(errors)

    def test_actions_cannot_smuggle_unvalidated_facts(self):
        for action in ("keep", "remove", "unresolved"):
            _, errors = review_row({"line": 2, "action": action, "facts": wire_rows()[0]["facts"]}, self.source, HEADER, self.prior)
            self.assertTrue(errors)


class IncrementalPipelineTests(unittest.TestCase):
    def test_exactly_one_call_at_each_new_stage(self):
        for stage in ("schema", "examples", "review"):
            client = ScriptedClient([{"lines": wire_rows()}])
            answer, calls, trace = process_item(ITEM, "1x", {}, stage=stage, client=client)
            self.assertEqual((answer["case"], calls, client.calls), ("unique", 1, 1))
            self.assertEqual(trace["development_stage"], stage)

    def test_schema_stage_keeps_old_three_call_allocation(self):
        extract = {"lines": [row for row in wire_rows() if row["line"] != 5]}
        audit = {"lines": wire_rows(verdict="supported")}
        client = ScriptedClient([statuses({5}), extract, audit])
        answer, calls, trace = process_item(ITEM, "3x", {}, stage="schema", client=client)
        self.assertEqual((answer["case"], calls), ("unique", 3))
        self.assertEqual([r["phase"] for r in trace["extraction_reports"]], ["classify", "extract", "audit"])

    def test_independent_read_has_all_source_and_no_candidate_ledger(self):
        client = ScriptedClient([{"lines": wire_rows()}, {"lines": wire_rows()}, actions()])
        answer, calls, trace = process_item(ITEM, "3x", {}, stage="review", client=client)
        self.assertEqual((answer["case"], calls), ("unique", 3))
        self.assertEqual([r["phase"] for r in trace["extraction_reports"]], ["extract", "independent", "review"])
        self.assertEqual(trace["extraction_reports"][1]["source_lines"], [s["line"] for s in SOURCES])
        self.assertNotIn("CANDIDATE READINGS", client.prompts[1])
        self.assertNotIn('"assignment"', client.prompts[2])
        self.assertNotIn('"case"', client.prompts[2])
        self.assertEqual(trace["provisional_lines"], [])

    def test_review_recovers_clue_discarded_by_first_read(self):
        first = wire_rows()
        first[3] = {"line": 5, "status": "ignored", "facts": []}
        review = actions()
        review["lines"][3] = {"line": 5, "action": "replace", "facts": wire_rows()[3]["facts"]}
        client = ScriptedClient([{"lines": first}, {"lines": wire_rows()}, review])
        answer, _, trace = process_item(ITEM, "3x", {}, stage="review", client=client)
        self.assertEqual(answer["case"], "unique")
        self.assertIn(5, trace["extraction_reports"][2]["changed_lines"])

    def test_incompatible_readings_are_not_automatically_unioned(self):
        second = wire_rows()
        second[0]["facts"][0]["negated"] = True
        client = ScriptedClient([{"lines": wire_rows()}, {"lines": second}, actions()])
        answer, _, trace = process_item(ITEM, "3x", {}, stage="review", client=client)
        self.assertEqual(answer["case"], "unique")
        self.assertFalse(any(f["polarity"] == "negated" for f in trace["facts"]))

    def test_review_removes_a_grounded_but_false_discussion_fact(self):
        text = ITEM["text"] + "\nWe debated whether Dev works at 15:00."
        item = {"id": "SYNTHETIC-DISCUSSION", "text": text}
        sources = line_records(text)
        extra = {"line": 9, "status": "asserted", "facts": [{"op": "block", "args": ["Dev", "15:00"], "negated": False}]}
        first = wire_rows() + [extra]
        second = wire_rows() + [{"line": 9, "status": "ignored", "facts": []}]
        review = actions(sources)
        review["lines"][-1]["action"] = "remove"
        client = ScriptedClient([{"lines": first}, {"lines": second}, review])
        answer, _, trace = process_item(item, "3x", {}, stage="review", client=client)
        self.assertEqual(answer["case"], "unique")
        self.assertFalse(any(f["line"] == 9 for f in trace["facts"]))

    def test_unresolved_review_is_flagged_and_preserves_prior_fact(self):
        review = actions()
        review["lines"][3]["action"] = "unresolved"
        client = ScriptedClient([{"lines": wire_rows()}, {"lines": wire_rows()}, review])
        answer, _, trace = process_item(ITEM, "3x", {}, stage="review", client=client)
        self.assertEqual(answer["case"], "unique")
        self.assertEqual(trace["unresolved_lines"], [5])
        self.assertEqual(trace["provisional_lines"], [5])
        self.assertEqual(next(r for r in trace["final_rows"] if r["line"] == 5)["support"], "unresolved")

    def test_invalid_review_preserves_prior_as_provisional(self):
        review = actions()
        review["lines"][3] = {"line": 5, "action": "replace", "facts": [{"op": "block", "args": ["Dev", "15:00"], "negated": False}]}
        client = ScriptedClient([{"lines": wire_rows()}, {"lines": wire_rows()}, review])
        answer, _, trace = process_item(ITEM, "3x", {}, stage="review", client=client)
        self.assertEqual(answer["case"], "unique")
        self.assertEqual(trace["unresolved_lines"], [5])
        self.assertEqual(next(r for r in trace["final_rows"] if r["line"] == 5)["support"], "provisional")

    def test_duplicate_review_actions_do_not_commit_partial_update(self):
        review = actions()
        review["lines"].append({"line": 5, "action": "remove", "facts": []})
        client = ScriptedClient([{"lines": wire_rows()}, {"lines": wire_rows()}, review])
        answer, _, trace = process_item(ITEM, "3x", {}, stage="review", client=client)
        self.assertEqual(answer["case"], "unique")
        self.assertEqual(trace["unresolved_lines"], [5])

    def test_ten_call_cap_for_all_new_stages(self):
        item = {"id": "SYNTHETIC-LONG", "text": HEADER_TEXT + "\n" + "\n".join(["Amal precedes Bea."] * 28)}
        for stage in ("schema", "examples", "review"):
            client = AllUnclearClient()
            _, calls, trace = process_item(item, "10x", {}, stage=stage, client=client)
            self.assertEqual((calls, client.calls), (10, 10))
            self.assertTrue(trace["excess_solutions"])

    def test_no_audit_and_no_independent_ablations(self):
        for ablation, replies in [("no_audit", [{"lines": wire_rows()}, {"lines": wire_rows()}]),
                                  ("no_independent", [{"lines": wire_rows()}, actions()])]:
            client = ScriptedClient(replies)
            answer, calls, _ = process_item(ITEM, "3x", {}, ablation, stage="review", client=client)
            self.assertEqual((answer["case"], calls), ("unique", 2))

    def test_malformed_output_consumes_its_call(self):
        client = ScriptedClient([ValueError("bad JSON")])
        answer, calls, trace = process_item(ITEM, "1x", {}, client=client)
        self.assertEqual(calls, 1)
        self.assertEqual(len(answer["assignments"]), 720)
        self.assertIn("parse_error", trace["extraction_reports"][0])

    def test_model_output_changes_the_answer(self):
        ignored = {"lines": [{"line": s["line"], "status": "ignored", "facts": []} for s in SOURCES]}
        a, _, _ = process_item(ITEM, "1x", {}, client=ScriptedClient([{"lines": wire_rows()}]))
        b, _, _ = process_item(ITEM, "1x", {}, client=ScriptedClient([ignored]))
        self.assertEqual(a["case"], "unique")
        self.assertEqual((b["case"], len(b["assignments"])), ("ambiguous", 720))

    def test_legacy_stage_keeps_the_archived_wire_contract(self):
        client = ScriptedClient([{"lines": fixture_rows()}])
        answer, calls, trace = process_item(ITEM, "1x", {}, stage="legacy", client=client)
        self.assertEqual((answer["case"], calls), ("unique", 1))
        self.assertEqual(trace["architecture"], "model_led_typed_atoms_v1")


if __name__ == "__main__":
    unittest.main()
