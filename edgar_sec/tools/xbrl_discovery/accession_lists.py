"""Tracked accession lists: the source inputs corpus regeneration reads.

Each JSON file carries the cohort registry rows (the SeedFiling schema)
for one corpus; the bundles themselves are regenerated, never tracked.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling, load_seed_cohort

_LISTS_DIR = Path(__file__).resolve().parent / "accession_lists"
CORPUS_NAMES = ("seed", "vintage", "sp100")


def accession_list_path(corpus: str) -> Path:
    """Path of one corpus's tracked accession list."""
    if corpus not in CORPUS_NAMES:
        raise ValueError(f"unknown corpus {corpus!r}; expected one of {CORPUS_NAMES}")
    return _LISTS_DIR / f"{corpus}.json"


def load_accession_list(corpus: str) -> tuple[SeedFiling, ...]:
    """Load one corpus's accession list as cohort filings."""
    return load_seed_cohort(accession_list_path(corpus))
