"""Form 144 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import FormReport


@dataclass(frozen=True, slots=True)
class Form144Report(FormReport):
    """Specialized projection for Form 144 filings."""

    def xml(self) -> str | bytes | None:
        rendered = self.filing.render()
        if rendered is not None:
            return rendered
        return self.filing.raw()

    def text(self) -> str | None:
        data = self.xml()
        if isinstance(data, str):
            return data
        if data is not None:
            return data.decode("utf-8", errors="replace")
        return None


__all__ = ["Form144Report"]
