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

"""Tests for coding-agent MCP profile installation."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def agent_profiles():
    script_path = Path(__file__).parents[2] / "desktop_app" / "agent_profiles.py"
    spec = importlib.util.spec_from_file_location("agent_profiles", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the agent profiles script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_vscode_profile_preserves_existing_servers(tmp_path, agent_profiles):
    config_path = tmp_path / ".vscode" / "mcp.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({"servers": {"other": {"type": "http", "url": "http://localhost"}}})
    )

    path = agent_profiles.install_vscode_profile(
        tmp_path, Path(r"C:\Tools\PyAEDT_MCP.exe"), ["--include-context"]
    )

    profile = json.loads(path.read_text())
    assert profile["servers"]["other"]["type"] == "http"
    assert profile["servers"]["pyaedt-mcp"] == {
        "type": "stdio",
        "command": r"C:\Tools\PyAEDT_MCP.exe",
        "args": ["--include-context"],
    }


def test_install_desktop_and_cursor_profiles(tmp_path, agent_profiles):
    executable = tmp_path / "PyAEDT_MCP.exe"

    claude_path = agent_profiles.install_claude_desktop_profile(
        tmp_path / "AppData" / "Claude", executable, []
    )
    cursor_path = agent_profiles.install_cursor_profile(
        tmp_path / "home" / ".cursor", executable, ["--connect"]
    )

    assert json.loads(claude_path.read_text())["mcpServers"]["pyaedt-mcp"]["args"] == []
    assert json.loads(cursor_path.read_text())["mcpServers"]["pyaedt-mcp"]["args"] == [
        "--connect",
    ]


def test_install_copilot_and_claude_code_user_profiles(tmp_path, agent_profiles):
    executable = tmp_path / "PyAEDT_MCP.exe"

    copilot_path = agent_profiles.install_copilot_cli_profile(
        tmp_path / ".copilot", executable, ["--connect"]
    )
    claude_path = agent_profiles.install_claude_code_profile(tmp_path, executable, ["--graphical"])

    assert copilot_path == tmp_path / ".copilot" / "mcp-config.json"
    assert json.loads(copilot_path.read_text())["mcpServers"]["pyaedt-mcp"] == {
        "type": "local",
        "command": str(executable),
        "args": ["--connect"],
        "tools": ["*"],
    }
    assert claude_path == tmp_path / ".claude.json"
    assert json.loads(claude_path.read_text())["mcpServers"]["pyaedt-mcp"]["args"] == [
        "--graphical",
    ]


def test_install_codex_profile_replaces_existing_server(tmp_path, agent_profiles):
    config_path = tmp_path / ".codex" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        '[mcp_servers.pyaedt-mcp]\ncommand = "old.exe"\nargs = []\n\n[features]\nfoo = true\n'
    )

    path = agent_profiles.install_codex_profile(
        config_path.parent, tmp_path / "PyAEDT_MCP.exe", ["--dynamic-tool-discovery"]
    )

    content = path.read_text()
    assert 'command = "old.exe"' not in content
    assert 'args = ["--dynamic-tool-discovery"]' in content
    assert "[features]\nfoo = true" in content


def test_install_http_and_opencode_profiles_in_custom_folders(tmp_path, agent_profiles):
    executable = tmp_path / "PyAEDT_MCP.exe"
    url = "http://127.0.0.1:8080/mcp"
    copilot_directory = tmp_path / "custom-copilot"
    opencode_directory = tmp_path / "custom-opencode"

    copilot_path = agent_profiles.install_copilot_cli_profile(
        copilot_directory, executable, [], transport="http", http_url=url
    )
    opencode_path = agent_profiles.install_opencode_profile(
        opencode_directory, executable, ["--connect"], transport="stdio"
    )

    assert copilot_path == copilot_directory / "mcp-config.json"
    assert json.loads(copilot_path.read_text())["mcpServers"]["pyaedt-mcp"] == {
        "type": "http",
        "url": url,
        "tools": ["*"],
    }
    assert opencode_path == opencode_directory / "opencode.json"
    opencode_profile = json.loads(opencode_path.read_text())
    assert "mcpServers" not in opencode_profile
    assert opencode_profile["mcp"]["pyaedt-mcp"] == {
        "type": "local",
        "command": [str(executable), "--connect"],
    }


def test_install_profile_uses_an_explicit_configuration_filename(tmp_path, agent_profiles):
    executable = tmp_path / "PyAEDT_MCP.exe"
    configuration_file = tmp_path / "profiles" / "custom-mcp.json"

    path = agent_profiles.install_cursor_profile(configuration_file, executable, [])

    assert path == configuration_file
    assert json.loads(path.read_text())["mcpServers"]["pyaedt-mcp"]["command"] == str(executable)
