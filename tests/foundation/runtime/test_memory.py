"""Unit tests for foundation.runtime.memory."""

from __future__ import annotations

from edgar_sec.foundation.runtime.memory import reclaim


def test_reclaim_does_not_crash() -> None:
    reclaim()
