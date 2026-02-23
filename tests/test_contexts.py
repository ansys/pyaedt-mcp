"""Unit tests for PyAEDT MCP context/guideline tools."""

import pytest


@pytest.mark.asyncio
async def test_context_tools_registered():
    """Test that all context tools are registered with the MCP server."""
    # Import contexts and tools to register them with the app
    from ansys.aedt.mcp import contexts, tools  # noqa: F401
    from ansys.aedt.mcp.server import app

    # Get list of registered tools
    tool_list = await app.list_tools()

    # Expected tool names
    expected_tools = [
        "get_guidelines_for_workflow_overview",
        "get_guidelines_for_hfss",
        "get_guidelines_for_maxwell",
        "get_guidelines_for_icepak",
        "get_guidelines_for_circuit",
        "get_guidelines_for_geometry",
        "get_guidelines_for_mesh",
        "get_guidelines_for_boundaries",
        "get_guidelines_for_postprocessing",
        "get_guidelines_for_parametric",
    ]

    # Check each expected tool is registered
    tool_names = [t.name for t in tool_list]
    for expected_name in expected_tools:
        assert expected_name in tool_names, f"Tool {expected_name} not found"


class TestGuidelineTools:
    """Tests for guideline context tools."""

    def test_workflow_overview(self):
        """Test workflow overview guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_workflow_overview()
        assert "AEDT Simulation Workflow" in result
        assert "PyAEDT Architecture" in result
        assert "HFSS" in result
        assert "Maxwell" in result

    def test_hfss_guidelines(self):
        """Test HFSS guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_hfss()
        assert "HFSS Simulation Guidelines" in result
        assert "Modal" in result
        assert "wave_port" in result

    def test_maxwell_guidelines(self):
        """Test Maxwell guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_maxwell()
        assert "Maxwell" in result
        assert "Magnetostatic" in result
        assert "assign_winding" in result

    def test_icepak_guidelines(self):
        """Test Icepak guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_icepak()
        assert "Icepak Thermal Simulation" in result
        assert "SteadyState" in result
        assert "assign_solid_block" in result

    def test_circuit_guidelines(self):
        """Test Circuit guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_circuit()
        assert "Circuit Simulation Guidelines" in result
        assert "create_resistor" in result
        assert "Touchstone" in result

    def test_geometry_guidelines(self):
        """Test geometry guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_geometry()
        assert "Geometry Creation Guidelines" in result
        assert "create_box" in result
        assert "Boolean Operations" in result

    def test_mesh_guidelines(self):
        """Test mesh guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_mesh()
        assert "Mesh Setup Guidelines" in result
        assert "assign_length_mesh" in result
        assert "adaptive" in result.lower()

    def test_boundaries_guidelines(self):
        """Test boundaries guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_boundaries()
        assert "Boundary and Excitation Guidelines" in result
        assert "radiation_boundary" in result.lower()
        assert "wave_port" in result

    def test_postprocessing_guidelines(self):
        """Test postprocessing guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_postprocessing()
        assert "Postprocessing Guidelines" in result
        assert "create_report" in result
        assert "export_touchstone" in result

    def test_parametric_guidelines(self):
        """Test parametric guideline."""
        from ansys.aedt.mcp import contexts

        result = contexts.get_guidelines_for_parametric()
        assert "Parametric" in result
        assert "Optimization" in result
        assert "add_variable" in result
