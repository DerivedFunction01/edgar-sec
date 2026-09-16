"""SEC identity, rate limit, timeout, retry, and failure history settings.

Contact identity is a secret-like value: it is resolved from the environment
or explicit CLI options, but never rendered into generated dotenv output,
persisted in phase config, or logged.
"""

from __future__ import annotations

from defs.sec_http.client import DEFAULT_USER_AGENT
from defs.sec_http.rate_limit import DEFAULT_RATE_LIMIT_RPS
from defs.sec_http.retry import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT_S

from . import SettingSpec

SETTING_SPECS = {
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
            default=3,
            env=True,
            cli=True,
            machine_local=True,
            description="failure ledger budget before a repeatedly failing URL is skipped",
        ),
    },
}

__all__ = ["SETTING_SPECS"]
