# Results

## Measured default

One sampled run at each budget on the same selected public development panel:
B2-002, B2-037, B2-006, B2-022, B2-023 and B2-005. There are two true cases per
kind. Both runs returned all six answers. The default is `named_review`.

| Budget | Exact | Macro exact | Unique | Ambiguous | Inconsistent | Calls | Runs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | 5/6 | 83.33% | 2/2 | 1/2 | 2/2 | 6 | 1 |
| 3x | 5/6 | 83.33% | 2/2 | 1/2 | 2/2 | 18 | 1 |
| 10x | N/M | N/M | N/M | N/M | N/M | N/M | 0 |

B2-022 was the sole miss in both runs: a betweenness clue was strengthened into
adjacency, producing a false contradiction. Additional calls did not improve
this panel's score. Exact scoring includes the full assignments or a valid
minimal conflict, not the case label alone.

### Case handling

Each measured run has the following matrix independently. Rows are true kinds;
columns are declared kinds. Missing/unparsed answers: zero in each run.

| True / declared | Unique | Ambiguous | Inconsistent |
| --- | --- | --- | --- |
| Unique | 2 | 0 | 0 |
| Ambiguous | 0 | 1 | 1 |
| Inconsistent | 0 | 0 | 2 |

The separate official matrices and per-kind rates are preserved in
`evidence/batch-v5-screen-named_review-01-{1x,3x}-score.json`.

## Short-guide experiment

The optional `named_json_short` stage preserves the interpretation policy and
uses a compact format reminder on a JSON-object provider route.

| Trial | Budget | Population | Exact | Calls | Runs |
| --- | --- | --- | --- | --- | --- |
| Screen | 1x | Same six-item panel | 5/6 | 6 | 1 |
| Focused correction | 3x | B2-022 | 1/1 | 3 | 1 |
| Separate repeat | 1x | B2-022 | 0/1 | 1 | 1 |

In the correction trial, both initial readings supplied wrong adjacency facts;
review replaced them with betweenness and recovered the exact answer. The
separate failed repeat is retained. These trials are not pooled into a six-item
3x score, and the candidate remains optional.

## Evaluation scope and reproduction

These are selected public development results, not full-set or held-out accuracy.
The current method's full-set curve, 10x score and component-removal scores are
unmeasured (N/M). A later comparison stopped after six HTTP 403 API-key
spending-limit rejections and zero model responses; it supplies no semantic
accuracy estimate. A de-identified summary is in `evidence/evaluation-stop.json`.

The scorer, public inputs and key are included unchanged. Run counts, predictions,
raw responses and traces accompany each measured trial. `check_submission.py`
replays saved responses and re-scores their answers against the original scorer.
Replay is an implementation check, not another sampled run. Required sampling
settings permit variation between live runs.

Historical results from another implementation are identified separately in
`METHOD_COMPARISON.md`. None is substituted for a score of this default.
