# Installation Guide

## Environment Overview

CAD2GDML depends on the following key components:

| Dependency | Version | Installation Method |
|------------|---------|---------------------|
| Python | >= 3.9 (recommended 3.10) | conda |
| PyQt6 | >= 6.4 | conda / pip |
| pythonocc-core | >= 7.6 (recommended 7.9.0) | conda-forge |
| VTK | >= 9.2 (recommended 9.3.1) | conda-forge |
| numpy | >= 1.21 | automatic dependency |
| gmsh (Python package) | >= 4.10 | pip |

> **Recommendation**: Use conda to manage the environment. The pip wheels for `pythonocc-core` and `VTK` have poor compatibility on Windows. conda-forge provides fully pre-compiled binaries for a more reliable installation.

---

## Method 1: Using the Provided Environment File (Recommended)

`environment.yml` contains the core dependencies of this module. It is fast to install and `conda env create` resolves every transitive dependency from conda-forge.

### Steps

```bash
# 1. Create environment from environment.yml
conda env create -f environment.yml

# 2. Activate the environment
conda activate pyoccenv
```

> **Windows note**: Use **Anaconda PowerShell Prompt** (not the regular cmd or PowerShell) to run conda commands. Regular command prompts may not recognize `conda`. You can find "Anaconda PowerShell Prompt" in the Start Menu after installing Anaconda / Miniconda.

### What's Included

`environment.yml` already contains:
- Python 3.10
- pythonocc-core 7.9.0 (includes OCCT 7.9.0)
- VTK 9.3.1
- PyQt6 6.4.2
- gmsh (Python package, includes the full meshing kernel — no separate executable)

> **Note**: `conda env create` automatically resolves all transitive dependencies (e.g. numpy, OpenGL libraries) from conda-forge — no need to install them manually.

---

## Method 2: Manual Setup (Fully Customizable)

If you prefer to set up step by step, or you already have a conda environment:

> **Windows note**: Use **Anaconda PowerShell Prompt** (Start Menu → "Anaconda PowerShell Prompt") for all conda commands below.

```bash
# 1. Create a fresh environment
conda create -n pyoccenv python=3.10
conda activate pyoccenv

# 2. Install core dependencies
conda install -c conda-forge pythonocc-core=7.9.0 vtk=9.3.1

# 3. Install remaining packages via pip
pip install PyQt6==6.4.2 gmsh

# 4. Verify installation
python -c "import OCC.Core; import vtk; import PyQt6; import gmsh; print('OK')"
```

---

## GMSH

Meshing uses the `gmsh` Python package only. The pip wheel ships the complete
kernel (`libgmsh` / `gmsh.dll`) with OpenCASCADE support, so no `gmsh.exe`
download, PATH entry or bundled binary is needed. Wheels exist for Windows,
macOS (Intel and Apple Silicon) and Linux, and the same environment file works
on all three:

```bash
pip install gmsh          # or: conda install -c conda-forge gmsh
python -c "import gmsh; gmsh.initialize(); print(gmsh.__version__); gmsh.finalize()"
```

---

## Verifying the Installation

```bash
conda activate pyoccenv
cd <path-to-cad2gdml>
python main.py
```

If the GUI starts successfully, the installation is complete.

---

## Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| `ImportError: No module named OCC` | pythonocc-core not installed | `conda install -c conda-forge pythonocc-core` |
| `Python package 'gmsh' not found` | gmsh not installed in the active env | `pip install gmsh` in that environment |
| `Qt platform plugin` error | PyQt6 incompatible with system | Reinstall: `pip install --force-reinstall PyQt6` |
| Slow conda solve | Package resolution | Use `conda env create -f environment.yml` instead |
