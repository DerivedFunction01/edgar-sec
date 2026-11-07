# feeds

Publishes the SEC structured-disclosure RSS feeds as an append-only
event ledger: the four live feeds and their monthly archives land as
one Parquet relation in a DAG store of their own, one row per accession
and source, stamped with the publishing snapshot and fetch time.

## Purpose

The ledger is the discovery record for structured disclosures. It names
filings the feeds served, with the provenance of every source that
listed each one, so a reader can join it to the catalog by accession at
read time. It is not a metadata source: nothing here writes into the
metadata DAG or manufactures canonical submission rows.

## Contracts

- **One row per accession × source**: dedupe merges provenance across
  feeds at the event level; the ledger keeps every source that listed
  an accession as its own row, so feed counts are never summed.
- **Dedupe is store-side**: each publish anti-joins its candidate rows
  against the tip's active parts in DuckDB on (accession, source); a
  batch with no new rows publishes nothing and leaves the tip unmoved.
- **Backfill streams month by month**: each month is fetched, deduped,
  and published before the next is fetched, so a long backfill holds
  one month's events, never the archive set.
- **The in-progress month is fetched uncached**: its HTTP cache rows
  are cleared before and after the fetch, so a still-filling month is
  never served from, or retained under, the archives' static posture.
  Completed months ride the static cache row.
- **Publication is CAS-guarded**: a publish names the tip it read and
  refuses to land if the branch moved underneath it.
- **Datetimes ride as ISO-8601 text**: acceptance and fetch times are
  stored as UTC ISO strings, the submissions schema's precedent, so
  ledger reads never depend on a timezone database.

## Deliberate gaps

- **No polling or schedule**: `run` and `backfill` are commands; any
  cadence wiring is a separate ruling.
- **No catalog join at write time**: the ledger stores events as
  served; joining to filings happens in readers, never here.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `backfill` | publish monthly-archive events for a month range | `--start`, `--end`, `[--artifacts]`, `[--branch]` |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `run` | fetch the live feeds and publish new ledger events | `[--feeds]`, `[--artifacts]`, `[--branch]` |
| `status` | report the ledger tip and per-source counts | `[--artifacts]`, `[--branch]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# Publish the four live feeds as the next ledger snapshot
python run.py feeds run

# Backfill the monthly archives for one quarter
python run.py feeds backfill --start 2026-07 --end 2026-09

# Report the tip and per-source counts without fetching
python run.py feeds status
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
└── feeds/
    └── snapshots/
        ├── catalog.sqlite
        └── {snapshot_id}/
            └── feed_events.parquet
```
<!-- AUTOGEN:PATHS:END -->
