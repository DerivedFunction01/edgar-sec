"""Form 40-F furnished-document kinds; the form has no item taxonomy.

The body is furnished Canadian documents, segmented by kind at the
engine step: annual information form, financial statements, MD&A, and
other exhibits as filed.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_40F_ITEMS: tuple[ItemDefinition, ...] = ()

FORM_40F_TITLES: tuple[str, ...] = ("form 40-f",)

FORM_40F_FURNISHED_KINDS: dict[str, tuple[str, ...]] = {
    "aif": ("annual information form",),
    "financial_statements": (
        "audited annual financial statements",
        "annual financial statements",
    ),
    "mda": (
        "management's discussion and analysis",
        "management’s discussion and analysis",
    ),
    "other_exhibits": ("other exhibits",),
}

__all__ = [
    "FORM_40F_FURNISHED_KINDS",
    "FORM_40F_ITEMS",
    "FORM_40F_TITLES",
]
