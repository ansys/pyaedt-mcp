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

"""Hooks that turn a regular HTTP server into a token-protected lane backend.

The lane spawner starts ``python -m ansys.aedt.mcp --transport http ...``
with a per-lane secret in :data:`TOKEN_ENV`. When :func:`server.launcher
<ansys.aedt.mcp.server.launcher>` finds that variable, it calls
:func:`apply_lane_backend_hooks`. That function:

* removes the secret from the environment so AEDT and any other child
  process never inherit it,
* requires the lane bearer token on every HTTP request, and
* applies the PyAEDT version fixes from :mod:`.aedt_compat`.

Without the variable, the server behaves exactly as before.
"""

from __future__ import annotations

import hmac
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fastmcp.server.auth import TokenVerifier

TOKEN_ENV = "ANSYS_AEDT_MCP_LANE_TOKEN"  # nosec B105 - variable name, not a secret
"""Environment variable holding the lane bearer token."""

CLIENT_ID = "ansys-aedt-mcp-lanes"
"""Client ID attached to requests authenticated with the lane token."""


def make_verifier(token: str) -> TokenVerifier:
    """Create a token verifier that accepts exactly ``token``.

    Parameters
    ----------
    token : str
        Expected bearer token.

    Returns
    -------
    fastmcp.server.auth.TokenVerifier
        Verifier using a constant-time comparison.
    """
    from fastmcp.server.auth import AccessToken, TokenVerifier

    expected = token.encode()

    class _LaneTokenVerifier(TokenVerifier):
        async def verify_token(self, token: str) -> AccessToken | None:
            if not hmac.compare_digest(token.encode(), expected):
                return None
            return AccessToken(token=token, client_id=CLIENT_ID, scopes=[])

    return _LaneTokenVerifier()


def is_lane_backend() -> bool:
    """Check whether this process was spawned as a lane backend.

    Returns
    -------
    bool
        ``True`` if :data:`TOKEN_ENV` is set.
    """
    return bool(os.environ.get(TOKEN_ENV))


def apply_lane_backend_hooks(app: FastMCP) -> bool:
    """Secure ``app`` with the lane token and apply the AEDT version fixes.

    Parameters
    ----------
    app : fastmcp.FastMCP
        Server about to run as a lane backend.

    Returns
    -------
    bool
        ``True`` if the hooks were applied, ``False`` if :data:`TOKEN_ENV` is not set.
    """
    token = os.environ.pop(TOKEN_ENV, None)
    if not token:
        return False

    from ansys.aedt.mcp.lanes import aedt_compat

    try:
        aedt_compat.install()
    except Exception as exc:  # The fixes are best effort; never block the backend.
        sys.stderr.write(f"ansys-aedt-mcp lanes: AEDT version fixes not applied: {exc!r}\n")

    app.auth = make_verifier(token)
    return True
