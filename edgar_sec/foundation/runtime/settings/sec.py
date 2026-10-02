"""SEC identity, rate limit, timeout, retry, and failure history settings.

Contact identity is a secret-like value: it is resolved from the environment
or explicit CLI options, but never rendered into generated dotenv output,
persisted in phase config, or logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_USER_AGENT = "Sample Company Name AdminContact@sample.com"
DEFAULT_RATE_LIMIT_RPS = 8.0
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_FAILURE_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class SecSettings:
    """Convenience typed view of SEC transport and identity settings."""

    user_agent: str = DEFAULT_USER_AGENT
    rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    max_failure_attempts: int = DEFAULT_MAX_FAILURE_ATTEMPTS

    @property
    def header_user_agent(self) -> str:
        """Formatted SEC user-agent header string."""
        return self.user_agent.strip()


def get_sec_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "sec": {
            "user_agent": SettingSpec(
                value_type=str,
                default=DEFAULT_USER_AGENT,
                env=True,
                cli=True,
                secret=True,
                description=(
                    "SEC contact identity required for live fetches, formatted as "
                    "'AppName/1.0 your-email@example.com'"
                ),
            ),
            "rate_limit_rps": SettingSpec(
                value_type=float,
                default=DEFAULT_RATE_LIMIT_RPS,
                env=True,
                cli=True,
                machine_local=True,
                description="aggregate SEC request rate limit across workers (requests/sec)",
            ),
            "timeout_s": SettingSpec(
                value_type=float,
                default=DEFAULT_TIMEOUT_S,
                env=True,
                cli=True,
                machine_local=True,
                description="HTTP request timeout in seconds",
            ),
            "max_retries": SettingSpec(
                value_type=int,
                default=DEFAULT_MAX_RETRIES,
                env=True,
                cli=True,
                machine_local=True,
                description="maximum retry attempts for transient SEC HTTP failures",
            ),
            "max_failure_attempts": SettingSpec(
                value_type=int,
                default=DEFAULT_MAX_FAILURE_ATTEMPTS,
                env=True,
                cli=True,
                machine_local=True,
                description="failure ledger budget before a repeatedly failing URL is skipped",
            ),
        },
    }


__all__ = [
    "DEFAULT_MAX_FAILURE_ATTEMPTS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RATE_LIMIT_RPS",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_USER_AGENT",
    "SecSettings",
    "get_sec_specs",
]
