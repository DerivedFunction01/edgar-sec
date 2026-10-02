# `edgar_sec/domain/forms/` — Cover and Form Domain Vocabulary, Contracts, and Evidence Packs

## Purpose

Every table, pattern, and data contract the SEC form normalization and evaluation engine
needs: canonical form aliases, label vocabularies, checkmark token boundaries, statutory
checkbox constraints, form-family evidence packs, and evaluator decision types. All of it
is data; none of it reads or fetches documents.

## Layout

`edgar_sec/domain/forms/` contains no modules of its own — only two subpackages.

| Subpackage | Responsibility |
| :--- | :--- |
| `common/` | Form-agnostic contracts: aliases, checkbox schemas, checkmark tokens, cover rules, label vocabulary, decision models |
| `families/` | Per-family evidence packs and Part/Item taxonomies (`annual/`, `quarterly/`, `current_report/`) |

See `common/README.md` and `families/README.md`.

## Contracts

- **Zero namespace shadowing:** no loose file in `domain/forms/` collides with a subpackage
  name. `families` is strictly a package directory, and form aliases live at
  `domain/forms/common/aliases.py`.
- **Layer-1 purity:** zero internal dependencies on `infra`, `engine`, `pipelines`, or
  `apps`. The only external imports are `pyarrow` and `edgar_sec.foundation`.
- **Canonical alias resolution:** all 30 aliases in `FORM_FAMILY_ALIASES` resolve to
  `"10-K"`, `"10-Q"`, `"8-K"`, `"20-F"`, `"6-K"`, or `None`.
- **No barrel re-exports:** consumers import from leaf modules, e.g.
  `from edgar_sec.domain.forms.common.aliases import resolve_alias`.

## Public surface

- `common.aliases`: `FORM_FAMILY_ALIASES`, `FORM_FAMILY_SUFFIXES`, `resolve_alias`, `form_family`, `aliases_for_family`
- `common.schemas`: `CheckboxConstraint`, `CoverCheckboxSchema`, `STATUTORY_CHECKBOX_CONSTRAINTS`, `ANNUAL_CHECKBOX_SCHEMA`, `QUARTERLY_CHECKBOX_SCHEMA`
- `common.checkmarks`: `CANONICAL_CHECKED`, `CANONICAL_UNCHECKED`, `CHECKMARK_MARK_RE`, `FONT_GLYPH_MAPPINGS`, `font_glyph_state`
- `common.models`: `CoverEvidencePack`, `BodyEvidencePack`, `ItemDefinition`, `StageRecord`, `ContentTransform`, `Evaluator`, `derive_lexical_pack`
- `common.decisions`: `DecisionAction`, `EvaluatorDecision`
- `common.rules`: the seven `PhraseSequenceRule` tables (`BANNER_RULES`, `FORM_TITLE_RULES`, `PERIOD_FILE_REGISTRANT_RULES`, `JURISDICTION_RULES`, `ADDRESS_RULES`, `SECURITIES_EXCHANGE_RULES`, `COMMON_PHRASE_RULES`)
- `common.vocabulary`: `COVER_LABELS`, `COVER_LABELS_FLAT`, `CHECKBOX_GRID_RE`, filer category constants, `is_state_value`
- `families.annual`: `AnnualReportEvidence`, `FORM_10K_ITEMS`, `FORM_20F_ITEMS`, `FORM_10K_DERIVED`, `FORM_20F_DERIVED`, `ANNUAL_CHECKBOX_SCHEMA`, `ANNUAL_BODY_LEXICAL_PACK`
- `families.quarterly`: `QuarterlyReportEvidence`, `FORM_10Q_ITEMS`, `FORM_10Q_DERIVED`, `QUARTERLY_CHECKBOX_SCHEMA`, `QUARTERLY_BODY_LEXICAL_PACK`
- `families.current_report`: `CurrentReportEvidence`, `FORM_8K_ITEMS`, `FORM_8K_DERIVED`, `CURRENT_REPORT_BODY_LEXICAL_PACK`

No command surface.

## Tests

```text
tests/domain/forms/common/       6 mirrored test files
tests/domain/forms/families/     8 mirrored test files
```

## Deliberate gaps

- **`common/rules.py` has no mirrored test.** It is the only module in this subtree without
  one, which `AGENTS.md` §6.3 requires. Its seven rule tables are consumed by
  `engine/forms/cover/` rather than asserted here.
- **`ANNUAL_CHECKBOX_SCHEMA` and `QUARTERLY_CHECKBOX_SCHEMA` are declared twice** —
  in `common/schemas.py` and again in `families/{annual,quarterly}/checkmarks.py`. The two
  definitions compare equal today, but there is no test pinning them to each other.
- **Checkmark solving, boundary detection, and evaluator execution live in Layer 3.**
  They are consumed from `engine/forms/cover/checkmarks/`, `engine/forms/cover/boundary/`,
  and `engine/forms/plugins/evaluators/` respectively; this subtree owns only the
  declarative data they read.