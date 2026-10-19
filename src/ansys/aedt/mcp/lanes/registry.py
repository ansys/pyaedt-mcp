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

"""File-backed registry of lane backends.

A *lane* is a long-lived ``ansys-aedt-mcp`` process serving the HTTP
transport on a loopback port. Each lane owns at most one AEDT session. The
registry records every running lane so that several MCP clients (IDE
windows, agents) can find and reuse the same backends.

The registry lives in a per-user state directory (``%LOCALAPPDATA%`` on
Windows, ``$XDG_STATE_HOME`` on POSIX) and is guarded by a bounded-timeout
:class:`filelock.FileLock`. A corrupt file is moved aside and replaced by an
empty registry, so every function here is safe to call from a recovery path.
"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import socket
import sys
import time
from typing import Any

import psutil

SCHEMA_VERSION = 1
"""Version of the on-disk registry format."""

DEFAULT_LOCK_TIMEOUT = 10.0
"""Seconds to wait for the registry lock before giving up."""

DEFAULT_HTTP_PORT_RANGE = (8090, 8189)
"""Inclusive port range for lane backends. It avoids the default HTTP port 8080."""

STATE_DIR_NAME = "ansys-aedt-mcp"
REGISTRY_FILENAME = "registry.json"
LOCKFILE_NAME = "registry.lock"

AEDT_PROCESS_PREFIXES = ("ansysedt",)
"""Process name prefixes identifying AEDT, which must survive a lane recycle."""


def state_dir() -> Path:
    """Return the per-user state directory, creating it if needed.

    Returns
    -------
    pathlib.Path
        Directory holding the registry, its lock file, and the lane logs.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    directory = Path(base) / STATE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def registry_path() -> Path:
    """Return the path to the registry JSON file.

    Returns
    -------
    pathlib.Path
        Registry file path.
    """
    return state_dir() / REGISTRY_FILENAME


def lockfile_path() -> Path:
    """Return the path to the registry lock file.

    Returns
    -------
    pathlib.Path
        Lock file path.
    """
    return state_dir() / LOCKFILE_NAME


@dataclass
class ServerEntry:
    """One lane backend recorded in the registry.

    Parameters
    ----------
    server_id : str
        Lane name, unique within the registry.
    http_port : int
        Loopback port the lane serves MCP over HTTP on.
    pid : int, optional
        Process ID of the lane backend.
    aedt_gpc_port : int, optional
        gRPC port of the AEDT session the lane owns, if known.
    log_path : str, optional
        File capturing the lane's stdout and stderr.
    started_at : float
        Creation time as a POSIX timestamp.
    python : str, optional
        Interpreter running the lane, which identifies its installation.
    auth_token : str, optional
        Bearer secret the lane requires on every HTTP request. It is never
        exposed to clients; use :meth:`public_dict` for display.
    """

    server_id: str
    http_port: int
    pid: int | None = None
    aedt_gpc_port: int | None = None
    log_path: str | None = None
    started_at: float = field(default_factory=time.time)
    python: str | None = None
    auth_token: str | None = field(default=None, repr=False)

    @property
    def auth_mode(self) -> str:
        """Authentication mode of the lane: ``"token"`` or ``"none"``."""
        return "token" if self.auth_token else "none"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation, including the secret.

        Returns
        -------
        dict[str, Any]
            All entry fields.
        """
        return asdict(self)

    def public_dict(self) -> dict[str, Any]:
        """Return a representation safe to show to clients.

        Returns
        -------
        dict[str, Any]
            Entry fields with ``auth_token`` replaced by ``auth``.
        """
        data = asdict(self)
        data.pop("auth_token", None)
        data["auth"] = self.auth_mode
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerEntry:
        """Rebuild an entry from JSON data, ignoring unknown fields.

        Parameters
        ----------
        data : dict[str, Any]
            Serialized entry.

        Returns
        -------
        ServerEntry
            Rebuilt entry.
        """
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class Registry:
    """In-memory view of the on-disk registry."""

    schema_version: int = SCHEMA_VERSION
    servers: dict[str, ServerEntry] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        Returns
        -------
        dict[str, Any]
            Serialized registry.
        """
        return {
            "schema_version": self.schema_version,
            "servers": {sid: entry.to_dict() for sid, entry in self.servers.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Registry:
        """Rebuild a registry from JSON data.

        Files with another schema version start empty. Malformed entries are
        skipped.

        Parameters
        ----------
        data : dict[str, Any]
            Serialized registry.

        Returns
        -------
        Registry
            Rebuilt registry.
        """
        if data.get("schema_version") != SCHEMA_VERSION:
            return cls()
        servers: dict[str, ServerEntry] = {}
        for sid, entry_data in (data.get("servers") or {}).items():
            with contextlib.suppress(Exception):
                servers[sid] = ServerEntry.from_dict(entry_data)
        return cls(servers=servers)


class RegistryLockTimeoutError(RuntimeError):
    """Raised when the registry lock cannot be acquired in time."""


@contextlib.contextmanager
def registry_lock(timeout: float | None = None) -> Iterator[None]:
    """Hold the registry lock for the duration of the block.

    The OS releases the lock when its holder dies, even if the lock file
    stays on disk.

    Parameters
    ----------
    timeout : float, optional
        Seconds to wait for the lock. Defaults to ``DEFAULT_LOCK_TIMEOUT``.

    Raises
    ------
    RegistryLockTimeoutError
        If the lock is not acquired within ``timeout`` seconds.
    """
    from filelock import FileLock, Timeout

    timeout = DEFAULT_LOCK_TIMEOUT if timeout is None else timeout
    lock = FileLock(str(lockfile_path()))
    try:
        with lock.acquire(timeout=timeout):
            yield
    except Timeout as exc:
        raise RegistryLockTimeoutError(
            f"Could not acquire the registry lock at {lockfile_path()} within {timeout:.1f}s. "
            "If nothing is holding it, run `ansys-aedt-mcp --lanes unlock`."
        ) from exc


def force_unlock() -> bool:
    """Delete the registry lock file.

    Use only when the lock is stuck and no legitimate holder exists. The
    registry file itself is left untouched.

    Returns
    -------
    bool
        ``True`` if a lock file was removed.
    """
    path = lockfile_path()
    try:
        if path.exists():
            path.unlink()
            return True
    except OSError:
        return False
    return False


def _backup_corrupt(path: Path) -> Path:
    """Move a corrupt registry file aside and return the backup path."""
    backup = path.with_name(f"{path.stem}.bad-{int(time.time())}{path.suffix}")
    with contextlib.suppress(OSError):
        path.replace(backup)
    return backup


def load_registry() -> Registry:
    """Read the registry from disk.

    A missing file yields an empty registry. A corrupt file is backed up and
    replaced by an empty registry.

    Returns
    -------
    Registry
        Current registry content.
    """
    path = registry_path()
    if not path.exists():
        return Registry()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError):
        _backup_corrupt(path)
        return Registry()
    if not isinstance(data, dict):
        _backup_corrupt(path)
        return Registry()
    return Registry.from_dict(data)


def save_registry(reg: Registry) -> None:
    """Write the registry to disk atomically.

    The caller must hold :func:`registry_lock`.

    Parameters
    ----------
    reg : Registry
        Registry to persist.
    """
    path = registry_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(reg.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def is_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    """Check whether a TCP connection to ``host:port`` succeeds.

    Parameters
    ----------
    host : str
        Host name or address.
    port : int
        TCP port.
    timeout : float, default: 0.3
        Connection timeout in seconds.

    Returns
    -------
    bool
        ``True`` if something accepts connections on the port.
    """
    with contextlib.suppress(OSError), socket.create_connection((host, port), timeout=timeout):
        return True
    return False


def pid_alive(pid: int) -> bool:
    """Check whether a process exists and is not a zombie.

    Parameters
    ----------
    pid : int
        Process ID.

    Returns
    -------
    bool
        ``True`` if the process is running.
    """
    if pid <= 0:
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def kill_pid(pid: int, timeout: float = 10.0, tree: bool = True) -> bool:
    """Kill a process and wait for it to exit.

    Parameters
    ----------
    pid : int
        Process ID.
    timeout : float, default: 10.0
        Seconds to wait for the processes to exit.
    tree : bool, default: True
        Whether to kill the descendants too. With ``False`` only ``pid`` is
        killed, so neither its children (such as an AEDT it launched) nor its
        exit handlers run.

    Returns
    -------
    bool
        ``True`` if ``pid`` is gone.
    """
    try:
        process = psutil.Process(pid)
    except psutil.Error:
        return True
    targets = [process]
    if tree:
        with contextlib.suppress(psutil.Error):
            targets.extend(process.children(recursive=True))
    for target in targets:
        with contextlib.suppress(psutil.Error):
            target.kill()
    psutil.wait_procs(targets, timeout=timeout)
    return not pid_alive(pid)


def kill_keeping_aedt(
    pid: int, timeout: float = 10.0, keep_names: tuple[str, ...] = AEDT_PROCESS_PREFIXES
) -> bool:
    """Kill a lane backend and its helpers but keep AEDT running.

    AEDT processes and their children are spared. Every other process is
    killed alone and abruptly, so no exit handler can close AEDT.

    Parameters
    ----------
    pid : int
        Process ID of the lane backend.
    timeout : float, default: 10.0
        Seconds to wait for each process to exit.
    keep_names : tuple[str, ...], default: ("ansysedt",)
        Lower-case process name prefixes to keep alive.

    Returns
    -------
    bool
        ``True`` if the backend process is gone.
    """
    try:
        descendants = psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        descendants = []
    keep: set[int] = set()
    for proc in descendants:
        with contextlib.suppress(psutil.Error):
            if proc.name().lower().startswith(keep_names):
                keep.add(proc.pid)
                keep.update(child.pid for child in proc.children(recursive=True))
    killed = kill_pid(pid, timeout=timeout, tree=False)
    for proc in descendants:
        if proc.pid not in keep:
            kill_pid(proc.pid, timeout=timeout, tree=False)
    return killed


@dataclass
class StopReport:
    """Outcome of :func:`stop_entry`."""

    server_id: str
    pid: int | None
    killed: bool
    removed: bool


def stop_entry(server_id: str, timeout: float = 10.0) -> StopReport | None:
    """Kill a lane backend and remove it from the registry.

    Parameters
    ----------
    server_id : str
        Lane name.
    timeout : float, default: 10.0
        Seconds to wait for the backend to exit.

    Returns
    -------
    StopReport or None
        What was killed and removed, or ``None`` if the lane is not registered.
    """
    entry = get_entry(server_id)
    if entry is None:
        return None
    killed = entry.pid is not None and kill_pid(entry.pid, timeout=timeout)
    return StopReport(server_id, entry.pid, killed, remove_entry(server_id))


@dataclass
class ReapReport:
    """Lanes removed and kept by :func:`reap_registry`."""

    dropped: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)


def reap_registry(host: str = "127.0.0.1") -> ReapReport:
    """Remove registry entries whose backend is no longer live.

    A lane is live when its process exists and its HTTP port accepts
    connections.

    Parameters
    ----------
    host : str, default: "127.0.0.1"
        Host the lanes listen on.

    Returns
    -------
    ReapReport
        Dropped and kept lane names.
    """
    report = ReapReport()
    with registry_lock():
        reg = load_registry()
        survivors: dict[str, ServerEntry] = {}
        for sid, entry in reg.servers.items():
            if (
                entry.pid is not None
                and pid_alive(entry.pid)
                and is_port_open(host, entry.http_port)
            ):
                survivors[sid] = entry
                report.kept.append(sid)
            else:
                report.dropped.append(sid)
        if report.dropped:
            reg.servers = survivors
            save_registry(reg)
    return report


@dataclass
class ResetReport:
    """Summary of :func:`reset_registry`."""

    dropped: list[str] = field(default_factory=list)
    killed: list[int] = field(default_factory=list)
    failed_to_kill: list[int] = field(default_factory=list)
    unlocked: bool = False


def reset_registry(kill_orphans: bool = False, unlock: bool = False) -> ResetReport:
    """Clear every registry entry.

    Parameters
    ----------
    kill_orphans : bool, default: False
        Whether to kill each lane process before clearing its entry.
    unlock : bool, default: False
        Whether to delete the lock file first. Use only when the lock is stuck.

    Returns
    -------
    ResetReport
        What was dropped, killed, and unlocked.
    """
    report = ResetReport()
    if unlock:
        report.unlocked = force_unlock()
    with registry_lock():
        reg = load_registry()
        for sid, entry in reg.servers.items():
            report.dropped.append(sid)
            if kill_orphans and entry.pid is not None:
                if kill_pid(entry.pid):
                    report.killed.append(entry.pid)
                else:
                    report.failed_to_kill.append(entry.pid)
        reg.servers = {}
        save_registry(reg)
    return report


def allocate_http_port(
    reg: Registry,
    host: str = "127.0.0.1",
    port_range: tuple[int, int] = DEFAULT_HTTP_PORT_RANGE,
) -> int:
    """Return the first port in range that is neither registered nor bound.

    The caller must hold :func:`registry_lock`. The port is reserved only
    once an entry using it is saved.

    Parameters
    ----------
    reg : Registry
        Current registry.
    host : str, default: "127.0.0.1"
        Host the lanes listen on.
    port_range : tuple[int, int], default: (8090, 8189)
        Inclusive range of candidate ports.

    Returns
    -------
    int
        Free port.

    Raises
    ------
    RuntimeError
        If every port in the range is taken.
    """
    reserved = {entry.http_port for entry in reg.servers.values()}
    for port in range(port_range[0], port_range[1] + 1):
        if port not in reserved and not is_port_open(host, port):
            return port
    raise RuntimeError(
        f"No free HTTP port available in {port_range[0]}..{port_range[1]} "
        f"(registry has {len(reserved)} entries)."
    )


def upsert_entry(entry: ServerEntry) -> None:
    """Insert or replace one entry.

    Parameters
    ----------
    entry : ServerEntry
        Entry to store.
    """
    with registry_lock():
        reg = load_registry()
        reg.servers[entry.server_id] = entry
        save_registry(reg)


def update_aedt_port(server_id: str, aedt_gpc_port: int | None) -> bool:
    """Set the AEDT gRPC port of one entry.

    Parameters
    ----------
    server_id : str
        Lane name.
    aedt_gpc_port : int, optional
        New AEDT gRPC port, or ``None`` to clear it.

    Returns
    -------
    bool
        ``False`` if the entry no longer exists.
    """
    with registry_lock():
        reg = load_registry()
        entry = reg.servers.get(server_id)
        if entry is None:
            return False
        entry.aedt_gpc_port = aedt_gpc_port
        save_registry(reg)
        return True


def remove_entry(server_id: str) -> bool:
    """Remove one entry.

    Parameters
    ----------
    server_id : str
        Lane name.

    Returns
    -------
    bool
        ``True`` if an entry was removed.
    """
    with registry_lock():
        reg = load_registry()
        if reg.servers.pop(server_id, None) is None:
            return False
        save_registry(reg)
        return True


def get_entry(server_id: str) -> ServerEntry | None:
    """Return one entry.

    Parameters
    ----------
    server_id : str
        Lane name.

    Returns
    -------
    ServerEntry or None
        The entry, or ``None`` if it does not exist.
    """
    with registry_lock():
        return load_registry().servers.get(server_id)


def list_entries() -> list[ServerEntry]:
    """Return every entry.

    Returns
    -------
    list[ServerEntry]
        Registered lanes.
    """
    with registry_lock():
        return list(load_registry().servers.values())
