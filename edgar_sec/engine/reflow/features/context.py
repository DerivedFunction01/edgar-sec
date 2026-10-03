"""Memoized scalar feature context for one block of ASCII lines.
Every property is a measurement, never a judgement, computed on first access because one pass evaluates the cascade repeatedly. Cover checkbox answers and statement section labels cannot be measured from text and are read off the injected policy.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any

from edgar_sec.domain.forms.common.checkmarks import CHECKMARK_MARK_RE
from edgar_sec.domain.taxonomy.schedules.statutory.exhibits import (
    RE_EXHIBIT_NUMBER,
    RE_EXHIBIT_STATUTORY_PHRASE,
)
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.engine.tables.patterns import COLUMN_DASH_RULE_RE
from edgar_sec.engine.tables.protection.tags import (
    TAGGED_TABLE_CLOSE_RE,
    TAGGED_TABLE_OPEN_RE,
)
from edgar_sec.foundation.text.dates import RE_FULL_DATE
from edgar_sec.foundation.text.grammar import (
    FUNCTION_WORDS,
    RE_ARTICLE,
    RE_POSSESSIVE,
    RE_PROSE_TRANSITION_PHRASE,
    RE_RELATIVE_PRONOUN,
    RE_TRAILING_CONNECTOR,
    RE_VERBAL_PARTICIPLE,
    RE_WORD_TOKEN,
)
from edgar_sec.foundation.text.patterns import (
    RE_COLUMN_GAP,
    RE_DOT_LEADER,
    RE_GRAMMATICAL_COMMA,
    RE_SENTENCE_TERMINAL,
    RE_SEPARATOR_LINE,
    RE_SEPARATOR_RUN,
    RE_STRUCTURAL_SGML,
)

from ..rules.thresholds import FEATURE_REGISTRY
from ..types import ReflowPolicy
from .geometry import (
    _line_gap_starts,
    _numeric_cell_starts,
    _shared_columns,
    is_signature_label_line,
)

_WINDOW_BOUNDS = ((0, 20), (21, 40), (41, 60), (61, 80))
_TARGET_WIDTH = 80
# A blank strip at least this wide, held across every line, is a column corridor.
_CORRIDOR_MIN_WIDTH = 3
_CORRIDOR_SCAN_LIMIT = 75
_CORRIDOR_MIN_BLOCK_WIDTH = 30
_GUTTER_MIN_WIDTH = 4
_GUTTER_POSITION_SLACK = 2
_EDGE_ALIGN_SLACK = 1
_STUB_GUTTER_MIN_WIDTH = 3
_NUMERIC_TAIL_FRACTION = 0.25
_WIDTH_FILL_COLUMNS = 65
_CONTINUATION_COL0 = 4
_EDGE_ALIGN_MIN_LINES = 2
_AUTOCORRELATION_MIN_LINES = 4
_ROW_PERIODICITY_MIN_LINES = 3
_INDENT_ALTERNATION_MIN_LINES = 3
_CORRIDOR_MIN_LINES = 3
_BILATERAL_LEFT_MIN = 4
_BILATERAL_RIGHT_MAX = 74
_EMPTY_RIGHT_MARGIN = 80


class BlockContext:
    """Memoized scalar feature context for an ASCII text block."""

    __slots__ = ("__dict__", "_lines_cache", "_policy", "_raw_text", "_target_width")

    def __init__(
        self,
        text_or_lines: str | tuple[str, ...] | list[str],
        policy: ReflowPolicy | None = None,
        target_width: int = 80,
    ) -> None:
        if isinstance(text_or_lines, str):
            self._raw_text = text_or_lines
            self._lines_cache: tuple[str, ...] | None = None
        else:
            self._lines_cache = tuple(text_or_lines)
            self._raw_text = "\n".join(text_or_lines)
        self._policy = policy
        self._target_width = target_width

    @property
    def target_width(self) -> int:
        return self._target_width

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

    @cached_property
    def line_count(self) -> int:
        return len(self.non_blank_lines)

    @property
    def non_blank(self) -> int:
        """Alias for line_count, so the compact geometry record and this one agree."""
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
        predicate = (
            self._policy.is_checkbox_answer_line if self._policy is not None else None
        )
        if CHECKMARK_MARK_RE.search(self._raw_text):
            return True
        if predicate is None:
            return False
        return any(predicate(line) for line in self.non_blank_lines)

    @cached_property
    def is_financial_bridge(self) -> bool:
        predicate = (
            self._policy.is_table_bridge_line if self._policy is not None else None
        )
        if predicate is None:
            return False
        return any(predicate(line) for line in self.non_blank_lines)

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
        """Alias for has_separator_run, so the compact geometry record and this one agree."""
        return self.has_separator_run

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
        if len(lines) < _EDGE_ALIGN_MIN_LINES:
            return 0
        gap_cols: dict[int, int] = {}
        for line in lines:
            content_start = len(line) - len(line.lstrip())
            stripped_end = len(line.rstrip())
            seen_line_cols: set[int] = set()
            for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
                if match.start() < content_start:
                    continue
                if (match.end() - match.start()) >= _GUTTER_MIN_WIDTH:
                    col = match.start()
                    bucket = next(
                        (
                            c
                            for c in seen_line_cols
                            if abs(c - col) <= _GUTTER_POSITION_SLACK
                        ),
                        col,
                    )
                    seen_line_cols.add(bucket)
            for c in seen_line_cols:
                bucket = next(
                    (b for b in gap_cols if abs(b - c) <= _GUTTER_POSITION_SLACK), c
                )
                gap_cols[bucket] = gap_cols.get(bucket, 0) + 1
        return max(gap_cols.values()) if gap_cols else 0

    @cached_property
    def has_deadspace_corridor(self) -> bool:
        """H-GEO-14: Persistent >= 3-col blank strip across all lines."""
        lines = self.non_blank_lines
        if len(lines) < _CORRIDOR_MIN_LINES:
            return False
        max_len = max(len(line) for line in lines)
        if max_len < _CORRIDOR_MIN_BLOCK_WIDTH:
            return False
        min_start = max(len(line) - len(line.lstrip()) for line in lines)
        scan_limit = min(max_len, _CORRIDOR_SCAN_LIMIT)
        blank_cols: list[bool] = [True] * scan_limit
        for line in lines:
            for col, ch in enumerate(line[:scan_limit]):
                if ch not in " \t":
                    blank_cols[col] = False
        run = 0
        for col in range(min_start, scan_limit):
            if blank_cols[col]:
                run += 1
                if run >= _CORRIDOR_MIN_WIDTH:
                    return True
            else:
                run = 0
        return False

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
        return num_ends >= 2 and (num_ends / (len(lines) - 1)) >= _NUMERIC_TAIL_FRACTION

    @cached_property
    def _window_bounds(self) -> tuple[tuple[int, int], ...]:
        w = self._target_width
        if w >= 75:
            return _WINDOW_BOUNDS
        q = w // 4
        return ((0, q), (q, 2 * q), (2 * q, 3 * q), (3 * q, w))

    @cached_property
    def _window_densities(
        self,
    ) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
        alpha_dens: list[float] = []
        numeric_dens: list[float] = []
        lines = self.non_blank_lines
        if not lines:
            return ((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0))
        for lo, hi in self._window_bounds:
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
        thresh = (
            int(self._target_width * 0.80)
            if self._target_width < 75
            else _WIDTH_FILL_COLUMNS
        )
        filled = sum(1 for line in lines if len(line.rstrip()) >= thresh)
        return filled / len(lines)

    @cached_property
    def continuation_col0_ratio(self) -> float:
        lines = self.non_blank_lines
        if len(lines) < 2:
            return 0.0
        col0_continuations = 0
        for line in lines[1:]:
            leading_ws = len(line) - len(line.lstrip())
            if leading_ws <= _CONTINUATION_COL0:
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
        rewrapped_lengths: list[int] = []
        current_len = 0
        w = self._target_width
        for token in tokens:
            t_len = len(token)
            if current_len == 0:
                current_len = t_len
            elif current_len + 1 + t_len <= w:
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
        return diff / (min_len * w)

    @cached_property
    def cell_edge_aligned_count(self) -> int:
        """Count repeated aligned numeric right edges (H-GEO-18)."""
        lines = self.non_blank_lines
        if len(lines) < _EDGE_ALIGN_MIN_LINES:
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
                    bucket = next(
                        (b for b in right_edges if abs(b - edge) <= _EDGE_ALIGN_SLACK),
                        edge,
                    )
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
                if len(match.group()) >= _STUB_GUTTER_MIN_WIDTH:
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
        if len(lines) < _ROW_PERIODICITY_MIN_LINES:
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
        if len(lines) < _INDENT_ALTERNATION_MIN_LINES:
            return 0.0
        indents = [len(line) - len(line.lstrip()) for line in lines]
        alternations = 0
        for i in range(len(indents) - 1):
            if (
                indents[i] == 0
                and indents[i + 1] >= _GUTTER_MIN_WIDTH
                or indents[i] >= _GUTTER_MIN_WIDTH
                and indents[i + 1] == 0
            ):
                alternations += 1
        return alternations / (len(indents) - 1)

    @cached_property
    def row_shape_autocorrelation(self) -> float:
        """Autocorrelation of numeric cell counts across rows (H-GEO-16)."""
        lines = self.non_blank_lines
        if len(lines) < _AUTOCORRELATION_MIN_LINES:
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

    @cached_property
    def _margins(self) -> tuple[int, int]:
        lines = self.non_blank_lines
        if not lines:
            return (0, _EMPTY_RIGHT_MARGIN)
        lefts = [len(line) - len(line.lstrip()) for line in lines]
        rights = [len(line.rstrip()) for line in lines]
        return (min(lefts), max(rights))

    @cached_property
    def is_bilateral_inset(self) -> bool:
        l_margin, r_margin = self._margins
        r_max = (
            self._target_width - 6 if self._target_width < 75 else _BILATERAL_RIGHT_MAX
        )
        return l_margin >= _BILATERAL_LEFT_MIN and r_margin <= r_max

    @cached_property
    def inset_measure_width(self) -> int:
        l_margin, r_margin = self._margins
        return max(0, r_margin - l_margin)

    @cached_property
    def is_width_overflow(self) -> bool:
        if self._target_width >= 75:
            return False
        lines = self.non_blank_lines
        if not lines:
            return False
        max_len = max(len(l.rstrip()) for l in lines)
        return max_len >= self._target_width + 10

    @cached_property
    def is_justified_prose(self) -> bool:
        lines = self.non_blank_lines
        if len(lines) < 2:
            return False
        w = self._target_width
        margin_hits = sum(1 for l in lines[:-1] if abs(len(l.rstrip()) - w) <= 1)
        is_justified_margins = (margin_hits / (len(lines) - 1)) >= 0.65
        if not is_justified_margins:
            return False
        if self.alpha_density < 0.55 or not self.any_lowercase:
            return False
        if (
            self.has_separator
            or self.has_structural
            or self.has_tab
            or self.has_signature
        ):
            return False
        return self.gutter_4_col_count < max(3, len(lines) // 10)

    @cached_property
    def exhibit_numbering_count(self) -> int:
        return len(RE_EXHIBIT_NUMBER.findall(self._raw_text))

    @cached_property
    def exhibit_phrase_count(self) -> int:
        return len(RE_EXHIBIT_STATUTORY_PHRASE.findall(self._raw_text))

    def to_feature_dict(self) -> dict[str, Any]:
        """Return every registered feature keyed by name, in registry order."""
        return {name: getattr(self, name) for name in FEATURE_REGISTRY}

    def to_feature_floats(self) -> tuple[float, ...]:
        """Return every registered feature in canonical order, as plain floats.
        A tuple, not an array: an array would put numpy in the import graph of every normalizing process.
        """
        values: list[float] = []
        for name, spec in FEATURE_REGISTRY.items():
            value = getattr(self, name)
            if spec.scalar_type is bool:
                values.append(1.0 if value else 0.0)
            else:
                values.append(float(value))
        return tuple(values)


__all__ = ["BlockContext"]
