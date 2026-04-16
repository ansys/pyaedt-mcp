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
        launcher(["--version", "2026.1"])

    cfg = getattr(package_mcp, "_cli_config", None)
    assert cfg is not None
    assert cfg["aedt_version"] == "2026.1"


@pytest.mark.unit
def test_product_startup_connects_when_connect_flag_is_true():
    """MCP startup should initialize AEDT Desktop when connect_on_startup is True."""
    from ansys.aedt.mcp.server import PyAEDTMCP

    with (patch("ansys.aedt.core.Desktop") as mock_desktop,):
        fake_desktop = MagicMock()
        mock_desktop.return_value = fake_desktop

        mcp = PyAEDTMCP()
        setattr(
            mcp,
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
        mcp.create_context()
        mcp.product_startup()

        mock_desktop.assert_called_once_with(
            version=None,
            non_graphical=True,
            new_desktop=False,
            machine="localhost",
            port=50051,
        )
        assert mcp.context.desktop is fake_desktop


@pytest.mark.unit
def test_product_startup_does_not_connect_by_default():
    """When connect_on_startup is False, MCP should not initialize AEDT Desktop."""
    from ansys.aedt.mcp.server import PyAEDTMCP

    with patch("ansys.aedt.core.Desktop") as mock_desktop:
        mcp = PyAEDTMCP()
        setattr(
            mcp,
            "_cli_config",
            {
                "transport_type": "stdio",
                "aedt_machine": "localhost",
                "aedt_port": 50051,
                "aedt_version": None,
                "non_graphical": True,
                "connect_on_startup": False,
                "http_host": "127.0.0.1",
                "http_port": 8080,
                "cors_origins": None,
            },
        )
        mcp.create_context()
        mcp.product_startup()

        mock_desktop.assert_not_called()
        assert mcp.context.desktop is None


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


@pytest.mark.unit
def test_legacy_enable_agent_codegen_context_flag_is_rejected():
    """Legacy flag should fail."""
    from ansys.aedt.mcp.server import launcher

    with pytest.raises(SystemExit):
        launcher(["--enable-agent-codegen-context"])
