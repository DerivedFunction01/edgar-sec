"""Tests for ASCII Form 4 layout shape classifier."""

from edgar_sec.engine.forms.ownership.ascii_shape import (
    AsciiShape,
    detect_ascii_shape,
)


def test_detect_pipe_underscore() -> None:
    text = "<TABLE>\nTable I\n|Col1|Col2|\n_________________________\n</TABLE>"
    assert detect_ascii_shape(text) == AsciiShape.PIPE_UNDERSCORE


def test_detect_box_plus() -> None:
    text = "<TABLE>\n+----------+----------+\n|  Item 1  |  Item 2  |\n</TABLE>"
    assert detect_ascii_shape(text) == AsciiShape.BOX_PLUS


def test_detect_sc_dash() -> None:
    text = "<TABLE>\n<S><C><C>\nTable I\n-------------------------\n</TABLE>"
    assert detect_ascii_shape(text) == AsciiShape.SC_DASH_RULES


def test_detect_stanzas() -> None:
    text = "1. Title of Security : Common Stock\n2. Transaction Date (Month/Day/Year) : 1/2/03\n"
    assert detect_ascii_shape(text) == AsciiShape.STANZAS


def test_detect_narrative() -> None:
    text = "INFORMATION REGARDING JOINT FILERS AND OTHER ENTITIES\nParent of NB Holdings Corporation\n"
    assert detect_ascii_shape(text) == AsciiShape.NARRATIVE
