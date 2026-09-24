"""Contract tests for unsupervised clustering and orthogonality analysis."""

from __future__ import annotations

import numpy as np

from defs.text.reflow.tools.clustering.context import BlockContext
from defs.text.reflow.tools.clustering.dataset import (
    COHORT_CLEAN_PROSE,
    COHORT_CLEAN_TABLES,
    DatasetBlock,
    extract_feature_matrix,
)
from defs.text.reflow.tools.clustering.tests.test_context import (
    SAMPLE_PROSE,
    SAMPLE_TABLE,
)
from defs.text.reflow.tools.clustering.unsupervised import (
    compute_feature_correlation,
    run_unsupervised_analysis,
)


def test_clustering_pipeline_on_sample_blocks() -> None:
    blocks = [
        DatasetBlock(
            block_id="p1",
            text=SAMPLE_PROSE,
            cohort=COHORT_CLEAN_PROSE,
            control_role="ordinary_prose_control",
            accession=None,
            document_path=None,
            start_line=10,
            end_line=14,
            body_start_line=0,
            context=BlockContext(SAMPLE_PROSE),
        ),
        DatasetBlock(
            block_id="t1",
            text=SAMPLE_TABLE,
            cohort=COHORT_CLEAN_TABLES,
            control_role="protected_table_control",
            accession=None,
            document_path=None,
            start_line=20,
            end_line=30,
            body_start_line=0,
            context=BlockContext(SAMPLE_TABLE),
        ),
    ]

    X, feat_names, _cohorts = extract_feature_matrix(blocks)
    assert X.shape[0] == 2
    assert X.shape[1] == len(feat_names)

    corr = compute_feature_correlation(X, feat_names)
    assert corr.shape == (len(feat_names), len(feat_names))
    assert np.all(corr >= -1.0) and np.all(corr <= 1.0)

    res = run_unsupervised_analysis(blocks, n_clusters=3)
    assert len(res.kmeans_clusters) == 3
    assert len(res.pca_explained_variance_ratio) == 2
    assert len(res.mutual_info_scores) == len(feat_names)
