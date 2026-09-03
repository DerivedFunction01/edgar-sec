# `defs/sec_forms/cover/` — SEC Cover Boundary Detection, Structural Parsing, and Form Profiles

Owns cover boundary policies, body root backward search, cover start clustering, table of contents detection, forward body-start detection, and universal text-based cover extractors consumed by normalization, layout rendering, and form processors.

---

## Layout

```text
defs/sec_forms/cover/
  __init__.py          # Public cover API surface
  boundary.py          # Cover boundary detection policies and coordinator
  closing.py           # Conservative closing-region detection (signatures, exhibit index)
  cover_start.py       # Cover start cluster detection and candidate search
  body_search.py       # Backward body root search and boundary confirmation
  body_start.py        # Forward body-start detection after cover/TOC
  body_context.py      # Unit indexing, eligibility context, lexical pack glue
  structure.py         # Structural line and Part/Item heading parsers
  toc.py               # Table of Contents detection and row classification
  extractors.py        # Universal text-based cover extractors (EIN, CIK, fiscal year)
  profiles.py          # Form-family cover profiles and boundary policies
  rules.py             # Compiled cover regexes and compiled lexical pack
  models.py            # Immutable data models (CoverBoundary, BodyStart, BodyRoot, ...)
  topology.py          # 4-zone document topology resolution
```

---

## Key Modules

- **`boundary.py`** — `find_cover_boundary()`, `find_cover_boundary_for_profile()`: multi-signal boundary detection across cover identity, incorporated references, TOC transitions, and Part/Item fallbacks.
- **`closing.py`** — `find_closing_span()`, `ClosingSpan`: exact standalone `SIGNATURES` headings, `By: /s/` signature lines, and `EXHIBIT INDEX` headings after a validated body anchor; dotted TOC rows are rejected, and an absent signal means "no closing region" rather than a guess.
- **`cover_start.py`** — `find_cover_start()`, `CoverStart`: anchors start of cover via SEC header, form titles, and registrant names.
- **`body_search.py`** — `_find_body_root_backward()`, `confirm_backward_body()`, `BodyRoot`: finds first structural body item after cover using the shared compiled lexical evaluator.
- **`body_start.py`** — `find_body_start()`, `BodyStart`: forward body-start detection after cover/TOC boundaries using structural, semantic, and substantive anchors with tiered lexical validation (score >= 2 accepted).
- **`body_context.py`** — `compile_body_lexical()`, `unit_context()`, `unit_in_toc()`: unit indexing, TOC/protected eligibility, and evidence-pack resolution shared by forward and backward body paths.
- **`toc.py`** — `find_toc_span()`, `is_toc_row()`: identifies and bounds embedded table of contents.
- **`extractors.py`** — `clean_company_name_string()`, `match_company_name()`, `normalize_ein()`, `extract_candidate_ein()`, `extract_fiscal_period()`, `extract_commission_file_number()`.
- **`profiles.py`** — `CoverProfile`, `COVER_PROFILES`, `get_profile()`: form-family profile selection (10-K, 20-F, 10-Q, 8-K, 6-K).
- **`topology.py`** — `resolve_document_topology()`: resolves the complete 4-zone partition (Cover, TOC, Body).

---

## Dependency Direction

- All cover modules consume canonical vocabulary and page marker primitives directly from `defs.sec_forms.vocabulary` and `defs.sec_forms.page_markers`.
- `extractors.py` consumes `defs.sec_forms.vocabulary` and `defs.text.dates`.
- `profiles.py` consumes `defs.sec_forms.vocabulary`, `defs.sec_forms.sequences`, and `defs.tables.templates.TableScope`.
- `body_start.py` and `body_search.py` consume the form-neutral `defs.text.bow` lexical evidence engine; form-specific vocabulary comes from the profile's `body_evidence` pack (`defs.sec_forms.forms.<form>/`). `body_context.py` adapts between boundary results and the generic engine; the scorer never reimplements cover or TOC detection.
