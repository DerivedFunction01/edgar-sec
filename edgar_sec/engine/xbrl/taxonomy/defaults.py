"""Presumed-coordinate defaults: values for axes an identity leaves silent."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import (
        PrimeHead,
        SubatomicModifier,
    )


@dataclass(frozen=True, slots=True)
class DefaultCoordinate:
    """A presumed axis value for an identity signature silent on that axis."""

    head: str
    identity_modifiers: tuple[str, ...]
    axis: str
    presumed_modifier: str
    rationale: str
    attestation_class: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DefaultCoordinate:
        """Create a DefaultCoordinate from raw dictionary mapping."""
        raw_identity = data.get("identity_modifiers", ())
        identity = (
            tuple(str(m) for m in raw_identity)
            if isinstance(raw_identity, (list, tuple))
            else ()
        )
        return cls(
            head=str(data["head"]),
            identity_modifiers=identity,
            axis=str(data["axis"]),
            presumed_modifier=str(data["presumed_modifier"]),
            rationale=str(data.get("rationale", "")),
            attestation_class=str(data.get("attestation_class", "")),
        )

    @property
    def signature(self) -> tuple[str, frozenset[str]]:
        """Identity signature this default keys on: head plus identity modifiers."""
        return self.head, frozenset(self.identity_modifiers)


def load_default_coordinates(source: Path) -> tuple[DefaultCoordinate, ...]:
    """Load presumed-coordinate defaults taxonomy from JSON or CSV file."""
    if source.suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"expected list of records in {source}")
        records = [dict(item) for item in payload]
    else:
        delimiter = "\t" if source.suffix == ".tsv" else ","
        with source.open("r", encoding="utf-8", newline="") as f:
            records = [dict(row) for row in csv.DictReader(f, delimiter=delimiter)]
    return tuple(DefaultCoordinate.from_dict(row) for row in records)


def load_defaults(
    source: Path,
    heads_source: Path,
    modifiers_source: Path,
    lexicon: TokenLexicon | None,
) -> tuple[DefaultCoordinate, ...]:
    """Load the taxonomy's defaults file when present, validating every record."""
    if not source.is_file():
        return ()
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import (
        load_prime_heads,
        load_subatomic_modifiers,
    )

    defaults = load_default_coordinates(source)
    validate_default_coordinates(
        defaults,
        load_prime_heads(heads_source),
        load_subatomic_modifiers(modifiers_source),
        lexicon,
    )
    return defaults


def validate_default_coordinates(
    defaults: tuple[DefaultCoordinate, ...],
    heads: tuple[PrimeHead, ...],
    modifiers: tuple[SubatomicModifier, ...],
    lexicon: TokenLexicon | None,
) -> None:
    """Reject defaults naming an unknown head, modifier, or lexicon identity."""
    head_ids = {h.head_id for h in heads}
    defs = {m.modifier_id: m for m in modifiers}
    claimed: set[str] = set()
    if lexicon is not None:
        for entry in lexicon.entries:
            claimed.update(entry.asserted_modifier_ids())
    seen: set[tuple[str, frozenset[str]]] = set()
    for entry in defaults:
        if entry.head not in head_ids:
            raise ValueError(f"default coordinate names unknown head {entry.head}")
        if entry.presumed_modifier not in defs:
            raise ValueError(
                f"default coordinate names unknown modifier {entry.presumed_modifier}"
            )
        if entry.axis not in defs[entry.presumed_modifier].sibling_groups:
            raise ValueError(
                f"presumed modifier {entry.presumed_modifier} is not in axis "
                f"{entry.axis}"
            )
        for modifier_id in entry.identity_modifiers:
            if modifier_id not in defs:
                raise ValueError(
                    f"default coordinate names unknown modifier {modifier_id}"
                )
            if entry.axis in defs[modifier_id].sibling_groups:
                raise ValueError(
                    f"identity modifier {modifier_id} belongs to axis {entry.axis}"
                )
            if lexicon is not None and modifier_id not in claimed:
                raise ValueError(
                    f"identity modifier {modifier_id} is claimed by no lexicon entry"
                )
        if entry.signature in seen:
            raise ValueError(f"duplicate default coordinate for {entry.signature}")
        seen.add(entry.signature)
