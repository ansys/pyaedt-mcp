.. _ref_workflows:

Workflow examples
=================

These examples provide practical, end-to-end sequences that show how to use
PyAEDT-MCP tools together for common AEDT tasks.

HFSS patch antenna
~~~~~~~~~~~~~~~~~~

#. ``check_aedt_installed``
#. ``connect_to_aedt`` or ``launch_aedt``
#. ``create_design`` with ``app_type="Hfss"``
#. ``run_python_code`` - create substrate, patch, ground plane, airbox, ports
#. ``run_python_code`` - create analysis setup and frequency sweep
#. ``analyze_design``
#. ``run_python_code`` - create S-parameter report
#. ``export_results`` - export ``.s1p`` Touchstone file

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
