.. _ref_installation:

Installation
============

``ansys-aedt-mcp`` can run in two common modes:

- Start the MCP server and let it launch AEDT later through tools.
- Start or reuse an AEDT gRPC session first, then have the server connect to it.

Requirements
------------

- Python 3.10 or later
- AEDT 2022 R2 or later for gRPC workflows
- A local AEDT installation or a reachable remote AEDT endpoint

Install with ``uvx``
--------------------

Use ``uvx`` when you want to run the server without cloning the repository.

.. code-block:: bash

   uvx --from git+https://github.com/ansys/pyaedt-mcp.git ansys-aedt-mcp

Install with ``pip``
--------------------

Use ``pip`` when you want the package available in your current Python
environment.

.. code-block:: bash

   pip install git+https://github.com/ansys/pyaedt-mcp.git

Install from source
-------------------

Use this option when you have cloned the repository and want a local
installation.

.. code-block:: bash

   git clone https://github.com/ansys/pyaedt-mcp
   cd pyaedt-mcp
   pip install .

If you plan to contribute (editable install, development dependencies, tests,
and linters), follow the development setup in :doc:`contribution`.

Start AEDT in gRPC mode
-----------------------

If you want to attach to an existing AEDT session, start AEDT in GRPC mode. You can do it from the command line or from the AEDT GUI. By default PyAEDT supports grpc in AEDT 2022 R2 and later.

.. code-block:: bash

   "C:\Program Files\ANSYS Inc\v261\AnsysEM\ansysedt.exe" -grpcsrv 50051

Start the MCP server
--------------------

The default transport is ``stdio``.

.. code-block:: bash

   ansys-aedt-mcp

Common options:

.. code-block:: bash

   ansys-aedt-mcp --connect --machine localhost --port 50051
   ansys-aedt-mcp --transport http --http-host 127.0.0.1 --http-port 8080
   ansys-aedt-mcp --include-context
   ansys-aedt-mcp --dynamic-tool-discovery

After the server starts, you can connect to it with any MCP-compatible client, such as Claude Code, Copilot CLI, Codex, Cursor etc. See :doc:`ide_configuration` for more details.

Important CLI options
---------------------

.. list-table::
   :header-rows: 1

   * - Option
     - Purpose
   * - ``--transport {stdio,http}``
     - Choose how the MCP server is exposed to the client.
   * - ``--machine`` / ``--port``
     - Point startup connection logic to an AEDT gRPC endpoint.
   * - ``--connect``
     - Attach to AEDT during server startup instead of waiting for a tool call.
   * - ``--include-context``
     - Register optional guidance tools for AEDT and PyAEDT workflows.
   * - ``--dynamic-tool-discovery``
     - Hide AEDT-only tools until ``launch_aedt`` or ``connect_to_aedt`` succeeds.
   * - ``--http-host`` / ``--http-port``
     - Configure the HTTP transport endpoint.

Typical first workflow
----------------------

Once the client is connected to the MCP server, the normal flow is:

1. Call ``check_aedt_installed``.
2. Call ``check_aedt_status``.
3. Use ``launch_aedt`` or ``connect_to_aedt``.
4. Open a project or create a design.
5. Use dedicated tools or ``run_python_code`` for the rest of the workflow.

.. note::

  If an operation is not supported by the tool surface, the AI Agent will
  generate a Python snippet and call ``run_python_code`` to execute it in the
  persistent PyAEDT session.

For recommended usage patterns, see :doc:`../user_guide/best_practices`. To
review the available tool surface, see :doc:`../user_guide/tools_and_capabilities`.
