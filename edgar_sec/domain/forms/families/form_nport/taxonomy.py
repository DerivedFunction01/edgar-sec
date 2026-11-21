"""Taxonomy and schema specifications for SEC Form N-PORT filings."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec

NPORT_SUBMISSION_TYPES = frozenset(
    {
        "NPORT-P",
        "NPORT-P/A",
        "NPORT-EX",
        "NPORT-EX/A",
        "NPORT-NP",
        "NPORT-NP/A",
    }
)
NPORT_NAMESPACE = "http://www.sec.gov/edgar/nport"
NPORT_COMMON_NAMESPACE = "http://www.sec.gov/edgar/nportcommon"
NPORT_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset(
        {
            NPORT_NAMESPACE,
            NPORT_COMMON_NAMESPACE,
            "http://www.sec.gov/edgar/common",
            "",
        }
    ),
    root_tags=frozenset({"edgarSubmission"}),
)

NPORT_PAYOFF_PROFILES = frozenset({"Long", "Short", "N/A"})
NPORT_YES_NO = frozenset({"Y", "N"})

__all__ = [
    "NPORT_COMMON_NAMESPACE",
    "NPORT_NAMESPACE",
    "NPORT_PAYOFF_PROFILES",
    "NPORT_SUBMISSION_TYPES",
    "NPORT_XML_SPEC",
    "NPORT_YES_NO",
]
