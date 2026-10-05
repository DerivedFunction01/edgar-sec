# `edgar_sec/domain/forms/` — Cover and Form Domain Vocabulary, Contracts, and Evidence Packs

## Purpose

Every table, pattern, and data contract the SEC form normalization and evaluation engine
needs: canonical form aliases, label vocabularies, checkmark token boundaries, statutory
checkbox constraints, form-family evidence packs, and evaluator decision types. All of it
is data; none of it reads or fetches documents.

## Layout

| Subpackage | Responsibility |
| :--- | :--- |
| `common/` | Form-agnostic contracts: aliases, checkbox schemas, checkmark tokens, cover rules, label vocabulary, decision models |
| `families/` | Per-family evidence packs and Part/Item taxonomies (`annual/`, `quarterly/`, `current/`) |

Per-module detail is in [common/README.md](common/README.md) and
[families/README.md](families/README.md).

## Contracts

- **Declarative only.** The checkmark solver, the cover boundary detector, and
  evaluator execution are `engine/forms/`'s; this subtree owns the data they read.
- **Layer-1 purity:** zero internal dependencies on `infra`, `engine`, `pipelines`, or
  `apps`, and no third-party imports beyond `edgar_sec.foundation`.

## Public surface

- Canonical family resolution — `resolve_alias()`, `form_family()`,
  `aliases_for_family()` in `common/aliases.py`.
- Cover and body evidence packs, item definitions, and the lexical-pack derivation —
  `common/models.py`.
- Statutory checkbox constraints and the per-family checkbox schemas —
  `common/schemas.py`.
- Cover-page label and filer-category vocabulary — `common/vocabulary.py`.
- Checkmark token boundaries and glyph tables — `common/checkmarks.py`.
- Cover phrase-sequence rule tables — `common/rules.py`.
- Evaluator decisions and their actions — `common/decisions.py`.
- The per-family evidence records, body-lexical packs, and Part/Item taxonomies —
  `families/{annual,quarterly,current}/`.

No command surface.

## Tests

Tests mirror this package under `tests/domain/forms/`.

## Deliberate gaps

- **The checkbox schemas are declared twice.** `ANNUAL_CHECKBOX_SCHEMA` and
  `QUARTERLY_CHECKBOX_SCHEMA` are each built independently in `common/schemas.py` and
  in `families/{annual,quarterly}/checkmarks.py`. The two copies compare equal today,
  nothing pins them to each other, and the copies `engine/forms/cover/` imports are
  the family ones — so import the family module and keep the `common/` copies in step.
