# Brief-to-submission mapping

The original requirements are in the unchanged `CANDIDATE_BRIEF.md`.

| Brief requirement | Submission implementation or evidence |
| --- | --- |
| Required root command | `./run <items.json> --budget <1x\|3x\|10x> --out <answers.json>` selects the model-led default. |
| Model and sampling constraints | Granite 4.2 8B only; temperature 1.0, top-p 0.95, reasoning disabled; `X-Item-Id` on every request. |
| Call budgets and model dependence | Per-item call guards, no automatic retries, saved traces and recorded synthetic checks. |
| Unique, ambiguous and inconsistent handling | Exact enumeration returns one schedule, all surviving schedules, or an inclusion-minimal source conflict with full quotations. |
| Python and dependency pinning | Python 3.12.12, `requirements.txt`, setup and endpoint configuration in `README.md`. |
| Two-page account | `WRITEUP.pdf`; editable `WRITEUP.md`. Covers model characterization, design, experiments, failures, generalization and future work. |
| Constraint-extraction disclosure | Model-based clue interpretation; symbolic header parsing and literal entity grounding. No training or aggressive clue grammar. |
| Accuracy curve and case handling | Selected public-panel 1x/3x measurements and confusion matrices in `RESULTS.md`; full-set curve and 10x unmeasured. |
| Component ablation table | `ABLATIONS.md` lists the measured baseline and unmeasured removal arms, with commands in `ablate.py`. Structural components were not separately isolated. |
| Reproducibility and private credentials | Source hashes, raw responses, run counts and official scores are preserved; credentials are excluded. |

## Evaluation boundary

The measured result is a six-item development pilot. The complete current-system
budget curve and component ablations requested by the brief were not obtained
before the API spending limit ended evaluation. They remain N/M. Recorded offline
checks verify implementation behavior; no live execution of the assembled archive
or held-out performance is claimed. The package and commands are provided for
review and evaluator reproduction.
