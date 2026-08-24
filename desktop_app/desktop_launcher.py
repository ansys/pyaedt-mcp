"""Bootstrap the per-user PyAEDT MCP environment for the Windows executable."""

import os
from pathlib import Path
import re
import subprocess  # nosec B404
import sys
from typing import Any

PACKAGE_NAME = "ansys-aedt-mcp"
APP_DIRECTORY_NAME = ".pyaedt_mcp"
SERVER_MODE_FLAG = "--server"


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


def setup_environment(
    app_directory: Path,
    runtime_dir: Path,
    version: str | None = None,
    upgrade: bool = False,
) -> Path:
    """Create the venv and install or update the requested MCP package version."""
    python_executable, mcp_executable = command_paths(app_directory)
    if mcp_executable.is_file() and version is None and not upgrade:
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
    install_command = [
        str(uv_executable),
        "pip",
        "install",
        "--python",
        str(python_executable),
        "--index-strategy",
        "unsafe-best-match",
    ]
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
        mcp_executable = setup_environment(application_directory(), runtime_directory())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"PyAEDT MCP setup failed: {error}", file=sys.stderr)
        return 1

    return subprocess.call([str(mcp_executable), *arguments[1:]])  # nosec B603


if __name__ == "__main__":
    raise SystemExit(main())
