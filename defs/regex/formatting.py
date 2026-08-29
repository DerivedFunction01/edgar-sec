"""Multi-line verbose formatting and structure helpers for complex regexes."""

from __future__ import annotations


def to_verbose_pattern(
    pattern: str,
    comment: str | None = None,
    indent: int = 4,
    escape_whitespace: bool = True,
) -> str:
    """Format a regex pattern with indentation and comments for re.VERBOSE.

    Splits top-level alternation branches across lines with proper indentation.
    If escape_whitespace is True, unescaped spaces inside branch terms are
    preserved with `\\ ` so re.VERBOSE does not discard them.
    """
    if not pattern:
        return ""

    spaces = " " * indent
    lines: list[str] = []
    if comment:
        lines.append(f"# {comment}")

    def _preserve_space(s: str) -> str:
        if not escape_whitespace:
            return s
        out = []
        in_class = False
        escaped = False
        for ch in s:
            if ch == "\\" and not escaped:
                escaped = True
                out.append(ch)
                continue
            if ch == "[" and not escaped:
                in_class = True
            elif ch == "]" and not escaped:
                in_class = False
            elif ch == " " and not in_class and not escaped:
                out.append(r"\ ")
                escaped = False
                continue
            out.append(ch)
            escaped = False
        return "".join(out)

    # If pattern starts with (?: and ends with ), format branches
    if pattern.startswith("(?:") and pattern.endswith(")"):
        inner = pattern[3:-1]
        branches: list[str] = []
        depth = 0
        current: list[str] = []
        for char in inner:
            if char == "(":
                depth += 1
                current.append(char)
            elif char == ")":
                depth = max(0, depth - 1)
                current.append(char)
            elif char == "|" and depth == 0:
                branches.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            branches.append("".join(current).strip())

        if len(branches) > 1:
            formatted_branches = [_preserve_space(b) for b in branches]
            lines.append(
                "(?:\n"
                + "\n".join(
                    f"{spaces}| {b}" if i > 0 else f"{spaces}  {b}"
                    for i, b in enumerate(formatted_branches)
                )
                + "\n)"
            )
            return "\n".join(lines)

    lines.append(_preserve_space(pattern))
    return "\n".join(lines)


__all__ = [
    "to_verbose_pattern",
]
