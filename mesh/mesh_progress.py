"""
MeshProgressDialog - Non-modal progress dialog for mesh generation.

Shows a progress bar during meshing and displays "Mesh ready"
message upon completion, with a button to open the mesh viewer.
"""

from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QProgressBar,
    QLabel, QPushButton, QWidget
)
from PyQt6.QtCore import Qt, QTimer


class MeshProgressDialog(QDialog):
    """Non-blocking progress dialog for GMSH mesh generation."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Mesh Generation Progress")
        self.setMinimumWidth(450)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setModal(False)  # Non-blocking

        self._finished = False
        self._view_mesh_btn: Optional[QPushButton] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

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

        # Bottom row: close + view mesh buttons
        btn_layout = QHBoxLayout()

        self._view_mesh_btn = QPushButton("View Mesh")
        self._view_mesh_btn.setEnabled(False)
        self._view_mesh_btn.setToolTip("Open mesh preview in a separate window")
        btn_layout.addWidget(self._view_mesh_btn)

        btn_layout.addStretch()

        self._close_btn = QPushButton("Close")
        btn_layout.addWidget(self._close_btn)

        layout.addLayout(btn_layout)

        # Connect buttons
        self._close_btn.clicked.connect(self.close)

    # ---- Public API ----

    def set_progress(self, value: int, status: str = ""):
        """Update progress bar and optional status text."""
        self._progress_bar.setValue(value)
        if status:
            if value >= 100:
                # Show "Mesh ready" below the progress bar when complete
                self._status_label.setText(f"<b>Mesh ready.</b><br>{status}")
                self._mark_finished()
            else:
                self._status_label.setText(status)

    def append_log(self, text: str):
        """Append a log line (shown in status when idle)."""
        # Only show latest log line in the status label
        self._status_label.setText(text)

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
        """Connect the View Mesh button to a callback function."""
        if self._view_mesh_btn:
            self._view_mesh_btn.clicked.connect(callback)

    def reset(self):
        """Reset dialog for a new meshing session."""
        self._progress_bar.setValue(0)
        self._status_label.setText("Initializing...")
        self._finished = False
        if self._view_mesh_btn:
            self._view_mesh_btn.setEnabled(False)
            self._view_mesh_btn.setStyleSheet("")
