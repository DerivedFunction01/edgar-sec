"""Verified staged-body references and immutable consumption receipts."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import cast

from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    RunStateError,
    get_target_state,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    BodyConsumptionReceipt,
    RECEIPT_SCHEMA_VERSION,
    StagedBodyRef,
)

_RECEIPT_FIELDS = frozenset(
    {
        "receipt_schema_version",
        "run_id",
        "target_id",
        "source_response_sha256",
        "selected_sha256",
        "processing_run_id",
        "consumed_at_utc",
    }
)


class BodyHandoffError(ValueError):
    pass


def _verified_relative_path(
    paths: AcquisitionPaths, run_id: str, relative_path: str, label: str
) -> Path:
    relative = PurePosixPath(relative_path)
    if (
        not relative_path
        or "\\" in relative_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise BodyHandoffError(f"{label} path is invalid")
    staging_root = paths.run_staging_root(run_id)
    run_root = paths.run_dir(run_id)
    if run_root.is_symlink() or staging_root.is_symlink() or not staging_root.is_dir():
        raise BodyHandoffError("run staging directory is unsafe")
    try:
        staging_resolved = staging_root.resolve(strict=True)
        candidate = run_root.joinpath(*relative.parts)
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(staging_resolved):
            raise BodyHandoffError(f"{label} path escapes run staging")
        cursor = run_root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise BodyHandoffError(f"{label} path contains a symlink")
        file_stat = candidate.lstat()
    except (OSError, RuntimeError) as error:
        raise BodyHandoffError(f"{label} file is missing or inaccessible") from error
    if not stat.S_ISREG(file_stat.st_mode):
        raise BodyHandoffError(f"{label} path is not a regular file")
    return candidate


def _hash_file(path: Path, label: str) -> tuple[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise BodyHandoffError(f"{label} file is unavailable") from error
    digest = hashlib.sha256()
    size = 0
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BodyHandoffError(f"{label} path is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(DEFAULT_IO_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


def _state(paths: AcquisitionPaths, run_id: str, target_id: str) -> TargetState:
    try:
        validate_safe_id(run_id, "run_id")
        validate_safe_id(target_id, "target_id")
        state = get_target_state(paths.run_state_path(run_id), target_id)
    except (OSError, ValueError, sqlite3.Error, RunStateError) as error:
        raise BodyHandoffError(str(error)) from error
    if state is None or state.outcome != "acquired":
        raise BodyHandoffError("run target is not acquired")
    if (
        not is_sha256_hex_digest(state.source_sha256)
        or type(state.source_byte_size) is not int
        or state.source_byte_size < 0
        or not is_sha256_hex_digest(state.selected_sha256)
        or type(state.selected_byte_size) is not int
        or state.selected_byte_size < 0
    ):
        raise BodyHandoffError("acquired target has incomplete body identity")
    return state


def get_staged_body_ref(
    paths: AcquisitionPaths, run_id: str, target_id: str
) -> StagedBodyRef:
    state = _state(paths, run_id, target_id)
    if state.selected_body_relative_path is None:
        raise BodyHandoffError("acquired target has no selected-body path")
    selected_path = _verified_relative_path(
        paths, run_id, state.selected_body_relative_path, "selected body"
    )
    selected_digest, selected_size = _hash_file(selected_path, "selected body")
    if (selected_digest, selected_size) != (
        state.selected_sha256,
        state.selected_byte_size,
    ):
        raise BodyHandoffError("selected body does not match committed identity")

    source_path = None
    if state.source_body_relative_path is not None:
        source_path = _verified_relative_path(
            paths, run_id, state.source_body_relative_path, "source response"
        )
        source_digest, source_size = _hash_file(source_path, "source response")
        if (source_digest, source_size) != (
            state.source_sha256,
            state.source_byte_size,
        ):
            raise BodyHandoffError("source response does not match committed identity")

    return StagedBodyRef(
        run_id=run_id,
        target_id=target_id,
        path=selected_path,
        sha256=state.selected_sha256,
        byte_size=state.selected_byte_size,
        selected_filename=None,
        source_response_path=source_path,
        source_response_sha256=state.source_sha256,
        source_response_byte_size=state.source_byte_size,
    )


def _validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise BodyHandoffError("receipt timestamp must be an ISO-8601 UTC value")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as error:
        raise BodyHandoffError(
            "receipt timestamp must be an ISO-8601 UTC value"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise BodyHandoffError("receipt timestamp must use UTC")
    return value


def _validate_receipt(
    paths: AcquisitionPaths,
    receipt: Mapping[str, object],
) -> BodyConsumptionReceipt:
    if set(receipt) != _RECEIPT_FIELDS:
        raise BodyHandoffError("receipt fields do not match the supported schema")
    run_id = receipt.get("run_id")
    target_id = receipt.get("target_id")
    processing_run_id = receipt.get("processing_run_id")
    if not isinstance(run_id, str) or not isinstance(target_id, str):
        raise BodyHandoffError("receipt run and target IDs must be strings")
    if not isinstance(processing_run_id, str):
        raise BodyHandoffError("receipt processing_run_id must be a string")
    try:
        validate_safe_id(processing_run_id, "processing_run_id")
    except ValueError as error:
        raise BodyHandoffError(str(error)) from error
    if receipt.get("receipt_schema_version") != RECEIPT_SCHEMA_VERSION:
        raise BodyHandoffError("unsupported receipt schema version")
    source_digest = receipt.get("source_response_sha256")
    selected_digest = receipt.get("selected_sha256")
    if not is_sha256_hex_digest(source_digest) or not is_sha256_hex_digest(
        selected_digest
    ):
        raise BodyHandoffError("receipt body digests are invalid")
    state = _state(paths, run_id, target_id)
    if (source_digest, selected_digest) != (state.source_sha256, state.selected_sha256):
        raise BodyHandoffError("receipt identity does not match acquired target")
    timestamp = _validate_timestamp(receipt.get("consumed_at_utc"))
    return cast(
        BodyConsumptionReceipt,
        {
            "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
            "run_id": run_id,
            "target_id": target_id,
            "source_response_sha256": source_digest,
            "selected_sha256": selected_digest,
            "processing_run_id": processing_run_id,
            "consumed_at_utc": timestamp,
        },
    )


def _receipt_directory(
    paths: AcquisitionPaths,
    run_id: str,
    target_id: str,
    *,
    create: bool,
) -> Path | None:
    run_root = paths.run_dir(run_id)
    if run_root.is_symlink() or not run_root.is_dir():
        raise BodyHandoffError("run directory is unsafe")
    directory = run_root
    for part in ("handoff", "receipts", target_id):
        directory = directory / part
        if directory.is_symlink():
            raise BodyHandoffError("receipt directory contains a symlink")
        if not directory.exists():
            if not create:
                return None
            directory.mkdir(exist_ok=True)
        if not directory.is_dir():
            raise BodyHandoffError("receipt directory is unsafe")
    return directory


def _read_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise BodyHandoffError("receipt sidecar is unsafe") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BodyHandoffError("receipt sidecar is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(16385)
    finally:
        os.close(descriptor)
    if len(data) > 16384:
        raise BodyHandoffError("receipt sidecar exceeds its size limit")
    return data


def read_body_consumption_receipt(
    paths: AcquisitionPaths, run_id: str, target_id: str
) -> BodyConsumptionReceipt | None:
    state = _state(paths, run_id, target_id)
    directory = _receipt_directory(paths, run_id, target_id, create=False)
    if directory is None:
        return None
    receipt_path = paths.body_consumption_receipt_path(
        run_id, target_id, state.selected_sha256
    )
    if receipt_path.parent != directory:
        raise BodyHandoffError("receipt path does not match its owner directory")
    if receipt_path.is_symlink():
        raise BodyHandoffError("receipt sidecar is unsafe")
    if not receipt_path.exists():
        return None
    try:
        data = _read_bytes(receipt_path)
        decoded = json.loads(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BodyHandoffError("receipt sidecar is corrupt") from error
    if not isinstance(decoded, dict):
        raise BodyHandoffError("receipt sidecar is corrupt")
    validated = _validate_receipt(paths, decoded)
    if data != canonical_json(validated).encode("utf-8"):
        raise BodyHandoffError("receipt sidecar is not canonical")
    return validated


def record_body_consumption_receipt(
    paths: AcquisitionPaths, receipt: Mapping[str, object]
) -> BodyConsumptionReceipt:
    validated = _validate_receipt(paths, receipt)
    run_id = validated["run_id"]
    target_id = validated["target_id"]
    destination = paths.body_consumption_receipt_path(
        run_id, target_id, validated["selected_sha256"]
    )
    directory = _receipt_directory(paths, run_id, target_id, create=True)
    if directory is None:
        raise BodyHandoffError("receipt directory could not be created")
    if destination.parent != directory:
        raise BodyHandoffError("receipt path does not match its owner directory")
    encoded = canonical_json(validated).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".receipt-", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
            if os.name == "posix":
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)

    readback = read_body_consumption_receipt(paths, run_id, target_id)
    if readback != validated:
        raise BodyHandoffError("conflicting immutable consumption receipt")
    return readback


__all__ = [
    "BodyHandoffError",
    "get_staged_body_ref",
    "read_body_consumption_receipt",
    "record_body_consumption_receipt",
]
