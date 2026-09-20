"""
GeoParamWidget - Property panel for displaying geometry parameters.

Shows properties of the currently selected item.
Supports three display modes:
  - "geometry" : all 5 groups (General, Position, BBox, Dimensions, Material)
  - "global_material" : only General (NIST info)
  - "local_material"  : General + Composition detail
"""

from typing import Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout,
    QDoubleSpinBox, QScrollArea, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from ui.occ_widget import WidgetOCC
    from core.geo_data_agent import GeoDataAgent


class GeoParamWidget(QWidget):
    """
    Property panel for inspecting selected node attributes.
    Dynamically switches display mode based on selected item type.
    """

    def __init__(self, occ_widget: 'WidgetOCC' = None,
                 geo_agent: 'GeoDataAgent' = None, parent=None):
        super().__init__(parent)
        self._occ_widget = occ_widget
        self._geo_agent = geo_agent
        self._dark_theme = True
        self._current_node = None
        self._mode = "geometry"  # "geometry" | "global_material" | "local_material"
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
        self._info_group = QGroupBox("General")
        info_layout = QFormLayout(self._info_group)
        info_layout.setSpacing(4)

        self._name_label = QLabel("-")
        self._name_label.setWordWrap(True)
        info_layout.addRow("Name:", self._name_label)

        self._type_label = QLabel("-")
        self._type_label.setWordWrap(True)
        info_layout.addRow("Type:", self._type_label)

        self._entry_id_label = QLabel("-")
        self._entry_id_label.setWordWrap(True)
        info_layout.addRow("Entry ID:", self._entry_id_label)

        layout.addWidget(self._info_group)

        # ===== Material detail group (hidden by default, shown for materials) =====
        self._mat_detail_group = QGroupBox("Material Details")
        mat_detail_layout = QVBoxLayout(self._mat_detail_group)
        mat_detail_layout.setSpacing(4)

        self._density_label = QLabel("-")
        mat_detail_layout.addWidget(self._density_label)

        self._composition_label = QLabel("-")
        self._composition_label.setWordWrap(True)
        mat_detail_layout.addWidget(self._composition_label)

        self._mat_detail_group.setVisible(False)
        layout.addWidget(self._mat_detail_group)

        # ===== Position / Center group =====
        self._pos_group = QGroupBox("Position")
        pos_layout = QFormLayout(self._pos_group)
        pos_layout.setSpacing(4)

        self._location_label = QLabel("-")
        pos_layout.addRow("Center:", self._location_label)

        layout.addWidget(self._pos_group)

        # ===== Bounding Box group =====
        self._bbox_group = QGroupBox("Bounding Box")
        bbox_layout = QFormLayout(self._bbox_group)
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

        layout.addWidget(self._bbox_group)

        # ===== Dimensions group =====
        self._dim_group = QGroupBox("Dimensions")
        dim_layout = QFormLayout(self._dim_group)
        dim_layout.setSpacing(4)

        self._bbox_size_label = QLabel("-")
        dim_layout.addRow("Size (XYZ):", self._bbox_size_label)

        self._volume_label = QLabel("-")
        dim_layout.addRow("Volume:", self._volume_label)

        layout.addWidget(self._dim_group)

        # ===== Material group =====
        self._mat_group = QGroupBox("Material")
        mat_layout = QFormLayout(self._mat_group)
        mat_layout.setSpacing(4)

        self._material_label = QLabel("None")
        mat_layout.addRow("Assigned:", self._material_label)

        layout.addWidget(self._mat_group)

        layout.addStretch()

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    # ── Mode switching ──────────────────────────────────────────────────────

    def _switch_to_geometry_mode(self):
        """Show all geometry-related groups, hide material detail."""
        self._mode = "geometry"
        self._pos_group.setVisible(True)
        self._bbox_group.setVisible(True)
        self._dim_group.setVisible(True)
        self._mat_group.setVisible(True)
        self._mat_detail_group.setVisible(False)

    def _switch_to_material_mode(self, subtype: str = ""):
        """
        Show only General + Material Details group.
        Hide geometry-specific groups.
        """
        self._mode = f"material_{subtype}" if subtype else "material"
        self._pos_group.setVisible(False)
        self._bbox_group.setVisible(False)
        self._dim_group.setVisible(False)
        self._mat_group.setVisible(False)
        self._mat_detail_group.setVisible(True)

    # ── Data display methods ────────────────────────────────────────────────

    def set_curr_tree_id(self, entry_id: str):
        """Set the current selected node by entry_id and refresh its data."""
        if self._geo_agent is None:
            return
        node = self._geo_agent.convert_entry_id_to_node(entry_id)
        self._current_node = node
        self._fresh_from_data_model()

    def refresh_node(self, node) -> None:
        """Re-read the fields if `node` is the one on display.

        The box, centre and size are measured off the shape as it stands at the
        moment of the read, so a part that has been moved since the last read
        has to be measured again -- otherwise the panel goes on describing where
        it used to be. That read is not cheap, so it only happens on demand: on
        selection here, and on the placement that is kept (see
        MainWindow._slot_edit_transform).
        """
        if node is not None and self._current_node is node:
            self._fresh_from_data_model()

    def _fresh_from_data_model(self):
        """Refresh all property fields from the current node."""
        if self._current_node is None:
            self.clear()
            return

        self._switch_to_geometry_mode()
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
        self._switch_to_geometry_mode()
        self._name_label.setText(name or "-")
        self._type_label.setText(node_type or "-")
        self._entry_id_label.setText(entry_id or "-")
        self._material_label.setText(material or "None")

    def show_material_reference(self, mat_name: str):
        """Display NIST material reference info — material mode, no geo groups."""
        self._current_node = None
        self._switch_to_material_mode("nist")
        self._name_label.setText(mat_name)
        self._type_label.setText("NIST Material")
        self._entry_id_label.setText("-")
        self._density_label.setText("")

        ref_text = (
            "Please refer to the <b>Geant4 User's Guide</b><br>"
            "or visit the NIST Material Database:<br>"
            "<a style='color:#89b4fa;' "
            "href='https://physics.nist.gov/cuu/Constants/'>"
            "https://physics.nist.gov/cuu/Constants/</a>"
        )
        self._composition_label.setText(ref_text)
        self._composition_label.setTextFormat(Qt.TextFormat.RichText)
        self._composition_label.setOpenExternalLinks(True)

    def show_local_material_info(self, mat):
        """Display local material details — material mode with composition info."""
        self._current_node = None
        cat = mat.mat_cate.value if hasattr(mat, 'mat_cate') else "Unknown"
        name = mat.mat_name if hasattr(mat, 'mat_name') else mat.name
        self._switch_to_material_mode(cat.lower())
        self._name_label.setText(name)
        self._type_label.setText(f"Local Material — {cat}")
        self._entry_id_label.setText(mat.mat_id if hasattr(mat, 'mat_id') else "-")

        # Density line
        density_lines = []
        if hasattr(mat, 'density'):
            unit = getattr(mat, 'unit', 'g/cm³')
            density_lines.append(f"Density: <b>{mat.density}</b> {unit}")
        if hasattr(mat, 'symbol'):
            density_lines.append(f"Symbol: <b>{mat.symbol}</b>")
        if hasattr(mat, 'number'):
            density_lines.append(f"Z (Atomic Number): <b>{int(mat.number)}</b>")
        if hasattr(mat, 'quality'):
            density_lines.append(f"Atomic Mass: <b>{mat.quality}</b>")
        self._density_label.setText("<br>".join(density_lines) if density_lines else "")
        self._density_label.setTextFormat(Qt.TextFormat.RichText)

        # Composition table
        if hasattr(mat, 'items') and mat.items:
            comp_lines = ["<b>Composition:</b>"]
            comp_lines.append(
                "<table style='margin-top:4px; border-collapse:collapse;'>"
                "<tr><th style='padding:2px 12px 2px 0; text-align:left;'>Element</th>"
                "<th style='padding:2px 12px; text-align:left;'>Ratio</th>"
                "<th style='padding:2px 0; text-align:left;'>Z</th></tr>"
            )
            for item in mat.items:
                elem = item.element_name if hasattr(item, 'element_name') else "?"
                ratio = item.ratio if hasattr(item, 'ratio') else 0
                z_val = int(item.z) if hasattr(item, 'z') else "-"
                comp_lines.append(
                    f"<tr><td style='padding:2px 12px 2px 0;'>{elem}</td>"
                    f"<td style='padding:2px 12px;'>{ratio}</td>"
                    f"<td style='padding:2px 0;'>{z_val}</td></tr>"
                )
            comp_lines.append("</table>")
            self._composition_label.setText("\n".join(comp_lines))
            self._composition_label.setTextFormat(Qt.TextFormat.RichText)
        else:
            self._composition_label.setText("(no composition data)")
            self._composition_label.setTextFormat(Qt.TextFormat.PlainText)

    def clear(self):
        """Clear all property fields and show geometry mode by default."""
        self._switch_to_geometry_mode()
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
        self._density_label.setText("-")
        self._composition_label.setText("-")

    # ── Theming ─────────────────────────────────────────────────────────────

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
            link_color = "#89b4fa"
            table_th_fg = "#a6adc8"
        else:
            bg = "#f5f5f5"
            hdr_fg = "#2c2c2c"
            grp_fg = "#555555"
            grp_border = "#d0d0d0"
            lbl_fg = "#2c2c2c"
            chk_fg = "#2c2c2c"
            spin_bg = "#ffffff"
            spin_fg = "#2c2c2c"
            link_color = "#0078d4"
            table_th_fg = "#555555"

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
            a {{
                color: {link_color};
            }}
            table th {{
                color: {table_th_fg};
                font-weight: bold;
            }}
        """)
