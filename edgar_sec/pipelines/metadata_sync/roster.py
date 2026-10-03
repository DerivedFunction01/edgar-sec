"""Content-addressed CIK roster datasets.

A roster is the single canonical statement of *which* CIKs a unit of work covers.
The list lives once, in an immutable Parquet dataset with a stable ordinal, and
everything else references it by identity.

Identity is content-derived from the ordered normalized CIK list together with
its display names and the roster schema version, so reformatting an input file
produces the same roster while reordering its rows does not. That is the point:
a roster says what the cohort *is*, not which bytes a curator happened to type.

The dataset also removes the O(n) linear scan that a name lookup against a
parallel tuple performed, because names travel with their CIK and are resolved
from one map rather than by searching.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.parquet import read_parquet_schema, write_parquet_table

from .manifest import InputManifest

ROSTER_SCHEMA_VERSION = "1.0.0"
ROSTER_FILE_NAME = "ciks.parquet"
SNAPSHOT_CIK_INDEX_NAME = "ciks.parquet"
ROSTER_MANIFEST_KIND = "cik_roster"

_ID_PREFIX = "cik-roster-v1"

__all__ = [
    "ROSTER_FILE_NAME",
    "ROSTER_MANIFEST_KIND",
    "ROSTER_SCHEMA",
    "ROSTER_SCHEMA_VERSION",
    "SNAPSHOT_CIK_INDEX_NAME",
    "SNAPSHOT_CIK_INDEX_SCHEMA",
    "Roster",
    "RosterError",
    "build_roster",
    "derive_roster_id",
    "empty_roster",
    "read_cik_index",
    "read_roster",
    "roster_from_manifest",
    "roster_to_csv_text",
    "union_rosters",
    "without_ciks",
    "write_cik_index",
    "write_roster",
]

ROSTER_SCHEMA = pa.schema(
    [
        ("ordinal", pa.int64()),
        ("cik_padded", pa.string()),
        ("name", pa.string()),
    ]
)

SNAPSHOT_CIK_INDEX_SCHEMA = pa.schema([("cik", pa.string())])


class RosterError(ValueError):
    """Raised when a roster cannot be produced, stored, or verified."""


@dataclass(frozen=True, slots=True)
class Roster:
    """An ordered, deduplicated CIK cohort with a content-derived identity.

    ``names`` runs parallel to ``ciks``. Both tuples are already normalized, so
    a roster never re-parses or re-pads a CIK.
    """

    roster_id: str
    ciks: tuple[str, ...] = ()
    names: tuple[str, ...] = ()

    @property
    def row_count(self) -> int:
        """Number of CIKs in this roster."""
        return len(self.ciks)

    @property
    def is_empty(self) -> bool:
        """True when the cohort holds no CIKs at all."""
        return not self.ciks

    def name_map(self) -> dict[str, str]:
        """Curated display names keyed by CIK, built once for bulk lookup.

        Callers needing many names build this once. ``InputManifest.name_for``
        serves the single-lookup case, and a per-CIK rebuild here would restore
        the quadratic behaviour the roster exists to remove.
        """
        return dict(zip(self.ciks, self.names, strict=True))

    def cik_set(self) -> frozenset[str]:
        """Membership set for anti-joins against this roster."""
        return frozenset(self.ciks)

    def range_ciks(self, start: int, length: int) -> tuple[str, ...]:
        """CIKs for one ordinal range; chunk membership is a range, not a list."""
        if start < 0 or length < 0:
            raise RosterError(f"invalid roster range start={start} length={length}")
        return self.ciks[start : start + length]


def derive_roster_id(ciks: Sequence[str], names: Sequence[str] = ()) -> str:
    """Derive a roster identity from ordered normalized CIKs and their names.

    Hashed row by row rather than through one canonical JSON document: a
    250,000-CIK roster would otherwise materialize a multi-megabyte string, and
    identity has to stay derivable at full-corpus scale.
    """
    if len(ciks) != len(names):
        raise RosterError(
            f"roster ciks/names length mismatch: {len(ciks)} vs {len(names)}"
        )
    digest = hashlib.sha256()
    digest.update(
        canonical_json([_ID_PREFIX, ROSTER_SCHEMA_VERSION, len(ciks)]).encode("utf-8")
    )
    for ordinal, (cik, name) in enumerate(zip(ciks, names, strict=True)):
        digest.update(
            f"{ordinal}\x1f{len(cik)}\x1f{cik}\x1f{len(name)}\x1f{name}\n".encode()
        )
    return digest.hexdigest()[:32]


def build_roster(ciks: Iterable[str], names: Sequence[str] = ()) -> Roster:
    """Build a roster from already-normalized CIKs, preserving the given order."""
    ordered = tuple(ciks)
    if not ordered:
        return empty_roster()
    if len(set(ordered)) != len(ordered):
        raise RosterError("a roster must not contain duplicate CIKs")
    paired = tuple(names) if names else ("",) * len(ordered)
    return Roster(
        roster_id=derive_roster_id(ordered, paired),
        ciks=ordered,
        names=paired,
    )


def empty_roster() -> Roster:
    """The empty cohort, with a stable identity of its own.

    Augmentation has to be able to say "nothing new" without inventing an
    identity for it, and that statement must not collide with any real roster.
    """
    return Roster(roster_id=derive_roster_id((), ()), ciks=(), names=())


def roster_from_manifest(manifest: InputManifest) -> Roster:
    """Build the roster for a parsed input manifest."""
    return build_roster(manifest.ciks, manifest.names)


def without_ciks(roster: Roster, excluded: Iterable[str]) -> Roster:
    """Return the roster minus every CIK in ``excluded``, preserving order."""
    drop = set(excluded)
    kept = [
        (cik, name)
        for cik, name in zip(roster.ciks, roster.names, strict=True)
        if cik not in drop
    ]
    if not kept:
        return empty_roster()
    return build_roster([cik for cik, _ in kept], [name for _, name in kept])


def union_rosters(*rosters: Roster) -> Roster:
    """Merge rosters in first-seen order, de-duplicating by CIK."""
    order: list[str] = []
    names: dict[str, str] = {}
    for roster in rosters:
        for cik, name in zip(roster.ciks, roster.names, strict=True):
            if cik in names:
                if not names[cik] and name:
                    names[cik] = name
                continue
            order.append(cik)
            names[cik] = name
    return build_roster(order, [names[cik] for cik in order])


def _roster_table(roster: Roster) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {"ordinal": ordinal, "cik_padded": cik, "name": name}
            for ordinal, (cik, name) in enumerate(
                zip(roster.ciks, roster.names, strict=True)
            )
        ],
        schema=ROSTER_SCHEMA,
    )


def write_roster(roster: Roster, path: str | os.PathLike[str]) -> str:
    """Write one roster atomically; return the artifact's SHA-256 digest.

    The file is read back and its schema compared, so a write that silently
    produced a different layout fails here rather than at a consumer that has
    already trusted the roster identity.
    """
    target = Path(path)
    write_parquet_table(_roster_table(roster), target)
    if not read_parquet_schema(target).equals(ROSTER_SCHEMA, check_metadata=False):
        raise RosterError(f"roster dataset schema drifted: {target}")
    return file_sha256(target)


def read_roster(
    path: str | os.PathLike[str], *, expected_roster_id: str | None = None
) -> Roster:
    """Load a roster and verify its schema and, when given, its identity."""
    import pyarrow.parquet as pq

    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"roster dataset not found: {target}")
    if not read_parquet_schema(target).equals(ROSTER_SCHEMA, check_metadata=False):
        raise RosterError(f"roster dataset schema drifted: {target}")
    table = pq.read_table(target, columns=["cik_padded", "name"])
    ciks = tuple(str(value) for value in table.column("cik_padded").to_pylist())
    names = tuple(str(value or "") for value in table.column("name").to_pylist())
    roster = build_roster(ciks, names)
    if expected_roster_id is not None and roster.roster_id != expected_roster_id:
        raise RosterError(
            f"roster at {target} has identity {roster.roster_id!r}, "
            f"expected {expected_roster_id!r}"
        )
    return roster


def write_cik_index(ciks: Iterable[str], path: str | os.PathLike[str]) -> str:
    """Write a sorted distinct CIK index beside a published payload."""
    target = Path(path)
    ordered = sorted(set(ciks))
    if not ordered:
        raise RosterError("a published CIK index must not be empty")
    table = pa.Table.from_pylist(
        [{"cik": cik} for cik in ordered], schema=SNAPSHOT_CIK_INDEX_SCHEMA
    )
    write_parquet_table(table, target)
    if not read_parquet_schema(target).equals(
        SNAPSHOT_CIK_INDEX_SCHEMA, check_metadata=False
    ):
        raise RosterError(f"CIK index schema drifted: {target}")
    return file_sha256(target)


def read_cik_index(path: str | os.PathLike[str]) -> tuple[str, ...]:
    """Read a published CIK index and verify it is sorted and duplicate-free."""
    import pyarrow.parquet as pq

    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"CIK index not found: {target}")
    if not read_parquet_schema(target).equals(
        SNAPSHOT_CIK_INDEX_SCHEMA, check_metadata=False
    ):
        raise RosterError(f"CIK index schema drifted: {target}")
    ciks = tuple(
        str(value) for value in pq.read_table(target).column("cik").to_pylist()
    )
    if list(ciks) != sorted(set(ciks)):
        raise RosterError(f"CIK index is not sorted and distinct: {target}")
    return ciks


def roster_to_csv_text(roster: Roster) -> str:
    """Render a roster as the ``cik,name`` CSV that people and scripts import.

    The CSV is an export format, not the internal carrier. It exists so the
    ``cik,name`` input contract keeps working while the roster dataset is what the
    planner actually reads.
    """
    lines = ["cik,name"]
    for cik, name in zip(roster.ciks, roster.names, strict=True):
        text = str(name or "")
        if any(character in text for character in (",", '"', "\n", "\r")):
            text = '"' + text.replace('"', '""') + '"'
        lines.append(f"{cik},{text}")
    return "\n".join(lines) + "\n"
