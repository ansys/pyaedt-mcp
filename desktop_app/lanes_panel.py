"""Server-tab section that lists and controls active PyAEDT MCP lanes."""

import asyncio
from collections.abc import Callable
from pathlib import Path
import subprocess  # nosec B404
from typing import Any

import flet as ft
from lanes_client import Lane, LanesClient, registered_lane_count

LANES_POLL_SECONDS = 10
LANES_HELP = (
    "Lanes are shared PyAEDT MCP backends started by coding agents configured with "
    "'ansys-aedt-mcp --lanes'. Each lane owns at most one AEDT session. This section "
    "appears while lanes are registered. Stopping a lane cuts off every agent routed to it."
)

BackgroundRunner = Callable[[Callable[[], Any], Callable[[Any, str | None], None]], None]


class LanesPanel:
    """Show registered lanes and offer stop, reap, reset, and dashboard actions."""

    def __init__(
        self,
        page: ft.Page,
        command: Callable[[], Path],
        run_background: BackgroundRunner,
        help_button: ft.Control,
    ) -> None:
        self.page = page
        self._command = command
        self._run_background = run_background
        self._dashboard_process: subprocess.Popen | None = None
        self._dashboard_url: str | None = None
        self.lanes: list[Lane] = []
        self.summary = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.lane_list = ft.Column(spacing=4, tight=True)
        self.refresh_button = ft.IconButton(
            ft.Icons.REFRESH, tooltip="Refresh lanes", icon_size=18, on_click=self.refresh
        )
        self.dashboard_button = ft.IconButton(
            ft.Icons.OPEN_IN_BROWSER,
            tooltip="Open the lanes dashboard",
            icon_size=18,
            on_click=self.open_dashboard,
        )
        self.reap_button = ft.OutlinedButton(
            "Remove dead lanes", icon=ft.Icons.CLEANING_SERVICES, on_click=self.reap
        )
        self.reset_button = ft.OutlinedButton(
            "Stop all lanes", icon=ft.Icons.STOP_CIRCLE, on_click=self._confirm_reset
        )
        self.container = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Lanes", size=15, weight=ft.FontWeight.W_600),
                            help_button,
                            ft.Container(expand=True),
                            self.dashboard_button,
                            self.refresh_button,
                        ],
                        spacing=0,
                    ),
                    self.summary,
                    self.lane_list,
                    ft.Row([self.reap_button, self.reset_button]),
                ],
                spacing=8,
            ),
            bgcolor=ft.Colors.SURFACE,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=6,
            padding=12,
            visible=registered_lane_count() > 0,
        )

    def _client(self) -> LanesClient:
        return LanesClient(self._command())

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        for control in (self.refresh_button, self.reap_button, self.reset_button):
            control.disabled = busy
        if message:
            self.summary.value = message
        self.page.update()

    def sync_visibility(self) -> bool:
        """Show the section only while lanes are registered; return whether it changed."""
        active = registered_lane_count() > 0
        if active == self.container.visible:
            return False
        self.container.visible = active
        if active:
            self.refresh(None)
        else:
            self.lanes = []
            self.lane_list.controls.clear()
        return True

    async def watch(self) -> None:
        """Poll the lanes registry so the section follows lanes started by agents."""
        while True:
            if self.sync_visibility():
                self.page.update()
            await asyncio.sleep(LANES_POLL_SECONDS)

    def refresh(self, _event) -> None:
        self._set_busy(True, "Loading lanes...")
        self._run_background(lambda: self._client().list_lanes(), self._finish_refresh)

    def _finish_refresh(self, lanes: list[Lane] | None, error: str | None) -> None:
        self.lanes = lanes or []
        self.lane_list.controls = [self._lane_row(lane) for lane in self.lanes]
        if error:
            message = f"Could not read lanes: {error}"
        elif not self.lanes:
            message = "No lanes are registered"
        else:
            unhealthy = sum(not lane.healthy for lane in self.lanes)
            message = f"{len(self.lanes)} lane(s) registered" + (
                f", {unhealthy} not responding" if unhealthy else ""
            )
        self._set_busy(False, message)

    def _lane_row(self, lane: Lane) -> ft.Container:
        aedt = f"AEDT {lane.aedt_port}" if lane.aedt_port else "no AEDT"
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        width=10,
                        height=10,
                        border_radius=5,
                        bgcolor=ft.Colors.GREEN_500 if lane.healthy else ft.Colors.RED_500,
                        tooltip="Running" if lane.healthy else "Not responding",
                    ),
                    ft.Text(lane.lane_id, weight=ft.FontWeight.W_500, expand=True),
                    ft.Text(
                        f"HTTP {lane.http_port} • {aedt} • up {lane.uptime()}",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.IconButton(
                        ft.Icons.STOP,
                        tooltip=f"Stop lane {lane.lane_id}",
                        icon_size=18,
                        icon_color=ft.Colors.RED_500,
                        on_click=lambda _event, lane_id=lane.lane_id: self._confirm_stop(lane_id),
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=4,
            padding=ft.Padding(left=10, top=2, right=2, bottom=2),
        )

    def _confirm(self, title: str, message: str, action: Callable[[], None]) -> None:
        def confirm(_event) -> None:
            self.page.pop_dialog()
            action()

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(title),
                content=ft.Text(message),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda _event: self.page.pop_dialog()),
                    ft.FilledButton("Stop", on_click=confirm),
                ],
            )
        )

    def _confirm_stop(self, lane_id: str) -> None:
        self._confirm(
            "Stop lane",
            f"Stop lane '{lane_id}'? Coding agents routed to it lose their backend. "
            "AEDT sessions launched by the lane are closed too.",
            lambda: self.stop(lane_id),
        )

    def _confirm_reset(self, _event) -> None:
        self._confirm(
            "Stop all lanes",
            "Stop every lane process and clear the lanes registry? "
            "All coding agents using lanes lose their backends.",
            self.reset,
        )

    def stop(self, lane_id: str) -> None:
        self._run_lane_action(f"Stopping lane '{lane_id}'...", lambda client: client.stop(lane_id))

    def reap(self, _event) -> None:
        self._run_lane_action("Removing dead lanes...", lambda client: client.reap())

    def reset(self) -> None:
        self._run_lane_action("Stopping all lanes...", lambda client: client.reset())

    def _run_lane_action(self, message: str, action: Callable[[LanesClient], str]) -> None:
        self._set_busy(True, message)
        self._run_background(lambda: action(self._client()), self._finish_action)

    def _finish_action(self, output: str | None, error: str | None) -> None:
        if error:
            self._set_busy(False, f"Lane action failed: {error}")
            return
        if output:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(output.splitlines()[0])))
        if not self.sync_visibility() and self.container.visible:
            self.refresh(None)
        else:
            self._set_busy(False)

    def _dashboard_running(self) -> bool:
        return self._dashboard_process is not None and self._dashboard_process.poll() is None

    async def open_dashboard(self, _event) -> None:
        if not self._dashboard_running():
            self.dashboard_button.disabled = True
            self.page.update()
            try:
                self._dashboard_process, self._dashboard_url = await asyncio.to_thread(
                    self._client().start_dashboard
                )
            except (OSError, RuntimeError) as error:
                self.summary.value = f"Could not open the lanes dashboard: {error}"
                return
            finally:
                self.dashboard_button.disabled = False
                self.page.update()
        await self.page.launch_url(self._dashboard_url)

    def close(self) -> None:
        """Stop the dashboard server started by this panel."""
        if self._dashboard_process is not None and self._dashboard_process.poll() is None:
            self._dashboard_process.terminate()
        self._dashboard_process = None
