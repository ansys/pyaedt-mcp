# HFSS Patch Antenna Workflow

This example demonstrates a complete HFSS microstrip patch antenna workflow
using the pyaedt-mcp tools. All steps below were validated live against
ANSYS AEDT 2025 R2.

## 1. Check AEDT Installation

**Tool:** `check_aedt_installed`

```
Response:
  AEDT is installed on this system.
  Version: 2025.2
  Executable: C:\Program Files\ANSYS Inc\v252\AnsysEM\ansysedt.exe
```

## 2. Launch AEDT

**Tool:** `launch_aedt`

```
Response:
  Successfully launched AEDT Desktop
  Version: 2025.2
  gRPC Port: 57993
  PID: 11712
  Startup Time: ~6s
```

## 3. Create HFSS Design

**Tool:** `create_design`

| Parameter   | Value                     |
|-------------|---------------------------|
| app_type    | Hfss                      |
| design_name | PatchAntenna_Validation   |

```
Response:
  Successfully created Hfss design
  Design Name: PatchAntenna_Validation
  Project: Project2
  Solution Type: Terminal
```

## 4. Build Geometry and Boundaries

**Tool:** `run_python_code`

```python
from ansys.aedt.core import Hfss
hfss = Hfss(project=desktop.project_list[0], design="PatchAntenna_Validation")

# Create substrate (40x40x1.6 mm FR4)
substrate = hfss.modeler.create_box(
    origin=[0, 0, 0],
    sizes=["40mm", "40mm", "1.6mm"],
    name="Substrate",
    material="FR4_epoxy"
)

# Create ground plane
ground = hfss.modeler.create_rectangle(
    orientation="XY",
    origin=[0, 0, 0],
    sizes=["40mm", "40mm"],
    name="Ground"
)

# Create patch (24x24 mm centered on substrate)
patch = hfss.modeler.create_rectangle(
    orientation="XY",
    origin=["8mm", "8mm", "1.6mm"],
    sizes=["24mm", "24mm"],
    name="Patch"
)

# Assign PerfE boundaries
hfss.assign_perfecte_to_sheets(ground.name)
hfss.assign_perfecte_to_sheets(patch.name)

objects = [obj.name for obj in hfss.modeler.objects.values()]
result = "Geometry and boundaries created. Objects: {}".format(objects)
```

```
Response: Geometry and boundaries created. Objects: ['Substrate', 'Ground', 'Patch']
```

## 5. Create Setup and Frequency Sweep

**Tool:** `run_python_code`

```python
from ansys.aedt.core import Hfss
hfss = Hfss(project=desktop.project_list[0], design="PatchAntenna_Validation")

# Create setup at 2.4 GHz
setup = hfss.create_setup(name="Setup1")
setup.props["Frequency"] = "2.4GHz"
setup.props["MaximumPasses"] = 6
setup.props["MaxDeltaS"] = 0.02
setup.update()

# Add linear step sweep 1-4 GHz
sweep = hfss.create_linear_step_sweep(
    setup="Setup1",
    unit="GHz",
    start_frequency=1.0,
    stop_frequency=4.0,
    step_size=0.05,
    name="Sweep1"
)

result = "Setup and sweep created. Setup: {}, Sweep: Sweep1".format(setup.name)
```

```
Response: Setup and sweep created. Setup: Setup1, Sweep: Sweep1
```

## 6. Capture Screenshot

**Tool:** `screenshot`

Returns a PNG image of the current AEDT 3D viewport.

## 7. Get Model Info

**Tool:** `get_model_info`

| Parameter   | Value                     |
|-------------|---------------------------|
| design_name | PatchAntenna_Validation   |

```json
{
  "design_name": "PatchAntenna_Validation",
  "design_type": "HFSS",
  "project_path": "..."
}
```

## 8. List Projects / Designs

**Tool:** `list_projects`

```json
{ "open_projects": ["Project2"], "count": 1 }
```

**Tool:** `list_designs`

```json
{ "project": "Project2", "designs": ["PatchAntenna_Validation"], "count": 1 }
```

## 9. Export 3D Model

**Tool:** `export_3d_model`

| Parameter     | Value                  |
|---------------|------------------------|
| output_path   | D:/output/model.step   |
| export_format | step                   |

```
Response: 3D model exported to: D:/output/model.step (12345 bytes, format: step)
```

## 10. Clear AEDT

**Tool:** `clear_aedt`

```
Response: AEDT state cleared. Closed 1 project(s).
```
