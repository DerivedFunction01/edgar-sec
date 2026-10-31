from __future__ import annotations

from typing import Any

from .policy import SelectionPolicy
from .source import CandidateSource


def floor_batch_size(
    required: int, current: int, rounds_remaining: int, budget_remaining: int
) -> int:
    if rounds_remaining <= 0 or budget_remaining <= 0:
        return 0
    needed = max(0, required - current)
    return min((needed + rounds_remaining - 1) // rounds_remaining, budget_remaining)


def select_floors(
    selector: Any,
    source: CandidateSource,
    con: Any,
    active_count: int,
    target_units: int,
    policy: SelectionPolicy,
) -> tuple[int, int]:
    from .selector import CLASSIFICATION_DIMENSIONS

    deduplicated = 0
    source.stage_floor_candidates(
        policy.floors,
        CLASSIFICATION_DIMENSIONS,
        policy.max_per_company_classification,
        target_units,
    )
    for round_index in range(policy.max_pool_rounds):
        if active_count >= target_units:
            return active_count, deduplicated
        deficits = selector._deficits(con)
        if not deficits:
            return active_count, deduplicated
        progressed = False
        rounds_remaining = policy.max_pool_rounds - round_index
        for _, dimension, value, _ in deficits:
            if active_count >= target_units:
                break
            required = int(policy.floors[dimension][value])
            current = selector._coverage_count(con, dimension, value)
            batch_size = floor_batch_size(
                required, current, rounds_remaining, target_units - active_count
            )
            while batch_size > 0:
                batch = list(
                    source.pool_for_staged_floor(
                        dimension,
                        value,
                        min(batch_size, policy.pool_per_value),
                        CLASSIFICATION_DIMENSIONS,
                        policy.max_per_company_classification,
                    )
                )
                if not batch:
                    break
                added_in_batch = 0
                for candidate in batch:
                    if selector._coverage_count(con, dimension, value) >= required:
                        break
                    recorded, capped = selector._record(source, con, candidate)
                    deduplicated += int(capped)
                    if recorded:
                        active_count += 1
                        added_in_batch += 1
                        progressed = True
                        if active_count >= target_units:
                            break
                batch_size -= added_in_batch
                if added_in_batch == 0:
                    break
            if active_count >= target_units:
                break
        if not progressed:
            return active_count, deduplicated
    return active_count, deduplicated
