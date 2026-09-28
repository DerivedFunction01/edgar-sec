"""Policy scanner registry and public entry point."""

from __future__ import annotations

from .base import Scanner, ScannerFinding
from .clean_exit import SCANNER as CLEAN_EXIT_SCANNER
from .environment import SCANNER as ENV_SCANNER
from .layers import SCANNER as LAYERS_SCANNER
from .length import SCANNER as LENGTH_SCANNER
from .paths import SCANNER as PATHS_SCANNER
from .resources import SCANNER as RESOURCES_SCANNER
from .secrets import SCANNER as SECRETS_SCANNER

ALL_SCANNERS: tuple[Scanner, ...] = (
    ENV_SCANNER,
    PATHS_SCANNER,
    SECRETS_SCANNER,
    CLEAN_EXIT_SCANNER,
    LENGTH_SCANNER,
    LAYERS_SCANNER,
    RESOURCES_SCANNER,
)

__all__ = [
    "ALL_SCANNERS",
    "CLEAN_EXIT_SCANNER",
    "ENV_SCANNER",
    "LAYERS_SCANNER",
    "LENGTH_SCANNER",
    "PATHS_SCANNER",
    "RESOURCES_SCANNER",
    "SECRETS_SCANNER",
    "Scanner",
    "ScannerFinding",
]
