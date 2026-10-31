"""Identity-checked rollforward and breakdown graphs over statement nodes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from edgar_sec.engine.xbrl.solve.identities import (
    identity_discrepancy,
    identity_verified,
    movement_sign,
    signed_rollforward_total,
)
from edgar_sec.engine.xbrl.solve.statement import StatementNode


@dataclass(frozen=True, slots=True)
class CashRollforwardGraph:
    """ASU 2016-18 rollforward: beginning plus change against the end total."""

    beginning: float | None = None
    net_change: float | None = None
    end: float | None = None
    beginning_date: str | None = None
    end_date: str | None = None
    balance_sheet_total: float | None = None
    components: tuple[StatementNode, ...] = ()
    total_concept: str | None = None

    def _rollforward_computed(self) -> float | None:
        if self.net_change is None:
            return None
        return signed_rollforward_total(self.beginning, ((self.net_change, 1.0),))

    @property
    def rollforward_discrepancy(self) -> float | None:
        """End minus (beginning + change), or None when a leg is missing."""
        return identity_discrepancy(self.end, self._rollforward_computed())

    @property
    def rollforward_verified(self) -> bool | None:
        """Whether beginning + change reproduces the reported end total."""
        return identity_verified(self.end, self._rollforward_computed())

    @property
    def balance_sheet_discrepancy(self) -> float | None:
        """End minus the reconciled balance-sheet lines, or None if absent."""
        return identity_discrepancy(self.end, self.balance_sheet_total)

    @property
    def balance_sheet_verified(self) -> bool | None:
        """Whether the balance-sheet lines reproduce the end total."""
        return identity_verified(self.end, self.balance_sheet_total)


@dataclass(frozen=True, slots=True)
class Level3RollforwardGraph:
    """ASC 820 Level-3 reconciliation for one class, checked by identity."""

    dimensions: tuple[tuple[str, str], ...] = ()
    opening: float | None = None
    closing: float | None = None
    gains_earnings: float | None = None
    gains_oci: float | None = None
    purchases: float | None = None
    sales: float | None = None
    issues: float | None = None
    settlements: float | None = None
    transfers_in: float | None = None
    transfers_out: float | None = None
    transfers_net: float | None = None
    net_change: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    balance_concept: str | None = None
    side: str | None = None
    missing_components: tuple[str, ...] = ()
    movements: tuple[StatementNode, ...] = ()

    @property
    def axis_qname(self) -> str | None:
        """The class axis when the class carries exactly one dimension."""
        return self.dimensions[0][0] if len(self.dimensions) == 1 else None

    @property
    def member_qname(self) -> str | None:
        """The class member when the class carries exactly one dimension."""
        return self.dimensions[0][1] if len(self.dimensions) == 1 else None

    @property
    def total_gains(self) -> float | None:
        """Filed gains across earnings and OCI, or None when neither filed."""
        parts = [
            value
            for value in (self.gains_earnings, self.gains_oci)
            if value is not None
        ]
        return sum(parts) if parts else None

    @property
    def computed_closing(self) -> float | None:
        """Opening plus signed movements, signs from declared valence."""
        side = "liability" if self.side == "liability" else "asset"
        return signed_rollforward_total(
            self.opening,
            (
                (self.gains_earnings, movement_sign("level3", "gains_earnings", side)),
                (self.gains_oci, movement_sign("level3", "gains_oci", side)),
                (self.purchases, movement_sign("level3", "purchases")),
                (self.issues, movement_sign("level3", "issues")),
                (self.transfers_in, movement_sign("level3", "transfers_in")),
                (self.transfers_net, movement_sign("level3", "transfers_net")),
                (self.sales, movement_sign("level3", "sales")),
                (self.settlements, movement_sign("level3", "settlements")),
                (self.transfers_out, movement_sign("level3", "transfers_out")),
            ),
        )

    @property
    def discrepancy(self) -> float | None:
        """Closing minus the component-computed closing."""
        return identity_discrepancy(self.closing, self.computed_closing)

    @property
    def verified(self) -> bool | None:
        """Whether opening plus components reproduces the closing balance."""
        return identity_verified(self.closing, self.computed_closing)

    def _change_computed(self) -> float | None:
        if self.net_change is None:
            return None
        return signed_rollforward_total(self.opening, ((self.net_change, 1.0),))

    @property
    def change_discrepancy(self) -> float | None:
        """Closing minus (opening plus the filed period net change)."""
        return identity_discrepancy(self.closing, self._change_computed())

    @property
    def change_verified(self) -> bool | None:
        """Whether the filed period net change reproduces the closing."""
        return identity_verified(self.closing, self._change_computed())


@dataclass(frozen=True, slots=True)
class SegmentMember:
    """One axis member's value within a segment breakdown."""

    member_qname: str
    label: str
    value: float


@dataclass(frozen=True, slots=True)
class SegmentBreakdownGraph:
    """Per-axis member breakdown checked against the undimensioned total."""

    concept_qname: str | None = None
    axis_qname: str | None = None
    total: float | None = None
    members: tuple[SegmentMember, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    instant_date: str | None = None
    unit: str | None = None

    @property
    def member_sum(self) -> float | None:
        """Sum of member values, or None when the breakdown is empty."""
        if not self.members:
            return None
        return sum(member.value for member in self.members)

    @property
    def discrepancy(self) -> float | None:
        """Total minus member sum, or None when either side is missing."""
        return identity_discrepancy(self.total, self.member_sum)

    @property
    def verified(self) -> bool | None:
        """Whether the members reproduce the reported total."""
        return identity_verified(self.total, self.member_sum)


@dataclass(frozen=True, slots=True)
class PensionRollforwardSide:
    """One defined-benefit rollforward: opening plus movements vs closing."""

    opening: float | None = None
    closing: float | None = None
    movements: Mapping[str, float] = field(default_factory=dict)
    negative_roles: frozenset[str] = frozenset()

    @property
    def computed_closing(self) -> float | None:
        """Opening plus signed movements; negative roles enter subtracted."""
        return signed_rollforward_total(
            self.opening,
            tuple(
                (value, -1.0 if role in self.negative_roles else 1.0)
                for role, value in self.movements.items()
            ),
        )

    @property
    def discrepancy(self) -> float | None:
        """Closing minus the component-computed closing."""
        return identity_discrepancy(self.closing, self.computed_closing)

    @property
    def verified(self) -> bool | None:
        """Whether opening plus movements reproduces the closing balance."""
        return identity_verified(self.closing, self.computed_closing)


@dataclass(frozen=True, slots=True)
class PensionFundedStatusGraph:
    """Defined-benefit funded status for one plan class, checked by identity."""

    dimensions: tuple[tuple[str, str], ...] = ()
    plan_assets: PensionRollforwardSide = field(default_factory=PensionRollforwardSide)
    obligation: PensionRollforwardSide = field(default_factory=PensionRollforwardSide)
    funded_status_filed: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    missing_components: tuple[str, ...] = ()
    movements: tuple[StatementNode, ...] = ()

    @property
    def funded_status(self) -> float | None:
        """Closing plan assets minus closing obligation, when both filed."""
        if self.plan_assets.closing is None or self.obligation.closing is None:
            return None
        return self.plan_assets.closing - self.obligation.closing

    @property
    def funded_discrepancy(self) -> float | None:
        """Filed funded status minus the computed assets-minus-obligation."""
        return identity_discrepancy(self.funded_status_filed, self.funded_status)

    @property
    def funded_verified(self) -> bool | None:
        """Whether the filed funded status equals assets minus obligation."""
        return identity_verified(self.funded_status_filed, self.funded_status)


@dataclass(frozen=True, slots=True)
class EquityComponentRollforward:
    """One equity component's rollforward: opening plus movements vs closing."""

    member_qname: str
    opening: float | None = None
    closing: float | None = None
    movements: Mapping[str, float] = field(default_factory=dict)
    filed_net_change: float | None = None

    @property
    def computed_closing(self) -> float | None:
        """Opening plus signed movements, or None when opening is unfiled."""
        return signed_rollforward_total(
            self.opening,
            tuple((value, 1.0) for value in self.movements.values()),
        )

    @property
    def discrepancy(self) -> float | None:
        """Closing minus the movement-computed closing."""
        return identity_discrepancy(self.closing, self.computed_closing)

    @property
    def verified(self) -> bool | None:
        """Whether opening plus movements reproduces the closing balance."""
        return identity_verified(self.closing, self.computed_closing)

    def _change_computed(self) -> float | None:
        if self.filed_net_change is None:
            return None
        return signed_rollforward_total(self.opening, ((self.filed_net_change, 1.0),))

    @property
    def change_discrepancy(self) -> float | None:
        """Closing minus (opening plus the filed period net change)."""
        return identity_discrepancy(self.closing, self._change_computed())

    @property
    def change_verified(self) -> bool | None:
        """Whether the filed period net change reproduces the closing."""
        return identity_verified(self.closing, self._change_computed())


@dataclass(frozen=True, slots=True)
class EquityRollforwardGraph:
    """Statement of changes in equity for one period, checked by identity."""

    axis_qname: str | None = None
    balance_concept: str | None = None
    opening: float | None = None
    closing: float | None = None
    components: tuple[EquityComponentRollforward, ...] = ()
    antichain_members: tuple[str, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    missing_components: tuple[str, ...] = ()
    movements: tuple[StatementNode, ...] = ()

    def component(self, member_qname: str) -> EquityComponentRollforward | None:
        """Return one component's rollforward by member, or None."""
        for comp in self.components:
            if comp.member_qname == member_qname:
                return comp
        return None

    @property
    def computed_closing(self) -> float | None:
        """Opening total plus the antichain components' signed movements."""
        return signed_rollforward_total(
            self.opening,
            tuple(
                (sum(comp.movements.values()), 1.0)
                for comp in self.components
                if comp.member_qname in self.antichain_members
            ),
        )

    @property
    def discrepancy(self) -> float | None:
        """Closing total minus the movement-computed closing total."""
        return identity_discrepancy(self.closing, self.computed_closing)

    @property
    def verified(self) -> bool | None:
        """Whether opening plus movements reproduces the closing total."""
        return identity_verified(self.closing, self.computed_closing)

    @property
    def components_sum(self) -> float | None:
        """Sum of the antichain components' closing balances, if all filed."""
        values = [
            comp.closing
            for comp in self.components
            if comp.member_qname in self.antichain_members
        ]
        if not values or any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    @property
    def components_discrepancy(self) -> float | None:
        """Closing total minus the antichain components' closing sum."""
        return identity_discrepancy(self.closing, self.components_sum)

    @property
    def components_verified(self) -> bool | None:
        """Whether the antichain components reproduce the closing total."""
        return identity_verified(self.closing, self.components_sum)
