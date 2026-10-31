"""Immutable records returned by the object store."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_id: str
    schema_name: str
    parent_object_id: str | None
    data: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SessionAlias:
    session_id: str
    alias_name: str
    target_id: str
    created_at: str
    updated_at: str
