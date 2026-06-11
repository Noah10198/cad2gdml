"""
WidgetOCC - OCC 3D display widget.

Wraps Open CASCADE's 3D display pipeline using pythonocc-core.
Provides CAD model visualization with interactive controls:
- Mouse: left rotate, middle pan, wheel zoom
- Graduated trihedron (bottom-left)
- Origin markers with RGB coordinate lines
"""

from typing import Optional, Dict, List, Tuple

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QEvent
from PyQt6.QtGui import QPaintEngine

from OCC.Display.backend import load_backend
load_backend("pyqt6")

from OCC.Display import OCCViewer
from OCC.Core.AIS import (
    AIS_InteractiveContext, AIS_Shape, AIS_Shaded, AIS_WireFrame,
    AIS_Point, AIS_TextLabel
)
from OCC.Core.Geom import Geom_CartesianPoint
from OCC.Core.gp import gp_Pnt
from OCC.Core.Quantity import (
    Quantity_Color, Quantity_NOC_RED, Quantity_NOC_GREEN,
    Quantity_NOC_BLUE1, Quantity_NOC_GRAY, Quantity_NOC_GOLD,
    Quantity_NOC_BLACK, Quantity_NOC_WHITE, Quantity_TOC_RGB
)
from OCC.Core.Graphic3d import (
    Graphic3d_GraduatedTrihedron
)
from OCC.Core.Aspect import Aspect_TOTP_LEFT_LOWER
from OCC.Core.V3d import V3d_ZBUFFER
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.BRep import BRep_Builder
from OCC.Core.Prs3d import Prs3d_LineAspect
from OCC.Core.Aspect import Aspect_TOL_SOLID

from core.materials_lib import MaterialsLib


class ViewMode:
    """View display mode constants."""
    WIRE = 0
    SOLID = 1


class WidgetOCC(QWidget):
    """OCC 3D display widget with OCC 3D viewport."""

    sig_shape_selected = pyqtSignal(object)

    def __init__(self, library: MaterialsLib, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._library = library
        self._dark_bg = True

        self._display = OCCViewer.Viewer3d()
        self._inited = False
        self._native_window_id: Optional[int] = None

        self._displayed_shapes: Dict[str, AIS_Shape] = {}

        self._view_operation = 0
        self._last_mouse_pos: Optional[QPoint] = None
        self._current_mode = AIS_Shaded

        self._axis_origin: Optional[AIS_Point] = None
        self._axis_origin_lines: List[AIS_Shape] = []
        self._axis_origin_label: Optional[AIS_TextLabel] = None

        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ---- Display lifecycle ----

    def _ensure_display_valid(self) -> bool:
        try:
            current_win_id = int(self.winId())
        except Exception:
            return False
        needs_reinit = False
        if self._inited:
            if self._native_window_id != current_win_id:
                needs_reinit = True
            else:
                try:
                    _ = self._display.Context
                except Exception:
                    needs_reinit = True
        if needs_reinit or not self._inited:
            try:
                self._display.Create(window_handle=current_win_id, parent=self)
                self._display.SetModeShaded()
                self._display.View.SetBackgroundColor(
                    Quantity_Color(0.12, 0.12, 0.18, Quantity_TOC_RGB)
                )
                self._display.View.SetProj(1, 0, 1)
                self._display.View.FitAll()
                self._native_window_id = current_win_id
                self._inited = True
                self._init_axis()
                try:
                    self.View.TriedronDisplay(
                        Aspect_TOTP_LEFT_LOWER,
                        Quantity_Color(Quantity_NOC_GOLD),
                        0.08, V3d_ZBUFFER
                    )
                except Exception:
                    pass
                self._re_display_all_stored_shapes()
            except Exception as e:
                print(f"[OCC] Re-init failed: {e}", flush=True)
                return False
        return self._inited

    def set_dark_theme(self, is_dark: bool):
        self._dark_bg = is_dark
        if not self._inited:
            return
        try:
            if is_dark:
                self.View.SetBackgroundColor(
                    Quantity_Color(0.12, 0.12, 0.18, Quantity_TOC_RGB))
            else:
                self.View.SetBackgroundColor(
                    Quantity_Color(0.95, 0.95, 0.95, Quantity_TOC_RGB))
            self.View.Update()
        except Exception:
            pass

    def _re_display_all_stored_shapes(self):
        for ais in self._displayed_shapes.values():
            try:
                self.Context.Display(ais, False)
            except Exception:
                pass
        try:
            self.Context.UpdateCurrentViewer()
            self._display.FitAll()
        except Exception:
            pass

    def paintEngine(self) -> QPaintEngine:
        return None

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_display_valid()

    def paintEvent(self, event):
        if self._inited:
            try:
                self.View.MustBeResized()
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._inited:
            try:
                self.View.MustBeResized()
            except Exception:
                pass

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            old_state = event.oldState()
            new_state = self.windowState()
            if (old_state & Qt.WindowState.WindowMinimized) and not (new_state & Qt.WindowState.WindowMinimized):
                self._ensure_display_valid()
                if self._inited:
                    try:
                        self.View.MustBeResized()
                        self._display.Context.UpdateCurrentViewer()
                    except Exception:
                        pass

    @property
    def Context(self) -> AIS_InteractiveContext:
        self._ensure_display_valid()
        return self._display.Context

    @property
    def Viewer(self):
        self._ensure_display_valid()
        return self._display.Viewer

    @property
    def View(self):
        self._ensure_display_valid()
        return self._display.View

    def _init_axis(self):
        if not self._ensure_display_valid():
            return
        try:
            origin = gp_Pnt(0, 0, 0)
            red = Quantity_Color(1.0, 0.0, 0.0, Quantity_TOC_RGB)
            green = Quantity_Color(0.0, 1.0, 0.0, Quantity_TOC_RGB)
            blue = Quantity_Color(0.0, 0.0, 1.0, Quantity_TOC_RGB)
            self._axis_origin = AIS_Point(Geom_CartesianPoint(origin))
            self.Context.Display(self._axis_origin, False)
            self._create_origin_markers(30.0, red, green, blue)
            self._axis_origin_label = AIS_TextLabel()
            self._axis_origin_label.SetText("O")
            self._axis_origin_label.SetPosition(gp_Pnt(0, 0, 0))
            self._axis_origin_label.SetColor(Quantity_Color(1.0, 1.0, 1.0, Quantity_TOC_RGB))
            try:
                self._axis_origin_label.SetFont("Arial")
                self._axis_origin_label.SetHeight(20)
            except Exception:
                pass
            self.Context.Display(self._axis_origin_label, False)
            trihedron = Graphic3d_GraduatedTrihedron()
            trihedron.SetArrowsLength(0.1)
            trihedron.SetGridColor(Quantity_Color(Quantity_NOC_GRAY))
            trihedron.SetDrawGrid(True)
            trihedron.SetDrawAxes(True)
            trihedron.SetNamesFont("Arial")
            trihedron.SetNamesSize(20)
            trihedron.SetValuesFont("Arial")
            trihedron.SetValuesSize(16)
            self.View.GraduatedTrihedronDisplay(trihedron)
            self.Context.UpdateCurrentViewer()
        except Exception as e:
            print(f"[OCC] _init_axis error: {e}", flush=True)

    def _create_origin_markers(self, length: float, red=None, green=None, blue=None):
        if red is None:
            red = Quantity_Color(1.0, 0.0, 0.0, Quantity_TOC_RGB)
        if green is None:
            green = Quantity_Color(0.0, 1.0, 0.0, Quantity_TOC_RGB)
        if blue is None:
            blue = Quantity_Color(0.0, 0.0, 1.0, Quantity_TOC_RGB)
        try:
            for g in self._axis_origin_lines:
                try:
                    self.Context.Remove(g, False)
                except Exception:
                    pass
            self._axis_origin_lines = []
        except Exception:
            pass
        origin = gp_Pnt(0, 0, 0)
        x_line = self._make_edge_ais(origin, gp_Pnt(length, 0, 0), red, 0.5)
        y_line = self._make_edge_ais(origin, gp_Pnt(0, length, 0), green, 0.5)
        z_line = self._make_edge_ais(origin, gp_Pnt(0, 0, length), blue, 0.5)
        for ais in [x_line, y_line, z_line]:
            if ais is not None:
                try:
                    self.Context.Display(ais, False)
                    self._axis_origin_lines.append(ais)
                except Exception:
                    pass

    def _make_edge_ais(self, p1: gp_Pnt, p2: gp_Pnt, color, width: float = 1.0):
        try:
            edge = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
            builder = BRep_Builder()
            compound = TopoDS_Compound()
            builder.MakeCompound(compound)
            builder.Add(compound, edge)
            ais = AIS_Shape(compound)
            ais.SetDisplayMode(AIS_WireFrame)
            line_aspect = Prs3d_LineAspect(color, Aspect_TOL_SOLID, width)
            ais.Attributes().SetLineAspect(line_aspect)
            return ais
        except Exception:
            return None

    # ---- Cleanup ----

    def shutdown(self):
        """Properly release OCC display/OpenGL context before the parent window
        is destroyed, preventing 'wglMakeCurrent() has failed' errors."""
        self._inited = False
        if self._display is not None:
            try:
                self._display.Context.RemoveAll(True)
            except Exception:
                pass
            try:
                self._display.View.Remove()
            except Exception:
                pass
        self._display = None

    # ---- Shape display API ----

    def add_shape(self, ais_shape: AIS_Shape, color: Optional[Quantity_Color] = None,
                  update: bool = True, name: Optional[str] = None):
        if ais_shape is None:
            return
        if not self._ensure_display_valid():
            return
        try:
            if color is not None:
                ais_shape.SetColor(color)
            self.Context.Display(ais_shape, not update)
            key = name or f"_shape_{len(self._displayed_shapes)}"
            self._displayed_shapes[key] = ais_shape
            if update:
                self.Context.UpdateCurrentViewer()
        except Exception as e:
            print(f"[OCC] add_shape error: {e}", flush=True)

    def remove_shape(self, ais_shape: AIS_Shape, update: bool = True):
        if ais_shape is None:
            return
        if not self._ensure_display_valid():
            return
        try:
            self.Context.Remove(ais_shape, not update)
            if update:
                self.Context.UpdateCurrentViewer()
        except Exception:
            pass

    def set_shape_visible(self, ais_shape: AIS_Shape, visible: bool, update: bool = True):
        if ais_shape is None:
            return
        if not self._ensure_display_valid():
            return
        try:
            if visible:
                self.Context.Display(ais_shape, not update)
            else:
                self.Context.Erase(ais_shape, not update)
            if update:
                self.Context.UpdateCurrentViewer()
        except Exception:
            pass

    def set_shape_color(self, ais_shape: AIS_Shape, color: Quantity_Color):
        if ais_shape is None:
            return
        if not self._ensure_display_valid():
            return
        try:
            ais_shape.SetColor(color)
            self.Context.UpdateCurrentViewer()
        except Exception:
            pass

    def fresh(self):
        if not self._ensure_display_valid():
            return
        try:
            self.Context.UpdateCurrentViewer()
        except Exception:
            pass

    def fit_all(self):
        if not self._ensure_display_valid():
            return
        try:
            self._display.FitAll()
        except Exception:
            pass

    def set_view_mode(self, mode: int):
        if not self._ensure_display_valid():
            return
        try:
            self._current_mode = mode
            self.Context.SetDisplayMode(mode, True)
            self.Context.UpdateCurrentViewer()
        except Exception:
            pass

    def highlight_shape(self, ais_shape: AIS_Shape):
        if ais_shape is None:
            return
        if not self._ensure_display_valid():
            return
        try:
            self.Context.ClearSelected(True)
            self.Context.SetSelected(ais_shape, False)
            self.Context.UpdateCurrentViewer()
        except Exception:
            pass

    def clear_selection(self):
        if not self._ensure_display_valid():
            return
        try:
            self.Context.ClearSelected(True)
            self.Context.UpdateCurrentViewer()
        except Exception:
            pass

    # ---- Mouse events ----

    def mousePressEvent(self, event):
        if not self._ensure_display_valid():
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
        if not self._ensure_display_valid():
            return
        try:
            rx = int(event.position().x())
            ry = int(event.position().y())

            if event.button() == Qt.MouseButton.LeftButton:
                if self._view_operation == 0:
                    self.Context.MoveTo(rx, ry, self.View, True)
                    self.Context.Select(True)
                    self.Context.InitSelected()
                    if self.Context.MoreSelected():
                        selected = self.Context.SelectedInteractive()
                        self.sig_shape_selected.emit(selected)
                self._view_operation = 0
            elif event.button() == Qt.MouseButton.MiddleButton:
                self._view_operation = 0
        except Exception:
            pass

    def mouseMoveEvent(self, event):
        if not self._ensure_display_valid() or self._last_mouse_pos is None:
            return
        try:
            rx = int(event.position().x())
            ry = int(event.position().y())

            buttons = event.buttons()
            if buttons & Qt.MouseButton.LeftButton:
                if self._view_operation == 0:
                    self.View.StartRotation(rx, ry)
                    self._view_operation = 3
                self.View.Rotation(rx, ry)
            elif buttons & Qt.MouseButton.MiddleButton:
                dx = int(rx - self._last_mouse_pos.x())
                dy = int(self._last_mouse_pos.y() - ry)
                self.View.Pan(dx, dy)
            self._last_mouse_pos = event.position().toPoint()
        except Exception:
            pass

    def wheelEvent(self, event):
        if not self._ensure_display_valid():
            return
        try:
            delta = event.angleDelta().y()
            if delta > 0:
                self.View.SetZoom(1.1)
            else:
                self.View.SetZoom(0.9)
        except Exception:
            pass

    # ---- Bounding box computation ----

    def compute_shape_bounding_box(self, ais_shape: AIS_Shape) -> Optional[Tuple[float, float, float, float, float, float]]:
        """Compute axis-aligned bounding box of an AIS shape.

        Returns (x_min, y_min, z_min, x_max, y_max, z_max) or None on failure.
        """
        if ais_shape is None:
            return None
        try:
            shape = ais_shape.Shape()
            if shape is None or shape.IsNull():
                return None
            from OCC.Core.Bnd import Bnd_Box
            from OCC.Core.BRepBndLib import brepbndlib
            bbox = Bnd_Box()
            brepbndlib.Add(shape, bbox)
            return bbox.Get()
        except Exception as e:
            print(f"[OCC] compute_shape_bounding_box error: {e}", flush=True)
            return None
