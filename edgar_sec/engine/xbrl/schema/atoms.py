"""Sub-atomic coordinates and subsumption lattice algebra."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Atom:
    """Sub-atomic coordinate consisting of a prime head and modifier atoms."""

    head: str
    modifiers: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Enforce uppercase normalization for head and modifier symbols."""
        norm_head = self.head.strip().upper()
        if not norm_head.startswith("H_"):
            norm_head = f"H_{norm_head}"
        norm_mods = frozenset(m.strip().upper() for m in self.modifiers if m)
        object.__setattr__(self, "head", norm_head)
        object.__setattr__(self, "modifiers", norm_mods)

    def is_a(self, other: Atom) -> bool:
        """Return True if self is a taxonomic subtype of other in the subset lattice."""
        if self.head != other.head:
            return False
        return self.modifiers.issuperset(other.modifiers)

    def subsumes(self, other: Atom) -> bool:
        """Return True if self is a taxonomic supertype of other."""
        return other.is_a(self)

    def meet(self, other: Atom) -> Atom | None:
        """Return greatest lower bound (intersection of concepts, union of modifiers)."""
        if self.head != other.head:
            return None
        return Atom(self.head, self.modifiers | other.modifiers)

    def join(self, other: Atom) -> Atom | None:
        """Return least upper bound (union of concepts, intersection of modifiers)."""
        if self.head != other.head:
            return None
        return Atom(self.head, self.modifiers & other.modifiers)

    def to_dict(self) -> dict[str, Any]:
        """Serialize atom coordinate to JSON-compatible dictionary."""
        return {"head": self.head, "mods": sorted(self.modifiers)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Atom:
        """Construct Atom from dictionary representation."""
        head = str(data.get("head", ""))
        mods = data.get("mods") or data.get("modifiers") or []
        return cls(head=head, modifiers=frozenset(str(m) for m in mods))

    def __str__(self) -> str:
        """Return readable coordinate string representation."""
        if not self.modifiers:
            return f"({self.head}, ∅)"
        sorted_mods = ", ".join(sorted(self.modifiers))
        return f"({self.head}, {{{sorted_mods}}})"


def prune_subsumed(atoms: Iterable[Atom]) -> list[Atom]:
    """Prune general atoms when more specific subtypes are present in the collection."""
    atom_list = list(atoms)
    result: list[Atom] = []
    for candidate in atom_list:
        if not any(other != candidate and other.is_a(candidate) for other in atom_list):
            result.append(candidate)
    return result


def prune_specialized(atoms: Iterable[Atom]) -> list[Atom]:
    """Prune specialized subtypes when more general supertypes are present."""
    atom_list = list(atoms)
    result: list[Atom] = []
    for candidate in atom_list:
        if not any(other != candidate and candidate.is_a(other) for other in atom_list):
            result.append(candidate)
    return result
