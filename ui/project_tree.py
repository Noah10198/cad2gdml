"""
ProjectTreeWidget - Project tree panel for managing geometry hierarchy.

Provides a QTreeWidget with:
- A "Geometry" root node containing imported STEP file hierarchies
- Global/Local Materials nodes for material assignment
- Checkbox visibility toggling per geometry item
- Visibility checkbox toggling per geometry item
"""

from typing import Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QMenu, QWidget, QVBoxLayout, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint

if TYPE_CHECKING:
    from core.geo_data_agent import GeoDataAgent


# Tree item type constants
TREE_ITEM_TYPE = {
    'GEO_ROOT': 1001,
    'GEO_SOLID': 1002,
    'GLOBAL_MATERIAL': 1003,
    'LOCAL_MATERIAL': 1004,
}


class TreeItemWithInfo(QTreeWidgetItem):
    """Tree item carrying an entry ID and optional widget type info."""

    def __init__(self, parent, text: str, item_type: int):
        super().__init__(parent, item_type)
        self.setText(0, text)
        self._entry_id: str = ""
        self._widget_type: int = -1

    def set_entry_id(self, entry_id: str):
        self._entry_id = entry_id

    def get_entry_id(self) -> str:
        return self._entry_id

    def set_widget_type(self, wtype: int):
        self._widget_type = wtype

    def get_widget_type(self) -> int:
        return self._widget_type


class ProjectTreeWidget(QWidget):
    """Project tree panel containing geometry hierarchy and material nodes."""

    item_selected = pyqtSignal(str)
    item_visibility_changed = pyqtSignal(str, bool)  # entry_id, visible
    import_step_requested = pyqtSignal()
    assign_material_requested = pyqtSignal(str, str)
    add_local_material_requested = pyqtSignal()
    remove_local_material_requested = pyqtSignal(str)  # mat_id
    save_local_materials_requested = pyqtSignal()
    load_local_materials_requested = pyqtSignal()
    delete_geometry_requested = pyqtSignal(str)  # entry_id of file node to delete
    edit_transform_requested = pyqtSignal(str)  # entry_id of file node to place

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Build the tree and header label."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("  Project Tree")
        header.setObjectName("TreeHeader")
        header.setFixedHeight(28)
        layout.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setMinimumWidth(180)
        self._tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self._tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._tree.setAnimated(True)
        self._tree.setIndentation(16)

        self._material_global = TreeItemWithInfo(
            self._tree, "Global Materials", TREE_ITEM_TYPE['GLOBAL_MATERIAL']
        )
        self._material_local = TreeItemWithInfo(
            self._tree, "Local Materials", TREE_ITEM_TYPE['LOCAL_MATERIAL']
        )
        self._geometry_root = TreeItemWithInfo(
            self._tree, "Geometry", TREE_ITEM_TYPE['GEO_ROOT']
        )

        self._geometry_root.setExpanded(True)
        self._material_global.setExpanded(False)   # too many to show expanded
        self._material_local.setExpanded(True)

        layout.addWidget(self._tree)

        # Apply dark theme by default
        self.set_dark_theme(True)

        # Connect signals
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

    def set_dark_theme(self, is_dark: bool):
        """Switch between dark and light appearance."""
        if is_dark:
            hdr_bg = "#181825"
            hdr_fg = "#a6adc8"
            hdr_border = "#313244"
            tree_bg = "#1e1e2e"
            tree_fg = "#cdd6f4"
            sel_bg = "#313244"
            sel_fg = "#cdd6f4"
            hover_bg = "#282840"
        else:
            hdr_bg = "#e8e8e8"
            hdr_fg = "#555555"
            hdr_border = "#d0d0d0"
            tree_bg = "#ffffff"
            tree_fg = "#2c2c2c"
            sel_bg = "#d0e4f6"
            sel_fg = "#2c2c2c"
            hover_bg = "#e8f0fe"

        self.setStyleSheet(f"""
            #TreeHeader {{
                background-color: {hdr_bg};
                color: {hdr_fg};
                font-size: 13px;
                font-weight: bold;
                padding: 4px 8px;
                border-bottom: 1px solid {hdr_border};
            }}
            QTreeWidget {{
                background-color: {tree_bg};
                color: {tree_fg};
                border: none;
                font-size: 13px;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 4px 2px;
                border: none;
            }}
            QTreeWidget::item:selected {{
                background-color: {sel_bg};
                color: {sel_fg};
            }}
            QTreeWidget::item:hover {{
                background-color: {hover_bg};
            }}
        """)

    def get_tree_widget(self) -> QTreeWidget:
        return self._tree

    def get_geometry_root(self) -> TreeItemWithInfo:
        return self._geometry_root

    def get_global_material_root(self) -> TreeItemWithInfo:
        return self._material_global

    def get_local_material_root(self) -> TreeItemWithInfo:
        return self._material_local

    def clear_geometry(self):
        for child in self._geometry_root.takeChildren():
            del child

    def populate_global_materials(self, material_names: list):
        """Populate the Global Materials root with all NIST material children."""
        for child in self._material_global.takeChildren():
            del child
        for name in sorted(material_names):
            child = TreeItemWithInfo(self._material_global, name,
                                     TREE_ITEM_TYPE['GLOBAL_MATERIAL'])
            child.setData(0, Qt.ItemDataRole.UserRole, f"__mat__:{name}")

    def populate_local_materials(self, mat_lib):
        """Populate the Local Materials root from the MaterialsLib."""
        for child in self._material_local.takeChildren():
            del child
        for mat in mat_lib.get_all_local_materials():
            name = mat.mat_name if hasattr(mat, 'mat_name') else mat.name
            child = TreeItemWithInfo(self._material_local, name,
                                     TREE_ITEM_TYPE['LOCAL_MATERIAL'])
            mat_id = mat.mat_id if hasattr(mat, 'mat_id') else getattr(mat, 'mat_id', '')
            child.setData(0, Qt.ItemDataRole.UserRole, f"__local__:{mat_id}")

    def _on_context_menu(self, pos):
        """Right-click context menu for geometry and local materials."""
        item = self._tree.itemAt(pos)
        if item is None:
            return

        # Right-click on a top-level imported geometry item (direct child of Geometry root)
        if item.type() == TREE_ITEM_TYPE['GEO_ROOT'] and item.parent() is self._geometry_root:
            menu = QMenu(self)
            entry_id = item.get_entry_id()
            # Placement before deletion: a file is placed as a whole, so this
            # belongs to the file row and to no row under it. The order is
            # deliberate -- the destructive entry stays at the bottom.
            edit_action = menu.addAction("✏️ Edit Transform...")
            edit_action.triggered.connect(
                lambda: self.edit_transform_requested.emit(entry_id))
            menu.addSeparator()
            del_action = menu.addAction("❌ Delete Geometry")
            del_action.triggered.connect(
                lambda: self.delete_geometry_requested.emit(entry_id))
            menu.exec(self._tree.viewport().mapToGlobal(pos))
            return

        if item is self._material_local:
            menu = QMenu(self)
            add_action = menu.addAction("➕ Add Material...")
            add_action.triggered.connect(self.add_local_material_requested.emit)
            menu.addSeparator()
            save_action = menu.addAction("💾 Save Materials...")
            save_action.triggered.connect(self.save_local_materials_requested.emit)
            load_action = menu.addAction("📂 Load Materials...")
            load_action.triggered.connect(self.load_local_materials_requested.emit)
            menu.exec(self._tree.viewport().mapToGlobal(pos))
        elif item.type() == TREE_ITEM_TYPE['LOCAL_MATERIAL']:
            mat_id = self._extract_local_mat_id(item)
            if not mat_id:
                return
            menu = QMenu(self)
            del_action = menu.addAction("❌ Delete Material")
            menu.addSeparator()
            del_action.triggered.connect(
                lambda: self.remove_local_material_requested.emit(mat_id))
            menu.exec(self._tree.viewport().mapToGlobal(pos))

    @staticmethod
    def _extract_local_mat_id(item):
        data = item.data(0, Qt.ItemDataRole.UserRole) or ""
        if data.startswith("__local__:"):
            return data[10:]
        return ""

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int):
        if item.type() == TREE_ITEM_TYPE['GEO_SOLID']:
            entry_id = item.data(0, Qt.ItemDataRole.UserRole)
            if entry_id:
                self.item_selected.emit(entry_id)
        elif item.type() == TREE_ITEM_TYPE['GLOBAL_MATERIAL']:
            mat_name = item.text(0)
            self.item_selected.emit(f"__mat__:{mat_name}")
        elif item.type() == TREE_ITEM_TYPE['LOCAL_MATERIAL']:
            user_data = item.data(0, Qt.ItemDataRole.UserRole) or ""
            self.item_selected.emit(user_data)

    def _on_item_changed(self, item: QTreeWidgetItem, col: int):
        if col != 0:
            return
        if item.type() not in (TREE_ITEM_TYPE['GEO_ROOT'], TREE_ITEM_TYPE['GEO_SOLID']):
            return

        state = item.checkState(0)

        # Skip PartiallyChecked — it's a side effect of child changes
        if state == Qt.CheckState.PartiallyChecked:
            return

        # Cascade checkbox state to all children (block signals to avoid recursion)
        if item.childCount() > 0:
            self._tree.blockSignals(True)
            self._cascade_check_state(item, state)
            self._tree.blockSignals(False)

        # Emit for every leaf GEO_SOLID under this branch (including self if leaf)
        self._emit_visibility_for_leaves(item, state)

    def _cascade_check_state(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, state)
            self._cascade_check_state(child, state)

    def _emit_visibility_for_leaves(self, item: QTreeWidgetItem, state: Qt.CheckState):
        """Recursively emit visibility signals only for GEO_SOLID leaf items."""
        if item.childCount() == 0:
            # Leaf item — emit visibility if it's a GEO_SOLID with an entry_id
            if item.type() == TREE_ITEM_TYPE['GEO_SOLID']:
                eid = item.data(0, Qt.ItemDataRole.UserRole)
                if eid:
                    self.item_visibility_changed.emit(eid, state == Qt.CheckState.Checked)
            return

        for i in range(item.childCount()):
            self._emit_visibility_for_leaves(item.child(i), state)

    def _expand_all(self, item: QTreeWidgetItem):
        item.setExpanded(True)
        for i in range(item.childCount()):
            self._expand_all(item.child(i))

    def _collapse_all(self, item: QTreeWidgetItem):
        item.setExpanded(False)
        for i in range(item.childCount()):
            self._collapse_all(item.child(i))

    def populate_from_geo_agent(self, geo_agent: 'GeoDataAgent'):
        """Populate the geometry tree from GeoDataAgent file nodes."""
        self.clear_geometry()
        from core.g_data_node import GDataNode
        for file_node in geo_agent.get_all_geo_file_nodes():
            file_item = TreeItemWithInfo(
                self._geometry_root, file_node.name, TREE_ITEM_TYPE['GEO_ROOT'])
            file_item.set_entry_id(file_node.entry_id)
            self._recursive_populate(file_item, file_node)

        # Auto-expand: if total solid count ≤ 20, expand fully; otherwise fold solids
        total_solids = self._count_solid_leaves(self._geometry_root)
        if total_solids <= 20:
            self._expand_all(self._geometry_root)
        else:
            self._geometry_root.setExpanded(True)

    def _count_solid_leaves(self, item: QTreeWidgetItem) -> int:
        """Recursively count GEO_SOLID leaf items under the given item."""
        count = 0
        for i in range(item.childCount()):
            child = item.child(i)
            if child.type() == TREE_ITEM_TYPE['GEO_SOLID'] and child.childCount() == 0:
                count += 1
            elif child.childCount() > 0:
                count += self._count_solid_leaves(child)
        return count

    def _recursive_populate(self, parent_item, parent_node: 'GDataNode'):
        for child in parent_node.children:
            child_item = TreeItemWithInfo(
                parent_item, child.name, TREE_ITEM_TYPE['GEO_SOLID'])
            child_item.set_entry_id(child.entry_id)
            child_item.setData(0, Qt.ItemDataRole.UserRole, child.entry_id)
            child_item.setCheckState(0, Qt.CheckState.Checked)
            child_item.setFlags(child_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self._recursive_populate(child_item, child)

    def focus_on_entry_id(self, entry_id: str):
        def _search(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) == entry_id:
                    return child
                result = _search(child)
                if result:
                    return result
            return None
        item = _search(self._tree.invisibleRootItem())
        if item:
            self._tree.setCurrentItem(item)
            p = item.parent()
            while p:
                p.setExpanded(True)
                p = p.parent()
