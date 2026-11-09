"""Install battery: prove the packaged form works from a bare directory.
Three legs, each stating what it proves: this tree's wheel, a local-directory
install of this tree (uncommitted changes included), and a ``git+file://``
install (committed state only — a mechanism proof). Opt-in only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_TAXONOMY_PROBE = (
    "from edgar_sec.engine.xbrl.taxonomy.archive import archived_taxonomies, load_slice\n"
    "names = archived_taxonomies()\n"
    "assert 'us-gaap' in names, names\n"
    "rows = load_slice('us-gaap', '2025')\n"
    "assert len(rows) > 1000, len(rows)\n"
    "print(f'taxonomies={len(names)} us-gaap-2025={len(rows)}')\n"
)

_COHORT_PROBE = (
    "from edgar_sec.engine.xbrl.discovery.cohort import load_canonical_union_cohort\n"
    "rows = load_canonical_union_cohort()\n"
    "assert len(rows) == 125, len(rows)\n"
    "print(f'union-cohort={len(rows)}')\n"
)

_PRESENCE_PROBE = (
    "from edgar_sec.foundation.runtime.paths import package_data_status\n"
    "status = package_data_status()\n"
    "assert status.present, status\n"
    "print(f'package-data present at {status.taxonomy_dir}')\n"
)

_IMPORT_SWEEP = (
    "import importlib, pkgutil\n"
    "import edgar_sec\n"
    "failures = []\n"
    "count = 0\n"
    "for info in pkgutil.walk_packages(edgar_sec.__path__, 'edgar_sec.'):\n"
    "    if info.name.startswith('edgar_sec.tools'):\n"
    "        continue\n"
    "    count += 1\n"
    "    try:\n"
    "        importlib.import_module(info.name)\n"
    "    except Exception as exc:\n"
    "        failures.append(f'{info.name}: {exc!r}')\n"
    "print(f'modules={count} failures={len(failures)}')\n"
    "for failure in failures:\n"
    "    print('FAIL', failure)\n"
    "raise SystemExit(1 if failures else 0)\n"
)


@dataclass
class LegResult:
    """One install leg: what it proves, its checks, and its verdict."""

    name: str
    proves: str
    checks: list[str] = field(default_factory=list)
    install_seconds: float = 0.0
    passed: bool = True

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self.checks.append(f"{'PASS' if ok else 'FAIL'} {label} {detail}".rstrip())
        self.passed = self.passed and ok


def _find_uv() -> str:
    """Resolve uv the way init_venv does: PATH first, then the user install."""
    found = shutil.which("uv")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "uv"
    if candidate.exists():
        return str(candidate)
    raise SystemExit("uv not found on PATH or at ~/.local/bin/uv")


def _run(
    argv: list[str], *, cwd: Path, env: dict | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)


def _timed_install(uv: str, venv: Path, source: str, bare: Path) -> float:
    """Create a clean venv and install one source form into it, timed.
    The venv is built from the launching interpreter, whose Python satisfies
    the package floor, while a host default may not.
    """
    created = _run([uv, "venv", "--python", sys.executable, str(venv)], cwd=bare)
    if created.returncode != 0:
        raise RuntimeError(f"venv creation failed: {created.stderr.strip()}")
    started = time.perf_counter()
    installed = _run(
        [uv, "pip", "install", "--python", str(venv / "bin" / "python"), source],
        cwd=bare,
    )
    elapsed = time.perf_counter() - started
    if installed.returncode != 0:
        raise RuntimeError(f"install of {source} failed: {installed.stderr.strip()}")
    return elapsed


def _exercise_installed(leg: LegResult, venv: Path, bare: Path) -> None:
    """Run the installed-form checks from a bare working directory."""
    python = str(venv / "bin" / "python")
    command = str(venv / "bin" / "edgar-sec")

    help_run = _run([command, "--help"], cwd=bare)
    leg.check("edgar-sec --help", help_run.returncode == 0)

    listing = _run([command, "--list-operations", "--json"], cwd=bare)
    operations: list = []
    if listing.returncode == 0:
        try:
            operations = json.loads(listing.stdout).get("operations", [])
        except json.JSONDecodeError:
            operations = []
    leg.check(
        "edgar-sec --list-operations --json (offline operation)",
        listing.returncode == 0 and len(operations) > 0,
        f"operations={len(operations)}",
    )
    if operations:
        first = operations[0]["id"] if isinstance(operations[0], dict) else ""
        op_help = _run([command, "--op", str(first), "--help"], cwd=bare)
        leg.check(f"edgar-sec --op {first} --help", op_help.returncode == 0)

    for label, probe in (
        ("taxonomy enumeration + us-gaap 2025 slice", _TAXONOMY_PROBE),
        ("canonical union cohort load", _COHORT_PROBE),
        ("package-data presence probe", _PRESENCE_PROBE),
        ("import sweep layers 0-5", _IMPORT_SWEEP),
    ):
        run = _run([python, "-c", probe], cwd=bare)
        detail = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
        leg.check(label, run.returncode == 0, detail)


def run_battery(repo: Path, scratch: Path, *, keep: bool = False) -> int:
    """Run all three legs, print the summary, and write the run record."""
    uv = _find_uv()
    bare = scratch / "bare"
    bare.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    legs: list[LegResult] = []

    started = time.perf_counter()
    built = _run(
        [uv, "build", "--wheel", "--out-dir", str(scratch / "dist"), str(repo)],
        cwd=bare,
    )
    build_seconds = time.perf_counter() - started
    wheels = list((scratch / "dist").glob("*.whl"))
    lines.append(
        f"build: {'PASS' if built.returncode == 0 and wheels else 'FAIL'} "
        f"in {build_seconds:.1f}s"
    )
    if built.returncode != 0 or not wheels:
        lines.append(built.stderr.strip())
        _finish(lines, legs, repo, scratch, keep=keep)
        return 1

    head = _run(["git", "-C", str(repo), "rev-parse", "HEAD"], cwd=bare)
    head_sha = head.stdout.strip() or "unknown"

    full_legs = (
        (
            "wheel",
            "validates the built wheel of the current tree end to end",
            str(wheels[0]),
        ),
        (
            "directory",
            "validates the NEW code end to end: a local-directory install "
            "builds from the working tree, uncommitted changes included",
            str(repo),
        ),
    )
    for name, proves, source in full_legs:
        leg = LegResult(name=name, proves=proves)
        try:
            leg.install_seconds = _timed_install(
                uv, scratch / f"venv-{name}", source, bare
            )
            _exercise_installed(leg, scratch / f"venv-{name}", bare)
        except RuntimeError as exc:
            leg.check("install", False, str(exc))
        legs.append(leg)

    git_leg = LegResult(
        name="git",
        proves=(
            "mechanism proof only: clone + build + install via git+file:// "
            f"against committed HEAD {head_sha}; says nothing about "
            "uncommitted changes"
        ),
    )
    try:
        git_leg.install_seconds = _timed_install(
            uv, scratch / "venv-git", f"git+file://{repo}", bare
        )
        probe = _run(
            [
                str(scratch / "venv-git" / "bin" / "python"),
                "-c",
                "import edgar_sec; print(edgar_sec.__version__)",
            ],
            cwd=bare,
        )
        git_leg.check(
            "git-form install imports",
            probe.returncode == 0,
            probe.stdout.strip(),
        )
    except RuntimeError as exc:
        git_leg.check("install", False, str(exc))
    legs.append(git_leg)

    return _finish(lines, legs, repo, scratch, keep=keep)


def _finish(
    lines: list[str],
    legs: list[LegResult],
    repo: Path,
    scratch: Path,
    *,
    keep: bool,
) -> int:
    """Print per-leg verdicts, write the run record, and clean the scratch."""
    for leg in legs:
        verdict = "PASS" if leg.passed else "FAIL"
        lines.append(
            f"{leg.name} leg: {verdict} (install {leg.install_seconds:.1f}s) — {leg.proves}"
        )
        lines.extend(f"  {check}" for check in leg.checks)
    overall = all(leg.passed for leg in legs) and any(
        line.startswith("build: PASS") for line in lines
    )
    lines.append(f"BATTERY: {'PASS' if overall else 'FAIL'}")

    from edgar_sec.foundation.runtime.settings.paths import DEFAULT_ARTIFACTS_ROOT

    record_dir = repo / DEFAULT_ARTIFACTS_ROOT / "run-logs"
    record_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    record = record_dir / f"{stamp}-install-battery.md"
    record.write_text(
        "# Install battery run\n\n" + "\n".join(f"- {line}" for line in lines) + "\n",
        encoding="utf-8",
    )
    lines.append(f"run record: {record}")
    print("\n".join(lines))
    if not keep:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0 if overall else 1


def main(argv: list[str] | None = None) -> int:
    """Battery entrypoint: repo and scratch default to this tree and its sibling."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--scratch",
        type=Path,
        default=REPO_ROOT.parent / "edgar-sec-pkg-battery-scratch",
    )
    parser.add_argument("--keep", action="store_true", help="keep the scratch tree")
    args = parser.parse_args(argv)
    return run_battery(args.repo.resolve(), args.scratch.resolve(), keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
