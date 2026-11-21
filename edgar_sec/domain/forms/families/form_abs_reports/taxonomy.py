"""Taxonomy for the ABS text reports (10-D / ABS-15G).

One item table serves both faces; the canonical order interleaves the
two documents so each face's own sequence stays monotonic. Item titles
carry both eras where the form renumbered them.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.form_abs_reports.models import (
    FormAbsReportsKind,
)

ABS_REPORTS_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "PART I",
        1,
        (
            "distribution information",
            "part i - distribution information",
            "part i – distribution information",
            "part i — distribution information",
            "representation and warranty information",
            "part i: representation and warranty information",
            "part i - representation and warranty information",
        ),
    ),
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "distribution and pool performance information",
            "item 1. distribution and pool performance information",
            "item 1 distribution and pool performance information",
        ),
    ),
    ItemDefinition(
        "ITEM 1A",
        1,
        (
            "asset-level information",
            "item 1a. asset-level information",
            "item 1a asset-level information",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 1B",
        1,
        (
            "asset representations reviewer and investor communication",
            "item 1b. asset representations reviewer and investor communication",
            "item 1b asset representations reviewer and investor communication",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 1.01",
        1,
        (
            "initial filing of rule 15ga-1 representations and warranties disclosure",
            "item 1.01 initial filing of rule 15ga-1 representations and warranties disclosure",
            "item 1.01. initial filing of rule 15ga-1 representations and warranties disclosure",
        ),
    ),
    ItemDefinition(
        "ITEM 1.02",
        1,
        (
            "periodic filing of rule 15ga-1 representations and warranties disclosure",
            "item 1.02 periodic filing of rule 15ga-1 representations and warranties disclosure",
            "item 1.02. periodic filing of rule 15ga-1 representations and warranties disclosure",
        ),
    ),
    ItemDefinition(
        "ITEM 1.03",
        1,
        (
            "notice of termination of duty to file reports under rule 15ga-1",
            "item 1.03 notice of termination of duty to file reports under rule 15ga-1",
            "item 1.03. notice of termination of duty to file reports under rule 15ga-1",
        ),
    ),
    ItemDefinition(
        "PART II",
        2,
        (
            "other information",
            "part ii - other information",
            "part ii – other information",
            "part ii — other information",
            "findings and conclusions of third-party due diligence reports",
            "part ii: findings and conclusions of third-party due diligence reports",
            "part ii - findings and conclusions of third-party due diligence reports",
        ),
    ),
    ItemDefinition(
        "ITEM 2",
        2,
        (
            "legal proceedings",
            "item 2. legal proceedings",
            "item 2 - legal proceedings",
        ),
    ),
    ItemDefinition(
        "ITEM 3",
        2,
        (
            "sales of securities and use of proceeds",
            "item 3. sales of securities and use of proceeds",
            "item 3 - sales of securities and use of proceeds",
        ),
    ),
    ItemDefinition(
        "ITEM 4",
        2,
        (
            "defaults upon senior securities",
            "item 4. defaults upon senior securities",
            "item 4 - defaults upon senior securities",
        ),
    ),
    ItemDefinition(
        "ITEM 5",
        2,
        (
            "submission of matters to a vote of security holders",
            "item 5. submission of matters to a vote of security holders",
            "item 5 - submission of matters to a vote of security holders",
        ),
    ),
    ItemDefinition(
        "ITEM 6",
        2,
        (
            "significant obligors of pool assets",
            "item 6. significant obligors of pool assets",
            "item 6 - significant obligors of pool assets",
        ),
    ),
    ItemDefinition(
        "ITEM 7",
        2,
        (
            "change in sponsor interest in the securities",
            "item 7. change in sponsor interest in the securities",
            "item 7 - change in sponsor interest in the securities",
            "significant enhancement provider information",
            "item 7. significant enhancement provider information",
            "item 7 - significant enhancement provider information",
        ),
    ),
    ItemDefinition(
        "ITEM 8",
        2,
        (
            "significant enhancement provider information",
            "item 8. significant enhancement provider information",
            "item 8 - significant enhancement provider information",
            "other information",
            "item 8. other information",
            "item 8 - other information",
        ),
    ),
    ItemDefinition(
        "ITEM 9",
        2,
        (
            "exhibits",
            "item 9. exhibits",
            "item 9 - exhibits",
            "other information",
            "item 9. other information",
            "item 9 - other information",
        ),
    ),
    ItemDefinition(
        "ITEM 10",
        2,
        (
            "exhibits",
            "item 10. exhibits",
            "item 10 - exhibits",
        ),
    ),
    ItemDefinition(
        "ITEM 2.01",
        2,
        (
            "findings and conclusions of a third party due diligence report obtained by the issuer",
            "findings and conclusions of a third-party due diligence report obtained by the issuer",
            "item 2.01 findings and conclusions of a third party due diligence report obtained by the issuer",
            "item 2.01. findings and conclusions of a third party due diligence report obtained by the issuer",
        ),
    ),
)

FORM_10D_TITLES: tuple[str, ...] = (
    "asset-backed issuer distribution report",
    "form 10-d",
)

FORM_ABS_15G_TITLES: tuple[str, ...] = (
    "asset-backed securitizer report",
    "form abs-15g",
)

_DISTRIBUTION_FORMS = frozenset({"10-D", "10-D/A"})
_SECURITIZER_FORMS = frozenset({"ABS-15G", "ABS-15G/A"})


def kind_of(form_type: str) -> FormAbsReportsKind:
    """Family kind for a form code; unknown codes read as securitizer."""
    code = form_type.strip().upper()
    if code in _DISTRIBUTION_FORMS:
        return FormAbsReportsKind.DISTRIBUTION
    return FormAbsReportsKind.SECURITIZER


__all__ = [
    "ABS_REPORTS_ITEMS",
    "FORM_10D_TITLES",
    "FORM_ABS_15G_TITLES",
    "kind_of",
]
