"""Measurement driver configuration: one JSON per protocol step.

Drivers are step-parameterized, never step-named: every constant
that differed between the baseline and current workspaces (seeds,
snapshot, exclusion dirs, file prefixes, caps, workdir) is config.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


#: Score bands the sampling and scoring drivers share.
BANDS = ((5.0, 7.5), (7.5, 10.0), (10.0, 15.0), (15.0, float("inf")))


def load_config() -> dict:
    """Pop ``--config <path>`` off argv and return the parsed config."""
    argv = sys.argv
    if len(argv) >= 3 and argv[1] == "--config":
        config = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        del argv[1:3]
        return config
    raise SystemExit("usage: --config <config.json> <driver args...>")


def workdir(config: dict) -> Path:
    """The step workspace the driver reads and writes, from config."""
    return Path(config["workdir"]).expanduser()
