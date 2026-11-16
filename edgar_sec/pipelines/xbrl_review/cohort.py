"""Canonical probe cohort registry for XBRL review and evaluation.

The probe cohort is a measurement population for the review and test
planes, not a production discovery input; its registry and bundle
corpus live in this package's fixtures, beside their consumers.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling, load_seed_cohort
from edgar_sec.pipelines.xbrl_review.paths import FIXTURES_DIR

PROBE_COHORT_FILE = "probe_cohort.json"


def canonical_probe_cohort_path() -> Path:
    """Path of the canonical probe cohort registry, the form-probe corpus."""
    return FIXTURES_DIR / PROBE_COHORT_FILE


def load_canonical_probe_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical probe cohort registry."""
    return load_seed_cohort(canonical_probe_cohort_path())


__all__ = [
    "PROBE_COHORT_FILE",
    "canonical_probe_cohort_path",
    "load_canonical_probe_cohort",
]
