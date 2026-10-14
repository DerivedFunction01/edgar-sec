"""CLI entry point for high-throughput end-to-end filing acquisition."""

from __future__ import annotations

import argparse
import json
import sys

from edgar_sec.apps.client.facade import Edgar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch",
        description="Acquire and process SEC filings end-to-end into DataFrames",
    )
    parser.add_argument("--forms", nargs="+", help="Filing form types")
    parser.add_argument("--ciks", nargs="+", help="Company CIKs")
    parser.add_argument("--dates", help="Date selection range (e.g. 2024)")
    parser.add_argument("--limit", type=int, help="Maximum accessions to acquire")
    parser.add_argument(
        "--role",
        default="primary",
        help="Target role: primary or exhibit type",
    )
    parser.add_argument(
        "--operation",
        default="raw",
        choices=["raw", "render_to_xml", "render_to_txt"],
        help="Acquisition operation",
    )
    parser.add_argument("--json", action="store_true", help="Output summary as JSON")

    args = parser.parse_args(argv)

    edgar = Edgar()
    results = edgar.fetch(
        forms=args.forms or (),
        ciks=args.ciks or (),
        dates=args.dates,
        role=args.role,
        limit=args.limit,
        operation=args.operation,
    )

    if args.json:
        payload = {
            "run_id": results.run_id,
            "plan_id": results.plan_id,
            "accession_count": len(results),
            "status": "complete",
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"Acquired {len(results)} accessions into run {results.run_id}")
        print(results.to_df())
    return 0


if __name__ == "__main__":
    sys.exit(main())
