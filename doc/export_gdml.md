# Export GDML

## Overview

**Export GDML** converts meshed geometry parts into a standard GDML (Geometry Description Markup Language) file suitable for Geant4 or SERad simulations. The exported file contains tessellated solid geometries, material references, and a world volume enclosing all parts.

## Prerequisites

Before the GDML export dialog can be opened, three conditions must be met:

- **Material Assignment** — All parts must have a material assigned via the Materials button. Any unassigned parts are listed in a warning dialog and block the export.
- **Meshing Complete** — Every part must have a corresponding VTK mesh file. The export checks that mesh files exist and are non-empty.
- **No Active Meshing** — If a meshing operation is still in progress, the export is blocked until it finishes.

## Opening

1. Load a STEP file with at least one solid body
2. Assign materials to all parts
3. Run Meshing to generate VTK files
4. Click the **Export GDML** button on the toolbar
5. The export configuration dialog opens (non-modal)

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Preview                                  │  World Volume    │
│  ┌──────────────────────┐                │  Factor: [× 5 ▼] │
│  │                      │                │  World: 50.0×50.0│
│  │  3D OCC Viewport     │                │    ×50.0 mm      │
│  │  (blue transparent   │                │                 │
│  │   parts + gray       │                │  World Material  │
│  │   wireframe box)     │                │  [G4_AIR    ▼] ✓ │
│  │                      │                │                 │
│  │                      │                │  Output File     │
│  │                      │                │  [out/exportgdml/│
│  │                      │                │   export.gdml]   │
│  └──────────────────────┘                │  [Browse...]     │
│                                           │                 │
│                                           │ [Fit View]      │
│                                           │ [Export GDML]   │
│                                           │ [Cancel]        │
└───────────────────────────────────────────┴─────────────────┘
```

### Left — OCC 3D Preview

- Displays all geometry parts as **blue semi-transparent** solids
- World volume shown as a **gray wireframe** box
- Preview updates in real time when the Factor is changed
- Mouse controls: **Left-click drag = rotate**, **Middle-click drag = pan**, **Scroll wheel = zoom**

### Right — Controls

#### World Volume

The world volume is a cubic box centered at the **origin (0, 0, 0)**. It acts as the outermost volume in the GDML hierarchy, containing all part volumes as physical volumes.

**Factor** — Multiplier applied to the global bounding-box max-edge:

| Factor | World Half-Size | Use Case |
|--------|----------------|----------|
| × 3    | 1.5 × maxEdge | Tight fit when parts nearly fill the simulation volume |
| × 5    | 2.5 × maxEdge | **Default** — balanced margin for most use cases |
| × 10   | 5.0 × maxEdge | Generous margins for particle tracking clearance |
| × 100  | 50.0 × maxEdge | Very large world for debugging or large sensitive volumes |

> **Note:** `maxEdge` is the largest span (X, Y, or Z) of the global bounding box of all parts. The world box is always a cube of side length `factor × maxEdge`.

#### World Material

| Component | Description |
|-----------|-------------|
| Dropdown   | `G4_AIR` (default), `G4_Galactic` |
| Manual entry | Any material name — real-time validator checks local library and NIST global database (**case-sensitive**) |
| Validation | `✓ known` / `✓ global` / `✓ local` / `⚠ not found` shown in real time |

Only **local/custom** materials appear in the GDML `<materials>` block. NIST global materials (`G4_*`) are built into Geant4 and omitted.

#### Output File

```
<project>/outputfile/exportgdml/export.gdml
```

- Default path: `outputfile/exportgdml/export.gdml` (relative to project root)
- Before each export, the entire `exportgdml/` directory is **cleared and recreated**
- Use **Browse...** to select a different location

## Generated GDML Structure

```
<gdml>
  <define>           ── Vertex positions (one <position> per vertex)
  <materials>        ── Local/custom material definitions only
  <solids>           ── WorldBox + <tessellated> solids for each part
  <structure>        ── Part volumes + worldVOL (materialref + solidref)
  <setup>            ── World reference (ref="worldVOL")
```

### World Volume Center

The world box is a cube centered at the origin `(0, 0, 0)`, spanning from `(-half, -half, -half)` to `(half, half, half)`, where `half = factor × maxEdge / 2`. Geometry parts retain their original positions from the STEP model.

## Workflow Summary

1. Load geometry and assign materials
2. Run Meshing to generate VTK files
3. Click **Export GDML** on the toolbar
4. Adjust world factor and material as needed
5. Click **Export GDML** to generate the file

## Dependencies

| Module | Purpose |
|--------|---------|
| `OCC.Core.BRepPrimAPI` | World box solid creation |
| `AIS_Shape` / `AIS_WireFrame` | 3D preview rendering |
| `PyQt6.QtWidgets` | GUI framework |
| `vtk` | VTK mesh file reading |
| `xml.etree.ElementTree` | GDML XML generation |
| `shutil` | Export directory cleanup |
