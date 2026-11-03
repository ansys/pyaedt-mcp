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

"""Shared helpers for the PyAEDT-MCP benchmark suite.

The benchmarks talk to a *real* PyAEDT-MCP server over stdio, exactly like an
MCP client does. The server is started from an arbitrary ``src`` directory so
that two code revisions (for example a baseline worktree and the current
checkout) can be measured with the same harness and the same interpreter.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess  # nosec B404
import sys
import time
from typing import Any, AsyncIterator

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = REPO_ROOT / "src"

_SERVER_BOOTSTRAP = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from ansys.aedt.mcp.server import launcher; launcher()"
)


def default_python() -> str:
    """Return the interpreter used to run the server (the repo virtualenv if present)."""
    if sys.platform == "win32":
        candidate = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = REPO_ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def server_env(src: Path) -> dict[str, str]:
    """Build the environment for a server started from ``src``."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


@asynccontextmanager
async def mcp_client(
    src: Path,
    server_args: list[str] | None = None,
    cwd: Path | None = None,
    python: str | None = None,
    timeout: float = 900.0,
) -> AsyncIterator[Any]:
    """Start a PyAEDT-MCP server from ``src`` over stdio and yield a connected client."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command=python or default_python(),
        args=["-c", _SERVER_BOOTSTRAP, str(src), *(server_args or [])],
        env=server_env(src),
        cwd=str(cwd) if cwd else None,
        keep_alive=False,
    )
    # "legacy" = the classic initialize handshake used by today's MCP clients.
    client = Client(transport, timeout=timeout, init_timeout=timeout, mode="legacy")
    async with client:
        yield client


def current_children() -> set[int]:
    """Return PIDs of every process currently below this one."""
    import psutil

    return {p.pid for p in psutil.Process().children(recursive=True)}


def process_tree_stats(before: set[int]) -> dict[str, float]:
    """Return process count and RSS of the processes spawned since ``before``."""
    import psutil

    procs = [p for p in psutil.Process().children(recursive=True) if p.pid not in before]
    rss = 0
    for proc in procs:
        try:
            rss += proc.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {"process_count": len(procs), "rss_mb": rss / (1024 * 1024)}


def tool_text(result: Any) -> str:
    """Join the text content blocks of a tool result."""
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


def git_describe(path: Path) -> str:
    """Return ``git describe`` information for ``path`` (best effort)."""
    try:
        out = subprocess.run(  # nosec
            ["git", "-C", str(path), "describe", "--always", "--dirty"],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


@dataclass
class Recorder:
    """Collect benchmark samples and serialize them to JSON."""

    label: str
    src: Path
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, name: str, value: float, unit: str = "s", better: str = "lower") -> None:
        """Append one sample to metric ``name``."""
        entry = self.metrics.setdefault(name, {"unit": unit, "better": better, "values": []})
        entry["values"].append(float(value))

    async def timed(self, name: str, coro: Any) -> Any:
        """Await ``coro`` and record its wall-clock duration under ``name``."""
        start = time.perf_counter()
        result = await coro
        self.add(name, time.perf_counter() - start)
        return result

    def summary(self) -> dict[str, Any]:
        """Return metrics with aggregate statistics."""
        out = {}
        for name, entry in sorted(self.metrics.items()):
            values = entry["values"]
            out[name] = {
                **entry,
                "n": len(values),
                "median": statistics.median(values),
                "mean": statistics.fmean(values),
                "min": min(values),
                "max": max(values),
                "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
            }
        return out

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-serializable result document."""
        return {
            "meta": {
                "label": self.label,
                "src": str(self.src),
                "git": git_describe(self.src),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "python": default_python(),
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
            },
            "metrics": self.summary(),
            "notes": self.notes,
        }


def write_results(path: Path, recorder: Recorder) -> None:
    """Write (or merge into) a JSON results file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = recorder.to_json()
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing["metrics"].update(data["metrics"])
        existing["notes"].extend(n for n in data["notes"] if n not in existing["notes"])
        existing["meta"] = data["meta"]
        data = existing
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class PingMonitor:
    """Measure server event-loop responsiveness by pinging while other work runs.

    A blocked event loop cannot answer pings, so the maximum ping latency
    observed during a tool call approximates how long the loop was blocked.
    """

    def __init__(self, client: Any, interval: float = 0.05):
        self._client = client
        self._interval = interval
        self._task: asyncio.Task | None = None
        self.latencies: list[float] = []

    async def _run(self) -> None:
        while True:
            start = time.perf_counter()
            try:
                await self._client.ping()
            except Exception:
                return
            self.latencies.append(time.perf_counter() - start)
            await asyncio.sleep(self._interval)

    async def __aenter__(self) -> "PingMonitor":
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._task is not None:
            # Give an in-flight ping the chance to finish so a blocked loop is recorded.
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=self._interval * 4)
            except (asyncio.TimeoutError, Exception):
                pass
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    @property
    def max_latency(self) -> float:
        """Return the largest observed ping latency in seconds."""
        return max(self.latencies) if self.latencies else 0.0
