"""Helper functions for PyAEDT MCP server.

This module provides utility functions for working with AEDT Desktop
instances and extracting information from them.
"""

import os
import socket
from pathlib import Path
from typing import Any

from ansys.common.mcp import get_logger

logger = get_logger(__name__)


def _is_docker() -> bool:
    """Detect whether the current process is running inside a Docker container."""
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def _probe_grpc_endpoint(host: str, port: int, timeout: float = 2.0) -> dict[str, Any]:
    """Test whether a gRPC endpoint is reachable via a TCP connect probe.

    Parameters
    ----------
    host : str
        Hostname or IP address to probe.
    port : int
        TCP port number.
    timeout : float, optional
        Connection timeout in seconds.  Default is ``2.0``.

    Returns
    -------
    dict[str, Any]
        ``{"reachable": bool, "host": str, "port": int, "error": str | None}``
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"reachable": True, "host": host, "port": port, "error": None}
    except Exception as e:
        return {"reachable": False, "host": host, "port": port, "error": str(e)}


def _resolve_aedt_executable(
    version: str | None = None,
) -> tuple[str, Path]:
    """Resolve AEDT version and locate the executable.

    Parameters
    ----------
    version : str | None
        Requested version (e.g. ``"2025.2"``, ``"252"``).  ``None`` picks
        the latest installed version.

    Returns
    -------
    tuple[str, Path]
        ``(target_version_key, path_to_ansysedt_exe)``

    Raises
    ------
    RuntimeError
        If no AEDT installation is found or the requested version is
        unavailable.
    """
    from ansys.aedt.core.desktop import Desktop

    temp = Desktop.__new__(Desktop)
    available = getattr(temp, "installed_versions", {})
    if not available:
        raise RuntimeError("No AEDT versions found installed on this system.")

    # Filter AWP root entries (not valid version IDs)
    versions = {k: v for k, v in available.items() if not k.endswith("AWP")}
    if not versions:
        versions = available

    # Resolve requested version
    if version:
        target = version
        install_dir = versions.get(target)
        if install_dir is None:
            for v, path in versions.items():
                if version in v or v in version:
                    target, install_dir = v, path
                    break
        if install_dir is None:
            raise RuntimeError(
                f"AEDT version '{version}' not found. Available: {list(versions.keys())}"
            )
    else:
        target = list(versions.keys())[-1]
        install_dir = versions[target]

    # Locate executable
    exe_name = "ansysedt.exe" if os.name == "nt" else "ansysedt"
    for candidate in [
        Path(install_dir) / exe_name,
        Path(install_dir) / "AnsysEM" / exe_name,
    ]:
        if candidate.exists():
            return target, candidate

    raise RuntimeError(f"AEDT executable not found under: {install_dir}")


def get_aedt_info(desktop: Any) -> dict[str, Any]:
    """Get comprehensive information from an AEDT Desktop instance.

    Parameters
    ----------
    desktop : Any
        The AEDT Desktop instance.

    Returns
    -------
    dict[str, Any]
        Dictionary containing AEDT information including:
        - connection: Connection details (version, machine, port, grpc mode)
        - projects: List of open projects
        - active_project: Currently active project
        - installed_versions: Available AEDT versions
    """
    info: dict[str, Any] = {
        "connection": {},
        "projects": [],
        "active_project": None,
        "active_design": None,
        "installed_versions": [],
    }

    try:
        # Connection information
        info["connection"] = {
            "version": str(desktop.aedt_version_id) if hasattr(desktop, "aedt_version_id") else "Unknown",
            "version_string": str(desktop.aedt_version_string) if hasattr(desktop, "aedt_version_string") else "Unknown",
            "install_dir": str(desktop.aedt_install_dir) if hasattr(desktop, "aedt_install_dir") else "Unknown",
            "is_grpc": desktop.is_grpc_api if hasattr(desktop, "is_grpc_api") else False,
            "machine": str(desktop.machine) if hasattr(desktop, "machine") else "localhost",
            "port": desktop.port if hasattr(desktop, "port") else None,
            "non_graphical": desktop.non_graphical if hasattr(desktop, "non_graphical") else True,
            "process_id": desktop.aedt_process_id if hasattr(desktop, "aedt_process_id") else None,
        }
    except Exception as e:
        info["connection"]["error"] = str(e)

    try:
        # Project list
        info["projects"] = desktop.project_list if hasattr(desktop, "project_list") else []
    except Exception as e:
        info["projects_error"] = str(e)

    try:
        # Active project
        active_proj = desktop.active_project() if hasattr(desktop, "active_project") and callable(desktop.active_project) else None
        if active_proj:
            info["active_project"] = active_proj.GetName() if hasattr(active_proj, "GetName") else str(active_proj)
    except Exception:
        info["active_project"] = None

    try:
        # Active design
        active_design = desktop.active_design() if hasattr(desktop, "active_design") and callable(desktop.active_design) else None
        if active_design:
            info["active_design"] = active_design.GetName() if hasattr(active_design, "GetName") else str(active_design)
    except Exception:
        info["active_design"] = None

    try:
        # Installed versions
        if hasattr(desktop, "installed_versions"):
            info["installed_versions"] = list(desktop.installed_versions.keys())
    except Exception as e:
        info["installed_versions_error"] = str(e)

    return info


def get_design_info(app: Any) -> dict[str, Any]:
    """Get information about an AEDT application/design.

    Parameters
    ----------
    app : Any
        An AEDT application instance (Hfss, Maxwell3d, Icepak, etc.)

    Returns
    -------
    dict[str, Any]
        Dictionary containing design information.
    """
    info: dict[str, Any] = {}

    try:
        info["design_name"] = app.design_name if hasattr(app, "design_name") else "Unknown"
        info["project_name"] = app.project_name if hasattr(app, "project_name") else "Unknown"
        info["design_type"] = app.design_type if hasattr(app, "design_type") else "Unknown"
        info["solution_type"] = app.solution_type if hasattr(app, "solution_type") else "Unknown"
        info["working_directory"] = app.working_directory if hasattr(app, "working_directory") else "Unknown"
        info["project_path"] = app.project_path if hasattr(app, "project_path") else "Unknown"
    except Exception as e:
        info["error"] = str(e)

    try:
        # Setup information
        if hasattr(app, "setups"):
            info["setups"] = [s.name if hasattr(s, "name") else str(s) for s in app.setups]
        else:
            info["setups"] = []
    except Exception:
        info["setups"] = []

    try:
        # Boundary information
        if hasattr(app, "boundaries"):
            info["boundaries"] = [b.name if hasattr(b, "name") else str(b) for b in app.boundaries]
        else:
            info["boundaries"] = []
    except Exception:
        info["boundaries"] = []

    try:
        # Variable information
        if hasattr(app, "variable_manager") and hasattr(app.variable_manager, "design_variables"):
            info["design_variables"] = list(app.variable_manager.design_variables.keys())
        else:
            info["design_variables"] = []
    except Exception:
        info["design_variables"] = []

    return info


def parse_aedt_version(version_str: str | None) -> str | None:
    """Parse and normalize AEDT version string.

    Parameters
    ----------
    version_str : str | None
        Version string in various formats (e.g., "2025.2", "252", "25.2")

    Returns
    -------
    str | None
        Normalized version string or None if invalid.
    """
    if version_str is None:
        return None

    version_str = str(version_str).strip()

    # Already in correct format
    if len(version_str) == 3 and version_str.isdigit():
        return version_str

    # Format: "2025.2" -> "252"
    if "." in version_str:
        parts = version_str.split(".")
        if len(parts) == 2:
            try:
                year = int(parts[0])
                release = int(parts[1])
                if year >= 2000:
                    return f"{year % 100}{release}"
            except ValueError:
                pass

    # Format: "25.2" -> "252"
    if "." in version_str:
        try:
            parts = version_str.split(".")
            if len(parts) == 2:
                return f"{parts[0]}{parts[1]}"
        except (ValueError, IndexError):
            pass

    return version_str
