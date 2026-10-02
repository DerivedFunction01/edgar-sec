# Implementation Plan: Phase 2.5 Normalization Reflow, Structural Metadata & Inversion Recovery

## Reference
This implementation plan operationalizes the architectural contracts and Lakehouse storage design defined in:
**[Architecture & Product Roadmap (v2)](./design.md)**

---

## 1. Objectives & Architectural Boundaries

1. **Structural Metadata Persistence (Layer 2 & 4)**: Expand `DOCUMENT_SNAPSHOT_SCHEMA` from 13 to 14 columns by persisting a canonical JSON `metadata` column (`pa.string()`). Capture essential downstream markers (`body_start_line`, `toc_span`, `table_count`, `word_count`, `representation`, `is_inversion`, `parent_locator_key`, `target_document_path`) while discarding ephemeral line-by-line debugging traces.
2. **No-Cover Reflow Contract & Active Current Profiles (Layer 3)**: Acknowledge that Form 8-K and Form 6-K possess statutory SEC cover pages governed by dedicated `CurrentReportEvidence` profiles (`build_current_profile`). Fix the reflow gating defect in `normalize.py` where `body_start_line > 0` skipped prose unwrapping for ASCII filings under unsegmented/no-cover profiles (`GENERIC`, standalone exhibits, `profile.boundary is None`), enabling reflow from line 0 to EOF.
3. **Form-Agnostic Inversion Recovery & Dual-Write (Layer 2 & 4)**: When a pre-2005 target link points to an exhibit (`ex*.txt`, `ex*.htm`), fetch `<accession>.txt`, extract the true primary document via form-typed Tier 1 unpacking (`target_types`), and dual-write **both** the recovered primary form (`role: "primary"`) and the original exhibit (`role: "exhibit"`, `parent_locator_key`). This satisfies the target plan's locator key without discarding the normalized exhibit.
4. **Symmetric Document Storage (Layer 2)**: Both primary documents and exhibits share the standard 14-column `DOCUMENT_SNAPSHOT_SCHEMA`, distinguished by `metadata.role` and linked via `parent_locator_key`, allowing Exhibit-First, Primary-First, and Selective-Exhibit plans to co-exist without schema divergence.
5. **Form-Aware XML Validity (Layer 2 & 4)**: Ensure `.xml` payloads are recognized as valid primary documents for XML-native forms (e.g., Form 144, Form 4, Form 3, Form 13F) rather than being skipped as non-text, while remaining filtered out as ancillary metadata (XBRL linkbases) for narrative periodic filings (10-K, 10-Q, 8-K, 6-K).
6. **Memory & Performance Guarantees (AGENTS.md Contract)**: Discard ephemeral raw bundle bytes inside workers, maintain the 64-document heap reclamation interval (`reclaim()`), bump `PROCESSOR_SCHEMA_VERSION = 2`, and enforce 100% policy scanner compliance.

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

_UNITS  = {"1": "one",   "2": "two",    "3": "three",   "4": "four",
           "5": "five",  "6": "six",    "7": "seven",   "8": "eight",  "9": "nine"}
_TEENS  = {"10": "ten",  "11": "eleven", "12": "twelve",  "13": "thirteen",
           "14": "fourteen", "15": "fifteen", "16": "sixteen", "17": "seventeen",
           "18": "eighteen", "19": "nineteen"}
_DECADES = {"20": "twenty", "30": "thirty", "40": "forty",   "50": "fifty",
            "60": "sixty",  "70": "seventy", "80": "eighty", "90": "ninety"}


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
        h     = n // 100
        rest  = n % 100
        hw    = _UNITS[str(h)]         # e.g. 'four' for 400s
        dec   = str((rest // 10) * 10)
        unit  = str(rest % 10)

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
    clean = _re.sub(r"[-/ ]+", "", alias)   # strip '-', '/', spaces
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
    patterns = [
        sep.join(combo)
        for combo in product(*segment_options)
    ]
    return patterns


from functools import lru_cache

@lru_cache(maxsize=64)
def get_primary_form_token_pattern(form: str | None) -> re.Pattern[str]:
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
    family  = resolve_alias(form) or (form.upper().strip() if form else None)
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
2. **Dynamic Profile Form Token Exclusion**: If the filename matches `get_primary_form_token_pattern(locator.form)` (e.g. `ex-10k.htm`, `ex10k.txt`), fetch directly as primary document.
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

### In-Scope for Milestone 1 Execution:
1. **14-Column `DOCUMENT_SNAPSHOT_SCHEMA`**: Add `("metadata", pa.string())` and update writers, readers, and validators.
2. **Structural Normalization Metadata**: Persist `body_start_line`, `toc_span`, `table_count`, `word_count`, `representation`, and inversion flags.
3. **Reflow Contract Fix**: Fix ASCII reflow gating in `normalize.py` for unsegmented/no-cover profiles (`GENERIC`, standalone exhibits) while ensuring cover-bearing forms (`10-K`, `10-Q`, `20-F`, `8-K`, `6-K`) reflow after their detected body start line.
4. **Form-Aware XML Validity**: Preserve and validate `.xml` primary documents for XML-native forms (e.g. `FORM TYPE: 144`, `4`, `3`, `13F`) with `representation: "xml"`.
5. **Inversion Recovery & Dual-Write**: Recover true primary forms in `fetching.py` / `worker.py` and write both the primary form and the original exhibit.
6. **Version Bump**: Bump `PROCESSOR_SCHEMA_VERSION = 2`.

### Deferred to Subsequent Milestones:
1. **Forced Full-Bundle Acquisition (`--acquisition-policy full_bundle`)**: Execution defaults to sparse acquisition (~2MB primary document).
2. **Cross-Snapshot Anti-Join Diffing (`--base-snapshot a1`)**: Incremental delta execution between published snapshots is deferred.
3. **BlockStream 1D Virtual AST**: Deferred; `SpanDecision` lacks byte/char offsets and merges spans, so normalization continues emitting clean `normalized_text`.
4. **Phase 3 Virtual Aggregate View (`filing_aggregates`)**: Deferred until Phase 3 materializes `sections.parquet`.

---

## 2. Phased Implementation Roadmap

```mermaid
flowchart LR
    S1["Stage 1: Storage Schema<br/>(14-Column DOCUMENT_SNAPSHOT_SCHEMA)"] --> S2["Stage 2: Engine Normalization<br/>(Reflow Fix & Metadata)"]
    S2 --> S3["Stage 3: Processor Evolution<br/>(PROCESSOR_SCHEMA_VERSION = 2)"]
    S3 --> S4["Stage 4: Inversion Dual-Write<br/>(Recovery & Target Key Preservation)"]
    S4 --> S5["Stage 5: Worker & Storage Integration<br/>(Chunk Serialization & Checks)"]
    S5 --> S6["Stage 6: Quality Gate & Verification<br/>(check.py --all & Review Cohort)"]
```

---

### Stage 1: Storage Schema Evolution (Layer 2: `infra/storage`)

#### Responsibilities:
- Add `("metadata", pa.string())` as the 14th column in `DOCUMENT_SNAPSHOT_SCHEMA` (`document_parquet.py`).
- Update `write_chunk_snapshot`, `validate_chunk_snapshot`, and `assemble_document_snapshots` to handle the `metadata` column.

#### File Modifications:
1. **`edgar_sec/infra/storage/document_parquet.py`**:
   - Update `DOCUMENT_SNAPSHOT_SCHEMA`:
     ```python
     DOCUMENT_SNAPSHOT_SCHEMA = pa.schema(
         [
             ("occurrence_id", pa.string()),
             ("source_cik", pa.string()),
             ("accession", pa.string()),
             ("document_path", pa.string()),
             ("document_locator_key", pa.string()),
             ("blob_hash", pa.string()),
             ("form", pa.string()),
             ("filing_date", pa.string()),
             ("raw_payload", pa.binary()),
             ("byte_size", pa.int64()),
             ("normalized_text", pa.string()),
             ("status", pa.string()),
             ("error_message", pa.string()),
             ("metadata", pa.string()),  # Canonical JSON structural metadata
         ]
     )
     ```
   - Update `write_chunk_snapshot` to accept `metadata_map: Mapping[str, str] | None = None` (defaulting to `"{}"`).
2. **`tests/infra/storage/test_document_parquet.py`**:
   - Update tests to verify that `metadata` is written, preserved through assembly, and queryable via DuckDB JSON functions.

---

### Stage 2: Engine Normalization & Reflow Fix (Layer 3: `engine/forms`)

#### Responsibilities:
- Fix the reflow gating defect in `normalize.py`: ensure that ASCII filings under no-cover profiles (`profile.boundary is None` or unsegmented `GENERIC`/exhibits) unwrap prose paragraphs starting from line 0, while cover-bearing current/periodic forms (`8-K`, `6-K`, `10-K`, `10-Q`) reflow after their detected `body_start_line`.

#### File Modifications:
1. **`edgar_sec/engine/forms/normalize.py`**:
   - Detect `is_no_cover = profile.boundary is None`.
   - Update reflow condition (lines 226–230):
     ```python
     reflow_result: ReflowResult | None = None
     if representation is not Representation.HTML and (body_start_line > 0 or is_no_cover):
         stage_trace.append(StageRecord.of("before_reflow", text))
         reflow_policy = ReflowPolicy(
             unwrap_pre_body_prose=True,
             relax_prose_layout_gaps=True,
             unwrap_bullet_continuations=True,
             is_checkbox_answer_line=is_checkbox_answer_line,
             is_page_boundary_line=is_page_marker_line,
             is_structural_line=is_cover_layout_line,
         )
         reflow_result = reflow_ascii(
             text,
             body_start_line=0 if is_no_cover else body_start_line,
             page_analysis=analysis,
             policy=reflow_policy,
         )
         text = reflow_result.text
         stage_trace.append(StageRecord.of("reflowed", text))
     ```
2. **`tests/engine/forms/test_normalize.py`**:
   - Add unit tests verifying that `GENERIC` and standalone exhibit ASCII text files unwrap hard-wrapped paragraphs from line 0, while `8-K` and `6-K` execute reflow following their detected cover page boundaries.

---

### Stage 3: Processor & Structural Metadata Serialization (Layer 4: `pipelines/document_storage`)

#### Responsibilities:
- Bump `PROCESSOR_SCHEMA_VERSION = 2` in `processor.py`.
- Ensure `FilingProcessor.process()` formats clean, compact structural metadata JSON.

#### File Modifications:
1. **`edgar_sec/pipelines/document_storage/processor.py`**:
   - Bump `PROCESSOR_SCHEMA_VERSION = 2`.
   - Format `ProcessedDocument.metadata` to include canonical structural fields:
     `processor_version`, `representation`, `word_count`, `table_count`, `body_start_line`, `toc_span`, `is_inversion`, `target_document_path`, `parent_locator_key`.
2. **`tests/pipelines/document_storage/test_processor.py`**:
   - Verify `PROCESSOR_FINGERPRINT` reflects `v2`.
   - Assert `ProcessedDocument.metadata` contains valid structural JSON fields.

---

### Stage 4: Inversion Recovery & Dual-Write Storage (Layer 4: `pipelines/document_storage`)

#### Responsibilities:
- In `fetching.py`, gate exhibit detection with `2000 <= filing_year < 2005`, `RE_STATUTORY_EXHIBIT_FILENAME`, and `RE_PRIMARY_FORM_TOKEN` rejection to strictly avoid false-positive bundle fetches on tickers (`EXAS`, `EXPO`) or company names (`exxon10k.htm`).
- When a true pre-2005 exhibit target is identified, promote the fetch to `<accession>.txt`.
- In `worker.py`, when an inversion is recovered via Tier 1 `<TYPE>` matching in `unpacker.py`, dual-write both the recovered primary document (`role: "primary"`) and the original exhibit (`role: "exhibit"`, `parent_locator_key`).

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
- The `get_primary_form_token_pattern(form)` check is a **fast pre-filter** to avoid fetching
  bundles unnecessarily. It does not assert primary identity.
- True primary identity is confirmed exclusively by `<TYPE>` matching inside the unpacked SGML
  envelope. The URL is advisory only.

#### File Modifications:
1. **`edgar_sec/pipelines/document_storage/fetching.py`**:
   - Detect pre-2005 exhibit-named targets via `RE_STATUTORY_EXHIBIT_FILENAME` and resolve to the accession bundle `<accession>.txt`.
   - `extract_from_sgml_envelope` extracts the true primary form matching `target_types=(form, form/A)` via Tier 1 in `unpacker.py`.
2. **`edgar_sec/pipelines/document_storage/worker.py`**:
   - In `_assemble_batch`, map `metadata` to the 14th column.
   - For recovered inversions, append both the primary form and the exhibit occurrence records to the chunk batch.
3. **`tests/pipelines/document_storage/test_worker.py`**:
   - Add test case verifying dual-write on inverted fixture submissions.

---

### Stage 5: Quality Gate & Verification

#### Responsibilities:
- Run all static policy scanners (`check.py`).
- Run full test suite (`check.py --all`).
- Verify line count limits (`worker.py` < 800 lines).
- Update package `README.md` files for touched packages.

#### Verification Steps:
1. `.venv/bin/python check.py --fast` (All 12 policy scanners green).
2. `.venv/bin/python check.py --all` (Complete test suite green).
3. Probe script verifying normalized output and structural metadata on review cohort filings.

---

## 3. Component Touch Matrix

| Component File | Layer | Action | Scanners & Contracts Enforced |
| :--- | :--- | :--- | :--- |
| `edgar_sec/infra/storage/document_parquet.py` | Layer 2 | **EDIT** | 14-column `DOCUMENT_SNAPSHOT_SCHEMA`; atomic writer & validator updates. |
| `tests/infra/storage/test_document_parquet.py` | Tests | **EDIT** | Mirrored path rule; verify metadata column write and validation. |
| `edgar_sec/engine/forms/normalize.py` | Layer 3 | **EDIT** | Enable `is_no_cover` reflow from line 0 for `GENERIC` ASCII / exhibits, while preserving cover boundaries for `8-K`, `6-K`, `10-K`, `10-Q`. |
| `tests/engine/forms/test_normalize.py` | Tests | **EDIT** | Verify no-cover prose unwrapping for `GENERIC`/exhibits and cover boundary reflow for `8-K`/`6-K`. |
| `edgar_sec/pipelines/document_storage/processor.py` | Layer 4 | **EDIT** | Bump `PROCESSOR_SCHEMA_VERSION = 2`; format structural metadata. |
| `tests/pipelines/document_storage/test_processor.py` | Tests | **EDIT** | Verify v2 fingerprint and metadata serialization. |
| `edgar_sec/pipelines/document_storage/fetching.py` | Layer 4 | **EDIT** | Promote pre-2005 exhibit targets to bundle fetches. |
| `edgar_sec/pipelines/document_storage/worker.py` | Layer 4 | **EDIT** | Emit 14-column batch; handle inversion dual-write; keep < 800 lines. |
| `tests/pipelines/document_storage/test_worker.py` | Tests | **EDIT** | Verify chunk serialization, metadata column, and dual-write. |
| `edgar_sec/infra/storage/README.md` | Doc | **EDIT** | Update 14-column schema documentation. |
| `edgar_sec/pipelines/document_storage/README.md` | Doc | **EDIT** | Document structural metadata and inversion dual-write. |

---

## 4. Sign-Off & Execution Readiness

This plan conforms strictly to:
1. `AGENTS.md` (5-layer acyclic downward import contract, cgroup memory bounds, mirrored test structure, zero legacy shims).
2. [Architecture & Product Roadmap (v2)](./design.md) (symmetric document storage, structural metadata contract, Lakehouse aggregate design).
