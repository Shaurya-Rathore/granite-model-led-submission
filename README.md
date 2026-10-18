# Building around Granite

Granite interprets the notes as typed constraints. Python validates the extracted
facts, searches all 720 schedules and returns the unique assignment, every valid
assignment, or a minimal conflict with verbatim source quotations.

Start with the [two-page write-up](WRITEUP.pdf), [results](RESULTS.md) and
[ablation table](ABLATIONS.md). The default method is `named_review`.

## Setup and run

Python **3.12.12**; dependencies are pinned in `requirements.txt`.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Set `OPENROUTER_BASE_URL` and `OPENROUTER_API_KEY` in `.env` to the provided
endpoint and key. Environment variables take precedence. Credentials are not
included in the repository.

Run from the repository root, choosing the required budget:

```sh
./run items.json --budget 1x --out answers.json
```

`--budget` also accepts `3x` and `10x`. Add `--trace-out traces.json` to save
extractions and raw responses. Input paths and output paths are configurable;
the runner never loads saved predictions or the answer key.

| Budget | Allocation |
| --- | --- |
| 1x | One complete extraction. |
| 3x | Extraction, independent reading, focused review. |
| 10x | Up to six extraction batches, independent reading, review, up to two targeted rereads. |

Every request uses `ibm-granite/granite-4.2-8b`, temperature **1.0**, top-p
**0.95**, disabled reasoning and `X-Item-Id`. There are no automatic retries.
On an endpoint failure, the CLI exits nonzero and retains other completed items.
An optional-call failure can still lose that item's earlier extraction.

The optional `--stage named_json_short` uses a compact format guide with the
DeepInfra JSON-object route. `--stage named_json` is its full-schema-text
control. Neither replaces the strict-schema default; no automatic route fallback
is performed. Clue interpretation is model-based; header parsing and literal
entity checks are symbolic. No training or aggressive clue grammar is used.

## Results and reproduction

The measured default scored **5/6 exact (83.33% macro exact)** at both 1x and 3x
on the same selected, balanced six-case public panel, one run per budget.
The full-set curve, 10x score and component-removal scores remain N/M after the
API spending limit stopped evaluation. These are public pilot results.

`results.zip` contains the measured answers, scores and raw-response traces,
plus the separate short-guide trials and clue-context summary. Extract it with:

```sh
python3 -m zipfile -e results.zip results
```

Score a completed run against the unchanged public scorer and key:

```sh
python3 -m model_solver.evaluate answers.json --items items.json \
  --key visible_key.json --traces traces.json --out score-result.json
```

Omit `--traces` when no trace file was saved. Failed items remain in the requested
population's denominator. Headline exact counts use `score.per_case`;
`per_item` contains partial diagnostics for unique cases.

For component comparisons, `ablate.py` prints a plan without making API calls:

```sh
python3 ablate.py items.json --key visible_key.json --out-dir results/ablations
```

`--execute` makes live calls; see [ABLATIONS.md](ABLATIONS.md) for applicability.

## Source

- `model_solver/pipeline.py`: call allocation and extraction/review flow.
- `model_solver/named.py` and `named_prompts.py`: typed contract and prompts.
- `model_solver/flat.py` and `representation.py`: binding and validation.
- `model_solver/engine.py`: exhaustive solving and minimal conflicts.
- `model_solver/transport.py`: endpoint client and header parsing.
- `MANIFEST.json`: hashes of the packaged files.

Legacy pipelines, test files and loose intermediate artifacts are omitted.
The cleanup removes unused paths; the measurements in `results.zip` are the
original development runs, with no new live evaluation claimed.
