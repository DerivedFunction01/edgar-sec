"""Canonical probe cohort registry for XBRL review and evaluation.

The probe cohort is a measurement population for the review and test
planes, not a production discovery input; its registry resolves through
the review paths seam, this package's fixtures as the fallback.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling, load_seed_cohort
from edgar_sec.pipelines.xbrl_review.paths import FIXTURES_DIR, review_corpus_dir

PROBE_COHORT_FILE = "probe_cohort.json"


def canonical_probe_cohort_path() -> Path:
    """Path of the canonical probe cohort registry, the form-probe corpus."""
    external = review_corpus_dir() / PROBE_COHORT_FILE
    return external if external.is_file() else FIXTURES_DIR / PROBE_COHORT_FILE


def load_canonical_probe_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical probe cohort registry."""
    return load_seed_cohort(canonical_probe_cohort_path())


__all__ = [
    "PROBE_COHORT_FILE",
    "canonical_probe_cohort_path",
    "load_canonical_probe_cohort",
]
