"""
ExportGdmlDialog — non-modal dialog for configuring and generating GDML export.

Layout:
  Left:    Embedded OCC 3D preview (blue transparent parts + world wireframe)
  Right:   World volume factor dropdown, output file path, Export button
"""

import os
import shutil
from typing import Optional, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QLineEdit, QFileDialog, QWidget, QFrame,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor

from OCC.Display import OCCViewer
from OCC.Core.AIS import AIS_Shape, AIS_WireFrame
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCC.Core.Prs3d import Prs3d_LineAspect
from OCC.Core.Aspect import Aspect_TOL_SOLID
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.gp import gp_Pnt
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox

from core.g_data_node import GDataNode
from core.materials_lib import MaterialsLib
from core.gdml_generator import compute_global_bbox, generate_gdml


# ────────────────────────────── OCC preview ──────────────────────────────


class _GDMLPreview(QFrame):
    """Lightweight embedded OCC 3D viewport for GDML export preview.

    Displays all parts as blue semi-transparent solids and the world box
    as a gray wireframe.  Mouse: left → rotate, middle → pan, wheel → zoom.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(380, 380)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._display: Optional[OCCViewer.Viewer3d] = None
        self._inited = False
        self._native_win: Optional[int] = None

        # mouse state
        self._view_op = 0
        self._last_pos: Optional[QPoint] = None

    # ---- Qt overrides ----
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

    # ---- OCC init ----
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
            print(f"[GDMLPreview] init failed: {e}", flush=True)
            return False
        return True

    def is_valid(self) -> bool:
        return self._inited

    # ---- display helpers ----
    def display_part(self, shape: TopoDS_Shape):
        """Add a geometry part as blue semi-transparent."""
        if not self._ensure_display():
            return
        try:
            ais = self._display.DisplayShape(shape, update=False)
            items = ais if isinstance(ais, (list, tuple)) else [ais]
            blue = Quantity_Color(0.2, 0.4, 0.9, Quantity_TOC_RGB)
            for a in items:
                a.SetColor(blue)
                a.SetTransparency(0.55)
        except Exception:
            pass

    def display_world_box(self, half: float):
        """Add a wireframe cube *[-half, half]³* centered at origin."""
        if not self._ensure_display():
            return
        try:
            from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
            box_shape = BRepPrimAPI_MakeBox(
                gp_Pnt(-half, -half, -half),
                gp_Pnt(half, half, half),
            ).Shape()
            ais = AIS_Shape(box_shape)
            ais.SetDisplayMode(AIS_WireFrame)
            gray = Quantity_Color(0.6, 0.6, 0.6, Quantity_TOC_RGB)
            aspect = Prs3d_LineAspect(gray, Aspect_TOL_SOLID, 1.5)
            ais.Attributes().SetLineAspect(aspect)
            self._display.Context.Display(ais, False)
        except Exception:
            pass

    def clear_all(self):
        if self._display and self._inited:
            try:
                self._display.Context.RemoveAll(True)
            except Exception:
                pass

    def fit_all(self):
        if self._display and self._inited:
            try:
                self._display.FitAll()
            except Exception:
                pass

    # ---- mouse interaction ----
    def mousePressEvent(self, event):
        if not self._inited:
            return
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self._last_pos = event.position().toPoint()
                self._view_op = 0
            elif event.button() == Qt.MouseButton.MiddleButton:
                self._last_pos = event.position().toPoint()
                self._view_op = 1
        except Exception:
            pass

    def mouseReleaseEvent(self, event):
        self._view_op = 0

    def mouseMoveEvent(self, event):
        if not self._inited or self._last_pos is None:
            return
        try:
            rx = int(event.position().x())
            ry = int(event.position().y())
            buttons = event.buttons()
            if buttons & Qt.MouseButton.LeftButton:
                if self._view_op == 0:
                    self._display.View.StartRotation(rx, ry)
                    self._view_op = 3
                self._display.View.Rotation(rx, ry)
            elif buttons & Qt.MouseButton.MiddleButton:
                dx = rx - self._last_pos.x()
                dy = self._last_pos.y() - ry
                self._display.View.Pan(int(dx), int(dy))
            self._last_pos = event.position().toPoint()
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


# ────────────────────────────── main dialog ──────────────────────────────


class ExportGdmlDialog(QDialog):
    """Non-modal dialog for GDML export configuration."""

    FACTORS = [3, 5, 10, 100]
    DEFAULT_WORLD_MATS = ["G4_AIR", "G4_Galactic"]

    def __init__(
        self,
        solid_nodes: List[GDataNode],
        meshed_nodes: dict,
        mat_lib: MaterialsLib,
        export_root: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Export GDML")
        self.setMinimumSize(780, 520)
        self.resize(820, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._solid_nodes = solid_nodes
        self._meshed_nodes = meshed_nodes
        self._mat_lib = mat_lib
        self._export_root = export_root

        # Compute bbox once
        self._max_edge, _, _ = compute_global_bbox(solid_nodes)

        self._build_ui()
        # Defer preview population to showEvent so OCC widget is initialized

    # ---- UI construction ----

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ---- Left: OCC preview ----
        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("Preview"))
        self._preview = _GDMLPreview()
        left_panel.addWidget(self._preview, 1)
        main_layout.addLayout(left_panel, 3)

        # ---- Right: controls ----
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)

        # World volume factor
        right_panel.addWidget(QLabel("<b>World Volume</b>"))
        factor_layout = QHBoxLayout()
        factor_layout.addWidget(QLabel("Factor:"))
        self._factor_combo = QComboBox()
        for f in self.FACTORS:
            self._factor_combo.addItem(f"× {f}", f)
        self._factor_combo.setCurrentIndex(1)  # default ×5
        self._factor_combo.currentIndexChanged.connect(self._on_factor_changed)
        factor_layout.addWidget(self._factor_combo)
        right_panel.addLayout(factor_layout)

        self._size_label = QLabel()
        right_panel.addWidget(self._size_label)

        # ---- World volume material ----
        right_panel.addSpacing(6)
        right_panel.addWidget(QLabel("<b>World Material</b>"))
        mat_layout = QHBoxLayout()
        self._world_mat_combo = QComboBox()
        self._world_mat_combo.setEditable(True)
        self._world_mat_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for m in self.DEFAULT_WORLD_MATS:
            self._world_mat_combo.addItem(m)
        self._world_mat_combo.setCurrentText("G4_AIR")
        self._world_mat_combo.editTextChanged.connect(self._on_world_mat_changed)
        self._world_mat_status = QLabel("")
        self._world_mat_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        mat_layout.addWidget(self._world_mat_combo, 1)
        mat_layout.addWidget(self._world_mat_status)
        right_panel.addLayout(mat_layout)

        # Output file
        right_panel.addSpacing(10)
        right_panel.addWidget(QLabel("<b>Output File</b>"))
        path_layout = QHBoxLayout()
        self._path_edit = QLineEdit()
        default_gdml_dir = os.path.join(self._export_root, "exportgdml")
        self._path_edit.setText(
            os.path.join(default_gdml_dir, "export.gdml")
        )
        path_layout.addWidget(self._path_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_path)
        path_layout.addWidget(browse_btn)
        right_panel.addLayout(path_layout)

        right_panel.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        fit_btn = QPushButton("Fit View")
        fit_btn.clicked.connect(self._preview.fit_all)
        btn_layout.addWidget(fit_btn)

        btn_layout.addStretch()

        export_btn = QPushButton("Export GDML")
        export_btn.setStyleSheet(
            "background-color: #0078d4; color: white; "
            "border: none; border-radius: 6px; padding: 8px 24px; "
            "font-weight: bold; font-size: 13px;"
        )
        export_btn.clicked.connect(self._on_export)
        btn_layout.addWidget(export_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        right_panel.addLayout(btn_layout)
        main_layout.addLayout(right_panel, 2)

        self._update_size_label()
        self._validate_world_mat("G4_AIR")

    # ---- deferred init ----

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.processEvents()
        self._populate_preview()

    # ---- world box label ----

    def _update_size_label(self):
        factor = self._factor_combo.currentData()
        half = self._max_edge * factor / 2.0
        size = half * 2
        self._size_label.setText(
            f"World: {size:.1f} × {size:.1f} × {size:.1f} mm"
        )

    def _on_factor_changed(self):
        self._update_size_label()
        self._populate_preview()

    # ---- path browsing ----

    def _browse_path(self):
        current = self._path_edit.text()
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save GDML File", current, "GDML Files (*.gdml);;All Files (*)"
        )
        if chosen:
            if not chosen.lower().endswith(".gdml"):
                chosen += ".gdml"
            self._path_edit.setText(chosen)

    # ---- world material validation ----

    def _validate_world_mat(self, text: str) -> bool:
        """Validate world material against the library.  Case-sensitive."""
        text = text.strip()
        if not text:
            self._world_mat_status.setText("⚠ empty")
            self._world_mat_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            return False
        if text in self.DEFAULT_WORLD_MATS:
            self._world_mat_status.setText("✓ known")
            self._world_mat_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            return True
        # Check NIST global materials
        global_mats = self._mat_lib.get_all_global_materials()
        if text in global_mats:
            self._world_mat_status.setText("✓ global")
            self._world_mat_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            return True
        # Check local materials
        local_names = self._mat_lib.get_local_material_names()
        if text in local_names:
            self._world_mat_status.setText("✓ local")
            self._world_mat_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            return True
        # Not found anywhere
        self._world_mat_status.setText("⚠ not found")
        self._world_mat_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
        return False

    def _on_world_mat_changed(self, text: str):
        self._validate_world_mat(text)

    # ---- populate preview ----

    def _populate_preview(self):
        # Don't early-return on is_valid — display_part calls _ensure_display internally
        self._preview.clear_all()
        factor = self._factor_combo.currentData()
        half = self._max_edge * factor / 2.0
        for node in self._solid_nodes:
            shape = node.shape
            if shape is not None and not shape.IsNull():
                self._preview.display_part(shape)
        self._preview.display_world_box(half)
        self._preview.fit_all()

    # ---- export ----

    def _on_export(self):
        output_path = self._path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "Warning", "Please specify an output file path.")
            return

        # Clear and recreate the exportgdml directory before writing
        gdml_dir = os.path.join(self._export_root, "exportgdml")
        try:
            if os.path.isdir(gdml_dir):
                shutil.rmtree(gdml_dir)
            os.makedirs(gdml_dir, exist_ok=True)
        except OSError:
            pass

        world_mat = self._world_mat_combo.currentText().strip()
        if not world_mat:
            QMessageBox.warning(self, "Warning", "Please specify a world volume material.")
            return

        # Validate world material one last time before export
        if not self._validate_world_mat(world_mat):
            ret = QMessageBox.question(
                self, "Unknown Material",
                f"The world material '{world_mat}' is not found in the material library.\n\n"
                "The GDML file will still be generated, but Geant4 may not find this material.\n\n"
                "Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        factor = self._factor_combo.currentData()

        ok = generate_gdml(
            solid_nodes=self._solid_nodes,
            meshed_nodes=self._meshed_nodes,
            mat_lib=self._mat_lib,
            output_path=output_path,
            world_factor=factor,
            world_material_name=world_mat,
        )

        if ok:
            QMessageBox.information(
                self, "Success",
                f"GDML exported successfully.\n{output_path}",
            )
            self.accept()
        else:
            QMessageBox.critical(
                self, "Error",
                "GDML export failed.\n"
                "Make sure parts have been meshed first.",
            )
