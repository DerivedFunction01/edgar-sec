"""Authority + code to pack lookup seam."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity


def resolve_pack_for_identity(identity: ExhibitIdentity) -> object | None:
    """Resolve content pack for an exhibit identity. Returns None in D1."""
    return None


def list_active_packs() -> tuple[str, ...]:
    """List active pack IDs. Empty in D1."""
    return ()


__all__ = [
    "resolve_pack_for_identity",
    "list_active_packs",
]
