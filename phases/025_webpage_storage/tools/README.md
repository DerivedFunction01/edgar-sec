# Phase 025 Document Review Tools

These tools provide the source-first document review and golden workflow for
Phase 025. The source of truth is a fixture ID; callers do not provide a raw
SQLite path.

## 1. Promote fixture documents to the corpus

The promotion command resolves the fixture through the shared runtime paths,
decompresses every `document_blobs.raw_payload`, verifies its SHA-256 digest,
and writes the corpus to:

```text
phases/025_webpage_storage/tests/fixtures/documents/
  document_corpus_v1.parquet
  manifest.json
```

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.promote_document_corpus \
  --fixture-id <fixture-id>
```

For a small diagnostic corpus, select document IDs or use a limit. A limit is
not intended to replace the full corpus promotion:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.promote_document_corpus \
  --fixture-id <fixture-id> \
  --doc-id <document-id> \
  --limit 100
```

Rows with missing or incorrect source hashes are rejected. Repair a legacy
fixture first with the temporary script described below.

## 2. Build review artifacts

Review artifacts can be generated directly from a fixture for the initial
review, or from the tracked Parquet corpus for all subsequent comparisons.
Each run contains per-document source/output/debug files and a
`review_manifest.jsonl`.

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.build_document_review_artifacts \
  --fixture-id <fixture-id> \
  --limit 100 \
  --output .artifacts/test-runs/webpage_storage/document-reviews/<run-id>
```

After corpus promotion, use the corpus path instead:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.build_document_review_artifacts \
  --corpus phases/025_webpage_storage/tests/fixtures/documents/document_corpus_v1.parquet \
  --limit 100 \
  --output .artifacts/test-runs/webpage_storage/document-reviews/<run-id>
```

Each case may contain:

```text
<document-id>.txt             source-first review bundle
<document-id>.html            sanitized visual rendering for HTML inputs
<document-id>.analysis.json   bounded pipeline/page-marker analysis
<document-id>.metadata.json   stable review metadata
```

Review runs are never regenerated in place. Choose a new `<run-id>` after a
code change.

## 3. Split into 20-document batches

The initial manual review target is 100 documents in five batches:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.chunk_document_reviews \
  .artifacts/test-runs/webpage_storage/document-reviews/<run-id>/review_manifest.jsonl \
  --output .artifacts/test-runs/webpage_storage/document-reviews/<run-id>/batches \
  --limit 100 \
  --size 20
```

Edit each batch JSONL to record `status`, `issues`, `evidence`,
`recommendation`, and `deferred`. Common issue values include:
`page_marker_preserved`, `page_marker_overremoved`, `collapsed_table`,
`financial_value_lost`, `toc_reference_removed`, `paragraph_joined`,
`paragraph_fragmented`, and `header_footer_overremoved`.

## 4. Inspect selected cases

Create one temporary review file for selected failures:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.dump_document_review_set \
  --ids-file failed-document-ids.txt \
  --output /tmp/document-review-failures.txt
```

Or select an individual case:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.dump_document_review_set \
  --id <document-id> \
  --output /tmp/document-review-one.txt
```

The command also writes per-case temporary artifacts beside the output file,
including HTML and diff files when an expected output exists.

Search the promoted corpus with:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.query_document_corpus \
  --status pending

.venv/bin/python -m phases.025_webpage_storage.tools.query_document_corpus \
  --grep "page number" \
  --show source \
  --head 80
```

## 5. Promote reviewed expectations

Promotion is explicit and never occurs during pytest. Verify the source hash,
re-run the current processor, and write the exact normalized output and stable
metadata for only the selected IDs:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.promote_document_expectations \
  --id <document-id>
```

For an IDs file:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.promote_document_expectations \
  --ids-file accepted-document-ids.txt
```

When behavior is intentionally deferred, preserve the current output as an
approved baseline and record the deferred feature:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.promote_document_expectations \
  --ids-file paragraph-healing-deferred.txt \
  --status accepted_current_behavior \
  --deferred paragraph_healing
```

Then run the golden tests:

```bash
.venv/bin/pytest phases/025_webpage_storage/tests/test_document_goldens.py
```

Expected-output divergence reports are written under the shared
`.artifacts/test-runs/` directory and include text and HTML diffs plus debug
metadata.

## Legacy fixture hash repair

`/tmp/repair_fixture_hashes.py` is a temporary migration aid for fixtures with
empty `raw_payload_sha256` values. It defaults to a dry run and only updates
empty or NULL hashes when `--apply` is supplied:

```bash
.venv/bin/python /tmp/repair_fixture_hashes.py \
  --fixture-id <fixture-id>

.venv/bin/python /tmp/repair_fixture_hashes.py \
  --fixture-id <fixture-id> \
  --apply
```

After repair, rerun corpus promotion and verify the corpus integrity test.
