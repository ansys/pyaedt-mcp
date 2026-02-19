"""PyAEDT MCP Server - Model Context Protocol server for Ansys Electronics Desktop.

This package provides an MCP server that enables AI assistants to interact
with Ansys Electronics Desktop (AEDT) through PyAEDT.

Supported AEDT Applications:
- HFSS (High Frequency Structure Simulator)
- Maxwell 2D/3D (Low-frequency electromagnetics)
- Q3D/Q2D (Parasitic extraction)
- Icepak (Thermal management)
- Circuit (Circuit simulation)
- TwinBuilder (System modeling)
- Mechanical (Structural analysis)
- EMIT (EMI/EMC analysis)
- RMXprt (Rotating machine design)
- HFSS 3D Layout (High-speed electronics)

Example:
    Run the MCP server::

        $ ansys-aedt-mcp --transport stdio

    Or connect to a running AEDT instance::

        $ ansys-aedt-mcp --connect --machine localhost --port 50051
"""

__version__ = "0.0.1"

from ansys.aedt.mcp.server import app, launcher

__all__ = ["app", "launcher", "__version__"]
