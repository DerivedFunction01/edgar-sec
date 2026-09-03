"""Render selected document cases into one source-first review file."""

from __future__ import annotations

import argparse
from pathlib import Path

from defs.storage import atomic_write_text

from ..testing.corpus import find_document_cases
from ..testing.review import run_document_case, write_review_artifacts


def _ids(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument("--id", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    ids = list(args.id) + _ids(args.ids_file)
    if not ids:
        parser.error("one of --ids-file or --id is required")
    records = find_document_cases(ids=ids, path=args.corpus)
    missing = sorted(set(ids) - {record["document_id"] for record in records})
    if missing:
        parser.error(f"unknown document ID(s): {', '.join(missing)}")
    sections = []
    for record in records:
        result = run_document_case(record)
        sections.append(
            Path(args.output).parent / ".document-review-temp" / result.document_id
        )
        output_dir = sections[-1]
        write_review_artifacts(
            result,
            output_dir,
            expected_output=record.get("expected_output"),
            expected_metadata=record.get("expected_metadata"),
        )
    text = "\n\n".join(
        (path / f"{path.name}.txt").read_text(encoding="utf-8") for path in sections
    )
    atomic_write_text(args.output, text + "\n")
    print(f"wrote {len(records)} document reviews to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
