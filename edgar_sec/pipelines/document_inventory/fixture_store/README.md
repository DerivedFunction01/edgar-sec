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

Captured response bytes are compressed only at rest and verified after replay. Fills
reuse successful accession pages while recording each new cohort membership. Failed
pages remain retryable; interrupted and partial fixtures remain discoverable. The
manifest records source-plan provenance but does not hash the mutable database.
Fixtures live at `{artifacts_root}/document_inventory/fixtures/<fixture_id>/`.
Their `manifest.json` uses the shared foundation envelope for identity, version,
storage path, and timestamps; store version, capture state, counts, and source-plan
contributions live under `details`.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

The inventory operator owns fixture create, fill, and list commands.

## Deliberate gaps

Fixture refresh of an already successful page is not exposed; capture reuses the
recorded response until a separate review decision defines refresh semantics.
