"""Registration statement review analysis and scorecard aggregation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.registration.taxonomy import FORM_S1_ITEMS
from edgar_sec.engine.forms.cover.boundary.detector import (
    find_cover_boundary_for_profile,
)
from edgar_sec.engine.forms.cover.checkmarks.solver import (
    infer_cover_checkmarks,
)
from edgar_sec.engine.forms.cover.models import BoundaryInput
from edgar_sec.engine.forms.cover.profiles import get_profile

_MIN_COVER_LINES = 5
_MAX_COVER_LINES = 500
_HIGH_CONFIDENCE_THRESHOLD = 0.8
_MEDIUM_CONFIDENCE_THRESHOLD = 0.5


def _locate_text_artifact(case_dir: Path) -> Path | None:
    ops_dir = case_dir / "operations"
    if not ops_dir.is_dir():
        return None
    preferred = ops_dir / "render_to_txt.txt"
    if preferred.is_file():
        return preferred
    for candidate in ops_dir.glob("*.txt"):
        if candidate.is_file():
            return candidate
    raw_path = ops_dir / "raw"
    if raw_path.is_file():
        return raw_path
    return None


def analyze_registration_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single Form S-1 review case directory producing diagnostics."""
    text_path = _locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    accession = str(record.get("accession", case_dir.name))
    form = str(record.get("form", "S-1"))
    profile = get_profile("S-1")

    boundary = find_cover_boundary_for_profile(
        BoundaryInput(text, representation="text"),
        profile,
    )
    cm_result = infer_cover_checkmarks(
        text,
        boundary,
        family=profile.family,
        schema=profile.checkbox_schema,
    )

    lines = text.splitlines()
    body_lines = lines[boundary.end_line :]
    body_text_sample = "\n".join(body_lines[:500]).lower()

    detected_items: list[str] = []
    for item_def in FORM_S1_ITEMS:
        for name in item_def.names:
            if name in body_text_sample:
                detected_items.append(item_def.item)
                break

    anomalies: list[dict[str, Any]] = []
    start = boundary.start_line or 0
    end = boundary.end_line or 0
    cover_lines = max(0, end - start)

    if boundary.confidence < _MEDIUM_CONFIDENCE_THRESHOLD:
        anomalies.append(
            {
                "kind": "low_confidence_boundary",
                "details": f"confidence {boundary.confidence:.2f} below threshold",
            }
        )
    if cover_lines < _MIN_COVER_LINES:
        anomalies.append(
            {
                "kind": "cover_too_short",
                "details": f"cover span {cover_lines} lines is suspiciously brief",
            }
        )
    elif cover_lines > _MAX_COVER_LINES:
        anomalies.append(
            {
                "kind": "cover_too_long",
                "details": f"cover span {cover_lines} lines exceeds typical facing sheet",
            }
        )
    if not detected_items:
        anomalies.append(
            {
                "kind": "no_items_detected",
                "details": "no statutory Part I/II items matched in early body prose",
            }
        )

    candidate_states: dict[str, str | None] = {}
    for c in cm_result.candidates:
        if (
            c.semantic_key not in candidate_states
            or candidate_states[c.semantic_key] is None
        ):
            candidate_states[c.semantic_key] = c.known_state

    filer_status = next(
        (
            k
            for k in (
                "large_accelerated_filer",
                "accelerated_filer",
                "non_accelerated_filer",
                "smaller_reporting_company",
                "emerging_growth_company",
            )
            if candidate_states.get(k) == "checked"
        ),
        None,
    )

    return {
        "accession": accession,
        "form": form,
        "cover_lines": cover_lines,
        "boundary": {
            "start_line": boundary.start_line,
            "end_line": boundary.end_line,
            "method": boundary.method,
            "confidence": boundary.confidence,
            "evidence_count": len(boundary.evidence),
        },
        "checkmarks": {
            "status": cm_result.status.value,
            "candidate_count": len(cm_result.candidates),
            "candidate_states": candidate_states,
            "rule_415": candidate_states.get("rule_415") == "checked",
            "rule_462b": candidate_states.get("rule_462b") == "checked",
            "filer_status": filer_status,
            "egc_opt_out": candidate_states.get("egc_opt_out") == "checked",
        },
        "taxonomy": {
            "item_count": len(detected_items),
            "detected_items": detected_items,
        },
        "anomalies": anomalies,
    }


def summarize_registration_cases(
    case_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate individual Form S-1 case analyses into an overall summary."""
    case_count = len(case_reports)
    if case_count == 0:
        return {"family": "S-1", "case_count": 0}

    method_counts: Counter[str] = Counter()
    confidence_tiers: Counter[str] = Counter()
    cover_line_lengths: list[int] = []

    rule_415_hits = 0
    rule_462b_hits = 0
    filer_status_counts: Counter[str] = Counter()
    egc_opt_out_hits = 0

    item_coverage: Counter[str] = Counter()
    total_detected_items = 0

    all_anomalies: list[dict[str, Any]] = []
    anomaly_counts: Counter[str] = Counter()

    for rep in case_reports:
        b = rep["boundary"]
        method_counts[b["method"]] += 1
        conf = b["confidence"]
        if conf >= _HIGH_CONFIDENCE_THRESHOLD:
            confidence_tiers["high"] += 1
        elif conf >= _MEDIUM_CONFIDENCE_THRESHOLD:
            confidence_tiers["medium"] += 1
        else:
            confidence_tiers["low"] += 1

        cover_line_lengths.append(rep["cover_lines"])

        cm = rep["checkmarks"]
        if cm.get("rule_415"):
            rule_415_hits += 1
        if cm.get("rule_462b"):
            rule_462b_hits += 1
        status = cm.get("filer_status")
        if status:
            filer_status_counts[status] += 1
        if cm.get("egc_opt_out"):
            egc_opt_out_hits += 1

        tax = rep["taxonomy"]
        total_detected_items += tax["item_count"]
        for it in tax["detected_items"]:
            item_coverage[it] += 1

        for anom in rep["anomalies"]:
            anomaly_counts[anom["kind"]] += 1
            all_anomalies.append(
                {
                    "accession": rep["accession"],
                    "kind": anom["kind"],
                    "details": anom["details"],
                }
            )

    mean_cover = sum(cover_line_lengths) / case_count

    return {
        "family": "S-1",
        "case_count": case_count,
        "boundary_scorecard": {
            "methods": dict(method_counts),
            "confidence_tiers": dict(confidence_tiers),
            "mean_cover_lines": round(mean_cover, 1),
            "min_cover_lines": min(cover_line_lengths),
            "max_cover_lines": max(cover_line_lengths),
        },
        "checkmark_scorecard": {
            "rule_415_count": rule_415_hits,
            "rule_462b_count": rule_462b_hits,
            "filer_status_counts": dict(filer_status_counts),
            "egc_opt_out_count": egc_opt_out_hits,
        },
        "taxonomy_scorecard": {
            "item_coverage": dict(sorted(item_coverage.items())),
            "mean_items_per_case": round(total_detected_items / case_count, 1),
        },
        "anomaly_summary": {
            "total_anomalies": len(all_anomalies),
            "kind_counts": dict(anomaly_counts),
            "sample_anomalies": all_anomalies[:10],
        },
    }


analyze_case = analyze_registration_review_case
summarize_cases = summarize_registration_cases

__all__ = [
    "analyze_case",
    "analyze_registration_review_case",
    "summarize_cases",
    "summarize_registration_cases",
]
