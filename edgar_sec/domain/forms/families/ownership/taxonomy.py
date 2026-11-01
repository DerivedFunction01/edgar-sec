"""Schema vocabularies for SEC ownership filings."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec
from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES

VALID_TRANSACTION_CODES: frozenset[str] = frozenset(
    {
        "A",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "I",
        "J",
        "L",
        "M",
        "O",
        "P",
        "S",
        "U",
        "W",
        "X",
        "Z",
    }
)
OWNERSHIP_DOCUMENT_TYPES = frozenset({"3", "3/A", "4", "4/A", "5", "5/A"})
OWNERSHIP_ACQUIRED_DISPOSED_CODES = frozenset({"A", "D"})
OWNERSHIP_TYPE_CODES = frozenset({"D", "I"})
OWNERSHIP_TRANSACTION_FORM_TYPES = frozenset({"4", "5"})
OWNERSHIP_HOLDING_FORM_TYPES = frozenset({"3"})
OWNERSHIP_TIMELINESS_CODES = frozenset({"E", "L"})

OWNERSHIP_STATE_CODES = STATE_POSTAL_CODES | frozenset({"AS", "MP"})
OWNERSHIP_XML_NAMESPACE = "http://www.sec.gov/edgar/ownership"
OWNERSHIP_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset({OWNERSHIP_XML_NAMESPACE, ""}),
    root_tags=frozenset({"ownershipDocument"}),
)

__all__ = [
    "OWNERSHIP_ACQUIRED_DISPOSED_CODES",
    "OWNERSHIP_DOCUMENT_TYPES",
    "OWNERSHIP_HOLDING_FORM_TYPES",
    "OWNERSHIP_STATE_CODES",
    "OWNERSHIP_TIMELINESS_CODES",
    "OWNERSHIP_TRANSACTION_FORM_TYPES",
    "OWNERSHIP_TYPE_CODES",
    "OWNERSHIP_XML_NAMESPACE",
    "OWNERSHIP_XML_SPEC",
    "VALID_TRANSACTION_CODES",
]
