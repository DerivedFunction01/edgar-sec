"""Company and entity domain projections for client applications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from edgar_sec.domain.identity import Cik
from edgar_sec.domain.submissions.models import Address, EntityProfile

if TYPE_CHECKING:
    from edgar_sec.apps.client.models import FilingsResult


@dataclass(frozen=True, slots=True)
class Company:
    """Company entity projection providing metadata and filing access."""

    profile: EntityProfile

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
    ) -> FilingsResult:
        """Fetch filings for this company."""
        from edgar_sec.apps.client.facade import Edgar

        return Edgar.fetch(
            ciks=self.cik,
            forms=forms,
            limit=limit,
            dates=dates,
            operation=operation,
        )


__all__ = ["Company"]
