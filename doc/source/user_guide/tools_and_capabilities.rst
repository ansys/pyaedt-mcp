.. _ref_tools_and_capabilities:

Tools and capabilities
======================

Tool availability
-----------------

By default, all tools are visible from startup. When
``--dynamic-tool-discovery`` is passed, tools that require an active AEDT
Desktop connection are hidden until the server has one.

**Always available** (no AEDT connection required):

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
     - Start a new AEDT Desktop instance.
   * - ``connect_to_aedt``
     - Attach to an already-running AEDT instance via gRPC.
   * - ``get_pyaedt_logs``
     - Read the local PyAEDT log file (useful for startup and environment
       debugging).

**Available after connecting to AEDT:**

When ``disconnect_from_aedt`` is called (and dynamic discovery is enabled),
these tools are hidden again.

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Tool
     - Description
   * - ``disconnect_from_aedt``
     - Release the current AEDT Desktop connection.
   * - ``clear_aedt``
     - Close all open projects and release the Desktop process.
   * - ``list_projects``
     - List all currently open AEDT projects.
   * - ``list_designs``
     - List designs inside a project.
   * - ``open_project``
     - Open an ``.aedt`` or ``.aedtz`` project file.
   * - ``save_project``
     - Save the active project to disk.
   * - ``create_design``
     - Create a new design (HFSS, Maxwell, Icepak, Circuit, and so on).
   * - ``analyze_design``
     - Run the configured solver analysis on the active design.
   * - ``export_config``
     - Export the current setup/sweep configuration as JSON.
   * - ``export_results``
     - Export solver results (Touchstone, profile, convergence, mesh).
   * - ``run_python_code``
     - Execute inline PyAEDT Python code in the persistent session.
   * - ``run_python_script``
     - Execute a ``.py`` script file in the persistent session.
   * - ``get_model_info``
     - Return a structured summary of the active design.
   * - ``screenshot``
     - Capture the current 3D modeler view as an image.

**Optional: enabled only with** ``--include-context``:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Tool
     - Description
   * - ``get_guidelines_for``
     - Return authoritative PyAEDT workflow guidelines for a specific topic
       (``workflow``, ``hfss``, ``maxwell``, ``icepak``, ``circuit``,
       ``geometry``, ``mesh``, ``boundaries``, ``postprocessing``,
       ``parametric``).

.. note::
   When ``--connect`` is used on startup, the connection is locked and
   ``launch_aedt``, ``connect_to_aedt``, and ``disconnect_from_aedt`` are
   disabled for the lifetime of the server.

Using the tools
---------------

Establishing a connection
~~~~~~~~~~~~~~~~~~~~~~~~~

Always start by confirming installation and connection state:

*"Check whether AEDT is installed."*

*"What is the current connection status?"*

Then either launch a new AEDT or attach to one that is already running:

*"Launch a new AEDT Desktop session."*

*"Connect to the AEDT instance on localhost port 50051."*

Working with projects and designs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*"List the currently open projects."*

*"Open C:/work/my_filter.aedt."*

*"Create a new HFSS design called PatchAntenna."*

*"Save the active project."*

Running inline PyAEDT code
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``run_python_code`` for geometry creation, parameter updates, boundary
assignment, and any step that does not have a dedicated tool.

All the code executes in the **persistent Python session** of the current AEDT Desktop instance. Imports and variables defined in one call are available in all subsequent calls.

``run_python_script`` is also available for executing a complete Python file in the same persistent session. Depending on the size of the script, or the agent guidance, it can use ``run_python_code`` instead of ``run_python_script`` to execute the script in smaller chunks.

Running an analysis
~~~~~~~~~~~~~~~~~~~

*"Analyze the active design."*

*"Run setup 'Setup1' on the active design."*

Inspecting the model
~~~~~~~~~~~~~~~~~~~~

*"Take a screenshot of the current view."*

*"Get a summary of the active design including its boundaries and variables."*

*"Show the last 50 PyAEDT log lines."*

Exporting results
~~~~~~~~~~~~~~~~~

*"Export the simulation results as a Touchstone file to C:/results/."*

*"Export the current design configuration."*

Getting workflow guidance
~~~~~~~~~~~~~~~~~~~~~~~~~

When the server is started with ``--include-context``, you can ask for
topic-specific PyAEDT guidance:

*"Get the HFSS workflow guidelines."*

*"Get the geometry creation guidelines."*

Available topics: ``workflow``, ``hfss``, ``maxwell``, ``icepak``,
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
     - 30 s
     - ``check_aedt_status``, ``check_aedt_installed``, ``get_pyaedt_logs``,
       ``list_projects``, ``list_designs``, ``get_model_info``
   * - Medium
     - 120 s
     - ``launch_aedt``, ``connect_to_aedt``, ``disconnect_from_aedt``,
       ``open_project``, ``save_project``, ``create_design``,
       ``screenshot``, ``clear_aedt``, ``export_config``
   * - Long
     - 600 s
     - ``run_python_script``, ``run_python_code``, ``analyze_design``,
       ``export_results``

Best practices
--------------

For recommendations on using PyAEDT-MCP effectively, see :doc:`best_practices`.
