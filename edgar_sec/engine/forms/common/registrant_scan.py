"""Canonical head-line scan for the registrant name."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.forms.common.entities import NAME_FORM_TOKENS
from edgar_sec.engine.forms.cover.registrant import parse_registrant_identity


@dataclass(frozen=True, slots=True)
class RegistrantLine:
    """A resolved registrant head line, as printed and normalized."""

    raw: str
    name: str


@dataclass(frozen=True, slots=True)
class RegistrantScan:
    """Per-caller gates for the shared registrant head-line scan."""

    window: int
    skip_tokens: tuple[str, ...] = ()
    reject_dollar: bool = True


FACING_SHEET_SCAN = RegistrantScan(
    window=80,
    skip_tokens=(
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
    ),
    reject_dollar=True,
)

ICA_HEAD_FALLBACK_SCAN = RegistrantScan(window=12, reject_dollar=False)

FORM_497_SCAN = RegistrantScan(
    window=20,
    skip_tokens=(
        "filed pursuant",
        "registration no",
        "registration statement",
        "prospectus supplement",
        "prospectus",
        "subject to completion",
    ),
    reject_dollar=True,
)


def scan_registrant_name(
    lines: list[str], scan: RegistrantScan
) -> RegistrantLine | None:
    """First gated head line whose identity parse yields a name."""
    for line in lines[: scan.window]:
        stripped = line.strip()
        if not 3 <= len(stripped) <= 80:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in scan.skip_tokens):
            continue
        if scan.reject_dollar and "$" in stripped:
            continue
        if not stripped[0].isalpha():
            continue
        if not any(token in lowered for token in NAME_FORM_TOKENS):
            continue
        identity = parse_registrant_identity(stripped)
        if identity.name:
            return RegistrantLine(raw=stripped, name=identity.name)
    return None


__all__ = [
    "FACING_SHEET_SCAN",
    "FORM_497_SCAN",
    "ICA_HEAD_FALLBACK_SCAN",
    "RegistrantLine",
    "RegistrantScan",
    "scan_registrant_name",
]
