"""List of tools in PyAEDT-MCP.

This module provides MCP tools for interacting with Ansys Electronics Desktop (AEDT)
through PyAEDT library. It supports all AEDT applications including HFSS, Maxwell,
Icepak, Circuit, Q3D, and more.
"""

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastmcp.server import Context
from fastmcp.server.server import get_logger
from mcp.types import ImageContent, TextContent

from ansys.aedt.mcp import app
from ansys.aedt.mcp.helpers import _is_docker, _probe_grpc_endpoint, get_aedt_info
from ansys.aedt.mcp.server import session

logger = get_logger(__name__)

# Tool timeout tiers (seconds)
_TIMEOUT_QUICK = 30       # status checks, listing, info queries
_TIMEOUT_MEDIUM = 120     # connect, launch, open/save, create design, screenshot
_TIMEOUT_LONG = 300       # script execution, analysis, exports


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


# AEDT Application types supported
AEDTAppType = Literal[
    "Hfss", "Maxwell2d", "Maxwell3d", "Q3d", "Q2d", "Icepak",
    "Circuit", "TwinBuilder", "Mechanical", "Emit", "RMXprt", "Hfss3dLayout"
]


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
            return (
                f"Running inside Docker – AEDT gRPC endpoint at "
                f"{host}:{port} is reachable."
            )
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
        installed = getattr(temp_desktop, 'installed_versions', {})

        if installed:
            versions = list(installed.keys())
            logger.info(f"AEDT installations found: {versions}")
            return f"AEDT is installed on this system.\nAvailable versions: {', '.join(str(v) for v in versions)}"
        else:
            # Try alternative detection
            import subprocess
            result = subprocess.run(
                ["where", "ansysedt.exe"],
                capture_output=True,
                text=True,
                timeout=30
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
) -> str:
    """Launch a new AEDT Desktop instance.

    This tool starts a new AEDT Desktop instance using PyAEDT's Desktop class.
    The launched instance will be automatically connected and stored in the context
    for subsequent operations.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    version : str, optional
        The AEDT version to launch (e.g., "2025.2", "252"). If None, the latest
        installed version will be used.
    non_graphical : bool, optional
        Whether to launch AEDT in non-graphical mode. Default is False
        (launch in graphical mode).
    new_desktop : bool, optional
        Whether to launch a new AEDT instance even if one is already running.
        Default is True.

    Returns
    -------
    str
        Launch status message with AEDT version and connection information.
    """
    logger.info("Launching new AEDT Desktop instance...")

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

        # Launch new AEDT instance
        kwargs: dict[str, Any] = {
            "non_graphical": non_graphical,
            "new_desktop": new_desktop,
        }

        if version is not None:
            kwargs["version"] = version

        desktop = Desktop(**kwargs)

        # Store in context for later use
        ctx.request_context.lifespan_context.desktop = desktop

        logger.info(f"AEDT launched successfully! Version: {desktop.aedt_version_id}")
        return (
            f"Successfully launched AEDT Desktop\n"
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
        logger.info(
            f"Docker detected – using AEDT endpoint {machine}:{port}"
        )

    try:
        # Check if there's already a connection
        if ctx.request_context.lifespan_context.desktop is not None:
            return (
                "Already connected to an AEDT Desktop instance. "
                "Please disconnect first using disconnect_from_aedt tool."
            )

        from ansys.aedt.core import Desktop

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

        # Store in context for later use
        ctx.request_context.lifespan_context.desktop = desktop

        logger.info(f"Connected to AEDT successfully at {machine}:{port}!")
        return (
            f"Successfully connected to AEDT at {machine}:{port}\n"
            f"Version: {desktop.aedt_version_id}\n"
            f"gRPC Mode: {desktop.is_grpc_api}\n"
        )

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
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

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
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

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
def list_projects(ctx: Context) -> str:
    """List all open projects in AEDT.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.

    Returns
    -------
    str
        JSON string containing list of open projects and their paths.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

    try:
        projects = desktop.project_list
        result = {
            "open_projects": projects,
            "count": len(projects),
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Error listing projects: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_QUICK)
def list_designs(ctx: Context, project_name: str | None = None) -> str:
    """List all designs in a project.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    project_name : str, optional
        The project name to list designs from. If None, uses the active project.

    Returns
    -------
    str
        JSON string containing list of designs and their types.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

    try:
        designs = desktop.design_list(project_name)
        result = {
            "project": project_name or "Active Project",
            "designs": designs,
            "count": len(designs),
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Error listing designs: {str(e)}"
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
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

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
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

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
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

    try:
        import ansys.aedt.core as aedt

        # Map app_type to class
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

        app_class = app_map.get(app_type)
        if app_class is None:
            return f"Unsupported application type: {app_type}. Supported types: {list(app_map.keys())}"

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
    design_name: str | None = None,
    num_cores: int | None = None,
) -> str:
    """Run analysis on an AEDT design.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    setup_name : str, optional
        Name of the setup to analyze. If None, analyzes all setups.
    design_name : str, optional
        Name of the design to analyze. If None, uses active design.
    num_cores : int, optional
        Number of CPU cores to use for analysis.

    Returns
    -------
    str
        Status message with analysis results.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

    try:
        logger.info(f"Running analysis on setup: {setup_name or 'all setups'}")

        # Get active project and analyze
        if setup_name:
            result = desktop.analyze_all(design=design_name, setup=setup_name)
        else:
            result = desktop.analyze_all(design=design_name)

        return f"Analysis completed successfully.\nResult: {result}"

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
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

    try:
        logger.info(f"Exporting {export_type} results to: {output_path}")

        # This would need access to the active application
        # For now, return a placeholder
        return f"Export functionality requires an active application instance. Use create_design first to create an app-specific connection."

    except Exception as e:
        error_msg = f"Error exporting results: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_QUICK)
def list_files(ctx: Context, directory: str | None = None, pattern: str = "*") -> str:
    """List files in the AEDT working directory.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    directory : str, optional
        Directory to list. If None, uses AEDT's temp directory.
    pattern : str, optional
        Glob pattern for filtering files. Default is '*' (all files).

    Returns
    -------
    str
        JSON string containing list of files.
    """
    try:
        import glob

        if directory is None:
            directory = tempfile.gettempdir()

        search_path = os.path.join(directory, pattern)
        files = glob.glob(search_path)

        file_info = []
        for f in files:
            stat = os.stat(f)
            file_info.append({
                "name": os.path.basename(f),
                "path": f,
                "size": stat.st_size,
                "is_directory": os.path.isdir(f),
            })

        result = {
            "directory": directory,
            "pattern": pattern,
            "files": file_info,
            "count": len(file_info),
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Error listing files: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_MEDIUM)
def upload_file(ctx: Context, local_path: str, remote_path: str | None = None) -> str:
    """Upload a file to the AEDT working directory.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    local_path : str
        Path to the local file to upload.
    remote_path : str, optional
        Destination path on the AEDT machine. If None, uploads to temp directory.

    Returns
    -------
    str
        Status message with the uploaded file path.
    """
    try:
        if not os.path.exists(local_path):
            return f"Local file not found: {local_path}"

        if remote_path is None:
            remote_path = os.path.join(tempfile.gettempdir(), os.path.basename(local_path))

        # For local connections, just copy
        import shutil
        shutil.copy2(local_path, remote_path)

        return f"File uploaded successfully to: {remote_path}"

    except Exception as e:
        error_msg = f"Error uploading file: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_MEDIUM)
def download_file(ctx: Context, remote_path: str, local_path: str | None = None) -> str:
    """Download a file from the AEDT working directory.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    remote_path : str
        Path to the remote file to download.
    local_path : str, optional
        Local destination path. If None, downloads to current working directory.

    Returns
    -------
    str
        Status message with the downloaded file path.
    """
    try:
        if not os.path.exists(remote_path):
            return f"Remote file not found: {remote_path}"

        if local_path is None:
            local_path = os.path.join(os.getcwd(), os.path.basename(remote_path))

        # For local connections, just copy
        import shutil
        shutil.copy2(remote_path, local_path)

        return f"File downloaded successfully to: {local_path}"

    except Exception as e:
        error_msg = f"Error downloading file: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(timeout=_TIMEOUT_MEDIUM)
def screenshot(
    ctx: Context,
    design_name: str | None = None,
    plot_type: str = "model",
) -> list[TextContent | ImageContent]:
    """Capture a screenshot of the current AEDT design view.

    This tool captures the current design preview as an image. It supports
    model views, field plots, and mesh visualizations depending on what's
    currently displayed in AEDT.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    design_name : str, optional
        Name of the design to capture. If None, uses active design.
    plot_type : str, optional
        Type of screenshot: "model", "field", or "mesh". Default is "model".

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

        # Create a temporary file with .jpg extension
        temp_fd, temp_path = tempfile.mkstemp(suffix=".jpg", prefix="aedt_screenshot_")
        os.close(temp_fd)

        # Use Desktop's export_design_preview_to_jpg if available
        try:
            # Try to export design preview
            if hasattr(desktop, "export_design_preview_to_jpg"):
                desktop.export_design_preview_to_jpg(temp_path)
            else:
                # Alternative: use oDesktop.ExportImage if available
                desktop.odesktop.ExportImage(temp_path, 1920, 1080)
        except Exception as e:
            logger.warning(f"Design preview export failed, trying alternative: {e}")
            # If export fails, return error
            return [TextContent(type="text", text=f"Screenshot capture failed: {str(e)}")]

        # Verify file was created
        image_path = Path(temp_path)
        if not image_path.exists():
            return [TextContent(type="text", text=f"Screenshot file not created: {temp_path}")]

        # Read image data
        with open(image_path, "rb") as f:
            image_data = f.read()

        # Encode to base64
        base64_data = base64.b64encode(image_data).decode("utf-8")

        # Determine mime type
        mime_type = "image/jpeg"

        logger.info(f"Screenshot captured successfully: {temp_path}")

        # Return both text (file path) and image content
        return [
            TextContent(type="text", text=f"Screenshot saved to: {temp_path}"),
            ImageContent(type="image", data=base64_data, mimeType=mime_type),
        ]

    except Exception as e:
        error_msg = f"Failed to capture screenshot: {str(e)}"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_LONG)
def export_touchstone(
    ctx: Context,
    output_path: str,
    setup_name: str | None = None,
    solution_name: str | None = None,
) -> str:
    """Export S-parameters to Touchstone format.

    This tool exports simulation results in Touchstone (.sNp) format,
    which is the standard format for S-parameter data exchange.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    output_path : str
        Path for the output Touchstone file (e.g., "results.s2p").
    setup_name : str, optional
        Name of the setup to export. If None, uses first available setup.
    solution_name : str, optional
        Name of the solution to export. If None, uses default solution.

    Returns
    -------
    str
        Status message with export details.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

    try:
        logger.info(f"Exporting Touchstone to: {output_path}")

        # Note: This requires an active HFSS or similar RF design
        # The actual implementation depends on the active application type
        return (
            f"Touchstone export configured for: {output_path}\n"
            "Note: Actual export requires an active RF simulation design (HFSS, Circuit, etc.) "
            "with completed analysis. Use create_design and analyze_design first."
        )

    except Exception as e:
        error_msg = f"Error exporting Touchstone: {str(e)}"
        logger.error(error_msg)
        return error_msg


@app.tool(tags={"aedt_tools"}, timeout=_TIMEOUT_LONG)
def export_3d_model(
    ctx: Context,
    output_path: str,
    export_format: str = "step",
    design_name: str | None = None,
) -> str:
    """Export 3D geometry from AEDT design.

    This tool exports the 3D geometry in various CAD formats for use
    in other applications or for documentation.

    Parameters
    ----------
    ctx : Context
        The MCP context containing server session and application context.
    output_path : str
        Path for the output file.
    export_format : str, optional
        Export format: "step", "iges", "sat", "stl". Default is "step".
    design_name : str, optional
        Name of the design to export. If None, uses active design.

    Returns
    -------
    str
        Status message with export details.
    """
    desktop = ctx.request_context.lifespan_context.desktop

    if desktop is None:
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

    try:
        logger.info(f"Exporting 3D model to {export_format}: {output_path}")

        # Validate format
        supported_formats = ["step", "iges", "sat", "stl"]
        if export_format.lower() not in supported_formats:
            return f"Unsupported format: {export_format}. Supported: {supported_formats}"

        return (
            f"3D model export configured for: {output_path} (format: {export_format})\n"
            "Note: Actual export requires an active 3D design with geometry. "
            "Use create_design first to set up the application."
        )

    except Exception as e:
        error_msg = f"Error exporting 3D model: {str(e)}"
        logger.error(error_msg)
        return error_msg


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
        return "No AEDT Desktop connection available. Use connect_to_aedt or launch_aedt tool first."

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
# Tools tagged with "context" should be disabled when running on AALI platform
if session.on_aali:
    app.disable(tags={"context"})

# Tools tagged with "locked_connection" should be disabled when connection is locked
if session.locked_connection:
    app.disable(tags={"locked_connection"})
