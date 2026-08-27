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
    "make_chunk_backend",
    "write_table_atomic",
]
