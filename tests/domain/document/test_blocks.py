from edgar_sec.domain.document.blocks import (
    BlockKind,
    BlockStream,
    DocumentBlock,
)


def test_document_block_properties() -> None:
    block = DocumentBlock(
        block_index=0,
        kind=BlockKind.PARAGRAPH,
        text="This is a test paragraph.",
        raw_lines=("This is a test paragraph.",),
        char_start=0,
        char_end=25,
    )
    assert not block.is_table
    assert block.line_count == 1
    assert block.kind == BlockKind.PARAGRAPH


def test_block_stream_operations() -> None:
    b1 = DocumentBlock(
        block_index=0,
        kind=BlockKind.PARAGRAPH,
        text="Introduction paragraph.",
        raw_lines=("Introduction paragraph.",),
        char_start=0,
        char_end=23,
    )
    b2 = DocumentBlock(
        block_index=1,
        kind=BlockKind.TABLE,
        text="<TABLE>\nCol1 | Col2\n</TABLE>",
        raw_lines=("<TABLE>", "Col1 | Col2", "</TABLE>"),
        char_start=25,
        char_end=54,
    )
    stream = BlockStream(blocks=(b1, b2))

    assert len(stream) == 2
    assert stream[0] == b1
    assert stream[1] == b2
    assert len(stream.tables) == 1
    assert len(stream.paragraphs) == 1
    assert stream.tables[0] == b2
    assert "Introduction paragraph." in stream.to_full_text()
    assert "<TABLE>" in stream.to_full_text()
