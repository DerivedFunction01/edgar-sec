"""Settings registry CLI: generate a documented ``.env`` template.

Consumes the same collected specs used for normal resolution, so generated
names always match what the runtime reads. Secret settings are never
written; machine-derived defaults render as commented suggestions so a
workspace does not freeze one machine's resources.

Usage via the root launcher:

    python run.py settings generate-dotenv [--path PATH] [--force] [--phase ID]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from defs.runtime.settings import (
    MISSING,
    collect_specs,
    environment_name,
    render_dotenv,
    resolve_settings,
)

DEFAULT_GENERATED_PATH = ".env"


def generate_dotenv(
    path: str | os.PathLike[str] = DEFAULT_GENERATED_PATH,
    *,
    force: bool = False,
    phase: str | None = None,
) -> str:
    """Atomically write a documented dotenv template; return the path.

    Refuses to overwrite an existing file unless ``force`` is set.
    """
    target = Path(path)
    if target.exists() and not force:
        raise ValueError(f"{target} already exists; pass --force to overwrite")
    specs = collect_specs(phase)
    # Specs whose default is MISSING expect a caller-provided value; the
    # template renders them as commented empty suggestions. This stays
    # spec-model-driven: no application-specific names live here.
    resolved = resolve_settings(
        phase,
        fallbacks={
            spec_path: ""
            for spec_path, spec in specs.items()
            if spec.default is MISSING
        },
    )
    text = render_dotenv(specs, resolved)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=".env-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="ascii", errors="backslashreplace") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, str(target))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return str(target)


def _summary(specs: dict, phase: str | None) -> list[str]:
    secrets = [p for p, s in specs.items() if s.secret]
    machine = [p for p, s in specs.items() if callable(s.default)]
    lines = [
        f"settings included: {len(specs)}"
        + (f" (phase: {phase})" if phase else " (shared only)"),
        f"secrets omitted: {len(secrets)}",
    ]
    for path in sorted(secrets):
        lines.append(f"  omitted secret: {environment_name(path)}")
    lines.append(f"machine-derived suggestions (commented): {len(machine)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="settings", description=__doc__.splitlines()[0]
    )
    commands = parser.add_subparsers(dest="command")
    generate = commands.add_parser(
        "generate-dotenv", help="write a documented .env template from the specs"
    )
    generate.add_argument(
        "--path", default=DEFAULT_GENERATED_PATH, help="target file (default: .env)"
    )
    generate.add_argument(
        "--force", action="store_true", help="overwrite an existing file"
    )
    generate.add_argument(
        "--phase",
        default=None,
        help="include a phase's settings in addition to shared settings",
    )
    args = parser.parse_args(argv)
    # `python run.py settings` (menu selection) passes no command; default to
    # the template generator so the click does something useful. Without a
    # subparser the generate-only options are absent, so fall back to defaults.
    command = args.command or "generate-dotenv"
    if command == "generate-dotenv":
        path = getattr(args, "path", DEFAULT_GENERATED_PATH)
        force = getattr(args, "force", False)
        phase = getattr(args, "phase", None)
        try:
            written = generate_dotenv(path, force=force, phase=phase)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        specs = collect_specs(phase)
        for line in _summary(specs, phase):
            print(line)
        print(f"wrote: {written}")
        return 0
    parser.error(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
