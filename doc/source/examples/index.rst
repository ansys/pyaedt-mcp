.. _ref_examples:

Examples
========

These examples show the intended flow more than exact solver setup details.

Connect to an existing AEDT session
-----------------------------------

1. Start AEDT with ``-grpcsrv 50051``.
2. Start the MCP server.
3. Call ``check_aedt_status`` to confirm whether a connection already exists.
4. Call ``connect_to_aedt``.
5. Call ``list_projects`` or ``open_project`` and continue from there.

Create and solve a new design
-----------------------------

1. Call ``launch_aedt`` or ``connect_to_aedt``.
2. Call ``create_design`` for the target solver.
3. Use ``run_python_code`` for geometry, materials, boundaries, and setup logic.
4. Call ``analyze_design``.
5. Call ``export_results`` or ``screenshot``.

Debug a failing workflow
------------------------

1. Call ``check_aedt_status`` to confirm connection state.
2. Call ``get_pyaedt_logs`` to inspect recent PyAEDT output.
3. Re-run the failing step with a smaller ``run_python_code`` snippet.
4. Export a screenshot or model summary if the failure looks geometry-related.
