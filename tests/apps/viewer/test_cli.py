"""The viewer parser, whose loopback default is a security decision, not a convenience."""

from __future__ import annotations

import pytest

from edgar_sec.apps.viewer.cli import DEFAULT_HOST, DEFAULT_PORT, build_parser


def test_the_default_bind_is_loopback() -> None:
    assert DEFAULT_HOST == "127.0.0.1"
    assert build_parser().parse_args([]).host == "127.0.0.1"


def test_the_default_port() -> None:
    assert build_parser().parse_args([]).port == DEFAULT_PORT


def test_artifacts_is_unset_by_default() -> None:
    """Unset means "resolve the project root", not "the current directory"."""
    assert build_parser().parse_args([]).artifacts is None


def test_the_ui_is_mounted_unless_api_only() -> None:
    assert build_parser().parse_args([]).api_only is False
    assert build_parser().parse_args(["--api-only"]).api_only is True


def test_overrides_are_accepted() -> None:
    args = build_parser().parse_args(
        ["--artifacts", "/tmp/artifacts", "--host", "0.0.0.0", "--port", "9001"]
    )
    assert args.artifacts == "/tmp/artifacts"
    assert args.host == "0.0.0.0"
    assert args.port == 9001


def test_a_non_numeric_port_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--port", "not-a-port"])
