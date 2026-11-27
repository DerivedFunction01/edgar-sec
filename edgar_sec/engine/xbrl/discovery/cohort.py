"""Seed cohort definitions and loaders for XBRL verification."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.runtime.paths import dataset_root, resolve_paths
from edgar_sec.foundation.runtime.settings import resolve_settings

# The in-repo discovery directory is the migration fallback: the canonical
# registries and their bundle corpora live beside this module until Step 8.
DISCOVERY_DIR = Path(__file__).resolve().parent
SEED_COHORT_FILE = "seed_cohort.json"
VINTAGE_COHORT_FILE = "vintage_cohort.json"
SP100_COHORT_FILE = "sp100_cohort.json"

XBRL_DATASET = "xbrl"
CORPUS_DIR = "corpus"


def corpus_root() -> Path:
    """Corpus root: the ``xbrl.corpus_root`` override when set, else the
    artifacts-root convention ``<artifacts_root>/xbrl/corpus``.
    """
    configured = resolve_settings().get("xbrl.corpus_root", "")
    text = str(configured).strip() if configured is not None else ""
    if text:
        return Path(text)
    return dataset_root(resolve_paths().artifacts_root, XBRL_DATASET) / CORPUS_DIR


def _canonical_registry_path(file_name: str) -> Path:
    """One canonical registry path: corpus root first, in-repo fallback.

    The corpus-root candidate is used only when the registry file is
    there; the in-repo registry is the migration fallback until Step 8.
    """
    external = corpus_root() / file_name
    return external if external.is_file() else DISCOVERY_DIR / file_name


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
    return _canonical_registry_path(SEED_COHORT_FILE)


def load_canonical_seed_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical seed cohort registry."""
    return load_seed_cohort(canonical_seed_cohort_path())


def canonical_vintage_cohort_path() -> Path:
    """Path of the canonical vintage cohort registry, the measurement corpus."""
    return _canonical_registry_path(VINTAGE_COHORT_FILE)


def load_canonical_vintage_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical vintage cohort registry."""
    return load_seed_cohort(canonical_vintage_cohort_path())


def canonical_sp100_cohort_path() -> Path:
    """Path of the canonical SP100 cohort registry, the scale corpus."""
    return _canonical_registry_path(SP100_COHORT_FILE)


def load_canonical_sp100_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical SP100 cohort registry."""
    return load_seed_cohort(canonical_sp100_cohort_path())


def load_canonical_union_cohort() -> tuple[SeedFiling, ...]:
    """Load all canonical registries: seed, then vintage, then SP100."""
    return (
        load_canonical_seed_cohort()
        + load_canonical_vintage_cohort()
        + load_canonical_sp100_cohort()
    )
