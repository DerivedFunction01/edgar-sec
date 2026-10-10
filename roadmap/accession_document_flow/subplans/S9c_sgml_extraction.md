# S9c — Legacy SGML Bundle Extraction

## Owner and status

- Owning stage in [S9](S9_acquisition.md): exact selection from submission envelopes.
- Status: bounded exact-sequence extraction is implemented in the engine; the S9
  runner that composes it with transport and target outcomes is not.
- Depends on: [S9a work orders](S9a_target_adapter.md), [S9b staged bodies](S9b_stream_transport.md).

## Current tracked-code audit (2026-10-10)

- **Status: bounded sequence selection is implemented separately from the bytes-based legacy helper.** The engine reads a source path in bounded chunks, writes only one unique positive sequence's exact `<TEXT>` bytes, and returns typed structure/source failures. The bytes-based helper remains the small-fixture parity oracle.
- **Evidence:** [`engine/document/unpacking/streaming.py`](../../../edgar_sec/engine/document/unpacking/streaming.py) and [`test_streaming.py`](../../../tests/engine/document/unpacking/test_streaming.py) cover chunk boundaries, malformed/duplicate/missing sequences, length checks, exact digest, cleanup, and bounded reads.
- **Next step:** compose the engine API with file-backed broker transport in the S9 runner and map its typed failures to target outcomes without fallback.

## Objective

Extract only the selected body from a legacy SEC SGML submission envelope using the sequence observed in the inventory. Never infer a primary or substitute sequence one.

## Models

```python
@dataclass(frozen=True, slots=True)
class BundleSelector:
    sequence: int
    expected_filename: str | None
    expected_document_type: str | None

@dataclass(frozen=True, slots=True)
class BundleDocumentHeader:
    ordinal: int
    sequence: int
    filename: str | None
    document_type: str | None
    description: str | None
    declared_length: int | None

@dataclass(frozen=True, slots=True)
class BundleExtraction:
    destination: Path
    selected: BundleDocumentHeader
    document_count: int
    source_size: int
    source_sha256: str
    body_size: int
    body_sha256: str

@dataclass(frozen=True, slots=True)
class BundleExtractionFailure:
    code: Literal[
        "not_sgml", "malformed_delimiters", "missing_sequence",
        "invalid_sequence", "sequence_not_found", "duplicate_sequence",
        "invalid_length", "length_mismatch", "length_out_of_bounds",
        "missing_text", "source_mismatch", "io_error",
    ]
    matching_sequences: int
    source_sha256: str
```

## Interface

```python
extract_bundle_sequence(
    source: Path,
    sequence: int,
    destination: Path,
    *,
    expected_filename: str | None = None,
    expected_document_type: str | None = None,
    expected_source_sha256: str | None = None,
) -> BundleExtraction | BundleExtractionFailure
```

The scanner reads the staged envelope in bounded chunks, validates non-nested balanced `<DOCUMENT>` delimiters, records headers in source order, and streams only the selected `<TEXT>` span to a new staged file while computing its digest and size. It does not retain all child bodies or copy the complete bundle into process memory. Header tags that cross chunk boundaries must be recognized without losing bytes.

The sequence is authoritative. Zero matches yields `sequence_not_found`; more than one match yields `duplicate_sequence`, even if filenames differ. If the selected header contains a filename or type that conflicts with the observed target metadata, return `source_mismatch`; do not fall back to another sequence. A missing filename is permitted when sequence uniquely identifies the child.

If `<LENGTH>` is present, parse it as a non-negative decimal and validate it against the child boundary and extracted byte count. It is never used alone to seek outside the enclosing `<DOCUMENT>` span. Invalid, inconsistent, or out-of-bounds length metadata is typed failure, not a truncated extraction. Preserve the exact bytes inside `<TEXT>`; do not trim or decode them before hashing.

The streaming primitive belongs in `edgar_sec.engine.document.unpacking` (for example, a dedicated `streaming.py` module), with a mirrored engine test module. The current bytes-based helper is useful as a small-fixture parity oracle but is not the production large-bundle transport. No new S9c or streaming-engine module imports `pipelines.document_storage`; the existing legacy package and its mirrored tests remain until the decommission gate.

## Tests

- Exact sequence extraction from multi-document envelopes, including a bundle larger than the configured worker-memory budget.
- Sequence tags and `<TEXT>` delimiters split across transport chunks.
- Missing, invalid, duplicate, and absent sequences produce distinct typed failures; sequence one is never guessed.
- Unbalanced/nested document tags, missing text blocks, invalid declared lengths, length mismatches, and out-of-bounds spans fail without a selected body.
- Filename/type disagreement is reported without choosing a different document.
- The extracted digest and size match the exact selected `<TEXT>` bytes; unselected bodies are not materialized.
- Results match the existing byte-based engine helper on supported small fixtures.

## Acceptance criteria

Extraction is sequence-exact, bounded in memory, preserves byte provenance, and fails closed on structural ambiguity. It returns one staged child body or a typed failure—never a guessed document.
