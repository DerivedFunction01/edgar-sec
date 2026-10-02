# `edgar_sec/domain/forms/common/` — Form-Agnostic Contracts, Schemas, and Aliases

## Purpose

Shared domain contracts used across SEC form normalization and evaluation: the canonical
form-family alias mapping, checkmark token specifications, evaluator decision models, base
data models, cover phrase rules, declarative checkbox schemas, and cover label vocabularies.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `aliases.py` | `FORM_FAMILY_ALIASES` (all 30 canonical SEC form aliases), `FORM_FAMILY_SUFFIXES`, `form_family()`, `resolve_alias()`, `aliases_for_family()` |
| `checkmarks.py` | `CANONICAL_CHECKED`, `CANONICAL_UNCHECKED`, bracket pairs, checked/unchecked symbol tables, `FONT_GLYPH_MAPPINGS`, `CHECKMARK_MARK_RE`, `font_glyph_state()` |
| `decisions.py` | `DecisionAction` (`PROCEED`, `REFETCH_SUB_DOC`, `SKIP_HARD_STUB`), `EvaluatorDecision` |
| `models.py` | `CoverEvidencePack`, `BodyEvidencePack`, `ItemDefinition`, `StageRecord`, `ContentTransform`, `Evaluator`, `derive_lexical_pack()` |
| `rules.py` | Seven `PhraseSequenceRule` tables (banner, form title, period/registrant, jurisdiction, address, securities exchange, common phrases) |
| `schemas.py` | `CheckboxConstraint`, `CoverCheckboxSchema`, `STATUTORY_CHECKBOX_CONSTRAINTS`, `ANNUAL_CHECKBOX_SCHEMA`, `QUARTERLY_CHECKBOX_SCHEMA` |
| `vocabulary.py` | `COVER_LABELS`, `COVER_LABELS_FLAT`, `CHECKBOX_GRID_RE`, filer-category constants, cover/value regexes, `is_state_value()` |

## Contracts

- **Canonical alias resolution:** `resolve_alias()` maps all 30 empirical form aliases
  (`10-K405`, `10-KSB`, `10-KT`, `20FR12B`, `8-K12B`, …) to one of `"10-K"`, `"10-Q"`,
  `"8-K"`, `"20-F"`, `"6-K"`, or `None`. Every alias resolves into that set.
- **Ordered suffix stripping:** `form_family()` strips amendment and filing suffixes in a
  fixed priority order (`_A`, `_W`, `_POS`, `-POS`, `MEF`, `-W`, `/A`), so `10-K/A` and
  `10-K405` both land on `10-K`. There is no separate `normalize_form()`.
- **Statutory constraints are declarative:** all seven SEC cover constraints (WKSI and
  shell exclusion, 12-month compliance, SOX 404(b), EGC transition, error correction,
  recovery analysis) are `CheckboxConstraint` values in `STATUTORY_CHECKBOX_CONSTRAINTS`.
- **Layer-1 purity:** zero internal dependencies on `infra`, `engine`, `pipelines`, or
  `apps`.

## Public surface

- `resolve_alias(form: str | None) -> str | None`, `form_family(form: str) -> str`, `aliases_for_family(family: str) -> tuple[str, ...]`, `FORM_FAMILY_ALIASES`, `FORM_FAMILY_SUFFIXES`
- `CoverEvidencePack`, `BodyEvidencePack`, `ItemDefinition`, `StageRecord`, `ContentTransform`, `Evaluator`, `derive_lexical_pack()`
- `CheckboxConstraint`, `CoverCheckboxSchema`, `STATUTORY_CHECKBOX_CONSTRAINTS`, `ANNUAL_CHECKBOX_SCHEMA`, `QUARTERLY_CHECKBOX_SCHEMA`
- `CANONICAL_CHECKED`, `CANONICAL_UNCHECKED`, `CHECKMARK_MARK_RE`, `FONT_GLYPH_MAPPINGS`, `FONT_BULLET_GLYPH_MAPPINGS`, `font_glyph_state()`, `font_bullet_glyph_state()`
- `DecisionAction`, `EvaluatorDecision`
- `COVER_LABELS`, `COVER_LABELS_FLAT`, `CHECKBOX_GRID_RE`, `COVER_EVIDENCE_TERMS`, `COVER_START_SHAPE_TERMS`, `is_state_value(value: str) -> bool`
- The seven rule tables in `rules.py`, plus `FILER_STATUS_TERMS` in `schemas.py`

No command surface.

## Tests

```text
tests/domain/forms/common/test_aliases.py
tests/domain/forms/common/test_checkmarks.py
tests/domain/forms/common/test_decisions.py
tests/domain/forms/common/test_models.py
tests/domain/forms/common/test_schemas.py
tests/domain/forms/common/test_vocabulary.py
```

## Deliberate gaps

- **`rules.py` has no mirrored test.** The other six modules do; this one does not, which
  `AGENTS.md` §6.3 requires. Its tables are read by `engine/forms/cover/` and asserted
  nowhere in `tests/domain/`.
- **`ANNUAL_CHECKBOX_SCHEMA` and `QUARTERLY_CHECKBOX_SCHEMA` are duplicated** in
  `domain/forms/families/{annual,quarterly}/checkmarks.py`. The copies compare equal today;
  no test pins them to each other, so a divergence would be silent. The families copies are
  the ones `engine/forms/cover/` imports.
- **The checkmark solver, penalty scoring, and token rewrite live in
  `engine/forms/cover/checkmarks/`.** This package owns only the static token vocabulary and
  schemas they match against.
- **`is_state_value()` derives its set from `domain/taxonomy/jurisdictions`** rather than
  restating it. An earlier revision kept a private list that silently omitted Guam, Puerto
  Rico, and the Virgin Islands; the derivation is why those are accepted today.