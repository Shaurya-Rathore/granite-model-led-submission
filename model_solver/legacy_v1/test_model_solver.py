"""Synthetic regression tests; no endpoint or visible-key access."""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from .engine import derive_answer, enumerate_solutions, facts_from_rows, holds, minimal_conflict
from .pipeline import process_item
from .prompts import build_prompt
from .representation import response_schema, symbol_table, validate_output, validate_row
from .transport import GraniteClient, line_records, parse_header, parse_model_json

HEADER_TEXT = ("5 staff on the rota: Amal, Bea, Cora, Dev, Eren. "
               "Blocks run 07:00, 09:00, 11:00, 13:00, 15:00, one person per block. "
               "There are 3 stations, one person on each: intake, packing, calibration. "
               "The people on a station are Amal, Bea, Cora; the rest have no station.")
HEADER = parse_header(HEADER_TEXT)
NOTES = ["Amal works at 07:00.", "Bea works at 09:00.", "Cora works at 11:00.",
         "Dev works at 13:00.", "Amal holds intake.", "Bea holds packing.", "Cora holds calibration."]
ITEM = {"id": "SYNTHETIC-TEST", "text": HEADER_TEXT + "\n" + "\n".join(NOTES)}
SOURCES = line_records(ITEM["text"])


def atom(op, evidence, polarity="affirmed", **roles):
    return {"op": op, "evidence": evidence, "polarity": polarity, **roles}


def fixture_rows():
    claims = [atom("block", NOTES[i], person=f"P{i}", block=f"T{i}") for i in range(4)]
    claims += [atom("station", NOTES[4 + i], person=f"P{i}", station=f"S{i}") for i in range(3)]
    return [{"line": i + 2, "scope": "current_clue", "claims": [claim]} for i, claim in enumerate(claims)]


def classification(excluded=()):
    return {"lines": [{"line": line["line"], "scope": "nonclue" if line["line"] in excluded else "current_clue"}
                      for line in SOURCES]}


def reviewed(rows, verdict="supported"):
    return {"lines": [{**row, "verdict": verdict} for row in deepcopy(rows)]}


class ScriptedClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.prompts = []
        self.formats = []
        self.raw_outputs = []
        self.call_metadata = []

    def call(self, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        self.formats.append(schema)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        self.raw_outputs.append(json.dumps(reply))
        return deepcopy(reply)


class UncertainClient(ScriptedClient):
    def __init__(self):
        super().__init__([])

    def call(self, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        self.formats.append(schema)
        phase = schema["json_schema"]["name"].removeprefix("model_shift_")
        variants = schema["json_schema"]["schema"]["properties"]["lines"]["items"]["anyOf"]
        numbers = sorted({row["properties"]["line"]["enum"][0] for row in variants})
        rows = [{"line": n, "scope": "uncertain",
                 **({"claims": []} if phase != "classify" else {}),
                 **({"verdict": "uncertain"} if phase in ("audit", "repair") else {})} for n in numbers]
        self.raw_outputs.append(json.dumps({"lines": rows}))
        return {"lines": rows}


class EngineTests(unittest.TestCase):
    def test_domain_has_exactly_720_schedules(self):
        solutions = enumerate_solutions(HEADER, [])
        self.assertEqual(len(solutions), 720)
        self.assertEqual(len({json.dumps(s, sort_keys=True) for s in solutions}), 720)
        self.assertTrue(all("station" not in s["Dev"] and "station" not in s["Eren"] for s in solutions))

    def test_unique_and_complete_ambiguity(self):
        rows = {r["line"]: r for r in fixture_rows()}
        facts = facts_from_rows(rows, SOURCES)
        answer, solutions = derive_answer(HEADER, facts)
        self.assertEqual(answer["case"], "unique")
        self.assertEqual(len(solutions), 1)
        self.assertEqual(answer["assignment"]["Eren"], {"block": "15:00"})
        ambiguous, solutions = derive_answer(HEADER, [fact for fact in facts if fact["line"] != 5])
        self.assertEqual(ambiguous["case"], "ambiguous")
        self.assertEqual(len(ambiguous["assignments"]), 2)
        self.assertEqual({a["Dev"]["block"] for a in solutions}, {"13:00", "15:00"})

    def test_all_operators_polarity_and_station_holder_resolution(self):
        symbols = symbol_table(HEADER)
        times = {name: i for i, name in enumerate(HEADER["staff"])}
        owners = {"intake": "Cora", "packing": "Amal", "calibration": "Bea"}
        true_claims = [atom("block", "", person="P3", block="T3"),
                       atom("station", "", person="P2", station="S0"),
                       atom("before", "", earlier="S0", later="P3"),
                       atom("next", "", earlier="P1", later="S0"),
                       atom("between", "", middle="S0", ends=["P4", "P0"])]
        for claim in true_claims:
            with self.subTest(claim=claim):
                self.assertTrue(holds(claim, times, owners, HEADER, symbols))
                self.assertFalse(holds({**claim, "polarity": "negated"}, times, owners, HEADER, symbols))
        moved = {**owners, "intake": "Eren"}
        self.assertFalse(holds(true_claims[2], times, moved, HEADER, symbols))

    def test_conflict_is_minimal_by_whole_source_line(self):
        facts = [{"line": 2, "quote": "Amal precedes Bea.", **atom("before", "", earlier="P0", later="P1")},
                 {"line": 3, "quote": "Bea precedes Cora.", **atom("before", "", earlier="P1", later="P2")},
                 {"line": 4, "quote": "Cora precedes Amal.", **atom("before", "", earlier="P2", later="P0")},
                 {"line": 4, "quote": "Cora precedes Amal.", **atom("block", "", person="P4", block="T4")},
                 {"line": 5, "quote": "Dev follows Bea.", **atom("before", "", earlier="P1", later="P3")}]
        core = minimal_conflict(HEADER, facts)
        self.assertEqual({fact["line"] for fact in core}, {2, 3, 4})
        self.assertEqual(len(core), 4)
        self.assertFalse(enumerate_solutions(HEADER, core))
        for n in {fact["line"] for fact in core}:
            self.assertTrue(enumerate_solutions(HEADER, [f for f in core if f["line"] != n]))
        answer, _ = derive_answer(HEADER, facts)
        self.assertEqual(answer["case"], "inconsistent")
        self.assertEqual(len(answer["conflicts"]), 3)


class RepresentationTests(unittest.TestCase):
    def test_unfamiliar_wording_is_not_decoded_by_code(self):
        source = {"line": 2, "text": "Amal's block is the predecessor of Bea's."}
        row = {"line": 2, "scope": "current_clue", "claims": [atom("next", source["text"], earlier="P0", later="P1")]}
        self.assertEqual(validate_row(row, source, HEADER), [])
        reverse = deepcopy(row)
        reverse["claims"][0].update(earlier="P1", later="P0")
        # The semantic error is the model audit's responsibility, not a hidden
        # word-pattern oracle in the evidence/type validator.
        self.assertEqual(validate_row(reverse, source, HEADER), [])

    def test_schema_does_not_choose_relation_direction_or_negation(self):
        left = response_schema([{"line": 2, "text": "Amal precedes Bea."}], HEADER, phase="extract")
        right = response_schema([{"line": 2, "text": "Amal does not follow Bea."}], HEADER, phase="extract")
        self.assertEqual(left, right)
        claims = left["json_schema"]["schema"]["properties"]["lines"]["items"]["anyOf"][0]["properties"]["claims"]["items"]["anyOf"]
        order = next(v for v in claims if v["properties"]["op"]["enum"] == ["before"])
        self.assertEqual(order["properties"]["earlier"]["enum"], ["P0", "P1"])
        self.assertEqual(order["properties"]["later"]["enum"], ["P0", "P1"])
        self.assertEqual(order["properties"]["polarity"]["enum"], ["affirmed", "negated"])

    def test_wrong_types_ungrounded_and_fabricated_evidence_are_rejected(self):
        source = {"line": 2, "text": "Amal starts before whoever holds intake."}
        good = {"line": 2, "scope": "current_clue", "claims": [atom("before", source["text"], earlier="P0", later="S0")]}
        self.assertEqual(validate_row(good, source, HEADER), [])
        for change in ({"later": "P2"}, {"evidence": "Amal starts after intake"}, {"later": "P0"}, {"op": ["before"]}):
            row = deepcopy(good)
            row["claims"][0].update(change)
            self.assertTrue(validate_row(row, source, HEADER))
        wrong_type = {"line": 2, "scope": "current_clue", "claims": [atom("station", source["text"], person="S0", station="P0")]}
        self.assertTrue(validate_row(wrong_type, source, HEADER))

    def test_duplicate_missing_rows_and_uncertain_audit_are_quarantined(self):
        rows = fixture_rows()
        bad = {"lines": [rows[0], rows[0], *rows[2:]]}
        checked, problems = validate_output(bad, SOURCES, HEADER)
        self.assertEqual(checked[2]["scope"], "uncertain")
        self.assertEqual(checked[3]["scope"], "uncertain")
        self.assertEqual({p["errors"][0] for p in problems}, {"duplicate source row", "omitted source row"})
        checked, problems = validate_output(reviewed(rows, "uncertain"), SOURCES, HEADER, phase="audit")
        self.assertTrue(all(row["scope"] == "uncertain" for row in checked.values()))
        self.assertEqual(len(problems), len(SOURCES))

    def test_grounding_ablation_keeps_verbatim_evidence_mandatory(self):
        source = SOURCES[0]
        row = {"line": 2, "scope": "current_clue", "claims": [atom("block", source["text"], person="P2", block="T0")]}
        self.assertTrue(validate_row(row, source, HEADER))
        self.assertEqual(validate_row(row, source, HEADER, grounding=False), [])
        row["claims"][0]["evidence"] = "Invented evidence"
        self.assertTrue(validate_row(row, source, HEADER, grounding=False))

    def test_malformed_between_arguments_are_quarantined_without_crashing(self):
        source = {"line": 2, "text": "Bea lies between Amal and Cora."}
        for ends in (["P0", "P2", 7], ["P0", "P2", {}], ["P0", {}], [], "P0"):
            row = {"line": 2, "scope": "current_clue", "claims": [atom("between", source["text"], middle="P1", ends=ends)]}
            with self.subTest(ends=ends):
                checked, problems = validate_output({"lines": [row]}, [source], HEADER)
                self.assertEqual(checked[2]["scope"], "uncertain")
                self.assertTrue(problems)

    def test_runtime_imports_no_baseline_semantic_or_key_module(self):
        root = Path(__file__).resolve().parent
        for file in ("pipeline.py", "prompts.py", "representation.py", "engine.py", "transport.py", "run.py"):
            text = (root / file).read_text()
            tree = ast.parse(text)
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
            self.assertFalse(any("semantics" in name or "granite_solver" in name for name in imports))
            self.assertNotIn("visible_key", text)


class PipelineTests(unittest.TestCase):
    def test_one_call_and_model_output_changes_answer(self):
        client = ScriptedClient([{"lines": fixture_rows()}])
        answer, calls, trace = process_item(ITEM, "1x", {}, client=client)
        self.assertEqual((answer["case"], calls, client.calls), ("unique", 1, 1))
        self.assertEqual(trace["unresolved_lines"], [])
        blank = {"lines": [{"line": x["line"], "scope": "nonclue", "claims": []} for x in SOURCES]}
        changed, calls, _ = process_item(ITEM, "1x", {}, client=ScriptedClient([blank]))
        self.assertEqual((changed["case"], calls), ("ambiguous", 1))
        self.assertEqual(len(changed["assignments"]), 720)

    def test_three_calls_audit_recovers_filtered_clue(self):
        rows = fixture_rows()
        extract = {"lines": [r for r in rows if r["line"] != 5]}
        audit = reviewed(rows)
        next(r for r in audit["lines"] if r["line"] == 5)["verdict"] = "missing_clue"
        client = ScriptedClient([classification({5}), extract, audit])
        answer, calls, trace = process_item(ITEM, "3x", {}, client=client)
        self.assertEqual((answer["case"], calls, client.calls), ("unique", 3, 3))
        self.assertEqual([r["phase"] for r in trace["extraction_reports"]], ["classify", "extract", "audit"])
        self.assertNotIn(5, trace["extraction_reports"][1]["source_lines"])
        self.assertIn(5, trace["extraction_reports"][2]["changed_lines"])
        self.assertEqual(trace["unresolved_lines"], [])
        self.assertIn("CANDIDATE READINGS", client.prompts[2])
        self.assertNotIn('"assignment"', client.prompts[2])
        self.assertNotIn('"case"', client.prompts[2])

    def test_invalid_audit_preserves_previous_valid_row(self):
        rows = fixture_rows()
        audit = reviewed(rows)
        next(r for r in audit["lines"] if r["line"] == 5)["claims"][0]["block"] = "T4"
        client = ScriptedClient([classification(), {"lines": rows}, audit])
        answer, calls, trace = process_item(ITEM, "3x", {}, client=client)
        self.assertEqual((answer["case"], calls), ("unique", 3))
        self.assertEqual(trace["unresolved_lines"], [5])
        self.assertEqual(trace["extraction_reports"][2]["retained_previous_lines"], [5])

    def test_ten_call_cap_includes_chunks_audit_and_repairs(self):
        large = {"id": "SYNTHETIC-LONG", "text": HEADER_TEXT + "\n" + "\n".join(["Amal precedes Bea."] * 28)}
        client = UncertainClient()
        answer, calls, trace = process_item(large, "10x", {}, client=client)
        self.assertEqual((calls, client.calls), (10, 10))
        phases = [r["phase"] for r in trace["extraction_reports"]]
        self.assertEqual(phases.count("extract"), 6)
        self.assertEqual(phases.count("repair"), 2)
        self.assertEqual(len(answer["assignments"]), 720)
        self.assertTrue(trace["excess_solutions"])

    def test_no_audit_ablation_uses_two_calls(self):
        rows = fixture_rows()
        client = ScriptedClient([classification({5}), {"lines": [r for r in rows if r["line"] != 5]}])
        answer, calls, _ = process_item(ITEM, "3x", {}, "no_audit", client=client)
        self.assertEqual((answer["case"], calls), ("ambiguous", 2))
        self.assertEqual(len(answer["assignments"]), 2)

    def test_no_filter_ablation_extracts_the_discarded_line(self):
        rows = fixture_rows()
        client = ScriptedClient([classification({5}), {"lines": rows}, reviewed(rows)])
        answer, calls, trace = process_item(ITEM, "3x", {}, "no_filter", client=client)
        self.assertEqual((answer["case"], calls), ("unique", 3))
        self.assertIn(5, trace["extraction_reports"][1]["source_lines"])

    def test_examples_and_grounding_ablation_flags_change_model_context(self):
        for ablation in ("no_examples", "no_grounding"):
            client = ScriptedClient([{"lines": fixture_rows()}])
            answer, calls, trace = process_item(ITEM, "1x", {}, ablation, client=client)
            self.assertEqual((answer["case"], calls), ("unique", 1))
            if ablation == "no_examples":
                self.assertNotIn("Small semantic contrasts", client.prompts[0])
            else:
                self.assertNotIn('"literal_symbols"', client.prompts[0])
                self.assertFalse(trace["literal_grounding_enabled"])

    def test_no_chunking_ablation_has_one_extraction_at_ten_x(self):
        rows = fixture_rows()
        client = ScriptedClient([classification(), {"lines": rows}, reviewed(rows)])
        answer, calls, trace = process_item(ITEM, "10x", {}, "no_chunking", client=client)
        self.assertEqual((answer["case"], calls), ("unique", 3))
        self.assertEqual([r["phase"] for r in trace["extraction_reports"]], ["classify", "extract", "audit"])

    def test_parse_failure_consumes_one_call_without_retry(self):
        client = ScriptedClient([ValueError("bad JSON")])
        answer, calls, trace = process_item(ITEM, "1x", {}, client=client)
        self.assertEqual((calls, client.calls), (1, 1))
        self.assertEqual(trace["extraction_reports"][0]["parse_error"], "bad JSON")
        self.assertEqual(len(trace["unresolved_lines"]), len(SOURCES))
        self.assertEqual(len(answer["assignments"]), 720)

    def test_transport_failure_does_not_become_an_answer(self):
        client = ScriptedClient([RuntimeError("endpoint failure")])
        with self.assertRaisesRegex(RuntimeError, "endpoint failure"):
            process_item(ITEM, "3x", {}, client=client)
        self.assertEqual(client.calls, 1)


class TransportTests(unittest.TestCase):
    ENV = {"OPENROUTER_BASE_URL": "https://example.invalid/api/v1", "OPENROUTER_API_KEY": "unit-test-placeholder"}

    def test_permitted_model_only(self):
        with self.assertRaisesRegex(ValueError, "only ibm-granite"):
            GraniteClient({**self.ENV, "MODEL": "other-model"}, "SYNTHETIC-TEST")

    def test_settings_and_item_header_on_every_request(self):
        client = GraniteClient(self.ENV, "SYNTHETIC-TEST")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": '{"lines": []}'}, "finish_reason": "stop"}]}).encode()
        with patch("model_solver.transport.urllib.request.urlopen", return_value=response) as urlopen:
            for _ in range(2):
                client.call("synthetic request", response_schema(SOURCES, HEADER, phase="extract"))
            for call in urlopen.call_args_list:
                request = call.args[0]
                payload = json.loads(request.data)
                self.assertEqual(payload["model"], "ibm-granite/granite-4.2-8b")
                self.assertEqual(payload["temperature"], 1.0)
                self.assertEqual(payload["top_p"], 0.95)
                self.assertEqual(payload["reasoning"], {"enabled": False})
                self.assertEqual(dict((k.lower(), v) for k, v in request.header_items())["x-item-id"], "SYNTHETIC-TEST")
        self.assertEqual(client.calls, 2)

    def test_json_parser_rejects_invalid_root_and_malformed_text(self):
        for text in ("not JSON", "[]", '{"lines": {}}', '{"lines": ['):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_model_json(text)

    def test_failed_http_request_is_counted_without_retry(self):
        client = GraniteClient(self.ENV, "SYNTHETIC-TEST")
        with patch("model_solver.transport.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")) as urlopen:
            with self.assertRaises(urllib.error.URLError):
                client.call("synthetic request", {})
            self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
