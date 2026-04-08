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
        assert "25" in result or "24" in result or "23" in result

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


class TestGuidelineToolsIntegration:
    """Integration tests for guideline tools."""

    def test_workflow_guideline_content(self):
        """Test workflow guideline has expected content."""
        from ansys.aedt.mcp.contexts import get_guidelines_for_workflow_overview

        result = get_guidelines_for_workflow_overview()

        # Should contain key workflow sections
        assert "Preprocessing" in result
        assert "Postprocessing" in result
        assert "PyAEDT" in result  # PyAEDT is mentioned in the workflow overview

    def test_hfss_guideline_content(self):
        """Test HFSS guideline has expected content."""
        from ansys.aedt.mcp.contexts import get_guidelines_for_hfss

        result = get_guidelines_for_hfss()

        # Should contain HFSS-specific methods
        assert "wave_port" in result
        assert "radiation_boundary" in result.lower()
        assert "create_setup" in result

    def test_maxwell_guideline_content(self):
        """Test Maxwell guideline has expected content."""
        from ansys.aedt.mcp.contexts import get_guidelines_for_maxwell

        result = get_guidelines_for_maxwell()

        # Should contain Maxwell-specific content
        assert "assign_winding" in result
        assert "Transient" in result
        assert "torque" in result.lower()

    def test_icepak_guideline_content(self):
        """Test Icepak guideline has expected content."""
        from ansys.aedt.mcp.contexts import get_guidelines_for_icepak

        result = get_guidelines_for_icepak()

        # Should contain Icepak-specific content
        assert "assign_solid_block" in result
        assert "temperature" in result.lower()
        assert "opening" in result.lower()
