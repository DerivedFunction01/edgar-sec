"""Managed SEC acquisition broker CLI: start, stop, status.

The broker is a same-host service that owns one production SEC client so
that Phase 2.5 process-pool workers share a single rate limiter, cache,
failure ledger, and metrics. Operational state (PID, registry, socket)
lives under the shared runtime layout resolved through
``defs.runtime.paths``.

    python -m defs.sec_http.broker start [--socket PATH] [--max-connections N]
    python -m defs.sec_http.broker stop [--socket PATH]
    python -m defs.sec_http.broker status [--socket PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from defs.runtime.config_io import write_json_config
from defs.runtime.paths import BrokerPaths, resolve_paths

from .broker import HEALTHCHECK_URL, PROTOCOL_VERSION, SecBroker, SecBrokerClient
from .client import make_sec_http_client

DEFAULT_MAX_CONNECTIONS = 16
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_STOP_TIMEOUT_S = 10.0


def _broker_paths(socket_path: str | Path | None) -> BrokerPaths:
    paths = resolve_paths().broker_paths()
    if socket_path is not None:
        requested = Path(socket_path).expanduser().resolve()
        paths = BrokerPaths(requested.parent, requested.name)
    return paths


def _read_registry(paths: BrokerPaths) -> dict[str, Any] | None:
    if not paths.registry_path.is_file():
        return None
    try:
        data = json.loads(paths.registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        payload = data.get("broker")
        return payload if isinstance(payload, dict) else data
    except (OSError, ValueError):
        return None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _socket_alive(paths: BrokerPaths) -> bool:
    if not paths.socket_path.exists():
        return False
    client = SecBrokerClient(paths.socket_path)
    try:
        result = client.fetch(HEALTHCHECK_URL)
    except Exception:
        return False
    return isinstance(result, dict) and result.get("status") == "ok"


def _wait_for_socket(paths: BrokerPaths, timeout_s: float = DEFAULT_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _socket_alive(paths):
            return True
        time.sleep(0.1)
    return False


def ensure_broker(
    socket_path: str | Path | None = None,
    *,
    max_connections: int = DEFAULT_MAX_CONNECTIONS,
) -> BrokerPaths:
    """Return broker paths, starting the broker if it is not already running.

    Safe under concurrent callers: a second caller that finds the broker
    already alive reuses it instead of launching a duplicate.
    """
    paths = _broker_paths(socket_path)
    if _socket_alive(paths):
        return paths
    _start_broker(paths, max_connections=max_connections)
    if not _socket_alive(paths):
        raise RuntimeError("broker did not become ready after start")
    return paths


def _write_registry(paths: BrokerPaths, payload: dict[str, Any]) -> None:
    write_json_config(paths.registry_path, payload, version=1, payload_key="broker")


def _start_broker(paths: BrokerPaths, *, max_connections: int) -> dict[str, Any]:
    paths.ensure_layout()
    if paths.pid_path.is_file():
        try:
            existing_pid = int(paths.pid_path.read_text(encoding="utf-8").strip())
            if _is_process_alive(existing_pid):
                raise RuntimeError(
                    f"broker already running (pid {existing_pid}); stop it first"
                )
        except ValueError:
            pass
    if _socket_alive(paths):
        raise RuntimeError("broker socket is already live; stop it first")

    cmd = [
        sys.executable,
        "-m",
        "defs.sec_http.broker",
        "serve",
        "--socket",
        str(paths.socket_path),
        "--max-connections",
        str(max_connections),
    ]
    env = None
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    paths.pid_path.write_text(str(proc.pid), encoding="utf-8")
    if not _wait_for_socket(paths):
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise RuntimeError("broker failed to become ready")
    registry = _read_registry(paths) or {
        "pid": proc.pid,
        "socket": str(paths.socket_path),
        "protocol_version": PROTOCOL_VERSION,
        "max_connections": max_connections,
    }
    registry["pid"] = proc.pid
    registry["socket"] = str(paths.socket_path)
    registry["protocol_version"] = PROTOCOL_VERSION
    registry["max_connections"] = max_connections
    _write_registry(paths, registry)
    return registry


def _stop_broker(paths: BrokerPaths) -> dict[str, Any]:
    registry = _read_registry(paths)
    pid: int | None = None
    if registry is not None:
        raw_pid = registry.get("pid")
        if isinstance(raw_pid, int):
            pid = raw_pid
    if pid is None and paths.pid_path.is_file():
        try:
            pid = int(paths.pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None

    if pid is not None and _is_process_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pid = None
        deadline = time.monotonic() + DEFAULT_STOP_TIMEOUT_S
        while time.monotonic() < deadline and _is_process_alive(pid):
            time.sleep(0.2)
        if _is_process_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    for path in (paths.pid_path, paths.registry_path, paths.socket_path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "stopped": True,
        "pid": pid,
        "socket": str(paths.socket_path),
    }


def _status_broker(paths: BrokerPaths) -> dict[str, Any]:
    registry = _read_registry(paths)
    alive = _socket_alive(paths)
    pid = None
    if registry is not None and isinstance(registry.get("pid"), int):
        pid = registry["pid"]
    elif paths.pid_path.is_file():
        try:
            pid = int(paths.pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None
    if pid is not None and not _is_process_alive(pid):
        alive = False
    summary = {
        "running": alive,
        "pid": pid,
        "socket": str(paths.socket_path),
        "protocol_version": PROTOCOL_VERSION,
        "registry_path": str(paths.registry_path),
    }
    if alive:
        client = SecBrokerClient(paths.socket_path)
        try:
            result = client.fetch(HEALTHCHECK_URL)
            if isinstance(result, dict) and result.get("status") == "ok":
                summary["metrics"] = None
        except Exception:
            summary["running"] = False
    if registry is not None:
        summary["registry"] = registry
    return summary


def _serve_broker(paths: BrokerPaths, *, max_connections: int) -> int:
    broker = SecBroker(
        socket_path=paths.socket_path,
        http_client=make_sec_http_client(),
        max_connections=max_connections,
    )
    paths.ensure_layout()
    write_json_config(
        paths.registry_path,
        {
            "pid": os.getpid(),
            "socket": str(paths.socket_path),
            "protocol_version": PROTOCOL_VERSION,
            "max_connections": max_connections,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        version=1,
        payload_key="broker",
    )
    try:
        broker.serve()
    except KeyboardInterrupt:
        broker.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="defs.sec_http.broker",
        description="Manage the same-host SEC acquisition broker",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="start the broker")
    start_parser.add_argument("--socket", default=None)
    start_parser.add_argument(
        "--max-connections", type=int, default=DEFAULT_MAX_CONNECTIONS
    )

    stop_parser = subparsers.add_parser("stop", help="stop the broker")
    stop_parser.add_argument("--socket", default=None)

    status_parser = subparsers.add_parser("status", help="report broker status")
    status_parser.add_argument("--socket", default=None)

    serve_parser = subparsers.add_parser("serve", help=argparse.SUPPRESS)
    serve_parser.add_argument("--socket", required=True)
    serve_parser.add_argument(
        "--max-connections", type=int, default=DEFAULT_MAX_CONNECTIONS
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = _broker_paths(getattr(args, "socket", None))
    try:
        if args.command == "start":
            registry = _start_broker(paths, max_connections=args.max_connections)
            print(json_dumps(registry))
            return 0
        if args.command == "stop":
            result = _stop_broker(paths)
            print(json_dumps(result))
            return 0
        if args.command == "status":
            print(json_dumps(_status_broker(paths)))
            return 0
        if args.command == "serve":
            return _serve_broker(paths, max_connections=args.max_connections)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("error: unknown command", file=sys.stderr)
    return 2


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
