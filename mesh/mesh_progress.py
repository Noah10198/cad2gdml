"""
MeshProgressDialog - Non-modal progress dialog for mesh generation.

Change (see doc/assembly_fragment_ui.md §9.6 figure 3):

  1. It used to be a single status line refreshed **in place** via append_log()
     -- the user could not watch the process and had nothing copyable to hand
     over when something went wrong. It is now a read-only log view where every
     line stays.
  2. New stage indicator (contact analysis / boolean fragment / reassignment),
     because the three assembly stages fail in completely different ways and the
     user needs to know which one is stuck.
  3. New "Cancel" -- a 3 minute x N solids timeout is not enough for assembly,
     and without cancel the only option is killing the process.
  4. Each run closes with one line in the log -- `→ #N · verdict · facets ·
     duration`, or `✕` when it failed. No emoji and no colour of its own: the
     state is carried by the words, as in the status bar.

Re-mesh (see doc/remesh_ui_mockup.html §4, where a second run is the whole
point -- the first run was always fine):

  5. The log only ever grows. `reset()` used to call `clear()`, so the second run
     erased the first one -- parameters, duration and verdict -- and "did my
     change make it better?" became unanswerable. Each run now starts with one
     separator line naming what changed since the previous run, and the runs are
     compared inside the one log instead of side by side.
  6. `🔁 Re-generate` repeats the run without going through the modal parameter
     dialog again, and `Roll back` re-points the model at an older run after a
     failed one -- made possible by the versioned work directories.

Dropped: the "last #N: ..." label and the verdict banner that sat under the log.
Both restated lines the log already holds verbatim -- `[STATE] ...` plus its
indented detail lines, then the `→ #N` summary -- and they squeezed the one pane
worth keeping. The dialog is 1.5x its old size, which is where that space went.
"""

from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QProgressBar,
    QLabel, QPushButton, QWidget, QPlainTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.conformity import MeshOutcome


# The parameters worth naming in a run header, in the order a user would read
# them. Keys match the dict built by MainWindow._mesh_params_dict().
_DIFF_PARAMS = [
    ("elem", "elem"),
    ("algorithm", "algo"),
    ("min_factor", "min"),
    ("max_factor", "max"),
    ("smoothing", "smooth"),
    ("order", "order"),
]


def _num(value: Any) -> str:
    """1.0 -> '1.00', 'Frontal-Delaunay' -> unchanged."""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _fmt_elapsed(seconds: float) -> str:
    """4 min 02 s -- the same shape the dialog has always used."""
    total = int(round(seconds))
    return f"{total // 60} min {total % 60:02d} s"


def _run_label(run_no: int, params: Optional[Dict[str, Any]],
               prev_params: Optional[Dict[str, Any]]) -> str:
    """`#2 · elem 1.00 → 0.50` -- only what changed, or the full set on run #1.

    Diffing is the point: the log keeps every run, so the header has to say why
    this run is not the previous one.
    """
    if not params:
        return f"#{run_no}"
    if prev_params:
        changes = []
        for key, name in _DIFF_PARAMS:
            before, after = prev_params.get(key), params.get(key)
            if before is None or after is None or before == after:
                continue
            changes.append(f"{name} {_num(before)} → {_num(after)}")
        if changes:
            return f"#{run_no} · " + " · ".join(changes)
    bits = [f"#{run_no}"]
    if params.get("algorithm"):
        bits.append(str(params["algorithm"]))
    if params.get("elem") is not None:
        bits.append(f"elem {_num(params['elem'])}")
    return " · ".join(bits)


class MeshProgressDialog(QDialog):
    """Non-blocking progress dialog for GMSH mesh generation."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Mesh Generation Progress")
        # 1.5x the old 450 px minimum: the log is the only content left, so a
        # GMSH line has to fit without wrapping.
        self.setMinimumSize(675, 560)
        self.resize(900, 700)
        # CustomizeWindowHint drops every button a hint does not name, so the X
        # has to be asked for by name. It closes exactly like the bottom Close
        # button (the dialog is a persistent session, hidden not destroyed, and
        # shown again by the next run) -- without it the only way out is a button
        # that a long log can push out of sight.
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(False)  # Non-blocking

        self._finished = False
        self._view_mesh_btn: Optional[QPushButton] = None
        self._stage_labels = []

        # History: the panel is a session, not a single run.
        self._run_no = 0
        self._run_failed = False
        self._rollback_run_no: Optional[int] = None
        self._last_params: Optional[Dict[str, Any]] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ---- Stage indicator: only assembly mode has multiple stages ----
        self._stage_row = QWidget()
        self._stage_layout = QHBoxLayout(self._stage_row)
        self._stage_layout.setContentsMargins(0, 0, 0, 0)
        self._stage_layout.setSpacing(16)
        self._stage_layout.addStretch()
        self._stage_row.setVisible(False)
        layout.addWidget(self._stage_row)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # Status label
        self._status_label = QLabel("Initializing...")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # ---- Log view: no more in-place refresh ----
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMinimumHeight(180)
        self._log_view.setMaximumBlockCount(2000)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        self._log_view.setFont(mono)
        # No stylesheet of its own: the view inherits the dialog palette, so it
        # flips with the theme exactly like the GmshDialog summary box. The old
        # hard-coded #1e1e2e became a black slab in the (default) light theme.
        layout.addWidget(self._log_view, 1)

        # Bottom row: close + cancel + view mesh buttons
        btn_layout = QHBoxLayout()

        self._view_mesh_btn = QPushButton("View Mesh")
        self._view_mesh_btn.setEnabled(False)
        self._view_mesh_btn.setToolTip("Open mesh preview in a separate window")
        btn_layout.addWidget(self._view_mesh_btn)

        # Re-run without the modal dialog. Enabled once a run has ended: while
        # one is in flight this would start a second gmsh into the same tree.
        self._regen_btn = QPushButton("🔁 Re-generate")
        self._regen_btn.setEnabled(False)
        self._regen_btn.setToolTip("Run the mesh again with the current parameters")
        btn_layout.addWidget(self._regen_btn)

        # Only shown after a failed run that left an older mesh in use.
        self._rollback_btn = QPushButton("Roll back")
        self._rollback_btn.setVisible(False)
        self._rollback_btn.setToolTip("Go back to the mesh of the previous run")
        btn_layout.addWidget(self._rollback_btn)

        btn_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setToolTip("Terminate the current gmsh job")
        btn_layout.addWidget(self._cancel_btn)

        self._close_btn = QPushButton("Close")
        btn_layout.addWidget(self._close_btn)

        layout.addLayout(btn_layout)

        # Connect buttons
        self._close_btn.clicked.connect(self.close)

    # ---- Run history ----

    def begin_run(self, run_no: int, params: Optional[Dict[str, Any]] = None,
                  prev_params: Optional[Dict[str, Any]] = None,
                  scope_text: str = "") -> None:
        """Start run #`run_no` **without** erasing the previous ones.

        This replaces the old reset() at mesh-start time: only the live parts of
        the panel (progress, stages, buttons) are cleared, while the log stays --
        it is what a re-mesh is judged against.
        """
        self._run_no = run_no
        self._run_failed = False
        self._last_params = params
        self._progress_bar.setValue(0)
        self._status_label.setText("Initializing...")
        self._finished = False
        self._cancel_btn.setEnabled(True)
        self.hide_rollback()
        self._set_regen_enabled(False)
        self.set_stages([])
        if self._view_mesh_btn:
            self._view_mesh_btn.setEnabled(False)
            self._view_mesh_btn.setStyleSheet("")
        self.append_run_header(run_no, params, prev_params, scope_text)

    def append_run_header(self, run_no: int,
                          params: Optional[Dict[str, Any]] = None,
                          prev_params: Optional[Dict[str, Any]] = None,
                          scope_text: str = "") -> None:
        """One separator line per run; the log itself is never cleared.

        Two shapes, both starting with the run number:
            ──── #2 · elem 1.00 → 0.50 ──────────────────
            ──── re-mesh #2 · scope: A B C (5 parts) · keep: D ────
        """
        if scope_text:
            label = f"re-mesh #{run_no} · {scope_text}"
        else:
            label = _run_label(run_no, params, prev_params)
        self.append_log(f"──── {label} " + "─" * max(4, 56 - len(label)))

    def set_run_title(self, run_no: Optional[int] = None,
                      failed: bool = False) -> None:
        """`Mesh Generation Progress · run #2 [failed]`: after three re-meshes
        three identical window titles cannot be told apart."""
        n = self._run_no if run_no is None else run_no
        title = f"Mesh Generation Progress · run #{n}" if n else \
            "Mesh Generation Progress"
        if failed:
            title += " failed"
        self.setWindowTitle(title)

    # ---- Re-generate / Roll back ----

    def _set_regen_enabled(self, enabled: bool) -> None:
        if self._regen_btn:
            self._regen_btn.setEnabled(enabled)

    def set_regenerate_callback(self, callback) -> None:
        """`🔁 Re-generate`: repeat the run with the parameters already in use."""
        if self._regen_btn:
            try:
                self._regen_btn.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._regen_btn.clicked.connect(callback)

    def set_rollback_callback(self, callback) -> None:
        if self._rollback_btn:
            try:
                self._rollback_btn.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._rollback_btn.clicked.connect(callback)

    def show_rollback(self, run_no: int) -> None:
        """A failed run does not have to mean starting over: if an older mesh is
        still on disk, offer it explicitly instead of leaving the user to guess
        whether the previous result survived."""
        self._rollback_run_no = run_no
        if self._rollback_btn:
            self._rollback_btn.setText(f"Roll back to #{run_no}")
            self._rollback_btn.setVisible(True)

    def hide_rollback(self) -> None:
        self._rollback_run_no = None
        if self._rollback_btn:
            self._rollback_btn.setVisible(False)

    @property
    def rollback_run_no(self) -> Optional[int]:
        return self._rollback_run_no

    def set_view_mesh_available(self, available: bool) -> None:
        """A failed run must not take the previous preview away."""
        if not self._view_mesh_btn:
            return
        self._view_mesh_btn.setEnabled(available)
        if not available:
            self._view_mesh_btn.setStyleSheet("")

    # ---- Stage indicator ----

    def set_stages(self, labels: Sequence[str]):
        """Assembly mode: ["Contact analysis", "Boolean fragment", "Reassign"].

        Per-solid mode passes a single stage, in which case the whole row is
        hidden -- a one-stage "stage indicator" carries no information.
        """
        for lb in self._stage_labels:
            self._stage_layout.removeWidget(lb)
            lb.deleteLater()
        self._stage_labels = []

        if len(labels) <= 1:
            self._stage_row.setVisible(False)
            if labels:
                self._status_label.setText(labels[0])
            return

        for i, name in enumerate(labels):
            # No colour of its own -- see set_stage().
            lb = QLabel(f"○ {name}")
            self._stage_labels.append(lb)
            self._stage_layout.insertWidget(i, lb)
        self._stage_row.setVisible(True)
        self.set_stage(0)

    def set_stage(self, index: int, message: str = ""):
        """Mark stage `index` as in progress and all previous ones as done.

        State is carried by the glyph (● done / in progress, ○ not reached yet)
        and by the weight -- *not* by colour. The labels use the dialog
        foreground, which is black in the (default) light theme; the old pastel
        green on that background could hardly be read.
        """
        for i, lb in enumerate(self._stage_labels):
            name = lb.text()[2:]
            if i < index:
                lb.setText(f"● {name}")
                lb.setStyleSheet("")
            elif i == index:
                lb.setText(f"● {name}")
                lb.setStyleSheet("font-weight: bold;")
            else:
                lb.setText(f"○ {name}")
                lb.setStyleSheet("")
        if message:
            self._status_label.setText(message)

    # ---- Outcome ----

    def set_outcome(self, outcome: MeshOutcome, success: bool):
        """Finalise everything when meshing ends: progress bar, button states, and
        one more line in the (never cleared) log. That closing line is the verdict
        of *this* run; the lines above it are the history of all of them."""
        self._finished = True
        self._run_failed = not success
        self._progress_bar.setValue(100)
        self._cancel_btn.setEnabled(False)

        # The comparison the user came for: one line per run, in order, and the
        # log is never cleared so the previous ones are still above it.
        mark = "→" if success else "✕"
        self.append_log(f"{mark} #{self._run_no} · {outcome.headline} · "
                        f"{outcome.overlap_facets} coincident facets · "
                        f"{_fmt_elapsed(outcome.elapsed)}")
        self.set_run_title(failed=not success)
        self._set_regen_enabled(True)

        if success:
            self._mark_finished()

    # ---- Public API ----

    def set_progress(self, value: int, status: str = ""):
        """Update progress bar and optional status text.

        No longer calls _mark_finished() automatically at 100%: a failed run also
        reports 100%, and the old code would then show "Mesh ready" and light up
        View Mesh. The outcome is now handled solely by set_outcome().
        """
        self._progress_bar.setValue(value)
        if status:
            self._status_label.setText(status)

    def append_log(self, text: str):
        """Append a log line. It used to overwrite the status line, leaving the
        user with nothing."""
        self._log_view.appendPlainText(text)

    def _mark_finished(self):
        """Called when meshing completes successfully."""
        self._finished = True
        if self._view_mesh_btn:
            self._view_mesh_btn.setEnabled(True)
            self._view_mesh_btn.setStyleSheet(
                "QPushButton { background-color: #4CAF50; color: white; "
                "font-weight: bold; padding: 6px 16px; border-radius: 4px; }"
            )

    def set_view_mesh_callback(self, callback):
        """Connect the View Mesh button to a callback function,
        first disconnecting any previous connection to avoid duplicates."""
        if self._view_mesh_btn:
            try:
                self._view_mesh_btn.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._view_mesh_btn.clicked.connect(callback)

    def set_cancel_callback(self, callback):
        """Cancel callback: an assembly job can run for a long time, and without
        cancel the only option is killing the process."""
        if self._cancel_btn:
            try:
                self._cancel_btn.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._cancel_btn.clicked.connect(callback)

    def reset(self, clear_log: bool = False):
        """Clear the live parts of the dialog.

        `clear_log` is off by default: the log is the run history, and wiping it
        at every mesh start threw away the very thing a re-mesh is judged
        against. Only a new CAD import (a different model) passes True.
        """
        self._progress_bar.setValue(0)
        self._status_label.setText("Initializing...")
        self._finished = False
        if clear_log:
            self._log_view.clear()
            self._run_no = 0
            self._last_params = None
        self._cancel_btn.setEnabled(True)
        self.set_stages([])
        if self._view_mesh_btn:
            self._view_mesh_btn.setEnabled(False)
            self._view_mesh_btn.setStyleSheet("")
