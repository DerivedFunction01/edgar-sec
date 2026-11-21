"""Taxonomy and schema specifications for SEC Form D filings."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec

FORMD_SUBMISSION_TYPES = frozenset({"D", "D/A", "REGDEX", "REGDEX/A"})
FORMD_LIVE_TEST_TYPES = frozenset({"LIVE", "TEST"})
FORMD_XML_NAMESPACE = "http://www.sec.gov/edgar/formd"
FORMD_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset({FORMD_XML_NAMESPACE, "http://www.sec.gov/edgar/common", ""}),
    root_tags=frozenset({"edgarSubmission"}),
)

FORMD_ENTITY_TYPES = frozenset(
    {
        "Corporation",
        "Limited Partnership",
        "Limited Liability Company",
        "General Partnership",
        "Business Trust",
        "Other",
    }
)

FORMD_REVENUE_RANGES = frozenset(
    {
        "No Revenues",
        "$1 - $1,000,000",
        "$1,000,001 - $5,000,000",
        "$5,000,001 - $25,000,000",
        "$25,000,001 - $100,000,000",
        "Over $100,000,000",
        "Decline to Disclose",
        "Not Applicable",
    }
)

__all__ = [
    "FORMD_ENTITY_TYPES",
    "FORMD_LIVE_TEST_TYPES",
    "FORMD_REVENUE_RANGES",
    "FORMD_SUBMISSION_TYPES",
    "FORMD_XML_NAMESPACE",
    "FORMD_XML_SPEC",
]
