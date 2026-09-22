"""
ImportProgressDialog - the window a CAD import reports in.

A bar, the line saying what is being read, and the one decision a read is
allowed to be interrupted by: whether the contact check runs once it is done.
That check is a second pass over the whole model, and the read is exactly when
the user finds out how big the model is -- so the box belongs in front of them
here, rather than in the Mesh panel they have not reached yet.

It brings its own layout rather than being a QProgressDialog: that dialog
exposes none to put a widget in (`layout()` is None on Qt 6.4), and the box is
the point of this window. The method names are QProgressDialog's on purpose --
`setValue`, `setLabelText`, `wasCanceled` -- because it stands where that one
stood in the import slot, so the progress reporting around it did not have to
move.
"""

from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QProgressBar,
    QLabel, QPushButton, QCheckBox, QWidget
)
from PyQt6.QtCore import Qt


class ImportProgressDialog(QDialog):
    """Window-modal progress window for a CAD import.

    Window-modal rather than modal, and shown rather than exec()'d: the read it
    reports on is the only thing to wait for and the main window behind it is
    out of bounds for the duration, but the slot that started the import keeps
    running underneath and reports into it.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Import CAD")
        self.setMinimumWidth(420)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self._cancelled = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._status_label = QLabel("Reading CAD files...")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # The one thing this window asks. Ticked is the behaviour there has
        # always been, so a user who ignores it gets exactly what they got
        # before; unticking is what the box is for, and it costs nothing to
        # take back because it is read only once the read is over.
        self._check_box = QCheckBox("Check contacts after import")
        self._check_box.setChecked(True)
        self._check_box.setToolTip(
            "Look for touching solids once the file has been read. Off skips "
            "the check: every part is then listed on its own in the Mesh "
            "panel, where Check contacts runs it on demand.")
        layout.addWidget(self._check_box)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setToolTip("Stop the import")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    # ---- Public API ----

    def setValue(self, value: int):
        """How far the read has got, in percent."""
        self._progress_bar.setValue(value)

    def setLabelText(self, text: str):
        """What is being read, in one line."""
        self._status_label.setText(text)

    def wasCanceled(self) -> bool:
        """Whether the user pressed Cancel and the read should stop."""
        return self._cancelled

    def check_contacts(self) -> bool:
        """Whether the contact check was asked for.

        Read once, after the read: the box stays live for the whole of it, so a
        decision taken at any point while the bar was up is the one that counts.
        """
        return self._check_box.isChecked()

    def _on_cancel(self):
        """Answer the click in the pass it arrives in.

        The flag is what stops the read, but a button that does not move reads
        as a click that missed -- and on a big file it is pressed precisely
        because nothing else is moving.
        """
        self._cancelled = True
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Cancelling...")
