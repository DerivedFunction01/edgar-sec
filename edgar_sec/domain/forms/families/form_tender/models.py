"""Tender family document-kind vocabulary shared by domain and engine."""

from __future__ import annotations

from enum import StrEnum


class TenderKind(StrEnum):
    """Document kinds inside the merged tender family; the going-private
    kind spans three cover faces, told apart at analysis time.
    """

    SCHEDULE_TO = "schedule_to"
    SOLICITATION = "solicitation"
    GOING_PRIVATE = "going_private"
    ISSUER_TENDER_PREDECESSOR = "issuer_tender_predecessor"
    THIRD_PARTY_PREDECESSOR = "third_party_predecessor"
    FOREIGN_NOTICE = "foreign_notice"


__all__ = ["TenderKind"]
