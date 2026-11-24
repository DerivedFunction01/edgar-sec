from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.operator.operator_drill_options import DETAIL_LEVELS
from edgar_sec.apps.client.operator.operator_kit import (
    accession_text as _accession_text,
    error_result as _error,
)
from edgar_sec.domain.forms.families.current.processing import (
    PROFILE as _CURRENT_PROFILE,
)
from edgar_sec.foundation.runtime.render import KeyValueRow, ProseRow


def _absent(kind: str, title: str, message: str, data: dict | None = None):
    return _error(kind, "absent", title, message, {**(data or {}), "present": False})


def _find_aggregate(result: Any, accession: str) -> Any:
    items = getattr(result, "items", None)
    candidates = items
    if candidates is None:
        try:
            candidates = iter(result)
        except TypeError:
            return None
    for filing in candidates:
        if _accession_text(filing) == accession:
            return filing
    return None


def _current_aggregate(session: Any) -> Any:
    """The position's aggregate, falling back to the sets' retained results."""
    filing = getattr(session, "current_filing", None)
    if filing is None:
        return None
    if getattr(filing, "aggregate", None) is not None:
        return filing.aggregate
    for working in session.sets.values():
        if working.result is not None:
            found = _find_aggregate(working.result, filing.accession)
            if found is not None:
                return found
    return None


def _capable(session: Any, flag: str) -> bool:
    aggregate = _current_aggregate(session)
    return aggregate is not None and bool(getattr(aggregate, flag, False))


def _earnings_capable(session: Any) -> bool:
    """Whether the filing's family is the current-report family.

    Keyed on the aggregate's own processing profile, compared against the
    current family's profile, so the operator stays form-agnostic.
    """
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return False
    profile = getattr(aggregate, "processing_profile", None)
    return profile is not None and profile.family == _CURRENT_PROFILE.family


def _gate(session: Any, flag: str, kind: str, title: str, noun: str):
    """An honest-absence result when the current filing lacks a capability."""
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return _absent(
            kind, title, "no filing aggregate is retained for the current filing"
        )
    if not bool(getattr(aggregate, flag, False)):
        form = str(getattr(aggregate, "form", "") or "")
        return _absent(
            kind,
            title,
            f"current filing ({form}) has no {noun}",
            {"accession": _accession_text(aggregate), "form": form},
        )
    return None


def _lead_block(text: str) -> str:
    lines = text.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    block: list[str] = []
    while index < len(lines) and lines[index].strip():
        block.append(lines[index])
        index += 1
    return "\n".join(block)


def _prose(
    title: str,
    text: str,
    detail: str,
    context: dict[str, Any],
    extra: dict[str, Any],
):
    from edgar_sec.apps.client.operator.operator_results import OpResult

    if detail not in DETAIL_LEVELS:
        return _error(
            "prose", "invalid_options", title, f"unknown detail level: {detail}"
        )
    shown_text = _lead_block(text) if detail == "minimal" else text
    data: dict[str, Any] = {
        **extra,
        "text": shown_text,
        "detail": detail,
        "full_size": len(text),
        "shown_size": len(shown_text),
    }
    components: list[Any] = [ProseRow(shown_text)]
    if detail == "full":
        data["context"] = context
        rows = [("position", f"{context['position']} of {context['total']}")]
        if context.get("previous_title"):
            rows.append(("previous", str(context["previous_title"])))
        if context.get("next_title"):
            rows.append(("next", str(context["next_title"])))
        components.extend(KeyValueRow(k, v) for k, v in rows)
    return OpResult(
        kind="prose",
        title=title,
        components=tuple(components),
        data=data,
        total=1,
        shown=1,
        hints=("back", "select_filing"),
    )


def _sole_context() -> dict[str, Any]:
    return {"position": 1, "total": 1, "previous_title": None, "next_title": None}


def _sequence_context(items: list[Any], index: int) -> dict[str, Any]:
    def title_of(item: Any) -> str | None:
        return str(getattr(item, "title", "") or "") or None

    return {
        "position": index + 1,
        "total": len(items),
        "previous_title": title_of(items[index - 1]) if index > 0 else None,
        "next_title": title_of(items[index + 1]) if index + 1 < len(items) else None,
    }


def _primary_text(aggregate: Any) -> str:
    report = aggregate.as_report()
    text_method = getattr(report, "text", None)
    if callable(text_method):
        text = text_method()
        if text:
            return str(text)
    raw = aggregate.raw()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        return raw
    rendered = aggregate.render()
    if isinstance(rendered, bytes):
        return rendered.decode("utf-8", errors="replace")
    return str(rendered or "")
