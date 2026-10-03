"""Quota selection over a feature snapshot. Fill order, decreasing authority: seeds,
composite strata, floors by deficit, form-by-era allocation, weighted pool,
reserve. At most `max_per_company_classification` candidates share a signature.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from edgar_sec.engine.selection.policy import (
    KNOWN_DIMENSIONS,
    SeedFiler,
    SelectionPolicy,
    normalize_value,
)
from edgar_sec.engine.selection.source import CandidateFilters, CandidateSource

# The six dimensions defining a company's filing posture. Capping this tuple is
# what stops one corporate group filling the sample with its own subsidiaries.
CLASSIFICATION_DIMENSIONS = (
    "company_family",
    "form",
    "era",
    "sic_code",
    "entity_type",
    "lifecycle_class",
)

# Keep the reserve scan bound named and adjustable rather than burying it in the
# loop condition.
DEFAULT_RESERVE_MAX_PAGES = 100


@dataclass(frozen=True, slots=True)
class SelectionResult:
    active_locators: list[str]
    active_candidates: list[dict[str, Any]]
    active_occurrences: list[dict[str, Any]]
    reserve_locators: list[str]
    reserve_candidates: list[dict[str, Any]]
    report: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _CellBudget:
    """One `(form, era)` cell's share of the budget: `taken` is what this phase drew,
    `selected` all the plan holds, so a filled cell gets a smaller share.
    """

    form: str
    era: str
    available: int
    selected: int = 0
    taken: int = 0


def classification_signature(candidate: dict[str, Any]) -> tuple[str, ...]:
    """The capped classification tuple; falls back to `company_name` when no family
    resolved, so an unclustered candidate cannot escape the cap.
    """
    family = candidate.get("company_family") or candidate.get("company_name")
    return tuple(
        normalize_value(
            candidate.get(dimension) if dimension != "company_family" else family
        )
        for dimension in CLASSIFICATION_DIMENSIONS
    )


class DeficitSelector:
    def __init__(
        self,
        snapshot_dir: str | Path,
        policy: SelectionPolicy,
        seed_filers: dict[str, SeedFiler] | None = None,
        *,
        page_size: int | None = None,
        threads: int | None = None,
        memory_limit: str | None = None,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir).resolve()
        self.policy = policy
        self.seed_filers = dict(seed_filers or {})
        self.page_size = page_size or policy.page_size
        self._threads = threads
        self._memory_limit = memory_limit

    def select(self, parent_active_keys: list[str] | None = None) -> SelectionResult:
        target_units = self.policy.requested_units()
        source = CandidateSource(
            self.snapshot_dir,
            self.policy.seed,
            page_size=self.page_size,
            filters=CandidateFilters(
                document_suffixes=tuple(self.policy.document_suffixes),
                max_reported_size=self.policy.max_reported_size,
                date_selection=self.policy.date_selection_clauses,
            ),
            threads=self._threads,
            memory_limit=self._memory_limit,
        )

        selected_keys: list[str] = list(parent_active_keys or [])
        selected_set: set[str] = set(selected_keys)
        if len(selected_set) != len(selected_keys):
            raise ValueError("parent selection contains duplicate locator keys")
        selected_candidates: list[dict[str, Any]] = []
        coverage: dict[str, dict[str, int]] = {dim: {} for dim in KNOWN_DIMENSIONS}
        signature_counts: Counter[tuple[str, ...]] = Counter()
        deduplicated_signatures = 0

        def _account(candidate: dict[str, Any]) -> None:
            """Add one already-accepted candidate to the coverage tallies."""
            selected_candidates.append(candidate)
            signature_counts[classification_signature(candidate)] += 1
            for dimension in KNOWN_DIMENSIONS:
                value = normalize_value(candidate.get(dimension))
                coverage[dimension][value] = coverage[dimension].get(value, 0) + 1

        def _record(candidate: dict[str, Any], *, check_cap: bool = True) -> bool:
            """Accept a candidate unless it is already selected or over its cap."""
            nonlocal deduplicated_signatures
            key = str(candidate["document_locator_key"])
            if key in selected_set:
                return False
            signature = classification_signature(candidate)
            if (
                check_cap
                and self.policy.max_per_company_classification is not None
                and signature_counts[signature]
                >= self.policy.max_per_company_classification
            ):
                deduplicated_signatures += 1
                return False
            selected_set.add(key)
            selected_keys.append(key)
            source.add_selected(key)
            _account(candidate)
            return True

        with source.session():
            source.register_selected(selected_keys)

            # A parent selection is part of the effective selection, not a side
            # input: its rows must consume quota or an expansion reports
            # coverage the published plan does not have.
            for candidate in source.load_candidates_for_locators(selected_keys):
                _account(candidate)

            self._select_seed_filers(source, _record, selected_keys, target_units)
            self._select_composites(source, _record, selected_keys, target_units)
            self._select_floors(source, _record, selected_keys, target_units, coverage)
            allocation = self._allocate_form_era_cells(
                source,
                _record,
                selected_keys,
                selected_candidates,
                target_units,
            )
            self._fill_weighted(source, _record, selected_keys, target_units, coverage)

            reserve_keys, reserve_candidates = self._select_reserve(
                source, selected_set
            )
            active_occurrences = source.load_occurrences_for_locators(selected_keys)

        return SelectionResult(
            active_locators=selected_keys,
            active_candidates=selected_candidates,
            active_occurrences=active_occurrences,
            reserve_locators=reserve_keys,
            reserve_candidates=reserve_candidates,
            report=self._build_report(
                target_units=target_units,
                selected_keys=selected_keys,
                active_occurrences=active_occurrences,
                reserve_keys=reserve_keys,
                deduplicated_signatures=deduplicated_signatures,
                signature_counts=signature_counts,
                coverage=coverage,
                allocation=allocation,
            ),
        )

    # -------------------------------------------------------------- phases

    def _select_seed_filers(
        self,
        source: CandidateSource,
        record: Any,
        selected_keys: list[str],
        target_units: int,
    ) -> None:
        if not self.seed_filers:
            return
        for candidate in source.pool_for_ciks(list(self.seed_filers), limit_per_cik=5):
            if len(selected_keys) >= target_units:
                break
            # Seeds bypass the family cap: dropping an anchor violates the
            # policy more than over-representation does.
            record(candidate, check_cap=False)

    def _select_composites(
        self,
        source: CandidateSource,
        record: Any,
        selected_keys: list[str],
        target_units: int,
    ) -> None:
        for composite in self.policy.composites:
            required = int(composite.get("min", 1))
            pool = source.pool_for_composite(
                composite.get("filters", {}), limit=max(required * 2, 60)
            )
            added = 0
            for candidate in pool:
                if added >= required or len(selected_keys) >= target_units:
                    break
                if record(candidate):
                    added += 1

    def _select_floors(
        self,
        source: CandidateSource,
        record: Any,
        selected_keys: list[str],
        target_units: int,
        coverage: dict[str, dict[str, int]],
    ) -> None:
        """Chase floors by relative deficit until no floor moves."""
        for round_index in range(self.policy.max_pool_rounds):
            if len(selected_keys) >= target_units:
                return
            deficits = self._deficits(coverage)
            if not deficits:
                return
            progressed = False
            for _ratio, dimension, value, needed in deficits:
                if len(selected_keys) >= target_units:
                    break
                pool = source.pool_for_value(
                    dimension,
                    value,
                    limit=min(needed * 2, self.policy.pool_per_value),
                )
                for candidate in pool:
                    if record(candidate):
                        progressed = True
                        break
            if not progressed:
                # Every remaining deficit has an exhausted pool. Further rounds
                # would re-query the same empty pools forever.
                return

    def _deficits(
        self, coverage: dict[str, dict[str, int]]
    ) -> list[tuple[float, str, str, int]]:
        """Return unfilled floors, most proportionally deficient first."""
        deficits: list[tuple[float, str, str, int]] = []
        for dimension, requirements in self.policy.floors.items():
            for value, required in requirements.items():
                if required <= 0:
                    continue
                filled = coverage[dimension].get(normalize_value(value), 0)
                if filled < required:
                    deficits.append(
                        (
                            (required - filled) / required,
                            dimension,
                            value,
                            required - filled,
                        )
                    )
        deficits.sort(key=lambda item: -item[0])
        return deficits

    def _allocate_form_era_cells(
        self,
        source: CandidateSource,
        record: Any,
        selected_keys: list[str],
        selected_candidates: list[dict[str, Any]],
        target_units: int,
    ) -> dict[str, Any]:
        """Fill the remaining budget evenly across nonempty form-by-era cells. Preceding
        the proportional weighted fill makes a floor a raise above balance.
        """
        availability = source.cell_availability()
        budget = max(0, target_units - len(selected_keys))
        if not availability:
            return {"budget": budget, "unallocated": budget, "rounds": 0, "cells": []}

        # What earlier phases hold counts toward its cell, so a floor-credited cell
        # is not handed a second full share. Keyed on raw column values:
        # cell_availability reports raw and pool_for_cell binds them back as-is.
        already: dict[tuple[str, str], int] = {}
        for candidate in selected_candidates:
            cell_key = (str(candidate.get("form")), str(candidate.get("era")))
            already[cell_key] = already.get(cell_key, 0) + 1

        cells = [
            _CellBudget(
                form=form,
                era=era,
                available=count,
                selected=already.get((form, era), 0),
            )
            for form, era, count in availability
        ]
        # Era-first: when the cap is smaller than the cell count, a chronological
        # pass gives every era a row before any takes a second; form-then-era
        # would spend the whole budget on whichever form sorts first.
        cells.sort(key=lambda cell: (self._era_rank(cell.era), cell.form, cell.era))

        remaining = budget
        rounds = 0
        while remaining > 0:
            open_cells = [cell for cell in cells if cell.taken < cell.available]
            if not open_cells:
                break
            rounds += 1
            added_this_round = 0
            share = max(1, remaining // len(open_cells))
            for cell in open_cells:
                if remaining <= 0:
                    break
                room = min(cell.available - cell.taken, remaining, share)
                if room <= 0:
                    continue
                added = self._fill_cell(source, record, cell, room)
                cell.taken += added
                cell.selected += added
                remaining -= added
                added_this_round += added
            if added_this_round == 0:
                # Every open cell was refused, which here means the family cap:
                # the rows exist but cannot be admitted without collapsing the
                # sample onto one classification. Another round would re-query
                # the same cells and be refused identically.
                break

        quota = max(1, budget // len(cells)) if cells else 0
        return {
            "budget": budget,
            "unallocated": remaining,
            "rounds": rounds,
            "equal_quota": quota,
            "cells": [
                {
                    "form": cell.form,
                    "era": cell.era,
                    "available": cell.available,
                    "selected": cell.selected,
                    "shortfall": max(0, quota - cell.selected),
                }
                for cell in cells
            ],
        }

    def _fill_cell(
        self,
        source: CandidateSource,
        record: Any,
        cell: _CellBudget,
        room: int,
    ) -> int:
        """Draw up to `room` candidates from one cell. A cell of one group's filings yields
        fewer rows than asked, counted as a shortfall rather than padded.
        """
        pool = source.pool_for_cell(cell.form, cell.era, limit=room)
        added = 0
        for candidate in pool:
            if added >= room:
                break
            if record(candidate):
                added += 1
        return added

    def _era_rank(self, era: str) -> tuple[int, int]:
        """Order eras by declared band, so allocation walks the calendar. Ranked by band
        start, not name; an undeclared era sorts last, outside the coverage.
        """
        for rank, band in enumerate(self.policy.era_bands):
            if band.name == era:
                return (rank, 0)
        return (len(self.policy.era_bands), 1)

    def _fill_weighted(
        self,
        source: CandidateSource,
        record: Any,
        selected_keys: list[str],
        target_units: int,
        coverage: dict[str, dict[str, int]],
    ) -> None:
        for page_index in range(self.policy.max_pages):
            if len(selected_keys) >= target_units:
                return
            page = source.candidate_page(page_index)
            if not page:
                return
            for candidate in page:
                if len(selected_keys) >= target_units:
                    break
                if not self._violates_cap(candidate, coverage, target_units):
                    record(candidate)

    def _violates_cap(
        self,
        candidate: dict[str, Any],
        coverage: dict[str, dict[str, int]],
        target_units: int,
    ) -> bool:
        """Whether admitting `candidate` would exceed a declared share cap. The cap is a
        fraction of the *target*, so it stays meaningful while selection fills.
        """
        for dimension, cap in self.policy.caps.items():
            value = normalize_value(candidate.get(dimension))
            filled = coverage[dimension].get(value, 0)
            if (filled + 1) / target_units > cap:
                return True
        return False

    def _select_reserve(
        self, source: CandidateSource, selected_set: set[str]
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Fill the reserve from candidates outside the active set."""
        if self.policy.reserve_size <= 0:
            return [], []
        reserve_keys: list[str] = []
        reserve_candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page_index in range(DEFAULT_RESERVE_MAX_PAGES):
            if len(reserve_keys) >= self.policy.reserve_size:
                break
            page = source.candidate_page(page_index)
            if not page:
                break
            for candidate in page:
                if len(reserve_keys) >= self.policy.reserve_size:
                    break
                key = str(candidate["document_locator_key"])
                if key in selected_set or key in seen:
                    continue
                seen.add(key)
                reserve_keys.append(key)
                reserve_candidates.append(candidate)
                # Excluded from later pool queries so a reserve row cannot also
                # be admitted to the active set by a subsequent phase.
                source.add_selected(key)
        return reserve_keys, reserve_candidates

    # -------------------------------------------------------------- report

    def _build_report(
        self,
        *,
        target_units: int,
        selected_keys: list[str],
        active_occurrences: list[dict[str, Any]],
        reserve_keys: list[str],
        deduplicated_signatures: int,
        signature_counts: Counter[tuple[str, ...]],
        coverage: dict[str, dict[str, int]],
        allocation: dict[str, Any],
    ) -> dict[str, Any]:
        underfilled: dict[str, dict[str, dict[str, int]]] = {}
        for dimension, requirements in self.policy.floors.items():
            for value, required in requirements.items():
                filled = coverage[dimension].get(normalize_value(value), 0)
                if filled < required:
                    underfilled.setdefault(dimension, {})[value] = {
                        "required": required,
                        "selected": filled,
                        "deficit": required - filled,
                    }
        allocation_cells = allocation.get("cells") or []
        return {
            "policy_fingerprint": self.policy.policy_fingerprint,
            "corpus_id": self.policy.corpus_id,
            "level": self.policy.level,
            "target_units": target_units,
            "active_locators_count": len(selected_keys),
            "active_occurrences_count": len(active_occurrences),
            "reserve_locators_count": len(reserve_keys),
            "deduplicated_company_classifications": deduplicated_signatures,
            "unique_company_families": len(
                {
                    signature[0]
                    for signature in signature_counts
                    if signature[0] != "none"
                }
            ),
            "underfilled_floors": underfilled,
            "era_band_count": len(self.policy.era_bands),
            "derives_era_bands": self.policy.derives_era_bands,
            "date_selection": list(self.policy.date_selection),
            "date_selection_text": self.policy.date_selection_text,
            "form_era_allocation": {
                "budget": allocation.get("budget", 0),
                "equal_quota": allocation.get("equal_quota", 0),
                "rounds": allocation.get("rounds", 0),
                "unallocated": allocation.get("unallocated", 0),
                "cell_count": len(allocation_cells),
                "underfilled_cells": sum(
                    1 for cell in allocation_cells if cell["shortfall"] > 0
                ),
                "cells": allocation_cells,
            },
            "coverage_distributions": {
                dimension: counts for dimension, counts in coverage.items() if counts
            },
        }


__all__ = [
    "CLASSIFICATION_DIMENSIONS",
    "DEFAULT_RESERVE_MAX_PAGES",
    "DeficitSelector",
    "SelectionResult",
    "classification_signature",
]
