"""Unit-aware CSS and HTML attribute normalization for table cells and containers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defs.tables.ascii_html.model import (
    BorderStyle,
    CellStyle,
    HorizontalAlign,
    VerticalAlign,
)

if TYPE_CHECKING:
    from defs.text.html import FastHtmlNode

# CSS declaration regex: property: value
_DECL_RE = re.compile(r"([a-zA-Z\-]+)\s*:\s*([^;]+)")
# Number + unit regex: e.g. "12.5px", "100%", "2pt", "1.5em", "300"
_UNIT_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([a-zA-Z%]*)$")
# Border style keywords
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


def _iter_cell_descendants(node: FastHtmlNode):  # type: ignore[name-defined]
    """Yield descendant raw selectolax nodes without crossing into nested cell/table boundaries.

    selectolax (lexbor) re-parents unclosed <td>/<th> siblings as children of the
    preceding cell when parsing malformed SEC HTML.  A plain `traverse()` call would
    therefore walk into sibling cells and inherit their inline styles (e.g. text-align)
    onto the wrong cell.  This bounded DFS stops recursing whenever it hits a boundary
    tag so only the current cell's own content is inspected.
    """
    # Seed stack from FastHtmlNode.iter_children() which wraps raw nodes properly
    stack = [c.raw_node for c in node.iter_children()]
    while stack:
        child = stack.pop()
        yield child
        tag = (child.tag or "").lower()
        if tag not in _CELL_BOUNDARY_TAGS:
            # Use raw selectolax .iter() for already-raw children
            stack.extend(c for c in child.iter(include_text=False) if c.tag)


def parse_dimension_px(value: str | None) -> tuple[float | None, str, bool]:
    """Parse a CSS or HTML dimension string into pixels, unit, and percent flag.

    Conversions:
    - px: 1:1
    - pt: 1pt = 1.3333px (96/72)
    - in: 1in = 96px
    - em/rem: 1em = 16px
    - %: preserved with is_percent=True
    - unitless: treated as px (standard in HTML width/height attributes)
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
    else:  # px or unitless
        return num, "px", False


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


def parse_style_and_attributes(node: FastHtmlNode) -> CellStyle:
    """Extract and normalize all inline CSS properties and HTML attributes into a CellStyle."""
    attrs = node.attributes

    # Initialize from HTML attributes
    w_attr, w_unit, is_pct = parse_dimension_px(attrs.get("width"))
    h_attr, _, _ = parse_dimension_px(attrs.get("height"))
    h_align = _parse_horizontal_align(attrs.get("align"))
    v_align = _parse_vertical_align(attrs.get("valign"))
    bg_color = attrs.get("bgcolor")
    is_nowrap = "nowrap" in attrs

    # Border attribute
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

    # Cellpadding attribute -> padding
    pad_left = pad_right = pad_top = pad_bottom = 0.0
    cellpadding = attrs.get("cellpadding")
    if cellpadding is not None:
        cp_val, _, _ = parse_dimension_px(cellpadding)
        if cp_val:
            pad_left = pad_right = pad_top = pad_bottom = cp_val

    # Parse inline style declaration overrides
    style_str = attrs.get("style", "")
    is_hidden = False
    if attrs.get("hidden") is not None:
        is_hidden = True
    elif style_str:
        from defs.tables.patterns import HIDDEN_ELEMENT_STYLE_RE

        if HIDDEN_ELEMENT_STYLE_RE.search(style_str):
            is_hidden = True

    font_weight = "normal"
    font_style = "normal"
    font_size: float | None = None
    white_space = "normal"
    margin_left = 0.0
    margin_right = 0.0
    text_indent = 0.0

    if style_str:
        for prop, val in _DECL_RE.findall(style_str):
            prop = prop.strip().lower()
            val = val.strip()

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

    # Check child tags and inline styles for nested borders or typography
    for child in _iter_cell_descendants(node):
        tag = (child.tag or "").lower()
        if tag in _CELL_BOUNDARY_TAGS:
            continue

        c_style = child.attributes.get("style", "")
        if c_style:
            for prop, val in _DECL_RE.findall(c_style):
                prop = prop.strip().lower()
                val = val.strip()
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

    # Check child formatting tags (<b>, <strong>, <i>, <em>) for typography inheritance
    is_bold = font_weight in ("bold", "700", "800", "900")
    if not is_bold and (node.find("b") or node.find("strong")):
        is_bold = True

    is_italic = font_style in ("italic", "oblique")
    if not is_italic and (node.find("i") or node.find("em")):
        is_italic = True

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


__all__ = [
    "parse_dimension_px",
    "parse_style_and_attributes",
]
