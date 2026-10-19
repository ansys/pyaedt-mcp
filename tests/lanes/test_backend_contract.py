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

"""Contract between the regular server and the lanes proxy.

Lane backends are the regular server run over HTTP. These tests check
that it still honors what the proxy relies on: the CLI flags the spawner
passes, the ``/mcp/`` endpoint, the MCP handshake, and a tool list equal to
the one the proxy advertises in-process.
"""

import asyncio
import subprocess  # nosec B404

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
import pytest

from ansys.aedt.mcp.lanes import proxy, spawner

CANONICAL_TOOL = "check_aedt_installed"


@pytest.mark.slow
def test_cli_exposes_flags_the_spawner_passes(backend_cmd):
    result = subprocess.run(  # nosec B603
        [*backend_cmd, "--help"], check=True, capture_output=True, text=True, timeout=60.0
    )
    help_text = result.stdout + result.stderr
    command = spawner.backend_command("127.0.0.1", 8090, [])
    for flag in (arg for arg in command if arg.startswith("--")):
        assert flag in help_text, f"The regular CLI no longer advertises {flag!r}."
    assert "http" in help_text
    assert "--lanes" in help_text


@pytest.mark.unit
def test_server_exposes_app_and_launcher():
    from fastmcp import FastMCP

    from ansys.aedt.mcp import server

    assert isinstance(server.app, FastMCP)
    assert hasattr(server.app, "auth")
    assert callable(server.launcher)


@pytest.mark.slow
def test_http_server_handshake_and_tools(http_server):
    url = f"http://{http_server['host']}:{http_server['port']}{http_server['path']}"
    assert url == proxy.lane_url(http_server["host"], http_server["port"])

    async def _run():
        async with Client(StreamableHttpTransport(url=url)) as client:
            return await client.list_tools()

    names = {tool.name for tool in asyncio.run(_run())}
    assert len(names) >= 5, sorted(names)
    assert CANONICAL_TOOL in names


@pytest.mark.slow
def test_in_process_tool_list_matches_http_backend(http_server):
    """The tool surface the proxy advertises equals what a real backend serves."""
    url = proxy.lane_url(http_server["host"], http_server["port"])

    async def _http_tools():
        async with Client(StreamableHttpTransport(url=url)) as client:
            return await client.list_tools()

    def _surface(tools):
        return {
            tool.name: (tool.description, tool.input_schema, tool.output_schema) for tool in tools
        }

    in_process = asyncio.run(proxy.list_upstream_tools([]))
    assert _surface(in_process) == _surface(asyncio.run(_http_tools()))
