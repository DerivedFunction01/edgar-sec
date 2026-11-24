"""Profile types: the measured-support and family-profile dataclasses."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_EX13,
    PROV_FAMILY_SUPPORT,
    PROSE_WINDOW_NONE,
)


@dataclass(frozen=True, slots=True)
class SupportState:
    """Measured support for one family: precision/recall per stratum."""

    annual_precision: float | None
    annual_recall: float | None
    quarterly_precision: float | None
    quarterly_recall: float | None
    quarterly_directed_recall: float | None = None
    assembly_quarterly_precision: float | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ExhibitLink:
    """One exhibit type declared as an evidence source (R3)."""

    exhibit_type: str
    strata: tuple[str, ...]
    provenance: str = PROV_EX13


@dataclass(frozen=True, slots=True)
class FamilyProfile:
    """One supported family's profile: support, seat, tests, links."""

    family: str
    kind: str
    support: SupportState | None
    vocabulary_seat: str
    form_tests: tuple[str, ...] = ()
    gate_bindings: tuple[str, ...] = ()
    exhibit_links: tuple[ExhibitLink, ...] = ()
    prose_window: str = PROSE_WINDOW_NONE
    region_gate: str | None = None
    shape: str | None = None
    note: str = ""
    provenance: str = PROV_FAMILY_SUPPORT
