"""Bounded furniture windows, observations, and cluster evidence.

The header/footer analyzer collects a bounded candidate window around every
accepted page anchor, normalizes candidate lines into templates, and groups
observations into local anchor clusters. This module owns those mechanics;
:class:`defs.sec_forms.page_markers.ascii.headers.analyze_repeating_headers`
owns the acceptance policy and marker emission.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from ..prose import looks_like_prose

_STANDALONE_TAG_RE = re.compile(r"^\s*</?[a-zA-Z][^>\s]{0,30}>\s*$")
_PAGE_TOKEN_RE = re.compile(r"\bpage\s+\d{1,4}\b", re.IGNORECASE)
_TRAILING_NUMBER_RE = re.compile(
    r"\s+(?:[a-z]-)?(?:\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)
_STANDALONE_PAGE_NUMBER_RE = re.compile(
    r"(?<=\s)(?:[a-z]-)?(?:\d{1,4}|[ivxlcdm]{1,8})(?=\s)",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")
_ALPHA_WORD_RE = re.compile(r"[a-z]")

MAX_FURNITURE_LINES = 8
MAX_FURNITURE_CHARS = 1200
LOCAL_DENSITY = 0.65
MAX_ANCHOR_GAP = 2
PERSISTENT_MIN_ANCHORS = 8
PERSISTENT_MIN_PRESENCE = 0.05
PERSISTENT_MIN_CLUSTERS = 3


def clean_template(line: str) -> str:
    """Normalize a candidate line into a repeat-comparable template.

    Page-label variation (arabic, roman, and letter-prefixed labels such as
    ``F-1``) is masked so a per-page number cannot fragment one repeated
    banner into one-occurrence templates. Trailing labels are masked only
    when the banner still carries at least three alphabetic words, keeping
    short content lines (``Exhibit 99``) distinct from furniture.
    """
    normalized = _WHITESPACE_RE.sub(" ", line.strip().casefold())
    normalized = _PAGE_TOKEN_RE.sub(" page #", normalized)
    normalized = _STANDALONE_PAGE_NUMBER_RE.sub("#", normalized)
    trailing = _TRAILING_NUMBER_RE.sub(" #", normalized)
    alpha_words = sum(1 for word in trailing.split() if _ALPHA_WORD_RE.search(word))
    return trailing.strip() if alpha_words >= 3 else normalized.strip()


@dataclass(frozen=True, slots=True)
class Observation:
    """One page-adjacent furniture candidate line observed from one anchor."""

    side: str
    slot: int
    template: str
    line_index: int
    raw: str
    anchor_position: int
    anchor_line: int | None


def is_table_tag(stripped: str) -> bool:
    """Return whether the stripped line is a bare table open/close tag."""
    return stripped.casefold() in {"<table>", "</table>"}


def eligible_line(
    line: str,
    toc_lines: set[int],
    line_index: int,
    unit_kind: str | None,
    *,
    allow_table: bool,
) -> bool:
    """Return whether a candidate line may become a furniture observation."""
    stripped = line.strip()
    if not stripped or line_index in toc_lines:
        return False
    if _STANDALONE_TAG_RE.match(stripped):
        return False
    if unit_kind == "table" and not allow_table:
        return False
    if looks_like_prose(stripped):
        return False
    return not len(stripped) > 140


def collect_window(
    lines: list[str],
    anchor: int,
    direction: int,
    boundary_lines: set[int],
) -> list[tuple[int, str]]:
    """Collect a bounded non-empty furniture window around one anchor."""
    result: list[tuple[int, str]] = []
    index = anchor + direction
    characters = 0
    while 0 <= index < len(lines) and len(result) < MAX_FURNITURE_LINES:
        if index in boundary_lines:
            break
        stripped = lines[index].strip()
        if not stripped:
            index += direction
            continue
        if stripped.casefold() in {"<page>", "</page>"}:
            break
        if is_table_tag(stripped):
            if result and (
                (direction > 0 and stripped.casefold() == "</table>")
                or (direction < 0 and stripped.casefold() == "<table>")
            ):
                break
            index += direction
            continue
        if _STANDALONE_TAG_RE.match(stripped):
            break
        characters += len(lines[index])
        if characters > MAX_FURNITURE_CHARS:
            break
        result.append((index, lines[index]))
        index += direction
    return result


def clusters(
    members: list[Observation],
) -> list[tuple[list[Observation], int, int, float]]:
    """Split observations into local anchor clusters with local density."""
    by_position: dict[int, list[Observation]] = defaultdict(list)
    for member in members:
        by_position[member.anchor_position].append(member)
    positions = sorted(by_position)
    groups: list[list[int]] = []
    current: list[int] = []
    for position in positions:
        if current and position - current[-1] > MAX_ANCHOR_GAP:
            groups.append(current)
            current = []
        current.append(position)
    if current:
        groups.append(current)
    result: list[tuple[list[Observation], int, int, float]] = []
    for cluster_positions in groups:
        start, end = cluster_positions[0], cluster_positions[-1]
        cluster_members = [
            member for member in members if member.anchor_position in cluster_positions
        ]
        density = len(cluster_positions) / (end - start + 1)
        result.append((cluster_members, start, end, density))
    return result


def merge_observations(
    observations: list[Observation],
    lines: list[str],
    offsets: list[int],
) -> list[tuple[int, int, int, int, str]]:
    """Merge only fully validated adjacent lines into block spans."""
    by_anchor: dict[tuple[str, int], list[Observation]] = defaultdict(list)
    for observation in observations:
        by_anchor[(observation.side, observation.anchor_position)].append(observation)
    ranges: list[tuple[int, int, int, int, str]] = []
    for (side, anchor_position), members in by_anchor.items():
        del anchor_position
        members.sort(key=lambda item: item.line_index)
        selected = {member.line_index for member in members}
        start = previous = members[0].line_index
        for member in members[1:]:
            between = range(previous + 1, member.line_index)
            if any(
                lines[index].strip()
                and not is_table_tag(lines[index].strip())
                and index not in selected
                for index in between
            ):
                ranges.append(
                    (
                        start,
                        previous,
                        offsets[start],
                        offsets[previous] + len(lines[previous]),
                        side,
                    )
                )
                start = member.line_index
            previous = member.line_index
        while start > 0 and lines[start - 1].strip().casefold() == "<table>":
            start -= 1
        end_line = previous
        while (
            end_line + 1 < len(lines)
            and lines[end_line + 1].strip().casefold() == "</table>"
        ):
            end_line += 1
        ranges.append(
            (
                start,
                end_line,
                offsets[start],
                offsets[end_line] + len(lines[end_line]),
                side,
            )
        )
    return ranges


__all__ = [
    "LOCAL_DENSITY",
    "MAX_ANCHOR_GAP",
    "MAX_FURNITURE_CHARS",
    "MAX_FURNITURE_LINES",
    "PERSISTENT_MIN_ANCHORS",
    "PERSISTENT_MIN_CLUSTERS",
    "PERSISTENT_MIN_PRESENCE",
    "Observation",
    "clean_template",
    "clusters",
    "collect_window",
    "eligible_line",
    "is_table_tag",
    "merge_observations",
]
