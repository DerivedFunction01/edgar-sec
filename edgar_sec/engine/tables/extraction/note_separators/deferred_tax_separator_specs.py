"""Deferred tax separator parameter table (TEST_DEFERRED_TAX_SEPARATOR).
The priced composition as built: the determined deferred-tax core
absent, conjoined with a shares stub or a geography stub
(provenance: PROV_DEFERRED_TAX_SEPARATOR).
"""

from dataclasses import dataclass

GEO_TOKENS = (
    "u s",
    "united states",
    "china",
    "foreign",
    "domestic",
    "international",
    "non u s",
    "europe",
    "asia",
    "canada",
    "mexico",
    "japan",
    "united kingdom",
    "americas",
    "worldwide",
)

SHARES_TOKEN = "shares"


@dataclass(frozen=True)
class DeferredTaxSeparatorSpec:
    """One family's separator: the priced composition's stub data.
    The refusal fires when the deferred-tax core is absent and a
    content leg holds: a shares stub, or a geography stub."""

    family: str
    geo_tokens: tuple[str, ...] = GEO_TOKENS
    shares_token: str = SHARES_TOKEN


DEFERRED_TAX_SEPARATOR_SPECS = {
    "deferred_tax": DeferredTaxSeparatorSpec(family="deferred_tax"),
}
