"""Async document processor protocol, pipeline execution, and default no-op processor."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..core.schemas import DocumentLocator, detect_mime, doc_id

_thread_local = threading.local()


def _get_thread_loop() -> asyncio.AbstractEventLoop:
    loop = getattr(_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _thread_local.loop = loop
    return loop


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """Outcome of processing one raw filing document through an async pipeline."""

    doc_id: str
    payload: bytes
    byte_size: int
    mime_type: str
    metadata: dict[str, object] = field(default_factory=dict)
    processor_fingerprint: str = "custom:unspecified"
    representation: str = "application/octet-stream"


@runtime_checkable
class DocumentProcessor(Protocol):
    """Async pipeline processor for transforming, cleaning, and extracting documents."""

    async def process(
        self, raw_bytes: bytes, locator: DocumentLocator
    ) -> ProcessedDocument:
        """Asynchronously process raw bytes for a given locator."""
        ...


class NoOpDocumentProcessor:
    """Default async pass-through document processor."""

    async def process(
        self, raw_bytes: bytes, locator: DocumentLocator
    ) -> ProcessedDocument:
        return ProcessedDocument(
            doc_id=doc_id(locator.accession, locator.document_path),
            payload=raw_bytes,
            byte_size=len(raw_bytes),
            mime_type=detect_mime(locator.document_path),
            metadata={},
            processor_fingerprint="raw-pass-through",
            representation="raw",
        )


def execute_processor(
    processor: DocumentProcessor,
    raw_bytes: bytes,
    locator: DocumentLocator,
) -> ProcessedDocument:
    """Execute an async DocumentProcessor from synchronous worker threads reusing thread event loops."""
    coro = processor.process(raw_bytes, locator)
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop is not None and current_loop.is_running():
        with ThreadPoolExecutor() as pool:
            return pool.submit(_get_thread_loop().run_until_complete, coro).result()
    return _get_thread_loop().run_until_complete(coro)


__all__ = [
    "DocumentProcessor",
    "NoOpDocumentProcessor",
    "ProcessedDocument",
    "execute_processor",
]
