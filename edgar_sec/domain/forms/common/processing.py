"""Document processing profile contracts for acquisition operations.

This module defines the DocumentProcessingProfile data contract that families use
to declare allowed acquisition operations and capability IDs. It is separate from
PrimaryReportProfile, which focuses on statutory-filing recognition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AcquisitionOperation(StrEnum):
    """Closed vocabulary of acquisition operations.

    These names are versioned and resolved against the acquisition capability catalog.
    """

    RAW = "raw"
    RENDER_TO_TXT = "render_to_txt"
    RENDER_TO_XML = "render_to_xml"


@dataclass(frozen=True, slots=True)
class DocumentProcessingProfile:
    """Declarative processing profile for a form family.

    family, version, allowed_operations.
    """

    family: str
    version: str
    allowed_operations: frozenset[AcquisitionOperation]

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
