"""Assembly: a filing's classified tables grouped and arbitrated.

Grouping joins split fragments into logical tables; relational
arbitration consumes measured containment, links co-note siblings,
ranks single-main slots, and records every act with provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from edgar_sec.engine.tables.extraction.classify import (
    Classification,
    TableKind,
    classify_filing,
)
from edgar_sec.engine.tables.extraction.context import Scale, TableContext
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.policy import (
    ClassificationPolicy,
    default_policy,
)
from edgar_sec.engine.tables.extraction.registry import (
    ASSIGNMENT_FLOOR,
    CONTAINMENT_PARENTS,
    CONTAINMENT_SUBSETS,
    CORE_FAMILIES,
    CO_NOTE_SIBLINGS,
    FAMILY_PRIORITY,
    PROV_CONTAINMENT,
    RESIDUAL_FAMILY,
    SHAPE_BOUNDS_BY_FAMILY,
    SLOT_MAIN_MIN_CANDIDACY,
)
from edgar_sec.engine.tables.extraction.typed_rows import (
    ColumnPeriod,
    RowKind,
    TypedTable,
    structure_table,
)
from edgar_sec.engine.tables.extraction.validation import evaluate_math

SIGNAL_ASSEMBLY_INCOMPLETE = "assembly_incomplete"
SIGNAL_KIND_UNCERTAIN = "kind_uncertain"
SIGNAL_SCALE_UNSTATED = "scale_unstated"
SIGNAL_BS_IDENTITY_FAILED = "bs_identity_failed"

_PROV_ASSEMBLY = "step7:assembly"
_PROV_CASCADE = "step4:cascade"
_PROV_SECOND_SET = "step8c:second_set"
SECOND_SET_TAG = "second_set"
_DUAL_PARENT = ("fair_value", "balance_sheet")
_STRONG_SIGNALS = ("continued marker", "joint closure")
# A non-strong signal corroborates only a fragment whose own top
# candidacy carries at least half the assignment floor in evidence.
RESIDUAL_JOIN_MIN_SCORE = ASSIGNMENT_FLOOR / 2


def _note_key(context: TableContext) -> str | None:
    note = context.note
    if note is None:
        return None
    if note.number is not None:
        return f"n{note.number}"
    if note.title:
        return "t:" + normalize_text(note.title)
    if note.label:
        return "l:" + normalize_text(note.label)
    return None


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    """One relational-arbitration act, with its provenance."""

    kind: str
    detail: str
    provenance: str


@dataclass(frozen=True, slots=True)
class AssembledTable:
    """One logical table: a ranked group with sections and tags."""

    family: str
    flavor: str | None
    kind: TableKind
    role: str
    members: tuple[int, ...]
    sections: tuple[str, ...]
    section_members: tuple[int, ...]
    tags: tuple[str, ...]
    score: float
    value_rows: int
    scale: Scale | None
    periods: tuple[ColumnPeriod, ...]
    signals: tuple[str, ...]
    decisions: tuple[ArbitrationDecision, ...]


@dataclass(frozen=True, slots=True)
class NoteGroup:
    """The geometries sharing one note, with sibling links."""

    key: str
    members: tuple[int, ...]
    families: tuple[str, ...]
    siblings: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class GeometryAssignment:
    """A geometry's effective family after assembly arbitration."""

    table_index: int
    family: str
    mechanism: str


@dataclass(frozen=True, slots=True)
class FilingAssembly:
    """A filing's assembled tables, note groups, and assignments."""

    tables: tuple[AssembledTable, ...]
    note_groups: tuple[NoteGroup, ...]
    assignments: tuple[GeometryAssignment, ...]
    unassigned: tuple[int, ...]
    decisions: tuple[ArbitrationDecision, ...]


@dataclass(slots=True)
class _Member:
    """One classified geometry inside the assembly working set."""

    position: int
    table: TypedTable
    result: Classification
    scores: dict[str, float]

    @property
    def table_index(self) -> int:
        return self.table.context.table_index

    @property
    def family(self) -> str:
        return self.result.family

    @property
    def value_rows(self) -> int:
        return sum(
            1 for row in self.table.rows if any(v is not None for v in row.values)
        )


@dataclass(slots=True)
class _Group:
    """A logical table under construction: one family's fragments."""

    family: str
    members: list[_Member]
    decisions: list[ArbitrationDecision] = field(default_factory=list)
    sections: set[str] = field(default_factory=set)
    section_members: list[int] = field(default_factory=list)
    extra_tags: set[str] = field(default_factory=set)
    role: str = "variant"

    @property
    def first(self) -> _Member:
        return self.members[0]

    @property
    def last(self) -> _Member:
        return self.members[-1]

    @property
    def rank(self) -> tuple[float, int, int, int]:
        """Slot rank: family score, specific tier, size, earliness."""
        specific = 1 if any(m.result.tier == "specific" for m in self.members) else 0
        score = max((m.scores.get(self.family, 0.0) for m in self.members), default=0.0)
        score = max(
            score,
            max(
                (m.result.score for m in self.members if m.family == self.family),
                default=0.0,
            ),
        )
        rows = sum(m.value_rows for m in self.members)
        return (score, specific, rows, -self.first.position)


def _period_signature(table: TypedTable) -> tuple[str | None, ...]:
    return tuple(period.label for period in table.periods)


def _joint_bs_closes(group: _Group, member: _Member) -> bool:
    rows = tuple(row for m in group.members for row in m.table.rows)
    merged = replace(member.table, rows=rows + member.table.rows)
    return any(
        outcome.family == "balance_sheet" and outcome.closed
        for outcome in evaluate_math(merged)
    )


def _continuity(group: _Group, member: _Member) -> str | None:
    """The join signal between a group and a following fragment."""
    last = group.last
    if member.table.continued:
        return "continued marker"
    member_titles = {normalize_text(title) for title in member.table.caption.titles}
    last_titles = {normalize_text(title) for title in last.table.caption.titles}
    overlap = bool(member_titles & last_titles)
    fresh = bool(member_titles) and not overlap
    if not fresh:
        signature = _period_signature(member.table)
        if signature == _period_signature(last.table) and any(
            label is not None for label in signature
        ):
            return "period continuity"
    if group.family == "balance_sheet" and _joint_bs_closes(group, member):
        return "joint closure"
    return None


def _gap_ok(group: _Group, member: _Member, members: list[_Member]) -> bool:
    gap = member.position - group.last.position
    if gap == 1:
        return True
    if gap == 2:
        return members[member.position - 1].family == RESIDUAL_FAMILY
    return False


def _group_winners(members: list[_Member]) -> list[_Group]:
    groups: list[_Group] = []
    latest: dict[str, _Group] = {}
    for member in members:
        if member.family == RESIDUAL_FAMILY:
            continue
        group = latest.get(member.family)
        signal = None
        if group is not None and _gap_ok(group, member, members):
            signal = _continuity(group, member)
        if group is not None and signal is not None:
            group.members.append(member)
            group.decisions.append(
                ArbitrationDecision(
                    "join",
                    f"table {member.table_index} joins on {signal}",
                    _PROV_ASSEMBLY,
                )
            )
        else:
            group = _Group(member.family, [member])
            groups.append(group)
        latest[member.family] = group
    return groups


def _join_residuals(
    members: list[_Member], groups: list[_Group], consumed: set[int]
) -> None:
    latest: dict[str, _Group] = {}
    owner: dict[int, _Group] = {}
    for group in groups:
        latest[group.family] = group
        for member in group.members:
            owner[member.position] = group
    for member in members:
        if member.family != RESIDUAL_FAMILY or member.position in consumed:
            continue
        if not member.scores:
            continue
        top = min(
            member.scores,
            key=lambda family: (
                -member.scores[family],
                FAMILY_PRIORITY.index(family),
            ),
        )
        group: _Group | None = None
        behind = owner.get(member.position - 1)
        behind_ok = behind is not None and _gap_ok(behind, member, members)
        if behind_ok and _continuity(behind, member) in _STRONG_SIGNALS:
            group = behind
        elif member.scores[top] > 0:
            candidate = latest.get(top)
            if (
                candidate is not None
                and candidate.last.position < member.position
                and _gap_ok(candidate, member, members)
            ):
                group = candidate
        elif behind_ok:
            group = behind
        if group is None:
            continue
        signal = _continuity(group, member)
        if signal is None:
            continue
        if (
            signal not in _STRONG_SIGNALS
            and member.scores[top] < RESIDUAL_JOIN_MIN_SCORE
        ):
            continue
        group.members.append(member)
        consumed.add(member.position)
        group.decisions.append(
            ArbitrationDecision(
                "join",
                f"residual table {member.table_index} joins as a fragment on {signal}",
                _PROV_ASSEMBLY,
            )
        )


def _consume_sections(
    groups: list[_Group], filing: list[ArbitrationDecision]
) -> dict[int, str]:
    sectioned: dict[int, str] = {}
    for group in groups:
        for subset in CONTAINMENT_SUBSETS.get(group.family, ()):
            if any(
                member.family == group.family
                and member.scores.get(subset, 0.0) >= ASSIGNMENT_FLOOR
                for member in group.members
            ):
                group.sections.add(subset)
                group.decisions.append(
                    ArbitrationDecision(
                        "section",
                        f"{subset} signature inside the {group.family} "
                        "assignment is a section, not a rival",
                        PROV_CONTAINMENT,
                    )
                )
    for group in list(groups):
        parent = CONTAINMENT_PARENTS.get(group.family)
        if parent is None:
            continue
        keys = {_note_key(m.table.context) for m in group.members} - {None}
        if not keys:
            continue
        host = next(
            (
                candidate
                for candidate in groups
                if candidate.family == parent
                and candidate is not group
                and keys & {_note_key(m.table.context) for m in candidate.members}
            ),
            None,
        )
        if host is None:
            continue
        host.sections.add(group.family)
        host.section_members.extend(member.table_index for member in group.members)
        for member in group.members:
            sectioned[member.position] = group.family
        host.decisions.append(
            ArbitrationDecision(
                "section",
                f"{group.family} tables sharing the note are sections "
                f"of the {parent} assembly",
                PROV_CONTAINMENT,
            )
        )
        filing.append(
            ArbitrationDecision(
                "section",
                f"{group.family} group consumed as {parent} sections",
                PROV_CONTAINMENT,
            )
        )
        groups.remove(group)
    return sectioned


def _dual_service(groups: list[_Group]) -> None:
    for group in groups:
        if group.family != _DUAL_PARENT[0]:
            continue
        if any(
            member.scores.get(_DUAL_PARENT[1], 0.0) >= ASSIGNMENT_FLOOR
            for member in group.members
        ):
            group.extra_tags.add(_DUAL_PARENT[1])
            group.decisions.append(
                ArbitrationDecision(
                    "dual",
                    "balance_sheet candidacy above the floor inside a "
                    "fair_value table serves both assemblies",
                    PROV_CONTAINMENT,
                )
            )


def _rival_decisions(members: list[_Member], filing: list[ArbitrationDecision]) -> None:
    for member in members:
        above = sorted(
            (
                family
                for family, score in member.scores.items()
                if score >= ASSIGNMENT_FLOOR and family != member.family
            ),
            key=FAMILY_PRIORITY.index,
        )
        if not above:
            continue
        if member.result.tier == "specific":
            filing.append(
                ArbitrationDecision(
                    "override",
                    f"table {member.table_index}: specific {member.family} "
                    f"overrides {', '.join(above)}",
                    _PROV_CASCADE,
                )
            )
        for family in above:
            if CONTAINMENT_PARENTS.get(family) == member.family:
                continue
            if CONTAINMENT_PARENTS.get(member.family) == family:
                continue
            if (member.family, family) == _DUAL_PARENT:
                continue
            filing.append(
                ArbitrationDecision(
                    "suppress",
                    f"table {member.table_index}: {family} candidacy "
                    f"stands down to {member.family}",
                    _PROV_ASSEMBLY,
                )
            )


def _main_eligible(group: _Group) -> bool:
    """A main needs the family's own candidacy: scored evidence at the
    main minimum, or a label-rule win over the members' own labels."""
    if group.rank[0] >= SLOT_MAIN_MIN_CANDIDACY:
        return True
    return any(
        entry.group == "label_rule"
        for member in group.members
        for entry in member.result.evidence
    )


def _rank_slots(groups: list[_Group]) -> None:
    by_family: dict[str, list[_Group]] = {}
    for group in groups:
        by_family.setdefault(group.family, []).append(group)
    for family, candidates in by_family.items():
        ranked = sorted(candidates, key=lambda group: group.rank, reverse=True)
        main = ranked[0]
        if not _main_eligible(main):
            main.role = "variant"
            main.decisions.append(
                ArbitrationDecision(
                    "slot",
                    f"no main for {family}: best candidacy {main.rank[0]:.2f} "
                    f"under the main minimum {SLOT_MAIN_MIN_CANDIDACY:.2f}",
                    _PROV_ASSEMBLY,
                )
            )
            for group in ranked[1:]:
                group.role = "variant"
                group.decisions.append(
                    ArbitrationDecision(
                        "slot",
                        f"variant of {family}: no main designated",
                        _PROV_ASSEMBLY,
                    )
                )
            continue
        main.role = "main"
        main.decisions.append(
            ArbitrationDecision(
                "slot",
                f"main of {len(ranked)} {family} candidate group(s)",
                _PROV_ASSEMBLY,
            )
        )
        for group in ranked[1:]:
            group.role = "variant"
            group.decisions.append(
                ArbitrationDecision(
                    "slot",
                    f"variant below the {family} main at table "
                    f"{main.first.table_index}",
                    _PROV_ASSEMBLY,
                )
            )


def _finalize(group: _Group) -> AssembledTable:
    head = group.first
    rows = tuple(row for member in group.members for row in member.table.rows)
    value_rows = sum(member.value_rows for member in group.members)
    kinds = {member.result.kind for member in group.members}
    parenthetical = sum(1 for row in rows if row.kind is RowKind.PARENTHETICAL)
    if rows and parenthetical * 2 >= len(rows):
        kind = TableKind.PARENTHETICAL
    else:
        kind = head.result.kind
    signals: list[str] = []
    if len(kinds) > 1:
        signals.append(SIGNAL_KIND_UNCERTAIN)
    scale = next(
        (member.table.scale for member in group.members if member.table.scale),
        None,
    )
    if scale is None:
        signals.append(SIGNAL_SCALE_UNSTATED)
    bound = SHAPE_BOUNDS_BY_FAMILY.get(group.family)
    if bound is not None and value_rows < bound.assembled_rows_p5:
        signals.append(SIGNAL_ASSEMBLY_INCOMPLETE)
    if group.family == "balance_sheet" and group.role == "main":
        merged = replace(head.table, rows=rows)
        outcome = next(
            (
                outcome
                for outcome in evaluate_math(merged)
                if outcome.family == "balance_sheet"
            ),
            None,
        )
        if outcome is not None and not outcome.closed:
            signals.append(SIGNAL_BS_IDENTITY_FAILED)
    tags = tuple(
        dict.fromkeys(
            [group.family, *sorted(group.sections), *sorted(group.extra_tags)]
        )
    )
    return AssembledTable(
        family=group.family,
        flavor=head.result.flavor,
        kind=kind,
        role=group.role,
        members=tuple(member.table_index for member in group.members),
        sections=tuple(sorted(group.sections)),
        section_members=tuple(group.section_members),
        tags=tags,
        score=group.rank[1],
        value_rows=value_rows,
        scale=scale,
        periods=head.table.periods,
        signals=tuple(signals),
        decisions=tuple(group.decisions),
    )


def _total_lines(table: TypedTable) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in table.rows:
        label = normalize_text(row.label)
        if not label.startswith("total"):
            continue
        value = next((v for v in row.values if v is not None), None)
        if value is not None:
            totals.setdefault(label, value)
    return totals


def _tag_second_sets(groups: list[_Group]) -> None:
    """A core variant whose totals conflict with the main's is a
    second statement set: a set boundary, not a fragment or a rival."""
    for family in CORE_FAMILIES:
        main = next(
            (g for g in groups if g.family == family and g.role == "main"),
            None,
        )
        if main is None:
            continue
        main_totals = _total_lines(main.first.table)
        if not main_totals:
            continue
        for group in groups:
            if group.family != family or group is main or group.role != "variant":
                continue
            if group.first.position <= main.first.position:
                continue
            totals = _total_lines(group.first.table)
            conflicts = sorted(
                label
                for label in set(totals) & set(main_totals)
                if totals[label] != main_totals[label]
            )
            if not conflicts:
                continue
            group.extra_tags.add(SECOND_SET_TAG)
            group.decisions.append(
                ArbitrationDecision(
                    "second_set",
                    f"totals differ from the {family} main on "
                    f"{conflicts[0]}: a second statement set",
                    _PROV_SECOND_SET,
                )
            )


def _note_groups(
    members: list[_Member], filing: list[ArbitrationDecision]
) -> tuple[NoteGroup, ...]:
    by_key: dict[str, list[_Member]] = {}
    for member in members:
        key = _note_key(member.table.context)
        if key is not None:
            by_key.setdefault(key, []).append(member)
    note_groups: list[NoteGroup] = []
    for key, grouped in by_key.items():
        families = tuple(sorted({member.family for member in grouped}))
        siblings = tuple(
            spec.families
            for spec in CO_NOTE_SIBLINGS
            if all(family in families for family in spec.families)
        )
        if siblings:
            filing.append(
                ArbitrationDecision(
                    "co_note",
                    f"note {key} links {siblings[0][0]} and "
                    f"{siblings[0][1]} as one note's tables",
                    PROV_CONTAINMENT,
                )
            )
        note_groups.append(
            NoteGroup(
                key=key,
                members=tuple(member.table_index for member in grouped),
                families=families,
                siblings=siblings,
            )
        )
    return tuple(note_groups)


def assemble(
    contexts: list[TableContext] | tuple[TableContext, ...],
    policy: ClassificationPolicy | None = None,
) -> FilingAssembly:
    """Assemble one filing's contexts into arbitrated statements."""
    policy = policy if policy is not None else default_policy()
    tables = [structure_table(context) for context in contexts]
    outcomes = [evaluate_math(table) for table in tables]
    results, filing_scores = classify_filing(tables, policy, outcomes)
    members: list[_Member] = []
    for position, context in enumerate(contexts):
        members.append(
            _Member(
                position=position,
                table=tables[position],
                result=results[position],
                scores=filing_scores[position],
            )
        )
    filing: list[ArbitrationDecision] = []
    groups = _group_winners(members)
    consumed = {member.position for group in groups for member in group.members}
    _join_residuals(members, groups, consumed)
    sectioned = _consume_sections(groups, filing)
    _dual_service(groups)
    _rival_decisions(members, filing)
    _rank_slots(groups)
    _tag_second_sets(groups)
    note_groups = _note_groups(members, filing)
    tables = tuple(_finalize(group) for group in groups)
    by_position: dict[int, GeometryAssignment] = {}
    for group in groups:
        for member in group.members:
            by_position[member.position] = GeometryAssignment(
                member.table_index,
                group.family,
                "winner" if member.family == group.family else "join",
            )
    for position, family in sectioned.items():
        member = members[position]
        by_position[position] = GeometryAssignment(
            member.table_index, family, "section"
        )
    unassigned: list[int] = []
    for member in members:
        if member.position not in by_position:
            by_position[member.position] = GeometryAssignment(
                member.table_index, RESIDUAL_FAMILY, "residual"
            )
            unassigned.append(member.table_index)
    assignments = tuple(by_position[member.position] for member in members)
    return FilingAssembly(
        tables=tables,
        note_groups=note_groups,
        assignments=assignments,
        unassigned=tuple(unassigned),
        decisions=tuple(filing),
    )
