"""Unit and contract tests for reflow dataset loading and resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from defs.text.reflow.tools.clustering.context import BlockContext
from defs.text.reflow.tools.clustering.dataset import (
    COHORT_CANDIDATES,
    COHORT_CLEAN_PROSE,
    COHORT_CLEAN_TABLES,
    COHORT_EDGE_CASE_TABLES,
    derive_cohort_and_action,
    load_dataset_from_jsonl,
    resolve_reflow_dataset,
)
from defs.text.reflow.types import ACTION_PRESERVE, ACTION_UNWRAP

SAMPLE_TABLE = (
    "          Office furniture and equipment  $   191,046\n"
    "          Computer equipment                  127,686\n"
    "                                          -----------\n"
    "                                          $   318,732"
)

SAMPLE_PROSE = (
    "The Company's consolidated financial statements have been prepared in accordance\n"
    "with U.S. generally accepted accounting principles."
)


def test_derive_cohort_and_action_from_gold_label() -> None:
    ctx = BlockContext(SAMPLE_PROSE)
    # A block that had table_tag_control in baseline, but gold_label is PROSE_UNWRAP
    rec = {
        "control_role": "table_tag_control",
        "gold_label": "PROSE_UNWRAP",
    }
    cohort, action = derive_cohort_and_action(rec, ctx)
    assert cohort == COHORT_CLEAN_PROSE
    assert action == ACTION_UNWRAP


def test_derive_cohort_and_action_structural_controls() -> None:
    ctx_table = BlockContext(SAMPLE_TABLE)
    rec_table = {
        "control_role": "protected_table_control",
        "record_kind": "protected_span",
    }
    cohort, action = derive_cohort_and_action(rec_table, ctx_table)
    assert cohort in (COHORT_CLEAN_TABLES, COHORT_EDGE_CASE_TABLES)
    assert action == ACTION_PRESERVE

    ctx_sig = BlockContext("     /s/ John Doe\n     Chief Executive Officer")
    rec_sig = {
        "control_role": "protected_signature_control",
        "record_kind": "protected_signature",
    }
    cohort_sig, action_sig = derive_cohort_and_action(rec_sig, ctx_sig)
    assert cohort_sig == COHORT_CANDIDATES
    assert action_sig is None

    ctx_prose = BlockContext(SAMPLE_PROSE)
    rec_prose = {"control_role": "ordinary_prose_control", "record_kind": "block"}
    cohort_prose, action_prose = derive_cohort_and_action(rec_prose, ctx_prose)
    assert cohort_prose == COHORT_CLEAN_PROSE
    assert action_prose == ACTION_UNWRAP


def test_derive_cohort_and_action_candidates() -> None:
    ctx = BlockContext("Revenue in 2023 was       $10,000")
    rec = {
        "control_role": "prose_dominant_candidate",
        "evidence": ["prose_dominant_numeric_alignment"],
    }
    cohort, action = derive_cohort_and_action(rec, ctx)
    assert cohort == COHORT_CANDIDATES
    assert action is None


def test_load_dataset_from_jsonl(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "dataset.jsonl"
    records = [
        {
            "block_id": "b1",
            "block_text": SAMPLE_PROSE,
            "control_role": "ordinary_prose_control",
            "record_kind": "block",
            "current_output_line_start": 10,
            "current_output_line_end": 15,
            "body_start_line": 5,
        },
        {
            "block_id": "b2",
            "block_text": SAMPLE_TABLE,
            "control_role": "protected_table_control",
            "record_kind": "protected_span",
            "current_output_line_start": 20,
            "current_output_line_end": 25,
            "body_start_line": 5,
        },
        {
            "block_id": "b3_cover",
            "block_text": "Item 1. Cover Page",
            "control_role": "ordinary_prose_control",
            "record_kind": "block",
            "current_output_line_start": 1,
            "current_output_line_end": 3,
            "body_start_line": 5,
        },
    ]

    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    blocks = load_dataset_from_jsonl(jsonl_path, enforce_cover_boundary=True)
    assert len(blocks) == 2
    assert blocks[0].block_id == "b1"
    assert blocks[0].expected_action == ACTION_UNWRAP
    assert blocks[1].block_id == "b2"
    assert blocks[1].expected_action == ACTION_PRESERVE


def test_resolve_reflow_dataset_explicit_file(tmp_path: Path) -> None:
    target_file = tmp_path / "custom.jsonl"
    target_file.write_text("{}\n", encoding="utf-8")

    resolved = resolve_reflow_dataset(target_file)
    assert resolved == target_file


def test_resolve_reflow_dataset_explicit_dir(tmp_path: Path) -> None:
    inv_dir = tmp_path / "my_inventory"
    inv_dir.mkdir()
    template = inv_dir / "inventory" / "annotation_template.jsonl"
    template.parent.mkdir()
    template.write_text("{}\n", encoding="utf-8")

    resolved = resolve_reflow_dataset(inv_dir)
    assert resolved == template


def test_resolve_reflow_dataset_missing_raises(tmp_path: Path) -> None:
    non_existent = tmp_path / "non_existent.jsonl"
    with pytest.raises(
        FileNotFoundError, match="Specified dataset path or ID not found"
    ):
        resolve_reflow_dataset(non_existent)
