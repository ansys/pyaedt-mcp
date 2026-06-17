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

    Or open AEDT from the desktop icon.

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
