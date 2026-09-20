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
fields -- and what it writes belongs to the *current* row: the one that was
clicked. The click and the tick are two different questions and they are answered
separately:

  - the tick is the scope of the run: "mesh this unit";
  - the click is the scope of the editor: "these numbers are this unit's".

So a solid can be given its own values without unticking the rest, which is what
makes a per-solid model worth looking at: the whole point of splitting a group is
that one part needs a finer mesh. The old behaviour -- one edit, every ticked unit
-- is still one click away, on `Apply to all ticked`, because it is genuinely the
fast way to give a whole model one set of numbers. It just says so now.

The block marks the fields that differ from the mesh its unit already has, which
is exactly the set a run will re-mesh.

The one value that is not per unit is the mode: auto / assembly / per-solid
decides what a unit *is* (a whole group, or one solid of it), so it is adopted by
the whole panel and rebuilds the rows when it changes.

Double-clicking a row highlights that group's solids in the 3D view, so the row
can stay one line however big the model gets.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from mesh.gmsh_dialog import (
    MODE_ASSEMBLY, MODE_AUTO, MODE_PER_SOLID, MeshParamsWidget,
    _PER_SOLID_SECONDS, _fmt_duration, estimate_seconds, merge_defaults,
    panel_palette, section_rule,
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

    Clicking emits `clicked`: the row is not just a tick any more, it is also how
    the parameter block below is aimed at one unit instead of at everything
    ticked. Double-click emits `activated` so the host can open the group on its
    own. The panel lists groups, not parts, and "Group A · 3 part(s)" is not an
    answer to "which three?" -- so the answer has to live somewhere, and the row
    stays one line.

    `title` / `count` override the two labels: in per-solid mode the row is one
    solid and is called by its name, with the group it belongs to where the part
    count sits.
    """

    toggled = pyqtSignal(int, bool)
    activated = pyqtSignal(int)
    clicked = pyqtSignal(int)

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
            "Ticked groups are meshed; an unticked one keeps the mesh it has.")
        lay.addWidget(self._check, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title = QLabel(title or f"Group {group.letter}")
        self._count = QLabel(count or f"{group.n_parts} part(s)")
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
        """Is this the row the parameter block is editing right now?

        The tick and the active row are two different questions -- "mesh this" and
        "edit this" -- so they get two different marks: the checkbox for the first,
        this accent edge for the second.
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
        """A single click makes this the row the parameters are edited for.

        Not a selection model and not a QListWidget: the point of the click is
        only that the one parameter block below stops writing to everything
        ticked and starts writing to one unit.
        """
        self.clicked.emit(self._index)
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

    def __init__(self, groups: Sequence[MeshGroup],
                 nodes: Sequence = (),
                 initial_params: Optional[dict] = None,
                 dark: bool = False,
                 first_run: bool = False,
                 last_run: Optional[dict] = None,
                 preselect: Optional[Sequence[int]] = None,
                 meshed_params: Optional[Dict[Tuple[str, ...], dict]] = None,
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
        self._last_run = last_run or None

        # What each group's existing mesh was made with, keyed by its member set
        # (see scope.group_key). The opening values, the baseline of the
        # changed-field markers and the reuse test all read this one dict.
        self._meshed_params: Dict[Tuple[str, ...], dict] = dict(meshed_params or {})
        self._defaults: Dict[str, Any] = merge_defaults(initial_params)
        # Which row the parameter block edits (an index into _groups), and the
        # mode the panel is set to. The mode is not one unit's business -- it
        # decides what a unit *is* (a whole group or one solid of it), so it is a
        # property of the panel while the six numbers are properties of the row.
        self._current: Optional[int] = None
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

        A component reads the record of its own mesh, a solid its own record
        when it has one. A per-solid run leaves the records per solid, so
        reading those back is the only way a solid's own numbers survive a
        re-open -- without it the whole component falls back to the panel's
        defaults and every solid is shown the first one's values, which then
        reads as "everything changed" against meshes that did not.

        Keys that are already there are left alone: this runs again when a
        late contact analysis hands the panel new components (set_components),
        and what the user typed in the meantime has to outlive that.
        """
        for comp in self._components:
            key = group_key(comp.entry_ids)
            if key not in self._unit_params:
                self._unit_params[key] = dict(
                    self._meshed_params.get(key) or self._defaults)
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
        """
        new = list(groups)
        if [group_key(g.entry_ids) for g in new] == \
                [group_key(g.entry_ids) for g in self._components]:
            return False
        ticked = {eid for i in self.selected_indices()
                  for eid in self._groups[i].entry_ids}
        was = self.current_index()
        unit_key = (group_key(self._groups[was].entry_ids)
                    if was is not None else None)
        self._components = new
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
        return True

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

    def _build_footer(self) -> QWidget:
        """The summary line and the buttons, as one strip (`.mkf`)."""
        p = self._pal
        foot = QFrame()
        foot.setObjectName("scopeFoot")
        f = QHBoxLayout(foot)
        f.setContentsMargins(11, 9, 11, 9)
        f.setSpacing(9)
        self._foot_label = QLabel()
        self._foot_label.setWordWrap(True)
        self._foot_label.setTextFormat(Qt.TextFormat.RichText)
        f.addWidget(self._foot_label, 1)

        cancel = self._plain("Cancel")
        cancel.clicked.connect(self.reject)
        f.addWidget(cancel)
        self._ok_btn = self._primary()
        self._ok_btn.clicked.connect(self.accept)
        f.addWidget(self._ok_btn)

        foot.setStyleSheet(
            f"#scopeFoot {{ background: {p['foot_bg']};"
            f" border-top: 1px solid {p['foot_border']}; }}"
            f" #scopeFoot QLabel {{ background: transparent; border: none;"
            f" color: {p['foot_text']}; font-size: 11.5px; }}")
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
        p = self._pal
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(25)
        b.setStyleSheet(
            f"QPushButton {{ background: {p['btn_bg']};"
            f" border: 1px solid {p['btn_border']}; border-radius: 6px;"
            f" color: {p['btn_text']}; padding: 3px 13px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {p['pri_bg']};"
            f" color: {p['pri_bg']}; }}")
        return b

    def _primary(self) -> QPushButton:
        p = self._pal
        b = QPushButton()
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(25)
        b.setDefault(True)
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
        """`Mesh parameters · <unit>` plus the copy-to-everything shortcut.

        The rule is *not* a constant, unlike Advanced: with per-unit values the
        one thing the reader cannot see anywhere else is which unit these numbers
        belong to. It changes on a click, never on a tick, so it does not drift
        under an edit. The shortcut next to it is the other half of the same
        truth: writing one row is the default now, and writing all the ticked
        ones is the button that says so.
        """
        row = section_rule("Mesh parameters")
        self._params_rule_label = row.findChildren(QLabel)[0]
        self._apply_btn = self._ghost("Apply to all ticked")
        self._apply_btn.clicked.connect(self._apply_to_ticked)
        row.layout().addWidget(self._apply_btn)
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
        else:
            state = ""
        return (f"{members}\n\n{self._full_params_text(self.params_for(g))}"
                f"{state}\n\nClick to set these values.\n"
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
        if unit.name:
            title = unit.name
            count = f"part of {self._component_of(unit).label}"
        else:
            title = ""
            count = ""
        row = _GroupRow(index, unit, self._pal, title=title, count=count,
                        parent=holder)
        row.toggled.connect(self._on_row_toggled)
        row.activated.connect(self._on_row_activated)
        row.clicked.connect(self._set_current)
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
        wanted = {int(i) for i in indices}
        self._loading = True
        try:
            for i, row in enumerate(self._rows):
                row.set_checked(i in wanted)
        finally:
            self._loading = False
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

    def _set_current(self, index: int):
        """Edit *this* row: the click, not the tick, decides what is written."""
        if not (0 <= index < len(self._groups)):
            return
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
        """The values the mesh covering `unit` was made with, or None.

        A group mesh is recorded per group and a per-solid one per part, so a
        component is also covered when *every* one of its parts carries its own
        record with the same values -- which is exactly what a forced per-solid
        run leaves behind. Without this, an A/B run would make the panel report
        the whole model as unmeshed the next time it is opened.
        """
        own = self._meshed_params.get(group_key(unit.entry_ids))
        if own:
            return own
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

    def _reused(self, group: MeshGroup) -> bool:
        """Does `group` already hold the mesh these values would produce?

        The same comparison the changed-field markers show: a group whose values
        are the ones its mesh was made with has nothing to redo, and running gmsh
        again for the facets it already has only costs time. A group whose run
        failed has no recorded mesh, so it is never reused by accident.
        """
        record = self._meshed_record(group)
        if record is None:
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
        made_with = self._meshed_record(target)
        self._params.set_params(self.params_for(target))
        self._params.set_baseline(_to_run_keys(made_with) if made_with else None,
                                  note="its current mesh" if made_with else "")

    def _on_params_edited(self):
        values = self._params.params()
        idx = self.current_index()
        if idx is not None:
            self._unit_params[group_key(self._groups[idx].entry_ids)] = dict(values)
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

    def _apply_to_ticked(self):
        """Copy the current row's values onto every ticked row.

        This is what an edit used to do by itself, and it is still the fast way to
        give a whole model one set of numbers -- but as a button that says it,
        because the implicit version made "give this one solid its own values"
        impossible without unticking everything else.
        """
        idx = self.current_index()
        if idx is None:
            return
        values = self.params_for(self._groups[idx])
        for i in self.selected_indices():
            key = group_key(self._groups[i].entry_ids)
            self._unit_params[key] = dict(values)
        # The marks are measured against each unit's own mesh, so they have to be
        # re-read: the unit being edited is one of the ones that just changed.
        self._load_params_for_current()
        self._refresh_all()

    # ----------------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------------

    def _refresh_all(self):
        self._refresh_rows()
        self._refresh_active()
        self._refresh_params_rule()
        self._refresh_footer()

    def _refresh_active(self):
        """Draw the accent edge on the row the parameters belong to."""
        idx = self.current_index()
        for i, row in enumerate(self._rows):
            row.set_active(i == idx)

    def _refresh_params_rule(self):
        """`Mesh parameters · <unit>`, and the copy-to-all shortcut with it.

        The unit name is the one thing the block must say: it used to write every
        ticked row, so it did not have to name any row. It is re-read here rather
        than at the edit, because a rebuild can move which row is current.
        """
        current = self.current_group()
        self._params_rule_label.setText(
            f"Mesh parameters · {current.label}" if current
            else "Mesh parameters")
        n = len(self.selected_indices())
        self._apply_btn.setText(f"Apply to all ticked ({n})")
        self._apply_btn.setEnabled(current is not None and n > 0)

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

    def _estimate_seconds(self) -> Optional[float]:
        """Rough duration for what this run will actually mesh.

        Summed over the planned groups, each with its own values, not one ratio
        over the whole selection: a scoped re-mesh halves the work of a full one,
        and groups already meshed add nothing to it.
        """
        groups = self._planned_groups()
        if not groups:
            return None
        total = 0.0
        for g in groups:
            secs = estimate_seconds(self.params_for(g), g.n_parts, self._last_run)
            total += secs if secs is not None else _PER_SOLID_SECONDS * g.n_parts
        return total

    def _unit_noun(self) -> str:
        """What a row is in this mode: a group, or one solid shown per-solid."""
        return "part" if self._per_solid else "group"

    def _footer_text(self) -> str:
        """One line: what will be meshed, what will not, and how long.

        The same sentence the system log will open this run with, so the header
        the user reads afterwards is one they have already seen here.
        """
        planned = self._planned_groups()
        reused = self.reused_groups()
        kept = self._kept_groups()
        noun = self._unit_noun()
        ink = self._pal["foot_ink"]
        head = f'<b style="color:{ink}">{len(planned)} {noun}(s)'
        # In per-solid mode the unit *is* a part, and "5 part(s) · 5 part(s)" is
        # the same number said twice. The part count only carries news when a row
        # can be a whole group.
        if noun != "part":
            head += f' · {sum(g.n_parts for g in planned)} part(s)'
        head += "</b>"
        if reused or kept:
            why = []
            if kept:
                why.append(f"{len(kept)} unticked")
            if reused:
                why.append(f"{len(reused)} already meshed with these values")
            head += (f'　·　keep {len(reused) + len(kept)} {noun}(s) '
                     f'({", ".join(why)})')
        secs = self._estimate_seconds()
        if secs is None:
            head += ("　·　nothing to mesh, the ticks already match the meshes"
                     if self.selected_indices()
                     else f"　·　no {noun} ticked, the model stays as it is")
        else:
            head += f"　·　estimated ≈ {_fmt_duration(secs)}"
        return head

    def _refresh_footer(self):
        """The summary line and the one button that starts the run.

        Nothing to mesh means neither, so the strip falls back to Cancel alone:
        "0 group(s) · nothing to mesh" only restates the ticks, and a Close
        button next to Cancel was the same way out offered twice. The line is
        emptied rather than hidden so it keeps pushing the buttons right.
        """
        planned = self._planned_groups()
        n_parts = sum(g.n_parts for g in planned)
        self._foot_label.setText(self._footer_text() if planned else "")
        self._ok_btn.setVisible(bool(planned))
        if not planned:
            return
        self._ok_btn.setEnabled(bool(self.selected_indices()))
        if self._first_run:
            self._ok_btn.setText(f"Mesh {n_parts} part(s)")
        else:
            self._ok_btn.setText(f"Re-mesh {n_parts} part(s)")

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
