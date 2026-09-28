# Phase 2.5 — Sub-Plan 06: Testing & Visual Review Harness

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Scope:** Developer Visual Inspection Tool (`python run.py review`), Plain-Text Archetype Goldens, and Non-Regression Test Suites  
> **Source Grounding:** `.v1/phases/025_webpage_storage/tools/build_document_review_artifacts.py`, `.v1/defs/tests/`

---

## 1. Objectives & Pragmatic Simplification

Because Phase 2.5 normalizes multi-megabyte filings across three distinct eras (1990s ASCII, 2000s HTML, 2010s+ iXBRL), developers need immediate, visible feedback when changing algorithms:

1. **Source-First Visual Review Tooling**: Rebuild the one tool that was actively used in `.v1` (`build_document_review_artifacts.py`) into a clean, standalone review command (`python run.py review`). It takes a filing or fixture directory and emits readable side-by-side bundles (`.source.txt`, `.source.html`, `.clean.txt`, `.diff`, `.stats.json`).
2. **Plain-Text Golden Archetypes**: Eliminate the speculative and never-built Parquet corpus promotion ceremony (`promote_document_corpus.py`, `promote_document_expectations.py`). Instead, commit 5–10 real historical archetype filings directly as plain files under `tests/fixtures/archetypes/` (1995 unformatted ASCII JNJ, 2005 HTML Apple, 2023 complex table Berkshire).
3. **Instant Automated Pytest Gate**: Archetype regressions run in `< 0.5s` via standard `pytest tests/engine/test_normalization_goldens.py`. If an algorithm change scrambles tables or alters reflow boundaries, pytest and `git diff` surface the exact character drift immediately.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Action |
| :--- | ---: | :--- | :--- |
| `phases/025/.../tools/build_document_review_artifacts.py` | 153 | `engine/document/review.py` | **REDESIGNED & PRESERVED**: The core visual review tool, exposed via `python run.py review`. |
| `phases/025/.../testing/review.py` | 290 | `engine/document/review_bundle.py` | Generates visual review bundles (.txt, .html, .diff, .stats.json). |
| `defs/tests/test_reflow.py` | 420 | `tests/engine/test_reflow.py` | **PRESERVED**: Strict whitespace, bullet splitting, and line rewrap regression suite. |
| `defs/tests/test_cover_checkmark_inference.py` | 380 | `tests/engine/test_cover_checkmark.py` | **PRESERVED**: Verifies quadratic penalty solver across 20+ statutory cover constraints. |
| `defs/tests/test_cas_concurrency.py` | 290 | `tests/infra/storage/test_cas_concurrency.py` | **PRESERVED**: Concurrency and lock contention verification for SQLite CAS. |
| `phases/025/.../tools/promote_document_corpus.py` | 310 | *DROPPED* (Archived in `.v1`) | Never built/populated in repository; Parquet corpus is clunky and not diffable in git. |
| `phases/025/.../tools/promote_document_expectations.py` | 140 | *DROPPED* (Archived in `.v1`) | Replaced by direct plain-text expected files in `tests/fixtures/archetypes/`. |
| `phases/025/.../tools/chunk_document_reviews.py` | 52 | *DROPPED* (Archived in `.v1`) | Dead code (20-line review splitter with 0 callers and 0 tests). |
| `phases/025/.../tools/dump_document_review_set.py` | 64 | *DROPPED* (Archived in `.v1`) | Dead code (dumped to `/tmp/`). Superseded by `python run.py review`. |
| `phases/025/.../tools/dump_documents.py` | 130 | *DROPPED* (Archived in `.v1`) | Dead code (dumped zstd blobs to disk). Superseded by viewer. |
| `phases/025/.../tools/query_document_corpus.py` | 55 | *DROPPED* (Archived in `.v1`) | Dead code (grep wrapper). Superseded by DuckDB queries. |

---

## 3. Detailed Component Specifications

### 3.1. Unified Developer Review Tool (`python run.py review`)
A lean, zero-ceremony visual verification tool:

```bash
# Review a single filing directly:
python run.py review --input path/to/filing.htm --output .artifacts/review/

# Review a test fixture batch:
python run.py review --fixture mini --output .artifacts/review/
```

#### What It Emits:
```text
.artifacts/review/<doc_id>/
├── <doc_id>.source.txt          # Raw source text
├── <doc_id>.source.html         # Sanitized source HTML for browser inspection
├── <doc_id>.clean.txt           # The normalized output text
├── <doc_id>.diff                # Character/line diff against expected golden (if available)
└── <doc_id>.stats.json          # Table counts, reflowed block counts, checkmark solver scores
```

### 3.2. Plain-Text Archetype Golden Testing (`tests/fixtures/archetypes/`)
Rather than maintaining a binary Parquet database that cannot be diffed, v2 stores 5–10 canonical filing archetypes directly as plain files:

```text
tests/fixtures/archetypes/
├── 1995_jnj_ascii/
│   ├── source.txt               # Raw 1995 unformatted ASCII 10-K
│   └── expected.txt             # Canonical normalized text (ASCII tables protected)
├── 2005_apple_html/
│   ├── source.htm               # Early 2000s HTML filing
│   └── expected.txt             # Canonical normalized text (clean paragraph rewraps)
└── 2023_berkshire_ixbrl/
    ├── source.htm               # Modern complex HTML table layout
    └── expected.txt             # Canonical normalized text (<TABLE> tagged spans)
```

#### The Automated Pytest Suite (`tests/engine/test_normalization_goldens.py`)
```python
def test_archetype_normalization(archetype_case):
    raw_content = archetype_case.source_path.read_bytes()
    expected_text = archetype_case.expected_path.read_text(encoding="utf-8")
    
    # Run full normalization engine
    normalized = normalize_document(raw_content, archetype_case.locator)
    
    # Assert character-for-character equality
    assert normalized.text == expected_text, (
        f"Normalization drifted for {archetype_case.name}. "
        f"Run 'python run.py review --input {archetype_case.source_path}' to inspect diff."
    )
```

---

## 4. Milestone Checklist & Verification

- [ ] **M6.1**: Implement `edgar_sec/engine/document/review_bundle.py` to generate review artifacts (`.txt`, `.html`, `.diff`, `.stats.json`).
- [ ] **M6.2**: Wire `python run.py review` and `python -m edgar_sec.engine.document.review`.
- [ ] **M6.3**: Populate `tests/fixtures/archetypes/` with sanitized real-world historical filings.
- [ ] **M6.4**: Implement `tests/engine/test_normalization_goldens.py` running in `< 0.5s`.
- [ ] **M6.5**: Port regression test suites (`test_reflow.py`, `test_cover_checkmark.py`, `test_cas_concurrency.py`).
- [ ] **M6.6**: Run full quality gate (`python check.py` and `python check.py --scan`).
