from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.infra.storage.review.diff import compare_review_runs
from edgar_sec.infra.storage.review.paths import (
    ReviewPaths,
    new_diff_dir,
    new_review_run_dir,
    review_runs_root,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.review_artifacts.builder import (
    build_review_artifacts,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.analyzer import (
    analyze_review_runs,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.labels import (
    build_review_label,
    load_processing_review_artifact,
    write_review_label,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.holdout import (
    analyze_holdout_review_run,
)


def cmd_review_artifacts(args: argparse.Namespace) -> int:
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts_root or None)
    output = (
        Path(args.output)
        if args.output
        else new_review_run_dir(
            review_runs_root(paths.artifacts_root, "document_acquisition")
        )
    )
    result = build_review_artifacts(
        args.fixture,
        output,
        paths=paths,
        limit=args.limit,
        workers=getattr(args, "workers", None),
        no_progress=args.no_progress,
    )
    summary = result.summary
    payload = {
        "schema_version": 1,
        "command": "review generate",
        "review_id": result.review_id,
        "fixture_id": args.fixture,
        "output": str(result.output_root),
        "total": summary.total,
        "completed": summary.completed,
        "fixture_verification_failures": summary.fixture_verification_failure,
        "execution_errors": summary.execution_error,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"review {result.review_id}: {summary.completed}/{summary.total} complete, "
            f"fixture verification failures={summary.fixture_verification_failure}, "
            f"execution errors={summary.execution_error}"
        )
    return result.exit_code


def _review_run_path(value: str, artifacts_root: str | None) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.exists():
        candidate = (
            review_runs_root(
                artifacts_root or resolve_acquisition_paths().artifacts_root,
                "document_acquisition",
            )
            / value
        )
    return candidate


def cmd_review_analyze(args: argparse.Namespace) -> int:
    from edgar_sec.foundation.serialization import pretty_json

    runs = tuple(_review_run_path(value, args.artifacts) for value in args.run)
    report = analyze_review_runs(
        runs, output=Path(args.output) if args.output else None
    )
    if args.json:
        print(pretty_json(report))
    else:
        for run in report["runs"]:
            statuses = ", ".join(
                f"{name}={count}" for name, count in run["case_status_counts"].items()
            )
            operation_statuses = (
                ", ".join(
                    f"{name}={count}"
                    for name, count in run["operation_status_counts"].items()
                )
                or "none"
            )
            print(
                f"review {run['review_id']}: {run['total_cases']} cases; "
                f"{statuses}; operations: {operation_statuses}"
            )
            for fam_rep in run.get("family_reports", []):
                fam = fam_rep.get("family", "")
                case_count = fam_rep.get("case_count", 0)
                print(f"\n--- Form Family '{fam}' Analysis ({case_count} cases) ---")
                print("  Top Element Counts:")
                for tag, cnt in list(fam_rep.get("element_counts", {}).items())[:10]:
                    print(f"    {tag}: {cnt}")
                anom_count = fam_rep.get("anomaly_count", 0)
                print(f"  Anomalies: {anom_count}")
                for anom in fam_rep.get("anomalies", [])[:5]:
                    val = anom.get("value")
                    val_str = f" (value: {val})" if val is not None else ""
                    print(
                        f"    [{anom['kind']}] {anom['accession']}: {anom['detail']}{val_str}"
                    )
                if review_count := fam_rep.get("review_signal_count", 0):
                    print(f"  Review Signals: {review_count}")
                    for signal in fam_rep.get("review_signal_samples", [])[:3]:
                        print(
                            f"    [{signal['kind']}] {signal['accession']}: "
                            f"{signal['value']}"
                        )
                if scorecard := fam_rep.get("field_scorecard"):
                    missing_fields = [
                        (field, values)
                        for field, values in scorecard.items()
                        if (
                            values.get("scope") == "document"
                            and values.get("cases_without_value", 0)
                        )
                        or values.get("blank_occurrences", 0)
                    ]
                    if missing_fields:
                        print("  Missing or Blank Canonical Fields:")
                        for field, values in missing_fields:
                            missing_count = values.get("cases_without_value", 0)
                            blanks = values.get("blank_occurrences", 0)
                            print(
                                f"    {field}: missing in {missing_count}/{case_count} cases; "
                                f"blank values={blanks}"
                            )
                if frequencies := fam_rep.get("value_frequencies"):
                    print("  Ownership Value Frequencies:")
                    for field, distribution in frequencies.items():
                        values = distribution.get("top_values", [])[:5]
                        rendered = ", ".join(
                            f"{entry['value']!r} ({entry['count']})" for entry in values
                        )
                        print(
                            f"    {field}: {distribution['distinct_values']} distinct; "
                            f"top: {rendered}"
                        )
                unp_count = fam_rep.get("unparsed_section_count", 0)
                print(f"  Unparsed Sections: {unp_count}")
                for sample in fam_rep.get("unparsed_samples", [])[:3]:
                    tbl = (
                        f"table {sample['table_index']} - "
                        if "table_index" in sample
                        else ""
                    )
                    print(
                        f"    [{tbl}role={sample.get('role', '-')} - "
                        f"{sample.get('char_length', 0)} chars]: {sample.get('snippet', '')[:100]}..."
                    )
                if outliers := fam_rep.get("outliers"):
                    print("  Outliers & Uncommon Patterns:")
                    missing = outliers.get("missing_fields", {})
                    if sig_miss := missing.get("missing_signatures"):
                        if sig_miss["count"] > 0:
                            samples = ", ".join(sig_miss["sample_accessions"][:3])
                            print(
                                f"    Missing Signatures: {sig_miss['count']} cases (samples: {samples})"
                            )
                    if wc_outliers := outliers.get("word_count_outliers"):
                        print(f"    Word Count Outliers ({len(wc_outliers)}):")
                        for wco in wc_outliers[:5]:
                            print(
                                f"      [{wco['field']}] {wco['accession']} "
                                f"({wco['word_count']} words): '{wco['value']}'"
                            )
                    if unp_pats := outliers.get("uncommon_patterns"):
                        print("    Uncommon Normalized Patterns:")
                        for fld, plist in unp_pats.items():
                            for pentry in plist[:2]:
                                print(
                                    f"      [{fld}] '{pentry['pattern']}' "
                                    f"({pentry['count']} cases, sample: {pentry['sample_accession']})"
                                )
                    if rare_ngs := outliers.get("rare_ngrams"):
                        print("    Rare N-Grams:")
                        for fld, nglist in rare_ngs.items():
                            ng_str = ", ".join(f"'{ng['ngram']}'" for ng in nglist[:3])
                            if ng_str:
                                print(f"      [{fld}]: {ng_str}")
    return 0


def cmd_review_label(args: argparse.Namespace) -> int:
    artifact_path = Path(args.artifact).expanduser()
    review_root, artifact = load_processing_review_artifact(artifact_path)
    analyze_review_runs((review_root,))
    observed_identity = None
    if args.observed_kind == "exhibit":
        if not args.observed_authority or not args.observed_code:
            raise ValueError("exhibit labels require observed authority and code")
        observed_identity = ExhibitIdentity(
            authority_id=args.observed_authority,
            code=args.observed_code,
        )
    elif args.observed_authority or args.observed_code:
        raise ValueError("non-exhibit labels cannot carry an exhibit identity")
    label = build_review_label(
        artifact,
        outcome=args.outcome,
        observed_kind=args.observed_kind,
        observed_identity=observed_identity,
        annotator_id=args.annotator_id,
        annotated_at_utc=args.annotated_at_utc,
        evidence_ref=args.evidence_ref,
        rationale=args.rationale,
        annotation_kind=args.annotation_kind,
        supersedes_label_sha256=tuple(args.supersedes or ()),
    )
    path = write_review_label(review_root, artifact, label)
    result = {
        "label_sha256": label["artifact_sha256"],
        "target_id": label["target_id"],
        "outcome": label["outcome"],
        "path": str(path),
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"label {label['artifact_sha256']}: {label['outcome']} -> {path}")
    return 0


def cmd_review_holdout(args: argparse.Namespace) -> int:
    run = _review_run_path(args.run, args.artifacts)
    spec = json.loads(Path(args.spec).expanduser().read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("holdout partition specification must be an object")
    report = analyze_holdout_review_run(
        run,
        spec,
        output=Path(args.output) if args.output else None,
    )
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(
            f"holdout {report['protocol_id']}: "
            f"{report['labeled_holdout_cases']} labeled cases; "
            f"exact duplicate and near-copy review remain separate evidence"
        )
    return 0


def cmd_review_compare(args: argparse.Namespace) -> int:
    from edgar_sec.pipelines.document_acquisition.review_artifacts.adapter import (
        AcquisitionReviewAdapter,
    )

    base_dir = _review_run_path(args.base, args.artifacts)
    new_dir = _review_run_path(args.new, args.artifacts)
    analyze_review_runs((base_dir, new_dir))
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts or None)
    output_dir = (
        Path(args.output)
        if args.output
        else new_diff_dir(
            review_runs_root(paths.artifacts_root, "document_acquisition")
        )
    )
    summary = compare_review_runs(
        base_dir=base_dir,
        new_dir=new_dir,
        output_dir=output_dir,
        adapter=AcquisitionReviewAdapter(),
        max_display=args.max_display,
    )
    result: dict[str, Any] = {
        "base_run": summary.base_run,
        "new_run": summary.new_run,
        "total_cases": summary.total_cases,
        "unchanged": summary.unchanged_count,
        "changed": summary.changed_count,
        "added": summary.added_count,
        "removed": summary.removed_count,
        "output_dir": str(output_dir),
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(ReviewPaths(output_dir).summary_file.read_text(encoding="utf-8"))
    return 0


__all__ = [
    "cmd_review_analyze",
    "cmd_review_artifacts",
    "cmd_review_compare",
    "cmd_review_holdout",
    "cmd_review_label",
]
