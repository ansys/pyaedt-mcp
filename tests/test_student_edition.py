# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
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

"""Student edition forwarding through tools and startup configuration."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("student", [False, True])
@pytest.mark.parametrize("application", [None, "Maxwell3d"])
async def test_launch_forwards_edition(mock_context_no_desktop, student, application):
    from ansys.aedt.mcp.tools import launch_aedt

    versions = MagicMock(
        current_version="2026.1", latest_version="2026.1", current_student_version="2025.2SV"
    )
    factory = MagicMock()
    with (
        patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
        patch("ansys.aedt.mcp.tools.discover_available_aedt_sessions", return_value=[]),
        patch("ansys.aedt.mcp.tools.aedt_versions", versions),
        patch("ansys.aedt.core.Desktop", factory),
        patch("ansys.aedt.mcp.tools._get_aedt_app_class", return_value=factory),
    ):
        result = await launch_aedt(
            mock_context_no_desktop, application=application, student_version=student
        )
    assert "Successfully launched" in result
    assert factory.call_args.kwargs["student_version"] is student
    assert factory.call_args.kwargs["version"] == ("2025.2SV" if student else "2026.1")


@pytest.mark.asyncio
@pytest.mark.parametrize("student", [False, True])
async def test_connect_forwards_edition(mock_context_no_desktop, student):
    from ansys.aedt.mcp.tools import connect_to_aedt

    with (
        patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
        patch("ansys.aedt.core.Desktop") as desktop,
    ):
        result = await connect_to_aedt(mock_context_no_desktop, port=50051, student_version=student)
    assert "Successfully connected" in result
    assert desktop.call_args.kwargs["student_version"] is student


@pytest.mark.asyncio
async def test_student_launch_error_preserves_unconnected_context(mock_context_no_desktop):
    from ansys.aedt.mcp.tools import launch_aedt

    with (
        patch("ansys.aedt.mcp.tools._is_docker", return_value=False),
        patch("ansys.aedt.mcp.tools.discover_available_aedt_sessions", return_value=[]),
        patch("ansys.aedt.core.Desktop", side_effect=RuntimeError("Student unavailable")),
    ):
        result = await launch_aedt(mock_context_no_desktop, version="2025.2", student_version=True)
    assert "Failed to launch AEDT: Student unavailable" in result
    assert mock_context_no_desktop.request_context.lifespan_context.desktop is None


@pytest.mark.parametrize("student", [False, True])
def test_startup_forwards_cli_edition(student):
    from ansys.aedt.mcp.server import app, launcher

    with patch.object(asyncio, "run"):
        launcher(["--connect", "--student-version"] if student else ["--connect"])
    assert app._cli_config["student_version"] is student
    with patch("ansys.aedt.core.Desktop") as desktop:
        app.create_context()
        app.product_startup()
    assert desktop.call_args.kwargs["student_version"] is student
