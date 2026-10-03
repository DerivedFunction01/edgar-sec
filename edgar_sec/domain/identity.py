"""Core identity value objects: Cik and AccessionNumber."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_ACCESSION_DIGITS_RE = re.compile(r"^\d{18}$")


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
        """Format as standard SEC 10-digit zero-padded string."""
        return f"{self.value:010d}"

    def __str__(self) -> str:
        return self.to_10digit()

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class AccessionNumber:
    """SEC Accession Number, held in the hyphenated form (e.g. '0000320193-23-000106')."""

    raw: str

    def __post_init__(self) -> None:
        cleaned = self.raw.strip()
        if not _ACCESSION_RE.match(cleaned):
            raise ValueError(f"invalid SEC accession number format: '{self.raw}'")
        object.__setattr__(self, "raw", cleaned)

    @classmethod
    def from_any(cls, raw: AccessionNumber | str) -> AccessionNumber:
        """Accept either EDGAR spelling and return the hyphenated form.

        EDGAR serves ``0000320193-23-000106`` and ``000032019320000106`` for the
        same filing, and both spellings are important: the
        hyphenated form is the human and bundle-filename convention, while the
        filing catalog and committed fixture rows carry the unhyphenated one.
        Accepting only the hyphenated form made a real catalog plan unloadable
        and split one document across two identities. Normalizing at the
        boundary is what keeps a single identity per filing.
        """
        if isinstance(raw, AccessionNumber):
            return raw
        text = str(raw).strip()
        if not _ACCESSION_RE.match(text):
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


__all__ = ["AccessionNumber", "Cik"]
