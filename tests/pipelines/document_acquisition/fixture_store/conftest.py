import pytest

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


@pytest.fixture
def acquisition_paths(tmp_path):
    return resolve_acquisition_paths(artifacts_root=tmp_path)
