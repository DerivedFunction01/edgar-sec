"""D3 translator: registry exhibit links to generic planning triples.

The only registry-aware piece on the classification surface: it reads
family profiles as data and emits planning's role/type/optional shape.
Planning and acquisition stay generic and never import the registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.profiles import (
    PROFILES,
    FamilyProfile,
    registry_fingerprint,
    registry_state,
)

from .planner import (
    DocumentTargetRow,
    FilingRow,
    PlanRequest,
    ProfileApplicationRow,
)

__all__ = [
    "FamilyTargets",
    "PlanningTriple",
    "family_targets",
    "plan_request_for",
    "planning_triples",
    "profile_application_rows",
    "registry_state_detail",
    "triples_for_family",
]

ROLE_EXHIBIT = "exhibit"


@dataclass(frozen=True, slots=True)
class PlanningTriple:
    """One generic planning target: role, type, optional."""

    role: str
    type: str
    optional: bool

    def as_dict(self) -> dict[str, object]:
        """This triple in planning's serialized target shape."""
        return {"role": self.role, "type": self.type, "optional": self.optional}


@dataclass(frozen=True, slots=True)
class FamilyTargets:
    """One family's declared exhibit targets, as generic triples."""

    family: str
    triples: tuple[PlanningTriple, ...]


def _selected(
    profiles: tuple[FamilyProfile, ...],
    families: tuple[str, ...] | None,
) -> tuple[FamilyProfile, ...]:
    if families is None:
        return profiles
    by_family = {profile.family: profile for profile in profiles}
    selected: list[FamilyProfile] = []
    for family in families:
        profile = by_family.get(family)
        if profile is None:
            raise ValueError(f"no registry profile for family: {family}")
        selected.append(profile)
    return tuple(selected)


def _triples_for_profile(
    profile: FamilyProfile, stratum: str | None
) -> tuple[PlanningTriple, ...]:
    triples: list[PlanningTriple] = []
    seen: set[str] = set()
    for link in profile.exhibit_links:
        if stratum is not None and stratum not in link.strata:
            continue
        exhibit_type = link.exhibit_type.strip().upper()
        if not exhibit_type or exhibit_type in seen:
            continue
        seen.add(exhibit_type)
        triples.append(PlanningTriple(ROLE_EXHIBIT, exhibit_type, True))
    return tuple(triples)


def triples_for_family(
    family: str,
    *,
    profiles: tuple[FamilyProfile, ...] = PROFILES,
    stratum: str | None = None,
) -> tuple[PlanningTriple, ...]:
    """The generic exhibit triples one family's profile declares."""
    (profile,) = _selected(profiles, (family,))
    return _triples_for_profile(profile, stratum)


def family_targets(
    *,
    profiles: tuple[FamilyProfile, ...] = PROFILES,
    families: tuple[str, ...] | None = None,
    stratum: str | None = None,
) -> tuple[FamilyTargets, ...]:
    """Per-family exhibit targets, only for families declaring any."""
    rows: list[FamilyTargets] = []
    for profile in _selected(profiles, families):
        triples = _triples_for_profile(profile, stratum)
        if triples:
            rows.append(FamilyTargets(profile.family, triples))
    return tuple(rows)


def planning_triples(
    *,
    profiles: tuple[FamilyProfile, ...] = PROFILES,
    families: tuple[str, ...] | None = None,
    stratum: str | None = None,
) -> tuple[PlanningTriple, ...]:
    """Every distinct generic triple the selected profiles declare."""
    triples: list[PlanningTriple] = []
    seen: set[tuple[str, str, bool]] = set()
    for row in family_targets(profiles=profiles, families=families, stratum=stratum):
        for triple in row.triples:
            key = (triple.role, triple.type, triple.optional)
            if key not in seen:
                seen.add(key)
                triples.append(triple)
    return tuple(triples)


def profile_application_rows(
    accessions: tuple[str, ...],
    *,
    profiles: tuple[FamilyProfile, ...] = PROFILES,
    families: tuple[str, ...] | None = None,
) -> tuple[dict[str, object], ...]:
    """Profile-application rows for a plan, in the core contract shape.

    One row per (accession, family): accession, family, kind, and
    vocabulary_seat, read from the registry profile verbatim.
    """
    rows: list[dict[str, object]] = []
    for profile in _selected(profiles, families):
        for accession in accessions:
            rows.append(
                {
                    "accession": accession,
                    "family": profile.family,
                    "kind": profile.kind,
                    "vocabulary_seat": profile.vocabulary_seat,
                }
            )
    rows.sort(key=lambda row: (str(row["accession"]), str(row["family"])))
    return tuple(rows)


def plan_request_for(
    accessions: tuple[str, ...],
    *,
    source_snapshot_id: str | None = None,
    stratum: str | None = None,
    form: str = "",
    families: tuple[str, ...] | None = None,
    normalize_version: str | None = None,
    renderer_version: str | None = None,
    provenance_route: str = "render_to_txt",
    created_at: str | None = None,
    profiles: tuple[FamilyProfile, ...] = PROFILES,
) -> PlanRequest:
    """One core plan request assembled from registry data.

    The translator's rows as the planner's typed rows: filings,
    profile applications, and per-filing document targets.
    """
    if not accessions:
        raise ValueError("a classification plan needs at least one accession")
    scoped = _selected(profiles, families)
    scoped_names = tuple(profile.family for profile in scoped)
    ordered = tuple(sorted(accessions))
    filings = tuple(
        FilingRow(
            accession=accession,
            cik=None,
            form=form,
            filing_date=None,
            stratum=stratum,
        )
        for accession in ordered
    )
    application = tuple(
        ProfileApplicationRow(
            accession=str(row["accession"]),
            family=str(row["family"]),
            kind=str(row["kind"]),
            vocabulary_seat=str(row["vocabulary_seat"]),
        )
        for row in profile_application_rows(
            ordered, profiles=scoped, families=scoped_names
        )
    )
    exhibit_triples = planning_triples(profiles=scoped, stratum=stratum)
    targets: list[DocumentTargetRow] = []
    for accession in ordered:
        targets.append(
            DocumentTargetRow(
                accession=accession,
                target_role="primary",
                target_type="primary",
                optional=False,
                provenance_route=provenance_route,
            )
        )
        targets.extend(
            DocumentTargetRow(
                accession=accession,
                target_role=triple.role,
                target_type=triple.type,
                optional=triple.optional,
                provenance_route=provenance_route,
            )
            for triple in exhibit_triples
        )
    return PlanRequest(
        registry_state=registry_state(profiles=profiles),
        source_snapshot_id=source_snapshot_id or "",
        normalize_version=normalize_version or "",
        renderer_version=renderer_version or "",
        filings=filings,
        profile_application=application,
        document_targets=tuple(targets),
        created_at=created_at,
    )


def registry_state_detail(
    *,
    profiles: tuple[FamilyProfile, ...] = PROFILES,
) -> dict[str, object]:
    """Identity of the registry state a translation was made from."""
    return {
        "digest": registry_fingerprint(profiles),
        "profile_count": len(profiles),
        "families": [profile.family for profile in profiles],
        "exhibit_types": sorted(
            {
                link.exhibit_type.strip().upper()
                for profile in profiles
                for link in profile.exhibit_links
            }
        ),
        "provenances": sorted({profile.provenance for profile in profiles}),
    }
