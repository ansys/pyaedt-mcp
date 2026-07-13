.. _ref_workflows:

Workflow examples
=================

These examples provide practical, end-to-end sequences that show how to use
PyAEDT-MCP tools together for common AEDT tasks.

HFSS patch antenna
~~~~~~~~~~~~~~~~~~

See :doc:`../examples/hfss_patch_antenna_workflow` for the full step-by-step
workflow, including geometry creation, setup, solve, reporting, and screenshots.

Maxwell motor analysis
~~~~~~~~~~~~~~~~~~~~~~

#. ``connect_to_aedt`` or ``launch_aedt``
#. ``create_design`` with ``app_type="Maxwell3d"``
#. ``run_python_code`` - build motor geometry and assign materials
#. ``run_python_code`` - assign windings, excitations, and motion setup
#. ``analyze_design``
#. ``run_python_code`` - create torque/speed report

Icepak thermal analysis
~~~~~~~~~~~~~~~~~~~~~~~

#. ``connect_to_aedt`` or ``launch_aedt``
#. ``create_design`` with ``app_type="Icepak"``
#. ``run_python_code`` - create PCB, components, and heat sources
#. ``run_python_code`` - assign boundary conditions
#. ``analyze_design``
#. ``run_python_code`` - create temperature-contour plot
#. ``export_results``
