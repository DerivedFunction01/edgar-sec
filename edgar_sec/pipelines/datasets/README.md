# datasets

Imports the SEC data-research dataset vintages this codebase adopted as
cross-check oracles — the BDC, Form N-MFP, and mutual fund risk/return
(MFRR) data sets — into a versioned DuckDB store, and publishes the
store's index (vintage census plus the BDC population reference) through
a DAG of its own.

## Purpose

The adopted sets are SEC pre-extractions of filings the codebase already
parses, so nothing here is an ingest of record: the store exists so a
verification pass can compare SEC's extraction against the codebase's own
records over a panel, in the FSDS-oracle posture. The pipeline is the
datasets home later dataset items extend with their own specs.

## Contracts

- **Vintages are keyed by content hash**: a vintage label plus its
  archive SHA identify a slice; a re-posted vintage (SEC refreshes
  published files in place) loads as a new slice and never mutates the
  earlier one.
- **Loads are DuckDB-side**: TSV members are extracted to files and read
  by DuckDB (`read_csv`, all columns text); no Python code materializes
  a dataset row. The one exception is the BDC Report register (hundreds
  of rows per year), normalized in Python.
- **Columns are stored as served**: the store keeps every member column
  as text under its served name, prefixed by set, vintage, and archive
  SHA; schema drift across vintages therefore loads without adapters,
  and drift stays visible in the store instead of being normalized away.
- **`soi.tsv` is archive-only**: the BDC schedule-of-investments member
  is a wide pivot whose column set is the union of tags in the slice, so
  it is retained in the bulk archive and never loaded.
- **The BDC population is the report union**: the reference relation
  keeps every BDC Report row with its report year; the register is the
  union over the loaded years, because one year's file is a mid-year
  snapshot. Dataset-slice populations come from each vintage's own
  submission table, never from the register.
- **Publication is the index, not the data**: a publish snapshots the
  vintage census and population relations as Parquet parts through the
  DAG; the dataset tables stay in the DuckDB store the index names.
- **Verification reconciles two independent counts**: a loaded table
  passes only when its row count equals its source member's line count
  (tallied during extraction, before any load) minus its header.

## Deliberate gaps

- **No ingest of record for any set**: every adopted set duplicates
  content the XBRL engine or a structured form family already parses;
  serving dataset values as answers is not a posture this pipeline has.
- **No fact-level XBRL oracle comparison**: the verification pass
  reconciles row counts and population identity; comparing individual
  facts against the solver's per-filing answers is the review pipeline's
  pattern, adopted when a later dataset item wires it.
- **N-PORT and N-CEN are not adopted**: N-PORT's span is ~12 GB of
  quarterly ZIPs duplicating the N-PORT family for oracle-only value,
  and the N-CEN sets currently exclude schema-3.1 filings, so their
  population is incomplete as published. The Step 14 probe record
  (`.artifacts/run-logs/2026-11-08-bdc-ic-dataset-probe.md`) carries the
  evidence for both.
- **No vintage discovery**: imports name vintages explicitly; listing
  pages are not crawled, so a new vintage is an operator's act until a
  later item rules a discovery leg.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `import` | download and load vintages of one dataset set | `--set`, `--vintage`, `[--artifacts]`, `[--branch]` |
| `population` | load the BDC Report population register | `[--year]`, `[--artifacts]`, `[--branch]` |
| `publish` | publish the store index as the next DAG snapshot | `[--artifacts]`, `[--branch]` |
| `status` | report the store's vintages and the index tip | `[--artifacts]`, `[--branch]` |
| `verify` | run the oracle verification pass over the store | `[--artifacts]`, `[--branch]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# Import two BDC vintages and the BDC population register
python run.py datasets import --set bdc --vintage 2025q1 --vintage 2026_08
python run.py datasets population

# Reconcile the store against source line counts and the register
python run.py datasets verify
python run.py datasets status
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
| Artifact | Owner | Path |
| :--- | :--- | :--- |
| Datasets store | `datasets/paths.py:DatasetsPaths.store_file` | `.artifacts/datasets/datasets.duckdb` |
| Index snapshots | `datasets/paths.py:DatasetsPaths.snapshots_root` | `.artifacts/datasets/snapshots/` |
| Vintage archives | `datasets/paths.py:DatasetsPaths.bulk_archives_root` | `.artifacts/bulk_archives/` |
<!-- AUTOGEN:PATHS:END -->
