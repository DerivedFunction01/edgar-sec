"""Shared phase runtime contracts."""

from .artifacts import (
    artifact_id,
    create_bundle,
    discover_legacy_manifests,
    import_bundle,
    load_manifest,
    make_manifest,
    publish_manifest,
    relative_path,
    resolve_manifest,
    validate_manifest,
)
from .cli import add_common_options, coalesce, load_config_or_template, print_json
from .defaults import DEFAULT_CHUNK_SIZE, DEFAULT_PARTITION_COUNT, DEFAULT_WORKERS
from .env import DEFAULT_DOTENV_PATH, get_env, load_dotenv
from .interactive import InteractivePhase, run_interactive
from .partitions import divide_ids_among_workers, parse_id_selection
from .paths import (
    MERGE_DIR_NAME,
    MERGE_REPORT_NAME,
    ArtifactClassification,
    ArtifactRole,
    PhasePaths,
    ProjectPaths,
    RunPaths,
    classify_artifact_path,
    merge_report_path_in,
    partition_artifact_path_in,
    partition_merge_report_path_in,
    partition_merge_root_in,
    resolve_paths,
)
from .progress import make_merge_progress_callback, make_tqdm_callback

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_DOTENV_PATH",
    "DEFAULT_PARTITION_COUNT",
    "DEFAULT_WORKERS",
    "MERGE_DIR_NAME",
    "MERGE_REPORT_NAME",
    "ArtifactClassification",
    "ArtifactRole",
    "InteractivePhase",
    "PhasePaths",
    "ProjectPaths",
    "RunPaths",
    "add_common_options",
    "artifact_id",
    "classify_artifact_path",
    "coalesce",
    "create_bundle",
    "discover_legacy_manifests",
    "divide_ids_among_workers",
    "get_env",
    "import_bundle",
    "load_config_or_template",
    "load_dotenv",
    "load_manifest",
    "make_manifest",
    "make_merge_progress_callback",
    "make_tqdm_callback",
    "merge_report_path_in",
    "parse_id_selection",
    "partition_artifact_path_in",
    "partition_merge_report_path_in",
    "partition_merge_root_in",
    "print_json",
    "publish_manifest",
    "relative_path",
    "resolve_manifest",
    "resolve_paths",
    "run_interactive",
    "validate_manifest",
]
