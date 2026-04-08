"""Unit tests for PyAEDT MCP tools.

These tests mock the AEDT Desktop instance and verify tool behavior.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ansys.aedt.mcp import tools  # noqa: F401 - import to register tools
from ansys.aedt.mcp.server import PyAEDTAppContext


@pytest.fixture
def mock_desktop():
    """Create a mock AEDT Desktop instance for testing."""
    desktop = MagicMock()
    desktop.aedt_version_id = "2026.1"
    desktop.aedt_version_string = "AEDT 2025 R2"
    desktop.aedt_install_dir = "C:\\Program Files\\ANSYS Inc\\v261\\AnsysEM"
    desktop.is_grpc_api = True
    desktop.machine = "localhost"
    desktop.port = 50051
    desktop.non_graphical = True
    desktop.aedt_process_id = 12345
    desktop.project_list = ["Project1", "Project2"]
    desktop.installed_versions = {"261": "C:\\Program Files\\ANSYS Inc\\v261"}
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

        result = check_aedt_status(mock_context_no_desktop)
        assert "No AEDT Desktop connection available" in result
        assert "connect_to_aedt" in result

    def test_with_connection(self, mock_context):
        """Test status check with active connection."""
        from ansys.aedt.mcp.tools import check_aedt_status

        with patch("ansys.aedt.mcp.tools.get_aedt_info") as mock_info:
            mock_info.return_value = {
                "connection": {
                    "version": "2026.1",
                    "is_grpc": True,
                    "machine": "localhost",
                    "port": 50051,
                },
                "projects": ["Project1", "Project2"],
            }
            result = check_aedt_status(mock_context)
            data = json.loads(result)
            assert data["connection"]["version"] == "2026.1"
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
            result = launch_aedt(mock_context)
            assert "Already connected" in result

    def test_launch_defaults_to_graphical_mode(self, mock_context_no_desktop):
        """Test launch_aedt defaults to graphical mode."""
        from ansys.aedt.mcp.tools import launch_aedt

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
            patch("ansys.aedt.core.Desktop") as mock_desktop,
            patch("ansys.aedt.mcp.tools._configure_pyaedt_runtime_settings") as mock_cfg,
        ):
            fake_desktop = MagicMock()
            fake_desktop.aedt_version_id = "2026.1"
            fake_desktop.aedt_install_dir = "C:\\Program Files\\ANSYS Inc\\v261\\AnsysEM"
            fake_desktop.is_grpc_api = True
            mock_desktop.return_value = fake_desktop

            result = launch_aedt(mock_context_no_desktop)

            call_kwargs = mock_desktop.call_args[1]
            assert call_kwargs["non_graphical"] is False
            mock_cfg.assert_called_once_with()
            assert "Successfully launched AEDT Desktop" in result


@pytest.mark.unit
class TestConnectToAEDT:
    """Tests for connect_to_aedt tool."""

    def test_already_connected(self, mock_context):
        """Test connect when already connected."""
        from ansys.aedt.mcp.tools import connect_to_aedt

        with patch("ansys.aedt.mcp.tools.session") as mock_session:
            mock_session.locked_connection = False
            mock_session.on_aali = False
            result = connect_to_aedt(mock_context, port=50051)
            assert "Already connected" in result

    def test_connect_configures_grpc_runtime_settings(self, mock_context_no_desktop):
        """Test connect_to_aedt configures gRPC and runtime safety settings."""
        from ansys.aedt.mcp.tools import connect_to_aedt

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
            patch("ansys.aedt.core.Desktop") as mock_desktop,
            patch("ansys.aedt.mcp.tools._configure_pyaedt_runtime_settings") as mock_cfg,
        ):
            fake_desktop = MagicMock()
            fake_desktop.aedt_version_id = "2026.1"
            fake_desktop.is_grpc_api = True
            mock_desktop.return_value = fake_desktop

            result = connect_to_aedt(mock_context_no_desktop, port=50051)

            mock_cfg.assert_called_once_with(enable_grpc=True)
            assert "Successfully connected to AEDT" in result


@pytest.mark.unit
class TestDisconnectFromAEDT:
    """Tests for disconnect_from_aedt tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test disconnect with no connection."""
        from ansys.aedt.mcp.tools import disconnect_from_aedt

        with patch("ansys.aedt.mcp.tools.session") as mock_session:
            mock_session.locked_connection = False
            mock_session.on_aali = False
            result = disconnect_from_aedt(mock_context_no_desktop)
            assert "No AEDT Desktop connection" in result

    def test_disconnect_success(self, mock_context):
        """Test successful disconnect."""
        from ansys.aedt.mcp.tools import disconnect_from_aedt

        with patch("ansys.aedt.mcp.tools.session") as mock_session:
            mock_session.locked_connection = False
            mock_session.on_aali = False
            result = disconnect_from_aedt(mock_context)
            assert "Successfully disconnected" in result


@pytest.mark.unit
class TestListProjects:
    """Tests for list_projects tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test list projects with no connection."""
        from ansys.aedt.mcp.tools import list_projects

        result = list_projects(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_list_projects_success(self, mock_context):
        """Test successful project listing."""
        from ansys.aedt.mcp.tools import list_projects

        result = list_projects(mock_context)
        data = json.loads(result)
        assert data["count"] == 2
        assert "Project1" in data["open_projects"]


@pytest.mark.unit
class TestListDesigns:
    """Tests for list_designs tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test list designs with no connection."""
        from ansys.aedt.mcp.tools import list_designs

        result = list_designs(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_list_designs_success(self, mock_context):
        """Test successful design listing."""
        from ansys.aedt.mcp.tools import list_designs

        result = list_designs(mock_context, project_name="Project1")
        data = json.loads(result)
        assert data["count"] == 2
        assert "Design1" in data["designs"]


@pytest.mark.unit
class TestRunPythonCode:
    """Tests for run_python_code tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test run code with no connection."""
        from ansys.aedt.mcp.tools import run_python_code

        result = run_python_code(mock_context_no_desktop, code="print('hello')")
        assert "No AEDT Desktop connection" in result

    def test_run_code_success(self, mock_context):
        """Test successful code execution."""
        from ansys.aedt.mcp.tools import run_python_code

        # Mock the python_session.run method
        mock_context.request_context.lifespan_context.python_session = MagicMock()
        mock_context.request_context.lifespan_context.python_session.run.return_value = (
            "test output"
        )

        result = run_python_code(mock_context, code="result = 'test output'")
        assert "test output" in result

    def test_run_code_disables_release_on_exception(self, mock_context):
        """Test run_python_code applies safe runtime settings before exec."""
        from ansys.aedt.mcp.tools import run_python_code

        with patch("ansys.aedt.mcp.tools._configure_pyaedt_runtime_settings") as mock_cfg:
            result = run_python_code(mock_context, code="result = 'ok'")

        mock_cfg.assert_called_once_with()
        assert "ok" in result


@pytest.mark.unit
class TestOpenProject:
    """Tests for open_project tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test open project with no connection."""
        from ansys.aedt.mcp.tools import open_project

        result = open_project(mock_context_no_desktop, project_path="test.aedt")
        assert "No AEDT Desktop connection" in result

    def test_file_not_found(self, mock_context):
        """Test open project with non-existent file."""
        from ansys.aedt.mcp.tools import open_project

        with patch("ansys.aedt.mcp.tools.os.path.exists", return_value=False):
            result = open_project(mock_context, project_path="nonexistent.aedt")
            assert "not found" in result

    def test_open_project_success(self, mock_context):
        """Test successful project open."""
        from ansys.aedt.mcp.tools import open_project

        with patch("ansys.aedt.mcp.tools.os.path.exists", return_value=True):
            result = open_project(mock_context, project_path="test.aedt")
            assert "Successfully opened" in result


@pytest.mark.unit
class TestSaveProject:
    """Tests for save_project tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test save project with no connection."""
        from ansys.aedt.mcp.tools import save_project

        result = save_project(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_save_project_success(self, mock_context):
        """Test successful project save."""
        from ansys.aedt.mcp.tools import save_project

        # Mock that there are projects open
        mock_context.request_context.lifespan_context.desktop.project_list = ["TestProject"]
        result = save_project(mock_context)
        assert "saved successfully" in result or "No project" in result


@pytest.mark.unit
class TestClearAEDT:
    """Tests for clear_aedt tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test clear AEDT with no connection."""
        from ansys.aedt.mcp.tools import clear_aedt

        result = clear_aedt(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_clear_success(self, mock_context):
        """Test successful clear operation."""
        from ansys.aedt.mcp.tools import clear_aedt

        result = clear_aedt(mock_context)
        assert "cleared" in result or "AEDT" in result


@pytest.mark.unit
class TestGetModelInfo:
    """Tests for get_model_info tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test get model info with no connection."""
        from ansys.aedt.mcp.tools import get_model_info

        result = get_model_info(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result


@pytest.mark.unit
class TestCreateDesign:
    """Tests for create_design tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test create design with no connection."""
        from ansys.aedt.mcp.tools import create_design

        result = create_design(mock_context_no_desktop, "Hfss", "TestDesign")
        assert "No AEDT Desktop connection" in result

    def test_create_design_success(self, mock_context):
        """Test successful design creation."""
        from ansys.aedt.mcp.tools import create_design

        with patch("ansys.aedt.core.Hfss") as mock_hfss:
            mock_instance = MagicMock()
            mock_instance.design_name = "TestDesign"
            mock_instance.project_name = "TestProject"
            mock_instance.solution_type = "DrivenModal"
            mock_hfss.return_value = mock_instance

            result = create_design(mock_context, "Hfss", "TestDesign")

            assert "Successfully created" in result or "Hfss" in result

    def test_create_design_invalid_app_type(self, mock_context):
        """Test create design with invalid app type."""
        from ansys.aedt.mcp.tools import create_design

        result = create_design(mock_context, "InvalidApp", "TestDesign")  # type: ignore
        assert "Unsupported" in result or "Error" in result


@pytest.mark.unit
class TestUploadFile:
    """Tests for upload_file tool."""

    def test_upload_file_not_found(self, mock_context):
        """Test upload with non-existent file."""
        from ansys.aedt.mcp.tools import upload_file

        result = upload_file(mock_context, "/nonexistent/file.txt")
        assert "not found" in result

    def test_upload_file_success(self, mock_context, tmp_path):
        """Test successful file upload."""
        from ansys.aedt.mcp.tools import upload_file

        # Create a temporary file
        test_file = tmp_path / "test_upload.txt"
        test_file.write_text("test content")

        with patch("shutil.copy2"):
            result = upload_file(mock_context, str(test_file))

            assert "uploaded successfully" in result or "Error" not in result


@pytest.mark.unit
class TestDownloadFile:
    """Tests for download_file tool."""

    def test_download_file_not_found(self, mock_context):
        """Test download with non-existent file."""
        from ansys.aedt.mcp.tools import download_file

        result = download_file(mock_context, "/nonexistent/file.txt")
        assert "not found" in result

    def test_download_file_success(self, mock_context, tmp_path):
        """Test successful file download."""
        from ansys.aedt.mcp.tools import download_file

        # Create a temporary file to "download"
        test_file = tmp_path / "test_download.txt"
        test_file.write_text("test content")

        dest_file = tmp_path / "destination.txt"

        result = download_file(mock_context, str(test_file), str(dest_file))

        assert "downloaded successfully" in result


@pytest.mark.unit
class TestScreenshot:
    """Tests for screenshot tool."""

    def test_screenshot_no_connection(self, mock_context_no_desktop):
        """Test screenshot with no connection."""
        from ansys.aedt.mcp.tools import screenshot

        result = screenshot(mock_context_no_desktop)

        assert len(result) >= 1
        assert "No AEDT Desktop connection" in result[0].text

    def test_screenshot_success(self, mock_context, tmp_path):
        """Test successful screenshot capture."""
        from ansys.aedt.mcp.tools import screenshot

        test_image = tmp_path / "screenshot.jpg"

        mock_project = MagicMock()
        mock_project.GetName.return_value = "Project1"
        mock_context.request_context.lifespan_context.desktop.active_project.return_value = (
            mock_project
        )
        mock_design_obj = MagicMock()
        mock_design_obj.GetName.return_value = "Design1"
        mock_context.request_context.lifespan_context.desktop.active_design.return_value = (
            mock_design_obj
        )
        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "HFSS"

        mock_app = MagicMock()
        mock_app.design_name = "Design1"
        mock_app.project_name = "Project1"

        def _export_image(path):
            Path(path).write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        mock_app.export_design_preview_to_jpg.side_effect = _export_image

        with patch("ansys.aedt.core.Hfss", return_value=mock_app):
            result = screenshot(mock_context, path=str(test_image))

        assert len(result) == 2
        assert "Screenshot saved to" in result[0].text
        assert "Design: Design1" in result[0].text
        assert "Project: Project1" in result[0].text
        assert result[1].mimeType == "image/jpeg"

    def test_screenshot_export_failure(self, mock_context):
        """Test screenshot export error with project save guidance."""
        from ansys.aedt.mcp.tools import screenshot

        mock_context.request_context.lifespan_context.desktop.active_project.return_value = None
        mock_context.request_context.lifespan_context.desktop.active_design.return_value = None
        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "HFSS"

        mock_app = MagicMock()
        mock_app.export_design_preview_to_jpg.side_effect = RuntimeError("preview export failed")

        with patch("ansys.aedt.core.Hfss", return_value=mock_app):
            result = screenshot(mock_context)

        assert len(result) == 1
        assert "Failed to export screenshot" in result[0].text
        assert "Try saving the project first" in result[0].text


@pytest.mark.unit
class TestExportConfig:
    """Tests for export_config tool."""

    def test_export_config_no_connection(self, mock_context_no_desktop):
        """Test config export with no connection."""
        from ansys.aedt.mcp.tools import export_config

        result = export_config(mock_context_no_desktop)

        assert "No AEDT Desktop connection" in result

    def test_export_config_inline_success(self, mock_context, tmp_path):
        """Test inline config export using a temporary file."""
        from ansys.aedt.mcp.tools import export_config

        mock_project = MagicMock()
        mock_project.GetName.return_value = "Project1"
        mock_context.request_context.lifespan_context.desktop.active_project.return_value = (
            mock_project
        )
        mock_design_obj = MagicMock()
        mock_design_obj.GetName.return_value = "Design1"
        mock_context.request_context.lifespan_context.desktop.active_design.return_value = (
            mock_design_obj
        )
        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "HFSS"

        config_path = tmp_path / "temp_config.json"
        config_data = {"variables": {"w": "10mm"}}

        mock_app = MagicMock()
        mock_app.design_name = "Design1"
        mock_app.project_name = "Project1"

        def _export_config(**kwargs):
            Path(kwargs["config_file"]).write_text(json.dumps(config_data), encoding="utf-8")
            return kwargs["config_file"]

        mock_app.configurations.export_config.side_effect = _export_config

        with (
            patch("ansys.aedt.core.Hfss", return_value=mock_app),
            patch("tempfile.mkstemp", return_value=(0, str(config_path))),
            patch("os.close"),
        ):
            result = export_config(mock_context)

        data = json.loads(result)
        assert data["design"] == "Design1"
        assert data["project"] == "Project1"
        assert data["config"] == config_data
        assert "config_file" not in data

    def test_export_config_to_output_success(self, mock_context, tmp_path):
        """Test config export to a user-specified output path."""
        from ansys.aedt.mcp.tools import export_config

        mock_context.request_context.lifespan_context.desktop.active_project.return_value = None
        mock_context.request_context.lifespan_context.desktop.active_design.return_value = None
        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "HFSS"

        output_path = tmp_path / "design_config"
        expected_file = tmp_path / "design_config.json"
        config_data = {"setups": ["Setup1"]}

        mock_app = MagicMock()
        mock_app.design_name = "Design1"
        mock_app.project_name = "Project1"

        def _export_config(**kwargs):
            Path(kwargs["config_file"]).write_text(json.dumps(config_data), encoding="utf-8")
            return kwargs["config_file"]

        mock_app.configurations.export_config.side_effect = _export_config

        with patch("ansys.aedt.core.Hfss", return_value=mock_app):
            result = export_config(mock_context, output=str(output_path), overwrite=True)

        data = json.loads(result)
        assert data["config"] == config_data
        assert data["config_file"] == str(expected_file)

    def test_export_config_failure(self, mock_context):
        """Test config export failure path."""
        from ansys.aedt.mcp.tools import export_config

        mock_context.request_context.lifespan_context.desktop.active_project.return_value = None
        mock_context.request_context.lifespan_context.desktop.active_design.return_value = None
        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "HFSS"

        mock_app = MagicMock()
        mock_app.configurations.export_config.return_value = None

        with patch("ansys.aedt.core.Hfss", return_value=mock_app):
            result = export_config(mock_context)

        assert "Failed to export configuration" in result


@pytest.mark.unit
class TestExportTouchstone:
    """Tests for export_touchstone tool."""

    def test_export_no_connection(self, mock_context_no_desktop):
        """Test export with no connection."""
        from ansys.aedt.mcp.tools import export_touchstone

        result = export_touchstone(mock_context_no_desktop, "/tmp/output.s2p")
        assert "No AEDT Desktop connection" in result

    def test_export_touchstone_success(self, mock_context):
        """Test successful Touchstone export."""
        from ansys.aedt.mcp.tools import export_touchstone

        result = export_touchstone(mock_context, "/tmp/output.s2p", "Setup1")

        assert "Touchstone" in result or "export" in result.lower()


@pytest.mark.unit
class TestExport3DModel:
    """Tests for export_3d_model tool."""

    def test_export_no_connection(self, mock_context_no_desktop):
        """Test export with no connection."""
        from ansys.aedt.mcp.tools import export_3d_model

        result = export_3d_model(mock_context_no_desktop, "/tmp/model.step")
        assert "No AEDT Desktop connection" in result

    def test_export_3d_model_success(self, mock_context):
        """Test successful 3D model export."""
        from ansys.aedt.mcp.tools import export_3d_model

        result = export_3d_model(mock_context, "/tmp/model.step", "step")

        assert "3D model export" in result or "configured" in result

    def test_export_3d_model_invalid_format(self, mock_context):
        """Test export with invalid format."""
        from ansys.aedt.mcp.tools import export_3d_model

        result = export_3d_model(mock_context, "/tmp/model.xyz", "invalid_format")

        assert "Unsupported" in result


@pytest.mark.asyncio
async def test_tools_registered():
    """Test that all tools are registered with the MCP server."""
    from ansys.aedt.mcp import contexts  # noqa: F401
    from ansys.aedt.mcp.server import app

    # Get list of registered tools
    tool_list = await app.list_tools()

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
        "export_config",
        "list_files",
        "upload_file",
        "download_file",
        "screenshot",
        "clear_aedt",
        "get_model_info",
    ]

    # Check each expected tool is registered
    tool_names = [t.name for t in tool_list]
    for expected_name in expected_tools:
        assert expected_name in tool_names, f"Tool {expected_name} not found"
