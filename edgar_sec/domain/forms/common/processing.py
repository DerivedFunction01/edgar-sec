"""Document processing profile contracts for acquisition operations.

This module defines the DocumentProcessingProfile data contract that families use
to declare allowed acquisition operations and capability IDs. It is separate from
PrimaryReportProfile, which focuses on statutory-filing recognition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edgar_sec.domain.forms.reports import FormReport


class AcquisitionOperation(StrEnum):
    """Closed vocabulary of acquisition operations."""

    RAW = "raw"
    RENDER_TO_TXT = "render_to_txt"
    RENDER_TO_XML = "render_to_xml"


@dataclass(frozen=True, slots=True)
class DocumentProcessingProfile:
    """Declarative processing profile for a form family."""

    family: str
    version: str
    allowed_operations: frozenset[AcquisitionOperation]
    report_class: type[FormReport] | None = None
    preferred_operation: AcquisitionOperation | None = None
    review_analyzer: str | None = None
    has_toc: bool = False
    has_sections: bool = False
    has_notes: bool = False
    has_xbrl: bool = False

    def has_operation(self, operation: AcquisitionOperation) -> bool:
        """Check if this family supports the given operation."""
        return operation in self.allowed_operations


# Default operations for families without explicit profiles
DEFAULT_OPERATIONS = frozenset({AcquisitionOperation.RAW})

__all__ = [
    "AcquisitionOperation",
    "DocumentProcessingProfile",
    "DEFAULT_OPERATIONS",
]
