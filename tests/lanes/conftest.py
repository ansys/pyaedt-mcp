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

"""Shared fixtures for the lanes test suite.

Every test runs against a scratch state directory, so the real per-user
registry, lock file, and lane logs are never touched. None of these tests
need AEDT.
"""

import asyncio
import contextlib
import os
from pathlib import Path
import socket
import subprocess  # nosec B404
import sys
import threading

import pytest

HOST = "127.0.0.1"
STARTUP_TIMEOUT = 60.0
SHUTDOWN_TIMEOUT = 10.0
STATE_ENV_VARS = ("LOCALAPPDATA", "APPDATA", "XDG_STATE_HOME")


def point_state_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    """Point the lanes state directory at ``path``."""
    for var in STATE_ENV_VARS:
        monkeypatch.setenv(var, str(path))


def get_free_port() -> int:
    """Return a loopback port that was free a moment ago."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def _kill_spawned_lanes(registry) -> None:
    """Kill lane backends this test session spawned and clear the registry.

    Only entries recorded by the spawner (``python`` set) are killed, so fake
    entries pointing at arbitrary pids (including this process) are safe.
    """
    with contextlib.suppress(Exception):
        for entry in registry.list_entries():
            if entry.python and entry.pid and entry.pid != os.getpid():
                registry.kill_pid(entry.pid, timeout=SHUTDOWN_TIMEOUT)
        registry.reset_registry()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point the registry at ``tmp_path`` and shorten the lock timeout.

    Yields the ``registry`` module. Lane backends spawned during the test are
    killed afterwards.
    """
    point_state_at(monkeypatch, tmp_path)
    from ansys.aedt.mcp.lanes import registry

    monkeypatch.setattr(registry, "DEFAULT_LOCK_TIMEOUT", 2.0)
    yield registry
    # A test may have pointed the state elsewhere (see ``lane_state``); only
    # clean up what this test owns.
    point_state_at(monkeypatch, tmp_path)
    _kill_spawned_lanes(registry)


@pytest.fixture(autouse=True)
def _restore_app_visibility():
    """Undo visibility rules that listing upstream tools adds to the shared app."""
    from ansys.aedt.mcp.server import app

    saved = list(app._transforms)
    yield
    app._transforms[:] = saved


@pytest.fixture
def free_port() -> int:
    """Return a free loopback port."""
    return get_free_port()


@pytest.fixture
def frozen_backend():
    """TCP listener that accepts connections and never responds.

    It mimics a lane backend frozen inside a PyAEDT gRPC call, which holds
    the GIL so the HTTP socket accepts connections but never answers.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind((HOST, 0))
    srv.listen(16)
    srv.settimeout(0.1)
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def _accept_loop():
        while not stop.is_set():
            with contextlib.suppress(OSError):
                conn, _ = srv.accept()
                accepted.append(conn)

    thread = threading.Thread(target=_accept_loop, daemon=True)
    thread.start()
    try:
        yield srv.getsockname()[1]
    finally:
        stop.set()
        thread.join(timeout=2)
        for conn in accepted:
            with contextlib.suppress(OSError):
                conn.close()
        srv.close()


@pytest.fixture
def slow_backend():
    """Responsive FastMCP HTTP backend with a tool that takes a while."""
    from fastmcp import FastMCP

    from ansys.aedt.mcp.lanes import spawner

    app = FastMCP("slow")

    @app.tool
    async def slow(seconds: float = 1.0) -> str:
        await asyncio.sleep(seconds)
        return "done"

    port = get_free_port()
    loop = asyncio.new_event_loop()
    tasks: list[asyncio.Task] = []

    async def _serve():
        tasks.append(asyncio.current_task())
        await app.run_http_async(host=HOST, port=port, show_banner=False)

    def _run():
        with contextlib.suppress(asyncio.CancelledError):
            loop.run_until_complete(_serve())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    try:
        assert spawner.wait_for_port(HOST, port, 15.0)
        yield port
    finally:
        if tasks:
            loop.call_soon_threadsafe(tasks[0].cancel)
        thread.join(timeout=5)
        if not thread.is_alive():
            loop.close()


@pytest.fixture(scope="session")
def backend_cmd() -> list[str]:
    """Return the command running the regular server, or skip if it is not runnable."""
    cmd = [sys.executable, "-m", "ansys.aedt.mcp"]
    try:
        subprocess.run(  # nosec B603
            [*cmd, "--help"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"ansys-aedt-mcp is not runnable in this environment: {exc}")
    return cmd


@pytest.fixture(scope="module")
def lane_backend(backend_cmd, tmp_path_factory):
    """Spawn one real token-protected lane backend, the way ``spawn_lane`` does.

    Yields a dict with the spawner ``handle`` and the ``state_dir`` holding
    its registry. Use :func:`lane_state` to point a test at that registry.
    """
    from ansys.aedt.mcp.lanes import registry, spawner

    state = tmp_path_factory.mktemp("lane-state")
    with pytest.MonkeyPatch.context() as mp:
        point_state_at(mp, state)
        handle = spawner.ensure_backend("secured", host=HOST, startup_timeout=STARTUP_TIMEOUT)
    try:
        yield {"handle": handle, "state_dir": state}
    finally:
        if handle.pid:
            with contextlib.suppress(Exception):
                registry.kill_pid(handle.pid, timeout=SHUTDOWN_TIMEOUT)
        spawner.wait_for_port(HOST, handle.port, SHUTDOWN_TIMEOUT, open_=False)


@pytest.fixture
def lane_state(lane_backend, isolated_state, monkeypatch):
    """Point the registry at the state directory of :func:`lane_backend`."""
    point_state_at(monkeypatch, lane_backend["state_dir"])
    return isolated_state


@pytest.fixture
def http_server(backend_cmd, tmp_path):
    """Run the regular server over HTTP, without a lane token, on a free port."""
    from ansys.aedt.mcp.lanes import registry, spawner
    from ansys.aedt.mcp.lanes.backend import TOKEN_ENV
    from ansys.aedt.mcp.lanes.client import DEFAULT_PATH

    port = get_free_port()
    log_path = tmp_path / f"server-{port}.log"
    env = {key: value for key, value in os.environ.items() if key != TOKEN_ENV}
    with log_path.open("w", encoding="utf-8") as log_fp:
        popen = subprocess.Popen(  # nosec B603
            spawner.backend_command(HOST, port, []),
            stdin=subprocess.DEVNULL,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            env=env,
        )
    try:
        if not spawner.wait_for_port(HOST, port, STARTUP_TIMEOUT):
            log = log_path.read_text(errors="replace")
            pytest.fail(f"Server did not open {HOST}:{port} in {STARTUP_TIMEOUT}s.\n{log}")
        yield {"host": HOST, "port": port, "path": DEFAULT_PATH, "log_path": log_path}
    finally:
        registry.kill_pid(popen.pid, timeout=SHUTDOWN_TIMEOUT)
        with contextlib.suppress(subprocess.TimeoutExpired):
            popen.wait(timeout=SHUTDOWN_TIMEOUT)
        spawner.wait_for_port(HOST, port, SHUTDOWN_TIMEOUT, open_=False)
