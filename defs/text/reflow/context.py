"""Production Lossless BlockContext with cached scalar feature properties.

This module composes domain-neutral primitives from defs/text, defs/tables,
and defs/taxonomy to extract scalar properties per text block. Properties are
memoized using @functools.cached_property for lazy, on-demand evaluation.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any

import numpy as np

from defs.sec_forms.cover.reflow import is_checkbox_answer_line
from defs.tables.numeric_cells import is_numeric_cell
from defs.tables.patterns import COLUMN_DASH_RULE_RE
from defs.tables.protection import TAGGED_TABLE_CLOSE_RE, TAGGED_TABLE_OPEN_RE
from defs.taxonomy.components.financials.reflow import is_financial_table_bridge_line
from defs.taxonomy.components.schedules.exhibit_index import (
    RE_EXHIBIT_NUMBER,
    RE_EXHIBIT_STATUTORY_PHRASE,
)
from defs.text.checkmarks import CHECKMARK_MARK_RE
from defs.text.dates import RE_FULL_DATE
from defs.text.grammar import (
    FUNCTION_WORDS,
    RE_ARTICLE,
    RE_POSSESSIVE,
    RE_PROSE_TRANSITION_PHRASE,
    RE_RELATIVE_PRONOUN,
    RE_TRAILING_CONNECTOR,
    RE_VERBAL_PARTICIPLE,
    RE_WORD_TOKEN,
)
from defs.text.patterns import (
    RE_COLUMN_GAP,
    RE_DOT_LEADER,
    RE_GRAMMATICAL_COMMA,
    RE_SENTENCE_TERMINAL,
    RE_SEPARATOR_LINE,
    RE_SEPARATOR_RUN,
    RE_STRUCTURAL_SGML,
)
from defs.text.reflow.features import (
    _line_gap_starts,
    _numeric_cell_starts,
    _shared_columns,
)
from defs.text.reflow.registry import FEATURE_REGISTRY
from defs.text.signatures import is_signature_label_line


class BlockContext:
    """Memoized scalar feature context for an ASCII text block."""

    __slots__ = ("__dict__", "_lines_cache", "_raw_text")

    def __init__(self, text_or_lines: str | tuple[str, ...] | list[str]) -> None:
        if isinstance(text_or_lines, str):
            self._raw_text = text_or_lines
            self._lines_cache: tuple[str, ...] | None = None
        else:
            self._lines_cache = tuple(text_or_lines)
            self._raw_text = "\n".join(text_or_lines)

    @property
    def raw_text(self) -> str:
        return self._raw_text

    @cached_property
    def raw_lines(self) -> tuple[str, ...]:
        if self._lines_cache is not None:
            return self._lines_cache
        return tuple(self._raw_text.splitlines())

    @cached_property
    def non_blank_lines(self) -> tuple[str, ...]:
        return tuple(line for line in self.raw_lines if line.strip())

    # 1. Structural, Boundary & Anchors
    @cached_property
    def line_count(self) -> int:
        return len(self.non_blank_lines)

    @property
    def non_blank(self) -> int:
        """Alias for line_count for backward compatibility with _Features."""
        return self.line_count

    @cached_property
    def ends_terminal_punct(self) -> bool:
        if not self.non_blank_lines:
            return False
        return bool(RE_SENTENCE_TERMINAL.search(self.non_blank_lines[-1]))

    @cached_property
    def starts_capital_or_indent(self) -> bool:
        if not self.non_blank_lines:
            return False
        first = self.non_blank_lines[0]
        leading_ws = len(first) - len(first.lstrip())
        first_char = first.strip()[0] if first.strip() else ""
        return leading_ws >= 2 or first_char.isupper()

    @cached_property
    def has_table_wrapper_tag(self) -> bool:
        if "<" not in self._raw_text:
            return False
        return bool(
            TAGGED_TABLE_OPEN_RE.search(self._raw_text)
            or TAGGED_TABLE_CLOSE_RE.search(self._raw_text)
        )

    @cached_property
    def has_checkbox(self) -> bool:
        return bool(
            CHECKMARK_MARK_RE.search(self._raw_text)
            or any(is_checkbox_answer_line(l) for l in self.non_blank_lines)
        )

    @cached_property
    def is_financial_bridge(self) -> bool:
        return any(is_financial_table_bridge_line(l) for l in self.non_blank_lines)

    @cached_property
    def column_underline_count(self) -> int:
        return sum(
            1
            for l in self.non_blank_lines
            if COLUMN_DASH_RULE_RE.match(l) or RE_SEPARATOR_LINE.match(l.strip())
        )

    @cached_property
    def has_dot_leader(self) -> bool:
        if "." not in self._raw_text:
            return False
        return bool(RE_DOT_LEADER.search(self._raw_text))

    @cached_property
    def has_structural(self) -> bool:
        if "<" not in self._raw_text:
            return False
        return any(RE_STRUCTURAL_SGML.search(l.strip()) for l in self.non_blank_lines)

    @cached_property
    def has_signature(self) -> bool:
        return any(is_signature_label_line(l) for l in self.non_blank_lines)

    @cached_property
    def has_tab(self) -> bool:
        return any("\t" in l.lstrip() for l in self.non_blank_lines)

    @cached_property
    def has_separator_run(self) -> bool:
        return bool(
            RE_SEPARATOR_RUN.search(self._raw_text)
            or any(RE_SEPARATOR_LINE.fullmatch(l.strip()) for l in self.non_blank_lines)
        )

    @property
    def has_separator(self) -> bool:
        """Alias for has_separator_run for backward compatibility with _Features."""
        return self.has_separator_run

    # 2. 2D Layout & Column Spacing Geometry
    @cached_property
    def gap_start_rows(self) -> tuple[tuple[int, ...], ...]:
        rows: list[tuple[int, ...]] = []
        for line in self.non_blank_lines:
            gaps = _line_gap_starts(line)
            if gaps:
                rows.append(gaps)
        return tuple(rows)

    @cached_property
    def numeric_cell_rows(self) -> tuple[tuple[int, ...], ...]:
        rows: list[tuple[int, ...]] = []
        for line in self.non_blank_lines:
            cells = _numeric_cell_starts(line)
            if cells:
                rows.append(cells)
        return tuple(rows)

    @cached_property
    def shared_numeric_columns(self) -> int:
        return _shared_columns(self.numeric_cell_rows, min_rows=3, tolerance=1)

    @cached_property
    def shared_gaps_count(self) -> int:
        return _shared_columns(self.gap_start_rows, min_rows=3, tolerance=1)

    @cached_property
    def numeric_cell_row_count(self) -> int:
        return len(self.numeric_cell_rows)

    @cached_property
    def numeric_row_density(self) -> float:
        return len(self.numeric_cell_rows) / max(self.non_blank, 1)

    @cached_property
    def max_gap(self) -> int:
        max_g = 0
        for line in self.non_blank_lines:
            content_start = len(line) - len(line.lstrip())
            for match in RE_COLUMN_GAP.finditer(line[: len(line.rstrip())]):
                if match.start() >= content_start:
                    max_g = max(max_g, len(match.group()))
        return max_g

    @cached_property
    def gutter_4_col_count(self) -> int:
        """Max recurrence of any >= 4-space gap position across lines."""
        lines = self.non_blank_lines
        if len(lines) < 2:
            return 0
        gap_cols: dict[int, int] = {}
        for line in lines:
            content_start = len(line) - len(line.lstrip())
            stripped_end = len(line.rstrip())
            seen_line_cols: set[int] = set()
            for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
                if match.start() < content_start:
                    continue
                if (match.end() - match.start()) >= 4:
                    col = match.start()
                    bucket = next((c for c in seen_line_cols if abs(c - col) <= 2), col)
                    seen_line_cols.add(bucket)
            for c in seen_line_cols:
                bucket = next((b for b in gap_cols if abs(b - c) <= 2), c)
                gap_cols[bucket] = gap_cols.get(bucket, 0) + 1
        return max(gap_cols.values()) if gap_cols else 0

    @cached_property
    def has_deadspace_corridor(self) -> bool:
        """H-GEO-14: Persistent >= 3-col blank strip across all lines."""
        lines = self.non_blank_lines
        if len(lines) < 3:
            return False
        max_len = max(len(line) for line in lines)
        if max_len < 30:
            return False
        min_start = max(len(line) - len(line.lstrip()) for line in lines)
        scan_limit = min(max_len, 75)
        blank_cols: list[bool] = [True] * scan_limit
        for line in lines:
            for col, ch in enumerate(line[:scan_limit]):
                if ch not in " \t":
                    blank_cols[col] = False
        run = 0
        for col in range(min_start, scan_limit):
            if blank_cols[col]:
                run += 1
                if run >= 3:
                    return True
            else:
                run = 0
        return False

    # 3. Macro Content Density & Grammar
    @cached_property
    def _char_counts(self) -> tuple[int, int, int]:
        alpha = numeric = total = 0
        for line in self.non_blank_lines:
            stripped = line.strip()
            total += len(stripped)
            for c in stripped:
                if c.isalpha():
                    alpha += 1
                elif c.isdigit():
                    numeric += 1
        return (alpha, numeric, total)

    @cached_property
    def alpha_density(self) -> float:
        alpha, _, total = self._char_counts
        return alpha / total if total else 0.0

    @cached_property
    def any_lowercase(self) -> bool:
        return any(c.islower() for line in self.non_blank_lines for c in line)

    @cached_property
    def non_final_ends_numeric(self) -> bool:
        lines = self.non_blank_lines
        if len(lines) < 2:
            return False
        num_ends = sum(
            1
            for l in lines[:-1]
            if (s := l.rstrip()) and (s[-1].isdigit() or s[-1] in ")]%")
        )
        return num_ends >= 2 and (num_ends / (len(lines) - 1)) >= 0.25

    @cached_property
    def _window_densities(
        self,
    ) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
        w_bounds = [(0, 20), (21, 40), (41, 60), (61, 80)]
        alpha_dens: list[float] = []
        numeric_dens: list[float] = []
        lines = self.non_blank_lines
        if not lines:
            return ((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0))
        for lo, hi in w_bounds:
            alphas = nums = chars = 0
            for line in lines:
                slice_str = line[lo:hi] if len(line) > lo else ""
                chars += len(slice_str.strip())
                alphas += sum(1 for c in slice_str if c.isalpha())
                nums += sum(1 for c in slice_str if c.isdigit())
            alpha_dens.append(alphas / chars if chars else 0.0)
            numeric_dens.append(nums / chars if chars else 0.0)
        return (tuple(alpha_dens), tuple(numeric_dens))  # type: ignore[return-value]

    @cached_property
    def alpha_density_w1(self) -> float:
        return self._window_densities[0][0]

    @cached_property
    def alpha_density_w2(self) -> float:
        return self._window_densities[0][1]

    @cached_property
    def alpha_density_w3(self) -> float:
        return self._window_densities[0][2]

    @cached_property
    def alpha_density_w4(self) -> float:
        return self._window_densities[0][3]

    @cached_property
    def numeric_density_w1(self) -> float:
        return self._window_densities[1][0]

    @cached_property
    def numeric_density_w2(self) -> float:
        return self._window_densities[1][1]

    @cached_property
    def numeric_density_w3(self) -> float:
        return self._window_densities[1][2]

    @cached_property
    def numeric_density_w4(self) -> float:
        return self._window_densities[1][3]

    @cached_property
    def possessive_count(self) -> int:
        return len(RE_POSSESSIVE.findall(self._raw_text))

    @cached_property
    def relative_clause_count(self) -> int:
        return len(RE_RELATIVE_PRONOUN.findall(self._raw_text))

    @cached_property
    def semicolon_count(self) -> int:
        return self._raw_text.count(";")

    @cached_property
    def grammatical_comma_ratio(self) -> float:
        all_commas = self._raw_text.count(",")
        if not all_commas:
            return 0.0
        prose_commas = len(RE_GRAMMATICAL_COMMA.findall(self._raw_text))
        return prose_commas / all_commas

    @cached_property
    def article_density(self) -> float:
        count = len(RE_ARTICLE.findall(self._raw_text))
        return count / max(self.line_count, 1)

    @cached_property
    def function_word_ratio(self) -> float:
        total_words = 0
        fn_count = 0
        for m in RE_WORD_TOKEN.finditer(self._raw_text):
            tok = m.group(0)
            if tok[0].isalpha():
                total_words += 1
                if tok.lower() in FUNCTION_WORDS:
                    fn_count += 1
        return fn_count / total_words if total_words else 0.0

    @cached_property
    def verbal_participle_count(self) -> int:
        return len(RE_VERBAL_PARTICIPLE.findall(self._raw_text))

    @cached_property
    def prose_phrase_right_half_count(self) -> int:
        count = 0
        for line in self.non_blank_lines:
            mid = len(line) // 2
            right_half = line[mid:]
            if RE_PROSE_TRANSITION_PHRASE.search(right_half):
                count += 1
        return count

    @cached_property
    def narrative_date_count(self) -> int:
        if self._char_counts[1] == 0:
            return 0
        return len(RE_FULL_DATE.findall(self._raw_text))

    # 4. Micro Interline Wrapping & Syntax
    @cached_property
    def soft_wrap_count(self) -> int:
        lines = self.non_blank_lines
        if len(lines) < 2:
            return 0
        count = 0
        for i in range(len(lines) - 1):
            curr_stripped = lines[i].rstrip()
            next_stripped = lines[i + 1].lstrip()
            if not curr_stripped or not next_stripped:
                continue
            last_char = curr_stripped[-1]
            first_char = next_stripped[0]
            if (last_char.isalpha() or last_char == ",") and first_char.islower():
                count += 1
        return count

    @cached_property
    def soft_wrap_ratio(self) -> float:
        lines = self.non_blank_lines
        if len(lines) < 2:
            return 0.0
        return self.soft_wrap_count / (len(lines) - 1)

    @cached_property
    def connector_wrap_count(self) -> int:
        count = 0
        for line in self.non_blank_lines[:-1]:
            stripped = line.rstrip()
            words = stripped.rsplit(None, 1)
            if words and RE_TRAILING_CONNECTOR.search(words[-1]):
                count += 1
        return count

    @cached_property
    def width_fill_65_ratio(self) -> float:
        lines = self.non_blank_lines
        if not lines:
            return 0.0
        filled = sum(1 for line in lines if len(line.rstrip()) >= 65)
        return filled / len(lines)

    @cached_property
    def continuation_col0_ratio(self) -> float:
        lines = self.non_blank_lines
        if len(lines) < 2:
            return 0.0
        col0_continuations = 0
        for line in lines[1:]:
            leading_ws = len(line) - len(line.lstrip())
            if leading_ws <= 4:
                col0_continuations += 1
        return col0_continuations / (len(lines) - 1)

    @cached_property
    def rewrap_residual(self) -> float:
        """H-GEO-13: Measure greedy line-wrap distortion residual."""
        lines = self.non_blank_lines
        if len(lines) < 3:
            return 0.0
        tokens: list[str] = []
        for line in lines:
            tokens.extend(line.split())
        if not tokens:
            return 0.0
        target_width = 80
        rewrapped_lengths: list[int] = []
        current_len = 0
        for token in tokens:
            t_len = len(token)
            if current_len == 0:
                current_len = t_len
            elif current_len + 1 + t_len <= target_width:
                current_len += 1 + t_len
            else:
                rewrapped_lengths.append(current_len)
                current_len = t_len
        if current_len > 0:
            rewrapped_lengths.append(current_len)
        orig_lengths = [len(line.rstrip()) for line in lines]
        min_len = min(len(orig_lengths), len(rewrapped_lengths))
        if min_len == 0:
            return 0.0
        diff = sum(abs(orig_lengths[i] - rewrapped_lengths[i]) for i in range(min_len))
        return diff / (min_len * target_width)

    # 5. Row-to-Row Relational Dynamics
    @cached_property
    def cell_edge_aligned_count(self) -> int:
        """Count repeated aligned numeric right edges (H-GEO-18)."""
        lines = self.non_blank_lines
        if len(lines) < 2:
            return 0
        right_edges: dict[int, int] = {}
        for line in lines:
            tokens = line.split()
            cursor = 0
            for token in tokens:
                pos = line.find(token, cursor)
                cursor = pos + len(token)
                if is_numeric_cell(token):
                    edge = cursor
                    bucket = next((b for b in right_edges if abs(b - edge) <= 1), edge)
                    right_edges[bucket] = right_edges.get(bucket, 0) + 1
        return max(right_edges.values()) if right_edges else 0

    @cached_property
    def stub_gutter_numeric_count(self) -> int:
        """Lines with text stub -> gutter -> numeric cell (H-GEO-17)."""
        lines = self.non_blank_lines
        count = 0
        for line in lines:
            content_start = len(line) - len(line.lstrip())
            stripped_end = len(line.rstrip())
            for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
                if match.start() < content_start:
                    continue
                if len(match.group()) >= 3:
                    stub = line[: match.start()].strip()
                    tail = line[match.end() :].strip().split()
                    if (
                        stub
                        and any(c.isalpha() for c in stub)
                        and tail
                        and is_numeric_cell(tail[0])
                    ):
                        count += 1
                        break
        return count

    @cached_property
    def row_template_periodicity(self) -> float:
        """Normalized row shape match ratio (H-GEO-11)."""
        lines = self.non_blank_lines
        if len(lines) < 3:
            return 0.0
        shapes: list[str] = []
        for line in lines:
            tokens = line.split()
            shape = "".join("N" if is_numeric_cell(t) else "T" for t in tokens)
            shapes.append(shape)
        if not shapes:
            return 0.0
        most_common = max(shapes, key=shapes.count)
        return shapes.count(most_common) / len(shapes)

    @cached_property
    def indent_alternation_ratio(self) -> float:
        """Ratio of alternating indent wraps across lines (H-GEO-12)."""
        lines = self.non_blank_lines
        if len(lines) < 3:
            return 0.0
        indents = [len(line) - len(line.lstrip()) for line in lines]
        alternations = 0
        for i in range(len(indents) - 1):
            if (
                indents[i] == 0
                and indents[i + 1] >= 4
                or indents[i] >= 4
                and indents[i + 1] == 0
            ):
                alternations += 1
        return alternations / (len(indents) - 1)

    @cached_property
    def row_shape_autocorrelation(self) -> float:
        """Autocorrelation of numeric cell counts across rows (H-GEO-16)."""
        lines = self.non_blank_lines
        if len(lines) < 4:
            return 0.0
        counts = [sum(1 for t in line.split() if is_numeric_cell(t)) for line in lines]
        if len(set(counts)) <= 1:
            return 1.0 if counts[0] > 0 else 0.0
        n = len(counts)
        mean = sum(counts) / n
        denom = sum((c - mean) ** 2 for c in counts)
        if denom == 0:
            return 0.0
        lag1_num = sum(
            (counts[i] - mean) * (counts[i + 1] - mean) for i in range(n - 1)
        )
        return float(lag1_num / denom)

    # 6. Bilateral Inset Geometry
    @cached_property
    def _margins(self) -> tuple[int, int]:
        lines = self.non_blank_lines
        if not lines:
            return (0, 80)
        lefts = [len(line) - len(line.lstrip()) for line in lines]
        rights = [len(line.rstrip()) for line in lines]
        return (min(lefts), max(rights))

    @cached_property
    def is_bilateral_inset(self) -> bool:
        l_margin, r_margin = self._margins
        return l_margin >= 4 and r_margin <= 74

    @cached_property
    def inset_measure_width(self) -> int:
        l_margin, r_margin = self._margins
        return max(0, r_margin - l_margin)

    # -------------------------------------------------------------------------
    # 7. Exhibit Index Markers
    # -------------------------------------------------------------------------

    @cached_property
    def exhibit_numbering_count(self) -> int:
        return len(RE_EXHIBIT_NUMBER.findall(self._raw_text))

    @cached_property
    def exhibit_phrase_count(self) -> int:
        return len(RE_EXHIBIT_STATUTORY_PHRASE.findall(self._raw_text))

    # -------------------------------------------------------------------------
    # Vector Serialization
    # -------------------------------------------------------------------------

    def to_feature_dict(self) -> dict[str, Any]:
        """Return dict of all registered scalar features."""
        return {name: getattr(self, name) for name in FEATURE_REGISTRY}

    def to_feature_vector(self) -> np.ndarray:
        """Return 1D float array of all registered features in canonical order."""
        vec = []
        for name, spec in FEATURE_REGISTRY.items():
            val = getattr(self, name)
            if spec.scalar_type is bool:
                vec.append(1.0 if val else 0.0)
            else:
                vec.append(float(val))
        return np.array(vec, dtype=float)


__all__ = [
    "BlockContext",
]
