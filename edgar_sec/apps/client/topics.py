"""Topic views as coordinate-subspace presets over display facts.

Debt and derivatives are per-fact coordinate scans: membership from
the Step 3 display records (the tokenizer covers dimension axes and
members), maxima and accumulations stated as preset rules below.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.statement import (
    DebtStructureGraph,
    DerivativePortfolioGraph,
    StatementNode,
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
        parts = [p for p in (current_debt, lt_debt) if p is not None]
        if parts:
            total_debt = sum(parts)
        elif cp is not None:
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
