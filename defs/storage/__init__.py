"""Reusable file storage primitives for extraction phases."""

import pyarrow as pa

from .artifacts import file_sha256, parquet_column_names, read_records
from .converter import DatasetConverter
from .dataset import Dataset
from .duckdb_merge import (
    MergeValidation,
    MergeValidationSpec,
    concat_to_parquet,
    connect,
    count_nested_values,
    count_rows,
    duplicate_values,
    jsonl_columns,
    ordered_keys,
    validate_files,
)
from .errors import (
    MalformedArtifact,
    SchemaMismatchError,
    StorageError,
    UnsupportedCapability,
)
from .executor import (
    DeleteMatching,
    FileStorageExecutor,
    SetRecords,
    StorageExecutor,
    StorageOperation,
)
from .factory import make_chunk_backend
from .finalized import DuckDBStaging, FinalizedArtifact

DEFAULT_STORAGE_FORMAT = "parquet"
from .jsonl import JsonlChunkBackend, JsonlCodec, JsonlKeyValueBackend, JsonlWal
from .memory import MemoryBackend
from .models import (
    ArtifactRef,
    BatchReceipt,
    ChunkRange,
    DatasetSpec,
    RunContext,
)
from .parquet import ParquetBackend, write_table_atomic
from .predicates import (
    And,
    Between,
    Eq,
    InSet,
    IsNotNull,
    IsNull,
    Neq,
    Not,
    Or,
    QueryPlan,
    SortKey,
)
from .protocols import (
    BatchWriteBackend,
    ChunkStore,
    FileBackend,
    StorageBackend,
    WalStore,
)

__all__ = [
    "DEFAULT_STORAGE_FORMAT",
    "And",
    "ArtifactRef",
    "BatchReceipt",
    "BatchWriteBackend",
    "Between",
    "ChunkRange",
    "ChunkStore",
    "Dataset",
    "DatasetConverter",
    "DatasetSpec",
    "DeleteMatching",
    "DuckDBStaging",
    "Eq",
    "FileBackend",
    "FileStorageExecutor",
    "FinalizedArtifact",
    "InSet",
    "IsNotNull",
    "IsNull",
    "JsonlChunkBackend",
    "JsonlCodec",
    "JsonlKeyValueBackend",
    "JsonlWal",
    "MalformedArtifact",
    "MemoryBackend",
    "MergeValidation",
    "MergeValidationSpec",
    "Neq",
    "Not",
    "Or",
    "ParquetBackend",
    "QueryPlan",
    "RunContext",
    "SchemaMismatchError",
    "SetRecords",
    "SortKey",
    "StorageBackend",
    "StorageError",
    "StorageExecutor",
    "StorageOperation",
    "UnsupportedCapability",
    "WalStore",
    "concat_to_parquet",
    "connect",
    "count_nested_values",
    "count_rows",
    "duplicate_values",
    "file_sha256",
    "jsonl_columns",
    "make_chunk_backend",
    "ordered_keys",
    "pa",
    "parquet_column_names",
    "read_records",
    "validate_files",
    "write_table_atomic",
]
