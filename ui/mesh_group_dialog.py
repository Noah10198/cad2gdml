"""
mesh_group_dialog.py -- one mesh group on a screen of its own.

The scope panel lists groups, not parts: "Group A · 3 part(s)" is not an answer
to "which three?", and the answer has to be somewhere. Lighting the parts up in
the main 3D view was the first attempt, and it is the wrong place: the model is
there, so the group is drawn among everything else, at whatever orientation the
main view happens to have, and a group that is partly inside the assembly is
hidden by exactly the parts that are not in question.

So the group gets its own window, like the interference check: only the parts in
question, in the same blue that check paints its two shapes with, fitted, with a
table naming them. Nothing is meshed or changed by looking at it.

Nothing here knows about meshing: it takes the group and the nodes it names.
"""

from typing import Optional, Sequence, Set

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QLabel, QWidget, QFrame,
)
from PyQt6.QtGui import QColor

from OCC.Core.Quantity import Quantity_Color, Quantity_NOC_BLUE1

from mesh.scope import MeshGroup
from ui.occ_preview import OCCPreview


# One colour for the whole group, and the same one the interference check uses
# for its two shapes. A colour per part would make the table a legend the user
# has to read; the parts are here to be identified, and the table names them.
PART_COLOR = Quantity_Color(Quantity_NOC_BLUE1)
PART_TRANSPARENCY = 0.55  # so parts sitting inside each other stay visible


class MeshGroupDialog(QDialog):
    """The parts of one mesh group, on their own: 3D view + table, non-modal."""

    OCC_SQUARE = 360  # px -- fixed square side for the embedded 3D view

    def __init__(self, group: MeshGroup, parts: Sequence,
                 meshed_ids: Optional[Set[str]] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle(f"{group.label} · {group.n_parts} part(s)")

        self._key = tuple(group.entry_ids)
        self._parts = list(parts)
        self._meshed_ids = set(meshed_ids or ())
        self._populated = False

        occ = self.OCC_SQUARE
        table_w = int(occ * 0.9)
        self.setFixedSize(4 + occ + 4 + table_w + 8,
                          4 + 24 + 4 + occ + 4 + 32 + 4)

        self._build_ui(group, occ, table_w)

    # ---- public ----

    def same_group(self, group: MeshGroup) -> bool:
        """True when this window already shows `group` (same parts, any order)."""
        return set(self._key) == set(group.entry_ids)

    # ---- UI ----

    def _build_ui(self, group: MeshGroup, occ: int, table_w: int):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)

        info = QLabel(f"{group.label} · {group.n_parts} part(s) · "
                      f"{group.mode_label}")
        info.setStyleSheet(
            "font-size: 13px; padding: 3px 6px; "
            "background-color: #14141F; color: #ffffff; border-radius: 3px;")
        info.setFixedHeight(24)
        layout.addWidget(info)

        center = QHBoxLayout()
        center.setSpacing(4)

        self._preview = OCCPreview()
        self._preview.setFrameShape(QFrame.Shape.StyledPanel)
        self._preview.setFixedSize(occ, occ)
        center.addWidget(self._preview)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Part", "Material", "Mesh"])
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setFixedWidth(table_w)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        center.addWidget(self._table)

        layout.addLayout(center)

        btn_row = QHBoxLayout()
        fit_btn = QPushButton("Fit View")
        fit_btn.clicked.connect(self._fit_preview)
        btn_row.addWidget(fit_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._fill_table()

    def showEvent(self, event):
        super().showEvent(event)
        # Only once the window is on screen: the OCC viewport needs a native
        # window handle, which Qt creates while showing it.
        if not self._populated:
            self._populated = True
            self._fill_preview()

    def _fill_preview(self):
        if not self._parts:
            return
        self._preview.clear_all()
        for node in self._parts:
            shape = node.shape
            if shape is None or shape.IsNull():
                continue
            self._preview.display_shape(shape, PART_COLOR,
                                        transparency=PART_TRANSPARENCY)
        self._preview.fit_all()
        self._preview.refresh()

    def _fill_table(self):
        self._table.setRowCount(0)
        for node in self._parts:
            row = self._table.rowCount()
            self._table.insertRow(row)

            self._table.setItem(
                row, 0, QTableWidgetItem(node.name or node.entry_id))
            self._table.setItem(
                row, 1, QTableWidgetItem(node.material_name or "—"))

            meshed = node.entry_id in self._meshed_ids
            cell = QTableWidgetItem("meshed" if meshed else "—")
            if not meshed:
                cell.setForeground(QColor(150, 150, 150))
            self._table.setItem(row, 2, cell)

    def _fit_preview(self):
        self._preview.fit_all()
        self._preview.refresh()

    # ---- Cleanup ----

    def closeEvent(self, event):
        self._preview.shutdown()
        super().closeEvent(event)
