# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Local, read-only status dashboard for lanes.

Serves one HTML page and one JSON endpoint on ``127.0.0.1``. Status comes
only from cheap, static sources: the registry file, process liveness, TCP
connects to the registered ports, and the tail of each lane log. The
dashboard never opens an MCP session, so it cannot load or be blocked by a
busy lane.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
import webbrowser

from ansys.aedt.mcp.lanes.registry import (
    Registry,
    ServerEntry,
    is_port_open,
    pid_alive,
    registry_path,
    state_dir,
)

DEFAULT_PORT = 8765
DEFAULT_REFRESH_SECONDS = 30
MIN_REFRESH_SECONDS = 2
LOG_TAIL_BYTES = 64 * 1024
BUSY_WARN_SECONDS = 30.0
HOST = "127.0.0.1"

_LOG_LINE_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ \[(\w+)\] (.*)$")
_CALL_MARKER = "Processing request of type CallToolRequest"
_PROTOCOL_MARKERS = (
    "Processing request of type",
    "Terminating session",
    "Created new transport with session ID",
)
_TRACEBACK_PREFIXES = ("*", "File ", "^", "Traceback")
_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; "
    "style-src 'unsafe-inline'; connect-src 'self'"
)


def _parse_ts(text: str) -> float | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def _read_tail(path: Path, max_bytes: int = LOG_TAIL_BYTES) -> list[str]:
    with path.open("rb") as fh:
        size = fh.seek(0, 2)
        start = max(0, size - max_bytes)
        fh.seek(start)
        lines = fh.read().decode("utf-8", errors="replace").splitlines()
    # The first line of a partial read is probably truncated.
    return lines[1:] if start > 0 and lines else lines


def summarize_log(path: Path, now: float | None = None) -> dict[str, Any]:
    """Summarize the tail of a lane log.

    A call is considered in progress when the most recent MCP protocol event
    in the log is a ``CallToolRequest``. This is a heuristic: the lane may
    also be frozen inside the call.

    Parameters
    ----------
    path : pathlib.Path
        Lane log file.
    now : float, optional
        Current POSIX time. Defaults to :func:`time.time`.

    Returns
    -------
    dict[str, Any]
        Log size, idle time, last protocol event, running call, and last error.
    """
    now = time.time() if now is None else now
    info: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not info["exists"]:
        return info
    try:
        stat = path.stat()
        lines = _read_tail(path)
    except OSError as exc:
        info["error"] = str(exc)
        return info

    last_event = last_event_at = last_call_at = last_error = last_error_at = None
    error_lines = 0
    for line in lines:
        match = _LOG_LINE_RE.match(line)
        if not match:
            continue
        ts_text, level, message = match.groups()
        ts = _parse_ts(ts_text)
        if level == "ERROR":
            error_lines += 1
            text = message.split(": ", 1)[-1].strip()
            if text and not text.startswith(_TRACEBACK_PREFIXES):
                last_error, last_error_at = text, ts
        if any(marker in message for marker in _PROTOCOL_MARKERS):
            last_event = message.split(": ", 1)[-1].strip()
            last_event_at = ts
            last_call_at = ts if _CALL_MARKER in message else None

    info.update(
        {
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
            "idle_seconds": round(max(0.0, now - stat.st_mtime), 1),
            "last_event": last_event,
            "last_event_at": last_event_at,
            "call_in_progress_since": last_call_at,
            "call_elapsed_seconds": (
                round(max(0.0, now - last_call_at), 1) if last_call_at is not None else None
            ),
            "error_lines_in_tail": error_lines,
            "last_error": last_error,
            "last_error_at": last_error_at,
        }
    )
    return info


def _lane_status(entry: ServerEntry, now: float) -> dict[str, Any]:
    listening = is_port_open(HOST, entry.http_port)
    alive = pid_alive(entry.pid) if entry.pid else False
    aedt_reachable = is_port_open(HOST, entry.aedt_gpc_port) if entry.aedt_gpc_port else None
    log_path = (
        Path(entry.log_path) if entry.log_path else state_dir() / f"lane-{entry.http_port}.log"
    )
    log = summarize_log(log_path, now=now)

    status = "ok"
    notes: list[str] = []
    if not listening:
        status = "down"
        notes.append(
            "process alive but HTTP port closed (starting up or wedged)"
            if alive
            else "backend not running; reap or relaunch"
        )
    else:
        elapsed = log.get("call_elapsed_seconds")
        if elapsed is not None:
            if elapsed >= BUSY_WARN_SECONDS:
                status = "busy"
                notes.append(f"tool call running for {int(elapsed)}s (or backend frozen)")
            else:
                notes.append(f"tool call running for {int(elapsed)}s")
        if not alive:
            status = "degraded" if status == "ok" else status
            notes.append("registered pid not found; port may be held by another process")
        if entry.aedt_gpc_port and not aedt_reachable:
            status = "degraded" if status == "ok" else status
            notes.append(f"AEDT gRPC port {entry.aedt_gpc_port} not reachable")
    if not entry.aedt_gpc_port:
        notes.append("no AEDT session attached")

    return {
        "lane_id": entry.server_id,
        "status": status,
        "notes": notes,
        "http_port": entry.http_port,
        "listening": listening,
        "pid": entry.pid,
        "pid_alive": alive,
        "auth": entry.auth_mode,
        "aedt_gpc_port": entry.aedt_gpc_port,
        "aedt_reachable": aedt_reachable,
        "started_at": entry.started_at,
        "uptime_seconds": round(max(0.0, now - entry.started_at), 1) if entry.started_at else None,
        "log": log,
    }


def collect_status(refresh_seconds: int = DEFAULT_REFRESH_SECONDS) -> dict[str, Any]:
    """Build the status document served at ``/api/status``.

    The registry is read without the lock: writers replace the file
    atomically, and a monitor must never contend with the live registry.

    Parameters
    ----------
    refresh_seconds : int, default: 30
        Refresh interval suggested to the page.

    Returns
    -------
    dict[str, Any]
        Registry details and per-lane status. Lane tokens are never included.
    """
    now = time.time()
    path = registry_path()
    registry: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    entries: list[ServerEntry] = []
    if registry["exists"]:
        try:
            registry["modified_at"] = path.stat().st_mtime
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            servers = Registry.from_dict(data if isinstance(data, dict) else {}).servers
            entries = sorted(servers.values(), key=lambda entry: entry.server_id)
        except (OSError, ValueError) as exc:
            registry["error"] = f"{type(exc).__name__}: {exc}"

    return {
        "generated_at": now,
        "refresh_seconds": refresh_seconds,
        "state_dir": str(state_dir()),
        "registry": registry,
        "lanes": [_lane_status(entry, now) for entry in entries],
    }


def _page_html() -> bytes:
    return resources.files(__package__).joinpath("dashboard.html").read_bytes()


def make_handler(refresh_seconds: int) -> type[BaseHTTPRequestHandler]:
    """Build the request handler serving the page and the status JSON.

    Parameters
    ----------
    refresh_seconds : int
        Refresh interval suggested to the page.

    Returns
    -------
    type[http.server.BaseHTTPRequestHandler]
        Handler class.
    """

    class _Handler(BaseHTTPRequestHandler):
        server_version = "ansys-aedt-mcp-lanes-dashboard"

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", _CSP)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            # DNS-rebinding guard: only answer requests addressed to loopback.
            port = self.server.server_address[1]  # type: ignore[index]
            if self.headers.get("Host", "") not in {f"{HOST}:{port}", f"localhost:{port}"}:
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            route = self.path.split("?", 1)[0]
            if route == "/":
                self._send(200, _page_html(), "text/html; charset=utf-8")
            elif route == "/api/status":
                body = json.dumps(collect_status(refresh_seconds)).encode("utf-8")
                self._send(200, body, "application/json")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            """Silence per-request logging."""

    return _Handler


def make_server(port: int, refresh_seconds: int) -> ThreadingHTTPServer:
    """Create the dashboard server on loopback without starting it.

    Parameters
    ----------
    port : int
        Port to bind. ``0`` picks a free port.
    refresh_seconds : int
        Refresh interval suggested to the page.

    Returns
    -------
    http.server.ThreadingHTTPServer
        Dashboard server.
    """
    server = ThreadingHTTPServer((HOST, port), make_handler(refresh_seconds))
    server.daemon_threads = True
    return server


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the dashboard options to a parser.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Parser to extend.
    """
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Dashboard port (default {DEFAULT_PORT})."
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=DEFAULT_REFRESH_SECONDS,
        help=f"Default refresh interval in seconds (default {DEFAULT_REFRESH_SECONDS}).",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")


def run(port: int, refresh_seconds: int, open_browser: bool = True) -> int:
    """Serve the dashboard until interrupted.

    Parameters
    ----------
    port : int
        Port to bind.
    refresh_seconds : int
        Refresh interval suggested to the page.
    open_browser : bool, default: True
        Whether to open the page in a browser.

    Returns
    -------
    int
        Process exit code.
    """
    try:
        server = make_server(port, refresh_seconds)
    except OSError as exc:
        print(f"Cannot bind {HOST}:{port}: {exc}. Try --port.", file=sys.stderr)
        return 1
    url = f"http://{HOST}:{server.server_address[1]}/"
    print(f"ansys-aedt-mcp lanes dashboard: {url}  (refresh {refresh_seconds}s, Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
