"""SUPPL cover model keyed on the supplement caption; no item taxonomy.

A supplement names its base form through the general-instruction
reference (F-9 II.K / F-10 II.L), its file number, its supplement kind,
and the base-prospectus date chain; those captions are the cover keys.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_SUPPL_ITEMS: tuple[ItemDefinition, ...] = ()

FORM_SUPPL_BASE_FORMS: tuple[str, ...] = ("F-9", "F-10")

FORM_SUPPL_INSTRUCTION_REFERENCES: tuple[str, ...] = (
    "general instruction ii.k of form f-9",
    "general instruction ii.l of form f-10",
)

FORM_SUPPL_KINDS: tuple[str, ...] = (
    "prospectus supplement",
    "pricing supplement",
    "preliminary prospectus supplement",
    "preliminary pricing supplement",
)

FORM_SUPPL_BASE_PROSPECTUS_PHRASES: tuple[str, ...] = (
    "to the short form base shelf prospectus dated",
    "to the base shelf prospectus dated",
    "short form base shelf prospectus dated",
    "base shelf prospectus dated",
)

__all__ = [
    "FORM_SUPPL_BASE_FORMS",
    "FORM_SUPPL_BASE_PROSPECTUS_PHRASES",
    "FORM_SUPPL_INSTRUCTION_REFERENCES",
    "FORM_SUPPL_ITEMS",
    "FORM_SUPPL_KINDS",
]
