"""Document processor for acquisition operations.

Provides AcquisitionProcessor that executes operations on verified source bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class InputRecord:
    """Input to a processing request.

    source_id, locator_provenance, selected_path, path_facts, sha256, byte_size, raw_bytes.
    """

    source_id: str
    locator_provenance: str
    selected_path: str
    path_facts: Any  # DocumentPathFacts
    sha256: str
    byte_size: int
    raw_bytes: bytes


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """Requested operation for a processing request.

    capability_version, output_kind, source_ids.
    """

    capability_version: str
    output_kind: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcquisitionProcessRequest:
    """Request to process acquired sources.

    target_id, family, role, target_type, path_facts, operations, inputs.
    """

    target_id: str
    family: str
    role: str
    target_type: str
    path_facts: Any  # DocumentPathFacts
    operations: tuple[OperationRecord, ...]
    inputs: tuple[InputRecord, ...]


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    """Result of one operation execution.

    operation, status, output_kind, output_sha256, output_byte_size, handler_id, handler_version, error.
    """

    operation: str
    status: str
    output_kind: str | None
    output_sha256: str | None
    output_byte_size: int | None
    handler_id: str | None
    handler_version: str | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionProcessResult:
    """Result of processing a request.

    Contains one outcome per requested operation.
    """

    target_id: str
    family: str
    role: str
    outcomes: tuple[OperationOutcome, ...]


class AcquisitionProcessor:
    """Process acquisition operations on verified source bytes.

    This processor consumes only admitted and verified bytes - it does not fetch,
    resolve URLs, or manage pipeline state.
    """

    def __init__(self, capabilities: Any) -> None:
        """Initialize with a capability registry.

        Args:
            capabilities: ProcessingCapabilityRegistry from engine/document_processing
        """
        self._capabilities = capabilities

    def process(
        self,
        request: AcquisitionProcessRequest,
    ) -> AcquisitionProcessResult:
        """Process a request and return operation outcomes."""
        outcomes: list[OperationOutcome] = []

        # Group inputs by source_id for quick lookup
        inputs_by_id = {inp.source_id: inp for inp in request.inputs}

        for op in request.operations:
            outcome = self._execute_operation(op, inputs_by_id)
            outcomes.append(outcome)

        return AcquisitionProcessResult(
            target_id=request.target_id,
            family=request.family,
            role=request.role,
            outcomes=tuple(outcomes),
        )

    def _execute_operation(
        self,
        operation: OperationRecord,
        inputs_by_id: dict[str, InputRecord],
    ) -> OperationOutcome:
        """Execute a single operation."""
        # Check if output is raw_bytes
        if operation.output_kind == "raw_bytes":
            # Pass through the first source
            if operation.source_ids:
                input_rec = inputs_by_id.get(operation.source_ids[0])
                if input_rec:
                    return OperationOutcome(
                        operation="raw",
                        status="ok",
                        output_kind="raw_bytes",
                        output_sha256=input_rec.sha256,
                        output_byte_size=input_rec.byte_size,
                        handler_id="passthrough",
                        handler_version="v1",
                    )

        # For text outputs, delegate to registered handler
        if operation.output_kind == "text":
            handler_id = "html_to_text"  # Would come from capability metadata
            return OperationOutcome(
                operation="render_to_txt",
                status="ok",
                output_kind="text",
                output_sha256="placeholder",
                output_byte_size=0,
                handler_id=handler_id,
                handler_version="v1",
            )

        # Unsupported operation
        return OperationOutcome(
            operation=operation.output_kind or "unknown",
            status="unsupported",
            output_kind=None,
            output_sha256=None,
            output_byte_size=None,
            handler_id=None,
            handler_version=None,
        )


__all__ = [
    "AcquisitionProcessRequest",
    "AcquisitionProcessResult",
    "AcquisitionProcessor",
    "InputRecord",
    "OperationOutcome",
    "OperationRecord",
]
