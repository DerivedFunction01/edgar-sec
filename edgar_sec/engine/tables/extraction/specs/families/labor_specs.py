"""Labor-form spec registry: the S6-B seat's priced signature data.

The bargaining-unit enumeration signature as priced on the
covered verified core (S6-B pricing record): term tuples verbatim
from the pricing instrument, with the priced covered-core cells.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import PROV_S6B_PRICING


@dataclass(frozen=True, slots=True)
class LaborEvidenceSpec:
    """One family's labor-form seat, as priced (S6-B).
    The priced cells are the covered verified core: seated of
    positives, touches on the covered negative populations."""

    family: str
    test_id: str
    seated: int
    positives: int
    neg_t1_touched: int
    neg_t1_tables: int
    neg_t2_touched: int
    neg_t2_tables: int
    provenance: str = PROV_S6B_PRICING


LABOR_EVIDENCE_SPECS: dict[str, LaborEvidenceSpec] = {
    "labor_contracts": LaborEvidenceSpec(
        family="labor_contracts",
        test_id="labor_contracts_form",
        seated=36,
        positives=36,
        neg_t1_touched=0,
        neg_t1_tables=272,
        neg_t2_touched=0,
        neg_t2_tables=55,
    ),
}

LABOR_EVIDENCE_SPECS_BY_TEST_ID: dict[str, LaborEvidenceSpec] = {
    spec.test_id: spec for spec in LABOR_EVIDENCE_SPECS.values()
}

# Header vocabulary of the priced signature (s6bprice.py, verbatim).
# hdr is the joined cells of the table's first two rows; stub is
# the joined first cell of each row.
REP_HDR: tuple[str, ...] = (
    "representative",
    "represented by",
    "union name",
    "union",
    "bargaining unit",
)
COUNT_HDR: tuple[str, ...] = (
    "number of employees",
    "no. of employees",
    "employees covered",
    "number of union employees",
    "headcount",
    "percentage of workforce",
    "% of workforce",
    "employees represented",
    "approximate number",
)
WORKFORCE_HDR: tuple[str, ...] = (
    "crewmembers",
    "crew members",
    "workforce",
    "associates",
    "team members",
    "personnel",
    "employees",
)
DATE_HDR: tuple[str, ...] = (
    "expiration",
    "amendable",
    "effective date",
    "contract status",
    "status of agreement",
    "contract start",
    "contract end",
    "agreement open",
    "expires",
    "amendable date",
    "open for amendment",
)
UNION_NAMES: tuple[str, ...] = (
    "air line pilots",
    "flight attendants association",
    "association of flight attendants",
    "machinists",
    "teamsters",
    "transport workers",
    "aircraft mechanics fraternal",
    "united food and commercial workers",
    "united steel",
    "steelworkers",
    "sindicato",
    "unifor",
    "employees representation association",
    "alpa",
    "afa",
    "iam",
    "ibt",
    "twu",
    "amfa",
    "ufcw",
    "usw",
    "pafca",
    "newsguild",
    "guild",
)
