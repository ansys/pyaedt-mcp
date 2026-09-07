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
from unittest.mock import AsyncMock, Mock

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
    assert page.window.icon.endswith("pyaedt_mcp_icon.ico")
    assert panel.theme_button.icon == ft.Icons.DARK_MODE


def test_theme_toggle_switches_from_system_to_light_mode(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    panel._toggle_theme(None)

    assert page.theme_mode == ft.ThemeMode.LIGHT
    assert panel.theme_button.icon == ft.Icons.DARK_MODE
    assert page.update_count > 0


@pytest.mark.asyncio
async def test_bug_report_button_opens_the_project_issue_tracker(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    page.launch_url = AsyncMock()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)
    header = page.controls[0].controls[0]

    await panel.submit_bug_report(None)

    assert header.controls[1] is panel.bug_report_button
    assert header.controls[2] is panel.theme_button
    assert panel.bug_report_button.tooltip == "Report a bug"
    page.launch_url.assert_awaited_once_with("https://github.com/ansys/pyaedt-mcp/issues")


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
    assert panel.start_button.content == "Start Server"


def test_missing_mcp_environment_shows_the_setup_guide(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()

    desktop_ui.McpControlPanel(page, load_versions=False)

    assert page.dialog.title.value == "Set up PyAEDT MCP"
    assert page.dialog.content.controls[0].value == "No managed MCP environment was found."
    assert (
        page.dialog.content.controls[-1].value == "Server output appears in the Server log window."
    )


@pytest.mark.asyncio
async def test_setup_guide_opens_the_desktop_app_documentation(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    page.launch_url = AsyncMock()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    await panel.open_desktop_app_documentation(None)

    assert page.dialog.actions[0].content == "View documentation"
    page.launch_url.assert_awaited_once_with(
        "https://aedt-mcp.docs.pyansys.com/version/stable/getting_started/desktop_app.html"
    )


def test_status_refresh_does_not_repeat_the_setup_guide(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)
    page.dialog = None

    panel.refresh_status()

    assert page.dialog is None


def test_running_server_uses_red_stop_button(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    panel._set_server_button_running(True)

    assert panel.start_button.content == "Stop Server"
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


def test_available_branches_returns_sorted_branch_names(monkeypatch, desktop_ui):
    response = io.StringIO(json.dumps([{"name": "main"}, {"name": "feat/desktop-manager"}]))
    monkeypatch.setattr(desktop_ui, "urlopen", lambda *_args, **_kwargs: response)

    assert desktop_ui.available_branches() == ["feat/desktop-manager", "main"]


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
    assert panel.install_source.value == "release"
    assert not panel.branch_picker.visible
    home = Path.home()
    assert Path(panel.profile_directories["copilot"].value) == home / ".copilot" / "mcp-config.json"
    assert Path(panel.profile_directories["claude_desktop"].value) == (
        tmp_path / "AppData" / "Claude" / "claude_desktop_config.json"
    )
    assert Path(panel.profile_directories["claude_code"].value) == home / ".claude.json"
    assert Path(panel.profile_directories["cursor"].value) == home / ".cursor" / "mcp.json"
    assert Path(panel.profile_directories["codex"].value) == home / ".codex" / "config.toml"
    assert Path(panel.profile_directories["opencode"].value) == (
        home / ".config" / "opencode" / "opencode.json"
    )


def test_detected_coding_agents_are_preselected_at_startup(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(
        desktop_ui,
        "installed_coding_agents",
        lambda: {
            "copilot": True,
            "claude_desktop": False,
            "claude_code": True,
            "cursor": False,
            "codex": True,
            "opencode": False,
        },
    )

    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    assert {name for name, checkbox in panel.profiles.items() if checkbox.value} == {
        "copilot",
        "claude_code",
        "codex",
    }
    assert panel.profiles["claude_desktop"].disabled
    assert panel.profiles["cursor"].disabled
    assert panel.profile_directories["claude_desktop"].disabled
    assert panel.profile_directories["cursor"].disabled


def test_refresh_coding_agents_updates_profile_availability(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    page = FakePage()
    profiles = ("copilot", "claude_desktop", "claude_code", "cursor", "codex", "opencode")
    monkeypatch.setattr(
        desktop_ui, "installed_coding_agents", lambda: dict.fromkeys(profiles, False)
    )
    panel = desktop_ui.McpControlPanel(page, load_versions=False)
    panel._agents_tab()
    monkeypatch.setattr(
        desktop_ui, "installed_coding_agents", lambda: dict.fromkeys(profiles, True)
    )

    panel.refresh_coding_agents(None)

    assert all(checkbox.value and not checkbox.disabled for checkbox in panel.profiles.values())
    assert all(not field.disabled for field in panel.profile_directories.values())
    assert all(not button.disabled for button in panel.profile_folder_buttons.values())
    assert panel.status.value == "Coding-agent availability refreshed"


@pytest.mark.asyncio
async def test_profile_folder_picker_uses_an_existing_parent_directory(
    monkeypatch, tmp_path, desktop_ui
):
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)
    panel.profile_directories["copilot"].value = str(tmp_path / "missing" / "mcp-config.json")
    get_directory_path = AsyncMock(return_value=None)
    monkeypatch.setattr(panel.folder_picker, "get_directory_path", get_directory_path)

    await panel._choose_profile_folder("copilot")

    assert get_directory_path.call_args.kwargs["initial_directory"] == str(tmp_path)


def test_profile_installation_shows_confirmation_snackbar(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    panel._finish_profiles([tmp_path / "mcp.json"], None)

    assert isinstance(page.dialog, ft.SnackBar)
    assert page.dialog.content.value == "Installed 1 coding-agent profile(s)"


def test_coding_agent_detection_checks_cli_and_desktop_locations(monkeypatch, tmp_path, desktop_ui):
    local_appdata = tmp_path / "AppData" / "Local"
    (local_appdata / "Programs" / "Claude").mkdir(parents=True)
    (local_appdata / "Programs" / "Claude" / "Claude.exe").touch()
    (local_appdata / "Programs" / "Cursor").mkdir(parents=True)
    (local_appdata / "Programs" / "Cursor" / "Cursor.exe").touch()
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(
        desktop_ui.shutil,
        "which",
        lambda command: (
            "C:/tools/agent.exe" if command in {"copilot", "claude", "opencode"} else None
        ),
    )

    detected_agents = desktop_ui.installed_coding_agents()

    assert detected_agents == {
        "copilot": True,
        "claude_desktop": True,
        "claude_code": True,
        "cursor": True,
        "codex": False,
        "opencode": True,
    }


def test_profile_controls_use_one_row_per_agent(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)
    profile_controls = panel._agents_tab().controls[0].content.controls[1].controls

    assert len(profile_controls) == 8
    assert profile_controls[1].controls[0].width == 230
    assert profile_controls[1].controls[1] is panel.profile_directories["copilot"]
    assert profile_controls[6].controls[1] is panel.profile_directories["opencode"]
    assert profile_controls[7].controls == [panel.profile_button, panel.custom_profile_button]


async def test_install_custom_profile_uses_selected_json_template(
    monkeypatch, tmp_path, desktop_ui
):
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)
    template_path = tmp_path / "custom-profile.json"
    template_path.write_text(
        json.dumps(
            {
                "path": str(tmp_path / "mcp.json"),
                "mcps": {"custom-server": {"type": "remote", "url": "http://localhost"}},
            }
        )
    )
    monkeypatch.setattr(
        panel.folder_picker,
        "pick_files",
        AsyncMock(return_value=[Mock(path=str(template_path))]),
    )
    paths = []
    monkeypatch.setattr(panel, "_run_background", lambda action, _complete: paths.extend(action()))

    await panel.install_custom_profile(None)

    assert paths == [tmp_path / "mcp.json"]
    assert json.loads(paths[0].read_text())["mcps"]["custom-server"]["url"] == "http://localhost"


def test_advanced_settings_are_shared_in_a_top_level_tab(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)
    tabs = page.controls[0].controls[1]
    tab_view = tabs.content.controls[1]
    advanced_tab = tab_view.controls[1]
    connection_settings = advanced_tab.controls[0].content.controls[1]
    advanced_settings = advanced_tab.controls[1].content.controls[1]

    assert page.window.width == 660
    assert page.window.min_width == 620
    assert tabs.length == 3
    assert connection_settings.tight
    assert advanced_settings.tight
    assert connection_settings.controls[0].controls[0] is panel.machine
    connection_ports = connection_settings.controls[1].controls
    assert connection_ports[0].controls[0] is panel.http_port
    assert connection_ports[1].controls[0] is panel.port
    assert advanced_settings.controls[0].controls[0].controls[0] is panel.connect
    assert advanced_settings.controls[1].controls[0].controls[0] is panel.include_context
    assert advanced_settings.controls[2].controls[0] is panel.debug


def test_branch_source_requires_a_selection_before_install(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)
    panel.install_source.value = "branch"

    panel.install(None)

    assert panel.status.value == "Choose a Git branch to install"


def test_stdio_profiles_use_the_installed_mcp_command(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    app_directory = tmp_path / "installed-mcp"
    _, command = desktop_ui.command_paths(app_directory)
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)
    panel.profile_directories["copilot"].value = str(tmp_path / "mcp-config.json")
    panel.connect.value = True
    panel.graphical.value = True
    panel.include_context.value = True
    panel.dynamic_tools.value = True
    for profile, checkbox in panel.profiles.items():
        checkbox.value = profile == "copilot"
    paths = []
    monkeypatch.setattr(desktop_ui, "application_directory", lambda: app_directory)
    monkeypatch.setattr(panel, "_run_background", lambda action, _complete: paths.extend(action()))

    panel.install_profiles(None)

    profile = json.loads(paths[0].read_text())["mcpServers"]["pyaedt-mcp"]
    assert profile["command"] == str(command)
    assert profile["args"] == [
        "--connect",
        "--machine",
        "localhost",
        "--port",
        "50051",
        "--graphical",
        "--include-context",
        "--dynamic-tool-discovery",
    ]
    assert "--server" not in profile["args"]
    assert "--http-port" not in profile["args"]


def test_server_arguments_include_http_transport_options(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    assert panel._server_arguments()[:6] == [
        "--transport",
        "http",
        "--http-host",
        "127.0.0.1",
        "--http-port",
        "8080",
    ]


def test_server_tab_contains_a_read_only_log_window(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)
    server_log_section = panel._server_tab().controls[1]
    server_log_header = server_log_section.content.controls[0]

    assert server_log_header.controls[0].value == "Server log"
    assert server_log_section.content.controls[1] is panel.server_log
    assert panel.server_log.read_only
    assert panel.server_log.multiline
    assert panel.server_log.bgcolor == "#0B1210"
    assert panel.server_log.text_style.font_family == "Cascadia Mono"
    assert server_log_header.controls[2] is panel.copy_log_button
    assert server_log_header.controls[3] is panel.clear_log_button


def test_server_output_is_appended_to_the_log(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    panel = desktop_ui.McpControlPanel(page, load_versions=False)

    panel._append_server_log("Server \\u2588 started \\U0001f389\n")
    panel._append_server_log("Ready\n")

    assert panel.server_log.value == "Server █ started 🎉\nReady\n"
    assert page.update_count > 0


def test_log_unicode_decoding_preserves_windows_paths(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    panel = desktop_ui.McpControlPanel(FakePage(), load_versions=False)

    log_line = panel._decode_unicode_escapes(r"C:\Users\demo \u2588")

    assert log_line == "C:\\Users\\demo █"


@pytest.mark.asyncio
async def test_server_log_copy_and_clear_actions(monkeypatch, tmp_path, desktop_ui):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    page = FakePage()
    page.clipboard = Mock(set=AsyncMock())
    panel = desktop_ui.McpControlPanel(page, load_versions=False)
    panel.server_log.value = "Server started\n"

    await panel.copy_server_log(None)
    panel.clear_server_log(None)

    page.clipboard.set.assert_awaited_once_with("Server started\n")
    assert panel.server_log.value == ""
