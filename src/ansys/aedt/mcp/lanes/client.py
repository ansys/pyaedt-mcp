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

"""Async MCP client used to drive one lane backend."""

from __future__ import annotations

from collections.abc import Generator
import contextlib
import json
from types import TracebackType
from typing import TYPE_CHECKING, Any

import httpx2

if TYPE_CHECKING:
    from fastmcp import Client

DEFAULT_PATH = "/mcp/"
"""Path of the MCP endpoint served by the HTTP transport."""


class BackendAuthError(RuntimeError):
    """Raised when a lane answers HTTP 401 because the token is wrong or missing."""


class LaneAuth(httpx2.Auth):
    """Send a lane bearer token and record whether the lane rejected it.

    The MCP client turns an HTTP 401 into a generic error, so the status is
    captured here, where the raw response is still visible.

    Parameters
    ----------
    token : str, optional
        Bearer token. When ``None``, no ``Authorization`` header is sent.
    """

    def __init__(self, token: str | None) -> None:
        self._token = token
        self.rejected = False

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        """Add the bearer token and inspect the response.

        Parameters
        ----------
        request : httpx2.Request
            Outgoing request.

        Yields
        ------
        httpx2.Request
            The authenticated request.
        """
        if self._token:
            request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request
        if response.status_code == 401:
            self.rejected = True


def _content_to_text(result: Any) -> str:
    """Join the text parts of a tool result."""
    parts = [getattr(part, "text", None) for part in getattr(result, "content", None) or []]
    return "\n".join(part for part in parts if isinstance(part, str))


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Return ``text`` parsed as a JSON object, or ``None``."""
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def aedt_port_from_status(status: dict[str, Any]) -> int | None:
    """Return the AEDT gRPC port from a ``check_aedt_status`` payload.

    Parameters
    ----------
    status : dict[str, Any]
        Parsed ``check_aedt_status`` output.

    Returns
    -------
    int or None
        AEDT gRPC port, or ``None`` when the lane is not connected.
    """
    if not status.get("connected"):
        return None
    port = (status.get("connection") or {}).get("port") or status.get("aedt_port")
    if isinstance(port, int) and port > 0:
        return port
    if isinstance(port, str) and port.isdigit():
        return int(port)
    return None


class BackendClient:
    """MCP client bound to one lane backend.

    Use it as an async context manager:

    >>> async with BackendClient(port=8090, auth_token=token) as backend:  # doctest: +SKIP
    ...     port = await backend.discover_aedt_port()

    Parameters
    ----------
    port : int
        HTTP port of the lane.
    host : str, default: "127.0.0.1"
        Host of the lane.
    path : str, default: "/mcp/"
        MCP endpoint path.
    auth_token : str, optional
        Bearer token of the lane.
    """

    def __init__(
        self,
        port: int,
        host: str = "127.0.0.1",
        path: str = DEFAULT_PATH,
        auth_token: str | None = None,
    ) -> None:
        self.url = f"http://{host}:{port}{path}"
        self._auth = LaneAuth(auth_token)
        self._client: Client | None = None

    def _auth_error(self) -> BackendAuthError:
        return BackendAuthError(f"Backend {self.url} rejected the lane token (HTTP 401).")

    async def __aenter__(self) -> BackendClient:
        """Open the MCP session."""
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        client = Client(StreamableHttpTransport(url=self.url, auth=self._auth))
        try:
            await client.__aenter__()
        except Exception as exc:
            if self._auth.rejected:
                raise self._auth_error() from exc
            raise
        self._client = client
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the MCP session."""
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.__aexit__(exc_type, exc, tb)
            self._client = None

    async def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
        """Call a tool on the lane.

        Parameters
        ----------
        tool_name : str
            Tool name.
        arguments : dict[str, Any], optional
            Tool arguments.

        Returns
        -------
        str
            Text payload of the result.

        Raises
        ------
        BackendAuthError
            If the lane rejected the token.
        RuntimeError
            If the client is not open or the call fails.
        """
        if self._client is None:
            raise RuntimeError(f"BackendClient({self.url}) used outside its context manager.")
        try:
            result = await self._client.call_tool(tool_name, arguments or {})
        except Exception as exc:
            if self._auth.rejected:
                raise self._auth_error() from exc
            raise RuntimeError(f"Backend {self.url}: tool {tool_name!r} failed: {exc}") from exc
        return _content_to_text(result)

    async def check_status(self) -> dict[str, Any]:
        """Return the parsed ``check_aedt_status`` payload.

        Returns
        -------
        dict[str, Any]
            Status payload, or ``{"raw": text}`` when the lane returned plain text.
        """
        text = await self.call("check_aedt_status")
        parsed = _parse_json_object(text)
        return parsed if parsed is not None else {"raw": text}

    async def discover_aedt_port(self) -> int | None:
        """Return the gRPC port of the AEDT session the lane is connected to.

        Returns
        -------
        int or None
            AEDT gRPC port, or ``None`` when the lane is not connected.
        """
        return aedt_port_from_status(await self.check_status())

    async def connect_aedt(self, port: int, non_graphical: bool = True) -> str:
        """Connect the lane to an existing AEDT session.

        Parameters
        ----------
        port : int
            AEDT gRPC port.
        non_graphical : bool, default: True
            Whether the session runs without a UI.

        Returns
        -------
        str
            Output of ``connect_to_aedt``.
        """
        return await self.call("connect_to_aedt", {"port": port, "non_graphical": non_graphical})
