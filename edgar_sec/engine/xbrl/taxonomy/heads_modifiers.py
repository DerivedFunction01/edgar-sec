"""Prime heads, subatomic modifier defs, and sibling-axis groups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.taxonomy.records import read_records

MODIFIER_KINDS = ("IDENTITY", "AXIS", "STRUCTURAL", "VALUATION", "SCOPE", "CONTEXT")
AXIS_CARDINALITIES = ("exclusive", "compoundable")


@dataclass(frozen=True, slots=True)
class PrimeHead:
    """Accounting prime head representation."""

    head_id: str
    head_symbol: str
    economic_class: str
    statement_type: str
    normal_balance: str
    is_dual_role_primitive: int
    description: str
    canonical_concept: str = ""
    recognition_book: str = "B_INCOME_STATEMENT"
    flow_stock: str = "FLOW"
    timing_horizon: str = "DURATION_PERIOD"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrimeHead:
        """Create a PrimeHead from raw data; classification fields are required.

        A record omitting recognition_book, flow_stock, or
        timing_horizon is refused: data states them, loaders never infer.
        """
        head_id = str(data["head_id"])
        for field in ("recognition_book", "flow_stock", "timing_horizon"):
            if not data.get(field):
                raise ValueError(f"prime head {head_id} omits required {field}")
        return cls(
            head_id=head_id,
            head_symbol=str(data["head_symbol"]),
            economic_class=str(data["economic_class"]),
            statement_type=str(data["statement_type"]),
            normal_balance=str(data["normal_balance"]),
            is_dual_role_primitive=int(data["is_dual_role_primitive"]),
            description=str(data["description"]),
            canonical_concept=str(data.get("canonical_concept", "")),
            recognition_book=str(data["recognition_book"]),
            flow_stock=str(data["flow_stock"]),
            timing_horizon=str(data["timing_horizon"]),
        )

    def to_tuple(self) -> tuple[str, str, str, str, str, int, str]:
        """Convert into canonical raw tuple representation."""
        return (
            self.head_id,
            self.head_symbol,
            self.economic_class,
            self.statement_type,
            self.normal_balance,
            self.is_dual_role_primitive,
            self.description,
        )


def _string_tuple(raw: Any) -> tuple[str, ...]:
    """Normalize a list or delimited scalar cell into a string tuple."""
    if isinstance(raw, (list, tuple)):
        return tuple(str(v) for v in raw)
    if isinstance(raw, str):
        clean = raw.replace("|", ";").replace(",", ";")
        return tuple(v.strip() for v in clean.split(";") if v.strip())
    return ()


@dataclass(frozen=True, slots=True)
class SubatomicModifier:
    """Sub-atomic domain or valuation modifier representation."""

    modifier_id: str
    category: str
    keywords: tuple[str, ...]
    description: str
    valuation_basis: str | None = None
    realization_state: str | None = None
    sibling_groups: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    asserted_item_types: tuple[str, ...] = ()

    @property
    def pattern_keywords(self) -> tuple[str, ...]:
        return self.keywords

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubatomicModifier:
        """Create a SubatomicModifier from raw dictionary mapping."""
        return cls(
            modifier_id=str(data["modifier_id"]),
            category=str(data["category"]),
            keywords=_string_tuple(data.get("keywords", ())),
            description=str(data["description"]),
            valuation_basis=data.get("valuation_basis"),
            realization_state=data.get("realization_state"),
            sibling_groups=_string_tuple(data.get("sibling_groups", ())),
            kinds=tuple(str(k) for k in data.get("kinds", ())),
            asserted_item_types=_string_tuple(data.get("asserted_item_types", ())),
        )

    def to_tuple(self) -> tuple[str, str, tuple[str, ...], str]:
        """Convert into canonical raw tuple representation."""
        return (
            self.modifier_id,
            self.category,
            self.keywords,
            self.description,
        )


@dataclass(frozen=True, slots=True)
class ScopeContext:
    """One coordinate context a scoped sibling group's swap is confined to.

    Admission is by head and the pair's shared modifiers; an exact
    context admits only pairs whose shared set is the named set itself.
    """

    heads: tuple[str, ...] = ()
    shared_modifiers: tuple[str, ...] = ()
    shared_exact: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScopeContext:
        """Create a ScopeContext from raw dictionary mapping."""
        return cls(
            heads=tuple(str(h) for h in data.get("heads", ())),
            shared_modifiers=tuple(str(m) for m in data.get("shared_modifiers", ())),
            shared_exact=bool(data.get("shared_exact", False)),
        )

    def admits(self, head: str, shared: frozenset[str]) -> bool:
        """True when a swap on this head with these shared modifiers is in scope."""
        if self.heads and head not in self.heads:
            return False
        required = frozenset(self.shared_modifiers)
        if self.shared_exact:
            return shared == required
        return required <= shared


@dataclass(frozen=True, slots=True)
class SiblingGroup:
    """A declared sibling axis: its member modifiers and value cardinality."""

    group: str
    members: tuple[str, ...]
    cardinality: str
    exceptions: str = ""
    scope: tuple[ScopeContext, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SiblingGroup:
        """Create a SiblingGroup from raw dictionary mapping."""
        cardinality = str(data["cardinality"])
        if cardinality not in AXIS_CARDINALITIES:
            raise ValueError(
                f"sibling group {data.get('group')} has unknown cardinality"
                f" {cardinality!r}"
            )
        return cls(
            group=str(data["group"]),
            members=tuple(str(m) for m in data.get("members", ())),
            cardinality=cardinality,
            exceptions=str(data.get("exceptions", "")),
            scope=tuple(ScopeContext.from_dict(s) for s in data.get("scope", ())),
        )

    def swap_admitted(self, head: str, shared: frozenset[str]) -> bool:
        """True when this group's scope admits a swap on these coordinates.

        An unscoped group admits every coordinate; a scoped group only
        the contexts its declaration names.
        """
        if not self.scope:
            return True
        return any(context.admits(head, shared) for context in self.scope)


def load_prime_heads(source: Path) -> tuple[PrimeHead, ...]:
    """Load prime heads taxonomy from JSON, CSV, or TSV file."""
    records = read_records(source)
    return tuple(PrimeHead.from_dict(row) for row in records)


def load_subatomic_modifiers(source: Path) -> tuple[SubatomicModifier, ...]:
    """Load subatomic modifiers taxonomy from JSON, CSV, or TSV file."""
    records = read_records(source)
    return tuple(SubatomicModifier.from_dict(row) for row in records)


def load_sibling_groups(source: Path) -> tuple[SiblingGroup, ...]:
    """Load the sibling-axis groups table from a JSON file."""
    records = read_records(source)
    return tuple(SiblingGroup.from_dict(row) for row in records)
