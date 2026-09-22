"""
remesh_scope_dialog.py -- the one mesh panel: the groups, and the parameters.

This module reproduces §2 of doc/remesh_scope_mockup.html in Qt: a card with one
row per group, one parameter block shared by the checked groups, and a footer
strip carrying the summary and the buttons.

Why it is the *only* mesh dialog:

  A mesh dialog collects exactly two things: the scope (which parts) and the
  parameters (how). On a first run every part has to be meshed -- "not meshed" is
  not something a GDML export accepts -- so the boxes start ticked, all of them.
  They are live from that first run too: meshing one group of a two-group
  assembly is a legitimate thing to want, and the other can follow later.
  An unticked group keeps the mesh it already has; so does a ticked group whose
  values did not change, because running gmsh again for the facets it already
  produced only costs time. One panel, one face, first mesh to last re-mesh.

Why the unit is a group and never a part: two parts that share a contact face
share one facet set, so re-meshing one side alone leaves the two sides with
unrelated triangulations, which Geant4 reports as false Overlaps. A group is a
connected component of the contact graph (mesh/scope.py), the smallest unit the
mesher can honour -- and the row says which kind it is right next to the name
(`Assembly conformal` vs `Per-solid`), turning a constraint of the mesher into a
visible fact instead of a surprise.

Where the parameters live: with the unit, not with the panel. One block edits
them -- a form per row, or per solid, would be six copies of the same eight
fields -- and what it writes belongs to every *selected* row. There is one
gesture, and the selection it builds is the scope of everything the panel does:

  - clicking a row selects that row alone, which is how one unit gets its own
    numbers: "these numbers are this unit's";
  - ctrl-click toggles one more row into the selection, shift-click takes the
    range back to the last click, ctrl-A takes everything -- and an edit then
    lands on all of them, field by field, so it is the fast way to give a whole
    model one set of numbers without copying the fields nobody touched;
  - the selection is also what `Mesh` runs and what `View Mesh` draws: what is
    ticked is what the run works on and what the 3D view shows.

An unticked unit keeps the mesh it has; so does a selected one whose values did
not change -- but only while the mesh it holds was made by the job it is in now.
A unit that was meshed per-solid and has since been grouped, or the other way
round, is meshed again: the facets that exist are not the facets its mode asks
for, and reporting them as its own would mix the two kinds of mesh in one model
(_source_of, and the provenance the host keeps in _mesh_source).

The block marks the fields that differ from the mesh its unit already has, which
is exactly the set a run will re-mesh.

The one value that is not per unit is the mode: auto / assembly / per-solid
decides what a unit *is* (a whole group, or one solid of it), so it is adopted by
the whole panel and rebuilds the rows when it changes -- which also drops the
reuse for every unit the new mode describes differently.

Double-clicking a row highlights that group's solids in the 3D view, so the row
can stay one line however big the model gets.

Why the progress bar is here too: this is the window a run is started from and
the window the user is looking at while it runs, so it is where the run reports
-- one bar under the parameters, and two rows under the bar that hold their
height whatever the bar is reading. The same goes for
the other wait this panel starts: Check contacts reports on that bar too, one
wait at a time, so the window a button is in is the window its wait is in
(_bar_owner). The separate progress dialog it replaces carried a second log (the
main window already has one), a Cancel (the toolbar turns into Cancel for the
length of a session) and a
"regenerate" button (the Mesh button, ten seconds later, once a value is
edited). What was worth keeping is here: the stage markers, the heartbeat, and
the two things to do with a model that has nothing left to plan -- look at the
mesh, or have the units behind it judged again. Both take the footer's left
slot, which holds the summary of the next run until the next run is a value
edit away.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from mesh.gmsh_dialog import (
    MODE_ASSEMBLY, MODE_AUTO, MODE_PER_SOLID, MeshParamsWidget,
    _fmt_duration, merge_defaults, panel_palette, section_rule,
)
from mesh.scope import MeshGroup, group_key, scope_text

# How a forced mode reads in the summary. MODE_AUTO is absent on purpose: it is
# not a mode but the absence of one, and resolved_mode() turns it into the mode
# the group actually needs.
_MODE_LABEL = {
    MODE_ASSEMBLY: "Force assembly",
    MODE_PER_SOLID: "Force per-solid",
}

# The card's width, fixed. The parameter block is a three-column form and needs
# 652 px of it by itself (measured: `MeshParamsWidget.minimumSizeHint`), plus the
# body's 13 px side margins -- so 680 is the width at which the panel is exactly
# itself and not one pixel wider. Widening it would only add whitespace around a
# form and a row list that are both fixed-content; leaving it free was worse, and
# is what the flash was: a dialog's sizeHint is the sum of every child's wish, so
# one long unwrapped sentence anywhere in the panel opened the window 300 px too
# wide and Qt re-laid it out on screen.
_CARD_WIDTH = 680

# The group list's floor: below this the list stops reading as a list, whatever
# the group count. It has no ceiling -- the list is the one band that takes the
# height a stretched window has to give, and dragging the panel taller is how a
# long scope is meant to be read.
_LIST_MIN_HEIGHT = 260

# The height the panel *opens* at. The list answers sizeHint() with its whole
# content now, so without a cap a forty-group model would open as a forty-row
# window, which §3 of the mockup rules out. Capping the opening height keeps the
# first sight of the panel the same size for every model; every pixel past it is
# the user's to drag, which is why this bounds the window and not the list.
_OPEN_HEIGHT_CAP = 660

# A row that is standing by rather than absent. The status block under the bar is
# two rows at every moment (_build_progress), and a row with nothing to say keeps
# its line by holding a no-break space: emptied, not hidden, the same way the
# notice band is kept (_refresh_contact_notice), so a wait that has no checklist
# does not take a line off the panel and pull everything above it down.
_BLANK_ROW = "\u00a0"


def resolved_mode(group: MeshGroup, params: Optional[dict]) -> str:
    """The mode this group will really be meshed in.

    "auto" only means anything per group: a coupled group *has* contact faces and
    therefore needs one assembly job, an isolated part needs one per-solid job.
    """
    chosen = (params or {}).get("mode", MODE_AUTO)
    return group.mode if chosen == MODE_AUTO else chosen


class _GroupRow(QFrame):
    """One row of the scope list: `Group A · 3 part(s)` plus the mode chip.

    A row is on or off, and the row itself says which -- `.sr.on` / `.sr.off` in
    the mockup: a checked row is tinted and its text keeps full contrast, an
    unchecked one is flat grey. Built by hand rather than as a QListWidget item
    because that is what buys the chip and the second state; a delegate would buy
    the same thing with more code.

    Clicking emits `clicked(index, how)`, where `how` is the selection gesture:
    "one" for a plain click, "toggle" for ctrl-click, "range" for shift-click.
    The row is not just a tick -- it is how the parameter block below is aimed at
    one unit instead of at everything ticked, and how several units are aimed at
    together. Double-click emits `activated` so the host can open the group on its
    own. The panel lists groups, not parts, and "Group A · 3 part(s)" is not an
    answer to "which three?" -- so the answer has to live somewhere, and the row
    stays one line.

    `title` / `count` override the two labels: in per-solid mode the row is one
    solid and is called by its name, with the group it belongs to where the part
    count sits.
    """

    toggled = pyqtSignal(int, bool)
    activated = pyqtSignal(int)
    clicked = pyqtSignal(int, str)

    def __init__(self, index: int, group: MeshGroup, pal: Dict[str, str],
                 title: str = "", count: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._index = index
        self._group = group
        self._pal = pal
        self._mode = group.mode
        self._forced = False
        self._active = False
        self.setObjectName("scopeRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 11, 7)
        lay.setSpacing(10)

        self._check = QCheckBox()
        self._check.setFixedSize(16, 16)
        self._check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check.toggled.connect(
            lambda on: self.toggled.emit(self._index, bool(on)))
        # Live on the first run too, and never hidden: the panel is the same panel
        # from the first mesh to the tenth re-mesh, and meshing one group of a
        # two-group assembly first is a legitimate way to work -- the rest only
        # has to be meshed before a GDML export, not before this.
        self._check.setChecked(True)
        self._check.setToolTip(
            "Ticked units are the ones this panel works on: they are what Mesh "
            "re-meshes and what View Mesh draws. An unticked one keeps the mesh "
            "it has.\n\n"
            "Click a row to work on that one alone, Ctrl-click to add or remove "
            "one, Shift-click to take a range, Ctrl-A for all of them: the "
            "parameters below are edited for everything ticked.")
        lay.addWidget(self._check, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title = QLabel(title or f"Group {group.letter}")
        # A titled row (per-solid mode) can have no count at all: a solid that
        # is its own component belongs to no larger group, and "1 part(s)"
        # would only restate the title. It stays out of the layout instead.
        self._count = QLabel(count or ("" if title else f"{group.n_parts} part(s)"))
        # Only ever hide, never setVisible(True) here: _count has no parent yet,
        # and Qt turns a shown parentless widget into its own top-level window,
        # which flashed a popup for every row _rebuild_rows re-made. A widget is
        # hidden by default, and addWidget (below) shows it once it has text.
        if not self._count.text():
            self._count.hide()
        self._chip = QLabel(group.mode_label)
        inner = QHBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        inner.addWidget(self._title)
        inner.addWidget(self._count)
        inner.addWidget(self._chip)
        inner.addStretch(1)
        lay.addLayout(inner, 1)

        self._paint()

    # -- state ---------------------------------------------------------

    def checked(self) -> bool:
        return self._check.isChecked()

    def set_checked(self, on: bool):
        self._check.setChecked(bool(on))
        self._paint()

    def set_active(self, on: bool):
        """Is this the row the parameter block is showing right now?

        The tick and the shown row are two different questions -- "which units
        this panel works on" and "whose numbers are on screen" -- so they get two
        different marks: the checkbox for the first, this accent edge for the
        second. Both are in the selection; a multi-row selection shows the row
        that was clicked last and edits all of them.
        """
        if bool(on) == self._active:
            return
        self._active = bool(on)
        self._paint()

    def set_tooltip(self, text: str):
        self.setToolTip(text)
        self._title.setToolTip(text)

    def set_mode(self, mode: str, forced: bool):
        """Show the mode this group will really be meshed in.

        The parameters can override it -- "Force per-solid" on a coupled group is
        a real choice, it is how an A/B on the coupling gets run -- and a chip
        still reading "Assembly conformal" while the run did per-solid would be
        the panel contradicting itself.
        """
        self._mode, self._forced = mode, forced
        self._chip.setText(_MODE_LABEL[mode] if forced else self._group.mode_label)
        self._chip.setStyleSheet(self._chip_qss(self.checked()))

    def mousePressEvent(self, event):
        """A click selects, with the modifiers every list has.

        Plain click: this row alone -- the one parameter block below then writes
        to one unit. Ctrl-click: add or remove this row. Shift-click: everything
        back to the last click. Not a QListWidget: the row carries a chip and two
        label styles, which a delegate would cost more code to reproduce.
        """
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            how = "toggle"
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            how = "range"
        else:
            how = "one"
        self.clicked.emit(self._index, how)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.activated.emit(self._index)
        super().mouseDoubleClickEvent(event)

    # -- painting ------------------------------------------------------

    def _paint(self):
        """Repaint the row for its current state.

        Colours, not a QGraphicsOpacityEffect: the off row is still readable, and
        the chip's own colours stay legible too.
        """
        p = self._pal
        on = self.checked()
        if self._active:
            bg, bd = p["row_sel_bg"], p["row_sel_border"]
            edge = f"border-left: 3px solid {bd};"
        else:
            bg = p["row_on_bg"] if on else p["row_off_bg"]
            bd = p["row_on_border"] if on else p["row_off_border"]
            edge = ""
        self.setStyleSheet(
            f"#scopeRow {{ background: {bg}; border: 1px solid {bd}; {edge}"
            f" border-radius: 9px; }}"
            f" #scopeRow QLabel {{ background: transparent; border: none; }}")
        self._title.setStyleSheet(
            f"color: {p['title'] if on else p['title_off']};"
            f" font-size: 12.5px; font-weight: 700;")
        self._count.setStyleSheet(
            f"color: {p['count'] if on else p['title_off']}; font-size: 11.5px;")
        self._check.setStyleSheet(self._check_qss())
        self._chip.setStyleSheet(self._chip_qss(on))

    def _check_qss(self) -> str:
        """Nothing but a transparent background: the tick itself is the platform's.

        The hand-drawn indicator was a flat blue square with no tick in it -- a
        state you had to already know was "on". The project tree draws its boxes
        the platform's way and they read at a glance, so this one does too.
        """
        return "QCheckBox { background: transparent; }"

    def _chip_qss(self, on: bool) -> str:
        p = self._pal
        if self._mode == MODE_ASSEMBLY:
            bg, bd, fg = p["conform_bg"], p["conform_border"], p["conform_text"]
        else:
            bg, bd, fg = p["indep_bg"], p["indep_border"], p["indep_text"]
        if not on:
            # An unchecked chip keeps its shape but loses its colour: the row is
            # still legible, and the mode is still readable.
            bd, fg = p["row_off_border"], p["title_off"]
        return (f"background: {bg}; border: 1px solid {bd};"
                f" border-radius: 999px; color: {fg}; padding: 1px 9px;"
                f" font-size: 11px; font-weight: 600;")


class MeshScopeDialog(QDialog):
    """Choose the groups to mesh, and the parameters that belong to them.

    Non-modal on purpose. Double-clicking a row opens the group in a window of
    its own, and an `exec()` here would freeze that window; the panel and the
    parts it talks about are one decision, so both stay live. The host opens it
    with `show()` and takes the answer from `accepted` -- see
    `MainWindow._slot_mesh`.
    """

    # The double-clicked group: the host opens it on a screen of its own. A
    # signal rather than a direct call, so this module keeps talking to nothing
    # but its own widgets. The group, not its entry ids: the window it opens is
    # titled and sized after it.
    group_activated = pyqtSignal(object)

    # The panel is also the progress window and it stays open after a run, so the
    # buttons of its left slot talk to the host instead of to the dialog's own
    # accept()/reject() machinery: the run, the contact analysis the rows are
    # built from, the mesh in the 3D view, and the way back from a failed run.
    mesh_requested = pyqtSignal()
    recheck_contacts_requested = pyqtSignal()
    regroup_accepted = pyqtSignal()
    view_mesh_requested = pyqtSignal()
    rollback_requested = pyqtSignal()

    def __init__(self, groups: Sequence[MeshGroup],
                 nodes: Sequence = (),
                 initial_params: Optional[dict] = None,
                 dark: bool = False,
                 first_run: bool = False,
                 preselect: Optional[Sequence[int]] = None,
                 meshed_params: Optional[Dict[Tuple[str, ...], dict]] = None,
                 source: Optional[Dict[str, Tuple[str, ...]]] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        # The components are the units the model *has* -- one per contact-graph
        # component, and they never change. `_groups` is what the rows show right
        # now: the same list, or one row per solid once the mode is forced to
        # per-solid (see _sync_units).
        self._components = list(groups)
        self._groups: List[MeshGroup] = []
        self._per_solid = False
        self._names = {n.entry_id: (n.name or n.entry_id) for n in nodes}
        self._dark = dark
        self._pal = panel_palette(dark)
        self._first_run = first_run

        # What each group's existing mesh was made with, keyed by its member set
        # (see scope.group_key). The opening values, the baseline of the
        # changed-field markers and the reuse test all read this one dict.
        self._meshed_params: Dict[Tuple[str, ...], dict] = dict(meshed_params or {})
        # Which job produced each part's current file: entry id -> the member set
        # of the job that wrote it. Records say what a unit was meshed with, but
        # not whether the file part holds is still that job's -- a per-solid run
        # and an assembly run write the same part's file, so a record can outlive
        # the mesh it describes. _source_of() is the other half of the reuse test.
        self._mesh_source: Dict[str, Tuple[str, ...]] = dict(source or {})
        self._defaults: Dict[str, Any] = merge_defaults(initial_params)

        # The run the panel is watching. The panel is the progress window now --
        # a session reports into it and it stays open when the session ends -- so
        # it holds the bar's state, and the flag that keeps `Mesh` from starting a
        # second session on top of the one already running.
        self._running = False
        self._run_no = 0
        # One bar, two waits, and neither is allowed to overwrite the other:
        # the session's percentage and line here, the re-checked analysis's with
        # the state it reports in (set_contact_progress). `_bar_owner` says
        # whose reading the bar is showing -- one at a time -- and a session
        # starts as the owner, so a panel that has never run anything reads
        # "Idle" at zero until a run or a re-check takes the bar
        # (_refresh_status).
        self._run_value = 0
        self._contact_value = 0
        self._contact_status = ""
        self._bar_owner = "run"
        # Whether the analysis now reporting is one the user asked for *here*.
        # The host runs the same analysis by itself (after an import, after a
        # part is moved), and that one is not a wait this panel started, so it
        # does not get this panel's bar (set_contact_state).
        self._recheck_asked = False
        self._has_mesh = bool(self._meshed_params)
        # What the contact analysis behind the rows is doing: "done" until the
        # host says otherwise (see set_contact_state). The rows are per-solid
        # while it runs, and that is a wait, not a verdict -- so the panel says
        # which of the two it is.
        self._contact_state = "done"
        self._contact_detail = ""
        # Set the moment a session is planned from the rows (start_run) and
        # never cleared: from then on the rows are what a run was reported
        # against, so a late contact analysis offers itself instead of
        # rewriting them (_late_components, set_components).
        self._rows_committed = False
        self._late_components: Optional[List[MeshGroup]] = None
        self._rollback_run_no: Optional[int] = None
        self._stages: List[str] = []
        self._stage = -1
        self._status_text = "Idle"
        self._elapsed: Optional[float] = None
        self._idle: Optional[float] = None
        # Which row the parameter block edits (an index into _groups), and the
        # mode the panel is set to. The mode is not one unit's business -- it
        # decides what a unit *is* (a whole group or one solid of it), so it is a
        # property of the panel while the six numbers are properties of the row.
        self._current: Optional[int] = None
        # Where a shift-click measures its range from: the row of the last click.
        # The ticks are the selection; this is only the far end of the gesture.
        self._anchor: Optional[int] = None
        self._mode_choice: str = self._defaults["mode"]
        # Values belong to the unit, not to the panel: one editor writes them, but
        # it writes them to the row that is current -- so a solid can be given its
        # own numbers without re-meshing the rest. Keyed by member set, not by row
        # number: a row number names a different unit the moment the rows are
        # rebuilt for per-solid, and what was typed has to survive that.
        self._unit_params: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        self._seed_unit_params()
        self._groups = self._units_for_mode(False)
        self._rows: List[_GroupRow] = []
        self._rows_layout: Optional[QVBoxLayout] = None
        self._loading = True

        # One title for every run: the first mesh and the tenth re-mesh are the
        # same panel, and a re-mesh is told from a first mesh by the button that
        # starts it ("Re-mesh 3 part(s)" rather than "Mesh 3 part(s)").
        self.setWindowTitle("Mesh · Mesh Scope")
        self.setFixedWidth(_CARD_WIDTH)
        self.setModal(False)
        self._build_ui()
        # Ctrl-A takes everything. A window shortcut rather than keyPressEvent:
        # the panel is full of spin boxes and combos, and a focused line edit eats
        # the keystroke as "select this text" before the dialog ever sees it.
        self._select_all_shortcut = QShortcut(
            QKeySequence(QKeySequence.StandardKey.SelectAll), self)
        self._select_all_shortcut.activated.connect(self.select_all)
        # The panel can open with the mode already forced -- it re-opens at the
        # last run's values -- and the rows have to be the ones that mode means
        # before anything is ticked.
        self._sync_units()
        self.set_selected(range(len(self._groups)) if preselect is None
                          else list(preselect))
        self._loading = False
        self._refresh_all()
        self._settle_geometry()

    def _seed_unit_params(self):
        """Opening values for every unit key the panel can show, once per key.

        A component reads the record of its own mesh, and failing that the one
        all of its parts carry (_parts_record): a unit regrouped late starts on
        the numbers the user gave those parts. A solid reads its own record when
        it has one. A per-solid run leaves the records per solid, so reading
        those back is the only way a solid's own numbers survive a re-open --
        without it the whole component falls back to the panel's defaults and
        every solid is shown the first one's values, which then reads as
        "everything changed" against meshes that did not.

        Keys that are already there are left alone: this runs again when a
        late contact analysis hands the panel new components (set_components),
        and what the user typed in the meantime has to outlive that.
        """
        for comp in self._components:
            key = group_key(comp.entry_ids)
            if key not in self._unit_params:
                self._unit_params[key] = dict(
                    self._meshed_params.get(key) or self._parts_record(comp)
                    or self._defaults)
            for eid in comp.entry_ids:
                part_key = group_key([eid])
                if part_key not in self._unit_params:
                    self._unit_params[part_key] = dict(
                        self._meshed_params.get(part_key)
                        or self._unit_params[key])
        # The panel's mode overrules whatever mode each unit's own record came
        # with, so the selector, the chips and the plan cannot disagree about
        # the one value that is not per unit.
        for params in self._unit_params.values():
            params["mode"] = self._mode_choice

    def set_components(self, groups: Sequence[MeshGroup]) -> bool:
        """Adopt a contact graph that landed after the panel was already open.

        The analysis runs behind the model, and on a big assembly it lands
        long after the import that started it -- so the panel is regularly
        built from an empty contact graph, where no solid has a neighbour and
        every row is a per-solid one for a model that is a single assembly.
        This is the other half of that: the real components go in, and the
        rows are re-made for them. The ticks follow the *solids* they were
        on, so a part that turns out to be coupled comes back ticked as part
        of its group, and the edited row follows its members too.

        Returns whether anything changed: the caller logs the regrouping,
        and a second call with the same components is a no-op.

        Rows that a run was planned from are never rebuilt. They are what that
        run's progress and its "kept / meshed" report were about, so swapping
        them afterwards leaves the report describing units that are no longer
        on screen. The answer is held instead and offered in the notice line,
        where the user takes it with the Regroup button (_on_regroup).
        """
        new = list(groups)
        if [group_key(g.entry_ids) for g in new] == \
                [group_key(g.entry_ids) for g in self._components]:
            # Nothing to adopt and nothing to offer: the answer agrees with
            # what is on screen, so the notice has no news either.
            self._late_components = None
            self._refresh_contact_notice()
            return False
        if self._running or self._rows_committed:
            self._late_components = new
            self._refresh_contact_notice()
            return False
        self._apply_components(new)
        return True

    def _apply_components(self, new: Sequence[MeshGroup]):
        """Rebuild the rows around `new`, the ticks still on their solids."""
        ticked = {eid for i in self.selected_indices()
                  for eid in self._groups[i].entry_ids}
        was = self.current_index()
        unit_key = (group_key(self._groups[was].entry_ids)
                    if was is not None else None)
        self._components = list(new)
        self._seed_unit_params()
        self._groups = self._units_for_mode(self._per_solid)
        self._rebuild_rows()
        self._loading = True
        try:
            for row, unit in zip(self._rows, self._groups):
                row.set_checked(bool(set(unit.entry_ids) & ticked))
        finally:
            self._loading = False
        self._current = self._row_of_keys(unit_key, None)
        self._resolve_current()
        self._load_params_for_current()
        self._refresh_all()
        # The list just changed length by an order of magnitude (one row per
        # solid, then one per group), so the window has to be re-sized for it.
        self._settle_geometry()

    def _on_regroup(self):
        """The notice's Regroup button: take the answer the rows were spared."""
        late = self._late_components
        if late is None or self._running:
            return
        self._late_components = None
        self._apply_components(late)
        self._refresh_contact_notice()
        self.regroup_accepted.emit()

    def set_contact_state(self, state: str, detail: str = ""):
        """What the contact analysis is doing: "running", "skipped", "failed"
        or "done".

        The host owns the analysis, so it is the host that says what it is up
        to -- the panel never asks a runner anything, the same rule its progress
        follows. "running" is the state that matters: the analysis can land well
        after the panel is open, and until it does every solid is a unit of its
        own. That is the only honest answer available (nothing is known to touch
        anything), but a per-solid list for a model that is one assembly reads
        as the tool's verdict unless the panel says it is still waiting -- and
        the chips cannot say it, because `Per-solid` is what they mean on a
        model the analysis has already cleared.

        It is also the state of the progress bar, for a re-checked analysis: a
        re-check is one of the two waits this panel owns, the session being the
        other, and the number that goes with this state arrives separately
        (set_contact_progress), since it is written many times a second and
        re-reading the notice for each tick would be work that never reaches the
        screen.
        """
        self._contact_state, self._contact_detail = state, detail
        if state == "running":
            # A re-check is a wait started from this panel, so it reports on
            # this panel's bar the way a session does -- but only the re-check:
            # the host runs the same analysis on its own after an import or a
            # move, and that one leaves the bar alone. It is not a wait the user
            # began here, and the bar is the button's wait; a panel opened onto
            # one of those reads zero and idle, which is what its next Mesh
            # press is about to fill.
            #
            # A session in flight also keeps the bar it took, even for our own
            # re-check: a check cannot be started during a session, but can
            # still be running when one begins, and the session was asked for
            # last.
            if self._recheck_asked and not self._running:
                self._bar_owner = "contact"
                self._contact_value = 0
                self._contact_status = "Contact analysis · starting…"
        else:
            # Landed, and "was this one ours" is answered either way: the next
            # check has to ask for the bar from its own press.
            self._recheck_asked = False
            if self._bar_owner == "contact":
                # The bar reads the verdict by the session's own rule
                # (finish_run): full when the analysis ran to the end, back to
                # zero when it did not. It keeps the bar rather than handing it
                # back, so the line under it is the analysis's last word -- the
                # detail behind a failure belongs to the notice band, which says
                # it above the rows it is about (_refresh_contact_notice).
                self._contact_value = 100 if state == "done" else 0
                self._contact_status = ("Contact analysis done" if state == "done"
                                        else "Contact analysis incomplete")
        self._refresh_status()
        self._refresh_contact_notice()
        self._refresh_footer()
        if not self.isVisible():
            # The panel is sized before it is shown, and the host pushes this
            # while it is still off screen, so a notice already on it has to be
            # paid for in that same pass: a window that grows the moment it
            # appears is the jump _settle_geometry exists to avoid.
            self._settle_geometry()

    def set_contact_progress(self, value: int, message: str = ""):
        """How far the analysis has got, in percent.

        The same number the status bar's own bar carries: two bars, one wait.
        That one is the reading that survives with this panel closed -- and the
        only one there when the re-check is started from a panel the user then
        closes -- while this one is the reading of the window the button is in,
        and only while that check is the panel's bar (_bar_owner): the analysis
        the host runs by itself keeps its number here unseen.

        Written to the analysis's own value, not to the widget: a session that
        owns the bar must not be captioned with the check's step.
        """
        self._contact_value = max(0, min(100, int(value)))
        if message:
            self._contact_status = f"{message} {self._contact_value}%"
        self._refresh_status()

    def _on_recheck_pressed(self):
        """Re-check contacts, and mark the answer as this panel's wait.

        The button asks the host for a run of the analysis, and the host runs
        the same one on its own account after an import or a move; the flag is
        what keeps the two apart on the bar (set_contact_state).
        """
        self._recheck_asked = True
        self.recheck_contacts_requested.emit()

    def _refresh_contact_notice(self):
        """The one line that keeps `Per-solid` from reading as a verdict.

        Body ink (`title`), not the dim section grey a heading over the list
        would take: this line is news about the rows, and the offer it carries
        is something to act on. The failure line keeps the warning colour --
        that one is the panel reporting that a background job did not finish,
        and colour is what makes it read as one.

        It is never blank, though: with nothing to report it states what the
        rows are (_grouping_state), in the dim grey the rest of the state about
        the panel is written in. An empty band above a list reads as something
        that failed to load -- and the state of the rows is the one thing the
        row chips cannot say, since they only ever speak for their own unit.
        """
        p = self._pal
        state = self._contact_state
        if state == "running":
            text = ("Contact analysis running: the units below are regrouped "
                    "when it lands." if not self._rows_committed else
                    "Contact analysis running: the rows stay on the units "
                    "meshed here.")
            colour = p["title"]
        elif state == "failed":
            # Two different situations behind one failure: a panel that never
            # had an answer is all singletons, one whose re-check failed still
            # shows what the last analysis found.
            found = any(len(g.entry_ids) > 1 for g in self._components)
            text = (f"Contact analysis incomplete ({self._contact_detail}): the "
                    "units are the ones the last analysis found." if found else
                    f"Contact analysis incomplete ({self._contact_detail}): "
                    "every solid is listed on its own.")
            colour = p["changed_border"]
        elif state == "skipped":
            # The import box left unticked, so nobody has looked at this model:
            # the rows are per-solid because no check was asked for, and not
            # because nothing touches. The button beside it is the ask, so the
            # line names it rather than promising a regroup that is not coming.
            text = ("Contact check skipped: every solid is listed on its own. "
                    "Check contacts runs it now." if not self._rows_committed
                    else "Contact check skipped: the rows stay on the units "
                    "meshed here.")
            colour = p["title"]
        elif self._late_components:
            # The answer disagrees with the rows and the rows are a run's, so
            # it waits here for the button beside it rather than rewriting them.
            text = (f"Contact analysis finished: it makes "
                    f"{len(self._late_components)} unit(s). The rows stay on "
                    "the units meshed here.")
            colour = p["title"]
        else:
            # No wait and nothing wrong: the band states the grouping instead of
            # emptying itself. Same band, same one line (_grouping_state), so a
            # notice arriving over it still moves nothing on screen.
            text = self._grouping_state()
            colour = p["foot_text"]
        self._notice_text.setText(text)
        self._notice_text.setStyleSheet(
            f"color: {colour}; font-size: 11.5px;")
        self._regroup_btn.setVisible(bool(self._late_components)
                                     and not self._running)

    def _grouping_state(self) -> str:
        """What the rows are, in one line: the band's state when it has no news.

        The chips say this per unit; this says it for the model -- how many
        units the analysis found over how many solids, and, in per-solid mode,
        that it is the mode rather than the analysis that is deciding. Rows that
        are one unit per solid either way (no contacts anywhere) say so instead
        of a count of one over one.
        """
        solids = sum(len(c.entry_ids) for c in self._components)
        units = len(self._components)
        if self._per_solid:
            text = f"Per-solid: {solids} solid(s), one unit each"
            return (f"{text}; the contact grouping ({units} unit(s)) is not "
                    "used." if units < solids else f"{text}.")
        if units == solids:
            return (f"No contacts between the {solids} solid(s): each one is "
                    "its own unit.")
        return f"Contact grouping: {units} unit(s) over {solids} solid(s)."

    def _settle_geometry(self):
        """Give the window its final height before it is ever shown.

        The height is not a constant, it is whatever the wrapped labels need at
        `_CARD_WIDTH` -- so it can only be asked for after the layout has run *at
        that width*, and it has to be asked for now: a window shown first and
        sized afterwards is a window that jumps in front of the user.

        Two passes, and they are not the same pass: a word-wrapped QLabel answers
        `sizeHint()` with its single-line height until the layout has handed it a
        width, so `adjustSize()` alone came up short of the card's own content and
        Qt re-laid the card out on screen -- a small window, then the real one.
        The first pass hands out the widths, the second reads back the heights.
        """
        lay = self.layout()
        if lay is None:
            return
        self.ensurePolished()
        self.resize(_CARD_WIDTH, 1)
        for _ in range(2):
            lay.activate()
            # `sizeHint()` now counts the list at its full content height, so it
            # is clamped: the cap belongs here, on how tall the panel opens, not
            # on the list, which has to stay free to grow when it is stretched.
            self.resize(_CARD_WIDTH,
                        min(lay.sizeHint().height(), _OPEN_HEIGHT_CAP))

    # ----------------------------------------------------------------
    # Construction
    # ----------------------------------------------------------------

    def _build_ui(self):
        """Body and footer strip -- the two bands left of the mockup card."""
        self.setObjectName("scopePanel")
        self.setStyleSheet(
            f"#scopePanel {{ background: {self._pal['card_bg']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # The body is the band that grows with the window: the scope line is
        # fixed, the group list takes the extra height. The parameters live
        # below the body rather than inside it, so they stay pinned above the
        # footer and do not drift when the window is stretched.
        body = QWidget()
        body.setObjectName("scopeBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(13, 12, 13, 0)
        bl.setSpacing(9)
        bl.addWidget(self._build_scope_line())
        bl.addWidget(self._build_contact_notice())
        bl.addWidget(self._build_rows(), 1)
        root.addWidget(body, 1)

        params_body = QWidget()
        params_body.setObjectName("scopeBody")
        pl = QVBoxLayout(params_body)
        pl.setContentsMargins(13, 9, 13, 11)
        pl.setSpacing(9)
        pl.addWidget(self._build_params_head())

        self._params = MeshParamsWidget(self._defaults, dark=self._dark,
                                        parent=self)
        self._params.changed.connect(self._on_params_edited)
        self._params.setSizePolicy(QSizePolicy.Policy.Preferred,
                                   QSizePolicy.Policy.Fixed)
        pl.addWidget(self._params)

        # Under the parameters, not beside them: the panel is read top-down as
        # what to mesh, with what numbers, and then how far a run has got. The
        # rule that opens it is the same one that separates the parameter block's
        # own Advanced section.
        pl.addWidget(self._build_progress())
        root.addWidget(params_body)

        root.addWidget(self._build_footer())

    def _build_scope_line(self) -> QWidget:
        """The All / None shortcuts, on their own line above the rows.

        Both are about the ticks the rows below hold: the two answers to "which
        groups" that must not need a click per row. They sit directly under the
        window title: the last-run strip that used to precede them ("re-mesh 2 ·
        last #1 …") was a second summary of a run the rows and the footer
        already describe.
        """
        line = QWidget()
        h = QHBoxLayout(line)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addStretch(1)

        self._all_btn = self._ghost("All")
        self._all_btn.clicked.connect(
            lambda: self.set_selected(range(len(self._groups))))
        self._none_btn = self._ghost("None")
        self._none_btn.clicked.connect(lambda: self.set_selected([]))
        h.addWidget(self._all_btn)
        h.addWidget(self._none_btn)
        return line

    def _build_contact_notice(self) -> QWidget:
        """The line between the ticks and the rows: the state of the grouping.

        It belongs here, directly above the list it is about: what the rows say
        (`Per-solid` / `Assembly conformal`) is only an answer once the contact
        analysis has landed, and that is exactly the kind of thing a chip cannot
        say on its own. It carries news when there is any -- a wait in flight, a
        failure, an answer that disagrees with the rows -- and the state of the
        grouping when there is none (_grouping_state), which is one line either
        way. Never blank: an empty band between the ticks and the list reads as
        something that failed to arrive.

        One line, and the band is reserved at the button's height: a notice
        lands on a window that is already on screen, and a row that grows then
        is a row the layout has to find room for, which drops the list and the
        footer below it.
        """
        self._notice = QFrame()
        n = QHBoxLayout(self._notice)
        n.setContentsMargins(0, 0, 0, 0)
        n.setSpacing(8)
        self._notice_text = QLabel()
        self._notice_text.setWordWrap(True)
        n.addWidget(self._notice_text, 1)
        # The button is the point of the line it sits on: an answer that
        # arrived after the rows were already a run's is offered, not applied
        # (set_components), and this is where the user takes it.
        self._regroup_btn = self._plain("Regroup")
        self._regroup_btn.setToolTip(
            "Rebuild the rows from the contact analysis that landed after the "
            "run")
        self._regroup_btn.clicked.connect(self._on_regroup)
        self._regroup_btn.setVisible(False)
        n.addWidget(self._regroup_btn, 0, Qt.AlignmentFlag.AlignTop)
        self._notice.setMinimumHeight(25)
        return self._notice

    def _build_rows(self) -> QWidget:
        """The group list, in a scroll area with a floor and no ceiling.

        A minimum rather than a cap: §3 of the mockup is explicit that a model
        with forty groups must not *open* as a forty-row dialog, but the list is
        still the band a stretched window has to give its extra height to.
        Capping it here is what made the panel fixed-height, and that is the one
        thing the scope list cannot be -- where it opens is capped in
        `_settle_geometry` instead, so a drag can still carry it far past it.
        """
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(7)
        self._rows_layout = v
        for i, g in enumerate(self._groups):
            row = self._make_row(i, g, holder)
            v.addWidget(row)
            self._rows.append(row)
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(holder)
        holder.adjustSize()
        # A floor, not a ceiling, and Expanding so the layout hands it every
        # pixel past the other bands: the list stays a list however few groups
        # there are, and grows without limit when the window is dragged down.
        scroll.setMinimumHeight(_LIST_MIN_HEIGHT)
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Expanding)
        return scroll

    def _build_progress(self) -> QWidget:
        """The bar and the two rows that say what the bar is doing.

        Two rows, and two of them at *every* moment, run or not: the stages on
        the first (what is behind, what is on, what is ahead) and the step it is
        on with its heartbeat on the second. Folded into one row they were
        longer than the panel is wide as soon as the step name was, so the row
        wrapped and unwrapped while the run was being watched -- and the panel's
        height moved with it. The same rule is why neither row is ever taken
        away: a wait with no checklist (the contact analysis) and a panel before
        its first run both read the same two lines as a run in progress, so
        nothing above the footer moves as the bar changes hands and back.
        """
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(5)
        v.addWidget(section_rule("Progress"))

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(16)
        v.addWidget(self._progress_bar)

        # Both rows are always in the layout; whose text goes in which is
        # _refresh_status's business.
        self._stage_label = QLabel(_BLANK_ROW)
        self._stage_label.setWordWrap(True)
        self._progress_label = QLabel(_BLANK_ROW)
        self._progress_label.setWordWrap(True)
        for lb in (self._stage_label, self._progress_label):
            lb.setStyleSheet(
                f"QLabel {{ color: {self._pal['foot_text']}; font-size: 11.5px; }}")
        v.addWidget(self._stage_label)
        v.addWidget(self._progress_label)
        self._refresh_status()
        return box

    def _build_footer(self) -> QWidget:
        """The buttons, as one strip: the model's on the left, the pair right.

        The left end holds what a run that just ended here leaves to do -- look
        at the mesh it produced, or undo it -- beside Check contacts, which
        is about the model rather than a run. The old window put "view result"
        and "regenerate" in a footer of its own, which meant the one thing the
        user wants next was on a window the user had to keep open.

        No summary line between them: the rows say which units the ticks picked
        and the blue button says how many parts a press would mesh, so a
        sentence in between only said it all a second time.
        """
        p = self._pal
        foot = QFrame()
        foot.setObjectName("scopeFoot")
        f = QHBoxLayout(foot)
        f.setContentsMargins(11, 9, 11, 9)
        f.setSpacing(9)

        self._rollback_btn = self._plain("Roll back")
        self._rollback_btn.clicked.connect(
            lambda: self.rollback_requested.emit())
        f.addWidget(self._rollback_btn)
        # Blue like the run button, and grey while it cannot be pressed: it is
        # only on screen when there is nothing left to mesh and the result *is*
        # the next thing to look at, so it makes the same promise the run button
        # does -- and the two are never on screen together.
        self._view_btn = self._primary("View Mesh")
        self._view_btn.clicked.connect(lambda: self.view_mesh_requested.emit())
        f.addWidget(self._view_btn)
        # The rows are one answer to "which parts belong together", and it is
        # the answer of a background job that ran on the model as it was then.
        # The button is the second opinion -- and the first, on a model whose
        # check was skipped at import. What it always is, is an explicit ask,
        # and the rows are rebuilt from what it finds (set_components).
        # Blue in every state too, grey only while it cannot run: it is about the
        # model rather than the next run, and a white button beside a blue one
        # reads as the lesser action, which this is not.
        self._recheck_btn = self._primary("Check contacts")
        self._recheck_btn.setToolTip(
            "Look for touching solids and regroup the units; a check already "
            "there is replaced")
        self._recheck_btn.clicked.connect(self._on_recheck_pressed)
        f.addWidget(self._recheck_btn)

        # Absorbs the spare width, holding the pair against the right edge.
        f.addStretch(1)

        cancel = self._plain("Cancel")
        cancel.clicked.connect(self.reject)
        f.addWidget(cancel)
        self._ok_btn = self._primary(is_default=True)
        # Not accept(): the session starts under this window and the window stays
        # open to carry its progress, so the button asks the host for a run.
        self._ok_btn.clicked.connect(lambda: self.mesh_requested.emit())
        f.addWidget(self._ok_btn)

        foot.setStyleSheet(
            f"#scopeFoot {{ background: {p['foot_bg']};"
            f" border-top: 1px solid {p['foot_border']}; }}")
        return foot

    # -- button factories ----------------------------------------------

    def _ghost(self, text: str) -> QPushButton:
        """A borderless shortcut: visible when looked for, silent otherwise."""
        p = self._pal
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {p['head_text']}; font-size: 11.5px; padding: 1px 3px; }}"
            f"QPushButton:hover {{ color: {p['pri_bg']}; }}"
            f"QPushButton:disabled {{ color: {p['title_off']}; }}")
        return b

    def _plain(self, text: str) -> QPushButton:
        """The white button: the way out, and the presses that are not the task."""
        p = self._pal
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(25)
        # Fixed: a button is the width of its word, so a strip of them reads as a
        # strip of buttons rather than a row of stretched placeholders.
        b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        b.setStyleSheet(
            f"QPushButton {{ background: {p['btn_bg']};"
            f" border: 1px solid {p['btn_border']}; border-radius: 6px;"
            f" color: {p['btn_text']}; padding: 3px 13px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {p['pri_bg']};"
            f" color: {p['pri_bg']}; }}"
            # Dimmed, not merely inert: the rule above overrides Qt's own
            # disabled look, so a session in flight would otherwise leave these
            # on screen looking exactly as pressable as before.
            f"QPushButton:disabled {{ background: {p['row_off_bg']};"
            f" border-color: {p['row_off_border']};"
            f" color: {p['title_off']}; }}")
        return b

    def _primary(self, text: str = "", is_default: bool = False) -> QPushButton:
        """The blue button: the press this strip is asking for.

        Grey while it is unavailable, which is what the colour is for: a press
        that cannot be made has to stop looking like one. `is_default` belongs to
        the run's button alone (it is the one Enter fires); the other two are
        blue without taking the key, because they are on screen as the thing to
        do next rather than as the window's default.
        """
        p = self._pal
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(25)
        b.setDefault(is_default)
        b.setStyleSheet(
            f"QPushButton {{ background: {p['pri_bg']};"
            f" border: 1px solid {p['pri_border']}; border-radius: 6px;"
            f" color: {p['pri_text']}; padding: 3px 15px; font-size: 12px;"
            f" font-weight: 600; }}"
            f"QPushButton:disabled {{ background: {p['row_off_border']};"
            f" border-color: {p['row_off_border']};"
            f" color: {p['title_off']}; }}")
        return b

    # ----------------------------------------------------------------
    # Text
    # ----------------------------------------------------------------

    def _build_params_head(self) -> QWidget:
        """`Mesh parameters · <unit>`, naming the scope the block writes to.

        The rule is *not* a constant, unlike Advanced, and it is the only place
        that can say what an edit is about to touch: the block displays one unit
        but writes to every ticked one, so it names the row on screen and, when
        the selection is bigger, how many more it stands for. There is no
        copy-to-all button any more -- selecting all and editing *is* that, and
        it is the same gesture as selecting two.
        """
        row = section_rule("Mesh parameters")
        self._params_rule_label = row.findChildren(QLabel)[0]
        return row

    def _full_params_text(self, p: dict) -> str:
        return "\n".join((
            f"Algorithm:           {p.get('algorithm')}",
            f"Element Size Factor: {float(p.get('elem_factor', 1.0)):g}",
            f"Mesh Min Factor:     {float(p.get('mesh_min_factor', 6.0)):g}",
            f"Mesh Max Factor:     {float(p.get('mesh_max_factor', 5.0)):g}",
            f"Smoothing Steps:     {int(p.get('smoothing', 1))}",
            f"Element Order:       {int(p.get('element_order', 1))}",
            f"Mode:                {_MODE_LABEL.get(p.get('mode'), 'Auto')}",
        ))

    def _row_tooltip(self, g: MeshGroup) -> str:
        """Members and parameters, for the row that deliberately shows neither.

        This is also where a unit's own values are readable: the block below shows
        one set at a time, and the row says which unit it belongs to and what that
        unit would be meshed with -- so a row that was given its own numbers is a
        row you can check without clicking through every other one.
        """
        members = ", ".join(self._names.get(e, e) for e in g.entry_ids)
        if g.index in set(self.selected_indices()) and self._reused(g):
            state = ("\n\nThese are the values of the mesh it has: this run "
                     "keeps it.")
        elif self._meshed_record(g) is not None:
            # A record that no longer matches the facets on the parts: the unit
            # was meshed in the other mode since, so this run re-meshes it.
            state = ("\n\nIt was meshed once, but not as this unit, and not "
                     "with the mode it now asks for: this run re-meshes it.")
        else:
            state = ""
        return (f"{members}\n\n{self._full_params_text(self.params_for(g))}"
                f"{state}\n\nClick to set these values for this unit alone; "
                f"Ctrl-click and Shift-click to edit several at once.\n"
                f"Double-click to highlight it in the 3D view.")

    # ----------------------------------------------------------------
    # Units
    # ----------------------------------------------------------------

    def _units_for_mode(self, per_solid: bool) -> List[MeshGroup]:
        """The rows for one mode: whole components, or one row per solid.

        Per-solid is the A/B escape hatch -- the coupling is what an assembly
        costs, so the only way to see what it buys is to run the parts without
        it -- and in that mode the list has to open up to the solids it is
        about, because "Group A" is not a thing that can be meshed per-solid.
        A component that is split up starts from the values it had as a group:
        this is a mode change, not a reset.
        """
        units: List[MeshGroup] = []
        for comp in self._components:
            members = ([list(comp.entry_ids)] if not per_solid
                       else [[eid] for eid in comp.entry_ids])
            for member_ids in members:
                key = group_key(member_ids)
                if key not in self._unit_params:
                    self._unit_params[key] = dict(
                        self._unit_params[group_key(comp.entry_ids)])
                # A one-member row of its own is named after the solid; a whole
                # component keeps the group letter.
                name = "" if len(member_ids) > 1 else \
                    self._names.get(member_ids[0], member_ids[0])
                units.append(MeshGroup(index=len(units), entry_ids=list(member_ids),
                                       name=name))
        return units

    def _component_of(self, unit: MeshGroup) -> MeshGroup:
        """The contact-graph component `unit` belongs to."""
        members = set(unit.entry_ids)
        for comp in self._components:
            if members <= set(comp.entry_ids):
                return comp
        return unit

    def _make_row(self, index: int, unit: MeshGroup, holder: QWidget) -> _GroupRow:
        """One row, titled for the unit it stands for."""
        title = count = ""
        if unit.name:
            title = unit.name
            comp = self._component_of(unit)
            # Only a real group gets a "part of": with no contacts every solid
            # is its own component, so "Solid1 part of Group A" would describe
            # a solid as a part of itself, and five such rows would read as
            # five groups where there are none.
            if comp.n_parts > 1:
                count = f"part of {comp.label}"
        row = _GroupRow(index, unit, self._pal, title=title, count=count,
                        parent=holder)
        row.toggled.connect(self._on_row_toggled)
        row.activated.connect(self._on_row_activated)
        row.clicked.connect(self._on_row_clicked)
        return row

    def _rebuild_rows(self):
        """Re-make the rows for the current units, keeping their order."""
        lay = self._rows_layout
        if lay is None:
            return
        for row in self._rows:
            lay.removeWidget(row)
            row.setParent(None)
        self._rows = []
        holder = lay.parentWidget()
        for i, unit in enumerate(self._groups):
            row = self._make_row(i, unit, holder)
            lay.insertWidget(i, row)
            self._rows.append(row)

    def _sync_units(self):
        """Follow the mode: rebuild the rows when the unit changes under them.

        Called after a mode edit, and a no-op unless the mode crossed between
        per-solid and everything else. What survives it is the *meaning* of the
        state, not the row numbers: the ticks by component, so splitting Group A
        cannot silently untick half of it, and the edited row by member set, so
        the editor stays on the solid that was being edited.
        """
        per_solid = self._mode_choice == MODE_PER_SOLID
        if per_solid == self._per_solid:
            return
        selected = self._selected_component_keys()
        was = self.current_index()
        unit_key = group_key(self._groups[was].entry_ids) if was is not None else None
        comp_key = (group_key(self._component_of(self._groups[was]).entry_ids)
                    if was is not None else None)
        self._per_solid = per_solid
        self._groups = self._units_for_mode(per_solid)
        self._rebuild_rows()
        self._select_component_keys(selected)
        self._current = self._row_of_keys(unit_key, comp_key)
        # The rows are new objects, so the shift-click anchor is a number into a
        # list that no longer exists: it starts again from the edited row.
        self._anchor = self._current

    def _row_of_keys(self, unit_key, comp_key) -> Optional[int]:
        """The row to keep editing after a rebuild: the same unit, else its group.

        A solid that was merged back into its component has no row of its own any
        more, and the component it belongs to is the honest answer to "which row
        was I editing?" -- the same numbers, on the coarser unit. A rebuild with
        nothing current stays with nothing current: the editor is pointed at the
        ticks by _resolve_current() instead, which is the rule for an open panel.
        """
        if unit_key is None and comp_key is None:
            return None
        for i, unit in enumerate(self._groups):
            if unit_key is not None and group_key(unit.entry_ids) == unit_key:
                return i
        for i, unit in enumerate(self._groups):
            if group_key(self._component_of(unit).entry_ids) == comp_key:
                return i
        sel = self.selected_indices()
        return sel[0] if sel else None

    def _selected_component_keys(self) -> set:
        """The components the current ticks stand for, as member-set keys."""
        return {group_key(self._component_of(self._groups[i]).entry_ids)
                for i in self.selected_indices()}

    def _select_component_keys(self, keys):
        """Tick every unit of `keys`, whatever the current granularity is."""
        wanted = set(keys)
        self._loading = True
        try:
            for row, unit in zip(self._rows, self._groups):
                row.set_checked(
                    group_key(self._component_of(unit).entry_ids) in wanted)
        finally:
            self._loading = False

    # ----------------------------------------------------------------
    # Selection
    # ----------------------------------------------------------------

    def set_selected(self, indices: Sequence[int]):
        """Check exactly `indices`, and keep the editor on a row that is left."""
        self._set_checked_indices(int(i) for i in indices)
        self._resolve_current()
        self._load_params_for_current()
        self._refresh_all()

    def _set_checked_indices(self, indices):
        """Tick exactly `indices` without being heard: the caller refreshes.

        `row.set_checked` emits `toggled`, which is the host's business, so the
        `_loading` flag that keeps a rebuild quiet keeps a selection quiet too.
        """
        wanted = set(indices)
        self._loading = True
        try:
            for i, row in enumerate(self._rows):
                row.set_checked(i in wanted)
        finally:
            self._loading = False

    def select_all(self):
        """Ctrl-A: everything, which is how a whole model gets one set of values.

        The panel is the only place the scope is chosen, and "all of them" is the
        scope of a first run -- so it is one keystroke rather than one click per
        row on a model with thirty solids.
        """
        self._set_checked_indices(range(len(self._groups)))
        self._resolve_current()
        self._load_params_for_current()
        self._refresh_all()

    # ----------------------------------------------------------------
    # The current row -- what the parameters belong to
    # ----------------------------------------------------------------

    def current_index(self) -> Optional[int]:
        """The row the parameter block edits, if there is one."""
        if self._current is not None and 0 <= self._current < len(self._groups):
            return self._current
        return None

    def current_group(self) -> Optional[MeshGroup]:
        idx = self.current_index()
        return None if idx is None else self._groups[idx]

    def _on_row_clicked(self, index: int, how: str = "one"):
        """A click on a row: select by the modifier's gesture, and show that row.

        A plain click leaves this row selected alone, which is how one unit gets
        its own numbers -- "these numbers are this unit's". Ctrl-click adds or
        removes one, shift-click takes everything back to the last click; either
        way an edit then lands on all of them, which is the fast way to give a
        handful of solids the same numbers without unticking the rest. The
        clicked row is the one the block below displays, whatever the gesture.
        """
        if not (0 <= index < len(self._groups)):
            return
        if how == "toggle":
            sel = set(self.selected_indices())
            sel.symmetric_difference_update({index})
            self._set_checked_indices(sel)
        elif how == "range" and self._anchor is not None:
            lo, hi = sorted((self._anchor, index))
            self._set_checked_indices(range(lo, hi + 1))
        else:
            self._set_checked_indices([index])
            self._anchor = index
        self._current = index
        self._load_params_for_current()
        self._refresh_all()

    def _resolve_current(self):
        """Fall back to the first ticked row when there is nothing to edit.

        The panel is opened with everything ticked and no click yet, and an
        editor pointing at nothing would be a dead block on a live panel.
        """
        if self.current_index() is None:
            sel = self.selected_indices()
            self._current = sel[0] if sel else None

    def selected_indices(self) -> List[int]:
        return [i for i, row in enumerate(self._rows) if row.checked()]

    def selected_groups(self) -> List[MeshGroup]:
        return [self._groups[i] for i in self.selected_indices()]

    def selected_entry_ids(self) -> List[str]:
        """Every solid the ticked units cover, in tree order.

        The host draws this set in the 3D view (View Mesh): the ticks say what
        the panel is working on, and looking at what one is working on is the
        same question, so it is the same answer.
        """
        ids: List[str] = []
        for g in self.selected_groups():
            ids.extend(g.entry_ids)
        return ids

    def _kept_groups(self) -> List[MeshGroup]:
        sel = set(self.selected_indices())
        return [g for g in self._groups if g.index not in sel]

    def _on_row_toggled(self, _index: int, _on: bool):
        if self._loading:
            return
        # A tick is scope, not an edit target: the block stays on the row it is
        # on, which is the whole point of splitting the two. Only the first tick
        # on an open panel moves it, because it opens with nothing to edit yet.
        self._resolve_current()
        self._load_params_for_current()
        self._refresh_all()

    def _on_row_activated(self, index: int):
        if 0 <= index < len(self._groups):
            self.group_activated.emit(self._groups[index])

    # ----------------------------------------------------------------
    # Parameters
    # ----------------------------------------------------------------

    def params_for(self, group: MeshGroup) -> Dict[str, Any]:
        """The values `group` will be meshed with. Its own, not the panel's."""
        return dict(self._unit_params[group_key(group.entry_ids)])

    def _meshed_record(self, unit: MeshGroup) -> Optional[dict]:
        """The values the mesh *of this unit* was made with, or None.

        Its own member set only -- never the parts' records, however well those
        agree. A unit with contact faces is meshed as one job, and a per-solid
        run leaves the other mesh: a facet set of its own on every shared face,
        which is the mesh the unit exists to replace
        (doc/assembly_fragment_gdml.md §1). Letting the parts stand in for it
        would report a unit that has just been regrouped as already meshed, and
        the panel would offer nothing for the run the regroup made necessary.
        """
        return self._meshed_params.get(group_key(unit.entry_ids))

    def _parts_record(self, unit: MeshGroup) -> Optional[dict]:
        """What every part of `unit` was meshed with, when they all agree.

        The other half of what the records answer: which numbers the unit opens
        on, not whether it is meshed. A per-solid run's values are the ones the
        user typed for these parts, so a regrouped unit starts from them and the
        changed-field markers stay quiet -- while _meshed_record() leaves the
        unit with a job to do.
        """
        if not unit.coupled:
            return None
        per_part = [self._meshed_params.get((eid,)) for eid in unit.entry_ids]
        if all(per_part) and all(_same_params(per_part[0], p) for p in per_part):
            return per_part[0]
        return None

    def shared_params(self) -> Dict[str, Any]:
        """The set a run header can show: the first ticked group's.

        One set is all a header has room for. The per-group sets are in plan(),
        and the log takes them one line per job.
        """
        sel = self.selected_indices()
        if not sel:
            return dict(self._defaults)
        return self.params_for(self._groups[sel[0]])

    def reused_groups(self) -> List[MeshGroup]:
        """Ticked groups this run keeps instead of meshing -- see _reused()."""
        return [g for g in self.selected_groups() if self._reused(g)]

    def _source_of(self, group: MeshGroup) -> bool:
        """Was every part's current file written by *this* unit's job?

        The other half of the reuse test, and the one that keeps the two kinds
        of mesh apart. A record says a unit was meshed with certain values; it
        does not say the file a part holds is still that job's, because both
        kinds of run write the same part's file: an assembly run replaces every
        member's mesh with its own fragment of the shared facets. Switching from
        per-solid to assembly and back would otherwise find the per-solid records
        intact, all six numbers equal, and reuse them for the per-solid mesh --
        except the facets in place are the assembly's, cut into the parts. That
        is one model holding the facets of two modes, and the very thing the
        assembly mesh exists to remove.

        With no provenance at all (a caller that passes no `source`) the test is
        skipped: the same conservatism as an unrecorded mesh is not read as a
        reuse, but a panel that cannot know must not refuse every reuse either.
        """
        if not self._mesh_source:
            return True
        key = group_key(group.entry_ids)
        return all(self._mesh_source.get(eid) == key for eid in group.entry_ids)

    def _reused(self, group: MeshGroup) -> bool:
        """Does `group` already hold the mesh these values would produce?

        The comparison the changed-field markers show, over the record of the
        unit's *own* mesh: a group whose values are the ones its mesh was made
        with has nothing to redo, and running gmsh again for the facets it
        already has only costs time. The parts' records do not count here, so a
        unit that has just been regrouped is never reused on the strength of the
        per-solid mesh it is meant to replace (_meshed_record). A group whose run
        failed has no recorded mesh, so it is never reused by accident. Neither
        does a record whose mesh is no longer on the parts it describes: that is
        what _source_of() answers, and it is asked after the values, because a
        value edit is a re-mesh whatever the provenance says.
        """
        record = self._meshed_record(group)
        if record is None:
            return False
        if not self._source_of(group):
            return False
        # The mode is the one value compared as it *resolves*, not as it is
        # written: "auto" and the mode this unit would take anyway are the same
        # mesh, so a record that spells out "per_solid" for a part with no contact
        # faces must not read as a change and buy it a re-mesh it does not need.
        # The six numbers are compared as written, which is where a real edit
        # shows up.
        want = self.params_for(group)
        return _same_params(
            dict(record, mode=resolved_mode(group, record)),
            dict(want, mode=resolved_mode(group, want)))

    def _planned_groups(self) -> List[MeshGroup]:
        """The ticked groups with something to do: what the run will mesh."""
        return [g for g in self.selected_groups() if not self._reused(g)]

    def _load_params_for_current(self):
        """Point the one editor at the current row.

        A form can display one set at a time, and now it writes that one set too:
        the tick says which units this run meshes, the click says which unit these
        numbers are for. The baseline is that unit's own existing mesh, so a marked
        field means "this unit is re-meshed because of me", which is the reuse rule
        drawn on the form.
        """
        idx = self.current_index()
        self._params.setEnabled(idx is not None)
        if idx is None:
            return
        target = self._groups[idx]
        own = self._meshed_record(target)
        made_with = own or self._parts_record(target)
        # Whose mesh the marks are measured against, in the words the row uses:
        # the unit's own when its own job made it, the parts' when they were
        # meshed one by one and the unit is a regrouping of them. Both are "the
        # numbers it opens on"; only the first is a mesh the unit still has, and
        # the two must not read alike (_meshed_record).
        note = ("its current mesh" if own else
                "its parts' meshes" if made_with else "")
        self._params.set_params(self.params_for(target))
        self._params.set_baseline(_to_run_keys(made_with) if made_with else None,
                                  note=note)

    def _on_params_edited(self, key: str = ""):
        """The one editor moved a field: give it to every selected unit.

        Field by field on purpose. The block stands for the whole selection --
        which is what ctrl- and shift-click built it for -- so an edit belongs to
        all of it, but only in the field that moved. A selection is regularly a
        set of units that differ in the others (one solid meshed finer, the rest
        on the defaults), and copying the whole form onto each of them would
        quietly overwrite the numbers nobody asked about. The current row takes
        the whole form: the form *is* that row's values.
        """
        values = self._params.params()
        idx = self.current_index()
        if idx is not None:
            for i in (self.selected_indices() or [idx]):
                params = self._unit_params[group_key(self._groups[i].entry_ids)]
                if i == idx:
                    params.update(values)
                elif key and key != "mode":
                    # The mode is not one unit's business; the block below hands
                    # it to the whole panel.
                    params[key] = values[key]
        # The mode is one of these values, but it is not one unit's business: it
        # decides what a unit *is* (a whole group or one solid of it), so a new
        # one is adopted by the whole panel -- that is what makes the rows and the
        # chip agree with the mode the run will use -- and the rows are rebuilt
        # for it before anything reads them.
        if values["mode"] != self._mode_choice:
            self._mode_choice = values["mode"]
            for params in self._unit_params.values():
                params["mode"] = self._mode_choice
            self._sync_units()
        self._refresh_all()

    # ----------------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------------

    def _refresh_all(self):
        self._refresh_rows()
        self._refresh_active()
        self._refresh_params_rule()
        self._refresh_footer()
        # The band's state line is about the grouping, and a mode edit is what
        # changes the grouping the rows are built along (_grouping_state).
        self._refresh_contact_notice()

    def _refresh_active(self):
        """Draw the accent edge on the row the parameters belong to."""
        idx = self.current_index()
        for i, row in enumerate(self._rows):
            row.set_active(i == idx)

    def _refresh_params_rule(self):
        """`Mesh parameters · <unit>`, plus how many more the edit reaches.

        The unit name is the one thing the block must say -- with per-unit values
        the reader cannot see anywhere else which unit these numbers belong to --
        and the count beside it is the other thing they cannot see: the block
        shows one row and writes to every ticked one. It is re-read here rather
        than at the edit, because a rebuild can move which row is current.
        """
        current = self.current_group()
        if current is None:
            self._params_rule_label.setText("Mesh parameters")
            return
        extra = len(self.selected_indices()) - 1
        self._params_rule_label.setText(
            f"Mesh parameters · {current.label}" if extra <= 0
            else f"Mesh parameters · {current.label} +{extra} more")

    def _refresh_rows(self):
        """Re-chip and re-tooltip the rows: the parameters in them just changed.

        The chip follows the resolved mode, not the coupling: forcing per-solid on
        a coupled group is a real choice, and the row has to say what the run will
        do rather than what the group would have preferred.
        """
        for row, g in zip(self._rows, self._groups):
            mode = resolved_mode(g, self.params_for(g))
            row.set_mode(mode, mode != g.mode)
            row.set_tooltip(self._row_tooltip(g))

    def _refresh_footer(self):
        """The buttons' state, and which of them the ticks and the run allow.

        The run button is a promise about the *next* run, and once every ticked
        unit is meshed with the values it holds there is no next run to make --
        until a number is edited, at which point it comes back. View Mesh stands
        next to it whenever there is a mesh at all, because the ticks are also
        how the 3D view is aimed: ticking three solids to look at the three of
        them is the same selection a run would work on, and taking the button
        away whenever some *other* ticked unit has work left would make the
        subset unviewable exactly when it is being worked on. Check contacts
        stands beside them in every state: it is about the model, not about a
        run, and it is the one thing to reach for when the grouping itself is in
        doubt.

        Grey is the answer to "can this be pressed": a session in flight leaves
        all of them on screen, and the colour is the only thing that says which
        of them is waiting for it.
        """
        planned = self._planned_groups()
        n_parts = sum(g.n_parts for g in planned)
        self._view_btn.setVisible(self._has_mesh)
        self._rollback_btn.setVisible(self._rollback_run_no is not None)
        # While a session is in flight the strip offers Cancel and nothing else,
        # which is the rule the toolbar already follows: the others either start
        # a second session or rewrite what the first one is writing into. The
        # re-check has a wait of its own on top of that: while the analysis it
        # would restart is running there is nothing to re-run.
        for btn in (self._view_btn, self._rollback_btn):
            btn.setEnabled(not self._running)
        self._recheck_btn.setEnabled(
            not self._running and self._contact_state != "running")
        self._ok_btn.setVisible(bool(planned))
        self._ok_btn.setEnabled(bool(self.selected_indices())
                               and not self._running)
        if not planned:
            return
        if self._first_run:
            self._ok_btn.setText(f"Mesh {n_parts} part(s)")
        else:
            self._ok_btn.setText(f"Re-mesh {n_parts} part(s)")

    # ----------------------------------------------------------------
    # Progress
    # ----------------------------------------------------------------

    # Called by the host while a session runs under this panel, and by nothing
    # else: the panel never asks a runner anything. Nothing here writes the bar
    # widget directly either -- every writer is a value of its own wait, and
    # _refresh_status is the one place that moves the bar to the owner's.

    def start_run(self, run_no: int, scope_text: str = ""):
        """A run was accepted here: reset the bar and lock the button.

        Locked because there is one session at a time, and this is the button
        that would start a second one. The panel is not closed -- it is the
        progress window now -- and a rerun is the same button once this one ends.

        Reset also takes the bar off the contact analysis, which may have been
        showing there: the run just asked for is the wait to watch, and a landed
        check is a reading that can wait its turn.

        This is also what commits the rows: from here on they are the units a
        run is reported against, and a contact analysis landing afterwards is
        offered instead of applied (_rows_committed, set_components).
        """
        self._run_no = run_no
        self._running = True
        self._rows_committed = True
        self._stages = []
        self._stage = -1
        self._elapsed = None
        self._idle = None
        self._status_text = f"run #{run_no}"
        if scope_text:
            self._status_text += f" · {scope_text}"
        self._run_value = 0
        self._bar_owner = "run"
        self._refresh_status()
        self._refresh_footer()
        # The notice's offer is a button, and buttons follow the strip's rule:
        # off while a session runs.
        self._refresh_contact_notice()

    def set_progress(self, value: int, status: str = ""):
        """The bar, in percent of the whole session.

        The session, not the job: a three-group run would otherwise fill and
        empty the bar three times, which reads as three runs.
        """
        self._run_value = max(0, min(100, int(value)))
        if status:
            self._status_text = status
        self._refresh_status()

    def set_status(self, text: str):
        """Replace the line, leaving the bar where it is."""
        self._status_text = text
        self._refresh_status()

    def set_stages(self, labels: Sequence[str]):
        """The stages the run passes through, in assembly mode.

        One stage is not a list, it is the name of the job, so it goes on the
        line as the status instead of as a checklist of one item.
        """
        names = list(labels)
        self._stages = names if len(names) > 1 else []
        self._stage = 0 if self._stages else -1
        if len(names) == 1:
            self._status_text = names[0]
        self._refresh_status()

    def set_stage(self, index: int, message: str = ""):
        """Move the markers to stage `index`, and optionally say what it is on."""
        self._stage = index
        if message:
            self._status_text = message
        self._refresh_status()

    def set_heartbeat(self, elapsed: Optional[float],
                      idle: Optional[float] = None):
        """How long the run has been going, and how long since gmsh last spoke.

        The second number is the point: a bar that has not moved in two minutes
        is only explained by a silent solver if the silence is on screen.
        """
        self._elapsed = elapsed
        self._idle = idle
        self._refresh_status()

    def finish_run(self, text: str, completed: bool):
        """The session ended -- successfully or not -- and its last line stays.

        The bar follows the session's own rule, the same one the status bar
        follows, because the two bars are read as one reading: full only when
        the session ran to the end, and back to zero when it was stopped, since
        a cancelled session has no finished work to show a bar for -- and the
        contact analysis reads its verdict by the same rule (set_contact_state).
        What happened is in the line, and in the log.
        """
        self._running = False
        self._stages = []
        self._stage = -1
        self._elapsed = None
        self._idle = None
        self._status_text = text
        self._run_value = 100 if completed else 0
        self._refresh_status()
        self._refresh_footer()
        self._refresh_contact_notice()

    def adopt_run(self, meshed_params: Dict[Tuple[str, ...], dict],
                  source: Optional[Dict[str, Tuple[str, ...]]] = None):
        """Take a finished run's records as this panel's picture of the model.

        The panel outlives the run now, so it has to be told what the run
        produced. Without this it would keep planning the run that has just
        finished -- and press again would re-mesh every unit all over again --
        and the changed-field markers would stay lit on the values the run used.

        The provenance comes with the records (see _source_of): a run that
        replaced per-solid meshes with an assembly one leaves the per-solid
        records in place, and the panel has to be told which job the files on the
        parts actually came from -- otherwise the next press would read those
        records, find the numbers unchanged, and keep fragments for a mesh the
        mode no longer asks for.
        """
        self._meshed_params = dict(meshed_params or {})
        if source is not None:
            self._mesh_source = dict(source)
        self._first_run = self._first_run and not self._meshed_params
        self._load_params_for_current()
        self._refresh_all()

    def set_view_mesh_available(self, available: bool):
        """Is there a mesh to look at? A fact about the model, not about a run:
        a failed run must not take the previous preview away."""
        self._has_mesh = bool(available)
        self._refresh_footer()

    def show_rollback(self, run_no: int):
        """Offer the way back to the run before the one that just failed."""
        self._rollback_run_no = run_no
        self._rollback_btn.setText(f"Roll back to #{run_no}")
        self._refresh_footer()

    def hide_rollback(self):
        self._rollback_run_no = None
        self._refresh_footer()

    def _refresh_status(self):
        """Two rows: the stages of the run above, the step it is on below.

        Two rows and not one: the two of them together are wider than the panel
        as soon as the step name is long, and a row that wraps mid-run takes the
        panel's height with it.

        The one bar moves to whichever wait owns it (_bar_owner), and every
        writer hands it a value instead of setting it: a session owns it from
        the press of Mesh, a re-check from the press of Check contacts, and
        each keeps its own percentage and its own line, so neither can leave the
        other's number or step on screen. The analysis the host runs by itself
        owns nothing here -- it is not a wait this panel started -- so a panel
        open across one still reads its own last run, or zero and idle.

        The stages and the heartbeat belong to a session alone -- the analysis
        has no checklist and no solver that can fall silent -- so the re-check's
        turn shows the bar and its step, and leaves the row above it standing
        empty (_BLANK_ROW). Neither row is ever dropped from the layout: what
        the bar is saying may change, the height of what says it may not.
        """
        if self._bar_owner == "contact":
            self._progress_bar.setValue(self._contact_value)
            self._stage_label.setText(_BLANK_ROW)
            self._progress_label.setText(self._contact_status or _BLANK_ROW)
            return

        self._progress_bar.setValue(self._run_value)
        marks = "　".join(f"{'●' if i <= self._stage else '○'} {name}"
                         for i, name in enumerate(self._stages))
        self._stage_label.setText(marks or _BLANK_ROW)

        text = self._status_text or "Idle"
        if self._elapsed is not None:
            text += f" · {_fmt_duration(self._elapsed)}"
            if self._idle is not None:
                # gmsh prints nothing for long stretches while it works, so a
                # silent job is only alarming once it is stated as a duration.
                text += (" · solver working" if self._idle < 2
                         else f" · quiet for {int(self._idle)} s")
        self._progress_label.setText(text)

    # ----------------------------------------------------------------
    # Result
    # ----------------------------------------------------------------

    def plan(self) -> List[Tuple[MeshGroup, Dict[str, Any]]]:
        """One (group, params) job per ticked group that has something to do.

        Per group, not one job for everything: a job is either an assembly
        fragment or a per-solid run, so a selection holding both has to be split
        anyway, and on a re-mesh each group's result has to land on its own. The
        ticked groups whose values did not change are left out -- they keep the
        mesh they have, which is what `reused_groups()` names.
        """
        return [(g, self.params_for(g)) for g in self._planned_groups()]

    def get_descriptive_summary(self) -> str:
        """The scope header for this run, for the system log."""
        return scope_text(self.selected_groups(), self._kept_groups())


def _same_params(a: Optional[dict], b: Optional[dict]) -> bool:
    """Do two parameter sets mean the same mesh?

    Floats are compared with a tolerance because the spin boxes round to two
    decimals: 6.00 read back out of a QDoubleSpinBox is not always the bit-exact
    double that went in, and "the values did not change" must not depend on that.
    """
    if not a or not b:
        return False
    for key in set(a) | set(b):
        x, y = a.get(key), b.get(key)
        if isinstance(x, float) or isinstance(y, float):
            if abs(float(x or 0.0) - float(y or 0.0)) > 1e-6:
                return False
        elif x != y:
            return False
    return True


def _to_run_keys(p: dict) -> Dict[str, Any]:
    """`params()` spelling -> the spelling MeshParamsWidget.values() returns.

    set_baseline() diffs against its own keys (min_factor, order), so the "what
    did this have before?" snapshot has to be in that spelling, otherwise the
    changed-field markers would compare a key against nothing and stay silent.
    """
    return {
        "algorithm": p["algorithm"],
        "elem_factor": p["elem_factor"],
        "min_factor": p["mesh_min_factor"],
        "max_factor": p["mesh_max_factor"],
        "smoothing": p["smoothing"],
        "order": p["element_order"],
        "mode": p["mode"],
    }
