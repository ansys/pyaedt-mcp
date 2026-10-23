.. _ref_docker:

Docker deployment
=================

You can run PyAEDT-MCP as a containerized service with HTTP transport.
Because AEDT does not have a publicly available Docker image, the MCP
container connects to an AEDT instance running on your host machine or on a
remote server.

.. warning::
   The HTTP transport has **no authentication or encryption**. Any client that can
   reach the port can call every tool with no credential, including
   ``run_python_code`` (arbitrary Python execution against the connected AEDT
   session) and tools that read or write attacker-chosen local paths, such as
   ``open_project``, ``save_project``, and ``export_results``. Never publish this
   port on a network you do not fully trust, or on the public internet. Only
   expose it beyond ``localhost`` if it is placed behind a reverse proxy (such as
   Nginx or HAProxy) that provides both TLS/SSL **and** its own authentication
   (for example mutual TLS or an authenticating gateway). The Docker Compose file
   included in this repository publishes the port on ``127.0.0.1`` only, so it is
   not reachable from other machines by default.

Quick start with Docker Compose
--------------------------------

Use Docker Compose for the fastest setup.

#. Start AEDT on the host machine first:

   .. code-block:: bash

      # Windows
      "C:\Program Files\ANSYS Inc\v261\AnsysEM\ansysedt.exe" -grpcsrv 50051

   Or open AEDT from the desktop icon.

#. Build and start the MCP container:

   .. code-block:: bash

      docker compose -f docker/docker-compose.yml up -d --build

   The MCP server is available at ``http://localhost:8080``.

#. Check the logs:

   .. code-block:: bash

      docker compose -f docker/docker-compose.yml logs -f pyaedt-mcp

#. Stop the server:

   .. code-block:: bash

      docker compose -f docker/docker-compose.yml down

MCP client configuration
------------------------

After the container starts, point your MCP client to the HTTP server.

**Visual Studio Code**

Edit the ``.vscode/mcp.json`` file:

.. code-block:: json

   {
     "servers": {
       "pyaedt-mcp": {
         "type": "http",
         "url": "http://localhost:8080"
       }
     }
   }

**Claude Desktop**:

.. code-block:: json

   {
     "mcpServers": {
       "pyaedt-mcp": {
         "url": "http://localhost:8080",
         "transport": "http"
       }
     }
   }

Environment variables
---------------------

.. list-table::
   :header-rows: 1

   * - Variable
     - Default
     - Description
   * - ``AEDT_MACHINE``
     - ``host.docker.internal``
     - AEDT server hostname
   * - ``AEDT_PORT``
     - ``50051``
     - AEDT gRPC port
   * - ``AEDT_VERSION``
     - ``2026.1``
     - AEDT version
   * - ``CONNECT_ON_STARTUP``
     - ``true``
     - Connect to AEDT as soon as the container starts, using ``AEDT_MACHINE``
       and ``AEDT_PORT``. Combined with an unauthenticated, network-reachable
       HTTP port, this means any reachable client can immediately drive the
       connected AEDT session. Set to ``false`` to require an explicit
       ``connect_to_aedt`` tool call first.
   * - ``HTTP_HOST``
     - ``0.0.0.0``
     - Bind address *inside* the container. Leave this as ``0.0.0.0`` for
       Docker's port publishing to work; actual network exposure is controlled
       by the ``ports`` mapping in ``docker-compose.yml``, which defaults to
       publishing on ``127.0.0.1`` only.
   * - ``HTTP_PORT``
     - ``8080``
     - HTTP server port, both inside the container and for the published
       ``ports`` mapping.
