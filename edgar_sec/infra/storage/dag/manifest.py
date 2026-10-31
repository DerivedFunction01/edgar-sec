"""Manifest models for DAG snapshot nodes.

Provides deterministic serialization and cryptographic integrity checking.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.serialization import canonical_json

NodeKind = Literal["checkpoint", "delta"]


def ordered_parts_fingerprint(part_sha256s: tuple[str, ...] | list[str]) -> str:
    return sha256_text(canonical_json(list(part_sha256s)))


@dataclass(frozen=True, slots=True)
class ParentRef:
    """Cryptographic reference to one parent snapshot node."""

    snapshot_id: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "snapshot_id": self.snapshot_id,
            "manifest_sha256": self.manifest_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ParentRef:
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            manifest_sha256=str(data["manifest_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class PartDescriptor:
    """Descriptor of one physical Parquet part in a snapshot relation."""

    path: str
    sha256: str
    row_count: int
    byte_size: int
    key_min: str | None = None
    key_max: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "sha256": self.sha256,
            "row_count": self.row_count,
            "byte_size": self.byte_size,
        }
        if self.key_min is not None:
            payload["key_min"] = self.key_min
        if self.key_max is not None:
            payload["key_max"] = self.key_max
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PartDescriptor:
        return cls(
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            row_count=int(data["row_count"]),
            byte_size=int(data["byte_size"]),
            key_min=str(data["key_min"]) if data.get("key_min") is not None else None,
            key_max=str(data["key_max"]) if data.get("key_max") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class DAGNodeManifest:
    """Immutable manifest for one DAG checkpoint or delta node."""

    snapshot_id: str
    kind: NodeKind
    parents: tuple[ParentRef, ...]
    checkpoint_anchor_id: str
    lineage_depth: int
    created_at: str
    relations: Mapping[str, tuple[PartDescriptor, ...]]
    logical_fingerprint: str
    schema_versions: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def parent_snapshot_id(self) -> str:
        """First parent snapshot ID or empty string if no parents."""
        return self.parents[0].snapshot_id if self.parents else ""

    @property
    def parent_manifest_sha256(self) -> str:
        """First parent manifest digest or empty string if no parents."""
        return self.parents[0].manifest_sha256 if self.parents else ""

    @property
    def manifest_sha256(self) -> str:
        """Digest of this snapshot node manifest."""
        return self.logical_fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "kind": self.kind,
            "parents": [p.to_dict() for p in self.parents],
            "checkpoint_anchor_id": self.checkpoint_anchor_id,
            "lineage_depth": self.lineage_depth,
            "created_at": self.created_at,
            "relations": {
                name: [part.to_dict() for part in parts]
                for name, parts in sorted(self.relations.items())
            },
            "logical_fingerprint": self.logical_fingerprint,
            "schema_versions": dict(sorted(self.schema_versions.items())),
            "metadata": dict(sorted(self.metadata.items())),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DAGNodeManifest:
        raw_relations = data.get("relations", {})
        relations = {
            name: tuple(PartDescriptor.from_dict(p) for p in parts)
            for name, parts in raw_relations.items()
        }
        raw_parents = data.get("parents")
        if raw_parents is not None and isinstance(raw_parents, list):
            parents = tuple(ParentRef.from_dict(p) for p in raw_parents)
        else:
            parents = ()
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            kind="checkpoint" if data.get("kind") == "checkpoint" else "delta",
            parents=parents,
            checkpoint_anchor_id=str(data.get("checkpoint_anchor_id") or ""),
            lineage_depth=int(data.get("lineage_depth", 0)),
            created_at=str(data.get("created_at") or datetime.now(UTC).isoformat()),
            relations=relations,
            logical_fingerprint=str(data.get("logical_fingerprint") or ""),
            schema_versions=dict(data.get("schema_versions", {})),
            metadata=dict(data.get("metadata", {})),
        )


__all__ = [
    "DAGNodeManifest",
    "NodeKind",
    "ParentRef",
    "PartDescriptor",
    "ordered_parts_fingerprint",
]
