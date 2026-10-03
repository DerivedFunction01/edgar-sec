"""Fixtures wiring the shared ``tests.support`` doubles into pytest."""

from __future__ import annotations

import pytest

from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from tests.support import FakeSession, build_test_client


@pytest.fixture()
def session() -> FakeSession:
    """A fresh scripted session with no registered payloads."""
    return FakeSession()


@pytest.fixture()
def client(session: FakeSession) -> SubmissionsClient:
    """A submissions client bound to the scripted session."""
    return build_test_client(session)
