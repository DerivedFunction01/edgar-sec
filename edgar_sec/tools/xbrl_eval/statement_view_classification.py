"""Cell classification for the statement-view driver."""

from __future__ import annotations

from typing import Any

from edgar_sec.tools.xbrl_eval.statement_view_vocabulary import (
    BLOCKED,
    FAITHFUL,
    HONEST,
    MECH_EXCEPTION,
    MECH_FACE,
    MECH_FISCAL,
    MECH_LABEL,
    MECH_MODE,
    MECH_PARSE,
    MECH_ROOT,
    MECH_UNVERIFIED,
)


def _exception_mechanism(error: str) -> str:
    """Name the mechanism an exception text evidences, conservatively."""
    lowered = error.lower()
    if "fiscal" in lowered or "length class" in lowered or "span" in lowered:
        return MECH_FISCAL
    if "no presentation role" in lowered or "no catalog" in lowered:
        return MECH_LABEL
    return MECH_EXCEPTION


def _classify_cell(cell: dict[str, Any], statement: bool) -> dict[str, str | None]:
    """One cell's classification and, when blocked, its mechanism."""
    kind = cell["kind"]
    error = cell.get("error")
    if kind == "catalog":
        return _classify_catalog(cell)
    if error is not None:
        return {"classification": BLOCKED, "mechanism": _exception_mechanism(error)}
    if kind == "statement":
        if cell["valued_nodes"] == 0:
            if cell.get("status") == "UNAVAILABLE":
                return {"classification": HONEST, "mechanism": None}
            if statement:
                return {"classification": BLOCKED, "mechanism": MECH_ROOT}
            return {"classification": HONEST, "mechanism": None}
        return {"classification": FAITHFUL, "mechanism": None}
    if kind == "cover":
        if cell["dei_filed"] == 0 and cell["facts"] == 0:
            return {"classification": HONEST, "mechanism": None}
        if cell["facts"] == cell["dei_filed"]:
            return {"classification": FAITHFUL, "mechanism": None}
        return {"classification": BLOCKED, "mechanism": MECH_PARSE}
    if kind == "scalar":
        if cell["value"] is None:
            return {"classification": HONEST, "mechanism": None}
        if cell.get("derived_verified") is not None:
            if cell["derived_verified"]:
                return {"classification": FAITHFUL, "mechanism": None}
            return {"classification": BLOCKED, "mechanism": MECH_UNVERIFIED}
        if cell["in_filed"]:
            return {"classification": FAITHFUL, "mechanism": None}
        return {"classification": BLOCKED, "mechanism": MECH_UNVERIFIED}
    if kind == "series":
        if cell["points"] == 0:
            return {"classification": HONEST, "mechanism": None}
        if cell.get("in_filed"):
            return {"classification": FAITHFUL, "mechanism": None}
        return {"classification": BLOCKED, "mechanism": MECH_UNVERIFIED}
    if kind == "yoy":
        outcome = HONEST if cell["value"] is None else FAITHFUL
        return {"classification": outcome, "mechanism": None}
    if kind == "view":
        outcome = FAITHFUL if cell.get("populated") else HONEST
        return {"classification": outcome, "mechanism": None}
    if kind == "metrics":
        outcome = FAITHFUL if cell["values"] else HONEST
        return {"classification": outcome, "mechanism": None}
    raise ValueError(f"unclassified cell kind {kind!r}")


def _classify_catalog(cell: dict[str, Any]) -> dict[str, str | None]:
    """Catalog cell: the worst of role exceptions, violations, face checks."""
    if cell.get("error") is not None:
        return {
            "classification": BLOCKED,
            "mechanism": _exception_mechanism(cell["error"]),
        }
    if cell["exceptions"]:
        return {"classification": BLOCKED, "mechanism": MECH_EXCEPTION}
    if cell["violations"]:
        return {"classification": BLOCKED, "mechanism": MECH_MODE}
    face = cell["face_totals"]
    if any(check["status"] in ("missing", "error") for check in face):
        return {"classification": BLOCKED, "mechanism": MECH_FACE}
    if face and all(check["status"] == "skipped" for check in face):
        return {"classification": HONEST, "mechanism": None}
    return {"classification": FAITHFUL, "mechanism": None}


def classify_record(record: dict[str, Any]) -> dict[str, Any]:
    """Classify every cell of one filing record against its posture."""
    statement = bool(record["analysis"]["statement"])
    verdicts = {
        name: _classify_cell(cell, statement) for name, cell in record["cells"].items()
    }
    return verdicts
