.. _ref_lanes:

Lanes
=====

By default, each MCP client starts its own PyAEDT-MCP server, which owns at
most one AEDT session. *Lanes mode* lets several MCP clients (for example
VS Code, Claude, and a terminal agent) **share** AEDT sessions, or run
**isolated** AEDT sessions side by side, from one machine.

Lanes mode is opt-in. It is enabled only by the ``--lanes`` argument. Without it,
PyAEDT-MCP behaves exactly as described in the rest of this guide.

How it works
------------

* A *lane* is a long-lived PyAEDT-MCP backend served over HTTP on
  ``127.0.0.1``. It owns at most one AEDT session.
* ``ansys-aedt-mcp --lanes`` starts a small stdio *routing proxy* in each MCP
  client. It exposes every regular PyAEDT-MCP tool plus lane management tools,
  and forwards each AEDT tool call to the lane the client has selected.
* Lanes are recorded in a per-user registry, so every client on the machine
  sees the same lanes. Lanes survive client restarts.
* No lane is spawned or selected at startup. The assistant calls
  ``list_lanes`` and then ``switch_lane`` or ``spawn_lane`` before using AEDT.

Security
~~~~~~~~

* Each lane is protected by a random bearer token, generated at spawn time and
  stored in the per-user registry. Requests without the token are rejected
  with HTTP 401.
* The token is removed from the backend environment before AEDT starts, so
  child processes never inherit it, and it is never returned by tools or the
  ``status`` command.
* Lanes bind to ``127.0.0.1`` by default.

Configure your MCP client
-------------------------

Add ``--lanes`` to the arguments of the regular stdio configuration. For
example, in VS Code (``.vscode/mcp.json``):

.. code-block:: json

   {
     "servers": {
       "pyaedt-lanes": {
         "type": "stdio",
         "command": "uvx",
         "args": [
           "--index-strategy", "unsafe-best-match",
           "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
           "ansys-aedt-mcp", "--lanes"
         ]
       }
     }
   }

Arguments after ``--`` are forwarded to every lane backend, for example
``["--lanes", "--", "--graphical", "--include-context"]``.

Proxy options
~~~~~~~~~~~~~

``--http-host HOST``
    Host that lane backends bind to. The default is ``127.0.0.1``.

``--startup-timeout SECONDS``
    Seconds a new lane gets to open its port. The default is ``60``.

``--probe-timeout SECONDS``
    Seconds a lane gets to answer a status probe before it is reported as
    unresponsive.

``--handshake-timeout SECONDS``
    Seconds a lane gets to answer the MCP handshake. A busy lane is reported
    as busy, and the call is *not* sent.

``--aedt-version {latest,pyaedt,VERSION}``
    Default AEDT version used by lane backends: the newest installed version
    (``latest``, the default), the PyAEDT default (``pyaedt``), or a version
    such as ``2026.1``. Also read from ``ANSYS_AEDT_MCP_LANE_AEDT_VERSION``.

``--dynamic-tool-discovery`` cannot be forwarded to lanes. The proxy opens an
MCP session for each call, so AEDT-only tools would never be advertised.
``--transport``, ``--http-host``, and ``--http-port`` are set by the proxy for
each lane and cannot be forwarded either.

Lane management tools
---------------------

These tools belong to the ``lanes`` toolset in ``toolsets://definition``.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Tool
     - Purpose
   * - ``list_lanes``
     - List registered lanes with their health and AEDT session.
   * - ``current_lane``
     - Show the selected lane and any call in flight.
   * - ``spawn_lane``
     - Create a new lane and, by default, select it. It fails if the
       name is already registered. It does not launch AEDT. Call ``launch_aedt``
       or ``connect_to_aedt`` next.
   * - ``switch_lane``
     - Select the lane that subsequent AEDT tool calls go to.
   * - ``stop_lane``
     - Shut down a lane backend.
   * - ``check_lane``
     - Diagnose a lane: listening, authentication, responsiveness, and AEDT state.
   * - ``recycle_lane``
     - Restart a lane backend and reattach it to the same AEDT session
       without closing AEDT.
   * - ``refresh_aedt_port``
     - Re-read the AEDT gRPC port that a lane is attached to.
   * - ``reap_lanes``
     - Drop registry entries whose backend is no longer running.
   * - ``reset_lanes``
     - Clear the registry and optionally stop the lane processes.
   * - ``unlock_registry_files``
     - Delete a stale registry lock file.

A typical session looks like this:

.. code-block:: text

   list_lanes()                  # reuse an existing lane with switch_lane("<name>")
   spawn_lane("patch-antenna")   # or create a lane and route to it
   launch_aedt(...)              # runs inside the patch-antenna lane
   ...                           # any AEDT tool, as usual
   stop_lane("patch-antenna")    # when the work is finished

Name lanes after the work, like git branches (``patch-antenna``,
``filter-tuning``), rather than ``default`` or a port number.

Recovery commands
-----------------

These commands work even when no MCP client is running:

.. code-block:: bash

   ansys-aedt-mcp --lanes status [--json]          # registered lanes and their health
   ansys-aedt-mcp --lanes reap                     # drop dead lanes
   ansys-aedt-mcp --lanes reset [--kill] [--unlock] [--yes]
   ansys-aedt-mcp --lanes unlock                   # delete a stale lock file
   ansys-aedt-mcp --lanes dashboard [--port 8765] [--refresh 30] [--no-browser]

The dashboard is a read-only local web page served on ``127.0.0.1``. It shows
whether each lane is up, busy, or degraded, together with its AEDT port and
recent log activity. It never opens an MCP session, so it cannot block a busy
lane.

State and logs
--------------

The registry, its lock file, and one ``lane-<port>.log`` per lane are stored in
the per-user state directory:

* Windows: ``%LOCALAPPDATA%\ansys-aedt-mcp``
* Linux: ``$XDG_STATE_HOME/ansys-aedt-mcp``, or ``~/.local/state/ansys-aedt-mcp``
