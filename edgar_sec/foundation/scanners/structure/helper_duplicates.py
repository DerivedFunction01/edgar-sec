"""Scanner flagging duplicated helper bodies outside their scaffold homes.
Flags a non-method function whose docstring-stripped body duplicates a body
in another module or a home. Allows methods, sub-six-node one-statement
bodies, the homes, and the census-scoped clusters named below.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..base import Scanner, ScannerFinding
from ..files import discover_python_files
from ..lines import is_scanner_infrastructure

_HOMES = (
    "edgar_sec/engine/forms/common/scaffold/family_scaffold.py",
    "edgar_sec/engine/forms/common/fields/row_extraction.py",
    "edgar_sec/engine/company_family/cohort.py",
    "edgar_sec/engine/forms/cover/boundary/corridor.py",
    "edgar_sec/apps/client/operator/operator_kit.py",
    "edgar_sec/infra/run_lock.py",
    "edgar_sec/infra/storage/dag/working/publication.py",
)

# Sanctioned divergences (coordinator rulings), transcribed
# from the census register: near-miss pairs whose bodies diverge in
# served semantics; this scanner measures identical bodies, never them.
_SANCTIONED_DIVERGENCES = (
    ("edgar_sec/apps/client/operator/operator_config.py", "_error_result"),
    ("edgar_sec/apps/client/operator/operator.py", "_error_result"),
)

# Census scope statement (coordinator ruling; full text in
# the census register): the census's unnamed remainder plus TC-14, out
# of cure scope only while a cluster's full site set matches an entry.
_CENSUS_SCOPED_CLUSTERS = (
    # T-1 `_get_client`
    frozenset(
        {
            ("edgar_sec/apps/client/fast_query/loaders.py", "_get_client"),
            ("edgar_sec/apps/client/fast_query/rendering.py", "_get_client"),
        }
    ),
    # T-2 operator `main`
    frozenset(
        {
            ("edgar_sec/pipelines/document_acquisition/operator.py", "main"),
            ("edgar_sec/pipelines/document_inventory/operator.py", "main"),
            ("edgar_sec/pipelines/filing_catalog/operator.py", "main"),
            ("edgar_sec/pipelines/xbrl_review/operator.py", "main"),
        }
    ),
    # T-3 operator `main`
    frozenset(
        {
            ("edgar_sec/pipelines/datasets/operator.py", "main"),
            ("edgar_sec/pipelines/feeds/operator.py", "main"),
        }
    ),
    # T-4 operator `main`
    frozenset(
        {
            ("edgar_sec/pipelines/document_planning/operator.py", "main"),
            ("edgar_sec/pipelines/table_classification/operator.py", "main"),
        }
    ),
    # T-5 `confirm_network`
    frozenset(
        {
            ("edgar_sec/pipelines/datasets/operator.py", "confirm_network"),
            ("edgar_sec/pipelines/feeds/operator.py", "confirm_network"),
            ("edgar_sec/pipelines/metadata_sync/flows/operator.py", "confirm_network"),
        }
    ),
    # T-6 `status`
    frozenset(
        {
            ("edgar_sec/pipelines/datasets/operator.py", "status"),
            ("edgar_sec/pipelines/feeds/operator.py", "status"),
        }
    ),
    # T-7 `_add_common`
    frozenset(
        {
            ("edgar_sec/pipelines/datasets/cli.py", "_add_common"),
            ("edgar_sec/pipelines/feeds/cli.py", "_add_common"),
        }
    ),
    # T-8 `_value_order`
    frozenset(
        {
            ("edgar_sec/apps/client/financials/financials_stitched.py", "_value_order"),
            ("edgar_sec/engine/xbrl/solve/series/assembly.py", "_value_order"),
        }
    ),
    # T-9 `_slice_patterns` / `_statement_root_patterns`
    frozenset(
        {
            ("edgar_sec/apps/client/core/catalog.py", "_slice_patterns"),
            (
                "edgar_sec/engine/xbrl/discovery/placement_slices.py",
                "_statement_root_patterns",
            ),
        }
    ),
    # T-11 `_merge_sections`
    frozenset(
        {
            ("edgar_sec/engine/forms/form144/sections.py", "_merge_sections"),
            ("edgar_sec/engine/forms/ownership/sections.py", "_merge_sections"),
        }
    ),
    # T-12 `_term_present` / `_present`
    frozenset(
        {
            (
                "edgar_sec/engine/tables/extraction/cascade/geometry/geometry_scoring.py",
                "_term_present",
            ),
            (
                "edgar_sec/engine/tables/extraction/evidence/balance_sheet/derivatives_evidence.py",
                "_present",
            ),
        }
    ),
    # T-13 `_matches`
    frozenset(
        {
            (
                "edgar_sec/engine/tables/extraction/form_tests/walk_form_tests.py",
                "_matches",
            ),
            (
                "edgar_sec/engine/tables/extraction/form_tests/percentage_form.py",
                "_matches",
            ),
        }
    ),
    # T-14 `_precision_rank` / `_precision_tolerance`
    frozenset(
        {
            (
                "edgar_sec/engine/xbrl/parsing/instance_parser.py",
                "_precision_rank",
            ),
            (
                "edgar_sec/engine/xbrl/solve/evaluation/counter_keys.py",
                "_precision_tolerance",
            ),
        }
    ),
    # T-15 `_local_name`
    frozenset(
        {
            ("edgar_sec/engine/xbrl/solve/core/breakdown.py", "_local_name"),
            ("edgar_sec/engine/xbrl/solve/evaluation/counter_keys.py", "_local_name"),
        }
    ),
    # T-16 `_utc_now` / `_now_iso`
    frozenset(
        {
            ("edgar_sec/infra/storage/bulk_archive.py", "_utc_now"),
            ("edgar_sec/pipelines/document_inventory/checkpoint.py", "_now_iso"),
        }
    ),
    # T-17 `_add_output_options`
    frozenset(
        {
            ("edgar_sec/pipelines/document_inventory/cli.py", "_add_output_options"),
            ("edgar_sec/pipelines/xbrl_review/cli.py", "_add_output_options"),
        }
    ),
    # T-18 `resolve_artifacts_root`
    frozenset(
        {
            (
                "edgar_sec/pipelines/document_inventory/commands/common.py",
                "resolve_artifacts_root",
            ),
            (
                "edgar_sec/pipelines/xbrl_review/commands/project.py",
                "resolve_artifacts_root",
            ),
        }
    ),
    # T-19 `sec_transport_factory` / `_configured_http_client`
    frozenset(
        {
            (
                "edgar_sec/pipelines/document_acquisition/commands/common.py",
                "sec_transport_factory",
            ),
            (
                "edgar_sec/pipelines/document_inventory/commands/fixture.py",
                "_configured_http_client",
            ),
        }
    ),
    # T-20 `build_http_client`
    frozenset(
        {
            (
                "edgar_sec/pipelines/document_acquisition/feed/feed_ingest.py",
                "build_http_client",
            ),
            ("edgar_sec/pipelines/feeds/commands/client.py", "build_http_client"),
        }
    ),
    # T-21 `_path_list`
    frozenset(
        {
            ("edgar_sec/pipelines/metadata_sync/flows/reconcile.py", "_path_list"),
            ("edgar_sec/pipelines/metadata_sync/flows/refresh.py", "_path_list"),
        }
    ),
    # T-22 `sorted_keys`
    frozenset(
        {
            (
                "edgar_sec/pipelines/document_inventory/snapshot/projection_inputs.py",
                "sorted_keys",
            ),
            ("edgar_sec/pipelines/filing_catalog/publication.py", "sorted_keys"),
        }
    ),
    # TC-14 cli `main` — coordinator-ruled KEEP
    frozenset(
        {
            ("edgar_sec/pipelines/datasets/cli.py", "main"),
            ("edgar_sec/pipelines/feeds/cli.py", "main"),
        }
    ),
)

_MIN_NODES = 6

_HINT = (
    "home the helper in edgar_sec.engine.forms.common.scaffold.family_scaffold or "
    "edgar_sec.apps.client.operator.operator_kit and import it instead of keeping a "
    "private copy"
)


def _body_statements(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


def _body_key(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    body = _body_statements(node)
    if not body:
        return None
    module = ast.Module(body=body, type_ignores=[])
    node_count = sum(1 for _ in ast.walk(module))
    if len(body) < 2 and node_count <= _MIN_NODES:
        return None
    return ast.dump(module)


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit(node: ast.AST, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not in_class:
                    found.append(child)
                visit(child, in_class)
            else:
                visit(child, in_class)

    visit(tree, False)
    return found


def _parse(path: str) -> ast.Module | None:
    try:
        return ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None


def scan_helper_duplicates() -> list[ScannerFinding]:
    """Flag helper bodies duplicated across modules or against a home."""
    home_keys: dict[str, str] = {}
    for home in _HOMES:
        tree = _parse(home)
        if tree is None:
            continue
        for node in _functions(tree):
            key = _body_key(node)
            if key is not None:
                home_keys.setdefault(key, home)

    collected: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, str | None]] = []
    by_key: dict[str, list[str]] = {}
    sites_by_key: dict[str, set[tuple[str, str]]] = {}
    for path in discover_python_files():
        if path in _HOMES or is_scanner_infrastructure(path):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in _functions(tree):
            key = _body_key(node)
            collected.append((path, node, key))
            if key is not None:
                by_key.setdefault(key, []).append(path)
                sites_by_key.setdefault(key, set()).add((path, node.name))

    scoped_keys = {
        key
        for key, sites in sites_by_key.items()
        if frozenset(sites) in _CENSUS_SCOPED_CLUSTERS
    }

    findings: list[ScannerFinding] = []
    for path, node, key in collected:
        if key is None:
            continue
        if key in scoped_keys:
            continue
        if key in home_keys:
            findings.append(
                ScannerFinding(
                    scanner="helper-duplicates",
                    source="scan",
                    path=path,
                    line=node.lineno,
                    message=(
                        f"helper body {node.name!r} duplicates its home "
                        f"in {home_keys[key]}"
                    ),
                    hint=_HINT,
                )
            )
            continue
        sites = by_key.get(key, [])
        # The census counts clusters touching production (with all
        # their sites); a cluster living wholly in the tools plane is
        # the tools census's measure, not this family's.
        if not any(not site.startswith("edgar_sec/tools/") for site in sites):
            continue
        others = {other for other in sites if other != path}
        if others:
            findings.append(
                ScannerFinding(
                    scanner="helper-duplicates",
                    source="scan",
                    path=path,
                    line=node.lineno,
                    message=(
                        f"helper body {node.name!r} is duplicated in "
                        f"{sorted(others)[0]}"
                    ),
                    hint=_HINT,
                )
            )
    return findings


SCANNER = Scanner(
    name="helper-duplicates",
    description=(
        "scan for function bodies duplicated across modules or against "
        "the scaffold and operator-kit homes"
    ),
    run=scan_helper_duplicates,
)
