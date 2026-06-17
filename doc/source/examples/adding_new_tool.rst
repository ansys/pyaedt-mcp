.. _ref_adding_new_tool:

Adding a new tool
=================

This guide explains how to add a new ``@app.tool(...)`` safely and make it
visible in the right stages of an MCP session.

Where to implement
------------------

1. Add the tool implementation to ``src/ansys/aedt/mcp/tools.py``.
2. Add the tool to an appropriate group in
   ``src/ansys/aedt/mcp/toolsets.py``.
3. Document behavior in :doc:`../user_guide/tools_and_capabilities`.

Decorator options and tags
--------------------------

PyAEDT-MCP uses FastMCP's ``@app.tool(...)`` decorator with key options:

- ``tags``: Set of tags used for grouping and runtime filtering.
- ``timeout``: Maximum execution time guard for the tool.

Common tags used in this repository:

- ``REQUIRES_AEDT_TAG``:
  Mark tools that require an active AEDT Desktop connection.
- ``aedt_tools``:
  General category tag used for core AEDT-facing tools.
- ``locked_connection``:
  Used for tools that are disabled when startup uses ``--connect`` and the
  connection is locked for the server lifetime.

Timeout tiers used in this repository:

- Quick: 30 s
- Medium: 120 s
- Long: 600 s

Example: AEDT-dependent tool
----------------------------

Use ``REQUIRES_AEDT_TAG`` when the tool cannot run before connection:

.. code-block:: python

   from fastmcp.server import Context
   from ansys.aedt.mcp import app
   from ansys.aedt.mcp.tools import REQUIRES_AEDT_TAG

   @app.tool(tags={"aedt_tools", REQUIRES_AEDT_TAG}, timeout=120)
   def my_new_tool(ctx: Context) -> str:
       return "ok"

Example: Pre-connection tool
---------------------------

Do not use ``REQUIRES_AEDT_TAG`` for tools that work before connecting:

.. code-block:: python

   from fastmcp.server import Context
   from ansys.aedt.mcp import app

   @app.tool(tags={"aedt_tools"}, timeout=30)
   def check_local_environment(ctx: Context) -> str:
       return "environment ready"

Runtime flags and their effect
------------------------------

Server startup flags affect tool visibility and behavior:

- ``--dynamic-tool-discovery``:
  Hides ``REQUIRES_AEDT_TAG`` tools until AEDT is connected.
- ``--connect``:
  Connects at startup and locks the session. In this mode,
  ``launch_aedt``, ``connect_to_aedt``, and ``disconnect_from_aedt`` are
  disabled for the process lifetime.
- ``--include-context``:
  Registers optional context tools such as ``get_guidelines_for``.

Validation checklist
--------------------

1. Add or update tests in ``tests/test_tools.py``.
2. Ensure the tool appears in a toolset definition
   (validated by ``tests/test_toolsets.py``).
3. Run tests locally.
4. Verify code coverage remains greater than 80%.
5. Update user-facing docs.
