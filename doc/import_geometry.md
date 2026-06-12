# Import Geometry

## File Formats

Click the **Import CAD** button on the Ribbon toolbar to open a file dialog. The following formats are supported:

| Format | Extension | Notes |
|--------|-----------|-------|
| STEP | `.step` / `.stp` | Best support — preserves assembly hierarchy |
| BREP | `.brep` / `.brp` | Full support, single or compound shapes |
| IGES | `.iges` / `.igs` | Import and display only |
| STL | `.stl` | Import and display only |

Multiple files can be selected and imported at once.

---

## Import Workflow

1. Click **Import CAD** on the toolbar.
2. Select one or more CAD files in the file dialog.
3. A progress dialog shows 3 stages:
   - **Reading files** (0–85%) — OCCT reads each file and extracts all solid bodies
   - **Building project tree** (86%) — Tree hierarchy is populated
   - **Rendering geometry** (90–100%) — Each solid is added to the 3D viewer with a random Lego-style color and 40% transparency
4. When complete, the geometry appears in both the **3D Viewer** and the **Project Tree**.

---

## Project Tree

The project tree (left panel) has three root nodes:

```
Project Tree
├── Global Materials     — NIST standard materials (G4_*) loaded from data/nist.txt
├── Local Materials      — User-defined materials (compounds, mixtures, custom elements)
└── Geometry             — Imported CAD file hierarchy
    ├── my_part.step
    │   ├── Bracket_Solid_1
    │   └── Shaft_Solid_2
    └── another_file.brep
        └── Body_Solid_1
```

### Tree Nodes

- **File nodes** (e.g. `my_part.step`) — Represent each imported file. Named after the filename.
- **Solid nodes** (e.g. `Bracket_Solid_1`) — Leaf nodes containing actual geometry shapes. Named in the pattern `{FileName}_{Type}_{Index}`.
- Each solid node has a **checkbox** to toggle visibility in the 3D viewer.
- Right-click on a **Local Materials** node to:
  - **Add Material...** — Create a new custom material
  - **Save Materials...** — Export all local materials to a JSON file
  - **Load Materials...** — Load local materials from a JSON file

### Tree Behaviour

- If total parts ≤ 20, the tree expands fully by default.
- Otherwise, only file-level nodes are expanded.

---

## 3D Viewer Interaction

The OCC 3D Viewer (center panel) supports:

| Action | Result |
|--------|--------|
| Left mouse drag | Rotate view |
| Middle mouse scroll | Zoom in/out |
| Middle mouse drag | Pan |

---

## Property Panel

The property panel (right dock) shows detailed information about the selected item.

### Geometry Mode (selected solid)

| Section | Fields |
|---------|--------|
| **General** | Name, Type, Entry ID |
| **Position** | Center coordinates (X, Y, Z) |
| **Bounding Box** | Min / Max X, Y, Z (read-only) |
| **Dimensions** | Size (DX, DY, DZ), approximate volume |
| **Material** | Currently assigned material name |

### Global Material Mode (selected NIST material)

| Section | Fields |
|---------|--------|
| **General** | Name, Symbol, Atomic number, Atomic mass |

### Local Material Mode (selected user-defined material)

| Section | Fields |
|---------|--------|
| **General** | Name, Type |
| **Material Details** | Density, Symbol, Atomic number, Atomic mass, chemical composition table (element, proportion, Z) |
