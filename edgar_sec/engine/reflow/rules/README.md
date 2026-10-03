# `edgar_sec/engine/reflow/rules` — reflow decision rules

## Purpose

Defines feature predicates and the rules that classify text blocks for reflow.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `thresholds.py` | Feature vocabulary and predicates. |
| `cascades.py` | Rule models, rule engine, and block decision API. |

## Contracts

- **Decisions combine feature predicates and preserve safeguards.** Tagged or ambiguous
  content is not unwrapped solely on a permissive prose match.
- **Every decision carries evidence and a trace** for downstream rendering and review.
- **Rule order is part of behavior.** Protected structures take precedence over
  permissive prose rules; the final fallback preserves ambiguous blocks.

## Public surface

- `FEATURE_REGISTRY`, `FeatureSpec` — `thresholds.py`.
- `FeatureThreshold`, `GroupQuota`, `SynergyRule`, `Rule`, `RuleEngine` — `cascades.py`.
- `decide_block` — public classification entry point in `cascades.py`.

## Command surface

None. This is a library package with no CLI.

## Tests

Mirrored coverage lives under `tests/engine/reflow/rules/`.

## Deliberate gaps

- **No runtime threshold learning or adaptive recalibration.** Predicates are fixed in
  the checked-in feature vocabulary.
- **No statement-quality validation.** Decisions classify layout for rewriting; they do not
  assess the financial correctness of a tagged table.
