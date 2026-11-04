"""Reg A report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import FormReport


@dataclass(frozen=True, slots=True)
class RegAReport(FormReport):
    """Specialized report projection for Regulation A filings."""

    def xml(self) -> str | bytes | None:
        """Rendered XML payload or fallback raw XML bytes."""
        rendered = self.filing.render()
        if rendered is not None:
            return rendered
        return self.filing.raw()

    def text(self) -> str | None:
        """Text representation of the filing payload."""
        rendered = self.filing.render("render_to_txt")
        if isinstance(rendered, str):
            return rendered
        data = self.xml()
        if isinstance(data, str):
            return data
        if data is not None:
            return data.decode("utf-8", errors="replace")
        return None


__all__ = ["RegAReport"]
