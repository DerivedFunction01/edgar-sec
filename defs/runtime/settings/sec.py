"""SEC identity, rate limit, timeout, retry, and failure history settings.

Contact identity is a secret-like value: it is resolved from the environment
or explicit CLI options, but never rendered into generated dotenv output,
persisted in phase config, or logged.
"""

from __future__ import annotations

from . import SettingSpec

SETTING_SPECS = {
    "sec": {
        "user_agent": SettingSpec(
            value_type=str,
            default="EdgarSec/1.0 contact@example.com",
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
            default=4.0,
            env=True,
            cli=True,
            machine_local=True,
            description="aggregate SEC request rate limit across workers (requests/sec)",
        ),
        "timeout_s": SettingSpec(
            value_type=float,
            default=15.0,
            env=True,
            cli=True,
            machine_local=True,
            description="HTTP request timeout in seconds",
        ),
        "max_retries": SettingSpec(
            value_type=int,
            default=4,
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
