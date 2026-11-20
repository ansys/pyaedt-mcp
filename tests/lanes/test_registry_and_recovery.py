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

"""Unit tests for the lane registry, its lock, and the CLI recovery paths.

The autouse ``isolated_state`` fixture pins the state directory to a temp
folder, so nothing on the real user's machine is touched.
"""

import json
import os
from pathlib import Path
import subprocess  # nosec B404
import sys
import threading

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Load / save / corruption
# ---------------------------------------------------------------------------


def test_state_dir_follows_environment(isolated_state, tmp_path):
    assert isolated_state.state_dir() == tmp_path / isolated_state.STATE_DIR_NAME
    assert isolated_state.registry_path().parent == isolated_state.state_dir()
    assert isolated_state.lockfile_path().parent == isolated_state.state_dir()


def test_load_empty_registry(isolated_state):
    reg = isolated_state.load_registry()
    assert reg.schema_version == isolated_state.SCHEMA_VERSION
    assert reg.servers == {}


def test_roundtrip_upsert_and_remove(isolated_state):
    isolated_state.upsert_entry(
        isolated_state.ServerEntry(server_id="alpha", http_port=8100, pid=12345)
    )

    fetched = isolated_state.get_entry("alpha")
    assert fetched is not None
    assert fetched.http_port == 8100
    assert fetched.pid == 12345
    assert [entry.server_id for entry in isolated_state.list_entries()] == ["alpha"]

    assert isolated_state.remove_entry("alpha") is True
    assert isolated_state.get_entry("alpha") is None
    assert isolated_state.remove_entry("alpha") is False


def test_corrupt_registry_is_backed_up_and_reset(isolated_state):
    path = isolated_state.registry_path()
    path.write_text("this is not JSON {{{", encoding="utf-8")

    assert isolated_state.load_registry().servers == {}
    assert list(path.parent.glob("registry.bad-*.json")), "Corrupt registry was not preserved."


def test_non_object_registry_is_backed_up_and_reset(isolated_state):
    path = isolated_state.registry_path()
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert isolated_state.load_registry().servers == {}
    assert list(path.parent.glob("registry.bad-*.json"))


def test_load_ignores_unknown_schema_version(isolated_state):
    isolated_state.registry_path().write_text(
        json.dumps({"schema_version": 99999, "servers": {"x": {"server_id": "x", "http_port": 1}}}),
        encoding="utf-8",
    )
    assert isolated_state.load_registry().servers == {}


def test_load_skips_malformed_entries_and_unknown_fields(isolated_state):
    isolated_state.registry_path().write_text(
        json.dumps(
            {
                "schema_version": isolated_state.SCHEMA_VERSION,
                "servers": {
                    "good": {"server_id": "good", "http_port": 8100, "lease_owner": "old"},
                    "bad": {"http_port": 8101},
                },
            }
        ),
        encoding="utf-8",
    )
    assert list(isolated_state.load_registry().servers) == ["good"]


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def test_registry_lock_can_be_reacquired(isolated_state):
    with isolated_state.registry_lock():
        pass
    with isolated_state.registry_lock():
        pass


def test_registry_lock_timeout_raises(isolated_state):
    holder_ready = threading.Event()
    can_release = threading.Event()
    holder_exc: list[BaseException] = []

    def _hold_lock():
        try:
            with isolated_state.registry_lock(timeout=5.0):
                holder_ready.set()
                can_release.wait(timeout=10.0)
        except BaseException as exc:  # pragma: no cover - defensive
            holder_exc.append(exc)

    thread = threading.Thread(target=_hold_lock, daemon=True)
    thread.start()
    assert holder_ready.wait(timeout=5.0), "Holder thread never grabbed the lock"

    try:
        with pytest.raises(isolated_state.RegistryLockTimeoutError, match="--lanes unlock"):
            with isolated_state.registry_lock(timeout=0.5):
                pytest.fail("Second acquire should have timed out")
    finally:
        can_release.set()
        thread.join(timeout=5.0)

    assert not holder_exc, f"Holder thread errored: {holder_exc}"


def test_registry_lock_default_timeout_is_read_at_call_time(isolated_state, monkeypatch):
    holder_ready = threading.Event()
    can_release = threading.Event()

    def _hold_lock():
        with isolated_state.registry_lock(timeout=5.0):
            holder_ready.set()
            can_release.wait(timeout=10.0)

    thread = threading.Thread(target=_hold_lock, daemon=True)
    thread.start()
    assert holder_ready.wait(timeout=5.0)
    monkeypatch.setattr(isolated_state, "DEFAULT_LOCK_TIMEOUT", 0.2)
    try:
        with pytest.raises(isolated_state.RegistryLockTimeoutError, match="0.2s"):
            with isolated_state.registry_lock():
                pass
    finally:
        can_release.set()
        thread.join(timeout=5.0)


def test_force_unlock_removes_lockfile(isolated_state):
    with isolated_state.registry_lock():
        pass
    lock_path = isolated_state.lockfile_path()
    lock_path.touch()

    assert isolated_state.force_unlock() is True
    assert not lock_path.exists()
    assert isolated_state.force_unlock() is False


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def test_pid_alive_and_kill_pid(isolated_state):
    assert isolated_state.pid_alive(os.getpid()) is True
    assert isolated_state.pid_alive(0) is False
    assert isolated_state.pid_alive(-1) is False

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # nosec B603
    try:
        assert isolated_state.pid_alive(proc.pid)
        assert isolated_state.kill_pid(proc.pid, timeout=10.0) is True
        proc.wait(timeout=10.0)
        assert not isolated_state.pid_alive(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10.0)


def test_is_port_open(isolated_state, free_port):
    import socket

    assert isolated_state.is_port_open("127.0.0.1", free_port) is False
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        assert isolated_state.is_port_open("127.0.0.1", sock.getsockname()[1]) is True


# ---------------------------------------------------------------------------
# Reap
# ---------------------------------------------------------------------------


def test_reap_drops_entries_with_dead_pid_or_closed_port(isolated_state, monkeypatch):
    for sid, port, pid in (("live", 8181, 1), ("dead", 8182, 2), ("closed", 8183, 1)):
        isolated_state.upsert_entry(
            isolated_state.ServerEntry(server_id=sid, http_port=port, pid=pid)
        )
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="no-pid", http_port=8181))

    monkeypatch.setattr(isolated_state, "pid_alive", lambda pid: pid == 1)
    monkeypatch.setattr(
        isolated_state, "is_port_open", lambda host, port, timeout=0.3: port == 8181
    )

    report = isolated_state.reap_registry()

    assert sorted(report.dropped) == ["closed", "dead", "no-pid"]
    assert report.kept == ["live"]
    assert [entry.server_id for entry in isolated_state.list_entries()] == ["live"]


def test_reap_keeps_everything_when_all_live(isolated_state, monkeypatch):
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="a", http_port=9000, pid=42))
    monkeypatch.setattr(isolated_state, "pid_alive", lambda pid: True)
    monkeypatch.setattr(isolated_state, "is_port_open", lambda host, port, timeout=0.3: True)

    report = isolated_state.reap_registry()
    assert report.dropped == []
    assert report.kept == ["a"]


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_reset_wipes_registry_and_optionally_kills_pids(isolated_state, monkeypatch):
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="a", http_port=9000, pid=42))
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="b", http_port=9001, pid=None))
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="c", http_port=9002, pid=43))

    killed: list[int] = []

    def fake_kill(pid: int, timeout: float = 10.0, tree: bool = True) -> bool:
        killed.append(pid)
        return pid == 42

    monkeypatch.setattr(isolated_state, "kill_pid", fake_kill)

    report = isolated_state.reset_registry(kill_orphans=True)

    assert set(report.dropped) == {"a", "b", "c"}
    assert sorted(killed) == [42, 43]
    assert report.killed == [42]
    assert report.failed_to_kill == [43]
    assert isolated_state.list_entries() == []


def test_reset_without_kill_does_not_touch_processes(isolated_state, monkeypatch):
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="a", http_port=9000, pid=42))
    monkeypatch.setattr(
        isolated_state, "kill_pid", lambda *_args, **_kw: pytest.fail("must not kill")
    )

    report = isolated_state.reset_registry(kill_orphans=False)
    assert report.killed == []
    assert report.dropped == ["a"]


def test_reset_unlock_removes_lockfile(isolated_state):
    isolated_state.lockfile_path().touch()

    report = isolated_state.reset_registry(unlock=True)

    assert report.unlocked is True


# ---------------------------------------------------------------------------
# Field-level updates
# ---------------------------------------------------------------------------


def test_update_aedt_port_preserves_concurrent_changes(isolated_state):
    isolated_state.upsert_entry(isolated_state.ServerEntry(server_id="a", http_port=9000, pid=42))
    stale = isolated_state.get_entry("a")

    # Another process changes the entry after the snapshot was taken.
    fresh = isolated_state.get_entry("a")
    fresh.pid = 4242
    isolated_state.upsert_entry(fresh)

    assert isolated_state.update_aedt_port(stale.server_id, 50051) is True

    result = isolated_state.get_entry("a")
    assert result.aedt_gpc_port == 50051
    assert result.pid == 4242

    assert isolated_state.update_aedt_port("a", None) is True
    assert isolated_state.get_entry("a").aedt_gpc_port is None


def test_update_aedt_port_missing_entry_returns_false(isolated_state):
    assert isolated_state.update_aedt_port("ghost", 50051) is False
    assert isolated_state.get_entry("ghost") is None


# ---------------------------------------------------------------------------
# HTTP port allocation
# ---------------------------------------------------------------------------


def test_default_port_range_avoids_regular_http_port(isolated_state):
    low, high = isolated_state.DEFAULT_HTTP_PORT_RANGE
    assert not low <= 8080 <= high


def test_allocate_http_port_skips_reserved_and_bound(isolated_state, monkeypatch):
    reg = isolated_state.Registry()
    reg.servers["one"] = isolated_state.ServerEntry(server_id="one", http_port=8080)

    monkeypatch.setattr(
        isolated_state, "is_port_open", lambda host, port, timeout=0.3: port == 8081
    )
    assert isolated_state.allocate_http_port(reg, port_range=(8080, 8090)) == 8082


def test_allocate_http_port_exhaustion_raises(isolated_state, monkeypatch):
    reg = isolated_state.Registry()
    monkeypatch.setattr(isolated_state, "is_port_open", lambda host, port, timeout=0.3: True)
    with pytest.raises(RuntimeError, match="No free HTTP port"):
        isolated_state.allocate_http_port(reg, port_range=(9500, 9502))


# ---------------------------------------------------------------------------
# Token handling
# ---------------------------------------------------------------------------


def test_entry_without_token(isolated_state):
    entry = isolated_state.ServerEntry.from_dict({"server_id": "old", "http_port": 8080})
    assert entry.auth_token is None
    assert entry.auth_mode == "none"
    public = entry.public_dict()
    assert public["auth"] == "none"
    assert "auth_token" not in public


def test_token_is_hidden_from_public_views(isolated_state):
    entry = isolated_state.ServerEntry("x", 1, auth_token="t0ps3cret")
    assert entry.auth_mode == "token"
    assert "t0ps3cret" not in repr(entry)
    assert "t0ps3cret" not in json.dumps(entry.public_dict())
    assert entry.to_dict()["auth_token"] == "t0ps3cret"


# ---------------------------------------------------------------------------
# CLI recovery end-to-end, in a subprocess
# ---------------------------------------------------------------------------


def _run_cli(tmp_path: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path), "APPDATA": str(tmp_path)}
    env["XDG_STATE_HOME"] = str(tmp_path)
    return subprocess.run(  # nosec B603
        [sys.executable, "-m", "ansys.aedt.mcp", "--lanes", *args],
        capture_output=True,
        text=True,
        input=stdin,
        env=env,
        timeout=60.0,
    )


def _seed_registry(tmp_path: Path) -> Path:
    state = tmp_path / "ansys-aedt-mcp"
    state.mkdir(parents=True, exist_ok=True)
    registry_file = state / "registry.json"
    registry_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "servers": {
                    "seeded": {
                        "server_id": "seeded",
                        "http_port": 8123,
                        "pid": None,
                        "aedt_gpc_port": None,
                        "log_path": None,
                        "started_at": 0.0,
                        "auth_token": "t0ps3cret",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return registry_file


@pytest.mark.slow
def test_cli_status_reports_empty_registry(tmp_path):
    result = _run_cli(tmp_path, "status", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["servers"] == []
    assert Path(payload["registry_path"]).parent == tmp_path / "ansys-aedt-mcp"


@pytest.mark.slow
def test_cli_status_redacts_seeded_token(tmp_path):
    _seed_registry(tmp_path)
    result = _run_cli(tmp_path, "status", "--json")
    assert result.returncode == 0, result.stderr
    assert "t0ps3cret" not in result.stdout
    (row,) = json.loads(result.stdout)["servers"]
    assert row["auth"] == "token"
    assert row["listening"] is False


@pytest.mark.slow
def test_cli_reset_wipes_seeded_registry(tmp_path):
    registry_file = _seed_registry(tmp_path)

    result = _run_cli(tmp_path, "reset", "--yes")
    assert result.returncode == 0, result.stderr
    assert json.loads(registry_file.read_text(encoding="utf-8"))["servers"] == {}


@pytest.mark.slow
def test_cli_reset_aborts_without_confirmation(tmp_path):
    registry_file = _seed_registry(tmp_path)

    result = _run_cli(tmp_path, "reset", stdin="n\n")
    assert result.returncode == 1
    assert "Aborted" in result.stdout
    assert "seeded" in json.loads(registry_file.read_text(encoding="utf-8"))["servers"]


@pytest.mark.slow
def test_cli_reap_reports_zero_when_empty(tmp_path):
    result = _run_cli(tmp_path, "reap")
    assert result.returncode == 0, result.stderr
    assert "Dropped 0" in result.stdout


@pytest.mark.slow
def test_cli_unlock_removes_stale_lockfile(tmp_path):
    state = tmp_path / "ansys-aedt-mcp"
    state.mkdir(parents=True, exist_ok=True)
    (state / "registry.lock").touch()

    result = _run_cli(tmp_path, "unlock")
    assert result.returncode == 0, result.stderr
    assert "registry_lock_removed=True" in result.stdout
    assert not (state / "registry.lock").exists()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_writers_do_not_lose_entries(isolated_state):
    errors: list[BaseException] = []

    def _writer(sid: str, port: int) -> None:
        try:
            isolated_state.upsert_entry(isolated_state.ServerEntry(server_id=sid, http_port=port))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [
        threading.Thread(target=_writer, args=(f"srv-{i}", 9100 + i), daemon=True) for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert not errors, f"Writers errored: {errors}"
    reg = isolated_state.load_registry()
    assert len(reg.servers) == 8
    assert {entry.http_port for entry in reg.servers.values()} == set(range(9100, 9108))
