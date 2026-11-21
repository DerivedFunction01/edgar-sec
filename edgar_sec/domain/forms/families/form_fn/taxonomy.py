"""Form F-N lettered appointment items as a flat field set; no taxonomy."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_FN_ITEMS: tuple[ItemDefinition, ...] = ()

FORM_FN_TITLES: tuple[str, ...] = (
    "form f-n",
    "appointment of agent for service of process",
)

FORM_FN_LETTERED_ITEMS: tuple[tuple[str, str], ...] = (
    ("A", "name of issuer or person filing"),
    ("B", "this is (select one)"),
    ("C", "identify the filing in conjunction with which this form is being filed"),
    ("D", "filer jurisdiction and principal place of business"),
    ("E", "designation and appointment of agent for service of process"),
    ("F", "successor agent stipulation and undertaking"),
    ("G", "undertaking to respond to commission staff inquiries"),
)

__all__ = [
    "FORM_FN_ITEMS",
    "FORM_FN_LETTERED_ITEMS",
    "FORM_FN_TITLES",
]
