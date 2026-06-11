"""
ExportMeshDialog — dialog for exporting mesh files (VTK, MSH).

Allows the user to choose an output directory, a sub-folder name,
and select which file formats to produce.
"""

import os
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QCheckBox, QLabel, QFileDialog, QGroupBox, QDialogButtonBox,
    QWidget,
)
from PyQt6.QtCore import Qt


class ExportMeshDialog(QDialog):
    """Dialog for configuring mesh export options."""

    def __init__(self, default_dir: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Export Mesh")
        self.setModal(True)
        self.setMinimumWidth(480)

        self._default_dir = default_dir
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Output path ──
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Output folder:"))
        self._path_edit = QLineEdit(self._default_dir)
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Select output directory...")
        path_layout.addWidget(self._path_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_path)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # ── Folder name ──
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Folder name:"))
        self._name_edit = QLineEdit("1")
        self._name_edit.setPlaceholderText("e.g. my_mesh_run")
        name_layout.addWidget(self._name_edit, 1)
        layout.addLayout(name_layout)

        # ── Format checkboxes ──
        fmt_group = QGroupBox("Export Formats")
        fmt_layout = QVBoxLayout(fmt_group)

        self._check_overall_vtk = QCheckBox("Overall VTK (.vtk)")
        self._check_overall_vtk.setToolTip(
            "Export a single VTK file containing all parts merged together.")
        self._check_overall_vtk.setChecked(True)
        fmt_layout.addWidget(self._check_overall_vtk)

        self._check_per_part_vtk = QCheckBox("Per-part VTK (.vtk)")
        self._check_per_part_vtk.setToolTip(
            "Export one VTK file per individual part.")
        self._check_per_part_vtk.setChecked(False)
        fmt_layout.addWidget(self._check_per_part_vtk)

        self._check_msh = QCheckBox("GMSH MSH (.msh)")
        self._check_msh.setToolTip(
            "Export the raw GMSH mesh file for each part.")
        self._check_msh.setChecked(True)
        fmt_layout.addWidget(self._check_msh)

        layout.addWidget(fmt_group)

        # ── Info label ──
        self._info_label = QLabel(
            "Files will be saved under:\n"
            f"  <output_folder>\\<folder_name>\\"
        )
        self._info_label.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(self._info_label)

        # ── Buttons ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_path(self):
        """Open directory picker, defaulting to the current path."""
        start = self._path_edit.text() or os.getcwd()
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", start)
        if chosen:
            self._path_edit.setText(chosen)
            self._update_info()

    def _update_info(self):
        """Refresh the info label with the effective path."""
        base = self._path_edit.text()
        name = self._name_edit.text().strip() or "1"
        self._info_label.setText(
            f"Files will be saved under:\n  {os.path.join(base, name)}\\"
        )

    def _on_name_changed(self):
        self._update_info()

    # ── Public accessors ──

    @property
    def output_directory(self) -> str:
        """Absolute path to the chosen base directory."""
        return self._path_edit.text()

    @property
    def folder_name(self) -> str:
        """User-specified sub-folder name (default '1')."""
        name = self._name_edit.text().strip()
        return name if name else "1"

    @property
    def export_overall_vtk(self) -> bool:
        return self._check_overall_vtk.isChecked()

    @property
    def export_per_part_vtk(self) -> bool:
        return self._check_per_part_vtk.isChecked()

    @property
    def export_msh(self) -> bool:
        return self._check_msh.isChecked()
