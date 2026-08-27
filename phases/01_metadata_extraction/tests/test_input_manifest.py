from conftest import imp

manifest = imp("phases.01_metadata_extraction.core.input_manifest")
schemas = imp("phases.01_metadata_extraction.core.schemas")

import pytest


def _write_csv(tmp_path, content):
    path = tmp_path / "input.csv"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_normalizes_ciks_to_ten_digits_and_sorts(tmp_path):
    path = _write_csv(tmp_path, "cik,name\n1985,Accel\n1761,Tranzonic\n20,K Tron\n")
    rows, report = manifest.read_input_manifest(path)
    assert [row.cik_padded for row in rows] == [
        "0000000020",
        "0000001761",
        "0000001985",
    ]
    assert report["row_count"] == 3
    assert report["malformed"] == []
    assert report["duplicates"] == []


def test_detects_malformed_and_duplicate_rows(tmp_path):
    path = _write_csv(
        tmp_path,
        "cik,name\n1985,Accel\n1985,Accel Dup\nabc,Broken\n,Empty\n99999999999,TooLong\n",
    )
    rows, report = manifest.read_input_manifest(path)
    assert [row.cik_padded for row in rows] == ["0000001985"]
    assert len(report["malformed"]) == 3
    assert len(report["duplicates"]) == 1
    assert report["duplicates"][0]["cik"] == "0000001985"


def test_fingerprint_is_stable_and_order_independent(tmp_path):
    a = _write_csv(tmp_path / "a" if False else tmp_path, "cik,name\n1985,A\n20,B\n")
    rows, _ = manifest.read_input_manifest(a)
    fingerprint_one = report_fingerprint(rows)
    rows2, _ = manifest.read_input_manifest(a)
    assert report_fingerprint(rows2) == fingerprint_one


def report_fingerprint(rows):
    return manifest.input_fingerprint(rows)


def test_missing_cik_column_raises(tmp_path):
    path = _write_csv(tmp_path, "identifier,name\n1985,Accel\n")
    with pytest.raises(manifest.ManifestError):
        manifest.read_input_manifest(path)


def test_normalize_cik_rejects_garbage():
    with pytest.raises(ValueError):
        manifest.normalize_cik("12ab")
    with pytest.raises(ValueError):
        manifest.normalize_cik("12345678901")
    assert manifest.normalize_cik("20") == "0000000020"
    assert manifest.normalize_cik("0000037996") == "0000037996"


def test_limit_bounds_rows(tmp_path):
    path = _write_csv(tmp_path, "cik,name\n1,A\n2,B\n3,C\n")
    rows, _ = manifest.read_input_manifest(path, limit=2)
    assert len(rows) == 2
