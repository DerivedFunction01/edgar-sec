"""Taxonomy and schema specifications for SEC Form N-MFP filings."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec

N_MFP_SUBMISSION_TYPES = frozenset(
    {"N-MFP", "N-MFP/A", "N-MFP2", "N-MFP2/A", "N-MFP3", "N-MFP3/A"}
)
N_MFP1_NAMESPACE = "http://www.sec.gov/edgar/nmfp"
N_MFP2_NAMESPACE = "http://www.sec.gov/edgar/nmfp2"
N_MFP3_NAMESPACE = "http://www.sec.gov/edgar/nmfp3"
N_MFP_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset(
        {
            N_MFP1_NAMESPACE,
            N_MFP2_NAMESPACE,
            N_MFP3_NAMESPACE,
            "http://www.sec.gov/edgar/common",
            "",
        }
    ),
    root_tags=frozenset({"edgarSubmission"}),
)

N_MFP_GENERATION_BY_NAMESPACE = {
    N_MFP1_NAMESPACE: 1,
    N_MFP2_NAMESPACE: 2,
    N_MFP3_NAMESPACE: 3,
}

__all__ = [
    "N_MFP1_NAMESPACE",
    "N_MFP2_NAMESPACE",
    "N_MFP3_NAMESPACE",
    "N_MFP_GENERATION_BY_NAMESPACE",
    "N_MFP_SUBMISSION_TYPES",
    "N_MFP_XML_SPEC",
]
