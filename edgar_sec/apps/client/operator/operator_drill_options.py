from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.apps.client.operator.operator_kit import help_field as _f

__all__ = [
    "DETAIL_LEVELS",
    "BackOptions",
    "NotesListOptions",
    "PrimaryDocumentOptions",
    "ReadNoteOptions",
    "ReadSectionOptions",
    "SectionsListOptions",
    "SelectFilingOptions",
    "TocOptions",
]


DETAIL_LEVELS = ("minimal", "standard", "full")


_DETAIL_HELP = "Detail dial (minimal, standard, full): minimal serves the lead block only, standard the complete item text, full the complete text plus its structural context. The dial selects structure, never a character count; any other value is refused."


_LIMIT_HELP = "Maximum rows shown; total versus shown is declared. Refused below 1."


_PATH_HELP = "Destination path; empty writes to the operator-saves area under the facade's artifacts root, and the result reports the path and byte size."


@dataclass(frozen=True, slots=True)
class SelectFilingOptions:
    """Options for moving the drill-down position to one filing."""

    accession: str = _f(
        "",
        "Accession to select from the current set. Refusal: a set retaining "
        "accessions only (no result) is refused, because drill-down needs "
        "the filing aggregates; an accession outside the set is not_found.",
    )


@dataclass(frozen=True, slots=True)
class BackOptions:
    """Options for clearing the drill-down position."""


@dataclass(frozen=True, slots=True)
class PrimaryDocumentOptions:
    """Options for reading the current filing's primary document."""

    detail: str = _f("standard", _DETAIL_HELP)


@dataclass(frozen=True, slots=True)
class SectionsListOptions:
    """Options for listing the current filing's sections."""

    limit: int = _f(20, _LIMIT_HELP)


@dataclass(frozen=True, slots=True)
class ReadSectionOptions:
    """Options for reading one section of the current filing."""

    item: str = _f(
        "", "Section item identifier (e.g. ITEM 1A); an unknown item is not_found."
    )
    detail: str = _f("standard", _DETAIL_HELP)


@dataclass(frozen=True, slots=True)
class NotesListOptions:
    """Options for listing the current filing's notes."""

    limit: int = _f(20, _LIMIT_HELP)


@dataclass(frozen=True, slots=True)
class ReadNoteOptions:
    """Options for reading one note of the current filing."""

    number: int = _f(0, "Note number; an unknown number is not_found.")
    detail: str = _f("standard", _DETAIL_HELP)


@dataclass(frozen=True, slots=True)
class TocOptions:
    """Options for showing the current filing's table of contents span."""
