"""Plan-derived candidate counts for one chunk.

Pure computation over locators and catalog occurrences: no network fetch, no
checkpoint read. This is what a skipped or resumed chunk reports so its summary
matches what a fresh run would produce.
"""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.pipelines.document_storage.occurrences import (
    _filing_work,
    _occurrences_by_key,
    _unique_locators,
)
from edgar_sec.pipelines.document_storage.work_order import (
    DocumentLocator,
    FilingOccurrence,
)


def candidate_summary(
    locators: Sequence[DocumentLocator],
    occurrences: Sequence[FilingOccurrence],
) -> tuple[int, int, int]:
    """Return ``(window_eligible, bundle_candidate, unresolved_date)`` over one chunk.

    Derived from the plan's own inputs rather than from a checkpoint, so a resumed chunk
    reports what a fresh one would; co-filer occurrences count on their shared locator once.
    """
    by_key = _occurrences_by_key(occurrences)
    eligible = 0
    candidates = 0
    unresolved = 0
    for work in (_filing_work(loc, by_key) for loc in _unique_locators(locators)):
        eligible += int(work.candidate.window_eligible)
        candidates += int(work.candidate.is_bundle_candidate)
        unresolved += int(work.filing_date is None)
    return eligible, candidates, unresolved


__all__ = ["candidate_summary"]
