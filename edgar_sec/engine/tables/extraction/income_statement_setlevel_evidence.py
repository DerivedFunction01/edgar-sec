"""Income-statement set-level refusal stage evidence.

The filing-level stage of the routed income_statement
cascade: routing, uniqueness, dominant-cluster membership,
and cross-statement ties refusals, in that firing order.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.income_statement_setlevel_specs import (
    ANCHOR_FAMILIES,
    CORE_VOCAB_FRESH,
    FAMILY,
)
from edgar_sec.engine.tables.extraction.pension_routed_evidence import stub_key
from edgar_sec.engine.tables.extraction.primary_gate import (
    GATE_SETS,
    missing_sections,
    section_presence,
    statement_clusters,
)

_ROUTING_DETAIL = "income statement assignment: cross-family routing"
_UNIQUENESS_DETAIL = "income statement assignment: within-filing uniqueness"
_CLUSTER_DETAIL = "income statement assignment: outside dominant cluster"
_TIES_DETAIL = "income statement assignment: cross-statement ties"


def core_share(geometry) -> float:
    """Share of the priced core vocabulary among the stub keys."""
    if not CORE_VOCAB_FRESH:
        return 0.0
    keys = {stub_key(stub) for stub in geometry.stubs}
    return sum(1 for term in CORE_VOCAB_FRESH if term in keys) / len(
        CORE_VOCAB_FRESH
    )


def _canon(value: float) -> str | None:
    if abs(value - round(value)) > 0.01:
        return None
    digits = str(int(abs(round(value)))).rstrip("0")
    return digits if len(digits) >= 3 else None


def _cell_value(cell: str) -> float | None:
    text = cell.replace("$", "").replace(",", "").replace("%", "").strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def net_values(geometry) -> set[str]:
    """Canonical net-income values on the grid's net rows."""
    values: set[str] = set()
    for line in geometry.grid_text.splitlines():
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if not cells:
            continue
        if not section_presence((cells[0],), FAMILY)["net_income_close"]:
            continue
        for cell in cells[1:]:
            value = _cell_value(cell)
            if value is None:
                continue
            canon = _canon(value)
            if canon:
                values.add(canon)
    return values


def _grouped_families(result) -> set[str]:
    return set(result.claims) | set(result.contested)


def _dominant_cluster(clusters, results) -> tuple[int, ...] | None:
    """The filing's dominant statement cluster, or None.

    The cluster carrying a balance-sheet grouped record; with
    several, the one carrying the most grouped records; with
    none, the cluster carrying the most grouped records.
    """
    unique = list(dict.fromkeys(clusters))
    if not unique:
        return None

    def grouped_count(members) -> int:
        return sum(1 for m in members if _grouped_families(results[m]))

    anchored = [
        members
        for members in unique
        if any("balance_sheet" in _grouped_families(results[m]) for m in members)
    ]
    pool = anchored if anchored else unique
    counts = {members: grouped_count(members) for members in pool}
    best = max(counts.values())
    if not anchored and best == 0:
        return None
    tops = [members for members, count in counts.items() if count == best]
    return tops[0] if len(tops) == 1 else None


def apply_income_statement_assignment(geometries, results):
    """Filing-level pass: refuse set-level-failed IS claims.

    Runs in compete_filing's set-level sequence, before the
    primary gate's final pass; it only removes claims.
    """
    from edgar_sec.engine.tables.extraction.competition import (
        ClaimEvidence,
        CompetitionResult,
        FamilyScore,
    )

    targeted = [
        index
        for index, result in enumerate(results)
        if FAMILY in result.claims or FAMILY in result.contested
    ]
    if not targeted:
        return list(results)
    clusters = statement_clusters(geometries)
    cluster_stubs = {
        index: tuple(
            stub for member in clusters[index] for stub in geometries[member].stubs
        )
        for index in range(len(geometries))
    }

    def gate_complete_cluster(index) -> bool:
        return not missing_sections(cluster_stubs[index], FAMILY)

    def routing_refuses(index) -> bool:
        if gate_complete_cluster(index):
            return False
        own = geometries[index].stubs
        return any(
            not missing_sections(own, other)
            for other in GATE_SETS
            if other != FAMILY
        )

    def uniqueness_eliminated() -> set[int]:
        if len(targeted) < 2:
            return set()

        def rank(index):
            score = results[index].scores.get(FAMILY)
            return (
                gate_complete_cluster(index),
                score.total if score is not None else 0.0,
                core_share(geometries[index]),
            )

        keep = max(targeted, key=rank)
        return {index for index in targeted if index != keep}

    dominant = _dominant_cluster(clusters, results)

    def ties_refuses(index) -> bool:
        mine = net_values(geometries[index])
        if not mine:
            return False
        anchors: set[str] = set()
        statements = 0
        for other_index, result in enumerate(results):
            if other_index == index:
                continue
            if not (_grouped_families(result) & set(ANCHOR_FAMILIES)):
                continue
            values = net_values(geometries[other_index])
            if values:
                statements += 1
                anchors |= values
        return statements > 0 and not (mine & anchors)

    eliminated = uniqueness_eliminated()
    refused: dict[int, str] = {}
    for index in targeted:
        if routing_refuses(index):
            refused[index] = _ROUTING_DETAIL
        elif index in eliminated:
            refused[index] = _UNIQUENESS_DETAIL
        elif dominant is not None and clusters[index] != dominant:
            refused[index] = _CLUSTER_DETAIL
        elif ties_refuses(index):
            refused[index] = _TIES_DETAIL
    if not refused:
        return list(results)
    out = []
    for index, result in enumerate(results):
        if index not in refused:
            out.append(result)
            continue
        scores = dict(result.scores)
        score = scores.get(FAMILY)
        if score is not None:
            scores[FAMILY] = FamilyScore(
                score.family,
                score.total,
                dict(score.by_channel),
                score.evidence + (ClaimEvidence("gate", refused[index], 0.0),),
            )
        out.append(
            CompetitionResult(
                claims=tuple(name for name in result.claims if name != FAMILY),
                contested=tuple(
                    name for name in result.contested if name != FAMILY
                ),
                scores=scores,
                foreign_explained=result.foreign_explained,
                groups=result.groups,
            )
        )
    return out
