"""Filing-catalog settings.

Logical paths are chosen so derived environment names read naturally:
``catalog.source_batch_size`` -> ``CATALOG_SOURCE_BATCH_SIZE``.

``source_batch_size`` is deliberately distinct from ``runtime.chunk_size``.
The latter sizes Phase 1's resumable *network* chunks; this one sizes how many
registrant rows Phase 2 stages into DuckDB per batch. They share a default of
1,000 but describe different concerns, so they are registered separately rather
than aliased.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_SOURCE_BATCH_SIZE = 1000

# This mirrors DEFAULT_ROW_GROUP_SIZE in edgar_sec.infra.storage.parquet, which
# is the authority for the value. The duplication is forced by the enforced
# layer graph: this module is Layer 0 (foundation) and may not import Layer 2
# (infra). tests/infra/storage/test_parquet.py pins the two equal, so a change to
# one without the other fails the gate rather than silently changing only the
# setting default.
DEFAULT_ROW_GROUP_SIZE = 128_000


def get_catalog_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "catalog": {
            "source_batch_size": SettingSpec(
                value_type=int,
                default=DEFAULT_SOURCE_BATCH_SIZE,
                env=True,
                machine_local=True,
                validate=validate_positive_int,
                description=(
                    "registrant rows staged into DuckDB per batch while "
                    "materializing the filing catalog"
                ),
            ),
            "row_group_size": SettingSpec(
                value_type=int,
                default=DEFAULT_ROW_GROUP_SIZE,
                validate=validate_positive_int,
                description="Parquet row group size for published catalog shards",
            ),
        },
    }


__all__ = [
    "DEFAULT_ROW_GROUP_SIZE",
    "DEFAULT_SOURCE_BATCH_SIZE",
    "get_catalog_specs",
]
