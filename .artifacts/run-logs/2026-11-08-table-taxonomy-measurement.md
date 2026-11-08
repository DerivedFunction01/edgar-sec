# Table-taxonomy measurement — earnings exhibits (2026-11-08)

Owner refinement (2026-11-08 ~00:02 EST): do not adopt `classify_table` on faith — measure it against the lane heuristics and let the evidence decide.

## Method

- Inputs: every table geometry from the Step 6 corpus specimens with exhibits (125 filings, 1,136 tables) plus the committed fixture corpus.
- Arm A: lane heuristics exactly as committed at b62649ad (`_table_roles` recovered from git).
- Arm B: `classify_table` (engine/tables/taxonomy/classifier.py) with FAMILY_SPECS as it stands; roles taken from the primary family plus tags and all matches, mapped income_statement / balance_sheet / cash_flow.
- Numeric-recognition path held constant across arms: the pre-rework private recognizer in both arms (the measurement isolates role classification; the common-numbers rework landed separately and is fixture-identical).
- Ground truth: the Step 6 corpus record's per-table roles and headline figures. Caveat: the recorded roles were themselves produced by caption/keyword rules of similar ancestry to arm A, so arm A's role scores are partially circular; the headline-figure scores are independent (recorded values), and several arm-B pathologies are visible without any truth definition.

## Per-role results (tp / fp / fn over 1,136 tables)

| role | arm A (heuristics) | arm B (taxonomy) |
|---|---|---|
| income_statement | 93 / 0 / 0 | 81 / 114 / 12 |
| balance_sheet | 81 / 0 / 0 | 3 / 6 / 78 |
| cash_flow | 52 / 0 / 0 | 43 / 4 / 9 |
| non_gaap_recon (no spec) | 55 / 0 / 0 | n/a |
| segment (no spec) | 52 / 0 / 0 | n/a |
| guidance (no spec) | 12 / 0 / 0 | n/a |
| summary (no spec) | 8 / 0 / 0 | n/a |

Taxonomy-only families: `equity_statement` fired on 99 tables and `eps_reconciliation` on 15; the corpus record carries no equity-statement ground truth, so these firings are unadjudicated — noted, not credited.

## Decisive downstream metric — headline figures (56 specimens, 168 components)

| arm | found | missed | wrong |
|---|---|---|---|
| A (heuristics) | 135 | 0 | 0 |
| B (taxonomy) | 128 | 7 | 0 |

Arm B lost all three components on three specimens because no exhibit earned an income_statement classification there, so the headline search landed on the wrong exhibit: 0001402829-08-000026 (Revenues 210,360 / Net income 17,399 / Diluted EPS 0.83), 0001021270-19-000041 (Total revenue 64,595), 0001104659-22-087209 (Total revenues 602,707 / Net loss (20,809).

## Disagreements (statement roles, table level)

- Taxonomy right / heuristic wrong: **0 tables**.
- Heuristic right / taxonomy wrong: **221 tables**. Specimen examples: 0001193125-05-202866 tables 0–1 classified income_statement by the taxonomy with no statement content; 0001178913-09-001176 balance-sheet tables (positions 1, 3, 9 across exhibits) missed entirely while non-statement tables were labelled income_statement/balance_sheet; 0001104659-04-022379 positions 3–6 all labelled income_statement.

## Finding — stale vocabulary

The taxonomy's vocabulary does not earn its place on current earnings exhibits: balance-sheet recall is 3/81 (the balance vocabulary essentially never fires on exhibit presentations), the income vocabulary over-fires (114 false positives, including cover/summary tables), and equity_statement fires on 99 tables without corroboration. The specs appear tuned to filing-body statement presentations, not EX-99 exhibit tables.

## Adoption decision

**Heuristics, for every measured role.** The taxonomy wins nowhere: statement roles stay with the lane heuristics (`_table_roles` remains, now as a measured decision rather than a default), and the no-spec roles (non_gaap_recon, guidance, segment, summary) stay earnings-local as before. `classify_table` is NOT wired into the earnings extraction; its production-caller count stays zero from this lane. If the registry is ever refreshed against exhibit presentations, this measurement is the baseline to beat.

## Common-numbers rework (same pass)

Private `_NUMERIC_RE` removed from the earnings extraction; cell recognition now goes through `clean_numeric` in `engine/forms/common/numbers.py` (schema numeric tokens + currency token handling), the same shared machinery the XML family processors use. Values are still served as printed. Fixture-corpus extraction output before vs after the whole rework pass: **byte-identical** (7 specimens, full result dump diffed). No escape-hatch remnants: the only regexes left in the package are whitespace collapsing, the earnings-specific headline label patterns (no currency/unit/numeric vocabulary inside them), and the filename-family patterns in selection.

## Gate on the reworked tip

Scoped gate (`check.py tests/engine/forms tests/apps/client --workers 2`): all 21 scanners clean; pytest 1,888 passed, 1 failed — `test_statement_battery_audit.py::test_statement_graphs_reproduce_battery_facts`, an XBRL battery test that does not touch the earnings code. It passes in isolation both on the pre-rework tree (77s) and on the reworked tip (102s); the full-suite failure occurred under heavy box contention (suite wall time 37 min). The held-out drive ran on pre-rework code; its coverage claims ride table counts, roles, and headline values whose recognition path is proven fixture-identical above, and role assignment is unchanged by this pass — a drive re-run is not needed.
