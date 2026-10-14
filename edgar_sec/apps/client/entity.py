"""Company and entity domain projections for client applications."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence

from edgar_sec.domain.identity import Cik
from edgar_sec.domain.submissions.models import Address, EntityProfile

if TYPE_CHECKING:
    from edgar_sec.apps.client.facade import Edgar
    from edgar_sec.apps.client.models import FilingsResult
    from edgar_sec.engine.xbrl.models import FilingXbrl


@dataclass(frozen=True, slots=True)
class Company:
    """Company entity projection providing metadata and filing access."""

    profile: EntityProfile
    facade: Edgar | None = None

    @property
    def cik(self) -> Cik:
        return self.profile.cik

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(listing.ticker for listing in self.profile.listings)

    @property
    def sic(self) -> str | None:
        return self.profile.sic_code

    @property
    def sic_description(self) -> str | None:
        return self.profile.sic_description

    @property
    def state_of_incorporation(self) -> str | None:
        return self.profile.state_of_incorporation

    @property
    def fiscal_year_end(self) -> str | None:
        return self.profile.fiscal_year_end

    @property
    def mailing_address(self) -> Address | None:
        return self.profile.mailing_address

    @property
    def business_address(self) -> Address | None:
        return self.profile.business_address

    def filings(
        self,
        forms: str | Sequence[str] | None = None,
        *,
        limit: int | None = None,
        dates: str | None = None,
        operation: str = "raw",
        mode: Literal["fast", "pipeline"] = "fast",
        publish_snapshot: bool = False,
        workers: int | None = None,
    ) -> FilingsResult:
        """Fetch filings for this company."""
        from edgar_sec.apps.client.facade import Edgar

        client = self.facade or Edgar()
        return client.fetch(
            ciks=self.cik.value,
            forms=forms or (),
            limit=limit,
            dates=dates,
            operation=operation,
            mode=mode,
            publish_snapshot=publish_snapshot,
            workers=workers,
        )

    def clear_cache(self) -> int:
        """Clear cached documents for this company."""
        from edgar_sec.apps.client.cache import get_default_cache

        cache = self.facade.cache if self.facade else get_default_cache()
        return cache.clear(cik=self.cik.value)

    def export_cache_zip(self, zip_path: Path | str) -> Path:
        """Export cached documents for this company to a ZIP archive."""
        from edgar_sec.apps.client.cache import get_default_cache

        cache = self.facade.cache if self.facade else get_default_cache()
        return cache.export_zip(zip_path, cik=self.cik.value)

    def xbrl(self, form: str | None = None) -> FilingXbrl | None:
        """Fetch latest filing and return parsed FilingXbrl."""
        if self.facade is None:
            return None
        forms = [form] if form is not None else ()
        filings = self.filings(forms=forms, limit=1)
        latest = filings.latest()
        if latest is None:
            return None
        return self.facade.xbrl(latest)


__all__ = ["Company"]
