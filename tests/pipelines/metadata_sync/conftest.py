"""Shared pytest fixtures for the metadata_sync pipeline.

Test doubles live in :mod:`tests.support` so the whole suite shares one
definition; this module only wires them into pytest.
"""

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
