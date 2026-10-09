"""CLI reflection and documentation sentinel synchronization engine.

Inspects ``ArgumentParser`` and ``paths.py`` definitions to update Markdown sentinels.
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from pathlib import Path
from typing import Any

COMMANDS_START = "<!-- AUTOGEN:COMMANDS:START -->"
COMMANDS_END = "<!-- AUTOGEN:COMMANDS:END -->"
PATHS_START = "<!-- AUTOGEN:PATHS:START -->"
PATHS_END = "<!-- AUTOGEN:PATHS:END -->"

_COMMANDS_RE = re.compile(
    rf"({re.escape(COMMANDS_START)}).*?({re.escape(COMMANDS_END)})",
    re.DOTALL,
)
_PATHS_RE = re.compile(
    rf"({re.escape(PATHS_START)}).*?({re.escape(PATHS_END)})",
    re.DOTALL,
)


def format_subcommand_options(subparser: argparse.ArgumentParser) -> str:
    """Format argument flags for a subparser compactly."""
    required_flags: list[str] = []
    optional_flags: list[str] = []
    for action in subparser._actions:
        opts = [o for o in action.option_strings if o not in ("-h", "--help")]
        if not opts:
            continue
        primary = opts[0]
        if action.required:
            required_flags.append(f"`{primary}`")
        else:
            optional_flags.append(f"`[{primary}]`")
    all_flags = [*required_flags, *optional_flags]
    return ", ".join(all_flags) if all_flags else "—"


def render_command_table(cli_module_dotted: str) -> str:
    """Import CLI module and render subparser markdown table."""
    try:
        mod = importlib.import_module(cli_module_dotted)
    except Exception as exc:
        return f"<!-- Error loading {cli_module_dotted}: {exc} -->"

    builder = getattr(mod, "build_parser", None)
    if not builder:
        return "None. Library package."

    parser = builder()
    subparsers_action = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)),
        None,
    )
    if not subparsers_action or not subparsers_action.choices:
        desc = parser.description or "CLI entrypoint."
        return f"`{parser.prog}` — {desc}"

    help_by_cmd = {
        ca.dest: ca.help for ca in getattr(subparsers_action, "_choices_actions", [])
    }
    rows = [
        "| Subcommand | Description | Arguments |",
        "| :--- | :--- | :--- |",
    ]
    for name, sub in sorted(subparsers_action.choices.items()):
        desc = help_by_cmd.get(name) or sub.description or ""
        opts = format_subcommand_options(sub)
        rows.append(f"| `{name}` | {desc} | {opts} |")
    return "\n".join(rows)


def render_paths_table(paths_module_dotted: str) -> str:
    """Import paths module and render relative artifact path table."""
    try:
        mod = importlib.import_module(paths_module_dotted)
    except Exception as exc:
        return f"<!-- Error loading {paths_module_dotted}: {exc} -->"

    path_classes = [
        obj
        for name, obj in vars(mod).items()
        if isinstance(obj, type) and name.endswith("Paths")
    ]
    if not path_classes:
        return "No paths dataclass found."

    cls = path_classes[0]
    doc = cls.__doc__ or "Paths layout."
    rows = [
        "| Logical Artifact | Resolution Seam |",
        "| :--- | :--- |",
    ]
    for attr_name in sorted(dir(cls)):
        if attr_name.startswith("_") or attr_name == "project":
            continue
        attr = getattr(cls, attr_name)
        if isinstance(attr, property):
            rows.append(f"| `{attr_name}` | Property |")
        elif callable(attr):
            rows.append(f"| `{attr_name}(...)` | Method |")
    if len(rows) <= 2:
        return f"`{cls.__name__}` — {doc.strip().splitlines()[0]}"
    return "\n".join(rows)


def sync_readme(readme_path: Path, apply: bool = False) -> tuple[bool, str]:
    """Sync sentinels in one README file; return (in_sync, updated_text)."""
    text = readme_path.read_text(encoding="utf-8")
    original = text
    pkg_dir = readme_path.parent

    rel_parts = pkg_dir.resolve().parts
    if "edgar_sec" in rel_parts:
        idx = rel_parts.index("edgar_sec")
        mod_prefix = ".".join(rel_parts[idx:])
    else:
        mod_prefix = ""

    if mod_prefix and _COMMANDS_RE.search(text) and (pkg_dir / "cli.py").exists():
        table = render_command_table(f"{mod_prefix}.cli")
        text = _COMMANDS_RE.sub(f"\\1\n{table}\n\\2", text)

    if mod_prefix and _PATHS_RE.search(text) and (pkg_dir / "paths.py").exists():
        table = render_paths_table(f"{mod_prefix}.paths")
        text = _PATHS_RE.sub(f"\\1\n{table}\n\\2", text)

    in_sync = text == original
    if not in_sync and apply:
        readme_path.write_text(text, encoding="utf-8")
    return in_sync, text


def scan_all_readmes(repo_root: Path, apply: bool = False) -> int:
    """Scan all READMEs with sentinels in repo; return exit code."""
    readmes = sorted(repo_root.glob("edgar_sec/**/README.md"))
    drifted: list[Path] = []
    for r in readmes:
        in_sync, _ = sync_readme(r, apply=apply)
        if not in_sync:
            drifted.append(r)

    if not drifted:
        print("==> all documentation sentinels in sync")
        return 0

    action = "updated" if apply else "out of sync"
    for d in drifted:
        print(f"  {d}: {action}")
    if not apply:
        print(f"==> {len(drifted)} README(s) drifted. Run with --fix to update.")
        return 1
    print(f"==> {len(drifted)} README(s) updated successfully.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI dispatcher for docgen sentinel verification and updates."""
    parser = argparse.ArgumentParser(description="Sentinel docgen tool.")
    parser.add_argument("--check", action="store_true", help="Verify sentinels.")
    parser.add_argument("--fix", action="store_true", help="Update sentinels in place.")
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    return scan_all_readmes(root, apply=args.fix)


if __name__ == "__main__":
    sys.exit(main())
