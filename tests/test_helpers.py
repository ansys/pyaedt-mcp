"""Unit tests for PyAEDT MCP helper functions."""

import pytest
from unittest.mock import MagicMock

from ansys.aedt.mcp.helpers import (
    get_aedt_info,
    get_design_info,
    format_aedt_error,
    validate_aedt_connection,
    parse_aedt_version,
)


class TestGetAEDTInfo:
    """Tests for get_aedt_info function."""

    def test_basic_info(self):
        """Test basic info extraction."""
        mock_desktop = MagicMock()
        mock_desktop.aedt_version_id = "252"
        mock_desktop.aedt_version_string = "AEDT 2025 R2"
        mock_desktop.aedt_install_dir = "C:\\ANSYS"
        mock_desktop.is_grpc_api = True
        mock_desktop.machine = "localhost"
        mock_desktop.port = 50051
        mock_desktop.non_graphical = True
        mock_desktop.aedt_process_id = 12345
        mock_desktop.project_list = ["Project1"]
        mock_desktop.installed_versions = {"252": "C:\\ANSYS"}

        info = get_aedt_info(mock_desktop)

        assert info["connection"]["version"] == "252"
        assert info["connection"]["is_grpc"] is True
        assert info["projects"] == ["Project1"]

    def test_missing_attributes(self):
        """Test with missing attributes."""
        mock_desktop = MagicMock(spec=[])  # Empty spec = no attributes
        
        info = get_aedt_info(mock_desktop)
        
        assert "connection" in info
        assert info["connection"]["version"] == "Unknown"


class TestGetDesignInfo:
    """Tests for get_design_info function."""

    def test_basic_design_info(self):
        """Test basic design info extraction."""
        mock_app = MagicMock()
        mock_app.design_name = "MyDesign"
        mock_app.project_name = "MyProject"
        mock_app.design_type = "Hfss"
        mock_app.solution_type = "Modal"
        mock_app.working_directory = "C:\\work"
        mock_app.project_path = "C:\\projects"
        mock_app.setups = []
        mock_app.boundaries = []
        mock_app.variable_manager.design_variables = {"var1": "10mm"}

        info = get_design_info(mock_app)

        assert info["design_name"] == "MyDesign"
        assert info["design_type"] == "Hfss"
        assert "var1" in info["design_variables"]


class TestFormatAEDTError:
    """Tests for format_aedt_error function."""

    def test_connection_error(self):
        """Test connection error formatting."""
        error = Exception("gRPC connection failed")
        result = format_aedt_error(error, "connect")
        
        assert "Connection error" in result
        assert "ansysedt.exe -grpcsrv" in result

    def test_license_error(self):
        """Test license error formatting."""
        error = Exception("License checkout failed")
        result = format_aedt_error(error, "launch")
        
        assert "License error" in result
        assert "license server" in result.lower()

    def test_version_error(self):
        """Test version error formatting."""
        error = Exception("Invalid version specified")
        result = format_aedt_error(error, "launch")
        
        assert "Version error" in result

    def test_generic_error(self):
        """Test generic error formatting."""
        error = ValueError("Something went wrong")
        result = format_aedt_error(error, "operation")
        
        assert "ValueError" in result
        assert "Something went wrong" in result


class TestValidateAEDTConnection:
    """Tests for validate_aedt_connection function."""

    def test_none_desktop(self):
        """Test with None desktop."""
        is_valid, msg = validate_aedt_connection(None)
        
        assert is_valid is False
        assert "No AEDT Desktop connection" in msg

    def test_valid_connection(self):
        """Test with valid connection."""
        mock_desktop = MagicMock()
        mock_desktop.project_list = ["Project1"]
        
        is_valid, msg = validate_aedt_connection(mock_desktop)
        
        assert is_valid is True
        assert "active" in msg

    def test_broken_connection(self):
        """Test with broken connection."""
        mock_desktop = MagicMock()
        mock_desktop.project_list = property(lambda s: exec("raise Exception('broken')"))
        type(mock_desktop).project_list = property(lambda s: exec("raise Exception('broken')"))
        
        # Force an exception on property access
        def raise_error():
            raise Exception("Connection broken")
        
        mock_desktop2 = MagicMock()
        type(mock_desktop2).project_list = property(lambda self: raise_error())
        
        is_valid, msg = validate_aedt_connection(mock_desktop2)
        
        assert is_valid is False


class TestParseAEDTVersion:
    """Tests for parse_aedt_version function."""

    def test_none_version(self):
        """Test with None version."""
        result = parse_aedt_version(None)
        assert result is None

    def test_three_digit_format(self):
        """Test with 3-digit format."""
        result = parse_aedt_version("252")
        assert result == "252"

    def test_year_dot_release_format(self):
        """Test with year.release format."""
        result = parse_aedt_version("2025.2")
        assert result == "252"

    def test_short_dot_format(self):
        """Test with short dot format."""
        result = parse_aedt_version("25.2")
        assert result == "252"

    def test_integer_input(self):
        """Test with integer input."""
        result = parse_aedt_version(252)
        assert result == "252"
