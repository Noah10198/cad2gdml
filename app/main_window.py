"""
MainWindow - Primary application window.
"""

import os
import time
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QSplitter, QVBoxLayout,
    QWidget, QFileDialog, QMessageBox, QDockWidget, QToolBar,
    QDialog, QProgressDialog
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPalette, QColor

from OCC.Core.AIS import AIS_Shape

from core.geo_data_agent import GeoDataAgent
from core.materials_lib import MaterialsLib
from core.lego_color_singleton import LegoColorSingleton
from ui.toolbar import RibbonToolBar
from ui.project_tree import ProjectTreeWidget, TREE_ITEM_TYPE
from ui.occ_widget import WidgetOCC
from ui.geo_param_widget import GeoParamWidget
from utils.task_manager import TaskManager
from utils.logger import AsyncLogger, LogLevel
from mesh.gmsh_dialog import GmshDialog
from mesh.mesh_runner import MeshRunner
from mesh.mesh_progress import MeshProgressDialog
from mesh.mesh_viewer import MeshViewer
from ui.export_gdml_dialog import ExportGdmlDialog


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CAD2GDML - CAD to GDML Converter")
        self.resize(1600, 1000)
        self._dark_theme = False

        self._geo_agent = GeoDataAgent()
        self._library = MaterialsLib()
        self._task_manager = TaskManager()
        self._logger = AsyncLogger()

        # Output directory for exported mesh files
        self._output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "outputfile"
        )
        os.makedirs(self._output_dir, exist_ok=True)

        # Non-modal dialog refs
        self._assign_material_dlg = None
        self._export_gdml_dlg = None
        self._mesh_viewers: list = []  # persistent refs to prevent GC from collecting active viewers

        # Mesh state
        self._mesh_runner: Optional[MeshRunner] = None
        self._mesh_progress_dlg: Optional[MeshProgressDialog] = None
        self._meshed_nodes: dict = {}  # entry_id -> vtk_path
        self._mesh_work_dir: str = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "_mesh_temp"
        )
        # Persist last mesh parameters across dialog invocations
        self._last_mesh_params: dict = {
            "algorithm": "Frontal-Delaunay",
            "elem_factor": 1.0,
            "mesh_min_factor": 5.0,
            "mesh_max_factor": 6.0,
            "smoothing": 1,
            "element_order": 1,
        }

        # Interference check state
        self._interference_dlg: Optional['InterferenceDialog'] = None
        self._interference_dlg_v2: Optional['InterferenceDialogV2'] = None
        self._last_import_dir: str = ""

        # Build UI before theme
        self._init_toolbar()
        self._init_project_tree()
        self._init_occ_widget()
        self._init_property_panel()
        self._init_log_panel()
        self._init_layout()
        self._init_status_bar()

        # Load NIST materials and populate tree (needs _library + _project_tree)
        self._load_nist_materials()

        # Apply unified theme after all UI panels exist
        self._apply_global_theme(False)
        self._connect_signals()
        QTimer.singleShot(0, self._init_occ_display_deferred)
        self._logger.log_system("CAD2GDML application started")

    # ---- Theme ----

    def _apply_global_theme(self, dark: bool):
        self._dark_theme = dark
        if dark:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#cdd6f4"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#181825"))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#313244"))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#313244"))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#cdd6f4"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#313244"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#cdd6f4"))
            palette.setColor(QPalette.ColorRole.BrightText, QColor("#f38ba8"))
            palette.setColor(QPalette.ColorRole.Link, QColor("#89b4fa"))
            palette.setColor(QPalette.ColorRole.Highlight, QColor("#45475a"))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#cdd6f4"))
            self.setPalette(palette)
            mw_bg = "#1e1e2e"; dock_bg = "#1e1e2e"; dock_fg = "#cdd6f4"
            dock_t_bg = "#181825"; dock_t_fg = "#a6adc8"; dock_t_bd = "#313244"
            sp_color = "#313244"; tool_bg = "#1e1e2e"
            sc_bg = "#181825"; sc_h = "#45475a"; sc_hh = "#585b70"
            log_bg = "#11111b"; log_fg = "#a6adc8"
            st_bg = "#181825"; st_fg = "#a6adc8"
        else:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#f5f5f5"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#2c2c2c"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#e8e8e8"))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#2c2c2c"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#2c2c2c"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#2c2c2c"))
            palette.setColor(QPalette.ColorRole.BrightText, QColor("#d32f2f"))
            palette.setColor(QPalette.ColorRole.Link, QColor("#0078d4"))
            palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            self.setPalette(palette)
            mw_bg = "#f5f5f5"; dock_bg = "#f5f5f5"; dock_fg = "#2c2c2c"
            dock_t_bg = "#e8e8e8"; dock_t_fg = "#555555"; dock_t_bd = "#d0d0d0"
            sp_color = "#cccccc"; tool_bg = "#f5f5f5"
            sc_bg = "#f0f0f0"; sc_h = "#c0c0c0"; sc_hh = "#a0a0a0"
            log_bg = "#fafafa"; log_fg = "#555555"
            st_bg = "#e8e8e8"; st_fg = "#555555"

        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {mw_bg}; }}
            QDockWidget {{ background-color: {dock_bg}; color: {dock_fg};
                titlebar-close-icon: none; titlebar-normal-icon: none; }}
            QDockWidget::title {{ background-color: {dock_t_bg}; color: {dock_t_fg};
                font-size: 13px; font-weight: bold; padding: 4px 8px;
                border-bottom: 1px solid {dock_t_bd}; text-align: left; }}
            QSplitter::handle {{ background-color: {sp_color}; }}
            QSplitter::handle:horizontal {{ width: 2px; }}
            QSplitter::handle:vertical {{ height: 2px; }}
            QToolBar {{ background-color: {tool_bg}; border: none; spacing: 0px; padding: 0px; }}
            QScrollBar:vertical {{ background: {sc_bg}; width: 10px; margin: 0px; }}
            QScrollBar::handle:vertical {{ background: {sc_h}; min-height: 20px; border-radius: 4px; }}
            QScrollBar::handle:vertical:hover {{ background: {sc_hh}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar:horizontal {{ background: {sc_bg}; height: 10px; margin: 0px; }}
            QScrollBar::handle:horizontal {{ background: {sc_h}; min-width: 20px; border-radius: 4px; }}
            QScrollBar::handle:horizontal:hover {{ background: {sc_hh}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
        """)

        self._system_log.setStyleSheet(f"""
            #SystemLog {{ background-color: {log_bg}; color: {log_fg};
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px; border: none; padding: 4px; }}
        """)
        self._status_bar.setStyleSheet(f"""
            QStatusBar {{ background-color: {st_bg}; color: {st_fg};
                font-size: 12px; padding: 2px 8px; }}
        """)

        # Sync all sub-widgets' theme state
        if hasattr(self, '_toolbar'):
            self._toolbar.set_dark_theme(dark)
        if hasattr(self, '_project_tree'):
            self._project_tree.set_dark_theme(dark)
        if hasattr(self, '_param_widget'):
            self._param_widget.set_dark_theme(dark)
        if hasattr(self, '_occ_widget'):
            self._occ_widget.set_dark_theme(dark)

    def _toggle_theme(self):
        new_dark = not self._dark_theme
        self._apply_global_theme(new_dark)
        self._logger.log_system(f"Theme switched to {'dark' if new_dark else 'light'} mode")

    # ---- UI Init ----

    def _init_toolbar(self):
        self._toolbar = RibbonToolBar()
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False); tb.setFloatable(False)
        tb.addWidget(self._toolbar)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

    def _init_project_tree(self):
        self._project_tree = ProjectTreeWidget()
        self._project_tree.import_step_requested.connect(self._slot_import_step)

    def _init_occ_widget(self):
        self._occ_widget = WidgetOCC(self._library)

    def _init_occ_display_deferred(self):
        self._occ_widget._ensure_display_valid()
        QApplication.processEvents()
        if self._occ_widget.View:
            self._occ_widget.View.FitAll()
        self._logger.log_system("OCC 3D display initialized")

    def _init_property_panel(self):
        self._param_widget = GeoParamWidget(
            occ_widget=self._occ_widget,
            geo_agent=self._geo_agent
        )

    def _init_log_panel(self):
        self._system_log = QTextEdit()
        self._system_log.setReadOnly(True)
        self._system_log.setObjectName("SystemLog")
        self._logger.set_system_log_widget(self._system_log)

    def _init_layout(self):
        self._tree_dock = QDockWidget("Project Tree", self)
        self._tree_dock.setWidget(self._project_tree)
        self._tree_dock.setMinimumWidth(200)
        self._tree_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._tree_dock)

        self._param_dock = QDockWidget("Properties", self)
        self._param_dock.setWidget(self._param_widget)
        self._param_dock.setMinimumWidth(200)
        self._param_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._param_dock)

        self._v_splitter = QSplitter(Qt.Orientation.Vertical)
        self._v_splitter.addWidget(self._occ_widget)
        self._v_splitter.addWidget(self._system_log)
        self._v_splitter.setStretchFactor(0, 3)
        self._v_splitter.setStretchFactor(1, 1)
        self._v_splitter.setSizes([700, 200])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._v_splitter)
        self.setCentralWidget(central)

    def _init_status_bar(self):
        self._status_bar = self.statusBar()
        self._status_bar.showMessage("Ready")

    def _connect_signals(self):
        self._toolbar.import_step_clicked.connect(self._slot_import_step)
        self._toolbar.interference_clicked.connect(self._slot_interference)
        self._toolbar.interference2_clicked.connect(self._slot_interference_2)
        self._toolbar.assign_material_clicked.connect(self._slot_assign_material)
        self._toolbar.mesh_clicked.connect(self._slot_mesh)
        self._toolbar.view_mesh_clicked.connect(self._slot_view_mesh)
        self._toolbar.export_gdml_clicked.connect(self._slot_export_gdml)
        self._toolbar.export_mesh_clicked.connect(self._slot_export_mesh)
        self._toolbar.help_clicked.connect(self._slot_help)
        self._toolbar.theme_toggled.connect(self._toggle_theme)
        self._project_tree.item_selected.connect(self._slot_tree_item_selected)
        self._project_tree.item_visibility_changed.connect(self._slot_tree_visibility_changed)
        self._project_tree.add_local_material_requested.connect(
            self._slot_add_local_material)
        self._project_tree.remove_local_material_requested.connect(
            self._slot_remove_local_material)
        self._project_tree.save_local_materials_requested.connect(
            self._slot_save_local_materials)
        self._project_tree.load_local_materials_requested.connect(
            self._slot_load_local_materials)
        self._project_tree.delete_geometry_requested.connect(
            self._slot_delete_geometry)
        self._task_manager.progress_updated.connect(self._slot_update_progress)
        self._occ_widget.sig_shape_selected.connect(self._slot_occ_shape_selected)

    # ---- Slots ----

    def _slot_import_step(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import CAD File", self._last_import_dir,
            "CAD Files (*.step *.stp *.igs *.iges *.brep *.stl);;"
            "STEP (*.step *.stp);;IGES (*.igs *.iges);;"
            "BREP (*.brep);;STL (*.stl)")
        if not files:
            return
        self._last_import_dir = os.path.dirname(files[0])

        t_import = time.time()
        self._logger.log_system(f"Importing: {', '.join(files)} ...")

        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("Reading CAD files...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Import CAD")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()

        color_gen = LegoColorSingleton()
        all_leaves: list = []  # accumulate leaf nodes for final batch render
        solid_count = [0]

        def _progress_cb(current: int, total: int,
                         new_leaves: Optional[list] = None):
            """Simple progress updater — does NOT render (that would slow the
            blocking OCC read).  Instead stores leaves for post-read rendering."""
            pct = int((current / total) * 85) if total > 0 else 0
            progress.setValue(pct)
            if new_leaves:
                all_leaves.extend(new_leaves)
                solid_count[0] += len(new_leaves)
            QApplication.processEvents()

        error_info: list = []
        file_nodes = []

        for i, fp in enumerate(files):
            if progress.wasCanceled():
                progress.close()
                self._logger.log_system("Import cancelled by user.",
                                        level=LogLevel.WARNING)
                return

            label = Path(fp).name
            progress.setLabelText(f"Reading {label}...")
            QApplication.processEvents()

            node = self._geo_agent._cad_reader.read_file(fp, error_info,
                                                          _progress_cb)
            if node is not None:
                file_nodes.append(node)
                self._geo_agent.add_file_nodes([node])

        if not file_nodes:
            progress.close()
            for err in error_info:
                self._logger.log_system(f"  [ERROR] {err}", level=LogLevel.ERROR)
            self._logger.log_system("Import failed — no valid geometry.",
                                    level=LogLevel.ERROR)
            return

        # ── 2. Build project tree ────────────────────────────────────────
        progress.setValue(86)
        progress.setLabelText("Building project tree...")
        QApplication.processEvents()
        self._project_tree.populate_from_geo_agent(self._geo_agent)

        # ── 3. Batch render all leaf shapes ──────────────────────────────
        progress.setValue(90)
        progress.setLabelText("Rendering geometry...")
        QApplication.processEvents()
        rendered = 0
        total_to_render = len(all_leaves)
        for n in all_leaves:
            if n.shape is None or n.shape.IsNull():
                continue
            try:
                ais = AIS_Shape(n.shape)
                ais.SetColor(color_gen.get_next_color())
                ais.SetDisplayMode(1)
                ais.SetTransparency(0.4)  # semi-transparent (match interference preview)
                n.ais_shape = ais
                self._occ_widget.add_shape(ais, name=n.name, update=False)
                rendered += 1
                if rendered % max(1, total_to_render // 10) == 0:
                    progress.setValue(90 + int(rendered / total_to_render * 10))
                    QApplication.processEvents()
            except Exception:
                pass

        self._occ_widget.fit_all()
        progress.setValue(100)
        progress.setLabelText("Complete.")
        QApplication.processEvents()
        progress.close()

        elapsed = time.time() - t_import
        file_names = ", ".join(Path(fp).name for fp in files)
        self._logger.log_system(
            f"Import complete ({elapsed:.1f}s) — {rendered} solids from "
            f"{len(files)} file(s): {file_names}")

    def _slot_delete_geometry(self, entry_id: str):
        """Delete an imported geometry file node and all its children."""
        node = self._geo_agent.convert_entry_id_to_node(entry_id)
        if node is None:
            return

        reply = QMessageBox.question(
            self, "Delete Geometry",
            f"Delete '{node.name}' and all its parts?\n\n"
            "This will remove geometry, material assignments, and mesh data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Collect all descendant entry_ids (for mesh data cleanup)
        all_descendants = node.get_all_descendants()
        removed_ids = {node.entry_id}
        for desc in all_descendants:
            removed_ids.add(desc.entry_id)

        # Remove AIS shapes from OCC widget
        for desc in all_descendants:
            if desc.ais_shape is not None:
                self._occ_widget.erase_shape(desc.ais_shape, update=False)
        if node.ais_shape is not None:
            self._occ_widget.erase_shape(node.ais_shape, update=False)

        # Remove from geo_agent data tree
        self._geo_agent.remove_node(entry_id)

        # Clean up mesh data associated with deleted ids
        for eid in removed_ids:
            self._meshed_nodes.pop(eid, None)

        # Repopulate tree
        self._project_tree.populate_from_geo_agent(self._geo_agent)

        # Fit 3D view
        self._occ_widget.fit_all()

        self._logger.log_system(
            f"Deleted geometry: {node.name} ({len(all_descendants)} part(s))")

    def _slot_interference(self):
        """Show Interference 1 (sampled heuristic, for reference only)."""
        solids = self._geo_agent.get_all_solid_nodes()
        if len(solids) < 2:
            self._logger.log_system("Interference 1: need at least 2 solids.")
            QMessageBox.information(self, "Interference Check 1",
                                    "Need at least 2 solid bodies.\nImport a STEP file with multiple parts first.")
            return

        if self._interference_dlg is None or not self._interference_dlg.isVisible():
            from ui.interference_dialog_v2 import InterferenceDialogV2
            self._interference_dlg = InterferenceDialogV2(
                self._geo_agent, self,
                import_dir=self._last_import_dir,
                log_callback=lambda msg: self._logger.log_system(msg))
            self._interference_dlg.show()
        else:
            self._interference_dlg.raise_()
            self._interference_dlg.activateWindow()

    def _slot_interference_2(self):
        """Show Interference 2 (exhaustive OBB + exact check on all close pairs)."""
        solids = self._geo_agent.get_all_solid_nodes()
        if len(solids) < 2:
            self._logger.log_system("Interference 2: need at least 2 solids.")
            QMessageBox.information(self, "Interference Check 2",
                                    "Need at least 2 solid bodies.\nImport a STEP file with multiple parts first.")
            return

        if self._interference_dlg_v2 is None or not self._interference_dlg_v2.isVisible():
            from ui.interference_dialog import InterferenceDialog
            self._interference_dlg_v2 = InterferenceDialog(
                self._geo_agent, self,
                import_dir=self._last_import_dir,
                log_callback=lambda msg: self._logger.log_system(msg))
            self._interference_dlg_v2.show()
        else:
            self._interference_dlg_v2.raise_()
            self._interference_dlg_v2.activateWindow()

    def _slot_mesh(self):
        """Open the mesh parameter dialog, then start meshing in background."""
        # Gather all solid nodes that need meshing
        solid_nodes = self._geo_agent.get_all_solid_nodes()
        if not solid_nodes:
            self._logger.log_system("No geometry loaded. Import a STEP file first.")
            QMessageBox.information(self, "No Geometry",
                                    "Import a STEP file before meshing.")
            return

        # Show parameter dialog (pre-populated with last used values)
        dlg = GmshDialog(self, initial_params=self._last_mesh_params)
        if dlg.exec() != GmshDialog.DialogCode.Accepted:
            self._logger.log_system("Meshing cancelled by user.")
            return

        # Save params for next time
        self._last_mesh_params = {
            "algorithm": dlg.algorithm,
            "elem_factor": dlg.element_size_factor,
            "mesh_min_factor": dlg.mesh_min_factor,
            "mesh_max_factor": dlg.mesh_max_factor,
            "smoothing": dlg.smoothing_steps,
            "element_order": dlg.element_order,
        }

        params = dlg.get_descriptive_summary()
        self._logger.log_system(f"Mesh parameters: {params}")

        # Clean previous mesh work area
        if os.path.exists(self._mesh_work_dir):
            import shutil
            shutil.rmtree(self._mesh_work_dir, ignore_errors=True)
        os.makedirs(self._mesh_work_dir, exist_ok=True)

        # Verify gmsh.exe is available
        from mesh.mesh_runner import find_gmsh_exe
        if not find_gmsh_exe():
            self._logger.log_system(
                "[ERROR] gmsh.exe not found. "
                "Place gmsh.exe in 'codebuddy-2st/gmsh/' folder.",
                level=LogLevel.ERROR
            )
            return

        # Create non-blocking progress dialog
        if self._mesh_progress_dlg is None:
            self._mesh_progress_dlg = MeshProgressDialog(self)
        else:
            self._mesh_progress_dlg.reset()

        self._mesh_progress_dlg.set_view_mesh_callback(self._slot_view_mesh)
        self._mesh_progress_dlg.show()

        # Create and start the background mesh runner
        self._mesh_start_time = time.time()

        self._mesh_runner = MeshRunner(
            nodes=solid_nodes,
            work_dir=self._mesh_work_dir,
            algorithm=dlg.algorithm_index,
            elem_factor=dlg.element_size_factor,
            mesh_min_factor=dlg.mesh_min_factor,
            mesh_max_factor=dlg.mesh_max_factor,
            smoothing=dlg.smoothing_steps,
            order=dlg.element_order,
        )

        # Connect signals
        self._mesh_runner.progress_updated.connect(self._on_mesh_progress)
        self._mesh_runner.log_emitted.connect(self._on_mesh_log)
        self._mesh_runner.finished_with_result.connect(self._on_mesh_finished)

        self._mesh_runner.start()

    def _slot_view_mesh(self):
        """Open a new mesh preview window each time (allows side-by-side
        comparison of different mesh parameter sets)."""
        if not self._meshed_nodes:
            self._logger.log_system("No mesh data to view. Run meshing first.")
            QMessageBox.information(self, "No Mesh",
                                    "Generate a mesh before viewing.")
            return

        viewer = MeshViewer()
        viewer.load_mesh(self._meshed_nodes, mesh_params=self._last_mesh_params)
        viewer.show()
        # Keep a reference so Python GC won't destroy the C++ QVTKRenderWindowInteractor
        # while Qt is still delivering mouse events to it.
        self._mesh_viewers.append(viewer)
        viewer.finished.connect(
            lambda result, v=viewer: self._mesh_viewers.remove(v))
        self._logger.log_system(
            f"Mesh preview opened: {len(self._meshed_nodes)} meshed part(s)."
        )

    # ---- Mesh runner callbacks ----

    def _on_mesh_progress(self, value: int, message: str):
        """Update progress dialog and status bar from mesh runner."""
        if self._mesh_progress_dlg:
            self._mesh_progress_dlg.set_progress(value, message)
        self._status_bar.showMessage(f"Meshing: {message} ({value}%)")

    def _on_mesh_log(self, line: str):
        """Forward GMSH log line to both the system log and progress dialog."""
        self._logger.log_system(line)
        if self._mesh_progress_dlg:
            self._mesh_progress_dlg.append_log(line.split("\n")[-1])

    def _on_mesh_finished(self, success: bool, mesh_paths: dict, message: str):
        """Handle meshing completion."""
        elapsed = time.time() - self._mesh_start_time
        self._meshed_nodes = mesh_paths
        if success:
            self._logger.log_system(f"Meshing completed ({elapsed:.1f}s): {message}")
        else:
            self._logger.log_system(f"Meshing finished with issues ({elapsed:.1f}s): {message}",
                                    level=LogLevel.WARNING)
        self._mesh_runner = None



    def _slot_export_gdml(self):
        """Open the non-modal GDML export dialog with precondition checks."""
        solid_nodes = self._geo_agent.get_all_solid_nodes()
        if not solid_nodes:
            self._logger.log_system("No geometry loaded — nothing to export.")
            return

        # Check 1: all parts must have a material assigned
        unmaterialized = [
            n.name or n.entry_id for n in solid_nodes
            if not n.material_name or not n.material_name.strip()
        ]
        if unmaterialized:
            names = "; ".join(unmaterialized[:5])
            if len(unmaterialized) > 5:
                names += f" … and {len(unmaterialized) - 5} more"
            self._logger.log_system(
                f"GDML export blocked — {len(unmaterialized)} part(s) missing material: {names}",
                level=LogLevel.WARNING)
            QMessageBox.warning(
                self, "Materials Not Assigned",
                f"{len(unmaterialized)} part(s) have no material assignment.\n\n"
                f"Missing: {names}\n\n"
                "Please assign materials via the Material button first.")
            return

        # Check 2: all parts must have mesh data
        unmeshed = [
            n.name or n.entry_id for n in solid_nodes
            if n.entry_id not in self._meshed_nodes
               or not os.path.isfile(self._meshed_nodes.get(n.entry_id, ""))
        ]
        if unmeshed:
            names = "; ".join(unmeshed[:5])
            if len(unmeshed) > 5:
                names += f" … and {len(unmeshed) - 5} more"
            self._logger.log_system(
                f"GDML export blocked — {len(unmeshed)} part(s) not yet meshed: {names}",
                level=LogLevel.WARNING)
            QMessageBox.warning(
                self, "Parts Not Meshed",
                f"{len(unmeshed)} part(s) have no mesh data.\n\n"
                f"Missing: {names}\n\n"
                "Please run meshing first.")
            return

        # Check 3: meshing still in progress
        if self._mesh_runner is not None:
            self._logger.log_system(
                "Meshing is still in progress. Please wait.",
                level=LogLevel.WARNING)
            QMessageBox.information(
                self, "Meshing In Progress",
                "Meshing is still running.\n"
                "Please wait for it to finish, then try again.")
            return

        if self._export_gdml_dlg is None or not self._export_gdml_dlg.isVisible():
            self._export_gdml_dlg = ExportGdmlDialog(
                solid_nodes=solid_nodes,
                meshed_nodes=self._meshed_nodes,
                mat_lib=self._library,
                export_root=self._output_dir,
                parent=self,
            )
            self._export_gdml_dlg.show()
        else:
            self._export_gdml_dlg.raise_()
            self._export_gdml_dlg.activateWindow()

        self._logger.log_system("GDML export dialog opened.")

    def _slot_export_mesh(self):
        """Open export dialog and save mesh files to user-chosen folder."""
        # 1. Meshing still in progress?
        if self._mesh_runner is not None:
            self._logger.log_system(
                "Meshing is still in progress. Please wait until it completes.",
                level=LogLevel.WARNING)
            QMessageBox.information(
                self, "Meshing In Progress",
                "Meshing is still running.\n"
                "Please wait for it to finish, then export again.")
            return

        # 2. No mesh data at all?
        if not self._meshed_nodes:
            self._logger.log_system(
                "No mesh data to export. Run meshing first.",
                level=LogLevel.WARNING)
            QMessageBox.information(
                self, "No Mesh",
                "Generate a mesh before exporting.\n"
                "Click the Mesh button first.")
            return

        from ui.export_mesh_dialog import ExportMeshDialog
        dlg = ExportMeshDialog(default_dir=self._output_dir, parent=self)
        if dlg.exec() != ExportMeshDialog.DialogCode.Accepted:
            return

        base_dir = dlg.output_directory
        folder_name = dlg.folder_name
        export_dir = os.path.join(base_dir, folder_name)
        os.makedirs(export_dir, exist_ok=True)

        overall_vtk = dlg.export_overall_vtk
        per_part_vtk = dlg.export_per_part_vtk
        export_msh = dlg.export_msh

        flags = (f"[overall VTK={'Y' if overall_vtk else 'N'}, "
                 f"per-part VTK={'Y' if per_part_vtk else 'N'}, "
                 f"MSH={'Y' if export_msh else 'N'}]")
        self._logger.log_system(
            f"Exporting mesh to: {export_dir}  {flags}")

        part_list = list(self._meshed_nodes.items())
        if not part_list:
            self._logger.log_system("No meshed parts to export.")
            return

        import shutil
        exported_count = 0

        for entry_id, src_path in part_list:
            if not os.path.isfile(src_path):
                continue

            node = self._geo_agent.convert_entry_id_to_node(entry_id)
            part_name = node.name if node else entry_id
            safe = "".join(
                c if c.isalnum() or c in ('-', '_') else '_' for c in part_name)

            # Per-part VTK: copy existing VTK file with part name
            if per_part_vtk:
                dst = os.path.join(export_dir, f"{safe}.vtk")
                shutil.copy2(src_path, dst)
                self._logger.log_system(f"  VTK: {dst}")

            # MSH: copy the .msh file alongside the .vtk (same base name, same dir)
            if export_msh:
                msh_src = os.path.splitext(src_path)[0] + ".msh"
                if os.path.isfile(msh_src):
                    dst = os.path.join(export_dir, f"{safe}.msh")
                    shutil.copy2(msh_src, dst)
                    self._logger.log_system(f"  MSH: {dst}")
                else:
                    self._logger.log_system(
                        f"  [INFO] No .msh file found for {safe}. "
                        f"Re-mesh to generate .msh output.",
                        level=LogLevel.WARNING)

            exported_count += 1

        # Overall VTK: merge original VTK files into one
        if overall_vtk:
            original_vtk_paths = [p for _, p in part_list if os.path.isfile(p)]
            if original_vtk_paths:
                merged_path = os.path.join(export_dir, "merged.vtk")
                try:
                    _merge_vtk_files(original_vtk_paths, merged_path)
                    self._logger.log_system(
                        f"  Merged overall VTK: {merged_path} "
                        f"({len(original_vtk_paths)} parts)")
                except Exception as e:
                    self._logger.log_system(
                        f"  Failed to merge VTK: {e}",
                        level=LogLevel.ERROR)

        self._logger.log_system(
            f"Export complete — {exported_count} part(s) to {export_dir}")

    def _load_nist_materials(self):
        """Load G4_ materials and elements from bundled data files."""
        data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data"
        )
        # Load element data
        elem_path = os.path.normpath(os.path.join(data_dir, "element.xml"))
        elem_count = self._library.load_elements_from_xml(elem_path)
        self._logger.log_system(
            f"Loaded {elem_count} elements from {os.path.basename(elem_path)}",
            level=LogLevel.INFO)

        # Load NIST materials
        nist_path = os.path.normpath(os.path.join(data_dir, "nist.txt"))
        count = self._library.load_nist_from_file(nist_path)
        if count > 0:
            self._logger.log_system(f"Loaded {count} NIST materials from {os.path.basename(nist_path)}",
                                    level=LogLevel.INFO)
        else:
            self._logger.log_system(
                f"NIST material file not found at {nist_path}, using defaults.",
                level=LogLevel.WARNING)
        # Populate the Global Materials tree node
        all_names = self._library.get_nist_left_list()
        self._project_tree.populate_global_materials(all_names)
        # Populate the Local Materials tree node
        self._refresh_local_material_tree()

    def _slot_assign_material(self):
        """Open the Assign Material dialog (non-modal)."""
        solids = self._geo_agent.get_all_solid_nodes()
        if not solids:
            self._logger.log_system("No geometry loaded. Import a CAD file first.")
            QMessageBox.information(self, "No Geometry",
                                    "Import a CAD file before assigning materials.")
            return

        from ui.assign_material_dialog import AssignMaterialDialog

        if self._assign_material_dlg is None \
                or not self._assign_material_dlg.isVisible():
            self._assign_material_dlg = AssignMaterialDialog(
                self._geo_agent, self._library, self)
            self._assign_material_dlg.materials_saved.connect(
                lambda assigned, total: self._logger.log_system(
                    f"Material assignments saved — "
                    f"{assigned}/{total} part(s) have materials."))
            self._assign_material_dlg.rejected.connect(
                lambda: self._logger.log_system(
                    "Material assignment cancelled."))
            self._assign_material_dlg.show()
        else:
            self._assign_material_dlg.raise_()
            self._assign_material_dlg.activateWindow()

    def _slot_add_local_material(self):
        """Open dialog to add a local material, then refresh tree."""
        from ui.local_material_dialog import LocalMaterialDialog
        dlg = LocalMaterialDialog(self._library, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_local_material_tree()
            if MaterialsLib.GDML_OUTPUT_ENABLED:
                gdml = dlg.last_gdml
                if gdml:
                    self._logger.log_system("━━ GDML Material Definition ━━━━", level=LogLevel.INFO)
                    for line in gdml.strip().splitlines():
                        self._logger.log_system(line, level=LogLevel.INFO)
                    self._logger.log_system("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", level=LogLevel.INFO)
                    return
            self._logger.log_system(
                f"Local material added.",
                level=LogLevel.INFO)

    def _slot_save_local_materials(self):
        """Save all local materials to a JSON file."""
        from pathlib import Path
        default_name = "local_materials.json"
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Local Materials",
            str(Path(self._last_import_dir) / default_name),
            "JSON Files (*.json)")
        if not filepath:
            return
        ok = self._library.save_local_materials_to_json(filepath)
        if ok:
            self._logger.log_system(
                f"Local materials saved to {filepath}",
                level=LogLevel.INFO)
        else:
            self._logger.log_system(
                f"Failed to save local materials to {filepath}",
                level=LogLevel.ERROR)

    def _slot_load_local_materials(self):
        """Load local materials from a JSON file, replacing current library."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Load Local Materials", self._last_import_dir,
            "JSON Files (*.json)")
        if not filepath:
            return
        count = self._library.load_local_materials_from_json(filepath)
        if count > 0:
            self._refresh_local_material_tree()
            self._logger.log_system(
                f"Loaded {count} local materials from {filepath}",
                level=LogLevel.INFO)
        else:
            self._logger.log_system(
                f"No valid materials found in {filepath}",
                level=LogLevel.ERROR)

    def _slot_remove_local_material(self, mat_id: str):
        """Delete a local material and refresh tree."""
        name = ""
        mat = self._library.get_custom_element(mat_id)
        if mat:
            name = mat.name
        if not name:
            mat = self._library.get_compound(mat_id)
            if mat:
                name = mat.mat_name
        if not name:
            mat = self._library.get_mixture(mat_id)
            if mat:
                name = mat.mat_name
        self._library.delete_material(mat_id)
        self._refresh_local_material_tree()
        self._logger.log_system(
            f"Deleted local material '{name or mat_id}'.",
            level=LogLevel.INFO)

    def _refresh_local_material_tree(self):
        """Refresh the Local Materials tree node from MaterialsLib."""
        self._project_tree.populate_local_materials(self._library)

    def _get_local_material_by_id(self, mat_id: str):
        """Look up a local material by ID from the library."""
        mat = self._library.get_custom_element(mat_id)
        if mat:
            return mat
        mat = self._library.get_compound(mat_id)
        if mat:
            return mat
        mat = self._library.get_mixture(mat_id)
        return mat

    def _slot_help(self):
        QMessageBox.about(self, "About CAD2GDML",
            "CAD2GDML v2.0\n\nSTEP to GDML geometry conversion tool.\n\n"
            "Built with PyQt6, pythonocc-core, and GMSH.")

    def _slot_tree_item_selected(self, entry_id: str):
        if entry_id.startswith("__mat__:"):
            mat_name = entry_id[8:]
            self._param_widget.show_material_reference(mat_name)
            return
        if entry_id.startswith("__local__:"):
            mat_id = entry_id[10:]
            mat = self._get_local_material_by_id(mat_id)
            if mat:
                self._param_widget.show_local_material_info(mat)
            return
        node = self._geo_agent.convert_entry_id_to_node(entry_id)
        if node is None:
            return
        self._param_widget.set_curr_tree_id(entry_id)
        if node.ais_shape:
            self._occ_widget.highlight_shape(node.ais_shape)

    def _expand_all(self, item):
        item.setExpanded(True)
        for i in range(item.childCount()):
            self._expand_all(item.child(i))

    def _collapse_all(self, item):
        item.setExpanded(False)
        for i in range(item.childCount()):
            self._collapse_all(item.child(i))

    def _slot_tree_visibility_changed(self, entry_id: str, visible: bool):
        """Toggle shape visibility from project tree checkbox."""
        node = self._geo_agent.convert_entry_id_to_node(entry_id)
        if node is None or node.ais_shape is None:
            return
        node.visible = visible
        self._occ_widget.set_shape_visible(node.ais_shape, visible)

    def _slot_occ_shape_selected(self, ais_shape):
        try:
            for node in self._geo_agent.get_all_solid_nodes():
                if node.ais_shape is ais_shape:
                    self._project_tree.focus_on_entry_id(node.entry_id)
                    self._param_widget.set_curr_tree_id(node.entry_id)
                    break
        except Exception as e:
            self._logger.log_system(f"Sync selection to tree error: {str(e)}", level=LogLevel.ERROR)

    def _slot_update_progress(self, value: float, description: str):
        self._status_bar.showMessage(f"{description} ({value:.0f}%)")

    def get_occ_widget(self) -> WidgetOCC:
        return self._occ_widget

    def closeEvent(self, event):
        """Clean up OCC display before Qt destroys native window handles."""
        self._occ_widget.shutdown()
        super().closeEvent(event)

    def get_system_log_widget(self):
        return self._system_log


def _merge_vtk_files(input_vtk_paths: list, output_path: str):
    """Merge multiple legacy VTK files into one by concatenating datasets.

    Each input VTK file should be a legacy VTK file with one UNSTRUCTURED_GRID.
    The merged file writes POINTS and CELLS from all files sequentially.
    """
    all_points = []
    all_cells = []
    cell_type = None
    point_offset = 0

    for vtk_path in input_vtk_paths:
        points = []
        cells = []
        with open(vtk_path, "r") as f:
            section = None
            for line in f:
                line_stripped = line.strip()
                if line_stripped.startswith("DATASET "):
                    section = None
                elif line_stripped.startswith("POINTS "):
                    section = "POINTS"
                elif line_stripped.startswith("CELL_TYPES "):
                    section = "CELL_TYPES"
                elif line_stripped.startswith("CELLS "):
                    section = "CELLS"
                elif line_stripped.startswith("POINT_DATA "):
                    section = "POINT_DATA"
                elif section == "POINTS":
                    parts = line_stripped.split()
                    if len(parts) >= 3 and _is_number(parts[0]):
                        points.append((float(parts[0]), float(parts[1]), float(parts[2])))
                elif section == "CELLS":
                    parts = line_stripped.split()
                    if len(parts) >= 2 and parts[0].isdigit():
                        n = int(parts[0])
                        conn = [int(p) + point_offset for p in parts[1:1 + n]]
                        cells.append(conn)
                elif section == "CELL_TYPES":
                    parts = line_stripped.split()
                    for p in parts:
                        if p.isdigit():
                            cell_type = int(p)
                            break
        all_points.extend(points)
        all_cells.extend(cells)
        point_offset += len(points)

    n_points = len(all_points)
    n_cells = len(all_cells)
    cell_conn_size = sum(len(c) for c in all_cells)

    with open(output_path, "w") as f:
        f.write("# vtk DataFile Version 3.0\n")
        f.write("Merged mesh output\n")
        f.write("ASCII\n")
        f.write("DATASET UNSTRUCTURED_GRID\n")
        f.write(f"POINTS {n_points} float\n")
        for x, y, z in all_points:
            f.write(f"{x:.10f} {y:.10f} {z:.10f}\n")
        f.write(f"CELLS {n_cells} {n_cells + cell_conn_size}\n")
        for conn in all_cells:
            f.write(f"{len(conn)} {' '.join(str(c) for c in conn)}\n")
        if cell_type is not None:
            f.write(f"CELL_TYPES {n_cells}\n")
            for _ in all_cells:
                f.write(f"{cell_type}\n")


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
