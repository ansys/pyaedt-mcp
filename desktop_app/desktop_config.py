"""Centralized configuration constants for the PyAEDT MCP desktop application."""

from pathlib import Path
import re
import sys

import yaml

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def config_path() -> Path:
    """Return the location of the bundled desktop configuration file."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "config.yaml"
    return Path(__file__).resolve().parent / "config.yaml"


def _load_config() -> dict:
    path = config_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a YAML mapping")
    return data


def _load_sha256(config: dict, key: str) -> str:
    """Coerce a configured checksum to str and validate it is 64 hex characters."""
    value = str(config["runtime"][key])
    if not _SHA256_HEX_RE.fullmatch(value.lower()):
        raise RuntimeError(
            f"runtime.{key} must be a 64-character hex SHA-256 digest, got {value!r}"
        )
    return value


_CONFIG = _load_config()

PACKAGE_NAME = _CONFIG["package"]["name"]
REPOSITORY_URL = _CONFIG["package"]["repository_url"]
PYPI_PACKAGE_URL = _CONFIG["package"]["pypi_url"]
GITHUB_BRANCHES_URL = _CONFIG["package"]["github_branches_url"]
ISSUES_URL = _CONFIG["package"]["issues_url"]
DESKTOP_APP_DOCUMENTATION_URL = _CONFIG["package"]["documentation_url"]

APP_DIRECTORY_NAME = _CONFIG["app"]["directory_name"]
SERVER_MODE_FLAG = _CONFIG["app"]["server_mode_flag"]
SETTINGS_FILENAME = _CONFIG["app"]["settings_filename"]
WINDOW_ICON_FILENAME = _CONFIG["app"]["window_icon_filename"]
TRAY_ICON_FILENAME = _CONFIG["app"]["tray_icon_filename"]

WHEELHOUSE_PYTHON_VERSION = str(_CONFIG["runtime"]["wheelhouse_python_version"])
CPYTHON_VERSION = str(_CONFIG["runtime"]["cpython_version"])
PYTHON_ARCHIVE_SHA256 = _load_sha256(_CONFIG, "cpython_archive_sha256")
ARCHIVE_URL = (
    f"https://www.python.org/ftp/python/{CPYTHON_VERSION}/python-{CPYTHON_VERSION}-embed-amd64.zip"
)

UV_VERSION = str(_CONFIG["runtime"]["uv_version"])
UV_ARCHIVE_SHA256 = _load_sha256(_CONFIG, "uv_archive_sha256")
UV_ARCHIVE_URL = (
    f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
)

SERVER_NAME = _CONFIG["mcp"]["server_name"]
STDIO_TRANSPORT = _CONFIG["mcp"]["stdio_transport"]
HTTP_TRANSPORT = _CONFIG["mcp"]["http_transport"]

TRUSTED_VSCODE_PUBLISHERS = list(_CONFIG["trusted_publishers"]["vscode"])
TRUSTED_CLAUDE_DESKTOP_PUBLISHERS = list(_CONFIG["trusted_publishers"]["claude_desktop"])
TRUSTED_CURSOR_PUBLISHERS = list(_CONFIG["trusted_publishers"]["cursor"])
