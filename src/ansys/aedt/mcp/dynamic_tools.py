# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Load MCP tools dynamically from a folder of Python files.

Functions decorated with ``fastmcp.tools.tool`` in the Python files of a folder
are added to the running server on demand, through the ``load_tools`` and
``call_loaded_tool`` tools defined in ``tools.py``.
"""

import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from fastmcp.tools import ToolResult

#: Environment variable with the folders, separated by ``os.pathsep``, from
#: which dynamic tools may be loaded. When it is not set, any folder is accepted.
DYNAMIC_TOOL_ROOTS_ENV = "PYAEDT_MCP_DYNAMIC_TOOL_ROOTS"

# Dynamic tool folders already loaded, keyed by normalized path.
_loaded_dynamic_tools: dict[str, FileSystemProvider] = {}


class DynamicToolError(Exception):
    """Raised when dynamic tools cannot be loaded or called."""


def dynamic_tool_roots() -> list[Path]:
    """Return the folders under which dynamic tool folders are accepted.

    An empty list means that any folder is accepted.
    """
    value = os.environ.get(DYNAMIC_TOOL_ROOTS_ENV, "")
    return [_absolute_path(Path(item)) for item in value.split(os.pathsep) if item.strip()]


def _absolute_path(path: Path) -> Path:
    """Return ``path`` absolute and normalized, without following links."""
    return Path(os.path.normpath(path.expanduser().absolute()))


def normalize_dynamic_tool_path(path: str) -> Path:
    """Convert a path or ``file://`` URI to an absolute path without resolving links.

    Folders are often reached through junctions or symlinks, so the path is kept
    as the client sees it and is not resolved to its link target.
    """
    if path.lower().startswith("file:"):
        parsed = urlparse(path)
        path = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path = f"\\\\{parsed.netloc}{path}"
    return _absolute_path(Path(path))


def check_dynamic_tool_folder(folder: Path) -> None:
    """Raise ``DynamicToolError`` if ``folder`` cannot be loaded."""
    roots = dynamic_tool_roots()
    if roots and not any(folder.is_relative_to(root) and folder != root for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise DynamicToolError(f"Folder {folder} is outside the allowed folders: {allowed}.")
    if not folder.is_dir():
        raise DynamicToolError(f"Folder {folder} does not exist.")


async def _describe_tools(provider: FileSystemProvider) -> list[dict[str, Any]]:
    """Return the MCP definitions of the tools served by ``provider``."""
    definitions = []
    for tool in sorted(await provider.list_tools(), key=lambda item: item.name):
        mcp_tool = tool.to_mcp_tool()
        definitions.append(
            {
                "name": mcp_tool.name,
                "description": mcp_tool.description,
                "inputSchema": mcp_tool.inputSchema,
            }
        )
    return definitions


async def load_dynamic_tools(app: FastMCP, path: str) -> tuple[dict[str, Any], bool]:
    """Add the tools in a dynamic tool folder to ``app``.

    Parameters
    ----------
    app : FastMCP
        Server that receives the tools.
    path : str
        Absolute path or ``file://`` URI of the dynamic tool folder.

    Returns
    -------
    tuple[dict, bool]
        Summary with the folder, the tool definitions, and the files that failed
        to load, and whether new tools were added to ``app``.

    Raises
    ------
    DynamicToolError
        If the folder is not allowed, holds no tools, or reuses tool names.
    """
    folder = normalize_dynamic_tool_path(path)
    key = os.path.normcase(str(folder))
    provider = _loaded_dynamic_tools.get(key)
    added = False

    if provider is None:
        check_dynamic_tool_folder(folder)

        candidate = FileSystemProvider(folder)
        new_names = {tool.name for tool in await candidate.list_tools()}
        if not new_names:
            raise DynamicToolError(f"No tools found in {folder}.")

        existing = {tool.name for tool in await app.list_tools(run_middleware=False)}
        clashes = sorted(new_names & existing)
        if clashes:
            raise DynamicToolError(f"Names already used by this server: {', '.join(clashes)}.")

        # Re-check after the awaits so concurrent calls cannot add it twice.
        provider = _loaded_dynamic_tools.get(key)
        if provider is None:
            provider = candidate
            app.add_provider(provider)
            _loaded_dynamic_tools[key] = provider
            added = True

    failed = getattr(provider, "_failed_files", {}) or {}
    summary = {
        "folder": str(folder),
        "already_loaded": not added,
        "tools": await _describe_tools(provider),
        "failed_files": {str(file): str(error) for file, error in failed.items()},
    }
    return summary, added


async def loaded_dynamic_tool_names() -> set[str]:
    """Return the names of every tool added through ``load_dynamic_tools``."""
    names: set[str] = set()
    for provider in _loaded_dynamic_tools.values():
        names.update(tool.name for tool in await provider.list_tools())
    return names


async def call_dynamic_tool(app: FastMCP, name: str, arguments: dict[str, Any]) -> ToolResult:
    """Call a tool added through ``load_dynamic_tools``.

    Raises
    ------
    DynamicToolError
        If ``name`` is not a loaded dynamic tool.
    """
    loaded = await loaded_dynamic_tool_names()
    if name not in loaded:
        available = ", ".join(sorted(loaded)) or "none; call load_tools first"
        raise DynamicToolError(f"{name!r} is not a loaded dynamic tool. Loaded tools: {available}.")
    return await app.call_tool(name, arguments)


def unload_all_dynamic_tools(app: FastMCP) -> None:
    """Remove every loaded dynamic tool folder from ``app``."""
    for provider in _loaded_dynamic_tools.values():
        if provider in app.providers:
            app.providers.remove(provider)
    _loaded_dynamic_tools.clear()
