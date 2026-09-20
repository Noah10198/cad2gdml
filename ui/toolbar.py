"""
RibbonToolBar - Office-style ribbon toolbar with emoji icons.

Provides 8 action buttons arranged horizontally:
  [Import CAD] [Interference 1 🔌] [Interference 2 ⚡] [Material] [Mesh] [View Mesh] [Export GDML] [Export Mesh] [Dark/Light] ... [Help]

Each button displays an emoji icon above with a text label below,
mimicking the Microsoft Office Ribbon style.

The Mesh button is the one exception: it carries its own state, because a single
always-clickable button let a second MeshRunner be started into the same work
directory while the first one was still writing there
(see doc/remesh_ui_mockup.html §2):

    🔧 Mesh    -> no mesh yet
    🔁 Re-mesh -> a mesh exists
    ⏹ Cancel  -> a job is running; the same button now terminates it

While a job runs every other button is disabled: they would either race the same
work directory or show the result of the previous run.
"""

from typing import Dict, Optional, Tuple

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QSizePolicy
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QFont, QColor


def _create_emoji_icon(emoji: str, size: int = 36, dim: bool = False) -> QIcon:
    """Render emoji at 2x resolution for supersampled crispness.

    `dim` is used for the disabled buttons: Qt greys the label through the
    stylesheet, but an icon pixmap is painted, not styled, so it needs its own
    dimmed pen.
    """
    scale = 2
    px = size * scale
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    font = QFont("Segoe UI Emoji", px - 24)
    painter.setFont(font)
    painter.setPen(QColor(110, 110, 110) if dim else QColor(220, 220, 220))
    _ = painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    _ = painter.end()
    return QIcon(pixmap)


def _ribbon_button(emoji: str, text: str) -> QToolButton:
    """Create a single ribbon-style tool button with icon above and text below."""
    btn = QToolButton()
    btn.setIcon(_create_emoji_icon(emoji))
    btn.setIconSize(QSize(36, 36))
    btn.setText(text)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    btn.setMinimumSize(85, 68)
    btn.setMaximumSize(120, 72)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class RibbonToolBar(QWidget):
    """
    Office-style ribbon toolbar widget.

    Signals are emitted when each button is clicked, allowing
    the MainWindow to connect and handle the actions.
    """

    import_step_clicked = pyqtSignal()
    interference_clicked = pyqtSignal()
    interference2_clicked = pyqtSignal()
    mesh_clicked = pyqtSignal()
    mesh_cancel_clicked = pyqtSignal()   # the same button, in its Cancel state
    view_mesh_clicked = pyqtSignal()
    assign_material_clicked = pyqtSignal()
    export_gdml_clicked = pyqtSignal()
    export_mesh_clicked = pyqtSignal()
    theme_toggled = pyqtSignal()
    help_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonToolBar")
        self._dark_theme = False
        self._build_ui()
        self._apply_theme(False)

    def _build_ui(self):
        """Construct the horizontal button layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)

        # Define button spec: (key, emoji, label, signal)
        # The Mesh entry has no signal of its own: it switches between Mesh /
        # Re-mesh / Cancel, so it goes through _on_mesh_clicked() instead.
        buttons = [
            ("import", "📂", "Import CAD", self.import_step_clicked),
            ("interference1", "🔌", "Interference 1", self.interference_clicked),
            ("interference2", "⚡", "Interference 2", self.interference2_clicked),
            ("material", "🧪", "Material", self.assign_material_clicked),
            ("mesh", "🔧", "Mesh", None),
            ("view_mesh", "👁", "View Mesh", self.view_mesh_clicked),
            ("export_gdml", "📦", "Export GDML", self.export_gdml_clicked),
            ("export_mesh", "📤", "Export Mesh", self.export_mesh_clicked),
        ]

        self._buttons: Dict[str, QToolButton] = {}
        self._button_emoji: Dict[str, str] = {}
        for key, emoji, label, signal in buttons:
            btn = _ribbon_button(emoji, label)
            if signal is not None:
                _ = btn.clicked.connect(signal.emit)
            self._buttons[key] = btn
            self._button_emoji[key] = emoji
            layout.addWidget(btn)

        self._mesh_btn = self._buttons["mesh"]
        self._mesh_state = "mesh"
        self._running = False
        _ = self._mesh_btn.clicked.connect(self._on_mesh_clicked)
        self.set_mesh_state("mesh")

        # Push right-side buttons (theme + help)
        layout.addStretch()

        self._theme_btn = _ribbon_button("🌙", "Dark")
        self._theme_btn.setObjectName("ThemeToggle")
        _ = self._theme_btn.clicked.connect(self.theme_toggled.emit)
        layout.addWidget(self._theme_btn)

        help_btn = _ribbon_button("❓", "Help")
        _ = help_btn.clicked.connect(self.help_clicked.emit)
        layout.addWidget(help_btn)

    # ---- Mesh button: three states ----

    def _on_mesh_clicked(self):
        """Mesh / Re-mesh / Cancel -- decided by the current state."""
        if self._mesh_state == "cancel":
            self.mesh_cancel_clicked.emit()
        else:
            self.mesh_clicked.emit()

    def set_mesh_state(self, state: str):
        """`mesh` (nothing meshed yet) / `remesh` (a mesh exists) / `cancel`
        (a job is running). The state lives on the button so the user never has
        to ask "have I already meshed this?" -- and so a second job cannot be
        started into the same work directory."""
        self._mesh_state = state
        if state == "cancel":
            icon, label = "⏹", "Cancel"
            tip = "Terminate the current gmsh job"
        elif state == "remesh":
            icon, label = "🔁", "Re-mesh"
            tip = "Mesh again: choose the groups and the parameters to re-run"
        else:
            icon, label = "🔧", "Mesh"
            tip = "Generate the mesh for the whole model"
        self._mesh_btn.setIcon(_create_emoji_icon(icon))
        self._mesh_btn.setText(label)
        self._mesh_btn.setToolTip(tip)
        self._style_mesh_button()

    def _style_mesh_button(self):
        """Only Cancel gets a colour of its own; the other two states keep the
        theme look (no new palette, cf. doc/remesh_ui_mockup.html §2)."""
        if self._mesh_state == "cancel":
            self._mesh_btn.setStyleSheet(
                "QToolButton { border: 1px solid #f38ba8; color: #f38ba8; "
                "background-color: #31242a; }")
        else:
            self._mesh_btn.setStyleSheet("")

    def set_running(self, running: bool):
        """Disable everything that must not be touched while a job runs."""
        self._running = running
        for key, btn in self._buttons.items():
            if key == "mesh":
                continue
            btn.setEnabled(not running)
            btn.setIcon(_create_emoji_icon(self._button_emoji[key], dim=running))
        self._theme_btn.setEnabled(not running)

    def set_dark_theme(self, is_dark: bool):
        """Switch the toolbar between dark and light appearance."""
        self._dark_theme = is_dark
        self._apply_theme(is_dark)
        emoji = "🌙" if is_dark else "☀️"
        label = "Dark" if is_dark else "Light"
        self._theme_btn.setIcon(_create_emoji_icon(emoji))
        self._theme_btn.setText(label)

    def _apply_theme(self, dark: bool):
        """Apply stylesheet based on current theme mode."""
        if dark:
            bg = "#1e1e2e"
            border = "#313244"
            btn_text = "#cdd6f4"
            btn_hover = "#313244"
            btn_hover_border = "#45475a"
            btn_pressed = "#45475a"
            btn_dim = "#6c7086"
        else:
            bg = "#f5f5f5"
            border = "#d0d0d0"
            btn_text = "#2c2c2c"
            btn_hover = "#e0e0e0"
            btn_hover_border = "#c0c0c0"
            btn_pressed = "#cccccc"
            btn_dim = "#a8a8a8"

        self.setStyleSheet(f"""
            #RibbonToolBar {{
                background-color: {bg};
                border-bottom: 2px solid {border};
                min-height: 72px;
            }}
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
                padding: 3px 10px;
                color: {btn_text};
                font-size: 12px;
                font-family: "Segoe UI", "Arial", sans-serif;
            }}
            QToolButton:hover {{
                background-color: {btn_hover};
                border: 1px solid {btn_hover_border};
            }}
            QToolButton:pressed {{
                background-color: {btn_pressed};
            }}
            QToolButton:disabled {{
                color: {btn_dim};
            }}
        """)
