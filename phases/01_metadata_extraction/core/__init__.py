"""Public API barrel for the metadata phase core.

Exports only the public application functions; entry points import from
here, not from individual implementation modules.
"""

from .application import (
    build_plan,
    get_status,
    load_plan,
    merge,
    merge_one_partition,
    preview_sample,
    run_chunk,
    run_partition,
    run_partition_with_automerge,
)
from .augmentation import (
    artifacts_root,
    discover_base_metadata_manifests,
    discover_source_manifests,
)
from .config import (
    CONFIG_VERSION,
    DEFAULT_ARTIFACTS,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_INPUT,
    DEFAULT_MAX_FAILURE_ATTEMPTS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PARTITION_COUNT,
    DEFAULT_PREVIEW_ARTIFACTS,
    DEFAULT_RATE_LIMIT_RPS,
    DEFAULT_STORAGE_FORMAT,
    DEFAULT_TIMEOUT_S,
    PLAN_DEFINING_FIELDS,
    PROJECT_CONFIG_DEFAULT_PATH,
    ProjectConfig,
    RunOptions,
    default_project_config,
    default_user_agent,
    load_project_config,
    plan_defining_fields,
    rate_limit_to_interval,
    validate_plan_against_options,
    write_project_config,
)
from .merge import MergeError
from .registry import compare_sources
from .source_registry import (
    SourceRegistryError,
    load_source_snapshot,
    parse_company_tickers,
    refresh_company_tickers,
)

__all__ = [
    "CONFIG_VERSION",
    "DEFAULT_ARTIFACTS",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_INPUT",
    "DEFAULT_MAX_FAILURE_ATTEMPTS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_PARTITION_COUNT",
    "DEFAULT_PREVIEW_ARTIFACTS",
    "DEFAULT_RATE_LIMIT_RPS",
    "DEFAULT_STORAGE_FORMAT",
    "DEFAULT_TIMEOUT_S",
    "PLAN_DEFINING_FIELDS",
    "PROJECT_CONFIG_DEFAULT_PATH",
    "MergeError",
    "ProjectConfig",
    "RunOptions",
    "SourceRegistryError",
    "artifacts_root",
    "build_plan",
    "compare_sources",
    "default_project_config",
    "default_user_agent",
    "discover_base_metadata_manifests",
    "discover_source_manifests",
    "get_status",
    "load_plan",
    "load_project_config",
    "load_source_snapshot",
    "merge",
    "merge_one_partition",
    "parse_company_tickers",
    "plan_defining_fields",
    "preview_sample",
    "rate_limit_to_interval",
    "refresh_company_tickers",
    "run_chunk",
    "run_partition",
    "run_partition_with_automerge",
    "validate_plan_against_options",
    "write_project_config",
]
