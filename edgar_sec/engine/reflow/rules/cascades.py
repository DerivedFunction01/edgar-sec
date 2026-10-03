"""The ordered decision cascade that turns block features into one action.
The list order is the contract: the first rule whose conditions hold decides the block. That is why hard protections precede general prose fallbacks - an ambiguous block must reach a preserve rule, and the only way to guarantee it is for every preserve rule to come first.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..features.context import BlockContext
from ..features.geometry import _Features, _shared_columns
from ..types import (
    _MIN_PROSE_ALPHA_DENSITY,
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    SpanDecision,
)
from .thresholds import FEATURE_REGISTRY

_OP_MAP: dict[str, Callable[[Any, Any], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

_PROSE_DOMINANT_ALPHA_DENSITY = 0.6
_PROSE_DOMINANT_ROW_DENSITY = 0.6
_PROSE_NUMERIC_ROW_DENSITY = 0.8
_RELAXED_PROSE_ALPHA_DENSITY = 0.55
_MIN_REPEATED_NUMERIC_COLUMNS = 1
_MIN_NUMERIC_CELL_ROWS = 2
_MIN_REPEATED_GAP_COLUMNS = 1
_MIN_STRONG_GUTTER = 2
_MIN_STUB_GUTTER_ROWS = 3
_MIN_ALIGNED_CELL_EDGES = 3


@dataclass(frozen=True, slots=True)
class FeatureThreshold:
    """A parameterized comparison against a BlockContext scalar property."""

    feature: str
    op: str
    value: Any

    def evaluate(self, ctx: BlockContext) -> bool:
        return _OP_MAP[self.op](getattr(ctx, self.feature), self.value)


@dataclass(frozen=True, slots=True)
class GroupQuota:
    """Requirement for a minimum and optional maximum active features in a group."""

    group_name: str
    min_active: int = 1
    max_active: int | None = None
    overrides: tuple[FeatureThreshold, ...] = ()


@dataclass(frozen=True, slots=True)
class SynergyRule:
    """Evaluates multiple groups jointly at calibrated lower thresholds."""

    name: str
    group_names: tuple[str, ...]
    min_total_active: int
    min_per_group: int = 1


@dataclass(frozen=True, slots=True)
class Rule:
    """A single declarative rule in the decision cascade."""

    name: str
    action: str
    confidence: float
    direct_conditions: tuple[FeatureThreshold, ...] = ()
    group_quotas: tuple[GroupQuota, ...] = ()
    synergies: tuple[SynergyRule, ...] = ()
    evidence: tuple[str, ...] | None = None
    evidence_builder: Callable[[BlockContext], tuple[str, ...]] | None = None
    rationale: str = ""


FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "linguistic_flow": (
        "possessive_count",
        "relative_clause_count",
        "semicolon_count",
        "grammatical_comma_ratio",
        "article_density",
        "function_word_ratio",
        "verbal_participle_count",
        "prose_phrase_right_half_count",
        "narrative_date_count",
    ),
    "interline_wrapping": (
        "soft_wrap_count",
        "soft_wrap_ratio",
        "connector_wrap_count",
        "width_fill_65_ratio",
    ),
    "row_dynamics": (
        "row_template_periodicity",
        "indent_alternation_ratio",
        "row_shape_autocorrelation",
    ),
    "window_density": (
        "alpha_density_w1",
        "alpha_density_w2",
        "alpha_density_w3",
        "alpha_density_w4",
        "numeric_density_w1",
        "numeric_density_w2",
        "numeric_density_w3",
        "numeric_density_w4",
    ),
    "table_geometry": (
        "gutter_4_col_count",
        "cell_edge_aligned_count",
        "stub_gutter_numeric_count",
        "column_underline_count",
        "has_deadspace_corridor",
    ),
    "structural_anchors": (
        "has_table_wrapper_tag",
        "has_checkbox",
        "is_financial_bridge",
        "has_dot_leader",
        "has_separator_run",
        "non_final_ends_numeric",
        "is_bilateral_inset",
        "exhibit_numbering_count",
        "exhibit_phrase_count",
    ),
}


class RuleEngine:
    """Production rule engine evaluating BlockContext against the calibrated cascade."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules: list[Rule] = rules if rules is not None else self._default_rules()

    def count_active_features(
        self,
        ctx: BlockContext,
        group_name: str,
        overrides: tuple[FeatureThreshold, ...] = (),
        early_stop: int | None = None,
    ) -> tuple[int, list[str]]:
        features = FEATURE_GROUPS.get(group_name, ())
        active: list[str] = []
        if overrides:
            override_map = {ot.feature: ot for ot in overrides}
            for feat_name in features:
                if feat_name in override_map:
                    if override_map[feat_name].evaluate(ctx):
                        active.append(feat_name)
                else:
                    spec = FEATURE_REGISTRY.get(feat_name)
                    if spec is not None and spec.default_predicate(
                        getattr(ctx, feat_name)
                    ):
                        active.append(feat_name)
                if early_stop is not None and len(active) >= early_stop:
                    break
        else:
            for feat_name in features:
                spec = FEATURE_REGISTRY.get(feat_name)
                if spec is not None and spec.default_predicate(getattr(ctx, feat_name)):
                    active.append(feat_name)
                if early_stop is not None and len(active) >= early_stop:
                    break
        return len(active), active

    def evaluate_rule(self, rule: Rule, ctx: BlockContext) -> tuple[bool, list[str]]:
        for cond in rule.direct_conditions:
            if not cond.evaluate(ctx):
                return False, []

        for quota in rule.group_quotas:
            early = (
                quota.min_active
                if (quota.max_active is None and rule.evidence is not None)
                else None
            )
            count, _ = self.count_active_features(
                ctx, quota.group_name, quota.overrides, early_stop=early
            )
            if count < quota.min_active:
                return False, []
            if quota.max_active is not None and count > quota.max_active:
                return False, []

        for syn in rule.synergies:
            total_active = 0
            for g_name in syn.group_names:
                cnt, _ = self.count_active_features(ctx, g_name)
                if cnt < syn.min_per_group:
                    return False, []
                total_active += cnt
            if total_active < syn.min_total_active:
                return False, []

        if rule.evidence_builder is not None:
            return True, list(rule.evidence_builder(ctx))
        if rule.evidence is not None:
            return True, list(rule.evidence)

        evidence: list[str] = [
            f"{cond.feature}{cond.op}{cond.value}" for cond in rule.direct_conditions
        ]
        for quota in rule.group_quotas:
            count, active = self.count_active_features(
                ctx, quota.group_name, quota.overrides
            )
            evidence.append(
                f"group:{quota.group_name}>={quota.min_active} (active={active})"
            )
        for syn in rule.synergies:
            all_active: list[str] = []
            for g_name in syn.group_names:
                _, act = self.count_active_features(ctx, g_name)
                all_active.extend(act)
            evidence.append(
                f"synergy:{syn.name}>={syn.min_total_active} (active={all_active})"
            )
        return True, evidence

    def decide(self, ctx: BlockContext, line_count: int | None = None) -> SpanDecision:
        """Evaluate block context across the rule cascade and return decision."""
        lc = line_count if line_count is not None else ctx.line_count
        if lc <= 1:
            if (
                ctx.alpha_density >= _MIN_PROSE_ALPHA_DENSITY
                and ctx.any_lowercase
                and ctx.exhibit_phrase_count == 0
            ):
                return SpanDecision(
                    ACTION_UNWRAP,
                    0,
                    lc,
                    0.7,
                    ("ordinary_prose",),
                    "unwrap_single_line_prose",
                )
            return SpanDecision(
                ACTION_PRESERVE,
                0,
                lc,
                1.0,
                ("single_line_block",),
                "preserve_single_line_noop",
            )

        for rule in self.rules:
            matched, evidence = self.evaluate_rule(rule, ctx)
            if matched:
                return SpanDecision(
                    rule.action,
                    0,
                    lc,
                    rule.confidence,
                    tuple(evidence) if evidence else (rule.name,),
                    rule.name,
                )

        return SpanDecision(
            ACTION_PRESERVE,
            0,
            lc,
            0.5,
            ("default_preserve",),
            "candidate_preserve",
        )

    @classmethod
    def _default_rules(cls) -> list[Rule]:
        """Canonical declarative rule definitions."""
        return [
            Rule(
                name="hard_preserve_table_tag",
                action=ACTION_PRESERVE,
                confidence=1.0,
                direct_conditions=(
                    FeatureThreshold("has_table_wrapper_tag", "==", True),
                ),
                evidence=("protected_tagged_table",),
                rationale="Tagged tables (<TABLE>...</TABLE>) are byte-for-byte protected.",
            ),
            Rule(
                name="hard_preserve_structural",
                action=ACTION_PRESERVE,
                confidence=1.0,
                direct_conditions=(FeatureThreshold("has_structural", "==", True),),
                evidence=("structural_marker",),
                rationale="Structural section headers and delimiters are preserved.",
            ),
            Rule(
                name="hard_preserve_tab",
                action=ACTION_PRESERVE,
                confidence=0.95,
                direct_conditions=(FeatureThreshold("has_tab", "==", True),),
                evidence=("internal_tab",),
                rationale="Internal tabs indicate legacy tabular column formatting.",
            ),
            Rule(
                name="hard_preserve_signature",
                action=ACTION_PRESERVE,
                confidence=0.90,
                direct_conditions=(FeatureThreshold("has_signature", "==", True),),
                evidence=("signature_shape",),
                rationale="Signature blocks are strictly preserved layout.",
            ),
            Rule(
                name="hard_preserve_checkbox",
                action=ACTION_PRESERVE,
                confidence=0.98,
                direct_conditions=(FeatureThreshold("has_checkbox", "==", True),),
                evidence=("checkbox_layout",),
                rationale="Cover page checkboxes [ ] / [X] are preserved layout.",
            ),
            Rule(
                name="hard_preserve_financial_bridge",
                action=ACTION_PRESERVE,
                confidence=0.95,
                direct_conditions=(
                    FeatureThreshold("is_financial_bridge", "==", True),
                ),
                evidence=("financial_bridge",),
                rationale="Financial section headers must not unwrap into prose.",
            ),
            Rule(
                name="hard_preserve_column_underlines",
                action=ACTION_PRESERVE,
                confidence=0.95,
                direct_conditions=(FeatureThreshold("column_underline_count", ">", 0),),
                evidence=("column_underlines",),
                rationale="Column underline dashes (---   ---) indicate financial grid.",
            ),
            Rule(
                name="unwrap_high_confidence_prose",
                action=ACTION_UNWRAP,
                confidence=0.90,
                direct_conditions=(
                    FeatureThreshold("line_count", ">", 1),
                    FeatureThreshold("non_final_ends_numeric", "==", False),
                    FeatureThreshold("gutter_4_col_count", "==", 0),
                    FeatureThreshold("has_deadspace_corridor", "==", False),
                    FeatureThreshold("has_dot_leader", "==", False),
                    FeatureThreshold("has_separator_run", "==", False),
                    FeatureThreshold("exhibit_phrase_count", "==", 0),
                ),
                group_quotas=(
                    GroupQuota("linguistic_flow", min_active=2),
                    GroupQuota("interline_wrapping", min_active=1),
                ),
                evidence=("ordinary_prose",),
                rationale="Continuous prose with strong linguistic flow, soft wraps, and full width.",
            ),
            Rule(
                name="preserve_prose_dominant_numeric_alignment",
                action=ACTION_PRESERVE,
                confidence=0.60,
                direct_conditions=(
                    FeatureThreshold("shared_numeric_columns", "==", 1),
                    FeatureThreshold("has_separator_run", "==", False),
                    FeatureThreshold(
                        "alpha_density", ">=", _PROSE_DOMINANT_ALPHA_DENSITY
                    ),
                    FeatureThreshold("any_lowercase", "==", True),
                    FeatureThreshold(
                        "numeric_row_density", "<", _PROSE_DOMINANT_ROW_DENSITY
                    ),
                ),
                evidence=("prose_dominant_numeric_alignment",),
                rationale="Prose text with single incidental numeric alignment.",
            ),
            Rule(
                name="preserve_linguistic_numeric_alignment",
                action=ACTION_PRESERVE,
                confidence=0.80,
                direct_conditions=(
                    FeatureThreshold("shared_numeric_columns", ">=", 1),
                    FeatureThreshold(
                        "numeric_row_density", ">=", _PROSE_NUMERIC_ROW_DENSITY
                    ),
                    FeatureThreshold("ends_terminal_punct", "==", True),
                    FeatureThreshold("has_dot_leader", "==", False),
                ),
                group_quotas=(GroupQuota("linguistic_flow", min_active=1),),
                evidence=("linguistic_numeric_prose",),
                rationale="Linguistic sentence evidence overrides numeric alignment.",
            ),
            Rule(
                name="tag_preserve_shared_numeric_table",
                action=ACTION_TAG_AND_PRESERVE,
                confidence=0.80,
                direct_conditions=(
                    FeatureThreshold(
                        "shared_numeric_columns", ">=", _MIN_REPEATED_NUMERIC_COLUMNS
                    ),
                    FeatureThreshold(
                        "numeric_cell_row_count", ">=", _MIN_NUMERIC_CELL_ROWS
                    ),
                ),
                evidence_builder=lambda ctx: (
                    f"repeated_numeric_columns:{ctx.shared_numeric_columns}",
                    f"numeric_rows:{len(ctx.numeric_cell_rows)}",
                ),
                rationale="Repeated numeric column alignment across multiple rows.",
            ),
            Rule(
                name="tag_preserve_separator_grid",
                action=ACTION_TAG_AND_PRESERVE,
                confidence=0.75,
                direct_conditions=(
                    FeatureThreshold("has_separator_run", "==", True),
                    FeatureThreshold(
                        "shared_gaps_count", ">=", _MIN_REPEATED_GAP_COLUMNS
                    ),
                ),
                evidence_builder=lambda ctx: (
                    "separator_grid",
                    f"repeated_gap_columns:{ctx.shared_gaps_count}",
                ),
                rationale="Separator line with repeated gap columns indicates table grid.",
            ),
            Rule(
                name="hard_preserve_dot_leader",
                action=ACTION_PRESERVE,
                confidence=0.95,
                direct_conditions=(FeatureThreshold("has_dot_leader", "==", True),),
                evidence=("dot_leader_layout",),
                rationale="Unqualified dot-leader layouts keep their spacing.",
            ),
            Rule(
                name="hard_preserve_strong_gutter",
                action=ACTION_PRESERVE,
                confidence=0.95,
                direct_conditions=(
                    FeatureThreshold("gutter_4_col_count", ">=", _MIN_STRONG_GUTTER),
                ),
                evidence=("gutter_layout",),
                rationale="Multi-line recurrence of >= 4-space gap indicates preserved layout.",
            ),
            Rule(
                name="hard_preserve_stub_gutter_numeric",
                action=ACTION_TAG_AND_PRESERVE,
                confidence=0.80,
                direct_conditions=(
                    FeatureThreshold(
                        "stub_gutter_numeric_count", ">=", _MIN_STUB_GUTTER_ROWS
                    ),
                    FeatureThreshold(
                        "cell_edge_aligned_count", ">=", _MIN_ALIGNED_CELL_EDGES
                    ),
                ),
                evidence_builder=lambda ctx: (
                    f"stub_gutter_numeric:{ctx.stub_gutter_numeric_count}",
                ),
                rationale="Repeated stub -> gutter -> numeric rows indicate table.",
            ),
            Rule(
                name="hard_preserve_numeric_aligned",
                action=ACTION_PRESERVE,
                confidence=0.90,
                direct_conditions=(
                    FeatureThreshold(
                        "cell_edge_aligned_count", ">=", _MIN_ALIGNED_CELL_EDGES
                    ),
                ),
                evidence=("aligned_cells",),
                rationale="Repeated aligned numeric right edges indicate preserved layout.",
            ),
            Rule(
                name="hard_preserve_separator_run",
                action=ACTION_PRESERVE,
                confidence=0.95,
                direct_conditions=(FeatureThreshold("has_separator_run", "==", True),),
                evidence=("separator_run",),
                rationale="Separator runs (--- or ===) indicate divider or dash leader.",
            ),
            Rule(
                name="hard_preserve_deadspace_corridor",
                action=ACTION_PRESERVE,
                confidence=0.95,
                direct_conditions=(
                    FeatureThreshold("has_deadspace_corridor", "==", True),
                ),
                evidence=("deadspace_corridor",),
                rationale="Persistent blank corridor spanning lines indicates columnar grid.",
            ),
            Rule(
                name="hard_preserve_exhibit_index",
                action=ACTION_PRESERVE,
                confidence=0.95,
                direct_conditions=(FeatureThreshold("exhibit_phrase_count", ">", 0),),
                evidence=("exhibit_index_phrase",),
                rationale="Exhibit index phrases indicate tabular exhibit descriptions.",
            ),
            Rule(
                name="unwrap_single_line_prose",
                action=ACTION_UNWRAP,
                confidence=0.70,
                direct_conditions=(
                    FeatureThreshold("line_count", "<=", 1),
                    FeatureThreshold("alpha_density", ">=", _MIN_PROSE_ALPHA_DENSITY),
                    FeatureThreshold("any_lowercase", "==", True),
                    FeatureThreshold("exhibit_phrase_count", "==", 0),
                ),
                evidence=("ordinary_prose",),
                rationale="Single-line prose with sufficient alpha density and lowercase text.",
            ),
            Rule(
                name="preserve_single_line_noop",
                action=ACTION_PRESERVE,
                confidence=1.0,
                direct_conditions=(FeatureThreshold("line_count", "<=", 1),),
                evidence=("single_line_block",),
                rationale="Single-line non-prose block preserved.",
            ),
            Rule(
                name="unwrap_ordinary_prose_no_gaps",
                action=ACTION_UNWRAP,
                confidence=0.70,
                direct_conditions=(
                    FeatureThreshold("has_separator_run", "==", False),
                    FeatureThreshold("max_gap", "<", 3),
                    FeatureThreshold("shared_numeric_columns", "==", 0),
                    FeatureThreshold("alpha_density", ">=", _MIN_PROSE_ALPHA_DENSITY),
                    FeatureThreshold("any_lowercase", "==", True),
                    FeatureThreshold("exhibit_phrase_count", "==", 0),
                ),
                evidence=("ordinary_prose",),
                rationale="Continuous prose without layout gaps or numeric alignment.",
            ),
            Rule(
                name="preserve_layout_gap_candidate",
                action=ACTION_PRESERVE,
                confidence=0.60,
                direct_conditions=(FeatureThreshold("max_gap", ">=", 3),),
                evidence=("layout_gap_without_alignment",),
                rationale="Significant layout gaps without table alignment preserved conservatively.",
            ),
            Rule(
                name="unwrap_general_prose",
                action=ACTION_UNWRAP,
                confidence=0.70,
                direct_conditions=(
                    FeatureThreshold("alpha_density", ">=", _MIN_PROSE_ALPHA_DENSITY),
                    FeatureThreshold("any_lowercase", "==", True),
                    FeatureThreshold("exhibit_phrase_count", "==", 0),
                ),
                evidence=("ordinary_prose",),
                rationale="General continuous prose with lowercase letters.",
            ),
            Rule(
                name="default_preserve_ambiguous",
                action=ACTION_PRESERVE,
                confidence=0.60,
                evidence=("default_preserve",),
                rationale="Ambiguous or unverified block preserved to guarantee zero table corruption.",
            ),
        ]


_DEFAULT_ENGINE = RuleEngine()


def decide_block(ctx: BlockContext, line_count: int | None = None) -> SpanDecision:
    """Evaluate block context using the production RuleEngine singleton."""
    return _DEFAULT_ENGINE.decide(ctx, line_count=line_count)


def _decide(
    context_or_features: BlockContext | _Features,
    line_count: int,
    has_masked: bool = False,
) -> SpanDecision:
    if has_masked:
        return SpanDecision(
            ACTION_PRESERVE,
            0,
            line_count,
            1.0,
            ("protected_tagged_table",),
            "hard_preserve",
        )

    if getattr(context_or_features, "is_width_overflow", False):
        has_num = bool(
            getattr(context_or_features, "numeric_cell_row_count", 0) >= 1
            or getattr(context_or_features, "shared_numeric_columns", 0) >= 1
            or getattr(context_or_features, "numeric_cell_rows", ())
        )
        action = ACTION_TAG_AND_PRESERVE if has_num else ACTION_PRESERVE
        ev = ("width_overflow_table",) if has_num else ("width_overflow_layout",)
        trace = "high_confidence_table" if has_num else "candidate_preserve"
        return SpanDecision(action, 0, line_count, 0.85, ev, trace)

    if isinstance(context_or_features, BlockContext):
        d = decide_block(context_or_features, line_count=line_count)
        if d.action == ACTION_UNWRAP:
            ev = d.evidence if d.evidence else ("ordinary_prose",)
            return SpanDecision(
                ACTION_UNWRAP, 0, line_count, d.confidence, ev, "fast_prose"
            )
        if d.action == ACTION_TAG_AND_PRESERVE:
            trace = "high_confidence_table"
        elif "hard_preserve" in d.trace:
            trace = "hard_preserve"
        elif "single_line" in d.trace or "noop" in d.trace:
            trace = "fast_noop"
        else:
            trace = "candidate_preserve"
        return SpanDecision(d.action, 0, line_count, d.confidence, d.evidence, trace)

    features = context_or_features
    if features.has_structural:
        return SpanDecision(
            ACTION_PRESERVE, 0, line_count, 1.0, ("structural_marker",), "hard_preserve"
        )
    if features.has_tab:
        return SpanDecision(
            ACTION_PRESERVE, 0, line_count, 0.95, ("internal_tab",), "hard_preserve"
        )
    if features.has_dot_leader:
        return SpanDecision(
            ACTION_PRESERVE,
            0,
            line_count,
            0.95,
            ("dot_leader_layout",),
            "hard_preserve",
        )
    if features.has_signature:
        return SpanDecision(
            ACTION_PRESERVE, 0, line_count, 0.9, ("signature_shape",), "hard_preserve"
        )

    if features.has_separator or features.max_gap >= 3 or features.numeric_cell_rows:
        shared_numeric = _shared_columns(
            features.numeric_cell_rows, min_rows=3, tolerance=1
        )
        shared_gaps = _shared_columns(features.gap_start_rows, min_rows=3, tolerance=1)
        if shared_numeric >= 1 and len(features.numeric_cell_rows) >= 2:
            numeric_row_density = len(features.numeric_cell_rows) / max(
                features.non_blank, 1
            )
            is_prose_dominant = (
                shared_numeric <= 3
                and not features.has_separator
                and features.alpha_density >= _PROSE_DOMINANT_ALPHA_DENSITY
                and features.any_lowercase
                and numeric_row_density < _PROSE_DOMINANT_ROW_DENSITY
            )
            if is_prose_dominant:
                if getattr(features, "is_justified_prose", False):
                    return SpanDecision(
                        ACTION_UNWRAP,
                        0,
                        line_count,
                        0.7,
                        ("justified_prose",),
                        "fast_prose",
                    )
                return SpanDecision(
                    ACTION_PRESERVE,
                    0,
                    line_count,
                    0.6,
                    ("prose_dominant_numeric_alignment",),
                    "candidate_preserve",
                )
            return SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                0,
                line_count,
                0.8,
                (
                    f"repeated_numeric_columns:{shared_numeric}",
                    f"numeric_rows:{len(features.numeric_cell_rows)}",
                ),
                "high_confidence_table",
            )
        if features.has_separator and shared_gaps >= 1:
            return SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                0,
                line_count,
                0.75,
                ("separator_grid", f"repeated_gap_columns:{shared_gaps}"),
                "high_confidence_table",
            )
        is_justified = getattr(features, "is_justified_prose", False)
        if (
            not features.has_separator
            and (features.max_gap < 3 or is_justified)
            and shared_numeric == 0
            and features.alpha_density >= _MIN_PROSE_ALPHA_DENSITY
            and features.any_lowercase
        ):
            ev = ("justified_prose",) if is_justified else ("ordinary_prose",)
            return SpanDecision(ACTION_UNWRAP, 0, line_count, 0.7, ev, "fast_prose")
        return SpanDecision(
            ACTION_PRESERVE,
            0,
            line_count,
            0.6,
            ("layout_gap_without_alignment",),
            "candidate_preserve",
        )

    if features.alpha_density >= _MIN_PROSE_ALPHA_DENSITY and features.any_lowercase:
        return SpanDecision(
            ACTION_UNWRAP, 0, line_count, 0.7, ("ordinary_prose",), "fast_prose"
        )
    return SpanDecision(
        ACTION_PRESERVE, 0, line_count, 0.5, ("default_preserve",), "candidate_preserve"
    )


__all__ = [
    "FEATURE_GROUPS",
    "FeatureThreshold",
    "GroupQuota",
    "Rule",
    "RuleEngine",
    "SynergyRule",
    "_decide",
    "decide_block",
]
