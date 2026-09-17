"""Contract tests for allocation-free text counters."""

from defs.text import count_lines, count_words


def test_count_words_matches_split():
    samples = [
        "",
        "   ",
        "one two three",
        "  leading and trailing  ",
        "tabs\tand\nnewlines\r\nand\x0bforms",
        "ünïcodé ✓ 一二三",
    ]
    for text in samples:
        assert count_words(text) == len(text.split())


def test_count_lines_matches_splitlines_for_newline_text():
    samples = [
        "",
        "single",
        "two\nlines",
        "trailing newline\n",
        "a\nb\nc\nd",
    ]
    for text in samples:
        assert count_lines(text) == len(text.splitlines())
