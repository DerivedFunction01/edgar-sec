"""Contract tests for the policy-scanner registry and individual domain/hygiene scanners.

Scanners run against temporary Git repositories so tests never depend on the
developer worktree's git state.
"""

from __future__ import annotations

import subprocess

import pytest

from defs.runtime import checks
from defs.runtime.checks import Scanner, ScannerFinding
from defs.runtime.env import scan_modified_environment_access
from defs.runtime.paths import scan_artifact_path_literals
from defs.runtime.scanners.clean_exit import scan_clean_exit_boundary
from defs.runtime.scanners.compat import scan_legacy_shims
from defs.runtime.scanners.form_isolation import scan_form_isolation
from defs.runtime.scanners.json_io import scan_json_io
from defs.runtime.scanners.length import scan_modified_file_length
from defs.runtime.scanners.paths import scan_path_construction
from defs.runtime.scanners.regex_alternations import scan_regex_alternations
from defs.runtime.scanners.resources import scan_resource_allocation
from defs.runtime.scanners.secrets import scan_secret_leakage
from defs.sql.checks import scan_sql_boundary
from defs.storage.checks import scan_storage_boundary

VIOLATION = 'VALUE = os.environ.get("THING", "")\n'


def _git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )
    return result.stdout


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_registry_contains_all_scanners():
    names = [scanner.name for scanner in checks.registered()]
    expected = [
        "environment-access",
        "artifact-paths",
        "sql-boundary",
        "storage-boundary",
        "secrets-leakage",
        "clean-exit",
        "legacy-shims",
        "file-length",
        "form-isolation",
        "resource-allocation",
    ]
    for name in expected:
        assert name in names
        assert names.count(name) == 1


def test_run_all_reports_clean_scanners_as_zero(capsys):
    clean = Scanner(
        name="always-clean",
        description="no findings",
        run=list,
    )
    assert checks.run_all(scanners=[clean]) == 0
    assert "always-clean" in capsys.readouterr().out


def test_run_all_reports_findings_and_fails(capsys):
    finding = ScannerFinding(
        scanner="fake",
        source="static",
        path="x.py",
        line=3,
        message="violation",
        hint="fix it",
    )
    scanner = Scanner(name="fake", description="one finding", run=lambda: [finding])
    assert checks.run_all(scanners=[scanner]) == 1
    out = capsys.readouterr().out
    assert "[static] x.py:3: violation" in out
    assert "hint: fix it" in out


def test_run_all_counts_scanner_errors_as_failures(capsys):
    def boom() -> list[ScannerFinding]:
        raise RuntimeError("scanner crashed")

    scanner = Scanner(name="boom", description="crashes", run=boom)
    assert checks.run_all(scanners=[scanner]) == 1
    assert "scanner crashed" in capsys.readouterr().out


# --- environment-access --------------------------------------------------------


def test_clean_repository_has_no_findings(repo):
    assert scan_modified_environment_access(repo_root=repo) == []


def test_unstaged_changes_are_scanned(repo):
    (repo / "app.py").write_text(VIOLATION, encoding="utf-8")
    findings = scan_modified_environment_access(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].source == "unstaged"
    assert findings[0].path == "app.py"
    assert findings[0].line == 1
    assert findings[0].scanner == "environment-access"


def test_staged_only_changes_are_scanned(repo):
    (repo / "app.py").write_text(VIOLATION, encoding="utf-8")
    _git(repo, "add", "app.py")
    findings = scan_modified_environment_access(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].source == "staged"


def test_staged_and_unstaged_findings_are_reported_separately(repo):
    (repo / "app.py").write_text(VIOLATION, encoding="utf-8")
    _git(repo, "add", "app.py")
    (repo / "app.py").write_text(
        VIOLATION + 'OTHER = os.getenv("OTHER")\n', encoding="utf-8"
    )
    findings = scan_modified_environment_access(repo_root=repo)
    sources = {finding.source for finding in findings}
    assert sources == {"staged", "unstaged"}


def test_untracked_files_are_scanned(repo):
    (repo / "untracked.py").write_text(VIOLATION, encoding="utf-8")
    findings = scan_modified_environment_access(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].source == "untracked"
    assert findings[0].path == "untracked.py"


def test_deleted_files_produce_no_findings(repo):
    (repo / "app.py").write_text(VIOLATION, encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "violation")
    (repo / "app.py").unlink()
    _git(repo, "add", "-A")
    assert scan_modified_environment_access(repo_root=repo) == []


def test_renamed_files_are_scanned_under_the_new_name(repo):
    _git(repo, "mv", "app.py", "renamed.py")
    (repo / "renamed.py").write_text(VIOLATION, encoding="utf-8")
    findings = scan_modified_environment_access(repo_root=repo)
    assert findings
    assert findings[-1].path == "renamed.py"


def test_allowlisted_paths_are_skipped(repo):
    boundary = repo / "defs" / "runtime"
    boundary.mkdir(parents=True)
    (boundary / "env.py").write_text(VIOLATION, encoding="utf-8")
    _git(repo, "add", "-A")
    test_dir = repo / "pkg" / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_x.py").write_text(VIOLATION, encoding="utf-8")
    assert scan_modified_environment_access(repo_root=repo) == []


def test_settings_modules_are_allowlisted(repo):
    boundary = repo / "defs" / "runtime" / "settings"
    boundary.mkdir(parents=True)
    (boundary / "sec.py").write_text('NAME = "SEC_USER_AGENT"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    assert scan_modified_environment_access(repo_root=repo) == []


def test_adhoc_dotenv_parsing_is_flagged_outside_env_layer(repo):
    (repo / "app.py").write_text(
        'from dotenv import load_dotenv\nload_dotenv("secret.env")\n',
        encoding="utf-8",
    )
    findings = scan_modified_environment_access(repo_root=repo)
    assert len(findings) == 1
    assert "dotenv" in findings[0].message


def test_env_name_constant_declaration_is_flagged(repo):
    (repo / "app.py").write_text('LEGACY_INPUT = "SEC_USER_AGENT"\n', encoding="utf-8")
    findings = scan_modified_environment_access(repo_root=repo)
    assert len(findings) == 1
    assert "environment-name constant" in findings[0].message


def test_ordinary_constants_are_not_flagged(repo):
    (repo / "app.py").write_text(
        'DEFAULT_WORKERS = 4\nMSG = "use the SETTINGS panel"\n',
        encoding="utf-8",
    )
    assert scan_modified_environment_access(repo_root=repo) == []


def test_findings_are_deterministically_ordered(repo):
    (repo / "a.py").write_text(VIOLATION, encoding="utf-8")
    (repo / "b.py").write_text(VIOLATION, encoding="utf-8")
    findings = scan_modified_environment_access(repo_root=repo)
    keys = [(finding.source, finding.path, finding.line) for finding in findings]
    assert keys == sorted(keys)


# --- artifact-paths scanner ----------------------------------------------------


def test_artifact_paths_scanner_flags_hardcoded_literals(repo):
    (repo / "phase.py").write_text(
        'path = ".artifacts/metadata/data"\n', encoding="utf-8"
    )
    findings = scan_artifact_path_literals(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "artifact-paths"
    assert "hardcoded .artifacts path literal" in findings[0].message


def test_artifact_paths_scanner_allows_defs_and_tests(repo):
    p = repo / "defs" / "runtime" / "paths.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('DEFAULT = ".artifacts"\n', encoding="utf-8")
    _git(repo, "add", "-A")

    t = repo / "defs" / "tests" / "test_foo.py"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text('target = ".artifacts/run"\n', encoding="utf-8")
    _git(repo, "add", "-A")

    assert scan_artifact_path_literals(repo_root=repo) == []


# --- sql-boundary scanner -------------------------------------------------------


def test_sql_boundary_scanner_flags_raw_sql_in_phases(repo):
    phase = repo / "phases" / "01_metadata_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "query.py").write_text(
        'SQL = "SELECT * FROM filing_metadata WHERE cik = 1"\n', encoding="utf-8"
    )
    findings = scan_sql_boundary(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "sql-boundary"


def test_sql_boundary_scanner_allows_defs_sql_and_storage(repo):
    s = repo / "defs" / "sql" / "compiler.py"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text('SQL = "SELECT 1"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    assert scan_sql_boundary(repo_root=repo) == []


# --- storage-boundary scanner ---------------------------------------------------


def test_storage_boundary_scanner_flags_direct_pyarrow_import(repo):
    phase = repo / "phases" / "01_metadata_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "schema.py").write_text("import pyarrow as pa\n", encoding="utf-8")
    findings = scan_storage_boundary(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "storage-boundary"
    assert "direct pyarrow import outside defs/storage" in findings[0].message


def test_storage_boundary_scanner_allows_pyarrow_in_defs_storage(repo):
    s = repo / "defs" / "storage" / "backend.py"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text("import pyarrow as pa\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert scan_storage_boundary(repo_root=repo) == []


def test_storage_boundary_scanner_flags_database_drivers_in_phases(repo):
    phase = repo / "phases" / "01_metadata_extraction" / "core"
    phase.mkdir(parents=True, exist_ok=True)
    (phase / "db.py").write_text("import duckdb\n", encoding="utf-8")
    findings = scan_storage_boundary(repo_root=repo)
    assert len(findings) == 1
    assert "direct database driver import" in findings[0].message


# --- secrets-leakage scanner ---------------------------------------------------


def test_secrets_leakage_scanner_flags_api_tokens(repo):
    (repo / "app.py").write_text(
        'api_key = "sk-123456789012345678901234567890"\n', encoding="utf-8"
    )
    findings = scan_secret_leakage(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "secrets-leakage"


def test_secrets_leakage_scanner_matches_case_insensitive_candidates(repo):
    (repo / "app.py").write_text('API_KEY = "abcdefghijklmnop"\n', encoding="utf-8")
    findings = scan_secret_leakage(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "secrets-leakage"


def test_secrets_leakage_scanner_allows_placeholders(repo):
    (repo / "app.py").write_text('api_key = "placeholder-key"\n', encoding="utf-8")
    assert scan_secret_leakage(repo_root=repo) == []


# --- clean-exit scanner --------------------------------------------------------


def test_clean_exit_scanner_flags_sys_exit_in_core(repo):
    phase = repo / "phases" / "01_metadata_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "logic.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    findings = scan_clean_exit_boundary(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "clean-exit"


def test_clean_exit_scanner_allows_cli_and_runner_scripts(repo):
    (repo / "run.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    _git(repo, "add", "-A")
    cli = repo / "phases" / "01_metadata_extraction" / "cli.py"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert scan_clean_exit_boundary(repo_root=repo) == []


# --- legacy-shims scanner ------------------------------------------------------


def test_legacy_shims_scanner_flags_compat_comments(repo):
    (repo / "app.py").write_text(
        "OldClass = NewClass # Backwards-compatibility alias\n", encoding="utf-8"
    )
    findings = scan_legacy_shims(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "legacy-shims"
    assert (
        "compatibility layer, legacy alias, or transitional shim detected"
        in findings[0].message
    )


def test_legacy_shims_scanner_matches_capitalized_legacy_comments(repo):
    (repo / "app.py").write_text(
        "# Legacy behavior retained temporarily\n", encoding="utf-8"
    )
    findings = scan_legacy_shims(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "legacy-shims"


def test_legacy_shims_scanner_flags_legacy_identifiers(repo):
    (repo / "app.py").write_text(
        "def _legacy_normalize():\n    pass\n", encoding="utf-8"
    )
    findings = scan_legacy_shims(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "legacy-shims"


def test_legacy_shims_scanner_allows_manifest_bootstrap_module(repo):
    p = repo / "defs" / "runtime" / "artifacts.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("def discover_legacy_manifests(): pass\n", encoding="utf-8")
    _git(repo, "add", "-A")
    assert scan_legacy_shims(repo_root=repo) == []


# --- file-length scanner -------------------------------------------------------


def test_file_length_scanner_flags_files_exceeding_threshold(repo):
    long_content = "\n".join(f"x_{i} = {i}" for i in range(505)) + "\n"
    (repo / "long_module.py").write_text(long_content, encoding="utf-8")
    findings = scan_modified_file_length(repo_root=repo, max_lines=500)
    assert len(findings) == 1
    assert findings[0].scanner == "file-length"
    assert "exceeds 500 lines threshold" in findings[0].message


def test_file_length_scanner_allows_test_files_and_allowed_paths(repo):
    long_content = "\n".join(f"x_{i} = {i}" for i in range(505)) + "\n"
    t = repo / "tests" / "test_big.py"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(long_content, encoding="utf-8")
    _git(repo, "add", "-A")

    s = repo / "scratch" / "probe.py"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text(long_content, encoding="utf-8")
    _git(repo, "add", "-A")

    assert scan_modified_file_length(repo_root=repo, max_lines=500) == []


# --- form-isolation scanner ----------------------------------------------------


def test_form_isolation_scanner_flags_hardcoded_10k_literals(repo):
    phase = repo / "phases" / "01_metadata_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "extract.py").write_text('TARGET_FORM = "10-K"\n', encoding="utf-8")
    findings = scan_form_isolation(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "form-isolation"
    assert "hardcoded form literal" in findings[0].message


def test_form_isolation_scanner_flags_10ka_and_10q(repo):
    phase = repo / "phases" / "01_metadata_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "extract.py").write_text('forms = ["10-K/A", "10-Q"]\n', encoding="utf-8")
    findings = scan_form_isolation(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "form-isolation"


def test_form_isolation_scanner_flags_8k_literals(repo):
    phase = repo / "phases" / "01_metadata_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "extract.py").write_text('TARGET_FORM = "8-K"\n', encoding="utf-8")
    findings = scan_form_isolation(repo_root=repo)
    assert len(findings) == 1
    assert findings[0].scanner == "form-isolation"


def test_form_isolation_scanner_allows_tests_and_comments(repo):
    (repo / "app.py").write_text(
        "# Reference: Form 10-K guidelines\nx = 1\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")

    t = repo / "phases" / "01_metadata_extraction" / "tests" / "test_extract.py"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text('form = "10-K"\n', encoding="utf-8")
    _git(repo, "add", "-A")

    assert scan_form_isolation(repo_root=repo) == []


# --- resource-allocation scanner ----------------------------------------------


def test_resource_allocation_scanner_flags_hardcoded_threads_and_memory(repo):
    phase = repo / "phases" / "02_filing_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "extract.py").write_text(
        'def run(threads: int = 4, memory_limit: str = "2GB"):\n    pass\n',
        encoding="utf-8",
    )
    findings = scan_resource_allocation(repo_root=repo)
    assert len(findings) >= 1
    assert findings[0].scanner == "resource-allocation"
    assert "hardcoded resource allocation" in findings[0].message


def test_resource_allocation_scanner_allows_resources_and_tests(repo):
    t = repo / "phases" / "02_filing_extraction" / "tests" / "test_extract.py"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text('threads = 4\nmemory_limit = "2GB"\n', encoding="utf-8")
    _git(repo, "add", "-A")

    assert scan_resource_allocation(repo_root=repo) == []


# --- path-construction scanner ------------------------------------------------


def test_path_construction_scanner_flags_adhoc_dataset_paths(repo):
    phase = repo / "phases" / "02_filing_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "extract.py").write_text(
        'dest = root / "filing_targets" / "final"\n',
        encoding="utf-8",
    )
    findings = scan_path_construction(repo_root=repo)
    assert "ad-hoc path construction" in findings[0].message


def test_path_construction_scanner_allows_paths_and_tests(repo):
    t = repo / "phases" / "02_filing_extraction" / "tests" / "test_extract.py"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text('dest = root / "filing_targets" / "final"\n', encoding="utf-8")
    _git(repo, "add", "-A")

    boundary = repo / "defs" / "runtime"
    boundary.mkdir(parents=True, exist_ok=True)
    (boundary / "paths.py").write_text(
        'root / "filing_targets" / "final"\n', encoding="utf-8"
    )
    _git(repo, "add", "-A")

    assert scan_path_construction(repo_root=repo) == []


# --- json-io scanner ----------------------------------------------------------


def test_json_io_scanner_flags_redundant_helpers(repo):
    phase = repo / "phases" / "02_filing_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "helper.py").write_text(
        "def canonical_json(value):\n    return ''\n",
        encoding="utf-8",
    )
    findings = scan_json_io(repo_root=repo)
    assert len(findings) >= 1
    assert findings[0].scanner == "json-io"
    assert "redundant definition of json helpers" in findings[0].message


def test_json_io_scanner_flags_non_atomic_writes(repo):
    phase = repo / "phases" / "02_filing_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "extract.py").write_text(
        'path.write_text(json.dumps({"a": 1}))\n',
        encoding="utf-8",
    )
    findings = scan_json_io(repo_root=repo)
    assert len(findings) >= 1
    assert findings[0].scanner == "json-io"
    assert "non-atomic JSON file write" in findings[0].message


def test_json_io_scanner_allows_storage_and_tests(repo):
    t = repo / "phases" / "02_filing_extraction" / "tests" / "test_extract.py"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text('path.write_text(json.dumps({"a": 1}))\n', encoding="utf-8")
    _git(repo, "add", "-A")

    boundary = repo / "defs" / "storage"
    boundary.mkdir(parents=True, exist_ok=True)
    (boundary / "artifacts.py").write_text(
        "def canonical_json(value):\n    return ''\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")

    assert scan_json_io(repo_root=repo) == []


# --- regex-alternations scanner -----------------------------------------------


def test_regex_alternations_scanner_flags_raw_pipes(repo):
    phase = repo / "phases" / "02_filing_extraction" / "core"
    phase.mkdir(parents=True)
    (phase / "parser.py").write_text(
        'RX = re.compile(r"(?:alpha|beta|gamma|delta)")\n',
        encoding="utf-8",
    )
    findings = scan_regex_alternations(repo_root=repo)
    assert len(findings) >= 1
    assert findings[0].scanner == "regex-alternations"
    assert "found raw multi-branch regex alternation literal" in findings[0].message


def test_regex_alternations_scanner_allows_defs_regex_and_tests(repo):
    # Test files are exempt
    t = repo / "phases" / "02_filing_extraction" / "tests" / "test_parser.py"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text('RX = re.compile(r"(?:alpha|beta|gamma|delta)")\n', encoding="utf-8")
    _git(repo, "add", "-A")

    # Code using build_alternation is exempt
    phase = repo / "phases" / "02_filing_extraction" / "core"
    phase.mkdir(parents=True, exist_ok=True)
    (phase / "parser.py").write_text(
        "RX = re.compile(rf\"{build_alternation(['a', 'b', 'c'])}\")\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")

    assert scan_regex_alternations(repo_root=repo) == []
