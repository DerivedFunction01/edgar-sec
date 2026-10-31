"""Flat 1D typed document block stream domain models."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum


class BlockKind(StrEnum):
    """Semantic block classification for normalized documents."""

    PARAGRAPH = "paragraph"
    TABLE = "table"
    PRESERVED = "preserved"
    PAGE_BREAK = "page_break"


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    """One immutable contiguous block of text within a normalized document."""

    block_index: int
    kind: BlockKind
    text: str
    raw_lines: tuple[str, ...]
    char_start: int
    char_end: int

    @property
    def line_count(self) -> int:
        return len(self.raw_lines)

    @property
    def is_table(self) -> bool:
        return self.kind == BlockKind.TABLE


@dataclass(frozen=True, slots=True)
class BlockStream:
    """An ordered, immutable sequence of DocumentBlocks representing an entire document."""

    blocks: tuple[DocumentBlock, ...]

    def __len__(self) -> int:
        return len(self.blocks)

    def __iter__(self) -> Iterator[DocumentBlock]:
        return iter(self.blocks)

    def __getitem__(self, index: int) -> DocumentBlock:
        return self.blocks[index]

    def filter_kind(self, kind: BlockKind) -> tuple[DocumentBlock, ...]:
        """Return all blocks matching the given kind."""
        return tuple(b for b in self.blocks if b.kind == kind)

    @property
    def tables(self) -> tuple[DocumentBlock, ...]:
        return self.filter_kind(BlockKind.TABLE)

    @property
    def paragraphs(self) -> tuple[DocumentBlock, ...]:
        return self.filter_kind(BlockKind.PARAGRAPH)

    def to_full_text(self, block_separator: str = "\n\n") -> str:
        """Reconstruct full document text by joining block texts."""
        return block_separator.join(b.text for b in self.blocks if b.text)


__all__ = [
    "BlockKind",
    "BlockStream",
    "DocumentBlock",
]
