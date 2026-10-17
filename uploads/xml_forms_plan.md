# XML-Based SEC Forms Architecture, Playbook & Skill Guide

Normative engineering guide and skill specification for implementing, normalizing, and verifying XML-based SEC form pipelines across the repository. This document synthesizes the lessons learned, architectural patterns, and strict constraints established across tabular HTML-to-XML conversion and modern native XML normalization pipelines.

---

## 1. Executive Summary & Problem Framing

Modern EDGAR filings increasingly mandate structured, machine-readable XML schemas, while historical archives (and occasional filer errors) contain unstructured or tabular HTML/ASCII presentations.

To handle both modern native XML and historical tabular HTML within a unified data model, the repository establishes an **acyclic, modular processing pipeline**:

1. **Acquisition & Normalization**: Accepts raw document bytes, detects native XML envelopes vs tabular HTML, parses HTML table grids into structured domain models, and synthesizes canonical SEC XML conforming to official schemas.
2. **Review & Semantic Analysis**: Evaluates extraction accuracy at scale across historical accessions, scoring field completeness, detecting unparsed tables, flagging boilerplate leaks, and verifying schema conformance without network egress.

---

## 2. Landscape Audit: Forms Requiring XML Pipelines

Of the form specifications across repository manifests, forms requiring structured XML acquisition and rendering pipelines follow a common transition pattern:

| Form Family                    | Description                      | Modern SEC XML Schema                      | Historical Format               | Required Pipeline Operation          | Status          |
| ------------------------------ | -------------------------------- | ------------------------------------------ | ------------------------------- | ------------------------------------ | --------------- |
| **Section 16 (Forms 3, 4, 5)** | Beneficial Ownership Disclosures | `<ownershipDocument>`                      | Tabular HTML / ASCII tables     | `AcquisitionOperation.RENDER_TO_XML` | Implemented (AASM) |
| **Form 144**                   | Proposed Sale of Securities      | `<noticeOfProposedSaleOfSecurities>`       | Multi-tier HTML / ASCII tables  | `AcquisitionOperation.RENDER_TO_XML` | Implemented (AASM) |
| **Form D**                     | Notice of Exempt Offering        | `<edgarSubmission>` / `<offeringData>`     | 16-item Tabular HTML notice     | `AcquisitionOperation.RENDER_TO_XML` | Planned         |
| **Form 13F**                   | Institutional Holdings           | `<edgarSubmission>` / `<informationTable>` | Fixed-width ASCII / HTML tables | `AcquisitionOperation.RENDER_TO_XML` | Planned         |
| **Schedule 13D/G**             | 5%+ Beneficial Ownership         | `<schedule13D>` / `<schedule13G>`          | Narrative HTML + Cover Matrix   | Hybrid (Matrix XML + Narrative TXT)  | Planned         |
| **EX-107**                     | Filing Fee Tables                | `<fee_tables>` / Rule 107 XML              | Unstructured HTML fee tables    | `AcquisitionOperation.RENDER_TO_XML` | Planned         |

---

## 3. Normative Rules & Architectural Constraints

When creating or modifying an XML-based form pipeline, the following constraints are strictly binding and enforced by CI/AST policy scanners:

### Rule 1: No Inline `re.search` with Ad-Hoc Regex Literals

- **Prohibition**: Never write ad-hoc inline regex patterns like `re.search(r"...", text)` inside loops, table cell iterators, or parsing functions.
- **Enforcement**: All regexes must be compiled module constants (`_XYZ_RE = re.compile(...)`) declared in the owning `patterns.py` or imported from shared common modules (`edgar_sec.engine.forms.common.*`).

### Rule 2: Multi-Branch Alternation DSL (`regex-alternations`)

- **Prohibition**: Never hand-write 3+ branch alternation strings like `(?:TYPE_A|TYPE_B|TYPE_C)`.
- **Enforcement**: Must use `build_alternation(...)` from `edgar_sec.foundation.regex.builder`. This guarantees longest-first branch sorting and prevents catastrophic backtracking or accidental group capturing hazards.

### Rule 3: Zero Hardcoded Numerics in Evidence Packs

- **Prohibition**: Never hardcode ephemeral or specific numeric identifiers (e.g. OMB control numbers like `3235-0101` or specific form sequence numbers) in lexical evidence packs.
- **Enforcement**: Keep lexical packs vocabulary-driven (e.g. `"omb approval"`, `"omb control number"`, `"notice of proposed sale"`). Match numeric patterns via general regex tokens (e.g. `\d{4}-\d{4}`).

### Rule 4: Zero Fallback Leaks Across Forms

- **Prohibition**: Never fall back to another form's renderer (e.g. `else: render_other_form_to_xml(...)`).
- **Enforcement**: All form renderers must be explicitly registered with `DEFAULT_HANDLER_REGISTRY` in `edgar_sec/engine/document_processing/registry.py`. When a form or family does not have a registered renderer for `render_to_xml`, it must immediately raise:

```python
raise UnsupportedRenderOperation(f"Form {form!r} has no registered XML renderer")

```

### Rule 5: Zero Backward-Compatibility Shims & No Barrel Re-exports

- **Prohibition**: Never create legacy alias shims, forwarding functions, or barrel re-exports in `__init__.py`.
- **AST Scanner Keyword Trap**: Avoid docstrings or comments containing phrases like `"legacy HTML"`, `"compat shim"`, or `"deprecated"`, which trigger the `legacy-shims` AST policy scanner. Use neutral terms like `"tabular HTML"` or `"historical filings"`.
- **Leaf Imports**: Consumers must always import directly from leaf modules (e.g. `from edgar_sec.domain.forms.families.<form_family>.models import FormDocument`).

### Rule 6: SEC Target URL Resolution Trap (`xsl*` Stylesheets)

- **Problem**: The SEC serves XHTML stylesheet transforms for modern electronic filings (e.g. `/xsl<form_family>_X01/primary_doc.xml`). If requested with the `xsl*` path, EDGAR returns rendered HTML instead of pure submission XML.
- **Enforcement**: Target planning pipelines must strip `/xsl*` prefixes from document URLs when acquiring primary XML fixtures to retrieve pure `<edgarSubmission>` bytes.

### Rule 7: Prose Length Caps & Docstring Budgeting

- **Module docstrings**: Maximum 4 lines.
- **Function and class docstrings**: Maximum 3 lines.
- **Test module docstrings**: Maximum 3 lines.
- **Test function docstrings**: Maximum 2 lines.
- **Document intent, not execution**: Enforced by the `prose-length` policy scanner.

### Rule 8: Ground XML Output Against Mined Canonical Raw XML (Schema & N-Gram Mining)

- **Mandatory Discovery Script**: Never implement `render_to_xml.py` by guessing tag names or relying solely on narrative filing guidelines. Always write a temporary Python script (`scratch/mine_<form>_xml_structure.py`) to parse all canonical `raw.xml` cases in the fixture corpus using `xml.etree.ElementTree`.
- **Mine Hierarchy & Namespaces**: Extract complete tag paths (e.g. `/edgarSubmission/formData/.../address/com:street1`), exact namespace prefixes (`xmlns:com="[http://www.sec.gov/edgar/common](http://www.sec.gov/edgar/common)"`), and parent-to-child relationships. Verify exact schema tags (e.g. field casing, schema abbreviations, nested grouping tags).
- **Mine N-Grams & Field Values**: Sample text values and n-grams across tags to identify exact format requirements (e.g. date formats `MM/DD/YYYY` vs `YYYY-MM-DD`, decimal vs integer precision, Yes/No flag values `'Y'/'N'` vs `true/false`).
- **Sniff Out Anomalies & Sample Files**: The script must tally tag frequencies, identify optional vs mandatory elements, highlight rare edge cases, and print representative sample accession files to inspect directly.

### Rule 9: Diagnostic `unparsedSections` XML Contract

- **Envelope Embedding**: Every HTML-to-XML renderer (`render_to_xml.py`) MUST embed unparsed tables into the generated XML envelope under `<unparsedSections><unparsedSection tableIndex="..." role="...">...</unparsedSection></unparsedSections>` using `strip_decorative_presentation_attributes`.
- **Anomaly Sniffing**: `analysis.py` MUST match `unparsedSection` by namespace-independent local name, filter recognized boilerplate, compute `substantive_unparsed_count`, and collect representative `unparsed_samples`.

### Rule 10: Evidence-Based Classification and Preservation

- **Data Beats Boilerplate**: An instruction phrase does not make a populated table an instruction table. Require positive evidence before discarding it as boilerplate.
- **Contextual Continuations**: Merge sibling fragments only when their section context and row/column evidence match; otherwise retain them in `unparsedSections`.
- **No Field-Presence Suppression**: Do not discard distinct source values just because a destination field is already populated. Suppress only verified duplicates or explicit no-report markers after representing their meaning.

### Rule 11: Form-Schema Anchor Alignment State Machine (AASM) Over Fixed Coordinates

- **Prohibition**: Never attempt to construct brittle fixed column-index mappings (`mapping["code"] = 3`) by guessing column positions from multi-row headers across unaligned ASCII or tabular HTML grids.
- **Enforcement**: Model tabular data using `TableSchema` with typed `CanonicalColumn` definitions from `edgar_sec.engine.forms.common.alignment`. Process rows through the Anchor Alignment State Machine:
  1. **Strict Anchor Identification**: Detect high-confidence invariant tokens (ISO/US dates, transaction codes, currency-prefixed values, ownership codes `'D'/'I'`, and market exchange acronyms) in $O(N \cdot M)$ time.
  2. **Deficit Deduction**: When cell count is less than column count ($L_{\text{cells}} < L_{\text{cols}}$), deduce missing optional columns as `None` without shifting adjacent required columns.
  3. **Interval Projection**: Match unanchored cells strictly within the candidate columns bounded by adjacent anchors.

### Rule 12: Table Boundary Termination Over Post-Hoc Cell Filtering

- **Prohibition**: Never let trailing signature blocks, notary jurats, or footnote explanation sections enter data row iteration to be filtered cell-by-cell with localized string checks.
- **Enforcement**: Terminate table row collection immediately upon encountering structural boundary markers (`/s/`, `** signature`, `Explanation of Responses`). This prevents non-tabular text from ever reaching title or description fields.

### Rule 13: Centralized Statutory Vocabulary Over Localized Phrase Duplication

- **Prohibition**: Never maintain private, ad-hoc lists of legal boilerplate or artifact phrases inside individual form parsers.
- **Enforcement**: Always import and reuse repository-level statutory evidence packs and precompiled alternations (`STATUTORY_PAGE_BOILERPLATE`, `STATUTORY_CRIMINAL_WARNING_PHRASES`, `is_instruction_row`, `HEADER_LEAK_RE`) from `domain.forms.common.statutory` and `engine.forms.common.*`.

---

## 4. The Canonical Modular Architecture (The Standard Form Pattern)

Every XML-based form pipeline is structured into standard, isolated modules across Layer 1 (Domain) and Layer 3 (Engine):

```text
edgar_sec/
├── domain/forms/families/<form_family>/
│   ├── __init__.py           # Package docstring only; zero barrel re-exports
│   ├── models.py             # Frozen dataclasses with __slots__ (Entities, Signatures, Tables)
│   ├── evidence.py           # Positive lexical packs, continuation markers, veto phrases
│   ├── processing.py         # FormProcessingProfile with review_analyzer pointer
│   ├── reports.py            # Typed report summary dataclasses
│   └── README.md             # Standardized contracts, invariants, and deliberate gaps
│
├── engine/forms/<form_family>/
│   ├── __init__.py           # Package docstring only
│   ├── patterns.py           # Precompiled module-level regexes via build_alternation
│   ├── sections.py           # HTML table classification and SectionRole partitioning
│   ├── metadata_parser.py    # Non-tabular/header metadata & signature extraction via lookahead
│   ├── securities.py         # Tabular transaction/holdings parsing via Anchor Alignment State Machine
│   ├── render_to_xml.py      # Canonical XML synthesis and native XML pass-through
│   ├── analysis.py           # Field completeness, scorecards, and anomaly detection
│   └── README.md             # Architectural contracts and layout
│
└── tests/
    ├── domain/forms/families/<form_family>/
    │   ├── test_models.py
    │   ├── test_evidence.py
    │   └── test_processing.py
    └── engine/forms/<form_family>/
        ├── test_patterns.py
        ├── test_sections.py
        ├── test_metadata_parser.py
        ├── test_securities.py
        ├── test_render_to_xml.py
        └── test_analysis.py

```

### Module Roles and Contracts

1. **`patterns.py`**:

- Owns all compiled regular expression patterns (`_IDENTIFIER_RE`, `_STATUTORY_LABEL_RE`, `_MARKER_RE`, etc.).
- Builds multi-branch alternations using `build_alternation(..., auto_escape=True)`.
- Never imports from upper layers (`pipelines`, `apps`, `tools`).

2. **`sections.py`**:

- Uses `parse_html` to classify table elements and resolves grids only for data-bearing roles.
- Assigns evidence-based `SectionRole` values (e.g. `COMBINED_HEADER`, `FILER_METADATA`, `TRANSACTION_GRID_PRIMARY`, `TRANSACTION_GRID_SECONDARY`, `SIGNATURES`, `REMARKS`, `INSTRUCTIONS`, `PAGE_ARTIFACT`, `UNPARSED`).
- Merges source-backed header and grid continuations while retaining unrecognized content in diagnostics.

3. **`metadata_parser.py`**:

- Extracts metadata from non-tabular cover boxes (entity identity, CIK, SEC file number, tax IDs, addresses, execution dates, signatories).
- Handles wrapped labels, values in adjacent or following cells, inline address columns, and marker columns without treating header markers as values.

4. **`securities.py`**:

- Strictly handles repetitive tabular data rows (e.g. primary transactions, secondary historical transactions, derivative holdings, security distribution schedules).
- Uses `TableSchema` and `align_row_to_schema` from `edgar_sec.engine.forms.common.alignment` with strict anchors, deficit deduction for missing optional columns, and interval projection. Terminates cleanly before signature or footnote blocks.

5. **`render_to_xml.py`**:

- Top-level dispatcher for `render_to_xml`.
- Checks if input bytes are already native XML (`_XML_DECL_RE` or root envelope patterns); passes them through intact if valid XML.
- For tabular HTML, invokes `partition_<family>_tables`, parses metadata and tables, and builds canonical `<edgarSubmission>` XML conforming to the official SEC XML schema.

6. **`analysis.py`**:

- Implements `analyze_case(case_dir: Path) -> FormCaseReport` and `summarize_cases(case_reports: list[FormCaseReport]) -> FormSummaryReport`.
- Measures field presence, detects namespace-qualified unparsed sections, flags boilerplate leakage, and highlights review signals (e.g. specialized plan adoption dates, exemption claims).

---

## 5. End-to-End Implementation Playbook (7-Step Sequence)

Follow this systematic step-by-step sequence when adding any new XML form:

### Step 1: Mine Raw XML Schemas, Attributes & N-Grams (Ground Truth Discovery)

1. Write a temporary Python script (`scratch/mine_<form_family>_xml_structure.py`) to parse all canonical `raw.xml` files in the fixture corpus using `xml.etree.ElementTree`.
2. Map the exact tag tree paths, namespaces (`xmlns:com`), element attributes, and parent-to-child relationships.
3. Extract n-grams, text patterns, and sample values across tags to confirm required formats (e.g. date formats, integer quantities, flag encodings).
4. Run anomaly and frequency checks to identify optional versus required elements and sample anomalous files to inspect.

### Step 2: Define Domain Models & Evidence (Layer 1)

1. Create `edgar_sec/domain/forms/families/<form_family>/models.py` with immutable, slotted dataclasses representing all sections and sub-items.
2. Create `evidence.py` with compiled lexical evidence packs (`EvidenceTier.PRIMARY`, `SECONDARY`, `VETO`).
3. Create `processing.py` defining `PROFILE_FORM_<FORM_FAMILY>` with `AcquisitionOperation.RENDER_TO_XML` and pointing `review_analyzer` to `edgar_sec.engine.forms.<form_family>.analysis`.
4. Create `reports.py` defining case and summary analysis report models.
5. Add unit tests in `tests/domain/forms/families/<form_family>/` (`test_models.py`, `test_evidence.py`, `test_processing.py`).

### Step 3: Register Aliases and Processing Catalog

1. In `edgar_sec/domain/forms/common/aliases.py`, register submission type aliases:

```python
"<form_family>": ("<PRIMARY_FORM>", "<AMENDMENT_FORM>")

```

2. In `edgar_sec/domain/forms/families/processing_profiles.py`, register the family in `CATALOG_PROFILES`:

```python
ProcessingCatalogEntry(family="<form_family>", profile=PROFILE_FORM_<FORM_FAMILY>),

```

### Step 4: Implement Engine Parsers, Unparsed Section Embedding & XML Serializer (Layer 3)

1. Create `patterns.py` with precompiled module constants using `build_alternation`.
2. Create `sections.py` with `SectionRole` classification and `partition_<form_family>_tables`.
3. Create `metadata_parser.py` using structural cell lookaheads for cover boxes, identity, and signatures.
4. Create `securities.py` using `TableSchema` and `align_row_to_schema` from `edgar_sec.engine.forms.common.alignment` for tabular row extraction.
5. Create `render_to_xml.py` producing canonical `<edgarSubmission>` XML with native XML pass-through and embedding `unparsedSections`.
6. Create `analysis.py` providing semantic review analysis, unparsed table sniffing, and anomaly reporting for offline evaluation.

### Step 5: Register Capabilities & Dispatcher

1. In `edgar_sec/engine/document_processing/capabilities.py`, register the capability in `DEFAULT_CAPABILITIES`:

```python
ProcessingCapability(
    handler_id="<form_family>_html_to_xml",
    handler_version="1",
    operation="render_to_xml",
    input_facts="markup route primary html body",
    output_kind=HandlerOutputKind.XML,
),

```

2. In `edgar_sec/engine/document_processing/registry.py`, register the handler in `default_handler_registry()`:

```python
registry.register(
    "<form_family>_html_to_xml",
    "1",
    "render_to_xml",
    HandlerOutputKind.XML,
    _<form_family>_html_to_xml,
    family="<form_family>",
)

```

3. In `edgar_sec/engine/forms/render.py`, ensure dispatch resolves via `DEFAULT_HANDLER_REGISTRY.resolve("render_to_xml", family, None)` and raises `UnsupportedRenderOperation` if unregistered.

### Step 6: Mirrored Unit Testing & Quality Gate

1. Add unit tests in `tests/engine/forms/<form_family>/`:

- `test_patterns.py`: Pattern compilation and regex matching.
- `test_sections.py`: Multi-table partitioning and classification.
- `test_metadata_parser.py`: Cover box extraction and signature resolution.
- `test_securities.py`: Tabular row mapping, schema alignment, and type conversion.
- `test_render_to_xml.py`: Native XML pass-through, HTML-to-XML conversion, and unparsed section serialization.
- `test_analysis.py`: Semantic case analysis and scorecard computation.

2. Run quality gate:

```bash
.venv/bin/python check.py --fast                  # Fast static gate: ruff format, lint, scanners
.venv/bin/python check.py tests/engine/forms/<form_family>/ tests/domain/forms/families/<form_family>/

```

### Step 7: Review Dataset Generation, Offline Semantic Sniffing & Scorecard Evaluation

1. Generate parsed review artifacts against historical captured fixtures:

```bash
.venv/bin/python -m edgar_sec.pipelines.document_acquisition.cli review generate --fixture <fixture_name>

```

2. Run offline semantic validation and summary reporting:

```bash
.venv/bin/python -m edgar_sec.pipelines.document_acquisition.cli review analyze --run <latest_run_id>

```

3. Inspect field scorecards, boilerplate leak signals, and unparsed table counts across the full dataset to verify high-fidelity extraction.

---

## 6. General Form Refinement & Quality Baseline Reference

When evaluating any newly implemented or refined HTML-to-XML pipeline, use standard review baselines and regression suites to measure extraction fidelity. Semantic gaps must be explicitly tracked in diagnostics rather than papered over with heuristic default values.

### Review Metric Verification Pattern

An extraction run over a benchmark dataset evaluates pipeline health across total accessions, unparsed table distributions, and field completeness metrics:

| Field Category                    | Cases with Value | Cases without Value | Notes                                             |
| --------------------------------- | ---------------- | ------------------- | ------------------------------------------------- |
| **Primary Filer / Issuer Entity** | High %           | Low %               | Verifies identification and CIK parsing           |
| **Reporting Person / Manager**    | High %           | Low %               | Verifies relationship and identity metadata       |
| **Security Class / Title**        | High %           | Low %               | Verifies instrument extraction                    |
| **Primary Quantities / Units**    | Expected %       | Variable            | Reflects transaction activity                     |
| **Aggregate Values / Valuation**  | Expected %       | Variable            | Source-dependent (often market-priced or unset)   |
| **Transaction / Period Date**     | High %           | Low %               | Verifies temporal extraction and date normalizers |
| **Signatures & Attestations**     | High %           | Low %               | Verifies non-tabular attestation blocks           |

_Missing-field counts always mix genuine source omissions with parser gaps; developers must inspect original accession source documents before altering parsing boundaries or guessing default values._

### Standard Source-Backed Refinement Principles

- **Mixed Content Disambiguation**: When an HTML table contains mixed substantive data and instructional text, preserve the substantive sections (e.g. metadata boxes, transaction rows, signatures) rather than discarding the table as boilerplate.
- **Fragmented Header Consolidation**: Merge sibling layout fragments into parent entity metadata. Handle wrapped text, offset label columns, and inline sub-fields without reading field labels as values.
- **Marker-Shifted Headers**: Handle wrapped column headers, numbered sub-item markers, and footnotes without corrupting adjacent columns. Leave market-dependent or optional values unset when the source filing does not specify an amount.
- **Contextual Continuation Merging**: Headerless continuation rows must merge with preceding tables only when column layouts, date alignments, and numeric structures match. Represent explicit negative disclosures (e.g. "None", "N/A") via distinct empty or no-report models rather than dropping rows.
- **Footnotes and Remarks**: Section notes and post-table remarks map to `<remarks>` or XML footnote elements. Preserve signature blocks even when positioned next to legal boilerplate or filing agent stamps.
- **Anchor Alignment State Machine**: Extract repetitive table rows via canonical column schemas and strict anchor recognition (temporal dates, enumerated transaction/operation codes, numerical amounts, and textual security titles), using deficit deduction to handle missing optional columns rather than brittle fixed-column coordinates that degrade when columns merge or shift.
- **Structural Boundary Termination**: Stop table row collection cleanly at structural boundary signals (signature lines, notary jurats, footnote section headers) rather than letting trailing non-tabular sections leak into data fields.
- **Namespace-Independent Diagnostics**: Review analysis must use namespace-independent element matching so that any `unparsedSection` embedded within the default SEC schema envelope is captured in diagnostic scorecards and audit samples.

### Triage Workflow for Remaining Extraction Gaps

1. **Unparsed Section Classification**: Categorize substantive unparsed sections into structural layout classes (e.g. split multi-column headers, nonstandard sub-item matrices, alternate orientation layouts). Retain unmapped structures inside `<unparsedSections>` diagnostics until explicit schema mappings are implemented.
2. **Distinguish Absence from Failure**: Continually separate source-absent values (e.g. optional items omitted by the filer) from parser omissions using anomaly reports.
3. **Artifact Freshness**: Following parser modifications, always regenerate review artifacts and re-run analysis to verify that changes resolve anomalies without introducing regressions across previously passing accessions.
4. **Gate Verification**: Ensure all tests and AST policy scanners pass cleanly before committing pipeline updates:

```bash
.venv/bin/python check.py tests/engine/forms/<form_family>/ tests/domain/forms/families/<form_family>/

```
