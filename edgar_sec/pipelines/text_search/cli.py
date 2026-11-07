"""Command surface for the text index build pipeline."""

from __future__ import annotations

import sys

from edgar_sec.infra.storage.text_index import TextIndexStore

from .builder import build_index
from .options import build_parser, options_from_args

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Run one text_search command."""
    args = build_parser().parse_args(argv)
    options = options_from_args(args)
    if args.command == "build":
        result = build_index(options)
        print(
            f"payloads={result.payload_count} new={result.new_payload_count} "
            f"reused={result.reused_payload_count} "
            f"documents={result.document_count} chunks={result.chunk_count} "
            f"postings={result.posting_count} terms={result.term_count} "
            f"wall={result.wall_seconds:.1f}s index={result.index_root}"
        )
        return 0
    if args.command == "status":
        store = TextIndexStore(options.resolved_index_root())
        stats = store.corpus_stats()
        if stats is None:
            print("no index stored")
            return 0
        print(
            f"snapshot={stats['source_snapshot_id']} "
            f"accessions={stats['accession_count']} "
            f"documents={stats['document_count']} "
            f"payloads={stats['payload_count']} chunks={stats['chunk_count']} "
            f"postings={stats['posting_count']} built={stats['built_at']}"
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
