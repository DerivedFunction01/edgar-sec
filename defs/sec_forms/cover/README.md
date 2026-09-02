# `defs/sec_forms/cover/` — SEC Cover Boundary Detection, Structural Parsing, and Form Profiles

Owns cover boundary policies, body root backward search, cover start clustering, table of contents detection, and universal text-based cover extractors consumed by normalization, layout rendering, and form processors.

---

## Layout

```text
defs/sec_forms/cover/
  __init__.py          # Public cover API surface
  boundary.py          # Cover boundary detection policies and coordinator
  cover_start.py       # Cover start cluster detection and candidate search
  body_search.py       # Backward body root search and boundary confirmation
  structure.py         # Structural line and Part/Item heading parsers
  toc.py               # Table of Contents detection and row classification
  extractors.py        # Universal text-based cover extractors (EIN, CIK, fiscal year)
  profiles.py          # Form-family cover profiles and boundary policies
  rules.py             # Compiled cover and body evidence regex rules
```

---

## Key Modules

- **`boundary.py`** — `find_cover_boundary()`, `find_cover_boundary_for_profile()`: multi-signal boundary detection across cover identity, incorporated references, TOC transitions, and Part/Item fallbacks.
- **`cover_start.py`** — `find_cover_start()`, `CoverStart`: anchors start of cover via SEC header, form titles, and registrant names.
- **`body_search.py`** — `_find_body_root_backward()`, `confirm_backward_body()`, `BodyRoot`: finds first structural body item after cover.
- **`toc.py`** — `find_toc_span()`, `is_toc_row()`: identifies and bounds embedded table of contents.
- **`extractors.py`** — `clean_company_name_string()`, `match_company_name()`, `normalize_ein()`, `extract_candidate_ein()`, `extract_fiscal_period()`, `extract_commission_file_number()`.
- **`profiles.py`** — `CoverProfile`, `COVER_PROFILES`, `get_profile()`: form-family profile selection (10-K, 20-F, 10-Q, 8-K, 6-K).

---

## Dependency Direction

- All cover modules consume canonical vocabulary and page marker primitives directly from `defs.sec_forms.vocabulary` and `defs.sec_forms.page_markers`.
- `extractors.py` consumes `defs.sec_forms.vocabulary` and `defs.text.dates`.
- `profiles.py` consumes `defs.sec_forms.vocabulary`, `defs.sec_forms.sequences`, and `defs.tables.templates.TableScope`.
