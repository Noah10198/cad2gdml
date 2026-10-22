# CAD2GDML

**CAD to GDML geometry conversion tool** — Convert CAD models into Geant4 simulation geometry (GDML) with mesh generation via GMSH.

> **Version 2.0.0** ｜ Chinese version: [README.zh.md](README.zh.md)


## Overview

CAD2GDML is a desktop GUI application that bridges CAD design and particle physics simulation. It imports CAD assembly files, displays them in a 3D OpenCASCADE viewer, generates finite-element meshes using GMSH, and exports the geometry in GDML format for use in Geant4-based simulation toolkits.

> **Platform note**: Currently developed and tested on **Windows**. Linux support will be verified in future releases.


## Features

- **CAD Import** — Load `.step` / `.stp` / `.brep` assemblies with a hierarchical tree and cross-session accumulation (`.iges` / `.igs` and `.stl` import is supported with limited functionality)
- **3D CAD Viewer** — PythonOCC-powered interactive 3D display with Lego-colored solids
- **Interference 1** — Exhaustive pairwise B-Rep check (`BRepExtrema_DistShapeShape` behind an OBB pre-filter), classified as Safe / Contact / Hard, with an embedded OCC preview of the selected pair
- **Interference 2** — Fast heuristic scan for large assemblies: an OBB + spatial-grid sweep enumerates candidate pairs and only the sampled top pairs are checked exactly (results are marked *sampled · for reference only*)
- **Transform Editing** — Move / rotate a single part or the whole import around the geometry centre or the world origin
- **Material Assignment** — Global and per-part material library with NIST reference materials, custom elements, compounds, and mixtures; batch assignment via multi-select
- **GMSH Meshing** — Background mesh generation (non-blocking) with configurable parameters (algorithm, element size factor, smoothing steps, element order) and adaptive sizing per bounding box; the toolbar Mesh button switches between **Mesh / Re-mesh / Cancel**, and Re-mesh re-runs a selected group of parts
- **Mesh Validation** — VTK-based mesh viewer with overlap extraction (Interference1) and distance heatmap tools
- **GDML Export** — Convert meshed geometry to Geant4 GDML format with tessellated solids, world volume, and NIST/custom material handling
- **VTK / MSH Export** — Export generated mesh files
- **Dark/Light Theme** — Full application theme toggle
- **Help** — In-app help / About dialog

### Supported Formats

| Format | Extension | Support Level |
|--------|-----------|--------------|
| STEP | `.step` / `.stp` | **Full** — Import, display, mesh, export |
| BREP | `.brep` | **Full** — Import, display, mesh, export |
| IGES | `.iges` / `.igs` | **Partial** — Import and display only; meshing not fully verified |
| STL | `.stl` | **Limited** — Import and display only; direct mesh extraction available |


## Requirements

| Dependency | Version |
|---|---|
| Python | >= 3.10 |
| PyQt6 | >= 6.4 |
| pythonocc-core | >= 7.6 |
| VTK | >= 9.2 |
| numpy | >= 1.21 |
| GMSH | >= 4.10 — bundled as `gmsh/gmsh.exe`, nothing to install |


## Installation

See the detailed installation guide at **[doc/installation.md](doc/installation.md)**.


## Usage

The workflow follows the pipeline order — import, check, assign materials, mesh, export:

1. **Import** — click **📂 Import CAD**; the assembly appears in the project tree and in the OCC viewer (imports accumulate across sessions).
2. **Interference** — **🔌 Interference 1** runs the exhaustive B-Rep check, **⚡ Interference 2** the fast sampled scan for large assemblies; both export their result table to CSV.
3. **Material** — **🧪 Material** assigns NIST or custom materials per part (multi-select) or globally.
4. **Mesh** — **🔧 Mesh** meshes the whole model, **🔁 Re-mesh** re-runs selected part groups, **⏹ Cancel** stops a running job; **👁 View Mesh** opens the VTK mesh viewer for validation.
5. **Export** — **📦 Export GDML** writes the tessellated GDML (world volume + materials), **📤 Export Mesh** writes the `.vtk` / `.msh` mesh files.

Double-click a part to inspect its properties and right-click it for transform editing; **❓ Help** opens the About dialog.


## Project Structure

```
  app/
    main_window.py          — Application main window, signal/slot wiring
  core/
    cad_reader.py           — Multi-format CAD import (STEP/IGES/BREP/STL)
    cad_process.py          — OCC shape processing helpers
    conformity.py           — Conformity verdict shared by mesh and export
    g_data_node.py          — Geometry data node tree model
    geo_data_agent.py       — Geometry data agent for inter-module communication
    gdml_generator.py       — GDML XML generation from meshed geometry
    import_worker.py        — Background CAD import thread
    lego_color_singleton.py — Lego-style color assignment for solids
    materials_lib.py        — NIST + custom element/compound/mixture library
    node_transform.py       — Node transform (move / rotate) support
  data/
    element.xml             — Periodic table (103 elements)
    nist.txt                — NIST material list
  doc/
    assembly_fragment_gdml.md  — Conformal (BooleanFragments) meshing + GDML plan
    assembly_fragment_ui.md    — Re-mesh scope UI design notes
    export_gdml.md          — GDML export guide
    import_geometry.md      — CAD import guide
    installation.md         — Installation guide
    interference_dialog.md  — Interference check dialog usage
    interference1_algorithm.md — Interference1 algorithm details
    interference2_algorithm.md — Interference2 algorithm details
    material_assignment.md  — Material assignment guide
    mesh.md                 — Mesh generation guide
    mesh_viewer.md          — Mesh viewer usage
  exampleSTEP/              — Sample STEP assemblies and demo tools
  fileio/                   — File I/O (placeholder)
  gmsh/                     — Bundled gmsh.exe
  icon/                     — Application icon (cad2gdml.svg)
  mesh/
    assembly_analysis.py    — Background contact analysis of the import
    gmsh_dialog.py          — Mesh parameter configuration dialog
    mesh_runner.py          — GMSH background thread (QProcess + .geo scripts)
    mesh_viewer.py          — VTK-based 3D mesh viewer (non-modal)
    remesh_scope_dialog.py  — Scope panel: groups, parameters, run progress
    scope.py                — Contact-graph grouping (the re-mesh units)
    vtk_tools.py            — Shared VTK helpers for the mesh viewer
  outputfile/               — Generated output files (VTK, MSH, GDML)
  test/                     — Mesh operation benchmark
  ui/
    toolbar.py              — Office-style ribbon toolbar
    project_tree.py         — Geometry hierarchy tree with visibility toggles
    occ_widget.py           — PythonOCC 3D display widget
    occ_preview.py          — Embedded OCC preview used by the interference dialogs
    geo_param_widget.py     — Property inspection panel
    import_progress.py      — Import progress dialog
    assign_material_dialog.py   — Per-part & batch material assignment
    local_material_dialog.py    — Custom element/compound/mixture editor
    export_gdml_dialog.py       — GDML export configuration dialog
    export_mesh_dialog.py       — Mesh file export dialog
    interference_dialog.py      — Interference 1 dialog (embedded OCC viewer)
    interference_dialog_v2.py   — Interference 2: sampled heuristic scan
    mesh_group_dialog.py        — Re-mesh group selection
    transform_dialog.py         — Move / rotate dialog
  utils/
    logger.py               — Async logger with signal-slot
    occ_quiet.py            — Suppresses OCC console noise
    task_manager.py         — Background task lifecycle manager
  environment.yml           — conda environment (name: pyoccenv)
  main.py                   — Application entry point
  README.md                 — This file
  README.zh.md              — Chinese version of this file
```


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


## Known Limitations

- **IGES** import is partial and its meshing path is not fully verified; **STL** is limited
  to display plus direct mesh extraction: STL has no B-Rep topology, so the whole file is
  merged into a single triangular shell.
- Unknown file extensions are rejected at import time.
- The IGES / STL limitations are enforced in `core/cad_reader.py`.
- Assembly (conformal) meshing relies on a single `BooleanFragments` pass; if that job
  fails the run degrades to a per-solid mesh, and the coincident contact faces may then be
  reported as overlaps by Geant4.
- The mesh overlap extraction reports at most 8 overlapping pairs.
- Meshing needs the bundled `gmsh/gmsh.exe`; only relative paths inside the module folder
  plus `PATH` are probed, so the folder layout must be preserved.
- CAD files of 4 MB and above are read in a child process with a 15-minute timeout.
- `fileio/` is an empty placeholder package.

## Development Notes

- **Threading**: `ImportWorker(QThread)` for CAD import, `MeshRunner(QThread)` for meshing,
  and a spawn child process (`core/cad_process.py`) for large CAD files, because
  `TransferRoots()` holds the GIL and would freeze the UI. Contact analysis
  (`mesh/assembly_analysis.py`) also runs in a spawn process polled by a `QTimer`.
- **GMSH invocation**: `QProcess` running `gmsh.exe <geo> -1` (non-interactive) with
  `MergedChannels`; output is parsed line by line for progress. The `.geo` script is
  generated from a template with the dialog parameters. The wait loop polls in 200 ms
  slices instead of one long `waitForFinished`, so **Cancel** stays responsive.
- **Mesh button state machine**: three states (mesh / re-mesh / cancel) driven by
  `RibbonToolbar.set_mesh_state()`; while a job runs the other buttons are disabled.
- **Singletons**: `TaskManager` and `LegoColorSingleton`.
- **OCC console noise**: `utils/occ_quiet.py` redirects stdout to `os.devnull` around the
  viewer-creation calls.

## Related Documents

- **Module documentation (`doc/`)**: [installation](doc/installation.md) ｜ [geometry import](doc/import_geometry.md) ｜ [mesh generation](doc/mesh.md) ｜ [mesh viewer](doc/mesh_viewer.md) ｜ [material assignment](doc/material_assignment.md) ｜ [GDML export](doc/export_gdml.md) ｜ [interference dialog](doc/interference_dialog.md) ｜ [Interference 1 algorithm](doc/interference1_algorithm.md) ｜ [Interference 2 algorithm](doc/interference2_algorithm.md) ｜ [re-mesh UI mockup](doc/remesh_ui_mockup.html)
- **Example assembly demo**: [exampleSTEP/merge_demo/README.md](exampleSTEP/merge_demo/README.md)
- Chinese version of this file: [README.zh.md](README.zh.md)


## License

[MIT](LICENSE) © ready2run

## Acknowledgments

- [OpenCASCADE Technology](https://dev.opencascade.org/) — CAD kernel
- [GMSH](https://gmsh.info/) — Finite element mesh generator
- [VTK](https://vtk.org/) — Visualization Toolkit
- [PythonOCC](https://github.com/tpaviot/pythonocc-core) — Python bindings for OCC
- [Geant4](https://geant4.web.cern.ch/) — GDML geometry format
- [CodeBuddy](https://www.codebuddy.ai/) & [DeepSeek](https://deepseek.com/) — AI-assisted development throughout this project
