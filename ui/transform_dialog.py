"""
TransformDialog - place one imported CAD file as a whole.

Opened from the file row's context menu (ui/project_tree.py), next to Delete:
the placement of an import belongs to the import, not to a part inside it. The
numbers here are absolute -- they describe where the file sits, so re-opening
the dialog shows what is in force and Reset really resets (see
core/node_transform.py).
"""

from typing import List, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from core.node_transform import ABOUT_GEOMETRY, ABOUT_ORIGIN, TransformSpec

# Very generous, but a spin box needs a range: these are millimetres and
# degrees, and the point of the limit is only to stop a typo from making a
# number that no longer fits in a double.
_LIMIT = 1e9


class TransformDialog(QDialog):
    """Translate / rotate one imported file -- all of it, at once."""

    # Every committed edit (a spin box, or the centre combo) is announced, so the
    # window that opened this dialog can move the model while the numbers are
    # being tried out, instead of only when Apply is pressed. What that costs is
    # the caller's business: this class just reports.
    specChanged = pyqtSignal()

    def __init__(self, name: str, spec: TransformSpec, dark: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Transform")
        self.setMinimumWidth(400)

        self._build_ui(name)
        self._load(spec)
        self._apply_theme(dark)

    # ---- UI ----

    def _build_ui(self, name: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel(name)
        title.setObjectName("TransformTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        self._move_group, self._t_spins = _xyz_block(
            "Translate (mm)", -_LIMIT, _LIMIT, 1.0)
        layout.addWidget(self._move_group)

        self._rot_group, self._r_spins = _xyz_block(
            "Rotate (deg)", -360.0, 360.0, 5.0, suffix="°", wrap=True)
        layout.addWidget(self._rot_group)

        centre_group = QGroupBox("Rotation centre")
        centre_form = QFormLayout(centre_group)
        centre_form.setContentsMargins(8, 4, 8, 8)
        self._about_combo = QComboBox()
        self._about_combo.addItem("Geometry centre (the whole import)",
                                  ABOUT_GEOMETRY)
        self._about_combo.addItem("World origin (0, 0, 0)", ABOUT_ORIGIN)
        centre_form.addRow(self._about_combo)
        layout.addWidget(centre_group)

        # Everything that spells the placement reports its edits. The boxes are
        # the only source of the spec, so listening to them is enough -- and the
        # panel is told to stop typing tracking (see _xyz_block), so a half
        # written number is never announced as an edit.
        for spin in self._t_spins + self._r_spins:
            spin.valueChanged.connect(self._on_edit)
        self._about_combo.currentIndexChanged.connect(self._on_edit)

        hint = QLabel(
            "The turn happens about this centre first, then the translation. "
            "The parts move together: their positions relative to each other "
            "never change.")
        hint.setObjectName("TransformHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip("Back to where the file was imported")
        reset_btn.clicked.connect(self._on_reset)
        buttons.addWidget(reset_btn)
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.accept)
        buttons.addWidget(apply_btn)
        layout.addLayout(buttons)

    def _load(self, spec: TransformSpec):
        """Fill the boxes with an existing placement."""
        for spin, value in zip(self._t_spins, spec.translation):
            spin.setValue(value)
        for spin, value in zip(self._r_spins, spec.rotation):
            spin.setValue(value)
        index = self._about_combo.findData(spec.about)
        self._about_combo.setCurrentIndex(max(index, 0))

    def _on_reset(self):
        """Zero every number -- the placement the file was imported with."""
        self._load(TransformSpec())

    def _on_edit(self, _value=None):
        """A number or the centre changed: report the placement it spells."""
        self.specChanged.emit()

    # ---- Result ----

    def spec(self) -> TransformSpec:
        """The placement the boxes spell, to be applied from the import."""
        tx, ty, tz = (s.value() for s in self._t_spins)
        rx, ry, rz = (s.value() for s in self._r_spins)
        return TransformSpec(tx=tx, ty=ty, tz=tz, rx=rx, ry=ry, rz=rz,
                             about=self._about_combo.currentData())

    # ---- Theming ----

    def _apply_theme(self, dark: bool):
        if dark:
            bg, title_fg, hint_fg = "#1e1e2e", "#cdd6f4", "#a6adc8"
            grp_fg, grp_border = "#a6adc8", "#313244"
            spin_bg, spin_fg = "#313244", "#cdd6f4"
            btn_bg, btn_fg, btn_border, btn_hover = (
                "#313244", "#cdd6f4", "#45475a", "#45475a")
        else:
            bg, title_fg, hint_fg = "#ffffff", "#2c2c2c", "#666666"
            grp_fg, grp_border = "#555555", "#d0d0d0"
            spin_bg, spin_fg = "#ffffff", "#2c2c2c"
            btn_bg, btn_fg, btn_border, btn_hover = (
                "#f0f0f0", "#2c2c2c", "#d0d0d0", "#e4e7eb")

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            #TransformTitle {{
                color: {title_fg};
                font-size: 13px;
                font-weight: bold;
            }}
            #TransformHint {{
                color: {hint_fg};
                font-size: 11px;
            }}
            QGroupBox {{
                font-size: 12px;
                font-weight: bold;
                color: {grp_fg};
                border: 1px solid {grp_border};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 16px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 8px;
                color: {grp_fg};
            }}
            QLabel {{ color: {title_fg}; font-size: 12px; }}
            QDoubleSpinBox, QComboBox {{
                background-color: {spin_bg};
                color: {spin_fg};
                border: 1px solid {grp_border};
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 12px;
                min-height: 20px;
            }}
            QDoubleSpinBox:focus, QComboBox:focus {{
                border: 1px solid #0078d4;
            }}
            QPushButton {{
                background-color: {btn_bg};
                color: {btn_fg};
                border: 1px solid {btn_border};
                border-radius: 4px;
                padding: 5px 16px;
                font-size: 12px;
                min-height: 20px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
                border: 1px solid #0078d4;
            }}
        """)


def _xyz_block(title: str, minimum: float, maximum: float, step: float,
               suffix: str = "", wrap: bool = False
               ) -> Tuple[QGroupBox, List[QDoubleSpinBox]]:
    """A group box holding an X / Y / Z row, labelled and stepped the same way."""
    group = QGroupBox(title)
    grid = QGridLayout(group)
    grid.setContentsMargins(8, 4, 8, 8)
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(2)

    spins: List[QDoubleSpinBox] = []
    for col, axis in enumerate(("X", "Y", "Z")):
        label = QLabel(axis)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        grid.addWidget(label, 0, col)

        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        if suffix:
            spin.setSuffix(suffix)
        # Degrees wrap so that -90 and 270 are the same request, not a spin box
        # that refuses to go past its end.
        spin.setWrapping(wrap)
        # Only read the box when it is done being typed in, so a value is never
        # taken half-written.
        spin.setKeyboardTracking(False)
        grid.addWidget(spin, 1, col)
        spins.append(spin)

    return group, spins
