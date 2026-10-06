# `edgar_sec.pipelines.document_inventory`

## Purpose

Project filing-cohort observations into accession-level index-page work, capture and
replay `-index.html` responses without the network, and (in later stages) publish an
immutable, queryable inventory snapshot. Layer 4: consumes published artifacts from
`filing_catalog`; imports only foundation, infra, domain, and sibling modules.

## Module layout

| Module | Responsibility |
|---|---|
| `cohort.py` | Project catalog observations into `CohortObservation`, `AccessionInventory`, and one `IndexWorkItem` per accession; validate dates/identities. |
| `index_parser.py` | Typed S3 parser contract: `IndexPageInput`, `ParsedIndexPage`, `UnrecognizedIndexPage`, `IndexParseFailure`, and `parse_html_index`. |
| `fixture_store.py` | Append-only capture-and-replay store (`index_fixtures.sqlite` + manifest): create, capture, publish, list, replay. |
| `cli.py` | Command surface (`inventory` subcommands plus interactive menu). |

## Contracts

- `project_cohort` emits one work item per accession, keyed by canonical accession; the cohort reader is offline and deterministic from a catalog snapshot or committed fixture.
- `capture_index_pages` upserts pages by `(request_url, response_sha256)`; changed responses append, failures become typed capture failures, and every source observation is recorded in `cohort_members`.
- `publish_index_fixture` finalizes the manifest with the committed database digest; `replay_index_page` opens the store read-only and refuses mismatched schema or digests.
- `parse_html_index` is a typed input/output boundary; it currently fails closed (`NotImplementedError`) pending S0 evidence to freeze parsing rules.

## Command surface

```
python run.py inventory <subcommand> [options]
  cohort        build the inventory cohort from a source
  index list    list captured index pages
  index replay  replay a captured index page
  status        report the inventory snapshot
  query         query the snapshot
  publish       publish the inventory snapshot
```

Common options: `--artifacts`, `--workers`, `--limit`, `--json`. Invoked without a
subcommand from `python run.py inventory` (no arguments), the launcher opens a narrow
interactive menu. Exit codes: 0 success, 1 error, 2 invalid usage, 130 interrupt.

## Mirrored tests

`tests/pipelines/document_inventory/`: `test_cohort.py`, `test_fixture_store.py`,
`test_index_parser.py`, `test_cli.py`.

## Deliberate gaps

- The parser body (`index_parser.py`) is not implemented; it fails closed. Table
  discovery and column-variant rules await S0's empirical audit.
- The CLI command bodies are placeholders; `inventory <subcommand>` returns 1 until
  the owning stage is implemented.
- `--workers`/`--limit` are accepted but unused until S4 execution exists.
- S5 snapshot publication, S4 worker orchestration, and S6 target planning are out of
  scope for this phase.
