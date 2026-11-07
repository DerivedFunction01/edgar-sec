"""Tests pinning the sequence codecs: lossless, deterministic round-trips."""

from __future__ import annotations

from edgar_sec.apps.client.sequence_codec import (
    decode_notes,
    decode_sections,
    encode_notes,
    encode_sections,
)
from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    NotesSequence,
    ResolvedNote,
    ResolvedSection,
    SectionSequence,
)


def _sections() -> SectionSequence:
    return SectionSequence(
        family="10-K",
        sections=(
            ResolvedSection(
                item_identifier="ITEM 1",
                start_line=0,
                end_line=10,
                title="Business",
                raw_heading="ITEM 1. BUSINESS",
                kind=CandidateKind.STANDARD,
                confidence=0.95,
                grouped_with=("ITEM 1A",),
                start_char=0,
                end_char=500,
            ),
            ResolvedSection(
                item_identifier="ITEM 1A",
                start_line=11,
                end_line=None,
                title="Risk Factors",
                raw_heading="ITEM 1A. RISK FACTORS",
                kind=CandidateKind.GROUPED,
                confidence=0.5,
                is_omitted=True,
                displaced=True,
            ),
        ),
        missing_items=("ITEM 2", "ITEM 3"),
        anachronistic_rejections=1,
        payload_sha256="deadbeef",
        representation_id="rep-1",
        renderer_version="v7",
    )


def _notes() -> NotesSequence:
    return NotesSequence(
        notes=(
            ResolvedNote(
                note_number=1,
                note_label="1",
                start_line=20,
                end_line=40,
                title="Summary of Significant Accounting Policies",
                raw_heading="Note 1. Summary",
                confidence=1.0,
                grouped_with=(2,),
                start_char=600,
                end_char=900,
            ),
        ),
        non_contiguous_rejections=2,
        payload_sha256="cafef00d",
        renderer_version="v3",
    )


def test_sections_round_trip_is_lossless_and_deterministic() -> None:
    """Verify encode/decode preserves every constructor field exactly."""
    seq = _sections()
    blob = encode_sections(seq)
    assert encode_sections(seq) == blob
    decoded = decode_sections(blob)
    assert decoded == seq
    assert decoded.get("1A") is not None
    assert decoded.find_section_for_line(5) is not None


def test_notes_round_trip_is_lossless_and_deterministic() -> None:
    """Verify the notes codec preserves numbers, groupings, and provenance."""
    seq = _notes()
    blob = encode_notes(seq)
    assert encode_notes(seq) == blob
    decoded = decode_notes(blob)
    assert decoded == seq
    assert decoded.get(1) is not None
    assert decoded.find_note_for_line(30) is not None
