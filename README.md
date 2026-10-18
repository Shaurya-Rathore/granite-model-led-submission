# Model-led Granite constraint extraction

This submission uses **model-based constraint extraction** followed by exact
schedule enumeration. Granite interprets the notes; code validates typed facts,
enumerates schedules and binds exact source citations. The default is
`named_review`. Header parsing and literal entity anchoring are symbolic;
constraint meanings come from the model.

## Read the submission

1. [Two-page account](WRITEUP.pdf): characterization, architecture, experiments,
   failure modes and future work. [Editable text](WRITEUP.md).
2. [Results](RESULTS.md): measured scores, case handling and saved evidence.
3. [Ablations](ABLATIONS.md): component switches and reproduction commands.
4. [Method comparison](METHOD_COMPARISON.md): default, experimental candidate
   and historical results.

**Measured result:** 5/6 exact (83.33% macro exact) at both 1x and 3x on the same
selected, balanced six-item public panel, one run per budget. The current
method's full-set curve, 10x score and component-removal scores are unmeasured.
Further evaluation stopped when the API key reached its spending limit.
These results establish a development pilot, not held-out accuracy.

The package uses unchanged Granite weights, generic prompts and exact solving.
It includes no aggressive clue grammar, per-item answer logic, fine-tuning,
frontier-model inference or credentials.

## Setup

Python **3.12.12**. Runtime dependencies are pinned in `requirements.txt`.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Set `OPENROUTER_BASE_URL` to the evaluator-provided endpoint and
`OPENROUTER_API_KEY` to the supplied key. Environment variables also work and
take precedence. The runner reads `.env` beside this README; do not share that
file. No credential is included in the archive.

## Required entrypoint

Run from the extracted archive root:

```sh
./run items.json --budget 1x --out answers.json
./run items.json --budget 3x --out answers.json
./run items.json --budget 10x --out answers.json
```

Each command is a separate live run. Only execute the desired budget. The
runner honors the supplied input path and writes the specified JSON output;
it does not load stored predictions or the scoring key. One item worker is
the default. An optional `--trace-out traces.json` preserves extraction history.

Every call uses only `ibm-granite/granite-4.2-8b`, temperature **1.0**, top-p
**0.95**, disabled reasoning, and the item's exact `X-Item-Id` header. There are
no automatic within-item retries. Sampling remains stochastic.

| Budget | Default allocation |
| --- | --- |
| 1x | Exactly one complete extraction. |
| 3x | Complete extraction, independent complete reading, focused source review. |
| 10x | Up to six primary batches, one independent reading, one review, at most two targeted rereads; at most ten total. |

The solver checks 720 schedules. It returns the single assignment, every
surviving assignment, or a source-line-minimal conflict with verbatim citations.
Both scope mistakes and well-formed semantic errors remain possible. More than
four surviving schedules is flagged in traces, never silently truncated.

On an HTTP/transport failure, the CLI exits nonzero and preserves other
completed items. An optional-call HTTP failure can still lose that item's
earlier usable extraction. The evaluator keeps missing items in the scoring
denominator. Detailed failure modes are covered in the write-up.

## Score a completed run

```sh
python3 -m model_solver.evaluate answers.json --items items.json \
  --key visible_key.json --out score-result.json
```

The original public items, scoring key, and scorer are included unchanged for
offline reproduction. The evaluator can substitute private inputs. Only the
offline evaluator loads the key; inference never imports it. `per_item` contains
partial diagnostics for unique cases, so headline exact counts must come from
`score.per_case`, not a sum of `per_item` values.

## Ablations

```sh
python3 ablate.py items.json --key visible_key.json --out-dir results/ablations
```

This prints a **dry-run plan**, including a request upper bound, without making
API calls. Add `--execute` to run that plan against the configured endpoint.
Use fresh output directories. [ABLATIONS.md](ABLATIONS.md) defines applicability
and labels unmeasured results N/M.

## Offline checks and source map

```sh
python3 -m unittest model_solver.test_named model_solver.test_incremental \
  model_solver.test_model_solver model_solver.legacy_v1.test_model_solver -q
python3 check_submission.py
```

Recorded verification: **111 local tests passed**, 20 saved item-run replays
matched, and 24 captured strict requests matched the measured default's client.
These checks use synthetic or saved responses and make no live model calls.
The records are in `CHECKS.json` and `PACKAGING_CHECKS.json`.

- `model_solver/named_prompts.py`: shared semantic instructions and examples.
- `model_solver/named.py`: typed contract and review targeting.
- `model_solver/incremental.py`: extraction/read/review orchestration.
- `model_solver/transport.py`: endpoint client and mechanical header parsing.
- `model_solver/engine.py`: exhaustive solving and minimal source conflicts.
- `SOURCE_PROVENANCE.json`: origin and changes of packaged source files.
- `MANIFEST.json`: final artifact hashes.
- `evidence/`: saved development results; never used to answer inputs.

[Package contents](SUBMISSION_STATUS.md) and the [brief-to-file mapping](REQUIREMENTS.md)
provide a compact handoff reference.

The short-guide candidate is optional: `--stage named_json_short`. It changes
the output route to DeepInfra JSON-object mode and uses a compact format guide.
It is not the submission default. `--stage named_json` is its full-schema-text
JSON-mode control. Older model-only stages are retained for comparison.
No automatic route switch or model fallback is performed.
