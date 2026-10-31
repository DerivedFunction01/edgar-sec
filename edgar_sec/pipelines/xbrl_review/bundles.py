"""Corpus-bundle resolution and loading for XBRL review execution.

A cohort registry names the filings; the fixture source registry in
its corpus root maps each accession to a bundle folder on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.discovery.cohort import (
    SeedFiling,
    canonical_probe_cohort_path,
    canonical_seed_cohort_path,
    canonical_sp100_cohort_path,
    canonical_vintage_cohort_path,
    load_seed_cohort,
)
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    PresentationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.concept_table import CohortEntry
from edgar_sec.engine.xbrl.storage.storage import (
    calculation_arcs_from_arrow_table,
    declarations_from_arrow_table,
    presentation_arcs_from_arrow_table,
    read_declarations_parquet,
)

_FACTS_FILE = "facts.parquet"
_CALC_FILE = "calculation_arcs.parquet"
_PRES_FILE = "presentation_arcs.parquet"
_DECLARATIONS_FILE = "declarations.parquet"
_SOURCE_REGISTRY_FILE = "fixture_source_registry.json"


class BundleNotFoundError(ValueError):
    """A registry accession has no bundle on disk."""


@dataclass(frozen=True, slots=True)
class LoadedFiling:
    """One filing's bundle artefacts loaded as engine inputs."""

    seed: SeedFiling
    bundle_dir: Path
    facts: tuple[XbrlFact, ...]
    calc_arcs: tuple[CalculationArc, ...]
    declarations: dict[str, ConceptDeclaration]
    pres_arcs: tuple[PresentationArc, ...] = ()

    @property
    def accession(self) -> str:
        """Registry accession string for this filing."""
        return str(self.seed.accession)

    @property
    def cohort_entry(self) -> CohortEntry:
        """Cohort-table entry pointing at this filing's facts."""
        return CohortEntry(
            accession=self.accession,
            facts_path=self.bundle_dir / _FACTS_FILE,
            firm=self.seed.firm,
        )


def bundle_root(registry_path: Path) -> Path:
    """Bundle root beside a cohort registry: <name>_cohort.json -> <name>/."""
    return registry_path.parent / registry_path.stem.removesuffix("_cohort")


def _folder_by_accession(registry_path: Path) -> dict[str, str]:
    source_registry = bundle_root(registry_path) / _SOURCE_REGISTRY_FILE
    if not source_registry.is_file():
        raise BundleNotFoundError(
            f"no fixture source registry beside cohort registry {registry_path}"
        )
    payload = json.loads(source_registry.read_text(encoding="utf-8"))
    return {
        str(source["cohort_accession"]): str(source["folder"])
        for source in payload["bundles"]
    }


def _canonical_registry_paths() -> tuple[Path, ...]:
    return (
        canonical_seed_cohort_path(),
        canonical_vintage_cohort_path(),
        canonical_sp100_cohort_path(),
        canonical_probe_cohort_path(),
    )


def corpus_registry_path(source_ref: str | None) -> Path | None:
    """Corpus registry named by a projection source ref, when it is one.

    A corpus registry is a cohort JSON whose bundle root beside it
    holds a fixture source registry; anything else returns None.
    """
    if not source_ref:
        return None
    candidate = Path(source_ref)
    if candidate.suffix != ".json" or not candidate.is_file():
        return None
    source_registry = bundle_root(candidate) / _SOURCE_REGISTRY_FILE
    return candidate if source_registry.is_file() else None


def bundle_dir_for(accession: str, registry_path: Path | None = None) -> Path:
    """Bundle folder for one registry accession; missing is a refusal.

    A registry path restricts resolution to that registry's corpus;
    without one, the canonical corpora are searched in order.
    """
    candidates = (
        (registry_path,) if registry_path is not None else _canonical_registry_paths()
    )
    bundle_dir: Path | None = None
    for candidate in candidates:
        folder = _folder_by_accession(candidate).get(accession)
        if folder is not None:
            bundle_dir = bundle_root(candidate) / folder
            break
    if bundle_dir is None:
        raise BundleNotFoundError(f"no bundle registered for accession {accession}")
    if not (bundle_dir / _FACTS_FILE).is_file():
        raise BundleNotFoundError(
            f"bundle for accession {accession} has no {_FACTS_FILE}: {bundle_dir}"
        )
    return bundle_dir


def registry_filings(
    accessions: list[str] | tuple[str, ...] | None = None,
    registry_path: Path | None = None,
) -> tuple[SeedFiling, ...]:
    """Registry filings, optionally restricted to accessions.

    Defaults to the canonical seed registry; a registry path loads
    the registry the run was projected with instead.
    """
    filings = load_seed_cohort(registry_path or canonical_seed_cohort_path())
    if accessions is None:
        return filings
    wanted = set(accessions)
    return tuple(f for f in filings if str(f.accession) in wanted)


def missing_bundles(
    accessions: list[str], registry_path: Path | None = None
) -> list[str]:
    """Accessions from the list that have no readable bundle."""
    missing: list[str] = []
    for accession in accessions:
        try:
            bundle_dir_for(accession, registry_path)
        except BundleNotFoundError:
            missing.append(accession)
    return missing


def load_filing(seed: SeedFiling, registry_path: Path | None = None) -> LoadedFiling:
    """Load one filing's facts, calculation and presentation arcs, declarations."""
    bundle_dir = bundle_dir_for(str(seed.accession), registry_path)
    fact_rows = pq.read_table(bundle_dir / _FACTS_FILE).to_pylist()
    facts = tuple(
        XbrlFact(
            accession=AccessionNumber.from_any(row["accession"]),
            concept_qname=row["concept_qname"],
            value=(
                row["numeric_value"]
                if row["numeric_value"] is not None
                else row["text_value"]
            ),
            unit=row["unit"],
            decimals=row["decimals"],
            period_type=row["period_type"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            instant_date=row["instant_date"],
            dimensions=json.loads(row["dimensions_json"]),
            context_id=row["context_id"],
        )
        for row in fact_rows
    )
    calc_arcs = calculation_arcs_from_arrow_table(
        pq.read_table(bundle_dir / _CALC_FILE)
    )
    pres_path = bundle_dir / _PRES_FILE
    pres_arcs = (
        presentation_arcs_from_arrow_table(pq.read_table(pres_path))
        if pres_path.is_file()
        else ()
    )
    declarations: dict[str, ConceptDeclaration] = {}
    declarations_path = bundle_dir / _DECLARATIONS_FILE
    if declarations_path.is_file():
        table = read_declarations_parquet(declarations_path)
        declarations = {
            declaration.concept_qname: declaration
            for declaration in declarations_from_arrow_table(table)
        }
    return LoadedFiling(
        seed=seed,
        bundle_dir=bundle_dir,
        facts=facts,
        calc_arcs=calc_arcs,
        declarations=declarations,
        pres_arcs=pres_arcs,
    )


def cohort_entries(
    filings: tuple[SeedFiling, ...], registry_path: Path | None = None
) -> tuple[CohortEntry, ...]:
    """Cohort-table entries for registry filings, in registry order."""
    return tuple(
        CohortEntry(
            accession=str(seed.accession),
            facts_path=bundle_dir_for(str(seed.accession), registry_path) / _FACTS_FILE,
            firm=seed.firm,
        )
        for seed in filings
    )


def registry_row(seed: SeedFiling) -> dict[str, Any]:
    """One registry filing as the plain dict the cohort JSON carries."""
    return {
        "firm": seed.firm,
        "company_name": seed.company_name,
        "cik": str(seed.cik),
        "sic_code": seed.sic_code,
        "sector": seed.sector,
        "fy": seed.fy,
        "form": seed.form,
        "accession": str(seed.accession),
        "sec_filing_url": seed.sec_filing_url,
    }


__all__ = [
    "BundleNotFoundError",
    "LoadedFiling",
    "bundle_dir_for",
    "bundle_root",
    "cohort_entries",
    "corpus_registry_path",
    "load_filing",
    "missing_bundles",
    "registry_filings",
    "registry_row",
]
