# Component comparisons

The full-system baseline is one run per budget on the selected balanced six-item
public panel. Each removal arm uses that same population for reproduction.
**N/M = not measured; -- = component inactive at that budget.**

| Setting | 1x macro exact | 3x macro exact | 10x macro exact |
| --- | --- | --- | --- |
| Full `named_review` | 83.33% (5/6) | 83.33% (5/6) | N/M |
| Without fixed semantic examples: `no_examples` | N/M | N/M | N/M |
| Without the scope/relation contrast block: `no_scope_examples` | N/M | N/M | N/M |
| Without literal entity hints/checks: `no_grounding` | N/M | N/M | N/M |
| Without independent reading: `no_independent` | -- | N/M | N/M |
| Without final correction: `no_audit` | -- | N/M | N/M |
| All-source review instead of focused selection: `no_focus` | -- | N/M | N/M |
| Without primary extraction chunking: `no_chunking` | -- | -- | N/M |

The removal scores were not obtained before the API spending limit ended
evaluation. The switches and commands are implemented for reproduction; no
numerical component benefit is inferred from their existence or local tests.
The exact solver, validation and citation binding remain fixed, so their separate
accuracy contributions were not isolated. The brief's complete measured
component-ablation requirement is therefore not fulfilled by this table.

## Design of the comparisons

- At 3x, `no_independent` and `no_audit` normally use two calls. Freed calls are
  not replaced with an arbitrary task. Record actual calls alongside accuracy.
- At 10x, the bounded reread policy remains active; the cap is still ten.
- At 1x, independent reading and review are absent, so their switches have no
  effect. Primary extraction chunking applies only to 10x.

## Reproduce an arm

```sh
./run items.json --budget 3x --out full.json --trace-out full-traces.json
./run items.json --budget 3x --ablation no_independent \
  --out no-independent.json --trace-out no-independent-traces.json
python3 -m model_solver.evaluate full.json --items items.json \
  --key visible_key.json --traces full-traces.json --out full-score.json
python3 -m model_solver.evaluate no-independent.json --items items.json \
  --key visible_key.json --traces no-independent-traces.json \
  --out no-independent-score.json
```

These commands make live calls. Use identical inputs, fresh output paths, and
report macro exact, per-kind rates, confusion matrices, actual calls, failures
and run count for both arms. Keep failures in the requested-population denominator.

## Reproduction driver

```sh
python3 ablate.py items.json --key visible_key.json --out-dir results/ablations
```

The default prints a dry-run plan and request upper bound without API calls.
`--execute` runs the baseline and applicable removal arms, saves traces and
scores every requested case. It refuses existing output directories and stops
on an incomplete run. No execution of this matrix occurred during packaging.
