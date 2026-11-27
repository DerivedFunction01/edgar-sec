"""Census pricing: feature inventory, kills/touches, residual."""

from __future__ import annotations

import json

from edgar_sec.tools.table_extraction_corpus.census_pricing import (
    main,
    price_population,
    specimen_features,
)

ROLLFORWARD = (
    " | 2023 | 2024\n"
    "Balance at beginning of period | 100 | 120\n"
    "Additions | 30 | 10\n"
    "Deductions | 10 | 5\n"
    "Balance at end of period | 120 | 125"
)
PROSE_TABLE = (
    "Narrative summary | Notes\n"
    "The committee met quarterly | discussion\n"
    "No amounts are reported here | narrative"
)


def _row(sid, family, side, table_text, *, text_source="primary"):
    return {
        "sid": sid,
        "family": family,
        "side": side,
        "table_text": table_text,
        "caption_stack": ["Note 1 - Summary"],
        "prose_before": "The following table presents the activity.",
        "prose_after": "See accompanying notes.",
        "text_source": text_source,
        "final_class": None,
        "mechanism": None,
        "true_family": None,
    }


def _population():
    rows = [
        _row(f"1000000001-24-00000{i}:1", "alpha", "true", ROLLFORWARD)
        for i in range(4)
    ]
    rows += [
        _row(f"2000000002-24-00000{i}:2", "alpha", "false", PROSE_TABLE)
        for i in range(2)
    ]
    rows.append(_row("3000000003-24-000001:3", "beta", "true", ROLLFORWARD))
    rows.append(
        _row("4000000004-24-000001:4", "alpha", "true", "", text_source=None)
    )
    return rows


def test_specimen_features_reads_bookends_and_totals():
    feats = specimen_features(_row("1-1:1", "alpha", "true", ROLLFORWARD))
    assert feats["has_bookend_pair"] == 1
    assert feats["n_rows"] == 5
    assert feats["stub:balance at beginning of period"] == 1
    assert feats["move_density"] > 0


def test_price_population_prices_and_names_residual():
    register = price_population(_population())
    alpha = register["alpha"]
    assert alpha["n_falses"] == 2
    assert alpha["n_trues"] == 4
    assert alpha["best_combo"]
    assert all(
        r["sid"].startswith("2000000002") for r in alpha["residual"]
    )
    single = alpha["singles"][0]
    assert set(single) >= {"feature", "dir", "kills", "touches"}
    assert register["beta"]["note"] == "no falses on this population"
    assert "4000000004" not in json.dumps(register)


def test_main_round_trips_a_population_file(tmp_path):
    rows = _population()
    pop = tmp_path / "population.jsonl"
    pop.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "pricing.json"
    assert main([str(pop), str(out)]) == 0
    assert json.loads(out.read_text()) == price_population(rows)
