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
    desktop.aedt_version_string = "AEDT 2026 R1"
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
            result = disconnect_from_aedt(mock_context_no_desktop)
            assert "No AEDT Desktop connection" in result

    def test_disconnect_success(self, mock_context):
        """Test successful disconnect."""
        from ansys.aedt.mcp.tools import disconnect_from_aedt

        with patch("ansys.aedt.mcp.tools.session") as mock_session:
            mock_session.locked_connection = False
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
class TestGetPyAEDTLogs:
    """Tests for get_pyaedt_logs tool."""

    def test_invalid_tail_lines(self, mock_context_no_desktop):
        """Test validation for tail_lines."""
        from ansys.aedt.mcp.tools import get_pyaedt_logs

        result = get_pyaedt_logs(mock_context_no_desktop, tail_lines=0)
        assert "tail_lines must be greater than 0" in result

    def test_log_file_not_resolved(self, mock_context_no_desktop):
        """Test response when no PyAEDT log file can be found."""
        from ansys.aedt.mcp.tools import get_pyaedt_logs

        with patch("ansys.aedt.mcp.tools._resolve_pyaedt_log_file", return_value=None):
            result = get_pyaedt_logs(mock_context_no_desktop)
        assert "could not be resolved" in result

    def test_get_logs_tail_and_filter(self, mock_context_no_desktop, tmp_path):
        """Test successful log retrieval with tail and text filter."""
        from ansys.aedt.mcp.tools import get_pyaedt_logs

        log_file = tmp_path / "pyaedt_test.log"
        log_file.write_text(
            "INFO startup\n" "ERROR solver failed\n" "INFO retry\n" "ERROR solver recovered\n",
            encoding="utf-8",
        )

        with patch(
            "ansys.aedt.mcp.tools._resolve_pyaedt_log_file",
            return_value=str(log_file),
        ):
            result = get_pyaedt_logs(mock_context_no_desktop, tail_lines=1, contains="error")

        data = json.loads(result)
        assert data["log_file"] == str(log_file.resolve())
        assert data["matched_lines"] == 2
        assert data["returned_lines"] == 1
        assert "ERROR solver recovered" in data["logs"]


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

        with (
            patch("ansys.aedt.core.get_pyaedt_app", return_value=mock_app),
            patch(
                "ansys.aedt.mcp.tools._open_file_in_default_viewer", return_value=None
            ) as mock_open_viewer,
        ):
            result = screenshot(mock_context, path=str(test_image))

        assert len(result) == 2
        assert "Screenshot saved to" in result[0].text
        assert "Design: Design1" in result[0].text
        assert "Project: Project1" in result[0].text
        assert "Opened screenshot in the default image viewer." in result[0].text
        assert result[1].mimeType == "image/jpeg"
        mock_open_viewer.assert_called_once_with(test_image.resolve())

    def test_screenshot_viewer_failure_does_not_fail_capture(self, mock_context, tmp_path):
        """Test screenshot still succeeds when viewer launch fails."""
        from ansys.aedt.mcp.tools import screenshot

        test_image = tmp_path / "screenshot.jpg"

        mock_context.request_context.lifespan_context.desktop.active_project.return_value = None
        mock_context.request_context.lifespan_context.desktop.active_design.return_value = None
        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "HFSS"

        mock_app = MagicMock()
        mock_app.design_name = "Design1"
        mock_app.project_name = "Project1"
        mock_app.export_design_preview_to_jpg.side_effect = lambda path: Path(path).write_bytes(
            b"\xff\xd8\xff" + b"\x00" * 100
        )

        with (
            patch("ansys.aedt.core.get_pyaedt_app", return_value=mock_app),
            patch(
                "ansys.aedt.mcp.tools._open_file_in_default_viewer",
                return_value="Viewer launch failed: test error",
            ),
        ):
            result = screenshot(mock_context, path=str(test_image))

        assert len(result) == 2
        assert "Screenshot saved to" in result[0].text
        assert "Viewer launch failed: test error" in result[0].text

    def test_screenshot_export_failure(self, mock_context):
        """Test screenshot export error with project save guidance."""
        from ansys.aedt.mcp.tools import screenshot

        mock_context.request_context.lifespan_context.desktop.active_project.return_value = None
        mock_context.request_context.lifespan_context.desktop.active_design.return_value = None
        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "HFSS"

        mock_app = MagicMock()
        mock_app.export_design_preview_to_jpg.side_effect = RuntimeError("preview export failed")

        with patch("ansys.aedt.core.get_pyaedt_app", return_value=mock_app):
            result = screenshot(mock_context)

        assert len(result) == 1
        assert "Failed to export screenshot" in result[0].text
        assert "Try saving the project first" in result[0].text


@pytest.mark.unit
class TestAnalyzeDesign:
    """Tests for analyze_design tool."""

    def test_analyze_design_uses_app_level_api(self, mock_context):
        """Test design-level analysis forwards PyAEDT solve options."""
        from ansys.aedt.mcp.tools import analyze_design

        mock_app = MagicMock()
        mock_app.project_name = "Project1"
        mock_app.design_name = "Design1"
        mock_app.analyze.return_value = True

        with patch("ansys.aedt.core.get_pyaedt_app", return_value=mock_app) as mock_get_app:
            result = analyze_design(
                mock_context,
                setup_name="Setup1",
                project_name="Project1",
                design_name="Design1",
                num_cores=8,
                num_tasks=2,
                num_gpus=1,
                acf_file="C:/temp/config.acf",
                use_auto_settings=False,
                solve_in_batch=True,
                machine="remote-host",
                run_in_thread=True,
                revert_to_initial_mesh=True,
                blocking=False,
            )

        mock_get_app.assert_called_once_with(
            project_name="Project1",
            design_name="Design1",
            desktop=mock_context.request_context.lifespan_context.desktop,
        )
        mock_app.analyze.assert_called_once_with(
            setup="Setup1",
            cores=8,
            tasks=2,
            gpus=1,
            acf_file="C:/temp/config.acf",
            use_auto_settings=False,
            solve_in_batch=True,
            machine="remote-host",
            run_in_thread=True,
            revert_to_initial_mesh=True,
            blocking=False,
        )
        assert "Analysis completed successfully" in result
        assert "Project: Project1" in result
        assert "Design: Design1" in result
        assert "Setup: Setup1" in result
        assert "Mode: batch" in result

    def test_analyze_design_can_run_desktop_analyze_all(self, mock_context):
        """Test explicit desktop-wide analysis path."""
        from ansys.aedt.mcp.tools import analyze_design

        mock_context.request_context.lifespan_context.desktop.analyze_all.return_value = True

        result = analyze_design(
            mock_context,
            project_name="Project1",
            design_name="Design1",
            analyze_all_designs=True,
        )

        mock_context.request_context.lifespan_context.desktop.analyze_all.assert_called_once_with(
            project="Project1",
            design="Design1",
        )
        assert "Analysis completed successfully" in result
        assert "Mode: desktop analyze_all" in result

    def test_analyze_design_rejects_setup_with_desktop_analyze_all(self, mock_context):
        """Test invalid analyze_all usage with a specific setup."""
        from ansys.aedt.mcp.tools import analyze_design

        result = analyze_design(
            mock_context,
            setup_name="Setup1",
            analyze_all_designs=True,
        )

        mock_context.request_context.lifespan_context.desktop.analyze_all.assert_not_called()
        assert "setup_name cannot be used" in result


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
            patch("ansys.aedt.core.get_pyaedt_app", return_value=mock_app),
            patch("tempfile.mkstemp", return_value=(0, str(config_path))),
            patch("os.close"),
            patch("os.remove"),
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

        with patch("ansys.aedt.core.get_pyaedt_app", return_value=mock_app):
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

        with patch("ansys.aedt.core.get_pyaedt_app", return_value=mock_app):
            result = export_config(mock_context)

        assert "Failed to export configuration" in result


@pytest.mark.asyncio
async def test_tools_registered():
    """Test that all tools are registered with the MCP server."""
    from ansys.aedt.mcp.server import app

    # Get list of registered tools
    tool_list = await app.list_tools()

    # Expected tool names
    expected_tools = [
        "check_aedt_status",
        "get_pyaedt_logs",
        "check_aedt_installed",
        "launch_aedt",
        "connect_to_aedt",
        "disconnect_from_aedt",
        "run_python_script",
        "run_python_code",
        "list_designs",
        "open_project",
        "save_project",
        "create_design",
        "analyze_design",
        "export_results",
        "export_config",
        "screenshot",
        "clear_aedt",
        "get_model_info",
    ]

    # Check each expected tool is registered
    tool_names = [t.name for t in tool_list]
    for expected_name in expected_tools:
        assert expected_name in tool_names, f"Tool {expected_name} not found"


@pytest.mark.unit
class TestCheckAEDTInstalled:
    """Tests for check_aedt_installed tool."""

    def test_docker_endpoint_reachable(self, mock_context):
        """Test Docker path when gRPC endpoint is reachable."""
        from ansys.aedt.mcp.tools import check_aedt_installed

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=True),
            patch(
                "ansys.aedt.mcp.tools._probe_grpc_endpoint",
                return_value={"reachable": True, "host": "myhost", "port": 50052, "error": None},
            ),
            patch.dict("os.environ", {"AEDT_MACHINE": "myhost", "AEDT_PORT": "50052"}),
        ):
            result = check_aedt_installed(mock_context)

        assert "Running inside Docker" in result
        assert "myhost:50052" in result
        assert "reachable" in result

    def test_docker_endpoint_not_reachable(self, mock_context):
        """Test Docker path when gRPC endpoint is NOT reachable."""
        from ansys.aedt.mcp.tools import check_aedt_installed

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=True),
            patch(
                "ansys.aedt.mcp.tools._probe_grpc_endpoint",
                return_value={
                    "reachable": False,
                    "host": "myhost",
                    "port": 50052,
                    "error": "connection refused",
                },
            ),
            patch.dict("os.environ", {"AEDT_MACHINE": "myhost", "AEDT_PORT": "50052"}),
        ):
            result = check_aedt_installed(mock_context)

        assert "NOT reachable" in result
        assert "ansysedt.exe" in result

    def test_native_installed_versions(self, mock_context):
        """Test native path with installed AEDT versions found."""
        from ansys.aedt.mcp.tools import check_aedt_installed

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
            patch(
                "ansys.aedt.mcp.tools._resolve_aedt_executable",
                return_value=("261", Path("C:/ANSYS/v261/AnsysEM/ansysedt.exe")),
            ),
        ):
            result = check_aedt_installed(mock_context)

        assert "AEDT is installed" in result
        assert "261" in result

    def test_native_not_installed(self, mock_context):
        """Test native path when AEDT is not found."""
        from ansys.aedt.mcp.tools import check_aedt_installed

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
            patch(
                "ansys.aedt.mcp.tools._resolve_aedt_executable",
                side_effect=RuntimeError("No AEDT versions found installed on this system."),
            ),
        ):
            result = check_aedt_installed(mock_context)

        assert "no aedt versions found installed" in result.lower()

    def test_native_exception(self, mock_context):
        """Test native path when an exception occurs."""
        from ansys.aedt.mcp.tools import check_aedt_installed

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
            patch(
                "ansys.aedt.mcp.tools._resolve_aedt_executable",
                side_effect=ImportError("no module"),
            ),
        ):
            result = check_aedt_installed(mock_context)

        assert "Error" in result


@pytest.mark.unit
class TestRunPythonScript:
    """Tests for run_python_script tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test run script with no connection."""
        from ansys.aedt.mcp.tools import run_python_script

        result = run_python_script(mock_context_no_desktop, script_path="test.py")
        assert "No AEDT Desktop connection" in result

    def test_script_not_found(self, mock_context):
        """Test run script with non-existent file."""
        from ansys.aedt.mcp.tools import run_python_script

        with patch("ansys.aedt.mcp.tools.os.path.exists", return_value=False):
            result = run_python_script(mock_context, script_path="/missing/script.py")

        assert "Script file not found" in result

    def test_script_success(self, mock_context):
        """Test successful script execution."""
        from ansys.aedt.mcp.tools import run_python_script

        mock_context.request_context.lifespan_context.desktop.odesktop.RunScript.return_value = "OK"

        with patch("ansys.aedt.mcp.tools.os.path.exists", return_value=True):
            result = run_python_script(mock_context, script_path="test.py")

        assert "Script executed successfully" in result
        assert "OK" in result

    def test_script_exception(self, mock_context):
        """Test script execution failure."""
        from ansys.aedt.mcp.tools import run_python_script

        mock_context.request_context.lifespan_context.desktop.odesktop.RunScript.side_effect = (
            RuntimeError("Script crashed")
        )

        with patch("ansys.aedt.mcp.tools.os.path.exists", return_value=True):
            result = run_python_script(mock_context, script_path="test.py")

        assert "Error executing script" in result
        assert "Script crashed" in result


@pytest.mark.unit
class TestExportResults:
    """Tests for export_results tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test export results with no connection."""
        from ansys.aedt.mcp.tools import export_results

        result = export_results(mock_context_no_desktop, output_path="/tmp/out.snp")
        assert "No AEDT Desktop connection" in result

    def test_export_returns_placeholder(self, mock_context):
        """Test export results returns placeholder message when no app instance."""
        from ansys.aedt.mcp.tools import export_results

        result = export_results(mock_context, output_path="/tmp/out.snp")
        assert "Export functionality requires an active application" in result

    def test_export_custom_type(self, mock_context):
        """Test export with a specific export type."""
        from ansys.aedt.mcp.tools import export_results

        result = export_results(mock_context, output_path="/tmp/out.csv", export_type="convergence")
        assert isinstance(result, str)


@pytest.mark.unit
class TestGetModelInfo:
    """Tests for get_model_info tool."""

    def test_no_connection(self, mock_context_no_desktop):
        """Test get model info with no connection."""
        from ansys.aedt.mcp.tools import get_model_info

        result = get_model_info(mock_context_no_desktop)
        assert "No AEDT Desktop connection" in result

    def test_get_model_info_success(self, mock_context):
        """Test successful model info retrieval."""
        from ansys.aedt.mcp.tools import get_model_info

        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "HFSS"
        mock_context.request_context.lifespan_context.desktop.project_path.return_value = (
            "C:\\Projects\\test.aedt"
        )

        result = get_model_info(mock_context, design_name="TestDesign")
        data = json.loads(result)
        assert data["design_name"] == "TestDesign"
        assert data["design_type"] == "HFSS"
        assert data["project_path"] == "C:\\Projects\\test.aedt"

    def test_get_model_info_active_design(self, mock_context):
        """Test model info with no explicit design name uses active design."""
        from ansys.aedt.mcp.tools import get_model_info

        mock_context.request_context.lifespan_context.desktop.design_type.return_value = "Maxwell3d"
        mock_context.request_context.lifespan_context.desktop.project_path.return_value = (
            "C:\\Projects\\maxwell.aedt"
        )

        result = get_model_info(mock_context)
        data = json.loads(result)
        assert data["design_name"] == "Active Design"
        assert data["design_type"] == "Maxwell3d"

    def test_get_model_info_exception(self, mock_context):
        """Test model info when an exception occurs."""
        from ansys.aedt.mcp.tools import get_model_info

        mock_context.request_context.lifespan_context.desktop.design_type.side_effect = (
            RuntimeError("No active design")
        )

        result = get_model_info(mock_context)
        assert "Error getting model info" in result


@pytest.mark.unit
class TestLaunchAEDTExtended:
    """Extended tests for launch_aedt tool."""

    def test_launch_in_docker_returns_error(self, mock_context_no_desktop):
        """Test that launching AEDT inside Docker is blocked."""
        from ansys.aedt.mcp.tools import launch_aedt

        with patch("ansys.aedt.mcp.tools._is_docker", return_value=True):
            result = launch_aedt(mock_context_no_desktop)

        assert "Docker" in result
        assert "not supported" in result

    def test_launch_with_application(self, mock_context_no_desktop):
        """Test launching AEDT with a specific application type."""
        from ansys.aedt.mcp.tools import launch_aedt

        mock_app_instance = MagicMock()
        mock_app_instance.desktop_class = MagicMock()
        mock_app_instance.desktop_class.aedt_version_id = "2026.1"
        mock_app_instance.desktop_class.aedt_install_dir = "C:\\ANSYS"
        mock_app_instance.desktop_class.is_grpc_api = True

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
            patch("ansys.aedt.core.Hfss", return_value=mock_app_instance),
            patch("ansys.aedt.mcp.tools._configure_pyaedt_runtime_settings"),
        ):
            result = launch_aedt(mock_context_no_desktop, application="Hfss")

        assert "Successfully launched Hfss" in result

    def test_launch_unsupported_application(self, mock_context_no_desktop):
        """Test launching AEDT with an unsupported application type."""
        from ansys.aedt.mcp.tools import launch_aedt

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
            patch("ansys.aedt.mcp.tools._configure_pyaedt_runtime_settings"),
        ):
            result = launch_aedt(mock_context_no_desktop, application="InvalidApp")  # type: ignore

        assert "Unsupported application type" in result


@pytest.mark.unit
class TestConnectToAEDTExtended:
    """Extended tests for connect_to_aedt tool."""

    def test_connect_docker_overrides_defaults(self, mock_context_no_desktop):
        """Test that Docker overrides default machine/port from env vars."""
        from ansys.aedt.mcp.tools import connect_to_aedt

        fake_desktop = MagicMock()
        fake_desktop.aedt_version_id = "2026.1"
        fake_desktop.is_grpc_api = True

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=True),
            patch.dict("os.environ", {"AEDT_MACHINE": "docker-host", "AEDT_PORT": "50099"}),
            patch("ansys.aedt.core.Desktop", return_value=fake_desktop) as mock_desktop,
            patch("ansys.aedt.mcp.tools._configure_pyaedt_runtime_settings"),
        ):
            result = connect_to_aedt(mock_context_no_desktop)

        call_kwargs = mock_desktop.call_args[1]
        assert call_kwargs["machine"] == "docker-host"
        assert call_kwargs["port"] == 50099
        assert "Successfully connected" in result

    def test_connect_with_design_name(self, mock_context_no_desktop):
        """Test connecting directly to a design."""
        from ansys.aedt.mcp.tools import connect_to_aedt

        fake_desktop = MagicMock()
        fake_desktop.aedt_version_id = "2026.1"
        fake_desktop.is_grpc_api = True

        fake_app = MagicMock()
        fake_app.project_name = "Project1"
        fake_app.design_name = "Design1"
        fake_app.design_type = "HFSS"

        with (
            patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
            patch("ansys.aedt.core.Desktop", return_value=fake_desktop),
            patch("ansys.aedt.core.get_pyaedt_app", return_value=fake_app),
            patch("ansys.aedt.mcp.tools._configure_pyaedt_runtime_settings"),
        ):
            result = connect_to_aedt(
                mock_context_no_desktop,
                design_name="Design1",
                project_name="Project1",
            )

        assert "Successfully connected" in result
        assert "Design: Design1" in result
        assert "Project: Project1" in result
