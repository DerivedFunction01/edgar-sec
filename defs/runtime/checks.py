"""Repository policy-scanner contract and registry for the validation gate.

A scanner is a named callable returning structured findings — whether it
shells out to a command (e.g. git), reads files, or runs in-process.
``check.py`` runs every registered scanner between linting and tests and
prints each scanner's description plus any findings; future policy scanners
register here instead of growing hardcoded branches in ``check.py``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ScannerFinding:
    """One policy violation reported by a scanner."""

    scanner: str
    source: str  # e.g. staged | unstaged | untracked | static
    path: str
    line: int | None
    message: str
    hint: str = ""


@dataclass(frozen=True)
class Scanner:
    """One registered repository scanner."""

    name: str
    description: str
    run: Callable[[], list[ScannerFinding]]


_SCANNERS: list[Scanner] = []


def register(scanner: Scanner) -> None:
    """Add a scanner to the registry (idempotent per name)."""
    if any(existing.name == scanner.name for existing in _SCANNERS):
        return
    _SCANNERS.append(scanner)


def registered() -> tuple[Scanner, ...]:
    """All registered scanners in deterministic registration order."""
    return tuple(_SCANNERS)


def _run_environment_access() -> list[ScannerFinding]:
    from .env import scan_modified_environment_access

    return scan_modified_environment_access()


def _run_artifact_paths() -> list[ScannerFinding]:
    from .paths import scan_artifact_path_literals

    return scan_artifact_path_literals()


def _run_sql_boundary() -> list[ScannerFinding]:
    from defs.sql.checks import scan_sql_boundary

    return scan_sql_boundary()


def _run_storage_boundary() -> list[ScannerFinding]:
    from defs.storage.checks import scan_storage_boundary

    return scan_storage_boundary()


def _run_secrets_leakage() -> list[ScannerFinding]:
    from .scanners.secrets import scan_secret_leakage

    return scan_secret_leakage()


def _run_clean_exit() -> list[ScannerFinding]:
    from .scanners.clean_exit import scan_clean_exit_boundary

    return scan_clean_exit_boundary()


def _run_legacy_shims() -> list[ScannerFinding]:
    from .scanners.compat import scan_legacy_shims

    return scan_legacy_shims()


def _run_file_length() -> list[ScannerFinding]:
    from .scanners.length import scan_modified_file_length

    return scan_modified_file_length()


register(
    Scanner(
        name="environment-access",
        description=(
            "scan modified Python files for direct environment access, "
            "ad-hoc dotenv parsing, and application env-name declarations"
        ),
        run=_run_environment_access,
    )
)

register(
    Scanner(
        name="artifact-paths",
        description="scan modified Python files for hardcoded .artifacts path literals",
        run=_run_artifact_paths,
    )
)

register(
    Scanner(
        name="sql-boundary",
        description="scan modified phase code for raw SQL string literals and execution",
        run=_run_sql_boundary,
    )
)

register(
    Scanner(
        name="storage-boundary",
        description="scan modified files for direct pyarrow, database driver, or pandas imports",
        run=_run_storage_boundary,
    )
)

register(
    Scanner(
        name="secrets-leakage",
        description="scan modified files for committed API keys, tokens, or credentials",
        run=_run_secrets_leakage,
    )
)

register(
    Scanner(
        name="clean-exit",
        description="scan modified library/core phase code for direct sys.exit() calls",
        run=_run_clean_exit,
    )
)

register(
    Scanner(
        name="legacy-shims",
        description="scan modified files for dead legacy behavior, backward compatibility aliases, and shims",
        run=_run_legacy_shims,
    )
)

register(
    Scanner(
        name="file-length",
        description="scan modified Python files and advise when line count exceeds recommended thresholds",
        run=_run_file_length,
    )
)


def _run_form_isolation() -> list[ScannerFinding]:
    from .scanners.form_isolation import scan_form_isolation

    return scan_form_isolation()


register(
    Scanner(
        name="form-isolation",
        description="scan modified generic pipeline and phase code for hardcoded 10-K/form literals",
        run=_run_form_isolation,
    )
)


def run_all(stream=None, scanners: Iterable[Scanner] | None = None) -> int:
    """Run scanners, printing descriptions and findings; 0 clean, else 1.

    Scanner findings and scanner errors both count as failures so a broken
    scanner can never silently pass the gate.
    """
    stream = sys.stdout if stream is None else stream
    active = tuple(scanners) if scanners is not None else registered()
    failures = 0
    for scanner in active:
        print(f"==> scanner: {scanner.name} - {scanner.description}", file=stream)
        try:
            findings = scanner.run()
        except Exception as exc:  # a failing scanner must fail the gate
            print(f"    error: {scanner.name} failed: {exc}", file=stream)
            failures += 1
            continue
        if not findings:
            print("    clean", file=stream)
            continue
        failures += len(findings)
        for finding in findings:
            location = (
                f"{finding.path}:{finding.line}"
                if finding.line is not None
                else finding.path
            )
            print(f"    [{finding.source}] {location}: {finding.message}", file=stream)
            if finding.hint:
                print(f"      hint: {finding.hint}", file=stream)
    if failures:
        print(f"scanner findings: {failures}", file=stream)
        return 1
    return 0


__all__ = ["Scanner", "ScannerFinding", "register", "registered", "run_all"]
