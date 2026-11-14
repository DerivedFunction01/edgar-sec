"""Exhibit type-variant vocabulary: the one spelling of a type family.

A consumer never spells its own variant list; it asks the predicate
for the family it means. Amendment marks are parenthesized suffixes
or a trailing ``.A`` segment, in any combination.
"""

from __future__ import annotations

#: The base type spelling of the Exhibit 13 family (Item 601 code 13).
EX13_BASE_TYPE = "EX-13"


def is_ex13_type(document_type: str | None) -> bool:
    """Whether a filing-index type names the Exhibit 13 family.

    The family is the base type, the base plus a decimal suffix of
    any digit width, and the ``.PDF`` suffix form of either.
    """
    if not document_type:
        return False
    value = document_type.strip().upper()
    if value.endswith(".PDF"):
        value = value[:-4]
    while value.endswith(")") and "(" in value:
        value = value[: value.rfind("(")].rstrip(".")
    if value == EX13_BASE_TYPE:
        return True
    if not value.startswith(f"{EX13_BASE_TYPE}."):
        return False
    suffix = value[len(EX13_BASE_TYPE) + 1 :]
    return suffix == "A" or suffix.isdigit()


__all__ = ["EX13_BASE_TYPE", "is_ex13_type"]
