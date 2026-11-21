from edgar_sec.domain.forms.families.ownership.taxonomy import (
    OWNERSHIP_STATE_CODES,
    VALID_TRANSACTION_CODES,
)
from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES


def test_transaction_codes_match_the_ownership_specification() -> None:
    assert VALID_TRANSACTION_CODES == frozenset(
        "A C D E F G H I J L M O P S U W X Z".split()
    )


def test_ownership_state_codes_match_the_specification_count() -> None:
    assert OWNERSHIP_STATE_CODES == STATE_POSTAL_CODES | {"AS", "MP"}
