"""Deterministic round-robin deficit selection over a feature snapshot.

Policy-driven and stateful: hard floors and composite strata are satisfied
first by rotating through the most deficient dimension values, then remaining
slots are filled by weighted marginal coverage. Every tie is broken by
md5(seed || locator_key) for strict reproducibility.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defs.runtime.resources import derive_resources

from .selection_policy import (
    KNOWN_DIMENSIONS,
    SeedFiler,
    SelectionPolicy,
    normalize_value,
)
from .selection_source import CandidateSource


@dataclass
class SelectionResult:
    active_locators: list[str]
    active_candidates: list[dict[str, Any]]
    active_occurrences: list[dict[str, Any]]
    reserve_locators: list[str]
    reserve_candidates: list[dict[str, Any]]
    report: dict[str, Any]


class DeficitSelector:
    """Execute policy-driven deficit selection over snapshot."""

    def __init__(
        self,
        snapshot_dir: str | Path,
        policy: SelectionPolicy,
        seed_filers: dict[str, SeedFiler] | None = None,
        *,
        threads: int | None = None,
        memory_limit: str | None = None,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir).resolve()
        self.policy = policy
        self.seed_filers = seed_filers or {}
        res = derive_resources()
        self.threads = threads if threads is not None else res.threads
        self.memory_limit = memory_limit or res.memory_limit

    def select(self, parent_active_keys: list[str] | None = None) -> SelectionResult:
        """Run full deficit selection and produce typed SelectionResult."""
        target_units = self.policy.requested_units()
        source = CandidateSource(
            snapshot_dir=self.snapshot_dir,
            seed=self.policy.seed,
            threads=self.threads,
            memory_limit=self.memory_limit,
            page_size=self.policy.page_size,
            max_reported_size=self.policy.max_reported_size,
            exclude_amendments=self.policy.exclude_amendments,
        )

        selected_keys: list[str] = list(parent_active_keys or [])
        selected_candidates: list[dict[str, Any]] = []
        coverage: dict[str, dict[str, int]] = {dim: {} for dim in KNOWN_DIMENSIONS}
        company_classification_counts: Counter[tuple[str, ...]] = Counter()
        deduplicated_company_classifications = 0

        def _classification_signature(cand: dict[str, Any]) -> tuple[str, ...]:
            return (
                normalize_value(cand.get("company_family") or cand.get("company_name")),
                normalize_value(cand.get("form")),
                normalize_value(cand.get("era")),
                normalize_value(cand.get("sic_code")),
                normalize_value(cand.get("entity_type")),
                normalize_value(cand.get("lifecycle_class")),
            )

        def _record(cand: dict[str, Any], *, check_dedup: bool = True) -> bool:
            nonlocal deduplicated_company_classifications
            k = str(cand["document_locator_key"])
            if k in selected_set:
                return False

            sig = _classification_signature(cand)
            if (
                check_dedup
                and self.policy.max_per_company_classification is not None
                and (
                    company_classification_counts[sig]
                    >= self.policy.max_per_company_classification
                )
            ):
                deduplicated_company_classifications += 1
                return False

            selected_set.add(k)
            selected_keys.append(k)
            selected_candidates.append(cand)
            company_classification_counts[sig] += 1
            source.add_selected(k)
            for dim in KNOWN_DIMENSIONS:
                val = normalize_value(cand.get(dim))
                coverage[dim][val] = coverage[dim].get(val, 0) + 1
            return True

        with source.session():
            selected_set = set(selected_keys)
            if len(selected_set) != len(selected_keys):
                raise ValueError("parent selection contains duplicate locator keys")
            source.register_selected(selected_keys)

            # Parent selections are part of the effective selection. Load their
            # feature rows so floors, caps, and company-classification limits
            # apply to the combined parent + expansion set.
            for cand in source.load_candidates_for_locators(selected_keys):
                selected_candidates.append(cand)
                sig = _classification_signature(cand)
                company_classification_counts[sig] += 1
                for dim in KNOWN_DIMENSIONS:
                    val = normalize_value(cand.get(dim))
                    coverage[dim][val] = coverage[dim].get(val, 0) + 1

            # Phase 1: Seed Filers
            if self.seed_filers:
                seed_ciks = list(self.seed_filers.keys())
                for cand in source.pool_for_ciks(seed_ciks, limit_per_cik=5):
                    if len(selected_keys) >= target_units:
                        break
                    _record(cand, check_dedup=False)

            # Phase 2: Composite Strata
            for comp in self.policy.composites:
                filters = comp.get("filters", {})
                req = int(comp.get("min", 1))
                pool = source.pool_for_composite(filters, limit=max(req * 2, 60))
                comp_added = 0
                for cand in pool:
                    if comp_added >= req or len(selected_keys) >= target_units:
                        break
                    if _record(cand):
                        comp_added += 1

            # Phase 3: Single-Dimension Floors
            rounds = 0
            while (
                rounds < self.policy.max_pool_rounds
                and len(selected_keys) < target_units
            ):
                rounds += 1
                deficits: list[tuple[float, str, str, int]] = []
                for dim, reqs in self.policy.floors.items():
                    for val, req in reqs.items():
                        norm_val = normalize_value(val)
                        curr = coverage[dim].get(norm_val, 0)
                        if curr < req:
                            deficit_ratio = (req - curr) / req
                            deficits.append((deficit_ratio, dim, val, req - curr))

                if not deficits:
                    break

                deficits.sort(key=lambda x: -x[0])
                progress_made = False
                for _, dim, val, need in deficits:
                    if len(selected_keys) >= target_units:
                        break
                    pool = source.pool_for_value(
                        dim, val, limit=min(need * 2, self.policy.pool_per_value)
                    )
                    for cand in pool:
                        if _record(cand):
                            progress_made = True
                            break
                if not progress_made:
                    break

            # Phase 4: Weighted Pool Filling
            page_idx = 0
            while (
                len(selected_keys) < target_units and page_idx < self.policy.max_pages
            ):
                page = source.candidate_page(page_idx)
                if not page:
                    break
                page_idx += 1
                for cand in page:
                    if len(selected_keys) >= target_units:
                        break
                    # Check caps
                    violates_cap = False
                    for dim, cap in self.policy.caps.items():
                        val = normalize_value(cand.get(dim))
                        curr = coverage[dim].get(val, 0)
                        if (curr + 1) / target_units > cap:
                            violates_cap = True
                            break
                    if not violates_cap:
                        _record(cand)

            # Phase 5: Reserve Selection
            reserve_keys: list[str] = []
            reserve_candidates: list[dict[str, Any]] = []
            if self.policy.reserve_size > 0:
                res_page_idx = 0
                while (
                    len(reserve_keys) < self.policy.reserve_size and res_page_idx < 100
                ):
                    page = source.candidate_page(res_page_idx)
                    if not page:
                        break
                    res_page_idx += 1
                    for cand in page:
                        if len(reserve_keys) >= self.policy.reserve_size:
                            break
                        k = str(cand["document_locator_key"])
                        if k not in selected_set and k not in reserve_keys:
                            reserve_keys.append(k)
                            reserve_candidates.append(cand)
                            source.add_selected(k)

            # Materialize Active Occurrences
            active_occurrences = source.load_occurrences_for_locators(selected_keys)

        # Build Coverage & Validation Report
        underfilled_floors: dict[str, dict[str, dict[str, int]]] = {}
        for dim, reqs in self.policy.floors.items():
            for val, req in reqs.items():
                norm_val = normalize_value(val)
                actual = coverage[dim].get(norm_val, 0)
                if actual < req:
                    underfilled_floors.setdefault(dim, {})[val] = {
                        "required": req,
                        "selected": actual,
                        "deficit": req - actual,
                    }

        report = {
            "policy_fingerprint": self.policy.policy_fingerprint,
            "corpus_id": self.policy.corpus_id,
            "level": self.policy.level,
            "target_units": target_units,
            "active_locators_count": len(selected_keys),
            "active_occurrences_count": len(active_occurrences),
            "reserve_locators_count": len(reserve_keys),
            "deduplicated_company_classifications": deduplicated_company_classifications,
            "unique_company_families": len(
                {sig[0] for sig in company_classification_counts if sig[0] != "none"}
            ),
            "underfilled_floors": underfilled_floors,
            "coverage_distributions": {
                dim: counts for dim, counts in coverage.items() if counts
            },
        }

        return SelectionResult(
            active_locators=selected_keys,
            active_candidates=selected_candidates,
            active_occurrences=active_occurrences,
            reserve_locators=reserve_keys,
            reserve_candidates=reserve_candidates,
            report=report,
        )


__all__ = [
    "CandidateSource",
    "DeficitSelector",
    "SelectionResult",
    "normalize_value",
]
