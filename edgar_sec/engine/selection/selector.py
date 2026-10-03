"""Quota selection over a feature snapshot.

Quota profile fill order, in decreasing authority — the order is the design:

* **Seed filers** are mandatory, whatever any quota says.
* **Composite strata** are conjunctions, so they precede single-dimension floors.
* **Single-dimension floors** are chased by relative deficit, feeding the
  dimension proportionally furthest from its floor first.
* **Form-by-era allocation** distributes the remaining quota across those cells.
* **Weighted pool filling** takes the remaining candidates, subject to caps.
* **The reserve** is filled last, from candidates not in the active set.

The property that matters most is the *family cap*. A naive sample is dominated
by large corporate groups, because a group with 400 subsidiaries files 400
documents. Every candidate is keyed by a six-part classification signature and at
most ``max_per_company_classification`` may share one; because every subsidiary
resolves to one ``company_family``, the cap suppresses a group's subsidiaries
without special-casing them. Seed filers bypass it because they are mandatory:
dropping an anchor would violate the policy more than over-representation.
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

# The six dimensions that define a company's filing posture. A cap on this
# tuple is what stops one corporate group filling the sample with its own
# subsidiaries.
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
    """The outcome of one selection run."""

    active_locators: list[str]
    active_candidates: list[dict[str, Any]]
    active_occurrences: list[dict[str, Any]]
    reserve_locators: list[str]
    reserve_candidates: list[dict[str, Any]]
    report: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _CellBudget:
    """One ``(form, era)`` cell's share of the remaining selection budget.

    ``taken`` counts what this phase drew, while ``selected`` counts everything
    the plan holds in the cell including earlier phases. The difference matters:
    a floor that already filled a cell reduces how much is left to allocate there,
    and the report has to say the cell is covered rather than that allocation
    covered it.
    """

    form: str
    era: str
    available: int
    selected: int = 0
    taken: int = 0


def classification_signature(candidate: dict[str, Any]) -> tuple[str, ...]:
    """Return the capped classification tuple for one candidate.

    Falls back to ``company_name`` when no family was resolved, so a candidate
    without clustering still participates in the cap rather than escaping it.
    """
    family = candidate.get("company_family") or candidate.get("company_name")
    return tuple(
        normalize_value(
            candidate.get(dimension) if dimension != "company_family" else family
        )
        for dimension in CLASSIFICATION_DIMENSIONS
    )


class DeficitSelector:
    """Execute policy-driven deficit selection over a feature snapshot."""

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
        """Run the selection stages and return the typed result."""
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

            # A parent selection is part of the effective selection, not a
            # side input: its rows must consume quota, or an expansion would
            # report coverage the published plan does not actually have.
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
        """Fill the remaining budget evenly across nonempty form-by-era cells.

        The weighted fill after this phase is proportional, so the largest form would
        take the leftover budget and a rare one would be represented only as far
        as a declared floor pushed it. Allocating across cells first makes the
        default sample balanced, and a floor stays a *raise* above that balance
        rather than the only thing producing it.

        Availability is read once per run; re-deriving it per cell would cost one
        aggregate scan per cell. The phase's result is reported, so a cell that
        could not fill its share is named rather than quietly replaced.

        The global cap is shared with the earlier phases, so this one draws only
        from what they left, and allocation can underfill when seeds or floors
        already claimed the budget. It stops when a round is refused in full: a
        cell whose every candidate is blocked by the family cap is refused
        identically on every later round, so the honest outcome is a named
        shortfall rather than a spin.
        """
        availability = source.cell_availability()
        budget = max(0, target_units - len(selected_keys))
        if not availability:
            return {"budget": budget, "unallocated": budget, "rounds": 0, "cells": []}

        # What the earlier phases already hold counts toward its cell, so a cell
        # credited by a floor is not then handed a second full share. Keyed on the
        # raw column values rather than the normalized dimension values:
        # ``cell_availability`` reports raw strings and ``pool_for_cell`` binds one
        # straight back into the query, so normalizing on only one side would
        # silently credit nothing.
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
        # Era-first ordering: when the cap is smaller than the cell count, a
        # chronological pass gives every era at least one row before any era
        # takes a second. Form-then-era would instead spend the whole budget on
        # whichever form sorts first.
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
        """Draw up to ``room`` candidates from one cell, respecting the cap.

        ``record`` enforces the family cap, so a cell that is entirely one
        corporate group's filings yields fewer rows than it asked for. That is
        counted as a shortfall rather than backfilled from elsewhere: the
        balance is over distinct filings, and padding a cell with a neighbour's
        rows would defeat it.
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
        """Order eras by their declared band, so allocation walks the calendar.

        Ranked by the band's own start rather than by name: names are ``1999`` or
        ``2003_2006`` and sort correctly only for one width. An era the policy
        did not declare -- ``unknown``, or a band no longer in effect -- sorts
        last, because it is not part of the declared coverage.
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
        """True when admitting ``candidate`` would exceed a declared share cap.

        The cap is a fraction of the *target*, not of the current count, so a
        cap stays meaningful while the selection is still filling up.
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
