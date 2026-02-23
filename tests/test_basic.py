"""Basic tests for PyAEDT MCP Server package."""

import pytest

import ansys.aedt.mcp


@pytest.mark.unit
def test_version():
    """Test that version is defined and is a string."""
    assert hasattr(ansys.aedt.mcp, "__version__")
    assert isinstance(ansys.aedt.mcp.__version__, str)
    assert len(ansys.aedt.mcp.__version__) > 0


@pytest.mark.unit
def test_package_imports():
    """Test that all expected functions and classes can be imported."""
    from ansys.aedt.mcp import (
        app,
    )

    assert app is not None


@pytest.mark.unit
def test_all_exports():
    """Test that __all__ contains all expected exports."""
    from ansys.aedt.mcp import __all__

    expected_exports = [
        "app",
        "launcher",
        "__version__",
    ]

    assert set(__all__) == set(expected_exports)


@pytest.mark.unit
def test_app_context_creation():
    """Test that PyAEDTAppContext can be created with Desktop instance."""
    from unittest.mock import MagicMock
    from ansys.aedt.mcp.server import PyAEDTAppContext

    mock_desktop = MagicMock()
    mock_desktop.aedt_version_id = "2025.2"
    
    ctx = PyAEDTAppContext()
    ctx.desktop = mock_desktop
    
    assert ctx.desktop is not None
    assert ctx.desktop.aedt_version_id == "2025.2"


@pytest.mark.unit
def test_app_context_no_desktop():
    """Test that PyAEDTAppContext can be created without Desktop instance."""
    from ansys.aedt.mcp.server import PyAEDTAppContext

    ctx = PyAEDTAppContext()
    ctx.desktop = None
    
    assert ctx.desktop is None
