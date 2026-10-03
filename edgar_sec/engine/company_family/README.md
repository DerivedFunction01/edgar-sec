# `edgar_sec/engine/company_family` — company-family normalization and clustering

Groups registrants that appear to represent the same economic entity, using company-name
normalization and deterministic family clustering.

## Purpose

The resulting `company_family` key lets downstream selection avoid over-representing one
registrant group. Construction is deterministic and in-memory; the seed/profile factories perform
the package's input I/O.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `normalizer.py` | Name normalization and structural-vocabulary helpers. |
| `clustering.py` | Family index construction, lookup, and identifier generation. |

## Contracts

- **Normalization and family assignment are deterministic.** Results do not depend on
  input ordering or process state.
- **The matching policy is conservative.** Shared generic words alone do not merge unrelated
  registrants; ambiguous names remain separate.
- **Resolution has a fallback for unknown registrants.** A name can still produce a family key
  when the CIK is absent from the built index.
- **The built index is immutable.** Later lookups cannot change its mappings or vocabulary.
- **Layer discipline.** The package depends on lower layers and does not import pipelines.

## Command surface

None. Library package, no CLI.

## Public surface

- `CompanyFamilyIndex`, `CompanyFamilyInfo`, and `family_id_for` — `clustering.py`.
- Name normalization, structural-vocabulary, and family-key helpers — `normalizer.py`.

## Mirrored tests

Mirrored coverage lives under `tests/engine/company_family/`.

## Deliberate gaps

- **No fuzzy matching or external entity graph.** A registrant with no recognizable name
  relationship to a parent remains a separate family.
- **No persisted family index.** The index is built from the current seed or profile input and
  discarded after use.
- **Family identifiers are part of published selection data.** Changing their derivation changes
  those identifiers and can invalidate comparisons across plans.
