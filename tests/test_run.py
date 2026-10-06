from run import ENTRIES


def test_inventory_launcher_routes_through_discovery_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "inventory")
    assert entry.module == "edgar_sec.pipelines.document_inventory.operator"
