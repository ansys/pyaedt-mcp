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

"""Live benchmark: realistic AEDT workflows against an *isolated* AEDT session.

Isolation guarantees
--------------------
- The benchmark starts its own non-graphical AEDT on a free gRPC port and the
  MCP server always targets that explicit port, so already running AEDT
  sessions are never attached, modified, or closed.
- Every ``ansysedt`` process that did not exist before the benchmark started is
  terminated at the end (PIDs that existed before are never touched).
- All projects are written into a temporary directory.

Scenarios
---------
``connect``  Connect to the isolated AEDT and run a typical agent workflow
             (create design, build geometry, list, inspect, validate, save,
             export config, logs, error recovery), repeated ``--iterations``
             times, measuring every tool call and event-loop responsiveness.
``launch``   Let the MCP server launch its own AEDT with ``launch_aedt`` and
             close it with ``disconnect_from_aedt(close_desktop=True)``.

Usage::

    python benchmarks/bench_live.py --src src --label current --out results/current.json
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
import time

from common import DEFAULT_SRC, PingMonitor, Recorder, mcp_client, tool_text, write_results

AEDT_NAMES = {"ansysedt.exe", "ansysedt", "ansysedtsv.exe", "ansysedtsv"}

GEOMETRY_CODE = """
from ansys.aedt.core import Hfss, settings
settings.release_on_exception = False
hfss = Hfss(project={project!r}, design={design!r}, port=aedt_port, new_desktop=False)
hfss.modeler.model_units = "mm"
for i in range(5):
    hfss.modeler.create_box([i * 12, 0, 0], [10, 10, 2], name=f"Box{{i}}", material="copper")
air = hfss.modeler.create_box([-10, -10, -10], [80, 30, 30], name="Air", material="vacuum")
hfss.assign_radiation_boundary_to_objects("Air")
setup = hfss.create_setup("Setup1")
setup.props["Frequency"] = "2GHz"
setup.props["MaximumPasses"] = 1
result = f"objects={{len(hfss.modeler.object_names)}}"
"""

FAILING_CODE = "raise RuntimeError('intentional benchmark failure')"

# Works on both revisions: reuse ``hfss`` when the namespace persisted, else re-create it.
FOLLOWUP_CODE = """
from ansys.aedt.core import Hfss
try:
    app = hfss
    assert app.design_name == {design!r}
except (NameError, AssertionError):
    app = Hfss(project={project!r}, design={design!r}, port=aedt_port, new_desktop=False)
app.modeler.create_cylinder("Z", [0, 20, 0], 3, 5, name="Post", material="copper")
result = f"objects={{len(app.modeler.object_names)}}"
"""


def aedt_pids() -> set[int]:
    """Return the PIDs of every AEDT process on the machine."""
    import psutil

    pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        if (proc.info.get("name") or "").lower() in AEDT_NAMES:
            pids.add(proc.info["pid"])
    return pids


def kill_new_aedt(baseline: set[int]) -> list[int]:
    """Terminate AEDT processes that were not running before the benchmark."""
    import psutil

    killed = []
    for pid in aedt_pids() - baseline:
        try:
            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                child.kill()
            proc.kill()
            killed.append(pid)
        except psutil.Error:
            pass
    return killed


def free_port() -> int:
    """Return a free localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def aedt_executable(version: str | None) -> tuple[str, str]:
    """Resolve the AEDT executable for ``version`` (default: PyAEDT current version)."""
    from ansys.aedt.core.internal.aedt_versions import aedt_versions

    installed = aedt_versions.installed_versions
    version = version or aedt_versions.current_version or aedt_versions.latest_version
    if version not in installed:
        raise SystemExit(f"AEDT {version} is not installed. Installed: {list(installed)}")
    exe = "ansysedt.exe" if sys.platform == "win32" else "ansysedt"
    return version, str(Path(installed[version]) / exe)


def start_isolated_aedt(
    version: str | None, timeout: float = 300.0
) -> tuple[subprocess.Popen, int]:
    """Start a dedicated non-graphical AEDT gRPC server and wait until it listens."""
    _, exe = aedt_executable(version)
    port = free_port()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(  # nosec
        [exe, "-ng", "-grpcsrv", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"AEDT exited early with code {proc.returncode}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return proc, port
        time.sleep(1)
    raise TimeoutError(f"AEDT did not open gRPC port {port} within {timeout} s")


class Step:
    """Call a tool, time it, monitor the event loop, and record failures."""

    def __init__(self, rec: Recorder, client, prefix: str):
        self.rec = rec
        self.client = client
        self.prefix = prefix

    async def __call__(
        self,
        tool: str,
        args: dict | None = None,
        expect: str | None = None,
        name: str | None = None,
    ) -> str:
        metric = f"{self.prefix}.{name or tool}"
        async with PingMonitor(self.client) as mon:
            start = time.perf_counter()
            try:
                result = await self.client.call_tool(tool, args or {}, raise_on_error=False)
                text = tool_text(result)
                failed = bool(getattr(result, "is_error", False))
            except Exception as exc:  # transport level failure
                text, failed = f"EXCEPTION: {exc}", True
            self.rec.add(metric, time.perf_counter() - start)
        self.rec.add(f"loop.max_ping.{metric}", mon.max_latency)
        if expect is not None and expect.lower() not in text.lower():
            failed = True
        self.rec.add("stability.failed_calls", 1.0 if failed else 0.0, unit="count")
        if failed:
            self.rec.notes.append(f"{metric} unexpected result: {text[:300]}")
        return text


async def scenario_connect(
    rec: Recorder, src: Path, version: str | None, iterations: int, workdir: Path
) -> None:
    """Connect to an isolated AEDT and run a representative agent workflow."""
    print("[live] starting isolated AEDT ...")
    start = time.perf_counter()
    proc, port = start_isolated_aedt(version)
    rec.notes.append(f"isolated AEDT pid={proc.pid} port={port}")
    print(f"[live] isolated AEDT pid={proc.pid} port={port} ({time.perf_counter() - start:.1f} s)")

    async with mcp_client(src, [], cwd=workdir) as client:
        step = Step(rec, client, "connect")
        await step("check_aedt_installed")
        await step("check_aedt_status", name="check_aedt_status.disconnected")
        await step("connect_to_aedt", {"port": port, "non_graphical": True}, expect="success")

        for it in range(iterations):
            project = str(workdir / f"bench_{it}.aedt")
            design = f"HfssBench{it}"
            print(f"[live] workflow iteration {it + 1}/{iterations}")
            await step(
                "run_python_code",
                {
                    "code": "from ansys.aedt.core import Hfss\n"
                    f"h = Hfss(project={project!r}, design={design!r}, port=aedt_port, "
                    "new_desktop=False)\nresult = h.design_name"
                },
                expect=design,
                name="run_python_code.create_project",
            )
            await step(
                "create_design",
                {"app_type": "Hfss", "design_name": f"{design}_b"},
                expect="success",
            )
            await step(
                "run_python_code",
                {"code": GEOMETRY_CODE.format(project=Path(project).stem, design=design)},
                expect="objects=6",
                name="run_python_code.geometry",
            )
            await step("check_aedt_status", name="check_aedt_status.connected")
            await step("list_projects")
            await step("list_designs")
            await step("get_model_info")
            # The geometry has no excitation, so AEDT reports a validation error; the
            # metric checks that the tool ran and returned a validation verdict.
            await step("validate_design", {"design_name": design}, expect="Design validation")
            await step(
                "validate_design",
                {"design_name": design},
                expect="Design validation",
                name="validate_design.repeat",
            )
            await step("export_config", {"design": design})
            await step("save_project", expect="saved")
            await step("get_pyaedt_logs", {"tail_lines": 200})
            # Stability: user-code failures must not break the session.
            await step(
                "run_python_code",
                {"code": FAILING_CODE},
                expect="intentional",
                name="run_python_code.error",
            )
            await step(
                "run_python_code",
                {"code": "result = len(desktop.project_list)"},
                name="run_python_code.after_error",
            )
            # Small follow-up edit, as an agent would issue after building geometry.
            # With a persistent namespace the ``hfss`` object from the geometry step can
            # be reused; otherwise the app must be re-created on every call.
            await step(
                "run_python_code",
                {"code": FOLLOWUP_CODE.format(project=Path(project).stem, design=design)},
                expect="objects=7",
                name="run_python_code.followup_edit",
            )

        await step("clear_aedt", expect="cleared")
        await step("disconnect_from_aedt", {"close_desktop": False}, expect="success")

        # Reconnect cost when the session already exists.
        for _ in range(max(1, iterations)):
            await step(
                "connect_to_aedt",
                {"port": port},
                expect="success",
                name="connect_to_aedt.reconnect",
            )
            await step(
                "disconnect_from_aedt",
                {"close_desktop": False},
                expect="success",
                name="disconnect_from_aedt.keep_open",
            )

    proc.kill()


async def scenario_launch(rec: Recorder, src: Path, version: str | None, workdir: Path) -> None:
    """Let the MCP launch and close its own AEDT instance."""
    async with mcp_client(src, [], cwd=workdir) as client:
        step = Step(rec, client, "launch")
        args: dict[str, object] = {"non_graphical": True, "confirm_new_session": True}
        if version:
            args["version"] = version
        print("[live] launch_aedt ...")
        await step("launch_aedt", args, expect="success")
        await step(
            "create_design", {"app_type": "Hfss", "design_name": "LaunchBench"}, expect="success"
        )
        print("[live] disconnect_from_aedt(close_desktop=True) ...")
        await step(
            "disconnect_from_aedt",
            {"close_desktop": True},
            expect="success",
            name="disconnect_from_aedt.close",
        )


async def main() -> None:
    """Run the live benchmark."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--label", default="current")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", default=None, help="AEDT version, for example 2026.1")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument(
        "--scenarios", nargs="+", default=["connect", "launch"], choices=["connect", "launch"]
    )
    args = parser.parse_args()

    rec = Recorder(label=args.label, src=args.src.resolve())
    baseline_pids = aedt_pids()
    workdir = Path(tempfile.mkdtemp(prefix="pyaedt-mcp-bench-"))
    try:
        if "connect" in args.scenarios:
            await scenario_connect(rec, args.src.resolve(), args.version, args.iterations, workdir)
        if "launch" in args.scenarios:
            await scenario_launch(rec, args.src.resolve(), args.version, workdir)
    finally:
        await asyncio.sleep(2)
        killed = kill_new_aedt(baseline_pids)
        if killed:
            rec.notes.append(f"cleanup killed benchmark AEDT pids: {killed}")
        untouched = baseline_pids - aedt_pids()
        if untouched:
            rec.notes.append(f"WARNING: pre-existing AEDT pids disappeared: {sorted(untouched)}")
        write_results(args.out, rec)
        shutil.rmtree(workdir, ignore_errors=True)
        print(f"[live] results written to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
