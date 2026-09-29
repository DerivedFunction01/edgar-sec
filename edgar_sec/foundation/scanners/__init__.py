"""Policy scanner registry and public entry point."""

from __future__ import annotations

from .base import Scanner, ScannerFinding
from .clean_exit import SCANNER as CLEAN_EXIT_SCANNER
from .date_patterns import SCANNER as DATE_PATTERNS_SCANNER
from .environment import SCANNER as ENV_SCANNER
from .json_io import SCANNER as JSON_IO_SCANNER
from .layers import SCANNER as LAYERS_SCANNER
from .legacy_shims import SCANNER as LEGACY_SHIMS_SCANNER
from .length import SCANNER as LENGTH_SCANNER
from .paths import SCANNER as PATHS_SCANNER
from .regex_alternations import SCANNER as REGEX_ALTERNATIONS_SCANNER
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
    REGEX_ALTERNATIONS_SCANNER,
    LEGACY_SHIMS_SCANNER,
    JSON_IO_SCANNER,
    DATE_PATTERNS_SCANNER,
)

__all__ = [
    "ALL_SCANNERS",
    "CLEAN_EXIT_SCANNER",
    "DATE_PATTERNS_SCANNER",
    "ENV_SCANNER",
    "JSON_IO_SCANNER",
    "LAYERS_SCANNER",
    "LEGACY_SHIMS_SCANNER",
    "LENGTH_SCANNER",
    "PATHS_SCANNER",
    "REGEX_ALTERNATIONS_SCANNER",
    "RESOURCES_SCANNER",
    "SECRETS_SCANNER",
    "Scanner",
    "ScannerFinding",
]
