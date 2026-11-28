"""Family board scoring: the three basis forms and fidelity."""

import json

from edgar_sec.tools.measurement.board import (
    fidelity_diff,
    joint_objective,
    load_basis,
    main,
    run_score,
    score_board,
)


def _write(path, payload):
    path.write_text(json.dumps(payload))
    return path


def _packet(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_frame_form_board():
    basis = {
        "family": "intangibles",
        "keying": "bare",
        "members": {"m1", "m2", "m3", "m4"},
        "falses": {"f1", "f2"},
        "truth": {},
    }
    board = score_board({"m1", "m2", "m3", "f1"}, {"m1", "m2", "m3", "f1"}, basis)
    assert board["members_named"] == 4
    assert board["members"] == 3
    assert board["member_claims"] == 3
    assert board["true_claims"] == 3
    assert board["false_claims"] == 1
    assert board["fn"] == 0
    assert board["P"] == 0.75
    assert board["R"] == 1.0
    assert board["missed_member_names"] == []
    assert board["members_not_in_packet"] == ["m4"]


def test_truth_form_board():
    basis = {
        "family": "fair_value",
        "keying": "bare",
        "members": {"a", "b", "c", "d"},
        "falses": set(),
        "truth": {
            "a": "fair_value",
            "b": "fair_value",
            "c": "fair_value",
            "d": "fair_value",
            "x": "fair_value",
            "y": "pension",
        },
    }
    board = score_board({"a", "b", "x", "y"}, {"a", "b", "c", "d", "x", "y"}, basis)
    assert board["member_claims"] == 2
    assert board["true_claims"] == 3
    assert board["false_claims"] == 1
    assert board["fn"] == 2
    assert board["P"] == 0.75
    assert board["R"] == 0.5


def test_labels_form_full_keying(tmp_path):
    basis_path = _write(
        tmp_path / "basis.json",
        {
            "family": "lease_maturity",
            "keying": "full",
            "members": ["k1#0", "k2#0", "k3#0"],
            "truth": {
                "k1#0": "lease_maturity",
                "k2#0": "lease_maturity",
                "k3#0": "lease_maturity",
                "k4#0": "other",
            },
        },
    )
    packet = _packet(
        tmp_path / "rows.jsonl",
        [
            {"specimen": "k1#0", "claims": ["lease_maturity"]},
            {"specimen": "k2#0", "claims": []},
            {"specimen": "k3#0", "claims": ["debt_maturity"]},
            {"specimen": "k4#0", "claims": ["lease_maturity"]},
        ],
    )
    board = run_score(packet, load_basis(basis_path))
    assert board["member_claims"] == 1
    assert board["true_claims"] == 1
    assert board["false_claims"] == 1
    assert board["fn"] == 2
    assert board["P"] == 0.5
    assert board["R"] == 0.3333


def test_bare_keying_collapses_occurrences(tmp_path):
    basis_path = _write(
        tmp_path / "basis.json",
        {
            "family": "intangibles",
            "keying": "bare",
            "members": ["acc:1"],
            "falses": [],
        },
    )
    packet = _packet(
        tmp_path / "rows.jsonl",
        [
            {"specimen": "acc:1#0", "claims": ["intangibles"]},
            {"specimen": "acc:1#1", "claims": ["intangibles"]},
            {"specimen": "acc:2#0", "claims": []},
        ],
    )
    board = run_score(packet, load_basis(basis_path))
    assert board["member_claims"] == 1
    assert board["fn"] == 0
    assert board["members_not_in_packet"] == []


def test_claims_record_with_corpus_universe(tmp_path):
    basis_path = _write(
        tmp_path / "basis.json",
        {
            "family": "segment_reporting",
            "keying": "bare",
            "members": ["m1", "m2", "m3"],
            "truth": {"m1": "segment_reporting", "m2": "segment_reporting",
                      "m3": "segment_reporting", "x": "pension"},
        },
    )
    packet = _packet(
        tmp_path / "rows.jsonl",
        [
            {"specimen": "m1#0", "claims": ["segment_reporting"]},
            {"specimen": "x#0", "claims": ["segment_reporting"]},
        ],
    )
    universe = _packet(
        tmp_path / "population.jsonl",
        [
            {"specimen_id": "m1#0"},
            {"specimen_id": "m2#0"},
            {"specimen_id": "m3#0"},
            {"specimen_id": "x#0"},
        ],
    )
    board = run_score(packet, load_basis(basis_path), universe)
    assert board["members"] == 3
    assert board["member_claims"] == 1
    assert board["fn"] == 2
    assert board["R"] == 0.3333
    record_only = run_score(packet, load_basis(basis_path))
    assert record_only["members"] == 1
    assert record_only["members_not_in_packet"] == ["m2", "m3"]


def test_joint_objective_points_of_record():
    assert round(joint_objective(171 / 176, 171 / 184), 4) == 0.9200
    assert round(joint_objective(172 / 180, 172 / 184), 4) == 0.9200
    assert joint_objective(0.6923, 0.7083) == 0.90


def test_fidelity_diff():
    board = {"member_claims": 111, "false_claims": 1, "fn": 4, "P": 0.9911, "R": 0.9652}
    expected = {
        "member_claims": 111,
        "false_claims": 1,
        "fn": 4,
        "P": 0.9911,
        "R": 0.9652,
    }
    assert fidelity_diff(board, expected) == []
    assert fidelity_diff(board, {"P": 0.99}) == [
        {"cell": "P", "got": 0.9911, "want": 0.99}
    ]


def test_cli_score_and_verify(tmp_path):
    basis_path = _write(
        tmp_path / "basis.json",
        {
            "family": "intangibles",
            "keying": "bare",
            "members": ["m1", "m2"],
            "falses": ["f1"],
        },
    )
    packet = _packet(
        tmp_path / "rows.jsonl",
        [
            {"specimen": "m1#0", "claims": ["intangibles"]},
            {"specimen": "f1#0", "claims": ["intangibles"]},
        ],
    )
    out = tmp_path / "board.json"
    assert main(["score", str(packet), str(basis_path), "--out", str(out)]) == 0
    board = json.loads(out.read_text())
    assert board["member_claims"] == 1
    assert board["false_claims"] == 1
    expected = _write(
        tmp_path / "expected.json",
        {"member_claims": 1, "false_claims": 1, "fn": 0, "P": 0.5, "R": 1.0},
    )
    assert main(["verify", str(packet), str(basis_path), str(expected)]) == 0
    wrong = _write(tmp_path / "wrong.json", {"member_claims": 2})
    assert main(["verify", str(packet), str(basis_path), str(wrong)]) == 1
