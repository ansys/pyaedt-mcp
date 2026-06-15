# Copyright (C) 2025 - 2026 ANSYS, Inc. and/or its affiliates.
# SPDX-License-Identifier: Apache-2.0

"""Additional unit tests for helper and startup modules."""

from pathlib import Path
import runpy
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from ansys.aedt.mcp import helpers


def test_open_file_in_default_viewer_paths(monkeypatch):
    from ansys.aedt.mcp import tools

    monkeypatch.setattr(tools, "_is_docker", lambda: True)
    assert tools._open_file_in_default_viewer(Path("C:/tmp/file.txt")) == (
        "Viewer launch skipped inside Docker."
    )

    monkeypatch.setattr(tools, "_is_docker", lambda: False)
    monkeypatch.setattr(tools.os, "startfile", lambda path: None, raising=False)
    assert tools._open_file_in_default_viewer(Path("C:/tmp/file.txt")) is None


def test_configure_pyaedt_runtime_settings(monkeypatch):
    from ansys.aedt.mcp import tools

    fake_settings = MagicMock()
    fake_module = ModuleType("ansys.aedt.core")
    fake_module.settings = fake_settings

    monkeypatch.setitem(sys.modules, "ansys.aedt.core", fake_module)
    tools._configure_pyaedt_runtime_settings(enable_grpc=True)

    assert fake_settings.use_grpc_api is True
    assert fake_settings.release_on_exception is False


def test_resolve_pyaedt_log_file_from_logger_handler(monkeypatch, tmp_path):
    from ansys.aedt.mcp import tools

    log_file = tmp_path / "pyaedt.log"
    log_file.write_text("hello", encoding="utf-8")

    handler = MagicMock()
    handler.baseFilename = str(log_file)
    raw_logger = MagicMock()
    raw_logger.handlers = [handler]
    fake_logger = MagicMock()
    fake_logger.logger = raw_logger

    fake_logger_module = ModuleType("ansys.aedt.core.aedt_logger")
    fake_logger_module.pyaedt_logger = fake_logger

    monkeypatch.setitem(sys.modules, "ansys.aedt.core.aedt_logger", fake_logger_module)

    result = tools._resolve_pyaedt_log_file()

    assert result == str(log_file.resolve())


def test_get_aedt_app_class_known_and_unknown():
    from ansys.aedt.mcp import tools

    assert tools._get_aedt_app_class("Hfss") is not None
    assert tools._get_aedt_app_class("Mechanical") is not None
    assert tools._get_aedt_app_class("Unknown") is None


def test_probe_grpc_endpoint_unreachable(monkeypatch):
    def _raise(*args, **kwargs):
        raise OSError("connection failed")

    monkeypatch.setattr(helpers.socket, "create_connection", _raise)

    result = helpers._probe_grpc_endpoint("127.0.0.1", 50051)

    assert result["reachable"] is False
    assert "connection failed" in result["error"]


def test_get_aedt_info_error_paths():
    class _Desktop:
        @property
        def aedt_version_id(self):
            raise RuntimeError("broken connection")

        @property
        def project_list(self):
            raise RuntimeError("no projects")

        @property
        def installed_versions(self):
            raise RuntimeError("no versions")

        def active_project(self):
            raise RuntimeError("active project error")

        def active_design(self):
            raise RuntimeError("active design error")

    info = helpers.get_aedt_info(_Desktop())

    assert "error" in info["connection"]
    assert "projects_error" in info
    assert info["active_project"] is None
    assert info["active_design"] is None
    assert "installed_versions_error" in info


def test_get_design_info_error_paths():
    class _VariableManager:
        @property
        def design_variables(self):
            raise RuntimeError("bad vars")

    class _App:
        @property
        def design_name(self):
            raise RuntimeError("bad design")

        @property
        def setups(self):
            raise RuntimeError("bad setups")

        @property
        def boundaries(self):
            raise RuntimeError("bad boundaries")

        variable_manager = _VariableManager()

    info = helpers.get_design_info(_App())

    assert "error" in info
    assert info["setups"] == []
    assert info["boundaries"] == []
    assert info["design_variables"] == []


def test_parse_aedt_version_edge_cases():
    assert helpers.parse_aedt_version("abcd") == "abcd"
    assert helpers.parse_aedt_version("2026.a") == "2026a"
    assert helpers.parse_aedt_version("  261  ") == "261"


def test_get_design_type_map_contains_expected_keys():
    design_map = helpers.get_design_type_map()
    assert "HFSS" in design_map
    assert "HFSS 3D Layout Design" in design_map


def test_resolve_design_app_uses_active_project_and_design(monkeypatch):
    class _Named:
        def __init__(self, name):
            self._name = name
            self.GetName = lambda: self._name

    class _Desktop:
        def active_project(self):
            return _Named("ProjA")

        def active_design(self):
            return _Named("DesignA")

        def design_type(self, design_name=None):
            assert design_name == "DesignA"
            return "HFSS"

    class _App:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.project_name = kwargs.get("project")
            self.design_name = kwargs.get("design")

    monkeypatch.setattr(helpers, "get_design_type_map", lambda: {"HFSS": _App})

    app, project_name, design_name = helpers.resolve_design_app(_Desktop())

    assert isinstance(app, _App)
    assert project_name == "ProjA"
    assert design_name == "DesignA"
    assert app.kwargs["new_desktop"] is False


def test_resolve_design_app_unsupported_type(monkeypatch):
    desktop = MagicMock()
    desktop.active_project.return_value = None
    desktop.active_design.return_value = None
    desktop.design_type.return_value = "UnsupportedType"

    monkeypatch.setattr(helpers, "get_design_type_map", lambda: {"HFSS": object})

    with pytest.raises(RuntimeError, match="Unsupported design type"):
        helpers.resolve_design_app(desktop)


def test_startup_code_save_plot_paths(monkeypatch):
    from ansys.aedt.mcp.aedt_helper import startup_code

    monkeypatch.setattr(startup_code, "MATPLOTLIB_AVAILABLE", False)
    assert "matplotlib is not installed" in startup_code.save_matplotlib_plot()

    plotter = MagicMock()
    monkeypatch.setattr(startup_code, "PYVISTA_AVAILABLE", False)
    assert startup_code.save_pyvista_plot(plotter) == "PyVista is not available"


def test_startup_code_matplotlib_file_output(monkeypatch, tmp_path):
    from ansys.aedt.mcp.aedt_helper import startup_code

    output_path = tmp_path / "plot.png"
    fake_plt = MagicMock()
    fake_plt.savefig.return_value = None
    fake_plt.close.return_value = None

    monkeypatch.setattr(startup_code, "MATPLOTLIB_AVAILABLE", True)
    monkeypatch.setattr(startup_code, "plt", fake_plt)

    result = startup_code.save_matplotlib_plot(
        filename=str(output_path), return_base64=False, dpi=175
    )

    assert result == f"Plot saved to {output_path}"
    fake_plt.savefig.assert_called_once_with(str(output_path), dpi=175, bbox_inches="tight")
    fake_plt.close.assert_called_once()


def test_startup_code_matplotlib_base64_output(monkeypatch):
    from ansys.aedt.mcp.aedt_helper import startup_code

    fake_buffer = MagicMock()
    fake_buffer.read.return_value = b"plot-bytes"
    fake_plt = MagicMock()
    fake_plt.savefig.return_value = None
    fake_plt.close.return_value = None

    monkeypatch.setattr(startup_code, "MATPLOTLIB_AVAILABLE", True)
    monkeypatch.setattr(startup_code, "plt", fake_plt)
    monkeypatch.setattr(startup_code, "BytesIO", lambda: fake_buffer)
    monkeypatch.setattr(startup_code.base64, "b64encode", lambda data: b"encoded")

    result = startup_code.save_matplotlib_plot(return_base64=True, dpi=90)

    assert result == "data:image/png;base64,encoded"
    fake_plt.savefig.assert_called_once_with(fake_buffer, format="PNG", dpi=90, bbox_inches="tight")
    fake_plt.close.assert_called_once()


def test_startup_code_pyvista_file_output(monkeypatch):
    from ansys.aedt.mcp.aedt_helper import startup_code

    fake_plotter = MagicMock()
    fake_plotter.screenshot.return_value = None
    fake_plotter.close.return_value = None

    monkeypatch.setattr(startup_code, "PYVISTA_AVAILABLE", True)
    monkeypatch.setattr(startup_code, "PIL_AVAILABLE", False)

    result = startup_code.save_pyvista_plot(
        fake_plotter, filename="C:/tmp/plot.png", return_base64=True
    )

    assert result == "Plot saved to C:/tmp/plot.png"
    fake_plotter.screenshot.assert_called_once_with("C:/tmp/plot.png", transparent_background=False)
    fake_plotter.close.assert_called_once()


def test_startup_code_get_aedt_version_paths(monkeypatch):
    import ansys.aedt.core as aedt_module

    from ansys.aedt.mcp.aedt_helper import startup_code

    monkeypatch.setattr(aedt_module, "__version__", "1.2.3")
    assert startup_code.get_aedt_version() == "1.2.3"


def test_module_entrypoint_invokes_launcher(monkeypatch):
    fake_server = ModuleType("ansys.aedt.mcp.server")
    launcher = MagicMock()
    fake_server.launcher = launcher

    monkeypatch.setitem(sys.modules, "ansys.aedt.mcp.server", fake_server)
    runpy.run_module("ansys.aedt.mcp.__main__", run_name="__main__")

    launcher.assert_called_once()
