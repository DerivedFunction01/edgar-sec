"""Shared facing-sheet field extraction for registration statements."""

from __future__ import annotations

from typing import Any

from edgar_sec.engine.forms.common.entities import (
    extract_cusip_near_caption,
    extract_registration_number,
)
from edgar_sec.engine.forms.common.registrant_scan import (
    FACING_SHEET_SCAN,
    scan_registrant_name,
)

FEE_TABLE_PHRASE = "calculation of registration fee"


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


def facing_sheet_fields(cover_text: str, lines: list[str], form: str) -> dict[str, Any]:
    """Extract the cover fields shared by the registration families."""
    head_text = "\n".join(lines[:120])
    primary = cover_text if len(cover_text.splitlines()) >= 4 else head_text
    registrant = scan_registrant_name(lines, FACING_SHEET_SCAN)
    return {
        "registrant_name": registrant.name if registrant else None,
        "registration_number": extract_registration_number(primary)
        or extract_registration_number(head_text)
        or extract_registration_number("\n".join(lines)),
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
