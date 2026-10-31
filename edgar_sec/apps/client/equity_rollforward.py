"""Equity rollforward builder: the statement of changes in equity.

The builder discovers the balance concept and its components axis
from the filed instant totals; each component verifies by its own
identity, and the components tie to the total by antichain.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.apps.client.topics import _NON_MONETARY, _AtomSource, accumulate_movement
from edgar_sec.engine.xbrl.evidence.subsumption import MemberSubsumption
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import DefinitionArc, XbrlFact, qname_local
from edgar_sec.engine.xbrl.solve.identities import movement_sign
from edgar_sec.engine.xbrl.solve.rollforward_graphs import (
    EquityComponentRollforward,
    EquityRollforwardGraph,
)
from edgar_sec.engine.xbrl.solve.statement import StatementNode, period_rank
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def _equity_balance_tier(atom: Atom) -> int | None:
    """Balance tier for an equity-total atom, or None when not a total."""
    mods = atom.modifiers
    if atom.head != "H_EQUITY":
        return None
    if not mods:
        return 0
    if mods == {"M_NONCONTROLLING_INTEREST"}:
        return 1
    return None


def _is_oci_total(atom: Atom) -> bool:
    """Whether the atom is a net-of-tax OCI total, not a decomposition."""
    return (
        atom.head == "H_INCOME"
        and "M_OCI" in atom.modifiers
        and "V_NET" in atom.modifiers
        and atom.modifiers <= {"M_OCI", "V_NET", "M_ATTRIBUTABLE_PARENT"}
    )


def _equity_role(
    atom: Atom,
    *,
    member_is_treasury: bool,
    has_oci_total: bool,
) -> str | None:
    """Movement role for one equity-statement fact, or None to exclude.

    The role's sign is declared valence data, applied by the caller.
    """
    mods = atom.modifiers
    if atom.head == "H_INCOME" and ("M_NET_BOTTOMLINE" in mods or not mods):
        return "net_income"
    if _is_oci_total(atom):
        return "oci"
    if "M_OCI" in mods or "M_COMPREHENSIVE" in mods or "M_RECLASSIFIED_OCI" in mods:
        if has_oci_total or "M_COMPREHENSIVE" in mods:
            return None
        if "M_PRETAX" in mods or "M_CURRENT" in mods:
            return None
        if "M_TAX" in mods and "V_NET" not in mods and "M_POST_TAX" not in mods:
            return None
        return "oci" if atom.head == "H_INCOME" else None
    if "M_DIVIDEND" in mods:
        return "dividends"
    if "M_TREASURY_REPURCHASE" in mods and "M_ACQUIRED" in mods:
        return "treasury_acquired" if member_is_treasury else None
    if "M_TREASURY_REPURCHASE" in mods and "M_REISSUED" in mods:
        return "treasury_reissued"
    if (
        atom.head == "H_EQUITY"
        and "M_TREASURY_REPURCHASE" in mods
        and "M_WEIGHTED_AVERAGE" not in mods
    ):
        return "repurchase"
    if atom.head == "H_EQUITY" and "M_ISSUANCE" in mods:
        return "issuance"
    if "M_APIC" in mods and "M_SBC" in mods:
        return "share_based_compensation"
    if "M_WITHHOLDING" in mods:
        return "tax_withholding"
    if "M_CHANGE" in mods:
        return "net_change"
    if "M_PRETAX" in mods or ("M_TAX" in mods and "V_NET" not in mods):
        return None
    if atom.head in {"H_EQUITY", "H_EXPENSE", "H_COST", "H_SHARE"}:
        return "other"
    return None


def _equity_antichain(
    components: Sequence[EquityComponentRollforward],
    target: float | None,
    *,
    subsumption: MemberSubsumption | None = None,
    axis: str | None = None,
) -> tuple[str, ...]:
    """Antichain members, largest closing first.

    With definition arcs the subsumption frontier decides candidacy and
    the graph's identity check against the filed total remains the verdict.
    """
    members = [
        (comp.member_qname, comp.closing)
        for comp in components
        if comp.closing is not None
    ]
    if subsumption is not None and axis is not None:
        frontier = subsumption.frontier(axis, [member for member, _v in members])
        if frontier is not None:
            keep = set(frontier)
            ordered = sorted(
                (item for item in members if item[0] in keep),
                key=lambda item: (-abs(item[1]), item[0]),  # type: ignore[arg-type]
            )
            return tuple(member for member, _value in ordered)
    return _equity_antichain_fallback(members, target)


def _equity_antichain_fallback(
    members: list[tuple[str, float | None]], target: float | None
) -> tuple[str, ...]:
    """Labelled fallback for arc-less filings: subset-sum search.

    Only for filings without usable definition arcs for the axis; the
    search decides inclusion by reconciliation to the filed total.
    """
    if target is None:
        return tuple(member for member, _value in members)
    ordered = sorted(members, key=lambda item: (-abs(item[1]), item[0]))  # type: ignore[arg-type]
    values = [float(value) for _member, value in ordered]  # type: ignore[arg-type]
    suffix_pos = [0.0] * (len(values) + 1)
    suffix_neg = [0.0] * (len(values) + 1)
    for i in range(len(values) - 1, -1, -1):
        suffix_pos[i] = suffix_pos[i + 1] + max(values[i], 0.0)
        suffix_neg[i] = suffix_neg[i + 1] + min(values[i], 0.0)
    chosen: list[str] = []

    def dfs(index: int, remaining: float) -> bool:
        if abs(remaining) <= 1.0:
            return True
        if index == len(ordered):
            return False
        if remaining - suffix_pos[index] > 1.0 or remaining - suffix_neg[index] < -1.0:
            return False
        chosen.append(ordered[index][0])
        if dfs(index + 1, remaining - values[index]):
            return True
        chosen.pop()
        return dfs(index + 1, remaining)

    if dfs(0, target):
        return tuple(chosen)
    return tuple(member for member, _value in members)


def build_equity_rollforward(
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    labels: Mapping[str, str] | None = None,
    year: int | str | None = None,
    *,
    member_qname: str | None = None,
    definition_arcs: Sequence[DefinitionArc] = (),
) -> EquityRollforwardGraph:
    """Resolve the statement of changes in equity for one annual period.

    The balance concept and its components axis are discovered from the
    filed instant totals; each component verifies by its own identity.
    """
    source = _AtomSource(records, taxonomy)
    lbl_map = dict(labels or {})
    target_year = str(year) if year is not None else None
    tiers: dict[str, int] = {}
    for f in facts:
        if f.period_type != "instant" or not isinstance(f.value, (int, float)):
            continue
        if f.unit in _NON_MONETARY:
            continue
        tier = _equity_balance_tier(source.atom(f.concept_qname))
        if tier is not None:
            tiers[f.concept_qname] = tier
    concept: str | None = None
    axis: str | None = None
    for tier in (0, 1):
        scored: list[tuple[int, str, str]] = []
        for qname, q_tier in tiers.items():
            if q_tier != tier:
                continue
            dim_facts = [
                f
                for f in facts
                if f.concept_qname == qname
                and f.period_type == "instant"
                and len(f.dimensions) == 1
            ]
            if dim_facts:
                axes = Counter(next(iter(f.dimensions)) for f in dim_facts)
                top_axis, _count = axes.most_common(1)[0]
                scored.append((len(dim_facts), qname, top_axis))
        if scored:
            scored.sort(key=lambda item: (-item[0], item[1]))
            _n, concept, axis = scored[0]
            break
    if concept is None or axis is None:
        return EquityRollforwardGraph()

    balances: dict[str, dict[str, tuple[tuple[int, int], XbrlFact]]] = {}
    totals: dict[str, XbrlFact] = {}
    for f in facts:
        if f.concept_qname != concept or f.period_type != "instant":
            continue
        if not isinstance(f.value, (int, float)) or f.unit in _NON_MONETARY:
            continue
        if not f.instant_date:
            continue
        if not f.dimensions:
            current = totals.get(f.instant_date)
            if current is None or period_rank(f) > period_rank(current):
                totals[f.instant_date] = f
        elif set(f.dimensions) == {axis}:
            slot = balances.setdefault(f.dimensions[axis], {})
            current_b = slot.get(f.instant_date)
            if current_b is None or period_rank(f) > current_b[0]:
                slot[f.instant_date] = (period_rank(f), f)

    spans: dict[tuple[str, str], list[XbrlFact]] = {}
    for f in facts:
        if f.period_type != "duration" or not f.start_date or not f.end_date:
            continue
        if set(f.dimensions) != {axis}:
            continue
        if not isinstance(f.value, (int, float)) or f.unit in _NON_MONETARY:
            continue
        spans.setdefault((f.start_date, f.end_date), []).append(f)

    subsumption = MemberSubsumption(definition_arcs) if definition_arcs else None
    graphs: list[EquityRollforwardGraph] = []
    for (start, end), span_facts in spans.items():
        if target_year and end[:4] != target_year:
            continue
        try:
            opening_date = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        except ValueError:
            continue
        oci_total_members = {
            f.dimensions[axis]
            for f in span_facts
            if _is_oci_total(source.atom(f.concept_qname))
        }
        per_member: dict[
            str, dict[str, dict[str, tuple[tuple[int, int], XbrlFact, float]]]
        ] = {}
        net_changes: dict[str, dict[str, tuple[tuple[int, int], float]]] = {}
        for f in span_facts:
            member = f.dimensions[axis]
            member_atom = source.atom(member)
            role = _equity_role(
                source.atom(f.concept_qname),
                member_is_treasury="M_TREASURY_REPURCHASE" in member_atom.modifiers,
                has_oci_total=member in oci_total_members,
            )
            if role is None:
                continue
            signed = movement_sign("equity", role) * float(f.value)  # type: ignore[arg-type]
            if role == "net_change":
                slot_c = net_changes.setdefault(member, {})
                current_c = slot_c.get(f.concept_qname)
                if current_c is None or period_rank(f) > current_c[0]:
                    slot_c[f.concept_qname] = (period_rank(f), signed)
                continue
            per_concept = per_member.setdefault(member, {}).setdefault(role, {})
            current_m = per_concept.get(f.concept_qname)
            if current_m is None or period_rank(f) > current_m[0]:
                per_concept[f.concept_qname] = (period_rank(f), f, signed)
        components: list[EquityComponentRollforward] = []
        nodes: list[StatementNode] = []
        for member in sorted(set(balances) | set(per_member) | set(net_changes)):
            bal = balances.get(member, {})
            opening_entry = bal.get(opening_date)
            closing_entry = bal.get(end)
            if opening_entry is None and closing_entry is None:
                continue
            sums: dict[str, float] = {}
            for role, per_concept in per_member.get(member, {}).items():
                for _rank, fact, signed in per_concept.values():
                    accumulate_movement(sums, role, signed)
                    nodes.append(
                        StatementNode(
                            concept_qname=fact.concept_qname,
                            atom=source.atom(fact.concept_qname),
                            label=lbl_map.get(
                                fact.concept_qname,
                                qname_local(fact.concept_qname),
                            ),
                            facts=(fact,),
                            value=float(fact.value),  # type: ignore[arg-type]
                        )
                    )
            filed_change = net_changes.get(member)
            components.append(
                EquityComponentRollforward(
                    member_qname=member,
                    opening=float(opening_entry[1].value)  # type: ignore[arg-type]
                    if opening_entry
                    else None,
                    closing=float(closing_entry[1].value)  # type: ignore[arg-type]
                    if closing_entry
                    else None,
                    movements=sums,
                    filed_net_change=sum(
                        value for _rank, value in filed_change.values()
                    )
                    if filed_change
                    else None,
                )
            )
        total_opening = totals.get(opening_date)
        total_closing = totals.get(end)
        antichain = _equity_antichain(
            components,
            float(total_closing.value) if total_closing is not None else None,  # type: ignore[arg-type]
            subsumption=subsumption,
            axis=axis,
        )
        missing: list[str] = []
        for comp in components:
            if comp.member_qname not in antichain:
                continue
            local = qname_local(comp.member_qname)
            if comp.opening is None:
                missing.append(f"{local}:opening_balance")
            if comp.closing is None:
                missing.append(f"{local}:closing_balance")
        graphs.append(
            EquityRollforwardGraph(
                axis_qname=axis,
                balance_concept=concept,
                opening=float(total_opening.value)  # type: ignore[arg-type]
                if total_opening is not None
                else None,
                closing=float(total_closing.value)  # type: ignore[arg-type]
                if total_closing is not None
                else None,
                components=tuple(components),
                antichain_members=antichain,
                start_date=start,
                end_date=end,
                missing_components=tuple(missing),
                movements=tuple(nodes),
            )
        )
    if not graphs:
        return EquityRollforwardGraph(axis_qname=axis, balance_concept=concept)

    def span_days(graph: EquityRollforwardGraph) -> int:
        if graph.start_date and graph.end_date:
            try:
                return (
                    date.fromisoformat(graph.end_date)
                    - date.fromisoformat(graph.start_date)
                ).days
            except ValueError:
                return 0
        return 0

    if member_qname is not None:
        filtered = [
            graph
            for graph in graphs
            if (comp := graph.component(member_qname)) is not None
            and comp.closing is not None
        ]
        if filtered:
            return max(
                filtered,
                key=lambda g: (
                    g.end_date or "",
                    (c := g.component(member_qname)) is not None and c.verified is True,
                    span_days(g),
                ),
            )
    return max(
        graphs,
        key=lambda g: (
            g.end_date or "",
            span_days(g),
            g.verified is True,
            abs(g.closing or 0.0),
        ),
    )
