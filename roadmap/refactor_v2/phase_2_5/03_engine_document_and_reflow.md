# Phase 2.5 — Sub-Plan 03: Engine Document Parser & Conservative Reflow

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Layer Focus:** Layer 3 (`engine/document/`, `engine/reflow/`)  
> **Source Grounding:** `.v1/defs/sec_documents/preprocessor.py`, `.v1/defs/text/html.py`, `.v1/defs/text/page_markers.py`, `.v1/defs/text/reflow/`

---

## 1. Objectives & Architectural Role

This subsystem converts raw, unstructured SEC documents (ranging from 1990s raw ASCII to 100MB modern HTML filings) into clean, readable, normalized plain text:
1. **SGML Multi-Document Unpacking**: Unrolls compound submission bundles (`.nc`, `.txt`) into discrete typed attachments.
2. **High-Performance HTML Parsing**: Uses `selectolax` (C-based Modest engine) for sub-millisecond DOM traversal, tag unrolling, and whitespace normalization.
3. **Bounded Page-Marker Stripping**: Identifies and removes running headers, footers, and page numbers across sliding block windows without over-removing table content.
4. **Conservative ASCII Reflow**: Re-wraps artificially hard-wrapped prose while strictly protecting tabular structures and bulleted lists.
5. **Research Lab Integration**: Houses the empirical layout feature engineering and unsupervised 2D clustering lab.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Invariants |
| :--- | ---: | :--- | :--- |
| `defs/sec_documents/preprocessor.py` | 240 | `engine/document/unpacker.py` | Parses `<DOCUMENT>` tags, extracts primary document and secondary exhibits. |
| `defs/text/html.py` | 310 | `engine/document/html.py` | `selectolax` parser: strips scripts/styles, unrolls inline formatting, normalizes block tags. |
| `defs/text/page_markers.py` | 280 | `engine/document/page_markers.py` | Bounded-window running header/footer and page number detection. |
| `defs/text/reflow/context.py` | 190 | `engine/reflow/context.py` | `BlockContext`: Lazy memoization of scalar layout metrics (`cached_property`). |
| `defs/text/reflow/rules.py` | 340 | `engine/reflow/rules.py` | Rule cascades with orthogonal quorums (Macro-Grammar, Micro-Line-Wrap, Geometric Anchors). |
| `defs/text/reflow/engine.py` | 260 | `engine/reflow/engine.py` | Conservative line-rewrap algorithm preserving leading whitespace and list formatting. |
| `defs/text/reflow/tools/` | ~1,200 | *DROPPED* (Archived in `.v1`) | One-off clustering lab & Parquet feature export; rules are already calibrated in `rules.py`. |

---

## 3. Detailed Component Specifications

### 3.1. SGML Multi-Document Unpacker (`edgar_sec/engine/document/unpacker.py`)
- **Handling Multi-Document Containers**: Historical SEC submissions combine all filing exhibits into one `.txt` or `.nc` file wrapped with SGML tags.
- **Contract**:
  ```python
  @dataclass(frozen=True)
  class SgmlAttachment:
      doc_type: str        # e.g. "10-K", "EX-13", "GRAPHIC"
      filename: str        # e.g. "form10k.htm", "ex13.htm"
      description: str
      content: bytes

  def unpack_sgml_submission(raw_bytes: bytes) -> list[SgmlAttachment]: ...
  ```

### 3.2. Selectolax HTML Normalization (`edgar_sec/engine/document/html.py`)
- **Speed & Memory**: Using Python's standard `html.parser` or `lxml` on a 50MB filing takes 3–8 seconds and consumes 300MB RAM. `selectolax` (Modest engine) parses it in < 200ms with < 40MB RAM.
- **Rules**:
  - Drops `<script>`, `<style>`, `<head>`, `<xml>`, and comment nodes.
  - Converts `<br>` and `<div>` tags into standardized newlines.
  - Replaces `&nbsp;` and unicode zero-width spaces with standard ASCII space `0x20`.

### 3.3. Conservative Reflow Engine (`edgar_sec/engine/reflow/`)
- **The Core Problem**: In 1990–2000s ASCII filings, lines were hard-wrapped at 72–80 characters. Naive paragraph joining breaks ASCII tables, financial matrices, and signature blocks.
- **The Solution**: The 5 Invariants defined in `RULE_ENGINE_SPEC.md`:
  1. **Raw Scalar Invariant**: Feature extractors compute natural scalars (`possessive_count`, `right_margin_variance`), not boolean flags.
  2. **Lazy Memoization**: Computation is zero-cost until a rule actively queries a property.
  3. **Orthogonal Quorums**: Signals from orthogonal domains (Grammar, Line-Wrap, Geometry) reinforce each other.
  4. **Short-Circuiting**: Evaluation terminates immediately if a table boundary or anchor gate fails.

### 3.4. Reflow Tools & Research Lab Disposition: Radically Simplified
In `.v1`, reflow research was coupled to an elaborate ML/clustering apparatus (`clustering/`, `dataset.py`, `analysis_export.py`, `analysis_inventory.py`). In v2, this is radically simplified:

#### 1. What is Preserved in v2:
- **Specifications (`RULE_ENGINE_SPEC.md`, `HYPOTHESES.md`)**: Stored in `docs/reflow/` or `engine/reflow/` as the formal scientific reference for layout invariants and scalar threshold derivations.
- **Calibrated Production Engine (`context.py`, `rules.py`, `engine.py`)**: The deterministic 6-tier rule cascade that actually executes rewrapping in production.
- **Direct Visual Verification**: Verified via the unified developer review tool (`python run.py review`) rather than separate Parquet annotation exporters.

#### 2. What is Dropped (Archived in `.v1`):
- `clustering/` (`unsupervised.py`, `audit.py`, `dataset.py`, `experimental_registry.py`): Scikit-Learn 2D space clustering was used once to discover threshold constants; carrying over this ML training harness creates dead maintenance overhead.
- `analysis_inventory.py`, `analysis_features.py`, `analysis_records.py`, `analysis_export.py`: Complex Parquet label-exporting machinery that was never built into active pipelines.
- `clustering/context.py`: 9-line re-export shim banned by `AGENTS.md`.
- Scratch probes: `scratch/audit_rule_engine.py`, `scratch/compare_thresholds.py`, `scratch/probe_block_trace.py`, and `scratch/probe_grammar.py`.

---

## 4. Milestone Checklist & Verification

- [ ] **M3.1**: Implement `edgar_sec/engine/document/unpacker.py` and test against multi-doc SGML fixtures.
- [ ] **M3.2**: Implement `edgar_sec/engine/document/html.py` with `selectolax`.
- [ ] **M3.3**: Implement `edgar_sec/engine/document/page_markers.py` with sliding window tests.
- [ ] **M3.4**: Implement `edgar_sec/engine/reflow/context.py`, `rules.py`, and `engine.py`.
- [ ] **M3.5**: Relocate layout research tools to `edgar_sec/engine/reflow/research/`.
- [ ] **M3.6**: Verify zero regression on reflow character accuracy using `.v1/defs/tests/test_reflow.py`.
