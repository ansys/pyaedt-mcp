.. _ref_best_practices:

Best practices
==============

Session management
------------------

**Reuse the AEDT Desktop connection**
    Keep the same AEDT session open across multiple tool calls. Each
    ``launch_aedt`` or ``connect_to_aedt`` call incurs a non-trivial startup
    cost; only reconnect when genuinely necessary.

**Prefer** ``check_aedt_status`` **before every workflow**
    Always call ``check_aedt_status`` at the start of a workflow to confirm
    whether a Desktop connection already exists. Use the result to decide
    between ``launch_aedt`` (no session) and ``connect_to_aedt`` (existing
    session).

**Clean shutdown**
    Disconnect properly when done. Abrupt termination can leave AEDT processes
    running and files in an inconsistent state. Use ``disconnect_from_aedt``
    for a graceful release or ``clear_aedt`` to also close all open projects.

**Error handling**
    Check the text returned by every tool for error messages before
    proceeding. Most tools return a human-readable error string rather than
    raising an exception, so the next step in a workflow can act on the result.

Scripting with ``run_python_code``
-----------------------------------

**Use the persistent session**
    ``run_python_code`` and ``run_python_script`` share a persistent Python
    interpreter. Prefer breaking complex workflows into several short
    ``run_python_code`` calls rather than one large script; this gives the AI
    assistant a chance to inspect intermediate state.

**Always include the safety preamble**
    Before any PyAEDT code that interacts with a live AEDT instance, include:

    .. code-block:: python

       from ansys.aedt.core import settings
       settings.release_on_exception = False

    This prevents AEDT from shutting down if an exception occurs during the
    tool call.

**Reuse the Desktop port**
    When opening a PyAEDT application class (``Hfss``, ``Maxwell3d``, and so
    on), always pass ``port=desktop.port`` to attach to the existing session
    rather than launching a new AEDT process:

    .. code-block:: python

       hfss = Hfss(project="MyProject", design="Antenna", port=desktop.port)

**Prefer** ``run_python_code`` **over** ``run_python_script``
    Use ``run_python_code`` for short inline tasks. Reserve
    ``run_python_script`` for files that already exist on disk (for example,
    customer-provided scripts or parametric templates).

**Use** ``get_guidelines_for`` **before generating code**
    When ``--include-context`` is active, call ``get_guidelines_for`` with the
    relevant topic before writing PyAEDT code. The returned guidelines contain
    correct API patterns, avoiding common mistakes.

Data handling
-------------

**Extract only what you need**
    Query specific design properties or result values rather than loading
    entire result sets. AEDT result files can be large; targeted extraction is
    faster and less likely to hit tool timeouts.

**Cache extracted data**
    Store extracted data in Python variables within the persistent session so
    subsequent analysis steps can reuse it without re-querying AEDT.

**Validate results**
    After extraction, verify that values are physically plausible (for
    example, positive power, non-zero S-parameters, realistic temperatures)
    before building reports or exporting.

Visualization
-------------

**Screenshot after key steps**
    Call ``screenshot`` after geometry creation, after meshing, and after
    analysis to give the AI assistant a visual checkpoint. This helps detect
    geometry errors before solving.

**Use** ``run_python_code`` **for custom plots**
    For plots beyond what AEDT produces natively, use PyAEDT's report API or
    Matplotlib inside ``run_python_code``. The persistent session keeps
    previously imported libraries available.

**Export for documentation**
    Save high-quality screenshots and result plots with meaningful file names
    so they can be included directly in engineering reports.

Workflow design
---------------

**Break complex tasks into steps**
    A well-structured workflow calls one dedicated tool per logical step
    (connect → create design → set up geometry → analyze → export). This keeps
    each tool call focused, makes errors easier to diagnose, and avoids timeout
    issues.

**Validate input before sending to AEDT**
    Check parameter values (for example, frequencies, dimensions, materials)
    in a ``run_python_code`` call before passing them to the solver. Early
    validation avoids long solve runs that fail for trivial reasons.

**Progress feedback**
    Include ``check_aedt_status`` and ``get_pyaedt_logs`` calls at key points
    in long-running workflows. This surfaces solver progress and errors in near
    real-time.

**Design for recovery**
    Structure workflows so that individual steps can be re-run without
    starting over. Use ``save_project`` after expensive geometry or mesh steps
    to create recovery points.

Performance
-----------

**Minimize Desktop restarts**
    Relaunching AEDT adds tens of seconds of overhead. Reuse the existing
    session across as many operations as possible.

**Adaptive meshing is preferred**
    Rely on AEDT's adaptive mesh refinement rather than manually specifying
    mesh operations unless a specific convergence criterion requires it.

**Parallel independent analyses**
    When running multiple independent designs (for example, a geometry sweep),
    consider using AEDT's built-in parametric solver rather than running
    designs sequentially from the MCP server.

**Result processing in Python**
    Extract result data into Python arrays or DataFrames and perform analysis
    there rather than issuing repeated AEDT queries. The persistent session
    retains the data between calls.

Common workflow patterns
------------------------

Parametric sweep
~~~~~~~~~~~~~~~~

#. Define the parameter space in PyAEDT ``ParameterSet``.
#. Register all combinations with the parametric setup.
#. Call ``analyze_design`` once; the solver iterates internally.
#. Use ``run_python_code`` to extract and aggregate results after the solve.

Convergence study
~~~~~~~~~~~~~~~~~

#. Solve with the default coarse mesh.
#. Inspect convergence data via ``export_results`` (type ``convergence``).
#. Refine the mesh selectively with mesh operations.
#. Re-run ``analyze_design``.
#. Repeat until the result delta meets the acceptance criterion.

Debugging a failed solve
~~~~~~~~~~~~~~~~~~~~~~~~

#. Call ``check_aedt_status`` to confirm the session is still alive.
#. Call ``get_pyaedt_logs`` with a ``contains`` filter for ``error`` or
   ``warning``.
#. Take a ``screenshot`` to visually inspect the model state.
#. Reproduce the failing step with a minimal ``run_python_code`` snippet.
