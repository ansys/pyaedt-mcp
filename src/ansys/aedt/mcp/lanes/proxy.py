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

"""Stdio routing proxy that multiplexes AEDT sessions ("lanes").

The proxy is what an MCP client starts with ``ansys-aedt-mcp --lanes``. It:

1. Lists the regular PyAEDT-MCP tools in-process, applying the same tag
   filters as the regular CLI. No backend is spawned at startup.
2. Registers one routing wrapper per tool. Each wrapper forwards the call to
   the lane selected in this proxy process, or fails fast when none is.
3. Adds lane management tools (``spawn_lane``, ``switch_lane``, and so on)
   plus health and recovery helpers.

The selected lane is per proxy process, so every client window gets an
independent view of the same machine-wide fleet.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
import functools
import importlib
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import urlsplit
import warnings

from ansys.aedt.mcp.lanes import registry as reg_mod, spawner
from ansys.aedt.mcp.lanes.client import (
    DEFAULT_PATH,
    BackendAuthError,
    BackendClient,
    LaneAuth,
    aedt_port_from_status,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fastmcp.tools import Tool, ToolResult

    from mcp.types import Tool as McpTool

DEFAULT_SHUTDOWN_TIMEOUT = 10.0
DEFAULT_PROBE_TIMEOUT = 10.0
DEFAULT_HANDSHAKE_TIMEOUT = 5.0
DEFAULT_RECONNECT_TIMEOUT = 180.0
HEARTBEAT_INTERVAL = 10.0
"""Seconds between progress notifications while a routed call is pending."""

ROUTED_TAG = "routed"
LANES_TOOLSET = "lanes"
UNSUPPORTED_BACKEND_ARGS = ("--dynamic-tool-discovery",)
"""Backend arguments the proxy cannot support.

The proxy opens a new MCP session per routed call, so per-session tool
gating would hide the AEDT-only tools forever.
"""

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

_NO_LANE_HINT = (
    "Call spawn_lane('<name>') with a short name describing the work "
    "(e.g. 'patch-antenna', 'filter-tuning'), or list_lanes + switch_lane to join "
    "an existing lane."
)

_AEDT_CONNECT_TOOLS = frozenset({"launch_aedt", "connect_to_aedt"})
_AEDT_DISCONNECT_TOOLS = frozenset({"disconnect_from_aedt"})

_BROKEN_CONNECTION_SIGNATURES = (
    "winerror 127",
    "has no attribute 'grpc_plugin'",
    "failed to connect to aedt via grpc",
    "statuscode.unavailable",
    "already loaded the aedt grpc client",
)
_BROKEN_CONNECTION_HINT = (
    "[ansys-aedt-mcp lanes] This looks like a broken AEDT connection inside the lane's "
    "backend (e.g. another PyAEDT script or toolkit attached to or closed the same "
    "AEDT, or the backend cannot load this AEDT version). Run check_lane to diagnose; "
    "recycle_lane restarts the lane's backend and re-attaches it to its AEDT without "
    "closing AEDT."
)

_INSTALL_VERSION_RE = re.compile(r"[\\/]v(\d{2})(\d)(?=[\\/]|$)")
_RELEASE_RE = re.compile(r"\d{4}\.\d")

LANE_INSTRUCTIONS = """\
## Lanes

This server routes AEDT tool calls through "lanes". Every AEDT tool call is forwarded
to the lane currently selected.

- A lane is an isolated backend that owns at most one AEDT session. Independent lanes
  let you run parallel work (e.g. baseline vs. experiment) without projects interfering.
- No lane is selected when this server starts, so AEDT tools fail with "No lane selected"
  until you pick one. Start with list_lanes: switch_lane to continue on an existing lane
  (lanes are shared by every client on this machine), or spawn_lane to create one.
- Name lanes like git branches, after the work ("patch-antenna", "filter-tuning"),
  never generic ("default", "main", "test") and never ports or numeric ids.
- "AEDT session" means a running ansysedt process, as reported by check_aedt_status.
  It is not the same as a lane. One lane owns one AEDT session.

Typical flow:
1. list_lanes()                  # anything to reuse? then switch_lane("<name>") and skip 2-3
2. spawn_lane("patch-antenna")   # ~5s: creates the lane and routes to it
3. launch_aedt(...)              # ~30-90s: runs INSIDE patch-antenna
4. ... use any AEDT tool normally ...
5. stop_lane("patch-antenna")    # when the work is finished and nobody else uses it

Rules:
- spawn_lane does NOT launch AEDT. Call launch_aedt (or connect_to_aedt) next.
- Use switch_lane to change where subsequent AEDT tool calls land.
- current_lane / list_lanes tell you where you are and what exists.
- stop_lane shuts a lane down; if it was the selected one, no lane is selected afterwards.
- If AEDT calls on a lane start failing oddly (e.g. after an external PyAEDT script or
  toolkit used the same AEDT, or "[WinError 127]"), run check_lane. recycle_lane restarts
  the lane's backend and re-attaches it to the same AEDT without closing AEDT.
- If things get wedged: reap_lanes (soft), reset_lanes (harder), unlock_registry_files.
- "Lane ... is busy" means that lane's backend is blocked in a long AEDT call and your call
  was NOT sent. Don't retry in a tight loop: wait, check current_lane (in_flight), ask the
  user whether AEDT shows a dialog or is solving, or continue on another lane.
"""

LANES_TOOLSET_ENTRY: dict[str, Any] = {
    "name": LANES_TOOLSET,
    "description": (
        "Tools for creating, selecting, diagnosing, and recovering lanes: isolated "
        "PyAEDT-MCP backends that each own one AEDT session."
    ),
    "skill": (
        "Call list_lanes first and switch_lane to reuse a lane, or spawn_lane to create "
        "one named after the work. Then use launch_aedt or connect_to_aedt as usual. Use "
        "check_lane and recycle_lane when a lane misbehaves, and stop_lane when done."
    ),
    "tools": [
        "current_lane",
        "list_lanes",
        "spawn_lane",
        "switch_lane",
        "stop_lane",
        "refresh_aedt_port",
        "check_lane",
        "recycle_lane",
        "reap_lanes",
        "reset_lanes",
        "unlock_registry_files",
    ],
}


@dataclass
class ProxyState:
    """Routing state of one proxy process.

    Parameters
    ----------
    host : str
        Host every lane listens on.
    current_lane : str, optional
        Selected lane, ``None`` until ``spawn_lane`` or ``switch_lane``.
    startup_timeout : float
        Seconds a new lane gets to bind its port.
    probe_timeout : float, optional
        Seconds a lane gets to answer a status probe. ``None`` waits forever.
    handshake_timeout : float
        Seconds a lane gets to answer the MCP handshake of a routed call.
    backend_args : list[str]
        Additional ``ansys-aedt-mcp`` arguments for spawned lanes.
    in_flight : dict[int, tuple[str, str, float]]
        Pending routed calls mapped to their lane, tool, and start time.
    """

    host: str
    current_lane: str | None = None
    startup_timeout: float = spawner.DEFAULT_STARTUP_TIMEOUT
    probe_timeout: float | None = DEFAULT_PROBE_TIMEOUT
    handshake_timeout: float = DEFAULT_HANDSHAKE_TIMEOUT
    backend_args: list[str] = field(default_factory=list)
    in_flight: dict[int, tuple[str, str, float]] = field(default_factory=dict)


def _no_lane_message(tool: str) -> str:
    return f"No lane selected, so {tool!r} was not sent. {_NO_LANE_HINT}"


def _no_target_error() -> dict[str, Any]:
    return {"ok": False, "error": f"No lane given and none selected. {_NO_LANE_HINT}"}


def lane_url(host: str, port: int) -> str:
    """Return the MCP endpoint URL of a lane.

    Parameters
    ----------
    host : str
        Lane host.
    port : int
        Lane HTTP port.

    Returns
    -------
    str
        Endpoint URL.
    """
    return f"http://{host}:{port}{DEFAULT_PATH}"


def is_auth_rejection(exc: BaseException) -> bool:
    """Check whether an exception is, or wraps, a :class:`BackendAuthError`.

    Parameters
    ----------
    exc : BaseException
        Exception to inspect, including exception groups and chained causes.

    Returns
    -------
    bool
        ``True`` if a lane rejected the token.
    """
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        err = stack.pop()
        if id(err) in seen:
            continue
        seen.add(id(err))
        if isinstance(err, BackendAuthError):
            return True
        stack.extend(getattr(err, "exceptions", ()) or ())
        stack.extend(e for e in (err.__cause__, err.__context__) if e is not None)
    return False


def _auth_rejected_message(lane_id: str, where: str) -> str:
    return (
        f"Lane {lane_id!r} backend at {where} rejected this proxy's credentials (HTTP 401). "
        "The token in the registry no longer matches the process on that port: the lane "
        "was probably respawned by a reset, or another process took the port. Nothing "
        "was sent. Run reap_lanes, or stop_lane + spawn_lane to get a fresh backend."
    )


def _unresponsive_message(timeout: float | None) -> str:
    # PyAEDT loads its gRPC client with ctypes.PyDLL, which holds the GIL, so a slow
    # AEDT call freezes the whole backend process, HTTP loop included.
    return (
        f"backend did not answer within {timeout:g}s. It is most likely blocked "
        "inside a long-running or hung AEDT call (PyAEDT gRPC calls hold the "
        "Python GIL, which stalls the entire backend until AEDT returns). "
        "Check that AEDT is not showing a modal dialog or still solving."
    )


def broken_connection_hint(text: str) -> str | None:
    """Return a recovery hint if a tool output reveals a broken AEDT connection.

    Parameters
    ----------
    text : str
        Text output of a routed tool.

    Returns
    -------
    str or None
        Hint pointing at ``check_lane`` and ``recycle_lane``, or ``None``.
    """
    lowered = text.lower()
    if any(signature in lowered for signature in _BROKEN_CONNECTION_SIGNATURES):
        return _BROKEN_CONNECTION_HINT
    return None


def _install_dir_version(path: Any) -> str | None:
    match = _INSTALL_VERSION_RE.search(str(path or ""))
    return f"20{match.group(1)}.{match.group(2)}" if match else None


def diagnose_status(status: dict[str, Any]) -> dict[str, Any]:
    """Classify a lane ``check_aedt_status`` payload.

    The AEDT process view comes from the backend's own ``available_sessions``
    scan; the client view comes from its PyAEDT ``Desktop``.

    Parameters
    ----------
    status : dict[str, Any]
        Parsed ``check_aedt_status`` output.

    Returns
    -------
    dict[str, Any]
        ``verdict`` (``healthy``, ``no_aedt``, ``connection_broken``,
        ``aedt_gone``, or ``version_mismatch``), a ``detail`` sentence, and the
        facts the verdict is based on.
    """
    if "raw" in status:
        return {
            "verdict": "connection_broken",
            "detail": f"check_aedt_status failed: {status['raw']}",
        }
    if not status.get("connected"):
        return {"verdict": "no_aedt", "detail": "The backend is not attached to any AEDT."}

    conn = status.get("connection") or {}
    port = aedt_port_from_status(status)
    sessions = status.get("available_sessions")
    session = next(
        (s for s in sessions or [] if isinstance(s, dict) and s.get("port") == port), None
    )
    process_version = session.get("version") if session else None
    if process_version == "unknown":
        process_version = None
    facts = {
        "aedt_port": port,
        "aedt_pid": session.get("pid") if session else conn.get("process_id"),
        "aedt_version": process_version,
        "client_version": conn.get("version"),
        "client_install_dir": conn.get("install_dir"),
    }

    errors = [str(e) for e in (conn.get("error"), status.get("projects_error")) if e]
    if not isinstance(status.get("projects"), list):
        errors.append(f"project list is {status.get('projects')!r}")
    if port is not None and isinstance(sessions, list) and session is None:
        suffix = f" ({'; '.join(errors)})." if errors else "."
        return {
            **facts,
            "verdict": "aedt_gone",
            "detail": f"No AEDT process serves gRPC port {port} any more{suffix}",
        }
    if errors:
        return {
            **facts,
            "verdict": "connection_broken",
            "detail": "AEDT is running but the backend's PyAEDT connection fails: "
            + "; ".join(errors),
        }
    versions = {
        version
        for version in (
            process_version,
            _install_dir_version(conn.get("install_dir")),
            str(conn.get("version") or "")[:6],
        )
        if version and _RELEASE_RE.fullmatch(version)
    }
    if len(versions) > 1:
        return {
            **facts,
            "verdict": "version_mismatch",
            "detail": (
                f"AEDT on port {port} is {process_version or 'unknown'}, but the backend's "
                f"PyAEDT client reports {conn.get('version')} from {conn.get('install_dir')}."
            ),
        }
    return {**facts, "verdict": "healthy", "detail": f"Attached to AEDT on port {port}."}


def _in_flight_rows(state: ProxyState, lane_id: str | None = None) -> list[dict[str, Any]]:
    now = time.monotonic()
    return [
        {"lane_id": lane, "tool": tool, "elapsed_s": round(now - started, 1)}
        for lane, tool, started in state.in_flight.values()
        if lane_id is None or lane == lane_id
    ]


def _same_install(entry: reg_mod.ServerEntry) -> bool | None:
    """Check whether a lane runs from the same interpreter as this proxy."""
    if not entry.python:
        return None
    return os.path.normcase(Path(entry.python).absolute()) == os.path.normcase(
        Path(sys.executable).absolute()
    )


def _deselect_if_gone(state: ProxyState, result: dict[str, Any]) -> None:
    """Clear the selected lane if its registry entry vanished."""
    lane_id = state.current_lane
    if lane_id is not None and reg_mod.get_entry(lane_id) is None:
        state.current_lane = None
        result["deselected_lane_id"] = lane_id
        result["next_step"] = f"Lane {lane_id!r} is gone and no lane is selected. {_NO_LANE_HINT}"
    result["current_lane_id"] = state.current_lane


def _lane_busy_message(state: ProxyState, lane_id: str, url: str, tool: str, exc: Exception) -> str:
    """Explain why a routed call could not reach its lane."""
    port = urlsplit(url).port
    if port is None or not reg_mod.is_port_open(state.host, port):
        return (
            f"Lane {lane_id!r} backend at {url} is not listening, so {tool!r} was not "
            "sent. Run reap_lanes, then spawn_lane (or switch_lane to another lane)."
        )
    pending = _in_flight_rows(state, lane_id)
    if pending:
        waiting = ", ".join(f"{row['tool']} ({row['elapsed_s']:.0f}s)" for row in pending)
        cause = f"This proxy is still waiting on: {waiting}."
    else:
        cause = (
            "No call from this client is pending on it, so another client or an "
            "earlier call that already timed out on the client side is keeping it busy."
        )
    return (
        f"Lane {lane_id!r} is busy: its backend did not answer the MCP handshake "
        f"within {state.handshake_timeout:g}s, so {tool!r} was NOT sent (no side "
        "effects). The backend is most likely blocked inside a long-running or "
        "hung AEDT call (PyAEDT gRPC calls freeze the whole backend until AEDT "
        f"returns). {cause} Retry shortly, check AEDT for a modal dialog or a "
        "running solve, or use switch_lane / spawn_lane to keep working elsewhere. "
        f"(handshake error: {exc})"
    )


def _error_result(message: str) -> ToolResult:
    from fastmcp.tools import ToolResult

    from mcp.types import TextContent

    return ToolResult(content=[TextContent(type="text", text=message)], is_error=True)


async def _report_heartbeats(lane_id: str, tool: str, started: float) -> None:
    """Send MCP progress notifications while a routed call is pending."""
    from fastmcp.server.dependencies import get_context

    try:
        ctx = get_context()
    except RuntimeError:
        return
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        elapsed = time.monotonic() - started
        with contextlib.suppress(Exception):
            await ctx.report_progress(
                progress=elapsed,
                message=(
                    f"Still waiting on lane {lane_id!r} for {tool} ({elapsed:.0f}s). "
                    "Long AEDT calls block the backend until they return."
                ),
            )


async def probe_lane_status(
    host: str,
    port: int,
    timeout: float | None = DEFAULT_PROBE_TIMEOUT,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Return a lane ``check_aedt_status`` payload within a time bound.

    Parameters
    ----------
    host : str
        Lane host.
    port : int
        Lane HTTP port.
    timeout : float, optional
        Seconds to wait. ``None`` waits forever.
    auth_token : str, optional
        Lane bearer token.

    Returns
    -------
    dict[str, Any]
        Parsed status payload.

    Raises
    ------
    TimeoutError
        If the lane does not answer in time.
    """

    async def _probe() -> dict[str, Any]:
        async with BackendClient(port=port, host=host, auth_token=auth_token) as backend:
            return await backend.check_status()

    return await asyncio.wait_for(_probe(), timeout)


async def probe_lane_aedt_port(
    host: str,
    port: int,
    timeout: float | None = DEFAULT_PROBE_TIMEOUT,
    auth_token: str | None = None,
) -> int | None:
    """Return the AEDT gRPC port a lane is attached to, within a time bound.

    Parameters
    ----------
    host : str
        Lane host.
    port : int
        Lane HTTP port.
    timeout : float, optional
        Seconds to wait. ``None`` waits forever.
    auth_token : str, optional
        Lane bearer token.

    Returns
    -------
    int or None
        AEDT gRPC port, or ``None`` when the lane is not attached.

    Raises
    ------
    TimeoutError
        If the lane does not answer in time.
    """
    return aedt_port_from_status(await probe_lane_status(host, port, timeout, auth_token))


async def _writeback_aedt_port(state: ProxyState, *, probe: bool) -> None:
    """Refresh the AEDT port of the selected lane in the registry.

    Failures are only logged: a stale registry is better than a failed tool call.
    """
    if state.current_lane is None:
        return
    try:
        entry = reg_mod.get_entry(state.current_lane)
        if entry is None:
            return
        port = (
            await probe_lane_aedt_port(
                state.host, entry.http_port, state.probe_timeout, entry.auth_token
            )
            if probe
            else None
        )
        reg_mod.update_aedt_port(entry.server_id, port)
    except Exception:
        logger.debug("AEDT port write-back failed for lane %s", state.current_lane, exc_info=True)


def make_routing_tool(upstream_tool: McpTool, state: ProxyState) -> Tool:
    """Build a tool that forwards ``upstream_tool`` to the selected lane.

    The routed tool keeps the upstream name, description, schemas, title,
    annotations, and tags, so clients see the same tool surface as with the
    regular server.

    Parameters
    ----------
    upstream_tool : mcp.types.Tool
        Upstream tool definition.
    state : ProxyState
        Routing state shared by every tool of the proxy.

    Returns
    -------
    fastmcp.tools.Tool
        Routing tool.
    """
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.tools import Tool, ToolResult

    from mcp.types import TextContent

    name = upstream_tool.name

    async def _forward(arguments: dict[str, Any]) -> ToolResult:
        lane_id = state.current_lane
        if lane_id is None:
            return _error_result(_no_lane_message(name))
        entry = reg_mod.get_entry(lane_id)
        if entry is None:
            return _error_result(
                f"Current lane {lane_id!r} is not in the registry. "
                "Call list_lanes to see what's available."
            )
        url = lane_url(state.host, entry.http_port)
        auth = LaneAuth(entry.auth_token)
        async with contextlib.AsyncExitStack() as stack:
            # The handshake doubles as a liveness check: a frozen backend never answers
            # it, so the call is abandoned before it is queued there.
            try:
                client = await stack.enter_async_context(
                    Client(
                        StreamableHttpTransport(url=url, auth=auth),
                        init_timeout=state.handshake_timeout,
                    )
                )
            except Exception as exc:
                if auth.rejected:
                    return _error_result(_auth_rejected_message(lane_id, url))
                logger.warning("Lane %s unreachable; %s not sent: %s", lane_id, name, exc)
                return _error_result(_lane_busy_message(state, lane_id, url, name, exc))

            started = time.monotonic()
            call_key = id(stack)
            state.in_flight[call_key] = (lane_id, name, started)
            heartbeat = asyncio.create_task(_report_heartbeats(lane_id, name, started))
            try:
                raw = await client.call_tool_mcp(name, arguments)
            except Exception as exc:
                elapsed = time.monotonic() - started
                return _error_result(
                    f"Lane {lane_id!r} backend {url} failed after {elapsed:.0f}s "
                    f"while running {name!r}: {exc}. The call may still "
                    "complete on the backend; check state before retrying."
                )
            finally:
                heartbeat.cancel()
                state.in_flight.pop(call_key, None)

        if not raw.is_error and name in _AEDT_CONNECT_TOOLS | _AEDT_DISCONNECT_TOOLS:
            await _writeback_aedt_port(state, probe=name in _AEDT_CONNECT_TOOLS)

        content = list(raw.content or [])
        hint = broken_connection_hint("\n".join(getattr(p, "text", "") or "" for p in content))
        if hint is not None:
            content.append(TextContent(type="text", text=hint))
        return ToolResult(
            content=content,
            structured_content=raw.structured_content,
            is_error=bool(raw.is_error),
        )

    class _RoutingTool(Tool):
        async def run(self, arguments: dict[str, Any]) -> ToolResult:
            return await _forward(arguments)

    upstream_tags = ((upstream_tool.meta or {}).get("fastmcp") or {}).get("tags") or []
    kwargs: dict[str, Any] = {
        "name": name,
        "title": upstream_tool.title,
        "description": upstream_tool.description or "",
        "parameters": upstream_tool.input_schema or {"type": "object", "properties": {}},
        "annotations": upstream_tool.annotations,
        "tags": {ROUTED_TAG, *upstream_tags},
    }
    if isinstance(upstream_tool.output_schema, dict):
        kwargs["output_schema"] = upstream_tool.output_schema
    return _RoutingTool(**kwargs)


def _parse_backend_flags(backend_args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--include-context", action="store_true")
    flags, _ = parser.parse_known_args(backend_args)
    return flags


def _import_upstream() -> Any:
    """Import the regular server modules and return the server module."""
    with warnings.catch_warnings():
        # Keep third-party deprecation noise out of stderr, which clients show to users.
        warnings.simplefilter("ignore", DeprecationWarning)
        server = importlib.import_module("ansys.aedt.mcp.server")
        for module in ("prompts", "tools", "contexts", "toolsets"):
            importlib.import_module(f"ansys.aedt.mcp.{module}")
    return server


async def list_upstream_tools(backend_args: list[str]) -> list[McpTool]:
    """List the tools a lane started with ``backend_args`` would serve.

    The regular server is imported in-process and the same tag filters as
    its CLI are applied: ``--connect`` hides the connection tools and
    ``--include-context`` adds the context helpers.

    Parameters
    ----------
    backend_args : list[str]
        Additional ``ansys-aedt-mcp`` arguments for the lanes.

    Returns
    -------
    list[mcp.types.Tool]
        Upstream tool definitions.
    """
    flags = _parse_backend_flags(backend_args)
    app = _import_upstream().app
    # Visibility rules stack and the last one wins, so set both groups explicitly.
    (app.disable if flags.connect else app.enable)(tags={"locked_connection"})
    (app.enable if flags.include_context else app.disable)(tags={"pyaedt_context"})
    return [tool.to_mcp_tool() for tool in await app.list_tools()]


def build_instructions() -> str:
    """Return the proxy instructions: the regular system prompt plus lane guidance.

    Returns
    -------
    str
        Server instructions.
    """
    prompts = importlib.import_module("ansys.aedt.mcp.prompts")
    return f"{prompts.build_system_prompt()}\n\n{LANE_INSTRUCTIONS}"


def _register_discovery(server: FastMCP, instructions: str) -> None:
    """Expose the system prompt and the toolset catalogue, extended with lanes."""
    toolsets = importlib.import_module("ansys.aedt.mcp.toolsets")

    @server.prompt(
        name="system_prompt",
        description="System prompt for PyAEDT-MCP, including lane routing guidance.",
    )
    def system_prompt() -> str:
        return instructions

    @server.resource(
        "toolsets://definition", name="toolsets_definition", mime_type="application/json"
    )
    def toolsets_definition() -> list[dict[str, Any]]:
        return [*toolsets.get_toolsets(), LANES_TOOLSET_ENTRY]


def _safe(fn: _F) -> _F:
    """Return errors of a management tool as a payload instead of raising.

    An exception escaping a tool can destabilize the stdio transport and make
    tools disappear from the client.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.exception("Lane tool %s failed", fn.__name__)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return wrapper  # type: ignore[return-value]


def _probe_entries(
    state: ProxyState, entries: list[reg_mod.ServerEntry]
) -> list[tuple[int | None, str | None]]:
    """Probe every lane concurrently and return its AEDT port and probe error."""

    async def _probe(entry: reg_mod.ServerEntry) -> tuple[int | None, str | None]:
        if not reg_mod.is_port_open(state.host, entry.http_port):
            return entry.aedt_gpc_port, "backend is not listening"
        try:
            port = await probe_lane_aedt_port(
                state.host, entry.http_port, state.probe_timeout, entry.auth_token
            )
        except asyncio.TimeoutError:
            return entry.aedt_gpc_port, _unresponsive_message(state.probe_timeout)
        except Exception as exc:
            if is_auth_rejection(exc):
                where = f"port {entry.http_port}"
                return entry.aedt_gpc_port, _auth_rejected_message(entry.server_id, where)
            return entry.aedt_gpc_port, f"{type(exc).__name__}: {exc}"
        return port, None

    async def _probe_all() -> list[tuple[int | None, str | None]]:
        return list(await asyncio.gather(*(_probe(entry) for entry in entries)))

    try:
        return asyncio.run(_probe_all())
    except Exception as exc:
        logger.debug("Lane probe failed", exc_info=True)
        return [(entry.aedt_gpc_port, f"probe failed: {exc}") for entry in entries]


def _reattach(
    handle: spawner.LaneHandle, aedt_port: int, non_graphical: bool
) -> tuple[str, int | None]:
    """Connect a freshly spawned lane to an existing AEDT session."""

    async def _run() -> tuple[str, int | None]:
        async with BackendClient(
            port=handle.port, host=handle.host, auth_token=handle.auth_token
        ) as backend:
            message = await backend.connect_aedt(aedt_port, non_graphical=non_graphical)
            return message, await backend.discover_aedt_port()

    return asyncio.run(asyncio.wait_for(_run(), DEFAULT_RECONNECT_TIMEOUT))


def register_management_tools(server: FastMCP, state: ProxyState) -> None:
    """Add the lane management and recovery tools to ``server``.

    Every tool returns an ``{"ok": False, "error": ...}`` payload instead of
    raising.

    Parameters
    ----------
    server : fastmcp.FastMCP
        Proxy server.
    state : ProxyState
        Routing state shared with the routing tools.
    """
    tags = {LANES_TOOLSET}

    @server.tool(tags=tags, timeout=None)
    @_safe
    def current_lane() -> dict[str, Any]:
        """Return the lane this client currently routes AEDT tool calls to.

        A lane is an isolated backend that owns one AEDT session. It differs
        from the AEDT sessions (running ``ansysedt`` processes) reported by
        ``check_aedt_status``. ``lane_id`` is ``None`` until ``spawn_lane`` or
        ``switch_lane`` selects one. ``in_flight`` lists the routed calls this
        client is still waiting on, which tells a slow AEDT call from a stuck one.

        Returns
        -------
        dict
            Selected lane, its backend details, and pending calls.
        """
        if state.current_lane is None:
            return {
                "lane_id": None,
                "backend": None,
                "in_flight": _in_flight_rows(state),
                "hint": f"No lane selected. {_NO_LANE_HINT}",
            }
        entry = reg_mod.get_entry(state.current_lane)
        return {
            "lane_id": state.current_lane,
            "backend": entry.public_dict() if entry is not None else None,
            "in_flight": _in_flight_rows(state),
        }

    @server.tool(tags=tags, timeout=None)
    @_safe
    def list_lanes() -> dict[str, Any]:
        """List every lane registered on this machine.

        Each lane is probed concurrently for its AEDT gRPC port, so
        ``aedt_gpc_port`` reflects the backend's current state. A lane that
        does not answer within the probe timeout is reported with
        ``responsive: false``, a ``probe_error``, and its cached port.
        ``same_install: false`` means the lane runs other code than this proxy
        (for example, it started before an upgrade); ``recycle_lane`` fixes that.

        Returns
        -------
        dict
            Lanes, their count, and the selected lane.
        """
        entries = reg_mod.list_entries()
        probed = _probe_entries(state, entries)
        rows = []
        for entry, (port, error) in zip(entries, probed, strict=True):
            if error is None and port != entry.aedt_gpc_port:
                entry.aedt_gpc_port = port
                with contextlib.suppress(Exception):
                    reg_mod.update_aedt_port(entry.server_id, port)
            rows.append(
                {
                    **entry.public_dict(),
                    "lane_id": entry.server_id,
                    "http_url": lane_url(state.host, entry.http_port),
                    "listening": reg_mod.is_port_open(state.host, entry.http_port),
                    "responsive": error is None,
                    "probe_error": error,
                    "pid_alive": entry.pid is not None and reg_mod.pid_alive(entry.pid),
                    "same_install": _same_install(entry),
                    "is_current": entry.server_id == state.current_lane,
                }
            )
        return {"lanes": rows, "count": len(rows), "current": state.current_lane}

    @server.tool(tags=tags, timeout=None)
    @_safe
    def spawn_lane(lane_id: str, switch: bool = True) -> dict[str, Any]:
        """Create a new isolated lane. This starts a backend only and takes about 5 s.

        This does NOT launch AEDT. Call ``launch_aedt`` or ``connect_to_aedt``
        next; with ``switch`` that call lands on the new lane. Keeping the two
        steps apart avoids a single call blocking the client for 30-90 s.

        Parameters
        ----------
        lane_id : str
            Unique lane name, chosen like a git branch name after the work, for
            example ``"patch-antenna"`` or ``"filter-tuning"``. Avoid generic
            names such as ``"default"`` and ports.
        switch : bool, default: True
            Whether to route subsequent tool calls to the new lane.

        Returns
        -------
        dict
            Lane details and the next step.
        """
        existing = reg_mod.get_entry(lane_id)
        if existing is not None and reg_mod.is_port_open(state.host, existing.http_port):
            return {
                "ok": False,
                "error": (
                    f"lane_id={lane_id!r} is already registered on port "
                    f"{existing.http_port}. Pick a different name, switch_lane to "
                    "join it, or call stop_lane first."
                ),
            }
        handle = spawner.ensure_backend(
            lane_id,
            host=state.host,
            extra_args=state.backend_args,
            startup_timeout=state.startup_timeout,
        )
        result: dict[str, Any] = {
            "ok": True,
            "lane_id": lane_id,
            "http_port": handle.port,
            "http_url": lane_url(state.host, handle.port),
            "pid": handle.pid,
            "aedt_gpc_port": None,
            "next_step": (
                "Backend is up but has no AEDT yet. "
                f"{'Routing is switched to this lane. ' if switch else ''}"
                "Call launch_aedt (or connect_to_aedt) to start AEDT inside it."
            ),
        }
        if switch:
            state.current_lane = lane_id
            result["switched_to"] = lane_id
        return result

    @server.tool(tags=tags, timeout=None)
    @_safe
    def switch_lane(lane_id: str) -> dict[str, Any]:
        """Route subsequent AEDT tool calls to another registered lane.

        No AEDT is launched.

        Parameters
        ----------
        lane_id : str
            Name of a lane listed by ``list_lanes``.

        Returns
        -------
        dict
            Previous and current lane.
        """
        entry = reg_mod.get_entry(lane_id)
        if entry is None:
            return {
                "ok": False,
                "error": (
                    f"Unknown lane {lane_id!r}. Call list_lanes to see "
                    "what's registered, or spawn_lane to create one."
                ),
            }
        if not reg_mod.is_port_open(state.host, entry.http_port):
            return {
                "ok": False,
                "error": (
                    f"Lane {lane_id!r} is registered but its backend on port "
                    f"{entry.http_port} is not listening. Try reap_lanes or "
                    "stop_lane + spawn_lane."
                ),
            }
        previous, state.current_lane = state.current_lane, lane_id
        return {
            "ok": True,
            "previous_lane_id": previous,
            "current_lane_id": lane_id,
            "http_url": lane_url(state.host, entry.http_port),
            "aedt_gpc_port": entry.aedt_gpc_port,
        }

    @server.tool(tags=tags, timeout=None)
    @_safe
    def stop_lane(lane_id: str, shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> dict:
        """Stop a lane backend and remove it from the registry.

        Lanes are shared machine-wide: stopping one also cuts off other clients
        routed to it. If it was this client's lane, no lane is selected afterwards.

        Parameters
        ----------
        lane_id : str
            Lane name.
        shutdown_timeout : float, default: 10.0
            Seconds to wait for the backend to exit.

        Returns
        -------
        dict
            Whether the lane was removed and its process killed.
        """
        report = reg_mod.stop_entry(lane_id, timeout=shutdown_timeout)
        if report is None:
            return {"ok": True, "lane_id": lane_id, "removed": False, "reason": "not registered"}
        result: dict[str, Any] = {
            "ok": True,
            "lane_id": lane_id,
            "removed": report.removed,
            "killed": report.killed,
            "pid": report.pid,
            "current_lane_id": state.current_lane,
        }
        if state.current_lane == lane_id:
            state.current_lane = None
            result["current_lane_id"] = None
            result["next_step"] = f"That was the selected lane. {_NO_LANE_HINT}"
        return result

    @server.tool(tags=tags, timeout=None)
    @_safe
    def refresh_aedt_port(lane_id: str | None = None) -> dict[str, Any]:
        """Ask a lane for its current AEDT gRPC port and update the registry.

        Parameters
        ----------
        lane_id : str, optional
            Lane name. Defaults to the selected lane.

        Returns
        -------
        dict
            Lane name and AEDT gRPC port.
        """
        target = lane_id or state.current_lane
        if target is None:
            return _no_target_error()
        entry = reg_mod.get_entry(target)
        if entry is None:
            return {"ok": False, "error": f"Unknown lane {target!r}"}
        try:
            port = asyncio.run(
                probe_lane_aedt_port(
                    state.host, entry.http_port, state.probe_timeout, entry.auth_token
                )
            )
        except asyncio.TimeoutError:
            message = _unresponsive_message(state.probe_timeout)
            return {"ok": False, "lane_id": target, "error": f"Lane {target!r}: {message}"}
        except Exception as exc:
            if not is_auth_rejection(exc):
                raise
            where = f"port {entry.http_port}"
            return {"ok": False, "lane_id": target, "error": _auth_rejected_message(target, where)}
        reg_mod.update_aedt_port(target, port)
        return {"ok": True, "lane_id": target, "aedt_gpc_port": port}

    @server.tool(tags=tags, timeout=None)
    @_safe
    def check_lane(lane_id: str | None = None) -> dict[str, Any]:
        """Diagnose a lane end to end: backend, PyAEDT connection, and AEDT process.

        Use it when AEDT calls on a lane fail for no obvious reason, for example
        after an external PyAEDT script attached to or closed the same AEDT,
        after AEDT restarted, or on ``[WinError 127]``. Only the cached AEDT
        port in the registry is updated.

        Verdicts: ``healthy``, ``no_aedt``, ``connection_broken``,
        ``aedt_gone``, ``version_mismatch``, ``busy`` (no answer in time),
        ``backend_down``, and ``auth_rejected``. ``aedt_version`` is read from
        the AEDT process, so it is reliable even when PyAEDT reports another one.

        Parameters
        ----------
        lane_id : str, optional
            Lane name. Defaults to the selected lane.

        Returns
        -------
        dict
            Verdict, details, and the recommended next step.
        """
        target = lane_id or state.current_lane
        if target is None:
            return _no_target_error()
        entry = reg_mod.get_entry(target)
        if entry is None:
            return {"ok": False, "error": f"Unknown lane {target!r}. Call list_lanes."}

        recycle = f"recycle_lane({target!r})"
        result: dict[str, Any] = {
            "ok": True,
            "lane_id": target,
            "in_flight": _in_flight_rows(state, target),
            "same_install": _same_install(entry),
        }
        if result["same_install"] is False:
            result["install_note"] = (
                f"Backend runs from another install ({entry.python}) than this proxy; "
                f"{recycle} restarts it with this proxy's code."
            )
        if not reg_mod.is_port_open(state.host, entry.http_port):
            reattach = (
                f" and re-attaches to AEDT port {entry.aedt_gpc_port}."
                if entry.aedt_gpc_port
                else "."
            )
            return {
                **result,
                "verdict": "backend_down",
                "detail": f"Backend on port {entry.http_port} is not listening.",
                "aedt_port": entry.aedt_gpc_port,
                "next_step": f"{recycle} starts a new backend for this lane{reattach}",
            }
        try:
            status = asyncio.run(
                probe_lane_status(
                    state.host, entry.http_port, state.probe_timeout, entry.auth_token
                )
            )
        except asyncio.TimeoutError:
            return {
                **result,
                "verdict": "busy",
                "detail": _unresponsive_message(state.probe_timeout),
                "aedt_port": entry.aedt_gpc_port,
                "next_step": (
                    "Wait if AEDT is solving or shows a dialog. If it is idle, "
                    f"{recycle} restarts the backend (a call still running on it is lost) "
                    "and re-attaches to the same AEDT."
                ),
            }
        except Exception as exc:
            if not is_auth_rejection(exc):
                raise
            return {
                **result,
                "verdict": "auth_rejected",
                "detail": _auth_rejected_message(target, f"port {entry.http_port}"),
                "next_step": "reap_lanes, or stop_lane + spawn_lane.",
            }

        diagnosis = diagnose_status(status)
        port = diagnosis.get("aedt_port")
        next_steps = {
            "healthy": "Nothing to fix.",
            "no_aedt": (
                "Call launch_aedt, or connect_to_aedt(port=...) to attach to a running AEDT."
            ),
            "connection_broken": (
                f"{recycle} restarts the backend and re-attaches to AEDT on port {port}; "
                "AEDT and its projects stay open."
            ),
            "aedt_gone": (
                f"recycle_lane({target!r}, reconnect=False) gives the lane a clean backend; "
                "then launch_aedt or connect_to_aedt."
            ),
            "version_mismatch": (
                f"{recycle} restarts the backend and re-attaches with the version of the "
                f"AEDT on port {port}."
            ),
        }
        if diagnosis["verdict"] in {"healthy", "no_aedt"}:
            with contextlib.suppress(Exception):
                reg_mod.update_aedt_port(target, aedt_port_from_status(status))
        return {**result, **diagnosis, "next_step": next_steps[diagnosis["verdict"]]}

    @server.tool(tags=tags, timeout=None)
    @_safe
    def recycle_lane(
        lane_id: str | None = None,
        reconnect: bool = True,
        shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> dict[str, Any]:
        """Restart a lane backend, keeping the lane name and its AEDT.

        Fixes a lane whose PyAEDT connection is wedged: ``check_lane`` reports
        ``connection_broken``, ``version_mismatch``, or ``busy`` with an idle
        AEDT, or calls fail with ``[WinError 127]``. The backend and its helpers
        are killed, but AEDT is spared, so AEDT and its open projects keep
        running. A new backend starts under the same name and, with
        ``reconnect``, attaches to the same AEDT. A call still running on the
        old backend is lost. Afterwards AEDT is no longer a child of the
        backend, so ``stop_lane`` leaves it running; call
        ``disconnect_from_aedt(close_desktop=True)`` first if AEDT should close.

        Parameters
        ----------
        lane_id : str, optional
            Lane name. Defaults to the selected lane.
        reconnect : bool, default: True
            Whether to re-attach the new backend to the same AEDT.
        shutdown_timeout : float, default: 10.0
            Seconds to wait for the old backend to exit.

        Returns
        -------
        dict
            Old and new process IDs, the AEDT port, and the next step.
        """
        target = lane_id or state.current_lane
        if target is None:
            return _no_target_error()
        entry = reg_mod.get_entry(target)
        if entry is None:
            return {"ok": False, "error": f"Unknown lane {target!r}. Call list_lanes."}

        aedt_port, non_graphical = entry.aedt_gpc_port, False
        listening = reg_mod.is_port_open(state.host, entry.http_port)
        if listening:
            try:
                status = asyncio.run(
                    probe_lane_status(
                        state.host, entry.http_port, state.probe_timeout, entry.auth_token
                    )
                )
                if "raw" not in status:
                    aedt_port = aedt_port_from_status(status)
                    non_graphical = bool((status.get("connection") or {}).get("non_graphical"))
            except Exception:
                logger.debug("recycle_lane: status probe of %s failed", target, exc_info=True)

        interrupted = _in_flight_rows(state, target)
        pid = entry.pid or spawner.find_listener_pid(entry.http_port)
        if listening:
            if pid is None:
                return {
                    "ok": False,
                    "lane_id": target,
                    "error": f"Cannot find the process listening on port {entry.http_port}.",
                }
            if not reg_mod.kill_keeping_aedt(pid, timeout=shutdown_timeout):
                return {
                    "ok": False,
                    "lane_id": target,
                    "error": f"Could not kill backend pid {pid}.",
                }
            spawner.wait_for_port(state.host, entry.http_port, shutdown_timeout, open_=False)
        reg_mod.remove_entry(target)

        handle = spawner.ensure_backend(
            target,
            host=state.host,
            extra_args=state.backend_args,
            startup_timeout=state.startup_timeout,
        )
        result: dict[str, Any] = {
            "ok": True,
            "lane_id": target,
            "old_pid": pid,
            "pid": handle.pid,
            "http_port": handle.port,
            "interrupted_calls": interrupted,
            "aedt_gpc_port": None,
        }
        if not reconnect or aedt_port is None:
            result["next_step"] = "Fresh backend without AEDT. Call launch_aedt or connect_to_aedt."
            return result
        if not reg_mod.is_port_open("localhost", aedt_port):
            result["next_step"] = (
                f"Nothing listens on AEDT port {aedt_port} any more, so the new backend is "
                "not attached. Call launch_aedt or connect_to_aedt."
            )
            return result
        try:
            message, attached = _reattach(handle, aedt_port, non_graphical)
        except asyncio.TimeoutError:
            result["next_step"] = (
                f"connect_to_aedt(port={aedt_port}) did not finish within "
                f"{DEFAULT_RECONNECT_TIMEOUT:g}s; it may still complete. Run check_lane."
            )
            return result
        except Exception as exc:
            result["ok"] = False
            result["next_step"] = (
                f"The backend restarted but re-attaching to AEDT port {aedt_port} failed "
                f"({exc}). Run check_lane, or call connect_to_aedt / launch_aedt yourself."
            )
            return result
        reg_mod.update_aedt_port(target, attached)
        result["aedt_gpc_port"] = attached
        result["connect_result"] = message.strip()
        if attached != aedt_port:
            result["ok"] = False
            result["next_step"] = (
                f"Re-attaching to AEDT port {aedt_port} failed; see connect_result. "
                "Run check_lane, or call connect_to_aedt / launch_aedt yourself."
            )
        return result

    @server.tool(tags=tags, timeout=None)
    @_safe
    def reap_lanes() -> dict[str, Any]:
        """Remove registry entries whose backend is no longer live.

        Returns
        -------
        dict
            Dropped and kept lanes.
        """
        report = reg_mod.reap_registry(host=state.host)
        result: dict[str, Any] = {"ok": True, "dropped": report.dropped, "kept": report.kept}
        _deselect_if_gone(state, result)
        return result

    @server.tool(tags=tags, timeout=None)
    @_safe
    def reset_lanes(kill_orphans: bool = False, unlock: bool = False) -> dict[str, Any]:
        """Clear the whole registry, optionally killing backends and breaking the lock.

        This is disruptive: it drops every lane, including lanes other clients
        use. Backends left running lose their token with the registry and become
        unreachable, so prefer ``kill_orphans=True``.

        Parameters
        ----------
        kill_orphans : bool, default: False
            Whether to kill every lane process.
        unlock : bool, default: False
            Whether to delete the registry lock file first.

        Returns
        -------
        dict
            What was dropped, killed, and unlocked.
        """
        report = reg_mod.reset_registry(kill_orphans=kill_orphans, unlock=unlock)
        result: dict[str, Any] = {
            "ok": True,
            "dropped": report.dropped,
            "killed": report.killed,
            "failed_to_kill": report.failed_to_kill,
            "unlocked": report.unlocked,
        }
        _deselect_if_gone(state, result)
        return result

    @server.tool(tags=tags, timeout=None)
    @_safe
    def unlock_registry_files() -> dict[str, Any]:
        """Delete the registry lock file.

        Last-resort recovery. Use only when the lock is stuck and no
        legitimate holder exists.

        Returns
        -------
        dict
            Whether a lock file was removed.
        """
        return {"ok": True, "registry_lock_removed": reg_mod.force_unlock()}


async def build_proxy(
    host: str = spawner.DEFAULT_HOST,
    startup_timeout: float = spawner.DEFAULT_STARTUP_TIMEOUT,
    backend_args: list[str] | None = None,
    probe_timeout: float | None = DEFAULT_PROBE_TIMEOUT,
    handshake_timeout: float = DEFAULT_HANDSHAKE_TIMEOUT,
) -> FastMCP:
    """Build the routing proxy server.

    Nothing is spawned: the upstream tools are listed in-process and no lane
    is selected until the client calls ``spawn_lane`` or ``switch_lane``.

    Parameters
    ----------
    host : str, default: "127.0.0.1"
        Host lanes listen on.
    startup_timeout : float, default: 60.0
        Seconds a new lane gets to bind its port.
    backend_args : list[str], optional
        Additional ``ansys-aedt-mcp`` arguments for spawned lanes.
    probe_timeout : float, default: 10.0
        Seconds a lane gets to answer a status probe.
    handshake_timeout : float, default: 5.0
        Seconds a lane gets to answer the MCP handshake of a routed call.

    Returns
    -------
    fastmcp.FastMCP
        Proxy server ready to run over stdio.

    Raises
    ------
    ValueError
        If ``backend_args`` contains an unsupported option.
    """
    from fastmcp import FastMCP

    backend_args = list(backend_args or [])
    unsupported = [arg for arg in backend_args if arg in UNSUPPORTED_BACKEND_ARGS]
    if unsupported:
        raise ValueError(
            f"{', '.join(unsupported)} is not supported for lane backends: the proxy opens "
            "a new MCP session per call, so AEDT-only tools would never be advertised."
        )
    state = ProxyState(
        host=host,
        startup_timeout=startup_timeout,
        probe_timeout=probe_timeout,
        handshake_timeout=handshake_timeout,
        backend_args=backend_args,
    )
    upstream_tools = await list_upstream_tools(backend_args)
    instructions = build_instructions()
    server = FastMCP(name="PyAEDT-MCP (lanes)", instructions=instructions)
    for upstream_tool in upstream_tools:
        server.add_tool(make_routing_tool(upstream_tool, state))
    register_management_tools(server, state)
    _register_discovery(server, instructions)
    logger.info("Lane proxy advertising %d upstream tools.", len(upstream_tools))
    return server
