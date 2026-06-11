"""
MeshRunner - Non-blocking GMSH mesh generation in a background thread.

Uses gmsh.exe directly (matching the C++ reference approach):
  1. Write each solid as a .step file
  2. Write a .geo script with mesh parameters
  3. Launch gmsh.exe to generate the mesh
  4. Read back the .vtk output
"""

import os
import re
import json
from typing import Optional, List

from PyQt6.QtCore import QThread, pyqtSignal, QProcess

from core.g_data_node import GDataNode

# ---- .geo script template (same structure as C++ MeshGen.h) ----
# %1 = input STEP path
# %2 = Mesh.Algorithm
# %3 = Mesh.Smoothing
# %4 = Mesh.CharacteristicLengthFactor  (NOT ElementSizeFactor - that's GMSH 2.x only)
# %5 = Mesh.MeshSizeMin
# %6 = Mesh.MeshSizeMax
# %7 = Mesh.ElementOrder
# %8 = output VTK path

GEO_TEMPLATE = (
    'SetFactory("OpenCASCADE");\n'
    'Merge "%1";\n'
    'Mesh.Algorithm = %2;\n'
    'Mesh.Smoothing = %3;\n'
    'Mesh.CharacteristicLengthFactor = %4;\n'
    'Mesh.MeshSizeMin = %5;\n'
    'Mesh.MeshSizeMax = %6;\n'
    'Mesh.ElementOrder = %7;\n'
    'Mesh 2;\n'
    'Save "%8";\n'
    'Save "%9";\n'
    'Exit;\n'
)


# ---- Auto-detect gmsh.exe ----

def find_gmsh_exe() -> Optional[str]:
    """Locate gmsh.exe. Checks: project gmsh/, 3rd_app/, and PATH."""
    candidates = [
        # User's gmsh folder (inside codebuddy-2st/)
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "gmsh", "gmsh.exe"),
        # From C++ reference: ../3rd_app/gmsh.exe
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "..", "3rd_app", "gmsh.exe"),
        # From sourcecode output
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "..", "sourcecode", "output", "3rd_app", "gmsh.exe"),
    ]
    # Also check PATH
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    # Fallback: try PATH
    import shutil
    return shutil.which("gmsh.exe") or shutil.which("gmsh")


class MeshRunner(QThread):
    """Generate meshes for geometry nodes using gmsh.exe in background."""

    progress_updated = pyqtSignal(int, str)
    log_emitted = pyqtSignal(str)
    finished_with_result = pyqtSignal(bool, dict, str)

    def __init__(self, nodes: List[GDataNode], work_dir: str,
                 algorithm: int = 6,
                 elem_factor: float = 1.0,
                 mesh_min_factor: float = 5.0,
                 mesh_max_factor: float = 6.0,
                 smoothing: int = 1,
                 order: int = 1,
                 parent=None):
        super().__init__(parent)
        self._nodes = nodes
        self._work_dir = work_dir
        self._algorithm = algorithm
        self._elem_factor = elem_factor
        self._mesh_min_factor = mesh_min_factor
        self._mesh_max_factor = mesh_max_factor
        self._smoothing = smoothing
        self._order = order
        self._cancelled = False

        # Locate gmsh.exe
        self._gmsh_exe = find_gmsh_exe()
        if self._gmsh_exe:
            self.log_emitted.emit(f"[GMSH] Using: {self._gmsh_exe}")

    def cancel(self):
        self._cancelled = True

    # ---------------------------------------------------------------

    def run(self):
        if not self._nodes:
            self.finished_with_result.emit(False, {}, "No nodes to mesh.")
            return

        if not self._gmsh_exe:
            self.log_emitted.emit(
                "[ERROR] gmsh.exe not found. Place it in codebuddy-2st/gmsh/ "
                "or add to PATH."
            )
            self.finished_with_result.emit(False, {}, "gmsh.exe not found.")
            return

        os.makedirs(self._work_dir, exist_ok=True)
        mesh_paths: dict = {}
        total = len(self._nodes)

        self.log_emitted.emit("=== GMSH Meshing Started ===")

        for idx, node in enumerate(self._nodes):
            if self._cancelled:
                self.log_emitted.emit("Meshing cancelled by user.")
                self.finished_with_result.emit(False, mesh_paths, "Cancelled.")
                return

            shape = node.shape
            if shape is None or shape.IsNull():
                self.log_emitted.emit(
                    f"[SKIP] {node.name}: no valid shape, skipping."
                )
                continue

            node_label = node.name or node.entry_id
            pct = int((idx / total) * 85)

            try:
                safe_name = self._safe_id(node.entry_id, idx)
                step_file = os.path.join(self._work_dir, f"{safe_name}_in.step")
                geo_file = os.path.join(self._work_dir, f"{safe_name}.geo")
                vtk_file = os.path.join(self._work_dir, f"{safe_name}.vtk")
                msh_file = os.path.join(self._work_dir, f"{safe_name}.msh")

                self.log_emitted.emit(f"[{idx+1}/{total}] Preparing {node_label} ...")
                self.progress_updated.emit(pct, f"Writing STEP for {node_label}...")

                # 1. Write shape as STEP file
                self._write_shape_to_step(shape, step_file)

                # 2. Compute bounding box for size factors
                diag = self._compute_diagonal(shape)
                size_min = diag / self._mesh_min_factor if self._mesh_min_factor > 0 else 0.001
                size_max = diag / self._mesh_max_factor if self._mesh_max_factor > 0 else 1.0

                self.log_emitted.emit(
                    f"  Algorithm={self._algorithm}, "
                    f"SizeMin={size_min:.4f}, SizeMax={size_max:.4f}, "
                    f"CharLengthFactor={self._elem_factor}, Order={self._order}"
                )

                # 3. Write .geo script
                geo_content = GEO_TEMPLATE.replace("%1", step_file) \
                    .replace("%2", str(self._algorithm)) \
                    .replace("%3", str(self._smoothing)) \
                    .replace("%4", str(self._elem_factor)) \
                    .replace("%5", str(size_min)) \
                    .replace("%6", str(size_max)) \
                    .replace("%7", str(self._order)) \
                    .replace("%8", vtk_file) \
                    .replace("%9", msh_file)

                with open(geo_file, "w", encoding="utf-8") as f:
                    f.write(geo_content)

                self.progress_updated.emit(pct + 3, f"Running GMSH on {node_label}...")
                self.log_emitted.emit(f"  Generating mesh for {node_label} ...")

                # 4. Launch gmsh.exe with the .geo script
                ok, gmsh_stdout = self._run_gmsh(geo_file)

                # 5. Forward GMSH output to log
                if gmsh_stdout:
                    for line in gmsh_stdout.split("\n"):
                        line = line.strip()
                        if line:
                            self.log_emitted.emit(f"  [GMSH] {line}")

                # 6. Check result
                if ok and os.path.exists(vtk_file) and os.path.getsize(vtk_file) > 0:
                    node.mesh_file_name = vtk_file
                    mesh_paths[node.entry_id] = vtk_file
                    # Quick VTK file read to get stats
                    n_elems, n_nodes = self._quick_vtk_stats(vtk_file)
                    self.log_emitted.emit(
                        f"  -> {node_label}: {n_elems:e} element(s), {n_nodes} node(s)"
                    )
                else:
                    self.log_emitted.emit(
                        f"  [ERROR] {node_label}: GMSH did not produce valid output"
                    )

                # Clean up temp files
                try:
                    os.remove(step_file)
                except Exception:
                    pass
                try:
                    os.remove(geo_file)
                except Exception:
                    pass

            except Exception as e:
                self.log_emitted.emit(f"  [ERROR] {node_label}: {e}")
                continue

            self.progress_updated.emit(pct + 5, f"Done: {node_label}")

        # Summary
        self.log_emitted.emit("=== GMSH Meshing Complete ===")
        success = len(mesh_paths) > 0
        if success:
            msg = f"Mesh ready. {len(mesh_paths)} of {total} nodes meshed successfully."
        else:
            msg = f"Meshing failed. 0 of {total} nodes meshed."
        self.progress_updated.emit(100, msg)
        self.finished_with_result.emit(success, mesh_paths, msg)

    # ---------------------------------------------------------------

    def _run_gmsh(self, geo_file: str):
        """Run gmsh.exe on a .geo script file and return (ok, stdout_text)."""
        proc = QProcess()
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setWorkingDirectory(self._work_dir)

        args = [geo_file, "-1"]  # -1 = non-interactive mode (same as C++ reference)
        proc.start(self._gmsh_exe, args)

        # Wait for process to finish (3 min timeout, matching C++ reference)
        if not proc.waitForFinished(3 * 60 * 1000):
            proc.kill()
            return False, ""

        stdout = proc.readAllStandardOutput().data().decode("utf-8", errors="replace")
        exit_code = proc.exitCode()

        return exit_code == 0, stdout

    # ---------------------------------------------------------------

    @staticmethod
    def _quick_vtk_stats(vtk_path: str):
        """Read a legacy VTK file to get rough element and node counts."""
        n_elems = 0
        n_nodes = 0
        try:
            with open(vtk_path, "r") as f:
                for line in f:
                    line = line.strip().lower()
                    if line.startswith("points "):
                        parts = line.split()
                        if len(parts) >= 2:
                            n_nodes = int(parts[1])
                    elif line.startswith("cells "):
                        parts = line.split()
                        if len(parts) >= 2:
                            n_elems = int(parts[1])
        except Exception:
            pass
        return n_elems, n_nodes

    @staticmethod
    def _safe_id(entry_id: str, index: int) -> str:
        safe = entry_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", safe)
        return f"{safe}_{index}"

    @staticmethod
    def _write_shape_to_step(shape, path: str):
        from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
        writer = STEPControl_Writer()
        writer.Transfer(shape, STEPControl_AsIs)
        writer.Write(path)

    @staticmethod
    def _compute_diagonal(shape) -> float:
        try:
            from OCC.Core.Bnd import Bnd_Box
            from OCC.Core.BRepBndLib import brepbndlib
            bbox = Bnd_Box()
            brepbndlib.Add(shape, bbox)
            x_min, y_min, z_min, x_max, y_max, z_max = bbox.Get()
            dx = x_max - x_min
            dy = y_max - y_min
            dz = z_max - z_min
            return (dx * dx + dy * dy + dz * dz) ** 0.5
        except Exception:
            return 10.0
