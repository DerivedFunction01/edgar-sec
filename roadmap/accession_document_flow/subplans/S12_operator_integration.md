# S12 — Operator Integration and End-to-End Quality Gate

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S12**.
- Status: inventory's split lifecycle CLI/operator is implemented; the cross-stage
  vertical verification gate remains design-only.
- Depends on: S1–S11 public contracts, including the command-oriented S9 contracts
  under [document_acquisition](document_acquisition/cli_inventory.md).
- Non-blocking: the integrated cross-stage operator and `document_storage`
  decommissioning. Stage-owned S6 CLI/operator work belongs to S6.

## Current tracked-code audit (2026-10-09)

- **Status: inventory lifecycle and stage-local planning commands exist; the S12 cross-stage surface and offline vertical gate are not implemented.** Inventory project/run/status/publish/query/review and S6 plan/inspect/status commands are tracked; there is no integrated `documents plan` command or fixture-driven plan-to-acquisition-to-processing-to-vacuum-to-review run matching this contract.
- **Evidence:** [`document_inventory/cli.py`](../../../edgar_sec/pipelines/document_inventory/cli.py) registers inventory commands. [`document_planning/cli.py`](../../../edgar_sec/pipelines/document_planning/cli.py) owns stage-local S6 commands, while `document_storage` retains a separate CLI and tests.
- **Next step:** defer the vertical integration test until S9 and S10 replacement APIs are implemented; then wire explicit artifact IDs and add the zero-network, no-payload-write end-to-end fixture gate before any legacy decommissioning.

## Objective

Expose a small CLI for inventory query/publication, S8 vacuum, inventory-backed or catalog-direct target planning, and review. Prove the pipeline using only committed/local fixtures, with no SEC requests and no durable payload writes.

## CLI contracts

Commands operate on explicit immutable artifact IDs. `current` is accepted only where a read or compare-and-publish operation is intended. Summaries are machine-readable JSON on stdout; diagnostics go to stderr. A nonzero exit code means a selected operation failed or any selected case failed.

```text
inventory query --snapshot <id|current> --accession <accession>
inventory query --snapshot <id|current> --accession <accession>
inventory query --snapshot <id|current> --form <form>
inventory query --snapshot <id|current> --filing-cik <cik>
inventory query --snapshot <id|current> --source-cik <cik>
inventory query --snapshot <id|current> --form <form> [--filing-cik <cik>] [--source-cik <cik>]
inventory vacuum --snapshot <snapshot-id|current> --retention <policy-id>

documents plan --catalog-plan <plan-id> [--inventory <snapshot-id|current>] --profile-id <id>

inventory fixture fill --catalog-plan <plan-id> --fixture <fixture-id>
inventory project --catalog-plan <plan-id>
inventory run --run-id <run-id>
inventory status [--run-id <run-id>]
inventory publish --run-id <run-id>
inventory review-artifacts --fixture <fixture-id> --output <dir>
inventory review --base <dir> --new <dir>
inventory inspect --snapshot <id|current> [--accession <accession>]
```

Until S12 is implemented, S6 is available through `python run.py planning plan`,
`planning inspect`, and `planning status`. The integrated `documents plan` spelling
above remains a future S12 command, not a launcher alias.

The S6 plan operation requires a catalog plan for scope and accepts an optional inventory snapshot for document evidence. The catalog plan determines selected accessions; the optional snapshot is the sole locator source when present. Missing snapshot accessions are `unresolved` / `accession_not_indexed`, never catalog-path fallback. Without a snapshot, S6 accepts only primary-only profiles and emits `catalog_direct` provenance. Both modes produce the same target-plan schema and pin the catalog plan plus the optional snapshot. `catalog_direct` is a provenance value, not a status or a synthetic inventory row.

`inventory query --filing-cik` uses the CIK encoded in the accession prefix;
`--source-cik` uses the separate S5 catalog/cohort relationship index. These are
not interchangeable, and the latter is not a verified legal co-filer list.
`inventory vacuum` requires an explicit retention policy and a base equal to
`current`; a stale snapshot ID refuses without moving the pointer. Vacuum/purge
never triggers network work.

S12 does not define the stage-owned production acquisition CLI; that belongs to S9's
command contracts. Acquisition and processing run from explicit S9 work orders and
fixture replay. The S6 package-local operator is implemented by the S6 pipeline; an
integrated operator that moves among inventory, planning, acquisition, processing,
and review remains a later S12 decision.

## Summary schemas

Every command emits a versioned summary with `command`, `schema_version`, `input_ids`, `status`, and typed counts. Counts remain stage-specific rather than coercing distinct outcomes into one vocabulary:

- Inventory: candidate accessions, known/new accessions, pages fetched/reused, source-CIK edges added, entries published, `fresh`/`reused` snapshot status.
- Target planning: rows by S6 `status` and `source_origin`, plus plan and pinned source IDs.
- Acquisition: executable/skipped targets and `acquired`, `not_filed`, `ambiguous`, `failed` counts, separated by live SEC vs fixture replay.
- Processing: verbatim-text passthrough, normalized text, validated XML, binary,
  unrecognized, and failed counts. Raw HTML remains source evidence; XML aliases its
  source digest, and PDF has no derived representation.
- Vacuum: source/compacted snapshot IDs, counts and logical fingerprints before/after, parity status, retained/pruned part counts.
- Review: selected, succeeded, failed cases and output manifest path.

## Minimal offline vertical run

The quality-gate integration fixture performs these stages in a temporary artifact root:

1. **Project cohort (S1):** read a small committed catalog-plan fixture, including an accession whose prefix `filing_cik` differs from its contributing `source_cik`, and verify one work item per accession with all source-CIK relations retained.
2. **Replay index pages (S2):** select committed `-index.html` fixture responses. No live capture or SEC call is allowed in this run.
3. **Parse and publish (S4/S5):** run the bounded worker path using the fixture transport, publish an annual-partition snapshot, and verify manifest inheritance, accession-scoped `scoped_mask` metadata, and atomic `current` update. A refresh test must show the new tip hides prior entries while the old named tip still returns them; no direct prior-entry-ID map is required.
4. **Query (S5):** compare accession, form/date, filing-CIK, and source-CIK results with expected rows; instrument the reader to prove DuckDB query execution prunes non-matching Parquet parts using `(key_min, key_max)` manifest metadata and row-group footer statistics, and keeps the CIK meanings distinct.
5. **Plan (S6):** create catalog-only and catalog-plus-inventory plans from local fixtures. Assert identical target schema and catalog accession scope, primary-only refusal without a snapshot, index-only locator use with a snapshot, `accession_not_indexed` independent of optionality, distinct `source_origin`, zero HTTP, and no inventory mutation.
6. **Acquire (S9):** replay direct-URL and bundle-sequence acquisition cases from an [acquisition fixture](document_acquisition/fixtures/index.md). Verify body/source/selected digests, exact sequence, and zero HTTP.
7. **Process (S10):** process fixture ASCII `.txt`, HTML/iXBRL, standalone XML, and binary/PDF cases. Verify text passthrough digest identity, raw-source versus normalized-HTML identities, XML source/representation aliasing, deferred PDF extraction, processor fingerprint, and retention of payload staging until S11 publication or explicit discard.
8. **Publish (S11):** publish the completed acquisition run and verify separate binary/text Parquet payload relations join to target/physical-slot evidence by digest; check Zstandard Parquet compression, pointer-last recovery, read-back hashes, and transient cleanup only after the receipt.
9. **Vacuum (S8):** compact the inventory snapshot under a test retention policy, compare its logical fingerprint and canonical query results, and prove an explicitly tagged old tip remains readable. An S6 target-plan reference alone is not a DAG retention root. A stale/concurrent pointer cannot be overwritten.
10. **Review (S7):** compare two parser runs over the same fixture and two target plans over pinned inputs; verify identity-keyed diffs, inert HTML, and empty-destination refusal.

The run asserts zero network calls, zero `document_storage` imports in new S9/S10 paths, no payload fields in inventory/target-plan Parquet, and cleanup of transient staging only after publication adoption or explicit discard.

## Quality gate

- Mirrored offline tests cover each new module and package boundary.
- `check.py` smart mode and `check.py --fast` pass; policy scanners confirm layer boundaries, resource-derived concurrency, and no `document_storage` imports from replacement modules. Existing legacy package/tests remain until the separate deletion gate.
- CLI invalid IDs, malformed manifests, conflicting/stale snapshots, unsupported target statuses, and non-empty review destinations fail explicitly.
- The default task does not run `check.py --all`; use the full unconditional suite only when explicitly requested.
- Package/layer/root README layout tables are updated when new production packages or commands are implemented. Adding the streaming SGML engine module also updates its package README and mirrored tests.

## Replacement boundary

S12 demonstrates replacement behavior but does not cut over or delete `document_storage`. Removal is the intended end state and has a separate post-S12 approval gate after the S11 payload store is implemented, S9/S10 parity is established, every legacy behavior is replaced or explicitly accepted as omitted, consumers are migrated, and rollback/artifact-retention plans are verified. The decommission change removes old CLI registration and updates root/layer/package README layouts and storage-path documentation; it also removes or rewrites tracked links to retired modules and deletes obsolete package docs/tests only after no consumers or fixtures depend on them.

## Acceptance criteria

The CLI surface matches S5/S6/S8, the offline vertical run exercises fixture-to-query-to-plan-to-acquisition-to-processing-to-vacuum-to-review, all source boundaries remain explicit, and no durable payload schema or legacy decommissioning is smuggled into the integration milestone.
