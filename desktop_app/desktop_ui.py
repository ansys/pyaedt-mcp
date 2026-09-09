"""Small Flet control panel for the PyAEDT MCP Windows executable."""

import asyncio
from enum import Enum
import json
import os
from pathlib import Path
import re
import shutil
import subprocess  # nosec B404
import sys
import threading
from typing import Any
from urllib.request import urlopen

from agent_profiles import (
    install_claude_code_profile,
    install_claude_desktop_profile,
    install_codex_profile,
    install_copilot_cli_profile,
    install_cursor_profile,
    install_opencode_profile,
    install_profile_from_template,
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

PYPI_PACKAGE_URL = "https://pypi.org/pypi/ansys-aedt-mcp/json"
GITHUB_BRANCHES_URL = "https://api.github.com/repos/ansys/pyaedt-mcp/branches?per_page=100"
WINDOW_ICON_FILENAME = "pyaedt_mcp_icon.ico"
TRAY_ICON_FILENAME = "pyaedt_mcp_icon.png"
UNICODE_ESCAPE_PATTERN = re.compile(r"\\(?:u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})")
ISSUES_URL = "https://github.com/ansys/pyaedt-mcp/issues"
DESKTOP_APP_DOCUMENTATION_URL = (
    "https://aedt-mcp.docs.pyansys.com/version/stable/getting_started/desktop_app.html"
)


class ServerState(Enum):
    """Server status states for the traffic light indicator."""

    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    ERROR = "error"


# Minimal patterns for server state detection (not tool-specific)
# Pattern to detect server is ready (Uvicorn started)
SERVER_READY_PATTERN = re.compile(r"Uvicorn running on|Application startup complete", re.IGNORECASE)

# Pattern to detect start of MCP log message: [09/09/26 11:34:33]
MCP_LOG_START_PATTERN = re.compile(r"^\s*\[\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\]")

# Pattern to detect MCP log continuation (indented line with actual content)
MCP_CONTINUATION_PATTERN = re.compile(r"^\s+[A-Za-z]")

# Pattern to detect lines to IGNORE (Autopilot tool reads, other log formats)
IGNORE_LINE_PATTERN = re.compile(
    r"tools\.py:\d+|"  # Autopilot reading tools.py
    r"Called the \w+ tool|"  # Autopilot tool call messages (anywhere in line)
    r"^<path>|^<type>|^<content>|^\d+:|^\(Showing lines|^</|"  # Tool output XML/content
    r"^PyAEDT |"  # PyAEDT logs
    r"^INFO:|^WARNING:|^ERROR:|^DEBUG:|"  # Other log prefixes
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}|"  # Timestamp format logs
    r"^INFO\s+\d+\.\d+\.\d+\.\d+|"  # HTTP request logs
)

# Pattern to detect errors from MCP log format: [09/09/26 11:34:33] ERROR ...
MCP_ERROR_PATTERN = re.compile(r"\[\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\]\s+ERROR\s+(.+)")

# Pattern to extract INFO messages from MCP log format: [09/09/26 11:34:33] INFO ...
MCP_INFO_PATTERN = re.compile(r"\[\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\]\s+INFO\s+(.+)")

# Pattern to detect AEDT connection success
AEDT_CONNECTED_PATTERN = re.compile(
    r"Connected to AEDT|Successfully connected to AEDT", re.IGNORECASE
)

# Pattern to extract AEDT port from log
AEDT_PORT_PATTERN = re.compile(r"(?:port|localhost:)\s*(\d{4,5})", re.IGNORECASE)


def asset_directory() -> Path:
    """Return the directory that contains the packaged desktop assets."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "assets"
    return Path(__file__).resolve().parent / "assets"


def app_icon_path() -> Path:
    """Return the bundled PyAEDT MCP application icon path."""
    return asset_directory() / WINDOW_ICON_FILENAME


def tray_icon_path() -> Path:
    """Return the bundled PyAEDT MCP system tray icon path."""
    return asset_directory() / TRAY_ICON_FILENAME


def available_package_versions() -> list[str]:
    """Return published MCP releases from PyPI, newest first."""
    with urlopen(PYPI_PACKAGE_URL, timeout=10) as response:  # nosec B310
        releases = json.load(response)["releases"]
    versions = [Version(version) for version, files in releases.items() if files]
    return [str(version) for version in sorted(versions, reverse=True)]


def available_branches() -> list[str]:
    """Return the repository branches available for installation."""
    with urlopen(GITHUB_BRANCHES_URL, timeout=10) as response:  # nosec B310
        branches = json.load(response)
    return sorted(branch["name"] for branch in branches if isinstance(branch.get("name"), str))


def installed_coding_agents() -> dict[str, bool]:
    """Return coding agents detected in the local user environment."""
    local_appdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return {
        "copilot": shutil.which("copilot") is not None or shutil.which("code") is not None,
        "claude_desktop": (local_appdata / "Programs" / "Claude" / "Claude.exe").is_file(),
        "claude_code": shutil.which("claude") is not None,
        "cursor": (local_appdata / "Programs" / "Cursor" / "Cursor.exe").is_file(),
        "codex": shutil.which("codex") is not None,
        "opencode": shutil.which("opencode") is not None,
    }


class McpControlPanel:
    """Display setup state, server settings, and coding-agent profile actions."""

    _active_tray_icon: Any = None
    _tray_lock = threading.Lock()

    def __init__(self, page: ft.Page, *, load_versions: bool = True) -> None:
        self.page = page
        self.server_process: subprocess.Popen | None = None
        self.tray_icon: Any = None
        self._server_state = ServerState.STOPPED
        self._aedt_port: str | None = None
        self._aedt_connected: bool = False
        self._current_activity: str | None = None
        self._mcp_message_buffer: str = ""  # Buffer for multi-line MCP messages
        self.status = ft.Text(
            "Checking the local environment...", color=ft.Colors.ON_SURFACE_VARIANT
        )
        # Server status indicator (traffic light)
        self.server_status_indicator = ft.Container(
            width=12,
            height=12,
            border_radius=6,
            bgcolor=ft.Colors.GREY_500,
        )
        self.server_status_text = ft.Text(
            "Server stopped",
            color=ft.Colors.ON_SURFACE_VARIANT,
            size=13,
        )
        self.machine = ft.TextField(label="AEDT host", value="localhost", dense=True, expand=True)
        self.port = ft.TextField(label="gRPC port", value="50051", dense=True, width=105)
        self.http_port = ft.TextField(label="HTTP port", value="8080", dense=True, width=105)
        self.server_log = ft.TextField(
            value="",
            multiline=True,
            min_lines=12,
            max_lines=12,
            read_only=True,
            expand=True,
            bgcolor="#0B1210",
            color="#D4E4D8",
            border_color="#385347",
            focused_border_color="#7BD9D4",
            border_radius=4,
            text_style=ft.TextStyle(font_family="Cascadia Mono", size=12),
        )
        self.server_log_expanded = False
        self.server_log_container: ft.Container | None = None
        self.log_expand_icon: ft.Icon | None = None
        self.log_header_subtitle: ft.Text | None = None
        self.copy_log_button = ft.IconButton(
            ft.Icons.CONTENT_COPY,
            tooltip="Copy all logs",
            on_click=self.copy_server_log,
            icon_size=18,
        )
        self.latest_log_button = ft.IconButton(
            ft.Icons.ARROW_DOWNWARD,
            tooltip="Scroll to latest log entry",
            on_click=self.scroll_to_latest_log,
            icon_size=18,
        )
        self.clear_log_button = ft.IconButton(
            ft.Icons.DELETE_OUTLINE,
            tooltip="Clear logs",
            on_click=self.clear_server_log,
            icon_size=18,
        )
        self.connect = ft.Checkbox(label="Connect on start")
        self.graphical = ft.Checkbox(label="Graphical AEDT")
        self.include_context = ft.Checkbox(label="Guidance tools")
        self.dynamic_tools = ft.Checkbox(label="Dynamic tools")
        self.debug = ft.Checkbox(label="Debug logging")
        self.detected_agents = installed_coding_agents()
        self.profiles = {
            "copilot": ft.Checkbox(
                label="Copilot CLI / VS Code",
                value=self.detected_agents["copilot"],
                disabled=not self.detected_agents["copilot"],
            ),
            "claude_desktop": ft.Checkbox(
                label="Claude Desktop",
                value=self.detected_agents["claude_desktop"],
                disabled=not self.detected_agents["claude_desktop"],
            ),
            "claude_code": ft.Checkbox(
                label="Claude Code",
                value=self.detected_agents["claude_code"],
                disabled=not self.detected_agents["claude_code"],
            ),
            "cursor": ft.Checkbox(
                label="Cursor",
                value=self.detected_agents["cursor"],
                disabled=not self.detected_agents["cursor"],
            ),
            "codex": ft.Checkbox(
                label="Codex",
                value=self.detected_agents["codex"],
                disabled=not self.detected_agents["codex"],
            ),
            "opencode": ft.Checkbox(
                label="OpenCode",
                value=self.detected_agents["opencode"],
                disabled=not self.detected_agents["opencode"],
            ),
        }
        home = Path.home()
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        self.profile_directories = {
            "copilot": ft.TextField(
                value=str(home / ".copilot" / "mcp-config.json"),
                dense=True,
                disabled=not self.detected_agents["copilot"],
                expand=True,
            ),
            "claude_desktop": ft.TextField(
                value=str(appdata / "Claude" / "claude_desktop_config.json"),
                dense=True,
                disabled=not self.detected_agents["claude_desktop"],
                expand=True,
            ),
            "claude_code": ft.TextField(
                value=str(home / ".claude.json"),
                dense=True,
                disabled=not self.detected_agents["claude_code"],
                expand=True,
            ),
            "cursor": ft.TextField(
                value=str(home / ".cursor" / "mcp.json"),
                dense=True,
                disabled=not self.detected_agents["cursor"],
                expand=True,
            ),
            "codex": ft.TextField(
                value=str(home / ".codex" / "config.toml"),
                dense=True,
                disabled=not self.detected_agents["codex"],
                expand=True,
            ),
            "opencode": ft.TextField(
                value=str(home / ".config" / "opencode" / "opencode.json"),
                dense=True,
                disabled=not self.detected_agents["opencode"],
                expand=True,
            ),
        }
        self.profile_folder_buttons: dict[str, ft.IconButton] = {}
        self.profile_transport = ft.Dropdown(
            label="Profile transport",
            value="http",
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
        self.install_source = ft.Dropdown(
            label="Install source",
            value="release",
            options=[
                ft.DropdownOption(key="release", text="Release"),
                ft.DropdownOption(key="branch", text="Git branch"),
            ],
            dense=True,
            on_select=self._change_install_source,
            width=170,
        )
        self.branch_picker = ft.Dropdown(
            label="Git branch",
            options=[],
            dense=True,
            expand=True,
            visible=False,
        )
        self.refresh_versions_button = ft.IconButton(
            ft.Icons.REFRESH,
            tooltip="Load published MCP versions",
            on_click=self.load_versions,
        )
        self.start_button = ft.FilledButton(
            content="Start Server",
            icon=ft.Icons.PLAY_ARROW,
            disabled=True,
            on_click=self.toggle_server,
        )
        self.profile_button = ft.OutlinedButton(
            "Install profiles", icon=ft.Icons.SETTINGS, on_click=self.install_profiles
        )
        self.refresh_profiles_button = ft.IconButton(
            ft.Icons.REFRESH,
            tooltip="Refresh coding-agent availability",
            on_click=self.refresh_coding_agents,
        )
        self.custom_profile_button = ft.OutlinedButton(
            "Install custom profile",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self.install_custom_profile,
        )
        self.bug_report_button = ft.IconButton(
            ft.Icons.BUG_REPORT,
            tooltip="Report a bug",
            on_click=self.submit_bug_report,
        )
        self.theme_button = ft.IconButton(on_click=self._toggle_theme)
        self._configure_page()
        if isinstance(self.page, ft.Page):
            self._configure_tray()
        self._build()
        self.refresh_status(show_setup_guide=True)
        if load_versions:
            self.load_versions(None)

    def _configure_page(self) -> None:
        self.page.title = "PyAEDT MCP"
        self.page.window.width = 660
        self.page.window.height = 680
        self.page.window.min_width = 620
        self.page.window.min_height = 620
        self.page.window.resizable = False
        self.page.window.visible = True
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
        if os.name != "nt":
            return
        import pystray

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
                    pystray.MenuItem("Start Server", self._tray_start_server),
                    pystray.MenuItem("Stop Server", self._tray_stop_server),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Exit", self._tray_exit),
                ),
            )
            type(self)._active_tray_icon = self.tray_icon
            self.tray_icon.run_detached()

    @staticmethod
    def _tray_image() -> Image.Image:
        icon_path = tray_icon_path()
        if icon_path.is_file():
            with Image.open(icon_path) as image:
                return image.convert("RGBA").resize((256, 256))
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

    def _section(
        self, title: str, content: ft.Control, *, header_actions: list[ft.Control] | None = None
    ) -> ft.Container:
        header = ft.Text(title, size=15, weight=ft.FontWeight.W_600)
        if header_actions:
            header = ft.Row(
                [header, ft.Container(expand=True), *header_actions],
                spacing=0,
            )
        return ft.Container(
            content=ft.Column([header, content], spacing=8),
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

    async def open_desktop_app_documentation(self, _event) -> None:
        await self.page.launch_url(DESKTOP_APP_DOCUMENTATION_URL)

    def _show_setup_guide(self) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Set up PyAEDT MCP"),
            content=ft.Column(
                [
                    ft.Text("No managed MCP environment was found."),
                    ft.Text("1. Select an install source and MCP version on the Server tab."),
                    ft.Text("2. Select Install MCP, then start the HTTP server when needed."),
                    ft.Text("3. Open Coding agents to install your selected client profiles."),
                    ft.Text("Server output appears in the Server log window."),
                ],
                tight=True,
                spacing=8,
            ),
            actions=[
                ft.TextButton("View documentation", on_click=self.open_desktop_app_documentation),
                ft.TextButton("Close", on_click=lambda _event: self.page.pop_dialog()),
            ],
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

        folder_button = ft.IconButton(
            ft.Icons.FOLDER_OPEN,
            tooltip="Choose configuration folder",
            on_click=choose_folder,
            disabled=not self.detected_agents[profile],
        )
        self.profile_folder_buttons[profile] = folder_button
        return ft.Row(
            [
                ft.Container(content=self._profile_option(profile, title, message), width=230),
                self.profile_directories[profile],
                folder_button,
            ],
            spacing=4,
        )

    async def _choose_profile_folder(self, profile: str) -> None:
        current_path = Path(self.profile_directories[profile].value)
        initial_directory = current_path.parent if current_path.suffix else current_path
        while not initial_directory.is_dir() and initial_directory != initial_directory.parent:
            initial_directory = initial_directory.parent
        selected_directory = await self.folder_picker.get_directory_path(
            dialog_title=f"Choose {self.profiles[profile].label} configuration folder",
            initial_directory=str(initial_directory),
        )
        if selected_directory:
            self.profile_directories[profile].value = selected_directory
            self.page.update()

    async def install_custom_profile(self, _event) -> None:
        """Install a profile defined by a user-selected JSON template."""
        selected_files = await self.folder_picker.pick_files(
            dialog_title="Choose custom profile template",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["json"],
            allow_multiple=False,
        )
        if not selected_files:
            return
        self.custom_profile_button.disabled = True
        self.status.value = "Installing custom profile..."
        self.page.update()
        template_path = Path(selected_files[0].path)
        self._run_background(
            lambda: [install_profile_from_template(template_path)], self._finish_custom_profile
        )

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
                            self.bug_report_button,
                            self.theme_button,
                        ]
                    ),
                    ft.Tabs(
                        length=3,
                        expand=True,
                        content=ft.Column(
                            [
                                ft.TabBar(
                                    tabs=[
                                        ft.Tab(label="Server"),
                                        ft.Tab(label="Advanced"),
                                        ft.Tab(label="Coding agents"),
                                    ]
                                ),
                                ft.TabBarView(
                                    expand=True,
                                    controls=[
                                        self._server_tab(),
                                        self._advanced_tab(),
                                        self._agents_tab(),
                                    ],
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
        # Server status row with traffic light indicator
        server_status_row = ft.Container(
            content=ft.Row(
                [
                    self.server_status_indicator,
                    self.server_status_text,
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=6,
            padding=ft.Padding(left=12, top=8, right=12, bottom=8),
            margin=ft.Margin(left=0, top=0, right=0, bottom=8),
        )

        # Collapsible server log section
        self.server_log_container = ft.Container(
            content=self.server_log,
            visible=False,  # Start collapsed
            padding=ft.Padding(left=0, top=8, right=0, bottom=0),
        )

        self.log_expand_icon = ft.Icon(
            ft.Icons.EXPAND_MORE,
            size=20,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

        log_header = ft.Container(
            content=ft.Row(
                [
                    self.log_expand_icon,
                    ft.Text("Server log", size=14, weight=ft.FontWeight.W_500),
                    ft.Text(
                        " • Click to expand",
                        size=11,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        ref=ft.Ref[ft.Text](),
                    ),
                    ft.Container(expand=True),
                    self.copy_log_button,
                    self.latest_log_button,
                    self.clear_log_button,
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=self._toggle_log_panel,
            ink=True,
            padding=ft.Padding(left=8, top=8, right=8, bottom=8),
            border_radius=4,
        )
        self.log_header_subtitle = log_header.content.controls[2]

        server_log_section = ft.Container(
            content=ft.Column(
                [
                    log_header,
                    self.server_log_container,
                ],
                spacing=0,
            ),
            bgcolor=ft.Colors.SURFACE,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=6,
        )

        return ft.Column(
            [
                self._section(
                    "Environment",
                    ft.Column(
                        [
                            self.status,
                            server_status_row,
                            ft.Row(
                                [
                                    self.install_source,
                                    self.version_picker,
                                    self.branch_picker,
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
                server_log_section,
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    def _toggle_log_panel(self, _event) -> None:
        """Toggle the server log panel visibility."""
        if (
            self.server_log_container is None
            or self.log_expand_icon is None
            or self.log_header_subtitle is None
        ):
            return  # UI not yet initialized
        self.server_log_expanded = not self.server_log_expanded
        self.server_log_container.visible = self.server_log_expanded
        self.log_expand_icon.icon = (
            ft.Icons.EXPAND_LESS if self.server_log_expanded else ft.Icons.EXPAND_MORE
        )
        self.log_header_subtitle.value = (
            " • Click to collapse" if self.server_log_expanded else " • Click to expand"
        )
        self.page.update()

    def _on_log_panel_change(self, e) -> None:
        """Handle expansion panel state change (legacy, kept for compatibility)."""
        pass

    def _advanced_tab(self) -> ft.Column:
        return ft.Column(
            [
                self._section(
                    "AEDT connection",
                    self._connection_settings(),
                ),
                self._section(
                    "MCP options",
                    self._advanced_settings(),
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    def _connection_settings(self) -> ft.Column:
        return ft.Column(
            [
                self._with_help(
                    self.machine,
                    "AEDT host",
                    "Host name or IP address of the AEDT session to connect to.",
                    expand=True,
                ),
                ft.Row(
                    [
                        self._with_help(
                            self.http_port,
                            "HTTP port",
                            "Local port for the optional HTTP MCP transport.",
                        ),
                        self._with_help(
                            self.port,
                            "gRPC port",
                            "AEDT's gRPC port. AEDT typically uses 50051.",
                        ),
                    ]
                ),
            ],
            spacing=12,
            tight=True,
        )

    def _advanced_settings(self) -> ft.Column:
        return ft.Column(
            [
                ft.Row(
                    [
                        self._with_help(
                            self.connect,
                            "Connect on start",
                            "Connect the MCP server to an existing AEDT session on startup.",
                        ),
                        self._with_help(
                            self.graphical,
                            "Graphical AEDT",
                            "Start or connect to AEDT with its graphical interface enabled.",
                        ),
                    ]
                ),
                ft.Row(
                    [
                        self._with_help(
                            self.include_context,
                            "Guidance tools",
                            "Expose MCP guidance tools that help an agent use the server.",
                        ),
                        self._with_help(
                            self.dynamic_tools,
                            "Dynamic tools",
                            "Discover tools from the connected AEDT design as needed.",
                        ),
                    ]
                ),
                self._with_help(
                    self.debug,
                    "Debug logging",
                    "Set the MCP server log level to DEBUG when starting HTTP transport.",
                ),
            ],
            spacing=12,
            tight=True,
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
                            ft.Row([self.profile_button, self.custom_profile_button]),
                        ],
                        spacing=4,
                    ),
                    header_actions=[self.refresh_profiles_button],
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

    async def submit_bug_report(self, _event) -> None:
        await self.page.launch_url(ISSUES_URL)

    def _update_theme_button(self) -> None:
        is_dark = self.page.theme_mode == ft.ThemeMode.DARK
        self.theme_button.icon = ft.Icons.LIGHT_MODE if is_dark else ft.Icons.DARK_MODE
        self.theme_button.tooltip = "Switch to light mode" if is_dark else "Switch to dark mode"

    def _mcp_arguments(self) -> list[str]:
        arguments = []
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

    def _server_arguments(self) -> list[str]:
        return [
            "--transport",
            "http",
            "--http-host",
            "127.0.0.1",
            "--http-port",
            self.http_port.value.strip() or "8080",
            *self._mcp_arguments(),
        ]

    def refresh_status(self, *, show_setup_guide: bool = False) -> None:
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
        if show_setup_guide and not installed:
            self._show_setup_guide()

    def refresh_coding_agents(self, _event) -> None:
        self.detected_agents = installed_coding_agents()
        for profile, checkbox in self.profiles.items():
            checkbox.disabled = not self.detected_agents[profile]
            checkbox.value = self.detected_agents[profile]
            self.profile_directories[profile].disabled = not self.detected_agents[profile]
            if folder_button := self.profile_folder_buttons.get(profile):
                folder_button.disabled = not self.detected_agents[profile]
        self.status.value = "Coding-agent availability refreshed"
        self.page.update()

    def load_versions(self, _event) -> None:
        self.refresh_versions_button.disabled = True
        loader = (
            available_branches
            if self.install_source.value == "branch"
            else available_package_versions
        )
        self._run_background(loader, self._finish_loading_versions)

    def _finish_loading_versions(self, versions, error: str | None) -> None:
        self.refresh_versions_button.disabled = False
        if error:
            self.status.value = f"Could not load install options: {error}"
        elif self.install_source.value == "branch":
            selected_branch = self.branch_picker.value
            self.branch_picker.options = [
                ft.DropdownOption(key=branch, text=branch) for branch in versions
            ]
            self.branch_picker.value = selected_branch if selected_branch in versions else None
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

    def _change_install_source(self, _event) -> None:
        is_branch = self.install_source.value == "branch"
        self.version_picker.visible = not is_branch
        self.branch_picker.visible = is_branch
        if is_branch and not self.branch_picker.options:
            self.load_versions(None)
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
        if self.install_source.value == "branch" and not self._selected_branch():
            self.status.value = "Choose a Git branch to install"
            self.page.update()
            return
        self.status.value = "Installing MCP..."
        self.install_button.disabled = True
        self.page.update()
        self._run_background(
            lambda: setup_environment(
                application_directory(),
                runtime_directory(),
                version=self._selected_version(),
                branch=self._selected_branch(),
            ),
            self._finish_install,
        )

    def update(self, _event) -> None:
        if self.install_source.value == "branch" and not self._selected_branch():
            self.status.value = "Choose a Git branch to install"
            self.page.update()
            return
        self.status.value = "Updating MCP..."
        self.update_button.disabled = True
        self.page.update()
        self._run_background(
            lambda: setup_environment(
                application_directory(),
                runtime_directory(),
                version=self._selected_version(),
                branch=self._selected_branch(),
                upgrade=True,
            ),
            self._finish_update,
        )

    def _selected_version(self) -> str | None:
        if self.install_source.value == "branch":
            return None
        return None if self.version_picker.value == "latest" else self.version_picker.value

    def _selected_branch(self) -> str | None:
        return self.branch_picker.value if self.install_source.value == "branch" else None

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
        self.start_button.content = "Stop Server" if running else "Start Server"
        self.start_button.icon = ft.Icons.STOP if running else ft.Icons.PLAY_ARROW
        self.start_button.bgcolor = ft.Colors.RED if running else None
        self.start_button.color = ft.Colors.ON_ERROR if running else None

    def _update_server_state(self, state: ServerState, message: str | None = None) -> None:
        """Update the traffic light indicator and status message."""
        self._server_state = state
        colors = {
            ServerState.STOPPED: ft.Colors.GREY_500,
            ServerState.STARTING: ft.Colors.AMBER_500,
            ServerState.READY: ft.Colors.GREEN_500,
            ServerState.ERROR: ft.Colors.RED_500,
        }
        self.server_status_indicator.bgcolor = colors.get(state, ft.Colors.GREY_500)

        if message:
            self.server_status_text.value = message
        else:
            default_messages = {
                ServerState.STOPPED: "Server stopped",
                ServerState.STARTING: "Starting server...",
                ServerState.READY: self._build_ready_message(),
                ServerState.ERROR: "Server error",
            }
            self.server_status_text.value = default_messages.get(state, "Unknown state")

        # Update text color based on state
        text_colors = {
            ServerState.STOPPED: ft.Colors.ON_SURFACE_VARIANT,
            ServerState.STARTING: ft.Colors.AMBER_700,
            ServerState.READY: ft.Colors.GREEN_700,
            ServerState.ERROR: ft.Colors.RED_700,
        }
        self.server_status_text.color = text_colors.get(state, ft.Colors.ON_SURFACE_VARIANT)

    def _build_ready_message(self) -> str:
        """Build the ready status message with URL, tool count, and AEDT connection."""
        port = self.http_port.value.strip() or "8080"
        parts = [f"Ready • http://127.0.0.1:{port}"]
        if self._aedt_connected and self._aedt_port:
            parts.append(f"AEDT:{self._aedt_port}")
        elif self._aedt_connected:
            parts.append("AEDT connected")
        if self._current_activity:
            parts.append(self._current_activity)
        return " • ".join(parts)

    def _extract_activity(self, message: str) -> str | None:
        """Extract activity from MCP log format: [timestamp] INFO message."""
        match = MCP_INFO_PATTERN.search(message)
        if not match:
            return None

        activity = match.group(1)

        # Normalize whitespace (replace newlines and multiple spaces with single space)
        activity = " ".join(activity.split())

        # Remove file references like "transport.py:363" anywhere in the string
        activity = re.sub(r"\s*\S+\.py:\d+\s*", " ", activity)

        # Clean up any double spaces and strip
        activity = " ".join(activity.split()).strip()

        if not activity:
            return None

        # Truncate long messages
        if len(activity) > 50:
            activity = activity[:47] + "..."

        return activity

    def _process_log_message(self, message: str) -> None:
        """Process a log message to update server state and activity."""
        # Check for MCP ERROR format (highest priority)
        if MCP_ERROR_PATTERN.search(message):
            error_match = MCP_ERROR_PATTERN.search(message)
            error_msg = error_match.group(1).strip() if error_match else "Error"
            if len(error_msg) > 45:
                error_msg = error_msg[:42] + "..."
            self._current_activity = error_msg
            self._update_server_state(ServerState.ERROR, error_msg)
            return

        # Check for AEDT connection (from MCP INFO messages)
        if AEDT_CONNECTED_PATTERN.search(message):
            port_match = AEDT_PORT_PATTERN.search(message)
            if port_match:
                self._aedt_port = port_match.group(1)
            self._aedt_connected = True
            self._current_activity = None  # Clear activity on successful connection
            if self._server_state == ServerState.READY:
                self._update_server_state(ServerState.READY)
            return

        # Check for server ready (Uvicorn started)
        if SERVER_READY_PATTERN.search(message):
            if self._server_state != ServerState.ERROR:
                self._current_activity = None
                self._update_server_state(ServerState.READY)
            return

        # Extract activity only from MCP INFO messages
        activity = self._extract_activity(message)
        if activity:
            self._current_activity = activity
            # Always update to show the activity, regardless of state
            if self._server_state == ServerState.READY:
                # Rebuild the ready message which includes _current_activity
                self._update_server_state(ServerState.READY)
            elif self._server_state in (ServerState.STOPPED, ServerState.STARTING):
                self._update_server_state(ServerState.STARTING, activity)

    def _append_server_log_sync(self, message: str) -> None:
        """Process a log message synchronously (no page.update - caller handles that)."""
        decoded_message = self._decode_unicode_escapes(message)

        # Always add to full log (for copy/debug purposes)
        self.server_log.value += decoded_message

        # Check for Uvicorn ready (non-MCP format)
        if SERVER_READY_PATTERN.search(decoded_message):
            self._flush_mcp_buffer()
            self._process_log_message(decoded_message)
            return

        line = decoded_message.rstrip()
        line_stripped = line.strip()

        # FIRST: Check if this is a new MCP log message [timestamp] - these are NEVER ignored
        if MCP_LOG_START_PATTERN.match(line):
            # Process previous buffered message first
            self._flush_mcp_buffer()
            # Start new buffer
            self._mcp_message_buffer = line
            return

        # SECOND: Check if this is a continuation of MCP message (indented with text)
        if self._mcp_message_buffer and MCP_CONTINUATION_PATTERN.match(decoded_message):
            # This is a continuation line - append to buffer
            self._mcp_message_buffer += " " + line_stripped
            return

        # THIRD: For all other lines, check if they should be ignored
        # But first flush the buffer since the MCP message is complete
        if IGNORE_LINE_PATTERN.search(line_stripped):
            self._flush_mcp_buffer()
            return

        # Any other line - flush buffer if we have one
        if self._mcp_message_buffer:
            self._flush_mcp_buffer()

    def _flush_mcp_buffer(self) -> None:
        """Process and clear the MCP message buffer."""
        if self._mcp_message_buffer:
            self._process_log_message(self._mcp_message_buffer)
            self._mcp_message_buffer = ""

    @staticmethod
    def _decode_unicode_escapes(message: str) -> str:
        return UNICODE_ESCAPE_PATTERN.sub(
            lambda match: chr(int(match.group()[2:], 16)),
            message,
        )

    async def copy_server_log(self, _event) -> None:
        await self.page.clipboard.set(self.server_log.value)

    def scroll_to_latest_log(self, _event) -> None:
        latest_offset = len(self.server_log.value)
        self.server_log.selection = ft.TextSelection(latest_offset, latest_offset)
        self.page.run_task(self.server_log.focus)

    def clear_server_log(self, _event) -> None:
        self.server_log.value = ""
        self._mcp_message_buffer = ""
        # Reset activity but keep current state
        self._current_activity = None
        if self._server_state == ServerState.READY:
            self._update_server_state(ServerState.READY)  # Refresh message
        self.page.update()

    async def _append_server_log_async(self, message: str) -> None:
        self._append_server_log_sync(message)
        self.page.update()

    def _read_server_output(self, process: subprocess.Popen) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            self.page.run_task(self._append_server_log_async, line)

    def start(self, _event) -> None:
        if self.server_process is not None and self.server_process.poll() is None:
            return
        _, command = command_paths(application_directory())
        environment = os.environ.copy()
        if self.debug.value:
            environment["FASTMCP_LOG_LEVEL"] = "DEBUG"
        self.server_log.value = ""
        self._mcp_message_buffer = ""
        self._aedt_port = None
        self._aedt_connected = False
        self._current_activity = None
        self._update_server_state(ServerState.STARTING, "Starting HTTP server...")
        self.server_process = subprocess.Popen(  # nosec B603
            [str(command), *self._server_arguments()],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            **hidden_window_options(),
        )
        threading.Thread(
            target=self._read_server_output,
            args=(self.server_process,),
            daemon=True,
        ).start()
        self.status.value = f"HTTP server running on port {self.http_port.value.strip() or '8080'}"
        self._set_server_button_running(True)
        self.page.update()

    def stop(self, _event) -> None:
        if self.server_process is not None and self.server_process.poll() is None:
            self.server_process.terminate()
        self.server_process = None
        self._aedt_port = None
        self._aedt_connected = False
        self._current_activity = None
        self._update_server_state(ServerState.STOPPED)
        self.status.value = "HTTP server stopped"
        self._set_server_button_running(False)
        self.page.update()

    def install_profiles(self, _event) -> None:
        server_arguments = self._mcp_arguments()
        _, executable = command_paths(application_directory())
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
            self.page.show_dialog(
                ft.SnackBar(content=ft.Text(f"Installed {len(paths)} coding-agent profile(s)"))
            )
        self.page.update()

    def _finish_custom_profile(self, paths, error: str | None) -> None:
        self.custom_profile_button.disabled = False
        if error:
            self.status.value = f"Custom profile installation failed: {error}"
        else:
            self.status.value = f"Installed {len(paths)} custom profile(s)"
        self.page.update()


def launch_gui() -> int:
    """Run the Flet desktop control panel."""
    ft.run(
        lambda page: McpControlPanel(page),
        assets_dir=str(asset_directory()),
        view=ft.AppView.FLET_APP_HIDDEN,
    )
    return 0
