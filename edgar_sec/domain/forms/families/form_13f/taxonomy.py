"""Taxonomy and schema specifications for SEC Form 13F filings."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec

FORM13F_SUBMISSION_TYPES = frozenset(
    {"13F-HR", "13F-HR/A", "13F-CTR", "13F-CTR/A", "13F-NT", "13F-NT/A"}
)
FORM13F_SUBMISSION_NAMESPACE = "http://www.sec.gov/edgar/thirteenffiler"
FORM13F_XML_NAMESPACE = "http://www.sec.gov/edgar/document/thirteenf/informationtable"
FORM13F_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset(
        {
            FORM13F_SUBMISSION_NAMESPACE,
            FORM13F_XML_NAMESPACE,
            "http://www.sec.gov/edgar/common",
            "",
        }
    ),
    root_tags=frozenset({"edgarSubmission", "informationTable"}),
)

FORM13F_REPORT_TYPES = frozenset(
    {"13F HOLDINGS REPORT", "13F NOTICE", "13F COMBINATION REPORT"}
)
FORM13F_AMENDMENT_TYPES = frozenset({"RESTATEMENT", "NEW HOLDINGS"})
FORM13F_AMOUNT_TYPES = frozenset({"SH", "PRN"})
FORM13F_PUT_CALL = frozenset({"Put", "Call"})
FORM13F_INVESTMENT_DISCRETION = frozenset({"SOLE", "DFND", "OTR"})

__all__ = [
    "FORM13F_AMENDMENT_TYPES",
    "FORM13F_AMOUNT_TYPES",
    "FORM13F_INVESTMENT_DISCRETION",
    "FORM13F_PUT_CALL",
    "FORM13F_REPORT_TYPES",
    "FORM13F_SUBMISSION_NAMESPACE",
    "FORM13F_SUBMISSION_TYPES",
    "FORM13F_XML_NAMESPACE",
    "FORM13F_XML_SPEC",
]
