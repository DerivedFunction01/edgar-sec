"""Schema specification and kind dispatch for SEC Form C (spec v8)."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec
from edgar_sec.domain.forms.families.form_c.models import FormCKind

FORMC_NAMESPACE = "http://www.sec.gov/edgar/formc"
FORMC_COMMON_NAMESPACE = "http://www.sec.gov/edgar/common"

FORMC_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset({FORMC_NAMESPACE, FORMC_COMMON_NAMESPACE, ""}),
    root_tags=frozenset({"edgarSubmission"}),
)

FORMC_SUBMISSION_TYPES = frozenset(
    {
        "C",
        "C/A",
        "C-U",
        "C-AR",
        "C-AR/A",
        "C-TR",
        "C-W",
        "C-AR-W",
        "C-TR-W",
        "C/A-W",
    }
)

_KIND_BY_TYPE = {
    "C": FormCKind.OFFERING,
    "C/A": FormCKind.OFFERING,
    "C-U": FormCKind.PROGRESS,
    "C-AR": FormCKind.ANNUAL_REPORT,
    "C-AR/A": FormCKind.ANNUAL_REPORT,
    "C-TR": FormCKind.TERMINATION,
    "C-W": FormCKind.WITHDRAWAL,
    "C-AR-W": FormCKind.WITHDRAWAL,
    "C-TR-W": FormCKind.WITHDRAWAL,
    "C/A-W": FormCKind.WITHDRAWAL,
}


def kind_of(submission_type: str | None) -> FormCKind:
    """Dispatch a header submission type to its Form C kind."""
    if submission_type is None:
        return FormCKind.UNKNOWN
    return _KIND_BY_TYPE.get(submission_type.strip().upper(), FormCKind.UNKNOWN)


__all__ = [
    "FORMC_COMMON_NAMESPACE",
    "FORMC_NAMESPACE",
    "FORMC_SUBMISSION_TYPES",
    "FORMC_XML_SPEC",
    "kind_of",
]
