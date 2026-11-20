.. _ref_workflows:

Workflows
=========

Use these practical, end-to-end workflows to run common AEDT tasks with
PyAEDT-MCP tools.

HFSS patch antenna
~~~~~~~~~~~~~~~~~~

See :doc:`../examples/hfss_patch_antenna_workflow` for a complete step-by-step
workflow that covers geometry creation, setup, solve, reporting, and screenshots.

Maxwell motor analysis
~~~~~~~~~~~~~~~~~~~~~~

#. Run ``connect_to_aedt`` with ``app_type="Maxwell3d"`` or ``launch_aedt`` with
   ``application="Maxwell3d"`` to connect to or launch AEDT and create the design
   in one call.
#. Run ``run_python_code`` to build the motor geometry and assign materials.
#. Run ``run_python_code`` to assign windings, excitations, and motion setup.
#. Run ``validate_design`` to catch model/setup issues before solving.
#. Run ``analyze_design`` to analyze your design.
#. Run ``run_python_code`` to create a torque and speed report.

Icepak thermal analysis
~~~~~~~~~~~~~~~~~~~~~~~

#. Run ``connect_to_aedt`` with ``app_type="Icepak"`` or ``launch_aedt`` with
   ``application="Icepak"`` to connect to or launch AEDT and create the design
   in one call.
#. Run ``run_python_code`` to create the PCB, components, and heat sources.
#. Run ``run_python_code`` to assign boundary conditions.
#. Run ``validate_design`` to catch model/setup issues before solving.
#. Run ``analyze_design`` to analyze your design.
#. Run ``run_python_code`` to create a temperature contour plot.
#. Run ``export_results`` to export the simulation results.
