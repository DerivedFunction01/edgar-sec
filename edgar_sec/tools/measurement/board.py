"""Family board scoring: packet claims against adjudicated bases.

Scores one family's claim packet (an emit's rows) against its
adjudicated basis — joint precision / recall / J over the basis
frame — and carries the fidelity form: a prior board of record
is reproduced from the same runner before a new board is read.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json

BAR = 0.90
_CELLS = ("member_claims", "true_claims", "false_claims", "fn", "P", "R", "J")


def joint_objective(precision: float, recall: float, bar: float = BAR) -> float:
    """The joint objective of record over one board's P and R.

    Each side is adjusted to the bar plus half its surplus over
    the bar (no surplus below the bar); the weaker adjusted side
    weighs threefold in the mean.
    """
    adjusted_p = bar + max(0.0, precision - bar) / 2.0
    adjusted_r = bar + max(0.0, recall - bar) / 2.0
    return (3.0 * min(adjusted_p, adjusted_r) + max(adjusted_p, adjusted_r)) / 4.0


def load_packet(packet_path: str | Path, family: str, keying: str) -> dict:
    """Read an emit rows file into one family's claim set.

    Returns the family's claimed specimen keys in the basis's
    keying (full occurrence keys, or bare keys without the
    occurrence ordinal) plus every specimen key the packet
    carries, in the same keying.
    """
    claimed: set[str] = set()
    universe: set[str] = set()
    for line in Path(packet_path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        specimen = row["specimen"]
        if keying == "bare":
            specimen = specimen.split("#")[0]
        universe.add(specimen)
        if family in (row.get("claims") or []):
            claimed.add(specimen)
    return {"claimed": claimed, "universe": universe}


def load_basis(basis_path: str | Path) -> dict:
    """Read a board basis: family, keying, members, falses, truth.

    Members and falses are specimen-key lists in the basis's
    keying; truth, when present, maps specimen keys to their
    adjudicated family label (the family's own name for members,
    another label for adjudicated non-members).
    """
    raw = json.loads(Path(basis_path).read_text())
    return {
        "family": raw["family"],
        "keying": raw.get("keying", "bare"),
        "members": set(raw.get("members") or []),
        "falses": set(raw.get("falses") or []),
        "truth": dict(raw.get("truth") or {}),
    }


def score_board(claimed: set[str], universe: set[str], basis: dict) -> dict:
    """Score one family's claim set against its adjudicated basis.

    Precision ranges over adjudicated claims: with a truth map,
    claims adjudicated to the family against claims adjudicated
    to any other label; without one, member claims against the
    named falses. Recall ranges over the basis's members present
    in the packet's universe; members outside it are named, not
    silently carried in the frame.
    """
    family = basis["family"]
    members_named = basis["members"]
    members = members_named & universe
    truth = basis["truth"]
    member_claims = claimed & members
    if truth:
        true_claims = {k for k in claimed if truth.get(k) == family}
        false_claims = {
            k for k in claimed if truth.get(k) is not None and truth.get(k) != family
        }
    else:
        true_claims = set(member_claims)
        false_claims = claimed & basis["falses"]
    precision = (
        len(true_claims) / (len(true_claims) + len(false_claims))
        if true_claims or false_claims
        else None
    )
    recall = len(member_claims) / len(members) if members else None
    joint = (
        round(joint_objective(precision, recall), 4)
        if precision is not None and recall is not None
        else None
    )
    return {
        "family": family,
        "keying": basis["keying"],
        "members": len(members),
        "members_named": len(members_named),
        "member_claims": len(member_claims),
        "true_claims": len(true_claims),
        "false_claims": len(false_claims),
        "fn": len(members) - len(member_claims),
        "P": None if precision is None else round(precision, 4),
        "R": None if recall is None else round(recall, 4),
        "J": joint,
        "member_claim_names": sorted(member_claims),
        "false_claim_names": sorted(false_claims),
        "missed_member_names": sorted(members - claimed),
        "members_not_in_packet": sorted(members_named - universe),
    }


def fidelity_diff(board: dict, expected: dict) -> list[dict]:
    """Divergences between a scored board and a board of record.

    The expected form names any subset of the board's cells
    (counts, fn, P, R, J); an empty result is exact reproduction.
    """
    out: list[dict] = []
    for cell in _CELLS:
        if cell in expected and board.get(cell) != expected[cell]:
            out.append({"cell": cell, "got": board.get(cell), "want": expected[cell]})
    return out


def run_score(packet: str | Path, basis: dict) -> dict:
    """Load a packet in the basis's keying and score its board."""
    packet_sets = load_packet(packet, basis["family"], basis["keying"])
    return score_board(packet_sets["claimed"], packet_sets["universe"], basis)


def main(argv: list[str] | None = None) -> int:
    """Score a family board, or verify one against its record."""
    parser = argparse.ArgumentParser(prog="board")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("score", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("packet", type=Path)
        cmd.add_argument("basis", type=Path)
        cmd.add_argument("--out", type=Path)
        if name == "verify":
            cmd.add_argument("expected", type=Path)
    args = parser.parse_args(argv)
    basis = load_basis(args.basis)
    board = run_score(args.packet, basis)
    if args.out:
        atomic_write_json(args.out, board, canonical=False, indent=1)
    if args.command == "score":
        print(json.dumps(board, indent=1, sort_keys=True))
        return 0
    expected = json.loads(args.expected.read_text())
    diff = fidelity_diff(board, expected)
    print(
        json.dumps(
            {"board": board, "fidelity_diff": diff, "reproduced": not diff},
            indent=1,
            sort_keys=True,
        )
    )
    return 0 if not diff else 1


if __name__ == "__main__":
    raise SystemExit(main())
