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

"""Lanes dashboard: status collection from static sources and its HTTP surface."""

import http.client
import json
import os
import socket
import threading
import time

import pytest

from ansys.aedt.mcp.lanes import dashboard

from .conftest import HOST, get_free_port

pytestmark = pytest.mark.unit


@pytest.fixture
def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, 0))
    sock.listen(8)
    yield sock.getsockname()[1]
    sock.close()


def _ts(offset: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + offset)) + ",000"


def _write_log(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_summarize_log_detects_running_call_and_last_error(tmp_path):
    log = tmp_path / "lane-1.log"
    _write_log(
        log,
        [
            f"{_ts(-120)} [INFO] mcp.server.streamable_http_manager: "
            "Created new transport with session ID: a",
            f"{_ts(-120)} [INFO] mcp.server.lowlevel.server: "
            "Processing request of type CallToolRequest",
            f"{_ts(-119)} [ERROR] Global: ****************************************************",
            f"{_ts(-119)} [ERROR] Global: AEDT API Error on open_project",
            f'{_ts(-119)} [ERROR] Global:   File "x.py", line 1, in f',
            f"{_ts(-118)} [INFO] mcp.server.streamable_http: Terminating session: a",
            f"{_ts(-60)} [INFO] mcp.server.lowlevel.server: "
            "Processing request of type CallToolRequest",
        ],
    )
    info = dashboard.summarize_log(log)
    assert info["call_in_progress_since"] is not None
    assert 55 <= info["call_elapsed_seconds"] <= 70
    assert info["last_error"] == "AEDT API Error on open_project"
    assert info["error_lines_in_tail"] == 3

    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"{_ts(-1)} [INFO] mcp.server.streamable_http: Terminating session: b\n")
    info = dashboard.summarize_log(log)
    assert info["call_in_progress_since"] is None
    assert info["last_event"] == "Terminating session: b"


def test_summarize_log_reads_only_the_tail(tmp_path):
    log = tmp_path / "lane-2.log"
    filler = ["x" * 200] * ((dashboard.LOG_TAIL_BYTES // 200) + 50)
    _write_log(
        log,
        [
            f"{_ts(-10)} [ERROR] Global: old error outside the tail",
            *filler,
            f"{_ts(-5)} [INFO] mcp.server.streamable_http: Terminating session: z",
        ],
    )
    info = dashboard.summarize_log(log)
    assert info["last_error"] is None
    assert info["last_event"] == "Terminating session: z"


def test_summarize_log_missing_file(tmp_path):
    path = tmp_path / "nope.log"
    assert dashboard.summarize_log(path) == {"path": str(path), "exists": False}


def test_collect_status_classifies_lanes(isolated_state, listener):
    registry = isolated_state
    busy_log = registry.state_dir() / f"lane-{listener}.log"
    _write_log(
        busy_log,
        [
            f"{_ts(-90)} [INFO] mcp.server.lowlevel.server: "
            "Processing request of type CallToolRequest"
        ],
    )
    reg = registry.Registry(
        servers={
            "busy": registry.ServerEntry(
                server_id="busy",
                http_port=listener,
                pid=os.getpid(),
                log_path=str(busy_log),
                auth_token="t0ps3cret",
            ),
            "dead": registry.ServerEntry(server_id="dead", http_port=get_free_port(), pid=None),
            "no-aedt": registry.ServerEntry(
                server_id="no-aedt",
                http_port=listener,
                pid=os.getpid(),
                aedt_gpc_port=get_free_port(),
                log_path=str(registry.state_dir() / "other.log"),
            ),
        }
    )
    registry.save_registry(reg)

    status = dashboard.collect_status(refresh_seconds=12)
    assert status["refresh_seconds"] == 12
    lanes = {lane["lane_id"]: lane for lane in status["lanes"]}
    assert [lane["lane_id"] for lane in status["lanes"]] == ["busy", "dead", "no-aedt"]
    assert lanes["busy"]["status"] == "busy"
    assert lanes["busy"]["listening"]
    assert lanes["busy"]["pid_alive"]
    assert lanes["busy"]["auth"] == "token"
    assert lanes["dead"]["status"] == "down"
    assert lanes["dead"]["log"]["path"].endswith(f"lane-{lanes['dead']['http_port']}.log")
    assert lanes["no-aedt"]["status"] == "degraded"
    assert lanes["no-aedt"]["aedt_reachable"] is False
    assert "t0ps3cret" not in json.dumps(status)


def test_collect_status_without_registry(isolated_state):
    status = dashboard.collect_status()
    assert status["registry"]["exists"] is False
    assert status["lanes"] == []
    assert status["refresh_seconds"] == dashboard.DEFAULT_REFRESH_SECONDS


def test_collect_status_reports_corrupt_registry(isolated_state):
    path = isolated_state.registry_path()
    path.write_text("{not json", encoding="utf-8")

    status = dashboard.collect_status()

    assert "JSONDecodeError" in status["registry"]["error"]
    assert status["lanes"] == []
    # The dashboard is read-only: it never moves the corrupt file aside.
    assert path.exists()


def test_http_routes_and_host_guard(isolated_state):
    server = dashboard.make_server(0, 15)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:

        def get(path, host):
            conn = http.client.HTTPConnection(HOST, port, timeout=10)
            conn.request("GET", path, headers={"Host": host})
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            return resp.status, resp.getheader("Content-Type"), body

        status, ctype, body = get("/", f"127.0.0.1:{port}")
        assert status == 200
        assert ctype.startswith("text/html")
        assert b"/api/status" in body

        status, ctype, body = get("/api/status", f"localhost:{port}")
        assert status == 200
        assert ctype == "application/json"
        assert json.loads(body)["refresh_seconds"] == 15

        assert get("/api/status", "evil.example:80")[0] == 403
        assert get("/registry.json", f"127.0.0.1:{port}")[0] == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cli_rejects_tiny_refresh(capsys):
    from ansys.aedt.mcp.lanes import cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["dashboard", "--refresh", "1", "--no-browser"])
    assert exc_info.value.code == 2
    assert "--refresh" in capsys.readouterr().err
