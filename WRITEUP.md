# Building around Granite

Granite reads each line and extracts what it asserts. Python handles the schedule search. Most of the difficulty was in interpreting the clues correctly. Even valid JSON could contain a wrong relationship.

## Experiments that shaped the design

| Experiment                     | Result                                                                                          | Decision                                        |
| ------------------------------ | ----------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Isolate a clue                 | 17/17 correct in isolation; 13/17 with full notes, on matched repeated probes.                  | Keep reviews focused. Test batching separately. |
| Split extraction into batches  | At 3x, scored 5/6, matching the default. One case improved and another regressed.               | Keep complete reads and review.                 |
| Compact atoms and choice menus | Produced malformed facts or incorrect meanings. No improvement in the screens.                  | Keep named roles in JSON.                       |
| Native extraction tools        | The first pilot covered 1/19 lines. The second returned an empty table.                         | Set this route aside.                           |
| Shorter format guide           | Scored 5/6 in a 1x screen. Separate B2-022 trials were correct at 3x and failed in a 1x repeat. | Leave optional; retain the default.             |

The clue probes repeated six selected lines. Each screen was a single run. The short-guide trial also changed the provider/output route, leaving the effect of prompt length unresolved.

## The system I kept

Granite extracts five operators: `block`, `station`, `before`, `next` and `between`. It identifies scope, relation, direction and negation, with named JSON roles for the arguments. `Between` accepts either endpoint order. A station's time belongs to whoever occupies it in the final schedule.

Every line receives an `asserted`, `ignored` or `unclear` row. Python checks types, entity mentions, duplicates and coverage, then attaches the original quotation. This avoids asking Granite to reproduce citations. The checks still allow semantically incorrect facts through.

Python enumerates all 720 schedules and returns a unique assignment, all surviving assignments, or a conflict reduced until every cited line is necessary. The solver's results depend on the extracted constraints being correct.

### Call allocation

- **1x:** Extract every line once.
- **3x:** Extract, read independently, then review. Invalid review edits leave earlier facts unchanged.
- **10x:** Up to six extraction batches, an independent read, a review and up to two targeted rereads.

## Results and next steps

### Measured result

I ran the default configuration, `named_review`, once at each measured budget on the same six public cases: two unique, two ambiguous and two inconsistent.

| Budget | Exact | Macro exact | Calls |
| ------ | ----- | ----------- | ----- |
| 1x     | 5/6   | 83.33%      | 6     |
| 3x     | 5/6   | 83.33%      | 18    |
| 10x    | N/M   | N/M         | N/M   |

Both measured budgets got 2/2 unique, 1/2 ambiguous and 2/2 inconsistent cases correct.

B2-022 failed in both runs. Granite read a betweenness constraint as adjacency. The separate short-guide trial corrected this during a 3x review, although the 1x repeat failed. I treated that result as diagnostic and left it out of the main panel.

The additional review calls produced no improvement in the measured exact score.

Evaluation covered a selected public pilot. The API spending limit stopped the full-set runs, 10x evaluation and component-removal experiments. `ABLATIONS.md` records these as N/M. I also have no isolated accuracy measurement for the structural core.

### Where it breaks, and what I would do next

Independent reads can agree on the same misinterpretation. Provisional facts still reach the solver, and any error in those facts carries into the assignments or reported conflicts. Optional-call failures can also discard an earlier usable result.

Human-written notes are another open problem. They often contain pronouns, references to earlier statements and implied context. The fixed header parser and literal entity grounding have yet to be tested on that kind of wording.

I used no clue grammar, per-item logic, training or frontier inference.

With another month, I would rerun the full set and finish the ablations, then test independently written clues and checkpoint recovery. I would prioritize improvements to 1x extraction, given the unchanged score at 3x.

**Reproduction.** Python 3.12.12; unchanged Granite 4.2 8B; temperature 1.0; top-p 0.95; reasoning disabled. Every call carries `X-Item-Id`; automatic retries are disabled. Pinned dependencies, traces and source hashes are included.
