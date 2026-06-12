# CAD2GDML

**CAD to GDML geometry conversion tool** — Convert CAD models into Geant4 simulation geometry (GDML) with mesh generation via GMSH.

---

## Overview

CAD2GDML is a desktop GUI application that bridges CAD design and particle physics simulation. It imports CAD assembly files, displays them in a 3D OpenCASCADE viewer, generates finite-element meshes using GMSH, and exports the geometry in GDML format for use in Geant4-based simulation toolkits.

> **Platform note**: Currently developed and tested on **Windows**. Linux support will be verified in future releases.

### Features

- **CAD Import** — Load `.step` / `.stp` / `.brep` assembly files with hierarchical tree structure (also supports `.iges` / `.igs` and `.stl` with limited functionality)
- **3D CAD Viewer** — PythonOCC-powered interactive 3D display with Lego-colored solids
- **GMSH Meshing** — Background mesh generation (non-blocking) with configurable parameters (algorithm, element size, smoothing, order)
- **Mesh Preview** — Standalone VTK mesh viewer window with cube axes annotation (non-modal, non-blocking)
- **GDML Export** — Convert meshed geometry to Geant4 GDML format *(in progress)*
- **VTK Export** — Export generated mesh files *(in progress)*
- **Dark/Light Theme** — Full application theme toggle
- **Material Assignment** — Global and per-part material library *(in progress)*

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
  app/            — Application logic (main window, signal wiring)
  core/           — Data models: GDataNode, GeoDataAgent, materials library
  data/           — Material library data (element.xml, nist.txt)
  doc/            — Documentation (installation, interference, algorithms)
  fileio/         — File export (GDML, VTK — in progress)
  mesh/           — Meshing subsystem
    gmsh_dialog.py    — Parameter configuration dialog
    mesh_runner.py    — GMSH background thread (QProcess + .geo scripts)
    mesh_progress.py  — Non-blocking progress dialog
    mesh_viewer.py    — VTK-based 3D mesh preview window
  outputfile/     — Generated output files (VTK, MSH, GDML)
  scripts/        — Utility scripts
  ui/             — Qt widgets
    toolbar.py        — Office-style ribbon toolbar (emoji icons)
    project_tree.py   — Geometry hierarchy tree with visibility toggles
    occ_widget.py     — PythonOCC 3D display widget
    geo_param_widget.py — Property inspection panel
  utils/          — AsyncLogger, TaskManager
  gmsh/           — Place gmsh.exe here
  _mesh_temp/     — Temporary meshing workspace (auto-cleaned)
  environment.yml       — Minimal environment definition
  environment_full.yml  — Full environment export
  requirements.txt
  main.py         — Application entry point
  README.md       — This file
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        MainWindow                                 │
│  ┌─────────┐ ┌──────────┐ ┌────────────┐ ┌───────────┐ ┌──────┐ │
│  │ Toolbar │ │Project   │ │   OCC      │ │Interference│ │Prop  │ │
│  │(Ribbon) │ │Tree      │ │  Viewer    │ │  Dialog   │ │Panel │ │
│  └─────────┘ └──────────┘ └────────────┘ └───────────┘ └──────┘ │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                      System Log                           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                     +                                              │
│  MeshRunner (QThread) → gmsh.exe → .vtk files                      │
│                     +                                              │
│  MeshViewer (QDialog) → QVTKRenderWindowInteractor                  │
└──────────────────────────────────────────────────────────────────┘
```

All mesh generation runs in a background `QThread` to keep the UI responsive. The VTK mesh viewer opens as a non-modal dialog (like MATLAB figure popups), allowing interaction with the main window while viewing meshes.

### Import Pipeline

```
CAD File (.step/.stp/.brep/.iges/.igs/.stl)
        │
        ▼
   pythonocc-core (OCCT) — B-Rep or mesh data extraction
        │
        ▼
   Project Tree (geometry hierarchy)
        │
        ├──► OCC Viewer (3D display)
        ├──► Interference Check (pairwise B-Rep distance)
        └──► MeshRunner → GMSH → GDML / VTK Export
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
