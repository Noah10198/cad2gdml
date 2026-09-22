# CAD2GDML

**CAD to GDML geometry conversion tool** — Convert CAD models into Geant4 simulation geometry (GDML) with mesh generation via GMSH.

---

## Overview

CAD2GDML is a desktop GUI application that bridges CAD design and particle physics simulation. It imports CAD assembly files, displays them in a 3D OpenCASCADE viewer, generates finite-element meshes using GMSH, and exports the geometry in GDML format for use in Geant4-based simulation toolkits.

> **Platform note**: Currently developed and tested on **Windows**. Linux support will be verified in future releases.

### Features

- **CAD Import** — Load `.step` / `.stp` / `.brep` assembly files with hierarchical tree structure and cross-session accumulation (also supports `.iges` / `.igs` and `.stl` with limited functionality)
- **3D CAD Viewer** — PythonOCC-powered interactive 3D display with Lego-colored solids
- **Interference Check** — Pairwise B-Rep interference detection with OBB pre-filtering, three-category classification (Safe / Contact / Hard), and two sampling modes (Fast / Full)
- **Material Assignment** — Global and per-part material library with NIST reference materials, custom elements, compounds, and mixtures; batch assignment via multi-select
- **GMSH Meshing** — Background mesh generation (non-blocking) with configurable parameters (algorithm, element size factor, smoothing steps, element order); adaptive sizing per bounding box
- **Mesh Validation** — VTK-based mesh viewer with overlap extraction (Interference1) and distance heatmap tools
- **GDML Export** — Convert meshed geometry to Geant4 GDML format with tessellated solids, world volume, and NIST/custom material handling
- **VTK / MSH Export** — Export generated mesh files
- **Dark/Light Theme** — Full application theme toggle

### Supported Formats

| Format | Extension | Support Level |
|--------|-----------|--------------|
| STEP | `.step` / `.stp` | **Full** — Import, display, mesh, export |
| BREP | `.brep` / `.brp` | **Full** — Import, display, mesh, export |
| IGES | `.iges` / `.igs` | **Partial** — Import and display only; meshing not fully verified |
| STL | `.stl` | **Limited** — Import and display only; direct mesh extraction available |

### Screenshots

*(Coming soon)*

---

## Requirements

| Dependency | Version |
|---|---|
| Python | >= 3.9 |
| PyQt6 | >= 6.4 |
| pythonocc-core | >= 7.6 |
| VTK | >= 9.2 |
| numpy | >= 1.21 |
| GMSH (executable) | >= 4.10 |

---

## Installation

See the detailed installation guide at **[doc/installation.md](doc/installation.md)**.

---

## Project Structure

```
  app/
    main_window.py          — Application main window, signal/slot wiring
  core/
    cad_reader.py           — Multi-format CAD import (STEP/IGES/BREP/STL)
    g_data_node.py          — Geometry data node tree model
    geo_data_agent.py       — Geometry data agent for inter-module communication
    gdml_generator.py       — GDML XML generation from meshed geometry
    import_worker.py        — Background CAD import thread
    lego_color_singleton.py — Lego-style color assignment for solids
    materials_lib.py        — NIST + custom element/compound/mixture library
  data/
    element.xml             — Periodic table (103 elements)
    nist.txt                — NIST material list
  doc/
    assembly_fragment_gdml.md — Conformal (BooleanFragments) meshing + GDML plan
    export_gdml.md          — GDML export guide
    import_geometry.md      — CAD import guide
    installation.md         — Installation guide
    interference_dialog.md  — Interference check dialog usage
    interference1_algorithm.md — Interference1 algorithm details
    interference2_algorithm.md — Interference2 algorithm details
    material_assignment.md  — Material assignment guide
    mesh.md                 — Mesh generation guide
    mesh_viewer.md          — Mesh viewer usage
  fileio/                   — File I/O (placeholder)
  gmsh/                     — Bundled gmsh.exe
  mesh/
    gmsh_dialog.py          — Mesh parameter configuration dialog
    mesh_runner.py          — GMSH background thread (QProcess + .geo scripts)
    mesh_viewer.py          — VTK-based 3D mesh viewer (non-modal)
    scope.py                — Contact-graph grouping (the re-mesh units)
    remesh_scope_dialog.py  — Scope panel: groups, parameters, run progress
    assembly_analysis.py    — Background contact analysis of the import
    conformity.py           — Conformity verdict shared by mesh and export
  outputfile/               — Generated output files (VTK, MSH, GDML)
  ui/
    toolbar.py              — Office-style ribbon toolbar
    project_tree.py         — Geometry hierarchy tree with visibility toggles
    occ_widget.py           — PythonOCC 3D display widget
    geo_param_widget.py     — Property inspection panel
    import_progress.py      — Import progress dialog
    assign_material_dialog.py   — Per-part & batch material assignment
    local_material_dialog.py    — Custom element/compound/mixture editor
    export_gdml_dialog.py       — GDML export configuration dialog
    export_mesh_dialog.py       — Mesh file export dialog
    interference_dialog.py      — Interference check dialog (OCC viewer)
    interference_dialog_v2.py   — Interference check v2 (standalone)
  utils/
    logger.py               — Async logger with signal-slot
    task_manager.py         — Background task lifecycle manager
  _mesh_temp/               — Temporary meshing workspace (auto-cleaned)
  environment.yml           — Minimal conda environment
  environment_full.yml      — Full conda environment export
  main.py                   — Application entry point
  README.md                 — This file
```

---

## Architecture

The software follows a pipeline-based architecture that processes CAD geometry through four stages: Import → Material → Mesh → Export.

```
┌──────────────────────────────────────────────────────────────────────┐
│                          MainWindow                                   │
│  ┌──────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌───────┐ │
│  │  Ribbon  │ │  Project   │ │    OCC     │ │Interfere │ │Property│ │
│  │  Toolbar │ │   Tree     │ │  Viewer    │ │  Dialog  │ │ Panel  │ │
│  └──────────┘ └────────────┘ └────────────┘ └──────────┘ └───────┘ │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     System Log                                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

  Pipeline Stages (non-blocking, background threads):

  ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌───────────┐
  │  Import   │───▶│  Material    │───▶│   Mesh   │───▶│  Export   │
  │  Worker   │    │  Assignment  │    │  Runner  │    │  Dialog   │
  └──────────┘    └──────────────┘    └──────────┘    └───────────┘
       │                 │                 │                 │
       ▼                 ▼                 ▼                 ▼
  CAD File→OCC    NIST / Custom       GMSH .exe         GDML XML
   B-Rep tree     material lib        (QProcess)        tessellated
```

All mesh generation runs in a background `QThread` to keep the UI responsive. The file dialogs (material, mesh, export) open as non-modal dialogs.

### Modules

```
                ┌───────────────────┐
                │   app/main_window │  ← Signal/slot orchestration
                └────────┬──────────┘
                         │
      ┌──────────────────┼──────────────────────┐
      ▼                  ▼                      ▼
┌──────────┐    ┌──────────────┐       ┌──────────────┐
│   core/  │    │     ui/      │       │    mesh/     │
│ data     │    │ Qt dialogs   │       │ GMSH process │
│ models   │    │ OCC viewer   │       │ VTK viewer   │
│ materials│    │ project tree │       │ mesh preview │
└──────────┘    └──────────────┘       └──────────────┘
                     │                       │
                     ▼                       ▼
              ┌──────────────┐       ┌──────────────┐
              │ interference │       │  outputfile/  │
              │  dialogs     │       │ .vtk/.msh/.gdml
              └──────────────┘       └──────────────┘
```

### Processing Pipeline

```
STEP / IGES / BREP / STL
        │
        ▼
   cad_reader.py — OCC B-Rep extraction
        │
        ▼
   Project Tree — geometry hierarchy (GDataNode)
        │
        ├──► OCC Viewer (3D display, lego coloring)
        ├──► Interference Check (OBB pre-filter + BRepExtrema)
        ├──► Material Assignment (NIST library / custom composition)
        ├──► MeshRunner → GMSH (.geo script → .vtk)
        │       └──► MeshViewer (VTK 3D preview, validation tools)
        └──► GDML Generator (tessellated solids → .gdml)
                └──► Export dialog (world box, material config)
```

---

## License

[MIT](LICENSE) © ready2run

---

## Acknowledgments

- [OpenCASCADE Technology](https://dev.opencascade.org/)
- [GMSH](https://gmsh.info/) — Finite element mesh generator
- [VTK](https://vtk.org/) — Visualization Toolkit
- [PythonOCC](https://github.com/tpaviot/pythonocc-core)
- [Geant4](https://geant4.web.cern.ch/) — GDML geometry format
- [CodeBuddy](https://www.codebuddy.ai/) & [DeepSeek](https://deepseek.com/) — AI-assisted development throughout this project
