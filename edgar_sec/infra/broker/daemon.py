"""Broker daemon lifecycle management and context helpers."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from edgar_sec.infra.broker.sec_broker import (
    HEALTHCHECK_URL,
    SecBroker,
    SecBrokerClient,
)


@contextmanager
def managed_broker(
    socket_path: str | Path,
    http_client: Any | None = None,
    max_connections: int = 32,
    ready_timeout_s: float = 5.0,
) -> Iterator[SecBrokerClient]:
    """Context manager hosting a live SecBroker server for the duration of a block."""
    path = Path(socket_path)
    server = SecBroker(
        socket_path=path,
        http_client=http_client,
        max_connections=max_connections,
    )
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()

    client = SecBrokerClient(path)
    deadline = time.monotonic() + ready_timeout_s
    ready = False
    while time.monotonic() < deadline:
        with suppress(Exception):
            result = client.fetch(HEALTHCHECK_URL)
            if isinstance(result, dict) and result.get("status") == "ok":
                ready = True
                break
        time.sleep(0.05)

    if not ready:
        server.stop()
        thread.join(timeout=2.0)
        raise RuntimeError(
            f"SecBroker failed to start on {path} within {ready_timeout_s}s"
        )

    try:
        yield client
    finally:
        server.stop()
        thread.join(timeout=3.0)


__all__ = ["managed_broker"]
