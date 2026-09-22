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

import ctypes
import functools
import os
import re
import sys
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

# How fast the bar crosses a stage whose length is unknown. Only a gmsh run is
# in that position, and it is most of the wall time of a job: the bar is driven
# by gmsh's own progress lines first (see _note_gmsh_line), elapsed time only
# fills the silences in between. The curve is asymptotic -- the ceiling of the
# stage is still written only where the stage really ends, so a creeping bar can
# never be read as "this stage is over".
STAGE_CREEP_S = 30.0

# ---- Driving the bar from gmsh's own output -------------------------------
# gmsh announces its meshing stages on stdout and then reports how far into each
# one it is, e.g.
#   Info    : Meshing 2D...
#   Info    : [ 40%] Meshing surface 5 (Plane, Frontal-Delaunay)
# so the bar shows what gmsh is actually doing instead of guessing from the
# clock. Each stage fills its own slice of the band the run was given; the 1D
# pass is a rounding error next to the surface solve, so it gets the small one.
_GMSH_STAGE_RE = re.compile(r"Meshing\s+(\dD)\s*\.\.\.")
_GMSH_PERCENT_RE = re.compile(r"\[\s*(\d+)%\]")
_GMSH_1D_SLICE = (0.0, 0.2)
_GMSH_MESH_SLICE = (0.2, 1.0)
_GMSH_STAGE_SLICE = {"1D": _GMSH_1D_SLICE}


# ---- gmsh liveness --------------------------------------------------------
# A gmsh job that prints nothing is not necessarily a stuck one: during the 2D
# solve it stays quiet for a minute or more while still burning CPU. Sampling
# the CPU time of the process itself is what tells the two apart, so the dialog
# can say how long ago gmsh was last seen working instead of leaving a frozen
# bar and a frozen log, which look exactly like a wedged process.
#
# Windows only, and strictly best-effort: anything that cannot be read returns
# None. A missing heartbeat only costs that one piece of information -- it must
# never turn into a "stalled" verdict.

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@functools.lru_cache(maxsize=1)
def _kernel32():
    """kernel32 with the signatures spelled out.

    The default c_int return type truncates the 64-bit HANDLE returned by
    OpenProcess; the truncated value is then rejected by GetProcessTimes on
    some machines and accepted on others, which is the kind of failure that
    cannot be reproduced.
    """
    from ctypes import wintypes
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.OpenProcess.restype = wintypes.HANDLE
    lib.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    lib.GetProcessTimes.restype = wintypes.BOOL
    lib.GetProcessTimes.argtypes = (wintypes.HANDLE,
                                    *[ctypes.POINTER(wintypes.FILETIME)] * 4)
    lib.CloseHandle.argtypes = (wintypes.HANDLE,)
    return lib


def process_cpu_seconds(pid: int) -> Optional[float]:
    """Total CPU seconds burnt by `pid`, or None when it cannot be read."""
    if sys.platform != "win32" or not pid:
        return None
    try:
        from ctypes import wintypes
        lib = _kernel32()
        handle = lib.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False,
                                 int(pid))
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            got = lib.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))
            if not got:
                return None
            # Kernel + user time; FILETIME counts 100 ns units.
            return sum((t.dwHighDateTime << 32) | t.dwLowDateTime
                       for t in times[2:]) / 1e7
        finally:
            lib.CloseHandle(handle)
    except Exception:
        return None


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
    # (elapsed, idle) in seconds for the running gmsh job. Both the bar and the
    # log sit still while one solid is being meshed, so this is what proves the
    # job is still working.
    heartbeat = pyqtSignal(float, float)
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

        # The stage the bar is currently inside: (floor, ceiling) plus the text
        # that goes with it, or None when no gmsh run is in flight. See
        # _begin_stage / _creep / _note_gmsh_line.
        self._stage_band: Optional[Tuple[int, int]] = None
        self._stage_msg = ""
        self._stage_value = 0
        self._gmsh_slice = _GMSH_1D_SLICE

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
            # This solid's own slice of the bar. The gmsh run inside it takes
            # most of its wall time and reports nothing, so the slice is entered
            # at its floor and crossed from the clock (_creep); the old fixed
            # +5 step kept every emit of a run inside its first two percent,
            # which is why a long run showed no colour at all.
            pct = int((idx / total) * 85)
            band_end = max(pct + 5, int(((idx + 1) / total) * 85))

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

                self._begin_stage(pct + 3, band_end,
                                  f"Running GMSH on {node_label}...")
                self.log_emitted.emit(f"  Generating mesh for {node_label} ...")

                # 4. Launch gmsh.exe with the .geo script. Its output is
                #    forwarded line by line while it runs, so only the verdict
                #    is left to report here.
                ok, _stdout, stop_reason = self._run_gmsh(geo_file)
                self._end_stage()

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

            self.progress_updated.emit(band_end, f"Done: {node_label}")

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
        self._begin_stage(18, 60, "BooleanFragments + assembly meshing...")

        ok, _stdout, stop_reason = self._run_gmsh(geo_file)
        self._end_stage()
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

    # ---- What the bar does while gmsh runs ----

    def _begin_stage(self, floor: int, ceiling: int, message: str) -> None:
        """Enter a stage the runner cannot report inside of, i.e. a gmsh run.

        It writes the floor and the message itself, so the caller states the
        span once: everything between floor and ceiling then comes from _creep,
        and the caller writes the ceiling where the run actually ends.
        """
        self._stage_band = (floor, max(floor, ceiling))
        self._stage_msg = message
        self._stage_value = floor
        self._gmsh_slice = _GMSH_1D_SLICE
        self.progress_updated.emit(floor, message)

    def _end_stage(self) -> None:
        self._stage_band = None

    def _creep(self, elapsed: float) -> None:
        """Carry the bar on towards the end of the running stage.

        gmsh reports its own mesh progress (_note_gmsh_line), but not
        continuously: between two of its lines -- and through the merge and
        fragment passes of an assembly job, which print no percent at all -- the
        bar would hold the value it was handed, which is exactly what a wedged
        process looks like. Elapsed time is the one number that does move while
        it works, so it carries the bar across those silences, and
        asymptotically: the clock never reaches the ceiling, which is still
        written only where the stage really ends. A bar that is full keeps
        meaning "the stage is over" and nothing less.
        """
        band = self._stage_band
        if band is None:
            return
        floor, ceiling = band
        if ceiling - floor < 2:
            return
        span = ceiling - floor - 1
        value = floor + int(span * (elapsed / (elapsed + STAGE_CREEP_S)))
        if value > self._stage_value:
            self._stage_value = value
            self.progress_updated.emit(value, self._stage_msg)

    def _note_gmsh_line(self, line: str) -> None:
        """Move the bar to where gmsh just said it is.

        The run is the only stage we cannot report inside of ourselves, and gmsh
        does report it: it announces each meshing stage and then prints how far
        into it went, so the percent of the line is what the bar gets, placed in
        the slice that stage owns inside the band. Value only ever grows, which
        is what keeps the clock (_creep) and the real progress from fighting:
        whichever is further along wins, and the creep -- whose curve lags
        behind real progress most of the time -- stays quiet.
        """
        band = self._stage_band
        if band is None:
            return
        stage = _GMSH_STAGE_RE.search(line)
        if stage:
            self._gmsh_slice = _GMSH_STAGE_SLICE.get(stage.group(1),
                                                     _GMSH_MESH_SLICE)
            return
        percent = _GMSH_PERCENT_RE.search(line)
        if percent is None:
            return
        floor, ceiling = band
        span = max(ceiling - floor - 1, 0)
        start, end = self._gmsh_slice
        value = floor + int(
            span * (start + (end - start) * int(percent.group(1)) / 100.0))
        if value > self._stage_value:
            self._stage_value = value
            self.progress_updated.emit(value, self._stage_msg)

    def _run_gmsh(self, geo_file: str):
        """Run gmsh.exe, return (ok, stdout_text, stop_reason).

        Polls in 200 ms slices instead of a single waitForFinished(timeout):
        otherwise the Cancel button would be unresponsive during a long
        assembly job, and the output could only be read once the process had
        exited -- which left the log empty exactly while the user was waiting.
        """
        proc = QProcess()
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setWorkingDirectory(self._work_dir)

        args = [geo_file, "-1"]  # -1 = non-interactive mode (same as C++ reference)
        proc.start(self._gmsh_exe, args)
        if not proc.waitForStarted(10 * 1000):
            return False, "", "start_failed"

        started = time.time()
        deadline = started + self._timeout_s
        lines: List[str] = []
        last_cpu = process_cpu_seconds(proc.processId())
        last_activity = started
        last_beat = (-1, -1)

        while not proc.waitForFinished(200):
            if self._drain_gmsh_output(proc, lines):
                last_activity = time.time()

            # CPU time is the only signal separating "quiet because it is
            # solving" from "wedged": the first keeps growing, the second does
            # not. None means unreadable, which is evidence of nothing.
            cpu = process_cpu_seconds(proc.processId())
            if cpu is not None:
                if last_cpu is not None and cpu > last_cpu + 0.01:
                    last_activity = time.time()
                last_cpu = cpu

            # At most one heartbeat per second: the two integers only change
            # then, and the dialog has nothing finer to show.
            beat = (int(time.time() - started), int(time.time() - last_activity))
            if beat != last_beat:
                last_beat = beat
                self.heartbeat.emit(float(beat[0]), float(beat[1]))
                # Same clock, second job: the dialog needs the two numbers to
                # tell "slow" from "wedged", the bar needs them because
                # otherwise it does not move at all for the length of the run.
                self._creep(beat[0])

            if self._cancelled:
                proc.kill()
                proc.waitForFinished(3000)
                return False, "\n".join(lines), "cancelled"
            if time.time() > deadline:
                proc.kill()
                proc.waitForFinished(3000)
                return False, "\n".join(lines), "timeout"

        self._drain_gmsh_output(proc, lines)
        return proc.exitCode() == 0, "\n".join(lines), ""

    def _drain_gmsh_output(self, proc: QProcess, lines: List[str]) -> bool:
        """Forward whatever gmsh printed since the last poll.

        Returns True when there was something, which is the caller's heartbeat:
        keeping the log moving while the job runs is what makes a long job look
        like a long job rather than a frozen window.
        """
        chunk = bytes(proc.readAllStandardOutput().data()).decode(
            "utf-8", errors="replace")
        found = False
        for line in chunk.splitlines():
            line = line.strip()
            if line:
                lines.append(line)
                self.log_emitted.emit(f"  [GMSH] {line}")
                # The bar has a use for the same line the log gets: gmsh is
                # the only one who knows how far into the mesh it is.
                self._note_gmsh_line(line)
                found = True
        return found

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
