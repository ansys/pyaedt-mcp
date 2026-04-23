# HFSS Patch Antenna Workflow

This example demonstrates a complete HFSS microstrip patch antenna workflow
using the pyaedt-mcp tools. All steps below were validated live against
ANSYS AEDT 2025 R2 on April 20, 2026.

> **GUI Mode:** Launch AEDT with `non_graphical=false` so the GUI is visible
> and you can see the antenna geometry, solved mesh, and S11 report plot
> interactively in the AEDT window.
>
> **IMPORTANT:** When creating PyAEDT app instances (Hfss, Maxwell3d, etc.)
> inside `run_python_code`, always pass `port=desktop.port` to ensure the
> app connects to the **same** AEDT Desktop instance that was launched.
> Without `port=`, PyAEDT may connect to a different or new AEDT process.

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

| Parameter      | Value |
|----------------|-------|
| non_graphical  | false |

> Launch in graphical mode so the antenna and S11 report are visible in the GUI.

```
Response:
  Successfully launched AEDT Desktop
  Version: 2025.2
  gRPC Port: 59661
  PID: 2600
  Startup Time: ~18s
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
  Project: Project6
  Solution Type: Terminal
```

## 4. Build Geometry and Boundaries

**Tool:** `run_python_code`

```python
from ansys.aedt.core import Hfss
hfss = Hfss(project=desktop.project_list[0], design="PatchAntenna_Validation", port=desktop.port)

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

## 5. Add Feed Line, Lumped Port, and Air Box

**Tool:** `run_python_code`

```python
from ansys.aedt.core import Hfss
hfss = Hfss(project=desktop.project_list[0], design="PatchAntenna_Validation", port=desktop.port)

# Feed line (3mm wide, centered in X, from y=0 to patch edge at y=8mm)
feed_x = (40 - 3) / 2
feed = hfss.modeler.create_rectangle(
    orientation="XY",
    origin=["{:.1f}mm".format(feed_x), "0mm", "1.6mm"],
    sizes=["3mm", "8mm"],
    name="FeedLine"
)
hfss.assign_perfecte_to_sheets(feed.name)

# Feed port face (YZ plane at y=0, spans ground to feedline)
feed_port = hfss.modeler.create_rectangle(
    orientation="YZ",
    origin=["{:.1f}mm".format(feed_x), "0mm", "0mm"],
    sizes=["1.6mm", "3mm"],
    name="FeedPort"
)

# Lumped port with Ground reference
hfss.lumped_port(
    assignment="FeedPort",
    name="Port1",
    reference=["Ground"],
    integration_line=1
)

# Air box + radiation boundary
airbox = hfss.modeler.create_box(
    origin=["-15mm", "-15mm", "-15mm"],
    sizes=["70mm", "70mm", "31.6mm"],
    name="AirBox",
    material="vacuum"
)
hfss.assign_radiation_boundary_to_objects("AirBox")

objects = [obj.name for obj in hfss.modeler.objects.values()]
result = "Feed, port, and airbox added. Objects: {}".format(objects)
```

```
Response: Feed, port, and airbox added. Objects: ['FeedLine', 'Substrate', 'Ground', 'Patch', 'FeedPort', 'AirBox']
```

## 6. Create Setup and Frequency Sweep

**Tool:** `run_python_code`

```python
from ansys.aedt.core import Hfss
hfss = Hfss(project=desktop.project_list[0], design="PatchAntenna_Validation", port=desktop.port)

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

# Validate design
valid = hfss.validate_full_design()

result = "Setup and sweep created. Setup: {}, Sweep: Sweep1, Valid: {}".format(
    setup.name, valid[1] if isinstance(valid, tuple) else valid
)
```

```
Response: Setup and sweep created. Setup: Setup1, Sweep: Sweep1, Valid: True
```

## 7. Capture Pre-Solve Screenshot

**Tool:** `screenshot`

Returns a PNG image of the AEDT viewport showing the antenna geometry.

## 8. Solve the Design

**Tool:** `run_python_code`

```python
import time
from ansys.aedt.core import Hfss
hfss = Hfss(project=desktop.project_list[0], design="PatchAntenna_Validation", port=desktop.port)

hfss.save_project()
t0 = time.time()
solved = hfss.analyze()
elapsed = time.time() - t0

result = "Solved: {}, Time: {:.0f}s".format(solved, elapsed)
```

```
Response: Solved: True, Time: 81s
```

## 9. Create S11 Report and Export Results

**Tool:** `run_python_code`

> Terminal solution type uses `St()` notation (not `S()`).

```python
import os, math
from ansys.aedt.core import Hfss

hfss = Hfss(project=desktop.project_list[0], design="PatchAntenna_Validation", port=desktop.port)

# Create S11 report via native API
report_module = hfss.odesign.GetModule("ReportSetup")
report_module.CreateReport(
    "S11_Return_Loss",
    "Terminal Solution Data",
    "Rectangular Plot",
    "Setup1 : Sweep1",
    ["Domain:=", "Sweep"],
    ["Freq:=", ["All"]],
    ["X Component:=", "Freq", "Y Component:=", ["dB(St(Port1_T1,Port1_T1))"]]
)

# Export Touchstone for data analysis
snp_path = r"D:\ANSYS-DEV\screenshots\PatchAntenna_Validation.s1p"
os.makedirs(os.path.dirname(snp_path), exist_ok=True)
hfss.export_touchstone(setup="Setup1", sweep="Sweep1", output_file=snp_path)

# Parse S1P (MA format: freq_GHz magnitude angle_deg)
with open(snp_path, 'r') as f:
    lines = f.readlines()
data = [l.strip() for l in lines if l.strip() and not l.startswith('!') and not l.startswith('#')]
min_s11, min_freq = 999, 0
for line in data:
    parts = line.split()
    if len(parts) >= 3:
        freq, mag = float(parts[0]), float(parts[1])
        db = 20 * math.log10(mag) if mag > 0 else -100
        if db < min_s11:
            min_s11, min_freq = db, freq

# Export report image
jpg_path = r"D:\ANSYS-DEV\screenshots\S11_Report_Validation.jpg"
report_module.ExportImageToFile("S11_Return_Loss", jpg_path, 1920, 1080)

result = "S11 Report created! Resonance: {:.4f} GHz, S11 = {:.2f} dB".format(min_freq, min_s11)
```

```
Response: S11 Report created! Resonance: 2.8000 GHz, S11 = -5.22 dB
```

## 10. Capture Post-Solve Screenshot

**Tool:** `screenshot`

Returns a PNG showing the S11_Return_Loss report visible in the AEDT GUI.

## 11. Export 3D Model

**Tool:** `run_python_code`

```python
import os
from ansys.aedt.core import Hfss

hfss = Hfss(project=desktop.project_list[0], design="PatchAntenna_Validation", port=desktop.port)

step_path = r"D:\ANSYS-DEV\screenshots\PatchAntenna_Validation.step"
export_ok = hfss.export_3d_model(
    file_name="PatchAntenna_Validation",
    file_path=r"D:\ANSYS-DEV\screenshots",
    file_format=".step"
)
hfss.save_project()

result = "STEP export: {}, size: {} bytes".format(
    export_ok, os.path.getsize(step_path) if os.path.exists(step_path) else 0
)
```

```
Response: STEP export: True, size: 30257 bytes
```

## 12. Clear AEDT (Optional)

**Tool:** `clear_aedt`

```
Response: AEDT state cleared. Closed 1 project(s).
```
