"""
LocalMaterialDialog - Dialog for adding / editing local materials.

Appears as a popup when the user right-clicks "Local Materials" → "Add Material..."
or re-opens a saved one via "Edit Material..." / double-click.
"""
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
    QWidget, QGroupBox, QSizePolicy, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, QTimer

from core.materials_lib import (
    MaterialsLib, CompoundMaterial, CompoundItem,
    MixtureMaterial, MixtureItem,
)

# Fixed widths of the ratio column, shared by the composition rows and their
# header so the two line up.
_RATIO_WIDTH = 120
_REMOVE_BTN_WIDTH = 28


class _CompositionItem:
    """Tracks a single element composition row."""
    def __init__(self, combo: QComboBox, spin: QDoubleSpinBox):
        self.combo = combo
        self.spin = spin


class LocalMaterialDialog(QDialog):
    """Dialog for adding a local material, or editing an existing one."""

    # Mass fractions have to sum to exactly 1. An epsilon rather than a plain
    # == 1.0 because binary floating point cannot add decimal fractions
    # exactly (0.1 + 0.2 + 0.7 == 0.9999999999999999); 1e-6 is far above that
    # noise and far below the 1e-4 the spin boxes can express.
    _TOTAL_TOLERANCE = 1e-6

    def __init__(self, mat_lib: MaterialsLib, parent=None, material=None):
        super().__init__(parent)
        self._mat_lib = mat_lib
        self._editing = material
        self._items: list[_CompositionItem] = []
        self._last_gdml: str = ""
        self._saved_mat = None

        is_edit = material is not None
        self.setWindowTitle("Edit Local Material" if is_edit else "Add Local Material")
        self.setMinimumSize(520, 400)
        self.resize(560, 480)

        self._build_ui()
        self._apply_theme()

        if is_edit:
            self._save_btn.setText("Save Changes")
            self._load_material(material)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # Category selector
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("Type:"))
        self._cat_combo = QComboBox()
        self._cat_combo.addItem("Compound (atom ratio)", "compound")
        self._cat_combo.addItem("Mixture (mass fraction)", "mixture")
        self._cat_combo.currentIndexChanged.connect(self._on_category_changed)
        cat_layout.addWidget(self._cat_combo)
        cat_layout.addStretch()
        layout.addLayout(cat_layout)

        # Basic Info
        common_group = QGroupBox("Basic Info")
        common_layout = QFormLayout(common_group)
        common_layout.setSpacing(4)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. my_steel, my_water...")
        common_layout.addRow("Name:", self._name_edit)

        self._density_spin = QDoubleSpinBox()
        self._density_spin.setDecimals(4)
        self._density_spin.setRange(0, 1e9)
        self._density_spin.setValue(1.0)
        self._density_spin.setToolTip("Density in g/cm³")
        common_layout.addRow("Density (g/cm³):", self._density_spin)

        # Keep the natural height: as a Preferred box it would take half of any
        # extra height the dialog gets, leaving a blank patch under Density.
        common_group.setSizePolicy(QSizePolicy.Policy.Preferred,
                                   QSizePolicy.Policy.Fixed)
        layout.addWidget(common_group)

        # Composition
        self._comp_group = QGroupBox("Composition")
        comp_layout = QVBoxLayout(self._comp_group)

        # Items container
        self._items_widget = QWidget()
        self._items_layout = QVBoxLayout(self._items_widget)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(4)

        # Header row: the Ratio label carries the same fixed width as the spin
        # box below, so the header columns sit over the actual columns. It is
        # part of the scrolled content on purpose -- outside of it the labels
        # would shift sideways by the scrollbar width whenever it appears.
        comp_header = QHBoxLayout()
        comp_header.setSpacing(8)
        comp_header.addWidget(QLabel("Element"), 1)
        ratio_header = QLabel("Ratio")
        ratio_header.setFixedWidth(_RATIO_WIDTH)
        comp_header.addWidget(ratio_header)
        comp_header.addSpacing(8 + _REMOVE_BTN_WIDTH)
        self._items_layout.addLayout(comp_header)

        # The rows are all fixed height, and a box layout with nothing
        # stretchable hands its leftover height to the spacing between items.
        # This trailing spacer absorbs it instead, keeping the rows packed at
        # the top and the Add button at the bottom of the group.
        self._items_layout.addStretch(1)

        # A long element list scrolls here instead of squeezing the rows or
        # stretching the dialog to the screen height.
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._items_widget)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMinimumHeight(132)
        comp_layout.addWidget(self._scroll, 1)

        # Mixture-only feedback: mass fractions are expected to sum to 1.
        total_row = QHBoxLayout()
        total_row.addStretch()
        self._total_label = QLabel("")
        total_row.addWidget(self._total_label)
        comp_layout.addLayout(total_row)

        add_item_btn = QPushButton("+ Add Element")
        add_item_btn.clicked.connect(self._add_composition_row)
        comp_layout.addWidget(add_item_btn)

        # Sole owner of the extra height when the dialog is resized.
        layout.addWidget(self._comp_group, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._save_btn = QPushButton("Add Material")
        self._save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self._save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        # Initial state
        self._on_category_changed(0)

    def _on_category_changed(self, idx: int):
        """Update spin box decimals when switching between compound and mixture."""
        is_mixture = self._cat_combo.currentData() == "mixture"
        decimals = 4 if is_mixture else 0
        for ci in self._items:
            ci.spin.setDecimals(decimals)
            ci.spin.setSingleStep(0.0001 if is_mixture else 1.0)
            if is_mixture and ci.spin.value() < 1:
                pass  # keep existing value
            elif not is_mixture:
                ci.spin.setValue(int(ci.spin.value()))
        self._update_total_display()

    def _update_total_display(self):
        """Show the mass-fraction total, for mixtures only.

        Compound ratios are atom counts -- any integers are valid -- so the
        label is blanked there rather than reported.
        """
        if self._cat_combo.currentData() != "mixture":
            self._total_label.setText("")
            return

        total = 0.0
        has_valid = False
        for ci in self._items:
            if not ci.combo.currentData():
                continue
            has_valid = True
            total += ci.spin.value()

        if not has_valid:
            self._total_label.setText("")
            return

        if abs(total - 1.0) < self._TOTAL_TOLERANCE:
            self._total_label.setText(f"Total: {total:.4f}  (OK)")
            self._total_label.setStyleSheet(
                "color: #2e7d32; font-size: 11px; font-weight: bold;")
        else:
            self._total_label.setText(f"Total: {total:.4f}  (must be 1.0)")
            self._total_label.setStyleSheet(
                "color: #c62828; font-size: 11px; font-weight: bold;")

    def _load_material(self, mat):
        """Pre-fill every field from an existing material (edit mode).

        The category is set first: the spin decimals of the rows created below
        follow the current category.
        """
        is_mixture = isinstance(mat, MixtureMaterial)
        idx = self._cat_combo.findData("mixture" if is_mixture else "compound")
        if idx >= 0:
            self._cat_combo.setCurrentIndex(idx)
        self._name_edit.setText(mat.mat_name)
        self._density_spin.setValue(mat.density)

        for item in mat.items:
            self._add_composition_row()
            ci = self._items[-1]
            pos = ci.combo.findData(item.element_name)
            if pos >= 0:
                ci.combo.setCurrentIndex(pos)
            ci.spin.setValue(item.ratio)

    def _add_composition_row(self):
        """Add a new element composition row with auto-populated spin step."""
        row = QHBoxLayout()
        row.setSpacing(8)

        combo = QComboBox()
        elements = self._mat_lib.get_all_element_symbols()
        combo.addItem("Select element...", "")
        for sym in elements:
            z, atom = self._mat_lib.get_z_and_atom_by_element_name(sym)
            combo.addItem(f"{sym} (Z={int(z):d})", sym)
        row.addWidget(combo)

        is_mixture = self._cat_combo.currentData() == "mixture"
        spin = QDoubleSpinBox()
        spin.setDecimals(4 if is_mixture else 0)
        spin.setRange(0, 1e9)
        spin.setSingleStep(0.0001 if is_mixture else 1.0)
        spin.setValue(1)
        spin.setToolTip("Ratio (mass fraction)" if is_mixture else "Ratio (atom count)")
        spin.setFixedWidth(_RATIO_WIDTH)
        spin.valueChanged.connect(self._update_total_display)
        row.addWidget(spin)

        remove_btn = QPushButton("×")
        remove_btn.setFixedWidth(_REMOVE_BTN_WIDTH)
        remove_btn.clicked.connect(lambda: self._remove_composition_row(row))
        row.addWidget(remove_btn)

        combo.currentIndexChanged.connect(self._update_total_display)

        # Inserted before the trailing spacer so most-recently-added rows land
        # at the bottom of the list.
        self._items_layout.insertLayout(self._items_layout.count() - 1, row)
        self._items.append(_CompositionItem(combo, spin))
        self._update_total_display()
        QTimer.singleShot(0, lambda: self._refresh_scroll_area(reveal_last=True))

    def _refresh_scroll_area(self, reveal_last: bool = False):
        """Size the scrolled content to its rows and optionally reveal the last.

        Deferred to the next event loop turn, for two reasons:

        * A nested row layout reports its real minimum size only once the layout
          has been activated; measured any earlier it is a stale 0-ish value.
        * Qt writes a layout's minimum size back to its widget only for
          top-level windows, so this child would otherwise keep a minimum of 0
          and QScrollArea would squeeze a long list into the viewport, letting
          the rows overlap instead of scrolling.

        A fixed height rather than a minimum one: it shrinks the widget again
        when rows are removed, and the resize it forces is what updates the
        scrollbar range.
        """
        self._items_widget.setFixedHeight(
            self._items_widget.minimumSizeHint().height())
        if reveal_last:
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _remove_composition_row(self, row_layout):
        """Remove a composition row safely."""
        # Find the _CompositionItem by matching combo widget
        for i, item in enumerate(self._items[:]):
            if item.combo.parent() is None or item.spin.parent() is None:
                self._items.pop(i)
                break

        # Find and remove the matching layout
        for i in range(self._items_layout.count()):
            item = self._items_layout.itemAt(i)
            if item and item.layout() is row_layout:
                # Remove from tracking
                for ci in self._items[:]:
                    # Check if any widget in this layout is ours
                    for j in range(row_layout.count()):
                        w = row_layout.itemAt(j)
                        if w and w.widget() in (ci.combo, ci.spin):
                            self._items.remove(ci)
                            break
                # Delete the layout
                self._clear_layout(row_layout)
                self._items_layout.removeItem(item)
                break
        self._update_total_display()
        QTimer.singleShot(0, self._refresh_scroll_area)

    def _clear_layout(self, layout):
        """Recursively clear a layout."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    @property
    def last_gdml(self) -> str:
        return self._last_gdml

    @property
    def saved_material(self):
        """The material as written to the library (None until accepted)."""
        return self._saved_mat

    def _on_save(self):
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setStyleSheet(
                "border: 1px solid #e74c3c; background-color: #fff0f0;")
            # Clear the red style after 1.5s so user can see it
            QTimer.singleShot(1500, lambda: self._name_edit.setStyleSheet(
                "border: 1px solid #d0d0d0; background-color: #ffffff;"))
            return
        else:
            self._name_edit.setStyleSheet(
                "border: 1px solid #d0d0d0; background-color: #ffffff;")

        # Collect valid composition items
        valid_items = []
        for ci in self._items:
            sym = ci.combo.currentData()
            if not sym:
                continue
            valid_items.append((ci, sym))

        if not valid_items:
            # Flash feedback: no valid element selected
            self._name_edit.setStyleSheet(
                "border: 1px solid #e74c3c; background-color: #fff0f0;")
            return

        cat = self._cat_combo.currentData()

        # Mass fractions have to add up to 1; atom counts have no such rule.
        # The label has already been showing the running total, so the block is
        # announced rather than silent.
        if cat == "mixture":
            total = sum(ci.spin.value() for ci, _ in valid_items)
            self._update_total_display()
            if abs(total - 1.0) > self._TOTAL_TOLERANCE:
                return

        # Reuse the existing id when editing so nothing pointing at this
        # material has to be rewritten.
        mat_id = self._editing.mat_id if self._editing else ""

        if cat == "compound":
            items = []
            for ci, sym in valid_items:
                z, atom = self._mat_lib.get_z_and_atom_by_element_name(sym)
                items.append(CompoundItem(
                    ratio=int(ci.spin.value()),
                    element_name=sym,
                    z=z,
                    atom=atom,
                ))
            mat = CompoundMaterial(
                mat_id=mat_id,
                mat_name=name,
                density=round(self._density_spin.value(), 4),
                unit="g/cm3",
                items=items,
            )
        else:  # mixture
            items = []
            for ci, sym in valid_items:
                z, atom = self._mat_lib.get_z_and_atom_by_element_name(sym)
                items.append(MixtureItem(
                    ratio=round(ci.spin.value(), 4),
                    element_name=sym,
                    z=z,
                    atom=atom,
                ))
            mat = MixtureMaterial(
                mat_id=mat_id,
                mat_name=name,
                density=round(self._density_spin.value(), 4),
                unit="g/cm3",
                items=items,
            )

        if self._editing:
            self._mat_lib.update_local_material(mat)
        elif isinstance(mat, CompoundMaterial):
            self._mat_lib.add_compound(mat)
        else:
            self._mat_lib.add_mixture(mat)

        self._saved_mat = mat
        self._last_gdml = MaterialsLib.to_gdml_string(mat)
        self.accept()

    # ---- Theming ----

    def _apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
            }
            /* The composition list must stay on the dialog background: a
               QScrollArea paints its viewport with the palette Base colour,
               which is not necessarily white outside of the light theme. */
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
            QLabel {
                color: #2c2c2c;
                font-size: 12px;
            }
            QGroupBox {
                font-size: 13px;
                font-weight: bold;
                color: #555555;
                border: 1px solid #cccccc;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 8px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background-color: #ffffff;
                color: #2c2c2c;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                min-height: 22px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #0078d4;
                background-color: #f8f9fa;
            }
            QComboBox {
                background-color: #ffffff;
                color: #2c2c2c;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 24px 4px 10px;
                font-size: 12px;
                min-height: 22px;
            }
            QComboBox:hover {
                border: 1px solid #0078d4;
                background-color: #f8f9fa;
            }
            QComboBox:on {
                border: 1px solid #0078d4;
                background-color: #f0f4ff;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border: none;
                border-left: 1px solid #e0e0e0;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QComboBox:hover::drop-down {
                border-left: 1px solid #0078d4;
            }
            QComboBox::down-arrow {
                width: 0;
                height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #666666;
                margin: 2px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #2c2c2c;
                border: 1px solid #d0d0d0;
                border-radius: 8px;
                padding: 4px;
                outline: none;
                selection-background-color: transparent;
                selection-color: #2c2c2c;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px 10px;
                min-height: 24px;
                border-radius: 4px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #e8f0fe;
                color: #1a1a1a;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #d2e3fc;
                color: #1a1a1a;
            }
            QPushButton {
                background-color: #f0f0f0;
                color: #2c2c2c;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 6px 18px;
                font-size: 12px;
                font-weight: 500;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #e4e7eb;
                border: 1px solid #0078d4;
            }
            QPushButton:pressed {
                background-color: #d2d5d9;
            }
        """)
