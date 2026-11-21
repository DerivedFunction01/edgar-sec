"""Canonical-JSON codecs for the facade's derived section/note sequences.

Only constructor fields are encoded; the sequences' internal index caches
are derived state that their constructors rebuild on decode.
"""

from __future__ import annotations

import dataclasses
import json
from enum import StrEnum
from typing import Any

from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    NotesSequence,
    ResolvedNote,
    ResolvedSection,
    SectionSequence,
)
from edgar_sec.foundation.serialization import canonical_json


def _encode_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _encode_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if field.init
        }
    if isinstance(value, tuple):
        return [_encode_value(item) for item in value]
    if isinstance(value, StrEnum):
        return str(value)
    return value


def _section_from(data: dict[str, Any]) -> ResolvedSection:
    return ResolvedSection(
        item_identifier=data["item_identifier"],
        start_line=data["start_line"],
        end_line=data["end_line"],
        title=data["title"],
        raw_heading=data["raw_heading"],
        kind=CandidateKind(data["kind"]),
        confidence=data["confidence"],
        is_omitted=data["is_omitted"],
        grouped_with=tuple(data["grouped_with"]),
        start_char=data["start_char"],
        end_char=data["end_char"],
        displaced=data["displaced"],
    )


def _note_from(data: dict[str, Any]) -> ResolvedNote:
    return ResolvedNote(
        note_number=data["note_number"],
        note_label=data["note_label"],
        start_line=data["start_line"],
        end_line=data["end_line"],
        title=data["title"],
        raw_heading=data["raw_heading"],
        confidence=data["confidence"],
        grouped_with=tuple(data["grouped_with"]),
        start_char=data["start_char"],
        end_char=data["end_char"],
    )


def encode_sections(seq: SectionSequence) -> bytes:
    """Serialize a section sequence to canonical JSON bytes."""
    return canonical_json(_encode_value(seq)).encode("utf-8")


def decode_sections(data: bytes) -> SectionSequence:
    """Rebuild a section sequence from its canonical JSON bytes."""
    raw = json.loads(data)
    return SectionSequence(
        family=raw["family"],
        sections=tuple(_section_from(item) for item in raw["sections"]),
        missing_items=tuple(raw["missing_items"]),
        anachronistic_rejections=raw["anachronistic_rejections"],
        non_contiguous_rejections=raw["non_contiguous_rejections"],
        disordered=raw["disordered"],
        payload_sha256=raw["payload_sha256"],
        representation_id=raw["representation_id"],
        renderer_version=raw["renderer_version"],
    )


def encode_notes(seq: NotesSequence) -> bytes:
    """Serialize a notes sequence to canonical JSON bytes."""
    return canonical_json(_encode_value(seq)).encode("utf-8")


def decode_notes(data: bytes) -> NotesSequence:
    """Rebuild a notes sequence from its canonical JSON bytes."""
    raw = json.loads(data)
    return NotesSequence(
        notes=tuple(_note_from(item) for item in raw["notes"]),
        anachronistic_rejections=raw["anachronistic_rejections"],
        non_contiguous_rejections=raw["non_contiguous_rejections"],
        payload_sha256=raw["payload_sha256"],
        representation_id=raw["representation_id"],
        renderer_version=raw["renderer_version"],
    )


__all__ = [
    "decode_notes",
    "decode_sections",
    "encode_notes",
    "encode_sections",
]
