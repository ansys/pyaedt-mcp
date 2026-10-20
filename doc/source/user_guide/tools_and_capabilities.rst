.. _ref_tools_and_capabilities:

Tools and capabilities
======================

Tool availability
-----------------

By default, you can see all tools at startup. When you pass
``--dynamic-tool-discovery``, tools that require an active AEDT connection are
hidden until PyAEDT-MCP has one.

Always available (no AEDT connection required)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Tool
     - Description
   * - ``check_aedt_installed``
     - Check whether AEDT is installed on the system.
   * - ``check_aedt_status``
     - Report current connection state. Use before every workflow to decide
       between ``launch_aedt`` and ``connect_to_aedt``.
   * - ``launch_aedt``
     - Start a new AEDT instance.
   * - ``connect_to_aedt``
     - Connect to an already-running AEDT instance via gRPC.
   * - ``get_pyaedt_logs``
     - Read the local PyAEDT log file (useful for startup and environment
       debugging).
   * - ``display_html``
     - Display self-contained HTML inline in an MCP Apps-compatible client, or
       in a detached window for other clients.

Available after connecting to AEDT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``disconnect_from_aedt`` is called (and dynamic discovery is enabled),
these tools are hidden again.

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Tool
     - Description
   * - ``disconnect_from_aedt``
     - Release the current AEDT connection.
   * - ``clear_aedt``
     - Close all open projects and release the AEDT process.
   * - ``list_projects``
     - List all currently open AEDT projects.
   * - ``list_designs``
     - List designs inside a project.
   * - ``open_project``
     - Open an AEDT or AEDTZ project file.
   * - ``save_project``
     - Save the active project to disk.
   * - ``create_design``
     - Create a new design (HFSS, Maxwell, Icepak, Circuit, and so on).
   * - ``validate_design``
     - Run design validation checks before solving.
   * - ``analyze_design``
     - Run the configured solver analysis on the active design.
   * - ``export_config``
     - Export the current setup/sweep configuration as JSON.
   * - ``export_results``
     - Export solver results (Touchstone, profile, convergence, mesh).
   * - ``run_python_code``
     - Execute inline PyAEDT Python code in the persistent session.
   * - ``run_python_script``
     - Launch a PyAEDT script asynchronously with CPython.
   * - ``get_model_info``
     - Return a structured summary of the active design.
   * - ``screenshot``
     - Capture the current 3D modeler view as an image.

Optional (enabled only with ``--include-context``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Tool
     - Description
   * - ``get_guidelines_for``
     - Return authoritative PyAEDT workflow guidelines for a specific topic
       (``workflow``, ``hfss``, ``maxwell``, ``icepak``, ``circuit``,
       ``geometry``, ``mesh``, ``boundaries``, ``postprocessing``,
       and ``parametric``).

.. note::
   When ``--connect`` is used on startup, the connection is locked and
   ``launch_aedt``, ``connect_to_aedt``, and ``disconnect_from_aedt`` are
   disabled for the lifetime of the server.

Tool usage
----------

Display custom HTML
~~~~~~~~~~~~~~~~~~~

Use ``display_html`` to render an HTML document or fragment. No AEDT
connection is required. For example:

.. code-block:: json

   {
     "html": "<h1>Results</h1><p>Simulation complete.</p>",
     "title": "Simulation Results",
     "height": 400
   }

Inline JavaScript and CSS are supported. The supplied HTML runs in a separate
sandbox: external resources, network requests, forms, popups, and access to the
MCP host are blocked. Embed images using data URLs. This tool does not run
Python or Matplotlib.

The ``display_mode`` argument controls where the HTML appears:

- ``auto`` (default): inline when the client supports MCP Apps, otherwise in a
  detached window.
- ``inline``: inline only. Clients without MCP Apps support receive a text
  fallback and the HTML in structured content.
- ``window``: always open a detached window.

The inline viewer loads the MCP Apps SDK from ``https://unpkg.com``, so that
domain must be reachable.

The detached window opens on the machine running the MCP server, using only the
Python standard library. It is a chromeless app window of an installed
Microsoft Edge or Google Chrome browser. If neither is found, the
default browser is used. To choose the browser, set the
``PYAEDT_MCP_HTML_BROWSER`` environment variable to its executable. No window
is opened when the server runs in a container or without a graphical display.
The detached window resizes itself to fit the rendered HTML, limited to the
available screen area. Pass ``width`` (200-3840) or ``height`` (200-1200), in
pixels, to fix either dimension instead. Window resizing is not available when
falling back to the default browser. Views are written to the ``pyaedt-mcp-html-views`` temporary directory and
removed after 24 hours.

Establish a connection
~~~~~~~~~~~~~~~~~~~~~~

Always start by confirming installation and connection state:

*"Check whether AEDT is installed."*

*"What is the current connection status?"*

Then launch a new AEDT instance or connect to one that is already running:

*"Launch a new AEDT session."*

*"Connect to the AEDT instance on localhost port 50051."*

Work with projects and designs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*"List the currently open projects."*

*"Open C:/work/my_filter.aedt."*

*"Create a new HFSS design named PatchAntenna."*

*"Save the active project."*

Run inline PyAEDT code
~~~~~~~~~~~~~~~~~~~~~~

Use ``run_python_code`` for geometry creation, parameter updates, boundary
assignment, and any step that does not have a dedicated tool.

Your code runs in the **persistent Python session** of the current AEDT
instance. Imports and variables from one call are available in later calls.

Use ``run_python_script`` when you want to run a complete Python file in
a separate CPython process connected to the same AEDT session through the
PyAEDT launcher environment variables. It uses the MCP server's Python
interpreter and opens no launcher UI or terminal. Native IronPython globals
such as ``oDesktop`` are not injected. The response contains the process ID
and an output log path, not a completion result; check the log before running
dependent operations. If a script is large, you can split it into smaller
chunks and run them with ``run_python_code``.

Run an analysis
~~~~~~~~~~~~~~~

Run design validation before starting a solve, especially after geometry,
boundary, setup, or sweep changes.

*"Validate the active design before solving."*

*"Analyze the active design."*

*"Run setup 'Setup1' on the active design."*

Inspect the model
~~~~~~~~~~~~~~~~~

*"Take a screenshot of the current view."*

*"Get a summary of the active design including its boundaries and variables."*

*"Show the last 50 PyAEDT log lines."*

Export results
~~~~~~~~~~~~~~

*"Export the simulation results as a Touchstone file to C:/results/."*

*"Export the current design configuration."*

Get workflow guidance
~~~~~~~~~~~~~~~~~~~~~

When you start the server with ``--include-context``, you can ask for
topic-specific PyAEDT guidance.

*"Get the HFSS workflow guidelines."*

*"Get the geometry creation guidelines."*

These topics are available: ``workflow``, ``hfss``, ``maxwell``, ``icepak``,
``circuit``, ``geometry``, ``mesh``, ``boundaries``, ``postprocessing``,
``parametric``.

Tool timeouts
-------------

Every tool has a timeout guard so that a stalled AEDT call cannot hang the
server indefinitely.

.. list-table::
   :header-rows: 1
   :widths: 15 15 70

   * - Tier
     - Timeout
     - Tools
   * - Quick
     - 30 seconds
     - ``check_aedt_status``, ``check_aedt_installed``, ``get_pyaedt_logs``,
       ``list_projects``, ``list_designs``, and ``get_model_info``
   * - Medium
     - 120 seconds
     - ``launch_aedt``, ``connect_to_aedt``, ``disconnect_from_aedt``,
       ``open_project``, ``save_project``, ``create_design``, ``validate_design``,
       ``screenshot``, ``clear_aedt``, and ``export_config``
   * - Long
     - 600 s
     - ``run_python_script``, ``run_python_code``, ``analyze_design``,
       and ``export_results``

Best practices
--------------

For recommendations on using PyAEDT-MCP effectively, see :doc:`best_practices`.
