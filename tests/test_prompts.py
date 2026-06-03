"""Tests for system prompt selection based on tool visibility mode."""

import pytest


@pytest.mark.unit
def test_build_system_prompt_defaults_to_static_surface_language():
    """Default prompt should describe the always-visible tool surface."""
    from ansys.aedt.mcp.prompts import build_system_prompt

    prompt = build_system_prompt()

    assert "exposes the full tool surface from startup" in prompt
    assert "call depends on whether an AEDT session is connected" not in prompt


@pytest.mark.unit
def test_build_system_prompt_dynamic_discovery_language():
    """Dynamic discovery prompt should describe connection-aware visibility."""
    from ansys.aedt.mcp.prompts import build_system_prompt

    prompt = build_system_prompt(dynamic_tool_discovery=True)

    assert "uses connection-aware tool visibility" in prompt
    assert "Unlocked automatically once `launch_aedt` or `connect_to_aedt` succeeds" in prompt
