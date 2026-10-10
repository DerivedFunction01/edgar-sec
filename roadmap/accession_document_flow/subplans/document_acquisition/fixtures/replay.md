# `acquisition fixture replay`

## Purpose and status

Replay one exact captured case from local evidence without network access. The case
lookup, CLI adapter, and operator action are implemented. The lower-level
`replay_fixture_response()` primitive incrementally decompresses a response BLOB into a
binary destination and verifies stored and uncompressed sizes and SHA-256 digests.

## CLI and operator

```text
acquisition fixture replay --fixture-id <id> --capture-id <id> --target-id <id> --output <new-path>
```

Replay requires exact fixture/capture/target IDs and an explicit output path. The
operator requires an affirmative, default-no confirmation before writing. The path
must not already exist; replay never overwrites it. Output is not printed as document
bytes.

```python
def replay_fixture_case(
    fixture_id: str,
    capture_id: str,
    target_id: str,
    output_path: Path,
    *,
    paths: AcquisitionPaths,
) -> FixtureReplayResult: ...
```

## Verification and route behavior

- Resolve the exact case from the named fixture and capture/target IDs. Open the fixture
  read-only, then stream the response through the existing integrity verifier, checking
  compressed and uncompressed byte sizes and SHA-256 digests.
- Ordinary direct cases require the verified source response identity to equal the
  recorded selected-body identity. Lazy-resolution cases verify the retained source,
  index, and selected responses independently; a selected bundle response is locally
  extracted at its recorded sequence and checked against selected digest and size. A
  bundle-sequence case is likewise locally extracted and verified. Replay performs no
  HTTP request or index lookup.
- A bodyless failed case returns its recorded attempt/outcome metadata only and creates
  no output file. A case with inconsistent body metadata or corrupt/mismatched response
  evidence fails rather than returning selected bytes.
- For acquired cases, write to a temporary file in the caller-selected output
  directory, then publish to the explicit path only if it remains new. Existing files
  and symlinks are refused. The fixture database is not modified.
- The output is a caller-owned file. There is no managed durable staging API,
  `StagedBodyRef` handoff, S10 consumption receipt, or cleanup protocol. Replay does not
  claim S10 integration and does not bypass the representative-evidence and approval
  gate for S11 publication.

## Tests

Offline tests cover exact case resolution, byte-identical direct replay, bundle
extraction and selected-body identity where such a case exists, metadata-only failure
without output, output no-overwrite behavior, and refusal on corrupt evidence.
