# fixture_store

Layer 4 acquisition subpackage for immutable response-fixture evidence.

## Purpose

The fixture store records replayable S9 HTTP response bytes in SQLite so offline runs can verify the same compressed response and original content. Fixture metadata and response bodies share the fixture database/manifest contract; bodies are not persisted as standalone files or external CAS objects.

## Contracts

- **Uniform compression**: Every response is Zstandard-compressed before SQLite insertion, independent of media type.
- **Digest verification**: Compressed and uncompressed sizes/digests are recorded; replay decompresses incrementally and verifies the original bytes.
- **Append-only captures**: A fixture case cannot be rewritten to point at different response or selected-body evidence.
- **Bounded replay**: Response bytes flow through incremental BLOB and decompressor interfaces rather than an in-memory full-body value.

## Deliberate gaps

- **No capture orchestration**: The store does not make SEC requests or decide which acquisition outcomes to capture; the fixture CLI remains a TODO track.
- **No snapshot payload role**: Fixture BLOBs are test evidence, not S11 binary/text payload relations or a durable production body store.
