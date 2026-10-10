"""Interactive entrypoint for acquisition command tracks."""

from __future__ import annotations

import argparse
import sys

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    build_menu,
    menu_action,
    operator_entrypoint,
)
from edgar_sec.pipelines.document_acquisition.cli import (
    main as cli_main,
    report_not_implemented,
)

MENU_TITLE = "Document Acquisition"


def _action(command: str, track: str) -> MenuAction:
    return menu_action(
        track,
        lambda: report_not_implemented(command),
    )


def build_operator_menu() -> tuple[MenuAction, ...]:
    return build_menu(
        _action("project", "Project a target plan (not implemented)"),
        _action("status", "Inspect acquisition runs (not implemented)"),
        _action("run", "Acquire pending bodies (not implemented)"),
        _action("process", "Process acquired bodies (not implemented)"),
        _action("publish", "Publish snapshot (S11 gate)"),
        _action("fixture list", "S9 fixtures console (capture, list, replay)"),
        _action("review build", "Review artifact console (build, compare)"),
        _action("snapshot status", "Snapshot status/evidence audit (S11 gate)"),
    )


def main(argv: list[str] | None = None) -> int:
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
