"""
MainWindow - Primary application window.
"""

import os
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QSplitter, QVBoxLayout,
    QWidget, QFileDialog, QMessageBox, QDockWidget, QToolBar
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


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CAD2GDML - STEP to GDML Converter")
        self.resize(1600, 1000)
        self._dark_theme = True

        self._geo_agent = GeoDataAgent()
        self._library = MaterialsLib()
        self._task_manager = TaskManager()
        self._logger = AsyncLogger()

        # Mesh state
        self._mesh_runner: Optional[MeshRunner] = None
        self._mesh_progress_dlg: Optional[MeshProgressDialog] = None
        self._mesh_viewer: Optional[MeshViewer] = None
        self._meshed_nodes: dict = {}  # entry_id -> vtk_path
        self._mesh_work_dir: str = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "_mesh_temp"
        )

        # Build UI before theme
        self._init_toolbar()
        self._init_project_tree()
        self._init_occ_widget()
        self._init_property_panel()
        self._init_log_panel()
        self._init_layout()
        self._init_status_bar()

        # Apply unified theme after all UI panels exist
        self._apply_global_theme(True)
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

    def _toggle_theme(self):
        new_dark = not self._dark_theme
        self._apply_global_theme(new_dark)
        self._toolbar.set_dark_theme(new_dark)
        self._project_tree.set_dark_theme(new_dark)
        self._param_widget.set_dark_theme(new_dark)
        self._occ_widget.set_dark_theme(new_dark)
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
        self.showMaximized()

    def _init_status_bar(self):
        self._status_bar = self.statusBar()
        self._status_bar.showMessage("Ready")

    def _connect_signals(self):
        self._toolbar.import_step_clicked.connect(self._slot_import_step)
        self._toolbar.mesh_clicked.connect(self._slot_mesh)
        self._toolbar.view_mesh_clicked.connect(self._slot_view_mesh)
        self._toolbar.export_gdml_clicked.connect(self._slot_export_gdml)
        self._toolbar.export_vtk_clicked.connect(self._slot_export_vtk)
        self._toolbar.help_clicked.connect(self._slot_help)
        self._toolbar.theme_toggled.connect(self._toggle_theme)
        self._project_tree.item_selected.connect(self._slot_tree_item_selected)
        self._project_tree.item_visibility_changed.connect(self._slot_tree_visibility_changed)
        self._task_manager.progress_updated.connect(self._slot_update_progress)
        self._occ_widget.sig_shape_selected.connect(self._slot_occ_shape_selected)
        self._project_tree.get_tree_widget().customContextMenuRequested.connect(
            self._slot_tree_context_menu)

    # ---- Slots ----

    def _slot_import_step(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import STEP File", "", "STEP Files (*.step *.stp)")
        if not files:
            return

        self._logger.log_system(f"Importing: {', '.join(files)} ...")

        # 1. Mark the start
        self._task_manager.start_task("Import STEP")
        self._task_manager.update_progress(10, "Reading STEP files ...")
        QApplication.processEvents()

        # 2. Actually read the STEP files
        error_info: list = []
        ok = self._geo_agent.read_step_files(files, error_info)

        if not ok and error_info:
            for err in error_info:
                self._logger.log_system(f"  [ERROR] {err}", level=LogLevel.ERROR)

        self._task_manager.update_progress(40, "Building project tree ...")
        QApplication.processEvents()

        # 3. Populate the tree
        self._project_tree.populate_from_geo_agent(self._geo_agent)
        self._project_tree.get_geometry_root().setExpanded(True)

        self._task_manager.update_progress(60, "Rendering 3D shapes ...")
        QApplication.processEvents()

        # 4. Create AIS shapes with Lego colors and display them
        color_gen = LegoColorSingleton()
        solid_count = 0
        for solid_node in self._geo_agent.get_all_solid_nodes():
            if solid_node.shape is None:
                continue
            try:
                ais = AIS_Shape(solid_node.shape)
                ais.SetColor(color_gen.get_next_color())
                ais.SetDisplayMode(1)  # AIS_Shaded
                solid_node.ais_shape = ais
                self._occ_widget.add_shape(ais, name=solid_node.entry_id, update=False)
                solid_count += 1
            except Exception as e:
                self._logger.log_system(
                    f"  Error displaying {solid_node.name}: {e}", level=LogLevel.WARNING)

        # 5. Finalize
        self._occ_widget.fit_all()

        self._task_manager.update_progress(100, f"Imported {solid_count} solids")
        self._task_manager.finish_task()

        file_names = ", ".join(Path(f).name for f in files)
        self._logger.log_system(
            f"Import complete — {solid_count} solids from {len(files)} file(s): {file_names}")

    def _slot_mesh(self):
        """Open the mesh parameter dialog, then start meshing in background."""
        # Gather all solid nodes that need meshing
        solid_nodes = self._geo_agent.get_all_solid_nodes()
        if not solid_nodes:
            self._logger.log_system("No geometry loaded. Import a STEP file first.")
            QMessageBox.information(self, "No Geometry",
                                    "Import a STEP file before meshing.")
            return

        # Show parameter dialog
        dlg = GmshDialog(self)
        if dlg.exec() != GmshDialog.DialogCode.Accepted:
            self._logger.log_system("Meshing cancelled by user.")
            return

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
        """Open a fresh non-blocking VTK mesh viewer window."""
        if not self._meshed_nodes:
            self._logger.log_system("No mesh data to view. Run meshing first.")
            QMessageBox.information(self, "No Mesh",
                                    "Generate a mesh before viewing.")
            return

        # Destroy previous viewer to avoid stale OpenGL context
        if self._mesh_viewer is not None:
            try:
                self._mesh_viewer.close()
            except Exception:
                pass
            self._mesh_viewer.deleteLater()
            self._mesh_viewer = None

        self._mesh_viewer = MeshViewer()
        self._mesh_viewer.show()
        self._mesh_viewer.raise_()
        self._mesh_viewer.load_mesh(self._meshed_nodes)
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
        self._meshed_nodes = mesh_paths
        if success:
            self._logger.log_system(f"Meshing completed: {message}")
        else:
            self._logger.log_system(f"Meshing finished with issues: {message}",
                                    level=LogLevel.WARNING)
        self._mesh_runner = None



    def _slot_export_gdml(self):
        self._logger.log_system("GDML export requested (not yet implemented)")

    def _slot_export_vtk(self):
        self._logger.log_system("VTK export requested (not yet implemented)")

    def _slot_help(self):
        QMessageBox.about(self, "About CAD2GDML",
            "CAD2GDML v2.0\n\nSTEP to GDML geometry conversion tool.\n\n"
            "Built with PyQt6, pythonocc-core, and GMSH.")

    def _slot_tree_item_selected(self, entry_id: str):
        node = self._geo_agent.convert_entry_id_to_node(entry_id)
        if node is None:
            return
        self._param_widget.set_curr_tree_id(entry_id)
        if node.ais_shape:
            self._occ_widget.highlight_shape(node.ais_shape)

    def _slot_tree_context_menu(self, pos):
        tree = self._project_tree.get_tree_widget()
        item = tree.itemAt(pos)
        if item is None:
            return
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        if item.type() == TREE_ITEM_TYPE['GEO_ROOT']:
            act = menu.addAction("Import STEP File")
            act.triggered.connect(self._slot_import_step)
            menu.addSeparator()
            menu.addAction("Expand All").triggered.connect(lambda: self._expand_all(item))
            menu.addAction("Collapse All").triggered.connect(lambda: self._collapse_all(item))
        elif item.type() == TREE_ITEM_TYPE['GEO_SOLID']:
            menu.addAction("Mesh").triggered.connect(self._slot_mesh)
            menu.addAction("Mesh Preview").triggered.connect(self._slot_view_mesh)
            menu.addSeparator()
            menu.addAction("Export GDML").triggered.connect(self._slot_export_gdml)
        menu.exec(tree.viewport().mapToGlobal(pos))

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
                    # Also update property panel
                    self._param_widget.set_curr_tree_id(node.entry_id)
                    break
        except Exception as e:
            self._logger.log_system(f"Sync selection to tree error: {str(e)}", level=LogLevel.ERROR)

    def _slot_update_progress(self, value: float, description: str):
        self._status_bar.showMessage(f"{description} ({value:.0f}%)")

    def get_occ_widget(self) -> WidgetOCC:
        return self._occ_widget

    def get_system_log_widget(self):
        return self._system_log
