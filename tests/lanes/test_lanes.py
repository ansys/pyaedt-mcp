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

"""No preselected lane: the proxy boots without a backend and routes nothing until asked.

The proxy lists the regular tools in-process, applies the same tag filters
as the regular CLI, and only forwards calls once the client picks a lane.
"""

import asyncio
import json

from fastmcp import Client
import pytest

from ansys.aedt.mcp.lanes import proxy

from .conftest import HOST, get_free_port

pytestmark = pytest.mark.unit

CONNECTION_TOOLS = {"launch_aedt", "connect_to_aedt", "disconnect_from_aedt"}


def _names(tools) -> set[str]:
    return {tool.name for tool in tools}


def _list(backend_args: list[str]):
    return asyncio.run(proxy.list_upstream_tools(backend_args))


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


def test_proxy_boots_without_any_backend(isolated_state):
    async def _run():
        server = await proxy.build_proxy(host=HOST)
        async with Client(server) as client:
            tools = await client.list_tools()
            current = (await client.call_tool("current_lane", {})).data
            listed = (await client.call_tool("list_lanes", {})).data
            routed = await client.call_tool_mcp("check_aedt_installed", {})
            refreshed = (await client.call_tool("refresh_aedt_port", {})).data
            prompt = await client.get_prompt("system_prompt")
            toolsets = await client.read_resource("toolsets://definition")
            return tools, current, listed, routed, refreshed, server.instructions, prompt, toolsets

    tools, current, listed, routed, refreshed, instructions, prompt, toolsets = asyncio.run(_run())

    names = _names(tools)
    assert {"check_aedt_installed", "spawn_lane", "list_lanes"} <= names
    assert set(proxy.LANES_TOOLSET_ENTRY["tools"]) <= names
    assert isolated_state.list_entries() == []
    assert current["lane_id"] is None
    assert "spawn_lane" in current["hint"]
    assert listed == {"lanes": [], "count": 0, "current": None}
    assert routed.is_error
    assert "No lane selected, so 'check_aedt_installed' was not sent" in routed.content[0].text
    assert refreshed["ok"] is False
    assert "none selected" in refreshed["error"]
    assert instructions.endswith(proxy.LANE_INSTRUCTIONS)
    assert proxy.LANE_INSTRUCTIONS in prompt.messages[0].content.text
    catalogue = json.loads(toolsets[0].text)
    assert catalogue[-1]["name"] == proxy.LANES_TOOLSET


def test_lane_instructions_never_suggest_generic_names():
    text = proxy.LANE_INSTRUCTIONS.replace('("default", "main", "test")', "")
    assert "default" not in text


def test_routed_tools_keep_upstream_surface():
    upstream = {tool.name: tool for tool in _list([])}

    async def _run():
        server = await proxy.build_proxy(host=HOST)
        async with Client(server) as client:
            return await client.list_tools()

    routed = {tool.name: tool for tool in asyncio.run(_run()) if tool.name in upstream}
    assert routed.keys() == upstream.keys()
    for name, tool in routed.items():
        assert tool.description == upstream[name].description
        assert tool.input_schema == upstream[name].input_schema


def test_connect_flag_hides_connection_tools_without_leaking():
    assert CONNECTION_TOOLS <= _names(_list([]))
    assert not CONNECTION_TOOLS & _names(_list(["--graphical", "--connect"]))
    assert CONNECTION_TOOLS <= _names(_list([]))


def test_include_context_flag_adds_context_tools():
    plain = _names(_list([]))
    with_context = _names(_list(["--include-context"]))
    assert plain < with_context
    assert plain == _names(_list([]))


def test_stop_current_lane_leaves_no_lane_selected(isolated_state):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=get_free_port())
    )
    state = proxy.ProxyState(host=HOST, current_lane="work")

    result = _call(_management_server(state), "stop_lane", {"lane_id": "work"})

    assert result["removed"] is True
    assert result["current_lane_id"] is None
    assert "spawn_lane" in result["next_step"]
    assert state.current_lane is None


def test_stop_other_lane_keeps_selection(isolated_state):
    for name in ("work", "other"):
        isolated_state.upsert_entry(
            isolated_state.ServerEntry(server_id=name, http_port=get_free_port())
        )
    state = proxy.ProxyState(host=HOST, current_lane="work")

    result = _call(_management_server(state), "stop_lane", {"lane_id": "other"})

    assert result["current_lane_id"] == "work"
    assert "next_step" not in result
    assert state.current_lane == "work"


def test_stop_unknown_lane_is_a_no_op(isolated_state):
    state = proxy.ProxyState(host=HOST)

    result = _call(_management_server(state), "stop_lane", {"lane_id": "ghost"})

    assert result == {"ok": True, "lane_id": "ghost", "removed": False, "reason": "not registered"}


def test_reap_deselects_dead_current_lane(isolated_state):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=get_free_port())
    )
    state = proxy.ProxyState(host=HOST, current_lane="work")

    result = _call(_management_server(state), "reap_lanes")

    assert result["dropped"] == ["work"]
    assert result["deselected_lane_id"] == "work"
    assert result["current_lane_id"] is None
    assert state.current_lane is None


def test_reset_lanes_deselects_current_lane(isolated_state):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=get_free_port())
    )
    state = proxy.ProxyState(host=HOST, current_lane="work")

    result = _call(_management_server(state), "reset_lanes")

    assert result["ok"] is True
    assert result["dropped"] == ["work"]
    assert result["deselected_lane_id"] == "work"
    assert state.current_lane is None


def test_unlock_registry_files_tool(isolated_state):
    isolated_state.lockfile_path().touch()
    state = proxy.ProxyState(host=HOST)

    result = _call(_management_server(state), "unlock_registry_files")

    assert result == {"ok": True, "registry_lock_removed": True}


def test_switch_lane_rejects_unknown_and_dead_lanes(isolated_state):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="dead", http_port=get_free_port())
    )
    state = proxy.ProxyState(host=HOST)
    server = _management_server(state)

    unknown = _call(server, "switch_lane", {"lane_id": "ghost"})
    dead = _call(server, "switch_lane", {"lane_id": "dead"})

    assert unknown["ok"] is False
    assert "spawn_lane" in unknown["error"]
    assert dead["ok"] is False
    assert "is not listening" in dead["error"]
    assert state.current_lane is None


def test_switch_lane_selects_listening_lane(isolated_state, frozen_backend):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=frozen_backend, aedt_gpc_port=50051)
    )
    state = proxy.ProxyState(host=HOST, current_lane="old")

    result = _call(_management_server(state), "switch_lane", {"lane_id": "work"})

    assert result["ok"] is True
    assert result["previous_lane_id"] == "old"
    assert result["current_lane_id"] == "work"
    assert result["http_url"] == proxy.lane_url(HOST, frozen_backend)
    assert result["aedt_gpc_port"] == 50051
    assert state.current_lane == "work"


def test_spawn_lane_rejects_a_name_already_listening(isolated_state, frozen_backend):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=frozen_backend)
    )
    state = proxy.ProxyState(host=HOST)

    result = _call(_management_server(state), "spawn_lane", {"lane_id": "work"})

    assert result["ok"] is False
    assert "already registered" in result["error"]
    assert state.current_lane is None


def test_management_tool_errors_become_payloads(isolated_state, monkeypatch):
    def _boom():
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(isolated_state, "force_unlock", _boom)

    result = _call(_management_server(proxy.ProxyState(host=HOST)), "unlock_registry_files")

    assert result == {"ok": False, "error": "RuntimeError: registry exploded"}
