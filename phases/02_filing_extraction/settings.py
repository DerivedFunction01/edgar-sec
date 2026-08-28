"""Phase-owned settings for the filing extraction phase.

Shared runtime execution settings live in ``defs/runtime/settings/runtime.py``
and remain machine-local; only phase behavior (persistable, dataset-scoped)
is declared here.
"""

from __future__ import annotations

from defs.runtime.settings import SettingSpec

from .core.config import DEFAULT_SOURCE_BATCH_SIZE

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
    },
}

__all__ = ["SETTING_SPECS"]
