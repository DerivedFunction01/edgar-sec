# S12 — Operator Integration and End-to-End Quality Gate

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S12**.
- Status: artifact-oriented CLI and vertical verification contract.
- Depends on: S1–S11 public contracts, including S9a–S9d.
- Non-blocking: interactive UX and `document_storage` decommissioning.

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

documents plan --inventory <snapshot-id|current> --profile <path>
documents plan --catalog-plan <plan-id> --profile <path>

inventory fill --catalog-plan <plan-id> --fixture <fixture-id>
inventory build --fixture <fixture-id>
inventory review-artifacts --fixture <fixture-id> --output <dir>
inventory review --base <dir> --new <dir>
inventory inspect --snapshot <id|current> [--accession <accession>]
```

`documents plan` requires exactly one source in the initial CLI: `--inventory` or `--catalog-plan`. Both produce the S6 target-plan row shape and pin their input artifact. Hybrid source precedence/deduplication is deliberately not inferred; a combined plan mode requires an explicit S6 policy before it is exposed. `catalog_direct` is a provenance value, not a status or a synthetic inventory row.

`inventory query --filing-cik` uses the CIK encoded in the accession prefix;
`--source-cik` uses the separate S5 catalog/cohort relationship index. These are
not interchangeable, and the latter is not a verified legal co-filer list.
`inventory vacuum` requires an explicit retention policy and a base equal to
`current`; a stale snapshot ID refuses without moving the pointer. Vacuum/purge
never triggers network work.

Acquisition and processing do not gain production SEC-fetch CLI commands in this stage. They run from the S9 work order and S9d fixture replay contracts; an interactive operator remains a later UX decision.

## Summary schemas

Every command emits a versioned summary with `command`, `schema_version`, `input_ids`, `status`, and typed counts. Counts remain stage-specific rather than coercing distinct outcomes into one vocabulary:

- Inventory: candidate accessions, known/new accessions, pages fetched/reused, source-CIK edges added, entries published, `fresh`/`reused` snapshot status.
- Target planning: rows by S6 `status` and `source_origin`, plus plan and pinned source IDs.
- Acquisition: executable/skipped targets and `acquired`, `not_filed`, `ambiguous`, `failed` counts, separated by live SEC vs fixture replay.
- Processing: normalized text, validated XML, binary, unrecognized, and failed counts.
- Vacuum: source/compacted snapshot IDs, counts and logical fingerprints before/after, parity status, retained/pruned part counts.
- Review: selected, succeeded, failed cases and output manifest path.

## Minimal offline vertical run

The quality-gate integration fixture performs these stages in a temporary artifact root:

1. **Project cohort (S1):** read a small committed catalog-plan fixture, including an accession whose prefix `filing_cik` differs from its contributing `source_cik`, and verify one work item per accession with all source-CIK relations retained.
2. **Replay index pages (S2):** select committed `-index.html` fixture responses. No live capture or SEC call is allowed in this run.
3. **Parse and publish (S4/S5):** run the bounded worker path using the fixture transport, publish an annual-partition snapshot, and verify manifest inheritance/tombstone metadata and atomic `current` update.
4. **Query (S5):** compare accession, form/date, filing-CIK, and source-CIK results with expected rows; instrument the reader to prove DuckDB query execution prunes non-matching Parquet parts using `(key_min, key_max)` manifest metadata and row-group footer statistics, and keeps the CIK meanings distinct.
5. **Plan (S6):** create an inventory-backed target plan and a separate catalog-direct plan from local fixtures. Assert identical target schema, distinct `source_origin`, zero HTTP, and no inventory mutation. The two source plans remain separate; this test does not imply hybrid precedence.
6. **Acquire (S9):** replay direct-URL and bundle-sequence acquisition cases from S9d. Verify body/source/selected digests, exact sequence, and zero HTTP.
7. **Process (S10):** process fixture HTML/iXBRL, standalone XML, binary/PDF, legacy `<PRE>`, and malformed-input cases. Verify route-specific outcomes, processor fingerprint, and that normalized data remains transient except for explicitly selected review output.
8. **Vacuum (S8):** compact the published snapshot under a test retention policy, compare the full logical fingerprint and canonical query results, and prove a plan-pinned old snapshot remains readable. A stale/concurrent pointer cannot be overwritten.
9. **Review (S7):** compare two parser runs over the same fixture and two target plans over pinned inputs; verify identity-keyed diffs, inert HTML, and empty-destination refusal.

The run asserts zero network calls, zero `document_storage` imports in new S9/S10 paths, no payload fields in inventory/target-plan Parquet, and cleanup of transient staging after success and injected failure.

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
