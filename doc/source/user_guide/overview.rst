.. _ref_overview:

Overview
========

PyAEDT-MCP is a Model Context Protocol (MCP) server that lets an AI client work
with AEDT. You can understand it as a bridge between the AI client and AEDT.

Main modules
------------

.. list-table::
   :header-rows: 1

   * - Module
     - Responsibility
   * - ``server.py``
     - Defines the app, CLI, startup logic, cleanup, transport selection, and the typed app context.
   * - ``tools.py``
     - Implements the AEDT-facing tool surface: connection, project management, scripting, analysis, inspection, and export.
   * - ``helpers.py``
     - Holds small helpers for endpoint probing, version parsing, and extracting structured AEDT model information.
   * - ``prompts.py``
     - Builds the system prompt exposed to MCP clients, including the connection workflow and tool-usage rules. It provides useful context for the AI client to understand the server's capabilities and limitations.
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

.. note::

  When ``--dynamic-tool-discovery`` is enabled, tools tagged with
  ``REQUIRES_AEDT_TAG`` are hidden until the server has an active AEDT
  connection. This helps save LLM context budget because AEDT-dependent tools
  are not advertised by default before a connection exists. Without that flag,
  the full tool surface stays visible from startup.

Simple AEDT use cases
---------------------

Here are a few simple workflows you can run through the MCP server:

- **Check your environment and connect:** verify installation, launch AEDT if
  needed, and connect to a running session.
- **Open and inspect a project:** list available projects and designs, open the
  one you need, and inspect model information, like geometry, materials, and boundary conditions.
- **Run a basic analysis:** analyze the active design and export setup
  configuration for review.
- **Collect quick outputs:** capture a screenshot and export solver results to
  share with teammates.
- **Automate a repetitive step:** leverage MCP tools to develop PyAEDT scripts that automate repetitive tasks. These tools can help to iterate faster and reduce manual errors in your workflow.

Next steps
----------

- Start with :doc:`../getting_started/index`.
- Review guidance in :doc:`best_practices`.
- Learn how to contribute in :doc:`../getting_started/contribution`.
