from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.document.path_facts import (
    DocumentPathFacts,
    DocumentPathShape,
    DocumentSuffixClass,
)
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
from edgar_sec.engine.document_processing.capabilities import get_capability
from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.runtime.resources import (
    available_memory_bytes,
    usable_memory_bytes,
)
from edgar_sec.infra.storage.atomic import atomic_write_bytes
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing_models import (
    OperationRequest,
    OperationResult,
    ProcessingRequest,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.schemas import StagedBodyRef


class ProcessingIOError(ValueError):
    pass


class ProcessingBudgetExceeded(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessingBudgetPolicy:
    budget_version: str
    route: DocumentRoute
    handler_id: str
    handler_version: str
    max_input_bytes: int
    max_output_bytes: int
    working_set_reservation_bytes: int

    def __post_init__(self) -> None:
        validate_safe_id(self.budget_version, "budget_version")
        validate_safe_id(self.handler_id, "handler_id")
        validate_safe_id(self.handler_version, "handler_version")
        if not isinstance(self.route, DocumentRoute):
            raise ValueError("processing budget route is invalid")
        limits = (
            self.max_input_bytes,
            self.max_output_bytes,
            self.working_set_reservation_bytes,
        )
        if any(type(value) is not int or value < 0 for value in limits):
            raise ValueError("processing budget byte limits must be finite integers")
        if self.max_input_bytes == 0 or self.max_output_bytes == 0:
            raise ValueError("processing input and output limits must be positive")


@dataclass(frozen=True, slots=True)
class ProcessingBudgetRegistry:
    policies: tuple[ProcessingBudgetPolicy, ...] = ()

    def __post_init__(self) -> None:
        keys = [
            (policy.route, policy.handler_id, policy.handler_version)
            for policy in self.policies
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("processing budget policy keys must be unique")

    def get(
        self, route: DocumentRoute, handler_id: str, handler_version: str
    ) -> ProcessingBudgetPolicy | None:
        return next(
            (
                policy
                for policy in self.policies
                if (policy.route, policy.handler_id, policy.handler_version)
                == (route, handler_id, handler_version)
            ),
            None,
        )


DEFAULT_PROCESSING_BUDGETS = ProcessingBudgetRegistry()


def select_operation_execution(
    request: ProcessingRequest,
    prior_results: tuple[OperationResult, ...] | None,
    selected_operation_ids: tuple[str, ...] | None,
) -> tuple[dict[str, OperationResult], frozenset[str]]:
    prior = () if prior_results is None else prior_results
    if type(prior) is not tuple or (
        selected_operation_ids is not None and type(selected_operation_ids) is not tuple
    ):
        raise ProcessingIOError("operation reuse selections must be tuples")
    by_id = {operation.operation_id: operation for operation in request.operations}
    if len(by_id) != len(request.operations):
        raise ProcessingIOError("operation request IDs are not unique")
    eligible = {
        operation.operation_id
        for operation in request.operations
        if operation.requested and operation.support_status == "supported"
    }
    prior_by_id: dict[str, OperationResult] = {}
    for result in prior:
        if not isinstance(result, OperationResult):
            raise ProcessingIOError("prior operation result type is invalid")
        operation_id = result.operation_id
        if not isinstance(operation_id, str):
            raise ProcessingIOError("prior operation result ID is invalid")
        if operation_id in prior_by_id:
            raise ProcessingIOError("prior operation result IDs are duplicated")
        if operation_id not in by_id:
            raise ProcessingIOError("prior operation result ID is unknown")
        if operation_id not in eligible:
            raise ProcessingIOError(
                "prior result is not for a requested supported operation"
            )
        if result.status not in {"available", "failed", "blocked"}:
            raise ProcessingIOError("prior operation result is not terminal")
        if by_id[operation_id].operation == "raw" and result.status != "available":
            raise ProcessingIOError("prior mandatory raw operation is unavailable")
        prior_by_id[operation_id] = result

    if selected_operation_ids is None:
        selected = eligible - prior_by_id.keys()
    else:
        if any(
            not isinstance(operation_id, str) for operation_id in selected_operation_ids
        ):
            raise ProcessingIOError("selected operation ID is invalid")
        selected = set(selected_operation_ids)
        if len(selected) != len(selected_operation_ids):
            raise ProcessingIOError("selected operation IDs are duplicated")
        if not selected <= by_id.keys():
            raise ProcessingIOError("selected operation ID is unknown")
        if not selected <= eligible:
            raise ProcessingIOError("selected operation is not requested and supported")
    if selected & prior_by_id.keys():
        raise ProcessingIOError("operation cannot be both selected and reused")
    if selected | prior_by_id.keys() != eligible:
        raise ProcessingIOError("requested operations lack execution or prior coverage")
    return prior_by_id, frozenset(selected)


def operation_fingerprint(
    request: ProcessingRequest,
    operation: OperationRequest,
    body: StagedBodyRef,
    route: DocumentRoute,
    effective_path: str,
    budget: ProcessingBudgetPolicy | None,
) -> str:
    return canonical_hash(
        {
            "operation_id": operation.operation_id,
            "operation": operation.operation,
            "requested": operation.requested,
            "support_status": operation.support_status,
            "source_request_id": operation.source_request_id,
            "capability_id": operation.capability_id,
            "capability_version": operation.capability_version,
            "handler_id": operation.handler_id,
            "handler_version": operation.handler_version,
            "output_kind": operation.output_kind,
            "target_id": request.target_id,
            "accession": str(request.accession),
            "form": request.form,
            "target_role": request.target_role,
            "target_type": request.target_type,
            "document_path": request.document_path,
            "selected_filename": request.selected_filename,
            "source_origin": request.source_origin,
            "source_sha256": body.sha256,
            "source_byte_size": body.byte_size,
            "source_response_sha256": body.source_response_sha256,
            "source_response_byte_size": body.source_response_byte_size,
            "body_path": body.path.as_posix(),
            "source_response_path": (
                body.source_response_path.as_posix()
                if body.source_response_path is not None
                else None
            ),
            "effective_path": effective_path,
            "route": route.value,
            "processing_budget": _budget_identity(budget),
        }
    )


def _budget_identity(policy: ProcessingBudgetPolicy | None) -> dict[str, object] | None:
    if policy is None:
        return None
    return {
        "budget_version": policy.budget_version,
        "route": policy.route.value,
        "handler_id": policy.handler_id,
        "handler_version": policy.handler_version,
        "max_input_bytes": policy.max_input_bytes,
        "max_output_bytes": policy.max_output_bytes,
        "working_set_reservation_bytes": policy.working_set_reservation_bytes,
    }


def validate_prior_operation_result(
    paths: AcquisitionPaths,
    operation: OperationRequest,
    result: OperationResult,
    body: StagedBodyRef,
    processing_id: str,
    fingerprint: str,
    budget: ProcessingBudgetPolicy | None,
) -> None:
    if result.operation_fingerprint != fingerprint:
        raise ProcessingIOError("prior operation fingerprint is stale")
    if result.status not in {"available", "failed", "blocked"}:
        raise ProcessingIOError("prior operation result is not reusable")
    if result.status != "available":
        if (
            result.representation_id is not None
            or result.output_sha256 is not None
            or result.output_size is not None
            or result.handler_id is not None
            or result.handler_version is not None
            or result.staged_output is not None
        ):
            raise ProcessingIOError("failed prior result contains output metadata")
        return
    if result.diagnostics:
        raise ProcessingIOError("available prior result contains failure diagnostics")

    expected_representation = (
        "raw"
        if operation.operation == "raw"
        else "text_normalized"
        if operation.output_kind == "text"
        else "xml"
    )
    expected_handler = (
        operation.handler_id,
        operation.handler_version,
    )
    expected_representation_id = (
        f"rep_{canonical_hash([fingerprint, expected_representation])[:32]}"
    )
    output = result.staged_output
    if (
        output is None
        or result.representation_id != expected_representation_id
        or result.output_sha256 != output.output_sha256
        or result.output_size != output.output_size
        or (result.handler_id, result.handler_version) != expected_handler
        or output.representation != expected_representation
        or output.staging_id != processing_id
        or not is_sha256_hex_digest(output.output_sha256)
        or type(output.output_size) is not int
        or output.output_size < 0
        or type(result.output_size) is not int
    ):
        raise ProcessingIOError("prior available result metadata is invalid")

    if operation.operation == "raw":
        if (
            output.path != body.path
            or output.output_sha256 != body.sha256
            or output.output_size != body.byte_size
        ):
            raise ProcessingIOError("prior raw reference differs from selected body")
        return

    if budget is None or output.output_size > budget.max_output_bytes:
        raise ProcessingIOError("prior derived output has no matching budget")
    expected_path = (
        paths.run_staging_root(body.run_id)
        / "processing"
        / processing_id
        / f"{canonical_hash(operation.operation_id)[:24]}-{output.output_sha256}.bin"
    )
    if output.path != expected_path:
        raise ProcessingIOError("prior derived output path is stale")
    run_path = paths.run_dir(body.run_id)
    staging_root = paths.run_staging_root(body.run_id)
    if run_path.is_symlink() or staging_root.is_symlink():
        raise ProcessingIOError("prior derived output root is unsafe")
    try:
        run_root = run_path.resolve(strict=True)
        staging_resolved = staging_root.resolve(strict=True)
        output_resolved = output.path.resolve(strict=True)
        output_stat = output.path.lstat()
    except OSError as error:
        raise ProcessingIOError("prior derived output is unavailable") from error
    cursor = run_path
    relative_parts = output.path.relative_to(run_path).parts
    if any((cursor := cursor / part).is_symlink() for part in relative_parts):
        raise ProcessingIOError("prior derived output path contains a symlink")
    if (
        not staging_resolved.is_relative_to(run_root)
        or not output_resolved.is_relative_to(
            staging_resolved / "processing" / processing_id
        )
        or output.path.is_symlink()
        or not stat.S_ISREG(output_stat.st_mode)
        or output_stat.st_size != output.output_size
        or file_sha256(output.path) != output.output_sha256
    ):
        raise ProcessingIOError("prior derived output failed path or digest validation")


def operation_pins(
    operation: OperationRequest,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    return (
        operation.capability_id,
        operation.capability_version,
        operation.handler_id,
        operation.handler_version,
        operation.output_kind,
    )


def expected_operation_pins(
    request: ProcessingRequest,
    operation: OperationRequest,
    facts: DocumentPathFacts,
) -> tuple[str, str, str, str, str] | None:
    if operation.operation == "raw":
        descriptor = get_capability("raw_identity")
        if not operation.capability_id or descriptor is None:
            return None
        return (
            operation.capability_id,
            "v1",
            "raw_identity",
            descriptor.handler_version if descriptor else "",
            descriptor.output_kind.value if descriptor else "raw_bytes",
        )

    profile = get_family_profile(request.form)
    if profile is None:
        return None
    capability_id = handler_id = output_kind = None
    if operation.operation == "render_to_txt":
        if facts.suffix_class is DocumentSuffixClass.TEXT:
            capability_id = "text.plain"
        elif facts.suffix_class is DocumentSuffixClass.MARKUP:
            capability_id = "text.markup"
        elif (
            facts.suffix_class is DocumentSuffixClass.XML
            and facts.path_shape is DocumentPathShape.NESTED
            and facts.path_context.split("/", 1)[0].casefold().startswith("xsl")
        ):
            capability_id = "text.rendered_markup"
        handler_id = "normalize_document"
        output_kind = "text"
    elif operation.operation == "render_to_xml":
        family = resolve_alias(request.form)
        if (
            family == "4"
            and request.target_role == "primary"
            and facts.suffix == ".htm"
            and facts.suffix_class is DocumentSuffixClass.MARKUP
        ):
            capability_id = "form4.htm.render_to_xml"
            handler_id = "form4_html_to_xml"
            output_kind = "xml"
    if (
        capability_id is None
        or AcquisitionOperation(operation.operation) not in profile.allowed_operations
    ):
        return None
    descriptor = get_capability(handler_id or "")
    if (
        descriptor is None
        or descriptor.operation != operation.operation
        or descriptor.output_kind.value != output_kind
    ):
        return None
    return (
        capability_id,
        profile.version,
        descriptor.handler_id,
        descriptor.handler_version,
        descriptor.output_kind.value,
    )


def resolve_requested_operation_budgets(
    request: ProcessingRequest,
    route: DocumentRoute,
    facts: DocumentPathFacts,
    registry: ProcessingBudgetRegistry,
) -> dict[str, ProcessingBudgetPolicy]:
    policies: dict[str, ProcessingBudgetPolicy] = {}
    for operation in request.operations:
        if (
            not operation.requested
            or operation.support_status != "supported"
            or operation.operation == "raw"
            or not (operation.source_request_id or "").strip()
        ):
            continue
        expected = expected_operation_pins(request, operation, facts)
        if expected is None or operation_pins(operation) != expected:
            continue
        policy = registry.get(
            route, operation.handler_id or "", operation.handler_version or ""
        )
        if policy is not None:
            policies[operation.operation_id] = policy
    return policies


def admit_requested_operations(
    request: ProcessingRequest,
    facts: DocumentPathFacts,
    input_size: int,
    selected_operation_ids: frozenset[str],
    budget_profiles: dict[str, ProcessingBudgetPolicy],
) -> tuple[dict[str, ProcessingBudgetPolicy], dict[str, str]]:
    policies: dict[str, ProcessingBudgetPolicy] = {}
    failures: dict[str, str] = {}
    available = None
    for operation in request.operations:
        if (
            operation.operation_id not in selected_operation_ids
            or not operation.requested
            or operation.support_status != "supported"
            or operation.operation == "raw"
            or not (operation.source_request_id or "").strip()
        ):
            continue
        expected = expected_operation_pins(request, operation, facts)
        if expected is None or operation_pins(operation) != expected:
            continue
        policy = budget_profiles.get(operation.operation_id)
        if policy is None:
            failures[operation.operation_id] = (
                "no versioned budget is registered for this route and handler"
            )
            continue
        if available is None:
            available = available_memory_bytes()
        if not admit_processing_budget(policy, input_size, available_bytes=available):
            failures[operation.operation_id] = (
                "input or working set exceeds the registered processing budget"
            )
            continue
        policies[operation.operation_id] = policy
    return policies, failures


def admit_processing_budget(
    policy: ProcessingBudgetPolicy,
    input_size: int,
    *,
    available_bytes: int | None = None,
) -> bool:
    if type(input_size) is not int or input_size < 0:
        return False
    if input_size > policy.max_input_bytes:
        return False
    available = available_memory_bytes() if available_bytes is None else available_bytes
    usable = usable_memory_bytes(
        available, reserve_bytes=policy.working_set_reservation_bytes
    )
    return policy.max_input_bytes + policy.max_output_bytes <= usable


def read_bounded_source(
    path: Path,
    expected_size: int,
    *,
    max_input_bytes: int,
) -> bytes:
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
    ):
        raise ProcessingIOError("selected source size is invalid")
    if type(max_input_bytes) is not int or max_input_bytes < 1:
        raise ProcessingIOError("selected source has no finite input budget")
    if expected_size > max_input_bytes:
        raise ProcessingBudgetExceeded("selected source exceeds its input budget")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ProcessingIOError("selected source is unavailable") from error
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size != expected_size:
            raise ProcessingIOError("selected source size or file type differs")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            source = stream.read(expected_size + 1)
    finally:
        os.close(descriptor)
    if len(source) != expected_size:
        raise ProcessingIOError("selected source size differs from its pinned metadata")
    return source


def stage_derived_output(
    paths: AcquisitionPaths,
    *,
    run_id: str,
    processing_id: str,
    operation_id: str,
    representation: str,
    output: bytes,
    expected_sha256: str,
    expected_size: int,
) -> StagedOutputRef:
    validate_safe_id(run_id, "run_id")
    validate_safe_id(processing_id, "processing_id")
    validate_safe_id(operation_id, "operation_id")
    if (
        not is_sha256_hex_digest(expected_sha256)
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
        or expected_size != len(output)
        or hashlib.sha256(output).hexdigest() != expected_sha256
        or not representation
    ):
        raise ProcessingIOError("derived output metadata is invalid")
    run_path = paths.run_dir(run_id)
    if run_path.is_symlink():
        raise ProcessingIOError("run path is unsafe")
    run_root = run_path.resolve()
    staging_root = paths.run_staging_root(run_id)
    staging_root.mkdir(parents=True, exist_ok=True)
    if staging_root.is_symlink() or not staging_root.resolve().is_relative_to(run_root):
        raise ProcessingIOError("run staging path is unsafe")

    output_root = staging_root / "processing"
    if output_root.is_symlink():
        raise ProcessingIOError("processing staging path is unsafe")
    output_dir = output_root / processing_id
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink() or not output_dir.resolve().is_relative_to(
        staging_root.resolve()
    ):
        raise ProcessingIOError("processing output path is unsafe")
    output_path = output_dir / f"{operation_id}-{expected_sha256}.bin"
    if output_path.is_symlink():
        raise ProcessingIOError("derived output path is unsafe")
    atomic_write_bytes(output_path, output)
    output_stat = output_path.stat(follow_symlinks=False)
    if (
        not stat.S_ISREG(output_stat.st_mode)
        or output_stat.st_size != expected_size
        or file_sha256(output_path) != expected_sha256
    ):
        raise ProcessingIOError("staged output failed digest or size verification")
    return StagedOutputRef(
        staging_id=processing_id,
        path=output_path,
        representation=representation,
        output_sha256=expected_sha256,
        output_size=expected_size,
    )


__all__ = [
    "DEFAULT_PROCESSING_BUDGETS",
    "ProcessingBudgetExceeded",
    "ProcessingBudgetPolicy",
    "ProcessingBudgetRegistry",
    "ProcessingIOError",
    "admit_processing_budget",
    "operation_fingerprint",
    "resolve_requested_operation_budgets",
    "read_bounded_source",
    "select_operation_execution",
    "stage_derived_output",
    "validate_prior_operation_result",
]
