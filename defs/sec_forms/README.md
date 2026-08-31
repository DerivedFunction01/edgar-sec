# `defs/sec_forms/` — Shared SEC Form Definitions, Semantic Concepts, and Cover-Page Contracts

Owns the canonical data models, regex patterns, phrase-sequence rules, concept definitions, and form taxonomies shared across SEC cover-page extraction, normalization, and layout rendering.

---

## Layout

```text
defs/sec_forms/
  __init__.py          # Public API exports
  models.py            # Frozen dataclasses for cover-page semantic models
  patterns.py          # Reusable regex patterns for filer categories, checkboxes, public float, shares
  sequences.py         # Phrase-sequence healing rules for SEC cover captions
  concepts.py          # ConceptPattern for dual regex/BoW semantic matching
  taxonomy.py          # Form 10-K, 10-Q, and 8-K item/part taxonomy constants
  families.py          # Canonical form-family alias registry and cover profile mapping
  cover/               # Subpackage for cover labels, matchers, extractors, and profiles (own README)
```

---

## Key Exports

- **`models.py`** — Frozen, slotted dataclasses:
  - `Security12b` — registered security under Section 12(b) (title, symbol, exchange, registrant)
  - `RegistrantEntry` — single legal entity in a multi-registrant filing (name, CIK, EIN, state, address, phone, target-entity flag)
  - `CheckboxDisclosures` — tri-state filer status and regulatory disclosure flags (WKSI, accelerated, smaller reporting, emerging growth, shell, voluntary, clawback, interactive data)
  - `CoverPageModel` — normalized semantic representation of a Form cover page (form, company, CIK, EIN, state, file number, fiscal year end, address, phone, co-registrants, securities, shares, public float, checkboxes, auditor, incorporated-documents note)

- **`patterns.py`** — Compiled regex and pattern tuples consumed by extraction algorithms:
  - `FILER_CATEGORY_PATTERNS` — filer-category regex tuples (large accelerated, accelerated, non-accelerated, smaller reporting, emerging growth)
  - `CHECKBOX_KEYWORDS` / `CHECKBOX_GRID_RE` — checkbox keyword alternation and compiled grid matcher
  - `PUBLIC_FLOAT_ANCHOR_RE`, `PUBLIC_FLOAT_VALUE_RE`, `PUBLIC_FLOAT_EXACT_RE` — public-float anchor and value matchers
  - `SHARES_ANCHOR_RE`, `SHARES_VALUE_RE` — shares-outstanding anchor and value matchers
  - `CURRENCY_SPACING_RE`, `PUNCT_SPACING_RE`, `IXBRL_FACT_RE` — text-cleanup and XBRL fact patterns
  - Consumes `PUBLIC_FLOAT_PHRASES` and `SHARES_PHRASES` from `defs.sec_forms.cover.vocabulary`

- **`sequences.py`** — `SEC_COVER_PHRASE_RULES`: ordered list of `PhraseSequenceRule` objects for healing fragmented cover captions (SEC banner, form titles, period/file-number/state/EIN/address/telephone captions, securities 12(b), shares outstanding, public float, incorporated documents, auditor, extended transition). Consumes phrase tuples from `defs.sec_forms.cover.vocabulary`.

- **`concepts.py`** — `ConceptPattern` frozen dataclass that compiles a phrase list into a single alternation regex via `defs.regex.build_alternation` and derives a Bag-of-Words token set (filtered through `defs.entities.NAME_STOPWORDS`) for dual regex-search and overlap scoring (`search`, `finditer`, `match_score`).

- **`taxonomy.py`** — Canonical form structure constants: `FORM_10K_ITEMS`, `FORM_10K_PARTS`, `FORM_10Q_ITEMS`, `FORM_10Q_PARTS`, `FORM_8K_ITEMS` mapping item numbers to statutory descriptions.

---

## Dependency Direction

- `patterns.py` and `sequences.py` consume `PUBLIC_FLOAT_PHRASES` and `SHARES_PHRASES` from `defs.sec_forms.cover.vocabulary`.
- `concepts.py` depends on `defs.regex.build_alternation` and `defs.entities.NAME_STOPWORDS`.
- `models.py`, `taxonomy.py` are self-contained with no internal or external dependencies beyond the standard library.
- The `cover/` subpackage has its own README and operates one level lower: it owns canonical cover labels, compiled label matchers, value patterns, and universal text-based extractors.
