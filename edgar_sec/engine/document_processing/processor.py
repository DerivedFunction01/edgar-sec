"""Execute independent processing operations over verified source bytes."""

from __future__ import annotations

from dataclasses import dataclass
from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import DocumentRoute, document_route
from edgar_sec.engine.document_processing.capabilities import HandlerOutputKind
from edgar_sec.engine.document_processing.registry import (
    DEFAULT_HANDLER_REGISTRY,
    HandlerContext,
    HandlerRegistry,
)
from edgar_sec.foundation.hashing import sha256_bytes


@dataclass(frozen=True, slots=True)
class InputRecord:
    source_id: str
    locator_provenance: str
    selected_path: str
    path_facts: DocumentPathFacts
    sha256: str
    byte_size: int
    raw_bytes: bytes


@dataclass(frozen=True, slots=True)
class OperationRecord:
    capability_version: str
    output_kind: str
    source_ids: tuple[str, ...]
    operation: str | None = None
    handler_id: str | None = None
    handler_version: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionProcessRequest:
    target_id: str
    family: str
    role: str
    target_type: str
    path_facts: DocumentPathFacts
    operations: tuple[OperationRecord, ...]
    inputs: tuple[InputRecord, ...]


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    operation: str
    status: str
    output_kind: str | None
    output_bytes: bytes | None
    output_text: str | None
    output_sha256: str | None
    output_byte_size: int | None
    handler_id: str | None
    handler_version: str | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionProcessResult:
    target_id: str
    family: str
    role: str
    outcomes: tuple[OperationOutcome, ...]


_OPERATION_OUTPUTS = {
    "raw": HandlerOutputKind.RAW_BYTES,
    "render_to_txt": HandlerOutputKind.TEXT,
    "render_to_xml": HandlerOutputKind.XML,
}
_TEXT_FALLBACK_ROUTES = frozenset(
    {DocumentRoute.MARKUP, DocumentRoute.RENDERED, DocumentRoute.TEXT}
)


class AcquisitionProcessor:
    def __init__(self, registry: HandlerRegistry = DEFAULT_HANDLER_REGISTRY) -> None:
        self._registry = registry

    def process(self, request: AcquisitionProcessRequest) -> AcquisitionProcessResult:
        by_id: dict[str, list[InputRecord]] = {}
        for input_record in request.inputs:
            by_id.setdefault(input_record.source_id, []).append(input_record)
        outcomes = tuple(
            self._execute_operation(request, operation, by_id)
            for operation in request.operations
        )
        return AcquisitionProcessResult(
            target_id=request.target_id,
            family=request.family,
            role=request.role,
            outcomes=outcomes,
        )

    def _execute_operation(
        self,
        request: AcquisitionProcessRequest,
        operation_record: OperationRecord,
        inputs_by_id: dict[str, list[InputRecord]],
    ) -> OperationOutcome:
        operation = operation_record.operation or {
            "raw_bytes": "raw",
            "text": "render_to_txt",
            "xml": "render_to_xml",
        }.get(operation_record.output_kind, "unknown")
        expected_kind = _OPERATION_OUTPUTS.get(operation)
        if expected_kind is None:
            return self._outcome(operation, "unsupported", "unknown_operation")
        if operation_record.output_kind != expected_kind.value:
            return self._outcome(operation, "failed", "operation_output_kind_mismatch")
        if len(operation_record.source_ids) != 1:
            return self._outcome(operation, "failed", "invalid_source_count")
        sources = inputs_by_id.get(operation_record.source_ids[0], [])
        if len(sources) != 1:
            return self._outcome(operation, "failed", "missing_or_ambiguous_source")
        input_record = sources[0]
        error = self._validate_input(request, input_record)
        if error:
            return self._outcome(operation, "failed", error)

        route = document_route(input_record.selected_path)
        registration = self._registry.resolve(operation, request.family, route)
        if (
            operation == "render_to_txt"
            and registration is not None
            and registration.handler_id == "normalize_document"
            and route not in _TEXT_FALLBACK_ROUTES
        ):
            registration = None
        if registration is None:
            return self._outcome(operation, "unsupported", "handler_not_registered")
        if (
            operation_record.handler_id is not None
            and operation_record.handler_id != registration.handler_id
        ) or (
            operation_record.handler_version is not None
            and operation_record.handler_version != registration.handler_version
        ):
            return self._outcome(operation, "failed", "handler_pin_mismatch")

        context = HandlerContext(
            family=request.family,
            role=request.role,
            target_type=request.target_type,
            selected_path=input_record.selected_path,
            path_facts=input_record.path_facts,
            route=route,
        )
        try:
            output = registration.handler(input_record.raw_bytes, context)
            output_bytes, output_text = self._encode_output(output, expected_kind)
            if operation == "raw" and output_bytes != input_record.raw_bytes:
                return self._outcome(operation, "failed", "raw_handler_changed_source")
        except Exception as error:
            return self._outcome(
                operation,
                "failed",
                f"handler_failed:{type(error).__name__}",
            )

        return OperationOutcome(
            operation=operation,
            status="ok",
            output_kind=expected_kind.value,
            output_bytes=output_bytes,
            output_text=output_text,
            output_sha256=sha256_bytes(output_bytes),
            output_byte_size=len(output_bytes),
            handler_id=registration.handler_id,
            handler_version=registration.handler_version,
        )

    @staticmethod
    def _validate_input(
        request: AcquisitionProcessRequest,
        input_record: InputRecord,
    ) -> str | None:
        if not isinstance(input_record.raw_bytes, bytes):
            return "invalid_source_bytes"
        if not isinstance(input_record.byte_size, int) or isinstance(
            input_record.byte_size, bool
        ):
            return "invalid_source_size"
        if input_record.byte_size != len(input_record.raw_bytes):
            return "source_size_mismatch"
        if input_record.sha256 != sha256_bytes(input_record.raw_bytes):
            return "source_digest_mismatch"
        if not isinstance(request.path_facts, DocumentPathFacts) or not isinstance(
            input_record.path_facts, DocumentPathFacts
        ):
            return "invalid_path_facts"
        if not all(
            isinstance(value, str)
            for value in (
                request.family,
                request.role,
                request.target_type,
                input_record.selected_path,
            )
        ):
            return "invalid_request_metadata"
        if not input_record.selected_path.strip():
            return "invalid_selected_path"
        return None

    @staticmethod
    def _encode_output(
        output: bytes | str,
        output_kind: HandlerOutputKind,
    ) -> tuple[bytes, str | None]:
        if output_kind is HandlerOutputKind.TEXT:
            if isinstance(output, str):
                return output.encode("utf-8"), output
            if isinstance(output, bytes):
                return output, output.decode("utf-8")
            raise TypeError("text handler must return str or UTF-8 bytes")
        if output_kind in {HandlerOutputKind.RAW_BYTES, HandlerOutputKind.XML}:
            if isinstance(output, bytes):
                return output, None
            if output_kind is HandlerOutputKind.XML and isinstance(output, str):
                return output.encode("utf-8"), None
        raise TypeError("byte handler returned an incompatible value")

    @staticmethod
    def _outcome(operation: str, status: str, error: str) -> OperationOutcome:
        return OperationOutcome(
            operation=operation,
            status=status,
            output_kind=None,
            output_bytes=None,
            output_text=None,
            output_sha256=None,
            output_byte_size=None,
            handler_id=None,
            handler_version=None,
            error=error,
        )


__all__ = [
    "AcquisitionProcessRequest",
    "AcquisitionProcessResult",
    "AcquisitionProcessor",
    "InputRecord",
    "OperationOutcome",
    "OperationRecord",
]
