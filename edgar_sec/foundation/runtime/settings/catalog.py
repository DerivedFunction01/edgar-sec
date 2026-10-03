"""Filing-catalog and document-storage settings.

``catalog.row_group_size`` -> ``CATALOG_ROW_GROUP_SIZE``. The constants below duplicate
their authority elsewhere because Layer 0 may not import a higher layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

# Mirrors DEFAULT_ROW_GROUP_SIZE in edgar_sec.infra.storage.parquet, its authority.
# tests/infra/storage/test_parquet.py pins the pair equal.
DEFAULT_ROW_GROUP_SIZE = 128_000

# These mirror edgar_sec.pipelines.document_storage.{queries,vacuum}; Layer 0 may
# not import Layer 4. tests/pipelines/document_storage/test_settings_contract.py pins.
DEFAULT_DOCUMENT_BATCH_SIZE = 4096
DEFAULT_TARGET_BYTES = 96 * 1024 * 1024


def get_catalog_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "catalog": {
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
    "DEFAULT_TARGET_BYTES",
    "get_catalog_specs",
]
