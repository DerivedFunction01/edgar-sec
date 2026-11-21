from edgar_sec.engine.selection.floor_selection import floor_batch_size


def test_floor_batch_size_spreads_deficit_over_remaining_rounds() -> None:
    assert floor_batch_size(40, 0, 20, 50) == 2
    assert floor_batch_size(40, 39, 2, 50) == 1
    assert floor_batch_size(40, 0, 1, 3) == 3
    assert floor_batch_size(40, 40, 20, 50) == 0
    assert floor_batch_size(40, 0, 0, 50) == 0
