"""Seeded cross-firm pair set and its live-lookup evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
    EXACT,
    GENERALIZATION,
    NEAR,
    SPECIALIZATION,
)


@dataclass(frozen=True, slots=True)
class PairSpec:
    """One seeded cross-firm pair with its rendered-text provenance."""

    target: str
    candidate: str
    tier: str
    provenance: str
    rule: str = ""
    direction: str = ""
    via_default: bool = False
    source_firm: str = ""
    candidate_firm: str = ""
    incompatibility: str = ""
    source_scope: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PairReport:
    """Gate outcome for the seeded pair set against the live lookup."""

    total: int
    passed: int
    failures: tuple[str, ...]

    @property
    def passed_all(self) -> bool:
        """True when every seeded pair holds at its expected tier."""
        return not self.failures


PAIR_SET: tuple[PairSpec, ...] = (
    PairSpec(
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:AccountsPayableCurrent",
        EXACT,
        "Phase 3 Step 4 specimen: APC target, 28 same-qname pairs EXACT",
        rule="equality",
    ),
    PairSpec(
        "us-gaap:AccountsPayable",
        "us-gaap:AccountsPayableCurrent",
        NEAR,
        "Phase 3 Step 4 specimen: bare payables, current form ranked first",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:AccountsPayable",
        "us-gaap:AccruedLiabilitiesCurrent",
        NEAR,
        "Phase 3 Step 4 specimen: bare payables, accrued form via default",
        rule="via_default",
        via_default=True,
    ),
    PairSpec(
        "us-gaap:AccountsPayable",
        "us-gaap:LiabilitiesCurrent",
        NEAR,
        "Phase 3 Step 4 specimen: bare payables, total-current generalization",
        rule="via_default",
        direction=GENERALIZATION,
        via_default=True,
    ),
    PairSpec(
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        NEAR,
        "Q3 probe Class 1: GIS headline 19,857.2M at this concept (text "
        "L3153); followup Step 2 Q-B pin carries it as the NEAR neighbour",
        rule="subsumption",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:Revenues",
        "us-gaap:RegulatedAndUnregulatedOperatingRevenue",
        NEAR,
        "Followup evidence S4 NEE: candidate is the presented operating "
        "revenues headline 24,753M (text L1889), confirming specimen",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:Revenues",
        "us-gaap:RevenueRemainingPerformanceObligation",
        NEAR,
        "Followup evidence S4 V: 4,100M performance-obligation backlog "
        "(text L1872) against net revenue 35,926M (text L789)",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:NetIncomeLoss",
        "us-gaap:NetIncomeLossAttributableToNoncontrollingInterest",
        NEAR,
        "Followup evidence S4 CAT/CF/FCX: noncontrolling-interest "
        "attribution lines (text CAT L1851, CF L1103, FCX L3765)",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:DerivativeLiabilities",
        "us-gaap:DerivativeFairValueOfDerivativeLiability",
        NEAR,
        "Followup evidence S4 APD/GIS: presented derivative-liability "
        "fair-value totals 93.6M / 72.0M (text APD L3250, GIS L4562)",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:DerivativeLiabilities",
        "us-gaap:DerivativeInstrumentsAndHedgesLiabilities",
        NEAR,
        "Followup evidence S4 CF: total derivative liabilities 3M "
        "(text L3312), confirming specimen",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:DerivativeLiabilities",
        "us-gaap:DerivativeLiabilitiesCurrent",
        NEAR,
        "Followup evidence S4 F: current slice 1,000M of a 1,900M total "
        "(text L4704); the tier is the specimen, the value is partial",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:Cash",
        NEAR,
        "WS4 step 3 (Edgartools round 1) AAPL/MSFT/GOOGL: Cash facts "
        "are the cash-only slice (AAPL CashMember 27,199M; MSFT "
        "11,571M) against balance-sheet cash and equivalents 29,943M "
        "(text AAPL L1006) / 18,315M (text MSFT L1661); GOOGL cash "
        "column 12,407M vs 23,466M (text L1643)",
        rule="single_modifier_difference",
        direction=GENERALIZATION,
    ),
    PairSpec(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        NEAR,
        "WS4 step 3 (Edgartools round 1) DUK: contract revenue filed "
        "gross of assessed tax under the Including sibling (30,050M; "
        "excise taxes recognized on a gross basis, text L6149; "
        "segment total text L10679)",
        rule="sibling_swap",
    ),
    PairSpec(
        "us-gaap:StockholdersEquity",
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        NEAR,
        "WS4 step 3 (Edgartools round 1) DUK/GIS: candidate is total "
        "equity including noncontrolling interests (DUK 51,256M, "
        "text L3695, with NCI 1,129M at L3693) against the "
        "parent-only target (GIS parent total 9,396.7M, text L3250, "
        "vs 9,648.5M including NCI)",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:AccountsPayableCurrent",
        "",
        "",
        "Phase 3 Step 4 specimen: MSFT payables source, every ASML "
        "match flagged unit-incompatible, none dropped",
        source_firm="MSFT",
        candidate_firm="ASML",
        incompatibility="unit",
    ),
    PairSpec(
        "jpm:NetIncomeLossAttributabletoParentAloneExcludingDividendsand"
        "IncomefromSubsidiariesandAffiliates",
        "us-gaap:NetIncomeLoss",
        EXACT,
        "Completeness Step 13 specimen: the JPM extension is the "
        "parent-alone scope's net income (ParentCompanyMember-dimensioned, "
        "FY2024); BAC files the standard concept under the same scope, "
        "so the pair is EXACT within the scope and only there",
        rule="equality",
        source_firm="JPM",
        candidate_firm="BAC",
        source_scope=(("srt:ConsolidatedEntitiesAxis", "srt:ParentCompanyMember"),),
    ),
)


def evaluate_pairs(
    lookup: Any,
    pairs: tuple[PairSpec, ...] = PAIR_SET,
    source_facts: Any = None,
) -> PairReport:
    """Evaluate seeded pairs through the cohort lookup; mismatches fail.

    Tier pairs read ranked tier/rule/direction from equivalents; fact
    pairs read compatibility from equivalent_facts over supplied facts.
    """
    failures: list[str] = []
    passed = 0
    for spec in pairs:
        label = f"{spec.target} -> {spec.candidate or spec.candidate_firm}"
        if spec.source_firm:
            source = (source_facts or {}).get((spec.source_firm, spec.target))
            if source is None:
                failures.append(f"{label}: no source fact supplied")
                continue
            matches = [
                item
                for item in lookup.equivalent_facts(source)
                if item.firm == spec.candidate_firm
            ]
            if spec.incompatibility:
                ok = bool(matches) and all(
                    not item.compatible and item.incompatibility == spec.incompatibility
                    for item in matches
                )
                if ok:
                    passed += 1
                else:
                    failures.append(
                        f"{label}: expected all {spec.candidate_firm} matches "
                        f"flagged {spec.incompatibility}, got {len(matches)} matches"
                    )
                continue
            scoped = [
                item
                for item in matches
                if item.qname == spec.candidate
                and item.compatible
                and item.tier == spec.tier
                and dict(item.fact.dimensions) == dict(source.dimensions)
            ]
            if scoped:
                passed += 1
            else:
                failures.append(
                    f"{label}: expected a compatible {spec.tier} "
                    f"{spec.candidate_firm} match in the source scope, "
                    f"got {len(matches)} matches"
                )
            continue
        hits = [
            item
            for item in lookup.equivalents(spec.target)
            if item.qname == spec.candidate
        ]
        if not hits:
            failures.append(f"{label}: candidate absent (expected {spec.tier})")
            continue
        actual = hits[0]
        ok = (
            actual.tier == spec.tier
            and (not spec.rule or actual.rule == spec.rule)
            and (not spec.direction or actual.direction == spec.direction)
            and actual.via_default == spec.via_default
        )
        if ok:
            passed += 1
        else:
            failures.append(
                f"{label}: expected tier={spec.tier} rule={spec.rule} "
                f"direction={spec.direction} via_default={spec.via_default}, "
                f"got tier={actual.tier} rule={actual.rule} "
                f"direction={actual.direction} via_default={actual.via_default}"
            )
    return PairReport(total=len(pairs), passed=passed, failures=tuple(failures))
