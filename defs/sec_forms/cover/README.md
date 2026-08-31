# `defs/sec_forms/cover/` — Canonical Cover Labels, Matchers, and Text-Based Extractors

Owns the canonical cover-page vocabulary (label aliases, compiled regex matchers, value patterns) and universal text-based cover extractors consumed by normalization, layout rendering, and future plain-text extraction.

---

## Layout

```text
defs/sec_forms/cover/
  __init__.py          # Public API exports
  vocabulary.py        # Canonical label aliases, compiled matchers, value patterns, phrase tuples
  extractors.py        # Universal text-based cover extractors
```

---

## `vocabulary.py` — Canonical Cover Vocabulary

### Label aliases

`COVER_LABELS: dict[str, tuple[str, ...]]` — canonical label tuples for:

- `state_of_incorporation` — "state or other jurisdiction of incorporation or organization", "jurisdiction of incorporation", "state of incorporation", "state of organization"
- `irs_ein` — "i.r.s. employer identification no.", "irs employer identification no.", "employer identification number", "employer identification no.", "taxpayer identification number", "i.r.s. no.", "irs no."
- `principal_address` — "address of principal executive offices", "principal executive offices"
- `zip_code` — "zip code", "postal code", "zip", "postal"
- `telephone` — "registrant's telephone number, including area code", "registrant telephone number, including area code", "telephone number, including area code", "telephone number"
- `registrant_name` — "exact name of registrant as specified in its charter", "name of registrant as specified in its charter", "exact name of registrant", "name of registrant"
- `commission_file_number` — "commission file number", "sec file number", "file number"
- `securities_12b` — "securities registered pursuant to section 12(b) of the act", "title of each class", "trading symbol(s)", "name of each exchange on which registered"

### Compiled label matchers

All built via `defs.regex.build_alternation(..., auto_escape=True)` from `COVER_LABELS`, wrapped to match optional parenthesized table-cell forms (`\(?...\)?`):

- `STATE_INCORPORATION_RE` — state of incorporation
- `IRS_EIN_RE` — IRS employer identification
- `ADDRESS_RE` — principal executive address
- `ZIP_RE` — ZIP/postal code
- `TELEPHONE_RE` — registrant telephone
- `REGISTRANT_NAME_RE` — registrant name as specified in charter
- `COMMISSION_FILE_RE` — SEC commission file number
- `SECURITIES_12B_RE` — securities registered under Section 12(b)

### Value patterns

- `EIN_VALUE_RE` — `\b\d{2}[\-\s]?\d{7}\b` (IRS employer identification number)
- `ZIP_VALUE_RE` — `(?<![\d\-])\d{5}(?:-\d{4})?(?!\d)` (US postal code)
- `COMMISSION_FILE_VALUE_RE` — `\b\d{1,3}[\-\s]\d{3,8}(?:[\-\s]\d{2,4})?\b` (SEC file number)

### Phrase tuples

- `PUBLIC_FLOAT_PHRASES` — aggregate-market-value phrases for public-float extraction
- `SHARES_PHRASES` — shares-outstanding phrases for shares extraction

### Helpers

- `is_state_value(value)` — returns whether a normalized cell contains a recognized state name or postal code

### Boundary phrases

`COVER_BOUNDARY_PHRASES` — phrases marking the end of the cover region ("documents incorporated by reference", "table of contents", "part i item 1").

---

## `profiles.py` — Form-Family Cover Profiles

Canonical cover profiles live here. They are immutable and selected by form
family; the preprocessor consumes a profile and never branches on form names.

- `CoverProfile` — frozen dataclass describing one profile:
  - `family` — canonical form family name
  - `eligible` — whether cover processing may run
  - `table_scope` — typed `defs.tables.templates.TableScope` for candidate tables
  - `labels` — label terms used to mark cover-candidate tables
  - `evidence_terms` — additional caption terms used for candidate detection
  - `boundary_phrases` — phrases delimiting the cover healing region
  - `phrase_rules` — phrase-healing rules enabled by this profile
- `COVER_PROFILES` — registry keyed by canonical family
- `get_profile(family)` — resolve a family to a profile, falling back to generic

### Capability groups

Profiles select compositional groups rather than re-declaring field lists:

- `COMMON_PHRASE_RULES` — banners, form titles, period/file/registrant, contact
  captions, and Section 12 securities captions (annual + quarterly)
- `ANNUAL_ADDITIONAL_PHRASE_RULES` — shares outstanding, public float,
  documents incorporated by reference, auditor, extended transition
- `COMMON_BOUNDARY_PHRASES` — "table of contents", "part i item 1"
- `ANNUAL_BOUNDARY_PHRASES` — common plus "documents incorporated by reference"
- `COMMON_COVER_LABELS` — all canonical label terms (annual + quarterly)

The annual-only anchors (`documents_incorporated_reference`, public float,
annual share-count wording, auditor disclosures) are enabled only by profiles
that support them. They must never apply to quarterly, current-report, or
no-cover profiles.

### Profile matrix

| Family | Eligible | Templates | Healing rules | Boundary |
|--------|----------|-----------|---------------|----------|
| `10-K` | yes | cover | common + annual | annual |
| `20-F` | yes | cover | common + annual | annual |
| `10-Q` | yes | cover | common | common |
| `8-K`  | no  | body | none | none |
| `6-K`  | no  | body | none | none |
| `GENERIC` | no | body | none | none |

The `20-F` profile extends the `10-K` profile with the same capabilities.
Foreign-issuer-specific captions are added only when sanitized fixture evidence
demonstrates them; they are not invented here.

---

## `extractors.py` — Universal Text-Based Extractors

All extractors operate on normalized plain text (post-hybrid-preprocessing), not on DOM nodes.

- `clean_company_name_string(raw)` — strips jurisdiction codes and trailing legal punctuation
- `get_core_name_tokens(name)` — lowercased core stem tokens stripping legal suffixes and stopwords
- `match_company_name(candidate, target, former_names)` — hierarchical 5-tier company name matcher (exact, core stem, substring/subset, Jaccard overlap) returning `(matched, tier, confidence)`
- `normalize_ein(candidate)` — strictly normalizes a candidate into a 9-digit IRS EIN (`XX-XXXXXXX`)
- `extract_candidate_ein(text, default_ein)` — finds and normalizes IRS EIN from text; tries bare value match first, then label-proximity search using `IRS_EIN_RE` and `EIN_VALUE_RE`
- `extract_fiscal_period(soup_or_text, filing_year, default_fy)` — extracts fiscal year or quarterly period end date; uses `parse_date` from `defs.text.dates` for full dates and `YEAR_IN_TEXT_RE` for standalone years
- `extract_commission_file_number(text_snippet, default_file)` — extracts SEC commission file number via `COMMISSION_FILE_RE` label + value proximity

---

## Contract

- All label matchers use `defs.regex.build_alternation` with `auto_escape=True`. No raw multi-branch regex alternations.
- No DOM traversal or BeautifulSoup usage. All extractors operate on strings.
- `vocabulary.py` is the single source of truth for cover label aliases and their compiled matchers. Table templates and other consumers import from here.
- `profiles.py` is the single source of truth for cover profiles and capability groups. The preprocessor consumes profiles; it does not branch on form names.
- Annual-only anchors are profile-gated. They are not applied globally.
- Profile construction touches `defs.tables` (typed scope) lazily, so importing `defs.sec_forms` does not trigger a circular import.

---

## Dependency Direction

- `vocabulary.py` is consumed by `defs/tables/templates/cover.py`, `defs/sec_forms/patterns.py`, `defs/sec_forms/sequences.py`, and future plain-text extraction.
- `extractors.py` consumes `vocabulary.py` and `defs.text.dates` (for `parse_date`, `YEAR_IN_TEXT_RE`).
- `profiles.py` consumes `vocabulary.py`, `defs.sec_forms.sequences`, and `defs.tables.templates.TableScope`.
- Neither `vocabulary.py` nor `extractors.py` imports from `defs/tables` or table-template code.
