"""Seeded answerability battery: facts the engine must answer correctly.

Companion to benchmark.py's pair set and relations.py's longitudinal
set. Every entry's expected value was verified against its filing —
by fact name and extracted facts, otherwise against rendered text.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope

from edgar_sec.engine.xbrl.review.battery_entries import (
    BatteryEntry,
)
from edgar_sec.engine.xbrl.review.battery_entries import (
    BATTERY_SET as _CORE_SET,
)
from edgar_sec.engine.xbrl.review.battery_entries_panel import PANEL_SET

BATTERY_SET: tuple[BatteryEntry, ...] = _CORE_SET + PANEL_SET


@dataclass(frozen=True, slots=True)
class BatteryResult:
    """One battery entry's live outcome."""

    entry_id: str
    tier: str
    firm: str
    qname: str
    passed: bool
    actual_status: str
    actual_value: float | None


@dataclass(frozen=True, slots=True)
class BatteryReport:
    """Gate outcome for the answerability battery."""

    total: int
    passed: int
    failures: tuple[str, ...]
    results: tuple[BatteryResult, ...]

    @property
    def passed_all(self) -> bool:
        """True when every battery entry answers at its verified value."""
        return not self.failures


def evaluate_battery(
    engine: Any,
    endpoints: Mapping[str, tuple[Sequence[XbrlFact], Sequence[Any]]],
    entries: tuple[BatteryEntry, ...] = BATTERY_SET,
) -> BatteryReport:
    """Evaluate battery entries through the query engine, per accession.

    An entry passes when the engine answers at its expected status and
    its verified value under the entry's own scope.
    """
    failures: list[str] = []
    results: list[BatteryResult] = []
    passed = 0
    for entry in entries:
        label = f"{entry.entry_id} ({entry.firm} {entry.qname})"
        endpoint = endpoints.get(entry.accession)
        if endpoint is None:
            failures.append(f"{label}: no endpoint facts for {entry.accession}")
            results.append(
                BatteryResult(
                    entry.entry_id,
                    entry.tier,
                    entry.firm,
                    entry.qname,
                    False,
                    "NO_ENDPOINT",
                    None,
                )
            )
            continue
        facts, arcs = endpoint
        scope = FactScope(
            accession=entry.accession,
            unit=entry.unit,
            instant_date=entry.instant or None,
            start_date=entry.start or None,
            end_date=entry.end or None,
            dimensions=dict(entry.dimensions),
        )
        result = engine.execute(
            FinancialQuery(entry.qname, scope, QueryMode(entry.mode)),
            facts,
            arcs,
        )
        ok = (
            result.status == QueryStatus(entry.expected_status)
            and result.value == entry.expected_value
        )
        if ok:
            passed += 1
        else:
            failures.append(
                f"{label}: expected {entry.expected_status} "
                f"{entry.expected_value}, got {result.status} {result.value}"
            )
        results.append(
            BatteryResult(
                entry.entry_id,
                entry.tier,
                entry.firm,
                entry.qname,
                ok,
                str(result.status),
                result.value,
            )
        )
    return BatteryReport(
        total=len(entries),
        passed=passed,
        failures=tuple(failures),
        results=tuple(results),
    )


__all__ = [
    "BASIC",
    "BATTERY_SET",
    "COMPLEX",
    "TEXTBOOK",
    "BatteryEntry",
    "BatteryReport",
    "BatteryResult",
    "evaluate_battery",
]
