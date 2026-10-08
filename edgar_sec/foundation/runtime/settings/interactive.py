"""Interactive terminal settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_PAGE_SIZE = 15


def get_interactive_specs() -> dict[str, dict[str, SettingSpec]]:
    """Return settings specifications for interactive terminal primitives."""
    from . import SettingSpec

    return {
        "interactive": {
            "page_size": SettingSpec(
                value_type=int,
                default=DEFAULT_PAGE_SIZE,
                env=True,
                config=True,
                cli=True,
                validate=validate_positive_int,
                description="items per page in interactive pick-lists",
            ),
        },
    }


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "get_interactive_specs",
]
