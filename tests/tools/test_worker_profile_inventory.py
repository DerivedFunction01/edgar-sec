from pathlib import Path

from edgar_sec.tools.worker_profile_inventory import scope_key


def test_scope_keys_cover_suite_folder_file_mixed_and_nodeids(tmp_path: Path) -> None:
    test_file = tmp_path / "test_sample.py"
    test_file.touch()
    assert scope_key(["tests"]) == "suite:tests"
    assert scope_key(["tests/domain"]) == "folder:tests/domain"
    assert scope_key([str(test_file)]) == f"file:{test_file.as_posix()}"
    assert scope_key(["tests/a.py", "tests/b.py"]) == scope_key(
        ["tests/b.py", "tests/a.py"]
    )
    assert scope_key(["tests/a.py::test_a", "tests/b.py::test_b"]) == scope_key(
        ["tests/b.py::test_b", "tests/a.py::test_a"]
    )
