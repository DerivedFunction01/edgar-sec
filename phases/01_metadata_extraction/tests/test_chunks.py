from conftest import imp

chunks = imp("phases.01_metadata_extraction.core.chunks")

import pytest


def test_assign_chunks_is_contiguous_and_inclusive():
    ciks = [str(i).zfill(10) for i in range(10)]
    ranges = chunks.assign_chunks(ciks, chunk_size=4)
    assert len(ranges) == 3
    assert (ranges[0].start_row, ranges[0].end_row) == (0, 3)
    assert (ranges[1].start_row, ranges[1].end_row) == (4, 7)
    assert (ranges[2].start_row, ranges[2].end_row) == (8, 9)
    assert ranges[0].row_count == 4
    assert ranges[2].row_count == 2
    assert ranges[1].first_cik == ciks[4]
    assert ranges[1].last_cik == ciks[7]


def test_assign_chunks_no_overlap_and_full_coverage():
    ciks = [f"{i:010d}" for i in range(37)]
    ranges = chunks.assign_chunks(ciks, chunk_size=10)
    covered = []
    for rng in ranges:
        covered.extend(range(rng.start_row, rng.end_row + 1))
    assert covered == list(range(37))


def test_verify_chunk_assignment_rejects_gaps():
    ciks = [f"{i:010d}" for i in range(5)]
    ranges = chunks.assign_chunks(ciks, 2)
    with pytest.raises(chunks.ChunkMismatchError):
        chunks.verify_chunk_assignment(ciks, [ranges[1]])


def test_select_chunk_rejects_fingerprint_and_version_mismatch():
    ciks = [f"{i:010d}" for i in range(6)]
    ranges = chunks.assign_chunks(ciks, 3)
    plan = {
        "schema_version": "1.0.0",
        "input_fingerprint": "abc123",
        "chunks": [rng.to_dict() for rng in ranges],
    }
    assert chunks.select_chunk(plan, 2, "abc123", "1.0.0").chunk_id == 2
    with pytest.raises(chunks.ChunkMismatchError):
        chunks.select_chunk(plan, 2, "other", "1.0.0")
    with pytest.raises(chunks.ChunkMismatchError):
        chunks.select_chunk(plan, 2, "abc123", "9.9.9")
    with pytest.raises(chunks.ChunkMismatchError):
        chunks.select_chunk(plan, 99, "abc123", "1.0.0")


def test_plan_hash_excludes_itself():
    plan = {"a": 1, "plan_hash": "old"}
    assert chunks.plan_hash(plan) == chunks.plan_hash({"a": 1})
