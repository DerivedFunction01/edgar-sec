# `edgar_sec.pipelines.document_inventory.snapshot.query`

## Purpose

Own the read surfaces over published snapshots: the high-level query
adapter executing range-pruned point lookups against active virtual views,
and inspection of one immutable snapshot through its pinned DAG lineage.

## Contracts

- **Reads are immutable**: callers may pin a snapshot ID; otherwise the
  active branch tip is read.
- **Point lookups are range-pruned** by the compiled virtual views over
  relation parts, never full scans of a snapshot's relations.

## Deliberate gaps

None.
