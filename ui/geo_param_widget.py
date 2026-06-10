"""
GeoParamWidget - Property panel for displaying geometry parameters.

Shows properties of the currently selected geometry item,
including name, bounding box coordinates, center position,
dimensions, material, and visibility controls.
"""

from typing import Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout,
    QDoubleSpinBox, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from ui.occ_widget import WidgetOCC
    from core.geo_data_agent import GeoDataAgent


class GeoParamWidget(QWidget):
    """
    Property panel for inspecting selected geometry node attributes.

    Displays read-only properties (name, bounding box coordinates,
    center position, volume) and provides controls for visibility toggling.
    """

    def __init__(self, occ_widget: 'WidgetOCC' = None,
                 geo_agent: 'GeoDataAgent' = None, parent=None):
        super().__init__(parent)
        self._occ_widget = occ_widget
        self._geo_agent = geo_agent
        self._dark_theme = True
        self._current_node = None
        self._setup_ui()
        self.set_dark_theme(True)

    def set_occ_widget(self, occ_widget: 'WidgetOCC'):
        self._occ_widget = occ_widget

    def set_geo_agent(self, geo_agent: 'GeoDataAgent'):
        self._geo_agent = geo_agent

    def _setup_ui(self):
        """Build the property panel layout."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        # Store references so set_dark_theme() can update them
        self._scroll_viewport = scroll.viewport()

        content = QWidget()
        content.setObjectName("PropContent")
        self._prop_content = content
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        header = QLabel("Properties")
        header.setObjectName("PropHeader")
        layout.addWidget(header)

        # ===== General info group =====
        info_group = QGroupBox("General")
        info_layout = QFormLayout(info_group)
        info_layout.setSpacing(4)

        self._name_label = QLabel("-")
        self._name_label.setWordWrap(True)
        info_layout.addRow("Name:", self._name_label)

        self._type_label = QLabel("-")
        info_layout.addRow("Type:", self._type_label)

        self._entry_id_label = QLabel("-")
        self._entry_id_label.setWordWrap(True)
        info_layout.addRow("Entry ID:", self._entry_id_label)

        layout.addWidget(info_group)

        # ===== Position / Center group =====
        pos_group = QGroupBox("Position")
        pos_layout = QFormLayout(pos_group)
        pos_layout.setSpacing(4)

        self._location_label = QLabel("-")
        pos_layout.addRow("Center:", self._location_label)

        layout.addWidget(pos_group)

        # ===== Bounding Box group =====
        bbox_group = QGroupBox("Bounding Box")
        bbox_layout = QFormLayout(bbox_group)
        bbox_layout.setSpacing(4)

        # Min values (read-only)
        min_form = QFormLayout()
        min_form.setSpacing(2)
        self._min_x_spin = QDoubleSpinBox()
        self._min_x_spin.setDecimals(3); self._min_x_spin.setReadOnly(True)
        self._min_x_spin.setRange(-1e9, 1e9)
        self._min_x_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        min_form.addRow("X:", self._min_x_spin)

        self._min_y_spin = QDoubleSpinBox()
        self._min_y_spin.setDecimals(3); self._min_y_spin.setReadOnly(True)
        self._min_y_spin.setRange(-1e9, 1e9)
        self._min_y_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        min_form.addRow("Y:", self._min_y_spin)

        self._min_z_spin = QDoubleSpinBox()
        self._min_z_spin.setDecimals(3); self._min_z_spin.setReadOnly(True)
        self._min_z_spin.setRange(-1e9, 1e9)
        self._min_z_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        min_form.addRow("Z:", self._min_z_spin)

        bbox_layout.addRow("Min:", min_form)

        # Max values (read-only)
        max_form = QFormLayout()
        max_form.setSpacing(2)
        self._max_x_spin = QDoubleSpinBox()
        self._max_x_spin.setDecimals(3); self._max_x_spin.setReadOnly(True)
        self._max_x_spin.setRange(-1e9, 1e9)
        self._max_x_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        max_form.addRow("X:", self._max_x_spin)

        self._max_y_spin = QDoubleSpinBox()
        self._max_y_spin.setDecimals(3); self._max_y_spin.setReadOnly(True)
        self._max_y_spin.setRange(-1e9, 1e9)
        self._max_y_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        max_form.addRow("Y:", self._max_y_spin)

        self._max_z_spin = QDoubleSpinBox()
        self._max_z_spin.setDecimals(3); self._max_z_spin.setReadOnly(True)
        self._max_z_spin.setRange(-1e9, 1e9)
        self._max_z_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        max_form.addRow("Z:", self._max_z_spin)

        bbox_layout.addRow("Max:", max_form)

        layout.addWidget(bbox_group)

        # ===== Dimensions group =====
        dim_group = QGroupBox("Dimensions")
        dim_layout = QFormLayout(dim_group)
        dim_layout.setSpacing(4)

        self._bbox_size_label = QLabel("-")
        dim_layout.addRow("Size (XYZ):", self._bbox_size_label)

        self._volume_label = QLabel("-")
        dim_layout.addRow("Volume:", self._volume_label)

        layout.addWidget(dim_group)

        # ===== Material group =====
        mat_group = QGroupBox("Material")
        mat_layout = QFormLayout(mat_group)
        mat_layout.setSpacing(4)

        self._material_label = QLabel("None")
        mat_layout.addRow("Assigned:", self._material_label)

        layout.addWidget(mat_group)

        layout.addStretch()

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def set_dark_theme(self, is_dark: bool):
        """Switch between dark and light appearance."""
        self._dark_theme = is_dark
        if is_dark:
            bg = "#1e1e2e"
            hdr_fg = "#cdd6f4"
            grp_fg = "#a6adc8"
            grp_border = "#313244"
            lbl_fg = "#cdd6f4"
            chk_fg = "#cdd6f4"
            spin_bg = "#313244"
            spin_fg = "#cdd6f4"
        else:
            bg = "#f5f5f5"
            hdr_fg = "#2c2c2c"
            grp_fg = "#555555"
            grp_border = "#d0d0d0"
            lbl_fg = "#2c2c2c"
            chk_fg = "#2c2c2c"
            spin_bg = "#ffffff"
            spin_fg = "#2c2c2c"

        # Update scroll viewport and content widget backgrounds directly
        self._scroll_viewport.setStyleSheet(f"background-color: {bg};")
        self._prop_content.setStyleSheet(f"#PropContent {{ background-color: {bg}; }}")

        self.setStyleSheet(f"""
            #PropHeader {{
                font-size: 14px;
                font-weight: bold;
                color: {hdr_fg};
                padding: 4px 0px;
            }}
            QGroupBox {{
                font-size: 13px;
                font-weight: bold;
                color: {grp_fg};
                border: 1px solid {grp_border};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 16px;
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 8px;
                color: {grp_fg};
            }}
            QLabel {{
                color: {lbl_fg};
                font-size: 12px;
            }}
            QCheckBox {{
                color: {chk_fg};
                font-size: 12px;
            }}
            QScrollArea {{
                background-color: {bg};
                border: none;
            }}
            QDoubleSpinBox {{
                background-color: {spin_bg};
                color: {spin_fg};
                border: 1px solid {grp_border};
                border-radius: 3px;
                padding: 1px 4px;
                font-size: 11px;
            }}
        """)

    def set_curr_tree_id(self, entry_id: str):
        """Set the current selected node by entry_id and refresh its data."""
        if self._geo_agent is None:
            return
        node = self._geo_agent.convert_entry_id_to_node(entry_id)
        self._current_node = node
        self._fresh_from_data_model()

    def _fresh_from_data_model(self):
        """Refresh all property fields from the current node."""
        if self._current_node is None:
            self.clear()
            return

        self._name_label.setText(self._current_node.name or "-")
        self._type_label.setText(self._current_node.node_type.name if self._current_node.node_type else "-")
        self._entry_id_label.setText(self._current_node.entry_id or "-")
        self._material_label.setText(self._current_node.material_name or "None")

        self._fresh_geo_location()

    def _fresh_geo_location(self):
        """Recalculate and display bounding box / center from the AIS shape."""
        if self._occ_widget is None:
            return
        if self._current_node is None or self._current_node.ais_shape is None:
            self._location_label.setText("-")
            self._min_x_spin.setValue(0); self._min_y_spin.setValue(0); self._min_z_spin.setValue(0)
            self._max_x_spin.setValue(0); self._max_y_spin.setValue(0); self._max_z_spin.setValue(0)
            self._bbox_size_label.setText("-")
            self._volume_label.setText("-")
            return

        bbox = self._occ_widget.compute_shape_bounding_box(
            self._current_node.ais_shape
        )
        if bbox is None:
            return

        min_x, min_y, min_z, max_x, max_y, max_z = bbox

        # Update min spinboxes
        self._min_x_spin.setValue(min_x)
        self._min_y_spin.setValue(min_y)
        self._min_z_spin.setValue(min_z)

        # Update max spinboxes
        self._max_x_spin.setValue(max_x)
        self._max_y_spin.setValue(max_y)
        self._max_z_spin.setValue(max_z)

        # Center coordinate
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        center_z = (min_z + max_z) / 2.0
        self._location_label.setText(
            f"({center_x:.1f}, {center_y:.1f}, {center_z:.1f})"
        )

        # Dimensions (bounding box size)
        size_x = max_x - min_x
        size_y = max_y - min_y
        size_z = max_z - min_z
        self._bbox_size_label.setText(
            f"({size_x:.2f}, {size_y:.2f}, {size_z:.2f})"
        )

        # Approximate volume
        volume = size_x * size_y * size_z
        self._volume_label.setText(f"{volume:.2f}")

    def set_properties(self, name: str = "", node_type: str = "",
                       entry_id: str = "", bbox: str = "",
                       volume: str = "", material: str = "None"):
        """Simple property setter (kept for backward compatibility)."""
        self._name_label.setText(name or "-")
        self._type_label.setText(node_type or "-")
        self._entry_id_label.setText(entry_id or "-")
        self._material_label.setText(material or "None")

    def clear(self):
        """Clear all property fields."""
        self._current_node = None
        self._name_label.setText("-")
        self._type_label.setText("-")
        self._entry_id_label.setText("-")
        self._location_label.setText("-")
        self._min_x_spin.setValue(0); self._min_y_spin.setValue(0); self._min_z_spin.setValue(0)
        self._max_x_spin.setValue(0); self._max_y_spin.setValue(0); self._max_z_spin.setValue(0)
        self._bbox_size_label.setText("-")
        self._volume_label.setText("-")
        self._material_label.setText("None")
