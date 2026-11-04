"""Schema specification for SEC Form 25-NSE XML documents (spec v4.3)."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec

FORM25NSE_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset({""}),
    root_tags=frozenset({"notificationOfRemoval"}),
)

# X0203 is the current document schema; X0202 filings remain as filed.
FORM25NSE_SCHEMA_VERSIONS = frozenset({"X0202", "X0203"})

FORM25NSE_RULE_PROVISIONS = frozenset(
    {
        "17 CFR 240.12d2-2(a)(1)",
        "17 CFR 240.12d2-2(a)(2)",
        "17 CFR 240.12d2-2(a)(3)",
        "17 CFR 240.12d2-2(a)(4)",
        "17 CFR 240.12d2-2(b)",
    }
)

__all__ = [
    "FORM25NSE_RULE_PROVISIONS",
    "FORM25NSE_SCHEMA_VERSIONS",
    "FORM25NSE_XML_SPEC",
]
