"""Debug the HTML table conversion pipeline for one source document."""

from __future__ import annotations

import argparse
from pathlib import Path

from defs.tables import convert_html_tables_to_ascii


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Read HTML from a file")
    source.add_argument("--html", help="Convert inline HTML text")
    parser.add_argument(
        "--write-output",
        type=Path,
        help="Write converted document to this path instead of stdout",
    )
    args = parser.parse_args()

    html = args.file.read_text(encoding="utf-8") if args.file else args.html
    converted = convert_html_tables_to_ascii(html, debug=True)
    if args.write_output:
        args.write_output.write_text(converted, encoding="utf-8")
    else:
        print(converted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
