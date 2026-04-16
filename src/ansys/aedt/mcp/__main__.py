"""Entry point for PyAEDT MCP server when run as a module.

Usage:
    python -m ansys.aedt.mcp [options]

Options:
    --transport {stdio,http}  Transport type (default: stdio)
    --machine MACHINE         AEDT machine hostname (default: localhost)
    --port PORT              AEDT gRPC port (default: 50051)
    --version VERSION        AEDT version to use
    --non-graphical          Run AEDT in non-graphical mode (default)
    --graphical              Run AEDT in graphical mode
    --connect                Connect to AEDT on startup
    --http-host HOST         HTTP transport host (default: 127.0.0.1)
    --http-port PORT         HTTP transport port (default: 8080)
    --cors-origins ORIGINS   Allowed CORS origins for HTTP transport
"""

from ansys.aedt.mcp.server import launcher

if __name__ == "__main__":
    launcher()
