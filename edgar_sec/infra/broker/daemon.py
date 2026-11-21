"""Broker daemon lifecycle management and context helpers."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
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
    ready_timeout_s: float = 60.0,
) -> Iterator[SecBrokerClient]:
    """Context manager hosting a live SecBroker server for the duration of a block.

    Startup waits on the broker's readiness signal (set once the socket
    listens); ready_timeout_s is only a hang guard.
    """
    path = Path(socket_path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = SecBroker(
        socket_path=path,
        http_client=http_client,
        max_connections=max_connections,
    )
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()

    client = SecBrokerClient(path)
    try:
        server.wait_ready(ready_timeout_s)
        result = client.fetch(HEALTHCHECK_URL)
        if not (isinstance(result, dict) and result.get("status") == "ok"):
            raise RuntimeError(f"SecBroker healthcheck failed on {path}: {result!r}")
    except BaseException:
        client.close()
        server.stop()
        thread.join(timeout=2.0)
        raise

    try:
        yield client
    finally:
        client.close()
        server.stop()
        thread.join(timeout=3.0)


__all__ = ["managed_broker"]
