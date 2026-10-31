"""Execute independent processing operations over verified source bytes."""

from __future__ import annotations

from dataclasses import dataclass
import re
from edgar_sec.domain.document.path_facts import (
    DocumentPathFacts,
    DocumentPathShape,
)
from edgar_sec.domain.document.route import (
    content_route,
    document_route,
)
from edgar_sec.engine.document.screening import (
    screen_candidate_document,
    screen_specialized_xml_source,
)
from edgar_sec.engine.document_processing.acquisition_capabilities import (
    resolve_acquisition_capability,
)
from edgar_sec.engine.document_processing.capabilities import (
    HandlerOutputKind,
    operation_output_kind,
)
from edgar_sec.engine.document_processing.registry import (
    DEFAULT_HANDLER_REGISTRY,
    HandlerContext,
    HandlerRegistry,
)
from edgar_sec.engine.document_processing.outputs import (
    HandlerOutput,
    HandlerSidecar,
    ProducedSidecar,
)
from edgar_sec.foundation.hashing import sha256_bytes

_SIDECAR_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


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
    form_type: str
    role: str
    target_type: str
    path_facts: DocumentPathFacts
    operations: tuple[OperationRecord, ...]
    inputs: tuple[InputRecord, ...]
    include_analysis_artifacts: bool = False
    filing_date: str | None = None
    report_date: str | None = None


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
    sidecar_outputs: tuple[ProducedSidecar, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionProcessResult:
    target_id: str
    family: str
    role: str
    outcomes: tuple[OperationOutcome, ...]


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
        expected_kind = operation_output_kind(operation)
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

        route = (
            document_route(input_record.path_facts.path_context)
            if input_record.path_facts.path_shape is DocumentPathShape.NESTED
            else content_route(input_record.path_facts.path_context)
        )
        capability = resolve_acquisition_capability(
            request.family,
            request.role,
            operation,
            input_record.path_facts,
            route,
            handlers=self._registry,
        )
        registration = capability.registration
        pins = capability.pins
        if registration is None or pins is None:
            return self._outcome(operation, "unsupported", "handler_not_registered")
        if operation == "render_to_xml" and request.role == "primary":
            identity = screen_candidate_document(
                request.form_type,
                filename=input_record.path_facts.path_context,
                raw_content=input_record.raw_bytes,
            )
            structure = screen_specialized_xml_source(
                request.family, input_record.raw_bytes
            )
            if identity.is_inversion or structure.is_inversion:
                return self._outcome(
                    operation, "unsupported", "primary_document_identity_mismatch"
                )
        if (
            (
                operation_record.capability_version is not None
                and operation_record.capability_version != pins[1]
            )
            or (
                operation_record.handler_id is not None
                and operation_record.handler_id != registration.handler_id
            )
            or (
                operation_record.handler_version is not None
                and operation_record.handler_version != registration.handler_version
            )
        ):
            return self._outcome(operation, "failed", "handler_pin_mismatch")

        context = HandlerContext(
            family=request.family,
            form_type=request.form_type,
            role=request.role,
            target_type=request.target_type,
            selected_path=input_record.selected_path,
            path_facts=input_record.path_facts,
            route=route,
            include_analysis_artifacts=request.include_analysis_artifacts,
            filing_date=request.filing_date,
            report_date=request.report_date,
        )
        try:
            output = registration.handler(input_record.raw_bytes, context)
            if isinstance(output, HandlerOutput):
                primary = output.content
                sidecars = (
                    self._encode_sidecars(output.sidecars)
                    if context.include_analysis_artifacts
                    else ()
                )
            else:
                primary = output
                sidecars = ()
            output_bytes, output_text = self._encode_output(primary, expected_kind)
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
            sidecar_outputs=sidecars,
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
        if request.path_facts != input_record.path_facts:
            return "path_facts_mismatch"
        if not all(
            isinstance(value, str)
            for value in (
                request.family,
                request.form_type,
                request.role,
                request.target_type,
                input_record.selected_path,
            )
        ):
            return "invalid_request_metadata"
        if type(request.include_analysis_artifacts) is not bool:
            return "invalid_request_metadata"
        if not input_record.selected_path.strip():
            return "invalid_selected_path"
        if input_record.path_facts.path_context != input_record.selected_path:
            return "selected_path_facts_mismatch"
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
    def _encode_sidecars(
        sidecars: tuple[HandlerSidecar, ...],
    ) -> tuple[ProducedSidecar, ...]:
        output = []
        seen: set[str] = set()
        for sidecar in sidecars:
            if (
                not _SIDECAR_NAME_RE.fullmatch(sidecar.name)
                or sidecar.name in {".", ".."}
                or "/" in sidecar.name
                or "\\" in sidecar.name
                or sidecar.name in seen
            ):
                raise ValueError("handler sidecar name is invalid or duplicated")
            seen.add(sidecar.name)
            if isinstance(sidecar.content, str):
                content = sidecar.content.encode("utf-8")
            elif isinstance(sidecar.content, bytes):
                content = sidecar.content
            else:
                raise TypeError("handler sidecar must contain str or bytes")
            output.append(
                ProducedSidecar(
                    name=sidecar.name,
                    content=content,
                    sha256=sha256_bytes(content),
                    byte_size=len(content),
                )
            )
        return tuple(output)

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
            sidecar_outputs=(),
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
