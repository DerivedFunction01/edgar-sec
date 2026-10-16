"""General review case analysis and scorecard aggregation for form families."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.processing_profiles import get_family_entry
from edgar_sec.engine.forms.cover.boundary.detector import (
    find_cover_boundary_for_profile,
)
from edgar_sec.engine.forms.cover.checkmarks.solver import infer_cover_checkmarks
from edgar_sec.engine.forms.cover.models import BoundaryInput
from edgar_sec.engine.forms.cover.profiles import get_profile
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.engine.forms.sections.notes.detector import detect_notes_sequence

_MIN_COVER_LINES = 5
_MAX_COVER_LINES = 500
_HIGH_CONFIDENCE_THRESHOLD = 0.8
_MEDIUM_CONFIDENCE_THRESHOLD = 0.5

_FILER_STATUS_KEYS = (
    "large_accelerated_filer",
    "accelerated_filer",
    "non_accelerated_filer",
    "smaller_reporting_company",
    "emerging_growth_company",
)


def locate_text_artifact(case_dir: Path) -> Path | None:
    """Find the rendered text artifact or fallback raw file for a review case."""
    ops_dir = case_dir / "operations"
    if not ops_dir.is_dir():
        return None
    preferred = ops_dir / "render_to_txt.txt"
    if preferred.is_file():
        return preferred
    for candidate in sorted(ops_dir.glob("*.txt")):
        if candidate.is_file():
            return candidate
    raw_path = ops_dir / "raw"
    if raw_path.is_file():
        return raw_path
    return None


def analyze_form_case(
    case_dir: Path,
    record: dict[str, Any],
    *,
    form: str | None = None,
    family: str | None = None,
) -> dict[str, Any] | None:
    """Analyze a single review case directory producing common form diagnostics."""
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    accession = str(record.get("accession", case_dir.name))
    resolved_form = str(form or record.get("form") or family or "")
    if not resolved_form:
        rev_path = case_dir / "processing-review.json"
        if rev_path.is_file():
            try:
                rev_data = json.loads(rev_path.read_text(encoding="utf-8"))
                resolved_form = str(rev_data.get("form") or "")
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
    if not resolved_form:
        return None
    cover_profile = get_profile(resolved_form)
    resolved_family = str(family or cover_profile.family)

    entry = get_family_entry(resolved_family) or get_family_entry(resolved_form)
    boundary = find_cover_boundary_for_profile(
        BoundaryInput(text, representation="text"),
        cover_profile,
    )
    cm_result = infer_cover_checkmarks(
        text,
        boundary,
        family=cover_profile.family,
        schema=cover_profile.checkbox_schema,
    )

    lines = text.splitlines()
    body_start = boundary.end_line or 0
    body_lines = lines[body_start:]
    body_text = "\n".join(body_lines)

    detected_items: list[str] = []
    if entry and entry.profile.has_sections and entry.taxonomy_items:
        seq = detect_section_sequence(
            body_text,
            family=resolved_family,
            taxonomy_items=entry.taxonomy_items,
        )
        detected_items = [s.item_identifier for s in seq.sections]

    detected_notes: list[str] = []
    if entry and entry.profile.has_notes:
        notes_seq = detect_notes_sequence(body_text)
        detected_notes = [n.note_label for n in notes_seq.notes]

    anomalies: list[dict[str, Any]] = []
    start = boundary.start_line or 0
    end = boundary.end_line or 0
    cover_lines = max(0, end - start)

    if boundary.confidence < _MEDIUM_CONFIDENCE_THRESHOLD:
        anomalies.append(
            {
                "kind": "low_confidence_boundary",
                "details": f"confidence {boundary.confidence:.2f} below threshold",
                "detail": f"confidence {boundary.confidence:.2f} below threshold",
            }
        )
    if cover_lines < _MIN_COVER_LINES:
        anomalies.append(
            {
                "kind": "cover_too_short",
                "details": f"cover span {cover_lines} lines is suspiciously brief",
                "detail": f"cover span {cover_lines} lines is suspiciously brief",
            }
        )
    elif cover_lines > _MAX_COVER_LINES:
        anomalies.append(
            {
                "kind": "cover_too_long",
                "details": f"cover span {cover_lines} lines exceeds typical facing sheet",
                "detail": f"cover span {cover_lines} lines exceeds typical facing sheet",
            }
        )
    if entry and entry.profile.has_sections and not detected_items:
        anomalies.append(
            {
                "kind": "no_items_detected",
                "details": f"no statutory items matched for family {resolved_family}",
                "detail": f"no statutory items matched for family {resolved_family}",
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
        (k for k in _FILER_STATUS_KEYS if candidate_states.get(k) == "checked"),
        None,
    )

    return {
        "accession": accession,
        "form": resolved_form,
        "family": resolved_family,
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
            "filer_status": filer_status,
        },
        "taxonomy": {
            "item_count": len(detected_items),
            "detected_items": detected_items,
        },
        "notes": {
            "note_count": len(detected_notes),
            "detected_notes": detected_notes,
        },
        "anomalies": anomalies,
    }


def summarize_form_cases(
    case_reports: list[dict[str, Any]],
    *,
    family: str | None = None,
) -> dict[str, Any]:
    """Aggregate individual form case analyses into an overall summary."""
    case_count = len(case_reports)
    resolved_family = family or (case_reports[0]["family"] if case_count else "generic")
    if case_count == 0:
        return {"family": resolved_family, "case_count": 0}

    method_counts: Counter[str] = Counter()
    confidence_tiers: Counter[str] = Counter()
    cover_line_lengths: list[int] = []
    filer_status_counts: Counter[str] = Counter()
    item_coverage: Counter[str] = Counter()
    total_detected_items = 0
    total_detected_notes = 0
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

        status = rep.get("checkmarks", {}).get("filer_status")
        if status:
            filer_status_counts[status] += 1

        tax = rep.get("taxonomy", {})
        total_detected_items += tax.get("item_count", 0)
        for it in tax.get("detected_items", []):
            item_coverage[it] += 1

        notes = rep.get("notes", {})
        total_detected_notes += notes.get("note_count", 0)

        for anom in rep.get("anomalies", []):
            anomaly_counts[anom["kind"]] += 1
            detail = anom.get("details", anom.get("detail", ""))
            all_anomalies.append(
                {
                    "accession": rep["accession"],
                    "kind": anom["kind"],
                    "details": detail,
                    "detail": detail,
                }
            )

    mean_cover = sum(cover_line_lengths) / case_count

    return {
        "family": resolved_family,
        "case_count": case_count,
        "anomaly_count": len(all_anomalies),
        "anomalies": all_anomalies,
        "boundary_scorecard": {
            "methods": dict(method_counts),
            "confidence_tiers": dict(confidence_tiers),
            "mean_cover_lines": round(mean_cover, 1),
            "min_cover_lines": min(cover_line_lengths),
            "max_cover_lines": max(cover_line_lengths),
        },
        "checkmark_scorecard": {
            "filer_status_counts": dict(filer_status_counts),
        },
        "taxonomy_scorecard": {
            "item_coverage": dict(sorted(item_coverage.items())),
            "mean_items_per_case": round(total_detected_items / case_count, 1),
        },
        "notes_scorecard": {
            "total_notes": total_detected_notes,
            "mean_notes_per_case": round(total_detected_notes / case_count, 1),
        },
        "anomaly_summary": {
            "total_anomalies": len(all_anomalies),
            "kind_counts": dict(anomaly_counts),
            "sample_anomalies": all_anomalies[:10],
        },
    }


analyze_case = analyze_form_case
summarize_cases = summarize_form_cases

__all__ = [
    "analyze_case",
    "analyze_form_case",
    "locate_text_artifact",
    "summarize_cases",
    "summarize_form_cases",
]
