from pathlib import Path

import pytest

from edgar_sec.pipelines.document_acquisition.plan_projection.relation_validation import (
    RelationValidationError,
    validate_relation_coverage,
)


def test_empty_target_bundle_requires_empty_related_relations():
    relations = {
        "target_operations": (),
        "source_requests": (),
        "operation_inputs": (),
    }

    validate_relation_coverage((), relations)

    relations["operation_inputs"] = (Path("orphan.parquet"),)
    with pytest.raises(RelationValidationError, match="without target rows"):
        validate_relation_coverage((), relations)
