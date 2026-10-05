"""Secure environment and .env resolution.

Resolves the process environment first, then the local .env file. Direct os.environ
access is encapsulated here so the environment-access policy scanner has one seam.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DOTENV_PATH = ".env"


def load_dotenv(path: str | os.PathLike[str] = DEFAULT_DOTENV_PATH) -> dict[str, str]:
    """Parse a .env file into a dictionary without mutating os.environ."""
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
    name: str,
    default: str = "",
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> str:
    """Resolve an environment variable: direct process environment first, then .env file."""
    val = os.environ.get(name)
    if val is not None and val != "":
        return val

    target_path = dotenv_path or os.environ.get("DOTENV_PATH") or DEFAULT_DOTENV_PATH
    file_values = load_dotenv(target_path)
    if name in file_values and file_values[name] != "":
        return file_values[name]

    return default


def get_env_int(
    name: str,
    default: int,
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> int:
    """Resolve an environment variable as an integer."""
    raw = get_env(name, default="", dotenv_path=dotenv_path)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_env_float(
    name: str,
    default: float,
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> float:
    """Resolve an environment variable as a float."""
    raw = get_env(name, default="", dotenv_path=dotenv_path)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def get_env_bool(
    name: str,
    default: bool = False,
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> bool:
    """Resolve an environment variable as a boolean."""
    raw = get_env(name, default="", dotenv_path=dotenv_path).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


__all__ = ["get_env", "get_env_bool", "get_env_float", "get_env_int", "load_dotenv"]
