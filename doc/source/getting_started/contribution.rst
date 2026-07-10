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

Clone and install in editable mode with development dependencies:

.. code-block:: bash

   git clone https://github.com/ansys/pyaedt-mcp.git
   cd pyaedt-mcp
   pip install -e .
   pre-commit install

Run the tests:

.. code-block:: bash

   pytest -q

.. note::
   Pull requests are accepted only when code coverage is greater than 80%.

Run the linters:

.. code-block:: bash

   pre-commit run --all-files

Build the documentation:

.. code-block:: bash

   python -m sphinx -W -b html doc/source doc/_build/html

API reference generation
========================

PyAEDT-MCP API docs are generated automatically during Sphinx builds.

- AutoAPI extension: ``ansys_sphinx_theme.extension.autoapi`` (configured in
  ``doc/source/conf.py``)
- Source package: ``src/ansys/aedt/mcp``
- Entry page: :doc:`../api/index`

When you add or rename modules, classes, or functions under
``src/ansys/aedt/mcp``, rebuild the docs to refresh generated API pages:

.. code-block:: bash

   python -m sphinx -W -b html doc/source doc/_build/html

To improve API output quality, write clear NumPy-style docstrings for public
objects and keep module docstrings up to date.

For tool-authoring guidance, see :doc:`../examples/adding_new_tool`.
