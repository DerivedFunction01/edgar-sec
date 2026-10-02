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
- In `fetching.py`, when a pre-2005 target link points to an exhibit, promote the fetch to `<accession>.txt`.
- In `worker.py`, when an inversion is recovered, dual-write both the recovered primary document (`role: "primary"`) and the original exhibit (`role: "exhibit"`, `parent_locator_key`).

#### File Modifications:
1. **`edgar_sec/pipelines/document_storage/fetching.py`**:
   - Detect pre-2005 exhibit-named targets and resolve to the accession bundle `<accession>.txt`.
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
