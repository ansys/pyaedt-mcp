.. _ref_overview:

Overview
========

PyAEDT-MCP is a Model Context Protocol (MCP) server that lets an AI client work
with AEDT through PyAEDT. The repository is small and centered around one app,
one runtime context, and one main tool module.

Runtime flow
------------

The server starts in a predictable order:

1. ``ansys.aedt.mcp.__main__`` forwards to ``server.launcher``.
2. ``server.launcher`` parses CLI options, stores them on the FastMCP app, and
   imports the modules that register prompts, tools, resources, and optional
   context helpers.
3. ``PyAEDTMCP.create_context`` creates a ``PyAEDTAppContext`` with a
   persistent Python session. That session loads startup code from
   ``aedt_helper.startup_code`` so follow-up tool calls can reuse state.
4. If ``--connect`` is used, ``product_startup`` tries to attach to AEDT during
   server initialization.
5. The MCP client calls lifecycle tools first, then project, simulation,
   inspection, export, or scripting tools.

Main modules
------------

.. list-table::
   :header-rows: 1

   * - Module
     - Responsibility
   * - ``server.py``
     - Defines the app, CLI, startup logic, cleanup, transport selection, and the typed application context.
   * - ``tools.py``
     - Implements the AEDT-facing tool surface: connection, project management, scripting, analysis, inspection, and export.
   * - ``helpers.py``
     - Holds small helpers for endpoint probing, version parsing, and extracting structured AEDT model information.
   * - ``prompts.py``
     - Builds the system prompt exposed to MCP clients, including the connection workflow and tool-usage rules.
   * - ``toolsets.py``
     - Publishes the ``toolsets://definition`` discovery resource that groups tools into logical categories.
   * - ``contexts.py``
     - Registers optional guideline tools that are enabled only when the server starts with ``--include-context``.
   * - ``aedt_helper/startup_code.py``
     - Provides the startup imports and shared helpers loaded into the persistent Python session.

Tool groups
-----------

The public tool surface is intentionally small and grouped by workflow:

- **Lifecycle:** installation checks, connection status, launch, connect, disconnect, and cleanup.
- **Project management:** list projects and designs, open projects, save work, and create designs.
- **Simulation:** analyze the active design and export setup configuration.
- **Inspection and results:** inspect the model, capture screenshots, read logs, and export solver results.
- **Scripting:** run short inline PyAEDT code or a Python file against the current AEDT session.

When ``--dynamic-tool-discovery`` is enabled, tools tagged with
``REQUIRES_AEDT_TAG`` are hidden until the server has an active AEDT
connection. Without that flag, the full tool surface stays visible from startup.

Important runtime details
-------------------------

- ``run_python_code`` and ``run_python_script`` share a persistent Python
  session, so imports and variables can survive across multiple tool calls.
- The server applies timeout tiers to avoid hanging forever on slow or stuck
  AEDT calls.
- ``get_pyaedt_logs`` stays available before connection, which makes it useful
  for startup and environment debugging.
- ``toolsets.py`` is only a discovery layer. It does not control access; tool
  visibility still comes from the tags used in ``tools.py``.

Repository layout
-----------------

.. code-block:: text

   pyaedt-mcp/
   |-- src/ansys/aedt/mcp/
   |   |-- __main__.py
   |   |-- server.py
   |   |-- tools.py
   |   |-- helpers.py
   |   |-- prompts.py
   |   |-- contexts.py
   |   |-- toolsets.py
   |   `-- aedt_helper/
   |-- doc/source/
   |-- tests/
   `-- docker/

Tests
-----

The test suite follows the same split as the runtime:

- ``tests/test_cli.py`` and ``tests/test_lifespan.py`` cover startup behavior.
- ``tests/test_tools.py`` covers most tool behavior with mocks.
- ``tests/test_toolsets.py`` verifies the discovery catalogue stays aligned with
  the registered tools.
- ``tests/test_integration.py`` exercises real AEDT connectivity and therefore
  requires a running AEDT gRPC instance.
