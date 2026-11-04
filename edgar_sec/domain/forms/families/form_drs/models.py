"""DRS wrapper document-kind vocabulary shared by domain and engine."""

from __future__ import annotations

from enum import StrEnum


class DrsKind(StrEnum):
    """Kinds inside the DRS wrapper: the draft submission itself and
    the correspondence letter variant.
    """

    SUBMISSION = "submission"
    LETTER = "letter"


__all__ = ["DrsKind"]
