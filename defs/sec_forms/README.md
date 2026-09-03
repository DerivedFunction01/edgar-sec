# `defs/sec_forms/` — Shared SEC Form Definitions, Semantic Concepts, and Cover-Page Contracts

Owns the canonical data models, universal vocabulary constants, compiled regex patterns, phrase-sequence rules, concept definitions, and form-family taxonomies shared across SEC cover-page extraction, normalization, and layout rendering.

---

## Layout & Ownership Architecture

```text
defs/sec_forms/
  __init__.py              # Root public exports (clean vocabulary, models, taxonomy, markers)
  vocabulary.py            # Universal vocabulary, shared cover labels, filer terms, and contact regexes
  models.py                # Frozen dataclasses for cover-page semantic models (CoverPageModel, etc.)
  page_markers/            # Coordinate-safe ASCII page-marker analysis package
    __init__.py             # Stable public API re-exports
    models.py               # Marker, candidate, run, evidence, and terminal-state models
    ascii.py                # ASCII/SGML orchestration and validated cleanup
    html.py                 # Visible DOM markers, PRE discrimination, and DOM cleanup
    candidates.py           # Firm patterns, contextual candidates, and promotion
    sequence.py             # Namespace-aware validation, healing, and inference
    headers.py              # Repeated header/footer evidence
    layout.py               # Alignment, spacing, and table-shape guards
  sequences.py             # Shared phrase-sequence healing rules for common cover captions
  concepts.py              # ConceptPattern for dual regex/BoW semantic matching
  families.py              # Canonical form-family alias registry and cover profile mapping
  forms/                   # Form-family specific taxonomies, evidence packs, and profiles
    __init__.py            # Form-family package entry point
    common.py              # Base evidence pack contracts (CoverEvidencePack, BodyEvidencePack)
    profiles.py            # Typed cover-profile composition (build_annual_profile, etc.)
    annual/                # Form 10-K & 20-F specific domain package
      __init__.py          # Annual API re-exports
      taxonomy.py          # Part (I-IV) and Item (1-16) taxonomy
      vocabulary.py        # Annual-only phrases and regexes (public float, shares, incorporated refs)
      sequences.py         # Annual-only phrase healing rules (float, shares, auditor, incorporated)
      evidence.py          # AnnualReportEvidence dataclass and semantic anchors
    quarterly/             # Form 10-Q specific domain package
      __init__.py          # Quarterly API re-exports
      taxonomy.py          # Part (I-II) and Item (1-4, Part II 1-6) taxonomy
      evidence.py          # QuarterlyReportEvidence dataclass and semantic anchors
    current_report/        # Form 8-K & 6-K specific domain package
      __init__.py          # Current-report API re-exports
      taxonomy.py          # Section 1-9 dotted Item taxonomy (1.01 through 9.01)
  cover/                   # Subpackage for cover boundary, extractors, and profiles (own README)
```

---

## Detailed Component Ownership

### 1. Universal / Shared Infrastructure

- **`vocabulary.py`** — Single canonical source for universal SEC terms and regex patterns:
  - `COVER_LABELS` / `COVER_LABELS_FLAT` — Universal cover caption dictionary and flattened list (state, EIN, address, zip, telephone, registrant name, commission file number, securities 12(b)).
  - `SEC_HEADER_TERMS`, `COVER_START_IDENTITY_TERMS`, `COVER_START_SHAPE_TERMS` — Universal header and cover start anchors.
  - `LARGE_ACCELERATED_FILER`, `ACCELERATED_FILER`, `NON_ACCELERATED_FILER`, `SMALLER_REPORTING_COMPANY`, `EMERGING_GROWTH_COMPANY`, `SHELL_COMPANY`, `WELL_KNOWN_SEASONED_ISSUER`, `VOLUNTARY_FILER` — Canonical category constants.
  - `FILER_CATEGORY_PATTERNS`, `CHECKBOX_KEYWORDS`, `CHECKBOX_GRID_RE` — Universal checkmark and status patterns.
  - `STATE_INCORPORATION_RE`, `IRS_EIN_RE`, `ADDRESS_RE`, `ZIP_RE`, `TELEPHONE_RE`, `REGISTRANT_NAME_RE`, `COMMISSION_FILE_RE`, `SECURITIES_12B_RE` — Universal field label patterns.
  - `ZIP_VALUE_RE`, `EIN_VALUE_RE`, `COMMISSION_FILE_VALUE_RE`, `is_state_value` — Value matching helpers.

- **`sequences.py`** — Universal phrase sequence healing rules (`COMMON_PHRASE_RULES` / `SEC_COVER_PHRASE_RULES`):
  - `BANNER_RULES` (SEC header), `FORM_TITLE_RULES` (form title captions), `PERIOD_FILE_REGISTRANT_RULES` (period ended, file number, registrant name), `CONTACT_CAPTION_RULES` (state, EIN, address, telephone), `REGISTRATION_RULES` (securities registered pursuant to section 12(b)).

- **`models.py`** — Shared immutable domain dataclasses:
  - `Security12b`, `RegistrantEntry`, `CheckboxDisclosures`, `CoverPageModel`.

- **`page_markers/`** — Universal page-marker analysis, classification, and stripping.
  - Firm SGML/footer forms remain compatible with the original public API.
  - Contextual ASCII candidates are promoted only through namespace-aware
    sequence, layout, TOC, prose, and financial/table exclusion evidence.
  - `PageMarkerAnalysis` retains source line ranges, accepted runs, unresolved
    candidates, inferred (metadata-only) boundaries, and terminal states.
  - `analyze_page_markers()`, `strip_page_markers()`, and `find_page_markers()`
    remain available from `defs.sec_forms.page_markers`.

- **`concepts.py`** — `ConceptPattern` dataclass for regex/BoW dual matching.

- **`families.py`** — Canonical form-family aliases and normalization (`form_family`, `resolve_alias`).

---

### 2. Form-Family Specific Packages (`forms/`)

- **`forms/annual/`** — Form 10-K and Form 20-F:
  - `taxonomy.py`: Defines `PARTS` (`PART I` through `PART IV`) and `ITEMS` (`ITEM 1` through `ITEM 16`).
  - `vocabulary.py`: Owns annual-exclusive terms and regexes:
    - Public float: `PUBLIC_FLOAT_PHRASES`, `PUBLIC_FLOAT_ANCHOR_RE`, `PUBLIC_FLOAT_VALUE_RE`, `PUBLIC_FLOAT_EXACT_RE`.
    - Shares outstanding: `SHARES_PHRASES`, `SHARES_ANCHOR_RE`, `SHARES_VALUE_RE`.
    - Documents incorporated by reference: `INCORPORATED_REFERENCE_TERMS`.
  - `sequences.py`: Owns annual-exclusive phrase healing rules:
    - `SHARES_RULES`, `PUBLIC_FLOAT_RULES`, `DOCUMENTS_INCORPORATED_RULES`, `AUDITOR_RULES`, `EXTENDED_TRANSITION_RULES`, `ANNUAL_ADDITIONAL_PHRASE_RULES`.
  - `evidence.py`: `AnnualReportEvidence` dataclass providing annual semantic headings, body n-grams, verbs, and healing rules.

- **`forms/quarterly/`** — Form 10-Q:
  - `taxonomy.py`: Defines `PARTS` (`PART I`, `PART II`) and `ITEMS` (`ITEM 1` to `ITEM 4`, `ITEM 1A`, `ITEM 5`, `ITEM 6`).
  - `evidence.py`: `QuarterlyReportEvidence` dataclass providing quarterly semantic headings and comparison verbs (`decreased`, `increased`, `compared`).

- **`forms/current_report/`** — Form 8-K and Form 6-K:
  - `taxonomy.py`: Defines event-driven `ITEMS` (Section 1 through Section 9 dotted items).

- **`forms/profiles.py`** & **`forms/common.py`**:
  - `CoverEvidencePack` and `BodyEvidencePack` base contracts.
  - `build_annual_profile()`, `build_quarterly_profile()`, `build_no_cover_profile()`.

---

## Dependency Invariants

1. **No Form Leakage**: Generic modules (`vocabulary.py`, `sequences.py`, `cover/rules.py`) never import from `forms/annual`, `forms/quarterly`, or `forms/current_report`.
2. **Strict Profile Composition**: Cover profiles compose universal vocabulary with form-family evidence packs explicitly.
3. **Zero Backward-Compatibility Shims**: Consumers import directly from canonical module locations without proxy aliases or re-export shims.
