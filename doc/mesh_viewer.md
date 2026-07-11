# Mesh Viewer

## Overview

**Mesh Viewer** is a standalone, non-blocking 3D mesh preview window powered by VTK (`QVTKRenderWindowInteractor`). It appears after mesh generation completes, allowing users to visually inspect the resulting tetrahedral meshes, detect interferences, and evaluate mesh quality.

The window is **non-modal** — the main application remains fully interactive while the viewer is open, and multiple viewer instances may be opened simultaneously for side-by-side comparison of different mesh parameters.

## Opening

1. Complete mesh generation via **Mesh** on the Ribbon toolbar
2. Click **View Mesh** (in the progress dialog, or on the toolbar)

Alternatively, the viewer can load `.vtk` files directly via `MeshViewer.load_mesh_files()`.

---

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Mesh Preview                                  [_][□][×]    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                    VTK 3D Viewport                          │
│                (QVTKRenderWindowInteractor)                 │
│                                                             │
│    [Gmsh Parameters overlay — top-left corner]              │
│    [Cube Axes — outer edges]                                │
│    [Scalar Bar — right edge (distance mode only)]           │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ Mesh loaded: 3 file(s), 245,832 cells                       │
│ [▣ Transparency] [✕ Edges] [✂ Clip] [⚡ Interference1]     │
│ [🌈 Distance] [⌂ Fit All] [◻ Ortho] [X] [Y] [Z]    [Close]│
├─────────────────────────────────────────────────────────────┤
│ (Clip panel — shown when ✂ Clip is active)                  │
│ Clip → [X-Axis ▼] [═══════●═══════] 500.00  [Reset]         │
├─────────────────────────────────────────────────────────────┤
│ (Collision panel — shown after Interference1 runs)          │
│ ⚡ Interference1: 2 pair(s)                        [✕ Hide] │
└─────────────────────────────────────────────────────────────┘
```

### Toolbar Buttons

| Button | State | Description |
|--------|-------|-------------|
| ▣ Transparency | Toggle | Switches between opaque (Solid) and 45% transparent mesh with light cyan edges |
| ✕ Edges | Toggle (default: on) | Shows/hides mesh edge lines (dark gray, 1.0 px) |
| ✂ Clip | Toggle | Enables/disables the clipping plane. Expands a second toolbar row with axis selector and position slider |
| ⚡ Interference1 | Toggle | Runs mesh-level overlap detection. Results are displayed as red overlay patches |
| 🌈 Distance | Toggle | Colors mesh vertices by their minimum distance to any other mesh (blue→red heatmap) |
| ⌂ Fit All | Action | Resets the camera to frame all meshes |
| ◻ Ortho | Toggle | Switches between orthographic and perspective projection |
| X / Y / Z | Radio | Snaps camera to axis-aligned orthographic view from +X, +Y, or +Z |
| Close | Action | Closes the viewer window |

---

## B. Clipping Plane

Allows slicing through the mesh to inspect internal structure and element quality.

### Controls

- **Axis selector** — X-Axis, Y-Axis, or Z-Axis
- **Slider** — 0–1000 range, maps linearly from the mesh's minimum to maximum coordinate along the selected axis
- **Position label** — shows the current clip plane coordinate (in model units)
- **Reset** — returns the slider to the mid-point of the current axis

### Implementation

A single `vtkPlane` object is shared across all mesh actors via `vtkMapper.AddClippingPlane()`. The plane origin and normal are updated on each slider move. No geometry is modified — the clip is purely visual.

---

## C. Interference1 — Clip-Based Overlap Detection

Detects and visualizes overlapping regions between meshed parts. For a full algorithm description, see [`interference1_algorithm.md`](interference1_algorithm.md).

### Quick Summary

| Stage | Method | Purpose |
|-------|--------|---------|
| AABB Pre-filter | Axis-aligned bounding box overlap test | Eliminate distant pairs instantly |
| Signed distance clipping | `vtkImplicitPolyDataDistance` + `vtkClipPolyData` | Extract the portion of mesh A that lies inside mesh B (and vice versa) |

### Visualization

- Overlap regions rendered as **bright red** `(1.0, 0.15, 0.15)`, 70% opacity, with visible red edges
- Overlaid on top of the semi-transparent original meshes (transparency is auto-enabled on activation)
- A report panel below the toolbar displays the count of intersecting pairs

### Tolerance

A dynamic tolerance of 0.3% of the model bounding-box diagonal is computed during mesh load. The clip boundary is set at distance = 0 (exact mesh surface).

### Usage

1. Load at least two meshed parts in the viewer
2. Click **⚡ Interference1** (toggle on)
3. Overlapping regions appear as red patches
4. Use **✕ Hide / ◉ Show** in the collision panel to toggle visibility of the overlap overlay
5. Click **⚡ Interference1** again (toggle off) to clear results and restore original appearance

---

## D. Distance Map

Colors each mesh vertex according to its **minimum signed distance** to the surface of any other mesh in the scene. This provides an intuitive heatmap of part proximity.

### Algorithm

For each vertex on mesh A, compute `abs(vtkImplicitPolyDataDistance.EvaluateFunction(vertex))` against every other mesh B, C, ... and take the minimum. The absolute value of the signed distance is used, so both internal and external proximity are captured.

### Colormap

| Property | Value |
|----------|-------|
| Lookup table | `vtkLookupTable` — 256 table values |
| Hue range | 0.667 (blue) → 0.0 (red) |
| Saturation | 1.0 |
| Value (brightness) | 1.0 |
| Scalar bar | `vtkScalarBarActor`, title "Distance", 5 labels, right edge of viewport |

- **Blue** = distant from all other parts
- **Red** = very close to (or touching) another part

### Usage

1. Load at least two meshed parts in the viewer
2. Click **🌈 Distance** (toggle on)
3. Mesh surfaces are recolored with the distance heatmap
4. A scalar bar appears on the right edge of the viewport
5. The info label updates to show the distance range
6. Click again (toggle off) to restore original mesh colors

---

## Interference2 (Removed)

**Interference2**, which used `vtkIntersectionPolyDataFilter` and `vtkDecimatePro` to extract intersection contour lines, has been removed from the Mesh Viewer UI. The algorithm code is retained in the codebase for reference (see [`interference2_algorithm.md`](interference2_algorithm.md)), but the toolbar button no longer appears.

Only **Interference1** and **Distance Map** remain as actively supported mesh inspection tools.

---

## Default Mesh Appearance

| Property | Value |
|----------|-------|
| Face color | Slate-blue `(0.35, 0.65, 0.80)` |
| Edge color | Dark gray `(0.1, 0.1, 0.1)` |
| Edge line width | 1.0 px (edges visible by default) |
| Ambient | 0.15 |
| Diffuse | 0.8 |
| Specular | 0.05 |
| Background | Dark blue-gray `(0.2, 0.25, 0.3)` |

---

## Gmsh Parameters Overlay

A `vtkCornerAnnotation` in the top-left corner of the viewport displays the mesh generation parameters used:

```
Gmsh Parameters
  Algorithm: Frontal-Delaunay
  Order: 1  |  Smooth: 1
  Elem Factor: 1.0
  Min/Max: 5.0 / 6.0
```

Text is white on a semi-transparent dark background (opacity 0.7), non-interactive.

---

## Cube Axes

A `vtkCubeAxesActor` is displayed at the outer edges of the mesh bounding box. Axes are color-coded:
- X-axis: red
- Y-axis: green
- Z-axis: blue

Axes use "fly mode" (outer edges only) to avoid cluttering the center of the viewport.

---

## Dependencies (VTK Classes)

| Class | Module | Role |
|-------|--------|------|
| `QVTKRenderWindowInteractor` | `vtkmodules.qt` | Qt-wrapped VTK OpenGL window |
| `vtkUnstructuredGridReader` | `vtkIOLegacy` | Read `.vtk` unstructured grid files |
| `vtkGeometryFilter` | `vtkFiltersGeometry` | Convert unstructured grid → polygonal surface |
| `vtkPolyDataNormals` | `vtkFiltersCore` | Compute consistent surface normals |
| `vtkPolyDataMapper` | `vtkRenderingCore` | Map polygonal data to renderable primitives |
| `vtkActor` | `vtkRenderingCore` | 3D renderable object |
| `vtkRenderer` | `vtkRenderingCore` | Scene renderer |
| `vtkPlane` | `vtkCommonDataModel` | Clipping plane geometry |
| `vtkImplicitPolyDataDistance` | `vtkFiltersCore` | Signed distance field (Interference1 + Distance) |
| `vtkClipPolyData` | `vtkFiltersCore` | Clip mesh by implicit function (Interference1) |
| `vtkLookupTable` | `vtkCommonCore` | Colormap (Distance) |
| `vtkScalarBarActor` | `vtkRenderingAnnotation` | Colormap legend (Distance) |
| `vtkCubeAxesActor` | `vtkRenderingAnnotation` | Bounding box coordinate axes |
| `vtkCornerAnnotation` | `vtkRenderingAnnotation` | Text overlay (mesh parameters) |
| `vtkInteractorStyleTrackballCamera` | `vtkInteractionStyle` | Mouse-based 3D navigation |

## External References

- [interference1_algorithm.md](interference1_algorithm.md) — Full Interference1 algorithm details
- [interference2_algorithm.md](interference2_algorithm.md) — Interference2 code reference (UI removed)
- [mesh.md](mesh.md) — Mesh generation workflow and GMSH parameters
