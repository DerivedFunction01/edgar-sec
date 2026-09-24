"""Dataset curation and matrix extraction for reflow clustering.

Ingests text blocks and acceptance inventory records, enforcing the Cover
Boundary Invariant (`start_line >= body_start_line`) to isolate candidate
cohorts past the cover page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from defs.runtime.paths import resolve_paths
from defs.text.reflow.registry import FEATURE_REGISTRY
from defs.text.reflow.tools.clustering.context import BlockContext
from defs.text.reflow.types import ACTION_PRESERVE, ACTION_UNWRAP

COHORT_CLEAN_TABLES = "clean_tables"
COHORT_EDGE_CASE_TABLES = "edge_case_tables"
COHORT_CLEAN_PROSE = "clean_prose"
COHORT_CANDIDATES = "candidates"
COHORT_COVER_EXCLUDED = "cover_excluded"


@dataclass(slots=True)
class DatasetBlock:
    """One annotated or raw text block in the analysis dataset."""

    block_id: str
    text: str
    cohort: str
    control_role: str
    record_kind: str = "block"
    expected_action: str | None = None
    gold_label: str | None = None
    label: str | None = None
    evidence: tuple[str, ...] = ()
    accession: str | None = None
    document_path: str | None = None
    start_line: int = 0
    end_line: int = 0
    body_start_line: int | None = None
    context: BlockContext = field(default=None)  # type: ignore[assignment]


def derive_cohort_and_action(
    record: dict[str, Any], context: BlockContext
) -> tuple[str, str | None]:
    """Derive analytical cohort and ground-truth action from record metadata.

    Returns
    -------
    cohort : str
        One of COHORT_CLEAN_TABLES, COHORT_EDGE_CASE_TABLES, COHORT_CLEAN_PROSE,
        or COHORT_CANDIDATES.
    expected_action : str or None
        ACTION_PRESERVE, ACTION_UNWRAP, or None (for ambiguous candidates).
    """
    gold_label = record.get("gold_label") or record.get("label")
    control_role = record.get("control_role", "")
    record_kind = record.get("record_kind", "block")
    evidence = tuple(record.get("evidence", []) or [])

    # Priority 1: Verified Gold Label / Human Annotation
    if gold_label == "PROSE_UNWRAP":
        return COHORT_CLEAN_PROSE, ACTION_UNWRAP
    if gold_label in ("TABLE_TAG", "LAYOUT_PRESERVE"):
        cohort = (
            COHORT_CLEAN_TABLES
            if (context.gutter_4_col_count >= 2 or context.has_deadspace_corridor)
            else COHORT_EDGE_CASE_TABLES
        )
        return cohort, ACTION_PRESERVE
    if gold_label == "MIXED_REVIEW":
        return COHORT_CANDIDATES, None

    # Priority 2: Explicit expected_action in record
    if "expected_action" in record and record["expected_action"] is not None:
        action = record["expected_action"]
        if action == ACTION_UNWRAP:
            return COHORT_CLEAN_PROSE, ACTION_UNWRAP
        if action == ACTION_PRESERVE:
            cohort = (
                COHORT_CLEAN_TABLES
                if (context.gutter_4_col_count >= 2 or context.has_deadspace_corridor)
                else COHORT_EDGE_CASE_TABLES
            )
            return cohort, ACTION_PRESERVE

    # Priority 3: Candidates with numeric alignment evidence or ambiguous roles
    if "prose_dominant_numeric_alignment" in evidence or control_role in (
        "prose_dominant_candidate",
        "layout_preserve_control",
        "protected_signature_control",
    ):
        return COHORT_CANDIDATES, None

    # Priority 4: Structural Table Controls
    if record_kind == "protected_span" or control_role == "protected_table_control":
        if context.gutter_4_col_count >= 2 or context.has_deadspace_corridor:
            return COHORT_CLEAN_TABLES, ACTION_PRESERVE
        return COHORT_EDGE_CASE_TABLES, ACTION_PRESERVE

    if control_role == "table_tag_control":
        if (
            context.gutter_4_col_count >= 2
            or context.has_deadspace_corridor
            or context.column_underline_count > 0
        ):
            return COHORT_CLEAN_TABLES, ACTION_PRESERVE
        return COHORT_CANDIDATES, None

    # Priority 5: Prose Controls
    if control_role in ("ordinary_prose_control", "hardwrapped_preserve_control"):
        if context.soft_wrap_count > 0 or context.function_word_ratio >= 0.20:
            return COHORT_CLEAN_PROSE, ACTION_UNWRAP
        return COHORT_CANDIDATES, None

    # Priority 6: Context-based fallback for uncurated blocks
    if context.has_table_wrapper_tag or context.gutter_4_col_count >= 2:
        return COHORT_CLEAN_TABLES, ACTION_PRESERVE
    if context.soft_wrap_ratio >= 0.25 and context.alpha_density_w1 >= 0.4:
        return COHORT_CLEAN_PROSE, ACTION_UNWRAP

    return COHORT_CANDIDATES, None


def determine_cohort(record: dict[str, Any], context: BlockContext) -> str:
    """Assign a block to one of the analytical cohorts."""
    cohort, _ = derive_cohort_and_action(record, context)
    return cohort


def resolve_reflow_dataset(path_or_id: str | Path | None = None) -> Path:
    """Resolve the JSONL dataset path from explicit input or acceptance artifacts.

    Precedence
    ----------
    1. Explicit path_or_id provided:
       - If path to an existing file, returns it directly.
       - If path to a directory, checks for ``inventory/annotation_template.jsonl``
         or ``annotation_template.jsonl``.
       - If string matches an inventory ID, looks under
         ``resolve_paths().acceptance_root / "reflow-prose" / <id>``.
    2. Dynamic acceptance inventory discovery:
       - Scans ``resolve_paths().acceptance_root / "reflow-prose"`` for all
         directories containing ``inventory/annotation_template.jsonl``.
       - Selects the latest inventory by modification time.
    3. Raises FileNotFoundError with instructions if no dataset is found.
    """
    acceptance_dir = resolve_paths().acceptance_root / "reflow-prose"
    inv_name = "inventory"
    template_name = "annotation_template.jsonl"

    if path_or_id is not None:
        p = Path(path_or_id).expanduser()
        if p.is_file():
            return p
        if p.is_dir():
            inv_sub = p / inv_name
            nested = inv_sub / template_name
            if nested.is_file():
                return nested
            direct = p / template_name
            if direct.is_file():
                return direct
            raise FileNotFoundError(f"No {template_name} found in directory: {p}")
        # Check if it matches an inventory directory under acceptance_dir
        target_dir = acceptance_dir / str(path_or_id)
        as_inv_dir = target_dir / inv_name / template_name
        if as_inv_dir.is_file():
            return as_inv_dir
        # Try prepending 'inventory-' if missing
        if not str(path_or_id).startswith("inventory-"):
            prefixed_dir = acceptance_dir / f"inventory-{path_or_id}"
            as_prefixed = prefixed_dir / inv_name / template_name
            if as_prefixed.is_file():
                return as_prefixed
        raise FileNotFoundError(f"Specified dataset path or ID not found: {path_or_id}")

    # Dynamic discovery under acceptance_dir
    if acceptance_dir.is_dir():
        candidates: list[Path] = []
        for inv_dir in acceptance_dir.iterdir():
            if not inv_dir.is_dir():
                continue
            inv_sub = inv_dir / inv_name
            template = inv_sub / template_name
            if template.is_file():
                candidates.append(template)

        if candidates:
            # Sort by file mtime descending (newest first)
            candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            return candidates[0]

    raise FileNotFoundError(
        f"No reflow acceptance inventory found under {acceptance_dir}. "
        "Build an inventory using 'python -m defs.text.reflow.tools.analysis inventory' "
        "or pass an explicit path via --dataset <path>."
    )


def load_dataset_from_jsonl(
    path: Path | str,
    *,
    enforce_cover_boundary: bool = True,
    max_blocks: int | None = None,
) -> list[DatasetBlock]:
    """Load blocks from an annotation template JSONL file.

    Parameters
    ----------
    path : Path or str
        Path to annotation_template.jsonl.
    enforce_cover_boundary : bool
        If True, excludes blocks with start_line < body_start_line when
        cover boundary is known or determinable.
    max_blocks : int, optional
        Limit on number of loaded blocks (for quick probing).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset path not found: {path}")

    dataset: list[DatasetBlock] = []

    with path.open("r", encoding="utf-8") as f:
        for line_idx, line in enumerate(f):
            if not line.strip():
                continue
            if max_blocks is not None and len(dataset) >= max_blocks:
                break
            record = json.loads(line)
            text = record.get("block_text", "")
            start_line = record.get("current_output_line_start", 0)
            end_line = record.get("current_output_line_end", 0)
            control_role = record.get("control_role", "")
            record_kind = record.get("record_kind", "block")
            gold_label = record.get("gold_label")
            label = record.get("label")
            evidence = tuple(record.get("evidence", []) or [])

            context = BlockContext(text)
            cohort, expected_action = derive_cohort_and_action(record, context)

            # Check cover boundary
            body_start_line = record.get("body_start_line")
            if (
                body_start_line is not None
                and enforce_cover_boundary
                and end_line <= body_start_line
            ):
                cohort = COHORT_COVER_EXCLUDED

            block = DatasetBlock(
                block_id=record.get("block_id", f"block_{line_idx}"),
                text=text,
                cohort=cohort,
                control_role=control_role,
                record_kind=record_kind,
                expected_action=expected_action,
                gold_label=gold_label,
                label=label,
                evidence=evidence,
                accession=record.get("accession"),
                document_path=record.get("document_path"),
                start_line=start_line,
                end_line=end_line,
                body_start_line=body_start_line,
                context=context,
            )

            if enforce_cover_boundary and cohort == COHORT_COVER_EXCLUDED:
                continue

            dataset.append(block)

    return dataset


def extract_feature_matrix(
    blocks: list[DatasetBlock],
) -> tuple[np.ndarray, list[str], list[str]]:
    """Convert dataset blocks into feature matrix X, feature names, and labels.

    Returns
    -------
    X : np.ndarray of shape (N, D)
        Feature values for all N blocks across D registered features.
    feature_names : list[str] of length D
        Names of the features in column order.
    cohorts : list[str] of length N
        Assigned cohort for each block.
    """
    feature_names = list(FEATURE_REGISTRY.keys())
    matrix = np.zeros((len(blocks), len(feature_names)), dtype=float)
    cohorts = [b.cohort for b in blocks]

    for i, block in enumerate(blocks):
        matrix[i, :] = block.context.to_feature_vector()

    return matrix, feature_names, cohorts


__all__ = [
    "COHORT_CANDIDATES",
    "COHORT_CLEAN_PROSE",
    "COHORT_CLEAN_TABLES",
    "COHORT_COVER_EXCLUDED",
    "COHORT_EDGE_CASE_TABLES",
    "DatasetBlock",
    "derive_cohort_and_action",
    "determine_cohort",
    "extract_feature_matrix",
    "load_dataset_from_jsonl",
    "resolve_reflow_dataset",
]
