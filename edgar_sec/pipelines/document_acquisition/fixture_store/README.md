# fixture_store

Layer 4 acquisition subpackage for immutable response-fixture evidence.

## Purpose

The fixture store persists exact S9 response evidence in SQLite for offline review.
Each new store is pinned to a published S6 plan. Review generation verifies captured
body bytes internally; the console does not export raw bodies to caller-selected paths.

## Contracts

- **Immutable evidence**: Existing fixture IDs are not recreated, and capture/case records and response BLOBs cannot be replaced.
- **Rewrite-only format**: The new store format has no legacy reader, migration, or compatibility path.
- **Verified streaming**: Responses are Zstandard-compressed on append and materialized incrementally with stored and original size/digest checks.
- **Plan pin**: Fixture identity records the published S6 plan ID, schema version, and canonical digest; fills must match that plan.
- **Exact capture identity**: Capture requires a run, work-order target, and exact attempt; only retained successful direct bodies and bodyless failed attempts are supported.
- **Metadata-only listing**: Listing streams case metadata without selecting, decompressing, or hashing response BLOBs; fixture open still performs SQLite integrity and foreign-key checks.
- **Internal verification**: Review generation materializes selected bodies only in temporary space and does not mutate fixture records.

## Deliberate gaps

- **Complete lazy-index and bundle capture**: Post-run state does not retain all source/index response evidence, so exact-form lazy-index and acquired bundle attempts are refused.
- **Managed payload store**: Fixture BLOBs are not the processing-result store; review generation reuses the source run's staged body and S10 result.
- **Snapshot payload role**: Fixture BLOBs are evidence only, not S11 binary/text payload relations or a durable production body store.
