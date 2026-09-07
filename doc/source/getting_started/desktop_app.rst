.. _ref_desktop_app:

Desktop app
===========

The PyAEDT MCP desktop app provides a Windows interface for installing and
updating the managed MCP environment, running the local HTTP server, and
configuring supported coding-agent profiles.

First launch
------------

When the managed environment has not been installed, the app opens a setup
guide. We refer as managed environment the virtual environment that the PyAEDT
MCP desktop app creates for installing and running the managed MCP environment.
By default, this environment will be available in `%APPDATA%\\.pyaedt_mcp`.

On the **Server** tab, choose an install source and MCP version, then
select **Install MCP**. After installation, the app enables **Start Server**.

Use the **Update MCP** button to update an existing managed environment. Choose
**Git branch** as the install source when testing a repository branch instead
of a published release.

Server tab
----------

Use the **Server** tab to install or update PyAEDT MCP and to start its local
HTTP transport. The **Server log** window displays standard output and errors
from the MCP server that the desktop app launches. Use it to confirm startup,
inspect debug output, and diagnose a server that exits unexpectedly.

Screenshot placeholder
^^^^^^^^^^^^^^^^^^^^^^

``Server tab with installation controls and server log``

Add the image at ``doc/source/_static/images/desktop_app/server-tab.png``.

System tray
-----------

.. warning::

	Closing the application window keeps PyAEDT MCP running in the Windows
	system tray. To exit the desktop app completely, right-click the PyAEDT MCP
	tray icon and select **Exit**. The tray menu also provides actions to open
	the window and start or stop the HTTP server.

Screenshot placeholder
^^^^^^^^^^^^^^^^^^^^^^

``PyAEDT MCP system-tray icon and context menu``

Add the image at ``doc/source/_static/images/desktop_app/system-tray-menu.png``.

Advanced tab
------------

Use **AEDT connection** to supply the HTTP port and the gRPC port for an AEDT
session. Select **Connect on start** to connect PyAEDT MCP to that session when
the HTTP server starts. The remaining controls configure graphical AEDT,
guidance tools, dynamic tool discovery, and debug logging.

Screenshot placeholder
^^^^^^^^^^^^^^^^^^^^^^

``Advanced tab with HTTP and gRPC connection ports``

Add the image at ``doc/source/_static/images/desktop_app/advanced-tab.png``.

Coding agents tab
-----------------

Select the coding-agent profiles to configure, choose **Stdio** or **HTTP** as
the profile transport, and confirm the configuration file path for each agent.
Select **Install profiles** to write the selected configuration files. Use
**HTTP** only after starting the local HTTP server.

Screenshot placeholder
^^^^^^^^^^^^^^^^^^^^^^

``Coding agents tab with selected profiles and HTTP transport``

Add the image at ``doc/source/_static/images/desktop_app/coding-agents-tab.png``.
