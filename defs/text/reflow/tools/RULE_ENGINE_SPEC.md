# Reflow Rule Engine & Classification Architecture Specification

This document defines the production software architecture, lazy evaluation pipeline, and declarative rule engine for classifying layout blocks in `defs/text/reflow/`.

While [HYPOTHESES.md](./HYPOTHESES.md) catalogues the scientific discovery, empirical distributions, and physical layout invariants, this specification defines the **production implementation contract**.

---

## 1. Core Architectural Invariants

### Invariant 1: The Raw Scalar Invariant
Feature extractors must compute and return their **natural scalar value** (integer count, float ratio, or character distance). 
- **Anti-Pattern**: Creating redundant boolean feature flags (e.g. `has_possessive`, `possessive_ge_2`, `possessive_rate_ge_0_5`).
- **Standard**: The extractor computes `possessive_count: int` **once**. Rules and feature groups then apply parameterized comparison predicates (`>`, `>=`, `==`, `<=`) against that single scalar value.

### Invariant 2: The Lazy Memoization Contract
Features must be evaluated **on demand** and cached on the context instance:
- Features are implemented as memoized properties (`@functools.cached_property`).
- Computation is zero-cost until a rule actively inspects that property.
- If an early rule terminates the cascade (e.g. single-line block or table tag), expensive algorithms (2D dead-space matrices, greedy rewrap simulations) are **never executed**.
- Memory is strictly scoped to the evaluation of a single block (zero cross-block state or memory leaks).

### Invariant 3: Single Canonical Taxonomy (Declare Once)
Feature groups are declared once as an immutable taxonomy. Different rules requiring higher, lower, or inverted thresholds must **not** duplicate group definitions under new names. Instead, rules reference the canonical group name and supply a **parameterized constraint tuple or override dictionary**.

### Invariant 4: Cross-Family Feature Synergy (Orthogonal Quorums)
Signals from orthogonal domains (Macro-Grammar, Micro-Line-Wrap, Geometric-Anchors) reinforce each other. When multiple orthogonal families provide simultaneous evidence, intra-family thresholds are relaxed (e.g. requiring only 1 feature per family rather than 3 in isolation), maximizing candidate recall while eliminating table false positives.

### Invariant 5: Short-Circuit Pipeline
Rule evaluation must short-circuit at two granularities:
1. **Rule-Level**: As soon as a required anchor gate or condition fails, subsequent condition checks in that rule abort immediately.
2. **Family Quota Level**: As soon as a group satisfies its required activation quota (`min_active`), evaluation of any remaining features in that group aborts immediately.

---

## 2. Lazy Scalar Context (`BlockContext`)

The `BlockContext` encapsulates a single layout block and provides memoized access to all scalar features:

```python
from functools import cached_property
import re
from typing import Any


class BlockContext:
    def __init__(self, text: str, raw_lines: list[str]):
        self.text = text
        self.lines = [l.rstrip() for l in raw_lines if l.strip()]
        self.line_count = len(self.lines)

    # ------------------------------------------------------------------
    # Category A: Structural & Anchor Boundaries
    # ------------------------------------------------------------------
    @cached_property
    def ends_terminal_punct(self) -> bool:
        if not self.lines:
            return False
        return bool(re.search(r'[.!?]["\')\]]*$', self.lines[-1]))

    @cached_property
    def starts_capital_or_indent(self) -> bool:
        if not self.lines:
            return False
        first = self.lines[0].lstrip()
        return bool(re.match(r'^[A-Z"\'\(]', first))

    @cached_property
    def has_table_wrapper_tag(self) -> bool:
        return "__SEC_TBL_" in self.text or "<TABLE>" in self.text

    # ------------------------------------------------------------------
    # Category B: Linguistic & Grammar (Raw Counts & Ratios)
    # ------------------------------------------------------------------
    @cached_property
    def possessive_count(self) -> int:
        return len(re.findall(r"\b[A-Za-z]+'s\b", self.text))

    @cached_property
    def relative_clause_count(self) -> int:
        return len(
            re.findall(
                r"\b(which|that|who|whose|whom|whereby|wherein)\b",
                self.text,
                re.IGNORECASE,
            )
        )

    @cached_property
    def semicolon_count(self) -> int:
        return self.text.count(";")

    @cached_property
    def grammatical_comma_ratio(self) -> float:
        g = len(re.findall(r"(?<=[a-zA-Z]),\s+(?=[a-zA-Z])", self.text))
        n = len(re.findall(r"(?<=\d),(?=\d)", self.text))
        return g / (g + n) if (g + n) > 0 else 0.0

    @cached_property
    def article_density(self) -> float:
        if not self.line_count:
            return 0.0
        arts = len(re.findall(r"\b(the|a|an)\b", self.text, re.IGNORECASE))
        return arts / self.line_count

    # ------------------------------------------------------------------
    # Category C: Micro-Layout & Interline Wrapping
    # ------------------------------------------------------------------
    @cached_property
    def soft_wrap_count(self) -> int:
        if self.line_count < 2:
            return 0
        count = 0
        for i in range(self.line_count - 1):
            if re.search(r"[a-zA-Z,]$", self.lines[i].strip()) and re.match(
                r"^[a-z]", self.lines[i + 1].strip()
            ):
                count += 1
        return count

    @cached_property
    def soft_wrap_ratio(self) -> float:
        if self.line_count < 2:
            return 0.0
        return self.soft_wrap_count / (self.line_count - 1)

    @cached_property
    def connector_wrap_count(self) -> int:
        if self.line_count < 2:
            return 0
        pat = re.compile(
            r"\b(the|a|an|of|to|in|for|with|and|or|that|which|as|by|from|under|between)\s*$",
            re.I,
        )
        return sum(1 for l in self.lines[:-1] if pat.search(l.strip()))

    @cached_property
    def width_fill_65_ratio(self) -> float:
        if not self.lines:
            return 0.0
        non_final = self.lines[:-1] if self.line_count > 1 else self.lines
        return sum(1 for l in non_final if len(l) >= 65) / len(non_final)

    @cached_property
    def continuation_col0_ratio(self) -> float:
        if self.line_count < 2:
            return 1.0
        cont = self.lines[1:]
        return sum(1 for l in cont if (len(l) - len(l.lstrip())) <= 4) / len(cont)

    @cached_property
    def rewrap_residual(self) -> float:
        # H-GEO-13: greedy rewrap line count distortion
        if self.line_count < 3:
            return 0.0
        words = self.text.split()
        if not words:
            return 0.0
        source_widths = [len(l) for l in self.lines[:-1]]
        target_w = (
            sorted(source_widths)[len(source_widths) // 2] if source_widths else 75
        )
        wrapped = []
        cur = []
        cur_len = 0
        for w in words:
            add_len = len(w) + (1 if cur else 0)
            if cur_len + add_len <= target_w:
                cur.append(w)
                cur_len += add_len
            else:
                if cur:
                    wrapped.append(" ".join(cur))
                cur = [w]
                cur_len = len(w)
        if cur:
            wrapped.append(" ".join(cur))
        return abs(len(wrapped) - self.line_count) / self.line_count

    # ------------------------------------------------------------------
    # Category D: 2D Spatial Geometry & Grid Structure
    # ------------------------------------------------------------------
    @cached_property
    def gutter_4_col_count(self) -> int:
        # Measures maximum recurrence of column gap >= 4 spaces across lines
        if self.line_count < 2:
            return 0
        counts = [0] * 85
        for l in self.lines:
            for m in re.finditer(r"\s{4,}", l):
                for c in range(min(84, m.start()), min(85, m.end())):
                    counts[c] += 1
        return max(counts) if counts else 0

    @cached_property
    def has_deadspace_corridor(self) -> bool:
        # H-GEO-14: Persistent 3-column empty vertical strip
        if self.line_count < 3:
            return False
        left_m = min(len(l) - len(l.lstrip()) for l in self.lines)
        right_m = max(len(l) for l in self.lines)
        if right_m - left_m < 15:
            return False
        for c in range(left_m + 3, right_m - 3):
            if all(
                c + dc < len(l) and l[c + dc].isspace()
                for l in self.lines
                for dc in range(3)
            ):
                return True
        return False

    @cached_property
    def cell_edge_aligned_count(self) -> int:
        # H-GEO-18: Vertical alignment of numeric right edges (+-1 col)
        right_edges = {}
        for l in self.lines:
            for m in re.finditer(r"\$?\d+(?:,\d{3})*(?:\.\d+)?%?", l):
                if re.search(r"\d", m.group(0)):
                    col = m.end()
                    right_edges[col] = right_edges.get(col, 0) + 1
        return max(right_edges.values()) if right_edges else 0

    @cached_property
    def stub_gutter_numeric_count(self) -> int:
        # H-GEO-17: Line matching [Text Stub] -> [Gutter >= 3] -> [Numeric Cell]
        pat = re.compile(r"[a-zA-Z]{2,}\s{3,}\$?\d+")
        return sum(1 for l in self.lines if pat.search(l))

    # ------------------------------------------------------------------
    # Category E: Exhibit Index Specifics
    # ------------------------------------------------------------------
    @cached_property
    def exhibit_numbering_count(self) -> int:
        pat = re.compile(
            r"^\s*(?:exhibit\s+)?(?:\(?[0-9]{1,2}(?:\.[0-9]{1,2})*[a-zA-Z]?\)?)[\s\.\-]+",
            re.I,
        )
        return sum(1 for l in self.lines if pat.match(l))

    @cached_property
    def exhibit_phrase_count(self) -> int:
        pat = re.compile(
            r"\b(filed\s+as\s+exhibit|incorporated\s+(?:herein\s+)?by\s+reference|filed\s+herewith)\b",
            re.I,
        )
        return sum(1 for l in self.lines if pat.search(l))
```

---

## 3. Canonical Feature Registry & Default Predicates

Every feature declared in `BlockContext` has a canonical entry with its return type and **default activation predicate**:

```python
import operator

FEATURE_REGISTRY = {
    # Structural Anchors
    "ends_terminal_punct": {"type": bool, "default": (operator.eq, True)},
    "starts_capital_or_indent": {"type": bool, "default": (operator.eq, True)},
    "has_table_wrapper_tag": {"type": bool, "default": (operator.eq, True)},
    # Linguistic Grammar
    "possessive_count": {"type": int, "default": (operator.gt, 0)},
    "relative_clause_count": {"type": int, "default": (operator.gt, 0)},
    "semicolon_count": {"type": int, "default": (operator.gt, 0)},
    "grammatical_comma_ratio": {"type": float, "default": (operator.ge, 0.70)},
    "article_density": {"type": float, "default": (operator.ge, 0.80)},
    # Interline & Layout
    "soft_wrap_count": {"type": int, "default": (operator.gt, 0)},
    "soft_wrap_ratio": {"type": float, "default": (operator.ge, 0.20)},
    "connector_wrap_count": {"type": int, "default": (operator.gt, 0)},
    "width_fill_65_ratio": {"type": float, "default": (operator.ge, 0.50)},
    "continuation_col0_ratio": {"type": float, "default": (operator.ge, 0.60)},
    "rewrap_residual": {"type": float, "default": (operator.le, 0.25)},
    # 2D Grid & Spatial Geometry
    "gutter_4_col_count": {"type": int, "default": (operator.ge, 2)},
    "has_deadspace_corridor": {"type": bool, "default": (operator.eq, True)},
    "cell_edge_aligned_count": {"type": int, "default": (operator.ge, 3)},
    "stub_gutter_numeric_count": {"type": int, "default": (operator.ge, 2)},
    # Exhibit Markers
    "exhibit_numbering_count": {"type": int, "default": (operator.ge, 2)},
    "exhibit_phrase_count": {"type": int, "default": (operator.ge, 2)},
}
```

---

## 4. Canonical Feature Taxonomy (Declared Once)

The orthogonal families are defined as immutable tuples of feature names. Rules reuse these canonical names without redefining them:

```python
FEATURE_GROUPS = {
    "ANCHOR": (
        "ends_terminal_punct",
        "starts_capital_or_indent",
    ),
    "GRAMMAR": (
        "possessive_count",
        "relative_clause_count",
        "grammatical_comma_ratio",
        "semicolon_count",
        "article_density",
    ),
    "INTERLINE_WRAP": (
        "soft_wrap_count",
        "connector_wrap_count",
        "width_fill_65_ratio",
        "continuation_col0_ratio",
        "rewrap_residual",
    ),
    "GRID_STRUCTURE": (
        "gutter_4_col_count",
        "has_deadspace_corridor",
        "cell_edge_aligned_count",
        "stub_gutter_numeric_count",
    ),
    "EXHIBIT": (
        "exhibit_numbering_count",
        "exhibit_phrase_count",
    ),
}
```

---

## 5. Declarative Rule Schema & Parameterized Quotas

Rules are declared in a prioritized array. Each rule specifies:
- `action`: `ACTION_UNWRAP`, `ACTION_PRESERVE`, or `ACTION_TAG_AND_PRESERVE`
- `confidence`: Decision confidence score ($0.0 \dots 1.0$)
- `anchor_gate`: (Optional) Single boolean condition required before evaluating groups.
- `quotas`: Mapping of `group_name -> QuotaConstraint`
  - `min_active`: Minimum number of features in that group that must satisfy their predicates.
  - `max_active`: Maximum allowed active features (negative guard).
  - `overrides`: (Optional) Feature-level predicate overrides for that rule.

```python
RULE_SETS = [
    # ------------------------------------------------------------------
    # TIER 1: Fast Structural Gates (Zero-Cost Early Exits)
    # ------------------------------------------------------------------
    {
        "name": "fast_single_line_noop",
        "action": "ACTION_PRESERVE",
        "confidence": 1.0,
        "direct_conditions": [("line_count", operator.le, 1)],
    },
    {
        "name": "protected_table_wrapper",
        "action": "ACTION_PRESERVE",
        "confidence": 1.0,
        "direct_conditions": [("has_table_wrapper_tag", operator.eq, True)],
    },
    {
        "name": "exhibit_index_preserve",
        "action": "ACTION_TAG_AND_PRESERVE",
        "confidence": 0.95,
        "quotas": {
            "EXHIBIT": {"min_active": 1},
        },
    },
    # ------------------------------------------------------------------
    # TIER 2: High-Confidence Cross-Family Synergy (Solves Ambiguous Candidates)
    # ------------------------------------------------------------------
    {
        "name": "cross_family_prose_synergy",
        "action": "ACTION_UNWRAP",
        "confidence": 0.94,
        "anchor_gate": ("ends_terminal_punct", operator.eq, True),
        "quotas": {
            # Relaxed quotas that reinforce each other:
            "GRAMMAR": {
                "min_active": 1,  # Only 1 grammar signal needed!
            },
            "INTERLINE_WRAP": {
                "min_active": 2,  # Only 2 wrap signals needed!
            },
            "GRID_STRUCTURE": {
                "max_active": 0,  # Strict negative guard: no grid structure allowed!
            },
        },
    },
    # ------------------------------------------------------------------
    # TIER 3: Parameterized Stricter Legal / Contract Prose
    # ------------------------------------------------------------------
    {
        "name": "strict_legal_contract_prose",
        "action": "ACTION_UNWRAP",
        "confidence": 0.92,
        "quotas": {
            "GRAMMAR": {
                "min_active": 2,
                # Dynamic Overrides: tighter thresholds without redefining the group!
                "overrides": {
                    "possessive_count": (operator.ge, 2),
                    "grammatical_comma_ratio": (operator.ge, 0.85),
                },
            },
            "INTERLINE_WRAP": {
                "min_active": 1,
            },
        },
    },
    # ------------------------------------------------------------------
    # TIER 4: Bilaterally Indented Prose (Blockquotes & Inset Justified Text)
    # ------------------------------------------------------------------
    {
        "name": "bilateral_inset_prose",
        "action": "ACTION_UNWRAP",
        "confidence": 0.90,
        "anchor_gate": ("ends_terminal_punct", operator.eq, True),
        "quotas": {
            "INTERLINE_WRAP": {
                "min_active": 2,
                "overrides": {
                    # Requires rewrap reconstruction and soft wraps within the inset span
                    "rewrap_residual": (operator.le, 0.20),
                    "soft_wrap_count": (operator.ge, 1),
                },
            },
            "GRID_STRUCTURE": {
                "max_active": 0,  # Prohibits internal gutters
            },
        },
    },
    # ------------------------------------------------------------------
    # TIER 5: Tabular Grid Structure (Data Tables to Preserve)
    # ------------------------------------------------------------------
    {
        "name": "tabular_grid_structure",
        "action": "ACTION_TAG_AND_PRESERVE",
        "confidence": 0.90,
        "quotas": {
            "GRID_STRUCTURE": {
                "min_active": 2,  # At least 2 spatial grid indicators
            },
            "GRAMMAR": {
                "max_active": 0,  # Must NOT have narrative prose grammar
            },
        },
    },
    # ------------------------------------------------------------------
    # TIER 6: Default Safe Fallback
    # ------------------------------------------------------------------
    {
        "name": "unclassified_layout_fallback",
        "action": "ACTION_PRESERVE",
        "confidence": 0.60,
        "direct_conditions": [],
    },
]
```

---

## 6. Execution Pipeline & Short-Circuit Algorithm

The evaluation engine executes rules strictly in sequence, short-circuiting as soon as a condition fails or a quota is reached:

```python
def evaluate_group_quota(ctx: BlockContext, group_name: str, quota_cfg: dict) -> bool:
    features = FEATURE_GROUPS[group_name]
    min_active = quota_cfg.get("min_active", 0)
    max_active = quota_cfg.get("max_active", len(features))
    overrides = quota_cfg.get("overrides", {})

    active_count = 0

    for feat_name in features:
        val = getattr(ctx, feat_name)

        # Determine comparison operator and target threshold
        if feat_name in overrides:
            op, target = overrides[feat_name]
        else:
            op, target = FEATURE_REGISTRY[feat_name]["default"]

        if op(val, target):
            active_count += 1

            # EARLY TERMINATION 1: Negative guard exceeded
            if active_count > max_active:
                return False

            # EARLY TERMINATION 2: Quota satisfied! Stop computing rest of group!
            if active_count >= min_active and max_active >= len(features):
                return True

    return min_active <= active_count <= max_active


def classify_block(
    ctx: BlockContext, rule_sets: list[dict]
) -> tuple[str, float, str, list[str]]:
    for rule in rule_sets:
        # Step 1: Direct Conditions (e.g. line_count <= 1)
        if "direct_conditions" in rule:
            passed = all(
                op(getattr(ctx, f), target)
                for f, op, target in rule["direct_conditions"]
            )
            if passed:
                return rule["action"], rule["confidence"], rule["name"], [rule["name"]]
            continue

        # Step 2: Anchor Gate
        if "anchor_gate" in rule:
            gate_feat, op, target = rule["anchor_gate"]
            if not op(getattr(ctx, gate_feat), target):
                continue  # Short-circuit: skip all groups in this rule!

        # Step 3: Quota Checks across Groups
        quotas_passed = True
        matched_evidence = [rule["name"]]

        for group_name, quota_cfg in rule.get("quotas", {}).items():
            if not evaluate_group_quota(ctx, group_name, quota_cfg):
                quotas_passed = False
                break  # Short-circuit: remaining groups in this rule are not evaluated!
            matched_evidence.append(f"{group_name}_ok")

        if quotas_passed:
            return rule["action"], rule["confidence"], rule["name"], matched_evidence

    return "ACTION_PRESERVE", 0.50, "default_fallback", ["fallback"]
```

---

## 7. Auditability, Provenance & Evidence Manifest

Every decision produces structured provenance that seamlessly populates `SpanDecision.evidence` and audit manifests:

```python
# Sample Emitted SpanDecision for Candidate Block:
SpanDecision(
    action=ACTION_UNWRAP,
    start_line=14,
    end_line=22,
    confidence=0.94,
    evidence=(
        "rule:cross_family_prose_synergy",
        "anchor:terminal_punct=True",
        "grammar:possessive_count=1,grammatical_comma_ratio=0.86",
        "interline_wrap:soft_wrap_count=2,rewrap_residual=0.14",
        "grid_structure:gutter_4_col_count=0",
    ),
    rationale="High-confidence unwrap: verified cross-domain synergy across grammar and layout with zero grid structure.",
)
```

### Review Tool Integration:
- In review manifests, annotators and engineers can inspect the exact scalar values that satisfied each quota.
- If a rule threshold needs tuning, adjusting the `RULE_SETS` array modifies behavior instantly without altering extractor algorithms or regenerating group names.
