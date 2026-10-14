# fixture_store

Layer 4 acquisition subpackage for immutable parser-body fixtures.

## Purpose

The fixture store captures selected parser inputs directly from a published S6 target
plan into SQLite. It does not require an S9 run; parser review materializes and verifies
fixture bodies internally.

## Contracts

- **Selected body capture**: Fixture BLOBs contain parser inputs and any lazy-index pages used for exact-form resolution; bundle containers and failed request histories are not retained.
- **Plan capture**: Fill revalidates the pinned S6 plan and fetches its executable targets without creating run state or attempts.
- **Fill serialization**: A per-fixture exclusive lock prevents overlapping fills from issuing duplicate requests or case captures.
- **Rewrite-only format**: Schema v3 rejects older fixture formats without migration or compatibility behavior.
- **Verified streaming**: Selected bodies are Zstandard-compressed on append and materialized incrementally with stored and original size/digest checks.
- **Plan pin**: Fixture identity records the published S6 plan ID, schema version, and canonical digest; fills from another plan are refused.
- **Capture identity**: One immutable capture groups plan-selected target bodies; repeated fill skips already captured targets.
- **Lazy-index cache**: A fixture stores one verified index page per accession and reuses it for all lazy-selected targets for that accession; a bundle child must still match the indexed form.
- **Offline parser boundary**: Review generation parses verified fixture bodies using current acquisition-engine handlers without source-run processing outputs.
- **Metadata-only listing**: Listing streams case metadata without selecting, decompressing, or hashing body BLOBs; fixture open still validates SQLite integrity and foreign keys.

## Deliberate gaps

- **Response history**: Ordinary source-response groups and failed request histories are not copied into parser fixtures.
- **Snapshot payload role**: Fixture BLOBs are review inputs, not production binary/text payload relations or a durable publisher body store.
