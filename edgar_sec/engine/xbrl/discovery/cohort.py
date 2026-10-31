"""Seed cohort definitions and loaders for XBRL verification."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from edgar_sec.domain.identity import AccessionNumber, Cik


@dataclass(frozen=True, slots=True)
class SeedFiling:
    """One filing record in the XBRL seed cohort."""

    firm: str
    company_name: str
    cik: Cik
    sic_code: int
    sector: str
    fy: int
    form: str
    accession: AccessionNumber
    sec_filing_url: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeedFiling:
        """Instantiate a SeedFiling from raw dictionary values."""
        return cls(
            firm=str(data["firm"]),
            company_name=str(data["company_name"]),
            cik=Cik.from_raw(data["cik"]),
            sic_code=int(data["sic_code"]),
            sector=str(data["sector"]),
            fy=int(data["fy"]),
            form=str(data["form"]),
            accession=AccessionNumber.from_any(data["accession"]),
            sec_filing_url=str(data["sec_filing_url"]),
        )


def load_seed_cohort(source: Path) -> tuple[SeedFiling, ...]:
    """Load and validate seed filing records from an explicit JSON path."""
    payload = json.loads(source.read_text(encoding="utf-8"))
    return tuple(SeedFiling.from_dict(row) for row in payload)


def canonical_seed_cohort_path() -> Path:
    """Path of the canonical seed cohort registry, the single cohort source."""
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "tests" / "fixtures" / "xbrl" / "seed_cohort.json"


def load_canonical_seed_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical seed cohort registry."""
    return load_seed_cohort(canonical_seed_cohort_path())


def canonical_vintage_cohort_path() -> Path:
    """Path of the canonical vintage cohort registry, the measurement corpus."""
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "tests" / "fixtures" / "xbrl" / "vintage_cohort.json"


def load_canonical_vintage_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical vintage cohort registry."""
    return load_seed_cohort(canonical_vintage_cohort_path())


def canonical_sp100_cohort_path() -> Path:
    """Path of the canonical SP100 cohort registry, the scale corpus."""
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "tests" / "fixtures" / "xbrl" / "sp100_cohort.json"


def load_canonical_sp100_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical SP100 cohort registry."""
    return load_seed_cohort(canonical_sp100_cohort_path())


def canonical_probe_cohort_path() -> Path:
    """Path of the canonical probe cohort registry, the form-probe corpus."""
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "tests" / "fixtures" / "xbrl" / "probe_cohort.json"


def load_canonical_probe_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical probe cohort registry."""
    return load_seed_cohort(canonical_probe_cohort_path())


def load_canonical_union_cohort() -> tuple[SeedFiling, ...]:
    """Load all canonical registries: seed, then vintage, then SP100."""
    return (
        load_canonical_seed_cohort()
        + load_canonical_vintage_cohort()
        + load_canonical_sp100_cohort()
    )
