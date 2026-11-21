"""Taxonomy and schema specifications for SEC Form N-PX filings."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec

N_PX_SUBMISSION_TYPES = frozenset({"N-PX", "N-PX/A", "N-PX CTR", "N-PX CTR/A"})
N_PX_NAMESPACE = "http://www.sec.gov/edgar/npx"
N_PX_CTR_NAMESPACE = "http://www.sec.gov/edgar/npxctr"
N_PX_VOTE_NAMESPACE = "http://www.sec.gov/edgar/document/npxproxy/informationtable"
N_PX_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset(
        {
            N_PX_NAMESPACE,
            N_PX_CTR_NAMESPACE,
            N_PX_VOTE_NAMESPACE,
            "http://www.sec.gov/edgar/common",
            "",
        }
    ),
    root_tags=frozenset({"edgarSubmission", "proxyVoteTable"}),
)

N_PX_REGISTRANT_TYPES = frozenset({"IM", "RMIC"})
N_PX_REPORT_TYPES = frozenset(
    {
        "FUND VOTING REPORT",
        "FUND NOTICE REPORT",
        "MANAGER VOTING REPORT",
        "MANAGER NOTICE REPORT",
    }
)
N_PX_VOTE_SOURCES = frozenset({"ISSUER", "SECURITY HOLDER"})

__all__ = [
    "N_PX_CTR_NAMESPACE",
    "N_PX_NAMESPACE",
    "N_PX_REGISTRANT_TYPES",
    "N_PX_REPORT_TYPES",
    "N_PX_SUBMISSION_TYPES",
    "N_PX_VOTE_NAMESPACE",
    "N_PX_VOTE_SOURCES",
    "N_PX_XML_SPEC",
]
