# `edgar_sec/domain/forms/common/` — Form-Agnostic Contracts, Schemas, and Aliases

## Purpose

Shared domain contracts used across SEC form normalization and evaluation: the canonical
form-family alias mapping, checkmark token specifications, evaluator decision models, base
data models, cover phrase rules, declarative checkbox schemas, and cover label vocabularies.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `aliases.py` | Canonical form-family aliases, suffix collapse, and alias resolution |
| `checkmarks.py` | Checked/unchecked tokens, bracket pairs, glyph tables, and the mark pattern |
| `decisions.py` | Evaluator decisions and the actions they carry |
| `forward_looking.py` | Forward-looking-statement phrases, terms, and verbs, shared by periodic and event reports |
| `models.py` | Cover and body evidence packs, item definitions, stage records, transforms, the `Evaluator` protocol, and the lexical-pack derivation |
| `rules.py` | Cover `PhraseSequenceRule` tables and the `COMMON_PHRASE_RULES` roll-up |
| `schemas.py` | Statutory checkbox constraints, filer and report-period groups, and the per-family checkbox schemas |
| `vocabulary.py` | Cover-page labels, filer categories, cover and value patterns, and the state-value test |

## Contracts

- **`resolve_alias()` is the only entry point that resolves a raw form string to a
  family.** It maps every alias in `FORM_FAMILY_ALIASES` — including the historical
  spellings such as `10-K405`, `10-KSB`, `20FR12B`, and `8-K12B` — to one of
  `"10-K"`, `"10-Q"`, `"8-K"`, `"20-F"`, `"6-K"`, or `None`. `form_family()` only
  collapses amendment and submission suffixes and does *not* normalize those
  historical spellings: `form_family("10-K405")` returns `"10-K405"`. Resolve a
  family through `resolve_alias()`; use `form_family()` when you deliberately want
  the suffix-collapsed string.
- Suffix collapse removes each suffix at most once, in a fixed priority order, so
  `10-K/A` and `10-Q/A-POS` both land on their base family.
- Statutory cover requirements are declarative: the SEC's WKSI and shell exclusions,
  twelve-month compliance, SOX 404(b), EGC transition, error correction, and recovery
  analysis are `CheckboxConstraint` values in `STATUTORY_CHECKBOX_CONSTRAINTS`.
- Layer-1 purity: zero internal dependencies on `infra`, `engine`, `pipelines`, or
  `apps`.

## Public surface

- `resolve_alias()`, `form_family()`, `aliases_for_family()`, and the alias tables —
  `aliases.py`.
- `CoverEvidencePack`, `BodyEvidencePack`, `ItemDefinition`, `StageRecord`,
  `ContentTransform`, `Evaluator`, `derive_lexical_pack()` — `models.py`.
- `CheckboxConstraint`, `CoverCheckboxSchema`, `STATUTORY_CHECKBOX_CONSTRAINTS`, and
  the per-family checkbox schemas — `schemas.py`.
- Checked/unchecked tokens, bracket pairs, glyph tables, `CHECKMARK_MARK_RE`, and the
  glyph-state helpers — `checkmarks.py`.
- `DecisionAction`, `EvaluatorDecision` — `decisions.py`.
- `COVER_LABELS`, `COVER_LABELS_FLAT`, the cover and filer-category patterns, and
  `is_state_value()` — `vocabulary.py`.
- The cover phrase-sequence rule tables — `rules.py`.

No command surface.

## Tests

Tests mirror this package under `tests/domain/forms/common/`.

## Deliberate gaps

- **The alias vocabulary covers only the periodic and current report families**
  (`10-K`, `10-Q`, `8-K`, `20-F`, `6-K`). Registration, proxy, ownership, and
  beneficial-ownership forms (`S-1`, `DEF 14A`, `SC 13G`, …) have no alias entry, so
  `resolve_alias()` returns `None` for them and the caller must decide what family,
  if any, such a filing belongs to.
