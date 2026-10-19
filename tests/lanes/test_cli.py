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

"""Tests for the ``--lanes`` dispatch of the regular CLI and the lane backend hooks."""

import asyncio
import json
import logging
import os
import sys
from unittest.mock import MagicMock

import pytest

from ansys.aedt.mcp import server
from ansys.aedt.mcp.lanes import aedt_compat, backend, cli, proxy

from .conftest import HOST


def _close_coroutine(coro):
    """Stand in for ``asyncio.run`` without running anything."""
    coro.close()


@pytest.fixture
def no_run(monkeypatch):
    """Replace ``asyncio.run`` so no server or proxy actually starts."""
    logger = logging.getLogger("ansys.aedt.mcp.lanes")
    monkeypatch.setattr(logger, "handlers", list(logger.handlers))
    monkeypatch.setattr(logger, "level", logger.level)
    fake = MagicMock(side_effect=_close_coroutine)
    monkeypatch.setattr(asyncio, "run", fake)
    return fake


@pytest.fixture
def restore_app_auth():
    """Restore ``app.auth``, since ``app`` is a module-level singleton."""
    saved = server.app.auth
    yield server.app
    server.app.auth = saved


# ---------------------------------------------------------------------------
# --lanes flag detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),
        (["--transport", "http"], None),
        (["--lanes"], []),
        (["--lanes", "status", "--json"], ["status", "--json"]),
        (["--http-host", "0.0.0.0", "--lanes"], ["--http-host", "0.0.0.0"]),
        (["--lanes", "--", "--graphical"], ["--", "--graphical"]),
        (["--", "--lanes"], None),
        (["--graphical", "--", "--lanes"], None),
    ],
)
def test_pop_lanes_flag(argv, expected):
    original = list(argv)
    assert server._pop_lanes_flag(argv) == expected
    assert argv == original


@pytest.mark.unit
def test_lanes_flag_dispatches_to_lanes_cli(monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(argv) or 0)

    server.launcher(["--lanes", "status", "--json"])

    assert seen == [["status", "--json"]]


@pytest.mark.unit
def test_lanes_nonzero_exit_code_is_raised(monkeypatch):
    monkeypatch.setattr(cli, "main", lambda argv: 3)

    with pytest.raises(SystemExit) as exc_info:
        server.launcher(["--lanes", "reap"])
    assert exc_info.value.code == 3


@pytest.mark.unit
def test_default_launcher_does_not_run_lanes(monkeypatch, no_run, restore_app_auth):
    monkeypatch.delenv(backend.TOKEN_ENV, raising=False)
    monkeypatch.setattr(cli, "main", lambda argv: pytest.fail("lanes CLI must not run"))
    restore_app_auth.auth = None

    server.launcher([])

    no_run.assert_called_once()
    assert restore_app_auth.auth is None


@pytest.mark.unit
def test_http_without_token_keeps_server_unauthenticated(monkeypatch, no_run, restore_app_auth):
    monkeypatch.delenv(backend.TOKEN_ENV, raising=False)
    restore_app_auth.auth = None

    server.launcher(["--transport", "http"])

    no_run.assert_called_once()
    assert restore_app_auth.auth is None


@pytest.mark.unit
def test_http_with_token_becomes_a_lane_backend(monkeypatch, no_run, restore_app_auth):
    install = MagicMock()
    monkeypatch.setattr(aedt_compat, "install", install)
    monkeypatch.setenv(backend.TOKEN_ENV, "s3cret")
    restore_app_auth.auth = None

    server.launcher(["--transport", "http"])

    no_run.assert_called_once()
    install.assert_called_once_with()
    assert backend.TOKEN_ENV not in os.environ
    assert restore_app_auth.auth is not None


# ---------------------------------------------------------------------------
# apply_lane_backend_hooks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_apply_hooks_without_token_is_a_no_op(monkeypatch, restore_app_auth):
    monkeypatch.delenv(backend.TOKEN_ENV, raising=False)
    monkeypatch.setattr(aedt_compat, "install", lambda: pytest.fail("must not patch PyAEDT"))
    restore_app_auth.auth = None

    assert backend.is_lane_backend() is False
    assert backend.apply_lane_backend_hooks(restore_app_auth) is False
    assert restore_app_auth.auth is None


@pytest.mark.unit
def test_apply_hooks_pops_token_and_installs_verifier(monkeypatch, restore_app_auth):
    monkeypatch.setattr(aedt_compat, "install", MagicMock())
    monkeypatch.setenv(backend.TOKEN_ENV, "s3cret")
    assert backend.is_lane_backend() is True

    assert backend.apply_lane_backend_hooks(restore_app_auth) is True

    assert backend.TOKEN_ENV not in os.environ
    verifier = restore_app_auth.auth
    assert asyncio.run(verifier.verify_token("s3cret")) is not None
    assert asyncio.run(verifier.verify_token("s3cret-")) is None
    assert asyncio.run(verifier.verify_token("")) is None


@pytest.mark.unit
def test_apply_hooks_survives_failing_aedt_fixes(monkeypatch, restore_app_auth, capsys):
    def _boom():
        raise RuntimeError("no pyaedt")

    monkeypatch.setattr(aedt_compat, "install", _boom)
    monkeypatch.setenv(backend.TOKEN_ENV, "s3cret")

    assert backend.apply_lane_backend_hooks(restore_app_auth) is True
    assert restore_app_auth.auth is not None
    assert "AEDT version fixes not applied" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Proxy options
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_build_proxy(monkeypatch, no_run):
    """Record ``proxy.build_proxy`` arguments without building anything."""
    calls: list[dict] = []

    async def _build(**kwargs):
        calls.append(kwargs)
        raise AssertionError("not reached: asyncio.run is patched")

    monkeypatch.setattr(proxy, "build_proxy", _build)
    return calls


@pytest.mark.unit
def test_proxy_options_reach_build_proxy(monkeypatch, no_run):
    seen: dict = {}

    async def _build(**kwargs):
        seen.update(kwargs)
        return MagicMock(run_stdio_async=MagicMock(side_effect=lambda **_: asyncio.sleep(0)))

    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    no_run.side_effect = _run
    monkeypatch.setattr(proxy, "build_proxy", _build)

    server.launcher(
        [
            "--lanes",
            "--http-host",
            "127.0.0.2",
            "--startup-timeout",
            "5",
            "--probe-timeout",
            "2",
            "--handshake-timeout",
            "1",
            "--",
            "--graphical",
            "--include-context",
        ]
    )

    assert seen == {
        "host": "127.0.0.2",
        "startup_timeout": 5.0,
        "backend_args": ["--graphical", "--include-context"],
        "probe_timeout": 2.0,
        "handshake_timeout": 1.0,
    }


@pytest.mark.unit
def test_lanes_rejects_dynamic_tool_discovery(fake_build_proxy, capsys):
    with pytest.raises(SystemExit) as exc_info:
        server.launcher(["--lanes", "--", "--dynamic-tool-discovery"])
    assert exc_info.value.code == 2
    assert "--dynamic-tool-discovery is not supported" in capsys.readouterr().err
    assert fake_build_proxy == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "forwarded",
    [["--http-port", "9000"], ["--http-port=9000"], ["--transport", "stdio"], ["--lanes"]],
)
def test_lanes_rejects_reserved_backend_args(fake_build_proxy, capsys, forwarded):
    with pytest.raises(SystemExit) as exc_info:
        server.launcher(["--lanes", "--", *forwarded])
    assert exc_info.value.code == 2
    assert "cannot be forwarded" in capsys.readouterr().err


@pytest.mark.unit
def test_lanes_rejects_bogus_aedt_version(fake_build_proxy, monkeypatch, capsys):
    monkeypatch.delenv(aedt_compat.VERSION_ENV, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        server.launcher(["--lanes", "--aedt-version", "bogus"])
    assert exc_info.value.code == 2
    assert "--aedt-version" in capsys.readouterr().err
    assert aedt_compat.VERSION_ENV not in os.environ


@pytest.mark.unit
@pytest.mark.parametrize(("value", "expected"), [("271", "2027.1"), ("Latest", "latest")])
def test_lanes_valid_aedt_version_sets_env(fake_build_proxy, no_run, monkeypatch, value, expected):
    monkeypatch.delenv(aedt_compat.VERSION_ENV, raising=False)

    server.launcher(["--lanes", "--aedt-version", value])

    assert os.environ[aedt_compat.VERSION_ENV] == expected
    no_run.assert_called_once()


# ---------------------------------------------------------------------------
# Recovery subcommands
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_status_json_does_not_leak_token(isolated_state, capsys):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=8123, auth_token="t0ps3cret")
    )

    server.launcher(["--lanes", "status", "--json"])

    out = capsys.readouterr().out
    assert "t0ps3cret" not in out
    payload = json.loads(out)
    assert payload["registry_path"] == str(isolated_state.registry_path())
    (row,) = payload["servers"]
    assert row["server_id"] == "work"
    assert row["auth"] == "token"
    assert "auth_token" not in row
    assert row["listening"] is False
    assert row["pid_alive"] is False


@pytest.mark.unit
def test_status_text_output(isolated_state, capsys):
    server.launcher(["--lanes", "status"])
    assert "(no registered lanes)" in capsys.readouterr().out

    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=8123, auth_token="t0ps3cret")
    )
    server.launcher(["--lanes", "status"])
    out = capsys.readouterr().out
    assert "1 lane(s)" in out
    assert "work" in out
    assert "t0ps3cret" not in out


@pytest.mark.unit
def test_stop_subcommand_kills_and_removes_the_lane(isolated_state, monkeypatch, capsys):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="work", http_port=8123, pid=4242)
    )
    killed = []
    monkeypatch.setattr(
        isolated_state, "kill_pid", lambda pid, timeout: killed.append((pid, timeout)) or True
    )

    server.launcher(["--lanes", "stop", "work", "--timeout", "3"])

    assert killed == [(4242, 3.0)]
    assert "Stopped lane 'work': killed=True removed=True pid=4242" in capsys.readouterr().out
    assert isolated_state.list_entries() == []


@pytest.mark.unit
def test_stop_subcommand_unknown_lane_fails(capsys):
    with pytest.raises(SystemExit) as exc_info:
        server.launcher(["--lanes", "stop", "ghost"])

    assert exc_info.value.code == 1
    assert "Lane 'ghost' is not registered." in capsys.readouterr().out


@pytest.mark.unit
def test_reap_subcommand(isolated_state, capsys):
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="dead", http_port=8123))

    server.launcher(["--lanes", "reap"])

    out = capsys.readouterr().out
    assert "Dropped 1 dead lane(s), kept 0." in out
    assert "drop: dead" in out
    assert isolated_state.list_entries() == []


@pytest.mark.unit
def test_reset_with_yes(isolated_state, monkeypatch, capsys):
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="work", http_port=8123))
    isolated_state.lockfile_path().touch()
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("must not prompt"))

    server.launcher(["--lanes", "reset", "--yes", "--unlock"])

    out = capsys.readouterr().out
    assert "dropped=1" in out
    assert "unlocked=True" in out
    assert isolated_state.list_entries() == []


@pytest.mark.unit
def test_reset_prompts_and_aborts(isolated_state, monkeypatch, capsys):
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="work", http_port=8123))
    monkeypatch.setattr("builtins.input", lambda *_: "n")

    with pytest.raises(SystemExit) as exc_info:
        server.launcher(["--lanes", "reset"])

    assert exc_info.value.code == 1
    assert "Aborted" in capsys.readouterr().out
    assert [entry.server_id for entry in isolated_state.list_entries()] == ["work"]


@pytest.mark.unit
def test_reset_prompt_accepts_yes(isolated_state, monkeypatch):
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="work", http_port=8123))
    monkeypatch.setattr("builtins.input", lambda *_: "y")

    server.launcher(["--lanes", "reset"])

    assert isolated_state.list_entries() == []


@pytest.mark.unit
def test_unlock_subcommand(isolated_state, capsys):
    isolated_state.lockfile_path().touch()

    server.launcher(["--lanes", "unlock"])

    assert "registry_lock_removed=True" in capsys.readouterr().out
    assert not isolated_state.lockfile_path().exists()


@pytest.mark.unit
def test_dashboard_rejects_tiny_refresh(monkeypatch, capsys):
    from ansys.aedt.mcp.lanes import dashboard

    monkeypatch.setattr(dashboard, "run", lambda *a, **k: pytest.fail("must not serve"))

    with pytest.raises(SystemExit) as exc_info:
        server.launcher(["--lanes", "dashboard", "--refresh", "1"])
    assert exc_info.value.code == 2
    assert "--refresh must be >=" in capsys.readouterr().err


@pytest.mark.unit
def test_dashboard_options_reach_run(monkeypatch):
    from ansys.aedt.mcp.lanes import dashboard

    seen: list = []
    monkeypatch.setattr(dashboard, "run", lambda *a, **k: seen.append((a, k)) or 0)

    server.launcher(["--lanes", "dashboard", "--port", "0", "--refresh", "5", "--no-browser"])

    assert seen == [((0, 5), {"open_browser": False})]


# ---------------------------------------------------------------------------
# End to end over stdio
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_stdio_proxy_end_to_end(backend_cmd, isolated_state, tmp_path):
    """The stdio proxy boots with no lane, then spawns, routes to, and stops one."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    env = {**os.environ, "LOCALAPPDATA": str(tmp_path), "APPDATA": str(tmp_path)}
    env["XDG_STATE_HOME"] = str(tmp_path)
    env.pop(backend.TOKEN_ENV, None)
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "ansys.aedt.mcp", "--lanes", "--http-host", HOST],
        env=env,
    )

    async def _run():
        async with Client(transport) as client:
            tools = await client.list_tools()
            before = (await client.call_tool("current_lane", {})).data
            unrouted = await client.call_tool_mcp("check_aedt_installed", {})
            spawned = (await client.call_tool("spawn_lane", {"lane_id": "e2e"})).data
            routed = await client.call_tool_mcp("check_aedt_installed", {})
            stopped = (await client.call_tool("stop_lane", {"lane_id": "e2e"})).data
            after = (await client.call_tool("current_lane", {})).data
            return tools, before, unrouted, spawned, routed, stopped, after

    tools, before, unrouted, spawned, routed, stopped, after = asyncio.run(_run())

    names = {tool.name for tool in tools}
    assert set(proxy.LANES_TOOLSET_ENTRY["tools"]) <= names
    assert "check_aedt_installed" in names
    assert before["lane_id"] is None
    assert unrouted.is_error
    assert "No lane selected" in unrouted.content[0].text
    assert spawned["ok"], spawned
    assert spawned["switched_to"] == "e2e"
    assert not routed.is_error, routed.content
    assert stopped["ok"], stopped
    assert stopped["removed"] is True
    assert stopped["current_lane_id"] is None
    assert after["lane_id"] is None
    assert isolated_state.list_entries() == []
