# PyAEDT MCP Server

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server that enables AI assistants to interact with Ansys Electronics Desktop (AEDT) through PyAEDT. This server exposes AEDT capabilities to large language models, allowing them to create, configure, run, and analyze electromagnetic, thermal, and circuit simulations.

## Features

- **Multi-Physics Support**: HFSS, Maxwell 2D/3D, Q3D, Q2D, Icepak, Circuit, TwinBuilder, and more
- **Full Simulation Workflow**: Geometry creation, meshing, boundary setup, analysis, post-processing
- **gRPC Remote Connection**: Connect to AEDT instances on local or remote machines
- **Comprehensive Guidelines**: Context tools providing AEDT workflow guidance to AI assistants
- **Parametric Studies**: Support for parametric sweeps, optimization, and DOE

## Supported AEDT Applications

| Application    | Description                                                         |
| -------------- | ------------------------------------------------------------------- |
| HFSS           | High-frequency electromagnetic simulation (RF, microwave, antennas) |
| Maxwell 2D/3D  | Low-frequency electromagnetic simulation (motors, transformers)     |
| Q3D/Q2D        | Parasitic extraction (capacitance, inductance, resistance)          |
| Icepak         | Thermal management and CFD analysis                                 |
| Circuit        | Circuit-level simulation                                            |
| TwinBuilder    | System-level modeling                                               |
| Mechanical     | Structural analysis                                                 |
| EMIT           | EMI/EMC analysis                                                    |
| RMXprt         | Rotating machine design                                             |
| HFSS 3D Layout | High-speed electronic layout analysis                               |

## Installation

### Using uvx (Recommended)

```bash
uvx --from git+https://github.com/ansys/pyaedt-mcp.git ansys-aedt-mcp
```

### Using pip

```bash
pip install git+https://github.com/ansys/pyaedt-mcp.git
```

### Development Installation

```bash
git clone https://github.com/ansys/pyaedt-mcp.git
cd pyaedt-mcp
pip install -e ".[dev]"
```

## Requirements

- Python >= 3.10
- PyAEDT >= 0.10.0
- fastmcp >= 0.1.0
- ansys-common-mcp >= 0.1.0
- Ansys Electronics Desktop 2022 R2 or later (for gRPC support)

## Usage

### Starting AEDT in gRPC Server Mode

Before connecting via MCP, start AEDT with gRPC server enabled:

```bash
# Windows
"C:\Program Files\ANSYS Inc\v252\AnsysEM\ansysedt.exe" -grpcsrv 50051

# Linux
/ansys_inc/v252/AnsysEM/Linux64/ansysedt -grpcsrv 50051
```

### Running the MCP Server

#### STDIO Transport (Default)

```bash
ansys-aedt-mcp
```

#### HTTP Transport

```bash
ansys-aedt-mcp --transport http --http-host 127.0.0.1 --http-port 8080
```

#### Auto-Connect on Startup

```bash
ansys-aedt-mcp --connect --machine localhost --port 50051
```

### CLI Options

| Option            | Description                       | Default     |
| ----------------- | --------------------------------- | ----------- |
| `--transport`     | Transport type: `stdio` or `http` | `stdio`     |
| `--machine`       | AEDT machine hostname/IP          | `localhost` |
| `--port`          | AEDT gRPC port                    | `50051`     |
| `--version`       | AEDT version (e.g., "2025.2")     | Auto-detect |
| `--non-graphical` | Run AEDT in non-graphical mode    | `True`      |
| `--graphical`     | Run AEDT in graphical mode        | `False`     |
| `--connect`       | Connect to AEDT on startup        | `False`     |
| `--http-host`     | HTTP transport host               | `127.0.0.1` |
| `--http-port`     | HTTP transport port               | `8080`      |

## MCP Tools

### Connection & Status Tools

| Tool                   | Description                          |
| ---------------------- | ------------------------------------ |
| `check_aedt_status`    | Check AEDT Desktop connection status |
| `check_aedt_installed` | Verify AEDT installation on system   |
| `launch_aedt`          | Launch new AEDT Desktop instance     |
| `connect_to_aedt`      | Connect to running AEDT via gRPC     |
| `disconnect_from_aedt` | Disconnect from AEDT                 |

### Project & Design Tools

| Tool             | Description                             |
| ---------------- | --------------------------------------- |
| `list_projects`  | List all open projects                  |
| `list_designs`   | List designs in a project               |
| `open_project`   | Open an AEDT project file (.aedt)       |
| `save_project`   | Save current project                    |
| `create_design`  | Create new design (HFSS, Maxwell, etc.) |
| `analyze_design` | Run simulation analysis                 |
| `export_results` | Export simulation results               |

### Script Execution Tools

| Tool                | Description                        |
| ------------------- | ---------------------------------- |
| `run_python_script` | Execute Python script file in AEDT |
| `run_python_code`   | Execute inline Python code in AEDT |

### File Management Tools

| Tool            | Description                     |
| --------------- | ------------------------------- |
| `list_files`    | List files in working directory |
| `upload_file`   | Upload file to AEDT machine     |
| `download_file` | Download file from AEDT machine |

### Utility Tools

| Tool                | Description                               |
| ------------------- | ----------------------------------------- |
| `clear_aedt`        | Clear AEDT state (close projects)         |
| `get_model_info`    | Get current design information            |
| `screenshot`        | Capture screenshot of current design view |
| `export_touchstone` | Export S-parameters to Touchstone format  |
| `export_3d_model`   | Export 3D geometry (STEP, IGES, SAT, STL) |

### Guideline/Context Tools

| Tool                                   | Description                          |
| -------------------------------------- | ------------------------------------ |
| `get_guidelines_for_workflow_overview` | General AEDT simulation workflow     |
| `get_guidelines_for_hfss`              | HFSS-specific guidance               |
| `get_guidelines_for_maxwell`           | Maxwell 2D/3D guidance               |
| `get_guidelines_for_icepak`            | Icepak thermal analysis guidance     |
| `get_guidelines_for_circuit`           | Circuit simulation guidance          |
| `get_guidelines_for_geometry`          | Geometry creation guidance           |
| `get_guidelines_for_mesh`              | Mesh setup guidance                  |
| `get_guidelines_for_boundaries`        | Boundaries and excitations guidance  |
| `get_guidelines_for_postprocessing`    | Results and export guidance          |
| `get_guidelines_for_parametric`        | Parametric and optimization guidance |

## VS Code Configuration

Add to your VS Code `settings.json`:

```json
{
  "mcp": {
    "servers": {
      "pyaedt-mcp": {
        "command": "uvx",
        "args": [
          "--index-strategy", "unsafe-best-match",
          "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
          "ansys-aedt-mcp"
        ]
      }
    }
  }
}
```

### With Auto-Connect

```json
{
  "mcp": {
    "servers": {
      "pyaedt-mcp": {
        "command": "uvx",
        "args": [
          "--index-strategy", "unsafe-best-match",
          "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
          "ansys-aedt-mcp"
        ]
      }
    }
  }
}
```

## Claude Desktop Configuration

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "pyaedt-mcp": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/ansys/pyaedt-mcp.git",
        "ansys-aedt-mcp"
      ]
    }
  }
}
```

## Example Workflows

### HFSS Patch Antenna Design

```
User: Create a 2.4 GHz patch antenna with FR4 substrate

AI Assistant uses:
1. connect_to_aedt - Connect to running AEDT
2. create_design - Create HFSS design
3. run_python_code - Create geometry, assign materials, boundaries
4. run_python_code - Create setup and frequency sweep
5. analyze_design - Run simulation
6. run_python_code - Create S-parameter report
7. export_results - Export touchstone file
```

### Maxwell Motor Analysis

```
User: Analyze torque vs speed for a brushless DC motor

AI Assistant uses:
1. connect_to_aedt - Connect to AEDT
2. create_design - Create Maxwell3d transient design
3. run_python_code - Create motor geometry
4. run_python_code - Assign windings and excitations
5. run_python_code - Set up motion and transient analysis
6. analyze_design - Run simulation
7. run_python_code - Create torque report
```

### Icepak Thermal Analysis

```
User: Analyze thermal performance of a PCB with multiple ICs

AI Assistant uses:
1. connect_to_aedt - Connect to AEDT
2. create_design - Create Icepak design
3. run_python_code - Create PCB and component geometry
4. run_python_code - Assign heat sources and boundary conditions
5. analyze_design - Run steady-state analysis
6. run_python_code - Create temperature contour plot
7. export_results - Export thermal summary
```

## Testing

### Run Unit Tests

```bash
pytest tests/ -v --ignore=tests/test_integration.py
```

### Run Integration Tests

```bash
# Start AEDT in gRPC mode first
pytest tests/test_integration.py -v -m integration
```

### With Environment Variables

```bash
AEDT_PORT=50051 AEDT_MACHINE=localhost pytest tests/test_integration.py -v
```

## Project Structure

```
pyaedt-mcp/
├── src/
│   └── ansys/
│       └── aedt/
│           └── mcp/
│               ├── __init__.py       # Package initialization
│               ├── __main__.py       # Entry point
│               ├── server.py         # MCP server and lifespan
│               ├── tools.py          # MCP tools (connection, project, etc.)
│               ├── contexts.py       # Guideline context tools
│               ├── helpers.py        # Utility functions
│               ├── prompts.py        # Prompt templates
│               ├── py.typed          # PEP 561 marker
│               └── aedt_helper/      # AEDT helper modules
│                   ├── __init__.py
│                   └── startup_code.py
├── tests/
│   ├── conftest.py
│   ├── test_tools.py
│   ├── test_contexts.py
│   ├── test_helpers.py
│   └── test_integration.py
├── docker/
│   └── docker-compose.yml
├── pyproject.toml
├── LICENSE
└── README.md
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest tests/ -v`
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Related Projects

- [PyAEDT](https://github.com/ansys/pyaedt) - Python library for AEDT
- [PyMAPDL MCP](https://github.com/ansys/pymapdl-mcp) - MCP server for MAPDL
- [PyMechanical MCP](https://github.com/ansys/pymechanical-mcp) - MCP server for Mechanical
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP specification
