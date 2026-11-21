"""Batch streaming contract for per-filing facade work.

A run yields one outcome per filing as it resolves: at most one facade
is live per worker, the runner accumulates nothing, and a filing's
failure — even its worker's death — is a named error, never a lost run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Generic, TypeVar

from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import derive_resources

U = TypeVar("U")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class FilingOutcome(Generic[U, T]):
    """One filing's batch result: a value, or the named error that failed it."""

    unit: U
    value: T | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the filing produced a value."""
        return self.error is None


def named_error(exc: BaseException) -> str:
    """The stable 'TypeName: message' form a failed filing is recorded under."""
    return f"{type(exc).__name__}: {exc}"


def _run_one(work: Callable[[U], T], unit: U) -> T:
    """Run one filing's work, then release this process's freed arenas."""
    try:
        return work(unit)
    finally:
        reclaim()


def stream_filing_outcomes(
    units: Sequence[U],
    work: Callable[[U], T],
    *,
    workers: int | None = None,
) -> Iterator[FilingOutcome[U, T]]:
    """Yield one outcome per unit under the batch streaming contract.

    `work` maps one unit to a small picklable result; a facade it builds
    stays inside the call. Failures yield error outcomes, never abort.
    """
    width = workers if workers is not None else derive_resources().workers
    if width <= 1 or len(units) <= 1:
        yield from _sequential_outcomes(units, work)
    else:
        yield from _pool_outcomes(units, work, width)


def _sequential_outcomes(
    units: Sequence[U], work: Callable[[U], T]
) -> Iterator[FilingOutcome[U, T]]:
    for unit in units:
        try:
            value = _run_one(work, unit)
        except Exception as exc:
            yield FilingOutcome(unit=unit, error=named_error(exc))
        else:
            yield FilingOutcome(unit=unit, value=value)


def _pool_outcomes(
    units: Sequence[U], work: Callable[[U], T], width: int
) -> Iterator[FilingOutcome[U, T]]:
    total = len(units)
    next_index = 0
    in_flight: dict[Future[T], int] = {}
    while next_index < total or in_flight:
        submitted = 0
        pool_error: BrokenProcessPool | None = None
        with ProcessPoolExecutor(max_workers=width) as pool:
            while next_index < total or in_flight:
                while (
                    next_index < total and len(in_flight) < width and pool_error is None
                ):
                    try:
                        future = pool.submit(_run_one, work, units[next_index])
                    except BrokenProcessPool as exc:
                        pool_error = exc
                        break
                    in_flight[future] = next_index
                    next_index += 1
                    submitted += 1
                if pool_error is not None or not in_flight:
                    break
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    index = in_flight.pop(future)
                    try:
                        value = future.result()
                    except BrokenProcessPool as exc:
                        pool_error = exc
                        yield FilingOutcome(unit=units[index], error=named_error(exc))
                        break
                    except Exception as exc:
                        yield FilingOutcome(unit=units[index], error=named_error(exc))
                    else:
                        yield FilingOutcome(unit=units[index], value=value)
                if pool_error is not None:
                    break
        if pool_error is not None:
            error = named_error(pool_error)
            for index in in_flight.values():
                yield FilingOutcome(unit=units[index], error=error)
            in_flight.clear()
            if submitted == 0:
                # Workers die at startup in every pool; no filing can run.
                for index in range(next_index, total):
                    yield FilingOutcome(unit=units[index], error=error)
                return


__all__ = [
    "FilingOutcome",
    "named_error",
    "stream_filing_outcomes",
]
