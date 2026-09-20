"""
assembly_analysis.py -- the background "contact analysis" run after import.

It answers one question: **do any two of these solids share a contact face?**

Why that is the only criterion (see exampleSTEP/merge_demo/README.md, conclusion 2):

    The problem is not "whether the parts are merged", it is "whether there is a
    contact face". a2 on its own, as a single STEP file, already has 75~85
    coincident facet pairs because bolt/nut/bracket inside it are touching to
    begin with. So "export everything into one STEP" is neither the cause nor
    the cure.

  - contact found   -> per-solid meshing drops its own facet set on both sides of
                       every contact face (coincident facets > 0); only assembly
                       BooleanFragments can drive that to zero -> assembly
  - all separated   -> both modes give 0 coincident facets, take the cheaper one
                       -> per_solid
  - only 1 solid    -> nothing to fragment -> per_solid

Flow: bbox pre-filter (pure math, O(N^2) but very fast) -> run
      BRepExtrema_DistShapeShape exactly only on bbox-overlapping pairs.

Ported from exampleSTEP/merge_demo/tools/decide_mode.py.
"""

import multiprocessing as mp
import pickle
import queue
import time
from typing import List, Optional, Sequence

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.conformity import AnalysisResult
from mesh.vtk_tools import bbox_of, boxes_touch, min_distance

# Relative tolerance: the contact test uses 1e-4 x the overall bbox diagonal.
# In the demo 1e-5 and 1e-4 gave identical results, so the looser one is used.
DEFAULT_TOL_FACTOR = 1e-4


def analyse_solids(
    shapes: Sequence,
    names: Sequence[str],
    tol_factor: float = DEFAULT_TOL_FACTOR,
    progress_cb=None,
    log_cb=None,
    cancel_cb=None,
) -> AnalysisResult:
    """Synchronous contact analysis. Returns AnalysisResult (failed=True on error)."""
    t0 = time.time()
    res = AnalysisResult()

    # `live` keeps the position of every solid in the original list, so a contact
    # can be reported both by name (for the log) and by index (for the scope
    # grouping, which must not depend on names being unique).
    live = [(k, n, s) for k, (n, s) in enumerate(zip(names, shapes))
            if s is not None and not s.IsNull()]
    res.n_solids = len(live)
    if not live:
        res.failed = True
        res.reason = "no usable solids"
        res.elapsed = time.time() - t0
        return res

    if log_cb:
        log_cb(f"Contact analysis: {res.n_solids} solids, starting bbox pre-filter ...")
    if progress_cb:
        progress_cb(5, "bbox pre-filter...")

    boxes = [bbox_of(s) for _, _, s in live]
    lo = [min(b[k] for b in boxes) for k in range(3)]
    hi = [max(b[k + 3] for b in boxes) for k in range(3)]
    res.bbox_diag = sum((hi[k] - lo[k]) ** 2 for k in range(3)) ** 0.5
    res.tol = tol_factor * res.bbox_diag

    # ---- Only 1 solid: nothing to fragment ----
    if res.n_solids <= 1:
        res.mode = "per_solid"
        res.reason = f"only {res.n_solids} solid(s), no contact face to fragment"
        res.elapsed = time.time() - t0
        if log_cb:
            log_cb(f"Contact analysis: {res.reason}")
        return res

    # ---- bbox pre-filter ----
    candidates = []
    n = res.n_solids
    for i in range(n):
        for j in range(i + 1, n):
            if boxes_touch(boxes[i], boxes[j], res.tol):
                candidates.append((i, j))

    if progress_cb:
        progress_cb(20, f"Exact distances: {len(candidates)} candidate pairs...")
    if log_cb:
        log_cb(f"  candidate pairs {len(candidates)} / total {n * (n - 1) // 2}")

    # ---- Exact distances (candidate pairs only) ----
    dmin = float("inf")
    total = max(1, len(candidates))
    step = max(1, total // 50)

    for k, (i, j) in enumerate(candidates):
        if cancel_cb and cancel_cb():
            res.failed = True
            res.reason = "cancelled"
            res.elapsed = time.time() - t0
            return res
        d = min_distance(live[i][2], live[j][2])
        if d < dmin:
            dmin = d
        if d <= res.tol:
            res.contact_pairs.append((live[i][1], live[j][1], d))
            res.contact_indices.append((live[i][0], live[j][0], d))
        if progress_cb and (k % step == 0 or k == total - 1):
            progress_cb(20 + int(75 * (k + 1) / total),
                        f"Exact distances {k + 1}/{total}...")

    res.tested_pairs = len(candidates)
    res.min_dist = dmin if candidates else float("inf")

    # ---- Verdict ----
    if res.contact_pairs:
        res.mode = "assembly"
        res.reason = (f"{len(res.contact_pairs)} contacting solid pair(s) "
                      f"(min distance {dmin:.4f} mm <= tol {res.tol:.4f} mm); "
                      f"per-solid meshing would drop a separate facet set on each")
    else:
        res.mode = "per_solid"
        shown = f"{dmin:.4f} mm" if dmin != float("inf") else "no measurable pair"
        res.reason = (f"no contacting pair (min distance {shown} > tol "
                      f"{res.tol:.4f} mm); both modes give 0 coincident facets, "
                      f"taking the cheaper per-solid meshing")

    res.elapsed = time.time() - t0
    if progress_cb:
        progress_cb(100, "Contact analysis complete")
    if log_cb:
        log_cb(f"Contact analysis complete ({res.elapsed:.1f} s): {res.reason}")
        for a, b, d in res.contact_pairs[:3]:
            log_cb(f"  contact: {a} <-> {b}  (d = {d:.6f} mm)")
    return res


# ──────────────────── background runner (child process) ────────────────────
#
# Why a child *process* and not a QThread:
#
#   BRepExtrema_DistShapeShape is a long, pure C++ call and the pythonocc
#   binding holds the GIL for its whole duration (~160 ms per candidate pair
#   on the 18-solid demo, ~8 s in total).  A QThread therefore never gets the
#   GIL back to the Qt main thread in time: measured on the demo assembly the
#   UI thread was starved ~80 % of the time with ~100 ms stalls ten times a
#   second for the whole run -- i.e. exactly the "UI freeze" after import.
#
#   A child process has its own interpreter and its own GIL, so the Qt thread
#   is never blocked.  Re-measured with the identical workload, the worst
#   main-thread stall dropped from ~100 ms to ~16 ms and the verdict was
#   unchanged (32 contacting pairs).
#
# Shapes travel by pickle (TopoDS_Shape is picklable in pythonocc 7.9): the 18
# demo solids serialise in ~25 ms / 0.7 MB, a single acceptable hitch.
# Progress/log lines come back over a queue that the Qt side drains from a
# timer, so no Qt object is ever touched from another thread.

_CHILD_JOB_TIMEOUT_S = 30.0


def _analysis_child(in_q, out_q):
    """Child-process entry point: run one analysis, report it, then exit."""
    try:
        payload = in_q.get(timeout=_CHILD_JOB_TIMEOUT_S)
    except Exception:
        return
    if payload is None:
        return
    try:
        shapes, names, tol_factor = pickle.loads(payload)
        res = analyse_solids(
            shapes, names, tol_factor,
            progress_cb=lambda v, m: out_q.put(("progress", v, m)),
            log_cb=lambda m: out_q.put(("log", m)),
            cancel_cb=None,          # cancelling means killing this process
        )
        out_q.put(("done", res))
    except BaseException as e:       # a worker process must not die silently
        try:
            out_q.put(("error", f"{type(e).__name__}: {e}"))
        except Exception:
            pass


class AssemblyAnalyzer(QObject):
    """Runs the contact analysis in a child process so the UI stays responsive.

    The public surface mirrors the previous QThread implementation
    (start / cancel / wait / isRunning plus the three signals) so callers do
    not have to know that a process is involved now.
    """

    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    finished_analysis = pyqtSignal(object)

    POLL_INTERVAL_MS = 60

    def __init__(self, shapes: Sequence, names: Sequence[str],
                 tol_factor: float = DEFAULT_TOL_FACTOR, parent=None):
        super().__init__(parent)
        self._shapes = list(shapes)
        self._names = list(names)
        self._tol_factor = tol_factor
        self._proc: Optional[mp.Process] = None
        self._in_q = None
        self._out_q = None
        self._finished = False
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._drain)

    # ---- Qt-thread API ----

    def start(self):
        """Spawn the worker and hand it the job. Returns immediately."""
        self._finished = False
        try:
            payload = pickle.dumps((self._shapes, self._names, self._tol_factor))
        except Exception as e:
            # Not serialisable: report it instead of hanging on "running..."
            self._finished = True
            self.finished_analysis.emit(
                AnalysisResult(failed=True, reason=f"failed: {e}"))
            return

        ctx = mp.get_context("spawn")
        self._in_q = ctx.Queue()
        self._out_q = ctx.Queue()
        self._proc = ctx.Process(target=_analysis_child,
                                 args=(self._in_q, self._out_q),
                                 name="ContactAnalysis", daemon=True)
        self._proc.start()
        self._timer.start()
        self._in_q.put(payload)

    def isRunning(self) -> bool:
        return self._proc is not None and not self._finished

    def cancel(self):
        """Stop the worker at once; no result is delivered."""
        if self._finished:
            return
        self._finished = True
        self._teardown(kill=True)

    def wait(self, ms: int = 3000) -> bool:
        """Kept for API parity; cancel() already reaps the child."""
        if self._proc is not None:
            try:
                self._proc.join(ms / 1000.0)
            except Exception:
                pass
        return True

    @property
    def cancelled(self) -> bool:
        return self._finished

    # ---- internals ----

    def _drain(self):
        """Timer slot: turn whatever the child produced into Qt signals."""
        result: Optional[AnalysisResult] = None
        while self._out_q is not None:
            try:
                msg = self._out_q.get_nowait()
            except queue.Empty:
                break
            except (EOFError, OSError, ValueError):
                break
            kind = msg[0]
            if kind == "log":
                self.log.emit(msg[1])
            elif kind == "progress":
                self.progress.emit(msg[1], msg[2])
            elif kind == "done":
                result = msg[1]
            elif kind == "error":
                result = AnalysisResult(failed=True, reason=f"failed: {msg[1]}")

        if result is None:
            if self._proc is not None and not self._proc.is_alive():
                result = AnalysisResult(
                    failed=True, reason="worker exited without a result")
                self.log.emit("[ERROR] contact analysis worker died unexpectedly")
            else:
                return

        self._finished = True
        self._teardown(kill=False)
        self.finished_analysis.emit(result)

    def _teardown(self, kill: bool):
        self._timer.stop()
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                if kill and proc.is_alive():
                    proc.terminate()
                proc.join(timeout=1.0)
            except Exception:
                pass
            try:
                proc.close()
            except Exception:
                pass
        for q in (self._in_q, self._out_q):
            if q is not None:
                try:
                    q.close()
                except Exception:
                    pass
        self._in_q = None
        self._out_q = None
