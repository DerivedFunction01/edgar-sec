"""Deterministic extraction of earnings-exhibit tables and headlines.

Tables ride the geometry machinery behind ``normalize_document``; a
table that cannot be structured is accounted as a review signal, never
silently dropped or best-effort parsed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.domain.forms.families.current.taxonomy import (
    uses_ifrs_headline_vocabulary,
)
from edgar_sec.engine.document_processing.pdf import (
    PdfConversionError,
    convert_pdf_to_text,
)
from edgar_sec.engine.forms.earnings.models import (
    EarningsExhibitResult,
    EarningsTable,
    EarningsTableRow,
    ExhibitCandidate,
    HeadlineFigure,
    HeadlineFigures,
    ReviewSignal,
)
from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.engine.forms.earnings.selection import select_exhibit_candidates
from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.engine.forms.plugins.exhibit_selection import evaluate_exhibit_body
from edgar_sec.engine.tables.ascii_html.model import TableGeometry

_WS_RE = re.compile(r"\s+")
_REVENUE_RE = re.compile(r"^(total\s+)?(net\s+)?(revenues?|sales)\b")
_NET_INCOME_RE = re.compile(r"^net\s+(income|loss|earnings)\b")

_CLASS_HTML_STATEMENT = "HTML statement exhibits (8-K/8-K/A)"
_CLASS_NO_TABLES = "HTML exhibits with no statement tables"
_CLASS_TEXT = "plain-text exhibits"
_CLASS_PDF_TEXT = "PDF exhibits (converted to text class)"
_CLASS_SIXK = "6-K IFRS statement exhibits"
_CLASS_IMAGE = "image exhibits"
_CLASS_MULTI = "multi-exhibit filings (EX-99.1 lacks the statement)"


@dataclass(frozen=True, slots=True)
class ExhibitPayload:
    """One candidate exhibit's identity and payload, or its absence."""

    candidate: ExhibitCandidate
    raw: bytes | None


@dataclass(frozen=True, slots=True)
class _Structured:
    candidate: ExhibitCandidate
    text: str
    tables: tuple[EarningsTable, ...]
    geometries: tuple[TableGeometry, ...]


def _collapse(value: str) -> str:
    return _WS_RE.sub(" ", value or "").strip()


def _label_of(row: tuple[str, ...]) -> str:
    return _collapse(row[0]).lower() if row else ""


def _first_numeric(row: tuple[str, ...]) -> str | None:
    for cell in row[1:]:
        collapsed = _collapse(cell)
        if clean_numeric(collapsed) is not None:
            return collapsed
    return None


def _find_value(
    rows: tuple[tuple[str, ...], ...], predicate: Callable[[str], bool]
) -> HeadlineFigure | None:
    for row in rows:
        if predicate(_label_of(row)):
            value = _first_numeric(row)
            if value is not None:
                return HeadlineFigure(label=_collapse(row[0]), value=value)
    return None


def _is_revenue_label(label: str) -> bool:
    return (
        bool(_REVENUE_RE.match(label))
        and "cost" not in label
        and "per share" not in label
    )


def _is_net_income_label(label: str) -> bool:
    return (
        bool(_NET_INCOME_RE.match(label))
        and "per share" not in label
        and "comprehensive" not in label
    )


def _is_eps_label(label: str, basis: str) -> bool:
    return basis in label and ("share" in label or "eps" in label)


def _table_roles(
    rows: tuple[tuple[str, ...], ...], table_index: int
) -> tuple[str, ...]:
    text = " ".join(_collapse(cell) for row in rows for cell in row).lower()
    labels = [_label_of(row) for row in rows]
    roles: list[str] = []
    if any(_is_revenue_label(label) for label in labels) and any(
        _is_net_income_label(label) for label in labels
    ):
        roles.append("income_statement")
    if "total assets" in text and (
        "total liabilities" in text
        or "stockholders' equity" in text
        or "shareholders' equity" in text
    ):
        roles.append("balance_sheet")
    if "net cash" in text and "operating activities" in text:
        roles.append("cash_flow")
    if (
        "non-gaap" in text
        or "non gaap" in text
        or ("adjusted" in text and "gaap" in text)
    ):
        roles.append("non_gaap_recon")
    if "guidance" in text or "outlook" in text:
        roles.append("guidance")
    if "segment" in text:
        roles.append("segment")
    if (
        len(rows) <= 10
        and table_index < 3
        and any(_is_revenue_label(label) for label in labels)
        and any("share" in label or "eps" in label for label in labels)
    ):
        roles.append("summary")
    return tuple(roles)


def _structure_table(geometry: TableGeometry, position: int) -> EarningsTable:
    rows = tuple(tuple(_collapse(cell) for cell in row) for row in geometry.rows)
    caption: str | None = None
    body = rows
    if len(rows) >= 2:
        nonempty = [cell for cell in rows[0] if cell]
        if len(nonempty) == 1:
            caption = nonempty[0]
            body = rows[1:]
    periods: tuple[str, ...] = ()
    header_count = geometry.header_row_count
    if 0 < header_count <= len(body):
        periods = tuple(cell for cell in body[header_count - 1][1:] if cell)
        body = body[header_count:]
    typed_rows = tuple(
        EarningsTableRow(label=row[0] if row else "", values=tuple(row[1:]))
        for row in body
        if any(row)
    )
    return EarningsTable(
        table_index=position,
        caption=caption,
        periods=periods,
        rows=typed_rows,
        roles=_table_roles(rows, position),
    )


def _headline_from(
    tables: tuple[EarningsTable, ...],
    raw_rows: dict[int, tuple[tuple[str, ...], ...]],
) -> HeadlineFigures | None:
    ordered = sorted(tables, key=lambda table: 0 if "summary" in table.roles else 1)
    for table in ordered:
        rows = raw_rows.get(table.table_index, ())
        revenue = _find_value(rows, _is_revenue_label)
        if revenue is None:
            continue
        net_income = _find_value(rows, _is_net_income_label)
        eps = _find_value(rows, lambda label: _is_eps_label(label, "diluted")) or (
            _find_value(rows, lambda label: _is_eps_label(label, "basic"))
        )
        if net_income is not None or eps is not None:
            locus = "summary-table" if "summary" in table.roles else "statement-table"
            return HeadlineFigures(
                revenue=revenue,
                net_income=net_income,
                eps=eps,
                source_table_index=table.table_index,
                locus=locus,
            )
    return None


def _role_mismatch(text: str, form: str, candidate: ExhibitCandidate) -> bool:
    identity = ExhibitIdentity("reg_s_k_item_601", "99")
    assessment = evaluate_exhibit_body(
        text,
        filing_form=form,
        expected_type="EX-99",
        expected_identity=identity,
    )
    if assessment is None or assessment.disposition != "possible_role_mismatch":
        return False
    observed = assessment.observed_identity
    if isinstance(observed, ExhibitIdentity):
        return not (observed.code == "99" or observed.code.startswith("99."))
    return False


def _structure_payload(
    payload: ExhibitPayload,
    form: str,
    signals: list[ReviewSignal],
) -> _Structured | None:
    candidate = payload.candidate
    if payload.raw is None:
        signals.append(
            ReviewSignal(
                kind="payload_not_acquired",
                specimen_class=_CLASS_HTML_STATEMENT,
                filename=candidate.filename,
                detail="exhibit payload was never acquired",
            )
        )
        return None
    if candidate.kind == "pdf":
        try:
            conversion = convert_pdf_to_text(payload.raw)
        except PdfConversionError:
            signals.append(
                ReviewSignal(
                    kind="pdf_unreadable",
                    specimen_class=_CLASS_PDF_TEXT,
                    filename=candidate.filename,
                    detail="PDF bytes are not a readable PDF",
                )
            )
            return None
        signals.append(
            ReviewSignal(
                kind="text_exhibit",
                specimen_class=_CLASS_PDF_TEXT,
                filename=candidate.filename,
                detail="converted text carries no table geometry",
            )
        )
        return _Structured(candidate, conversion.text, (), ())
    try:
        result: NormalizationResult = normalize_document(
            payload.raw, form=form, document_path=candidate.filename
        )
    except ValueError:
        signals.append(
            ReviewSignal(
                kind="binary_route_refused",
                specimen_class=_CLASS_IMAGE,
                filename=candidate.filename,
                detail="normalize_document refused a binary route",
            )
        )
        return None
    if _role_mismatch(result.text, form, candidate):
        signals.append(
            ReviewSignal(
                kind="possible_role_mismatch",
                specimen_class=_CLASS_HTML_STATEMENT,
                filename=candidate.filename,
                detail="exhibit evaluator reports a role mismatch",
            )
        )
        return None
    if candidate.kind == "text":
        signals.append(
            ReviewSignal(
                kind="text_exhibit",
                specimen_class=_CLASS_TEXT,
                filename=candidate.filename,
                detail="text exhibits carry no deterministic table geometry",
            )
        )
        return _Structured(candidate, result.text, (), result.table_geometries)
    tables: list[EarningsTable] = []
    for position, geometry in enumerate(result.table_geometries):
        if geometry.is_fallback:
            signals.append(
                ReviewSignal(
                    kind="fallback_geometry",
                    specimen_class=_CLASS_HTML_STATEMENT,
                    filename=candidate.filename,
                    table_index=position,
                    detail="geometry machinery fell back for this table",
                )
            )
            continue
        tables.append(_structure_table(geometry, position))
    return _Structured(candidate, result.text, tuple(tables), result.table_geometries)


def extract_earnings_payloads(
    *,
    accession: str,
    form: str,
    payloads: tuple[ExhibitPayload, ...],
) -> EarningsExhibitResult:
    """Extract tables and headline figures from selected exhibit payloads."""
    candidates = tuple(payload.candidate for payload in payloads)
    images = tuple(c.filename for c in candidates if c.kind == "image")
    signals: list[ReviewSignal] = []
    if not candidates:
        return EarningsExhibitResult(
            accession=accession,
            form=form,
            exhibit=None,
            tables=(),
            headline=None,
            review_signals=(),
            text="",
            image_exhibits=(),
            absence_reason="no_ex99_exhibit",
        )
    documents = tuple(p for p in payloads if p.candidate.kind != "image")
    if not documents:
        signals.append(
            ReviewSignal(
                kind="image_exhibit_refused",
                specimen_class=_CLASS_IMAGE,
                filename=images[0],
                detail="image exhibits are inventoried, never OCRed",
            )
        )
        return EarningsExhibitResult(
            accession=accession,
            form=form,
            exhibit=candidates[0],
            tables=(),
            headline=None,
            review_signals=tuple(signals),
            text="",
            image_exhibits=images,
        )
    structured: list[_Structured] = []
    for payload in documents:
        built = _structure_payload(payload, form, signals)
        if built is not None:
            structured.append(built)
    if not structured:
        return EarningsExhibitResult(
            accession=accession,
            form=form,
            exhibit=documents[0].candidate,
            tables=(),
            headline=None,
            review_signals=tuple(signals),
            text="",
            image_exhibits=images,
        )
    effective = next(
        (
            item
            for item in structured
            if any("income_statement" in table.roles for table in item.tables)
        ),
        structured[0],
    )
    if effective is not structured[0]:
        signals.append(
            ReviewSignal(
                kind="exhibit_fallback",
                specimen_class=_CLASS_MULTI,
                filename=effective.candidate.filename,
                detail="earlier EX-99 exhibits carry no income statement",
            )
        )
    tables = effective.tables
    if not tables:
        if effective.candidate.kind == "html":
            signals.append(
                ReviewSignal(
                    kind="no_statement_tables",
                    specimen_class=_CLASS_NO_TABLES,
                    filename=effective.candidate.filename,
                    detail="headline figures are prose-borne in this exhibit",
                )
            )
        return EarningsExhibitResult(
            accession=accession,
            form=form,
            exhibit=effective.candidate,
            tables=(),
            headline=None,
            review_signals=tuple(signals),
            text=effective.text,
            image_exhibits=images,
        )
    if uses_ifrs_headline_vocabulary(form):
        signals.append(
            ReviewSignal(
                kind="sixk_headline_vocabulary",
                specimen_class=_CLASS_SIXK,
                filename=effective.candidate.filename,
                detail="headline figures need the IFRS label vocabulary",
            )
        )
        return EarningsExhibitResult(
            accession=accession,
            form=form,
            exhibit=effective.candidate,
            tables=tables,
            headline=None,
            review_signals=tuple(signals),
            text=effective.text,
            image_exhibits=images,
        )
    structured_ids = {table.table_index for table in tables}
    raw_rows = {
        position: tuple(tuple(_collapse(cell) for cell in row) for row in geometry.rows)
        for position, geometry in enumerate(effective.geometries)
        if position in structured_ids
    }
    headline = _headline_from(tables, raw_rows)
    if headline is None:
        has_statement = any("income_statement" in table.roles for table in tables)
        signals.append(
            ReviewSignal(
                kind="headline_not_extracted",
                specimen_class=_CLASS_HTML_STATEMENT,
                filename=effective.candidate.filename,
                detail=(
                    "income statement present but headline rules found no figure set"
                    if has_statement
                    else "no income statement among the extracted tables"
                ),
            )
        )
    return EarningsExhibitResult(
        accession=accession,
        form=form,
        exhibit=effective.candidate,
        tables=tables,
        headline=headline,
        review_signals=tuple(signals),
        text=effective.text,
        image_exhibits=images,
    )


def extract_earnings_exhibit(filing: FilingAggregate) -> EarningsExhibitResult:
    """Extract the earnings exhibit of one current-report filing."""
    attachments: tuple[FilingAttachment, ...] = filing.get_attachments()
    candidates = select_exhibit_candidates(
        tuple((a.filename, a.document_type) for a in attachments)
    )
    by_name = {a.filename: a for a in attachments}
    payloads = tuple(
        ExhibitPayload(
            candidate=candidate,
            raw=(
                by_name[candidate.filename].raw() if candidate.kind != "image" else None
            ),
        )
        for candidate in candidates
        if candidate.filename in by_name
    )
    return extract_earnings_payloads(
        accession=str(filing.accession), form=filing.form, payloads=payloads
    )


__all__ = ["ExhibitPayload", "extract_earnings_exhibit", "extract_earnings_payloads"]
