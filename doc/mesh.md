# Mesh Generation

## Overview

Mesh generation tessellates the **surfaces** of CAD solid bodies into triangles using **GMSH**
(the `gmsh` Python package). It is a 2D surface mesh (`mesh.generate(2)`), not a tetrahedral
volume mesh. The process runs in a background thread, keeping the UI responsive.

> **File format is not the mesh type.** The `.vtk` files are written as legacy
> `DATASET UNSTRUCTURED_GRID` because that is what gmsh emits and what
> `vtkUnstructuredGridReader` reads, but every cell in them is a triangle
> (`CELL_TYPES = 5`); there are no tetrahedra anywhere in the pipeline. `vtkGeometryFilter`
> is used in the readers only to turn that container back into `vtkPolyData`.
>
> `core/gdml_generator.py` reads those triangles and writes one GDML `<tessellated>` solid per
> part, so each part's facets must be **closed** (every edge shared by exactly two triangles,
> see `mesh/vtk_tools.check_closed`) and **consistently oriented** — `G4TessellatedSolid`
> decides inside/outside from the facet normals, so a flipped patch turns into a phantom
> Overlap in Geant4. Finer triangles buy accuracy; closedness and orientation decide whether
> the geometry is usable at all.

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
| **Mesh Min Factor** | Double | 6.0 | Minimum element size = bounding box diagonal / this factor (must be >= Max Factor) |
| **Mesh Max Factor** | Double | 5.0 | Maximum element size = bounding box diagonal / this factor |
| **Smoothing Steps** | Integer | 1 | Number of mesh smoothing iterations (0–100) |
| **Element Order** | Combo | 1st Order | 1st Order (linear) or 2nd Order (quadratic) elements |

---

## Meshing Modes

Two modes exist. The mode is chosen automatically from the contact analysis that runs right
after import (`mesh/assembly_analysis.py`), not by the user:

| Mode | How it works | When it is used |
|------|--------------|-----------------|
| **Per-solid** | One STEP file and one gmsh worker process per solid body. Both sides of a contact face get their own facet set, so coincident facets remain and Geant4 may report false Overlaps. | A single solid, or an assembly whose contact analysis failed. |
| **Assembly (conformal)** | All solids are merged into one gmsh session and a single `BooleanFragments` genuinely splits the touching faces, so both sides share the same topology and only one set of interface facets remains. The resulting triangles are then reassigned back to their original solids. | Two or more solids with touching contact faces. |

A failed assembly job is never a dead end: every failing step **degrades to per-solid
meshing** and the result is marked *non-conformal*, which the GDML export dialog gates on.
A degraded run reports at most the first 8 contact pairs.

## Meshing Process

### Background Execution

- The `MeshRunner` extends `QThread` and runs `mesh/gmsh_worker.py` via `QProcess`,
  started with the application's own interpreter (`sys.executable`).
- Per-solid mode runs one worker process per body, sequentially; assembly mode runs a single
  job for the whole group.
- Timeout: 3 minutes per solid, 15 minutes for a single assembly job.
- The wait loop polls in 200 ms slices instead of one long `waitForFinished`, so **Cancel**
  stays responsive.

### Per-Solid Workflow

For each solid node:

1. **Export** the solid shape to a temporary `.step` file.
2. **Write** a job description (`.json`) with the selected mesh parameters.
3. **Run** the worker on it:

```bash
python -u mesh/gmsh_worker.py input.json  # writes the .vtk / .msh named in the job
```

4. **Read** the generated `.vtk` file back into the application.
5. **Register** the mesh file path with the solid node.

### Job Description

The job file holds only paths and numbers; `mesh/gmsh_worker.py` turns it into gmsh API
calls. A per-solid job:

```json
{
  "steps": ["input.step"],
  "outputs": ["output.vtk", "output.msh"],
  "fragment": false,
  "algorithm": 6,
  "smoothing": 1,
  "elem_factor": 1.0,
  "size_min": 0.01,
  "size_max": 0.1,
  "order": 1
}
```

which the worker executes as:

```python
gmsh.model.occ.importShapes("input.step")
gmsh.model.occ.synchronize()
gmsh.option.setNumber("Mesh.Algorithm", 6)               # Frontal-Delaunay
gmsh.option.setNumber("Mesh.Smoothing", 1)
gmsh.option.setNumber("Mesh.CharacteristicLengthFactor", 1.0)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.01)          # from bounding box
gmsh.option.setNumber("Mesh.MeshSizeMax", 0.1)           # from bounding box
gmsh.option.setNumber("Mesh.ElementOrder", 1)
gmsh.model.mesh.generate(2)                              # surface mesh, no volume
gmsh.write("output.vtk")
gmsh.write("output.msh")
```

### Assembly Job

One job for the whole group: every STEP file is imported, then `fragment: true` runs a single
`BooleanFragments` that splits the contact faces, and the same options are applied:

```python
for step in ["solid_1.step", "solid_2.step"]:
    gmsh.model.occ.importShapes(step)
gmsh.model.occ.synchronize()
gmsh.model.occ.fragment(gmsh.model.getEntities(3), [])
gmsh.model.occ.synchronize()
```

The mesh size factors come from the **overall** bounding box, because the whole group is a
single gmsh job.

### Progress Reporting

Per-solid mode estimates progress as a fraction of the total number of solids. Assembly mode
reports stage ranges instead: contact analysis 0–18 %, Boolean fragment + assembly meshing
18–60 %, triangle reassignment 60–100 %.

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

## GMSH Installation

Meshing uses the `gmsh` **Python package** only — no executable is required:

```bash
pip install gmsh          # or: conda install -c conda-forge gmsh
```

The wheel contains the whole kernel (`libgmsh` / `gmsh.dll`) with OpenCASCADE support, so
the same code runs on Windows, macOS and Linux. If the package is missing from the active
environment, the mesh button logs `Python package 'gmsh' not found` and stops.

The worker is a child process on purpose: a running gmsh solve cannot be interrupted from
inside the process, so Cancel and the timeout can only kill it.
