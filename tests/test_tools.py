"""Unit tests for PyAEDT MCP tools.

These tests mock the AEDT Desktop instance and verify tool behavior.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from ansys.aedt.mcp.server import PyAEDTAppContext
from ansys.aedt.mcp import tools  # noqa: F401 - import to register tools


@pytest.fixture
def mock_desktop():
    """Create a mock AEDT Desktop instance for testing."""
    desktop = MagicMock()
    desktop.aedt_version_id = "2025.2"
    desktop.aedt_version_string = "AEDT 2025 R2"
    desktop.aedt_install_dir = "C:\\Program Files\\ANSYS Inc\\v252\\AnsysEM"
    desktop.is_grpc_api = True
    desktop.machine = "localhost"
    desktop.port = 50051
    desktop.non_graphical = True
    desktop.aedt_process_id = 12345
    desktop.project_list = ["Project1", "Project2"]
    desktop.installed_versions = {"252": "C:\\Program Files\\ANSYS Inc\\v252"}
    desktop.release_desktop = MagicMock()
    desktop.save_project = MagicMock()
    desktop.close_project = MagicMock()
    desktop.open_project = MagicMock()
    desktop.design_list = MagicMock(return_value=["Design1", "Design2"])
    return desktop


@pytest.fixture
def app_context(mock_desktop):
    """Create a PyAEDTAppContext with a mock Desktop instance."""
    ctx = PyAEDTAppContext()
    ctx.desktop = mock_desktop
    return ctx


@pytest.fixture
def app_context_no_desktop():
    """Create a PyAEDTAppContext without Desktop (simulating no connection)."""
    ctx = PyAEDTAppContext()
    ctx.desktop = None
    return ctx


@pytest.fixture
def mock_context(app_context):
    """Create a mock Context with PyAEDTAppContext for testing tools."""
    context = MagicMock()
    context.request_context = MagicMock()
    context.request_context.lifespan_context = app_context
    return context


@pytest.fixture
def mock_context_no_desktop(app_context_no_desktop):
    """Create a mock Context without Desktop for testing error handling."""
    context = MagicMock()
    context.request_context = MagicMock()
    context.request_context.lifespan_context = app_context_no_desktop
    return context


@pytest.mark.unit
class TestCheckAEDTStatus:
    """Tests for check_aedt_status tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test status check with no connection."""
        from ansys.aedt.mcp.tools import check_aedt_status
        
        result = check_aedt_status.fn(mock_context_no_desktop)
        assert "No AEDT Desktop connection available" in result
        assert "connect_to_aedt" in result

    def test_with_connection(self, mock_context):
        """Test status check with active connection."""
        from ansys.aedt.mcp.tools import check_aedt_status
        
        with patch("ansys.aedt.mcp.tools.get_aedt_info") as mock_info:
            mock_info.return_value = {
                "connection": {
                    "version": "2025.2",
                    "is_grpc": True,
                    "machine": "localhost",
                    "port": 50051
                },
                "projects": ["Project1", "Project2"]
            }
            result = check_aedt_status.fn(mock_context)
            data = json.loads(result)
            assert data["connection"]["version"] == "2025.2"
            assert data["connection"]["is_grpc"] is True


@pytest.mark.unit
class TestLaunchAEDT:
    """Tests for launch_aedt tool."""

    def test_already_connected(self, mock_context):
        """Test launch when already connected."""
        from ansys.aedt.mcp.tools import launch_aedt
        
        with patch("ansys.aedt.mcp.tools.session") as mock_session:
            mock_session.locked_connection = False
            mock_session.on_aali = False
            result = launch_aedt.fn(mock_context)
            assert "Already connected" in result


@pytest.mark.unit
class TestConnectToAEDT:
    """Tests for connect_to_aedt tool."""

    def test_already_connected(self, mock_context):
        """Test connect when already connected."""
        from ansys.aedt.mcp.tools import connect_to_aedt
        
        with patch("ansys.aedt.mcp.tools.session") as mock_session:
            mock_session.locked_connection = False
            mock_session.on_aali = False
            result = connect_to_aedt.fn(mock_context, port=50051)
            assert "Already connected" in result


@pytest.mark.unit
class TestDisconnectFromAEDT:
    """Tests for disconnect_from_aedt tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test disconnect with no connection."""
        from ansys.aedt.mcp.tools import disconnect_from_aedt
        
        with patch("ansys.aedt.mcp.tools.session") as mock_session:
            mock_session.locked_connection = False
            mock_session.on_aali = False
            result = disconnect_from_aedt.fn(mock_context_no_desktop)
            assert "No AEDT Desktop connection" in result

    def test_disconnect_success(self, mock_context):
        """Test successful disconnect."""
        from ansys.aedt.mcp.tools import disconnect_from_aedt
        
        with patch("ansys.aedt.mcp.tools.session") as mock_session:
            mock_session.locked_connection = False
            mock_session.on_aali = False
            result = disconnect_from_aedt.fn(mock_context)
            assert "Successfully disconnected" in result


@pytest.mark.unit
class TestListProjects:
    """Tests for list_projects tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test list projects with no connection."""
        from ansys.aedt.mcp.tools import list_projects
        
        result = list_projects.fn(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_list_projects_success(self, mock_context):
        """Test successful project listing."""
        from ansys.aedt.mcp.tools import list_projects
        
        result = list_projects.fn(mock_context)
        data = json.loads(result)
        assert data["count"] == 2
        assert "Project1" in data["open_projects"]


@pytest.mark.unit
class TestListDesigns:
    """Tests for list_designs tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test list designs with no connection."""
        from ansys.aedt.mcp.tools import list_designs
        
        result = list_designs.fn(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_list_designs_success(self, mock_context):
        """Test successful design listing."""
        from ansys.aedt.mcp.tools import list_designs
        
        result = list_designs.fn(mock_context, project_name="Project1")
        data = json.loads(result)
        assert data["count"] == 2
        assert "Design1" in data["designs"]


@pytest.mark.unit
class TestRunPythonCode:
    """Tests for run_python_code tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test run code with no connection."""
        from ansys.aedt.mcp.tools import run_python_code
        
        result = run_python_code.fn(mock_context_no_desktop, code="print('hello')")
        assert "No AEDT Desktop connection" in result

    def test_run_code_success(self, mock_context):
        """Test successful code execution."""
        from ansys.aedt.mcp.tools import run_python_code
        
        # Mock the python_session.run method
        mock_context.request_context.lifespan_context.python_session = MagicMock()
        mock_context.request_context.lifespan_context.python_session.run.return_value = "test output"
        
        result = run_python_code.fn(mock_context, code="result = 'test output'")
        assert "test output" in result


@pytest.mark.unit
class TestOpenProject:
    """Tests for open_project tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test open project with no connection."""
        from ansys.aedt.mcp.tools import open_project
        
        result = open_project.fn(mock_context_no_desktop, project_path="test.aedt")
        assert "No AEDT Desktop connection" in result

    def test_file_not_found(self, mock_context):
        """Test open project with non-existent file."""
        from ansys.aedt.mcp.tools import open_project
        
        with patch("ansys.aedt.mcp.tools.os.path.exists", return_value=False):
            result = open_project.fn(mock_context, project_path="nonexistent.aedt")
            assert "not found" in result

    def test_open_project_success(self, mock_context):
        """Test successful project open."""
        from ansys.aedt.mcp.tools import open_project
        
        with patch("ansys.aedt.mcp.tools.os.path.exists", return_value=True):
            result = open_project.fn(mock_context, project_path="test.aedt")
            assert "Successfully opened" in result


@pytest.mark.unit
class TestSaveProject:
    """Tests for save_project tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test save project with no connection."""
        from ansys.aedt.mcp.tools import save_project
        
        result = save_project.fn(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_save_project_success(self, mock_context):
        """Test successful project save."""
        from ansys.aedt.mcp.tools import save_project
        
        # Mock that there are projects open
        mock_context.request_context.lifespan_context.desktop.project_list = ["TestProject"]
        result = save_project.fn(mock_context)
        assert "saved successfully" in result or "No project" in result


@pytest.mark.unit
class TestClearAEDT:
    """Tests for clear_aedt tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test clear AEDT with no connection."""
        from ansys.aedt.mcp.tools import clear_aedt
        
        result = clear_aedt.fn(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_clear_success(self, mock_context):
        """Test successful clear operation."""
        from ansys.aedt.mcp.tools import clear_aedt
        
        result = clear_aedt.fn(mock_context)
        assert "cleared" in result or "AEDT" in result


@pytest.mark.unit
class TestGetModelInfo:
    """Tests for get_model_info tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test get model info with no connection."""
        from ansys.aedt.mcp.tools import get_model_info
        
        result = get_model_info.fn(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result


@pytest.mark.asyncio
async def test_tools_registered():
    """Test that all tools are registered with the MCP server."""
    from ansys.aedt.mcp import contexts, tools  # noqa: F401
    from ansys.aedt.mcp.server import app

    # Get list of registered tools
    tool_list = await app.get_tools()

    # Expected tool names
    expected_tools = [
        "check_aedt_status",
        "check_aedt_installed",
        "launch_aedt",
        "connect_to_aedt",
        "disconnect_from_aedt",
        "run_python_script",
        "run_python_code",
        "list_projects",
        "list_designs",
        "open_project",
        "save_project",
        "create_design",
        "analyze_design",
        "export_results",
        "list_files",
        "upload_file",
        "download_file",
        "clear_aedt",
        "get_model_info",
    ]

    # Check each expected tool is registered
    tool_names = [t.name for t in tool_list.values()]
    for expected_name in expected_tools:
        assert expected_name in tool_names, f"Tool {expected_name} not found"
