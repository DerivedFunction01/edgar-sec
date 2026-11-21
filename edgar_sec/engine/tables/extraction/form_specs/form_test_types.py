"""Form-test registry types: the cross-kind spec and outcome
shapes every form-test module is written against.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.profiles import PROV_DECLARED_SPECS


@dataclass(frozen=True, slots=True)
class FormTestSpec:
    """One form test as registry data: the cross-kind fields only.
    Label anchors ride here where the kind uses them; each kind's
    own parameters live in its per-kind table keyed by test_id."""

    family: str
    kind: str
    test_id: str
    points: float
    beginning: tuple[str, ...] = ()
    ending: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    provenance: str = PROV_DECLARED_SPECS


@dataclass(frozen=True, slots=True)
class FormTestOutcome:
    """One form test's evaluation over one table."""

    family: str
    test_id: str
    kind: str
    passed: bool
    evaluable: bool
    columns_closed: int
    points: float
    detail: str
