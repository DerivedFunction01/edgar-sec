"""Tests for common acquisition command utilities."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from unittest.mock import MagicMock

from edgar_sec.infra.broker.sec_broker import StreamedFileResult
from edgar_sec.pipelines.document_acquisition.commands import common


def test_lazy_transport_lifecycle(tmp_path: Path, monkeypatch) -> None:
    fake_http = MagicMock()
    fake_broker = MagicMock()
    exited = []

    def fake_managed_broker(socket_path, http_client=None):
        class Ctx:
            def __enter__(self):
                return fake_broker

            def __exit__(self, *args):
                exited.append(socket_path)

        return Ctx()

    monkeypatch.setattr(common, "managed_broker", fake_managed_broker)
    transport = common._LazySecTransport(lambda: fake_http)

    assert transport._broker is None
    transport.warm()
    assert transport._broker is fake_broker

    transport.close()
    assert transport._broker is None
    assert transport._http_client is None
    assert len(exited) == 1


def test_lazy_transport_concurrent_stream(tmp_path: Path, monkeypatch) -> None:
    fake_http = MagicMock()
    fake_broker = MagicMock()
    broker_starts = 0

    def fake_managed_broker(socket_path, http_client=None):
        nonlocal broker_starts
        broker_starts += 1

        class Ctx:
            def __enter__(self):
                return fake_broker

            def __exit__(self, *args):
                pass

        return Ctx()

    fake_file = tmp_path / "streamed.bin"
    fake_file.write_bytes(b"content")
    digest = "a" * 64

    import uuid

    def fake_stream(*args, **kwargs):
        dest_parent = kwargs.get("staging_root")
        out = Path(dest_parent) / f"part_{uuid.uuid4().hex}.bin"
        out.write_bytes(b"content")
        return StreamedFileResult(
            "ok",
            out,
            digest,
            7,
            "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/report.htm",
            "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/report.htm",
            200,
            "text/html",
            None,
            None,
            None,
        )

    fake_broker.stream_to_file.side_effect = fake_stream
    monkeypatch.setattr(common, "managed_broker", fake_managed_broker)

    transport = common._LazySecTransport(lambda: fake_http)
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/report.htm"

    def _worker(idx: int):
        dest = tmp_path / f"dest_{idx}.bin"
        return transport.stream_to_file(
            url,
            dest,
            max_response_bytes=1024,
            validate_redirect=lambda u: None,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_worker, range(16)))

    assert broker_starts == 1
    assert len(results) == 16
    assert all(r.byte_size == 7 for r in results)
    transport.close()
