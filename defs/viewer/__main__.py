"""``python -m defs.viewer`` — serve the local, read-only dataset viewer."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m defs.viewer",
        description="Serve the read-only dataset viewer (API + built UI).",
    )
    parser.add_argument(
        "--artifacts-root",
        default=None,
        help="artifacts workspace (default: ARTIFACTS_ROOT or .artifacts)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8500)
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="serve the API without built UI (pair with `bun run dev`)",
    )
    args = parser.parse_args()

    import uvicorn

    from .server import create_app

    app = create_app(Path(args.artifacts_root) if args.artifacts_root else None)
    print(f"Serving viewer on http://{args.host}:{args.port}")
    if args.api_only:
        print("API-only mode: UI expected from `bun run dev` (vite proxy).")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
