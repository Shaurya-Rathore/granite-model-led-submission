"""Offline contract checks and saved-response replay; no live API requests."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
from unittest.mock import patch

from model_solver.incremental import process_item
from model_solver.transport import parse_model_json
from model_solver import run as cli
from model_solver.test_named import Client, rows as synthetic_rows
from model_solver.legacy_v1.test_model_solver import ITEM, HEADER_TEXT

ROOT = Path(__file__).resolve().parent


def load(path):
    return json.loads(Path(path).read_text())


class ReplayClient:
    def __init__(self, saved):
        self.outputs = iter(saved["raw_model_outputs"])
        self.calls = 0
        self.raw_outputs, self.call_metadata = [], []

    def call(self, prompt, schema):
        raw = next(self.outputs)
        self.calls += 1
        self.raw_outputs.append(raw)
        return parse_model_json(raw)


def score_evidence(prefix, budget, stage, items, scorer, key):
    saved = load(ROOT / "evidence" / (prefix + "-" + budget + "-traces.json"))
    answers = load(ROOT / "evidence" / (prefix + "-" + budget + "-answers.json"))
    scores = load(ROOT / "evidence" / (prefix + "-" + budget + "-score.json"))["score"]
    selected = [item for item in items if item["id"] in answers]
    assert len(selected) == len(answers) == len(saved)
    for item in selected:
        client = ReplayClient(saved[item["id"]])
        answer, calls, trace = process_item(item, budget, {}, stage=stage, client=client)
        assert answer == answers[item["id"]], (prefix, budget, item["id"], "changed answer")
        assert calls == saved[item["id"]]["model_calls"]
        assert trace["facts"] == saved[item["id"]]["facts"]
    score = scorer({i["id"]: key[i["id"]] for i in selected}, answers, selected)
    assert score == scores, (prefix, budget, "changed official score")
    return {"source": prefix, "stage": stage, "budget": budget, "items": len(selected),
            "exact": sum(v["correct"] for v in score["per_case"].values()),
            "macro_exact_match": score["macro_exact_match"], "per_case": score["per_case"],
            "confusion": score["confusion"], "replay_matches": True}


def cli_contracts():
    result = {}
    env = {"OPENROUTER_BASE_URL": "https://example.invalid/api/v1",
           "OPENROUTER_API_KEY": "offline-synthetic-placeholder"}
    item = {"id": "SYNTHETIC-CONTRACT", "text": HEADER_TEXT + "\n" + "\n".join(["Amal precedes Bea."] * 28)}
    for budget, count in [("1x", 1), ("3x", 3), ("10x", 10)]:
        requests = []

        class Response:
            def __init__(self, content):
                self.content = content

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": json.dumps(self.content)},
                                               "finish_reason": "stop"}]}).encode()

        def fake_urlopen(request, **kwargs):
            payload = json.loads(request.data)
            requests.append((payload, {k.lower(): v for k, v in request.header_items()}))
            row = payload["response_format"]["json_schema"]["schema"]["properties"]["lines"]["items"]
            variant = row["anyOf"][0]
            ids = variant["properties"]["line"]["enum"]
            action = "action" in variant["properties"]
            return Response({"lines": [{"line": n, "action" if action else "status":
                                        "unresolved" if action else "unclear", "facts": []} for n in ids]})

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "items.json"
            output = Path(directory) / "answers.json"
            source.write_text(json.dumps([item]))
            argv = [str(ROOT / "run"), str(source), "--budget", budget, "--out", str(output)]
            with patch.object(sys, "argv", argv), patch.object(cli, "load_env", return_value=env), \
                    patch("model_solver.transport.urllib.request.urlopen", side_effect=fake_urlopen), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                assert cli.main() == 0
            answer = load(output)
            assert set(answer) == {item["id"]}
            assert answer[item["id"]]["case"] == "ambiguous"
            assert len(answer[item["id"]]["assignments"]) == 720
        assert len(requests) == count
        for payload, headers in requests:
            assert payload["model"] == "ibm-granite/granite-4.2-8b"
            assert payload["temperature"] == 1.0 and payload["top_p"] == 0.95
            assert payload["reasoning"] == {"enabled": False}
            assert headers["x-item-id"] == item["id"]
        result[budget] = {"mock_http_requests": count, "settings_and_item_header": "passed",
                          "output_json": "passed", "live_requests": 0}
    first, _, _ = process_item(ITEM, "1x", {}, stage="named_review", client=Client([{"lines": synthetic_rows()}]))
    ignored = {"lines": [{"line": r["line"], "status": "ignored", "facts": []} for r in synthetic_rows()]}
    second, _, _ = process_item(ITEM, "1x", {}, stage="named_review", client=Client([ignored]))
    assert first["case"] == "unique" and second["case"] == "ambiguous" and first != second
    result["model_output_dependence"] = "passed: changing synthetic model output changes the answer"
    return result


def main():
    provenance = load(ROOT / "SOURCE_PROVENANCE.json")
    for source in provenance["runtime_provenance"]:
        assert hashlib.sha256((ROOT / source["packaged"]).read_bytes()).hexdigest() == source["packaged_sha256"]
    for file, digest in provenance["original_inputs_sha256"].items():
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest
    for file in ["run.py", "pipeline.py", "incremental.py", "named.py", "named_prompts.py",
                 "representation.py", "transport.py", "engine.py"]:
        text = (ROOT / "model_solver" / file).read_text()
        assert "visible_key" not in text
        assert "granite_solver" not in text
    scorer = runpy.run_path(str(ROOT / "score.py"))["score"]
    items, key = load(ROOT / "items.json"), load(ROOT / "visible_key.json")
    trials = [("batch-v5-screen-named_review-01", "1x", "named_review"),
              ("batch-v5-screen-named_review-01", "3x", "named_review"),
              ("batch-v16-screen-named_json_short-01", "1x", "named_json_short"),
              ("batch-v16-correction-named_json_short-01", "3x", "named_json_short"),
              ("batch-v16-repeat-named_json_short-01", "1x", "named_json_short")]
    evidence = [score_evidence(prefix, budget, stage, items, scorer, key) for prefix, budget, stage in trials]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0],
              "new_live_model_requests": 0, "source_and_input_hashes": "passed",
              "inference_key_and_rules_import_check": "passed", "cli_contracts": cli_contracts(),
              "saved_response_replays": evidence,
              "limits": ["Mocked requests do not establish endpoint compatibility or availability.",
                         "Replaying saved responses does not establish live reproducibility or new accuracy.",
                         "Current full-set curve and complete live component ablations remain unmeasured."]}
    (ROOT / "CHECKS.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
