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

"""Safeguards for attaching the MCP server to the right AEDT session.

PyAEDT talks to AEDT through the native gRPC client library
(``PyDesktopPlugin``) of one AEDT installation, chosen before connecting:

* Without an explicit version, PyAEDT picks the newest *stable* install. When
  the running session is newer, that client cannot attach and PyAEDT silently
  starts a new AEDT session instead.
* Once a process loads one version's client library, Windows cannot load
  another version's library in the same process (``[WinError 127] The
  specified procedure could not be found``).
* MCP clients may run ``check_aedt_status`` in parallel with a connect or
  disconnect and observe the state from before the change.

The connection tools in :mod:`ansys.aedt.mcp.tools` use these helpers to pick
the version of the target session, detect unexpected new sessions, fail fast on
client library conflicts, and keep status checks consistent. All checks are
in-memory and cost microseconds.
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
import functools
from pathlib import Path
import sys
import threading
from typing import Any, ParamSpec, TypeVar

from ansys.common.mcp import get_logger

logger = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

RESTART_HINT = (
    "This error usually means this MCP server process already loaded the gRPC client "
    "library of another AEDT version. Restart the MCP server to switch AEDT versions."
)


class _ConnectionTransitions:
    """Count in-flight connection changes and let readers wait for them."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = 0

    @contextmanager
    def track(self) -> Iterator[None]:
        with self._condition:
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def wait_idle(self, timeout: float) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: self._active == 0, timeout=timeout)


_transitions = _ConnectionTransitions()


def connection_change(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Mark an async tool as changing the AEDT connection.

    :func:`wait_for_connection_changes` blocks while any decorated tool runs.
    """

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with _transitions.track():
            return await fn(*args, **kwargs)

    return wrapper


def wait_for_connection_changes(timeout: float) -> None:
    """Wait until no connect, launch, or disconnect is in flight.

    Returns immediately when nothing is in flight.

    Parameters
    ----------
    timeout : float
        Maximum time to wait in seconds.
    """
    if not _transitions.wait_idle(timeout):
        logger.warning("AEDT connection change still in progress; status may be outdated.")


def normalize_aedt_version(version: Any) -> str | None:
    """Return an AEDT version as ``"YYYY.R"``, or ``None`` when it cannot be parsed."""
    if version is None:
        return None
    try:
        from ansys.aedt.core.cli.aedt import _normalize_version_to_string

        return _normalize_version_to_string(str(version).strip()[:6])
    except Exception:
        return None


def loaded_aedt_client_version() -> str | None:
    """Return the AEDT version whose gRPC client library is loaded in this process.

    Only already-loaded modules are queried. Returns ``None`` outside Windows or
    when no AEDT client library is loaded.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        from ansys.aedt.core.internal.aedt_versions import aedt_versions

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        for installed, install_dir in aedt_versions.installed_versions.items():
            if kernel32.GetModuleHandleW(str(Path(install_dir) / "PyDesktopPlugin.dll")):
                return normalize_aedt_version(installed)
    except Exception:
        logger.debug("Unable to inspect loaded AEDT client libraries.", exc_info=True)
    return None


def check_client_version(version: Any) -> str | None:
    """Return an error message if this process cannot load ``version``'s client library.

    Parameters
    ----------
    version : Any
        Target AEDT version, for example ``"2027.1"`` or ``"271"``.

    Returns
    -------
    str or None
        Actionable message, or ``None`` when the version can be used.
    """
    target = normalize_aedt_version(version)
    loaded = loaded_aedt_client_version()
    if not (target and loaded) or target == loaded:
        return None
    return (
        f"Cannot use AEDT {target}: this MCP server process has already loaded the "
        f"AEDT {loaded} gRPC client library, and Windows cannot load another AEDT "
        "version's client library in the same process. Restart the MCP server to work with "
        f"AEDT {target}. Sessions running AEDT {loaded} remain usable."
    )


def explain_connection_error(message: str, exc: BaseException) -> str:
    """Append a restart hint to ``message`` when ``exc`` is a client library conflict."""
    if getattr(exc, "winerror", None) == 127 or "procedure could not be found" in str(exc):
        return f"{message}\n{RESTART_HINT}"
    return message


def find_session_on_port(sessions: list[dict[str, Any]], port: int | None) -> dict[str, Any] | None:
    """Return the discovered connectable session listening on ``port``."""
    if port is None:
        return None
    for session_info in sessions:
        if session_info.get("connectable") and session_info.get("port") == port:
            return session_info
    return None


def resolve_connect_version(
    version: str | None, target_session: dict[str, Any] | None
) -> str | None:
    """Return the version to request from PyAEDT when attaching to a session.

    An explicit ``version`` is kept. Otherwise the version of the target session
    is used, so PyAEDT loads the matching client instead of the latest stable one.
    """
    if version is not None or target_session is None:
        return version
    session_version = normalize_aedt_version(target_session.get("version"))
    if session_version is not None:
        logger.info(
            "Using AEDT %s detected for the session on port %s.",
            session_version,
            target_session.get("port"),
        )
    return session_version


def describe_connection_mismatch(
    desktop: Any,
    requested_port: int,
    target_session: dict[str, Any] | None,
) -> str | None:
    """Return a warning when PyAEDT did not attach to the requested session.

    Parameters
    ----------
    desktop : Any
        PyAEDT ``Desktop`` returned by the connection attempt.
    requested_port : int
        gRPC port the caller asked to attach to.
    target_session : dict[str, Any] or None
        Discovered session listening on ``requested_port``.

    Returns
    -------
    str or None
        Warning for the caller, or ``None`` when the expected session is attached.
    """
    actual_port = actual_desktop_port(desktop, requested_port)
    actual_pid = getattr(desktop, "aedt_process_id", None)
    expected_pid = target_session.get("pid") if target_session else None
    launched = getattr(desktop, "launched_by_pyaedt", False) is True
    pid_mismatch = (
        isinstance(actual_pid, int) and isinstance(expected_pid, int) and actual_pid != expected_pid
    )
    if not (launched or pid_mismatch or actual_port != requested_port):
        return None
    expected = f"the session on port {requested_port}"
    if target_session:
        expected += f" (PID {expected_pid}, AEDT {target_session.get('version')})"
    actual = "a new AEDT session that it started" if launched else "a different AEDT session"
    warning = (
        f"WARNING: PyAEDT did not attach to {expected}. It is connected to {actual} "
        f"(AEDT {getattr(desktop, 'aedt_version_id', 'unknown')}, PID {actual_pid}, "
        f"port {actual_port}) instead. Tell the user before continuing."
    )
    if launched:
        warning += " To close this new session, call disconnect_from_aedt(close_desktop=True)."
    return warning


def actual_desktop_port(desktop: Any, fallback: int) -> int:
    """Return the gRPC port the ``Desktop`` is connected to, or ``fallback``."""
    port = getattr(desktop, "port", None)
    return port if isinstance(port, int) and port > 0 else fallback
