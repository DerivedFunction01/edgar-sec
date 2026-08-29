"""Phase-owned settings for the filing extraction phase.

Shared runtime execution settings live in ``defs/runtime/settings/runtime.py``
and remain machine-local; only phase behavior (persistable, dataset-scoped)
is declared here.
"""

from __future__ import annotations

from defs.runtime.settings import SettingSpec

from .core.config import DEFAULT_AMENDMENT, DEFAULT_SOURCE_BATCH_SIZE

SETTING_SPECS = {
    "filing_extraction": {
        "source_batch_size": SettingSpec(
            value_type=int,
            default=DEFAULT_SOURCE_BATCH_SIZE,
            env=True,
            config=True,
            cli=True,
            description="source rows materialized per bounded DuckDB batch",
        ),
        "target_forms": SettingSpec(
            value_type=str,
            default="",
            env=True,
            config=True,
            cli=True,
            description="comma-separated target forms for filing extraction",
        ),
        "amendment": SettingSpec(
            value_type=str,
            default=DEFAULT_AMENDMENT,
            env=True,
            config=True,
            cli=True,
            description="amendment policy for filing extraction",
        ),
    },
}

__all__ = ["SETTING_SPECS"]
