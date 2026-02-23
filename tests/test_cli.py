"""Unit tests for MCP CLI parsing and startup connection behavior."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
def test_main_parses_defaults(monkeypatch):
    """Default args populate mcp._cli_config correctly and doesn't run server."""
    from ansys.aedt.mcp import app as package_mcp
    from ansys.aedt.mcp.server import launcher

    # Prevent actual asyncio.run from running
    with patch.object(asyncio, "run") as mock_run:
        launcher([])
        mock_run.assert_called_once()

    # Ensure mcp._cli_config attached and has defaults
    cfg = getattr(package_mcp, "_cli_config", None)
    assert cfg is not None
    assert cfg["transport_type"] == "stdio"
    assert cfg["aedt_machine"] == "localhost"
    assert cfg["aedt_port"] == 50051
    assert cfg["connect_on_startup"] is False
    assert cfg["http_host"] == "127.0.0.1"
    assert cfg["http_port"] == 8080
    assert cfg["cors_origins"] is None


@pytest.mark.unit
def test_main_accepts_http_transport(monkeypatch):
    """Selecting http transport should work."""
    from ansys.aedt.mcp import app as package_mcp
    from ansys.aedt.mcp.server import launcher

    # Prevent actual asyncio.run from running
    with patch.object(asyncio, "run") as mock_run:
        launcher(["--transport", "http"])
        mock_run.assert_called_once()

    # Ensure mcp._cli_config attached and has http transport
    cfg = getattr(package_mcp, "_cli_config", None)
    assert cfg is not None
    assert cfg["transport_type"] == "http"


@pytest.mark.unit
def test_main_invalid_port_raises():
    """Providing an invalid port should cause argparse to exit."""
    from ansys.aedt.mcp.server import launcher

    with pytest.raises(SystemExit):
        launcher(["--port", "70000"])  # out of 1-65535 should exit


@pytest.mark.unit
def test_main_accepts_custom_machine():
    """Test that custom machine name is accepted."""
    from ansys.aedt.mcp import app as package_mcp
    from ansys.aedt.mcp.server import launcher

    with patch.object(asyncio, "run"):
        launcher(["--machine", "remote-server.example.com"])

    cfg = getattr(package_mcp, "_cli_config", None)
    assert cfg is not None
    assert cfg["aedt_machine"] == "remote-server.example.com"


@pytest.mark.unit
def test_main_accepts_aedt_version():
    """Test that AEDT version is accepted."""
    from ansys.aedt.mcp import app as package_mcp
    from ansys.aedt.mcp.server import launcher

    with patch.object(asyncio, "run"):
        launcher(["--version", "2025.2"])

    cfg = getattr(package_mcp, "_cli_config", None)
    assert cfg is not None
    assert cfg["aedt_version"] == "2025.2"


@pytest.mark.unit
def test_product_startup_attempts_connect_on_startup():
    """When connect_on_startup is True, MCP should attempt to connect to AEDT."""
    from ansys.aedt.mcp.server import PyAEDTMCP, app

    # Prepare a fake Desktop instance to be returned by Desktop
    fake_desktop = MagicMock()
    fake_desktop.release_desktop = MagicMock()

    # Attach CLI config to server
    setattr(
        app,
        "_cli_config",
        {
            "transport_type": "stdio",
            "aedt_machine": "localhost",
            "aedt_port": 50051,
            "aedt_version": None,
            "non_graphical": True,
            "connect_on_startup": True,
            "http_host": "127.0.0.1",
            "http_port": 8080,
            "cors_origins": None,
        },
    )

    # Mock Desktop to return our fake instance
    with patch("ansys.aedt.core.Desktop", return_value=fake_desktop) as mock_desktop:
        # Create MCP instance
        mcp = PyAEDTMCP()
        mcp.server = app  # Manually attach server
        mcp.create_context()
        mcp.product_startup()

        # Verify Desktop was called with correct parameters
        mock_desktop.assert_called_once_with(
            version=None,
            non_graphical=True,
            new_desktop=False,
            machine="localhost",
            port=50051,
        )

        # Verify Desktop instance was stored in context
        assert mcp.context.desktop == fake_desktop

        # Test cleanup
        mcp.product_cleanup()
        fake_desktop.release_desktop.assert_called_once_with(close_projects=False)

    # Clean up _cli_config
    delattr(app, "_cli_config")


@pytest.mark.unit
def test_non_graphical_modes():
    """Test graphical/non-graphical mode flags."""
    from ansys.aedt.mcp import app as package_mcp
    from ansys.aedt.mcp.server import launcher

    # Test default (non-graphical)
    with patch.object(asyncio, "run"):
        launcher([])
    cfg = getattr(package_mcp, "_cli_config", None)
    assert cfg["non_graphical"] is True

    # Test explicit graphical mode
    with patch.object(asyncio, "run"):
        launcher(["--graphical"])
    cfg = getattr(package_mcp, "_cli_config", None)
    assert cfg["non_graphical"] is False
