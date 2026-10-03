# `edgar_sec/domain/taxonomy/` — Statutory name vocabulary

Shared vocabulary and normalizers for jurisdiction, legal-form, company-name, and filing
taxonomy data.

## Purpose

Provides the shared vocabulary consumed by domain and engine normalization. Financial
statement and table taxonomies are documented in their subpackage READMEs.

## Layout

| Subpackage / Module | Responsibility |
| :--- | :--- |
| `jurisdictions.py` | Jurisdiction vocabulary and suffix normalization |
| `legal_forms.py` | Legal-form vocabulary and name tokenization |
| `family_vocab.py` | Company-name abbreviation, plural, and structural vocabulary, plus the family-resolution seed and tuning constants |
| `components/cover.py` | Cover-page table specifications and terms |
| `statements/` | Financial statement vocabulary; see its README |
| `schedules/` | Footnote and statutory schedule vocabulary; see its README |
| `tables/` | Financial table specifications; see its README |

## Contracts

- Vocabulary tables are immutable shared inputs, so one caller cannot change what
  another sees.
- Jurisdiction cleanup strips a recognized slash-delimited suffix from an entity
  name; legal forms and company-name tokens are normalized against their own
  vocabularies.
- State codes and names have one canonical vocabulary here, shared with the cover
  vocabulary, so a second copy cannot drift.
- An ambiguous abbreviation expands only under the neighbor constraints declared
  for it. Extend abbreviation vocabulary through those constraints rather than
  adding a bare entry, which would corrupt unrelated names.
- Family resolution is deterministic: a fixed seed breaks ties when choosing a
  family representative, so the same registrants resolve to the same naming across
  runs and machines. Changing the seed changes which representative wins.

## Public surface

- `strip_jurisdiction()`, `clean_entity_name()`, the state code and name
  vocabulary, and the compiled jurisdiction pattern — `jurisdictions.py`.
- Legal-form vocabulary and `entity_name_tokens()` — `legal_forms.py`.
- Abbreviation, plural, and structural vocabulary, the family-resolution seed, and
  the resolution tuning constants — `family_vocab.py`.
- Cover-page table specifications and terms — `components/cover.py`.
- Statement, schedule, and table-family vocabulary — [statements](statements/README.md),
  [schedules](schedules/README.md), [tables](tables/README.md).

No command surface.

## Tests

Tests mirror this package under `tests/domain/taxonomy/`.

## Deliberate gaps

- **Jurisdiction cleanup is US-only.** The vocabulary covers US states and
  territories, and `legal_forms.py` recognizes foreign legal-form tokens such as
  `gmbh` or `plc`, but a foreign jurisdiction suffix is never stripped: a caller
  normalizing a non-US name gets the suffix back unchanged.
