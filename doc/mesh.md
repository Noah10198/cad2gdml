# Mesh Generation

## Overview

Mesh generation converts CAD solid bodies into finite-element tetrahedral meshes using **GMSH** (`gmsh.exe`). The process runs in a background thread, keeping the UI responsive.

---

## Workflow

```
Import CAD → [Mesh] → [Mesh Progress] → [View Mesh] / [Export Mesh]
                                ↓
                          [Export GDML]
```

### Step-by-Step

1. **Import** a CAD file (STEP / BREP).
2. Click **Mesh** on the Ribbon toolbar.
3. Configure mesh parameters in the dialog.
4. Click **OK** to start meshing.
5. A progress dialog shows the status.
6. When complete, use **View Mesh** to preview or **Export Mesh** to save `.vtk` files.

---

## Mesh Parameter Dialog

Clicking **Mesh** opens the **Mesh Generation Parameters** dialog:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| **Algorithm** | Combo | Frontal-Delaunay | Meshing algorithm: MeshAdapt (1), Automatic (2), Delaunay (5), Frontal-Delaunay (6) |
| **Element Size Factor** | Double | 1.0 | Global characteristic length factor — smaller = finer mesh |
| **Mesh Min Factor** | Double | 5.0 | Minimum element size = bounding box diagonal / this factor |
| **Mesh Max Factor** | Double | 6.0 | Maximum element size = bounding box diagonal / this factor |
| **Smoothing Steps** | Integer | 1 | Number of mesh smoothing iterations (0–100) |
| **Element Order** | Combo | 1st Order | 1st Order (linear) or 2nd Order (quadratic) elements |

---

## Meshing Process

### Background Execution

- The `MeshRunner` extends `QThread` and runs gmsh.exe via `QProcess`.
- It processes each solid body sequentially.

### Per-Solid Workflow

For each solid node:

1. **Export** the solid shape to a temporary `.step` file.
2. **Write** a `.geo` script with the selected mesh parameters.
3. **Launch** `gmsh.exe` with the `.geo` script:

```bash
gmsh.exe input.geo -  # generates .vtk, .msh output
```

4. **Read** the generated `.vtk` file back into the application.
5. **Register** the mesh file path with the solid node.

### .geo Script Template

```python
SetFactory("OpenCASCADE");
Merge "input.step";
Mesh.Algorithm = 6;           # Frontal-Delaunay
Mesh.Smoothing = 1;           # smoothing steps
Mesh.CharacteristicLengthFactor = 1.0;
Mesh.MeshSizeMin = 0.01;      # computed from bounding box
Mesh.MeshSizeMax = 0.1;       # computed from bounding box
Mesh.ElementOrder = 1;        # 1st Order
Mesh 2;                       # generate 2D (surface) mesh
Save "output.vtk";
Save "output.msh";
Exit;
```

### Progress Reporting

Progress is estimated per solid as a fraction of the total number of solids.

---

## Progress Dialog

The **Mesh Generation Progress** dialog is non-modal — you can continue interacting with the main window.

```
┌─────────────────────────────────────┐
│  Mesh Generation Progress           │
├─────────────────────────────────────┤
│  ████████░░░░░░░░░░░  45%           │
│  Meshing Bracket_Solid_1...         │
│                                     │
│  [View Mesh]                        │
└─────────────────────────────────────┘
```

- **Progress bar** shows overall completion across all solids.
- **Status label** shows the current solid being meshed.
- **View Mesh** button becomes enabled when meshing is complete.

---

## Viewing Mesh

Click **View Mesh** on the toolbar (or use the button in the progress dialog).

- Opens a **VTK mesh viewer** window (non-modal).
- Each mesh part is displayed with a distinct colour.
- The viewer includes:
  - 3D rotation / pan / zoom
  - Cube axes annotation
- Multiple viewer windows can be opened simultaneously for side-by-side comparison of different mesh parameters.

> **Note**: View Mesh requires meshed data. If no mesh has been generated, a warning is shown.

---

## Exporting Mesh

Click **Export Mesh** on the toolbar.

1. A folder selection dialog opens.
2. Meshed `.vtk` files are saved to the chosen folder.
3. The logger confirms: `"Mesh files exported to ..."`

> **Note**: Export requires meshed data. If meshing is still in progress, a warning is shown.

---

## GMSH Executable Location

The application searches for `gmsh.exe` in the following order:

1. `gmsh/` folder — place `gmsh.exe` inside this directory
2. System `PATH`

If `gmsh.exe` is not found, mesh generation will fail with an error message.
