"""The identifier-patterns scanner: the identifier family lines.
A private accession, CIK, commission, EIN, registration, or CUSIP
recognizer makes two modules disagree about what an identifier is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import identifier_patterns


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _messages(findings: list) -> list[str]:
    return [f.message for f in findings]


# --- The accession line: positive fixtures are the production copies verbatim ---


def test_flags_accession_core_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_ACCESSION_RE = re.compile(r"^\\d{10}-\\d{2}-\\d{6}$")\n'},
    )
    findings = identifier_patterns.scan_identifier_patterns()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]
    assert _messages(findings) == ["private accession recognizer outside its home"]


def test_flags_accession_digits_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_ACCESSION_RE = re.compile(r"^[0-9]{18}$")\n'},
    )
    assert identifier_patterns.scan_identifier_patterns()


def test_flags_accession_named_loose_capture(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_ACCESSION_RE = re.compile(r"AccNo:</b>\\s*([0-9][0-9-]*)")\n'
            )
        },
    )
    assert identifier_patterns.scan_identifier_patterns()


def test_flags_cik_member_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_MEMBER_RE = re.compile(r"^CIK(\\d{10})\\.json$")\n'},
    )
    findings = identifier_patterns.scan_identifier_patterns()
    assert _messages(findings) == ["private CIK member-name recognizer outside its home"]


def test_flags_commission_number_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "_FILE_NUMBER_RE = re.compile(\n"
                '    r"commission file (?:numbers?|no\\.?)[:\\s]*([0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+)",\n'
                "    re.IGNORECASE,\n"
                ")\n"
            )
        },
    )
    findings = identifier_patterns.scan_identifier_patterns()
    assert _messages(findings) == [
        "private commission file-number recognizer outside its home"
    ]


def test_flags_commission_whitespace_caption_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_FILE_CAPTION_RE = re.compile(r"commission\\s+file\\s+(?:no\\.?|number)", re.IGNORECASE)\n'
            )
        },
    )
    assert identifier_patterns.scan_identifier_patterns()


def test_flags_ein_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_EIN_RE = re.compile(r"\\b\\d{2}-\\d{7}\\b")\n'},
    )
    findings = identifier_patterns.scan_identifier_patterns()
    assert _messages(findings) == ["private EIN recognizer outside its home"]


def test_flags_registration_value_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_NUMBER_RE = re.compile(r"\\d{3}-\\d{3,}(?:-\\d{2})?")\n'},
    )
    findings = identifier_patterns.scan_identifier_patterns()
    assert _messages(findings) == [
        "private registration-number recognizer outside its home"
    ]


def test_flags_registration_prefix_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": '_NUMBER_RE = re.compile(r"(?:333|33)-\\d{3,}(?:-\\d{2})?")\n'},
    )
    assert identifier_patterns.scan_identifier_patterns()


def test_flags_cusip_value_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_CUSIP_RE = re.compile(r"(?i)(?<![0-9A-Z])[0-9A-Z*@#]{9}(?![0-9A-Z])")\n'
            )
        },
    )
    findings = identifier_patterns.scan_identifier_patterns()
    assert _messages(findings) == ["private CUSIP recognizer outside its home"]


def test_flags_cusip_label_copy(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_CUSIP_LABEL_RE = re.compile(r"cusip (?:number|no\\.?)", re.IGNORECASE)\n'
            )
        },
    )
    assert identifier_patterns.scan_identifier_patterns()


# --- Homes, compositions, and format shapes are allowed ---


def test_allows_the_homes(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/domain/identity.py": (
                'ACCESSION_RE = re.compile(r"^\\d{10}-\\d{2}-\\d{6}$")\n'
                'ACCESSION_DIGITS_RE = re.compile(r"^\\d{18}$")\n'
            ),
            "edgar_sec/engine/forms/common/entities.py": (
                'IRS_RE = re.compile(r"\\b(\\d{2}-\\d{7}|\\d{9})\\b")\n'
                'CUSIP_RE = re.compile(r"(?i)(?<![0-9A-Z])[0-9A-Z*@#]{9}(?![0-9A-Z])")\n'
            ),
            "edgar_sec/pipelines/metadata_sync/paths.py": (
                'CIK_MEMBER_RE = re.compile(r"^CIK(\\d{10})\\.json$")\n'
            ),
        },
    )
    assert identifier_patterns.scan_identifier_patterns() == []


def test_allows_compositions_of_the_homed_patterns(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/form_rega/analysis.py": (
                "_FILE_NUMBER_RE = re.compile(\n"
                '    COMMISSION_FILE_CAPTION_RE.pattern + r"[:\\s]*(024-[0-9]+)",\n'
                "    re.IGNORECASE,\n"
                ")\n"
            ),
            "edgar_sec/engine/forms/form_abs_reports/analysis.py": (
                '_FILE_NUMBER_VALUE = f"({COMMISSION_FILE_TOKEN_RE.pattern})"\n'
            ),
        },
    )
    assert identifier_patterns.scan_identifier_patterns() == []


def test_allows_sql_regexp_shapes(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing.py": (
                "\"SELECT * FROM t WHERE regexp_matches(accession, '^[0-9]{10}-[0-9]{2}-[0-9]{6}$')\"\n"
                "\"SELECT * FROM t WHERE regexp_matches(member_name, '^CIK[0-9]{10}\\\\.json$')\"\n"
            )
        },
    )
    assert identifier_patterns.scan_identifier_patterns() == []


def test_allows_sec_url_paths(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_SUBMISSION_RE = re.compile(r"^/Archives/edgar/data/\\d+/[^/]+/\\d{10}-\\d{2}-\\d{6}\\.txt$")\n'
            )
        },
    )
    assert identifier_patterns.scan_identifier_patterns() == []


def test_allows_legitimate_number_formats(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                '_OMB_RE = re.compile(r"^\\d{4}-\\d{4}$")\n'
                '_PHONE_RE = re.compile(r"(?:\\+?1[-.\\s]?)?\\(?\\b\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}\\b")\n'
                '_ZIP_RE = re.compile(r"\\b\\d{5}-\\d{4}\\b")\n'
                '_FILED_RE = re.compile(r"^FILED AS OF DATE:\\s*(\\d{4})(\\d{2})(\\d{2})", re.MULTILINE)\n'
            )
        },
    )
    assert identifier_patterns.scan_identifier_patterns() == []


# --- The sanctioned sites stand at their own paths only ---


def test_sanctioned_sites_read_clean(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/document_planning/catalog_scope.py": (
                '_ACCESSION_RE = re.compile(r"^[0-9]{18}$")\n'
            ),
            "edgar_sec/engine/feeds/parser_atom.py": (
                '_ACCESSION_RE = re.compile(r"AccNo:</b>\\s*([0-9][0-9-]*)")\n'
            ),
            "edgar_sec/pipelines/document_acquisition/feed_inventory.py": (
                '_ACCESSION_RE = re.compile(r"^ACCESSION NUMBER:\\s*(\\S+)", re.MULTILINE)\n'
                '_SGML_ACCESSION_RE = re.compile(r"<ACCESSION-NUMBER>\\s*([^\\s<]+)")\n'
            ),
            "edgar_sec/pipelines/document_planning/matching.py": (
                '_COMPLETE_SUBMISSION_NAME = re.compile(r"\\d{10}-\\d{2}-\\d{6}\\.txt$")\n'
            ),
            "edgar_sec/pipelines/metadata_sync/planner.py": (
                '_SHARD_MEMBER_RE = re.compile(r"^CIK(\\d{10})-submissions-(\\d+)\\.json$")\n'
            ),
            "edgar_sec/engine/forms/form_11k/analysis.py": (
                "_FILE_NUMBER_RE = re.compile(\n"
                '    r"commission file (?:number|no\\.?)[:\\s]*([0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+)",\n'
                "    re.IGNORECASE,\n"
                ")\n"
                '_FILE_CAPTION_RE = re.compile(r"commission file (?:number|no\\.)", re.IGNORECASE)\n'
            ),
            "edgar_sec/engine/forms/form_425/analysis.py": (
                '_FILE_CAPTION_RE = re.compile(r"commission\\s+file\\s+(?:no\\.?|number)", re.IGNORECASE)\n'
            ),
            "edgar_sec/engine/forms/form_sd/analysis.py": (
                '_EIN_RE = re.compile(r"\\b\\d{2}-\\d{7}\\b")\n'
            ),
            "edgar_sec/engine/forms/form_424b/analysis.py": (
                "_REGISTRATION_RE = re.compile(\n"
                '    r"(?:" + _REGISTRATION_CAPTION_ALT + r")[:\\s]*(\\d{3}-\\d{3,})",\n'
                "    re.IGNORECASE,\n"
                ")\n"
            ),
            "edgar_sec/engine/forms/form_497/analysis.py": (
                "_REGISTRATION_RE = re.compile(\n"
                '    r"registration\\s+(?:statement\\s+)?no\\.?\\s*:?\\s*((?:\\d{3}-\\d{3,}(?:-\\d{2})?))",\n'
                "    re.IGNORECASE,\n"
                ")\n"
            ),
            "edgar_sec/engine/forms/form_fwp/analysis.py": (
                "_REGISTRATION_RE = re.compile(\n"
                '    r"registration\\s+(?:statement\\s+)?nos?\\.?[:\\s]*"\n'
                '    r"((?:\\d{3}-\\d{3,}(?:-\\d{2})?[\\s,and;]*)+)",\n'
                "    re.IGNORECASE,\n"
                ")\n"
                '_NUMBER_RE = re.compile(r"\\d{3}-\\d{3,}(?:-\\d{2})?")\n'
            ),
            "edgar_sec/engine/forms/form_fn/analysis.py": (
                '_NUMBER_RE = re.compile(r"(?:333|33)-\\d{3,}(?:-\\d{2})?")\n'
            ),
            "edgar_sec/engine/forms/form_12b25/analysis.py": (
                '_CUSIP_LABEL_RE = re.compile(r"cusip (?:number|no\\.?)", re.IGNORECASE)\n'
            ),
        },
    )
    assert identifier_patterns.scan_identifier_patterns() == []


def test_sanction_does_not_travel_to_other_paths(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/form_8k/analysis.py": (
                '_EIN_RE = re.compile(r"\\b\\d{2}-\\d{7}\\b")\n'
            )
        },
    )
    assert identifier_patterns.scan_identifier_patterns()


def test_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/test_thing.py": '_ACCESSION_RE = re.compile(r"^\\d{10}-\\d{2}-\\d{6}$")\n'},
    )
    assert identifier_patterns.scan_identifier_patterns() == []
