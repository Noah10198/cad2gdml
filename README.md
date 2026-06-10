# CAD2GDML

**STEP to GDML geometry conversion tool** — Convert CAD models (STEP) into Geant4 simulation geometry (GDML) with mesh generation via GMSH.

---

## Overview

CAD2GDML is a desktop GUI application that bridges CAD design and particle physics simulation. It imports STEP assembly files, displays them in a 3D OpenCASCADE viewer, generates finite-element meshes using GMSH, and exports the geometry in GDML format for use in Geant4-based simulation toolkits.

### Features

- **STEP Import** — Load `.step` / `.stp` assembly files with hierarchical tree structure
- **3D CAD Viewer** — PythonOCC-powered interactive 3D display with Lego-colored solids
- **GMSH Meshing** — Background mesh generation (non-blocking) with configurable parameters (algorithm, element size, smoothing, order)
- **Mesh Preview** — Standalone VTK mesh viewer window with cube axes annotation (non-modal, non-blocking)
- **GDML Export** — Convert meshed geometry to Geant4 GDML format *(in progress)*
- **VTK Export** — Export generated mesh files *(in progress)*
- **Dark/Light Theme** — Full application theme toggle
- **Material Assignment** — Global and per-part material library *(in progress)*

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

### 1. Create a Conda environment (recommended)

```bash
conda create -n cad2gdml python=3.10
conda activate cad2gdml
```

### 2. Install Python dependencies

```bash
pip install -r codebuddy-2st/requirements.txt
```

Note: Both `pythonocc-core` and `VTK` provide pre-built wheels. On Windows, `conda install -c conda-forge pythonocc-core vtk` is an alternative if pip fails.

### 3. Obtain GMSH

- Download `gmsh-4.10.0-Windows64.zip` from [gmsh.info](https://gmsh.info)
- Extract `gmsh.exe` to `codebuddy-2st/gmsh/` OR add it to your system PATH

### 4. Run

```bash
cd codebuddy-2st
python main.py
```

---

## Project Structure

```
codebuddy-2st/
  app/            — Application logic (main window, signal wiring)
  core/           — Data models: GDataNode, GeoDataAgent, materials library
  fileio/         — File export (GDML, VTK stubs)
  mesh/           — Meshing subsystem
    gmsh_dialog.py    — Parameter configuration dialog
    mesh_runner.py    — GMSH background thread (QProcess + .geo scripts)
    mesh_progress.py  — Non-blocking progress dialog
    mesh_viewer.py    — VTK-based 3D mesh preview window
  ui/             — Qt widgets
    toolbar.py        — Office-style ribbon toolbar (emoji icons)
    project_tree.py   — Geometry hierarchy tree with visibility toggles
    occ_widget.py     — PythonOCC 3D display widget
    geo_param_widget.py — Property inspection panel
  utils/          — AsyncLogger, TaskManager
  gmsh/           — Place gmsh.exe here
  _mesh_temp/     — Temporary meshing workspace (auto-cleaned)
  requirements.txt
  main.py         — Application entry point
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  MainWindow                      │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌──────┐  │
│  │ Toolbar │ │Project   │ │ OCC    │ │Prop  │  │
│  │(Ribbon) │ │Tree      │ │Viewer  │ │Panel │  │
│  └─────────┘ └──────────┘ └────────┘ └──────┘  │
│  ┌──────────────────────────────────────────┐   │
│  │            System Log                     │   │
│  └──────────────────────────────────────────┘   │
│                     +                            │
│  MeshRunner (QThread) → gmsh.exe → .vtk files    │
│                     +                            │
│  MeshViewer (QDialog) → QVTKRenderWindowInteractor│
└─────────────────────────────────────────────────┘
```

All mesh generation runs in a background `QThread` to keep the UI responsive. The VTK mesh viewer opens as a non-modal dialog (like MATLAB figure popups), allowing interaction with the main window while viewing meshes.

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
