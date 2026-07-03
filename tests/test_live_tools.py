# Copyright (C) 2025 - 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
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

"""Live AEDT system tests for MCP tools.

These tests connect to a real AEDT session and are intended for dedicated
Linux runners with AEDT installed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ansys.aedt.core.internal.aedt_versions import aedt_versions
import pytest

from ansys.aedt.mcp.server import PyAEDTAppContext
from ansys.aedt.mcp.tools import (
    analyze_design,
    check_aedt_installed,
    check_aedt_status,
    clear_aedt,
    connect_to_aedt,
    create_design,
    disconnect_from_aedt,
    export_config,
    export_results,
    get_model_info,
    get_pyaedt_logs,
    launch_aedt,
    list_designs,
    list_projects,
    open_project,
    run_python_code,
    run_python_script,
    save_project,
    screenshot,
)

pytestmark = [pytest.mark.system, pytest.mark.general]


def _configured_version() -> str | None:
    requested_version = os.environ.get("PYAEDT_TEST_VERSION")
    if requested_version:
        return requested_version
    return aedt_versions.current_version or aedt_versions.latest_version


def _configure_live_settings() -> None:
    try:
        from ansys.aedt.core import settings
    except Exception:
        from ansys.aedt.core.generic.settings import settings

    settings.use_grpc_api = True
    settings.release_on_exception = False


def _build_tool_context() -> SimpleNamespace:
    app_context = PyAEDTAppContext()
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=app_context),
        enable_components=AsyncMock(),
        disable_components=AsyncMock(),
    )


def _release_desktop(ctx: SimpleNamespace) -> None:
    desktop = ctx.request_context.lifespan_context.desktop
    if desktop is None:
        return

    try:
        desktop.release_desktop(close_projects=False)
    except Exception:
        pass
    finally:
        ctx.request_context.lifespan_context.desktop = None


@pytest.fixture
def running_aedt_session():
    """Start a real AEDT session that tests can attach to."""
    from ansys.aedt.core import Desktop

    _configure_live_settings()

    kwargs = {
        "non_graphical": True,
        "new_desktop": True,
    }
    version = _configured_version()
    if version is not None:
        kwargs["version"] = version

    desktop = Desktop(**kwargs)
    if getattr(desktop, "port", None) is None:
        try:
            desktop.release_desktop(close_projects=False)
        except Exception:
            pass
        pytest.skip("Launched AEDT session did not expose a gRPC port.")

    yield desktop

    try:
        desktop.release_desktop(close_projects=False)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_launch_aedt_live_session_exercises_all_tools(test_tmp_dir):
    """Launch a real AEDT session and validate the full live MCP tool surface."""
    ctx = _build_tool_context()
    base_project_path = test_tmp_dir / "live_tools_project.aedt"
    saved_project_path = test_tmp_dir / "live_tools_project_saved.aedt"
    script_path = test_tmp_dir / "touch_aedt_script.py"
    script_marker = test_tmp_dir / "script_marker.txt"
    config_path = test_tmp_dir / "design_config.json"
    screenshot_path = test_tmp_dir / "design_preview.jpg"
    touchstone_path = test_tmp_dir / "live_tools.s2p"

    try:
        install_status = check_aedt_installed(ctx)
        assert "AEDT is installed" in install_status or "is reachable" in install_status

        disconnected_status = json.loads(check_aedt_status(ctx))
        assert disconnected_status["connected"] is False

        result = await launch_aedt(ctx, non_graphical=True, confirm_new_session=True)
        assert "Successfully launched AEDT Desktop" in result

        status = json.loads(check_aedt_status(ctx))
        assert status["connected"] is True
        assert status["connection"]["is_grpc"] is True

        version_result = run_python_code(
            ctx,
            code=f"""
from ansys.aedt.core import Circuit

circuit = Circuit(
    project=r"{base_project_path}",
    design="LiveCircuit",
    new_desktop=False,
    port=aedt_port,
)
inductor = circuit.modeler.schematic.create_inductor("L1", 1e-9, [400, 400])
circuit.modeler.schematic.create_interface_port(name="Port1", location=inductor.pins[0].location)
circuit.modeler.schematic.create_interface_port(name="Port2", location=inductor.pins[1].location)
setup = circuit.create_setup("Dom_LNA")
setup.SweepDefinition = [
    ("Variable", "Freq"),
    ("Data", "LIN 1GHz 5GHz 101"),
    ("OffsetF1", False),
    ("Synchronize", 0),
]
setup.update()
result = circuit.project_name
""",
        )
        project_name = version_result

        logs = json.loads(get_pyaedt_logs(ctx, tail_lines=50, max_chars=10000))
        assert Path(logs["log_file"]).exists()

        projects = json.loads(list_projects(ctx))
        assert project_name in projects["open_projects"]

        create_result = create_design(
            ctx,
            "Circuit",
            design_name="LiveCircuitExtra",
            project_name=project_name,
        )
        assert "Successfully created Circuit design" in create_result

        designs = json.loads(list_designs(ctx, project_name=project_name))
        assert any("LiveCircuit" in design for design in designs["designs"])
        assert any("LiveCircuitExtra" in design for design in designs["designs"])

        model_info = json.loads(get_model_info(ctx, design_name="LiveCircuit"))
        assert model_info["design_name"] == "LiveCircuit"
        assert "Circuit" in model_info["design_type"]

        script_path.write_text(
            'with open(r"' + str(script_marker) + '", "w") as file_handle:\n'
            '    file_handle.write("script executed")\n',
            encoding="utf-8",
        )
        script_result = run_python_script(ctx, str(script_path))
        assert "Script executed successfully" in script_result
        assert script_marker.exists()

        save_result = save_project(ctx, save_as=str(saved_project_path))
        assert save_result == f"Project saved to: {saved_project_path}"
        assert saved_project_path.exists()

        clear_result = clear_aedt(ctx, close_projects=True)
        assert "AEDT state cleared" in clear_result

        open_result = open_project(ctx, str(saved_project_path), design_name="LiveCircuit")
        assert "Successfully opened project" in open_result
        reopened_projects = json.loads(list_projects(ctx))
        reopened_project_name = saved_project_path.stem
        assert reopened_project_name in reopened_projects["open_projects"]

        analyze_result = analyze_design(
            ctx,
            project_name=reopened_project_name,
            design_name="LiveCircuit",
            setup_name="Dom_LNA",
        )
        assert "Analysis completed successfully" in analyze_result

        export_result = export_results(
            ctx,
            output_path=str(touchstone_path),
            export_type="touchstone",
            setup_name="Dom_LNA",
        )
        assert "Touchstone exported" in export_result
        assert touchstone_path.exists()

        screenshot_result = screenshot(
            ctx,
            path=str(screenshot_path),
            project=reopened_project_name,
            design="LiveCircuit",
            open_viewer=False,
        )
        assert len(screenshot_result) == 2
        assert screenshot_path.exists()

        config_result = json.loads(
            export_config(
                ctx,
                output=str(config_path),
                project=reopened_project_name,
                design="LiveCircuit",
                overwrite=True,
            )
        )
        assert Path(config_result["config_file"]).exists()
    finally:
        _release_desktop(ctx)


@pytest.mark.asyncio
async def test_connect_to_existing_live_session(running_aedt_session):
    """Attach to an already running AEDT gRPC session through the MCP tool."""
    ctx = _build_tool_context()

    result = await connect_to_aedt(
        ctx,
        machine="localhost",
        port=running_aedt_session.port,
        non_graphical=True,
    )
    assert "Successfully connected to AEDT" in result

    status = json.loads(check_aedt_status(ctx))
    assert status["connected"] is True
    assert status["connection"]["port"] == running_aedt_session.port

    disconnect_result = await disconnect_from_aedt(ctx)
    assert disconnect_result == "Successfully disconnected from AEDT Desktop."
