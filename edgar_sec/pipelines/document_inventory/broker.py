"""Broker adapter for SEC index-page fetch through a shared Unix-socket broker.

Stores only the socket path across pickle boundaries; each spawn-context child
reconnects to the one shared broker, so SEC pacing stays aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.infra.broker.sec_broker import SecBrokerClient

__all__ = ["IndexFetchFailure", "IndexPageEnvelope", "IndexPageBrokerClient"]


@dataclass(frozen=True, slots=True)
class IndexFetchFailure:
    """Broker reported a terminal failure for one index-page fetch."""

    accession: AccessionNumber
    code: Literal["fetch_failed"]
    detail: str


@dataclass(frozen=True, slots=True)
class IndexPageEnvelope:
    """One fetched index page: identity, URL, size, and exact response bytes."""

    accession: AccessionNumber
    index_url: str
    response_size: int
    html_bytes: bytes


class IndexPageBrokerClient:
    """Picklable Layer-4 wrapper that reconstructs a ``SecBrokerClient`` per child.

    Stores only the socket path across pickle boundaries; each spawn-context child
    reconnects to the one shared broker, so SEC pacing stays aggregate.
    """

    __slots__ = ("_socket_path", "_client")

    def __init__(self, socket_path: str | Path) -> None:
        self._socket_path = Path(socket_path)
        self._client = SecBrokerClient(self._socket_path)

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def __getstate__(self) -> dict[str, object]:
        return {"socket_path": self._socket_path}

    def __setstate__(self, state: dict[str, object]) -> None:
        self._socket_path = Path(state["socket_path"])  # type: ignore[arg-type]
        self._client = SecBrokerClient(self._socket_path)

    def fetch_index(
        self,
        accession: AccessionNumber,
        index_url: str,
        *,
        force_refresh: bool = False,
    ) -> IndexPageEnvelope | IndexFetchFailure:
        """Fetch one index page, returning a typed envelope or typed failure."""
        result = self._client.fetch(index_url, force_refresh=force_refresh)
        if result.get("status") != "ok":
            detail = str(result.get("error") or "broker reported failure")
            return IndexFetchFailure(accession, "fetch_failed", detail)
        payload = result.get("payload") or b""
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        return IndexPageEnvelope(accession, index_url, len(payload), payload)
