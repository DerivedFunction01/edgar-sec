"""Seeded composed-chain benchmark set: evidence on/off expectations.

Companion to benchmark.py's pair set; kept apart so each seeded set
stays inside the file-length budget. Evaluation lives with the
composition surface's tests, which own the chain mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChainSpec:
    """One seeded composed chain with evidence on/off expectations.

    Per mode, the mediated operand's expectations: evidence may change
    which concept resolves or its rung, never a better status.
    """

    label: str
    cohort: str
    resolver: str
    firm: str
    terms: tuple[tuple[str, str], ...]
    mediated_term: str
    on_concept: str | None
    off_concept: str | None
    on_provenance: str
    off_provenance: str
    on_status: str
    off_status: str
    on_unit: str | None
    on_period_key: str | None
    off_unit: str | None
    off_period_key: str | None
    on_value: float | None
    off_value: float | None
    provenance: str


CHAIN_SET: tuple[ChainSpec, ...] = (
    ChainSpec(
        label="msft-fcf-name-control",
        cohort="seed",
        resolver="ladder",
        firm="MSFT",
        terms=(
            ("+", "us-gaap:NetCashProvidedByUsedInOperatingActivities"),
            ("-", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"),
        ),
        mediated_term="us-gaap:NetCashProvidedByUsedInOperatingActivities",
        on_concept="us-gaap:NetCashProvidedByUsedInOperatingActivities",
        off_concept="us-gaap:NetCashProvidedByUsedInOperatingActivities",
        on_provenance="name",
        off_provenance="name",
        on_status="REPORTED",
        off_status="REPORTED",
        on_unit="USD",
        on_period_key="duration:2023-07-01:2024-06-30",
        off_unit="USD",
        off_period_key="duration:2023-07-01:2024-06-30",
        on_value=74_071_000_000.0,
        off_value=74_071_000_000.0,
        provenance=(
            "Phase 4 FCF preset specimen over the MSFT 2024 10-K seed "
            "bundle: both operands resolve to their named concepts in "
            "both evidence modes (the name-evidenced control chain)."
        ),
    ),
    ChainSpec(
        label="fcx-impairment-gated-claim",
        cohort="seed",
        resolver="gated",
        firm="FCX",
        terms=(
            ("+", "us-gaap:ImpairmentOfOilAndGasProperties"),
            ("+", "us-gaap:ProfitLoss"),
        ),
        mediated_term="us-gaap:ImpairmentOfOilAndGasProperties",
        on_concept="us-gaap:ImpairmentOfOilAndGasProperties",
        off_concept="us-gaap:ImpairmentOfOilAndGasProperties",
        on_provenance="gated_claim",
        off_provenance="name",
        on_status="REPORTED",
        off_status="REPORTED",
        on_unit="USD",
        on_period_key="duration:2024-01-01:2024-12-31",
        off_unit="USD",
        off_period_key="duration:2024-01-01:2024-12-31",
        on_value=4_468_000_000.0,
        off_value=4_468_000_000.0,
        provenance=(
            "WS3b specimen: FCX 2024 10-K reports the concept "
            "attested_placed in its own evidence record, so under the "
            "filing's evidence context the gated Impairment-Of claim "
            "fires (H_INCOME {M_IMPAIRMENT}); without evidence the "
            "name decomposes filing-agnostically. Facts are the "
            "filing's own: impairment 69,000,000 and ProfitLoss "
            "4,399,000,000, USD duration 2024-01-01:2024-12-31."
        ),
    ),
    ChainSpec(
        label="filing-local-placement-current",
        cohort="filing_local_fixture",
        resolver="ladder",
        firm="BBB",
        terms=(
            ("+", "us-gaap:AccruedLiabilitiesCurrent"),
            ("+", "us-gaap:CashAndCashEquivalentsAtCarryingValue"),
        ),
        mediated_term="us-gaap:AccruedLiabilitiesCurrent",
        on_concept="us-gaap:AccountsPayable",
        off_concept="us-gaap:AccountsPayable",
        on_provenance="filing_local",
        off_provenance="default",
        on_status="REPORTED",
        off_status="REPORTED",
        on_unit="USD",
        on_period_key="instant:2024-12-31",
        off_unit="USD",
        off_period_key="instant:2024-12-31",
        on_value=600.0,
        off_value=600.0,
        provenance=(
            "WS3a ladder fixture (filing B): bare AccountsPayable "
            "calc-placed under LiabilitiesCurrent. The normative AP "
            "regression case 'placement speaks current': the verdict "
            "equals the default-mediated verdict, flagged "
            "via_filing_local instead of via_default."
        ),
    ),
    ChainSpec(
        label="filing-local-placement-noncurrent",
        cohort="filing_local_fixture",
        resolver="ladder",
        firm="CCC",
        terms=(
            ("+", "us-gaap:AccruedLiabilitiesCurrent"),
            ("+", "us-gaap:CashAndCashEquivalentsAtCarryingValue"),
        ),
        mediated_term="us-gaap:AccruedLiabilitiesCurrent",
        on_concept=None,
        off_concept="us-gaap:AccountsPayable",
        on_provenance="name",
        off_provenance="default",
        on_status="UNAVAILABLE",
        off_status="REPORTED",
        on_unit=None,
        on_period_key=None,
        off_unit="USD",
        off_period_key="instant:2024-12-31",
        on_value=None,
        off_value=600.0,
        provenance=(
            "WS3a ladder fixture (filing C): bare AccountsPayable "
            "calc-placed under LiabilitiesNoncurrent. The normative AP "
            "regression case 'placement speaks noncurrent': filing-"
            "local presumption outranks the global default, so the "
            "current-form operand resolves to no concept under "
            "evidence (the unresolved operand exposes no rung) and "
            "to the default-mediated payables fact without it."
        ),
    ),
)
