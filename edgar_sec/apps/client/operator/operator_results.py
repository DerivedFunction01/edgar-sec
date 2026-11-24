from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edgar_sec.foundation.runtime.render import ProseRow, RenderComponent

__all__ = [
    "ERROR_CODES",
    "RESULT_KINDS",
    "OpResult",
]


RESULT_KINDS = frozenset({"grid", "key_value", "prose", "object"})


ERROR_CODES = frozenset(
    {
        "invalid_options",
        "missing_context",
        "unknown_operation",
        "refused",
        "not_found",
        "absent",
        "external_failure",
        "unsupported_version",
    }
)


@dataclass(frozen=True, slots=True)
class OpResult:
    """One operation outcome; ``total``/``shown`` declare the clamp, if any."""

    kind: str
    title: str = ""
    components: tuple[RenderComponent, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    shown: int = 0
    error_code: str | None = None
    hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in RESULT_KINDS:
            raise ValueError(f"unknown result kind: {self.kind!r}")
        if self.error_code is not None and self.error_code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {self.error_code!r}")
        if self.total < 0 or self.shown < 0 or self.shown > self.total:
            raise ValueError("shown must lie between 0 and total")

    def to_payload(self) -> dict[str, Any]:
        """The JSON-native rendering every operation offers."""
        message: str | None = None
        if self.error_code is not None:
            prose = next(
                (row.text for row in self.components if isinstance(row, ProseRow)),
                None,
            )
            carried = self.data.get("message")
            message = (
                prose if prose is not None else (str(carried) if carried else None)
            )
        return {
            "kind": self.kind,
            "title": self.title,
            "data": self.data,
            "total": self.total,
            "shown": self.shown,
            "error_code": self.error_code,
            "message": message,
            "hints": list(self.hints),
        }


def _error_result(
    kind: str, code: str, title: str, message: str, data: dict[str, Any] | None = None
) -> OpResult:
    return OpResult(
        kind=kind,
        title=title,
        components=(ProseRow(message),) if message else (),
        data=data or {},
        error_code=code,
    )
