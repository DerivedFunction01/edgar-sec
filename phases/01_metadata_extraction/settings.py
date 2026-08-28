"""Phase-owned settings for the metadata extraction phase.

Shared SEC/runtime settings (identity, cache, workers, chunk size) live in
``defs/runtime/settings/``; only phase-specific behavior is declared here.
"""

from __future__ import annotations

from defs.runtime.settings import SettingSpec

from .core.config import DEFAULT_MAX_FAILURE_ATTEMPTS

SETTING_SPECS = {
    "metadata": {
        "max_failure_attempts": SettingSpec(
            value_type=int,
            default=DEFAULT_MAX_FAILURE_ATTEMPTS,
            config=True,
            cli=True,
            description="retry budget per failing chunk before it is quarantined",
        ),
    },
}

__all__ = ["SETTING_SPECS"]
