"""Taxonomy and schema specifications for SEC Form N-CEN filings."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec

N_CEN_SUBMISSION_TYPES = frozenset({"N-CEN", "N-CEN/A"})
N_CEN_NAMESPACE = "http://www.sec.gov/edgar/ncen"
N_CEN_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset(
        {
            N_CEN_NAMESPACE,
            "http://www.sec.gov/edgar/common",
            "",
        }
    ),
    root_tags=frozenset({"edgarSubmission"}),
)

N_CEN_YES_NO = frozenset({"Y", "N"})

__all__ = [
    "N_CEN_NAMESPACE",
    "N_CEN_SUBMISSION_TYPES",
    "N_CEN_XML_SPEC",
    "N_CEN_YES_NO",
]
