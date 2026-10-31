from run import ENTRIES


def test_inventory_launcher_routes_through_discovery_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "inventory")
    assert entry.module == "edgar_sec.pipelines.document_inventory.operator"


def test_document_planning_launcher_routes_through_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "planning")
    assert entry.module == "edgar_sec.pipelines.document_planning.operator"


def test_document_acquisition_launcher_routes_through_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "acquisition")
    assert entry.module == "edgar_sec.pipelines.document_acquisition.operator"


def test_dag_launcher_routes_through_dag_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "dag")
    assert entry.module == "edgar_sec.infra.storage.dag.operator"


def test_cohort_launcher_routes_through_cohort_cli() -> None:
    entry = next(item for item in ENTRIES if item.id == "cohort")
    assert entry.module == "edgar_sec.pipelines.cohort.cli"
