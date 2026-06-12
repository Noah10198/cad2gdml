"""
InterferenceDialogV2 — Fast heuristic interference scan (sampled).

Instead of checking every pair with the expensive BRepExtrema_DistShapeShape,
this version uses a two-pass approach:

  1. OBB + spatial grid to enumerate ALL nearby pairs (pure math, ~O(N))
  2. Sort candidate pairs by OBB distance → take the Top N most suspicious
  3. Run exact DistShapeShape ONLY on those sampled pairs

For large assemblies this is dramatically faster than the exhaustive V1 check.
The results are clearly marked as **sampled · for reference only**.
"""

import math
import time
import heapq

from PyQt6.QtWidgets import QApplication, QProgressDialog

from OCC.Core.gp import gp_XYZ

from ui.interference_dialog import (
    InterferenceDialog,
    CONTACT_THRESHOLD,
)


# ── Configuration ─────────────────────────────────────────────────────
SAMPLE_FRACTION = 0.05   # sample 5% of total pairs
MAX_SAMPLE_PAIRS = 50   # but never exceed this cap


class InterferenceDialogV2(InterferenceDialog):
    """Interference scan with heuristic sampling.

    Strategy:
      - Compute OBB for every solid (O(N), cheap).
      - Build a spatial grid, iterate neighbours, compute OBB distance.
      - Sample min(5% of total pairs, 50) closest pairs.
      - Run the exact B-Rep DistShapeShape only on those.
      - Results are labelled "sampled · reference only".
    """

    def _do_check(self):
        n = len(self._solids)
        if n < 2:
            self._summary_label.setText("Need at least 2 solids.")
            return

        self._table.setRowCount(0)
        self._results.clear()
        self._occ_preview.clear_all()
        self._pair_info.setText("Select a row to preview the pair")

        total_pairs = n * (n - 1) // 2
        n_sample = min(max(1, int(total_pairs * SAMPLE_FRACTION)), MAX_SAMPLE_PAIRS)
        progress = QProgressDialog(
            "Scanning candidate pairs...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Interference Scan V2")
        progress.setModal(True)
        progress.show()
        QApplication.processEvents()

        t0 = time.time()
        inf = float("inf")

        # ── Phase 1: OBBs + scene bounds ──────────────────────────────
        progress.setLabelText("Computing bounding boxes...")
        QApplication.processEvents()
        t0_bbox = time.time()
        bboxes = [self._compute_bbox(s[2]) for s in self._solids]
        t_bbox = time.time() - t0_bbox

        # ── Phase 2: spatial grid ─────────────────────────────────────
        progress.setLabelText("Building spatial grid...")
        QApplication.processEvents()

        # Scene diagonal
        scene_min = gp_XYZ(inf, inf, inf)
        scene_max = gp_XYZ(-inf, -inf, -inf)
        for obb in bboxes:
            for c in self._obb_corners(obb):
                scene_min = gp_XYZ(
                    min(scene_min.X(), c.X()),
                    min(scene_min.Y(), c.Y()),
                    min(scene_min.Z(), c.Z()),
                )
                scene_max = gp_XYZ(
                    max(scene_max.X(), c.X()),
                    max(scene_max.Y(), c.Y()),
                    max(scene_max.Z(), c.Z()),
                )

        span = scene_max.Subtracted(scene_min)
        diag = math.sqrt(span.X() ** 2 + span.Y() ** 2 + span.Z() ** 2)
        cell_size = diag / 30.0
        if cell_size < 1e-6:
            cell_size = 1.0

        # For each solid, cache its grid cell keys
        solid_cells = []
        for idx in range(n):
            corners = self._obb_corners(bboxes[idx])
            cmin = gp_XYZ(inf, inf, inf)
            cmax = gp_XYZ(-inf, -inf, -inf)
            for c in corners:
                cmin = gp_XYZ(min(cmin.X(), c.X()),
                              min(cmin.Y(), c.Y()),
                              min(cmin.Z(), c.Z()))
                cmax = gp_XYZ(max(cmax.X(), c.X()),
                              max(cmax.Y(), c.Y()),
                              max(cmax.Z(), c.Z()))
            gx0 = int(math.floor(cmin.X() / cell_size))
            gy0 = int(math.floor(cmin.Y() / cell_size))
            gz0 = int(math.floor(cmin.Z() / cell_size))
            gx1 = int(math.floor(cmax.X() / cell_size))
            gy1 = int(math.floor(cmax.Y() / cell_size))
            gz1 = int(math.floor(cmax.Z() / cell_size))
            keys = [(gx, gy, gz)
                    for gx in range(gx0, gx1 + 1)
                    for gy in range(gy0, gy1 + 1)
                    for gz in range(gz0, gz1 + 1)]
            solid_cells.append(keys)

        # Build reverse grid: cell → set of solid indices
        grid = {}
        for idx, keys in enumerate(solid_cells):
            for key in keys:
                grid.setdefault(key, set()).add(idx)

        # ── Phase 3: collect candidate pairs with OBB distance ────────
        progress.setLabelText(f"Ranking {total_pairs} candidate pairs...")
        QApplication.processEvents()

        # Use a max-heap of size n_sample to keep closest pairs
        # heap element = (neg_distance_sq, i, j) so min-heap acts as max-heap
        heap: list = []
        checked: set = set()

        for i in range(n):
            if progress.wasCanceled():
                progress.close()
                self._summary_label.setText("⚠ Cancelled.")
                return

            # Gather neighbours from i's cells + 26 adjacent cells
            neighbour_indices: set = set()
            for key in solid_cells[i]:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            nk = (key[0] + dx, key[1] + dy, key[2] + dz)
                            if nk in grid:
                                neighbour_indices.update(grid[nk])

            for j in neighbour_indices:
                if j <= i:
                    continue
                pair_key = (i, j)
                if pair_key in checked:
                    continue
                checked.add(pair_key)

                # OBB distance — pure math, nanoseconds
                bdist_sq = self._bbox_distance_sq(bboxes[i], bboxes[j])
                heapq.heappush(heap, (-bdist_sq, i, j))
                if len(heap) > n_sample:
                    heapq.heappop(heap)  # discard farthest

        n_candidates = len(heap)
        t_scan = time.time() - t0

        # ── Phase 4: exact check on sampled pairs ─────────────────────
        t1 = time.time()
        hard_count = contact_count = safe_count = 0
        exact_done = 0
        sampled_results = []

        # Show sampled status in table
        progress.setLabelText(
            f"Checking {n_candidates} sampled pairs...")
        progress.setMaximum(n_candidates if n_candidates > 0 else 1)
        QApplication.processEvents()

        # Extract pairs from heap (closest first)
        sampled_pairs = []
        while heap:
            neg_d2, i, j = heapq.heappop(heap)
            sampled_pairs.append((i, j))
        sampled_pairs.reverse()  # closest first

        cancelled = False
        for idx, (i, j) in enumerate(sampled_pairs):
            if cancelled:
                break
            id_a, name_a, shape_a = self._solids[i]
            id_b, name_b, shape_b = self._solids[j]

            status, distance = self._classify_pair(shape_a, shape_b)
            sampled_results.append(self._make_result(
                i, j, id_a, name_a, id_b, name_b,
                status, distance, shape_a, shape_b))
            hard_count += (status == "hard")
            contact_count += (status == "contact")
            safe_count += (status == "safe")
            exact_done += 1

            if exact_done % 50 == 0 or exact_done == n_candidates:
                progress.setValue(exact_done)
                QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True

        progress.close()
        t_exact = time.time() - t1
        elapsed = time.time() - t0

        # ── Report ────────────────────────────────────────────────────
        if not cancelled:
            parts = (
                '<span style="color:#ff4444;">■</span> Hard: '
                f"{hard_count}  "
                '<span style="color:#ffaa00;">■</span> Contact: '
                f"{contact_count}  "
                '<span style="color:#44cc44;">■</span> Safe: '
                f"{safe_count}"
            )
            sampled_note = (
                '<span style="color:#ff8800;">⚠ Sampled — for reference only'
                '</span>'
            )
            self._summary_label.setText(
                f"{sampled_note}  |  "
                f"{exact_done} pairs checked in {elapsed:.1f}s"
                f"  (scan: {t_scan:.1f}s, exact: {t_exact:.1f}s)"
                f"  |  {parts}"
            )
            if self._log_callback:
                self._log_callback(
                    f"Interference V2 (sampled) completed ({elapsed:.1f}s): "
                    f"{hard_count} hard, {contact_count} contact, "
                    f"{safe_count} safe "
                    f"[scanned {n_candidates} from {total_pairs} total, "
                    f"exact on {exact_done}]")
        else:
            self._summary_label.setText(
                f"⚠ Cancelled — {exact_done} pairs checked")
            sampled_results.clear()

        self._results = sampled_results
        self._populate_table()
