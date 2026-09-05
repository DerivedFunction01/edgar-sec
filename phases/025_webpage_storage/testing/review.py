"""Document case execution, bounded diagnostics, and review rendering."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defs.text.html import parse_html

from ..core.records import DocumentLocator
from ..processors import DefaultFilingProcessor


@dataclass(frozen=True, slots=True)
class DocumentCaseResult:
    """Detailed result used by review tools without changing production output."""

    document_id: str
    accession: str
    document_path: str
    source_sha256: str
    source_text: str
    preprocessed: Any
    normalization: Any
    processed: Any

    @property
    def normalized_text(self) -> str:
        return self.processed.payload.decode("utf-8")


def run_document_case(record: dict[str, Any]) -> DocumentCaseResult:
    """Run one corpus row through the production processor and capture stages."""

    raw = bytes(record["source_bytes"])
    expected_hash = str(record["source_sha256"])
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"source hash mismatch for {record['document_id']}")
    locator = DocumentLocator(
        locator_key=str(record["document_id"]),
        accession=str(record["accession"]),
        document_path=str(record["document_path"]),
        archive_url="",
        form=str(record.get("form", "")),
    )
    processor = DefaultFilingProcessor()
    preprocessed = processor.preprocessor.preprocess(
        raw, metadata={"form": locator.form}
    )
    normalization = processor.normalizer.normalize_result(
        preprocessed, metadata={"form": locator.form}
    )
    processed = processor.build_processed_document(preprocessed, normalization, locator)
    return DocumentCaseResult(
        document_id=str(record["document_id"]),
        accession=str(record["accession"]),
        document_path=str(record["document_path"]),
        source_sha256=expected_hash,
        source_text=preprocessed.raw_text,
        preprocessed=preprocessed,
        normalization=normalization,
        processed=processed,
    )


def stable_expected_metadata(result: DocumentCaseResult) -> dict[str, Any]:
    """Return only deterministic contract metadata suitable for a golden."""

    metadata = result.processed.metadata
    analysis = result.normalization.page_analysis
    decisions = getattr(analysis, "decisions", ()) if analysis else ()
    return {
        "representation": result.preprocessed.representation,
        "reflow": result.normalization.reflow is not None,
        "marker_count": len(getattr(analysis, "markers", ())) if analysis else 0,
        "marker_actions": {
            "remove": sum(item.action.value == "remove" for item in decisions),
            "normalize": sum(item.action.value == "normalize" for item in decisions),
            "preserve": sum(item.action.value == "preserve" for item in decisions),
        },
        "accepted_run_count": len(getattr(analysis, "page_number_runs", ()))
        if analysis
        else 0,
        "terminal_state": (
            analysis.terminal_state.value if analysis is not None else "none"
        ),
        "body_anchor_type": metadata.get("body_anchor_type"),
        "toc_detected": metadata.get("toc_start_line") is not None,
    }


def bounded_analysis(result: DocumentCaseResult) -> dict[str, Any]:
    """Serialize analysis without persisting the unbounded source_text field."""

    analysis = result.normalization.page_analysis
    if analysis is None:
        return {}
    payload = dataclasses.asdict(analysis)
    payload.pop("source_text", None)
    payload["markers"] = payload.get("markers", ())[:256]
    payload["decisions"] = payload.get("decisions", ())[:256]
    payload["page_number_runs"] = payload.get("page_number_runs", ())[:64]
    payload["header_footer_templates"] = payload.get("header_footer_templates", ())[:64]
    payload["inferred_boundaries"] = payload.get("inferred_boundaries", ())[:256]
    payload["unresolved"] = payload.get("unresolved", ())[:256]
    return payload


def _sanitized_html(source: str) -> str:
    tree = parse_html(source)
    tree.strip_tags(("script", "style", "meta", "noscript"))
    for node in tree.traverse():
        for name in list(node.attributes.keys()):
            if name.casefold().startswith("on") or name.casefold() in {
                "src",
                "href",
                "action",
            }:
                del node.raw_node.attrs[name]
    return str(tree)


def write_review_artifacts(
    result: DocumentCaseResult,
    output_dir: Path,
    *,
    expected_output: str | None = None,
    expected_metadata: str | None = None,
) -> dict[str, Any]:
    """Write one source-first review bundle and return its manifest entry."""

    output_dir.mkdir(parents=True, exist_ok=True)
    current = result.normalized_text
    case_id = result.document_id
    metadata = {
        "document_id": case_id,
        "accession": result.accession,
        "document_path": result.document_path,
        "source_sha256": result.source_sha256,
        "representation": result.preprocessed.representation,
        "source_bytes": len(result.source_text.encode("utf-8")),
        "current_output_sha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
        "expected_metadata": (
            json.loads(expected_metadata) if expected_metadata else None
        ),
    }
    (output_dir / f"{case_id}.txt").write_text(current + "\n", encoding="utf-8")
    (output_dir / f"{case_id}.analysis.json").write_text(
        json.dumps(bounded_analysis(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{case_id}.metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if result.document_path.casefold().endswith((".htm", ".html", ".xhtml")):
        (output_dir / f"{case_id}.html").write_text(
            _sanitized_html(result.source_text), encoding="utf-8"
        )

    if expected_output is not None:
        from difflib import HtmlDiff, unified_diff

        diff = "".join(
            unified_diff(
                expected_output.splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile="expected",
                tofile="actual",
            )
        )
        (output_dir / f"{case_id}.diff.patch").write_text(diff, encoding="utf-8")
        diff_html = HtmlDiff().make_file(
            expected_output.splitlines(),
            current.splitlines(),
            fromdesc="expected",
            todesc="actual",
        )
        (output_dir / f"{case_id}.diff.html").write_text(diff_html, encoding="utf-8")

    analysis = result.normalization.page_analysis
    return {
        "document_id": case_id,
        "accession": result.accession,
        "document_path": result.document_path,
        "source_sha256": result.source_sha256,
        "representation": result.preprocessed.representation,
        "marker_count": len(getattr(analysis, "markers", ())) if analysis else 0,
        "table_count": result.source_text.casefold().count("<table"),
        "current_output_sha256": metadata["current_output_sha256"],
        "expected_available": expected_output is not None,
        "status": None,
        "pattern": None,
        "issues": [],
        "evidence": None,
        "recommendation": None,
        "deferred": [],
    }


def process_and_write_review_case(
    record: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Execute processing for one document case, write its files, and return manifest entry."""
    result = run_document_case(record)
    return write_review_artifacts(
        result,
        output_dir,
        expected_output=record.get("expected_output"),
        expected_metadata=record.get("expected_metadata"),
    )


__all__ = [
    "DocumentCaseResult",
    "bounded_analysis",
    "process_and_write_review_case",
    "run_document_case",
    "stable_expected_metadata",
    "write_review_artifacts",
]
