# Copyright (C) 2025 - 2026 ANSYS, Inc. and/or its affiliates.
# SPDX-License-Identifier: Apache-2.0

"""Additional unit tests for helper and startup modules."""

import runpy
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from ansys.aedt.mcp import helpers


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

        def GetName(self):
            return self._name

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


def test_module_entrypoint_invokes_launcher(monkeypatch):
    fake_server = ModuleType("ansys.aedt.mcp.server")
    launcher = MagicMock()
    fake_server.launcher = launcher

    monkeypatch.setitem(sys.modules, "ansys.aedt.mcp.server", fake_server)
    runpy.run_module("ansys.aedt.mcp.__main__", run_name="__main__")

    launcher.assert_called_once()
