"""Configuration specifications for pipeline runner and targeting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from edgar_sec.domain.forms.families.processing_profiles import get_family_profile

if TYPE_CHECKING:
    from edgar_sec.infra.sec_http.client import SecHttpClient


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """Target selection and filtering specification."""

    forms: tuple[str, ...] = ()
    ciks: tuple[str, ...] = ()
    dates: str | None = None
    suffixes: tuple[str, ...] = ()
    role: str = "primary"
    limit: int | None = None
    input_file: Path | str | None = None


@dataclass(frozen=True, slots=True)
class RunnerOptions:
    """Execution, transport, and concurrency options for the pipeline runner."""

    operation: str = "raw"
    family_operations: dict[str, str] = field(default_factory=dict)
    use_broker: bool = True
    workers: int | None = None
    publish_snapshot: bool = True
    sec_client: SecHttpClient | None = None
    artifacts_root: Path | None = None
    output_dir: Path | None = None

    def resolve_operation(self, family: str) -> str:
        """Resolve operation for a form family, checking overrides and capabilities."""
        if family in self.family_operations:
            return self.family_operations[family]
        if self.operation == "auto":
            profile = get_family_profile(family)
            if profile is not None:
                if profile.preferred_operation is not None:
                    return profile.preferred_operation.value
                for op in profile.allowed_operations:
                    if op.value != "raw":
                        return op.value
            return "raw"
        return self.operation


__all__ = ["RunnerOptions", "TargetSpec"]
