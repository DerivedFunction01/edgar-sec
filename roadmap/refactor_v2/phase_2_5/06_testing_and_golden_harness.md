# Phase 2.5 — Sub-Plan 06: Testing & Visual Review Harness

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Scope:** Review harness (`python run.py documents review`), pinned normalization goldens, and non-regression suites. **M6.3/M6.4 are deferred** — see §5.  
> **Source Grounding:** `.v1/phases/025_webpage_storage/tools/build_document_review_artifacts.py`, `.v1/defs/tests/`

---

## 1. Objectives & Pragmatic Simplification

Because Phase 2.5 normalizes multi-megabyte filings across three distinct eras (1990s ASCII, 2000s HTML, 2010s+ iXBRL), developers need immediate, visible feedback when changing algorithms:

1. **Review Tooling**: Rebuild the one tool that was actively used in `.v1`
   (`build_document_review_artifacts.py`) into two clean commands
   (`python run.py documents review-artifacts` and `... review`). It reads a
   **fixture**, not a published snapshot, and emits a bounded set of
   self-contained review bundles plus a manifest.

   Fixture-only is a deliberate design constraint, not a shortcut
   (`review_artifacts.py:8-15`): "There is no plan, no chunk, no checkpoint, no
   Parquet, and no published snapshot, because a review run is evidence about
   *this* code on *these* documents." A review run that could not be reproduced
   from a fixture alone would show what the snapshot did rather than what the
   edit did. Selection is deterministic and limitable, which is what makes a run
   diffable against a sibling run.
2. **Plain-Text Golden Archetypes**: Eliminate the speculative and never-built Parquet corpus promotion ceremony (`promote_document_corpus.py`, `promote_document_expectations.py`). Instead, commit 5–10 real historical archetype filings directly as plain files under `tests/fixtures/archetypes/` (1995 unformatted ASCII JNJ, 2005 HTML Apple, 2023 complex table Berkshire).
3. **Instant Automated Pytest Gate**: Archetype regressions run in `< 0.5s` via standard `pytest tests/engine/test_normalization_goldens.py`. If an algorithm change scrambles tables or alters reflow boundaries, pytest and `git diff` surface the exact character drift immediately.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Action |
| :--- | ---: | :--- | :--- |
| `phases/025/.../tools/build_document_review_artifacts.py` | 153 | `pipelines/document_storage/review_artifacts.py` | **REDESIGNED & PRESERVED**: source-first review bundles rendered from a fixture, not from a published snapshot. Reached via `python run.py documents review-artifacts`. |
| `phases/025/.../testing/review.py` | 290 | `pipelines/document_storage/review.py` | Comparison half: `compare_review_runs` diffs two rendered runs. **Not** `engine/document/review_bundle.py`, which was never created. |
| `defs/tests/test_reflow.py` | 420 | `tests/engine/reflow/test_reflow.py` | **PRESERVED**: strict whitespace, bullet splitting, and line rewrap regression suite. |
| `defs/tests/test_cover_checkmark_inference.py` | 380 | `tests/engine/forms/checkmarks/{test_solver_core,test_yesno}.py` + `tests/engine/forms/cover/` | **PRESERVED as a split suite**: the solver core and Yes/No inference ship as two files, and the cover boundary/body/closing contracts have their own suite. There is no `tests/engine/forms/test_cover_checkmark.py`. |
| `defs/tests/test_cas_concurrency.py` | 290 | *NOT PORTED* | No `edgar_sec/infra/storage/cas/` module and no `tests/infra/storage/cas/` test exist — both directories are empty and untracked. The concurrency contract this suite verified has no v2 subject. |
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
# Render one review run from a fixture:
python run.py documents review-artifacts --fixture <fixture-id> --limit 100

# Then compare two runs:
python run.py documents review --base <run-a> --new <run-b>
```

> [!IMPORTANT]
> `documents review` is the **comparison** command and requires both `--base` and
> `--new`. It does not read a published snapshot and it takes no `--limit`. An
> earlier version of this section showed `documents review --limit 20 --json`,
> which is not a valid invocation: `python run.py documents review --limit 20`
> exits with `the following arguments are required: --base, --new`. Generation and
> comparison are two commands, and they are the two that ship.

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

### 3.2 Normalization Goldens (`tests/fixtures/document_storage/`)

> [!NOTE]
> The original design here was `tests/fixtures/archetypes/` holding 5-10 *real*
> historical filings as `source.txt`/`expected.txt` pairs. That is M6.3 and it is
> **deferred** — see §5. What ships instead is two committed synthetic goldens.

```text
tests/fixtures/document_storage/
├── annual_10k_normalization.json   # ASCII path: page policy, cover, body anchor,
│                                  #   closing span, reflow, evaluator verdict
└── annual_10k_html.json            # HTML path, incl. <TABLE> byte preservation
```

#### The Automated Pytest Suite (`tests/engine/forms/test_normalization_goldens.py`)

```python
def _observed(data: dict[str, Any]) -> dict[str, Any]:
    """Run the chain and report everything the golden pins."""
    result = normalize_document(data["source_text"], form=data["form"])
    return {
        "representation": result.representation,
        "cover_boundary_method": result.cover_boundary.method.value,
        "body_anchor_type": None if result.body_start is None else result.body_start.anchor_type,
        "decision_action": get_plugin(data["form"]).evaluator(result.text).action.value,
        "page_marker_count": len(result.page_analysis.markers),
        "word_count": len(result.text.split()),
        "stage_order": [entry["stage"] for entry in result.stage_trace],
        "table_survives": "<TABLE>" in result.text,
        "no_sentinels_leaked": "__SEC_TBL_" not in result.text,
    }

def test_normalization_golden(name: str) -> None:
    data = _load(name)
    assert _observed(data) == data["expectations"]
```

> [!IMPORTANT]
> **These goldens do not compare the normalized text itself.** They compare a
> 20-field projection of the chain's *decisions* — boundaries, anchors, counts,
> stage order, and two table invariants. `word_count` is the only field that
> touches the text, and it is an integer. The original design's
> `assert normalized.text == expected_text` character-for-character comparison is
> **not** what ships, which is exactly the hole
> [Plan 07](07_end_to_end_normalized_text_parity.md) exists to close.
>
> A consequence worth stating plainly: a golden can stay green while the
> normalized text drifts within the same word count. That is not a defect in the
> test; it is the scope the test was written to cover.

---

## 4. Milestone Checklist & Verification

- [x] **M6.1**: review bundles render from a fixture and diff pairwise
  (`review_artifacts.py`, `review.py`; 14 + 13 tests). **Not** at
  `engine/document/review_bundle.py` — that module was never created, and the two
  commands are not a single one.
- [x] **M6.2**: `python run.py documents {review,review-artifacts}` wired through
  the root launcher, with a phase-local menu when no subcommand is given.
- [ ] **M6.3 (deferred)**: Populate `tests/fixtures/archetypes/` with sanitized real-world historical filings.
- [x] **M6.4**: `tests/engine/forms/test_normalization_goldens.py` runs in `< 0.5s`
  against two committed synthetic goldens. **Not** at
  `tests/engine/test_normalization_goldens.py`.
- [x] **M6.5**: reflow and cover-constraint regression suites ported
  (`tests/engine/reflow/test_reflow.py`, `tests/engine/forms/checkmarks/`,
  `tests/engine/forms/cover/`). The v1 CAS-concurrency suite was **not** ported —
  it has no v2 subject.
- [x] **M6.6**: full quality gate green — 2,143 tests pass, all 12 registered
  policy scanners clean (`check.py`).
- [ ] **M6.7 (open)**: six assertion holes in the review artifact suite. The
  `.analysis.json` content (`bounded_analysis`'s capped `table_geometries`,
  `stage_trace`, and dropped `source_text`) is never asserted — the file is written
  and never read. The `ProcessPoolExecutor` branch (`review_artifacts.py:499-514`)
  never executes, because all six render calls in the test pass `workers=1`.
  `new_review_run_id` has no test at all.


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
