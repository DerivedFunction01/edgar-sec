"""Contract tests for the static launcher registry and root dispatcher."""

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from defs.runtime.registry import ENTRIES, LauncherEntry, find_entry

RUN_PATH = Path(__file__).resolve().parents[2] / "run.py"


def _load_root_launcher():
    spec = importlib.util.spec_from_file_location("root_launcher", RUN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_registry_shape_is_unique_and_complete():
    ids = [entry.id for entry in ENTRIES]
    assert len(ids) == len(set(ids))
    assert all(
        entry.id and entry.label and entry.description and entry.module
        for entry in ENTRIES
    )
    assert {entry.id for entry in ENTRIES} == {
        "viewer",
        "metadata",
        "filing-catalog",
        "webpage-storage",
        "artifact-bundle",
        "settings",
    }


def test_registered_modules_import_and_expose_main():
    for entry in ENTRIES:
        module = importlib.import_module(entry.module)
        assert callable(getattr(module, "main", None)), entry.module


def test_find_entry_hit_and_miss():
    entry = find_entry("viewer")
    assert isinstance(entry, LauncherEntry)
    assert entry.module == "defs.viewer.__main__"
    assert find_entry("not-an-entry") is None


def test_list_flag_prints_entries_as_json(capsys):
    launcher = _load_root_launcher()
    assert launcher.main(["--list"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == len(ENTRIES)
    assert {item["id"] for item in payload} == {entry.id for entry in ENTRIES}


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_direct_dispatch_passes_argv_through(capsys):
    launcher = _load_root_launcher()
    assert launcher.main(["viewer", "--help"]) == 0
    assert "usage" in capsys.readouterr().out.lower()


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_direct_dispatch_reaches_phase_shim(capsys):
    launcher = _load_root_launcher()
    assert launcher.main(["metadata", "--help"]) == 0
    assert "chunk-id" in capsys.readouterr().out.lower()


def test_unknown_entry_exits_two_and_lists_valid_ids(capsys):
    launcher = _load_root_launcher()
    assert launcher.main(["nope", "--flag"]) == 2
    err = capsys.readouterr().err
    assert "nope" in err
    assert "viewer" in err and "metadata" in err


def test_root_help_prints_usage(capsys):
    launcher = _load_root_launcher()
    assert launcher.main(["--help"]) == 0
    assert "entries" in capsys.readouterr().out.lower()


def test_phase_dependencies_declared_and_retrieved():
    from defs.runtime.registry import get_phase_dependencies

    phase2_deps = get_phase_dependencies("filing-catalog")
    assert len(phase2_deps) == 1
    assert phase2_deps[0].phase == "metadata"
    assert phase2_deps[0].dataset == "submission_metadata"

    phase1_deps = get_phase_dependencies("metadata")
    assert phase1_deps == ()
