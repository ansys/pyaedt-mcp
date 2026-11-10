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

"""Tests for the detached HTML window fallback."""

import html as html_lib
import os
from pathlib import Path
import re
import time
from unittest.mock import patch

import pytest

from ansys.aedt.mcp import html_window


@pytest.fixture
def view_dir(tmp_path):
    with patch.object(html_window.tempfile, "gettempdir", return_value=str(tmp_path)):
        yield tmp_path / html_window.VIEW_DIR_NAME


@pytest.fixture
def desktop():
    with patch.object(html_window, "display_unavailable_reason", return_value=None):
        yield


def _srcdoc(document: str) -> str:
    return html_lib.unescape(re.search(r'srcdoc="([^"]*)"', document).group(1))


@pytest.mark.unit
class TestBuildWindowDocument:
    def test_html_is_sandboxed_and_escaped(self):
        payload = '<p>"x" & y</p><script>alert(1)</script></iframe>'
        document = html_window.build_window_document(payload, 'A <b>"T"</b>')

        assert 'sandbox="allow-scripts"' in document
        assert "allow-same-origin" not in document
        assert "<title>A &lt;b&gt;&quot;T&quot;&lt;/b&gt;</title>" in document
        assert "<script>alert(1)" not in document
        inner = _srcdoc(document)
        assert inner.endswith(payload)
        assert html_window.CONTENT_POLICY in inner

    def test_fixed_size_is_embedded(self):
        document = html_window.build_window_document("<p>x</p>", "T", 640, 300)
        assert "const fixedWidth = 640, fixedHeight = 300;" in document
        assert "const fixedWidth = 640;" in _srcdoc(document)

    def test_policies_block_network(self):
        document = html_window.build_window_document("<p>x</p>", "T")
        assert "connect-src 'none'" in document
        assert "default-src 'none'" in document
        assert "http" not in html_window.CONTENT_POLICY


@pytest.mark.unit
class TestFindAppBrowser:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(html_window.BROWSER_ENV_VAR, "mybrowser")
        with patch.object(html_window.shutil, "which", return_value="/bin/mybrowser"):
            assert html_window.find_app_browser() == "/bin/mybrowser"

    def test_invalid_override_falls_back(self, monkeypatch):
        monkeypatch.setenv(html_window.BROWSER_ENV_VAR, "missing")
        monkeypatch.setattr(html_window.sys, "platform", "linux")
        found = {"google-chrome": "/usr/bin/google-chrome"}
        with patch.object(html_window.shutil, "which", side_effect=found.get):
            assert html_window.find_app_browser() == "/usr/bin/google-chrome"

    def test_windows_program_files(self, monkeypatch, tmp_path):
        exe = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.delenv(html_window.BROWSER_ENV_VAR, raising=False)
        monkeypatch.setattr(html_window.sys, "platform", "win32")
        for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            monkeypatch.setenv(name, str(tmp_path))
        assert html_window.find_app_browser() == str(exe)

    def test_none_found(self, monkeypatch):
        monkeypatch.delenv(html_window.BROWSER_ENV_VAR, raising=False)
        monkeypatch.setattr(html_window.sys, "platform", "linux")
        with patch.object(html_window.shutil, "which", return_value=None):
            assert html_window.find_app_browser() is None


@pytest.mark.unit
class TestDisplayUnavailableReason:
    def test_linux_without_display(self, monkeypatch):
        monkeypatch.setattr(html_window.sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        with patch.object(html_window.Path, "exists", return_value=False):
            assert "No graphical display" in html_window.display_unavailable_reason()

    def test_container(self):
        with patch.object(html_window.Path, "exists", return_value=True):
            assert "container" in html_window.display_unavailable_reason()

    def test_windows_desktop(self, monkeypatch):
        monkeypatch.setattr(html_window.sys, "platform", "win32")
        with patch.object(html_window.Path, "exists", return_value=False):
            assert html_window.display_unavailable_reason() is None


@pytest.mark.unit
class TestOpenHtmlWindow:
    def test_app_window(self, view_dir, desktop):
        with (
            patch.object(html_window, "find_app_browser", return_value="msedge"),
            patch.object(html_window.subprocess, "Popen") as popen,
        ):
            result = html_window.open_html_window("<p>Hi</p>", "Title", 640, 500)

        assert result.opened and result.method == "app_window"
        assert result.browser == "msedge"
        path = Path(result.path)
        assert path.parent == view_dir
        assert "&lt;p&gt;Hi&lt;/p&gt;" in path.read_text(encoding="utf-8")
        command = popen.call_args.args[0]
        assert command[0] == "msedge"
        assert command[1] == f"--app={path.as_uri()}"
        assert "--window-size=640,540" in command
        assert popen.call_args.kwargs["stdin"] is html_window.subprocess.DEVNULL

    def test_app_window_default_size_is_fitted(self, view_dir, desktop):
        with (
            patch.object(html_window, "find_app_browser", return_value="msedge"),
            patch.object(html_window.subprocess, "Popen") as popen,
        ):
            result = html_window.open_html_window("<p>Hi</p>", "Title")

        assert "--window-size=800,640" in popen.call_args.args[0]
        document = Path(result.path).read_text(encoding="utf-8")
        assert "resizeTo(" in document
        assert "const fixedWidth = null, fixedHeight = null;" in document

    def test_default_browser_fallback(self, view_dir, desktop):
        with (
            patch.object(html_window, "find_app_browser", return_value="msedge"),
            patch.object(html_window.subprocess, "Popen", side_effect=OSError("boom")),
            patch.object(html_window.webbrowser, "open", return_value=True) as wb_open,
        ):
            result = html_window.open_html_window("<p>Hi</p>", "Title")

        assert result.opened and result.method == "default_browser"
        wb_open.assert_called_once_with(Path(result.path).as_uri(), new=1)

    def test_no_browser(self, view_dir, desktop):
        with (
            patch.object(html_window, "find_app_browser", return_value=None),
            patch.object(html_window.webbrowser, "open", return_value=False),
        ):
            result = html_window.open_html_window("<p>Hi</p>", "Title")

        assert not result.opened and result.method == "none"
        assert Path(result.path).is_file()
        assert "manually" in result.error

    def test_no_display(self, view_dir):
        with (
            patch.object(html_window, "display_unavailable_reason", return_value="headless"),
            patch.object(html_window.subprocess, "Popen") as popen,
        ):
            result = html_window.open_html_window("<p>Hi</p>", "Title")

        assert result.to_dict() == {
            "opened": False,
            "method": "none",
            "path": None,
            "browser": None,
            "error": "headless",
        }
        popen.assert_not_called()
        assert not view_dir.exists()

    def test_stale_views_removed(self, view_dir, desktop):
        view_dir.mkdir(parents=True)
        stale = view_dir / "view-old.html"
        fresh = view_dir / "view-new.html"
        other = view_dir / "keep.txt"
        for item in (stale, fresh, other):
            item.write_text("x")
        old = time.time() - 2 * 24 * 60 * 60
        os.utime(stale, (old, old))
        os.utime(other, (old, old))

        with (
            patch.object(html_window, "find_app_browser", return_value="msedge"),
            patch.object(html_window.subprocess, "Popen"),
        ):
            html_window.open_html_window("<p>Hi</p>", "Title")

        assert not stale.exists()
        assert fresh.exists() and other.exists()
