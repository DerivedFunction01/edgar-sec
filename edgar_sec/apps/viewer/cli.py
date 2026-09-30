"""Command entry for the dataset viewer.

Named ``cli`` to match the other three launch targets (``metadata_sync.operator``,
``filing_catalog.operator``, ``document_storage.cli``), so the root launcher's
module field means the same thing for every entry.

The bind address defaults to loopback, and that default is a *refusal* of remote
access rather than a default that happens to be local. A viewer over the artifacts
tree serves whole filings and whatever else a pipeline has published; binding it
to 0.0.0.0 by accident is much cheaper to design out than to notice later, so
``--host`` exists for deliberate override and nothing else changes it.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8500


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m edgar_sec.apps.viewer.cli",
        description="Serve the read-only dataset viewer (API + built UI).",
    )
    parser.add_argument(
        "--artifacts-root",
        default=None,
        help="artifacts workspace (default: the resolved project artifacts root)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"bind address (default: {DEFAULT_HOST}; remote binds are deliberate)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="serve the API without the built UI (pair with the vite dev server)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    import uvicorn

    from edgar_sec.apps.viewer.server import create_app

    logging.basicConfig(level=logging.WARNING)
    root = Path(args.artifacts_root) if args.artifacts_root else None
    app = create_app(root)

    print(f"Serving viewer on http://{args.host}:{args.port}")
    if args.api_only:
        print("API-only mode: UI expected from the vite dev server.")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"WARNING: bound to {args.host}, not loopback. This serves published "
            f"artifacts to the network with no authentication."
        )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
