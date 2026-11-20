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

"""Lane probes and routed calls must stay bounded when a backend is frozen.

A backend blocked inside a PyAEDT gRPC call holds the GIL, so its HTTP
socket accepts connections but never answers. The ``frozen_backend``
fixture simulates that with a raw TCP listener.
"""

import asyncio
import re
import time

import pytest

from ansys.aedt.mcp.lanes import proxy

from .conftest import HOST, get_free_port

pytestmark = pytest.mark.unit


def _call_tool(state, name, args=None):
    from fastmcp import Client, FastMCP

    server = FastMCP(name="test")
    proxy.register_management_tools(server, state)

    async def _run():
        async with Client(server) as client:
            return await client.call_tool(name, args or {})

    return asyncio.run(_run()).data


def _routed_server(state, tool_name, properties=None):
    from fastmcp import FastMCP
    from mcp.types import Tool as McpTool

    upstream = McpTool(
        name=tool_name, input_schema={"type": "object", "properties": properties or {}}
    )
    server = FastMCP(name="test")
    server.add_tool(proxy.make_routing_tool(upstream, state))
    proxy.register_management_tools(server, state)
    return server


def _call_routed(server, name, args=None):
    from fastmcp import Client

    async def _run():
        async with Client(server) as client:
            return await client.call_tool_mcp(name, args or {})

    return asyncio.run(_run())


def test_routed_call_to_frozen_backend_fails_fast(isolated_state, frozen_backend):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=frozen_backend)
    )
    state = proxy.ProxyState(host=HOST, current_lane="work", handshake_timeout=1.0)

    start = time.monotonic()
    raw = _call_routed(_routed_server(state, "run_python_code"), "run_python_code")

    assert time.monotonic() - start < 10.0
    assert raw.is_error
    text = raw.content[0].text
    assert "Lane 'work' is busy" in text
    assert "was NOT sent" in text
    assert "another client" in text


def test_routed_call_busy_message_names_pending_call(isolated_state, frozen_backend):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=frozen_backend)
    )
    state = proxy.ProxyState(host=HOST, current_lane="work", handshake_timeout=1.0)
    state.in_flight[1] = ("work", "check_aedt_status", time.monotonic() - 42)

    raw = _call_routed(_routed_server(state, "run_python_code"), "run_python_code")

    assert re.search(r"still waiting on: check_aedt_status \(4\ds\)", raw.content[0].text)


def test_routed_call_to_dead_backend_says_not_listening(isolated_state):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=get_free_port())
    )
    state = proxy.ProxyState(host=HOST, current_lane="work", handshake_timeout=1.0)

    raw = _call_routed(_routed_server(state, "run_python_code"), "run_python_code")

    assert raw.is_error
    assert "is not listening" in raw.content[0].text


def test_routed_call_to_unregistered_lane(isolated_state):
    state = proxy.ProxyState(host=HOST, current_lane="ghost")

    raw = _call_routed(_routed_server(state, "run_python_code"), "run_python_code")

    assert raw.is_error
    assert "'ghost' is not in the registry" in raw.content[0].text


@pytest.mark.slow
def test_routed_slow_call_reports_progress_and_in_flight(isolated_state, slow_backend, monkeypatch):
    from fastmcp import Client

    monkeypatch.setattr(proxy, "HEARTBEAT_INTERVAL", 0.3)
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=slow_backend)
    )
    state = proxy.ProxyState(host=HOST, current_lane="work")
    server = _routed_server(state, "slow", {"seconds": {"type": "number"}})
    progress: list[str | None] = []

    async def _on_progress(progress_value, total, message):
        progress.append(message)

    async def _run():
        async with Client(server, progress_handler=_on_progress) as client:
            call = asyncio.create_task(client.call_tool_mcp("slow", {"seconds": 1.5}))
            await asyncio.sleep(0.8)
            lane = await client.call_tool("current_lane", {})
            return await call, lane.data

    raw, lane = asyncio.run(_run())

    assert not raw.is_error
    assert raw.content[0].text == "done"
    assert [row["tool"] for row in lane["in_flight"]] == ["slow"]
    assert progress
    assert "Still waiting on lane 'work' for slow" in progress[0]
    assert state.in_flight == {}


def test_probe_lane_times_out_on_frozen_backend(frozen_backend):
    start = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(proxy.probe_lane_aedt_port(HOST, frozen_backend, timeout=1.0))
    assert time.monotonic() - start < 10.0


def test_list_lanes_reports_frozen_lane_without_hanging(isolated_state, frozen_backend):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=frozen_backend, aedt_gpc_port=50053)
    )
    state = proxy.ProxyState(host=HOST, current_lane="work", probe_timeout=1.0)

    start = time.monotonic()
    result = _call_tool(state, "list_lanes")
    elapsed = time.monotonic() - start

    assert elapsed < 10.0
    (row,) = result["lanes"]
    assert row["listening"] is True
    assert row["responsive"] is False
    assert row["is_current"] is True
    assert "did not answer within 1s" in row["probe_error"]
    # The cached port is kept and not clobbered in the registry.
    assert row["aedt_gpc_port"] == 50053
    assert isolated_state.get_entry("work").aedt_gpc_port == 50053


def test_list_lanes_probes_lanes_concurrently(isolated_state, frozen_backend):
    for name in ("a", "b", "c"):
        isolated_state.upsert_entry(
            isolated_state.ServerEntry(server_id=name, http_port=frozen_backend)
        )
    state = proxy.ProxyState(host=HOST, current_lane="a", probe_timeout=2.0)

    start = time.monotonic()
    result = _call_tool(state, "list_lanes")
    elapsed = time.monotonic() - start

    assert result["count"] == 3
    assert all(row["responsive"] is False for row in result["lanes"])
    # Sequential probing would take at least 6s.
    assert elapsed < 5.5


def test_refresh_aedt_port_reports_timeout(isolated_state, frozen_backend):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=frozen_backend, aedt_gpc_port=50053)
    )
    state = proxy.ProxyState(host=HOST, current_lane="work", probe_timeout=1.0)

    result = _call_tool(state, "refresh_aedt_port")

    assert result["ok"] is False
    assert "did not answer within 1s" in result["error"]
    assert isolated_state.get_entry("work").aedt_gpc_port == 50053


def test_check_lane_reports_busy_on_frozen_backend(isolated_state, frozen_backend):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=frozen_backend, aedt_gpc_port=50053)
    )
    state = proxy.ProxyState(host=HOST, current_lane="work", probe_timeout=1.0)

    result = _call_tool(state, "check_lane")

    assert result["verdict"] == "busy"
    assert "did not answer within 1s" in result["detail"]
    assert "recycle_lane('work')" in result["next_step"]


def test_cli_rejects_dynamic_tool_discovery(capsys):
    from ansys.aedt.mcp.lanes import cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--", "--dynamic-tool-discovery"])
    assert exc_info.value.code == 2
    assert "--dynamic-tool-discovery is not supported" in capsys.readouterr().err


def test_build_proxy_rejects_dynamic_tool_discovery():
    with pytest.raises(ValueError, match="--dynamic-tool-discovery"):
        asyncio.run(proxy.build_proxy(backend_args=["--dynamic-tool-discovery"]))
