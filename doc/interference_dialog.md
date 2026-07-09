# Interference Dialog

## Overview

**Interference Dialog** is a CAD-level B-Rep interference check dialog. For every pair of solid bodies in an imported STEP model, it computes the exact geometric distance and classifies the result into three categories, displayed in a color-coded table. Clicking any row opens an embedded OCC 3D preview of the selected pair.

## Opening

1. Import a STEP file containing at least 2 solid bodies
2. Click the **`⚡ Interference`** button on the Ribbon toolbar
3. The dialog opens and automatically starts checking all pairs

## Layout

```
┌─────────────────────────────────────────────────────┐
│  ■ Hard: 3  ■ Contact: 1  ■ Safe: 45               │  ← summary bar
├──────────────────┬──────────────────────────────────┤
│  ■ Hard Inter.  │  ■ │ Part A      │ Part B  │ Dist│
│   PartA ↔ PartB  │  ──┼─────────────┼─────────┼─────┤
│   Min dist: 0.00 │  ■ │ Bracket_L   │ Bracket_R│Over │
│                  │  ■ │ Shaft       │ Housing  │0.03 │
│  ┌──────────┐    │  ...                             │
│  │ OCC 3D   │    │                                   │
│  │ Preview  │    │                                   │
│  └──────────┘    │                                   │
├──────────────────┴──────────────────────────────────┤
│  [⟳ Re-check]  [⊞ Fit Preview]  [⬇ Export Table]  ... [Close]
└─────────────────────────────────────────────────────┘
```

### Left — OCC 3D Preview
- Fixed 360×360 px square viewport
- Displays the two selected bodies in semi-transparent blue
- For Hard Interference, the intersection region is highlighted with **thick red curves** (12 px wireframe)
- A static hint label sits above the viewport: *"Select a row to preview the pair"* — its background matches the OCC backdrop (`#14141F`)
- Mouse controls: **Left-click drag = rotate**, **Middle-click drag = pan**, **Scroll wheel = zoom**

### Right — Results Table

| Column | Meaning |
|--------|---------|
| `■` | Status indicator: red = Hard, yellow = Contact, green = Safe |
| Part A | Name of the first body |
| Part B | Name of the second body |
| Distance | Minimum distance (mm): "Overlap" for Hard, numeric value for Safe/Contact |

Row background colours provide additional visual cues:
- Red tint = Hard
- Yellow tint = Contact
- Green tint = Safe

### Summary Bar
The top bar shows aggregated counts with coloured `■` (U+25A0 black square) markers and the total elapsed time.

### Bottom Button Bar

| Button | Action |
|--------|--------|
| ⟳ Re-check | Re-runs interference detection on all pairs |
| ⊞ Fit Preview | Fits the 3D preview to show all displayed shapes |
| ⬇ Export Table | Opens a **Save As** dialog to export the table as CSV |
| Close | Closes the dialog |

## Export Table

Clicking **⬇ Export Table** opens a `QFileDialog.getSaveFileName()` dialog pre-populated with `interference_report.csv` in the **same directory as the last STEP import**.

The exported CSV uses `utf-8-sig` encoding (BOM) so Excel opens it correctly on all locales. Columns:

| Column | Content |
|--------|---------|
| Status | `Hard` / `Contact` / `Safe` / `Unknown` |
| Part A | First body name |
| Part B | Second body name |
| Distance (mm) | Numeric value, `Overlap`, or `—` |

## Classification Algorithm

### Threshold

```python
CONTACT_THRESHOLD = 0.0000001  # mm
```

**To modify**: edit the constant at the top of `ui/interference_dialog.py`:

```
ui/interference_dialog.py  →  CONTACT_THRESHOLD = 0.1
```

This value is shared by V1 (`InterferenceDialog`) and V2 (`InterferenceDialogV2`, which imports it at `interference_dialog_v2.py:25`). Changing it in one place updates both versions automatically.

### Decision Logic

```
distance > 0.1 mm  ──────────────────────────────→ Safe
0.0001 < distance ≤ 0.1 mm  ────────────────────→ Contact
distance ≈ 0  → run Section boolean intersection
    ├── intersection edges/faces found  ─────────→ Hard
    └── no intersection geometry  ───────────────→ Contact
```

### Implementation

1. **`BRepExtrema_DistShapeShape`** — OCC exact distance computation for initial classification
2. **`BRepAlgoAPI_Section`** — when the distance is near zero, performs boolean intersection to distinguish volumetric overlap (Hard) from surface tangency (Contact)
3. All computation is performed at the B-Rep level — **no meshing required**, precision is the CAD kernel's machine tolerance

## 3D Preview Rendering

| Element | Colour | Transparency | Display Mode |
|---------|--------|-------------|--------------|
| Body A | Blue `BLUE1` | 0.55 (45 %) | Shaded |
| Body B | Blue `BLUE1` | 0.55 (45 %) | Shaded |
| Hard intersection | Red `NOC_RED` | Opaque | **WireFrame** (12 px line width) |

Semi-transparent blue allows both bodies to be seen simultaneously; the thick red curves (12 px, controlled via `Prs3d_LineAspect`) clearly mark the overlapping boundary.

## Cleanup on Close

When the dialog or the main window closes, the OCC display context is properly shut down and the OpenGL window binding is released (`View.Remove()` + `Context.RemoveAll`), preventing `wglMakeCurrent()` "invalid handle" errors.

## Dependencies

| Module | Purpose |
|--------|---------|
| `BRepExtrema_DistShapeShape` | Exact distance computation |
| `BRepAlgoAPI_Section` | Boolean intersection |
| `AIS_Shape` / `AIS_WireFrame` | 3D display primitives |
| `Prs3d_LineAspect` | Line width control |
| `PyQt6.QtWidgets` | GUI framework |
| `csv` (stdlib) | CSV export |
