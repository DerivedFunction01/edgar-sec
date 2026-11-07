"""The sec-surface scanner: unclassified shapes and unregistered surfaces.

Synthetic repos pin both directions; a final test pins the scanner's static
interpretation of the rule table against the runtime classifier.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import sec_surface

_URL_MODULE = """
SURFACE_SUBMISSIONS = "submissions"
SURFACE_COMPANY_TICKERS = "company_tickers"

SEC_SURFACE_RULES: tuple[tuple[str, str, str], ...] = (
    (SURFACE_SUBMISSIONS, "data.sec.gov", r"^/submissions(/|$)"),
    (SURFACE_COMPANY_TICKERS, "www.sec.gov", r"^/files/company_tickers\\.json$"),
)

URL_BUILDER_SURFACES: dict[str, str] = {"submissions_url": SURFACE_SUBMISSIONS}
"""


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    _build_repo(tmp_path, {"edgar_sec/domain/sec_urls.py": _URL_MODULE})
    return tmp_path


def test_flags_an_unclassified_sec_url_shape(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                'URL = "https://www.sec.gov/Archives/edgar/full-index/x.xml"\n'
            )
        },
    )
    findings = sec_surface.scan_sec_surfaces()
    assert [(f.path, f.line) for f in findings] == [
        ("edgar_sec/pipelines/thing/job.py", 1)
    ]


def test_allows_a_classified_sec_url_shape(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing/job.py": (
                'URL = "https://www.sec.gov/files/company_tickers.json"\n'
                'OTHER = "https://data.sec.gov/submissions/CIK0000320193.json"\n'
            )
        },
    )
    assert sec_surface.scan_sec_surfaces() == []


def test_ignores_http_namespace_identifiers(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/domain/forms/thing/taxonomy.py": (
                'NS = "http://www.sec.gov/edgar/common"\n'
            )
        },
    )
    assert sec_surface.scan_sec_surfaces() == []


def test_flags_a_rule_surface_without_a_policy_row(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/domain/sec_urls.py": _URL_MODULE.replace(
                'SURFACE_COMPANY_TICKERS = "company_tickers"',
                'SURFACE_COMPANY_TICKERS = "company_tickers"\n'
                'SURFACE_UNREGISTERED = "unregistered_surface"',
            ).replace(
                '(SURFACE_COMPANY_TICKERS, "www.sec.gov", r"^/files/company_tickers\\.json$"),',
                '(SURFACE_COMPANY_TICKERS, "www.sec.gov", r"^/files/company_tickers\\.json$"),\n'
                '    (SURFACE_UNREGISTERED, "www.sec.gov", r"^/files/other\\.json$"),',
            )
        },
    )
    findings = sec_surface.scan_sec_surfaces()
    assert len(findings) == 1
    assert findings[0].path == "edgar_sec/domain/sec_urls.py"
    assert "unregistered_surface" in findings[0].message


def test_static_interpretation_agrees_with_the_runtime_classifier() -> None:
    from edgar_sec.domain import sec_urls

    book = sec_surface._load_rule_book()
    builders = {
        "submissions_url": sec_urls.submissions_url("320193"),
        "historical_submissions_url": sec_urls.historical_submissions_url(
            "CIK0000320193-submissions-001.json"
        ),
        "submissions_bulk_url": sec_urls.submissions_bulk_url(),
        "companyconcept_url": sec_urls.companyconcept_url(
            "320193", "us-gaap", "Assets"
        ),
        "archives_url": sec_urls.archives_url(320193, "000032019323000106", "aapl.htm"),
        "index_url_for": sec_urls.index_url_for("0000320193-23-000106", 320193),
        "index_json_url_for": sec_urls.index_json_url_for(
            "0000320193-23-000106", 320193
        ),
        "full_submission_url_for": sec_urls.full_submission_url_for(
            "320193", "0000320193-23-000106"
        ),
        "xbrl_package_url_for": sec_urls.xbrl_package_url_for(
            "320193", "0000320193-23-000106"
        ),
    }
    assert set(builders) == set(sec_urls.URL_BUILDER_SURFACES)
    for builder_name, url in builders.items():
        expected = sec_urls.URL_BUILDER_SURFACES[builder_name]
        assert sec_urls.classify_sec_surface(url) == expected
        assert sec_surface._classify(book, url) == expected
