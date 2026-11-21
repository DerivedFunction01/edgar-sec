"""Domain model for the Section 12 registration cluster."""

from __future__ import annotations

from enum import StrEnum


class Form12RegKind(StrEnum):
    """Which face of the cluster a filing carries."""

    NOTIFICATION = "notification"
    REGISTRATION = "registration"
    PREDECESSOR_REGISTRATION = "predecessor_registration"


__all__ = ["Form12RegKind"]
