.. _ref_ide_configuration:

IDE and client configuration
=============================

PyAEDT-MCP works with any MCP-compatible client. This page covers the most
common ones: Claude Code, Visual Studio Code, and Claude Desktop.

Claude Code
-----------

Claude Code is Anthropic's AI-powered code editor with built-in MCP support.

Configure for a specific project (recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run from the project directory:

.. code-block:: bash

   cd my-project
   claude mcp add --transport stdio pyaedt-mcp -- \
     uvx --from git+https://github.com/ansys/pyaedt-mcp ansys-aedt-mcp

**Advantages**

- Scoped to the project, shareable via version control.
- Supports per-project CLI flags (for example ``--include-context``).

Configure globally
~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   claude mcp add --transport stdio --scope user pyaedt-mcp -- \
     uvx --from git+https://github.com/ansys/pyaedt-mcp ansys-aedt-mcp

**Advantages**

- Available in all Claude Code projects without per-project configuration.

See `Claude Code MCP installation
<https://code.claude.com/docs/en/mcp#installing-mcp-servers>`_ for details.

Visual Studio Code
------------------

VS Code integrates MCP servers through the Copilot extension.

Start from GitHub (recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add this to ``.vscode/mcp.json`` (create the file if it does not exist):

.. code-block:: json

   {
     "servers": {
       "pyaedt-mcp": {
         "type": "stdio",
         "command": "uvx",
         "args": [
           "--index-strategy", "unsafe-best-match",
           "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
           "ansys-aedt-mcp"
         ]
       }
     }
   }

Use local development install
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you have cloned the repository and installed it in a virtual environment:

.. code-block:: json

   {
     "servers": {
       "pyaedt-mcp": {
         "type": "stdio",
         "command": ".venv/Scripts/python",
         "args": ["-m", "ansys.aedt.mcp"],
         "env": {
           "FASTMCP_LOG_LEVEL": "DEBUG"
         }
       }
     }
   }

Use ``bin/python`` instead of ``Scripts/python`` on Linux or macOS.

Configure HTTP transport
~~~~~~~~~~~~~~~~~~~~~~~~

If you have started the server with ``--transport http``:

.. code-block:: json

   {
     "servers": {
       "pyaedt-mcp": {
         "type": "http",
         "url": "http://127.0.0.1:8080"
       }
     }
   }

Start the server before connecting:

.. code-block:: bash

   ansys-aedt-mcp --transport http --http-host 127.0.0.1 --http-port 8080

Enable MCP in Visual Studio Code
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Open VS Code settings (``Ctrl+,`` / ``Cmd+,``).
2. Search for ``MCP``.
3. Enable the setting to allow Copilot to use MCP servers.
4. Restart VS Code.

See `Visual Studio Code MCP servers
<https://code.visualstudio.com/docs/copilot/customization/mcp-servers>`_
documentation for details.

Claude Desktop
--------------

Edit ``~/Library/Application Support/Claude/claude_desktop_config.json``
(macOS) or the equivalent path on Windows:

.. code-block:: json

   {
     "mcpServers": {
       "pyaedt-mcp": {
         "command": "uvx",
         "args": [
           "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
           "ansys-aedt-mcp"
         ]
       }
     }
   }

Claude Code vs. Visual Studio Code
------------------------------------

.. list-table::
   :header-rows: 1

   * - Feature
     - Claude Code
     - Visual Studio Code
   * - Configuration method
     - CLI command (``claude mcp add``)
     - JSON file (``.vscode/mcp.json``)
   * - Setup level
     - Project or global
     - Project-level only
   * - Transport support
     - STDIO (default)
     - STDIO or HTTP
   * - Team sharing
     - Via project config files
      - Via ``.vscode/mcp.json`` in the repository
   * - Learning curve
     - Low (CLI-based)
     - Medium (JSON configuration)

Advanced configuration
----------------------

Auto-connect to AEDT on startup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pass ``--connect`` to have the server attach to AEDT during initialization.
Use ``--machine`` and ``--port`` to target a specific gRPC endpoint:

**Visual Studio Code** (``.vscode/mcp.json``):

.. code-block:: json

   {
     "servers": {
       "pyaedt-mcp": {
         "type": "stdio",
         "command": "uvx",
         "args": [
           "--index-strategy", "unsafe-best-match",
           "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
           "ansys-aedt-mcp",
           "--connect",
           "--machine", "192.168.1.100",
           "--port", "50051"
         ]
       }
     }
   }

**Claude Code**:

.. code-block:: bash

   claude mcp add --transport stdio pyaedt-mcp -- \
     uvx --from git+https://github.com/ansys/pyaedt-mcp ansys-aedt-mcp \
     --connect --machine 192.168.1.100 --port 50051

.. warning::
   When ``--connect`` is used, the server locks the connection. The
   ``launch_aedt``, ``connect_to_aedt``, and ``disconnect_from_aedt`` tools
   are disabled for the lifetime of the server process.

Enable optional context tools
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``--include-context`` flag registers ``get_guidelines_for``, which provides
inline AEDT and PyAEDT workflow guidance to the AI assistant.

.. code-block:: json

   {
     "servers": {
       "pyaedt-mcp": {
         "type": "stdio",
         "command": "uvx",
         "args": [
           "--index-strategy", "unsafe-best-match",
           "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
           "ansys-aedt-mcp",
           "--include-context"
         ]
       }
     }
   }

Enable dynamic tool discovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``--dynamic-tool-discovery`` to hide AEDT-only tools until a session is
established. This keeps the AI assistant's context small before connection.

.. code-block:: bash

   ansys-aedt-mcp --dynamic-tool-discovery

Enable debug logging
~~~~~~~~~~~~~~~~~~~~~

Set the ``FASTMCP_LOG_LEVEL`` environment variable to ``DEBUG``:

**Visual Studio Code** (``.vscode/mcp.json``):

.. code-block:: json

   {
     "servers": {
       "pyaedt-mcp": {
         "type": "stdio",
         "command": "uvx",
         "args": [
           "--index-strategy", "unsafe-best-match",
           "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
           "ansys-aedt-mcp"
         ],
         "env": {
           "FASTMCP_LOG_LEVEL": "DEBUG"
         }
       }
     }
   }

**Command line**:

.. code-block:: bash

   FASTMCP_LOG_LEVEL=DEBUG ansys-aedt-mcp

Connect with HTTP (Docker or remote)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For containerized or remote deployments, see :doc:`../user_guide/docker`.

Next steps
----------

- To understand which tools are available, see :doc:`../user_guide/tools_and_capabilities`.
- For recommended usage patterns, see :doc:`../user_guide/best_practices`.
- For containerized deployment, see :doc:`../user_guide/docker`.
