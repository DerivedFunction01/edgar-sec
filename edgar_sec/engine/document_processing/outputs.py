from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HandlerSidecar:
    name: str
    content: bytes | str


@dataclass(frozen=True, slots=True)
class HandlerOutput:
    content: bytes | str
    sidecars: tuple[HandlerSidecar, ...] = ()


@dataclass(frozen=True, slots=True)
class ProducedSidecar:
    name: str
    content: bytes
    sha256: str
    byte_size: int


__all__ = ["HandlerOutput", "HandlerSidecar", "ProducedSidecar"]
