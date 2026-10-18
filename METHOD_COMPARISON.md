# Method distinctions

## Selected method and experiments

| Method | Main distinction | Measured scope | Role in this package |
| --- | --- | --- | --- |
| `named_review` | Named roles, fixed contrasts, strict schema; independent reading and focused review at larger budgets | Same six-item public panel: 5/6 at 1x and 5/6 at 3x, one run each | Default |
| `named_json_short` | Same interpretation policy; compact format guide and DeepInfra JSON-object route with local validation | Six-item 1x screen: 5/6. Separate B2-022 3x correction: 1/1; separate 1x repeat: 0/1 | Optional experiment |
| `named_json` | Full schema text in the prompt on the same JSON-object route | Smaller three-case 1x control: 2/3 | Optional route control; not the same population as the six-item screen |
| Historical no-rules harness | Earlier implementation with aggressive symbolic clue interpretation disabled | Full public set: 26/60 (43.33%) at 1x, one run | Historical reference only; not this submission's accuracy |

The rules-heavy implementation and its scores are excluded. The archive-root
`./run` selects model-led inference. The original development workspace has a
separate root launcher for its preserved baseline.

## Interpreting the comparisons

- A selected-panel percentage and a full-set percentage describe different
  populations. They do not establish an improvement over one another.
- The short-guide stage changes the provider/output route relative to the strict
  default. Effects cannot be attributed solely to prompt length. Its full-schema
  JSON-mode control uses the same route but was measured on a smaller panel.
- The successful B2-022 correction and failed repeat are separate trials. Neither
  supplies a broader 3x result or a component ablation.
- The six-item screen and diagnostic probes are public development data.

## Validation, review and solving

Structural validation checks fields, types, source IDs, duplicates and entity
mentions. Model review checks the proposed meaning against the original source.
A valid structure or a model's `supported` label is not a proof of faithful
interpretation. The exact solver is correct relative to its input facts.

JSON is the serialization; the semantic representation is five typed operators,
named roles and negation. Compact strings, large choice menus and native-tool
experiments did not establish an accuracy gain and are not the selected method.
The submitted source review is the review call inside `named_review`; separate
`source_check`/`source_focus` experiments are not bundled.

## Provenance

The named interpretation body, prompts, validator and solver preserve the
measured default. Packaging removes dispatch to unbundled experiments and uses
one item worker, matching the sequential screen. `SOURCE_PROVENANCE.json`
records origin hashes, declared changes and request-equivalence checks.
Original evidence files are preserved unchanged; historical manifests retain
workspace-relative paths. Use the README commands to run the packaged system.

The development file `gemini_llm_calls.csv` is a code-call inventory, not an HTTP
request ledger. It is excluded. Actual model settings and counts come from
source, traces and experiment records. The answering pipeline uses only Granite.
