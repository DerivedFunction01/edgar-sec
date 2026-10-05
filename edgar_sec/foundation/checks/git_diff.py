"""Git status parser and change classifier for test selection."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

NON_CODE_EXTENSIONS = {
    ".md",
    ".rst",
    ".txt",
    ".json",
    ".csv",
    ".parquet",
    ".sql",
    ".yaml",
    ".yml",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".html",
}

ROOT_CONFIG_NAMES = {
    "pyproject.toml",
    "tests/conftest.py",
}


@dataclass(frozen=True)
class GitStatusSnapshot:
    """Snapshot of working tree changes relative to HEAD."""

    modified_files: tuple[str, ...] = field(default_factory=tuple)
    deleted_files: tuple[str, ...] = field(default_factory=tuple)
    untracked_files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_changes(self) -> bool:
        return bool(self.modified_files or self.deleted_files or self.untracked_files)

    @property
    def all_active_files(self) -> tuple[str, ...]:
        """All modified or newly created files (excluding deleted)."""
        return tuple(dict.fromkeys((*self.modified_files, *self.untracked_files)))

    @property
    def python_sources(self) -> tuple[str, ...]:
        """Changed Python files under edgar_sec/ or root Python scripts."""
        return tuple(
            f
            for f in self.all_active_files
            if (f.startswith("edgar_sec/") or f in ("check.py", "run.py"))
            and f.endswith(".py")
        )

    @property
    def python_tests(self) -> tuple[str, ...]:
        """Changed test files under tests/."""
        return tuple(
            f
            for f in self.all_active_files
            if f.startswith("tests/")
            and f.endswith(".py")
            and not f.endswith("conftest.py")
        )

    @property
    def changed_conftests(self) -> tuple[str, ...]:
        """Changed conftest.py files."""
        return tuple(f for f in self.all_active_files if f.endswith("conftest.py"))

    def excluding(self, paths: frozenset[str]) -> GitStatusSnapshot:
        """Drop the given paths, so they no longer satisfy any classifier below."""
        if not paths:
            return self
        return GitStatusSnapshot(
            modified_files=tuple(f for f in self.modified_files if f not in paths),
            deleted_files=self.deleted_files,
            untracked_files=tuple(f for f in self.untracked_files if f not in paths),
        )

    @property
    def touches_root_config(self) -> bool:
        """True if root configs or test fixtures root changed."""
        for f in (*self.all_active_files, *self.deleted_files):
            if f in ROOT_CONFIG_NAMES or f == "tests/conftest.py":
                return True
        return False

    @property
    def is_docs_or_assets_only(self) -> bool:
        """True if changes exist but none touch executable Python code or configs."""
        if not self.has_changes:
            return False
        if self.touches_root_config:
            return False
        if self.python_sources or self.python_tests or self.changed_conftests:
            return False
        # If any file has non-doc python or executable extensions, return False
        for f in (*self.all_active_files, *self.deleted_files):
            if f.endswith((".py", ".sh")):
                return False
        return True


def parse_porcelain_output(stdout: str) -> GitStatusSnapshot:
    """Parse output from `git status --porcelain=v1`."""
    modified: list[str] = []
    deleted: list[str] = []
    untracked: list[str] = []

    for line in stdout.splitlines():
        if not line or len(line) < 4:
            continue
        status = line[:2]
        path_part = line[3:].strip()
        # Handle rename format: "R  old -> new"
        if " -> " in path_part:
            path_part = path_part.split(" -> ")[1].strip()

        # Strip optional quotes if git quoted paths
        if path_part.startswith('"') and path_part.endswith('"'):
            path_part = path_part[1:-1]

        if status == "??":
            untracked.append(path_part)
        elif "D" in status:
            deleted.append(path_part)
        else:
            modified.append(path_part)

    return GitStatusSnapshot(
        modified_files=tuple(dict.fromkeys(modified)),
        deleted_files=tuple(dict.fromkeys(deleted)),
        untracked_files=tuple(dict.fromkeys(untracked)),
    )


def get_git_status(repo_root: Path | None = None) -> GitStatusSnapshot:
    """Run `git status --porcelain` in the repo root and return parsed snapshot."""
    root = repo_root or Path.cwd()
    cmd = ["git", "status", "--porcelain=v1"]
    proc = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        # Fallback for non-git environments: report no changes so caller handles safely
        return GitStatusSnapshot()
    return parse_porcelain_output(proc.stdout)
