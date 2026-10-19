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

"""Detached HTML window for clients without MCP Apps support.

The HTML is written to a temporary wrapper file and opened in a chromeless
application window of an installed Chromium-based browser (Microsoft Edge,
Google Chrome, or Chromium). If none is found, the default browser is used.
Only the Python standard library is required.

The supplied HTML runs inside an ``iframe`` sandbox with an opaque origin and
a Content Security Policy that blocks network access, external resources,
forms, popups, and access to local files.
"""

from dataclasses import asdict, dataclass
import html as html_lib
import os
from pathlib import Path
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
import webbrowser

from ansys.common.mcp import get_logger

logger = get_logger(__name__)

BROWSER_ENV_VAR = "PYAEDT_MCP_HTML_BROWSER"
"""Environment variable with the path of a Chromium-based browser to use."""

VIEW_DIR_NAME = "pyaedt-mcp-html-views"
_MAX_VIEW_AGE_SECONDS = 24 * 60 * 60
_WINDOW_WIDTH = 1024
_WINDOW_CHROME_HEIGHT = 40

CONTENT_POLICY = (
    "default-src 'none'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
    "connect-src 'none'; frame-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'"
)

_WRAPPER_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{wrapper_policy}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{title}</title>
<style>
html, body {{ margin: 0; height: 100%; }}
iframe {{ display: block; width: 100%; height: 100%; border: 0; }}
</style>
</head>
<body>
<iframe title="{title}" sandbox="allow-scripts" srcdoc="{srcdoc}"></iframe>
</body>
</html>
"""

_WINDOWS_BROWSERS = (
    ("Microsoft", "Edge", "Application", "msedge.exe"),
    ("Google", "Chrome", "Application", "chrome.exe"),
    ("Chromium", "Application", "chrome.exe"),
)
_MAC_BROWSERS = (
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
_POSIX_BROWSERS = (
    "microsoft-edge",
    "microsoft-edge-stable",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)


@dataclass
class WindowResult:
    """Outcome of an attempt to open a detached HTML window.

    Attributes
    ----------
    opened : bool
        Whether a window or browser was launched.
    method : str
        ``"app_window"``, ``"default_browser"``, or ``"none"``.
    path : str | None
        Wrapper file that was opened, if one was written.
    browser : str | None
        Browser executable used for ``"app_window"``.
    error : str | None
        Reason the window could not be opened.
    """

    opened: bool
    method: str
    path: str | None = None
    browser: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """Return the result as a JSON-serializable dictionary."""
        return asdict(self)


def build_window_document(html: str, title: str) -> str:
    """Build the wrapper page that sandboxes the supplied HTML.

    Parameters
    ----------
    html : str
        HTML document or fragment to display.
    title : str
        Window title.

    Returns
    -------
    str
        Complete HTML wrapper document.
    """
    policy = f'<meta http-equiv="Content-Security-Policy" content="{CONTENT_POLICY}">'
    inner = "<!doctype html>" + policy + html
    return _WRAPPER_TEMPLATE.format(
        wrapper_policy=CONTENT_POLICY.replace("frame-src 'none'", "frame-src 'self'"),
        title=html_lib.escape(title, quote=True),
        srcdoc=html_lib.escape(inner, quote=True),
    )


def find_app_browser() -> str | None:
    """Find a Chromium-based browser that supports ``--app`` windows.

    The ``PYAEDT_MCP_HTML_BROWSER`` environment variable takes precedence.

    Returns
    -------
    str | None
        Path of the browser executable, or ``None`` if none was found.
    """
    override = os.environ.get(BROWSER_ENV_VAR, "").strip()
    if override:
        resolved = shutil.which(override)
        if resolved:
            return resolved
        logger.warning(f"{BROWSER_ENV_VAR}={override!r} is not an executable; ignoring it.")

    if sys.platform == "win32":
        roots = [
            os.environ.get(name) for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
        ]
        for parts in _WINDOWS_BROWSERS:
            for root in filter(None, roots):
                candidate = Path(root, *parts)
                if candidate.is_file():
                    return str(candidate)
    elif sys.platform == "darwin":
        for candidate in _MAC_BROWSERS:
            if Path(candidate).is_file():
                return candidate

    for name in _POSIX_BROWSERS:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def display_unavailable_reason() -> str | None:
    """Return why a local window cannot be shown, or ``None`` if it can.

    Returns
    -------
    str | None
        Reason a window cannot be displayed on this machine.
    """
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return "The MCP server is running in a container without a desktop."
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return "No graphical display is available (DISPLAY and WAYLAND_DISPLAY are unset)."
    return None


def _view_dir() -> Path:
    view_dir = Path(tempfile.gettempdir()) / VIEW_DIR_NAME
    view_dir.mkdir(parents=True, exist_ok=True)
    return view_dir


def _remove_stale_views(view_dir: Path) -> None:
    cutoff = time.time() - _MAX_VIEW_AGE_SECONDS
    for item in view_dir.glob("view-*.html"):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            pass


def _write_view(html: str, title: str) -> Path:
    view_dir = _view_dir()
    _remove_stale_views(view_dir)
    handle, name = tempfile.mkstemp(prefix="view-", suffix=".html", dir=view_dir)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(build_window_document(html, title))
    return Path(name)


def _launch_app_window(browser: str, url: str, height: int) -> None:
    command = [
        browser,
        f"--app={url}",
        f"--window-size={_WINDOW_WIDTH},{height + _WINDOW_CHROME_HEIGHT}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)  # nosec B603


def open_html_window(html: str, title: str, height: int = 480) -> WindowResult:
    """Open HTML in a detached window on the machine running the MCP server.

    Parameters
    ----------
    html : str
        HTML document or fragment to display.
    title : str
        Window title.
    height : int, optional
        Requested content height in pixels.

    Returns
    -------
    WindowResult
        How the HTML was opened, or why it could not be.
    """
    reason = display_unavailable_reason()
    if reason:
        return WindowResult(opened=False, method="none", error=reason)

    try:
        path = _write_view(html, title)
    except OSError as e:
        return WindowResult(opened=False, method="none", error=f"Could not write view: {e}")
    url = path.as_uri()

    browser = find_app_browser()
    if browser:
        try:
            _launch_app_window(browser, url, height)
            return WindowResult(opened=True, method="app_window", path=str(path), browser=browser)
        except OSError as e:
            logger.warning(f"Could not launch {browser} in app mode: {e}")

    try:
        if webbrowser.open(url, new=1):
            return WindowResult(opened=True, method="default_browser", path=str(path))
    except webbrowser.Error as e:
        logger.warning(f"Could not open the default browser: {e}")
    return WindowResult(
        opened=False,
        method="none",
        path=str(path),
        error="No browser could be launched. Open the file manually.",
    )
