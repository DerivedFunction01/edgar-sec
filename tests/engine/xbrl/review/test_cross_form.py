"""Tests for the cross-form census summary and scoring gate."""

from edgar_sec.engine.xbrl.review.cross_form import (
    DEI_PRESENCE_EXPECTATIONS,
    FACT_EXPECTATIONS,
    K1_EXPECTATIONS,
    CrossFormExpectation,
    DeiPresenceExpectation,
    FactExpectation,
    K1Expectation,
    block_key,
    score_cross_form,
    score_dei_presence,
    score_fact_matrix,
    score_k1,
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


def _k1_row(**overrides) -> dict:
    """One synthetic K1 block row in the summary's shape."""
    fields = {
        "form": "10-K",
        "taxonomy": "us-gaap",
        "filings": 119,
        "k1_facts": 10,
        "no_calc_role": 6,
        "in_calc_arcs": 4,
        "per_share": 1,
        "schedule": 0,
        "breakdown_served": 5,
        "calc_component": 3,
        "orphan": 1,
    }
    fields.update(overrides)
    return fields


def _k1_expectation(**overrides) -> K1Expectation:
    """The pinned expectation matching the synthetic K1 row."""
    fields = {
        "form": "10-K",
        "taxonomy": "us-gaap",
        "filings": 119,
        "k1_facts": 10,
        "no_calc_role": 6,
        "in_calc_arcs": 4,
        "per_share": 1,
        "schedule": 0,
        "breakdown_served": 5,
        "calc_component": 3,
        "orphan": 1,
    }
    fields.update(overrides)
    return K1Expectation(**fields)


def test_k1_expectations_partition_the_pinned_mass() -> None:
    """Every pinned K1 block's dispositions and calc split sum to its mass."""
    assert len(K1_EXPECTATIONS) >= 50
    for key, row in K1_EXPECTATIONS.items():
        assert key == f"{row.form}|{row.taxonomy}"
        dispositions = (
            row.per_share
            + row.schedule
            + row.breakdown_served
            + row.calc_component
            + row.orphan
        )
        assert dispositions == row.k1_facts
        assert row.no_calc_role + row.in_calc_arcs == row.k1_facts


def test_score_k1_passes_exact_blocks() -> None:
    """K1 scoring passes when every pinned block matches exactly."""
    key = "10-K|us-gaap"
    score = score_k1({"k1_blocks": {key: _k1_row()}}, {key: _k1_expectation()})
    assert score.passed
    assert score.failures == ()


def test_score_k1_names_moved_mass() -> None:
    """A moved K1 count fails, naming the field and both counts."""
    key = "10-K|us-gaap"
    summary = {"k1_blocks": {key: _k1_row(orphan=2)}}
    score = score_k1(summary, {key: _k1_expectation()})
    assert not score.passed
    assert any(
        failure == f"k1 {key}: orphan 2 != expected 1" for failure in score.failures
    )


def test_score_k1_missing_block_fails() -> None:
    """A pinned K1 block absent from the census fails the gate."""
    key = "10-K|us-gaap"
    score = score_k1({"k1_blocks": {}}, {key: _k1_expectation()})
    assert not score.passed
    assert any("block missing from K1 census" in f for f in score.failures)


def _dei_row(**overrides) -> dict:
    """One synthetic dei presence row in the summary's shape."""
    fields = {
        "filings": 2,
        "present": {"DocumentType": 2, "DocumentPeriodEndDate": 1},
    }
    fields.update(overrides)
    return fields


def _dei_expectation(**overrides) -> DeiPresenceExpectation:
    """The pinned expectation matching the synthetic dei row."""
    fields = {
        "form": "8-K",
        "filings": 2,
        "present": {"DocumentType": 2, "DocumentPeriodEndDate": 1},
    }
    fields.update(overrides)
    return DeiPresenceExpectation(**fields)


def test_dei_presence_expectations_cover_the_probe_families() -> None:
    """Pinned families total the probe cohort; counts stay within filings."""
    assert sum(row.filings for row in DEI_PRESENCE_EXPECTATIONS.values()) == 90
    key_sets = {frozenset(row.present) for row in DEI_PRESENCE_EXPECTATIONS.values()}
    assert len(key_sets) == 1
    for row in DEI_PRESENCE_EXPECTATIONS.values():
        assert all(0 <= count <= row.filings for count in row.present.values())


def test_score_dei_presence_passes_exact_rows() -> None:
    """Dei presence scoring passes when every pinned family matches."""
    summary = {"dei_presence": {"8-K": _dei_row()}}
    score = score_dei_presence(summary, {"8-K": _dei_expectation()})
    assert score.passed
    assert score.failures == ()


def test_score_dei_presence_names_moved_presence() -> None:
    """A moved presence count fails, naming the family."""
    moved = {"DocumentType": 2, "DocumentPeriodEndDate": 2}
    summary = {"dei_presence": {"8-K": _dei_row(present=moved)}}
    score = score_dei_presence(summary, {"8-K": _dei_expectation()})
    assert not score.passed
    assert any(failure.startswith("dei 8-K: presence") for failure in score.failures)


def test_score_dei_presence_missing_family_fails() -> None:
    """A pinned family absent from the census fails the gate."""
    score = score_dei_presence({"dei_presence": {}}, {"8-K": _dei_expectation()})
    assert not score.passed
    assert any("family missing from census" in f for f in score.failures)
