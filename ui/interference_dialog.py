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
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor

# OCC B-Rep tools
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Section
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.Quantity import (
    Quantity_Color, Quantity_TOC_RGB,
    Quantity_NOC_BLUE1, Quantity_NOC_RED,
)

# OCC bounding box (oriented)
from OCC.Core.Bnd import Bnd_OBB
from OCC.Core.BRepBndLib import brepbndlib

# OCC 3D viewer
from OCC.Display import OCCViewer

# OCC display helpers
from OCC.Core.AIS import AIS_Shape, AIS_WireFrame
from OCC.Core.Prs3d import Prs3d_LineAspect
from OCC.Core.Aspect import Aspect_TOL_SOLID


# ── Constants ─────────────────────────────────────────────────────────
CONTACT_THRESHOLD = 0.1  # mm


# ══════════════════════════════════════════════════════════════════════
#  Mini OCC 3D Viewer Widget
# ══════════════════════════════════════════════════════════════════════

class _OCCPreview(QFrame):
    """Lightweight OCC 3D viewport for previewing a single pair.

    Mirrors the pattern from WidgetOCC (paintEngine → None, paintEvent → MustBeResized)
    to avoid Qt/OCC native-window conflicts.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._display: Optional[OCCViewer.Viewer3d] = None
        self._inited = False
        self._native_win: Optional[int] = None
        self._displayed: List = []

        # Mouse interaction state
        self._view_operation = 0
        self._last_mouse_pos: Optional[QPoint] = None

    def paintEngine(self):
        return None

    def paintEvent(self, event):
        if self._inited:
            try:
                self._display.View.MustBeResized()
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._inited:
            try:
                self._display.View.MustBeResized()
            except Exception:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_display()

    # ---- OCC helpers ----

    def _ensure_display(self) -> bool:
        try:
            wid = int(self.winId())
        except Exception:
            return False
        if self._inited and self._native_win == wid:
            return True
        try:
            self._display = OCCViewer.Viewer3d()
            self._display.Create(window_handle=wid, parent=self)
            self._display.SetModeShaded()
            self._display.View.SetBackgroundColor(
                Quantity_Color(0.08, 0.08, 0.12, Quantity_TOC_RGB)
            )
            self._display.View.SetProj(0.5, -0.5, 0.7)
            self._native_win = wid
            self._inited = True
        except Exception as e:
            print(f"[OCCPreview] Init failed: {e}", flush=True)
            return False
        return True

    def display_shape(self, shape: TopoDS_Shape,
                      color: Optional[Quantity_Color] = None,
                      transparency: float = 0.0) -> object:
        if not self._ensure_display():
            return None
        try:
            ais = self._display.DisplayShape(shape, update=False)
            if color is not None and ais:
                items = ais if isinstance(ais, (list, tuple)) else [ais]
                for a in items:
                    a.SetColor(color)
                    if transparency > 0:
                        a.SetTransparency(transparency)
            self._displayed.append(ais)
            return ais
        except Exception as e:
            print(f"[OCCPreview] display_shape error: {e}", flush=True)
            return None

    def clear_all(self):
        if self._display and self._inited:
            try:
                self._display.Context.RemoveAll(True)
            except Exception:
                pass
        self._displayed.clear()

    def fit_all(self):
        if self._display and self._inited:
            try:
                self._display.FitAll()
            except Exception:
                pass

    def refresh(self):
        if self._display and self._inited:
            try:
                self._display.Context.UpdateCurrentViewer()
            except Exception:
                pass

    def display_edges_thick(self, shape: TopoDS_Shape,
                             color: Quantity_Color,
                             line_width: float = 12.0) -> object:
        """Display a shape's edges as thick coloured lines (wireframe mode).
        Uses Prs3d_LineAspect to set a wide line width for visibility."""
        if not self._ensure_display():
            return None
        try:
            ais = AIS_Shape(shape)
            ais.SetDisplayMode(AIS_WireFrame)
            line_aspect = Prs3d_LineAspect(color, Aspect_TOL_SOLID, line_width)
            ais.Attributes().SetLineAspect(line_aspect)
            self._display.Context.Display(ais, False)
            self._displayed.append(ais)
            return ais
        except Exception as e:
            print(f"[OCCPreview] display_edges_thick error: {e}", flush=True)
            return None

    def shutdown(self):
        """Properly release the OCC display/OpenGL context before Qt destroys
        the native window handle, preventing 'wglMakeCurrent() has failed' errors."""
        if self._inited and self._display is not None:
            try:
                self._display.Context.RemoveAll(True)
            except Exception:
                pass
            try:
                # Remove the view from the viewer — releases the native window binding
                self._display.View.Remove()
            except Exception:
                pass
        self._inited = False
        self._display = None

    # ---- Mouse interaction ----

    def mousePressEvent(self, event):
        if not self._inited:
            return
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self._last_mouse_pos = event.position().toPoint()
                self._view_operation = 0
            elif event.button() == Qt.MouseButton.MiddleButton:
                self._last_mouse_pos = event.position().toPoint()
                self._view_operation = 1
        except Exception:
            pass

    def mouseReleaseEvent(self, event):
        if not self._inited:
            return
        self._view_operation = 0

    def mouseMoveEvent(self, event):
        if not self._inited or self._last_mouse_pos is None:
            return
        try:
            rx = int(event.position().x())
            ry = int(event.position().y())
            buttons = event.buttons()
            if buttons & Qt.MouseButton.LeftButton:
                if self._view_operation == 0:
                    self._display.View.StartRotation(rx, ry)
                    self._view_operation = 3
                self._display.View.Rotation(rx, ry)
            elif buttons & Qt.MouseButton.MiddleButton:
                dx = int(rx - self._last_mouse_pos.x())
                dy = int(self._last_mouse_pos.y() - ry)
                self._display.View.Pan(dx, dy)
            self._last_mouse_pos = event.position().toPoint()
        except Exception:
            pass

    def wheelEvent(self, event):
        if not self._inited:
            return
        try:
            delta = event.angleDelta().y()
            if delta > 0:
                self._display.View.SetZoom(1.1)
            else:
                self._display.View.SetZoom(0.9)
        except Exception:
            pass


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

        self._occ_preview = _OCCPreview()
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
