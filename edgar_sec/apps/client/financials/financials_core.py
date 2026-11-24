"""Served scalar and series machinery for the financials catalogue.

Every metric is served at a named span class: the annual class first,
then the fallback ladder, with the served class named alongside.
"""

from __future__ import annotations

from collections.abc import Callable

from edgar_sec.apps.client.core.composition import ChainTerms, CompositionResult
from edgar_sec.apps.client.core.kernel import FilingKernel
from edgar_sec.apps.client.financials.financials_classed import ClassedSeriesMixin
from edgar_sec.apps.client.financials.financials_eps import EpsSharesMixin
from edgar_sec.apps.client.financials.financials_series import SeriesMixin


class FinancialsCore(SeriesMixin, ClassedSeriesMixin, EpsSharesMixin):
    """Kernel-bound serving machinery the metric catalogue is expressed in."""

    def __init__(
        self,
        kernel: FilingKernel,
        *,
        composition_resolver: Callable[[ChainTerms, int | None], CompositionResult]
        | None = None,
    ) -> None:
        self._kernel = kernel
        self._facts = kernel.facts
        self._arcs = kernel.calculation_arcs
        self._definition_arcs = kernel.definition_arcs
        self._taxonomy = kernel.taxonomy
        self._labels = kernel.labels
        self._records = kernel.records
        self._composition_resolver = composition_resolver
        self._composer = kernel.composer
