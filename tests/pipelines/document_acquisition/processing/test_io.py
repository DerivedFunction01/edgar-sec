from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.processing.io import (
    ProcessingIOError,
    read_bounded_source,
    stage_derived_output,
)


def test_read_bounded_source_verifies_size_and_content(tmp_path: Path) -> None:
    source = b"verified source"
    path = tmp_path / "selected.bin"
    path.write_bytes(source)

    assert read_bounded_source(path, len(source)) == source

    with pytest.raises(ProcessingIOError, match="size or file type differs"):
        read_bounded_source(path, len(source) + 1)

    with pytest.raises(ProcessingIOError, match="size is invalid"):
        read_bounded_source(path, -1)


def test_derived_output_stages_atomically_with_verified_identity(
    tmp_path: Path,
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    output = b"normalized output"
    digest = hashlib.sha256(output).hexdigest()
    staged = stage_derived_output(
        paths,
        run_id="run_test",
        processing_id="proc_test",
        operation_id="operation-test",
        representation="text_normalized",
        output=output,
        expected_sha256=digest,
        expected_size=len(output),
    )

    assert staged.path.is_relative_to(paths.run_staging_root("run_test"))
    assert staged.path.read_bytes() == output
    assert staged.output_sha256 == digest
    assert staged.output_size == len(output)

    with pytest.raises(ProcessingIOError, match="metadata is invalid"):
        stage_derived_output(
            paths,
            run_id="run_test",
            processing_id="proc_test",
            operation_id="other-operation",
            representation="text_normalized",
            output=output,
            expected_sha256="0" * 64,
            expected_size=len(output),
        )
