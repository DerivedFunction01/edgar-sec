"""Section corpus: the detector over the simplified specimen set.

The specimens are skeleton texts under ``simplified/`` beside this
corpus's taxonomies: each carries one named detector behaviour (a
family's section-sequence shape, a TOC-span or pseudo-TOC case, a
run-in, wrapped, colon, parenthesized, table-row, or composite
heading form, or a control case) with the expected resolutions the
banked corpus's index carried for that behaviour. Banking and
conventions: the corpus README beside the fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from tests.support.fixtures import fixture_path

_CORPUS = fixture_path("engine/forms/sections/section_corpus")
_SIMPLIFIED = _CORPUS / "simplified"

# Families whose profiles opt into run-in section titles; the corpus
# builder (edgar_sec.tools.section_corpus) applies the same convention.
_RUN_IN_FAMILIES = frozenset({"form_n23c3"})


def _taxonomies() -> dict[str, tuple[ItemDefinition, ...]]:
    raw = json.loads((_CORPUS / "taxonomies.json").read_text(encoding="utf-8"))
    return {
        slug: tuple(
            ItemDefinition(
                item=it["item"],
                part=it["part"],
                names=tuple(it["names"]),
                optional=it["optional"],
                early=it["early"],
            )
            for it in items
        )
        for slug, items in raw.items()
    }


_TAXONOMIES = _taxonomies()
_SPECIMENS = json.loads((_SIMPLIFIED / "specimens.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "specimen", _SPECIMENS, ids=[s["id"] for s in _SPECIMENS]
)
def test_specimen_resolutions_match_expectations(specimen: dict) -> None:
    text = (_SIMPLIFIED / specimen["text"]).read_text(encoding="utf-8")
    toc_span = tuple(specimen["toc_span"]) if specimen["toc_span"] else None
    seq = detect_section_sequence(
        text,
        family=specimen["family"],
        taxonomy_items=_TAXONOMIES[specimen["family"]],
        toc_span=toc_span,
        run_in_titles=specimen["family"] in _RUN_IN_FAMILIES,
    )
    assert [s.item_identifier for s in seq.sections] == specimen["expected"]


def test_specimen_set_is_complete_and_consistent() -> None:
    ids = [s["id"] for s in _SPECIMENS]
    assert len(ids) == len(set(ids))
    covered = {s["family"] for s in _SPECIMENS}
    assert covered == set(_TAXONOMIES)
    for specimen in _SPECIMENS:
        text_path = _SIMPLIFIED / specimen["text"]
        assert text_path.is_file() and text_path.stat().st_size > 0
        assert Path(specimen["text"]).name == specimen["text"]
        known = {
            f"ITEM {item.item}" for item in _TAXONOMIES[specimen["family"]]
        }
        assert set(specimen["expected"]) <= known
