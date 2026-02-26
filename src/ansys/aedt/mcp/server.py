"""Lifespan and CLI entry for the PyAEDT MCP server with startup options."""

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Optional

from ansys.common.mcp import (
    PyAnsysBaseMCP,
    get_logger,
)
from ansys.common.mcp.context import PyAnsysBaseAppContext
from ansys.common.mcp.helpers import PersistentPythonSession

logger = get_logger(__name__)


@dataclass
class PyAEDTAppContext(PyAnsysBaseAppContext):
    """Application context with typed dependencies and CLI options.

    Attributes
    ----------
    desktop : Optional[Any]
        AEDT Desktop instance connection. Using Any to avoid type issues.
    transport_type : str
        Transport type for MCP server ('stdio' or 'http').
    aedt_machine : Optional[str]
        Machine name or IP for AEDT connection.
    aedt_port : Optional[int]
        Port number for AEDT gRPC connection.
    aedt_version : Optional[str]
        Version of AEDT to use.
    non_graphical : bool
        Whether to run AEDT in non-graphical mode.
    connect_on_startup : bool
        Whether to attempt AEDT connection on MCP startup.
    http_host : str
        Host address for HTTP transport.
    http_port : int
        Port number for HTTP transport.
    cors_origins : Optional[list[str]]
        List of allowed CORS origins for HTTP transport.
    """

    desktop: Any | None = None  # Using Any to avoid type issues with AEDT variants
    transport_type: str = "stdio"
    aedt_machine: str | None = None
    aedt_port: int | None = None
    aedt_version: str | None = None
    non_graphical: bool = True
    connect_on_startup: bool = False
    http_host: str = "127.0.0.1"
    http_port: int = 8080
    cors_origins: list[str] | None = None

    @property
    def product_instance(self) -> Optional[Any]:
        """Returns the default AEDT Desktop instance for backward compatibility.

        Returns
        -------
        Optional[Any]
            The default AEDT Desktop instance, or None if not connected.
        """
        return self.desktop

    @product_instance.setter
    def product_instance(self, value: Any) -> None:
        """Setter for product_instance."""
        self.desktop = value


class PyAEDTMCP(PyAnsysBaseMCP):
    """FastMCP server for managing AEDT Desktop instances."""

    def __init__(self, name: str = "PyAEDT MCP Server", *args, **kwargs):
        super().__init__(name=name, *args, **kwargs)

    def create_context(self) -> PyAEDTAppContext:
        """
        Create a new application context.

        Returns
        -------
        PyAEDTAppContext
            The application context for managing AEDT instances.
        """
        startup_code = "from ansys.aedt.mcp.aedt_helper.startup_code import *"
        python_session = PersistentPythonSession(
            python_executable=self.python_executable,
            working_directory=self.working_directory,
            startup_code=startup_code,
        )

        context = PyAEDTAppContext(
            python_session=python_session,
            command_history=[],
        )

        # Populate context from CLI config if available
        cli_cfg = getattr(self, "_cli_config", None)

        if cli_cfg is not None:
            context.transport_type = cli_cfg.get("transport_type", context.transport_type)
            context.aedt_machine = cli_cfg.get("aedt_machine", context.aedt_machine)
            context.aedt_port = cli_cfg.get("aedt_port", context.aedt_port)
            context.aedt_version = cli_cfg.get("aedt_version", context.aedt_version)
            context.non_graphical = cli_cfg.get("non_graphical", context.non_graphical)
            context.connect_on_startup = cli_cfg.get(
                "connect_on_startup", context.connect_on_startup
            )
            context.http_host = cli_cfg.get("http_host", context.http_host)
            context.http_port = cli_cfg.get("http_port", context.http_port)
            context.cors_origins = cli_cfg.get("cors_origins", context.cors_origins)

        self.context = context
        return context

    def product_startup(self):
        """Allow PyAEDT-MCP specific startup actions."""
        logger.info("PyAEDT MCP server starting up...")

        context = self.context

        if context.connect_on_startup:
            try:
                from ansys.aedt.core import Desktop
                from ansys.aedt.core.generic.settings import settings

                # Enable gRPC API
                settings.use_grpc_api = True

                logger.info(
                    f"Attempting to connect to AEDT at {context.aedt_machine}:{context.aedt_port}..."
                )

                # Connect to running AEDT instance
                context.desktop = Desktop(
                    version=context.aedt_version,
                    non_graphical=context.non_graphical,
                    new_desktop=False,
                    machine=context.aedt_machine,
                    port=context.aedt_port,
                )
                logger.info("Successfully connected to AEDT on startup.")

            except Exception as e:
                logger.error(f"Failed to connect to AEDT on startup: {e}")
        else:
            logger.info("MCP Server initialized. Use connect_to_aedt to establish a connection.")

    def product_cleanup(self):
        """Perform cleanup actions for AEDT instances on shutdown."""
        context = self.context
        # Cleanup on shutdown
        if context.desktop is not None:
            try:
                logger.info("Disconnecting from AEDT...")
                context.desktop.release_desktop(close_projects=False)
                logger.info("AEDT disconnect complete")
            except Exception as e:
                logger.error(f"Error during AEDT disconnect: {e}")


# Pass lifespan to server
app = PyAEDTMCP(name="PyAEDT MCP Server")


@dataclass
class SessionContext:
    """Session context for storing CLI options."""

    connect_on_startup: bool = False
    on_aali: bool = False

    @property
    def locked_connection(self) -> bool:
        """Whether to lock the connection on startup."""
        return self.connect_on_startup


session = SessionContext()


def _validate_port(port: int) -> int:
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("Port must be in range 1-65535")
    return port


def launcher(argv: list[str] | None = None) -> None:
    """Entry point for the MCP server.

    Parameters
    ----------
    argv : list[str] | None
        Optional list of arguments for testing. Defaults to `sys.argv[1:]`.
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="ansys.aedt.mcp")
    parser.add_argument(
        "--transport",
        dest="transport_type",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport type. Allowed: stdio, http",
    )
    parser.add_argument(
        "--machine",
        dest="aedt_machine",
        default="localhost",
        help="AEDT machine hostname or IP (default: localhost)",
    )
    parser.add_argument(
        "--port",
        dest="aedt_port",
        type=lambda v: _validate_port(int(v)),
        default=50051,
        help="AEDT gRPC port (default: 50051)",
    )
    parser.add_argument(
        "--version",
        dest="aedt_version",
        default=None,
        help="AEDT version to use (e.g., '2025.2' or '252')",
    )
    parser.add_argument(
        "--non-graphical",
        dest="non_graphical",
        action="store_true",
        default=True,
        help="Run AEDT in non-graphical mode (default: True)",
    )
    parser.add_argument(
        "--graphical",
        dest="non_graphical",
        action="store_false",
        help="Run AEDT in graphical mode",
    )
    parser.add_argument(
        "--connect",
        dest="connect_on_startup",
        action="store_true",
        help="Attempt to connect to AEDT on startup",
    )
    parser.add_argument(
        "--http-host",
        dest="http_host",
        default="127.0.0.1",
        help="HTTP transport host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--http-port",
        dest="http_port",
        type=lambda v: _validate_port(int(v)),
        default=8080,
        help="HTTP transport port (default: 8080)",
    )
    parser.add_argument(
        "--cors-origins",
        dest="cors_origins",
        nargs="+",
        default=None,
        help="Allowed CORS origins for HTTP transport",
    )
    parser.add_argument(
        "--on-aali",
        dest="on_aali",
        action="store_true",
        default=False,
        help="Indicates running on AALI platform (disables certain tools)",
    )

    args = parser.parse_args(argv)

    # Parse CORS origins if provided
    cors_origins = None
    if args.cors_origins:
        cors_origins = args.cors_origins

    # Attach CLI config to server so lifespan can read it
    session.connect_on_startup = bool(args.connect_on_startup)
    session.on_aali = bool(args.on_aali)

    if session.connect_on_startup:
        logger.info(
            f"MCP will attempt to connect to AEDT at "
            f"{args.aedt_machine}:{args.aedt_port} on startup. "
            "The tools 'launch_aedt', 'connect_to_aedt' and "
            "'disconnect_from_aedt' will be disabled."
        )

    setattr(
        app,
        "_cli_config",
        {
            "transport_type": args.transport_type,
            "aedt_machine": args.aedt_machine,
            "aedt_port": args.aedt_port,
            "aedt_version": args.aedt_version,
            "non_graphical": args.non_graphical,
            "connect_on_startup": session.connect_on_startup,
            "http_host": args.http_host,
            "http_port": args.http_port,
            "cors_origins": cors_origins,
            "on_aali": session.on_aali,
        },
    )

    # Run server using selected transport
    import asyncio

    # Import tools, contexts, and prompts to register them with the app
    if not session.on_aali:
        from ansys.aedt.mcp import contexts  # noqa: F401
    from ansys.aedt.mcp import prompts  # noqa: F401
    from ansys.aedt.mcp import tools  # noqa: F401

    # Guarantee the system prompt is delivered during the MCP initialize handshake
    app.instructions = prompts.SYSTEM_PROMPT

    if args.transport_type == "stdio":
        asyncio.run(app.run_stdio_async())
    elif args.transport_type == "http":
        asyncio.run(
            app.run_http_async(
                transport="http",  # Use streamable HTTP (default)
                host=args.http_host,
                port=args.http_port,
            )
        )
