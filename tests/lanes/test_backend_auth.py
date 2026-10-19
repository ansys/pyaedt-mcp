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

"""Per-lane bearer tokens.

A lane backend rejects callers without its secret, the spawner records the
secret only in the registry, and the routing proxy presents it on every
connection without ever showing it to clients.
"""

import asyncio
import json
import urllib.error
import urllib.request

import pytest

from ansys.aedt.mcp.lanes import proxy
from ansys.aedt.mcp.lanes.backend import TOKEN_ENV

from .conftest import HOST


def _list_tools(port: int, token: str | None):
    from ansys.aedt.mcp.lanes.client import BackendClient

    async def _run():
        async with BackendClient(port=port, host=HOST, auth_token=token) as backend:
            return await backend._client.list_tools()

    return asyncio.run(_run())


def _raw_post(port: int, headers: dict[str, str]) -> int:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310
        f"http://{HOST}:{port}/mcp",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **headers,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


# ---------------------------------------------------------------------------
# Real backend
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_spawner_stores_token_only_in_registry(lane_backend, lane_state):
    handle = lane_backend["handle"]
    entry = lane_state.get_entry("secured")

    assert handle.spawned is True
    assert handle.auth_token
    assert len(handle.auth_token) >= 40
    assert entry.auth_token == handle.auth_token
    assert entry.auth_mode == "token"
    assert handle.log_path.name == f"lane-{handle.port}.log"
    assert handle.auth_token not in handle.log_path.read_text(errors="replace")


@pytest.mark.slow
def test_ensure_backend_reuses_live_lane(lane_backend, lane_state):
    from ansys.aedt.mcp.lanes import spawner

    handle = lane_backend["handle"]
    again = spawner.ensure_backend("secured", host=HOST)

    assert again.spawned is False
    assert again.port == handle.port
    assert again.pid == handle.pid
    assert again.auth_token == handle.auth_token


@pytest.mark.slow
def test_backend_rejects_missing_and_wrong_token(lane_backend):
    port = lane_backend["handle"].port
    for token in (None, "not-the-token"):
        with pytest.raises(Exception) as info:
            _list_tools(port, token)
        assert proxy.is_auth_rejection(info.value), repr(info.value)


@pytest.mark.slow
def test_backend_accepts_correct_token(lane_backend):
    handle = lane_backend["handle"]
    names = {tool.name for tool in _list_tools(handle.port, handle.auth_token)}
    assert "check_aedt_installed" in names


@pytest.mark.slow
def test_backend_guards_host_and_origin(lane_backend):
    handle = lane_backend["handle"]
    auth = {"Authorization": "Bearer " + handle.auth_token}

    assert _raw_post(handle.port, auth) == 200
    assert _raw_post(handle.port, {}) == 401
    assert _raw_post(handle.port, {**auth, "Host": "evil.example"}) == 421
    assert _raw_post(handle.port, {**auth, "Origin": "http://evil.example"}) == 403


@pytest.mark.slow
def test_proxy_routes_with_token_and_hides_it(lane_backend, lane_state):
    from fastmcp import Client, FastMCP
    from mcp.types import Tool as McpTool

    token = lane_backend["handle"].auth_token
    state = proxy.ProxyState(host=HOST, current_lane="secured")
    server = FastMCP(name="test")
    upstream = McpTool(name="check_aedt_installed", input_schema={"type": "object"})
    server.add_tool(proxy.make_routing_tool(upstream, state))
    proxy.register_management_tools(server, state)

    async def _run():
        async with Client(server) as client:
            routed = await client.call_tool_mcp("check_aedt_installed", {})
            lanes = await client.call_tool("list_lanes", {})
            current = await client.call_tool("current_lane", {})
            return routed, lanes.data, current.data

    routed, lanes, current = asyncio.run(_run())

    assert not routed.is_error, routed.content
    (row,) = lanes["lanes"]
    assert row["auth"] == "token"
    assert row["responsive"], row["probe_error"]
    assert row["same_install"] is True
    assert current["backend"]["auth"] == "token"
    assert token not in json.dumps(lanes) + json.dumps(current)


@pytest.mark.slow
def test_proxy_explains_rejected_token(lane_backend, lane_state):
    from fastmcp import Client, FastMCP
    from mcp.types import Tool as McpTool

    entry = lane_state.get_entry("secured")
    good = entry.auth_token
    entry.auth_token = "stale-token"
    lane_state.upsert_entry(entry)
    try:
        state = proxy.ProxyState(host=HOST, current_lane="secured")
        server = FastMCP(name="test")
        upstream = McpTool(name="check_aedt_installed", input_schema={"type": "object"})
        server.add_tool(proxy.make_routing_tool(upstream, state))
        proxy.register_management_tools(server, state)

        async def _run():
            async with Client(server) as client:
                routed = await client.call_tool_mcp("check_aedt_installed", {})
                checked = (await client.call_tool("check_lane", {})).data
                refreshed = (await client.call_tool("refresh_aedt_port", {})).data
                return routed, checked, refreshed

        raw, checked, refreshed = asyncio.run(_run())
    finally:
        entry.auth_token = good
        lane_state.upsert_entry(entry)

    assert raw.is_error
    assert "HTTP 401" in raw.content[0].text
    assert "Nothing was sent" in raw.content[0].text
    assert checked["verdict"] == "auth_rejected"
    assert refreshed["ok"] is False
    assert "HTTP 401" in refreshed["error"]


@pytest.mark.slow
def test_cli_status_redacts_token(lane_backend, lane_state, capsys):
    from ansys.aedt.mcp.lanes import cli

    assert cli.main(["status", "--json"]) == 0
    out = capsys.readouterr().out
    assert lane_backend["handle"].auth_token not in out
    (row,) = json.loads(out)["servers"]
    assert row["auth"] == "token"
    assert row["listening"] is True
    assert row["pid_alive"] is True


@pytest.mark.slow
def test_dashboard_redacts_token(lane_backend, lane_state):
    from ansys.aedt.mcp.lanes.dashboard import collect_status

    status = collect_status()
    (lane,) = status["lanes"]
    assert lane["auth"] == "token"
    assert lane["status"] == "ok"
    assert lane_backend["handle"].auth_token not in json.dumps(status)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_make_verifier_accepts_only_the_token():
    from ansys.aedt.mcp.lanes.backend import CLIENT_ID, make_verifier

    verifier = make_verifier("s3cret")

    accepted = asyncio.run(verifier.verify_token("s3cret"))
    assert accepted is not None
    assert accepted.client_id == CLIENT_ID
    assert asyncio.run(verifier.verify_token("s3cret-")) is None
    assert asyncio.run(verifier.verify_token("")) is None


@pytest.mark.unit
def test_backend_env(monkeypatch):
    from ansys.aedt.mcp.lanes import spawner

    monkeypatch.setenv(TOKEN_ENV, "inherited")
    monkeypatch.delenv("FASTMCP_HTTP_HOST_ORIGIN_PROTECTION", raising=False)

    env = spawner.backend_env("abc")
    assert env[TOKEN_ENV] == "abc"
    assert env["FASTMCP_HTTP_HOST_ORIGIN_PROTECTION"] == "auto"

    monkeypatch.setenv("FASTMCP_HTTP_HOST_ORIGIN_PROTECTION", "off")
    assert spawner.backend_env("abc")["FASTMCP_HTTP_HOST_ORIGIN_PROTECTION"] == "off"


@pytest.mark.unit
def test_backend_command_never_carries_the_token():
    import sys

    from ansys.aedt.mcp.lanes import spawner

    cmd = spawner.backend_command(HOST, 8123, ["--graphical"])

    assert cmd[:3] == [sys.executable, "-m", "ansys.aedt.mcp"]
    assert cmd[3:] == [
        "--transport",
        "http",
        "--http-host",
        HOST,
        "--http-port",
        "8123",
        "--graphical",
    ]


@pytest.mark.unit
def test_is_auth_rejection_unwraps_groups_and_causes():
    from ansys.aedt.mcp.lanes.client import BackendAuthError

    assert proxy.is_auth_rejection(BackendAuthError("401"))
    assert proxy.is_auth_rejection(ExceptionGroup("g", [ValueError(), BackendAuthError("401")]))
    try:
        try:
            raise BackendAuthError("401")
        except BackendAuthError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert proxy.is_auth_rejection(outer)
    assert not proxy.is_auth_rejection(RuntimeError("other"))
