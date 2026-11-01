"""Domain models and specifications for native SEC XML forms."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecXmlSchemaSpec:
    """Namespace URIs and valid root tags for a native SEC XML submission."""

    namespaces: frozenset[str]
    root_tags: frozenset[str]


__all__ = ["SecXmlSchemaSpec"]
