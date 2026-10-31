"""Reconciliation rollforward builders: Level-3 fair value and pensions.

Both builders resolve one class's rollforward from atom coordinates;
the identity, not the filing, decides whether the class verifies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.apps.client.topics import _NON_MONETARY, _AtomSource, accumulate_movement
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.identities import negative_roles
from edgar_sec.engine.xbrl.solve.rollforward_graphs import (
    Level3RollforwardGraph,
    PensionFundedStatusGraph,
    PensionRollforwardSide,
)
from edgar_sec.engine.xbrl.solve.statement import StatementNode, period_rank
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy

_ClassKey = tuple[tuple[str, str], ...]


def _level3_role(atom: Atom, period_type: str) -> str | None:
    """Rollforward role from atom coordinates alone."""
    mods = atom.modifiers
    if period_type == "instant":
        if {"M_FAIR_VALUE", "M_RECONCILIATION"} <= mods:
            return "balance"
        if {"M_FAIR_VALUE", "M_DERIVATIVE", "V_NET"} <= mods:
            return "balance_net"
        return None
    if "M_FAIR_VALUE" not in mods or "M_RECONCILIATION" not in mods:
        return None
    if "M_CHANGE" in mods:
        return "net_change"
    if "M_TRANSFER_IN" in mods:
        return "transfers_in"
    if "M_TRANSFER_OUT" in mods:
        return "transfers_out"
    if "M_TRANSFER" in mods and "V_NET" in mods:
        return "transfers_net"
    if atom.head == "H_INCOME":
        return "gains_oci" if "M_OCI" in mods else "gains_earnings"
    if "M_SALES_GOODS" in mods:
        return "sales"
    if "M_PURCHASE" in mods:
        return "purchases"
    if "M_ISSUANCE" in mods:
        return "issues"
    if "M_SETTLEMENT" in mods:
        return "settlements"
    return None


def build_level3_rollforward(
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    labels: Mapping[str, str] | None = None,
    year: int | str | None = None,
    *,
    axis_qname: str | None = None,
    member_qname: str | None = None,
) -> Level3RollforwardGraph:
    """Resolve one class's Level-3 rollforward, selected by its identity.

    A class is a dimension tuple minus the filing's constant qualifier
    axes; a filed net change verifies a class whose components do not.
    """
    source = _AtomSource(records, taxonomy)
    lbl_map = dict(labels or {})
    target_year = str(year) if year is not None else None
    candidates: list[tuple[XbrlFact, str]] = []
    members_by_axis: dict[str, set[str]] = {}
    for f in facts:
        if not isinstance(f.value, (int, float)) or f.unit in _NON_MONETARY:
            continue
        atom = source.atom(f.concept_qname)
        role = _level3_role(atom, f.period_type)
        if role is None:
            continue
        candidates.append((f, role))
        for axis, member in f.dimensions.items():
            members_by_axis.setdefault(axis, set()).add(member)
    qualifiers = {
        axis for axis, members in members_by_axis.items() if len(members) == 1
    }

    def class_key(fact: XbrlFact) -> _ClassKey:
        return tuple(
            sorted(
                (ax, mem) for ax, mem in fact.dimensions.items() if ax not in qualifiers
            )
        )

    balances: dict[tuple[_ClassKey, str], tuple[int, tuple[int, int], XbrlFact]] = {}
    movements: dict[
        tuple[_ClassKey, str, str],
        dict[str, dict[str, tuple[tuple[int, int], XbrlFact]]],
    ] = {}
    for f, role in candidates:
        key = class_key(f)
        if role in ("balance", "balance_net") and f.instant_date:
            slot = (key, f.instant_date)
            entry = (2 if role == "balance" else 1, period_rank(f), f)
            if slot not in balances or entry[:2] > balances[slot][:2]:
                balances[slot] = entry
        elif f.period_type == "duration" and f.start_date and f.end_date:
            roles = movements.setdefault((key, f.start_date, f.end_date), {})
            per_concept = roles.setdefault(role, {})
            current = per_concept.get(f.concept_qname)
            if current is None or period_rank(f) > current[0]:
                per_concept[f.concept_qname] = (period_rank(f), f)

    graphs: list[tuple[_ClassKey, Level3RollforwardGraph]] = []
    for (key, start, end), roles in movements.items():
        if target_year and end[:4] != target_year:
            continue
        try:
            opening_date = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        except ValueError:
            opening_date = None
        opening_entry = balances.get((key, opening_date)) if opening_date else None
        closing_entry = balances.get((key, end))
        opening = float(opening_entry[2].value) if opening_entry else None  # type: ignore[arg-type]
        closing = float(closing_entry[2].value) if closing_entry else None  # type: ignore[arg-type]
        balance_entry = closing_entry or opening_entry
        balance_fact = balance_entry[2] if balance_entry else None
        sums: dict[str, float] = {}
        nodes: list[StatementNode] = []
        is_derivative = False
        balance_atom = source.atom(balance_fact.concept_qname) if balance_fact else None
        is_liability = balance_atom is not None and balance_atom.head == "H_LIABILITY"
        for role, per_concept in roles.items():
            for _rank, fact in per_concept.values():
                atom = source.atom(fact.concept_qname)
                accumulate_movement(sums, role, float(fact.value))  # type: ignore[arg-type]
                nodes.append(
                    StatementNode(
                        concept_qname=fact.concept_qname,
                        atom=atom,
                        label=lbl_map.get(
                            fact.concept_qname, fact.concept_qname.split(":")[-1]
                        ),
                        facts=(fact,),
                        value=float(fact.value),  # type: ignore[arg-type]
                    )
                )
                if "M_DERIVATIVE" in atom.modifiers:
                    is_derivative = True
                elif (
                    role not in ("gains_earnings", "gains_oci")
                    and atom.head == "H_LIABILITY"
                ):
                    is_liability = True
        side = (
            "derivative" if is_derivative else "liability" if is_liability else "asset"
        )
        missing: list[str] = []
        if opening is None:
            missing.append("opening_balance")
        if closing is None:
            missing.append("closing_balance")
        if "gains_earnings" not in sums and "gains_oci" not in sums:
            missing.append("gains")
        for role in ("purchases", "sales", "issues", "settlements"):
            if role not in sums:
                missing.append(role)
        if not any(
            role in sums for role in ("transfers_in", "transfers_out", "transfers_net")
        ):
            missing.append("transfers")
        rep_fact = balance_fact or (nodes[0].facts[0] if nodes else None)
        representative = key
        if rep_fact is not None:
            representative = tuple(sorted(rep_fact.dimensions.items()))
        graphs.append(
            (
                key,
                Level3RollforwardGraph(
                    dimensions=representative,
                    opening=opening,
                    closing=closing,
                    gains_earnings=sums.get("gains_earnings"),
                    gains_oci=sums.get("gains_oci"),
                    purchases=sums.get("purchases"),
                    sales=sums.get("sales"),
                    issues=sums.get("issues"),
                    settlements=sums.get("settlements"),
                    transfers_in=sums.get("transfers_in"),
                    transfers_out=sums.get("transfers_out"),
                    transfers_net=sums.get("transfers_net"),
                    net_change=sums.get("net_change"),
                    start_date=start,
                    end_date=end,
                    balance_concept=balance_fact.concept_qname
                    if balance_fact
                    else None,
                    side=side,
                    missing_components=tuple(missing),
                    movements=tuple(nodes),
                ),
            )
        )
    if not graphs:
        dims = ((axis_qname, member_qname),) if axis_qname and member_qname else ()
        return Level3RollforwardGraph(dimensions=dims)  # type: ignore[arg-type]

    def matches(graph: Level3RollforwardGraph) -> bool:
        if axis_qname is not None and axis_qname not in dict(graph.dimensions):
            return False
        return member_qname is None or member_qname in dict(graph.dimensions).values()

    def quality(graph: Level3RollforwardGraph) -> tuple[bool, float, int]:
        return (
            graph.verified is True or graph.change_verified is True,
            abs(graph.closing or 0.0),
            len(graph.movements),
        )

    if axis_qname is not None or member_qname is not None:
        filtered = [graph for _key, graph in graphs if matches(graph)]
        if not filtered:
            dims = ((axis_qname, member_qname),) if axis_qname and member_qname else ()
            return Level3RollforwardGraph(dimensions=dims)  # type: ignore[arg-type]
        return max(filtered, key=lambda g: (g.end_date or "", *quality(g)))
    latest: dict[_ClassKey, Level3RollforwardGraph] = {}
    for key, graph in graphs:
        current = latest.get(key)
        if current is None or (graph.end_date or "") > (current.end_date or ""):
            latest[key] = graph
    return max(latest.values(), key=quality)


_ASSETS_CORE = ("actual_return", "employer_contributions", "benefits_paid")
_OBLIGATION_CORE = ("service_cost", "interest_cost", "benefits_paid", "actuarial")


def _pension_role(atom: Atom, period_type: str) -> tuple[str, str] | None:
    """(side, role) for a defined-benefit fact, from atom coordinates."""
    mods = atom.modifiers
    if "M_PENSION_DEFINED_BENEFIT" not in mods:
        return None
    if period_type == "instant":
        if "M_FUNDED_STATUS" in mods:
            return ("funded", "funded_status")
        if mods == {"M_PENSION_DEFINED_BENEFIT", "M_PLAN_ASSETS", "M_FAIR_VALUE"}:
            return ("assets", "balance")
        if atom.head == "H_LIABILITY" and mods == {
            "M_PENSION_DEFINED_BENEFIT",
            "M_BENEFIT_OBLIGATION",
        }:
            return ("obligation", "balance")
        return None
    if "M_EMPLOYER_CONTRIBUTION" in mods:
        return ("assets", "employer_contributions")
    if "M_PLAN_ASSETS" in mods:
        if "M_ACTUAL_RETURN" in mods:
            return ("assets", "actual_return")
        if "M_PARTICIPANT_CONTRIBUTION" in mods:
            return ("assets", "participant_contributions")
        if "M_BENEFITS_PAID" in mods:
            return ("assets", "benefits_paid")
        if "M_SETTLEMENT" in mods and not mods & {"M_PURCHASE", "M_CURTAILMENT"}:
            return ("assets", "settlements")
        if "M_FX_CTA" in mods:
            return ("assets", "fx_translation")
        if "M_OTHER_CHANGE" in mods:
            return ("assets", "other_change")
        return None
    if "M_BENEFIT_OBLIGATION" in mods:
        if "M_BENEFITS_PAID" in mods:
            return ("obligation", "benefits_paid")
        if "M_PARTICIPANT_CONTRIBUTION" in mods:
            return ("obligation", "participant_contributions")
        if "M_SETTLEMENT" in mods and not mods & {"M_PURCHASE", "M_CURTAILMENT"}:
            return ("obligation", "settlements")
        if "M_FX_CURRENCY" in mods:
            return ("obligation", "fx_changes")
        if "M_ACTUARIAL" in mods:
            return ("obligation", "actuarial")
        return None
    if atom.head == "H_COST":
        if mods == {"M_PENSION_DEFINED_BENEFIT", "M_SERVICE"}:
            return ("obligation", "service_cost")
        if mods == {"M_PENSION_DEFINED_BENEFIT", "M_INTEREST"}:
            return ("obligation", "interest_cost")
    if "M_ACTUARIAL" in mods and "V_NET" not in mods:
        return ("obligation", "actuarial")
    if "M_CURTAILMENT" in mods and "M_SETTLEMENT" not in mods and "V_NET" not in mods:
        return ("obligation", "curtailments")
    if "M_PLAN_AMENDMENT" in mods:
        return ("obligation", "plan_amendments")
    if "M_TERMINATION_BENEFIT" in mods:
        return ("obligation", "special_termination")
    return None


def build_pension_funded_status(
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    labels: Mapping[str, str] | None = None,
    year: int | str | None = None,
    *,
    axis_qname: str | None = None,
    member_qname: str | None = None,
) -> PensionFundedStatusGraph:
    """Resolve one plan class's funded status and both rollforwards.

    A class is a dimension tuple minus the filing's constant qualifier
    axes; each side verifies by its own rollforward identity.
    """
    source = _AtomSource(records, taxonomy)
    lbl_map = dict(labels or {})
    target_year = str(year) if year is not None else None
    candidates: list[tuple[XbrlFact, str, str]] = []
    members_by_axis: dict[str, set[str]] = {}
    for f in facts:
        if not isinstance(f.value, (int, float)) or f.unit in _NON_MONETARY:
            continue
        atom = source.atom(f.concept_qname)
        found = _pension_role(atom, f.period_type)
        if found is None:
            continue
        candidates.append((f, found[0], found[1]))
        for axis, member in f.dimensions.items():
            members_by_axis.setdefault(axis, set()).add(member)
    qualifiers = {
        axis for axis, members in members_by_axis.items() if len(members) == 1
    }

    def class_key(fact: XbrlFact) -> _ClassKey:
        return tuple(
            sorted(
                (ax, mem) for ax, mem in fact.dimensions.items() if ax not in qualifiers
            )
        )

    balances: dict[tuple[_ClassKey, str, str], tuple[tuple[int, int], XbrlFact]] = {}
    funded_facts: dict[tuple[_ClassKey, str], XbrlFact] = {}
    movements: dict[
        tuple[_ClassKey, str, str],
        dict[tuple[str, str], dict[str, tuple[tuple[int, int], XbrlFact]]],
    ] = {}
    for f, side, role in candidates:
        key = class_key(f)
        if role == "balance" and f.instant_date:
            slot = (key, side, f.instant_date)
            current = balances.get(slot)
            if current is None or period_rank(f) > current[0]:
                balances[slot] = (period_rank(f), f)
        elif role == "funded_status" and f.instant_date:
            slot_f = (key, f.instant_date)
            current_f = funded_facts.get(slot_f)
            if current_f is None or period_rank(f) > period_rank(current_f):
                funded_facts[slot_f] = f
        elif f.period_type == "duration" and f.start_date and f.end_date:
            roles = movements.setdefault((key, f.start_date, f.end_date), {})
            per_concept = roles.setdefault((side, role), {})
            current = per_concept.get(f.concept_qname)
            if current is None or period_rank(f) > current[0]:
                per_concept[f.concept_qname] = (period_rank(f), f)

    graphs: list[tuple[_ClassKey, PensionFundedStatusGraph]] = []
    for (key, start, end), roles in movements.items():
        if target_year and end[:4] != target_year:
            continue
        try:
            opening_date = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        except ValueError:
            opening_date = None
        sides: dict[str, PensionRollforwardSide] = {}
        nodes: list[StatementNode] = []
        missing: list[str] = []
        rep_fact: XbrlFact | None = None
        for side, core in (
            ("assets", _ASSETS_CORE),
            ("obligation", _OBLIGATION_CORE),
        ):
            negative = negative_roles("pension", side)
            opening_entry = (
                balances.get((key, side, opening_date)) if opening_date else None
            )
            closing_entry = balances.get((key, side, end))
            if rep_fact is None and (closing_entry or opening_entry):
                rep_fact = (closing_entry or opening_entry)[1]  # type: ignore[index]
            sums: dict[str, float] = {}
            for (s, role), per_concept in roles.items():
                if s != side:
                    continue
                for _rank, fact in per_concept.values():
                    accumulate_movement(sums, role, float(fact.value))  # type: ignore[arg-type]
                    nodes.append(
                        StatementNode(
                            concept_qname=fact.concept_qname,
                            atom=source.atom(fact.concept_qname),
                            label=lbl_map.get(
                                fact.concept_qname,
                                fact.concept_qname.split(":")[-1],
                            ),
                            facts=(fact,),
                            value=float(fact.value),  # type: ignore[arg-type]
                        )
                    )
            if opening_entry is None:
                missing.append(f"{side}_opening_balance")
            if closing_entry is None:
                missing.append(f"{side}_closing_balance")
            for role in core:
                if role not in sums:
                    missing.append(role)
            sides[side] = PensionRollforwardSide(
                opening=float(opening_entry[1].value) if opening_entry else None,  # type: ignore[arg-type]
                closing=float(closing_entry[1].value) if closing_entry else None,  # type: ignore[arg-type]
                movements=sums,
                negative_roles=negative,
            )
        if rep_fact is None and nodes:
            rep_fact = nodes[0].facts[0]
        representative = (
            tuple(sorted(rep_fact.dimensions.items())) if rep_fact is not None else key
        )
        funded_fact = funded_facts.get((key, end))
        graphs.append(
            (
                key,
                PensionFundedStatusGraph(
                    dimensions=representative,
                    plan_assets=sides["assets"],
                    obligation=sides["obligation"],
                    funded_status_filed=float(funded_fact.value)  # type: ignore[arg-type]
                    if funded_fact is not None
                    else None,
                    start_date=start,
                    end_date=end,
                    missing_components=tuple(missing),
                    movements=tuple(nodes),
                ),
            )
        )
    if not graphs:
        dims = ((axis_qname, member_qname),) if axis_qname and member_qname else ()
        return PensionFundedStatusGraph(dimensions=dims)  # type: ignore[arg-type]

    def matches(graph: PensionFundedStatusGraph) -> bool:
        if axis_qname is not None and axis_qname not in dict(graph.dimensions):
            return False
        return member_qname is None or member_qname in dict(graph.dimensions).values()

    def quality(graph: PensionFundedStatusGraph) -> tuple[bool, float, int]:
        verified = (
            graph.funded_verified is True
            or graph.plan_assets.verified is True
            or graph.obligation.verified is True
        )
        scale = graph.funded_status
        if scale is None:
            scale = graph.plan_assets.closing or 0.0
        return (verified, abs(scale), len(graph.movements))

    if axis_qname is not None or member_qname is not None:
        filtered = [graph for _key, graph in graphs if matches(graph)]
        if not filtered:
            dims = ((axis_qname, member_qname),) if axis_qname and member_qname else ()
            return PensionFundedStatusGraph(dimensions=dims)  # type: ignore[arg-type]
        return max(filtered, key=lambda g: (g.end_date or "", *quality(g)))
    latest: dict[_ClassKey, PensionFundedStatusGraph] = {}
    for key, graph in graphs:
        current = latest.get(key)
        if current is None or (graph.end_date or "") > (current.end_date or ""):
            latest[key] = graph
    return max(latest.values(), key=quality)
