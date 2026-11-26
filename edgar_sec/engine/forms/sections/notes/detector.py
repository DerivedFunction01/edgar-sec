"""Financial statement notes sequence detector."""

from __future__ import annotations

import re

from edgar_sec.engine.document.page_markers.candidates import line_offsets
from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    NotesSequence,
    ResolvedNote,
    SectionCandidate,
)
from edgar_sec.engine.forms.sections.notes.candidates import extract_note_candidates
from edgar_sec.engine.forms.sections.sequence import MonotonicSequenceTracker
from edgar_sec.foundation.hashing import sha256_text

_RE_NOTES_START = re.compile(
    r"^\s*(?:NOTES?\s+TO\s+(?:CONSOLIDATED\s+)?FINANCIAL\s+STATEMENTS)\b",
    re.IGNORECASE,
)


def _find_notes_start_line(lines: list[str]) -> int:
    """Locate the starting line of the financial statement notes block."""
    for idx, line in enumerate(lines):
        if _RE_NOTES_START.search(line):
            return idx
    return 0


def _identifier_number(token: str) -> int | None:
    """Map a candidate identifier to its canonical note number."""
    if token.isdigit():
        return int(token)
    if len(token) == 1 and token.isalpha():
        return ord(token.upper()) - 64
    return None


def _track_candidates(
    raw_candidates: list[SectionCandidate],
) -> tuple[list[ResolvedNote], int, int]:
    """Run the monotonic tracker over candidates from one scan scope."""
    canonical_order = tuple(range(1, 100))
    tracker = MonotonicSequenceTracker[int](canonical_order)

    resolved: list[ResolvedNote] = []
    anachronisms = 0
    non_contiguous = 0

    for cand in raw_candidates:
        if cand.preceded_by_continuation:
            continue

        mapped = [_identifier_number(x) for x in cand.identifiers]
        if any(n is None for n in mapped):
            continue
        int_ids = tuple(n for n in mapped if n is not None)

        if cand.kind == CandidateKind.GROUPED:
            if not tracker.validate_group_contiguity(int_ids):
                non_contiguous += 1
                continue
            if not tracker.accept_group(int_ids):
                anachronisms += 1
                continue
            for num in int_ids:
                resolved.append(
                    ResolvedNote(
                        note_number=num,
                        note_label=f"NOTE {num}",
                        start_line=cand.line_number,
                        end_line=None,
                        title=cand.title,
                        raw_heading=cand.raw_text,
                        confidence=0.9,
                        grouped_with=tuple(i for i in int_ids if i != num),
                    )
                )
            continue

        num = int_ids[0]
        if not tracker.accept(num):
            anachronisms += 1
            continue

        token = cand.identifiers[0]
        label = f"NOTE {token.upper()}" if token.isalpha() else f"NOTE {num}"
        conf = 0.95 if cand.kind == CandidateKind.STANDARD else 0.85
        resolved.append(
            ResolvedNote(
                note_number=num,
                note_label=label,
                start_line=cand.line_number,
                end_line=None,
                title=cand.title,
                raw_heading=cand.raw_text,
                confidence=conf,
            )
        )

    return resolved, anachronisms, non_contiguous


def detect_notes_sequence(
    text: str,
    *,
    scope_span: tuple[int, int] | None = None,
    payload_sha256: str | None = None,
    representation_id: str | None = None,
    renderer_version: str | None = None,
) -> NotesSequence:
    """Detect monotonic financial statement footnotes across the notes block."""
    lines = text.splitlines()
    total_lines = len(lines)
    offsets = line_offsets(lines)

    if scope_span is not None:
        start_line, end_line = scope_span
        raw_candidates = extract_note_candidates(
            lines, start_line=start_line, end_line=end_line
        )
        resolved, anachronisms, non_contiguous = _track_candidates(raw_candidates)
    else:
        end_line = total_lines
        start_line = _find_notes_start_line(lines)
        raw_candidates = extract_note_candidates(
            lines, start_line=start_line, end_line=end_line
        )
        resolved, anachronisms, non_contiguous = _track_candidates(raw_candidates)
        if start_line > 0 and len(resolved) < 3:
            retry_candidates = extract_note_candidates(
                lines, start_line=0, end_line=end_line
            )
            retry, retry_anach, retry_noncontig = _track_candidates(retry_candidates)
            if len(retry) > len(resolved):
                resolved = retry
                anachronisms = retry_anach
                non_contiguous = retry_noncontig

    bounded_notes: list[ResolvedNote] = []
    text_len = len(text)
    for idx, note in enumerate(resolved):
        next_note = next(
            (n for n in resolved[idx + 1 :] if n.start_line > note.start_line),
            None,
        )
        bounded_end = next_note.start_line - 1 if next_note else end_line
        norm_end_line = max(note.start_line, bounded_end)
        start_char = (
            offsets[note.start_line] if note.start_line < len(offsets) else text_len
        )
        end_char = (
            offsets[norm_end_line + 1] if norm_end_line + 1 < len(offsets) else text_len
        )
        bounded_notes.append(
            ResolvedNote(
                note_number=note.note_number,
                note_label=note.note_label,
                start_line=note.start_line,
                end_line=norm_end_line,
                title=note.title,
                raw_heading=note.raw_heading,
                confidence=note.confidence,
                grouped_with=note.grouped_with,
                start_char=start_char,
                end_char=end_char,
            )
        )

    digest = payload_sha256 or (sha256_text(text) if text else None)
    return NotesSequence(
        notes=tuple(bounded_notes),
        anachronistic_rejections=anachronisms,
        non_contiguous_rejections=non_contiguous,
        payload_sha256=digest,
        representation_id=representation_id,
        renderer_version=renderer_version,
    )
