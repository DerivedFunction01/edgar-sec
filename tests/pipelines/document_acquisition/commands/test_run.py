from __future__ import annotations

import json
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from edgar_sec.infra.broker.sec_broker import StreamedFileResult
from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import common, run


def test_run_command_delegates_policy_and_keeps_transport_lazy(
    capsys, tmp_path, monkeypatch
) -> None:
    calls = []

    def fake_run(run_id, **kwargs):
        calls.append((run_id, kwargs))
        return SimpleNamespace(
            run_id=run_id,
            state="complete",
            target_counts={"acquired": 2, "pending": 0},
            attempted_count=2,
            retryable_failure_count=0,
            non_retryable_failure_count=0,
            cancelled=False,
        )

    monkeypatch.setattr(run, "execute_acquisition_run", fake_run)
    result = cli.main(
        [
            "run",
            "--run-id",
            "run-1",
            "--max-response-bytes",
            "2048",
            "--workers",
            "4",
            "--retain-response-evidence",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    run_id, arguments = calls[0]
    assert run_id == "run-1"
    assert arguments["policy"].max_response_bytes == 2048
    assert arguments["policy"].requested_workers == 4
    assert arguments["policy"].retain_response_evidence
    assert isinstance(arguments["transport"], common._LazySecTransport)
    assert arguments["transport"]._http_client is None
    assert arguments["transport"]._broker is None
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "complete"
    assert payload["retain_response_evidence"]


def test_run_uses_configured_response_limit_when_omitted(
    tmp_path, monkeypatch, capsys
) -> None:
    calls = []
    monkeypatch.setattr(
        common,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )
    monkeypatch.setattr(
        run,
        "execute_acquisition_run",
        lambda run_id, **kwargs: (
            calls.append(kwargs["policy"].max_response_bytes)
            or SimpleNamespace(
                run_id=run_id,
                state="complete",
                target_counts={"acquired": 0},
                attempted_count=0,
                retryable_failure_count=0,
                non_retryable_failure_count=0,
                cancelled=False,
            )
        ),
    )

    result = cli.main(["run", "--run-id", "run-1", "--artifacts", str(tmp_path)])

    assert result == 0
    assert calls == [268435456]
    output = capsys.readouterr().out
    assert "run run-1" in output
    assert "retain_response_evidence=False" in output


def test_lazy_cli_transport_streams_through_shared_broker(
    tmp_path, monkeypatch
) -> None:
    class FakeHttpClient:
        closed = False

        def close(self):
            self.closed = True

    class FakeBrokerClient:
        closed = False
        request = None

        def stream_to_file(
            self,
            url,
            *,
            max_response_bytes,
            accession_cik,
            accession_number,
            staging_root,
        ):
            self.request = (url, max_response_bytes, accession_cik, accession_number)
            body = b"broker-streamed"
            path = Path(staging_root) / "sec-stream-test.part"
            path.write_bytes(body)
            return StreamedFileResult(
                "ok",
                path,
                sha256(body).hexdigest(),
                len(body),
                url,
                url,
                200,
                "text/html",
                None,
                None,
                None,
            )

        def close(self):
            self.closed = True

    fake_http = FakeHttpClient()
    fake_broker = FakeBrokerClient()
    exited = []

    @contextmanager
    def fake_managed_broker(socket_path, *, http_client):
        assert http_client is fake_http
        yield fake_broker
        exited.append(socket_path)

    monkeypatch.setattr(common, "managed_broker", fake_managed_broker)
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)
    destination = staging / "response-generated.bin"
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/report.htm"
    validated = []
    transport = common._LazySecTransport(lambda: fake_http)

    response = transport.stream_to_file(
        url,
        destination,
        max_response_bytes=256,
        validate_redirect=validated.append,
    )
    transport.close()

    assert response.path == destination
    assert destination.read_bytes() == b"broker-streamed"
    assert fake_broker.request == (url, 256, "320193", "000032019320000096")
    assert validated == [url]
    assert fake_broker.closed and fake_http.closed and exited
