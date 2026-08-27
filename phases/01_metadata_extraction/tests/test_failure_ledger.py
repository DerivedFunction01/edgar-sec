
from conftest import imp

http = imp("defs.sec_http")

import pytest


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        if not self.script:
            return FakeResponse(200)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(script, tmp_path, **kwargs):
    kwargs.setdefault("rate_limiter", http.RateLimiter(min_interval_s=0.001))
    kwargs.setdefault(
        "retry_policy", http.RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0)
    )
    session = FakeSession(script)
    client = http.SecHttpClient(
        user_agent="TestClient/1.0 test@example.com",
        cache_dir=str(tmp_path / "cache"),
        session_factory=lambda: session,
        **kwargs,
    )
    return client, session


def exhausted_client(tmp_path, payload_script=None):
    """A client whose budget exhausts on first call (max_retries=1 → 2 sends)."""
    script = payload_script or [FakeResponse(500), FakeResponse(500)]
    return make_client(script, tmp_path)


def test_exhausted_retry_is_recorded_in_ledger(tmp_path):
    client, _ = exhausted_client(tmp_path)
    with pytest.raises(http.RetryExhausted):
        client.get_json("https://x/broken.json")
    entry = client.load_failure_entry("https://x/broken.json")
    assert entry["failed_runs"] == 1
    assert entry["last_kind"] == "transient_exhausted"
    assert entry["last_status"] == 500
    assert not entry["permanent"]


def test_404_is_recorded_permanent_and_skipped_next_session(tmp_path):
    client, _session = make_client([FakeResponse(404)], tmp_path)
    with pytest.raises(http.PermanentHttpError):
        client.get_json("https://x/gone.json")
    assert client.load_failure_entry("https://x/gone.json")["permanent"]

    # A brand-new session must fail fast with zero HTTP requests.
    fresh, fresh_session = make_client([FakeResponse(200)], tmp_path)
    with pytest.raises(http.PermanentHttpError, match="permanent failure on a previous run"):
        fresh.get_json("https://x/gone.json")
    assert fresh_session.calls == 0


def test_transient_failures_accumulate_across_sessions_until_budget(tmp_path):
    # Session 1: exhausted once.
    client1, _s1 = make_client([FakeResponse(503), FakeResponse(503)], tmp_path)
    with pytest.raises(http.RetryExhausted):
        client1.get_json("https://x/flaky.json")

    # Session 2 with default budget 3: below threshold, so it still tries HTTP.
    client2, s2 = make_client([FakeResponse(503), FakeResponse(503)], tmp_path)
    with pytest.raises(http.RetryExhausted):
        client2.get_json("https://x/flaky.json")
    assert s2.calls == 2
    assert client2.load_failure_entry("https://x/flaky.json")["failed_runs"] == 2

    # Session 3: still tries.
    client3, s3 = make_client([FakeResponse(503), FakeResponse(503)], tmp_path)
    with pytest.raises(http.RetryExhausted):
        client3.get_json("https://x/flaky.json")
    assert s3.calls == 2

    # Session 4: budget of 3 independent failed runs reached — no HTTP at all.
    client4, s4 = make_client([FakeResponse(200)], tmp_path)
    with pytest.raises(http.PermanentHttpError, match="3 independent run"):
        client4.get_json("https://x/flaky.json")
    assert s4.calls == 0


def test_custom_budget_skips_sooner(tmp_path):
    for _ in range(2):
        client, _ = make_client([FakeResponse(500), FakeResponse(500)], tmp_path)
        with pytest.raises(http.RetryExhausted):
            client.get_json("https://x/y.json")
    fresh, session = make_client(
        [FakeResponse(200)], tmp_path, max_failure_attempts=2
    )
    with pytest.raises(http.PermanentHttpError):
        fresh.get_json("https://x/y.json")
    assert session.calls == 0


def test_success_clears_the_ledger_entry(tmp_path):
    client, _ = make_client([FakeResponse(500), FakeResponse(500)], tmp_path)
    with pytest.raises(http.RetryExhausted):
        client.get_json("https://x/recovers.json")
    assert client.load_failure_entry("https://x/recovers.json")

    recovered, _ = make_client(
        [FakeResponse(200, b'{"ok": true}')], tmp_path, ignore_failure_history=False
    )
    # failed_runs=1 < budget 3, so it attempts and succeeds.
    assert recovered.get_json("https://x/recovers.json") == {"ok": True}
    assert recovered.load_failure_entry("https://x/recovers.json") is None

    # Later failures start counting from zero again.
    final = recovered.load_failure_entry("https://x/recovers.json")
    assert final is None


def test_ignore_failure_history_forces_attempts(tmp_path):
    client, _ = make_client([FakeResponse(404)], tmp_path)
    with pytest.raises(http.PermanentHttpError):
        client.get_json("https://x/dead.json")

    forced, session = make_client(
        [FakeResponse(404)], tmp_path, ignore_failure_history=True
    )
    with pytest.raises(http.PermanentHttpError):
        forced.get_json("https://x/dead.json")
    assert session.calls == 1  # attempted despite permanent history


def test_empty_body_json_decode_failure_is_tracked_as_permanent(tmp_path):
    client, _ = make_client([FakeResponse(200, b"")], tmp_path)
    with pytest.raises(http.PermanentHttpError, match="Expecting value"):
        client.get_json("https://x/empty.json")
    entry = client.load_failure_entry("https://x/empty.json")
    assert entry["permanent"]
    assert entry["last_kind"] == "bad_payload"

    # Not retried by a later session.
    fresh, session = make_client([FakeResponse(200)], tmp_path)
    with pytest.raises(http.PermanentHttpError):
        fresh.get_json("https://x/empty.json")
    assert session.calls == 0


def test_valid_zero_filing_payload_is_success_not_failure(tmp_path):
    client, _session = make_client(
        [FakeResponse(200, b'{"cik": "1", "filings": {"recent": {}, "files": []}}')],
        tmp_path,
    )
    payload = client.get_json("https://x/zerofilings.json")
    assert payload["filings"]["recent"] == {}  # supplied-but-empty preserved
    assert client.load_failure_entry("https://x/zerofilings.json") is None
    # It is cached as a normal success for reruns.
    again, second_session = make_client([], tmp_path)
    assert again.get_json("https://x/zerofilings.json") == payload
    assert second_session.calls == 0  # served from cache


def test_ledger_write_is_atomic(tmp_path):
    client, _ = make_client([FakeResponse(404)], tmp_path)
    with pytest.raises(http.PermanentHttpError):
        client.get_json("https://x/z.json")

    files = list((tmp_path / "cache" / "failures").glob("*"))
    assert len(files) == 1
    assert not [f for f in files if f.name.endswith(".tmp")]
