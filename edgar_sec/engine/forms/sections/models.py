"""Data models for structural section and note sequence analysis."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from enum import StrEnum


class CandidateKind(StrEnum):
    """Classification of a raw structural candidate heading."""

    STANDARD = "standard"
    GROUPED = "grouped"
    NUMERIC = "numeric"
    TITLE_ONLY = "title_only"


@dataclass(frozen=True, slots=True)
class SectionCandidate:
    """Raw structural section candidate extracted from document lines."""

    line_number: int
    raw_text: str
    kind: CandidateKind
    identifiers: tuple[str, ...]
    title: str = ""
    part: int | None = None
    is_omitted: bool = False
    preceded_by_continuation: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedSection:
    """Validated structural section bounded by document line coordinates."""

    item_identifier: str
    start_line: int
    end_line: int | None
    title: str
    raw_heading: str
    kind: CandidateKind
    confidence: float
    is_omitted: bool = False
    grouped_with: tuple[str, ...] = ()
    start_char: int | None = None
    end_char: int | None = None


@dataclass(frozen=True, slots=True)
class SectionSequence:
    """Document-level sequence of resolved statutory Part/Item sections."""

    family: str
    sections: tuple[ResolvedSection, ...]
    missing_items: tuple[str, ...] = ()
    anachronistic_rejections: int = 0
    non_contiguous_rejections: int = 0
    payload_sha256: str | None = None
    representation_id: str | None = None
    renderer_version: str | None = None
    _by_id_cache: dict[str, ResolvedSection] = field(
        default_factory=dict, init=False, repr=False, compare=False, hash=False
    )
    _line_starts: tuple[int, ...] = field(
        default_factory=tuple, init=False, repr=False, compare=False, hash=False
    )
    _char_starts: tuple[int, ...] = field(
        default_factory=tuple, init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_by_id_cache",
            {s.item_identifier: s for s in self.sections},
        )
        object.__setattr__(
            self,
            "_line_starts",
            tuple(s.start_line for s in self.sections),
        )
        object.__setattr__(
            self,
            "_char_starts",
            tuple(s.start_char or 0 for s in self.sections),
        )

    def get(self, item: str) -> ResolvedSection | None:
        """Find section by item identifier (e.g. 'ITEM 1A' or '1A') in O(1)."""
        canon = item.upper().strip()
        if not canon.startswith("ITEM"):
            canon = f"ITEM {canon}"
        return self._by_id_cache.get(canon)

    def find_section_for_line(self, line_number: int) -> ResolvedSection | None:
        """Find section containing line_number using bisect in O(log S)."""
        if not self.sections:
            return None
        idx = bisect_right(self._line_starts, line_number) - 1
        if idx < 0:
            return None
        sec = self.sections[idx]
        if sec.end_line is not None and line_number > sec.end_line:
            return None
        return sec

    def find_section_for_offset(self, char_offset: int) -> ResolvedSection | None:
        """Find section containing char_offset using bisect in O(log S)."""
        if not self.sections:
            return None
        idx = bisect_right(self._char_starts, char_offset) - 1
        if idx < 0:
            return None
        sec = self.sections[idx]
        if sec.end_char is not None and char_offset >= sec.end_char:
            return None
        return sec

    def get_text(self, text: str, item: str) -> str:
        """Extract text of section in O(1) via direct substring slicing."""
        sec = self.get(item)
        if sec is None:
            return ""
        if sec.start_char is not None and sec.end_char is not None:
            return text[sec.start_char : sec.end_char].rstrip()
        lines = text.splitlines()
        end = (sec.end_line + 1) if sec.end_line is not None else len(lines)
        return "\n".join(lines[sec.start_line : end])


@dataclass(frozen=True, slots=True)
class ResolvedNote:
    """Validated financial statement footnote bounded by document coordinates."""

    note_number: int
    note_label: str
    start_line: int
    end_line: int | None
    title: str
    raw_heading: str
    confidence: float
    grouped_with: tuple[int, ...] = ()
    start_char: int | None = None
    end_char: int | None = None


@dataclass(frozen=True, slots=True)
class NotesSequence:
    """Document-level sequence of financial statement footnotes."""

    notes: tuple[ResolvedNote, ...]
    anachronistic_rejections: int = 0
    non_contiguous_rejections: int = 0
    payload_sha256: str | None = None
    representation_id: str | None = None
    renderer_version: str | None = None
    _by_num_cache: dict[int, ResolvedNote] = field(
        default_factory=dict, init=False, repr=False, compare=False, hash=False
    )
    _line_starts: tuple[int, ...] = field(
        default_factory=tuple, init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_by_num_cache",
            {n.note_number: n for n in self.notes},
        )
        object.__setattr__(
            self,
            "_line_starts",
            tuple(n.start_line for n in self.notes),
        )

    def get(self, note_number: int) -> ResolvedNote | None:
        """Find footnote by note number in O(1)."""
        return self._by_num_cache.get(note_number)

    def find_note_for_line(self, line_number: int) -> ResolvedNote | None:
        """Find footnote containing line_number using bisect in O(log N)."""
        if not self.notes:
            return None
        idx = bisect_right(self._line_starts, line_number) - 1
        if idx < 0:
            return None
        note = self.notes[idx]
        if note.end_line is not None and line_number > note.end_line:
            return None
        return note

    def get_text(self, text: str, note_number: int) -> str:
        """Extract text of footnote in O(1) via direct substring slicing."""
        note = self.get(note_number)
        if note is None:
            return ""
        if note.start_char is not None and note.end_char is not None:
            return text[note.start_char : note.end_char].rstrip()
        lines = text.splitlines()
        end = (note.end_line + 1) if note.end_line is not None else len(lines)
        return "\n".join(lines[note.start_line : end])
