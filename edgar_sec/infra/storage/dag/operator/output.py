"""Shared JSON output emitter for DAG operator commands."""

from __future__ import annotations

import json
from typing import Any


def _emit(data: dict[str, Any] | list[Any]) -> None:
    print(json.dumps(data, indent=2))
