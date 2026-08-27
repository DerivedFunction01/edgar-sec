"""Shared phase runtime contracts."""

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
    resolve_paths,
)
from .progress import make_tqdm_callback

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
    "classify_artifact_path",
    "coalesce",
    "divide_ids_among_workers",
    "get_env",
    "load_config_or_template",
    "load_dotenv",
    "make_tqdm_callback",
    "merge_report_path_in",
    "parse_id_selection",
    "print_json",
    "resolve_paths",
    "run_interactive",
]
