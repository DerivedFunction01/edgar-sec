"""Block, context, and annotation-record construction for reflow analysis."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from defs.sec_forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
    is_page_marker_line,
)
from defs.tables.protection import mask_tagged_tables, strip_table_wrapper_tags
from defs.taxonomy.components.financials.reflow import (
    is_financial_table_bridge_line,
    is_financial_table_tail_line,
)
from defs.text.reflow.classifier import _decide
from defs.text.reflow.engine import _classify_block, _segment, reflow_ascii
from defs.text.reflow.features import _compute_features
from defs.text.reflow.types import ACTION_TAG_AND_PRESERVE, ACTION_UNWRAP, ReflowPolicy
from defs.text.syntax.signatures import mask_signature_regions

from .analysis_features import (
    CONTROL_ROLES,
    FEATURE_VERSION,
    digest,
    display_block_text,
    feature_values,
    tokenize,
)


def analysis_policy() -> ReflowPolicy:
    """Return the deterministic policy used for review-output replays."""
    return ReflowPolicy(
        unwrap_pre_body_prose=True,
        relax_prose_layout_gaps=True,
        unwrap_bullet_continuations=True,
        is_checkbox_answer_line=is_checkbox_answer_line,
        is_page_boundary_line=is_page_marker_line,
        is_structural_line=is_cover_layout_line,
        is_table_bridge_line=is_financial_table_bridge_line,
        is_table_tail_line=is_financial_table_tail_line,
    )


def _output_line(line: int, table_spans: tuple, text: str) -> int:
    removed_newlines = 0
    for span in table_spans:
        original_line = text.count("\n", 0, span.start)
        masked_line = original_line - removed_newlines
        if line <= masked_line:
            break
        removed_newlines += span.text.count("\n")
    return line + removed_newlines


def _masked_table_line(spans: tuple, text: str, span_index: int) -> int:
    removed = 0
    for index, span in enumerate(spans):
        masked_line = text.count("\n", 0, span.start) - removed
        if index == span_index:
            return masked_line
        removed += span.text.count("\n")
    raise IndexError(span_index)


def _context(lines: list[str], start: int, end: int, before: bool) -> str:
    window = lines[max(0, start - 2) : start] if before else lines[end : end + 2]
    return "\n".join(display_block_text(line) for line in window)


def _final_decision(decisions: tuple, start: int, end: int):
    return next(
        (
            decision
            for decision in decisions
            if decision.start_line <= start and end <= decision.end_line
        ),
        None,
    )


def _role(
    record_kind: str,
    evidence: tuple[str, ...],
    pipeline_action: str,
    final_action: str,
    features: dict[str, Any],
) -> str:
    if record_kind == "protected_span":
        return "protected_table_control"
    if record_kind == "protected_signature":
        return "protected_signature_control"
    if record_kind == "signature_context":
        return "masked_signature_context"
    if "prose_dominant_numeric_alignment" in evidence:
        return "prose_dominant_candidate"
    if pipeline_action == ACTION_UNWRAP:
        return "ordinary_prose_control"
    if final_action == ACTION_TAG_AND_PRESERVE:
        return "table_tag_control"
    if (
        features["feature_alpha_density"] >= 0.55
        and features["feature_numeric_cell_rows"]
    ):
        return "hardwrapped_preserve_control"
    return "layout_preserve_control"


def _record_id(
    document_id: str, output_sha: str, kind: str, start: int, end: int, text: str
) -> tuple[str, str]:
    content_hash = digest(text)
    block_id = digest(
        "\0".join((document_id, output_sha, kind, str(start), str(end), content_hash))
    )
    return block_id, content_hash


def _template_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_id": row["block_id"],
        "case_id": row["case_id"],
        "document_id": row["document_id"],
        "accession": row["accession"],
        "document_path": row["document_path"],
        "record_kind": row["record_kind"],
        "control_role": row["control_role"],
        "current_output_line_start": row["current_output_line_start"],
        "current_output_line_end": row["current_output_line_end"],
        "current_action": row["pipeline_action"],
        "evidence": row["pipeline_evidence"],
        "features": {
            key: value for key, value in row.items() if key.startswith("feature_")
        },
        "context_before": row["context_before"],
        "block_text": row["block_text"],
        "context_after": row["context_after"],
        "label": None,
        "rationale": "",
        "annotator": "",
    }


def _selected_ids(rows: list[dict[str, Any]], per_role_per_document: int) -> set[str]:
    selected = {
        row["block_id"]
        for row in rows
        if "prose_dominant_numeric_alignment" in row["classifier_evidence"]
        and not row["contains_protected_signature"]
    }
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["control_role"] in CONTROL_ROLES:
            grouped[(row["document_id"], row["control_role"])].append(row)
    for (document_id, role), candidates in sorted(grouped.items()):
        candidates.sort(
            key=lambda row: digest(
                "\0".join((document_id, role, row["block_id"], FEATURE_VERSION))
            )
        )
        selected.update(row["block_id"] for row in candidates[:per_role_per_document])
    return selected


def document_records(
    manifest_row: dict[str, Any],
    text: str,
    metadata: dict[str, Any],
    output_sha: str,
    policy: ReflowPolicy,
    controls_per_role: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract one file's block rows, annotation template, and selected tokens."""
    document_id = str(manifest_row["document_id"])
    accession = str(manifest_row.get("accession") or metadata.get("accession") or "")
    document_path = str(
        manifest_row.get("document_path") or metadata.get("document_path") or ""
    )
    form = str(metadata.get("form") or "")
    source_sha = str(manifest_row.get("source_sha256") or "")
    masked_tables, table_spans = mask_tagged_tables(text)
    masked, signature_regions = mask_signature_regions(masked_tables)
    masked_lines = masked.split("\n")
    blocks = _segment(masked_lines, policy=policy)
    final_result = reflow_ascii(text, body_start_line=0, policy=policy)
    rows: list[dict[str, Any]] = []
    token_sources: dict[str, str] = {}

    for start, end, lines in blocks:
        source_block_text = "\n".join(lines)
        contains_table = any("__SEC_TBL_" in line for line in lines)
        contains_signature = any(
            start < region.end_line and region.start_line < end
            for region in signature_regions
        )
        features = _compute_features(lines)
        classifier = _decide(features, len(lines), contains_table)
        pipeline = _classify_block(
            lines,
            start_line=start,
            end_line=end,
            body_start_line=0,
            page_context=False,
            policy=policy,
            features=features,
        )
        final = _final_decision(final_result.decisions, start, end) or pipeline
        block_text = display_block_text(source_block_text)
        feature_data = feature_values(lines, features)
        block_id, content_fingerprint = _record_id(
            document_id, output_sha, "block", start, end, source_block_text
        )
        output_start = _output_line(start, table_spans, text) + 1
        output_end = max(output_start, _output_line(end, table_spans, text))
        role = _role(
            "signature_context" if contains_signature else "block",
            classifier.evidence,
            pipeline.action,
            final.action,
            feature_data,
        )
        rows.append(
            {
                "block_id": block_id,
                "record_kind": "block",
                "case_id": document_id,
                "document_id": document_id,
                "accession": accession,
                "document_path": document_path,
                "form": form,
                "source_sha256": source_sha,
                "current_output_sha256": output_sha,
                "current_output_line_start": output_start,
                "current_output_line_end": output_end,
                "masked_line_start": start,
                "masked_line_end": end,
                "source_char_start": None,
                "source_char_end": None,
                "block_text": block_text,
                "context_before": _context(masked_lines, start, end, True),
                "context_after": _context(masked_lines, start, end, False),
                "contains_protected_table": contains_table,
                "contains_protected_signature": contains_signature,
                "classifier_action": classifier.action,
                "classifier_confidence": classifier.confidence,
                "classifier_evidence": list(classifier.evidence),
                "classifier_trace": classifier.trace,
                "pipeline_action": pipeline.action,
                "pipeline_evidence": list(pipeline.evidence),
                "pipeline_trace": pipeline.trace,
                "final_action": final.action,
                "final_evidence": list(final.evidence),
                "final_trace": final.trace,
                "control_role": role,
                "label_required": False,
                "gold_label": None,
                "label_rationale": None,
                "split_group": document_id,
                "content_fingerprint": content_fingerprint,
                **feature_data,
            }
        )
        token_sources[block_id] = re.sub(
            r"\[(?:PROTECTED_TABLE|PROTECTED_SIGNATURE)\]", "", block_text
        )

    for span_index, span in enumerate(table_spans):
        output_start = text.count("\n", 0, span.start) + 1
        output_end = max(output_start, text.count("\n", 0, span.end) + 1)
        removed_newlines = sum(
            prior.text.count("\n") for prior in table_spans[:span_index]
        )
        masked_start = text.count("\n", 0, span.start) - removed_newlines
        analysis_text = strip_table_wrapper_tags(span.text)
        block_id, content_fingerprint = _record_id(
            document_id,
            output_sha,
            "protected_span",
            span.start,
            span.end,
            span.text,
        )
        feature_data = feature_values(tuple(analysis_text.splitlines()))
        role = "protected_table_control"
        rows.append(
            {
                "block_id": block_id,
                "record_kind": "protected_span",
                "case_id": document_id,
                "document_id": document_id,
                "accession": accession,
                "document_path": document_path,
                "form": form,
                "source_sha256": source_sha,
                "current_output_sha256": output_sha,
                "current_output_line_start": output_start,
                "current_output_line_end": output_end,
                "masked_line_start": masked_start,
                "masked_line_end": masked_start + 1,
                "source_char_start": span.start,
                "source_char_end": span.end,
                "block_text": span.text,
                "context_before": _context(
                    text.splitlines(), output_start - 1, output_start - 1, True
                ),
                "context_after": _context(
                    text.splitlines(), output_end, output_end, False
                ),
                "contains_protected_table": True,
                "contains_protected_signature": False,
                "classifier_action": "preserve",
                "classifier_confidence": 1.0,
                "classifier_evidence": ["protected_tagged_table"],
                "classifier_trace": "hard_preserve",
                "pipeline_action": "preserve",
                "pipeline_evidence": ["protected_tagged_table"],
                "pipeline_trace": "hard_preserve",
                "final_action": "preserve",
                "final_evidence": ["protected_tagged_table"],
                "final_trace": "hard_preserve",
                "control_role": role,
                "label_required": False,
                "gold_label": None,
                "label_rationale": None,
                "split_group": document_id,
                "content_fingerprint": content_fingerprint,
                **feature_data,
            }
        )
        token_sources[block_id] = analysis_text

    for region in signature_regions:
        region_text = "\n".join(region.lines)
        output_start = _output_line(region.start_line, table_spans, text) + 1
        output_end = max(output_start, _output_line(region.end_line, table_spans, text))
        block_id, content_fingerprint = _record_id(
            document_id,
            output_sha,
            "protected_signature",
            region.start_line,
            region.end_line,
            region_text,
        )
        feature_data = feature_values(region.lines)
        role = "protected_signature_control"
        rows.append(
            {
                "block_id": block_id,
                "record_kind": "protected_signature",
                "case_id": document_id,
                "document_id": document_id,
                "accession": accession,
                "document_path": document_path,
                "form": form,
                "source_sha256": source_sha,
                "current_output_sha256": output_sha,
                "current_output_line_start": output_start,
                "current_output_line_end": output_end,
                "masked_line_start": region.start_line,
                "masked_line_end": region.end_line,
                "source_char_start": None,
                "source_char_end": None,
                "block_text": region_text,
                "context_before": _context(
                    masked_lines, region.start_line, region.start_line, True
                ),
                "context_after": _context(
                    masked_lines, region.end_line, region.end_line, False
                ),
                "contains_protected_table": False,
                "contains_protected_signature": True,
                "classifier_action": "preserve",
                "classifier_confidence": region.confidence,
                "classifier_evidence": ["protected_signature_layout"],
                "classifier_trace": "hard_preserve",
                "pipeline_action": "preserve",
                "pipeline_evidence": ["protected_signature_layout"],
                "pipeline_trace": "hard_preserve",
                "final_action": "preserve",
                "final_evidence": ["protected_signature_layout"],
                "final_trace": "hard_preserve",
                "control_role": role,
                "label_required": False,
                "gold_label": None,
                "label_rationale": None,
                "split_group": document_id,
                "content_fingerprint": content_fingerprint,
                **feature_data,
            }
        )
        token_sources[block_id] = region_text

    selected = _selected_ids(rows, controls_per_role)
    templates: list[dict[str, Any]] = []
    tokens: list[dict[str, Any]] = []
    for row in rows:
        row["label_required"] = row["block_id"] in selected
        if row["label_required"]:
            templates.append(_template_row(row))
            tokens.extend(
                tokenize(
                    token_sources[row["block_id"]],
                    row["block_id"],
                    document_id,
                    row["control_role"],
                )
            )
    return rows, templates, tokens


__all__ = ["analysis_policy", "document_records"]
