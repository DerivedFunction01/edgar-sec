"""Conservative repeated ASCII header/footer classification."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from defs.text.logical_units import classify_units

from ..models import (
    PageMarker,
    PageMarkerAction,
    PageMarkerDecision,
    PageMarkerKind,
    TemplateEvidence,
)
from .candidates import line_offsets

_STANDALONE_TAG_RE = re.compile(r"^\s*</?[a-zA-Z][^>\s]{0,30}>\s*$")
_PAGE_TOKEN_RE = re.compile(r"\bpage\s+\d{1,4}\b", re.IGNORECASE)
_TRAILING_NUMBER_RE = re.compile(r"\s{2,}(?:\d{1,4}|[ivxlcdm]{1,8})\s*$", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_template(line: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", line.strip().casefold())
    normalized = _PAGE_TOKEN_RE.sub(" page #", normalized)
    normalized = _TRAILING_NUMBER_RE.sub(" #", normalized)
    return normalized.strip()


_MAX_FURNITURE_LINES = 8
_MAX_FURNITURE_CHARS = 1200
_LOCAL_DENSITY = 0.65
_MAX_ANCHOR_GAP = 2


@dataclass(frozen=True, slots=True)
class _Observation:
    side: str
    slot: int
    template: str
    line_index: int
    raw: str
    anchor_position: int
    anchor_line: int | None


def _is_table_tag(stripped: str) -> bool:
    return stripped.casefold() in {"<table>", "</table>"}


def _eligible(
    line: str,
    toc_lines: set[int],
    line_index: int,
    unit_kind: str | None,
    *,
    allow_table: bool,
) -> bool:
    stripped = line.strip()
    if not stripped or line_index in toc_lines:
        return False
    if _STANDALONE_TAG_RE.match(stripped):
        return False
    if unit_kind == "table" and not allow_table:
        return False
    return not len(stripped) > 140


def _collect_window(
    lines: list[str],
    anchor: int,
    direction: int,
    boundary_lines: set[int],
) -> list[tuple[int, str]]:
    """Collect a bounded non-empty furniture window around one anchor."""
    result: list[tuple[int, str]] = []
    index = anchor + direction
    characters = 0
    while 0 <= index < len(lines) and len(result) < _MAX_FURNITURE_LINES:
        if index in boundary_lines:
            break
        stripped = lines[index].strip()
        if not stripped:
            index += direction
            continue
        if stripped.casefold() in {"<page>", "</page>"}:
            break
        if _is_table_tag(stripped):
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
        if characters > _MAX_FURNITURE_CHARS:
            break
        result.append((index, lines[index]))
        index += direction
    return result


def _clusters(
    members: list[_Observation],
) -> list[tuple[list[_Observation], int, int, float]]:
    by_position: dict[int, list[_Observation]] = defaultdict(list)
    for member in members:
        by_position[member.anchor_position].append(member)
    positions = sorted(by_position)
    clusters: list[list[int]] = []
    current: list[int] = []
    for position in positions:
        if current and position - current[-1] > _MAX_ANCHOR_GAP:
            clusters.append(current)
            current = []
        current.append(position)
    if current:
        clusters.append(current)
    result: list[tuple[list[_Observation], int, int, float]] = []
    for positions in clusters:
        start, end = positions[0], positions[-1]
        cluster_members = [
            member for member in members if member.anchor_position in positions
        ]
        density = len(positions) / (end - start + 1)
        result.append((cluster_members, start, end, density))
    return result


def _merge_observations(
    observations: list[_Observation],
    lines: list[str],
    offsets: list[int],
) -> list[tuple[int, int, int, int, str]]:
    """Merge only fully validated adjacent lines into block spans."""
    by_anchor: dict[tuple[str, int], list[_Observation]] = defaultdict(list)
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
                and not _is_table_tag(lines[index].strip())
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


def analyze_repeating_headers(
    text: str,
    markers: list[PageMarker],
    *,
    toc_lines: set[int] | None = None,
    allow_table_furniture: bool = False,
    boundary_lines: set[int] | None = None,
    header_anchors: list[int] | None = None,
    footer_anchors: list[int] | None = None,
) -> tuple[tuple[TemplateEvidence, ...], list[PageMarker], list[PageMarkerDecision]]:
    """Classify bounded repeated text adjacent to accepted page anchors."""

    lines = text.splitlines()
    offsets = line_offsets(lines)
    toc_lines = toc_lines or set()
    anchors = sorted(
        {marker.start_line for marker in markers if marker.start_line is not None}
    )
    header_anchor_lines = sorted(set(header_anchors or anchors))
    footer_anchor_lines = sorted(set(footer_anchors or anchors))
    if max(len(header_anchor_lines), len(footer_anchor_lines)) < 3:
        return (), [], []
    # The cover has no anchor before it and the last page has none after it.
    # When a side already has enough real anchors, treat the document start
    # (header side) and end (footer side) as implicit structural boundaries.
    side_scan: dict[str, list[tuple[int, int | None]]] = {
        "header": [(line, line) for line in header_anchor_lines],
        "footer": [(line, line) for line in footer_anchor_lines],
    }
    if len(header_anchor_lines) >= 3:
        side_scan["header"].insert(0, (-1, None))
    if len(footer_anchor_lines) >= 3:
        side_scan["footer"].append((len(lines), None))
    units_by_line: dict[int, str] = {}
    for unit in classify_units(text):
        for line_index in range(unit.start_line, unit.end_line + 1):
            units_by_line[line_index] = unit.kind
    table_depth = 0
    for line_index, line in enumerate(lines):
        stripped = line.strip().casefold()
        if "<table>" in stripped:
            table_depth += stripped.count("<table>")
        if table_depth:
            units_by_line[line_index] = "table"
        if "</table>" in stripped:
            table_depth = max(0, table_depth - stripped.count("</table>"))
    boundary_lines = boundary_lines or {
        line
        for marker in markers
        for line in range(marker.start_line or 0, (marker.end_line or 0) + 1)
    }
    groups: dict[tuple[str, int, str], list[_Observation]] = defaultdict(list)
    for side, direction in (("header", 1), ("footer", -1)):
        anchor_positions = {
            line: position for position, (line, _) in enumerate(side_scan[side])
        }
        for anchor, anchor_line in side_scan[side]:
            anchor_position = anchor_positions[anchor]
            for slot, (index, line) in enumerate(
                _collect_window(lines, anchor, direction, boundary_lines)
            ):
                if not _eligible(
                    line,
                    toc_lines,
                    index,
                    units_by_line.get(index),
                    allow_table=allow_table_furniture,
                ):
                    continue
                template = _clean_template(line)
                if template:
                    groups[(side, slot, template)].append(
                        _Observation(
                            side,
                            slot,
                            template,
                            index,
                            line,
                            anchor_position,
                            anchor_line,
                        )
                    )

    templates: list[TemplateEvidence] = []
    header_markers: list[PageMarker] = []
    decisions: list[PageMarkerDecision] = []
    removable: list[_Observation] = []
    retained_lines: set[int] = set()
    observed_groups: list[
        tuple[tuple[str, int, str], list[_Observation], int, int, float]
    ] = []

    for key, members in groups.items():
        side, position, template = key
        for cluster_members, start, end, presence in _clusters(members):
            positions = {member.anchor_position for member in cluster_members}
            if len(positions) < 3 or presence < _LOCAL_DENSITY:
                continue
            if len(positions) == 3 and not allow_table_furniture and presence < 1.0:
                continue
            observed_groups.append((key, cluster_members, start, end, presence))

    # Attach same-side/same-template observations whose own slot group was
    # too sparse (for example the cover occurrence, where the furniture is
    # the second non-empty line from document start) to an accepted cluster
    # of the identical template. They inherit that cluster's role. Clusters
    # are addressed by index: one key can yield several accepted clusters.
    accepted_keys = {key for key, *_ in observed_groups}
    augmented_members: list[list[_Observation]] = [
        sorted(members, key=lambda item: (item.anchor_position, item.line_index))
        for _, members, _, _, _ in observed_groups
    ]
    for key, observations in groups.items():
        if key in accepted_keys:
            continue
        side, _, template = key
        candidate_indexes = [
            index
            for index, entry in enumerate(observed_groups)
            if entry[0][0] == side and entry[0][2] == template
        ]
        if not candidate_indexes:
            continue
        for observation in observations:
            best_index: int | None = None
            best_distance: int | None = None
            for index in candidate_indexes:
                g_start, g_end = observed_groups[index][2], observed_groups[index][3]
                if g_start - 1 <= observation.anchor_position <= g_end + 1:
                    distance = 0
                else:
                    distance = min(
                        abs(observation.anchor_position - g_start),
                        abs(observation.anchor_position - g_end),
                    )
                if best_distance is None or distance < best_distance:
                    best_index, best_distance = index, distance
            if best_index is not None:
                augmented_members[best_index].append(observation)

    for group_index, (key, _cluster_members, start, end, _presence) in enumerate(
        observed_groups
    ):
        members = sorted(
            augmented_members[group_index],
            key=lambda item: (item.anchor_position, item.line_index),
        )
        cluster_positions = sorted({member.anchor_position for member in members})
        start, end = cluster_positions[0], cluster_positions[-1]
        presence = len(cluster_positions) / (end - start + 1)
        side, position, template = key
        variants = {
            other_key[2]
            for other_key, _, other_start, other_end, _ in observed_groups
            if other_key[0] == side
            and other_key[1] == position
            and other_start <= end + 1
            and start <= other_end + 1
        }
        variable = len(variants) > 1
        role = (
            "footer"
            if side == "footer"
            else ("section_header" if variable else "boilerplate")
        )
        retention = (
            "remove_all" if role != "section_header" else "keep_first_per_cohort"
        )
        kind = (
            PageMarkerKind.REPEATING_HEADER
            if side == "header"
            else PageMarkerKind.REPEATING_FOOTER
        )
        lines_seen = tuple(member.line_index for member in members)
        templates.append(
            TemplateEvidence(
                side,
                position,
                template,
                len(members),
                presence,
                kind,
                lines_seen,
                members[0].anchor_line,
                members[-1].anchor_line,
                role,
                retention,
            )
        )
        first_by_template: set[str] = set()
        for member in sorted(members, key=lambda item: item.anchor_position):
            if role == "section_header" and member.template not in first_by_template:
                first_by_template.add(member.template)
                retained_lines.add(member.line_index)
                continue
            removable.append(member)

    # An occurrence of the same line can be observed from both sides; claim
    # it for the side whose anchor is strictly closer to the line (a line
    # right after a break is a header, a line right before the next label is
    # a footer). Header groups are encountered first, so ties stay headers.
    # Virtual boundary anchors measure distance from the document start
    # (header side) or end (footer side). Lines explicitly retained by a
    # keep-first group are never removed by the other side's claim.
    def _anchor_distance(observation: _Observation) -> int:
        if observation.anchor_line is not None:
            return abs(observation.line_index - observation.anchor_line)
        if observation.side == "header":
            return observation.line_index + 1
        return len(lines) - observation.line_index

    unique_removable: dict[int, _Observation] = {}
    for observation in removable:
        if observation.line_index in retained_lines:
            continue
        previous = unique_removable.get(observation.line_index)
        if previous is None or _anchor_distance(observation) < _anchor_distance(
            previous
        ):
            unique_removable[observation.line_index] = observation
    removable = list(unique_removable.values())

    # Coalesce adjacent per-anchor spans (including opposite sides) into one
    # block span; every coalesced line is individually evidence-backed. The
    # block kind follows the side majority, ties stay headers.
    coalesced: list[list] = []  # [start_line, end_line, start, end, header, footer]
    for (
        start_line,
        end_line,
        span_start,
        span_end,
        side,
    ) in sorted(_merge_observations(removable, lines, offsets), key=lambda s: s[0]):
        line_count = end_line - start_line + 1
        if coalesced and span_start <= coalesced[-1][3] + 1:
            previous = coalesced[-1]
            previous[1] = max(previous[1], end_line)
            previous[3] = max(previous[3], span_end)
            if side == "header":
                previous[4] += line_count
            else:
                previous[5] += line_count
        else:
            coalesced.append(
                [
                    start_line,
                    end_line,
                    span_start,
                    span_end,
                    line_count if side == "header" else 0,
                    line_count if side == "footer" else 0,
                ]
            )
    for start_line, end_line, start, end, header_lines, footer_lines in coalesced:
        raw = text[start:end]
        side = "header" if header_lines >= footer_lines else "footer"
        kind = (
            PageMarkerKind.REPEATING_HEADER
            if side == "header"
            else PageMarkerKind.REPEATING_FOOTER
        )
        marker = PageMarker(
            start=start,
            end=end,
            text=raw,
            kind=kind,
            representation="html" if allow_table_furniture else "ascii",
            confidence=0.8,
            start_line=start_line,
            end_line=end_line,
            family=kind,
            evidence=("repeated_block", f"lines:{end_line - start_line + 1}"),
        )
        header_markers.append(marker)
        decisions.append(
            PageMarkerDecision(
                marker,
                PageMarkerAction.REMOVE,
                "repeating_furniture_block",
                0.8,
                marker.evidence,
            )
        )

    return tuple(templates), header_markers, decisions


__all__ = ["analyze_repeating_headers"]
