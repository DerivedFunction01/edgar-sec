"""Shared phase runtime contracts."""

from .defaults import DEFAULT_CHUNK_SIZE, DEFAULT_PARTITION_COUNT, DEFAULT_WORKERS
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
from .interactive import InteractivePhase, run_interactive
from .partitions import divide_ids_among_workers, parse_id_selection
from .cli import add_common_options, coalesce, load_config_or_template, print_json
from .env import DEFAULT_DOTENV_PATH, get_env, load_dotenv

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_PARTITION_COUNT",
    "DEFAULT_WORKERS",
    "ArtifactClassification",
    "ArtifactRole",
    "MERGE_DIR_NAME",
    "MERGE_REPORT_NAME",
    "PhasePaths",
    "ProjectPaths",
    "RunPaths",
    "make_tqdm_callback",
    "InteractivePhase",
    "run_interactive",
    "divide_ids_among_workers",
    "parse_id_selection",
    "add_common_options",
    "coalesce",
    "load_config_or_template",
    "print_json",
    "resolve_paths",
    "classify_artifact_path",
    "merge_report_path_in",
    "DEFAULT_DOTENV_PATH",
    "get_env",
    "load_dotenv",
]
