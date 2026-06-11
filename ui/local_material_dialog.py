"""
LocalMaterialDialog - Dialog for adding local materials (Compound / Mixture).

Appears as a popup when the user right-clicks "Local Materials" → "Add Material...".
"""
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
    QWidget, QGroupBox,
)
from PyQt6.QtCore import Qt

from core.materials_lib import (
    MaterialsLib, CompoundMaterial, CompoundItem,
    MixtureMaterial, MixtureItem,
)


class _CompositionItem:
    """Tracks a single element composition row."""
    def __init__(self, combo: QComboBox, spin: QDoubleSpinBox):
        self.combo = combo
        self.spin = spin


class LocalMaterialDialog(QDialog):
    """Non-modal dialog for adding a local material (compound or mixture)."""

    def __init__(self, mat_lib: MaterialsLib, parent=None):
        super().__init__(parent)
        self._mat_lib = mat_lib
        self._items: list[_CompositionItem] = []
        self._last_gdml: str = ""

        self.setWindowTitle("Add Local Material")
        self.setMinimumSize(520, 400)
        self.resize(560, 480)

        self._build_ui()
        self._apply_theme()

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

        layout.addWidget(common_group)

        # Composition
        self._comp_group = QGroupBox("Composition")
        comp_layout = QVBoxLayout(self._comp_group)

        # Header row
        comp_header = QHBoxLayout()
        comp_header.addWidget(QLabel("Element"))
        comp_header.addWidget(QLabel("Ratio"))
        comp_header.addStretch()
        comp_layout.addLayout(comp_header)

        # Items container
        self._items_widget = QWidget()
        self._items_layout = QVBoxLayout(self._items_widget)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(4)
        comp_layout.addWidget(self._items_widget)

        add_item_btn = QPushButton("+ Add Element")
        add_item_btn.clicked.connect(self._add_composition_row)
        comp_layout.addWidget(add_item_btn)

        layout.addWidget(self._comp_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("Add Material")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)
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

        # Attach label to show current value for compound/mixture context
        ratio_label = QLabel()
        ratio_label.setStyleSheet("color: #888888; font-size: 11px;")

        row.addWidget(spin)

        remove_btn = QPushButton("×")
        remove_btn.setFixedWidth(28)
        remove_btn.clicked.connect(lambda: self._remove_composition_row(row))
        row.addWidget(remove_btn)

        self._items_layout.addLayout(row)
        self._items.append(_CompositionItem(combo, spin))

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

    def _on_save(self):
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setStyleSheet(
                "border: 1px solid #e74c3c; background-color: #fff0f0;")
            # Clear the red style after 1.5s so user can see it
            from PyQt6.QtCore import QTimer
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
                mat_id="",
                mat_name=name,
                density=round(self._density_spin.value(), 4),
                unit="g/cm3",
                items=items,
            )
            self._mat_lib.add_compound(mat)
            self._last_gdml = MaterialsLib.to_gdml_string(mat)

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
                mat_id="",
                mat_name=name,
                density=round(self._density_spin.value(), 4),
                unit="g/cm3",
                items=items,
            )
            self._mat_lib.add_mixture(mat)
            self._last_gdml = MaterialsLib.to_gdml_string(mat)

        self.accept()

    # ---- Theming ----

    def _apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
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
