"""Base models and protocols for repository policy scanners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ScannerFinding:
    """One policy violation reported by a scanner."""

    scanner: str
    source: str
    path: str
    line: int | None
    message: str
    hint: str = ""


@dataclass(frozen=True)
class Scanner:
    """One registered repository scanner."""

    name: str
    description: str
    run: Callable[[], list[ScannerFinding]]
