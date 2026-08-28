"""Phase-owned settings barrel.

Maps phase identifiers to their settings modules. Numbered phase packages
load through ``importlib`` because names like ``phases.01_metadata_extraction``
are not valid static import identifiers. Each phase root owns one
``settings.py`` exporting a single ``SETTING_SPECS`` dictionary; shared
settings stay under ``defs/runtime/settings/``.
"""

from __future__ import annotations

import importlib

PHASE_SETTING_MODULES = {
    "metadata": "phases.01_metadata_extraction.settings",
    "filing_extraction": "phases.02_filing_extraction.settings",
}


def phase_settings_module(phase_id: str) -> str:
    """Return the settings module path for a phase identifier."""
    try:
        return PHASE_SETTING_MODULES[phase_id]
    except KeyError:
        raise ValueError(
            f"unknown phase {phase_id!r}; known: {sorted(PHASE_SETTING_MODULES)}"
        ) from None


def load_phase_specs(phase_id: str) -> dict:
    """Import and return one phase's ``SETTING_SPECS`` dictionary."""
    module = importlib.import_module(phase_settings_module(phase_id))
    return module.SETTING_SPECS


__all__ = ["PHASE_SETTING_MODULES", "load_phase_specs", "phase_settings_module"]
