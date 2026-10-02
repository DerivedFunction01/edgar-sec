"""Repeated header/footer classification and the evidence behind it.

A line is page furniture when it recurs at the same distance from a page anchor
on every page. That is the whole test, and it is deliberately narrow: the
window around each anchor is bounded, the observations are grouped by side and
slot so a header and a footer in the same place never compete, and a group is
only accepted when its local anchor cluster is dense enough or its recurrence
across the document is persistent enough.

Two acceptance tiers exist because a filing has two furniture habits. A dense
local run — a three-line block above every `<PAGE>` — is caught by the density
test. A banner that recurs on every few pages, with no dense run anywhere, is
caught by the persistence test instead, and the recurrence across the document
is then the evidence.

Removal is conservative in three further ways. A *section header* is kept once
per cohort rather than removed, because a recurring line that changes with the
section is a heading. A line observed from both sides is claimed by the side
whose anchor is strictly closer, so a line right after a break is a header and
a line right before the next label is a footer. And a block is only removed when
every line in it is individually evidence-backed, so a body line caught between
two furniture lines keeps the block intact.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .candidates import line_offsets, looks_like_prose
from .models import (
    PageMarker,
    PageMarkerAction,
    PageMarkerDecision,
    PageMarkerKind,
    TemplateEvidence,
)
from .units import classify_units

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

#: A page-furniture block recovered from inside a rendered table. Repeating
#: furniture is a compact table; a content table is not, and this is the size
#: bound that keeps the two apart.
MAX_FURNITURE_TABLE_LINES = 12

#: A banner must carry at least this many alphabetic words to be the line that
#: identifies a recovered table as furniture rather than a page number.
MIN_BANNER_WORDS = 3


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
    return trailing.strip() if alpha_words >= MIN_BANNER_WORDS else normalized.strip()


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
    """Return whether a candidate line may become a furniture observation.

    A line inside a table repeats because the table does, so it is refused
    unless the caller has already said that rendered table furniture is
    admissible. A table of contents line repeats because the contents do. A
    sentence repeats because the filing does.
    """
    stripped = line.strip()
    if not stripped or line_index in toc_lines:
        return False
    if is_table_tag(stripped):
        return allow_table
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
    *,
    allow_table: bool = False,
) -> list[tuple[int, str]]:
    """Collect a bounded non-empty furniture window around one anchor.

    The window is bounded in lines, in characters, and by the next page
    boundary, so a document whose cover has no break cannot donate its whole
    first page as a header block. A rendered table is taken whole when the
    caller admits table furniture, and is the end of the window when it does
    not.
    """
    result: list[tuple[int, str]] = []
    index = anchor + direction
    # Skip any contiguous boundary lines / consecutive <PAGE> tags at this anchor cluster
    while 0 <= index < len(lines) and (
        index in boundary_lines
        or lines[index].strip().casefold() in {"<page>", "</page>"}
    ):
        index += direction
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
            if not allow_table:
                break
            if direction > 0 and stripped.casefold() == "<table>":
                close_idx = next(
                    (
                        i
                        for i in range(
                            index + 1, min(len(lines), index + MAX_FURNITURE_LINES)
                        )
                        if lines[i].strip().casefold() == "</table>"
                    ),
                    None,
                )
                if close_idx is None:
                    break
                for tbl_i in range(index, close_idx + 1):
                    result.append((tbl_i, lines[tbl_i]))
                index = close_idx + 1
                continue
            if direction < 0 and stripped.casefold() == "</table>":
                open_idx = next(
                    (
                        i
                        for i in range(
                            index - 1, max(-1, index - MAX_FURNITURE_LINES), -1
                        )
                        if lines[i].strip().casefold() == "<table>"
                    ),
                    None,
                )
                if open_idx is None:
                    break
                for tbl_i in range(index, open_idx - 1, -1):
                    result.append((tbl_i, lines[tbl_i]))
                index = open_idx - 1
                continue
            break
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
    """Split observations into local anchor clusters with local density.

    A cluster is a run of adjacent anchors: positions no more than
    ``MAX_ANCHOR_GAP`` apart. Its density is the fraction of anchor positions in
    that span at which the template was observed, so a run of three anchors
    with the template on all three has density 1.0 and a run of four with it on
    three does not.
    """
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
    """Merge only fully validated adjacent lines into block spans.

    Two lines merge into one span only when every line between them is empty or
    a structural table tag, or is another selected line. A body line caught
    between two furniture lines splits the span, so the block removal never
    covers a line that was not itself evidence-backed.
    """
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


def _deduplicate_anchors(anchor_lines: list[int]) -> list[int]:
    """Collapse physical anchor lines within <= 2 lines of each other.

    Consecutive or tightly clustered anchors (e.g. from multiple break
    mechanisms for a single page transition) are merged into one,
    preventing anchor denominator inflation.
    """
    if not anchor_lines:
        return []
    deduped = [anchor_lines[0]]
    for line in anchor_lines[1:]:
        if line - deduped[-1] > 2:
            deduped.append(line)
    return deduped


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
    """Classify bounded repeated text adjacent to accepted page anchors.

    The two anchor sets are supplied separately because a document can be
    asymmetric: a filing that states a structural break but no page number
    anchors its furniture from the break side only. The entry guard is
    ``max(header_count, footer_count) < 3`` over the *deduplicated* sets, which
    with asymmetric anchors means both sides must fall short of three before
    nothing is analysed.
    """
    lines = text.splitlines()
    offsets = line_offsets(lines)
    toc_lines = toc_lines or set()
    anchors = sorted(
        {marker.start_line for marker in markers if marker.start_line is not None}
    )
    header_anchor_lines = _deduplicate_anchors(header_anchors or anchors)
    footer_anchor_lines = _deduplicate_anchors(footer_anchors or anchors)
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
        if "<" in line:
            stripped = line.strip().casefold()
            if "<table>" in stripped:
                table_depth += stripped.count("<table>")
            if table_depth:
                units_by_line[line_index] = "table"
            if "</table>" in stripped:
                table_depth = max(0, table_depth - stripped.count("</table>"))
        elif table_depth:
            units_by_line[line_index] = "table"
    boundary_lines = boundary_lines or {
        line
        for marker in markers
        for line in range(marker.start_line or 0, (marker.end_line or 0) + 1)
    }
    groups: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    for side, direction in (("header", 1), ("footer", -1)):
        anchor_positions = {
            line: position for position, (line, _) in enumerate(side_scan[side])
        }
        for anchor, anchor_line in side_scan[side]:
            anchor_position = anchor_positions[anchor]
            for slot, (index, line) in enumerate(
                collect_window(
                    lines,
                    anchor,
                    direction,
                    boundary_lines,
                    allow_table=allow_table_furniture,
                )
            ):
                if not eligible_line(
                    line,
                    toc_lines,
                    index,
                    units_by_line.get(index),
                    allow_table=allow_table_furniture,
                ):
                    continue
                template = clean_template(line)
                if template:
                    groups[(side, slot, template)].append(
                        Observation(
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
    removable: list[Observation] = []
    retained_lines: set[int] = set()
    observed_groups: list[
        tuple[tuple[str, int, str], list[Observation], int, int, float]
    ] = []

    for key, members in groups.items():
        side, position, template = key
        for cluster_members, start, end, presence in clusters(members):
            positions = {member.anchor_position for member in cluster_members}
            if len(positions) < 3 or presence < LOCAL_DENSITY:
                continue
            if len(positions) == 3 and not allow_table_furniture and presence < 1.0:
                continue
            observed_groups.append((key, cluster_members, start, end, presence))

    # Document-persistent tier: some filings repeat furniture steadily across
    # the whole document (a "Table of Contents" header or a company banner
    # footer on every few pages) without any dense local run. When the same
    # normalized template recurs on at least PERSISTENT_MIN_ANCHORS anchors,
    # covers at least PERSISTENT_MIN_PRESENCE of the side's anchors, and is
    # split into at least PERSISTENT_MIN_CLUSTERS separate clusters, the
    # recurrence itself is the evidence.
    accepted_keys = {key for key, *_ in observed_groups}
    side_anchor_counts = {side: len(scan) for side, scan in side_scan.items()}
    for key, members in groups.items():
        if key in accepted_keys:
            continue
        side, _, _ = key
        positions = {member.anchor_position for member in members}
        cluster_count = len(clusters(members))
        if (
            len(positions) >= PERSISTENT_MIN_ANCHORS
            and len(positions) / side_anchor_counts[side] >= PERSISTENT_MIN_PRESENCE
            and (
                cluster_count >= PERSISTENT_MIN_CLUSTERS
                or (
                    len(positions) >= 8
                    and len(positions) / side_anchor_counts[side] >= 0.05
                )
            )
        ):
            observed_groups.append(
                (
                    key,
                    list(members),
                    0,
                    side_anchor_counts[side] - 1,
                    len(positions) / side_anchor_counts[side],
                ),
            )

    # Attach same-side/same-template observations whose own slot group was
    # too sparse or isolated to an accepted cluster of the identical template.
    # They inherit that cluster's role. Clusters are addressed by index:
    # one key can yield several accepted clusters.
    augmented_members: list[list[Observation]] = [
        sorted(members, key=lambda item: (item.anchor_position, item.line_index))
        for _, members, _, _, _ in observed_groups
    ]
    accepted_obs_ids = {id(obs) for members in augmented_members for obs in members}
    for key, observations in groups.items():
        side, _, template = key
        candidate_indexes = [
            index
            for index, entry in enumerate(observed_groups)
            if entry[0][0] == side and entry[0][2] == template
        ]
        if not candidate_indexes:
            continue
        for observation in observations:
            if id(observation) in accepted_obs_ids:
                continue
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
                accepted_obs_ids.add(id(observation))

    # Recover isolated tagged-table furniture that falls between accepted
    # anchors. A page can be absent from the numeric anchor run while its
    # repeated footer remains unambiguous (for example pages 59 and 78 in
    # filings with missing page markers). Once footer templates have passed
    # the repetition checks above, a compact table whose content consists
    # entirely of those templates — including at least one banner-like
    # template — is furniture and safe to remove. Structural table tags and
    # dash-only separator lines never trigger recovery on their own, so
    # content tables that merely contain a dashed rule are preserved.
    footer_groups = {
        (key[1], key[2]): index
        for index, (key, *_rest) in enumerate(observed_groups)
        if key[0] == "footer"
    }
    if footer_groups and allow_table_furniture:
        footer_templates = {template for _, template in footer_groups}
        banner_templates = {
            template
            for template in footer_templates
            if (
                sum(1 for word in template.split() if any(ch.isalpha() for ch in word))
                >= MIN_BANNER_WORDS
            )
        }
        table_starts: list[int] = []
        for line_index, line in enumerate(lines):
            stripped = line.strip().casefold()
            if stripped == "<table>":
                table_starts.append(line_index)
                continue
            if stripped != "</table>" or not table_starts:
                continue
            table_start = table_starts.pop()
            # Repeated page furniture is a compact table. Never promote
            # content inside or beyond this size bound.
            if line_index - table_start > MAX_FURNITURE_TABLE_LINES:
                continue
            content_templates = [
                clean_template(content_line)
                for content_line in lines[table_start + 1 : line_index]
                if content_line.strip()
            ]
            if not content_templates:
                continue
            if any(template not in footer_templates for template in content_templates):
                continue
            if not any(template in banner_templates for template in content_templates):
                continue
            banner_offset = next(
                offset
                for offset, content_line in enumerate(
                    lines[table_start + 1 : line_index]
                )
                if content_line.strip()
                and clean_template(content_line) in banner_templates
            )
            banner_template = clean_template(lines[table_start + 1 + banner_offset])
            for (position, template), group_index in footer_groups.items():
                if template != banner_template:
                    continue
                if any(
                    member.line_index >= table_start and member.line_index < line_index
                    for member in augmented_members[group_index]
                ):
                    continue
                augmented_members[group_index].append(
                    Observation(
                        "footer",
                        position,
                        template,
                        table_start + 1 + banner_offset,
                        lines[table_start + 1 + banner_offset],
                        len(augmented_members[group_index]) + 1,
                        None,
                    )
                )

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
    def _anchor_distance(observation: Observation) -> int:
        if observation.anchor_line is not None:
            return abs(observation.line_index - observation.anchor_line)
        if observation.side == "header":
            return observation.line_index + 1
        return len(lines) - observation.line_index

    unique_removable: dict[int, Observation] = {}
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
    ) in sorted(merge_observations(removable, lines, offsets), key=lambda s: s[0]):
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


__all__ = [
    "LOCAL_DENSITY",
    "MAX_ANCHOR_GAP",
    "MAX_FURNITURE_CHARS",
    "MAX_FURNITURE_LINES",
    "PERSISTENT_MIN_ANCHORS",
    "PERSISTENT_MIN_CLUSTERS",
    "PERSISTENT_MIN_PRESENCE",
    "Observation",
    "analyze_repeating_headers",
    "clean_template",
    "clusters",
    "collect_window",
    "eligible_line",
    "is_table_tag",
    "merge_observations",
]
