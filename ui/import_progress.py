"""
ImportProgressDialog - Non-modal progress dialog for CAD file import.

Shows a progress bar during file reading and a completion message.
Simplified version of MeshProgressDialog (no "view result" button).
"""

from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QProgressBar,
    QLabel, QPushButton, QWidget
)
from PyQt6.QtCore import Qt, QTimer


class ImportProgressDialog(QDialog):
    """Non-blocking progress dialog for CAD file import."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Import Progress")
        self.setMinimumWidth(420)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setModal(False)  # Non-blocking

        self._finished = False
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

        # Close button only (no extra action button for import)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._close_btn = QPushButton("Close")
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

        self._close_btn.clicked.connect(self.close)

    # ---- Public API ----

    def set_progress(self, value: int, status: str = ""):
        """Update progress bar and optional status text."""
        self._progress_bar.setValue(value)
        if status:
            if value >= 100:
                self._status_label.setText(f"<b>Import ready.</b><br>{status}")
            else:
                self._status_label.setText(status)

    def append_log(self, text: str):
        """Show latest log line in the status label."""
        self._status_label.setText(text)

    def reset(self):
        """Reset dialog for a new import session."""
        self._progress_bar.setValue(0)
        self._status_label.setText("Initializing...")
        self._finished = False
