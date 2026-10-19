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

"""Command line of the opt-in lanes mode (``ansys-aedt-mcp --lanes``).

``ansys-aedt-mcp --lanes [options] [-- backend args]``
    Run the stdio routing proxy. Arguments after ``--`` are forwarded to
    every lane backend, for example ``-- --graphical --include-context``.

``ansys-aedt-mcp --lanes status|reap|reset|unlock|dashboard``
    Inspect or recover the lane registry without starting the proxy, which
    works even when the whole MCP stack is unreachable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from ansys.aedt.mcp.lanes import aedt_compat, dashboard, proxy, registry as reg_mod, spawner

PROG = "ansys-aedt-mcp --lanes"
SUBCOMMANDS = ("status", "stop", "reap", "reset", "unlock", "dashboard")
RESERVED_BACKEND_ARGS = ("--transport", "--http-host", "--http-port", "--lanes")
"""Backend arguments the spawner sets itself, so they cannot be forwarded."""


def _split_backend_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split ``argv`` at the first ``--`` into proxy and backend arguments."""
    if "--" not in argv:
        return list(argv), []
    index = argv.index("--")
    return argv[:index], argv[index + 1 :]


def _build_proxy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Run a stdio routing proxy over shared PyAEDT-MCP HTTP backends (lanes), so "
            "several MCP clients can share or isolate AEDT sessions. Nothing is spawned "
            "until a client calls spawn_lane. Arguments after `--` are forwarded to every "
            f"lane backend. Recovery subcommands: {', '.join(SUBCOMMANDS)}."
        ),
    )
    parser.add_argument(
        "--http-host",
        default=spawner.DEFAULT_HOST,
        help=f"Host lane backends bind to (default: {spawner.DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=spawner.DEFAULT_STARTUP_TIMEOUT,
        help="Seconds a new lane gets to bind its port "
        f"(default: {spawner.DEFAULT_STARTUP_TIMEOUT:g}).",
    )
    parser.add_argument(
        "--probe-timeout",
        type=float,
        default=proxy.DEFAULT_PROBE_TIMEOUT,
        help="Seconds a lane gets to answer a status probe before it is reported "
        f"unresponsive (default: {proxy.DEFAULT_PROBE_TIMEOUT:g}).",
    )
    parser.add_argument(
        "--handshake-timeout",
        type=float,
        default=proxy.DEFAULT_HANDSHAKE_TIMEOUT,
        help="Seconds a lane gets to answer the MCP handshake before a routed call is "
        f"rejected as 'lane busy' without being sent "
        f"(default: {proxy.DEFAULT_HANDSHAKE_TIMEOUT:g}).",
    )
    parser.add_argument(
        "--aedt-version",
        default=None,
        help="Default AEDT version of lane backends: 'latest' (newest installed, the "
        "default), 'pyaedt' (the PyAEDT default), or a version such as 2027.1 or 271. "
        f"Also read from {aedt_compat.VERSION_ENV}.",
    )
    return parser


def _configure_logging() -> None:
    # stdout carries the MCP stdio protocol, so diagnostics go to stderr.
    logger = logging.getLogger("ansys.aedt.mcp.lanes")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def run_proxy(argv: list[str]) -> int:
    """Parse the proxy options and serve the routing proxy over stdio.

    Parameters
    ----------
    argv : list[str]
        Proxy options, optionally followed by ``--`` and backend arguments.

    Returns
    -------
    int
        Process exit code.
    """
    parser = _build_proxy_parser()
    own_args, backend_args = _split_backend_args(argv)
    args = parser.parse_args(own_args)
    unsupported = [arg for arg in backend_args if arg in proxy.UNSUPPORTED_BACKEND_ARGS]
    if unsupported:
        parser.error(
            f"{', '.join(unsupported)} is not supported for lane backends: AEDT-only tools "
            "would never be advertised. Remove it from the forwarded arguments."
        )
    reserved = [arg for arg in backend_args if arg.split("=", 1)[0] in RESERVED_BACKEND_ARGS]
    if reserved:
        parser.error(
            f"{', '.join(reserved)} cannot be forwarded: each lane gets its own HTTP port. "
            "Use --http-host before `--` to choose the host lanes bind to."
        )
    if args.aedt_version is not None:
        try:
            # Lane backends inherit the environment of the proxy.
            os.environ[aedt_compat.VERSION_ENV] = aedt_compat.validate_preference(args.aedt_version)
        except ValueError as exc:
            parser.error(f"--aedt-version: {exc}")

    _configure_logging()

    async def _serve() -> None:
        server = await proxy.build_proxy(
            host=args.http_host,
            startup_timeout=args.startup_timeout,
            backend_args=backend_args,
            probe_timeout=args.probe_timeout,
            handshake_timeout=args.handshake_timeout,
        )
        await server.run_stdio_async(show_banner=False)

    asyncio.run(_serve())
    return 0


def _status(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"{PROG} status", description="Show registered lanes.")
    parser.add_argument("--http-host", default=spawner.DEFAULT_HOST)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)
    servers: list[dict[str, Any]] = [
        {
            **entry.public_dict(),
            "listening": reg_mod.is_port_open(args.http_host, entry.http_port),
            "pid_alive": entry.pid is not None and reg_mod.pid_alive(entry.pid),
        }
        for entry in reg_mod.list_entries()
    ]
    paths = {
        "state_dir": str(reg_mod.state_dir()),
        "registry_path": str(reg_mod.registry_path()),
        "lockfile_path": str(reg_mod.lockfile_path()),
    }
    if args.json:
        print(json.dumps({**paths, "servers": servers}, indent=2, sort_keys=True))
        return 0
    print(f"State dir : {paths['state_dir']}")
    print(f"Registry  : {paths['registry_path']}")
    print(f"Lockfile  : {paths['lockfile_path']}")
    if not servers:
        print("\n(no registered lanes)")
        return 0
    print(f"\n{len(servers)} lane(s):")
    for row in servers:
        print(
            f"  - {row['server_id']:20s} http={row['http_port']:>5} "
            f"aedt={row['aedt_gpc_port'] or '?':>5} pid={row['pid'] or '?':>7} "
            f"listening={row['listening']} pid_alive={row['pid_alive']} auth={row['auth']}"
        )
    return 0


def _stop(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"{PROG} stop", description="Stop a lane and remove it from the registry."
    )
    parser.add_argument("lane_id", help="Name of the lane to stop.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=proxy.DEFAULT_SHUTDOWN_TIMEOUT,
        help="Seconds to wait for the backend to exit "
        f"(default: {proxy.DEFAULT_SHUTDOWN_TIMEOUT:g}).",
    )
    args = parser.parse_args(argv)
    report = reg_mod.stop_entry(args.lane_id, timeout=args.timeout)
    if report is None:
        print(f"Lane {args.lane_id!r} is not registered.")
        return 1
    print(
        f"Stopped lane {report.server_id!r}: killed={report.killed} "
        f"removed={report.removed} pid={report.pid or '?'}"
    )
    return 0


def _reap(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"{PROG} reap", description="Drop dead lanes.")
    parser.add_argument("--http-host", default=spawner.DEFAULT_HOST)
    args = parser.parse_args(argv)
    report = reg_mod.reap_registry(host=args.http_host)
    print(f"Dropped {len(report.dropped)} dead lane(s), kept {len(report.kept)}.")
    for sid in report.dropped:
        print(f"  drop: {sid}")
    return 0


def _reset(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"{PROG} reset", description="Clear the registry.")
    parser.add_argument(
        "--kill", action="store_true", help="Also kill every registered lane process."
    )
    parser.add_argument(
        "--unlock", action="store_true", help="Also delete the registry lock file first."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args(argv)
    if not args.yes:
        extra = (" and kill lane processes" if args.kill else "") + (
            " and delete the lock file" if args.unlock else ""
        )
        answer = input(f"About to wipe the registry at {reg_mod.registry_path()}{extra}. [y/N]: ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Aborted.")
            return 1
    report = reg_mod.reset_registry(kill_orphans=args.kill, unlock=args.unlock)
    print(
        f"Reset done. dropped={len(report.dropped)} killed={len(report.killed)} "
        f"failed_to_kill={len(report.failed_to_kill)} unlocked={report.unlocked}"
    )
    return 0


def _unlock(argv: list[str]) -> int:
    argparse.ArgumentParser(prog=f"{PROG} unlock", description="Delete the lock file.").parse_args(
        argv
    )
    print(f"registry_lock_removed={reg_mod.force_unlock()}")
    return 0


def _dashboard(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"{PROG} dashboard", description="Live, read-only status page for lanes."
    )
    dashboard.add_arguments(parser)
    args = parser.parse_args(argv)
    if args.refresh < dashboard.MIN_REFRESH_SECONDS:
        parser.error(f"--refresh must be >= {dashboard.MIN_REFRESH_SECONDS}")
    return dashboard.run(args.port, args.refresh, open_browser=not args.no_browser)


_HANDLERS = {
    "status": _status,
    "stop": _stop,
    "reap": _reap,
    "reset": _reset,
    "unlock": _unlock,
    "dashboard": _dashboard,
}


def main(argv: list[str]) -> int:
    """Run the lanes command line.

    Parameters
    ----------
    argv : list[str]
        Arguments following ``--lanes``.

    Returns
    -------
    int
        Process exit code.
    """
    if argv and argv[0] in _HANDLERS:
        return _HANDLERS[argv[0]](argv[1:])
    return run_proxy(argv)
