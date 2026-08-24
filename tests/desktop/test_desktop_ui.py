# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the desktop control panel theme behavior."""

import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import flet as ft
import pytest


class FakeWindow:
    """Provide the window attributes used by the control panel."""


class FakePage:
    """Provide the minimal Flet page surface needed to construct the panel."""

    def __init__(self) -> None:
        self.window = FakeWindow()
        self.services = []
        self.controls = []
        self.update_count = 0

    def add(self, *controls) -> None:
        self.controls.extend(controls)

    def update(self) -> None:
        self.update_count += 1

    def show_dialog(self, dialog) -> None:
        self.dialog = dialog

    def pop_dialog(self) -> None:
        self.dialog = None


@pytest.fixture(scope="module")
def desktop_ui():
    desktop_app_directory = Path(__file__).parents[2] / "desktop_app"
    sys.path.insert(0, str(desktop_app_directory))
    script_path = desktop_app_directory / "desktop_ui.py"
    spec = importlib.util.spec_from_file_location("desktop_ui_for_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the desktop UI script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_control_panel_starts_in_system_theme_mode(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()

    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    assert page.theme_mode == ft.ThemeMode.SYSTEM
    assert page.theme.color_scheme.on_surface == "#171D1D"
    assert not page.window.resizable
    assert page.window.icon == str(desktop_ui.app_icon_path())
    assert panel.theme_button.icon == ft.Icons.DARK_MODE


def test_theme_toggle_switches_from_system_to_light_mode(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    panel._toggle_theme(None)

    assert page.theme_mode == ft.ThemeMode.LIGHT
    assert panel.theme_button.icon == ft.Icons.DARK_MODE
    assert page.update_count > 0


def test_installed_mcp_shows_update_and_enables_start_button(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    _, command = desktop_ui.command_paths(tmp_path / ".pyaedt_mcp")
    command.parent.mkdir(parents=True)
    command.touch()
    monkeypatch.setattr(desktop_ui, "application_directory", lambda: tmp_path / ".pyaedt_mcp")
    monkeypatch.setattr(desktop_ui, "installed_version", lambda _: "1.2.3")

    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    assert panel.install_button.disabled
    assert panel.update_button.visible
    assert not panel.start_button.disabled
    assert panel.start_button.content == "Start HTTP"


def test_running_server_uses_red_stop_button(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    panel._set_server_button_running(True)

    assert panel.start_button.content == "Stop HTTP"
    assert panel.start_button.icon == ft.Icons.STOP
    assert panel.start_button.bgcolor == ft.Colors.RED


def test_tray_open_schedules_window_restore(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    page.run_task = Mock()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    panel._tray_open_window(None, None)

    page.run_task.assert_called_once_with(panel._show_window)


def test_window_close_hides_window_in_system_tray(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    panel._on_window_event(type("WindowEvent", (), {"type": ft.WindowEventType.CLOSE})())

    assert page.window.visible is False
    assert page.window.skip_task_bar is True


def test_tray_uses_bundled_app_icon(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    assert panel._tray_image().size == (256, 256)
    assert (desktop_ui.asset_directory() / "pyaedt_mcp_icon.ico").is_file()


def test_tray_falls_back_when_a_legacy_executable_lacks_assets(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(desktop_ui, "asset_directory", lambda: tmp_path / "missing-assets")
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    assert panel._tray_image().size == (64, 64)


def test_available_package_versions_filters_empty_releases(monkeypatch, desktop_ui):
    response = io.StringIO(json.dumps({"releases": {"0.1.0": [{}], "0.2.0": [{}], "0.3.0": []}}))
    monkeypatch.setattr(desktop_ui, "urlopen", lambda *_args, **_kwargs: response)

    assert desktop_ui.available_package_versions() == ["0.2.0", "0.1.0"]


def test_control_panel_loads_versions_on_open(monkeypatch, desktop_ui):
    calls = []
    monkeypatch.setattr(
        desktop_ui.McpControlPanel,
        "load_versions",
        lambda _panel, _event: calls.append("loaded"),
    )

    desktop_ui.McpControlPanel(FakePage())

    assert calls == ["loaded"]


def test_help_button_opens_information_dialog(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    panel._show_info("gRPC port", "Used to connect to AEDT.")

    assert page.dialog.title.value == "gRPC port"
    assert page.dialog.content.value == "Used to connect to AEDT."


def test_profile_controls_include_custom_directories_and_transport(
    monkeypatch, tmp_path, desktop_ui
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    assert panel.profile_transport.value == "stdio"
    assert set(panel.profile_directories) == {
        "copilot",
        "claude_desktop",
        "claude_code",
        "cursor",
        "codex",
        "opencode",
    }
    assert panel.profiles["copilot"].label == "Copilot CLI / VS Code"


def test_profile_controls_use_one_row_per_agent(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)
    profile_controls = panel._agents_tab().controls[0].content.controls[1].controls

    assert len(profile_controls) == 8
    assert profile_controls[1].controls[0].width == 200
    assert profile_controls[1].controls[1] is panel.profile_directories["copilot"]
    assert profile_controls[6].controls[1] is panel.profile_directories["opencode"]


def test_server_settings_keep_checkbox_rows_within_the_fixed_window(
    monkeypatch, tmp_path, desktop_ui
):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)
    server_tab = panel._server_tab()
    server_section = server_tab.controls[1].content.controls[1]
    settings_rows = server_section.controls

    assert len(settings_rows) == 5
    assert settings_rows[0].controls[0].expand
    assert settings_rows[2].controls[0].controls[0] is panel.connect
    assert settings_rows[3].controls[0].controls[0] is panel.include_context
    assert settings_rows[4].controls[0].controls[0] is panel.debug
    assert len(settings_rows[2].controls) == 2
    assert len(settings_rows[3].controls) == 2
    assert len(settings_rows[4].controls) == 1
