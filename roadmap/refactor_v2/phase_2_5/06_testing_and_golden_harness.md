# Phase 2.5 — Sub-Plan 06: Testing & Visual Review Harness

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Scope:** Review harness (`python run.py documents review`), pinned normalization goldens, and non-regression suites. **M6.3/M6.4 are deferred** — see §5.  
> **Source Grounding:** `.v1/phases/025_webpage_storage/tools/build_document_review_artifacts.py`, `.v1/defs/tests/`

---

## 1. Objectives & Pragmatic Simplification

Because Phase 2.5 normalizes multi-megabyte filings across three distinct eras (1990s ASCII, 2000s HTML, 2010s+ iXBRL), developers need immediate, visible feedback when changing algorithms:

1. **Review Tooling**: Rebuild the one tool that was actively used in `.v1`
   (`build_document_review_artifacts.py`) into a clean review command
   (`python run.py documents review`). It reads a published snapshot and emits a
   bounded set of self-contained review bundles plus a manifest.

   The selection is **stratified by outcome, not sampled**. A uniform sample of a
   99.9%-clean corpus shows only clean documents, so the surprising outcomes
   (failed, missing, empty text) are filled first and the limit is spent only
   then on ordinary ones. Selection is deterministic for a given snapshot, which
   is what makes a review diffable across runs.
2. **Plain-Text Golden Archetypes**: Eliminate the speculative and never-built Parquet corpus promotion ceremony (`promote_document_corpus.py`, `promote_document_expectations.py`). Instead, commit 5–10 real historical archetype filings directly as plain files under `tests/fixtures/archetypes/` (1995 unformatted ASCII JNJ, 2005 HTML Apple, 2023 complex table Berkshire).
3. **Instant Automated Pytest Gate**: Archetype regressions run in `< 0.5s` via standard `pytest tests/engine/test_normalization_goldens.py`. If an algorithm change scrambles tables or alters reflow boundaries, pytest and `git diff` surface the exact character drift immediately.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Action |
| :--- | ---: | :--- | :--- |
| `phases/025/.../tools/build_document_review_artifacts.py` | 153 | `pipelines/document_storage/review.py` | **REDESIGNED & PRESERVED**: renders bounded, outcome-stratified review bundles from a published snapshot. Reached via `python run.py documents review`. |
| `phases/025/.../testing/review.py` | 290 | `engine/document/review_bundle.py` | Generates visual review bundles (.txt, .html, .diff, .stats.json). |
| `defs/tests/test_reflow.py` | 420 | `tests/engine/test_reflow.py` | **PRESERVED**: Strict whitespace, bullet splitting, and line rewrap regression suite. |
| `defs/tests/test_cover_checkmark_inference.py` | 380 | `tests/engine/test_cover_checkmark.py` | **PRESERVED**: Verifies quadratic penalty solver across 20+ statutory cover constraints. |
| `defs/tests/test_cas_concurrency.py` | 290 | `tests/infra/storage/test_cas_concurrency.py` | **PRESERVED**: Concurrency and lock contention verification for SQLite CAS. |
| `phases/025/.../tools/promote_document_corpus.py` | 310 | *DROPPED* (Archived in `.v1`) | Never built/populated in repository; Parquet corpus is clunky and not diffable in git. |
| `phases/025/.../tools/promote_document_expectations.py` | 140 | *DROPPED* (Archived in `.v1`) | Replaced by committed expectation files. The promotion ceremony is what was dropped. |
| `phases/025/.../tools/chunk_document_reviews.py` | 52 | *DROPPED* (Archived in `.v1`) | Dead code (20-line review splitter with 0 callers and 0 tests). |
| `phases/025/.../tools/dump_document_review_set.py` | 64 | *DROPPED* (Archived in `.v1`) | Dead code (dumped to `/tmp/`). Superseded by the review harness. |
| `phases/025/.../tools/dump_documents.py` | 130 | *DROPPED* (Archived in `.v1`) | Dead code (dumped zstd blobs to disk). Superseded by viewer. |
| `phases/025/.../tools/query_document_corpus.py` | 55 | *DROPPED* (Archived in `.v1`) | Dead code (grep wrapper). Superseded by DuckDB queries. |

---

## 3. Detailed Component Specifications

### 3.1. Review Harness (`review-artifacts` + `review`)
A lean, zero-ceremony verification tool, split so generation and comparison
are separate commands:

```bash
# Review a single filing directly:
python run.py documents review --limit 20 --json

# Render one review run from a fixture, then compare two runs:
python run.py documents review-artifacts --fixture <fixture-id> --limit 100
python run.py documents review --base <run-a> --new <run-b>
```

> [!IMPORTANT]
> This section previously described `.source.txt` / `.source.html` / `.clean.txt`
> / `.diff` / `.stats.json` under `.artifacts/review/`. **No v1 tool ever emitted
> that layout.** `build_document_review_artifacts.py` wrote
> `<doc_id>.txt`, `<doc_id>.analysis.json`, `<doc_id>.metadata.json`, and a
> conditional `<doc_id>.html`, and its `.diff` files came from a promoted
> `document_corpus_v1.parquet` with an `expected_output` column — not from
> comparing two runs. The layout below is what v2 actually implements.

#### What It Emits:
```text
.artifacts/document_storage/review-runs/<run-id>/
├── review_manifest.jsonl        # One line per document: identity, form, source and output hashes
└── cases/<doc_id>/
    ├── <doc_id>.source.txt      # The stored source bytes, verbatim
    ├── <doc_id>.txt             # The full normalized output
    ├── <doc_id>.analysis.json   # Page-marker analysis and stage trace, capped
    └── <doc_id>.html            # Sanitized source HTML, for HTML inputs only
```

`documents review --base A --new B` then writes `.artifacts/document_storage/review-runs/diff-<id>/`
containing `summary.txt`, `review_diff.json`, and per-document
`<doc_id>.diff.patch` / `<doc_id>.diff.html`. It exits 1 when differences exist.

Generation is refused into a non-empty directory: two runs sharing an output
root cannot be compared, so a code change means a new run id.

### 3.2. Normalization Goldens (`tests/fixtures/document_storage/`)

> [!NOTE]
> The original design here was `tests/fixtures/archetypes/` holding 5-10 *real*
> historical filings. That is M6.3 and it is **deferred** — see §5. What ships
> instead is described there; this section documents the committed synthetic
> goldens.
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
        f"Run 'python run.py documents review' to inspect the stored snapshot."
    )
```

---

## 4. Milestone Checklist & Verification

- [ ] **M6.1**: Implement `edgar_sec/engine/document/review_bundle.py` to generate review artifacts (`.txt`, `.html`, `.diff`, `.stats.json`).
- [x] **M6.1**: Review harness rendering bounded, outcome-stratified bundles.
- [x] **M6.2**: `python run.py documents review` wired through the root launcher.
- [ ] **M6.3 (deferred)**: Populate `tests/fixtures/archetypes/` with sanitized real-world historical filings.
- [ ] **M6.4**: Implement `tests/engine/test_normalization_goldens.py` running in `< 0.5s`.
- [ ] **M6.5**: Port regression test suites (`test_reflow.py`, `test_cover_checkmark.py`, `test_cas_concurrency.py`).
- [ ] **M6.6**: Run full quality gate (`python check.py` and `python check.py --scan`).


---

## 5. Status: M6.3 and M6.4 are deferred

M6.3 requires committing real SEC filings into the repository. That is a
sanitization, licensing, and repository-size decision, not an engineering one, so
it is deliberately not taken here. M6.4 depends on M6.3.

**What shipped instead.** Two committed **synthetic** goldens under
`tests/fixtures/document_storage/`, asserted by
`tests/engine/forms/test_normalization_goldens.py`:

| Golden | Exercises |
| :--- | :--- |
| `annual_10k_normalization.json` | The ASCII path end to end: page policy, cover boundary, structural body anchor, closing span, reflow, evaluator verdict. |
| `annual_10k_html.json` | The HTML path, including the `<TABLE>` byte-preservation invariant and the absence of leaked `__SEC_TBL_` sentinels. |

Each pins the cover boundary method and detected line, body anchor type, closing
span, evaluator decision, checkmark status, page-marker count, word count, and
**stage order**. Stage order is pinned because it is the load-bearing invariant:
reflow must not run before the boundary is detected, or the solver would be
handed a stale coordinate frame.

These catch the failure a golden exists to catch — a refactor silently moving a
boundary, dropping a stage, or changing what an evaluator concludes — offline,
deterministically, in under a second. They do **not** establish parity against
real filings. That remains open, and `roadmap/refactor_v2/parity_inventory.csv`
should be re-audited with a mutation probe before it is republished, since its
427 `NOT_STARTED` rows predate this work.
