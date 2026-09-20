"""
occ_preview.py -- a small standalone OCC viewport for a dialog.

Extracted from interference_dialog.py, which had the only copy of it: the
interference table and the mesh-group window both need "show me these shapes
on their own, turnable, next to a table", and neither may touch the main
viewport. Mirrors the pattern from WidgetOCC (paintEngine -> None, paintEvent
-> MustBeResized) to avoid Qt/OCC native-window conflicts.
"""

from typing import Optional, List

from PyQt6.QtWidgets import QFrame, QWidget
from PyQt6.QtCore import Qt, QPoint

from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCC.Core.AIS import AIS_Shape, AIS_WireFrame
from OCC.Core.Prs3d import Prs3d_LineAspect
from OCC.Core.Aspect import Aspect_TOL_SOLID

from OCC.Display import OCCViewer

from utils.occ_quiet import new_viewer


class OCCPreview(QFrame):
    """Lightweight OCC 3D viewport for previewing shapes inside a dialog."""

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
            self._display = new_viewer(wid, self)
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
                self._display.View.Remove()
            except Exception:
                pass
            try:
                self._display.Viewer.Remove()
            except Exception:
                pass
        self._display = None
        self._inited = False
        self._native_win = None
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
