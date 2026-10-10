# fixture_store

Layer 4 acquisition subpackage for immutable response-fixture evidence.

## Purpose

The fixture store persists exact S9 response evidence in SQLite for offline inspection and replay. The fixture CLI and operator use its creation, append, discovery, and case-replay services; captured bodies remain replay evidence, not published snapshot payloads.

## Contracts

- **Immutable evidence**: Existing fixture IDs are not recreated, and capture/case records and response BLOBs cannot be replaced.
- **Verified streaming**: Responses are Zstandard-compressed on append and replayed incrementally with stored and original size/digest checks.
- **Exact capture identity**: Capture requires a run, work-order target, and exact attempt; only retained successful direct bodies and bodyless failed attempts are supported.
- **Metadata-only listing**: Listing streams case metadata without selecting, decompressing, or hashing response BLOBs; fixture open still performs SQLite integrity and foreign-key checks.
- **Caller-owned replay output**: Replay resolves an exact fixture/capture/target, verifies evidence, and writes acquired output only to a new explicit path.

## Deliberate gaps

- **Complete lazy-index and bundle capture**: Post-run state does not retain all source/index response evidence, so exact-form lazy-index and acquired bundle attempts are refused.
- **Managed S10 replay handoff**: Replay writes a caller-selected file; no managed durable staging, consumption receipt, or S10 handoff API exists.
- **Snapshot payload role**: Fixture BLOBs are evidence only, not S11 binary/text payload relations or a durable production body store.
