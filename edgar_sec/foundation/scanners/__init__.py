"""Policy scanner registry and public entry point."""

from __future__ import annotations

from .base import SEVERITY_ERROR, SEVERITY_NOTICE, Scanner, ScannerFinding
from .content.denylist import SCANNER as DENYLIST_SCANNER
from .content.portability import SCANNER as PORTABILITY_SCANNER
from .content.living_dates import SCANNER as LIVING_DATES_SCANNER
from .forms.form_isolation import SCANNER as FORM_ISOLATION_SCANNER
from .forms.form_vocabulary import SCANNER as FORM_VOCABULARY_SCANNER
from .forms.tables_form_literals import SCANNER as TABLES_FORM_LITERALS_SCANNER
from .mechanics.artifact_paths import SCANNER as PATHS_SCANNER
from .mechanics.json_io import SCANNER as JSON_IO_SCANNER
from .mechanics.regex_alternations import SCANNER as REGEX_ALTERNATIONS_SCANNER
from .mechanics.sec_surface import SCANNER as SEC_SURFACE_SCANNER
from .mechanics.sha256_validation import SCANNER as SHA256_VALIDATION_SCANNER
from .mechanics.sql_interpolation import SCANNER as SQL_INTERPOLATION_SCANNER
from .mechanics.string_lookup import SCANNER as STRING_LOOKUP_SCANNER
from .mechanics.uncompiled_regex import SCANNER as UNCOMPILED_REGEX_SCANNER
from .mechanics.whole_file_read import SCANNER as WHOLE_FILE_READ_SCANNER
from .patterns.date_patterns import SCANNER as DATE_PATTERNS_SCANNER
from .patterns.identifier_patterns import SCANNER as IDENTIFIER_PATTERNS_SCANNER
from .patterns.money_patterns import SCANNER as MONEY_PATTERNS_SCANNER
from .patterns.page_patterns import SCANNER as PAGE_PATTERNS_SCANNER
from .patterns.pattern_registry import SCANNER as PATTERN_REGISTRY_SCANNER
from .patterns.period_patterns import SCANNER as PERIOD_PATTERNS_SCANNER
from .patterns.refcell_patterns import SCANNER as REFCELL_PATTERNS_SCANNER
from .runtime.batch_defaults import SCANNER as BATCH_DEFAULTS_SCANNER
from .runtime.clean_exit import SCANNER as CLEAN_EXIT_SCANNER
from .runtime.environment import SCANNER as ENV_SCANNER
from .runtime.resources import SCANNER as RESOURCES_SCANNER
from .runtime.secrets import SCANNER as SECRETS_SCANNER
from .structure.folder_density import SCANNER as FOLDER_DENSITY_SCANNER
from .structure.helper_duplicates import SCANNER as HELPER_DUPLICATES_SCANNER
from .structure.layers import SCANNER as LAYERS_SCANNER
from .structure.legacy_shims import SCANNER as LEGACY_SHIMS_SCANNER
from .structure.length import SCANNER as LENGTH_SCANNER
from .structure.prose_length import SCANNER as PROSE_LENGTH_SCANNER
from .structure.test_tree_paths import SCANNER as TEST_TREE_PATHS_SCANNER

ALL_SCANNERS: tuple[Scanner, ...] = (
    ENV_SCANNER,
    PATHS_SCANNER,
    BATCH_DEFAULTS_SCANNER,
    SECRETS_SCANNER,
    SHA256_VALIDATION_SCANNER,
    CLEAN_EXIT_SCANNER,
    LENGTH_SCANNER,
    LAYERS_SCANNER,
    RESOURCES_SCANNER,
    WHOLE_FILE_READ_SCANNER,
    REGEX_ALTERNATIONS_SCANNER,
    UNCOMPILED_REGEX_SCANNER,
    LEGACY_SHIMS_SCANNER,
    JSON_IO_SCANNER,
    DATE_PATTERNS_SCANNER,
    REFCELL_PATTERNS_SCANNER,
    PATTERN_REGISTRY_SCANNER,
    SQL_INTERPOLATION_SCANNER,
    STRING_LOOKUP_SCANNER,
    PROSE_LENGTH_SCANNER,
    LIVING_DATES_SCANNER,
    FORM_ISOLATION_SCANNER,
    FORM_VOCABULARY_SCANNER,
    SEC_SURFACE_SCANNER,
    TEST_TREE_PATHS_SCANNER,
    TABLES_FORM_LITERALS_SCANNER,
    MONEY_PATTERNS_SCANNER,
    PAGE_PATTERNS_SCANNER,
    HELPER_DUPLICATES_SCANNER,
    IDENTIFIER_PATTERNS_SCANNER,
    PERIOD_PATTERNS_SCANNER,
    FOLDER_DENSITY_SCANNER,
    DENYLIST_SCANNER,
    PORTABILITY_SCANNER,
)

__all__ = [
    "ALL_SCANNERS",
    "BATCH_DEFAULTS_SCANNER",
    "CLEAN_EXIT_SCANNER",
    "DATE_PATTERNS_SCANNER",
    "DENYLIST_SCANNER",
    "ENV_SCANNER",
    "FORM_ISOLATION_SCANNER",
    "FORM_VOCABULARY_SCANNER",
    "FOLDER_DENSITY_SCANNER",
    "HELPER_DUPLICATES_SCANNER",
    "IDENTIFIER_PATTERNS_SCANNER",
    "JSON_IO_SCANNER",
    "LAYERS_SCANNER",
    "LEGACY_SHIMS_SCANNER",
    "LENGTH_SCANNER",
    "LIVING_DATES_SCANNER",
    "MONEY_PATTERNS_SCANNER",
    "PAGE_PATTERNS_SCANNER",
    "PATHS_SCANNER",
    "PERIOD_PATTERNS_SCANNER",
    "PORTABILITY_SCANNER",
    "PATTERN_REGISTRY_SCANNER",
    "PROSE_LENGTH_SCANNER",
    "REFCELL_PATTERNS_SCANNER",
    "REGEX_ALTERNATIONS_SCANNER",
    "RESOURCES_SCANNER",
    "SECRETS_SCANNER",
    "SEC_SURFACE_SCANNER",
    "SEVERITY_ERROR",
    "SEVERITY_NOTICE",
    "SHA256_VALIDATION_SCANNER",
    "SQL_INTERPOLATION_SCANNER",
    "STRING_LOOKUP_SCANNER",
    "TABLES_FORM_LITERALS_SCANNER",
    "TEST_TREE_PATHS_SCANNER",
    "WHOLE_FILE_READ_SCANNER",
    "UNCOMPILED_REGEX_SCANNER",
    "Scanner",
    "ScannerFinding",
]
