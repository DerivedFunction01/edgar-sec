from __future__ import annotations

from pathlib import Path

from edgar_sec.tools.worker_profile_cases import case_estimate, current_cases


def test_case_estimate_uses_file_then_folder_distribution() -> None:
    file = Path("tests/pipelines/test_new.py")
    cases = {
        "tests/pipelines/test_old.py::test_a": {
            "file": "tests/pipelines/test_old.py",
            "folder": "pipelines",
            "duration": 2.0,
        },
        "tests/pipelines/test_other.py::test_b": {
            "file": "tests/pipelines/test_other.py",
            "folder": "pipelines",
            "duration": 4.0,
        },
    }

    assert case_estimate(file, cases) == 3.0
    cases[next(iter(cases))]["file"] = file.as_posix()
    assert case_estimate(file, cases) == 2.0


def test_current_cases_preserves_unchanged_and_estimates_new_cases(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "tests" / "pipelines" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_old(): pass\ndef test_new(): pass\n")
    unchanged = f"{test_file.as_posix()}::test_old"
    added = f"{test_file.as_posix()}::test_new"
    removed = "tests/pipelines/test_removed.py::test_removed"
    prior = {
        "cases": {
            unchanged: {
                "file": test_file.as_posix(),
                "folder": "pipelines",
                "fingerprint": "current",
                "duration": 3.0,
                "estimated": False,
            },
            removed: {
                "file": "tests/pipelines/test_removed.py",
                "folder": "pipelines",
                "fingerprint": "old",
                "duration": 8.0,
                "estimated": False,
            },
        }
    }

    cases = current_cases(
        [unchanged, added], [test_file], prior, {test_file.as_posix(): "current"}
    )

    assert cases[unchanged]["duration"] == 3.0
    assert cases[added]["duration"] == 3.0
    assert cases[added]["estimated"] is True
    assert removed not in cases
