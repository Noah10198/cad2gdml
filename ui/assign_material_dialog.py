"""
AssignMaterialDialog - Material assignment table dialog.

Displays the full assembly tree in a table. Leaf SOLID nodes can be
batch-assigned materials via right-click; parent nodes are shown for
context but are not assignable.
"""

from typing import Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QAbstractItemView, QMenu, QWidget,
    QComboBox, QDialogButtonBox, QLabel, QFrame, QWidgetAction
)
from PyQt6.QtCore import Qt, QSize, QTimer, QEvent, QObject, pyqtSignal
from PyQt6.QtGui import QColor

if TYPE_CHECKING:
    from core.geo_data_agent import GeoDataAgent
    from core.g_data_node import GDataNode
    from core.materials_lib import MaterialsLib


# ---- Column indices ----
COL_NODE_NAME = 0
COL_SOURCE_FILE = 1
COL_STATUS = 2
COL_MATERIAL = 3
COL_ENTRY_ID = 4  # hidden

HEADERS = ["Node Name", "Source File", "Status", "Material"]

_DIM_COLOR = QColor("#6c7086")  # grayed text for non-assignable rows


class _ComboHoverWatcher(QObject):
    """Opens the combo popup on mouse hover for a better UX."""

    def __init__(self, combo: QComboBox, parent=None):
        super().__init__(parent)
        self._combo = combo
        combo.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._combo and event.type() == QEvent.Type.Enter:
            QTimer.singleShot(0, self._combo.showPopup)
        return super().eventFilter(obj, event)


class AssignMaterialDialog(QDialog):
    """Non-modal table dialog for batch-assigning materials.

    Emits ``materials_saved(assigned, total)`` when the user clicks Save.
    """

    materials_saved = pyqtSignal(int, int)

    def __init__(self, geo_agent: 'GeoDataAgent',
                 material_lib: 'MaterialsLib', parent=None):
        super().__init__(parent)
        self._geo_agent = geo_agent
        self._mat_lib = material_lib

        # Flat list: (node, depth, assignable)
        self._all_rows: list = []
        # Leaf solids only (for counting at save time)
        self._solid_nodes: list = []

        self.setWindowTitle("Assign Materials")
        self.setMinimumSize(750, 500)
        self.resize(850, 600)

        self._build_ui()
        self._populate_table()
        self._apply_theme()

    # ---- UI Construction ----

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Select assignable rows, right-click to set material.")
        header.setObjectName("MatDlgHeader")
        layout.addWidget(header)

        self._table = QTableWidget()
        self._table.setColumnCount(len(HEADERS) + 1)
        self._table.setHorizontalHeaderLabels(HEADERS)
        self._table.setColumnHidden(COL_ENTRY_ID, True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(
            self._on_table_context_menu)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(COL_NODE_NAME,
                                  QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_SOURCE_FILE,
                                  QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_STATUS,
                                  QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(COL_MATERIAL,
                                  QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)

        # Bottom bar
        summary_layout = QHBoxLayout()
        self._summary_label = QLabel("0 nodes selected")
        self._summary_label.setObjectName("MatDlgSummary")
        summary_layout.addWidget(self._summary_label)
        summary_layout.addStretch()

        btn_box = QDialogButtonBox()
        save_btn = btn_box.addButton("Save && Close",
                                     QDialogButtonBox.ButtonRole.AcceptRole)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = btn_box.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.clicked.connect(self.reject)
        summary_layout.addWidget(btn_box)
        layout.addLayout(summary_layout)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)

    # ---- Data Population ----

    def _populate_table(self):
        """Recursively populate the table with the full assembly tree."""
        self._all_rows = []
        self._solid_nodes = []
        self._table.setRowCount(0)

        for file_node in self._geo_agent.get_all_geo_file_nodes():
            self._append_node_rows(file_node, 0)

        self._table.setRowCount(len(self._all_rows))

        for row, (node, depth, assignable) in enumerate(self._all_rows):
            if assignable:
                self._solid_nodes.append(node)

            # Node name with indentation
            prefix = "  " * depth
            display = prefix + node.name
            name_item = QTableWidgetItem(display)
            name_item.setToolTip(node.name)
            if not assignable:
                name_item.setForeground(_DIM_COLOR)
            self._table.setItem(row, COL_NODE_NAME, name_item)

            # Source file
            src = self._get_source_file_name(node) if assignable else ""
            src_item = QTableWidgetItem(src)
            if not assignable:
                src_item.setForeground(_DIM_COLOR)
            self._table.setItem(row, COL_SOURCE_FILE, src_item)

            # Hidden entry_id
            self._table.setItem(row, COL_ENTRY_ID,
                                QTableWidgetItem(node.entry_id))

            # Status + Material columns
            if assignable:
                self._update_row_status(row, node)
            else:
                empty = QTableWidgetItem("")
                empty.setForeground(_DIM_COLOR)
                self._table.setItem(row, COL_STATUS, empty)

                empty_mat = QTableWidgetItem("")
                empty_mat.setForeground(_DIM_COLOR)
                self._table.setItem(row, COL_MATERIAL, empty_mat)

    def _append_node_rows(self, node: 'GDataNode', depth: int):
        """Recursively flatten the tree into ``_all_rows``."""
        assignable = node.is_leaf() and node.shape is not None
        self._all_rows.append((node, depth, assignable))
        for child in node.children:
            self._append_node_rows(child, depth + 1)

    def _get_source_file_name(self, node: 'GDataNode') -> str:
        """Walk up to find the parent file-node name."""
        parent = node.parent
        while (parent is not None and parent.parent is not None
               and parent.parent.parent is not None):
            parent = parent.parent
        return parent.name if parent else ""

    def _update_row_status(self, row: int, node: 'GDataNode'):
        """Refresh ✅/❌ and material name for an assignable row."""
        mat = node.material_name.strip()
        if mat:
            status_item = QTableWidgetItem("✅")
            status_item.setToolTip("Assigned")
            mat_item = QTableWidgetItem(mat)
            mat_item.setToolTip(mat)
        else:
            status_item = QTableWidgetItem("❌")
            status_item.setToolTip("Not assigned")
            mat_item = QTableWidgetItem("")
        self._table.setItem(row, COL_STATUS, status_item)
        self._table.setItem(row, COL_MATERIAL, mat_item)

    # ---- Right-click Context Menu ----

    def _on_table_context_menu(self, pos):
        """Context menu — only shows for assignable rows."""
        selected_rows = set()
        for item in self._table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            return

        # Keep only assignable rows
        assignable_rows = {r for r in selected_rows
                           if self._all_rows[r][2]}
        if not assignable_rows:
            return

        menu = QMenu(self)

        # Global materials selector
        global_menu = menu.addMenu("Global Material")
        global_names = self._mat_lib.get_nist_left_list()
        global_combo = QComboBox()
        global_combo.setPlaceholderText("Select global material...")
        global_combo.addItem("")
        for name in global_names:
            global_combo.addItem(name)
        global_combo.currentTextChanged.connect(
            lambda txt, m=menu: (
                self._on_global_selected(txt, assignable_rows,
                                         global_combo, local_combo),
                m.close()))
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(global_combo)
        global_menu.addAction(wa)
        _ComboHoverWatcher(global_combo, self)

        # Local materials selector
        local_menu = menu.addMenu("Local Material")
        local_names = self._mat_lib.get_local_material_names()
        local_combo = QComboBox()
        local_combo.setPlaceholderText("Select local material...")
        local_combo.addItem("")
        for name in sorted(local_names):
            local_combo.addItem(name)
        local_combo.currentTextChanged.connect(
            lambda txt, m=menu: (
                self._on_local_selected(txt, assignable_rows,
                                        local_combo, global_combo),
                m.close()))
        wa2 = QWidgetAction(menu)
        wa2.setDefaultWidget(local_combo)
        local_menu.addAction(wa2)
        _ComboHoverWatcher(local_combo, self)

        menu.addSeparator()
        clear_action = menu.addAction("❌ Clear Material")
        clear_action.triggered.connect(
            lambda: (self._clear_material(assignable_rows), menu.close()))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_global_selected(self, text: str, rows: set,
                            global_cb: QComboBox, local_cb: QComboBox):
        if not text:
            return
        local_cb.blockSignals(True)
        local_cb.setCurrentIndex(0)
        local_cb.blockSignals(False)
        self._apply_material_to_rows(text, rows)
        global_cb.blockSignals(True)
        global_cb.setCurrentIndex(0)
        global_cb.blockSignals(False)

    def _on_local_selected(self, text: str, rows: set,
                           local_cb: QComboBox, global_cb: QComboBox):
        if not text:
            return
        global_cb.blockSignals(True)
        global_cb.setCurrentIndex(0)
        global_cb.blockSignals(False)
        self._apply_material_to_rows(text, rows)
        local_cb.blockSignals(True)
        local_cb.setCurrentIndex(0)
        local_cb.blockSignals(False)

    def _apply_material_to_rows(self, material_name: str, rows: set):
        for row in rows:
            node, _, assignable = self._all_rows[row]
            if not assignable:
                continue
            node.material_name = material_name
            self._update_row_status(row, node)

    def _clear_material(self, rows: set):
        for row in rows:
            node, _, assignable = self._all_rows[row]
            if not assignable:
                continue
            node.material_name = ""
            self._update_row_status(row, node)

    # ---- Selection Tracking ----

    def _on_selection_changed(self):
        rows = set()
        for item in self._table.selectedItems():
            rows.add(item.row())
        assignable = sum(1 for r in rows if self._all_rows[r][2])
        total = sum(1 for _, _, a in self._all_rows if a)
        self._summary_label.setText(
            f"{assignable}/{total} assignable node(s) selected")

    # ---- Save ----

    def _on_save(self):
        assigned = sum(1 for n in self._solid_nodes
                       if n.material_name.strip())
        self.materials_saved.emit(assigned, len(self._solid_nodes))
        self.accept()

    # ---- Theming ----

    def _apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
            }
            #MatDlgHeader {
                color: #2c2c2c;
                font-size: 13px;
                padding: 4px 0px;
            }
            #MatDlgSummary {
                color: #666666;
                font-size: 12px;
            }
            QTableWidget {
                background-color: #ffffff;
                color: #2c2c2c;
                gridline-color: #e0e0e0;
                border: 1px solid #cccccc;
                border-radius: 4px;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 4px 8px;
                background-color: transparent;
            }
            QTableWidget::item:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
            QTableWidget:focus {
                outline: none;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                color: #333333;
                padding: 6px 8px;
                border: none;
                border-bottom: 1px solid #cccccc;
                font-weight: bold;
                font-size: 12px;
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
            QLabel {
                color: #2c2c2c;
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
            QMenu {
                background-color: #ffffff;
                color: #2c2c2c;
                border: 1px solid #d0d0d0;
                border-radius: 8px;
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 4px;
                min-height: 22px;
            }
            QMenu::item:selected {
                background-color: #e8f0fe;
                color: #1a1a1a;
            }
            QMenu::item:disabled {
                color: #aaaaaa;
            }
            QMenu::separator {
                height: 1px;
                background-color: #e0e0e0;
                margin: 4px 8px;
            }
        """)
