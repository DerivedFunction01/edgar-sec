"""Tests for the cross-form census summary and scoring gate."""

from edgar_sec.engine.xbrl.review.cross_form import (
    FACT_EXPECTATIONS,
    CrossFormExpectation,
    FactExpectation,
    block_key,
    score_cross_form,
    score_fact_matrix,
    summarize_cross_form,
)


def _evaluation(
    form: str = "10-K",
    taxonomy: str = "us-gaap",
    period_shape: str = "FY",
    classification: str = "correct",
    status: str = "REPORTED",
    quarantined_facts: int = 0,
    replay_mismatch: bool = False,
    population: str = "cross-form",
) -> dict:
    """One minimal cross-form evaluation record."""
    return {
        "population": population,
        "firm": "msft",
        "form": form,
        "taxonomy": taxonomy,
        "period_shape": period_shape,
        "classification": classification,
        "facade": {"status": status, "value": 1.0},
        "replay_mismatch": replay_mismatch,
        "quarantined_facts": quarantined_facts,
    }


def _expectation(
    posture: str = "measured",
    n: int = 2,
    correct: int = 1,
    honest: int = 1,
    surfaced_conflicts: int = 0,
    form: str = "10-K",
    taxonomy: str = "us-gaap",
    period_shape: str = "FY",
) -> CrossFormExpectation:
    """One expectation for the default synthetic block."""
    return CrossFormExpectation(
        form=form,
        taxonomy=taxonomy,
        period_shape=period_shape,
        posture=posture,
        n=n,
        correct=correct,
        honest=honest,
        surfaced_conflicts=surfaced_conflicts,
    )


def test_summarize_cross_form_groups_blocks() -> None:
    """Summaries group by block, sum quarantines, ignore other populations."""
    evaluations = [
        _evaluation(status="CONFLICT", quarantined_facts=2),
        _evaluation(classification="honest-faithful", quarantined_facts=3),
        _evaluation(
            classification="wrong-value", quarantined_facts=0, replay_mismatch=True
        ),
        _evaluation(form="10-Q", period_shape="Q", quarantined_facts=5),
        _evaluation(population="probe", quarantined_facts=7),
    ]
    blocks = summarize_cross_form(evaluations)["blocks"]
    assert set(blocks) == {
        block_key("10-K", "us-gaap", "FY"),
        block_key("10-Q", "us-gaap", "Q"),
    }
    annual = blocks[block_key("10-K", "us-gaap", "FY")]
    assert annual["form"] == "10-K"
    assert annual["taxonomy"] == "us-gaap"
    assert annual["period_shape"] == "FY"
    assert annual["n"] == 3
    assert annual["solved"] == 1
    assert annual["honest"] == 1
    assert annual["conflict"] == 1
    assert annual["quarantined_facts"] == 5
    assert annual["adverse"] == {"wrong-value": 1}
    assert annual["replay_mismatches"] == 1
    quarterly = blocks[block_key("10-Q", "us-gaap", "Q")]
    assert quarterly["n"] == 1
    assert quarterly["solved"] == 1
    assert quarterly["quarantined_facts"] == 5


def test_score_cross_form_passes_exact_expectations() -> None:
    """Scoring passes when every block matches its expectation exactly."""
    evaluations = [
        _evaluation(),
        _evaluation(classification="honest-faithful"),
    ]
    key = block_key("10-K", "us-gaap", "FY")
    score = score_cross_form(summarize_cross_form(evaluations), {key: _expectation()})
    assert score.passed
    assert score.failures == ()


def test_score_cross_form_names_moved_correct_count() -> None:
    """A moved correct count fails, naming the actual and expected counts."""
    evaluations = [
        _evaluation(),
        _evaluation(classification="honest-faithful"),
    ]
    key = block_key("10-K", "us-gaap", "FY")
    score = score_cross_form(
        summarize_cross_form(evaluations), {key: _expectation(correct=2)}
    )
    assert not score.passed
    assert any(
        failure == f"{key}: correct 1 != expected 2" for failure in score.failures
    )


def test_score_cross_form_absence_posture_rejects_solved() -> None:
    """An absence block serving any solved value fails the gate."""
    key = block_key("10-K", "us-gaap", "FY")
    expectation = _expectation(posture="absence", n=1, correct=1, honest=0)
    score = score_cross_form(summarize_cross_form([_evaluation()]), {key: expectation})
    assert not score.passed
    assert any(failure == f"{key}: absence solved 1 != 0" for failure in score.failures)


def test_score_cross_form_adverse_baseline_is_exact() -> None:
    """A pinned adverse baseline passes exactly; movement either way fails."""
    evaluations = [
        _evaluation(classification="refused", replay_mismatch=True),
        _evaluation(classification="honest-faithful"),
    ]
    key = block_key("10-K", "us-gaap", "FY")
    pinned = CrossFormExpectation(
        form="10-K",
        taxonomy="us-gaap",
        period_shape="FY",
        posture="measured",
        n=2,
        correct=0,
        honest=1,
        surfaced_conflicts=0,
        adverse={"refused": 1},
        replay_mismatches=1,
    )
    summary = summarize_cross_form(evaluations)
    assert score_cross_form(summary, {key: pinned}).passed
    moved = score_cross_form(summary, {key: _expectation()})
    assert not moved.passed
    assert any("adverse" in failure for failure in moved.failures)


def test_summarize_cross_form_counts_mixed_population_as_adverse() -> None:
    """A mixed-population pair answer lands in the block's adverse counts."""
    evaluations = [
        _evaluation(form="10-Q+10-Q/A", classification="mixed-population"),
        _evaluation(form="10-Q+10-Q/A"),
    ]
    blocks = summarize_cross_form(evaluations)["blocks"]
    block = blocks[block_key("10-Q+10-Q/A", "us-gaap", "FY")]
    assert block["adverse"] == {"mixed-population": 1}
    assert block["solved"] == 1


def test_score_cross_form_missing_block_fails() -> None:
    """An expectation whose block is absent from the summary fails."""
    key = block_key("10-K", "us-gaap", "FY")
    score = score_cross_form({"blocks": {}}, {key: _expectation()})
    assert not score.passed
    assert any("block missing from summary" in f for f in score.failures)


def _fact_row(
    filings: int = 2,
    facts: int = 270,
    numeric_facts: int = 209,
    dimensioned_numeric: int = 146,
    quarantined_facts: int = 146,
) -> dict:
    """One synthetic fact-matrix row in the summary's shape."""
    return {
        "form": "DEF 14A",
        "taxonomy": "ecd",
        "period_shape": "annual",
        "filings": filings,
        "facts": facts,
        "numeric_facts": numeric_facts,
        "dimensioned_numeric": dimensioned_numeric,
        "quarantined_facts": quarantined_facts,
    }


def _fact_expectation(**overrides) -> FactExpectation:
    """The pinned expectation matching the synthetic fact row."""
    fields = {
        "form": "DEF 14A",
        "taxonomy": "ecd",
        "period_shape": "annual",
        "filings": 2,
        "facts": 270,
        "numeric_facts": 209,
        "dimensioned_numeric": 146,
        "quarantined_facts": 146,
    }
    fields.update(overrides)
    return FactExpectation(**fields)


def test_fact_expectations_cover_every_closed_set() -> None:
    """The pinned fact rows name each closed-set taxonomy's accounting."""
    taxonomies = {row.taxonomy for row in FACT_EXPECTATIONS.values()}
    assert {"ecd", "cyd", "rxp", "cef", "us-gaap-ebp", "oef"} <= taxonomies
    for key, row in FACT_EXPECTATIONS.items():
        assert key == block_key(row.form, row.taxonomy, row.period_shape)


def test_score_fact_matrix_passes_exact_rows() -> None:
    """Fact scoring passes when every pinned row matches exactly."""
    key = block_key("DEF 14A", "ecd", "annual")
    summary = {"fact_matrix": {key: _fact_row()}}
    score = score_fact_matrix(summary, {key: _fact_expectation()})
    assert score.passed
    assert score.failures == ()


def test_score_fact_matrix_names_moved_counts() -> None:
    """A moved fact count fails, naming the field and both counts."""
    key = block_key("DEF 14A", "ecd", "annual")
    summary = {"fact_matrix": {key: _fact_row(facts=271)}}
    score = score_fact_matrix(summary, {key: _fact_expectation()})
    assert not score.passed
    assert any(
        failure == f"fact {key}: facts 271 != expected 270"
        for failure in score.failures
    )


def test_score_fact_matrix_missing_row_fails() -> None:
    """A pinned row absent from the fact matrix fails the gate."""
    key = block_key("DEF 14A", "ecd", "annual")
    score = score_fact_matrix({"fact_matrix": {}}, {key: _fact_expectation()})
    assert not score.passed
    assert any("row missing from fact matrix" in f for f in score.failures)
