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

"""Tests for lanes management in the desktop control panel."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import flet as ft
import pytest

DESKTOP_APP_DIRECTORY = Path(__file__).parents[2] / "desktop_app"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, DESKTOP_APP_DIRECTORY / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load the {name} script")
    module = importlib.util.module_from_spec(spec)
    # Only exposed on sys.path for the duration of the import, not the whole test session.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.syspath_prepend(str(DESKTOP_APP_DIRECTORY))
        spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lanes_client():
    return _load("lanes_client")


@pytest.fixture(scope="module")
def lanes_panel():
    return _load("lanes_panel")


@pytest.fixture(autouse=True)
def lanes_state(tmp_path, monkeypatch):
    """Point the per-user lanes state at a scratch directory."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    return tmp_path / "Local" / "ansys-aedt-mcp"


def _register_lanes(state_directory: Path, *names: str) -> None:
    state_directory.mkdir(parents=True, exist_ok=True)
    servers = {name: {"server_id": name, "http_port": 8090} for name in names}
    (state_directory / "registry.json").write_text(
        json.dumps({"schema_version": 1, "servers": servers}), encoding="utf-8"
    )


def _status_entry(name: str, *, healthy: bool = True, **overrides) -> dict:
    return {
        "server_id": name,
        "http_port": 8090,
        "aedt_gpc_port": 50051,
        "pid": 1234,
        "listening": healthy,
        "pid_alive": healthy,
        "started_at": 0.0,
        "auth": "token",
        **overrides,
    }


class FakePage:
    """Provide the minimal Flet page surface used by the lanes panel."""

    def __init__(self) -> None:
        self.update_count = 0
        self.dialog = None
        self.launch_url = AsyncMock()

    def update(self) -> None:
        self.update_count += 1

    def show_dialog(self, dialog) -> None:
        self.dialog = dialog

    def pop_dialog(self) -> None:
        self.dialog = None


class FakeLanesClient:
    """Record lane actions instead of running the MCP command."""

    def __init__(self, lanes=None, error: str | None = None) -> None:
        self.lanes = lanes or []
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    def list_lanes(self):
        self.calls.append(("list",))
        if self.error:
            raise RuntimeError(self.error)
        return self.lanes

    def stop(self, lane_id: str) -> str:
        self.calls.append(("stop", lane_id))
        return f"Stopped lane {lane_id!r}"

    def reap(self) -> str:
        self.calls.append(("reap",))
        return "Dropped 1 dead lane(s), kept 0."

    def reset(self) -> str:
        self.calls.append(("reset",))
        return "Reset done."


def _run_now(action, complete) -> None:
    try:
        result = action()
    except Exception as error:
        complete(None, str(error))
    else:
        complete(result, None)


@pytest.fixture
def make_panel(lanes_panel, lanes_client, monkeypatch, tmp_path):
    def factory(client: FakeLanesClient):
        monkeypatch.setattr(lanes_panel, "LanesClient", lambda _command: client)
        page = FakePage()
        panel = lanes_panel.LanesPanel(
            page, lambda: tmp_path / "ansys-aedt-mcp.exe", _run_now, ft.Text("help")
        )
        return panel, page

    return factory


# ---------------------------------------------------------------------------
# lanes_client
# ---------------------------------------------------------------------------


def test_registered_lane_count_reads_the_per_user_registry(lanes_client, lanes_state):
    assert lanes_client.registered_lane_count() == 0

    _register_lanes(lanes_state, "patch", "filter")

    assert lanes_client.lanes_registry_path() == lanes_state / "registry.json"
    assert lanes_client.registered_lane_count() == 2


def test_registered_lane_count_ignores_a_corrupt_registry(lanes_client, lanes_state):
    lanes_state.mkdir(parents=True)
    (lanes_state / "registry.json").write_text("{not json", encoding="utf-8")

    assert lanes_client.registered_lane_count() == 0


@pytest.mark.parametrize(
    ("server_arguments", "expected"),
    [
        ([], ["--lanes"]),
        (["--graphical"], ["--lanes", "--", "--graphical"]),
    ],
)
def test_lanes_profile_arguments_forward_server_options(lanes_client, server_arguments, expected):
    assert lanes_client.lanes_profile_arguments(server_arguments) == expected


def test_lane_health_and_uptime(lanes_client):
    lane = lanes_client.Lane.from_status(_status_entry("patch", started_at=100.0))

    assert lane.healthy
    assert lane.aedt_port == 50051
    assert lane.uptime(now=100.0 + 3 * 3600 + 12 * 60) == "3h 12m"
    assert lane.uptime(now=100.0 + 5 * 60) == "5m"
    assert not lanes_client.Lane.from_status(_status_entry("x", healthy=False)).healthy
    assert lanes_client.Lane.from_status(_status_entry("x", started_at=None)).uptime() == "?"


def test_client_lists_lanes_from_status_json(lanes_client, monkeypatch, tmp_path):
    command = tmp_path / "ansys-aedt-mcp.exe"
    command.touch()
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        status = {"servers": [_status_entry("zeta"), _status_entry("alpha")]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(status), stderr="")

    monkeypatch.setattr(lanes_client.subprocess, "run", fake_run)

    lanes = lanes_client.LanesClient(command).list_lanes()

    assert calls == [[str(command), "--lanes", "status", "--json"]]
    assert [lane.lane_id for lane in lanes] == ["alpha", "zeta"]


@pytest.mark.parametrize(
    ("method", "arguments", "expected"),
    [
        ("stop", ("patch",), ["stop", "patch"]),
        ("reap", (), ["reap"]),
        ("reset", (), ["reset", "--kill", "--yes"]),
    ],
)
def test_client_actions_run_lanes_subcommands(
    lanes_client, monkeypatch, tmp_path, method, arguments, expected
):
    command = tmp_path / "ansys-aedt-mcp.exe"
    command.touch()
    calls = []
    monkeypatch.setattr(
        lanes_client.subprocess,
        "run",
        lambda args, **_kw: calls.append(args) or SimpleNamespace(returncode=0, stdout="ok\n"),
    )

    assert getattr(lanes_client.LanesClient(command), method)(*arguments) == "ok"
    assert calls == [[str(command), "--lanes", *expected]]


def test_client_reports_the_last_error_line(lanes_client, monkeypatch, tmp_path):
    command = tmp_path / "ansys-aedt-mcp.exe"
    command.touch()
    monkeypatch.setattr(
        lanes_client.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=2, stdout="", stderr="usage: ...\nerror: unrecognized arguments: stop"
        ),
    )

    with pytest.raises(RuntimeError, match="unrecognized arguments: stop"):
        lanes_client.LanesClient(command).stop("patch")


def test_client_requires_an_installed_command(lanes_client, tmp_path):
    client = lanes_client.LanesClient(tmp_path / "missing.exe")

    with pytest.raises(RuntimeError, match="Install PyAEDT MCP"):
        client.list_lanes()
    with pytest.raises(RuntimeError, match="Install PyAEDT MCP"):
        client.start_dashboard()


def test_client_starts_the_dashboard_on_a_free_port(lanes_client, monkeypatch, tmp_path):
    command = tmp_path / "ansys-aedt-mcp.exe"
    command.touch()
    started = {}

    def fake_popen(arguments, **kwargs):
        started["arguments"] = arguments
        return SimpleNamespace(
            stdout=io.StringIO("ansys-aedt-mcp lanes dashboard: http://127.0.0.1:51234/  ...\n")
        )

    monkeypatch.setattr(lanes_client.subprocess, "Popen", fake_popen)

    process, url = lanes_client.LanesClient(command).start_dashboard()

    assert url == "http://127.0.0.1:51234/"
    assert started["arguments"] == [
        str(command),
        "--lanes",
        "dashboard",
        "--port",
        "0",
        "--no-browser",
    ]
    assert process.stdout is not None


def test_client_kills_a_dashboard_that_fails_to_start(lanes_client, monkeypatch, tmp_path):
    command = tmp_path / "ansys-aedt-mcp.exe"
    command.touch()
    killed = []
    monkeypatch.setattr(
        lanes_client.subprocess,
        "Popen",
        lambda *_a, **_kw: SimpleNamespace(
            stdout=io.StringIO("Cannot bind 127.0.0.1:0\n"), kill=lambda: killed.append(True)
        ),
    )

    with pytest.raises(RuntimeError, match="Cannot bind"):
        lanes_client.LanesClient(command).start_dashboard()
    assert killed == [True]


# ---------------------------------------------------------------------------
# lanes_panel
# ---------------------------------------------------------------------------


def test_panel_is_hidden_without_registered_lanes(make_panel):
    panel, _page = make_panel(FakeLanesClient())

    assert not panel.container.visible


def test_panel_appears_and_lists_lanes_once_lanes_are_registered(make_panel, lanes_state):
    client = FakeLanesClient(
        [
            SimpleNamespace(
                lane_id="patch", http_port=8090, aedt_port=50051, healthy=True, uptime=lambda: "5m"
            ),
            SimpleNamespace(
                lane_id="filter", http_port=8091, aedt_port=None, healthy=False, uptime=lambda: "?"
            ),
        ]
    )
    panel, _page = make_panel(client)

    _register_lanes(lanes_state, "patch", "filter")

    assert panel.sync_visibility()
    assert panel.container.visible
    assert client.calls == [("list",)]
    assert len(panel.lane_list.controls) == 2
    assert panel.summary.value == "2 lane(s) registered, 1 not responding"
    assert not panel.sync_visibility()


def test_panel_hides_again_when_the_last_lane_is_gone(make_panel, lanes_state):
    _register_lanes(lanes_state, "patch")
    panel, _page = make_panel(FakeLanesClient())
    assert panel.container.visible

    (lanes_state / "registry.json").unlink()

    assert panel.sync_visibility()
    assert not panel.container.visible
    assert panel.lane_list.controls == []


def test_panel_reports_status_errors(make_panel, lanes_state):
    _register_lanes(lanes_state, "patch")
    panel, _page = make_panel(FakeLanesClient(error="registry locked"))

    panel.refresh(None)

    assert panel.summary.value == "Could not read lanes: registry locked"
    assert not panel.refresh_button.disabled


def test_stopping_a_lane_asks_for_confirmation(make_panel, lanes_state):
    _register_lanes(lanes_state, "patch")
    client = FakeLanesClient()
    panel, page = make_panel(client)

    panel._confirm_stop("patch")

    assert "Stop lane 'patch'?" in page.dialog.content.value
    assert client.calls == []
    cancel, confirm = page.dialog.actions
    confirm.on_click(None)
    assert client.calls[0] == ("stop", "patch")
    assert page.dialog.content.value == "Stopped lane 'patch'"


def test_stop_all_lanes_resets_the_registry(make_panel, lanes_state):
    _register_lanes(lanes_state, "patch")
    client = FakeLanesClient()
    panel, page = make_panel(client)

    panel._confirm_reset(None)
    (lanes_state / "registry.json").unlink()
    page.dialog.actions[1].on_click(None)

    assert client.calls == [("reset",)]
    assert not panel.container.visible


def test_reap_refreshes_the_remaining_lanes(make_panel, lanes_state):
    _register_lanes(lanes_state, "patch")
    client = FakeLanesClient()
    panel, _page = make_panel(client)

    panel.reap(None)

    assert client.calls == [("reap",), ("list",)]
    assert panel.summary.value == "No lanes are registered"


async def test_dashboard_is_started_once_and_opened_in_the_browser(
    make_panel, lanes_panel, monkeypatch
):
    panel, page = make_panel(FakeLanesClient())
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: setattr(process, "done", True))
    starts = []

    def start_dashboard(_client):
        starts.append(True)
        return process, "http://127.0.0.1:51234/"

    monkeypatch.setattr(
        lanes_panel,
        "LanesClient",
        lambda _command: SimpleNamespace(start_dashboard=lambda: start_dashboard(None)),
    )

    await panel.open_dashboard(None)
    await panel.open_dashboard(None)
    panel.close()

    assert starts == [True]
    assert page.launch_url.await_count == 2
    page.launch_url.assert_awaited_with("http://127.0.0.1:51234/")
    assert process.done


async def test_dashboard_start_failure_is_reported(make_panel, lanes_panel, monkeypatch):
    panel, page = make_panel(FakeLanesClient())

    def fail():
        raise RuntimeError("Cannot bind")

    monkeypatch.setattr(
        lanes_panel, "LanesClient", lambda _command: SimpleNamespace(start_dashboard=fail)
    )

    await panel.open_dashboard(None)

    assert panel.summary.value == "Could not open the lanes dashboard: Cannot bind"
    page.launch_url.assert_not_awaited()
    assert not panel.dashboard_button.disabled


def test_closing_without_a_dashboard_is_a_no_op(make_panel):
    panel, _page = make_panel(FakeLanesClient())

    panel.close()
