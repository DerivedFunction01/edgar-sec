# Implementation Plan: Phase 2.5 Normalization Reflow, Structural Metadata & Inversion Recovery

> **Historical implementation record.** The milestones and recovery design below
> describe the frozen `document_storage` path, not the replacement acquisition
> contract. The current flow is owned by
> [accession document flow](./accession_document_flow/implementation.md): S5 publishes
> observed index facts, S6 plans explicit targets, S9 acquires those targets, and S10
> processes each selected body. Do not port the legacy candidate regex, era gate,
> evaluator-triggered refetch, sequence fallback, or dual-write into that flow. If
> index evidence is needed, publish it through S5 before planning; S9/S10 do not fetch
> an index page to recover a target.

## Reference
This implementation plan operationalizes the architectural contracts and Lakehouse storage design defined in:
**[Architecture & Product Roadmap (v2)](./design.md)**

---

## 1. Objectives & Architectural Boundaries

> **Milestone 1 status (2026-10-05).** The document-route classification,
> no-cover reflow, rendered-document fetch fallback, the sparse acquisition model,
> the processor v2 bump, and the pre-2005 exhibit-candidate gate have shipped
> and are verified by the suite. The candidate-gated recovery and dual-write have
> shipped: a bundle-first seam, role-neutral resolution, and the 15-column
> checkpoint schema (13 identity/normalization columns plus `metadata` and
> `report_date`) persist resolution/storage metadata. Newer-era tiered retrieval
> (index/header parsing, XBRL ZIP, heavy-HTML) remains deferred; see §1.2.

1. **Document Route Classification (Layer 1 — shipped)**: `edgar_sec/domain/document/route.py` classifies a document path into a `DocumentRoute` (`RENDERED`, `MARKUP`, `TEXT`, `PAPER`, `XML`, `BINARY`, `UNKNOWN`) before any bytes are read. A path containing `/` is `RENDERED` — an XSL rendering EDGAR serves as HTML even when its basename is `.xml` — so a slash outranks the suffix and a flat suffix is the only decisive signal. A flat `.xml` routes to `XML` and is recorded with `representation: "xml"`; `.paper` routes to `PAPER` (a fixed SGML stub naming an off-archive Document Control Number, with no filing prose); `.pdf`/`.gif`/`.jpg` route to `BINARY` and are stored verbatim.
2. **No-Cover Reflow Contract (Layer 3 — shipped)**: ASCII filings under a no-cover profile reflow prose from line 0 to EOF. No-cover is identified by the `GENERIC_PROFILE_FAMILY` key, **not** by `profile.boundary is None` — every profile carries a boundary policy, so `None` is not a distinguishing test. Cover-bearing forms (`10-K`, `10-Q`, `20-F`, `8-K`, `6-K`) still reflow after their detected `body_start_line`.
3. **Processor Version Bump (Layer 4 — shipped)**: `PROCESSOR_SCHEMA_VERSION = 2`. The normalized text changed (no-cover reflow, route-driven representation), so the processor fingerprint gates chunk reuse and a v1 checkpoint is recomputed, not reused.
4. **Sparse Submission Acquisition Model (Layer 1 & 3 & 4 — shipped)**: `AcquiredSubmission` is one accession-scoped view of one response. It separates the three things one fetch conflates — the requested `DocumentLocator`, the `AcquisitionSource` that actually answered, and each document's own `DocumentRoute`. It describes every document the response revealed as a `SubmissionDocument` and loads exactly one body, named by `selected_index` because sequence numbers and filenames can be absent or duplicated. Direct content is the singleton case; an SGML envelope routes each child by its own `<FILENAME>`, so an XML primary inside an `<accession>.txt` bundle is normalized as XML. `extract_target_sub_document_selection` materializes no sibling body, and the complete envelope is released before normalization, surviving only as `FetchResult.source_payload` for fixture seeding and the delegated-exhibit pass. The processor signature is `process(AcquiredSubmission)`, so a processor reads the body and route rather than re-deriving them from the locator. No identity, schema, SQL, or catalog-planning behavior changed.
5. **Form-Aware XML Validity — superseded by route classification.** The plan's form-based distinction (XML-native forms valid, narrative forms filter `.xml` as XBRL linkbases) was not built. The shipped behavior is path-based: a flat `.xml` is a valid primary document with `representation: "xml"` and is never reflowed; the route does not consult the form and does not filter `.xml` out of narrative filings. Form-aware XML validity remains a deliberate gap.
6. **Structural Metadata Persistence (shipped)**: `DOCUMENT_SNAPSHOT_SCHEMA` now carries 15 columns — the original 13 identity/normalization columns plus a canonical-JSON `metadata` column and a typed `report_date` column. See Stage 4. `ProcessedDocument.metadata` and review-artifact diagnostics remain separate from the persisted index and are not repurposed as the document index. Acquisition provenance (`AcquiredSubmission.source`, its document descriptors) is likewise in-memory only; no column carries it.
7. **Form-Agnostic Inversion Recovery & Dual-Write (shipped)**: pre-2005 exhibit-target recovery and the primary/exhibit dual-write now execute end to end. `candidates.py` (later the same classifier in `candidate_recovery.py`) classifies each requested locator against the 2000-2004 window, the Item 601 filename grammar, and the target form's canonical tokens; the run report counts the population. A true candidate acquires the submission bundle through a role-neutral bundle-first seam, resolves the request against it, emits one row per requested co-filer plus one projected primary row per co-filer, and persists role/parent/path/provenance in `metadata`. Unresolved outcomes fall back to the ordinary requested-document fetch and persist the typed outcome. Newer-era tiered retrieval (index/header parsing, XBRL ZIP, heavy-HTML) remains deferred; see §1.2.

---

## 1.1 Empirical Evidence: Multi-Form Sequence 1 Inversion Analysis

### Regulatory Origin (SEC EDGAR Filer Manual, October 2002 §1.5.2)
When Modernized EDGARLink launched in 2000, filers frequently attached supporting exhibits (e.g. `ex231.txt`, `consent.htm`, `bylaws.txt`) **before** the primary document. The SEC automated submission feed (`CIK***.json`) mechanically indexed Sequence 1 as the `primaryDocument`.

### Exhibit vs. Ticker Discrimination & Bundle Call Minimization
A naive pattern matching `ex*.txt` / `ex*.htm` causes false-positive bundle fetches on company names and ticker prefixes (`EXC`, `EXAS`, `EXPO`, `exxon10k.htm`, `ex-10k.htm`, `exp_10q.txt`). Monolithic bundles (50MB–200MB) must only be fetched when true sequence displacement exists.

#### 1. Precision Statutory Exhibit Regex & Grammatical Number-Word Construction:
SEC Regulation S-K Item 601 exhibits are numbered 1 to 105. Exhibit targets must match statutory number constraints and delimiter rules without matching embedded form names. Built using `foundation.regex.builder.build_alternation` per repository contract:
```python
from edgar_sec.domain.forms.common.aliases import aliases_for_family, resolve_alias
from edgar_sec.foundation.regex.builder import build_alternation

# Statutory exhibit prefix and extension alternations
_EXHIBIT_PREFIX_ALT = build_alternation(["dex", "exhibit", "ex"], auto_escape=True)
_EXHIBIT_EXT_ALT = build_alternation(["txt", "htm", "html"], auto_escape=True)
_STATUTORY_NUM_PATTERN = r"(?:[1-9]|[1-9]\d|10[0-5])"

# Matches: 'ex-10.1.htm', 'ex21.txt', 'exhibit99.htm', 'dex101.htm', 'ex-3_1.txt'
# Rejects: 'exxon.htm', 'exp.txt', 'exas.htm'
RE_STATUTORY_EXHIBIT_FILENAME = re.compile(
    rf"(?i)^(?:{_EXHIBIT_PREFIX_ALT})[-_]?{_STATUTORY_NUM_PATTERN}(?:[-._][a-z0-9]+)?\.(?:{_EXHIBIT_EXT_ALT})$"
)

# ── Grammatical Atoms & Multipliers ────────────────────────────────────────────
# Used to decompose any numeric segment of a statutory form name into a pattern
# that matches all filing-era orthographic variants observed in the catalog.
#
# Unit Atoms  (1..9):  one, two, three, four, five, six, seven, eight, nine
# Teen Atoms (10..19):  ten, eleven, twelve, thirteen, fourteen, fifteen,
#                       sixteen, seventeen, eighteen, nineteen
# Decade Atoms (20,30..90): twenty, thirty, forty, fifty, sixty, seventy,
#                            eighty, ninety
# Multipliers:  hundred  (×100),  thousand  (×1000)
#
# 2-digit compounds (21–99):
#   decade[-_]?unit          e.g. 'twenty[-_]?five' matches 'twentyfive', 'twenty-five'
#
# 3-digit hundreds (100–999) — three surface forms observed in catalog:
#   1. Colloquial (omit 'hundred') [most common in filenames]:
#        unit[-_]?decade[-_]?unit?  →  'fourtwentyfour' (424), 'onefortyfour' (144)
#        Empirical: 'fourtwentyfour.txt', 'glacprofourtwentyfour.txt' (Form 424B)
#   2. Full formal (with optional 'hundred' and optional 'and'):
#        unit[-_]?hundred(?:[-_]?and)?[-_]?...  →  'four-hundred-twenty-four'
#        Empirical: 'formfourfourhundredthousand.txt' (Form 4), 'oneeighthundred_13ga-123106.txt'
#   3. Digit-hybrid:
#        unit[-_]?\d{2}  →  'four24', 'four25'  (leading word + trailing digits)
#
# Delimiter placement rules (from catalog count analysis):
#   - Delimiters occur exclusively at major lexical-transition boundaries:
#       number↔letter:   10[-_]?k,  8[-_]?k,  424[-_]?b
#       form↔sub-rule:   10[-_]?ksb,  12b[-_]?25,  10[-_]?k[-_]?405
#   - Sub-acronym clusters (ksb, 405, b3) are NEVER internally fragmented.
#   - Catalog counts (13.85 M rows):
#       10ksb (no sep): 22,927  |  10-ksb: 958  |  10_ksb: 1,019
#       10k405: 1,050           |  10-k405: 3,325
#       12b25: 16,576           |  12b-25: 4,514  |  12b_25: 5,141

_UNITS = {
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}
_TEENS = {
    "10": "ten",
    "11": "eleven",
    "12": "twelve",
    "13": "thirteen",
    "14": "fourteen",
    "15": "fifteen",
    "16": "sixteen",
    "17": "seventeen",
    "18": "eighteen",
    "19": "nineteen",
}
_DECADES = {
    "20": "twenty",
    "30": "thirty",
    "40": "forty",
    "50": "fifty",
    "60": "sixty",
    "70": "seventy",
    "80": "eighty",
    "90": "ninety",
}


def _num_word_variants(n: int) -> list[str]:
    """Return all regex sub-patterns that match the word-spelled form of integer n.

    Returned patterns assume case-insensitive matching and allow [-_]? between
    every component.  The raw digit string itself is NOT included here — callers
    add that separately so the digit form is always an option.

    Supported range: 1..999.
    """
    sep = r"[-_]?"
    s = str(n)
    variants: list[str] = []

    if n <= 9:
        # e.g. 3 → 'three'
        variants.append(_UNITS[s])

    elif n <= 19:
        # e.g. 12 → 'twelve'
        variants.append(_TEENS[s])

    elif n <= 99:
        # e.g. 25 → 'twenty[-_]?five'  OR just 'twenty' if decade-exact
        dec = str((n // 10) * 10)
        unit = str(n % 10)
        if unit == "0":
            variants.append(_DECADES[dec])
        else:
            variants.append(_DECADES[dec] + sep + _UNITS[unit])

    else:
        # 100..999
        h = n // 100
        rest = n % 100
        hw = _UNITS[str(h)]  # e.g. 'four' for 400s
        dec = str((rest // 10) * 10)
        unit = str(rest % 10)

        if rest == 0:
            rest_w = None
        elif rest <= 9:
            rest_w = _UNITS[str(rest)]
        elif rest <= 19:
            rest_w = _TEENS[str(rest)]
        else:
            u = rest % 10
            rest_w = _DECADES[dec] + (sep + _UNITS[str(u)] if u != 0 else "")

        # Form 1 – colloquial (omit 'hundred'): fourtwentyfour, onefortyfour
        if rest_w:
            variants.append(hw + sep + rest_w)

        # Form 2 – full formal with optional 'hundred' prefix and optional 'and':
        #   four[-_]?hundred[-_]?twenty[-_]?four
        #   four[-_]?hundred[-_]?and[-_]?twenty[-_]?four
        if rest_w:
            and_clause = f"(?:{sep}and)?{sep}"
            variants.append(hw + sep + "hundred" + and_clause + rest_w)
            # also without leading unit: hundred[-_]?...  (e.g. 'hundredfortyfour')
            variants.append("hundred" + and_clause + rest_w)
        else:
            variants.append(hw + sep + "hundred")

        # Form 3 – digit-hybrid: leading word + trailing two-digit number
        #   'four24', 'four-24'  (observed: 'four25' → 425)
        if rest > 0:
            variants.append(hw + sep + str(rest).zfill(2))

    return variants


def _alias_word_patterns(alias: str) -> list[str]:
    """Expand one canonical alias string into all word+digit variant patterns.

    Algorithm (empirically derived from 2000-2005 era catalog filings):
      1. Tokenise alias into alternating runs of digit-characters and
         alpha-characters, stripping canonical separators (- /).
         e.g. '12b-25' → ['12', 'b', '25']
              '10-K405' → ['10', 'k', '405']
              '10-KSB'  → ['10', 'ksb']
              '424B3'   → ['424', 'b', '3']
              '10-K'    → ['10', 'k']
      2. For each numeric run produce two pattern options:
           a. raw digit string:       '12'
           b. word-atom expansion(s): _num_word_variants(12)  ('twelve')
      3. For each alpha run, treat as a single literal atom (no expansion).
      4. Cross-product all segment options, joined by sep = r'[-_]?'.
         This matches both concatenated and delimited variants.

    Examples:
      '10-KSB'  → r'(?:10|ten)[-_]?ksb'
      '10-K405' → r'(?:10|ten)[-_]?k[-_]?(?:405|fourhundred[-_]?(?:and[-_]?)?five|fourhundredfive|fourhundred[-_]?and[-_]?five|four05)'
      '12b-25'  → r'(?:12|twelve)[-_]?b[-_]?(?:25|twenty[-_]?five)'
      '424B3'   → r'(?:424|four[-_]?twenty[-_]?four|four[-_]?hundred[-_]?(?:and[-_]?)?twenty[-_]?four|four24)[-_]?b[-_]?(?:3|three)'
    """
    import re as _re

    sep = r"[-_]?"
    # Tokenise: split into alternating digit-runs and alpha-runs,
    # ignoring canonical separators.
    clean = _re.sub(r"[-/ ]+", "", alias)  # strip '-', '/', spaces
    tokens = _re.findall(r"(\d+|[a-zA-Z]+)", clean)

    # Build list-of-lists: each position holds the possible regex atoms
    segment_options: list[list[str]] = []
    for tok in tokens:
        if tok.isdigit():
            opts = [tok] + _num_word_variants(int(tok))
            # Wrap in non-capturing group if > 1 option
            if len(opts) > 1:
                alt = build_alternation(opts, auto_escape=False)
                segment_options.append([alt])
            else:
                segment_options.append(opts)
        else:
            segment_options.append([tok.lower()])

    # Cross-product: join each combination with sep
    from itertools import product

    patterns = [sep.join(combo) for combo in product(*segment_options)]
    return patterns


from functools import lru_cache


@lru_cache(maxsize=64)
def primary_form_token_pattern(form: str | None) -> re.Pattern[str]:
    """Derive and memoize a primary-document token pattern for one canonical form family.

    Why lru_cache instead of a global table:
      - Homogeneous plan (e.g. 10-K with 353,000 targets): pattern compiled once,
        then 100% cache hits.  No global 500-form alternation string allocated.
      - Mixed-form plan: each family's isolated pattern fetched from the LRU cache
        independently; never a monolithic cross-form regex.

    What the generated pattern matches:
      The pattern fires on filenames whose token is plausibly the *primary* form
      document (not a Tier-4 exhibit inversion).  It covers:
        - Canonical digit form strings:   '10k',  '8k',  '424b3'
        - All alias digit strings:        '10ksb', '10k405', '12b25'
        - Word-number variants of each alias segment (2000-2005 era filer practice):
            '10-KSB'  → 'ten[-_]?ksb',  'tenksb'
            '12b-25'  → 'twelve[-_]?b[-_]?(?:25|twenty[-_]?five)'
            '8-K'     → '(?:8|eight)[-_]?k'
        - Context tokens:  'form', 'report', 'annual', 'quarterly', 'current'

    Delimiter placement follows catalog-empirical rules (see atom comment above):
      - [-_]? is placed at every major digit↔letter or form↔sub-rule boundary.
      - Sub-acronym clusters (ksb, 405, b3) are never internally split.
    """
    family = resolve_alias(form) or (form.upper().strip() if form else None)
    aliases = aliases_for_family(family) if family else ()

    # Seed with universal context tokens
    all_patterns: list[str] = ["form", "report"]

    if family:
        # Context tokens per family
        if family in ("10-K", "20-F"):
            all_patterns.append("annual")
        elif family == "10-Q":
            all_patterns.append("quarterly")
        elif family == "8-K":
            all_patterns.append("current")

        # Expand every alias (including canonical family name) into word variants
        for alias in (family, *aliases):
            all_patterns.extend(_alias_word_patterns(alias))

    token_alt = build_alternation(sorted(set(all_patterns)), auto_escape=False)
    return re.compile(rf"(?i){token_alt}")
```

#### 2. Four-Tier Filter to Minimize Monolithic Bundle Calls (99.98% Reduction):
1. **Temporal Gate (`2000-01-01 <= filing_date < 2005-01-01`)**:
   - Pre-2000 targets are already monolithic bundles by default.
   - Post-2005 submissions have **0.0% true sequence inversions** across 3.19M filings due to Modernized EDGARLink header enforcement. All post-2005 targets `PROCEED` directly.
2. **Dynamic Profile Form Token Exclusion**: If the filename matches `primary_form_token_pattern(locator.form)` (e.g. `ex-10k.htm`, `ex10k.txt`), fetch directly as primary document.
3. **Statutory Number Match**: Filenames lacking statutory numbers 1–105 (e.g. `exxon.htm`, `exp.txt`) are fetched directly.
4. **SGML Envelope Tier 1 `<TYPE>` Extraction**:
   - When the bundle `<accession>.txt` is unpacked, `unpacker.resolve_target_sub_document(docs, target_types=(form, form/A))` searches all sub-document `<TYPE>` tags.
   - If Sequence 1 is already `<TYPE> 10-K`, it is extracted directly as primary.
   - If Sequence 1 is `<TYPE> EX-21` and Sequence 2 is `<TYPE> 10-K`, Sequence 2 is extracted as primary and Sequence 1 is preserved as the dual-written companion exhibit.

### Empirical Verification Across All Major Form Cohorts (3,191,541 Filings)
Direct out-of-core SQL analysis in DuckDB over the target plans (`548a9e4e9be668b05289b7ea` for 10-K, `ca709ba4d53c192ae537119f` for 10-Q, and `f062669cec5db007df9c2452` for 8-K) reveals the exact historical footprint across 33 years (1993–2026):

| Form Cohort | Total Targets | Monolithic Bundles (`<acc>.txt`) | Standard Form Names | Exhibit-Named Primary Targets | Proven True Inversions | Post-2005 True Inversions |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Form 10-K / 10-K/A** | 353,261 | 72,586 | 208,353 | 622 | ~500 | 0 |
| **Form 10-Q / 10-Q/A** | 758,140 | 118,290 | 542,810 | 41 | 32 | 0 |
| **Form 8-K / 8-K/A** | 2,080,140 | 109,082 | 1,425,768 | 157 | 42 | 0 |
| **Combined Total** | **3,191,541** | **299,958** | **2,176,931** | **820** | **~574** | **0** |

#### The Three Structural Eras:
1. **Pre-2000 Era (1993–1999)**:
   - **0 exhibit inversions** across all forms.
   - 100% of filings are monolithic `<accession>.txt` submission bundles where all sub-documents reside inside the ASCII envelope.
2. **Early Modernized EDGARLink Era (2000–2004)**:
   - **Peak Sequence 1 Inversion Era**: Over 90% of all true inversions occur in this window (72 in 10-K, 32 in 10-Q, 34 in 8-K in 2001 alone).
   - Filers attached supporting exhibits (`EX-99`, `EX-16`, `EX-11`, `EX-3`) prior to the primary form.
   - **Verified Inversion Samples**:
     - *10-K (2001, CIK 0000890923)*: Seq 1 is `ex21.txt` (`EX-21`), Seq 2 is `d10k405.txt` (`10-K405`).
     - *10-Q (2000, CIK 0001092896)*: Seq 1 is `ex11.txt` (`EX-11`), Seq 2 is `form10q.txt` (`10-Q`).
     - *8-K (2001, CIK 0000893958)*: Seq 1–9 are exhibits (`EX-99`, `EX-4`), Seq 11 is `carat2001-1post8k01232001.txt` (`8-K`).
3. **Post-2005 & Modern XBRL Era (2005–present)**:
   - **Zero True Inversions (0.0%)**: Modernized EDGARLink validation eliminated sequence displacement.
   - The few exhibit-named files (94 in 8-K, 4 in 10-Q) were audited against live SEC dissemination indexes: **100% are officially registered in EDGAR headers as Sequence 1 with primary form type** (e.g., `<TYPE> 8-K` for `bylawamendment.htm` or `ex99-1.htm`). The filer merely gave the primary document an exhibit-like filename upon upload.

This proves that Sequence 1 Exhibit Inversion is **strictly a 2000–2004 legacy artifact**, and that the `REFETCH_BUNDLE` recovery strategy generalizes cleanly across 10-K, 10-Q, and 8-K.

---

## 1.2 Deliberate Gaps & Milestone Scope

### Shipped in Milestone 1:
1. **Document Route Classification**: `domain/document/route.py` — `DocumentRoute`, `document_route()`, `mime_type_for_suffix()`, `is_markup_document_path()`, `archive_root_candidate()`, and the `REPRESENTATION_*` names.
2. **No-Cover Reflow**: ASCII prose under a no-cover profile reflows from line 0; cover-bearing forms reflow after `body_start_line`. No-cover is keyed on `GENERIC_PROFILE_FAMILY`, not `profile.boundary is None`.
3. **Rendered-Document Fetch Fallback**: `fetching.archive_root_url()` fetches a `RENDERED` path's archive-root basename first, keeping the rendering as fallback.
4. **Processor v2**: `PROCESSOR_SCHEMA_VERSION = 2`; the fingerprint gates chunk reuse.

### Deferred to Subsequent Milestones:
1. **Form-Aware XML Validity**: distinguishing an XML-native form's filing from an XBRL linkbase by form. The shipped route is path-based and makes no such distinction.
2. **Forced Full-Bundle Acquisition (`--acquisition-policy full_bundle`)**: execution defaults to sparse acquisition (~2MB primary document).
3. **Cross-Snapshot Anti-Join Diffing (`--base-snapshot a1`)**: incremental delta execution between published snapshots.
4. **BlockStream 1D Virtual AST**: `SpanDecision` lacks byte/char offsets and merges spans, so normalization continues emitting clean `normalized_text`.
5. **Phase 3 Virtual Aggregate View (`filing_aggregates`)**: deferred until Phase 3 materializes `sections.parquet`.

---

## 2. Phased Implementation Roadmap

```mermaid
flowchart LR
    S1["Stage 1: Document Route<br/>(shipped)"] --> S2["Stage 2: No-Cover Reflow<br/>(shipped)"]
    S2 --> S3["Stage 3: Processor v2<br/>(shipped)"]
    S3 --> S4["Stage 4: Storage Schema & Metadata<br/>(shipped)"]
    S4 --> S5["Stage 5: Inversion Dual-Write<br/>(shipped)"]
    S5 --> S6["Stage 6: Quality Gate & Verification"]
```

---

### Stage 1: Document Route Classification (Layer 1 — shipped)

#### Responsibilities:
- Classify a document path into a `DocumentRoute` before any bytes are read.
- A path containing `/` is `RENDERED` (an XSL rendering EDGAR serves as HTML); a flat suffix selects `MARKUP`, `TEXT`, `PAPER`, `XML`, `BINARY`, or `UNKNOWN`.
- Own the MIME table and the representation names so the fixture index and the processor describe one document with the same type.

#### File Modifications:
1. **`edgar_sec/domain/document/route.py`**: `DocumentRoute`, `document_route()`, `is_markup_document_path()`, `is_rendered_document_path()`, `archive_root_candidate()`, `mime_type_for_suffix()`, `MIME_BY_SUFFIX`, and the `REPRESENTATION_*` names.
2. **`edgar_sec/pipelines/document_storage/fetching.py`**: `archive_root_url()` fetches a `RENDERED` path's archive-root basename first and keeps the rendering as fallback, so a root document that does not exist cannot turn a reachable filing into a failure.
3. **`tests/domain/document/test_route.py`**: mirrored coverage of the route table, the slash-outranks-suffix rule, and the MIME table.

---

### Stage 2: Engine Normalization & No-Cover Reflow (Layer 3 — shipped)

#### Responsibilities:
- Fix the reflow gating defect in `normalize.py`: ASCII filings under a no-cover profile unwrap prose paragraphs from line 0, while cover-bearing forms (`8-K`, `6-K`, `10-K`, `10-Q`) reflow after their detected `body_start_line`.
- No-cover is identified by `profile.family == GENERIC_PROFILE_FAMILY`, **not** by `profile.boundary is None` — every profile carries a boundary policy, so `None` is not a distinguishing test.
- Only the text routes enter the reflow gate; markup, XML, binary, and paper routes are excluded by omission.

#### File Modifications:
1. **`edgar_sec/engine/forms/normalize.py`**:
   - `normalize_document(raw_bytes, *, form=None, document_path=None)` — `document_path` selects the route.
   - `_TEXT_ROUTES` gates reflow eligibility; `_representation_name(route, detected)` returns `REPRESENTATION_XML` for the XML route, where detection cannot see the format.
   - Reflow condition:
     ```python
     reflow_result: ReflowResult | None = None
     reflow_eligible = route in _TEXT_ROUTES
     no_cover = profile.family == GENERIC_PROFILE_FAMILY
     if (
         reflow_eligible
         and representation is not Representation.HTML
         and (body_start_line > 0 or no_cover)
     ):
         ...
         reflow_result = reflow_ascii(
             text,
             body_start_line=0 if no_cover else body_start_line,
             page_analysis=analysis,
             policy=reflow_policy,
         )
     ```
   - A `PAPER` route returns before any form-driven stage runs; a `BINARY` route raises rather than inventing text.
2. **`edgar_sec/engine/forms/cover/profiles.py`**: `GENERIC_PROFILE_FAMILY` — the family key every unmodelled form resolves to.
3. **`tests/engine/forms/test_normalize.py`**: no-cover ASCII unwraps from line 0; cover-bearing forms reflow after their boundary; XML-like input is not reflowed.

---

### Stage 3: Processor Evolution (Layer 4 — shipped)

#### Responsibilities:
- Bump `PROCESSOR_SCHEMA_VERSION = 2`, so a v1 checkpoint is recomputed rather than reused.
- Route the document in `FilingProcessor.process()`: `BINARY` is stored verbatim; `PAPER` skips the evaluator; every other route normalizes.

#### File Modifications:
1. **`edgar_sec/pipelines/document_storage/processor.py`**:
   - `PROCESSOR_SCHEMA_VERSION = 2` and the matching fingerprint.
   - `ProcessedDocument.metadata` carries the normalization diagnostics already produced — `family`, `representation`, `word_count`, the page-marker and reflow counts, `stage_count`, the cover/body/closing boundary fields, and the triage decision. It does **not** carry `table_count`, `toc_span`, `is_inversion`, `target_document_path`, or `parent_locator_key`; those belong to the deferred structural-metadata work.
   - `ProcessedDocument.text` returns `""` for a `raw` payload rather than decoding bytes into invented text.
2. **`tests/pipelines/document_storage/test_processor.py`**: the fingerprint reflects v2; `ProcessedDocument.metadata` contains the diagnostic fields.

---

### Stage 4: Storage Schema & Structural Metadata (Layer 4 — shipped)

#### Shipped: the 15-column snapshot schema and per-occurrence metadata

The checkpoint schema grew from 13 to 15 columns. Column 14 is `metadata`, a Parquet
string column holding canonical JSON from the resolution/worker context (default
`"{}"`); column 15 is `report_date`, the occurrence's typed report date, carried from
the catalog plan and nullable on old snapshots. `ProcessedDocument.metadata` stays
scoped to normalization/evaluator diagnostics and is not the filing-resolution metadata
source; acquisition provenance stays in-memory only.

#### File Modifications:
1. **`edgar_sec/pipelines/document_storage/checkpoint.py`**:
   - Added `("metadata", pa.string())` and `("report_date", pa.string())` to
     `DOCUMENT_SNAPSHOT_SCHEMA`.
   - `write_chunk_snapshot` accepts `metadata_map` and `report_dates` per-occurrence
     mappings; metadata is validated as canonical JSON at write time.
2. **`edgar_sec/pipelines/document_storage/worker.py`**: `_build_snapshot_batch` emits
   both columns; `process_chunk` tracks occurrence IDs seen in a chunk and counts
   unique persisted rows for the staging commit.
3. **`edgar_sec/pipelines/document_storage/merger.py`**: carries `metadata` and
   `report_date` through the assembled artifact and into the index parts; bumps
   `SNAPSHOT_SCHEMA_VERSION` to `2`; merge assembly collapses identical rows per
   `occurrence_id` and rejects conflicting identity, metadata, payload/text, or
   status/error values.
4. **`edgar_sec/pipelines/document_storage/parts.py`**: `INDEX_COLUMNS` gains
   `metadata`.
5. **`edgar_sec/pipelines/document_storage/queries.py`**: `effective_snapshot_relations`
   projects `COALESCE(metadata, '{}') AS metadata` so old snapshots consolidate with
   new ones.
6. **`edgar_sec/pipelines/document_storage/delegation.py`**: `write_exhibit_snapshot`
   passes the new column mappings.
7. **`tests/pipelines/document_storage/test_checkpoint.py`**: verify the `metadata`
   and `report_date` columns are written and validated.

---

### Stage 5: Inversion Recovery & Dual-Write Storage (Layer 4 — shipped)

#### Shipped: bundle-first candidate recovery and the dual-write

A `BUNDLE_CANDIDATE` now acquires the submission bundle through a new
`ArchiveFetcher.fetch_bundle(locator) -> BundleFetchResult` seam (fixture, broker, and
live backends), resolves the requested document against it with the existing
`resolve_candidate_filing`, and emits one row per requested co-filer plus one projected
primary row per co-filer. The bundle-first execution lives in
`edgar_sec/pipelines/document_storage/candidate_recovery.py`; the worker keeps its
locator loop, candidate decision, and row writing. Unresolved outcomes fall back to the
ordinary requested-document fetch and persist the typed outcome in `metadata`.

#### File Modifications:
1. **`edgar_sec/pipelines/document_storage/fetching.py`**: `ArchiveFetcher.fetch_bundle`
   acquires the complete submission bundle for a candidate locator through the fixture,
   broker, and live backends, returning a typed `BundleFetchResult`. It keeps accession
   URL construction inside the backend; neither the worker nor the resolver builds a
   `.txt` path.
2. **`edgar_sec/pipelines/document_storage/candidate_recovery.py`**: bundle-first
   execution, role-neutral seed-reference construction, resolver adaptation, direct
   fallback, reference-to-`AcquiredSubmission` conversion, and per-body processing
   results. Emits one `CandidateOutcome` per row with the resolution/storage metadata
   (`document_role`, `parent_locator_key`, `document_path_source`, `resolution_outcome`).
3. **`edgar_sec/pipelines/document_storage/worker.py`**: a `BUNDLE_CANDIDATE` runs
   `run_candidate_recovery`, writes each outcome (deduped by `occurrence_id` within the
   chunk), and records any stub delegation target; unresolved outcomes fall back to the
   ordinary requested-document fetch.
4. **`edgar_sec/pipelines/document_storage/processing.py`**: ordinary-path helpers
   (`_build_snapshot_batch`, `_process_locator`, `_record_delegation`) moved out of
   the worker loop so `worker.py` stays under its line cap.
5. **`edgar_sec/pipelines/document_storage/work_order.py`**: `FilingWork` and
   `DelegationTarget` moved here so the ordinary-path helpers can share them without a
   cycle on the worker.
6. **`tests/pipelines/document_storage/test_fetching.py`**: bundle-first recovery
   through the broker fetcher, dual-write rows, and the role/parent/metadata contract.

#### Shipped: catalog resumability with a transient run manifest

A catalog plan run is resumable under the same `run_id`; generic and JSON-plan runs
remain fresh-only. A transient manifest (`runs/<run_id>/manifest.json`) records the
bundle's plan identity, verified selection fingerprint, source digests, and execution
inputs, and is written atomically before the first fetch. A matching manifest makes the
run `resumed` and skips every complete chunk whose Parquet checkpoint, processor
fingerprint, and durable delegation sidecar validate; a missing, malformed, or mismatched
manifest refuses before fetch and leaves all chunks untouched. The three chunk states are
reported as `fresh_chunk_count` (no valid `.tmp` stage), `resumed_chunk_count` (continued
from a valid partial stage), and `reused_chunk_count` (skipped behind a valid checkpoint
and sidecar). The delegated-exhibit pass carries a validated input identity from the
per-chunk sidecars and processor fingerprint, so `chunk-delegated.parquet` and its state
are reused rather than refetched. Publication of the same `run_id` validates the existing
snapshot manifest, artifact digest, row count, chunk inventory, and every part's size,
row count, SHA-256, and safe path, and returns it unmodified with `reused=True` when all
checks pass; an incomplete, malformed, or conflicting snapshot is refused without
mutation. Selection drift is detected through the recomputed selection fingerprint and
pinned source digests. Fixture contents are not hashed, so a resumed incomplete chunk may
observe newer payloads for the same fixture IDs.

#### URL / Filename Is Not Authoritative for Primary Identity (2000–2005 era)

Even when the EDGAR-disseminated URL or the `primary_document` field in the submissions catalog
carries a name that looks like the primary form (e.g. `form10k.txt`, `eightk.txt`, `tenksb.htm`),
that name is **not a contract**. In the 2000–2005 era, filers routinely registered the wrong
sequence-1 slot or used exhibit-pattern names for the true primary. Resolution therefore depends on
the bundle format:

**ASCII / SGML bundles (`.txt` envelope) — authoritative and machine-readable:**
- Every sub-document within the SGML envelope is delimited by `<DOCUMENT>` / `</DOCUMENT>` blocks
  and carries explicit headers:
  ```
  <SEQUENCE>1
  <FILENAME>ex21.txt
  <TYPE>EX-21
  ```
  and
  ```
  <SEQUENCE>2
  <FILENAME>d10k405.txt 
  <TYPE>10-K405
  ```
- `unpacker.resolve_target_sub_document(docs, target_types=(form, form/A))` scans all
  `<TYPE>` values in sequence order and promotes the first match to primary, regardless of
  its sequence number. This is fully deterministic and does not rely on the filename at all.
- Sequence inversion (exhibit-at-seq-1) is therefore **trivially recoverable from ASCII bundles**:
  the `<TYPE>` tag on each sub-document is the ground truth.

**HTML submissions — no equivalent structural header:**
- Pre-2005 HTML-primary filings do not carry `<SEQUENCE>` / `<TYPE>` blocks in a parseable
  envelope. The only available signal is the EDGAR filing index page which lists documents with their described type and sequence.
- Where the target URL points to an HTML file, and the filename resembles an exhibit (matches
  `RE_STATUTORY_EXHIBIT_FILENAME` but not the form token pattern), the recovery path falls back
  to fetching the full SGML bundle `<accession>.txt`.

**Practical consequence for Stage 4:**
- The `primary_form_token_pattern(form)` check is a **fast pre-filter** to avoid fetching
  bundles unnecessarily. It does not assert primary identity.
- True primary identity is confirmed exclusively by `<TYPE>` matching inside the unpacked SGML
  envelope. The URL is advisory only.

#### File Modifications:
1. **`edgar_sec/pipelines/document_storage/fetching.py`**:
   - Detect pre-2005 exhibit-named targets via `RE_STATUTORY_EXHIBIT_FILENAME` and resolve to the accession bundle `<accession>.txt`.
   - `extract_from_sgml_envelope` extracts the true primary form matching `target_types=(form, form/A)` via Tier 1 in `unpacker.py`.
2. **`edgar_sec/pipelines/document_storage/worker.py`**:
   - For recovered inversions, append both the primary form and the exhibit occurrence records to the chunk batch.
   - Emitting `metadata` to the 14th column is Stage 4 work, in `_build_snapshot_batch`.
3. **`tests/pipelines/document_storage/test_worker.py`**:
   - Add test case verifying dual-write on inverted fixture submissions.

---

### Stage 6: Quality Gate & Verification

#### Responsibilities:
- Run all static policy scanners (`check.py`).
- Run the full test suite (`check.py --all`), only when explicitly requested.
- Verify line count limits (`worker.py` < 800 lines).
- Update package `README.md` files for touched packages.

#### Verification Steps:
1. `.venv/bin/python check.py --fast` (all registered policy scanners green — `AGENTS.md` registers 14, not the 12 this plan previously claimed).
2. `.venv/bin/python check.py` ( test suite green).
3. Probe script verifying normalized output and representation on review cohort filings, covering a flat `.xml`, an XSL rendering, and a `.paper` stub.

---

## 3. Component Touch Matrix

Actual Milestone 1 and Milestone 2 changes. The deferred later-stage work (cross-snapshot
anti-join diffing, `full_bundle` acquisition policy, blockstream 1D virtual AST, Phase 3
`filing_aggregates`) is excluded.

| Component File | Layer | Action | Scanners & Contracts Enforced |
| :--- | :--- | :--- | :--- |
| `edgar_sec/domain/document/route.py` | Layer 1 | **ADD** | `DocumentRoute` classification; slash-outranks-suffix rule; single MIME vocabulary. |
| `tests/domain/document/test_route.py` | Tests | **ADD** | Mirrored path rule; route table and MIME table coverage. |
| `edgar_sec/engine/forms/normalize.py` | Layer 3 | **EDIT** | Route-gated no-cover reflow from line 0; route-driven representation; paper stub and binary refusal. |
| `edgar_sec/engine/forms/cover/profiles.py` | Layer 3 | **EDIT** | `GENERIC_PROFILE_FAMILY` as the no-cover key. |
| `tests/engine/forms/test_normalize.py` | Tests | **EDIT** | No-cover unwrapping, cover-boundary reflow, and XML no-reflow regression. |
| `edgar_sec/pipelines/document_storage/processor.py` | Layer 4 | **EDIT** | `PROCESSOR_SCHEMA_VERSION = 2`; binary verbatim storage; `raw` text contract. |
| `tests/pipelines/document_storage/test_processor.py` | Tests | **ADD** | v2 fingerprint and diagnostic metadata. |
| `edgar_sec/pipelines/document_storage/fetching.py` | Layer 4 | **EDIT** | `archive_root_url()` rendered-document fallback; fixture lookup order. |
| `edgar_sec/pipelines/document_storage/candidates.py` | Layer 4 | **ADD** | Item 601 filename grammar; family-keyed primary-form-token memo; occurrence-date agreement; advisory candidate decision. |
| `edgar_sec/pipelines/document_storage/worker.py` | Layer 4 | **EDIT** | `FilingWork` handoff; plan-derived candidate counts on processed and skipped chunks. |
| `edgar_sec/pipelines/document_storage/operator.py` | Layer 4 | **EDIT** | Candidate counts on `RunReport` and `to_dict()`. |
| `edgar_sec/pipelines/document_storage/cli.py` | Layer 4 | **EDIT** | Candidate counts in the `run` summary. |
| `tests/pipelines/document_storage/test_candidates.py` | Tests | **ADD** | Window edges, date agreement, filename and form-token discrimination. |
| `tests/pipelines/document_storage/test_fetching.py` | Tests | **EDIT** | A candidate request changes no broker or live request, selection, or stored row. |
| `tests/pipelines/document_storage/test_operator_and_cli.py` | Tests | **EDIT** | Candidate counts in JSON and text output, across chunks, over co-filers, and for a resumed chunk. |
| `edgar_sec/pipelines/document_storage/fixture_operator.py` | Layer 4 | **EDIT** | MIME sourced from the shared route table. |
| `edgar_sec/pipelines/document_storage/review_artifacts.py` | Layer 4 | **EDIT** | Review defers a binary route exactly as the worker does. |
| `tests/pipelines/document_storage/test_worker.py` | Tests | **EDIT** | Checkpoint reuse gated on the v2 fingerprint; candidate counts on processed, resumed, and pooled chunks. |
| `edgar_sec/domain/document/README.md` | Doc | **EDIT** | Route contracts and caller obligations. |
| `edgar_sec/engine/forms/README.md` | Doc | **EDIT** | Route-driven stage eligibility and representation. |
| `edgar_sec/pipelines/document_storage/README.md` | Doc | **EDIT** | Route-aware acquisition and normalization. |
| `edgar_sec/pipelines/document_storage/checkpoint.py` | Layer 4 | **EDIT** | 15-column snapshot schema (`metadata`, `report_date`); canonical-JSON validation; schema enforcement. |
| `tests/pipelines/document_storage/test_checkpoint.py` | Tests | **ADD** | Mirrored path; `metadata`/`report_date` written and validated. |
| `edgar_sec/pipelines/document_storage/candidate_recovery.py` | Layer 4 | **ADD** | Bundle-first execution, role-neutral resolution, per-body processing, stub delegation targets. |
| `tests/pipelines/document_storage/test_candidate_recovery.py` | Tests | **ADD** | Bundle success/missing/failed, `PRIMARY_RECOVERED` and `REQUESTED_IS_PRIMARY`, fallback. |
| `edgar_sec/pipelines/document_storage/processing.py` | Layer 4 | **ADD** | Ordinary-path helpers (`_build_snapshot_batch`, `_process_locator`, `_record_delegation`) extracted from the worker loop. |
| `tests/pipelines/document_storage/test_processing.py` | Tests | **ADD** | Mirrored; snapshot-batch and locator processing. |
| `edgar_sec/pipelines/document_storage/work_order.py` | Layer 4 | **ADD** | `FilingWork`, `DelegationTarget`, `ChunkInput`, `WorkOrder` protocol. |
| `edgar_sec/pipelines/document_storage/merger.py` | Layer 4 | **EDIT** | `metadata`/`report_date` carried to artifact and index parts; dedup by `occurrence_id`; conflict refusal. |
| `tests/pipelines/document_storage/test_merger.py` | Tests | **EDIT** | Schema version, `metadata`/`report_date`, dedup and conflict refusal. |
| `edgar_sec/pipelines/document_storage/parts.py` | Layer 4 | **EDIT** | `INDEX_COLUMNS` gains `metadata`. |
| `tests/pipelines/document_storage/test_parts.py` | Tests | **ADD** | Mirrored path; `INDEX_COLUMNS` includes `metadata`. |
| `edgar_sec/pipelines/document_storage/queries.py` | Layer 4 | **EDIT** | `effective_snapshot_relations` projects old `metadata` as `{}`. |
| `tests/pipelines/document_storage/test_queries.py` | Tests | **EDIT** | Old/new snapshot consolidation. |
| `edgar_sec/pipelines/document_storage/vacuum.py` | Layer 4 | **EDIT** | Compatibility projection for mixed old/new snapshots. |
| `tests/pipelines/document_storage/test_vacuum.py` | Tests | **ADD** | Mirrored; old snapshot read with defaults. |
| `tests/pipelines/document_storage/test_operator_and_cli.py` | Tests | **EDIT** | Candidate-count summary plus bundle-first recovery counts. |
| `edgar_sec/pipelines/document_storage/README.md` | Doc | **EDIT** | Layout includes `candidate_recovery.py`; bundle-first execution; persisted `document_path_source`. |
---
## 4. Sign-Off & Execution Readiness

This plan conforms strictly to:
1. `AGENTS.md` (5-layer acyclic downward import contract, cgroup memory bounds, mirrored test structure, zero legacy shims).
2. [Architecture & Product Roadmap (v2)](./design.md) (document route selection, sparse aggregate design, Lakehouse aggregate design).
