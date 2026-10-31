# `edgar_sec/infra/storage/cohort`

This package owns shared CIK datasets, published family-index pointers, their
catalog, official-source lifecycle, and set/query operations. Dataset paths
persisted in SQLite are relative to the configured `cohorts_root`.

## Contracts

- Cohort directories and persisted dataset paths cannot resolve outside
  `cohorts_root`.
- SQLite connections use WAL mode, foreign keys, and normal synchronous mode;
  fresh catalog files use 8192-byte pages.
- `cohorts.sqlite` owns cohort metadata, including the schema version and origin
  JSON. Published cohort directories contain `ciks.parquet`; detached directories
  also carry the `.detached` retention marker.
- The active family-index pointer is keyed by its universe cohort and records the
  immutable assignment path and digest. Registration refuses noncanonical IDs,
  paths, missing files, and digest mismatches.
- Official-source identity records retain the raw payload digest and deterministic
  snapshot ID in catalog provenance; refreshes do not copy raw payloads into storage.
- Generic cohort identity is `c-` plus the first 16 lowercase hexadecimal
  characters of the CIK-roster SHA-256. Official-source identity instead uses
  the first 16 characters of its validated full `source_snapshot_id` SHA-256;
  each record still stores the CIK-roster digest independently. Published
  dataset bytes are verified against their recorded digest.
- A CIK is the membership key; datasets contain each CIK once. Intake chooses
  the first non-empty trimmed name in input order. Union and intersection prefer
  the left operand's non-empty name, then the right; callers put the authoritative
  source first. A name-less row remains blank unless the other operand supplies a
  name.
- A different dataset payload for an existing cohort identity is rejected.
  Official source snapshots with the same CIK set but changed names remain
  separate immutable records, and active source pointers target their cohort IDs.
- Active source pointers accept only pinned official snapshots for their source;
  the reserved `universe` and `tickers` identifiers resolve those pointers.
- Staging directories are siblings of final cohort directories, allowing an
  atomic directory rename on the same filesystem. Failed catalog registration
  removes the unpublished catalog entry's final directory.
- Deletion refuses pinned or active-source cohorts; workspace alias references
  require explicit force, which removes those aliases. `--keep-dataset` records
  the retained path and digest so orphan cleanup preserves it until explicit removal.
- Maintenance uses the publication lock and the existing catalog without schema
  initialization or workspace-session cleanup. Doctor is read-only; maintenance
  does not inspect or modify workspace aliases.
- Doctor checks catalog and active family-index checksums, Parquet readability,
  detached retention records, orphan cohort directories, and staging leases.
- Missing datasets referenced by workspace variables fail lazily during variable
  evaluation with `CohortNotFoundError`.

## Deliberate Gaps

- Family-index generation belongs to the cohort pipeline. Storage records its
  active immutable artifact; family-grouped sampling still requires the caller
  to supply an explicit assignment path.
- Existing on-disk `cohort.json` files are left in place but are not migrated or
  consulted; SQLite remains authoritative.
- Historical raw SEC payload files under `source_snapshots/` remain until the
  explicit `--clean-raw-snapshots` action; refreshes no longer write new copies.
- No cleanup is scheduled at process startup. Detached datasets remain until
  `--clean-detached` is explicitly selected.
