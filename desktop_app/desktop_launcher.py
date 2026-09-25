"""Bootstrap the per-user PyAEDT MCP environment for the Windows executable."""

import os
from pathlib import Path
import re
import subprocess  # nosec B404
import sys
from typing import Any
import zipfile

from desktop_settings import load_settings

PACKAGE_NAME = "ansys-aedt-mcp"
APP_DIRECTORY_NAME = ".pyaedt_mcp"
SERVER_MODE_FLAG = "--server"
REPOSITORY_URL = "https://github.com/ansys/pyaedt-mcp.git"
WHEELHOUSE_PYTHON_VERSION = "3.13"


def hidden_window_options() -> dict[str, Any]:
    """Return subprocess options that prevent Windows console windows from appearing."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW")}
    return {}


def application_directory() -> Path:
    """Return the user-owned directory that holds the MCP virtual environment."""
    appdata_dir = os.environ.get("APPDATA", "").strip()
    appdata_root = Path(appdata_dir) if appdata_dir else Path.home() / "AppData" / "Roaming"
    return appdata_root / APP_DIRECTORY_NAME


def runtime_directory() -> Path:
    """Return the directory containing the embedded Python and uv executables."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "runtime"
    return Path(__file__).resolve().parent / ".desktop-runtime"


def command_paths(app_directory: Path) -> tuple[Path, Path]:
    """Return the venv Python and MCP command paths."""
    scripts_directory = app_directory / ".venv" / "Scripts"
    return scripts_directory / "python.exe", scripts_directory / "ansys-aedt-mcp.exe"


def installed_version(app_directory: Path) -> str | None:
    """Return the MCP version installed in the user virtual environment, if any."""
    site_packages = app_directory / ".venv" / "Lib" / "site-packages"
    for metadata_path in site_packages.glob("ansys_aedt_mcp-*.dist-info/METADATA"):
        version_match = re.search(
            r"^Version: (.+)$", metadata_path.read_text(encoding="utf-8"), re.MULTILINE
        )
        if version_match:
            return version_match.group(1)
    return None


def validate_wheelhouse(wheelhouse: Path) -> None:
    """Ensure a selected wheelhouse ZIP matches the embedded Python version."""
    version_match = re.search(r"-(\d+\.\d+)\.zip$", wheelhouse.name, re.IGNORECASE)
    if wheelhouse.suffix.lower() != ".zip" or version_match is None:
        raise RuntimeError("Select a wheelhouse ZIP named with its Python version")
    if version_match.group(1) != WHEELHOUSE_PYTHON_VERSION:
        raise RuntimeError(
            f"Select a Python {WHEELHOUSE_PYTHON_VERSION} wheelhouse, not Python "
            f"{version_match.group(1)}"
        )


def _wheelhouse_directory(app_directory: Path, wheelhouse: str) -> Path:
    """Extract a selected wheelhouse ZIP into the managed application directory."""
    source = Path(wheelhouse).expanduser()
    if not source.is_file():
        raise RuntimeError(f"Wheelhouse was not found: {source}")
    validate_wheelhouse(source)
    extracted = app_directory / "wheelhouse" / source.stem
    if not extracted.is_dir():
        extracted.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source) as archive:
            archive.extractall(extracted)
    return extracted


def setup_environment(
    app_directory: Path,
    runtime_dir: Path,
    version: str | None = None,
    branch: str | None = None,
    upgrade: bool = False,
    wheelhouse: str | None = None,
) -> Path:
    """Create the venv and install or update the requested MCP package version."""
    if version is not None and branch is not None:
        raise ValueError("Specify either a package version or a Git branch, not both")
    if wheelhouse and branch:
        raise ValueError("Offline installation supports published releases, not Git branches")
    python_executable, mcp_executable = command_paths(app_directory)
    if mcp_executable.is_file() and version is None and branch is None and not upgrade:
        return mcp_executable

    embedded_python = runtime_dir / "python" / "python.exe"
    uv_executable = runtime_dir / "uv" / "uv.exe"
    if not embedded_python.is_file() or not uv_executable.is_file():
        raise RuntimeError("The executable is missing its embedded Python or uv runtime")

    environment = os.environ.copy()
    environment["UV_NO_MANAGED_PYTHON"] = "1"
    if not python_executable.is_file():
        app_directory.mkdir(parents=True, exist_ok=True)
        subprocess.run(  # nosec B603
            [
                str(uv_executable),
                "venv",
                "--python",
                str(embedded_python),
                str(app_directory / ".venv"),
            ],
            check=True,
            env=environment,
            **hidden_window_options(),
        )
    package = f"{PACKAGE_NAME}=={version}" if version else PACKAGE_NAME
    if branch:
        package = f"{PACKAGE_NAME} @ git+{REPOSITORY_URL}@{branch}"
    install_command = [
        str(uv_executable),
        "pip",
        "install",
        "--python",
        str(python_executable),
        "--index-strategy",
        "unsafe-best-match",
    ]
    if wheelhouse:
        install_command.extend(
            ["--no-index", "--find-links", str(_wheelhouse_directory(app_directory, wheelhouse))]
        )
    if upgrade:
        install_command.append("--upgrade")
    install_command.append(package)
    subprocess.run(  # nosec B603
        install_command,
        check=True,
        env=environment,
        **hidden_window_options(),
    )
    if not mcp_executable.is_file():
        raise RuntimeError(f"{PACKAGE_NAME} was installed but its console command was not found")
    return mcp_executable


def main(argv: list[str] | None = None) -> int:
    """Launch the UI or run the MCP server when requested by a client profile."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] != SERVER_MODE_FLAG:
        from desktop_ui import launch_gui

        return launch_gui()

    try:
        app_directory = application_directory()
        settings = load_settings(app_directory)
        if settings["offline_install"] and not command_paths(app_directory)[1].is_file():
            raise RuntimeError("Open the desktop manager and select a wheelhouse before starting")
        mcp_executable = setup_environment(app_directory, runtime_directory())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"PyAEDT MCP setup failed: {error}", file=sys.stderr)
        return 1

    return subprocess.call([str(mcp_executable), *arguments[1:]])  # nosec B603


if __name__ == "__main__":
    raise SystemExit(main())
