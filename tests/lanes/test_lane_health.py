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

"""Lane health: ``check_lane``, ``recycle_lane``, status diagnosis, and recovery hints."""

import asyncio
from pathlib import Path
import subprocess  # nosec B404
import sys

from fastmcp import Client
import psutil
import pytest

from ansys.aedt.mcp.lanes import proxy

from .conftest import HOST, get_free_port


def _management_server(state):
    from fastmcp import FastMCP

    server = FastMCP(name="test")
    proxy.register_management_tools(server, state)
    return server


def _call(server, name, args=None):
    async def _run():
        async with Client(server) as client:
            return (await client.call_tool(name, args or {})).data

    return asyncio.run(_run())


def _status(**overrides):
    status = {
        "connected": True,
        "connection": {
            "version": "2027.1",
            "install_dir": r"C:\Program Files\ANSYS Inc\v271\AnsysEM",
            "port": 50051,
            "non_graphical": False,
            "process_id": 1234,
        },
        "projects": ["Project1"],
        "available_sessions": [{"pid": 1234, "port": 50051, "version": "2027.1"}],
    }
    status.update(overrides)
    return status


def _verdict(status):
    return proxy.diagnose_status(status)["verdict"]


@pytest.mark.unit
def test_diagnose_healthy():
    diagnosis = proxy.diagnose_status(_status())
    assert diagnosis["verdict"] == "healthy"
    assert diagnosis["aedt_version"] == "2027.1"
    assert diagnosis["aedt_pid"] == 1234
    assert diagnosis["aedt_port"] == 50051


@pytest.mark.unit
def test_diagnose_no_aedt_and_unparsable_status():
    assert _verdict({"connected": False, "available_sessions": []}) == "no_aedt"
    assert _verdict({"raw": "Error checking AEDT status: boom"}) == "connection_broken"


@pytest.mark.unit
def test_diagnose_broken_connection():
    broken = _status(projects_error="[WinError 127] procedure not found")
    assert _verdict(broken) == "connection_broken"
    assert _verdict(_status(projects=None)) == "connection_broken"


@pytest.mark.unit
def test_diagnose_aedt_gone():
    gone = _status(available_sessions=[], projects_error="StatusCode.UNAVAILABLE")
    assert _verdict(gone) == "aedt_gone"


@pytest.mark.unit
def test_diagnose_version_mismatch():
    """A 2027 R1 AEDT driven by a client set up from the 2026 R1 install."""
    conn = {**_status()["connection"], "install_dir": r"C:\Program Files\ANSYS Inc\v261\AnsysEM"}
    assert _verdict(_status(connection=conn)) == "version_mismatch"
    unknown = {**_status()["connection"], "version": "Unknown", "install_dir": "Unknown"}
    assert _verdict(_status(connection=unknown)) == "healthy"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "hinted"),
    [
        (
            "Failed to connect to AEDT at localhost:50051: [WinError 127] The specified procedure",
            True,
        ),
        ("'Desktop' object has no attribute 'grpc_plugin'", True),
        ("Project 'foo' not found", False),
    ],
)
def test_broken_connection_hint(text, hinted):
    hint = proxy.broken_connection_hint(text)
    assert (hint is not None) == hinted
    if hinted:
        assert "check_lane" in hint
        assert "recycle_lane" in hint


@pytest.mark.unit
def test_check_lane_without_lane(isolated_state):
    result = _call(_management_server(proxy.ProxyState(host=HOST)), "check_lane")
    assert result["ok"] is False
    assert "spawn_lane" in result["error"]


@pytest.mark.unit
def test_recycle_lane_without_lane(isolated_state):
    result = _call(_management_server(proxy.ProxyState(host=HOST)), "recycle_lane")
    assert result["ok"] is False
    assert "none selected" in result["error"]


@pytest.mark.unit
def test_check_lane_reports_dead_backend(isolated_state):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=get_free_port(), aedt_gpc_port=50051)
    )
    state = proxy.ProxyState(host=HOST, current_lane="work")

    result = _call(_management_server(state), "check_lane")

    assert result["verdict"] == "backend_down"
    assert "recycle_lane('work')" in result["next_step"]
    assert "50051" in result["next_step"]


@pytest.mark.unit
def test_check_lane_flags_other_install(isolated_state):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(
            server_id="work", http_port=get_free_port(), python=str(Path("elsewhere", "python"))
        )
    )
    state = proxy.ProxyState(host=HOST, current_lane="work")

    result = _call(_management_server(state), "check_lane")

    assert result["same_install"] is False
    assert "recycle_lane('work')" in result["install_note"]


def _parent_with_child():
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess, sys, time;"
        f"p = subprocess.Popen([sys.executable, '-c', {child_code!r}]);"
        "print(p.pid, flush=True); time.sleep(60)"
    )
    parent = subprocess.Popen(  # nosec B603
        [sys.executable, "-c", parent_code], stdout=subprocess.PIPE, text=True
    )
    return parent, int(parent.stdout.readline())


@pytest.mark.unit
@pytest.mark.parametrize(("keep_names", "child_survives"), [((), False), (("python",), True)])
def test_kill_keeping_aedt(isolated_state, keep_names, child_survives):
    """Children are killed unless their name marks them as AEDT (stand-in: python)."""
    parent, child_pid = _parent_with_child()
    try:
        assert isolated_state.kill_keeping_aedt(parent.pid, timeout=10.0, keep_names=keep_names)
        assert isolated_state.pid_alive(child_pid) is child_survives
    finally:
        isolated_state.kill_pid(child_pid, timeout=10.0)
        parent.stdout.close()
        parent.wait(timeout=10.0)


@pytest.mark.slow
def test_recycle_lane_restarts_backend_under_same_name(backend_cmd, isolated_state):
    state = proxy.ProxyState(host=HOST)
    server = _management_server(state)

    spawned = _call(server, "spawn_lane", {"lane_id": "work"})
    assert spawned["ok"], spawned
    assert spawned["switched_to"] == "work"
    assert _call(server, "check_lane")["verdict"] == "no_aedt"
    # The persistent Python session of the backend runs as its child.
    old_children = [p.pid for p in psutil.Process(spawned["pid"]).children(recursive=True)]

    recycled = _call(server, "recycle_lane")
    assert recycled["ok"], recycled
    assert recycled["lane_id"] == "work"
    assert recycled["old_pid"] == spawned["pid"]
    assert recycled["pid"] != spawned["pid"]
    assert recycled["aedt_gpc_port"] is None
    assert "launch_aedt" in recycled["next_step"]
    assert not isolated_state.pid_alive(spawned["pid"])
    assert not any(isolated_state.pid_alive(pid) for pid in old_children)

    entry = isolated_state.get_entry("work")
    assert entry.pid == recycled["pid"]
    assert entry.http_port == recycled["http_port"]
    assert entry.python == sys.executable
    assert state.current_lane == "work"
    assert _call(server, "check_lane")["verdict"] == "no_aedt"
    log_path = Path(entry.log_path)
    assert log_path.name == f"lane-{entry.http_port}.log"
    assert "AEDT version fixes not applied" not in log_path.read_text(errors="replace")

    stopped = _call(server, "stop_lane", {"lane_id": "work"})
    assert stopped["removed"] is True
    assert stopped["killed"] is True
    assert state.current_lane is None
