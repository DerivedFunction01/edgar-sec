from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.review.paths import PIPELINE_REVIEW_MANIFEST_FILE
from edgar_sec.pipelines.document_acquisition.review_artifacts.analyzer import (
    ReviewAnalysisError,
    _load_artifact,
    analyze_review_run,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.labels import (
    ReviewLabelError,
    load_case_review_labels,
)


class HoldoutAnalysisError(ValueError):
    pass


def _validated_spec(spec: dict[str, Any]) -> dict[str, Any]:
    try:
        if spec.get("schema_version") != 1:
            raise ValueError
        protocol_id = validate_safe_id(spec["protocol_id"], "protocol_id")
        century = spec["accession_century"]
        train_end = spec["training_end_year"]
        holdout_start = spec["holdout_start_year"]
        holdout_end = spec["holdout_end_year"]
        raw_ciks = spec["holdout_ciks"]
        if century not in {1900, 2000}:
            raise ValueError
        if any(
            type(value) is not int for value in (train_end, holdout_start, holdout_end)
        ):
            raise ValueError
        if not century <= train_end < holdout_start <= holdout_end < century + 100:
            raise ValueError
        if not isinstance(raw_ciks, list) or not raw_ciks:
            raise ValueError
        ciks = tuple(str(Cik.from_raw(value)) for value in raw_ciks)
        if len(set(ciks)) != len(ciks) or tuple(sorted(ciks)) != ciks:
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise HoldoutAnalysisError(
            "holdout partition specification is invalid"
        ) from error
    return {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "accession_century": century,
        "training_end_year": train_end,
        "holdout_start_year": holdout_start,
        "holdout_end_year": holdout_end,
        "holdout_ciks": ciks,
    }


def _case_rows(labels: tuple[dict[str, object], ...]) -> tuple[dict[str, Any], ...]:
    groups: dict[str, list[dict[str, object]]] = {}
    seen_labels: set[str] = set()
    for label in labels:
        digest = label.get("artifact_sha256")
        unsigned = {
            key: value for key, value in label.items() if key != "artifact_sha256"
        }
        if (
            label.get("artifact_type") != "document_acquisition.exhibit_label"
            or label.get("artifact_version") != 1
            or not is_sha256_hex_digest(digest)
            or canonical_hash(unsigned) != digest
            or digest in seen_labels
        ):
            raise HoldoutAnalysisError("holdout label record is invalid")
        seen_labels.add(digest)
        groups.setdefault(str(label.get("processing_review_sha256")), []).append(label)

    rows = []
    for review_digest, case_labels in sorted(groups.items()):
        first = case_labels[0]
        invariant_fields = (
            "fixture_id",
            "capture_id",
            "target_id",
            "accession",
            "issuer_cik",
            "accession_year_code",
            "form",
            "target_type",
            "selected_sha256",
            "predicted_outcome",
            "expected_identity",
            "versions",
        )
        if any(
            any(label.get(field) != first.get(field) for field in invariant_fields)
            for label in case_labels[1:]
        ):
            raise HoldoutAnalysisError("case labels disagree on pinned identity")
        if not is_sha256_hex_digest(review_digest) or not is_sha256_hex_digest(
            first.get("selected_sha256")
        ):
            raise HoldoutAnalysisError("holdout case digests are invalid")
        try:
            accession = AccessionNumber.from_any(str(first["accession"]))
            cik = str(Cik.from_raw(first["issuer_cik"]))
        except (KeyError, TypeError, ValueError) as error:
            raise HoldoutAnalysisError(
                "holdout accession identity is invalid"
            ) from error
        if (
            cik != str(Cik.from_raw(accession.raw[:10]))
            or first.get("accession_year_code") != accession.raw[11:13]
            or any(
                label.get("outcome") not in {"positive", "negative", "ambiguous"}
                for label in case_labels
            )
            or first.get("predicted_outcome")
            not in {"positive", "negative", "ambiguous"}
        ):
            raise HoldoutAnalysisError("holdout label disagrees with accession")
        adjudications = [
            label
            for label in case_labels
            if label.get("annotation_kind") == "adjudication"
        ]
        independent = [
            label
            for label in case_labels
            if label.get("annotation_kind") == "independent"
        ]
        if len(adjudications) > 1 or len(
            {label.get("annotator_id") for label in independent}
        ) != len(independent):
            raise HoldoutAnalysisError("case labels violate annotation policy")
        if adjudications:
            resolved = str(adjudications[0]["outcome"])
        else:
            outcomes = {str(label["outcome"]) for label in independent}
            resolved = (
                next(iter(outcomes))
                if len(independent) >= 2 and len(outcomes) == 1
                else None
            )
        rows.append(
            {
                "review_sha256": review_digest,
                "selected_sha256": first["selected_sha256"],
                "accession": str(accession),
                "issuer_cik": cik,
                "accession_year_code": accession.raw[11:13],
                "form": first["form"],
                "family": first["target_type"],
                "predicted": first["predicted_outcome"],
                "outcome": resolved,
                "annotation_count": len(case_labels),
            }
        )
    return tuple(rows)


def _partition(year: int, cik: str, spec: dict[str, Any]) -> str:
    if cik in spec["holdout_ciks"]:
        if spec["holdout_start_year"] <= year <= spec["holdout_end_year"]:
            return "holdout"
        return "excluded"
    if year <= spec["training_end_year"]:
        return "training"
    return "excluded"


def _metrics(rows: tuple[dict[str, Any], ...]) -> list[dict[str, int | str]]:
    groups: dict[tuple[str, str], Counter[str]] = {}
    for row in rows:
        key = (row["form"], row["family"])
        counts = groups.setdefault(key, Counter())
        counts["cases"] += 1
        counts["annotations"] += row["annotation_count"]
        if row["outcome"] is None:
            counts["unresolved_cases"] += 1
            continue
        counts["resolved_cases"] += 1
        if row["outcome"] == "ambiguous":
            counts["ambiguous_labels"] += 1
        elif row["predicted"] == "ambiguous":
            counts["prediction_abstentions"] += 1
            counts[f"{row['outcome']}_abstentions"] += 1
            if row["outcome"] == "positive":
                counts["false_negatives"] += 1
        elif row["outcome"] == "positive" and row["predicted"] == "positive":
            counts["true_positives"] += 1
        elif row["outcome"] == "positive":
            counts["false_negatives"] += 1
        elif row["predicted"] == "positive":
            counts["false_positives"] += 1
        else:
            counts["true_negatives"] += 1
    return [
        {
            "form": form,
            "family": family,
            **{
                name: counts[name]
                for name in (
                    "cases",
                    "annotations",
                    "resolved_cases",
                    "unresolved_cases",
                    "true_positives",
                    "false_positives",
                    "true_negatives",
                    "false_negatives",
                    "ambiguous_labels",
                    "prediction_abstentions",
                    "positive_abstentions",
                    "negative_abstentions",
                )
            },
        }
        for (form, family), counts in sorted(groups.items())
    ]


def analyze_holdout_labels(
    labels: tuple[dict[str, object], ...], partition_spec: dict[str, Any]
) -> dict[str, Any]:
    spec = _validated_spec(partition_spec)
    rows = _case_rows(labels)
    if not rows:
        raise HoldoutAnalysisError("holdout report has no labeled cases")
    body_partitions: dict[str, str] = {}
    partitions: dict[str, list[dict[str, Any]]] = {
        "training": [],
        "holdout": [],
        "excluded": [],
    }
    for row in rows:
        try:
            year = spec["accession_century"] + int(row["accession_year_code"])
        except (TypeError, ValueError) as error:
            raise HoldoutAnalysisError("accession year code is invalid") from error
        partition = _partition(year, row["issuer_cik"], spec)
        previous = body_partitions.get(row["selected_sha256"])
        if previous is not None and previous != partition:
            raise HoldoutAnalysisError("identical selected bodies cross partitions")
        if previous is not None:
            raise HoldoutAnalysisError(
                "duplicate selected bodies inflate holdout counts"
            )
        body_partitions[row["selected_sha256"]] = partition
        partitions[partition].append(row)
    if not partitions["holdout"]:
        raise HoldoutAnalysisError("partition has no labeled holdout cases")
    training_ciks = {row["issuer_cik"] for row in partitions["training"]}
    holdout_ciks = {row["issuer_cik"] for row in partitions["holdout"]}
    if training_ciks & holdout_ciks:
        raise HoldoutAnalysisError("issuer leakage crosses training and holdout")
    label_digests = sorted(str(label["artifact_sha256"]) for label in labels)
    return {
        "schema_version": 1,
        "report_type": "document_acquisition.exhibit_holdout",
        "protocol_id": spec["protocol_id"],
        "partition_spec_sha256": canonical_hash(spec),
        "accession_century": spec["accession_century"],
        "training_end_year": spec["training_end_year"],
        "holdout_start_year": spec["holdout_start_year"],
        "holdout_end_year": spec["holdout_end_year"],
        "holdout_issuer_count": len(spec["holdout_ciks"]),
        "holdout_issuers_observed": len(holdout_ciks),
        "labeled_training_cases": len(partitions["training"]),
        "labeled_holdout_cases": len(partitions["holdout"]),
        "excluded_labeled_cases": len(partitions["excluded"]),
        "unresolved_holdout_cases": sum(
            row["outcome"] is None for row in partitions["holdout"]
        ),
        "label_set_sha256": canonical_hash(label_digests),
        "near_duplicate_review": "not_performed",
        "family_form_metrics": _metrics(tuple(partitions["holdout"])),
    }


def analyze_holdout_review_run(
    review_run: str | Path,
    partition_spec: dict[str, Any],
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    requested_root = Path(review_run).expanduser()
    if requested_root.is_symlink():
        raise HoldoutAnalysisError("review run must not be a symlink")
    root = requested_root.resolve(strict=True)
    analyze_review_run(root)
    labels = []
    manifest_path = root / PIPELINE_REVIEW_MANIFEST_FILE
    try:
        with manifest_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                if record.get("status") != "complete":
                    continue
                artifact = _load_artifact(root, record)
                labels.extend(load_case_review_labels(root, artifact))
    except (OSError, UnicodeError, json.JSONDecodeError, ReviewAnalysisError) as error:
        raise HoldoutAnalysisError(
            "review run could not be read for holdout analysis"
        ) from error
    except ReviewLabelError as error:
        raise HoldoutAnalysisError("review label sidecar is invalid") from error
    report = analyze_holdout_labels(tuple(labels), partition_spec)
    if output is not None:
        output_path = Path(output).expanduser()
        if output_path.resolve().is_relative_to(root):
            raise HoldoutAnalysisError(
                "holdout report must be separate from review data"
            )
        atomic_write_json(output_path, report)
    return report
