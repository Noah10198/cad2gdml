"""
gmsh_dialog.py -- the GMSH parameter rows, and the helpers around them.

The six parameter rows (algorithm, element size factor, mesh min/max factor,
smoothing, element order) plus the mode selector, as one widget. There is no
dialog in this module any more: GmshDialog existed to collect the parameters
*and* the scope, but the scope it could express was degenerate -- on a first run
every part has to be meshed -- which made the two dialogs one state space with
two front ends. The single panel is mesh/remesh_scope_dialog.py. The two used to
be held together only by sharing this widget; with one front end there is
nothing left to hold together.

It stays a widget of its own rather than being folded into that panel because
the parameters are a self-contained object there: the panel points one editor at
several targets (all selected groups, or a single group), so moving the editor
has to save what was typed -- see set_params().

The widget owns three things the panel must not re-derive:
  - the defaults, in DEFAULT_PARAMS, in the one spelling that round-trips;
  - the tooltips (the factors are divisors, not element sizes);
  - the changed-value markers, which compare against a baseline, so "what am I
    actually changing?" is answered before the run instead of by diffing the
    product afterwards.
"""

from typing import Any, Dict, Optional

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QComboBox,
    QDoubleSpinBox, QSpinBox,
    QFrame, QWidget, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal

MODE_AUTO = "auto"
MODE_ASSEMBLY = "assembly"
MODE_PER_SOLID = "per_solid"

# The values a fresh widget starts from, in the spelling MeshParamsWidget takes
# them in -- the same spelling MainWindow persists and hands back.
#
# One dict instead of the defaults scattered over the six `p.get(...)` calls
# below: "what is the default?" is now a question with a single answer, which
# matters because a *group* can carry its own parameter set. "This group has no
# values of its own" and "this group's values happen to equal the defaults" have
# to mean the same thing, and they only do if there is one definition.
DEFAULT_PARAMS: Dict[str, Any] = {
    "algorithm": "Frontal-Delaunay",
    "elem_factor": 1.0,
    "mesh_min_factor": 6.0,
    "mesh_max_factor": 5.0,
    "smoothing": 1,
    "element_order": 1,
    "mode": MODE_AUTO,
}

def merge_defaults(params: Optional[dict] = None) -> Dict[str, Any]:
    """`params` on top of DEFAULT_PARAMS, so every key is always present."""
    merged = dict(DEFAULT_PARAMS)
    merged.update(params or {})
    return merged


def _fmt_duration(seconds: float) -> str:
    """242 -> '4 min 02 s', the same shape the progress dialog uses."""
    total = int(round(seconds))
    return f"{total // 60} min {total % 60:02d} s"


def panel_palette(dark: bool = False) -> Dict[str, str]:
    """The scope panel's colours, in one place, for both of its modules.

    Named by role, not by hue: the panel is a card with a header strip, group
    rows that read as on/off, and a footer strip, and those roles have to keep
    their relationships in either theme. The light column is lifted from
    doc/remesh_scope_mockup.html §2 (`.mk` / `.mkh` / `.sr` / `.chip` / `.mkf`);
    the dark column is the same roles re-picked
    against the mockup's own dark log block (#181825 / #313244 / #45475a), not a
    second design.
    """
    if dark:
        pairs = {
            "card_bg": "#1e1e2e", "card_border": "#313244",
            "head_bg": "#181825", "head_border": "#313244",
            "head_text": "#a6adc8", "head_dim": "#6c7086",
            "section_text": "#7f849c",
            "row_bg": "#1e1e2e", "row_border": "#313244",
            "row_on_bg": "#1e2536", "row_on_border": "#3b5378",
            "row_off_bg": "#181825", "row_off_border": "#262637",
            "row_sel_bg": "#1b2437", "row_sel_border": "#3b82f6",
            "title": "#cdd6f4", "title_off": "#6c7086", "count": "#9399b2",
            "conform_border": "#2d5f4a", "conform_bg": "#1b3a30",
            "conform_text": "#a6e3a1",
            "indep_border": "#4a3f6b", "indep_bg": "#2a2440",
            "indep_text": "#cba6f7",
            "foot_bg": "#181825", "foot_border": "#313244",
            "foot_text": "#a6adc8", "foot_ink": "#cdd6f4",
            "field_bg": "#313244", "field_border": "#45475a",
            "field_text": "#cdd6f4", "label": "#9399b2",
            "changed_bg": "#3a3320", "changed_border": "#f9e2af",
            "btn_bg": "#313244", "btn_border": "#45475a", "btn_text": "#cdd6f4",
            "pri_bg": "#2563eb", "pri_border": "#2563eb", "pri_text": "#ffffff",
        }
    else:
        pairs = {
            "card_bg": "#ffffff", "card_border": "#d8dee9",
            "head_bg": "#eef1f5", "head_border": "#d8dee9",
            "head_text": "#5a6473", "head_dim": "#8892a4",
            "section_text": "#94a3b8",
            "row_bg": "#ffffff", "row_border": "#e5e9f0",
            "row_on_bg": "#f8fbff", "row_on_border": "#bfdbfe",
            "row_off_bg": "#fafafa", "row_off_border": "#eceff3",
            "row_sel_bg": "#ffffff", "row_sel_border": "#2563eb",
            "title": "#0f172a", "title_off": "#94a3b8", "count": "#64748b",
            "conform_border": "#a7f3d0", "conform_bg": "#ecfdf5",
            "conform_text": "#059669",
            "indep_border": "#ddd6fe", "indep_bg": "#f5f3ff",
            "indep_text": "#7c3aed",
            "foot_bg": "#f8fafc", "foot_border": "#e5e9f0",
            "foot_text": "#475569", "foot_ink": "#0f172a",
            "field_bg": "#ffffff", "field_border": "#cbd5e1",
            "field_text": "#1e293b", "label": "#64748b",
            "changed_bg": "#fffdf5", "changed_border": "#f0a90a",
            "btn_bg": "#ffffff", "btn_border": "#cbd5e1", "btn_text": "#334155",
            "pri_bg": "#2563eb", "pri_border": "#2563eb", "pri_text": "#ffffff",
        }
    return pairs


# Tooltips for the two size-factor rows. The factor is a *divisor*, not a size:
# mesh_runner.py computes MeshSizeMin = bbox_diagonal / Mesh Min Factor and
# MeshSizeMax = bbox_diagonal / Mesh Max Factor, then writes both numbers into
# the .geo script as Mesh.MeshSizeMin / Mesh.MeshSizeMax.
MESH_MIN_FACTOR_TIP = (
    "Mesh Min Factor is a divisor, not an element size.\n"
    "\n"
    "MeshSizeMin = bbox_diagonal / Mesh Min Factor\n"
    "\n"
    "bbox_diagonal: diagonal of the bounding box, in model units\n"
    "  per-solid mode -> that solid's own bbox\n"
    "  assembly mode  -> the bbox of the whole merged assembly\n"
    "\n"
    "Larger factor -> smaller minimum element size.\n"
    "Default 6.00 -> MeshSizeMin = diagonal / 6 (about 16.7% of the diagonal)\n"
    "\n"
    "Note: MeshSizeMin <= MeshSizeMax requires Min Factor >= Max Factor,\n"
    "so the Min Factor must not be the smaller of the two.\n"
    "Default 6.00 / 5.00 keeps the range ordered: 16.7% <= 20% of the diagonal."
)

MESH_MAX_FACTOR_TIP = (
    "Mesh Max Factor is a divisor, not an element size.\n"
    "\n"
    "MeshSizeMax = bbox_diagonal / Mesh Max Factor\n"
    "\n"
    "bbox_diagonal: diagonal of the bounding box, in model units\n"
    "  per-solid mode -> that solid's own bbox\n"
    "  assembly mode  -> the bbox of the whole merged assembly\n"
    "\n"
    "Larger factor -> smaller maximum element size.\n"
    "Default 5.00 -> MeshSizeMax = diagonal / 5 (20% of the diagonal)\n"
    "\n"
    "Element Size Factor is a separate multiplier: it is written as\n"
    "Mesh.CharacteristicLengthFactor and scales the whole size range."
)


def field_qss(pal: Dict[str, str]) -> str:
    """The panel's input fields, plus the marker for an edited one.

    A property selector rather than a per-widget stylesheet: a widget-level
    stylesheet would drop the base rule the field needs to keep its shape, and
    then the marked field would be the only one without a border radius. The
    caller sets the `changed` property; `refresh_changed()` re-polishes.
    """
    f = ("background: {bg}; border: 1px solid {bd}; border-radius: 5px; "
         "padding: 1px 6px; color: {fg}; min-height: 23px;")
    base = f.format(bg=pal["field_bg"], bd=pal["field_border"],
                    fg=pal["field_text"])
    mark = f.format(bg=pal["changed_bg"], bd=pal["changed_border"],
                    fg=pal["field_text"])
    return (f"QComboBox, QDoubleSpinBox, QSpinBox {{ {base} }}\n"
            f'QComboBox[changed="true"], QDoubleSpinBox[changed="true"], '
            f'QSpinBox[changed="true"] {{ {mark} }}')


def section_rule(title: str) -> QWidget:
    """A title followed by a horizontal rule filling the remaining width.

    Module level rather than private to MeshParamsWidget because the scope panel
    separates its own sections the same way, and two implementations of "a rule
    with a name on it" is exactly the kind of drift that put the parameters in
    one widget to begin with.
    """
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    lab = QLabel(title)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    h.addWidget(lab)
    h.addWidget(line, 1)
    return row


class MeshParamsWidget(QWidget):
    """The six parameter rows plus the mode selector, on their own.

    Extracted from GmshDialog because the re-mesh scope panel
    (doc/remesh_scope_mockup.html §2) shows the very same rows: one definition
    means the tooltips and the changed-parameter highlighting cannot drift apart
    between the two dialogs.

    The changed-parameter highlighting is what makes a re-mesh comparable: after
    `set_baseline(prev_params)` any row whose value differs from the previous run
    gets a marker, so "what am I actually changing?" is answered before the run
    rather than by diffing the product afterwards.
    """

    # GMSH algorithm index mapping
    ALGORITHMS = {
        "MeshAdapt": 1,
        "Automatic": 2,
        "Delaunay": 5,
        "Frontal-Delaunay": 6,
    }

    # The keys `values()` returns, in display order.
    KEYS = ("algorithm", "elem_factor", "min_factor", "max_factor",
            "smoothing", "order")

    # Emitted on any user edit, not on refresh, carrying the key of the field
    # that was edited ("algorithm", "mode", ...). One editor can stand for
    # several rows (remesh_scope_dialog), and knowing which field moved is what
    # lets an edit reach them all without copying the fields nobody touched.
    changed = pyqtSignal(str)

    def __init__(self, initial_params: Optional[dict] = None,
                 dark: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._dark = dark
        self._pal = panel_palette(dark)
        self._baseline: Optional[Dict[str, Any]] = None
        self._baseline_note = ""
        self._labels: Dict[str, QLabel] = {}
        self._label_text: Dict[str, str] = {}
        self._fields_by_key: Dict[str, QWidget] = {}
        self._build(merge_defaults(initial_params))
        self.refresh_changed()

    # ---- Construction ----

    def _build(self, p: Dict[str, Any]):
        """The six rows. `p` is already merged over DEFAULT_PARAMS, so every key
        is present and the defaults are not spelled out a second time here."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.setStyleSheet(field_qss(self._pal))

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(9)

        def add(key: str, text: str, field: QWidget) -> QWidget:
            """A label above its field -- the mockup's `.pf` cell (`.pform`).

            Two rows of three instead of six form rows: the parameters share the
            panel with the scope list, and a right-aligned label column would
            spend a third of the width on punctuation. The grid position follows
            the call order, which is the order KEYS documents.
            """
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(3)
            cap = QLabel(text)
            # No font of its own: the caption reads exactly like the "Mode:"
            # label at the foot of the Advanced form, which is the only other
            # field label in this widget. The edited state is the one thing that
            # does style it -- see refresh_changed().
            v.addWidget(cap)
            v.addWidget(field)
            self._labels[key] = cap
            self._label_text[key] = text
            self._fields_by_key[key] = field
            r, c = divmod(len(self._fields_by_key) - 1, 3)
            grid.addWidget(box, r, c)
            return cap

        self._algo_combo = QComboBox()
        for name in self.ALGORITHMS:
            self._algo_combo.addItem(name)
        self._algo_combo.setToolTip(
            "MeshAdapt=1, Automatic=2, Delaunay=5, Frontal-Delaunay=6")
        add("algorithm", "Algorithm:", self._algo_combo)

        self._elem_factor_spin = QDoubleSpinBox()
        self._elem_factor_spin.setRange(0.01, 999999.0)
        self._elem_factor_spin.setSingleStep(0.1)
        self._elem_factor_spin.setDecimals(2)
        add("elem_factor", "Element Size Factor:", self._elem_factor_spin)

        self._min_factor_spin = QDoubleSpinBox()
        self._min_factor_spin.setRange(0.01, 999999.0)
        self._min_factor_spin.setSingleStep(0.5)
        self._min_factor_spin.setDecimals(2)
        self._min_factor_spin.setToolTip(MESH_MIN_FACTOR_TIP)
        add("min_factor", "Mesh Min Factor:", self._min_factor_spin)

        self._max_factor_spin = QDoubleSpinBox()
        self._max_factor_spin.setRange(0.01, 999999.0)
        self._max_factor_spin.setSingleStep(0.5)
        self._max_factor_spin.setDecimals(2)
        self._max_factor_spin.setToolTip(MESH_MAX_FACTOR_TIP)
        add("max_factor", "Mesh Max Factor:", self._max_factor_spin)

        self._smoothing_spin = QSpinBox()
        self._smoothing_spin.setRange(0, 100)
        add("smoothing", "Smoothing Steps:", self._smoothing_spin)

        self._order_combo = QComboBox()
        self._order_combo.addItem("1st Order", 1)
        self._order_combo.addItem("2nd Order", 2)
        add("order", "Element Order:", self._order_combo)

        for c in range(3):
            grid.setColumnStretch(c, 1)
        outer.addLayout(grid)
        outer.addSpacing(10)

        # ---- Advanced (always open, closed off by a section rule) ----
        # The mode selector lives here rather than out front: automatic selection
        # is good enough, and on the main form it would look mandatory.
        outer.addWidget(self._section_rule("Advanced"))

        adv = QWidget()
        adv_form = QFormLayout(adv)
        adv_form.setContentsMargins(18, 0, 0, 0)
        adv_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Auto (recommended)", MODE_AUTO)
        self._mode_combo.addItem("Force assembly conformal", MODE_ASSEMBLY)
        self._mode_combo.addItem("Force per-solid", MODE_PER_SOLID)
        adv_form.addRow("Mode:", self._mode_combo)
        outer.addWidget(adv)

        # Every field in one tuple: loading a parameter set is then the same
        # operation whatever the set is and wherever it came from.
        self._fields = (self._algo_combo, self._elem_factor_spin,
                        self._min_factor_spin, self._max_factor_spin,
                        self._smoothing_spin, self._order_combo,
                        self._mode_combo)
        self._apply_values(p)

        # User edits only: refresh_changed() must not re-enter through these.
        self._algo_combo.currentIndexChanged.connect(
            lambda *_: self._on_edited("algorithm"))
        self._elem_factor_spin.valueChanged.connect(
            lambda *_: self._on_edited("elem_factor"))
        self._min_factor_spin.valueChanged.connect(
            lambda *_: self._on_edited("mesh_min_factor"))
        self._max_factor_spin.valueChanged.connect(
            lambda *_: self._on_edited("mesh_max_factor"))
        self._smoothing_spin.valueChanged.connect(
            lambda *_: self._on_edited("smoothing"))
        self._order_combo.currentIndexChanged.connect(
            lambda *_: self._on_edited("element_order"))
        self._mode_combo.currentIndexChanged.connect(
            lambda *_: self._on_edited("mode"))

    def _apply_values(self, p: Dict[str, Any]):
        """Write `p` into the fields without emitting `changed`.

        Signals are *blocked*, not merely ignored. Loading is not an edit, and
        the scope panel depends on that: moving the editor from "all selected
        groups" to one group must not be recorded as a change to the values that
        were previously on screen.
        """
        for w in self._fields:
            w.blockSignals(True)
        try:
            idx = self._algo_combo.findText(str(p["algorithm"]))
            self._algo_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._elem_factor_spin.setValue(float(p["elem_factor"]))
            self._min_factor_spin.setValue(float(p["mesh_min_factor"]))
            self._max_factor_spin.setValue(float(p["mesh_max_factor"]))
            self._smoothing_spin.setValue(int(p["smoothing"]))
            self._order_combo.setCurrentIndex(max(0, int(p["element_order"]) - 1))
            mode_idx = self._mode_combo.findData(p["mode"])
            self._mode_combo.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        finally:
            for w in self._fields:
                w.blockSignals(False)

    def params(self) -> Dict[str, Any]:
        """The six parameters + mode in the spelling this widget accepts.

        `values()` is the run-time dict (min_factor / order); this is the
        round-trippable one, so a set can be read out, stored on a group and
        handed back to `set_params()` without any key renaming in between.
        """
        v = self.values()
        return {
            "algorithm": v["algorithm"],
            "elem_factor": v["elem_factor"],
            "mesh_min_factor": v["min_factor"],
            "mesh_max_factor": v["max_factor"],
            "smoothing": v["smoothing"],
            "element_order": v["order"],
            "mode": v["mode"],
        }

    def set_params(self, params: Optional[dict]):
        """Load a different parameter set into these same widgets.

        The scope panel needs it to move the editor between the values shared by
        all selected groups and the values belonging to one group. With several
        targets and one editor, switching has to *save* what was typed -- which
        is the only reason this is a method and not a fresh widget.
        """
        self._apply_values(merge_defaults(params))
        self.refresh_changed()

    @staticmethod
    def _section_rule(title: str) -> QWidget:
        return section_rule(title)

    def _on_edited(self, key: str = ""):
        self.refresh_changed()
        self.changed.emit(key)

    # ---- Values ----

    def values(self) -> Dict[str, Any]:
        """Every parameter, keyed for the run log / viewer / MeshRunner."""
        return {
            "algorithm": self._algo_combo.currentText(),
            "algorithm_index": self.ALGORITHMS[self._algo_combo.currentText()],
            "elem_factor": self._elem_factor_spin.value(),
            "min_factor": self._min_factor_spin.value(),
            "max_factor": self._max_factor_spin.value(),
            "smoothing": self._smoothing_spin.value(),
            "order": self._order_combo.currentData(),
            "mode": self._mode_combo.currentData(),
        }

    def set_baseline(self, params: Optional[dict], note: str = ""):
        """Compare against `params` from now on (None switches the diff off)."""
        self._baseline = dict(params) if params else None
        self._baseline_note = note
        self.refresh_changed()

    def refresh_changed(self):
        """Mark the fields that differ from the baseline.

        A tinted border on the *field* (`.num.ch` in the mockup), not a marker
        character on the caption: the value is what changed, so the value is what
        should look different. The caption carries the "was X, now Y" tooltip.
        """
        cur = self.values()
        base = self._baseline or {}
        for key, cap in self._labels.items():
            base_val = base.get(key)
            changed = (self._baseline is not None and base_val is not None
                       and base_val != cur.get(key))
            cap.setText(("• " + self._label_text[key]) if changed
                        else self._label_text[key])
            # Only the edited state carries a style. An unedited caption is left
            # unstyled so it matches the "Mode:" label; pinning an 11px size on
            # it here is what made the two halves of the form disagree.
            cap.setStyleSheet(
                f"color: {self._pal['changed_border']}; font-weight: 700;"
                if changed else "")
            field = self._fields_by_key.get(key)
            if field is not None and bool(field.property("changed")) != changed:
                field.setProperty("changed", changed)
                field.style().unpolish(field)
                field.style().polish(field)
            if changed:
                where = f"{self._baseline_note}: " if self._baseline_note else ""
                cap.setToolTip(f"{where}{base_val} → {cur.get(key)}")
            else:
                cap.setToolTip("")

    def summary_text(self) -> str:
        """One line, for the status bar and the viewer header."""
        v = self.values()
        return (f"Algorithm={v['algorithm']}, "
                f"ElementSizeFactor={v['elem_factor']:.2f}, "
                f"MeshMinFactor={v['min_factor']:.2f}, "
                f"MeshMaxFactor={v['max_factor']:.2f}, "
                f"Smoothing={v['smoothing']}, ElementOrder={v['order']}")

    # ---- Convenience accessors (same names the dialog always exposed) ----

    @property
    def mode(self) -> str:
        return self._mode_combo.currentData()

    @property
    def algorithm(self) -> str:
        return self._algo_combo.currentText()

    @property
    def algorithm_index(self) -> int:
        return self.ALGORITHMS[self.algorithm]

    @property
    def element_size_factor(self) -> float:
        return self._elem_factor_spin.value()

    @property
    def mesh_min_factor(self) -> float:
        return self._min_factor_spin.value()

    @property
    def mesh_max_factor(self) -> float:
        return self._max_factor_spin.value()

    @property
    def smoothing_steps(self) -> int:
        return self._smoothing_spin.value()

    @property
    def element_order(self) -> int:
        return self._order_combo.currentData()
