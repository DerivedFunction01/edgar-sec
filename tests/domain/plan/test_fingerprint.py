from edgar_sec.domain.plan import fingerprint


def test_plan_fingerprint_preserves_published_digest_bytes() -> None:
    metadata = {
        "catalog_id": "c",
        "plan_id": "p",
        "scope": "deterministic",
    }
    assert fingerprint.plan_fingerprint_from_sorted_keys(metadata, ["a", "b"]) == (
        "79d2f6112a383b00a9c6f61aba8a7b29"
    )


def test_plan_fingerprint_accepts_an_empty_sorted_key_stream() -> None:
    metadata = {"catalog_id": "c", "plan_id": "p", "scope": "deterministic"}
    digest = fingerprint.plan_fingerprint_from_sorted_keys(metadata, [])
    assert len(digest) == 32
    assert digest == fingerprint.plan_fingerprint_from_sorted_keys(metadata, iter(()))
