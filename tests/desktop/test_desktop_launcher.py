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

"""Tests for the Windows executable bootstrap script."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import types

import pytest


@pytest.fixture(scope="module")
def desktop_launcher():
    script_path = Path(__file__).parents[2] / "desktop_app" / "desktop_launcher.py"
    spec = importlib.util.spec_from_file_location("desktop_launcher", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the desktop launcher script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_application_directory_uses_appdata(monkeypatch, desktop_launcher):
    monkeypatch.setenv("APPDATA", r"C:\Users\example\AppData\Roaming")

    assert desktop_launcher.application_directory() == Path(
        r"C:\Users\example\AppData\Roaming\.pyaedt_mcp"
    )


def test_setup_environment_creates_venv_and_installs_package(
    monkeypatch, tmp_path, desktop_launcher
):
    app_directory = tmp_path / ".pyaedt_mcp"
    runtime_directory = tmp_path / "runtime"
    embedded_python = runtime_directory / "python" / "python.exe"
    uv_executable = runtime_directory / "uv" / "uv.exe"
    embedded_python.parent.mkdir(parents=True)
    uv_executable.parent.mkdir()
    embedded_python.touch()
    uv_executable.touch()
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        if command[1:3] == ["pip", "install"]:
            _, mcp_executable = desktop_launcher.command_paths(app_directory)
            mcp_executable.parent.mkdir(parents=True)
            mcp_executable.touch()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(desktop_launcher.subprocess, "run", fake_run)

    mcp_executable = desktop_launcher.setup_environment(app_directory, runtime_directory)

    assert mcp_executable.is_file()
    assert commands[0][0][1] == "venv"
    assert commands[1][0][1:3] == ["pip", "install"]
    assert commands[1][0][-1] == "ansys-aedt-mcp"
    assert commands[0][1]["env"]["UV_NO_MANAGED_PYTHON"] == "1"
    assert commands[0][1]["creationflags"] == desktop_launcher.subprocess.CREATE_NO_WINDOW
    assert commands[1][1]["creationflags"] == desktop_launcher.subprocess.CREATE_NO_WINDOW


def test_setup_environment_reuses_existing_command(monkeypatch, tmp_path, desktop_launcher):
    app_directory = tmp_path / ".pyaedt_mcp"
    _, mcp_executable = desktop_launcher.command_paths(app_directory)
    mcp_executable.parent.mkdir(parents=True)
    mcp_executable.touch()
    monkeypatch.setattr(desktop_launcher.subprocess, "run", pytest.fail)

    assert desktop_launcher.setup_environment(app_directory, tmp_path / "runtime") == mcp_executable


def test_setup_environment_updates_selected_version(monkeypatch, tmp_path, desktop_launcher):
    app_directory = tmp_path / ".pyaedt_mcp"
    python_executable, mcp_executable = desktop_launcher.command_paths(app_directory)
    python_executable.parent.mkdir(parents=True)
    python_executable.touch()
    mcp_executable.touch()
    runtime_directory = tmp_path / "runtime"
    embedded_python = runtime_directory / "python" / "python.exe"
    uv_executable = runtime_directory / "uv" / "uv.exe"
    embedded_python.parent.mkdir(parents=True)
    uv_executable.parent.mkdir()
    embedded_python.touch()
    uv_executable.touch()
    commands = []
    monkeypatch.setattr(
        desktop_launcher.subprocess,
        "run",
        lambda command, **kwargs: (
            commands.append(command) or subprocess.CompletedProcess(command, 0)
        ),
    )

    desktop_launcher.setup_environment(
        app_directory, runtime_directory, version="1.2.3", upgrade=True
    )

    assert commands == [
        [
            str(uv_executable),
            "pip",
            "install",
            "--python",
            str(python_executable),
            "--index-strategy",
            "unsafe-best-match",
            "--upgrade",
            "ansys-aedt-mcp==1.2.3",
        ]
    ]


def test_main_forwards_arguments(monkeypatch, tmp_path, desktop_launcher):
    mcp_executable = tmp_path / "ansys-aedt-mcp.exe"
    monkeypatch.setattr(desktop_launcher, "application_directory", lambda: tmp_path)
    monkeypatch.setattr(desktop_launcher, "runtime_directory", lambda: tmp_path)
    monkeypatch.setattr(desktop_launcher, "setup_environment", lambda *_: mcp_executable)
    command = []
    monkeypatch.setattr(
        desktop_launcher.subprocess, "call", lambda value: command.append(value) or 7
    )

    assert desktop_launcher.main(["--server", "--transport", "http"]) == 7
    assert command == [[str(mcp_executable), "--transport", "http"]]


def test_main_opens_ui_without_server_mode(monkeypatch, desktop_launcher):
    ui_module = types.ModuleType("desktop_ui")
    ui_module.launch_gui = lambda: 3
    monkeypatch.setitem(sys.modules, "desktop_ui", ui_module)

    assert desktop_launcher.main([]) == 3
