# SEC Form Onboarding & Cover Profile Workflow Playbook

A normative, repeatable engineering guide for onboarding new SEC form families into `edgar_sec`, integrating statutory checkbox schemas, cover boundary detection, Item taxonomies, review analyzers, and verification pipelines.

---

## 1. Executive Summary: The Form S-1 Case Study

The onboarding of **Form S-1** established the architectural blueprint for Securities Act registration statements and general cover-page extraction across the repository. The process spanned five acyclic layers without introducing backward-compatibility shims or hardcoded form literals outside authorized paths.

### 1.1 Architectural Layer Progression

```text
Layer 1: Domain
├── taxonomy.py              (PART I Items 1-12A, PART II Items 13-17, early/late items)
├── checkmarks.py            (Securities Act Rules 415/462 + Filer Status + EGC)
├── evidence.py              (Shape terms, 8-tier LexicalEvidencePack, 2-3 word n-grams)
├── reports.py               (RegistrationReport dataclass)
├── profiles.py              (PRIMARY_PROFILE_S1)
├── processing.py           (PROFILE_S1, default render_to_txt operation)
├── common/aliases.py        (S-1, S-1/A, S-1MEF, S-1POS -> S-1)
└── families/processing_profiles.py (LAZY_INDEX_FORM_FAMILIES registration)

Layer 2: Policy Scanners
└── foundation/scanners/form_isolation.py (S-1 pattern + path allowance exceptions)

Layer 3: Engine
├── cover/profiles.py        (build_registration_profile, COVER_PROFILES["S-1"])
├── cover/checkmarks/solver.py (Group-based constraint satisfaction & known_state)
├── registration/analysis.py (Case diagnostics: boundary conf, checkmarks, Part I/II Items)
└── forms/analysis.py        (Generic multi-family review analyzer & summarizer)

Layer 4: Pipelines
├── document_acquisition/cli.py (review generate, review analyze)
└── review_artifacts/builder.py (Parallelized artifact generation)

Tests (Mirrored Tree)
├── tests/domain/forms/families/registration/ (test_taxonomy, test_checkmarks, test_evidence)
├── tests/engine/forms/registration/ (test_analysis)
└── tests/engine/forms/cover/test_profiles.py (test_s1_profile_contracts)
```

---

## 2. Form S-1 Artifact Blueprint Details

### 2.1 Checkbox Schema Architecture (`checkmarks.py`)

Form S-1 cover sheets combine offering-specific statutory rules under the Securities Act of 1933 with registrant-level Exchange Act classification checkboxes:

```python
# 1. Offering Binary Rules (Securities Act Rules 415 and 462)
RULE_415_LABEL = "delayed or continuous basis pursuant to rule 415"
RULE_462B_LABEL = "register additional securities for an offering pursuant to rule 462(b)"
RULE_462C_LABEL = "post-effective amendment filed pursuant to rule 462(c)"
RULE_462D_LABEL = "post-effective amendment filed pursuant to rule 462(d)"

# 2. Registrant Classification Group (Mutually Exclusive Filer Status)
FILER_STATUS_GROUP = "filer_status"
# Keys: large_accelerated_filer, accelerated_filer, non_accelerated_filer,
#       smaller_reporting_company, emerging_growth_company

# 3. Emerging Growth Company Extended Transition Opt-Out
EGC_OPT_OUT_LABEL = "elected not to use the extended transition period"
```

**Key Constraint Rules**:

- `filer_status` uses `ConstraintKind.MUTUALLY_EXCLUSIVE` across LAF, AF, and Non-AF.
- `statutory_binary` constraints evaluate independently per rule.
- Solver candidate resolution extracts `known_state` (`checked` vs `unchecked`) directly from ASCII brackets (`[X]`, `[ ]`), Unicode glyphs (`☑`, `☒`, `✓`), or HTML entity tags (`&#9746;`, `&#9745;`).

### 2.2 Eight-Tier Lexical Evidence Pack (`evidence.py`)

To distinguish cover-page facing sheets from substantive prospectus prose, `REGISTRATION_BODY_LEXICAL_PACK` mirrors the standard 8-tier hierarchy:

| Priority | Value | Tier Name            | Match Kind |    Hit Policy     |  Case Mode  | Target Vocabulary / Anchors                                                                                                                                                                                             |
| :------: | :---: | :------------------- | :--------: | :---------------: | :---------: | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
|  **30**  | **3** | `body_phrase`        |  `ngram`   |      $\ge 1$      |   `FOLD`    | Decisive 2–3 word n-grams: `"we have"`, `"we are"`, `"we will"`, `"our business"`, `"our common stock"`, `"use of proceeds"`, `"selling stockholders"`, `"balance sheets"`, `"cash flows"`, `"discussion and analysis"` |
|  **20**  | **2** | `body_strong`        | `unigram`  |      $\ge 2$      |   `FOLD`    | Unambiguous body tokens: `founded`, `organized`, `leading`, `underwriters`, `dilution`, `capitalization`, `subordinated`, `debentures`                                                                                  |
|  **20**  | **2** | `body_forward`       | `unigram`  |      $\ge 2$      | `LOWERCASE` | Safe harbor terms: `FORWARD_LOOKING_TERMS` (`CaseMode.LOWERCASE` prevents uppercase safe-harbor headings from scoring prematurely)                                                                                      |
|  **20**  | **2** | `body_header`        | `unigram`  |      $\ge 2$      |   `FOLD`    | Structural headers: `business`, `description`, `operations`, `prospectus`, `summary`, `offering`                                                                                                                        |
|  **20**  | **2** | `body_header_phrase` |  `ngram`   |      $\ge 1$      |   `FOLD`    | Common header phrases: `"our company"`, `"our business"`, `"the offering"`, `"table of contents"`                                                                                                                       |
|  **15**  | **1** | `body_phrase_soft`   |  `ngram`   | $\ge 1$ (Support) |   `FOLD`    | Cautionary phrases: `"safe harbor"`, `"cautionary statements"`, `"cautionary note"`, `"undue reliance"`, `"future performance"`                                                                                         |
|  **10**  | **1** | `body_general`       | `unigram`  |      $\ge 2$      |   `FOLD`    | General prose tokens: `continue`, `include`, `regarding`, `could`, `should`, `approximately`                                                                                                                            |
|  **10**  | **1** | `body_weak`          | `unigram`  |      $\ge 2$      |   `FOLD`    | Business verbs & terms: `provides`, `operates`, `manufactures`, `sells`, `develops`, `products`, `services`                                                                                                             |

> [!IMPORTANT]
> **Token Collision Invariant**: In `compile_evidence_pack()`, any token in a tier with `CaseMode.LOWERCASE` (e.g. words in `FORWARD_LOOKING_TERMS` like `forward`, `looking`, `results`, `risks`) must NOT appear as tokens in any tier configured with `CaseMode.FOLD`.

### 2.3 Boundary Detection & Backward Semantic Refinement

The boundary engine (`edgar_sec/engine/forms/cover/boundary/detector.py`) executes:

1. **First-Page & Identity Layout**: Signals facing sheet headers, SEC registration title, and SIC code blocks.
2. **TOC Transition**: Locates `TABLE OF CONTENTS` or preliminary prospectus headers.
3. **Backward Body Refinement**: Uses `REGISTRATION_BODY_LEXICAL_PACK` to detect the exact line where substantive narrative prose begins, adjusting or confirming the boundary (`confidence=0.9`).

---

## 3. Landscape Survey: Candidate Forms in `uploads/sec_forms/`

The `uploads/sec_forms/` catalog contains 20 statutory specifications. The table below classifies their eligibility for dedicated cover profiles, checkbox schemas, and item taxonomies:

| Form Specification   | Form Family            | Statutory Purpose                               | Cover Facing Sheet? | Checkbox Groups Present                                                                                  |       Item Taxonomy       | Recommended Implementation Strategy                                                                                  |
| :------------------- | :--------------------- | :---------------------------------------------- | :-----------------: | :------------------------------------------------------------------------------------------------------- | :-----------------------: | :------------------------------------------------------------------------------------------------------------------- |
| **`forms-1.md`**     | `registration`         | General registration (Securities Act 1933)      |       **Yes**       | Rules 415/462, Filer Status, EGC opt-out                                                                 |  Parts I & II (19 items)  | **Implemented** as inaugural registration profile                                                                    |
| **`forms-3.md`**     | `registration`         | Short-form seasoned issuer registration         |       **Yes**       | Dividend plans, Rule 415, Rules 462(b)/(c)/(e) WKSI auto-shelf, Rule 413(b), Filer Status, EGC           | Items 1–13 (Part I & II)  | **High Priority**: Direct plug-in to `registration/` family. Extends `S1_CHECKBOX_SCHEMA` with Rules 462(e) & 413(b) |
| **`forms-4.md`**     | `registration`         | Business combinations, mergers, exchange offers |       **Yes**       | Instruction G, Rules 462(b)/(d), Cross-border Rules 13e-4(i) & 14d-1(d), Filer Status, EGC               | Items 1–22 (Parts I & II) | **High Priority**: Direct plug-in to `registration/` family. Adds cross-border tender offer checkbox group           |
| **`forms-8.md`**     | `registration`         | Securities offered under employee benefit plans |       **Yes**       | Filer Status, EGC opt-out, Plan title/agent                                                              | Items 1–9 (Parts I & II)  | **Medium Priority**: Direct plug-in to `registration/`. Minimal facing sheet with employee benefit plan metadata     |
| **`def14a.md`**      | `proxy`                | Proxy Statement (Section 14(a) Exchange Act)    |       **Yes**       | Filing Classification (Prelim, Def, Additional, Rule 14a-12), Fee Payment (No fee, Fee paid, Item 25(b)) |        Items 1–25         | **High Priority**: New `proxy` form family. Dedicated cover sheet with distinct fee and filing party blocks          |
| **`form12b-25.md`**  | `late_notice`          | Inability to timely file periodic reports       |       **Yes**       | Filing Selections (10-K, 20-F, 11-K, 10-Q, 10-D, N-CEN, N-CSR), Relief Rules 12b-25(b)/(c)               |        Parts I–IV         | **High Priority**: New `late_notice` family. Highly structured checkmark-driven facing sheet                         |
| **`form15.md`**      | `termination`          | Termination of registration / suspension        |       **Yes**       | Certification Rules (Rule 12g-4, Rule 12h-3 checkboxes)                                                  |        Single page        | **Medium Priority**: Compact certification with binary rule-selection checkboxes                                     |
| **`schedule13d.md`** | `beneficial_ownership` | Active beneficial ownership acquisition (>5%)   |       **Yes**       | Cover sheet: Reporting person, CUSIP, citizenship, Box checks (Group, Funds, SEC use)                    |         Items 1–7         | **Medium Priority**: Distinct tabular cover sheet preceding narrative items                                          |
| **`schedule13g.md`** | `beneficial_ownership` | Passive beneficial ownership report (>5%)       |       **Yes**       | Cover sheet: CUSIP, citizenship, Item 3 institution classification checkboxes                            |        Items 1–10         | **Medium Priority**: Shares family with 13D; Item 3 institutional classification group                               |
| **`form144.md`**     | `sales`                | Proposed sale of restricted securities          |       **Yes**       | Table of proposed sales, SEC file number, approximate date                                               |       Single table        | Specialized tabular cover                                                                                            |
| **`form13f.md`**     | `holdings`             | Institutional manager holdings (> $100M)        |       **Yes**       | Report Type (13F Holdings, 13F Notice, 13F Combination), Manager List                                    |     Information Table     | XML/Text hybrid holding reports                                                                                      |
| **`formd.md`**       | `exempt`               | Reg D notice of exempt offering                 |       **Yes**       | Federal Exemptions (Rule 504, 506(b), 506(c)), Offering Type                                             |        Items 1–16         | XML-dominant filing format                                                                                           |

---

## 4. The Standard Repeatable Workflow Blueprint

When onboarding any new SEC form, execute the following 8-stage sequence:

### Stage 1: Statutory Source Mining (`uploads/sec_forms/<form>.md`)

1. Read the statutory specification in `uploads/sec_forms/`.
2. Extract the **Facing Sheet Shape**: Exact titles, CIK/IRS layout, registrant address, agent for service, fee tables.
3. Extract all **Checkbox Declarations**: Identify mutual exclusivity (e.g. filer status) vs independent binary flags (e.g. Rule 415, Rule 462).
4. Extract the **Item Taxonomy**: Note Part divisions, item numbers, titles, and whether items appear early (prospectus/facing) or late (exhibits/signatures).
5. Identify the **Primary Route**: HTML/text vs XML vs Tabular.

### Stage 2: Layer 1 Domain Package Modeling

Create or extend `edgar_sec/domain/forms/families/<family>/`:

1. **`__init__.py`**: Docstring cap $\le 4$ lines. No barrel re-exports.
2. **`README.md`**: Standard sections: `# <family>`, `## Purpose`, `## Contracts`, `## Deliberate gaps`.
3. **`taxonomy.py`**:
   - Define `ItemDefinition(item, part, names=(...), early=bool, optional=bool)`.
   - Compile derived lookups via `build_taxonomy_derived(FORM_ITEMS, PARTS)`.
4. **`checkmarks.py`**:
   - Define checkbox group names and `CheckboxConstraint` instances.
   - Build `CoverCheckboxSchema(family, groups, constraints)`.
5. **`evidence.py`**:
   - Define shape terms, 2–3 word body n-grams (`_BODY_PHRASES`), strong unigrams, verbs, header phrases, soft phrases.
   - Assemble 8-tier `LexicalEvidencePack`.
   - Define cover exclusion terms (`_COVER_EXCLUSION_TERMS`).
   - Define `<Family>Evidence` dataclass.
6. **`reports.py`**: Dataclass inheriting from `CompanyReport` or `FormReport`.
7. **`profiles.py`**: Define `PRIMARY_PROFILE_<FORM>` (`PrimaryReportProfile`).
8. **`processing.py`**: Define `PROFILE_<FORM>` (`DocumentProcessingProfile`).
9. **Register in Common Modules**:
   - `edgar_sec/domain/forms/common/aliases.py`: Map form variants (e.g. `"S-3"`, `"S-3/A"` -> `"S-3"`).
   - `edgar_sec/domain/forms/families/processing_profiles.py`: Add to `FORM_FAMILY_CATALOG` and `LAZY_INDEX_FORM_FAMILIES`.

### Stage 3: Layer 2 Policy Scanner Updates

Update `edgar_sec/foundation/scanners/form_isolation.py`:

1. Add form pattern regex to `_FORM_PATTERNS` (e.g. `r"S-?3(?:/[Aa])?"`).
2. Add authorized domain and engine package paths to `_ALLOWED_PATHS`:
   - `"edgar_sec/domain/forms/families/<family>/"`
   - `"edgar_sec/engine/forms/<family>/"`
3. Run `python check.py --scan` to verify zero policy violations.

### Stage 4: Layer 3 Engine Cover & Review Integration

1. **`edgar_sec/engine/forms/cover/profiles.py`**:
   - Implement `build_<form>_profile(family: str) -> CoverProfile`.
   - Wire `signals`, `derived_taxonomy`, `checkbox_schema`, and `RegistrationEvidence` (or family evidence).
   - Register in `COVER_PROFILES` dictionary.
2. **`edgar_sec/engine/forms/analysis.py`** (or family `analysis.py`):
   - Provide `analyze_case(case_dir, record)` and `summarize_cases(case_reports)`.
   - Surface boundary metrics, checkmark distributions, taxonomy item matches, and anomaly records.

### Stage 5: Mirrored Unit Testing

Create test packages mirroring source paths package-for-package:

1. `tests/domain/forms/families/<family>/test_taxonomy.py`
2. `tests/domain/forms/families/<family>/test_checkmarks.py`
3. `tests/domain/forms/families/<family>/test_evidence.py`
4. `tests/engine/forms/<family>/test_analysis.py`
5. Update `tests/engine/forms/cover/test_profiles.py`.

### Stage 6: Quality Gate Verification

Execute targeted tests and policy scans:

```bash
# Run only targeted tests for the new form
.venv/bin/python check.py --test tests/domain/forms/families/<family>/ tests/engine/forms/<family>/

# Verify all 16 policy scanners
.venv/bin/python check.py --scan
```

### Stage 7: Empirical Fixture Review & Calibration

1. **Populate Fixture**:
   ```bash
   .venv/bin/python -m edgar_sec.pipelines.document_acquisition.cli fixture fill --fixture fix-<plan_id>-v3
   ```
2. **Generate Review Artifacts**:
   ```bash
   .venv/bin/python -m edgar_sec.pipelines.document_acquisition.cli review generate --fixture fix-<plan_id>-v3
   ```
3. **Analyze Review Run**:
   ```bash
   .venv/bin/python -m edgar_sec.pipelines.document_acquisition.cli review analyze --run <run_id_or_path>
   ```

### Stage 8: Post-Cover N-Gram Mining & Refinement

1. Inspect generated rendered text files in `review-runs/<run_id>/cases/<case_id>/operations/render_to_txt.txt`.
2. Check for rendering anomalies: table misalignment, page-sentinel leaks, unparsed ASCII markup.
3. Mine emergent 2–3 word n-grams immediately following `boundary.end_line`.
4. Incorporate frequent unmodelled phrases into `_BODY_PHRASES` to continually elevate boundary precision.

---

## 5. Master File Reference & Command Cheat Sheet

### 5.1 Repository File Map

| Purpose                    | Relevant File Path (Relative)                                          |
| :------------------------- | :--------------------------------------------------------------------- |
| **Statutory Form Specs**   | `uploads/sec_forms/*.md`                                               |
| **Exhibit Specifications** | `uploads/exhibits.md`                                                  |
| **Formatting Guidelines**  | `uploads/FORMATTING_GUIDELINES.md`                                     |
| **Form Family Domain**     | `edgar_sec/domain/forms/families/<family>/`                            |
| **Form Aliases**           | `edgar_sec/domain/forms/common/aliases.py`                             |
| **Processing Catalog**     | `edgar_sec/domain/forms/families/processing_profiles.py`               |
| **Policy Scanners**        | `edgar_sec/foundation/scanners/form_isolation.py`                      |
| **Cover Profiles**         | `edgar_sec/engine/forms/cover/profiles.py`                             |
| **Checkmark Solver**       | `edgar_sec/engine/forms/cover/checkmarks/solver.py`                    |
| **Review Analyzer**        | `edgar_sec/engine/forms/analysis.py`                                   |
| **Document Normalizer**    | `edgar_sec/engine/forms/normalize.py`                                  |
| **Acquisition CLI**        | `edgar_sec/pipelines/document_acquisition/cli.py`                      |
| **Review Builder**         | `edgar_sec/pipelines/document_acquisition/review_artifacts/builder.py` |
| **Targeted Unit Tests**    | `tests/domain/forms/families/<family>/`                                |

### 5.2 Canonical Execution Commands

```bash
# 1. Verification & Quality Gates (Never run bare check.py without explicit targets)
.venv/bin/python check.py --fast                             # format, lint & scanners
.venv/bin/python check.py --scan                             # policy scanners only
.venv/bin/python check.py --test <test_path>                 # targeted pytest

# 2. Review Run Generation & Offline Analysis
.venv/bin/python -m edgar_sec.pipelines.document_acquisition.cli review generate --fixture <fixture_id>
.venv/bin/python -m edgar_sec.pipelines.document_acquisition.cli review analyze --run <run_id>
.venv/bin/python -m edgar_sec.pipelines.document_acquisition.cli review analyze --run <run_id> --json

# 3. Interactive Launcher Console
.venv/bin/python run.py                                      # Menu item 6: Document Acquisition
```
