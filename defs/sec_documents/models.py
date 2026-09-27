"""Document representation types and preprocessed document models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DocumentRepresentation(str, Enum):
    """Canonical representation format of an SEC document payload."""

    HTML = "html"
    ASCII_PRE = "ascii_pre"
    ASCII_PLAIN = "ascii_plain"
    XML = "xml"
    BINARY = "binary"

    @property
    def is_html(self) -> bool:
        return self == DocumentRepresentation.HTML

    @property
    def is_ascii(self) -> bool:
        return self in (
            DocumentRepresentation.ASCII_PRE,
            DocumentRepresentation.ASCII_PLAIN,
        )

    @property
    def is_xml(self) -> bool:
        return self == DocumentRepresentation.XML


@dataclass(frozen=True, slots=True)
class PreprocessedDocument:
    """Intermediate representation produced by document preprocessing."""

    raw_text: str
    cleaned_text: str
    word_count: int
    has_html_tags: bool
    detected_encoding: str
    metadata: dict[str, Any] = field(default_factory=dict)
    representation: str = "ascii"


__all__ = [
    "DocumentRepresentation",
    "PreprocessedDocument",
]
