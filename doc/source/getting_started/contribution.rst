.. _ref_contributing:

============
Contributing
============

You can contribute to PyAEDT-MCP in several ways:

- Answer discussions on the `GitHub Discussions page <https://github.com/ansys/pyaedt-mcp/discussions>`_
- Post issues on the `GitHub Issues page <https://github.com/ansys/pyaedt-mcp/issues>`_
- Submit pull requests with bug fixes, new features, or documentation improvements

Before contributing, read
`Contributing <https://dev.docs.pyansys.com/how-to/contributing.html>`_
and `Coding style <https://dev.docs.pyansys.com/coding-style/index.html>`_
in the *PyAnsys developer's guide*. To generate useful release notes, follow
the guidelines in `Branch-naming conventions
<https://dev.docs.pyansys.com/how-to/contributing.html#branch-naming-conventions>`_
and `Commit-naming conventions
<https://dev.docs.pyansys.com/how-to/contributing.html#commit-naming-conventions>`_.

Answer discussions
==================

Answering questions in GitHub Discussions is the easiest way to contribute.
Only a GitHub account is required. It deepens your understanding of the project
and helps other users who are facing similar issues.

Post issues
===========

Use the `GitHub Issues page <https://github.com/ansys/pyaedt-mcp/issues>`_ to
report bugs, suggest improvements, or request features.

Use the most appropriate template when available:

- **🐞 Bug, problem, or error**: File a bug report.
- **📖 Documentation issue**: Suggest changes to the documentation.
- **💡 New feature**: Propose a new capability.

If none of the templates fits, open a `blank issue
<https://github.com/ansys/pyaedt-mcp/issues/new>`_.

Development setup
=================

Clone and install:

.. code-block:: bash

   git clone https://github.com/ansys/pyaedt-mcp.git
   cd pyaedt-mcp
   pip install -e ".[dev]"
   pre-commit install

Run the tests:

.. code-block:: bash

   pytest -q

Run the linters:

.. code-block:: bash

   pre-commit run --all-files

Build the documentation:

.. code-block:: bash

   python -m sphinx -W -b html doc/source doc/_build/html

Adding a new tool
-----------------

When adding a new ``@app.tool(...)`` to ``src/ansys/aedt/mcp/tools.py``:

1. **If the tool requires an active AEDT connection**, tag it with
   ``REQUIRES_AEDT_TAG``:

   .. code-block:: python

      from ansys.aedt.mcp.tools import REQUIRES_AEDT_TAG

      @app.tool(tags={REQUIRES_AEDT_TAG})
      def my_new_tool(ctx: Context, ...) -> str:
          ...

2. **If the tool is usable before any AEDT session** (for example, an
   installation check), do *not* add that tag and make sure
   ``tests/test_tools.py`` still reflects the expected pre-connection surface.

3. **Add the tool to the appropriate group of tools** in
   ``src/ansys/aedt/mcp/toolsets.py`` so that it appears in the
   ``toolsets://definition`` discovery resource. The
   ``test_toolsets.py::TestToolsetsResource::test_every_registered_tool_appears_in_some_toolset``
   test fails if it is missing.

4. **Document the tool** in :doc:`../user_guide/tools_and_capabilities`.
