"""
MainWindow - Primary application window.
"""

import math
import os
import shutil
import time
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QSplitter, QVBoxLayout,
    QWidget, QFileDialog, QMessageBox, QDockWidget, QToolBar,
    QDialog, QLabel, QProgressBar
)
from PyQt6.QtCore import Qt, QEventLoop, QTimer
from PyQt6.QtGui import QPalette, QColor

from OCC.Core.AIS import AIS_Shape
from OCC.Core.Quantity import Quantity_Color

from core.geo_data_agent import GeoDataAgent
from core.cad_process import needs_child_process, read_file_in_child_process
from core.materials_lib import MaterialsLib
from core.lego_color_singleton import LegoColorSingleton
from core.node_transform import (
    TransformSpec, rotation_centre, transformed, trsf_for,
)
from ui.toolbar import RibbonToolBar
from ui.project_tree import ProjectTreeWidget, TREE_ITEM_TYPE
from ui.occ_widget import WidgetOCC
from ui.geo_param_widget import GeoParamWidget
from ui.import_progress import ImportProgressDialog
from utils.task_manager import TaskManager
from utils.logger import AsyncLogger, LogLevel
from mesh.gmsh_dialog import DEFAULT_PARAMS, MeshParamsWidget
from mesh.remesh_scope_dialog import MeshScopeDialog, resolved_mode
from mesh.scope import MeshGroup, build_groups, group_key, part_param_rows
from mesh.mesh_runner import MeshRunner
from mesh.mesh_viewer import MeshViewer
from mesh.assembly_analysis import AssemblyAnalyzer
from core.conformity import (
    AnalysisResult, MeshOutcome, CONFORMAL, NON_CONFORMAL, PARTIAL, UNKNOWN,
    state_color_for, text as state_text,
)
from ui.export_gdml_dialog import ExportGdmlDialog
from ui.mesh_group_dialog import MeshGroupDialog
from ui.transform_dialog import TransformDialog

# Live preview of the transform dialog: a spin box reports every arrow-key step,
# and each preview re-transforms the whole import, so the edits are coalesced for
# this long before the model is moved.
_PREVIEW_DEBOUNCE_MS = 80


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
        # Whether the running session was stopped by the user. A cancelled
        # session is not a finished one, and the status bar cell says so.
        self._mesh_cancelled = False
        self._meshed_nodes: dict = {}  # entry_id -> vtk_path
        # Contact analysis: starts in the background right after import; its
        # result decides the meshing mode
        self._analysis: Optional[AnalysisResult] = None
        self._analysis_runner: Optional[AssemblyAnalyzer] = None
        # Whether the automatic contact check is switched off for this model
        # (the box on the import dialog, left unticked). Only the automatic
        # triggers honour it -- the import, a delete, a move -- so a model the
        # user asked not to check is not then checked behind their back. The
        # scope panel's Check contacts is an explicit ask and clears it.
        self._contact_skipped = False
        # Verdict of the last meshing run, used to gate the export
        self._mesh_outcome: Optional[MeshOutcome] = None
        # The scope panel while it is open, so a late contact analysis can be
        # filled into it (see _on_analysis_done).
        self._open_mesh_dialog = None
        # The group window opened from the panel (one at a time).
        self._group_dialog = None
        self._mesh_work_dir: str = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "_mesh_temp"
        )
        # ---- Versioned work area: one directory per run ----
        # The whole tree used to be wiped at every mesh start, so a failed
        # re-mesh took the previous, good VTK set with it and left _meshed_nodes
        # pointing at deleted files (see doc/remesh_ui_mockup.html §5). Each run
        # now gets _mesh_temp/run_NNN, so failing costs nothing and the previous
        # run stays on disk to roll back to or to look at afterwards.
        self._mesh_run_dir: str = ""           # work dir of the run in flight
        self._mesh_prev_run_dir: str = ""      # work dir of the run before it
        # Snapshot of the published mesh taken when a run starts: this is what
        # "Roll back to #N" puts back, and what tells us whether a rollback is
        # possible at all.
        self._mesh_prev_nodes: dict = {}
        self._mesh_prev_params: dict = {}
        self._mesh_prev_source: dict = {}
        self._mesh_prev_outcome: Optional[MeshOutcome] = None
        self._mesh_prev_run: Optional[dict] = None
        self._mesh_prev_run_no: int = 0
        # ---- One mesh session: one accepted panel, one job per group ----
        # A session is a list of jobs rather than a single run because each
        # group carries its own parameters and its own mode (remesh_scope_dialog).
        self._mesh_jobs: list = []          # [(MeshGroup, params)] still to run
        self._mesh_run_no: int = 0
        self._mesh_scope_text: str = ""
        self._mesh_session_meshed: dict = {}   # entry_id -> vtk_path, this session
        self._mesh_kept: dict = {}             # paths kept from earlier sessions
        self._mesh_job_elapsed: dict = {}      # group index -> seconds
        # One entry per finished job, in run order: the session verdict is the
        # worst of them (_combine_outcomes), not the last one.
        self._mesh_session_outcomes: list = []
        self._mesh_session_failed: int = 0
        # The values last used. Passed back into the panel so that re-opening it
        # repeats the last run instead of quietly reverting to the defaults.
        self._last_mesh_params: dict = dict(DEFAULT_PARAMS)
        self._last_mesh_run: Optional[dict] = None
        self._mesh_current_group: Optional[MeshGroup] = None
        self._mesh_current_params: dict = {}
        self._mesh_job_started: float = 0.0
        # Per group, the values its existing mesh was made with, keyed by member
        # set (scope.group_key): the panel opens each group at its own numbers,
        # marks what changed against them, and skips a group that has nothing to
        # redo. This is what makes "the second run only meshes what changed" true.
        self._meshed_params: dict = {}
        # Which job wrote each part's current file: entry_id -> the member set of
        # the group that produced it. Both kinds of run write the same part's
        # file, so _meshed_params alone cannot say whether a record still
        # describes the facets in use -- an assembly run leaves every per-solid
        # record of its members intact while replacing their meshes with one
        # fragment each. This is the provenance that closes the gap, and it is
        # what the panel and the preview read to tell the two apart.
        self._mesh_source: dict = {}

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
            pb_bg = "#313244"; pb_chunk = "#89b4fa"
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
            pb_bg = "#ffffff"; pb_chunk = "#0078d4"

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
        # NB: a QLabel placed in the status bar does NOT inherit the font
        # declared on QStatusBar, so the two right-hand cells used to render at
        # the application default font while the message on the left rendered at
        # 12 px. The descendant rule below pins them to the very same
        # declaration, so left and right always agree -- and because both the
        # background and this foreground come from the theme, the cells simply
        # invert when the theme is switched.
        # The contact bar carries one state more than the full/empty pair: an
        # analysis that ended without an answer. It checked nothing, so it may
        # not wear the full bar, and it is not a wait still on either, so the
        # empty groove on its own is not enough -- it takes the red of the
        # NON_CONFORMAL state. A dynamic property rather than an instance
        # stylesheet, because this red is a theme colour like the two above: it
        # has to be resolved again when the theme is switched, and this is the
        # one place that knows which theme is on. _set_status_progress owns the
        # property of the same name.
        err = state_color_for(NON_CONFORMAL, dark)
        self._status_bar.setStyleSheet(f"""
            QStatusBar {{ background-color: {st_bg}; color: {st_fg};
                font-size: 12px; padding: 2px 8px; }}
            QStatusBar QLabel {{ color: {st_fg}; font-size: 12px; }}
            QStatusBar QProgressBar {{ background-color: {pb_bg};
                border: 1px solid {st_fg}; border-radius: 3px; }}
            QStatusBar QProgressBar::chunk {{ background-color: {pb_chunk};
                border-radius: 2px; }}
            QStatusBar QProgressBar[failed="true"] {{ background-color: {err};
                border: 1px solid {err}; border-radius: 3px; }}
            QStatusBar QProgressBar[failed="true"]::chunk
                {{ background-color: {err}; border-radius: 2px; }}
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

        # Three permanent cells on the right: conformity state, contact analysis
        # progress and meshing progress. The contact analysis is the only basis
        # for choosing a meshing mode, so it must be visible right after import;
        # otherwise the user has to pick blindly when pressing Mesh
        # (see doc/assembly_fragment_ui.md §9.6).
        #
        # Typography: plain text, no colour of their own. Two things were wrong
        # before. (1) Rich text plus a 🟢/🔴 emoji made Qt pull in a second font
        # (Segoe UI Emoji) for the leading glyph. (2) A QLabel placed in a status
        # bar does *not* inherit the font declared on QStatusBar -- measured, the
        # cells stayed at the application default (9 pt) while "Ready" rendered
        # at 12 px, so the two halves of the bar never matched, and on a scaled
        # display they drifted further apart. The descendant rule in
        # _apply_global_theme pins the cells to the status bar's own font and
        # foreground, so they read exactly like the message on the left and
        # simply invert when the theme is switched.
        self._conformity_label = QLabel()
        self._conformity_label.setMinimumWidth(240)
        self._analysis_label = QLabel()
        self._analysis_label.setMinimumWidth(200)
        # The bar of the contact analysis, and of nothing else, placed right
        # after the cell that names that analysis: it is the same statement
        # drawn instead of spelled out. It is resident, like the cells beside
        # it, and that is the point: shown and hidden it dragged those cells
        # left and right every time an analysis started and landed. A landed
        # analysis leaves it full and the next run starts it over
        # (_set_status_progress), so at rest the cell reads "checked, 100%".
        # A meshing session has a bar of its own in its own window, and its
        # cell here carries the percentage in words.
        self._contact_progress_bar = QProgressBar()
        self._contact_progress_bar.setFixedWidth(90)
        self._contact_progress_bar.setFixedHeight(10)
        self._contact_progress_bar.setTextVisible(False)
        self._contact_progress_bar.setValue(0)
        # Third cell: the meshing progress of the running session. The progress
        # window is a window the user has usually pushed aside to look at the
        # model, and the cell beside it only speaks about the import, so this is
        # the one place that says how far the meshing itself has got.
        self._mesh_progress_label = QLabel()
        self._mesh_progress_label.setMinimumWidth(150)
        for lb in (self._conformity_label, self._analysis_label,
                   self._mesh_progress_label):
            lb.setContentsMargins(8, 0, 8, 0)
            lb.setAlignment(Qt.AlignmentFlag.AlignLeft |
                            Qt.AlignmentFlag.AlignVCenter)
        self._status_bar.addPermanentWidget(self._conformity_label)
        self._status_bar.addPermanentWidget(self._analysis_label)
        self._status_bar.addPermanentWidget(self._contact_progress_bar)
        self._status_bar.addPermanentWidget(self._mesh_progress_label)

        self._set_conformity(UNKNOWN)
        self._set_analysis_text("Contact: waiting for import")
        self._set_mesh_status()

    # ---- Single update entry point for the status bar cells ----
    #
    # Text only; the colour is the status bar's own foreground, so it follows
    # the theme on its own. The state itself is carried by the words.

    def _set_analysis_text(self, text: str):
        if hasattr(self, "_analysis_label"):
            self._analysis_label.setText(text)

    def _set_conformity(self, kind: str, detail: str = ""):
        if not hasattr(self, "_conformity_label"):
            return
        txt = state_text(kind)
        if detail:
            txt += f" · {detail}"
        self._conformity_label.setText(txt)

    def _set_status_progress(self, value: Optional[int], failed: bool = False):
        """The single entry point for the contact bar of the status bar.

        One bar, one owner: this is the contact analysis that runs right after
        import and on demand from the scope panel, and no other wait in the
        application is allowed to write here. The bar answers "how far is the
        thing I am waiting on", which is a question it can only be asked about
        one thing at a time.

        None is what a landed analysis writes, and it leaves the bar full: the
        bar then answers "is this model checked" at a glance, while the empty
        groove of a bar taken back down says a wait is still on. The cell beside
        it names the verdict in words, and the next run resets the bar by
        writing its own numbers.

        failed is the third state and the reason the value is not enough on its
        own: an analysis that ended without an answer is empty like a fresh run
        and must not be read as one, so the groove takes the red declared for
        [failed="true"] in _apply_global_theme. Value and tint are written
        together, so the next run clears the override by writing numbers of its
        own.
        """
        if not hasattr(self, "_contact_progress_bar"):
            return
        bar = self._contact_progress_bar
        bar.setValue(100 if value is None else max(0, min(100, int(value))))
        # Re-polished only on a change of state: _on_analysis_progress writes
        # here many times a second, and a re-polish per tick would cost more
        # than it can ever show.
        if bool(bar.property("failed")) != failed:
            bar.setProperty("failed", failed)
            bar.style().unpolish(bar)
            bar.style().polish(bar)

    def _set_mesh_status(self, text: str = ""):
        """The single entry point for the meshing cell of the status bar.

        The cell is permanent, never hidden: it sits empty and dashed between
        runs. A cell that only exists while a session runs cannot do its job --
        the user has no way of telling "no progress yet" from "no such thing",
        and on a mesh that takes a few seconds it is gone again before it has
        been noticed.

        The percentage is part of the text and not of a bar: the bar of the
        status bar belongs to the contact analysis.
        """
        if not hasattr(self, "_mesh_progress_label"):
            return
        self._mesh_progress_label.setText(text or "Fragment: idle")

    def _mesh_session_progress(self, value: int) -> tuple:
        """Where the session as a whole stands, given the running job's percent.

        A session is one job per group, so the job's own number is not the
        answer the user is after: (which group, of how many) and the overall
        percentage are what the cell reports.
        """
        done = len(self._mesh_job_elapsed)
        total = max(done + len(self._mesh_jobs) + 1, 1)
        overall = int((done + value / 100.0) / total * 100)
        # Capped at 99: 100% is only ever written once the whole session is
        # over (_finish_mesh_session), so the number on its own says whether
        # there is still something running.
        return done + 1, total, max(0, min(99, overall))

    # ---- Contact analysis (runs automatically after import) ----

    def _on_recheck_contacts(self):
        """The scope panel's Check contacts was pressed.

        An explicit ask, so it runs even on a model whose automatic check was
        turned off at import -- and clears the model's setting by doing so, so
        the automatic triggers that follow (a delete, a move) stay honest about
        an answer that is now there.
        """
        self._start_assembly_analysis(True)

    def _start_assembly_analysis(self, check: Optional[bool] = None):
        """Run the contact analysis in the background as soon as import ends.

        It is the only basis for "assembly conformal or per-solid": when a
        contact face exists, assembly is mandatory, otherwise each side of that
        face would get its own facet set. Running it after import means the
        answer is already there when the user presses Mesh.

        `check` is the answer to "is this wanted at all". None is an automatic
        trigger -- the import, a delete, a move -- and the model's own setting
        decides it (see _contact_skipped). True is the scope panel's Check
        contacts, an explicit ask. False is the import box left unticked, and
        that is a state of its own rather than a gap: the rows stay per-solid,
        and "not checked" has to read as that and not as a verdict (see
        _push_contact_state).
        """
        prev = self._analysis_runner
        if prev is not None and prev.isRunning():
            # cancel() kills the worker process and returns at once, so there
            # is nothing to wait for and the UI thread is never parked here.
            prev.cancel()

        if check is None:
            check = not self._contact_skipped
        self._contact_skipped = not check

        self._analysis = None
        if not check:
            # The bar of the model that was on screen before this one goes with
            # it: a full bar means "checked" and this model has not been.
            self._set_analysis_text("Contact: skipped")
            self._set_status_progress(0)
            self._push_contact_state()
            return

        solids = self._geo_agent.get_all_solid_nodes()
        if not solids:
            self._set_analysis_text("Contact: no geometry")
            # Nothing to analyse, so no answer lands either: the bar of the
            # model that was on screen before this one goes with it, because
            # the full bar means "checked" and this model has not been.
            self._set_status_progress(0)
            return

        self._analysis_runner = AssemblyAnalyzer(
            [n.shape for n in solids],
            [n.name or n.entry_id for n in solids],
            parent=self)
        self._analysis_runner.progress.connect(self._on_analysis_progress)
        self._analysis_runner.log.connect(self._on_analysis_log)
        self._analysis_runner.finished_analysis.connect(self._on_analysis_done)
        self._set_analysis_text("Contact: running... 0%")
        self._set_status_progress(0)
        self._analysis_runner.start()
        self._push_contact_state()

    def _on_analysis_progress(self, value: int, message: str):
        self._set_analysis_text(f"Contact: {message} {value}%")
        # The bar goes with the text: the analysis is the long wait before the
        # first mesh, so it is what the bar is showing while it runs.
        self._set_status_progress(value)
        # The same number into the scope panel's own bar while one is open: the
        # re-check is pressed there, so that is the window the wait has to report
        # in (MeshScopeDialog.set_contact_progress). Two bars, one wait -- this
        # status bar cell is the reading that survives with the panel closed.
        panel = self._mesh_panel()
        if panel is not None:
            panel.set_contact_progress(value, message)

    def _on_analysis_log(self, line: str):
        self._logger.log_system(line)

    def _on_analysis_done(self, res: AnalysisResult):
        self._analysis = res
        ok = res is not None and not res.failed
        # The bar is settled by the wait it was opened for: full once an answer
        # has landed, empty and red when the run ended without one, because
        # "checked" is exactly what a failed run is not. A run that a newer one
        # has superseded is not allowed to write here at all -- the bar belongs
        # to the newer run now, and settling it here would report an answer that
        # has not been given.
        if self.sender() is self._analysis_runner:
            self._set_status_progress(None if ok else 0, failed=not ok)
        if ok:
            self._set_analysis_text(f"Contact: done ({res.elapsed:.1f} s)")
            self._logger.log_system(
                f"Mesh mode suggestion: {res.mode_label} -- {res.reason}")
        else:
            reason = res.reason if res is not None else "no result"
            self._set_analysis_text(f"Contact: incomplete ({reason})")
        self._push_contact_state()
        self._fill_open_scope_panel()

    def _push_contact_state(self):
        """Tell the open panel where the contact analysis stands.

        The panel can be open before the analysis lands, and while it has no
        answer every solid is a unit of its own -- which the panel has to be
        able to tell apart from a model the analysis has cleared, and from a
        model nothing was ever asked to look at (see
        MeshScopeDialog.set_contact_state). Driven from the four moments the
        state changes: the analysis starts, it ends, it is skipped, and a panel
        opens onto whatever it happens to be doing.
        """
        dlg = self._open_mesh_dialog
        if dlg is None:
            return
        res = self._analysis
        if res is not None and not res.failed:
            dlg.set_contact_state("done")
        elif res is not None:
            dlg.set_contact_state("failed", res.reason)
        elif self._contact_skipped:
            # Not a wait and not a verdict either: nothing has looked at this
            # model, and the per-solid rows below must not read as "nothing
            # touches anything".
            dlg.set_contact_state("skipped")
        elif self._analysis_runner is not None \
                and self._analysis_runner.isRunning():
            dlg.set_contact_state("running")

    def _fill_open_scope_panel(self):
        """Hand a late contact analysis to a scope panel that is already open.

        The panel can be opened before the analysis lands, and on a big
        assembly that is the normal case rather than the exception. A panel
        built without it is a list of lonely solids for a model that is one
        assembly, so it is regrouped in place -- the ticks follow the solids
        they were on, so nothing the user set is lost.

        A panel whose rows have already been planned once is the exception. The
        rows are what that run's progress and report were about, so they are not
        rebuilt: the panel holds the answer and offers it back to the user in
        its notice line (set_components). Nothing is logged here in that case --
        the user writes that line by taking the offer.
        """
        dlg = self._open_mesh_dialog
        res = self._analysis
        if dlg is None or not dlg.isVisible() or res is None or res.failed:
            return
        if dlg.set_components(
                self._current_mesh_groups(self._geo_agent.get_all_solid_nodes())):
            self._log_scope_regrouped()

    def _log_scope_regrouped(self):
        """One regrouping, one line -- the automatic one and the offered one."""
        self._logger.log_system(
            "Scope panel regrouped from the contact analysis: the coupled "
            "parts are listed as one assembly group now.")

    def _connect_signals(self):
        self._toolbar.import_step_clicked.connect(self._slot_import_step)
        self._toolbar.interference_clicked.connect(self._slot_interference)
        self._toolbar.interference2_clicked.connect(self._slot_interference_2)
        self._toolbar.assign_material_clicked.connect(self._slot_assign_material)
        self._toolbar.mesh_clicked.connect(self._slot_mesh)
        # The button is a three-state one (Mesh / Re-mesh / Cancel): the same
        # click target means "start" or "stop" depending on whether a session is
        # in flight, so both signals have to be wired.
        self._toolbar.mesh_cancel_clicked.connect(self._on_mesh_cancel)
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
        self._project_tree.edit_transform_requested.connect(
            self._slot_edit_transform)
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

        # Shown straight away and kept up for the whole read, then closed once
        # at the end: a window-modal box left open would block every input.
        # The box it carries is the contact check: off is for a model whose
        # read already told the user how big it is, since the check is a whole
        # second pass over it (see _start_assembly_analysis).
        progress = ImportProgressDialog(self)
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

        t_step = [0.0]

        def _pump() -> bool:
            """Drive the box while a child process converts the file.

            OCC reports nothing inside TransferRoots(), so the bar runs on
            elapsed time: quick at first, then asymptotic onto the 85 % that
            the tree and render stages take over from.
            """
            elapsed = time.time() - t_step[0]
            progress.setValue(int(85 * (1.0 - math.exp(-elapsed / 6.0))))
            QApplication.processEvents()
            return not progress.wasCanceled()

        def _cancelled() -> bool:
            if not progress.wasCanceled():
                return False
            progress.close()
            self._logger.log_system("Import cancelled by user.",
                                    level=LogLevel.WARNING)
            return True

        error_info: list = []
        file_nodes = []

        for i, fp in enumerate(files):
            if _cancelled():
                return

            label = Path(fp).name
            # A big file is read in a child process: OCC holds the GIL for the
            # whole conversion, so an inline read would freeze the window (and
            # this box with it) for exactly as long as the conversion takes.
            big = needs_child_process(fp)
            progress.setLabelText(
                f"Reading {label}"
                f"{' - converting large file' if big else ''}...")
            QApplication.processEvents()

            t_step[0] = time.time()
            if big:
                node, child_errors = read_file_in_child_process(fp, _pump)
                if _cancelled():
                    return
                error_info.extend(child_errors)
                if node is not None:
                    _progress_cb(1, 1, node.get_leaf_nodes())
            else:
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

        # Read before the box goes away: this is the last moment it can still be
        # changed, and nothing between here and the run below can change it.
        check_contacts = progress.check_contacts()
        self._occ_widget.fit_all()
        progress.setValue(100)
        progress.close()
        QApplication.processEvents()

        elapsed = time.time() - t_import
        file_names = ", ".join(Path(fp).name for fp in files)
        self._logger.log_system(
            f"Import complete ({elapsed:.1f}s) — {rendered} solids from "
            f"{len(files)} file(s): {file_names}")

        # A new import is a new model: everything that described the old one goes
        # (see _reset_model_state).
        self._reset_model_state()

        # Start the contact analysis in the background right away: it is the only
        # basis for "assembly conformal or per-solid"
        self._start_assembly_analysis(check_contacts)

    def _reset_model_state(self):
        """Drop everything that describes the geometry that was on screen.

        Called when a new import replaces the model, and when the loaded model is
        moved (its geometry is then somewhere else, and a mesh is a set of
        coordinates). The verdict, the per-group values and the run history all
        describe parts that are no longer where they were, so letting them
        survive would make them actively misleading -- the panel would offer to
        repeat a run on parts that have moved or no longer exist.
        """
        self._discard_mesh_scope_panel()
        self._meshed_nodes = {}
        self._meshed_params = {}
        self._mesh_source = {}
        self._mesh_outcome = None
        self._last_mesh_run = None
        self._last_mesh_params = dict(DEFAULT_PARAMS)
        self._mesh_run_no = 0
        # Nothing points into the work area any more, so this is the one place
        # where the run directories may go in bulk: keeping them would offer to
        # roll back to a model that is no longer loaded.
        self._forget_mesh_runs()
        self._toolbar.set_mesh_state("mesh")
        self._set_conformity(UNKNOWN)
        # A new model has no run of its own, so the cell goes back to idle here
        # (the one place that may empty a cell a finished run left full).
        self._set_mesh_status()

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
            self._mesh_source.pop(eid, None)
        # A group's values describe the parts that were meshed together, so a key
        # that just lost one of them describes nothing: it goes rather than wait
        # for a group that no longer exists in that shape.
        self._meshed_params = {
            k: v for k, v in self._meshed_params.items()
            if not (set(k) & set(removed_ids))}

        # Repopulate tree
        self._project_tree.populate_from_geo_agent(self._geo_agent)

        # Fit 3D view
        self._occ_widget.fit_all()

        self._logger.log_system(
            f"Deleted geometry: {node.name} ({len(all_descendants)} part(s))")

        # The solid set changed, so the previous contact analysis is void; redo it
        self._discard_mesh_scope_panel()
        self._start_assembly_analysis()

    def _slot_edit_transform(self, entry_id: str):
        """Place one imported file as a whole: translate and rotate all of it.

        Offered on the file row only, and deliberately not per solid: a CAD
        import is one rigid body, the parts are where they are *relative to each
        other*, and moving one of them on its own would break exactly the contact
        the mesher works on.
        """
        node = self._geo_agent.convert_entry_id_to_node(entry_id)
        if node is None:
            return

        # Same guard as the export slots use: a job in flight describes the
        # placement it started in, so moving the model under it would leave the
        # session writing meshes of where the parts used to be.
        if self._mesh_runner is not None:
            self._logger.log_system(
                "Meshing is still in progress. Please wait until it completes.",
                level=LogLevel.WARNING)
            QMessageBox.information(
                self, "Meshing In Progress",
                "A meshing session is running. Wait for it to finish before "
                "moving the model.")
            return

        targets = [n for n in [node] + node.get_all_descendants()
                   if n.shape is not None]
        if not targets:
            self._logger.log_system(
                f"{node.name}: nothing to transform, no shape is loaded.",
                level=LogLevel.WARNING)
            return

        # The shapes as imported. Every node keeps its own from the first
        # transform on, so a spec is always applied to the import -- editing the
        # numbers edits the placement instead of stacking one on top of the last.
        bases = [n.base_shape if n.base_shape is not None else n.shape
                 for n in targets]

        # The placement in force when the dialog opened: what Cancel restores.
        original = node.transform or TransformSpec()
        dlg = TransformDialog(node.name, original, dark=self._dark_theme,
                              parent=self)

        # Live preview. Qt goes on running the event loop while the dialog is up,
        # so its edits can reach the model, and because every spec is applied to
        # the shapes as imported, each preview *replaces* the last instead of
        # stacking on it (core/node_transform.py). Debounced: a spin box reports
        # every arrow-key step, and transforming a whole assembly is not free.
        placed = {"spec": None}

        def preview():
            placed["spec"] = dlg.spec()
            self._place_spec(node, targets, bases, placed["spec"])

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(_PREVIEW_DEBOUNCE_MS)
        timer.timeout.connect(preview)
        dlg.specChanged.connect(lambda: timer.start())

        # The ruler in the corner measures the bounding box of everything on
        # screen, so it would rescale at every preview step. It is taken down for
        # the time the dialog is up and put back on the placement that is kept,
        # so it is computed once, on what the dialog actually leaves behind.
        self._occ_widget.set_trihedron_visible(False)

        # The dialog is not modal: a placement is only readable against the
        # structure it lands in, and that means turning the model around while
        # the numbers are being tried -- and the camera is driven by mouse
        # gestures on the main window. What the dialog cannot survive is the
        # model changing under it -- deleted, replaced, or a second dialog opened
        # on it -- so the commands that do that are taken out while it is up. The
        # viewport and the read-only panels stay.
        frozen = (self._toolbar, self._tree_dock)
        for widget in frozen:
            widget.setEnabled(False)

        # exec() would make the dialog application-modal and take the main
        # window's input with it, so the waiting is done by hand. The loop also
        # has to end when the window is closed under the dialog: nothing else
        # would end it, and the process would go on running with nothing on
        # screen.
        app = QApplication.instance()
        loop = QEventLoop()
        window_closed = False

        def end_wait():
            nonlocal window_closed
            window_closed = True
            loop.quit()

        app.lastWindowClosed.connect(end_wait)
        dlg.finished.connect(lambda *_: loop.quit())
        dlg.show()
        loop.exec()
        app.lastWindowClosed.disconnect(end_wait)
        for widget in frozen:
            widget.setEnabled(True)
        if window_closed:
            return
        accepted = dlg.result() == QDialog.DialogCode.Accepted

        timer.stop()
        dlg.specChanged.disconnect()
        timer.deleteLater()
        spec = dlg.spec()
        # exec() used to own the dialog and drop it on return; shown by hand, it
        # is parented to the window and would otherwise sit there for the life of
        # the session, once per edit.
        dlg.deleteLater()

        def restore():
            """Undo the previews: back to the placement the dialog opened on."""
            if placed["spec"] is not None:
                self._place_spec(node, targets, bases, original)
            self._occ_widget.set_trihedron_visible(True)

        if not accepted:
            restore()
            return

        if spec.is_identity() and original.is_identity():
            self._occ_widget.set_trihedron_visible(True)
            return  # nothing asked for, and nothing was in force

        if self._meshed_nodes:
            reply = QMessageBox.question(
                self, "Edit Transform",
                f"'{node.name}' has a mesh ({len(self._meshed_nodes)} part(s) "
                "meshed in all).\n\nMoving the model invalidates it, so it will "
                "be dropped and has to be made again.\n\nApply the transform?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                restore()
                return
            had_mesh = True
        else:
            had_mesh = False

        # Nothing to do if the debounce got there first -- the preview writes the
        # placement through the same call, so both roads lead to the same result.
        if placed["spec"] != spec:
            self._place_spec(node, targets, bases, spec)

        self._occ_widget.set_trihedron_visible(True)
        # The parts are somewhere new, so the panel's bounding box -- read off
        # the shape as it stands -- describes the place they were in before the
        # dialog opened.
        for target in targets:
            self._param_widget.refresh_node(target)
        self._reset_model_state()
        self._occ_widget.fit_all()

        self._logger.log_system(
            f"{node.name}: transform applied — {spec.describe()} "
            f"({len(targets)} part(s) moved as one body)")
        if had_mesh:
            self._logger.log_system(
                "The mesh was dropped: it was generated in the old placement, so "
                "it is made again from the parts where they are now.",
                level=LogLevel.WARNING)

        # What touches what is the input to the next Mesh press, so it has to be
        # right -- but not necessarily *recomputed*. A rigid move of the whole
        # model leaves every contact exactly where it was, so the analysis
        # already in hand is still the answer, and re-running it on a big
        # assembly would be the most expensive thing this dialog does, for
        # nothing (the demo 18-solid assembly takes seconds; the pairs grow with
        # the square of the solid count). Only a move of *part* of the model can
        # change contacts, and only for the pairs that cross between the moved
        # file and the rest.
        analysis = self._analysis
        solids = self._geo_agent.get_all_solid_nodes()
        moved = {id(n) for n in targets}
        whole_model = (
            analysis is not None and not analysis.failed
            and len(solids) == analysis.n_solids      # same solids it analysed
            and all(id(n) in moved for n in solids))  # ...and all of them moved

        if whole_model:
            self._set_analysis_text(
                f"Contact: kept ({analysis.n_solids} solids, moved as one body)")
            self._logger.log_system(
                "Contact analysis kept as it stands: the whole model moved as one "
                "rigid body, so which parts touch which did not change.")
        else:
            self._start_assembly_analysis()

    def _place_spec(self, node, targets, bases, spec):
        """Put a file's parts where `spec` says, applied to the shapes as imported.

        The one place a placement is written, shared by the transform dialog's
        live preview and by its commit, so what is previewed and what is kept
        cannot drift apart. `bases` is the shapes as imported (see the caller).
        """
        trsf = trsf_for(spec, rotation_centre(spec, bases))
        for n, base in zip(targets, bases):
            n.base_shape = base
            n.shape = transformed(base, trsf)
            if n.ais_shape is not None:
                self._replace_displayed_shape(n)
        # None while the file sits where it was imported: "placed" and "not
        # placed" stay distinguishable, so re-opening the dialog on a file that
        # was reset shows zeros rather than a zero spec that was once a move.
        node.transform = None if spec.is_identity() else spec
        self._occ_widget.fresh()

    def _replace_displayed_shape(self, node):
        """Show a node's new shape in place of the one it had.

        The fast path keeps the AIS object and so keeps its colour, transparency
        and display mode; a fresh AIS_Shape is the fallback for an object that
        would not take the new shape, and is why the look is copied across.
        """
        ais = node.ais_shape
        if ais is None:
            # Never displayed (an assembly node above the solids is not drawn on
            # its own), so there is nothing to keep up to date.
            return
        if self._occ_widget.update_shape(ais, node.shape, update=False):
            return

        # The object would not take the new shape, so it goes and a fresh one
        # takes its place -- carrying the colour and transparency across, since
        # only the geometry is supposed to be new.
        color = None
        transparency = 0.4
        try:
            stored = Quantity_Color()
            ais.Color(stored)
            color = stored
            transparency = ais.Transparency()
        except Exception:
            pass
        self._occ_widget.erase_shape(ais, update=False)

        fresh = AIS_Shape(node.shape)
        if color is not None:
            fresh.SetColor(color)
        fresh.SetDisplayMode(1)
        try:
            fresh.SetTransparency(transparency)
        except Exception:
            pass
        node.ais_shape = fresh
        self._occ_widget.add_shape(fresh, update=False, name=node.name)

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
        """Open the scope panel; on OK it starts the meshing session.

        Non-modal: the panel is shown, and the session is started from its
        `accepted` signal. Keeping the main window live is the point -- the panel
        is where a group is picked, and the 3D view is where it is inspected.
        """
        # Gather all solid nodes that need meshing
        solid_nodes = self._geo_agent.get_all_solid_nodes()
        if not solid_nodes:
            self._logger.log_system("No geometry loaded. Import a STEP file first.")
            QMessageBox.information(self, "No Geometry",
                                    "Import a STEP file before meshing.")
            return

        # One panel at a time. It is non-modal now, so a second press of Mesh
        # would open a second list of groups over the first one -- same model,
        # two sessions planned from it. The open one is raised instead.
        opened = self._open_mesh_dialog
        if opened is not None and opened.isVisible():
            opened.raise_()
            opened.activateWindow()
            return

        # The scope panel: the groups and the parameters in one place, for a
        # first mesh and for a re-mesh alike (mesh/remesh_scope_dialog.py).
        groups = self._current_mesh_groups(solid_nodes)
        if self._contact_skipped:
            # Not a wait: nothing is coming, so the panel has to say who turns
            # it on (its own Check contacts) rather than promise a regroup.
            self._logger.log_system(
                "Contact check skipped at import: every part is listed on its "
                "own. Check contacts in this panel to regroup them.")
        elif self._analysis is None:
            # The panel is being built without the contact analysis, so every
            # solid is listed on its own whether or not it touches a neighbour.
            # It is filled in as soon as the analysis lands (see
            # _fill_open_scope_panel) -- unless a run is planned from these
            # rows first, in which case the answer is offered instead.
            self._logger.log_system(
                "Contact analysis still running: the scope starts per-solid "
                "and is regrouped when the analysis lands (or offered back "
                "once a run has used these rows).",
                level=LogLevel.WARNING)
        elif self._analysis.failed:
            self._logger.log_system(
                f"Contact analysis unavailable ({self._analysis.reason}): "
                "every part is listed per-solid.")
        first_run = not self._meshed_nodes

        dlg = MeshScopeDialog(
            groups,
            nodes=solid_nodes,
            initial_params=self._last_mesh_params,
            dark=self._dark_theme,
            first_run=first_run,
            meshed_params=self._meshed_params,
            source=self._mesh_source,
            parent=self,
        )
        # Double-clicking a group in the panel opens its parts in a window of
        # their own, so the row itself can stay "name + count + kind".
        dlg.group_activated.connect(self._open_mesh_group_window)
        # Shown, not exec()'d: the panel is non-modal, so the group windows it
        # opens stay usable while it is up -- and so is the run it starts, which
        # is reported back into it (it is the progress window now).
        dlg.mesh_requested.connect(lambda d=dlg: self._on_mesh_scope_accepted(d))
        # The grouping the rows show is one background job's answer, and this is
        # the second opinion -- the same run the import starts, on demand.
        dlg.recheck_contacts_requested.connect(self._on_recheck_contacts)
        # The panel applies that answer itself when the user takes the offer in
        # its notice line; the line it leaves in the log is the host's business.
        dlg.regroup_accepted.connect(self._log_scope_regrouped)
        dlg.view_mesh_requested.connect(self._slot_view_mesh)
        dlg.rollback_requested.connect(self._rollback_mesh)
        dlg.rejected.connect(self._on_mesh_scope_rejected)
        dlg.finished.connect(lambda _r, d=dlg: self._release_mesh_dialog(d))
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._open_mesh_dialog = dlg
        dlg.set_view_mesh_available(bool(self._meshed_nodes))
        # Which of the two meanings of "every solid is its own unit" the rows
        # have: the analysis cleared them, or it has not answered yet.
        self._push_contact_state()
        dlg.show()

    def _release_mesh_dialog(self, dlg):
        """Forget the panel once it is closed, so the next Mesh press opens one."""
        if self._open_mesh_dialog is dlg:
            self._open_mesh_dialog = None

    def _mesh_panel(self):
        """The open scope panel, or None.

        It is the progress window now, so every report from a running session
        goes through here -- and the user may close it mid-run, in which case the
        status bar cell and the toolbar carry the session alone.
        """
        return self._open_mesh_dialog

    def _current_mesh_groups(self, solid_nodes) -> list:
        """The re-mesh units of the model as it is now, in tree order.

        Group by *index*, never by name: the reader names solids after their
        parent, so a nested assembly can repeat a name (as1-oc-214.stp yields
        18 solids / 4 distinct names). A name-keyed merge then fuses parts that
        never touch -- e.g. it collapses the whole model into 4 groups. The
        indices are only trustworthy while the tree is the one that was
        analysed, so fall back to the names when the analysis is gone.
        """
        analysis = None if (self._analysis is None or self._analysis.failed) \
            else self._analysis
        return build_groups(
            solid_nodes,
            () if analysis is None else analysis.contact_pairs,
            index_pairs=() if analysis is None else analysis.contact_indices,
        )

    def _on_mesh_scope_rejected(self):
        """The panel was closed.

        Closing it is not cancelling: the panel is the progress window, so a
        session started from it runs on without its window (the toolbar's Cancel
        stops it). Said out loud, so a closed panel is not read as a dead run.
        """
        self._logger.log_system(
            "Mesh scope closed." if self._mesh_current_group is None else
            "Mesh scope closed: the run continues, Cancel in the toolbar stops "
            "it.")

    def _discard_mesh_scope_panel(self):
        """Close the panel when the model changes under it.

        Non-modal means an import or a delete can land while the panel is up.
        Its rows are the groups of the model that was analysed, so they are
        dropped rather than re-filled: the next Mesh press builds them from the
        tree as it is then.
        """
        dlg = self._open_mesh_dialog
        if dlg is not None and dlg.isVisible():
            dlg.close()
        # The group window shows shapes of the same model, and the OCC objects
        # behind them go away with it (see _clear_scene).
        group_dlg = self._group_dialog
        if group_dlg is not None and group_dlg.isVisible():
            group_dlg.close()

    def _on_mesh_scope_accepted(self, dlg):
        """The panel's Mesh button: run one session, one job per selected group.

        The panel is not closed by it -- it stays up as the progress window, and
        is told what the run produced when the run ends (see _finish_mesh_session).
        """
        jobs = dlg.plan()
        if not jobs:
            if dlg.selected_indices():
                self._logger.log_system(
                    "Nothing to re-mesh: every ticked group already has a mesh "
                    "made with these values.")
            else:
                self._logger.log_system("Nothing to mesh: no group selected.")
            return
        # Ticked groups with nothing to redo keep their mesh. Said out loud, so
        # the run cannot look like it quietly skipped part of the selection.
        for g in dlg.reused_groups():
            self._logger.log_system(
                f"  {g.label}: kept, its values did not change "
                f"({g.n_parts} part(s)).")

        # Keep the choice -- the shared values go back into the panel next time,
        # so that re-opening it continues from what is in the model instead of
        # from the defaults.
        self._last_mesh_params = dlg.shared_params()
        self._mesh_scope_text = dlg.get_descriptive_summary()
        self._logger.log_system(self._mesh_scope_text)
        for g, p in jobs:
            self._logger.log_system(
                f"  {g.label} ({g.mode_label}, {g.n_parts} part(s)): "
                f"algorithm={p['algorithm']}, elem_factor={p['elem_factor']:.2f}, "
                f"min/max={p['mesh_min_factor']:.2f}/{p['mesh_max_factor']:.2f}, "
                f"smoothing={p['smoothing']}, order={p['element_order']}, "
                f"mode={resolved_mode(g, p)}")

        # No more "clean the work area": the previous run's mesh has to survive
        # this one, because a failed re-mesh must not cost the user the mesh
        # they already had (doc/remesh_ui_mockup.html §5). This run gets its own
        # sub-directory; nothing below _mesh_work_dir is deleted here.
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

        # ---- Open the session: one job per group, run back to back ----
        self._mesh_jobs = list(jobs)
        self._mesh_session_meshed = {}
        # The mesh of everything not in this session survives it untouched; that
        # is the whole point of a scoped re-mesh, so it is tracked apart from
        # what this session produces rather than overwritten.
        selected_ids = {eid for g, _ in jobs for eid in g.entry_ids}
        self._mesh_kept = {eid: path for eid, path in self._meshed_nodes.items()
                           if eid not in selected_ids}
        # What the model looks like right now -- the mesh in use, the values
        # behind it and the verdict that described it. Kept whole so that "Roll
        # back to #N" has something exact to put back rather than a guess.
        self._mesh_prev_nodes = dict(self._meshed_nodes)
        self._mesh_prev_params = dict(self._meshed_params)
        self._mesh_prev_source = dict(self._mesh_source)
        self._mesh_prev_outcome = self._mesh_outcome
        self._mesh_prev_run = dict(self._last_mesh_run) if self._last_mesh_run \
            else None
        self._mesh_prev_run_no = self._mesh_run_no
        self._mesh_prev_run_dir = self._mesh_run_dir
        self._mesh_start_time = time.time()
        self._mesh_job_elapsed = {}
        self._mesh_session_outcomes = []
        self._mesh_session_failed = 0
        self._mesh_cancelled = False
        self._mesh_outcome = None
        self._mesh_run_no += 1
        # This run's own directory. Nothing outside it is written, so the
        # previous run's VTK files stay valid whatever happens below -- which is
        # what makes both rollback and a post-mortem possible.
        self._mesh_run_dir = os.path.join(self._mesh_work_dir,
                                          f"run_{self._mesh_run_no:03d}")
        os.makedirs(self._mesh_run_dir, exist_ok=True)

        dlg.start_run(self._mesh_run_no, self._mesh_scope_text)

        # While a session is in flight the toolbar offers Cancel, and only
        # Cancel: starting a second session on top of the first would make the
        # two write into the same work directory.
        self._toolbar.set_running(True)
        self._toolbar.set_mesh_state("cancel")
        n_jobs = len(self._mesh_jobs)
        self._set_mesh_status(f"Fragment 1/{n_jobs} · 0%")
        self._start_next_mesh_job()

    def _start_next_mesh_job(self):
        """Start the next group of the session, or close the session out."""
        if not self._mesh_jobs:
            self._finish_mesh_session()
            return

        group, params = self._mesh_jobs.pop(0)
        nodes = [n for n in self._geo_agent.get_all_solid_nodes()
                 if n.entry_id in set(group.entry_ids)]
        if not nodes:
            self._logger.log_system(
                f"  {group.label}: skipped, the parts are no longer in the tree.",
                level=LogLevel.WARNING)
            self._start_next_mesh_job()
            return

        self._mesh_job_started = time.time()
        self._logger.log_system(
            f"Meshing {group.label}: {group.n_parts} part(s) in "
            f"{resolved_mode(group, params)} mode…")
        # The bar keeps the session's percentage while the line names the job: a
        # job is not a run, and dropping the bar back to zero for each group
        # would read as three runs in a row.
        done = len(self._mesh_job_elapsed)
        total = done + len(self._mesh_jobs) + 1
        panel = self._mesh_panel()
        if panel is not None:
            panel.set_progress(
                int(done * 100 / total),
                f"{group.label} ({done + 1}/{total}) · starting…")

        self._mesh_runner = MeshRunner(
            nodes=nodes,
            work_dir=os.path.join(self._mesh_run_dir, f"group_{group.index}"),
            algorithm=MeshParamsWidget.ALGORITHMS.get(
                params["algorithm"], MeshParamsWidget.ALGORITHMS["Frontal-Delaunay"]),
            elem_factor=params["elem_factor"],
            mesh_min_factor=params["mesh_min_factor"],
            mesh_max_factor=params["mesh_max_factor"],
            smoothing=params["smoothing"],
            order=params["element_order"],
            mode=resolved_mode(group, params),
            analysis=self._analysis,
        )
        # The runner reports what it is working on, so the per-job label and the
        # values it was handed are known when the results come back.
        self._mesh_current_group = group
        self._mesh_current_params = dict(params)

        self._mesh_runner.progress_updated.connect(self._on_mesh_progress)
        self._mesh_runner.heartbeat.connect(self._on_mesh_heartbeat)
        self._mesh_runner.log_emitted.connect(self._on_mesh_log)
        self._mesh_runner.finished_with_result.connect(self._on_mesh_finished)
        self._mesh_runner.stages_defined.connect(self._on_mesh_stages)
        self._mesh_runner.stage_changed.connect(self._on_mesh_stage_changed)
        self._mesh_runner.start()

    def _on_mesh_cancel(self):
        """Cancel means the whole session: the jobs are one accepted decision."""
        self._mesh_cancelled = True
        if self._mesh_jobs:
            self._logger.log_system(
                f"{len(self._mesh_jobs)} pending group(s) dropped.",
                level=LogLevel.WARNING)
            self._mesh_jobs = []
        if self._mesh_runner is not None:
            self._mesh_runner.cancel()
            self._logger.log_system("Cancelling meshing…",
                                    level=LogLevel.WARNING)
            panel = self._mesh_panel()
            if panel is not None:
                panel.set_status("Cancelling… terminating the gmsh job.")

    def _on_mesh_stages(self, labels: list):
        panel = self._mesh_panel()
        if panel is not None:
            panel.set_stages(labels)

    def _on_mesh_stage_changed(self, index: int, message: str):
        panel = self._mesh_panel()
        if panel is not None:
            panel.set_stage(index, message)

    def _slot_view_mesh(self):
        """Open a new mesh preview window each time (allows side-by-side
        comparison of different mesh parameter sets)."""
        if not self._meshed_nodes:
            self._logger.log_system("No mesh data to view. Run meshing first.")
            QMessageBox.information(self, "No Mesh",
                                    "Generate a mesh before viewing.")
            return

        scope = self._view_mesh_scope()
        if not scope:
            self._logger.log_system(
                "Nothing to view: none of the ticked units has a mesh yet.")
            QMessageBox.information(
                self, "Nothing to View",
                "None of the ticked units has a mesh yet. Tick a meshed unit, "
                "or run the mesh first.")
            return

        # Parented to this window on purpose: the preview is a child window, so
        # it goes away with its host -- and it is not a primary window, so it
        # cannot keep the application alive once the host is closed.
        viewer = MeshViewer(self)
        viewer.load_mesh(scope,
                         mesh_params=self._view_mesh_params(),
                         title=self._mesh_viewer_title(),
                         part_rows=self._mesh_part_rows(scope))
        viewer.show()
        # Keep a reference so Python GC won't destroy the C++ QVTKRenderWindowInteractor
        # while Qt is still delivering mouse events to it.
        self._mesh_viewers.append(viewer)
        viewer.finished.connect(
            lambda result, v=viewer: self._mesh_viewers.remove(v))
        self._logger.log_system(
            f"Mesh preview opened: {len(scope)} meshed part(s)."
        )

    def _view_mesh_scope(self) -> dict:
        """The meshed parts to show: the panel's ticked units, when it is open.

        The ticks are what the panel works on -- what Mesh would run, what the
        parameter block edits, what the rows describe -- so they are what the
        preview draws as well: ticking three solids to look at those three is
        one gesture rather than a selection plus a separate filter. With no
        panel open there is no selection on screen, and the preview is what it
        always was: everything that has a mesh.
        """
        panel = self._mesh_panel()
        if panel is None:
            return dict(self._meshed_nodes)
        wanted = set(panel.selected_entry_ids())
        return {eid: p for eid, p in self._meshed_nodes.items()
                if eid in wanted}

    def _view_mesh_params(self) -> dict:
        """The parameter overlay for the preview: the values last used.

        Only the fallback; the preview reads the per-part report below, because
        the parts on screen were not necessarily all meshed with these values.
        """
        return dict(self._last_mesh_params)

    def _mesh_part_rows(self, meshed_nodes: Optional[dict] = None) -> list:
        """One row per meshed part on screen: its unit and the values its mesh
        was made with. This is what the preview's table and CSV export are made
        of, so it lists the parts being shown and no others."""
        nodes = self._geo_agent.get_all_solid_nodes()
        return part_param_rows(
            self._meshed_nodes if meshed_nodes is None else meshed_nodes,
            self._meshed_params,
            self._current_mesh_groups(nodes),
            {n.entry_id: (n.name or n.entry_id) for n in nodes},
            self._last_mesh_params,
            source=self._mesh_source)

    def _mesh_viewer_title(self) -> str:
        """`Mesh Preview #2 · Frontal-Delaunay · elem 0.50 · Conformal`.

        A preview window is opened *per view* so that two runs can be compared
        side by side -- but every window said "Mesh Preview", so after three
        runs the comparison the window exists for was impossible. The run
        number gives the history, the parameters the difference and the verdict
        the conclusion (doc/remesh_ui_mockup.html §6).
        """
        run = self._last_mesh_run or {}
        run_no = run.get("run_no")
        bits = [f"Mesh Preview #{run_no}" if run_no else "Mesh Preview"]
        algo = self._last_mesh_params.get("algorithm")
        if algo:
            bits.append(str(algo))
        elem = self._last_mesh_params.get("elem_factor")
        if isinstance(elem, (int, float)):
            bits.append(f"elem {float(elem):.2f}")
        kind_text = run.get("kind_text")
        if kind_text:
            bits.append(str(kind_text))
        return " · ".join(bits)

    def _open_mesh_group_window(self, group):
        """Show one mesh group's parts on a screen of their own.

        The panel lists groups, not parts, so this is how the user checks what
        "Group A · 3 part(s)" actually is before re-meshing it. Their own window
        rather than a highlight in the 3D view: the group is drawn there among
        everything else, and the parts that are not in question are usually the
        ones in front of it.
        """
        parts = []
        for eid in group.entry_ids:
            node = self._geo_agent.convert_entry_id_to_node(eid)
            if node is None or node.shape is None or node.shape.IsNull():
                continue
            parts.append(node)
        if not parts:
            self._logger.log_system(
                f"{group.label}: no 3D shape to show.")
            return

        open_dlg = self._group_dialog
        if open_dlg is not None and open_dlg.isVisible():
            if open_dlg.same_group(group):
                open_dlg.raise_()
                open_dlg.activateWindow()
                return
            open_dlg.close()

        dlg = MeshGroupDialog(group, parts,
                              meshed_ids=set(self._meshed_nodes),
                              parent=self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.finished.connect(lambda _r, d=dlg: self._release_group_dialog(d))
        self._group_dialog = dlg
        dlg.show()
        self._logger.log_system(
            f"{group.label} opened: " + ", ".join(
                n.name or n.entry_id for n in parts))

    def _release_group_dialog(self, dlg):
        """Forget the group window once it is closed."""
        if self._group_dialog is dlg:
            self._group_dialog = None

    # ---- Mesh runner callbacks ----

    def _on_mesh_progress(self, value: int, message: str):
        """Update the panel and the status bar from the mesh runner.

        The message itself goes to the panel and the log; the status bar cell
        stays short -- group count and overall percentage -- because it has to
        read at a glance from the far side of the screen. The panel gets the
        session's percentage too, not the job's: it is watched, and 0..100 three
        times over is not a progress bar.

        The percentage is carried by the cell's own text: the bar next to it
        belongs to the contact analysis, and this session is not that analysis.
        """
        idx, total, overall = self._mesh_session_progress(value)
        panel = self._mesh_panel()
        if panel is not None:
            panel.set_progress(overall, message)
        self._set_mesh_status(f"Fragment {idx}/{total} · {overall}%")

    def _on_mesh_log(self, line: str):
        """Forward a gmsh log line to the system log, and nowhere else."""
        self._logger.log_system(line)

    def _on_mesh_heartbeat(self, elapsed: float, idle: float):
        """Pass the runner's liveness on to the panel.

        A single gmsh job freezes both the bar and the log, which is what a
        wedged process looks like too; elapsed and idle tell the two apart.
        """
        panel = self._mesh_panel()
        if panel is not None:
            panel.set_heartbeat(elapsed, idle)

    def _on_mesh_finished(self, success: bool, mesh_paths: dict, message: str):
        """One job is done: fold it in, then start the next one.

        Not "the meshing is over": a session is one job per group, and the
        verdict for the whole session is only assembled once the queue is empty
        (_finish_mesh_session) -- a group finishing conformal says nothing about
        the groups still to come.
        """
        job_elapsed = time.time() - self._mesh_job_started
        group = self._mesh_current_group

        # Take the verdict off the runner before dropping the reference
        outcome = None
        if self._mesh_runner is not None:
            outcome = self._mesh_runner.outcome
            outcome.elapsed = outcome.elapsed or job_elapsed
        self._mesh_runner = None

        who = group.label if group is not None else "Group"
        if group is not None:
            self._mesh_job_elapsed[group.index] = job_elapsed
        self._mesh_session_outcomes.append(outcome or MeshOutcome())
        if not success:
            self._mesh_session_failed += 1

        if success:
            self._mesh_session_meshed.update(mesh_paths)
            if group is not None:
                # Recorded per group, not per run: these are the values that made
                # this group's mesh, which is what the panel compares against next
                # time to decide whether the group has to run again at all.
                key = group_key(group.entry_ids)
                self._meshed_params[key] = dict(self._mesh_current_params)
                # The same for the provenance: these parts now hold *this* job's
                # mesh, whatever they held before it -- an assembly run overwrites
                # the per-solid files of its members, so their earlier records
                # have to stop pointing anywhere.
                for eid in mesh_paths:
                    if eid in group.entry_ids:
                        self._mesh_source[eid] = key
            self._logger.log_system(
                f"{who}: meshed ({job_elapsed:.1f}s): {message}")
        else:
            if group is not None:
                # A failed group falls back to the mesh it already had. This is
                # the whole payoff of the versioned work area: the old files were
                # never deleted, so the failure costs the run and not the mesh --
                # export and preview keep working, and nothing has to be redone
                # (doc/remesh_ui_mockup.html §5). Only a group that had no mesh
                # before is left without one.
                restored = {eid: self._mesh_prev_nodes[eid]
                            for eid in group.entry_ids
                            if eid in self._mesh_prev_nodes}
                self._mesh_kept.update(restored)
                # The files in use are the ones they had, so the provenance goes
                # back with them: a failed job leaves the model exactly as it
                # found it, records and all.
                for eid in group.entry_ids:
                    if eid in restored and eid in self._mesh_prev_source:
                        self._mesh_source[eid] = self._mesh_prev_source[eid]
                    else:
                        self._mesh_source.pop(eid, None)
                key = group_key(group.entry_ids)
                if restored and key in self._mesh_prev_params:
                    # Put the values back too: the mesh in use is still the old
                    # one, so the panel has to compare the next run against the
                    # numbers that actually made it.
                    self._meshed_params[key] = dict(self._mesh_prev_params[key])
                else:
                    self._meshed_params.pop(key, None)
            self._logger.log_system(
                f"{who}: finished with issues ({job_elapsed:.1f}s): {message}",
                level=LogLevel.WARNING)
            # The remaining groups are independent of this one, so a failure does
            # not abort the session: whatever did mesh stays usable, and the
            # export gate reports exactly which parts are still missing.

        # Publish what exists so far, so a long session can be previewed while it
        # is still running (the parts kept from earlier runs are in _mesh_kept).
        self._meshed_nodes = dict(self._mesh_kept)
        self._meshed_nodes.update(self._mesh_session_meshed)
        self._mesh_current_group = None
        self._start_next_mesh_job()

    def _combine_outcomes(self, elapsed: float) -> MeshOutcome:
        """One verdict for a session made of several independent jobs.

        The worst job decides: one group left with coincident facets makes the
        model non-conformal whatever the others achieved. UNKNOWN propagates
        instead of being rounded off, so a job that produced no verdict at all
        cannot end up looking like a success.
        """
        outs = list(self._mesh_session_outcomes)
        combined = MeshOutcome()
        combined.kind = UNKNOWN
        combined.n_solids = len(self._meshed_nodes)
        combined.n_meshed = len(self._mesh_session_meshed)
        combined.overlap_facets = sum(o.overlap_facets for o in outs)
        combined.open_edges = sum(o.open_edges for o in outs)
        combined.bad_solids = [b for o in outs for b in o.bad_solids]
        combined.notes = [n for o in outs for n in o.notes]
        combined.elapsed = elapsed

        # request/actual mode are per job and a session can mix them, so the pair
        # is only carried over when it stays meaningful -- and it is carried over
        # for a *degraded* job first, because that is the one worth reporting.
        degraded = [o for o in outs if o.degraded]
        if degraded:
            combined.requested_mode = degraded[0].requested_mode
            combined.actual_mode = degraded[0].actual_mode
            for i, o in enumerate(outs):
                if o.degraded:
                    combined.notes.append(
                        f"job {i + 1}: {o.requested_mode} degraded to "
                        f"{o.actual_mode}")
        else:
            modes = {o.actual_mode for o in outs}
            one = modes.pop() if len(modes) == 1 else "mixed"
            combined.requested_mode = one
            combined.actual_mode = one

        if self._mesh_session_failed or not outs:
            combined.kind = NON_CONFORMAL
            combined.notes.append(
                f"{self._mesh_session_failed} of {len(outs) + self._mesh_session_failed} "
                f"job(s) failed" if outs or self._mesh_session_failed
                else "no job ran")
        elif NON_CONFORMAL in {o.kind for o in outs}:
            combined.kind = NON_CONFORMAL
        elif PARTIAL in {o.kind for o in outs}:
            combined.kind = PARTIAL
        elif UNKNOWN in {o.kind for o in outs}:
            combined.kind = UNKNOWN
        else:
            combined.kind = CONFORMAL
        return combined

    def _finish_mesh_session(self):
        """Every job has finished (or been cancelled): publish one verdict."""
        self._meshed_nodes = dict(self._mesh_kept)
        self._meshed_nodes.update(self._mesh_session_meshed)
        elapsed = time.time() - self._mesh_start_time

        outcome = self._combine_outcomes(elapsed)
        success = not self._mesh_session_failed and bool(self._mesh_session_meshed)
        self._mesh_outcome = outcome

        # Everything the panel needs to describe this run as the "Last run" row
        # next time: the full parameter set as well, so the panel can diff the
        # two runs without a second lookup.
        self._last_mesh_run = dict(self._last_mesh_params)
        self._last_mesh_run.update({
            "run_no": self._mesh_run_no,
            "elapsed": elapsed,
            "n_solids": len(self._meshed_nodes),
            "kind": outcome.kind,
            "kind_text": state_text(outcome.kind),
            "scope": self._mesh_scope_text,
        })

        self._logger.log_system(
            f"{self._mesh_scope_text} — {outcome.headline} in {elapsed:.1f}s")
        detail = f"{outcome.n_meshed} solids"
        if outcome.kind == NON_CONFORMAL:
            detail += f" · coincident facets {outcome.overlap_facets}"
        self._set_conformity(outcome.kind, detail)
        self._logger.log_system(
            f"Conformity: {outcome.headline}"
            + (" (" + "; ".join(outcome.notes) + ")" if outcome.notes else ""))

        # The session is over. The cell keeps the run on display rather than
        # dropping back to an empty slot: a running session is capped at 99, so
        # 100% is the one reading that can only mean "this is finished", and a
        # user who looks at the status bar after a run has to be able to see that
        # something happened -- an empty cell says the opposite. A cancelled
        # session is the exception: it did not finish, so it has no reading to
        # leave behind.
        if self._mesh_cancelled:
            self._set_mesh_status()
        else:
            n_jobs = len(self._mesh_session_outcomes) or 1
            self._set_mesh_status(f"Fragment {n_jobs}/{n_jobs} · 100%")

        panel = self._mesh_panel()
        if panel is not None:
            # The panel is where this run was started from and it is still open,
            # so it has to be told twice over: where the run got to (the bar and
            # its last line), and what it left behind (adopt_run -- the next
            # press of Mesh plans the *next* run, and the changed-field markers
            # compare against the values the model now holds).
            panel.set_view_mesh_available(bool(self._meshed_nodes))
            # The same reading the status bar cell was just given, including the
            # cancelled case: one bar for one run, whichever of the two the user
            # happens to be looking at.
            panel.finish_run(
                f"#{self._mesh_run_no} · {outcome.headline} · "
                f"{outcome.n_meshed} solid(s) · {elapsed:.1f}s"
                + (" · cancelled" if self._mesh_cancelled else ""),
                not self._mesh_cancelled)
            panel.adopt_run(self._meshed_params, self._mesh_source)
            self._offer_rollback(success)

        # Run directories that nothing points at any more go now that the
        # verdict is known; the current and previous runs are never touched.
        self._prune_mesh_runs()

        # A mesh exists now, so the toolbar button becomes Re-mesh, and the
        # buttons set_running() disabled come back.
        self._toolbar.set_mesh_state("remesh" if self._meshed_nodes else "mesh")
        self._toolbar.set_running(False)
        self._mesh_current_group = None

    def _offer_rollback(self, success: bool) -> None:
        """After a failed run, say the previous mesh survived -- and offer it back.

        Before the work area was versioned a failed re-mesh left _meshed_nodes
        pointing at deleted files: export was gated off and preview came up
        empty, with nothing to go back to. The failed groups now fall back to
        the mesh they had, so the run costs nothing; what is left to decide is
        whether the groups that *did* mesh should be kept, and that is the one
        thing the button answers. It is only offered when the run actually
        changed what is in use -- otherwise it would be a button that does
        nothing.
        """
        dlg = self._mesh_panel()
        if success or not self._mesh_prev_nodes or not self._mesh_prev_run_no:
            return
        if self._meshed_nodes == self._mesh_prev_nodes:
            # Every group either failed or was untouched, so #N is still exactly
            # what is in use: nothing to roll back to.
            self._logger.log_system(
                f"  in use: the #{self._mesh_prev_run_no} mesh, unchanged "
                f"({len(self._mesh_prev_nodes)} solid(s)) — preview and export "
                f"are unaffected.")
            return
        self._logger.log_system(
            f"  in use: #{self._mesh_prev_run_no} for the failed group(s), "
            f"this run for the rest.")
        if dlg is not None:
            dlg.show_rollback(self._mesh_prev_run_no)

    def _rollback_mesh(self):
        """`Roll back to #N`: put the previous run's mesh back in use.

        Restores the whole picture, not just the paths: the per-group values,
        the verdict that gates export, and the "last run" row the scope panel
        diffs against. Anything less would leave the model looking right while
        behaving as if the failed run had won.
        """
        run_no = self._mesh_prev_run_no
        if not run_no or not self._mesh_prev_nodes:
            return

        # Only the files that are still there: a hand-cleaned work area must
        # not be mistaken for a rollback that worked.
        live = {eid: p for eid, p in self._mesh_prev_nodes.items()
                if os.path.isfile(p)}
        if not live:
            self._logger.log_system(
                f"Roll back to #{run_no} failed: its mesh files are gone.",
                level=LogLevel.ERROR)
            if self._mesh_panel() is not None:
                self._mesh_panel().hide_rollback()
            return

        self._meshed_nodes = live
        self._meshed_params = dict(self._mesh_prev_params)
        # The provenance of that run, not this one's: which job wrote each file
        # is part of what "put the previous run back" means.
        self._mesh_source = dict(self._mesh_prev_source)
        self._mesh_outcome = self._mesh_prev_outcome
        self._last_mesh_run = dict(self._mesh_prev_run) if self._mesh_prev_run \
            else None
        # The values go back to that run's as well, not only the meshes. The panel
        # opens on _last_mesh_params, so leaving the failed run's numbers there
        # would open it one mode and one set of numbers away from the meshes that
        # are actually in use -- and every group whose record says otherwise would
        # be reported as needing a re-mesh it does not need. The run record keeps
        # them under their own keys, beside the run's own (run_no, elapsed, ...).
        _prev = self._mesh_prev_run or {}
        self._last_mesh_params = dict(
            DEFAULT_PARAMS,
            **{k: v for k, v in _prev.items() if k in DEFAULT_PARAMS})
        # The session's own bookkeeping is dead now: the model is back to the
        # earlier run, and a late job callback would otherwise republish it.
        self._mesh_kept = dict(live)
        self._mesh_session_meshed = {}
        self._mesh_current_group = None

        kind = self._mesh_outcome.kind if self._mesh_outcome else UNKNOWN
        detail = f"{len(live)} solids"
        if self._mesh_outcome is not None and kind == NON_CONFORMAL:
            detail += f" · coincident facets {self._mesh_outcome.overlap_facets}"
        self._set_conformity(kind, detail)
        self._logger.log_system(
            f"Rolled back to run #{run_no}: {len(live)} solid(s) in use again.")

        panel = self._mesh_panel()
        if panel is not None:
            # The panel outlives the run, so the rollback has to reach it too:
            # the values it plans against are the previous run's again, and that
            # is the mesh its View Mesh button should open.
            panel.hide_rollback()
            panel.set_view_mesh_available(True)
            panel.adopt_run(self._meshed_params, self._mesh_source)
        self._toolbar.set_mesh_state("remesh" if live else "mesh")

    # ---- Mesh work area (versioned per run) ----

    def _prune_mesh_runs(self) -> None:
        """Delete run directories that nothing points at any more.

        The work area used to be wiped before every run; it now grows by one
        directory per run, so the old sledgehammer has to become a rule. A run
        directory goes only when no live mesh path lives inside it, and never
        the run that just ended (its log is still worth reading after a failure)
        nor the one before it (rollback needs it).
        """
        try:
            names = os.listdir(self._mesh_work_dir)
        except OSError:
            return

        root = os.path.abspath(self._mesh_work_dir)
        keep = {os.path.abspath(d) for d in
                (self._mesh_run_dir, self._mesh_prev_run_dir) if d}
        for path in self._meshed_nodes.values():
            keep_path = os.path.abspath(str(path)) if path else ""
            if not keep_path.startswith(root + os.sep):
                continue          # not ours (an old tree, a hand-picked file)
            # Walk up to the run directory, whatever depth the runner nests at.
            p = os.path.dirname(keep_path)
            while p != root and os.path.dirname(p) != root:
                p = os.path.dirname(p)
            if p != root:
                keep.add(p)

        for name in names:
            if not name.startswith("run_"):
                continue          # anything a human put there is left alone
            path = os.path.join(self._mesh_work_dir, name)
            if not os.path.isdir(path) or os.path.abspath(path) in keep:
                continue
            shutil.rmtree(path, ignore_errors=True)

    def _forget_mesh_runs(self) -> None:
        """Drop the whole work area and its history.

        Only safe when no mesh is in use -- a new CAD import is the one place
        that is true, and it is exactly where a stale run directory would
        otherwise offer to roll back to a model that is no longer loaded.
        """
        self._mesh_run_dir = ""
        self._mesh_prev_run_dir = ""
        self._mesh_prev_nodes = {}
        self._mesh_prev_params = {}
        self._mesh_prev_outcome = None
        self._mesh_prev_run = None
        self._mesh_prev_run_no = 0
        shutil.rmtree(self._mesh_work_dir, ignore_errors=True)

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
            # An import can add local materials; repopulate the tree node.
            self._assign_material_dlg.local_materials_changed.connect(
                self._refresh_local_material_tree)
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
        # Drop a still-running contact analysis worker before we go away
        if self._analysis_runner is not None:
            self._analysis_runner.cancel()
        # Close the mesh previews explicitly instead of letting them be hidden
        # with the window: their closeEvent is what finalizes the VTK render
        # window, and that has to run while the native handles are still alive.
        # Iterate a copy -- closing emits finished, which drops it from the list.
        for viewer in list(self._mesh_viewers):
            viewer.close()
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
