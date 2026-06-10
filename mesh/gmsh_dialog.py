"""
GmshDialog - Parameter dialog for GMSH mesh generation.

Provides controls for mesh algorithm, element size, smoothing,
and element order. Based on the C++ GridParamSetDlg reference.
"""

from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QComboBox, QDoubleSpinBox, QSpinBox,
    QWidget, QDialogButtonBox, QLabel
)
from PyQt6.QtCore import Qt


class GmshDialog(QDialog):
    """Dialog for configuring GMSH mesh generation parameters."""

    # GMSH algorithm index mapping
    ALGORITHMS = {
        "MeshAdapt": 1,
        "Automatic": 2,
        "Delaunay": 5,
        "Frontal-Delaunay": 6,
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Mesh Generation Parameters")
        self.setMinimumWidth(380)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Configure GMSH mesh parameters for the selected geometry:")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Form layout for parameters
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Algorithm
        self._algo_combo = QComboBox()
        for name in self.ALGORITHMS:
            self._algo_combo.addItem(name)
        self._algo_combo.setCurrentText("Frontal-Delaunay")
        self._algo_combo.setToolTip(
            "MeshAdapt=1, Automatic=2, Delaunay=5, Frontal-Delaunay=6"
        )
        form.addRow("Algorithm:", self._algo_combo)

        # Element size factor
        self._elem_factor_spin = QDoubleSpinBox()
        self._elem_factor_spin.setRange(0.01, 999999.0)
        self._elem_factor_spin.setValue(1.0)
        self._elem_factor_spin.setSingleStep(0.1)
        self._elem_factor_spin.setDecimals(2)
        form.addRow("Element Size Factor:", self._elem_factor_spin)

        # Mesh min factor (used to compute MeshSizeMin)
        self._min_factor_spin = QDoubleSpinBox()
        self._min_factor_spin.setRange(0.01, 999999.0)
        self._min_factor_spin.setValue(5.0)
        self._min_factor_spin.setSingleStep(0.5)
        self._min_factor_spin.setDecimals(2)
        form.addRow("Mesh Min Factor:", self._min_factor_spin)

        # Mesh max factor (used to compute MeshSizeMax)
        self._max_factor_spin = QDoubleSpinBox()
        self._max_factor_spin.setRange(0.01, 999999.0)
        self._max_factor_spin.setValue(6.0)
        self._max_factor_spin.setSingleStep(0.5)
        self._max_factor_spin.setDecimals(2)
        form.addRow("Mesh Max Factor:", self._max_factor_spin)

        # Smoothing steps
        self._smoothing_spin = QSpinBox()
        self._smoothing_spin.setRange(0, 100)
        self._smoothing_spin.setValue(1)
        form.addRow("Smoothing Steps:", self._smoothing_spin)

        # Element order
        self._order_combo = QComboBox()
        self._order_combo.addItem("1st Order", 1)
        self._order_combo.addItem("2nd Order", 2)
        form.addRow("Element Order:", self._order_combo)

        layout.addLayout(form)
        layout.addSpacing(10)

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ---- Parameter accessors ----

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

    def get_descriptive_summary(self) -> str:
        """Return a human-readable summary of current parameters."""
        return (
            f"Algorithm={self.algorithm}, "
            f"ElementSizeFactor={self.element_size_factor:.2f}, "
            f"MeshMinFactor={self.mesh_min_factor:.2f}, "
            f"MeshMaxFactor={self.mesh_max_factor:.2f}, "
            f"Smoothing={self.smoothing_steps}, "
            f"ElementOrder={self.element_order}"
        )
