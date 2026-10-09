# Index fixture store

Stores captured SEC index pages and cohort provenance for offline parser review. It
is mutable local evidence, not a published inventory snapshot.

| Module | Responsibility |
|---|---|
| `models.py` | Fixture schema and immutable capture/manifest records |
| `_db.py` | SQLite transactions, validation, and atomic manifest IO |
| `capture.py` | Fixture creation and appendable per-accession capture |
| `reader.py` | Read-only case enumeration and exact-byte replay |
| `discovery.py` | Manifest-only fixture discovery |

## Contracts

- **Compressed-at-rest, verified-on-replay**: Captured response bytes are compressed only at rest and verified after replay.
- **Page fill reuse**: Fills reuse successful accession pages while recording each new cohort membership.
- **Retryable failures**: Failed pages remain retryable.
- **Discoverable partial fixtures**: Interrupted and partial fixtures remain discoverable.
- **Manifest stores provenance only**: The manifest records source-plan provenance but does not hash the mutable database.
- **Fixtures stored at `{artifacts_root}/document_inventory/fixtures/<fixture_id>/`**: `manifest.json` uses the shared foundation envelope for identity, version, storage path, and timestamps.
- **Details sub-object**: store version, capture state, counts, and source-plan contributions.

## Usage examples

The inventory operator owns fixture create, fill, and list commands.

## Deliberate gaps

Fixture refresh of an already successful page is not exposed; capture reuses the
recorded response until a separate review decision defines refresh semantics.
