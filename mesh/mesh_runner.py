"""
MeshRunner - Non-blocking GMSH mesh generation in a background thread.

Two meshing modes (chosen automatically by the "contact analysis" run after
import, see mesh/assembly_analysis.py):

  per_solid  per-solid meshing (original behaviour)
             One STEP and one gmsh process per solid.
             Both parts on a contact face get their own facet set -> coincident
             facets > 0 -> false Geant4 Overlaps.

  assembly   assembly conformal meshing
             Merge all solids into one gmsh session, then run a single
             BooleanFragments. Contact faces are genuinely split and both sides
             share the same topology, so only one set of interface facets remains.
             After meshing the triangles must be "reassigned" back to the
             original solids, otherwise GDML cannot tell which triangle belongs
             to which <tessellated>.

Failure of assembly mode is never a dead end: any failing step **degrades to
per-solid meshing**, and the result is marked "non-conformal" so the export
dialog can gate it.
"""

import os
import re
import time
from typing import List, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal, QProcess

from core.conformity import (
    AnalysisResult, MeshOutcome, CONFORMAL, NON_CONFORMAL, PARTIAL,
)
from core.g_data_node import GDataNode
from mesh.vtk_tools import (
    assign_owners, bbox_of, build_parts, check_closed,
    count_coincident_facets, read_vtk, write_vtk,
)

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

# ---- Assembly conformal template ----
# Merge can be called repeatedly, so there is no need to build a real multi-body
# STEP: merging several STEP files into one session in turn is equivalent
# (see merge_demo/README.md).
ASSEMBLY_HEAD = 'SetFactory("OpenCASCADE");\n'
ASSEMBLY_MERGE = 'Merge "%s";\n'
ASSEMBLY_FRAGMENT = 'BooleanFragments{ Volume{:}; Delete; }{ }\n'
ASSEMBLY_TAIL = (
    'Mesh.Algorithm = %s;\n'
    'Mesh.Smoothing = %s;\n'
    'Mesh.CharacteristicLengthFactor = %s;\n'
    'Mesh.MeshSizeMin = %s;\n'
    'Mesh.MeshSizeMax = %s;\n'
    'Mesh.ElementOrder = %s;\n'
    'Mesh 2;\n'
    'Save "%s";\n'
    'Exit;\n'
)

# Default timeouts. Assembly mode runs a single gmsh job, but that job is heavy;
# 3 minutes (the original per-solid value) would make assembly time out almost
# every time.
DEFAULT_TIMEOUT_PER_SOLID = 3 * 60
DEFAULT_TIMEOUT_ASSEMBLY = 15 * 60

# Triangle budget for the coincident-facet count: skip beyond it and only say so
# in the log.
_OVERLAP_BUDGET = 400_000
_MAX_OVERLAP_PAIRS = 8


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
    # Stage indicator: assembly mode is [Contact analysis / Boolean fragment /
    # Reassign], per-solid has a single stage
    stages_defined = pyqtSignal(list)
    stage_changed = pyqtSignal(int, str)

    def __init__(self, nodes: List[GDataNode], work_dir: str,
                 algorithm: int = 6,
                 elem_factor: float = 1.0,
                 mesh_min_factor: float = 6.0,
                 mesh_max_factor: float = 5.0,
                 smoothing: int = 1,
                 order: int = 1,
                 mode: str = "auto",
                 analysis: Optional[AnalysisResult] = None,
                 timeout_s: Optional[int] = None,
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
        self._analysis = analysis
        self._cancelled = False
        self._degraded = False

        # "auto" -> follow the contact analysis; if it has not finished, go
        # per-solid (conservative and no waiting)
        if mode == "auto":
            if analysis is not None and not analysis.failed:
                mode = analysis.mode
            else:
                mode = "per_solid"
        self._mode = mode

        self._timeout_s = timeout_s or (
            DEFAULT_TIMEOUT_ASSEMBLY if mode == "assembly"
            else DEFAULT_TIMEOUT_PER_SOLID)

        self.outcome = MeshOutcome(
            requested_mode=mode,
            actual_mode=mode,
            n_solids=len(nodes),
        )

        # Locate gmsh.exe
        self._gmsh_exe = find_gmsh_exe()
        if self._gmsh_exe:
            self.log_emitted.emit(f"[GMSH] Using: {self._gmsh_exe}")

    def cancel(self):
        self._cancelled = True

    @property
    def mode(self) -> str:
        return self._mode

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
        self.log_emitted.emit("=== GMSH Meshing Started ===")

        if self._mode == "assembly" and len(self._nodes) > 1:
            self.log_emitted.emit(
                "[MODE] Assembly conformal meshing (Merge + BooleanFragments)")
            self.stages_defined.emit(
                ["Contact analysis", "Boolean fragment", "Reassign"])
            ok, mesh_paths, msg = self._run_assembly()
            if ok:
                self._finish(True, mesh_paths, msg)
                return
            # ---- Degrade ladder: a failed assembly job is not a dead end; fall
            # back to per-solid meshing and mark it non-conformal ----
            self.log_emitted.emit(
                "[WARN] Assembly conformal meshing failed, degraded to per-solid "
                "meshing. Contact faces will no longer share facets and the export "
                "will be flagged as non-conformal.")
            self._degraded = True
            self.outcome.actual_mode = "per_solid"
            self.outcome.notes.append(
                "assembly job failed, degraded to per-solid meshing")
        else:
            self.log_emitted.emit("[MODE] Per-solid meshing")

        self.stages_defined.emit(["Per-solid meshing"])
        ok, mesh_paths, msg = self._run_per_solid()
        self._finish(ok, mesh_paths, msg)

    # ---------------------------------------------------------------
    # Per-solid meshing (original behaviour)
    # ---------------------------------------------------------------

    def _run_per_solid(self) -> Tuple[bool, dict, str]:
        mesh_paths: dict = {}
        total = len(self._nodes)
        self.stage_changed.emit(0, "Per-solid meshing...")

        for idx, node in enumerate(self._nodes):
            if self._cancelled:
                self.log_emitted.emit("Meshing cancelled by user.")
                return False, mesh_paths, "Cancelled."

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
                ok, gmsh_stdout, stop_reason = self._run_gmsh(geo_file)

                # 5. Forward GMSH output to log
                if gmsh_stdout:
                    for line in gmsh_stdout.split("\n"):
                        line = line.strip()
                        if line:
                            self.log_emitted.emit(f"  [GMSH] {line}")
                if stop_reason:
                    self.log_emitted.emit(
                        f"  [ERROR] {node_label}: {self._stop_message(stop_reason)}")
                    if stop_reason == "cancelled":
                        return False, mesh_paths, "Cancelled."
                    continue

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
        success = len(mesh_paths) > 0
        if success:
            msg = f"Mesh ready. {len(mesh_paths)} of {total} nodes meshed successfully."
        else:
            msg = f"Meshing failed. 0 of {total} nodes meshed."
        return success, mesh_paths, msg

    # ---------------------------------------------------------------
    # Assembly conformal meshing
    # ---------------------------------------------------------------

    def _run_assembly(self) -> Tuple[bool, dict, str]:
        """Merge N STEP files -> BooleanFragments -> Mesh 2 -> reassign to solids.

        Any failing step returns (False, {}, reason); run() decides the fallback.
        """
        live = [n for n in self._nodes
                if n.shape is not None and not n.shape.IsNull()]
        if len(live) < 2:
            return False, {}, "assembly mode needs at least 2 valid solids"

        t0 = time.time()

        # ---- Stage 0: contact analysis ----
        self.stage_changed.emit(0, "Contact analysis...")
        if self._analysis is not None and not self._analysis.failed:
            self.progress_updated.emit(2, "Reusing contact analysis from import...")
            self.log_emitted.emit(
                f"  contact analysis: {self._analysis.summary()}"
                f" (tol = {self._analysis.tol:.4f} mm)")
            for a, b, d in self._analysis.contact_pairs[:3]:
                self.log_emitted.emit(f"    contact: {a} <-> {b}  (d = {d:.6f} mm)")
        else:
            self.log_emitted.emit(
                "  no contact analysis available, submitting as an assembly job.")
        self.progress_updated.emit(5, "Preparing assembly job...")

        # ---- Stage 1: boolean fragment ----
        self.stage_changed.emit(1, "Boolean fragment...")
        step_files: List[str] = []
        for idx, node in enumerate(live):
            if self._cancelled:
                return False, {}, "Cancelled."
            safe_name = self._safe_id(node.entry_id, idx)
            step_file = os.path.join(self._work_dir, f"asm{idx:04d}_{safe_name}.step")
            try:
                self._write_shape_to_step(node.shape, step_file)
            except Exception as e:
                self.log_emitted.emit(f"  [ERROR] STEP export failed {node.name}: {e}")
                return False, {}, f"STEP export failed: {e}"
            if not os.path.exists(step_file) or os.path.getsize(step_file) == 0:
                return False, {}, f"STEP not written: {node.name}"
            step_files.append(step_file)
            self.progress_updated.emit(
                5 + int(10 * (idx + 1) / len(live)),
                f"Exporting STEP {idx + 1}/{len(live)}...")

        # Size factors come from the **overall** bbox: assembly is one job, so the
        # solids cannot each use their own scale
        abox = [bbox_of(n.shape) for n in live]
        lo = [min(b[k] for b in abox) for k in range(3)]
        hi = [max(b[k + 3] for b in abox) for k in range(3)]
        diag = sum((hi[k] - lo[k]) ** 2 for k in range(3)) ** 0.5
        size_min = diag / self._mesh_min_factor if self._mesh_min_factor > 0 else 0.001
        size_max = diag / self._mesh_max_factor if self._mesh_max_factor > 0 else 1.0

        geo_file = os.path.join(self._work_dir, "assembly.geo")
        asm_vtk = os.path.join(self._work_dir, "assembly.vtk")
        chunk = [ASSEMBLY_HEAD]
        chunk += [ASSEMBLY_MERGE % sf.replace("\\", "/") for sf in step_files]
        chunk.append(ASSEMBLY_FRAGMENT)
        chunk.append(ASSEMBLY_TAIL % (
            self._algorithm, self._smoothing, self._elem_factor,
            size_min, size_max, self._order, asm_vtk.replace("\\", "/")))
        with open(geo_file, "w", encoding="utf-8") as f:
            f.write("".join(chunk))

        self.log_emitted.emit(
            f"  assembly job: {len(step_files)} solids, SizeMin={size_min:.4f}, "
            f"SizeMax={size_max:.4f}, CharLengthFactor={self._elem_factor}")
        self.progress_updated.emit(18, "BooleanFragments + assembly meshing...")

        ok, gmsh_stdout, stop_reason = self._run_gmsh(geo_file)
        if gmsh_stdout:
            for line in gmsh_stdout.split("\n"):
                line = line.strip()
                if line:
                    self.log_emitted.emit(f"  [GMSH] {line}")
        if stop_reason:
            return False, {}, self._stop_message(stop_reason)
        if not ok or not os.path.exists(asm_vtk) or os.path.getsize(asm_vtk) == 0:
            return False, {}, "gmsh produced no assembly VTK"
        self.progress_updated.emit(60, "Assembly mesh written, starting reassignment...")
        self.log_emitted.emit("[OK] boolean fragment and assembly meshing done")

        # ---- Stage 2: reassignment ----
        self.stage_changed.emit(2, "Reassign...")
        try:
            pts, tris = read_vtk(asm_vtk)
        except Exception as e:
            return False, {}, f"failed to read assembly VTK: {e}"
        if not tris:
            return False, {}, "assembly VTK contains no triangles"
        self.log_emitted.emit(
            f"  assembly mesh: {len(pts)} nodes / {len(tris)} triangles")

        tol = (self._analysis.tol if (self._analysis and self._analysis.tol > 0)
               else 1e-4 * diag)
        try:
            owners = assign_owners(
                pts, tris, [n.shape for n in live], abox, tol,
                progress_cb=lambda k, t: self.progress_updated.emit(
                    60 + int(25 * k / max(1, t)), f"Reassign {k}/{t}..."),
                cancel_cb=lambda: self._cancelled)
        except InterruptedError:
            return False, {}, "Cancelled."

        unassigned = sum(1 for ow in owners if not ow)
        if unassigned:
            self.log_emitted.emit(
                f"  [WARN] {unassigned} triangles were not assigned to any solid "
                f"(tol = {tol:.4f} mm)")

        parts = build_parts(pts, tris, owners, [n.name or n.entry_id for n in live])

        mesh_paths: dict = {}
        bad_solids: List[str] = []
        open_total = 0
        for node, (nm, verts, ptris) in zip(live, parts):
            if not ptris:
                self.log_emitted.emit(
                    f"  [ERROR] {nm}: no facets left after reassignment")
                bad_solids.append(nm)
                continue
            open_edges, _ = check_closed(ptris)
            if open_edges:
                open_total += open_edges
                bad_solids.append(nm)
                self.log_emitted.emit(
                    f"  [WARN] {nm}: not closed, {open_edges} open edges")
            out = os.path.join(self._work_dir, f"{self._safe_id(node.entry_id, 0)}.vtk")
            write_vtk(out, verts, ptris, title=nm)
            node.mesh_file_name = out
            mesh_paths[node.entry_id] = out
            self.log_emitted.emit(
                f"  -> {nm}: {len(ptris)} triangles / {len(verts)} nodes")

        if not mesh_paths:
            return False, {}, "reassignment produced no solid mesh"

        self.progress_updated.emit(95, "Reassignment complete")
        self.outcome.actual_mode = "assembly"
        # Assembly conformal: both sides of a contact face receive the **same
        # batch of triangles**, so there are no spatially coincident yet
        # topologically unrelated facets -- the coincident count is always 0.
        self.outcome.overlap_facets = 0
        self.outcome.open_edges = open_total
        self.outcome.bad_solids = bad_solids
        self.outcome.elapsed = time.time() - t0

        msg = (f"Assembly conformal done: {len(mesh_paths)} solids / "
               f"{len(tris)} triangles, 0 coincident facets")
        return True, mesh_paths, msg

    # ---------------------------------------------------------------
    # Wrap-up and state verdict
    # ---------------------------------------------------------------

    def _finish(self, success: bool, mesh_paths: dict, msg: str):
        self.log_emitted.emit("=== GMSH Meshing Complete ===")
        self.outcome.n_meshed = len(mesh_paths)
        self.progress_updated.emit(100, msg)

        if not success:
            self.outcome.kind = NON_CONFORMAL
            self.outcome.notes.append(msg)
        elif self._mode == "assembly" and not self._degraded:
            self.outcome.kind = PARTIAL if self.outcome.bad_solids else CONFORMAL
        else:
            self._resolve_per_solid_conformity(mesh_paths)

        self.log_emitted.emit(f"[STATE] {self.outcome.headline}")
        if self.outcome.kind != CONFORMAL:
            for line in self.outcome.detail_lines():
                self.log_emitted.emit(f"    {line}")

        self.finished_with_result.emit(success, mesh_paths, msg)

    def _resolve_per_solid_conformity(self, mesh_paths: dict):
        """Conformity verdict after per-solid meshing.

        The verdict is mostly **derived**: as soon as a contacting pair exists,
        per-solid meshing inevitably drops a separate facet set on that face.
        Here up to 8 pairs are additionally measured for real, so 🔴 comes with a
        number the user can check themselves.
        """
        pairs = list(self._analysis.contact_pairs) if self._analysis else []
        if not pairs:
            self.outcome.kind = CONFORMAL
            self.outcome.notes.append(
                "no contact face, per-solid meshing is conformal")
            return

        by_name = {}
        for node in self._nodes:
            p = mesh_paths.get(node.entry_id)
            if p:
                by_name[node.name or node.entry_id] = p

        tol = max(self._analysis.tol, 1e-6) if self._analysis else 1e-6
        total = 0
        truncated = False
        for a, b, _d in pairs[:_MAX_OVERLAP_PAIRS]:
            if a not in by_name or b not in by_name:
                continue
            try:
                n, cut = count_coincident_facets(
                    read_vtk(by_name[a]), read_vtk(by_name[b]), tol,
                    _OVERLAP_BUDGET)
            except Exception:
                continue
            total += n
            truncated = truncated or cut

        self.outcome.overlap_facets = total
        self.outcome.kind = NON_CONFORMAL
        if truncated:
            self.outcome.notes.append(
                "coincident-facet count truncated by budget, actual count is higher")
        if len(pairs) > _MAX_OVERLAP_PAIRS:
            self.outcome.notes.append(
                f"only the first {_MAX_OVERLAP_PAIRS} contact pairs were measured")

    @staticmethod
    def _stop_message(reason: str) -> str:
        return {
            "timeout": "gmsh timed out and was killed (consider a longer timeout "
                       "for assembly jobs)",
            "cancelled": "Cancelled.",
            "start_failed": "failed to start gmsh",
        }.get(reason, reason)

    # ---------------------------------------------------------------

    def _run_gmsh(self, geo_file: str):
        """Run gmsh.exe, return (ok, stdout_text, stop_reason).

        Polls in 200 ms slices instead of a single waitForFinished(180s):
        otherwise the Cancel button would be unresponsive during a long
        assembly job.
        """
        proc = QProcess()
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setWorkingDirectory(self._work_dir)

        args = [geo_file, "-1"]  # -1 = non-interactive mode (same as C++ reference)
        proc.start(self._gmsh_exe, args)
        if not proc.waitForStarted(10 * 1000):
            return False, "", "start_failed"

        deadline = time.time() + self._timeout_s
        while not proc.waitForFinished(200):
            if self._cancelled:
                proc.kill()
                proc.waitForFinished(3000)
                return False, "", "cancelled"
            if time.time() > deadline:
                proc.kill()
                proc.waitForFinished(3000)
                return False, "", "timeout"

        stdout = proc.readAllStandardOutput().data().decode("utf-8", errors="replace")
        return proc.exitCode() == 0, stdout, ""

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
