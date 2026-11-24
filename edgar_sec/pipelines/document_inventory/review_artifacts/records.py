from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import resolve_alias


_EXHIBIT_TYPES = ("EX-", "EX ")


_EXHIBIT_NAMES = {"GRAPHIC", "ZIP"}


def _is_exhibit(document_type: str) -> bool:
    return document_type.startswith(_EXHIBIT_TYPES) or document_type in _EXHIBIT_NAMES


def _matches_form(document_type: str, form: str) -> bool:
    normalized_type = document_type.strip().upper()
    normalized_form = form.strip().upper()
    if normalized_type == normalized_form:
        return True
    family = resolve_alias(normalized_form)
    return family is not None and resolve_alias(normalized_type) == family


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_summary(row: dict) -> dict:
    return {
        field: row.get(field)
        for field in (
            "table_kind",
            "row_ordinal",
            "sequence",
            "document_type",
            "filename",
            "href",
            "archive_url",
        )
    }


def _finding(case: dict, code: str, **details) -> dict:
    return {
        "run_id": case.get("run_id"),
        "accession": case["accession"],
        "request_url": case["request_url"],
        "response_sha256": case["response_sha256"],
        "code": code,
        **details,
    }
