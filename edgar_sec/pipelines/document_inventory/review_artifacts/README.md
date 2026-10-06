# Parser review artifacts

Builds offline, parser-fingerprinted evidence from captured index-page fixtures.

| Module | Responsibility |
|---|---|
| `builder.py` | Bounded case selection, parsing, output, and manifest commit |
| `sanitizer.py` | Structural inert HTML reconstruction |
| `paths.py` | Review-run and response-case output layout |
| `models.py` | Review run summary records |

## Contracts

Each captured response is digest-checked and processed independently. Source previews
are rebuilt without source attributes or active/resource subtrees. Failed pages retain
status and diagnostics and never receive an `entries.csv`. Case output is atomically
renamed, and manifest rows are committed in deterministic selection order.

## Public surface

Use `build_review_artifacts` from `builder.py`; package imports do not re-export child
symbols. It makes no network requests and does not mutate fixture stores.

## Command surface

`inventory review-artifacts` is wired by the document-inventory operator.

## Mirrored tests

`tests/pipelines/document_inventory/review_artifacts/`

## Deliberate gaps

Parser-run diffing and review of snapshot/acquisition outputs remain downstream work.
