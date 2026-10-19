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

"""Spawn lane backends and record them in the registry.

A lane backend is ``python -m ansys.aedt.mcp --transport http`` started
detached from the proxy, so it outlives the client window that created it.
Its bearer token travels only through the environment, never through the
command line, which other local users can read.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import subprocess  # nosec B404
import sys
import time
from typing import Any

import psutil

from ansys.aedt.mcp.lanes import registry as reg_mod
from ansys.aedt.mcp.lanes.backend import TOKEN_ENV

DEFAULT_HOST = "127.0.0.1"
DEFAULT_STARTUP_TIMEOUT = 60.0
"""Seconds a new lane gets to bind its HTTP port."""

BACKEND_MODULE = "ansys.aedt.mcp"
_ACCESS_DENIED = 5


@dataclass
class LaneHandle:
    """Connection details of a running lane.

    Parameters
    ----------
    server_id : str
        Lane name.
    host : str
        Host the lane listens on.
    port : int
        HTTP port of the lane.
    log_path : pathlib.Path
        Log file of the lane.
    pid : int, optional
        Process ID of the lane.
    auth_token : str, optional
        Bearer token of the lane.
    spawned : bool
        ``True`` if this call started the lane, ``False`` if it was reused.
    """

    server_id: str
    host: str
    port: int
    log_path: Path
    pid: int | None = None
    auth_token: str | None = None
    spawned: bool = False


def log_path_for(port: int) -> Path:
    """Return the log file used by the lane on ``port``.

    Parameters
    ----------
    port : int
        HTTP port of the lane.

    Returns
    -------
    pathlib.Path
        Log file path in the state directory.
    """
    return reg_mod.state_dir() / f"lane-{port}.log"


def wait_for_port(host: str, port: int, timeout: float, *, open_: bool = True) -> bool:
    """Wait until a port is open, or closed when ``open_`` is ``False``.

    Parameters
    ----------
    host : str
        Host to probe.
    port : int
        Port to probe.
    timeout : float
        Seconds to wait.
    open_ : bool, default: True
        Desired state of the port.

    Returns
    -------
    bool
        ``True`` if the port reached the desired state in time.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if reg_mod.is_port_open(host, port, timeout=0.25) == open_:
            return True
        time.sleep(0.25)
    return False


def find_listener_pid(port: int) -> int | None:
    """Return the process listening on a TCP port.

    Parameters
    ----------
    port : int
        TCP port.

    Returns
    -------
    int or None
        Process ID, or ``None`` if it cannot be determined.
    """
    with contextlib.suppress(psutil.Error, OSError):
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
                return conn.pid
    return None


def backend_env(auth_token: str) -> dict[str, str]:
    """Build the environment of a lane backend.

    Parameters
    ----------
    auth_token : str
        Bearer token the lane must require.

    Returns
    -------
    dict[str, str]
        Environment with the token and Host/Origin validation enabled, which
        guards the loopback port against DNS rebinding and cross-site requests.
    """
    env = os.environ.copy()
    env[TOKEN_ENV] = auth_token
    env.setdefault("FASTMCP_HTTP_HOST_ORIGIN_PROTECTION", "auto")
    return env


def backend_command(host: str, port: int, extra_args: list[str]) -> list[str]:
    """Build the command line of a lane backend.

    Parameters
    ----------
    host : str
        Host to bind.
    port : int
        Port to bind.
    extra_args : list[str]
        Additional ``ansys-aedt-mcp`` arguments.

    Returns
    -------
    list[str]
        Command line.
    """
    return [
        sys.executable,
        "-m",
        BACKEND_MODULE,
        "--transport",
        "http",
        "--http-host",
        host,
        "--http-port",
        str(port),
        *extra_args,
    ]


def spawn_backend(
    host: str, port: int, extra_args: list[str], log_path: Path, auth_token: str
) -> subprocess.Popen[bytes]:
    """Start a lane backend detached from the current process.

    Parameters
    ----------
    host : str
        Host to bind.
    port : int
        Port to bind.
    extra_args : list[str]
        Additional ``ansys-aedt-mcp`` arguments.
    log_path : pathlib.Path
        File receiving the backend stdout and stderr.
    auth_token : str
        Bearer token the lane must require.

    Returns
    -------
    subprocess.Popen
        Handle of the spawned process.
    """
    cmd = backend_command(host, port, extra_args)
    with log_path.open("a", encoding="utf-8", errors="replace") as log_fp:
        log_fp.write(
            f"\n---- spawn proxy_pid={os.getpid()} time={time.strftime('%Y-%m-%dT%H:%M:%S')} "
            f"host={host} port={port} cmd={cmd}\n"
        )
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_fp,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
            "env": backend_env(auth_token),
        }
        if sys.platform == "win32":
            # No console window, no Ctrl+C from the proxy, and escape the IDE's
            # job object so the lane survives when the IDE kills the proxy.
            detached = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            kwargs["creationflags"] = detached | subprocess.CREATE_BREAKAWAY_FROM_JOB
            try:
                return subprocess.Popen(cmd, **kwargs)  # nosec B603
            except OSError as exc:
                if getattr(exc, "winerror", None) != _ACCESS_DENIED:
                    raise
                # Some job objects refuse breakaway; spawn inside the job instead.
                kwargs["creationflags"] = detached
                return subprocess.Popen(cmd, **kwargs)  # nosec B603
        kwargs["start_new_session"] = True
        return subprocess.Popen(cmd, **kwargs)  # nosec B603


def ensure_backend(
    server_id: str,
    host: str = DEFAULT_HOST,
    extra_args: list[str] | None = None,
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
) -> LaneHandle:
    """Return a live lane named ``server_id``, spawning it if needed.

    A free port is reserved in the registry before spawning, so concurrent
    proxies cannot pick the same one. The spawn itself runs outside the
    registry lock because it can take many seconds.

    Parameters
    ----------
    server_id : str
        Lane name.
    host : str, default: "127.0.0.1"
        Host the lane binds to.
    extra_args : list[str], optional
        Additional ``ansys-aedt-mcp`` arguments for a new lane.
    startup_timeout : float, default: 60.0
        Seconds a new lane gets to bind its port.

    Returns
    -------
    LaneHandle
        Connection details of the lane.

    Raises
    ------
    RuntimeError
        If a new lane does not start in time.
    """
    with contextlib.suppress(Exception):
        reg_mod.reap_registry(host=host)

    with reg_mod.registry_lock():
        reg = reg_mod.load_registry()
        existing = reg.servers.get(server_id)
        if (
            existing is not None
            and reg_mod.is_port_open(host, existing.http_port)
            and (existing.pid is None or reg_mod.pid_alive(existing.pid))
        ):
            return LaneHandle(
                server_id=server_id,
                host=host,
                port=existing.http_port,
                log_path=Path(existing.log_path or log_path_for(existing.http_port)),
                pid=existing.pid or find_listener_pid(existing.http_port),
                auth_token=existing.auth_token,
            )
        port = reg_mod.allocate_http_port(reg, host=host)
        log_path = log_path_for(port)
        token = secrets.token_urlsafe(32)
        reg.servers[server_id] = reg_mod.ServerEntry(
            server_id=server_id, http_port=port, log_path=str(log_path), auth_token=token
        )
        reg_mod.save_registry(reg)

    popen = spawn_backend(host, port, list(extra_args or []), log_path, token)
    if not wait_for_port(host, port, startup_timeout):
        with contextlib.suppress(Exception):
            reg_mod.remove_entry(server_id)
        with contextlib.suppress(Exception):
            reg_mod.kill_pid(popen.pid)
        raise RuntimeError(
            f"Lane backend did not start on {host}:{port} within {startup_timeout:.0f}s. "
            f"See {log_path} for details."
        )

    reg_mod.upsert_entry(
        reg_mod.ServerEntry(
            server_id=server_id,
            http_port=port,
            pid=popen.pid,
            log_path=str(log_path),
            python=sys.executable,
            auth_token=token,
        )
    )
    return LaneHandle(
        server_id=server_id,
        host=host,
        port=port,
        log_path=log_path,
        pid=popen.pid,
        auth_token=token,
        spawned=True,
    )
