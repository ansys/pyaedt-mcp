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

"""Tests for the performance and stability changes."""

import asyncio
import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from ansys.aedt.mcp import tools


@pytest.mark.unit
class TestServerStartup:
    def test_persistent_python_session_is_not_started_by_default(self):
        from ansys.aedt.mcp.server import PyAEDTMCP

        assert PyAEDTMCP()._need_python is False

    def test_persistent_python_session_can_be_requested(self):
        from ansys.aedt.mcp.server import PyAEDTMCP

        assert PyAEDTMCP(need_python=True)._need_python is True


@pytest.mark.unit
class TestRunPythonCode:
    def test_namespace_persists_between_calls(self, mock_context):
        assert tools.run_python_code(mock_context, code="counter = 41") == (
            "Code executed successfully. (No result variable set.)"
        )
        assert tools.run_python_code(mock_context, code="result = counter + 1") == "42"

    def test_stale_result_is_not_returned(self, mock_context):
        tools.run_python_code(mock_context, code="result = 'first'")
        assert "first" not in tools.run_python_code(mock_context, code="x = 1")

    def test_print_output_is_returned(self, mock_context):
        assert tools.run_python_code(mock_context, code="print('hello')") == "hello"
        out = tools.run_python_code(mock_context, code="print('log')\nresult = 5")
        assert out.startswith("5") and "log" in out

    def test_error_reports_line_and_prior_output(self, mock_context):
        code = "print('step 1')\nx = 1\nraise ValueError('boom')"
        out = tools.run_python_code(mock_context, code=code)
        assert out.startswith("Error executing code: ValueError: boom")
        assert "Line 3: raise ValueError('boom')" in out
        assert "step 1" in out

    def test_syntax_error_reports_line(self, mock_context):
        out = tools.run_python_code(mock_context, code="x = 1\nif x\n  pass")
        assert "SyntaxError" in out and "Line 2" in out

    def test_long_output_is_truncated(self, mock_context):
        out = tools.run_python_code(mock_context, code="print('a' * 50000)")
        assert "characters truncated" in out
        assert len(out) < 21000

    @pytest.mark.asyncio
    async def test_disconnect_resets_namespace(self, mock_context):
        tools.run_python_code(mock_context, code="hfss = 'stale app'")
        await tools.disconnect_from_aedt(mock_context, close_desktop=False)
        assert mock_context.request_context.lifespan_context.code_namespace == {}

    def test_clear_aedt_resets_namespace(self, mock_context):
        tools.run_python_code(mock_context, code="hfss = 'stale app'")
        tools.clear_aedt(mock_context)
        assert mock_context.request_context.lifespan_context.code_namespace == {}


@pytest.mark.unit
class TestReadLogTail:
    def test_tail_of_large_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_LOG_TAIL_BYTES", 100)
        log = tmp_path / "pyaedt.log"
        log.write_text("".join(f"line {i:04d}\n" for i in range(1000)), encoding="utf-8")

        lines, total = tools._read_log_tail(log, need_all_lines=False)
        assert total == 1000
        assert lines[-1] == "line 0999\n"
        # The partial first line is dropped; every returned line is complete.
        assert all(line.startswith("line ") for line in lines)
        assert len(lines) < 1000

        all_lines, _ = tools._read_log_tail(log, need_all_lines=True)
        assert len(all_lines) == 1000


@pytest.mark.unit
def test_json_tool_output_is_compact(mock_context_no_desktop):
    with patch("ansys.aedt.mcp.tools.discover_available_aedt_sessions", return_value=[]):
        result = tools.check_aedt_status(mock_context_no_desktop)
    assert "\n" not in result
    assert json.loads(result)["connected"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_does_not_block_event_loop(mock_context_no_desktop):
    """A slow AEDT attach must not freeze the MCP event loop."""

    def slow_desktop(**kwargs):
        time.sleep(0.5)
        desktop = MagicMock()
        desktop.project_list = []
        return desktop

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    task = asyncio.create_task(ticker())
    with (
        patch("ansys.aedt.core.Desktop", side_effect=slow_desktop),
        patch("ansys.aedt.mcp.tools._configure_pyaedt_runtime_settings"),
    ):
        result = await tools.connect_to_aedt(mock_context_no_desktop, port=50051)
    task.cancel()

    assert "Successfully connected" in result
    # A blocked loop would yield 0-1 ticks during the 0.5 s attach.
    assert ticks >= 10
    assert threading.current_thread() is threading.main_thread()
