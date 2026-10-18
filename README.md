# Building around Granite

[Read the two-page write-up](WRITEUP.pdf) · [Ablation table](ABLATIONS.md)

Granite interprets the clues; Python validates typed facts and searches all 720
schedules. The default method is `named_review`. Results, experiments and design
decisions are described in the PDF.

## Setup

Python **3.12.12**. Dependencies are pinned in `requirements.txt`.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 -m zipfile -e results.zip results
```

Set `OPENROUTER_BASE_URL` and `OPENROUTER_API_KEY` in `.env` to the provided
endpoint and key. Environment variables take precedence. Credentials are excluded.

## Run

```sh
./run results/public/items.json --budget 1x --out answers.json
```

Use any input items path; `--budget` accepts `1x`, `3x` or `10x`. Add
`--trace-out traces.json` to save model responses and extraction history.
The runner never loads saved answers or the scoring key.

Every call uses `ibm-granite/granite-4.2-8b`, temperature **1.0**, top-p **0.95**,
disabled reasoning and `X-Item-Id`. There are no automatic retries. Endpoint
failures produce a nonzero exit; other completed items are saved. An optional-call
failure can still lose that item's earlier extraction.

`--stage named_json_short` selects the optional compact-guide experiment;
`--stage named_json` selects its full-schema-text control. These use the DeepInfra
JSON-object route. The default uses a strict schema; no automatic fallback occurs.

## Reproduce results

After extracting `results.zip`, `results/measured-results.md` describes the saved
runs. `results/default/` holds the measured six-case pilot; the `short-guide-*`
folders hold separate diagnostic trials. `results/public/` contains the original
public items and key. Traces, run metadata and source hashes are in the archive.

```sh
python3 -m model_solver.evaluate answers.json --out score-result.json
python3 -m model_solver.ablate results/public/items.json \
  --key results/public/visible_key.json --out-dir results/ablations
```

The scorer uses the extracted public items/key by default. Override `--items` and
`--key` for other inputs; add `--traces traces.json` for extraction diagnostics.
The ablation command prints a plan without API calls; `--execute` runs it.
The full-set curve, 10x score and component-removal scores remain unmeasured.

All Python implementation and evaluation code lives in `model_solver/`.
The root `run` launcher preserves the required command interface.
