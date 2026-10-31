"""Topic views as coordinate-subspace presets over display facts.

Debt and derivatives are per-fact coordinate scans: membership from
the Step 3 display records (the tokenizer covers dimension axes and
members), maxima and accumulations stated as preset rules below.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.engine.xbrl.evidence.subsumption import MemberSubsumption
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import CalculationArc, DefinitionArc, XbrlFact
from edgar_sec.engine.xbrl.solve.identities import evaluate_composition
from edgar_sec.engine.xbrl.solve.rollforward_graphs import (
    CashRollforwardGraph,
    SegmentBreakdownGraph,
    SegmentMember,
)
from edgar_sec.engine.xbrl.solve.statement import (
    DebtStructureGraph,
    DerivativePortfolioGraph,
    StatementNode,
    period_rank,
)
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy

_DEBT_MODS = {"M_DEBT", "M_DEBT_BORROWING", "M_COMMERCIAL_PAPER"}
_LEASE_MODS = {"M_LEASE", "M_ROU_LEASE"}
_MATURITY_MODS = {"M_MATURITY", "M_MATURITY_HORIZON"}
_RISK_MODS = {
    "M_RISK_IR": "interest_rate",
    "M_RISK_FX": "foreign_exchange",
    "M_RISK_CREDIT": "credit",
    "M_RISK_COMMODITY": "commodity",
    "M_RISK_EQUITY": "equity",
}


class _AtomSource:
    """Record atoms first; the tokenizer service for axes and members."""

    def __init__(
        self,
        records: Mapping[str, DisplayRecord],
        taxonomy: DomainTaxonomy,
    ) -> None:
        self._records = records
        self._tokenizer = (
            ConceptTokenizer(taxonomy) if taxonomy.token_lexicon is not None else None
        )
        self._cache: dict[str, Atom] = {}

    def atom(self, qname: str) -> Atom:
        """Atom for any concept string, H_UNKNOWN when no lexicon."""
        record = self._records.get(qname)
        if record is not None:
            return record.atom
        if qname not in self._cache:
            if self._tokenizer is None:
                self._cache[qname] = Atom("H_UNKNOWN")
            else:
                self._cache[qname] = self._tokenizer.tokenize(qname).atom
        return self._cache[qname]


def _max(current: float | None, val: float) -> float:
    return val if current is None else max(current, val)


def accumulate_movement(
    sums: dict[str, float], role: str, value: float, sign: float = 1.0
) -> None:
    """Add one signed movement value into a per-role sum."""
    sums[role] = sums.get(role, 0.0) + sign * value


def build_debt_structure(
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    labels: Mapping[str, str] | None = None,
    year: int | str | None = None,
) -> DebtStructureGraph:
    """Resolve capital debt structure, tranches, and maturity schedules."""
    source = _AtomSource(records, taxonomy)
    lbl_map = dict(labels or {})
    target_year = str(year) if year is not None else None
    positions: list[StatementNode] = []
    maturities: list[StatementNode] = []
    maturities_by_year: dict[str, float] = {}
    total_debt = current_debt = lt_debt = cp = leases = None

    for f in facts:
        if not isinstance(f.value, (int, float)):
            continue
        yr = (f.instant_date or f.end_date or "")[:4]
        if target_year and yr != target_year:
            continue
        atom = source.atom(f.concept_qname)
        val = float(f.value)

        if atom.head == "H_LIABILITY":
            if atom.modifiers & _DEBT_MODS:
                if not f.dimensions:
                    if "M_COMMERCIAL_PAPER" in atom.modifiers:
                        cp = _max(cp, val)
                    if "M_CURRENT" in atom.modifiers:
                        current_debt = _max(current_debt, val)
                    elif "M_NONCURRENT" in atom.modifiers:
                        lt_debt = _max(lt_debt, val)
                    elif "M_COMMERCIAL_PAPER" not in atom.modifiers:
                        total_debt = _max(total_debt, val)
                positions.append(
                    StatementNode(
                        concept_qname=f.concept_qname,
                        atom=atom,
                        label=lbl_map.get(
                            f.concept_qname, f.concept_qname.split(":")[-1]
                        ),
                        facts=(f,),
                        value=val,
                    )
                )
            elif (atom.modifiers & _LEASE_MODS) and not f.dimensions:
                leases = _max(leases, val)

        dim_mods: set[str] = set()
        for ax in f.dimensions:
            dim_mods.update(source.atom(ax).modifiers)
        if (atom.modifiers | dim_mods) & _MATURITY_MODS:
            maturities.append(
                StatementNode(
                    concept_qname=f.concept_qname,
                    atom=atom,
                    label=lbl_map.get(f.concept_qname, f.concept_qname.split(":")[-1]),
                    facts=(f,),
                    value=val,
                )
            )
            for mem in f.dimensions.values():
                mem_yr = mem[-4:]
                if mem_yr.isdigit():
                    maturities_by_year[mem_yr] = val

    if total_debt is None:
        total_debt = evaluate_composition(
            "debt_total", {"current": current_debt, "noncurrent": lt_debt}
        )
        if total_debt is None:
            total_debt = cp

    return DebtStructureGraph(
        total_debt=total_debt,
        current_debt=current_debt,
        long_term_debt=lt_debt,
        commercial_paper=cp,
        leases=leases,
        positions=tuple(positions),
        maturities=tuple(maturities),
        maturities_by_year=maturities_by_year,
    )


def _classify_risk(
    source: _AtomSource,
    taxonomy: DomainTaxonomy,
    concept_qname: str,
    dimensions: Mapping[str, str],
) -> str:
    for mem in dimensions.values():
        risk = taxonomy.resolve_instrument_risk(mem)
        if risk:
            return risk
    mods = set(source.atom(concept_qname).modifiers)
    for ax, mem in dimensions.items():
        mods.update(source.atom(ax).modifiers)
        mods.update(source.atom(mem).modifiers)
    for mod, risk_type in _RISK_MODS.items():
        if mod in mods:
            return risk_type
    return taxonomy.resolve_instrument_risk(concept_qname) or "other"


def build_derivative_portfolio(
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    labels: Mapping[str, str] | None = None,
    year: int | str | None = None,
) -> DerivativePortfolioGraph:
    """Resolve dynamic derivative exposures, risk buckets, and netting."""
    source = _AtomSource(records, taxonomy)
    lbl_map = dict(labels or {})
    target_year = str(year) if year is not None else None
    positions: list[StatementNode] = []
    by_risk: dict[str, list[StatementNode]] = {}
    risk_totals: dict[str, dict[str, float]] = {}
    gross_assets = net_assets = gross_liab = net_liab = None
    notional = collateral = netting = None

    for f in facts:
        if not isinstance(f.value, (int, float)):
            continue
        yr = (f.instant_date or f.end_date or "")[:4]
        if target_year and yr != target_year:
            continue
        atom = source.atom(f.concept_qname)
        is_deriv = "M_DERIVATIVE" in atom.modifiers or any(
            "Derivative" in ax for ax in f.dimensions
        )
        val = float(f.value)

        if not f.dimensions:
            if atom.head == "H_ASSET" and "M_DERIVATIVE" in atom.modifiers:
                if "V_NET" in atom.modifiers:
                    net_assets = _max(net_assets, val)
                else:
                    gross_assets = _max(gross_assets, val)
            elif atom.head == "H_LIABILITY" and "M_DERIVATIVE" in atom.modifiers:
                if "V_NET" in atom.modifiers:
                    net_liab = _max(net_liab, val)
                else:
                    gross_liab = _max(gross_liab, val)
            elif atom.head == "H_NOTIONAL":
                notional = _max(notional, val)
            elif "M_CASH_COLLATERAL_OFFSET" in atom.modifiers:
                collateral = _max(collateral, val)
            elif "M_NOT_SUBJECT_TO_NETTING" in atom.modifiers:
                netting = _max(netting, val)

        if is_deriv:
            risk_cat = _classify_risk(source, taxonomy, f.concept_qname, f.dimensions)
            node = StatementNode(
                concept_qname=f.concept_qname,
                atom=atom,
                label=lbl_map.get(f.concept_qname, f.concept_qname.split(":")[-1]),
                facts=(f,),
                value=val,
            )
            positions.append(node)
            by_risk.setdefault(risk_cat, []).append(node)
            totals = risk_totals.setdefault(
                risk_cat,
                {"gross_assets": 0.0, "gross_liabilities": 0.0, "notional": 0.0},
            )
            if atom.head == "H_ASSET":
                totals["gross_assets"] += val
            elif atom.head == "H_LIABILITY":
                totals["gross_liabilities"] += val
            elif atom.head == "H_NOTIONAL":
                totals["notional"] += val

    return DerivativePortfolioGraph(
        gross_assets=gross_assets,
        net_assets=net_assets,
        gross_liabilities=gross_liab,
        net_liabilities=net_liab,
        notional_amount=notional,
        collateral_offsets=collateral,
        master_netting_offsets=netting,
        positions=tuple(positions),
        by_risk={k: tuple(v) for k, v in by_risk.items()},
        risk_totals=risk_totals,
    )


_NON_MONETARY = ("pure", "shares", "item", "ratio")
_RESTRICTED_COMPONENT_MODS = {"M_RESTRICTED", "M_CURRENT", "M_NONCURRENT"}


def _cash_node(
    source: _AtomSource, labels: Mapping[str, str], fact: XbrlFact
) -> StatementNode:
    return StatementNode(
        concept_qname=fact.concept_qname,
        atom=source.atom(fact.concept_qname),
        label=labels.get(fact.concept_qname, fact.concept_qname.split(":")[-1]),
        facts=(fact,),
        value=float(fact.value),  # type: ignore[arg-type]
    )


def build_cash_rollforward(
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    labels: Mapping[str, str] | None = None,
    year: int | str | None = None,
    *,
    calculation_arcs: Sequence[CalculationArc] = (),
) -> CashRollforwardGraph:
    """Resolve the ASU 2016-18 rollforward, selected by its own identity."""
    source = _AtomSource(records, taxonomy)
    lbl_map = dict(labels or {})
    target_year = str(year) if year is not None else None
    totals: dict[str, dict[str, XbrlFact]] = {}
    instant_at: dict[tuple[str, str], XbrlFact] = {}
    changes: dict[str, list[XbrlFact]] = {}
    fx_effects: dict[tuple[str, str], XbrlFact] = {}

    for f in facts:
        if f.dimensions or not isinstance(f.value, (int, float)):
            continue
        if f.unit in _NON_MONETARY:
            continue
        atom = source.atom(f.concept_qname)
        if f.period_type == "instant" and f.instant_date:
            instant_at[(f.concept_qname, f.instant_date)] = f
        if atom.head != "H_CASH":
            continue
        if f.period_type == "instant" and f.instant_date:
            mods = set(atom.modifiers)
            if mods == {"M_RESTRICTED"} or mods == {"M_CARRYING_AMOUNT"}:
                totals.setdefault(f.concept_qname, {})[f.instant_date] = f
        elif f.period_type == "duration" and f.end_date:
            if {"M_CHANGE", "M_RESTRICTED"} <= set(atom.modifiers):
                changes.setdefault(f.end_date, []).append(f)
            elif set(atom.modifiers) == {"M_FX_CURRENCY", "M_RESTRICTED"}:
                if f.start_date:
                    fx_effects[(f.start_date, f.end_date)] = f

    def tier(qname: str) -> tuple[int, str]:
        mods = set(source.atom(qname).modifiers)
        if mods == {"M_CARRYING_AMOUNT"}:
            return (2, qname)
        return (0, qname)

    def change_for(end_date: str) -> tuple[float | None, XbrlFact | None]:
        cands = changes.get(end_date, [])
        if not cands:
            return None, None

        def span(fact: XbrlFact) -> int:
            if fact.start_date and fact.end_date:
                try:
                    return (
                        date.fromisoformat(fact.end_date)
                        - date.fromisoformat(fact.start_date)
                    ).days
                except ValueError:
                    return 0
            return 0

        chosen = max(
            cands,
            key=lambda f: (
                "M_INCLUDING" in set(source.atom(f.concept_qname).modifiers),
                span(f),
            ),
        )
        value = float(chosen.value)  # type: ignore[arg-type]
        mods = set(source.atom(chosen.concept_qname).modifiers)
        if "M_EXCLUDING" in mods and chosen.start_date:
            fx = fx_effects.get((chosen.start_date, end_date))
            if fx is not None:
                composed = evaluate_composition(
                    "cash_change_including_fx",
                    {
                        "change_excluding_fx": value,
                        "fx_effect": float(fx.value),  # type: ignore[arg-type]
                    },
                )
                if composed is not None:
                    value = composed
        return value, chosen

    selected: tuple[str, str, float | None, float | None, float] | None = None
    fallback: tuple[str, str, float | None, float | None, float] | None = None
    for qname in sorted(totals, key=tier):
        series = totals[qname]
        ends = [d for d in series if target_year is None or d[:4] == target_year]
        if not ends:
            continue
        end_date = max(ends)
        end_val = float(series[end_date].value)  # type: ignore[arg-type]
        change_val, change_fact = change_for(end_date)
        beg_date: str | None = None
        if change_fact is not None and change_fact.start_date:
            try:
                prior = date.fromisoformat(change_fact.start_date) - timedelta(days=1)
                if prior.isoformat() in series:
                    beg_date = prior.isoformat()
            except ValueError:
                beg_date = None
        if beg_date is None:
            earlier = [d for d in series if d < end_date]
            beg_date = max(earlier) if earlier else None
        beg_val = float(series[beg_date].value) if beg_date else None  # type: ignore[arg-type]
        attempt = (qname, end_date, beg_val, change_val, end_val)
        if fallback is None:
            fallback = attempt
        probe = CashRollforwardGraph(
            beginning=beg_val, net_change=change_val, end=end_val
        )
        if probe.rollforward_verified:
            selected = attempt
            break
    chosen_attempt = selected or fallback
    if chosen_attempt is None:
        return CashRollforwardGraph()
    total_qname, end_date, beg_val, change_val, end_val = chosen_attempt
    beg_date_final: str | None = None
    series = totals[total_qname]
    _, change_fact = change_for(end_date)
    if change_fact is not None and change_fact.start_date:
        try:
            prior = date.fromisoformat(change_fact.start_date) - timedelta(days=1)
            if prior.isoformat() in series:
                beg_date_final = prior.isoformat()
        except ValueError:
            beg_date_final = None
    if beg_date_final is None and beg_val is not None:
        earlier = [d for d in series if d < end_date]
        beg_date_final = max(earlier) if earlier else None

    calc_nodes: list[StatementNode] = []
    calc_total: float | None = None
    for arc in calculation_arcs:
        if arc.parent_qname != total_qname:
            continue
        fact = instant_at.get((arc.child_qname, end_date))
        if fact is not None:
            calc_nodes.append(_cash_node(source, lbl_map, fact))
            calc_total = (calc_total or 0.0) + arc.weight * float(fact.value)  # type: ignore[arg-type]
    comp_nodes: list[StatementNode] = []
    comp_total: float | None = None
    for (qname, instant), fact in sorted(instant_at.items()):
        if instant != end_date or qname == total_qname:
            continue
        atom = source.atom(qname)
        mods = set(atom.modifiers)
        is_carrying = mods == {"M_CARRYING_AMOUNT"}
        is_restricted_part = (
            mods <= _RESTRICTED_COMPONENT_MODS and "M_RESTRICTED" in mods
        )
        if is_carrying or is_restricted_part:
            comp_nodes.append(_cash_node(source, lbl_map, fact))
            comp_total = (comp_total or 0.0) + float(fact.value)  # type: ignore[arg-type]

    if calc_total is not None and abs(end_val - calc_total) <= 1.0:
        bs_total, components = calc_total, tuple(calc_nodes)
    elif comp_total is not None and abs(end_val - comp_total) <= 1.0:
        bs_total, components = comp_total, tuple(comp_nodes)
    elif calc_nodes:
        bs_total, components = calc_total, tuple(calc_nodes)
    elif comp_nodes:
        bs_total, components = comp_total, tuple(comp_nodes)
    else:
        bs_total, components = None, ()

    return CashRollforwardGraph(
        beginning=beg_val,
        net_change=change_val,
        end=end_val,
        beginning_date=beg_date_final,
        end_date=end_date,
        balance_sheet_total=bs_total,
        components=components,
        total_concept=total_qname,
    )


_PeriodKey = tuple[str | None, str | None, str | None, str | None]
_ClassKey = tuple[tuple[str, str], ...]


def _period_key(fact: XbrlFact) -> _PeriodKey:
    return (fact.period_type, fact.start_date, fact.end_date, fact.instant_date)


def build_segment_breakdown(
    facts: Sequence[XbrlFact],
    records: Mapping[str, DisplayRecord],
    taxonomy: DomainTaxonomy,
    labels: Mapping[str, str] | None = None,
    year: int | str | None = None,
    *,
    concept_qname: str | None = None,
    axis_qname: str | None = None,
    definition_arcs: Sequence[DefinitionArc] = (),
) -> SegmentBreakdownGraph:
    """Resolve one axis's members against the concept's reported total.

    Single-axis members form the antichain; with definition arcs a member
    subsumed by another is excluded declaratively, otherwise all stay.
    """
    del records, taxonomy, labels
    subsumption = MemberSubsumption(definition_arcs) if definition_arcs else None
    target_year = str(year) if year is not None else None
    totals: dict[tuple[str, str | None, _PeriodKey], XbrlFact] = {}
    groups: dict[tuple[str, str, str | None, _PeriodKey], dict[str, XbrlFact]] = {}
    for f in facts:
        if not isinstance(f.value, (int, float)):
            continue
        period = _period_key(f)
        if not f.dimensions:
            key = (f.concept_qname, f.unit, period)
            current = totals.get(key)
            if current is None or period_rank(f) > period_rank(current):
                totals[key] = f
        elif len(f.dimensions) == 1:
            axis, member = next(iter(f.dimensions.items()))
            members = groups.setdefault((f.concept_qname, axis, f.unit, period), {})
            current = members.get(member)
            if current is None or period_rank(f) > period_rank(current):
                members[member] = f

    candidates: list[SegmentBreakdownGraph] = []
    for (concept, axis, unit, period), members in groups.items():
        if len(members) < 2:
            continue
        if concept_qname is not None and concept != concept_qname:
            continue
        if axis_qname is not None and axis != axis_qname:
            continue
        total_fact = totals.get((concept, unit, period))
        if total_fact is None:
            continue
        _period_type, start, end, instant = period
        if target_year and (end or instant or "")[:4] != target_year:
            continue
        ordered = sorted(
            members.items(),
            key=lambda item: (-abs(float(item[1].value)), item[0]),  # type: ignore[arg-type]
        )
        if subsumption is not None:
            frontier = subsumption.frontier(axis, [member for member, _f in ordered])
            if frontier is not None:
                keep = set(frontier)
                ordered = [item for item in ordered if item[0] in keep]
        candidates.append(
            SegmentBreakdownGraph(
                concept_qname=concept,
                axis_qname=axis,
                total=float(total_fact.value),  # type: ignore[arg-type]
                members=tuple(
                    SegmentMember(
                        member_qname=member,
                        label=member.split(":")[-1],
                        value=float(fact.value),  # type: ignore[arg-type]
                    )
                    for member, fact in ordered
                ),
                start_date=start,
                end_date=end,
                instant_date=instant,
                unit=unit,
            )
        )
    if not candidates:
        return SegmentBreakdownGraph(concept_qname=concept_qname, axis_qname=axis_qname)

    def period_end(graph: SegmentBreakdownGraph) -> str:
        return graph.end_date or graph.instant_date or ""

    if concept_qname is not None or axis_qname is not None:
        return max(
            candidates,
            key=lambda g: (
                period_end(g),
                g.verified is True,
                abs(g.total or 0.0),
                g.concept_qname or "",
                g.axis_qname or "",
                g.unit or "",
            ),
        )
    latest: dict[tuple[str | None, str | None, str | None], SegmentBreakdownGraph] = {}
    for graph in candidates:
        key = (graph.concept_qname, graph.axis_qname, graph.unit)
        current = latest.get(key)
        if current is None or period_end(graph) > period_end(current):
            latest[key] = graph
    return max(
        latest.values(),
        key=lambda g: (
            g.verified is True,
            abs(g.total or 0.0),
            len(g.members),
            g.concept_qname or "",
            g.axis_qname or "",
            g.unit or "",
        ),
    )
