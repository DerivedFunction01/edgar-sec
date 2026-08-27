"""Reusable file storage primitives for extraction phases."""

from .converter import DatasetConverter
from .dataset import Dataset
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

DEFAULT_STORAGE_FORMAT = "parquet"
from .memory import MemoryBackend
from .models import (
    ArtifactRef,
    BatchReceipt,
    ChunkRange,
    DatasetSpec,
    RunContext,
)
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
from .jsonl import JsonlChunkBackend, JsonlCodec, JsonlKeyValueBackend, JsonlWal
from .parquet import ParquetBackend, write_table_atomic

__all__ = [
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
    "Eq",
    "FileBackend",
    "FileStorageExecutor",
    "InSet",
    "IsNotNull",
    "IsNull",
    "JsonlChunkBackend",
    "JsonlCodec",
    "JsonlKeyValueBackend",
    "JsonlWal",
    "MalformedArtifact",
    "make_chunk_backend",
    "DEFAULT_STORAGE_FORMAT",
    "MemoryBackend",
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
    "write_table_atomic",
]
