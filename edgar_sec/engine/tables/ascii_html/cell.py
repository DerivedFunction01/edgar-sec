"""Cell styling and cell text: CSS normalization, whitespace, wrapping, padding."""

from __future__ import annotations

import re
import textwrap
from functools import lru_cache
from typing import Any

from edgar_sec.foundation.text.normalize import NORMALIZE_TO_SPACE, STRIP_ZERO_WIDTH
from edgar_sec.foundation.text.tokens import BULLET_MARKER_RE

from ..patterns import HIDDEN_ELEMENT_STYLE_RE
from .model import BorderStyle, CellStyle, HorizontalAlign, VerticalAlign

_DECL_RE = re.compile(r"([a-zA-Z\-]+)\s*:\s*([^;]+)")


@lru_cache(maxsize=1024)
def _parse_css_declarations(style_str: str) -> tuple[tuple[str, str], ...]:
    """Parse and normalize CSS property: value pairs from a style attribute string."""
    return tuple(
        (prop.strip().lower(), val.strip()) for prop, val in _DECL_RE.findall(style_str)
    )


_UNIT_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%]*)$")
_BORDER_STYLES = {
    "none": BorderStyle.NONE,
    "hidden": BorderStyle.NONE,
    "solid": BorderStyle.SOLID,
    "double": BorderStyle.DOUBLE,
    "dashed": BorderStyle.DASHED,
    "dotted": BorderStyle.DOTTED,
}
# Cell boundary tags — traversal must not descend into these when inheriting child styles
_CELL_BOUNDARY_TAGS = frozenset(("table", "tr", "td", "th"))
# Typography tags for inline bold/italic detection (replaces node.find() CSS queries)
_BOLD_TAGS = frozenset(("b", "strong"))
_ITALIC_TAGS = frozenset(("i", "em"))


def _iter_cell_descendants(node: Any):
    """Yield descendant raw selectolax nodes without crossing into nested cell/table boundaries.
    lexbor re-parents unclosed ``<td>``/``<th>`` siblings as children of the preceding cell.
    """
    raw_node = getattr(node, "raw_node", node)
    stack = [c for c in raw_node.iter(include_text=False) if c.tag]
    while stack:
        child = stack.pop()
        yield child
        tag = (child.tag or "").lower()
        if tag not in _CELL_BOUNDARY_TAGS:
            stack.extend(c for c in child.iter(include_text=False) if c.tag)


@lru_cache(maxsize=2048)
def parse_dimension_px(value: str | None) -> tuple[float | None, str, bool]:
    """Parse a CSS or HTML dimension string into pixels, unit, and percent flag.
    A unitless value is treated as px, per HTML width/height; results are memoized.
    """
    if not value:
        return None, "px", False
    raw = value.strip().lower()
    if not raw or raw == "auto":
        return None, "px", False

    m = _UNIT_RE.match(raw)
    if not m:
        return None, "px", False

    num_str, unit = m.groups()
    try:
        num = float(num_str)
    except ValueError:
        return None, "px", False

    if unit == "%":
        return num, "%", True
    elif unit == "pt":
        return num * (96.0 / 72.0), "px", False
    elif unit == "in":
        return num * 96.0, "px", False
    elif unit in ("em", "rem"):
        return num * 16.0, "px", False
    elif unit == "cm":
        return num * (96.0 / 2.54), "px", False
    elif unit == "mm":
        return num * (96.0 / 25.4), "px", False
    else:
        return num, "px", False


@lru_cache(maxsize=1024)
def _parse_border_shorthand(
    val: str,
) -> tuple[float, BorderStyle, str | None]:
    """Parse a CSS border shorthand like '1px solid #000' or 'none'."""
    val = val.strip().lower()
    if not val or val == "none" or val == "0" or val == "0px":
        return 0.0, BorderStyle.NONE, None

    tokens = val.split()
    width = 1.0
    style = BorderStyle.SOLID
    color: str | None = None

    for tok in tokens:
        if tok in _BORDER_STYLES:
            style = _BORDER_STYLES[tok]
            if style == BorderStyle.NONE:
                width = 0.0
        elif tok.startswith(("#", "rgb")) or tok.isalpha():
            color = tok
        else:
            w, _, is_pct = parse_dimension_px(tok)
            if w is not None and not is_pct:
                width = w

    return width, style, color


@lru_cache(maxsize=1024)
def _parse_box_4values(
    val: str,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Parse a 1-to-4 value CSS box dimension (top, right, bottom, left) into px."""
    tokens = val.split()
    if not tokens:
        return None, None, None, None

    parsed: list[float | None] = []
    for tok in tokens:
        px_val, _, _ = parse_dimension_px(tok)
        parsed.append(px_val)

    if len(parsed) == 1:
        v = parsed[0]
        return v, v, v, v
    elif len(parsed) == 2:
        top_bot, right_left = parsed[0], parsed[1]
        return top_bot, right_left, top_bot, right_left
    elif len(parsed) == 3:
        top, right_left, bot = parsed[0], parsed[1], parsed[2]
        return top, right_left, bot, right_left
    elif len(parsed) >= 4:
        return parsed[0], parsed[1], parsed[2], parsed[3]
    return None, None, None, None


@lru_cache(maxsize=256)
def _parse_horizontal_align(val: str | None) -> HorizontalAlign:
    if not val:
        return HorizontalAlign.AUTO
    norm = val.strip().lower()
    if norm in ("left", "start"):
        return HorizontalAlign.LEFT
    elif norm in ("right", "end"):
        return HorizontalAlign.RIGHT
    elif norm == "center":
        return HorizontalAlign.CENTER
    elif norm == "justify":
        return HorizontalAlign.JUSTIFY
    return HorizontalAlign.AUTO


@lru_cache(maxsize=256)
def _parse_vertical_align(val: str | None) -> VerticalAlign:
    if not val:
        return VerticalAlign.AUTO
    norm = val.strip().lower()
    if norm in ("top", "text-top"):
        return VerticalAlign.TOP
    elif norm in ("bottom", "text-bottom"):
        return VerticalAlign.BOTTOM
    elif norm in ("middle", "center"):
        return VerticalAlign.MIDDLE
    elif norm == "baseline":
        return VerticalAlign.BASELINE
    return VerticalAlign.AUTO


_DEFAULT_CELL_STYLE = CellStyle()


def parse_style_and_attributes(node: Any) -> CellStyle:
    """Extract and normalize all inline CSS properties and HTML attributes into a CellStyle."""
    raw_node = getattr(node, "raw_node", node)
    raw_attrs = raw_node.attributes or {}
    if not raw_attrs:
        return _DEFAULT_CELL_STYLE
    attrs = {
        str(k).lower(): str(v)
        for k, v in raw_attrs.items()
        if k is not None and v is not None
    }

    w_attr, w_unit, is_pct = parse_dimension_px(attrs.get("width"))
    h_attr, _, _ = parse_dimension_px(attrs.get("height"))
    h_align = _parse_horizontal_align(attrs.get("align"))
    v_align = _parse_vertical_align(attrs.get("valign"))
    bg_color = attrs.get("bgcolor")
    is_nowrap = "nowrap" in attrs

    b_attr_val = attrs.get("border")
    b_top_w, b_top_s, b_top_c = 0.0, BorderStyle.NONE, None
    b_bot_w, b_bot_s, b_bot_c = 0.0, BorderStyle.NONE, None
    b_left_w, b_left_s, b_left_c = 0.0, BorderStyle.NONE, None
    b_right_w, b_right_s, b_right_c = 0.0, BorderStyle.NONE, None

    if b_attr_val is not None:
        bw, _, _ = parse_dimension_px(b_attr_val)
        if bw and bw > 0:
            b_top_w = b_bot_w = b_left_w = b_right_w = bw
            b_top_s = b_bot_s = b_left_s = b_right_s = BorderStyle.SOLID

    pad_left = pad_right = pad_top = pad_bottom = 0.0
    cellpadding = attrs.get("cellpadding")
    if cellpadding is not None:
        cp_val, _, _ = parse_dimension_px(cellpadding)
        if cp_val:
            pad_left = pad_right = pad_top = pad_bottom = cp_val

    style_str = attrs.get("style", "")
    is_hidden = bool(
        attrs.get("hidden") is not None
        or (style_str and HIDDEN_ELEMENT_STYLE_RE.search(style_str))
    )

    font_weight = "normal"
    font_style = "normal"
    font_size: float | None = None
    white_space = "normal"
    margin_left = 0.0
    margin_right = 0.0
    text_indent = 0.0

    if style_str:
        for prop, val in _parse_css_declarations(style_str):
            if (
                prop == "display"
                and val.lower() == "none"
                or prop == "visibility"
                and val.lower() == "hidden"
            ):
                is_hidden = True
            elif prop == "width":
                w, u, p = parse_dimension_px(val)
                if w is not None:
                    w_attr, w_unit, is_pct = w, u, p
            elif prop == "height":
                h, _, _ = parse_dimension_px(val)
                if h is not None:
                    h_attr = h
            elif prop == "text-align":
                h_align = _parse_horizontal_align(val)
            elif prop == "vertical-align":
                v_align = _parse_vertical_align(val)
            elif prop in ("background-color", "background"):
                if not val.lower().startswith("url"):
                    bg_color = val
            elif prop == "white-space":
                white_space = val.lower()
                if white_space in ("nowrap", "pre"):
                    is_nowrap = True
            elif prop == "font-weight":
                font_weight = val.lower()
            elif prop == "font-style":
                font_style = val.lower()
            elif prop == "font-size":
                fs, _, _ = parse_dimension_px(val)
                if fs is not None:
                    font_size = fs
            elif prop == "text-indent":
                ti, _, _ = parse_dimension_px(val)
                if ti is not None:
                    text_indent = ti
            elif prop == "margin":
                _, mr_val, _, ml_val = _parse_box_4values(val)
                if mr_val is not None:
                    margin_right = mr_val
                if ml_val is not None:
                    margin_left = ml_val
            elif prop == "margin-left":
                ml, _, _ = parse_dimension_px(val)
                if ml is not None:
                    margin_left = ml
            elif prop == "margin-right":
                mr, _, _ = parse_dimension_px(val)
                if mr is not None:
                    margin_right = mr
            elif prop == "padding":
                pt_val, pr_val, pb_val, pl_val = _parse_box_4values(val)
                if pt_val is not None:
                    pad_top = pt_val
                if pr_val is not None:
                    pad_right = pr_val
                if pb_val is not None:
                    pad_bottom = pb_val
                if pl_val is not None:
                    pad_left = pl_val
            elif prop == "padding-left":
                pl, _, _ = parse_dimension_px(val)
                if pl is not None:
                    pad_left = pl
            elif prop == "padding-right":
                pr, _, _ = parse_dimension_px(val)
                if pr is not None:
                    pad_right = pr
            elif prop == "padding-top":
                pt, _, _ = parse_dimension_px(val)
                if pt is not None:
                    pad_top = pt
            elif prop == "padding-bottom":
                pb, _, _ = parse_dimension_px(val)
                if pb is not None:
                    pad_bottom = pb
            elif prop == "border":
                bw, bs, bc = _parse_border_shorthand(val)
                b_top_w = b_bot_w = b_left_w = b_right_w = bw
                b_top_s = b_bot_s = b_left_s = b_right_s = bs
                b_top_c = b_bot_c = b_left_c = b_right_c = bc
            elif prop == "border-top":
                b_top_w, b_top_s, b_top_c = _parse_border_shorthand(val)
            elif prop == "border-bottom":
                b_bot_w, b_bot_s, b_bot_c = _parse_border_shorthand(val)
            elif prop == "border-left":
                b_left_w, b_left_s, b_left_c = _parse_border_shorthand(val)
            elif prop == "border-right":
                b_right_w, b_right_s, b_right_c = _parse_border_shorthand(val)
            elif prop == "border-bottom-style":
                b_bot_s = _BORDER_STYLES.get(val.lower(), BorderStyle.SOLID)
                if b_bot_w == 0.0:
                    b_bot_w = 1.0
            elif prop == "border-bottom-width":
                bw, _, _ = parse_dimension_px(val)
                if bw is not None:
                    b_bot_w = bw
            elif prop == "border-bottom-color":
                b_bot_c = val.lower()
            elif prop == "border-top-style":
                b_top_s = _BORDER_STYLES.get(val.lower(), BorderStyle.SOLID)
                if b_top_w == 0.0:
                    b_top_w = 1.0
            elif prop == "border-top-width":
                tw, _, _ = parse_dimension_px(val)
                if tw is not None:
                    b_top_w = tw
            elif prop == "border-top-color":
                b_top_c = val.lower()

    # Fast inline check for element children: a text-only node skips the whole subtree walk.
    _c = raw_node.child
    _has_elem_child = False
    while _c is not None:
        _t = _c.tag
        if _t and _t not in ("-text", "-comment"):
            _has_elem_child = True
            break
        _c = _c.next

    if _has_elem_child:
        found_bold = False
        found_italic = False
        # Child tags and inline styles carry nested borders and typography.
        for child in _iter_cell_descendants(raw_node):
            tag = (child.tag or "").lower()
            if tag in _CELL_BOUNDARY_TAGS:
                continue

            if tag in _BOLD_TAGS:
                found_bold = True
            elif tag in _ITALIC_TAGS:
                found_italic = True

            c_style = child.attributes.get("style", "")
            if c_style:
                for prop, val in _parse_css_declarations(c_style):
                    if prop in ("border-bottom", "border"):
                        _, bs, bc = _parse_border_shorthand(val)
                        if bs != BorderStyle.NONE:
                            b_bot_s = bs
                            b_bot_w = max(b_bot_w, 1.0)
                            if bc:
                                b_bot_c = bc
                    elif prop == "border-bottom-style":
                        bs = _BORDER_STYLES.get(val.lower(), BorderStyle.SOLID)
                        if bs != BorderStyle.NONE:
                            b_bot_s = bs
                            b_bot_w = max(b_bot_w, 1.0)
                    elif prop in ("border-top",):
                        _, ts, tc = _parse_border_shorthand(val)
                        if ts != BorderStyle.NONE:
                            b_top_s = ts
                            b_top_w = max(b_top_w, 1.0)
                            if tc:
                                b_top_c = tc
                    elif prop == "font-weight" and val.lower() in (
                        "bold",
                        "700",
                        "800",
                        "900",
                    ):
                        font_weight = "bold"
                    elif prop == "text-align":
                        inner_align = _parse_horizontal_align(val)
                        if inner_align != HorizontalAlign.AUTO:
                            h_align = (
                                HorizontalAlign.LEFT
                                if inner_align == HorizontalAlign.JUSTIFY
                                else inner_align
                            )

            if tag == "hr":
                b_bot_w = max(b_bot_w, 1.0)
                b_bot_s = BorderStyle.SOLID

        is_bold = font_weight in ("bold", "700", "800", "900") or found_bold
        is_italic = font_style in ("italic", "oblique") or found_italic
    else:
        is_bold = font_weight in ("bold", "700", "800", "900")
        is_italic = font_style in ("italic", "oblique")

    return CellStyle(
        width=w_attr,
        width_unit=w_unit,
        is_percent_width=is_pct,
        height=h_attr,
        padding_left=pad_left,
        padding_right=pad_right,
        padding_top=pad_top,
        padding_bottom=pad_bottom,
        margin_left=margin_left,
        margin_right=margin_right,
        text_indent=text_indent,
        text_align=h_align,
        vertical_align=v_align,
        white_space=white_space,
        font_weight=font_weight,
        font_style=font_style,
        font_size=font_size,
        background_color=bg_color,
        border_top_width=b_top_w,
        border_top_style=b_top_s,
        border_top_color=b_top_c,
        border_bottom_width=b_bot_w,
        border_bottom_style=b_bot_s,
        border_bottom_color=b_bot_c,
        border_left_width=b_left_w,
        border_left_style=b_left_s,
        border_left_color=b_left_c,
        border_right_width=b_right_w,
        border_right_style=b_right_s,
        border_right_color=b_right_c,
        is_bold=is_bold,
        is_italic=is_italic,
        is_nowrap=is_nowrap,
        is_hidden=is_hidden,
    )


_NORMALIZE_TRANS = str.maketrans(
    {ch: " " for ch in NORMALIZE_TO_SPACE} | {ch: None for ch in STRIP_ZERO_WIDTH}
)
_SENTENCE_END_RE = re.compile(r"[:.!?\)]\s*$")
_RE_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_RE_DOTS = re.compile(r"\.{4,}")


def _collapse_non_structural_newlines(text: str) -> str:
    """Collapse soft wrapping newlines while preserving paragraphs and bullet/sentence breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = _RE_PARAGRAPH_SPLIT.split(text.strip())
    out_paragraphs: list[str] = []

    for p in paragraphs:
        lines = p.split("\n")
        curr_line: list[str] = []
        p_lines: list[str] = []
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if not curr_line:
                curr_line.append(line_str)
            else:
                prev = curr_line[-1]
                first_word = line_str.split()[0]
                is_bullet = bool(BULLET_MARKER_RE.match(first_word))
                is_sentence_end = bool(_SENTENCE_END_RE.search(prev))
                is_capital = line_str[0].isupper() or line_str[0].isdigit()
                if is_bullet or (is_sentence_end and is_capital):
                    p_lines.append(" ".join(" ".join(curr_line).split()))
                    curr_line = [line_str]
                else:
                    curr_line.append(line_str)
        if curr_line:
            p_lines.append(" ".join(" ".join(curr_line).split()))
        if p_lines:
            out_paragraphs.append("\n".join(p_lines))

    return "\n".join(out_paragraphs)


def normalize_cell_whitespace(text: str, *, preserve_newlines: bool = False) -> str:
    """Normalize cell text whitespace, dots, and soft wrapping newlines."""
    text = text.translate(_NORMALIZE_TRANS)
    text = _RE_DOTS.sub("...", text)
    if not preserve_newlines:
        text = _collapse_non_structural_newlines(text)
    return text


def _split_wide_hyphenated(text: str, width: int) -> str:
    """Split hyphenated long words to fit within available cell width."""
    if width < 4:
        return text
    tokens = text.split()
    prepared: list[str] = []
    for token in tokens:
        if len(token) > width and "-" in token:
            parts = token.split("-")
            current = parts[0]
            for part in parts[1:]:
                candidate = current + "-" + part
                if len(candidate) <= width:
                    current = candidate
                else:
                    prepared.append(current + "-")
                    current = part
            if current:
                prepared.append(current)
        else:
            prepared.append(token)
    return " ".join(prepared)


def _normalize_wrap_whitespace(text: str) -> str:
    """Make source whitespace consistently breakable for direct wrap callers."""
    return text.translate(_NORMALIZE_TRANS)


def wrap_cell_text(text: str, width: int) -> list[str]:
    """Wrap cell text at word boundaries into lines fitting the column width."""
    text = _normalize_wrap_whitespace(text)
    if not text:
        return [""]
    if len(text) <= width and "\n" not in text:
        return [text]

    raw_lines = text.split("\n")
    wrapped_lines: list[str] = []

    for line in raw_lines:
        if not line:
            wrapped_lines.append("")
            continue
        lstripped = line.lstrip(" ")
        indent_len = len(line) - len(lstripped)
        indent_str = " " * indent_len if indent_len > 0 else ""
        content = lstripped.rstrip()
        if not content:
            wrapped_lines.append(indent_str)
            continue

        prepared = _split_wide_hyphenated(content, max(4, width))
        chunks = textwrap.wrap(
            prepared,
            width=max(4, width),
            initial_indent=indent_str,
            subsequent_indent=indent_str,
            break_long_words=True,
            break_on_hyphens=False,
        )
        wrapped_lines.extend(chunks if chunks else [""])

    return wrapped_lines if wrapped_lines else [""]


def format_cell_line(
    text: str, width: int, align: HorizontalAlign = HorizontalAlign.LEFT
) -> str:
    """Format and pad a single line of text to exact column width with alignment."""
    if align == HorizontalAlign.RIGHT:
        txt = text.strip()
        if len(txt) > width:
            txt = txt[:width]
        return txt.rjust(width)
    elif align == HorizontalAlign.CENTER:
        txt = text.strip()
        if len(txt) > width:
            txt = txt[:width]
        return txt.center(width)
    else:  # LEFT or JUSTIFY or AUTO
        # Preserve leading indentation for left alignment
        txt = text.rstrip()
        if len(txt) > width:
            txt = txt[:width]
        return txt.ljust(width)


def normalize_grid_indents(
    raw_grid: list[list[str]],
    single_col_grid: list[list[str]],
) -> tuple[list[list[str]], list[list[str]]]:
    """Normalize effective column visual indentation to discrete 2-space tiers."""
    if not raw_grid or not raw_grid[0]:
        return raw_grid, single_col_grid

    num_cols = len(raw_grid[0])
    num_rows = len(raw_grid)

    new_raw = [list(r) for r in raw_grid]
    new_single = [list(r) for r in single_col_grid]

    for c in range(num_cols):
        indents: list[int] = []
        for r in range(num_rows):
            txt = new_single[r][c] if c < len(new_single[r]) else ""
            if txt.strip():
                leading = len(txt) - len(txt.lstrip(" "))
                indents.append(leading)

        if not indents:
            continue

        unique = sorted(set(indents))
        if len(unique) <= 1:
            if unique[0] > 0:
                for r in range(num_rows):
                    if c < len(new_raw[r]) and new_raw[r][c].strip():
                        new_raw[r][c] = new_raw[r][c].lstrip(" ")
                    if c < len(new_single[r]) and new_single[r][c].strip():
                        new_single[r][c] = new_single[r][c].lstrip(" ")
            continue

        mapping = {u: min(8, rank * 2) for rank, u in enumerate(unique)}

        for r in range(num_rows):
            for target_grid in (new_raw, new_single):
                if c < len(target_grid[r]):
                    txt = target_grid[r][c]
                    if txt.strip():
                        leading = len(txt) - len(txt.lstrip(" "))
                        content = txt.lstrip(" ")
                        new_indent = mapping.get(leading, min(8, leading))
                        target_grid[r][c] = (" " * new_indent) + content

    return new_raw, new_single


__all__ = [
    "format_cell_line",
    "normalize_cell_whitespace",
    "normalize_grid_indents",
    "parse_dimension_px",
    "parse_style_and_attributes",
    "wrap_cell_text",
]
