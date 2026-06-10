.. _ref_docker:

Docker deployment
=================

PyAEDT-MCP can run as a containerized service with HTTP transport. Because AEDT
does not have a publicly available Docker image, the MCP container connects to
an AEDT instance running on the host machine or on a remote server.

.. warning::
   HTTP transport is not encrypted. Use only on trusted networks or behind a
   reverse proxy (such as Nginx or HAProxy) that provides TLS/SSL.

Quick start with Docker Compose
--------------------------------

The easiest path is Docker Compose.

1. Start AEDT on the host machine first:

   .. code-block:: bash

      # Windows
      "C:\Program Files\ANSYS Inc\v261\AnsysEM\ansysedt.exe" -grpcsrv 50051

2. Build and start the MCP container:

   .. code-block:: bash

      docker compose -f docker/docker-compose.yml up -d --build

   The MCP server is available at ``http://localhost:8080``.

3. Check the logs:

   .. code-block:: bash

      docker compose -f docker/docker-compose.yml logs -f pyaedt-mcp

4. Stop the server:

   .. code-block:: bash

      docker compose -f docker/docker-compose.yml down

Docker Compose environment variables
-------------------------------------

Configure the container by setting environment variables before running
``docker compose``:

.. list-table::
   :header-rows: 1
   :widths: 25 25 50

   * - Variable
     - Default
     - Description
   * - ``AEDT_MACHINE``
     - ``host.docker.internal``
     - Hostname or IP of the machine running AEDT.
   * - ``AEDT_PORT``
     - ``50051``
     - gRPC port that AEDT is listening on.
   * - ``AEDT_VERSION``
     - ``2026.1``
     - AEDT version to pass to PyAEDT.
   * - ``AEDT_NON_GRAPHICAL``
     - ``true``
     - Run AEDT in non-graphical mode.
   * - ``CONNECT_ON_STARTUP``
     - ``true``
     - Attempt to attach to AEDT when the container starts.

Example: connect to a remote AEDT instance:

.. code-block:: bash

   AEDT_MACHINE=192.168.1.100 AEDT_PORT=50051 \
     docker compose -f docker/docker-compose.yml up -d --build

Build a standalone image
------------------------

From the repository root:

**Linux / macOS**:

.. code-block:: bash

   docker build -f docker/Dockerfile -t pyaedt-mcp .

**Windows (PowerShell)**:

.. code-block:: powershell

   docker build -f docker\Dockerfile -t pyaedt-mcp .

Run the standalone container
-----------------------------

Connect to a local AEDT instance (Windows / macOS):

.. code-block:: bash

   docker run -p 8080:8080 \
     -e AEDT_MACHINE=host.docker.internal \
     pyaedt-mcp

Connect to a local AEDT instance (Linux):

.. code-block:: bash

   docker run --network host \
     -e AEDT_MACHINE=localhost \
     pyaedt-mcp

Connect to a remote AEDT instance:

.. code-block:: bash

   docker run -p 8080:8080 \
     -e AEDT_MACHINE=192.168.1.100 \
     -e AEDT_PORT=50051 \
     pyaedt-mcp

MCP client configuration
-------------------------

Once the container is running, point your MCP client to the HTTP server.

**Visual Studio Code** (``.vscode/mcp.json``):

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

Limitations
-----------

- AEDT does not have a public Docker image. The MCP container only wraps the
  server process; AEDT itself must run on a host with a valid Ansys license.
- Non-graphical mode is required when connecting from a container because there
  is no display server inside the MCP container.
- Graphical screenshots captured by ``screenshot`` work through AEDT's
  off-screen rendering capability.
