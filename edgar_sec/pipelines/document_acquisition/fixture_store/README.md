# fixture_store

Layer 4 acquisition subpackage for immutable parser-body fixtures.

## Purpose

The fixture store copies the selected staged body for each acquired target from a
recorded S9 run into SQLite. Each store is pinned to a published S6 plan; parser review
materializes and verifies fixture bodies internally.

## Contracts

- **Selected body only**: Fixture BLOBs contain parser inputs, not source responses, index pages, bundle containers, or failure records.
- **Run capture**: Fill discovers and captures all acquired selected bodies in a validated run; target and attempt identifiers are stored as provenance, not operator inputs.
- **Rewrite-only format**: Schema v2 rejects the previous response-group format without migration or compatibility behavior.
- **Verified streaming**: Selected bodies are Zstandard-compressed on append and materialized incrementally with stored and original size/digest checks.
- **Plan pin**: Fixture identity records the published S6 plan ID, schema version, and canonical digest; fills from another plan are refused.
- **Run-scoped capture identity**: One capture groups the selected bodies from a run; immutable case and body records cannot be replaced.
- **Offline parser boundary**: Review generation parses verified fixture bodies using current acquisition-engine handlers without source-run processing outputs.
- **Metadata-only listing**: Listing streams case metadata without selecting, decompressing, or hashing body BLOBs; fixture open still validates SQLite integrity and foreign keys.

## Deliberate gaps

- **Response history**: Source-response groups and failed acquisition attempts remain in run evidence and are not copied into parser fixtures.
- **Snapshot payload role**: Fixture BLOBs are review inputs, not production binary/text payload relations or a durable publisher body store.
