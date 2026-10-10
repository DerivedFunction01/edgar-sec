"""Core identity value objects: Cik and AccessionNumber."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_ACCESSION_DIGITS_RE = re.compile(r"^\d{18}$")


def is_hyphenated_accession(value: str) -> bool:
    return _ACCESSION_RE.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Cik:
    """SEC Central Index Key (CIK), stored as a numeric integer with 10-digit zero padding."""

    value: int

    def __post_init__(self) -> None:
        if self.value < 0 or self.value > 9_999_999_999:
            raise ValueError(f"invalid CIK value: {self.value}")

    @classmethod
    def from_raw(cls, raw: int | str) -> Cik:
        """Create a Cik from integer or string, stripping leading zeros and whitespace."""
        if isinstance(raw, int):
            return cls(raw)
        cleaned = str(raw).strip().lstrip("0")
        return cls(int(cleaned) if cleaned else 0)

    def to_10digit(self) -> str:
        return f"{self.value:010d}"

    def __str__(self) -> str:
        return self.to_10digit()

    def __int__(self) -> int:
        return self.value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Cik):
            return NotImplemented
        return self.value < other.value


@dataclass(frozen=True, slots=True)
class AccessionNumber:
    """SEC Accession Number, held in the hyphenated form (e.g. '0000320193-23-000106')."""

    raw: str

    def __post_init__(self) -> None:
        cleaned = self.raw.strip()
        if not is_hyphenated_accession(cleaned):
            raise ValueError(f"invalid SEC accession number format: '{self.raw}'")
        object.__setattr__(self, "raw", cleaned)

    @classmethod
    def from_any(cls, raw: AccessionNumber | str) -> AccessionNumber:
        """Accept either EDGAR spelling and return the hyphenated form.

        Both spellings are real -- catalog and fixture rows carry the unhyphenated one --
        so rejecting it split one document across two identities.
        """
        if isinstance(raw, AccessionNumber):
            return raw
        text = str(raw).strip()
        if not is_hyphenated_accession(text):
            digits = text.replace("-", "")
            if _ACCESSION_DIGITS_RE.match(digits):
                text = f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"
        return cls(text)

    @property
    def normalized(self) -> str:
        """Accession number without hyphens (20 alphanumeric characters)."""
        return self.raw.replace("-", "")

    def __str__(self) -> str:
        return self.raw

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, AccessionNumber):
            return NotImplemented
        return self.raw < other.raw


__all__ = ["AccessionNumber", "Cik", "is_hyphenated_accession"]
