"""Schema specification, kind dispatch, and item taxonomies for Reg A."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec
from edgar_sec.domain.forms.families.form_rega.models import RegAKind

REGA_OFFERING_NAMESPACE = "http://www.sec.gov/edgar/rega/oneafiler"
REGA_ANNUAL_NAMESPACE = "http://www.sec.gov/edgar/rega/onekfiler"
REGA_EXIT_NAMESPACE = "http://www.sec.gov/edgar/rega/onezfiler"
REGA_COMMON_NAMESPACE = "http://www.sec.gov/edgar/common"

REGA_OFFERING_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset({REGA_OFFERING_NAMESPACE, REGA_COMMON_NAMESPACE, ""}),
    root_tags=frozenset({"edgarSubmission"}),
)
REGA_ANNUAL_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset({REGA_ANNUAL_NAMESPACE, REGA_COMMON_NAMESPACE, ""}),
    root_tags=frozenset({"edgarSubmission"}),
)
REGA_EXIT_XML_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset({REGA_EXIT_NAMESPACE, REGA_COMMON_NAMESPACE, ""}),
    root_tags=frozenset({"edgarSubmission"}),
)

REGA_SUBMISSION_TYPES = frozenset(
    {"1-A", "1-A/A", "1-A POS", "1-K", "1-K/A", "1-Z", "1-Z/A"}
)

_KIND_BY_TYPE = {
    "1-A": RegAKind.OFFERING,
    "1-A/A": RegAKind.OFFERING,
    "1-A POS": RegAKind.OFFERING,
    "1-K": RegAKind.ANNUAL_REPORT,
    "1-K/A": RegAKind.ANNUAL_REPORT,
    "1-Z": RegAKind.EXIT_REPORT,
    "1-Z/A": RegAKind.EXIT_REPORT,
}

_KIND_BY_FORM = {
    **_KIND_BY_TYPE,
    "1-A-W": RegAKind.WITHDRAWAL,
    "1-A-W/A": RegAKind.WITHDRAWAL,
    "1-SA": RegAKind.SEMI_ANNUAL,
    "1-SA/A": RegAKind.SEMI_ANNUAL,
    "1-U": RegAKind.CURRENT,
    "1-U/A": RegAKind.CURRENT,
}


def kind_of(submission_type: str | None) -> RegAKind:
    """Dispatch a header submission type to its Reg A kind."""
    if submission_type is None:
        return RegAKind.UNKNOWN
    return _KIND_BY_TYPE.get(submission_type.strip().upper(), RegAKind.UNKNOWN)


def kind_of_form(form_code: str) -> RegAKind:
    """Dispatch a catalog form code to its Reg A kind."""
    return _KIND_BY_FORM.get(form_code.strip().upper(), RegAKind.UNKNOWN)


FORM_1SA_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "management's discussion and analysis of financial condition and results of operations",
            "item 1. management's discussion and analysis of financial condition and results of operations",
            "item 1 management's discussion and analysis of financial condition and results of operations",
            "management’s discussion and analysis of financial condition and results of operations",
            "item 1. management’s discussion and analysis of financial condition and results of operations",
        ),
    ),
    ItemDefinition(
        "ITEM 2",
        2,
        (
            "other information",
            "item 2. other information",
            "item 2 other information",
        ),
    ),
    ItemDefinition(
        "ITEM 3",
        3,
        (
            "financial statements",
            "item 3. financial statements",
            "item 3 financial statements",
        ),
    ),
    ItemDefinition(
        "ITEM 4",
        4,
        (
            "exhibits",
            "item 4. exhibits",
            "item 4 exhibits",
        ),
    ),
)

FORM_1U_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "fundamental changes",
            "item 1. fundamental changes",
            "item 1 fundamental changes",
        ),
    ),
    ItemDefinition(
        "ITEM 2",
        2,
        (
            "bankruptcy or receivership",
            "item 2. bankruptcy or receivership",
            "item 2 bankruptcy or receivership",
        ),
    ),
    ItemDefinition(
        "ITEM 3",
        3,
        (
            "material modification to rights of securityholders",
            "item 3. material modification to rights of securityholders",
            "item 3 material modification to rights of securityholders",
        ),
    ),
    ItemDefinition(
        "ITEM 4",
        4,
        (
            "change in issuer's certifying accountant",
            "item 4. change in issuer's certifying accountant",
            "change in issuer’s certifying accountant",
            "item 4. change in issuer’s certifying accountant",
            "changes in issuer’s certifying accountant",
            "item 4. changes in issuer’s certifying accountant",
            "change of issuer's certifying accountant",
        ),
    ),
    ItemDefinition(
        "ITEM 5",
        5,
        (
            "non-reliance on previous financial statements or a related audit report or completed interim review",
            "item 5. non-reliance on previous financial statements or a related audit report or completed interim review",
            "non-reliance on previous financial statements",
        ),
    ),
    ItemDefinition(
        "ITEM 6",
        6,
        (
            "changes in control of issuer",
            "item 6. changes in control of issuer",
            "item 6 changes in control of issuer",
            "change in control of issuer",
        ),
    ),
    ItemDefinition(
        "ITEM 7",
        7,
        (
            "departure of certain officers",
            "item 7. departure of certain officers",
            "item 7 departure of certain officers",
            "departure of certain corporate officers",
            "item 7: departure of certain corporate officers",
        ),
    ),
    ItemDefinition(
        "ITEM 8",
        8,
        (
            "election of directors; appointment of certain officers; compensatory arrangements of certain officers",
            "item 8. election of directors; appointment of certain officers; compensatory arrangements of certain officers",
            "election of directors",
            "compensatory arrangements of certain officers",
        ),
    ),
    ItemDefinition(
        "ITEM 9",
        9,
        (
            "other events",
            "item 9. other events",
            "item 9 other events",
        ),
    ),
)

FORM_1SA_TITLES: tuple[str, ...] = ("semiannual report pursuant to regulation a",)
FORM_1U_TITLES: tuple[str, ...] = ("current report pursuant to regulation a",)

__all__ = [
    "FORM_1SA_ITEMS",
    "FORM_1SA_TITLES",
    "FORM_1U_ITEMS",
    "FORM_1U_TITLES",
    "REGA_ANNUAL_NAMESPACE",
    "REGA_ANNUAL_XML_SPEC",
    "REGA_COMMON_NAMESPACE",
    "REGA_EXIT_NAMESPACE",
    "REGA_EXIT_XML_SPEC",
    "REGA_OFFERING_NAMESPACE",
    "REGA_OFFERING_XML_SPEC",
    "REGA_SUBMISSION_TYPES",
    "kind_of",
    "kind_of_form",
]
