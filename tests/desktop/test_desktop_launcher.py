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
import zipfile

import pytest


@pytest.fixture(scope="module")
def desktop_launcher():
    desktop_app_directory = Path(__file__).parents[2] / "desktop_app"
    script_path = desktop_app_directory / "desktop_launcher.py"
    spec = importlib.util.spec_from_file_location("desktop_launcher", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the desktop launcher script")
    module = importlib.util.module_from_spec(spec)
    # Only exposed on sys.path for the duration of the import, not the whole test session.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.syspath_prepend(str(desktop_app_directory))
        spec.loader.exec_module(module)
    return module


def test_application_directory_uses_appdata(monkeypatch, desktop_launcher):
    monkeypatch.setenv("APPDATA", r"C:\Users\example\AppData\Roaming")

    assert (
        desktop_launcher.application_directory()
        == Path(r"C:\Users\example\AppData\Roaming") / ".pyaedt_mcp"
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
    assert commands[0][1]["check"] is True
    assert commands[1][1]["check"] is True
    for key, value in desktop_launcher.hidden_window_options().items():
        assert commands[0][1][key] == value
        assert commands[1][1][key] == value


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


def test_setup_environment_installs_selected_branch(monkeypatch, tmp_path, desktop_launcher):
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
        app_directory, runtime_directory, branch="feat/desktop-manager", upgrade=True
    )

    assert commands[0][-1] == (
        "ansys-aedt-mcp @ git+https://github.com/ansys/pyaedt-mcp.git@feat/desktop-manager"
    )


def test_setup_environment_reports_uv_install_error(monkeypatch, tmp_path, desktop_launcher):
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

    def fake_run(command, **_kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="Git executable not found")

    monkeypatch.setattr(desktop_launcher.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Could not install ansys-aedt-mcp: Git executable"):
        desktop_launcher.setup_environment(
            app_directory, runtime_directory, branch="main", upgrade=True
        )


def test_setup_environment_installs_from_a_local_wheelhouse(
    monkeypatch, tmp_path, desktop_launcher
):
    app_directory = tmp_path / ".pyaedt_mcp"
    python_executable, mcp_executable = desktop_launcher.command_paths(app_directory)
    python_executable.parent.mkdir(parents=True)
    python_executable.touch()
    runtime_directory = tmp_path / "runtime"
    (runtime_directory / "python").mkdir(parents=True)
    (runtime_directory / "uv").mkdir()
    (runtime_directory / "python" / "python.exe").touch()
    uv_executable = runtime_directory / "uv" / "uv.exe"
    uv_executable.touch()
    wheelhouse = tmp_path / "ansys_aedt_mcp-wheelhouse-windows-3.13.zip"
    with zipfile.ZipFile(wheelhouse, "w") as archive:
        archive.writestr("placeholder.whl", "")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["pip", "install"]:
            mcp_executable.touch()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(desktop_launcher.subprocess, "run", fake_run)

    desktop_launcher.setup_environment(app_directory, runtime_directory, wheelhouse=str(wheelhouse))

    assert commands == [
        [
            str(uv_executable),
            "pip",
            "install",
            "--python",
            str(python_executable),
            "--index-strategy",
            "unsafe-best-match",
            "--no-index",
            "--find-links",
            str(app_directory / "wheelhouse" / wheelhouse.stem),
            "ansys-aedt-mcp",
        ]
    ]


def test_validate_wheelhouse_rejects_another_python_version(tmp_path, desktop_launcher):
    wheelhouse = tmp_path / "ansys_aedt_mcp-wheelhouse-windows-3.12.zip"

    with pytest.raises(RuntimeError, match="Python 3.13 wheelhouse"):
        desktop_launcher.validate_wheelhouse(wheelhouse)


def test_setup_environment_rejects_version_and_branch(tmp_path, desktop_launcher):
    with pytest.raises(ValueError, match="either a package version or a Git branch"):
        desktop_launcher.setup_environment(
            tmp_path / ".pyaedt_mcp", tmp_path / "runtime", version="1.2.3", branch="main"
        )


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


@pytest.mark.parametrize("root_python", [False, True])
def test_custom_environment_is_used_without_creating_a_venv(
    monkeypatch, tmp_path, desktop_launcher, root_python
):
    app_directory = tmp_path / "app"
    directory = tmp_path / "existing environment"
    (directory / "Scripts").mkdir(parents=True)
    python = directory / "python.exe" if root_python else directory / "Scripts" / "python.exe"
    python.touch()
    command = directory / "Scripts" / "ansys-aedt-mcp.exe"
    command.touch()
    sys.modules["desktop_settings"].save_settings(
        app_directory, offline_install=False, custom_environment=str(directory)
    )
    monkeypatch.setattr(desktop_launcher.subprocess, "run", pytest.fail)

    assert desktop_launcher.command_paths(app_directory) == (python, command)
    assert desktop_launcher.setup_environment(app_directory, tmp_path / "runtime") == command
    assert not (app_directory / ".venv").exists()


def test_invalid_custom_environment_is_not_recreated(monkeypatch, tmp_path, desktop_launcher):
    app_directory = tmp_path / "app"
    directory = tmp_path / "missing"
    sys.modules["desktop_settings"].save_settings(
        app_directory, offline_install=False, custom_environment=str(directory)
    )
    monkeypatch.setattr(desktop_launcher.subprocess, "run", pytest.fail)

    with pytest.raises(RuntimeError, match="Select a Python environment folder"):
        desktop_launcher.setup_environment(app_directory, tmp_path / "runtime")

    assert not directory.exists()
    assert not (app_directory / ".venv").exists()


def test_install_targets_custom_python_without_creating_environment(
    monkeypatch, tmp_path, desktop_launcher
):
    app_directory = tmp_path / "app"
    directory = tmp_path / "existing"
    (directory / "Scripts").mkdir(parents=True)
    python = directory / "Scripts" / "python.exe"
    python.touch()
    command = directory / "Scripts" / "ansys-aedt-mcp.exe"
    sys.modules["desktop_settings"].save_settings(
        app_directory, offline_install=False, custom_environment=str(directory)
    )
    runtime = tmp_path / "runtime"
    (runtime / "python").mkdir(parents=True)
    (runtime / "python" / "python.exe").touch()
    (runtime / "uv").mkdir()
    (runtime / "uv" / "uv.exe").touch()
    commands = []

    def fake_run(arguments, **kwargs):
        commands.append(arguments)
        command.touch()
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(desktop_launcher.subprocess, "run", fake_run)

    assert desktop_launcher.setup_environment(app_directory, runtime, version="1.2.3") == command
    assert len(commands) == 1
    assert commands[0][1:5] == ["pip", "install", "--python", str(python)]
    assert not (app_directory / ".venv").exists()


def test_server_mode_uses_persisted_custom_environment(monkeypatch, tmp_path, desktop_launcher):
    directory = tmp_path / "existing"
    (directory / "Scripts").mkdir(parents=True)
    (directory / "Scripts" / "python.exe").touch()
    command = directory / "Scripts" / "ansys-aedt-mcp.exe"
    command.touch()
    sys.modules["desktop_settings"].save_settings(
        tmp_path, offline_install=False, custom_environment=str(directory)
    )
    monkeypatch.setattr(desktop_launcher, "application_directory", lambda: tmp_path)
    monkeypatch.setattr(desktop_launcher.subprocess, "run", pytest.fail)
    calls = []
    monkeypatch.setattr(desktop_launcher.subprocess, "call", lambda args: calls.append(args) or 0)

    assert desktop_launcher.main(["--server", "--transport", "stdio"]) == 0
    assert calls == [[str(command), "--transport", "stdio"]]


def test_installed_version_reads_custom_environment(tmp_path, desktop_launcher):
    directory = tmp_path / "existing"
    metadata = directory / "Lib" / "site-packages" / "ansys_aedt_mcp-1.2.3.dist-info" / "METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("Version: 1.2.3\n", encoding="utf-8")
    sys.modules["desktop_settings"].save_settings(
        tmp_path, offline_install=False, custom_environment=str(directory)
    )

    assert desktop_launcher.installed_version(tmp_path) == "1.2.3"
