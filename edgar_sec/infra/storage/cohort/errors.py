"""Error taxonomy for cohort catalog operations."""

from __future__ import annotations


class CohortCatalogError(ValueError):
    """A cohort catalog operation violates an identity or lifecycle rule."""


class CohortCollisionError(CohortCatalogError):
    """A 16-hex cohort identifier is already bound to another roster."""


class CohortPinnedError(CohortCatalogError):
    """A pinned cohort cannot be deleted."""


class CohortActiveSourceError(CohortCatalogError):
    """A cohort referenced by an active source pointer cannot be deleted."""


class CohortInUseError(CohortCatalogError):
    """A cohort referenced by a workspace alias cannot be deleted."""


class CohortIdentifierError(CohortCatalogError):
    """A cohort identifier is missing, too short, or ambiguous."""


class CohortNotFoundError(CohortCatalogError):
    """A workspace variable refers to a missing cohort dataset."""


__all__ = [
    "CohortActiveSourceError",
    "CohortCatalogError",
    "CohortCollisionError",
    "CohortIdentifierError",
    "CohortInUseError",
    "CohortNotFoundError",
    "CohortPinnedError",
]
