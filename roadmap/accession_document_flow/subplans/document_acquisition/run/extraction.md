# S9 exact bundle-sequence extraction

## Purpose and status

Select the body named by an S6 `bundle_sequence` target from a streamed legacy SEC
submission envelope. This is design-only. The existing bytes-based
`unpack_sgml_submission()` is only a small-fixture parity oracle; production needs a
bounded engine implementation.

## Engine API proposal

The scanner belongs in `edgar_sec.engine.document.unpacking` and receives paths and
primitive selectors, not S9 pipeline models:

```python
@dataclass(frozen=True, slots=True)
class BundleSelector:
    sequence: int

@dataclass(frozen=True, slots=True)
class BundleDocumentHeader:
    ordinal: int
    sequence: int | None
    filename: str | None
    document_type: str | None
    description: str | None
    declared_length: int | None

@dataclass(frozen=True, slots=True)
class BundleExtraction:
    output_path: Path
    selected_filename: str | None
    document_type: str | None
    declared_length: int | None
    selected_sha256: str
    selected_byte_size: int
    document_count: int

@dataclass(frozen=True, slots=True)
class BundleExtractionFailure:
    code: Literal[
        "not_sgml", "malformed_delimiters", "invalid_sequence",
        "sequence_not_found", "duplicate_sequence", "invalid_length",
        "length_mismatch", "length_out_of_bounds", "missing_text",
        "source_mismatch",
    ]
    matching_sequences: int
    source_sha256: str

def extract_bundle_sequence(
    source_path: Path,
    destination: Path,
    selector: BundleSelector,
    *,
    chunk_size: int,
    expected_source_sha256: str,
) -> BundleExtraction | BundleExtractionFailure: ...
```

`chunk_size` comes from a bounded engine/runtime setting; it is not a hardcoded
memory limit. S9 converts a successful engine result to its staged-body handle and
maps typed failures to acquisition outcomes.

## Selection and byte contract

- Parse the complete envelope in bounded chunks. Recognize `<DOCUMENT>`, header
  fields, `<TEXT>`, and closing delimiters even when tokens cross input chunk
  boundaries. Reject nested or unbalanced document delimiters.
- The S6 positive sequence is authoritative. One exact match is selected; zero
  matches after a complete valid scan is `not_filed`; duplicate sequence matches
  are `ambiguous`. Never select sequence one, the lowest sequence, or a filename
  resemblance as fallback.
- S6 does not publish an expected SGML filename/type. `target_role` and
  `target_type` are profile intent, not expected `<FILENAME>`/`<TYPE>` values. Use
  the selected header's actual filename/type for provenance only. S9 does not
  cross-check that header against the S5 index row; adding that guarantee requires
  carrying the observed type in a versioned target-plan contract.
- If `<LENGTH>` is present, require a non-negative decimal and verify it against the
  enclosing document boundary and extracted byte count. It cannot authorize seeking
  outside the `<DOCUMENT>` span.
- Preserve exact bytes within `<TEXT>`; do not trim, decode, normalize newlines, or
  apply HTML/XML processing before hashing. Verify the source file against the
  streamed source digest before accepting a child body.
- A direct URL bypasses this extractor; its downloaded body is the selected body.

## Failures and cleanup

Not-SGML, malformed delimiters, invalid/absent/duplicate sequence, invalid lengths,
truncated text, or source-digest disagreement return a typed failure and no selected
body. Remove any partial output on failure. A valid complete source with a missing
sequence yields `not_filed`, not `failed`.

## Tests

Tests cover large envelopes, delimiters/header fields split at every chunk boundary,
PEM envelope handling, sequence zero/missing/duplicate, absent filename, optional
length and length mismatch, malformed nesting, truncated/empty text, digest mismatch,
exact selected-byte digest/size, and parity with the existing bytes parser for
supported small fixtures. Unselected body spans are never materialized.
