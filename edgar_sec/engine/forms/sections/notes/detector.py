"""Financial statement notes sequence detector."""

from __future__ import annotations

import re

from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    NotesSequence,
    ResolvedNote,
)
from edgar_sec.engine.forms.sections.notes.candidates import extract_note_candidates
from edgar_sec.engine.forms.sections.sequence import MonotonicSequenceTracker

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


def detect_notes_sequence(
    text: str,
    *,
    scope_span: tuple[int, int] | None = None,
) -> NotesSequence:
    """Detect monotonic financial statement footnotes across the notes block."""
    lines = text.splitlines()
    total_lines = len(lines)

    if scope_span is not None:
        start_line, end_line = scope_span
    else:
        start_line = _find_notes_start_line(lines)
        end_line = total_lines

    raw_candidates = extract_note_candidates(
        lines, start_line=start_line, end_line=end_line
    )

    canonical_order = tuple(range(1, 100))
    tracker = MonotonicSequenceTracker[int](canonical_order)

    resolved: list[ResolvedNote] = []
    anachronisms = 0
    non_contiguous = 0

    for cand in raw_candidates:
        if cand.preceded_by_continuation:
            continue

        try:
            int_ids = tuple(int(x) for x in cand.identifiers)
        except ValueError:
            continue

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

        conf = 0.95 if cand.kind == CandidateKind.STANDARD else 0.85
        resolved.append(
            ResolvedNote(
                note_number=num,
                note_label=f"NOTE {num}",
                start_line=cand.line_number,
                end_line=None,
                title=cand.title,
                raw_heading=cand.raw_text,
                confidence=conf,
            )
        )

    bounded_notes: list[ResolvedNote] = []
    for idx, note in enumerate(resolved):
        next_note = next(
            (n for n in resolved[idx + 1 :] if n.start_line > note.start_line),
            None,
        )
        bounded_end = next_note.start_line - 1 if next_note else end_line
        bounded_notes.append(
            ResolvedNote(
                note_number=note.note_number,
                note_label=note.note_label,
                start_line=note.start_line,
                end_line=max(note.start_line, bounded_end),
                title=note.title,
                raw_heading=note.raw_heading,
                confidence=note.confidence,
                grouped_with=note.grouped_with,
            )
        )

    return NotesSequence(
        notes=tuple(bounded_notes),
        anachronistic_rejections=anachronisms,
        non_contiguous_rejections=non_contiguous,
    )
