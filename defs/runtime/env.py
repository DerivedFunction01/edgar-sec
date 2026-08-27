"""Environment and .env-based setting resolution.

Settings resolve in order: direct process environment, then the repository
``.env`` file (default ``.env``, overridable via ``EDGAR_DOTENV_PATH``).
Secrets never come from tracked configuration; ``.env`` is git-ignored.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DOTENV_PATH = ".env"


def load_dotenv(path: str | os.PathLike[str] = DEFAULT_DOTENV_PATH) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping without mutating the environment.

    Supports blank lines, ``#`` comments, an optional ``export `` prefix,
    and matching single/double quotes around values. A missing or unreadable
    file yields an empty mapping.
    """
    values: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def get_env(
    name: str, default: str = "", *, path: str | os.PathLike[str] | None = None
) -> str:
    """Resolve one setting: direct environment first, then the ``.env`` file.

    An empty direct-environment value is treated as unset so a ``.env``
    fallback still applies. ``path=None`` uses ``EDGAR_DOTENV_PATH`` when set,
    otherwise ``.env`` relative to the current working directory.
    """
    value = os.environ.get(name)
    if value:
        return value
    dotenv_path = (
        path
        if path is not None
        else os.environ.get("EDGAR_DOTENV_PATH", DEFAULT_DOTENV_PATH)
    )
    return load_dotenv(dotenv_path).get(name, default)


__all__ = ["DEFAULT_DOTENV_PATH", "get_env", "load_dotenv"]
