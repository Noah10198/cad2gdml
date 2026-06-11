# Interference2 Algorithm

## Overview

**Interference2** extracts the **intersection contour lines** between two meshed CAD parts. Unlike Interference1 which shows overlapping *surface regions*, Interference2 draws the **exact boundary curves** where the two meshes intersect.

```
Mesh A ──┐
         ├── Stage 1: AABB filter (same as Interference1)
Mesh B ──┘      │
                ▼
           Pass? ──No──→ No intersection
                │
               Yes
                │
                ▼
    ┌──────────────────────────┐
    │  Try Method A            │
    │  vtkIntersectionPolyData │
    │  Filter (exact)          │
    │                          │
    │  Success? ──Yes──→ Use it│
    │     │                   │
    │    No                    │
    │     │                   │
    │     ▼                    │
    │  Method B (fallback)     │
    │  vtkCutter + Signed     │
    │  Distance Field          │
    └──────────────────────────┘
                │
                ▼
      Intersection contour lines
      (cyan/green, 3px thick)
```

## Method A: `vtkIntersectionPolyDataFilter` (Exact)

This VTK filter computes the **exact triangle-triangle intersection** between two polygonal meshes and outputs the intersection line segments.

### Input Requirements (critical)

Failure to meet any of these will cause `GetStatus() == 0` (failure) or produce incorrect results:

#### 1. Input type: `vtkPolyData` (surface mesh) only
- **Cannot accept** `vtkUnstructuredGrid` (volume mesh)
- If working with volume models, first extract surface via `vtkDataSetSurfaceFilter`

#### 2. All cells must be triangles
- Quadrilaterals, polygons with >3 edges, or mixed cell types will cause errors
- Must pass through `vtkTriangleFilter` first (already in pipeline)

#### 3. Avoid coplanar overlapping faces
- Large coplanar/coincident face regions between two meshes cause intersection line confusion
- `vtkIntersectionPolyDataFilter` does **not** support 2D boolean operations
- If coplanar overlap is detected (status=0), the code automatically falls back to Method B (Cutter)

#### 4. Pre-clean the mesh
- Always use `vtkCleanPolyData` to remove duplicate points and degenerate cells
- Redundant/corrupted vertices slow down computation and may cause wrong results

#### 5. Check `GetStatus()` after computation
- `status == 1` → success, use the result
- `status == 0` → failure (likely coplanar faces, missing normals, or corrupt cells)
- Code will automatically fall back to Method B on failure

#### 6. Normal vector consistency (especially for non-closed surfaces)
- Non-closed/open surfaces often have missing, flipped, or inconsistent normals
- The pipeline enforces `vtkPolyDataNormals` with `AutoOrientNormalsOn` + `ConsistencyOn`
- Additionally enables `CheckInput` and `CheckMesh` parameters on the filter for validation

### Preprocessing Pipeline

```
Raw Mesh (poly_i/poly_j)
    │
    ▼
vtkCleanPolyData
    │  Remove duplicate points, degenerate cells
    ▼
vtkTriangleFilter
    │  Convert all polygons to triangles
    ▼
vtkPolyDataNormals
    │  AutoOrientNormals + Consistency (fixes non-closed surfaces)
    ▼
vtkIntersectionPolyDataFilter
    ├── SetCheckInput(True)   ← validates input structure
    ├── SetCheckMesh(True)    ← validates mesh integrity
    └── Update()
         │
         ▼
    GetStatus() == 1? ──Yes──→ Output intersection lines
         │
        No (status=0)
         │
         ▼
    Fallback to Method B
```

### Output

- A `vtkPolyData` containing only **line cells** (`VTK_LINE`) at the exact intersection
- Each line segment lies exactly on both mesh surfaces

### Known Issues

- May fail (status=0) on **coplanar overlapping faces** (automatically falls back to Cutter)
- Can produce fragmented line segments if meshes have poor triangle quality
- Both meshes must be triangulated beforehand (always true in our pipeline)

## Method B: `vtkCutter` + `vtkImplicitPolyDataDistance` (Stable Fallback)

If `vtkIntersectionPolyDataFilter` fails, this method provides a robust alternative.

### Approach

1. Construct a `vtkImplicitPolyDataDistance` function from Mesh B — computes the signed distance of any point to Mesh B's surface
2. Use `vtkCutter` to **cut Mesh A at distance = 0** from Mesh B's surface (extracts the contour polyline where Mesh A crosses Mesh B's boundary)
3. Repeat in reverse: cut Mesh B with Mesh A's distance field
4. Merge both contour sets into one polyline dataset

### Output

- Contour polylines approximating the intersection curve
- Less precise than Method A, but numerically stable on all mesh types

### Advantages

- **Will not crash** — `vtkCutter` with an implicit function is highly robust
- Works on non-manifold, open, and coarse meshes
- Captures intersection even when mesh quality is poor
- No input type restrictions (except must be `vtkPolyData`)

## Visualization

All extracted contour lines are rendered as:
- **Color**: Cyan/green `(0.0, 1.0, 0.8)`
- **Line width**: 3.0 pixels (visible against both light and dark backgrounds)
- **Opacity**: 0.95

The original meshes are set to semi-transparent so the contour lines inside/behind the parts remain visible.

## Comparison: Interference1 vs Interference2

| Feature | Interference1 | Interference2 |
|---------|---------------|---------------|
| Output type | Red surface patches (clipped overlap) | Cyan contour lines (intersection curves) |
| Algorithm | `vtkClipPolyData` + signed distance | `vtkIntersectionPolyDataFilter` / `vtkCutter` |
| Precision | Approximate (mesh resolution) | Exact (Method A) or approximated (Method B) |
| Robustness | Very robust | Method A may fail; Method B is robust |
| Input constraints | Few (just `vtkPolyData`) | Many (triangles, no coplanar overlap, normals OK) |
| Best for | Seeing *where* and *how much* overlap | Seeing the *exact boundary* of intersection |

## Dependencies (VTK Classes)

| Class | Role | Module |
|-------|------|--------|
| `vtkIntersectionPolyDataFilter` | Exact triangle-triangle intersection line extraction | `vtkFiltersGeneral` |
| `vtkCutter` | Cut mesh with implicit function to extract contour lines | `vtkFiltersCore` |
| `vtkImplicitPolyDataDistance` | Signed distance field used as cut function | `vtkFiltersCore` |
| `vtkCleanPolyData` | Remove duplicate points before intersection | `vtkFiltersCore` |
| `vtkTriangleFilter` | Ensure all polygons are triangles | `vtkFiltersCore` |
| `vtkPolyDataNormals` | Consistent normal orientation for non-closed surfaces | `vtkFiltersCore` |

## Input Constraints Summary (for Method A)

| Constraint | Solution in code | Status |
|------------|-----------------|--------|
| Input must be `vtkPolyData` | Already `vtkPolyData` from mesh loading | ✓ |
| All cells must be triangles | `vtkTriangleFilter` | ✓ |
| Remove duplicate points | `vtkCleanPolyData` | ✓ |
| Consistent normals | `vtkPolyDataNormals` | ✓ |
| Enable CheckInput / CheckMesh | `SetCheckInput(True)`, `SetCheckMesh(True)` | ✓ |
| Check `GetStatus()` | Checked after `Update()` | ✓ |
| Coplanar overlap fallback | Automatically falls back to Method B | ✓ |

## Usage

1. Load two or more meshed CAD parts
2. Click **`⚡ Interference2`** button
3. Cyan/green contour lines appear at the intersection boundaries
4. The report panel shows which method was used per pair (`IntersectionFilter` or `Cutter`)
5. If `IntersectionFilter` fails (status=0), the report shows the failure reason and fallback
6. Toggle visibility with **`✕ Hide / ◉ Show`**
