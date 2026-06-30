"""
MeshViewer - Standalone, non-blocking 3D mesh preview window with
clipping plane (B), Interference1 (C), Interference2 (E), and distance map (D).

Uses QVTKRenderWindowInteractor (QOpenGLWidget) for proper OpenGL context.
"""

import os
from typing import Optional, List, Dict, Tuple, Set

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSlider, QWidget, QButtonGroup, QProgressDialog, QApplication,
)
from PyQt6.QtCore import Qt

# ---- VTK imports ----
from vtkmodules.vtkIOLegacy import vtkUnstructuredGridReader
from vtkmodules.vtkFiltersCore import (
    vtkPolyDataNormals, vtkImplicitPolyDataDistance, vtkClipPolyData,
    vtkTriangleFilter, vtkDecimatePro,
)
from vtkmodules.vtkFiltersGeneral import vtkIntersectionPolyDataFilter
from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter
from vtkmodules.vtkRenderingCore import (
    vtkActor, vtkPolyDataMapper, vtkRenderer,
)
from vtkmodules.vtkRenderingAnnotation import (
    vtkCubeAxesActor, vtkScalarBarActor, vtkCornerAnnotation,
)
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkCommonDataModel import vtkPlane, vtkPolyData
from vtkmodules.vtkCommonCore import vtkLookupTable, vtkDoubleArray, vtkObject
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
import vtkmodules.vtkRenderingOpenGL2
import vtkmodules.vtkInteractionStyle


class MeshViewer(QDialog):
    """Standalone, non-blocking VTK mesh preview window."""

    def __init__(self, parent: Optional['QWidget'] = None):
        super().__init__(parent)
        self.setWindowTitle("Mesh Preview")
        self.setMinimumSize(960, 720)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        # ---- VTK state ----
        self._renderer: Optional[vtkRenderer] = None
        self._render_window = None
        self._mesh_actors: List[vtkActor] = []
        self._mesh_polydata: List = []
        self._mesh_names: List[str] = []
        self._mesh_paths: List[str] = []
        self._total_cells = 0
        self._cube_axes: Optional[vtkCubeAxesActor] = None

        # ---- View state ----
        self._transparent = False
        self._show_edges = True
        self._is_ortho = False
        self._original_colors: Dict[int, Tuple[float, float, float]] = {}

        # ---- B. Clipping state ----
        self._clip_active = False
        self._clip_axis = 0
        self._clip_plane = vtkPlane()
        self._clip_plane.SetOrigin(0, 0, 0)
        self._clip_plane.SetNormal(1, 0, 0)
        self._clip_bounds = None

        # ---- C. Collision state (Interference1) ----
        self._collision_actors: List[vtkActor] = []
        self._collision_tol = 0.0  # set during mesh load

        # ---- Mesh parameters overlay ----
        self._mesh_params: Optional[dict] = None
        self._params_annotation: Optional[vtkCornerAnnotation] = None

        # ---- E. Interference2 state (IntersectionPolyDataFilter-based) ----
        self._i2_actors: List[vtkActor] = []
        self._i2_collided: Set[int] = set()        # indices of meshes with intersection
        # Cancel flag for interruptible computation
        self._i2_cancel_flag = False

        # ---- D. Distance map state ----
        self._distance_mode = False
        self._distance_lut: Optional[vtkLookupTable] = None
        self._scalar_bar: Optional[vtkScalarBarActor] = None

        self._build_ui()

    # ================================================================
    #  UI
    # ================================================================

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # --- VTK viewport ---
        self._vtk_widget = QVTKRenderWindowInteractor(self)
        layout.addWidget(self._vtk_widget, 1)

        # --- Toolbar row 1 ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._info_label = QLabel("No mesh loaded")
        self._info_label.setWordWrap(True)
        toolbar.addWidget(self._info_label, 1)

        self._btn_transparency = QPushButton("▣ Transparency")
        self._btn_transparency.setCheckable(True)
        self._btn_transparency.setToolTip("Toggle mesh transparency")
        self._btn_transparency.clicked.connect(self._toggle_transparency)
        toolbar.addWidget(self._btn_transparency)

        self._btn_edges = QPushButton("✕ Edges")
        self._btn_edges.setCheckable(True)
        self._btn_edges.setChecked(True)
        self._btn_edges.setToolTip("Toggle mesh edge lines")
        self._btn_edges.clicked.connect(self._toggle_edges)
        toolbar.addWidget(self._btn_edges)

        # B
        self._btn_clip = QPushButton("✂ Clip")
        self._btn_clip.setCheckable(True)
        self._btn_clip.setToolTip("Enable clipping plane")
        self._btn_clip.clicked.connect(self._toggle_clip_panel)
        toolbar.addWidget(self._btn_clip)

        # C
        self._btn_collide = QPushButton("⚡ Interference1")
        self._btn_collide.setCheckable(True)
        self._btn_collide.setToolTip("Toggle Interference1: clip-based overlap region extraction")
        self._btn_collide.clicked.connect(self._run_collision_detection)
        toolbar.addWidget(self._btn_collide)

        # D
        self._btn_distance = QPushButton("🌈 Distance")
        self._btn_distance.setCheckable(True)
        self._btn_distance.setToolTip("Toggle distance heatmap")
        self._btn_distance.clicked.connect(self._toggle_distance_map)
        toolbar.addWidget(self._btn_distance)

        btn_fit = QPushButton("⌂ Fit All")
        btn_fit.setToolTip("Reset camera")
        btn_fit.clicked.connect(self._fit_all)
        toolbar.addWidget(btn_fit)

        self._btn_proj = QPushButton("◻ Ortho")
        self._btn_proj.setCheckable(True)
        self._btn_proj.setToolTip("Toggle orthographic / perspective projection")
        self._btn_proj.clicked.connect(self._toggle_projection)
        toolbar.addWidget(self._btn_proj)

        self._axis_group = QButtonGroup(self)
        self._axis_group.setExclusive(True)

        self._btn_axis_x = QPushButton("X")
        self._btn_axis_x.setCheckable(True)
        self._btn_axis_x.setToolTip("View from +X axis")
        self._btn_axis_x.clicked.connect(lambda: self._set_axis_view(0))
        toolbar.addWidget(self._btn_axis_x)
        self._axis_group.addButton(self._btn_axis_x)

        self._btn_axis_y = QPushButton("Y")
        self._btn_axis_y.setCheckable(True)
        self._btn_axis_y.setToolTip("View from +Y axis")
        self._btn_axis_y.clicked.connect(lambda: self._set_axis_view(1))
        toolbar.addWidget(self._btn_axis_y)
        self._axis_group.addButton(self._btn_axis_y)

        self._btn_axis_z = QPushButton("Z")
        self._btn_axis_z.setCheckable(True)
        self._btn_axis_z.setToolTip("View from +Z axis")
        self._btn_axis_z.clicked.connect(lambda: self._set_axis_view(2))
        toolbar.addWidget(self._btn_axis_z)
        self._axis_group.addButton(self._btn_axis_z)

        toolbar.addStretch()

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        toolbar.addWidget(btn_close)

        layout.addLayout(toolbar)

        # --- Clipping controls row 2 (hidden) ---
        self._clip_panel = QWidget()
        clip_row = QHBoxLayout(self._clip_panel)
        clip_row.setContentsMargins(0, 0, 0, 0)
        clip_row.setSpacing(6)

        cl = QLabel("Clip →")
        cl.setStyleSheet("font-weight: bold; color: #f38ba8;")
        clip_row.addWidget(cl)

        self._clip_axis_cb = QComboBox()
        self._clip_axis_cb.addItems(["X-Axis", "Y-Axis", "Z-Axis"])
        self._clip_axis_cb.currentIndexChanged.connect(self._on_clip_changed)
        clip_row.addWidget(self._clip_axis_cb)

        self._clip_slider = QSlider(Qt.Orientation.Horizontal)
        self._clip_slider.setMinimumWidth(200)
        self._clip_slider.setRange(0, 1000)
        self._clip_slider.setValue(500)
        self._clip_slider.valueChanged.connect(self._on_clip_changed)
        clip_row.addWidget(self._clip_slider, 1)

        self._clip_label = QLabel("0.00")
        self._clip_label.setMinimumWidth(60)
        clip_row.addWidget(self._clip_label)

        cr = QPushButton("Reset")
        cr.clicked.connect(self._clip_reset)
        clip_row.addWidget(cr)

        self._clip_panel.setVisible(False)
        layout.addWidget(self._clip_panel)

        # --- Collision report row 3 (hidden) ---
        self._collision_panel = QWidget()
        coll_row = QHBoxLayout(self._collision_panel)
        coll_row.setContentsMargins(0, 0, 0, 0)
        coll_row.setSpacing(6)

        ci = QLabel("⚡")
        coll_row.addWidget(ci)

        self._collision_label = QLabel("No collisions")
        self._collision_label.setStyleSheet("font-weight: bold;")
        coll_row.addWidget(self._collision_label, 1)

        self._btn_coll_viz = QPushButton("✕ Hide")
        self._btn_coll_viz.setCheckable(True)
        self._btn_coll_viz.setChecked(True)
        self._btn_coll_viz.clicked.connect(self._toggle_collision_visibility)
        coll_row.addWidget(self._btn_coll_viz)

        self._collision_panel.setVisible(False)
        layout.addWidget(self._collision_panel)

        # ---- VTK setup ----
        self._render_window = self._vtk_widget.GetRenderWindow()
        self._renderer = vtkRenderer()
        self._renderer.SetBackground(0.2, 0.25, 0.3)
        self._render_window.AddRenderer(self._renderer)

        interactor = self._render_window.GetInteractor()
        style = vtkInteractorStyleTrackballCamera()
        interactor.SetInteractorStyle(style)

        self._vtk_widget.Initialize()
        self._vtk_widget.Start()

        # ---- Mesh params corner annotation ----
        self._params_annotation = vtkCornerAnnotation()
        self._params_annotation.SetText(2, "Mesh Parameters:\n  <none>")
        self._params_annotation.SetMaximumFontSize(14)
        self._params_annotation.GetTextProperty().SetColor(0.9, 0.9, 0.9)
        self._params_annotation.GetTextProperty().SetBackgroundColor(0.1, 0.1, 0.15)
        self._params_annotation.GetTextProperty().SetBackgroundOpacity(0.7)
        self._params_annotation.GetTextProperty().SetFrame(False)
        self._renderer.AddActor(self._params_annotation)

    # ================================================================
    #  Public API
    # ================================================================

    def load_mesh(self, mesh_paths: Dict[str, str],
                  mesh_params: Optional[dict] = None):
        self._mesh_paths = list(mesh_paths.values())
        self._mesh_names = list(mesh_paths.keys())
        if mesh_params is not None:
            self._mesh_params = mesh_params
        self._update_params_text()
        self._render_mesh_multi()

    def load_mesh_files(self, file_paths: List[str]):
        self._mesh_paths = file_paths
        self._mesh_names = [os.path.basename(p) for p in file_paths]
        self._render_mesh_multi()

    def _update_params_text(self):
        """Refresh the corner-annotation overlay from self._mesh_params."""
        if self._params_annotation is None:
            return
        if self._mesh_params is None:
            self._params_annotation.SetText(2, "")
            return

        p = self._mesh_params
        alg = p.get("algorithm", "?")
        elem = p.get("elem_factor", "?")
        mn = p.get("mesh_min_factor", "?")
        mx = p.get("mesh_max_factor", "?")
        smooth = p.get("smoothing", "?")
        order = p.get("element_order", "?")

        lines = [
            "Gmsh Parameters",
            f"  Algorithm: {alg}",
            f"  Order: {order}  |  Smooth: {smooth}",
            f"  Elem Factor: {elem}",
            f"  Min/Max: {mn} / {mx}",
        ]
        self._params_annotation.SetText(2, "\n".join(lines))
        self._render_window.Render()

    # ================================================================
    #  Rendering — one actor per mesh
    # ================================================================

    def _clear_all(self):
        for a in self._mesh_actors:
            self._renderer.RemoveActor(a)
        for a in self._collision_actors:
            self._renderer.RemoveActor(a)
        for a in self._i2_actors:
            self._renderer.RemoveActor(a)
        if self._scalar_bar:
            self._renderer.RemoveActor(self._scalar_bar)
            self._scalar_bar = None
        if self._cube_axes:
            self._renderer.RemoveActor(self._cube_axes)
            self._cube_axes = None
        self._mesh_actors.clear()
        self._mesh_polydata.clear()
        self._collision_actors.clear()
        self._i2_actors.clear()
        self._i2_collided.clear()
        self._collision_panel.setVisible(False)
        self._clip_panel.setVisible(False)
        self._clip_active = False
        self._btn_clip.setChecked(False)
        self._btn_collide.setChecked(False)
        self._distance_mode = False
        self._btn_distance.setChecked(False)
        self._transparent = False
        self._btn_transparency.setChecked(False)
        self._original_colors.clear()

    @staticmethod
    def _make_default_actor(mapper: vtkPolyDataMapper) -> vtkActor:
        actor = vtkActor()
        actor.SetMapper(mapper)
        p = actor.GetProperty()
        p.SetColor(0.35, 0.65, 0.80)   # cool slate-blue — contrasts with red occlusion
        p.SetEdgeColor(0.1, 0.1, 0.1)
        p.SetEdgeVisibility(True)
        p.SetLineWidth(1.0)
        p.SetAmbient(0.15)
        p.SetDiffuse(0.8)
        p.SetSpecular(0.05)
        return actor

    def _render_mesh_multi(self):
        if not self._renderer or not self._mesh_paths:
            return
        self._clear_all()

        self._total_cells = 0
        for fpath in self._mesh_paths:
            if not os.path.exists(fpath):
                continue
            try:
                reader = vtkUnstructuredGridReader()
                reader.SetFileName(fpath)
                reader.Update()
                out = reader.GetOutput()
                if not out or out.GetNumberOfCells() == 0:
                    continue

                geo = vtkGeometryFilter()
                geo.SetInputData(out)
                geo.Update()

                normals = vtkPolyDataNormals()
                normals.SetInputConnection(geo.GetOutputPort())
                normals.ComputePointNormalsOn()
                normals.Update()

                poly = normals.GetOutput()
                self._mesh_polydata.append(poly)

                mapper = vtkPolyDataMapper()
                mapper.SetInputData(poly)
                mapper.ScalarVisibilityOff()

                actor = self._make_default_actor(mapper)
                self._mesh_actors.append(actor)
                self._renderer.AddActor(actor)
                self._total_cells += out.GetNumberOfCells()
            except Exception as e:
                print(f"[MeshViewer] Error: {e}")

        if not self._mesh_actors:
            self._info_label.setText("No mesh data loaded")
            return

        for i, a in enumerate(self._mesh_actors):
            c = a.GetProperty().GetColor()
            self._original_colors[i] = (c[0], c[1], c[2])

        # Overall bounds for cube axes + clip slider
        bounds = [float('inf'), -float('inf'),
                  float('inf'), -float('inf'),
                  float('inf'), -float('inf')]
        for a in self._mesh_actors:
            b = a.GetBounds()
            if b:
                for k in range(6):
                    if k % 2 == 0:
                        bounds[k] = min(bounds[k], b[k])
                    else:
                        bounds[k] = max(bounds[k], b[k])
        self._clip_bounds = bounds

        # Interference detection tolerance: 0.3% of model diagonal
        diag = ((bounds[1] - bounds[0])**2 + (bounds[3] - bounds[2])**2 +
                (bounds[5] - bounds[4])**2) ** 0.5
        self._collision_tol = max(diag * 0.003, 1e-6)

        if all(abs(v) < 1e10 for v in bounds):
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
            f"{self._total_cells:,} cells"
        )
        self._render_window.Render()

    # ================================================================
    #  B — Clipping Plane
    # ================================================================

    def _toggle_clip_panel(self):
        self._clip_active = self._btn_clip.isChecked()
        self._clip_panel.setVisible(self._clip_active)
        if self._clip_active:
            self._sync_clip_plane()
        else:
            self._remove_clip_planes()
        if self._render_window:
            self._render_window.Render()

    def _on_clip_changed(self):
        if self._clip_active:
            self._sync_clip_plane()

    def _sync_clip_plane(self):
        b = self._clip_bounds
        if not b:
            return
        axis = self._clip_axis_cb.currentIndex()
        lo, hi = b[axis * 2], b[axis * 2 + 1]
        t = self._clip_slider.value() / 1000.0
        pos = lo + t * (hi - lo)
        self._clip_label.setText(f"{pos:.2f}")

        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        origin = [0.0, 0.0, 0.0]
        origin[axis] = pos
        self._clip_plane.SetOrigin(origin)
        self._clip_plane.SetNormal(normal)

        for a in self._mesh_actors:
            m = a.GetMapper()
            m.RemoveAllClippingPlanes()
            m.AddClippingPlane(self._clip_plane)
        self._render_window.Render()

    def _remove_clip_planes(self):
        for a in self._mesh_actors:
            a.GetMapper().RemoveAllClippingPlanes()
        if self._render_window:
            self._render_window.Render()

    def _clip_reset(self):
        b = self._clip_bounds
        if not b:
            return
        axis = self._clip_axis_cb.currentIndex()
        mid = (b[axis*2] + b[axis*2+1]) / 2
        rng = b[axis*2+1] - b[axis*2]
        val = int((mid - b[axis*2]) / rng * 1000) if rng > 0 else 500
        self._clip_slider.setValue(val)

    # ================================================================
    #  C — Interference1 (Clip-based Overlap Extraction)
    # ================================================================

    def _run_collision_detection(self):
        # --- Toggle OFF: clear effects ---
        if not self._btn_collide.isChecked():
            for a in self._collision_actors:
                self._renderer.RemoveActor(a)
            self._collision_actors.clear()
            # Restore mesh opacity if it was auto-enabled
            if self._transparent:
                self._toggle_transparency()
            self._render_window.Render()
            return

        n = len(self._mesh_polydata)
        if n < 2:
            self._btn_collide.setChecked(False)
            return

        self._btn_collide.setEnabled(False)
        self._btn_collide.setText("⚡ Computing...")

        for a in self._collision_actors:
            self._renderer.RemoveActor(a)
        self._collision_actors.clear()

        vtkObject.GlobalWarningDisplayOff()

        # Auto-enable transparency to see overlap inside
        if not self._transparent:
            self._toggle_transparency()

        # Spatial pre-filter: only check pairs whose bounding boxes overlap.
        # For typical CAD assemblies (n < 20 parts), this O(n²) loop with
        # AABB early reject is fast enough. For very large assemblies a
        # spatial hash / BVH could be added, but AABB covers the common case.
        for i in range(n):
            poly_i = self._mesh_polydata[i]
            for j in range(i + 1, n):
                poly_j = self._mesh_polydata[j]

                # AABB overlap → parts are close enough in space
                b_i = poly_i.GetBounds()
                b_j = poly_j.GetBounds()
                if not (b_i[0] <= b_j[1] and b_i[1] >= b_j[0] and
                        b_i[2] <= b_j[3] and b_i[3] >= b_j[2] and
                        b_i[4] <= b_j[5] and b_i[5] >= b_j[4]):
                    continue

                # Clip mesh i with mesh j's signed distance → overlap patch
                imp_ij = vtkImplicitPolyDataDistance()
                imp_ij.SetInput(poly_j)

                clipper_ij = vtkClipPolyData()
                clipper_ij.SetInputData(poly_i)
                clipper_ij.SetClipFunction(imp_ij)
                clipper_ij.InsideOutOn()
                clipper_ij.SetValue(0.0)
                clipper_ij.Update()
                overlap_ij = clipper_ij.GetOutput()

                # Clip mesh j with mesh i's signed distance
                imp_ji = vtkImplicitPolyDataDistance()
                imp_ji.SetInput(poly_i)

                clipper_ji = vtkClipPolyData()
                clipper_ji.SetInputData(poly_j)
                clipper_ji.SetClipFunction(imp_ji)
                clipper_ji.InsideOutOn()
                clipper_ji.SetValue(0.0)
                clipper_ji.Update()
                overlap_ji = clipper_ji.GetOutput()

                n_cells_ij = overlap_ij.GetNumberOfCells()
                n_cells_ji = overlap_ji.GetNumberOfCells()

                # --- Visualize overlapping region(s) in bright red ---
                for clip_result in [overlap_ij, overlap_ji]:
                    if clip_result.GetNumberOfCells() == 0:
                        continue

                    mapper = vtkPolyDataMapper()
                    mapper.SetInputData(clip_result)
                    mapper.ScalarVisibilityOff()

                    actor = vtkActor()
                    actor.SetMapper(mapper)
                    pp = actor.GetProperty()
                    pp.SetColor(1.0, 0.15, 0.15)   # bright red — distinct from slate-blue mesh
                    pp.SetOpacity(0.70)
                    pp.SetEdgeVisibility(True)
                    pp.SetEdgeColor(1.0, 0.5, 0.5)
                    pp.SetLineWidth(1.5)

                    self._collision_actors.append(actor)
                    self._renderer.AddActor(actor)

        self._btn_collide.setEnabled(True)
        self._btn_collide.setText("⚡ Interference1")
        vtkObject.GlobalWarningDisplayOn()
        self._render_window.Render()

    # ================================================================
    #  E — Interference2 (IntersectionPolyDataFilter-based)
    # ================================================================

    def _restore_mesh_colors(self):
        """Restore mesh actors to their original (non-interference) colors."""
        for i, a in enumerate(self._mesh_actors):
            oc = self._original_colors.get(i, (0.35, 0.65, 0.80))
            a.GetProperty().SetColor(oc)

    def _run_interference2(self):
        # --- Toggle OFF: clear effects ---
        if not self._btn_i2.isChecked():
            for a in self._i2_actors:
                self._renderer.RemoveActor(a)
            self._i2_actors.clear()
            self._restore_mesh_colors()
            self._i2_collided.clear()
            self._collision_panel.setVisible(False)
            if self._transparent:
                self._toggle_transparency()
            self._render_window.Render()
            return

        n = len(self._mesh_polydata)
        if n < 2:
            self._btn_i2.setChecked(False)
            return

        self._btn_i2.setEnabled(False)
        self._btn_i2.setText("⚡ Computing...")

        # Clean slate
        for a in self._i2_actors:
            self._renderer.RemoveActor(a)
        self._i2_actors.clear()
        self._restore_mesh_colors()
        self._i2_collided.clear()

        # Transparency helps see intersection lines through parts
        if not self._transparent:
            self._toggle_transparency()

        vtkObject.GlobalWarningDisplayOff()

        # ── Progress dialog ──
        total_pairs = n * (n - 1) // 2
        progress = QProgressDialog(
            "Checking surface intersections...", "Cancel", 0, total_pairs, self
        )
        progress.setWindowTitle("Interference2")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self._i2_cancel_flag = False
        progress.canceled.connect(lambda: setattr(self, '_i2_cancel_flag', True))
        progress.show()
        QApplication.processEvents()

        cancelled = False
        step = 0
        overlap_count = 0
        details = []

        try:
            for i in range(n):
                if cancelled:
                    break
                poly_i = self._mesh_polydata[i]
                ni = self._mesh_names[i][:12] if i < len(self._mesh_names) else f"#{i}"

                for j in range(i + 1, n):
                    poly_j = self._mesh_polydata[j]
                    nj = self._mesh_names[j][:12] if j < len(self._mesh_names) else f"#{j}"
                    step += 1
                    progress.setValue(step)
                    progress.setLabelText(f"{ni} ↔ {nj}")
                    QApplication.processEvents()

                    if self._i2_cancel_flag:
                        cancelled = True
                        break

                    # AABB pre-filter
                    b_i = poly_i.GetBounds()
                    b_j = poly_j.GetBounds()
                    if not (b_i[0] <= b_j[1] and b_i[1] >= b_j[0] and
                            b_i[2] <= b_j[3] and b_i[3] >= b_j[2] and
                            b_i[4] <= b_j[5] and b_i[5] >= b_j[4]):
                        continue

                    # ── Decimate + IntersectionPolyDataFilter ──
                    try:
                        # Decimate both to ~5% of original triangles for speed and
                        # to eliminate degenerate STEP triangles
                        dec_i = vtkDecimatePro()
                        dec_i.SetInputData(poly_i)
                        dec_i.SetTargetReduction(0.95)
                        dec_i.SetPreserveTopology(True)
                        dec_i.Update()

                        dec_j = vtkDecimatePro()
                        dec_j.SetInputData(poly_j)
                        dec_j.SetTargetReduction(0.95)
                        dec_j.SetPreserveTopology(True)
                        dec_j.Update()

                        # Exact surface-surface intersection on decimated meshes
                        intersect = vtkIntersectionPolyDataFilter()
                        intersect.SetInputData(0, dec_i.GetOutput())
                        intersect.SetInputData(1, dec_j.GetOutput())
                        intersect.Update()

                        lines = intersect.GetOutput()
                        n_cells = lines.GetNumberOfCells()

                        if n_cells > 0:
                            self._i2_collided.add(i)
                            self._i2_collided.add(j)

                            # Draw intersection lines as red curves
                            mapper = vtkPolyDataMapper()
                            mapper.SetInputData(lines)
                            mapper.ScalarVisibilityOff()

                            actor = vtkActor()
                            actor.SetMapper(mapper)
                            pp = actor.GetProperty()
                            pp.SetColor(1.0, 0.0, 0.0)
                            pp.SetLineWidth(2.5)

                            self._i2_actors.append(actor)
                            self._renderer.AddActor(actor)

                            overlap_count += 1
                            details.append(
                                f"  {ni} ↔ {nj}  ({n_cells} inter cells)"
                            )
                            print(
                                f"[I2]  {ni} ↔ {nj}  "
                                f"{n_cells} intersection cells"
                            )

                    except Exception as e:
                        details.append(f"  {ni} ↔ {nj}  error: {str(e)[:60]}")
                        print(f"[I2]  {ni} ↔ {nj}  exception: {e}")

                    QApplication.processEvents()

                if cancelled:
                    break

        finally:
            progress.close()

        # Cancel → restore everything
        if cancelled:
            for a in self._i2_actors:
                self._renderer.RemoveActor(a)
            self._i2_actors.clear()
            self._restore_mesh_colors()
            self._i2_collided.clear()
            self._btn_i2.setEnabled(True)
            self._btn_i2.setText("⚡ Interference2")
            self._btn_i2.setChecked(False)
            vtkObject.GlobalWarningDisplayOn()
            self._render_window.Render()
            return

        # ── Highlight collided meshes in red ──
        for idx in self._i2_collided:
            if idx < len(self._mesh_actors):
                self._mesh_actors[idx].GetProperty().SetColor(1.0, 0.2, 0.2)

        # ---- Update report panel ----
        if overlap_count > 0:
            txt = f"Interference2: {overlap_count} pair(s)"
            for d in details:
                txt += "\n" + d
            self._collision_label.setText(txt)
            self._collision_label.setStyleSheet("font-weight: bold; color: #f38ba8;")
            self._btn_coll_viz.setChecked(True)
            self._btn_coll_viz.setText("✕ Hide")
        else:
            self._collision_label.setText(
                f"Interference2: No intersections — {total_pairs} pairs ✓"
            )
            self._collision_label.setStyleSheet("font-weight: bold; color: #a6e3a1;")

        self._collision_panel.setVisible(True)
        self._btn_i2.setEnabled(True)
        self._btn_i2.setText("⚡ Interference2")
        vtkObject.GlobalWarningDisplayOn()
        self._render_window.Render()

    def _toggle_collision_visibility(self):
        vis = self._btn_coll_viz.isChecked()
        # Interference1: toggle overlap actors
        for a in self._collision_actors:
            a.SetVisibility(vis)
        # Interference2: toggle intersection line actors + mesh colors
        for a in self._i2_actors:
            a.SetVisibility(vis)
        if vis:
            for idx in self._i2_collided:
                if idx < len(self._mesh_actors):
                    self._mesh_actors[idx].GetProperty().SetColor(1.0, 0.2, 0.2)
        else:
            self._restore_mesh_colors()
        self._btn_coll_viz.setText("✕ Hide" if vis else "◉ Show")
        self._render_window.Render()

    # ================================================================
    #  D — Distance Map
    # ================================================================

    def _toggle_distance_map(self):
        if not self._mesh_polydata:
            return
        self._distance_mode = self._btn_distance.isChecked()
        if self._distance_mode:
            self._btn_distance.setText("🌈 Solid")
            self._build_distance_map()
        else:
            self._btn_distance.setText("🌈 Distance")
            self._remove_distance_map()
        self._render_window.Render()

    @staticmethod
    def _make_heatmap_lut(d_min, d_max):
        lut = vtkLookupTable()
        lut.SetNumberOfTableValues(256)
        lut.SetRange(d_min, d_max)
        lut.SetHueRange(0.667, 0.0)
        lut.SetSaturationRange(1.0, 1.0)
        lut.SetValueRange(1.0, 1.0)
        lut.Build()
        return lut

    def _build_distance_map(self):
        n = len(self._mesh_polydata)
        if n < 2:
            return
        if self._scalar_bar:
            self._renderer.RemoveActor(self._scalar_bar)
            self._scalar_bar = None

        # Per-mesh min distance to any other mesh
        global_min = float('inf')
        global_max = 0.0
        per_mesh_dists: List[List[float]] = []

        for i in range(n):
            poly_i = self._mesh_polydata[i]
            n_pts = poly_i.GetNumberOfPoints()
            min_dists = [float('inf')] * n_pts

            for j in range(n):
                if i == j:
                    continue
                poly_j = self._mesh_polydata[j]
                imp = vtkImplicitPolyDataDistance()
                imp.SetInput(poly_j)
                for k in range(n_pts):
                    pt = poly_i.GetPoint(k)
                    d = abs(imp.EvaluateFunction(pt))  # == 0 means touching
                    if d < min_dists[k]:
                        min_dists[k] = d

            per_mesh_dists.append(min_dists)
            dmin = min(min_dists)
            dmax = max(min_dists)
            if dmin < global_min:
                global_min = dmin
            if dmax > global_max:
                global_max = dmax

        if global_max <= global_min:
            global_max = global_min + 0.001

        self._distance_lut = self._make_heatmap_lut(global_min, global_max)

        for i, actor in enumerate(self._mesh_actors):
            poly = self._mesh_polydata[i]
            arr = vtkDoubleArray()
            arr.SetName("Distance")
            for d in per_mesh_dists[i]:
                arr.InsertNextValue(d)
            poly.GetPointData().SetScalars(arr)

            mapper = vtkPolyDataMapper()
            mapper.SetInputData(poly)
            mapper.ScalarVisibilityOn()
            mapper.SetLookupTable(self._distance_lut)
            mapper.SetScalarRange(global_min, global_max)
            actor.SetMapper(mapper)
            actor.GetProperty().SetEdgeVisibility(self._show_edges)

        self._scalar_bar = vtkScalarBarActor()
        self._scalar_bar.SetLookupTable(self._distance_lut)
        self._scalar_bar.SetTitle("Distance")
        self._scalar_bar.SetNumberOfLabels(5)
        self._scalar_bar.SetWidth(0.08)
        self._scalar_bar.SetHeight(0.5)
        self._scalar_bar.GetPositionCoordinate().SetValue(0.88, 0.25)
        self._renderer.AddActor(self._scalar_bar)

        self._info_label.setText(
            f"Distance | range [{global_min:.4f}, {global_max:.4f}]"
        )

    def _remove_distance_map(self):
        if self._scalar_bar:
            self._renderer.RemoveActor(self._scalar_bar)
            self._scalar_bar = None
        for i, actor in enumerate(self._mesh_actors):
            self._mesh_polydata[i].GetPointData().SetScalars(None)
            mapper = vtkPolyDataMapper()
            mapper.SetInputData(self._mesh_polydata[i])
            mapper.ScalarVisibilityOff()
            actor.SetMapper(mapper)
            oc = self._original_colors.get(i, (0.35, 0.65, 0.80))
            actor.GetProperty().SetColor(oc)
            actor.GetProperty().SetEdgeVisibility(self._show_edges)

    # ================================================================
    #  View Controls (multi-actor aware)
    # ================================================================

    def _toggle_transparency(self):
        if not self._mesh_actors:
            return
        self._transparent = not self._transparent
        for a in self._mesh_actors:
            p = a.GetProperty()
            if self._transparent:
                p.SetOpacity(0.45)
                p.SetEdgeColor(0.5, 0.8, 0.9)   # light cyan edges — visible through transparency
            else:
                p.SetOpacity(1.0)
                p.SetEdgeColor(0.1, 0.1, 0.1)
        self._btn_transparency.setText("▣ Solid" if self._transparent else "▣ Transparency")
        self._render_window.Render()

    def _toggle_edges(self):
        if not self._mesh_actors:
            return
        self._show_edges = not self._show_edges
        for a in self._mesh_actors:
            a.GetProperty().SetEdgeVisibility(self._show_edges)
        self._btn_edges.setChecked(self._show_edges)
        self._render_window.Render()

    def _toggle_projection(self):
        if not self._renderer:
            return
        self._is_ortho = not self._is_ortho
        cam = self._renderer.GetActiveCamera()
        cam.SetParallelProjection(self._is_ortho)
        self._btn_proj.setText("◻ Ortho" if self._is_ortho else "◻ Perspective")
        self._btn_proj.setChecked(self._is_ortho)
        self._render_window.Render()

    def _fit_all(self):
        if self._renderer:
            self._renderer.ResetCamera()
            self._render_window.Render()

    def _set_axis_view(self, axis: int):
        if not self._renderer or not self._clip_bounds:
            return
        b = self._clip_bounds
        cx = (b[0] + b[1]) / 2
        cy = (b[2] + b[3]) / 2
        cz = (b[4] + b[5]) / 2
        diag = max(b[1] - b[0], b[3] - b[2], b[5] - b[4]) * 2.0

        cam = self._renderer.GetActiveCamera()
        # Ensure orthographic is on for clean axis-aligned view
        if not self._is_ortho:
            self._is_ortho = True
            cam.SetParallelProjection(True)
            self._btn_proj.setText("◻ Ortho")
            self._btn_proj.setChecked(True)

        if axis == 0:   # +X
            cam.SetPosition(cx + diag, cy, cz)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 0, 1)
        elif axis == 1:  # +Y
            cam.SetPosition(cx, cy + diag, cz)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 0, 1)
        else:            # +Z
            cam.SetPosition(cx, cy, cz + diag)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 1, 0)
        self._renderer.ResetCameraClippingRange()
        self._render_window.Render()

    def closeEvent(self, event):
        try:
            # Release VTK OpenGL resources before destroying the widget
            if self._render_window:
                self._render_window.Finalize()
            self._vtk_widget.close()
        except Exception:
            pass
        super().closeEvent(event)
