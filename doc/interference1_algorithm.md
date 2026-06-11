# Interference1 Algorithm

## Overview

**Interference1** is a mesh-based interference (overlap) detection algorithm for CAD parts that have been discretized into unstructured (tetrahedral) grids. It not only detects *whether* two parts interfere, but also **extracts and visualizes the actual overlapping mesh regions**.

## Algorithm Pipeline

```
Mesh A (PolyData) ──┐
                    ├── Stage 1: AABB Overlap Filter
Mesh B (PolyData) ──┘         │
                              ▼
                         Pass? ──No──→ No interference
                              │
                             Yes
                              │
                              ▼
           ┌──────────────────┼──────────────────┐
           │                                      │
    Stage 2a: Clip A by B's              Stage 2b: Clip B by A's
    Signed Distance                       Signed Distance
   (vtkClipPolyData +                    (vtkClipPolyData +
    vtkImplicitPolyDataDistance)          vtkImplicitPolyDataDistance)
           │                                      │
           ▼                                      ▼
   Region of A inside B                 Region of B inside A
   (colored red, opacity=0.7)           (colored red, opacity=0.7)
```

## Stage 1 — AABB Bounding Box Overlap (Fast Filter)

For each pair of meshes, their **axis-aligned bounding boxes (AABB)** are compared. If the bounding boxes do not intersect in all three axes (X, Y, Z), the pair is trivially rejected without further computation.

This filter eliminates distant part pairs instantly.

```
AABB overlap ⇔  (bx1_min ≤ bx2_max) ∧ (bx1_max ≥ bx2_min)
               ∧ (by1_min ≤ by2_max) ∧ (by1_max ≥ by2_min)
               ∧ (bz1_min ≤ bz2_max) ∧ (bz1_max ≥ bz2_min)
```

## Stage 2 — Clipping via Signed Distance Field

For each pair that passes the AABB test:

### Step 2a: Clip Mesh A with Mesh B's Signed Distance

1. Construct a `vtkImplicitPolyDataDistance` function from Mesh B. This function evaluates the **signed distance** of any query point to the surface of Mesh B:
   - Positive → outside Mesh B
   - Zero → on the surface of Mesh B
   - Negative → inside Mesh B

2. Use `vtkClipPolyData` with `InsideOutOn` to **keep only the portion of Mesh A that lies inside Mesh B** (i.e., where the signed distance < 0).

   The clip boundary is the exact surface of Mesh B, so the extracted region is Mesh A's geometry that penetrates into Mesh B.

### Step 2b: Clip Mesh B with Mesh A's Signed Distance

The same operation is performed in reverse: Mesh B is clipped against Mesh A's signed distance field to extract the portion of Mesh B that is inside Mesh A.

### Visualization

Both clipped regions are rendered as **bright red, semi-transparent (opacity=0.7) mesh surfaces with visible edges**, overlaid on top of the original semi-transparent meshes. This clearly shows:

- **Where** the overlap occurs (spatial location)
- **What shape** the overlap region has (the actual geometry of the penetration)
- **Which mesh** contributes to the overlap on each side

## Key Characteristics

### Advantages
- **Robust**: `vtkClipPolyData` with an implicit distance function is numerically stable even on coarse or non-manifold CAD meshes (unlike `vtkIntersectionPolyDataFilter` which often segfaults)
- **Fast**: The AABB pre-filter eliminates distant pairs; the clipping operation is O(N) per mesh
- **Informative**: Shows the actual overlapping surface region, not just discrete points
- **Bidirectional**: Extracts overlap from both sides (A-in-B and B-in-A)

### Limitations
- For **open surfaces** (e.g., thin plates, shells without thickness), the concept of "inside" is ambiguous, and the signed distance may produce false positives on the back side
- The clipped result is an approximation at the mesh resolution — it won't show smooth intersection curves unless the mesh is sufficiently fine

### Tolerance
A dynamic tolerance of 0.3% of the model diagonal is computed during mesh load. The clip value is set to 0.0 (exact surface boundary), and the signed distance itself provides the penetration measure.

## Dependencies (VTK Classes)

| Class | Role |
|-------|------|
| `vtkImplicitPolyDataDistance` | Computes signed distance from a point to a polygonal mesh surface |
| `vtkClipPolyData` | Clips polygonal data using an implicit function |
| `vtkPolyDataNormals` | Pre-computes consistent point normals for the distance function |
| `vtkGeometryFilter` | Converts unstructured grids to polygonal data |

## Usage

In the Mesh Preview window:

1. Load two or more meshed CAD parts
2. Click the **`⚡ Interference1`** button
3. The overlapping regions will appear as red surfaces
4. Use **`✕ Hide / ◉ Show`** to toggle the overlap overlay visibility
5. The report panel displays the count of intersecting pairs and overlapping cell counts
