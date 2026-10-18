# Submission overview

The package contains a model-led Granite system, the required two-page account,
and reproducible development evidence. The selected default is `named_review`.

## Contents

| Deliverable | Files |
| --- | --- |
| Runnable system and all three budget paths | `run`, `model_solver/` |
| Setup and pinned environment | `README.md`, `requirements.txt`, `.python-version`, `.env.example` |
| Two-page architecture account and editable source | `WRITEUP.pdf`, `WRITEUP.md` |
| Measured results and case handling | `RESULTS.md`, `evidence/` |
| Component switches and reproduction commands | `ABLATIONS.md`, `ablate.py` |
| Method distinctions and brief mapping | `METHOD_COMPARISON.md`, `REQUIREMENTS.md` |
| Recorded offline checks and provenance | `CHECKS.json`, `PACKAGING_CHECKS.json`, `SOURCE_PROVENANCE.json`, `MANIFEST.json` |
| Current scope and review handoff | `SUBMISSION_SUMMARY.json` |
| Original public evaluation materials | `items.json`, `visible_key.json`, `score.py`, `CANDIDATE_BRIEF.md` |

Granite uses unchanged weights, the required sampling settings, disabled reasoning
and per-item request headers. Code handles typed validation, complete schedule
enumeration and verbatim source citations. Header parsing and entity anchoring
are mechanical; clue interpretation is model-based. Credentials and the aggressive
rules implementation are excluded from the archive.

## Evidence scope

The default achieved **5/6 exact (83.33% macro exact) at both 1x and 3x** on the
same selected, balanced six-item public panel, one sampled run per budget.
Recorded offline verification includes 111 passing local tests, 20 matching
saved item-run replays and 24 equivalent strict requests.

Evaluation ended at the API spending limit. The current method's full-set curve,
10x score and component-removal scores are unmeasured and explicitly marked N/M.
The reproduction commands are provided; their availability is not a measured
ablation result. The structural core's individual accuracy contributions were
not isolated. Private held-out grading belongs to the evaluator.

## Review handoff

Read `README.md`, `WRITEUP.pdf`, `RESULTS.md` and `ABLATIONS.md` first. Saved scores,
source traces and historical trials remain separate. The optional short-guide
candidate has not replaced the default. Runtime behavior and measured evidence
are preserved during this documentation pass; code cleanup and presentation
polish are the next review stages. No live model requests were made in this pass.
