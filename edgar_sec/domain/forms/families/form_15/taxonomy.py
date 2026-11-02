"""Form 15 taxonomy for the single-page deregistration notice."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_15_ITEMS: tuple[ItemDefinition, ...] = ()

FORM_15_TITLES: tuple[str, ...] = (
    "certification and notice of termination of registration",
    "suspension of duty to file reports",
    "form 15",
)

__all__ = [
    "FORM_15_ITEMS",
    "FORM_15_TITLES",
]
