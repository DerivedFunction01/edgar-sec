"""Unsupervised feature clustering and orthogonality analysis.

Uses scikit-learn and scipy to discover natural feature groups, measure
pairwise feature correlation, compute PCA loadings, and rank features
by mutual information against clean tabular vs prose ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.feature_selection import mutual_info_classif
from sklearn.preprocessing import StandardScaler

from defs.text.reflow.tools.clustering.dataset import (
    COHORT_CLEAN_PROSE,
    COHORT_CLEAN_TABLES,
    DatasetBlock,
    extract_feature_matrix,
    load_dataset_from_jsonl,
    resolve_reflow_dataset,
)


@dataclass(slots=True)
class ClusteringAnalysisResult:
    """Summary of unsupervised clustering and orthogonality analysis."""

    feature_names: list[str]
    correlation_pearson: np.ndarray
    hac_clusters: dict[int, list[str]]
    kmeans_clusters: dict[int, list[str]]
    pca_explained_variance_ratio: list[float]
    pca_top_loadings: dict[str, list[tuple[str, float]]]
    mutual_info_scores: dict[str, float]
    suggested_feature_groups: dict[str, list[str]]


def compute_feature_correlation(X: np.ndarray, feature_names: list[str]) -> np.ndarray:
    """Compute Pearson correlation matrix between feature columns."""
    # Add epsilon to zero-variance features to prevent NaN
    stds = np.std(X, axis=0)
    safe_X = X.copy()
    zero_var = stds < 1e-9
    safe_X[:, zero_var] += np.random.RandomState(42).normal(
        0, 1e-8, size=(X.shape[0], int(np.sum(zero_var)))
    )
    corr = np.corrcoef(safe_X, rowvar=False)
    # Ensure diagonal is exactly 1.0 and clip
    np.fill_diagonal(corr, 1.0)
    return np.clip(corr, -1.0, 1.0)


def cluster_features_hac(
    corr_matrix: np.ndarray,
    feature_names: list[str],
    n_clusters: int = 5,
) -> dict[int, list[str]]:
    """Cluster features using Hierarchical Agglomerative Clustering on correlation distance."""
    # Distance = 1 - |r|
    dist = 1.0 - np.abs(corr_matrix)
    np.fill_diagonal(dist, 0.0)
    # Ensure distance is symmetric and strictly >= 0
    dist = np.maximum(dist, 0.0)
    dist = (dist + dist.T) / 2.0
    condensed = squareform(dist, checks=False)

    Z = linkage(condensed, method="average")
    cluster_labels = fcluster(Z, t=n_clusters, criterion="maxclust")

    clusters: dict[int, list[str]] = {}
    for feat_idx, cluster_id in enumerate(cluster_labels):
        clusters.setdefault(int(cluster_id), []).append(feature_names[feat_idx])

    return clusters


def cluster_features_kmeans(
    X: np.ndarray,
    feature_names: list[str],
    n_clusters: int = 5,
    random_state: int = 42,
) -> dict[int, list[str]]:
    """Cluster features by running KMeans on standardized transposed matrix (X^T)."""
    scaler = StandardScaler()
    X_std = scaler.fit_transform(X)
    # Transpose so features are samples (D, N)
    features_as_samples = X_std.T

    km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init="auto")
    labels = km.fit_predict(features_as_samples)

    clusters: dict[int, list[str]] = {}
    for feat_idx, cluster_id in enumerate(labels):
        clusters.setdefault(int(cluster_id), []).append(feature_names[feat_idx])

    return clusters


def compute_pca_analysis(
    X: np.ndarray,
    feature_names: list[str],
    n_components: int = 4,
) -> tuple[list[float], dict[str, list[tuple[str, float]]]]:
    """Run PCA to find latent orthogonal dimensions and feature loadings."""
    scaler = StandardScaler()
    X_std = scaler.fit_transform(X)
    n_comp = min(n_components, X.shape[0], X.shape[1])
    if n_comp < 1:
        return [], {}
    pca = PCA(n_components=n_comp, random_state=42)
    pca.fit(X_std)

    explained = [float(v) for v in pca.explained_variance_ratio_]
    top_loadings: dict[str, list[tuple[str, float]]] = {}

    for comp_idx in range(n_comp):
        loadings = pca.components_[comp_idx]
        sorted_indices = np.argsort(np.abs(loadings))[::-1]
        top = [(feature_names[idx], float(loadings[idx])) for idx in sorted_indices[:6]]
        top_loadings[f"PC_{comp_idx + 1}"] = top

    return explained, top_loadings


def compute_mutual_information(
    X: np.ndarray,
    feature_names: list[str],
    cohorts: list[str],
) -> dict[str, float]:
    """Compute mutual information between features and Table vs Prose labels."""
    # Filter to clean tables vs clean prose for pure discriminative signal
    valid_indices = [
        i
        for i, c in enumerate(cohorts)
        if c in (COHORT_CLEAN_TABLES, COHORT_CLEAN_PROSE)
    ]
    if not valid_indices or len({cohorts[i] for i in valid_indices}) < 2:
        # Fallback: treat anything containing "table" as 1, else 0
        y = np.array([1 if "table" in c else 0 for c in cohorts], dtype=int)
        valid_X = X
    else:
        valid_X = X[valid_indices]
        y = np.array(
            [1 if cohorts[i] == COHORT_CLEAN_TABLES else 0 for i in valid_indices],
            dtype=int,
        )

    if valid_X.shape[0] < 3:
        return {name: 0.0 for name in feature_names}

    n_neighbors = min(3, valid_X.shape[0] - 1)
    mi = mutual_info_classif(valid_X, y, n_neighbors=n_neighbors, random_state=42)
    scores = {name: float(score) for name, score in zip(feature_names, mi)}
    return dict(sorted(scores.items(), key=lambda item: item[1], reverse=True))


def suggest_canonical_groups(
    kmeans_clusters: dict[int, list[str]],
    mutual_info: dict[str, float],
) -> dict[str, list[str]]:
    """Map unsupervised clusters to semantic group names based on dominant features."""
    assigned_groups: dict[str, list[str]] = {}

    for cluster_id, feats in kmeans_clusters.items():
        # Inspect dominant keywords in feature names to name the cluster
        has_density = any("density" in f for f in feats)
        has_grammar = any(
            f in ("possessive_count", "relative_clause_count", "function_word_ratio")
            for f in feats
        )
        has_wrap = any(
            f in ("soft_wrap_count", "connector_wrap_count", "width_fill_65_ratio")
            for f in feats
        )
        has_grid = any(
            f
            in (
                "gutter_4_col_count",
                "has_deadspace_corridor",
                "cell_edge_aligned_count",
            )
            for f in feats
        )

        if has_grid:
            name = "2d_grid_geometry"
        elif has_wrap:
            name = "interline_wrap_syntax"
        elif has_grammar:
            name = "macro_grammar_flow"
        elif has_density:
            name = "window_density"
        else:
            name = f"cluster_{cluster_id}"

        # Handle name collisions
        suffix = 1
        final_name = name
        while final_name in assigned_groups:
            suffix += 1
            final_name = f"{name}_{suffix}"

        assigned_groups[final_name] = sorted(
            feats, key=lambda f: mutual_info.get(f, 0.0), reverse=True
        )

    return assigned_groups


def run_unsupervised_analysis(
    blocks: list[DatasetBlock],
    n_clusters: int = 5,
) -> ClusteringAnalysisResult:
    """Run full unsupervised discovery pipeline on dataset blocks."""
    X, feature_names, cohorts = extract_feature_matrix(blocks)

    corr = compute_feature_correlation(X, feature_names)
    hac_clusters = cluster_features_hac(corr, feature_names, n_clusters=n_clusters)
    km_clusters = cluster_features_kmeans(X, feature_names, n_clusters=n_clusters)
    pca_explained, pca_loadings = compute_pca_analysis(X, feature_names, n_components=4)
    mi_scores = compute_mutual_information(X, feature_names, cohorts)
    suggested = suggest_canonical_groups(km_clusters, mi_scores)

    return ClusteringAnalysisResult(
        feature_names=feature_names,
        correlation_pearson=corr,
        hac_clusters=hac_clusters,
        kmeans_clusters=km_clusters,
        pca_explained_variance_ratio=pca_explained,
        pca_top_loadings=pca_loadings,
        mutual_info_scores=mi_scores,
        suggested_feature_groups=suggested,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Unsupervised feature analysis and clustering for reflow."
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        default=None,
        help="Optional path to JSONL dataset, inventory directory, or inventory ID.",
    )
    parser.add_argument(
        "--dataset",
        "-d",
        dest="dataset_flag",
        default=None,
        help="Optional flag specifying dataset path or inventory ID.",
    )
    args = parser.parse_args()

    dataset_arg = args.dataset_flag or args.dataset
    dataset_path = resolve_reflow_dataset(dataset_arg)

    print(f"Loading dataset from {dataset_path}...")
    blocks = load_dataset_from_jsonl(dataset_path)
    print(f"Loaded {len(blocks)} blocks past cover boundary.")
    res = run_unsupervised_analysis(blocks)
    print("\n=== TOP 10 FEATURES BY MUTUAL INFORMATION ===")
    for feat, score in list(res.mutual_info_scores.items())[:10]:
        print(f"  {feat:<35}: {score:.4f}")
    print("\n=== DISCOVERED FEATURE GROUPS (KMeans) ===")
    for group, feats in res.suggested_feature_groups.items():
        print(f"\nGroup [{group}]:")
        for f in feats:
            print(f"  - {f} (MI: {res.mutual_info_scores.get(f, 0.0):.4f})")
    print("\n=== PCA EXPLAINED VARIANCE ===")
    for i, ev in enumerate(res.pca_explained_variance_ratio, 1):
        print(f"  PC_{i}: {ev * 100:.2f}%")
