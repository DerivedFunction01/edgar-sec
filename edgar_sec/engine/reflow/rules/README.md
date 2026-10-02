# `edgar_sec/engine/reflow/rules` — 44 calibrated thresholds and the decision cascade

## Purpose

Two modules, and the split is load-bearing. `thresholds.py` says what a measured value has
to be for a feature to count as active evidence. `cascades.py` says which combination of
active features decides a block, and in what order.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `thresholds.py` | `FeatureSpec`, `FEATURE_REGISTRY` (44 features), `_register`. |
| `cascades.py` | `FeatureThreshold`, `GroupQuota`, `SynergyRule`, `Rule`, `FEATURE_GROUPS`, `RuleEngine`, `decide_block`, `_decide`. |

`__init__.py` is a docstring per `AGENTS.md` §1.2. Consumers import the leaf:

```python
from edgar_sec.engine.reflow.rules.cascades import decide_block
```

## The thresholds are calibrated, not chosen

Every predicate in `thresholds.py` was fitted with scikit-learn optimal information-gain
decision splits over 3,411 ground-truth acceptance blocks. `optimal_threshold` records the
fitted split and the predicate is that split rounded to a readable value. Where the two
differ, **the rounded predicate is the one that runs**.

| Feature | Fitted split | Predicate | Accuracy |
| :--- | :--- | :--- | :--- |
| `function_word_ratio` | 0.299 | `>= 0.30` | 84.7% |
| `article_density` | 0.977 | `>= 1.0` | 85.5% |
| `width_fill_65_ratio` | 0.989 | `>= 0.98` | 78.3% |
| `row_template_periodicity` | 0.078 | `>= 0.08` | 85.2% |
| `indent_alternation_ratio` | 0.011 | `>= 0.01` | 83.3% |
| `continuation_col0_ratio` | 0.006 | `>= 0.01` | 82.4% |
| `rewrap_residual` | 0.001 | `<= 0.001` | 83.2% |
| `soft_wrap_ratio` | 0.004 | `> 0` | 61.7% |
| `grammatical_comma_ratio` | 0.411 | `>= 0.40` | 62.6% |
| `row_shape_autocorrelation` | 0.0 | `> 0` | 69.0% |
| `gutter_4_col_count` | 1.5 | `>= 2` | 98.4% |
| `cell_edge_aligned_count` | 2.5 | `>= 3` | 87.7% |
| `stub_gutter_numeric_count` | 0.5 | `>= 1` | 86.1% |
| `line_count` | 3.5 | `>= 4` | 86.7% |
| `column_underline_count` | 0.5 | `>= 1` | 81.4% |
| `inset_measure_width` | 134.5 | `0 < v <= 135` | 76.7% |

The four `alpha_density_w*` and four `numeric_density_w*` window features carry their own
fitted splits; `tests/engine/reflow/rules/test_thresholds.py` pins all of them.

**This is why the registry is asserted by count and by order.** A threshold that gets
"tidied" moves a boundary and silently reclassifies blocks, and the failure mode is a
collapsed table rather than a visible error.

## The cascade is a list, and order is the contract

The first rule whose conditions hold decides the block; nothing after it is consulted. The
twenty-five rules run in four bands, listed in this order in `cascades.py`:

1. **Hard protections** (1–7) — tagged tables, structural SGML, tabs, signature
   blocks, checkboxes, injected statement labels, column underlines. Nothing below this band
   can override them.
2. **Continuous narrative** (8) — prose with linguistic flow, a soft wrap, and full width. The
   only "high confidence" unwrap.
3. **Table geometry** (9–19) — prose-dominant numeric alignment, linguistic prose evidence,
   shared numeric columns, separator grids, dot-leader fallback, strong gutters, aligned edges,
   separator runs, dead-space corridors, exhibit indexes, and stub→gutter→numeric rows.
   Dot leaders preserve spacing only after numeric table rules have had a chance to match.
4. **Single lines then general fallbacks** (20–25) — single-line prose, the single-line no-op,
   ordinary prose with no gaps, the layout-gap refusal, the general prose unwrap, and
   `default_preserve_ambiguous`.

Band 4 is what makes the safety bias real: every permissive rule there is guarded by a shape
condition, and the last rule is a preserve.

## Contracts

- **No cut point is hard-coded in a rule.** A rule names a feature and a comparison; the
  value lives in the registry. One table is the only place a threshold can change.
- **A condition shape composes, it does not override.** A rule's `direct_conditions`,
  `group_quotas`, and `synergies` all have to hold. `GroupQuota.max_active` and
  `SynergyRule.min_per_group` are the only way a rule can be *stricter* than a group's
  default, and a synergy can only ask for less per group while demanding more in total.
- **Group membership is total and disjoint.** `FEATURE_GROUPS` names six groups covering 38
  of the 44 registered features; the six read by a rule's direct condition rather than
  through a quota are `continuation_col0_ratio`, `ends_terminal_punct`,
  `inset_measure_width`, `line_count`, `rewrap_residual`, and `starts_capital_or_indent`. No
  feature belongs to two groups, and the ungrouped set is asserted.
- **Evidence is explicit where a rule can explain itself.** A rule with `evidence` or an
  `evidence_builder` reports the reason it matched; otherwise the engine derives one from the
  conditions that fired, so a matched rule always produces non-empty evidence.
- **`decide_block` collapses nothing.** `_decide` above it maps the coarse action onto the
  trace the render and merge passes group by (`fast_prose`, `high_confidence_table`,
  `hard_preserve`, `fast_noop`, `candidate_preserve`), which is why a decision's `trace` is
  shorter than the rule that produced it.
- **A masked block never reaches the cascade.** `_decide(..., has_masked=True)` short-circuits
  to a preserve with evidence `("protected_tagged_table",)`.
- **A single-line block is decided before the cascade.** `RuleEngine.decide` handles
  `line_count <= 1` itself, so no multi-line rule can fire on a one-line block.
- **Row runs reuse the block cascade.** `rewrapper.py` measures a geometrically confirmed run
  as one `BlockContext` and applies the same numeric-table and linguistic-prose rules; a dot leader
  is a fallback preserve signal, not a TOC-specific rejection.

## Public surface

- `FEATURE_REGISTRY` — insertion-ordered `dict[str, FeatureSpec]`, the canonical
  feature-vector order.
- `FeatureSpec` — `name`, `scalar_type`, `description`, `default_predicate`,
  `optimal_threshold`, `hypothesis_ref`, `default_group`.
- `FeatureThreshold(feature, op, value).evaluate(ctx)` — all six operators.
- `GroupQuota(group_name, min_active=1, max_active=None, overrides=())`.
- `SynergyRule(name, group_names, min_total_active, min_per_group=1)`.
- `Rule(name, action, confidence, direct_conditions=(), group_quotas=(), synergies=(),
  evidence=None, evidence_builder=None, rationale="")`.
- `RuleEngine(rules=None)`, `.rules`, `.decide(ctx, line_count=None)`,
  `.evaluate_rule(rule, ctx)`, `.count_active_features(ctx, group_name, overrides=(),
  early_stop=None)`.
- `decide_block(ctx, line_count=None)`,
  `_decide(context_or_features, line_count, has_masked=False)`.

## Command surface

None. This is a library package with no CLI.

## Production consumers

- `../engine/rewrapper.py` — `_classify_block` calls `_decide` with a `BlockContext`, and
  `decide_block` with a compact `_Features` record when a caller supplies one.

## Tests

- `tests/engine/reflow/rules/test_thresholds.py` (119) — the registry count, order, and split
  points.
- `tests/engine/reflow/rules/test_cascades.py` (46) — the condition shapes, the rule
  sequence, the ordering guarantees, and both `_decide` branches.

## Deliberate gaps

- **Rules 20 and 21 are unreachable.** `RuleEngine.decide` answers `line_count <= 1` itself
  before iterating `self.rules`, so `unwrap_single_line_prose` and
  `preserve_single_line_noop` never fire. The early branch returns the same two outcomes
  with the same evidence and trace names, so nothing observable is missing; the rules are
  retained so the list reads as the full decision surface.
- **`hard_preserve_stub_gutter_numeric` tags rather than preserves.** The name says preserve;
  its action is `ACTION_TAG_AND_PRESERVE`. Renaming it would change the `trace` string
  callers group by, so it stands.
- **`SynergyRule` and `GroupQuota.max_active` have no production use.** The twenty-five
  production rules use only `direct_conditions`, `min_active` quotas, and overrides. The
  other two shapes are part of the public rule vocabulary and are covered in isolation by
  the tests so they are not dead code by accident.
- **`FeatureSpec.default_group` is never populated.** Every feature is a member of at most
  one group in `FEATURE_GROUPS`, so the per-spec field is redundant with that map. It is
  part of the `FeatureSpec` contract and is left at its default.
- **`_OP_MAP` is never read.** The operator dispatch in `FeatureThreshold` is a literal `if`
  chain and `_OP_MAP` is a reference-tree leftover. Deleting it is a one-line change.
- **`count_active_features(early_stop=...)` is used for its side effect.** `evaluate_rule`
  passes `early_stop` only when a quota has no maximum *and* the rule declares explicit
  evidence, on the reasoning that derived evidence needs the full active set while declared
  evidence does not.
- **No rule learns.** The thresholds are fixed. There is no per-form calibration, no feedback
  loop from a review corpus, and no way to re-fit a split without editing `thresholds.py` and
  the test that pins it.
- **No feature for table *quality*.** The cascade decides tag-versus-preserve. Whether a
  tagged span is a well-formed statement is the renderer's and the review corpus's question,
  not a feature here.
