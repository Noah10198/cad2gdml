"""
InterferenceDialog — CAD-level B-Rep interference check (no mesh required).

Uses OpenCASCADE BRepExtrema_DistShapeShape to compute minimum distance
between every pair of solid bodies, then classifies each pair as:
  🔴 Hard Interference  — shapes genuinely overlap
  🟡 Contact            — touching or very close (< 0.1 mm)
  🟢 Safe               — clearly separated (≥ 0.1 mm)

Clicking a row opens an **embedded OCC 3D preview** showing only the
selected pair with distinct colours and a red intersection curve.
No changes are made to the main OCC viewport.

Performance optimisation:
  - OBB pre-filter: compute oriented bounding boxes once, skip distant pairs
"""

from typing import Optional, List, Tuple
import csv
import time
import math

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLabel, QWidget, QProgressDialog,
    QApplication, QFrame, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

# OCC B-Rep tools
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Section
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.Quantity import (
    Quantity_Color, Quantity_NOC_BLUE1, Quantity_NOC_RED,
)

# OCC bounding box (oriented)
from OCC.Core.Bnd import Bnd_OBB
from OCC.Core.BRepBndLib import brepbndlib

from ui.occ_preview import OCCPreview


# ── Constants ─────────────────────────────────────────────────────────
CONTACT_THRESHOLD = 0.1  # mm


# ══════════════════════════════════════════════════════════════════════
#  Main Dialog
# ══════════════════════════════════════════════════════════════════════

class InterferenceDialog(QDialog):
    """Non-modal dialog showing B-Rep interference results with 3D preview."""

    OCC_SQUARE = 360  # px — fixed square side for the embedded 3D preview

    def __init__(self, geo_agent, parent: Optional[QWidget] = None,
                 import_dir: str = "",
                 log_callback: Optional[callable] = None):
        super().__init__(parent)
        self.setWindowTitle("Interference Check")
        self.setModal(False)
        self._import_dir = import_dir
        self._log_callback = log_callback

        # Fixed dialog size: OCC square * 1:1.8 ratio
        occ = self.OCC_SQUARE
        left_w = occ + 4
        right_w = int(occ * 1.8)
        dlg_w = left_w + 4 + right_w + 8
        dlg_h = 4 + 24 + 4 + 24 + 2 + occ + 4 + 32 + 4
        self.setFixedSize(dlg_w, dlg_h)

        self._geo_agent = geo_agent

        # Collect solid nodes with valid TopoDS_Shape
        self._solids: List[Tuple[str, str, TopoDS_Shape]] = []
        for node in geo_agent.get_all_solid_nodes():
            shape = node.shape
            if shape is not None and not shape.IsNull():
                self._solids.append((node.entry_id, node.name or node.entry_id[:12], shape))

        self._results: List[dict] = []
        self._build_ui()
        self._do_check()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)

        # Summary bar
        self._summary_label = QLabel("Checking...")
        self._summary_label.setTextFormat(Qt.TextFormat.RichText)
        self._summary_label.setStyleSheet(
            "font-size: 13px; padding: 4px;")
        self._summary_label.setFixedHeight(24)
        layout.addWidget(self._summary_label)

        # ── Center: fixed-width left (OCC) + right (table) ──
        center = QHBoxLayout()
        center.setSpacing(4)

        occ = self.OCC_SQUARE

        # ── Left: OCC 3D preview (fixed square) ──
        left_col = QWidget()
        left_col.setFixedWidth(occ + 4)
        lv = QVBoxLayout(left_col)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(2)

        self._pair_info = QLabel("Select a row to preview the pair")
        self._pair_info.setStyleSheet(
            "font-size: 13px; padding: 3px 6px; "
            "background-color: #14141F; color: #ffffff; border-radius: 3px;")
        self._pair_info.setFixedHeight(24)
        lv.addWidget(self._pair_info)

        self._occ_preview = OCCPreview()
        self._occ_preview.setFrameShape(QFrame.Shape.StyledPanel)
        self._occ_preview.setFixedSize(occ, occ)
        lv.addWidget(self._occ_preview)

        center.addWidget(left_col)

        # ── Right: results table ──
        right_col = QWidget()
        right_col.setFixedWidth(int(occ * 1.8))
        rv = QVBoxLayout(right_col)
        rv.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            ["", "Part A", "Part B", "Distance"])
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setStretchLastSection(True)
        self._table.itemClicked.connect(self._on_row_clicked)
        rv.addWidget(self._table)

        center.addWidget(right_col)
        layout.addLayout(center)

        # ── Bottom buttons ──
        btn_row = QHBoxLayout()
        self._recheck_btn = QPushButton("⟳ Re-check")
        self._recheck_btn.clicked.connect(self._do_check)
        btn_row.addWidget(self._recheck_btn)
        self._fit_btn = QPushButton("⊞ Fit Preview")
        self._fit_btn.clicked.connect(self._fit_preview)
        btn_row.addWidget(self._fit_btn)
        self._export_btn = QPushButton("⬇ Export Table")
        self._export_btn.clicked.connect(self._export_table)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.close)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

    # ── OBB helpers ──────────────────────────────────────────────────

    @staticmethod
    def _compute_bbox(shape: TopoDS_Shape) -> Bnd_OBB:
        """Compute an oriented bounding box (OBB) for a shape.

        OBB follows the shape's natural orientation, producing a much
        tighter fit than AABB for tilted / slender parts (beams, pipes).
        This reduces false positives in the pre-filter.
        """
        obb = Bnd_OBB()
        brepbndlib.AddOBB(shape, obb)
        return obb

    @staticmethod
    def _obb_corners(obb: Bnd_OBB):
        """Return the 8 corner coordinates of an OBB as list of gp_XYZ."""
        c = obb.Center()
        axes = [obb.XDirection(), obb.YDirection(), obb.ZDirection()]
        half = [obb.XHSize(), obb.YHSize(), obb.ZHSize()]
        corners = []
        for i in range(8):
            p = c
            p = p.Added(axes[0].Multiplied(half[0] if (i & 1) else -half[0]))
            p = p.Added(axes[1].Multiplied(half[1] if (i & 2) else -half[1]))
            p = p.Added(axes[2].Multiplied(half[2] if (i & 4) else -half[2]))
            corners.append(p)
        return corners

    @staticmethod
    def _bbox_distance_sq(box_a: Bnd_OBB, box_b: Bnd_OBB) -> float:
        """Squared minimum distance between two OBBs (0 if they overlap).

        Uses IsOut() for the overlap test (fast), and falls back to
        minimum vertex-to-vertex distance for separated boxes.
        """
        if not box_a.IsOut(box_b):
            return 0.0  # boxes overlap

        # Minimum vertex-vertex distance (conservative, but sufficient
        # for a pre-filter — overestimates slightly at worst).
        corners_a = InterferenceDialog._obb_corners(box_a)
        corners_b = InterferenceDialog._obb_corners(box_b)
        min_d2 = float('inf')
        for ca in corners_a:
            for cb in corners_b:
                d2 = (ca.X() - cb.X())**2 + (ca.Y() - cb.Y())**2 + (ca.Z() - cb.Z())**2
                if d2 < min_d2:
                    min_d2 = d2
                    if min_d2 == 0.0:
                        return 0.0
        return min_d2

    # ── Core check ────────────────────────────────────────────────────

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
        progress = QProgressDialog(
            f"Checking {total_pairs} pairs...", "Cancel", 0, total_pairs, self)
        progress.setWindowTitle("Interference Check")
        progress.setModal(True)
        progress.show()
        QApplication.processEvents()

        # ── Phase 1: pre-compute bounding boxes for all solids ─────────
        t0_bbox = time.time()
        bboxes = [self._compute_bbox(s[2]) for s in self._solids]
        t_bbox = time.time() - t0_bbox

        # ── Phase 2: OBB pre-filter → exact check on close pairs ────
        cancelled = False
        t0 = time.time()
        hard_count = contact_count = safe_count = obb_skipped = 0
        done = 0

        for i in range(n):
            if cancelled:
                break
            box_a = bboxes[i]
            id_a, name_a, shape_a = self._solids[i]
            for j in range(i + 1, n):
                if cancelled:
                    break
                box_b = bboxes[j]
                id_b, name_b, shape_b = self._solids[j]

                # Fast OBB pre-filter (nanosecond-grade math)
                bdist_sq = self._bbox_distance_sq(box_a, box_b)
                if bdist_sq > CONTACT_THRESHOLD * CONTACT_THRESHOLD:
                    # OBBs are far apart → trivially safe, no OCC call needed
                    d = math.sqrt(bdist_sq) if bdist_sq > 0 else 0.0
                    self._results.append(self._make_result(
                        i, j, id_a, name_a, id_b, name_b,
                        "safe", d, shape_a, shape_b))
                    obb_skipped += 1
                else:
                    # OBBs close/overlapping → run exact B-Rep classification
                    status, distance = self._classify_pair(shape_a, shape_b)
                    self._results.append(self._make_result(
                        i, j, id_a, name_a, id_b, name_b,
                        status, distance, shape_a, shape_b))
                    hard_count += (status == "hard")
                    contact_count += (status == "contact")
                    safe_count += (status == "safe")

                done += 1
                progress.setValue(done)
                if progress.wasCanceled():
                    cancelled = True
                    break

        progress.close()
        elapsed = time.time() - t0

        if not cancelled:
            parts = (
                '<span style="color:#ff4444;">■</span> Hard: '
                f"{hard_count}  "
                '<span style="color:#ffaa00;">■</span> Contact: '
                f"{contact_count}  "
                '<span style="color:#44cc44;">■</span> Safe: '
                f"{safe_count}"
            )
            self._summary_label.setText(
                f"{len(self._results)} pairs checked in {elapsed:.1f}s"
                f"  (bbox: {t_bbox:.2f}s)"
                f"  |  {parts}"
            )
            if self._log_callback:
                self._log_callback(
                    f"Interference check completed ({elapsed:.1f}s): "
                    f"{hard_count} hard, {contact_count} contact, "
                    f"{safe_count} safe (OBB filter: {obb_skipped} skipped)")
        else:
            self._summary_label.setText(
                f"⚠ Cancelled — {len(self._results)} / {total_pairs} pairs checked"
            )
            if self._log_callback:
                self._log_callback(
                    f"Interference check cancelled — {len(self._results)} / {total_pairs} pairs")
            self._results.clear()

        self._populate_table()

    # ── Helper: build result dict without repeating boilerplate ───────

    @staticmethod
    def _make_result(i, j, id_a, name_a, id_b, name_b,
                     status, distance, shape_a, shape_b):
        return {
            "i": i, "j": j,
            "id_a": id_a, "name_a": name_a,
            "id_b": id_b, "name_b": name_b,
            "status": status, "distance": distance,
            "shape_a": shape_a, "shape_b": shape_b,
        }

    # ── Classification ────────────────────────────────────────────────

    @staticmethod
    def _classify_pair(shape_a: TopoDS_Shape,
                       shape_b: TopoDS_Shape) -> Tuple[str, float]:
        try:
            dist = BRepExtrema_DistShapeShape(shape_a, shape_b)
            if not dist.IsDone():
                return ("unknown", float("inf"))
            d = dist.Value()
        except Exception:
            return ("unknown", float("inf"))

        if d > CONTACT_THRESHOLD:
            return ("safe", d)
        if d > 1e-6:
            return ("contact", d)

        # Distance ≈ 0 — section check to distinguish overlap from touch
        try:
            section = BRepAlgoAPI_Section(shape_a, shape_b)
            section.Build()
            if section.IsDone():
                result = section.Shape()
                exp_f = TopExp_Explorer(result, TopAbs_FACE)
                exp_e = TopExp_Explorer(result, TopAbs_EDGE)
                if exp_f.More() or exp_e.More():
                    return ("hard", -0.001)
                return ("contact", 0.0)
        except Exception:
            pass
        return ("contact", 0.0)

    # ── Table population ──────────────────────────────────────────────

    def _populate_table(self):
        self._table.setRowCount(0)
        line_color = {
            "hard": QColor("#ff4444"),
            "contact": QColor("#ffaa00"),
            "safe": QColor("#44cc44"),
            "unknown": QColor(180, 180, 180),
        }
        bg_map = {
            "hard": QColor(255, 220, 220),
            "contact": QColor(255, 255, 210),
            "safe": QColor(220, 255, 220),
            "unknown": QColor(240, 240, 240),
        }

        for row_data in self._results:
            row = self._table.rowCount()
            self._table.insertRow(row)

            icon_item = QTableWidgetItem("■")
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            fg = line_color.get(row_data["status"], QColor(180, 180, 180))
            icon_item.setForeground(fg)
            self._table.setItem(row, 0, icon_item)
            self._table.setItem(row, 1, QTableWidgetItem(row_data["name_a"]))
            self._table.setItem(row, 2, QTableWidgetItem(row_data["name_b"]))

            d = row_data["distance"]
            text = "Overlap" if row_data["status"] == "hard" else (
                "—" if d == float("inf") else f"{d:.4f} mm")
            dist_item = QTableWidgetItem(text)
            dist_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 3, dist_item)

            color = bg_map.get(row_data["status"])
            if color:
                for col in range(4):
                    self._table.item(row, col).setBackground(color)

    # ── Row click → embedded OCC preview ──────────────────────────────

    def _on_row_clicked(self, item: QTableWidgetItem):
        row = item.row()
        if row < 0 or row >= len(self._results):
            return

        data = self._results[row]
        shape_a: TopoDS_Shape = data["shape_a"]
        shape_b: TopoDS_Shape = data["shape_b"]

        # Clear previous preview
        self._occ_preview.clear_all()

        # Display both shapes in blue (semi-transparent) — same colour
        self._occ_preview.display_shape(
            shape_a, Quantity_Color(Quantity_NOC_BLUE1), transparency=0.55)
        self._occ_preview.display_shape(
            shape_b, Quantity_Color(Quantity_NOC_BLUE1), transparency=0.55)

        # If hard interference, compute and show intersection as thick red curves.
        # Wireframe mode with a heavy line aspect is used for visibility.
        if data["status"] == "hard":
            try:
                section = BRepAlgoAPI_Section(shape_a, shape_b)
                section.Build()
                if section.IsDone():
                    result = section.Shape()
                    exp_e = TopExp_Explorer(result, TopAbs_EDGE)
                    exp_f = TopExp_Explorer(result, TopAbs_FACE)
                    if exp_e.More() or exp_f.More():
                        self._occ_preview.display_edges_thick(
                            result,
                            Quantity_Color(Quantity_NOC_RED),
                            line_width=12.0)
            except Exception:
                pass

        self._occ_preview.fit_all()
        self._occ_preview.refresh()

    def _fit_preview(self):
        self._occ_preview.fit_all()
        self._occ_preview.refresh()

    # ── Export ────────────────────────────────────────────────────────

    def _export_table(self):
        """Export the results table as a CSV file using a relative path."""
        if not self._results:
            return

        # Default to the same directory as the last STEP import
        default_dir = self._import_dir if self._import_dir else os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        default_path = os.path.join(default_dir, "interference_report.csv")

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Table", default_path,
            "CSV Files (*.csv);;All Files (*)")
        if not path:
            return

        try:
            status_map = {"hard": "Hard", "contact": "Contact",
                          "safe": "Safe", "unknown": "Unknown"}
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Status", "Part A", "Part B", "Distance (mm)"])
                for r in self._results:
                    d = r["distance"]
                    dist_str = (f"{d:.4f}" if d not in (float("inf"), -0.001)
                                else ("Overlap" if r["status"] == "hard" else "—"))
                    writer.writerow([
                        status_map.get(r["status"], "Unknown"),
                        r["name_a"],
                        r["name_b"],
                        dist_str,
                    ])
        except OSError as e:
            QMessageBox.warning(self, "Export Error", f"Failed to write:\n{e}")

    # ── Cleanup ───────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._occ_preview.shutdown()
        super().closeEvent(event)
