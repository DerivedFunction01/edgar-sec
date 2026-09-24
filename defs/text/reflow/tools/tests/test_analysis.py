from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from defs.storage import pq
from defs.text.reflow.tools.analysis_export import export_labeled_inventory
from defs.text.reflow.tools.analysis_features import LABELS
from defs.text.reflow.tools.analysis_inventory import build_inventory


def _review_case(root: Path, *, stale_manifest_hash: bool = False) -> tuple[Path, str]:
    document_id = "a" * 64
    case_dir = root / "cases" / document_id
    case_dir.mkdir(parents=True)
    prose_candidate = (
        "Revenues for the year ended 2024 increased by".ljust(55) + "   18.2%",
        "Approximately 5 percent or $400 of the increase is".ljust(55) + "   $12,400",
        "The remaining increase reflects service hours under".ljust(55) + "   $10,500",
        "Existing and new service contracts in the region",
        "The changes occurred during December 2023 and".ljust(55) + "   2023",
        "Additional offices opened in January and March of",
        "Local revenue growth continued during the following",
    )
    ordinary_prose = (
        "The company operates home health offices in several regions.\n"
        "Its services are delivered by local clinical teams."
    )
    table = (
        "Revenue by service\n"
        "Domestic ASDS 9.6/56/64 kbps                                 25%\n"
        "Domestic DDS                                                 40%\n"
        "Domestic ACCUNET T1.5                                        55%\n"
        "Domestic ACCUNET T45                                         50%"
    )
    protected = "<TABLE>\n<S> Service <C> Amount\nHome care $100\n</TABLE>"
    signature = (
        "Signature                         Title                  Date\n\n"
        "/s/ Test Signer\n"
        "____________\n"
        "Test Signer                      Director                January 1, 2024"
    )
    text = "\n\n".join(
        ("\n".join(prose_candidate), ordinary_prose, table, protected, signature)
    )
    text_path = case_dir / f"{document_id}.txt"
    text_path.write_text(text, encoding="utf-8")
    metadata = {
        "accession": "000000000024000001",
        "document_path": "review.txt",
        "form": "10-K",
    }
    (case_dir / f"{document_id}.metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    output_hash = hashlib.sha256(text_path.read_bytes()).hexdigest()
    manifest_hash = "0" * 64 if stale_manifest_hash else output_hash
    row = {
        "document_id": document_id,
        "accession": metadata["accession"],
        "document_path": metadata["document_path"],
        "source_sha256": "1" * 64,
        "current_output_sha256": manifest_hash,
    }
    (root / "review_manifest.jsonl").write_text(
        json.dumps(row, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root, document_id


def _read_shards(root: Path, files: list[dict], subdirectory: str) -> list[dict]:
    rows = []
    for shard in files:
        table = pq.read_table(root / subdirectory / shard["path"])
        rows.extend(table.to_pylist())
    return rows


def test_inventory_exports_stable_blocks_controls_and_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review_root, document_id = _review_case(tmp_path / "review")
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_ROOT", str(artifacts_root))

    first = build_inventory(
        review_root,
        "inventory-one",
        controls_per_role_per_document=1,
        block_batch_size=2,
        token_batch_size=20,
    )
    second = build_inventory(
        review_root,
        "inventory-two",
        controls_per_role_per_document=1,
        block_batch_size=3,
        token_batch_size=30,
    )

    first_root = (
        artifacts_root / "acceptance" / "reflow-prose" / "inventory-one" / "inventory"
    )
    first_blocks = _read_shards(first_root, first["files"]["blocks"], "")
    first_tokens = _read_shards(first_root, first["files"]["tokens"], "")
    second_root = (
        artifacts_root / "acceptance" / "reflow-prose" / "inventory-two" / "inventory"
    )
    second_blocks = _read_shards(second_root, second["files"]["blocks"], "")

    assert first["review_document_count"] == 1
    assert first["block_row_count"] == len(first_blocks)
    assert first["token_row_count"] == len(first_tokens)
    assert {row["block_id"] for row in first_blocks} == {
        row["block_id"] for row in second_blocks
    }
    candidates = [
        row
        for row in first_blocks
        if "prose_dominant_numeric_alignment" in row["classifier_evidence"]
    ]
    assert len(candidates) == 1
    assert candidates[0]["document_id"] == document_id
    assert candidates[0]["label_required"] is True
    assert candidates[0]["classifier_action"] == "preserve"
    assert any(row["record_kind"] == "protected_span" for row in first_blocks)
    assert any(row["record_kind"] == "protected_signature" for row in first_blocks)
    assert any(row["control_role"] == "ordinary_prose_control" for row in first_blocks)
    assert first_tokens

    template = [
        json.loads(line)
        for line in (first_root / "annotation_template.jsonl").read_text().splitlines()
    ]
    assert candidates[0]["block_id"] in {row["block_id"] for row in template}
    labels = []
    for row in template:
        if row["control_role"] in {
            "ordinary_prose_control",
            "prose_dominant_candidate",
        }:
            label = "PROSE_UNWRAP"
        elif row["control_role"] in {"protected_table_control", "table_tag_control"}:
            label = "TABLE_TAG"
        else:
            label = "LAYOUT_PRESERVE"
        assert label in LABELS
        labels.append(
            {
                "block_id": row["block_id"],
                "label": label,
                "rationale": "synthetic test control",
                "annotator": "test",
            }
        )
    annotation_path = tmp_path / "labels.jsonl"
    annotation_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in labels),
        encoding="utf-8",
    )
    exported = export_labeled_inventory(
        "inventory-one", "labels-one", annotation_path, batch_size=2
    )
    label_root = first_root.parent / "labels" / "labels-one"
    labeled_blocks = _read_shards(label_root, exported["files"]["blocks"], "")
    candidate_labeled = next(
        row for row in labeled_blocks if row["block_id"] == candidates[0]["block_id"]
    )
    assert candidate_labeled["gold_label"] == "PROSE_UNWRAP"
    assert exported["annotation_count"] == len(labels)


def test_inventory_rejects_stale_review_output_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review_root, _ = _review_case(tmp_path / "review", stale_manifest_hash=True)
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path / "artifacts"))

    with pytest.raises(ValueError, match="hash mismatch"):
        build_inventory(review_root, "stale-inventory")


def test_export_rejects_incomplete_or_duplicate_annotations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review_root, _ = _review_case(tmp_path / "review")
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path / "artifacts"))
    build_inventory(review_root, "inventory")
    inventory_root = (
        tmp_path
        / "artifacts"
        / "acceptance"
        / "reflow-prose"
        / "inventory"
        / "inventory"
    )
    template = [
        json.loads(line)
        for line in (inventory_root / "annotation_template.jsonl")
        .read_text()
        .splitlines()
    ]
    assert template
    one_label = {
        "block_id": template[0]["block_id"],
        "label": "MIXED_REVIEW",
        "rationale": "test",
    }
    annotations = tmp_path / "incomplete.jsonl"
    annotations.write_text(json.dumps(one_label) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="coverage mismatch"):
        export_labeled_inventory("inventory", "incomplete", annotations)

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        json.dumps(one_label) + "\n" + json.dumps(one_label) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate block_id"):
        export_labeled_inventory("inventory", "duplicate", duplicate)
