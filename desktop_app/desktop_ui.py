"""Small Flet control panel for the PyAEDT MCP Windows executable."""

import asyncio
import json
import os
from pathlib import Path
import subprocess  # nosec B404
import sys
import threading
from urllib.request import urlopen

from agent_profiles import (
    install_claude_code_profile,
    install_claude_desktop_profile,
    install_codex_profile,
    install_copilot_cli_profile,
    install_cursor_profile,
    install_opencode_profile,
)
from desktop_launcher import (
    application_directory,
    command_paths,
    hidden_window_options,
    installed_version,
    runtime_directory,
    setup_environment,
)
import flet as ft
from packaging.version import Version
from PIL import Image
import pystray

PYPI_PACKAGE_URL = "https://pypi.org/pypi/ansys-aedt-mcp/json"
ICON_FILENAME = "pyaedt_mcp_icon.png"


def asset_directory() -> Path:
    """Return the directory that contains the packaged desktop assets."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "assets"
    return Path(__file__).resolve().parent / "assets"


def app_icon_path() -> Path:
    """Return the bundled PyAEDT MCP application icon path."""
    return asset_directory() / ICON_FILENAME


def available_package_versions() -> list[str]:
    """Return published MCP releases from PyPI, newest first."""
    with urlopen(PYPI_PACKAGE_URL, timeout=10) as response:  # nosec B310
        releases = json.load(response)["releases"]
    versions = [Version(version) for version, files in releases.items() if files]
    return [str(version) for version in sorted(versions, reverse=True)]


class McpControlPanel:
    """Display setup state, server settings, and coding-agent profile actions."""

    _active_tray_icon: pystray.Icon | None = None
    _tray_lock = threading.Lock()

    def __init__(self, page: ft.Page, *, load_versions: bool = True) -> None:
        self.page = page
        self.server_process: subprocess.Popen | None = None
        self.tray_icon: pystray.Icon | None = None
        self.status = ft.Text(
            "Checking the local environment...", color=ft.Colors.ON_SURFACE_VARIANT
        )
        self.machine = ft.TextField(label="AEDT host", value="localhost", dense=True, expand=True)
        self.port = ft.TextField(label="gRPC port", value="50051", dense=True, width=105)
        self.http_port = ft.TextField(label="HTTP port", value="8080", dense=True, width=105)
        self.connect = ft.Checkbox(label="Connect on start")
        self.graphical = ft.Checkbox(label="Graphical AEDT")
        self.include_context = ft.Checkbox(label="Guidance tools")
        self.dynamic_tools = ft.Checkbox(label="Dynamic tools")
        self.debug = ft.Checkbox(label="Debug logging")
        self.profiles = {
            "copilot": ft.Checkbox(label="Copilot CLI / VS Code", value=True),
            "claude_desktop": ft.Checkbox(label="Claude Desktop", value=True),
            "claude_code": ft.Checkbox(label="Claude Code"),
            "cursor": ft.Checkbox(label="Cursor"),
            "codex": ft.Checkbox(label="Codex"),
            "opencode": ft.Checkbox(label="OpenCode"),
        }
        home = Path.home()
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        self.profile_directories = {
            "copilot": ft.TextField(value=str(home / ".copilot"), dense=True, expand=True),
            "claude_desktop": ft.TextField(value=str(appdata / "Claude"), dense=True, expand=True),
            "claude_code": ft.TextField(value=str(home), dense=True, expand=True),
            "cursor": ft.TextField(value=str(home / ".cursor"), dense=True, expand=True),
            "codex": ft.TextField(value=str(home / ".codex"), dense=True, expand=True),
            "opencode": ft.TextField(
                value=str(home / ".config" / "opencode"), dense=True, expand=True
            ),
        }
        self.profile_transport = ft.Dropdown(
            label="Profile transport",
            value="stdio",
            options=[
                ft.DropdownOption(key="stdio", text="Stdio"),
                ft.DropdownOption(key="http", text="HTTP"),
            ],
            dense=True,
            expand=True,
        )
        self.folder_picker = ft.FilePicker()
        self.page.services.append(self.folder_picker)
        self.install_button = ft.FilledButton(
            "Install MCP", icon=ft.Icons.DOWNLOAD, on_click=self.install
        )
        self.update_button = ft.FilledButton(
            "Update MCP", icon=ft.Icons.SYSTEM_UPDATE, visible=False, on_click=self.update
        )
        self.version_picker = ft.Dropdown(
            label="MCP version",
            value="latest",
            options=[ft.DropdownOption(key="latest", text="Latest available")],
            dense=True,
            expand=True,
        )
        self.refresh_versions_button = ft.IconButton(
            ft.Icons.REFRESH,
            tooltip="Load published MCP versions",
            on_click=self.load_versions,
        )
        self.start_button = ft.FilledButton(
            content="Start HTTP",
            icon=ft.Icons.PLAY_ARROW,
            disabled=True,
            on_click=self.toggle_server,
        )
        self.profile_button = ft.OutlinedButton(
            "Install profiles", icon=ft.Icons.SETTINGS, on_click=self.install_profiles
        )
        self.theme_button = ft.IconButton(on_click=self._toggle_theme)
        self._configure_page()
        if isinstance(self.page, ft.Page):
            self._configure_tray()
        self._build()
        self.refresh_status()
        if load_versions:
            self.load_versions(None)

    def _configure_page(self) -> None:
        self.page.title = "PyAEDT MCP"
        self.page.window.width = 540
        self.page.window.height = 680
        self.page.window.min_width = 500
        self.page.window.min_height = 620
        self.page.window.resizable = False
        if app_icon_path().is_file():
            self.page.window.icon = str(app_icon_path())
        self.page.window.prevent_close = True
        self.page.window.on_event = self._on_window_event
        self.page.padding = 20
        self.page.theme_mode = ft.ThemeMode.SYSTEM
        self.page.theme = ft.Theme(
            color_scheme=ft.ColorScheme(
                primary="#007A78",
                on_primary="#FFFFFF",
                primary_container="#B8F2EF",
                on_primary_container="#00201F",
                surface="#F6F8F8",
                on_surface="#171D1D",
                on_surface_variant="#3E4948",
                outline="#6E7978",
                outline_variant="#BEC9C8",
            )
        )
        self.page.dark_theme = ft.Theme(
            color_scheme=ft.ColorScheme(
                primary="#7BD9D4",
                on_primary="#003735",
                primary_container="#00504D",
                on_primary_container="#B8F2EF",
                surface="#101918",
                on_surface="#DEE5E4",
                on_surface_variant="#BEC9C8",
                outline="#889391",
                outline_variant="#3E4948",
            )
        )
        self._update_theme_button()

    def _configure_tray(self) -> None:
        with self._tray_lock:
            active_tray_icon = type(self)._active_tray_icon
            if active_tray_icon is not None:
                active_tray_icon.stop()
            self.tray_icon = pystray.Icon(
                "PyAEDT MCP",
                self._tray_image(),
                "PyAEDT MCP",
                pystray.Menu(
                    pystray.MenuItem("Open window", self._tray_open_window, default=True),
                    pystray.MenuItem("Start HTTP server", self._tray_start_server),
                    pystray.MenuItem("Stop HTTP server", self._tray_stop_server),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Exit", self._tray_exit),
                ),
            )
            type(self)._active_tray_icon = self.tray_icon
            self.tray_icon.run_detached()

    @staticmethod
    def _tray_image() -> Image.Image:
        icon_path = app_icon_path()
        if icon_path.is_file():
            with Image.open(icon_path) as image:
                return image.convert("RGBA").copy()
        return Image.new("RGBA", (64, 64), "#007A78")

    def _on_window_event(self, event) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide_window()

    def _hide_window(self) -> None:
        self.page.window.visible = False
        self.page.window.skip_task_bar = True
        self.page.update()

    async def _show_window(self) -> None:
        self.page.window.visible = True
        self.page.window.skip_task_bar = False
        self.page.window.focused = True
        self.page.update()

    def _tray_open_window(self, _icon, _item) -> None:
        self.page.run_task(self._show_window)

    async def _tray_start_http_server(self) -> None:
        self.start(None)

    def _tray_start_server(self, _icon, _item) -> None:
        self.page.run_task(self._tray_start_http_server)

    async def _tray_stop_http_server(self) -> None:
        self.stop(None)

    def _tray_stop_server(self, _icon, _item) -> None:
        self.page.run_task(self._tray_stop_http_server)

    async def _exit_application(self) -> None:
        self.stop(None)
        with self._tray_lock:
            if self.tray_icon is not None:
                self.tray_icon.stop()
            if type(self)._active_tray_icon is self.tray_icon:
                type(self)._active_tray_icon = None
        await self.page.window.destroy()

    def _tray_exit(self, _icon, _item) -> None:
        self.page.run_task(self._exit_application)

    def _section(self, title: str, content: ft.Control) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [ft.Text(title, size=15, weight=ft.FontWeight.W_600), content], spacing=8
            ),
            bgcolor=ft.Colors.SURFACE,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=6,
            padding=12,
        )

    def _help_button(self, title: str, message: str) -> ft.IconButton:
        return ft.IconButton(
            ft.Icons.INFO_OUTLINE,
            tooltip=f"About {title}",
            icon_size=18,
            on_click=lambda _event: self._show_info(title, message),
        )

    def _show_info(self, title: str, message: str) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[ft.TextButton("Close", on_click=lambda _event: self.page.pop_dialog())],
        )
        self.page.show_dialog(dialog)

    def _with_help(
        self, control: ft.Control, title: str, message: str, *, expand: bool = False
    ) -> ft.Row:
        return ft.Row([control, self._help_button(title, message)], spacing=0, expand=expand)

    def _profile_option(self, profile: str, title: str, message: str) -> ft.Row:
        return self._with_help(self.profiles[profile], title, message)

    def _profile_row(self, profile: str, title: str, message: str) -> ft.Row:
        async def choose_folder(_event) -> None:
            await self._choose_profile_folder(profile)

        return ft.Row(
            [
                ft.Container(content=self._profile_option(profile, title, message), width=200),
                self.profile_directories[profile],
                ft.IconButton(
                    ft.Icons.FOLDER_OPEN,
                    tooltip="Choose configuration folder",
                    on_click=choose_folder,
                ),
            ],
            spacing=4,
        )

    async def _choose_profile_folder(self, profile: str) -> None:
        current_path = Path(self.profile_directories[profile].value)
        selected_directory = await self.folder_picker.get_directory_path(
            dialog_title=f"Choose {self.profiles[profile].label} configuration folder",
            initial_directory=str(current_path.parent if current_path.suffix else current_path),
        )
        if selected_directory:
            self.profile_directories[profile].value = selected_directory
            self.page.update()

    def _build(self) -> None:
        self.page.add(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text("PyAEDT MCP", size=24, weight=ft.FontWeight.W_600),
                                    ft.Text(
                                        "Local server and coding-agent setup",
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            self.theme_button,
                        ]
                    ),
                    ft.Tabs(
                        length=2,
                        expand=True,
                        content=ft.Column(
                            [
                                ft.TabBar(
                                    tabs=[ft.Tab(label="Server"), ft.Tab(label="Coding agents")]
                                ),
                                ft.TabBarView(
                                    expand=True,
                                    controls=[self._server_tab(), self._agents_tab()],
                                ),
                            ],
                            expand=True,
                        ),
                    ),
                ],
                spacing=12,
                expand=True,
            )
        )

    def _server_tab(self) -> ft.Column:
        return ft.Column(
            [
                self._section(
                    "Environment",
                    ft.Column(
                        [
                            self.status,
                            ft.Row(
                                [
                                    self.version_picker,
                                    self.refresh_versions_button,
                                    self._help_button(
                                        "MCP version",
                                        "Choose the release to install or update. "
                                        "Published versions are loaded from PyPI "
                                        "when the app opens.",
                                    ),
                                ]
                            ),
                            ft.Row(
                                [
                                    self.install_button,
                                    self.update_button,
                                    self.start_button,
                                ]
                            ),
                        ],
                        spacing=12,
                    ),
                ),
                self._section(
                    "Server",
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    self._with_help(
                                        self.machine,
                                        "AEDT host",
                                        "Host name or IP address of the AEDT session "
                                        "to connect to.",
                                        expand=True,
                                    ),
                                ]
                            ),
                            ft.Row(
                                [
                                    self._with_help(
                                        self.port,
                                        "gRPC port",
                                        "AEDT's gRPC port. AEDT typically uses 50051.",
                                    ),
                                    self._with_help(
                                        self.http_port,
                                        "HTTP port",
                                        "Local port for the optional HTTP MCP transport.",
                                    ),
                                ]
                            ),
                            ft.Row(
                                [
                                    self._with_help(
                                        self.connect,
                                        "Connect on start",
                                        "Connect the MCP server to an existing AEDT "
                                        "session on startup.",
                                    ),
                                    self._with_help(
                                        self.graphical,
                                        "Graphical AEDT",
                                        "Start or connect to AEDT with its graphical "
                                        "interface enabled.",
                                    ),
                                ]
                            ),
                            ft.Row(
                                [
                                    self._with_help(
                                        self.include_context,
                                        "Guidance tools",
                                        "Expose MCP guidance tools that help an agent "
                                        "use the server.",
                                    ),
                                    self._with_help(
                                        self.dynamic_tools,
                                        "Dynamic tools",
                                        "Discover tools from the connected AEDT design as needed.",
                                    ),
                                ]
                            ),
                            ft.Row(
                                [
                                    self._with_help(
                                        self.debug,
                                        "Debug logging",
                                        "Set the MCP server log level to DEBUG when "
                                        "starting HTTP transport.",
                                    ),
                                ]
                            ),
                        ],
                        spacing=12,
                    ),
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    def _agents_tab(self) -> ft.Column:
        home = Path.home()
        return ft.Column(
            [
                self._section(
                    "User profiles",
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    self.profile_transport,
                                    self._help_button(
                                        "Profile transport",
                                        "Stdio starts PyAEDT MCP for each agent. "
                                        "HTTP connects the agent to the local server "
                                        "on the HTTP port.",
                                    ),
                                ]
                            ),
                            self._profile_row(
                                "copilot",
                                "GitHub Copilot CLI / VS Code",
                                f"Writes {home / '.copilot' / 'mcp-config.json'} "
                                "for the Copilot CLI profile. Enter a folder or a JSON file path.",
                            ),
                            self._profile_row(
                                "claude_desktop",
                                "Claude Desktop",
                                "Enter a folder or a JSON file path.",
                            ),
                            self._profile_row(
                                "claude_code",
                                "Claude Code",
                                "Enter a folder or a JSON file path.",
                            ),
                            self._profile_row(
                                "cursor",
                                "Cursor",
                                "Enter a folder or a JSON file path.",
                            ),
                            self._profile_row(
                                "codex",
                                "Codex",
                                "Enter a folder or a TOML file path.",
                            ),
                            self._profile_row(
                                "opencode",
                                "OpenCode",
                                "Enter a folder or a JSON file path.",
                            ),
                            self.profile_button,
                        ],
                        spacing=4,
                    ),
                )
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    def _toggle_theme(self, _event) -> None:
        self.page.theme_mode = (
            ft.ThemeMode.DARK if self.page.theme_mode == ft.ThemeMode.LIGHT else ft.ThemeMode.LIGHT
        )
        self._update_theme_button()
        self.page.update()

    def _update_theme_button(self) -> None:
        is_dark = self.page.theme_mode == ft.ThemeMode.DARK
        self.theme_button.icon = ft.Icons.LIGHT_MODE if is_dark else ft.Icons.DARK_MODE
        self.theme_button.tooltip = "Switch to light mode" if is_dark else "Switch to dark mode"

    def _server_arguments(self, http: bool) -> list[str]:
        arguments = []
        if http:
            arguments.extend(
                [
                    "--transport",
                    "http",
                    "--http-host",
                    "127.0.0.1",
                    "--http-port",
                    self.http_port.value.strip() or "8080",
                ]
            )
        if self.connect.value:
            arguments.extend(
                [
                    "--connect",
                    "--machine",
                    self.machine.value.strip() or "localhost",
                    "--port",
                    self.port.value.strip() or "50051",
                ]
            )
        if self.graphical.value:
            arguments.append("--graphical")
        if self.include_context.value:
            arguments.append("--include-context")
        if self.dynamic_tools.value:
            arguments.append("--dynamic-tool-discovery")
        return arguments

    def _executable(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable)
        return Path(__file__).with_name("desktop_launcher.py")

    def refresh_status(self) -> None:
        app_directory = application_directory()
        _, command = command_paths(app_directory)
        installed = command.is_file()
        version = installed_version(app_directory) if installed else None
        self.status.value = f"MCP {version} installed" if version else "MCP is not installed"
        self.install_button.disabled = installed
        self.update_button.visible = installed
        if self.server_process is None or self.server_process.poll() is not None:
            self._set_server_button_running(False)
            self.start_button.disabled = not installed
        self.page.update()

    def load_versions(self, _event) -> None:
        self.refresh_versions_button.disabled = True
        self._run_background(available_package_versions, self._finish_loading_versions)

    def _finish_loading_versions(self, versions, error: str | None) -> None:
        self.refresh_versions_button.disabled = False
        if error:
            self.status.value = f"Could not load MCP versions: {error}"
        else:
            selected_version = self.version_picker.value
            self.version_picker.options = [ft.DropdownOption(key="latest", text="Latest available")]
            self.version_picker.options.extend(
                ft.DropdownOption(key=version, text=version) for version in versions
            )
            self.version_picker.value = (
                selected_version if selected_version in ["latest", *versions] else "latest"
            )
        self.page.update()

    def _run_background(self, action, complete) -> None:
        def worker() -> None:
            try:
                result = action()
                self.page.run_task(self._complete_background, complete, result, None)
            except Exception as error:
                self.page.run_task(self._complete_background, complete, None, str(error))

        threading.Thread(target=worker, daemon=True).start()

    async def _complete_background(self, complete, result, error: str | None) -> None:
        await asyncio.sleep(0)
        complete(result, error)

    def install(self, _event) -> None:
        self.status.value = "Installing MCP..."
        self.install_button.disabled = True
        self.page.update()
        self._run_background(
            lambda: setup_environment(
                application_directory(), runtime_directory(), version=self._selected_version()
            ),
            self._finish_install,
        )

    def update(self, _event) -> None:
        self.status.value = "Updating MCP..."
        self.update_button.disabled = True
        self.page.update()
        self._run_background(
            lambda: setup_environment(
                application_directory(),
                runtime_directory(),
                version=self._selected_version(),
                upgrade=True,
            ),
            self._finish_update,
        )

    def _selected_version(self) -> str | None:
        return None if self.version_picker.value == "latest" else self.version_picker.value

    def _finish_install(self, _result, error: str | None) -> None:
        self.status.value = f"Installation failed: {error}" if error else "MCP installed"
        self.refresh_status()

    def _finish_update(self, _result, error: str | None) -> None:
        self.update_button.disabled = False
        self.status.value = f"Update failed: {error}" if error else "MCP updated"
        self.refresh_status()

    def toggle_server(self, event) -> None:
        if self.server_process is not None and self.server_process.poll() is None:
            self.stop(event)
        else:
            self.start(event)

    def _set_server_button_running(self, running: bool) -> None:
        self.start_button.content = "Stop HTTP" if running else "Start HTTP"
        self.start_button.icon = ft.Icons.STOP if running else ft.Icons.PLAY_ARROW
        self.start_button.bgcolor = ft.Colors.RED if running else None
        self.start_button.color = ft.Colors.ON_ERROR if running else None

    def start(self, _event) -> None:
        if self.server_process is not None and self.server_process.poll() is None:
            return
        _, command = command_paths(application_directory())
        environment = os.environ.copy()
        if self.debug.value:
            environment["FASTMCP_LOG_LEVEL"] = "DEBUG"
        self.server_process = subprocess.Popen(  # nosec B603
            [str(command), *self._server_arguments(http=True)],
            env=environment,
            **hidden_window_options(),
        )
        self.status.value = f"HTTP server running on port {self.http_port.value.strip() or '8080'}"
        self._set_server_button_running(True)
        self.page.update()

    def stop(self, _event) -> None:
        if self.server_process is not None and self.server_process.poll() is None:
            self.server_process.terminate()
        self.server_process = None
        self.status.value = "HTTP server stopped"
        self._set_server_button_running(False)
        self.page.update()

    def install_profiles(self, _event) -> None:
        server_arguments = self._server_arguments(http=False)
        executable = self._executable()
        transport = self.profile_transport.value or "stdio"
        http_url = f"http://127.0.0.1:{self.http_port.value.strip() or '8080'}/mcp"
        directories = {
            profile: Path(field.value).expanduser()
            for profile, field in self.profile_directories.items()
        }
        actions = []
        if self.profiles["copilot"].value:
            actions.append(
                lambda: install_copilot_cli_profile(
                    directories["copilot"], executable, server_arguments, transport, http_url
                )
            )
        if self.profiles["claude_desktop"].value:
            actions.append(
                lambda: install_claude_desktop_profile(
                    directories["claude_desktop"], executable, server_arguments, transport, http_url
                )
            )
        if self.profiles["claude_code"].value:
            actions.append(
                lambda: install_claude_code_profile(
                    directories["claude_code"], executable, server_arguments, transport, http_url
                )
            )
        if self.profiles["cursor"].value:
            actions.append(
                lambda: install_cursor_profile(
                    directories["cursor"], executable, server_arguments, transport, http_url
                )
            )
        if self.profiles["codex"].value:
            actions.append(
                lambda: install_codex_profile(
                    directories["codex"], executable, server_arguments, transport, http_url
                )
            )
        if self.profiles["opencode"].value:
            actions.append(
                lambda: install_opencode_profile(
                    directories["opencode"], executable, server_arguments, transport, http_url
                )
            )
        if not actions:
            self.status.value = "Select at least one coding agent"
            self.page.update()
            return
        self.profile_button.disabled = True
        self.status.value = "Installing profiles..."
        self.page.update()
        self._run_background(lambda: [action() for action in actions], self._finish_profiles)

    def _finish_profiles(self, paths, error: str | None) -> None:
        self.profile_button.disabled = False
        if error:
            self.status.value = f"Profile installation failed: {error}"
        else:
            self.status.value = f"Installed {len(paths)} profile(s)"
        self.page.update()


def launch_gui() -> int:
    """Run the Flet desktop control panel."""
    ft.run(lambda page: McpControlPanel(page), assets_dir=str(asset_directory()))
    return 0
