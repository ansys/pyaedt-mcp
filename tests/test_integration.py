# Copyright (C) 2025 - 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
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

"""Integration tests for PyAEDT MCP server.

These tests require a running AEDT instance with gRPC server enabled.
Run AEDT in gRPC mode: ansysedt.exe -grpcsrv 50051

Mark tests with @pytest.mark.integration to skip in CI.
"""

import json
import os
from unittest.mock import MagicMock

import pytest

# Skip all tests if AEDT is not available
pytestmark = pytest.mark.integration


@pytest.fixture
def aedt_port():
    """Get AEDT port from environment or default."""
    return int(os.environ.get("AEDT_PORT", 50051))


@pytest.fixture
def aedt_machine():
    """Get AEDT machine from environment or default."""
    return os.environ.get("AEDT_MACHINE", "localhost")


@pytest.fixture
def mock_ctx_connected(aedt_port, aedt_machine):
    """Create a context with actual AEDT connection.

    This fixture attempts to connect to a real AEDT instance.
    Skip tests if AEDT is not available.
    """
    try:
        from ansys.aedt.core import Desktop
        from ansys.aedt.core.generic.settings import settings

        settings.use_grpc_api = True

        desktop = Desktop(
            non_graphical=True,
            new_desktop=False,
            machine=aedt_machine,
            port=aedt_port,
        )

        ctx = MagicMock()
        ctx.request_context.lifespan_context.desktop = desktop

        yield ctx

        # Cleanup
        try:
            desktop.release_desktop(close_projects=False)
        except Exception:
            pass

    except Exception as e:
        pytest.skip(f"AEDT not available: {e}")


class TestAEDTConnection:
    """Integration tests for AEDT connection."""

    def test_check_status(self, mock_ctx_connected):
        """Test status check with real AEDT connection."""
        from ansys.aedt.mcp.tools import check_aedt_status

        result = check_aedt_status(mock_ctx_connected)

        # Should return valid JSON
        data = json.loads(result)
        assert "connection" in data
        assert data["connection"]["is_grpc"] is True

    def test_list_projects(self, mock_ctx_connected):
        """Test listing projects."""
        from ansys.aedt.mcp.tools import list_projects

        result = list_projects(mock_ctx_connected)

        data = json.loads(result)
        assert "open_projects" in data
        assert "count" in data


class TestProjectOperations:
    """Integration tests for project operations."""

    def test_create_and_list_project(self, mock_ctx_connected, tmp_path):
        """Test creating and listing a project."""
        mock_ctx_connected.request_context.lifespan_context.desktop

        from ansys.aedt.mcp.tools import run_python_code

        code = """
desktop.odesktop.NewProject()
result = "Project created"
"""
        result = run_python_code(mock_ctx_connected, code=code)

        # List should show the new project
        from ansys.aedt.mcp.tools import list_projects

        result = list_projects(mock_ctx_connected)

        data = json.loads(result)
        assert data["count"] >= 1


class TestDesignOperations:
    """Integration tests for design operations."""

    def test_get_model_info(self, mock_ctx_connected):
        """Test getting model info."""
        from ansys.aedt.mcp.tools import get_model_info

        result = get_model_info(mock_ctx_connected)

        # Even with no active design, should return valid structure
        data = json.loads(result)
        assert "design_name" in data or "error" in data


class TestCodeExecution:
    """Integration tests for code execution."""

    def test_run_simple_code(self, mock_ctx_connected):
        """Test running simple Python code."""
        from ansys.aedt.mcp.tools import run_python_code

        code = """
result = desktop.aedt_version_id
"""
        result = run_python_code(mock_ctx_connected, code=code)

        # Should return the version string
        assert "26" in result or "25" in result or "24" in result or "23" in result

    def test_run_aedt_command(self, mock_ctx_connected):
        """Test running AEDT-specific command."""
        from ansys.aedt.mcp.tools import run_python_code

        code = """
versions = list(desktop.installed_versions.keys()) if hasattr(desktop, 'installed_versions') else []
result = str(versions)
"""
        result = run_python_code(mock_ctx_connected, code=code)

        # Should return a list representation
        assert "[" in result
