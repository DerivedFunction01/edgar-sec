"""Defect register shared by the table-extraction corpus drives.

Every exception a drive meets becomes an entry with a defect class, the
stage that produced it, specimens, and an explanation. A step closes
only with zero entries whose explanation is empty.
"""

from __future__ import annotations

import json
from pathlib import Path

_SPECIMEN_CAP = 3


class DefectRegister:
    """Aggregating register: one entry per (class, stage, accession, table)."""

    def __init__(self, run_id: str, step: str, population: str) -> None:
        self._run_id = run_id
        self._step = step
        self._population = population
        self._entries: dict[tuple, dict] = {}

    def add(
        self,
        defect_class: str,
        stage: str,
        accession: str,
        explanation: str,
        *,
        table_index: int | None = None,
        specimen: str | None = None,
    ) -> None:
        key = (defect_class, stage, accession, table_index)
        entry = self._entries.get(key)
        if entry is None:
            entry = {
                "class": defect_class,
                "stage": stage,
                "accession": accession,
                "table_index": table_index,
                "count": 0,
                "specimens": [],
                "explanation": explanation,
            }
            self._entries[key] = entry
        entry["count"] += 1
        if specimen is not None and len(entry["specimens"]) < _SPECIMEN_CAP:
            entry["specimens"].append(specimen)

    def add_entry(self, entry: dict) -> None:
        key = (entry["class"], entry["stage"], entry["accession"], entry["table_index"])
        mine = self._entries.get(key)
        if mine is None:
            self._entries[key] = dict(entry)
        else:
            mine["count"] += entry["count"]
            for specimen in entry["specimens"]:
                if len(mine["specimens"]) < _SPECIMEN_CAP:
                    mine["specimens"].append(specimen)

    def absorb(self, other: DefectRegister) -> None:
        for entry in other.entries():
            self.add_entry(entry)

    def entries(self) -> list[dict]:
        return [self._entries[key] for key in sorted(self._entries, key=str)]

    def unexplained(self) -> list[dict]:
        return [e for e in self.entries() if not e["explanation"].strip()]

    def by_class(self, defect_class: str) -> list[dict]:
        return [e for e in self.entries() if e["class"] == defect_class]

    def to_dict(self) -> dict:
        return {
            "run_id": self._run_id,
            "step": self._step,
            "population": self._population,
            "entries": self.entries(),
        }

    def write(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_dict(), indent=1, sort_keys=True), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> DefectRegister:
        data = json.loads(path.read_text(encoding="utf-8"))
        register = cls(data["run_id"], data["step"], data["population"])
        for entry in data["entries"]:
            register._entries[
                (
                    entry["class"],
                    entry["stage"],
                    entry["accession"],
                    entry["table_index"],
                )
            ] = entry
        return register
