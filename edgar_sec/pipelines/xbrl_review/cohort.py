"""Canonical probe cohort registry for XBRL review and evaluation.

The probe cohort is a measurement population for the review and test
planes, not a production discovery input; its registry is homed with
the tools plane that consumes it, under edgar_sec/tools/xbrl_eval.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling, load_seed_cohort
from edgar_sec.foundation.runtime.paths import PACKAGE_ROOT
from edgar_sec.pipelines.xbrl_review.paths import review_corpus_dir

PROBE_COHORT_FILE = "probe_cohort.json"
PROBE_COHORT_HOME = PACKAGE_ROOT / "tools" / "xbrl_eval"


def canonical_probe_cohort_path() -> Path:
    """Path of the canonical probe cohort registry, the form-probe corpus."""
    external = review_corpus_dir() / PROBE_COHORT_FILE
    return external if external.is_file() else PROBE_COHORT_HOME / PROBE_COHORT_FILE


def load_canonical_probe_cohort() -> tuple[SeedFiling, ...]:
    """Load the canonical probe cohort registry."""
    return load_seed_cohort(canonical_probe_cohort_path())


__all__ = [
    "PROBE_COHORT_FILE",
    "PROBE_COHORT_HOME",
    "canonical_probe_cohort_path",
    "load_canonical_probe_cohort",
]
