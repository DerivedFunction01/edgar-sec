"""Conservative repeated ASCII header/footer classification."""

from __future__ import annotations

from collections import defaultdict

from defs.text.logical_units import classify_units

from ..models import (
    PageMarker,
    PageMarkerAction,
    PageMarkerDecision,
    PageMarkerKind,
    TemplateEvidence,
)
from .candidates import line_offsets
from .windows import (
    LOCAL_DENSITY,
    PERSISTENT_MIN_ANCHORS,
    PERSISTENT_MIN_CLUSTERS,
    PERSISTENT_MIN_PRESENCE,
    Observation,
    clean_template,
    clusters,
    collect_window,
    eligible_line,
    merge_observations,
)


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
    groups: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    for side, direction in (("header", 1), ("footer", -1)):
        anchor_positions = {
            line: position for position, (line, _) in enumerate(side_scan[side])
        }
        for anchor, anchor_line in side_scan[side]:
            anchor_position = anchor_positions[anchor]
            for slot, (index, line) in enumerate(
                collect_window(lines, anchor, direction, boundary_lines)
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
            and cluster_count >= PERSISTENT_MIN_CLUSTERS
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
    # too sparse (for example the cover occurrence, where the furniture is
    # the second non-empty line from document start) to an accepted cluster
    # of the identical template. They inherit that cluster's role. Clusters
    # are addressed by index: one key can yield several accepted clusters.
    accepted_keys = {key for key, *_ in observed_groups}
    augmented_members: list[list[Observation]] = [
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


__all__ = ["analyze_repeating_headers"]
