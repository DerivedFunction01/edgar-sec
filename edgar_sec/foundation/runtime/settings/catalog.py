"""Filing-catalog and document-storage settings.

Logical paths are chosen so derived environment names read naturally:
``catalog.source_batch_size`` -> ``CATALOG_SOURCE_BATCH_SIZE``.

``source_batch_size`` is deliberately distinct from ``runtime.chunk_size``.
The latter sizes Phase 1's resumable *network* chunks; this one sizes how many
registrant rows Phase 2 stages into DuckDB per batch. They share a default of
1,000 but describe different concerns, so they are registered separately rather
than aliased.

``documents.*`` is Phase 2.5's group, registered here rather than in the
pipeline so the environment contract stays in the registry. An earlier
revision left those two values as module constants in
``pipelines/document_storage``, which made them silently not env-overridable
while ``metadata_sync`` and ``filing_catalog`` were.
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

# These mirror the authority for the value in
# edgar_sec.pipelines.document_storage.{queries,vacuum}. Same forced
# duplication as DEFAULT_ROW_GROUP_SIZE: Layer 0 may not import Layer 4.
# tests/pipelines/document_storage/test_settings_contract.py pins the pairs.
DEFAULT_DOCUMENT_BATCH_SIZE = 4096
DEFAULT_TARGET_BYTES = 96 * 1024 * 1024


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
        "documents": {
            "read_batch_size": SettingSpec(
                value_type=int,
                default=DEFAULT_DOCUMENT_BATCH_SIZE,
                env=True,
                machine_local=True,
                validate=validate_positive_int,
                description=(
                    "effective-index rows fetched per batch while streaming "
                    "document snapshots for selection or purge"
                ),
            ),
            "payload_target_bytes": SettingSpec(
                value_type=int,
                default=DEFAULT_TARGET_BYTES,
                env=True,
                machine_local=True,
                validate=validate_positive_int,
                description=(
                    "byte target a consolidated payload part is packed "
                    "towards during vacuum"
                ),
            ),
        },
    }


__all__ = [
    "DEFAULT_DOCUMENT_BATCH_SIZE",
    "DEFAULT_ROW_GROUP_SIZE",
    "DEFAULT_SOURCE_BATCH_SIZE",
    "DEFAULT_TARGET_BYTES",
    "get_catalog_specs",
]
