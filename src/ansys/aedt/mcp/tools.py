"""List of tools in PyAEDT-MCP.

This module provides MCP tools for interacting with Ansys Electronics Desktop (AEDT)
through PyAEDT library. It supports all AEDT applications including HFSS, Maxwell,
Icepak, Circuit, Q3D, and more.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastmcp.server import Context
from fastmcp.server.server import get_logger
from mcp.types import ImageContent, TextContent

from ansys.aedt.mcp import app
from ansys.aedt.mcp.helpers import (
    _is_docker,
    _probe_grpc_endpoint,
    get_aedt_info,
    resolve_design_app,
)
from ansys.aedt.mcp.server import session

logger = get_logger(__name__)

# Tool timeout tiers (seconds)
_TIMEOUT_QUICK = 30  # status checks, listing, info queries
_TIMEOUT_MEDIUM = 120  # connect, launch, open/save, create design, screenshot
_TIMEOUT_LONG = 300  # script execution, analysis, exports


def _open_file_in_default_viewer(path: Path) -> str | None:
    """Open a file with the system's default viewer.

    Returns
    -------
    str | None
        ``None`` when the file was opened successfully, otherwise a short
        message describing why the viewer could not be launched.
    """
    if _is_docker():
        return "Viewer launch skipped inside Docker."

    try:
        if hasattr(os, "startfile"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        return f"Viewer launch failed: {exc}"

    return None


def _configure_pyaedt_runtime_settings(enable_grpc: bool = False) -> None:
    """Configure PyAEDT runtime settings for safer MCP execution.

    Parameters
    ----------
    enable_grpc : bool, optional
        Whether to force gRPC API mode. Default is False.
    """
    try:
        # Preferred import path in newer PyAEDT versions.
        from ansys.aedt.core import settings
    except Exception:
        # Backward-compatible import path.
        from ansys.aedt.core.generic.settings import settings

    if enable_grpc:
        settings.use_grpc_api = True

    # Prevent Desktop shutdown when user-provided code raises.
    settings.release_on_exception = False


def _resolve_pyaedt_log_file() -> str | None:
    """Resolve the active PyAEDT global log file path.

    Returns
    -------
    str | None
        Absolute path to the active PyAEDT log file, or ``None`` when no
        readable log file can be resolved.
    """
    try:
        from ansys.aedt.core.aedt_logger import pyaedt_logger

        raw_logger = getattr(pyaedt_logger, "logger", None)
        if raw_logger is not None:
            for handler in getattr(raw_logger, "handlers", []):
                handler_path = getattr(handler, "baseFilename", None)
                if handler_path and os.path.isfile(handler_path):
                    return str(Path(handler_path).expanduser().resolve())

        logger_filename = getattr(pyaedt_logger, "filename", None)
        if logger_filename and os.path.isfile(logger_filename):
            return str(Path(logger_filename).expanduser().resolve())
    except Exception:
        pass

    try:
        from ansys.aedt.core import settings

        logger_file_path = getattr(settings, "logger_file_path", None)
        if logger_file_path:
            candidate = Path(logger_file_path).expanduser()
            if candidate.is_file():
                return str(candidate.resolve())
            if candidate.is_dir():
                log_candidates = sorted(
                    candidate.glob("pyaedt*.log"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if log_candidates:
                    return str(log_candidates[0].resolve())
    except Exception:
        pass

    return None


# AEDT Application types supported
AEDTAppType = Literal[
    "Hfss",
    "Maxwell2d",
    "Maxwell3d",
    "Q3d",
    "Q2d",
    "Icepak",
    "Circuit",
    "TwinBuilder",
    "Mechanical",
    "Emit",
    "RMXprt",
    "Hfss3dLayout",
]


def _get_aedt_app_class(app_type: AEDTAppType) -> Any | None:
    """Resolve an AEDT application type to the corresponding PyAEDT class."""
    import ansys.aedt.core as aedt

    app_map = {
        "Hfss": aedt.Hfss,
        "Maxwell2d": aedt.Maxwell2d,
        "Maxwell3d": aedt.Maxwell3d,
        "Q3d": aedt.Q3d,
        "Q2d": aedt.Q2d,
        "Icepak": aedt.Icepak,
        "Circuit": aedt.Circuit,
        "TwinBuilder": aedt.TwinBuilder,
        "Mechanical": aedt.Mechanical,
        "Emit": aedt.Emit,
        "RMXprt": getattr(aedt, "Rmxprt", None),
        "Hfss3dLayout": aedt.Hfss3dLayout,
    }
    return app_map.get(app_type)


@app.tool(timeout=_TIMEOUT_QUICK)
def check_aedt_status(ctx: Context) -> str:
    """Check the status of AEDT Desktop initialization.

    This tool retrieves comprehensive information from the connected AEDT
    Desktop instance including version, active projects, designs, and
    connection details.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.

    Returns
    -------
    str
        JSON string containing comprehensive AEDT status information including:
        - connection: Basic connection info (version, machine, port, is_grpc)
        - projects: List of open projects
        - active_project: Currently active project name
        - active_design: Currently active design name
        - installed_versions: Available AEDT versions on the system

        Returns an error message if AEDT is not available.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool to establish a connection."

    try:
        info = get_aedt_info(desktop)
        return json.dumps(info, indent=2)

    except Exception as e:
        error_msg = f"Error checking AEDT status: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_QUICK)
def get_pyaedt_logs(
    ctx: Context,
    tail_lines: int = 200,
    contains: str | None = None,
    max_chars: int = 40000,
) -> str:
    """Return recent entries from the PyAEDT global logger.

    This tool reads the active PyAEDT global log file and returns a tail view
    of the log contents. Optionally filter lines using a case-insensitive
    substring.

    Parameters
    ----------
    ctx : Context
        MCP context. Included for tool signature consistency.
    tail_lines : int, optional
        Number of recent lines to return after filtering. Default is 200.
    contains : str, optional
        Case-insensitive substring used to filter log lines.
    max_chars : int, optional
        Hard cap for returned log text length. Default is 40000 characters.

    Returns
    -------
    str
        JSON string with log metadata and selected log text.
    """
    del ctx  # tool does not require an active AEDT desktop connection

    if tail_lines <= 0:
        return "Invalid parameter: tail_lines must be greater than 0."
    if max_chars <= 0:
        return "Invalid parameter: max_chars must be greater than 0."

    safe_tail_lines = min(tail_lines, 5000)
    safe_max_chars = min(max_chars, 200000)

    try:
        log_file = _resolve_pyaedt_log_file()
        if log_file is None:
            return (
                "PyAEDT global log file could not be resolved. "
                "Run a PyAEDT operation first to initialize the logger."
            )

        with open(log_file, "r", encoding="utf-8", errors="replace") as file_handle:
            all_lines = file_handle.readlines()

        filtered_lines = all_lines
        if contains:
            filter_token = contains.lower()
            filtered_lines = [line for line in all_lines if filter_token in line.lower()]

        selected_lines = filtered_lines[-safe_tail_lines:]
        log_text = "".join(selected_lines)

        truncated = False
        if len(log_text) > safe_max_chars:
            log_text = log_text[-safe_max_chars:]
            truncated = True

        payload = {
            "log_file": log_file,
            "contains": contains,
            "total_lines": len(all_lines),
            "matched_lines": len(filtered_lines),
            "returned_lines": len(selected_lines),
            "tail_lines_requested": tail_lines,
            "max_chars_requested": max_chars,
            "truncated": truncated,
            "logs": log_text,
        }
        return json.dumps(payload, indent=2)

    except Exception as e:
        error_msg = f"Error reading PyAEDT logs: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_QUICK)
def check_aedt_installed(ctx: Context) -> str:
    """Check if AEDT is installed on the system.

    This tool checks for valid AEDT installations on the system and
    returns information about available versions.

    When running inside a Docker container, the tool probes the remote
    gRPC endpoint (``AEDT_MACHINE:AEDT_PORT``) instead of searching
    for a local AEDT installation.

    Returns
    -------
    str
        Status message indicating whether AEDT is installed and which versions
        are available.
    """
    logger.info("Checking if AEDT is installed...")

    # ------- Docker path: probe the remote gRPC endpoint -------
    if _is_docker():
        host = os.environ.get("AEDT_MACHINE", "host.docker.internal")
        port = int(os.environ.get("AEDT_PORT", "50051"))
        reachable = _probe_grpc_endpoint(host, port)
        if reachable:
            return f"Running inside Docker – AEDT gRPC endpoint at " f"{host}:{port} is reachable."
        return (
            f"Running inside Docker – AEDT gRPC endpoint at "
            f"{host}:{port} is NOT reachable. Ensure AEDT is started "
            f"with: ansysedt.exe -grpcsrv {port}"
        )

    # ------- Native path: search for local installation -------
    try:
        from ansys.aedt.core.desktop import Desktop

        # Get installed versions without starting AEDT
        temp_desktop = Desktop.__new__(Desktop)
        installed = getattr(temp_desktop, "installed_versions", {})

        if installed:
            versions = list(installed.keys())
            logger.info(f"AEDT installations found: {versions}")
            return f"AEDT is installed on this system.\nAvailable versions: {', '.join(str(v) for v in versions)}"
        else:
            # Try alternative detection
            import subprocess

            result = subprocess.run(
                ["where", "ansysedt.exe"], capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return f"AEDT executable found at: {result.stdout.strip()}"
            else:
                return (
                    "AEDT is not installed on this system or cannot be found. "
                    "Please ensure ANSYS Electronics Desktop is properly installed "
                    "and the installation path is in the system PATH."
                )

    except Exception as e:
        error_msg = f"Error checking AEDT installation: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools", "locked_connection"}, timeout=_TIMEOUT_MEDIUM)
def launch_aedt(
    ctx: Context,
    version: str | None = None,
    non_graphical: bool = False,
    new_desktop: bool = True,
    application: AEDTAppType | None = None,
) -> str:
    """Launch a new AEDT Desktop instance.

    This tool starts a new AEDT Desktop instance using PyAEDT's Desktop class,
    or launches directly into a specific AEDT application session when requested.
    The launched instance will be automatically connected and stored in the context
    for subsequent operations.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    version : str, optional
        The AEDT version to launch (e.g., "2026.1", "261"). If None, the latest
        installed version will be used.
    non_graphical : bool, optional
        Whether to launch AEDT in non-graphical mode. Default is False
        (launch in graphical mode).
    new_desktop : bool, optional
        Whether to launch a new AEDT instance even if one is already running.
        Default is True.
    application : AEDTAppType, optional
        AEDT application to launch directly, such as ``Hfss`` or ``Maxwell3d``.
        If omitted, AEDT launches in desktop mode.

    Returns
    -------
    str
        Launch status message with AEDT version and connection information.
    """
    launch_target = application or "Desktop"
    logger.info(f"Launching new AEDT {launch_target} instance...")

    # Docker guard: launching a local AEDT inside a container is not supported
    if _is_docker():
        return (
            "Launching a local AEDT instance from inside a Docker container "
            "is not supported. Use the connect_to_aedt tool to connect to an "
            "AEDT instance running on the host or a remote machine."
        )

    try:
        # Check if there's already a connection
        if ctx.request_context.lifespan_context.desktop is not None:
            return (
                "Already connected to an AEDT Desktop instance. "
                "Please disconnect first using disconnect_from_aedt tool."
            )

        from ansys.aedt.core import Desktop

        _configure_pyaedt_runtime_settings()

        kwargs: dict[str, Any] = {
            "non_graphical": non_graphical,
            "new_desktop": new_desktop,
        }

        if version is not None:
            kwargs["version"] = version

        if application is None:
            desktop = Desktop(**kwargs)
            launched_target = "AEDT Desktop"
        else:
            app_class = _get_aedt_app_class(application)
            if app_class is None:
                return f"Unsupported application type: {application}"

            app_instance = app_class(**kwargs)
            desktop = getattr(app_instance, "desktop_class", None)
            if desktop is None:
                raise RuntimeError(
                    f"Unable to resolve desktop handle from launched {application} session"
                )
            launched_target = application

        # Store in context for later use
        ctx.request_context.lifespan_context.desktop = desktop

        logger.info(f"AEDT launched successfully! Target: {launched_target}")
        return (
            f"Successfully launched {launched_target}\n"
            f"Version: {desktop.aedt_version_id}\n"
            f"Installation Directory: {desktop.aedt_install_dir}\n"
            f"Non-graphical Mode: {non_graphical}\n"
            f"gRPC Mode: {desktop.is_grpc_api}\n"
        )

    except Exception as e:
        error_msg = f"Failed to launch AEDT: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools", "locked_connection"}, timeout=_TIMEOUT_MEDIUM)
def connect_to_aedt(
    ctx: Context,
    port: int = 50051,
    machine: str = "localhost",
    version: str | None = None,
    non_graphical: bool = True,
    project_name: str | None = None,
    design_name: str | None = None,
) -> str:
    """Connect to an existing AEDT instance via gRPC.

    This tool establishes a connection to a running AEDT instance using gRPC.
    The AEDT instance must be started with gRPC server enabled:
    `ansysedt.exe -grpcsrv <port>`

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    port : int, optional
        The gRPC port where AEDT is listening. Default is 50051.
    machine : str, optional
        The machine hostname or IP where AEDT is running. Default is "localhost".
    version : str, optional
        The AEDT version to connect to. If None, will auto-detect.
    non_graphical : bool, optional
        Whether AEDT is running in non-graphical mode. Default is True.
    project_name : str, optional
        Project name to activate when connecting directly to a design.
    design_name : str, optional
        Design name to attach directly to a PyAEDT application session.
        If omitted, the connection remains at AEDT desktop level.

    Returns
    -------
    str
        Connection status message with AEDT version information.
    """
    logger.info(f"Connecting to AEDT instance at {machine}:{port}...")

    # Docker env-var override: when defaults are used and we are inside a
    # container, prefer AEDT_MACHINE / AEDT_PORT from the environment so
    # the container automatically reaches the host AEDT instance.
    if _is_docker():
        if machine == "localhost":
            machine = os.environ.get("AEDT_MACHINE", "host.docker.internal")
        if port == 50051:
            port = int(os.environ.get("AEDT_PORT", "50051"))
        logger.info(f"Docker detected – using AEDT endpoint {machine}:{port}")

    try:
        # Check if there's already a connection
        if ctx.request_context.lifespan_context.desktop is not None:
            return (
                "Already connected to an AEDT Desktop instance. "
                "Please disconnect first using disconnect_from_aedt tool."
            )

        from ansys.aedt.core import Desktop, get_pyaedt_app

        _configure_pyaedt_runtime_settings(enable_grpc=True)

        # Connect to existing AEDT instance
        kwargs: dict[str, Any] = {
            "non_graphical": non_graphical,
            "new_desktop": False,  # Connect to existing
            "machine": machine,
            "port": port,
        }

        if version is not None:
            kwargs["version"] = version

        desktop = Desktop(**kwargs)

        connected_app = None
        if design_name is not None:
            connected_app = get_pyaedt_app(
                project_name=project_name,
                design_name=design_name,
                desktop=desktop,
            )
            if connected_app is None:
                raise RuntimeError(
                    f"Unable to attach to project '{project_name}' design '{design_name}'"
                )

        # Store in context for later use
        ctx.request_context.lifespan_context.desktop = desktop

        logger.info(f"Connected to AEDT successfully at {machine}:{port}!")
        message = (
            f"Successfully connected to AEDT at {machine}:{port}\n"
            f"Version: {desktop.aedt_version_id}\n"
            f"gRPC Mode: {desktop.is_grpc_api}\n"
        )
        if connected_app is not None:
            message += (
                f"Project: {connected_app.project_name}\n"
                f"Design: {connected_app.design_name}\n"
                f"Application: {connected_app.design_type}\n"
            )
        else:
            message += (
                "Tip: provide design_name"
                + (" and project_name" if project_name is None else "")
                + " if you want to connect directly to a specific AEDT design.\n"
            )
        return message

    except Exception as e:
        error_msg = f"Failed to connect to AEDT at {machine}:{port}: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools", "locked_connection"}, timeout=_TIMEOUT_MEDIUM)
def disconnect_from_aedt(ctx: Context, close_projects: bool = False) -> str:
    """Disconnect from the AEDT Desktop instance.

    This tool closes the connection to the AEDT Desktop instance and releases
    associated resources.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    close_projects : bool, optional
        Whether to close all open projects before disconnecting. Default is False.

    Returns
    -------
    str
        Disconnection status message.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return "No AEDT Desktop connection to disconnect."

    try:
        logger.info("Disconnecting from AEDT...")

        # Release desktop
        desktop.release_desktop(close_projects=close_projects)
        ctx.request_context.lifespan_context.desktop = None

        logger.info("Disconnected from AEDT successfully!")
        return "Successfully disconnected from AEDT Desktop."

    except Exception as e:
        error_msg = f"Error during AEDT disconnect: {str(e)}"
        logger.error(error_msg)
        # Clear the connection anyway
        ctx.request_context.lifespan_context.desktop = None
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_LONG)
def run_python_script(ctx: Context, script_path: str) -> str:
    """Execute a Python script file inside AEDT.

    This tool runs a Python script from a file path within the AEDT environment,
    using AEDT's built-in Python interpreter. The script has access to all AEDT
    APIs including oDesktop, oProject, oDesign, etc.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    script_path : str
        The path to the Python script file to execute.

    Returns
    -------
    str
        Script execution result or error message.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        # Verify file exists
        if not os.path.exists(script_path):
            return f"Script file not found: {script_path}"

        logger.info(f"Executing script: {script_path}")

        # Execute using desktop's _run_script method or oDesktop API
        result = desktop.odesktop.RunScript(script_path)

        return f"Script executed successfully.\nResult: {result}"

    except Exception as e:
        error_msg = f"Error executing script {script_path}: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_LONG)
def run_python_code(ctx: Context, code: str) -> str:
    """Execute Python code inside AEDT.

    This tool runs inline Python code within the AEDT environment. The code
    has access to the connected Desktop instance via the `desktop` variable.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    code : str
        The Python code to execute. The code has access to:
        - `desktop`: The PyAEDT Desktop instance
        - `odesktop`: The native AEDT oDesktop COM object

    Returns
    -------
    str
        Code execution result or error message.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        logger.info("Executing inline Python code in AEDT...")

        # Keep AEDT alive when user code raises an exception.
        _configure_pyaedt_runtime_settings()

        # Create a local namespace with desktop available
        local_ns = {
            "desktop": desktop,
            "odesktop": desktop.odesktop,
        }

        # Execute the code
        exec(code, local_ns)

        # Try to get result if defined
        result = local_ns.get("result", "Code executed successfully (no result variable set)")

        return str(result)

    except Exception as e:
        error_msg = f"Error executing code: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_QUICK)
def list_designs(ctx: Context, project_name: str | None = None) -> str:
    """List projects and designs for the connected AEDT instance.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    project_name : str, optional
        Optional project name to limit the response to a single project.
        If None, all open projects and their designs are returned.

    Returns
    -------
    str
        JSON string containing the connected instance projects and designs.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        if project_name is not None:
            projects = [project_name]
        else:
            projects = list(desktop.project_list)

        project_entries = []
        total_design_count = 0
        for project in projects:
            designs = desktop.design_list(project)
            project_entries.append(
                {
                    "project": project,
                    "designs": designs,
                    "count": len(designs),
                }
            )
            total_design_count += len(designs)

        active_project = None
        if callable(getattr(desktop, "active_project", None)):
            current_project = desktop.active_project()
            if current_project is not None and hasattr(current_project, "GetName"):
                active_project = str(current_project.GetName())

        active_design = None
        if callable(getattr(desktop, "active_design", None)):
            current_design = desktop.active_design()
            if current_design is not None and hasattr(current_design, "GetName"):
                active_design = str(current_design.GetName())

        result = {
            "active_project": active_project,
            "active_design": active_design,
            "projects": project_entries,
            "project_count": len(project_entries),
            "design_count": total_design_count,
        }
        if project_name is not None and project_entries:
            result["project"] = project_entries[0]["project"]
            result["designs"] = project_entries[0]["designs"]
            result["count"] = project_entries[0]["count"]
        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Error listing designs: {str(e)}"
        logger.error(error_msg)
        return error_msg


def list_projects(ctx: Context) -> str:
    """Backward-compatible wrapper for callers expecting project-only listing."""
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        projects = list(desktop.project_list)
        result = {
            "open_projects": projects,
            "count": len(projects),
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Error listing projects: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_MEDIUM)
def open_project(ctx: Context, project_path: str, design_name: str | None = None) -> str:
    """Open an AEDT project file.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    project_path : str
        Full path to the .aedt project file.
    design_name : str, optional
        Name of the design to activate after opening. If None, the first design
        will be active.

    Returns
    -------
    str
        Status message with project and design information.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        if not os.path.exists(project_path):
            return f"Project file not found: {project_path}"

        logger.info(f"Opening project: {project_path}")
        desktop.load_project(project_path, design_name=design_name)

        return (
            f"Successfully opened project: {project_path}\n"
            f"Active design: {design_name or 'First design in project'}"
        )

    except Exception as e:
        error_msg = f"Error opening project: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_MEDIUM)
def save_project(ctx: Context, project_name: str | None = None, save_as: str | None = None) -> str:
    """Save an AEDT project.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    project_name : str, optional
        Name of the project to save. If None, saves the active project.
    save_as : str, optional
        Path to save the project to. If None, saves to existing location.

    Returns
    -------
    str
        Status message confirming the save operation.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        logger.info(f"Saving project: {project_name or 'active project'}")

        if save_as:
            desktop.save_project(project_file=save_as)
            return f"Project saved to: {save_as}"
        else:
            desktop.save_project(project_name=project_name)
            return f"Project saved successfully: {project_name or 'active project'}"

    except Exception as e:
        error_msg = f"Error saving project: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_MEDIUM)
def create_design(
    ctx: Context,
    app_type: AEDTAppType,
    design_name: str | None = None,
    project_name: str | None = None,
    solution_type: str | None = None,
) -> str:
    """Create a new design in AEDT.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    app_type : str
        The AEDT application type. Must be one of: 'Hfss', 'Maxwell2d',
        'Maxwell3d', 'Q3d', 'Q2d', 'Icepak', 'Circuit', 'TwinBuilder',
        'Mechanical', 'Emit', 'RMXprt', 'Hfss3dLayout'.
    design_name : str, optional
        Name for the new design. If None, AEDT will auto-generate a name.
    project_name : str, optional
        Project to create design in. If None, uses active project.
    solution_type : str, optional
        Solution type for the design (app-specific).

    Returns
    -------
    str
        Status message with the created design information.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        app_class = _get_aedt_app_class(app_type)
        if app_class is None:
            return f"Unsupported application type: {app_type}"

        logger.info(f"Creating {app_type} design: {design_name}")

        kwargs: dict[str, Any] = {}
        if design_name:
            kwargs["design"] = design_name
        if project_name:
            kwargs["project"] = project_name
        if solution_type:
            kwargs["solution_type"] = solution_type

        # Create the application/design
        app_instance = app_class(**kwargs)

        return (
            f"Successfully created {app_type} design\n"
            f"Design Name: {app_instance.design_name}\n"
            f"Project: {app_instance.project_name}\n"
            f"Solution Type: {app_instance.solution_type}\n"
        )

    except Exception as e:
        error_msg = f"Error creating design: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_LONG)
def analyze_design(
    ctx: Context,
    setup_name: str | None = None,
    project_name: str | None = None,
    design_name: str | None = None,
    num_cores: int | None = None,
    num_tasks: int | None = None,
    num_gpus: int | None = None,
    acf_file: str | None = None,
    use_auto_settings: bool = True,
    solve_in_batch: bool = False,
    machine: str = "localhost",
    run_in_thread: bool = False,
    revert_to_initial_mesh: bool = False,
    blocking: bool = True,
    analyze_all_designs: bool = False,
) -> str:
    """Run analysis on an AEDT design.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    setup_name : str, optional
        Name of the setup to analyze. If None, analyzes all setups in the target design.
    project_name : str, optional
        Name of the project to analyze. If None, uses the active project.
    design_name : str, optional
        Name of the design to analyze. If None, uses active design.
    num_cores : int, optional
        Number of CPU cores to use for analysis.
    num_tasks : int, optional
        Number of HPC tasks to use for analysis.
    num_gpus : int, optional
        Number of GPUs to use for analysis.
    acf_file : str, optional
        Full path to a custom ACF file for HPC configuration.
    use_auto_settings : bool, optional
        Whether to use automatic HPC settings when supported.
    solve_in_batch : bool, optional
        Whether to solve the design in batch mode.
    machine : str, optional
        Target machine name for remote or batch solves.
    run_in_thread : bool, optional
        Whether to submit the batch solve in a background thread.
    revert_to_initial_mesh : bool, optional
        Whether to revert to the initial mesh before solving.
    blocking : bool, optional
        Whether to block until the solve is complete.
    analyze_all_designs : bool, optional
        When True, call Desktop.analyze_all for the target project/design. This
        analyzes all setups in a design or all designs in a project.

    Returns
    -------
    str
        Status message with analysis results.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        if analyze_all_designs:
            if setup_name:
                return (
                    "setup_name cannot be used when analyze_all_designs=True. "
                    "Use design-level analysis to solve a specific setup."
                )

            logger.info(
                "Running desktop analyze_all on project=%s design=%s",
                project_name or "active project",
                design_name or "all designs",
            )

            result = desktop.analyze_all(project=project_name, design=design_name)
            if not result:
                return "Analysis failed during desktop-wide analyze_all invocation."

            return (
                "Analysis completed successfully.\n"
                f"Project: {project_name or 'active project'}\n"
                f"Design Scope: {design_name or 'all designs'}\n"
                "Mode: desktop analyze_all\n"
                f"Result: {result}"
            )

        app_instance, resolved_project_name, resolved_design_name = resolve_design_app(
            desktop,
            project_name=project_name,
            design_name=design_name,
        )

        logger.info(
            "Running design analysis on project=%s design=%s setup=%s",
            resolved_project_name or project_name or "active project",
            resolved_design_name or design_name or "active design",
            setup_name or "all setups",
        )

        result = app_instance.analyze(
            setup=setup_name,
            cores=num_cores,
            tasks=num_tasks,
            gpus=num_gpus,
            acf_file=acf_file,
            use_auto_settings=use_auto_settings,
            solve_in_batch=solve_in_batch,
            machine=machine,
            run_in_thread=run_in_thread,
            revert_to_initial_mesh=revert_to_initial_mesh,
            blocking=blocking,
        )

        if not result:
            return (
                "Analysis failed.\n"
                f"Project: {resolved_project_name or 'Unknown'}\n"
                f"Design: {resolved_design_name or 'Unknown'}\n"
                f"Setup: {setup_name or 'all setups'}"
            )

        return (
            "Analysis completed successfully.\n"
            f"Project: {resolved_project_name or getattr(app_instance, 'project_name', 'Unknown')}\n"
            f"Design: {resolved_design_name or getattr(app_instance, 'design_name', 'Unknown')}\n"
            f"Setup: {setup_name or 'all setups'}\n"
            f"Mode: {'batch' if solve_in_batch else 'interactive'}\n"
            f"Blocking: {blocking}\n"
            f"Result: {result}"
        )

    except Exception as e:
        error_msg = f"Error during analysis: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_LONG)
def export_results(
    ctx: Context,
    output_path: str,
    export_type: str = "touchstone",
    setup_name: str | None = None,
) -> str:
    """Export simulation results from AEDT.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    output_path : str
        Path where results will be exported.
    export_type : str, optional
        Type of export. Options: 'touchstone', 'profile', 'convergence', 'mesh'.
        Default is 'touchstone'.
    setup_name : str, optional
        Setup name for the export. If None, uses active setup.

    Returns
    -------
    str
        Status message with export file path.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        logger.info(f"Exporting {export_type} results to: {output_path}")

        # This would need access to the active application
        # For now, return a placeholder
        return "Export functionality requires an active application instance. Use create_design first to create an app-specific connection."

    except Exception as e:
        error_msg = f"Error exporting results: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(timeout=_TIMEOUT_MEDIUM)
def screenshot(
    ctx: Context,
    path: str = "screenshot.jpg",
    project: str | None = None,
    design: str | None = None,
    plot_type: str = "model",
    open_viewer: bool = True,
) -> list[TextContent | ImageContent]:
    """Capture a screenshot of the current AEDT design view.

    This tool captures the current design preview as an image. It supports
    model views, field plots, and mesh visualizations depending on what's
    currently displayed in AEDT.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    path : str, optional
        Output image path. Default is ``"screenshot.jpg"``.
    project : str, optional
        Project containing the design to capture. If None, uses active project.
    design : str, optional
        Design to capture. If None, uses active design.
    plot_type : str, optional
        Type of screenshot: "model", "field", or "mesh". Default is "model".
    open_viewer : bool, optional
        Whether to open the saved screenshot in the system image viewer.
        Default is True.

    Returns
    -------
    list[TextContent | ImageContent]
        A list containing:
        - TextContent with the screenshot file path
        - ImageContent with the base64-encoded image data
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return [
            TextContent(
                type="text",
                text=(
                    "No AEDT Desktop connection available. "
                    "Use connect_to_aedt or launch_aedt tool first."
                ),
            )
        ]

    try:
        logger.info(f"Capturing AEDT screenshot (type: {plot_type})...")
        try:
            app_instance, _, _ = resolve_design_app(
                desktop, project_name=project, design_name=design
            )
        except RuntimeError as resolve_error:
            return [TextContent(type="text", text=f"Cannot capture screenshot: {resolve_error}")]

        output_path = str(Path(path).expanduser().resolve())

        try:
            app_instance.export_design_preview_to_jpg(output_path)
        except Exception as export_error:
            raise RuntimeError(
                f"Failed to export screenshot: {export_error}. "
                "Try saving the project first before exporting an image."
            ) from export_error

        # Verify file was created
        image_path = Path(output_path)
        if not image_path.exists():
            raise RuntimeError(f"Screenshot file not created: {output_path}")

        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = f.read()
        base64_data = base64.b64encode(image_data).decode("utf-8")
        mime_type = "image/jpeg"

        viewer_message = None
        if open_viewer:
            viewer_message = _open_file_in_default_viewer(image_path)

        logger.info(f"Screenshot captured successfully: {output_path}")

        status_lines = [
            f"Screenshot saved to '{output_path}'",
            f"Design: {app_instance.design_name}",
            f"Project: {app_instance.project_name}",
        ]
        if open_viewer:
            status_lines.append(viewer_message or "Opened screenshot in the default image viewer.")

        return [
            TextContent(
                type="text",
                text="\n".join(status_lines),
            ),
            ImageContent(type="image", data=base64_data, mimeType=mime_type),
        ]

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_MEDIUM)
def export_config(
    ctx: Context,
    output: str | None = None,
    project: str | None = None,
    design: str | None = None,
    overwrite: bool = False,
) -> str:
    """Export the active design configuration as JSON.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    output : str, optional
        Output JSON file path. If omitted, the configuration is exported to a
        temporary file and returned inline.
    project : str, optional
        Project containing the design to export.
    design : str, optional
        Design to export configuration from.
    overwrite : bool, optional
        Whether to overwrite an existing config file.

    Returns
    -------
    str
        JSON string containing the exported configuration and associated
        design metadata. When ``output`` is provided, the returned JSON also
        includes the written config file path.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    temp_config_file: str | None = None

    try:
        app_instance, resolved_project, _ = resolve_design_app(
            desktop, project_name=project, design_name=design
        )

        if output:
            config_target = output if output.lower().endswith(".json") else f"{output}.json"
        else:
            fd, config_target = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            os.remove(config_target)
            temp_config_file = config_target

        config_file = app_instance.configurations.export_config(
            config_file=config_target, overwrite=overwrite
        )
        if not config_file:
            raise RuntimeError("Failed to export configuration.")

        with open(config_file, "r", encoding="utf-8") as file_handle:
            config_content = json.load(file_handle)

        data: dict[str, Any] = {
            "config": config_content,
            "design": app_instance.design_name,
            "project": resolved_project,
        }
        if output:
            data["config_file"] = config_file

        return json.dumps(data, indent=2)

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.error(error_msg)
        return error_msg
    finally:
        if temp_config_file and os.path.exists(temp_config_file):
            os.remove(temp_config_file)


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_MEDIUM)
def clear_aedt(ctx: Context, close_projects: bool = True) -> str:
    """Clear AEDT state by closing all projects.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    close_projects : bool, optional
        Whether to close all open projects. Default is True.

    Returns
    -------
    str
        Status message confirming the clear operation.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return "No AEDT Desktop connection available."

    try:
        logger.info("Clearing AEDT state...")

        if close_projects:
            # Get list of projects and close them
            projects = desktop.project_list
            for proj in projects:
                desktop.odesktop.CloseProject(proj)

        desktop.clear_messages()

        return f"AEDT state cleared. Closed {len(projects) if close_projects else 0} project(s)."

    except Exception as e:
        error_msg = f"Error clearing AEDT: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_QUICK)
def get_model_info(ctx: Context, design_name: str | None = None) -> str:
    """Get information about the current model/design.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    design_name : str, optional
        Name of the design to get info for. If None, uses active design.

    Returns
    -------
    str
        JSON string containing model information.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return (
            "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."
        )

    try:
        design_type = desktop.design_type(design_name=design_name)
        project_path = desktop.project_path()

        result = {
            "design_name": design_name or "Active Design",
            "design_type": design_type,
            "project_path": project_path,
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Error getting model info: {str(e)}"
        logger.error(error_msg)
        return error_msg


# Conditionally disable tools based on session configuration
# Tools tagged with "locked_connection" should be disabled when connection is locked
if session.locked_connection:
    app.disable(tags={"locked_connection"})
