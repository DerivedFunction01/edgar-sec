"""Unit tests for the normalization stage record."""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from edgar_sec.domain.forms.common.models import StageRecord


def test_stage_record_carries_stage_digest_and_counts() -> None:
    record = StageRecord.of("decode", "line one\nline two")
    assert record.stage == "decode"
    assert record.text_identity == hashlib.sha256(b"line one\nline two").hexdigest()
    assert record.line_count == 2
    assert record.char_count == 17


def test_empty_stage_output_counts_zero_lines() -> None:
    record = StageRecord.of("decode", "")
    assert record.line_count == 0
    assert record.char_count == 0
    assert record.text_identity == hashlib.sha256(b"").hexdigest()


def test_line_count_ignores_a_trailing_newline() -> None:
    assert StageRecord.of("whitespace", "a\nb\n").line_count == 2


def test_line_count_excludes_non_newline_separators() -> None:
    """`str.splitlines` splits on \\x0c and \\x0b, which are not lines here."""
    assert StageRecord.of("decode", "a\x0cb\x0bc").line_count == 1
    assert StageRecord.of("decode", "a\x0cb\x0bc").char_count == 5


def test_line_count_matches_splitlines_for_the_normalized_shape() -> None:
    for text in ("one", "one\ntwo", "one\ntwo\n", "a\n\nb"):
        assert StageRecord.of("decode", text).line_count == len(text.splitlines())


def test_digest_changes_with_the_output_and_not_with_the_stage_name() -> None:
    first = StageRecord.of("reflow", "alpha")
    renamed = StageRecord.of("whitespace", "alpha")
    changed = StageRecord.of("reflow", "beta")
    assert first.text_identity == renamed.text_identity
    assert first.text_identity != changed.text_identity


def test_to_dict_is_json_serializable_and_keeps_the_field_names() -> None:
    payload = json.loads(json.dumps(StageRecord.of("closing", "x\ny").to_dict()))
    assert payload == {
        "stage": "closing",
        "text_identity": hashlib.sha256(b"x\ny").hexdigest(),
        "line_count": 2,
        "char_count": 3,
    }


def test_to_dict_matches_asdict() -> None:
    record = StageRecord.of("toc", "body")
    assert record.to_dict() == dataclasses.asdict(record)


def test_record_is_frozen() -> None:
    record = StageRecord.of("decode", "x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.line_count = 99  # type: ignore[misc]


def test_records_are_comparable_so_two_runs_can_be_diffed() -> None:
    assert StageRecord.of("toc", "a") == StageRecord.of("toc", "a")
    assert StageRecord.of("toc", "a") != StageRecord.of("toc", "b")
