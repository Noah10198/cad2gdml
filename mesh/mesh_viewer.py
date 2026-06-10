"""
MeshViewer - Standalone, non-blocking 3D mesh preview window.

Uses QVTKRenderWindowInteractor (based on QOpenGLWidget for PyQt6),
which provides a properly initialized OpenGL context with correct
pixel format for VTK rendering.

Opens as a separate QDialog (non-modal, like MATLAB figure popups).
"""

import os
from typing import Optional, List, Dict

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
)
from PyQt6.QtCore import Qt

# ---- VTK imports ----
from vtkmodules.vtkIOLegacy import vtkUnstructuredGridReader
from vtkmodules.vtkFiltersCore import vtkAppendFilter
from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter
from vtkmodules.vtkRenderingCore import (
    vtkActor, vtkPolyDataMapper, vtkRenderer
)
from vtkmodules.vtkRenderingAnnotation import vtkCubeAxesActor
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
# Ensure backends are loaded
import vtkmodules.vtkRenderingOpenGL2
import vtkmodules.vtkInteractionStyle


class MeshViewer(QDialog):
    """Standalone, non-blocking VTK mesh preview window."""

    def __init__(self, parent: Optional['QWidget'] = None):
        super().__init__(parent)
        self.setWindowTitle("Mesh Preview")
        self.setMinimumSize(900, 650)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        # VTK state
        self._renderer: Optional[vtkRenderer] = None
        self._mesh_actor: Optional[vtkActor] = None
        self._cube_axes: Optional[vtkCubeAxesActor] = None
        self._mesh_paths: List[str] = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # VTK widget - QVTKRenderWindowInteractor uses QOpenGLWidget internally,
        # providing a proper OpenGL context with correct pixel format
        self._vtk_widget = QVTKRenderWindowInteractor(self)
        layout.addWidget(self._vtk_widget, 1)

        # Bottom toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._info_label = QLabel("No mesh loaded")
        toolbar.addWidget(self._info_label, 1)

        btn_fit = QPushButton("Fit All")
        btn_fit.clicked.connect(self._fit_all)
        toolbar.addWidget(btn_fit)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        toolbar.addWidget(btn_close)

        layout.addLayout(toolbar)

        # ---- VTK setup ----
        render_window = self._vtk_widget.GetRenderWindow()

        self._renderer = vtkRenderer()
        self._renderer.SetBackground(0.2, 0.25, 0.3)  # Dark slate
        render_window.AddRenderer(self._renderer)

        # Set up interactor style
        interactor = self._vtk_widget.GetRenderWindow().GetInteractor()
        style = vtkInteractorStyleTrackballCamera()
        interactor.SetInteractorStyle(style)

        self._vtk_widget.Initialize()
        self._vtk_widget.Start()

    # ---- Public API ----

    def load_mesh(self, mesh_paths: Dict[str, str]):
        """Load one or more VTK mesh files and display them.

        Args:
            mesh_paths: Dictionary mapping node entry_id -> vtk file path
        """
        paths = list(mesh_paths.values())
        self._mesh_paths = paths
        self._render_mesh()

    def load_mesh_files(self, file_paths: List[str]):
        """Load a list of VTK file paths directly."""
        self._mesh_paths = file_paths
        self._render_mesh()

    # ---- Rendering ----

    def _render_mesh(self):
        """Build and display the VTK mesh from loaded file paths."""
        if not self._renderer or not self._mesh_paths:
            return

        # Remove old actors
        if self._mesh_actor:
            self._renderer.RemoveActor(self._mesh_actor)
            self._mesh_actor = None
        if self._cube_axes:
            self._renderer.RemoveActor(self._cube_axes)
            self._cube_axes = None

        # Read and append all VTK files
        append_filter = vtkAppendFilter()
        total_cells = 0

        for fpath in self._mesh_paths:
            if not os.path.exists(fpath):
                continue
            try:
                reader = vtkUnstructuredGridReader()
                reader.SetFileName(fpath)
                reader.Update()
                output = reader.GetOutput()
                if output and output.GetNumberOfCells() > 0:
                    append_filter.AddInputData(output)
                    total_cells += output.GetNumberOfCells()
            except Exception as e:
                print(f"[MeshViewer] Error reading {fpath}: {e}")

        if total_cells == 0:
            self._info_label.setText("No mesh data loaded")
            return

        append_filter.Update()

        # Convert vtkUnstructuredGrid -> vtkPolyData for the mapper
        surface_filter = vtkGeometryFilter()
        surface_filter.SetInputConnection(append_filter.GetOutputPort())
        surface_filter.Update()

        # Mapper + Actor
        mapper = vtkPolyDataMapper()
        mapper.SetInputConnection(surface_filter.GetOutputPort())
        mapper.ScalarVisibilityOff()

        self._mesh_actor = vtkActor()
        self._mesh_actor.SetMapper(mapper)

        # Surface properties - warm orange color for contrast
        prop = self._mesh_actor.GetProperty()
        prop.SetColor(0.9, 0.6, 0.15)          # Orange (contrasts with dark bg)
        prop.SetEdgeColor(0.1, 0.1, 0.1)        # Dark edges
        prop.SetEdgeVisibility(True)
        prop.SetLineWidth(1.0)
        prop.SetAmbient(0.15)
        prop.SetDiffuse(0.8)
        prop.SetSpecular(0.05)

        self._renderer.AddActor(self._mesh_actor)

        # Cube axes annotation
        bounds = self._mesh_actor.GetBounds()
        if bounds and all(abs(v) < 1e10 for v in bounds):
            self._cube_axes = vtkCubeAxesActor()
            self._cube_axes.SetBounds(bounds)
            self._cube_axes.SetCamera(self._renderer.GetActiveCamera())
            self._cube_axes.SetXLabelFormat("%.2f")
            self._cube_axes.SetYLabelFormat("%.2f")
            self._cube_axes.SetZLabelFormat("%.2f")
            self._cube_axes.GetXAxesLinesProperty().SetColor(1, 0, 0)
            self._cube_axes.GetYAxesLinesProperty().SetColor(0, 1, 0)
            self._cube_axes.GetZAxesLinesProperty().SetColor(0, 0, 1)
            self._cube_axes.SetFlyModeToOuterEdges()
            self._renderer.AddActor(self._cube_axes)

        self._renderer.ResetCamera()

        self._info_label.setText(
            f"Mesh loaded: {len(self._mesh_paths)} file(s), "
            f"{total_cells:,} cells"
        )

        # Render
        self._vtk_widget.GetRenderWindow().Render()

    def _fit_all(self):
        if self._renderer:
            self._renderer.ResetCamera()
            self._vtk_widget.GetRenderWindow().Render()

    def closeEvent(self, event):
        """Clean up VTK resources on close."""
        try:
            self._vtk_widget.close()
        except Exception:
            pass
        super().closeEvent(event)
