"""Shared facing-sheet field extraction for registration statements."""

from __future__ import annotations

from typing import Any

from edgar_sec.engine.forms.common.entities import (
    NAME_FORM_TOKENS,
    extract_cusip_near_caption,
    extract_registration_number,
)
from edgar_sec.engine.forms.cover.registrant import parse_registrant_identity

FEE_TABLE_PHRASE = "calculation of registration fee"

_SKIP_TOKENS: tuple[str, ...] = (
    "securities and exchange commission",
    "washington",
    "form f-",
    "registration statement under",
    "securities act of 1933",
    "registration no",
    "file no",
    "files nos",
    "calculation of registration fee",
    "check the appropriate box",
    "check one",
)


def registration_document_kind(form: str) -> str:
    """Classify a registration form code into its document kind."""
    code = form.upper()
    if code.endswith("POS"):
        return "post_effective_amendment"
    if "ASR" in code:
        return "automatic_shelf_registration"
    if "MEF" in code:
        return "additional_securities_mef"
    if code.endswith("/A"):
        return "amendment"
    if code == "F-3D":
        return "dividend_reinvestment_plan"
    return "registration_statement"


def _registrant_name(lines: list[str]) -> str | None:
    for line in lines[:80]:
        stripped = line.strip()
        if not 3 <= len(stripped) <= 80:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in _SKIP_TOKENS):
            continue
        if "$" in stripped or not stripped[0].isalpha():
            continue
        if not any(token in lowered for token in NAME_FORM_TOKENS):
            continue
        identity = parse_registrant_identity(stripped)
        if identity.name:
            return identity.name
    return None


def facing_sheet_fields(cover_text: str, lines: list[str], form: str) -> dict[str, Any]:
    """Extract the cover fields shared by the registration families."""
    head_text = "\n".join(lines[:120])
    primary = cover_text if len(cover_text.splitlines()) >= 4 else head_text
    full_text = "\n".join(lines)
    return {
        "registrant_name": _registrant_name(lines),
        "registration_number": extract_registration_number(primary)
        or extract_registration_number(head_text)
        or extract_registration_number(full_text),
        "document_kind": registration_document_kind(form),
        "fee_table_present": FEE_TABLE_PHRASE in primary.lower()
        or FEE_TABLE_PHRASE in head_text.lower(),
        "cusip": extract_cusip_near_caption(primary),
    }


__all__ = [
    "FEE_TABLE_PHRASE",
    "facing_sheet_fields",
    "registration_document_kind",
]
