"""Automated anomaly and signal drift comparator for beneficial ownership runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Structured drift metrics and categorised items between two audit runs."""

    baseline_count: int
    candidate_count: int
    net_change: int
    fixed: tuple[dict[str, Any], ...]
    remaining: tuple[dict[str, Any], ...]
    regressions: tuple[dict[str, Any], ...]
    fixed_by_kind: dict[str, int]
    remaining_by_kind: dict[str, int]
    regressions_by_kind: dict[str, int]
    has_regressions: bool


def _load_data(source: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _extract_items(summary: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = summary.get(key, [])
    if isinstance(items, list):
        return items
    return []


def _item_key(item: dict[str, Any]) -> tuple[str, str, str]:
    accession = str(item.get("accession", ""))
    kind = str(item.get("kind", ""))
    field = str(item.get("field", ""))
    return accession, kind, field


def compare_audit_summaries(
    baseline: dict[str, Any] | str | Path,
    candidate: dict[str, Any] | str | Path,
) -> DriftReport:
    """Compare baseline and candidate run summaries, tracking fixes and regressions."""
    base_data = _load_data(baseline)
    cand_data = _load_data(candidate)

    base_anomalies = _extract_items(base_data, "anomalies")
    cand_anomalies = _extract_items(cand_data, "anomalies")

    base_map = {_item_key(it): it for it in base_anomalies}
    cand_map = {_item_key(it): it for it in cand_anomalies}

    base_keys = set(base_map)
    cand_keys = set(cand_map)

    fixed_keys = sorted(base_keys - cand_keys)
    remaining_keys = sorted(base_keys & cand_keys)
    regression_keys = sorted(cand_keys - base_keys)

    fixed = tuple(base_map[k] for k in fixed_keys)
    remaining = tuple(cand_map[k] for k in remaining_keys)
    regressions = tuple(cand_map[k] for k in regression_keys)

    fixed_counts = Counter(it.get("kind", "") for it in fixed)
    remaining_counts = Counter(it.get("kind", "") for it in remaining)
    regression_counts = Counter(it.get("kind", "") for it in regressions)

    base_count = len(base_anomalies)
    cand_count = len(cand_anomalies)

    return DriftReport(
        baseline_count=base_count,
        candidate_count=cand_count,
        net_change=cand_count - base_count,
        fixed=fixed,
        remaining=remaining,
        regressions=regressions,
        fixed_by_kind=dict(sorted(fixed_counts.items())),
        remaining_by_kind=dict(sorted(remaining_counts.items())),
        regressions_by_kind=dict(sorted(regression_counts.items())),
        has_regressions=bool(regressions),
    )


def format_drift_report(report: DriftReport) -> str:
    """Format drift report metrics and categorized accessions into readable text."""
    lines: list[str] = [
        "Beneficial Ownership Audit Drift Report",
        "========================================",
        f"Baseline Anomalies:  {report.baseline_count}",
        f"Candidate Anomalies: {report.candidate_count}",
        f"Net Change:          {report.net_change:+d}",
        f"Fixed:               {len(report.fixed)}",
        f"Remaining:           {len(report.remaining)}",
        f"Regressions:         {len(report.regressions)}",
    ]

    if report.fixed_by_kind:
        lines.append("\n[FIXED] Anomalies by Kind:")
        for kind, count in report.fixed_by_kind.items():
            lines.append(f"  - {kind}: {count}")

    if report.regressions_by_kind:
        lines.append("\n[REGRESSION] New Anomalies:")
        for it in report.regressions:
            acc = it.get("accession", "")
            kind = it.get("kind", "")
            field = it.get("field", "")
            detail = it.get("detail", "")
            prefix = f"  * {acc} [{kind}]"
            lines.append(f"{prefix} field={field} detail={detail}".strip())

    if report.remaining_by_kind:
        lines.append("\n[REMAINING] Known Anomalies by Kind:")
        for kind, count in report.remaining_by_kind.items():
            lines.append(f"  - {kind}: {count}")

    return "\n".join(lines)


__all__ = [
    "DriftReport",
    "compare_audit_summaries",
    "format_drift_report",
]
