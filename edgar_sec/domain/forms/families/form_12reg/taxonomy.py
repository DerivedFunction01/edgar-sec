"""Taxonomy for the Section 12 registration cluster (25 / 8-A / 8-B)."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.form_12reg.models import Form12RegKind

FORM_8A_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "description of securities to be registered",
            "item 1. description of securities to be registered",
            "item 1 description of securities to be registered",
            "description of registrant's securities to be registered",
            "item 1. description of registrant's securities to be registered",
            "item 1 description of registrant's securities to be registered",
            "description of registrant’s securities to be registered",
            "item 1. description of registrant’s securities to be registered",
        ),
    ),
    ItemDefinition(
        "ITEM 2",
        2,
        (
            "exhibits",
            "item 2. exhibits",
            "item 2 exhibits",
        ),
    ),
)

FORM_25_TITLES: tuple[str, ...] = (
    "notification of removal from listing and/or registration",
    "form 25",
)

FORM_8B_TITLES: tuple[str, ...] = (
    "registration of securities of successor issuers",
    "form 8-b",
)

_NOTIFICATION_FORMS = frozenset({"25", "25/A"})
_REGISTRATION_FORMS = frozenset(
    {
        "8-A",
        "8-A12B",
        "8-A12B/A",
        "8-A12G",
        "8-A12G/A",
        "8A12BEF",
        "8A12BT",
        "8A12BT/A",
    }
)
_PREDECESSOR_FORMS = frozenset({"8-B", "8-B12B", "8-B12B/A", "8-B12G"})


def kind_of(form_type: str) -> Form12RegKind:
    """Cluster kind for a form code; unknown codes read as registration."""
    code = form_type.strip().upper()
    if code in _NOTIFICATION_FORMS:
        return Form12RegKind.NOTIFICATION
    if code in _PREDECESSOR_FORMS:
        return Form12RegKind.PREDECESSOR_REGISTRATION
    return Form12RegKind.REGISTRATION


__all__ = [
    "FORM_8A_ITEMS",
    "FORM_25_TITLES",
    "FORM_8B_TITLES",
    "kind_of",
]
