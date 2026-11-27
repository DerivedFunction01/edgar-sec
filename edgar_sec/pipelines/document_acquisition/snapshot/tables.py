"""Snapshot relation assembly for acquisition publishing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths

from .errors import ReferentialIntegrityError
from .schema import SNAPSHOT_RELATION_SCHEMAS


def _assemble_snapshot_tables(
    paths: AcquisitionPaths,
    run_id: str,
    work_targets: list[dict[str, Any]],
    db_data: dict[str, list[dict[str, Any]]],
) -> dict[str, pa.Table]:
    target_states = {row["target_id"]: row for row in db_data.get("target_state", [])}

    accession_ciks: dict[str, str] = {}
    source_assets: dict[str, dict[str, Any]] = {}
    acquisition_slots: list[dict[str, Any]] = []
    logical_docs: dict[str, dict[str, Any]] = {}
    target_results: list[dict[str, Any]] = []
    source_payloads: set[tuple[str, str]] = set()

    for target in work_targets:
        accession = target["accession"]
        target_url = target.get("target_url")
        if target_url:
            # The CIK is the archive CIK the catalog paired with this
            # accession in its target URL, never the accession prefix.
            accession_ciks[accession] = validate_archive_url(
                target_url, accession
            ).archive_cik

        target_id = target["target_id"]
        req_id = target["request_id"]
        source_key = (
            f"bundle:{target.get('target_url') or ''}#seq={target.get('sequence') or 0}"
            if target.get("retrieval_mode") == "bundle_sequence"
            else f"bundle:{target.get('target_url') or ''}#scan"
            if target.get("retrieval_mode") == "bundle_scan"
            else f"direct:{target.get('target_url') or ''}"
        )
        source_asset_id = "asset_" + canonical_hash([accession, source_key])[:32]
        source_assets[source_asset_id] = {
            "source_asset_id": source_asset_id,
            "accession": accession,
            "source_key": source_key,
            "source_kind": target.get("target_role", "primary"),
            "retrieval_mode": target.get("retrieval_mode", "direct_url"),
            "canonical_path": target.get("target_url"),
        }

        seq = target.get("sequence") or 0
        obs_id = f"obs_{target_id}"
        obs_time = datetime.now(UTC)
        acquisition_slots.append(
            {
                "accession": accession,
                "sequence": int(seq),
                "observation_id": obs_id,
                "source_asset_id": source_asset_id,
                "locator": str(target.get("target_url") or ""),
                "retrieval_mode": str(target.get("retrieval_mode") or "direct_url"),
                "observed_at_utc": obs_time,
            }
        )

        planned_key = str(target.get("planned_source_key") or source_key)
        doc_id = "doc_" + canonical_hash([accession, req_id, planned_key])[:32]
        logical_docs[doc_id] = {
            "logical_document_id": doc_id,
            "accession": accession,
            "request_id": req_id,
            "planned_source_key": planned_key,
            "target_role": target.get("target_role", "primary"),
            "target_type": target.get("target_type", "primary"),
        }

        state = target_states.get(target_id, {})
        outcome = state.get("outcome") or (
            "skipped" if not target.get("executable", True) else "failed"
        )
        selected_sha = state.get("selected_sha256")
        selected_bytes = state.get("byte_size")
        target_results.append(
            {
                "run_id": run_id,
                **{
                    k: target[k]
                    for k in target
                    if k in SNAPSHOT_RELATION_SCHEMAS["target_results"].names
                    and k != "run_id"
                },
                "logical_document_id": doc_id,
                "outcome": outcome,
                "status_reason": state.get("status_reason")
                or target.get("skip_reason"),
                "source_asset_id": source_asset_id if selected_sha else None,
                "selected_sha256": selected_sha,
                "byte_size": selected_bytes,
            }
        )
        if selected_sha:
            source_payloads.add((source_asset_id, selected_sha))

    raw_attempts = db_data.get("attempts", [])
    acq_attempts: list[dict[str, Any]] = []
    for att in raw_attempts:
        acq_attempts.append(
            {
                "run_id": run_id,
                "attempt_id": att["attempt_id"],
                "target_id": att["target_id"],
                "source_request_id": att.get("source_request_id"),
                "source_asset_id": att.get("source_asset_id"),
                "attempt_number": int(att.get("attempt_number") or 1),
                "worker_attempt_number": att.get("worker_attempt_number"),
                "attempt_kind": str(att.get("attempt_kind") or "direct"),
                "origin": str(att.get("origin") or "sec_http"),
                "outcome": str(att.get("outcome") or "ok"),
                "retryable": bool(att.get("retryable", False)),
                "sanitized_locator": att.get("sanitized_locator"),
                "http_status": att.get("http_status"),
                "response_sha256": att.get("response_sha256"),
                "response_byte_size": att.get("response_byte_size"),
                "selected_sha256": att.get("selected_sha256"),
                "selected_byte_size": att.get("selected_byte_size"),
                "created_at_utc": _parse_timestamp(att.get("created_at_utc")),
            }
        )

    target_slot_selections = []
    for res in db_data.get("target_slot_resolutions", []):
        target_slot_selections.append(
            {
                "run_id": run_id,
                "target_id": res["target_id"],
                "resolution_id": res["resolution_id"],
                "logical_document_id": f"doc_{res['target_id']}",
                "accession": res.get("accession", ""),
                "sequence": int(res.get("selected_sequence") or 0),
                "observation_id": res.get("observation_id"),
                "source_asset_id": res.get("source_asset_id"),
                "selector": res.get("selector", "catalog_direct"),
                "result": res.get("result", "ok"),
                "evidence_ref": res.get("evidence"),
            }
        )

    slot_types: list[dict[str, Any]] = []

    op_results: list[dict[str, Any]] = []
    representations: list[dict[str, Any]] = []
    representation_inputs: list[dict[str, Any]] = []
    payload_map: dict[str, tuple[str, bytes]] = {}

    for op in db_data.get("operation_state", []):
        t_id = op["target_id"]
        t_state = target_states.get(t_id, {})
        doc_id = next(
            (
                r["logical_document_id"]
                for r in target_results
                if r["target_id"] == t_id
            ),
            f"doc_{t_id}",
        )
        rep_id = op.get("representation_id")
        op_results.append(
            {
                "run_id": run_id,
                "operation_id": op["operation_id"],
                "target_id": t_id,
                "logical_document_id": doc_id,
                "operation": op.get("operation", "raw"),
                "requested": bool(op.get("requested", True)),
                "support_status": op.get("support_status", "supported"),
                "status": "available"
                if op.get("status") in ("available", "succeeded")
                else op.get("status", "available"),
                "source_request_id": op.get("source_request_id"),
                "capability_id": op.get("capability_id"),
                "capability_version": op.get("capability_version"),
                "handler_id": op.get("handler_id"),
                "handler_version": op.get("handler_version"),
                "latest_attempt_id": op.get("latest_attempt_id"),
                "reason_code": op.get("reason_code"),
                "retryable": bool(op.get("retryable", False)),
                "representation_id": rep_id,
            }
        )
        if op.get("status") in ("available", "succeeded") and rep_id:
            out_sha = op.get("output_sha256") or t_state.get("selected_sha256")
            out_size = op.get("output_size") or t_state.get("byte_size") or 0
            if out_sha:
                route = DocumentRoute.TEXT.value
                representations.append(
                    {
                        "representation_id": rep_id,
                        "logical_document_id": doc_id,
                        "operation": op.get("operation", "raw"),
                        "output_kind": "text"
                        if op.get("operation") != "raw"
                        else "raw_bytes",
                        "capability_id": op.get("capability_id")
                        or "raw.selected_source",
                        "capability_version": op.get("capability_version") or "v1",
                        "handler_id": op.get("handler_id") or "raw_identity",
                        "handler_version": op.get("handler_version") or "1",
                        "options_sha256": None,
                        "input_fingerprint": op.get("input_fingerprint") or rep_id,
                        "output_sha256": out_sha,
                        "byte_size": int(out_size),
                        "route": route,
                    }
                )
                src_asset = next(
                    (
                        r["source_asset_id"]
                        for r in target_results
                        if r["target_id"] == t_id
                    ),
                    "asset_default",
                )
                representation_inputs.append(
                    {
                        "representation_id": rep_id,
                        "input_ordinal": 0,
                        "source_asset_id": src_asset or "asset_default",
                        "payload_sha256": out_sha,
                        "input_role": "source",
                    }
                )

    op_attempts: list[dict[str, Any]] = []
    for att in db_data.get("operation_attempts", []):
        op_attempts.append(
            {
                "run_id": run_id,
                "operation_attempt_id": att.get("operation_attempt_id")
                or att.get("attempt_id")
                or "",
                "operation_id": att["operation_id"],
                "attempt_number": int(att.get("attempt_number") or 1),
                "attempt_kind": att.get("attempt_kind", "transform"),
                "input_fingerprint": att.get("input_fingerprint", ""),
                "capability_id": att.get("capability_id"),
                "capability_version": att.get("capability_version"),
                "handler_id": att.get("handler_id"),
                "handler_version": att.get("handler_version"),
                "options_sha256": att.get("options_sha256"),
                "status": "available"
                if att.get("outcome") == "succeeded"
                else att.get("status", att.get("outcome", "failed")),
                "error_code": att.get("error_code"),
                "input_sha256": att.get("input_sha256"),
                "input_byte_size": att.get("input_byte_size"),
                "output_sha256": att.get("output_sha256"),
                "output_byte_size": att.get("output_byte_size"),
            }
        )

    _collect_payload_bytes(paths, run_id, target_states, representations, payload_map)

    payload_index_rows = []
    binary_rows = []
    text_rows = []
    for sha, (storage_class, content) in payload_map.items():
        payload_index_rows.append(
            {
                "payload_sha256": sha,
                "storage_class": storage_class,
                "byte_size": len(content),
            }
        )
        if storage_class == "binary":
            binary_rows.append({"payload_sha256": sha, "payload_bytes": content})
        else:
            text_val = None
            try:
                text_val = content.decode("utf-8")
            except UnicodeDecodeError:
                pass
            text_rows.append(
                {
                    "payload_sha256": sha,
                    "payload_bytes": content,
                    "text_value": text_val,
                }
            )

    doc_sections: list[dict[str, Any]] = []
    doc_notes: list[dict[str, Any]] = []
    staging_root = paths.run_staging_root(run_id)
    if staging_root.is_dir():
        for candidate in staging_root.rglob("*sections.json"):
            if candidate.is_file():
                try:
                    s_data = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(s_data, list):
                        doc_sections.extend(s_data)
                    elif isinstance(s_data, dict) and "sections" in s_data:
                        doc_sections.extend(s_data["sections"])
                except Exception:
                    pass
        for candidate in staging_root.rglob("*notes.json"):
            if candidate.is_file():
                try:
                    n_data = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(n_data, list):
                        doc_notes.extend(n_data)
                    elif isinstance(n_data, dict) and "notes" in n_data:
                        doc_notes.extend(n_data["notes"])
                except Exception:
                    pass

    return {
        "accession_ciks": _to_table(
            "accession_ciks",
            [{"accession": k, "cik": v} for k, v in accession_ciks.items()],
        ),
        "source_assets": _to_table("source_assets", list(source_assets.values())),
        "acquisition_slots": _to_table("acquisition_slots", acquisition_slots),
        "slot_types": _to_table("slot_types", slot_types),
        "logical_documents": _to_table(
            "logical_documents", list(logical_docs.values())
        ),
        "target_results": _to_table("target_results", target_results),
        "target_slot_selections": _to_table(
            "target_slot_selections", target_slot_selections
        ),
        "acquisition_attempts": _to_table("acquisition_attempts", acq_attempts),
        "source_payloads": _to_table(
            "source_payloads",
            [{"source_asset_id": k, "payload_sha256": v} for k, v in source_payloads],
        ),
        "operation_results": _to_table("operation_results", op_results),
        "operation_attempts": _to_table("operation_attempts", op_attempts),
        "representations": _to_table("representations", representations),
        "representation_inputs": _to_table(
            "representation_inputs", representation_inputs
        ),
        "payload_index": _to_table("payload_index", payload_index_rows),
        "binary_payloads": _to_table("binary_payloads", binary_rows),
        "text_payloads": _to_table("text_payloads", text_rows),
        "document_sections": _to_table("document_sections", doc_sections),
        "document_notes": _to_table("document_notes", doc_notes),
    }


def _collect_payload_bytes(
    paths: AcquisitionPaths,
    run_id: str,
    target_states: dict[str, dict[str, Any]],
    representations: list[dict[str, Any]],
    payload_map: dict[str, tuple[str, bytes]],
) -> None:
    staging_root = paths.run_staging_root(run_id)
    for state in target_states.values():
        sha = state.get("selected_sha256")
        rel_file = state.get("selected_body_relative_path") or state.get(
            "selected_file"
        )
        if sha and rel_file:
            path = (
                paths.run_dir(run_id) / rel_file
                if str(rel_file).startswith("staging/")
                else staging_root / rel_file
            )
            if path.is_file():
                data = path.read_bytes()
                if sha256_bytes(data) == sha:
                    payload_map[sha] = ("text", data)

    for rep in representations:
        sha = rep["output_sha256"]
        if sha not in payload_map:
            for candidate in staging_root.rglob(f"*{sha}*"):
                if candidate.is_file():
                    data = candidate.read_bytes()
                    if sha256_bytes(data) == sha:
                        payload_map[sha] = ("text", data)
                        break


def _to_table(name: str, rows: list[dict[str, Any]]) -> pa.Table:
    schema = SNAPSHOT_RELATION_SCHEMAS[name]
    if not rows:
        return pa.Table.from_batches([], schema=schema)
    arrays = []
    for field in schema:
        values = [row.get(field.name) for row in rows]
        arrays.append(pa.array(values, type=field.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def _validate_referential_integrity(tables: dict[str, pa.Table]) -> None:
    payload_index_shas = (
        set(tables["payload_index"].column("payload_sha256").to_pylist())
        if tables["payload_index"].num_rows > 0
        else set()
    )

    for row in tables["source_payloads"].to_pylist():
        sha = row["payload_sha256"]
        if sha not in payload_index_shas:
            raise ReferentialIntegrityError(
                f"source payload missing from payload_index: {sha}"
            )

    for row in tables["representations"].to_pylist():
        sha = row["output_sha256"]
        if sha not in payload_index_shas:
            raise ReferentialIntegrityError(
                f"representation output missing from payload_index: {sha}"
            )


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)
