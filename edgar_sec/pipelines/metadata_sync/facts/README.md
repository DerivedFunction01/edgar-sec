# `edgar_sec.pipelines.metadata_sync.facts` — Company-Facts Leg

The self-contained company-facts leg: the nightly companyfacts bulk archive
is normalized into its own DuckDB facts store and published through the
DAG as a cross-check corpus.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Bulk archive member model | [companyfacts.py](companyfacts.py) |
| Facts store ingest and local reads | [facts_store.py](facts_store.py) |
| Facts snapshot publication | [facts_publish.py](facts_publish.py) |

## Contracts

- Normalization is member-level and never mass-extracts; members are read
  per CIK through the memory-mapped index.
- Re-ingest carries unchanged members forward by member CRC; a changed
  member is replaced, and CIKs absent from the new archive are removed.
- Republishing identical content is a no-op.
- Facts reads are local: no HTTP on the read path.

## Deliberate Gaps

- The facts leg is a batch command, not a plan shape: it does not join the
  plan/run/merge machinery.
- The facts store is a cross-check corpus, not a serving source.
